"""Integration tests through the HTTP API (FastAPI TestClient, SQLite, fake models)."""
from __future__ import annotations

import io
import json

from PIL import Image

from backend.services.llm import set_llm
from backend.tests.conftest import make_docx, make_pdf

ADMIN = {"X-Admin-Key": "test-admin"}


def test_health_reports_components(client):
    body = client.get("/api/health").json()
    assert set(body["checks"]) == {"database", "vector_index", "llm", "embeddings"}
    assert body["checks"]["database"]["ok"] is True
    assert "test-admin" not in json.dumps(body)


def test_grounded_answer_with_citations(client, seeded):
    r = client.post("/api/chat", json={"message": "How is attendance marked by the faculty?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["grounded"] is True
    assert body["answer"] == body["response"]  # field kept for older clients
    assert body["sources"] and body["sources"][0]["source_type"] == "help_portal"
    assert body["sources"][0]["url"].startswith("http://help.synchronik.co.in/attendance")
    assert body["confidence"]["level"] in {"high", "medium", "low"}
    assert body["message_id"] > 0 and body["query_id"]
    assert body["metadata"]["model"] == "fake-llm"
    # the system prompt is sent separately from the retrieved data
    system, turns = seeded["llm"].calls[-1]
    assert "untrusted reference DATA" in system and "<sources>" in turns[-1].text


def test_out_of_scope_is_refused_without_calling_llm_in_docs_only_mode(client, seeded, monkeypatch):
    from backend.core.config import get_settings

    monkeypatch.setattr(get_settings(), "general_answers", False)
    calls_before = len(seeded["llm"].calls)
    body = client.post("/api/chat", json={"message": "Who won the football world cup in 1998?"}).json()
    assert body["grounded"] is False and body["sources"] == []
    assert body["intent"] == "out_of_scope"
    assert body["confidence"]["level"] == "none"
    assert len(seeded["llm"].calls) == calls_before


def test_greeting_skips_retrieval(client, seeded):
    body = client.post("/api/chat", json={"message": "Hello"}).json()
    assert body["intent"] == "greeting" and body["retrieval_count"] == 0


def test_follow_up_is_rewritten_with_history(client, seeded):
    first = client.post("/api/chat", json={"message": "How is attendance marked by the faculty?"}).json()
    second = client.post("/api/chat", json={"message": "Can I edit it later?",
                                            "conversation_id": first["conversation_id"]}).json()
    assert second["intent"] == "follow_up"
    assert second["rewritten_query"]
    conv = client.get(f"/api/conversations/{first['conversation_id']}").json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant", "user", "assistant"]
    assert conv["title"].startswith("How is attendance")


def test_streaming_emits_real_events(client, seeded):
    with client.stream("POST", "/api/chat/stream", json={"message": "How is attendance marked?"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        raw = "".join(r.iter_text())
    events = [blk.split("\n")[0].removeprefix("event: ") for blk in raw.strip().split("\n\n")]
    assert events[0] == "status" and "meta" in events and events[-1] == "done"
    assert events.count("token") > 3  # streamed in pieces
    done = json.loads(raw.strip().split("\n\n")[-1].split("data: ", 1)[1])
    assert done["sources"]


def test_extractive_fallback_without_llm(client, seeded):
    set_llm(None)
    body = client.post("/api/chat", json={"message": "How is attendance marked by the faculty?"}).json()
    assert body["metadata"]["model"] == "extractive-fallback"
    assert "not enabled on this server" in body["answer"] and body["sources"]
    assert "GEMINI_API_KEY" not in body["answer"]  # no configuration details shown to users


def test_v1_compat_endpoint(client, seeded):
    r = client.post("/chat", json={"session_id": "demouser", "message": "How is attendance marked?"})
    assert r.status_code == 200 and r.json()["session_id"] == "demouser"


def test_validation_errors_use_envelope(client):
    r = client.post("/api/chat", json={"message": "   "})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert "X-Request-ID" in r.headers


def test_feedback_new_and_legacy(client, seeded):
    body = client.post("/api/chat", json={"message": "How is attendance marked?"}).json()
    r = client.post("/api/feedback", json={"message_id": body["message_id"], "rating": "negative",
                                           "reason": "missing_info", "comment": "no screenshots"})
    assert r.status_code == 200
    conv = client.get(f"/api/conversations/{body['conversation_id']}").json()
    assert conv["messages"][-1]["feedback"] == "negative"
    assert client.post("/feedback", json={"question": "q", "answer": "a", "feedback_type": "positive"}).status_code == 200
    stats = client.get("/api/admin/analytics", headers=ADMIN).json()
    assert stats["feedback"] == {"positive": 1, "negative": 1, "positive_rate": 0.5, "reasons": {"missing_info": 1}}
    assert stats["total_queries"] == 1


def test_conversation_search_rename_export_delete(client, seeded):
    cid = client.post("/api/chat", json={"message": "Tell me about library circulation fines"}).json()["conversation_id"]
    assert any(c["id"] == cid for c in client.get("/api/conversations", params={"q": "circulation"}).json())
    assert client.get("/api/conversations", params={"q": "zzz-nothing"}).json() == []
    assert client.patch(f"/api/conversations/{cid}", json={"title": "Library"}).json()["title"] == "Library"
    md = client.get(f"/api/conversations/{cid}/export").text
    assert md.startswith("# Library") and "**Sources**" in md
    assert client.delete(f"/api/conversations/{cid}").status_code == 204
    assert client.get(f"/api/conversations/{cid}").status_code == 404


def test_admin_routes_require_key(client):
    assert client.get("/api/admin/stats").status_code == 401
    assert client.get("/api/admin/stats", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert client.post("/api/documents", files={"file": ("a.pdf", make_pdf(["x"]))}).status_code == 401
    assert client.get("/api/admin/stats", headers=ADMIN).status_code == 200


def test_admin_upload_reprocess_delete(client, app_env):
    pdf = make_pdf(["Hostel allotment is done by the warden", "Hostel fees are paid each semester"])
    r = client.post("/api/documents", headers=ADMIN, files={"file": ("../../hostel.pdf", pdf, "application/pdf")})
    assert r.status_code == 201, r.text
    doc = r.json()["document"]
    assert doc["status"] == "ready" and doc["chunk_count"] == 2 and doc["title"] == "hostel.pdf"
    hits = client.get("/api/search", params={"q": "hostel allotment warden"}).json()["results"]
    assert hits and hits[0]["page"] == 1
    assert client.post(f"/api/documents/{doc['id']}/reprocess", headers=ADMIN).json()["chunks"] == 2
    assert client.delete(f"/api/documents/{doc['id']}", headers=ADMIN).status_code == 204
    assert client.get("/api/search", params={"q": "hostel allotment warden"}).json()["results"] == []
    assert app_env["index"].size == 0


def test_upload_rejects_spoofed_and_oversized_files(client, monkeypatch):
    exe = b"MZ" + b"\0" * 100
    r = client.post("/api/documents", headers=ADMIN, files={"file": ("report.pdf", exe, "application/pdf")})
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_file"
    from backend.core.config import get_settings
    monkeypatch.setattr(get_settings(), "max_document_mb", 0)
    r = client.post("/api/documents", headers=ADMIN, files={"file": ("a.pdf", make_pdf(["x"]))})
    assert r.status_code == 413


def test_attachment_is_scoped_to_its_conversation(client, app_env):
    docx = make_docx([("Transport", "Heading 1"), ("Bus route 7 leaves the campus at 5 pm daily.", None)])
    r = client.post("/api/chat/attachments", files={"file": ("routes.docx", docx)})
    assert r.status_code == 200, r.text
    cid = r.json()["conversation_id"]
    own = client.post("/api/chat", json={"message": "When does bus route 7 leave the campus?", "conversation_id": cid}).json()
    other = client.post("/api/chat", json={"message": "When does bus route 7 leave the campus?"}).json()
    assert own["grounded"] and own["sources"][0]["source_type"] == "attachment"
    assert other["grounded"] is False  # not visible from another conversation
    assert client.get("/api/documents").json() == []  # never listed in the global KB


def test_image_chat(client):
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, format="PNG")
    r = client.post("/api/chat/image", data={"question": "What screen is this?"},
                    files={"file": ("shot.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["intent"] == "image_question" and "Attendance" in r.json()["answer"]
    bad = client.post("/api/chat/image", data={"question": "?"}, files={"file": ("x.png", b"\x89PNG\r\n\x1a\nbroken")})
    assert bad.status_code == 415


def test_attachment_questions_see_the_whole_document(client, seeded):
    from backend.services import context_builder as cb

    docx = make_docx([("Circular 14/2026", "Heading 1"),
                      ("Issued by the Controller of Examinations.", None),
                      ("The condonation fee for attendance below 75% is Rs. 500.", None)])
    cid = client.post("/api/chat/attachments", files={"file": ("circular.docx", docx)}).json()["conversation_id"]
    assert client.get(f"/api/conversations/{cid}").json()["title"] == "Attached circular.docx"  # no Markdown
    llm = seeded["llm"]

    # A question pointing at the document, and a vague follow-up that retrieval alone would not match.
    for q in ("summarise this document", "who issued it?"):
        body = client.post("/api/chat", json={"message": q, "conversation_id": cid}).json()
        system, turns = llm.calls[-1]
        assert system == cb.ATTACHMENT_SYSTEM_PROMPT and body["intent"] == "attachment_question"
        assert 'type="attachment"' in turns[-1].text and "Rs. 500" in turns[-1].text
        assert "Controller of Examinations" in turns[-1].text and turns[-1].text.endswith(f"Question: {q}")
        if q.startswith("summarise"):  # explicitly about the document: no help-portal pages mixed in
            assert 'type="documentation"' not in turns[-1].text
        assert body["sources"] and body["sources"][0]["source_type"] == "attachment"

    # An ERP how-to question in the same conversation also gets the matching help-portal pages.
    client.post("/api/chat", json={"message": "How is attendance marked by the faculty?", "conversation_id": cid})
    assert 'type="documentation"' in llm.calls[-1][1][-1].text


def test_image_answer_uses_matching_documentation(client, seeded):
    from backend.services import context_builder as cb
    from backend.tests.conftest import FakeLLM

    class ImageLLM(FakeLLM):
        def __init__(self):
            super().__init__()
            self.image_prompts = []

        def describe_image(self, system, question, image_bytes, mime):
            self.image_prompts.append(question)
            if question == cb.IMAGE_READ_PROMPT:
                return "Attendance Entry screen. Error: attendance is marked per lecture by the faculty."
            return "This is the attendance screen. Attendance is marked per lecture by the faculty [1]."

    llm = ImageLLM()
    set_llm(llm)
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, format="PNG")
    body = client.post("/api/chat/image", data={"question": "What does this mean and how do I fix it?"},
                       files={"file": ("shot.png", buf.getvalue(), "image/png")}).json()
    assert llm.image_prompts[0] == cb.IMAGE_READ_PROMPT  # the image is read first ...
    assert "<sources>" in llm.image_prompts[1]  # ... and the answer sees the documentation found for it
    assert body["grounded"] is True and body["sources"][0]["source_type"] == "help_portal"


def test_vision_falls_back_to_the_answer_model_when_overloaded():
    from types import SimpleNamespace

    from backend.services.llm import GeminiProvider

    used = []

    def generate_content(model, contents, config):
        used.append(model)
        if model == "vision":
            raise RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")
        return SimpleNamespace(text="A white square.")

    p = GeminiProvider.__new__(GeminiProvider)
    p.model, p.vision_model = "answer", "vision"
    p._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    assert p.describe_image("sys", "What is this?", b"img", "image/png") == "A white square."
    assert used == ["vision", "answer"]


def test_regenerate_replaces_last_answer(client, seeded):
    first = client.post("/api/chat", json={"message": "How is attendance marked?"}).json()
    again = client.post("/api/chat/regenerate", json={"conversation_id": first["conversation_id"]}).json()
    msgs = client.get(f"/api/conversations/{first['conversation_id']}").json()["messages"]
    assert len(msgs) == 2 and msgs[-1]["id"] == again["message_id"]


def test_rate_limit(client, monkeypatch):
    from backend.core.config import get_settings
    monkeypatch.setattr(get_settings(), "rate_limit_chat_per_min", 2)
    codes = [client.post("/api/chat", json={"message": "hello"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_crawler_change_detection(app_env):
    from backend.services.document_processing import extract_html
    from backend.services.ingestion import upsert_web_page
    from backend.tests.conftest import ATTENDANCE_PAGE

    title, sections = extract_html(ATTENDANCE_PAGE)
    assert upsert_web_page("http://help.synchronik.co.in/a", title, sections, "help_portal")[0] == "created"
    assert upsert_web_page("http://help.synchronik.co.in/a", title, sections, "help_portal")[0] == "unchanged"
    title, sections = extract_html(ATTENDANCE_PAGE.replace("HOD approval", "Principal approval"))
    assert upsert_web_page("http://help.synchronik.co.in/a", title, sections, "help_portal")[0] == "updated"


def test_crawler_refuses_unlisted_hosts(app_env):
    import pytest
    from backend.crawler.crawler import Crawler, normalise

    with pytest.raises(ValueError):
        Crawler("https://example.com", "website")
    assert normalise("https://Help.Synchronik.co.in/a/#x") == "https://help.synchronik.co.in/a"


def test_regenerate_stream_replaces_last_answer(client, seeded):
    first = client.post("/api/chat", json={"message": "How is attendance marked?"}).json()
    cid = first["conversation_id"]
    with client.stream("POST", "/api/chat/regenerate/stream", json={"conversation_id": cid}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert "event: token" in body and "event: done" in body
    msgs = client.get(f"/api/conversations/{cid}").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_retry_of_unsent_question_keeps_previous_exchange(client, seeded):
    """A retry whose question never reached the server must not erase the exchange before it."""
    first = client.post("/api/chat", json={"message": "How is attendance marked?"}).json()
    cid = first["conversation_id"]
    r = client.post("/api/chat/regenerate", json={"conversation_id": cid, "message": "Who approves attendance edits?"})
    assert r.status_code == 200, r.text
    msgs = client.get(f"/api/conversations/{cid}").json()["messages"]
    assert [m["content"] for m in msgs if m["role"] == "user"] == ["How is attendance marked?", "Who approves attendance edits?"]
    assert len(msgs) == 4


def test_retry_of_stored_question_does_not_duplicate_it(client, seeded):
    first = client.post("/api/chat", json={"message": "How is attendance marked?"}).json()
    cid = first["conversation_id"]
    client.post("/api/chat/regenerate", json={"conversation_id": cid, "message": "How is attendance marked?"})
    msgs = client.get(f"/api/conversations/{cid}").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_stop_mid_stream_keeps_partial_answer(client, seeded):
    from backend.services import conversations as convs
    from backend.services import rag_pipeline

    events = rag_pipeline.run_events("How is attendance marked by the faculty?", None)
    cid, tokens = None, 0
    for event, payload in events:
        if event == "meta":
            cid = payload["conversation_id"]
        if event == "token":
            tokens += 1
            if tokens == 3:
                break
    events.close()  # what the server does when the client disconnects (Stop)
    msgs = client.get(f"/api/conversations/{cid}").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[-1]["content"].endswith(rag_pipeline.STOPPED_NOTE.strip())
    assert msgs[-1]["content"].startswith("Attendance is marked")
    # A regenerate afterwards replaces the stopped answer instead of stacking another one.
    assert convs.delete_last_assistant(cid) == "How is attendance marked by the faculty?"


def test_llm_quota_exhausted_falls_back_to_cited_excerpts(client, seeded):
    """A 429 from Gemini before any text must not fail the request: the retrieved evidence is still shown."""
    from backend.core.errors import RateLimited
    from backend.services.llm import get_llm

    class QuotaLLM(type(get_llm())):
        def stream(self, system, turns):
            raise RateLimited("quota")
            yield  # pragma: no cover

    set_llm(QuotaLLM())
    r = client.post("/api/chat", json={"message": "How is attendance marked by the faculty?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["metadata"]["model"] == "extractive-fallback"
    assert body["answer"].startswith("_The AI model is unavailable right now")
    assert body["grounded"] is True and body["sources"]

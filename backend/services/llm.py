"""LLM provider abstraction (Gemini today, swappable tomorrow).

The system prompt is passed as a separate ``system_instruction`` — it is never
concatenated with retrieved text — which is the first layer of the
prompt-injection defence (see ``context_builder``).
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass

from backend.core.config import get_settings
from backend.core.errors import LLMNotConfigured, LLMUnavailable, RateLimited
from backend.core.logging import log_event


@dataclass
class ChatTurn:
    role: str  # "user" | "model"
    text: str


class LLMProvider(ABC):
    model: str

    @abstractmethod
    def generate(self, system: str, turns: list[ChatTurn], *, max_tokens: int | None = None) -> str: ...

    @abstractmethod
    def stream(self, system: str, turns: list[ChatTurn]) -> Iterator[str]: ...

    @abstractmethod
    def describe_image(self, system: str, question: str, image_bytes: bytes, mime: str) -> str: ...


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, vision_model: str) -> None:
        from google import genai

        s = get_settings()
        self._client = genai.Client(api_key=api_key, http_options={"timeout": int(s.llm_timeout_s * 1000)})
        self.model = model
        self.vision_model = vision_model

    def _config(self, system: str, max_tokens: int | None = None):
        from google.genai import types

        s = get_settings()
        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=s.llm_temperature,
            max_output_tokens=max_tokens or s.llm_max_output_tokens,
        )

    @staticmethod
    def _contents(turns: list[ChatTurn]):
        from google.genai import types

        return [types.Content(role=t.role, parts=[types.Part.from_text(text=t.text)]) for t in turns]

    @staticmethod
    def _translate(exc: Exception) -> Exception:
        msg = str(exc)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            return RateLimited("The AI model is rate-limited right now. Please retry in a minute.")
        return LLMUnavailable()

    def generate(self, system, turns, *, max_tokens=None) -> str:
        try:
            resp = self._client.models.generate_content(
                model=self.model, contents=self._contents(turns), config=self._config(system, max_tokens)
            )
            return (resp.text or "").strip()
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

    def stream(self, system, turns) -> Iterator[str]:
        try:
            for chunk in self._client.models.generate_content_stream(
                model=self.model, contents=self._contents(turns), config=self._config(system)
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

    def describe_image(self, system, question, image_bytes, mime) -> str:
        from google.genai import types

        contents = [types.Part.from_bytes(data=image_bytes, mime_type=mime), question]
        # The answer model reads images too: use it when the vision model is overloaded or not offered to this key.
        models = [self.vision_model] + ([self.model] if self.model != self.vision_model else [])
        # The vision model "thinks" before answering and that counts against the output limit, so image answers get
        # a larger budget than text answers; otherwise longer answers stop mid-sentence.
        budget = 4 * get_settings().llm_max_output_tokens
        for i, model in enumerate(models):
            try:
                resp = self._client.models.generate_content(model=model, contents=contents,
                                                            config=self._config(system, budget))
                reason = str(getattr((getattr(resp, "candidates", None) or [None])[0], "finish_reason", "") or "")
                if "MAX_TOKENS" in reason:
                    log_event("llm_output_truncated", model=model)
                return (resp.text or "").strip()
            except Exception as exc:  # noqa: BLE001
                err = self._translate(exc)
                if i == len(models) - 1:
                    raise err from exc
                log_event("vision_model_fallback", model=model, error=type(exc).__name__,
                          status=getattr(exc, "code", None))
        raise LLMUnavailable()  # pragma: no cover - the loop always returns or raises


_lock = threading.Lock()
_provider: LLMProvider | None = None
_override = False


def get_llm(required: bool = True) -> LLMProvider | None:
    global _provider
    with _lock:
        if _provider is None and not _override:
            s = get_settings()
            if s.llm_configured:
                _provider = GeminiProvider(s.gemini_api_key, s.llm_model, s.vision_model)
        if _provider is None and required:
            raise LLMNotConfigured()
        return _provider


def set_llm(provider: LLMProvider | None) -> None:
    """Inject a provider (tests) — ``None`` forces 'not configured'."""
    global _provider, _override
    with _lock:
        _provider, _override = provider, True

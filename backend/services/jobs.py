"""Background jobs (crawl, reindex) on a single worker thread, with status persisted in ``jobs``.

One worker serialises index mutations. For multi-instance deployments this
would move to a real queue (RQ/Celery/Cloud Tasks) — documented as future work.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from backend.core.logging import log_event
from backend.db.models import Job, utcnow
from backend.db.session import session_scope
from backend.services.analytics import job_dict

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jobs")


def _update(job_id: str, **fields) -> None:
    with session_scope() as db:
        job = db.get(Job, job_id)
        for k, v in fields.items():
            setattr(job, k, v)


def submit(kind: str, fn: Callable[[], str]) -> dict:
    with session_scope() as db:
        job = Job(kind=kind, status="queued")
        db.add(job)
        db.flush()
        job_id, out = job.id, job_dict(job)

    def run():
        _update(job_id, status="running", started_at=utcnow())
        try:
            detail = fn()
            _update(job_id, status="succeeded", detail=detail, finished_at=utcnow())
            log_event("job_succeeded", job_id=job_id, kind=kind)
        except Exception as exc:  # noqa: BLE001
            _update(job_id, status="failed", detail=f"{type(exc).__name__}: {str(exc)[:300]}", finished_at=utcnow())
            log_event("job_failed", job_id=job_id, kind=kind, error=type(exc).__name__)

    _executor.submit(run)
    return out


def start_scheduler(interval_hours: float) -> None:
    """Periodic crawl refresh (opt-in via CRAWL_INTERVAL_HOURS)."""
    if interval_hours <= 0:
        return
    from backend.crawler.crawler import crawl_all

    stop = threading.Event()

    def loop():
        while not stop.wait(interval_hours * 3600):
            submit("crawl", lambda: crawl_all("all"))

    threading.Thread(target=loop, daemon=True, name="crawl-scheduler").start()
    log_event("scheduler_started", interval_hours=interval_hours)

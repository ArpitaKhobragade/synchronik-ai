"""Polite, scoped crawler for authorised Synchronik documentation sources.

* host allow-list (``CRAWL_ALLOWED_HOSTS``) and robots.txt respected,
* breadth-first within the seed host, capped by ``CRAWL_MAX_PAGES``,
* fixed delay between requests, timeouts, retries with backoff on 5xx/429,
* URL normalisation (fragments, trailing slashes, tracking params) for dedup,
* content-hash change detection: unchanged pages are not re-embedded,
* honest identifying User-Agent (``CRAWL_USER_AGENT``) instead of impersonating Chrome.
"""
from __future__ import annotations

import time
from collections import deque
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from backend.core.config import get_settings
from backend.core.logging import log_event
from backend.services.document_processing import extract_html
from backend.services.ingestion import upsert_web_page

SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".mp4", ".css", ".js", ".ico", ".webp", ".docx", ".xlsx")


def normalise(url: str) -> str:
    url, _ = urldefrag(url)
    p = urlparse(url)
    path = p.path.rstrip("/") or "/"
    return f"{p.scheme}://{p.netloc.lower()}{path}" + (f"?{p.query}" if p.query and "utm_" not in p.query else "")


class Crawler:
    def __init__(self, seed: str, source_type: str) -> None:
        s = get_settings()
        self.seed, self.source_type = seed, source_type
        self.host = urlparse(seed).netloc.lower()
        if self.host not in s.crawl_allowed_hosts:
            raise ValueError(f"{self.host} is not in CRAWL_ALLOWED_HOSTS")
        self.max_pages, self.delay, self.timeout = s.crawl_max_pages, s.crawl_delay_s, s.crawl_timeout_s
        self.session = requests.Session()
        self.ua = s.crawl_user_agent
        self.session.headers["User-Agent"] = self.ua
        self.robots = RobotFileParser()
        try:
            r = self.session.get(urljoin(seed, "/robots.txt"), timeout=self.timeout)
            self.robots.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            self.robots.parse([])

    def fetch(self, url: str, retries: int = 2) -> requests.Response | None:
        for attempt in range(retries + 1):
            try:
                r = self.session.get(url, timeout=self.timeout)
                if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(2 ** attempt * 2)
                    continue
                return r
            except requests.RequestException as exc:
                if attempt == retries:
                    log_event("crawl_fetch_failed", url=url, error=type(exc).__name__)
                    return None
                time.sleep(2 ** attempt * 2)
        return None

    def run(self) -> dict:
        stats = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0, "skipped": 0}
        seen: set[str] = set()
        queue = deque([normalise(self.seed)])
        while queue and len(seen) < self.max_pages:
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            if not self.robots.can_fetch(self.ua, url):
                stats["skipped"] += 1
                continue
            r = self.fetch(url)
            time.sleep(self.delay)
            if r is None or r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
                stats["failed" if r is None or r.status_code >= 400 else "skipped"] += 1
                continue
            r.encoding = r.apparent_encoding
            html = r.text
            for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
                link = normalise(urljoin(url, a["href"]))
                p = urlparse(link)
                if p.scheme in ("http", "https") and p.netloc.lower() == self.host \
                        and not p.path.lower().endswith(SKIP_EXT) and link not in seen:
                    queue.append(link)
            title, sections = extract_html(html)
            if sum(len(s.text) for s in sections) < 80:  # navigation-only page
                stats["skipped"] += 1
                continue
            try:
                action, _ = upsert_web_page(url, title or url, sections, self.source_type)
                stats[action] += 1
            except Exception as exc:  # noqa: BLE001
                stats["failed"] += 1
                log_event("crawl_page_failed", url=url, error=type(exc).__name__)
        log_event("crawl_done", seed=self.seed, pages=len(seen), **stats)
        return stats


def crawl_all(source: str = "all") -> str:
    from backend.services.curated import load_curated

    seeds = get_settings().crawl_seeds
    chosen = seeds if source == "all" else ({} if source == "curated" else {source: seeds[source]})
    results = {name: Crawler(url, name).run() for name, url in chosen.items()}
    if source in ("all", "curated"):
        results["curated"] = load_curated()  # repository FAQ documents (backend/knowledge)
    return "; ".join(f"{k}: " + ", ".join(f"{a}={n}" for a, n in v.items()) for k, v in results.items())


if __name__ == "__main__":
    import sys

    from backend.core.logging import configure_logging
    from backend.db.session import init_db
    from backend.services.vector_store import knowledge_index

    configure_logging(as_json=False)
    init_db()
    knowledge_index.load_or_build()
    print(crawl_all(sys.argv[1] if len(sys.argv) > 1 else "all"))

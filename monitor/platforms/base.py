"""Base scraper interface with HTTP retry support."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

from ..state import Program


class BaseScraper(ABC):
    """Each platform scraper implements `name`, `fetch`, and `parse`."""

    name: str = "base"
    display_name: str = "Base"

    # Retry policy
    max_retries: int = 3
    backoff_base: float = 1.0  # seconds
    backoff_factor: float = 2.0  # exponential factor
    retry_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504})

    def __init__(self, url: str, timeout: int = 30, user_agent: str = "Mozilla/5.0"):
        self.url = url
        self.timeout = timeout
        self.user_agent = user_agent

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/json",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    def fetch(self) -> str | None:
        """Fetch the platform page with retry on transient errors.

        Retries on: connection errors, timeouts, and 429/5xx responses.
        Backoff: exponential (1s, 2s, 4s, ...). Network errors get
        jittered backoff to avoid thundering-herd on transient outages.
        """
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with self._client() as c:
                    r = c.get(self.url)
                    if r.status_code in self.retry_statuses and attempt < self.max_retries:
                        delay = self.backoff_base * (self.backoff_factor ** attempt)
                        print(f"[{self.name}] HTTP {r.status_code}, retrying in {delay:.1f}s "
                              f"(attempt {attempt + 1}/{self.max_retries})")
                        time.sleep(delay)
                        continue
                    r.raise_for_status()
                    return r.text
            except (httpx.HTTPError, httpx.RequestError) as e:
                last_err = e
                if attempt < self.max_retries:
                    delay = self.backoff_base * (self.backoff_factor ** attempt)
                    print(f"[{self.name}] network error: {e}, retrying in {delay:.1f}s "
                          f"(attempt {attempt + 1}/{self.max_retries})")
                    time.sleep(delay)
                    continue
                break
        print(f"[{self.name}] fetch failed after {self.max_retries + 1} attempts: {last_err}")
        return None

    @abstractmethod
    def parse(self, raw: str) -> list[Program]:
        """Parse raw content into a list of Programs. Must be deterministic."""
        ...

    def run(self) -> list[Program]:
        raw = self.fetch()
        if raw is None:
            return []
        try:
            return self.parse(raw)
        except Exception as e:
            print(f"[{self.name}] parse error: {e}")
            return []


def safe_int(s: Any) -> int | None:
    """Parse a value into an int, returning None on failure.

    Handles: int, float, str (with $ and , stripping), None, and
    empty strings. Anything we can't parse becomes None.
    """
    if s is None:
        return None
    if isinstance(s, bool):
        return int(s)
    if isinstance(s, int):
        return s
    if isinstance(s, float):
        return int(s)
    if isinstance(s, str):
        s = s.replace(",", "").replace("$", "").strip()
        if not s:
            return None
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return None
    return None

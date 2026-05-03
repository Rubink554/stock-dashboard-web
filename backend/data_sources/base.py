from __future__ import annotations

import time
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass


DEFAULT_USER_AGENT = "WoobinStockDashboard/0.1 (+personal research dashboard)"


@dataclass
class FetchResult:
    ok: bool
    status: int | None
    text: str
    error: str | None = None


class SafeFetcher:
    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, delay_seconds: float = 1.0, timeout: float = 8.0):
        self.user_agent = user_agent
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self._last_request_at = 0.0
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    def can_fetch(self, url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        if root not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(urllib.parse.urljoin(root, "/robots.txt"))
            try:
                parser.read()
            except Exception:
                return False
            self._robots[root] = parser
        return self._robots[root].can_fetch(self.user_agent, url)

    def get(self, url: str) -> FetchResult:
        if not self.can_fetch(url):
            return FetchResult(False, None, "", "robots.txt disallows or robots.txt unavailable")
        elapsed = time.time() - self._last_request_at
        if elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                self._last_request_at = time.time()
                charset = response.headers.get_content_charset() or "utf-8"
                return FetchResult(True, response.status, response.read().decode(charset, errors="replace"))
        except Exception as exc:
            self._last_request_at = time.time()
            return FetchResult(False, None, "", str(exc))

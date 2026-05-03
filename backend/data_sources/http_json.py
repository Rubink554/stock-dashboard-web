from __future__ import annotations

import json
import time
import urllib.request


class JsonHttpClient:
    def __init__(self, name: str, delay_seconds: float = 0.8, timeout: float = 8.0) -> None:
        self.name = name
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self._last_request_at = 0.0
        self._cache: dict[str, tuple[float, dict | list]] = {}
        self._ttl = 1800

    def get_json(self, url: str) -> dict | list:
        cached = self._cache.get(url)
        if cached and time.time() - cached[0] < self._ttl:
            return cached[1]
        elapsed = time.time() - self._last_request_at
        if elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "WoobinStockDashboard/0.1 (+personal research dashboard)",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                self._last_request_at = time.time()
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
                self._cache[url] = (time.time(), payload)
                return payload
        except Exception:
            self._last_request_at = time.time()
            return {}


def to_float(value):
    if value in (None, "", "None", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

from __future__ import annotations

from .base import SafeFetcher


class NaverFinanceProvider:
    name = "naver_finance"

    def __init__(self) -> None:
        self.fetcher = SafeFetcher(delay_seconds=1.2)

    def search(self, query: str) -> list[dict]:
        # TODO: implement only after validating robots.txt and page/API terms.
        return []

    def metrics(self, ticker: str) -> dict | None:
        # TODO: parse null-safely and cache responses.
        return None

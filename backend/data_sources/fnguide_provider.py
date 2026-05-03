from __future__ import annotations

from .base import SafeFetcher


class FnGuideProvider:
    name = "fnguide"

    def __init__(self) -> None:
        self.fetcher = SafeFetcher(delay_seconds=1.5)

    def metrics(self, ticker: str) -> dict | None:
        # TODO: implement consensus/forward metrics after confirming terms.
        return None

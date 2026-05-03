from __future__ import annotations

from backend.database import SAMPLE_STOCKS


class SampleProvider:
    name = "sample_seed"

    def search(self, query: str) -> list[dict]:
        q = query.lower().strip()
        if not q:
            return []
        return [
            item
            for item in SAMPLE_STOCKS
            if q in item["ticker"].lower() or q in item["name"].lower() or q in item["theme"].lower()
        ]

    def metrics(self, ticker: str) -> dict | None:
        return next((item for item in SAMPLE_STOCKS if item["ticker"] == ticker), None)

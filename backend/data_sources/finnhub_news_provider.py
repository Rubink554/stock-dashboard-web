from __future__ import annotations

import os
import urllib.parse
from datetime import date, timedelta

from .http_json import JsonHttpClient


class FinnhubNewsProvider:
    name = "finnhub_news"

    def __init__(self) -> None:
        self.api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
        self.http = JsonHttpClient(self.name)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def news(self, ticker: str, name: str | None = None) -> list[dict]:
        if not self.enabled:
            return []
        symbol = normalize_symbol(ticker)
        today = date.today()
        start = today - timedelta(days=14)
        url = "https://finnhub.io/api/v1/company-news?" + urllib.parse.urlencode(
            {"symbol": symbol, "from": start.isoformat(), "to": today.isoformat(), "token": self.api_key}
        )
        payload = self.http.get_json(url)
        rows = payload if isinstance(payload, list) else []
        items = []
        for row in rows[:20]:
            title = row.get("headline")
            url = row.get("url")
            if not title or not url:
                continue
            items.append(
                {
                    "title": title,
                    "publisher": row.get("source") or self.name,
                    "published_at": row.get("datetime"),
                    "url": url,
                    "summary": row.get("summary") or "",
                    "source": self.name,
                }
            )
        return items


def normalize_symbol(ticker: str) -> str:
    ticker = ticker.strip().upper()
    if ":" in ticker:
        return ticker.split(":")[-1]
    if ticker.isdigit():
        return f"{ticker}.KS"
    return ticker

from __future__ import annotations

import os
import urllib.parse
import urllib.request
import json


class NaverNewsProvider:
    name = "naver_news"

    def __init__(self) -> None:
        self.client_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
        self.client_secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def news(self, ticker: str, name: str | None = None) -> list[dict]:
        if not self.enabled:
            return []
        query = f"{name or ticker} 주식"
        url = "https://openapi.naver.com/v1/search/news.json?" + urllib.parse.urlencode(
            {"query": query, "display": 10, "sort": "date"}
        )
        req = urllib.request.Request(
            url,
            headers={
                "X-Naver-Client-Id": self.client_id,
                "X-Naver-Client-Secret": self.client_secret,
                "User-Agent": "WoobinStockDashboard/0.1 (+personal research dashboard)",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception:
            return []
        items = []
        for row in payload.get("items", []):
            title = strip_html(row.get("title", ""))
            link = row.get("originallink") or row.get("link")
            if not title or not link:
                continue
            items.append(
                {
                    "title": title,
                    "publisher": self.name,
                    "published_at": row.get("pubDate"),
                    "url": link,
                    "summary": strip_html(row.get("description", "")),
                    "source": self.name,
                }
            )
        return items


def strip_html(value: str) -> str:
    return (
        value.replace("<b>", "")
        .replace("</b>", "")
        .replace("&quot;", '"')
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )

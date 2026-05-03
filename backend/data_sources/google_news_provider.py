from __future__ import annotations

import email.utils
import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


class GoogleNewsProvider:
    name = "google_news"

    def news(self, ticker: str, name: str | None = None) -> list[dict]:
        symbol = str(ticker or "").strip()
        company = str(name or ticker or "").strip()
        if symbol.isdigit() and len(symbol) <= 6:
            query = f"\"{company}\" OR \"{symbol.zfill(6)}\" 주식 실적 주가 공시"
        else:
            query = f"\"{company}\" OR \"{symbol}\" stock earnings shares analyst"
        return self.search(query, limit=15)

    def search(self, query: str, limit: int = 15) -> list[dict]:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
        )
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "WoobinStockDashboard/0.1 (+personal research dashboard)",
                "Accept": "application/rss+xml,application/xml,text/xml,*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except Exception:
            return []
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            return []
        items = []
        for item in root.findall("./channel/item")[:limit]:
            title = clean_text(item.findtext("title") or "")
            link = item.findtext("link") or ""
            description = clean_text(item.findtext("description") or "")
            published_at = parse_rss_date(item.findtext("pubDate") or "")
            if not title or not link:
                continue
            publisher = title.split(" - ")[-1].strip() if " - " in title else self.name
            title = title.rsplit(" - ", 1)[0].strip() if " - " in title else title
            items.append(
                {
                    "title": title,
                    "publisher": publisher,
                    "published_at": published_at,
                    "url": link,
                    "summary": description,
                    "source": self.name,
                }
            )
        return items


def clean_text(value: str) -> str:
    text = html.unescape(value)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_rss_date(value: str) -> str:
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        return parsed.isoformat()
    except Exception:
        return value


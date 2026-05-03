from __future__ import annotations

import os
import urllib.parse

from .http_json import JsonHttpClient, to_float


class AlphaVantageProvider:
    name = "alpha_vantage"

    def __init__(self) -> None:
        self.api_key = normalize_api_key(os.environ.get("ALPHAVANTAGE_API_KEY", ""), "apikey")
        self.http = JsonHttpClient(self.name, delay_seconds=12.0)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str) -> list[dict]:
        if not self.enabled or not query.strip():
            return []
        url = "https://www.alphavantage.co/query?" + urllib.parse.urlencode(
            {"function": "SYMBOL_SEARCH", "keywords": query, "apikey": self.api_key}
        )
        payload = self.http.get_json(url)
        matches = payload.get("bestMatches", []) if isinstance(payload, dict) else []
        return [
            {
                "ticker": item.get("1. symbol"),
                "name": item.get("2. name") or item.get("1. symbol"),
                "market": item.get("4. region") or "",
                "sector": None,
                "industry": None,
                "theme": None,
                "source": self.name,
            }
            for item in matches
            if item.get("1. symbol")
        ][:10]

    def metrics(self, ticker: str) -> dict | None:
        if not self.enabled:
            return None
        symbol = normalize_symbol(ticker)
        url = "https://www.alphavantage.co/query?" + urllib.parse.urlencode(
            {"function": "OVERVIEW", "symbol": symbol, "apikey": self.api_key}
        )
        payload = self.http.get_json(url)
        if not isinstance(payload, dict) or not payload.get("Symbol"):
            return None
        return {
            "ticker": ticker,
            "external_symbol": symbol,
            "per": to_float(payload.get("PERatio")),
            "pbr": to_float(payload.get("PriceToBookRatio")),
            "forward_pe": to_float(payload.get("ForwardPE")),
            "roe": percent_value(to_float(payload.get("ReturnOnEquityTTM"))),
            "eps": to_float(payload.get("EPS")),
            "bps": to_float(payload.get("BookValue")),
            "dividend_yield": to_float(payload.get("DividendYield")),
            "market_cap": to_float(payload.get("MarketCapitalization")),
            "target_price_avg": to_float(payload.get("AnalystTargetPrice")),
            "source": self.name,
        }


def normalize_symbol(ticker: str) -> str:
    ticker = ticker.strip().upper()
    if ":" in ticker:
        ticker = ticker.split(":")[-1]
    if ticker.isdigit():
        return f"{ticker}.KS"
    return ticker


def normalize_api_key(value: str, param_name: str = "apikey") -> str:
    value = (value or "").strip().strip('"').strip("'")
    if not value:
        return ""
    if f"{param_name}=" in value:
        parsed = urllib.parse.parse_qs(value.lstrip("?&"))
        return (parsed.get(param_name) or [value])[-1].strip()
    return value


def percent_value(value):
    if value is None:
        return None
    return value * 100 if abs(value) <= 5 else value

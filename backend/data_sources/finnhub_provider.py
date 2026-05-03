from __future__ import annotations

import os
import urllib.parse

from .http_json import JsonHttpClient, to_float


class FinnhubProvider:
    name = "finnhub"

    def __init__(self) -> None:
        self.api_key = normalize_api_key(os.environ.get("FINNHUB_API_KEY", ""), "token")
        self.http = JsonHttpClient(self.name)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str) -> list[dict]:
        if not self.enabled or not query.strip():
            return []
        url = "https://finnhub.io/api/v1/search?" + urllib.parse.urlencode({"q": query, "token": self.api_key})
        payload = self.http.get_json(url)
        results = payload.get("result", []) if isinstance(payload, dict) else []
        return [
            {
                "ticker": item.get("symbol"),
                "name": item.get("description") or item.get("displaySymbol") or item.get("symbol"),
                "market": item.get("type") or "",
                "sector": None,
                "industry": None,
                "theme": None,
                "source": self.name,
            }
            for item in results
            if item.get("symbol")
        ][:10]

    def metrics(self, ticker: str) -> dict | None:
        if not self.enabled:
            return None
        symbol = normalize_symbol(ticker)
        metric_url = "https://finnhub.io/api/v1/stock/metric?" + urllib.parse.urlencode(
            {"symbol": symbol, "metric": "all", "token": self.api_key}
        )
        quote_url = "https://finnhub.io/api/v1/quote?" + urllib.parse.urlencode({"symbol": symbol, "token": self.api_key})
        metric_payload = self.http.get_json(metric_url)
        quote_payload = self.http.get_json(quote_url)
        metrics = metric_payload.get("metric", {}) if isinstance(metric_payload, dict) else {}
        if not metrics and not quote_payload:
            return None
        price = to_float(quote_payload.get("c")) if isinstance(quote_payload, dict) else None
        target_avg = to_float(metrics.get("targetMean"))
        return {
            "ticker": ticker,
            "external_symbol": symbol,
            "price": price,
            "per": first(metrics, ["peTTM", "peBasicExclExtraTTM"]),
            "pbr": first(metrics, ["pbAnnual", "pbQuarterly"]),
            "forward_pe": first(metrics, ["forwardPE"]),
            "roe": first(metrics, ["roeTTM", "roeRfy"]),
            "eps": first(metrics, ["epsInclExtraItemsTTM", "epsBasicExclExtraItemsTTM"]),
            "dividend_yield": first(metrics, ["dividendYieldIndicatedAnnual", "currentDividendYieldTTM"]),
            "market_cap": first(metrics, ["marketCapitalization"]),
            "high52": first(metrics, ["52WeekHigh"]),
            "low52": first(metrics, ["52WeekLow"]),
            "target_price_high": first(metrics, ["targetHigh"]),
            "target_price_low": first(metrics, ["targetLow"]),
            "target_price_avg": target_avg,
            "upside_pct": target_avg / price - 1 if target_avg and price else None,
            "source": self.name,
        }


def first(data: dict, keys: list[str]):
    for key in keys:
        value = to_float(data.get(key))
        if value is not None:
            return value
    return None


def normalize_symbol(ticker: str) -> str:
    ticker = ticker.strip().upper()
    if ":" in ticker:
        return ticker.split(":")[-1]
    if ticker.isdigit():
        return f"{ticker}.KS"
    return ticker


def normalize_api_key(value: str, param_name: str = "token") -> str:
    value = (value or "").strip().strip('"').strip("'")
    if not value:
        return ""
    if f"{param_name}=" in value:
        parsed = urllib.parse.parse_qs(value.lstrip("?&"))
        return (parsed.get(param_name) or [value])[-1].strip()
    return value

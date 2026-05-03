from __future__ import annotations

import os
import urllib.parse

from .http_json import JsonHttpClient, to_float


class FinancialModelingPrepProvider:
    name = "financial_modeling_prep"

    def __init__(self) -> None:
        self.api_key = normalize_api_key(os.environ.get("FMP_API_KEY", ""))
        self.http = JsonHttpClient(self.name)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str) -> list[dict]:
        if not self.enabled or not query.strip():
            return []
        payload = self._get_json("/api/v3/search", {"query": query, "limit": 10})
        if not payload:
            payload = self._get_json("/stable/search-symbol", {"query": query, "limit": 10})
        rows = payload if isinstance(payload, list) else []
        return [
            {
                "ticker": item.get("symbol"),
                "name": item.get("name") or item.get("symbol"),
                "market": item.get("exchangeShortName") or item.get("stockExchange") or item.get("exchange") or "",
                "sector": None,
                "industry": None,
                "theme": None,
                "source": self.name,
            }
            for item in rows
            if item.get("symbol")
        ]

    def metrics(self, ticker: str) -> dict | None:
        if not self.enabled:
            return None
        symbol = normalize_symbol(ticker)
        profile = self._first_working([
            (f"/api/v3/profile/{symbol}", {}),
            ("/stable/profile", {"symbol": symbol}),
        ])
        ratios = self._first_working([
            (f"/api/v3/ratios-ttm/{symbol}", {}),
            ("/stable/ratios-ttm", {"symbol": symbol}),
        ])
        key_metrics = self._first_working([
            (f"/api/v3/key-metrics-ttm/{symbol}", {}),
            ("/stable/key-metrics-ttm", {"symbol": symbol}),
        ])
        price_target = self._first_working([
            ("/stable/price-target-summary", {"symbol": symbol}),
            ("/stable/price-target-consensus", {"symbol": symbol}),
            ("/api/v4/price-target-consensus", {"symbol": symbol}),
        ])
        estimates = self._first_working([
            (f"/api/v3/analyst-estimates/{symbol}", {"period": "annual", "limit": 1}),
            ("/stable/analyst-estimates", {"symbol": symbol, "period": "annual", "limit": 1}),
        ])
        if not profile and not ratios and not key_metrics and not estimates and not price_target:
            return None
        price = first_number(profile, ["price", "lastDiv", "marketPrice"])
        target_avg = first_number(profile, ["targetPrice", "target_price"])
        if target_avg is None:
            target_avg = first_number(price_target, ["targetConsensus", "targetPrice", "targetMean", "priceTargetAverage", "targetAvg", "priceTargetConsensus", "target"])
        target_high = first_number(price_target, ["targetHigh", "priceTargetHigh", "high", "targetPriceHigh"])
        target_low = first_number(price_target, ["targetLow", "priceTargetLow", "low", "targetPriceLow"])
        if target_avg is None and target_high and target_low:
            target_avg = (target_high + target_low) / 2
        pbr = first_available_number([ratios, key_metrics], ["priceToBookRatioTTM", "pbRatioTTM", "priceBookValueRatioTTM", "pbRatio", "priceToBookRatio"])
        book_value_per_share = first_available_number([key_metrics, ratios], ["bookValuePerShareTTM", "bookValuePerShare", "bookValue"])
        if pbr is None and price and book_value_per_share:
            pbr = price / book_value_per_share
        estimated_eps = first_available_number([estimates], ["estimatedEpsAvg", "epsAvg", "estimatedEpsHigh"])
        forward_pe = price / estimated_eps if price and estimated_eps else None
        return {
            "ticker": ticker,
            "external_symbol": symbol,
            "price": price,
            "per": first_available_number([ratios, key_metrics], ["peRatioTTM", "priceEarningsRatioTTM", "peTTM", "peRatio"]),
            "pbr": pbr,
            "roe": percent_value(first_available_number([ratios, key_metrics], ["returnOnEquityTTM", "roeTTM", "returnOnEquity", "roe"])),
            "forward_pe": forward_pe,
            "eps": first_number(profile, ["eps", "epsTTM"]),
            "dividend_yield": first_number(ratios, ["dividendYielTTM", "dividendYieldTTM"]),
            "market_cap": first_number(profile, ["mktCap", "marketCap"]),
            "target_price_high": target_high,
            "target_price_low": target_low,
            "target_price_avg": target_avg,
            "upside_pct": target_avg / price - 1 if target_avg and price else None,
            "revenue_growth": first_number(estimates, ["estimatedRevenueAvg", "revenueAvg", "estimatedRevenueHigh"]),
            "source": self.name,
        }

    def _get_json(self, path: str, params: dict) -> dict | list:
        params = {**params, "apikey": self.api_key}
        url = "https://financialmodelingprep.com" + path + "?" + urllib.parse.urlencode(params)
        return self.http.get_json(url)

    def _first_working(self, requests: list[tuple[str, dict]]) -> dict | None:
        for path, params in requests:
            payload = self._get_json(path, params)
            row = get_first(payload)
            if row:
                return row
        return None


def get_first(payload):
    if isinstance(payload, list) and payload:
        return payload[0]
    if isinstance(payload, dict):
        for key in ("data", "results"):
            value = payload.get(key)
            if isinstance(value, list) and value:
                return value[0]
            if isinstance(value, dict):
                return value
        if payload and not payload.get("Error Message") and not payload.get("error"):
            return payload
    return None


def normalize_symbol(ticker: str) -> str:
    ticker = ticker.strip().upper()
    if ":" in ticker:
        ticker = ticker.split(":")[-1]
    if ticker.isdigit():
        return f"{ticker}.KS"
    return ticker


def normalize_api_key(value: str) -> str:
    value = (value or "").strip().strip('"').strip("'")
    if not value:
        return ""
    if "apikey=" in value:
        parsed = urllib.parse.parse_qs(value.lstrip("?&"))
        return (parsed.get("apikey") or [value])[-1].strip()
    return value


def first_number(row: dict | None, keys: list[str]):
    if not row:
        return None
    for key in keys:
        value = to_float(row.get(key))
        if value is not None:
            return value
    return None


def first_available_number(rows: list[dict | None], keys: list[str]):
    for row in rows:
        value = first_number(row, keys)
        if value is not None:
            return value
    return None


def percent_value(value):
    if value is None:
        return None
    return value * 100 if abs(value) <= 5 else value




from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

try:
    import yfinance as yf
except Exception:
    yf = None


class YahooFinanceProvider:
    """Small no-dependency Yahoo Finance adapter.

    This is best-effort. Yahoo endpoints can throttle or change response shapes,
    so callers must treat missing values as normal and fall back gracefully.
    """

    name = "yahoo_finance"

    def __init__(self, delay_seconds: float = 0.8, timeout: float = 8.0) -> None:
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self._last_request_at = 0.0
        self._cache: dict[str, tuple[float, dict | list]] = {}
        self._ttl = 1800

    def search(self, query: str) -> list[dict]:
        query = query.strip()
        if not query:
            return []
        url = "https://query1.finance.yahoo.com/v1/finance/search?" + urllib.parse.urlencode(
            {"q": query, "quotesCount": 8, "newsCount": 0}
        )
        payload = self._get_json(url)
        quotes = payload.get("quotes", []) if isinstance(payload, dict) else []
        results = []
        for quote in quotes:
            symbol = quote.get("symbol")
            if not symbol:
                continue
            results.append(
                {
                    "ticker": symbol,
                    "name": quote.get("shortname") or quote.get("longname") or symbol,
                    "market": quote.get("exchDisp") or quote.get("exchange") or "",
                    "sector": None,
                    "industry": quote.get("sector") or quote.get("industry"),
                    "theme": None,
                    "source": self.name,
                }
            )
        return results

    def metrics(self, ticker: str) -> dict | None:
        for symbol in self._candidate_symbols(ticker):
            metrics = self._metrics_for_symbol(symbol) or {}
            package_metrics = self._metrics_from_yfinance_package(symbol) or {}
            merged = {**metrics, **{key: value for key, value in package_metrics.items() if value is not None}}
            if merged and any(value is not None for value in merged.values()):
                merged["ticker"] = ticker
                merged["external_symbol"] = symbol
                merged["source"] = self.name
                return merged
        return None

    def prices(self, ticker: str, period: str = "1y", interval: str = "1d") -> dict | None:
        for symbol in self._candidate_symbols(ticker):
            payload = self._prices_for_symbol(symbol, period, interval)
            if payload and payload.get("items"):
                payload["ticker"] = ticker
                payload["external_symbol"] = symbol
                payload["source"] = self.name
                return payload
        return None

    def _metrics_for_symbol(self, symbol: str) -> dict | None:
        modules = ",".join(["price", "summaryDetail", "defaultKeyStatistics", "financialData"])
        url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(symbol)}?" + urllib.parse.urlencode(
            {"modules": modules}
        )
        payload = self._get_json(url)
        result = (
            payload.get("quoteSummary", {}).get("result", [None])[0]
            if isinstance(payload, dict)
            else None
        )
        if not result:
            return None
        price = result.get("price", {})
        summary = result.get("summaryDetail", {})
        stats = result.get("defaultKeyStatistics", {})
        financial = result.get("financialData", {})
        current_price = self._raw(price.get("regularMarketPrice")) or self._raw(financial.get("currentPrice"))
        target_avg = self._raw(financial.get("targetMeanPrice"))
        upside = None
        if current_price and target_avg:
            upside = target_avg / current_price - 1
        return {
            "price": current_price,
            "per": self._raw(summary.get("trailingPE")),
            "pbr": self._raw(stats.get("priceToBook")),
            "forward_pe": self._raw(stats.get("forwardPE")),
            "roe": self._percent(self._raw(financial.get("returnOnEquity"))),
            "eps": self._raw(stats.get("trailingEps")),
            "bps": self._raw(stats.get("bookValue")),
            "dividend_yield": self._raw(summary.get("dividendYield")),
            "market_cap": self._raw(price.get("marketCap")),
            "high52": self._raw(summary.get("fiftyTwoWeekHigh")),
            "low52": self._raw(summary.get("fiftyTwoWeekLow")),
            "target_price_high": self._raw(financial.get("targetHighPrice")),
            "target_price_low": self._raw(financial.get("targetLowPrice")),
            "target_price_avg": target_avg,
            "upside_pct": upside,
            "investment_opinion_avg": self._raw(financial.get("recommendationMean")),
            "report_count": self._raw(financial.get("numberOfAnalystOpinions")),
        }

    def _metrics_from_yfinance_package(self, symbol: str) -> dict | None:
        if yf is None:
            return None
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.get_info() or {}
            fast = getattr(ticker, "fast_info", {}) or {}
        except Exception:
            return None
        current_price = self._to_float(info.get("currentPrice")) or self._to_float(info.get("regularMarketPrice")) or self._to_float(getattr(fast, "last_price", None))
        target_avg = self._to_float(info.get("targetMeanPrice"))
        metrics = {
            "price": current_price,
            "per": self._to_float(info.get("trailingPE")),
            "pbr": self._to_float(info.get("priceToBook")),
            "forward_pe": self._to_float(info.get("forwardPE")),
            "roe": self._percent(self._to_float(info.get("returnOnEquity"))),
            "eps": self._to_float(info.get("trailingEps")),
            "bps": self._to_float(info.get("bookValue")),
            "dividend_yield": self._to_float(info.get("dividendYield")),
            "market_cap": self._to_float(info.get("marketCap")) or self._to_float(getattr(fast, "market_cap", None)),
            "high52": self._to_float(info.get("fiftyTwoWeekHigh")) or self._to_float(getattr(fast, "year_high", None)),
            "low52": self._to_float(info.get("fiftyTwoWeekLow")) or self._to_float(getattr(fast, "year_low", None)),
            "target_price_high": self._to_float(info.get("targetHighPrice")),
            "target_price_low": self._to_float(info.get("targetLowPrice")),
            "target_price_avg": target_avg,
            "upside_pct": target_avg / current_price - 1 if target_avg and current_price else None,
            "investment_opinion_avg": self._to_float(info.get("recommendationMean")),
            "report_count": self._to_float(info.get("numberOfAnalystOpinions")),
        }
        return metrics if any(value is not None for value in metrics.values()) else None
    def _prices_for_symbol(self, symbol: str, period: str, interval: str) -> dict | None:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?" + urllib.parse.urlencode(
            {"range": period, "interval": interval}
        )
        payload = self._get_json(url)
        result = (
            payload.get("chart", {}).get("result", [None])[0]
            if isinstance(payload, dict)
            else None
        )
        if not result:
            return None
        timestamps = result.get("timestamp") or []
        quote = (result.get("indicators", {}).get("quote") or [{}])[0]
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []
        items = []
        date_format = "%H:%M" if period == "1d" or interval.endswith("m") else "%Y-%m-%d"
        for index, timestamp in enumerate(timestamps):
            close = closes[index] if index < len(closes) else None
            if close is None:
                continue
            items.append(
                {
                    "date": time.strftime(date_format, time.localtime(timestamp)),
                    "close": close,
                    "volume": volumes[index] if index < len(volumes) else None,
                }
            )
        meta = result.get("meta", {})
        return {
            "currency": meta.get("currency"),
            "regular_market_price": meta.get("regularMarketPrice"),
            "items": items,
        }

    def _candidate_symbols(self, ticker: str) -> list[str]:
        ticker = ticker.strip().upper()
        if not ticker:
            return []
        if ":" in ticker:
            ticker = ticker.split(":")[-1]
        if "." in ticker or not ticker.isdigit():
            return [ticker]
        # Korean listed names are commonly exposed as .KS or .KQ on Yahoo.
        return [f"{ticker}.KS", f"{ticker}.KQ", ticker]

    def _get_json(self, url: str) -> dict:
        cached = self._cache.get(url)
        if cached and time.time() - cached[0] < self._ttl:
            return cached[1]  # type: ignore[return-value]
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

    @staticmethod
    def _raw(value):
        if isinstance(value, dict):
            return value.get("raw")
        return value

    @staticmethod
    def _to_float(value):
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _percent(value):
        number = YahooFinanceProvider._to_float(value)
        if number is None:
            return None
        return number * 100 if abs(number) <= 5 else number



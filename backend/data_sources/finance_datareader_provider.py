from __future__ import annotations

from datetime import datetime, timedelta

try:
    import FinanceDataReader as fdr
except Exception:
    fdr = None


class FinanceDataReaderProvider:
    name = "finance_datareader"

    @property
    def enabled(self) -> bool:
        return fdr is not None

    def search(self, query: str) -> list[dict]:
        if not self.enabled:
            return []
        q = (query or "").strip().lower()
        if not q:
            return []
        markets = ["KRX", "S&P500", "NASDAQ", "NYSE", "AMEX"]
        rows = []
        for market in markets:
            try:
                df = fdr.StockListing(market)
            except Exception:
                continue
            for _, row in df.head(8000).iterrows():
                symbol = str(row.get("Code") or row.get("Symbol") or row.get("Ticker") or "").strip()
                name = str(row.get("Name") or row.get("NameEn") or symbol).strip()
                if not symbol:
                    continue
                if q in f"{symbol} {name}".lower():
                    rows.append({
                        "ticker": symbol,
                        "name": name or symbol,
                        "market": market,
                        "sector": row.get("Sector") if hasattr(row, "get") else None,
                        "industry": row.get("Industry") if hasattr(row, "get") else None,
                        "theme": None,
                        "source": self.name,
                    })
                if len(rows) >= 12:
                    return rows
        return rows

    def metrics(self, ticker: str) -> dict | None:
        # FinanceDataReader is used mainly for price/index data. Fundamental metrics are handled by pykrx/API providers.
        price_payload = self.prices(ticker, period="1y")
        if not price_payload or not price_payload.get("items"):
            return None
        items = price_payload["items"]
        closes = [item["close"] for item in items if isinstance(item.get("close"), (int, float))]
        if not closes:
            return None
        latest = closes[-1]
        d1 = latest / closes[-2] - 1 if len(closes) > 1 and closes[-2] else None
        ytd = latest / closes[0] - 1 if closes[0] else None
        return {
            "ticker": ticker,
            "external_symbol": price_payload.get("external_symbol"),
            "price": latest,
            "high52": max(closes),
            "low52": min(closes),
            "d1": d1,
            "ytd": ytd,
            "source": self.name,
        }

    def prices(self, ticker: str, period: str = "1y", interval: str = "1d") -> dict | None:
        if not self.enabled:
            return None
        symbol = normalize_symbol(ticker)
        days = {"1mo": 45, "3mo": 120, "6mo": 220, "1y": 430, "2y": 800, "5y": 1900}.get(period, 430)
        end_date = datetime.now()
        start = (end_date - timedelta(days=days)).strftime("%Y-%m-%d")
        end = end_date.strftime("%Y-%m-%d")
        candidates = candidate_symbols(symbol)
        for candidate in candidates:
            try:
                df = fdr.DataReader(candidate, start, end)
            except Exception:
                continue
            if df is None or getattr(df, "empty", True):
                continue
            close_col = "Close" if "Close" in df.columns else "종가" if "종가" in df.columns else None
            volume_col = "Volume" if "Volume" in df.columns else "거래량" if "거래량" in df.columns else None
            if not close_col:
                continue
            items = []
            for idx, row in df.iterrows():
                close = to_number(row.get(close_col))
                if close is None:
                    continue
                date = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
                items.append({"date": date, "close": close, "volume": to_number(row.get(volume_col)) if volume_col else None})
            if items:
                return {"ticker": ticker, "external_symbol": candidate, "period": period, "source": self.name, "items": items}
        return None


def normalize_symbol(ticker: str) -> str:
    clean = str(ticker or "").strip().upper()
    if ":" in clean:
        clean = clean.split(":")[-1]
    return clean


def candidate_symbols(symbol: str) -> list[str]:
    if symbol.isdigit():
        base = symbol.zfill(6)
        return [base, f"KRX:{base}", f"NAVER:{base}", f"YAHOO:{base}.KS", f"YAHOO:{base}.KQ"]
    return [symbol]


def to_number(value):
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except Exception:
        return None

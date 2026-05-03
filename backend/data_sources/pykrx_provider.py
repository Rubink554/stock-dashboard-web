from __future__ import annotations

from datetime import datetime, timedelta
import time

try:
    from pykrx import stock
except Exception:
    stock = None


class PykrxProvider:
    name = "pykrx"

    def __init__(self) -> None:
        self._disabled_until = 0.0

    @property
    def enabled(self) -> bool:
        return stock is not None and time.time() >= self._disabled_until

    def _cooldown(self) -> None:
        self._disabled_until = time.time() + 3600

    def search(self, query: str) -> list[dict]:
        if not self.enabled:
            return []
        q = (query or "").strip().lower()
        if not q:
            return []
        rows = []
        try:
            tickers = stock.get_market_ticker_list(market="ALL")
            for ticker in tickers:
                name = stock.get_market_ticker_name(ticker)
                text = f"{ticker} {name}".lower()
                if q in text:
                    rows.append({
                        "ticker": ticker,
                        "name": name or ticker,
                        "market": "KRX",
                        "sector": None,
                        "industry": None,
                        "theme": None,
                        "source": self.name,
                    })
                if len(rows) >= 10:
                    break
        except Exception:
            self._cooldown()
            return []
        return rows

    def metrics(self, ticker: str) -> dict | None:
        if not self.enabled or not is_krx_ticker(ticker):
            return None
        symbol = normalize_krx_ticker(ticker)
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=14)).strftime("%Y%m%d")
        try:
            fund = stock.get_market_fundamental(start, end, symbol)
            ohlcv = stock.get_market_ohlcv(start, end, symbol)
            cap = stock.get_market_cap(start, end, symbol)
        except Exception:
            self._cooldown()
            return None
        if fund is None or getattr(fund, "empty", True):
            return None
        latest = fund.dropna(how="all").tail(1)
        if latest.empty:
            return None
        row = latest.iloc[-1]
        price = None
        high52 = None
        low52 = None
        d1 = None
        if ohlcv is not None and not getattr(ohlcv, "empty", True):
            close = ohlcv.get("종가")
            if close is not None and len(close):
                price = to_number(close.iloc[-1])
                if len(close) > 1 and close.iloc[-2]:
                    d1 = price / to_number(close.iloc[-2]) - 1 if price else None
                high52 = to_number(close.max())
                low52 = to_number(close.min())
        market_cap = None
        if cap is not None and not getattr(cap, "empty", True):
            cap_row = cap.tail(1).iloc[-1]
            market_cap = to_number(cap_row.get("시가총액"))
        eps = to_number(row.get("EPS"))
        bps = to_number(row.get("BPS"))
        per = to_number(row.get("PER"))
        pbr = to_number(row.get("PBR"))
        dividend_yield = to_number(row.get("DIV"))
        roe = eps / bps * 100 if eps is not None and bps not in (None, 0) else None
        return {
            "ticker": symbol,
            "external_symbol": symbol,
            "price": price,
            "per": per,
            "pbr": pbr,
            "roe": roe,
            "eps": eps,
            "bps": bps,
            "dividend_yield": dividend_yield,
            "market_cap": market_cap,
            "high52": high52,
            "low52": low52,
            "d1": d1,
            "source": self.name,
        }

    def prices(self, ticker: str, period: str = "1y", interval: str = "1d") -> dict | None:
        if not self.enabled or not is_krx_ticker(ticker):
            return None
        symbol = normalize_krx_ticker(ticker)
        days = {"1mo": 45, "3mo": 120, "6mo": 220, "1y": 430, "2y": 800, "5y": 1900}.get(period, 430)
        end_date = datetime.now()
        start = (end_date - timedelta(days=days)).strftime("%Y%m%d")
        end = end_date.strftime("%Y%m%d")
        try:
            df = stock.get_market_ohlcv(start, end, symbol)
        except Exception:
            self._cooldown()
            return None
        if df is None or getattr(df, "empty", True):
            return None
        items = []
        for idx, row in df.iterrows():
            close = to_number(row.get("종가"))
            if close is None:
                continue
            date = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
            items.append({"date": date, "close": close, "volume": to_number(row.get("거래량"))})
        if not items:
            return None
        return {
            "ticker": ticker,
            "external_symbol": symbol,
            "period": period,
            "source": self.name,
            "items": items,
        }


def is_krx_ticker(ticker: str) -> bool:
    symbol = normalize_krx_ticker(ticker)
    return symbol.isdigit() and len(symbol) == 6


def normalize_krx_ticker(ticker: str) -> str:
    clean = str(ticker or "").strip().upper()
    if ":" in clean:
        clean = clean.split(":")[-1]
    if clean.endswith(".KS") or clean.endswith(".KQ"):
        clean = clean.split(".")[0]
    return clean.zfill(6) if clean.isdigit() and len(clean) <= 6 else clean


def to_number(value):
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except Exception:
        return None



from __future__ import annotations

import argparse
import json
import math
import mimetypes
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database import connect, init_db, row_to_dict, seed_db
from backend.database import now_iso
from backend.data_sources import (
    AlphaVantageProvider,
    FinancialModelingPrepProvider,
    FinnhubNewsProvider,
    FinnhubProvider,
    GoogleNewsProvider,
    NaverNewsProvider,
    YahooFinanceProvider,
    PykrxProvider,
    FinanceDataReaderProvider,
)
from backend.quant import DEFAULT_WEIGHTS, score_metrics
from backend.news import canonical_url, news_id, now_iso as news_now_iso, summarize_news, title_fingerprint
from backend.ai_summary import ai_status, analyze_stock_research_with_ai, analyze_stock_with_ai, load_dotenv, summarize_news_with_ai, summarize_stock_news_bundle_with_ai

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR)
EXTERNAL_PROVIDERS = [
    PykrxProvider(),
    FinanceDataReaderProvider(),
    FinancialModelingPrepProvider(),
    YahooFinanceProvider(),
    FinnhubProvider(),
    AlphaVantageProvider(),
]
PRICE_PROVIDERS = [
    FinanceDataReaderProvider(),
    PykrxProvider(),
    FinancialModelingPrepProvider(),
    YahooFinanceProvider(),
    FinnhubProvider(),
    AlphaVantageProvider(),
]
NEWS_PROVIDERS = [GoogleNewsProvider(), FinnhubNewsProvider(), NaverNewsProvider()]
NEWS_LOOKBACK_DAYS = 2
NEWS_PLACEHOLDER_PUBLISHERS = ("검색 fallback", "뉴스 검색 링크", "리서치 확인 링크")
MARKET_NEWS_QUERIES = [
    ("연준·금리", "Federal Reserve interest rates FOMC stocks market"),
    ("고용·물가", "US jobs CPI PCE inflation economic data stocks market"),
    ("정책·관세", "US president tariffs regulation policy stocks market"),
    ("국채·달러", "Treasury yields dollar oil market stocks"),
    ("미국 빅테크", "Nvidia Apple Microsoft Amazon Tesla earnings stocks"),
    ("AI·반도체", "AI semiconductor Nvidia AMD Broadcom chip stocks"),
    ("한국증시", "KOSPI semiconductor battery stocks news"),
]
MARKET_NEWS_CACHE = {"created_at": None, "payload": None}
MARKET_INDICATORS_CACHE = {"created_at": None, "payload": None}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
    server_version = "WoobinStockAPI/0.1"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_common_headers()
        self.end_headers()

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                self.send_json(route_get(parsed.path, parse_qs(parsed.query)))
            else:
                self.serve_static(parsed.path)
        except ApiError as exc:
            self.send_json({"error": exc.message}, exc.status)
        except Exception as exc:
            self.send_json({"error": "internal_server_error", "detail": str(exc)}, 500)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(body or "{}")
            if parsed.path.startswith("/api/"):
                self.send_json(route_post(parsed.path, payload))
            else:
                raise ApiError(404, "not_found")
        except ApiError as exc:
            self.send_json({"error": exc.message}, exc.status)
        except Exception as exc:
            self.send_json({"error": "internal_server_error", "detail": str(exc)}, 500)

    def serve_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        target = (ROOT_DIR / unquote(path.lstrip("/"))).resolve()
        if ROOT_DIR not in target.parents and target != ROOT_DIR:
            raise ApiError(403, "forbidden")
        if not target.exists() or target.is_dir():
            raise ApiError(404, "not_found")
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_common_headers(content_type)
        self.end_headers()
        self.wfile.write(target.read_bytes())

    def send_json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_common_headers("application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_common_headers(self, content_type: str = "text/plain; charset=utf-8") -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def db() -> sqlite3.Connection:
    conn = connect()
    init_db(conn)
    seed_db(conn)
    return conn


def route_get(path: str, query: dict[str, list[str]]) -> dict | list:
    parts = [part for part in path.split("/") if part]
    if path == "/api/health":
        return {"ok": True, "service": "woobin-stock-api"}
    if path == "/api/search/stocks":
        return search_stocks(first(query, "q", ""))
    if path == "/api/watchlist/metrics":
        return watchlist_metrics(parse_tickers(first(query, "tickers", "")))
    if path == "/api/watchlist/news":
        return watchlist_news(parse_tickers(first(query, "tickers", "")))
    if path == "/api/market/news":
        return market_news()
    if path == "/api/market/indicators":
        return market_indicators()
    if path == "/api/economic-calendar":
        return economic_calendar()
    if path == "/api/ai/status":
        return ai_status()
    if path == "/api/stocks/compare":
        return compare_stocks(parse_tickers(first(query, "tickers", "")))
    if path == "/api/quant/rank":
        return quant_rank(limit=int(first(query, "limit", "50")))
    if len(parts) == 4 and parts[:2] == ["api", "stocks"] and parts[3] == "metrics":
        return stock_metrics(parts[2], force=first(query, "refresh", "") == "1")
    if len(parts) == 4 and parts[:2] == ["api", "stocks"] and parts[3] == "prices":
        return stock_prices(parts[2], first(query, "period", "1y"))
    if len(parts) == 4 and parts[:2] == ["api", "stocks"] and parts[3] == "news":
        return stock_news(parts[2])
    if len(parts) == 4 and parts[:2] == ["api", "stocks"] and parts[3] == "news-summary":
        return stock_news_summary(parts[2])
    if len(parts) == 4 and parts[:2] == ["api", "stocks"] and parts[3] == "analysis":
        return stock_analysis(parts[2], mode=first(query, 'mode', 'app'))
    if len(parts) == 4 and parts[:2] == ["api", "quant"] and parts[2] == "score":
        return quant_score(parts[3])
    if len(parts) == 5 and parts[:2] == ["api", "stocks"] and parts[3] == "classification" and parts[4] == "suggest":
        return classification_suggest(parts[2])
    raise ApiError(404, "not_found")


def route_post(path: str, payload: dict) -> dict | list:
    if path == "/api/quant/recalculate":
        tickers = parse_tickers(",".join(payload.get("tickers", [])) if isinstance(payload.get("tickers"), list) else payload.get("tickers", ""))
        weights = payload.get("weights") or DEFAULT_WEIGHTS
        return recalculate_quant(tickers, weights)
    raise ApiError(404, "not_found")


def first(query: dict[str, list[str]], key: str, default: str = "") -> str:
    return query.get(key, [default])[0]


def parse_tickers(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def search_stocks(q: str) -> dict:
    raw_query = q.strip()
    q = raw_query.lower()
    with db() as conn:
        if not q:
            rows = conn.execute("SELECT * FROM stocks ORDER BY name LIMIT 20").fetchall()
        else:
            like = f"%{q}%"
            rows = conn.execute(
                """
                SELECT * FROM stocks
                WHERE lower(ticker) LIKE ? OR lower(name) LIKE ? OR lower(sector) LIKE ? OR lower(theme) LIKE ?
                ORDER BY name
                LIMIT 30
                """,
                (like, like, like, like),
            ).fetchall()
        local_results = [row_to_dict(row) for row in rows]

    external_results: list[dict] = []
    provider_errors: list[dict] = []
    for provider in ordered_search_providers(raw_query):
        try:
            external_results.extend(provider.search(raw_query))
            if is_us_ticker_query(raw_query) and has_exact_ticker_result(external_results, raw_query):
                break
        except Exception as exc:
            provider_errors.append({"source": getattr(provider, "name", "unknown"), "error": str(exc)[:120]})

    seen = {str(item.get("ticker") or "").upper() for item in local_results if item.get("ticker")}
    merged = list(local_results)
    for item in external_results:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker or ticker.upper() in seen:
            continue
        seen.add(ticker.upper())
        merged.append(item)

    direct = direct_ticker_candidate(raw_query)
    if direct and direct["ticker"].upper() not in seen:
        merged.append(direct)

    merged = sorted(merged, key=lambda item: search_rank(item, raw_query))[:30]
    return {
        "query": q,
        "results": merged,
        "sources": ["sqlite", *[provider.name for provider in ordered_search_providers(raw_query)]],
        "errors": provider_errors,
    }


def ordered_search_providers(query: str) -> list:
    fast_names = ["financial_modeling_prep", "yahoo_finance", "finnhub", "alpha_vantage"]
    slow_names = ["finance_datareader", "pykrx"]
    by_name = {provider.name: provider for provider in EXTERNAL_PROVIDERS}
    providers = [by_name[name] for name in fast_names if name in by_name]
    # FinanceDataReader/pykrx are useful, but slower. Use them after fast sources or for Korean numeric codes.
    if is_krx_query(query) or not is_us_ticker_query(query):
        providers.extend([by_name[name] for name in slow_names if name in by_name])
    return providers


def is_us_ticker_query(query: str) -> bool:
    return re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-]{0,9}", query.strip() or "") is not None


def is_krx_query(query: str) -> bool:
    return re.fullmatch(r"\d{5,6}", query.strip() or "") is not None


def direct_ticker_candidate(query: str) -> dict | None:
    clean = query.strip().upper()
    if not clean:
        return None
    if is_us_ticker_query(clean):
        return {
            "ticker": clean,
            "name": clean,
            "market": "US",
            "sector": "미분류",
            "industry": "일반",
            "theme": "일반",
            "source": "direct_ticker",
        }
    if is_krx_query(clean):
        return {
            "ticker": clean.zfill(6),
            "name": clean.zfill(6),
            "market": "KRX",
            "sector": "미분류",
            "industry": "일반",
            "theme": "일반",
            "source": "direct_ticker",
        }
    return None


def is_derivative_symbol(ticker: str) -> bool:
    return re.search(r"[A-Z]{1,8}\d{6}[CP]\d{8}", (ticker or "").upper()) is not None


def market_rank(item: dict) -> int:
    ticker = str(item.get("ticker") or "").upper()
    market = str(item.get("market") or "").upper()
    if any(key in market for key in ("NASDAQ", "NYSE", "AMEX", "NYSEARCA", "US")):
        return 0
    if any(key in market for key in ("KRX", "KOSPI", "KOSDAQ")):
        return 1
    if market == "OPR" or is_derivative_symbol(ticker):
        return 20
    if re.search(r"\.[A-Z]{2,4}$", ticker):
        return 8
    return 4


def source_rank(item: dict) -> int:
    source = str(item.get("source") or "")
    if source in ("financial_modeling_prep", "yahoo_finance", "finnhub"):
        return 0
    if source == "direct_ticker":
        return 2
    return 4


def has_exact_ticker_result(items: list[dict], query: str) -> bool:
    q = query.strip().upper()
    return any(str(item.get("ticker") or "").upper() == q and not is_derivative_symbol(str(item.get("ticker") or "")) for item in items)


def search_rank(item: dict, query: str) -> tuple[int, int, int, str]:
    q = query.strip().upper()
    ticker = str(item.get("ticker") or "").upper()
    name = str(item.get("name") or "").upper()
    if ticker == q:
        base = 0
    elif ticker.startswith(q):
        base = 1
    elif q and q in name:
        base = 2
    else:
        base = 5
    derivative = 20 if is_derivative_symbol(ticker) else 0
    return (base, market_rank(item) + derivative, source_rank(item), ticker or name)

def stock_metrics(ticker: str, force: bool = False) -> dict:
    with db() as conn:
        stock = row_to_dict(conn.execute("SELECT * FROM stocks WHERE ticker = ?", (ticker,)).fetchone())
        metrics = row_to_dict(conn.execute("SELECT * FROM stock_metrics WHERE ticker = ?", (ticker,)).fetchone())
        if force or metrics_needs_external(metrics):
            for provider in EXTERNAL_PROVIDERS:
                external = provider.metrics(ticker)
                if not external:
                    continue
                upsert_external_metrics(conn, ticker, external)
                metrics = row_to_dict(conn.execute("SELECT * FROM stock_metrics WHERE ticker = ?", (ticker,)).fetchone())
                if not stock:
                    stock = row_to_dict(conn.execute("SELECT * FROM stocks WHERE ticker = ?", (ticker,)).fetchone())
                if not metrics_has_fill_gaps(metrics):
                    break
        if not stock and not metrics:
            raise ApiError(404, "stock_not_found")
        if metrics:
            metrics = derive_metrics_values(metrics)
        return {"stock": stock, "metrics": metrics or {}, "missing_as_null": True}


def stock_prices(ticker: str, period: str = "1y") -> dict:
    period = period if period in {"1d", "1mo", "3mo", "6mo", "1y", "5y"} else "1y"
    with db() as conn:
        cached = cached_prices(conn, ticker, period)
        if cached:
            return cached
    providers = sorted(PRICE_PROVIDERS, key=lambda provider: 0 if period == "1d" and getattr(provider, "name", "") == "yahoo_finance" else 1)
    interval = "5m" if period == "1d" else "1d"
    for provider in providers:
        prices = getattr(provider, "prices", None)
        if not prices:
            continue
        payload = prices(ticker, period=period, interval=interval)
        if payload and payload.get("items"):
            with db() as conn:
                upsert_prices(conn, ticker, period, payload)
            return payload
    with db() as conn:
        fallback = fallback_prices(conn, ticker, period)
        if fallback:
            return fallback
    raise ApiError(404, "prices_not_found")


def fallback_prices(conn: sqlite3.Connection, ticker: str, period: str) -> dict | None:
    metrics = row_to_dict(conn.execute("SELECT * FROM stock_metrics WHERE ticker = ?", (ticker,)).fetchone()) or {}
    stock = row_to_dict(conn.execute("SELECT * FROM stocks WHERE ticker = ?", (ticker,)).fetchone()) or {}
    price = metrics.get("price") or stock.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    days = {"1d": 1, "1mo": 22, "3mo": 66, "6mo": 126, "1y": 252, "5y": 1260}.get(period, 252)
    ytd = metrics.get("ytd") if isinstance(metrics.get("ytd"), (int, float)) else 0.08
    start = price / max(0.2, 1 + ytd)
    today = datetime.now().date()
    items = []
    for index in range(days):
        ratio = index / max(1, days - 1)
        wave = math.sin(ratio * math.pi * 4) * 0.035 + math.sin(ratio * math.pi * 9) * 0.018
        close = max(0.01, start + (price - start) * ratio + price * wave)
        day = today - timedelta(days=days - index - 1)
        items.append({"date": day.isoformat(), "close": round(close, 4), "volume": None})
    return {
        "ticker": ticker,
        "period": period,
        "source": "local_chart_fallback",
        "cached": False,
        "collected_at": now_iso(),
        "items": items,
    }


def cached_prices(conn: sqlite3.Connection, ticker: str, period: str) -> dict | None:
    rows = conn.execute(
        """
        SELECT * FROM stock_prices
        WHERE ticker = ? AND period = ?
        ORDER BY price_date
        """,
        (ticker, period),
    ).fetchall()
    if not rows:
        return None
    first_row = row_to_dict(rows[0]) or {}
    collected_at = parse_dt(first_row.get("collected_at"))
    ttl = timedelta(minutes=10) if period == "1d" else timedelta(hours=12)
    if not collected_at or datetime.now(timezone.utc).astimezone() - collected_at > ttl:
        return None
    items = [
        {"date": row["price_date"], "close": row["close"], "volume": row["volume"]}
        for row in rows
    ]
    return {
        "ticker": ticker,
        "period": period,
        "source": first_row.get("source") or "sqlite_cache",
        "cached": True,
        "collected_at": first_row.get("collected_at"),
        "items": items,
    }


def upsert_prices(conn: sqlite3.Connection, ticker: str, period: str, payload: dict) -> None:
    collected_at = now_iso()
    items = [
        item
        for item in payload.get("items", [])
        if item.get("date") and isinstance(item.get("close"), (int, float))
    ]
    rows = [
        (
            ticker,
            period,
            item.get("date"),
            item.get("close"),
            item.get("volume"),
            payload.get("source"),
            collected_at,
        )
        for item in items
    ]
    if not rows:
        return
    conn.execute("DELETE FROM stock_prices WHERE ticker = ? AND period = ?", (ticker, period))
    conn.executemany(
        """
        INSERT OR REPLACE INTO stock_prices
        (ticker, period, price_date, close, volume, source, collected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    update_metrics_from_prices(conn, ticker, items, payload.get("source"), collected_at)
    conn.commit()


def update_metrics_from_prices(conn: sqlite3.Connection, ticker: str, items: list[dict], source: str | None, collected_at: str) -> None:
    values = [item["close"] for item in items]
    latest = values[-1]
    first = values[0]
    d1 = latest / values[-2] - 1 if len(values) > 1 and values[-2] else None
    m1 = latest / values[-22] - 1 if len(values) > 21 and values[-22] else None
    ytd = latest / first - 1 if first else None
    existing = row_to_dict(conn.execute("SELECT * FROM stock_metrics WHERE ticker = ?", (ticker,)).fetchone()) or {}
    merged = {
        **existing,
        "ticker": ticker,
        "price": latest,
        "high52": max(values),
        "low52": min(values),
        "d1": d1,
        "m1": m1,
        "ytd": ytd,
        "source": source or existing.get("source") or "price_history",
        "collected_at": collected_at,
    }
    merged = derive_metrics_values(merged)
    conn.execute(
        """
        INSERT OR REPLACE INTO stock_metrics
        (ticker, price, per, pbr, forward_pe, roe, eps, bps, dividend_yield, market_cap,
         trading_value, high52, low52, d1, m1, ytd, revenue_growth, operating_income_growth,
         net_income_growth, operating_margin, debt_ratio, target_price_high, target_price_low,
         target_price_avg, upside_pct, investment_opinion_avg, report_count, source, collected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticker,
            merged.get("price"),
            merged.get("per"),
            merged.get("pbr"),
            merged.get("forward_pe"),
            merged.get("roe"),
            merged.get("eps"),
            merged.get("bps"),
            merged.get("dividend_yield"),
            merged.get("market_cap"),
            merged.get("trading_value"),
            merged.get("high52"),
            merged.get("low52"),
            merged.get("d1"),
            merged.get("m1"),
            merged.get("ytd"),
            merged.get("revenue_growth"),
            merged.get("operating_income_growth"),
            merged.get("net_income_growth"),
            merged.get("operating_margin"),
            merged.get("debt_ratio"),
            merged.get("target_price_high"),
            merged.get("target_price_low"),
            merged.get("target_price_avg"),
            merged.get("upside_pct"),
            merged.get("investment_opinion_avg"),
            merged.get("report_count"),
            merged.get("source"),
            merged.get("collected_at"),
        ),
    )


def parse_dt(value: str | int | float | None) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).astimezone()
        except Exception:
            return None
    clean = str(value).strip()
    if clean.isdigit():
        try:
            return datetime.fromtimestamp(int(clean), tz=timezone.utc).astimezone()
        except Exception:
            return None
    try:
        return datetime.fromisoformat(clean)
    except ValueError:
        return None


def metrics_needs_external(metrics: dict | None) -> bool:
    if not metrics:
        return True
    collected_at = parse_dt(metrics.get("collected_at"))
    if not collected_at:
        return True
    age = datetime.now(timezone.utc).astimezone() - collected_at
    # PER/PBR/ROE are core. If these are missing, try providers immediately.
    if any(metrics.get(key) is None for key in ["per", "pbr", "roe"]):
        return True
    # Optional fields are refreshed by the manual full-refresh button to avoid slow detail loading.
    return age > timedelta(days=7)


def core_metrics_have_gaps(metrics: dict | None) -> bool:
    if not metrics:
        return True
    # Negative ROE is valid data. Only None means missing.
    needed = ["per", "pbr", "roe", "forward_pe", "target_price_avg"]
    return any(metrics.get(key) is None for key in needed)


def metrics_has_fill_gaps(metrics: dict | None) -> bool:
    if not metrics:
        return True
    needed = ["per", "pbr", "roe", "forward_pe", "target_price_avg"]
    return any(metrics.get(key) is None for key in needed)


def derive_metrics_values(metrics: dict) -> dict:
    result = dict(metrics or {})
    price = result.get("price")
    eps = result.get("eps")
    bps = result.get("bps")
    if result.get("per") is None and isinstance(price, (int, float)) and isinstance(eps, (int, float)) and eps > 0:
        result["per"] = price / eps
    if result.get("pbr") is None and isinstance(price, (int, float)) and isinstance(bps, (int, float)) and bps > 0:
        result["pbr"] = price / bps
    source = str(result.get("source") or "").lower()
    roe = result.get("roe")
    if isinstance(roe, (int, float)) and source in {"financial_modeling_prep", "yahoo_finance", "alpha_vantage"} and 0 < abs(roe) <= 5:
        result["roe"] = roe * 100
    if result.get("roe") is None and isinstance(eps, (int, float)) and isinstance(bps, (int, float)) and bps != 0:
        result["roe"] = eps / bps * 100
    target = result.get("target_price_avg")
    high = result.get("target_price_high")
    low = result.get("target_price_low")
    if target is None and isinstance(high, (int, float)) and isinstance(low, (int, float)):
        result["target_price_avg"] = (high + low) / 2
        target = result["target_price_avg"]
    if result.get("upside_pct") is None and isinstance(target, (int, float)) and isinstance(price, (int, float)) and price > 0:
        result["upside_pct"] = target / price - 1
    return result


def upsert_external_metrics(conn: sqlite3.Connection, ticker: str, metrics: dict) -> None:
    collected_at = now_iso()
    conn.execute(
        """
        INSERT OR IGNORE INTO stocks
        (ticker, name, market, sector, industry, theme, currency, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticker,
            ticker,
            metrics.get("external_symbol"),
            None,
            None,
            None,
            None,
            metrics.get("source"),
            collected_at,
        ),
    )
    fields = {
        "price": metrics.get("price"),
        "per": metrics.get("per"),
        "pbr": metrics.get("pbr"),
        "forward_pe": metrics.get("forward_pe"),
        "roe": metrics.get("roe"),
        "eps": metrics.get("eps"),
        "bps": metrics.get("bps"),
        "dividend_yield": metrics.get("dividend_yield"),
        "market_cap": metrics.get("market_cap"),
        "high52": metrics.get("high52"),
        "low52": metrics.get("low52"),
        "target_price_high": metrics.get("target_price_high"),
        "target_price_low": metrics.get("target_price_low"),
        "target_price_avg": metrics.get("target_price_avg"),
        "upside_pct": metrics.get("upside_pct"),
        "investment_opinion_avg": metrics.get("investment_opinion_avg"),
        "report_count": metrics.get("report_count"),
        "source": metrics.get("source"),
        "collected_at": collected_at,
    }
    existing = row_to_dict(conn.execute("SELECT * FROM stock_metrics WHERE ticker = ?", (ticker,)).fetchone()) or {}
    merged = derive_metrics_values({**existing, **{key: value for key, value in fields.items() if value is not None}})
    conn.execute(
        """
        INSERT OR REPLACE INTO stock_metrics
        (ticker, price, per, pbr, forward_pe, roe, eps, bps, dividend_yield, market_cap,
         high52, low52, target_price_high, target_price_low, target_price_avg, upside_pct,
         investment_opinion_avg, report_count, source, collected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticker,
            merged.get("price"),
            merged.get("per"),
            merged.get("pbr"),
            merged.get("forward_pe"),
            merged.get("roe"),
            merged.get("eps"),
            merged.get("bps"),
            merged.get("dividend_yield"),
            merged.get("market_cap"),
            merged.get("high52"),
            merged.get("low52"),
            merged.get("target_price_high"),
            merged.get("target_price_low"),
            merged.get("target_price_avg"),
            merged.get("upside_pct"),
            merged.get("investment_opinion_avg"),
            merged.get("report_count"),
            merged.get("source"),
            merged.get("collected_at"),
        ),
    )
    conn.commit()



def market_indicators() -> dict:
    cached_at = MARKET_INDICATORS_CACHE.get("created_at")
    if cached_at and MARKET_INDICATORS_CACHE.get("payload") and datetime.now(timezone.utc).astimezone() - cached_at < timedelta(minutes=10):
        return MARKET_INDICATORS_CACHE["payload"]

    provider = next((item for item in PRICE_PROVIDERS if getattr(item, "name", "") == "yahoo_finance"), None)
    configs = [
        {"label": "VIX", "symbol": "^VIX", "digits": 2},
        {"label": "USD/KRW", "symbol": "KRW=X", "digits": 2},
    ]
    items = []
    if provider:
        for config in configs:
            try:
                payload = provider.prices(config["symbol"], period="5d", interval="1d")
                if not payload:
                    continue
                points = payload.get("items") or []
                closes = [point.get("close") for point in points if isinstance(point.get("close"), (int, float))]
                price = payload.get("regular_market_price")
                if not isinstance(price, (int, float)) and closes:
                    price = closes[-1]
                previous = closes[-2] if len(closes) >= 2 else None
                change_pct = price / previous - 1 if isinstance(price, (int, float)) and isinstance(previous, (int, float)) and previous else None
                if isinstance(price, (int, float)):
                    items.append({
                        "label": config["label"],
                        "value": f"{price:,.{config['digits']}f}",
                        "change_pct": change_pct,
                        "source": "yahoo_finance",
                    })
            except Exception:
                continue

    payload = {"items": items, "generated_at": now_iso()}
    MARKET_INDICATORS_CACHE["created_at"] = datetime.now(timezone.utc).astimezone()
    MARKET_INDICATORS_CACHE["payload"] = payload
    return payload

def watchlist_metrics(tickers: list[str]) -> dict:
    return {"tickers": tickers, "items": [stock_metrics(ticker) for ticker in tickers]}


def compare_stocks(tickers: list[str]) -> dict:
    return {"tickers": tickers, "items": [stock_metrics(ticker) for ticker in tickers]}


def economic_calendar() -> dict:
    events = [
        {"date": "2026-05-08", "time_et": "08:30", "event": "Employment Situation", "label": "고용보고서", "category": "고용", "impact": "고용이 강하면 금리 인하 기대가 약해질 수 있고, 약하면 경기 둔화 우려와 금리 인하 기대가 동시에 커질 수 있습니다.", "source": "BLS", "url": "https://www.bls.gov/schedule/news_release/empsit.htm"},
        {"date": "2026-05-12", "time_et": "08:30", "event": "Consumer Price Index", "label": "CPI", "category": "물가", "impact": "물가가 높으면 성장주 밸류에이션에 부담, 낮으면 금리 인하 기대에 우호적일 수 있습니다.", "source": "BLS", "url": "https://www.bls.gov/schedule/news_release/cpi.htm"},
        {"date": "2026-05-14", "time_et": "08:30", "event": "Advance Monthly Retail Sales", "label": "소매판매", "category": "소비", "impact": "소비 강도는 경기 체력과 기업 매출 기대를 가늠하는 데 중요합니다.", "source": "FRED/Census", "url": "https://fred.stlouisfed.org/releases/calendar?rid=9&y=2026"},
        {"date": "2026-05-28", "time_et": "08:30", "event": "GDP Second Estimate / Corporate Profits", "label": "GDP 2차 추정", "category": "성장", "impact": "성장률과 기업이익 흐름은 경기 민감 업종과 시장 전체 이익 전망에 영향을 줍니다.", "source": "BEA", "url": "https://www.bea.gov/news/schedule"},
        {"date": "2026-05-28", "time_et": "08:30", "event": "Personal Income and Outlays", "label": "PCE/개인소득", "category": "물가", "impact": "PCE는 연준이 중시하는 물가 지표라 금리 전망에 직접 연결됩니다.", "source": "BEA", "url": "https://www.bea.gov/news/schedule"},
        {"date": "2026-06-16~2026-06-17", "time_et": "14:00", "event": "FOMC Meeting", "label": "FOMC", "category": "금리", "impact": "정책금리, 점도표, 기자회견 발언이 성장주와 채권금리, 달러에 큰 영향을 줄 수 있습니다.", "source": "Federal Reserve", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"},
    ]
    return {"country": "US", "timezone": "ET", "items": events, "source_note": "BLS, BEA, Federal Reserve, FRED/Census official schedules"}
def market_news() -> dict:
    cached_at = MARKET_NEWS_CACHE.get("created_at")
    if cached_at and datetime.now(timezone.utc).astimezone() - cached_at < timedelta(minutes=45):
        return MARKET_NEWS_CACHE["payload"]
    provider = GoogleNewsProvider()
    seen_titles = set()
    seen_urls = set()
    items = []
    for topic, query in MARKET_NEWS_QUERIES:
        for item in provider.search(query, limit=8):
            if not is_recent_news(item.get("published_at")):
                continue
            title = item.get("title") or ""
            url = canonical_url(item.get("url", ""))
            title_key = title_fingerprint(title)
            if not title or not url or url in seen_urls or title_key in seen_titles:
                continue
            seen_urls.add(url)
            seen_titles.add(title_key)
            summary = summarize_market_news(topic, title, item.get("summary"))
            ai_summary = summarize_news_with_ai(title, item.get("summary") or summary["ai_summary"], summary["tags"])
            if ai_summary:
                summary = ai_summary
            items.append(
                {
                    "title": title,
                    "publisher": item.get("publisher") or item.get("source") or provider.name,
                    "published_at": item.get("published_at"),
                    "url": url,
                    "summary": summary["ai_summary"],
                    "ai_summary": summary["ai_summary"],
                    "sentiment": summary["sentiment"],
                    "tags": summary["tags"],
                    "topic": topic,
                    "related_tickers": infer_related_tickers(f"{title} {item.get('summary') or ''}") or ["시장공통"],
                }
            )
    items.sort(key=lambda item: item.get("published_at") or "", reverse=True)
    payload = {"items": items[:18], "lookback_days": NEWS_LOOKBACK_DAYS, "sources": [provider.name], "deduped": True}
    MARKET_NEWS_CACHE["created_at"] = datetime.now(timezone.utc).astimezone()
    MARKET_NEWS_CACHE["payload"] = payload
    return payload



def infer_related_tickers(text: str, limit: int = 8) -> list[str]:
    raw = text or ""
    raw_upper = raw.upper()
    compact = "".join(ch for ch in raw.lower() if ch.isalnum() or "가" <= ch <= "힣")
    alias_rows: list[tuple[str, str]] = []
    try:
        with db() as conn:
            alias_rows.extend((str(row["ticker"] or ""), str(row["name"] or "")) for row in conn.execute("SELECT ticker, name FROM stocks ORDER BY name LIMIT 600").fetchall())
    except Exception:
        pass
    try:
        frontend_text = (ROOT_DIR / "assets" / "data.js").read_text(encoding="utf-8")
        match = re.search(r"window\.STOCK_DATA\s*=\s*(\{.*\});?\s*$", frontend_text, flags=re.S)
        frontend = json.loads(match.group(1)) if match else {"stocks": []}
        for item in frontend.get("stocks", []):
            ticker = str(item.get("ticker") or item.get("gfKey") or item.get("nameKr") or "").strip()
            for name in [item.get("nameKr"), item.get("nameEn"), item.get("name")]:
                if ticker and name:
                    alias_rows.append((ticker, str(name)))
    except Exception:
        pass
    matched: list[str] = []
    for ticker, name in alias_rows:
        ticker = str(ticker or "").strip()
        name = str(name or "").strip()
        ticker_key = "".join(ch for ch in ticker.upper() if ch.isalnum())
        name_key = "".join(ch for ch in name.lower() if ch.isalnum() or "가" <= ch <= "힣")
        ticker_hit = False
        if ticker_key.isdigit() and len(ticker_key) >= 4:
            ticker_hit = ticker_key in raw_upper
        elif len(ticker_key) >= 2:
            ticker_hit = re.search(rf"(?<![A-Z0-9]){re.escape(ticker_key)}(?![A-Z0-9])", raw_upper) is not None
        if ticker_hit:
            matched.append(ticker)
        else:
            stripped_name = re.sub(r"\b(inc|incorporated|corporation|corp|ltd|limited|plc|co|company|class|common|stock)\b", " ", name.lower())
            stripped_key = "".join(ch for ch in stripped_name if ch.isalnum() or "가" <= ch <= "힣")
            if name and name != ticker and ((len(name_key) >= 3 and name_key in compact) or (len(stripped_key) >= 3 and stripped_key in compact)):
                matched.append(ticker)
        if len(matched) >= limit:
            break
    seen = set()
    unique = []
    for ticker in matched:
        if ticker in seen:
            continue
        seen.add(ticker)
        unique.append(ticker)
    return unique

def summarize_market_news(topic: str, title: str, summary: str | None = None) -> dict:
    text = f"{title or ''} {summary or ''}".lower()
    impact = "시장 전체에 영향을 줄 수 있는 거시 이슈입니다."
    sentiment = "neutral"
    tags = [topic]
    if any(word in text for word in ["fed", "fomc", "interest rate", "rate cut", "rate hike", "금리", "연준"]):
        tags.append("금리")
        impact = "연준과 금리 기대를 바꿀 수 있어 성장주와 기술주 전반에 영향을 줄 수 있습니다."
    if any(word in text for word in ["jobs", "payroll", "employment", "unemployment", "고용"]):
        tags.append("고용")
        impact = "고용 지표는 금리 전망을 흔들 수 있어 시장 전체 변동성을 키울 수 있습니다."
    if any(word in text for word in ["cpi", "pce", "inflation", "물가", "인플레이션"]):
        tags.append("물가")
        impact = "물가 지표는 금리 인하 기대와 밸류에이션에 직접 영향을 줄 수 있습니다."
    if any(word in text for word in ["tariff", "tariffs", "trade", "regulation", "관세", "규제"]):
        tags.append("정책")
        impact = "정책과 관세 이슈는 업종별 비용과 수요 전망을 바꿀 수 있습니다."
    if any(word in text for word in ["treasury", "yield", "dollar", "oil", "국채", "달러", "유가"]):
        tags.append("금융여건")
        impact = "국채금리, 달러, 유가는 위험자산 선호와 업종별 수익성에 영향을 줄 수 있습니다."
    if any(word in text for word in ["rises", "higher", "hot", "strong", "상승", "강세"]):
        sentiment = "negative" if any(tag in tags for tag in ["금리", "물가", "금융여건"]) else "neutral"
    if any(word in text for word in ["falls", "lower", "cool", "weak", "하락", "둔화"]):
        sentiment = "positive" if any(tag in tags for tag in ["금리", "물가"]) else "neutral"
    return {"ai_summary": impact, "sentiment": sentiment, "tags": sorted(set(tags))}


def frontend_aliases_for_ticker(ticker: str) -> list[str]:
    key = str(ticker or "").strip().upper()
    if not hasattr(frontend_aliases_for_ticker, "cache"):
        cache: dict[str, list[str]] = {}
        try:
            frontend_text = (ROOT_DIR / "assets" / "data.js").read_text(encoding="utf-8")
            match = re.search(r"window\.STOCK_DATA\s*=\s*(\{.*\});?\s*$", frontend_text, flags=re.S)
            frontend = json.loads(match.group(1)) if match else {"stocks": []}
            for item in frontend.get("stocks", []):
                symbols = [item.get("ticker"), item.get("gfKey"), item.get("nameKr")]
                names = [item.get("nameKr"), item.get("nameEn"), item.get("name")]
                for symbol in symbols:
                    if not symbol:
                        continue
                    cache.setdefault(str(symbol).strip().upper(), [])
                    for name in names:
                        if name and str(name) not in cache[str(symbol).strip().upper()]:
                            cache[str(symbol).strip().upper()].append(str(name))
        except Exception:
            cache = {}
        frontend_aliases_for_ticker.cache = cache
    return getattr(frontend_aliases_for_ticker, "cache", {}).get(key, [])
def news_matches_stock(title: str | None, summary: str | None, ticker: str, name: str | None = None) -> bool:
    text = f"{title or ''} {summary or ''}"
    if not ticker:
        return True
    if "최신 뉴스 검색" in text:
        return True
    upper = text.upper()
    compact = "".join(ch for ch in text.lower() if ch.isalnum() or "가" <= ch <= "힣")
    symbol = str(ticker or "").strip().upper()
    if ":" in symbol:
        symbol = symbol.split(":")[-1]
    if symbol.endswith(".KS") or symbol.endswith(".KQ"):
        symbol = symbol.split(".")[0]
    symbol_key = "".join(ch for ch in symbol if ch.isalnum())
    if symbol_key.isdigit() and len(symbol_key) <= 6:
        if symbol_key.zfill(6) in upper:
            return True
    elif len(symbol_key) >= 2 and re.search(rf"(?<![A-Z0-9]){re.escape(symbol_key)}(?![A-Z0-9])", upper):
        return True
    aliases = [str(name or "").strip(), *frontend_aliases_for_ticker(ticker)]
    stripped = re.sub(r"\b(inc|incorporated|corporation|corp|ltd|limited|plc|co|company|class|common|stock|holdings|holding)\b", " ", aliases[0].lower()) if aliases[0] else ""
    aliases.append(stripped)
    for alias in aliases:
        alias_key = "".join(ch for ch in alias.lower() if ch.isalnum() or "가" <= ch <= "힣")
        if len(alias_key) >= 3 and alias_key in compact:
            return True
    return False
def stock_news(ticker: str) -> dict:
    with db() as conn:
        ensure_news(conn, ticker)
        stock = row_to_dict(conn.execute("SELECT * FROM stocks WHERE ticker = ?", (ticker,)).fetchone()) or {}
        name = stock.get("name") or ticker
        rows = conn.execute(
            """
            SELECT * FROM stock_news
            WHERE ticker = ?
              AND publisher NOT IN (?, ?, ?)
            ORDER BY id DESC
            LIMIT 60
            """,
            (ticker, *NEWS_PLACEHOLDER_PUBLISHERS),
        ).fetchall()
        items = [normalize_news(row_to_dict(row)) for row in rows]
        items = [item for item in items if is_recent_news(item.get("published_at")) and news_matches_stock(item.get("title"), item.get("ai_summary") or item.get("summary"), ticker, name)]
        if not items:
            rows = conn.execute(
                """
                SELECT * FROM stock_news
                WHERE ticker = ?
                ORDER BY id DESC
                LIMIT 20
                """,
                (ticker,),
            ).fetchall()
            items = [normalize_news(row_to_dict(row)) for row in rows]
            items = [item for item in items if news_matches_stock(item.get("title"), item.get("ai_summary") or item.get("summary"), ticker, name)]
        items = sorted(items, key=lambda item: parse_dt(item.get("published_at")) or parse_dt(item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return {
            "ticker": ticker,
            "items": items[:20],
            "cache_ttl_minutes": 60,
            "sources": [provider.name for provider in NEWS_PROVIDERS],
        }

def stock_news_summary(ticker: str) -> dict:
    payload = stock_news(ticker)
    items = payload.get("items", [])
    with db() as conn:
        stock = row_to_dict(conn.execute("SELECT * FROM stocks WHERE ticker = ?", (ticker,)).fetchone()) or {}
    summary = summarize_stock_news_bundle_with_ai(ticker, stock.get("name") or ticker, items)
    return {
        "ticker": ticker,
        "summary": summary or {
            "source": "empty",
            "headline": "최근 뉴스가 없습니다.",
            "sentiment": "neutral",
            "key_issues": [],
            "watch_points": [],
            "reason": "뉴스 API 기준 최근 2일 내 수집된 기사가 없습니다.",
            "articles": [],
        },
        "item_count": len(items),
    }


def ensure_news(conn: sqlite3.Connection, ticker: str) -> None:
    newest = row_to_dict(
        conn.execute(
            """
            SELECT created_at FROM stock_news
            WHERE ticker = ?
              AND publisher NOT IN ('검색 fallback', '뉴스 검색 링크', '리서치 확인 링크')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (ticker,),
        ).fetchone()
    )
    newest_at = parse_dt((newest or {}).get("created_at"))
    if newest_at and datetime.now(timezone.utc).astimezone() - newest_at < timedelta(hours=1):
        return
    stock = row_to_dict(conn.execute("SELECT * FROM stocks WHERE ticker = ?", (ticker,)).fetchone()) or {}
    name = stock.get("name") or ticker
    related = json.dumps([ticker], ensure_ascii=False)
    created_at = news_now_iso()
    inserted = 0
    seen_urls = set()
    seen_titles = set()
    for provider in NEWS_PROVIDERS:
        for item in provider.news(ticker, name):
            title = item.get("title")
            url = canonical_url(item.get("url", ""))
            if not title or not url:
                continue
            if not is_recent_news(item.get("published_at")):
                continue
            if not news_matches_stock(title, item.get("summary"), ticker, name):
                continue
            title_key = title_fingerprint(title)
            if url in seen_urls or title_key in seen_titles:
                continue
            seen_urls.add(url)
            seen_titles.add(title_key)
            summary = summarize_news(title, item.get("summary"))
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO stock_news
                (ticker, title, publisher, published_at, url, summary, related_tickers, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker,
                    title,
                    item.get("publisher") or item.get("source") or provider.name,
                    str(item.get("published_at") or created_at),
                    url,
                    json.dumps(summary, ensure_ascii=False),
                    related,
                    created_at,
                ),
            )
            if cursor.rowcount == 0:
                existing = row_to_dict(conn.execute("SELECT related_tickers FROM stock_news WHERE url = ?", (url,)).fetchone())
                try:
                    tickers = set(json.loads((existing or {}).get("related_tickers") or "[]"))
                except Exception:
                    tickers = set()
                tickers.add(ticker)
                conn.execute("UPDATE stock_news SET related_tickers = ? WHERE url = ?", (json.dumps(sorted(tickers), ensure_ascii=False), url))
            inserted += cursor.rowcount
            if inserted >= 8:
                break
        if inserted >= 8:
            break
    if not inserted:
        fallback = summarize_news(f"{name} 최신 뉴스 검색", "뉴스 API 키가 없거나 수집 결과가 없어 검색 링크를 제공합니다.")
        conn.execute(
            """
            INSERT OR IGNORE INTO stock_news
            (ticker, title, publisher, published_at, url, summary, related_tickers, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticker,
                f"{name} 최신 뉴스 검색",
                "검색 fallback",
                created_at,
                f"https://www.google.com/search?tbm=nws&q={ticker}+{name}+주식",
                json.dumps(fallback, ensure_ascii=False),
                related,
                created_at,
            ),
        )
    conn.commit()


def news_cutoff_iso() -> str:
    return (datetime.now(timezone.utc).astimezone() - timedelta(days=NEWS_LOOKBACK_DAYS)).isoformat(timespec="seconds")


def is_recent_news(value: str | None) -> bool:
    published_at = parse_dt(value)
    if not published_at:
        return True
    return datetime.now(timezone.utc).astimezone() - published_at <= timedelta(days=NEWS_LOOKBACK_DAYS)



def stock_analysis(ticker: str, mode: str = 'app') -> dict:
    metrics_payload = stock_metrics(ticker)
    stock = metrics_payload.get("stock") or {"ticker": ticker}
    metrics = metrics_payload.get("metrics") or {}
    try:
        prices = stock_prices(ticker, "6mo").get("items", [])
    except Exception:
        prices = []
    try:
        news_items = stock_news(ticker).get("items", [])[:6]
    except Exception:
        news_items = []
    if mode == "research":
        analysis = analyze_stock_research_with_ai(stock, metrics)
    else:
        analysis = analyze_stock_with_ai(stock, metrics, prices, news_items)
    if not analysis:
        analysis = fallback_stock_analysis(stock, metrics, prices)
    return {"ticker": ticker, "mode": mode, "analysis": analysis, "ai": ai_status(), "generated_at": now_iso()}


def fallback_stock_analysis(stock: dict, metrics: dict, prices: list[dict]) -> dict:
    closes = [item.get("close") for item in prices if isinstance(item.get("close"), (int, float))]
    trend = "가격 이력이 부족해 차트 추세 판단은 보류합니다."
    if len(closes) >= 20:
        recent = closes[-1]
        avg20 = sum(closes[-20:]) / 20
        direction = "20일 평균 위" if recent >= avg20 else "20일 평균 아래"
        trend = f"최근 종가는 20일 평균 대비 {direction}에 있습니다."
    filled = []
    missing = []
    for label, key in [("PER", "per"), ("PBR", "pbr"), ("ROE", "roe"), ("Forward PE", "forward_pe"), ("목표가", "target_price_avg")]:
        (filled if metrics.get(key) is not None else missing).append(label)
    return {
        "summary": f"{stock.get('name') or stock.get('ticker') or '선택 종목'}은 현재 지표 {len(filled)}개가 채워져 있고 {len(missing)}개는 비어 있습니다.",
        "trend": trend,
        "strategy": "아래 3단 시나리오를 기준으로 검토하세요.",
        "strategies": {
            "conservative": {"trigger": "지지선 확인 및 변동성 완화", "action": "소량 분할 접근 또는 관망", "invalidation": "지지선 이탈", "comment": "데이터가 부족할수록 보수적 접근이 유리합니다."},
            "neutral": {"trigger": "20일 평균 회복 또는 박스권 상단 돌파", "action": "분할 진입 후 짧은 손절 기준 설정", "invalidation": "돌파 실패 후 이전 저점 이탈", "comment": "차트와 지표 확인을 병행합니다."},
            "aggressive": {"trigger": "거래량 동반 단기 저항 돌파", "action": "작은 비중으로 추세 추종", "invalidation": "돌파 가격 아래로 빠른 되돌림", "comment": "손절 기준을 먼저 정해야 합니다."},
        },
        "question": "AI 응답 실패 또는 제한으로 기본 3단 전략을 표시합니다.",
        "source": "fallback",
        "risks": ["목표가와 일부 밸류 지표가 비어 있으면 판단 신뢰도가 낮아집니다.", "뉴스 이벤트나 실적 발표 전후에는 변동성이 커질 수 있습니다."],
        "checklist": ["최근 차트 고점과 저점 확인", "PBR/ROE/Forward PE 채움 여부 확인", "최근 뉴스와 실적 일정 확인", "진입가와 손절가를 먼저 정하기"],
    }
def watchlist_news(tickers: list[str]) -> dict:
    seen_urls = set()
    seen_titles = set()
    items = []
    errors = []
    for ticker in tickers:
        try:
            ticker_items = stock_news(ticker)["items"]
        except Exception as exc:
            errors.append({"ticker": ticker, "error": str(exc)[:120]})
            ticker_items = []
        for item in ticker_items:
            title_key = title_fingerprint(item.get("title", ""))
            if item["url"] in seen_urls or title_key in seen_titles:
                for existing in items:
                    if existing["url"] == item["url"] or title_fingerprint(existing.get("title", "")) == title_key:
                        existing["related_tickers"] = sorted(set(existing["related_tickers"] + [ticker]))
                continue
            seen_urls.add(item["url"])
            seen_titles.add(title_key)
            items.append(item)
    return {"tickers": tickers, "items": items, "deduped": True, "errors": errors}


def normalize_news(row: dict) -> dict:
    try:
        related = json.loads(row.get("related_tickers") or "[]")
    except Exception:
        related = [row.get("ticker")]
    try:
        summary = json.loads(row.get("summary") or "{}")
    except Exception:
        summary = {"ai_summary": row.get("summary") or "", "sentiment": "neutral", "tags": ["일반"]}
    row["related_tickers"] = related
    row["ai_summary"] = summary.get("ai_summary", "")
    row["sentiment"] = summary.get("sentiment", "neutral")
    row["tags"] = summary.get("tags", ["일반"])
    return row


def recalculate_quant(tickers: list[str], weights: dict) -> dict:
    with db() as conn:
        if tickers:
            rows = conn.execute(
                f"SELECT * FROM stock_metrics WHERE ticker IN ({','.join('?' for _ in tickers)})",
                tickers,
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM stock_metrics").fetchall()
        items = []
        for row in rows:
            metrics = row_to_dict(row)
            scores = score_metrics(metrics, weights)
            conn.execute(
                """
                INSERT OR REPLACE INTO quant_scores
                (ticker, value_score, quality_score, momentum_score, growth_score, stability_score, total_score, calculated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metrics["ticker"],
                    scores["value_score"],
                    scores["quality_score"],
                    scores["momentum_score"],
                    scores["growth_score"],
                    scores["stability_score"],
                    scores["total_score"],
                    scores["calculated_at"],
                ),
            )
            items.append({"ticker": metrics["ticker"], **scores})
        conn.commit()
        return {"weights": weights, "items": sorted(items, key=lambda item: item["total_score"], reverse=True)}


def quant_rank(limit: int = 50) -> dict:
    recalculate_quant([], DEFAULT_WEIGHTS)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT q.*, s.name, s.market, s.sector, s.theme
            FROM quant_scores q
            LEFT JOIN stocks s ON s.ticker = q.ticker
            ORDER BY q.total_score DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return {"items": [row_to_dict(row) for row in rows], "weights": DEFAULT_WEIGHTS}


def quant_score(ticker: str) -> dict:
    result = recalculate_quant([ticker], DEFAULT_WEIGHTS)
    if not result["items"]:
        raise ApiError(404, "stock_not_found")
    return result["items"][0]


def classification_suggest(ticker: str) -> dict:
    with db() as conn:
        stock = row_to_dict(conn.execute("SELECT * FROM stocks WHERE ticker = ?", (ticker,)).fetchone())
        if not stock:
            raise ApiError(404, "stock_not_found")
        rows = conn.execute(
            """
            SELECT sector, theme, COUNT(*) AS count
            FROM stocks
            WHERE sector IS NOT NULL AND theme IS NOT NULL
            GROUP BY sector, theme
            ORDER BY
              CASE WHEN sector = ? THEN 0 ELSE 1 END,
              count DESC
            LIMIT 5
            """,
            (stock.get("sector"),),
        ).fetchall()
        return {"ticker": ticker, "current": stock, "suggestions": [row_to_dict(row) for row in rows]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Woobin Stock API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8787, type=int)
    args = parser.parse_args()
    with db():
        pass
    print(f"Woobin Stock running at http://{args.host}:{args.port}")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()

































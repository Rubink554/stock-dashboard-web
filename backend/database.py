from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_JS = ROOT_DIR / "assets" / "data.js"
DB_PATH = ROOT_DIR / "backend" / "woobin_stock.sqlite3"


SAMPLE_STOCKS = []


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS stocks (
            ticker TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            market TEXT,
            sector TEXT,
            industry TEXT,
            theme TEXT,
            currency TEXT,
            source TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL UNIQUE,
            memo TEXT,
            tags TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS stock_metrics (
            ticker TEXT PRIMARY KEY,
            price REAL,
            per REAL,
            pbr REAL,
            forward_pe REAL,
            roe REAL,
            eps REAL,
            bps REAL,
            dividend_yield REAL,
            market_cap REAL,
            trading_value REAL,
            high52 REAL,
            low52 REAL,
            d1 REAL,
            m1 REAL,
            ytd REAL,
            revenue_growth REAL,
            operating_income_growth REAL,
            net_income_growth REAL,
            operating_margin REAL,
            debt_ratio REAL,
            target_price_high REAL,
            target_price_low REAL,
            target_price_avg REAL,
            upside_pct REAL,
            investment_opinion_avg REAL,
            report_count INTEGER,
            source TEXT,
            collected_at TEXT
        );

        CREATE TABLE IF NOT EXISTS stock_news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            title TEXT NOT NULL,
            publisher TEXT,
            published_at TEXT,
            url TEXT NOT NULL,
            summary TEXT,
            related_tickers TEXT,
            created_at TEXT,
            UNIQUE(url)
        );

        CREATE TABLE IF NOT EXISTS stock_prices (
            ticker TEXT NOT NULL,
            period TEXT NOT NULL,
            price_date TEXT NOT NULL,
            close REAL NOT NULL,
            volume REAL,
            source TEXT,
            collected_at TEXT,
            PRIMARY KEY (ticker, period, price_date)
        );

        CREATE TABLE IF NOT EXISTS quant_scores (
            ticker TEXT PRIMARY KEY,
            value_score REAL,
            quality_score REAL,
            momentum_score REAL,
            growth_score REAL,
            stability_score REAL,
            total_score REAL,
            calculated_at TEXT
        );
        """
    )
    conn.commit()


def _load_frontend_data() -> dict:
    text = DATA_JS.read_text(encoding="utf-8")
    match = re.search(r"window\.STOCK_DATA\s*=\s*(\{.*\});?\s*$", text, flags=re.S)
    if not match:
        return {"stocks": []}
    return json.loads(match.group(1))


def seed_db(conn: sqlite3.Connection) -> None:
    init_db(conn)
    collected_at = now_iso()
    if not conn.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]:
        frontend = _load_frontend_data()
        for item in frontend.get("stocks", []):
            ticker = item.get("ticker") or item.get("gfKey") or item.get("nameKr")
            if not ticker:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO stocks
                (ticker, name, market, sector, industry, theme, currency, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(ticker),
                    item.get("nameKr") or item.get("nameEn") or str(ticker),
                    item.get("exchange") or ("PRIVATE" if item.get("status") != "LISTED" else "UNKNOWN"),
                    item.get("part"),
                    item.get("theme"),
                    item.get("theme"),
                    item.get("currency"),
                    "excel_data_js",
                    collected_at,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO stock_metrics
                (ticker, price, per, market_cap, high52, low52, d1, m1, ytd, source, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(ticker),
                    item.get("price"),
                    item.get("per"),
                    item.get("marketCap"),
                    item.get("high52"),
                    item.get("low52"),
                    item.get("d1"),
                    item.get("m1"),
                    item.get("ytd"),
                    "excel_data_js",
                    collected_at,
                ),
            )

    for sample in SAMPLE_STOCKS:
        upsert_sample(conn, sample, collected_at)
    conn.commit()


def upsert_sample(conn: sqlite3.Connection, sample: dict, collected_at: str | None = None) -> None:
    collected_at = collected_at or now_iso()
    conn.execute(
        """
        INSERT OR REPLACE INTO stocks
        (ticker, name, market, sector, industry, theme, currency, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sample["ticker"],
            sample["name"],
            sample["market"],
            sample["sector"],
            sample["industry"],
            sample["theme"],
            "KRW",
            "sample_seed",
            collected_at,
        ),
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO stock_metrics
        (ticker, per, pbr, forward_pe, roe, eps, bps, dividend_yield, market_cap,
         target_price_high, target_price_low, target_price_avg, investment_opinion_avg,
         report_count, source, collected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sample["ticker"],
            sample["per"],
            sample["pbr"],
            sample["forward_pe"],
            sample["roe"],
            sample["eps"],
            sample["bps"],
            sample["dividend_yield"],
            sample["market_cap"],
            sample["target_price_high"],
            sample["target_price_low"],
            sample["target_price_avg"],
            sample["investment_opinion_avg"],
            sample["report_count"],
            "sample_seed",
            collected_at,
        ),
    )
    seed_news(conn, sample["ticker"], sample["name"], collected_at)


def seed_news(conn: sqlite3.Connection, ticker: str, name: str, created_at: str) -> None:
    rows = [
        (
            ticker,
            f"{name} latest news search",
            "News search link",
            created_at,
            f"https://www.google.com/search?tbm=nws&q={ticker}+{name}+stock",
            "Fallback news search link for this ticker.",
            json.dumps([ticker], ensure_ascii=False),
            created_at,
        ),
        (
            ticker,
            f"{name} earnings and consensus check",
            "Research search link",
            created_at,
            f"https://www.google.com/search?q={ticker}+{name}+earnings+consensus",
            "Fallback research search link for earnings and consensus checks.",
            json.dumps([ticker], ensure_ascii=False),
            created_at,
        ),
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO stock_news
        (ticker, title, publisher, published_at, url, summary, related_tickers, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )

def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return None if row is None else {key: row[key] for key in row.keys()}





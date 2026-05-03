from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database import connect, init_db, seed_db
from backend.server import stock_metrics, stock_news, stock_prices


DEFAULT_PERIODS = ["1mo", "3mo", "6mo", "1y"]


def load_tickers(limit: int | None = None) -> list[str]:
    with connect() as conn:
        init_db(conn)
        seed_db(conn)
        query = "SELECT ticker FROM stocks WHERE ticker IS NOT NULL AND ticker != '' ORDER BY ticker"
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = conn.execute(query).fetchall()
    return [row["ticker"] for row in rows]


def refresh_ticker(ticker: str, periods: list[str], include_news: bool) -> dict:
    result = {"ticker": ticker, "metrics": False, "prices": [], "news": False, "errors": []}
    try:
        stock_metrics(ticker)
        result["metrics"] = True
    except Exception as exc:
        result["errors"].append(f"metrics: {exc}")
    for period in periods:
        try:
            stock_prices(ticker, period)
            result["prices"].append(period)
        except Exception as exc:
            result["errors"].append(f"prices {period}: {exc}")
    if include_news:
        try:
            stock_news(ticker)
            result["news"] = True
        except Exception as exc:
            result["errors"].append(f"news: {exc}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh stock metrics, price history, and news caches.")
    parser.add_argument("--tickers", default="", help="Comma-separated tickers. If omitted, all known tickers are refreshed.")
    parser.add_argument("--periods", default=",".join(DEFAULT_PERIODS), help="Comma-separated chart periods.")
    parser.add_argument("--limit", type=int, default=0, help="Refresh only the first N tickers when --tickers is omitted.")
    parser.add_argument("--skip-news", action="store_true", help="Skip news refresh.")
    args = parser.parse_args()

    periods = [item.strip() for item in args.periods.split(",") if item.strip()]
    tickers = [item.strip() for item in args.tickers.split(",") if item.strip()] or load_tickers(args.limit or None)
    print(f"Refreshing {len(tickers)} tickers: {', '.join(tickers[:10])}{'...' if len(tickers) > 10 else ''}")
    for ticker in tickers:
        result = refresh_ticker(ticker, periods, include_news=not args.skip_news)
        status = "ok" if not result["errors"] else "partial"
        print(f"{ticker}: {status} metrics={result['metrics']} prices={','.join(result['prices']) or '-'} news={result['news']}")
        for error in result["errors"]:
            print(f"  - {error}")


if __name__ == "__main__":
    main()

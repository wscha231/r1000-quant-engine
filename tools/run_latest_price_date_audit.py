#!/usr/bin/env python3
"""P0 freshness hygiene: audit the latest cached price bar vs the audit date.

The 26491652391 baseline review found the broker-ledger replay ended on
2026-05-22 while the run date was 2026-05-27 — a silent 3-trading-day gap that
made "latest" metrics look current when they were stale. This audit makes that
gap loud: it scans the replay price cache for benchmark + target-book tickers,
finds the most recent cached bar, counts business days between that bar and the
audit date, and raises a ``STALE_PRICE_REVIEW`` flag when the gap exceeds the
threshold (default 2 trading days).

Research/ops tool. Read-only; never mutates data or production policy.

Output: outputs/latest_price_date_audit.json
  {
    "status": "ok" | "STALE_PRICE_REVIEW" | "blocked",
    "stale_trading_days": int,
    "latest_cached_bar_date": "YYYY-MM-DD",
    "audit_date": "YYYY-MM-DD",
    "per_ticker": {ticker: latest_bar_date},
    ...
  }

Note: business-day counting uses pandas bdate_range (weekdays). US market
holidays can overstate the gap by one day; the threshold check is therefore
conservative (it can flag one day early, never late).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import load_price_series  # noqa: E402


BENCHMARK_TICKERS = ("SPY", "QQQ")
DEFAULT_OUTPUT = "outputs/latest_price_date_audit.json"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def book_tickers(latest_run: Path, max_tickers: int) -> list[str]:
    """Sample tickers from operating target books so the audit covers what we trade."""
    tickers: list[str] = []
    for name in (
        "reports/operating_main_target_book.csv",
        "reports/operating_concentrated_target_book.csv",
    ):
        path = latest_run / name
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, usecols=lambda c: c in {"ticker"}, low_memory=False)
        except Exception:
            continue
        for raw in frame.get("ticker", pd.Series(dtype=str)).astype(str):
            ticker = raw.upper().strip()
            if ticker and ticker not in {"CASH"} and ticker not in tickers:
                tickers.append(ticker)
    return tickers[: max(0, int(max_tickers))]


def parse_ticker_list(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        raw_items = str(value).replace(";", ",").split(",")
    out: list[str] = []
    for raw in raw_items:
        ticker = str(raw).upper().strip()
        if ticker and ticker not in {"CASH", "__CASH__"} and ticker not in out:
            out.append(ticker)
    return out


def latest_bar_date(price_cache: Path, ticker: str) -> pd.Timestamp | None:
    px = load_price_series(price_cache, ticker)
    if px.empty:
        return None
    idx = pd.to_datetime(px.index, errors="coerce").dropna()
    if idx.empty:
        return None
    return pd.Timestamp(idx.max()).normalize()


def stale_trading_days_between(latest_bar: pd.Timestamp, audit_date: pd.Timestamp) -> int:
    """Business days strictly after latest_bar, up to and including audit_date."""
    if latest_bar >= audit_date:
        return 0
    days = pd.bdate_range(latest_bar + pd.Timedelta(days=1), audit_date)
    return int(len(days))


def run_audit(
    *,
    price_cache: Path,
    latest_run: Path,
    audit_date: pd.Timestamp,
    stale_threshold: int,
    max_book_tickers: int,
    extra_tickers: list[str] | None = None,
) -> dict[str, Any]:
    tickers: list[str] = []
    for ticker in list(BENCHMARK_TICKERS) + parse_ticker_list(extra_tickers) + book_tickers(latest_run, max_book_tickers):
        if ticker not in tickers:
            tickers.append(ticker)
    per_ticker: dict[str, str] = {}
    missing: list[str] = []
    dates: list[pd.Timestamp] = []
    for ticker in tickers:
        bar = latest_bar_date(price_cache, ticker)
        if bar is None:
            missing.append(ticker)
            continue
        per_ticker[ticker] = bar.date().isoformat()
        dates.append(bar)

    if not dates:
        return {
            "status": "blocked",
            "reason": "no cached price series found for any audited ticker",
            "audited_tickers": tickers,
            "missing_tickers": missing,
            "price_cache": str(price_cache),
            "audit_date": audit_date.date().isoformat(),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "research_only": True,
        }

    overall_latest = max(dates)
    benchmark_dates = [d for t, d in zip(tickers, dates) if t in BENCHMARK_TICKERS]
    # The benchmark is the canonical freshness anchor: book tickers can lag for
    # legitimate reasons (halts, delists), but SPY/QQQ must be current.
    anchor = max(benchmark_dates) if benchmark_dates else overall_latest
    stale_days = stale_trading_days_between(anchor, audit_date)
    flagged = stale_days > int(stale_threshold)
    return {
        "status": "STALE_PRICE_REVIEW" if flagged else "ok",
        "stale_price_review": flagged,
        "stale_trading_days": stale_days,
        "stale_trading_days_threshold": int(stale_threshold),
        "latest_cached_bar_date": overall_latest.date().isoformat(),
        "benchmark_anchor_date": anchor.date().isoformat(),
        "audit_date": audit_date.date().isoformat(),
        "per_ticker": per_ticker,
        "missing_tickers": missing,
        "audited_ticker_count": len(tickers),
        "extra_tickers": parse_ticker_list(extra_tickers),
        "price_cache": str(price_cache),
        "bday_note": "weekday counting; US holidays may overstate by <=1 day (conservative)",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--audit-date", default="", help="YYYY-MM-DD; defaults to today (UTC).")
    parser.add_argument("--stale-trading-days-threshold", type=int, default=2)
    parser.add_argument("--max-book-tickers", type=int, default=40)
    parser.add_argument("--extra-tickers", default="", help="Comma-separated additional tickers that must be included in the freshness audit, e.g. hedge instruments.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit_date = (
        pd.Timestamp(args.audit_date).normalize()
        if args.audit_date
        else pd.Timestamp(datetime.now(timezone.utc).date())
    )
    payload = run_audit(
        price_cache=repo_path(args.price_cache),
        latest_run=repo_path(args.latest_run),
        audit_date=audit_date,
        stale_threshold=args.stale_trading_days_threshold,
        max_book_tickers=args.max_book_tickers,
        extra_tickers=parse_ticker_list(args.extra_tickers),
    )
    out = repo_path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"[price-audit] status={payload.get('status')} stale_trading_days={payload.get('stale_trading_days')} "
        f"anchor={payload.get('benchmark_anchor_date')} audit_date={payload.get('audit_date')}"
    )
    return 0 if payload.get("status") != "blocked" else 2


if __name__ == "__main__":
    sys.exit(main())

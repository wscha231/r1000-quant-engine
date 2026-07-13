#!/usr/bin/env python3
"""Fail closed unless every operating ticker has the exact session close.

The gate covers the current target books, bootstrap/persistent account
positions, unresolved pending orders, and required benchmark tickers.  A
prior-session fallback is never accepted for a daily portfolio publication.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_weekly_evaluation import load_price_series, price_on_or_before  # noqa: E402


DATE_COLUMNS = ("rebalance_date", "target_date", "as_of_date", "effective_date", "date")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def clean_ticker(value: Any) -> str:
    ticker = str(value or "").strip().upper()
    return "" if ticker in {"", "NAN", "NONE", "CASH"} else ticker


def latest_target_tickers(path: Path, session_date: pd.Timestamp) -> set[str]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    frame = pd.read_csv(path, low_memory=False)
    if frame.empty or "ticker" not in frame.columns:
        return set()
    for column in DATE_COLUMNS:
        if column not in frame.columns:
            continue
        dates = pd.to_datetime(frame[column], errors="coerce").dt.tz_localize(None).dt.normalize()
        eligible = dates.notna() & (dates <= session_date)
        if eligible.any():
            latest = dates[eligible].max()
            frame = frame[dates.eq(latest)].copy()
        break
    return {ticker for ticker in frame["ticker"].map(clean_ticker) if ticker}


def account_tickers(path: Path) -> set[str]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    tickers: set[str] = set()
    positions = payload.get("positions") if isinstance(payload, dict) else []
    if not isinstance(positions, list):
        return tickers
    for row in positions:
        if not isinstance(row, dict):
            continue
        ticker = clean_ticker(row.get("ticker"))
        quantity = row.get("shares", row.get("quantity", row.get("current_shares", 0)))
        try:
            held = float(quantity) > 0
        except (TypeError, ValueError):
            held = False
        if ticker and held:
            tickers.add(ticker)
    return tickers


def pending_tickers(state_dir: Path) -> set[str]:
    tickers: set[str] = set()
    if not state_dir.exists():
        return tickers
    for path in sorted(state_dir.glob("*/pending_orders.csv")):
        if not path.exists() or path.stat().st_size == 0:
            continue
        frame = pd.read_csv(path, low_memory=False)
        if frame.empty or "ticker" not in frame.columns:
            continue
        if "pending_status" in frame.columns:
            active = frame["pending_status"].astype(str).str.startswith("PENDING")
            frame = frame[active].copy()
        tickers.update(ticker for ticker in frame["ticker"].map(clean_ticker) if ticker)
    return tickers


def collect_required_tickers(
    *,
    targets: Iterable[Path],
    accounts: Iterable[Path],
    state_dir: Path,
    required_tickers: Iterable[str],
    session_date: pd.Timestamp,
) -> tuple[set[str], dict[str, list[str]]]:
    sources: dict[str, set[str]] = {}
    for path in targets:
        sources[f"target:{path.name}"] = latest_target_tickers(path, session_date)
    for path in accounts:
        sources[f"account:{path.name}"] = account_tickers(path)
    for path in sorted(state_dir.glob("*/account_state_latest.json")) if state_dir.exists() else []:
        sources[f"state_account:{path.parent.name}"] = account_tickers(path)
    sources["pending_orders"] = pending_tickers(state_dir)
    sources["required"] = {ticker for ticker in map(clean_ticker, required_tickers) if ticker}
    tickers = set().union(*sources.values()) if sources else set()
    return tickers, {name: sorted(values) for name, values in sources.items() if values}


def evaluate_close_coverage(*, price_cache: Path, session_date: pd.Timestamp, tickers: Iterable[str]) -> dict[str, Any]:
    session = session_date.normalize()
    rows: list[dict[str, Any]] = []
    for ticker in sorted(set(tickers)):
        prices = load_price_series(price_cache, ticker)
        actual_date, close = price_on_or_before(prices, session, "close")
        actual = pd.Timestamp(actual_date).normalize() if actual_date is not None else None
        exact = bool(
            actual is not None
            and actual == session
            and close is not None
            and math.isfinite(float(close))
            and float(close) > 0
        )
        rows.append(
            {
                "ticker": ticker,
                "required_session_date": session.date().isoformat(),
                "actual_price_date": actual.date().isoformat() if actual is not None else "",
                "close": float(close) if close is not None and math.isfinite(float(close)) else None,
                "exact_close_present": exact,
            }
        )
    missing = [row["ticker"] for row in rows if not row["exact_close_present"]]
    return {
        "schema_version": "daily-close-price-coverage-v1",
        "status": "PASS" if rows and not missing else "BLOCKED_MISSING_EXACT_CLOSE",
        "session_date": session.date().isoformat(),
        "exact_close_coverage": bool(rows and not missing),
        "required_ticker_count": len(rows),
        "exact_ticker_count": len(rows) - len(missing),
        "missing_ticker_count": len(missing),
        "missing_tickers": missing,
        "rows": rows,
        "prior_session_fallback_allowed": False,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    session = pd.Timestamp(args.session_date).normalize()
    if pd.isna(session):
        raise ValueError("--session-date must be a completed NYSE session date")
    tickers, sources = collect_required_tickers(
        targets=[repo_path(path) for path in args.target],
        accounts=[repo_path(path) for path in args.account],
        state_dir=repo_path(args.state_dir),
        required_tickers=args.required_ticker,
        session_date=session,
    )
    payload = evaluate_close_coverage(price_cache=repo_path(args.price_cache), session_date=session, tickers=tickers)
    payload["ticker_sources"] = sources
    output = repo_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows_path = output.with_name("close_price_coverage.csv")
    pd.DataFrame(payload["rows"]).to_csv(rows_path, index=False)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--account", action="append", default=[])
    parser.add_argument("--state-dir", default="outputs/daily_simulated_fill_ledger")
    parser.add_argument("--required-ticker", action="append", default=[])
    parser.add_argument("--output", default="outputs/daily_market_session_gate/close_price_coverage.json")
    return parser.parse_args()


def main() -> int:
    try:
        payload = run(parse_args())
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["exact_close_coverage"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

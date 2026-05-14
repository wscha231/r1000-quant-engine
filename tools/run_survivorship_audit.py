#!/usr/bin/env python3
"""Survivorship audit (2026-05-14 hard-gate F2).

Verify the price cache covers historical R1000 constituents that have since
been delisted, acquired, or dropped from the index. Without this audit,
broker_ledger_replay over 7+ years can only see survivors -- inflating
CAGR and hiding MaxDD.

What it does
============
    1. Load historical_universe_membership.{csv,parquet,xlsx} -- the full set
       of (rebalance_date, ticker) pairs that ever appeared in the
       reconstructed R1000 universe.
    2. Build the set of historically-present tickers (>=1 month, >=1 year, or
       a configurable minimum-tenure threshold).
    3. For each historically-present ticker, check the price cache for usable
       data coverage during its tenure window.
    4. Emit `outputs/audit/survivorship_coverage.json` with:
         - delisted_count                  (tickers never appearing in latest month)
         - delisted_covered_count          (have at least min_days of cache during tenure)
         - delisted_uncovered_count        (cache-missing or sparse)
         - survivor_count                  (still in latest month)
         - coverage_ratio                  (delisted_covered / delisted_count)
         - delisted_uncovered              (list of missing tickers, capped at 50 for log size)
         - sample_delisted                 (first 50 delisted tickers with coverage stats)

Hard gate flip
==============
    broker_accounting_audit.survivorship_coverage_audited flips TRUE when:
      coverage_ratio >= --coverage-threshold (default 0.85)
      AND delisted_count >= --min-delisted-count (default 100)
    Until then, gate remains FALSE.

Usage
=====
    python tools/run_survivorship_audit.py
    python tools/run_survivorship_audit.py \\
        --membership data_raw/historical_universe_membership.csv \\
        --price-cache cache_prices \\
        --output outputs/audit/survivorship_coverage.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def safe_load_membership(path: Path):
    """Load a historical universe membership table. Returns a DataFrame with
    columns at least: ticker, rebalance_date. Returns empty DataFrame on
    failure (missing file, parse error, etc.) -- the audit then emits an
    empty report rather than crashing the workflow.
    """
    import pandas as pd

    if not path.exists():
        return pd.DataFrame(columns=["ticker", "rebalance_date"])
    try:
        suffix = path.suffix.lower()
        if suffix == ".parquet":
            df = pd.read_parquet(path)
        elif suffix in {".xls", ".xlsx"}:
            df = pd.read_excel(path)
        else:
            df = pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame(columns=["ticker", "rebalance_date"])
    if "ticker" not in df.columns or "rebalance_date" not in df.columns:
        # Try common alternatives.
        if "Ticker" in df.columns:
            df = df.rename(columns={"Ticker": "ticker"})
        if "Symbol" in df.columns:
            df = df.rename(columns={"Symbol": "ticker"})
        if "date" in df.columns and "rebalance_date" not in df.columns:
            df = df.rename(columns={"date": "rebalance_date"})
    if "ticker" not in df.columns or "rebalance_date" not in df.columns:
        return pd.DataFrame(columns=["ticker", "rebalance_date"])
    out = df[["ticker", "rebalance_date"]].copy()
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")
    out = out.dropna(subset=["ticker", "rebalance_date"])
    out = out[out["ticker"] != ""]
    return out.drop_duplicates(["ticker", "rebalance_date"]).reset_index(drop=True)


def price_cache_coverage(price_cache: Path, ticker: str) -> dict[str, Any]:
    """Inspect a single ticker's price cache parquet (or csv fallback) and
    return a tiny dict: {has_data, num_days, first_date, last_date}.
    Cheap operation -- reads only the column index, not the full series.
    """
    import pandas as pd

    candidates = [
        price_cache / f"{ticker}.parquet",
        price_cache / f"{ticker}.csv",
    ]
    for cand in candidates:
        if not cand.exists():
            continue
        try:
            if cand.suffix == ".parquet":
                df = pd.read_parquet(cand, columns=["close"])
            else:
                df = pd.read_csv(cand, low_memory=False)
            if df is None or df.empty:
                continue
            if "close" not in df.columns:
                continue
            close = pd.to_numeric(df["close"], errors="coerce").dropna()
            close = close[close > 0]
            if close.empty:
                continue
            idx = pd.to_datetime(df.index, errors="coerce") if not isinstance(df.index, pd.DatetimeIndex) else df.index
            return {
                "has_data": True,
                "num_days": int(len(close)),
                "first_date": pd.Timestamp(idx.min()).date().isoformat() if pd.notna(idx.min()) else None,
                "last_date": pd.Timestamp(idx.max()).date().isoformat() if pd.notna(idx.max()) else None,
            }
        except Exception:
            continue
    return {"has_data": False, "num_days": 0, "first_date": None, "last_date": None}


def run_audit(
    *,
    membership_path: Path,
    price_cache: Path,
    output_path: Path,
    min_tenure_months: int = 1,
    min_cache_days: int = 252,
    sample_size: int = 50,
    coverage_threshold: float = 0.85,
    min_delisted_count: int = 100,
) -> dict[str, Any]:
    """Run the audit. Returns the same payload it writes to output_path."""
    import pandas as pd

    member = safe_load_membership(membership_path)
    if member.empty:
        payload = {
            "status": "blocked",
            "blocked_reason": f"membership file not found / unparseable: {membership_path}",
            "as_of_utc": datetime.now(timezone.utc).isoformat(),
            "membership_path": str(membership_path),
            "price_cache": str(price_cache),
            "delisted_count": 0,
            "delisted_covered_count": 0,
            "delisted_uncovered_count": 0,
            "survivor_count": 0,
            "coverage_ratio": None,
            "coverage_threshold": coverage_threshold,
            "min_delisted_count": min_delisted_count,
            "hard_gate_flip_eligible": False,
            "delisted_uncovered": [],
            "sample_delisted": [],
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return payload

    latest_dt = member["rebalance_date"].max()
    latest_tickers = set(member.loc[member["rebalance_date"] == latest_dt, "ticker"].tolist())

    # Tenure check: ticker counts as "historically present" only if it
    # appeared in >= min_tenure_months distinct rebalance dates.
    tenure = member.groupby("ticker")["rebalance_date"].nunique()
    historical_tickers = set(tenure[tenure >= int(min_tenure_months)].index.tolist())

    delisted_tickers = sorted(historical_tickers - latest_tickers)
    survivor_count = len(latest_tickers)

    covered: list[str] = []
    uncovered: list[str] = []
    samples: list[dict[str, Any]] = []
    for i, ticker in enumerate(delisted_tickers):
        cov = price_cache_coverage(price_cache, ticker)
        if cov["has_data"] and cov["num_days"] >= int(min_cache_days):
            covered.append(ticker)
        else:
            uncovered.append(ticker)
        if i < sample_size:
            samples.append({"ticker": ticker, **cov})

    delisted_count = len(delisted_tickers)
    coverage_ratio = (
        float(len(covered)) / float(delisted_count) if delisted_count > 0 else None
    )
    hard_gate_eligible = bool(
        delisted_count >= int(min_delisted_count)
        and coverage_ratio is not None
        and coverage_ratio >= float(coverage_threshold)
    )

    payload = {
        "status": "completed",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "membership_path": str(membership_path),
        "price_cache": str(price_cache),
        "latest_rebalance_date": pd.Timestamp(latest_dt).date().isoformat() if pd.notna(latest_dt) else None,
        "historical_tickers_count": len(historical_tickers),
        "delisted_count": delisted_count,
        "delisted_covered_count": len(covered),
        "delisted_uncovered_count": len(uncovered),
        "survivor_count": survivor_count,
        "coverage_ratio": coverage_ratio,
        "coverage_threshold": float(coverage_threshold),
        "min_delisted_count": int(min_delisted_count),
        "min_cache_days": int(min_cache_days),
        "min_tenure_months": int(min_tenure_months),
        "hard_gate_flip_eligible": hard_gate_eligible,
        "hard_gate_flip_reason": (
            "coverage_ratio >= threshold AND delisted_count >= min_delisted_count"
            if hard_gate_eligible
            else f"coverage_ratio={coverage_ratio}, threshold={coverage_threshold}, delisted_count={delisted_count}, min={min_delisted_count}"
        ),
        "delisted_uncovered": uncovered[:50],
        "delisted_uncovered_truncated": len(uncovered) > 50,
        "sample_delisted": samples,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--membership", default="data_raw/historical_universe_membership.csv")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output", default="outputs/audit/survivorship_coverage.json")
    parser.add_argument("--min-tenure-months", type=int, default=1)
    parser.add_argument("--min-cache-days", type=int, default=252)
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument("--coverage-threshold", type=float, default=0.85)
    parser.add_argument("--min-delisted-count", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run_audit(
        membership_path=Path(args.membership) if Path(args.membership).is_absolute() else REPO_ROOT / args.membership,
        price_cache=Path(args.price_cache) if Path(args.price_cache).is_absolute() else REPO_ROOT / args.price_cache,
        output_path=Path(args.output) if Path(args.output).is_absolute() else REPO_ROOT / args.output,
        min_tenure_months=args.min_tenure_months,
        min_cache_days=args.min_cache_days,
        sample_size=args.sample_size,
        coverage_threshold=args.coverage_threshold,
        min_delisted_count=args.min_delisted_count,
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

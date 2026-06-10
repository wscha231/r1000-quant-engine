#!/usr/bin/env python3
"""grade_trades - Phase 18a ad-hoc trade grading CLI.

Reads outputs/trade_journal/holdings_history.parquet, pairs entries with exits,
applies grade rules, and writes trades.parquet plus grades.parquet.

Usage
-----
    python tools/grade_trades.py
    python tools/grade_trades.py --history outputs/trade_journal/holdings_history.parquet
    python tools/grade_trades.py --print-digest
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HISTORY = REPO_ROOT / "outputs" / "trade_journal" / "holdings_history.parquet"

sys.path.insert(0, str(REPO_ROOT))

from r1000_trade_journal import (   # noqa: E402
    grade_trades,
    pair_entries_with_exits,
    summary_digest,
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--history", default=str(DEFAULT_HISTORY),
                   help="path to holdings_history.parquet")
    p.add_argument("--out-dir", default=None,
                   help="override output directory (default: parent of --history)")
    p.add_argument("--engine-version", default="manual-regrade",
                   help="engine_version tag stamped onto trades.parquet")
    p.add_argument("--print-digest", action="store_true",
                   help="print summary_digest as JSON to stdout")
    args = p.parse_args()

    history_path = Path(args.history)
    if not history_path.exists():
        print(f"[grade] ERROR: {history_path} not found", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir) if args.out_dir else history_path.parent
    paths = {"outputs": str(out_dir.parent)}

    if history_path.suffix == ".csv":
        holdings = pd.read_csv(history_path)
    else:
        holdings = pd.read_parquet(history_path)

    print(f"[grade] loaded {len(holdings)} holding rows from {history_path}")
    if "rebalance_date" in holdings.columns:
        n_dates = pd.to_datetime(holdings["rebalance_date"], errors="coerce").nunique()
        n_tickers = holdings["ticker"].nunique() if "ticker" in holdings.columns else 0
        print(f"[grade]   unique dates: {n_dates}  unique tickers: {n_tickers}")

    trades = pair_entries_with_exits(holdings, paths, args.engine_version, benchmark_returns=None)
    if trades is None or trades.empty:
        print("[grade] no trades produced (empty pairing)")
        return 1

    grades = grade_trades(trades, paths)
    digest = summary_digest(grades)

    print()
    print(f"[grade] trades:     {digest.get('n_trades')}")
    print(f"[grade] win_rate:   {digest.get('win_rate'):.3f}")
    print(f"[grade] loss_rate:  {digest.get('loss_rate'):.3f}")
    print(f"[grade] mean_ret:   {digest.get('mean_realized')}")
    print(f"[grade] median_ret: {digest.get('median_realized')}")
    print(f"[grade] labels:     {digest.get('label_counts')}")
    print(f"[grade] top wins:")
    for w in digest.get("top_wins", []):
        print(f"             {w.get('ticker'):>8}  {w.get('realized_return'):+.2%}  ({w.get('grade_label')})")
    print(f"[grade] top losses:")
    for w in digest.get("top_losses", []):
        print(f"             {w.get('ticker'):>8}  {w.get('realized_return'):+.2%}  ({w.get('grade_label')})")

    if args.print_digest:
        print()
        print(json.dumps(digest, indent=2, default=str))

    return 0


if __name__ == "__main__":
    sys.exit(main())

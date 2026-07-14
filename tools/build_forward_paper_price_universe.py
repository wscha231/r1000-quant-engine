#!/usr/bin/env python3
"""Build the bounded ticker set needed by the forward paper ledger.

The set is the union of today's fixed paper cohorts, unresolved prior ledger
observations, and the benchmark. It does not select portfolio holdings, infer
historical signals, or fetch prices itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_free_data_forward_paper_ledger import (  # noqa: E402
    CONTROL_RANK_END,
    CONTROL_RANK_START,
    COHORT_TOP_N,
    normalize_ticker,
    read_candidates,
    select_cohort_candidates,
)


SCHEMA_VERSION = "forward-paper-price-universe-v1"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pending_tickers(status_path: Path) -> set[str]:
    if not status_path.exists():
        return set()
    try:
        status = pd.read_csv(status_path, dtype=str, keep_default_na=False)
    except Exception:
        return set()
    if status.empty or "ticker" not in status.columns:
        return set()
    horizon_columns = [column for column in status.columns if column.startswith("outcome_") and column.endswith("d_status")]
    if not horizon_columns:
        return {normalize_ticker(value) for value in status["ticker"] if normalize_ticker(value)}
    unresolved = status[horizon_columns].ne("completed").any(axis=1)
    return {
        normalize_ticker(value)
        for value in status.loc[unresolved, "ticker"]
        if normalize_ticker(value)
    }


def build(
    *,
    ranked_universe: str | Path,
    current_status: str | Path,
    output_csv: str | Path,
    summary_json: str | Path,
    benchmark: str = "SPY",
) -> dict[str, Any]:
    ranked_path = repo_path(ranked_universe)
    status_path = repo_path(current_status)
    output_path = repo_path(output_csv)
    summary_path = repo_path(summary_json)
    ranked = read_candidates(ranked_path)
    cohort, audit = select_cohort_candidates(ranked)
    required_counts = {
        "base_top30": COHORT_TOP_N,
        "overlay_top30": COHORT_TOP_N,
        "matched_control_ranks31_60": CONTROL_RANK_END - CONTROL_RANK_START + 1,
    }
    blockers: list[str] = []
    if ranked.empty:
        blockers.append("ranked_universe_empty_or_unreadable")
    if "free_data_base_selection_rank" not in ranked.columns:
        blockers.append("contemporaneous_base_selection_rank_required")
    counts = audit.get("cohort_counts") or {}
    for name, expected in required_counts.items():
        actual = int(counts.get(name, 0) or 0)
        if actual != expected:
            blockers.append(f"incomplete_fixed_cohort:{name}:{actual}!={expected}")

    current = {normalize_ticker(value) for value in cohort.get("ticker", pd.Series(dtype=str))}
    current.discard("")
    pending = pending_tickers(status_path)
    benchmark_ticker = normalize_ticker(benchmark) or "SPY"
    tickers = sorted(current | pending | {benchmark_ticker})
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED_INCOMPLETE_COHORT" if blockers else "READY_FOR_BOUNDED_PRICE_REFRESH",
        "blockers": blockers,
        "ranked_universe_path": str(ranked_path),
        "ranked_universe_sha256": sha256_file(ranked_path) if ranked_path.exists() else "",
        "cohort_audit": audit,
        "required_exact_cohort_counts": required_counts,
        "current_cohort_unique_ticker_count": len(current),
        "pending_prior_unique_ticker_count": len(pending),
        "price_universe_unique_ticker_count": len(tickers),
        "benchmark_ticker": benchmark_ticker,
        "historical_signal_backfill_allowed": False,
        "portfolio_mutation_allowed": False,
        "production_allowed": False,
        "live_trading_allowed": False,
        "fullrun_allowed": False,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    if not blockers:
        sources: dict[str, list[str]] = {}
        for ticker in current:
            sources.setdefault(ticker, []).append("current_fixed_cohort")
        for ticker in pending:
            sources.setdefault(ticker, []).append("pending_prior_observation")
        sources.setdefault(benchmark_ticker, []).append("benchmark")
        frame = pd.DataFrame(
            [
                {"ticker": ticker, "source": "|".join(sorted(set(sources[ticker])))}
                for ticker in sorted(sources)
            ]
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(output_path, index=False)
        summary["output_csv"] = str(output_path)
        summary["output_sha256"] = sha256_file(output_path)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ranked-universe", required=True)
    parser.add_argument("--current-status", default="outputs/free_data_forward_paper_ledger/current_status.csv")
    parser.add_argument("--output", default="outputs/free_data_forward_paper_ledger/price_universe.csv")
    parser.add_argument("--summary", default="outputs/free_data_forward_paper_ledger/price_universe_summary.json")
    parser.add_argument("--benchmark", default="SPY")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build(
        ranked_universe=args.ranked_universe,
        current_status=args.current_status,
        output_csv=args.output,
        summary_json=args.summary,
        benchmark=args.benchmark,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "READY_FOR_BOUNDED_PRICE_REFRESH" else 2


if __name__ == "__main__":
    raise SystemExit(main())

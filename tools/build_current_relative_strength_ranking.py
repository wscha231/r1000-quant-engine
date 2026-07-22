#!/usr/bin/env python3
"""Build a review-only current ranking with benchmark-relative strength.

The tool consumes a dated scored cross-section and exact-close benchmark
returns. It recomputes the eligible universe ranking, a diversified top 30,
and a focus 15 without calling the network, a backtest, or fullrun.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_current_relative_strength_portfolios import (  # noqa: E402
    constrained_select,
    prepare_ranked,
)

SCHEMA_VERSION = "run287-current-relative-strength-ranking-v1"
HORIZONS = {
    "1d": ("ret_1d", 0.10),
    "1m": ("mom_1m", 0.35),
    "3m": ("mom_3m", 0.30),
    "6m": ("mom_6m", 0.15),
    "12m": ("mom_12m", 0.10),
}
BENCHMARKS = ("SPY", "QQQ", "SMH")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def as_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def pct_rank(series: pd.Series, *, ascending: bool = True) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    fallback = values.median() if values.notna().any() else 0.0
    return values.fillna(fallback).rank(method="average", pct=True, ascending=ascending)


def average_pct(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    available = [column for column in columns if column in frame.columns]
    if not available:
        return pd.Series(0.5, index=frame.index)
    return pd.concat([pct_rank(frame[column]) for column in available], axis=1).mean(axis=1)


def validate_benchmarks(frame: pd.DataFrame, valuation_date: str) -> pd.DataFrame:
    required = {"benchmark", "date"} | {
        f"ret_{horizon}" for horizon in HORIZONS
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("benchmark source missing columns: " + ",".join(missing))
    out = frame.copy()
    out["benchmark"] = out["benchmark"].astype(str).str.upper().str.strip()
    dates = pd.to_datetime(out["date"], errors="coerce").dt.date.astype(str)
    if not dates.eq(valuation_date).all():
        raise ValueError("benchmark returns are not from the exact valuation close")
    if set(out["benchmark"]) != set(BENCHMARKS):
        raise ValueError("benchmark source must contain exactly SPY, QQQ, and SMH")
    return out.set_index("benchmark")


def build_ranking(
    scored: pd.DataFrame,
    benchmarks: pd.DataFrame,
    *,
    valuation_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    eligibility_columns = {
        "ticker",
        "registered_ranking_eligible",
        "research_eligible_after_quarantine",
        "corporate_action_quarantine",
        "score_total",
        "current_price_live",
        "valuation_price_cutoff_date",
        "sector",
        "industry_group",
        *[column for column, _weight in HORIZONS.values()],
    }
    missing = sorted(eligibility_columns - set(scored.columns))
    if missing:
        raise ValueError("scored source missing columns: " + ",".join(missing))
    price_cutoffs = pd.to_datetime(
        scored["valuation_price_cutoff_date"], errors="coerce"
    ).dt.date.astype(str)
    if not price_cutoffs.eq(valuation_date).all():
        raise ValueError("scored source is not from the exact valuation close")
    eligible = scored.loc[
        as_bool(scored["registered_ranking_eligible"])
        & as_bool(scored["research_eligible_after_quarantine"])
        & ~as_bool(scored["corporate_action_quarantine"])
    ].copy()
    if eligible.empty:
        raise ValueError("eligible ranked universe is empty")
    eligible["ticker"] = eligible["ticker"].astype(str).str.upper().str.strip()
    if eligible["ticker"].duplicated().any():
        raise ValueError("eligible ranked universe contains duplicate tickers")
    aliases = {
        "Financial": "Financials",
        "Internet": "Communication Services",
        "Communication": "Communication Services",
        "Semiconductors": "Information Technology",
    }
    eligible["sector_normalized"] = (
        eligible["sector"].fillna("Unknown").astype(str).replace(aliases)
    )

    bench = validate_benchmarks(benchmarks, valuation_date)
    rs_components: list[pd.Series] = []
    for horizon, (stock_column, weight) in HORIZONS.items():
        stock_return = pd.to_numeric(eligible[stock_column], errors="coerce")
        for ticker in BENCHMARKS:
            benchmark_return = float(bench.loc[ticker, f"ret_{horizon}"])
            if not math.isfinite(benchmark_return):
                raise ValueError(f"invalid benchmark return: {ticker}:{horizon}")
            eligible[f"rs_{ticker.lower()}_{horizon}"] = stock_return - benchmark_return
        rs_components.append(weight * pct_rank(eligible[f"rs_spy_{horizon}"]))

    eligible["rs_composite_pct"] = sum(rs_components)
    eligible["model_pct"] = pct_rank(eligible["score_total"])
    eligible["quality_pct"] = average_pct(
        eligible,
        [
            "score_quality_core",
            "multidimensional_confirmation_score",
            "fundamental_reliability_score",
            "score_fundamental_confidence",
            "selection_confirmation_score",
        ],
    )
    eligible["trend_entry_pct"] = average_pct(
        eligible,
        [
            "minervini_trend_template_score",
            "entry_quality_score",
            "uptrend_continuation_score",
            "oneil_leadership_score",
            "price_above_ma50",
            "price_above_ma200",
        ],
    )
    eligible["risk_penalty_pct"] = average_pct(
        eligible,
        [
            "overheat_signal_score",
            "broken_momentum_penalty",
            "atr14_pct",
            "vol_252d",
            "live_event_risk_score",
            "focus_live_event_risk_penalty",
        ],
    )
    eligible["optimization_raw"] = (
        0.42 * eligible["model_pct"]
        + 0.33 * eligible["rs_composite_pct"]
        + 0.15 * eligible["quality_pct"]
        + 0.10 * eligible["trend_entry_pct"]
        - 0.08 * eligible["risk_penalty_pct"]
    )
    eligible["optimization_score"] = 100.0 * pct_rank(eligible["optimization_raw"])
    eligible["optimization_rank"] = eligible["optimization_score"].rank(
        method="first", ascending=False
    ).astype(int)

    def numeric(column: str, default: float) -> pd.Series:
        if column not in eligible.columns:
            return pd.Series(default, index=eligible.index, dtype=float)
        return pd.to_numeric(eligible[column], errors="coerce").fillna(default)

    above_50 = numeric("price_above_ma50", 0.0).ge(1)
    above_200 = numeric("price_above_ma200", 0.0).ge(1)
    broken = numeric("broken_momentum_penalty", 1.0)
    overheat = numeric("overheat_signal_score", 0.0)
    overheat_cutoff = float(overheat.quantile(0.75))
    eligible["research_status"] = np.select(
        [
            above_50
            & above_200
            & broken.le(0.375)
            & eligible["rs_spy_1m"].gt(0)
            & eligible["rs_spy_3m"].gt(0)
            & overheat.le(overheat_cutoff),
            above_200 & broken.le(0.5),
            broken.gt(0.5) | overheat.gt(overheat_cutoff),
        ],
        [
            "A_ENTRY_READY_RESEARCH",
            "B_PULLBACK_WATCH",
            "C_RISK_OR_EXTENSION_WATCH",
        ],
        default="B_TREND_REPAIR_WATCH",
    )
    eligible["production_eligible"] = False
    eligible["valuation_close_date"] = valuation_date
    ranked = prepare_ranked(eligible)
    top30 = constrained_select(ranked, count=30, sector_cap=4, industry_cap=2)
    focus15 = constrained_select(top30, count=15, sector_cap=3, industry_cap=2)
    return ranked, top30, focus15


def build(args: argparse.Namespace) -> dict[str, Any]:
    scored_path = repo_path(args.scored_latest)
    benchmark_path = repo_path(args.benchmark_returns)
    output_dir = repo_path(args.output_dir)
    ranked, top30, focus15 = build_ranking(
        pd.read_csv(scored_path, low_memory=False),
        pd.read_csv(benchmark_path),
        valuation_date=args.valuation_date,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    ranked_path = output_dir / "candidate_universe_ranked.csv"
    top30_path = output_dir / "optimized_candidates_30.csv"
    focus15_path = output_dir / "focus_candidates_15.csv"
    ranked.to_csv(ranked_path, index=False)
    top30.to_csv(top30_path, index=False)
    focus15.to_csv(focus15_path, index=False)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_REVIEW_ONLY_CURRENT_RELATIVE_STRENGTH_RANKING",
        "valuation_close_date": args.valuation_date,
        "eligible_count": int(len(ranked)),
        "optimized_candidate_count": int(len(top30)),
        "focus_candidate_count": int(len(focus15)),
        "upstream_full_bundle_ready": bool(args.upstream_full_bundle_ready),
        "selection_method": {
            "model_weight": 0.42,
            "relative_strength_weight": 0.33,
            "quality_weight": 0.15,
            "trend_entry_weight": 0.10,
            "risk_penalty_weight": 0.08,
            "relative_strength_horizon_weights": {
                horizon: weight for horizon, (_column, weight) in HORIZONS.items()
            },
            "top30_sector_cap": 4,
            "top30_industry_group_cap": 2,
            "focus15_sector_cap": 3,
            "focus15_industry_group_cap": 2,
        },
        "source_inputs": {
            "scored_latest": {"path": str(scored_path), "sha256": sha256(scored_path)},
            "benchmark_returns": {
                "path": str(benchmark_path),
                "sha256": sha256(benchmark_path),
            },
        },
        "outputs": {
            "candidate_universe_ranked": {"path": str(ranked_path), "sha256": sha256(ranked_path)},
            "optimized_candidates_30": {"path": str(top30_path), "sha256": sha256(top30_path)},
            "focus_candidates_15": {"path": str(focus15_path), "sha256": sha256(focus15_path)},
        },
        "review_only": True,
        "target_books_mutated": False,
        "orders_generated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_requests_executed": 0,
        "production_activation_allowed": False,
    }
    (output_dir / "selection_summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored-latest", required=True)
    parser.add_argument("--benchmark-returns", required=True)
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--upstream-full-bundle-ready", action="store_true")
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(
        json.dumps(
            {
                "status": payload["status"],
                "valuation_close_date": payload["valuation_close_date"],
                "eligible_count": payload["eligible_count"],
                "fullrun_executed": payload["fullrun_executed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

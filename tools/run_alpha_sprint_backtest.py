#!/usr/bin/env python3
"""Historical Alpha Sprint sidecar replay from candidate replay book."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from historical_replay_lib import (
    blocked_payload,
    calc_metrics,
    equity_curve_rows,
    infer_return_col,
    normalize_rebalance_frame,
    read_table,
    repo_path,
    safe_float,
    turnover,
    worst_month_rows,
    write_json,
    write_rows,
    write_text,
)
from r1000_alpha_sprint import ALPHA_SPRINT_POLICY, build_alpha_sprint_snapshot


DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUT_DIR = "outputs/alpha_sprint_backtest"
ACTIVE_REGIMES = {"bull", "strong_bull", "exceptional_bull"}


def replay(candidate_book: Path, output_dir: Path, cost_bps: float, allow_neutral: bool) -> dict[str, Any]:
    frame = normalize_rebalance_frame(read_table(candidate_book))
    if frame.empty:
        return blocked_payload("candidate replay book is empty", candidate_book, output_dir, "alpha_sprint_historical_sidecar")
    return_col = infer_return_col(frame)
    if return_col is None:
        return blocked_payload("candidate replay book has no period return column", candidate_book, output_dir, "alpha_sprint_historical_sidecar")

    monthly_rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []
    prev_weights: dict[str, float] = {}
    active_months = 0
    for dt, group in frame.groupby("rebalance_date", sort=True):
        rows = group.to_dict("records")
        regime = str(rows[0].get("regime_state") or "neutral")
        if allow_neutral and regime == "neutral":
            regime_for_policy = "bull"
        else:
            regime_for_policy = regime
        snapshot = build_alpha_sprint_snapshot(rows, regime_state=regime_for_policy, policy=ALPHA_SPRINT_POLICY)
        weights = {str(k): float(v) for k, v in (snapshot.get("portfolio", {}).get("weights") or {}).items()}
        score_lookup = {
            str(item.get("ticker") or "").upper(): safe_float(item.get("alpha_sprint_score"))
            for item in (snapshot.get("candidates") or [])
        }
        if regime not in ACTIVE_REGIMES and not allow_neutral:
            weights = {}
        active_months += 1 if weights else 0
        lookup = {str(row.get("ticker") or "").upper(): row for row in rows}
        turn = turnover(prev_weights, weights)
        gross_return = 0.0
        for ticker, weight in weights.items():
            source = lookup.get(ticker, {})
            raw_ret = safe_float(source.get(return_col), 0.0)
            clipped_ret = max(raw_ret, safe_float(ALPHA_SPRINT_POLICY.get("hard_stop"), -0.07))
            gross_return += weight * clipped_ret
            holding_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "weight": weight,
                    "period_forward_return": raw_ret,
                    "risk_clipped_return": clipped_ret,
                    "weighted_forward_return": weight * clipped_ret,
                    "regime_state": regime,
                    "alpha_sprint_score": score_lookup.get(ticker, ""),
                    "rs_acceleration_score": source.get("rs_acceleration_score", ""),
                    "breakout_setup_quality_score": source.get("breakout_setup_quality_score", ""),
                    "explosion_entry_score": source.get("explosion_entry_score", ""),
                    "explosion_exit_score": source.get("explosion_exit_score", ""),
                }
            )
        cost = turn * (cost_bps / 10000.0)
        monthly_rows.append(
            {
                "rebalance_date": dt,
                "regime_state": regime,
                "active": bool(weights),
                "gross_return": gross_return,
                "cost": cost,
                "turnover": turn,
                "net_return": gross_return - cost,
                "n_positions": len(weights),
                "selected_tickers": ",".join(weights.keys()),
            }
        )
        prev_weights = weights

    curve = equity_curve_rows(monthly_rows)
    metrics = calc_metrics([safe_float(row.get("net_return")) for row in monthly_rows])
    metrics.update(
        {
            "experiment_id": "alpha_sprint_historical_sidecar",
            "status": "completed" if active_months else "inactive_no_bull_months_or_candidates",
            "data_mode": "historical_candidate_replay_book",
            "candidate_book": str(candidate_book),
            "return_column": return_col,
            "active_months": active_months,
            "allow_neutral_proxy": allow_neutral,
            "research_only": True,
            "production_activation_allowed": False,
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metrics.json", metrics)
    write_rows(output_dir / "monthly.csv", monthly_rows)
    write_rows(output_dir / "holdings.csv", holding_rows)
    write_rows(output_dir / "equity_curve.csv", curve)
    write_rows(output_dir / "stress_windows.csv", worst_month_rows(curve))
    write_text(output_dir / "replay_report.md", render_report(metrics))
    return metrics


def render_report(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Alpha Sprint Historical Sidecar",
            "",
            "Bull-only research replay for short-horizon explosive candidates.",
            "",
            f"- Status: `{metrics.get('status')}`",
            f"- Active months: {metrics.get('active_months')}",
            f"- CAGR contribution stream: {safe_float(metrics.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
            "",
            "This remains a sidecar until it improves the unified orchestrator replay after costs.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--cost-bps", type=float, default=50.0)
    parser.add_argument("--allow-neutral-proxy", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    candidate_book = repo_path(args.candidate_book) if args.candidate_book else latest_run / "reports" / "candidate_replay_book.csv"
    output_dir = repo_path(args.output_dir)
    if not candidate_book.exists():
        blocked_payload("missing reports/candidate_replay_book.csv from full rebuild", candidate_book, output_dir, "alpha_sprint_historical_sidecar")
        return 0
    replay(candidate_book, output_dir, cost_bps=args.cost_bps, allow_neutral=args.allow_neutral_proxy)
    print(f"[alpha-sprint-backtest] wrote {output_dir / 'metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Historical research replay for Main v2.

This runner requires `reports/candidate_replay_book.csv` from a full rebuild.
It does not alter production defaults. It reselects Main v2 core/future/early
sleeves for every rebalance month and computes a challenger return stream.
"""
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

from r1000_main_v2 import MAIN_V2_BALANCED_POLICY, compose_main_sleeve_portfolio


DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUT_DIR = "outputs/main_v2_backtest"


def row_lookup(frame_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("ticker") or "").upper(): row for row in frame_rows if row.get("ticker")}


def replay(candidate_book: Path, output_dir: Path, cost_bps: float) -> dict[str, Any]:
    frame = normalize_rebalance_frame(read_table(candidate_book))
    if frame.empty:
        return blocked_payload("candidate replay book is empty", candidate_book, output_dir, "main_v2_historical_replay")
    return_col = infer_return_col(frame)
    if return_col is None:
        return blocked_payload("candidate replay book has no period return column", candidate_book, output_dir, "main_v2_historical_replay")

    monthly_rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []
    turnover_rows: list[dict[str, Any]] = []
    prev_weights: dict[str, float] = {}
    for dt, group in frame.groupby("rebalance_date", sort=True):
        rows = group.to_dict("records")
        lookup = row_lookup(rows)
        result = compose_main_sleeve_portfolio(rows, policy=MAIN_V2_BALANCED_POLICY)
        weights = {str(k): float(v) for k, v in (result.get("main_v2_weights") or {}).items()}
        score_lookup = {}
        for sleeve_items in (result.get("selected_by_sleeve") or {}).values():
            for item in sleeve_items:
                ticker = str(item.get("ticker") or "").upper()
                if ticker:
                    score_lookup[ticker] = max(safe_float(score_lookup.get(ticker)), safe_float(item.get("score")))
        month_turnover = turnover(prev_weights, weights)
        gross_return = 0.0
        selected_names: list[str] = []
        for ticker, weight in weights.items():
            source = lookup.get(ticker, {})
            period_return = safe_float(source.get(return_col), 0.0)
            gross_return += weight * period_return
            selected_names.append(ticker)
            holding_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "weight": weight,
                    "period_forward_return": period_return,
                    "weighted_forward_return": weight * period_return,
                    "main_v2_score": score_lookup.get(ticker, ""),
                    "score": source.get("score", ""),
                    "sector": source.get("sector", ""),
                    "regime_state": result.get("regime_state"),
                    "risk_penalty": source.get("risk_penalty", ""),
                    "stage2_overext_penalty": source.get("stage2_overext_penalty", ""),
                    "explosion_exit_score": source.get("explosion_exit_score", ""),
                    "rs_acceleration_score": source.get("rs_acceleration_score", ""),
                }
            )
        cost = month_turnover * (cost_bps / 10000.0)
        net_return = gross_return - cost
        monthly_rows.append(
            {
                "rebalance_date": dt,
                "regime_state": result.get("regime_state"),
                "gross_return": gross_return,
                "cost": cost,
                "turnover": month_turnover,
                "net_return": net_return,
                "cash_weight": result.get("cash_target"),
                "n_positions": len(weights),
                "selected_tickers": ",".join(selected_names),
            }
        )
        turnover_rows.append({"rebalance_date": dt, "turnover": month_turnover, "cost": cost})
        prev_weights = weights

    curve = equity_curve_rows(monthly_rows)
    metrics = calc_metrics([safe_float(row.get("net_return")) for row in monthly_rows])
    metrics.update(
        {
            "experiment_id": "main_v2_historical_replay",
            "status": "completed",
            "data_mode": "historical_candidate_replay_book",
            "candidate_book": str(candidate_book),
            "return_column": return_col,
            "avg_cash_weight": sum(safe_float(row.get("cash_weight")) for row in monthly_rows) / max(len(monthly_rows), 1),
            "avg_turnover_monthly": sum(safe_float(row.get("turnover")) for row in monthly_rows) / max(len(monthly_rows), 1),
            "research_only": True,
            "production_activation_allowed": False,
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metrics.json", metrics)
    write_rows(output_dir / "monthly_holdings.csv", holding_rows)
    write_rows(output_dir / "equity_curve.csv", curve)
    write_rows(output_dir / "turnover.csv", turnover_rows)
    write_rows(output_dir / "stress_windows.csv", worst_month_rows(curve))
    write_text(output_dir / "replay_report.md", render_report(metrics))
    return metrics


def render_report(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Main v2 Historical Replay",
            "",
            "Research-only challenger replay. Production defaults are unchanged.",
            "",
            f"- Status: `{metrics.get('status')}`",
            f"- Months: {metrics.get('months')}",
            f"- CAGR: {safe_float(metrics.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
            f"- Avg cash: {safe_float(metrics.get('avg_cash_weight')):.2%}",
            f"- Avg monthly turnover: {safe_float(metrics.get('avg_turnover_monthly')):.2%}",
            "",
            "Promotion requires comparison against the same-run legacy main metrics and strict target gates.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--cost-bps", type=float, default=50.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    candidate_book = repo_path(args.candidate_book) if args.candidate_book else latest_run / "reports" / "candidate_replay_book.csv"
    output_dir = repo_path(args.output_dir)
    if not candidate_book.exists():
        blocked_payload("missing reports/candidate_replay_book.csv from full rebuild", candidate_book, output_dir, "main_v2_historical_replay")
        return 0
    replay(candidate_book, output_dir, cost_bps=args.cost_bps)
    print(f"[main-v2-backtest] wrote {output_dir / 'metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

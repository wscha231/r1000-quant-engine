#!/usr/bin/env python3
"""Historical concentrated policy replay from the candidate replay book."""
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
    score_power_weights,
    turnover,
    worst_month_rows,
    write_json,
    write_rows,
    write_text,
)
from r1000_concentrated_policy import (
    CONCENTRATED_POLICY_BY_REGIME,
    concentrated_conviction_score,
    entry_gate_flags,
    monster_early_score,
    risk_gate_flags,
    risk_entry_block_score,
)


DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUT_DIR = "outputs/concentrated_policy_replay"


def candidate_passes(row: dict[str, Any]) -> bool:
    return all(entry_gate_flags(row, CONCENTRATED_POLICY_BY_REGIME.get("entry")).values()) and all(risk_gate_flags(row).values())


def select_candidates(rows: list[dict[str, Any]], target_n: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        if not ticker or ticker == "CASH":
            continue
        item = dict(row)
        item["concentrated_conviction_score"] = concentrated_conviction_score(item)
        if item["concentrated_conviction_score"] <= 0:
            continue
        if not candidate_passes(item):
            continue
        selected.append(item)
    selected.sort(key=lambda row: safe_float(row.get("concentrated_conviction_score")), reverse=True)
    return selected[:target_n]


def run_variant(frame, return_col: str, target_n: int, single_cap: float, cost_bps: float) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    monthly_rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []
    prev_weights: dict[str, float] = {}
    for dt, group in frame.groupby("rebalance_date", sort=True):
        rows = group.to_dict("records")
        selected = select_candidates(rows, target_n=target_n)
        weights = score_power_weights(selected, "concentrated_conviction_score", single_name_cap=single_cap)
        turn = turnover(prev_weights, weights)
        gross_return = 0.0
        for item in selected:
            ticker = str(item.get("ticker") or "").upper()
            weight = safe_float(weights.get(ticker), 0.0)
            if weight <= 0:
                continue
            ret = safe_float(item.get(return_col), 0.0)
            gross_return += weight * ret
            holding_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "weight": weight,
                    "period_forward_return": ret,
                    "weighted_forward_return": weight * ret,
                    "concentrated_conviction_score": item.get("concentrated_conviction_score"),
                    "sector": item.get("sector", ""),
                    "regime_state": item.get("regime_state", ""),
                    "rs_acceleration_score": item.get("rs_acceleration_score", ""),
                    "stage2_overext_penalty": item.get("stage2_overext_penalty", ""),
                    "explosion_exit_score": item.get("explosion_exit_score", ""),
                    "portfolio_monster_early_score": item.get("portfolio_monster_early_score", monster_early_score(item)),
                    "portfolio_risk_entry_block_score": item.get("portfolio_risk_entry_block_score", risk_entry_block_score(item)),
                    "portfolio_defensive_rotation_action": item.get("portfolio_defensive_rotation_action", ""),
                }
            )
        cost = turn * (cost_bps / 10000.0)
        monthly_rows.append(
            {
                "rebalance_date": dt,
                "target_n": target_n,
                "single_name_cap": single_cap,
                "gross_return": gross_return,
                "cost": cost,
                "turnover": turn,
                "net_return": gross_return - cost,
                "cash_weight": max(0.0, 1.0 - sum(weights.values())),
                "n_positions": len(weights),
                "selected_tickers": ",".join(weights.keys()),
            }
        )
        prev_weights = weights
    metrics = calc_metrics([safe_float(row.get("net_return")) for row in monthly_rows])
    metrics.update(
        {
            "target_n": target_n,
            "single_name_cap": single_cap,
            "avg_turnover_monthly": sum(safe_float(row.get("turnover")) for row in monthly_rows) / max(len(monthly_rows), 1),
            "avg_cash_weight": sum(safe_float(row.get("cash_weight")) for row in monthly_rows) / max(len(monthly_rows), 1),
        }
    )
    return metrics, monthly_rows, holding_rows


def replay(candidate_book: Path, output_dir: Path, target_ns: list[int], single_caps: list[float], cost_bps: float) -> dict[str, Any]:
    frame = normalize_rebalance_frame(read_table(candidate_book))
    if frame.empty:
        return blocked_payload("candidate replay book is empty", candidate_book, output_dir, "concentrated_policy_replay")
    return_col = infer_return_col(frame)
    if return_col is None:
        return blocked_payload("candidate replay book has no period return column", candidate_book, output_dir, "concentrated_policy_replay")

    comparison: list[dict[str, Any]] = []
    best: tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]] | None = None
    for target_n in target_ns:
        for single_cap in single_caps:
            metrics, monthly_rows, holding_rows = run_variant(frame, return_col, target_n, single_cap, cost_bps)
            row = {
                "target_n": target_n,
                "single_name_cap": single_cap,
                "cagr": metrics.get("cagr"),
                "sharpe": metrics.get("sharpe"),
                "max_dd": metrics.get("max_dd"),
                "calmar": metrics.get("calmar"),
                "avg_turnover_monthly": metrics.get("avg_turnover_monthly"),
                "avg_cash_weight": metrics.get("avg_cash_weight"),
            }
            comparison.append(row)
            if best is None or safe_float(metrics.get("cagr"), -99.0) > safe_float(best[0].get("cagr"), -99.0):
                best = (metrics, monthly_rows, holding_rows)

    assert best is not None
    best_metrics, best_monthly, best_holdings = best
    best_metrics.update(
        {
            "experiment_id": "concentrated_policy_replay",
            "status": "completed",
            "data_mode": "historical_candidate_replay_book",
            "candidate_book": str(candidate_book),
            "return_column": return_col,
            "research_only": True,
            "production_activation_allowed": False,
            "max_single_cap_tested": max(single_caps) if single_caps else None,
        }
    )
    curve = equity_curve_rows(best_monthly)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metrics.json", best_metrics)
    write_rows(output_dir / "comparison.csv", comparison)
    write_rows(output_dir / "monthly.csv", best_monthly)
    write_rows(output_dir / "holdings.csv", best_holdings)
    write_rows(output_dir / "equity_curve.csv", curve)
    write_rows(output_dir / "stress_windows.csv", worst_month_rows(curve))
    write_text(output_dir / "replay_report.md", render_report(best_metrics))
    return best_metrics


def render_report(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Concentrated Policy Replay",
            "",
            "Research-only concentrated replay from historical candidate rows.",
            "",
            f"- Status: `{metrics.get('status')}`",
            f"- Target N: {metrics.get('target_n')}",
            f"- Single cap: {safe_float(metrics.get('single_name_cap')):.2%}",
            f"- CAGR: {safe_float(metrics.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
            "",
            "This is the path that can test high-conviction caps up to 50% without hardcoding tickers.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--target-ns", default="3,5,7")
    parser.add_argument("--single-caps", default="0.25,0.35,0.50")
    parser.add_argument("--cost-bps", type=float, default=50.0)
    return parser.parse_args()


def parse_ints(value: str) -> list[int]:
    return [int(x.strip()) for x in value.split(",") if x.strip()]


def parse_floats(value: str) -> list[float]:
    return [float(x.strip()) for x in value.split(",") if x.strip()]


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    candidate_book = repo_path(args.candidate_book) if args.candidate_book else latest_run / "reports" / "candidate_replay_book.csv"
    output_dir = repo_path(args.output_dir)
    if not candidate_book.exists():
        blocked_payload("missing reports/candidate_replay_book.csv from full rebuild", candidate_book, output_dir, "concentrated_policy_replay")
        return 0
    replay(candidate_book, output_dir, parse_ints(args.target_ns), parse_floats(args.single_caps), args.cost_bps)
    print(f"[concentrated-policy-replay] wrote {output_dir / 'metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Research-only Main v3 alpha-concentration replay.

Main v2 proved useful for diagnosing sleeve structure, but the official
broker-ledger results still show main is too diluted and loses too much alpha
to cash, churn, and wide diversification. This runner creates a narrower
future/monster/early-leader challenger from the same PIT candidate replay book.

The output is a target book (`monthly_holdings.csv`) that can be passed directly
to `run_broker_ledger_replay.py` for production-compatible next-close account
evaluation. This script itself is research-only and does not change production
defaults.
"""
from __future__ import annotations

import argparse
import copy
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

from r1000_main_v2 import MAIN_V2_BALANCED_POLICY, compose_main_sleeve_portfolio  # noqa: E402
from tools.historical_replay_lib import (  # noqa: E402
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


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUT_DIR = "outputs/main_v3_alpha_concentration"

MAIN_V3_CAPACITY_BY_REGIME = {
    "deep_bear": {"core": 0.35, "future": 0.12, "early": 0.00, "cash": 0.53},
    "bear": {"core": 0.30, "future": 0.25, "early": 0.05, "cash": 0.40},
    "neutral": {"core": 0.12, "future": 0.62, "early": 0.23, "cash": 0.03},
    "bull": {"core": 0.08, "future": 0.66, "early": 0.23, "cash": 0.03},
    "strong_bull": {"core": 0.05, "future": 0.68, "early": 0.24, "cash": 0.03},
}

MAIN_V3_TARGET_N_BY_REGIME = {
    "deep_bear": {"core": 3, "future": 2, "early": 0},
    "bear": {"core": 3, "future": 3, "early": 1},
    "neutral": {"core": 2, "future": 6, "early": 2},
    "bull": {"core": 1, "future": 7, "early": 3},
    "strong_bull": {"core": 1, "future": 6, "early": 3},
}


def build_policy(single_name_cap: float, cash_floor: float) -> dict[str, Any]:
    policy = copy.deepcopy(MAIN_V2_BALANCED_POLICY)
    policy["name"] = "main_v3_alpha_concentration"
    policy["single_name_cap"] = float(single_name_cap)
    policy["sleeve_capacity_by_regime"] = copy.deepcopy(MAIN_V3_CAPACITY_BY_REGIME)
    policy["target_n_by_regime"] = copy.deepcopy(MAIN_V3_TARGET_N_BY_REGIME)
    policy["rebalance_months"] = {"core": 3, "future": 1, "early": 1}
    policy["main_v3_cash_floor"] = float(cash_floor)
    style = dict(policy.get("style_aware_selection") or {})
    style["replacement_bonus_scale"] = max(safe_float(style.get("replacement_bonus_scale")), 0.26)
    style["replacement_penalty_scale"] = max(safe_float(style.get("replacement_penalty_scale")), 0.22)
    style["replacement_strong_threshold"] = min(safe_float(style.get("replacement_strong_threshold"), 0.60), 0.55)
    style["capacity_delta_by_style"] = {
        **(style.get("capacity_delta_by_style") or {}),
        "breakout_growth": {"core": -0.04, "future": 0.06, "early": 0.02},
        "turnaround_accumulation": {"core": -0.03, "future": -0.02, "early": 0.08},
        "quality_compounder": {"core": 0.04, "future": -0.02, "early": -0.01},
        "cash_defense": {"core": 0.04, "future": -0.10, "early": -0.08},
    }
    style["target_delta_by_style"] = {
        **(style.get("target_delta_by_style") or {}),
        "breakout_growth": {"core": -1, "future": 1, "early": 1},
        "turnaround_accumulation": {"core": -1, "future": 0, "early": 2},
        "quality_compounder": {"core": 1, "future": 0, "early": -1},
        "cash_defense": {"core": 1, "future": -1, "early": -1},
    }
    policy["style_aware_selection"] = style
    return policy


def score_lookup_from_result(result: dict[str, Any]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for sleeve_items in (result.get("selected_by_sleeve") or {}).values():
        for item in sleeve_items:
            ticker = str(item.get("ticker") or "").upper()
            if ticker:
                scores[ticker] = max(scores.get(ticker, 0.0), safe_float(item.get("score")))
    return scores


def selected_meta_from_result(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for sleeve, sleeve_items in (result.get("selected_by_sleeve") or {}).items():
        for item in sleeve_items:
            ticker = str(item.get("ticker") or "").upper()
            if not ticker:
                continue
            existing = out.get(ticker, {})
            merged = {**existing, **item}
            sleeves = set(str(merged.get("main_v3_sleeves") or "").split(",")) if merged.get("main_v3_sleeves") else set()
            sleeves.add(str(sleeve))
            merged["main_v3_sleeves"] = ",".join(sorted(s for s in sleeves if s))
            out[ticker] = merged
    return out


def rebalance_to_cash_floor(weights: dict[str, float], scores: dict[str, float], cap: float, cash_floor: float) -> dict[str, float]:
    if not weights:
        return {}
    cap = max(0.01, min(1.0, float(cap)))
    target_invested = max(0.0, min(1.0, 1.0 - float(cash_floor)))
    out = {ticker: max(0.0, min(cap, float(weight))) for ticker, weight in weights.items() if float(weight) > 1e-12}
    total = sum(out.values())
    if total <= 1e-12:
        return out
    if total > target_invested:
        scale = target_invested / total
        return {ticker: weight * scale for ticker, weight in out.items()}
    remaining = target_invested - total
    while remaining > 1e-9:
        available = {ticker: cap - weight for ticker, weight in out.items() if cap - weight > 1e-9}
        if not available:
            break
        raw = {ticker: max(scores.get(ticker, 0.0), 0.05) for ticker in available}
        raw_total = sum(raw.values())
        if raw_total <= 0:
            raw = {ticker: 1.0 for ticker in available}
            raw_total = sum(raw.values())
        used = 0.0
        for ticker, room in available.items():
            add = min(room, remaining * raw[ticker] / raw_total)
            out[ticker] += add
            used += add
        if used <= 1e-12:
            break
        remaining -= used
    return {ticker: weight for ticker, weight in out.items() if weight > 1e-12}


def render_report(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Main v3 Alpha-Concentration Replay",
            "",
            "Research-only challenger. Production defaults are unchanged.",
            "",
            f"- Status: `{metrics.get('status')}`",
            f"- Months: {metrics.get('months')}",
            f"- CAGR: {safe_float(metrics.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
            f"- Avg cash: {safe_float(metrics.get('avg_cash_weight')):.2%}",
            f"- Avg positions: {safe_float(metrics.get('avg_position_count')):.2f}",
            f"- Avg monthly turnover: {safe_float(metrics.get('avg_turnover_monthly')):.2%}",
            "",
            "The companion broker-ledger replay is required for production-compatible evidence.",
            "",
        ]
    )


def replay(
    candidate_book: Path,
    output_dir: Path,
    *,
    cost_bps: float,
    single_name_cap: float,
    cash_floor: float,
) -> dict[str, Any]:
    frame = normalize_rebalance_frame(read_table(candidate_book))
    if frame.empty:
        return blocked_payload("candidate replay book is empty", candidate_book, output_dir, "main_v3_alpha_concentration")
    return_col = infer_return_col(frame)
    if return_col is None:
        return blocked_payload("candidate replay book has no period return column", candidate_book, output_dir, "main_v3_alpha_concentration")

    policy = build_policy(single_name_cap, cash_floor)
    monthly_rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []
    turnover_rows: list[dict[str, Any]] = []
    prev_weights: dict[str, float] = {}
    for dt, group in frame.groupby("rebalance_date", sort=True):
        rows = group.to_dict("records")
        lookup = {str(row.get("ticker") or "").upper(): row for row in rows}
        result = compose_main_sleeve_portfolio(rows, policy=policy)
        score_lookup = score_lookup_from_result(result)
        selected_meta = selected_meta_from_result(result)
        weights = {str(k): float(v) for k, v in (result.get("main_v2_weights") or {}).items()}
        regime = str(result.get("regime_state") or "neutral")
        floor = cash_floor if regime not in {"bear", "deep_bear"} else max(cash_floor, safe_float(result.get("cash_target"), 0.0))
        weights = rebalance_to_cash_floor(weights, score_lookup, single_name_cap, floor)
        month_turnover = turnover(prev_weights, weights)
        gross_return = 0.0
        selected_names: list[str] = []
        for ticker, weight in sorted(weights.items(), key=lambda item: item[1], reverse=True):
            source = lookup.get(ticker, {})
            meta = selected_meta.get(ticker, {})
            period_return = safe_float(source.get(return_col), 0.0)
            gross_return += weight * period_return
            selected_names.append(ticker)
            holding_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "Name": source.get("Name", ""),
                    "sector": source.get("sector", ""),
                    "weight": weight,
                    "period_forward_return": period_return,
                    "weighted_forward_return": weight * period_return,
                    "main_v3_score": score_lookup.get(ticker, ""),
                    "main_v3_sleeves": meta.get("main_v3_sleeves", ""),
                    "main_v3_style_regime": result.get("style_regime"),
                    "main_v3_replacement_score": meta.get("main_v2_replacement_score", ""),
                    "main_v3_replacement_catalyst_score": meta.get("main_v2_replacement_catalyst_score", ""),
                    "main_v3_replacement_decay_score": meta.get("main_v2_replacement_decay_score", ""),
                    "score": source.get("score", ""),
                    "score_total": source.get("score_total", ""),
                    "portfolio_sleeve_label": source.get("portfolio_sleeve_label", ""),
                    "portfolio_candidate_gate_label": source.get("portfolio_candidate_gate_label", ""),
                    "portfolio_future_winner_engine_score": source.get("portfolio_future_winner_engine_score", ""),
                    "portfolio_early_scout_engine_score": source.get("portfolio_early_scout_engine_score", ""),
                    "portfolio_monster_early_score": source.get("portfolio_monster_early_score", ""),
                    "portfolio_stale_mega_leader_score": source.get("portfolio_stale_mega_leader_score", ""),
                    "portfolio_risk_entry_block_score": source.get("portfolio_risk_entry_block_score", ""),
                    "rs_acceleration_score": source.get("rs_acceleration_score", ""),
                    "regime_state": result.get("regime_state"),
                    "style_regime": result.get("style_regime"),
                    "theme_horizon_primary": source.get("theme_horizon_primary", ""),
                    "theme_holding_profile_primary": source.get("theme_holding_profile_primary", ""),
                    "research_only_backtest": True,
                    "production_activation_allowed": False,
                }
            )
        cost = month_turnover * (cost_bps / 10000.0)
        net_return = gross_return - cost
        cash_weight = max(0.0, 1.0 - sum(weights.values()))
        monthly_rows.append(
            {
                "rebalance_date": dt,
                "regime_state": result.get("regime_state"),
                "style_regime": result.get("style_regime"),
                "gross_return": gross_return,
                "cost": cost,
                "turnover": month_turnover,
                "net_return": net_return,
                "cash_weight": cash_weight,
                "n_positions": len(weights),
                "single_name_cap": single_name_cap,
                "selected_tickers": ",".join(selected_names),
            }
        )
        turnover_rows.append({"rebalance_date": dt, "turnover": month_turnover, "cost": cost})
        prev_weights = weights

    curve = equity_curve_rows(monthly_rows)
    metrics = calc_metrics([safe_float(row.get("net_return")) for row in monthly_rows])
    metrics.update(
        {
            "experiment_id": "main_v3_alpha_concentration",
            "candidate_id": "main_v3_alpha_concentration",
            "status": "completed",
            "data_mode": "historical_candidate_replay_book",
            "candidate_book": str(candidate_book),
            "return_column": return_col,
            "single_name_cap": float(single_name_cap),
            "cash_floor": float(cash_floor),
            "avg_cash_weight": sum(safe_float(row.get("cash_weight")) for row in monthly_rows) / max(len(monthly_rows), 1),
            "avg_position_count": sum(safe_float(row.get("n_positions")) for row in monthly_rows) / max(len(monthly_rows), 1),
            "avg_turnover_monthly": sum(safe_float(row.get("turnover")) for row in monthly_rows) / max(len(monthly_rows), 1),
            "research_only": True,
            "production_activation_allowed": False,
            "broker_ledger_required_for_official_verdict": True,
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metrics.json", metrics)
    write_rows(output_dir / "monthly_returns.csv", monthly_rows)
    write_rows(output_dir / "monthly_holdings.csv", holding_rows)
    write_rows(output_dir / "equity_curve.csv", curve)
    write_rows(output_dir / "turnover.csv", turnover_rows)
    write_rows(output_dir / "stress_windows.csv", worst_month_rows(curve))
    write_text(output_dir / "replay_report.md", render_report(metrics))
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--cost-bps", type=float, default=50.0)
    parser.add_argument("--single-name-cap", type=float, default=0.33)
    parser.add_argument("--cash-floor", type=float, default=0.00)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    candidate_book = repo_path(args.candidate_book) if args.candidate_book else latest_run / "reports" / "candidate_replay_book.csv"
    output_dir = repo_path(args.output_dir)
    payload = replay(
        candidate_book,
        output_dir,
        cost_bps=args.cost_bps,
        single_name_cap=args.single_name_cap,
        cash_floor=args.cash_floor,
    )
    print({"status": payload.get("status"), "cagr": payload.get("cagr"), "max_dd": payload.get("max_dd")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

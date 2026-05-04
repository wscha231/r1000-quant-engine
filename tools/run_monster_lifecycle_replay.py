#!/usr/bin/env python3
"""Historical monster-winner lifecycle replay.

Research-only state machine for the user priority:
  early scout -> confirm -> pyramid winner -> defend/exit on true breakdown.

The runner is ticker-agnostic. It uses the full rebuild
`reports/candidate_replay_book.csv` and never hardcodes examples such as GEV,
PLTR, SNDK, LITE, GOOGL, or WMT.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from historical_replay_lib import (  # noqa: E402
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


DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUT_DIR = "outputs/monster_lifecycle_replay"

POLICIES = {
    "main": {
        "max_single_name_weight": 0.33,
        "max_total_positions": 14,
        "max_new_scouts_per_month": 4,
        "scout_weight": 0.025,
        "confirm_weight": 0.070,
        "winner_weight": 0.160,
        "monster_weight": 0.330,
        "min_entry_score": 0.58,
        "capacity": 1.0,
    },
    "concentrated": {
        "max_single_name_weight": 0.50,
        "max_total_positions": 8,
        "max_new_scouts_per_month": 3,
        "scout_weight": 0.050,
        "confirm_weight": 0.120,
        "winner_weight": 0.280,
        "monster_weight": 0.500,
        "min_entry_score": 0.62,
        "capacity": 1.0,
    },
}


def clip01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def max_col(row: dict[str, Any], keys: tuple[str, ...], default: float = 0.0) -> float:
    return max(safe_float(row.get(key), default) for key in keys)


def liquidity_pass(row: dict[str, Any]) -> bool:
    mcap = max_col(row, ("market_cap_live", "mktcap"))
    dollar_vol = safe_float(row.get("dollar_vol_20d"), 0.0)
    price = max_col(row, ("current_price_live", "px"))
    return mcap >= 5_000_000_000 and dollar_vol >= 20_000_000 and price >= 10


def trend_ok(row: dict[str, Any]) -> bool:
    return safe_float(row.get("price_above_ma50")) > 0 and safe_float(row.get("price_above_ma200")) > 0


def monster_onset_score(row: dict[str, Any]) -> float:
    """Blend technical, fundamental, theme, and leadership signals."""
    technical = (
        0.22 * safe_float(row.get("rs_acceleration_score"))
        + 0.16 * safe_float(row.get("breakout_setup_quality_score"))
        + 0.12 * safe_float(row.get("post_breakout_hold_score"))
        + 0.08 * (1.0 if safe_float(row.get("price_above_ma50")) > 0 else 0.0)
        + 0.08 * (1.0 if safe_float(row.get("price_above_ma200")) > 0 else 0.0)
        + 0.06 * safe_float(row.get("volatility_contraction_score"))
    )
    fundamental = (
        0.16 * safe_float(row.get("revenue_growth_final"))
        + 0.12 * safe_float(row.get("rev_growth_accel_4q"))
        + 0.10 * max_col(row, ("eps_revision_score", "revision_score", "eps_revision_proxy"))
        + 0.08 * safe_float(row.get("profitability_inflection_score"))
        + 0.05 * safe_float(row.get("cashflow_inflection_under_loss_score"))
        + 0.06 * safe_float(row.get("fundamental_reliability_score"), 0.5)
    )
    turn_positive = any(
        truthy(row.get(key)) or safe_float(row.get(key)) > 0
        for key in ("profit_turn_positive_4q", "cashflow_turn_positive_4q", "ni_loss_narrowing_4q", "any_profit_sign_flip_pos")
    )
    leadership = (
        0.10 * max(safe_float(row.get("theme_phase_multiplier_primary"), 1.0) - 1.0, 0.0)
        + 0.10 * max(safe_float(row.get("theme_phase_multiplier_max"), 1.0) - 1.0, 0.0)
        + 0.10 * safe_float(row.get("industry_group_strength_score"))
        + 0.10 * safe_float(row.get("h6_dynamic_leader_score"))
        + 0.08 * safe_float(row.get("oneil_leadership_score"))
        + 0.06 * safe_float(row.get("multi_year_winner_score"))
    )
    risk = (
        0.22 * safe_float(row.get("risk_penalty"))
        + 0.24 * safe_float(row.get("stage2_overext_penalty"))
        + 0.24 * safe_float(row.get("explosion_exit_score"))
        + 0.18 * safe_float(row.get("live_event_risk_score"))
        + 0.08 * safe_float(row.get("overheat_penalty"))
    )
    score = technical + fundamental + leadership - risk
    if turn_positive:
        score += 0.08
    if not trend_ok(row):
        score -= 0.30
    if not liquidity_pass(row):
        score -= 0.40
    return float(score)


def classify_exit(row: dict[str, Any], last_return: float, cum_return: float, peak_return: float) -> tuple[str, str]:
    """Distinguish shakeout from distribution using available monthly signals."""
    score = monster_onset_score(row)
    drawdown_from_peak = (1.0 + cum_return) / max(1.0 + peak_return, 1e-8) - 1.0
    distribution_risk = max(
        safe_float(row.get("explosion_exit_score")),
        safe_float(row.get("stage2_overext_penalty")),
        safe_float(row.get("risk_penalty")),
        safe_float(row.get("live_event_risk_score")),
    )
    rs = safe_float(row.get("rs_acceleration_score"))
    if last_return <= -0.18 and distribution_risk >= 0.70 and rs < 0:
        return "exit", "distribution_breakdown"
    if drawdown_from_peak <= -0.22 and score < 0.45:
        return "exit", "failed_recovery_after_peak"
    if last_return <= -0.12 and score >= 0.62 and trend_ok(row):
        return "hold", "shakeout_hold"
    if distribution_risk >= 0.90:
        return "trim", "distribution_trim"
    return "hold", "hold"


def next_stage(stage: str, score: float, cum_return: float, months_held: int) -> str:
    if stage == "scout" and (score >= 0.72 or cum_return >= 0.12 or months_held >= 2 and score >= 0.65):
        return "confirm"
    if stage == "confirm" and (score >= 0.82 or cum_return >= 0.35):
        return "winner"
    if stage == "winner" and (score >= 0.92 or cum_return >= 1.00):
        return "monster"
    return stage


def stage_weight(stage: str, policy: dict[str, Any]) -> float:
    return {
        "scout": safe_float(policy.get("scout_weight")),
        "confirm": safe_float(policy.get("confirm_weight")),
        "winner": safe_float(policy.get("winner_weight")),
        "monster": safe_float(policy.get("monster_weight")),
    }.get(stage, safe_float(policy.get("scout_weight")))


def normalize_weights(raw: dict[str, float], capacity: float, max_single: float) -> dict[str, float]:
    capped = {ticker: min(weight, max_single) for ticker, weight in raw.items() if weight > 0}
    total = sum(capped.values())
    if total <= capacity:
        return capped
    scale = capacity / total
    return {ticker: weight * scale for ticker, weight in capped.items()}


def replay(candidate_book: Path, output_dir: Path, policy_name: str, cost_bps: float) -> dict[str, Any]:
    policy = POLICIES[policy_name]
    frame = normalize_rebalance_frame(read_table(candidate_book))
    if frame.empty:
        return blocked_payload("candidate replay book is empty", candidate_book, output_dir, "monster_lifecycle_replay")
    return_col = infer_return_col(frame)
    if return_col is None:
        return blocked_payload("candidate replay book has no period return column", candidate_book, output_dir, "monster_lifecycle_replay")

    state: dict[str, dict[str, Any]] = {}
    prev_weights: dict[str, float] = {}
    monthly_rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    for dt, group in frame.groupby("rebalance_date", sort=True):
        rows = group.to_dict("records")
        by_ticker = {str(row.get("ticker") or "").upper(): row for row in rows}

        raw_weights: dict[str, float] = {}
        active_state: dict[str, dict[str, Any]] = {}
        for ticker, pos in list(state.items()):
            row = by_ticker.get(ticker)
            if not row:
                event_rows.append(
                    {
                        "rebalance_date": dt,
                        "ticker": ticker,
                        "action": "exit",
                        "reason": "missing_from_candidate_book",
                        "stage": pos.get("stage"),
                    }
                )
                continue
            cum_before = safe_float(pos.get("cum_return"))
            peak_before = safe_float(pos.get("peak_return"))
            action, reason = classify_exit(row, safe_float(pos.get("last_return"), 0.0), cum_before, peak_before)
            if action == "exit":
                event_rows.append({"rebalance_date": dt, "ticker": ticker, "action": action, "reason": reason, "stage": pos.get("stage")})
                continue
            score = monster_onset_score(row)
            stage = next_stage(str(pos.get("stage", "scout")), score, cum_before, int(pos.get("months_held", 0)))
            weight = stage_weight(stage, policy)
            if action == "trim":
                weight *= 0.5
            raw_weights[ticker] = weight
            active_state[ticker] = {
                "stage": stage,
                "cum_return": cum_before,
                "peak_return": peak_before,
                "months_held": int(pos.get("months_held", 0)),
                "last_score": score,
                "last_return": safe_float(pos.get("last_return"), 0.0),
            }
            event_rows.append({"rebalance_date": dt, "ticker": ticker, "action": action, "reason": reason, "stage": stage})

        # Add new scouts from broad candidate book.
        slots = max(0, int(policy["max_total_positions"]) - len(active_state))
        new_limit = min(slots, int(policy["max_new_scouts_per_month"]))
        if new_limit > 0:
            candidates: list[dict[str, Any]] = []
            for row in rows:
                ticker = str(row.get("ticker") or "").upper()
                if ticker in active_state:
                    continue
                score = monster_onset_score(row)
                if score >= safe_float(policy.get("min_entry_score")) and liquidity_pass(row) and trend_ok(row):
                    item = dict(row)
                    item["monster_onset_score"] = score
                    candidates.append(item)
            candidates.sort(key=lambda row: safe_float(row.get("monster_onset_score")), reverse=True)
            for row in candidates[:new_limit]:
                ticker = str(row.get("ticker") or "").upper()
                raw_weights[ticker] = safe_float(policy.get("scout_weight"))
                active_state[ticker] = {
                    "stage": "scout",
                    "cum_return": 0.0,
                    "peak_return": 0.0,
                    "months_held": 0,
                    "last_score": safe_float(row.get("monster_onset_score")),
                    "last_return": 0.0,
                }
                event_rows.append({"rebalance_date": dt, "ticker": ticker, "action": "enter", "reason": "monster_scout", "stage": "scout"})

        weights = normalize_weights(raw_weights, safe_float(policy.get("capacity"), 1.0), safe_float(policy.get("max_single_name_weight"), 0.33))
        month_turnover = turnover(prev_weights, weights)
        gross_return = 0.0
        next_state: dict[str, dict[str, Any]] = {}
        for ticker, weight in weights.items():
            row = by_ticker.get(ticker, {})
            pos = active_state.get(ticker, {})
            ret = safe_float(row.get(return_col), 0.0)
            cum_before = safe_float(pos.get("cum_return"))
            cum_after = (1.0 + cum_before) * (1.0 + ret) - 1.0
            peak_after = max(safe_float(pos.get("peak_return")), cum_after)
            next_state[ticker] = {
                "stage": pos.get("stage", "scout"),
                "cum_return": cum_after,
                "peak_return": peak_after,
                "months_held": int(pos.get("months_held", 0)) + 1,
                "last_score": safe_float(pos.get("last_score")),
                "last_return": ret,
            }
            gross_return += weight * ret
        cost = month_turnover * (cost_bps / 10000.0)
        net_return = gross_return - cost
        monthly_rows.append(
            {
                "rebalance_date": dt,
                "policy": policy_name,
                "gross_return": gross_return,
                "cost": cost,
                "turnover": month_turnover,
                "net_return": net_return,
                "cash_weight": max(0.0, 1.0 - sum(weights.values())),
                "n_positions": len(weights),
                "selected_tickers": ",".join(weights.keys()),
                "monster_count": sum(1 for ticker in weights if active_state.get(ticker, {}).get("stage") == "monster"),
                "winner_count": sum(1 for ticker in weights if active_state.get(ticker, {}).get("stage") == "winner"),
                "scout_count": sum(1 for ticker in weights if active_state.get(ticker, {}).get("stage") == "scout"),
            }
        )
        for ticker, weight in weights.items():
            row = by_ticker.get(ticker, {})
            pos = next_state.get(ticker, {})
            ret = safe_float(row.get(return_col), 0.0)
            holding_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "weight": weight,
                    "stage": pos.get("stage"),
                    "monster_onset_score": pos.get("last_score"),
                    "cum_return": pos.get("cum_return"),
                    "peak_return": pos.get("peak_return"),
                    "months_held": pos.get("months_held"),
                    "period_forward_return": ret,
                    "weighted_forward_return": weight * ret,
                    "sector": row.get("sector", ""),
                    "industry_group": row.get("industry_group", ""),
                    "rs_acceleration_score": row.get("rs_acceleration_score", ""),
                    "revenue_growth_final": row.get("revenue_growth_final", ""),
                    "revision_score": max_col(row, ("eps_revision_score", "revision_score", "eps_revision_proxy")),
                    "explosion_exit_score": row.get("explosion_exit_score", ""),
                    "stage2_overext_penalty": row.get("stage2_overext_penalty", ""),
                }
            )
        state = next_state
        prev_weights = weights

    curve = equity_curve_rows(monthly_rows)
    metrics = calc_metrics([safe_float(row.get("net_return")) for row in monthly_rows])
    metrics.update(
        {
            "experiment_id": "monster_lifecycle_replay",
            "status": "completed",
            "policy": policy_name,
            "data_mode": "historical_candidate_replay_book",
            "candidate_book": str(candidate_book),
            "return_column": return_col,
            "avg_cash_weight": sum(safe_float(row.get("cash_weight")) for row in monthly_rows) / max(len(monthly_rows), 1),
            "avg_turnover_monthly": sum(safe_float(row.get("turnover")) for row in monthly_rows) / max(len(monthly_rows), 1),
            "max_single_name_weight": policy["max_single_name_weight"],
            "research_only": True,
            "production_activation_allowed": False,
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metrics.json", metrics)
    write_rows(output_dir / "monthly.csv", monthly_rows)
    write_rows(output_dir / "holdings.csv", holding_rows)
    write_rows(output_dir / "events.csv", event_rows)
    write_rows(output_dir / "equity_curve.csv", curve)
    write_rows(output_dir / "stress_windows.csv", worst_month_rows(curve))
    write_text(output_dir / "replay_report.md", render_report(metrics))
    return metrics


def render_report(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Monster Lifecycle Replay",
            "",
            "Research-only staged sizing replay: scout -> confirm -> winner -> monster.",
            "",
            f"- Policy: `{metrics.get('policy')}`",
            f"- Status: `{metrics.get('status')}`",
            f"- Max single-name weight: {safe_float(metrics.get('max_single_name_weight')):.2%}",
            f"- CAGR: {safe_float(metrics.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
            f"- Avg cash: {safe_float(metrics.get('avg_cash_weight')):.2%}",
            f"- Avg turnover: {safe_float(metrics.get('avg_turnover_monthly')):.2%}",
            "",
            "This is the priority challenger for detecting early monster winners without hardcoded tickers.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--policy", choices=sorted(POLICIES), default="concentrated")
    parser.add_argument("--cost-bps", type=float, default=50.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    candidate_book = repo_path(args.candidate_book) if args.candidate_book else latest_run / "reports" / "candidate_replay_book.csv"
    output_dir = repo_path(args.output_dir)
    if not candidate_book.exists():
        blocked_payload("missing reports/candidate_replay_book.csv from full rebuild", candidate_book, output_dir, "monster_lifecycle_replay")
        return 0
    replay(candidate_book, output_dir, policy_name=args.policy, cost_bps=args.cost_bps)
    print(f"[monster-lifecycle] wrote {output_dir / 'metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

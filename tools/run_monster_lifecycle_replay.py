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
    "lifecycle_review_main": {
        "max_single_name_weight": 0.33,
        "max_total_positions": 12,
        "max_new_scouts_per_month": 3,
        "scout_weight": 0.030,
        "confirm_weight": 0.080,
        "winner_weight": 0.180,
        "monster_weight": 0.330,
        "min_entry_score": 0.60,
        "capacity": 1.0,
        "entry_requires_leadership": True,
        "min_entry_leadership": 0.34,
        "min_entry_growth": 0.10,
        "max_entry_distribution_risk": 0.78,
        "min_mcap": 10_000_000_000,
        "scout_timeout_months": 4,
        "scout_timeout_min_return": 0.04,
        "scout_timeout_min_score": 0.62,
        "stale_patience_months": 2,
        "stale_score_threshold": 0.36,
        "hard_peak_drawdown": -0.34,
        "shakeout_hold_score": 0.54,
        "distribution_exit_risk": 0.78,
        "distribution_trim_risk": 0.68,
        "trim_scale": 0.50,
        "confirm_score": 0.72,
        "confirm_return": 0.10,
        "confirm_after_months": 3,
        "confirm_after_months_score": 0.64,
        "winner_score": 0.82,
        "winner_return": 0.32,
        "monster_score": 0.94,
        "monster_return": 1.00,
        "hard_stop_proxy": -0.10,
        "hard_stop_exit": True,
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
    "lifecycle_review_concentrated": {
        "max_single_name_weight": 0.50,
        "max_total_positions": 7,
        "max_new_scouts_per_month": 3,
        "scout_weight": 0.050,
        "confirm_weight": 0.140,
        "winner_weight": 0.320,
        "monster_weight": 0.500,
        "min_entry_score": 0.64,
        "capacity": 1.0,
        "entry_requires_leadership": True,
        "min_entry_leadership": 0.38,
        "min_entry_growth": 0.12,
        "max_entry_distribution_risk": 0.74,
        "min_mcap": 10_000_000_000,
        "scout_timeout_months": 4,
        "scout_timeout_min_return": 0.06,
        "scout_timeout_min_score": 0.66,
        "stale_patience_months": 2,
        "stale_score_threshold": 0.38,
        "hard_peak_drawdown": -0.32,
        "shakeout_hold_score": 0.56,
        "distribution_exit_risk": 0.76,
        "distribution_trim_risk": 0.66,
        "trim_scale": 0.45,
        "confirm_score": 0.75,
        "confirm_return": 0.12,
        "confirm_after_months": 2,
        "confirm_after_months_score": 0.68,
        "winner_score": 0.84,
        "winner_return": 0.35,
        "monster_score": 0.94,
        "monster_return": 0.95,
        "hard_stop_proxy": -0.08,
        "hard_stop_exit": True,
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


def distribution_risk_score(row: dict[str, Any]) -> float:
    return max(
        max(safe_float(row.get("explosion_exit_score")), 0.0),
        max(safe_float(row.get("stage2_overext_penalty")), 0.0),
        max(safe_float(row.get("risk_penalty")), 0.0),
        max(safe_float(row.get("live_event_risk_score")), 0.0),
        max(safe_float(row.get("overheat_penalty")), 0.0),
    )


def technical_leadership_signal(row: dict[str, Any]) -> float:
    rs = safe_float(row.get("rs_acceleration_score"), 0.0)
    return max(
        safe_float(row.get("portfolio_monster_early_score"), 0.0),
        safe_float(row.get("breakout_setup_quality_score"), 0.0),
        safe_float(row.get("post_breakout_hold_score"), 0.0),
        safe_float(row.get("h6_dynamic_leader_score"), 0.0),
        safe_float(row.get("oneil_leadership_score"), 0.0),
        min(max(rs / 2.0, 0.0), 1.0),
    )


def leadership_signal(row: dict[str, Any]) -> float:
    return max(
        technical_leadership_signal(row),
        safe_float(row.get("industry_group_strength_score"), 0.0),
    )


def growth_signal(row: dict[str, Any]) -> float:
    return max(
        safe_float(row.get("revenue_growth_final"), 0.0),
        safe_float(row.get("rev_growth_accel_4q"), 0.0),
        safe_float(row.get("profitability_inflection_score"), 0.0),
        safe_float(row.get("cashflow_inflection_under_loss_score"), 0.0),
        max_col(row, ("eps_revision_score", "revision_score", "eps_revision_proxy")),
    )


def theme_event_risk(row: dict[str, Any]) -> float:
    return min(
        1.0,
        max(
            safe_float(row.get("theme_event_risk_sensitivity_max"), 0.35),
            safe_float(row.get("theme_event_risk_sensitivity_primary"), 0.35),
        ),
    )


def theme_structural_growth(row: dict[str, Any]) -> float:
    return min(
        1.0,
        max(
            safe_float(row.get("theme_structural_growth_max"), 0.35),
            safe_float(row.get("theme_structural_growth_primary"), 0.35),
        ),
    )


def theme_short_cycle(row: dict[str, Any]) -> bool:
    return (
        safe_float(row.get("theme_short_cycle_flag_max"), 0.0) >= 0.5
        or safe_float(row.get("theme_short_cycle_flag_primary"), 0.0) >= 0.5
    )


def theme_adjusted_policy(row: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Adjust lifecycle thresholds by theme half-life.

    Event/commodity beneficiaries get a shorter leash. Structural growth and
    compounder themes get more patience when leadership/fundamentals remain
    intact. This is research-only and affects replay sidecars, not production
    scoring or DEFAULT_FEATURES.
    """
    event_risk = theme_event_risk(row)
    structural = theme_structural_growth(row)
    out = dict(policy)
    if event_risk >= 0.60 or theme_short_cycle(row):
        out["stale_patience_months"] = max(1, int(safe_float(out.get("stale_patience_months"), 2) - 1))
        out["scout_timeout_months"] = max(2, int(safe_float(out.get("scout_timeout_months"), 4) - 1))
        out["distribution_exit_risk"] = max(0.55, safe_float(out.get("distribution_exit_risk"), 0.78) - 0.08 * event_risk)
        out["distribution_trim_risk"] = max(0.48, safe_float(out.get("distribution_trim_risk"), 0.68) - 0.08 * event_risk)
        out["shakeout_hold_score"] = min(0.85, safe_float(out.get("shakeout_hold_score"), 0.58) + 0.08 * event_risk)
        out["hard_peak_drawdown"] = min(-0.18, safe_float(out.get("hard_peak_drawdown"), -0.34) + 0.10 * event_risk)
        out["trim_scale"] = max(0.25, safe_float(out.get("trim_scale"), 0.50) - 0.12 * event_risk)
    if structural >= 0.70 and event_risk < 0.65:
        out["stale_patience_months"] = int(safe_float(out.get("stale_patience_months"), 2)) + 1
        out["scout_timeout_months"] = int(safe_float(out.get("scout_timeout_months"), 4)) + 1
        out["distribution_exit_risk"] = min(0.90, safe_float(out.get("distribution_exit_risk"), 0.78) + 0.04 * structural)
        out["distribution_trim_risk"] = min(0.82, safe_float(out.get("distribution_trim_risk"), 0.68) + 0.03 * structural)
        out["shakeout_hold_score"] = max(0.45, safe_float(out.get("shakeout_hold_score"), 0.58) - 0.05 * structural)
        out["hard_peak_drawdown"] = max(-0.42, safe_float(out.get("hard_peak_drawdown"), -0.34) - 0.04 * structural)
    return out


def entry_qualified(row: dict[str, Any], score: float, policy: dict[str, Any]) -> bool:
    if score < safe_float(policy.get("min_entry_score")):
        return False
    if not liquidity_pass(row) or not trend_ok(row):
        return False
    if max_col(row, ("market_cap_live", "mktcap")) < safe_float(policy.get("min_mcap"), 5_000_000_000):
        return False
    if distribution_risk_score(row) >= safe_float(policy.get("max_entry_distribution_risk"), 0.85):
        return False
    if theme_event_risk(row) >= 0.75 and str(row.get("theme_phase_primary", "")).lower() in {"peaking", "ending", "dead"}:
        return False
    if not bool(policy.get("entry_requires_leadership", False)):
        return True
    technical_leadership = technical_leadership_signal(row)
    broad_leadership = leadership_signal(row)
    growth = growth_signal(row)
    monster_override = safe_float(row.get("portfolio_monster_early_score"), 0.0) >= safe_float(policy.get("min_entry_leadership"), 0.0) + 0.08
    return (
        technical_leadership >= safe_float(policy.get("min_entry_leadership"), 0.0)
        or (broad_leadership >= safe_float(policy.get("min_entry_leadership"), 0.0) and growth >= safe_float(policy.get("min_entry_growth"), 0.0))
        or monster_override
    )


def monster_onset_score(row: dict[str, Any]) -> float:
    """Blend technical, fundamental, theme, and leadership signals."""
    portfolio_monster = safe_float(row.get("portfolio_monster_early_score"), 0.0)
    portfolio_block = safe_float(row.get("portfolio_risk_entry_block_score"), 0.0)
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
        0.22 * max(safe_float(row.get("risk_penalty")), 0.0)
        + 0.24 * max(safe_float(row.get("stage2_overext_penalty")), 0.0)
        + 0.24 * max(safe_float(row.get("explosion_exit_score")), 0.0)
        + 0.18 * max(safe_float(row.get("live_event_risk_score")), 0.0)
        + 0.08 * max(safe_float(row.get("overheat_penalty")), 0.0)
    )
    score = technical + fundamental + leadership + 0.35 * portfolio_monster - risk - 0.15 * portfolio_block
    if turn_positive:
        score += 0.08
    if not trend_ok(row):
        score -= 0.30
    if not liquidity_pass(row):
        score -= 0.40
    return float(score)


def classify_exit(
    row: dict[str, Any],
    last_return: float,
    cum_return: float,
    peak_return: float,
    pos: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[str, str, int]:
    """Distinguish shakeout from distribution using available monthly signals."""
    policy = theme_adjusted_policy(row, policy)
    score = monster_onset_score(row)
    drawdown_from_peak = (1.0 + cum_return) / max(1.0 + peak_return, 1e-8) - 1.0
    distribution_risk = distribution_risk_score(row)
    rs = safe_float(row.get("rs_acceleration_score"))
    stage = str(pos.get("stage", "scout"))
    months_held = int(pos.get("months_held", 0))
    bad_months = int(pos.get("bad_months", 0))
    event_risk = theme_event_risk(row)
    max_hold_months = safe_float(row.get("theme_max_hold_months_primary"), 0.0)
    target_hold_months = safe_float(row.get("theme_target_hold_months_primary"), 0.0)
    weak_trend = not trend_ok(row)
    stale_signal = (
        score < safe_float(policy.get("stale_score_threshold"), 0.42)
        or (weak_trend and rs < 0.0)
        or (drawdown_from_peak <= -0.18 and score < safe_float(policy.get("shakeout_hold_score"), 0.58))
    )
    next_bad_months = bad_months + 1 if stale_signal else 0

    if last_return <= -0.18 and distribution_risk >= safe_float(policy.get("distribution_exit_risk"), 0.78) and rs < 0 and weak_trend:
        return "exit", "distribution_breakdown", next_bad_months
    if (
        event_risk >= 0.65
        and max_hold_months > 0
        and months_held >= int(max_hold_months)
        and stage not in {"monster"}
        and score < safe_float(policy.get("winner_score"), 0.82)
    ):
        return "exit", "event_theme_time_stop", next_bad_months
    if (
        event_risk >= 0.65
        and target_hold_months > 0
        and months_held >= int(target_hold_months)
        and (distribution_risk >= safe_float(policy.get("distribution_trim_risk"), 0.68) or rs < -0.25)
    ):
        return "trim", "event_theme_half_life_trim", next_bad_months
    if drawdown_from_peak <= safe_float(policy.get("hard_peak_drawdown"), -0.34) and score < safe_float(policy.get("shakeout_hold_score"), 0.58):
        return "exit", "failed_recovery_after_peak", next_bad_months
    if last_return <= -0.12 and score >= safe_float(policy.get("shakeout_hold_score"), 0.58) and trend_ok(row):
        return "hold", "shakeout_hold", 0
    if (
        stage == "scout"
        and months_held >= int(safe_float(policy.get("scout_timeout_months"), 5))
        and cum_return < safe_float(policy.get("scout_timeout_min_return"), 0.04)
        and score < safe_float(policy.get("scout_timeout_min_score"), 0.62)
    ):
        return "exit", "failed_scout_timeout", next_bad_months
    if next_bad_months >= int(safe_float(policy.get("stale_patience_months"), 2)):
        return "exit", "stale_leader_review_exit", next_bad_months
    if distribution_risk >= safe_float(policy.get("distribution_trim_risk"), 0.68):
        return "trim", "distribution_trim", next_bad_months
    return "hold", "hold" if next_bad_months == 0 else "watch_stale", next_bad_months


def next_stage(stage: str, score: float, cum_return: float, months_held: int, policy: dict[str, Any]) -> str:
    if stage == "scout" and (
        score >= safe_float(policy.get("confirm_score"), 0.72)
        or cum_return >= safe_float(policy.get("confirm_return"), 0.12)
        or months_held >= int(safe_float(policy.get("confirm_after_months"), 2))
        and score >= safe_float(policy.get("confirm_after_months_score"), 0.65)
    ):
        return "confirm"
    if stage == "confirm" and (score >= safe_float(policy.get("winner_score"), 0.82) or cum_return >= safe_float(policy.get("winner_return"), 0.35)):
        return "winner"
    if stage == "winner" and (score >= safe_float(policy.get("monster_score"), 0.92) or cum_return >= safe_float(policy.get("monster_return"), 1.00)):
        return "monster"
    return stage


def stage_weight(stage: str, policy: dict[str, Any]) -> float:
    return {
        "scout": safe_float(policy.get("scout_weight")),
        "confirm": safe_float(policy.get("confirm_weight")),
        "winner": safe_float(policy.get("winner_weight")),
        "monster": safe_float(policy.get("monster_weight")),
    }.get(stage, safe_float(policy.get("scout_weight")))


def risk_adjusted_period_return(ret: float, policy: dict[str, Any]) -> tuple[float, bool, str]:
    hard_stop = policy.get("hard_stop_proxy")
    if hard_stop is None or hard_stop == "":
        return ret, False, "none"
    stop = safe_float(hard_stop, 0.0)
    if ret < stop:
        return stop, True, "monthly_hard_stop_proxy"
    return ret, False, "hold"


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
            action, reason, next_bad_months = classify_exit(
                row,
                safe_float(pos.get("last_return"), 0.0),
                cum_before,
                peak_before,
                pos,
                policy,
            )
            if action == "exit":
                event_rows.append({"rebalance_date": dt, "ticker": ticker, "action": action, "reason": reason, "stage": pos.get("stage")})
                continue
            row_policy = theme_adjusted_policy(row, policy)
            score = monster_onset_score(row)
            stage = next_stage(str(pos.get("stage", "scout")), score, cum_before, int(pos.get("months_held", 0)), row_policy)
            weight = stage_weight(stage, row_policy)
            if action == "trim":
                weight *= safe_float(row_policy.get("trim_scale"), 0.5)
            raw_weights[ticker] = weight
            active_state[ticker] = {
                "stage": stage,
                "cum_return": cum_before,
                "peak_return": peak_before,
                "months_held": int(pos.get("months_held", 0)),
                "last_score": score,
                "last_return": safe_float(pos.get("last_return"), 0.0),
                "bad_months": next_bad_months,
            }
            event_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "action": action,
                    "reason": reason,
                    "stage": stage,
                    "score": score,
                    "bad_months": next_bad_months,
                    "distribution_risk": distribution_risk_score(row),
                    "theme_event_risk": theme_event_risk(row),
                    "theme_structural_growth": theme_structural_growth(row),
                }
            )

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
                row_policy = theme_adjusted_policy(row, policy)
                if entry_qualified(row, score, row_policy):
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
                    "bad_months": 0,
                }
                event_rows.append(
                    {
                        "rebalance_date": dt,
                        "ticker": ticker,
                        "action": "enter",
                        "reason": "monster_scout",
                        "stage": "scout",
                        "score": safe_float(row.get("monster_onset_score")),
                        "bad_months": 0,
                        "distribution_risk": distribution_risk_score(row),
                        "theme_event_risk": theme_event_risk(row),
                        "theme_structural_growth": theme_structural_growth(row),
                    }
                )

        weights = normalize_weights(raw_weights, safe_float(policy.get("capacity"), 1.0), safe_float(policy.get("max_single_name_weight"), 0.33))
        month_turnover = turnover(prev_weights, weights)
        gross_return = 0.0
        next_state: dict[str, dict[str, Any]] = {}
        for ticker, weight in weights.items():
            row = by_ticker.get(ticker, {})
            pos = active_state.get(ticker, {})
            ret = safe_float(row.get(return_col), 0.0)
            row_policy = theme_adjusted_policy(row, policy)
            risk_ret, risk_exit, risk_reason = risk_adjusted_period_return(ret, row_policy)
            cum_before = safe_float(pos.get("cum_return"))
            cum_after = (1.0 + cum_before) * (1.0 + risk_ret) - 1.0
            peak_after = max(safe_float(pos.get("peak_return")), cum_after)
            if risk_exit and bool(row_policy.get("hard_stop_exit", True)):
                event_rows.append(
                    {
                        "rebalance_date": dt,
                        "ticker": ticker,
                        "action": "exit",
                        "reason": risk_reason,
                        "stage": pos.get("stage"),
                        "score": pos.get("last_score"),
                        "period_forward_return": ret,
                        "risk_adjusted_forward_return": risk_ret,
                    }
                )
            else:
                next_state[ticker] = {
                    "stage": pos.get("stage", "scout"),
                    "cum_return": cum_after,
                    "peak_return": peak_after,
                    "months_held": int(pos.get("months_held", 0)) + 1,
                    "last_score": safe_float(pos.get("last_score")),
                    "last_return": risk_ret,
                    "bad_months": int(pos.get("bad_months", 0)),
                }
            gross_return += weight * risk_ret
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
            pos = next_state.get(ticker) or active_state.get(ticker, {})
            ret = safe_float(row.get(return_col), 0.0)
            row_policy = theme_adjusted_policy(row, policy)
            risk_ret, risk_exit, risk_reason = risk_adjusted_period_return(ret, row_policy)
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
                    "bad_months": pos.get("bad_months"),
                    "period_forward_return": ret,
                    "risk_adjusted_forward_return": risk_ret,
                    "weighted_forward_return": weight * risk_ret,
                    "risk_exit_proxy": risk_exit,
                    "risk_exit_reason": risk_reason,
                    "hard_stop_proxy": row_policy.get("hard_stop_proxy", ""),
                    "sector": row.get("sector", ""),
                    "industry_group": row.get("industry_group", ""),
                    "theme_horizon_primary": row.get("theme_horizon_primary", ""),
                    "theme_holding_profile_primary": row.get("theme_holding_profile_primary", ""),
                    "theme_event_risk_sensitivity_max": row.get("theme_event_risk_sensitivity_max", ""),
                    "theme_structural_growth_max": row.get("theme_structural_growth_max", ""),
                    "technical_leadership_signal": technical_leadership_signal(row),
                    "leadership_signal": leadership_signal(row),
                    "growth_signal": growth_signal(row),
                    "rs_acceleration_score": row.get("rs_acceleration_score", ""),
                    "revenue_growth_final": row.get("revenue_growth_final", ""),
                    "revision_score": max_col(row, ("eps_revision_score", "revision_score", "eps_revision_proxy")),
                    "portfolio_monster_early_score": row.get("portfolio_monster_early_score", ""),
                    "portfolio_risk_entry_block_score": row.get("portfolio_risk_entry_block_score", ""),
                    "portfolio_defensive_rotation_action": row.get("portfolio_defensive_rotation_action", ""),
                    "distribution_risk_score": distribution_risk_score(row),
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
            "max_new_scouts_per_month": policy["max_new_scouts_per_month"],
            "max_total_positions": policy["max_total_positions"],
            "entry_requires_leadership": bool(policy.get("entry_requires_leadership", False)),
            "stale_patience_months": policy.get("stale_patience_months"),
            "scout_timeout_months": policy.get("scout_timeout_months"),
            "hard_stop_proxy": policy.get("hard_stop_proxy"),
            "hard_stop_exit": policy.get("hard_stop_exit"),
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
            f"- Max positions: {int(safe_float(metrics.get('max_total_positions'), 0))}",
            f"- Max new scouts/month: {int(safe_float(metrics.get('max_new_scouts_per_month'), 0))}",
            f"- Entry requires leadership/growth: `{bool(metrics.get('entry_requires_leadership'))}`",
            f"- Stale patience months: {metrics.get('stale_patience_months')}",
            f"- Hard-stop proxy: {safe_float(metrics.get('hard_stop_proxy')):.2%}",
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

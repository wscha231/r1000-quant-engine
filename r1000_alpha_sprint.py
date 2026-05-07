"""Research-only Alpha Sprint sleeve sidecar.

Alpha Sprint is a bull-only short-horizon alpha booster candidate. This module
builds candidates and shadow weights only; it is not connected to production
portfolio construction or order execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


ALPHA_SPRINT_ENABLED = False
ALPHA_SPRINT_TARGET_N = 3
ALPHA_SPRINT_MAX_N = 5
ALPHA_SPRINT_MIN_MARKET_CAP = 1_000_000_000
ALPHA_SPRINT_MIN_DOLLAR_VOL = 20_000_000
ALPHA_SPRINT_MIN_PRICE = 10
ALPHA_SPRINT_RISK_PER_TRADE = 0.0075
ALPHA_SPRINT_HARD_STOP = -0.07
ALPHA_SPRINT_TRAILING_STOP = -0.12
ALPHA_SPRINT_TIME_STOP_DAYS = 30
ALPHA_SPRINT_MAX_SINGLE_NAME_WEIGHT = 0.06

ALPHA_SPRINT_CAPACITY_BY_REGIME = {
    "deep_bear": 0.00,
    "bear": 0.00,
    "neutral": 0.00,
    "bull": 0.05,
    "strong_bull": 0.10,
    "exceptional_bull": 0.15,
}

ALPHA_SPRINT_POLICY = {
    "name": "alpha_sprint_research_only",
    "enabled_default": ALPHA_SPRINT_ENABLED,
    "target_n": ALPHA_SPRINT_TARGET_N,
    "max_n": ALPHA_SPRINT_MAX_N,
    "capacity_by_regime": ALPHA_SPRINT_CAPACITY_BY_REGIME,
    "min_market_cap": ALPHA_SPRINT_MIN_MARKET_CAP,
    "min_dollar_vol": ALPHA_SPRINT_MIN_DOLLAR_VOL,
    "min_price": ALPHA_SPRINT_MIN_PRICE,
    "risk_per_trade": ALPHA_SPRINT_RISK_PER_TRADE,
    "hard_stop": ALPHA_SPRINT_HARD_STOP,
    "trailing_stop": ALPHA_SPRINT_TRAILING_STOP,
    "time_stop_days": ALPHA_SPRINT_TIME_STOP_DAYS,
    "max_single_name_weight": ALPHA_SPRINT_MAX_SINGLE_NAME_WEIGHT,
}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if out != out:
            return default
        return out
    except (TypeError, ValueError):
        return default


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def infer_regime(rows: list[dict[str, Any]], default: str = "neutral") -> str:
    counts: dict[str, int] = {}
    for row in rows:
        regime = str(row.get("regime_state") or row.get("event_regime_label") or "").strip()
        if regime:
            counts[regime] = counts.get(regime, 0) + 1
    if not counts:
        return default
    return max(counts.items(), key=lambda item: item[1])[0]


def _first_float(row: dict[str, Any], keys: tuple[str, ...], default: float = 0.0) -> float:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return safe_float(value, default)
    return default


def _theme_phase_term(row: dict[str, Any]) -> float:
    return max(
        safe_float(row.get("theme_phase_multiplier_primary"), 1.0) - 1.0,
        safe_float(row.get("theme_phase_multiplier_max"), 1.0) - 1.0,
        safe_float(row.get("sector_leader_score")),
        safe_float(row.get("leader_emergence_score")),
        0.0,
    )


def _earnings_revision_or_surprise(row: dict[str, Any]) -> float:
    return max(
        safe_float(row.get("eps_revision_score")),
        safe_float(row.get("revision_score")),
        safe_float(row.get("eps_revision_proxy")),
        safe_float(row.get("actual_results_score")),
        safe_float(row.get("event_reaction_score")),
        0.0,
    )


def compute_alpha_sprint_score(row: dict[str, Any]) -> float:
    return (
        0.20 * safe_float(row.get("rs_acceleration_score"))
        + 0.18 * safe_float(row.get("breakout_setup_quality_score"))
        + 0.15 * safe_float(row.get("volatility_contraction_score"))
        + 0.15 * safe_float(row.get("explosion_entry_score"))
        + 0.10 * safe_float(row.get("h6_dynamic_leader_score"))
        + 0.10 * _theme_phase_term(row)
        + 0.07 * _earnings_revision_or_surprise(row)
        + 0.05 * safe_float(row.get("industry_group_strength_score"))
        - 0.20 * safe_float(row.get("explosion_exit_score"))
        - 0.20 * safe_float(row.get("stage2_overext_penalty"))
        - 0.15 * safe_float(row.get("live_event_risk_score"))
    )


def universe_filter_flags(row: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, bool]:
    policy = policy or ALPHA_SPRINT_POLICY
    market_cap = _first_float(row, ("market_cap_live", "mktcap"))
    price = _first_float(row, ("current_price_live", "px"))
    dollar_vol = safe_float(row.get("dollar_vol_20d"))
    return {
        "market_cap_ok": market_cap >= safe_float(policy.get("min_market_cap"), ALPHA_SPRINT_MIN_MARKET_CAP),
        "dollar_volume_ok": dollar_vol >= safe_float(policy.get("min_dollar_vol"), ALPHA_SPRINT_MIN_DOLLAR_VOL),
        "price_ok": price >= safe_float(policy.get("min_price"), ALPHA_SPRINT_MIN_PRICE),
        "not_pattern_blocked": not truthy(row.get("pattern_blocked")),
    }


def catalyst_flags(row: dict[str, Any]) -> dict[str, bool]:
    return {
        "earnings_revision_or_surprise": _earnings_revision_or_surprise(row) > 0.25,
        "revenue_growth_acceleration": safe_float(row.get("revenue_growth_final")) > 0.15
        or safe_float(row.get("rev_growth_accel_4q")) > 0.02,
        "profitability_turn": any(
            truthy(row.get(key)) or safe_float(row.get(key)) > 0
            for key in (
                "profit_turn_positive_4q",
                "cashflow_turn_positive_4q",
                "any_profitability_turn_positive_4q",
                "ni_loss_narrowing_4q",
            )
        ),
        "theme_or_industry_acceleration": _theme_phase_term(row) > 0.15
        or safe_float(row.get("industry_group_strength_score")) > 0.15,
        "explosion_entry": safe_float(row.get("explosion_entry_score")) > 0,
    }


def technical_gate_flags(row: dict[str, Any]) -> dict[str, bool]:
    setup_confirmations = [
        safe_float(row.get("near_52w_high_pct")) >= -0.12,
        safe_float(row.get("breakout_fresh_20d")) > 0,
        safe_float(row.get("breakout_volume_z")) > 0,
        safe_float(row.get("volume_dryup_20d")) > 0,
        safe_float(row.get("volatility_contraction_score")) > 0,
        safe_float(row.get("post_breakout_hold_score")) >= 0.45,
        safe_float(row.get("minervini_trend_template_score")) > 0,
    ]
    return {
        "price_above_ma50": safe_float(row.get("price_above_ma50")) > 0,
        "price_above_ma200": safe_float(row.get("price_above_ma200")) > 0,
        "setup_confirmation": sum(1 for ok in setup_confirmations if ok) >= 2,
    }


def overextension_flags(row: dict[str, Any]) -> dict[str, bool]:
    return {
        "stage2_overextension_ok": safe_float(row.get("stage2_overext_penalty")) < 1.0,
        "explosion_exit_ok": safe_float(row.get("explosion_exit_score")) <= 0.75,
        "live_event_risk_ok": safe_float(row.get("live_event_risk_score")) <= 0.75,
        "atr_ok": safe_float(row.get("atr14_pct")) <= 0.12,
        "rsi_not_climax": safe_float(row.get("rsi14")) <= 85.0,
    }


def candidate_passes(row: dict[str, Any], policy: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
    universe = universe_filter_flags(row, policy)
    catalyst = catalyst_flags(row)
    technical = technical_gate_flags(row)
    overextension = overextension_flags(row)
    pass_flags = {
        "universe_pass": all(universe.values()),
        "catalyst_pass": any(catalyst.values()),
        "technical_pass": all(technical.values()),
        "overextension_pass": all(overextension.values()),
    }
    detail = {
        "universe": universe,
        "catalyst": catalyst,
        "technical": technical,
        "overextension": overextension,
        "pass_flags": pass_flags,
    }
    return all(pass_flags.values()), detail


def build_alpha_sprint_candidates(
    rows: list[dict[str, Any]],
    regime_state: str | None = None,
    policy: dict[str, Any] | None = None,
    top_n: int | None = None,
) -> dict[str, Any]:
    policy = policy or ALPHA_SPRINT_POLICY
    regime_state = str(regime_state or infer_regime(rows))
    limit = int(top_n or policy.get("max_n") or ALPHA_SPRINT_MAX_N)
    candidates: list[dict[str, Any]] = []
    rejected_counts = {"universe": 0, "catalyst": 0, "technical": 0, "overextension": 0}
    for row in rows:
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker or ticker == "CASH":
            continue
        score = compute_alpha_sprint_score(row)
        passed, detail = candidate_passes(row, policy)
        if not passed:
            flags = detail["pass_flags"]
            if not flags["universe_pass"]:
                rejected_counts["universe"] += 1
            elif not flags["catalyst_pass"]:
                rejected_counts["catalyst"] += 1
            elif not flags["technical_pass"]:
                rejected_counts["technical"] += 1
            elif not flags["overextension_pass"]:
                rejected_counts["overextension"] += 1
            continue
        if score <= 0:
            continue
        candidates.append(
            {
                "ticker": ticker,
                "name": row.get("Name"),
                "sector": row.get("sector"),
                "industry_group": row.get("industry_group"),
                "alpha_sprint_score": score,
                "rs_acceleration_score": safe_float(row.get("rs_acceleration_score")),
                "breakout_setup_quality_score": safe_float(row.get("breakout_setup_quality_score")),
                "volatility_contraction_score": safe_float(row.get("volatility_contraction_score")),
                "explosion_entry_score": safe_float(row.get("explosion_entry_score")),
                "h6_dynamic_leader_score": safe_float(row.get("h6_dynamic_leader_score")),
                "theme_phase_term": _theme_phase_term(row),
                "earnings_revision_or_surprise": _earnings_revision_or_surprise(row),
                "industry_group_strength_score": safe_float(row.get("industry_group_strength_score")),
                "stage2_overext_penalty": safe_float(row.get("stage2_overext_penalty")),
                "explosion_exit_score": safe_float(row.get("explosion_exit_score")),
                "live_event_risk_score": safe_float(row.get("live_event_risk_score")),
                "atr14_pct": safe_float(row.get("atr14_pct")),
                "rsi14": safe_float(row.get("rsi14")),
                "gate_detail": detail,
            }
        )
    candidates.sort(key=lambda item: item["alpha_sprint_score"], reverse=True)
    candidates = candidates[:limit]
    return {
        "regime_state": regime_state,
        "candidates": candidates,
        "audit": {
            "research_only": True,
            "candidate_count": len(candidates),
            "rejected_counts": rejected_counts,
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "production_activation_allowed": False,
        },
    }


def construct_alpha_sprint_weights(
    candidates: list[dict[str, Any]],
    regime_state: str,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or ALPHA_SPRINT_POLICY
    capacity = safe_float((policy.get("capacity_by_regime") or {}).get(regime_state), 0.0)
    active = capacity > 0 and len(candidates) >= 2
    hard_stop_distance = abs(safe_float(policy.get("hard_stop"), ALPHA_SPRINT_HARD_STOP))
    risk_per_trade = safe_float(policy.get("risk_per_trade"), ALPHA_SPRINT_RISK_PER_TRADE)
    max_single = safe_float(policy.get("max_single_name_weight"), ALPHA_SPRINT_MAX_SINGLE_NAME_WEIGHT)
    base_single = min(max_single, risk_per_trade / hard_stop_distance) if hard_stop_distance > 0 else max_single

    weights: dict[str, float] = {}
    if active:
        selected = candidates[: int(policy.get("target_n") or ALPHA_SPRINT_TARGET_N)]
        raw = {str(item["ticker"]): base_single for item in selected}
        total_raw = sum(raw.values())
        scale = min(1.0, capacity / total_raw) if total_raw > 0 else 0.0
        weights = {ticker: weight * scale for ticker, weight in raw.items()}

    invested = sum(weights.values())
    return {
        "weights": dict(sorted(weights.items(), key=lambda item: item[1], reverse=True)),
        "cash_target": max(0.0, min(1.0, 1.0 - invested)),
        "activation": {
            "active": active,
            "reason": "active" if active else "capacity_zero_or_insufficient_candidates",
            "regime_state": regime_state,
            "capacity": capacity,
            "candidate_count": len(candidates),
            "min_candidates_required": 2,
        },
        "risk_policy": {
            "risk_per_trade": risk_per_trade,
            "hard_stop": safe_float(policy.get("hard_stop"), ALPHA_SPRINT_HARD_STOP),
            "trailing_stop": safe_float(policy.get("trailing_stop"), ALPHA_SPRINT_TRAILING_STOP),
            "time_stop_days": int(policy.get("time_stop_days") or ALPHA_SPRINT_TIME_STOP_DAYS),
            "max_single_name_weight": max_single,
            "base_single_name_weight_from_risk": base_single,
        },
    }


def build_alpha_sprint_snapshot(
    rows: list[dict[str, Any]],
    regime_state: str | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or ALPHA_SPRINT_POLICY
    candidate_result = build_alpha_sprint_candidates(rows, regime_state=regime_state, policy=policy)
    weights_result = construct_alpha_sprint_weights(
        candidate_result["candidates"],
        candidate_result["regime_state"],
        policy=policy,
    )
    return {
        "policy": policy,
        "regime_state": candidate_result["regime_state"],
        "candidates": candidate_result["candidates"],
        "portfolio": weights_result,
        "audit": {
            **candidate_result["audit"],
            "active": weights_result["activation"]["active"],
            "capacity": weights_result["activation"]["capacity"],
            "n_positions": len(weights_result["weights"]),
        },
    }

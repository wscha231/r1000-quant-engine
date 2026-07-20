"""Canonical Run287 crisis, selective-defense, and re-entry policy.

This module is deliberately pure: no filesystem, network, broker, or clock I/O.
Historical replay, the current monitor, and same-close paper target construction
must all call this policy instead of maintaining separate state or cash logic.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd


SCHEMA_VERSION = "run287-canonical-crisis-policy-v1"
CANONICAL_STATES = (
    "GREEN",
    "WATCH",
    "DEFENSE",
    "CRISIS",
    "REENTRY_STAGE_1",
    "REENTRY_STAGE_2",
    "REENTRY_STAGE_3",
    "DEGRADED_DATA",
)
STATE_RANK = {
    "GREEN": 0,
    "REENTRY_STAGE_3": 0,
    "REENTRY_STAGE_2": 1,
    "REENTRY_STAGE_1": 2,
    "WATCH": 3,
    "DEFENSE": 4,
    "DEGRADED_DATA": 5,
    "CRISIS": 6,
}
LEGACY_STATE_ALIASES = {
    "NORMAL": "GREEN",
    "CAUTION": "WATCH",
    "DEFENSE_REVIEW": "DEFENSE",
    "CRISIS_DEFENSE": "CRISIS",
    "REENTRY_READY": "REENTRY_STAGE_1",
}
FUTURE_LABEL_COLUMNS = {"false_alarm_no_drawdown_63d"}
RESERVE_REASONS = (
    "crisis_reserve",
    "capacity_unallocated",
    "reentry_pending",
    "data_block_reserve",
    "transaction_buffer",
    "residual_cash",
)
SELL_PRIORITY_REASONS = (
    "THESIS_BREAK",
    "RS_TREND_BREAK",
    "LOSS_BETA_VOLATILITY",
    "DUPLICATED_EXPOSURE",
    "LOW_CONVICTION",
    "EMERGENCY_PROPORTIONAL",
)
REENTRY_THRESHOLDS = (0.40, 0.60, 0.75)
REENTRY_GROSS_MULTIPLIERS = {
    "REENTRY_STAGE_1": 0.25,
    "REENTRY_STAGE_2": 0.60,
    "REENTRY_STAGE_3": 1.00,
}


@dataclass(frozen=True)
class ComponentAvailability:
    component: str
    available: bool
    fresh: bool
    available_from: str
    critical: bool
    fixed_weight: float
    value: float | None
    source_field: str
    caveat: str = ""


@dataclass(frozen=True)
class StateDecision:
    state: str
    raw_state: str
    prior_state: str
    reentry_score: float
    reentry_multiplier: float
    missing_components: tuple[str, ...]
    missing_critical_components: tuple[str, ...]
    transition_reason: str


@dataclass(frozen=True)
class ExposurePolicy:
    state: str
    normal_equity_weight: float
    target_equity_weight: float
    target_reserve_weight: float
    block_new_buys: bool
    selective_sell_required: bool
    reentry_multiplier: float
    valid_core_exposure_floor: float


COMPONENT_SPECS: tuple[tuple[str, tuple[str, ...], bool, float], ...] = (
    ("spy_trend_drawdown", ("market_trend_damage_score", "spy_drawdown", "spy_20d_dd"), True, 0.00),
    ("qqq_trend", ("qqq_below_ma200", "qqq_close"), True, 0.25),
    ("universe_breadth", ("market_breadth_above_ma200",), False, 0.20),
    ("hy_oas", ("hy_oas_zscore_252d", "hy_oas_zscore_60d", "credit_stress_score"), True, 0.15),
    ("vix", ("vix_zscore_252d", "vix_zscore_60d", "volatility_stress_score"), True, 0.30),
    ("liquidity", ("liquidity_confirmation_score",), False, 0.00),
    ("rate_shock", ("rate_shock_score", "ten_year_20d_change_bps"), False, 0.00),
    ("sector_industry_breadth", ("market_sector_participation",), False, 0.00),
    ("leadership", ("market_leadership_narrowing",), False, 0.10),
)


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if np.isfinite(result) else default


def canonical_state(value: Any, reentry_stage: Any = "") -> str:
    state = str(value or "GREEN").upper().strip()
    stage = str(reentry_stage or "").upper().strip()
    if state == "REENTRY_READY" and stage in REENTRY_GROSS_MULTIPLIERS:
        return stage
    state = LEGACY_STATE_ALIASES.get(state, state)
    return state if state in CANONICAL_STATES else "DEGRADED_DATA"


def strip_future_labels(frame: pd.DataFrame) -> pd.DataFrame:
    """Physically remove all future-label columns before inference."""
    columns = [
        column
        for column in frame.columns
        if not str(column).lower().startswith("future_")
        and str(column) not in FUTURE_LABEL_COLUMNS
    ]
    return frame.loc[:, columns].copy()


def _availability_date(value: Any) -> pd.Timestamp:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return parsed if not pd.isna(parsed) else pd.NaT


def component_availability(
    values: Mapping[str, Any],
    *,
    decision_time: Any = None,
    available_from: Any = None,
) -> list[ComponentAvailability]:
    decision = _availability_date(decision_time)
    global_available = _availability_date(available_from)
    rows: list[ComponentAvailability] = []
    for component, fields, critical, fixed_weight in COMPONENT_SPECS:
        source_field = next(
            (field for field in fields if safe_float(values.get(field)) is not None), ""
        )
        value = safe_float(values.get(source_field)) if source_field else None
        component_available_from = _availability_date(
            values.get(f"{component}_available_from", global_available)
        )
        future = bool(
            not pd.isna(decision)
            and not pd.isna(component_available_from)
            and component_available_from > decision
        )
        explicitly_stale = bool(values.get(f"{component}_stale", False))
        available = value is not None and not future
        fresh = available and not explicitly_stale
        caveat = ""
        if future:
            caveat = "available_after_decision"
        elif value is None:
            caveat = "missing"
        elif explicitly_stale:
            caveat = "stale"
        rows.append(
            ComponentAvailability(
                component=component,
                available=available,
                fresh=fresh,
                available_from=(
                    component_available_from.isoformat()
                    if not pd.isna(component_available_from)
                    else ""
                ),
                critical=critical,
                fixed_weight=fixed_weight,
                value=value,
                source_field=source_field,
                caveat=caveat,
            )
        )
    return rows


def availability_records(rows: list[ComponentAvailability]) -> list[dict[str, Any]]:
    return [asdict(row) for row in rows]


def _recovery_component(values: Mapping[str, Any], component: str) -> float:
    if component == "vix":
        z = safe_float(values.get("vix_zscore_252d"))
        if z is None:
            z = safe_float(values.get("vix_zscore_60d"))
        if z is not None:
            return float(np.clip(1.0 - max(z, 0.0) / 2.0, 0.0, 1.0))
        stress = safe_float(values.get("volatility_stress_score"))
        return float(np.clip(1.0 - (stress or 0.0), 0.0, 1.0)) if stress is not None else 0.0
    if component == "qqq_trend":
        below = safe_float(values.get("qqq_below_ma200"))
        if below is not None:
            return float(np.clip(1.0 - below, 0.0, 1.0))
        close = safe_float(values.get("qqq_close"))
        ma200 = safe_float(values.get("qqq_ma200"))
        return 1.0 if close is not None and ma200 and close >= ma200 else 0.0
    if component == "universe_breadth":
        return float(np.clip(safe_float(values.get("market_breadth_above_ma200"), 0.0) or 0.0, 0.0, 1.0))
    if component == "hy_oas":
        z = safe_float(values.get("hy_oas_zscore_252d"))
        if z is None:
            z = safe_float(values.get("hy_oas_zscore_60d"))
        if z is not None:
            return float(np.clip(1.0 - max(z, 0.0) / 2.0, 0.0, 1.0))
        stress = safe_float(values.get("credit_stress_score"))
        return float(np.clip(1.0 - (stress or 0.0), 0.0, 1.0)) if stress is not None else 0.0
    if component == "leadership":
        narrowing = safe_float(values.get("market_leadership_narrowing"))
        return float(np.clip(1.0 - (narrowing or 0.0), 0.0, 1.0)) if narrowing is not None else 0.0
    return 0.0


def compute_reentry_score(
    values: Mapping[str, Any], availability: list[ComponentAvailability]
) -> float:
    """Use fixed weights; missing components contribute zero and are never renormalized."""
    by_name = {row.component: row for row in availability}
    score = 0.0
    for component in ("vix", "qqq_trend", "universe_breadth", "hy_oas", "leadership"):
        row = by_name[component]
        if row.available and row.fresh:
            score += row.fixed_weight * _recovery_component(values, component)
    return float(np.clip(score, 0.0, 1.0))


def stronger_state(left: Any, right: Any) -> str:
    a = canonical_state(left)
    b = canonical_state(right)
    return a if STATE_RANK[a] >= STATE_RANK[b] else b


def _reentry_stage(score: float) -> str:
    if score >= REENTRY_THRESHOLDS[2]:
        return "REENTRY_STAGE_3"
    if score >= REENTRY_THRESHOLDS[1]:
        return "REENTRY_STAGE_2"
    return "REENTRY_STAGE_1"


def transition_state(
    *,
    raw_state: Any,
    prior_state: Any,
    raw_state_streak: int,
    values: Mapping[str, Any],
    availability: list[ComponentAvailability],
) -> StateDecision:
    raw = canonical_state(raw_state)
    prior = canonical_state(prior_state)
    missing = tuple(row.component for row in availability if not row.available or not row.fresh)
    missing_critical = tuple(
        row.component
        for row in availability
        if row.critical and (not row.available or not row.fresh)
    )
    score = compute_reentry_score(values, availability)
    if missing_critical:
        state = "DEGRADED_DATA"
        reason = "critical_component_unavailable"
    elif raw == "CRISIS":
        state = "CRISIS"
        reason = "immediate_crisis"
    elif raw == "DEFENSE":
        state = "DEFENSE" if raw_state_streak >= 2 or prior != "GREEN" else "GREEN"
        reason = "confirmed_defense" if state == "DEFENSE" else "defense_confirmation_pending"
    elif raw == "WATCH":
        if prior in {"CRISIS", "DEFENSE", "DEGRADED_DATA"}:
            state = "DEFENSE" if prior != "DEGRADED_DATA" else "DEGRADED_DATA"
            reason = "defense_not_released_on_watch"
        else:
            state = "WATCH" if raw_state_streak >= 2 or prior != "GREEN" else "GREEN"
            reason = "confirmed_watch" if state == "WATCH" else "watch_confirmation_pending"
    elif prior in {"CRISIS", "DEFENSE", "DEGRADED_DATA"}:
        if score < REENTRY_THRESHOLDS[0]:
            state = "DEFENSE" if prior != "DEGRADED_DATA" else "DEGRADED_DATA"
            reason = "reentry_threshold_not_met"
        else:
            state = _reentry_stage(score)
            reason = "reentry_score_threshold"
    elif prior.startswith("REENTRY_STAGE_"):
        state = _reentry_stage(score) if score >= REENTRY_THRESHOLDS[0] else "DEFENSE"
        reason = "reentry_progress" if state.startswith("REENTRY") else "reentry_failed"
    else:
        state = "GREEN"
        reason = "risk_on"
    multiplier = REENTRY_GROSS_MULTIPLIERS.get(state, 1.0)
    return StateDecision(
        state=state,
        raw_state=raw,
        prior_state=prior,
        reentry_score=score,
        reentry_multiplier=multiplier,
        missing_components=missing,
        missing_critical_components=missing_critical,
        transition_reason=reason,
    )


def exposure_policy(state: Any, normal_equity_weight: float, portfolio_kind: str) -> ExposurePolicy:
    canonical = canonical_state(state)
    normal = float(np.clip(normal_equity_weight, 0.0, 1.0))
    core_floor = 0.40 if str(portfolio_kind).lower() == "main" else 0.30
    if canonical == "GREEN":
        target = normal
        block, selective, multiplier = False, False, 1.0
    elif canonical == "WATCH":
        target = normal
        block, selective, multiplier = True, False, 1.0
    elif canonical == "DEFENSE":
        target = min(normal, max(core_floor, 0.75))
        block, selective, multiplier = True, target < normal - 1e-12, target / normal if normal else 0.0
    elif canonical == "CRISIS":
        target = min(normal, max(core_floor, 0.50))
        block, selective, multiplier = True, target < normal - 1e-12, target / normal if normal else 0.0
    elif canonical == "DEGRADED_DATA":
        target = min(normal, max(core_floor, 0.60))
        block, selective, multiplier = True, target < normal - 1e-12, target / normal if normal else 0.0
    else:
        multiplier = REENTRY_GROSS_MULTIPLIERS[canonical]
        target = normal * multiplier
        block = canonical != "REENTRY_STAGE_3"
        selective = target < normal - 1e-12
    return ExposurePolicy(
        state=canonical,
        normal_equity_weight=normal,
        target_equity_weight=float(target),
        target_reserve_weight=float(1.0 - target),
        block_new_buys=block,
        selective_sell_required=selective,
        reentry_multiplier=float(multiplier),
        valid_core_exposure_floor=float(core_floor),
    )


def _bool(row: Mapping[str, Any], *names: str) -> bool:
    for name in names:
        value = row.get(name)
        if isinstance(value, str):
            if value.strip().lower() in {"1", "true", "yes", "alert", "broken"}:
                return True
        elif bool(value) if value is not None and not pd.isna(value) else False:
            return True
    return False


def sell_priority(row: Mapping[str, Any]) -> tuple[int, float, str]:
    state = str(row.get("held_risk_state") or row.get("risk_state") or "").upper()
    reasons = str(row.get("held_risk_reason_codes") or row.get("risk_reason_codes") or "").upper()
    if _bool(row, "confirmed_thesis_break", "thesis_break", "fundamental_break"):
        return 1, 0.0, "THESIS_BREAK"
    severe = _bool(row, "severe_rs_trend_break", "trend_break") or (
        state == "ALERT" and any(token in reasons for token in ("TREND", "RS", "MA200", "GAP"))
    )
    if severe:
        return 2, 0.0, "RS_TREND_BREAK"
    loss = safe_float(row.get("loss_contribution"), 0.0) or 0.0
    beta = safe_float(row.get("beta"), 0.0) or 0.0
    vol = safe_float(row.get("volatility"), safe_float(row.get("vol_252d"), 0.0)) or 0.0
    if state == "ALERT" or _bool(row, "high_loss_beta_volatility") or loss > 0 or beta > 1.5:
        severity = loss + max(beta - 1.0, 0.0) + vol
        return 3, -severity, "LOSS_BETA_VOLATILITY"
    if _bool(row, "duplicated_exposure", "sector_duplicate", "theme_duplicate", "factor_duplicate"):
        return 4, 0.0, "DUPLICATED_EXPOSURE"
    conviction = safe_float(
        row.get("current_conviction"),
        safe_float(row.get("alphaops_vnext_score"), safe_float(row.get("score"), 0.0)),
    ) or 0.0
    return 5, conviction, "LOW_CONVICTION"


def _evidence_by_ticker(evidence: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    if evidence is None or evidence.empty or "ticker" not in evidence.columns:
        return {}
    work = evidence.copy()
    work["ticker"] = work["ticker"].astype(str).str.upper().str.strip()
    return {
        str(row["ticker"]): row
        for row in work.drop_duplicates("ticker", keep="last").to_dict("records")
    }


def apply_selective_defense(
    weights: pd.DataFrame,
    *,
    state: Any,
    portfolio_kind: str,
    evidence: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    """Apply the canonical policy without default uniform non-cash scaling."""
    if not {"ticker", "weight"}.issubset(weights.columns):
        raise ValueError("weights require ticker and weight")
    out = weights[["ticker", "weight"]].copy()
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce")
    if out["weight"].isna().any() or out["ticker"].duplicated().any():
        raise ValueError("invalid or duplicate target weights")
    if not np.isclose(float(out["weight"].sum()), 1.0, atol=1e-9):
        raise ValueError("target weights must sum to one")
    cash_mask = out["ticker"].eq("CASH")
    if not cash_mask.any():
        out = pd.concat([out, pd.DataFrame([{"ticker": "CASH", "weight": 0.0}])], ignore_index=True)
        cash_mask = out["ticker"].eq("CASH")
    base_cash = float(out.loc[cash_mask, "weight"].sum())
    base_equity = 1.0 - base_cash
    policy = exposure_policy(state, base_equity, portfolio_kind)
    required = max(0.0, base_equity - policy.target_equity_weight)
    evidence_map = _evidence_by_ticker(evidence)
    candidates: list[tuple[int, float, str, int, float]] = []
    for index, row in out.loc[~cash_mask].iterrows():
        ticker = str(row["ticker"])
        priority, secondary, reason = sell_priority(evidence_map.get(ticker, {}))
        candidates.append((priority, secondary, ticker, int(index), float(row["weight"])))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    actions: list[dict[str, Any]] = []
    remaining = required
    for priority, _secondary, ticker, index, current in candidates:
        if remaining <= 1e-12:
            break
        reason = sell_priority(evidence_map.get(ticker, {}))[2]
        trim = min(current, remaining)
        if trim <= 1e-12:
            continue
        out.loc[index, "weight"] = current - trim
        remaining -= trim
        actions.append(
            {
                "ticker": ticker,
                "priority": priority,
                "reason": reason,
                "weight_before": current,
                "trim_weight": trim,
                "weight_after": current - trim,
            }
        )
    if remaining > 1e-9:
        # This can happen only with malformed/non-equity rows; retain an explicit
        # emergency audit instead of silently renormalizing surviving positions.
        actions.append(
            {
                "ticker": "*",
                "priority": 6,
                "reason": "EMERGENCY_PROPORTIONAL",
                "weight_before": base_equity,
                "trim_weight": required - remaining,
                "weight_after": base_equity - required + remaining,
            }
        )
        raise ValueError("unable to reach reserve target from equity weights")
    final_equity = float(out.loc[~out["ticker"].eq("CASH"), "weight"].sum())
    final_cash = 1.0 - final_equity
    out.loc[out["ticker"].eq("CASH"), "weight"] = 0.0
    first_cash = out.index[out["ticker"].eq("CASH")][0]
    out.loc[first_cash, "weight"] = final_cash
    reserve = {reason: 0.0 for reason in RESERVE_REASONS}
    reserve["capacity_unallocated"] = base_cash
    incremental = max(0.0, final_cash - base_cash)
    if policy.state in {"DEFENSE", "CRISIS"}:
        reserve["crisis_reserve"] = incremental
    elif policy.state.startswith("REENTRY_STAGE_"):
        reserve["reentry_pending"] = incremental
    elif policy.state == "DEGRADED_DATA":
        reserve["data_block_reserve"] = incremental
    reserve["residual_cash"] = final_cash - sum(reserve.values())
    if abs(reserve["residual_cash"]) < 1e-12:
        reserve["residual_cash"] = 0.0
    if not np.isclose(sum(reserve.values()), final_cash, atol=1e-9):
        raise ValueError("reserve reason reconciliation failure")
    out = out.loc[out["weight"].gt(1e-12)].sort_values(
        ["weight", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "policy": asdict(policy),
        "base_cash_weight": base_cash,
        "final_cash_weight": final_cash,
        "incremental_policy_reserve": incremental,
        "reserve_reasons": reserve,
        "selective_sell_count": len(actions),
        "selective_sell_counts_by_reason": {
            reason: sum(action["reason"] == reason for action in actions)
            for reason in SELL_PRIORITY_REASONS
        },
        "uniform_noncash_scaling_used": False,
        "weights_conserved": bool(np.isclose(float(out["weight"].sum()), 1.0, atol=1e-9)),
    }
    return out, actions, summary

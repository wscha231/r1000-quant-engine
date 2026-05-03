"""Research-only concentrated sleeve policy and audit helpers.

The constants here define challenger policy maps for the concentrated alpha
book. They are not wired into production selection or execution by default.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


CONCENTRATED_CAPACITY_MAPS = {
    "conservative": {
        "deep_bear": 0.00,
        "bear": 0.05,
        "neutral": 0.10,
        "bull": 0.15,
        "strong_bull": 0.20,
    },
    "balanced": {
        "deep_bear": 0.00,
        "bear": 0.05,
        "neutral": 0.20,
        "bull": 0.25,
        "strong_bull": 0.30,
    },
    "aggressive": {
        "deep_bear": 0.00,
        "bear": 0.05,
        "neutral": 0.25,
        "bull": 0.35,
        "strong_bull": 0.40,
    },
}

CONCENTRATED_TARGET_N_BY_REGIME = {
    "deep_bear": 0,
    "bear": 3,
    "neutral": 5,
    "bull": 5,
    "strong_bull": 3,
}

CONCENTRATED_RISK_BUDGET = {
    "single_name_cap": 0.25,
    "high_conviction_cap": 0.30,
    "theme_cap": 0.45,
    "sector_cap": 0.55,
    "unified_single_name_cap": 0.18,
    "unified_theme_cap": 0.40,
    "sleeve_dd_scale_down": -0.08,
    "sleeve_dd_disable": -0.15,
}

CONCENTRATED_ENTRY_GATE = {
    "min_entry_quality_score": 0.70,
    "require_price_above_ma50": True,
    "require_price_above_ma200": True,
    "block_if_theme_ending": True,
}

CONCENTRATED_EXIT_RULES = {
    "hard_stop": -0.10,
    "trailing_stop": -0.15,
    "rs_decay_pp": -30,
    "review_days": 7,
    "enable_better_replacement_swap": True,
}

CONCENTRATED_POLICY_BY_REGIME = {
    "capacity": CONCENTRATED_CAPACITY_MAPS["balanced"],
    "target_n": CONCENTRATED_TARGET_N_BY_REGIME,
    "risk": CONCENTRATED_RISK_BUDGET,
    "entry": CONCENTRATED_ENTRY_GATE,
    "exit": CONCENTRATED_EXIT_RULES,
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


def concentrated_conviction_score(row: dict[str, Any]) -> float:
    revision_or_cycle = max(
        safe_float(row.get("revision_score")),
        safe_float(row.get("eps_revision_score")),
        safe_float(row.get("cycle_recovery_score")),
    )
    theme_leadership = max(
        safe_float(row.get("theme_phase_multiplier_primary"), 1.0) - 1.0,
        safe_float(row.get("theme_phase_multiplier_max"), 1.0) - 1.0,
        safe_float(row.get("leader_emergence_score")),
        safe_float(row.get("sector_leader_score")),
    )
    return (
        0.25 * safe_float(row.get("portfolio_future_winner_engine_score"))
        + 0.20 * safe_float(row.get("multi_year_winner_score"))
        + 0.15 * safe_float(row.get("rs_acceleration_score"))
        + 0.15 * safe_float(row.get("entry_quality_score"))
        + 0.10 * safe_float(row.get("industry_group_strength_score"))
        + 0.10 * theme_leadership
        + 0.05 * revision_or_cycle
        - 0.20 * safe_float(row.get("stage2_overext_penalty"))
        - 0.20 * safe_float(row.get("risk_penalty"))
    )


def entry_gate_flags(row: dict[str, Any], gate: dict[str, Any] | None = None) -> dict[str, bool]:
    gate = gate or CONCENTRATED_ENTRY_GATE
    entry_quality = safe_float(row.get("entry_quality_score"))
    theme_primary = str(row.get("theme_phase_primary") or row.get("theme_phase") or "").lower()
    theme_block = bool(gate.get("block_if_theme_ending")) and theme_primary in {"ending", "dead"}
    return {
        "entry_quality_ok": entry_quality >= safe_float(gate.get("min_entry_quality_score"), 0.70),
        "price_above_ma50_ok": (not gate.get("require_price_above_ma50")) or safe_float(row.get("price_above_ma50")) > 0,
        "price_above_ma200_ok": (not gate.get("require_price_above_ma200")) or safe_float(row.get("price_above_ma200")) > 0,
        "theme_not_blocked": not theme_block,
    }


def risk_gate_flags(row: dict[str, Any]) -> dict[str, bool]:
    return {
        "not_pattern_blocked": not truthy(row.get("pattern_blocked")),
        "overextension_ok": safe_float(row.get("stage2_overext_penalty")) < 1.0,
        "rs_not_decaying": safe_float(row.get("rs_acceleration_score")) > -0.5,
        "fundamental_reliability_ok": safe_float(row.get("fundamental_reliability_score"), 0.0) >= 0.45,
    }


def audit_concentrated_portfolio(
    holdings: list[dict[str, Any]],
    scored_rows: list[dict[str, Any]] | None = None,
    regime_state: str | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or CONCENTRATED_POLICY_BY_REGIME
    scored_by_ticker = {
        str(row.get("ticker") or "").upper(): row
        for row in scored_rows or []
        if row.get("ticker")
    }
    regime_state = str(regime_state or infer_regime(holdings or (scored_rows or [])))
    risk = dict(policy.get("risk") or {})
    capacity_map = dict(policy.get("capacity") or {})
    target_n_map = dict(policy.get("target_n") or {})
    single_cap = safe_float(risk.get("single_name_cap"), 0.25)
    sector_cap = safe_float(risk.get("sector_cap"), 0.55)

    rows: list[dict[str, Any]] = []
    sector_weights: dict[str, float] = defaultdict(float)
    cap_violations: list[dict[str, Any]] = []
    entry_blocked: list[dict[str, Any]] = []
    risk_blocked: list[dict[str, Any]] = []
    for h in holdings:
        ticker = str(h.get("ticker") or "").upper()
        if not ticker or ticker == "CASH":
            continue
        scored = scored_by_ticker.get(ticker, {})
        merged = dict(scored)
        merged.update(h)
        weight = safe_float(h.get("weight") or h.get("target_weight"))
        sector = str(h.get("sector") or scored.get("sector") or "Unknown")
        sector_weights[sector] += weight
        conviction = concentrated_conviction_score(merged)
        entry_flags = entry_gate_flags(merged, dict(policy.get("entry") or {}))
        risk_flags = risk_gate_flags(merged)
        if weight > single_cap:
            cap_violations.append(
                {
                    "ticker": ticker,
                    "cap_type": "single_name",
                    "weight": weight,
                    "cap": single_cap,
                    "excess": weight - single_cap,
                }
            )
        if not all(entry_flags.values()):
            entry_blocked.append({"ticker": ticker, "failed": [k for k, v in entry_flags.items() if not v]})
        if not all(risk_flags.values()):
            risk_blocked.append({"ticker": ticker, "failed": [k for k, v in risk_flags.items() if not v]})
        rows.append(
            {
                "ticker": ticker,
                "name": h.get("Name") or scored.get("Name"),
                "sector": sector,
                "weight": weight,
                "concentrated_score": safe_float(merged.get("concentrated_score")),
                "concentrated_conviction_score": conviction,
                "entry_gate_pass": all(entry_flags.values()),
                "risk_gate_pass": all(risk_flags.values()),
                "entry_failed": ",".join(k for k, v in entry_flags.items() if not v),
                "risk_failed": ",".join(k for k, v in risk_flags.items() if not v),
            }
        )

    sector_violations = [
        {
            "sector": sector,
            "weight": weight,
            "cap": sector_cap,
            "excess": weight - sector_cap,
        }
        for sector, weight in sorted(sector_weights.items())
        if weight > sector_cap
    ]
    cap_violations.extend({"cap_type": "sector", **row} for row in sector_violations)
    total_weight = sum(safe_float(row.get("weight")) for row in rows)
    return {
        "policy_name": "concentrated_balanced_research_policy",
        "research_only": True,
        "regime_state": regime_state,
        "recommended_capacity": safe_float(capacity_map.get(regime_state), 0.0),
        "recommended_target_n": int(target_n_map.get(regime_state, 0)),
        "current_n": len(rows),
        "current_weight_sum": total_weight,
        "risk_budget": risk,
        "entry_gate": policy.get("entry"),
        "exit_rules": policy.get("exit"),
        "rows": rows,
        "sector_weights": dict(sorted(sector_weights.items(), key=lambda item: item[1], reverse=True)),
        "cap_violations": cap_violations,
        "entry_blocked": entry_blocked,
        "risk_blocked": risk_blocked,
        "audit": {
            "single_name_cap_pass": not any(row.get("cap_type") == "single_name" for row in cap_violations),
            "sector_cap_pass": not sector_violations,
            "entry_gate_all_pass": not entry_blocked,
            "risk_gate_all_pass": not risk_blocked,
            "production_activation_allowed": False,
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }

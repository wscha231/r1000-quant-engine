"""Research-only Main v2 internal sleeve orchestrator.

This module does not replace production portfolio construction. It builds a
shadow `main_v2` book by selecting core/future/early sleeves independently,
scaling each sleeve by regime capacity, merging duplicate tickers with
sum-then-cap, and writing an auditable target.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


MAIN_V2_BALANCED_CAPACITY_BY_REGIME = {
    "deep_bear": {"core": 0.40, "future": 0.20, "early": 0.00, "cash": 0.40},
    "bear": {"core": 0.45, "future": 0.25, "early": 0.05, "cash": 0.25},
    "neutral": {"core": 0.25, "future": 0.55, "early": 0.15, "cash": 0.05},
    "bull": {"core": 0.20, "future": 0.60, "early": 0.20, "cash": 0.00},
    "strong_bull": {"core": 0.15, "future": 0.65, "early": 0.20, "cash": 0.00},
}

MAIN_V2_BALANCED_TARGET_N_BY_REGIME = {
    "deep_bear": {"core": 5, "future": 3, "early": 0},
    "bear": {"core": 5, "future": 4, "early": 1},
    "neutral": {"core": 4, "future": 7, "early": 2},
    "bull": {"core": 3, "future": 8, "early": 3},
    "strong_bull": {"core": 2, "future": 8, "early": 3},
}

MAIN_V2_BALANCED_POLICY = {
    "name": "main_v2_balanced",
    "mode": "research_only",
    "single_name_cap": 0.15,
    "incumbent_buffer": 3,
    "merge_mode": "sum_then_cap",
    "sleeve_capacity_by_regime": MAIN_V2_BALANCED_CAPACITY_BY_REGIME,
    "target_n_by_regime": MAIN_V2_BALANCED_TARGET_N_BY_REGIME,
    "rebalance_months": {"core": 3, "future": 2, "early": 1},
    "bear_feature_overlay": {
        "rs_acceleration_score_factor": 1.3,
        "h1_oversold_value_score_factor": 1.3,
        "theme_phase_multiplier_primary_factor": 0.0,
        "theme_phase_multiplier_max_factor": 0.0,
    },
}

SLEEVE_NAME_MAP = {
    "core": "core_compounder",
    "future": "future_winner",
    "early": "early_scout",
}


@dataclass
class MainV2Result:
    weights: dict[str, float]
    cash_target: float
    by_sleeve_capacity: dict[str, float]
    selected_by_sleeve: dict[str, list[dict[str, Any]]]
    conflicts: list[dict[str, Any]]
    cap_violations: list[dict[str, Any]]
    regime_state: str
    audit: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "main_v2_weights": self.weights,
            "cash_target": self.cash_target,
            "by_sleeve_capacity": self.by_sleeve_capacity,
            "selected_by_sleeve": self.selected_by_sleeve,
            "conflicts": self.conflicts,
            "cap_violations": self.cap_violations,
            "regime_state": self.regime_state,
            "audit": self.audit,
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


def infer_regime(rows: Iterable[dict[str, Any]], default: str = "neutral") -> str:
    counts: dict[str, int] = {}
    for row in rows:
        regime = str(row.get("regime_state") or row.get("event_regime_label") or "").strip()
        if regime:
            counts[regime] = counts.get(regime, 0) + 1
    if not counts:
        return default
    return max(counts.items(), key=lambda item: item[1])[0]


def _theme_multiplier(row: dict[str, Any], regime_state: str) -> float:
    primary = safe_float(row.get("theme_phase_multiplier_primary"), 1.0)
    max_val = safe_float(row.get("theme_phase_multiplier_max"), 1.0)
    if regime_state == "bear":
        return 0.0
    return max(primary, max_val, 0.0)


def score_core(row: dict[str, Any], regime_state: str = "neutral") -> float:
    score = (
        0.40 * safe_float(row.get("portfolio_core_compounder_engine_score"))
        + 0.18 * safe_float(row.get("long_hold_compounder_score"))
        + 0.14 * safe_float(row.get("capital_efficiency_score"))
        + 0.12 * safe_float(row.get("sector_adjusted_quality_score"))
        + 0.08 * safe_float(row.get("multi_year_winner_score"))
        + 0.08 * safe_float(row.get("fundamental_reliability_score"))
        - 0.12 * safe_float(row.get("risk_penalty"))
        - 0.08 * safe_float(row.get("stage2_overext_penalty"))
    )
    if safe_float(row.get("price_above_ma200")) <= 0:
        score -= 0.35
    return score


def score_future(row: dict[str, Any], regime_state: str = "neutral") -> float:
    rs = safe_float(row.get("rs_acceleration_score"))
    h1 = safe_float(row.get("h1_oversold_value_score"))
    theme = _theme_multiplier(row, regime_state)
    if regime_state == "bear":
        rs *= 1.3
        h1 *= 1.3
    score = (
        0.36 * safe_float(row.get("portfolio_future_winner_engine_score"))
        + 0.18 * safe_float(row.get("future_winner_scout_score"))
        + 0.14 * safe_float(row.get("multi_year_winner_score"))
        + 0.10 * rs
        + 0.08 * safe_float(row.get("oneil_leadership_score"))
        + 0.06 * safe_float(row.get("industry_group_strength_score"))
        + 0.05 * theme
        + 0.03 * h1
        - 0.12 * safe_float(row.get("stage2_overext_penalty"))
        - 0.08 * safe_float(row.get("overheat_penalty"))
    )
    if safe_float(row.get("price_above_ma200")) <= 0:
        score -= 0.50
    return score


def score_early(row: dict[str, Any], regime_state: str = "neutral") -> float:
    if regime_state in {"deep_bear", "bear"}:
        regime_penalty = 0.45
    else:
        regime_penalty = 0.0
    turn_flags = sum(
        1.0
        for key in (
            "profit_turn_positive_4q",
            "cashflow_turn_positive_4q",
            "ni_loss_narrowing_4q",
            "any_profit_sign_flip_pos",
        )
        if truthy(row.get(key)) or safe_float(row.get(key)) > 0
    )
    price_confirm = max(
        safe_float(row.get("price_above_ma50")),
        safe_float(row.get("breakout_fresh_20d")),
        safe_float(row.get("post_breakout_hold_score")),
    )
    score = (
        0.32 * safe_float(row.get("portfolio_early_scout_engine_score"))
        + 0.18 * safe_float(row.get("profitability_inflection_score"))
        + 0.12 * min(turn_flags, 2.0)
        + 0.12 * safe_float(row.get("rs_acceleration_score"))
        + 0.10 * price_confirm
        + 0.08 * safe_float(row.get("cashflow_inflection_under_loss_score"))
        + 0.08 * _theme_multiplier(row, regime_state)
        - 0.18 * (1.0 - safe_float(row.get("fundamental_reliability_score"), 0.5))
        - 0.12 * safe_float(row.get("risk_penalty"))
        - regime_penalty
    )
    if price_confirm <= 0:
        score -= 0.35
    return score


def candidate_passes(row: dict[str, Any], sleeve: str, regime_state: str) -> bool:
    if truthy(row.get("pattern_blocked")):
        return False
    if sleeve == "core":
        return safe_float(row.get("score")) > 0 and safe_float(row.get("fundamental_reliability_score"), 0.0) >= 0.45
    if sleeve == "future":
        return safe_float(row.get("price_above_ma200")) > 0 and safe_float(row.get("score")) > 0
    if sleeve == "early":
        if regime_state == "deep_bear":
            return False
        has_turn = any(
            truthy(row.get(key)) or safe_float(row.get(key)) > 0
            for key in (
                "profit_turn_positive_4q",
                "cashflow_turn_positive_4q",
                "ni_loss_narrowing_4q",
                "any_profit_sign_flip_pos",
            )
        )
        has_price = (
            safe_float(row.get("price_above_ma50")) > 0
            or safe_float(row.get("breakout_fresh_20d")) > 0
            or safe_float(row.get("post_breakout_hold_score")) >= 0.45
        )
        return has_turn and has_price and safe_float(row.get("fundamental_reliability_score"), 0.0) >= 0.35
    return False


def _score_row(row: dict[str, Any], sleeve: str, regime_state: str) -> float:
    if sleeve == "core":
        return score_core(row, regime_state)
    if sleeve == "future":
        return score_future(row, regime_state)
    if sleeve == "early":
        return score_early(row, regime_state)
    return 0.0


def select_sleeve_candidates(
    rows: list[dict[str, Any]],
    sleeve: str,
    regime_state: str,
    target_n: int,
) -> list[dict[str, Any]]:
    if target_n <= 0:
        return []
    scored: list[dict[str, Any]] = []
    for row in rows:
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker or ticker == "CASH":
            continue
        if not candidate_passes(row, sleeve, regime_state):
            continue
        item = dict(row)
        item["ticker"] = ticker
        item["main_v2_sleeve"] = sleeve
        item["main_v2_score"] = _score_row(row, sleeve, regime_state)
        if item["main_v2_score"] <= 0:
            continue
        scored.append(item)
    scored.sort(
        key=lambda r: (
            safe_float(r.get("main_v2_score")),
            safe_float(r.get("score")),
            safe_float(r.get("portfolio_sleeve_confidence")),
        ),
        reverse=True,
    )
    return scored[:target_n]


def _score_power_weights(selected: list[dict[str, Any]]) -> dict[str, float]:
    if not selected:
        return {}
    min_score = min(safe_float(row.get("main_v2_score")) for row in selected)
    raw: dict[str, float] = {}
    for row in selected:
        ticker = str(row.get("ticker")).upper()
        shifted = max(safe_float(row.get("main_v2_score")) - min_score + 0.25, 1e-6)
        raw[ticker] = shifted * shifted
    total = sum(raw.values())
    if total <= 0:
        equal = 1.0 / len(raw)
        return {ticker: equal for ticker in raw}
    return {ticker: value / total for ticker, value in raw.items()}


def _scale_sleeve(weights: dict[str, float], capacity: float) -> dict[str, float]:
    total = sum(float(v) for v in weights.values())
    if capacity <= 0 or total <= 0:
        return {}
    return {ticker: float(weight) / total * capacity for ticker, weight in weights.items()}


def _merge_sum_then_cap(
    sleeve_weights: dict[str, dict[str, float]],
    single_name_cap: float,
) -> tuple[dict[str, float], list[dict[str, Any]], list[dict[str, Any]]]:
    by_ticker: dict[str, dict[str, float]] = {}
    for sleeve, weights in sleeve_weights.items():
        for ticker, weight in weights.items():
            by_ticker.setdefault(ticker, {})[sleeve] = float(weight)
    merged: dict[str, float] = {}
    conflicts: list[dict[str, Any]] = []
    cap_violations: list[dict[str, Any]] = []
    for ticker, parts in sorted(by_ticker.items()):
        raw_weight = sum(parts.values())
        final_weight = min(raw_weight, single_name_cap)
        merged[ticker] = final_weight
        if len(parts) > 1:
            conflicts.append(
                {
                    "ticker": ticker,
                    "sleeves": sorted(parts),
                    "weights_per_sleeve": parts,
                    "raw_weight": raw_weight,
                    "final_weight": final_weight,
                    "multi_sleeve_conviction_bonus": raw_weight - max(parts.values()),
                }
            )
        if final_weight < raw_weight:
            cap_violations.append(
                {
                    "ticker": ticker,
                    "raw_weight": raw_weight,
                    "capped_weight": final_weight,
                    "excess_to_cash": raw_weight - final_weight,
                }
            )
    return dict(sorted(merged.items(), key=lambda item: item[1], reverse=True)), conflicts, cap_violations


def compose_main_sleeve_portfolio(
    candidate_rows: list[dict[str, Any]],
    regime_state: str | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or MAIN_V2_BALANCED_POLICY
    regime_state = str(regime_state or infer_regime(candidate_rows) or "neutral")
    capacity_map = dict((policy.get("sleeve_capacity_by_regime") or {}).get(regime_state) or {})
    if not capacity_map:
        capacity_map = dict(MAIN_V2_BALANCED_CAPACITY_BY_REGIME["neutral"])
    target_map = dict((policy.get("target_n_by_regime") or {}).get(regime_state) or {})
    if not target_map:
        target_map = dict(MAIN_V2_BALANCED_TARGET_N_BY_REGIME["neutral"])

    selected_by_sleeve: dict[str, list[dict[str, Any]]] = {}
    scaled_by_sleeve: dict[str, dict[str, float]] = {}
    for sleeve in ("core", "future", "early"):
        selected = select_sleeve_candidates(candidate_rows, sleeve, regime_state, int(target_map.get(sleeve, 0)))
        selected_by_sleeve[sleeve] = [
            {
                "ticker": row.get("ticker"),
                "name": row.get("Name"),
                "sector": row.get("sector"),
                "score": safe_float(row.get("main_v2_score")),
                "legacy_sleeve": row.get("portfolio_sleeve_label"),
                "engine_score": safe_float(row.get(f"portfolio_{SLEEVE_NAME_MAP[sleeve]}_engine_score")),
            }
            for row in selected
        ]
        raw_weights = _score_power_weights(selected)
        scaled_by_sleeve[sleeve] = _scale_sleeve(raw_weights, safe_float(capacity_map.get(sleeve), 0.0))

    weights, conflicts, cap_violations = _merge_sum_then_cap(
        scaled_by_sleeve,
        safe_float(policy.get("single_name_cap"), 0.15),
    )
    invested = sum(weights.values())
    cash_target = max(0.0, min(1.0, 1.0 - invested))
    expected_cash = safe_float(capacity_map.get("cash"), 0.0)
    result = MainV2Result(
        weights=weights,
        cash_target=cash_target,
        by_sleeve_capacity={
            "core": safe_float(capacity_map.get("core")),
            "future": safe_float(capacity_map.get("future")),
            "early": safe_float(capacity_map.get("early")),
            "cash": expected_cash,
        },
        selected_by_sleeve=selected_by_sleeve,
        conflicts=conflicts,
        cap_violations=cap_violations,
        regime_state=regime_state,
        audit={
            "policy_name": policy.get("name"),
            "research_only": True,
            "merge_mode": policy.get("merge_mode"),
            "single_name_cap": safe_float(policy.get("single_name_cap"), 0.15),
            "target_n_by_sleeve": target_map,
            "selected_n_by_sleeve": {k: len(v) for k, v in selected_by_sleeve.items()},
            "raw_scaled_sleeve_sums": {k: sum(v.values()) for k, v in scaled_by_sleeve.items()},
            "expected_invested_before_cap": sum(safe_float(capacity_map.get(k), 0.0) for k in ("core", "future", "early")),
            "actual_invested_after_cap": invested,
            "expected_cash": expected_cash,
            "cash_target": cash_target,
            "cap_excess_to_cash": sum(row["excess_to_cash"] for row in cap_violations),
            "n_positions": len(weights),
            "n_conflicts": len(conflicts),
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "production_activation_allowed": False,
        },
    )
    return result.to_dict()


def result_to_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    selected_lookup: dict[str, list[str]] = {}
    score_lookup: dict[str, float] = {}
    for sleeve, items in (result.get("selected_by_sleeve") or {}).items():
        for item in items:
            ticker = str(item.get("ticker")).upper()
            selected_lookup.setdefault(ticker, []).append(sleeve)
            score_lookup[ticker] = max(score_lookup.get(ticker, 0.0), safe_float(item.get("score")))
    for rank, (ticker, weight) in enumerate((result.get("main_v2_weights") or {}).items(), start=1):
        rows.append(
            {
                "rank": rank,
                "ticker": ticker,
                "target_weight": weight,
                "main_v2_sleeves": ",".join(sorted(selected_lookup.get(ticker, []))),
                "main_v2_score": score_lookup.get(ticker, 0.0),
                "regime_state": result.get("regime_state"),
                "row_type": "equity",
            }
        )
    rows.append(
        {
            "rank": len(rows) + 1,
            "ticker": "CASH",
            "target_weight": result.get("cash_target", 0.0),
            "main_v2_sleeves": "cash",
            "main_v2_score": 0.0,
            "regime_state": result.get("regime_state"),
            "row_type": "cash",
        }
    )
    return rows

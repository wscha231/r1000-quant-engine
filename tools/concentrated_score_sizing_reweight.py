"""Shared score-sizing reweight helper for Concentrated research arms.

The helper is deliberately policy-neutral: it never selects tickers, never
reads forward-return columns, and only redistributes the stock weights already
present in one rebalance-date slice.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

CASH_TICKERS = {"CASH", "__CASH__"}
DEFAULT_SIGNAL = "alphaops_vnext_score"
DEFAULT_BLEND = 0.75
DEFAULT_RANK_POWER = 1.5
DEFAULT_CAP_MODE = "telemetry_only"
DEFAULT_SINGLE_CAP = 0.30
CAP_MODES = {"telemetry_only", "cap30_waterfill", "cap30_clip_to_cash"}
TOL = 1e-10


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if pd.isna(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def clean_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def _hhi(weights: list[float]) -> float:
    return float(sum(max(0.0, weight) ** 2 for weight in weights))


def _rank_allocation(scores: pd.Series, gross: float, rank_power: float) -> tuple[list[float], list[float]]:
    ranks = scores.rank(method="average", pct=True).fillna(0.0).clip(lower=0.0)
    raw = ranks.pow(float(rank_power))
    denom = float(raw.sum())
    if denom <= TOL:
        return [], []
    allocation = (raw / denom * gross).astype(float)
    return [float(value) for value in allocation.tolist()], [float(value) for value in raw.tolist()]


def _waterfill(
    desired: list[float],
    preferences: list[float],
    *,
    gross: float,
    single_cap: float,
) -> tuple[list[float], float, str]:
    if not desired:
        return [], 0.0, "no_records"
    cap = max(0.0, float(single_cap))
    total_capacity = cap * len(desired)
    if gross > total_capacity + TOL:
        return [cap for _ in desired], float(gross - total_capacity), "cap_infeasible_cash_residual"

    weights = [min(max(0.0, value), cap) for value in desired]
    excess = float(gross - sum(weights))
    loops = 0
    while excess > TOL and loops < 100:
        loops += 1
        candidates = [i for i, weight in enumerate(weights) if weight < cap - TOL]
        if not candidates:
            break
        pref_sum = sum(max(0.0, preferences[i]) for i in candidates)
        if pref_sum <= TOL:
            pref_sum = sum(max(0.0, cap - weights[i]) for i in candidates)
            shares = {i: max(0.0, cap - weights[i]) / pref_sum for i in candidates} if pref_sum > TOL else {}
        else:
            shares = {i: max(0.0, preferences[i]) / pref_sum for i in candidates}
        allocated = 0.0
        for i in candidates:
            room = max(0.0, cap - weights[i])
            add = min(room, excess * shares.get(i, 0.0))
            weights[i] += add
            allocated += add
        if allocated <= TOL:
            break
        excess = float(gross - sum(weights))

    residual = max(0.0, float(gross - sum(weights)))
    status = "gross_preserved" if residual <= 1e-8 else "cap_infeasible_cash_residual"
    return weights, residual, status


def reweight_concentrated_records(
    records: list[dict[str, Any]],
    *,
    signal: str = DEFAULT_SIGNAL,
    blend: float = DEFAULT_BLEND,
    rank_power: float = DEFAULT_RANK_POWER,
    cap_mode: str = DEFAULT_CAP_MODE,
    single_cap: float = DEFAULT_SINGLE_CAP,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Reweight one Concentrated stock slice and return rows plus telemetry."""
    mode = str(cap_mode or DEFAULT_CAP_MODE)
    if mode not in CAP_MODES:
        raise ValueError(f"unsupported cap_mode: {mode}")
    stock_records = [dict(row) for row in records if clean_ticker(row.get("ticker")) not in CASH_TICKERS]
    if not stock_records:
        return list(records), {
            "status": "no_stock_records",
            "gross_preservation_status": "no_stock_records",
            "cash_residual_weight": 0.0,
        }

    base_weights = [
        max(0.0, safe_float(row.get("target_weight"), safe_float(row.get("weight"))))
        for row in stock_records
    ]
    gross = float(sum(base_weights))
    scores = pd.Series([safe_float(row.get(signal), float("nan")) for row in stock_records], dtype=float)
    if gross <= TOL:
        return stock_records, {
            "status": "no_stock_gross",
            "gross_preservation_status": "no_stock_gross",
            "cash_residual_weight": 0.0,
        }
    if scores.notna().sum() < 2 or scores.nunique(dropna=True) < 2:
        return stock_records, {
            "status": "no_signal_variation",
            "gross_preservation_status": "no_signal_variation",
            "cash_residual_weight": 0.0,
            "stock_gross_before": gross,
            "stock_gross_after": gross,
        }

    rank_alloc, preferences = _rank_allocation(scores, gross, rank_power)
    if not rank_alloc:
        return stock_records, {
            "status": "no_signal_variation",
            "gross_preservation_status": "no_signal_variation",
            "cash_residual_weight": 0.0,
            "stock_gross_before": gross,
            "stock_gross_after": gross,
        }

    target = [
        max(0.0, (1.0 - float(blend)) * before + float(blend) * alloc)
        for before, alloc in zip(base_weights, rank_alloc)
    ]
    cash_residual = 0.0
    gross_status = "gross_preserved"
    if mode == "cap30_waterfill":
        target, cash_residual, gross_status = _waterfill(
            target,
            preferences,
            gross=gross,
            single_cap=single_cap,
        )
    elif mode == "cap30_clip_to_cash":
        target = [min(value, float(single_cap)) for value in target]
        cash_residual = max(0.0, float(gross - sum(target)))
        gross_status = "gross_preserved" if cash_residual <= 1e-8 else "cap_infeasible_cash_residual"

    out: list[dict[str, Any]] = []
    cap_breach_excess = 0.0
    total_abs_delta = 0.0
    for row, before, after in zip(stock_records, base_weights, target):
        item = dict(row)
        after = max(0.0, float(after))
        delta = after - float(before)
        cap_excess = max(0.0, after - float(single_cap))
        cap_breach_excess += cap_excess
        total_abs_delta += abs(delta)
        item["pre_concentrated_score_sizing_reweight_weight"] = float(before)
        item["weight"] = after
        item["target_weight"] = after
        item["concentrated_score_sizing_reweight_weight"] = after
        item["concentrated_score_sizing_reweight_status"] = "applied"
        item["concentrated_score_sizing_reweight_signal"] = signal
        item["concentrated_score_sizing_reweight_blend"] = float(blend)
        item["concentrated_score_sizing_reweight_rank_power"] = float(rank_power)
        item["concentrated_score_sizing_reweight_cap_mode"] = mode
        item["concentrated_score_sizing_reweight_cap"] = float(single_cap)
        item["concentrated_score_sizing_reweight_delta"] = delta
        item["concentrated_score_sizing_reweight_cap_exceeded"] = bool(cap_excess > TOL)
        out.append(item)

    after_weights = [safe_float(row.get("weight")) for row in out]
    telemetry = {
        "status": "applied",
        "signal": signal,
        "blend": float(blend),
        "rank_power": float(rank_power),
        "cap_mode": mode,
        "single_cap": float(single_cap),
        "stock_gross_before": gross,
        "stock_gross_after": float(sum(after_weights)),
        "max_weight_before": float(max(base_weights)) if base_weights else 0.0,
        "max_weight_after": float(max(after_weights)) if after_weights else 0.0,
        "hhi_before": _hhi(base_weights),
        "hhi_after": _hhi(after_weights),
        "total_abs_weight_delta": float(total_abs_delta),
        "cap_breach_count": int(sum(1 for weight in after_weights if weight > float(single_cap) + TOL)),
        "cap_breach_excess_weight": float(cap_breach_excess),
        "gross_preservation_status": gross_status,
        "cash_residual_weight": float(cash_residual),
    }
    return out, telemetry

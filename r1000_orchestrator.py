"""r1000_orchestrator - Phase 19a portfolio orchestrator scaffolding.

Pure-transform module. Takes per-mandate weight maps plus regime_state and
produces a unified target portfolio weight dict. This is inspection-only for
now; the production backtest still uses the existing portfolio construction.

Usage
-----
    from r1000_orchestrator import compose_unified_portfolio
    out = compose_unified_portfolio(main_weights={"AAPL": 0.08}, regime_state="bull")
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Mandate registry lookup
try:
    from r1000_config import MANDATE_REGISTRY, mandate_capacity_for_regime
except ImportError:
    MANDATE_REGISTRY = {}
    def mandate_capacity_for_regime(mandate: str, regime_state: str) -> float:  # type: ignore
        return 0.0


@dataclass
class OrchestratorResult:
    """Structured return type for compose_unified_portfolio."""
    unified_weights: dict
    cash_target: float
    by_mandate_capacity: dict
    conflicts: list
    regime_state: str
    audit: dict

    def to_dict(self) -> dict:
        return {
            "unified_weights": self.unified_weights,
            "cash_target": self.cash_target,
            "by_mandate_capacity": self.by_mandate_capacity,
            "conflicts": self.conflicts,
            "regime_state": self.regime_state,
            "audit": self.audit,
        }


def _normalize_weights(weights: Optional[dict]) -> dict:
    """Coerce weights dict to {str ticker -> float} with NaN/None -> 0.
    Preserves zero-weight entries so callers see the full universe."""
    if not weights:
        return {}
    out: dict[str, float] = {}
    for k, v in weights.items():
        if k is None or str(k).strip() == "":
            continue
        try:
            fv = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            fv = 0.0
        out[str(k).upper()] = fv
    return out


def _scale_by_mandate_capacity(
    weights: dict,
    mandate: str,
    regime_state: str,
) -> tuple[dict, float]:
    """Multiply each weight by the mandate's capacity for this regime.

    Input weights typically sum to 1.0 within the mandate; output sums
    to mandate_capacity_for_regime(mandate, regime_state).

    Returns (scaled_weights, capacity_used).
    """
    cap = float(mandate_capacity_for_regime(mandate, regime_state))
    if cap <= 0 or not weights:
        return {}, cap
    raw_sum = sum(float(v) for v in weights.values())
    if raw_sum <= 0:
        return {}, cap
    # Normalize then scale to mandate capacity
    scale = cap / raw_sum
    return {k: float(v) * scale for k, v in weights.items()}, cap


def _merge_with_max(
    main_w: dict,
    conc_w: dict,
    tact_w: dict,
) -> tuple[dict, list]:
    """Merge three weight dicts; keep MAX weight per ticker. Tickers
    appearing in 2+ dicts are reported as conflicts.

    Returns (merged_dict, conflicts_list).
    """
    all_tickers = set(main_w) | set(conc_w) | set(tact_w)
    merged: dict[str, float] = {}
    conflicts: list[dict] = []
    for t in sorted(all_tickers):
        candidates = []
        for src, d in (("main", main_w), ("concentrated", conc_w), ("tactical", tact_w)):
            if t in d:
                candidates.append((src, float(d[t])))
        if not candidates:
            continue
        # Pick max
        candidates.sort(key=lambda x: x[1], reverse=True)
        merged[t] = candidates[0][1]
        if len(candidates) > 1:
            conflicts.append({
                "ticker": t,
                "mandates": [src for src, _ in candidates],
                "weights_per_mandate": {src: w for src, w in candidates},
                "max_weight_used": candidates[0][1],
                "winning_mandate": candidates[0][0],
            })
    return merged, conflicts


def compose_unified_portfolio(
    main_weights: Optional[dict] = None,
    concentrated_weights: Optional[dict] = None,
    tactical_weights: Optional[dict] = None,
    regime_state: str = "neutral",
    cfg=None,
) -> dict:
    """Compose a unified target weight map from 3 per-mandate weight dicts.

    Algorithm
    ---------
    1. Normalize each input dict (str ticker -> float; drop NaN/None).
    2. For each mandate, scale weights so they sum to
       mandate_capacity_for_regime(mandate, regime_state).
       (e.g. if main has 5 names equal-weighted at 0.20 each = 1.0 sum,
       and main capacity in 'bull' is 0.75, output sums to 0.75.)
    3. Merge the 3 scaled dicts via _merge_with_max -- conflicts (same
       ticker in 2+ mandates) keep the highest scaled weight.
    4. cash_target = 1.0 - sum(merged) (clamped to [0, 1]).

    Returns a dict matching OrchestratorResult.to_dict() schema.
    """
    main_w = _normalize_weights(main_weights)
    conc_w = _normalize_weights(concentrated_weights)
    tact_w = _normalize_weights(tactical_weights)

    raw_sums = {
        "main": sum(main_w.values()),
        "concentrated": sum(conc_w.values()),
        "tactical": sum(tact_w.values()),
    }

    main_scaled, main_cap = _scale_by_mandate_capacity(main_w, "main", regime_state)
    conc_scaled, conc_cap = _scale_by_mandate_capacity(conc_w, "concentrated", regime_state)
    tact_scaled, tact_cap = _scale_by_mandate_capacity(tact_w, "tactical", regime_state)

    scaled_sums = {
        "main": sum(main_scaled.values()),
        "concentrated": sum(conc_scaled.values()),
        "tactical": sum(tact_scaled.values()),
    }

    merged, conflicts = _merge_with_max(main_scaled, conc_scaled, tact_scaled)
    invested = sum(merged.values())
    cash_target = max(0.0, min(1.0, 1.0 - invested))

    expected_total = main_cap + conc_cap + tact_cap

    result = OrchestratorResult(
        unified_weights=dict(sorted(merged.items(), key=lambda kv: -kv[1])),
        cash_target=float(cash_target),
        by_mandate_capacity={
            "main": float(main_cap),
            "concentrated": float(conc_cap),
            "tactical": float(tact_cap),
        },
        conflicts=conflicts,
        regime_state=str(regime_state),
        audit={
            "input_weights_sum": raw_sums,
            "scaled_weights_sum": scaled_sums,
            "policy_capacity": {
                "main": float(main_cap),
                "concentrated": float(conc_cap),
                "tactical": float(tact_cap),
                "expected_total_invested": float(expected_total),
                "actual_total_invested_after_merge": float(invested),
                "merged_below_expected_due_to_conflicts": float(max(0.0, expected_total - invested)),
            },
            "n_unique_tickers": len(merged),
            "n_conflicts": len(conflicts),
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    return result.to_dict()


def audit_unified_portfolio(
    result: dict,
    tolerance: float = 1e-6,
) -> dict:
    """Validate that a compose_unified_portfolio output is internally
    consistent. Returns a dict of {check_name: bool/value}; useful for
    smoke tests and the orchestrator CLI.
    """
    weights = result.get("unified_weights", {})
    cash = float(result.get("cash_target", 0.0))
    invested = sum(float(v) for v in weights.values())

    checks: dict = {
        "weights_nonnegative": all(float(w) >= 0 for w in weights.values()),
        "weights_at_most_one": all(float(w) <= 1.0 + tolerance for w in weights.values()),
        "cash_in_unit_range": 0.0 <= cash <= 1.0 + tolerance,
        "invested_plus_cash_close_to_one": abs(invested + cash - 1.0) <= tolerance,
        "invested_amount": float(invested),
        "cash_amount": float(cash),
        "n_positions": len(weights),
        "n_conflicts": len(result.get("conflicts", []) or []),
    }
    checks["all_passed"] = all(
        v is True for v in (
            checks["weights_nonnegative"],
            checks["weights_at_most_one"],
            checks["cash_in_unit_range"],
            checks["invested_plus_cash_close_to_one"],
        )
    )
    return checks


def write_orchestrator_output(
    result: dict,
    out_dir: Path,
    asof_date: Optional[str] = None,
) -> Path:
    """Persist orchestrator result + audit to JSON. Filename includes date."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if asof_date is None:
        asof_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    audit = audit_unified_portfolio(result)
    payload = dict(result)
    payload["audit_checks"] = audit
    daily_path = out_dir / f"unified_target_{asof_date}.json"
    daily_path.write_text(json.dumps(payload, indent=2, default=str))
    (out_dir / "latest.json").write_text(json.dumps(payload, indent=2, default=str))
    return daily_path


def orchestrator_result_to_frame(result: dict) -> list[dict]:
    """Convert an orchestrator result to stable CSV rows.

    Includes a CASH row so the file reconciles to 100% exposure for operator
    review. This is still report-only; no order routing consumes it.
    """
    rows: list[dict] = []
    weights = result.get("unified_weights", {}) or {}
    regime_state = str(result.get("regime_state", "neutral"))
    for rank, (ticker, weight) in enumerate(
        sorted(weights.items(), key=lambda kv: float(kv[1]), reverse=True),
        start=1,
    ):
        rows.append({
            "rank": rank,
            "ticker": str(ticker),
            "target_weight": float(weight),
            "regime_state": regime_state,
            "row_type": "equity",
        })
    rows.append({
        "rank": len(rows) + 1,
        "ticker": "CASH",
        "target_weight": float(result.get("cash_target", 0.0) or 0.0),
        "regime_state": regime_state,
        "row_type": "cash",
    })
    return rows


def write_orchestrator_output_bundle(
    result: dict,
    out_dir: Path,
    asof_date: Optional[str] = None,
    prefix: str = "unified_target",
) -> dict[str, str]:
    """Persist orchestrator JSON, audit JSON, and CSV shadow target."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if asof_date is None:
        asof_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    audit = audit_unified_portfolio(result)
    payload = dict(result)
    payload["audit_checks"] = audit

    daily_json = out_dir / f"{prefix}_{asof_date}.json"
    latest_json = out_dir / f"{prefix}_latest.json"
    audit_json = out_dir / f"{prefix}_audit_latest.json"
    daily_csv = out_dir / f"{prefix}_{asof_date}.csv"
    latest_csv = out_dir / f"{prefix}_latest.csv"

    daily_json.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    latest_json.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    audit_json.write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")

    try:
        import pandas as pd

        frame = pd.DataFrame(orchestrator_result_to_frame(payload))
        frame.to_csv(daily_csv, index=False)
        frame.to_csv(latest_csv, index=False)
    except Exception:
        # JSON outputs are enough for smoke/reporting if pandas is unavailable.
        daily_csv.write_text("", encoding="utf-8")
        latest_csv.write_text("", encoding="utf-8")

    return {
        "json": str(daily_json),
        "latest_json": str(latest_json),
        "audit_json": str(audit_json),
        "csv": str(daily_csv),
        "latest_csv": str(latest_csv),
    }

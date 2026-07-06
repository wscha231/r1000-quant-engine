#!/usr/bin/env python3
"""Shared AlphaOps governance helpers.

This module keeps the research-vs-production labels, frozen dispatch payload,
and trading-calendar freshness math in one place so readiness gates and
fullrun artifacts do not drift apart.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
FROZEN_POLICY_PAYLOAD_MANIFEST = REPO_ROOT / "docs" / "CODEX_POLICY_PATH_COMBO_CANDIDATE_20260704.payload.json"
FROZEN_POLICY_SOURCE_DOC = "docs/CODEX_POLICY_PATH_COMBO_CANDIDATE_20260704.md"
PRODUCTION_BLOCKER_PIT_FALSE = "pit_universe_label_clean_false_until_membership_audit_passes"
PRODUCTION_BLOCKER_PIT_SHORT = "pit_universe_label_clean_false"

_FROZEN_POLICY_PAYLOAD_FALLBACK: dict[str, str] = {
    "PHASE_MAIN_POST_SELECTION_TOPN_FILTER_ENABLED": "1",
    "R1000_MAIN_POST_SELECTION_TOP_N": "14",
    "PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED": "1",
    "R1000_MAIN_AI_CAPEX_TILT_STRENGTH": "0.20",
    "PHASE_CONCENTRATED_REPLACEMENT_QUALITY_ENABLED": "1",
    "PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED": "1",
    "R1000_CONC_CASHFUNDED_EARLY_ENTRY_ADD_WEIGHT": "0.058",
    "R1000_CONC_CASHFUNDED_EARLY_ENTRY_MIN_BREAKOUT_QUALITY": "0.50",
}


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps({str(k): str(v) for k, v in payload.items()}, sort_keys=True, separators=(",", ":"))


def payload_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def load_frozen_policy_payload_manifest() -> dict[str, Any]:
    if not FROZEN_POLICY_PAYLOAD_MANIFEST.exists():
        return {
            "schema_version": "alphaops-frozen-policy-payload-v1",
            "policy_id": "clean_control_policy_path_combo_20260704",
            "source_doc": FROZEN_POLICY_SOURCE_DOC,
            "payload": _FROZEN_POLICY_PAYLOAD_FALLBACK,
            "_manifest_missing": True,
        }
    try:
        raw = json.loads(FROZEN_POLICY_PAYLOAD_MANIFEST.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "schema_version": "alphaops-frozen-policy-payload-v1",
            "policy_id": "clean_control_policy_path_combo_20260704",
            "source_doc": FROZEN_POLICY_SOURCE_DOC,
            "payload": _FROZEN_POLICY_PAYLOAD_FALLBACK,
            "_manifest_invalid_json": str(exc),
        }
    payload = raw.get("payload") if isinstance(raw, dict) else None
    if not isinstance(payload, dict):
        raw = dict(raw) if isinstance(raw, dict) else {}
        raw["payload"] = _FROZEN_POLICY_PAYLOAD_FALLBACK
        raw["_manifest_invalid_payload"] = True
    return raw


def frozen_policy_payload() -> dict[str, str]:
    raw = load_frozen_policy_payload_manifest().get("payload") or {}
    return {str(k): str(v) for k, v in raw.items()}


FROZEN_POLICY_PAYLOAD = frozen_policy_payload()
FROZEN_POLICY_PAYLOAD_HASH = payload_sha256(FROZEN_POLICY_PAYLOAD)


def payload_diff(actual: dict[str, Any], expected: dict[str, Any] | None = None) -> dict[str, Any]:
    expected = expected or FROZEN_POLICY_PAYLOAD
    actual_s = {str(k): str(v) for k, v in actual.items()}
    expected_s = {str(k): str(v) for k, v in expected.items()}
    missing = sorted(k for k in expected_s if k not in actual_s)
    extra = sorted(k for k in actual_s if k not in expected_s)
    changed = {
        k: {"expected": expected_s[k], "actual": actual_s[k]}
        for k in sorted(expected_s)
        if k in actual_s and actual_s[k] != expected_s[k]
    }
    return {"missing": missing, "extra": extra, "changed": changed}


def frozen_payload_binding_fields(actual: dict[str, Any]) -> dict[str, Any]:
    actual_s = {str(k): str(v) for k, v in actual.items()}
    actual_hash = payload_sha256(actual_s)
    matches = actual_hash == FROZEN_POLICY_PAYLOAD_HASH
    return {
        "frozen_policy_id": "clean_control_policy_path_combo_20260704",
        "frozen_policy_payload_source_doc": FROZEN_POLICY_SOURCE_DOC,
        "frozen_policy_payload_manifest": str(FROZEN_POLICY_PAYLOAD_MANIFEST.relative_to(REPO_ROOT)),
        "frozen_policy_payload_hash": FROZEN_POLICY_PAYLOAD_HASH,
        "dispatch_payload_hash": actual_hash,
        "frozen_payload_match": matches,
        "frozen_payload_expected_key_count": len(FROZEN_POLICY_PAYLOAD),
        "dispatch_payload_key_count": len(actual_s),
        "frozen_payload_diff": payload_diff(actual_s),
    }


def research_production_gate_fields(
    *,
    pit_universe_label_clean: bool = False,
    research_evidence_valid: bool = True,
    research_fullrun_preconditions_ready: bool | None = None,
) -> dict[str, Any]:
    pit_clean = bool(pit_universe_label_clean)
    production_blockers = [] if pit_clean else [PRODUCTION_BLOCKER_PIT_SHORT]
    out: dict[str, Any] = {
        "research_only": True,
        "research_evidence_valid": bool(research_evidence_valid),
        "production_evidence_valid": False,
        "research_fullrun_allowed_despite_pit_false": not pit_clean,
        "production_promotion_blocked_by_pit_false": not pit_clean,
        "production_promotion_allowed": False,
        "production_blocker": PRODUCTION_BLOCKER_PIT_FALSE if not pit_clean else "",
        "production_blockers": production_blockers,
        "public_display_allowed": False,
        "live_trading_enabled": False,
        "forbidden_labels": [
            "production_ready",
            "live_trading_ready",
            "public_return_claim",
            "official_service_performance",
        ],
        "allowed_research_labels": [
            "research_7y_fullrun_pass",
            "production_blocked_research_pass",
            "ready_for_human_review",
        ],
        "result_label": "production_blocked_research_pass" if research_evidence_valid else "ready_for_human_review",
    }
    if research_fullrun_preconditions_ready is not None:
        out["research_fullrun_preconditions_ready"] = bool(research_fullrun_preconditions_ready)
    return out


def _safe_read_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "missing_or_invalid", "reason": str(exc)}
    return raw if isinstance(raw, dict) else {"status": "missing_or_invalid", "reason": "json_root_not_object"}


def _repo_display_path(path: str | Path) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    try:
        return str(p.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(p)


def measurement_contract_caveat_fields(
    *,
    parity_summary_path: str | Path,
    survivorship_summary_path: str | Path,
) -> dict[str, Any]:
    """Return required run287 measurement caveats from R1/R2 summaries."""
    parity = _safe_read_json(parity_summary_path)
    survivorship = _safe_read_json(survivorship_summary_path)
    estimate = survivorship.get("survivorship_inflation_estimate")
    if not isinstance(estimate, dict):
        estimate = {
            "cagr_pp_lower_bound": survivorship.get("survivorship_inflation_estimate_cagr_pp"),
            "label": survivorship.get("label", "missing"),
            "method": survivorship.get("method", "missing"),
            "unmeasured_component": survivorship.get("unmeasured_component", "missing"),
        }
    return {
        "runner_parity_status": parity.get("runner_parity_status", "missing"),
        "runner_parity_reason": parity.get("runner_parity_reason", ""),
        "runner_parity_summary_path": _repo_display_path(parity_summary_path),
        "survivorship_inflation_estimate": estimate,
        "survivorship_inflation_estimate_cagr_pp": survivorship.get(
            "survivorship_inflation_estimate_cagr_pp", estimate.get("cagr_pp_lower_bound")
        ),
        "survivorship_inflation_label": survivorship.get("label", estimate.get("label", "missing")),
        "survivorship_unmeasured_component": survivorship.get(
            "unmeasured_component", estimate.get("unmeasured_component", "missing")
        ),
        "survivorship_summary_path": _repo_display_path(survivorship_summary_path),
    }


def measurement_contract_acceptance_blockers(caveats: dict[str, Any]) -> list[str]:
    """Return blockers that prevent acceptance-style labels for run287 metrics."""
    blockers: list[str] = []
    parity_status = str(caveats.get("runner_parity_status") or "missing")
    if parity_status == "missing":
        blockers.append("runner_parity_status_missing")
    elif parity_status != "parity_exact":
        blockers.append("runner_parity_not_exact")

    survival_label = str(caveats.get("survivorship_inflation_label") or "missing")
    survival_component = str(caveats.get("survivorship_unmeasured_component") or "missing")
    estimate = caveats.get("survivorship_inflation_estimate")
    if survival_label == "missing":
        blockers.append("survivorship_inflation_label_missing")
    if survival_component == "missing":
        blockers.append("survivorship_unmeasured_component_missing")
    if not isinstance(estimate, dict):
        blockers.append("survivorship_inflation_estimate_missing")
    if caveats.get("survivorship_inflation_estimate_cagr_pp") is None:
        blockers.append("survivorship_inflation_estimate_cagr_pp_missing")
    return blockers


def _normalize_date(value: Any) -> Any | None:
    import pandas as pd

    out = pd.to_datetime(value, errors="coerce")
    if pd.isna(out):
        return None
    return pd.Timestamp(out).normalize()


def _fallback_xnys_trading_days(start: Any, end: Any) -> list[Any]:
    import pandas as pd
    from pandas.tseries.holiday import (
        AbstractHolidayCalendar,
        GoodFriday,
        Holiday,
        USLaborDay,
        USMartinLutherKingJr,
        USMemorialDay,
        USPresidentsDay,
        USThanksgivingDay,
        nearest_workday,
    )
    from pandas.tseries.offsets import CustomBusinessDay

    class XNYSFallbackHolidayCalendar(AbstractHolidayCalendar):
        rules = [
            Holiday("New Years Day", month=1, day=1, observance=nearest_workday),
            USMartinLutherKingJr,
            USPresidentsDay,
            GoodFriday,
            USMemorialDay,
            Holiday("Juneteenth", month=6, day=19, observance=nearest_workday, start_date="2022-06-19"),
            Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
            USLaborDay,
            USThanksgivingDay,
            Holiday("Christmas", month=12, day=25, observance=nearest_workday),
        ]

    freq = CustomBusinessDay(calendar=XNYSFallbackHolidayCalendar())
    days = pd.date_range(start + pd.Timedelta(days=1), end, freq=freq)
    return [pd.Timestamp(day).normalize() for day in days]


def xnys_trading_days_between(start_exclusive: Any, end_inclusive: Any) -> tuple[list[Any], str]:
    """Return XNYS trading days in (start_exclusive, end_inclusive]."""
    import pandas as pd

    start = _normalize_date(start_exclusive)
    end = _normalize_date(end_inclusive)
    if start is None or end is None or start >= end:
        return [], "none"
    try:
        import pandas_market_calendars as mcal  # type: ignore

        calendar = mcal.get_calendar("XNYS")
        schedule = calendar.schedule(start_date=start.date().isoformat(), end_date=end.date().isoformat())
        days = [pd.Timestamp(idx).normalize() for idx in schedule.index]
        return [day for day in days if start < day <= end], "pandas_market_calendars_xnys"
    except Exception:
        return _fallback_xnys_trading_days(start, end), "pandas_fallback_xnys_holidays"


def xnys_trading_day_count_between(start_exclusive: Any, end_inclusive: Any) -> tuple[int, str]:
    days, source = xnys_trading_days_between(start_exclusive, end_inclusive)
    return int(len(days)), source

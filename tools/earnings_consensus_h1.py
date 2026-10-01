#!/usr/bin/env python3
"""H1 data-integrity helpers for forward earnings/consensus evidence.

Pure functions only. No vendor calls, ranking, target-book, or trading authority.
The module intentionally separates recommendation sentiment from estimate revisions,
preserves nullable numerics, and compares revisions only within the same fiscal period.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Any, Iterable

SCHEMA_VERSION = "earnings-consensus-h1-v1"


def optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def optional_int(value: Any) -> int | None:
    out = optional_float(value)
    return None if out is None else int(out)


def pct_change(current: Any, previous: Any) -> float | None:
    c, p = optional_float(current), optional_float(previous)
    if c is None or p is None or p == 0:
        return None
    return (c - p) / abs(p)


def iso_utc(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            try:
                dt = datetime.fromisoformat(text + "T00:00:00+00:00")
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def period_value(row: dict[str, Any]) -> str | None:
    for key in ("period", "date", "fiscalDateEnding", "fiscal_period_end"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)[:10]
    return None


def estimate_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        data = payload.get("data", payload.get("estimate", []))
    else:
        data = payload
    rows = [dict(x) for x in data if isinstance(x, dict)] if isinstance(data, list) else []
    rows.sort(key=lambda x: period_value(x) or "")
    return rows


def first_two(payload: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = estimate_rows(payload)
    if not rows:
        return {}, {}
    if len(rows) == 1:
        return rows[0], {}
    return rows[0], rows[1]


def recommendation_metrics(payload: Any) -> dict[str, Any]:
    rows = [dict(x) for x in payload if isinstance(x, dict)] if isinstance(payload, list) else []
    rows.sort(key=lambda x: str(x.get("period") or ""))
    row = rows[-1] if rows else {}
    strong_buy = optional_int(row.get("strongBuy")) or 0
    buy = optional_int(row.get("buy")) or 0
    hold = optional_int(row.get("hold")) or 0
    sell = optional_int(row.get("sell")) or 0
    strong_sell = optional_int(row.get("strongSell")) or 0
    bull, bear = strong_buy + buy, sell + strong_sell
    denom = bull + bear
    return {
        "recommendation_period": str(row.get("period") or "") or None,
        "recommendation_bull_count": bull,
        "recommendation_hold_count": hold,
        "recommendation_bear_count": bear,
        "recommendation_balance": ((bull - bear) / denom) if denom else None,
        "est_eps_revision_breadth": None,
        "est_eps_revision_breadth_status": "UNAVAILABLE_FROM_RECOMMENDATION_PAYLOAD",
    }


def _estimate_fields(row: dict[str, Any], prefix: str) -> dict[str, Any]:
    avg = optional_float(row.get("avg"))
    high = optional_float(row.get("high"))
    low = optional_float(row.get("low"))
    analysts = optional_int(row.get("numberAnalysts"))
    dispersion = None
    if high is not None and low is not None and low != 0:
        dispersion = (high - low) / abs(low)
    return {
        f"{prefix}_period_end": period_value(row),
        f"{prefix}_avg": avg,
        f"{prefix}_high": high,
        f"{prefix}_low": low,
        f"{prefix}_analyst_count": analysts,
        f"{prefix}_dispersion": dispersion,
    }


def build_snapshot(
    ticker: str,
    *,
    eps_payload: Any,
    revenue_payload: Any,
    recommendation_payload: Any,
    observed_at: Any,
    collected_at: Any,
    first_seen_at: Any | None = None,
    provider_published_at: Any | None = None,
    fetch_source: str = "",
    eps_estimate_access: bool = True,
    revenue_estimate_access: bool = True,
) -> dict[str, Any]:
    eps1, eps2 = first_two(eps_payload)
    rev1, rev2 = first_two(revenue_payload)
    observed = iso_utc(observed_at)
    collected = iso_utc(collected_at)
    published = iso_utc(provider_published_at)
    first_seen = iso_utc(first_seen_at) or observed
    candidates = [x for x in (published, first_seen, observed) if x]
    available = max(candidates) if candidates else collected
    eps_fields = _estimate_fields(eps1, "eps_fy1") | _estimate_fields(eps2, "eps_fy2")
    rev_fields = _estimate_fields(rev1, "rev_fy1") | _estimate_fields(rev2, "rev_fy2")
    rec = recommendation_metrics(recommendation_payload)
    has_forward = bool(eps_fields["eps_fy1_avg"] is not None or rev_fields["rev_fy1_avg"] is not None)
    row = {
        "schema_version": SCHEMA_VERSION,
        "ticker": str(ticker).upper().strip(),
        "fetch_source": fetch_source,
        "observed_at": observed,
        "first_seen_at": first_seen,
        "provider_published_at": published,
        "available_at": available,
        "collected_at": collected,
        "timestamp_precision": "INTRADAY" if any("T" in str(x or "") for x in (observed_at, provider_published_at)) else "DATE_ONLY",
        "eps_estimate_access": bool(eps_estimate_access),
        "revenue_estimate_access": bool(revenue_estimate_access),
        "vendor_estimate_access": bool(eps_estimate_access or revenue_estimate_access),
        "has_forward_estimate": int(has_forward),
        **eps_fields,
        **rev_fields,
        **rec,
    }
    row["data_quality_status"] = "OK" if has_forward else "NO_USABLE_FORWARD_ESTIMATE"
    return row


def same_period_revision(current: dict[str, Any], prior: dict[str, Any], prefix: str) -> float | None:
    pkey = f"{prefix}_period_end"
    vkey = f"{prefix}_avg"
    if not current.get(pkey) or current.get(pkey) != prior.get(pkey):
        return None
    return pct_change(current.get(vkey), prior.get(vkey))


def revision_features(current: dict[str, Any], prior: dict[str, Any] | None) -> dict[str, Any]:
    if not prior:
        return {"eps_revision_same_period": None, "revenue_revision_same_period": None, "revision_status": "NO_PRIOR_SAME_PERIOD_SNAPSHOT"}
    eps = same_period_revision(current, prior, "eps_fy1")
    rev = same_period_revision(current, prior, "rev_fy1")
    status = "OK" if eps is not None or rev is not None else "FISCAL_PERIOD_ROLLOVER_OR_MISSING"
    return {"eps_revision_same_period": eps, "revenue_revision_same_period": rev, "revision_status": status}


def frozen_pre_event_consensus(snapshots: Iterable[dict[str, Any]], *, event_available_at: Any, fiscal_period_end: str) -> dict[str, Any] | None:
    cutoff = iso_utc(event_available_at)
    if not cutoff:
        return None
    eligible = []
    for row in snapshots:
        avail = iso_utc(row.get("available_at"))
        if not avail or avail > cutoff:
            continue
        periods = {row.get("eps_fy1_period_end"), row.get("eps_fy2_period_end")}
        if fiscal_period_end not in periods:
            continue
        eligible.append(row)
    if not eligible:
        return None
    return max(eligible, key=lambda x: iso_utc(x.get("available_at")) or "")


def causal_event_id(ticker: str, fiscal_period_end: str, event_available_at: Any) -> str:
    raw = f"{str(ticker).upper()}|{fiscal_period_end}|{iso_utc(event_available_at) or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def classify_attempt_state(*, has_success: bool, success_age_days: int | None, selection_count: int, last_error_class: str | None, stale_after_days: int = 7) -> str:
    err = (last_error_class or "").upper()
    if err in {"NON_EQUITY", "PLACEHOLDER"}:
        return "NON_EQUITY"
    if err in {"QUARANTINE", "MALFORMED_RESPONSE", "IDENTITY_MISMATCH"}:
        return "QUARANTINED"
    if err in {"401", "403", "ENTITLEMENT", "ENTITLEMENT_BLOCKED"}:
        return "ENTITLEMENT_BLOCKED"
    if has_success:
        if success_age_days is not None and success_age_days >= stale_after_days:
            return "STALE_SUCCESS"
        return "FRESH_SUCCESS"
    if selection_count <= 0:
        return "NEVER_ATTEMPTED"
    if err in {"NO_DATA", "NO_COVERAGE", "UNSUPPORTED_SYMBOL"}:
        return "PROVIDER_NO_COVERAGE"
    return "TRANSIENT_FAILURE"


def retry_priority(state: str, *, active_candidate: bool = False, earnings_near: bool = False) -> int:
    if state == "NEVER_ATTEMPTED":
        base = 20
    elif state == "STALE_SUCCESS":
        base = 30
    elif state == "TRANSIENT_FAILURE":
        base = 40
    elif state == "PROVIDER_NO_COVERAGE":
        base = 80
    elif state in {"ENTITLEMENT_BLOCKED", "QUARANTINED", "NON_EQUITY", "FRESH_SUCCESS"}:
        base = 100
    else:
        raise ValueError(f"unknown state: {state}")
    if active_candidate:
        base -= 8
    if earnings_near:
        base -= 10
    return max(0, base)

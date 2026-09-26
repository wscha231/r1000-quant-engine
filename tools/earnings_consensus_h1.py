#!/usr/bin/env python3
"""H1-only consensus integrity. No network, ranking, target or order authority.

Compatibility field names are retained. Economic comparisons additionally need
explicit instrument/provider/unit identity. Missing context is not guessed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import numbers
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

SCHEMA_VERSION = "earnings-consensus-h1-v2"
CONTEXT_KEYS = ("security_id", "issuer_id", "fetch_source", "currency", "accounting_basis", "share_unit", "period_type")
BLOCKED_STATES = {"ENTITLEMENT_BLOCKED", "QUARANTINED", "NON_EQUITY", "FRESH_SUCCESS", "UNKNOWN_FRESHNESS"}


def optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (str, numbers.Real, Decimal)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        out = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def optional_int(value: Any) -> int | None:
    """Nonnegative exact count; no truncation or bool-to-one coercion."""
    if isinstance(value, bool) or not isinstance(value, (str, numbers.Real, Decimal)):
        return None
    try:
        out = Decimal(str(value).strip())
        if not out.is_finite() or out < 0 or out != out.to_integral_value() or out > 2**53 - 1:
            return None
        return int(out)
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None


def pct_change(current: Any, previous: Any) -> float | None:
    c, p = optional_float(current), optional_float(previous)
    if c is None or p is None or p == 0:
        return None
    result = (c - p) / abs(p)
    return result if math.isfinite(result) else None


def iso_utc(value: Any) -> str | None:
    """Require timezone-aware intraday evidence; preserve microseconds."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", value.strip()):
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    try:
        if dt.tzinfo is None or dt.utcoffset() is None:
            return None
        return dt.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError, TypeError):
        return None


def _dt(value: Any) -> datetime | None:
    text = iso_utc(value)
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def period_value(row: dict[str, Any]) -> str | None:
    values = []
    for key in ("period", "date", "fiscalDateEnding", "fiscal_period_end"):
        value = row.get(key)
        if value is None or value == "":
            continue
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return None
        try:
            values.append(date.fromisoformat(value).isoformat())
        except ValueError:
            return None
    return values[0] if values and len(set(values)) == 1 else None


def estimate_rows(payload: Any) -> list[dict[str, Any]]:
    data = payload.get("data", payload.get("estimate", [])) if isinstance(payload, dict) else payload
    rows = [dict(x) for x in data if isinstance(x, dict)] if isinstance(data, list) else []
    return sorted(rows, key=lambda x: period_value(x) or "")


def first_two(payload: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = estimate_rows(payload)
    return (rows[0] if rows else {}, rows[1] if len(rows) > 1 else {})


def recommendation_metrics(payload: Any) -> dict[str, Any]:
    rows = [dict(x) for x in payload if isinstance(x, dict)] if isinstance(payload, list) else []
    rows.sort(key=lambda x: str(x.get("period") or ""))
    row = rows[-1] if rows else {}
    counts = {k: optional_int(row.get(k)) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}
    bull = counts["strongBuy"] + counts["buy"] if counts["strongBuy"] is not None and counts["buy"] is not None else None
    bear = counts["sell"] + counts["strongSell"] if counts["sell"] is not None and counts["strongSell"] is not None else None
    complete = all(v is not None for v in counts.values())
    denom = bull + bear if bull is not None and bear is not None else 0
    return {
        "recommendation_period": row.get("period") or None,
        "recommendation_bull_count": bull,
        "recommendation_hold_count": counts["hold"],
        "recommendation_bear_count": bear,
        "recommendation_balance": (bull - bear) / denom if complete and denom else None,
        "recommendation_status": "COMPLETE" if complete else "INCOMPLETE_COUNTS",
        "est_eps_revision_breadth": None,
        "est_eps_revision_breadth_status": "UNAVAILABLE_FROM_RECOMMENDATION_PAYLOAD",
    }


def _estimate_fields(row: dict[str, Any], prefix: str) -> dict[str, Any]:
    avg, high, low = (optional_float(row.get(k)) for k in ("avg", "high", "low"))
    dispersion = None
    bounds_ok = high is not None and low is not None and high >= low
    if bounds_ok and low != 0 and (avg is None or low <= avg <= high):
        dispersion = (high - low) / abs(low)
        if not math.isfinite(dispersion):
            dispersion = None
    return {f"{prefix}_period_end": period_value(row), f"{prefix}_avg": avg,
            f"{prefix}_high": high, f"{prefix}_low": low,
            f"{prefix}_analyst_count": optional_int(row.get("numberAnalysts")),
            f"{prefix}_dispersion": dispersion}


def _valid_context(row: dict[str, Any]) -> bool:
    return (all(isinstance(row.get(k), str) and row[k].strip() and row[k].upper() not in {"UNKNOWN", "MISSING", "N/A"} for k in CONTEXT_KEYS)
            and row.get("period_type") in {"ANNUAL", "QUARTERLY"})


def _admissible_time(row: dict[str, Any]) -> datetime | None:
    available, observed, collected, first = (_dt(row.get(k)) for k in ("available_at", "observed_at", "collected_at", "first_seen_at"))
    if None in (available, observed, collected, first):
        return None
    if not (first <= observed <= collected <= available):
        return None
    published_raw = row.get("provider_published_at")
    if published_raw is not None:
        published = _dt(published_raw)
        if published is None or published > observed:
            return None
    return available


def build_snapshot(ticker: str, *, eps_payload: Any, revenue_payload: Any,
                   recommendation_payload: Any, observed_at: Any, collected_at: Any,
                   first_seen_at: Any | None = None, provider_published_at: Any | None = None,
                   fetch_source: str = "", eps_estimate_access: bool = True,
                   revenue_estimate_access: bool = True,
                   identity_context: dict[str, Any] | None = None) -> dict[str, Any]:
    observed, collected = iso_utc(observed_at), iso_utc(collected_at)
    first = iso_utc(first_seen_at) if first_seen_at is not None else observed
    published = iso_utc(provider_published_at)
    context = identity_context or {}
    row = {"schema_version": SCHEMA_VERSION, "ticker": str(ticker).upper().strip(),
           **{k: context.get(k) for k in CONTEXT_KEYS}, "fetch_source": fetch_source,
           "observed_at": observed, "first_seen_at": first, "collected_at": collected,
           "provider_published_at": published,
           "available_at": collected, "timestamp_precision": "INTRADAY" if observed and collected else "UNVERIFIED",
           "eps_estimate_access": eps_estimate_access is True,
           "revenue_estimate_access": revenue_estimate_access is True,
           "vendor_estimate_access": eps_estimate_access is True or revenue_estimate_access is True}
    problems = []
    if provider_published_at is not None and published is None:
        problems.append("INVALID_PROVIDER_PUBLICATION_TIME")
    if _admissible_time(row) is None:
        problems.append("INVALID_OR_UNORDERED_TIME")
    for name, payload, access in (("eps", eps_payload, eps_estimate_access), ("rev", revenue_payload, revenue_estimate_access)):
        rows = estimate_rows(payload)
        periods = [period_value(r) for r in rows]
        if any(p is None for p in periods):
            problems.append(name + ":INVALID_FISCAL_PERIOD")
        if len(periods) != len(set(periods)):
            problems.append(name + ":DUPLICATE_FISCAL_PERIOD")
        if access is not True:
            rows = []
        # Preserve nearest explicitly supplied periods. No guessed annual/quarterly roll.
        for n in (1, 2):
            row.update(_estimate_fields(rows[n-1] if len(rows) >= n else {}, f"{name}_fy{n}"))
    row.update(recommendation_metrics(recommendation_payload))
    numeric_present = row["eps_fy1_avg"] is not None or row["rev_fy1_avg"] is not None
    if not row["ticker"]:
        problems.append("MISSING_TICKER")
    row["has_forward_estimate"] = int(numeric_present and not problems)
    row["comparison_identity_complete"] = _valid_context(row)
    row["data_quality_status"] = "BLOCKED_INPUT" if problems else "OBSERVED_CONTEXT_INCOMPLETE" if not _valid_context(row) else "OK" if numeric_present else "NO_USABLE_FORWARD_ESTIMATE"
    row["validation_errors"] = problems
    if problems:
        row["available_at"] = None
    return row


def same_period_revision(current: dict[str, Any], prior: dict[str, Any], prefix: str) -> float | None:
    if not _valid_context(current) or not _valid_context(prior):
        return None
    if any(current[k] != prior[k] for k in CONTEXT_KEYS):
        return None
    ct, pt = _admissible_time(current), _admissible_time(prior)
    if ct is None or pt is None or pt >= ct:
        return None
    if current.get("validation_errors") or prior.get("validation_errors"):
        return None
    period = current.get(f"{prefix}_period_end")
    if period_value({"period": period}) is None or period != prior.get(f"{prefix}_period_end"):
        return None
    return pct_change(current.get(f"{prefix}_avg"), prior.get(f"{prefix}_avg"))


def revision_features(current: dict[str, Any], prior: dict[str, Any] | None) -> dict[str, Any]:
    eps = same_period_revision(current, prior, "eps_fy1") if prior else None
    rev = same_period_revision(current, prior, "rev_fy1") if prior else None
    return {"eps_revision_same_period": eps, "revenue_revision_same_period": rev,
            "revision_status": "OK" if eps is not None or rev is not None else "NOT_COMPARABLE_IDENTITY_TIME_OR_PERIOD"}


def frozen_pre_event_consensus(snapshots: Iterable[dict[str, Any]], *, event_available_at: Any,
                               fiscal_period_end: str, identity_context: dict[str, Any] | None = None,
                               metric: str = "eps") -> dict[str, Any] | None:
    cutoff = _dt(event_available_at)
    if cutoff is None or not _valid_context(identity_context or {}) or metric not in {"eps", "rev"}:
        return None
    if period_value({"period": fiscal_period_end}) is None:
        return None
    eligible = []
    for row in snapshots:
        if not _valid_context(row) or any(row[k] != identity_context[k] for k in CONTEXT_KEYS):
            continue
        avail = _admissible_time(row)
        if avail is None or avail >= cutoff or row.get("validation_errors"):
            continue
        values = [optional_float(row.get(f"{metric}_fy{n}_avg")) for n in (1, 2)
                  if row.get(f"{metric}_fy{n}_period_end") == fiscal_period_end]
        values = [v for v in values if v is not None]
        if len(set(values)) != 1:
            continue
        eligible.append((avail, values[0], row))
    if not eligible:
        return None
    latest = max(x[0] for x in eligible)
    tied = [x for x in eligible if x[0] == latest]
    if len({x[1] for x in tied}) != 1:
        return None
    # Stable return without mutating or inventing an order between conflicting events.
    chosen = min((x[2] for x in tied), key=lambda x: json.dumps(x, sort_keys=True, default=str))
    return copy.deepcopy(chosen)


def causal_event_id(ticker: str, fiscal_period_end: str, event_available_at: Any) -> str:
    timestamp = iso_utc(event_available_at)
    if not isinstance(ticker, str) or not ticker.strip() or not timestamp or period_value({"period": fiscal_period_end}) is None:
        raise ValueError("INVALID_EVENT_IDENTITY_OR_TIME")
    raw = f"{ticker.upper().strip()}|{fiscal_period_end}|{timestamp}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def classify_attempt_state(*, has_success: bool, success_age_days: int | None,
                           selection_count: int, last_error_class: str | None,
                           stale_after_days: int = 7) -> str:
    if type(has_success) is not bool or type(selection_count) is not int or type(stale_after_days) is not int or optional_int(selection_count) is None or optional_int(stale_after_days) in (None, 0):
        return "QUARANTINED"
    if last_error_class is not None and not isinstance(last_error_class, str):
        return "QUARANTINED"
    err = (last_error_class or "").upper()
    if err in {"NON_EQUITY", "PLACEHOLDER"}:
        return "NON_EQUITY"
    if err in {"QUARANTINE", "MALFORMED_RESPONSE", "IDENTITY_MISMATCH"}:
        return "QUARANTINED"
    if err in {"401", "403", "ENTITLEMENT", "ENTITLEMENT_BLOCKED"}:
        return "ENTITLEMENT_BLOCKED"
    if has_success:
        age = optional_int(success_age_days)
        if age is None:
            return "UNKNOWN_FRESHNESS"
        return "STALE_SUCCESS" if age >= stale_after_days else "FRESH_SUCCESS"
    if selection_count == 0:
        return "NEVER_ATTEMPTED"
    return "PROVIDER_NO_COVERAGE" if err in {"NO_DATA", "NO_COVERAGE", "UNSUPPORTED_SYMBOL"} else "TRANSIENT_FAILURE"


def retry_priority(state: str, *, active_candidate: bool = False, earnings_near: bool = False) -> int | None:
    if state in BLOCKED_STATES:
        return None
    bases = {"NEVER_ATTEMPTED": 20, "STALE_SUCCESS": 30, "TRANSIENT_FAILURE": 40, "PROVIDER_NO_COVERAGE": 80}
    if state not in bases:
        raise ValueError(f"unknown state: {state}")
    return max(0, bases[state] - (8 if active_candidate else 0) - (10 if earnings_near else 0))


def retry_decision(state: str, *, now: Any, retry_after: Any = None,
                   active_candidate: bool = False, earnings_near: bool = False) -> dict[str, Any]:
    current = _dt(now)
    due = _dt(retry_after) if retry_after is not None else None
    priority = retry_priority(state, active_candidate=active_candidate, earnings_near=earnings_near)
    allowed = current is not None and priority is not None
    if retry_after is not None and (due is None or current is None or due > current):
        allowed = False
    return {"state": state, "eligible_for_request": allowed, "priority": priority if allowed else None,
            "reason": "DUE" if allowed else "BLOCKED_OR_NOT_DUE"}

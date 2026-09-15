"""Strict supported interface for Theme/ETF Runtime V1.

The lower-level runtime module remains pure and backwards-readable; this module
adds point-in-time input checks and revalidation. CLI and CI use this interface.
"""
from __future__ import annotations

from datetime import date
import math
from typing import Any, Iterable

try:
    from . import runtime as _core
except ImportError:  # direct CLI/test import with runtime directory on sys.path
    import runtime as _core

ContractError = _core.ContractError
build_holding_events = _core.build_holding_events
compose_universe = _core.compose_universe
latest_asof_by_fund = _core.latest_asof_by_fund
digest = _core.digest


def normalize_weight(value: Any, unit: str) -> float:
    raw = str(value).strip() if value is not None else ""
    normalized_unit = str(unit).upper().strip()
    if normalized_unit == "FRACTION" and "%" in raw:
        raise ContractError("percent-marked value conflicts with FRACTION unit")
    return _core.normalize_weight(value, normalized_unit)


def normalize_snapshot(raw: dict[str, Any]) -> dict[str, Any]:
    unit = str(raw.get("weight_unit") or "").upper().strip()
    for row in raw.get("rows", []):
        normalize_weight(row.get("weight"), unit)
    snapshot = _core.normalize_snapshot(raw)
    try:
        holdings_as_of = date.fromisoformat(str(snapshot.get("holdings_as_of") or ""))
    except ValueError as exc:
        raise ContractError("holdings_as_of must be an ISO date") from exc
    if holdings_as_of > _core.utc(snapshot["available_at"]).date():
        raise ContractError("holdings_as_of cannot be later than available_at")
    return snapshot


def validate_normalized_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Validate conservative cached snapshots.

    Externally supplied pre-normalized snapshots may be reused only when they
    are incomplete/conservative. A `complete=True` claim must be rebuilt from
    the raw snapshot contract in the current run, because the normalized shape
    does not retain enough evidence to independently prove source completeness.
    """
    if snapshot.get("schema") != "etf-snapshot-v2":
        raise ContractError("normalized snapshot schema mismatch")
    expected_sha = str(snapshot.get("snapshot_sha256") or "")
    actual_sha = digest({k: v for k, v in snapshot.items() if k != "snapshot_sha256"})
    if not expected_sha or expected_sha != actual_sha:
        raise ContractError("normalized snapshot hash mismatch")
    if str(snapshot.get("coverage_kind") or "").upper() not in _core.ALLOWED_COVERAGE:
        raise ContractError("normalized snapshot coverage_kind invalid")
    available = _core.utc(str(snapshot["available_at"]))
    try:
        holdings_as_of = date.fromisoformat(str(snapshot.get("holdings_as_of") or ""))
    except ValueError as exc:
        raise ContractError("normalized holdings_as_of must be an ISO date") from exc
    if holdings_as_of > available.date():
        raise ContractError("normalized holdings_as_of cannot be later than available_at")
    rows = list(snapshot.get("rows") or [])
    if not rows:
        raise ContractError("normalized snapshot rows required")
    seen: set[str] = set()
    actual_identity_ok = True
    for row in rows:
        security_id = str(row.get("security_id") or "").upper()
        if not security_id or security_id in seen:
            raise ContractError("normalized snapshot security identity invalid")
        seen.add(security_id)
        try:
            weight = float(row.get("weight"))
        except (TypeError, ValueError) as exc:
            raise ContractError("normalized snapshot weight invalid") from exc
        if not math.isfinite(weight) or weight < -1.0 or weight > 1.0:
            raise ContractError("normalized snapshot weight invalid")
        if str(row.get("instrument") or "").upper() in {"COMMON", "ADR", "ETF"} and not bool(row.get("identity_verified", False)):
            actual_identity_ok = False
    if bool(snapshot.get("identity_ok")) != actual_identity_ok:
        raise ContractError("normalized snapshot identity gate mismatch")
    weight_sum = sum(float(row["weight"]) for row in rows)
    if abs(float(snapshot.get("weight_sum")) - weight_sum) > 1e-12:
        raise ContractError("normalized snapshot weight_sum mismatch")
    if bool(snapshot.get("complete", False)):
        raise ContractError("complete normalized snapshot must be rebuilt from raw source evidence")
    return snapshot


def _cutoff(decision_at: str):
    return _core.utc(decision_at)


def validate_price_rows(rows: Iterable[dict[str, Any]], decision_at: str) -> list[dict[str, Any]]:
    cutoff = _cutoff(decision_at)
    out = list(rows)
    seen: set[tuple[str, str]] = set()
    for row in out:
        security_id = str(row.get("security_id") or "").strip().upper()
        session = str(row.get("session") or "").strip()
        available_at = row.get("available_at")
        if not security_id or not session or not available_at:
            raise ContractError("price rows require security_id, session, and available_at")
        key = (security_id, session)
        if key in seen:
            raise ContractError(f"duplicate price row: {security_id} {session}")
        seen.add(key)
        try:
            session_date = date.fromisoformat(session)
            value = float(row.get("total_return_index"))
        except (TypeError, ValueError) as exc:
            raise ContractError("invalid price session or total_return_index") from exc
        if session_date > cutoff.date():
            raise ContractError("future price session at decision time")
        available = _core.utc(str(available_at))
        if available > cutoff:
            raise ContractError("price row was not available at decision time")
        if available.date() < session_date:
            raise ContractError("price row cannot be available before its session")
        if not math.isfinite(value) or value <= 0:
            raise ContractError("total_return_index must be finite and positive")
    return out


def compute_leadership(price_rows: Iterable[dict[str, Any]], benchmark_id: str, *, decision_at: str) -> list[dict[str, Any]]:
    rows = validate_price_rows(price_rows, decision_at)
    return _core.compute_leadership(rows, benchmark_id)


def validate_documents(documents: Iterable[dict[str, Any]], decision_at: str) -> list[dict[str, Any]]:
    cutoff = _cutoff(decision_at)
    out = list(documents)
    seen: set[str] = set()
    for doc in out:
        doc_id = str(doc.get("document_id") or "").strip()
        available_at = doc.get("available_at")
        if not doc_id or not available_at:
            raise ContractError("documents require document_id and available_at")
        if doc_id in seen:
            continue
        seen.add(doc_id)
        if _core.utc(str(available_at)) > cutoff:
            raise ContractError("future document at decision time")
    return out


def discover_terms(documents: Iterable[dict[str, Any]], *, decision_at: str, max_terms: int = 30) -> list[dict[str, Any]]:
    docs = validate_documents(documents, decision_at)
    return _core.discover_terms(docs, max_terms=max_terms)


def validate_membership_events(events: Iterable[dict[str, Any]], decision_at: str) -> list[dict[str, Any]]:
    cutoff = _cutoff(decision_at)
    out = list(events)
    seen: set[str] = set()
    for event in out:
        event_id = str(event.get("event_id") or "").strip()
        observed_at = event.get("observed_at")
        if not event_id or not observed_at:
            raise ContractError("membership events require event_id and observed_at")
        if event_id in seen:
            raise ContractError(f"duplicate membership event_id: {event_id}")
        seen.add(event_id)
        _core.utc(str(event["effective_at"]))
        if _core.utc(str(observed_at)) > cutoff:
            raise ContractError("membership event was not observed at decision time")
        if bool(event.get("reviewed", False)):
            reviewed_at = event.get("reviewed_at")
            if not reviewed_at:
                raise ContractError("reviewed membership event requires reviewed_at")
            reviewed_ts = _core.utc(str(reviewed_at))
            observed_ts = _core.utc(str(observed_at))
            if reviewed_ts > cutoff:
                raise ContractError("membership event was not reviewed at decision time")
            if reviewed_ts < observed_ts:
                raise ContractError("membership review cannot predate observation")
    return out


def resolve_memberships(events: Iterable[dict[str, Any]], decision_at: str) -> dict[str, dict[str, Any]]:
    validated = validate_membership_events(events, decision_at)
    return _core.resolve_memberships(validated, decision_at)


def run_payload(payload: dict[str, Any]) -> dict[str, Any]:
    decision_at = str(payload.get("decision_at") or "")
    _cutoff(decision_at)
    for snapshot in payload.get("etf_snapshots", []):
        if snapshot.get("schema") == "etf-snapshot-v2":
            validate_normalized_snapshot(snapshot)
            if _core.utc(str(snapshot["available_at"])) > _cutoff(decision_at):
                raise ContractError("ETF snapshot was not available at decision time")
        else:
            unit = str(snapshot.get("weight_unit") or "").upper().strip()
            for row in snapshot.get("rows", []):
                normalize_weight(row.get("weight"), unit)
    validate_price_rows(payload.get("prices", []), decision_at)
    validate_documents(payload.get("documents", []), decision_at)
    validate_membership_events(payload.get("membership_events", []), decision_at)
    return _core.run_payload(payload)

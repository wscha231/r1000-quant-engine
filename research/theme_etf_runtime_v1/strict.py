"""Strict supported interface for Theme/ETF Runtime V1.

The lower-level runtime module remains pure and backwards-readable; this module
adds input conflict checks and revalidation for normalized snapshots. CLI and
CI use this interface.
"""
from __future__ import annotations

import math
from typing import Any

try:
    from . import runtime as _core
except ImportError:  # direct CLI/test import with runtime directory on sys.path
    import runtime as _core

ContractError = _core.ContractError
build_holding_events = _core.build_holding_events
compose_universe = _core.compose_universe
compute_leadership = _core.compute_leadership
discover_terms = _core.discover_terms
latest_asof_by_fund = _core.latest_asof_by_fund
resolve_memberships = _core.resolve_memberships
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
    return _core.normalize_snapshot(raw)


def validate_normalized_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    if snapshot.get("schema") != "etf-snapshot-v2":
        raise ContractError("normalized snapshot schema mismatch")
    expected_sha = str(snapshot.get("snapshot_sha256") or "")
    actual_sha = digest({k: v for k, v in snapshot.items() if k != "snapshot_sha256"})
    if not expected_sha or expected_sha != actual_sha:
        raise ContractError("normalized snapshot hash mismatch")
    if str(snapshot.get("coverage_kind") or "").upper() not in _core.ALLOWED_COVERAGE:
        raise ContractError("normalized snapshot coverage_kind invalid")
    _core.utc(str(snapshot["available_at"]))
    rows = list(snapshot.get("rows") or [])
    if not rows:
        raise ContractError("normalized snapshot rows required")
    seen: set[str] = set()
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
    weight_sum = sum(float(row["weight"]) for row in rows)
    if abs(float(snapshot.get("weight_sum")) - weight_sum) > 1e-12:
        raise ContractError("normalized snapshot weight_sum mismatch")
    if bool(snapshot.get("complete", False)):
        if str(snapshot.get("coverage_kind")).upper() != _core.FULL_COVERAGE:
            raise ContractError("only FULL snapshots may be complete")
        if not all(bool(snapshot.get(k, False)) for k in ("expected_unique_rows_ok", "identity_ok", "weight_sum_ok")):
            raise ContractError("complete snapshot gates are inconsistent")
        if abs(weight_sum - 1.0) > 0.02:
            raise ContractError("complete snapshot weight sum outside tolerance")
    return snapshot


def run_payload(payload: dict[str, Any]) -> dict[str, Any]:
    for snapshot in payload.get("etf_snapshots", []):
        if snapshot.get("schema") == "etf-snapshot-v2":
            validate_normalized_snapshot(snapshot)
        else:
            unit = str(snapshot.get("weight_unit") or "").upper().strip()
            for row in snapshot.get("rows", []):
                normalize_weight(row.get("weight"), unit)
    return _core.run_payload(payload)

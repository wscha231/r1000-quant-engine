"""Moat/bottleneck causal diagnostic, RESEARCH_ONLY.

An additive observation of an existing immutable Moat/Quality V2 result.
It does NOT alter the six moat dimension weights, admit an A3 packet, compute
validated alpha, or authorize buying/portfolio exposure.

The caller must supply an authenticated artifact resolver and independent
producer/admission evidence. SHA agreement alone is NOT authentication.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from typing import Any, Callable

SCHEMA = "moat-bottleneck-causal-diagnostic-v1"
RESULT_SCHEMA = "moat-bottleneck-causal-diagnostic-result-v1"
BARRIERS = (
    "capital_intensity", "technical_complexity", "accumulated_knowhow",
    "institutional_protection",
)
STATES = {"EVIDENCED", "CONTESTED", "WEAK", "UNKNOWN", "NOT_APPLICABLE"}
METRICS = {
    "demand_growth_yoy_pct", "capacity_growth_yoy_pct", "backlog_growth_yoy_pct",
    "lead_time_days", "asp_growth_yoy_pct", "roic_pct", "wacc_pct",
    "fcf_margin_pct", "incremental_roic_pct",
}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,199}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_MAX_RAW = 1_048_576
_MAX_TOTAL = 8 * _MAX_RAW
MAX_EVIDENCE = 48
MAX_METRICS = 20
RawResolver = Callable[[str, str], bytes]


class MoatDiagnosticError(ValueError):
    """A malformed, inconsistent or temporally ineligible research input."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise MoatDiagnosticError(code)


def text(value: Any, code: str, limit: int = 1200) -> str:
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= limit, code)
    return value.strip()


def ident(value: Any, code: str) -> str:
    value = text(value, code, 200)
    require(bool(_ID.fullmatch(value)), code)
    return value


def hash64(value: Any, code: str) -> str:
    require(isinstance(value, str) and bool(_HASH.fullmatch(value)), code)
    return value


def stamp(value: Any, code: str) -> datetime:
    value = text(value, code, 50)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise MoatDiagnosticError(code) from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, code)
    return parsed.astimezone(timezone.utc)


def day(value: Any, code: str) -> date:
    value = text(value, code, 10)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise MoatDiagnosticError(code) from exc
    require(parsed.isoformat() == value, code)
    return parsed


def finite(value: Any, code: str) -> float:
    require(type(value) in (int, float), code)
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise MoatDiagnosticError(code) from exc
    require(math.isfinite(number) and abs(number) <= 1_000_000, code)
    return number


def sha_object(obj: Any) -> str:
    return hashlib.sha256(json.dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def decode_strict(raw: bytes) -> Any:
    require(len(raw) <= _MAX_RAW, "moat_raw_oversize")
    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, val in items:
            require(key not in obj, "duplicate_json_key")
            obj[key] = val
        return obj
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda x: (_ for _ in ()).throw(MoatDiagnosticError("nonfinite_json")))
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, MoatDiagnosticError):
            raise
        raise MoatDiagnosticError("moat_json_invalid") from exc


def evaluate(packet: dict[str, Any], cutoff: str, raw_resolver: RawResolver) -> dict[str, Any]:
    require(type(packet) is dict and callable(raw_resolver), "packet_or_resolver")
    require(packet.get("schema") == SCHEMA, "schema")
    require(packet.get("review_status") == "RESEARCH_REVIEWED", "research_review_required")
    as_of = stamp(packet.get("as_of"), "as_of")
    reviewed_at = stamp(packet.get("reviewed_at"), "reviewed_at")
    clock = stamp(cutoff, "trusted_cutoff")
    require(as_of <= reviewed_at <= clock, "future_review")
    asset = ident(packet.get("asset_id"), "asset_id")
    issuer = ident(packet.get("issuer_id"), "issuer_id")

    seen_artifacts: dict[str, str] = {}
    raw_cache: dict[tuple[str, str], bytes] = {}
    used_bytes = 0
    def resolve(artifact: str, digest: str) -> bytes:
        nonlocal used_bytes
        artifact = ident(artifact, "artifact_id")
        digest = hash64(digest, "artifact_sha256")
        require(artifact not in seen_artifacts or seen_artifacts[artifact] == digest,
                "artifact_identity_conflict")
        seen_artifacts[artifact] = digest
        key = (artifact, digest)
        if key not in raw_cache:
            try:
                value = raw_resolver(artifact, digest)
            except Exception as exc:
                raise MoatDiagnosticError("raw_evidence_unavailable") from exc
            require(type(value) is bytes and 0 < len(value) <= _MAX_RAW,
                    "raw_evidence_bytes")
            used_bytes += len(value)
            require(used_bytes <= _MAX_TOTAL, "raw_budget_exceeded")
            require(hashlib.sha256(value).hexdigest() == digest, "raw_hash_mismatch")
            raw_cache[key] = value
        return raw_cache[key]

    moat_ref = packet.get("moat_result_ref")
    require(type(moat_ref) is dict, "moat_ref_required")
    require(stamp(moat_ref.get("available_at"), "moat_available_at") <=
            stamp(moat_ref.get("collected_at"), "moat_collected_at") <= as_of,
            "moat_future_or_clock")
    moat = decode_strict(resolve(moat_ref.get("artifact_id"), moat_ref.get("sha256")))
    require(type(moat) is dict and moat.get("schema") == "moat-quality-v2-result"
            and moat.get("status") == "COMPLETE_RESEARCH_REVIEW", "moat_result_schema")
    require(moat.get("asset_id") == asset and moat.get("issuer_id") == issuer,
            "moat_subject_mismatch")
    require(stamp(moat.get("as_of"), "moat_as_of") <= as_of and
            stamp(moat.get("reviewed_at"), "moat_reviewed_at") <=
            stamp(moat_ref["available_at"], "moat_available_at"),
            "moat_clock_mismatch")
    require(moat.get("selector_eligible") is False and
            type(moat.get("portfolio_weight_effect")) in (int, float) and
            moat["portfolio_weight_effect"] == 0 and
            moat.get("orders_allowed") is False and
            moat.get("oos_validated") is False,
            "moat_authority_mismatch")
    hash64(moat.get("packet_sha256"), "moat_packet_sha256")
    moat_score = finite(moat.get("moat_quality_score"), "moat_quality_score")
    require(0.0 <= moat_score <= 1.0 and moat.get("production_authority") is False,
            "moat_score_or_authority")

    evidence = packet.get("evidence")
    require(type(evidence) is list and len(evidence) <= MAX_EVIDENCE, "evidence_count")
    by_id: dict[str, dict[str, Any]] = {}
    for row in evidence:
        require(type(row) is dict, "evidence_row")
        eid = ident(row.get("evidence_id"), "evidence_id")
        require(eid not in by_id, "duplicate_evidence_id")
        require(row.get("issuer_id") == issuer, "evidence_issuer_identity")
        require(row.get("asset_id") == asset, "evidence_asset_identity")
        observed = stamp(row.get("observed_at"), "evidence_observed_at")
        published = stamp(row.get("published_at"), "evidence_published_at")
        available = stamp(row.get("available_at"), "evidence_available_at")
        collected = stamp(row.get("collected_at"), "evidence_collected_at")
        verified = stamp(row.get("verified_at"), "evidence_verified_at")
        valid_through = stamp(row.get("valid_through"), "evidence_valid_through")
        require(observed <= published <= available <= collected <= verified <= as_of
                <= valid_through, "evidence_temporal_order")
        require(row.get("direction") in ("SUPPORT", "CHALLENGE"), "evidence_direction")
        require(row.get("source_affiliation") in ("ISSUER", "INDEPENDENT"),
                "evidence_affiliation")
        group = ident(row.get("independence_group"), "independence_group")
        claim = text(row.get("claim"), "evidence_claim")
        resolve(row.get("artifact_id"), row.get("sha256"))
        by_id[eid] = dict(direction=row["direction"], affiliation=row["source_affiliation"],
                          independence_group=group, claim=claim)

    barriers = packet.get("barriers")
    require(type(barriers) is dict and set(barriers) == set(BARRIERS), "barrier_set")
    barrier_out: dict[str, dict[str, Any]] = {}
    for name in BARRIERS:
        item = barriers[name]
        require(type(item) is dict and item.get("state") in STATES, "barrier_state")
        state = item["state"]
        mechanism = text(item.get("mechanism"), "barrier_mechanism")
        counter = text(item.get("counter_thesis"), "barrier_counter_thesis")
        invalidations = item.get("invalidation_conditions")
        require(type(invalidations) is list and bool(invalidations) and
                len(invalidations) <= 8, "barrier_invalidations")
        invalidations = [text(x, "barrier_invalidation", 500) for x in invalidations]
        require(len(invalidations) == len(set(invalidations)), "duplicate_invalidation")
        refs = item.get("evidence_ids")
        require(type(refs) is list and len(refs) <= MAX_EVIDENCE and
                all(type(x) is str and x in by_id for x in refs),
                "barrier_evidence_refs")
        require(len(refs) == len(set(refs)), "barrier_evidence_refs")
        support = [by_id[x] for x in refs if by_id[x]["direction"] == "SUPPORT"]
        challenge = [by_id[x] for x in refs if by_id[x]["direction"] == "CHALLENGE"]
        if state == "EVIDENCED":
            require(support and any(x["affiliation"] == "INDEPENDENT" for x in support),
                    "barrier_independent_support")
        elif state == "CONTESTED":
            require(support and challenge, "barrier_two_sided_evidence")
        elif state == "WEAK":
            require(challenge, "barrier_challenge_required")
        else:
            require(not refs, "barrier_unknown_must_not_cite")
        barrier_out[name] = dict(state=state, mechanism=mechanism,
                                 counter_thesis=counter,
                                 invalidation_conditions=invalidations,
                                 evidence_ids=list(refs))

    metrics = packet.get("metrics")
    require(type(metrics) is list and len(metrics) <= MAX_METRICS, "metric_count")
    metric_map: dict[str, dict[str, Any]] = {}
    for row in metrics:
        require(type(row) is dict, "metric_row")
        name = row.get("name")
        require(type(name) is str and name in METRICS and name not in metric_map,
                "metric_name_or_duplicate")
        value = finite(row.get("value"), "metric_value")
        if name == "lead_time_days":
            require(value >= 0, "negative_lead_time")
        eid = ident(row.get("evidence_id"), "metric_evidence_id")
        require(eid in by_id, "metric_unverified_source")
        period_end = day(row.get("period_end"), "metric_period_end")
        require(period_end <= as_of.date(), "future_metric_period")
        basis = text(row.get("basis"), "metric_basis", 120)
        metric_map[name] = dict(value=value, period_end=period_end.isoformat(),
                                basis=basis, evidence_id=eid)

    def paired(left: str, right: str) -> tuple[float | None, str]:
        if left not in metric_map or right not in metric_map:
            return None, "MISSING_INPUT"
        a, b = metric_map[left], metric_map[right]
        if a["period_end"] != b["period_end"] or a["basis"] != b["basis"]:
            return None, "INCOMPARABLE_PERIOD_OR_BASIS"
        return a["value"] - b["value"], "ARITHMETIC_ONLY_NOT_CALIBRATED"

    capacity_minus_demand, gap_status = paired("capacity_growth_yoy_pct", "demand_growth_yoy_pct")
    roic_minus_wacc, spread_status = paired("roic_pct", "wacc_pct")
    return {
        "schema": RESULT_SCHEMA,
        "status": "CAUSAL_DIAGNOSTIC_RESEARCH_ONLY",
        "asset_id": asset, "issuer_id": issuer, "as_of": packet["as_of"],
        "moat_v2_result_sha256": moat_ref["sha256"],
        "moat_v2_packet_semantic_sha256": moat["packet_sha256"],
        "moat_v2_score_unchanged": moat_score,
        "barriers": barrier_out,
        "metrics": metric_map,
        "capacity_minus_demand_growth_pp": capacity_minus_demand,
        "capacity_demand_comparison_status": gap_status,
        "roic_minus_wacc_pp": roic_minus_wacc,
        "economic_spread_comparison_status": spread_status,
        "packet_sha256": sha_object(packet),
        "raw_artifact_count": len(raw_cache),
        "source_authenticated": False,
        "metric_values_externally_reconciled": False,
        "historical_pit_certified": False,
        "oos_validated": False,
        "selector_eligible": False,
        "portfolio_weight_effect": 0.0,
        "er_eligible": False,
        "orders_allowed": False,
        "target_book_write_allowed": False,
        "regime_authorized": False,
        "research_only": True,
    }

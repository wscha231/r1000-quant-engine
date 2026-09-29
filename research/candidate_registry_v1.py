"""#516 I0.1: a reference-only index over existing A3 packets and results.

This is a pure adapter, not a persistent registry writer, new evaluator,
review authenticator, freshness policy, or A5 consumer. It replays the existing
A3 *validator* against resolved bytes; it does not repeat upstream research.
A coherent caller-supplied bundle is not proof of an independently accepted
review or of which bundle is current. All economic and reuse authority stays
closed, including when an A3 result declares VALIDATED_ER_LINKED.
"""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any

if __package__:
    from .a3_candidate_packet_v1 import A3CandidatePacketError, evaluate_packet
else:
    from a3_candidate_packet_v1 import A3CandidatePacketError, evaluate_packet

SCHEMA = "candidate-registry-v1-reference-index"
MAX_ENTRIES = 10000
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 100000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,199}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z")
_ENTRY_FIELDS = {"asset_id", "issuer_id", "a3_packet_ref", "a3_result_ref"}
_REF_FIELDS = {"artifact_id", "sha256", "available_at", "collected_at", "expires_at"}
_A3_ROLES = {"methodology", "moat", "market_valuation", "source_graph", "validated_er"}
_CONSUMPTION_BLOCKERS = (
    "A0_CURRENT_REFERENCE_AUTHENTICATION_REQUIRED",
    "INDEPENDENT_REVIEW_NOT_AUTHENTICATED",
    "DOMAIN_ADMISSION_NOT_VERIFIED",
    "FRESHNESS_CATALYST_COLLECTION_CHECK_REQUIRED",
    "ECONOMIC_ADMISSION_NOT_VERIFIED",
    "A5_CONSUMER_NOT_CONNECTED",
)
ArtifactResolver = Callable[[str, str], bytes]


class ReferenceIndexError(ValueError):
    """Invalid supplied reference set, identity, bytes or metadata."""


class _BatchError(ReferenceIndexError):
    """An ambiguous immutable identity or exhausted shared budget."""


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise ReferenceIndexError(reason)


def _identifier(value: Any, reason: str) -> str:
    _require(isinstance(value, str) and _ID.fullmatch(value) is not None, reason)
    return value


def _digest(value: Any) -> str:
    _require(isinstance(value, str) and _HASH.fullmatch(value) is not None, "invalid_sha256")
    return value


def _stamp(value: Any) -> datetime:
    _require(isinstance(value, str) and _TIME.fullmatch(value) is not None, "timezone_required")
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _require(out.tzinfo is not None and out.utcoffset() is not None, "timezone_required")
        return out.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ReferenceIndexError("invalid_timestamp") from exc


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _json_object(raw: bytes) -> dict[str, Any]:
    def pairs(items):
        out = {}
        for key, value in items:
            _require(key not in out, "duplicate_json_key")
            out[key] = value
        return out

    def constant(_):
        raise ReferenceIndexError("nonfinite_json")

    def finite(value):
        number = float(value)
        _require(math.isfinite(number), "nonfinite_json")
        return number

    try:
        obj = json.loads(raw, object_pairs_hook=pairs,
                         parse_constant=constant, parse_float=finite)
    except ReferenceIndexError:
        raise
    except RecursionError as exc:
        raise ReferenceIndexError("json_depth_limit") from exc
    except (ValueError, UnicodeError) as exc:
        raise ReferenceIndexError("invalid_json") from exc
    _require(isinstance(obj, dict), "json_object_required")
    stack, count = [(obj, 0)], 0
    while stack:
        value, depth = stack.pop()
        count += 1
        _require(count <= MAX_JSON_NODES, "json_node_limit")
        _require(depth <= MAX_JSON_DEPTH, "json_depth_limit")
        if isinstance(value, dict):
            stack.extend((v, depth + 1) for v in value.values())
        elif isinstance(value, list):
            stack.extend((v, depth + 1) for v in value)
    return obj


class _Snapshot:
    """Resolve once per exact ID/hash within this invocation, never across runs.

    The caller supplies a trusted read-only resolver. This adapter cannot turn
    an arbitrary injected callback into a network or filesystem sandbox.
    """
    def __init__(self, resolver: ArtifactResolver):
        self.resolver = resolver
        self.cache: dict[tuple[str, str], bytes] = {}
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.decode_errors: dict[tuple[str, str], str] = {}
        self.identities: dict[str, str] = {}
        self.bytes_read = 0
        self.current_reads: set[tuple[str, str]] = set()
        self.fatal: _BatchError | None = None

    def register(self, aid: str, digest: str) -> None:
        _identifier(aid, "artifact_id")
        _digest(digest)
        old = self.identities.get(aid)
        if old is not None and old != digest:
            self.fatal = _BatchError("artifact_id_conflict")
            raise self.fatal
        self.identities[aid] = digest

    def read(self, aid: str, digest: str) -> bytes:
        self.register(aid, digest)
        key = (aid, digest)
        self.current_reads.add(key)
        if key in self.cache:
            return self.cache[key]
        try:
            raw = self.resolver(aid, digest)
        except Exception:
            # Provider errors may contain credentials or private URLs.
            raise ReferenceIndexError("artifact_unavailable") from None
        _require(type(raw) is bytes and 0 < len(raw) <= MAX_ARTIFACT_BYTES, "artifact_bytes")
        if self.bytes_read + len(raw) > MAX_TOTAL_BYTES:
            self.fatal = _BatchError("total_byte_budget")
            raise self.fatal
        self.bytes_read += len(raw)
        _require(hashlib.sha256(raw).hexdigest() == digest, "artifact_hash_mismatch")
        self.cache[key] = raw
        return raw

    def object(self, ref: dict[str, Any]) -> dict[str, Any]:
        # Always track reads, even when decoding has already succeeded/failed.
        raw = self.read(ref["artifact_id"], ref["sha256"])
        key = (ref["artifact_id"], ref["sha256"])
        if key in self.decode_errors:
            raise ReferenceIndexError(self.decode_errors[key])
        if key not in self.objects:
            try:
                self.objects[key] = _json_object(raw)
            except ReferenceIndexError as exc:
                # Store only the bounded reason, not a traceback retaining raw data.
                self.decode_errors[key] = str(exc)
                raise
        return self.objects[key]


def _reference(value: Any, cutoff: datetime) -> dict[str, Any]:
    _require(isinstance(value, dict) and set(value) == _REF_FIELDS, "reference_fields")
    _identifier(value["artifact_id"], "artifact_id")
    _digest(value["sha256"])
    available, collected = _stamp(value["available_at"]), _stamp(value["collected_at"])
    _require(available <= collected <= cutoff, "reference_time_order")
    expiry = value["expires_at"]
    if expiry is not None:
        _require(_stamp(expiry) >= collected, "expiry_precedes_collection")
    return deepcopy(value)


def _closed_record(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": entry["asset_id"], "issuer_id": entry["issuer_id"],
        "reference_status": "BLOCKED", "blockers": [],
        "a3_packet_ref": None, "a3_result_ref": None,
        "packet_semantic_sha256": None, "upstream_artifact_refs": None,
        "resolved_blob_refs": [], "validated_er_ref": None,
        "a3_result_status": None, "metadata": None,
        "declared_expiry_state": "UNKNOWN",
        "research_freshness_state": "NOT_CERTIFIED",
        "review_authentication_status": "NOT_VERIFIED",
        "current_selection_status": "NOT_VERIFIED",
        "domain_admission_status": "NOT_VERIFIED",
        "consumption_blockers": list(_CONSUMPTION_BLOCKERS),
        "reuse_authorized": False, "A5_eligible_input": False,
        "selector_eligible": False, "target_book_write_allowed": False,
        "ledger_write_allowed": False, "orders_allowed": False,
        "production_authority": False,
    }


def _index_one(entry: dict[str, Any], row: dict[str, Any], cutoff: datetime,
               snapshot: _Snapshot) -> None:
    _require(set(entry) == _ENTRY_FIELDS, "entry_fields")
    pref = _reference(entry["a3_packet_ref"], cutoff)
    rref = _reference(entry["a3_result_ref"], cutoff)
    row["a3_packet_ref"], row["a3_result_ref"] = pref, rref
    _require(_stamp(rref["available_at"]) >= _stamp(pref["collected_at"]), "result_precedes_packet")
    packet, stored = snapshot.object(pref), snapshot.object(rref)
    _require(packet.get("asset_id") == entry["asset_id"], "packet_asset_identity")
    _require(packet.get("issuer_id") == entry["issuer_id"], "packet_issuer_identity")
    _require(_stamp(pref["available_at"]) >= _stamp(packet.get("reviewed_at")), "packet_precedes_review")
    refs = packet.get("artifacts")
    _require(isinstance(refs, dict) and set(refs) <= _A3_ROLES, "a3_artifact_roles")
    # Strict decode of structured dependencies; raw source documents remain
    # arbitrary bytes and are checked by the unchanged A3 resolver boundary.
    for ref in refs.values():
        if ref is not None:
            _require(isinstance(ref, dict), "a3_artifact_reference")
            snapshot.object(ref)
    try:
        actual = evaluate_packet(packet, cutoff.isoformat(), snapshot.read)
    except A3CandidatePacketError:
        if snapshot.fatal is not None:
            raise snapshot.fatal
        raise ReferenceIndexError("A3_VALIDATION_FAILED") from None
    # Python equality considers False == 0. Compare canonical JSON instead.
    _require(_canonical(actual) == _canonical(stored), "result_replay_mismatch")
    market = snapshot.object(refs["market_valuation"])
    for value in (packet["country"], packet["asset_class"], market["currency"], market["benchmark_id"]):
        _identifier(value, "metadata_identity")
    expected_fields = {"kind", "artifact_id", "sha256", "available_at", "review_status"}
    upstream = {}
    for role, ref in refs.items():
        if ref is not None:
            _require(set(ref) == expected_fields, "a3_reference_fields")
            upstream[role] = deepcopy(ref)
    expiries = [pref["expires_at"], rref["expires_at"]]
    if any(x is not None and _stamp(x) <= cutoff for x in expiries):
        expiry_state = "EXPIRED"
    elif any(x is None for x in expiries):
        expiry_state = "UNKNOWN"
    else:
        expiry_state = "UNEXPIRED"
    row.update({
        "reference_status": "A3_REFERENCE_REPLAY_VERIFIED",
        "packet_semantic_sha256": actual["packet_sha256"],
        "a3_result_status": actual["status"],
        "upstream_artifact_refs": upstream,
        "validated_er_ref": deepcopy(upstream.get("validated_er")),
        "declared_expiry_state": expiry_state,
        "resolved_blob_refs": [
            {"artifact_id": aid, "sha256": sha, "bytes": len(snapshot.cache[(aid, sha)])}
            for aid, sha in sorted(snapshot.current_reads)
        ],
        "metadata": {
            "as_of": packet["as_of"], "reviewed_at": packet["reviewed_at"],
            "country": packet["country"], "asset_class": packet["asset_class"],
            "currency": market["currency"], "benchmark_id": market["benchmark_id"],
            "market_session_date": market["session_date"],
            "thesis_status": packet["thesis"]["status"],
        },
    })
    if upstream.get("validated_er") is None:
        row["consumption_blockers"].append("VALIDATED_ER_NOT_LINKED")
    if expiry_state != "UNEXPIRED":
        row["consumption_blockers"].append("DECLARED_REFERENCE_EXPIRY_" + expiry_state)


def build_reference_index(entries: Any, *, cutoff: str,
                          artifact_resolver: ArtifactResolver) -> dict[str, Any]:
    """Build an immutable *proposal object* for one supplied reference per asset.

    Duplicate or unidentifiable securities, ID/hash conflicts, and exhausted
    shared budgets reject the entire invocation. Identifiable records with
    invalid source evidence remain visible as BLOCKED rows. Nothing is saved,
    promoted, dispatched, sized, or removed from any canonical registry.
    """
    cutoff_stamp = _stamp(cutoff)
    _require(callable(artifact_resolver), "artifact_resolver_required")
    _require(isinstance(entries, list) and len(entries) <= MAX_ENTRIES, "entry_batch")
    seen = set()
    for entry in entries:
        _require(isinstance(entry, dict), "entry_object")
        aid = _identifier(entry.get("asset_id"), "asset_id")
        _identifier(entry.get("issuer_id"), "issuer_id")
        _require(aid not in seen, "duplicate_asset_id")
        seen.add(aid)
    snapshot = _Snapshot(artifact_resolver)
    # Contradictory immutable identities are a batch error, even if a row's
    # timestamps or other metadata will prevent it from reaching resolution.
    for entry in entries:
        for role in ("a3_packet_ref", "a3_result_ref"):
            ref = entry.get(role)
            if not isinstance(ref, dict):
                continue
            try:
                aid = _identifier(ref.get("artifact_id"), "artifact_id")
                digest = _digest(ref.get("sha256"))
            except ReferenceIndexError:
                continue  # Malformed identity descriptors remain row-local errors.
            snapshot.register(aid, digest)
    records = []
    for entry in sorted(entries, key=lambda e: e["asset_id"]):
        row = _closed_record(entry)
        snapshot.current_reads = set()
        try:
            _index_one(entry, row, cutoff_stamp, snapshot)
        except _BatchError:
            raise
        except ReferenceIndexError as exc:
            row["blockers"] = [str(exc)]
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            if snapshot.fatal is not None:
                raise snapshot.fatal
            row["blockers"] = ["MALFORMED_A3_INPUT"]
        records.append(row)
    verified = sum(row["reference_status"] == "A3_REFERENCE_REPLAY_VERIFIED" for row in records)
    out = {
        "schema": SCHEMA, "authority": "PROPOSAL_NOT_CANONICAL",
        "scope": "SUPPLIED_REFERENCE_SET_ONLY", "cutoff": cutoff_stamp.isoformat(),
        "status": ("EMPTY_INPUT" if not records else "REFERENCE_INDEX_BUILT"
                   if verified == len(records) else "REFERENCE_ERRORS_PRESENT"),
        "input_count": len(records), "reference_verified_count": verified,
        "blocked_count": len(records) - verified,
        "economic_consumption_allowed": False, "canonical_write_performed": False,
        "records": records,
    }
    out["index_sha256"] = hashlib.sha256(_canonical(out)).hexdigest()
    return out


__all__ = ["ReferenceIndexError", "build_reference_index"]

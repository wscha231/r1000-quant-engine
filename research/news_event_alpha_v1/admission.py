"""P0-2 bounded local input-bundle verification, not automatic certification.

Three different facts are preserved: byte integrity, internally consistent
provenance, and an independently pinned approval. A hash alone proves neither
market truth, PIT correctness, coverage completeness nor licensing. This module
never downloads data, grants rights, writes a Drive head or changes a selector.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from bisect import bisect_left
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlsplit

from .runtime import (ContractError, checkpoint_key, event_revision_key, normalize_event,
                      strict_bool, utc, validate_sessions)
from .execution import ExecutionBook, require, validate_policy

CONSUMER = "news-event-next-close-audit-p0.2"
ROLES = {"snapshots", "prices", "sessions", "securities", "documents", "rights", "coverage", "policy", "config"}
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_BUNDLE_BYTES = 256 * 1024 * 1024
MAX_ROWS = 100000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def json_load(b: bytes) -> Any:
    def unique(pairs):
        out = {}
        for k, v in pairs:
            require(k not in out, "DUPLICATE_JSON_KEY")
            out[k] = v
        return out
    def invalid(_):
        raise ContractError("NONFINITE_JSON")
    try:
        return json.loads(b.decode("utf-8-sig"), object_pairs_hook=unique, parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("INVALID_JSON") from exc


def timestamp(value, name):
    require(type(value) is str, "INVALID_TIMESTAMP:" + name)
    return utc(value)


def safe_rel(rel: str) -> str:
    require(type(rel) is str and len(rel) <= 240 and bool(rel), "UNSAFE_PATH")
    require(not any(c in rel for c in ("\\", ":")) and not any(ord(c) < 32 for c in rel) and not PurePosixPath(rel).is_absolute(), "UNSAFE_PATH")
    parts = rel.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1,10)} | {f"LPT{i}" for i in range(1,10)}
    require(all(p not in {"", ".", ".."} and not p.endswith((" ", "."))
                and p.split(".")[0].upper() not in reserved for p in parts), "UNSAFE_PATH")
    return rel


def reparse_point(p: Path) -> bool:
    # Windows junction detection also works on Python 3.10/3.11.
    import stat
    if not p.exists() and not p.is_symlink():
        return False
    return p.is_symlink() or bool(getattr(p.lstat(), "st_file_attributes", 0)
                                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def checked_file(root: Path, rel: str) -> Path:
    safe_rel(rel)
    p = root
    for part in rel.split("/"):
        p = p / part
        require(not reparse_point(p), "SYMLINK_NOT_ALLOWED")
        require(not (hasattr(p, "is_junction") and p.is_junction()), "JUNCTION_NOT_ALLOWED")
    require(p.resolve().is_relative_to(root.resolve()), "PATH_ESCAPE")
    require(p.is_file(), "FILE_MISSING:" + rel)
    return p


def read_bounded(p: Path, limit: int = MAX_FILE_BYTES) -> bytes:
    require(p.stat().st_size <= limit, "FILE_TOO_LARGE")
    with p.open("rb") as f:
        b = f.read(limit + 1)
    require(len(b) <= limit, "FILE_TOO_LARGE")
    return b


def rows(b: bytes) -> list[dict]:
    out = []
    for line in b.splitlines():
        if not line.strip():
            continue
        r = json_load(line)
        require(type(r) is dict, "ROW_NOT_OBJECT")
        out.append(r)
        require(len(out) <= MAX_ROWS, "ROW_BUDGET_EXCEEDED")
    return out


@dataclass(frozen=True)
class VerifiedBundle:
    """A snapshot of already-hashed bytes, preventing verify-then-reread races."""
    manifest_bytes: bytes
    files: Mapping[str, bytes]
    roles: Mapping[str, str]
    manifest_sha256: str
    report: Mapping[str, Any]

    def json(self, role: str):
        return json_load(self.files[self.roles[role]])

    def rows(self, role: str):
        return rows(self.files[self.roles[role]])

    @property
    def manifest(self):
        return json_load(self.manifest_bytes)


def verify_bundle(root: Path, *, now: str) -> VerifiedBundle:
    """Check bytes and declared data graph; NEVER returns an approval itself."""
    root = Path(root)
    require(root.is_dir() and not reparse_point(root), "BUNDLE_ROOT")
    raw = read_bounded(checked_file(root, "manifest.json"))
    m = json_load(raw)
    require(type(m) is dict and m.get("schema") == "news-event-input-bundle-p0.2", "MANIFEST_SCHEMA")
    require(m.get("consumer") == CONSUMER, "WRONG_CONSUMER")
    require(m.get("origin") in {"HISTORICAL_RECONSTRUCTION", "FORWARD_OBSERVED", "SYNTHETIC_TEST"}, "BUNDLE_ORIGIN")
    require(bool(HEX40.fullmatch(str(m.get("source_commit", "")))), "SOURCE_COMMIT")
    cutoff = timestamp(m.get("data_cutoff"), "data_cutoff")
    generated = timestamp(m.get("generated_at"), "generated_at")
    require(cutoff <= generated <= utc(now), "BUNDLE_CLOCK")
    require(type(m.get("generation")) is int and m["generation"] >= 1, "GENERATION")
    parent = m.get("parent_receipt_sha256")
    require((m["generation"] == 1 and parent is None) or
            (m["generation"] > 1 and bool(HEX64.fullmatch(str(parent)))), "PARENT_SHAPE")
    entries = m.get("files")
    require(type(entries) is list and bool(entries), "MANIFEST_FILES")
    files, roles, case_names = {}, {}, set()
    total = 0
    for e in entries:
        require(type(e) is dict, "FILE_ENTRY")
        rel = safe_rel(e.get("path"))
        require(rel != "manifest.json" and rel.casefold() not in case_names, "DUPLICATE_FILE_PATH")
        case_names.add(rel.casefold())
        require(type(e.get("bytes")) is int and 0 <= e["bytes"] <= MAX_FILE_BYTES, "FILE_LENGTH")
        require(bool(HEX64.fullmatch(str(e.get("sha256", "")))), "FILE_HASH_SHAPE")
        total += e["bytes"]
        require(total <= MAX_BUNDLE_BYTES, "BUNDLE_BUDGET_EXCEEDED")
        data = read_bounded(checked_file(root, rel))
        require(len(data) == e["bytes"] and sha256(data) == e["sha256"], "FILE_HASH_MISMATCH:" + rel)
        role = e.get("role")
        require(role in ROLES | {"raw_object", "rights_evidence", "calendar_evidence", "policy_source"}, "FILE_ROLE")
        if role in ROLES:
            require(role not in roles, "DUPLICATE_FILE_ROLE")
            roles[role] = rel
        files[rel] = data
    require(set(roles) == ROLES, "REQUIRED_FILE_ROLE_MISSING")
    # Extra files, even ignored credentials, are not silently absorbed.
    actual = set()
    for p in root.rglob("*"):
        require(not reparse_point(p), "SYMLINK_NOT_ALLOWED")
        require(not (hasattr(p,"is_junction") and p.is_junction()), "JUNCTION_NOT_ALLOWED")
        if p.is_file():
            actual.add(p.relative_to(root).as_posix())
    require(actual == set(files) | {"manifest.json"}, "UNDECLARED_OR_MISSING_FILE")
    bundle = VerifiedBundle(raw, MappingProxyType(files), MappingProxyType(roles), sha256(raw), MappingProxyType({}))
    report = _validate_graph(bundle, cutoff, generated, utc(now))
    return VerifiedBundle(raw, MappingProxyType(files), MappingProxyType(roles), sha256(raw), MappingProxyType(report))


def _validate_graph(b: VerifiedBundle, cutoff, generated, now) -> dict:
    role_by_path = {e["path"]: e["role"] for e in b.manifest["files"]}
    policy = validate_policy(b.json("policy"))
    require(policy.get("source_contract_path") in b.files
            and role_by_path[policy["source_contract_path"]] == "policy_source", "POLICY_SOURCE_MISSING")
    source_raw = b.files[policy["source_contract_path"]]
    require(sha256(source_raw) == policy["source_contract_sha256"], "POLICY_SOURCE_HASH")
    upstream = json_load(source_raw).get("replay", {})
    require(upstream.get("fill_mode") == "next_close"
            and upstream.get("primary_cost_bps_per_side") == 25
            and upstream.get("cost_sensitivity_bps_per_side") == [25,50,100], "UPSTREAM_POLICY_CONFLICT")
    config = b.json("config")
    require(config.get("schema") == "news-event-audit-config-p0.2", "CONFIG_SCHEMA")
    for k in ("selector_enabled", "portfolio_enabled", "orders_enabled", "historical_training_enabled"):
        require(strict_bool(config.get(k), k) is False, "CONFIG_AUTHORITY")
    require(config.get("scope") == "BOUNDED_LABEL_AUDIT", "CONFIG_SCOPE")

    sessions = validate_sessions(b.rows("sessions"))
    book = ExecutionBook(b.rows("prices"), sessions, as_of=cutoff.isoformat())
    coverage = b.json("coverage")
    require(coverage.get("schema") == "news-event-coverage-p0.2", "COVERAGE_SCHEMA")
    require(coverage.get("scope") == "DECLARED_INPUT_ONLY_NOT_ENTIRE_US_MARKET", "COVERAGE_SCOPE")
    require(coverage.get("calendar_start") == sessions[0]["session"]
            and coverage.get("calendar_end") == sessions[-1]["session"], "CALENDAR_COVERAGE")
    cal_path = coverage.get("calendar_evidence_path")
    require(cal_path in b.files and role_by_path[cal_path] == "calendar_evidence", "CALENDAR_EVIDENCE_MISSING")
    # A byte-identical schedule attachment supports provenance, not an exchange certification.
    require(b.files[cal_path] == b.files[b.roles["sessions"]], "CALENDAR_EVIDENCE_MISMATCH")
    require(coverage.get("historical_universe_complete") is False, "UNSUPPORTED_FULL_UNIVERSE_CLAIM")
    require(type(coverage.get("selection_rule")) is str and bool(coverage["selection_rule"]), "SELECTION_RULE_MISSING")

    rights = b.json("rights")
    require(rights.get("schema") == "news-event-source-rights-p0.2", "RIGHTS_SCHEMA")
    rights_map = {}
    for r in rights.get("sources", []):
        sid = r.get("source_id")
        require(type(sid) is str and bool(sid) and sid not in rights_map, "RIGHTS_SOURCE_DUPLICATE")
        path = r.get("evidence_path")
        require(path in b.files and role_by_path[path] == "rights_evidence", "RIGHTS_EVIDENCE_MISSING")
        for perm in ("read", "store", "derive"):
            require(strict_bool(r.get(perm), perm) is True, "RIGHTS_NOT_GRANTED:"+perm)
        strict_bool(r.get("train"), "train")
        strict_bool(r.get("redistribute"), "redistribute")
        require(timestamp(r.get("reviewed_at"), "rights.review") <= generated, "RIGHTS_REVIEW_CLOCK")
        require(timestamp(r.get("valid_until"), "rights.expiry") > now, "RIGHTS_EXPIRED")
        rights_map[sid] = r
    require(bool(rights_map), "RIGHTS_MISSING")
    for entry in b.manifest["files"]:
        require(entry.get("source_id") in rights_map, "FILE_SOURCE_RIGHTS_MISSING")

    docs = {}
    for d in b.rows("documents"):
        did = d.get("document_id")
        require(type(did) is str and bool(did) and did not in docs, "DOCUMENT_ID")
        rel = d.get("raw_path")
        require(rel in b.files and role_by_path[rel] == "raw_object", "DOCUMENT_RAW_MISSING")
        require(sha256(b.files[rel]) == d.get("raw_sha256"), "DOCUMENT_RAW_HASH")
        require(d.get("source_id") in rights_map, "DOCUMENT_RIGHTS")
        pub = timestamp(d.get("source_public_at"), "document.public")
        ing = timestamp(d.get("ingested_at"), "document.ingested")
        require(pub <= ing <= generated, "DOCUMENT_CLOCK")
        require(d.get("revision_policy") == "IMMUTABLE_PUBLIC_VERSION", "DOCUMENT_REVISION_POLICY")
        u = urlsplit(d.get("source_url", ""))
        require(u.scheme == "https" and bool(u.hostname) and not u.username and not u.password
                and not u.query and not u.fragment, "DOCUMENT_SOURCE_URL")
        docs[did] = d
    require(bool(docs), "DOCUMENTS_MISSING")

    securities: dict[str, list[dict]] = {}
    for s in b.rows("securities"):
        sid = s.get("stable_security_id")
        require(type(sid) is str and bool(sid), "SECURITY_ID")
        require(s.get("listing_country") == "US" and s.get("exchange") in {"XNYS","XNAS","XASE"}, "NON_US_SECURITY")
        require(s.get("instrument") in {"COMMON","ADR","ETF"}, "SECURITY_TYPE")
        require(type(s.get("issuer_id")) is str and bool(s["issuer_id"]), "SECURITY_ISSUER")
        start, end = date.fromisoformat(s["valid_from"]), date.fromisoformat(s["valid_to"])
        require(start <= end, "SECURITY_INTERVAL")
        require(s.get("evidence_document_id") in docs, "SECURITY_EVIDENCE")
        require(timestamp(s.get("known_at"), "security.known") >= utc(docs[s["evidence_document_id"]]["source_public_at"]), "SECURITY_BACKDATED")
        for previous in securities.get(sid, []):
            require(s["valid_to"] < previous["valid_from"] or s["valid_from"] > previous["valid_to"], "SECURITY_INTERVAL_OVERLAP")
        securities.setdefault(sid, []).append(s)
    def at_security(sid, session):
        candidates = [s for s in securities.get(sid, []) if s["valid_from"] <= session <= s["valid_to"]]
        require(len(candidates) == 1, "SECURITY_MAPPING_MISSING")
        return candidates[0]
    for (sid, session), p in book.data.items():
        mapped = at_security(sid, session)
        if sid == policy["benchmark_security_id"]:
            require(mapped["ticker"] == "SPY" and mapped["instrument"] == "ETF", "BENCHMARK_MAPPING")
        if p["status"] == "TERMINAL_LOSS":
            d = docs.get(p.get("terminal_evidence_id"))
            require(d is not None and utc(d["source_public_at"]) <= utc(p["available_at"]), "TERMINAL_SOURCE_EVIDENCE")

    snapshots = b.rows("snapshots")
    keys = set()
    for c in snapshots:
        normalize_event(c)   # Reuse P0-1 strict booleans/US/versions, not legacy coercion.
        key = checkpoint_key(c)
        require(key not in keys, "DUPLICATE_SNAPSHOT")
        keys.add(key)
        decision = utc(c["decision_at"])
        require(c["checkpoint_session"] in book.pos, "SNAPSHOT_CALENDAR")
        first = utc(c.get("first_available_at", c["available_at"]))
        event_pos = bisect_left(book.closes, first)
        require(event_pos < len(book.dates) and event_pos + c["checkpoint"] == book.pos[c["checkpoint_session"]],
                "SNAPSHOT_CHECKPOINT_OFFSET")
        require(book.close(c["checkpoint_session"]) <= decision <= cutoff, "SNAPSHOT_TIME")
        require(utc(c["available_at"]) <= decision, "SNAPSHOT_FUTURE_EVENT")
        expected_origin = "FORWARD_SHADOW" if b.manifest["origin"] == "FORWARD_OBSERVED" else "HISTORICAL_BACKFILL"
        require(c["sample_origin"] == expected_origin, "ORIGIN_LAUNDERING")
        refs = c.get("source_document_ids")
        require(type(refs) is list and bool(refs) and len(refs) == len(set(refs)), "SNAPSHOT_DOCUMENT_REFS")
        for did in refs:
            require(did in docs, "SNAPSHOT_DOCUMENT_MISSING")
            require(utc(docs[did]["source_public_at"]) <= utc(c["available_at"]), "FUTURE_DOCUMENT")
            if b.manifest["origin"] == "FORWARD_OBSERVED":
                require(utc(docs[did]["ingested_at"]) <= decision, "HISTORICAL_RECONSTRUCTION_IS_NOT_FORWARD")
        sec = at_security(c["stable_security_id"], c["checkpoint_session"])
        require(sec["instrument"] in {"COMMON","ADR"}, "CANDIDATE_NOT_COMMON_ADR")
        require(sec["issuer_id"] == c["issuer_id"] and sec["ticker"] == c["security_id"], "SNAPSHOT_SECURITY_MISMATCH")
        require(utc(sec["known_at"]) <= decision, "SECURITY_NOT_KNOWN_AT_DECISION")
        field_times = c.get("feature_available_at", {})
        require(type(field_times) is dict and all(utc(t) <= decision for t in field_times.values()), "FUTURE_FEATURE")
        require(c.get("price_features_available_at") is not None
                and book.close(c["checkpoint_session"]) <= utc(c["price_features_available_at"]) <= decision,
                "PRICE_FEATURE_AVAILABILITY")
        for sid in (c["stable_security_id"], policy["benchmark_security_id"]):
            quote = book.row(sid, c["checkpoint_session"])
            require(quote is not None and quote["status"] == "ACTIVE", "SNAPSHOT_CLOSE_PRICE_MISSING")
            require(utc(quote["available_at"]) <= utc(c["price_features_available_at"]), "SNAPSHOT_PRICE_BACKDATED")
    included = len({event_revision_key(c) for c in snapshots})
    rejected = coverage.get("rejected_events")
    require(type(rejected) is list and all(type(r) is dict and r.get("reason") and r.get("event_id") for r in rejected), "REJECTION_DENOMINATOR")
    require(len({r["event_id"] for r in rejected}) == len(rejected), "DUPLICATE_REJECTION")
    require(type(coverage.get("included_event_security_revisions")) is int
            and coverage["included_event_security_revisions"] == included, "COVERAGE_INCLUDED_COUNT")
    require(type(coverage.get("candidate_count")) is int
            and coverage["candidate_count"] == included + len(rejected), "COVERAGE_DENOMINATOR")
    require(coverage.get("price_row_count") == len(book.data), "COVERAGE_PRICE_COUNT")
    require(coverage.get("document_count") == len(docs), "COVERAGE_DOCUMENT_COUNT")
    return {"status": "BYTE_AND_GRAPH_CHECKED_NOT_AUTHORIZED", "manifest_sha256": b.manifest_sha256,
            "files_verified": len(b.files), "bytes_verified": sum(map(len,b.files.values())),
            "snapshots": len(snapshots), "event_security_revisions": included,
            "price_rows": len(book.data), "documents": len(docs), "rejections": len(rejected),
            "origin": b.manifest["origin"], "selector_weight": 0.0,
            "rights_truth_independently_verified": False, "pit_truth_independently_verified": False,
            "whole_market_coverage_certified": False}


def require_reviewed_receipt(
    b: VerifiedBundle, receipt_bytes: bytes, *, reviewed_registry: dict,
    expected_parent: str | None, now: str,
) -> dict:
    """Only an external, reviewed registry can accept a REAL bounded audit.

    The standalone CLI has an empty registry by default. Neither the input
    bundle nor the receipt may authorize itself. An altered registry requires
    normal repository review; this is not protection against arbitrary code edit.
    """
    r = json_load(receipt_bytes)
    rh = sha256(receipt_bytes)
    require(type(r) is dict, "RECEIPT_OBJECT")
    require(type(reviewed_registry) is dict and reviewed_registry.get("schema") == "news-input-approval-registry-p0.2", "REGISTRY_SCHEMA")
    approvals = reviewed_registry.get("approvals")
    require(type(approvals) is list and all(type(a) is dict for a in approvals), "REGISTRY_APPROVALS")
    matches = [a for a in approvals if a.get("receipt_sha256") == rh]
    require(len(matches) == 1, "RECEIPT_NOT_IN_REVIEWED_REGISTRY")
    a = matches[0]
    require(a.get("revoked") is False, "RECEIPT_REVOKED")
    require(type(a.get("review_evidence")) is str and bool(a["review_evidence"]), "REVIEW_EVIDENCE_REQUIRED")
    require(b.manifest["origin"] != "SYNTHETIC_TEST", "SYNTHETIC_CANNOT_AUTHORIZE_REAL_INPUT")
    require(r.get("schema") == "news-input-review-receipt-p0.2" and r.get("consumer") == CONSUMER, "RECEIPT_CONSUMER")
    require(r.get("manifest_sha256") == b.manifest_sha256 == a.get("manifest_sha256"), "RECEIPT_MANIFEST_BINDING")
    require(r.get("source_commit") == b.manifest["source_commit"], "RECEIPT_CODE_BINDING")
    require(r.get("policy_sha256") == sha256(b.files[b.roles["policy"]]), "RECEIPT_POLICY_BINDING")
    require(r.get("config_sha256") == sha256(b.files[b.roles["config"]]), "RECEIPT_CONFIG_BINDING")
    require(type(r.get("generation")) is int and r["generation"] == b.manifest["generation"], "RECEIPT_GENERATION")
    require(r.get("parent_receipt_sha256") == b.manifest["parent_receipt_sha256"] == expected_parent == a.get("expected_parent"), "RECEIPT_PARENT_BINDING")
    require(timestamp(r.get("reviewed_at"), "receipt.review") >= utc(b.manifest["generated_at"]), "RECEIPT_PRECEDES_DATA")
    require(utc(r["reviewed_at"]) <= utc(now) < timestamp(r.get("valid_until"), "receipt.expiry"), "RECEIPT_CLOCK")
    require(r.get("approved_purpose") == "BOUNDED_LABEL_AUDIT", "RECEIPT_PURPOSE")
    for k in ("rights", "pit", "security_identity", "calendar", "coverage"):
        require(r.get("reviews", {}).get(k) == "VERIFIED_FOR_DECLARED_SCOPE", "RECEIPT_REVIEW:"+k)
    return {"status": "REVIEWED_INPUT_FOR_BOUNDED_AUDIT_ONLY", "receipt_sha256": rh,
            "manifest_sha256": b.manifest_sha256, "authority_evidence": a["review_evidence"],
            "historical_training_allowed": False, "selector_weight": 0.0,
            "parent_chain_fully_restored": False}

"""Evidence-based quality admission, independent of prices and portfolio capital.

This module validates captured evidence and a separately supplied review receipt.
It does NOT establish remote-document authenticity, independently judge semantic
entailment, call an LLM, assign alpha points, or grant trading permission. A review
receipt is trusted caller input, not a cryptographic reviewer authentication.
"""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Any, Mapping
from urllib.parse import unquote

from .data import digest, reject_diagnostic_scores, source_url, timestamp, validate_persistable_sources

METHOD_VERSION = "quality-evidence-v1.1"
AXES = ("technology", "bottleneck", "competition", "demand_sustainability",
        "governance", "management_allocation", "price_expectations")
COMPANY_AXES = AXES[:-1]  # Price evidence cannot erase an assessed business.
CLAIM_FIELDS = {"claim_id", "axis", "segment", "kind", "statement", "required",
                "verdict", "impact", "severity", "rationale", "strongest_bear_case",
                "invalidation_condition", "review_due_at", "evidence"}
SOURCE_FIELDS = {"source_id", "url", "origin_url", "issuer_id", "kind", "content_sha256",
                 "capture_scope", "captured_text", "published_at", "available_from",
                 "first_seen_at", "ingested_at", "supersedes_source_id"}
PACKET_FIELDS = {"schema_version", "security_id", "data_kind", "created_at", "claims", "bindings"}
RECEIPT_FIELDS = {"schema_version", "subject_hash", "review_id", "reviewer", "reviewer_type",
                  "scope", "reviewed_at", "decision"}
HASH = re.compile(r"[0-9a-f]{64}")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}")
SECURITY = re.compile(r"(?:US:[A-Z][A-Z0-9.\-]{0,9}|KR:[0-9]{6})")


def _require(test: bool, code: str) -> None:
    if not test:
        raise ValueError(code)


def _text(value: Any, code: str, limit: int = 8000) -> str:
    _require(isinstance(value, str) and bool(value.strip()) and len(value) <= limit, code)
    return value


def _closed(value: Any, fields: set[str], code: str) -> None:
    _require(isinstance(value, dict) and set(value) == fields, code)


def _identifier(value: Any, code: str) -> str:
    _require(isinstance(value, str) and ID.fullmatch(value) is not None, code)
    return value


def _url(value: Any) -> None:
    _text(value, "source_url_required", 2048)
    _require(not any(c.isspace() or ord(c) < 32 for c in value), "source_url_whitespace")
    source_url(value)
    # Scoped quality contract; this does not silently patch upstream H1.
    decoded = unquote(value)
    _require(not re.search(r"(?i)(?:[;/])(?:j?session[_-]?id|cookie|sid)(?:[=/;])", decoded),
             "source_url_session_credential")


def _role_matches(source: dict, role: str, security_id: str) -> bool:
    """Check every declared role; an issuer capture is not independent evidence.

    Source metadata still requires source-grounding review. This is a consistency
    check, not authentication of whoever supplied the source metadata.
    """
    own_issuer = source["issuer_id"] == security_id
    kind = source["kind"]
    return ((role == "issuer" and own_issuer and kind == "company") or
            (role == "competitor" and not own_issuer and kind == "competitor") or
            (role == "customer" and not own_issuer and kind == "customer") or
            (role == "industry" and not own_issuer and kind in {"independent", "regulator"}))


def _source_errors(source: dict, source_id: str, cutoff: str, data_kind: str) -> list[str]:
    try:
        _closed(source, SOURCE_FIELDS, "source_schema")
        _require(source["source_id"] == source_id, "source_identity")
        _identifier(source_id, "source_id")
        _text(source["issuer_id"], "source_issuer")
        _require(source["kind"] in {"company", "customer", "competitor", "independent", "regulator"}, "source_kind")
        _require(source["capture_scope"] in {"full_document", "excerpt"}, "capture_scope")
        _url(source["url"])
        _url(source["origin_url"])
        validate_persistable_sources(source, real=data_kind == "REAL")
        text = _text(source["captured_text"], "captured_text", 200000)
        _require(isinstance(source["content_sha256"], str) and HASH.fullmatch(source["content_sha256"]) is not None,
                 "source_hash_format")
        _require(hashlib.sha256(text.encode("utf-8")).hexdigest() == source["content_sha256"], "source_hash_mismatch")
        available, seen, ingested, cut = [timestamp(x) for x in
            (source["available_from"], source["first_seen_at"], source["ingested_at"], cutoff)]
        _require(available <= seen <= ingested <= cut, "source_time_order_or_future")
        if source["published_at"] is not None:
            _require(timestamp(source["published_at"]) <= available, "source_publication_order")
        if source["supersedes_source_id"] is not None:
            _identifier(source["supersedes_source_id"], "superseded_source_id")
            _require(source["supersedes_source_id"] != source_id, "source_self_supersession")
    except (ValueError, TypeError, KeyError):
        # Controlled codes only: no raw provider response or arbitrary exception text.
        return ["invalid_source"]
    return []


def review_subject_hash(packet: dict, corpus: Mapping[str, dict]) -> str:
    """Bind review to statements, business assumptions, and captured source identity.

    Retrieval timestamps remain independently checked but a repeated byte-identical
    fetch is not a business improvement. first_seen_at is retained in the binding.
    """
    sources = {sid: ({k: v for k, v in src.items() if k not in {"captured_text", "ingested_at"}}
                     if isinstance(src, dict) else {"invalid_source_value_hash": digest(src)})
               for sid, src in sorted(corpus.items())}
    return digest({"method": METHOD_VERSION, "packet": packet, "sources": sources})


def semantic_hash(packet: dict, corpus: Mapping[str, dict]) -> str:
    claims = [{k: v for k, v in claim.items() if k != "review_due_at"} for claim in packet.get("claims", [])]
    sources = {sid: ({k: src.get(k) for k in ("origin_url", "content_sha256", "supersedes_source_id")}
                     if isinstance(src, dict) else {"invalid_source_value_hash": digest(src)})
               for sid, src in sorted(corpus.items())}
    return digest({"security_id": packet.get("security_id"), "data_kind": packet.get("data_kind"),
                   "claims": claims, "bindings": packet.get("bindings", []), "sources": sources})


def assess_quality(packet: Any, corpus: Any, receipt: Any, *, security_id: str,
                   data_kind: str, cutoff: str) -> dict:
    """Return per-claim stages and business assessment, never a return probability.

    Source matching means fidelity to the identified captured bytes, NOT an
    independent verification of the issuer's claim. Classification/entailment and
    adequate coverage require an explicit external review receipt. Malformed core
    inputs cannot pass; invalid optional evidence cannot erase unrelated claims.
    """
    out = {"schema_version": "research-quality-assessment-v1", "method_version": METHOD_VERSION,
           "security_id": security_id, "data_kind": data_kind, "decision_cutoff": cutoff,
           "company_assessment": "unverified", "claims": [], "axes": {}, "blockers": [],
           "schema_valid": False, "review_receipt_valid": False, "reviewer_type": None,
           "remote_document_authenticity_verified": False, "independent_review_completed": False,
           "orders_allowed": False, "oos_validated": False}
    try:
        _require(isinstance(security_id, str) and SECURITY.fullmatch(security_id) is not None, "security_identity")
        _require(data_kind in {"REAL", "SYNTHETIC"}, "data_kind")
        cut = timestamp(cutoff)
        _closed(packet, PACKET_FIELDS, "packet_schema")
        _require(packet["schema_version"] == "research-quality-input-v1", "packet_version")
        _require(packet["security_id"] == security_id and packet["data_kind"] == data_kind, "packet_identity")
        _require(timestamp(packet["created_at"]) <= cut, "packet_after_cutoff")
        _require(isinstance(packet["claims"], list) and 0 < len(packet["claims"]) <= 128, "claims_required")
        _require(isinstance(packet["bindings"], list) and len(packet["bindings"]) <= 128, "bindings_schema")
        _require(isinstance(corpus, dict) and len(corpus) <= 128, "corpus_schema")
        _require(all(isinstance(sid, str) and ID.fullmatch(sid) for sid in corpus), "corpus_source_id")
        digest(corpus)  # Reject non-JSON/non-finite source metadata before review hashing.
        reject_diagnostic_scores(packet)
        validate_persistable_sources(packet, real=data_kind == "REAL")
        # Enforce closed/typed claims before hashing a review subject.
        ids = set()
        for claim in packet["claims"]:
            _closed(claim, CLAIM_FIELDS, "claim_schema")
            cid = _identifier(claim["claim_id"], "claim_id")
            _require(cid not in ids, "duplicate_claim_id")
            ids.add(cid)
            _require(claim["axis"] in AXES, "claim_axis")
            _require(type(claim["required"]) is bool, "claim_required_type")
            _require(claim["kind"] in {"fact", "inference", "scenario_assumption"}, "claim_kind")
            _require(claim["verdict"] in {"supported", "mixed", "contradicted", "unverified"}, "claim_verdict")
            _require(claim["impact"] in {"favorable", "adverse", "unknown"}, "claim_impact")
            _require(claim["severity"] in {"ordinary", "critical"}, "claim_severity")
            for field in ("segment", "statement", "rationale", "strongest_bear_case", "invalidation_condition"):
                _text(claim[field], "claim_text_required")
            timestamp(claim["review_due_at"])
            _require(isinstance(claim["evidence"], list) and len(claim["evidence"]) <= 32, "evidence_schema")
            for ev in claim["evidence"]:
                _closed(ev, {"source_id", "relation", "role", "quote", "locator", "content_sha256"}, "evidence_schema")
                _identifier(ev["source_id"], "evidence_source_id")
                _require(ev["relation"] in {"support", "oppose"}, "evidence_relation")
                _require(ev["role"] in {"issuer", "competitor", "customer", "industry"}, "evidence_role")
                _text(ev["quote"], "evidence_quote", 4000)
                _text(ev["locator"], "evidence_locator", 1000)
                _require(isinstance(ev["content_sha256"], str) and HASH.fullmatch(ev["content_sha256"]) is not None,
                         "evidence_hash")
        out["schema_valid"] = True
    except (ValueError, KeyError, TypeError):
        out["blockers"] = ["quality_schema_or_identity_invalid"]
        return out

    source_errors = {sid: _source_errors(src, sid, cutoff, data_kind) for sid, src in corpus.items()}
    superseded = set()
    for sid, src in corpus.items():
        if not source_errors[sid] and src["supersedes_source_id"]:
            old = corpus.get(src["supersedes_source_id"])
            if isinstance(old, dict) and old.get("issuer_id") == src["issuer_id"]:
                superseded.add(src["supersedes_source_id"])
    try:
        subject = review_subject_hash(packet, corpus)
        out["review_subject_hash"] = subject
        out["semantic_hash"] = semantic_hash(packet, corpus)
        _closed(receipt, RECEIPT_FIELDS, "review_receipt_schema")
        _require(receipt["schema_version"] == "quality-review-receipt-v1", "review_receipt_version")
        _require(receipt["subject_hash"] == subject, "review_subject_changed")
        _identifier(receipt["review_id"], "review_id")
        _text(receipt["reviewer"], "reviewer")
        _require(receipt["reviewer_type"] in {"human", "model"}, "reviewer_type")
        _require(receipt["scope"] == "claim_and_axis_sufficiency", "review_scope")
        reviewed = timestamp(receipt["reviewed_at"])
        _require(timestamp(packet["created_at"]) <= reviewed <= cut, "review_time")
        _require(all(timestamp(src["first_seen_at"]) <= reviewed for sid, src in corpus.items() if not source_errors[sid]),
                 "review_before_source_observation")
        _require(receipt["decision"] == "accepted", "review_not_accepted")
        out["review_receipt_valid"] = True
        out["reviewer_type"] = receipt["reviewer_type"]
    except (ValueError, TypeError, KeyError):
        out["blockers"].append("review_receipt_missing_or_invalid")

    for claim in packet["claims"]:
        cid = claim["claim_id"]
        errors, support, oppose = [], set(), set()
        for ev in claim["evidence"]:
            sid = ev["source_id"]
            src = corpus.get(sid)
            if src is None:
                errors.append("source_missing")
            elif source_errors.get(sid) or sid in superseded:
                errors.append("source_invalid_or_superseded")
            elif not _role_matches(src, ev["role"], security_id):
                errors.append("source_issuer_role_mismatch")
            elif ev["content_sha256"] != src["content_sha256"] or ev["quote"] not in src["captured_text"]:
                errors.append("quote_or_hash_mismatch")
            else:
                (support if ev["relation"] == "support" else oppose).add(src["origin_url"])
        source_match = bool(support or oppose) and not errors
        declared = claim["verdict"]
        if timestamp(claim["review_due_at"]) < cut:
            errors.append("review_expired")
        if declared == "supported" and (not support or oppose):
            errors.append("unsupported_or_conflicting_support")
        if declared == "contradicted" and (not oppose or support):
            errors.append("unresolved_contradiction")
        if declared == "mixed" and not (support and oppose):
            errors.append("mixed_requires_both_sides")
        effective = declared if source_match and out["review_receipt_valid"] and not errors else "unverified"
        out["claims"].append({"claim_id": cid, "axis": claim["axis"], "required": claim["required"],
                              "kind": claim["kind"], "impact": claim["impact"], "severity": claim["severity"],
                              "declared_status": declared, "effective_status": effective,
                              "source_match": source_match, "supporting_origins": len(support),
                              "opposing_origins": len(oppose), "blockers": sorted(set(errors)),
                              "rationale": claim["rationale"], "strongest_bear_case": claim["strongest_bear_case"],
                              "invalidation_condition": claim["invalidation_condition"]})
    for axis in AXES:
        rows = [c for c in out["claims"] if c["axis"] == axis and c["required"]]
        statuses = {c["effective_status"] for c in rows}
        out["axes"][axis] = ("unverified" if not rows or "unverified" in statuses else
                             "supported" if statuses == {"supported"} else "mixed")
    critical = any(c["severity"] == "critical" and c["impact"] == "adverse" and
                   c["effective_status"] == "supported" for c in out["claims"])
    incomplete = any(out["axes"][a] == "unverified" for a in COMPANY_AXES)
    uncertain = any(out["axes"][a] != "supported" for a in COMPANY_AXES) or any(
        c["required"] and c["axis"] in COMPANY_AXES and c["impact"] != "favorable" for c in out["claims"])
    out["company_assessment"] = "fail" if critical else "unverified" if incomplete else "uncertain" if uncertain else "pass"
    out["critical_adverse_claim"] = critical
    out["source_matched_claims"] = sum(c["source_match"] for c in out["claims"])
    out["reviewed_claims"] = sum(c["effective_status"] != "unverified" for c in out["claims"])
    out["core_company_axes_complete"] = not incomplete
    # Even exact captured quotes plus a model receipt do not constitute an
    # independent review or historical-PIT/OOS/investment-performance validation.
    return out


def compare_quality(previous: dict, current: dict) -> dict:
    """Attribute quality changes without assigning a return or rank increment."""
    _require(previous.get("security_id") == current.get("security_id"), "comparison_security")
    if previous.get("semantic_hash") == current.get("semantic_hash") and current.get("semantic_hash"):
        reason = "no_business_evidence_change"
    else:
        reason = "business_evidence_changed_requires_review"
    old = {c["claim_id"]: c for c in previous.get("claims", [])}
    new = {c["claim_id"]: c for c in current.get("claims", [])}
    return {"reason": reason,
            "added_claim_ids": sorted(set(new) - set(old)),
            "removed_claim_ids": sorted(set(old) - set(new)),
            "status_changed_claim_ids": sorted(k for k in old.keys() & new.keys()
                                                if old[k]["effective_status"] != new[k]["effective_status"]),
            "company_before": previous.get("company_assessment"), "company_after": current.get("company_assessment"),
            "numeric_alpha_added": False}

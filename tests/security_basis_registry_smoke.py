#!/usr/bin/env python3
"""Offline fail-closed contract for reviewed COMMON/ADR security-basis evidence."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_security_basis_registry import (
    PARTIAL,
    READY,
    build_registry,
)


RAW: dict[tuple[str, str], bytes] = {}


def resolver(artifact_id: str, sha256: str) -> bytes:
    return RAW[(artifact_id, sha256)]


def raw_ref(artifact_id: str, payload: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(payload).hexdigest()
    RAW[(artifact_id, digest)] = payload
    return artifact_id, digest


def identity(
    security_id: str,
    ticker: str,
    *,
    instrument: str = "COMMON",
    available_at: str = "2026-09-18T21:00:00Z",
) -> dict:
    return {
        "security_id": security_id,
        "issuer_id": "ISSUER:" + ticker,
        "ticker": ticker,
        "instrument": instrument,
        "currency": "USD",
        "available_at": available_at,
        "identity_verified": True,
        "research_eligible": True,
    }


def proof(
    *,
    adr: bool = False,
    corporate_basis: str = "SPLIT_AND_DIVIDEND_ADJUSTED_TOTAL_RETURN",
    corporate_available_at: str = "2026-09-18T21:30:00Z",
    prefix: str = "AAA",
) -> dict:
    ca_id, ca_sha = raw_ref(f"RAW:{prefix}:CA", f"corporate-{prefix}".encode())
    value = {
        "corporate_action": {
            "verified": True,
            "review_status": "approved",
            "exact_available_from": True,
            "available_at": corporate_available_at,
            "source_url": "https://example.test/price-basis",
            "source_artifact_id": ca_id,
            "source_sha256": ca_sha,
            "basis": corporate_basis,
        }
    }
    if adr:
        adr_id, adr_sha = raw_ref(f"RAW:{prefix}:ADR", f"adr-{prefix}".encode())
        value["adr_share_basis"] = {
            "verified": True,
            "review_status": "approved",
            "exact_available_from": True,
            "available_at": "2026-09-18T21:40:00Z",
            "source_url": "https://example.test/adr-basis",
            "source_artifact_id": adr_id,
            "source_sha256": adr_sha,
            "adr_ratio": 5,
            "underlying_currency": "TWD",
        }
    return value

def test_ready_common_and_adr() -> None:
    identities = {
        "securities": [
            identity("SECURITY:AAA", "AAA"),
            identity("SECURITY:TSM", "TSM", instrument="ADR"),
        ]
    }
    evidence = {
        "evidence": [
            {"security_id": "SECURITY:AAA", **proof(prefix="AAA")},
            {"security_id": "SECURITY:TSM", **proof(adr=True, prefix="TSM")},
        ]
    }
    out = build_registry(identities, evidence, "2026-09-18T22:30:00Z", resolver)
    assert out["status"] == READY
    assert out["ready_security_count"] == 2
    tsm = next(row for row in out["securities"] if row["ticker"] == "TSM")
    assert tsm["adr_share_basis_verified"] is True
    assert tsm["adr_ratio"] == 5.0
    assert tsm["underlying_currency"] == "TWD"
    assert tsm["corporate_action_source_artifact_id"] == "RAW:TSM:CA"
    assert tsm["adr_source_artifact_id"] == "RAW:TSM:ADR"


def test_missing_adr_basis_preserves_but_blocks_row() -> None:
    identities = {
        "securities": [
            identity("SECURITY:AAA", "AAA"),
            identity("SECURITY:TSM", "TSM", instrument="ADR"),
        ]
    }
    evidence = {
        "evidence": [
            {"security_id": "SECURITY:AAA", **proof()},
            {"security_id": "SECURITY:TSM", **proof()},
        ]
    }
    out = build_registry(identities, evidence, "2026-09-18T22:30:00Z", resolver)
    assert out["status"] == PARTIAL
    tsm = next(row for row in out["securities"] if row["ticker"] == "TSM")
    assert "adr_share_basis_evidence_missing" in tsm["basis_blockers"]
    assert tsm["adr_ratio"] is None


def test_future_and_raw_evidence_fail_closed() -> None:
    identities = {"securities": [identity("SECURITY:AAA", "AAA")]}
    future = {
        "evidence": [{
            "security_id": "SECURITY:AAA",
            **proof(corporate_available_at="2026-09-19T00:00:00Z"),
        }]
    }
    out = build_registry(identities, future, "2026-09-18T22:30:00Z", resolver)
    assert "corporate_action_future_availability" in out["securities"][0]["basis_blockers"]

    raw = {
        "evidence": [{
            "security_id": "SECURITY:AAA",
            **proof(corporate_basis="RAW"),
        }]
    }
    out = build_registry(identities, raw, "2026-09-18T22:30:00Z", resolver)
    assert "corporate_action_basis_unverified" in out["securities"][0]["basis_blockers"]


def test_duplicate_identity_and_orphan_evidence_fail_closed() -> None:
    duplicate = {
        "securities": [
            identity("SECURITY:AAA", "AAA"),
            identity("SECURITY:BBB", "AAA"),
        ]
    }
    try:
        build_registry(duplicate, {"evidence": []}, "2026-09-18T22:30:00Z", resolver)
    except ValueError as exc:
        assert "ticker_not_one_to_one" in str(exc)
    else:
        raise AssertionError("duplicate ticker identity was accepted")

    identities = {"securities": [identity("SECURITY:AAA", "AAA")]}
    orphan = {"evidence": [{"security_id": "SECURITY:ZZZ", **proof()}]}
    try:
        build_registry(identities, orphan, "2026-09-18T22:30:00Z", resolver)
    except ValueError as exc:
        assert "unknown_security_id" in str(exc)
    else:
        raise AssertionError("orphan evidence was accepted")


def test_tampered_corporate_source_blocks_row() -> None:
    p = proof(prefix="AAA")
    row = p["corporate_action"]
    RAW[(row["source_artifact_id"], row["source_sha256"])] = b"tampered"
    out = build_registry(
        {"securities": [identity("SECURITY:AAA", "AAA")]},
        {"evidence": [{"security_id": "SECURITY:AAA", **p}]},
        "2026-09-18T22:30:00Z",
        resolver,
    )
    assert out["status"] == PARTIAL
    assert "corporate_action_raw_evidence_hash_mismatch" in out["securities"][0]["basis_blockers"]


def test_missing_source_blocks_row() -> None:
    p = proof(prefix="AAA")
    row = p["corporate_action"]
    RAW.pop((row["source_artifact_id"], row["source_sha256"]))
    out = build_registry(
        {"securities": [identity("SECURITY:AAA", "AAA")]},
        {"evidence": [{"security_id": "SECURITY:AAA", **p}]},
        "2026-09-18T22:30:00Z",
        resolver,
    )
    assert "corporate_action_raw_evidence_unavailable" in out["securities"][0]["basis_blockers"]


def test_adr_source_is_independently_hash_bound() -> None:
    p = proof(adr=True, prefix="TSM")
    row = p["adr_share_basis"]
    RAW[(row["source_artifact_id"], row["source_sha256"])] = b"tampered-adr"
    out = build_registry(
        {"securities": [identity("SECURITY:TSM", "TSM", instrument="ADR")]},
        {"evidence": [{"security_id": "SECURITY:TSM", **p}]},
        "2026-09-18T22:30:00Z",
        resolver,
    )
    assert "adr_share_basis_raw_evidence_hash_mismatch" in out["securities"][0]["basis_blockers"]
    assert out["securities"][0]["adr_ratio"] is None


def test_malformed_artifact_id_fails_closed() -> None:
    p = proof(prefix="AAA")
    p["corporate_action"]["source_artifact_id"] = " ../bad"
    out = build_registry(
        {"securities": [identity("SECURITY:AAA", "AAA")]},
        {"evidence": [{"security_id": "SECURITY:AAA", **p}]},
        "2026-09-18T22:30:00Z",
        resolver,
    )
    assert "corporate_action_source_artifact_id_invalid" in out["securities"][0]["basis_blockers"]


def test_missing_resolver_is_build_level_failure() -> None:
    try:
        build_registry(
            {"securities": [identity("SECURITY:AAA", "AAA")]},
            {"evidence": []},
            "2026-09-18T22:30:00Z",
            None,  # type: ignore[arg-type]
        )
    except ValueError as exc:
        assert str(exc) == "raw_resolver_required"
    else:
        raise AssertionError("missing resolver accepted")


if __name__ == "__main__":
    tests = [
        test_ready_common_and_adr,
        test_missing_adr_basis_preserves_but_blocks_row,
        test_future_and_raw_evidence_fail_closed,
        test_duplicate_identity_and_orphan_evidence_fail_closed,
        test_tampered_corporate_source_blocks_row,
        test_missing_source_blocks_row,
        test_adr_source_is_independently_hash_bound,
        test_malformed_artifact_id_fails_closed,
        test_missing_resolver_is_build_level_failure,
    ]
    for fn in tests:
        RAW.clear()
        fn()
    print("security basis provenance smoke: PASS")

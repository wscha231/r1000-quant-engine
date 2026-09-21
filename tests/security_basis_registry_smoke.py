#!/usr/bin/env python3
"""Offline fail-closed contract for reviewed COMMON/ADR security-basis evidence."""
from __future__ import annotations

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
) -> dict:
    value = {
        "corporate_action": {
            "verified": True,
            "review_status": "approved",
            "exact_available_from": True,
            "available_at": corporate_available_at,
            "source_url": "https://example.test/price-basis",
            "source_sha256": "a" * 64,
            "basis": corporate_basis,
        }
    }
    if adr:
        value["adr_share_basis"] = {
            "verified": True,
            "review_status": "approved",
            "exact_available_from": True,
            "available_at": "2026-09-18T21:40:00Z",
            "source_url": "https://example.test/adr-basis",
            "source_sha256": "b" * 64,
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
            {"security_id": "SECURITY:AAA", **proof()},
            {"security_id": "SECURITY:TSM", **proof(adr=True)},
        ]
    }
    out = build_registry(identities, evidence, "2026-09-18T22:30:00Z")
    assert out["status"] == READY
    assert out["ready_security_count"] == 2
    tsm = next(row for row in out["securities"] if row["ticker"] == "TSM")
    assert tsm["adr_share_basis_verified"] is True
    assert tsm["adr_ratio"] == 5.0
    assert tsm["underlying_currency"] == "TWD"


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
    out = build_registry(identities, evidence, "2026-09-18T22:30:00Z")
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
    out = build_registry(identities, future, "2026-09-18T22:30:00Z")
    assert "corporate_action_future_availability" in out["securities"][0]["basis_blockers"]

    raw = {
        "evidence": [{
            "security_id": "SECURITY:AAA",
            **proof(corporate_basis="RAW"),
        }]
    }
    out = build_registry(identities, raw, "2026-09-18T22:30:00Z")
    assert "corporate_action_basis_unverified" in out["securities"][0]["basis_blockers"]


def test_duplicate_identity_and_orphan_evidence_fail_closed() -> None:
    duplicate = {
        "securities": [
            identity("SECURITY:AAA", "AAA"),
            identity("SECURITY:BBB", "AAA"),
        ]
    }
    try:
        build_registry(duplicate, {"evidence": []}, "2026-09-18T22:30:00Z")
    except ValueError as exc:
        assert "ticker_not_one_to_one" in str(exc)
    else:
        raise AssertionError("duplicate ticker identity was accepted")

    identities = {"securities": [identity("SECURITY:AAA", "AAA")]}
    orphan = {"evidence": [{"security_id": "SECURITY:ZZZ", **proof()}]}
    try:
        build_registry(identities, orphan, "2026-09-18T22:30:00Z")
    except ValueError as exc:
        assert "unknown_security_id" in str(exc)
    else:
        raise AssertionError("orphan evidence was accepted")


if __name__ == "__main__":
    test_ready_common_and_adr()
    test_missing_adr_basis_preserves_but_blocks_row()
    test_future_and_raw_evidence_fail_closed()
    test_duplicate_identity_and_orphan_evidence_fail_closed()
    print("security basis registry smoke: PASS")

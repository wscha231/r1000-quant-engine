#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verify_sec_13f_publication import verify  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_sec_and_smart_publications_bind_identity_and_hashes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        index = root / "index.parquet"
        holdings = root / "holdings.parquet"
        form4 = root / "form4.csv"
        etf = root / "etf.csv"
        index.write_bytes(b"index")
        holdings.write_bytes(b"holdings")
        form4.write_bytes(b"form4")
        etf.write_bytes(b"etf")
        freshness = {
            "freshness_ready": True,
            "parsed_holdings_required": True,
            "filings_index_sha256": digest(index),
            "holdings_sha256": digest(holdings),
            "weighted_evidence_required": True,
            "weighted_evidence_sha256": {
                "form4": digest(form4),
                "etf": digest(etf),
            },
            "source_identity": {
                "workflow_run_id": "123",
                "head_sha": "a" * 40,
                "head_branch": "master",
            },
        }
        ready = verify(
            kind="sec",
            manifest=freshness,
            filings_index=index,
            holdings=holdings,
            form4=form4,
            etf=etf,
            expected_run_id="123",
            expected_head_sha="a" * 40,
            expected_head_branch="master",
        )
        assert ready["status"] == "ready"
        smart = {
            "publication_identity": {
                "workflow_run_id": "456",
                "head_sha": "b" * 40,
                "head_branch": "master",
            },
            "13f_freshness": freshness,
            "evidence_sha256": {
                "form4": digest(form4),
                "etf": digest(etf),
            },
        }
        blocked = verify(
            kind="smart",
            manifest=smart,
            filings_index=index,
            holdings=holdings,
            form4=form4,
            etf=etf,
            expected_run_id="456",
            expected_head_sha="c" * 40,
            expected_head_branch="master",
        )
        assert blocked["status"] == "blocked"
        assert "identity_mismatch:head_sha" in blocked["failures"]
        etf.write_bytes(b"tampered")
        tampered = verify(
            kind="smart",
            manifest=smart,
            filings_index=index,
            holdings=holdings,
            form4=form4,
            etf=etf,
            expected_run_id="456",
            expected_head_sha="b" * 40,
            expected_head_branch="master",
        )
        assert tampered["status"] == "blocked"
        assert "etf_evidence_sha256_mismatch" in tampered["failures"]


if __name__ == "__main__":
    test_sec_and_smart_publications_bind_identity_and_hashes()
    print("sec_13f_publication_verification_smoke: PASS")

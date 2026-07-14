#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_sec_guidance_goldset_packet import build_packet  # noqa: E402


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    contract = json.loads(
        (REPO_ROOT / "docs/run287_sec_guidance_goldset_contract.json").read_text(encoding="utf-8")
    )
    contract["expected_filing_count"] = 2
    contract_path = root / "goldset_contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    scout_contract_path = REPO_ROOT / "docs/run287_sec_management_guidance_scout_contract.json"
    scout_output = root / "scout"
    cache = root / "cache"
    scout_output.mkdir()

    rows = []
    candidates = []
    for idx, ticker in enumerate(("ADR1", "ADR2"), start=1):
        accession = f"000000000{idx}-24-00000{idx}"
        raw = (
            "<SEC-DOCUMENT><ACCEPTANCE-DATETIME>20240501161500"
            "<DOCUMENT><TYPE>EX-99.1\n<TEXT><html><body>"
            + (
                "Management expects adjusted EPS between $4.10 and $4.30 for fiscal 2025."
                if ticker == "ADR1"
                else "The company reported historical results for the quarter."
            )
            + "</body></html></TEXT></DOCUMENT></SEC-DOCUMENT>"
        ).encode("utf-8")
        cache_path = cache / ticker / f"{accession.replace('-', '')}.txt"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(raw)
        rows.append(
            {
                "ticker": ticker,
                "cik10": f"{idx:010d}",
                "accession_number": accession,
                "form_type": "6-K",
                "filing_date": "2024-05-01",
                "accepted_at": "2024-05-01T20:15:00+00:00",
                "source_url": f"https://www.sec.gov/Archives/{accession}.txt",
                "cache_path": str(cache_path),
                "source_sha256": sha256(raw),
                "download_state": "cached",
                "download_success": True,
                "raw_header_accepted_at": "2024-05-01T20:15:00+00:00",
                "raw_header_exact_match": True,
            }
        )
        if ticker == "ADR1":
            candidates.append(
                {
                    "candidate_id": "candidate-1",
                    "ticker": ticker,
                    "accession_number": accession,
                    "document_type": "EX-99.1",
                    "metrics": "eps",
                    "source_sha256": sha256(raw),
                    "snippet": "Management expects adjusted EPS between $4.10 and $4.30.",
                }
            )

    pd.DataFrame(rows).to_csv(scout_output / "download_log.csv", index=False)
    pd.DataFrame(candidates).to_csv(scout_output / "guidance_candidates.csv", index=False)
    summary = {
        "schema_version": contract["source_scout_schema_version"],
        "status": "READY_FOR_MANUAL_SCHEMA_REVIEW",
        "exact_acceptance_ratio": 1.0,
        "raw_header_acceptance_match_ratio": 1.0,
        "quarantined_missing_acceptance_count": 0,
        "raw_header_acceptance_mismatch_count": 0,
        "return_join_allowed": False,
        "portfolio_ab_allowed": False,
        "portfolio_mutation_allowed": False,
        "fullrun_allowed": False,
        "production_allowed": False,
        "live_trading_allowed": False,
    }
    (scout_output / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return contract_path, scout_contract_path, scout_output, cache


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        contract, scout_contract, scout_output, cache = write_fixture(root)
        output = root / "packet"
        summary = build_packet(
            contract_path=contract,
            scout_contract_path=scout_contract,
            scout_output=scout_output,
            cache_dir=cache,
            output_dir=output,
        )
        assert summary["status"] == "READY_FOR_DUAL_REVIEW", summary
        assert summary["filing_count"] == 2
        assert summary["heuristic_candidate_filing_count"] == 1
        assert summary["heuristic_negative_filing_count"] == 1
        assert summary["return_join_allowed"] is False
        manifest = pd.read_csv(output / "review_manifest.csv")
        assert len(manifest) == 2
        assert manifest["source_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
        assert set(manifest["heuristic_candidate_detected"].astype(bool)) == {True, False}
        for reviewer in ("reviewer_a", "reviewer_b"):
            labels = pd.read_csv(output / f"filing_labels_{reviewer}.csv").fillna("")
            assert len(labels) == 2
            assert set(labels["reviewer_id"]) == {reviewer}
            assert (labels["filing_class"] == "").all()
            assert (labels["precision_label"] == "").all()
            components = pd.read_csv(output / f"component_labels_{reviewer}.csv")
            assert components.empty
        review_text = (output / manifest.iloc[0]["review_text_path"]).resolve()
        if not review_text.exists():
            review_text = REPO_ROOT / manifest.iloc[0]["review_text_path"]
        assert review_text.exists()

        downloads = pd.read_csv(scout_output / "download_log.csv")
        downloads.loc[0, "source_sha256"] = "0" * 64
        downloads.to_csv(scout_output / "download_log.csv", index=False)
        try:
            build_packet(
                contract_path=contract,
                scout_contract_path=scout_contract,
                scout_output=scout_output,
                cache_dir=cache,
                output_dir=root / "blocked_packet",
            )
        except ValueError as exc:
            assert "source_hash_mismatch" in str(exc)
        else:
            raise AssertionError("source hash mismatch must block packet creation")

    print("sec_guidance_goldset_packet_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

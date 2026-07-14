#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_sec_management_guidance_scout import guidance_candidates, run  # noqa: E402


ACCESSIONS = {
    "ADR1": "0000000001-24-000001",
    "ADR2": "0000000002-24-000002",
    "ADR3": "0000000003-24-000003",
}


def write_fixture(root: Path, *, missing_acceptance: bool = False) -> argparse.Namespace:
    sample = pd.DataFrame(
        [
            {
                "request_row_id": f"ACTIVE_{idx:03d}",
                "ticker": ticker,
                "is_delisted": False,
                "is_adr_global_listing": True,
            }
            for idx, ticker in enumerate(ACCESSIONS, start=1)
        ]
    )
    sample_path = root / "sample.csv"
    sample.to_csv(sample_path, index=False)

    filings = []
    cache = root / "cache"
    for idx, (ticker, accession) in enumerate(ACCESSIONS.items(), start=1):
        filings.append(
            {
                "ticker": ticker,
                "cik10": f"{idx:010d}",
                "accession_number": accession,
                "form_type": "6-K",
                "filing_date": "2024-05-01",
                "accepted_at": "" if missing_acceptance and ticker == "ADR1" else "2024-05-01T20:15:00+00:00",
            }
        )
        raw = (
            "<SEC-DOCUMENT><DOCUMENT><TYPE>EX-99.1\n<TEXT><html><body>"
            "The company raises its fiscal 2025 outlook and expects revenue between "
            "$100 million and $110 million."
            "</body></html></TEXT></DOCUMENT></SEC-DOCUMENT>"
        )
        path = cache / ticker / f"{accession.replace('-', '')}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
    index_path = root / "filings.csv"
    pd.DataFrame(filings).to_csv(index_path, index=False)

    return argparse.Namespace(
        contract=str(REPO_ROOT / "docs/run287_sec_management_guidance_scout_contract.json"),
        sample_request=str(sample_path),
        filings_index=[str(index_path)],
        output_dir=str(root / "output"),
        cache_dir=str(cache),
        ticker_limit=3,
        max_filings_per_ticker=1,
        history_start="2019-06-03",
        history_end="2026-07-10",
        user_agent="fixture test@example.com",
        sleep=0.0,
        offline=True,
    )


def main() -> int:
    direct = guidance_candidates(
        "Management expects adjusted EPS between $4.10 and $4.30 for fiscal 2027."
    )
    assert direct and direct[0]["metrics"] == "eps"
    boilerplate = guidance_candidates(
        "Forward-looking statements include projections and expectations involving revenue of $1 billion."
    )
    assert boilerplate == []

    with tempfile.TemporaryDirectory() as tmp:
        args = write_fixture(Path(tmp))
        summary = run(args)
        assert summary["status"] == "READY_FOR_MANUAL_SCHEMA_REVIEW", summary
        assert summary["candidate_count"] == 3
        assert summary["candidate_filing_count"] == 3
        assert summary["candidate_ticker_count"] == 3
        assert summary["exact_acceptance_ratio"] == 1.0
        assert summary["provider_email_required"] is False
        assert summary["api_key_required"] is False
        assert summary["historical_consensus_requirement_satisfied"] is False
        assert summary["return_join_allowed"] is False
        assert summary["portfolio_ab_allowed"] is False
        assert summary["fullrun_allowed"] is False
        assert summary["production_allowed"] is False
        assert summary["live_trading_allowed"] is False
        candidates = pd.read_csv(Path(args.output_dir) / "guidance_candidates.csv")
        assert set(candidates["available_from"]) == {"2024-05-01T20:15:00+00:00"}
        assert candidates["source_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()

    with tempfile.TemporaryDirectory() as tmp:
        args = write_fixture(Path(tmp), missing_acceptance=True)
        summary = run(args)
        assert summary["status"] == "BLOCKED_PIT", summary
        assert summary["exact_acceptance_ratio"] < 1.0

    print("sec_management_guidance_scout_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

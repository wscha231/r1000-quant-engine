#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.fetch_run287_recent_companyfacts import build  # noqa: E402


def test_single_statement_fetch_and_isolated_index() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        delta = root / "delta.parquet"
        pd.DataFrame(
            {
                "ticker": ["DAL"], "cik10": ["0000027904"],
                "accession_number": ["0000027904-26-000031"], "form": ["10-Q"],
                "filing_date": ["2026-07-10"], "accepted_at": ["2026-07-10T16:17:17Z"],
                "available_from": ["2026-07-10T16:17:17Z"], "period_of_report": ["2026-06-30"],
                "primary_document": ["dal.htm"], "filing_url": ["https://example.test/dal"],
                "exact_acceptance": [True],
            }
        ).to_parquet(delta, index=False)
        manifest = root / "delta_manifest.json"
        manifest.write_text(json.dumps({
            "status": "READY_RECENT_SEC_ACCEPTED_DELTA",
            "outputs": {"accepted_time_delta": {"path": str(delta), "sha256": hashlib.sha256(delta.read_bytes()).hexdigest()}},
        }), encoding="utf-8")
        canonical = root / "canonical.parquet"
        pd.DataFrame(columns=["ticker", "cik10", "accession_number", "form_type", "filing_date", "accepted_at", "available_from", "period_of_report", "primary_document", "filing_url", "source", "download_status", "parse_status"]).to_parquet(canonical, index=False)

        def fetcher(_url: str, _ua: str) -> bytes:
            return json.dumps({"cik": 27904, "facts": {}}).encode("utf-8")

        payload = build(argparse.Namespace(
            delta_manifest=str(manifest), canonical_index=str(canonical),
            decision_time_utc="2026-07-14T05:00:00Z", user_agent="Research test@example.org",
            max_network_requests=2, output_dir=str(root / "output"),
        ), fetcher=fetcher)
        assert payload["status"] == "READY_RECENT_COMPANYFACTS_DELTA"
        assert payload["network_requests_executed"] == 1
        combined = pd.read_parquet(root / "output" / "combined_sec_filings_index.parquet")
        assert set(combined["accession_number"]) == {"0000027904-26-000031"}


if __name__ == "__main__":
    test_single_statement_fetch_and_isolated_index()
    print("run287_recent_companyfacts_smoke: PASS")

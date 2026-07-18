#!/usr/bin/env python3
"""Smoke test for the candidate full-history coverage freeze."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.audit_run287_candidate_full_history import build  # noqa: E402


def main() -> int:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "issuer_key": "AAA",
                    "identity_cik10": "0000000001",
                    "in_frozen_universe": False,
                    "price_history_status": "CANONICAL_7Y_PRICE_READY",
                    "price_history_start": "2010-01-01",
                    "price_history_end": "2026-07-14",
                    "price_history_rows": 100,
                    "price_history_authoritative_full_fetch": True,
                    "canonical_7y_price_eligible": True,
                    "sec_route_status": "DOMESTIC_ACCEPTED_TIME_ROUTE",
                    "issuer_sec_proxy_ticker": "",
                    "home_market_filing_backfill_required": False,
                },
                {
                    "ticker": "HHH.KS",
                    "issuer_key": "HHH",
                    "identity_cik10": "",
                    "in_frozen_universe": False,
                    "price_history_status": "FULL_AVAILABLE_HISTORY_SHORT_LISTING",
                    "price_history_start": "2025-01-01",
                    "price_history_end": "2026-07-14",
                    "price_history_rows": 10,
                    "price_history_authoritative_full_fetch": True,
                    "canonical_7y_price_eligible": False,
                    "sec_route_status": "MISSING_SEC_ACCEPTED_HISTORY",
                    "issuer_sec_proxy_ticker": "HHH",
                    "home_market_filing_backfill_required": True,
                },
            ]
        ).to_csv(root / "audit.csv", index=False)
        (root / "price.json").write_text(
            json.dumps({"status": "completed", "failed_count": 0}), encoding="utf-8"
        )
        pd.DataFrame(
            [{"ticker": "AAA", "accession_number": "a", "accepted_at": "2026-01-01T00:00:00Z"}]
        ).to_parquet(root / "sec.parquet", index=False)
        raw = json.dumps(
            {
                "cik": 1,
                "facts": {
                    "us-gaap": {
                        "Revenue": {"units": {"USD": [{"accn": "a", "val": 1}]}}
                    }
                },
            }
        ).encode("utf-8")
        facts = root / "CIK0000000001.json"
        facts.write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
        (root / "cf_manifest.json").write_text(
            json.dumps(
                {
                    "status": "READY_RESEARCH_ONLY_COMPANYFACTS_HISTORY",
                    "companyfacts_files": [
                        {"cik10": "0000000001", "path": str(facts), "sha256": sha}
                    ],
                }
            ),
            encoding="utf-8",
        )
        with zipfile.ZipFile(root / "companyfacts.zip", "w") as archive:
            archive.writestr("CIK0000000001.json", raw)
        args = argparse.Namespace(
            candidate_audit=str(root / "audit.csv"),
            price_manifest=str(root / "price.json"),
            sec_index=[str(root / "sec.parquet")],
            companyfacts_zip=str(root / "companyfacts.zip"),
            companyfacts_manifest=[str(root / "cf_manifest.json")],
            output_dir=str(root / "out"),
        )
        summary = build(args)
        assert summary["candidate_count"] == 2, summary
        assert summary["full_available_price_history_count"] == 2, summary
        assert summary["canonical_7y_price_eligible_count"] == 1, summary
        assert summary["exact_sec_accepted_ticker_count"] == 1, summary
        assert summary["companyfacts_available_ticker_count"] == 1, summary
        assert summary["companyfacts_gap_count"] == 1, summary
        assert summary["fullrun_executed"] is False, summary
        coverage = pd.read_csv(root / "out" / "candidate_full_history_coverage.csv")
        home = coverage.loc[coverage["ticker"].eq("HHH.KS")].iloc[0]
        assert home["companyfacts_source"] == "ISSUER_SEC_PROXY_ONLY_NOT_HOME_LISTING_SPECIFIC", home
        assert not bool(home["historical_portfolio_evaluation_allowed"]), home

    print("run287 candidate full-history smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

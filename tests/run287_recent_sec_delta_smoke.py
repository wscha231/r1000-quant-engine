#!/usr/bin/env python3
"""Smoke test for the recent accepted-time SEC delta collector."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.collect_run287_recent_sec_delta import build  # noqa: E402


def test_daily_prefilter_and_exact_acceptance_join() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        universe = root / "universe.csv"
        pd.DataFrame({"ticker": ["AAA", "BBB"]}).to_csv(universe, index=False)
        company = root / "company_tickers.json"
        company.write_text(
            json.dumps({"0": {"ticker": "AAA", "cik_str": 1234}}), encoding="utf-8"
        )
        identity = root / "identity.parquet"
        pd.DataFrame({"ticker": ["AAA"], "cik10": ["0000001234"]}).to_parquet(
            identity, index=False
        )
        master = (
            "CIK|Company Name|Form Type|Date Filed|Filename\n"
            "1234|Alpha Inc|8-K|20260713|edgar/data/1234/0000001234-26-000001.txt\n"
        ).encode("latin-1")
        submission = json.dumps(
            {
                "filings": {
                    "recent": {
                        "accessionNumber": ["0000001234-26-000001"],
                        "form": ["8-K"],
                        "filingDate": ["2026-07-13"],
                        "acceptanceDateTime": ["2026-07-13T21:00:00.000Z"],
                        "reportDate": ["2026-07-13"],
                        "primaryDocument": ["a.htm"],
                        "items": ["2.02"],
                    }
                }
            }
        ).encode("utf-8")

        def fetcher(url: str, _user_agent: str) -> bytes:
            return master if "master.20260713.idx" in url else submission

        payload = build(
            argparse.Namespace(
                universe_file=str(universe),
                company_tickers=str(company),
                identity_index=str(identity),
                dates="2026-07-13",
                forms="8-K,10-Q",
                valuation_close_date="2026-07-13",
                decision_time_utc="2026-07-14T05:00:00Z",
                user_agent="Research test@example.org",
                sleep=0.0,
                max_network_requests=4,
                output_dir=str(root / "output"),
            ),
            fetcher=fetcher,
        )
        assert payload["status"] == "READY_RECENT_SEC_ACCEPTED_DELTA"
        assert payload["network_requests_executed"] == 2
        assert payload["coverage"]["exact_acceptance_count"] == 1
        assert payload["coverage"]["event_metadata_count"] == 1
        assert payload["coverage"]["fundamental_refresh_candidate_count"] == 0
        audit = pd.read_csv(root / "output" / "event_actual_audit.csv")
        assert bool(audit.iloc[0]["exact_acceptance"])
        assert bool(audit.iloc[0]["item_2_02_reported_results"])
        assert str(audit.iloc[0]["accepted_at"]).startswith("2026-07-13T21:00:00")


def main() -> int:
    test_daily_prefilter_and_exact_acceptance_join()
    print("run287_recent_sec_delta_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

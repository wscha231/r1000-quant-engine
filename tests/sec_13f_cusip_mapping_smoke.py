#!/usr/bin/env python3
"""Smoke checks for SEC 13F CUSIP -> ticker mapping."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.build_sec_13f_cusip_ticker_map import build_cusip_map  # noqa: E402
from tools.run_sec_13f_parser import read_cusip_map  # noqa: E402
from tools.run_sec_institutional_signals import build_13f_signal  # noqa: E402


def _holdings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "manager_cik": "0001067983",
                "manager_name": "Example Manager",
                "report_period": "2025-12-31",
                "filing_date": "2026-02-14",
                "accepted_at": "2026-02-14T18:00:00+00:00",
                "available_from": "2026-02-14T18:00:00+00:00",
                "cusip": "037833100",
                "issuer_name": "APPLE INC",
                "ticker_mapped": "",
                "shares": 100000.0,
                "market_value_usd": 10_000_000.0,
            },
            {
                "manager_cik": "0001067983",
                "manager_name": "Example Manager",
                "report_period": "2026-03-31",
                "filing_date": "2026-05-15",
                "accepted_at": "2026-05-15T18:00:00+00:00",
                "available_from": "2026-05-15T18:00:00+00:00",
                "cusip": "037833100",
                "issuer_name": "APPLE INC",
                "ticker_mapped": "",
                "shares": 180000.0,
                "market_value_usd": 18_000_000.0,
            },
            {
                "manager_cik": "0001067983",
                "manager_name": "Example Manager",
                "report_period": "2026-03-31",
                "filing_date": "2026-05-15",
                "accepted_at": "2026-05-15T18:00:00+00:00",
                "available_from": "2026-05-15T18:00:00+00:00",
                "cusip": "999999999",
                "issuer_name": "UNKNOWN TEST ISSUER",
                "ticker_mapped": "",
                "shares": 10.0,
                "market_value_usd": 10.0,
            },
        ]
    )


def test_cusip_builder_maps_manual_overrides_and_preserves_unmapped_audit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        raw = root / "raw"
        raw.mkdir(parents=True)
        manual = root / "manual.csv"
        manual.write_text("cusip,ticker,issuer_name\n037833100,AAPL,APPLE INC\n", encoding="utf-8")
        mapped, unmapped, audit = build_cusip_map(
            _holdings(),
            raw_dir=raw,
            manual_overrides=manual,
            seed_files=[],
            user_agent="",
            refresh_company_tickers=False,
        )
        assert audit["research_only"] is True
        assert audit["production_activation_allowed"] is False
        assert audit["score_total_changed"] is False
        assert int(audit["mapped_unique_cusips"]) == 1
        assert int(audit["unmapped_unique_cusips"]) == 1
        assert mapped.loc[0, "ticker"] == "AAPL"
        assert "999999999" in set(unmapped["cusip"])

        parquet = root / "cusip_ticker_map.parquet"
        mapped.to_parquet(parquet, index=False)
        assert read_cusip_map(parquet)["037833100"] == "AAPL"

        enriched = _holdings().copy()
        lookup = read_cusip_map(parquet)
        enriched["ticker_mapped"] = enriched["cusip"].map(lookup).fillna("")
        signals = build_13f_signal(enriched, as_of="2026-05-16T00:00:00+00:00", lookback_days=210)
        assert len(signals) == 1
        assert signals.loc[0, "ticker"] == "AAPL"
        assert float(signals.loc[0, "institutional_evidence_score"]) > 0.0


if __name__ == "__main__":
    test_cusip_builder_maps_manual_overrides_and_preserves_unmapped_audit()
    print(json.dumps({"status": "PASS", "test": "sec_13f_cusip_mapping_smoke"}))

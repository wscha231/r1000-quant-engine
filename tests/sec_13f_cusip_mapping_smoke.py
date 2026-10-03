#!/usr/bin/env python3
"""Smoke checks for SEC 13F CUSIP -> ticker mapping."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.build_sec_13f_cusip_ticker_map import build_cusip_map, load_manual_overrides, read_table  # noqa: E402
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
        # A conflicting cached issuer lookup must not mask a broken manual key.
        (raw / "company_tickers.json").write_text(
            json.dumps({"0": {"cik_str": 320193, "ticker": "WRONG", "title": "APPLE INC"}}),
            encoding="utf-8",
        )
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
        assert mapped.loc[0, "source"] == "manual_override"
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


def test_canonical_overrides_cover_verified_q2_2026_disclosures() -> None:
    overrides = pd.read_csv(ROOT / "research" / "sec_13f_cusip_map_overrides.csv", dtype=str)
    overrides["cusip"] = overrides["cusip"].fillna("").str.strip().str.upper()
    overrides["ticker"] = overrides["ticker"].fillna("").str.strip().str.upper()
    assert not overrides["cusip"].duplicated().any()
    lookup = overrides.set_index("cusip")["ticker"].to_dict()
    assert lookup["88262P102"] == "TPL"
    assert lookup["46090E103"] == "QQQ"
    assert lookup["42824C109"] == "HPE"
    assert lookup["284902509"] == "EGO"


class CusipCsvIdentityTests(unittest.TestCase):
    """Native CSV boundaries must preserve identities even under Python -O."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()
        (self.raw / "company_tickers.json").write_text(
            json.dumps({"0": {"cik_str": 320193, "ticker": "WRONG", "title": "APPLE INC"}}),
            encoding="utf-8",
        )
        self.manual = self.root / "manual.csv"
        self.manual.write_text(
            "cusip,ticker,issuer_name\n037833100,AAPL,APPLE INC\n023135106,AMZN,AMAZON COM INC\n",
            encoding="utf-8",
        )
        network_patch = patch(
            "tools.run_sec_submissions_collector.sec_get_json",
            side_effect=AssertionError("offline fixture must not fetch SEC data"),
        )
        self.network = network_patch.start()
        self.addCleanup(network_patch.stop)

    def test_manual_numeric_keys_preserve_leading_zero(self) -> None:
        overrides = load_manual_overrides(self.manual)
        self.assertEqual(overrides.set_index("cusip")["ticker"].to_dict(), {
            "037833100": "AAPL", "023135106": "AMZN",
        })
        self.network.assert_not_called()

    def test_csv_holdings_build_exact_manual_map_and_unmapped_audit(self) -> None:
        holdings_csv = self.root / "holdings.csv"
        _holdings().to_csv(holdings_csv, index=False)
        holdings = read_table(holdings_csv)
        self.assertEqual(holdings["cusip"].tolist(), ["037833100", "037833100", "999999999"])
        mapped, unmapped, audit = build_cusip_map(
            holdings, raw_dir=self.raw, manual_overrides=self.manual, seed_files=[],
            user_agent="", refresh_company_tickers=False,
        )
        self.assertEqual(mapped.set_index("cusip")["ticker"].to_dict(), {"037833100": "AAPL"})
        self.assertEqual(mapped["source"].tolist(), ["manual_override"])
        self.assertEqual(unmapped["cusip"].tolist(), ["999999999"])
        self.assertEqual((audit["holding_rows"], audit["unique_cusips"], audit["mapped_unique_cusips"]), (3, 2, 1))
        self.assertFalse(audit["production_activation_allowed"])
        self.assertFalse(audit["score_total_changed"])
        self.network.assert_not_called()

    def test_csv_and_parquet_consumer_round_trip_agree(self) -> None:
        frame = load_manual_overrides(self.manual)
        csv = self.root / "map.csv"
        parquet = self.root / "map.parquet"
        frame.to_csv(csv, index=False)
        frame.to_parquet(parquet, index=False)
        expected = {"037833100": "AAPL", "023135106": "AMZN"}
        self.assertEqual(read_cusip_map(csv), expected)
        self.assertEqual(read_cusip_map(parquet), expected)

    def test_case_insensitive_identity_headers(self) -> None:
        self.manual.write_text("CuSiP,TiCkEr_MaPpEd\n037833100,AAPL\n", encoding="utf-8")
        self.assertEqual(load_manual_overrides(self.manual)["cusip"].tolist(), ["037833100"])
        self.assertEqual(read_cusip_map(self.manual), {"037833100": "AAPL"})

    def test_missing_identity_stays_empty_and_literal_na_ticker_stays_text(self) -> None:
        self.manual.write_text(
            "cusip,ticker\n037833100,AAPL\n023135106,\n,MSFT\n000000001,NA\n",
            encoding="utf-8",
        )
        expected = {"037833100": "AAPL", "000000001": "NA"}
        self.assertEqual(load_manual_overrides(self.manual).set_index("cusip")["ticker"].to_dict(), expected)
        self.assertEqual(read_cusip_map(self.manual), expected)

    def test_native_cli_csv_inputs_and_outputs_preserve_key(self) -> None:
        holdings = self.root / "holdings.csv"
        _holdings().to_csv(holdings, index=False)
        parquet, csv, audit, unmapped = [self.root / name for name in ("map.parquet", "map.csv", "audit.json", "unmapped.csv")]
        result = subprocess.run([
            sys.executable, str(ROOT / "tools" / "build_sec_13f_cusip_ticker_map.py"),
            "--holdings", str(holdings), "--raw-dir", str(self.raw),
            "--manual-overrides", str(self.manual), "--seed-file", str(self.root / "absent.csv"),
            "--output", str(parquet), "--csv-output", str(csv), "--audit", str(audit),
            "--unmapped", str(unmapped),
        ], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(read_cusip_map(csv), {"037833100": "AAPL"})
        self.assertEqual(read_cusip_map(parquet), {"037833100": "AAPL"})
        receipt = json.loads(audit.read_text(encoding="utf-8"))
        self.assertEqual(receipt["sources"], {"manual_override": 1})
        self.assertEqual(receipt["unmapped_unique_cusips"], 1)
        self.assertTrue(receipt["research_only"])
        self.assertFalse(receipt["production_activation_allowed"])


if __name__ == "__main__":
    test_cusip_builder_maps_manual_overrides_and_preserves_unmapped_audit()
    test_canonical_overrides_cover_verified_q2_2026_disclosures()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CusipCsvIdentityTests)
    if not unittest.TextTestRunner().run(suite).wasSuccessful():
        raise SystemExit(1)
    print(json.dumps({"status": "PASS", "test": "sec_13f_cusip_mapping_smoke"}))

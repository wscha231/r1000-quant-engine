"""Offline regression for archived PSA/EXR contamination and both consumers."""
import sys
import csv
import json
import hashlib
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import run_theme_leadership_tape as tape
import run_theme_concentration_challenger as challenger


class ThemeTests(unittest.TestCase):
    def theme(self, **row):
        return tape.infer_theme(pd.Series(row))

    def test_archived_six_members(self):
        # Membership is from the 2026-05-10 report, not invented price rows.
        # Exact aggregate row copied from theme_leadership.csv at base 481bcf5.
        with (ROOT / "tests/fixtures/theme_memory_20260510.csv").open(newline="") as source:
            archived = next(csv.DictReader(source))
        self.assertEqual(int(archived["member_count"]), 6)
        self.assertEqual(archived["top_tickers"], "MU,SNDK,STX,WDC,PSA,EXR")
        for ticker in ("MU", "SNDK", "STX", "WDC"):
            self.assertEqual(self.theme(ticker=ticker), "memory_semiconductors")
        for ticker, name in (("PSA", "Public Storage"), ("EXR", "Extra Space Storage")):
            self.assertNotEqual(self.theme(ticker=ticker, Name=name), "memory_semiconductors")

    def test_actual_archived_business_rows(self):
        rows = pd.read_csv(ROOT / "tests/fixtures/theme_memory_members_20260510.csv")
        expected = {"MU": "memory_semiconductors", "SNDK": "memory_semiconductors",
                    "STX": "memory_semiconductors", "WDC": "memory_semiconductors",
                    "PSA": "real_estate", "EXR": "real_estate"}
        self.assertEqual(rows.set_index("ticker")["leadership_theme"].to_dict(),
                         {ticker: "memory_semiconductors" for ticker in expected})
        self.assertEqual(dict(zip(rows["ticker"], rows.apply(tape.infer_theme, axis=1))), expected)
        self.assertEqual(dict(zip(rows["ticker"], challenger.add_theme_and_scores(rows)["leadership_theme"])), expected)

    def test_real_estate_separator_normalization(self):
        for sector in ("Real Estate", "Real-Estate", "Real_Estate", "real/estate"):
            for name in ("Public Storage", "Extra Space Storage"):
                self.assertEqual(self.theme(ticker="TEST", Name=name, sector=sector), "real_estate")
        for industry in ("REIT-Industrial", "REIT_Industrial", "REIT / Industrial"):
            self.assertEqual(self.theme(ticker="TEST", Name="Storage", industry=industry), "real_estate")

    def test_hot_path_reuses_compiled_patterns(self):
        with patch.object(tape.re, "compile", side_effect=AssertionError("per-row compile")), \
             patch.object(tape.re, "search", side_effect=AssertionError("per-row pattern construction")), \
             patch.object(tape.re, "sub", side_effect=AssertionError("per-row normalization pattern")):
            self.assertEqual(self.theme(ticker="TEST", Name="Flash Memory", industry="Semiconductors"),
                             "memory_semiconductors")
            self.assertEqual(self.theme(ticker="EXR", Name="Extra Space Storage", sector="Real-Estate"),
                             "real_estate")

    def test_recorded_diagnostic_evidence_hashes(self):
        evidence = ROOT / "docs/theme_memory_fix_evidence_20261015"
        manifest = json.loads((evidence / "manifest.json").read_text())
        required = {f"{date}_{kind}.csv" for date in ("20260510", "20260512")
                    for kind in ("themes_before", "themes_after", "score_comparison", "membership_changes")}
        self.assertTrue(required.issubset({entry["path"] for entry in manifest["files"]}))
        for entry in manifest["files"]:
            data = (evidence / entry["path"]).read_bytes()
            self.assertEqual(len(data), entry["size_bytes"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"])

    def test_all_curated_memory_issuers_preserved(self):
        for ticker in tape.THEME_TAXONOMY["memory_semiconductors"]["tickers"]:
            self.assertEqual(self.theme(ticker=ticker), "memory_semiconductors")

    def test_hardware_storage_and_memory(self):
        for name in ("Storage Systems", "NAND", "DRAM", "HBM", "SSD", "Flash", "Memory"):
            for industry in ("Semiconductors", "Computer Hardware", "Electronic Components", "Electronic Equipment & Parts"):
                with self.subTest(name=name, industry=industry):
                    self.assertEqual(self.theme(ticker="TEST", Name=name, industry=industry),
                                     "memory_semiconductors")

    def test_precise_digital_hardware_phrases(self):
        for name in ("Flash Memory", "Hard-Disk Drives", "Solid-State Drives",
                     "Data Storage Devices", "High Bandwidth Memory"):
            self.assertEqual(self.theme(ticker="TEST", Name=name), "memory_semiconductors")

    def test_physical_and_energy_storage_excluded(self):
        for industry in ("REIT - Specialty", "Real Estate", "Self-Storage",
                         "Warehousing", "Cold Storage", "Battery Storage",
                         "Energy Storage", "Gas Storage", "Oil Storage", "Logistics"):
            self.assertNotEqual(self.theme(ticker="TEST", Name="Flash Memory Storage",
                                           industry=industry), "memory_semiconductors")

    def test_inherited_labels_cannot_certify_business(self):
        for key in ("theme_phase_primary", "theme_horizon_primary",
                    "theme_holding_profile_primary", "portfolio_sleeve_label"):
            self.assertNotEqual(self.theme(ticker="TEST", Name="Public Storage",
                                           **{key: "memory_semiconductors flash dram storage"}),
                                "memory_semiconductors")

    def test_contradictory_industry_rejects_name_only_hardware(self):
        for industry in ("Software - Application", "Healthcare", "Financial Services"):
            self.assertNotEqual(self.theme(ticker="TEST", Name="Flash Memory", industry=industry),
                                "memory_semiconductors")

    def test_word_boundaries(self):
        for name in ("Dramatic Health", "Brandy Foods", "Flashlight Rental", "Memory Care"):
            self.assertNotEqual(self.theme(ticker="TEST", Name=name), "memory_semiconductors")

    def test_missing_metadata_and_no_cross_field_phrase(self):
        for value in (None, float("nan"), pd.NA, ""):
            self.assertEqual(self.theme(ticker="TEST", Name=value), "unclassified")
        self.assertNotEqual(self.theme(ticker="TEST", Name="Flash", industry="Memory Care"),
                            "memory_semiconductors")

    def test_missing_string_industries_preserve_precise_evidence(self):
        for industry in ("Unknown", "N/A", "nan", "none", "null", "NA"):
            self.assertEqual(self.theme(ticker="TEST", Name="Flash Memory", industry=industry),
                             "memory_semiconductors")

    def test_other_theme_and_fallback_preserved(self):
        self.assertEqual(self.theme(ticker="NVDA"), "ai_compute_semiconductors")
        self.assertEqual(self.theme(ticker="FLNC", Name="Battery Storage"), "power_grid_gas_turbine")
        self.assertEqual(self.theme(ticker="PSA", Name="Public Storage", sector="Real Estate"),
                         "real_estate")

    def test_two_real_consumers_agree(self):
        scored = pd.DataFrame([{"ticker": t, "Name": n, "industry": i}
                               for t, n, i in (("PSA", "Public Storage", "REIT - Specialty"),
                                               ("EXR", "Extra Space Storage", "REIT - Specialty"),
                                               ("MU", "Micron", "Semiconductors"),
                                               ("STX", "Seagate", "Computer Hardware"),
                                               ("TEST", "Storage", "Computer Hardware"))])
        def metrics(_cache, ticker):
            return dict(ticker=ticker, dollar_volume_20d=1e8, ret_1d=.01, ret_5d=.02,
                        ret_21d=.04, ret_63d=.08, ret_126d=.1, volume_z_20d=0)
        with patch.object(tape, "price_metrics", side_effect=metrics):
            daily = tape.build_ticker_tape(scored, Path("unused"), 0, 0)
        monthly = challenger.add_theme_and_scores(scored)
        self.assertEqual(daily.set_index("ticker")["leadership_theme"].to_dict(),
                         monthly.set_index("ticker")["leadership_theme"].to_dict())

    def test_aggregate_uses_corrected_membership(self):
        # Synthetic arithmetic control only; no historical score claim.
        scored = pd.DataFrame([{"ticker":t, "Name":n} for t,n in
                               (("MU","Micron"),("SNDK","Sandisk"),("STX","Seagate"),
                                ("WDC","Western Digital"),("PSA","Public Storage"),
                                ("EXR","Extra Space Storage"))])
        scored["leadership_theme"] = scored.apply(tape.infer_theme, axis=1)
        for col, value in (("ret_1d",.01),("ret_5d",.02),("ret_21d",.04),("ret_63d",.08),
                           ("participation_score",1.),("bubble_climax_score",1.),
                           ("early_leadership_score",1.),("dollar_volume_20d",1e8)):
            scored[col] = value
        scored["liquidity_pass"] = True
        row = tape.aggregate_leadership(scored, "leadership_theme").set_index("leadership_theme").loc["memory_semiconductors"]
        self.assertEqual(row["member_count"], 4)
        self.assertEqual(set(row["top_tickers"].split(",")), {"MU","SNDK","STX","WDC"})


if __name__ == "__main__":
    unittest.main()

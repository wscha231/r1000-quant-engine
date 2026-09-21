from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "research" / "cross_market_gold_set_v1.json"


class CrossMarketGoldSetV1Tests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        self.rows = self.data["candidates"]

    def test_registry_is_research_only_and_bounded(self):
        self.assertEqual(self.data["authority"], "RESEARCH_VALIDATION_ONLY")
        self.assertLessEqual(len(self.rows), self.data["constraints"]["max_candidates"])
        self.assertFalse(self.data["constraints"]["sector_quota_is_alpha"])
        self.assertFalse(self.data["constraints"]["methodology_selector_authority"])
        self.assertFalse(self.data["constraints"]["moat_selector_authority"])

    def test_candidate_identity_is_unique(self):
        ids = [row["id"] for row in self.rows]
        self.assertEqual(len(ids), len(set(ids)))
        market_tickers = [(row["market"], row["ticker"]) for row in self.rows]
        self.assertEqual(len(market_tickers), len(set(market_tickers)))

    def test_cross_market_and_multi_asset_coverage_exists(self):
        countries = {row["country"] for row in self.rows}
        asset_classes = {row["asset_class"] for row in self.rows}
        self.assertTrue({"US", "KR", "GLOBAL"}.issubset(countries))
        self.assertIn("EQUITY", asset_classes)
        self.assertIn("COMMODITY", asset_classes)

    def test_required_validation_profiles_exist(self):
        profiles = {row["sector_profile"] for row in self.rows}
        required = {
            "SEMICONDUCTOR_HARDWARE",
            "POWER_UTILITIES_INFRA",
            "PROJECT_INDUSTRIAL_SHIPBUILDING_NUCLEAR",
            "CONSUMER_BRAND_ODM",
            "BIOTECH_PRECOMMERCIAL",
            "COMMODITY_CYCLICAL",
        }
        self.assertTrue(required.issubset(profiles))

    def test_control_and_challenged_cases_exist(self):
        roles = {row["validation_role"] for row in self.rows}
        self.assertIn("CHALLENGED_FORMER_MONOPOLY", roles)
        self.assertIn("EMERGING_OPTICAL_SMALLCAP_CONTROL", roles)
        self.assertIn("NUCLEAR_FUEL_BOTTLENECK", roles)

    def test_all_rows_have_fair_comparison_metadata(self):
        for row in self.rows:
            with self.subTest(row=row["id"]):
                self.assertTrue(row["peer_group_key"])
                self.assertTrue(row["benchmark"])
                self.assertIn(row["priority"], {"P0", "P1", "P2"})
                self.assertIn(row["currency"], {"USD", "KRW"})
                self.assertTrue(row["validation_role"])

    def test_korean_equities_use_market_appropriate_primary_benchmark(self):
        for row in self.rows:
            if row["country"] != "KR":
                continue
            with self.subTest(row=row["id"]):
                expected = "KOSPI200" if row["market"] == "KOSPI" else "KOSDAQ150"
                self.assertEqual(row["benchmark"], expected)

    def test_gold_set_contains_no_hidden_weights_or_scores(self):
        forbidden = {
            "score", "weight", "expected_return", "target_weight", "buy",
            "sell", "rank", "methodology_score", "moat_score",
        }
        for row in self.rows:
            with self.subTest(row=row["id"]):
                self.assertTrue(forbidden.isdisjoint(row.keys()))


if __name__ == "__main__":
    unittest.main()

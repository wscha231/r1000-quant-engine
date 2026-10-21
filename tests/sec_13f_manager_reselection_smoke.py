#!/usr/bin/env python3
"""Smoke checks for semiannual SEC 13F manager reselection candidates."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_sec_13f_manager_reselection import run, return_ranked_selection, review_cycle  # noqa: E402


def test_manager_reselection_is_research_only_and_uses_repo_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        universe = root / "managers.csv"
        alpha = root / "13f_manager_alpha.csv"
        holdings = root / "holdings.csv"
        out = root / "out"
        candidate_universe = root / "managers_candidate.csv"

        pd.DataFrame(
            [
                {
                    "label": "GOOD",
                    "manager_name": "Good Manager LP",
                    "cik10": "12345",
                    "active": "true",
                    "verified_cik": "true",
                    "user_priority": "10",
                },
                {
                    "label": "WEAK",
                    "manager_name": "Weak Manager LP",
                    "cik10": "54321",
                    "active": "true",
                    "verified_cik": "true",
                    "user_priority": "20",
                },
            ]
        ).to_csv(universe, index=False)
        pd.DataFrame(
            [
                {
                    "manager_cik": "0000012345",
                    "manager_name": "Good Manager LP",
                    "observations": 30,
                    "avg_excess_return": 0.05,
                    "hit_rate_excess_positive": 0.70,
                    "manager_quality_score": 0.82,
                },
                {
                    "manager_cik": "0000054321",
                    "manager_name": "Weak Manager LP",
                    "observations": 30,
                    "avg_excess_return": -0.02,
                    "hit_rate_excess_positive": 0.35,
                    "manager_quality_score": 0.20,
                },
            ]
        ).to_csv(alpha, index=False)
        pd.DataFrame(
            [
                {
                    "manager_cik": "0000012345",
                    "manager_name": "Good Manager LP",
                    "ticker_mapped": "AAPL",
                    "report_period": "2026-03-31",
                    "available_from": "2026-05-15T00:00:00+00:00",
                    "accepted_at": "2026-05-15T00:00:00+00:00",
                    "shares": 1000,
                    "market_value_usd": 200_000_000,
                },
                {
                    "manager_cik": "0000054321",
                    "manager_name": "Weak Manager LP",
                    "ticker_mapped": "MSFT",
                    "report_period": "2026-03-31",
                    "available_from": "2026-05-15T00:00:00+00:00",
                    "accepted_at": "2026-05-15T00:00:00+00:00",
                    "shares": 1000,
                    "market_value_usd": 10_000_000,
                },
            ]
        ).to_csv(holdings, index=False)

        payload = run(
            argparse.Namespace(
                manager_universe=str(universe),
                manager_alpha=str(alpha),
                holdings=str(holdings),
                output_dir=str(out),
                output_candidate_universe=str(candidate_universe),
                extra="",
                max_managers=10,
                min_observations=10,
                review_interval_days=183,
            )
        )

        assert payload["status"] == "blocked"
        assert payload["reason"] == "missing_comparable_performance_evidence"
        assert payload["production_activation_allowed"] is False
        assert payload["active_manager_universe_changed"] is False
        assert candidate_universe.exists()
        summary = json.loads((out / "manager_reselection_summary.json").read_text(encoding="utf-8"))
        assert summary["review_interval_days"] == 183
        candidates = pd.read_csv(out / "manager_reselection_candidates.csv", dtype=str)
        assert str(candidates.iloc[0]["manager_cik"]).zfill(10) == "0000012345"
        assert candidates.iloc[0]["reselection_action"] in {"candidate_include", "keep_active"}


class ReturnRankedCycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / "source.json"
        source.write_text('{"fixture": "not real fund returns"}')
        self.source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        self.universe = pd.DataFrame([dict(cik10=f"{i:010d}", label=f"M{i}", manager_name=f"Manager {i}",
                                          verified_flag=True) for i in range(1, 13)])
        self.receipt = dict(schema="sec-manager-performance-evidence-v1", selection_cycle="2026-06-05",
                            performance_basis="FUND_NAV_NET_TOTAL_RETURN", window_start="2023-05-31",
                            window_end="2026-05-31", calculated_at="2026-06-04T00:00:00Z",
                            methodology_id="fixture-net-total-return-v1", currency="USD", managers=[])
        for i in range(1, 13):
            self.receipt["managers"].append(dict(
                manager_cik=f"{i:010d}", total_return=i / 100, status="COMPLETE", evidence_file="source.json",
                evidence_sha256=self.source_hash, source_available_at="2026-06-03T00:00:00Z",
                **{k: self.receipt[k] for k in ("window_start", "window_end", "performance_basis", "methodology_id", "currency")}))
        self.path = self.root / "receipt.json"

    def select(self, **kwargs):
        self.path.write_text(json.dumps(self.receipt))
        return return_ranked_selection(self.universe, self.path, decision_at="2026-10-21T00:00:00Z",
                                       top_n=kwargs.get("top_n", 10),
                                       performance_basis=kwargs.get("basis", "FUND_NAV_NET_TOTAL_RETURN"))

    def test_return_order_and_more_than_ten(self):
        result = self.select(top_n=11)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["selected_managers"]), 11)
        self.assertEqual(result["selected_managers"][0]["manager_cik"], "0000000012")
        self.assertFalse(result["source_authenticated"])
        self.assertFalse(result["production_activation_allowed"])

    def test_insufficient_missing_and_zero(self):
        self.receipt["managers"][0]["total_return"] = 0
        self.receipt["managers"][1]["total_return"] = None
        self.receipt["managers"][2]["status"] = "STALE"
        result = self.select()
        self.assertEqual(result["eligible_managers"], 10)
        self.assertEqual(self.select(top_n=11)["reasons"], ["insufficient_comparable_managers"])
        self.assertEqual(self.select(top_n=9)["status"], "blocked")

    def test_future_receipt_and_wrong_cycle(self):
        self.receipt["calculated_at"] = "2026-06-06T00:00:00Z"
        self.assertEqual(self.select()["status"], "blocked")
        self.receipt["calculated_at"] = "2026-06-04T00:00:00Z"
        self.receipt["selection_cycle"] = "2025-12-05"
        self.assertEqual(self.select()["status"], "blocked")

    def test_stale_performance_window_and_age_boundary(self):
        for end, expected in (("2026-03-05", "completed"), ("2026-03-04", "blocked"),
                              ("2003-05-31", "blocked")):
            self.receipt["window_start"] = "2000-05-31"
            self.receipt["window_end"] = end
            for row in self.receipt["managers"]:
                row.update(window_start="2000-05-31", window_end=end)
            result = self.select()
            self.assertEqual(result["status"], expected)
            if expected == "blocked":
                self.assertEqual(result["reasons"], ["stale_performance_window"])

    def test_basis_and_period_not_mixed(self):
        self.assertEqual(self.select(basis="DISCLOSED_13F_LONG_PROXY_TOTAL_RETURN")["status"], "blocked")
        for row in self.receipt["managers"][:3]:
            row["window_start"] = "2025-05-31"
        self.assertEqual(self.select()["eligible_managers"], 9)
        self.assertEqual(self.select()["selected_managers"], [])

    def test_duplicate_manager_fails_closed(self):
        self.receipt["managers"].append(copy.deepcopy(self.receipt["managers"][0]))
        self.assertEqual(self.select()["reasons"], ["invalid_performance_evidence"])

    def test_tampered_source_missing_identity_and_future_source(self):
        self.receipt["managers"][0]["evidence_sha256"] = "0" * 64
        self.universe.loc[1, "verified_flag"] = False
        self.receipt["managers"][2]["source_available_at"] = "2026-07-01T00:00:00Z"
        result = self.select()
        self.assertEqual(result["eligible_managers"], 9)
        self.assertEqual(result["selected_managers"], [])

    def test_same_cycle_replay_and_changed_evidence_refusal(self):
        self.select()
        universe_file = self.root / "universe.csv"
        self.universe.rename(columns={"verified_flag": "verified_cik"}).to_csv(universe_file, index=False)
        args = argparse.Namespace(manager_universe=str(universe_file), manager_alpha=str(self.root / "missing.csv"),
            holdings=str(self.root / "missing.parquet"), output_dir=str(self.root / "out"),
            output_candidate_universe="", extra="", max_managers=40, min_observations=10, review_interval_days=183,
            performance_evidence=str(self.path), top_n=10, performance_basis="FUND_NAV_NET_TOTAL_RETURN",
            decision_at="2026-10-21T00:00:00Z")
        self.assertEqual(run(args)["status"], "completed")
        frozen = self.root / "out/manager_selection_2026-06-05.json"
        original = frozen.read_bytes()
        self.assertEqual(run(args)["status"], "completed")
        self.assertEqual(original, frozen.read_bytes())
        args.decision_at = "2026-10-21T00:00:00"
        with self.assertRaises(ValueError):
            run(args)
        current = json.loads((self.root / "out/manager_performance_selection.json").read_text())
        self.assertEqual(current["status"], "blocked")
        self.assertEqual(current["selected_managers"], [])
        self.assertTrue(pd.read_csv(self.root / "out/manager_performance_selected.csv").empty)
        self.assertEqual(original, frozen.read_bytes())
        args.decision_at = "2026-10-21T00:00:00Z"
        self.assertEqual(run(args)["status"], "completed")
        for field, invalid, error in (("top_n", "invalid", ValueError),
                                      ("manager_universe", str(self.root), IsADirectoryError)):
            before = getattr(args, field)
            setattr(args, field, invalid)
            with self.assertRaises(error):
                run(args)
            current = json.loads((self.root / "out/manager_performance_selection.json").read_text())
            self.assertEqual(current["status"], "blocked")
            self.assertTrue(pd.read_csv(self.root / "out/manager_performance_selected.csv").empty)
            self.assertEqual(original, frozen.read_bytes())
            setattr(args, field, before)
            self.assertEqual(run(args)["status"], "completed")
        self.receipt["managers"][0]["total_return"] = 9.0
        self.path.write_text(json.dumps(self.receipt))
        self.assertEqual(run(args)["reason"], "frozen_cycle_conflict")
        self.assertEqual(original, frozen.read_bytes())
        self.assertTrue(pd.read_csv(self.root / "out/manager_performance_selected.csv").empty)
        self.path.unlink()
        self.assertEqual(run(args)["status"], "blocked")

    def test_calendar_six_month_boundary(self):
        self.assertEqual(review_cycle("2026-12-05T04:59:59Z")[0].date().isoformat(), "2026-06-05")
        cutoff, due = review_cycle("2026-12-05T05:00:00Z")
        self.assertEqual(cutoff.date().isoformat(), "2026-12-05")
        self.assertEqual(due.isoformat(), "2027-06-05")
        with self.assertRaises(ValueError):
            review_cycle("2026-12-05T05:00:00")


if __name__ == "__main__":
    test_manager_reselection_is_research_only_and_uses_repo_evidence()
    unittest.main()

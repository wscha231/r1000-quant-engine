#!/usr/bin/env python3
"""No-network regressions for daily research provenance and stale inputs."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import run_run287_daily_research_monitor as monitor

CONTRACT = json.loads(monitor.CONTRACT.read_text(encoding="utf-8"))
NOW = monitor.timestamp("2026-09-05T08:30:00Z")


def sample_run(run_id=2, conclusion="success"):
    return {"id": run_id, "run_attempt": 1, "head_sha": "a" * 40,
            "head_branch": "master", "head_repository": {"full_name": CONTRACT["repository"]},
            "created_at": f"2026-09-0{run_id}T05:00:00Z", "event": "schedule",
            "path": ".github/workflows/after_close_daily.yml", "status": "completed",
            "conclusion": conclusion}


def evidence():
    sources = {key: {"status": "VERIFIED_ARTIFACT", "artifact_hash_verified": True,
                     "run": sample_run(), "data": {}} for key in CONTRACT["sources"]}
    sources["tactical"]["data"]["summary"] = {
        "data_as_of": "2026-09-04", "latest_scored_rebalance_date": "2026-07-13"}
    sources["estimates"]["data"]["summary"] = {
        "fetch_date": "2026-09-05", "collector_status": "blocked_partial_coverage",
        "request_estimate_coverage_ratio": 1 / 6, "coverage_ratio": 1.0}
    sources["ownership"]["data"] = {
        "summary": {"13f_freshness": {"as_of_date": "2026-09-05", "freshness_ready": True,
                                     "required_due_period_end": "2026-06-30"}},
        "ranked": [{"ticker": "ETN", "smart_money_score": "0.7",
                    "latest_available_from": "2026-08-14T16:00:00Z"}]}
    sources["operating"]["data"]["prices"] = [{"ticker": "ETN", "previous_close": "300",
                                                  "latest_price_date": "2026-09-04", "currency": "USD"}]
    return sources


class MonitorTests(unittest.TestCase):
    def test_latest_failure_is_not_hidden_by_prior_success(self):
        runs = [sample_run(1), sample_run(2, "failure")]
        self.assertEqual(monitor.latest_run(runs, "after_close_daily.yml", CONTRACT["repository"])["id"], 2)
        foreign = sample_run(3)
        foreign["head_repository"]["full_name"] = "foreign/repo"
        self.assertEqual(monitor.latest_run(runs + [foreign], "after_close_daily.yml", CONTRACT["repository"])["id"], 2)
        runs[-1]["status"] = "in_progress"
        self.assertEqual(monitor.latest_run(runs, "after_close_daily.yml", CONTRACT["repository"])["id"], 2)

    def test_dates_prices_and_estimate_coverage_are_separate(self):
        report = monitor.evaluate(evidence(), "2026-09-04", NOW, CONTRACT)
        self.assertIn("tactical:latest_scored_rebalance_date:STALE", report["alerts"])
        self.assertNotIn("tactical:data_as_of:STALE", report["alerts"])
        self.assertIn("estimates:PARTIAL_OR_UNKNOWN_FORWARD_ESTIMATE_COVERAGE", report["alerts"])
        self.assertFalse(report["current_investment_ranking_ready"])
        etn = next(row for row in report["watchlist"] if row["ticker"] == "ETN")
        self.assertEqual(etn["close"], 300)
        self.assertEqual(etn["ownership_score"], 0.7)
        self.assertIsNone(etn["current_engine_score"])

    def test_future_and_duplicate_prices_are_not_current(self):
        source = evidence()
        source["operating"]["data"]["prices"][0]["latest_price_date"] = "2026-09-08"
        report = monitor.evaluate(source, "2026-09-04", NOW, CONTRACT)
        etn = next(r for r in report["watchlist"] if r["ticker"] == "ETN")
        self.assertIsNone(etn["close"])
        source["operating"]["data"]["prices"].append(copy.deepcopy(source["operating"]["data"]["prices"][0]))
        report = monitor.evaluate(source, "2026-09-04", NOW, CONTRACT)
        self.assertIn("operating:DUPLICATE_PRICE_TICKERS", report["alerts"])

    def test_disclosure_period_is_not_current_flow_or_zero_imputed(self):
        report = monitor.evaluate(evidence(), "2026-09-04", NOW, CONTRACT)
        self.assertEqual(report["observations"]["ownership"]["required_due_period_end"], "2026-06-30")
        self.assertTrue(all(r["ownership_score"] is None for r in report["watchlist"] if r["market"] == "KR"))
        self.assertIn("000660", [r["ticker"] for r in report["watchlist"]])
        source = evidence()
        source["ownership"]["data"]["ranked"][0]["latest_available_from"] = "2026-09-06T00:00:00Z"
        report = monitor.evaluate(source, "2026-09-04", NOW, CONTRACT)
        self.assertTrue(all(r["ownership_score"] is None for r in report["watchlist"]))

    def test_invalid_date_numeric_and_missing_inputs(self):
        self.assertEqual(monitor.date_state("2026-02-30", "2026-09-04"), "MISSING_OR_INVALID_DATE")
        self.assertFalse(monitor.collection_current("2026-09-04Tgarbage", "2026-09-04", NOW))
        self.assertIsNone(monitor.number("nan"))
        self.assertIsNone(monitor.number("inf"))
        report = monitor.evaluate({}, "2026-09-04", NOW, CONTRACT)
        self.assertEqual(report["status"], "ATTENTION_REQUIRED")
        self.assertIn("operating:MISSING_SOURCE", report["alerts"])

    def test_zip_exact_members_hashes_and_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.zip"
            raw = b'{"date":"2026-09-04"}'
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("outputs/summary.json", raw)
                z.writestr("../../ignored.py", b"raise RuntimeError()")
            data, hashes = monitor.read_members(path, {"summary": "outputs/summary.json"}, 1000)
            self.assertEqual(data["summary"]["date"], "2026-09-04")
            self.assertEqual(hashes["summary"]["sha256"], hashlib.sha256(raw).hexdigest())
            with self.assertRaisesRegex(ValueError, "artifact_member_size"):
                monitor.read_members(path, {"summary": "outputs/summary.json"}, 2)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(path, "a") as z:
                    z.writestr("outputs/summary.json", raw)
            with self.assertRaisesRegex(ValueError, "duplicate_artifact_member"):
                monitor.read_members(path, {"summary": "outputs/summary.json"}, 1000)

    def test_artifact_digest_and_run_identity_fail_closed(self):
        class Fake:
            def json(self, path):
                if "/workflows/" in path:
                    return {"workflow_runs": [sample_run()]}
                return {"artifacts": [{"id": 3, "name": "after-close-daily-2",
                                      "size_in_bytes": 1, "digest": "sha256:" + "a" * 64,
                                      "workflow_run": {"id": 2, "head_sha": "a" * 40}}]}

            def archive(self, artifact_id, destination, limit):
                return "sha256:" + "b" * 64
        result = monitor.collect_source(Fake(), "tactical", CONTRACT["sources"]["tactical"], CONTRACT)
        self.assertEqual(result["reason"], "artifact_digest_mismatch")
        self.assertEqual(result["data"], {})

    def test_weekend_holiday_and_early_close(self):
        self.assertEqual(monitor.completed_session(NOW), "2026-09-04")
        self.assertEqual(monitor.completed_session(monitor.timestamp("2026-09-07T22:00:00Z")), "2026-09-04")
        self.assertEqual(monitor.completed_session(monitor.timestamp("2026-11-27T19:31:00Z")), "2026-11-27")
        self.assertEqual(monitor.completed_session(monitor.timestamp("2026-11-27T19:00:00Z")), "2026-11-25")

    def test_report_does_not_mutate_sources_or_pretend_to_rank(self):
        source = evidence()
        original = copy.deepcopy(source)
        report = monitor.evaluate(source, "2026-09-04", NOW, CONTRACT)
        self.assertEqual(source, original)
        self.assertNotIn('"data"', json.dumps(report["sources"]))
        self.assertIn("**withheld**", monitor.render(report))
        self.assertTrue(report["safety"]["research_only"])
        self.assertTrue(all(v is False for k, v in report["safety"].items() if k != "research_only"))


def main() -> int:
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(MonitorTests))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

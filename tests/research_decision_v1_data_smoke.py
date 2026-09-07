"""Counterexamples for isolated research input admission."""
import copy
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_decision_v1_fixture import bundle, rehash
from tools.research_decision_v1.data import export_market, total_return_series, envelope_errors
from tools.research_decision_v1.io import immutable_json, read_json


class DataContractTests(unittest.TestCase):
    def result(self, b):
        return export_market(b, b["market"])["securities"][0]

    def test_valid_and_deterministic(self):
        b = bundle()
        self.assertEqual(export_market(b, "US"), export_market(copy.deepcopy(b), "US"))
        r = self.result(b)
        self.assertTrue(r["data_quality_pass"])
        self.assertEqual(r["discovery"]["rs"]["240"]["value"], 0.)

    def test_future_stale_identity_currency_period_hash(self):
        mutations = [
            lambda s: s["blocks"]["financials"].update(public_available_at="2026-09-08T00:00:00Z"),
            lambda s: s["blocks"]["price"]["payload"]["bars"].pop(),
            lambda s: s["blocks"]["financials"].update(security_id="US:OTHER"),
            lambda s: s["blocks"]["financials"].update(currency="KRW"),
            lambda s: s["blocks"]["financials"]["payload"]["period"].update(end="2024-01-01"),
            lambda s: s["blocks"]["financials"].update(data_hash="0" * 64),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                b = bundle(); mutate(b["securities"][0])
                self.assertFalse(self.result(b)["data_quality_pass"])

    def test_optional_failure_no_event_and_zero(self):
        b = bundle(); s = b["securities"][0]
        s["optional"] = {"estimates": {"status": "provider_error", "http": 403},
                         "form4": {"status": "no_event"}, "news": {"status": "missing"}}
        s["blocks"]["financials"]["payload"]["ttm"]["net_debt"] = 0.
        rehash(s["blocks"]["financials"])
        r = self.result(b)
        self.assertTrue(r["data_quality_pass"])
        self.assertEqual(r["optional"]["estimates"]["status"], "provider_error")
        s["blocks"]["financials"]["payload"]["ttm"]["net_debt"] = None
        rehash(s["blocks"]["financials"])
        self.assertFalse(self.result(b)["data_quality_pass"])

    def test_nonranking_forbidden(self):
        for field in ("nonranking_score", "score", "current_engine_score", "ownership_score"):
            b = bundle(); b["securities"][0][field] = 999
            with self.assertRaisesRegex(ValueError, "NONRANKING"): export_market(b, "US")
        b = bundle(); b["securities"][0]["status"] = "NONRANKING"
        with self.assertRaisesRegex(ValueError, "NONRANKING"): export_market(b, "US")

    def test_public_availability_and_official_close(self):
        for market in ("US", "KR"):
            b = bundle(market); price = b["securities"][0]["blocks"]["price"]
            price["public_available_at"] = None
            self.assertIn("price:public_available_at_unknown", self.result(b)["blockers"])
            price["public_available_at"] = "2026-09-04T00:00:00Z"
            self.assertFalse(self.result(b)["data_quality_pass"])
        b = bundle(); financials = b["securities"][0]["blocks"]["financials"]
        financials.update(published_at="2026-06-01T00:00:00Z", public_available_at="2026-06-01T00:00:00Z")
        self.assertIn("financials:period_after_published_at", self.result(b)["blockers"])

    def test_forecast_period_is_not_a_future_reported_actual(self):
        b = bundle(); security = b["securities"][0]
        block = copy.deepcopy(security["blocks"]["financials"])
        block.update(accounting_basis="RESEARCH_ASSUMPTION", report_period={"start": "2026-09-07", "end": "2027-09-07"})
        self.assertEqual(envelope_errors(block, security, b["decision_cutoff"]), [])
        block["accounting_basis"] = "US_GAAP"
        self.assertIn("period_after_published_at", envelope_errors(block, security, b["decision_cutoff"]))

    def test_benchmark_identity_actions_and_board(self):
        for market in ("US", "KR"):
            b = bundle(market); p = b["securities"][0]["blocks"]["price"]
            p["payload"]["benchmark_actions_through"] = "2020-01-01"; rehash(p)
            self.assertIn("price:benchmark_actions_stale", self.result(b)["blockers"])
            b = bundle(market); p = b["securities"][0]["blocks"]["price"]
            p["payload"]["benchmark_id"] = "OTHER"; rehash(p)
            self.assertIn("price:benchmark_identity_mismatch", self.result(b)["blockers"])
        b = bundle("KR"); b["securities"][0]["listing_board"] = "KOSDAQ"
        self.assertFalse(self.result(b)["data_quality_pass"])
        p = b["securities"][0]["blocks"]["price"]; p["payload"]["benchmark_id"] = "KOSDAQ150"; rehash(p)
        self.assertTrue(self.result(b)["data_quality_pass"])

    def test_recent_financial_recency_and_continuity(self):
        for field in ("recent_quarters", "recent_annual"):
            b = bundle(); f = b["securities"][0]["blocks"]["financials"]
            for row in f["payload"][field]:
                row["start"] = row["start"].replace("2026", "2010").replace("2025", "2009")
                row["end"] = row["end"].replace("2026", "2010").replace("2025", "2009")
            rehash(f); self.assertFalse(self.result(b)["data_quality_pass"])
        b = bundle(); f = b["securities"][0]["blocks"]["financials"]
        f["payload"]["recent_quarters"].append({"start": "2025-10-01", "end": "2025-12-31", "revenue": 2000.})
        rehash(f); self.assertIn("recent_quarters_gap_or_overlap", self.result(b)["blockers"])

    def test_unsafe_sources_never_reach_blocked_snapshot(self):
        sources = ("https://example.org/a?apikey=dummy", "https://example.org/a#access_token=dummy",
                   "https://example.org/token/dummy", "https://user:dummy@example.org/a")
        for source in sources:
            b = bundle(); b["securities"][0]["blocks"]["price"] = {"status": "missing", "source": source}
            with self.assertRaises(ValueError): export_market(b, "US")
        b = bundle(); b["data_kind"] = "REAL"
        with self.assertRaisesRegex(ValueError, "synthetic_source"): export_market(b, "US")

    def test_atomic_write_failure_can_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "record.json"
            with patch("tools.research_decision_v1.io.os.fsync", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError): immutable_json(p, {"x": 1})
            self.assertFalse(p.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])
            immutable_json(p, {"x": 1})
            self.assertEqual(read_json(p), {"x": 1})

    def test_short_history_and_split_dividend(self):
        b = bundle(); p = b["securities"][0]["blocks"]["price"]
        p["payload"]["bars"] = p["payload"]["bars"][-240:]
        p["payload"]["benchmark_bars"] = p["payload"]["benchmark_bars"][-240:]
        rehash(p)
        self.assertEqual(self.result(b)["discovery"]["rs"]["240"]["status"], "missing")
        raw = [{"close": 100., "split_ratio": 1., "dividend": 0.},
               {"close": 49., "split_ratio": 2., "dividend": 1.}]
        self.assertEqual(total_return_series(raw, "raw_unadjusted"), [1., 1.])
        adjusted = [{"close": 50., "split_ratio": 1., "dividend": 0.},
                    {"close": 49., "split_ratio": 2., "dividend": 1.}]
        self.assertEqual(total_return_series(adjusted, "split_adjusted"), [1., 1.])

    def test_market_cutoff_and_fcf(self):
        us, kr = bundle(), bundle("KR")
        self.assertEqual(self.result(us)["required_session"], "2026-09-04")
        self.assertEqual(self.result(kr)["required_session"], "2026-09-07")
        with self.assertRaises(ValueError): export_market(kr, "US")
        b = bundle(); f = b["securities"][0]["blocks"]["financials"]
        f["payload"]["ttm"]["fcf"] += 100.; rehash(f)
        self.assertFalse(self.result(b)["data_quality_pass"])

    def test_stale_rehashed_price_and_calendar_gap(self):
        b = bundle(); p = b["securities"][0]["blocks"]["price"]
        p["payload"]["bars"] = p["payload"]["bars"][:-1]; rehash(p)
        self.assertIn("price:stale_or_future_price", self.result(b)["blockers"])
        b = bundle(); p = b["securities"][0]["blocks"]["price"]
        p["payload"]["bars"] = p["payload"]["bars"][:5] + p["payload"]["bars"][6:]; rehash(p)
        self.assertIn("price:calendar_gap_or_non_session", self.result(b)["blockers"])

    def test_immutable_conflict_json_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "record.json"
            immutable_json(p, {"x": 0}); immutable_json(p, {"x": 0})
            with self.assertRaisesRegex(ValueError, "immutable_history_conflict"): immutable_json(p, {"x": 1})
            bad = Path(directory) / "bad.json"; bad.write_text('{"a":1,"a":2}')
            with self.assertRaisesRegex(ValueError, "duplicate_json_key"): read_json(bad)
            link = Path(directory) / "link.json"; link.symlink_to(p)
            with self.assertRaisesRegex(ValueError, "output_symlink"): immutable_json(link, {"x": 0})


if __name__ == "__main__": unittest.main()

from __future__ import annotations
import unittest
from copy import deepcopy
from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.sec_13f_manager_clone_event_evidence import (
    CloneEvidenceConfig, CloneEvidenceError, build_event_clone_evidence,
)


def frame(start="2020-01-02", periods=900, start_px=100.0, step=0.1):
    idx = pd.bdate_range(start, periods=periods)
    return pd.DataFrame({"close": [start_px + i * step for i in range(periods)]}, index=idx)


def provenance():
    return {
        "adjusted_close_total_return_proxy_verified": True,
        "benchmark_total_return_verified": True,
        "calendar_verified": True,
        "prices_pit_or_frozen_snapshot_verified": True,
        "price_snapshot_id": "SYNTHETIC_PRICE_SNAPSHOT",
        "calendar_id": "SYNTHETIC_NYSE",
        "benchmark_id": "SYNTHETIC_SPY_TR",
        "cost_model_id": "FIXED_10BPS_PER_SIDE_TEST",
    }


def event(**kw):
    base = {
        "event_id": "E1", "manager_cik": "1536411", "ticker": "AAA",
        "event_type": "new", "available_from": "2020-01-03T22:00:00Z",
        "report_period": "2019-12-31",
    }
    base.update(kw)
    return base


class CloneEventEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.frames = {"AAA": frame(), "BBB": frame(start_px=50, step=-0.01), "SPY": frame(start_px=200, step=0.05)}
        self.loader = lambda ticker: self.frames[ticker]
        self.map = {"1536411": "DUQUESNE", "0001536411": "DUQUESNE"}
        self.cutoff = "2024-12-31T23:59:59Z"

    def build(self, events=None, **kwargs):
        return build_event_clone_evidence(events or [event()], price_loader=self.loader,
            manager_map=self.map, decision_cutoff=kwargs.pop("decision_cutoff", self.cutoff),
            provenance=kwargs.pop("provenance", provenance()), config=kwargs.pop("config", CloneEvidenceConfig()), **kwargs)

    def test_strict_next_calendar_day_entry(self):
        out = self.build()
        row = next(r for r in out["event_rows"] if r.get("status") == "MATURED" and r["entry_delay_sessions"] == 0 and r["horizon_sessions"] == 63)
        self.assertEqual(row["entry_date"], "2020-01-06")

    def test_entry_delay_uses_trading_sessions(self):
        out = self.build()
        dates = {r["entry_delay_sessions"]: r["entry_date"] for r in out["event_rows"] if r.get("horizon_sessions") == 63 and r.get("status") == "MATURED"}
        self.assertEqual(dates[0], "2020-01-06")
        self.assertEqual(dates[2], "2020-01-08")
        self.assertEqual(dates[5], "2020-01-13")

    def test_cost_reduces_gross_return(self):
        row = next(r for r in self.build()["event_rows"] if r.get("status") == "MATURED" and r["entry_delay_sessions"] == 0 and r["horizon_sessions"] == 63)
        self.assertLess(row["net_return"], row["gross_return"])

    def test_future_target_is_pending_even_if_price_file_contains_it(self):
        out = self.build(decision_cutoff="2020-02-01T23:59:59Z")
        self.assertTrue(out["event_rows"])
        self.assertTrue(all(r["status"] == "PENDING_MATURITY" for r in out["event_rows"] if "horizon_sessions" in r))

    def test_insufficient_504_price_history_is_explicit_pending(self):
        self.frames["AAA"] = frame(periods=300)
        out = self.build()
        self.assertTrue(any(r.get("horizon_sessions") == 504 and r["status"] == "PENDING_PRICE_HISTORY" for r in out["event_rows"]))

    def test_trim_exit_hold_are_not_positive_clone_events(self):
        events = [event(event_id="N", event_type="new"), event(event_id="T", event_type="trim"), event(event_id="X", event_type="exit"), event(event_id="H", event_type="hold")]
        out = self.build(events)
        self.assertEqual({r["event_id"] for r in out["event_rows"]}, {"N"})

    def test_duplicate_event_id_fails_closed(self):
        with self.assertRaisesRegex(CloneEvidenceError, "duplicate_event_id"):
            self.build([event(), deepcopy(event())])

    def test_manager_identity_must_be_explicitly_mapped(self):
        with self.assertRaisesRegex(CloneEvidenceError, "mapping_missing"):
            build_event_clone_evidence([event(manager_cik="999")], price_loader=self.loader, manager_map=self.map,
                decision_cutoff=self.cutoff, provenance=provenance())

    def test_unverified_total_return_provenance_blocks(self):
        p = provenance(); p["benchmark_total_return_verified"] = False
        with self.assertRaisesRegex(CloneEvidenceError, "not_verified"):
            self.build(provenance=p)

    def test_benchmark_calendar_mismatch_blocks_horizon(self):
        self.frames["SPY"] = self.frames["SPY"].drop(self.frames["SPY"].index[70])
        out = self.build()
        self.assertTrue(any(r["status"] == "BLOCKED_BENCHMARK" for r in out["event_rows"]))

    def test_explicit_economic_manager_id_does_not_require_name_guess(self):
        out = self.build([event(economic_manager_id="DUQUESNE", manager_cik="")])
        self.assertEqual({r["economic_manager_id"] for r in out["event_rows"]}, {"DUQUESNE"})

    def test_no_manager_rank_or_continuous_nav_claim(self):
        out = self.build()
        self.assertFalse(out["continuous_clone_nav_built"])
        self.assertFalse(out["manager_skill_rank_built"])
        self.assertFalse(out["production_promotion_allowed"])
        self.assertFalse(out["automatic_trade_allowed"])

    def test_same_input_is_deterministic(self):
        self.assertEqual(self.build()["evidence_id"], self.build()["evidence_id"])

    def test_cost_config_is_preregisterable_and_validated(self):
        with self.assertRaises(CloneEvidenceError): CloneEvidenceConfig(per_side_cost_bps=-1)
        with self.assertRaises(CloneEvidenceError): CloneEvidenceConfig(horizons=(252, 63))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations
import unittest
from copy import deepcopy
from pathlib import Path
import sys
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from tools.sec_13f_manager_event_scorecard import ScorecardConfig, ScorecardError, build_manager_event_scorecards

CUTOFF = "2026-09-16T23:59:59Z"

def rows(manager="M1", count=6, ticker_prefix="A", start="2024-01-02"):
    out=[]
    dates=pd.bdate_range(start, periods=count)
    for i,d in enumerate(dates):
        for delay in (0,2,5):
            for h in (63,126,252,504):
                avail=pd.Timestamp(d, tz="UTC")
                target=avail + pd.Timedelta(days=h*2)
                out.append({
                    "event_id":f"{manager}-E{i}","economic_manager_id":manager,"ticker":f"{ticker_prefix}{i%4}",
                    "event_type":"new" if i%2==0 else "add","available_from":avail.isoformat(),
                    "entry_delay_sessions":delay,"horizon_sessions":h,"status":"MATURED",
                    "net_return":0.10+i*.01-delay*.001,"benchmark_total_return":0.04,
                    "net_excess_return":0.06+i*.01-delay*.001,"max_drawdown_from_entry":-0.10+i*.002,
                    "target_date":target.date().isoformat(),"outcome_available_at":"2026-09-01T23:59:59Z",
                    "price_snapshot_id":"PX1","cost_model_id":"COST1"})
    return out

class ScorecardTests(unittest.TestCase):
    def build(self, data=None, **kw):
        return build_manager_event_scorecards(data if data is not None else rows(), decision_cutoff=CUTOFF,
            source_evidence_id="EVENT-EVIDENCE-1", config=kw.pop("config", ScorecardConfig()), **kw)

    def test_is_explicitly_not_nav_or_rank(self):
        out=self.build(); self.assertTrue(out["event_study_not_account_nav"]); self.assertFalse(out["continuous_clone_nav_built"]); self.assertFalse(out["manager_skill_rank_built"])

    def test_horizon_stats_are_separate(self):
        card=self.build()["scorecards"][0]
        self.assertEqual(set(card["horizons"]), {"63","126","252","504"})
        self.assertEqual(card["horizons"]["252"]["events"], 6)

    def test_delay_robustness_pairs_same_event_and_horizon(self):
        card=self.build()["scorecards"][0]
        self.assertEqual(card["delay_robustness"]["2"]["pairs"], 24)
        self.assertLess(card["delay_robustness"]["2"]["mean_excess_change_vs_base"], 0)

    def test_missing_horizon_is_ineligible_not_zero(self):
        data=[r for r in rows() if r["horizon_sessions"]!=504]
        card=self.build(data)["scorecards"][0]
        self.assertEqual(card["horizons"]["504"]["status"], "NO_SAMPLE")
        self.assertFalse(card["eligible_for_skill_ranking"])

    def test_small_sample_is_ineligible(self):
        card=self.build(rows(count=2))["scorecards"][0]
        self.assertFalse(card["eligible_for_skill_ranking"])

    def test_nonmatured_row_rejected(self):
        data=rows(); data[0]["status"]="PENDING_MATURITY"
        with self.assertRaisesRegex(ScorecardError,"only_matured"): self.build(data)

    def test_future_outcome_availability_rejected(self):
        data=rows(); data[0]["outcome_available_at"]="2027-01-01T00:00:00Z"
        with self.assertRaisesRegex(ScorecardError,"future_or_inverted"): self.build(data)

    def test_duplicate_event_delay_horizon_rejected(self):
        data=rows(); data.append(deepcopy(data[0]))
        with self.assertRaisesRegex(ScorecardError,"duplicate_event"): self.build(data)

    def test_event_identity_drift_rejected(self):
        data=rows(); data[1]["ticker"]="DIFFERENT"
        with self.assertRaisesRegex(ScorecardError,"event_identity_inconsistent"): self.build(data)

    def test_independence_proxy_uses_other_manager_tickers(self):
        data=rows("M1", ticker_prefix="A")+rows("M2", ticker_prefix="A")
        cards={c["economic_manager_id"]:c for c in self.build(data)["scorecards"]}
        self.assertLess(cards["M1"]["independence_proxy"], 1)
        self.assertFalse(cards["M1"]["outcome_overlap_adjusted"])

    def test_new_add_stats_kept_separate(self):
        card=self.build()["scorecards"][0]
        self.assertGreater(card["event_type_stats"]["new"]["unique_events"],0)
        self.assertGreater(card["event_type_stats"]["add"]["unique_events"],0)

    def test_same_input_deterministic(self):
        self.assertEqual(self.build()["scorecard_evidence_id"], self.build()["scorecard_evidence_id"])

    def test_unexpected_horizon_rejected(self):
        data=rows(); data[0]["horizon_sessions"]=42
        with self.assertRaisesRegex(ScorecardError,"unexpected_horizon"): self.build(data)

    def test_empty_input_returns_no_evidence(self):
        out=self.build([]); self.assertEqual(out["status"],"NO_MATURED_EVENT_EVIDENCE"); self.assertEqual(out["scorecards"],[])

if __name__=="__main__": unittest.main()

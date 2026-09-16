from __future__ import annotations
import tempfile, unittest
from pathlib import Path
import sys
import pandas as pd
ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from tools.run_sec_13f_manager_event_scorecard import ScorecardError, config_from_json, evaluate, publish_immutable, validate_source_manifest

CONF={"horizons":[63,126,252,504],"base_delay":0,"robustness_delays":[2,5],"minimum_events_per_horizon":2,"minimum_unique_tickers":2,"recent_window_months":36}
MAN={"artifact_kind":"RESEARCH_DIAGNOSTIC_NOT_ACCEPTED_STATE","research_only":True,"manager_skill_rank_built":False,"evidence_id":"EVENT-1"}

def evidence():
    rows=[]
    for i in range(2):
        for delay in (0,2,5):
            for h in (63,126,252,504):
                rows.append({"event_id":f"E{i}","economic_manager_id":"M1","ticker":f"T{i}","event_type":"new","available_from":"2024-01-02T00:00:00Z","entry_delay_sessions":delay,"horizon_sessions":h,"status":"MATURED","net_return":.1,"benchmark_total_return":.04,"net_excess_return":.06-delay*.001,"max_drawdown_from_entry":-.1,"target_date":"2025-12-01","outcome_available_at":"2026-01-01T00:00:00Z","price_snapshot_id":"PX","cost_model_id":"COST"})
    return pd.DataFrame(rows)

class RunnerTests(unittest.TestCase):
    def test_source_manifest_boundary_required(self):
        bad=dict(MAN); bad["manager_skill_rank_built"]=True
        with self.assertRaises(ScorecardError): validate_source_manifest(bad)

    def test_unknown_config_rejected(self):
        with self.assertRaises(ScorecardError): config_from_json({**CONF,"magic":1})

    def test_evaluate_builds_descriptive_not_rank(self):
        out=evaluate(evidence(),MAN,CONF,"2026-09-16T23:59:59Z")
        self.assertEqual(out["status"],"READY_DESCRIPTIVE_SCORECARDS")
        self.assertFalse(out["manager_skill_rank_built"])
        self.assertTrue(out["event_study_not_account_nav"])

    def test_publish_identical_rerun_and_tamper_block(self):
        out=evaluate(evidence(),MAN,CONF,"2026-09-16T23:59:59Z")
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"artifact"
            a=publish_immutable(p,out,{"decision_cutoff":out["decision_cutoff"]})
            b=publish_immutable(p,out,{"decision_cutoff":out["decision_cutoff"]})
            self.assertEqual(a["publication"],"NEW_LOCAL_DIAGNOSTIC"); self.assertEqual(b["publication"],"IDENTICAL_RERUN_VERIFIED")
            (p/"manager_event_scorecards.json").write_text("tamper",encoding="utf-8")
            with self.assertRaises(ScorecardError): publish_immutable(p,out,{"decision_cutoff":out["decision_cutoff"]})

    def test_empty_source_yields_no_scorecard(self):
        out=evaluate(pd.DataFrame(),MAN,CONF,"2026-09-16T23:59:59Z")
        self.assertEqual(out["status"],"NO_MATURED_EVENT_EVIDENCE")

if __name__=="__main__": unittest.main()

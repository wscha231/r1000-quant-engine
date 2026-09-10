"""Offline synthetic regressions for stale-data liquidation and unknown regimes."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import r1000_tactical_alpha as tactical
from tools.macro_daily_snapshot import classify_regime
from tools.etf_leadership_snapshot import classify_state

SESSION = "2026-09-08"


def candidate(ticker="AAA", session=SESSION):
    return {"ticker": ticker, "price_as_of": session, "px": 100.,
            "tactical_rank": 1., "tactical_rank_score": .8,
            "tactical_hard_exit": False, "tactical_soft_exit": False}


class TacticalInputTests(unittest.TestCase):
    def test_recorded_regression_cannot_become_full_liquidation(self):
        frame=pd.DataFrame([candidate(session="2026-08-24")])
        previous={"data_as_of":"2026-09-04","candidate_count":141}
        held={name:.2 for name in ("HELD1","HELD2","HELD3","HELD4","HELD5")}
        gate=tactical.tactical_input_gate(frame,previous,held,SESSION,"2026-07-13")
        self.assertFalse(gate["ready"])
        self.assertTrue({"data_as_of_regressed","candidate_universe_collapsed",
            "scored_snapshot_not_current_session","held_security_missing_current_evidence"} <= set(gate["blockers"]))
        plan=tactical.build_trade_plan(pd.DataFrame(),frame,held,required_session=SESSION)
        self.assertEqual(set(plan.action),{"HOLD"})
        self.assertEqual(dict(zip(plan.ticker,plan.target_weight)),held)
        self.assertTrue(plan.delta_weight.eq(0).all())

    def test_fresh_complete_evidence_allows_review(self):
        frame=pd.DataFrame([candidate()])
        gate=tactical.tactical_input_gate(frame,{"data_as_of":"2026-09-04","candidate_count":1},{"AAA":.2},SESSION,SESSION)
        self.assertTrue(gate["ready"],gate)
        plan=tactical.build_trade_plan(pd.DataFrame(),frame,{"AAA":.2},required_session=SESSION)
        self.assertEqual(plan.iloc[0].action,"SELL")
        self.assertTrue(plan.iloc[0].input_ready)

    def test_single_stale_name_cannot_hide_behind_majority_date(self):
        frame=pd.DataFrame([candidate("AAA"),candidate("BBB"),candidate("CCC","2026-09-04")])
        gate=tactical.tactical_input_gate(frame,{}, {},SESSION,SESSION)
        self.assertIn("candidate_prices_not_exact_session",gate["blockers"])

    def test_nonfinite_or_missing_price_rank_blocks_trade(self):
        for field in ("px","tactical_rank","tactical_rank_score"):
            for value in (None,float("nan"),float("inf")):
                with self.subTest(field=field,value=value):
                    row=candidate();row[field]=value;frame=pd.DataFrame([row])
                    self.assertFalse(tactical.tactical_input_gate(frame,{}, {},SESSION,SESSION)["ready"])
                    plan=tactical.build_trade_plan(pd.DataFrame(),frame,{"AAA":.2},required_session=SESSION)
                    self.assertEqual(plan.iloc[0].action,"HOLD")

    def test_invalid_price_date_and_duplicate_tickers_block(self):
        for value in (None,"nan","", "2026-09-09"):
            frame=pd.DataFrame([candidate(session=value)])
            plan=tactical.build_trade_plan(pd.DataFrame(),frame,{"AAA":.2},required_session=SESSION)
            self.assertEqual(plan.iloc[0].action,"HOLD")
        frame=pd.DataFrame([candidate(),candidate()])
        self.assertIn("duplicate_candidate_ticker",tactical.tactical_input_gate(frame,{}, {},SESSION,SESSION)["blockers"])

    def test_completed_close_uses_intraday_holiday_and_early_close(self):
        for stamp,expected in (("2026-09-08T19:59:00Z","2026-09-04"),
                               ("2026-09-08T20:00:00Z",SESSION),
                               ("2026-09-07","2026-09-04"),
                               ("2025-11-28T17:59:00Z","2025-11-26"),
                               ("2025-11-28T18:00:00Z","2025-11-28")):
            self.assertEqual(str(tactical.latest_nyse_day_on_or_before(stamp).date()),expected)

    def test_failed_or_duplicate_run_preserves_prior_outputs(self):
        for duplicate in (False,True):
            with self.subTest(duplicate=duplicate),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);out=root/"outputs/tactical_alpha";out.mkdir(parents=True)
                previous={"data_as_of":SESSION if duplicate else "2026-09-04","candidate_count":1 if duplicate else 141}
                (out/"tactical_run_summary.json").write_text(json.dumps(previous))
                for name in ("tactical_portfolio_latest.csv","tactical_trade_plan.csv"):(out/name).write_text("preserve previous research bytes\n")
                before={p.name:p.read_bytes() for p in out.iterdir()}
                args=SimpleNamespace(base_dir=temp,as_of=SESSION,scored_path=None,previous_holdings=None,
                    update_prices=False,preliminary_limit=240,min_price=5.,min_dollar_vol=20e6,output_dir=None)
                scored=pd.DataFrame([{"ticker":"AAA","score":1.,"rebalance_date":SESSION}])
                held=pd.DataFrame([{"ticker":"AAA","weight":.2}])
                with patch.object(tactical,"parse_args",return_value=args),patch.object(tactical,"get_paths",return_value={"out":root/"outputs"}),\
                     patch.object(tactical,"load_scored_latest",return_value=tactical.LoadedFrame(scored,None)),\
                     patch.object(tactical,"prepare_concentrated_frame",side_effect=lambda cfg,frame:frame),\
                     patch.object(tactical,"build_candidate_frame",return_value=pd.DataFrame([candidate()])),\
                     patch.object(tactical,"load_previous_holdings",return_value=tactical.LoadedFrame(held,None)),\
                     patch.object(tactical,"select_tactical_portfolio") as select:
                    self.assertEqual(tactical.main(),0 if duplicate else 2);select.assert_not_called()
                self.assertEqual(before,{p.name:p.read_bytes() for p in out.iterdir() if p.is_file()})
                self.assertEqual(len(list((out/"diagnostics").glob("*/input_gate.json"))),1)

    def test_unknown_macro_and_etf_inputs_are_not_regimes(self):
        valid={"spy_close":110.,"spy_ma200":100.,"spy_ret_3m":.08,"vix":20.,"vix_z_63d":-.2}
        self.assertEqual(classify_regime(valid),"bull")
        for key in valid:
            for value in (None,float("nan"),float("inf")):
                snap=copy.deepcopy(valid);snap[key]=value
                self.assertEqual(classify_regime(snap),"unknown")
        self.assertEqual(classify_regime({}),"unknown")
        for value in (None,float("nan"),float("inf"),-float("inf")):
            self.assertEqual(classify_state(value),"unknown")

    def test_required_workflow_failures_propagate(self):
        payload=yaml.load((ROOT/".github/workflows/after_close_daily.yml").read_text(),Loader=yaml.BaseLoader)
        steps={s["name"]:s for s in payload["jobs"]["after_close"]["steps"]}
        for name in ("R1000 scanner digest","Theme leadership tape","Explosive mover scan","Tactical alpha after-close review"):
            self.assertNotIn("::warning::",steps[name]["run"])
            self.assertNotIn("set +e",steps[name]["run"])
        self.assertIn("exit 2",steps["Theme leadership tape"]["run"])
        self.assertEqual(steps["Commit daily cloud results"]["if"],"success()")
        self.assertEqual(steps["Upload daily artifacts"]["if"],"always()")


if __name__ == "__main__":unittest.main(verbosity=2)

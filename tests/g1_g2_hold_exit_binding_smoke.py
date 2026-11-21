from __future__ import annotations
from argparse import Namespace
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd
from pandas.testing import assert_frame_equal

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from tools import legacy_control_adapter as g1
from tools import run287_hold_exit_policy as g2
from tools import g1_g2_hold_exit_binding as binding


def legacy_spec(kind="main"):
    return g1.StrategySpec(
        portfolio_kind=kind,target_n=15 if kind=="main" else 5,
        candidate_source_ref="fixture:candidate",regime_crisis_ref=("fixture:f","fixture:t"),
        discovery_module="LEGACY",entry_module="LEGACY",hold_exit_module="LEGACY",
        regime_module="LEGACY",allocation_module="LEGACY",version=g1.LEGACY_STRATEGY_VERSION,parameters=(),
    )

def g2_spec(kind="main",gap=None):
    return replace(legacy_spec(kind),hold_exit_module=binding.G2_HOLD_EXIT_MODULE_ID,parameters=binding.make_g2_parameters(minimum_score_gap=gap))

def evaluation():
    return g1.EvaluationSpec("u","NYSE","prices","next_close",25.0,True,7,g1.LEGACY_ACCOUNTING_EVALUATOR_REF,(None,None),100000.0)


class BindingTests(unittest.TestCase):
    def test_legacy_path_never_loads_g2_and_preserves_all_g1_delegates(self):
        main=legacy_spec(); conc=legacy_spec("concentrated"); ev=evaluation()
        candidate=pd.DataFrame({"x":[1]}); crisis=pd.DataFrame({"y":[2]}); prices={"A":pd.DataFrame({"Close":[1.0]})}
        build_result=(pd.DataFrame({"target":[1]}),pd.DataFrame({"lane":[1]}),pd.DataFrame({"reject":[1]}),pd.DataFrame({"exposure":[1]}))
        allocation=[{"ticker":"AAA","weight":0.9}]
        control_result={"status":"control"}; broker_result={"status":"broker"}
        args=Namespace(marker="same-object")
        with patch.object(binding,"_load_g2",side_effect=AssertionError("G2 must not load")) as loader, \
             patch.object(g1,"build_variant_book",return_value=build_result) as build_mock, \
             patch.object(g1,"assign_weights",return_value=allocation) as alloc_mock, \
             patch.object(g1,"run_control",return_value=control_result) as control_mock, \
             patch.object(g1,"run_broker_replays",return_value=broker_result) as broker_mock:
            binding.validate_strategy_spec(main)
            built=binding.build_control_variant_book(main,candidate=candidate,crisis_states=crisis,prices=prices)
            weighted=binding.assign_weights(main,selected=[{"ticker":"AAA"}],cash_target=0.1)
            treated=binding.apply_hold_exit_module(main,build_result[0])
            controlled=binding.run_control(main,conc,ev,args=args)
            brokered=binding.run_broker_replays(main,conc,ev,latest_run="L")
        loader.assert_not_called()
        self.assertIs(built,build_result)
        self.assertIs(weighted,allocation)
        self.assertIs(treated[0],build_result[0])
        self.assertEqual(treated[3]["status"],"LEGACY_BYPASS")
        self.assertIs(controlled,control_result); self.assertIs(brokered,broker_result)
        build_mock.assert_called_once_with(main,candidate=candidate,crisis_states=crisis,prices=prices)
        alloc_mock.assert_called_once_with(main,selected=[{"ticker":"AAA"}],cash_target=0.1)
        control_mock.assert_called_once_with(main,conc,ev,args=args)
        broker_mock.assert_called_once_with(main,conc,ev,latest_run="L")

    def test_g2_builds_control_through_legacy_shadow_only(self):
        spec=g2_spec(); sentinel=(pd.DataFrame({"target":[1]}),pd.DataFrame(),pd.DataFrame(),pd.DataFrame())
        with patch.object(g1,"build_variant_book",return_value=sentinel) as mocked:
            got=binding.build_control_variant_book(spec,candidate=pd.DataFrame(),crisis_states=pd.DataFrame(),prices={})
        self.assertIs(got,sentinel)
        shadow=mocked.call_args.args[0]
        self.assertEqual(shadow.hold_exit_module,"LEGACY")
        self.assertEqual(shadow.parameters,())
        self.assertEqual(shadow.portfolio_kind,spec.portfolio_kind)
        self.assertEqual(shadow.target_n,spec.target_n)

    def test_g2_default_policy_delegates_exact_existing_builder_and_isolates_inputs(self):
        spec=g2_spec(); config=dict(spec.parameters)["hold_exit_policy_config"]
        control=pd.DataFrame({"rebalance_date":["2024-01-31"],"ticker":["AAA"],"weight":[1.0],"meta":[{"x":[1]}]})
        scored=pd.DataFrame({"rebalance_date":["2024-01-31"],"ticker":["AAA"],"pit_evidence_blocked":[False]})
        before_control=control.copy(deep=True); before_meta=json.loads(json.dumps(control.iloc[0]["meta"]))
        seen={}
        def fake_build(control_book,scored_candidates,*,portfolio,lifecycle_path,policy):
            seen.update({"control":control_book,"scored":scored_candidates,"portfolio":portfolio,"lifecycle":lifecycle_path,"policy":policy})
            control_book.iloc[0]["meta"]["x"].append(99)
            return control_book,pd.DataFrame({"action":["G2"]}),pd.DataFrame(),{"policy":config}
        with tempfile.TemporaryDirectory() as raw:
            cache=Path(raw)/"scored.csv"; lifecycle=Path(raw)/"lifecycle.csv"
            cache.write_text("placeholder\n",encoding="utf-8"); lifecycle.write_text("placeholder\n",encoding="utf-8")
            with patch.object(g2,"load_scored_candidate_cache",return_value=scored) as load_mock, \
                 patch.object(g2,"build_leadership_persistence_book",side_effect=fake_build) as build_mock:
                result=binding.apply_hold_exit_module(spec,control,scored_candidate_cache_path=cache,lifecycle_path=lifecycle)
            load_mock.assert_called_once_with(cache); self.assertEqual(build_mock.call_count,1)
            self.assertEqual(seen["portfolio"],"main"); self.assertEqual(seen["lifecycle"],lifecycle)
            self.assertEqual(g2.serialize_policy_config(seen["policy"]),config)
        self.assertEqual(control.iloc[0]["meta"],before_meta)
        assert_frame_equal(control,before_control,check_exact=True)
        self.assertEqual(result[1].iloc[0]["action"],"G2")

    def test_bounded_candidate_changes_only_minimum_score_gap(self):
        base=dict(g2_spec().parameters); changed=dict(g2_spec(gap=0.23).parameters)
        base_cfg=json.loads(base["hold_exit_policy_config"]); changed_cfg=json.loads(changed["hold_exit_policy_config"])
        diffs=[k for k in base_cfg["parameters"] if base_cfg["parameters"][k]!=changed_cfg["parameters"][k]]
        self.assertEqual(diffs,["minimum_score_gap"])
        self.assertNotEqual(base["hold_exit_policy_identity"],changed["hold_exit_policy_identity"])
        binding.validate_strategy_spec(g2_spec(gap=0.23))

    def test_unknown_module_and_unsupported_version_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"unknown hold_exit_module"):
            binding.validate_strategy_spec(replace(legacy_spec(),hold_exit_module="OTHER"))
        spec=g2_spec(); params=dict(spec.parameters); params["hold_exit_module_version"]="2"
        with self.assertRaisesRegex(ValueError,"unsupported G2"):
            binding.validate_strategy_spec(replace(spec,parameters=tuple(params.items())))

    def test_missing_g2_inputs_fail_closed_before_loader(self):
        spec=g2_spec(); control=pd.DataFrame()
        with patch.object(g2,"load_scored_candidate_cache") as loader:
            with self.assertRaisesRegex(ValueError,"scored-candidate"):
                binding.apply_hold_exit_module(spec,control)
            loader.assert_not_called()
        with tempfile.TemporaryDirectory() as raw:
            cache=Path(raw)/"scored.csv"; cache.write_text("x\n",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"lifecycle"):
                binding.apply_hold_exit_module(spec,control,scored_candidate_cache_path=cache)

    def test_invalid_config_identity_fails_closed(self):
        spec=g2_spec(); params=dict(spec.parameters); params["hold_exit_policy_identity"]="0"*64
        with self.assertRaisesRegex(ValueError,"config identity"):
            binding.validate_strategy_spec(replace(spec,parameters=tuple(params.items())))

    def test_missing_replacement_cost_identity_fails_closed_even_if_rehashed(self):
        spec=g2_spec(); params=dict(spec.parameters); payload=json.loads(params["hold_exit_policy_config"])
        del payload["parameters"]["round_trip_cost_penalty"]
        tampered=json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False)
        params["hold_exit_policy_config"]=tampered
        params["hold_exit_policy_identity"]=hashlib.sha256(tampered.encode()).hexdigest()
        with self.assertRaisesRegex(ValueError,"bounded minimum_score_gap"):
            binding.validate_strategy_spec(replace(spec,parameters=tuple(params.items())))

    def test_pit_flag_and_lifecycle_identity_are_not_stripped(self):
        spec=g2_spec(); control=pd.DataFrame({"ticker":["AAA"]}); scored=pd.DataFrame({"ticker":["AAA"],"pit_evidence_blocked":[True]})
        seen={}
        def fake_build(c,s,*,portfolio,lifecycle_path,policy):
            seen["pit"]=bool(s.iloc[0]["pit_evidence_blocked"]); seen["lifecycle"]=lifecycle_path
            return c,pd.DataFrame(),pd.DataFrame(),{}
        with tempfile.TemporaryDirectory() as raw:
            cache=Path(raw)/"scored.csv"; lifecycle=Path(raw)/"lifecycle.csv"
            cache.write_text("x\n",encoding="utf-8"); lifecycle.write_text("terminal\n",encoding="utf-8")
            with patch.object(g2,"load_scored_candidate_cache",return_value=scored), patch.object(g2,"build_leadership_persistence_book",side_effect=fake_build):
                binding.apply_hold_exit_module(spec,control,scored_candidate_cache_path=cache,lifecycle_path=lifecycle)
        self.assertIs(seen["pit"],True); self.assertEqual(seen["lifecycle"],lifecycle)

    def test_g2_full_runner_and_broker_fail_closed_until_treatment_materialized(self):
        main=g2_spec(); conc=g2_spec("concentrated")
        with self.assertRaisesRegex(ValueError,"post-Control/pre-broker"):
            binding.run_control(main,conc,evaluation(),args=Namespace())
        with self.assertRaisesRegex(ValueError,"materialization"):
            binding.run_broker_replays(main,conc,evaluation(),latest_run="L")
        m,c=binding.broker_specs_after_treatment(main,conc)
        self.assertEqual(m.hold_exit_module,"LEGACY"); self.assertEqual(c.hold_exit_module,"LEGACY")
        self.assertEqual(m.parameters,()); self.assertEqual(c.parameters,())

if __name__=="__main__": unittest.main(verbosity=2)

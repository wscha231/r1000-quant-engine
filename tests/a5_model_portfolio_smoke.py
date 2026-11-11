"""Native allocation presentation and strict A3/A4/A6 handoff refusals."""
import copy
from datetime import timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import a5_model_portfolio as a5
from tools import chameleon_market_context_v2 as context
from research.multi_asset_v1 import runtime
from research.multi_asset_v1.contracts import digest,stamp
from tests.multi_asset_leadership_smoke import fixture,reviewed,risk,CUTOFF


def report():
    value=dict(schema="market-analysis-report-v2",cutoff=CUTOFF,request_sha256="a"*64,status="READY_RESEARCH_ONLY",
        market_assessment=dict(ready_axis_count=8,required_axes_ready=True),
        enhanced_readiness=dict(funding=True,liquidity=True,bank_credit=True,macro=True),
        target_book_write_allowed=False,order_generation_allowed=False,ledger_mutation_allowed=False,
        funding={},liquidity={},bank_credit={},horizon_outlook=[])
    value["content_sha256"]=context.digest(value)
    return value


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.p,self.r,self.policy=fixture();reviewed(self.p,self.r,self.policy)
        self.risk=risk(self.p,self.r,self.policy);self.report=report()
        self.risk.update(a4_report_content_sha256=self.report["content_sha256"],a4_request_sha256=self.report["request_sha256"])
        self.policy["reviewed_pins"]["risk"].append(digest(self.risk))

    def test_missing_current_graph_cannot_enter_native_allocator(self):
        with patch.object(runtime,"run") as run:
            result=a5.build_model_proposal(self.p,self.r,self.policy,self.report)
            run.assert_not_called()
        self.assertEqual(result["status"],"BLOCKED")
        self.assertIsNone(result["cash"])
        self.assertIsNone(result["proposed_weights"])
        self.assertIn("unavailable",a5.render(result))

    def test_invalid_a4_risk_binding_cutoff_readiness_and_authority_refuse(self):
        for change in ("binding","cutoff","readiness","authority","hash","review"):
            value=copy.deepcopy(self.report);p=copy.deepcopy(self.p);policy=copy.deepcopy(self.policy)
            if change=="binding":p["risk"]["a4_report_content_sha256"]="b"*64
            elif change=="cutoff":value["cutoff"]="2026-09-18T22:00:00Z"
            elif change=="readiness":value["enhanced_readiness"]["bank_credit"]=False
            elif change=="authority":value["target_book_write_allowed"]=True
            elif change=="hash":value["content_sha256"]="b"*64
            else:policy["reviewed_pins"]["risk"]=[]
            if change not in {"hash","binding","review"}:
                value["content_sha256"]=context.digest({k:v for k,v in value.items() if k!="content_sha256"})
                p["risk"]["a4_report_content_sha256"]=value["content_sha256"]
                policy["reviewed_pins"]["risk"].append(digest(p["risk"]))
            with self.subTest(change=change),self.assertRaises(ValueError):a5.validate_report(value,p,policy)

    def test_real_native_weights_and_cash_are_presented_without_new_sizing(self):
        native=runtime.run(self.p,self.r,self.policy)
        self.assertEqual(native["proposal"]["status"],"RESEARCH_PROPOSAL")
        native["a3_model_input_candidates"]=self.p["evaluations"]
        value=a5._explain_result(native,self.risk,self.report)
        self.assertEqual(value["proposed_weights"],native["proposal"]["proposed_weights"])
        self.assertEqual(value["cash"],native["proposal"]["cash"])
        self.assertAlmostEqual(sum(value["proposed_weights"].values())+value["cash"],1)
        self.assertTrue(all(r["reasons"] for r in value["changes"]))
        self.assertFalse(value["actual_holdings_claimed"])
        self.assertFalse(value["accepted_target_written"])
        self.assertIn("CASH",a5.render(value))

    def test_previous_proposal_needs_external_pin_and_does_not_become_positions(self):
        native=runtime.run(self.p,self.r,self.policy)
        previous=a5._explain_result(native,self.risk,self.report)
        previous["as_of"]=(stamp(CUTOFF)-timedelta(hours=1)).isoformat()
        previous.pop("proposal_sha256");a5.seal(previous)
        with self.assertRaises(ValueError):a5._explain_result(native,self.risk,self.report,previous=previous,policy=self.policy)
        self.policy["reviewed_pins"]["model_proposal_history"]=[digest(previous)]
        value=a5._explain_result(native,self.risk,self.report,previous=previous,policy=self.policy)
        self.assertEqual(value["comparison_basis"],"PREVIOUS_MODEL_PROPOSAL")
        self.assertTrue(all(r["change"]==0 for r in value["changes"]))
        self.assertFalse(value["actual_holdings_claimed"])

    def test_nan_weight_sum_cannot_hide_bad_allocation(self):
        native=runtime.run(self.p,self.r,self.policy)
        native["proposal"]["cash"]=float("nan")
        with self.assertRaises(ValueError):a5._explain_result(native,self.risk,self.report)

    def test_actual_account_book_is_not_used_as_genesis_model(self):
        self.p["positions"]=[dict(asset_id="US:FTI",weight=.1)]
        with patch.object(runtime,"run") as run:
            result=a5.build_model_proposal(self.p,self.r,self.policy,self.report)
            run.assert_not_called()
        self.assertEqual(result["status"],"BLOCKED")

    def test_complete_original_graph_with_v2_reaches_native_a5(self):
        # Real incumbent A3/Registry, A0/A6 graph, native A4 and A5 code over
        # disposable synthetic originals. This is not actual economic admission.
        from tests.multi_asset_leadership_smoke import A3OriginalInputs,CODE_SHA
        from tests.control_plane_agent_contract_smoke import ControlPlaneTests
        candidate=A3OriginalInputs('runTest');candidate.setUp();self.addCleanup(candidate.doCleanups)
        values={"SOFR":4.2,"TGCR":4.1,"IORB":4.0,"DFF":3.98,"WALCL":7000000,"WRESBAL":3000000,
            "WDTGAL":600000,"RRPONTSYD":500,"DPSACBW027SBOG":120,"DPSDCBW027SBOG":100,
            "DPSLCBW027SBOG":70,"DPSSCBW027SBOG":30,"TOTLL":60,"TOTCI":20,
            "CASACBW027SBOG":10,"TLAACBW027SBOG":180,"UNRATE":4,"CPIAUCSL":320,
            "DGS10":4,"BAMLH0A0HYM2":3,"DTWEXBGS":120}
        extras=[(sid,("observation_date,"+sid+"\n2026-09-16,"+str(value)+"\n").encode()) for sid,value in values.items()]
        original=ControlPlaneTests.model_case
        def with_v2(case,**kwargs):
            case.a4_extra_originals=extras
            return original(case,**kwargs)
        with patch.object(ControlPlaneTests,'model_case',with_v2):
            case,_=candidate.current_review()
        value=case._model_case_risk
        candidate.p['risk'].update(a4_report_content_sha256=value['content_sha256'],a4_request_sha256=value['request_sha256'])
        candidate.policy['reviewed_pins']['risk'].append(digest(candidate.p['risk']))
        profile=candidate.policy['current_a3_review_profile']
        profile['risk_sha256']=digest(candidate.p['risk'])
        profile['policy_base_sha256']=digest({k:v for k,v in candidate.policy.items() if k!='current_a3_review_profile'})
        result=a5.build_model_proposal(candidate.p,candidate.r,candidate.policy,value,
            artifact_resolver=candidate.memory(),review_root=case.root,code_sha=CODE_SHA)
        self.assertEqual(result['status'],'RESEARCH_PROPOSAL',result)
        self.assertAlmostEqual(sum(result['proposed_weights'].values())+result['cash'],1)
        self.assertEqual(result['a4_report_content_sha256'],value['content_sha256'])
        self.assertFalse(result['orders_generated'])
        self.assertTrue(any(r['cost_assumptions'] is not None for r in result['changes']))


if __name__=="__main__":unittest.main()

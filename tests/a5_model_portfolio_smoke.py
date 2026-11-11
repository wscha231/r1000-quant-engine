"""Native allocation presentation and strict A3/A4/A6 handoff refusals."""
import copy
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
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
    def v2_originals(self):
        values={"SOFR":4.2,"TGCR":4.1,"IORB":4.0,"DFF":3.98,"WALCL":7000000,"WRESBAL":3000000,
            "WDTGAL":600000,"RRPONTSYD":500,"DPSACBW027SBOG":120,"DPSDCBW027SBOG":100,
            "DPSLCBW027SBOG":70,"DPSSCBW027SBOG":30,"TOTLL":60,"TOTCI":20,
            "CASACBW027SBOG":10,"TLAACBW027SBOG":180,"UNRATE":4,"CPIAUCSL":320,
            "DGS10":4,"BAMLH0A0HYM2":3,"DTWEXBGS":120}
        return [(sid,("observation_date,"+sid+"\n2026-09-16,"+str(value)+"\n").encode()) for sid,value in values.items()]

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

    def test_legacy_evaluations_cannot_allocate_outside_the_original_graph(self):
        self.p.update(requested_security_ids=["US:FTI"],a3_reference_entries=[],current_a3_review={})
        with patch.object(runtime,"run") as run:
            result=a5.build_model_proposal(self.p,self.r,self.policy,self.report)
            run.assert_not_called()
        self.assertEqual(result["status"],"BLOCKED")
        self.assertIsNone(result["proposed_weights"])

    def test_uncovered_allocator_cohort_is_blocked_even_without_legacy_evaluations(self):
        self.p.update(evaluations=[],requested_security_ids=["US:FTI"],a3_reference_entries=[],current_a3_review={})
        with patch.object(runtime,"run") as run:
            self.assertEqual(a5.build_model_proposal(self.p,self.r,self.policy,self.report)["status"],"BLOCKED")
            run.assert_not_called()

    def test_complete_original_graph_with_v2_reaches_native_a5(self):
        # Real incumbent A3/Registry, A0/A6 graph, native A4 and A5 code over
        # disposable synthetic originals. This is not actual economic admission.
        from tests.multi_asset_leadership_smoke import A3OriginalInputs,CODE_SHA
        from tests.control_plane_agent_contract_smoke import ControlPlaneTests
        candidate=A3OriginalInputs('runTest');candidate.setUp();self.addCleanup(candidate.doCleanups)
        candidate.r['assets']=[r for r in candidate.r['assets'] if r['asset_id'] in {'US:SPY','US:FTI'}]
        candidate.p['prices']=[r for r in candidate.p['prices'] if r['asset_id'] in {'US:SPY','US:FTI'}]
        # Controlled relative acceleration gives this single submitted original
        # a real native entry signal, rather than relying on uncovered assets.
        import math
        security=[r for r in candidate.p['prices'] if r['asset_id']=='US:FTI']
        benchmark=[r for r in candidate.p['prices'] if r['asset_id']=='US:SPY']
        for i,(row,bench) in enumerate(zip(security,benchmark)):
            factor=math.exp(.000005*i*i)
            row['price']=bench['price']*factor
            row['total_return_index']=bench['total_return_index']*factor
        candidate.market['price']=security[-1]['price']
        for h in (20,60,120,240):
            ret=security[-1]['total_return_index']/security[-1-h]['total_return_index']-1
            bench=benchmark[-1]['total_return_index']/benchmark[-1-h]['total_return_index']-1
            candidate.market['return_'+str(h)+'d']=ret
            candidate.market['benchmark_return_'+str(h)+'d']=bench
            candidate.market['rs_'+str(h)+'d']=math.log1p(ret)-math.log1p(bench)
        extras=self.v2_originals()
        original=ControlPlaneTests.model_case
        def with_v2(case,**kwargs):
            case.a4_extra_originals=extras
            return original(case,**kwargs)
        with patch.object(ControlPlaneTests,'model_case',with_v2):
            case,_=candidate.current_review()
        # This submitted cohort has one security and its benchmark; the full
        # allocator cohort now has original A3 coverage and no legacy input.
        candidate.p['evaluations']=[]
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
        self.assertTrue(all(r['cost_assumptions'] is not None for r in result['changes'] if r['weight']>0))
        self.assertTrue(set(result['proposed_weights'])<=set(candidate.p['requested_security_ids']))
        self.assertTrue(result['proposed_weights'])
        # Exercise the actual hosted entry point with a later execution clock,
        # portable originals and a pinned original policy, without mocking A5.
        import json
        from tools import run_a4_research_cycle as cycle
        from tools.macro_history_sources import encoded,digest as raw_digest
        originals={aid:raw for (aid,_),raw in candidate.refs.raw.items()}
        candidate.p['artifact_files']=[]
        for i,(aid,raw) in enumerate(originals.items()):
            name='cloud_a3_'+str(i)+'.json';(case.root/name).write_bytes(raw)
            candidate.p['artifact_files'].append(dict(artifact_id=aid,path=name,sha256=raw_digest(raw)))
        def put(name,body):
            raw=encoded(body);(case.root/name).write_bytes(raw)
            return dict(path=name,sha256=raw_digest(raw))
        request_raw=(case.root/'a4/request.json').read_bytes()
        (case.root/'request.json').write_bytes(request_raw)
        (case.root/'request.sha256').write_text(raw_digest(request_raw))
        for spec in json.loads(request_raw)['inputs']:
            (case.root/spec['path']).write_bytes((case.root/'a4'/spec['path']).read_bytes())
        model_request=dict(schema='a5-model-proposal-request-v1',inputs=put('cloud_payload.json',candidate.p),
            registry=put('cloud_registry.json',candidate.r),policy=put('cloud_policy.json',candidate.policy))
        (case.root/'a5_request.json').write_bytes(encoded(model_request))
        execution=(stamp(candidate.p['as_of'])+timedelta(minutes=2)).isoformat()
        cloud_temp=tempfile.TemporaryDirectory();self.addCleanup(cloud_temp.cleanup)
        cloud_root=Path(cloud_temp.name)
        cloud=cycle.run_cycle(input_root=case.root,state_root=cloud_root/'state',
            output_dir=cloud_root/'attempt',cutoff=execution,
            a5_policy_sha256=model_request['policy']['sha256'],code_sha=CODE_SHA)
        self.assertEqual(cloud['a5_status'],'RESEARCH_PROPOSAL',cloud)
        self.assertEqual(stamp(cloud['decision_cutoff']),stamp(candidate.p['as_of']))
        self.assertNotEqual(cloud['decision_cutoff'],execution)
        self.assertEqual(json.loads((cloud_root/'attempt/market_analysis.json').read_bytes()),value)
        for execution in (candidate.policy['current_a3_review_profile']['expires_at'],'2026-09-21T22:00:00Z'):
            with self.subTest(execution=execution),self.assertRaises(ValueError):
                # Source request freshness is checked by the cycle separately.
                a5.decision_cutoff(case.root,model_request,expected_policy_sha256=model_request['policy']['sha256'],execution_at=execution)

    def test_stock_scope_verified_model_reaches_public_consumer_and_preserves_unknown(self):
        import math
        from tests.multi_asset_leadership_smoke import A3OriginalInputs,CODE_SHA,feature_identity
        from tests.control_plane_agent_contract_smoke import ControlPlaneTests
        from tools.macro_history_sources import encoded,digest as raw_digest
        candidate=A3OriginalInputs('runTest');candidate.setUp();self.addCleanup(candidate.doCleanups)
        security=[r for r in candidate.p['prices'] if r['asset_id']=='US:FTI']
        benchmark=[r for r in candidate.p['prices'] if r['asset_id']=='US:SPY']
        for i,(row,bench) in enumerate(zip(security,benchmark)):
            factor=math.exp(.000005*i*i)
            row['price']=bench['price']*factor;row['total_return_index']=bench['total_return_index']*factor
        candidate.market['price']=security[-1]['price']
        for h in (20,60,120,240):
            ret=security[-1]['total_return_index']/security[-1-h]['total_return_index']-1
            bench=benchmark[-1]['total_return_index']/benchmark[-1-h]['total_return_index']-1
            candidate.market['return_'+str(h)+'d']=ret;candidate.market['benchmark_return_'+str(h)+'d']=bench
            candidate.market['rs_'+str(h)+'d']=math.log1p(ret)-math.log1p(bench)
        original=ControlPlaneTests.model_case;extras=self.v2_originals()
        def with_v2(case,**kwargs):
            case.a4_extra_originals=extras;return original(case,**kwargs)
        with patch.object(ControlPlaneTests,'model_case',with_v2):
            origin=ControlPlaneTests('runTest');origin.setUp();self.addCleanup(origin.doCleanups)
            model_context,model_policy,_,aid=origin.model_incumbents_case(candidate)
            self.assertEqual(aid,'US:FTI')
            candidate.policy['reviewed_pins']['positions']=model_policy['reviewed_pins']['positions']
            candidate.p['as_of']='2026-09-19T10:30:00+00:00'
            reviewed(candidate.p,candidate.r,candidate.policy);risk(candidate.p,candidate.r,candidate.policy)
            candidate.original=next(e for e in candidate.p['evaluations'] if e['asset_id']=='US:FTI')
            candidate.original['issuer_id']='CIK:1';candidate.p['evaluations']=[]
            candidate.stock_review_inputs();candidate.reseal()
            case=ControlPlaneTests('runTest');case.setUp();self.addCleanup(case.doCleanups)
            binding,_,principals=case.current_review_case(candidate,
                model_binding=(model_context,origin.root),model_policy=candidate.policy)
        candidate.p.update(current_a3_review=binding,position_book_kind='MODEL',
            model_identity=copy.deepcopy(model_context['model_state']['model_identity']))
        value=case._model_case_risk
        candidate.p['risk'].update(a4_report_content_sha256=value['content_sha256'],a4_request_sha256=value['request_sha256'])
        candidate.policy['reviewed_pins']['risk'].append(digest(candidate.p['risk']))
        candidate.policy['current_a3_review_profile']=dict(schema='current-a3-review-profile-v1',
            purpose='CURRENT_RESEARCH_FORWARD_ONLY',context_sha256=binding['portfolio_context']['sha256'],
            graph_sha256=binding['review_graph']['sha256'],binding_sha256=digest(binding),
            policy_base_sha256=digest(candidate.policy),feature_sha256=feature_identity(candidate.p,candidate.r),
            risk_sha256=digest(candidate.p['risk']),code_sha=CODE_SHA,available_at=case.at(-5.25),
            expires_at=min(case.at(30),binding['review_graph']['expires_at']),principals=principals)
        # Only dirty-source Git attestation is isolated. A3/A4/A6, MODEL proof,
        # cost/cash, optimizer and public request/policy loaders are all real.
        synthetic_code={'SYNTHETIC:TEST_ONLY':'a'*64};observed=[];real_run=runtime.run
        def native(*args,**kwargs):
            result=real_run(*args,**kwargs);observed.append(result);return result
        with patch('tools.run_multi_asset_leadership.verified_source_hashes',return_value=synthetic_code),patch.object(runtime,'run',side_effect=native):
            result=a5.build_model_proposal(candidate.p,candidate.r,candidate.policy,value,
                artifact_resolver=candidate.memory(),review_root=case.root,code_sha=CODE_SHA)
        self.assertEqual(result['status'],'RESEARCH_PROPOSAL',result)
        self.assertFalse(result['global_ranking_ready'])
        self.assertIn('US:UNMAPPED',result['full_roster_asset_ids'])
        self.assertTrue(result['comparison_allocation_only'])
        changed=next(row for row in result['changes'] if row['asset_id']=='US:FTI')
        self.assertEqual(changed['previous_model_weight'],.15)  # Original A5 proposal was .20.
        self.assertAlmostEqual(result['cash_change'],result['cash']-.85)
        self.assertFalse(result['actual_holdings_claimed']);self.assertFalse(result['orders_generated'])
        native_result=observed[0]
        with self.assertRaisesRegex(ValueError,'NOT_PREVIOUS_PROPOSAL'):
            a5._explain_result(native_result,candidate.p['risk'],value,previous={'proposed_weights':{'US:FTI':.2}},policy=candidate.policy)
        bad=copy.deepcopy(native_result);bad['proposal']['carried_position_weights']['US:FTI']=.2
        with self.assertRaisesRegex(ValueError,'COMPARISON_WEIGHTS_OR_CASH'):
            a5._explain_result(bad,candidate.p['risk'],value,policy=candidate.policy)
        for kind in ('ACTUAL','PAPER','APPROVED_TARGET'):
            bad=copy.deepcopy(candidate.p);bad['position_book_kind']=kind
            with patch.object(runtime,'run') as allocator:
                self.assertEqual(a5.build_model_proposal(bad,candidate.r,candidate.policy,value)['status'],'BLOCKED')
                allocator.assert_not_called()
        candidate.p['artifact_files']=[]
        for i,(aid,raw) in enumerate({a:b for (a,_),b in candidate.refs.raw.items()}.items()):
            name='stock_original_'+str(i)+'.bin';(case.root/name).write_bytes(raw)
            candidate.p['artifact_files'].append(dict(artifact_id=aid,path=name,sha256=raw_digest(raw)))
        def put(name,body):
            raw=encoded(body);(case.root/name).write_bytes(raw);return dict(path=name,sha256=raw_digest(raw))
        request=dict(schema='a5-model-proposal-request-v1',inputs=put('stock_input.json',candidate.p),
            registry=put('stock_registry.json',candidate.r),policy=put('stock_policy.json',candidate.policy))
        with patch('tools.run_multi_asset_leadership.verified_source_hashes',return_value=synthetic_code):
            loaded=a5.load_and_build(case.root,request,value,expected_policy_sha256=request['policy']['sha256'],
                code_sha=CODE_SHA,execution_at=(stamp(candidate.p['as_of'])+timedelta(minutes=2)).isoformat())
        self.assertEqual(loaded['proposal_sha256'],result['proposal_sha256'])


if __name__=="__main__":unittest.main()

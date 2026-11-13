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


    def replay_original(self, session="2026-01-02", *, intent="REVIEW_REBALANCE", weights=None):
        import pandas_market_calendars as mcal
        from datetime import timedelta
        date=stamp(session+"T00:00:00Z").date()
        grid=mcal.get_calendar("NYSE").schedule(start_date=date,end_date=date+timedelta(days=10))
        weights=weights or {"CONTROL":{"US:FTI":.2},"COST_AWARE_LONG_ONLY":{"US:FTI":.3}}
        value=dict(schema=a5.SCHEMA,status="RESEARCH_PROPOSAL",as_of=session+"T22:00:00Z",session=session,
            proposed_weights=weights["COST_AWARE_LONG_ONLY"],cash=1-sum(weights["COST_AWARE_LONG_ONLY"].values()),
            intent=intent,reviewed_max_gross=.9,reviewed_max_security_weight=.4,
            full_roster_asset_ids=["US:FTI","US:UNKNOWN"],a3_reference_coverage={"scope":"SYNTHETIC"},
            comparisons={arm:dict(weights=w,objective=-.01,incremental_cost_fraction=.001)
                         for arm,w in weights.items()},
            decision_clock=dict(decision_session=session,decision_at=session+"T22:00:00Z",
                                fill_mode="NEXT_NYSE_CLOSE",earliest_fill_at=grid["market_close"].iloc[1].isoformat()),
            replay_requirements=dict(fill_mode="next_close",integer_shares=True,model_cost_bps_per_side=25,
                cash_carry_mode="risk_free_rate",cash_rate_source="DGS3MO",cash_rate_lag_days=1,
                cash_carry_haircut_bps=0,cash_carry_day_count=365),**a5.SAFETY)
        for key in ("native_result_sha256","feature_sha256","policy_sha256","comparison_inputs_sha256",
                    "a4_report_content_sha256","a4_request_sha256"):
            value[key]=digest({"synthetic":key,"session":session})
        return a5.seal(value)

    def replay_export(self, originals=None):
        originals=originals or [self.replay_original()]
        return a5.prepare_model_replay_targets(originals,self.r,
            expected_proposal_hashes=[digest(p) for p in originals],expected_registry_sha256=digest(self.r))

    def test_replay_export_preserves_all_cash_dates_holds_and_originals(self):
        import json
        originals=[self.replay_original(),self.replay_original("2026-01-05",intent="HOLD_UNTIL_SCHEDULED_REVIEW"),
                   self.replay_original("2026-01-06",intent="NO_ENTRY_HOLD_CASH",
                                        weights={a:{} for a in a5.REPLAY_ARMS})]
        before=copy.deepcopy(originals);export=self.replay_export(originals)
        self.assertEqual(originals,before)
        self.assertFalse(export["decisions"][1]["rebalance_exported"])
        self.assertIn("US:UNKNOWN",export["decisions"][0]["full_roster_asset_ids"])
        for arm in a5.REPLAY_ARMS:
            rows=export["arms"][arm]
            self.assertEqual({r["rebalance_date"] for r in rows},{"2026-01-02","2026-01-06"})
            cash=[r for r in rows if r["rebalance_date"]=="2026-01-06"]
            self.assertEqual(cash,[dict(rebalance_date="2026-01-06",ticker="CASH",weight=1.0)])
        self.assertEqual(export["decisions"][0]["original_sha256"],digest(originals[0]))
        self.assertIn("NOT_CLOSED_LOOP",export["comparison_scope"])
        self.assertFalse(export["replay_executed"]);self.assertFalse(export["Source_admitted"])
        json.dumps(export,allow_nan=False)

    def test_replay_export_refuses_nan_pins_identity_duplicate_and_initial_hold(self):
        import math
        for kind in ("nan","pin","identity","duplicate","hold","same_close","weight","unknown"):
            p=self.replay_original();registry=copy.deepcopy(self.r);originals=[p]
            if kind=="nan":p["comparisons"]["CONTROL"]["weights"]["US:FTI"]=math.nan
            elif kind=="pin":p["native_result_sha256"]="bad"
            elif kind=="identity":
                next(r for r in registry["assets"] if r["asset_id"]=="US:FTI")["identity_verified"]=False
            elif kind=="duplicate":originals.append(copy.deepcopy(p))
            elif kind=="hold":p["intent"]="HOLD_UNTIL_SCHEDULED_REVIEW"
            elif kind=="same_close":p["decision_clock"]["earliest_fill_at"]="2026-01-02T21:00:00Z"
            elif kind=="weight":p["comparisons"]["CONTROL"]["weights"]["US:FTI"]=.5
            else:p["comparisons"]["CONTROL"]["weights"]={"US:UNKNOWN":.1}
            p.pop("proposal_sha256",None)
            if kind!="nan":a5.seal(p)
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                a5.prepare_model_replay_targets(originals,registry,
                    expected_proposal_hashes=[digest(x) for x in originals],expected_registry_sha256=digest(registry))
        original=self.replay_original()
        with self.assertRaisesRegex(ValueError,"ORIGINAL_PIN"):
            a5.prepare_model_replay_targets([original],self.r,
                expected_proposal_hashes=["0"*64],expected_registry_sha256=digest(self.r))

    def replay_measurement_pair(self, export=None, *, cost=25, changed_nav=False):
        from tests.nav_metrics_v2_smoke import rows,context as nav_context,binding as nav_binding,frame
        from tools import nav_metrics_v2 as nav
        export=export or self.replay_export()
        reports={};bindings={}
        for i,arm in enumerate(a5.REPLAY_ARMS):
            data=rows((99950.0,100050.0 if changed_nav and i else 99950.0,100050.0 if changed_nav and i else 99950.0))
            ctx=nav_context(data,anchor_nav=100000)
            report=nav.calculate_frame(frame(data),ctx,valuation_binding=nav_binding(data))
            report.update(execution_status="completed",trade_count=1,cost_bps_per_side=cost,
                          target_fill_coverage=dict(execution_clock_contract="explicit_cutoff_exact_next_close_v1",
                                                    coverage_complete=True,chronology_safe=True),
                          **{k:v for k,v in export["replay_requirements"].items()
                             if k!="model_cost_bps_per_side"})
            reports[arm]=report
            binding=dict(schema="a5-fixed-target-replay-binding-v1",arm=arm,export_sha256=digest(export),
                target_rows_sha256=export["target_rows_sha256_by_arm"][arm],metrics_sha256=digest(report),
                measurement_context_sha256=report["measurement_context_sha256"],
                valuation_binding_sha256=report["valuation_binding_provenance"]["sha256"])
            for key in ("price_input_sha256","identity_sha256","source_pit_binding_sha256","cash_policy_sha256",
                        "execution_policy_sha256","session_grid_sha256"):
                binding[key]=digest({"synthetic":key})
            bindings[arm]=binding
        return export,reports,bindings

    def pair(self,export,reports,bindings,*,cost=25):
        return a5.compare_model_replay_reports(export,reports,bindings,expected_export_sha256=digest(export),
            expected_report_sha256_by_arm={a:digest(r) for a,r in reports.items()},
            expected_binding_sha256_by_arm={a:digest(r) for a,r in bindings.items()},cost_bps_per_side=cost)

    def test_matched_E2_keeps_total_return_CAGR_and_per_arm_NAV_distinct(self):
        export,reports,bindings=self.replay_measurement_pair(changed_nav=True)
        result=self.pair(export,reports,bindings)
        self.assertTrue(result["paired_measurement_ready"],result)
        self.assertNotEqual(result["metrics"]["CONTROL"]["total_return"],result["metrics"]["CONTROL"]["cagr"])
        self.assertGreater(result["deltas"]["ending_capital_usd"],0)
        self.assertEqual(result["metrics"]["CONTROL"]["max_dd"],reports["CONTROL"]["max_dd"])
        self.assertIsNone(result["metrics"]["CONTROL"]["total_fees_usd"])
        self.assertFalse(result["economically_validated"]);self.assertFalse(result["closed_loop_policy_tested"])

    def test_matched_E2_refuses_one_failed_arm_and_shared_policy_drift_atomically(self):
        from tools import nav_metrics_v2 as nav
        for kind in ("blocked","legacy","RF","cash","price","cost","variable_cost","window","binding","authority"):
            export,reports,bindings=self.replay_measurement_pair()
            r=reports["COST_AWARE_LONG_ONLY"];b=bindings["COST_AWARE_LONG_ONLY"]
            if kind=="blocked":r.update(nav.blocked("ORIGINAL_MISSING"))
            elif kind=="legacy":r["status"]="completed"
            elif kind=="RF":r["status"]=nav.PARTIAL_RAW_ONLY;r["metric_admission_complete"]=False
            elif kind=="cash":r["cash_carry_haircut_bps"]=50
            elif kind=="price":b["price_input_sha256"]="f"*64
            elif kind=="cost":r["cost_bps_per_side"]=50
            elif kind=="variable_cost":
                r.update(execution_cost_mode="spread_adv_impact",
                         execution_cost_config=dict(mode="spread_adv_impact",enabled=True))
            elif kind=="window":r["start_date"]="2026-01-06"
            elif kind=="binding":b["target_rows_sha256"]="f"*64
            else:r["valid_for_production"]=True
            b["metrics_sha256"]=digest(r)
            with self.subTest(kind=kind):
                result=self.pair(export,reports,bindings)
                self.assertEqual(result["status"],"BLOCKED",result)
                self.assertIsNone(result["metrics"]);self.assertIsNone(result["deltas"])
                self.assertFalse(result["paired_measurement_ready"])

    def test_fixed_target_cost_stress_is_not_reoptimization_and_never_recharges_NAV(self):
        export,reports,bindings=self.replay_measurement_pair(cost=50)
        out=self.pair(export,reports,bindings,cost=50)
        self.assertTrue(out["paired_measurement_ready"],out)
        self.assertEqual(out["cost_relation"],"FIXED_TARGET_COST_STRESS_NO_REOPTIMIZATION")
        self.assertEqual(out["metrics"]["CONTROL"]["ending_capital_usd"],99950)
        self.assertEqual(out["deltas"]["total_return"],0)
        self.assertIn("NOT_CHARGED_AGAIN",out["fee_application"])
        from tools.execution_cost_model import EXECUTION_COST_MODE_FIXED
        for arm in a5.REPLAY_ARMS:
            reports[arm].update(execution_cost_mode=EXECUTION_COST_MODE_FIXED,
                execution_cost_config=dict(mode=EXECUTION_COST_MODE_FIXED,enabled=False))
            bindings[arm]["metrics_sha256"]=digest(reports[arm])
        self.assertTrue(self.pair(export,reports,bindings,cost=50)["paired_measurement_ready"])

    def test_matched_E2_rejects_lag_tolerant_or_incomplete_next_close_even_when_repinned(self):
        export,original_reports,original_bindings=self.replay_measurement_pair()
        for kind in ("missing","legacy","gap","chronology"):
            reports=copy.deepcopy(original_reports);bindings=copy.deepcopy(original_bindings)
            report=reports["COST_AWARE_LONG_ONLY"]
            if kind=="missing":report.pop("target_fill_coverage")
            elif kind=="legacy":report["target_fill_coverage"].pop("execution_clock_contract")
            elif kind=="gap":report["target_fill_coverage"]["coverage_complete"]=False
            else:report["target_fill_coverage"]["chronology_safe"]=False
            bindings["COST_AWARE_LONG_ONLY"]["metrics_sha256"]=digest(report)
            with self.subTest(kind=kind):
                result=self.pair(export,reports,bindings)
                self.assertEqual(result["status"],"BLOCKED")
                self.assertIsNone(result["metrics"]);self.assertIsNone(result["deltas"])


    def test_export_to_existing_E2_replay_keeps_cash_exit_and_cost_once(self):
        self.existing_E2_cash_replay((25,50,100))

    def test_exact_clock_pair_accepts_actual_broker_E2_proof(self):
        self.existing_E2_cash_replay((25,))

    def existing_E2_cash_replay(self,costs):
        import pandas as pd
        import pandas_market_calendars as mcal
        from tools import run_broker_ledger_replay as broker,nav_metrics_v2 as nav
        from tests.broker_cash_carry_smoke import _write_px
        from tests.nav_metrics_v2_smoke import context as nav_context,binding as nav_binding
        from datetime import timedelta
        originals=[self.replay_original(weights={a:{"US:FTI":.2} for a in a5.REPLAY_ARMS}),
                   self.replay_original("2026-01-05",intent="NO_ENTRY_HOLD_CASH",
                                        weights={a:{} for a in a5.REPLAY_ARMS})]
        export=self.replay_export(originals);ending=[]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cache=root/"prices";cache.mkdir()
            for ticker in ("FTI","SPY"):_write_px(cache,ticker,[100.0]*4)
            rates=root/"rates.csv";rates.write_text("DATE,DGS3MO\n2025-12-31,0\n",encoding="utf8")
            cash=broker.CashCarryConfig(mode=broker.CASH_CARRY_MODE_RISK_FREE,rate_source="DGS3MO",
                rate_lag_days=1,haircut_bps=0,day_count=365,rate_path=rates)
            paths={}
            for arm in a5.REPLAY_ARMS:
                paths[arm]=root/(arm+".csv");pd.DataFrame(export["arms"][arm]).to_csv(paths[arm],index=False)
            for cost in costs:
                base=root/("base"+str(cost))
                def replay(arm,out,ctx=None):
                    return broker.replay(target_book=paths[arm],price_cache=cache,output_dir=out,
                        portfolio_kind="main",starting_capital=100000,fill_mode="next_close",
                        cost_bps=cost,integer_shares=True,disable_concentrated_champion_filter=True,
                        evidence_end_date="2026-01-07",cash_carry_config=cash,reserve_mode="DGS3MO_CARRY",
                        measurement_context=ctx)
                before=replay("CONTROL",base)
                self.assertEqual(before["status"],"completed",before)
                curve=pd.read_csv(base/"equity_curve.csv")
                schedule=mcal.get_calendar("NYSE").schedule(start_date=curve["date"].iloc[0],end_date=curve["date"].iloc[-1])
                data=[dict(session=str(r["date"])[:10],timestamp=schedule.loc[pd.Timestamp(r["date"]),"market_close"].isoformat(),
                           nav=float(r["equity_usd"])) for r in curve.to_dict("records")]
                first=pd.Timestamp(data[0]["session"]).date()
                previous=mcal.get_calendar("NYSE").schedule(start_date=first-timedelta(days=10),end_date=first-timedelta(days=1))
                ctx=nav_context(data,anchor_nav=100000,anchor_time=previous["market_close"].iloc[-1].isoformat())
                package={"full":ctx,"valuation_binding":nav_binding(data)}
                _,_,bindings=self.replay_measurement_pair(export,cost=cost)
                reports={}
                for arm in a5.REPLAY_ARMS:
                    out=root/(arm+str(cost));reports[arm]=replay(arm,out,package)
                    r=reports[arm];self.assertEqual(r["status"],nav.COMPLETE,r)
                    bindings[arm].update(metrics_sha256=digest(r),measurement_context_sha256=r["measurement_context_sha256"],
                        valuation_binding_sha256=r["valuation_binding_provenance"]["sha256"])
                    trades=pd.read_csv(out/nav.NAMESPACE/nav.artifact_name("trades.csv"))
                    self.assertEqual(list(trades["side"]),["BUY","SELL"])
                    self.assertEqual(list(trades["date"]),["2026-01-05","2026-01-06"])
                    self.assertAlmostEqual(trades["fee_usd"].sum(),40000*cost/10000)
                    self.assertAlmostEqual(r["ending_capital_usd"],100000-trades["fee_usd"].sum())
                    self.assertAlmostEqual(r["max_dd"],r["total_return"])
                result=self.pair(export,reports,bindings,cost=cost)
                self.assertTrue(result["paired_measurement_ready"],result)
                self.assertEqual(result["deltas"]["total_return"],0)
                ending.append(result["metrics"]["CONTROL"]["ending_capital_usd"])
        for first,second in zip(ending,ending[1:]):self.assertGreater(first,second)


if __name__=="__main__":unittest.main()

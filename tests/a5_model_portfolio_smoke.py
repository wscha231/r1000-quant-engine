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

    def stock63_inputs(self):
        from tests.multi_asset_leadership_smoke import StockCashResearch,SESSIONS
        from research.er_horizon_v1 import session63_exposure
        owner=StockCashResearch("runTest")
        p,r,policy=owner.inputs()
        policy["stock_cash_research"].update(schema="stock-cash-research-v2",horizon="63_NYSE_SESSIONS")
        clock=session63_exposure(list(SESSIONS)[-1])
        for model in policy["validated_models"].values():model["horizon"]="63_NYSE_SESSIONS"
        for er in p["evaluations"]:
            self.as63(er,clock)
        policy["reviewed_pins"]["evaluation"]=[digest(er) for er in p["evaluations"]]
        review=p["risk"]["stock_cash_allocation"]
        review.update(horizon="63_NYSE_SESSIONS",minimum_expected_alpha_horizon="63_NYSE_SESSIONS",
                      evaluation_sha256_by_asset={er["asset_id"]:digest(er) for er in p["evaluations"]})
        policy["reviewed_pins"]["risk"].append(digest(p["risk"]))
        return p,r,policy,owner.memory

    def as63(self,er,clock):
        # Synthetic separately specified 63-period distribution, not conversion
        # or annualization of an existing monthly forecast.
        for h in ("1m","3m","6m","12m"):
            er.pop("expected_return_"+h,None);er.pop("benchmark_expected_return_"+h,None)
        er.update(schema="validated-er-nyse-sessions-v1",horizon="63_NYSE_SESSIONS",
            horizon_unit="NYSE_PRICE_INTERVALS",horizon_count=63,
            cost_horizon="63_NYSE_SESSIONS",downside_horizon="63_NYSE_SESSIONS",
            forecast_clock=clock,expected_return_63s=.06,benchmark_expected_return_63s=.02,
            scenarios={"63s":{"bear":{"return":-.02,"probability":.25},
                "base":{"return":.06,"probability":.5},"bull":{"return":.14,"probability":.25}}})
        er["portfolio_cost_basis"].update(schema="reviewed-portfolio-cost-basis-v2",
            horizon="63_NYSE_SESSIONS",ongoing_cost_period="HORIZON_TOTAL_BPS",gross_expected_return=.065)


    def baseline_originals(self, kind=None, arm=None):
        """Actual A1/A2/A3/A6/Native path, disposable synthetic originals only."""
        from tests.multi_asset_leadership_smoke import A3OriginalInputs, CODE_SHA
        from tests.control_plane_agent_contract_smoke import ControlPlaneTests
        from research.er_horizon_v1 import session63_exposure
        from research.multi_asset_v1.prices import grid
        from research.multi_asset_v1.runtime import feature_identity
        owner=A3OriginalInputs('runTest');owner.setUp();self.addCleanup(owner.doCleanups)
        owner.r['assets']=[r for r in owner.r['assets'] if r['asset_id'] in {'US:SPY','US:FTI'}]
        owner.p['prices']=[r for r in owner.p['prices'] if r['asset_id'] in {'US:SPY','US:FTI'}]
        import math
        security=[r for r in owner.p['prices'] if r['asset_id']=='US:FTI']
        benchmark=[r for r in owner.p['prices'] if r['asset_id']=='US:SPY']
        for i,(row,bench) in enumerate(zip(security,benchmark)):
            factor=math.exp(.000005*i*i)
            row['price']=bench['price']*factor
            row['total_return_index']=bench['total_return_index']*factor
        owner.market['price']=security[-1]['price']
        for h in (20,60,120,240):
            ret=security[-1]['total_return_index']/security[-1-h]['total_return_index']-1
            bench=benchmark[-1]['total_return_index']/benchmark[-1-h]['total_return_index']-1
            owner.market['return_'+str(h)+'d']=ret
            owner.market['benchmark_return_'+str(h)+'d']=bench
            owner.market['rs_'+str(h)+'d']=math.log1p(ret)-math.log1p(bench)
        old_stock=A3OriginalInputs.stock_review_inputs
        old_graph=ControlPlaneTests.current_review_case
        def stock63(candidate):
            old_stock(candidate)
            candidate.policy['stock_cash_research'].update(schema='stock-cash-research-v2',horizon='63_NYSE_SESSIONS')
            if kind is not None:
                candidate.policy["stock_cash_research"].update(portfolio_kind=kind,
                    portfolio_contract="portfolio-kind-v1", allocator=arm)
                candidate.p["portfolio_kind"] = kind
                candidate.p["risk"]["stock_cash_allocation"]["portfolio_kind"] = kind
            candidate.policy['validated_models']['TEST_MODEL']['horizon']='63_NYSE_SESSIONS'
            self.as63(candidate.original,session63_exposure(list(grid(candidate.p['as_of']))[-1]))
            candidate.policy['reviewed_pins']['evaluation'].append(digest(candidate.original))
            rr=candidate.p['risk']
            for key in ('regime','a4_report_content_sha256','a4_request_sha256'):rr.pop(key,None)
            rr['a5_context_profile']='STOCK_CASH_BASELINE_V1'
            rr['stock_cash_allocation'].update(horizon='63_NYSE_SESSIONS',
                minimum_expected_alpha_horizon='63_NYSE_SESSIONS',
                evaluation_sha256_by_asset={candidate.original['asset_id']:digest(candidate.original)})
            candidate.policy['a5_context_profile']='STOCK_CASH_BASELINE_V1'
            candidate.policy['reviewed_pins']['risk'].append(digest(rr))
        def graph(case,candidate,*args,**kwargs):
            case._baseline_risk=candidate.p['risk']
            case._model_policy=candidate.policy
            return old_graph(case,candidate,*args,**kwargs)
        with patch.object(A3OriginalInputs,'stock_review_inputs',stock63), \
             patch.object(ControlPlaneTests,'current_review_case',graph), \
             patch('tools.market_analysis_engine.load_report',side_effect=AssertionError('A4 must not execute')):
            case,graph=owner.current_review(stock=True)
        self.assertEqual(owner.original['feature_sha256'],feature_identity(owner.p,owner.r))
        owner.p['evaluations']=[]
        return owner,case,graph,CODE_SHA

    def baseline_call(self,owner,case,code):
        # Only dirty-checkout Git attestation is isolated for synthetic fixtures;
        # original A1/A2/A3/A6, risk, costs, Native allocation all run unchanged.
        with patch('tools.run_multi_asset_leadership.verified_source_hashes',return_value={'synthetic':'a'*64}):
            return a5.build_model_proposal(owner.p,owner.r,owner.policy,None,
                artifact_resolver=owner.memory(),review_root=case.root,code_sha=code)

    def test_baseline_full_original_graph_native_A5_and_replay_without_A4(self):
        from tools import run_agent_board as board
        owner,case,graph,code=self.baseline_originals()
        before=copy.deepcopy(case.state)
        with patch('tools.market_analysis_engine.load_report',side_effect=AssertionError('A4 must not execute')):
            result=self.baseline_call(owner,case,code)
            self.assertEqual(result['status'],'RESEARCH_PROPOSAL',result)
            self.assertEqual(result,self.baseline_call(owner,case,code))
        self.assertTrue(result['proposed_weights'])
        self.assertAlmostEqual(sum(result['proposed_weights'].values())+result['cash'],1)
        self.assertFalse(result['a4_connected'])
        self.assertIsNone(result['a4_report_content_sha256'])
        self.assertIsNone(result['a4_request_sha256'])
        self.assertIsNone(result['macro_reason_evidence'])
        self.assertIsNone(result['composite_review_context'])
        self.assertIsNone(result['market_review_handoff'])
        self.assertEqual(result['market_regime_assessment'],'NOT_SELECTED')
        self.assertFalse(result['orders_generated']);self.assertFalse(result['accepted_target_written'])
        self.assertTrue(all(r['cost_assumptions'] is not None for r in result['changes'] if r['weight']>0))
        self.assertEqual({r['agent'] for r in graph['state']['requests']},{'A1','A2','A3','A5','A6'})
        packet=next(p for p in case.tasks() if p['agent']=='A5')
        self.assertEqual(packet['status'],'READY',packet)
        self.assertNotIn('regime',packet['inputs'])
        self.assertIn('regime:source_missing',case.state['context']['blockers'])
        self.assertEqual(case.state,before)
        export=a5.prepare_model_replay_targets([result],owner.r,
            expected_proposal_hashes=[digest(result)],expected_registry_sha256=digest(owner.r))
        self.assertEqual(export['a5_context_profile'],'STOCK_CASH_BASELINE_V1')
        self.assertFalse(export['a4_connected'])
        self.assertNotIn('a4_report_content_sha256',export['decisions'][0])
        self.assertIn('reviewed_risk_sha256',export['decisions'][0])
        with self.assertRaises(ValueError):
            a5.prepare_model_replay_targets([{**result,'a4_request_sha256':'a'*64}],owner.r,
                expected_proposal_hashes=[digest({**result,'a4_request_sha256':'a'*64})],expected_registry_sha256=digest(owner.r))
        text=a5.render(result)
        self.assertIn('A4 disconnected',text)
        self.assertIsNone(board.read_json(case.root/owner.p['current_a3_review']['portfolio_context']['path']).get('a4_request'))

    def test_baseline_keeps_missing_source_g0_and_qa_failures(self):
        owner,case,graph,code=self.baseline_originals()
        for reason in ('regime:hash_mismatch','execution:source_missing','HISTORICAL_R1000_PIT_UNCERTIFIED'):
            saved=copy.deepcopy(case.state)
            case.state['context']['blockers'].append(reason)
            packet=next(p for p in case.tasks() if p['agent']=='A5')
            self.assertNotEqual(packet['status'],'READY',(reason,packet))
            case.state=saved
        case.state['g0']['status']='BLOCKED'
        self.assertNotEqual(next(p for p in case.tasks() if p['agent']=='A5')['status'],'READY')
        case.state['g0']['status']='PASS'
        graph_ref=owner.p['current_a3_review']['review_graph']
        (case.root/graph_ref['path']).write_bytes(b'changed original graph')
        result=self.baseline_call(owner,case,code)
        self.assertEqual(result['status'],'BLOCKED')
        self.assertIsNone(result['proposed_weights']);self.assertIsNone(result['cash'])

    def test_baseline_native_rejects_different_risk_even_when_both_are_reviewed_pins(self):
        from tools import run_agent_board as board
        owner,case,_,code=self.baseline_originals()
        changed=copy.deepcopy(owner.p['risk']);changed['max_gross']=.25
        owner.policy['reviewed_pins']['risk'].append(digest(changed))
        profile=owner.policy['current_a3_review_profile']
        profile['risk_sha256']=digest(changed)
        profile['policy_base_sha256']=digest({k:v for k,v in owner.policy.items() if k!='current_a3_review_profile'})
        with self.assertRaisesRegex(board.ContractError,'a3_review_baseline_original_risk_mismatch'):
            board.current_a3_reference_admission(owner.p['current_a3_review'],owner.policy,case.root,
                board.timestamp(owner.p['as_of']),code,owner.p['requested_security_ids'],
                owner.p['a3_reference_entries'],profile['feature_sha256'],changed)

    def test_baseline_model_origin_and_next_incumbent_acceptance_use_original_profile(self):
        from tools import run_agent_board as board
        from tools import run_multi_asset_leadership as publisher
        from tests.control_plane_agent_contract_smoke import ControlPlaneTests
        owner,_,_,code=self.baseline_originals()
        origin=ControlPlaneTests('runTest');origin.setUp();self.addCleanup(origin.doCleanups)
        origin._baseline_risk=owner.p['risk'];origin._model_policy=owner.policy
        context,policy,acceptance,aid=origin.model_incumbents_case(owner)
        at=board.timestamp(context['decision_time'])
        read,_=publisher._model_originals(origin.root,at,at)
        packet,receipt,original_context=publisher._model_origin(acceptance['proofs'],read,at)
        self.assertEqual(packet['dependencies'],['A3','A6'])
        self.assertNotIn('regime',packet['inputs'])
        self.assertEqual(original_context['a5_context_profile'],'STOCK_CASH_BASELINE_V1')
        result=board.verify_current_model_incumbents(context,origin.root,at,at,
            policy=policy,code_sha=code)
        self.assertEqual(result['current_weights'],{aid:.15})
        self.assertFalse(result['actual_holdings_claimed'])

    def test_model_cli_from_external_cwd_blocks_missing_originals_without_side_effects(self):
        import json,subprocess
        with tempfile.TemporaryDirectory() as folder:
            script=Path(a5.__file__).resolve()
            result=subprocess.run([sys.executable,*(['-O'] if sys.flags.optimize else []),str(script),
                '--artifact-root',folder,'--request',str(Path(folder)/'missing.json'),
                '--expected-policy-sha256','a'*64,'--code-sha','b'*40],cwd=folder,
                capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,2,result.stderr)
            value=json.loads(result.stdout)
            self.assertEqual(value['status'],'BLOCKED')
            self.assertIsNone(value['proposed_weights']);self.assertIsNone(value['cash'])
            self.assertFalse(value['orders_generated'])
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_baseline_requires_explicit_63_policy_pinned_risk_and_no_special_risk(self):
        from research.multi_asset_v1.contracts import a5_context_profile,baseline_risk
        self.assertEqual(a5_context_profile({}),'STRICT_A4_V1')
        with self.assertRaises(ValueError):a5_context_profile({'a5_context_profile':'STOCK_CASH_BASELINE_V1'})
        p,r,policy,_=self.stock63_inputs()
        policy['a5_context_profile']='STOCK_CASH_BASELINE_V1'
        rr=p['risk'];rr.pop('regime');rr['a5_context_profile']='STOCK_CASH_BASELINE_V1'
        policy['reviewed_pins']['risk'].append(digest(rr))
        self.assertIs(baseline_risk(rr,policy,p['as_of']),rr)
        for updates in ({'regime':None},{'a4_request_sha256':'a'*64},
                        {'stock_cash_allocation':{**rr['stock_cash_allocation'],
                            'exception_reviews':[{'basis':'SPECIAL_RISK'}]}}):
            bad={**rr,**updates};policy['reviewed_pins']['risk'].append(digest(bad))
            with self.assertRaises(ValueError):baseline_risk(bad,policy,p['as_of'])
        with self.assertRaises(ValueError):a5.validate_report(report(),p,policy)
        with self.assertRaises(ValueError):a5.validate_report(None,p,self.policy)

    def test_period_end_review_with_holiday_event_and_separate_next_fill(self):
        from research.multi_asset_v1.decisions import stock_decision_clock
        profile = dict(cadence="WEEKLY", schedule_basis="NYSE_PERIOD_END")
        def clock(cutoff, previous=None, events=()):
            return stock_decision_clock(cutoff, profile, {"previous_decision_at":previous}, events)

        self.assertTrue(clock("2021-09-30T20:15:00Z")["scheduled_due"])
        self.assertFalse(clock("2024-03-27T20:10:00Z")["scheduled_due"])
        # Good Friday closed the market on the calendar month and week's final weekday.
        month_end = "2024-03-28T20:10:00Z"
        self.assertTrue(clock(month_end)["scheduled_due"])
        self.assertEqual(stamp(clock(month_end)["earliest_fill_at"]).date().isoformat(), "2024-04-01")
        self.assertFalse(clock("2024-04-01T20:10:00Z", month_end)["scheduled_due"])
        profile["cadence"] = "MONTHLY_CONFIRMED_EVENT"
        before, after = "2024-03-26T20:05:00Z", "2024-03-26T20:20:00Z"
        event = dict(event_id="SEC:1",confirmed=True,materiality=.8,material_change_times=[after])
        self.assertFalse(clock(before, events=[event])["scheduled_due"])
        at_review = clock(after, before, [event])
        self.assertEqual(at_review["confirmed_new_event_ids"], ["SEC:1"])
        self.assertTrue(at_review["scheduled_due"])
        self.assertFalse(clock("2024-03-27T20:10:00Z", after, [event])["scheduled_due"])
        # An earlier event in this same month cannot suppress the regular month-end review.
        self.assertTrue(clock(month_end, after, [event])["scheduled_due"])
        self.assertFalse(clock("2024-03-28T20:15:00Z",month_end,[event])["scheduled_due"])
        _, _, policy, _ = self.stock63_inputs()
        policy["stock_cash_research"]["schedule_basis"] = "NYSE_PERIOD_END"
        self.assertEqual(runtime.stock_comparison_plan(policy)["shared"]["schedule_basis"], "NYSE_PERIOD_END")
        policy["stock_cash_research"]["schedule_basis"] = "UNKNOWN"
        with self.assertRaisesRegex(ValueError, "stock_schedule_basis"):
            runtime.stock_comparison_plan(policy)

    def test_repeated_calendar_queries_keep_exact_close_and_private_mapping(self):
        from research.multi_asset_v1.prices import grid
        early = "2024-11-29T18:00:00Z"
        before = grid("2024-11-29T17:59:59Z", 1)
        self.assertEqual(list(before), ["2024-11-27"])
        after = grid(early, 2)
        self.assertEqual(list(after), ["2024-11-27", "2024-11-29"])
        after.clear()
        self.assertEqual(list(grid("2024-11-29T13:00:00-05:00", 2)), ["2024-11-27", "2024-11-29"])
        self.assertEqual(list(grid(early, 1)), ["2024-11-29"])

    def test_stock63_clock_matches_existing_learner_and_cash_exposure(self):
        import pandas as pd
        from tools.run_run287_expected_return_challenger import expected_nyse_label_ends
        from research.er_horizon_v1 import session63_exposure
        from research.multi_asset_v1.decisions import stock_decision_clock
        for day in ("2026-11-25","2026-10-30","2024-02-28"):
            exposure=session63_exposure(day)
            end=expected_nyse_label_ends(pd.Series([day]),63).iloc[0].date().isoformat()
            self.assertEqual(stamp(exposure["mark_at"]).date().isoformat(),end)
            self.assertEqual(exposure["held_intervals"],63)
            self.assertEqual(exposure["carry_calendar_days"],
                (stamp(exposure["mark_at"]).date()-stamp(exposure["entry_at"]).date()).days)
        self.assertEqual(stamp(session63_exposure("2026-11-25")["entry_at"]).hour,18)
        self.assertEqual(stamp(session63_exposure("2026-10-30")["entry_at"]).hour,21)
        legacy=stock_decision_clock(CUTOFF,{"cadence":"MONTHLY"},{},[])
        self.assertEqual(legacy["horizon"],"12_CALENDAR_MONTHS")
        self.assertNotIn("forecast_clock",legacy)
        with self.assertRaises(ValueError):
            stock_decision_clock(CUTOFF,{"schema":"stock-cash-research-v2","cadence":"MONTHLY"},{},[])
        p,r,policy,memory=self.stock63_inputs()
        clock=stock_decision_clock(CUTOFF,policy["stock_cash_research"],{},[])
        self.assertEqual(clock["covariance_scale_sessions"],63)
        self.assertGreater(clock["pre_entry_calendar_days"],0)
        self.assertEqual(clock["horizon_end"],stamp(clock["forecast_clock"]["mark_at"]).date().isoformat())
        self.assertTrue(clock["holding_horizon_is_not_an_exit_instruction"])

    def test_portfolio_kind_bound_to_request_reviewed_risk_and_incumbents(self):
        for kind in ("main", "concentrated"):
            p, registry, policy, memory = self.stock63_inputs()
            policy["stock_cash_research"].update(portfolio_contract="portfolio-kind-v1", portfolio_kind=kind)
            with self.assertRaisesRegex(ValueError, "stock_portfolio_request_mismatch"):
                runtime.run(p, registry, policy, artifact_resolver=memory)
            p["portfolio_kind"] = kind
            mismatch = runtime.run(p, registry, policy, artifact_resolver=memory)
            self.assertEqual(mismatch["proposal"]["status"], "BLOCKED")
            self.assertIn("stock_portfolio_risk_mismatch", str(mismatch["proposal"]))
            p["risk"]["stock_cash_allocation"]["portfolio_kind"] = kind
            policy["reviewed_pins"]["risk"].append(digest(p["risk"]))
            result = runtime.run(p, registry, policy, artifact_resolver=memory)
            self.assertEqual(result["proposal"]["status"], "RESEARCH_PROPOSAL", result["proposal"])
            self.assertEqual(result["stock_research"]["portfolio_kind"], kind)
            p.update(position_book_kind="PAPER", positions=[{"asset_id": "US:CCJ", "weight": .01}])
            with self.assertRaisesRegex(ValueError, "stock_portfolio_model_book_required"):
                runtime.run(p, registry, policy, artifact_resolver=memory)
            other_kind = "MAIN" if kind == "concentrated" else "CONCENTRATED"
            p.update(position_book_kind="MODEL", model_identity={"model_id": "RESEARCH:" + other_kind})
            policy["stock_cash_research"]["model_identity_sha256"] = digest(p["model_identity"])
            with self.assertRaisesRegex(ValueError, "stock_portfolio_incumbent_identity"):
                runtime.run(p, registry, policy, artifact_resolver=memory)

    def test_portfolio_kind_applies_native_sector_limit(self):
        from research.multi_asset_v1.decisions import _stock_replacement_concentration
        weights = {"AAA": .55, "BBB": .45}
        rows = {ticker: {"hold_exit_evidence": {"record": {"ticker": ticker, "sector": ticker}}}
                for ticker in weights}
        with self.assertRaisesRegex(ValueError, "sector_limit"):
            _stock_replacement_concentration(weights, weights, rows, "sector_limit", portfolio_kind="main")
        audit = _stock_replacement_concentration(weights, weights, rows, "sector_limit",
                                                 portfolio_kind="concentrated")
        self.assertEqual(audit["note"], "pass")

    def test_native_A5_genesis_proposals_enter_four_separate_books(self):
        import pandas as pd
        from r1000_legacy_input_guard import latest_completed_close
        packets = {}
        for kind in ("main", "concentrated"):
            for arm in a5.REPLAY_ARMS:
                owner, case, _, code = self.baseline_originals(kind, arm)
                packets[kind, arm] = dict(payload=owner.p, registry=owner.r, policy=owner.policy,
                    artifact_resolver=owner.memory(), review_root=case.root, code_sha=code)
        date = latest_completed_close(owner.p["as_of"])[0]
        marks = {"FTI": pd.DataFrame({"close": [100.]}, index=pd.to_datetime([date]))}
        with patch("tools.run_multi_asset_leadership.verified_source_hashes", return_value={"fixture": "a"*64}):
            result = a5.trace_stock_research_books(marks, [date], evidence_end_date=date,
                load_reviewed_packet=lambda kind, arm, snapshot: packets[kind, arm])
        for book in result["books"].values():
            self.assertEqual(book["decisions"][0]["weights"], {"CASH": 1.0})
            self.assertTrue(book["terminal_pending"])
            self.assertEqual(book["trades"], ())
        self.assertFalse(result["performance_measured"])

    def test_closed_loop_four_books_advance_own_fills_and_ignore_future_rows(self):
        import pandas as pd
        _, registry, _ = fixture()
        sessions = ["2026-11-16", "2026-11-17", "2026-11-18"]
        marks = {"CCJ": [100., 110., 105.], "FTI": [50., 45., 48.]}
        prices = {s: pd.DataFrame({"close": values}, index=pd.to_datetime(sessions)) for s, values in marks.items()}

        def load(kind, arm, snapshot):
            payload = dict(portfolio_kind=kind, as_of=snapshot.session+"T22:00:00Z",
                           marked=dict(snapshot.weights))
            if snapshot.session != sessions[0]:
                payload.update(position_book_kind="MODEL", model_identity={"model_id": arm+":"+kind.upper()})
            profile = dict(portfolio_kind=kind, portfolio_contract="portfolio-kind-v1", allocator=arm,
                           cost_bps_per_side=25, horizon="63_NYSE_SESSIONS")
            return dict(payload=payload, policy={"stock_cash_research": profile}, registry=registry,
                        review_root=None, code_sha="a"*40)

        def choose(payload, registry, policy, *args, **kwargs):
            arm = policy["stock_cash_research"]["allocator"]
            ticker = "FTI" if arm == "CONTROL" else "CCJ"
            weight = .30 if payload["portfolio_kind"] == "main" else .55
            prior = payload["marked"]
            changes = [dict(asset_id="US:"+s, previous_model_weight=prior.get(s, 0),
                            weight=weight if s == ticker else 0) for s in marks]
            return dict(status="RESEARCH_PROPOSAL", portfolio_kind=payload["portfolio_kind"],
                        session=payload["as_of"][:10], allocation_horizon="63_NYSE_SESSIONS",
                        changes=changes, intent="REVIEW_REBALANCE", proposal_sha256=digest(changes))

        def trace(market, reader=load):
            return a5.trace_stock_research_books(market, sessions[:2], evidence_end_date=sessions[-1],
                                                 load_reviewed_packet=reader)
        with patch.object(a5, "build_model_proposal", side_effect=choose):
            result = trace(prices)
            future = {s: pd.concat([frame, pd.DataFrame({"close": [999.]},
                       index=pd.to_datetime(["2026-11-19"]))]) for s, frame in prices.items()}
            self.assertEqual(result, trace(future))
            mutable_sessions = sessions[:2]
            mutable_prices = {s: f.copy(deep=True) for s, f in prices.items()}
            calls = []
            def mutate_after_first(kind, arm, snapshot):
                if not calls:
                    mutable_sessions.clear()
                    mutable_prices["FTI"].iloc[1, 0] = 99999.
                calls.append(snapshot.session)
                return load(kind, arm, snapshot)
            isolated = a5.trace_stock_research_books(mutable_prices, mutable_sessions,
                evidence_end_date=sessions[-1], load_reviewed_packet=mutate_after_first)
            self.assertEqual(isolated, result)
            self.assertEqual(calls, [sessions[0]] * 4 + [sessions[1]] * 4)
            books = result["books"]
            for kind in ("main", "concentrated"):
                for arm, symbol in (("CONTROL", "FTI"), ("COST_AWARE_LONG_ONLY", "CCJ")):
                    d0, d1 = books[kind+"/"+arm]["decisions"]
                    self.assertEqual(d0["shares"], {})
                    self.assertEqual(set(d1["shares"]), {symbol})
                    self.assertLess(d1["cash"], d0["cash"])
            self.assertGreater(books["concentrated/CONTROL"]["decisions"][1]["shares"]["FTI"],
                               books["main/CONTROL"]["decisions"][1]["shares"]["FTI"])
            def stale(kind, arm, snapshot):
                packet = load(kind, arm, snapshot)
                packet["payload"]["marked"] = {"CASH": 1.0}
                return packet
            with self.assertRaisesRegex(ValueError, "DIFFER_FROM_FILLS"):
                trace(prices, stale)

    def test_comparison_end_requires_completed_nyse_session(self):
        _, _, policy, _ = self.stock63_inputs()
        self.assertEqual(runtime.stock_comparison_plan(policy)["shared"]["end"], "2026-11-06")
        profile = policy["stock_cash_research"]
        for date, valid in (("2026-11-18", True), ("2026-11-15", False), ("2026-11-19", False)):
            profile["comparison_end_session"] = date
            if valid:
                plan = runtime.stock_comparison_plan(policy, latest_completed_session="2026-11-18")
                self.assertEqual(plan["shared"]["end"], date)
            else:
                with self.assertRaisesRegex(ValueError, "stock_comparison_end"):
                    runtime.stock_comparison_plan(policy, latest_completed_session="2026-11-18")

    def test_stock63_actual_runtime_allocates_without_month_alias_and_cost_twice(self):
        from research.multi_asset_v1.decisions import _stock_cost
        p,r,policy,memory=self.stock63_inputs()
        original=copy.deepcopy(p)
        result=runtime.run(p,r,policy,artifact_resolver=memory)
        proposal=result["proposal"]
        self.assertEqual(proposal["status"],"RESEARCH_PROPOSAL",proposal)
        self.assertEqual(p,original)
        self.assertEqual(result["allocation_horizon"],"63_NYSE_SESSIONS")
        self.assertGreater(sum(proposal["proposed_weights"].values()),0)
        self.assertEqual(proposal["comparison_inputs"]["expected_return_horizon"],"63_NYSE_SESSIONS")
        self.assertTrue(all(abs(v-.065)<1e-12 for v in proposal["comparison_inputs"]["gross_er"]))
        self.assertEqual(proposal["comparison_inputs"]["side_cost"],[.0025]*3)
        for row in result["multi_asset_leadership_latest"]:
            self.assertIsNone(row["expected_return_12m"])
            self.assertAlmostEqual(row["expected_alpha_63s"],.04)
        self.assertIn("ER 63 NYSE intervals",runtime.render(result))
        basis=p["evaluations"][0]
        gross,side=_stock_cost(basis,25,policy["stock_cash_research"])
        self.assertAlmostEqual(gross-2*side,.06)
        self.assertFalse(proposal["orders_generated"])

    def test_stock63_wrong_period_model_cost_threshold_and_forecast_refuse(self):
        for name in ("model","horizon","forecast","downside","cost","expense","threshold","schema"):
            p,r,policy,memory=self.stock63_inputs();er=p["evaluations"][0]
            if name=="model":policy["validated_models"]["TEST_MODEL"]["horizon"]="12_CALENDAR_MONTHS"
            elif name=="horizon":er["horizon_count"]=True
            elif name=="forecast":er["forecast_clock"]={**er["forecast_clock"],"held_intervals":62}
            elif name=="downside":er["downside_horizon"]="12_CALENDAR_MONTHS"
            elif name=="cost":er["portfolio_cost_basis"]["horizon"]="12_CALENDAR_MONTHS"
            elif name=="expense":er["portfolio_cost_basis"]["ongoing_cost_period"]="ANNUAL_BPS"
            elif name=="threshold":p["risk"]["stock_cash_allocation"].pop("minimum_expected_alpha_horizon")
            else:policy["stock_cash_research"]["schema"]="stock-cash-research-v1"
            policy["reviewed_pins"]["evaluation"].append(digest(er))
            p["risk"]["stock_cash_allocation"]["evaluation_sha256_by_asset"]={e["asset_id"]:digest(e) for e in p["evaluations"]}
            policy["reviewed_pins"]["risk"].append(digest(p["risk"]))
            with self.subTest(name=name):
                try:result=runtime.run(p,r,policy,artifact_resolver=memory)
                except ValueError:
                    self.assertEqual(name,"schema")
                else:self.assertEqual(result["proposal"]["status"],"BLOCKED",result["proposal"])

    def test_stock63_original_A3_registry_handoff_keeps_new_horizon(self):
        from tests.multi_asset_leadership_smoke import A3OriginalInputs
        from research.er_horizon_v1 import session63_exposure
        owner=A3OriginalInputs("runTest");owner.setUp()
        owner.stock_review_inputs()
        owner.policy["stock_cash_research"].update(schema="stock-cash-research-v2",horizon="63_NYSE_SESSIONS")
        owner.policy["validated_models"]["TEST_MODEL"]["horizon"]="63_NYSE_SESSIONS"
        from research.multi_asset_v1.prices import grid
        self.as63(owner.original,session63_exposure(list(grid(CUTOFF))[-1]))
        owner.policy["reviewed_pins"]["evaluation"].append(digest(owner.original))
        owner.reseal()
        # Existing Registry performs actual sealed A3 replay; current A3/A6
        # review remains mandatory before runtime accepts the ER for sizing.
        result=owner.execute()
        record=result["a3_reference_coverage"]["records"][0]
        self.assertTrue(record["original_runtime_contract_verified"],record)
        self.assertFalse(record["runtime_evaluation_admitted"])
        self.assertEqual(record["blocker"],"CURRENT_A3_REVIEW_ADMISSION_REQUIRED")
        self.assertEqual(result["proposal"]["status"],"BLOCKED")

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

    def test_joint_review_carries_native_signals_without_changing_the_proposal(self):
        native=runtime.run(self.p,self.r,self.policy)
        native['a3_model_input_candidates']=self.p['evaluations']
        original=copy.deepcopy(native)
        market=copy.deepcopy(self.report)
        market['composite_review_context']={'schema':'a4-composite-review-context-v1',
            'families':{'options':{'gamma_status':'GAMMA_NOT_VERIFIED'}}}
        market['review_handoff']={'candidate':'RISK_WORSENING','portfolio_effect_allowed':False}
        market.pop('content_sha256');market['content_sha256']=context.digest(market)
        value=a5._explain_result(native,self.risk,market,policy=self.policy)
        self.assertEqual(native,original)
        self.assertEqual(value['proposed_weights'],native['proposal']['proposed_weights'])
        self.assertEqual(value['cash'],native['proposal']['cash'])
        rows={r['asset_id']:r for r in native['multi_asset_leadership_latest']}
        for change in value['changes']:
            row=rows[change['asset_id']];evidence=change['decision_evidence']
            self.assertEqual(evidence['native_review_status'],row['portfolio_status'])
            self.assertEqual(evidence['risk_adjusted_expected_alpha_rank'],row['rank'])
            self.assertEqual(evidence['discovery_rank'],row['discovery_rank'])
            self.assertEqual(evidence['market_relative']['rs']['60'],row['RS60'])
            self.assertEqual(evidence['market_relative']['benchmark_id'],self.policy['benchmark_id'])
            self.assertEqual(evidence['trading']['volume_acceleration'],row['volume_acceleration'])
            self.assertEqual(evidence['thesis']['thesis_status'],row['thesis_status'])
            self.assertIsNone(evidence['sector_relative']['value'])
            self.assertEqual(evidence['accepted_exit_reviews'],[])
            self.assertFalse(evidence['new_decision_computed'])
        self.assertIn('Joint review evidence',a5.render(value))
        value['composite_review_context']['families']['options']['gamma_status']='changed copy'
        self.assertEqual(market['composite_review_context']['families']['options']['gamma_status'],'GAMMA_NOT_VERIFIED')

    def test_hold_reduce_and_exit_reviews_remain_distinct_from_accepted_reductions(self):
        from research.multi_asset_v1.decisions import classify
        base=dict(RS20=-.03,RS60=.02,RS120=.1,RS240=.2,RS20_change_5d=-.01,RS60_change_5d=-.01)
        for thesis,features,expected in (('INTACT',base,'HOLD'),
                ('NEGATIVE',{**base,'RS120':-.01},'REDUCE_REVIEW'),('INVALID',base,'EXIT_REVIEW')):
            evaluation=dict(thesis_status=thesis,valuation_acceptable=True)
            leadership,status=classify(features,evaluation,held=True)
            self.assertEqual(status,expected)
            row=dict(asset_id='US:FTI',portfolio_status=status,leadership_state=leadership,**features,**evaluation)
            out=a5.decision_evidence(row,evaluation,{},
                {'review_handoff':{'candidate':'RISK_WORSENING'}},self.policy)
            self.assertEqual(out['native_review_status'],expected)
            self.assertEqual(out['accepted_exit_reviews'],[])
            self.assertFalse(out['market_context_is_security_exit_approval'])
            if expected=='HOLD':self.assertTrue(out['review_tensions'])
        for taxonomy in ('THESIS_EXIT','RISK_EXIT','REPLACEMENT_EXIT','LIFECYCLE_EXIT'):
            audit=dict(asset_id='US:FTI',taxonomy=taxonomy,review_sha256='b'*64,prior_weight=.1,max_weight=0)
            other=dict(asset_id='US:CCJ',taxonomy='THESIS_EXIT',review_sha256='c'*64)
            proposal={'exit_reviews':[audit,other]}
            out=a5.decision_evidence(row,evaluation,proposal,
                {'review_handoff':{'candidate':'RISK_EASING'}},self.policy)
            self.assertEqual(out['accepted_exit_reviews'],[audit])
            self.assertTrue(out['review_tensions'])
            out['accepted_exit_reviews'][0]['max_weight']=.5
            self.assertEqual(audit['max_weight'],0)

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

    def test_stock63_complete_original_graph_reaches_public_A5(self):
        from tests.multi_asset_leadership_smoke import A3OriginalInputs
        from research.er_horizon_v1 import session63_exposure
        from research.multi_asset_v1.prices import grid
        old_stock=A3OriginalInputs.stock_review_inputs
        old_review=A3OriginalInputs.current_review
        old_build=a5.build_model_proposal
        observed=[]
        def stock63(owner):
            old_stock(owner)
            owner.policy["stock_cash_research"].update(schema="stock-cash-research-v2",horizon="63_NYSE_SESSIONS")
            owner.policy["validated_models"]["TEST_MODEL"]["horizon"]="63_NYSE_SESSIONS"
            self.as63(owner.original,session63_exposure(list(grid(owner.p["as_of"]))[-1]))
            owner.policy["reviewed_pins"]["evaluation"].append(digest(owner.original))
            owner.p["risk"]["stock_cash_allocation"].update(horizon="63_NYSE_SESSIONS",
                minimum_expected_alpha_horizon="63_NYSE_SESSIONS",
                evaluation_sha256_by_asset={owner.original["asset_id"]:digest(owner.original)})
            owner.policy["reviewed_pins"]["risk"].append(digest(owner.p["risk"]))
        def review(owner,*args,**kwargs):
            with patch.object(A3OriginalInputs,"stock_review_inputs",stock63):
                return old_review(owner,*args,**{**kwargs,"stock":True})
        def build(*args,**kwargs):
            value=old_build(*args,**kwargs);observed.append(value);return value
        # Only dirty-checkout Git attestation is isolated. Real A3/Registry,
        # current A0/A6 graph, A4 reader and public A5 all execute unchanged.
        with patch.object(A3OriginalInputs,"current_review",review), \
             patch("tools.run_multi_asset_leadership.verified_source_hashes",return_value={"synthetic":"a"*64}), \
             patch.object(a5,"build_model_proposal",side_effect=build):
            self.test_complete_original_graph_with_v2_reaches_native_a5()
        self.assertEqual(len(observed),2)  # direct public call and hosted cycle
        for value in observed:
            self.assertEqual(value["allocation_horizon"],"63_NYSE_SESSIONS")
            self.assertTrue(value["proposed_weights"])
            self.assertFalse(value["orders_generated"])
            self.assertFalse(value["accepted_target_written"])
            self.assertTrue(all("expected_return_63s" in row and "expected_return_12m" not in row
                                for row in value["changes"]))

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

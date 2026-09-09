"""Synthetic integrated-engine seam tests, not end-to-end H1 market admission.

Only export replay is mocked, transparently. All quality/valuation/FX/ranking/
portfolio/funding/decision-ledger functions below are actual production source.
No real issuer receives a synthetic approval and no order path is called.
"""
import copy
import importlib.util
from pathlib import Path
import sys
import subprocess
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.research_decision_v1 import engine, data

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
q=load('quality_fixture','tests/research_quality_v1_smoke.py')
f=load('funding_fixture','tests/research_workflow_funding_smoke.py')

def quality_entry(sid='US:EXAM'):
    packet,corpus=q.make_packet()
    packet['security_id']=sid
    for src in corpus.values(): src['issuer_id']=sid
    return {'packet':packet,'corpus':corpus,'receipt':q.receipt(packet,corpus),'baseline':None}

def bundle(entries=None):
    return {'schema_version':'research-quality-bundle-v1','data_kind':'SYNTHETIC',
            'decision_cutoff':f.CUTOFF,'assessments':entries if entries is not None else {'US:EXAM':quality_entry()}}

def run(secs=None,ctx=None,b=None,previous=None):
    secs=secs if secs is not None else [f.security()]
    exports=[]
    for market in sorted({s['market'] for s in secs}):
        exports.append({'market':market,'data_kind':'SYNTHETIC','decision_cutoff':f.CUTOFF,
                        'export_hash':('a' if market=='US' else 'b')*64,
                        'securities':[s for s in secs if s['market']==market]})
    with patch.object(engine,'replay_export',side_effect=lambda e:copy.deepcopy(e)):
        return engine.run_decisions(exports,ctx or f.context(),f.CONFIG,previous,quality_bundle=b if b is not None else bundle())

class IntegratedQualityTests(unittest.TestCase):
    def test_reviewed_quality_reaches_actual_portfolio(self):
        d=run();r=d['ranking'][0];p=d['portfolio_proposal']
        self.assertTrue(r['quality_gate']['eligible'])
        self.assertEqual(r['four_questions']['good_company'],'pass')
        self.assertEqual(r['four_questions']['portfolio_value'],'pass_research_only')
        self.assertTrue(p['ready']);self.assertGreater(p['rows'][0]['target_weight'],0.)
        self.assertIn('funding',p)
        self.assertEqual(d['workflow']['mode'],'QUALITY_CONNECTED_RESEARCH')
        self.assertFalse(d['readiness']['orders_allowed'])

    def test_bare_legacy_label_cannot_allocate_in_quality_mode(self):
        d=run(b=bundle({}));r=d['ranking'][0]
        self.assertTrue(r['valuation_ready'])
        self.assertFalse(r['quality_gate']['eligible'])
        self.assertIsNone(r['investment_rank'])
        self.assertEqual(d['portfolio_proposal']['rows'][0]['target_weight'],0.)
        self.assertFalse(d['readiness']['research_ranking_ready'])

    def test_no_quote_match_no_allocation(self):
        b=bundle();e=b['assessments']['US:EXAM'];e['packet']['claims'][0]['evidence'][0]['quote']='not in source'
        e['receipt']=q.receipt(e['packet'],e['corpus'])
        r=run(b=b)
        self.assertEqual(r['portfolio_proposal']['rows'][0]['target_weight'],0.)

    def test_price_missing_preserves_business(self):
        s=f.security();s.update(blockers=['price:missing'],discovery=None,data_quality_pass=False)
        r=run([s])['ranking'][0]
        self.assertEqual(r['four_questions']['good_company'],'pass')
        self.assertFalse(r['valuation_ready']);self.assertIsNone(r['investment_rank'])

    def test_capital_missing_preserves_quality_and_global_rank(self):
        c=f.context();del c['capital_krw']
        d=run(ctx=c)
        self.assertEqual(d['ranking'][0]['investment_rank'],1)
        self.assertEqual(d['ranking'][0]['four_questions']['good_company'],'pass')
        self.assertFalse(d['portfolio_proposal']['ready'])

    def test_fx_conversion_does_not_erase_quality_failure(self):
        b=bundle();e=b['assessments']['US:EXAM']
        e['packet']['claims'][4].update(impact='adverse',severity='critical')
        e['receipt']=q.receipt(e['packet'],e['corpus'])
        d=run(b=b);r=d['ranking'][0]
        self.assertEqual(r['four_questions']['good_company'],'fail')
        self.assertEqual(r['four_questions']['good_stock'],'fail')
        self.assertNotEqual(r['four_questions']['buy_price_now'],'pass')
        self.assertIsNone(r['investment_rank'])

    def test_old_method_receipt_does_not_reapprove(self):
        b=bundle();b['assessments']['US:EXAM']['receipt']['subject_hash']='0'*64
        self.assertFalse(run(b=b)['ranking'][0]['quality_gate']['eligible'])

    def test_partial_company_does_not_get_neutral_grade(self):
        b=bundle();e=b['assessments']['US:EXAM'];e['packet']['claims'].pop()
        e['receipt']=q.receipt(e['packet'],e['corpus'])
        d=run(b=b)
        self.assertEqual(d['ranking'][0]['four_questions']['good_company'],'unverified')
        self.assertIsNone(d['ranking'][0]['investment_rank'])

    def test_missing_quality_incumbent_preserves_whole_book(self):
        c=f.context();c.update(mode='EXISTING_BOOK_PROPOSAL',book={
            'source':'https://fixture.example.org/book','decision_cutoff':f.CUTOFF,'currency':'KRW',
            'verified_at':f.CUTOFF,'pending_orders':[], 'positions':{'US:EXAM':.15},'cash_weight':.85})
        d=run(ctx=c,b=bundle({}));p=d['portfolio_proposal']
        self.assertFalse(p['ready']);self.assertEqual(p['rows'][0]['action'],'HOLD')
        self.assertEqual(p['rows'][0]['target_weight'],.15)

    def test_invalid_bundle_identity_is_not_silent_fallback(self):
        for field,value in [('data_kind','REAL'),('decision_cutoff','2026-01-01T00:00:00Z')]:
            b=bundle();b[field]=value
            with self.assertRaises(ValueError):run(b=b)

    def test_unknown_company_and_legacy_score_bundle_rejected(self):
        b=bundle({'US:OTHER':quality_entry('US:OTHER')})
        with self.assertRaises(ValueError):run(b=b)
        b=bundle();b['engine_score']=1.
        with self.assertRaises(ValueError):run(b=b)

    def test_multiple_candidates_excludes_unreviewed_from_investment_rank(self):
        secs=[f.security('US:EXAM'),f.security('US:NEXT')]
        d=run(secs,b=bundle())
        rows={r['security_id']:r for r in d['ranking']}
        self.assertEqual(rows['US:EXAM']['investment_rank'],1)
        self.assertIsNone(rows['US:NEXT']['investment_rank'])
        self.assertIsNotNone(rows['US:NEXT']['expected_return_rank'])

    def test_sensitivity_does_not_reinstate_quality_failed_rank(self):
        d=run(b=bundle({}));r=d['ranking'][0]
        self.assertEqual(r['rank_sensitivity']['status'],'blocked_quality')

    def test_previous_decision_replays_without_false_secret_or_rank_rejection(self):
        d=run();again=run(previous=d)
        self.assertEqual(again['previous_decision_hash'],d['decision_hash'])
        self.assertEqual(again['ranking'][0]['rank_change_reasons'],['unchanged'])

    def test_receipt_change_is_tracked_not_price_change(self):
        old=run();b=bundle();b['assessments']['US:EXAM']['receipt']['subject_hash']='0'*64
        new=run(b=b,previous=old)
        changes=new['ranking'][0]['rank_change_reasons']
        self.assertIn('quality_review',changes);self.assertNotIn('price',changes)

    def test_scenario_changes_keep_value_arithmetic_and_traceable_link(self):
        s=f.security();e=quality_entry();baseline=q.binding(e['packet'],s)
        e['baseline']=baseline;e['receipt']=q.receipt(e['packet'],e['corpus'])
        d=run([s],b=bundle({'US:EXAM':e}));r=d['ranking'][0]
        self.assertTrue(r['quality_gate']['eligible'])
        self.assertAlmostEqual(r['scenario_links']['counterfactual']['target_price_deltas']['Base'],2.4)

    def test_fixed_inputs_deterministic_and_not_mutated(self):
        b=bundle();s=[f.security()];c=f.context();before=copy.deepcopy((b,s,c))
        self.assertEqual(data.digest(run(s,c,b)),data.digest(run(s,c,b)))
        self.assertEqual((b,s,c),before)

    def test_invalid_fx_still_retains_local_valuation(self):
        c=f.context();c['fx']['spot']=0.
        d=run(ctx=c);r=d['ranking'][0]
        self.assertIsNotNone(r['expected_total_return'])
        self.assertEqual(r['investment_rank_local'],1)
        self.assertIsNone(r['investment_rank']);self.assertFalse(d['portfolio_proposal']['ready'])

    def test_cli_exposes_explicit_quality_option(self):
        r=subprocess.run([sys.executable,'-I',str(ROOT/'tools/run_research_decision_v1.py'),'--help'],capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,0);self.assertIn('--quality-bundle',r.stdout)

    def test_full_five_plus_two_synthetic_decision_and_funding(self):
        ids=['US:FIXA','US:FIXB','US:FIXC','US:FIXD','US:FIXE','KR:990001','KR:990002']
        secs=[];entries={}
        for i,sid in enumerate(ids):
            security=f.security(sid)
            if sid.startswith('KR:'):
                security.update(market='KR',currency='KRW')
                security['blocks']['scenario']['currency']='KRW'
            security['blocks']['risk']['payload']['exposures']={
                'industry:fixture'+str(i):1.,'theme:fixture'+str(i):1.,'customer:fixture'+str(i):1.}
            secs.append(security);entries[sid]=quality_entry(sid)
        d=run(secs,b=bundle(entries));p=d['portfolio_proposal']
        self.assertTrue(d['readiness']['target_5_plus_2_complete'])
        self.assertEqual(sum(x['target_weight']>0 for x in p['rows']),7)
        self.assertEqual(d['data_kind'],'SYNTHETIC');self.assertFalse(d['readiness']['oos_validated'])
        self.assertAlmostEqual(sum(x['target_weight'] for x in p['rows'])+p['cash_weight'],1.)
        fund=p['funding']
        self.assertAlmostEqual(sum(fund['position_values_krw'].values())+fund['cash_krw']+fund['transaction_cost_krw'],fund['initial_nav_krw'])

    def test_unreviewed_cash_is_not_risk_off_cash(self):
        d=run(b=bundle({}));p=d['portfolio_proposal']
        self.assertFalse(p['ready'])
        self.assertTrue(p['cash_is_unallocated_fallback'])
        self.assertEqual(p['cash_reason'],'UNALLOCATED_MISSING_EVIDENCE')

    def test_krw_native_values_survive_missing_usd_fx(self):
        security=f.security('KR:990001');security.update(market='KR',currency='KRW')
        security['blocks']['scenario']['currency']='KRW'
        c=f.context();del c['fx']
        d=run([security],c,bundle({'KR:990001':quality_entry('KR:990001')}));row=d['ranking'][0]
        self.assertIsNotNone(row['expected_total_return_krw'])
        self.assertEqual(row['expected_total_return_krw'],row['expected_total_return'])
        self.assertEqual(row['investment_rank_local'],1);self.assertIsNone(row['investment_rank'])
        self.assertFalse(d['portfolio_proposal']['ready'])

if __name__=='__main__':unittest.main(verbosity=2)

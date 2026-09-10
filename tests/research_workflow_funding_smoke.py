"""Synthetic seam regressions; no provider coverage, PIT or return-performance claim.

The engine tests mock ONLY its market-export replay boundary with a labelled
admitted synthetic fixture. They do not relax the real H1 admission contract.
Run: python -I tests/research_workflow_funding_smoke.py
"""
from __future__ import annotations
import copy
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.research_decision_v1 import portfolio, engine, data
from tools.research_decision_v1.valuation import evaluate_security
CUTOFF = "2026-09-08T15:45:00Z"
STAMP = "2026-09-08T14:00:00Z"
PERIOD = {"start":"2026-09-08", "end":"2027-09-08"}

def base_security():
    scenarios=[dict(name=n,probability=p,revenue=r,margin=.1,multiple=20.,net_debt=0.,
                    diluted_shares=100.,dividend=0.) for n,p,r in
               (("Bear",.25,800.),("Base",.5,1200.),("Bull",.25,1600.))]
    payload={"probability_type":"SUBJECTIVE_SCENARIO","company_type":"PROFITABLE_OPERATING",
             "horizon_months":12,"target_date":PERIOD["end"],"method":"PE",
             "rationale":"Fixed synthetic scenarios, not a forecast.","scenarios":scenarios}
    block={"status":"available","source":"https://fixture.example.org/scenario","security_id":"US:EXAM",
           "currency":"USD","decision_cutoff":CUTOFF,"unit":"scenario_currency_and_shares",
           "accounting_basis":"RESEARCH_ASSUMPTION","published_at":STAMP,"public_available_at":STAMP,
           "first_seen_at":STAMP,"ingested_at":STAMP,"report_period":PERIOD,
           "payload":payload,"data_hash":data.digest(payload)}
    return {"security_id":"US:EXAM","market":"US","currency":"USD","blockers":[],
            "discovery":{"price":10.}, "blocks":{"scenario":block,
            "financials":{"payload":{"ttm":{"revenue":1000.,"net_income":100.,"ebitda":120.}}},
            "thesis":{"payload":{"company_quality":"pass","strongest_bear_case":"Synthetic downside.",
                "catalyst":"Synthetic milestone.","invalidation_condition":"Synthetic failure.","source_evidence":[]}},
            "risk":{"payload":{"uncertainty":.1}}}}

CONFIG = json.loads((ROOT/'docs/research_decision_v1_config.json').read_text(encoding='utf-8'))

def context():
    return {'decision_cutoff': CUTOFF, 'mode': 'NEW_CAPITAL_RESEARCH',
            'capital_is_assumption': True, 'capital_krw': 100_000_000.,
            'fx': {'status': 'available', 'pair': 'KRW_PER_USD', 'source': 'https://fixture.example.org/fx',
                   'spot': 1300., 'observed_at': CUTOFF, 'assumption_type': 'SUBJECTIVE_SCENARIO',
                   'scenario_rates': {'Bear': 1300., 'Base': 1300., 'Bull': 1300.}},
            'regime': {'state': 'RISK_ON', 'source': 'https://fixture.example.org/regime',
                       'observed_at': CUTOFF, 'rationale': 'Synthetic controlled regime.'}}

def security(sid='US:EXAM'):
    s = base_security()
    s.update(security_id=sid, data_quality_pass=True, data_kind='SYNTHETIC', optional={})
    s['discovery'].update(adv20_local=1e9, history_sessions=0,
        rs={str(h): {'status': 'missing'} for h in (20,60,120,240)})
    s['blocks']['scenario']['security_id']=sid
    s['blocks']['thesis']['payload'].update(intact=True, strengthened=False, confidence=.8)
    s['blocks']['risk']['payload'].update(integrity_alert=False,liquidity_restriction=False,
        stress_loss=.2,exposures={'industry:fixture':1.,'theme:fixture':1.,'customer:fixture':1.})
    return s

def run_fixture(ctx=None, sec=None, cfg=None):
    s = security() if sec is None else sec
    export = {'market': s['market'], 'decision_cutoff': CUTOFF, 'data_kind':'SYNTHETIC',
              'export_hash':'a'*64, 'securities':[s]}
    with patch.object(engine, 'replay_export', side_effect=lambda e:copy.deepcopy(e)):
        return engine.run_decisions([export], ctx or context(), cfg or CONFIG)

class FundingSeamTests(unittest.TestCase):
    def test_capital_error_does_not_disable_valid_fx_rank(self):
        for value in (0., None, 'invalid', -1.):
            c=context(); c['capital_krw']=value
            r=run_fixture(c)
            self.assertEqual(r['ranking'][0]['investment_rank'],1)
            self.assertIsNotNone(r['ranking'][0]['expected_total_return_krw'])
            self.assertFalse(r['portfolio_proposal']['ready'])
            self.assertFalse(any(e.startswith('fx') for e in r['portfolio_proposal']['blockers']))

    def test_missing_capital_is_distinct(self):
        c=context(); del c['capital_krw']
        errors=portfolio.context_errors(c, CONFIG, CUTOFF)
        self.assertIn('capital_unverified', errors)
        self.assertFalse(any(e.startswith('fx') for e in errors))

    def test_invalid_fx_is_not_capital_error(self):
        c=context(); c['fx']['spot']=0.
        errors=portfolio.context_errors(c, CONFIG, CUTOFF)
        self.assertIn('fx_unverified',errors)
        self.assertNotIn('capital_unverified',errors)

    def test_new_capital_funds_positions_cash_and_cost(self):
        r=run_fixture(); p=r['portfolio_proposal']; f=p['funding']
        self.assertTrue(p['ready'])
        self.assertAlmostEqual(sum(f['position_values_krw'].values())+f['cash_krw']+f['transaction_cost_krw'], f['initial_nav_krw'])
        self.assertAlmostEqual(sum(x['target_weight'] for x in p['rows'])+p['cash_weight'],1.)
        self.assertGreater(f['transaction_cost_krw'],0.)
        self.assertEqual(p['target_weight_basis'],'POST_COST_NAV')
        self.assertLess(f['post_cost_nav_krw'],f['initial_nav_krw'])

    def test_one_asset_closed_form(self):
        s=security(); desired={'US:EXAM':.2}
        f=portfolio.fund_targets(desired,{}, {'US:EXAM':s}, context(),CONFIG)
        scale=1/(1+.2*.0015)
        self.assertAlmostEqual(f['post_cost_nav_fraction'],scale)
        self.assertAlmostEqual(f['target_weights']['US:EXAM'],.2)
        self.assertAlmostEqual(f['cost_fraction_initial_nav'],1-scale)

    def test_hold_has_no_hidden_notional_trade(self):
        ss={sid:security(sid) for sid in ('US:EXAM','US:NEXT')}
        f=portfolio.fund_targets({'US:EXAM':.15,'US:NEXT':.2},{'US:EXAM':.15},ss,context(),CONFIG)
        self.assertEqual(f['position_fraction_initial_nav']['US:EXAM'],.15)
        self.assertEqual(f['trade_fraction_initial_nav']['US:EXAM'],0.)
        self.assertGreater(f['target_weights']['US:EXAM'],.15)

    def test_full_exit_reserves_fee_and_leaves_only_cash(self):
        f=portfolio.fund_targets({'US:EXAM':0.},{'US:EXAM':.2},{'US:EXAM':security()},context(),CONFIG)
        self.assertAlmostEqual(f['cost_fraction_initial_nav'],.2*.0015)
        self.assertAlmostEqual(f['cash_weight'],1.)
        self.assertAlmostEqual(f['cash_krw'],100_000_000*(1-.2*.0015))

    def test_buy_and_sell_costs_use_each_market(self):
        ss={'US:EXAM':security(),'KR:000660':{'market':'KR'}}
        f=portfolio.fund_targets({'US:EXAM':0.,'KR:000660':.2},{'US:EXAM':.2},ss,context(),CONFIG)
        expected=.2*.0015+f['position_fraction_initial_nav']['KR:000660']*.0025
        self.assertAlmostEqual(f['cost_fraction_initial_nav'],expected)

    def test_zero_fee_parity(self):
        cfg=copy.deepcopy(CONFIG);cfg['one_way_cost_bps']={'US':0.,'KR':0.}
        f=portfolio.fund_targets({'US:EXAM':.2},{},{'US:EXAM':security()},context(),cfg)
        self.assertEqual(f['target_weights'],{'US:EXAM':.2})
        self.assertAlmostEqual(f['cash_weight'],.8)
        self.assertEqual(f['transaction_cost_krw'],0.)

    def test_financing_never_reverses_add_into_sale(self):
        with self.assertRaisesRegex(ValueError,'funding_changes_trade_direction'):
            portfolio.fund_targets({'US:EXAM':.20000001,'US:NEXT':.5}, {'US:EXAM':.2},
                {sid:security(sid) for sid in ('US:EXAM','US:NEXT')},context(),CONFIG)

    def test_oversubscribed_preserved_hold_is_blocked(self):
        with self.assertRaises(ValueError):
            portfolio.fund_targets({'US:EXAM':1.,'US:NEXT':.1},{'US:EXAM':1.},
                {sid:security(sid) for sid in ('US:EXAM','US:NEXT')},context(),CONFIG)

    def test_random_synthetic_conservation(self):
        rng=random.Random(7301)
        ss={'US:EXAM':security(),'KR:000660':{'market':'KR'}}
        for _ in range(200):
            w={'US:EXAM':rng.uniform(.01,.4),'KR:000660':rng.uniform(.01,.4)}
            f=portfolio.fund_targets(w,{},ss,context(),CONFIG)
            self.assertGreaterEqual(f['cash_krw'],0.)
            self.assertAlmostEqual(f['cash_weight']+sum(f['target_weights'].values()),1.)
            self.assertAlmostEqual(sum(f['position_values_krw'].values())+f['cash_krw']+f['transaction_cost_krw'],100_000_000.,places=6)

    def test_expected_return_math_not_changed_by_funding(self):
        p=run_fixture()['ranking'][0]
        direct=evaluate_security(security(),CONFIG,CUTOFF)
        self.assertEqual(p['expected_total_return'],direct['expected_total_return'])

    def test_deterministic_replay_and_no_orders(self):
        first=run_fixture(); second=run_fixture()
        self.assertEqual(data.digest(first),data.digest(second))
        self.assertFalse(first['readiness']['orders_allowed'])
        self.assertFalse(first['readiness']['oos_validated'])

if __name__=='__main__': unittest.main(verbosity=2)

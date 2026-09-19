#!/usr/bin/env python3
from __future__ import annotations
import copy
from pathlib import Path
import sys
import types
import unittest
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import collect_earnings_estimates_h1 as c
CTX=dict(security_id='US:TEST:COMMON',issuer_id='CIK:TEST',fetch_source='fixture',currency='USD',
         accounting_basis='GAAP',share_unit='PER_COMMON_SHARE',period_type='ANNUAL')

def row(time='2026-09-01T20:00:00Z',eps=3.0,context=CTX):
    return c.parse_snapshot_row('TEST',fetch_date=time,
        eps_payload={'data':[dict(period='2027-12-31',avg=eps,low=1,high=4,numberAnalysts=8)]},
        revenue_payload=[],earnings_payload=[],recommendation_payload=[],fetch_source='fixture',identity_context=context)

def calculate(rows,cutoff='2026-09-02T00:00:00Z'):
    return c.compute_estimate_revision_features(pd.DataFrame(rows),as_of_date=cutoff)

class IntegrationTests(unittest.TestCase):
    def test_actual_parser_routes_to_h1(self):
        r=row(eps=True); self.assertIsNone(r['est_eps_fy1']); self.assertEqual(r['has_forward_estimate'],0)
    def test_naive_clock_is_blocked(self):
        r=row('2026-09-01'); self.assertIsNone(r['available_from']); self.assertEqual(r['has_forward_estimate'],0)
    def test_explicit_zero_survives_compatibility(self):
        self.assertEqual(row(eps=0)['est_eps_fy1'],0)
    def test_revision_on_observed_clock(self):
        out,s=calculate([row('2026-08-01T20:00:00Z',2),row()])
        self.assertAlmostEqual(out.iloc[-1]['est_eps_revision_30d'],.5)
        self.assertEqual(out.iloc[-1]['estimate_revision_replacement_gate_pass'],0)
        self.assertEqual(out.iloc[-1]['estimate_revision_future_winner_multiplier'],1.0)
        self.assertEqual(s['output_rows'],2)
    def test_no_prior_remains_null(self):
        out,s=calculate([row()]); self.assertIsNone(out.iloc[0]['est_eps_revision_30d'])
    def test_date_only_cutoff_is_not_a_market_close(self):
        out,s=calculate([row()],cutoff='2026-09-01'); self.assertTrue(out.empty); self.assertEqual(s['status'],'blocked')
    def test_after_close_cannot_enter_same_close(self):
        out,s=calculate([row('2026-09-01T20:05:00Z')],cutoff='2026-09-01T20:00:00Z')
        self.assertTrue(out.empty); self.assertEqual(s['excluded_rows'],1)
    def test_backdated_asof_not_lookback(self):
        previous=row('2026-08-25T20:00:00Z',2); previous['as_of_date']='2026-01-01'
        out,s=calculate([previous,row()]); self.assertTrue(pd.isna(out.iloc[-1]['est_eps_revision_30d']))
    def test_each_context_axis_blocks_comparison(self):
        for key in CTX:
            context=dict(CTX); context[key]='OTHER'
            a=row('2026-08-01T20:00:00Z',2,context); a[key]='OTHER'
            out,s=calculate([a,row()])
            current=out[out.available_from.str.startswith('2026-09-01')].iloc[0]
            with self.subTest(axis=key): self.assertTrue(pd.isna(current['est_eps_revision_30d']))
    def test_period_roll_preserves_same_period_in_fy2(self):
        a=row('2026-08-01T20:00:00Z',1)
        a['eps_fy1_period_end']='2026-12-31'
        a['eps_fy2_period_end']='2027-12-31'; a['eps_fy2_avg']=2
        out,s=calculate([a,row()]); self.assertAlmostEqual(out.iloc[-1]['est_eps_revision_30d'],.5)
    def test_conflicting_historical_snapshots_not_last_writer_wins(self):
        a=row('2026-08-01T20:00:00Z',1); b=row('2026-08-01T20:00:00Z',2)
        out,s=calculate([a,b,row()]); self.assertTrue(pd.isna(out.iloc[-1]['est_eps_revision_30d']))
    def test_missing_identity_kept_but_not_compared(self):
        out,s=calculate([row('2026-08-01T20:00:00Z',2,None),row(context=None)])
        self.assertEqual(s['output_rows'],2); self.assertTrue(pd.isna(out.iloc[-1]['est_eps_revision_30d']))
    def test_no_recommendation_breadth_relabel(self):
        a=row(); a['recommendation_balance']=1.0; a['est_eps_revision_breadth']=1.0
        out,s=calculate([a]); self.assertIsNone(out.iloc[0]['est_eps_revision_breadth'])
    def test_legacy_callbacks_reused_and_restored(self):
        oldparse,oldcalc=object(),object()
        fake=types.SimpleNamespace(parse_snapshot_row=oldparse,compute_estimate_revision_features=oldcalc)
        def main():
            self.assertIs(fake.compute_estimate_revision_features,c.compute_estimate_revision_features)
            value=fake.parse_snapshot_row('TEST',fetch_date='2026-09-01T20:00:00Z',eps_payload={'data':[{'period':'2027-12-31','avg':True}]},revenue_payload=[],earnings_payload=[],recommendation_payload=[])
            self.assertEqual(value['has_forward_estimate'],0)
            return 17
        fake.main=main
        self.assertEqual(c.run_legacy(fake),17)
        self.assertIs(fake.parse_snapshot_row,oldparse); self.assertIs(fake.compute_estimate_revision_features,oldcalc)
    def test_callbacks_restored_after_network_coordinator_error(self):
        oldparse,oldcalc=object(),object()
        def fail(): raise RuntimeError('synthetic failure')
        fake=types.SimpleNamespace(parse_snapshot_row=oldparse,compute_estimate_revision_features=oldcalc,main=fail)
        with self.assertRaises(RuntimeError): c.run_legacy(fake)
        self.assertIs(fake.parse_snapshot_row,oldparse); self.assertIs(fake.compute_estimate_revision_features,oldcalc)
    def test_actual_fiscal_date_not_announcement(self):
        r=c.parse_snapshot_row('TEST',fetch_date='2026-09-01T20:00:00Z',eps_payload=[],revenue_payload=[],recommendation_payload=[],earnings_payload=[{'period':'2026-06-30','actual':2,'surprise':.5,'surprisePercent':25}])
        self.assertIsNone(r['actual_report_date']); self.assertIsNone(r['earnings_surprise_last'])
        self.assertEqual(r['provider_surprise_absolute'],.5); self.assertEqual(r['provider_surprise_percent'],25)
    def test_repeat_no_mutation(self):
        data=pd.DataFrame([row('2026-08-01T20:00:00Z',2),row()]); original=copy.deepcopy(data)
        a,sa=c.compute_estimate_revision_features(data,as_of_date='2026-09-02T00:00:00Z')
        b,sb=c.compute_estimate_revision_features(data,as_of_date='2026-09-02T00:00:00Z')
        pd.testing.assert_frame_equal(a,b); pd.testing.assert_frame_equal(data,original); self.assertEqual(sa,sb)

if __name__=='__main__': unittest.main(verbosity=2)

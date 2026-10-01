#!/usr/bin/env python3
"""Executable unittest regressions; assertions remain active under python -O."""
from __future__ import annotations
import copy
import importlib.util
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('h1', ROOT/'tools/earnings_consensus_h1.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
CTX = dict(security_id='US:TEST:COMMON', issuer_id='CIK:TEST', fetch_source='fixture', currency='USD',
           accounting_basis='GAAP', share_unit='PER_COMMON_SHARE', period_type='ANNUAL')

def snapshot(time='2026-09-01T20:00:00Z', eps=2.0, **kw):
    args = dict(ticker='TEST', eps_payload={'data':[{'period':'2027-12-31','avg':eps,'low':1,'high':4,'numberAnalysts':8}]},
                revenue_payload=[], recommendation_payload=[], observed_at=time, collected_at=time,
                first_seen_at=time, fetch_source='fixture', identity_context=CTX)
    args.update(kw)
    return h.build_snapshot(**args)

class BoundaryTests(unittest.TestCase):
    def test_missing_numeric(self):
        for x in (None,'','x',float('nan'),float('inf'),{},[],True,False):
            with self.subTest(value=repr(x)): self.assertIsNone(h.optional_float(x))
    def test_explicit_zero_and_negative_eps(self):
        self.assertEqual(h.optional_float(0),0.0); self.assertEqual(h.optional_float('-2'),-2.0)
    def test_fractional_negative_bool_counts_rejected(self):
        for x in (2.9,-1,True,'2.9','NaN',2**54):
            with self.subTest(x=x): self.assertIsNone(h.optional_int(x))
    def test_valid_count(self):
        self.assertEqual(h.optional_int('8.0'),8); self.assertEqual(h.optional_int(0),0)
    def test_timezone_required(self):
        for x in ('2026-09-01','2026-09-01T12:30:00','2026-09-01 garbage',None):
            with self.subTest(x=x): self.assertIsNone(h.iso_utc(x))
    def test_offsets_normalized(self):
        self.assertEqual(h.iso_utc('2026-09-02T05:00:00+09:00'),h.iso_utc('2026-09-01T20:00:00Z'))
    def test_microseconds_preserved(self):
        self.assertNotEqual(h.iso_utc('2026-09-01T20:00:00.000001Z'),h.iso_utc('2026-09-01T20:00:00Z'))
    def test_period_date_validation(self):
        for x in ('20261301','2026-13-01','2026-02-30',20261231):
            with self.subTest(x=x): self.assertIsNone(h.period_value({'period':x}))
    def test_period_alias_conflict(self):
        self.assertIsNone(h.period_value({'period':'2027-12-31','date':'2026-12-31'}))
    def test_missing_recommendation_counts_not_zero(self):
        self.assertIsNone(h.recommendation_metrics([])['recommendation_bull_count'])
    def test_recommendation_not_revision(self):
        r=h.recommendation_metrics([dict(period='2026-09-01',strongBuy=4,buy=3,hold=1,sell=1,strongSell=0)])
        self.assertAlmostEqual(r['recommendation_balance'],.75); self.assertIsNone(r['est_eps_revision_breadth'])
    def test_partial_counts_no_sentiment(self):
        self.assertIsNone(h.recommendation_metrics([{'buy':7}])['recommendation_balance'])
    def test_chronology_block(self):
        r=snapshot(collected_at='2026-09-01T19:00:00Z')
        self.assertEqual(r['data_quality_status'],'BLOCKED_INPUT'); self.assertIsNone(r['available_at'])
    def test_invalid_published_time_block(self):
        self.assertEqual(snapshot(provider_published_at='2026-09-01')['has_forward_estimate'],0)
    def test_publication_after_observation_block(self):
        self.assertEqual(snapshot(provider_published_at='2026-09-01T21:00:00Z')['has_forward_estimate'],0)
    def test_first_seen_after_observation_block(self):
        self.assertEqual(snapshot(first_seen_at='2026-09-01T21:00:00Z')['has_forward_estimate'],0)
    def test_access_denied_not_usable(self):
        self.assertEqual(snapshot(eps_estimate_access=False)['has_forward_estimate'],0)
    def test_string_access_flag_not_truth(self):
        self.assertEqual(snapshot(eps_estimate_access='false')['has_forward_estimate'],0)
    def test_zero_is_usable_observation(self):
        self.assertEqual(snapshot(eps=0)['has_forward_estimate'],1)
    def test_missing_identity_preserves_observation_blocks_comparison(self):
        r=snapshot(identity_context=None)
        self.assertEqual(r['eps_fy1_avg'],2.0); self.assertFalse(r['comparison_identity_complete'])
    def test_duplicate_period_block(self):
        rows=[{'period':'2027-12-31','avg':1},{'period':'2027-12-31','avg':2}]
        self.assertEqual(snapshot(eps_payload={'data':rows})['has_forward_estimate'],0)
    def test_bad_period_block(self):
        self.assertEqual(snapshot(eps_payload={'data':[{'period':'bad','avg':1}]})['has_forward_estimate'],0)
    def test_invalid_bounds_no_dispersion(self):
        r=snapshot(eps_payload={'data':[{'period':'2027-12-31','avg':2,'high':1,'low':4}]})
        self.assertIsNone(r['eps_fy1_dispersion'])
    def test_matching_revision(self):
        a=snapshot('2026-08-01T20:00:00Z',eps=2); b=snapshot(eps=3)
        self.assertAlmostEqual(h.same_period_revision(b,a,'eps_fy1'),.5)
    def test_each_identity_axis_checked(self):
        a=snapshot('2026-08-01T20:00:00Z'); b=snapshot(eps=3)
        for key in h.CONTEXT_KEYS:
            c=copy.deepcopy(a); c[key]='DIFFERENT'
            with self.subTest(key=key): self.assertIsNone(h.same_period_revision(b,c,'eps_fy1'))
    def test_missing_identity_axis_blocks(self):
        a=snapshot('2026-08-01T20:00:00Z'); b=snapshot(eps=3)
        a.pop('currency'); self.assertIsNone(h.same_period_revision(b,a,'eps_fy1'))
    def test_future_prior_not_revision(self):
        self.assertIsNone(h.same_period_revision(snapshot(),snapshot('2026-09-02T20:00:00Z'),'eps_fy1'))
    def test_same_timestamp_not_revision(self):
        self.assertIsNone(h.same_period_revision(snapshot(eps=3),snapshot(),'eps_fy1'))
    def test_fiscal_roll_not_revision(self):
        a=snapshot('2026-08-01T20:00:00Z'); a['eps_fy1_period_end']='2026-12-31'
        self.assertIsNone(h.same_period_revision(snapshot(),a,'eps_fy1'))
    def test_zero_denominator_no_fabricated_growth(self):
        self.assertIsNone(h.pct_change(2,0))
    def test_pre_event_requires_identity(self):
        self.assertIsNone(h.frozen_pre_event_consensus([snapshot()],event_available_at='2026-09-02T00:00:00Z',fiscal_period_end='2027-12-31'))
    def test_pre_event_excludes_other_company(self):
        other=snapshot('2026-09-01T21:00:00Z'); other['security_id']='OTHER'; other['ticker']='OTHER'
        r=h.frozen_pre_event_consensus([snapshot(),other],event_available_at='2026-09-02T00:00:00Z',fiscal_period_end='2027-12-31',identity_context=CTX)
        self.assertEqual(r['ticker'],'TEST')
    def test_pre_event_equal_timestamp_excluded(self):
        self.assertIsNone(h.frozen_pre_event_consensus([snapshot()],event_available_at='2026-09-01T20:00:00Z',fiscal_period_end='2027-12-31',identity_context=CTX))
    def test_pre_event_strict_microsecond_order(self):
        r=h.frozen_pre_event_consensus([snapshot('2026-09-01T20:00:00.000001Z')],event_available_at='2026-09-01T20:00:00.000002Z',fiscal_period_end='2027-12-31',identity_context=CTX)
        self.assertIsNotNone(r)
    def test_pre_event_conflict_is_not_last_write_wins(self):
        self.assertIsNone(h.frozen_pre_event_consensus([snapshot(eps=2),snapshot(eps=3)],event_available_at='2026-09-02T00:00:00Z',fiscal_period_end='2027-12-31',identity_context=CTX))
    def test_pre_event_no_mutation(self):
        source=snapshot(); before=copy.deepcopy(source)
        r=h.frozen_pre_event_consensus([source],event_available_at='2026-09-02T00:00:00Z',fiscal_period_end='2027-12-31',identity_context=CTX)
        r['ticker']='CHANGE'; self.assertEqual(source,before)
    def test_missing_success_age_not_fresh(self):
        self.assertEqual(h.classify_attempt_state(has_success=True,success_age_days=None,selection_count=1,last_error_class=None),'UNKNOWN_FRESHNESS')
    def test_negative_success_age_not_fresh(self):
        self.assertEqual(h.classify_attempt_state(has_success=True,success_age_days=-1,selection_count=1,last_error_class=None),'UNKNOWN_FRESHNESS')
    def test_fresh_stale_boundary(self):
        self.assertEqual(h.classify_attempt_state(has_success=True,success_age_days=7,selection_count=1,last_error_class=None),'STALE_SUCCESS')
    def test_blocked_requests_cannot_be_boosted(self):
        for s in h.BLOCKED_STATES:
            with self.subTest(state=s):
                self.assertIsNone(h.retry_priority(s,active_candidate=True,earnings_near=True))
                self.assertFalse(h.retry_decision(s,now='2026-09-01T00:00:00Z')['eligible_for_request'])
    def test_cooldown_blocks(self):
        self.assertFalse(h.retry_decision('TRANSIENT_FAILURE',now='2026-09-01T00:00:00Z',retry_after='2026-09-02T00:00:00Z')['eligible_for_request'])
    def test_retry_due(self):
        self.assertTrue(h.retry_decision('NEVER_ATTEMPTED',now='2026-09-01T00:00:00Z')['eligible_for_request'])
    def test_invalid_event_time_raises(self):
        with self.assertRaises(ValueError): h.causal_event_id('TEST','2027-12-31','2026-09-01')
    def test_event_subsecond_identity(self):
        a=h.causal_event_id('TEST','2027-12-31','2026-09-01T20:00:00.000001Z')
        b=h.causal_event_id('TEST','2027-12-31','2026-09-01T20:00:00.000002Z')
        self.assertNotEqual(a,b)

if __name__=='__main__':
    unittest.main(verbosity=2)

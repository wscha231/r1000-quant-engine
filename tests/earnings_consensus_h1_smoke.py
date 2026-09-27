#!/usr/bin/env python3
"""Deterministic H1 admission regressions; no vendor/network/economic runs."""
from __future__ import annotations
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import earnings_consensus_h1 as h1
from tools import collect_earnings_estimates_finnhub as c
from tools.run_free_data_selection_overlay import build_overlay


def estimate(value=1.0, period="2026-12-31", **overrides):
    return dict(period=period, avg=value, high=1.4, low=0.8, numberAnalysts=5,
                issuer_id="CIK:1", security_id="FIGI:AAA", period_type="ANNUAL",
                accounting_basis="GAAP", currency="USD", share_or_ADR_unit="DILUTED_COMMON_SHARE", **overrides)


def snapshot(time="2026-04-01T18:00:00Z", value=1.0, period="2026-12-31", ticker="AAA", **kwargs):
    args = dict(fetch_date=pd.Timestamp(time[:10]), eps_payload={"data": [estimate(value, period)]},
                revenue_payload={"data": [estimate(100.0, period)]}, earnings_payload=[],
                recommendation_payload=[dict(strongBuy=4,buy=3,sell=1,strongSell=0)],
                observed_at=time, collected_at=time)
    args.update(kwargs)
    return c.parse_snapshot_row(ticker, **args)


def features(rows):
    return c.compute_estimate_revision_features(pd.DataFrame(rows))[0]


class AdmissionTests(unittest.TestCase):
    def test_recommendation_is_not_breadth(self):
        row = snapshot()
        self.assertEqual(row['analyst_recommendation_balance'], .75)
        self.assertIsNone(row['est_eps_revision_breadth'])
        self.assertIsNone(features([row]).iloc[0]['est_eps_revision_breadth'])

    def test_missing_not_zero(self):
        row = snapshot(eps_payload={"data": [estimate(None)]}, revenue_payload={})
        self.assertIsNone(row['est_eps_fy1'])
        self.assertEqual(row['eps_fy1_status'], 'MISSING')
        self.assertEqual(row['rev_fy1_status'], 'NO_COVERAGE')
        self.assertIsNone(snapshot(recommendation_payload=[])['analyst_recommendation_balance'])

    def test_same_period_revision_eps_and_revenue(self):
        rows = [snapshot(), snapshot('2026-05-02T18:00:00Z', 1.2,
                                    revenue_payload={"data": [estimate(110)]})]
        last = features(rows).iloc[-1]
        self.assertAlmostEqual(last.est_eps_revision_30d, .2)
        self.assertAlmostEqual(last.est_rev_revision_30d, .1)

    def test_fy_roll_is_not_revision(self):
        last = features([snapshot(),snapshot('2026-05-02T18:00:00Z',2,'2027-12-31')]).iloc[-1]
        self.assertTrue(pd.isna(last.est_eps_revision_30d))

    def test_fy_view_can_match_prior_fy2_only_same_identity(self):
        before = snapshot(eps_payload={"data":[estimate(1),estimate(2,'2027-12-31')]})
        after = snapshot('2026-05-02T18:00:00Z',2.2,'2027-12-31')
        self.assertAlmostEqual(h1.same_period_revision(after,before),.1)
        self.assertEqual(json.loads(after['eps_fy1_identity'])['fiscal_period_end'],'2027-12-31')

    def test_currency_unit_security_and_basis_block(self):
        before=snapshot()
        for key,value in [('currency','EUR'),('share_or_ADR_unit','ADR_2_COMMON'),('security_id','FIGI:OTHER'),('issuer_id','CIK:2'),('accounting_basis','NON_GAAP'),('period_type','QUARTERLY')]:
            item=estimate(1.2); item[key]=value
            after=snapshot('2026-05-02T18:00:00Z',eps_payload={'data':[item]})
            self.assertIsNone(h1.same_period_revision(after,before),key)

    def test_after_close_and_utc_offsets(self):
        row=snapshot('2026-07-01T16:01:00-04:00')
        self.assertTrue(c.latest_signal_by_ticker(features([row]),decision_date='2026-07-01T20:00:00Z').empty)
        self.assertFalse(c.latest_signal_by_ticker(features([row]),decision_date='2026-07-02T20:00:00Z').empty)
        self.assertTrue(c.latest_signal_by_ticker(features([row]),decision_date='2026-07-01').empty)

    def test_no_snapshot_historical_backfill(self):
        row=snapshot('2026-07-02T21:00:00Z',fetch_date=pd.Timestamp('2000-01-01'))
        self.assertEqual(row['as_of_date'],'2026-07-02')
        self.assertTrue(c.compute_estimate_revision_features(pd.DataFrame([row]),as_of_date='2000-01-01')[0].empty)
        with patch.object(sys,'argv',['collector','--fetch-date','2000-01-01']):
            with self.assertRaisesRegex(ValueError,'backfill'): c.main()

    def test_frozen_pre_announcement(self):
        before=snapshot('2026-07-01T19:59:00Z',1)
        simultaneous=snapshot('2026-07-01T20:00:00Z',3)
        after=snapshot('2026-07-01T20:01:00Z',9)
        identity=json.loads(before['eps_fy1_identity'])
        frozen=h1.frozen_pre_event_consensus([before,simultaneous,after],event_available_at='2026-07-01T20:00:00Z',identity=identity,fetch_source='finnhub')
        self.assertEqual(frozen['value'],1)
        self.assertAlmostEqual(h1.earnings_surprise(1.5,frozen,identity=identity,announcement_at='2026-07-01T20:00:00Z'),.5)
        self.assertIsNone(h1.earnings_surprise(1.5,frozen,identity={**identity,'currency':'EUR'},announcement_at='2026-07-01T20:00:00Z'))
        self.assertIsNone(snapshot(earnings_payload=[{'period':'2026-06-30','surprisePercent':99}])['earnings_surprise_last'])

    def test_provider_corrections_preserve_versions(self):
        before=snapshot('2026-07-01T19:00:00Z',1)
        correction=snapshot('2026-07-01T21:00:00Z',2,provider_published_at='2026-06-01T00:00:00Z')
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'estimates.parquet'; pd.DataFrame([before]).to_parquet(p)
            merged,_=c.merge_same_day_snapshot(p,pd.DataFrame([correction]))
            self.assertEqual(len(merged),2)
            self.assertEqual(c.latest_signal_by_ticker(merged,decision_date='2026-07-01T20:00:00Z').iloc[0].est_eps_fy1,1)
            self.assertNotEqual(before['snapshot_version_id'],correction['snapshot_version_id'])

    def test_causal_event_dedupe(self):
        key=h1.causal_event_id('CIK:1','2026-06-30','2026-07-01T20:00:00Z')
        rows=[dict(causal_event_id=key,causal_link_verified=True,kind=k) for k in ['surprise','revision','rating','target_price','news']]
        self.assertEqual(len(h1.dedupe_causal_events(rows+rows)),1)
        self.assertEqual(len(h1.dedupe_causal_events(rows)[0]['reactions']),5)
        self.assertEqual(h1.dedupe_causal_events([dict(causal_event_id=key)]),[])

    def test_provider_missing_preserves_attempted_candidate(self):
        with patch.object(c,'fetch_estimate_payloads_by_order',return_value=({}, {}, '', False, False, True)):
            rows,_,attempted,_=c.collect_live_snapshot(['AAA','BBB'],finnhub_api_key='',alphavantage_api_key='',fmp_api_key='fixture',vendor_order=['fmp'],fetch_date=pd.Timestamp('2026-07-01'),sleep_seconds=0,max_errors=10)
        self.assertEqual(rows.ticker.tolist(),['AAA','BBB'])
        self.assertEqual(attempted,['AAA','BBB'])
        self.assertEqual(rows.provider_coverage_status.tolist(),['NO_COVERAGE','NO_COVERAGE'])

    def test_partial_update_equals_full_recompute(self):
        rows=[snapshot(ticker='AAA'),snapshot(ticker='BBB'),snapshot('2026-05-02T18:00:00Z',1.2),snapshot('2026-05-02T18:00:00Z',1.3,ticker='BBB')]
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'day.parquet'; pd.DataFrame(rows[:3]).to_parquet(p)
            merged,_=c.merge_same_day_snapshot(p,pd.DataFrame(rows[3:]))
            expected=features(rows).sort_values(['ticker','available_from']).reset_index(drop=True)
            actual=features(merged.to_dict('records')).sort_values(['ticker','available_from']).reset_index(drop=True)
            pd.testing.assert_frame_equal(actual,expected,check_like=True)

    def test_explicit_zero_remains_zero(self):
        row=snapshot(value=0)
        self.assertEqual(row['est_eps_fy1'],0)
        self.assertEqual(row['eps_fy1_status'],'EXPLICIT_ZERO')
        self.assertEqual(h1.same_period_revision(snapshot('2026-05-02T18:00:00Z',0),snapshot()),-1)
        self.assertIsNone(h1.same_period_revision(snapshot('2026-05-02T18:00:00Z',1),row))

    def test_null_survives_storage_and_compute(self):
        row=snapshot(value=None)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'test.parquet'; pd.DataFrame([row]).to_parquet(p)
            out=features(pd.read_parquet(p).to_dict('records'))
            self.assertTrue(pd.isna(out.iloc[0].est_eps_fy1))
            self.assertTrue(pd.isna(out.iloc[0].est_eps_revision_30d))
        for value in [None,'',float('nan'),float('inf'),True]: self.assertIsNone(h1.optional_float(value))

    def test_incomplete_identity_and_date_only_are_not_admitted(self):
        after=snapshot('2026-05-02T18:00:00Z',eps_payload={'data':[{'period':'2026','avg':2}]})
        self.assertIsNone(h1.same_period_revision(after,snapshot()))
        self.assertIsNone(h1.iso_utc('2026-07-01'))
        self.assertIsNone(h1.iso_utc('2026-07-01T20:00:00'))
        self.assertTrue(features([{'ticker':'AAA','available_from':'2026-07-01','est_eps_fy1':1}]).empty)

    def test_vendor_switch_not_revision(self):
        self.assertIsNone(h1.same_period_revision(snapshot('2026-05-02T18:00:00Z',2,fetch_source='fmp'),snapshot()))

    def test_revenue_fy1_is_first_not_last(self):
        row=snapshot(revenue_payload={'data':[estimate(100),estimate(200,'2027-12-31')]})
        self.assertEqual(row['est_rev_fy1'],100)
        self.assertEqual(row['rev_fy1_period_end'],'2026-12-31')

    def test_h2_consumers_stay_inactive(self):
        signals=features([snapshot(),snapshot('2026-05-02T18:00:00Z',2)])
        scored=pd.DataFrame([{'ticker':'AAA','score':.7,'portfolio_future_winner_engine_score':1},{'ticker':'BBB','score':.8,'portfolio_future_winner_engine_score':2}])
        out,summary=c.apply_estimate_revision_confirmation(scored,signals,decision_date='2026-05-03',enabled=True)
        self.assertEqual(out.portfolio_future_winner_engine_score.tolist(),[1,2])
        args=dict(decision_date=pd.Timestamp('2026-05-03'),listing=pd.DataFrame(),earnings_calendar=pd.DataFrame(),top_n=2)
        baseline,_=build_overlay(scored,signals=pd.DataFrame(),**args)
        result,_=build_overlay(scored,signals=signals,**args)
        pd.testing.assert_frame_equal(baseline,result)

    def test_availability_uses_latest_required_timestamp(self):
        row=snapshot('2026-07-01T18:00:00Z',collected_at='2026-07-02T18:00:00Z',first_seen_at='2026-06-01T18:00:00Z')
        self.assertEqual(row['strategy_available_at'],'2026-07-02T18:00:00Z')

    def test_missing_latest_does_not_fall_back_to_old_known(self):
        rows=[snapshot(),snapshot('2026-04-02T18:00:00Z',None),snapshot('2026-05-03T18:00:00Z',2)]
        self.assertTrue(pd.isna(features(rows).iloc[-1].est_eps_revision_30d))

    def test_conflicting_same_time_is_unknown(self):
        before=snapshot(); conflict=snapshot(value=3); after=snapshot('2026-05-02T18:00:00Z',2)
        self.assertTrue(pd.isna(features([before,conflict,after]).iloc[-1].est_eps_revision_30d))

if __name__=='__main__': unittest.main()

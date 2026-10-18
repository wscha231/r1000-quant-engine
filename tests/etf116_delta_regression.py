"""New discriminating regressions only; original 61 cases remain separate evidence."""
from __future__ import annotations

import copy
import math
import statistics
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.etf116_research_metrics_h1 import compute_horizons, RefuseInput
from tools.etf_top3_holdings_overlay_h1 import build_lookthrough, OverlayError

REVIEW = '2026-10-18T14:00:00Z'


class DeltaRegression(unittest.TestCase):
    def setUp(self):
        day, end = date(2025, 10, 16), date(2026, 10, 16)
        self.sessions = []
        while day <= end:
            if day.weekday() < 5:
                self.sessions.append(day.isoformat())
            day += timedelta(days=1)
        self.rows = self.series('GARP')

    def series(self, ticker):
        return [dict(ticker=ticker, date=s, tr_index=100 + i * .1 + (i % 3) * .2,
                     basis='NAV_TR_INDEX', source_sha256=f'{i+1:064x}',
                     available_at_utc='2026-10-18T13:00:00Z')
                for i, s in enumerate(self.sessions)]

    def compute(self, **kw):
        args = dict(ticker='GARP', asof='2026-10-16', decision_at=REVIEW,
                    official_sessions=self.sessions, tr_rows=self.rows,
                    issuer_listing_date='2020-01-01')
        args.update(kw)
        return compute_horizons(**args)

    def test_missing_rf_preserves_independent_volatility_and_mdd(self):
        risk = self.compute()['horizons']['12']['risk']
        returns = [b['tr_index']/a['tr_index']-1 for a,b in zip(self.rows,self.rows[1:])]
        self.assertAlmostEqual(risk['ann_volatility'], statistics.stdev(returns)*math.sqrt(252))
        self.assertLessEqual(risk['mdd'], 0)
        self.assertIsNone(risk['sharpe'])
        self.assertIsNone(risk['sortino'])
        self.assertEqual(risk['risk_free_status'], 'BLOCKED_RF_NOT_SUPPLIED')

    def test_invalid_rf_preserves_volatility_without_zero_rate_fallback(self):
        bad=[dict(observation_date='2025-10-15',dgs3mo_pct=float('nan'),available_at_utc=REVIEW)]
        risk=self.compute(rf_rows=bad)['horizons']['12']['risk']
        self.assertGreater(risk['ann_volatility'],0)
        self.assertEqual(risk['risk_free_status'],'BLOCKED_RF_NONNUMERIC')
        self.assertIsNone(risk['sharpe'])

    def test_bad_optional_spy_keeps_subject_and_blocks_comparison(self):
        bench=self.series('SPY');bench[0]['basis']='RAW_SIP_OHLCV'
        result=self.compute(benchmark_rows=bench)['horizons']['12']
        self.assertEqual(result['status'],'RESEARCH_DAILY_TR_COMPLETE')
        self.assertEqual(result['benchmark_status'],'BLOCKED_OPTIONAL_BENCHMARK_SERIES_NOT_TOTAL_RETURN_INDEX')
        self.assertNotIn('log_relative_rs_spy',result)

    def test_structurally_bad_optional_spy_keeps_subject(self):
        bench=self.series('SPY');bench[0]['basis']=[]
        result=self.compute(benchmark_rows=bench)['horizons']['12']
        self.assertEqual(result['status'],'RESEARCH_DAILY_TR_COMPLETE')
        self.assertIn('BLOCKED_OPTIONAL_BENCHMARK_',result['benchmark_status'])

    def test_structurally_bad_rf_keeps_subject_volatility(self):
        risk=self.compute(rf_rows=7)['horizons']['12']['risk']
        self.assertGreater(risk['ann_volatility'],0)
        self.assertEqual(risk['risk_free_status'],'BLOCKED_RF_NOT_LIST')
        self.assertIsNone(risk['sharpe'])

    def test_bad_subject_still_refuses(self):
        self.rows[0]['basis']='RAW_SIP_OHLCV'
        with self.assertRaisesRegex(RefuseInput,'SERIES_NOT_TOTAL_RETURN_INDEX'):
            self.compute(benchmark_rows=self.series('SPY'))

    def test_valid_optional_spy_keeps_beta_without_rf(self):
        result=self.compute(benchmark_rows=self.series('SPY'))['horizons']['12']
        self.assertAlmostEqual(result['risk']['beta_vs_spy'],1)
        self.assertAlmostEqual(result['log_relative_rs_spy'],0)
        self.assertIsNone(result['risk']['sharpe'])

    def test_mixed_nav_market_stays_blocked(self):
        bench=self.series('SPY')
        for row in bench:row['basis']='MARKET_TR_INDEX'
        result=self.compute(benchmark_rows=bench)['horizons']['12']
        self.assertEqual(result['benchmark_status'],'BENCHMARK_BASIS_MISMATCH')
        self.assertNotIn('beta_vs_spy',result['risk'])

    def holding_rows(self):
        return [dict(etf=f,ticker=f'A{i}',rank=i,weight_pct=1.,
                     holdings_asof='2026-10-16' if f=='SPMO' else '2026-10-15',
                     source_url='https://etfiq.com/funds/'+f.lower()+'/holdings/')
                for f in ['GARP','QUAL','SPMO'] for i in range(1,11)]

    def overlay(self, rows, **kw):
        return build_lookthrough(rows, [f'A{i}' for i in range(1,11)],reviewed_at_utc=REVIEW,**kw)

    def test_mixed_same_etf_snapshot_refuses(self):
        rows=self.holding_rows();rows[0]['holdings_asof']='2026-10-14'
        with self.assertRaisesRegex(OverlayError,'ETF_SNAPSHOT_MIXED_ASOF'):
            self.overlay(rows)

    def test_different_etf_dates_remain_allowed_without_pit(self):
        r=self.overlay(self.holding_rows())
        self.assertEqual(r['holding_slots'],30)
        self.assertFalse(r['eligible_for_pit'])
        self.assertFalse(r['universe_seed_modified'])

    def test_total_fund_weight_over_100_refuses(self):
        rows=self.holding_rows()
        for row in rows[:10]:row['weight_pct']=11
        with self.assertRaisesRegex(OverlayError,'ETF_TOP_HOLDINGS_WEIGHT_EXCEEDS_FUND'):
            self.overlay(rows)

    def test_bool_top_n_refuses(self):
        with self.assertRaisesRegex(OverlayError,'TOP_N_INVALID'):
            self.overlay(self.holding_rows(),expected_top_n=True)

    def test_no_investment_authority_added_by_optional_refusal(self):
        bench=self.series('SPY');bench[0]['ticker']='QQQ'
        r=self.compute(benchmark_rows=bench)
        for key in ['a1_source_admitted','portfolio_approval','rank_promotion','source_rights_verified']:
            self.assertFalse(r[key])

    def test_job_fragment_discovers_cases_and_remains_disabled(self):
        fragment=(ROOT/'.github/workflows/free_data_daily_update.yml').read_text()
        self.assertIn('python tests/etf116_research_backend_smoke.py',fragment)
        self.assertTrue((ROOT/'tests/etf116_research_backend_smoke.py').is_file())
        self.assertIn("false && vars.ETF116_RESEARCH_ENABLED",fragment)
        self.assertEqual(fragment.count("cron: '30 23 * * 1-5'"),1)



if __name__=='__main__':unittest.main()

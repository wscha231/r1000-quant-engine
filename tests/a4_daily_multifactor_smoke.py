"""Daily as-of and multivariate experiment contract; synthetic inputs only."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import a4_daily_multifactor as daily


class DailyMultifactor(unittest.TestCase):
    def prices(self, n=1500):
        rng=np.random.default_rng(287)
        index=pd.bdate_range('2016-01-04',periods=n)
        close=pd.Series(100*np.exp(np.cumsum(rng.normal(.0002,.012,n))),index=index)
        benchmark=pd.Series(100*np.exp(np.cumsum(rng.normal(.0001,.009,n))),index=index)
        return close,benchmark

    def sessions(self):
        return [dict(session='2026-11-12',close_utc='2026-11-12T21:00:00+00:00'),
                dict(session='2026-11-13',close_utc='2026-11-13T21:00:00+00:00'),
                dict(session='2026-11-16',close_utc='2026-11-16T21:00:00+00:00')]

    def observation(self, value=100, **kwargs):
        row=dict(logical_id='payrolls',source_id='rtdsm:EMPLOY',value=value,
                 unit='thousands_persons',frequency='monthly',max_age_days=90,
                 family='GROWTH',observation_date='2026-10-01',
                 available_at='2026-11-13T21:01:00+00:00',
                 collected_at='2026-11-14T01:00:00+00:00',original_sha256='a'*64)
        return {**row,**kwargs}

    def test_registry_and_combinations_are_closed(self):
        reg=daily.registry()
        self.assertGreaterEqual(reg['distinct_macro_inputs'],20)
        self.assertEqual(reg['technical_features'],26)
        names=[r['id'] for r in reg['features']]
        self.assertEqual(len(names),len(set(names)))
        for groups in daily.COHORTS.values():
            for features in groups.values():
                self.assertTrue(set(features)<=set(names))
                self.assertEqual(len(features),len(set(features)))
        self.assertFalse(reg['derived_features_are_independent_sources'])

    def test_monthly_state_is_not_visible_before_real_availability(self):
        panel=daily.macro_state([self.observation()],self.sessions())
        self.assertTrue(panel['level:payrolls'].iloc[:2].isna().all())
        self.assertEqual(panel['level:payrolls'].iloc[2],100)

    def test_current_history_cannot_backfill_past(self):
        row=self.observation(available_at='2026-11-17T00:00:00Z')
        panel=daily.macro_state([row],self.sessions())
        self.assertTrue(panel.isna().all().all())

    def test_future_append_and_null_latest_preserve_prefix(self):
        sessions=self.sessions()
        first=self.observation(available_at='2026-11-12T20:00:00Z')
        original=daily.macro_state([first],sessions)
        later=self.observation(None,available_at='2026-11-16T20:00:00Z')
        changed=daily.macro_state([first,later],sessions)
        pd.testing.assert_frame_equal(original.iloc[:2],changed.iloc[:2])
        self.assertTrue(np.isnan(changed['level:payrolls'].iloc[-1]))

    def test_conflicting_same_clock_and_source_changes_refuse(self):
        first=self.observation()
        with self.assertRaisesRegex(ValueError,'CONFLICTING_VINTAGE'):
            daily.macro_state([first,{**first,'value':101}],self.sessions())
        with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):
            daily.macro_state([first,{**first,'source_id':'bls:PAYEMS'}],self.sessions())

    def test_units_and_age_cannot_extend_validity(self):
        for changes,reason in [({'unit':'persons'},'UNIT_FREQUENCY'),({'max_age_days':900},'MACRO_AGE'),
                               ({'value':True},'MACRO_VALUE')]:
            with self.assertRaisesRegex(ValueError,reason):
                daily.macro_state([self.observation(**changes)],self.sessions())

    def test_dated_quarterly_source_retains_its_own_age_contract(self):
        row=self.observation(4.1,logical_id='unemployment',source_id='rtdsm:RUC',unit='percent',max_age_days=150)
        self.assertEqual(daily.macro_state([row],self.sessions())['level:unemployment'].iloc[-1],4.1)
        with self.assertRaisesRegex(ValueError,'MACRO_AGE'):
            daily.macro_state([self.observation(max_age_days=150)],self.sessions())

    def test_funding_bp_and_matched_observation_dates(self):
        common=dict(available_at='2026-11-12T20:00:00Z',observation_date='2026-11-10',
                    frequency='daily',unit='percent',max_age_days=5,family='FUNDING')
        rows=[self.observation(4.01,logical_id='sofr',source_id='nyfed:SOFR',**common),
              self.observation(4.00,logical_id='iorb',source_id='frb:IORB',**common)]
        value=daily.macro_state(rows,self.sessions())['funding:sofr_minus_iorb'].iloc[0]
        self.assertAlmostEqual(value,1)
        rows[1]['observation_date']='2026-11-09'
        self.assertTrue(daily.macro_state(rows,self.sessions())['funding:sofr_minus_iorb'].isna().all())

    def test_technical_prefix_unchanged_by_future_prices(self):
        close,benchmark=self.prices()
        original=daily.price_features(close,benchmark)
        changed_close=close.copy();changed_close.iloc[1000:]*=2
        changed_benchmark=benchmark.copy();changed_benchmark.iloc[1000:]*=3
        changed=daily.price_features(changed_close,changed_benchmark)
        pd.testing.assert_frame_equal(original.iloc[:1000],changed.iloc[:1000])

    def test_ridge_uses_training_scale_and_all_features(self):
        rng=np.random.default_rng(1)
        x=rng.normal(size=(1000,2));y=2*x[:,0]-3*x[:,1]
        test=np.array([[2.,1.],[-1.,3.]])
        forecast,pin=daily.ridge_predictions(x,y,test)
        shifted=np.column_stack([x[:,0]*1000+500,x[:,1]*.001-2])
        changed=np.column_stack([test[:,0]*1000+500,test[:,1]*.001-2])
        equivalent,_=daily.ridge_predictions(shifted,y,changed)
        np.testing.assert_allclose(forecast,equivalent,rtol=1e-10,atol=1e-10)
        self.assertEqual(pin['active_features'],2)
        self.assertLess(float(np.mean((forecast-test@np.array([2.,-3.]))**2)),.02)

    def test_long_horizon_can_fit_without_twenty_independent_windows(self):
        close,benchmark=self.prices(1700)
        panel=daily.price_features(close,benchmark)
        shared=sorted(set(daily.TREND+daily.RISK))
        result=daily.evaluate(panel,close,'TECHNICAL','ALL_TECHNICAL',horizon=252,outcome='return',shared_columns=shared)
        self.assertGreater(result['oos_rows'],0)
        self.assertLess(result['nonoverlap_oos_windows'],20)
        self.assertEqual(result['evidence_status'],'INSUFFICIENT_INDEPENDENT_EVIDENCE')
        self.assertFalse(result['eligible_for_selector'])
        for fold in result['folds']:
            self.assertLess(fold['last_training_label_position'],fold['first_test_position'])

    def test_shared_cohort_prevents_arm_specific_sample_selection(self):
        close,benchmark=self.prices(1700)
        panel=daily.price_features(close,benchmark)
        panel.loc[panel.index[1000:1100],'realized_vol_63']=np.nan
        shared=sorted(set(daily.TREND+daily.RISK))
        a=daily.evaluate(panel,close,'TECHNICAL','TREND',horizon=21,outcome='return',shared_columns=shared)
        b=daily.evaluate(panel,close,'TECHNICAL','RISK',horizon=21,outcome='return',shared_columns=shared)
        self.assertEqual(a['shared_cohort_sha256'],b['shared_cohort_sha256'])
        self.assertEqual(a['oos_rows'],b['oos_rows'])
        self.assertEqual(a['baseline_rmse_pp'],b['baseline_rmse_pp'])

    def test_future_prices_do_not_change_past_fit_parameters(self):
        close,benchmark=self.prices(1700)
        panel=daily.price_features(close,benchmark)
        shared=list(daily.RISK)
        before=daily.evaluate(panel,close,'TECHNICAL','RISK',horizon=21,outcome='return',shared_columns=shared)
        revised=close.copy();revised.iloc[1100:]*=1.5
        changed=daily.price_features(revised,benchmark)
        after=daily.evaluate(changed,revised,'TECHNICAL','RISK',horizon=21,outcome='return',shared_columns=shared)
        self.assertEqual(before['folds'][0]['parameter_sha256'],after['folds'][0]['parameter_sha256'])

    def test_nonreturn_direction_is_not_reported(self):
        close,benchmark=self.prices(1500)
        panel=daily.price_features(close,benchmark)
        row=daily.evaluate(panel,close,'TECHNICAL','RISK',horizon=21,outcome='maximum_drawdown',shared_columns=list(daily.RISK))
        self.assertIsNone(row['direction_accuracy'])

    def test_family_includes_missing_cases(self):
        rows=[dict(p_value=.001),dict(p_value=None),dict(p_value=None)]
        daily.adjust_family(rows)
        self.assertAlmostEqual(rows[0]['family_q_value'],.001*3*(1+1/2+1/3))
        self.assertNotIn('family_q_value',rows[1])

    def test_spec_pin_checked_before_fit(self):
        with patch.object(daily,'evaluate',side_effect=AssertionError('unexpected fit')):
            with self.assertRaisesRegex(ValueError,'SPECIFICATION_PIN'):
                daily.compare({}, {}, expected_spec_sha256='0'*64)

    def test_horizon_changes_require_another_preregistration(self):
        close,benchmark=self.prices(10)
        panel=daily.price_features(close,benchmark)
        with self.assertRaisesRegex(ValueError,'DECLARED_HORIZONS'):
            daily.compare({'SPY':panel,'QQQ':panel},{'SPY':close,'QQQ':benchmark},
                          expected_spec_sha256=daily.digest(daily.specification()),horizons=(21,))

    def test_missing_target_cannot_reduce_predeclared_family(self):
        close,benchmark=self.prices(10)
        panel=daily.price_features(close,benchmark)
        with patch.object(daily,'evaluate',side_effect=AssertionError('unexpected fit')):
            with self.assertRaisesRegex(ValueError,'TARGETS'):
                daily.compare({'SPY':panel},{'SPY':close},expected_spec_sha256=daily.digest(daily.specification()))


if __name__=='__main__':
    unittest.main()

#!/usr/bin/env python3
"""Behavioral synthetic tests of the incumbent walk-forward fit/predict path."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import r1000_pipeline as pipeline
from r1000_config import EngineConfig


def synthetic_frame():
    dates = pipeline.month_end_trading_days('2016-01-01', '2022-03-31')
    rows = []
    for month, date in enumerate(dates):
        for security in range(100):
            row = dict(ticker=f'T{security:03d}', rebalance_date=date, feature_date=date,
                       px=20.0, dollar_vol_20d=750000.0, mktcap=np.nan,
                       signal_a=security / 100.0, signal_b=np.sin(month / 12.0) + security / 1000.0)
            for label, months in (('1m', 1), ('3m', 3), ('6m', 6), ('12m', 12), ('24m', 24), ('36m', 36)):
                row[f'r_{label}'] = .02 + security / 500.0
                row[f'bench_r_{label}'] = .01
                row[f'r_{label}_label_end_date'] = date + pd.DateOffset(months=months)
                row[f'bench_r_{label}_label_end_date'] = date + pd.DateOffset(months=months)
                if date >= pd.Timestamp('2021-09-01'):
                    row[f'r_{label}'] = row[f'bench_r_{label}'] = np.nan
            rows.append(row)
    frame = pd.DataFrame(rows)
    frame['feature_available_from'] = pipeline.decision_session_close_utc(frame['rebalance_date'])
    return frame


def configuration(root):
    cfg = EngineConfig()
    cfg.base_dir = str(root)
    cfg.start_date = '2016-01-01'
    cfg.evaluation_start_date = '2021-09-01'
    cfg.end_date = '2022-03-31'
    cfg.min_train_samples = 3000
    cfg.resume_partial_walkforward = False
    cfg.reuse_existing_artifacts = False
    cfg.walkforward_retrain_frequency_months = 3
    cfg.cat_validation_months = 0
    cfg.ranking_enabled = False
    return cfg


class WalkforwardDecisionClockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = synthetic_frame()

    def test_asof_context_ignores_future_coverage_and_late_published_old_rows(self):
        cfg = configuration('unused-synthetic-no-io')
        cutoff = pd.Timestamp('2021-09-30')
        base, context = pipeline._walkforward_training_pool(self.frame, cfg, cutoff)
        future = self.frame.loc[self.frame['feature_date'].ge('2022-01-01')].copy()
        future['mktcap'], future['dollar_vol_20d'] = 1e12, 50000000.0
        # A dense, fully labelled future cohort actually flips all three old
        # full-frame statistics. It is not a no-op negative control.
        far = []
        for copy_id in range(3):
            later = self.frame.copy()
            later['ticker'] = f'F{copy_id}:' + later['ticker']
            later['feature_date'] += pd.DateOffset(years=10)
            later['rebalance_date'] += pd.DateOffset(years=10)
            later['feature_available_from'] += pd.DateOffset(years=10)
            for column in [c for c in later if c.endswith('_label_end_date')]:
                later[column] += pd.DateOffset(years=10)
            later['mktcap'], later['dollar_vol_20d'] = 1e12, 50000000.0
            far.append(later)
        late = self.frame.iloc[:100].copy()
        late['ticker'] = 'LATE:' + late['ticker']
        late['feature_available_from'] = pd.Timestamp('2025-01-01', tz='UTC')
        variant = pd.concat([self.frame, future, late, *far], ignore_index=True)
        self.assertGreaterEqual(float(variant['mktcap'].notna().mean()), .25)
        self.assertGreater(float(variant['dollar_vol_20d'].max()), 1100000)
        self.assertGreater(float(variant.groupby('rebalance_date')['ticker'].nunique().median()),
                           context['median_monthly_tickers'])
        actual, changed_context = pipeline._walkforward_training_pool(variant, cfg, cutoff)
        self.assertEqual(context, changed_context)
        self.assertEqual(list(zip(base['ticker'], base['feature_date'])),
                         list(zip(actual['ticker'], actual['feature_date'])))
        self.assertGreater(len(base), context['effective_min_train_samples'])
        self.assertEqual(context['min_dollar_vol_20d'], 500000.0)
        self.assertFalse(context['require_mktcap'])
        self.assertTrue(pipeline.label_ready_before(actual, 'short', cutoff).all())
        future_fit = actual.loc[actual['future_winner_available']]
        self.assertGreater(len(future_fit), 500)
        self.assertTrue(pipeline.label_ready_before(future_fit, 'future', cutoff).all())

    def test_explicit_unavailable_decision_clock_is_not_a_qualified_row(self):
        month = self.frame.loc[self.frame['rebalance_date'].eq('2021-11-30')].copy()
        month.loc[month.index[0], 'feature_available_from'] = pd.Timestamp('2021-12-01', tz='UTC')
        month.loc[month.index[1], 'feature_available_from'] = pd.NaT
        result = pipeline._walkforward_asof_rows(month, '2021-11-30')
        self.assertEqual(len(result), 98)
        self.assertNotIn(month.iloc[0]['ticker'], set(result['ticker']))
        self.assertNotIn(month.iloc[1]['ticker'], set(result['ticker']))

    def run_core(self, frame, *, end='2022-03-31', evaluation_start='2021-09-01', retrain=3):
        trace = dict(scalers=[], fits=[], adaptive=[])
        with tempfile.TemporaryDirectory() as temporary:
            cfg = configuration(temporary)
            cfg.end_date = end
            cfg.evaluation_start_date = evaluation_start
            cfg.walkforward_retrain_frequency_months = retrain
            scaler = pipeline.fit_scaler
            ridge_fit = pipeline.Ridge.fit
            adaptive = pipeline.compute_adaptive_ensemble_state
            def fit_scaler(rows, features):
                value = scaler(rows, features)
                trace['scalers'].append((rows.copy(), copy.deepcopy(value)))
                return value
            def fit_ridge(model, x, y, **kwargs):
                trace['fits'].append((float(model.alpha), np.array(x), np.array(y)))
                return ridge_fit(model, x, y, **kwargs)
            def score(rows, _mapping, cfg=None):
                result = rows.copy()
                result['score_linear'] = result['pred_lin_ret']
                result['score_cat'] = result['pred_cat_ret']
                result['score_ranker'] = result['pred_rank']
                result['score'] = result['pred_lin_ret']
                return result
            def adaptive_history(rows, cfg, as_of_date=None):
                if not rows.empty and as_of_date is not None:
                    self.assertTrue(pipeline.label_ready_before(rows, 'short', as_of_date).all())
                trace['adaptive'].append(len(rows))
                return adaptive(rows, cfg, as_of_date=as_of_date)
            with patch.object(pipeline, 'model_feature_columns', return_value=['signal_a', 'signal_b']), \
                 patch.object(pipeline, 'resolve_optional_catboost', return_value=dict(available=False, error='SYNTHETIC_TEST_ONLY')), \
                 patch.object(pipeline, 'fit_scaler', fit_scaler), \
                 patch.object(pipeline.Ridge, 'fit', fit_ridge), \
                 patch.object(pipeline, 'add_model_score_columns', score), \
                 patch.object(pipeline, 'add_total_score_columns', side_effect=lambda rows, *a, **k: rows), \
                 patch.object(pipeline, 'apply_focus_score_overlay', side_effect=lambda rows, *a, **k: rows), \
                 patch.object(pipeline, 'compute_adaptive_ensemble_state', adaptive_history), \
                 patch.object(pipeline, 'save_phase4_latest_scoring_artifacts', return_value=None):
                pipeline.train_walkforward(cfg, frame)
            output = pd.read_parquet(Path(temporary)/'feature_store'/'scored_oos_latest.parquet')
        self.assertGreater(len(trace['fits']), 0, 'A blocked/empty run is not an invariance control')
        self.assertGreater(len(output), 0)
        return output, trace

    def test_late_only_month_cannot_shift_later_retraining_anchor(self):
        baseline_frame = self.frame.loc[self.frame['rebalance_date'].ne('2021-10-29')].copy()
        late = self.frame.loc[self.frame['rebalance_date'].eq('2021-10-29')].copy()
        late['feature_available_from'] = pd.Timestamp('2025-01-01', tz='UTC')
        original, original_trace = self.run_core(baseline_frame, end='2021-11-30',
                                                evaluation_start='2021-10-01', retrain=2)
        actual, actual_trace = self.run_core(pd.concat([baseline_frame,late],ignore_index=True),
                                            end='2021-11-30', evaluation_start='2021-10-01', retrain=2)
        self.assertEqual(list(original['rebalance_date']),list(actual['rebalance_date']))
        self.assertEqual(sorted(original['rebalance_date'].unique().tolist()),
                         [pd.Timestamp('2021-09-30'),pd.Timestamp('2021-11-30')])
        self.assertEqual(len(original_trace['fits']),len(actual_trace['fits']))
        self.assertEqual(len(original_trace['scalers']),1)
        self.assertEqual(len(actual_trace['scalers']),1)
        np.testing.assert_allclose(original['pred_lin_ret'],actual['pred_lin_ret'],rtol=0,atol=1e-12)

    def test_real_fit_predict_preserves_unlabelled_latest_and_future_tail_invariance(self):
        baseline, baseline_trace = self.run_core(self.frame)
        changed = self.frame.copy()
        future = changed['feature_date'].ge('2022-01-01')
        changed.loc[future, 'mktcap'] = 1e12
        changed.loc[future, 'dollar_vol_20d'] = 50000000.0
        changed.loc[future, 'signal_a'] += 1000
        # These past decision outcomes are still unavailable at the decision;
        # revealing/altering their later labels must not change their scores.
        target = changed['feature_date'].eq('2021-11-30')
        for label in ('1m','3m','6m','12m','24m','36m'):
            changed.loc[target, f'r_{label}'] = 99.0
            changed.loc[target, f'bench_r_{label}'] = -.5
        actual, actual_trace = self.run_core(changed)
        earlier = baseline['rebalance_date'].le('2021-11-30')
        observed = actual.loc[actual['rebalance_date'].le('2021-11-30')]
        expected = baseline.loc[earlier]
        self.assertEqual(list(zip(expected['ticker'],expected['rebalance_date'])),
                         list(zip(observed['ticker'],observed['rebalance_date'])))
        np.testing.assert_allclose(expected['pred_lin_ret'],observed['pred_lin_ret'],rtol=0,atol=1e-12)
        np.testing.assert_allclose(expected['score'],observed['score'],rtol=0,atol=1e-12)
        first_fit, first_scaler = baseline_trace['scalers'][0]
        other_fit, other_scaler = actual_trace['scalers'][0]
        self.assertEqual(first_scaler,other_scaler)
        self.assertEqual(list(zip(first_fit['ticker'],first_fit['feature_date'])),
                         list(zip(other_fit['ticker'],other_fit['feature_date'])))
        self.assertTrue(pipeline.label_ready_before(first_fit,'short','2021-09-30').all())
        self.assertTrue(first_fit['feature_date'].lt('2021-09-30').all())
        self.assertEqual(baseline['rebalance_date'].max(),pd.Timestamp('2022-03-31'))
        self.assertEqual(len(baseline.loc[baseline['rebalance_date'].eq('2022-03-31')]),100)
        self.assertTrue(baseline.loc[baseline['rebalance_date'].eq('2022-03-31'),'y_blend'].isna().all())
        # Confirm that the negative mutation really reached the diagnostic raw
        # outcomes while the two independent fit/predict runs remained valid.
        self.assertTrue(actual.loc[actual['rebalance_date'].eq('2021-11-30'),'r_6m'].eq(99).all())
        self.assertTrue(baseline.loc[baseline['rebalance_date'].eq('2021-11-30'),'r_6m'].isna().all())


if __name__ == '__main__':
    unittest.main()

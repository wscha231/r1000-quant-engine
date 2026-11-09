#!/usr/bin/env python3
"""Behavioral synthetic tests of the incumbent walk-forward fit/predict path."""
from __future__ import annotations

import copy
import ast
import inspect
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

    def test_final_weekend_or_holiday_uses_completed_close_without_new_decision(self):
        cfg=configuration('unused-synthetic-no-io')
        mature=self.frame.loc[self.frame['feature_date'].eq('2016-01-29')].copy()
        friday=pipeline._walkforward_mature_history(mature,cfg,'2021-09-17',end_of_evidence=True)
        saturday=pipeline._walkforward_mature_history(mature,cfg,'2021-09-18',end_of_evidence=True)
        self.assertGreater(len(friday),0)
        pd.testing.assert_frame_equal(friday,saturday)
        wednesday=pipeline._walkforward_mature_history(mature,cfg,'2021-11-24',end_of_evidence=True)
        thanksgiving=pipeline._walkforward_mature_history(mature,cfg,'2021-11-25',end_of_evidence=True)
        pd.testing.assert_frame_equal(wednesday,thanksgiving)
        # Non-session dates remain invalid as actual decisions.
        self.assertTrue(pipeline._walkforward_mature_history(mature,cfg,'2021-09-18').empty)

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


class LatestAdaptiveOutcomeTests(unittest.TestCase):
    def history(self, mature_months):
        rows=[]
        sessions=pipeline.month_end_trading_days('2019-01-01','2020-12-31')
        for month,date in enumerate(sessions[:12]):
            for name in range(20):
                row=dict(ticker=f'S{name}',rebalance_date=date,feature_date=date,
                         y_blend=(name-10)/20 if month<mature_months else np.nan,
                         score_linear=name,score_cat=20-name,score_ranker=(name*7)%20)
                for label,months in (('1m',1),('3m',3),('6m',6)):
                    row[f'r_{label}']=(name-10)/20 if month<mature_months else np.nan
                    row[f'bench_r_{label}']=.01 if month<mature_months else np.nan
                    row[f'r_{label}_label_end_date']=sessions[month+months]
                    row[f'bench_r_{label}_label_end_date']=sessions[month+months]
                for label in ('12m','24m','36m'):
                    row[f'r_{label}']=row[f'bench_r_{label}']=np.nan
                    row[f'r_{label}_label_end_date']=row[f'bench_r_{label}_label_end_date']=pd.NaT
                rows.append(row)
        return pd.DataFrame(rows)

    def state(self, history, cfg=None):
        return pipeline.compute_adaptive_ensemble_state(history,cfg or EngineConfig(),as_of_date='2020-01-31')

    def test_five_mature_plus_seven_unlabelled_never_activates(self):
        history=self.history(5)
        original=history.copy(deep=True)
        state=self.state(history)
        self.assertFalse(state['active'])
        self.assertEqual(state['history_months'],5)
        self.assertEqual(state['weights'],self.state(history.loc[history.y_blend.notna()])['weights'])
        pd.testing.assert_frame_equal(history,original)

    def test_six_mature_weights_and_lookback_ignore_unknown_tail(self):
        history=self.history(6)
        mature=history.loc[history.y_blend.notna()].copy()
        original=self.state(mature)
        actual=self.state(history)
        self.assertTrue(actual['active'])
        self.assertEqual(actual,original)
        self.assertEqual(actual['history_months'],6)
        cfg=EngineConfig();cfg.adaptive_ensemble_lookback_months=3;cfg.adaptive_ensemble_min_months=3
        bounded=self.state(history,cfg)
        self.assertTrue(bounded['active'])
        self.assertEqual(bounded['history_months'],3)
        pd.testing.assert_series_equal(pd.Series(bounded['weights']),pd.Series(self.state(mature,cfg)['weights']))
        invalid=history.copy();invalid.loc[invalid.y_blend.isna(),'y_blend']=np.inf
        self.assertEqual(self.state(invalid,cfg),bounded)

    def test_both_latest_consumers_execute_the_shared_outcome_gate(self):
        tree=ast.parse(inspect.getsource(pipeline.build_latest_recommendations))
        assignments={name:[node for node in ast.walk(tree) if isinstance(node,ast.Assign)
                           and any(isinstance(target,ast.Name) and target.id==name for target in node.targets)]
                     for name in ('latest_adaptive_state','_regime_w')}
        for nodes in assignments.values():
            self.assertEqual(len(nodes),1,'No later bundle fallback may replace the as-of state')
        gates=[node for node in ast.walk(tree) if isinstance(node,ast.Assign)
               and any(isinstance(target,ast.Name) and target.id=='adaptive_history' for target in node.targets)
               and any(isinstance(call,ast.Call) and isinstance(call.func,ast.Name)
                       and call.func.id=='_walkforward_mature_history' for call in ast.walk(node.value))]
        applies=[node for node in ast.walk(tree) if isinstance(node,ast.Call)
                 and isinstance(node.func,ast.Name) and node.func.id=='apply_adaptive_ensemble_state']
        self.assertEqual((len(gates),len(applies)),(1,2))
        future_bundle=type('FutureBundle',(),dict(adaptive_ensemble_weights={'linear':1.,'catboost':0.,'ranker':0.},
            adaptive_ensemble_diagnostics={'active':True,'history_months':99},
            regime_ensemble_weights={'balanced':{'linear':1.,'catboost':0.,'ranker':0.}}))()
        for mature in (5,6):
            history=self.history(mature)
            if mature==6:
                history['live_event_alert_label']='balanced'
            poison=history['rebalance_date'].eq(sorted(history['rebalance_date'].unique())[6])
            history.loc[poison,'y_blend']=99.
            for label in ('1m','3m','6m'):
                history.loc[poison,f'r_{label}']=99.
                history.loc[poison,f'bench_r_{label}']=.01
            history.loc[poison,'r_6m_label_end_date']=pd.Timestamp('2022-01-31')
            history.loc[poison,'bench_r_6m_label_end_date']=pd.Timestamp('2022-01-31')
            original=history.copy(deep=True)
            namespace=dict(compute_adaptive_ensemble_state=pipeline.compute_adaptive_ensemble_state,
                compute_regime_conditional_ensemble_weights=pipeline.compute_regime_conditional_ensemble_weights,
                _walkforward_mature_history=pipeline._walkforward_mature_history,
                apply_adaptive_ensemble_state=pipeline.apply_adaptive_ensemble_state,
                pd=pd,adaptive_history=history,cfg=EngineConfig(),adaptive_as_of=pd.Timestamp('2020-01-31'),
                model_bundle=future_bundle,latest_df=pd.DataFrame({'ticker':[f'N{i}' for i in range(20)],
                                                               'live_event_alert_label':['balanced']*20}))
            namespace['adaptive_history']=eval(compile(ast.Expression(gates[0].value),'<actual-latest-maturity-gate>','eval'),namespace)
            for name in ('latest_adaptive_state','_regime_w'):
                node=assignments[name][0]
                self.assertLess(node.lineno,min(call.lineno for call in applies))
                namespace[name]=eval(compile(ast.Expression(node.value),'<actual-current-weight-state>','eval'),namespace)
            state=namespace['latest_adaptive_state']
            self.assertEqual(state['active'],mature==6)
            self.assertEqual(state['history_months'],mature)
            expected=namespace['_regime_w'].get('balanced',state['weights'])
            for call in applies:
                result=eval(compile(ast.Expression(call),'<actual-latest-downstream-apply>','eval'),namespace)
                self.assertEqual(len(result),20)
                self.assertTrue(result['adaptive_ensemble_active'].eq(mature==6).all())
                for key in ('linear','catboost','ranker'):
                    np.testing.assert_allclose(result['ensemble_weight_'+key],expected[key])
            pd.testing.assert_frame_equal(history,original)

    def test_duplicate_index_keeps_nonempty_mature_adaptive_state(self):
        history=self.history(6)
        expected=self.state(history)
        history.index=[0]*len(history)
        self.assertTrue(expected['active'])
        self.assertEqual(self.state(history),expected)
        self.assertEqual(len(history),240)

    def test_strict_mature_six_positive_ignores_finite_future_endpoint(self):
        history=self.history(6)
        cfg=EngineConfig()
        expected=pipeline._walkforward_mature_history(history,cfg,'2020-01-31')
        poison=history.loc[history['rebalance_date'].eq(sorted(history['rebalance_date'].unique())[6])].copy()
        for label in ('1m','3m','6m'):
            poison[f'r_{label}']=99.
            poison[f'bench_r_{label}']=.01
        poison['y_blend']=99.
        poison['r_6m_label_end_date']=poison['bench_r_6m_label_end_date']=pd.Timestamp('2022-01-31')
        actual=pipeline._walkforward_mature_history(pd.concat([history,poison],ignore_index=True),cfg,'2020-01-31')
        pd.testing.assert_frame_equal(expected.reset_index(drop=True),actual.reset_index(drop=True))
        self.assertTrue(self.state(actual)['active'])
        self.assertEqual(self.state(actual)['history_months'],6)
        eligible=poison.copy()
        eligible['r_6m_label_end_date']=eligible['bench_r_6m_label_end_date']=pd.Timestamp('2020-01-30')
        control=pipeline._walkforward_mature_history(pd.concat([history,eligible],ignore_index=True),cfg,'2020-01-31')
        self.assertEqual(self.state(control)['history_months'],7)


class UniverseSizeCausalityTests(unittest.TestCase):
    def monthly(self, dates=('2021-01-29', '2021-02-26')):
        rows=[]
        for month,date in enumerate(dates):
            for name in range(8):
                rows.append(dict(ticker=f'S{name}', rebalance_date=pd.Timestamp(date),
                                 px=20., shares=np.nan, dollar_vol_20d=1e6+name*1e5,
                                 vol_252d=.2, dd_1y=.2,
                                 mktcap=(2000.+name if month==0 and name<2 else np.nan),
                                 universe_source='historical_membership_file'))
        frame=pd.DataFrame(rows)
        frame['feature_available_from']=pipeline.decision_session_close_utc(frame['rebalance_date'])
        return frame

    def cfg(self):
        cfg=EngineConfig()
        cfg.min_mktcap=1000.
        cfg.min_dollar_vol_20d=1.
        cfg.universe_size=3
        return cfg

    def test_actual_universe_route_retains_bounded_starved_latest_retry(self):
        class SelectionBoundary(Exception):
            pass
        dates=pd.to_datetime(['2021-01-29','2021-02-26'])
        names=[f'S{i:02d}' for i in range(25)]
        candidates=pd.DataFrame(dict(ticker=names,cik10=['0000000001']*25,
                                     Name=names,sector=['Synthetic']*25,
                                     universe_source=['historical_membership_file']*25))
        for latest_known,historical_known in ((0,True),(6,True),(0,False)):
            with self.subTest(latest_coverage=latest_known/25,historical_known=historical_known):
                calls=[]; observed={}
                def prices(_paths,ticker):
                    ordinal=names.index(ticker)
                    return pd.DataFrame(dict(px=[20.,20.],dollar_vol_20d=[1e6+ordinal]*2,
                        vol_252d=[.2,.2],dd_1y=[.2,.2],
                        shares=[100. if historical_known else np.nan,
                                100. if ordinal<latest_known else np.nan],
                        feature_available_from=pipeline.decision_session_close_utc(pd.Series(dates)).to_numpy()),index=dates)
                def proxy(_cfg,_paths,tickers,max_new=500):
                    calls.append((list(tickers),max_new))
                    if max_new==600:
                        return pd.DataFrame()  # Initial batch is not the retry.
                    return pd.DataFrame(dict(ticker=tickers,mktcap_proxy=[1e12]*len(tickers),
                        updated_at=['2021-03-01T00:00:00Z']*len(tickers),price_currency=['USD']*len(tickers)))
                def selected(*args,**kwargs):
                    observed['rows']=args[5].copy()
                    raise SelectionBoundary()
                with patch.object(pipeline,'get_paths',return_value={}), \
                     patch.object(pipeline,'load_historical_universe_membership',return_value=pd.DataFrame()), \
                     patch.object(pipeline,'build_candidate_universe',return_value=candidates), \
                     patch.object(pipeline,'ensure_prices_cached_incremental',return_value=None), \
                     patch.object(pipeline,'load_or_update_fund_panel',return_value=pd.DataFrame()), \
                     patch.object(pipeline,'write_fund_panel_recent_flow_report',return_value=None), \
                     patch.object(pipeline,'month_end_trading_days',return_value=list(dates)), \
                     patch.object(pipeline,'load_px',side_effect=prices), \
                     patch.object(pipeline,'compute_daily_tech_table',side_effect=lambda frame:frame), \
                     patch.object(pipeline,'apply_leader_rescue_backtest_mode_filter',side_effect=lambda cfg,paths,frame:frame), \
                     patch.object(pipeline,'asof_join_fundamentals',side_effect=lambda frame,*args:frame), \
                     patch.object(pipeline,'merge_trend_features_into_monthly',side_effect=lambda frame,*args:frame), \
                     patch.object(pipeline,'attach_fund_panel_join_diagnostics',side_effect=lambda frame,*args:frame), \
                     patch.object(pipeline,'write_stage_coverage_report',return_value=None), \
                     patch.object(pipeline,'load_mktcap_proxy_cache',return_value=pd.DataFrame()), \
                     patch.object(pipeline,'ensure_mktcap_proxy',side_effect=proxy), \
                     patch.object(pipeline,'write_leader_drop_diagnostics',side_effect=selected):
                    with self.assertRaises(SelectionBoundary):
                        pipeline.build_universe_monthly(self.cfg())
                self.assertEqual([cap for _,cap in calls],[600,1200] if historical_known else [600])
                if historical_known:
                    self.assertEqual(len(calls[1][0]),25-latest_known)
                latest=observed['rows'].loc[observed['rows']['rebalance_date'].eq(dates[-1])]
                self.assertGreater(len(latest),0)
                self.assertTrue(latest['mktcap'].dropna().le(2000.).all())
                self.assertFalse(latest['mktcap_proxy'].notna().any())

    def test_actual_monthly_selection_ignores_future_cohort_and_late_rows(self):
        baseline=self.monthly()
        before,ranked,expected=pipeline._causal_universe_size_rows(baseline,self.cfg())
        future=pd.concat([self.monthly(('2026-01-30',)) for _ in range(10)],ignore_index=True)
        future['ticker']=[f'F{i}' for i in range(len(future))]
        future['mktcap']=1e12
        late=self.monthly(('2021-01-29',))
        late['ticker']='LATE:'+late['ticker']
        late['feature_available_from']=pd.Timestamp('2025-01-01',tz='UTC')
        changed=pd.concat([baseline,future,late],ignore_index=True)
        self.assertGreater(changed['mktcap'].notna().mean(),.25)
        actual_pre,actual_ranked,actual=pipeline._causal_universe_size_rows(changed,self.cfg())
        for old,new in ((before,actual_pre),(ranked,actual_ranked),(expected,actual)):
            new=new.loc[new['rebalance_date'].lt('2022-01-01')]
            columns=['ticker','rebalance_date','mktcap','size_metric','mktcap_filter_used','mktcap_dollar_vol_fallback']
            if 'rank_size' in old: columns.append('rank_size')
            pd.testing.assert_frame_equal(old[columns].reset_index(drop=True),new[columns].reset_index(drop=True))
        self.assertEqual(len(expected),5)
        self.assertGreater(len(actual),len(expected))

    def test_former_latest_fallback_stays_identical_after_append(self):
        old=self.monthly(('2021-01-29',))
        old['mktcap']=100.  # All caps fail the existing minimum.
        before=pipeline._causal_universe_size_rows(old,self.cfg())[2]
        later=self.monthly(('2021-02-26',))
        later['mktcap']=1e12
        after=pipeline._causal_universe_size_rows(pd.concat([old,later],ignore_index=True),self.cfg())[2]
        pd.testing.assert_frame_equal(before.reset_index(drop=True),
                                      after.loc[after['rebalance_date'].eq('2021-01-29')].reset_index(drop=True))
        self.assertEqual(len(before),3)
        self.assertTrue(before['mktcap'].isna().all())
        self.assertTrue(before['mktcap_dollar_vol_fallback'].all())

    def test_proxy_uses_original_clock_and_refuses_unknown_future_stale_conflict(self):
        monthly=self.monthly(('2021-01-29',)).iloc[:1].copy()
        close=pipeline.decision_session_close_utc(monthly['rebalance_date']).iloc[0]
        good=pd.DataFrame([dict(ticker='S0',mktcap_proxy=5000.,updated_at=close,price_currency='USD')])
        result=pipeline._mktcap_proxy_at_decisions(monthly,good)
        self.assertEqual(float(result.iloc[0]['mktcap_proxy']),5000.)
        for stamp in (None,'invalid',close+pd.Timedelta(seconds=1),close-pd.Timedelta(days=15)):
            bad=good.copy();bad['updated_at']=stamp
            self.assertTrue(pipeline._mktcap_proxy_at_decisions(monthly,bad)['mktcap_proxy'].isna().all())
        future=good.copy();future['updated_at']=close+pd.Timedelta(days=365);future['mktcap_proxy']=9e15
        pd.testing.assert_frame_equal(result,pipeline._mktcap_proxy_at_decisions(monthly,pd.concat([good,future],ignore_index=True)))
        conflict=good.copy();conflict['mktcap_proxy']=6000.
        self.assertTrue(pipeline._mktcap_proxy_at_decisions(monthly,pd.concat([good,conflict],ignore_index=True))['mktcap_proxy'].isna().all())
        older=good.copy();older['updated_at']=close-pd.Timedelta(days=1)
        for later in (good.assign(mktcap_proxy=np.nan),good.assign(mktcap_proxy=0.),
                      pd.concat([good,conflict],ignore_index=True)):
            self.assertTrue(pipeline._mktcap_proxy_at_decisions(monthly,pd.concat([older,later],ignore_index=True))['mktcap_proxy'].isna().all())

    def test_adr_future_raw_or_proxy_cannot_rewrite_past_and_unknown_cap_is_not_zero(self):
        frame=self.monthly(('2021-01-29',)).iloc[:2].copy()
        frame.loc[frame.index[0],'universe_source']='adr_whitelist'
        frame['mktcap']=[10000.,5000.]
        clock=pipeline.decision_session_close_utc(frame['rebalance_date']).iloc[0]
        proxy=pd.DataFrame([dict(ticker='S0',mktcap_proxy=2000.,updated_at=clock,price_currency='USD')])
        expected=pipeline.apply_adr_usd_mktcap_proxy(frame,self.cfg(),{},proxy_snapshots=proxy)
        self.assertEqual(expected['mktcap'].tolist(),[2000.,5000.])
        future=frame.copy();future['rebalance_date']=pd.Timestamp('2026-01-30');future['mktcap']*=100
        later=proxy.copy();later['updated_at']=pd.Timestamp('2026-01-30T21:00:00Z');later['mktcap_proxy']=1e7
        actual=pipeline.apply_adr_usd_mktcap_proxy(pd.concat([frame,future],ignore_index=True),self.cfg(),{},
                                                 proxy_snapshots=pd.concat([proxy,later],ignore_index=True))
        pd.testing.assert_frame_equal(expected.reset_index(drop=True),actual.iloc[:2].reset_index(drop=True))
        for change in ({'updated_at':None},{'updated_at':clock+pd.Timedelta(seconds=1)},{'price_currency':'TWD'}):
            bad=proxy.assign(**change)
            unknown=pipeline.apply_adr_usd_mktcap_proxy(frame,self.cfg(),{},proxy_snapshots=bad)
            self.assertTrue(pd.isna(unknown.iloc[0]['mktcap']))
            self.assertEqual(unknown.iloc[0]['mktcap_px_shares_raw'],10000.)
            self.assertEqual(unknown.iloc[1]['mktcap'],5000.)

from tools.run_broker_ledger_replay import ResearchNextCloseSession, NYSE_CALENDAR


def c0_fixture():
    cfg = EngineConfig()
    cfg.end_date = "2026-04-30"
    dates = pd.to_datetime(["2026-01-30", "2026-02-27", "2026-03-31", "2026-04-30"])
    rows = []
    for date in dates:
        close = pipeline.decision_session_close_utc(pd.Series([date])).iloc[0]
        for index in range(18):
            row = dict.fromkeys(cfg.features, 0.2)
            row.update(dict.fromkeys(pipeline.CORE_FUNDAMENTAL_MINIMUM_FIELDS, 0.2))
            row.update(ticker=f"S{index:02}", Name=f"Synthetic {index}", sector=f"Sector{index % 6}",
                       rebalance_date=date, feature_date=date, feature_available_from=close,
                       score=(10.+index if date == dates[1] and index >= 9 else 4.0-index*.07),
                       px=100., mktcap=1e8*(index+1), dollar_vol_20d=1e8,
                       vol_6m=.2, mom_1m=.05, mom_3m=.1, mom_6m=.2, mom_12m=.3,
                       dist_ma200=.1, selection_confirmation_score=.9,
                       fundamental_presence_score=1., fundamental_reliability_score=1.,
                       fundamental_history_coverage_score=1., entry_quality_score=.8,
                       portfolio_sleeve_label=("core_compounder", "future_winner", "early_scout")[index % 3],
                       portfolio_sleeve_label_raw=("core_compounder", "future_winner", "early_scout")[index % 3],
                       revenues_ttm=1e9, net_income_ttm=1e8, ocf_ttm=1.5e8,
                       assets=2e9, liabilities=1e9, risk_penalty=0., rs_acceleration_score=.1,
                       revenue_growth_final=(.1 if index >= 13 else .5), roe_proxy=.25,
                       net_margin=.2, op_margin_ttm=.2, mom_24m=.8, revision_blueprint_score=.8,
                       fundamental_turnaround_acceleration_score=(.8 if index < 6 else .1),
                       cashflow_inflection_under_loss_score=(.8 if index < 6 else .1),
                       macro_risk_off_score=0., market_regime_score=1., spy_above_ma200=1.,
                       bench_above_ma200=1., market_breadth_regime_score=.8,
                       market_sector_participation=.7, systemic_crisis_score=0.,
                       live_event_risk_score=0., liquidity_drain_score=0., inflation_pressure_score=0.,
                       trend_template_full=1., price_above_ma50=1., price_above_ma200=1.,
                       relative_strength_composite=2-index*.02, _is_speculative=0.,
                       y_blend=999., r_6m=100., r_6m_label_end_date=date+pd.DateOffset(months=6))
            rows.append(row)
    sessions = NYSE_CALENDAR.schedule(start_date=dates[0].date(), end_date=cfg.end_date).index
    prices = {f"S{index:02}": pd.DataFrame({"close": 100., "open": 99.}, index=sessions)
              for index in range(18)}
    return cfg, pd.DataFrame(rows), prices


class CausalMonthlyDecisionTests(unittest.TestCase):
    def main_result(self, cfg, frame, prices):
        session = ResearchNextCloseSession(prices, evidence_end_date=cfg.end_date)
        original = pipeline.build_target_portfolio
        calls = []

        def observe(*args, **kwargs):
            result = original(*args, **kwargs)
            calls.append((args[1].copy(deep=True), dict(kwargs.get("prev_w") or {}), result[0].copy()))
            return result

        with patch.object(pipeline, "build_target_portfolio", side_effect=observe), \
             patch.object(pipeline, "merge_partial_sleeve_rebalance_state", wraps=pipeline.merge_partial_sleeve_rebalance_state) as partial, \
             patch.object(pipeline, "month_forward_return_open", side_effect=AssertionError("future-return feedback")), \
             patch.object(pipeline, "get_paths", side_effect=AssertionError("research output I/O")):
            result = pipeline.backtest_portfolio(cfg, frame, research_session=session)
            partial_calls = partial.call_count
        return result, session, calls, partial_calls

    def test_nonempty_original_main_future_open_and_tail_cannot_change_past_decisions(self):
        cfg, frame, prices = c0_fixture()
        first, session, calls, partial_calls = self.main_result(cfg, frame, prices)
        self.assertGreater(len(session.trades), 0)
        self.assertGreater(len(calls), 1)
        self.assertTrue(any(not call[2].empty for call in calls))
        self.assertTrue(any(call[1] for call in calls[1:]))
        self.assertGreater(partial_calls, 0)
        self.assertTrue(cfg.portfolio_position_risk_enabled)
        self.assertTrue(cfg.portfolio_hold_policy_enabled)
        self.assertTrue(cfg.sleeve_specific_rebalance_enabled)
        self.assertTrue(any("portfolio_hold_policy_bonus" in call[2] for call in calls))
        for call in calls:
            self.assertNotIn("y_blend", call[0])
            self.assertNotIn("r_6m", call[0])
        poisoned = {ticker: price.copy() for ticker, price in prices.items()}
        for price in poisoned.values():
            price.loc[price.index >= "2026-03-02", "open"] = 1e9
        changed = frame.copy()
        changed.loc[changed.rebalance_date > "2026-02-27", ["y_blend", "r_6m"]] = -1e10
        # An entirely later cohort must not add an evaluated current decision.
        tail = changed.tail(18).copy()
        tail["rebalance_date"] = tail["feature_date"] = pd.Timestamp("2027-01-29")
        tail["feature_available_from"] = pd.Timestamp("2027-01-29T21:00:00Z")
        second, other, _, _ = self.main_result(cfg, pd.concat([changed, tail], ignore_index=True), poisoned)
        self.assertEqual(first.monthly_returns.to_dict("records"), second.monthly_returns.to_dict("records"))
        pd.testing.assert_frame_equal(first.equity_curve, second.equity_curve)
        self.assertEqual(session.trades, other.trades)
        self.assertEqual(first.metrics["status"], "SYNTHETIC_ONLY_REAL_EXECUTION_BLOCKED")
        self.assertFalse(first.metrics["source_admission"])

    def test_future_close_changes_later_nav_but_not_prior_valid_targets(self):
        cfg, frame, prices = c0_fixture()
        first, session, _, _ = self.main_result(cfg, frame, prices)
        poisoned = {ticker: price.copy() for ticker, price in prices.items()}
        for price in poisoned.values():
            price.loc[price.index >= "2026-03-02", "close"] = 40.
        second, other, _, _ = self.main_result(cfg, frame, poisoned)
        before = first.monthly_returns.loc[first.monthly_returns.rebalance_date <= "2026-02-27"]
        after = second.monthly_returns.loc[second.monthly_returns.rebalance_date <= "2026-02-27"]
        self.assertEqual(before.to_dict("records"), after.to_dict("records"))
        self.assertNotEqual(first.metrics["ending_equity_usd"], second.metrics["ending_equity_usd"])
        self.assertGreater(len(session.trades), 0)
        self.assertGreater(len(other.trades), 0)
        self.assertGreater(second.monthly_returns.dd_breaker_level.max(), 0)

    def test_monthly_forced_exit_is_not_rebought_or_credited_a_stop_fill(self):
        cfg, frame, prices = c0_fixture()
        baseline, original_session, _, _ = self.main_result(cfg, frame, prices)
        bought = next(row["ticker"] for row in original_session.trades if row["side"] == "BUY")
        prices[bought].loc[prices[bought].index >= "2026-02-27", "close"] = 70.
        prices[bought].loc[prices[bought].index >= "2026-03-02", "close"] = 40.
        result, session, _, _ = self.main_result(cfg, frame, prices)
        decision = result.monthly_returns.loc[result.monthly_returns.rebalance_date.eq(pd.Timestamp("2026-02-27"))].iloc[0]
        self.assertIn(bought, dict(decision.risk_exits))
        self.assertEqual(dict(decision.target_weights).get(bought, 0.), 0.)
        fills = [row for row in session.trades if row["ticker"] == bought and row["date"] == "2026-03-02"]
        self.assertTrue(fills)
        self.assertEqual({row["side"] for row in fills}, {"SELL"})
        self.assertTrue(all(row["fill_price"] == 40. for row in fills))
        self.assertLess(result.metrics["ending_equity_usd"], baseline.metrics["ending_equity_usd"])

    def test_concentrated_reuses_n3_score_power_monthly_and_same_ledger(self):
        cfg, frame, prices = c0_fixture()
        session = ResearchNextCloseSession(prices, evidence_end_date=cfg.end_date)
        with patch.object(pipeline, "select_concentrated_portfolio_topk", wraps=pipeline.select_concentrated_portfolio_topk) as selector, \
             patch.object(pipeline, "month_forward_return_open", side_effect=AssertionError("future outcome")), \
             patch.object(pipeline, "get_paths", side_effect=AssertionError("output I/O")):
            result = pipeline.backtest_concentrated_portfolio(cfg, frame, top_n=3, weighting_mode="score_power",
                                                               rebalance_interval_months=1, research_session=session)
        self.assertEqual(selector.call_count, 4)
        self.assertTrue(all(call.kwargs["top_n"] == 3 for call in selector.call_args_list))
        self.assertGreater(len(session.trades), 0)
        self.assertFalse(result.metrics["valid_for_production"])
        self.assertIsNotNone(result.metrics["pending_intent"])
        self.assertEqual(result.metrics["pending_intent"]["due"], "2026-05-01")
        self.assertEqual(result.metrics["ending_equity_usd"], session.nav_rows[-1]["equity_usd"])
        wrong = ResearchNextCloseSession(prices, evidence_end_date=cfg.end_date)
        with self.assertRaisesRegex(ValueError, "causal_concentrated_registered"):
            pipeline.backtest_concentrated_portfolio(cfg, frame, weighting_mode="conviction_curve", research_session=wrong)

    def test_fixed_c0_cannot_be_renamed_policy_off_or_override(self):
        cfg, frame, prices = c0_fixture()
        changes = (("portfolio_hold_policy_enabled", False),
                   ("sleeve_specific_rebalance_enabled", False),
                   ("portfolio_position_risk_enabled", False),
                   ("drawdown_breaker_multilevel_enabled", False),
                   ("sleeve_regime_apply_champion", False),
                   ("manual_regime_conditioned_sleeve_map", {}),
                   ("regime_conditioned_sleeve_map", {"balanced": {"cash": 1.0}}),
                   ("regime_conditioned_min_learned_months", 0))
        for field, value in changes:
            with self.subTest(field=field):
                cfg = EngineConfig()
                cfg.end_date = "2026-04-30"
                setattr(cfg, field, value)
                session = ResearchNextCloseSession(prices, evidence_end_date=cfg.end_date)
                with self.assertRaisesRegex(ValueError, "causal_c0_policy_override"):
                    pipeline.backtest_portfolio(cfg, frame, research_session=session)
        cfg, frame, prices = c0_fixture()
        canonical = ResearchNextCloseSession(prices, evidence_end_date=cfg.end_date)
        self.assertIs(pipeline._causal_research_session(canonical, cfg), canonical)
        # Nested numeric equality must not bypass the canonical scalar type.
        changed_map = copy.deepcopy(cfg.manual_regime_conditioned_sleeve_map)
        first = next(iter(changed_map.values()))
        first["core"] = np.float64(first["core"])
        cfg.manual_regime_conditioned_sleeve_map = changed_map
        with self.assertRaisesRegex(ValueError, "causal_c0_policy_override:manual_regime_conditioned_sleeve_map"):
            pipeline._causal_research_session(canonical, cfg)
        cfg, frame, prices = c0_fixture()
        for override in ({"rebalance_interval_months_override": 2},
                         {"adaptive_interval_policy_override": False},
                         {"sleeve_override": {"cash": 1.0}}, {"cash_target_max": .5}):
            session = ResearchNextCloseSession(prices, evidence_end_date=cfg.end_date)
            with self.assertRaisesRegex(ValueError, "causal_c0_main_policy_override"):
                pipeline.backtest_portfolio(cfg, frame, research_session=session, **override)

    def test_consumed_policy_fields_are_explicit_and_reject_sizing_variants(self):
        cfg, frame, prices = c0_fixture()
        session = ResearchNextCloseSession(prices, evidence_end_date=cfg.end_date)
        self.assertIs(pipeline._causal_research_session(session, cfg), session)
        variants = (("min_dynamic_port_names", 100), ("partial_scout_total_weight_cap", 0.0),
                    ("weight_score_power", -1.0), ("cash_buffer_enabled", not cfg.cash_buffer_enabled),
                    ("partial_scout_gate_enabled", not cfg.partial_scout_gate_enabled),
                    ("sector_adjusted_gate_enabled", not cfg.sector_adjusted_gate_enabled))
        for field, value in variants:
            with self.subTest(field=field):
                changed = copy.deepcopy(cfg)
                setattr(changed, field, value)
                with self.assertRaisesRegex(ValueError, "^causal_c0_policy_override:" + field + "$"):
                    pipeline._causal_research_session(session, changed)
        changed = copy.deepcopy(cfg)
        changed.min_dynamic_port_names = float(cfg.min_dynamic_port_names)
        with self.assertRaisesRegex(ValueError, "causal_c0_policy_override:min_dynamic_port_names"):
            pipeline._causal_research_session(session, changed)

        # Audit literal reads in the actual consumer graph, including imports
        # inside candidate-gate functions. Parse code, never execute providers.
        modules = {}
        for module in ("r1000_pipeline", "r1000_signals", "r1000_helpers", "r1000_market_leader_engine"):
            tree = ast.parse((ROOT / (module + ".py")).read_bytes())
            definitions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
            imports = {alias.asname or alias.name: (node.module, alias.name)
                       for node in tree.body if isinstance(node, ast.ImportFrom) for alias in node.names}
            modules[module] = definitions, imports
        stack = [("r1000_pipeline", name) for name in
                 ("backtest_portfolio", "backtest_concentrated_portfolio", "_causal_monthly_risk")]
        stack += [("r1000_signals", name) for name in
                  ("build_target_portfolio", "select_concentrated_portfolio_topk", "concentrated_weight_map")]
        excluded = {"get_paths", "month_forward_return_open", "load_benchmark_price_series",
                    "get_hist", "load_fred_series", "fetch_price_history"}
        visited, reads, dynamic = set(), set(), set()
        while stack:
            module, name = stack.pop()
            if (module, name) in visited or name in excluded:
                continue
            definitions, imports = modules.get(module, ({}, {}))
            node = definitions.get(name)
            if node is None:
                continue
            visited.add((module, name))
            imports = dict(imports)
            for child in ast.walk(node):
                if isinstance(child, ast.ImportFrom):
                    imports.update({alias.asname or alias.name: (child.module, alias.name)
                                    for alias in child.names})
            for child in ast.walk(node):
                if (isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name)
                        and child.value.id in {"cfg", "cfg_obj", "config"}):
                    reads.add(child.attr)
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                    if (child.func.id == "getattr" and len(child.args) >= 2
                            and isinstance(child.args[0], ast.Name)
                            and child.args[0].id in {"cfg", "cfg_obj", "config"}):
                        key = child.args[1]
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            reads.add(key.value)
                        else:
                            dynamic.add((name, ast.unparse(key)))
                    target = ((module, child.func.id) if child.func.id in definitions
                              else imports.get(child.func.id))
                    if target and target[0] in modules:
                        stack.append(target)
                    elif target and any(isinstance(arg, ast.Name)
                                        and arg.id in {"cfg", "cfg_obj", "config"}
                                        for arg in list(child.args) + [kw.value for kw in child.keywords]):
                        self.fail("unreviewed_external_policy_consumer:" + ":".join(target))
        self.assertIn(("r1000_pipeline", "add_core_fundamental_minimum_flags"), visited)
        self.assertFalse(reads - pipeline._CAUSAL_C0_POLICY_FIELDS
                         - pipeline._CAUSAL_C0_NONPOLICY_REFERENCES.keys())
        self.assertTrue(dynamic <= {("_causal_research_session", "name")} | {
            ("_causal_monthly_risk", "prefix + " + repr("_position_risk_" + suffix))
            for suffix in ("enabled", "hard_stop", "trailing_stop", "trailing_min_profit", "distribution_threshold")})
        # Dynamic Main/Con risk keys also have explicit canonical bindings.
        for prefix in ("portfolio", "concentrated"):
            for suffix in ("enabled", "hard_stop", "trailing_stop", "trailing_min_profit", "distribution_threshold"):
                self.assertIn(prefix + "_position_risk_" + suffix, pipeline._CAUSAL_C0_POLICY_FIELDS)

    def test_filled_sleeve_controls_trailing_while_observable_risk_updates(self):
        cfg, frame, prices = c0_fixture()
        ticker = "S00"
        prices[ticker].loc[pd.Timestamp("2026-02-03"), "close"] = 150.
        prices[ticker].loc[pd.Timestamp("2026-02-27"), "close"] = 129.
        session = ResearchNextCloseSession({ticker: prices[ticker]}, evidence_end_date=cfg.end_date)
        initial = session.advance("2026-01-30")
        session.queue("2026-01-30", {ticker: 1.0})
        intended = pd.DataFrame([{"ticker": ticker, "portfolio_sleeve_label": "early_scout"}])
        current = frame.iloc[:1].copy()
        current["revision_score"] = .5
        current["portfolio_sleeve_label"] = "core_compounder"
        self.assertFalse(initial.positions)
        self.assertEqual(pipeline._causal_monthly_risk(cfg, current, initial, {}, intended), {})
        self.assertEqual(pipeline._causal_filled_sleeves(initial, (), None, {}), {})
        snapshot = session.advance("2026-02-27")
        self.assertEqual(len(snapshot.positions), 1)
        self.assertEqual(snapshot.positions[0].gross_cost_basis, 100.)
        self.assertEqual(snapshot.positions[0].peak_close, 150.)
        pending = ("2026-01-30", {ticker: "early_scout"})
        allocated = pipeline._causal_filled_sleeves(snapshot, session.trades, pending, {})
        self.assertEqual(allocated[ticker][1], "early_scout")
        for actual, raw, expected in (("early_scout", "core_compounder", {ticker: "sleeve_trailing_stop"}),
                                      ("core_compounder", "early_scout", {})):
            current["portfolio_sleeve_label"] = raw
            previous = pd.DataFrame([{"ticker": ticker, "portfolio_sleeve_label": actual,
                                      "revision_score": -100., "rs_acceleration_score": -100.}])
            with patch.object(pipeline, "_managed_position_risk_exit_signal",
                              wraps=pipeline._managed_position_risk_exit_signal) as observed:
                exits = pipeline._causal_monthly_risk(cfg, current, snapshot, {}, previous)
            self.assertEqual(exits, expected)
            row = observed.call_args.args[0]
            self.assertEqual(row["portfolio_sleeve_label"], actual)
            self.assertEqual(row["revision_score"], .5)
            self.assertEqual(row["rs_acceleration_score"], current.iloc[0].rs_acceleration_score)
        # No actual trade: neither an unfilled intent nor an integer no-op may
        # promote a different target sleeve into this existing holding.
        changed_intent = ("2026-02-27", {ticker: "core_compounder"})
        self.assertEqual(pipeline._causal_filled_sleeves(snapshot, (), changed_intent, allocated), allocated)
        current["risk_penalty"] = 1.
        current["rs_acceleration_score"] = -1.
        current["portfolio_sleeve_label"] = "early_scout"
        core = pd.DataFrame([{"ticker": ticker, "portfolio_sleeve_label": "core_compounder"}])
        self.assertEqual(pipeline._causal_monthly_risk(cfg, current, snapshot, {}, core),
                         {ticker: "distribution_risk_decay"})

    def test_noop_proposed_sleeve_cannot_change_canonical_partial_hold_decision(self):
        cfg, frame, prices = c0_fixture()
        intervals = pipeline.resolve_sleeve_rebalance_interval_map(cfg)
        self.assertEqual(intervals, {"core_compounder": 1, "future_winner": 2, "early_scout": 1})
        due = [name for name, interval in intervals.items() if interval == 1]
        self.assertEqual(set(due), {"core_compounder", "early_scout"})
        for actual, proposed, retained in (("early_scout", "future_winner", False),
                                           ("future_winner", "core_compounder", True)):
            with self.subTest(actual=actual, proposed=proposed):
                ticker = "S00"
                session = ResearchNextCloseSession({ticker: prices[ticker]}, evidence_end_date=cfg.end_date)
                session.advance("2026-01-30")
                session.queue("2026-01-30", {ticker: 1.0})
                first = session.advance("2026-02-27")
                allocated = pipeline._causal_filled_sleeves(
                    first, session.trades, ("2026-01-30", {ticker: actual}), {})
                trades_before = len(session.trades)
                session.queue("2026-02-27", {ticker: 1.0})
                later = session.advance("2026-03-31")
                self.assertTrue(later.positions)
                self.assertEqual(len(session.trades), trades_before, "real integer sizing must be a no-op")
                allocated = pipeline._causal_filled_sleeves(
                    later, session.trades[trades_before:], ("2026-02-27", {ticker: proposed}), allocated)
                current = frame.loc[frame.rebalance_date.eq(frame.rebalance_date.min())].copy()
                current.loc[current.ticker.eq(ticker), "portfolio_sleeve_label"] = proposed
                portfolio, weights, actual_map = pipeline._causal_actual_portfolio(current, later, allocated)
                self.assertEqual(portfolio.portfolio_sleeve_label.tolist(), [actual])
                self.assertEqual(actual_map, {ticker: actual})
                target = current.loc[current.ticker.eq("S01")].copy()
                target["portfolio_sleeve_label"] = "core_compounder"
                _, correct, _ = pipeline.merge_partial_sleeve_rebalance_state(
                    current, weights, actual_map, target, {"S01": 1.0}, due, cfg, interval_map=intervals)
                _, poisoned, _ = pipeline.merge_partial_sleeve_rebalance_state(
                    current, weights, {ticker: proposed}, target, {"S01": 1.0}, due, cfg, interval_map=intervals)
                self.assertIs(ticker in correct, retained)
                self.assertNotEqual(ticker in correct, ticker in poisoned,
                                    "counterfactual proposed metadata must expose the old wrong hold decision")


class MacroPrefixCausalityTests(unittest.TestCase):
    def fixture(self):
        cfg = EngineConfig()
        dates = pd.bdate_range("2016-01-01", "2026-11-06")
        x = np.arange(len(dates), dtype=float)
        prices = {ticker: pd.DataFrame({"Close": 100. + x * .03 + np.sin(x / 31.)}, index=dates)
                  for ticker in pipeline.MACRO_PRICE_TICKERS.values()}
        series = {name: pd.Series(20. + x * .002 + np.sin(x / 23.), index=dates)
                  for name in pipeline.MACRO_FRED_SERIES}
        months = pd.date_range("2016-01-01", "2026-11-01", freq="MS")
        y = np.arange(len(months), dtype=float)
        series["m2"] = pd.Series(100. + y * .3 + y ** 2 * .005 + np.sin(y / 3.), index=months)
        return cfg, prices, series

    def test_single_and_multiple_past_dates_never_use_current_or_cache_fallback(self):
        cfg, prices, _ = self.fixture()
        for dates in (["2021-09-30"], ["2021-09-30", "2021-10-29"]):
            original = pd.DataFrame({"ticker": ["S00"] * len(dates), "rebalance_date": dates})
            with patch.object(pipeline, "build_macro_regime_table", side_effect=AssertionError("CURRENT_FALLBACK")), \
                 patch.object(pipeline, "load_fred_series", side_effect=AssertionError("CURRENT_FRED")), \
                 patch.object(pipeline, "ensure_prices_cached_incremental", side_effect=AssertionError("PROVIDER")):
                with self.assertRaisesRegex(ValueError, "historical_macro_inputs_unbound"):
                    pipeline.merge_macro_regime_features(cfg, {}, original)
                with self.assertRaisesRegex(ValueError, "historical_macro_inputs_unbound"):
                    pipeline.merge_macro_regime_features(cfg, {}, original, macro_price_history=prices)
            self.assertEqual(original.columns.tolist(), ["ticker", "rebalance_date"])
        with patch.object(pipeline, "get_paths", side_effect=AssertionError("IO_BEFORE_BINDING")):
            for build in (pipeline.build_feature_store, pipeline.build_universe_monthly):
                with self.assertRaisesRegex(ValueError, "historical_macro_inputs_unbound"):
                    build(cfg)

    def test_macro_policy_is_part_of_existing_cache_identity_without_config_dump(self):
        cfg = EngineConfig()
        # Replace serialization with a synthetic noncredential mapping; this
        # tests the real fingerprint policy boundary without copying cfg values.
        with patch.object(pipeline, "asdict", return_value={"synthetic_feature_recipe": "same"}):
            current = pipeline.reuse_fingerprint(cfg, "phase1_to_phase3_data")
            with patch.object(pipeline, "MACRO_FEATURE_PREFIX_POLICY", "old-global-normalization"):
                old = pipeline.reuse_fingerprint(cfg, "phase1_to_phase3_data")
        self.assertNotEqual(current, old)

    def test_disabled_macro_keeps_rows_unknown_and_cannot_relabel_fixed_c0(self):
        cfg, prices, _ = self.fixture()
        cfg.use_macro_regime_features = False
        cached = pd.DataFrame({"ticker": ["S00"], "rebalance_date": ["2021-09-30"],
                               **{name: [999.] for name in pipeline.MACRO_REGIME_COLUMNS},
                               "macro_asof_cutoff_utc": [pd.Timestamp("2026-11-06T21:00:00Z")]})
        cached.attrs.update(historical_pit_certified=True, source_admission=True, macro_sources={"stale": "not reused"})
        with patch.object(pipeline, "load_macro_series", side_effect=AssertionError("DISABLED_SOURCE_READ")), \
             patch.object(pipeline, "build_macro_regime_table", side_effect=AssertionError("DISABLED_CURRENT_READ")):
            result = pipeline.merge_macro_regime_features(cfg, {}, cached)
        self.assertEqual(result.ticker.tolist(), cached.ticker.tolist())
        self.assertTrue(result[pipeline.MACRO_REGIME_COLUMNS].isna().all().all())
        self.assertTrue(result.macro_asof_cutoff_utc.isna().all())
        self.assertEqual(result.attrs["macro_scope"], "DISABLED")
        self.assertIs(result.attrs["historical_pit_certified"], False)
        self.assertIs(result.attrs["source_admission"], False)
        self.assertNotIn("macro_sources", result.attrs)
        with patch.object(pipeline, "_require_macro_feature_inputs", side_effect=AssertionError("DISABLED_BINDING")), \
             patch.object(pipeline, "get_paths", side_effect=RuntimeError("LEGACY_ENTRY_REACHED")):
            for build in (pipeline.build_feature_store, pipeline.build_universe_monthly):
                with self.assertRaisesRegex(RuntimeError, "LEGACY_ENTRY_REACHED"):
                    build(cfg)
        session = ResearchNextCloseSession(prices, evidence_end_date="2026-11-06")
        with self.assertRaisesRegex(ValueError, "causal_c0_policy_override:use_macro_regime_features"):
            pipeline._causal_research_session(session, cfg)

    def test_future_extremes_cannot_rewrite_prefix_but_later_features_respond(self):
        cfg, prices, series = self.fixture()
        date, later = pd.Timestamp("2021-09-30"), pd.Timestamp("2026-10-30")
        baseline = pipeline.compute_macro_regime_prefix(cfg, date, prices, series)
        changed = {key: value.copy() for key, value in series.items()}
        future = changed["m2"].index > date
        changed["m2"].loc[future] *= np.linspace(2., 200., int(future.sum()))
        poisoned_prices = {key: value.copy() for key, value in prices.items()}
        for price in poisoned_prices.values():
            price.loc[price.index > date, "Close"] *= 10.
        actual = pipeline.compute_macro_regime_prefix(cfg, date, poisoned_prices, changed)
        pd.testing.assert_frame_equal(baseline, actual)
        old_later = pipeline.compute_macro_regime_prefix(cfg, later, prices, series)
        new_later = pipeline.compute_macro_regime_prefix(cfg, later, poisoned_prices, changed)
        self.assertFalse(old_later[pipeline.MACRO_REGIME_COLUMNS].equals(new_later[pipeline.MACRO_REGIME_COLUMNS]))
        # The old full-window normalization is demonstrably sensitive at this
        # past anchor; only the prefix tail is eligible as the feature value.
        full = pipeline.compute_macro_regime_frame(cfg, prices, series)
        altered = pipeline.compute_macro_regime_frame(cfg, poisoned_prices, changed)
        before = full.loc[full.macro_date.le(date), pipeline.MACRO_REGIME_COLUMNS].tail(1)
        after = altered.loc[altered.macro_date.le(date), pipeline.MACRO_REGIME_COLUMNS].tail(1)
        self.assertFalse(before.equals(after))

    def test_same_cutoff_prefix_tail_keeps_native_math_and_missing_rules(self):
        cfg, prices, series = self.fixture()
        date = pd.Timestamp("2021-09-30")
        p = {key: value.loc[value.index <= date].copy() for key, value in prices.items()}
        s = {key: value.loc[value.index <= date].copy() for key, value in series.items()}
        expected = pipeline.compute_macro_regime_frame(cfg, p, s).iloc[-1]
        result = pipeline.compute_macro_regime_prefix(cfg, date, prices, series).iloc[0]
        np.testing.assert_allclose(result[pipeline.MACRO_REGIME_COLUMNS].to_numpy(dtype=float),
                                   expected[pipeline.MACRO_REGIME_COLUMNS].to_numpy(dtype=float), equal_nan=True)
        self.assertEqual(result.macro_asof_cutoff_utc, pipeline.decision_session_close_utc(pd.Series([date])).iloc[0])
        self.assertEqual(cfg.macro_m2_release_lag_months, 1)
        self.assertEqual(cfg.macro_slow_release_lag_months, 1)
        empty = pipeline.compute_macro_regime_prefix(cfg, date, {}, {})
        self.assertTrue(empty[pipeline.MACRO_REGIME_COLUMNS].isna().all().all())
        self.assertIs(empty.attrs["historical_pit_certified"], False)
        with self.assertRaisesRegex(ValueError, "macro_feature_date_not_nyse_session"):
            pipeline.compute_macro_regime_prefix(cfg, "2021-10-02", prices, series)

    def projected_source(self, series, *, changed=None, revision_at=None, mismatch=False):
        import types
        module = types.ModuleType("tools.long_history_lake")
        class Lake:
            pass
        module.Lake = Lake
        calls = []
        ids = {series_id: name for name, series_id in pipeline.MACRO_FRED_SERIES.items()}
        def project(lake, series_id, decision_at):
            cutoff = pd.Timestamp(decision_at)
            calls.append((series_id, cutoff))
            name = ids[series_id]
            values = changed[name] if changed is not None and cutoff >= revision_at else series[name]
            values = values.loc[values.index <= cutoff.tz_convert("America/New_York").tz_localize(None).normalize()]
            return dict(status="DATE_ARCHIVE_RESEARCH_ONLY", decision_at=cutoff.isoformat(),
                        archive_through="2026-11-06", published_at_precision="DATE_ONLY",
                        historical_pit_certified=False, source_commit=("c" * 64 if mismatch and len(calls) == 2 else "a" * 64),
                        execution_receipt_sha256="b" * 64,
                        records=[dict(observation_date=stamp.date().isoformat(), value=None if pd.isna(value) else float(value))
                                 for stamp, value in values.items()])
        module.project_alfred_asof = project
        return module, Lake(), calls

    def test_each_feature_uses_its_own_projected_vintage_and_only_its_tail(self):
        cfg, prices, series = self.fixture()
        changed = {name: values.copy() for name, values in series.items()}
        changed["m2"] *= np.linspace(1., 50., len(changed["m2"]))
        source, lake, calls = self.projected_source(series, changed=changed,
                                                   revision_at=pd.Timestamp("2021-10-01T00:00:00Z"))
        monthly = pd.DataFrame({"ticker": ["S00", "S01", "S00"],
                                "rebalance_date": ["2021-09-30", "2021-09-30", "2021-10-29"],
                                "liquidity_regime_score": [999., 999., 999.]})
        with patch.dict(sys.modules, {"tools.long_history_lake": source}), \
             patch.object(pipeline, "build_macro_regime_table", side_effect=AssertionError("CURRENT_FALLBACK")):
            result = pipeline.merge_macro_regime_features(cfg, {}, monthly, macro_lake=lake, macro_price_history=prices)
        self.assertEqual(result.ticker.tolist(), monthly.ticker.tolist())
        self.assertEqual(len(calls), 2 * len(pipeline._NATIVE_MACRO_FRED_NAMES))
        earlier = pipeline.compute_macro_regime_prefix(cfg, "2021-09-30", prices, series).iloc[0]
        later = pipeline.compute_macro_regime_prefix(cfg, "2021-10-29", prices, changed).iloc[0]
        for index, expected in ((0, earlier), (1, earlier), (2, later)):
            np.testing.assert_allclose(result.iloc[index][pipeline.MACRO_REGIME_COLUMNS].to_numpy(dtype=float),
                                       expected[pipeline.MACRO_REGIME_COLUMNS].to_numpy(dtype=float), equal_nan=True)
        self.assertEqual(result.attrs["macro_scope"], "DATE_ARCHIVE_RESEARCH_ONLY")
        self.assertIs(result.attrs["historical_pit_certified"], False)
        self.assertIs(result.attrs["source_admission"], False)

    def test_unavailable_api_mixed_generation_and_missing_price_prefix_block(self):
        import types
        cfg, prices, series = self.fixture()
        monthly = pd.DataFrame({"ticker": ["S00"], "rebalance_date": ["2021-09-30"]})
        absent = types.ModuleType("tools.long_history_lake")
        with patch.dict(sys.modules, {"tools.long_history_lake": absent}):
            with self.assertRaisesRegex(ValueError, "historical_macro_source_api_unavailable"):
                pipeline.load_macro_series(object(), pd.Timestamp("2021-09-30T20:00:00Z"))
            with patch.object(pipeline, "get_paths", side_effect=AssertionError("IO_BEFORE_API_BINDING")):
                with self.assertRaisesRegex(ValueError, "historical_macro_source_api_unavailable"):
                    pipeline.build_feature_store(cfg, macro_lake=object(), macro_price_history=prices)
        source, lake, _ = self.projected_source(series, mismatch=True)
        with patch.dict(sys.modules, {"tools.long_history_lake": source}):
            with self.assertRaisesRegex(ValueError, "historical_macro_source_generation_mismatch"):
                pipeline.merge_macro_regime_features(cfg, {}, monthly, macro_lake=lake, macro_price_history=prices)
            with self.assertRaisesRegex(ValueError, "historical_macro_price_prefix_missing"):
                pipeline.merge_macro_regime_features(cfg, {}, monthly, macro_lake=lake, macro_price_history={})

    def test_price_schema_refuses_before_upstream_io_using_existing_prefix_contract(self):
        cfg, _, series = self.fixture()
        source, lake, calls = self.projected_source(series)
        day = pd.DatetimeIndex(["2021-09-30"])
        cases = ((pd.DataFrame({"Close": [100.]}, index=["2021-09-30"]), "macro_observation_index_invalid"),
                 (pd.DataFrame({"Close": [100.]}, index=[0]), "macro_observation_index_invalid"),
                 (pd.DataFrame({"Close": [100.]}, index=pd.DatetimeIndex(["2021-09-30T12:00:00"])), "macro_observation_index_invalid"),
                 (pd.DataFrame({"Close": [100., 100.]}, index=day.repeat(2)), "macro_observation_index_invalid"),
                 (pd.DataFrame({"Close": [100.]}, index=day.tz_localize("UTC")), "macro_observation_index_invalid"),
                 (pd.DataFrame({"Close": [100.]}, index=pd.DatetimeIndex([pd.NaT])), "macro_observation_index_invalid"),
                 (pd.DataFrame({"Open": [100.]}, index=day), "historical_macro_price_columns_missing"),
                 (pd.DataFrame({"Close": [np.nan]}, index=day), "historical_macro_price_values_missing"),
                 (pd.DataFrame({"Adj Close": [np.nan], "Close": [100.]}, index=day), "historical_macro_price_values_missing"))
        with patch.dict(sys.modules, {"tools.long_history_lake": source}), \
             patch.object(pipeline, "get_paths", side_effect=RuntimeError("UPSTREAM_IO_REACHED")) as io:
            for frame, reason in cases:
                invalid = {ticker: frame.copy() for ticker in pipeline.MACRO_PRICE_TICKERS.values()}
                for build in (pipeline.build_feature_store, pipeline.build_universe_monthly):
                    with self.subTest(index_type=type(frame.index).__name__, columns=tuple(frame.columns), build=build.__name__):
                        with self.assertRaisesRegex(ValueError, "^" + reason + "(?::[A-Z]+)?$"):
                            build(cfg, macro_lake=lake, macro_price_history=invalid)
            self.assertEqual(io.call_count, 0)
            self.assertEqual(calls, [])
            # Both real column spellings remain accepted; only the sentinel,
            # rather than any real get_paths/provider work, may run afterwards.
            for column in ("Close", "Adj Close"):
                valid = {ticker: pd.DataFrame({column: [100.]}, index=day)
                         for ticker in pipeline.MACRO_PRICE_TICKERS.values()}
                for build in (pipeline.build_feature_store, pipeline.build_universe_monthly):
                    with self.assertRaisesRegex(RuntimeError, "^UPSTREAM_IO_REACHED$"):
                        build(cfg, macro_lake=lake, macro_price_history=valid)
            self.assertEqual(io.call_count, 4)
            self.assertEqual(calls, [])

    def test_current_report_wrapper_preserves_unprefixed_math_and_io(self):
        cfg, prices, series = self.fixture()
        expected = pipeline.compute_macro_regime_frame(cfg, prices, series)
        by_id = {series_id: series[name] for name, series_id in pipeline.MACRO_FRED_SERIES.items()}
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(pipeline, "ensure_prices_cached_incremental") as ensure, \
             patch.object(pipeline, "load_px", side_effect=lambda paths, ticker: prices[ticker]), \
             patch.object(pipeline, "load_fred_series", side_effect=lambda cfg, paths, name, sid: by_id[sid]) as fred, \
             patch.object(pipeline, "load_cnn_fear_greed_table", return_value=pd.DataFrame()), \
             patch.object(pipeline, "load_macro_series", side_effect=AssertionError("HISTORICAL_API_IN_CURRENT_REPORT")), \
             patch.object(pipeline, "write_stage_coverage_report") as coverage:
            actual = pipeline.build_macro_regime_table(cfg, {"feature_store": Path(temp)})
            saved = pd.read_parquet(Path(temp) / "macro_regime_latest.parquet")
        pd.testing.assert_frame_equal(expected, actual)
        pd.testing.assert_frame_equal(expected, saved)
        self.assertEqual(ensure.call_count, 1)
        self.assertEqual(fred.call_count, len(pipeline.MACRO_FRED_SERIES))
        self.assertEqual(coverage.call_count, 1)

    def test_nonfinite_nonpositive_prices_block_without_dropping_or_replacing_values(self):
        cfg, _, series = self.fixture()
        source, lake, calls = self.projected_source(series)
        invalids = ([np.inf], [-np.inf], [0.], [-1.], [100., np.inf], [100., "invalid"],
                    [True], [1. + 2.j], [pd.Timestamp("2021-09-30")])
        with patch.dict(sys.modules, {"tools.long_history_lake": source}), \
             patch.object(pipeline, "get_paths", side_effect=RuntimeError("UPSTREAM_IO_REACHED")) as io:
            for values in invalids:
                days = pd.bdate_range("2021-09-29", periods=len(values))
                for column in ("Close", "Adj Close"):
                    frame = pd.DataFrame({column: values}, index=days)
                    # Keep the preferred-column rule even when a valid lower
                    # priority Close exists alongside an invalid Adj Close.
                    if column == "Adj Close":
                        frame["Close"] = 100.
                    original = frame.copy(deep=True)
                    prices = {ticker: frame.copy() for ticker in pipeline.MACRO_PRICE_TICKERS.values()}
                    for build in (pipeline.build_feature_store, pipeline.build_universe_monthly):
                        with self.subTest(values_type=str(frame[column].dtype), column=column, build=build.__name__):
                            with self.assertRaisesRegex(ValueError, "^historical_macro_price_values_invalid:[A-Z]+$"):
                                build(cfg, macro_lake=lake, macro_price_history=prices)
                    pd.testing.assert_frame_equal(frame, original)
            self.assertEqual(io.call_count, 0)
            self.assertEqual(calls, [])
            for column in ("Close", "Adj Close"):
                frame = pd.DataFrame({column: [np.nan, 100.]}, index=pd.bdate_range("2021-09-29", periods=2))
                original = frame.copy(deep=True)
                prices = {ticker: frame.copy() for ticker in pipeline.MACRO_PRICE_TICKERS.values()}
                for build in (pipeline.build_feature_store, pipeline.build_universe_monthly):
                    with self.assertRaisesRegex(RuntimeError, "^UPSTREAM_IO_REACHED$"):
                        build(cfg, macro_lake=lake, macro_price_history=prices)
                pd.testing.assert_frame_equal(frame, original)
                self.assertTrue(pd.isna(frame.iloc[0][column]))
            self.assertEqual(io.call_count, 4)
            self.assertEqual(calls, [])

    def test_historical_projection_requires_only_the_thirteen_consumed_fred_series(self):
        cfg, prices, series = self.fixture()
        body = ast.parse(inspect.getsource(pipeline.compute_macro_regime_frame))
        consumed = {node.args[0].value for node in ast.walk(body)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "fred_series"
                    and node.func.attr == "get" and node.args and isinstance(node.args[0], ast.Constant)}
        self.assertEqual(set(pipeline._NATIVE_MACRO_FRED_NAMES), consumed)
        self.assertEqual(len(consumed), 13)
        unused = set(pipeline.MACRO_FRED_SERIES) - consumed
        self.assertEqual(unused, {"dgs3mo", "sp500"})
        bound = {name: values for name, values in series.items() if name in consumed}
        source, lake, calls = self.projected_source(bound)
        original_project = source.project_alfred_asof
        unused_ids = {pipeline.MACRO_FRED_SERIES[name] for name in unused}
        def project(lake, series_id, decision_at):
            if series_id in unused_ids:
                raise ValueError("UNUSED_ARCHIVE_DOES_NOT_EXIST")
            return original_project(lake, series_id, decision_at)
        source.project_alfred_asof = project
        cutoff = pipeline.decision_session_close_utc(pd.Series([pd.Timestamp("2021-09-30")])).iloc[0]
        with patch.dict(sys.modules, {"tools.long_history_lake": source}):
            loaded, context = pipeline.load_macro_series(lake, cutoff)
        self.assertEqual(set(loaded), consumed)
        self.assertEqual(len(calls), 13)
        self.assertEqual({sid for sid, _ in calls}, {pipeline.MACRO_FRED_SERIES[name] for name in consumed})
        self.assertEqual(set(context["archive_through"]), {sid for sid, _ in calls})
        self.assertEqual(context["source_commit"], "a" * 64)
        self.assertEqual(context["execution_receipt_sha256"], "b" * 64)
        self.assertIs(context["historical_pit_certified"], False)
        # Irrelevant malformed series must not become new math prerequisites.
        extras = dict(bound, **{name: pd.Series([1.], index=["unusable-unused-index"]) for name in unused})
        pd.testing.assert_frame_equal(pipeline.compute_macro_regime_prefix(cfg, "2021-09-30", prices, loaded),
                                      pipeline.compute_macro_regime_prefix(cfg, "2021-09-30", prices, extras))

    def test_integrated_source_api_replays_local_original_receipt_and_vintages(self):
        import io
        from contextlib import redirect_stdout
        from tools import long_history_lake as history
        cutoff = pd.Timestamp("2021-09-30T20:00:00Z")
        later = pd.Timestamp("2021-10-29T20:00:00Z")
        # All bytes and receipts below are a disposable synthetic local fixture.
        # The real Lake, verified_execution and public projection stay unmocked.
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            root = Path(temp)
            transport = history.LocalTransport(root / "synthetic-remote")
            writer = history.Lake(transport, root / "writer")
            for name in pipeline._NATIVE_MACRO_FRED_NAMES:
                sid = pipeline.MACRO_FRED_SERIES[name]
                rows = []
                for observed, vintage, value in (("2021-09-01", "2021-09-01", 10.),
                                                  ("2021-09-02", "2021-09-02", None),
                                                  ("2021-09-01", "2021-10-01", 99.)):
                    available = (pd.Timestamp(vintage) + pd.Timedelta(days=1)).tz_localize(
                        "America/New_York").tz_convert("UTC")
                    rows.append(dict(series=sid, observation_date=observed, vintage_date=vintage,
                                     realtime_end="9999-12-31", available_at=available.isoformat(),
                                     published_at=None, evidence="alfred_date_archive", value=value))
                writer.dataset("alfred/" + sid, [history.encoded(rows)], rows,
                               dict(rows=len(rows), evidence="alfred_date_archive",
                                    requested_through="2021-10-29"))
            publication = writer.publish("synthetic-macro-shape", {})
            reader = history.Lake(transport, root / "reader")
            with self.assertRaisesRegex(ValueError, "^historical_macro_projection_blocked:VIXCLS$"):
                pipeline.load_macro_series(reader, cutoff)
            quality = history.encoded(dict(schema="long-history-quality-v1", status="PARTIAL",
                                           eligible_for_selector=False))
            quality_sha = history.digest(quality)
            transport.write(history.PREFIX + "/reports/" + quality_sha, quality)
            receipt = history.encoded(dict(schema="long-history-execution-v1",
                run_id="synthetic-macro-shape", commit_sha256=publication["commit_sha256"],
                catalog_sha256=publication["catalog_sha256"], reports={"quality.json": quality_sha},
                consumer_rows=39, study_recomputed_from_drive=True, quality_status="PARTIAL",
                eligible_for_selector=False))
            receipt_sha = history.digest(receipt)
            transport.write(history.PREFIX + "/executions/" + receipt_sha, receipt)
            self.assertIs(pipeline._macro_source_projection_api(reader), history.project_alfred_asof)
            loaded, context = pipeline.load_macro_series(reader, cutoff)
            newer, later_context = pipeline.load_macro_series(reader, later)
            self.assertEqual(set(loaded), set(pipeline._NATIVE_MACRO_FRED_NAMES))
            self.assertEqual(context["source_commit"], publication["commit_sha256"])
            self.assertEqual(context["execution_receipt_sha256"], receipt_sha)
            self.assertEqual(context, later_context)
            self.assertIs(context["historical_pit_certified"], False)
            self.assertIs(context["source_admission"], False)
            for name in loaded:
                self.assertEqual(loaded[name].loc["2021-09-01"], 10.)
                self.assertTrue(pd.isna(loaded[name].loc["2021-09-02"]))
                self.assertEqual(newer[name].loc["2021-09-01"], 99.)
            original_read = transport.read
            def corrupted_report(path):
                return b"corrupt-original-report" if path.endswith("/reports/" + quality_sha) else original_read(path)
            with patch.object(transport, "read", side_effect=corrupted_report):
                with self.assertRaisesRegex(ValueError, "^historical_macro_projection_blocked:VIXCLS$"):
                    pipeline.load_macro_series(reader, cutoff)
            reader.catalog["datasets"]["alfred/VIXCLS"]["status"] = "STALE_RETAINED"
            with self.assertRaisesRegex(ValueError, "^historical_macro_projection_blocked:VIXCLS$"):
                pipeline.load_macro_series(reader, cutoff)


if __name__ == "__main__":
    unittest.main(verbosity=2)

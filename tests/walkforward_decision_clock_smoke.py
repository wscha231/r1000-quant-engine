#!/usr/bin/env python3
"""Behavioral synthetic tests of the incumbent walk-forward fit/predict path."""
from __future__ import annotations

import copy
import ast
import inspect
from pathlib import Path
import copy
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


if __name__ == "__main__":
    unittest.main(verbosity=2)

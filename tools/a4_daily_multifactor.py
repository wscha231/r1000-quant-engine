"""Standalone daily multifactor experiments; no Source or forecast admission.

As-of macro state is distinct from the incumbent sparse release-event model.
Overlapping outcomes may be fitted, but never counted as independent evidence.
No collector, scheduler, accepted model, A3/A5 or portfolio interface is added.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from tools import a4_liquidity_analysis as analysis
from tools import a4_macro_learning as learning
from tools import free_market_context as free
from tools import macro_technical_study as study
from tools.a4_primary_sources import semantic_register
from tools.a4_primary_macro_sources import registers
from tools import a4_rtdsm_sources as vintage

HORIZONS = (1, 5, 10, 21, 63, 126, 252, 504)
SAFETY = dict(source_admitted=False, training_admitted=False, historical_pit_certified=False,
              eligible_for_selector=False, automatic_promotion_allowed=False,
              qualified_backtest=False, forecast_release_allowed=False,
              accepted_model_changed=False, accepted_portfolio_changed=False,
              a3_executed=False, a5_executed=False, orders_generated=False)
RAW_GROUPS = {
    'FUNDING': ('sofr', 'tgcr', 'iorb', 'effr'),
    'LIQUIDITY': ('fed_assets', 'reserves_week_average', 'tga_week_average', 'rrp_other_week_average'),
    'BANK': ('deposits_all', 'deposits_domestic', 'deposits_large', 'deposits_small',
             'loans_all', 'commercial_industrial_loans', 'cash_assets_all'),
    'RATES': ('yield_2y', 'yield_10y', 'real_yield_10y'),
    'CREDIT': ('hy_oas', 'ig_oas'),
    'FX': ('broad_usd',),
    'ECONOMY': ('payrolls', 'unemployment', 'cpi', 'core_cpi', 'initial_claims',
                'retail_sales_nominal', 'real_disposable_income', 'core_pce'),
}
RAW = {key: group for group, keys in RAW_GROUPS.items() for key in keys}
TREND = tuple([f'distance_sma{n}' for n in (20, 50, 100, 200)] +
              [f'slope_sma{n}_20' for n in (20, 50, 100, 200)] +
              ['above_sma200', 'golden_cross_50_200', 'death_cross_50_200', 'breakout_20', 'breakout_60'] +
              [name for n in (20, 60, 120, 240) for name in (f'momentum_{n}', f'relative_strength_{n}')])
RISK = ('realized_vol_20', 'realized_vol_63', 'drawdown_63', 'drawdown_252', 'vol_ratio_20_63')
CORE = ('momentum_20', 'momentum_60', 'momentum_120', 'momentum_240',
        'distance_sma50', 'distance_sma200', 'realized_vol_20', 'drawdown_252')
ECON = tuple(f'{kind}:{key}' for key in ('payrolls', 'cpi', 'unemployment') for kind in ('level', 'change'))
FUNDING = tuple('funding:'+name for name in analysis.SPREADS)
LIQ_BANK = tuple('change:'+key for key in RAW_GROUPS['LIQUIDITY'] + RAW_GROUPS['BANK']) + FUNDING
RATES_CREDIT = tuple(f'{kind}:{key}' for key in RAW_GROUPS['RATES']+RAW_GROUPS['CREDIT'] for kind in ('level', 'change'))
COHORTS = {
    'TECHNICAL': {'TREND': TREND, 'RISK': RISK, 'ALL_TECHNICAL': TREND+RISK},
    'DATED_ECONOMY': {'PRICE_BASE': CORE, 'ECONOMY_ONLY': ECON, 'PRICE_ECONOMY': CORE+ECON},
    'LIQUIDITY_BANK': {'PRICE_BASE': CORE, 'PRICE_LIQUIDITY_BANK': CORE+LIQ_BANK},
    'RATES_CREDIT': {'PRICE_BASE': CORE, 'PRICE_RATES_CREDIT': CORE+RATES_CREDIT},
    'FULL': {'PRICE_BASE': CORE, 'FULL_MULTIFACTOR': TREND+RISK+ECON+LIQ_BANK+RATES_CREDIT+('level:broad_usd',)},
}


def require(ok, reason):
    if not ok:
        raise ValueError('A4_DAILY_'+reason)


def encoded(value):
    return (json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':'))+'\n').encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def registry():
    """Priorities are research order, not investment weights or proven skill."""
    result = []
    for name in TREND+RISK:
        result.append(dict(id=name, group='PRICE_RISK' if name in RISK else 'PRICE_TREND',
                           priority='P0', inputs=['target_close', 'benchmark_close'] if name.startswith('relative_') else ['target_close'],
                           independent_family='SHARED_PRICE_PATH', native_frequency='session'))
    for key, group in RAW.items():
        for kind in ('level', 'change'):
            result.append(dict(id=kind+':'+key, group=group,
                priority='P1' if group in ('BANK', 'ECONOMY', 'FX') else 'P0', inputs=[key],
                independent_family=group, native_frequency='RETAIN_ORIGINAL',
                transform='NATIVE_LEVEL' if kind == 'level' else '4_WEEK_FRACTION_WEEKLY__1_MONTH_DELTA_MONTHLY__5_OBSERVATION_DELTA_DAILY'))
    for name, inputs in analysis.SPREADS.items():
        result.append(dict(id='funding:'+name, group='FUNDING', priority='P0', inputs=list(inputs),
                           independent_family='FUNDING_SHARED_INPUTS', native_frequency='daily', unit='basis_points'))
    return dict(schema='a4-daily-feature-registry-v1', features=result,
        distinct_macro_inputs=len(RAW), technical_features=len(TREND+RISK),
        derived_feature_count=len(result), priorities_are_investment_weights=False,
        derived_features_are_independent_sources=False, **SAFETY)


def specification():
    return dict(schema='a4-daily-multifactor-spec-v1', registry_sha256=digest(registry()),
        horizons=list(HORIZONS), outcomes=list(learning.OUTCOMES), targets=['SPY', 'QQQ'],
        cohorts={c:{g:list(names) for g,names in groups.items()} for c,groups in COHORTS.items()},
        ridge_alpha=10.0, initial_sessions=756, fold_sessions=252, minimum_training_rows=504,
        entry_delay_sessions=1, hac_lag='HORIZON_PLUS_ENTRY_DELAY',
        evidence_minimum_nonoverlap_windows=20, evidence_minimum_folds=3,
        multiple_testing='BY_ALL_DECLARED_CASES_INCLUDING_FAILED_AND_UNAVAILABLE',
        selection='NO_HYPERPARAMETER_OR_COMBINATION_SELECTION_ON_TEST',
        shared_cohort='UNION_OF_REQUIRED_FEATURES_SAME_TRAIN_TEST_ROWS_WITHIN_EACH_COHORT',
        missing_values='NO_BACKFILL_NO_ZERO_FILL_NO_COMPLETE_CASE_CHANGE_PER_ARM',
        current_forecasts='NOT_RELEASED', **SAFETY)


def price_features(close, benchmark):
    require(isinstance(close, pd.Series) and close.index.equals(benchmark.index), 'PRICE_GRID')
    require(close.index.is_unique and close.index.is_monotonic_increasing, 'PRICE_ORDER')
    for series in (close, benchmark):
        require(not np.isinf(series.to_numpy(float)).any() and (series.dropna() > 0).all(), 'PRICE_VALUE')
    features, _ = study.technical_features(close, benchmark)
    returns = np.log(close).diff()
    for n in (20, 63):
        features[f'realized_vol_{n}'] = returns.rolling(n, min_periods=n).std(ddof=1)*math.sqrt(252)
    for n in (63, 252):
        features[f'drawdown_{n}'] = close/close.rolling(n, min_periods=n).max()-1
    features['vol_ratio_20_63'] = features['realized_vol_20']/features['realized_vol_63'].replace(0, np.nan)
    panel = pd.DataFrame(features).reindex(columns=TREND+RISK)
    # pandas rolling ignores gaps after they leave the window; study price
    # change retains its full endpoints. Do not interpolate missing prices.
    return panel.replace([np.inf, -np.inf], np.nan)


def macro_state(observations, sessions):
    """As-of daily state, not independent repeated release-event observations.

    An archived current history stays invisible before its real available_at.
    New vintage/null/expiry events are retained, never filled from future rows.
    """
    require(type(observations) is list and len(observations) <= 150000, 'MACRO_BUDGET')
    learning.calendar_sessions(sessions, sessions[-1]['close_utc'])
    specs = {'fred:'+sid:spec for sid,spec in analysis.SERIES.items()}
    specs.update({'frb:'+sid:spec for sid,spec in semantic_register().items()})
    specs.update({provider+':'+sid:spec for provider,group in registers().items() for sid,spec in group.items()})
    specs.update({'nyfed:'+sid:analysis.SERIES[sid] for sid in ('SOFR','TGCR','EFFR')})
    specs.update({'rtdsm:'+sid:spec for sid,spec in vintage.register().items()})
    ordered, seen, sources = [], {}, {}
    for row in observations:
        require(type(row) is dict and row.get('logical_id') in RAW, 'MACRO_SERIES')
        key = row['logical_id']
        require(row.get('source_id') in specs and specs[row['source_id']][0] == key, 'MACRO_SOURCE')
        spec=specs[row['source_id']]
        require(row.get('unit') == spec[1] and row.get('frequency') == spec[2], 'MACRO_UNIT_FREQUENCY')
        require(type(row.get('max_age_days')) is int and row['max_age_days'] == spec[6], 'MACRO_AGE')
        require(sources.setdefault(key, row['source_id']) == row['source_id'], 'MACRO_SOURCE_CHANGED')
        available = free.utc(row['available_at'])
        require(free.iso_date(row['observation_date']) <= available.date(), 'OBSERVATION_AFTER_AVAILABILITY')
        require(free.iso_date(row['observation_date']) <= free.utc(row['collected_at']).date(), 'OBSERVATION_AFTER_COLLECTION')
        value = row['value']
        require(value is None or (type(value) in (int, float) and math.isfinite(value)), 'MACRO_VALUE')
        require(type(row.get('original_sha256')) is str and len(row['original_sha256']) == 64
                and all(ch in '0123456789abcdef' for ch in row['original_sha256']), 'MACRO_ORIGINAL')
        identity = (key, row['observation_date'], available)
        require(identity not in seen or seen[identity] == row, 'CONFLICTING_VINTAGE')
        if identity not in seen:
            ordered.append(row)
            seen[identity] = row
    ordered.sort(key=lambda r:(free.utc(r['available_at']),r['logical_id'],r['observation_date']))
    names = [f'{kind}:{key}' for key in RAW for kind in ('level', 'change')] + list(FUNDING)
    panel = pd.DataFrame(np.nan, index=pd.DatetimeIndex([s['session'] for s in sessions]), columns=names)
    histories, cursor = defaultdict(dict), 0
    for session in sessions:
        cutoff = free.utc(session['close_utc'])
        while cursor < len(ordered) and free.utc(ordered[cursor]['available_at']) <= cutoff:
            row = ordered[cursor]
            histories[row['logical_id']][row['observation_date']] = row
            cursor += 1
        current = {}
        for key, history in histories.items():
            rows = [history[day] for day in sorted(history)]
            point = analysis.summarize(rows, session['close_utc'])
            current[key] = point
            panel.loc[session['session'], 'level:'+key] = point['value']
            period = '4' if point['frequency'] == 'weekly' else '1' if point['frequency'] == 'monthly' else '5'
            change = point['changes'][period]
            panel.loc[session['session'], 'change:'+key] = change['fraction'] if point['frequency'] == 'weekly' else change['value']
        for name, (left, right) in analysis.SPREADS.items():
            a, b = current.get(left), current.get(right)
            if (a and b and a['status'] == b['status'] == 'OBSERVED'
                    and a['observation_date'] == b['observation_date']):
                panel.loc[session['session'], 'funding:'+name] = (a['value']-b['value'])*100
    return panel


def panel_digest(panel):
    values = panel.to_numpy(float)
    require(not np.isinf(values).any(), 'PANEL_INFINITE')
    return digest(dict(columns=list(panel.columns), dates=[d.date().isoformat() for d in panel.index],
        values=[[float(v) if math.isfinite(v) else None for v in row] for row in values]))


def ridge_predictions(x_train, y_train, x_test, alpha=10.0):
    """Fixed penalty, training-only scale and constant-column removal."""
    require(alpha > 0 and np.isfinite(x_train).all() and np.isfinite(y_train).all()
            and np.isfinite(x_test).all(), 'RIDGE_INPUT')
    mean, sd = np.mean(x_train, axis=0), np.std(x_train, axis=0)
    active = sd > 1e-12
    baseline = float(np.mean(y_train))
    if not active.any():
        return np.full(len(x_test), baseline), dict(active_features=0)
    train = (x_train[:,active]-mean[active])/sd[active]
    test = (x_test[:,active]-mean[active])/sd[active]
    beta = np.linalg.solve(train.T@train + alpha*np.eye(int(active.sum())), train.T@(y_train-baseline))
    require(np.isfinite(beta).all(), 'RIDGE_NONFINITE')
    return baseline + test@beta, dict(active_features=int(active.sum()),
        parameter_sha256=digest(dict(mean=mean[active].tolist(),sd=sd[active].tolist(),beta=beta.tolist(),intercept=baseline)))


def hac_improvement(actual, model, baseline, horizon):
    """Exploratory mean-loss uncertainty on the ORIGINAL session grid.

    Bartlett HAC is not a finite-sample guarantee for long horizons. Retain
    nonoverlap counts and prohibit economic/admission claims independently.
    """
    valid = np.isfinite(actual) & np.isfinite(model) & np.isfinite(baseline)
    n = int(valid.sum())
    if n < 3:
        return dict(p_value=None, improvement_ci95=None)
    differences = (actual[valid]-baseline[valid])**2-(actual[valid]-model[valid])**2
    mean = float(differences.mean())
    scores = np.zeros(len(actual))
    scores[valid] = differences-mean
    variance = float(scores@scores/n)
    lag = min(horizon+1,len(scores)-1)
    for k in range(1,lag+1):
        variance += 2*(1-k/(lag+1))*float(scores[k:]@scores[:-k]/n)
    se = math.sqrt(max(variance,0)/n)
    return dict(p_value=float(2*norm.sf(abs(mean/se))) if se > 1e-15 else None,
                improvement_ci95=[mean-1.96*se, mean+1.96*se], hac_lag_sessions=lag)


def evaluate(panel, close, cohort, arm, *, horizon, outcome, shared_columns,
             initial=756, fold_size=252, min_train=504, target_labels=None):
    require(panel.index.equals(close.index) and horizon in HORIZONS and outcome in learning.OUTCOMES, 'EVALUATION_SCOPE')
    require(arm in COHORTS[cohort] and initial >= 2 and fold_size >= 1 and min_train >= 2, 'EVALUATION_CONFIG')
    names = list(COHORTS[cohort][arm])
    matrix = panel.reindex(columns=names).to_numpy(float)
    complete = np.isfinite(panel.reindex(columns=shared_columns).to_numpy(float)).all(axis=1)
    labels = (learning.outcome_labels(close, horizon)[outcome].to_numpy(float)
              if target_labels is None else np.asarray(target_labels, dtype=float))
    require(labels.shape == (len(panel),) and not np.isinf(labels).any(), 'LABEL_ARRAY')
    positions = np.arange(len(panel))
    model, baseline = np.full(len(panel),np.nan), np.full(len(panel),np.nan)
    folds = []
    for start in range(initial,len(panel),fold_size):
        train = complete & np.isfinite(labels) & (positions+horizon+1 < start)
        test = complete & np.isfinite(labels) & (positions >= start) & (positions < start+fold_size)
        if int(train.sum()) < min_train or not test.any():
            continue
        forecast, pin = ridge_predictions(matrix[train],labels[train],matrix[test])
        model[test], baseline[test] = forecast, float(np.mean(labels[train]))
        folds.append(dict(first_test_position=start,last_training_label_position=int(positions[train][-1]+horizon+1),
            training_rows=int(train.sum()), test_rows=int(test.sum()), **pin))
    valid = np.isfinite(model)
    n = int(valid.sum())
    independent = study.independent_windows(np.flatnonzero(valid),horizon)
    result = dict(cohort=cohort,arm=arm,features=names,horizon_sessions=horizon,outcome=outcome,
        oos_rows=n, nonoverlap_oos_windows=independent, folds=folds,
        shared_cohort_sha256=digest(dict(columns=shared_columns,eligible_positions=positions[complete].tolist())),
        fitting_blockers=[] if n else ['NO_MATURE_COMPLETE_TRAIN_TEST_ROWS'],
        evidence_status='EXPLORATORY_EVALUATED' if n else 'INSUFFICIENT_INPUTS_OR_HISTORY',
        p_value=None, family_q_value=None, **SAFETY)
    if n:
        model_mse=float(np.mean((labels[valid]-model[valid])**2))
        base_mse=float(np.mean((labels[valid]-baseline[valid])**2))
        result.update(model_rmse_pp=math.sqrt(model_mse)*100,baseline_rmse_pp=math.sqrt(base_mse)*100,
            oos_mse_improvement=base_mse-model_mse,
            direction_accuracy=float(np.mean(np.sign(model[valid]) == np.sign(labels[valid]))) if outcome == 'return' else None,
            baseline_direction_accuracy=float(np.mean(np.sign(baseline[valid]) == np.sign(labels[valid]))) if outcome == 'return' else None,
            oos_start=panel.index[valid][0].date().isoformat(),oos_end=panel.index[valid][-1].date().isoformat(),
            **hac_improvement(labels,model,baseline,horizon))
        if independent < 20 or len(folds) < 3:
            result.update(evidence_status='INSUFFICIENT_INDEPENDENT_EVIDENCE',p_value=None)
    return result


def adjust_family(rows):
    """All declared cases enter BY, including unavailable cases as p=1."""
    m = len(rows)
    harmonic, running = sum(1/i for i in range(1,m+1)), 1.0
    values = [r['p_value'] if r.get('p_value') is not None else 1.0 for r in rows]
    for rank,index in reversed(list(enumerate(np.argsort(values),start=1))):
        running = min(running,values[index]*m*harmonic/rank)
        if rows[index].get('p_value') is not None:
            rows[index]['family_q_value'] = float(running)


def compare(panels, prices, *, expected_spec_sha256, horizons=HORIZONS):
    require(digest(specification()) == expected_spec_sha256,'SPECIFICATION_PIN')
    require(set(panels) == set(prices) and set(prices) <= {'SPY','QQQ'} and prices, 'TARGETS')
    require(tuple(horizons) == HORIZONS, 'DECLARED_HORIZONS')
    rows = []
    for target in sorted(prices):
        panel, close = panels[target],prices[target]
        require(panel.index.equals(close.index) and 2 <= len(panel) <= 10000
                and len(panel.columns) <= 128 and panel.columns.is_unique, 'PANEL_BUDGET')
        labels = {h: learning.outcome_labels(close,h) for h in horizons}
        for cohort,arms in COHORTS.items():
            shared = sorted({name for names in arms.values() for name in names})
            for horizon in horizons:
                for outcome in learning.OUTCOMES:
                    for arm in arms:
                        row=evaluate(panel,close,cohort,arm,horizon=horizon,outcome=outcome,shared_columns=shared,
                                     target_labels=labels[horizon][outcome].to_numpy(float))
                        row['target']=target
                        rows.append(row)
    adjust_family(rows)
    return dict(schema='a4-daily-multifactor-result-v1',status='EXPLORATORY_ONLY',
        specification_sha256=expected_spec_sha256,implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        panel_sha256={key:panel_digest(value) for key,value in panels.items()},
        tested_targets=sorted(prices), tests_declared=len(rows),
        fits=sum(len(row['folds']) for row in rows),
        macro_state_sampling='DAILY_ASOF_STATE_NOT_NEW_INDEPENDENT_RELEASES',
        finite_sample_uncertainty='HAC_EXPLORATORY_NOT_BLIND_OR_PIT_CERTIFICATION',
        current_forecasts_released=0,results=rows,**SAFETY)

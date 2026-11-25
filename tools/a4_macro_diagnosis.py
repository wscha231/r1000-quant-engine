"""Explain observed macro conditions without inventing a return forecast.

Signs describe financing pressure or economic quantities, not calibrated
equity effects. Families are never counted as independent risk votes.
"""
from __future__ import annotations

import math
import pandas as pd
from tools import free_market_context as f
from tools import a4_liquidity_analysis as analysis

WINDOWS = {
    'SHORT': dict(daily=5, weekly=1, monthly=1),
    'MEDIUM': dict(daily=21, weekly=4, monthly=3),
    'LONG': dict(daily=21, weekly=13, monthly=12),
}
PROVENANCE = ('source_id', 'observation_date', 'available_at', 'collected_at',
              'published_at', 'original_sha256', 'normalized_sha256',
              'measurement_basis', 'seasonal_basis', 'bank_aggregation', 'publication_freshness')


def observed(row, cutoff):
    if not isinstance(row, dict) or row.get('status') != 'OBSERVED': return False
    value = row.get('value')
    return (type(value) in (float, int) and math.isfinite(value)
        and analysis.current_observation(row, cutoff))


def measurement(panel, key, period, orientation, cutoff):
    row = panel.get(key)
    item = dict(series=key, status='INSUFFICIENT_EVIDENCE', condition=None,
        value=None, change=None, change_unit=None, window=period,
        blocker='FRESH_ORIGINAL_AND_COMPLETE_CHANGE_WINDOW_REQUIRED', evidence=[])
    if not observed(row, cutoff): return item
    item['evidence'] = [{k: row[k] for k in PROVENANCE if k in row}]
    item['value'] = row['value']
    delta = row.get('changes', {}).get(str(period), {})
    value = delta.get('value')
    if type(value) not in (int, float) or not math.isfinite(value): return item
    # Rates in percent become bp; balance quantities keep their source units.
    scale = 100 if row['unit'] == 'percent' else 1
    if not math.isfinite(value*scale): return item
    item.update(status='OBSERVED', change=value*scale,
        change_unit='basis_points' if scale == 100 else row['unit'],
        window_unit='weeks' if row['frequency'] == 'weekly' else 'months' if row['frequency'] == 'monthly' else 'source_observations',
        previous_observation_date=delta.get('previous_observation_date'), blocker=None,
        condition='UNCHANGED' if value == 0 else 'TIGHTENING' if value*orientation > 0 else 'EASING')
    return item


def group(name, measures, *, caveat):
    pressures = {m['condition'] for m in measures if m['status'] == 'OBSERVED'}-{'UNCHANGED'}
    missing = [m['series'] for m in measures if m['status'] != 'OBSERVED']
    state = ('MIXED' if len(pressures)>1 else next(iter(pressures))
        if pressures else 'UNCHANGED' if not missing else 'INSUFFICIENT_EVIDENCE')
    return dict(family=name, status='PARTIAL' if missing else 'OBSERVED',
        observed_condition=state, measures=measures, missing=missing, caveat=caveat,
        independent_risk_vote=False, causal_equity_effect_established=False)


def qe_assessment(report):
    """Observed policy drivers are not a model of a future QE announcement."""
    panel={**report.get('liquidity',{}).get('series',{}),
           **report.get('funding',{}).get('series',{}),**report.get('macro_direction_inputs',{})}
    drivers=[measurement(panel,key,period,orientation,report['cutoff']) for key,period,orientation in (
        ('fed_assets',4,-1),('reserves_week_average',4,-1),('tga_week_average',4,1),
        ('iorb',5,1),('unemployment',1,1),('core_cpi',1,1))]
    for driver in drivers:
        driver.pop('condition',None)
        driver['value_unit']=panel.get(driver['series'],{}).get('unit') if driver['value'] is not None else None
        delta=driver['change']
        driver['observed_change_direction']=('UNKNOWN' if delta is None else
            'INCREASE' if delta>0 else 'DECREASE' if delta<0 else 'UNCHANGED')
    return dict(schema='a4-qe-research-context-v1',status='INSUFFICIENT_EVIDENCE',
        policy_state='OFFICIAL_POLICY_NOT_VERIFIED',qe_start_probability=None,
        horizons_sessions=[r['horizon_sessions'] for r in report.get('horizon_outlook',[])],
        observed_drivers=drivers,driver_signs_are_qe_probabilities=False,
        confirmed_qe_from_balance_growth=False,qe_event_history_verified=False,
        independent_sample_unit='POLICY_EPISODE_NOT_DAILY_OR_WEEKLY_REPEAT',
        alternative_explanations=['TGA_REDISTRIBUTION','RESERVE_MANAGEMENT_PURCHASES',
                                  'REPO_OR_EMERGENCY_LENDING','QT_SLOWDOWN_OR_END','REINVESTMENT'],
        required_evidence=['Dated official FOMC announcement and implementation directive with actual availability',
            'Asset-purchase purpose, instrument, net-purchase versus reinvestment and program scope',
            'Reviewed QE episode labels, rights/PIT inputs and independent out-of-sample event calibration'],
        definition_references=[
            'https://www.federalreserve.gov/newsevents/pressreleases/monetary20191011a.htm',
            'https://www.federalreserve.gov/newsevents/pressreleases/monetary20200315a.htm'],
        reference_pages_are_training_originals=False,model_fit_performed=False,
        equity_direction_inferred=False,portfolio_effect_allowed=False)


def funding(report, period):
    measures=[]
    for key, row in sorted(report.get('funding', {}).get('spreads', {}).items()):
        delta=row.get('changes_bp', {}).get(str(period))
        valid=(row['status']=='OBSERVED' and type(delta) in (int, float) and math.isfinite(delta)
            and 0 <= (f.utc(report['cutoff']).date()-f.iso_date(row['observation_date'])).days <= 5)
        measures.append(dict(series=key, status='OBSERVED' if valid else 'INSUFFICIENT_EVIDENCE',
            value=row['value'], unit='basis_points', change=delta if valid else None,
            change_unit='basis_points', window=period, window_unit='source_observations',
            condition=('UNCHANGED' if delta==0 else 'TIGHTENING' if delta>0 else 'EASING') if valid else None,
            positive_observation_streak=row.get('positive_observation_streak'),
            evidence=[dict(original_sha256=sha,observation_date=row['observation_date']) for sha in row['original_sha256']],
            blocker=None if valid else 'COMPLETE_SAME_DATE_FUNDING_WINDOW_REQUIRED'))
    if not measures:
        measures=[dict(series='funding_spreads',status='INSUFFICIENT_EVIDENCE',condition=None)]
    return group('funding', measures, caveat='Spread changes share rates; a positive spread alone is not a crisis threshold.')


def condition_windows(report):
    cutoff=report['cutoff']
    panel={**report.get('liquidity',{}).get('series',{}),
        **report.get('bank_credit',{}).get('series',{}),**report.get('macro_direction_inputs',{})}
    out={}
    for name,window in WINDOWS.items():
        def take(key, orientation, vocabulary=None):
            row=panel.get(key)
            period=window.get(row.get('frequency'),window['weekly']) if row else window['weekly']
            result=measurement(panel,key,period,orientation,cutoff)
            if vocabulary and result['condition'] in vocabulary:
                result['condition']=vocabulary[result['condition']]
            return result
        quantities={'EASING':'EXPANDING','TIGHTENING':'CONTRACTING'}
        labor={'EASING':'STRENGTHENING','TIGHTENING':'WEAKENING'}
        families=[funding(report,window['daily']),
            group('liquidity',[take('reserves_week_average',-1),take('tga_week_average',1)],
                caveat='Separate weekly average balances; no net-liquidity sum, fixed reserve cutoff or identified asset transfer.'),
            group('bank_credit',[take(key,-1,quantities) for key in
                ('deposits_all','loans_all','commercial_industrial_loans','cash_assets_all')],
                caveat='Balance quantities only, including contrary cash-asset changes; neither funding/credit easing, asset transfers nor credit quality is inferred.'),
            group('labor',[take('payrolls',-1,labor),take('unemployment',1,labor)],
                caveat='Employment quantities describe growth resilience; policy and equity effects can differ.'),
            group('rates',[take('yield_10y',1),take('real_yield_10y',1)],
                caveat='Rising yields indicate higher discount-rate pressure; nominal and real yields overlap.'),
            group('dollar',[take('broad_usd',1,{'TIGHTENING':'APPRECIATING','EASING':'DEPRECIATING'})],
                caveat='Broad-dollar direction only; no universal financing or equity-return effect.')]
        # Family descriptions are deliberately not averaged or tallied into
        # an equity direction, native risk score or confidence probability.
        out[name]=dict(lookback=window,families=families,
            missing_families=[r['family'] for r in families if r['status']!='OBSERVED'],
            interpretation='OBSERVED_CONDITIONS_NOT_HORIZON_RETURN_FORECAST')
    return out


def diagnose(report):
    windows=condition_windows(report)
    panel=report.get('macro_direction_inputs',{})
    inflation=[]
    for key in ('cpi','core_cpi'):
        row=panel.get(key)
        if not observed(row, report['cutoff']): continue
        inflation.append(dict(series=key,observation_date=row['observation_date'],
            monthly_fraction=row['changes'].get('1',{}).get('fraction'),
            quarterly_fraction=row['changes'].get('3',{}).get('fraction'),
            annual_fraction=row['changes'].get('12',{}).get('fraction'),
            evidence={k:row[k] for k in PROVENANCE if k in row},
            interpretation='PRICE_CHANGE_NOT_EQUITY_RETURN_SIGNAL'))
    native=report['market_assessment']
    financing=report.get('financing_conditions',{})
    blockers=[]
    if native['status']!='READY_RESEARCH_ONLY':
        blockers.append(dict(code='NATIVE_TEN_AXIS_INPUTS_REQUIRED',owner='Source/native macro input producer',
            required='Pinned current risk_metrics and risk_calendar; unchanged minimum-eight and required-axis contract',
            native_blockers=native.get('blockers',[])))
    if report.get('learning_provenance',{}).get('status')!='EXTERNALLY_REVIEWED_FIXED_RELEASE':
        blockers.append(dict(code='QUALIFIED_LEARNING_AND_FIXED_RELEASE_REQUIRED',owner='A4 research input review',
            required='Rights/source-bound14 ETF prices, actual historical availability, reviewed policy and independently verified mature trials'))
    report['macro_diagnosis']=dict(schema='a4-macro-condition-diagnosis-v1',
        status='OBSERVED_CONTEXT_ONLY' if any(any(r['status']=='OBSERVED' for r in w['families']) for w in windows.values()) else 'DATA_BLOCKED',
        cutoff=report['cutoff'],session=report['session'],windows=windows,inflation=inflation,
        missing_consumption=not any(observed(panel.get(k),report['cutoff']) for k in ('retail_sales_nominal','real_disposable_income')),
        bank_lending_survey_status=financing.get('lending_standards',{}).get('status','DATA_BLOCKED'),
        native_risk_status=native['status'],native_ready_axes=native['ready_axis_count'],
        completion_blockers=blockers,diagnosis_only=True,
        return_forecast_calibrated=False,portfolio_effect_allowed=False,
        causal_effect_identified=False,independent_risk_votes=0)
    report['qe_assessment']=qe_assessment(report)
    for horizon in report.get('horizon_outlook',[]):
        window='SHORT' if horizon['horizon_sessions']<=10 else 'MEDIUM' if horizon['horizon_sessions']<=63 else 'LONG'
        horizon['current_conditions_window']=window
        horizon['current_conditions_reference']='macro_diagnosis.windows.'+window
        horizon['current_conditions_are_return_forecast']=False
    return report


def recession_watch(report, *, primary_rows, cape=None, sessions):
    """Explain observable recession and market-risk inputs by family."""
    from tools.a4_regime_features import yield_curve

    cutoff = report['cutoff']
    context = report['existing_market_context']
    panel = report['macro_direction_inputs']
    histories = analysis.visible_histories(primary_rows, cutoff)
    if 'yield_3m' in histories:
        panel = {**panel, 'yield_3m': analysis.summarize(histories['yield_3m'], cutoff)}

    def point(key, provider_panel=panel):
        row = provider_panel.get(key, {})
        if row.get('status') != 'OBSERVED':
            return None
        return {k: row[k] for k in (*PROVENANCE, 'value', 'unit', 'changes',
                  'change_from_previous_observation', 'source_sha256') if k in row}

    def component(value, blocker):
        return dict(status='OBSERVED' if value is not None else 'DATA_BLOCKED',
                    evidence=value, blocker=None if value is not None else blocker)

    def family(**parts):
        count = sum(x['status'] == 'OBSERVED' for x in parts.values())
        status = 'OBSERVED' if count == len(parts) else 'PARTIAL' if count else 'DATA_BLOCKED'
        return dict(status=status, components=parts)

    # Require both point estimates on the latest NYSE grid row; leave gaps in
    # the tails rather than treating an older common observation as current.
    curve = {}
    tenors = ('yield_10y','yield_2y','yield_3m')
    grid = list(sessions[-64:])
    frame = pd.DataFrame({key: {r['observation_date']: r['value'] for r in histories.get(key, [])}
                          for key in tenors}, index=grid, dtype=float)
    frame.index = pd.DatetimeIndex(frame.index)
    if len(frame):
        calculated = yield_curve(frame).iloc[-1]
        for short in ('2y','3m'):
            prefix = 'curve_10y_'+short
            long_point, short_point = point('yield_10y'), point('yield_'+short)
            if (long_point and short_point and long_point['observation_date'] == short_point['observation_date']
                    == grid[-1] and math.isfinite(calculated[prefix+'_bp'])):
                prior = frame.iloc[-2] if len(frame) >= 2 else None
                metrics = {k.removeprefix(prefix+'_'): float(v) if pd.notna(v) else None
                           for k,v in calculated.items() if k.startswith(prefix+'_')}
                metrics['complete_lookback_21'] = len(frame)>=22 and bool(frame[['yield_10y','yield_'+short]].iloc[-22:].notna().all().all())
                metrics['complete_lookback_63'] = len(frame)>=64 and bool(frame[['yield_10y','yield_'+short]].iloc[-64:].notna().all().all())
                for lookback in (21,63):
                    if not metrics[f'complete_lookback_{lookback}']:
                        for key in ('change', 'short_fall', 'long_rise'):
                            metrics[f'{key}_{lookback}_bp'] = None
                if prior is None or pd.isna(prior['yield_10y']) or pd.isna(prior['yield_'+short]):
                    metrics['re_cross'] = None
                # The bounded frame does not establish how long an inversion
                # lasted before the start of this context.
                metrics.pop('inverted_sessions')
                metrics.pop('sessions_since_re_cross')
                curve[short] = dict(metrics=metrics, sources=[long_point, short_point])

    labor = point('unemployment')
    sahm = None
    missing_months = []
    if labor and labor['source_id']=='bls:UNRATE':
        dates = pd.period_range(end=labor['observation_date'],periods=15,freq='M')
        rows = {pd.Period(r['observation_date'],freq='M'): r for r in histories.get('unemployment', [])}
        missing_months = [str(d) for d in dates if d not in rows or rows[d]['value'] is None]
        if not missing_months:
            values = pd.Series([rows[d]['value'] for d in dates],index=dates)
            average = values.rolling(3).mean().dropna()
            gap = round(float(average.iloc[-1]-average.iloc[-13:-1].min()), 10)
            origins = {rows[d]['original_sha256']: rows[d] for d in dates}
            sahm = dict(value=gap, unit='percentage_points', threshold=0.50,
                reaches_threshold=gap>=0.50, observation_month=str(dates[-1]),
                basis='BLS_CURRENT_VINTAGE_SAHM_PROXY',
                sources=[{k:r[k] for k in PROVENANCE if k in r} for r in origins.values()],
                historical_pit_certified=False)

    native_axes = {r['axis']:r for r in report['market_assessment'].get('axes', []) if r.get('axis_ready')}
    current_native = report['market_assessment']['status']=='READY_RESEARCH_ONLY'
    broad = [{key: r[key] for key in ('cohort', 'session', 'source_sha256', 'available_at',
                                     'advancers', 'decliners', 'unchanged', 'missing_return_count')}
             for r in context.get('price',[]) if r['context_status']=='OBSERVED'
             and r['advancers']+r['decliners']+r['unchanged'] > 0] if not current_native else []
    spreads = {key:item for key,item in report['funding']['spreads'].items() if item['status']=='OBSERVED'}
    lending = report['financing_conditions']['lending_standards']
    survey = (dict(survey_period=lending['survey_period'], evidence_path='financing_conditions.lending_standards',
                   basis='SLOOS_BANK_CREDIT_SUPPLY')
              if lending['status']=='OBSERVED' else None)
    sahm_component = component(sahm,'FIFTEEN_CONTIGUOUS_BLS_MONTHS_REQUIRED')
    sahm_component['missing_months'] = missing_months
    return dict(schema='a4-recession-watch-v1', cutoff=cutoff, session=report['session'],
        interpretation='OBSERVED_RECESSION_AND_EQUITY_RISK_CONTEXT',
        recession_probability=None, historical_training_admitted=False,
        native_risk_status=report['market_assessment']['status'], independent_votes=None,
        groups=dict(
            yield_curve=family(ten_year_two_year=component(curve.get('2y'),'CURRENT_MATCHED_TREASURY_10Y_2Y_REQUIRED'),
                ten_year_three_month=component(curve.get('3m'),'CURRENT_MATCHED_TREASURY_10Y_3M_REQUIRED')),
            market_internals=family(
                breadth=component(native_axes.get('market_breadth') or broad or None,'CURRENT_BREADTH_REQUIRED'),
                trend=component(native_axes.get('trend_drawdown'),'CURRENT_SPY_TREND_REQUIRED'),
                ad_divergence=component(None,'COMPLETE_DATED_BREADTH_POPULATION_REQUIRED')),
            credit=family(hy_oas=component(point('hy_oas'),'CURRENT_HY_OAS_REQUIRED'),
                ig_oas=component(point('ig_oas'),'CURRENT_IG_OAS_REQUIRED'),
                ccc_hy_gap=component(None,'CCC_SOURCE_RIGHTS_AND_CLOCK_REQUIRED'),
                lending_standards=component(survey,'CURRENT_SLOOS_SOURCE_REQUIRED')),
            policy_cycle=family(administered_rate=component(point('iorb',report['funding']['series']),'CURRENT_IORB_REQUIRED'),
                funding_pressure=component(spreads or None,'MATCHED_FUNDING_SPREADS_REQUIRED'),
                fomc_cycle=component(None,'VERIFIED_FOMC_ANNOUNCEMENT_SEQUENCE_REQUIRED')),
            valuation_earnings=family(cape=component(cape if cape and cape['status']=='OBSERVED' else None,
                'SHILLER_ORIGINAL_REQUIRED' if cape is None else 'SHILLER_'+cape['status']),
                earnings_revisions=component(None,'DATED_EARNINGS_ESTIMATE_RIGHTS_AND_VINTAGES_REQUIRED')),
            leading_labor=family(unemployment=component(labor,'CURRENT_UNEMPLOYMENT_REQUIRED'),
                payrolls=component(point('payrolls'),'CURRENT_PAYROLLS_REQUIRED'),
                initial_claims=component(point('initial_claims'),'CURRENT_INITIAL_CLAIMS_REQUIRED'),
                sahm_proxy=sahm_component,
                official_sahm=component(None,'OFFICIAL_REALTIME_SAHM_SOURCE_REQUIRED'),
                lei=component(None,'DATED_LEI_DEPTH_DIFFUSION_AND_RIGHTS_REQUIRED')),
            sector_rotation=family(rotation=component(None,'MATCHED_21_63_SESSION_SECTOR_ETF_HISTORY_REQUIRED')),
        ),
        supplemental=dict(
            vix=component(point('vix_30d',context.get('macro',{})) or native_axes.get('volatility'),
                          'CURRENT_VIX_SOURCE_REQUIRED'),
            cnn_fear_greed=component(None,'CNN_HISTORY_RIGHTS_AND_CLOCK_REQUIRED')))


def native_review_timing(daily, sentiment, states):
    """Expose the incumbent transition and recovery guards for the latest close."""
    latest = daily.iloc[-1]
    previous = daily.iloc[-2] if len(daily) > 1 else None
    effective = latest['effective_state']
    previous_state = previous['effective_state'] if previous is not None else None
    comparable = (previous is not None and bool(previous['state_change_allowed'])
                  and int(previous['nyse_session_ordinal']) + 1 == int(latest['nyse_session_ordinal'])
                  and previous_state in states and effective in states)
    order = {name: i for i, name in enumerate(states)}
    worse = comparable and order[latest['observed_state']] > order[effective]
    change = order[effective] - order[previous_state] if comparable else 0
    return dict(
        comparable=comparable, previous_state=previous_state if comparable else None,
        decision_at=latest['decision_time_utc'].isoformat(),
        axis_source_bundle_sha256=latest['state_source_hash_bundle_sha256'],
        first_pending_escalation=worse and int(latest['entry_confirmation_count']) == 1,
        confirmed_escalation=change > 0, confirmed_easing=change < 0,
        recovery_stage_advanced=bool(sentiment['fear_recovery_stage_changed']),
        recovery_guards_ready=bool(sentiment['fear_recovery_pause_guards_ready']),
        recovery_paused=bool(sentiment['fear_recovery_paused']),
        worsening_observed=worse,
    )


def _short_review(report, expires_at):
    native = report['market_assessment']
    timing = native.get('review_timing', {})
    if f.utc(report['cutoff']) >= expires_at:
        return 'DATA_BLOCKED', None, ['ENTRY_OR_REQUEST_WINDOW_CLOSED']
    if native['status'] != 'READY_RESEARCH_ONLY':
        return 'DATA_BLOCKED', None, native.get('blockers') or ['NATIVE_RISK_NOT_READY']
    if not timing.get('comparable'):
        return 'DATA_BLOCKED', None, ['ADJACENT_NATIVE_DECISIONS_REQUIRED']
    if timing['first_pending_escalation']:
        return 'REVIEW_CANDIDATE', 'RISK_WORSENING', []
    if (timing['recovery_stage_advanced'] and timing['recovery_guards_ready']
            and not timing['recovery_paused'] and not timing['worsening_observed']
            and not timing['confirmed_escalation']):
        return 'REVIEW_CANDIDATE', 'REENTRY_REVIEW', []
    if timing['confirmed_easing']:
        return 'REVIEW_CANDIDATE', 'RISK_EASING', []
    return 'NO_NEW_REVIEW', None, []


def composite_review_context(report, *, public_rows, sessions):
    """Join observed families for review; do not create another score or policy.

    Optional option histories are current-vintage originals. A five-session
    statistic requires the exact exchange grid, and a percentile excludes the
    current value. Neither supplies historical availability or dealer positions.
    """
    context = report['existing_market_context']
    native = report['market_assessment']
    session = report['session']
    f.require(bool(sessions) and sessions[-1] == session, 'OPTIONS_SESSION_GRID')
    macro = context.get('macro', {})

    def point(row):
        if row is None:
            return dict(status='MISSING', value=None, observation_date=None)
        current = row.get('status') == 'OBSERVED' and row.get('observation_date') == session
        return dict(status='OBSERVED' if current else 'DELAYED' if row.get('status') == 'OBSERVED' else row.get('status'),
            value=row.get('value') if current else None, observation_date=row.get('observation_date'),
            source_id=row.get('source_id'), source_sha256=row.get('source_sha256'),
            available_at=row.get('available_at'), unit=row.get('unit'),
            truth_class='CURRENT_VINTAGE_RESEARCH_ONLY')

    volatility = {key: point(macro.get(key)) for key in ('vix_9d', 'vix_30d', 'vix_3m', 'vvix', 'skew_index')}
    ratios = {}
    for name, left, right in (('vix9d_to_vix30', 'vix_9d', 'vix_30d'),
                              ('vix30_to_vix3m', 'vix_30d', 'vix_3m')):
        row = dict(context.get('derived_macro', {}).get(name, {}))
        current = all(volatility[key]['status'] == 'OBSERVED' for key in (left, right))
        ratios[name] = dict(status='OBSERVED' if current and row.get('status') == 'OBSERVED' else 'INSUFFICIENT_EVIDENCE',
            value=row.get('value') if current else None, evidence_path='existing_market_context.derived_macro.'+name,
            interpretation='IMPLIED_VOLATILITY_HORIZON_RATIO_NOT_FUTURES_CURVE')
    put_call = {}
    panel = {r['entity_id']: r for r in context.get('public', []) if r['provider'] == 'CBOE'}
    for universe in ('EQUITY', 'INDEX', 'TOTAL'):
        summary = panel.get(universe)
        current = bool(summary and summary['status'] == 'OBSERVED' and summary['observation_date'] == session)
        history = {r['observation_date']: r['value'] for r in public_rows
                   if r['provider'] == 'CBOE' and r['entity_id'] == universe}
        f.require(all(day < sessions[0] or day in sessions for day in history), 'CBOE_NON_SESSION_OBSERVATION')
        last_five = [history.get(day) for day in sessions[-5:]]
        last_six = [history.get(day) for day in sessions[-6:]]
        complete_five = current and len(last_five) == 5 and all(v is not None for v in last_five)
        complete_six = current and len(last_six) == 6 and all(v is not None for v in last_six)
        # Stop at the first gap; never skip a missing session to fill a window.
        prior = []
        for day in reversed(sessions[:-1][-63:]):
            value = history.get(day)
            if value is None:
                break
            prior.append(value)
        value = summary['current_value'] if current else None
        percentile = ((sum(x < value for x in prior)+.5*sum(x == value for x in prior))/len(prior)
                      if current and len(prior) >= 20 else None)
        put_call[universe] = dict(universe=universe, metric='put_call_volume_ratio',
            status='OBSERVED' if current else 'MISSING' if summary is None else
                'DELAYED' if summary['status'] == 'OBSERVED' else summary['status'],
            value=value, observation_date=None if summary is None else summary['observation_date'],
            source_sha256=None if summary is None else summary['source_sha256'],
            available_at=None if summary is None else summary['available_at'],
            mean_5_sessions=sum(last_five)/5 if complete_five else None,
            change_5_sessions=last_six[-1]-last_six[0] if complete_six else None,
            prior_only_midrank=percentile, prior_contiguous_sessions=len(prior),
            percentile_minimum_sessions=20, percentile_maximum_sessions=63,
            interpretation='TRADING_ACTIVITY_NOT_OPEN_INTEREST_OR_SIGNED_POSITION',
            historical_pit_certified=False)
    observed_options = sum(r['status'] == 'OBSERVED' for r in [*volatility.values(), *put_call.values()])
    options = dict(status='OBSERVED' if observed_options == 8 else 'PARTIAL' if observed_options else 'DATA_BLOCKED',
        volatility=volatility, horizon_ratios=ratios, put_call=put_call,
        gamma_status='GAMMA_NOT_VERIFIED', dealer_gamma=None,
        expiry_positioning_status='VERIFIED_CONTRACT_CALENDAR_AND_POSITION_DATA_REQUIRED',
        independent_risk_vote=False, directional_probability=None,
        source_admission_allowed=False, historical_pit_certified=False)
    ready_native = native['status'] == 'READY_RESEARCH_ONLY'
    axes = [{**r, 'axis_score': r.get('axis_score') if ready_native and r.get('axis_ready') else None}
            for r in native.get('axes', [])]
    price_axes = [r for r in axes if r['axis'] in {'market_breadth', 'trend_drawdown'}]
    ready_price_axes = {r['axis'] for r in price_axes if ready_native and r.get('axis_ready')}
    missing_price_axes = sorted({'market_breadth', 'trend_drawdown'}-ready_price_axes)
    positions = [r for r in context.get('public', []) if r['provider'] == 'CFTC']
    observed_positions = sum(r['status'] == 'OBSERVED' for r in positions)
    families = dict(
        price_breadth=dict(status='OBSERVED' if not missing_price_axes else 'PARTIAL' if ready_price_axes else 'DATA_BLOCKED',
            native_axes=price_axes, missing_native_axes=missing_price_axes,
            price_cohorts=context.get('price', []), independent_risk_vote=False),
        macro_credit_liquidity=dict(status=report.get('macro_diagnosis', {}).get('status', 'DATA_BLOCKED'),
            evidence_paths=['macro_diagnosis.windows', 'funding', 'liquidity', 'bank_credit',
                            'financing_conditions', 'recession_watch.groups.credit'],
            native_axes=[r for r in axes if r['axis'] in {'credit', 'rates_liquidity', 'economic_stress', 'cross_asset'}],
            independent_risk_vote=False),
        options=options,
        sentiment=dict(status=native.get('sentiment_context', {}).get('status', 'DATA_BLOCKED'),
            native=native.get('sentiment_context'), household_expectations=report.get('household_expectations', []),
            external_fear_greed_status='NOT_CONNECTED', external_fear_greed_value=None,
            overlaps_with=['price_breadth', 'options', 'macro_credit_liquidity'], independent_risk_vote=False),
        positioning=dict(status='OBSERVED' if positions and observed_positions == len(positions) else
                         'PARTIAL' if observed_positions else 'DATA_BLOCKED',
            observations=positions, observed_count=observed_positions, supplied_count=len(positions),
            interpretation='FUTURES_PARTICIPANT_CLASSES_NOT_STOCK_OPTION_DEALER_POSITIONS', independent_risk_vote=False),
        security_leadership_thesis=dict(status='A2_A3_ORIGINALS_REQUIRED',
            consumer='A5_EXISTING_NATIVE_CANDIDATE_COMPETITION',
            requirements=['MARKET_RELATIVE_RS_20_60_120_240', 'SECTOR_BENCHMARK_IF_VERIFIED',
                'VOLUME_AND_LIQUIDITY', 'CURRENT_REVIEWED_THESIS_AND_NET_ER',
                'ORIGINAL_EXIT_REVIEW_AND_REPLACEMENT_COSTS']))
    return dict(schema='a4-composite-review-context-v1', authority='RESEARCH_CONTEXT_ONLY',
        status='OBSERVED_CONTEXT_ONLY' if ready_native else 'PARTIAL_CONTEXT_NATIVE_BLOCKED',
        session=session, cutoff=report['cutoff'], native_risk_status=native['status'],
        families=families, composite_score=None, independent_vote_count=None,
        automatic_buy_sell_allowed=False, portfolio_effect_allowed=False,
        required_security_review=['HOLD', 'SELECTIVE_REDUCTION', 'THESIS_EXIT', 'COST_AWARE_REPLACEMENT', 'CASH_COMPARISON'],
        sell_authority='EXISTING_A3_A5_ORIGINAL_EXIT_REVIEW_REQUIRED',
        single_indicator_exit_allowed=False, semiconductor_only=False)


def review_handoff(report, *, expires_at, entry_close_at, release_expires_at=None):
    """Build an additive A4-to-research context view of the existing V2 report."""
    expiry = min(f.utc(expires_at), f.utc(entry_close_at))
    status, candidate, blockers = _short_review(report, expiry)
    release = report.get('learning_provenance', {})
    release_expiry = min(expiry, f.utc(release_expires_at)) if release_expires_at is not None else None
    reviewed = (release.get('status') == 'EXTERNALLY_REVIEWED_FIXED_RELEASE'
                and release_expiry is not None and f.utc(report['cutoff']) < release_expiry)
    benchmarks = {(row['target'], row['horizon_sessions']): row for row in report.get('benchmark_outlook', [])}
    horizons = []
    for horizon, role in ((21, 'ENTRY_WARNING_AND_REVIEW'), (63, 'PRIMARY_SELECTION_RESEARCH'),
                          (126, 'PERSISTENCE_RESEARCH')):
        pair = {}
        for target in ('SPY', 'QQQ'):
            row = benchmarks.get((target, horizon), {})
            direction = row.get('direction')
            if reviewed and row.get('evidence') and direction in {'UP', 'DOWN', 'FLAT', 'MIXED'}:
                pair[target] = dict(status='REVIEWED_RESEARCH_EVIDENCE', direction=direction, expires_at=release_expiry.isoformat(),
                                    evidence_path='benchmark_outlook')
            else:
                pair[target] = dict(status='INSUFFICIENT_EVIDENCE', direction=None,
                                    blockers=row.get('blockers') or ['CURRENT_REVIEWED_BENCHMARK_EVIDENCE_REQUIRED'])
        horizons.append(dict(horizon_sessions=horizon, role=role, benchmarks=pair))
    native = report['market_assessment']
    alternatives = {
        'RISK_WORSENING': ['HOLD_EXISTING', 'DEFER_NEW_OR_INCREASED_EXPOSURE',
                           'REVIEW_SELECTIVE_REDUCTION', 'REVIEW_THESIS_EXIT',
                           'COMPARE_COST_AWARE_REPLACEMENT', 'CASH_ALTERNATIVE'],
        'RISK_EASING': ['HOLD_EXISTING', 'REVIEW_NEW_OR_INCREASED_EXPOSURE', 'CASH_ALTERNATIVE'],
        'REENTRY_REVIEW': ['HOLD_EXISTING', 'COMPARE_STAGED_REENTRY', 'CASH_ALTERNATIVE'],
    }
    return dict(
        schema='a4-market-review-handoff-v1', authority='RESEARCH_CONTEXT_ONLY',
        session=report['session'], cutoff=report['cutoff'], expires_at=expiry.isoformat(),
        request_sha256=report['request_sha256'],
        entry_close_at=entry_close_at, holding_period_basis='NYSE_CLOSE_TO_CLOSE',
        return_maturity='H_TRADING_INTERVALS_AFTER_NEXT_NYSE_CLOSE',
        status=status, candidate=candidate, blockers=blockers,
        candidate_key=report['session']+':'+candidate if candidate else None,
        native_timing=native.get('review_timing'), native_truth_class=native.get('declared_input_truth_class'),
        recovery_stage=native.get('fear_recovery_stage'), horizons=horizons,
        evidence_paths=['market_assessment.axes', 'source_receipts', 'a4_observation_provenance',
                        'macro_diagnosis.windows', 'financing_conditions', 'recession_watch',
                        'candidate_reassessment_snapshot', 'composite_review_context'],
        context_status={key: report.get(key, {}).get('status', 'DATA_BLOCKED')
                        for key in ('funding', 'liquidity', 'bank_credit', 'financing_conditions')},
        exposure=dict(scope='US_EQUITY_COMMON_RISK', channels=['RISK', 'TIMING'],
                      affected_assets=None, candidate_mapping='VERIFIED_EXPOSURE_INDEX_REQUIRED'),
        research_alternatives=alternatives.get(candidate, []),
        reduction_exit_requirements=['CURRENT_SAME_SECURITY_A3_THESIS_AND_NET_ER',
            'MARKET_RELATIVE_RS_AND_LIQUIDITY', 'VERIFIED_PORTFOLIO_COMMON_RISK_EXPOSURE',
            'ORIGINAL_A5_EXIT_REVIEW', 'REPLACEMENT_COSTS_REENTRY_RISK_AND_UNCERTAINTY'],
        invalidated_by=['ENTRY_OR_REQUEST_WINDOW_CLOSED', 'LATER_SESSION_OR_SOURCE_REVISION',
                        'NATIVE_READINESS_LOST', 'RECOVERY_GUARDS_MISSING_OR_PAUSED'],
        solo_stock_cash_research_allowed=True, portfolio_effect_allowed=False,
        automatic_winner_exit_allowed=False, automatic_dispatch_allowed=False,
    )

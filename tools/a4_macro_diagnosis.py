"""Explain observed macro conditions without inventing a return forecast.

Signs describe financing pressure or economic quantities, not calibrated
equity effects. Families are never counted as independent risk votes.
"""
from __future__ import annotations

import math
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

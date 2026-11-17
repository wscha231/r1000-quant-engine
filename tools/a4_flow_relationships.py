"""Current-vintage balance/rate associations. No fit, forecast or PIT admission."""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
from datetime import timedelta
import math
import re
import numpy as np
import pandas as pd
from tools import a4_primary_sources as primary, a4_liquidity_analysis as liquidity
from tools import macro_technical_study as technical
from tools.macro_history_sources import digest, encoded

LOADED_METHOD_SHA256=digest(Path(__file__).read_bytes())
TARGETS=('SPY','QQQ')
HORIZONS=(1,5,10,21,63,126,252,504)
BALANCES=('fed_assets','reserves_week_average','tga_week_average','rrp_other_week_average')+tuple(
    name for base in ('deposits','loans','commercial_industrial_loans','cash_assets')
    for name in ((base if base=='commercial_industrial_loans' else base+'_all'),
                 base+'_domestic',base+'_large',base+'_small'))
RATES=('sofr','tgcr','iorb','effr')
MAX_ROWS=150000
SAFETY=dict(historical_pit_certified=False,training_admitted=False,source_admitted=False,
    qualified_backtest=False,forecast_release_allowed=False,accepted_model_changed=False,
    accepted_portfolio_changed=False,a3_executed=False,a5_executed=False,model_fits=0)

def need(ok,reason):
    if not ok:raise ValueError('A4_FLOW_'+reason)

def specification():
    return dict(schema='a4-flow-relationship-spec-v1',targets=list(TARGETS),
        horizons=list(HORIZONS),base_series=list(BALANCES+RATES),base_series_count=24,
        derived_spreads=dict(liquidity.SPREADS),balance_transform='EXACT_7_CALENDAR_DAY_USD_DELTA',
        rate_transform='PREVIOUS_NATIVE_OBSERVATION_DELTA_BP_MAX_7_DAY_GAP',
        spread_transform='SAME_OBSERVATION_DATE_LEVEL_BP',
        alignment='MEASUREMENT_DATE_NEXT_OBSERVED_PRICE_SESSION',entry_delay_sessions=1,
        left_edge='MEASUREMENT_DATE_MUST_NOT_PRECEDE_FIRST_PRICE_SESSION',
        outcome='NEXT_CLOSE_FORWARD_PRICE_RETURN',minimum_pairs=30,
        statistics=['PEARSON','SPEARMAN'],declared_pairs=448,declared_coefficients=896,
        p_values=False,multiple_test_selection=False,independent_source_votes=False,
        interpretation='CURRENT_VINTAGE_DESCRIPTIVE_NOT_HISTORICALLY_TRADABLE',**SAFETY)

def _visible(rows,cutoff):
    need(type(rows) is list and len(rows)<=MAX_ROWS,'ROW_BUDGET')
    specs={'frb:'+k:v for k,v in primary.semantic_register().items()}
    specs.update({'nyfed:'+k:liquidity.SERIES[k] for k in ('SOFR','TGCR','EFFR')})
    state=defaultdict(dict);sources={};visible=[]
    for row in rows:
        need(type(row) is dict,'ROW_TYPE')
        key=row.get('logical_id')
        if key not in BALANCES+RATES:continue
        # Later captures cannot alter a fixed earlier descriptive view.
        available=primary.clock(row['available_at']);collected=primary.clock(row['collected_at'])
        if available>cutoff or collected>cutoff:continue
        date=primary.day(row['observation_date'])
        need(date<=available.date() and date<=collected.date(),'OBSERVATION_CLOCK')
        sid=row.get('source_id');need(sid in specs and specs[sid][0]==key,'SOURCE_ID')
        spec=specs[sid]
        need(tuple(row.get(k) for k in ('unit','frequency','measurement_basis','seasonal_basis'))==spec[1:5],'SEMANTICS')
        need(sources.setdefault(key,sid)==sid,'MIXED_PUBLISHER')
        pin=row.get('original_sha256');need(type(pin) is str and re.fullmatch('[0-9a-f]{64}',pin),'ORIGINAL_HASH')
        value=row.get('value');need(value is None or (type(value) in (int,float) and math.isfinite(value) and abs(value)<=1e15),'VALUE')
        need(date not in state[key],'DUPLICATE_OBSERVATION')
        state[key][date]=row;visible.append(row)
    return state,visible

def _features(state):
    result={}
    for key in BALANCES+RATES:
        history=state.get(key,{})
        points=[];previous=None
        for date,row in sorted(history.items()):
            peer=history.get(date-timedelta(days=7)) if key in BALANCES else previous
            value=None
            if peer is not None and row['value'] is not None and peer['value'] is not None:
                gap=(date-primary.day(peer['observation_date'])).days
                if key in BALANCES or 0<gap<=7:
                    scale={'millions_usd':1e6,'billions_usd':1e9,'percent':100}[row['unit']]
                    value=(row['value']-peer['value'])*scale
                    need(math.isfinite(value),'TRANSFORM_OVERFLOW')
            if value is not None:points.append((date,value))
            previous=row
        result['change:'+key]=points
    for name,(left,right) in liquidity.SPREADS.items():
        a,b=state.get(left,{}),state.get(right,{})
        result['spread:'+name]=[(date,(a[date]['value']-b[date]['value'])*100)
            for date in sorted(set(a)&set(b)) if a[date]['value'] is not None and b[date]['value'] is not None]
    return result

def _correlation(x,y):
    a=np.asarray(x,dtype=float);b=np.asarray(y,dtype=float)
    # Center then scale before products; retain unknown for constant operands.
    a=a-a.mean();b=b-b.mean();sa=float(np.max(np.abs(a)));sb=float(np.max(np.abs(b)))
    if sa==0 or sb==0:return None
    a=a/sa;b=b/sb;denom=math.sqrt(float(a@a)*float(b@b))
    return max(-1.,min(1.,float(a@b)/denom)) if denom else None

def describe(rows,prices,*,cutoff):
    """One native observation per anchor; all declared pairs, including missing.

    Original actual availability is retained. Measurement-date alignment of a
    currently revised history does NOT authenticate availability at that date.
    The caller supplies independently pinned original/Reader evidence.
    """
    need(digest(Path(__file__).read_bytes())==LOADED_METHOD_SHA256,'LOADED_METHOD_CHANGED')
    clock=primary.clock(cutoff);need(type(prices) is dict and set(prices)==set(TARGETS),'BOTH_TARGETS_REQUIRED')
    closed={}
    for target,series in prices.items():
        need(isinstance(series,pd.Series) and isinstance(series.index,pd.DatetimeIndex),'PRICE_SERIES')
        idx=series.index
        need(idx.tz is None and not idx.hasnans and idx.is_unique and idx.is_monotonic_increasing
             and idx.equals(idx.normalize()) and 2<=len(idx)<=10000,'PRICE_GRID')
        values=series.to_numpy(float)
        need(not np.isinf(values).any() and ((values[np.isfinite(values)]>0)&(values[np.isfinite(values)]<=1e12)).all(),'PRICE_VALUE')
        # Exclude the current UTC date without inventing an intraday close clock.
        closed[target]=series.loc[idx<pd.Timestamp(clock.date())].astype(float)
    need(closed['SPY'].index.equals(closed['QQQ'].index) and len(closed['SPY'])>=2,'COMMON_PRICE_GRID')
    state,visible=_visible(rows,clock);features=_features(state);results=[]
    dates=closed['SPY'].index
    labels={t:{h:technical.labels(s,h).to_numpy(float) for h in HORIZONS} for t,s in closed.items()}
    for feature,points in features.items():
        # Weekend/holiday mappings cannot count several releases as one extra
        # independent session sample. Keep the latest native date at each anchor.
        anchors={};collisions=0
        for day,value in points:
            if day<dates[0].date():continue
            position=int(dates.searchsorted(pd.Timestamp(day)))
            if position>=len(dates):continue
            if position in anchors:collisions+=1
            anchors[position]=(day,value)
        for target in TARGETS:
            for horizon in HORIZONS:
                y=labels[target][horizon];pairs=[(pos,day,x,float(y[pos])) for pos,(day,x) in sorted(anchors.items()) if np.isfinite(y[pos])]
                xs=[r[2] for r in pairs];ys=[r[3] for r in pairs];positions=[r[0] for r in pairs]
                pearson=spearman=None
                if len(pairs)>=30:
                    pearson=_correlation(xs,ys)
                    spearman=_correlation(pd.Series(xs).rank(method='average'),pd.Series(ys).rank(method='average'))
                independent=technical.independent_windows(positions,horizon+1)
                results.append(dict(feature=feature,target=target,horizon_sessions=horizon,
                    native_feature_observations=len(points),pairs=len(pairs),anchor_collisions_discarded=collisions,
                    nonoverlap_outcome_windows=independent,first=None if not pairs else pairs[0][1].isoformat(),
                    last=None if not pairs else pairs[-1][1].isoformat(),pearson=pearson,spearman=spearman,
                    status='DESCRIPTIVE_ONLY' if pearson is not None else 'INSUFFICIENT_EVIDENCE',
                    statistical_evidence='NOT_TESTED_FOR_SIGNIFICANCE' if independent>=20 else 'INSUFFICIENT_EVIDENCE',
                    independent_signal=False,dependence_group=('BANK_AGGREGATIONS_OVERLAP' if any(name in feature for name in ('deposits','loans','cash_assets')) else 'FUNDING_SHARED_INPUTS' if feature.startswith('spread:') or feature.split(':',1)[1] in RATES else 'CENTRAL_BANK_BALANCE_SHEET')))
    specification_pin=digest(encoded(specification()))
    semantic=dict(specification_sha256=specification_pin,
        macro=[{k:r[k] for k in ('logical_id','observation_date','value','unit','frequency','measurement_basis','seasonal_basis')}
               for r in sorted(visible,key=lambda r:(r['logical_id'],r['observation_date']))],
        prices={t:dict(dates=[x.date().isoformat() for x in s.index],values=[float(x) if math.isfinite(x) else None for x in s]) for t,s in sorted(closed.items())})
    provenance={key:dict(source_id=next(iter(history.values()))['source_id'],
        originals=sorted({r['original_sha256'] for r in history.values()}),
        available_at_min=min((r['available_at'] for r in history.values()),key=primary.clock),available_at_max=max((r['available_at'] for r in history.values()),key=primary.clock)) for key,history in sorted(state.items()) if history}
    return dict(schema='a4-flow-relationship-report-v1',status='CURRENT_VINTAGE_DESCRIPTIVE_ONLY',
        cutoff=cutoff,specification=specification(),semantic_input_sha256=digest(encoded(semantic)),
        source_provenance=provenance,actual_base_series=len(state),requested_base_series=24,
        missing_base_series=sorted(set(BALANCES+RATES)-set(state)),results=results,
        comparison_population='PAIRWISE_NATIVE_OBSERVATIONS_NOT_COMMON_COMPLETE_24_SERIES',
        cross_feature_ranking_validated=False,statistical_significance_claimed=False,
        causal_effect_claimed=False,observation_date_is_release_date=False,
        deposit_change_is_identified_transfer=False,price_is_index_proxy='SPY_AND_QQQ_ETFS',**SAFETY)

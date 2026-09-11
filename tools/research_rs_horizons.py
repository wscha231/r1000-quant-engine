"""Date-aligned relative strength for every candidate; never an alpha weight.

Input prices are provider-adjusted discovery observations. Today's cohort is
not historical membership. No missing bar, pre-IPO value or future close is filled.
"""
from collections import Counter, defaultdict
from bisect import bisect_right
import math

HORIZONS=(5,10,20,60,120,240,504)
GROUPS={'short':(5,10,20),'medium':(60,120),'long':(240,504)}


def clean(rows,end):
    result={};last=''
    for row in rows:
        day=row['t'][:10];price=row['c']
        if day>end:continue
        if day<=last or type(price) not in (int,float) or not math.isfinite(price) or price<=0:
            raise ValueError('rs_invalid_or_duplicate_price')
        last=day
        result[day]=float(price)
    return result


def horizon(prices,benchmark,dates,anchor,n):
    if anchor<n:return {'status':'missing','reason':'insufficient_benchmark_history'}
    window=dates[anchor-n:anchor+1]
    if any(day not in prices for day in window):
        return {'status':'missing','reason':'missing_price_or_pre_listing_history'}
    start,end=window[0],window[-1]
    ret=prices[end]/prices[start]-1.;br=benchmark[end]/benchmark[start]-1.
    return dict(status='available',start=start,end=end,stock_return=ret,benchmark_return=br,
        excess_return_pp=(ret-br)*100.,relative_wealth_return=(1+ret)/(1+br)-1.)


def percentiles(items,key):
    ordered=sorted(items,key=lambda r:r[key]);n=len(ordered)
    values=[r[key] for r in ordered]
    for r in ordered:
        # Equal values receive equal ranks. A one-name cohort has no percentile.
        lo=values.index(r[key]);hi=bisect_right(values,r[key])-1
        r['percentile']=100.*(lo+hi)/2/(n-1) if n>1 else None
        r['peer_count']=n


def state(values):
    present=[v['excess_return_pp'] for v in values if v['status']=='available']
    if not present:return 'insufficient_history'
    if len(present)!=len(values):return 'partial_history'
    if all(v>0 for v in present):return 'outperforming'
    if all(v<0 for v in present):return 'underperforming'
    return 'mixed'


def analyze(adjusted,members,end):
    if 'SPY' not in adjusted:raise ValueError('rs_benchmark_missing')
    benchmark=clean(adjusted['SPY'],end);dates=sorted(benchmark)
    if not dates or dates[-1]!=end:raise ValueError('rs_benchmark_stale')
    rows=[]
    for member in members:
        ticker=member['ticker']
        if member['market']!='US' or ticker=='SPY':continue
        prices=clean(adjusted.get(ticker,[]),end)
        horizons={str(n):horizon(prices,benchmark,dates,len(dates)-1,n) for n in HORIZONS}
        short_change=None
        if len(dates)>40:
            previous=horizon(prices,benchmark,dates,len(dates)-21,20)
            if previous['status']=='available' and horizons['20']['status']=='available':
                short_change=horizons['20']['excess_return_pp']-previous['excess_return_pp']
        window=dates[-200:]
        above=(prices[end]>sum(prices[d] for d in window)/200
            if len(window)==200 and all(d in prices for d in window) else None)
        rows.append(dict(ticker=ticker,security_id='US:'+ticker,sector=member.get('sector'),
            sector_basis='IWB' if 'US_IWB' in member.get('candidate_origins',[]) or 'IWB' in member.get('candidate_origins',[]) else 'foreign_seed_unverified',
            last_session=max(prices) if prices else None,horizons=horizons,
            strength={g:state([horizons[str(n)] for n in ns]) for g,ns in GROUPS.items()},
            rs20_change_over_20_sessions_pp=short_change,above_200_session_average=above,
            investment_rank=None))
    for n in HORIZONS:
        eligible=[r for r in rows if r['horizons'][str(n)]['status']=='available']
        peers=[dict(ticker=r['ticker'],value=r['horizons'][str(n)]['excess_return_pp']) for r in eligible]
        percentiles(peers,'value');by={r['ticker']:r for r in peers}
        sectors=defaultdict(list)
        for r in eligible:
            if r['sector_basis']=='IWB' and r['sector'] not in (None,'','Unclassified'):
                sectors[r['sector']].append(dict(ticker=r['ticker'],value=r['horizons'][str(n)]['excess_return_pp']))
        sector_rank={}
        for values in sectors.values():
            if len(values)>=5:
                percentiles(values,'value');sector_rank.update({r['ticker']:r for r in values})
        for r in eligible:
            h=r['horizons'][str(n)];p=by[r['ticker']];s=sector_rank.get(r['ticker'],{})
            h.update(market_percentile=p['percentile'],market_peer_count=p['peer_count'],
                sector_percentile=s.get('percentile'),sector_peer_count=s.get('peer_count',0))
    return dict(schema_version='research-rs-horizons-v1',as_of=end,benchmark='SPY',horizons=list(HORIZONS),
        candidate_count=len(rows),data_kind='REAL',historical_membership_verified=False,
        price_basis='provider_adjusted_discovery_proxy',ranking_use='RESEARCH_DISCOVERY_ONLY',
        investment_approved=False,rows=rows,
        coverage={str(n):sum(r['horizons'][str(n)]['status']=='available' for r in rows) for n in HORIZONS},
        state_counts={g:dict(Counter(r['strength'][g] for r in rows)) for g in GROUPS})

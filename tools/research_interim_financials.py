"""Normalize explicitly reviewed interim observations without backdating them.

The append-only observation registry bridges foreign issuer quarterly reports
that companyfacts omits. Comparative figures remain current-research evidence;
this module never creates a historical H1 envelope or a valuation approval.
"""
from datetime import date,datetime,timedelta,timezone
import hashlib
import json
import math
from pathlib import Path


def normalize(registry,ticker,analysis_at):
    cutoff=datetime.fromisoformat(analysis_at.replace('Z','+00:00'))
    rows=[r for r in registry['records'] if r['ticker']==ticker and
        datetime.fromisoformat(r['observed_at'].replace('Z','+00:00'))<=cutoff]
    if not rows:return dict(status='MISSING',ticker=ticker,historical_use_allowed=False)
    periods={}
    for r in rows:
        start,end=map(date.fromisoformat,(r['period_start'],r['period_end']))
        if r['period_kind']!='QUARTER' or not 70<=(end-start).days<=105 or end>cutoff.date():
            raise ValueError('interim_period_invalid')
        if r.get('historical_use_allowed') is not False:raise ValueError('interim_backdating_prohibited')
        if not r['source'].startswith('https://') or not r['pages']:raise ValueError('interim_source_missing')
        if r['scale']!=1000000:raise ValueError('interim_scale_invalid')
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in r['values'].values()):
            raise ValueError('interim_number_invalid')
        if r['values']['capex_ppe']<0:raise ValueError('interim_capex_sign')
        if end in periods:raise ValueError('interim_conflicting_period')
        periods[end]=r
    rows=[periods[d] for d in sorted(periods)][-4:]
    complete=(len(rows)==4 and len({r['currency'] for r in rows})==1 and all(
        date.fromisoformat(b['period_start'])==date.fromisoformat(a['period_end'])+timedelta(days=1)
        for a,b in zip(rows,rows[1:])))
    age=(cutoff.date()-date.fromisoformat(rows[-1]['period_end'])).days
    totals={k:sum(r['values'][k]*r['scale'] for r in rows) for k in rows[-1]['values']} if complete and age<=135 else None
    if totals:totals['free_cash_flow_ppe']=totals['operating_cash_flow']-totals['capex_ppe']
    return dict(status='CURRENT_TTM_NORMALIZED' if totals else 'INCOMPLETE_OR_STALE_TTM',
        ticker=ticker,reporting_currency=rows[-1]['currency'],trading_currency='USD',
        latest_quarter_end=rows[-1]['period_end'],quarter_count=len(rows),ttm_company_totals=totals,
        components=rows,analysis_at=analysis_at,historical_use_allowed=False,
        native_to_usd_conversion_verified=False,full_h1_ready=False,valuation_approved=False,
        per_us_security_basis_verified=False,free_cash_flow_definition=registry['free_cash_flow_definition'])


def current_packets(analysis_at):
    path=Path(__file__).resolve().parents[1]/'docs/research_interim_financials_20260910.json'
    raw=path.read_bytes();registry=json.loads(raw)
    return dict(registry_sha256=hashlib.sha256(raw).hexdigest(),
        packets=[normalize(registry,t,analysis_at) for t in sorted({r['ticker'] for r in registry['records']})])

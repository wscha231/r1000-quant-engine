#!/usr/bin/env python3
"""Source-derived candidate inventories; membership is not investment approval."""
from __future__ import annotations

from collections import Counter
import csv
from datetime import date, datetime
import io
import json
from pathlib import Path
import re

from research_source_connection import canonical, digest_bytes, guarded, key, require, save_private

IWB_URL = 'https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/latest-holdings.csv'
KR_ENDPOINTS = {'KOSPI':'stk_bydd_trd', 'KOSDAQ':'ksq_bydd_trd'}
US_EXCHANGES = {'NYSE', 'Nasdaq', 'NYSE American', 'NYSE Arca', 'Cboe BZX'}


def adr_candidates():
    # This file is a discovery seed, not current capitalization, proof of an
    # active listing, or historical membership. Ignore speculative watchlists.
    import yaml
    path=Path(__file__).resolve().parents[1]/'adr_universe.yaml'
    raw=path.read_bytes();rows=yaml.safe_load(raw)['adr_universe']
    require(isinstance(rows,list) and rows,'adr_seed_schema')
    symbols=[r['ticker'] for r in rows]
    require(len(symbols)==len(set(symbols)),'duplicate_member')
    require({'TSM','ASML'}<=set(symbols),'priority_adr_missing')
    return rows,dict(path='adr_universe.yaml',sha256=digest_bytes(raw))


def parse_sec_exchange(value):
    require(isinstance(value,dict) and {'fields','data'}<=set(value),'sec_exchange_schema')
    fields=value['fields']
    require({'cik','name','ticker','exchange'}<=set(fields),'sec_exchange_schema')
    rows=[dict(zip(fields,r)) for r in value['data'] if len(r)==len(fields)]
    require(len(rows)==len(value['data']) and rows,'sec_exchange_schema')
    result={}
    for r in rows:
        ticker=r['ticker'].replace('-','.') if '.' not in r['ticker'] else r['ticker']
        require(ticker not in result,'duplicate_member')
        result[ticker]={**r,'ticker':ticker,'cik':str(r['cik']).zfill(10)}
    return result


def collect_us_foreign(capture,end):
    seeds,provenance=adr_candidates()
    value,receipt=capture.get('sec_exchange_membership','https://www.sec.gov/files/company_tickers_exchange.json',
        validator=parse_sec_exchange)
    listed=parse_sec_exchange(value);members=[];excluded=[]
    for seed in seeds:
        ticker=seed['ticker'];row=listed.get(ticker)
        reason=('seed_skip' if seed.get('skip') else 'not_in_current_sec_exchange_map' if not row
                else 'non_us_exchange_or_otc' if row['exchange'] not in US_EXCHANGES else None)
        if reason:
            excluded.append(dict(ticker=ticker,reason=reason));continue
        members.append(dict(ticker=ticker,market='US',currency='USD',name=row['name'],exchange=row['exchange'],
            issuer_id='CIK:'+row['cik'],issuer_country=seed.get('country'),issuer_country_verified=False,
            sector=seed.get('sector','Unclassified'),security_type='foreign_listing_structure_review_required',
            membership_as_of=None,observed_at=receipt['retrieved_at'],requested_date=end,
            candidate_origin='curated_foreign_seed_verified_current_sec_exchange',
            entity_history_verified=False))
    missing=sorted({'TSM','ASML'}-{m['ticker'] for m in members})
    return dict(source_kind='US_LISTED_FOREIGN_CANDIDATES',members=members,seed_provenance=provenance,
        seed_count=len(seeds),excluded_candidates=excluded,excluded=dict(Counter(r['reason'] for r in excluded)),
        priority_missing=missing,priority_coverage_complete=not missing,receipt=receipt,
        membership_as_of=None,observed_at=receipt['retrieved_at'],exact_requested_date=False,
        current_exchange_identity_only=True,broker_tradability_verified=False,
        historical_selection_allowed=False,exhaustive_adr_universe=False)


def collect_us_universe(capture,end):
    sources=[guarded('US_IWB',lambda:collect_iwb(capture,end)),
             guarded('US_FOREIGN',lambda:collect_us_foreign(capture,end))]
    merged={};duplicates=0
    for source in sources:
        if source['status']!='COLLECTED':continue
        for member in source['data']['members']:
            ticker=member['ticker']
            if ticker in merged:
                duplicates+=1
                old=merged[ticker]
                require(old['currency']==member['currency'],'duplicate_currency_conflict')
                merged[ticker]={**old,**member,'membership_as_of':old['membership_as_of'],
                    'candidate_origins':['IWB','US_FOREIGN']}
            else:merged[ticker]={**member,'candidate_origins':[source['name']]}
    members=[merged[t] for t in sorted(merged)]
    require(all(m['market']=='US' and m['currency']=='USD' for m in members),'us_market_currency')
    issuer_groups={}
    for m in members:
        if m.get('issuer_id'):issuer_groups.setdefault(m['issuer_id'],[]).append(m['ticker'])
    result=dict(mode='US_LISTED_WITH_FOREIGN_INVENTORY',sources=sources,members=members,historical_probes=[],
        source_coverage_complete=all(s['status']=='COLLECTED' and s['data'].get('priority_coverage_complete',True) for s in sources),
        duplicate_security_rows_merged=duplicates,
        duplicate_issuer_groups=[v for v in issuer_groups.values() if len(v)>1],
        historical_selection_allowed=False,continuous_historical_membership_verified=False,
        qualitative_analysis_complete=False,investment_approval=False,
        scope='US IWB equities plus current US-exchange foreign candidates; USD cash permitted; no KR listings')
    save_private(capture.root/'universe_snapshots.json',canonical(result))
    return result


def connection_sample():
    """Retain the old test set with its actual origin, never call it top-ranked."""
    path=Path(__file__).resolve().parents[1]/'docs/run287_daily_research_monitor_contract.json'
    raw=path.read_bytes();watchlist=json.loads(raw)['watchlist']
    require(set(watchlist)=={'US','KR'},'sample_markets')
    require(all(v and len(v)==len(set(v)) for v in watchlist.values()),'sample_duplicates')
    return dict(mode='CONNECTION_SAMPLE',symbols=watchlist,
        provenance=dict(path='docs/run287_daily_research_monitor_contract.json',sha256=digest_bytes(raw)),
        selection_method='inherited_theme_watchlist',quantitative_selection_rule=None,
        historical_selection_allowed=False,investment_approval=False)


def parse_iwb(raw,requested_date):
    table=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
    require(table and table[0] and table[0][0].strip()=='iShares Russell 1000 ETF','iwb_identity')
    dates=[r[1].strip() for r in table[:20] if len(r)>1 and r[0].strip()=='Fund Holdings as of']
    require(len(dates)==1,'iwb_date_missing')
    asof=datetime.strptime(dates[0],'%b %d, %Y').date().isoformat()
    require(asof<=requested_date,'future_membership')
    header=next((i for i,r in enumerate(table[:25]) if r and r[0].strip()=='Ticker'),None)
    require(header is not None,'iwb_schema')
    fields=[c.strip() for c in table[header]]
    require({'Ticker','Name','Sector','Asset Class','Exchange','Market Currency'}<=set(fields),'iwb_schema')
    members=[];excluded=Counter();seen=set();equity_rows=0
    for cells in table[header+1:]:
        if not cells or not any(c.strip() for c in cells):break
        require(len(cells)==len(fields),'iwb_row_schema')
        row=dict(zip(fields,cells))
        if row['Asset Class']!='Equity':
            excluded['non_equity']+=1;continue
        equity_rows+=1
        ticker=row['Ticker'].strip().replace(' ','.').replace('/','.')
        if not re.fullmatch(r'[A-Z][A-Z0-9]{0,7}(?:[.\-][A-Z0-9]{1,3})?',ticker):
            excluded['unresolved_symbol']+=1;continue
        require(ticker not in seen,'duplicate_member');seen.add(ticker)
        members.append(dict(ticker=ticker,market='US',name=row['Name'],sector=row['Sector'],
            exchange=row['Exchange'],currency=row['Market Currency'],membership_as_of=asof,
            security_type='provider_equity',entity_history_verified=False))
    require(members,'iwb_empty')
    return dict(source_kind='IWB_EQUITY_PROXY',requested_date=requested_date,membership_as_of=asof,
        exact_requested_date=asof==requested_date,equity_rows=equity_rows,members=members,
        excluded=dict(excluded),sector_counts=dict(sorted(Counter(m['sector'] for m in members).items())),
        historical_selection_allowed=False,full_us_market=False,index_membership_exact=False)


def collect_iwb(capture,end):
    raw,receipt=capture.get('iwb_current_membership',IWB_URL,json_body=False,
        validator=lambda r:parse_iwb(r,end))
    result=parse_iwb(raw,end)
    # This is a broad index proxy. A truncated file must not degrade into a
    # small, apparently complete candidate pool.
    require(len(result['members'])>=800,'iwb_coverage_floor')
    result['receipt']=receipt
    return result


def number(value):
    if value in (None,'','-'):return None
    value=float(str(value).replace(',',''))
    require(value>=0 and value<float('inf'),'krx_nonnegative_number')
    return value


def parse_krx(value,end,board):
    rows=value['OutBlock_1'];require(isinstance(rows,list) and rows,'krx_rows')
    members=[];seen=set()
    for r in rows:
        require(r.get('BAS_DD')==end.replace('-',''),'krx_date')
        ticker=str(r.get('ISU_CD',''))
        require(re.fullmatch(r'[0-9A-Z]{6}',ticker) is not None,'krx_symbol')
        require(ticker not in seen,'duplicate_member');seen.add(ticker)
        close=number(r.get('TDD_CLSPRC'));volume=number(r.get('ACC_TRDVOL'))
        members.append(dict(ticker=ticker,market='KR',board=board,name=r.get('ISU_NM'),
            currency='KRW',membership_as_of=end,session=end,close=close,volume=volume,
            market_cap_krw=number(r.get('MKTCAP')),turnover_krw=number(r.get('ACC_TRDVAL')),
            has_positive_trade=bool(close and volume),
            security_type='share_class_review_required',entity_history_verified=False))
    # Keep halted/no-price names in the inventory. Excluding them would hide
    # the missing-price or lifecycle work from later eligibility checks.
    return dict(source_kind='KRX_DAILY_SHARES',board=board,membership_as_of=end,
        exact_requested_date=True,members=members,historical_selection_allowed=False,
        publication_time_verified=False,continuous_history_verified=False)


def collect_kr_board(capture,end,board):
    endpoint='https://data-dbg.krx.co.kr/svc/apis/sto/'+KR_ENDPOINTS[board]
    value,receipt=capture.get('krx_'+board+'_'+end,endpoint,{'basDd':end.replace('-','')},
        {'AUTH_KEY':key('KRX_API_KEY')},validator=lambda r:parse_krx(r,end,board))
    result=parse_krx(value,end,board);result['receipt']=receipt
    return result


def listing_temporal_audit(rows,asof,state):
    """An HTTP 200 and a requested date do not establish historical content."""
    issues=Counter()
    for r in rows:
        ipo=r.get('ipoDate');end=r.get('delistingDate')
        try:
            ipo=date.fromisoformat(ipo).isoformat()
        except (ValueError,TypeError):
            issues['missing_or_invalid_ipo_date']+=1;ipo=None
        if ipo and ipo>asof:issues['ipo_after_requested_date']+=1
        if end in ('null','None','','-'):end=None
        if end:
            try:end=date.fromisoformat(end).isoformat()
            except (ValueError,TypeError):
                issues['invalid_delisting_date']+=1;end=None
        if state=='active' and end and end<=asof:issues['delisted_by_requested_date']+=1
        if state=='delisted' and (not end or end>asof):issues['delisting_not_by_requested_date']+=1
        if str(r.get('status','')).lower()!=state:issues['status_mismatch']+=1
    return dict(temporal_consistency_pass=not issues,temporal_issues=dict(issues),
        # Necessary consistency checks are not proof of completeness or a
        # historical stable security ID. Keep those independent gates false.
        historical_universe_verified=False)


def collect_current_universe(capture,end,historical_probe=None):
    sources=[guarded('US_IWB',lambda:collect_iwb(capture,end))]
    sources.extend(guarded('KR_'+board,lambda b=board:collect_kr_board(capture,end,b)) for board in KR_ENDPOINTS)
    members=[m for s in sources if s['status']=='COLLECTED' for m in s['data']['members']]
    ids=[m['market']+':'+m['ticker'] for m in members]
    require(len(ids)==len(set(ids)),'cross_source_duplicate_member')
    probes=[]
    if historical_probe:
        require(historical_probe<end,'historical_probe_date')
        probes.extend(guarded('KR_'+board+'_'+historical_probe,
            lambda b=board:collect_kr_board(capture,historical_probe,b)) for board in KR_ENDPOINTS)
    result=dict(mode='CURRENT_MARKET_INVENTORY',sources=sources,members=members,
        historical_probes=probes,source_coverage_complete=all(s['status']=='COLLECTED' for s in sources),
        historical_selection_allowed=False,continuous_historical_membership_verified=False,
        qualitative_analysis_complete=False,investment_approval=False,
        scope='US IWB equities; KR KOSPI and KOSDAQ share records; no industry whitelist')
    save_private(capture.root/'universe_snapshots.json',canonical(result))
    return result


def summarize_universe(result):
    def summary(source):
        output={k:v for k,v in source.items() if k!='data'}
        if 'data' in source:
            data=source['data'];members=data.get('members',[])
            output['data']={k:v for k,v in data.items() if k not in ('members','receipt','excluded_candidates')}
            output['data']['member_count']=len(members)
            output['data']['no_positive_trade_count']=sum(m.get('has_positive_trade') is False for m in members)
            if 'receipt' in data:output['data']['receipt']=data['receipt']
        return output
    return {**{k:v for k,v in result.items() if k not in ('members','sources','historical_probes','duplicate_issuer_groups')},
        'duplicate_issuer_group_count':len(result.get('duplicate_issuer_groups',[])),
        'member_count':len(result['members']),
        'market_counts':dict(Counter(m['market'] for m in result['members'])),
        'sources':[summary(s) for s in result['sources']],
        'historical_probes':[summary(s) for s in result['historical_probes']]}

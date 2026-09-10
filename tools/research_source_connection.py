#!/usr/bin/env python3
"""Independent source connection for the USD100k fund study.

Raw responses stay in a private directory. Public reports contain coverage,
hashes and explicitly unapproved current financial/price observations only.
No current watchlist is substituted for historical index membership.
"""
from __future__ import annotations
import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

HOSTS = {'data.sec.gov','www.sec.gov','data.alpaca.markets','api.stlouisfed.org',
         'www.alphavantage.co','data-dbg.krx.co.kr','opendart.fss.or.kr','www.ishares.com'}
MAX_BYTES = 24*1024*1024


class SourceFailure(ValueError):
    def __init__(self,reason,diagnostic):
        super().__init__(reason);self.diagnostic=diagnostic


def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def digest_bytes(raw): return hashlib.sha256(raw).hexdigest()
def canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def require(ok, reason):
    if not ok: raise ValueError(reason)


SAFE_REASONS = {'credential_missing','credential_alias_conflict','provider_body_error',
    'listing_csv_schema','listing_empty','issuer_identity','bars_schema','page_limit',
    'repeated_page_token','fred_pagination_required','response_size','source_url',
    'duplicate_or_reverse_bars','bar_value_or_date','raw_adjusted_alignment',
    'krx_rows','krx_date','krx_price','symlink_path','raw_corruption',
    'iwb_identity','iwb_date_missing','iwb_schema','future_membership','iwb_row_schema',
    'duplicate_member','iwb_empty','iwb_coverage_floor','krx_symbol','krx_nonnegative_number',
    'cross_source_duplicate_member','historical_probe_date','us_membership_missing',
    'adr_seed_schema','priority_adr_missing','sec_exchange_schema','duplicate_currency_conflict','us_market_currency'}


def save_private(path, raw):
    path=Path(path)
    require(not any(p.is_symlink() for p in (path,*path.parents)),'symlink_path')
    if path.exists(): require(path.read_bytes()==raw,'raw_corruption')
    else:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as out: out.write(raw)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): raise ValueError('redirect_blocked')


def request_raw(base, params=None, headers=None):
    url=urlsplit(base)
    require(url.scheme=='https' and url.hostname in HOSTS and not url.username and not url.query, 'source_url')
    request=Request(base+('?' + urlencode(params) if params else ''),
        headers={'User-Agent':'R1000Research (contact: andrewcha231@gmail.com)','Accept':'application/json',**(headers or {})})
    with build_opener(NoRedirect()).open(request,timeout=25) as response:
        require(response.status==200,'provider_status')
        raw=response.read(MAX_BYTES+1)
    require(0 < len(raw) <= MAX_BYTES,'response_size')
    return raw


def key(name, alias=None):
    value=os.environ.get(name,'').strip()
    other=os.environ.get(alias,'').strip() if alias else ''
    require(not(value and other and value!=other),'credential_alias_conflict')
    require(bool(value or other),'credential_missing')
    return value or other


class Capture:
    def __init__(self, root):
        self.root=Path(root).absolute()
        require(not any(p.is_symlink() for p in (self.root,*self.root.parents)),'symlink_path')
        self.root.mkdir(parents=True,exist_ok=True)
        self.receipts=[]

    def get(self, name, base, params=None, headers=None, *, json_body=True, validator=None):
        raw=request_raw(base,params,headers)
        # Providers sometimes echo the API key in a JSON error even when CSV
        # was requested. Discard such bodies before writing any file.
        prefix=raw.decode('utf-8-sig').lstrip()
        probe=json.loads(prefix) if json_body or prefix.startswith(('{','[')) else None
        if isinstance(probe,dict):
            require(not any(k in probe for k in ('Error Message','Information','Note','error_message','error')),'provider_body_error')
            require(not ('status' in probe and probe['status'] not in ('000','success','OK','ok')),'provider_body_error')
        value=probe if json_body else raw
        if validator:validator(value)
        sha=digest_bytes(raw)
        path=self.root/(sha+'.raw')
        save_private(path,raw)
        receipt=dict(name=name,source=base,retrieved_at=now(),raw_sha256=sha,bytes=len(raw))
        self.receipts.append(receipt)
        # Request URLs, headers and provider error bodies are never persisted
        # in receipts. Credential-bearing API parameters remain in memory.
        return value,receipt


def guarded(name, fn):
    try: return dict(name=name,status='COLLECTED',data=fn())
    except SourceFailure as exc:return dict(name=name,status='BLOCKED',reason=str(exc),diagnostic=exc.diagnostic)
    except HTTPError as exc:
        # Classify a small known set of provider failures without retaining or
        # printing messages that may echo the request URL and API key.
        detail=exc.read(8192).decode('utf-8',errors='replace').lower()
        category='http_error'
        if 'vintage' in detail and any(x in detail for x in ('maximum','limit','too many')):category='vintage_query_limit'
        elif 'output_type' in detail:category='output_type_contract'
        elif any(x in detail for x in ('invalid api_key','api key is invalid','api_key is not registered')):category='credential_invalid'
        return dict(name=name,status='BLOCKED',reason='HTTP_'+str(exc.code),provider_error_category=category)
    except (URLError,TimeoutError,OSError): return dict(name=name,status='BLOCKED',reason='TRANSPORT_ERROR')
    except (ValueError,TypeError,KeyError,IndexError,csv.Error) as exc:
        reason=str(exc) if type(exc) is ValueError and str(exc) in SAFE_REASONS else 'INPUT_OR_PROVIDER_CONTRACT'
        return dict(name=name,status='BLOCKED',reason=reason)


def collect_bars(capture, start, end, symbols):
    require(symbols and len(symbols)==len(set(symbols)), 'unique_symbols_required')
    auth={'APCA-API-KEY-ID':key('ALPACA_API_KEY'),'APCA-API-SECRET-KEY':key('ALPACA_API_SECRET')}
    all_bars={}; receipts=[]
    for adjustment in ('raw','all'):
        bars={s:[] for s in symbols}
        # Bound each request independently of the size of the candidate pool.
        # Pagination limits apply per batch, never truncate to the first names.
        for offset in range(0,len(symbols),50):
            batch=symbols[offset:offset+50];token=None;seen_tokens=set()
            for page in range(30):
                params=dict(symbols=','.join(batch),timeframe='1Day',start=start+'T00:00:00Z',
                    end=end+'T23:59:59Z',feed='sip',adjustment=adjustment,asof=end,limit=10000,sort='asc')
                if token: params['page_token']=token
                value,receipt=capture.get('alpaca_'+adjustment,'https://data.alpaca.markets/v2/stocks/bars',params,auth)
                require(isinstance(value.get('bars'),dict),'bars_schema')
                require(set(value['bars'])<=set(batch),'unexpected_symbol')
                for symbol,rows in value['bars'].items(): bars[symbol].extend(rows)
                receipts.append(receipt['raw_sha256'])
                token=value.get('next_page_token')
                if not token: break
                require(token not in seen_tokens,'repeated_page_token'); seen_tokens.add(token)
            else: raise ValueError('page_limit')
        for symbol,rows in bars.items():
            dates=[r['t'][:10] for r in rows]
            require(dates==sorted(set(dates)),'duplicate_or_reverse_bars')
            for row in rows:
                require(start<=row['t'][:10]<=end and type(row['c']) in (int,float) and math.isfinite(row['c']) and row['c']>0,'bar_value_or_date')
        all_bars[adjustment]=bars
    output=[]
    for symbol in symbols:
        raw,adjusted=all_bars['raw'][symbol],all_bars['all'][symbol]
        require([r['t'] for r in raw]==[r['t'] for r in adjusted],'raw_adjusted_alignment')
        row=dict(ticker=symbol,rows=len(raw),first=raw[0]['t'][:10] if raw else None,
                 last=raw[-1]['t'][:10] if raw else None,close=raw[-1]['c'] if raw else None,
                 exact_requested_close=bool(raw and raw[-1]['t'][:10]==end),currency='USD')
        if len(adjusted)>240:
            row['returns']={str(n):adjusted[-1]['c']/adjusted[-1-n]['c']-1 for n in (20,60,120,240)}
            row['above_200_session_average']=adjusted[-1]['c']>sum(r['c'] for r in adjusted[-200:])/200
        output.append(row)
    save_private(capture.root/'bars.json',canonical(all_bars))
    return dict(securities=output,raw_response_hashes=receipts,price_basis='raw',
        discovery_basis='provider_adjusted_total_return_proxy',corporate_action_cashflows_verified=False,
        historical_universe_verified=False)


def collect_actions(capture,start,end,symbols):
    auth={'APCA-API-KEY-ID':key('ALPACA_API_KEY'),'APCA-API-SECRET-KEY':key('ALPACA_API_SECRET')}
    actions={};token=None;seen=set();hashes=[]
    for page in range(20):
        params=dict(symbols=','.join(symbols),start=start,end=end,limit=1000,sort='asc')
        if token:params['page_token']=token
        value,receipt=capture.get('alpaca_actions','https://data.alpaca.markets/v1/corporate-actions',params,auth)
        groups=value['corporate_actions'];require(isinstance(groups,dict),'actions_schema')
        for kind,rows in groups.items():
            require(isinstance(rows,list),'actions_schema');actions.setdefault(kind,[]).extend(rows)
        hashes.append(receipt['raw_sha256']);token=value.get('next_page_token')
        if not token:break
        require(token not in seen,'repeated_page_token');seen.add(token)
    else:raise ValueError('page_limit')
    identities=[r['id'] for rows in actions.values() for r in rows]
    require(len(set(identities))==len(identities),'duplicate_action')
    save_private(capture.root/'actions.json',canonical(actions))
    cash_kinds={'cash_dividends','cash_mergers','stock_and_cash_mergers','redemptions'}
    result=[]
    for symbol in symbols:
        selected=[(kind,r) for kind,rows in actions.items() for r in rows
                  if symbol in [r.get(k) for k in ('symbol','old_symbol','source_symbol','acquiree_symbol')]]
        cash=[r for kind,r in selected if kind in cash_kinds]
        result.append(dict(ticker=symbol,actions=len(selected),cash_actions=len(cash),
            cash_payment_dates_missing=sum(not r.get('payable_date') for r in cash),
            original_announcement_times_verified=False))
    return dict(securities=result,counts_by_kind={k:len(v) for k,v in actions.items()},
                raw_response_hashes=hashes,full_action_coverage_verified=False)


def filed_records(facts, tags, end, unit='USD', namespace='us-gaap'):
    for tag in tags:
        group=facts.get('facts',{}).get(namespace,{}).get(tag,{})
        rows=[r for r in group.get('units',{}).get(unit,[]) if r.get('filed','9999')<=end and r.get('end','9999')<=end
              and r.get('form') in ('10-K','10-Q','20-F','40-F','6-K') and type(r.get('val')) in (int,float) and math.isfinite(r['val'])]
        if rows: return tag,rows
    return None,[]


def ttm_from_facts(facts,tags,end,unit='USD',namespace='us-gaap'):
    if len(tags)>1:
        # Evaluate each equivalent mapping independently; never stop at an old
        # tag merely because it has some history, or mix nonmatching periods.
        choices=[ttm_from_facts(facts,[tag],end,unit,namespace) for tag in tags]
        choices=[c for c in choices if c]
        return max(choices,key=lambda c:c['period_end']) if choices else None
    tag,rows=filed_records(facts,tags,end,unit,namespace)
    periods={}
    for row in sorted(rows,key=lambda r:(r['filed'],r.get('accn',''))):
        if row.get('start'): periods[(row['start'],row['end'])]=row
    annual=[r for r in periods.values() if 330<=(date.fromisoformat(r['end'])-date.fromisoformat(r['start'])).days<=380]
    if not annual: return None
    year=max(annual,key=lambda r:(r['end'],r['filed']))
    later=[r for r in periods.values() if r['end']>year['end'] and r['start']>year['end']]
    if not later: components=[year]; value=year['val']; finish=year['end']
    else:
        ytd=max(later,key=lambda r:(r['end'],-date.fromisoformat(r['start']).toordinal()))
        # Require a fiscal YTD immediately after the annual period. A single
        # quarter is not silently treated as year-to-date cash flow.
        if (date.fromisoformat(ytd['start'])-date.fromisoformat(year['end'])).days!=1: return None
        candidates=[r for r in periods.values() if abs((date.fromisoformat(ytd['end'])-date.fromisoformat(r['end'])).days-365)<=8
                    and abs((date.fromisoformat(ytd['start'])-date.fromisoformat(r['start'])).days-365)<=8]
        if len(candidates)!=1: return None
        prior=candidates[0];value=year['val']+ytd['val']-prior['val'];components=[year,ytd,prior];finish=ytd['end']
    if (date.fromisoformat(end)-date.fromisoformat(finish)).days>210:return None
    return dict(value=value,period_end=finish,tag=tag,currency=unit,namespace=namespace,
                components=[{k:r.get(k) for k in ('start','end','filed','accn','val')} for r in components],
                intraday_publication_verified=False,valuation_approved=False)


FOREIGN_REPORTING = {
    'TSM':dict(currency='TWD',namespace='ifrs-full',issuer_country='TW',security_type='ADS',
        source='https://investor.tsmc.com/english/quarterly-results/2026/q2',
        listing_source='https://investor.tsmc.com/english/faq'),
    'ASML':dict(currency='EUR',namespace='us-gaap',issuer_country='NL',security_type='US_REGISTERED_ORDINARY',
        source='https://www.asml.com/en/news/press-releases/2026/q2-2026-financial-results',
        listing_source='https://www.asml.com/en/investors/shares')}


def financial_packet(facts,end,ticker):
    reporting=FOREIGN_REPORTING.get(ticker,dict(currency='USD',namespace='us-gaap'))
    unit,namespace=reporting['currency'],reporting['namespace']
    tags=({'revenue':['Revenue'],'net_income':['ProfitLoss'],
        'operating_cash_flow':['CashFlowsFromUsedInOperatingActivities'],
        'capex':['PurchaseOfPropertyPlantAndEquipment']} if namespace=='ifrs-full' else {
        'revenue':['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet'],
        'net_income':['NetIncomeLoss','ProfitLoss'],
        'operating_cash_flow':['NetCashProvidedByUsedInOperatingActivities'],
        'capex':['PaymentsToAcquirePropertyPlantAndEquipment']})
    metrics={name:ttm_from_facts(facts,choices,end,unit,namespace) for name,choices in tags.items()}
    cfo,capex=metrics['operating_cash_flow'],metrics['capex']
    metrics['free_cash_flow']=(dict(value=cfo['value']-capex['value'],period_end=cfo['period_end'],
        currency=unit,namespace=namespace,valuation_approved=False) if cfo and capex and
        cfo['period_end']==capex['period_end'] and capex['value']>=0 else None)
    # Preserve useful older annual statements without calling them current TTM.
    annual={}
    for name,choices in tags.items():
        candidates=[]
        for tag in choices:
            _,rows=filed_records(facts,[tag],end,unit,namespace)
            candidates.extend({**r,'tag':tag} for r in rows if r.get('start') and
                330<=(date.fromisoformat(r['end'])-date.fromisoformat(r['start'])).days<=380)
        if candidates:
            row=max(candidates,key=lambda r:(r['end'],r['filed'],r.get('accn','')))
            annual[name]={k:row.get(k) for k in ('start','end','filed','accn','val','tag')}
            annual[name].update(currency=unit,namespace=namespace)
    return dict(financial_metrics=metrics,latest_annual_metrics=annual,reporting=reporting,
        trading_currency='USD',native_to_usd_conversion_verified=unit=='USD',
        per_us_security_basis_verified=False,financial_values_are_company_totals=True)


def collect_sec(capture,end,symbols):
    mapping,_=capture.get('sec_tickers','https://www.sec.gov/files/company_tickers.json')
    tickers={r['ticker']:r['cik_str'] for r in mapping.values()}
    summaries=[]
    for ticker in symbols:
        def one():
            cik=str(tickers[ticker]).zfill(10)
            facts,receipt=capture.get('sec_facts_'+ticker,'https://data.sec.gov/api/xbrl/companyfacts/CIK'+cik+'.json')
            filings,fr=capture.get('sec_submissions_'+ticker,'https://data.sec.gov/submissions/CIK'+cik+'.json')
            require(str(facts['cik']).zfill(10)==cik and str(filings['cik']).zfill(10)==cik,'issuer_identity')
            return dict(ticker=ticker,issuer_id='CIK:'+cik,**financial_packet(facts,end,ticker),raw_sha256=receipt['raw_sha256'],
                submissions_sha256=fr['raw_sha256'],older_submission_files=len(filings.get('filings',{}).get('files',[])),
                full_h1_ready=False,quality_review_complete=False)
        summaries.append(guarded(ticker,one));time.sleep(.15)
    return summaries


def collect_fred(capture,start,end):
    output=[]
    for series in ('DGS3MO','DGS2','DGS10','UNRATE'):
        def one():
            # The eight-year daily request returned HTTP 400 in the first real
            # probe. Bound vintage windows, preserving the response versions.
            rows=[];hashes=[]
            for year in range(int(start[:4]),int(end[:4])+1):
                lo=max(start,str(year)+'-01-01');hi=min(end,str(year)+'-12-31')
                value,receipt=capture.get('fred_initial_'+series+'_'+str(year),'https://api.stlouisfed.org/fred/series/observations',
                    dict(series_id=series,file_type='json',api_key=key('FRED_API_KEY'),realtime_start=lo,realtime_end=hi,
                         observation_start=start,observation_end=end,output_type=4,limit=100000))
                part=value['observations'];require(isinstance(part,list),'fred_observations')
                require(int(value.get('count',len(part)))==len(part),'fred_pagination_required')
                rows.extend(part);hashes.append(receipt['raw_sha256'])
            require(rows,'fred_observations')
            rows=sorted({canonical(r):r for r in rows}.values(),key=lambda r:(r['date'],r.get('realtime_start','')))
            usable=[r for r in rows if r.get('value') not in ('.','',None)]
            save_private(capture.root/('fred_'+series+'.json'),canonical(rows))
            return dict(series=series,rows=len(rows),usable_rows=len(usable),first=usable[0]['date'] if usable else None,
                last=usable[-1]['date'] if usable else None,raw_response_hashes=hashes,
                unique_observation_dates=len({r['date'] for r in rows}),
                output_type='initial_release',vintage_dates_present=all('realtime_start' in r and 'realtime_end' in r for r in rows),
                publication_time_mapping_verified=False)
        output.append(guarded(series,one))
    return output


def collect_listing(capture,asof):
    output=[]
    for state in ('active','delisted'):
        def parse(raw):
            reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
            fields=[f.strip() for f in (reader.fieldnames or [])]
            expected={'symbol','ipoDate','delistingDate','status'}
            if not expected<=set(fields):
                known={'symbol','name','exchange','assetType','ipoDate','delistingDate','delistDate','status'}
                lowered=raw[:8192].decode('utf-8',errors='replace').lower()
                category='unrecognized_response'
                for label,phrases in {'quota':('rate limit','call frequency','calls per day'),
                        'subscription':('premium endpoint','premium api','subscription'),
                        'empty_result':('no data found','no records found')}.items():
                    if any(p in lowered for p in phrases):category=label;break
                raise SourceFailure('listing_csv_schema',{'recognized_columns':sorted(set(fields)&known),
                                    'column_count':len(fields),'body_category':category})
            rows=[{k.strip():v for k,v in r.items() if isinstance(k,str)} for r in reader]
            require(rows,'listing_empty')
            return rows
        def one():
            raw,receipt=capture.get('listing_'+state,'https://www.alphavantage.co/query',
                dict(function='LISTING_STATUS',date=asof,state=state,apikey=key('ALPHAVANTAGE_API_KEY','ALPHA_VANTAGE_API_KEY')),json_body=False,validator=parse)
            rows=parse(raw)
            from research_universe_connection import listing_temporal_audit
            return dict(state=state,requested_as_of=asof,rows=len(rows),raw_sha256=receipt['raw_sha256'],
                        russell_membership_verified=False,provider_historical_semantics_documented=True,
                        historical_entity_mapping_verified=False,**listing_temporal_audit(rows,asof,state))
        output.append(guarded(state,one))
    return output


def collect_krx(capture,end,symbols):
    value,receipt=capture.get('krx_close','https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd',
                              {'basDd':end.replace('-','')},{'AUTH_KEY':key('KRX_API_KEY')})
    rows=value['OutBlock_1'];require(isinstance(rows,list) and rows,'krx_rows')
    selected=[]
    for r in rows:
        if str(r.get('ISU_CD')) not in symbols: continue
        require(r.get('BAS_DD')==end.replace('-',''),'krx_date')
        price=float(str(r['TDD_CLSPRC']).replace(',',''))
        require(math.isfinite(price) and price>0,'krx_price')
        selected.append(dict(ticker=r['ISU_CD'],name=r.get('ISU_NM'),close=price,currency='KRW',session=end))
    return dict(rows=len(rows),selected=selected,raw_sha256=receipt['raw_sha256'],historical_price_actions_verified=False)


def run(root,start,end,universe_mode='us_listed',historical_probe=None):
    require(date.fromisoformat(start)<date.fromisoformat(end)<datetime.now(timezone.utc).date(),'completed_date_window')
    require(universe_mode in ('connection_sample','current_markets','us_listed'),'universe_mode')
    from research_universe_connection import collect_current_universe, collect_us_universe, connection_sample
    capture=Capture(root)
    if universe_mode=='connection_sample':
        universe=connection_sample();us=universe['symbols']['US'];kr=universe['symbols']['KR']
        symbols=sorted(set(us+['SPY']))
        results=[guarded('US_prices',lambda:collect_bars(capture,start,end,symbols)),
                 guarded('US_corporate_actions',lambda:collect_actions(capture,start,end,symbols)),
                 guarded('SEC_facts',lambda:collect_sec(capture,end,us)),
                 guarded('macro_initial_releases',lambda:collect_fred(capture,start,end)),
                 guarded('historical_listing_reference',lambda:collect_listing(capture,start)),
                 guarded('KR_current_close',lambda:collect_krx(capture,end,kr))]
    else:
        # Wide discovery must use source membership, never the old thematic
        # sample. Missing a board/source remains visible; no sample fallback.
        universe=(collect_us_universe(capture,end) if universe_mode=='us_listed'
                  else collect_current_universe(capture,end,historical_probe))
        us=[m['ticker'] for m in universe['members'] if m['market']=='US']
        kr=[m for m in universe['members'] if m['market']=='KR']
        results=[guarded('US_prices',lambda:collect_bars(capture,start,end,sorted(set(us+['SPY']))))
                 if us else dict(name='US_prices',status='BLOCKED',reason='us_membership_missing'),
                 dict(name='KR_current_close',status='OUT_OF_SCOPE' if universe_mode=='us_listed' else 'COLLECTED' if kr else 'BLOCKED',
                      data=dict(selected=kr,board_coverage_complete=all(s['status']=='COLLECTED'
                          for s in universe['sources'] if s['name'].startswith('KR_')))),
                 guarded('SEC_facts',lambda:collect_sec(capture,end,[t for t in FOREIGN_REPORTING if t in us]))
                    if universe_mode=='us_listed' else dict(name='SEC_facts',status='NOT_RUN',reason='broad_discovery_before_company_underwriting',data=[]),
                 dict(name='US_corporate_actions',status='NOT_RUN',reason='fund_cashflow_reconciliation_pending'),
                 guarded('historical_listing_reference',lambda:collect_listing(capture,historical_probe or start))]
    report=dict(schema_version='research-source-connection-v1',generated_at=now(),start=start,end=end,
        data_kind='REAL',initial_cash_usd=100000,objective='after_cost_usd_cagr',sources=results,
        collection_scope=universe_mode,universe=universe,requested_investment_start='2019-06-03',
        source_receipt_count=len(capture.receipts),source_receipts_hash=digest_bytes(canonical(capture.receipts)),
        status='SOURCE_CAPTURE_ONLY',backtest_status='BLOCKED',metrics=None,portfolio_weights=None,
        remaining_gates=['historical_investable_universe','publication_timed_normalized_financials',
                         'full_raw_price_action_cashflow_coverage','reviewed_asof_quality_and_scenarios','engine_packet_binding'],
        orders_allowed=False,accepted_state_modified=False)
    if universe_mode=='us_listed':
        report['market_profile']='US_LISTED_USD_V1'
        report['required_priority_candidates']={ticker:ticker in us for ticker in FOREIGN_REPORTING}
    save_private(capture.root/'receipts.json',canonical(capture.receipts))
    save_private(capture.root/'connection_report.json',canonical(report))
    return report


def public_report(report):
    """Keep the full wide-source inventory/quotes private, publish coverage."""
    if report.get('collection_scope') not in ('current_markets','us_listed'):return report
    from research_universe_connection import summarize_universe
    result={**report,'universe':summarize_universe(report['universe']),'sources':[]}
    for source in report['sources']:
        item={**source}
        if source['name']=='US_prices' and 'data' in source:
            data=source['data'];rows=data['securities']
            item['data']={k:v for k,v in data.items() if k!='securities'}
            item['data'].update(security_count=len(rows),bar_count=sum(r['rows'] for r in rows),
                exact_requested_close_count=sum(r['exact_requested_close'] for r in rows),
                rs_240_input_count=sum('returns' in r for r in rows),
                missing_symbol_count=sum(not r['rows'] for r in rows))
            if report.get('market_profile')=='US_LISTED_USD_V1':
                by={r['ticker']:r for r in rows};benchmark=by.get('SPY',{})
                diagnostics={}
                for ticker in FOREIGN_REPORTING:
                    row=by.get(ticker,{})
                    aligned=(row.get('exact_requested_close') and benchmark.get('exact_requested_close') and
                        'returns' in row and 'returns' in benchmark)
                    diagnostics[ticker]=dict(history_sessions=row.get('rows',0),last_session=row.get('last'),
                        above_200_session_average=row.get('above_200_session_average') if aligned else None,
                        excess_return_vs_spy={h:row['returns'][h]-benchmark['returns'][h] for h in ('20','60','120','240')} if aligned else None,
                        method='adjusted_price_return_difference; discovery_only',investment_rank=None)
                item['data']['priority_diagnostics']=diagnostics
        elif source['name']=='KR_current_close' and 'data' in source:
            item['data']={k:v for k,v in source['data'].items() if k!='selected'}
            item['data']['security_count']=len(source['data']['selected'])
        elif source['name']=='SEC_facts' and 'data' in source:
            # Publish diagnostic coverage, not raw financial values or filings.
            item['data']=[{k:v for k,v in row.items() if k!='data'} | (
                dict(data=dict(ticker=row['data']['ticker'],reporting=row['data']['reporting'],
                    ttm_fields_available=[k for k,v in row['data']['financial_metrics'].items() if v is not None],
                    annual_fields_available=list(row['data']['latest_annual_metrics']),
                    annual_period_ends=sorted({v['end'] for v in row['data']['latest_annual_metrics'].values()}),
                    native_to_usd_conversion_verified=row['data']['native_to_usd_conversion_verified'],
                    per_us_security_basis_verified=row['data']['per_us_security_basis_verified']))
                if 'data' in row else {}) for row in source['data']]
        result['sources'].append(item)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--private-dir',required=True)
    p.add_argument('--start',required=True);p.add_argument('--end',required=True);p.add_argument('--report',required=True)
    p.add_argument('--universe-mode',choices=('connection_sample','current_markets','us_listed'),default='us_listed')
    p.add_argument('--historical-probe-date')
    a=p.parse_args();report=public_report(run(a.private_dir,a.start,a.end,a.universe_mode,a.historical_probe_date))
    Path(a.report).parent.mkdir(parents=True,exist_ok=True)
    Path(a.report).write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,sort_keys=True))
    return 0 if any(r['status']=='COLLECTED' for r in report['sources']) else 2


if __name__=='__main__':raise SystemExit(main())

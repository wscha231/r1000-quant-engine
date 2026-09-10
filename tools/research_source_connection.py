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

US = ('NVDA AMD AVGO ANET TSM MU AMAT KLAC LRCX GEV ETN VRT PWR EME FIX NVT CEG VST NEE BE CCJ FCX MTZ FLR').split()
KR = ('000660 005930 267260 010120 298040 034020 052690 009830 000720').split()
HOSTS = {'data.sec.gov','www.sec.gov','data.alpaca.markets','api.stlouisfed.org',
         'www.alphavantage.co','data-dbg.krx.co.kr','opendart.fss.or.kr'}
MAX_BYTES = 24*1024*1024


def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def digest_bytes(raw): return hashlib.sha256(raw).hexdigest()
def canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def require(ok, reason):
    if not ok: raise ValueError(reason)


SAFE_REASONS = {'credential_missing','credential_alias_conflict','provider_body_error',
    'listing_csv_schema','listing_empty','issuer_identity','bars_schema','page_limit',
    'repeated_page_token','fred_pagination_required','response_size','source_url',
    'duplicate_or_reverse_bars','bar_value_or_date','raw_adjusted_alignment',
    'krx_rows','krx_date','krx_price','symlink_path','raw_corruption'}


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

    def get(self, name, base, params=None, headers=None, *, json_body=True):
        raw=request_raw(base,params,headers)
        # Providers sometimes echo the API key in a JSON error even when CSV
        # was requested. Discard such bodies before writing any file.
        probe=json.loads(raw) if json_body or raw.lstrip().startswith((b'{',b'[')) else None
        if isinstance(probe,dict):
            require(not any(k in probe for k in ('Error Message','Information','Note','error_message','error')),'provider_body_error')
            require(not ('status' in probe and probe['status'] not in ('000','success','OK','ok')),'provider_body_error')
        value=probe if json_body else raw
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
    except HTTPError as exc: return dict(name=name,status='BLOCKED',reason='HTTP_'+str(exc.code))
    except (URLError,TimeoutError,OSError): return dict(name=name,status='BLOCKED',reason='TRANSPORT_ERROR')
    except (ValueError,TypeError,KeyError,IndexError,csv.Error) as exc:
        reason=str(exc) if type(exc) is ValueError and str(exc) in SAFE_REASONS else 'INPUT_OR_PROVIDER_CONTRACT'
        return dict(name=name,status='BLOCKED',reason=reason)


def collect_bars(capture, start, end):
    auth={'APCA-API-KEY-ID':key('ALPACA_API_KEY'),'APCA-API-SECRET-KEY':key('ALPACA_API_SECRET')}
    all_bars={}; receipts=[]
    for adjustment in ('raw','all'):
        token=None; seen_tokens=set(); bars={s:[] for s in US+['SPY']}
        for page in range(20):
            params=dict(symbols=','.join(bars),timeframe='1Day',start=start+'T00:00:00Z',
                end=end+'T23:59:59Z',feed='sip',adjustment=adjustment,asof=end,limit=10000,sort='asc')
            if token: params['page_token']=token
            value,receipt=capture.get('alpaca_'+adjustment,'https://data.alpaca.markets/v2/stocks/bars',params,auth)
            require(isinstance(value.get('bars'),dict),'bars_schema')
            require(set(value['bars'])<=set(bars),'unexpected_symbol')
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
    for symbol in US+['SPY']:
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
        watchlist_only=True,historical_universe_verified=False)


def filed_records(facts, tags, end, unit='USD'):
    for tag in tags:
        group=facts.get('facts',{}).get('us-gaap',{}).get(tag,{})
        rows=[r for r in group.get('units',{}).get(unit,[]) if r.get('filed','9999')<=end and r.get('end','9999')<=end
              and r.get('form') in ('10-K','10-Q','20-F','40-F') and type(r.get('val')) in (int,float) and math.isfinite(r['val'])]
        if rows: return tag,rows
    return None,[]


def ttm_from_facts(facts,tags,end):
    tag,rows=filed_records(facts,tags,end)
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
    return dict(value=value,period_end=finish,tag=tag,components=[{k:r.get(k) for k in ('start','end','filed','accn','val')} for r in components],
                intraday_publication_verified=False,valuation_approved=False)


def collect_sec(capture,end):
    mapping,_=capture.get('sec_tickers','https://www.sec.gov/files/company_tickers.json')
    tickers={r['ticker']:r['cik_str'] for r in mapping.values()}
    summaries=[]
    for ticker in US:
        def one():
            cik=str(tickers[ticker]).zfill(10)
            facts,receipt=capture.get('sec_facts_'+ticker,'https://data.sec.gov/api/xbrl/companyfacts/CIK'+cik+'.json')
            filings,fr=capture.get('sec_submissions_'+ticker,'https://data.sec.gov/submissions/CIK'+cik+'.json')
            require(str(facts['cik']).zfill(10)==cik and str(filings['cik']).zfill(10)==cik,'issuer_identity')
            metrics={name:ttm_from_facts(facts,tags,end) for name,tags in {
                'revenue':['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet'],
                'net_income':['NetIncomeLoss','ProfitLoss'],
                'operating_cash_flow':['NetCashProvidedByUsedInOperatingActivities'],
                'capex':['PaymentsToAcquirePropertyPlantAndEquipment']}.items()}
            cfo,capex=metrics['operating_cash_flow'],metrics['capex']
            metrics['free_cash_flow']=dict(value=cfo['value']-capex['value'],period_end=cfo['period_end']) if cfo and capex and cfo['period_end']==capex['period_end'] else None
            return dict(ticker=ticker,financial_metrics=metrics,raw_sha256=receipt['raw_sha256'],
                submissions_sha256=fr['raw_sha256'],older_submission_files=len(filings.get('filings',{}).get('files',[])),
                full_h1_ready=False,quality_review_complete=False)
        summaries.append(guarded(ticker,one));time.sleep(.15)
    return summaries


def collect_fred(capture,start,end):
    output=[]
    for series in ('DGS3MO','DGS2','DGS10','UNRATE'):
        def one():
            value,receipt=capture.get('fred_initial_'+series,'https://api.stlouisfed.org/fred/series/observations',
                dict(series_id=series,file_type='json',api_key=key('FRED_API_KEY'),realtime_start=start,realtime_end=end,
                     observation_start=start,observation_end=end,output_type=4,limit=100000))
            rows=value['observations'];require(isinstance(rows,list) and rows,'fred_observations')
            require(int(value.get('count',len(rows)))==len(rows),'fred_pagination_required')
            usable=[r for r in rows if r.get('value') not in ('.','',None)]
            return dict(series=series,rows=len(rows),usable_rows=len(usable),first=usable[0]['date'] if usable else None,
                last=usable[-1]['date'] if usable else None,raw_sha256=receipt['raw_sha256'],
                output_type='initial_release',vintage_dates_present=all('realtime_start' in r and 'realtime_end' in r for r in rows),
                publication_time_mapping_verified=False)
        output.append(guarded(series,one))
    return output


def collect_listing(capture,asof):
    output=[]
    for state in ('active','delisted'):
        raw,receipt=capture.get('listing_'+state,'https://www.alphavantage.co/query',
            dict(function='LISTING_STATUS',date=asof,state=state,apikey=key('ALPHAVANTAGE_API_KEY','ALPHA_VANTAGE_API_KEY')),json_body=False)
        reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        require(reader.fieldnames and {'symbol','ipoDate','delistingDate','status'}<=set(reader.fieldnames),'listing_csv_schema')
        rows=list(reader);require(rows,'listing_empty')
        output.append(dict(state=state,requested_as_of=asof,rows=len(rows),raw_sha256=receipt['raw_sha256'],
                           russell_membership_verified=False,provider_historical_semantics_documented=True,
                           historical_entity_mapping_verified=False))
    return output


def collect_krx(capture,end):
    value,receipt=capture.get('krx_close','https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd',
                              {'basDd':end.replace('-','')},{'AUTH_KEY':key('KRX_API_KEY')})
    rows=value['OutBlock_1'];require(isinstance(rows,list) and rows,'krx_rows')
    selected=[]
    for r in rows:
        if str(r.get('ISU_CD')) not in KR: continue
        require(r.get('BAS_DD')==end.replace('-',''),'krx_date')
        price=float(str(r['TDD_CLSPRC']).replace(',',''))
        require(math.isfinite(price) and price>0,'krx_price')
        selected.append(dict(ticker=r['ISU_CD'],name=r.get('ISU_NM'),close=price,currency='KRW',session=end))
    return dict(rows=len(rows),selected=selected,raw_sha256=receipt['raw_sha256'],historical_price_actions_verified=False)


def run(root,start,end):
    require(date.fromisoformat(start)<date.fromisoformat(end)<datetime.now(timezone.utc).date(),'completed_date_window')
    capture=Capture(root)
    results=[guarded('US_prices',lambda:collect_bars(capture,start,end)),
             guarded('SEC_facts',lambda:collect_sec(capture,end)),
             guarded('macro_initial_releases',lambda:collect_fred(capture,start,end)),
             guarded('historical_listing_reference',lambda:collect_listing(capture,start)),
             guarded('KR_current_close',lambda:collect_krx(capture,end))]
    report=dict(schema_version='research-source-connection-v1',generated_at=now(),start=start,end=end,
        data_kind='REAL',initial_cash_usd=100000,objective='after_cost_usd_cagr',sources=results,
        source_receipt_count=len(capture.receipts),source_receipts_hash=digest_bytes(canonical(capture.receipts)),
        status='SOURCE_CAPTURE_ONLY',backtest_status='BLOCKED',metrics=None,portfolio_weights=None,
        remaining_gates=['historical_investable_universe','publication_timed_normalized_financials',
                         'full_raw_price_action_cashflow_coverage','reviewed_asof_quality_and_scenarios','engine_packet_binding'],
        orders_allowed=False,accepted_state_modified=False)
    save_private(capture.root/'receipts.json',canonical(capture.receipts))
    save_private(capture.root/'connection_report.json',canonical(report))
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--private-dir',required=True)
    p.add_argument('--start',default='2019-05-09');p.add_argument('--end',required=True);p.add_argument('--report',required=True)
    a=p.parse_args();report=run(a.private_dir,a.start,a.end)
    Path(a.report).parent.mkdir(parents=True,exist_ok=True)
    Path(a.report).write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,sort_keys=True))
    return 0 if any(r['status']=='COLLECTED' for r in report['sources']) else 2


if __name__=='__main__':raise SystemExit(main())

#!/usr/bin/env python3
"""Partitioned, append-only research history. No target, ledger or trading writes.

Reuse the bounded FRED parser and verified Drive transport from macro research.
Batch content-addressed objects in small packs to avoid thousands of Drive calls.
Only a hash-verified catalog commit exposes new data to consumers. Source failures
remain explicit even when an older version is retained. Never certify current
SEC companyfacts or revised macro histories as historical point-in-time truth.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import date, datetime, timedelta, timezone
import gzip
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.macro_history_sources import (NoRedirect, digest, encoded, exclusive,
    fetch as fetch_fred, parse_alfred, parse_graph, registry, require, utc_now)
from tools.macro_research_checkpoint import LocalTransport, RcloneTransport, relative

SCHEMA = 'long-history-catalog-v1'
PREFIX = 'long-history-v1'
MAX_OBJECT = 18 * 1024 * 1024
PACK_BYTES = 18 * 1024 * 1024
COHORT_SHA = '4e1eb090f8137395603228dbc55c35907307ad6d049ec778f2722d1cbb87f4b4'
ARCHIVES = ('UNRATE','PAYEMS','CPIAUCSL','PCEPILFE','RSAFS','DSPIC96','PSAVERT','M2SL','ICSA','NFCI','WALCL','WRESBAL')
COUNTRIES = ('USA','CHN','JPN','KOR','EMU')
WB_INDICATORS = ('NY.GDP.MKTP.KD.ZG','FP.CPI.TOTL.ZG','SP.POP.TOTL','SP.POP.65UP.TO.ZS')
FORMS = {'10-K','10-K/A','10-Q','10-Q/A','20-F','20-F/A','40-F','40-F/A','6-K','6-K/A'}
_LOCK = threading.Lock()
_LAST = 0.0


def packed(raw):
    return gzip.compress(raw, compresslevel=6, mtime=0)


def unpacked(raw):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as handle:
        result = handle.read(128 * 1024 * 1024 + 1)
    require(len(result) <= 128 * 1024 * 1024, 'decompressed_size')
    return result


def get_public(url, conditional=None):
    """Bounded retry, conditional GET; no response bodies or secret URLs in logs."""
    global _LAST
    host = urlsplit(url).hostname
    require(urlsplit(url).scheme == 'https' and host in
        {'www.sec.gov','data.sec.gov','api.worldbank.org'}, 'source_host')
    headers = {'User-Agent':'R1000Research andrewcha231@gmail.com','Accept':'application/json'}
    if conditional:
        if conditional.get('etag'):
            headers['If-None-Match'] = conditional['etag']
        if conditional.get('last_modified'):
            headers['If-Modified-Since'] = conditional['last_modified']
    for attempt in range(3):
        if host.endswith('sec.gov'):
            with _LOCK:
                time.sleep(max(0, .28 - (time.monotonic() - _LAST)))
                _LAST = time.monotonic()
        try:
            with build_opener(NoRedirect()).open(Request(url,headers=headers),timeout=30) as response:
                raw = response.read(32*1024*1024+1)
                metadata = {'etag':response.headers.get('ETag'),
                    'last_modified':response.headers.get('Last-Modified')}
            require(0 < len(raw) <= 32*1024*1024, 'source_size')
            return raw, metadata
        except HTTPError as exc:
            if exc.code == 304 and conditional:
                return None, conditional
            if exc.code in (429,500,502,503,504) and attempt < 2:
                time.sleep(2**attempt)
                continue
            raise ValueError('HTTP_'+str(exc.code)) from None
        except (URLError, TimeoutError, OSError):
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise ValueError('TRANSPORT_ERROR') from None
    raise ValueError('REQUEST_EXHAUSTED')


def sec_rows(raw, cik, start, through):
    """All available statement concepts/units/forms, including distinct revisions.

    Do not sum fiscal YTD and quarterly rows, infer missing quarters, convert
    currencies, apply current shares to ADRs, or collapse amended filings.
    """
    payload = json.loads(raw)
    require(str(payload.get('cik','')).zfill(10) == cik, 'issuer_identity')
    require(isinstance(payload.get('facts'),dict), 'facts_schema')
    rows, seen, rejected = [], {}, 0
    for namespace, concepts in payload['facts'].items():
        if namespace not in ('us-gaap','ifrs-full','dei'):
            continue
        for concept, fact in concepts.items():
            for unit, entries in fact.get('units',{}).items():
                for r in entries:
                    if r.get('form') not in FORMS:
                        continue
                    try:
                        end = date.fromisoformat(r['end'])
                        filed = date.fromisoformat(r['filed'])
                        begin = date.fromisoformat(r['start']) if r.get('start') else None
                        require(begin is None or begin <= end, 'period_order')
                        value = r['val']
                        require(type(value) in (int,float) and math.isfinite(value), 'finite_fact')
                        require(bool(re.fullmatch(r'\d{10}-\d{2}-\d{6}',r['accn'])), 'accession')
                    except (KeyError,TypeError,ValueError):
                        rejected += 1
                        continue
                    if end.isoformat() < start or end.isoformat() > through or filed.isoformat() > through:
                        continue
                    identity = (namespace,concept,unit,r.get('start'),r['end'],r['filed'],r['accn'],r['form'])
                    require(identity not in seen or seen[identity] == value, 'conflicting_fact_version')
                    if identity in seen:
                        continue
                    seen[identity] = value
                    rows.append(dict(cik=cik,namespace=namespace,concept=concept,unit=unit,
                        start=r.get('start'),end=r['end'],filed=r['filed'],accession=r['accn'],
                        form=r['form'],value=value,fy=r.get('fy'),fp=r.get('fp'),frame=r.get('frame'),
                        duration_days=(end-begin).days+1 if begin else None,
                        evidence='SEC_FILED_DATE_CURRENT_ARCHIVE_NOT_CERTIFIED_PIT'))
    rows.sort(key=lambda r:(r['end'],r['filed'],r['namespace'],r['concept'],r['unit'],r['accession'],r['start'] or ''))
    return rows, rejected


def fact_coverage(rows, start, through):
    years = sorted({int(r['end'][:4]) for r in rows})
    annual = sorted({int(r['end'][:4]) for r in rows if r['duration_days'] and 330 <= r['duration_days'] <= 400})
    # Presence of some concepts is NOT three-statement or per-quarter completeness.
    return dict(rows=len(rows),earliest=min((r['end'] for r in rows),default=None),
        latest=max((r['end'] for r in rows),default=None),years_with_any_facts=years,
        annual_period_end_years=annual,
        missing_years=[y for y in range(int(start[:4]),int(through[:4])) if y not in years],
        statement_completeness='NOT_CERTIFIED',quarter_completeness='NOT_CERTIFIED',
        currencies_and_units=sorted({r['unit'] for r in rows}),
        last_filed=max((r['filed'] for r in rows),default=None))


def issuer_queue(members, mapping):
    require(isinstance(members,list) and len(members)>=1000,'cohort_below_1000')
    symbols = [r['ticker'] for r in members]
    require(len(symbols)==len(set(symbols)), 'duplicate_security')
    lookup = {}
    for r in mapping.values():
        key = r['ticker'].upper().replace('.','-')
        cik = str(r['cik_str']).zfill(10)
        require(re.fullmatch(r'\d{10}',cik), 'cik_identity')
        lookup.setdefault(key,set()).add(cik)
    groups, missing = {}, []
    for symbol in symbols:
        require(isinstance(symbol,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,14}',symbol),'ticker_identity')
        matches = lookup.get(symbol.upper().replace('.','-'),set())
        if len(matches)==1:
            groups.setdefault(next(iter(matches)),[]).append(symbol)
        else:
            missing.append(dict(ticker=symbol,reason='CIK_MISSING_OR_AMBIGUOUS'))
    return groups, missing


def wb_rows(raw, indicator, start, through, retrieved):
    payload = json.loads(raw)
    require(isinstance(payload,list) and len(payload)==2,'worldbank_schema')
    meta, data = payload
    require(meta.get('pages')==1 and int(meta.get('total',-1))==len(data),'worldbank_pagination')
    rows, seen = [], set()
    for r in data:
        require(r['indicator']['id']==indicator and r['countryiso3code'] in COUNTRIES,'worldbank_identity')
        year = int(r['date'])
        require(int(start[:4])<=year<=int(through[:4]),'worldbank_period')
        key=(r['countryiso3code'],year)
        require(key not in seen,'worldbank_duplicate'); seen.add(key)
        value = r['value']
        require(value is None or (type(value) in (int,float) and math.isfinite(value)),'worldbank_value')
        rows.append(dict(country=key[0],series=indicator,observation_date=f'{year}-01-01',
            value=value,available_at=retrieved,evidence='current_only',published_at=None))
    require(rows,'worldbank_empty')
    return sorted(rows,key=lambda r:(r['country'],r['observation_date']))


def safe_error(exc):
    text = str(exc)
    return text if re.fullmatch(r'[A-Za-z0-9_]{1,90}',text) else 'SOURCE_OR_CONTRACT_ERROR'


class Lake:
    """Catalog chain and small immutable pack objects, independent of paper state."""
    def __init__(self, transport, workspace):
        self.transport=transport
        self.workspace=Path(workspace)
        self.workspace.mkdir(parents=True,exist_ok=True)
        self.pending={}
        self._pack_cache=(None,None)
        self.parent,self.catalog=self.restore_catalog()
        self.before=copy.deepcopy(self.catalog)

    def read_hash(self, folder, sha):
        require(re.fullmatch(r'[a-f0-9]{64}',sha),'hash_identity')
        raw=self.transport.read(f'{PREFIX}/{folder}/{sha}')
        require(digest(raw)==sha,'remote_hash')
        return raw

    def restore_catalog(self):
        names=self.transport.names(f'{PREFIX}/commits')
        require(len(names)==len(set(names)) and len(names)<=20000,'commit_inventory')
        entries={n:json.loads(self.read_hash('commits',n)) for n in names}
        parent=None; generation=0; last=None
        while entries:
            following=[(s,v) for s,v in entries.items() if v.get('parent')==parent]
            require(len(following)==1,'catalog_fork_or_broken_chain')
            parent,last=following[0]
            generation+=1
            require(last.get('generation')==generation and last.get('schema')=='long-history-commit-v1','commit_schema')
            del entries[parent]
        if last is None:
            return None,dict(schema=SCHEMA,generation=0,datasets={},locations={},eligible_for_selector=False)
        catalog=json.loads(self.read_hash('catalogs',last['catalog']))
        require(catalog.get('schema')==SCHEMA and catalog.get('generation')==generation,'catalog_schema')
        require(catalog.get('eligible_for_selector') is False,'research_only')
        for dataset in catalog['datasets'].values():
            for obj in dataset.get('objects',[]):
                require(obj in catalog['locations'],'catalog_dependency')
        return parent,catalog

    def object(self, raw):
        require(0<len(raw)<=MAX_OBJECT,'object_size')
        sha=digest(raw)
        if sha not in self.catalog['locations']:
            path=self.workspace/'objects'/sha
            exclusive(path,raw)
            self.pending[sha]=path
        return sha

    def dataset(self,key,pages,rows,metadata):
        raw_hashes=[self.object(packed(p)) for p in pages]
        normalized=self.object(packed(b''.join(encoded(r) for r in rows)))
        old=self.catalog['datasets'].get(key,{})
        self.catalog['datasets'][key]=dict(metadata,status='COLLECTED',objects=raw_hashes+[normalized],
            raw_objects=raw_hashes,normalized=normalized,encoding='gzip_jsonl',
            changed=old.get('objects')!=raw_hashes+[normalized],checked_at=utc_now())

    def blocked(self,key,exc):
        old=self.catalog['datasets'].get(key,{})
        self.catalog['datasets'][key]=dict(old,status='STALE_RETAINED' if old.get('objects') else 'BLOCKED',
            last_failure=safe_error(exc),checked_at=utc_now())

    def get_bytes(self,sha):
        if sha in self.pending:
            raw=self.pending[sha].read_bytes()
        else:
            pack_id=self.catalog['locations'][sha]
            if self._pack_cache[0]!=pack_id:
                self._pack_cache=(pack_id,self.read_hash('packs',pack_id))
            pack=self._pack_cache[1]
            with zipfile.ZipFile(io.BytesIO(pack)) as z:
                info=z.getinfo(sha)
                require(info.file_size<=MAX_OBJECT,'pack_member_size')
                raw=z.read(info)
            require(digest(raw)==sha,'object_hash')
        return raw

    def get_records(self,key):
        raw=self.get_bytes(self.catalog['datasets'][key]['normalized'])
        return [json.loads(line) for line in unpacked(raw).splitlines()]

    def publish(self,run_id,config):
        require(re.fullmatch('[A-Za-z0-9_-]{1,100}',run_id),'run_id')
        require(self.restore_catalog()[0]==self.parent,'stale_writer')
        groups=[]; current=[]; size=0
        for sha,path in sorted(self.pending.items()):
            n=path.stat().st_size
            if current and size+n>PACK_BYTES:
                groups.append(current); current=[]; size=0
            current.append((sha,path)); size+=n
        if current: groups.append(current)
        verified_bytes=0
        for i,group in enumerate(groups):
            output=io.BytesIO()
            with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as z:
                for sha,path in group:
                    info=zipfile.ZipInfo(sha,date_time=(1980,1,1,0,0,0))
                    z.writestr(info,path.read_bytes())
            raw=output.getvalue()
            require(len(raw)<20*1024*1024,'pack_size')
            pack_sha=digest(raw)
            self.transport.write(f'{PREFIX}/packs/{pack_sha}',raw)
            restored=self.read_hash('packs',pack_sha)
            with zipfile.ZipFile(io.BytesIO(restored)) as z:
                require(set(z.namelist())=={sha for sha,_ in group},'pack_inventory')
                for sha,_ in group:
                    require(digest(z.read(sha))==sha,'pack_object_hash')
                    self.catalog['locations'][sha]=pack_sha
            verified_bytes+=len(raw)
            print(json.dumps(dict(phase='PACK_VERIFIED',pack=i+1,total=len(groups))),flush=True)
        self.catalog.update(generation=self.catalog['generation']+1,run_id=run_id,created_at=utc_now(),
            config=config,config_sha256=digest(encoded(config)),code_sha=os.environ.get('GITHUB_SHA'),
            eligible_for_selector=False,fullrun_executed=False)
        raw=encoded(self.catalog); catalog_sha=digest(raw)
        require(len(raw)<=MAX_OBJECT,'catalog_size')
        self.transport.write(f'{PREFIX}/catalogs/{catalog_sha}',raw)
        require(self.read_hash('catalogs',catalog_sha)==raw,'catalog_roundtrip')
        require(self.restore_catalog()[0]==self.parent,'stale_writer')
        commit=dict(schema='long-history-commit-v1',parent=self.parent,catalog=catalog_sha,
            generation=self.catalog['generation'],run_id=run_id,created_at=utc_now())
        commit_raw=encoded(commit); commit_sha=digest(commit_raw)
        self.transport.write(f'{PREFIX}/commits/{commit_sha}',commit_raw)
        require(self.restore_catalog()[0]==commit_sha,'publication_conflict')
        return dict(commit_sha256=commit_sha,catalog_sha256=catalog_sha,
            new_packs=len(groups),verified_new_bytes=verified_bytes,
            remote_verified=self.transport.remote_verified,eligible_for_selector=False)


def collect_financials(lake,cohort,start,through):
    raw=Path(cohort).read_bytes()
    require(digest(raw)==COHORT_SHA,'cohort_hash')
    payload=json.loads(raw)
    members=payload['rows']
    require(payload['candidate_count']==len(members) and payload['as_of']<=through,'cohort_identity')
    mapping_raw,_=get_public('https://www.sec.gov/files/company_tickers.json')
    groups,missing=issuer_queue(members,json.loads(mapping_raw))
    lake.dataset('universe/cohort',[raw,mapping_raw],members,dict(evidence='CURRENT_COHORT_NOT_HISTORICAL_MEMBERSHIP',
        rows=len(members),requested_securities=len(members),mapped_issuers=len(groups),missing=missing))
    def one(item):
        cik,symbols=item; key='sec/'+cik
        old=lake.catalog['datasets'].get(key,{})
        try:
            # An older restored object can only be reused for the same extraction
            # floor/schema. A changed window forces a full response.
            conditional=old.get('http') if old.get('start')==start else None
            data,http=get_public(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json',conditional)
            if data is None:
                require(old.get('objects') and old.get('normalized'),'304_without_prior')
                return key,None,None,dict(old,status='UNCHANGED',changed=False,checked_at=utc_now())
            rows,rejected=sec_rows(data,cik,start,through)
            require(rows,'NO_FACTS_IN_WINDOW')
            metadata=dict(cik=cik,tickers=symbols,start=start,through=through,http=http,
                retrieved_at=utc_now(),evidence='SEC_FILED_DATE_CURRENT_ARCHIVE_NOT_CERTIFIED_PIT',
                rejected_rows=rejected,**fact_coverage(rows,start,through))
            return key,[data],rows,metadata
        except (ValueError,KeyError,TypeError,OSError) as exc:
            return key,None,None,exc
    for count,(key,pages,rows,result) in enumerate(ThreadPoolExecutor(max_workers=6).map(one,sorted(groups.items())),1):
        if isinstance(result,Exception): lake.blocked(key,result)
        elif pages is None: lake.catalog['datasets'][key]=result
        else: lake.dataset(key,pages,rows,result)
        if count%100==0: print(json.dumps(dict(phase='SEC_COLLECTED',issuers=count,total=len(groups))),flush=True)
    return dict(requested_securities=len(members),mapped_issuers=len(groups),missing=missing)


def collect_macros(lake,start,through):
    for spec in registry()['series']:
        sid=spec['id']
        for mode in (['current','alfred'] if sid in ARCHIVES else ['current']):
            key=f'{mode}/{sid}'
            try:
                pages,retrieved=fetch_fred(sid,start,through,mode)
                if mode=='current': rows,missing=parse_graph(pages[0],sid,start,through,retrieved)
                else: rows=parse_alfred(pages,sid,start,through,retrieved)
                # Retrieval belongs to the version receipt, not every unchanged row.
                clean=[{k:v for k,v in r.items() if k!='retrieved_at'} for r in rows]
                if mode=='current':
                    for r in clean: r.pop('available_at',None)
                lake.dataset(key,pages,clean,dict(series=sid,frequency=spec['frequency'],group=spec['group'],unit=spec['unit'],
                    rows=len(rows),earliest=min(r['observation_date'] for r in rows),
                    latest=max(r['observation_date'] for r in rows if r['value'] is not None),retrieved_at=retrieved,
                    evidence='alfred_date_archive' if mode=='alfred' else 'current_only',
                    requested_start=start,requested_through=through,raw_redistribution=spec['raw_redistribution']))
            except Exception as exc: lake.blocked(key,exc)
    for indicator in WB_INDICATORS:
        key='worldbank/'+indicator
        try:
            url='https://api.worldbank.org/v2/country/'+';'.join(COUNTRIES)+'/indicator/'+indicator+'?'+urlencode(
                dict(format='json',date=start[:4]+':'+through[:4],per_page=20000))
            pages,_=get_public(url); retrieved=utc_now()
            rows=wb_rows(pages,indicator,start,through,retrieved)
            for r in rows: r.pop('available_at',None)
            lake.dataset(key,[pages],rows,dict(rows=len(rows),evidence='current_only',retrieved_at=retrieved,
                earliest=min(r['observation_date'] for r in rows if r['value'] is not None),latest=max(r['observation_date'] for r in rows if r['value'] is not None),
                countries=list(COUNTRIES),indicator=indicator,frequency='annual',
                requested_start=start,requested_through=through))
        except Exception as exc: lake.blocked(key,exc)


def diagnostics(lake):
    datasets=lake.catalog['datasets']; sec=[d for k,d in datasets.items() if k.startswith('sec/')]
    macro={k:d for k,d in datasets.items() if k.startswith(('current/','alfred/','worldbank/'))}
    counts={s:sum(d['status']==s for d in datasets.values()) for s in ('COLLECTED','UNCHANGED','STALE_RETAINED','BLOCKED')}
    return dict(schema='long-history-quality-v1',as_of=utc_now(),status='PARTIAL' if counts['BLOCKED'] or counts['STALE_RETAINED'] else 'COLLECTED_NOT_PIT_CERTIFIED',
        status_counts=counts,financial_issuers=len(sec),financial_fact_rows=sum(d.get('rows',0) for d in sec),
        financial_issuers_collected=sum(d['status'] in ('COLLECTED','UNCHANGED') for d in sec),
        issuers_with_ten_calendar_years=sum(len(d.get('years_with_any_facts',[]))>=10 for d in sec),
        three_statement_ten_year_completeness='NOT_CERTIFIED',
        macro_coverage={k:{f:d.get(f) for f in ('status','rows','earliest','latest','evidence','last_failure')} for k,d in macro.items()},
        universe=datasets.get('universe/cohort',{}),eligible_for_selector=False,weights_activated=False,
        historical_membership_verified=False,historical_pit_certified=False,
        provider_failures={k:d.get('last_failure') for k,d in datasets.items() if d['status'] in ('BLOCKED','STALE_RETAINED')})


def materialize(lake,destination,keys,cutoff):
    """Rebuildable SQL cache from pinned, verified versions. No PIT relabelling."""
    require(not Path(destination).exists(),'database_already_exists')
    conn=sqlite3.connect(destination)
    conn.execute('create table records(dataset text, observation_date text, filed_date text, concept text, unit text, value real, evidence text, payload text)')
    conn.execute('create table provenance(catalog_generation integer, cutoff text, historical_pit_certified integer)')
    conn.execute('insert into provenance values(?,?,0)',(lake.catalog['generation'],cutoff))
    count=0
    with conn:
        for key in keys:
            entry=lake.catalog['datasets'][key]
            require(entry['status'] in ('COLLECTED','UNCHANGED'),'stale_dataset')
            require(entry.get('evidence')!='current_only' or cutoff>=entry['retrieved_at'][:10],
                    'current_vintage_historical_cutoff_forbidden')
            for row in lake.get_records(key):
                observed=row.get('observation_date',row.get('end'))
                if observed and observed>cutoff: continue
                if row.get('filed') and row['filed']>cutoff: continue
                if row.get('available_at') and row['available_at'][:10]>cutoff: continue
                conn.execute('insert into records values(?,?,?,?,?,?,?,?)',(key,observed,row.get('filed'),row.get('concept',row.get('series')),row.get('unit'),row.get('value'),row.get('evidence',entry['evidence']),json.dumps(row)))
                count+=1
        conn.execute('create index lookup on records(dataset,observation_date,filed_date)')
    conn.close()
    return count


def analyze_restored(lake, root, start, through):
    """Run the existing fixed study on a freshly restored catalog's real bytes."""
    from tools.macro_technical_study import study
    from tools.macro_research_cycle import CURRENT, engine_context
    from tools.macro_history_sources import REGISTRY
    store=Path(root)/'store'
    registry_raw=REGISTRY.read_bytes()
    exclusive(store/'registries'/(digest(registry_raw)+'.json'),registry_raw)
    receipts=[]
    for mode,ids in [('current',CURRENT),('alfred',['UNRATE','PAYEMS','CPIAUCSL'])]:
        sources=[]
        for sid in ids:
            entry=lake.catalog['datasets'][mode+'/'+sid]
            require(entry['status'] in ('COLLECTED','UNCHANGED'),'study_required_source_blocked')
            raw_pages=[unpacked(lake.get_bytes(sha)) for sha in entry['raw_objects']]
            retrieved=entry['retrieved_at']
            if mode=='current': rows,_=parse_graph(raw_pages[0],sid,start,through,retrieved)
            else: rows=parse_alfred(raw_pages,sid,start,through,retrieved)
            raw_hashes=[]
            for raw in raw_pages:
                sha=digest(raw); exclusive(store/'objects'/sha,raw); raw_hashes.append(sha)
            normalized=encoded(rows); sha=digest(normalized)
            exclusive(store/'objects'/sha,normalized)
            sources.append(dict(series=sid,status='COLLECTED',records_sha256=sha,raw_sha256=raw_hashes,
                earliest=entry['earliest'],latest=entry['latest'],retrieved_at=retrieved,evidence=entry['evidence']))
        receipt=dict(schema='macro-history-bundle-v1',mode=mode,requested_start=start,
            requested_through=through,created_at=utc_now(),registry_sha256=digest(registry_raw),
            sources=sources,durable_remote_verified=True,historical_price_pit_verified=False)
        raw=encoded(receipt); path=store/'receipts'/(digest(raw)+'.json')
        exclusive(path,raw); receipts.append(path)
    result=study(store,receipts[0],utc_now(),[receipts[1]])
    result['durable_remote_verified']=lake.transport.remote_verified
    result['long_history_catalog_generation']=lake.catalog['generation']
    return result,engine_context(result)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--remote',required=True)
    p.add_argument('--workspace',required=True)
    p.add_argument('--cohort',required=True)
    p.add_argument('--run-id',required=True)
    p.add_argument('--report-dir',required=True)
    p.add_argument('--macro-start',default='1996-01-01')
    p.add_argument('--financial-start',default='2016-01-01')
    args=p.parse_args()
    reports=Path(args.report_dir); reports.mkdir(parents=True,exist_ok=True)
    # A separate local temp root avoids concurrent collection touching a previous
    # verified source bundle. Network destination is the configured research lane.
    transport=RcloneTransport(args.remote)
    transport.call('mkdir',transport.path(f'{PREFIX}/commits'))
    lake=Lake(transport,args.workspace)
    through=date.today().isoformat()
    config=dict(macro_start=args.macro_start,financial_start=args.financial_start,through=through,
        cohort_sha256=COHORT_SHA,archives=list(ARCHIVES),countries=list(COUNTRIES),
        worldbank_indicators=list(WB_INDICATORS),registry_sha256=digest(encoded(registry())))
    collect_macros(lake,args.macro_start,through)
    collect_financials(lake,args.cohort,args.financial_start,through)
    report=diagnostics(lake)
    (reports/'quality.json').write_bytes(encoded(report))
    result=lake.publish(args.run_id,config)
    # Exercise the consumer with every macro dataset that passed. Full financial
    # SQL materialization is available on demand; no repeated multi-GB restore.
    keys=[k for k,d in lake.catalog['datasets'].items() if k.startswith(('current/','alfred/','worldbank/')) and d['status'] in ('COLLECTED','UNCHANGED')]
    consumer=Lake(transport,Path(args.workspace)/'clean-consumer')
    consumer_rows=materialize(consumer,Path(args.workspace)/'macro.sqlite',keys,through)
    try:
        study_result,context=analyze_restored(consumer,Path(args.workspace)/'study',args.macro_start,through)
        context['catalog_sha256']=result['catalog_sha256']
        (reports/'macro-evaluation.json').write_bytes(encoded(study_result))
        (reports/'engine-context.json').write_bytes(encoded(context))
        result.update(study_recomputed_from_drive=True,study_tests=study_result['tests_declared'])
    except (ValueError,KeyError,TypeError,OSError) as exc:
        result.update(study_recomputed_from_drive=False,study_blocked_reason=safe_error(exc))
    result.update(consumer_rows=consumer_rows,consumer='VERIFIED_SQL_RESEARCH_CACHE',quality_status=report['status'])
    durable_reports={}
    for path in sorted(reports.glob('*.json')):
        raw=path.read_bytes(); sha=digest(raw)
        require(len(raw)<=MAX_OBJECT,'report_size')
        transport.write(f'{PREFIX}/reports/{sha}',raw)
        durable_reports[path.name]=sha
    receipt=dict(schema='long-history-execution-v1',run_id=args.run_id,created_at=utc_now(),
        catalog_sha256=result['catalog_sha256'],commit_sha256=result['commit_sha256'],
        reports=durable_reports,consumer_rows=consumer_rows,
        study_recomputed_from_drive=result['study_recomputed_from_drive'],
        quality_status=report['status'],eligible_for_selector=False)
    raw=encoded(receipt); receipt_sha=digest(raw)
    transport.write(f'{PREFIX}/executions/{receipt_sha}',raw)
    result['execution_receipt_sha256']=receipt_sha
    (reports/'publication.json').write_bytes(encoded(result))
    print('LONG_HISTORY_SUMMARY '+json.dumps(dict(result,financial_issuers=report['financial_issuers'],financial_fact_rows=report['financial_fact_rows'])),flush=True)
    if report['status']=='PARTIAL' or not result['study_recomputed_from_drive']: return 2
    return 0

if __name__=='__main__':
    try: raise SystemExit(main())
    except (ValueError,KeyError,TypeError,OSError) as exc:
        raise SystemExit('LONG_HISTORY_BLOCKED:'+safe_error(exc)) from None

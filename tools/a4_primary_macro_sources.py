"""Government-original growth, inflation, dollar and Treasury research inputs.

Separate typed adapter preserves the accepted bank/funding capture codec. All
histories are revised-current, available at collection, never historical PIT.
"""
from __future__ import annotations

import gzip
import io
from pathlib import Path
import re
import stat
from urllib.request import Request, build_opener
import xml.etree.ElementTree as ET
import zipfile
import zlib

from tools import a4_primary_sources as p
from tools.macro_history_sources import digest, encoded, exclusive, NoRedirect
from tools.macro_research_checkpoint import LocalTransport

SCHEMA = 'a4-primary-economic-bundle-v1'
MAX_RAW = 8 * 1024**2
BLS_URI = 'https://api.bls.gov/publicAPI/v2/timeseries/data/'
UST_BASE = 'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data='
FEEDS = ('h10', 'ust_nominal', 'ust_real', 'bls_1996_2005', 'bls_2006_2015', 'bls_2016_2025', 'bls_recent')
BLS = {
    'LNS14000000': ('UNRATE', 'unemployment', 'percent', 'GROWTH'),
    'CES0000000001': ('PAYEMS', 'payrolls', 'thousands_persons', 'GROWTH'),
    'CUSR0000SA0': ('CPIAUCSL', 'cpi', 'index', 'INFLATION'),
    'CUSR0000SA0L1E': ('CPILFESL', 'core_cpi', 'index', 'INFLATION'),
}
ATOM='http://www.w3.org/2005/Atom'
DATA='http://schemas.microsoft.com/ado/2007/08/dataservices'
META=DATA+'/metadata'


def registers():
    return dict(
        frb={'H10_BROAD': ('broad_usd','index','daily','PERIOD_OBSERVATION','SOURCE_DEFINED','FX',7)},
        ust={'DGS2': ('yield_2y','percent','daily','PAR_YIELD_CURVE','NSA','RATES',7),
             'DGS10': ('yield_10y','percent','daily','PAR_YIELD_CURVE','NSA','RATES',7),
             'DFII10': ('real_yield_10y','percent','daily','PAR_REAL_YIELD_CURVE','NSA','RATES',7)},
        bls={alias:(logical,unit,'monthly','PERIOD_OBSERVATION','SA',family,90)
             for alias,logical,unit,family in BLS.values()})


def request_spec(feed, collected_at, request_year=None):
    p.check(feed in FEEDS, 'ECONOMIC_FEED')
    year=p.clock(collected_at).year
    p.check(1996<=year<=2035, 'ECONOMIC_REVIEW_WINDOW')
    payload=None
    if feed=='h10':
        p.check(request_year is None, 'ECONOMIC_REQUEST_YEAR')
        uri='https://www.federalreserve.gov/releases/h10/data/FRB_h10_xml.zip'
    elif feed.startswith('ust_'):
        p.check(type(request_year) is int and (2003 if feed=='ust_real' else 1996)<=request_year<=year,
                'ECONOMIC_REQUEST_YEAR')
        kind='daily_treasury_real_yield_curve' if feed=='ust_real' else 'daily_treasury_yield_curve'
        uri=UST_BASE+kind+'&field_tdr_date_value='+str(request_year)
    else:
        p.check(request_year is None, 'ECONOMIC_REQUEST_YEAR')
        start,end=(2026,year) if feed=='bls_recent' else tuple(map(int,feed.split('_')[1:]))
        p.check(start<=end and end-start<10, 'ECONOMIC_BLS_WINDOW')
        payload=dict(seriesid=list(BLS),startyear=str(start),endyear=str(end))
        uri=BLS_URI
    return uri,payload


def capture(feed, *, fetcher=None, request_year=None):
    uri,payload=request_spec(feed,p.now(),request_year)
    body=encoded(payload) if payload is not None else None
    if fetcher is not None:
        raw=fetcher(uri,MAX_RAW,body)
    else:
        headers={'User-Agent':'r1000-primary-macro-research/1.0',
                 'Accept':'application/json, application/xml, application/x-zip-compressed'}
        if body is not None:headers['Content-Type']='application/json'
        with build_opener(NoRedirect()).open(Request(uri,data=body,headers=headers),timeout=30) as response:
            p.check(response.status==200,'ECONOMIC_HTTP_STATUS');raw=response.read(MAX_RAW+1)
    p.check(type(raw) is bytes and 0<len(raw)<=MAX_RAW,'ECONOMIC_ORIGINAL_BUDGET')
    return raw,p.now()


def _xml_events(raw):
    stack=[];nodes=0
    for event,e in ET.iterparse(p.SafeXML(io.BytesIO(raw),p.MAX_EXPANDED),events=('start','end')):
        if event=='start':
            stack.append(e);nodes+=1
            p.check(len(stack)<=12 and nodes<=2000000,'ECONOMIC_XML_NODE_BUDGET')
        yield event,e,stack
        if event=='end':stack.pop()


def _h10(raw):
    output=[];selected=None;found=0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members=archive.infolist();names=[m.filename for m in members]
        p.check(0<len(members)<=8 and len(names)==len(set(names)) and
                all(re.fullmatch('[A-Za-z0-9_]+\\.(xml|xsd)',m.filename) and not m.flag_bits&1
                    and not stat.S_ISLNK(m.external_attr>>16)
                    and 0<m.file_size<=p.MAX_EXPANDED for m in members) and
                sum(m.file_size for m in members)<=p.MAX_EXPANDED and
                {'H10_data.xml','H10_struct.xml'}<=set(names),'ECONOMIC_ZIP_INVENTORY')
        # The published H.10 archive is27MB expanded; charge actual bytes, not
        # only the ZIP directory, and release unselected observation elements.
        with archive.open('H10_data.xml') as handle:
            stack=[];nodes=0;reader=p.SafeXML(handle,p.MAX_EXPANDED)
            for event,e in ET.iterparse(reader,events=('start','end')):
                tag=p._local(e.tag)
                if event=='start':
                    stack.append(e);nodes+=1
                    p.check(len(stack)<=12 and nodes<=2000000,'ECONOMIC_XML_NODE_BUDGET')
                    if tag=='Series':
                        p.check(selected is None,'ECONOMIC_NESTED_SERIES')
                        if e.get('SERIES_NAME')=='JRXWTFB_N.B':
                            p.check(all(e.get(k)==v for k,v in dict(FREQ='9',FX='BRD',CURRENCY='NA',UNIT='Index:_1997_Jan_100',UNIT_MULT='1').items()),'ECONOMIC_H10_IDENTITY')
                            found+=1;p.check(found==1,'ECONOMIC_DUPLICATE_SERIES');selected=e
                else:
                    if tag=='Obs' and selected is not None:
                        p.check(len(stack)>1 and stack[-2] is selected,'ECONOMIC_XML_PARENT')
                        status=e.get('OBS_STATUS');p.check(status in {'A','NA','ND','NC','E','P'},'ECONOMIC_OBSERVATION_STATUS')
                        value=None if status in {'NA','ND','NC'} else p.f.number(e.get('OBS_VALUE'))
                        p.check(value is None or value>=0,'ECONOMIC_INDEX_VALUE')
                        output.append(('frb','H10_BROAD',e.get('TIME_PERIOD'),value,
                            dict(native_series_id='JRXWTFB_N.B',native_unit='Index:_1997_Jan_100',native_frequency='9',
                                 native_observation_status=status,index_definition='BRD current broad index; V0 BRDG goods-only history is excluded; native base label retained without rebasing')))
                        p.check(len(output)<=20000,'ECONOMIC_H10_ROWS')
                    if tag=='Series':selected=None
                    if tag in {'Obs','Series'}:
                        e.clear()
                        if len(stack)>1:stack[-2].remove(e)
                    stack.pop()
    p.check(found==1 and output,'ECONOMIC_REQUIRED_SERIES')
    return output


def _treasury(raw, feed, year):
    fields={'TC_10YEAR':'DFII10'} if feed=='ust_real' else {'BC_2YEAR':'DGS2','BC_10YEAR':'DGS10'}
    output=[];entries=0;root=None
    for event,e,stack in _xml_events(raw):
        if root is None:
            root=e;p.check(e.tag=='{'+ATOM+'}feed','ECONOMIC_TREASURY_SCHEMA')
        if event=='start':continue
        if e.tag=='{'+ATOM+'}link' and e.get('rel')=='next':raise ValueError('ECONOMIC_TREASURY_PAGINATION')
        if e.tag!='{'+ATOM+'}entry':continue
        entries+=1;p.check(entries<=270,'ECONOMIC_TREASURY_ROWS')
        props=e.findall('.//{'+META+'}properties');p.check(len(props)==1,'ECONOMIC_TREASURY_PROPERTIES')
        values={}
        for item in props[0]:
            p.check(item.tag.startswith('{'+DATA+'}'),'ECONOMIC_TREASURY_NAMESPACE')
            name=p._local(item.tag);p.check(name not in values,'ECONOMIC_TREASURY_DUPLICATE_PROPERTY');values[name]=item
        stamp=values.get('NEW_DATE');p.check(stamp is not None and type(stamp.text) is str and
            re.fullmatch(r'\d{4}-\d{2}-\d{2}T00:00:00',stamp.text),'ECONOMIC_TREASURY_DATE')
        observed=p.day(stamp.text[:10]);p.check(observed.year==year,'ECONOMIC_TREASURY_YEAR')
        for native,alias in fields.items():
            item=values.get(native);p.check(item is not None,'ECONOMIC_TREASURY_FIELD')
            value=None if item.get('{'+META+'}null')=='true' else p.f.number(item.text)
            output.append(('ust',alias,observed.isoformat(),value,dict(native_series_id=native,
                native_unit='percent_per_annum',request_year=year,
                publication_warning='Atom updated is current feed regeneration, not original historical publication')))
        e.clear()
        if len(stack)>1:stack[-2].remove(e)
    p.check(entries>0,'ECONOMIC_TREASURY_EMPTY_YEAR')
    return output


def _bls(raw,payload):
    data=p.f.strict_json(raw)
    p.check(type(data) is dict and data.get('status')=='REQUEST_SUCCEEDED' and data.get('message')==[], 'ECONOMIC_BLS_RESPONSE')
    results=data.get('Results');p.check(type(results) is dict and type(results.get('series')) is list,'ECONOMIC_BLS_SCHEMA')
    series=results['series'];p.check(len(series)==len(BLS),'ECONOMIC_BLS_SERIES')
    output=[];seen=set()
    for item in series:
        p.check(type(item) is dict,'ECONOMIC_BLS_SERIES')
        native=item.get('seriesID');p.check(native in BLS and native not in seen,'ECONOMIC_BLS_SERIES');seen.add(native)
        observations=item.get('data');p.check(type(observations) is list and 0<len(observations)<=120,'ECONOMIC_BLS_ROWS')
        for row in observations:
            p.check(type(row) is dict,'ECONOMIC_BLS_ROW')
            year,period=row.get('year'),row.get('period')
            p.check(type(year) is str and re.fullmatch('[0-9]{4}',year) and
                int(payload['startyear'])<=int(year)<=int(payload['endyear']) and type(period) is str and
                re.fullmatch('M(0[1-9]|1[0-2])',period),'ECONOMIC_BLS_PERIOD')
            text=row.get('value');p.check(type(text) is str and 0<len(text)<=100,'ECONOMIC_BLS_VALUE')
            value=None if text in {'.','-','NA','N/A'} else p.f.number(text)
            alias,_,_,_=BLS[native]
            p.check(value is None or (0<=value<=100 if alias=='UNRATE' else value>=0),'ECONOMIC_BLS_VALUE')
            footnotes=row.get('footnotes',[])
            p.check(type(footnotes) is list and len(footnotes)<=10 and all(type(n) is dict and set(n)<={'code','text'} and
                all(type(v) is str and len(v)<=1000 for v in n.values()) for n in footnotes),'ECONOMIC_BLS_FOOTNOTES')
            output.append(('bls',alias,year+'-'+period[1:]+'-01',value,
                dict(native_series_id=native,native_unit=BLS[native][2],source_footnotes=footnotes)))
    return output


def normalize(raw,feed,*,collected_at,start='1996-01-01',through=None,request_year=None):
    p.check(type(raw) is bytes and 0<len(raw)<=MAX_RAW,'ECONOMIC_ORIGINAL_BUDGET')
    collected=p.clock(collected_at);first=p.day(start);last=p.day(through) if through else collected.date()
    p.check(first<=last<=collected.date(),'ECONOMIC_OBSERVATION_WINDOW')
    uri,payload=request_spec(feed,collected_at,request_year)
    try:
        source=_h10(raw) if feed=='h10' else _treasury(raw,feed,request_year) if feed.startswith('ust_') else _bls(raw,payload)
    except (zipfile.BadZipFile,ET.ParseError,RuntimeError):raise ValueError('ECONOMIC_ORIGINAL_INVALID') from None
    rows=[];seen=set();specs=registers();original_sha=digest(raw)
    for provider,alias,observed,value,extras in source:
        date=p.day(observed);key=(provider,alias,observed)
        p.check(key not in seen,'ECONOMIC_DUPLICATE_OBSERVATION');seen.add(key)
        if not first<=date<=last:continue
        logical,unit,frequency,basis,seasonal,family,age=specs[provider][alias]
        rows.append(dict(source_id=provider+':'+alias,logical_id=logical,observation_date=observed,value=value,
            unit=unit,frequency=frequency,measurement_basis=basis,seasonal_basis=seasonal,family=family,max_age_days=age,
            original_sha256=original_sha,collected_at=collected_at,available_at=collected_at,published_at=None,
            truth_class='PRIMARY_CURRENT_VINTAGE',historical_pit_certified=False,**extras))
    p.check(rows and len(rows)<=20000,'ECONOMIC_OBSERVATION_BUDGET');rows.sort(key=lambda r:(r['source_id'],r['observation_date']))
    normalized_sha=digest(encoded(rows))
    for row in rows:row['normalized_sha256']=normalized_sha
    notices=['Source: Board of Governors of the Federal Reserve System; native H.10 series identity/base labels retained.'] if feed=='h10' else (
        ['Source: U.S. Department of the Treasury; current downloaded par-yield data, not original historical publication.'] if feed.startswith('ust_') else
        ['Source: U.S. Bureau of Labor Statistics; accessed '+collected_at+'. BLS.gov cannot vouch for the data or analyses derived from these data after the data have been retrieved from BLS.gov.'])
    return rows,dict(feed=feed,original_sha256=original_sha,original_bytes=len(raw),normalized_sha256=normalized_sha,
        observations=len(rows),series=sorted({r['source_id'] for r in rows}),first_observation=min(r['observation_date'] for r in rows),
        last_observation=max(r['observation_date'] for r in rows),requested_start=start,requested_through=last.isoformat(),
        collected_at=collected_at,request_year=request_year,request_json=payload,source_uri=uri,source_notices=notices,
        provider='FEDERAL_RESERVE_BOARD' if feed=='h10' else 'US_TREASURY' if feed.startswith('ust_') else 'US_BUREAU_OF_LABOR_STATISTICS',
        rights_uri='https://www.federalreserve.gov/disclaimer.htm' if feed=='h10' else
            'https://home.treasury.gov/footer/site-policies-and-notices' if feed.startswith('ust_') else
            'https://www.bls.gov/developers/termsOfService.htm',
        source_admitted=False,training_admitted=False,historical_pit_certified=False)


def _manifest(receipt, normalized):
    return dict(schema=SCHEMA,**receipt,normalized_object_sha256=digest(normalized),normalized_object_bytes=len(normalized),
        normalizer_sha256=digest(Path(__file__).read_bytes()),base_codec_sha256=digest(Path(p.__file__).read_bytes()),
        fullrun_executed=False,accepted_state_written=False)


def prepare(raw,feed,**kwargs):
    rows,receipt=normalize(raw,feed,**kwargs);buffer=io.BytesIO()
    with gzip.GzipFile(fileobj=buffer,mode='wb',filename='',mtime=0,compresslevel=6) as stream:
        for line in p._normalized_lines(rows):stream.write(line)
    normalized=buffer.getvalue();p.check(len(normalized)<=MAX_RAW,'ECONOMIC_NORMALIZED_BUDGET')
    manifest=_manifest(receipt,normalized);body=encoded(manifest)
    return rows,manifest,{'objects/'+digest(raw):raw,'objects/'+digest(normalized):normalized,'generations/'+digest(body)+'.json':body}


def store_capture(root,raw,feed,**kwargs):
    _,manifest,files=prepare(raw,feed,**kwargs);root=Path(root)
    for name,body in files.items():
        path=root/name;p.check(not any(q.is_symlink() for q in (path,*path.parents)),'ECONOMIC_OUTPUT_SYMLINK')
        p.check(not path.exists() or p._bounded(path,MAX_RAW)==body,'ECONOMIC_OUTPUT_CONFLICT')
    for name,body in files.items():
        if not (root/name).exists():exclusive(root/name,body)
        p.check(p._bounded(root/name,MAX_RAW)==body,'ECONOMIC_OUTPUT_READBACK')
    return dict(manifest=manifest,generation_sha256=digest(encoded(manifest)),files=sorted(files))


def read_generation(transport,pin,*,cutoff):
    p.check(type(pin) is str and re.fullmatch('[a-f0-9]{64}',pin),'ECONOMIC_GENERATION_PIN')
    raw=p.read_object(transport,p.PREFIX+'/generations/'+pin+'.json',pin,65536);manifest=p.f.strict_json(raw)
    p.check(type(manifest) is dict and manifest.get('schema')==SCHEMA,'ECONOMIC_GENERATION_SCHEMA')
    p.check(p.clock(manifest['collected_at'])<=p.clock(cutoff),'ECONOMIC_FUTURE_CAPTURE')
    original=p.read_object(transport,p.PREFIX+'/objects/'+manifest['original_sha256'],manifest['original_sha256'],MAX_RAW)
    normalized=p.read_object(transport,p.PREFIX+'/objects/'+manifest['normalized_object_sha256'],manifest['normalized_object_sha256'],MAX_RAW)
    rows,receipt=normalize(original,manifest['feed'],collected_at=manifest['collected_at'],start=manifest['requested_start'],
        through=manifest['requested_through'],request_year=manifest['request_year'])
    p.check(_manifest(receipt,normalized)==manifest and encoded(manifest)==raw,'ECONOMIC_NORMALIZATION_REPLAY')
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(normalized),mode='rb') as stream:
            for expected in p._normalized_lines(rows):p.check(stream.readline(p.MAX_LINE_BYTES+1)==expected,'ECONOMIC_NORMALIZATION_REPLAY')
            p.check(stream.read(1)==b'','ECONOMIC_NORMALIZATION_REPLAY')
    except (OSError,EOFError,zlib.error):raise ValueError('ECONOMIC_NORMALIZATION_REPLAY') from None
    return rows,manifest


def publish_capture(transport,root,pin,*,cutoff):
    class Prepared(LocalTransport):
        def read(self,path):
            p.check(path.startswith(p.PREFIX+'/'),'ECONOMIC_PREPARED_SCOPE')
            return super().read(path[len(p.PREFIX)+1:])
    _,manifest=read_generation(Prepared(root),pin,cutoff=cutoff)
    for name in ('objects/'+manifest['original_sha256'],'objects/'+manifest['normalized_object_sha256'],'generations/'+pin+'.json'):
        body=p._bounded(Path(root)/name,MAX_RAW);transport.write(p.PREFIX+'/'+name,body)
        p.check(p.read_object(transport,p.PREFIX+'/'+name,digest(body),MAX_RAW)==body,'ECONOMIC_DURABLE_READBACK')
    rows,checked=read_generation(transport,pin,cutoff=cutoff)
    return dict(generation_sha256=pin,observations=len(rows),original_sha256=checked['original_sha256'],
        original_bytes=checked['original_bytes'],transport_readback_verified=transport.remote_verified is True,
        source_admitted=False,training_admitted=False,historical_pit_certified=False)

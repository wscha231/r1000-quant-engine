"""Bounded Treasury/SLOOS/ACM originals; no licensed-series substitution."""
from __future__ import annotations
import csv
from datetime import datetime
from decimal import Decimal,InvalidOperation
import gzip
from html.parser import HTMLParser
import io
import math
from pathlib import Path
import re
import struct
import zlib
from urllib.request import Request,build_opener

from tools import a4_primary_sources as p
from tools.macro_history_sources import digest,encoded,exclusive
from tools.macro_research_checkpoint import LocalTransport
from tools.macro_history_sources import NoRedirect

SCHEMA='a4-primary-financing-bundle-v1'
MAX_RAW=8*1024**2
MAX_XLS=12*1024**2
MAX_ROWS=30000
FEEDS=('auction_notes','auction_bonds','sloos_index','sloos_domestic','acm_monthly','acm_daily')
URLS={
    'auction_notes':'https://www.treasurydirect.gov/TA_WS/securities/auctioned?format=json&type=Note',
    'auction_bonds':'https://www.treasurydirect.gov/TA_WS/securities/auctioned?format=json&type=Bond',
    'sloos_index':'https://www.federalreserve.gov/data/sloos.htm',
    'acm_monthly':'https://www.newyorkfed.org/medialibrary/media/research/data_indicators/acmPlot_data.csv',
    'acm_daily':'https://www.newyorkfed.org/medialibrary/media/research/data_indicators/ACMTermPremium.xls',
}


def input_limit(feed):return MAX_XLS if feed=='acm_daily' else MAX_RAW


def capture(feed,*,fetcher=None,period=None):
    uri=source_uri(feed,period)
    limit=input_limit(feed)
    if fetcher is not None:raw=fetcher(uri,limit)
    else:
        request=Request(uri,headers={'User-Agent':'R1000-Research/1.0',
            'Accept':'application/vnd.ms-excel,application/octet-stream' if feed=='acm_daily' else 'application/json,text/html,text/csv'})
        with build_opener(NoRedirect).open(request,timeout=45) as response:
            p.check(response.status==200,'FINANCING_HTTP_STATUS')
            raw=response.read(limit+1)
    p.check(type(raw) is bytes and 0<len(raw)<=limit,'FINANCING_ORIGINAL_BUDGET')
    return raw,p.now()


def number(value,*,minimum=None,maximum=None):
    p.check(type(value) in {str,int,float} and type(value) is not bool,'FINANCING_NUMBER')
    try:result=float(value)
    except (ValueError,OverflowError):raise ValueError('FINANCING_NUMBER') from None
    p.check(math.isfinite(result) and (minimum is None or result>=minimum)
            and (maximum is None or result<=maximum),'FINANCING_NUMBER')
    return result


def amount(value,*,minimum=0,maximum=10**15):
    p.check(type(value) in {str,int},'AUCTION_DOLLAR_UNIT')
    try:result=Decimal(value)
    except (InvalidOperation,ValueError):raise ValueError('AUCTION_DOLLAR_UNIT') from None
    p.check(result.is_finite() and minimum<=result<=maximum and result==result.to_integral_value(),
            'AUCTION_DOLLAR_UNIT')
    return int(result)


def source_uri(feed,period=None):
    p.check(feed in FEEDS,'FINANCING_FEED')
    if feed=='sloos_domestic':
        p.check(type(period) is str and re.fullmatch(r'20\d{2}(01|04|07|10)',period),'SLOOS_PERIOD')
        return 'https://www.federalreserve.gov/data/sloos/sloos-'+period+'-table-1.htm'
    p.check(period is None,'FINANCING_UNEXPECTED_PERIOD')
    return URLS[feed]


class Node:
    def __init__(self,tag,attrs):self.tag=tag;self.attrs=dict(attrs);self.children=[]
    def text(self):
        return ' '.join(' '.join(x.text() if isinstance(x,Node) else x for x in self.children).split())
    def nodes(self,tag):
        pending=list(reversed(self.children))
        while pending:
            node=pending.pop()
            if isinstance(node,Node):
                if node.tag==tag:yield node
                pending.extend(reversed(node.children))


class Document(HTMLParser):
    VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    def __init__(self,raw):
        p.check(len(raw)<=2*1024**2 and b'\x00' not in raw and b'<!ENTITY' not in raw.upper(),'FINANCING_HTML')
        super().__init__(convert_charrefs=True)
        self.root=Node('root',[]);self.stack=[self.root];self.count=0
        self.feed(raw.decode('utf-8-sig'));self.close()
    def handle_starttag(self,tag,attrs):
        self.count+=1
        p.check(self.count<=100000 and len(self.stack)<128 and len(attrs)<=50,'FINANCING_HTML_BUDGET')
        p.check(all(len(k)<128 and (v is None or len(v)<=8192) for k,v in attrs),'FINANCING_HTML_ATTRIBUTE')
        p.check(len({k for k,_ in attrs})==len(attrs),'FINANCING_HTML_DUPLICATE_ATTRIBUTE')
        node=Node(tag,attrs);self.stack[-1].children.append(node)
        if tag not in self.VOID:self.stack.append(node)
    def handle_endtag(self,tag):
        for index in range(len(self.stack)-1,0,-1):
            if self.stack[index].tag==tag:
                del self.stack[index:];break
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.VOID:self.handle_endtag(tag)
    def handle_data(self,data):self.stack[-1].children.append(data)
    def unknown_decl(self,data):raise ValueError('FINANCING_HTML_DECLARATION')


def sloos_period(raw,through):
    doc=Document(raw);periods=set()
    for node in doc.root.nodes('a'):
        match=re.fullmatch(r'/data/sloos/sloos-(20\d{2}(?:01|04|07|10))\.htm',node.attrs.get('href',''))
        if match and match[1]<=through[:4]+through[5:7]:periods.add(match[1])
    p.check(bool(periods),'SLOOS_RELEASE_INDEX')
    return max(periods)


def auctions(raw,feed,through):
    data=p.f.strict_json(raw)
    p.check(type(data) is list and 0<len(data)<=5000,'AUCTION_ROWS')
    expected='Note' if feed=='auction_notes' else 'Bond'
    output=[];seen=set();groups=set()
    for row in data:
        p.check(type(row) is dict,'AUCTION_ROW')
        raw_date=row.get('competitiveAuctionCloseDate')
        p.check(type(raw_date) is str,'AUCTION_DATE')
        date=p.day(raw_date[:10]).isoformat()
        if date>through:continue
        p.check(row.get('securityType')==expected,'AUCTION_SECURITY_TYPE')
        if row.get('inflationProtected')=='Yes' or row.get('floatingRate')=='Yes':continue
        p.check(row.get('inflationProtected')=='No' and row.get('floatingRate')=='No','AUCTION_PRODUCT_FLAGS')
        term=row.get('originalSecurityTerm');match=re.fullmatch(r'(2|3|5|7|10|20|30)-Year',term or '')
        p.check(bool(match),'AUCTION_ORIGINAL_TERM')
        p.check(int(match[1]) in ({2,3,5,7,10} if expected=='Note' else {20,30}),'AUCTION_TERM_TYPE')
        cusip=row.get('cusip');reopen=row.get('reopening')
        p.check(type(cusip) is str and re.fullmatch('[A-Z0-9]{9}',cusip) and reopen in {'Yes','No'},'AUCTION_IDENTITY')
        key=(date,cusip);p.check(key not in seen,'AUCTION_DUPLICATE');seen.add(key)
        group=(date,term);p.check(group not in groups,'AUCTION_AMBIGUOUS_SAME_DAY_TERM');groups.add(group)
        offered=amount(row.get('offeringAmount'),minimum=1)
        competitive=amount(row.get('subtotalCompetitiveParAwardedInsideOfOfferingAmount'),minimum=1)
        components={name:amount(row.get(native),maximum=competitive) for name,native in
            [('dealer','primaryDealersCompetitiveParAwarded'),('direct','directBiddersCompetitiveParAwarded'),
             ('indirect','indirectBiddersCompetitiveParAwarded')]}
        p.check(sum(components.values())==competitive,'AUCTION_COMPETITIVE_RECONCILIATION')
        output.append(dict(kind='TREASURY_AUCTION',observation_date=date,security_type=expected,
            original_term_years=int(match[1]),native_security_term=row.get('securityTerm'),cusip=cusip,
            reopening=reopen=='Yes',high_yield_percent=number(row.get('highYield'),minimum=-10,maximum=100),
            bid_to_cover=number(row.get('bidToCoverRatio'),minimum=.01,maximum=100),offering_usd=offered,
            competitive_accepted_inside_offering_usd=competitive,competitive_accepted_usd=components,
            competitive_shares_percent={k:100*v/competitive for k,v in components.items()},
            native_updated_timestamp=row.get('updatedTimestamp'),
            rate_basis='NOMINAL_HIGH_YIELD_PERCENT',denominator_basis='COMPETITIVE_PAR_AWARDED_INSIDE_OFFERING',
            population='CURRENT_API_AUCTIONED_SNAPSHOT_NOT_COMPLETE_HISTORICAL_UNIVERSE'))
    p.check(bool(output),'AUCTION_NO_OBSERVATIONS')
    return sorted(output,key=lambda r:(r['observation_date'],r['cusip']))


TIGHT=('Tightened considerably','Tightened somewhat','Remained basically unchanged','Eased somewhat','Eased considerably')
DEMAND=('Substantially stronger','Moderately stronger','About the same','Moderately weaker','Substantially weaker')
SECTORS={'small_firms':'standards for small firms','cre_construction':'construction and land development',
         'cre_nonfarm':'nonfarm nonresidential','cre_multifamily':'multifamily',
         'ndfi_mortgage':'mortgage credit intermediaries','ndfi_business':'business credit intermediaries',
         'ndfi_private_equity':'private equity funds','ndfi_consumer':'consumer credit intermediaries','ndfi_other':'other ndfis'}


def survey(raw,period,through):
    source_uri('sloos_domestic',period)
    p.check(period<=through[:4]+through[5:7],'SLOOS_FUTURE_PERIOD')
    doc=Document(raw);labels={}
    for tag in ('p','h1','h2','h3','h4','h5'):
        for node in doc.root.nodes(tag):
            name=node.attrs.get('id')
            if name and re.fullmatch(r'q\d+(?:-\d+)*',name):
                p.check(name not in labels,'SLOOS_DUPLICATE_LABEL');labels[name]=node.text()
    months=('January','February','March','April','May','June','July','August','September','October','November','December')
    month=months[int(period[4:])-1]+' '+period[:4]
    p.check('Status of Policy as of '+month in doc.root.text(),'SLOOS_DOCUMENT_PERIOD')
    output=[];seen=set()
    for table in doc.root.nodes('table'):
        p.check(not list(table.nodes('table')),'SLOOS_NESTED_TABLE')
        refs=table.attrs.get('aria-labelledby','').split()
        if not refs:continue
        if not all(ref in labels for ref in refs):continue
        question=' '.join(labels[ref] for ref in refs);lower=question.lower()
        data={};group=None
        for th in table.nodes('th'):
            if th.text()=='All Respondents':
                p.check(group is None,'SLOOS_RESPONDENT_HEADER');group=th.attrs.get('id')
        if not group:continue
        for tr in table.nodes('tr'):
            headers=list(tr.nodes('th'));cells=list(tr.nodes('td'))
            if not headers:continue
            label=headers[0].text()
            if label not in {*TIGHT,*DEMAND,'Total'}:continue
            values={suffix:[c for c in cells if group+'-'+suffix in c.attrs.get('headers','').split()] for suffix in ('b','p')}
            p.check(label not in data and all(len(v)==1 for v in values.values()),'SLOOS_RESPONSE_COLUMNS')
            count=number(values['b'][0].text(),minimum=0,maximum=1000)
            p.check(count.is_integer(),'SLOOS_BANK_COUNT')
            data[label]=(int(count),number(values['p'][0].text(),minimum=0,maximum=100))
        if set(data)=={*TIGHT,'Total'} and 'credit standards' in lower:kind='NET_TIGHTENING';names=TIGHT
        elif set(data)=={*DEMAND,'Total'} and 'demand' in lower:kind='NET_STRONGER_DEMAND';names=DEMAND
        else:continue
        sectors=[key for key,phrase in SECTORS.items() if phrase in lower]
        p.check(len(sectors)<=1,'SLOOS_AMBIGUOUS_SECTOR')
        if not sectors:continue
        sector=sectors[0];key=(sector,kind)
        p.check(key not in seen,'SLOOS_DUPLICATE_MEASURE');seen.add(key)
        total=data['Total'][0]
        p.check(total>0 and sum(data[n][0] for n in names)==total and abs(data['Total'][1]-100)<.01,'SLOOS_RESPONSE_RECONCILIATION')
        p.check(all(abs(100*data[n][0]/total-data[n][1])<=.11 for n in names),'SLOOS_PERCENT_RECONCILIATION')
        value=100*(data[names[0]][0]+data[names[1]][0]-data[names[3]][0]-data[names[4]][0])/total
        output.append(dict(kind='SLOOS',observation_date=period[:4]+'-'+period[4:]+'-01',
            survey_period=period,sector=sector,measure=kind,value=value,unit='net_percent_of_respondents',
            response_counts={n:data[n][0] for n in names},respondents=total,question_ids=refs,
            question=question,frequency='quarterly',measurement_basis='NET_PERCENT_FROM_COUNTS',
            population='DOMESTIC_SLOOS_RESPONDENTS_NOT_H8_AGGREGATES'))
    p.check(any(r['sector']=='small_firms' for r in output) and
            all(any(r['sector']==k and r['measure']=='NET_TIGHTENING' for r in output)
                for k in ('cre_construction','cre_nonfarm','cre_multifamily')),'SLOOS_REQUIRED_STANDARD_ITEMS')
    return sorted(output,key=lambda r:(r['sector'],r['measure']))


def model_day(value):
    p.check(type(value) is str,'ACM_DATE')
    match=re.fullmatch(r'(\d{1,2})-([A-Za-z]{3})-(\d{4})',value)
    months=('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec')
    p.check(match is not None and match[2] in months,'ACM_DATE')
    return p.day(f'{int(match[3]):04d}-{months.index(match[2])+1:02d}-{int(match[1]):02d}').isoformat()


def daily_acm(raw,through):
    p.check(raw.startswith(bytes.fromhex('d0cf11e0a1b11ae1')),'ACM_XLS_SIGNATURE')
    try:import xlrd
    except ImportError:raise ValueError('ACM_XLS_PARSER_UNAVAILABLE') from None
    from xlrd.compdoc import CompDocError
    p.check(xlrd.__version__=='2.0.2','ACM_XLS_PARSER_VERSION')
    book=None
    try:
        book=xlrd.open_workbook(file_contents=raw,logfile=io.StringIO(),on_demand=True,ragged_rows=True)
        p.check(book.nsheets==2 and set(book.sheet_names())=={'ACM Monthly','ACM Daily'},'ACM_XLS_SHEETS')
        sheet=book.sheet_by_name('ACM Daily')
        header=['DATE']+[f'{stem}{i:02d}' for stem in ('ACMY','ACMTP','ACMRNY') for i in range(1,11)]
        p.check(sheet.ncols==31 and 1<sheet.nrows<=MAX_ROWS+1 and sheet.row_values(0)==header,'ACM_XLS_HEADER')
        output=[];seen=set()
        for index in range(1,sheet.nrows):
            cell=sheet.cell(index,0)
            date=(xlrd.xldate_as_datetime(cell.value,book.datemode).date().isoformat()
                  if cell.ctype==xlrd.XL_CELL_DATE else model_day(cell.value))
            if date>through:continue
            p.check(date not in seen,'ACM_DAILY_DUPLICATE');seen.add(date)
            cells=[sheet.cell(index,header.index(name)) for name in ('ACMTP10','ACMY10','ACMRNY10')]
            missing=any(c.ctype in {xlrd.XL_CELL_EMPTY,xlrd.XL_CELL_BLANK} for c in cells)
            p.check(all(c.ctype in {xlrd.XL_CELL_NUMBER,xlrd.XL_CELL_EMPTY,xlrd.XL_CELL_BLANK} for c in cells),'ACM_XLS_CELL_TYPE')
            values=[None,None,None] if missing else [number(c.value,minimum=-20,maximum=50) for c in cells]
            if not missing:p.check(abs(values[0]+values[2]-values[1])<1e-8,'ACM_MODEL_DECOMPOSITION')
            output.append(dict(kind='ACM_DAILY',observation_date=date,frequency='daily',
                term_premium_10y_percent=values[0],fitted_yield_10y_percent=values[1],
                expected_short_rate_10y_percent=values[2],native_value_status='MISSING_NATIVE_CELL' if missing else 'OBSERVED',
                estimate_basis='ACM_MODEL_ESTIMATE_NOT_OBSERVED_PREMIUM',daily_series_verified=True))
        p.check(bool(output),'ACM_NO_OBSERVATIONS')
        dates=sorted(seen)
        if len(dates)>=3:p.check(min((p.day(b)-p.day(a)).days for a,b in zip(dates,dates[1:]))<=7,'ACM_DAILY_CADENCE')
        return sorted(output,key=lambda r:r['observation_date'])
    except (xlrd.XLRDError,CompDocError,ValueError,TypeError,IndexError,AssertionError,struct.error,OverflowError):
        raise ValueError('ACM_XLS_INVALID') from None
    finally:
        if book is not None:book.release_resources()


def monthly_acm(raw,through):
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline=''))
    p.check(reader.fieldnames==['RunDates','TERMYld','ACMFITYld','GSWYld'],'ACM_COLUMNS')
    output=[];seen=set()
    for item in reader:
        p.check(len(output)<MAX_ROWS and None not in item,'ACM_ROWS')
        date=model_day(item['RunDates'])
        if date>through:continue
        key=date[:7];p.check(key not in seen,'ACM_MONTHLY_DUPLICATE');seen.add(key)
        output.append(dict(kind='ACM_MONTHLY',observation_date=date,frequency='monthly',
            term_premium_10y_percent=number(item['TERMYld'],minimum=-20,maximum=50),
            fitted_yield_10y_percent=number(item['ACMFITYld'],minimum=-20,maximum=50),
            gsw_yield_10y_percent=number(item['GSWYld'],minimum=-20,maximum=50),
            estimate_basis='ACM_MODEL_ESTIMATE_NOT_OBSERVED_PREMIUM',daily_series_verified=False))
    p.check(bool(output),'ACM_NO_OBSERVATIONS')
    return sorted(output,key=lambda r:r['observation_date'])


def normalize(raw,feed,*,collected_at,through=None,period=None):
    p.check(type(raw) is bytes and 0<len(raw)<=input_limit(feed),'FINANCING_ORIGINAL_BUDGET')
    cutoff=p.clock(collected_at);last=p.day(through or cutoff.date().isoformat()).isoformat()
    p.check(last<=cutoff.date().isoformat(),'FINANCING_FUTURE_WINDOW');uri=source_uri(feed,period)
    if feed.startswith('auction_'):rows=auctions(raw,feed,last)
    elif feed=='sloos_index':
        selected=sloos_period(raw,last)
        rows=[dict(kind='SLOOS_RELEASE_INDEX',observation_date=selected[:4]+'-'+selected[4:]+'-01',period=selected)]
    elif feed=='sloos_domestic':rows=survey(raw,period,last)
    elif feed=='acm_daily':rows=daily_acm(raw,last)
    else:rows=monthly_acm(raw,last)
    p.check(len(rows)<=MAX_ROWS,'FINANCING_ROW_BUDGET');original_sha=digest(raw)
    for row in rows:row.update(original_sha256=original_sha,source_uri=uri,available_at=collected_at,
        collected_at=collected_at,published_at=None,historical_pit_certified=False)
    rights=('https://www.federalreserve.gov/disclaimer.htm' if feed.startswith('sloos_') else
            'https://www.newyorkfed.org/privacy/termsofuse' if feed.startswith('acm_') else
            'https://home.treasury.gov/footer/site-policies-and-notices')
    return rows,dict(feed=feed,original_sha256=original_sha,original_bytes=len(raw),observations=len(rows),
        normalized_sha256=digest(encoded(rows)),collected_at=collected_at,requested_through=last,period=period,
        resolved_period=rows[0]['period'] if feed=='sloos_index' else period,
        parser_version='xlrd-2.0.2' if feed=='acm_daily' else None,
        first_observation=min(r['observation_date'] for r in rows),last_observation=max(r['observation_date'] for r in rows),
        source_uri=uri,rights_uri=rights,source_admitted=False,training_admitted=False,historical_pit_certified=False,
        historical_use='FORWARD_CAPTURE_ONLY',feature_recipe_admission='INDEPENDENT_REVIEW_REQUIRED')


def manifest(receipt,normalized):
    return dict(schema=SCHEMA,**receipt,normalizer_sha256=digest(Path(__file__).read_bytes()),
        base_codec_sha256=digest(Path(p.__file__).read_bytes()),normalized_object_sha256=digest(normalized),
        normalized_object_bytes=len(normalized),fullrun_executed=False,accepted_state_written=False)


def store_capture(root,raw,feed,**kwargs):
    rows,receipt=normalize(raw,feed,**kwargs);buffer=io.BytesIO()
    with gzip.GzipFile(fileobj=buffer,mode='wb',filename='',mtime=0,compresslevel=6) as stream:
        for line in p._normalized_lines(rows):stream.write(line)
    normalized=buffer.getvalue();p.check(len(normalized)<=MAX_RAW,'FINANCING_NORMALIZED_BUDGET')
    meta=manifest(receipt,normalized);body=encoded(meta);root=Path(root)
    files={'objects/'+digest(raw):raw,'objects/'+digest(normalized):normalized,'generations/'+digest(body)+'.json':body}
    for name,value in files.items():
        path=root/name;p.check(not any(q.is_symlink() for q in (path,*path.parents)),'FINANCING_OUTPUT_SYMLINK')
        p.check(not path.exists() or p._bounded(path,input_limit(feed))==value,'FINANCING_OUTPUT_CONFLICT')
    for name,value in files.items():
        if not (root/name).exists():exclusive(root/name,value)
        p.check(p._bounded(root/name,input_limit(feed))==value,'FINANCING_OUTPUT_READBACK')
    return dict(manifest=meta,generation_sha256=digest(body),files=sorted(files))


def read_generation(transport,pin,*,cutoff):
    p.check(type(pin) is str and re.fullmatch('[a-f0-9]{64}',pin),'FINANCING_GENERATION_PIN')
    raw=p.read_object(transport,p.PREFIX+'/generations/'+pin+'.json',pin,65536);meta=p.f.strict_json(raw)
    p.check(type(meta) is dict and meta.get('schema')==SCHEMA and p.clock(meta['collected_at'])<=p.clock(cutoff),'FINANCING_GENERATION_CLOCK')
    original=p.read_object(transport,p.PREFIX+'/objects/'+meta['original_sha256'],meta['original_sha256'],input_limit(meta['feed']))
    normalized=p.read_object(transport,p.PREFIX+'/objects/'+meta['normalized_object_sha256'],meta['normalized_object_sha256'],MAX_RAW)
    rows,receipt=normalize(original,meta['feed'],collected_at=meta['collected_at'],through=meta['requested_through'],period=meta['period'])
    p.check(manifest(receipt,normalized)==meta and encoded(meta)==raw,'FINANCING_NORMALIZATION_REPLAY')
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(normalized),mode='rb') as stream:
            for expected in p._normalized_lines(rows):p.check(stream.readline(p.MAX_LINE_BYTES+1)==expected,'FINANCING_NORMALIZATION_REPLAY')
            p.check(stream.read(1)==b'','FINANCING_NORMALIZATION_REPLAY')
    except (OSError,EOFError,zlib.error):raise ValueError('FINANCING_NORMALIZATION_REPLAY') from None
    return rows,meta


def publish_capture(transport,root,pin,*,cutoff):
    class Prepared(LocalTransport):
        def read(self,path):
            p.check(path.startswith(p.PREFIX+'/'),'FINANCING_PREPARED_SCOPE')
            return super().read(path[len(p.PREFIX)+1:])
    _,meta=read_generation(Prepared(root),pin,cutoff=cutoff)
    for name in ('objects/'+meta['original_sha256'],'objects/'+meta['normalized_object_sha256'],'generations/'+pin+'.json'):
        body=p._bounded(Path(root)/name,input_limit(meta['feed']));transport.write(p.PREFIX+'/'+name,body)
        p.check(p.read_object(transport,p.PREFIX+'/'+name,digest(body),input_limit(meta['feed']))==body,'FINANCING_DURABLE_READBACK')
    rows,checked=read_generation(transport,pin,cutoff=cutoff)
    return dict(generation_sha256=pin,observations=len(rows),original_sha256=checked['original_sha256'],
        original_bytes=checked['original_bytes'],transport_readback_verified=transport.remote_verified is True,
        source_admitted=False,training_admitted=False,historical_pit_certified=False)

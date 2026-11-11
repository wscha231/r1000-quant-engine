"""Auction cohorts, survey populations, frequency, immutable replay and gates."""
import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import a4_financing_sources as f,a4_financing_analysis as a
from tools import a4_primary_sources as p,collect_a4_primary_data as c,market_analysis_engine as m
from tools.macro_history_sources import encoded,digest
from tools.macro_research_checkpoint import LocalTransport
from tests.a4_primary_sources_smoke import NOW,archive,nyfed


def auction(kind='Note',years=10):
    return [dict(securityType=kind,securityTerm=str(years)+'-Year',originalSecurityTerm=str(years)+'-Year',
        inflationProtected='No',floatingRate='No',competitiveAuctionCloseDate='2026-'+str(month).zfill(2)+'-06T00:00:00',
        cusip='12345678A',reopening='Yes' if month%3 else 'No',offeringAmount='1000',
        subtotalCompetitiveParAwardedInsideOfOfferingAmount='900',primaryDealersCompetitiveParAwarded='90',
        directBiddersCompetitiveParAwarded='180',indirectBiddersCompetitiveParAwarded='630',highYield='4.5',
        bidToCoverRatio='2.0' if month==11 else '2.5',grandTotalParAwarded='2000') for month in range(5,12)]


def survey(*,ndfi=True,demand=True):
    parts=['<!DOCTYPE html><html><h5>(Status of Policy as of October 2026)</h5>']
    def table(q,sector,text,kind):
        suffix='-'+sector;parent=q;leaf=q+suffix
        parts.append('<p id="'+parent+'">'+text+'</p><p id="'+leaf+'">'+sector+'</p>')
        parts.append('<table aria-labelledby="'+parent+' '+leaf+'"><tr><th id="'+leaf+'-col1">All Respondents</th></tr>')
        counts=[5,15,70,6,4] if kind=='tight' else [0,5,70,20,5]
        labels=f.TIGHT if kind=='tight' else f.DEMAND
        for label,count in [*zip(labels,counts),('Total',100)]:
            parts.append('<tr><th>'+label+'</th><td headers="'+leaf+'-col1-b">'+str(count)+
                '</td><td headers="'+leaf+'-col1-p">'+str(count)+'</td></tr>')
        parts.append('</table>')
    specs=[('q1','1','Credit standards: standards for small firms'),
        ('q7','1','Credit standards for construction and land development loans'),
        ('q8','1','Credit standards for nonfarm nonresidential loans'),
        ('q9','1','Credit standards for multifamily loans')]
    for q,s,text in specs:table(q,s,text,'tight')
    if demand:table('q10','1','Demand for construction and land development loans','demand')
    if ndfi:table('q29','1','Credit standards for private equity funds','tight')
    return ''.join(parts+['</html>']).encode()


def monthly():return b'RunDates,TERMYld,ACMFITYld,GSWYld\n30-Oct-2026,0.75,4.5,4.6\n'


XLS=bytes.fromhex('d0cf11e0a1b11ae1')+b'synthetic test book; parser boundary is mocked'


def daily_book(*,missing=False):
    import xlrd
    header=['DATE']+[f'{stem}{i:02d}' for stem in ('ACMY','ACMTP','ACMRNY') for i in range(1,11)]
    data=[header]
    for day in (4,5,6):
        row=[f'{day:02d}-Nov-2026']+[0.]*30
        for name,value in [('ACMY10',4.5),('ACMTP10',.75),('ACMRNY10',3.75)]:row[header.index(name)]=value
        data.append(row)
    if missing:data[-1][header.index('ACMTP10')]=''
    def cell(row,column):
        value=data[row][column]
        return SimpleNamespace(value=value,ctype=xlrd.XL_CELL_TEXT if column==0 else
            xlrd.XL_CELL_EMPTY if value=='' else xlrd.XL_CELL_NUMBER)
    sheet=SimpleNamespace(nrows=len(data),ncols=31,row_values=lambda r:data[r],cell=cell)
    book=SimpleNamespace(nsheets=2,datemode=0,sheet_names=lambda:['ACM Monthly','ACM Daily'],
        sheet_by_name=lambda n:sheet if n=='ACM Daily' else None,release_resources=lambda:None)
    return book,data


def fixture_fetch(url,*_):
    if url in {r[0] for r in p.FEEDS.values()}:
        feed=next(k for k,v in p.FEEDS.items() if v[0]==url)
        return nyfed(feed) if feed in {'sofr','tgcr','effr'} else archive(feed)
    if 'type=Note' in url:return encoded(auction())
    if 'type=Bond' in url:return encoded(auction('Bond',30))
    if url==f.URLS['sloos_index']:return b'<a href="/data/sloos/sloos-202610.htm">Oct</a>'
    if 'table-1.htm' in url:return survey()
    if url==f.URLS['acm_monthly']:return monthly()
    if url==f.URLS['acm_daily']:return XLS
    raise AssertionError('unexpected source')


class FinancingTests(unittest.TestCase):
    def normalize(self,raw,feed,**kwargs):return f.normalize(raw,feed,collected_at=NOW,**kwargs)

    def test_auction_native_ratios_and_competitive_denominator(self):
        rows,meta=self.normalize(encoded(auction()),'auction_notes')
        r=rows[-1];self.assertEqual(r['bid_to_cover'],2.)
        self.assertEqual(r['competitive_shares_percent'],dict(dealer=10.,direct=20.,indirect=70.))
        self.assertEqual(r['offering_usd'],1000.);self.assertFalse(meta['historical_pit_certified'])
        self.assertEqual(r['available_at'],NOW);self.assertIsNone(r['published_at'])

    def test_auction_peer_baselines_never_mix_maturities_or_future_results(self):
        rows,_=self.normalize(encoded(auction()),'auction_notes')
        future=auction()[0];future['competitiveAuctionCloseDate']='2026-12-06T00:00:00'
        future.update(originalSecurityTerm='50-Year',bidToCoverRatio='not-yet-known')
        extended,_=self.normalize(encoded(auction()+[future]),'auction_notes')
        # New original bytes have a new provenance hash; prior numeric decisions
        # must be unchanged when the added result is after the decision cutoff.
        self.assertNotEqual(rows[0]['original_sha256'],extended[0]['original_sha256'])
        self.assertEqual([{k:v for k,v in r.items() if k!='original_sha256'} for r in rows],
                         [{k:v for k,v in r.items() if k!='original_sha256'} for r in extended])
        result=a.analyze(rows,cutoff=NOW)['treasury_auctions'][0]
        self.assertEqual(result['prior_six_same_original_term_btc_mean'],2.5)
        self.assertIsNone(result['prior_six_same_issuance_type_btc_mean'])
        self.assertIsNone(result['tail_bp']);self.assertEqual(result['comparison'],'BELOW_PRIOR_SIX_BTC')

    def test_auction_wrong_type_duplicate_and_component_mismatch_refuse(self):
        for edit in (lambda r:r.update(securityType='Bond'),lambda r:r.update(originalSecurityTerm='30-Year'),
                     lambda r:r.update(primaryDealersCompetitiveParAwarded='91'),lambda r:r.update(bidToCoverRatio='NaN')):
            raw=auction();edit(raw[0])
            with self.assertRaises(ValueError):self.normalize(encoded(raw),'auction_notes')
        with self.assertRaises(ValueError):self.normalize(encoded(auction()+auction()[:1]),'auction_notes')
        with self.assertRaises(ValueError):f.amount('1000000000000000.01')

    def test_sloos_question_denominators_and_demand_are_separate(self):
        rows,_=self.normalize(survey(),'sloos_domestic',period='202610')
        values={(r['sector'],r['measure']):r for r in rows}
        self.assertEqual(values[('small_firms','NET_TIGHTENING')]['value'],10.)
        self.assertEqual(values[('cre_construction','NET_STRONGER_DEMAND')]['value'],-20.)
        self.assertEqual(values[('ndfi_private_equity','NET_TIGHTENING')]['respondents'],100)
        self.assertTrue(all(r['population']=='DOMESTIC_SLOOS_RESPONDENTS_NOT_H8_AGGREGATES' for r in rows))

    def test_sloos_schema_period_and_wrong_header_do_not_silently_relabel(self):
        for raw,period in [(survey(),'202607'),(survey().replace(b'All Respondents',b'Foreign Banks'),'202610'),
                           (survey().replace(b'>100</td>',b'>99</td>'),'202610')]:
            with self.assertRaises(ValueError):self.normalize(raw,'sloos_domestic',period=period)
        rows,_=self.normalize(survey(ndfi=False),'sloos_domestic',period='202610')
        result=a.analyze(rows,cutoff=NOW)
        self.assertEqual(result['lending_standards']['ndfi_status'],'NOT_ASKED_OR_NOT_VERIFIED_THIS_RELEASE')

    def test_sloos_release_discovery_rejects_foreign_and_future_links(self):
        raw=b'<a href="/data/sloos/sloos-202610.htm">Oct</a><a href="/data/sloos/sloos-202701.htm">Jan</a>'
        rows,_=self.normalize(raw,'sloos_index');self.assertEqual(rows[0]['period'],'202610')
        with self.assertRaises(ValueError):self.normalize(b'<a href="https://other.test/sloos-202610.htm">x</a>','sloos_index')

    def test_monthly_chart_is_not_daily_or_historical_pit(self):
        rows,meta=self.normalize(monthly(),'acm_monthly');result=a.analyze(rows,cutoff=NOW)
        self.assertEqual(rows[0]['frequency'],'monthly');self.assertFalse(rows[0]['daily_series_verified'])
        self.assertFalse(meta['training_admitted']);self.assertEqual(result['term_premium']['status'],'MONTHLY_CONTEXT_ONLY')
        self.assertFalse(result['readiness']['daily_term_premium'])
        with self.assertRaises(ValueError):self.normalize(monthly()+b'01-Oct-2026,1,2,3\n','acm_monthly')

    def test_daily_xls_sheet_decomposition_and_latest_missing_are_explicit(self):
        for missing in (False,True):
            book,_=daily_book(missing=missing)
            with patch('xlrd.open_workbook',return_value=book):rows,meta=self.normalize(XLS,'acm_daily')
            result=a.analyze(rows,cutoff=NOW)
            self.assertEqual(rows[-1]['frequency'],'daily');self.assertEqual(meta['parser_version'],'xlrd-2.0.2')
            self.assertEqual(result['readiness']['daily_term_premium'],not missing)
            self.assertEqual(result['term_premium']['latest']['observation_date'],'2026-11-06')
        book,data=daily_book();data[-1][10]=5.
        with patch('xlrd.open_workbook',return_value=book),self.assertRaises(ValueError):self.normalize(XLS,'acm_daily')

    def test_daily_xls_has_narrow_size_and_schema_limits(self):
        self.assertEqual(f.input_limit('acm_daily'),12*1024**2)
        self.assertEqual(f.input_limit('sloos_domestic'),8*1024**2)
        with self.assertRaises(ValueError):self.normalize(b'not an OLE workbook','acm_daily')
        book,data=daily_book();data[0][0]='MONTH'
        with patch('xlrd.open_workbook',return_value=book),self.assertRaises(ValueError):self.normalize(XLS,'acm_daily')

    def test_source_paths_html_budgets_and_unlicensed_urls_are_closed(self):
        for feed,period in [('ici_mmf',None),('sloos_domestic','../202610'),('sloos_domestic','202611')]:
            with self.assertRaises(ValueError):f.source_uri(feed,period)
        with self.assertRaises(ValueError):f.Document(b'<html>'+b'x'*(2*1024**2))
        self.assertTrue(all('fred' not in url and 'ici.org' not in url for url in f.URLS.values()))
        result=a.analyze([],cutoff=NOW)
        self.assertEqual(result['credit_fragility']['status'],'RIGHTS_EVIDENCE_REQUIRED')
        self.assertEqual(result['fund_flows']['status'],'RIGHTS_EVIDENCE_REQUIRED')
        self.assertFalse(result['automatic_winner_exit_allowed']);self.assertFalse(result['portfolio_weights_allowed'])

    def test_shared_generation_replay_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepared=f.store_capture(root,monthly(),'acm_monthly',collected_at=NOW)
            class Archive(LocalTransport):
                def read(self,path):return super().read(path[len(p.PREFIX)+1:])
            reader=Archive(root);rows,_=f.read_generation(reader,prepared['generation_sha256'],cutoff=NOW)
            self.assertEqual(len(rows),1)
            path=root/'objects'/prepared['manifest']['original_sha256'];path.write_bytes(b'changed')
            with self.assertRaises(ValueError):f.read_generation(reader,prepared['generation_sha256'],cutoff=NOW)

    def test_stale_context_and_future_availability_do_not_mark_ready(self):
        rows,_=self.normalize(encoded(auction()),'auction_notes')
        result=a.analyze(rows,cutoff='2027-02-07T10:00:00Z')
        self.assertFalse(result['readiness']['treasury_auction_context'])
        self.assertTrue(all(r['status']=='STALE' for r in result['treasury_auctions']))
        rows[-1]['available_at']='2026-12-07T10:00:00Z'
        with self.assertRaises(ValueError):a.analyze(rows,cutoff=NOW)

    def test_normalized_gzip_variant_replays_without_recompression(self):
        with tempfile.TemporaryDirectory() as tmp:
            local=LocalTransport(tmp)
            rows,receipt=self.normalize(monthly(),'acm_monthly')
            zipped=bytearray(gzip.compress(b''.join(encoded(r) for r in rows),compresslevel=1,mtime=0));zipped[9]=3
            raw=bytes(zipped);meta=f.manifest(receipt,raw);pin=digest(encoded(meta))
            local.write(p.PREFIX+'/objects/'+digest(monthly()),monthly())
            local.write(p.PREFIX+'/objects/'+digest(raw),raw)
            local.write(p.PREFIX+'/generations/'+pin+'.json',encoded(meta))
            replay,_=f.read_generation(local,pin,cutoff=NOW);self.assertEqual(rows,replay)

    def test_combined_collection_keeps_core_and_external_authority_closed(self):
        book,_=daily_book()
        with tempfile.TemporaryDirectory() as tmp,patch.object(p,'now',return_value=NOW),patch('xlrd.open_workbook',return_value=book):
            root=Path(tmp)/'capture';result=c.collect(root,code_sha='a'*40,fetcher=fixture_fetch,include_financing=True)
            self.assertEqual(result['failures'],[]);self.assertEqual(result['originals'],12)
            report=json.loads((root/'market_analysis.json').read_bytes())
            self.assertTrue(report['financing_conditions']['readiness']['treasury_auction_context'])
            self.assertEqual(report['status'],'DATA_BLOCKED');self.assertFalse(result['model_fit_performed'])
            self.assertIn('Treasury auction demand',m.render_report(report))

    def test_missing_index_keeps_core_partial_and_never_reuses_an_old_survey(self):
        calls=[]
        def fetch(url,*args):
            calls.append(url)
            return b'<html>unavailable</html>' if url==f.URLS['sloos_index'] else fixture_fetch(url,*args)
        book,_=daily_book()
        with tempfile.TemporaryDirectory() as tmp,patch.object(p,'now',return_value=NOW),patch('xlrd.open_workbook',return_value=book):
            root=Path(tmp)/'capture';result=c.collect(root,code_sha='a'*40,fetcher=fetch,include_financing=True)
            self.assertEqual(result['status'],'PARTIAL_RESEARCH_CAPTURE')
            self.assertEqual({r['feed'] for r in result['failures']},{'sloos_index','sloos_domestic'})
            self.assertFalse(any('table-1.htm' in url for url in calls))
            report=json.loads((root/'market_analysis.json').read_bytes())
            self.assertFalse(report['financing_conditions']['readiness']['sloos_context'])
            self.assertFalse(result['accepted_portfolio_changed'])

    def test_v1_and_unregistered_v2_financing_inputs_refuse(self):
        spec=dict(kind='financing_primary',feed='acm_monthly',path='source.csv',sha256=digest(monthly()),
            status='COLLECTED',collected_at=NOW,observation_through='2026-11-07',source_period=None)
        request=dict(schema=m.REQUEST_SCHEMA_V2,market='US',session=m.current_session(NOW),available_at=NOW,
            expires_at='2026-11-08T10:00:00Z',inputs=[spec])
        m.verify_request(encoded(request),digest(encoded(request)),NOW,request['session'])
        request['schema']=m.REQUEST_SCHEMA
        with self.assertRaises(ValueError):m.verify_request(encoded(request),digest(encoded(request)),NOW,request['session'])
        request['schema']=m.REQUEST_SCHEMA_V2;spec['feed']='ici_unverified'
        with self.assertRaises(ValueError):m.verify_request(encoded(request),digest(encoded(request)),NOW,request['session'])


if __name__=='__main__':unittest.main(verbosity=1)

"""Synthetic source-shape/adapter tests; no SEC truth or market performance."""
from __future__ import annotations
import copy
import csv
from datetime import timedelta
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from research.news_event_alpha_v1 import source_bridge as S
from research.news_event_alpha_v1 import admission as A
from research.news_event_alpha_v1 import runtime as R
from research.news_event_alpha_v1 import execution as E
from news_event_p0_receipt_execution_smoke import write_bundle, fixture, NOW


def sec_payload(cik='0000111111', form='8-K', date='2024-04-23', accepted='2024-04-23T19:00:00Z',items='1.01,2.03',acc='0000111111-24-000001',primary='report.htm'):
    return {'cik':int(cik),'tickers':['CURRENT_NOT_PIT'], 'filings':{'recent':{
        'accessionNumber':[acc],'form':[form],'filingDate':[date],'primaryDocument':[primary],
        'acceptanceDateTime':[accepted],'items':[items]},'files':[]}}


def parse(p=None,**kw):
    args=dict(cik='0000111111',source_url='https://data.sec.gov/submissions/CIK0000111111.json',
              ingested_at='2026-09-18T10:00:00Z',window_start='2024-01-01',window_end='2025-12-31')
    args.update(kw)
    return S.parse_submissions(R.canonical_bytes(sec_payload() if p is None else p),**args)


def csv_bytes(prices):
    fields=['stable_security_id','session','total_return_index','available_at','currency','feed','return_convention','status','tradable']
    out=io.StringIO(newline='');w=csv.DictWriter(out,fieldnames=fields);w.writeheader()
    for p in prices:
        r={k:p[k] for k in fields};r['tradable']='true' if r['tradable'] else 'false';w.writerow(r)
    return out.getvalue().encode()


def write_export(root: Path):
    m=write_bundle(root)
    for e in list(m['files']):
        if e['role'] in {'snapshots','prices','coverage'}:
            (root/e['path']).unlink();m['files'].remove(e)
    (root/'manifest.json').unlink()
    cal,prices,_,_,_,cutoff=fixture()
    def put(path,role,data,**meta):
        if type(data) is not bytes:data=R.canonical_bytes(data)
        (root/path).parent.mkdir(parents=True,exist_ok=True);(root/path).write_bytes(data)
        m['files'][:]=[e for e in m['files'] if e['path']!=path]
        m['files'].append({'path':path,'role':role,'bytes':len(data),'sha256':A.sha256(data),'source_id':'test',**meta})
    docs=A.rows((root/'documents.jsonl').read_bytes());securities=A.rows((root/'securities.jsonl').read_bytes())
    reviews=[]
    accepted=(R.utc(cal[80]['market_close_utc'])-timedelta(hours=2)).isoformat()
    public=(R.utc(cal[80]['market_close_utc'])-timedelta(hours=1)).isoformat()
    for sid,cik,form in [('A','0000111111','8-K'),('B','0000222222','6-K')]:
        acc=f'{cik}-24-000001';fn='report.htm';url=S.filing_url(cik,acc,fn)
        p=sec_payload(cik,form,cal[80]['session'],accepted,'1.01,2.03',acc,fn)
        put(f'raw/sec-{sid}.json','sec_submissions',p,cik=cik,source_url=f'https://data.sec.gov/submissions/CIK{cik}.json',ingested_at=m['generated_at'])
        raw=f'SYNTHETIC {form}. NO MARKET CLAIM. issuer {sid}'.encode()
        put(f'raw/primary-{sid}.htm','raw_object',raw)
        docs.append({'document_id':'primary:'+sid,'raw_path':f'raw/primary-{sid}.htm','raw_sha256':A.sha256(raw),
            'source_id':'test','source_public_at':public,'ingested_at':m['generated_at'],
            'revision_policy':'IMMUTABLE_PUBLIC_VERSION','source_url':url})
        securities[['A','B','SPY'].index(sid)]['cik']=cik
        reviews.append({'candidate_id':f'sec:{cik}:{acc}','stable_security_id':'TEST:'+sid,
            'state':'REVIEWED_FOR_ASSEMBLY_NOT_APPROVAL','reviewer_id':'synthetic-reviewer',
            'reviewed_at':m['generated_at'],'available_at':public,
            'publication_time_basis':'DOCUMENTED_PUBLIC_TIME_WITH_EVIDENCE','publication_evidence_document_id':'primary:'+sid,
            'source_document_ids':['primary:'+sid],'role':'DIRECT','economic_value_confirmed':False,'business_relation_new':False})
    for path,role,rr in [('documents.jsonl','documents',docs),('securities.jsonl','securities',securities),('reviews.jsonl','reviews',reviews)]:
        put(path,role,b''.join(R.canonical_bytes(r) for r in rr))
    put('prices.csv','prices_csv',csv_bytes(prices))
    m.update(schema='news-source-export-p0.3',window_start='2024-01-01',window_end='2025-12-31',adapter_source_id='test')
    for k in ('consumer','generation','parent_receipt_sha256'):m.pop(k,None)
    m['selection_rule']='SYNTHETIC_FIXTURE_ONLY'
    (root/'export_manifest.json').write_bytes(R.canonical_bytes(m))
    return m


def mutate(root,path,fn,*,lines=False):
    b=(root/path).read_bytes();v=A.rows(b) if lines else A.json_load(b);fn(v)
    raw=b''.join(R.canonical_bytes(r) for r in v) if lines else R.canonical_bytes(v)
    (root/path).write_bytes(raw)
    m=A.json_load((root/'export_manifest.json').read_bytes())
    for e in m['files']:
        if e['path']==path:e.update(bytes=len(raw),sha256=A.sha256(raw))
    (root/'export_manifest.json').write_bytes(R.canonical_bytes(m))


class SecIndexTests(unittest.TestCase):
    def test_recent_multi_item_is_not_auto_bullish(self):
        c=parse()['candidates'][0];self.assertEqual(c['descriptive_event_tags'],['MATERIAL_AGREEMENT_UNCLASSIFIED','FINANCIAL_OBLIGATION']);self.assertIsNone(c['economic_amount_usd']);self.assertIsNone(c['sentiment'])
    def test_acceptance_is_not_publication(self):
        c=parse()['candidates'][0];self.assertIsNotNone(c['accepted_at']);self.assertIsNone(c['source_public_at']);self.assertIsNone(c['available_at'])
    def test_current_ticker_not_historical_identity(self):
        c=parse()['candidates'][0];self.assertNotIn('security_id',c);self.assertFalse(c['listing_verified'])
    def test_6k_does_not_use_8k_tags(self):
        c=parse(sec_payload(form='6-K'))['candidates'][0];self.assertEqual(c['descriptive_event_tags'],['FPI_DISCLOSURE_UNCLASSIFIED'])
    def test_6k_amendment_preserved_not_guessed(self):
        c=parse(sec_payload(form='6-K/A'))['candidates'][0];self.assertTrue(c['is_amendment']);self.assertIsNone(c['amends_event_id'])
    def test_8k_amendment_retained(self):self.assertEqual(parse(sec_payload(form='8-K/A'))['candidates'][0]['form_type'],'8-K/A')
    def test_flat_history_json_supported(self):
        p=sec_payload()['filings']['recent'];r=parse(p,source_url='https://data.sec.gov/submissions/CIK0000111111-submissions-001.json');self.assertEqual(len(r['candidates']),1)
    def test_date_only_acceptance_not_midnight(self):self.assertIsNone(parse(sec_payload(accepted='2024-04-23'))['candidates'][0]['accepted_at'])
    def test_naive_acceptance_not_timezone_guessed(self):self.assertIsNone(parse(sec_payload(accepted='2024-04-23T19:00:00'))['candidates'][0]['accepted_at'])
    def test_wrong_cik_rejected(self):
        with self.assertRaisesRegex(R.ContractError,'PAYLOAD_CIK'):parse(sec_payload(cik='0000222222'))
    def test_column_misalignment_rejected(self):
        p=sec_payload();p['filings']['recent']['items']=[]
        with self.assertRaisesRegex(R.ContractError,'COLUMN_LENGTH'):parse(p)
    def test_invalid_accession_rejected(self):
        with self.assertRaisesRegex(R.ContractError,'ACCESSION'):parse(sec_payload(acc='../../evil'))
    def test_url_cik_not_accession_prefix(self):
        url=S.filing_url('0000111111','0000950170-24-012345','report.htm');self.assertIn('/111111/000095017024012345/',url)
    def test_primary_traversal_rejected(self):
        with self.assertRaises(R.ContractError):parse(sec_payload(primary='../report.htm'))
    def test_unsupported_forms_remain_exclusion(self):
        r=parse(sec_payload(form='10-K'));self.assertEqual(len(r['excluded_records']),1);self.assertFalse(r['candidates'])
    def test_window_filter_is_explicit(self):self.assertEqual(parse(window_start='2025-01-01')['excluded_records'][0]['reason'],'OUTSIDE_COLLECTION_WINDOW')
    def test_missing_items_no_contract_guess(self):
        p=sec_payload();del p['filings']['recent']['items'];self.assertEqual(parse(p)['candidates'][0]['descriptive_event_tags'],['CURRENT_REPORT_UNCLASSIFIED'])
    def test_old_history_page_missing_is_visible(self):
        p=sec_payload();p['filings']['files']=[{'name':'CIK0000111111-submissions-001.json','filingFrom':'2024-01-01','filingTo':'2024-12-31'}]
        r=S.merge_indexes([parse(p)],set());self.assertFalse(r['declared_history_pages_complete']);self.assertEqual(len(r['unresolved_history_urls']),1)
    def test_dedup_does_not_inflate_economic_events(self):
        r=parse();m=S.merge_indexes([r,copy.deepcopy(r)],set());self.assertEqual(len(m['candidates']),1)
    def test_conflicting_reprint_fails_closed(self):
        a=parse();b=parse(sec_payload(items='1.02'))
        with self.assertRaisesRegex(R.ContractError,'CONFLICTING'):S.merge_indexes([a,b],set())
    def test_future_acceptance_retained_for_review(self):self.assertIsNone(parse(sec_payload(accepted='2027-01-01T00:00:00Z'))['candidates'][0]['accepted_at'])
    def test_no_primary_path_is_not_dropped(self):self.assertIn('PRIMARY_DOCUMENT_MISSING',parse(sec_payload(primary=''))['candidates'][0]['blockers'])
    def test_flat_shape_not_mistaken_for_current(self):
        with self.assertRaisesRegex(R.ContractError,'FLAT_JSON'):parse(sec_payload()['filings']['recent'])
    def test_url_restrictions(self):
        for url in ['http://data.sec.gov/submissions/CIK0000111111.json','https://data.sec.gov.evil/submissions/CIK0000111111.json',
                    'https://user:pass@data.sec.gov/submissions/CIK0000111111.json','https://data.sec.gov/submissions/CIK0000111111.json?token=bad',
                    'https://data.sec.gov:443/submissions/CIK0000111111.json']:
            with self.subTest(url=url),self.assertRaises(R.ContractError):S.sec_url(url)


class PriceAdapterTests(unittest.TestCase):
    def setUp(self):self.raw=csv_bytes(fixture(6)[1][:15])
    def test_roundtrip_total_return_csv(self):self.assertEqual(S.parse_price_csv(self.raw)[0]['total_return_index'],100)
    def test_raw_close_not_promoted(self):
        with self.assertRaisesRegex(R.ContractError,'COLUMNS'):S.parse_price_csv(self.raw.replace(b'total_return_index',b'close'))
    def test_adjusted_close_not_assumed_tri(self):
        with self.assertRaisesRegex(R.ContractError,'COLUMNS'):S.parse_price_csv(self.raw.replace(b'total_return_index',b'Adj Close'))
    def test_missing_available_at_rejected(self):
        with self.assertRaises(R.ContractError):S.parse_price_csv(self.raw.replace(b'available_at',b'source_date'))
    def test_boolean_typo_rejected(self):
        with self.assertRaisesRegex(R.ContractError,'BOOLEAN'):S.parse_price_csv(self.raw.replace(b'true',b'yes'))
    def test_nonfinite_rejected(self):
        with self.assertRaisesRegex(R.ContractError,'NUMBER'):S.parse_price_csv(self.raw.replace(b'100.0',b'NaN',1))
    def test_duplicate_columns_rejected(self):
        with self.assertRaises(R.ContractError):S.parse_price_csv(self.raw.replace(b'feed',b'currency',1))
    def test_utf8_bom_supported(self):self.assertEqual(len(S.parse_price_csv(b'\xef\xbb\xbf'+self.raw)),15)


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.src=self.root/'export';self.src.mkdir();write_export(self.src);self.dst=self.root/'out'
    def tearDown(self):self.tmp.cleanup()
    def run_assembly(self):return S.assemble_export(self.src,self.dst,now=NOW)
    def test_sec_to_snapshots_to_existing_admission(self):
        r=self.run_assembly();self.assertEqual(r['snapshots'],8);self.assertEqual(r['included_event_security_revisions'],2);self.assertFalse(r['real_input_approval_granted']);self.assertEqual(r['selector_weight'],0)
    def test_next_close_bridge_end_to_end(self):
        self.run_assembly();b=A.verify_bundle(self.dst/'bundle',now=NOW)
        out=E.attach_executable_outcomes(b.rows('snapshots'),b.rows('prices'),b.rows('sessions'),as_of=b.manifest['data_cutoff'],policy=b.json('policy'))
        self.assertEqual(len(out),48);self.assertNotEqual(out[0]['entry_session'],out[0]['checkpoint_session'])
    def test_no_reviews_means_no_guessed_events(self):
        mutate(self.src,'reviews.jsonl',lambda rr:rr.clear(),lines=True);r=self.run_assembly();self.assertEqual(r['snapshots'],0);self.assertEqual(r['rejected_events'],2)
    def test_no_automatic_real_approval(self):
        self.run_assembly();b=A.verify_bundle(self.dst/'bundle',now=NOW)
        with self.assertRaisesRegex(R.ContractError,'NOT_IN_REVIEWED_REGISTRY'):
            A.require_reviewed_receipt(b,b'{}',reviewed_registry={'schema':'news-input-approval-registry-p0.2','approvals':[]},expected_parent=None,now=NOW)
    def test_duplicate_review_rejected(self):
        mutate(self.src,'reviews.jsonl',lambda rr:rr.append(copy.deepcopy(rr[0])),lines=True)
        with self.assertRaisesRegex(R.ContractError,'DUPLICATE'):self.run_assembly()
    def test_wrong_issuer_mapping_not_included(self):
        mutate(self.src,'securities.jsonl',lambda rr:rr[0].update(cik='0000333333'),lines=True);r=self.run_assembly();self.assertEqual(r['included_event_security_revisions'],1)
    def test_unknown_stable_id_is_excluded(self):
        mutate(self.src,'reviews.jsonl',lambda rr:rr[0].update(stable_security_id='UNKNOWN'),lines=True);self.assertEqual(self.run_assembly()['rejected_events'],1)
    def test_string_false_rejected(self):
        mutate(self.src,'reviews.jsonl',lambda rr:rr[0].update(business_relation_new='false'),lines=True)
        with self.assertRaises(R.ContractError):self.run_assembly()
    def test_amount_without_citation_blocked(self):
        mutate(self.src,'reviews.jsonl',lambda rr:rr[0].update(economic_value_confirmed=True,economic_amount_usd=500),lines=True)
        with self.assertRaisesRegex(R.ContractError,'FACT_EVIDENCE'):self.run_assembly()
    def test_primary_document_must_match_accession(self):
        mutate(self.src,'documents.jsonl',lambda rr:rr[1].update(source_url='https://www.sec.gov/Archives/edgar/data/111111/000011111124000099/report.htm'),lines=True)
        with self.assertRaisesRegex(R.ContractError,'PRIMARY_DOCUMENT'):self.run_assembly()
    def test_later_document_cannot_rewrite_event(self):
        mutate(self.src,'documents.jsonl',lambda rr:rr[1].update(source_public_at='2025-01-01T00:00:00Z'),lines=True)
        with self.assertRaisesRegex(R.ContractError,'LATE_EVIDENCE'):self.run_assembly()
    def test_captured_today_not_forward_history(self):
        m=A.json_load((self.src/'export_manifest.json').read_bytes());m['origin']='FORWARD_OBSERVED';(self.src/'export_manifest.json').write_bytes(R.canonical_bytes(m))
        with self.assertRaisesRegex(R.ContractError,'RECONSTRUCTION_NOT_FORWARD'):self.run_assembly()
    def test_output_cannot_overwrite(self):
        self.dst.mkdir();(self.dst/'user.txt').write_text('KEEP')
        with self.assertRaisesRegex(R.ContractError,'OUTPUT_EXISTS'):self.run_assembly()
        self.assertEqual((self.dst/'user.txt').read_text(),'KEEP')
    def test_export_hash_tamper_rejected(self):
        with (self.src/'prices.csv').open('ab') as f:f.write(b'bad')
        with self.assertRaisesRegex(R.ContractError,'HASH_MISMATCH'):self.run_assembly()
    def test_unknown_unlisted_file_blocked(self):
        (self.src/'auth.json').write_text('not-a-token')
        with self.assertRaisesRegex(R.ContractError,'UNDECLARED'):self.run_assembly()
    def test_missing_history_still_shown_on_bundle_report(self):
        mutate(self.src,'raw/sec-A.json',lambda p:p['filings'].update(files=[{'name':'CIK0000111111-submissions-001.json','filingFrom':'2024-01-01','filingTo':'2024-12-31'}]))
        r=self.run_assembly();self.assertFalse(r['history_pages_complete']);self.assertEqual(r['missing_history_pages'],1)
    def test_no_theme_breadth_invented(self):
        self.run_assembly();b=A.verify_bundle(self.dst/'bundle',now=NOW)
        self.assertTrue(all(s['theme_breadth_checkpoint'] is None and not s['confirmed_combo'] for s in b.rows('snapshots')))
    def test_pre_rs60_uses_prior_data(self):
        self.run_assembly();b=A.verify_bundle(self.dst/'bundle',now=NOW);s=b.rows('snapshots')[0]
        self.assertAlmostEqual(s['pre_rs60'],1.003**60-1.001**60)
    def test_retains_6k_form_in_checkpoint(self):
        self.run_assembly();b=A.verify_bundle(self.dst/'bundle',now=NOW)
        self.assertEqual({s['sec_form_type'] for s in b.rows('snapshots')},{'8-K','6-K'})
    def test_rights_failure_keeps_no_success_report(self):
        mutate(self.src,'rights.json',lambda v:v['sources'][0].update(store=False))
        with self.assertRaisesRegex(R.ContractError,'RIGHTS_NOT_GRANTED'):self.run_assembly()
        self.assertFalse((self.dst/'ASSEMBLY_REPORT.json').exists())
    def test_cli_index_readonly(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/prepare_news_event_sources_p0.py'),'index','--export',str(self.src)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr);self.assertFalse(self.dst.exists());self.assertIn('INDEXED_REVIEW_REQUIRED',p.stdout)
    def test_cli_capture_network_opt_in_required(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/prepare_news_event_sources_p0.py'),'capture','--plan','missing.json','--output-dir',str(self.dst),'--lock-file',str(self.root/'lock')],capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0);self.assertIn('SEC_NETWORK_NOT_AUTHORIZED',p.stderr);self.assertFalse(self.dst.exists())
    def cite_amount(self, change=None):
        raw=(self.src/'raw/primary-A.htm').read_bytes()
        def edit(rr):
            e={'document_id':'primary:A','raw_sha256':A.sha256(raw),'byte_start':0,'byte_end':9,
               'quote_utf8':raw[:9].decode(),'locator':'raw bytes 0:9'}
            if change: e.update(change)
            rr[0].update(economic_value_confirmed=True,economic_amount_usd=500,economic_currency='USD',
                         economic_amount_kind='CEILING',fact_evidence={'economic_amount_usd':e})
        mutate(self.src,'reviews.jsonl',edit,lines=True)
    def test_cited_ceiling_kept_separate_from_revenue(self):
        self.cite_amount();self.run_assembly();b=A.verify_bundle(self.dst/'bundle',now=NOW)
        self.assertEqual(b.rows('snapshots')[0]['economic_amount_kind'],'CEILING')
        self.assertNotIn('revenue',b.rows('snapshots')[0])
    def test_fabricated_quote_rejected(self):
        self.cite_amount({'quote_utf8':'NOT ACTUAL'})
        with self.assertRaisesRegex(R.ContractError,'CITATION_QUOTE'):self.run_assembly()
    def test_fabricated_citation_hash_rejected(self):
        self.cite_amount({'raw_sha256':'0'*64})
        with self.assertRaisesRegex(R.ContractError,'CITATION_HASH'):self.run_assembly()
    def test_bad_citation_span_rejected(self):
        self.cite_amount({'byte_start':-1})
        with self.assertRaisesRegex(R.ContractError,'CITATION_RANGE'):self.run_assembly()
    def test_supplied_review_is_hash_bound(self):
        self.run_assembly();b=A.verify_bundle(self.dst/'bundle',now=NOW)
        r=A.rows((self.src/'reviews.jsonl').read_bytes())[0]
        self.assertEqual(b.rows('snapshots')[0]['review_record_sha256'],A.sha256(R.canonical_bytes(r)))
    def test_index_only_export_need_not_have_prices(self):
        m=A.json_load((self.src/'export_manifest.json').read_bytes())
        keep=[e for e in m['files'] if e['role']=='sec_submissions']
        for e in m['files']:
            if e not in keep:(self.src/e['path']).unlink()
        m['files']=keep;(self.src/'export_manifest.json').write_bytes(R.canonical_bytes(m))
        m,f,_=S.load_export(self.src,now=NOW,index_only=True);self.assertEqual(len(S.index_export(m,f)['candidates']),2)

if __name__=='__main__':unittest.main(verbosity=2)

"""Mocked network and real temporary local storage; zero market-data claims."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from research.news_event_alpha_v1 import source_capture as C
from research.news_event_alpha_v1 import source_bridge as S
from research.news_event_alpha_v1 import admission as A
from research.news_event_alpha_v1 import runtime as R
from news_event_p0_source_bridge_smoke import sec_payload

NOW='2026-09-19T12:00:00+00:00'
UA='Synthetic test contact@example.invalid'
URL='https://data.sec.gov/submissions/CIK0000111111.json'


def plan():return {'schema':'news-sec-capture-plan-p0.3','ciks':['0000111111'],
    'window_start':'2024-01-01','window_end':'2025-12-31','source_commit':'a'*40,
    'data_cutoff':'2026-09-18T00:00:00Z','max_filings':100,'max_requests':20,
    'selection_rule':'EARLIEST_BY_FILED_DATE_THEN_CIK_ACCESSION_NO_RETURNS'}


class Clock:
    def __init__(self):self.t=0;self.waits=[]
    def mono(self):return self.t
    def sleep(self,s):self.t+=s;self.waits.append(s)


class CaptureStoreTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.clock=Clock();self.calls=[]
        def fetch(u,a):self.calls.append(u);return R.canonical_bytes(sec_payload())
        self.store=C.CaptureStore(self.root/'store',user_agent=UA,request_budget=3,clock=lambda:NOW,
            fetcher=fetch,monotonic=self.clock.mono,sleeper=self.clock.sleep)
    def tearDown(self):self.t.cleanup()
    def test_content_address_and_receipt(self):
        raw,r=self.store.get(URL);self.assertEqual((self.root/'store'/'objects'/A.sha256(raw)).read_bytes(),raw);self.assertFalse(r['historical_pit_certified'])
    def test_resume_reuses_bytes_not_network(self):
        a=self.store.get(URL);b=self.store.get(URL);self.assertEqual(a,b);self.assertEqual(len(self.calls),1);self.assertEqual(self.store.reused,1)
    def test_two_calls_are_rate_limited(self):
        self.store.get(URL);self.store.get(URL.replace('111111','222222'));self.assertEqual(self.clock.waits,[.5])
    def test_request_budget_stops(self):
        self.store.request_budget=1;self.store.get(URL)
        with self.assertRaisesRegex(C.CaptureBlocked,'BUDGET'):self.store.get(URL.replace('111111','222222'))
        self.assertEqual(len(self.calls),1)
    def test_tampered_cached_object_not_reused(self):
        raw,r=self.store.get(URL);(self.root/'store'/'objects'/r['raw_sha256']).write_bytes(b'changed')
        with self.assertRaisesRegex(R.ContractError,'RECEIPT_BYTES'):self.store.get(URL)
    def test_tampered_cached_url_rejected(self):
        self.store.get(URL);p=next((self.root/'store'/'receipts').iterdir());r=json.loads(p.read_bytes());r['source_url']=URL+'?x';p.write_bytes(R.canonical_bytes(r))
        with self.assertRaisesRegex(R.ContractError,'RECEIPT_IDENTITY'):self.store.get(URL)
    def test_http429_no_immediate_retry(self):
        def blocked(u,a):raise C.CaptureBlocked('HTTP_429','120')
        self.store.fetcher=blocked
        with self.assertRaisesRegex(C.CaptureBlocked,'HTTP_429'):self.store.get(URL)
        self.assertEqual(self.store.calls,1);self.assertFalse((self.root/'store'/'receipts').exists())
    def test_html_instead_of_json_not_accepted(self):
        self.store.fetcher=lambda u,a:b'<html>access denied</html>'
        with self.assertRaises(R.ContractError):self.store.get(URL)
        self.assertFalse((self.root/'store'/'receipts').exists())
    def test_oversized_response_rejected(self):
        self.store.fetcher=lambda u,a:b'x'*8
        with patch.object(C,'MAX_BODY',4),self.assertRaisesRegex(R.ContractError,'BODY_BUDGET'):self.store.get(URL)
    def test_storage_budget_rejected(self):
        with patch.object(C,'MAX_STORED',1),self.assertRaisesRegex(R.ContractError,'STORAGE_BUDGET'):self.store.get(URL)
    def test_future_receipt_rejected(self):
        self.store.get(URL);p=next((self.root/'store'/'receipts').iterdir());r=json.loads(p.read_bytes());r['ingested_at']='2027-01-01T00:00:00Z';p.write_bytes(R.canonical_bytes(r))
        with self.assertRaisesRegex(R.ContractError,'FUTURE_RECEIPT'):self.store.get(URL)
    def test_immutable_conflict_preserves_old(self):
        p=self.root/'obj';C.exclusive_bytes(p,b'first')
        with self.assertRaisesRegex(R.ContractError,'CONFLICT'):C.exclusive_bytes(p,b'second')
        self.assertEqual(p.read_bytes(),b'first')
    def test_path_inside_git_is_rejected(self):
        gitroot=self.root/'repo';(gitroot/'.git').mkdir(parents=True)
        with self.assertRaisesRegex(R.ContractError,'WORKTREE'):C.CaptureStore(gitroot/'data',user_agent=UA,request_budget=1)
    def test_secret_not_written_to_receipt(self):
        self.store.user_agent='NotARealSecret contact@example.invalid';_,r=self.store.get(URL)
        self.assertNotIn('NotARealSecret',json.dumps(r));self.assertNotIn('user_agent',r)
    def test_symlink_object_rejected(self):
        _,r=self.store.get(URL);p=self.root/'store'/'objects'/r['raw_sha256'];raw=p.read_bytes();p.unlink();other=self.root/'other';other.write_bytes(raw);p.symlink_to(other)
        with self.assertRaisesRegex(R.ContractError,'SYMLINK'):self.store.get(URL)
    def test_global_lock_conflict_and_release(self):
        lock=self.root/'shared'/'lock'
        with C.writer_lock(lock):
            self.assertTrue(lock.exists())
            with self.assertRaisesRegex(C.CaptureBlocked,'LOCK_EXISTS'):
                with C.writer_lock(lock):pass
        self.assertFalse(lock.exists())


class CaptureFlowTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.out=self.root/'capture';self.clock=Clock();self.calls=[]
        self.responses={URL:R.canonical_bytes(sec_payload()),S.filing_url('111111','0000111111-24-000001','report.htm'):b'SYNTHETIC 8-K; not a real SEC filing.'}
    def tearDown(self):self.t.cleanup()
    def run_capture(self,p=None,resume=False,fetcher=None):
        def fake(u,a):self.calls.append(u);return self.responses[u]
        return C.capture(p or plan(),self.out,user_agent=UA,lock_path=self.root/'lock',resume=resume,clock=lambda:NOW,
                         fetcher=fetcher or fake,monotonic=self.clock.mono,sleeper=self.clock.sleep)
    def test_capture_index_and_primary_preserves_review_queue(self):
        r=self.run_capture();self.assertEqual(r['captured_documents'],1);self.assertEqual(r['new_requests'],2);self.assertEqual(r['selector_weight'],0)
        m,f,_=S.load_export(Path(r['export_dir']),now=NOW,index_only=True);ix=S.index_export(m,f)
        self.assertEqual(len(ix['candidates']),1);self.assertIsNone(ix['candidates'][0]['available_at'])
    def test_resume_complete_does_not_fetch_again(self):
        self.run_capture();r=self.run_capture(resume=True);self.assertEqual(r['new_requests'],0);self.assertEqual(r['reused_verified_receipts'],2)
    def test_existing_without_resume_blocked(self):
        self.run_capture()
        with self.assertRaisesRegex(R.ContractError,'EXISTS_USE'):self.run_capture()
    def test_resume_plan_mutation_rejected(self):
        self.run_capture();p=plan();p['max_filings']=50
        with self.assertRaisesRegex(R.ContractError,'IMMUTABLE_CAPTURE_CONFLICT'):self.run_capture(p,resume=True)
    def test_resume_user_directory_not_adopted(self):
        self.out.mkdir();(self.out/'my-note.txt').write_text('KEEP')
        with self.assertRaisesRegex(R.ContractError,'RESUME_PLAN_MISSING'):self.run_capture(resume=True)
        self.assertEqual((self.out/'my-note.txt').read_text(),'KEEP')
    def test_additional_history_page_is_requested(self):
        p=sec_payload();h='https://data.sec.gov/submissions/CIK0000111111-submissions-001.json'
        p['filings']['files']=[{'name':h.split('/')[-1],'filingFrom':'2024-01-01','filingTo':'2024-12-31'}]
        self.responses[URL]=R.canonical_bytes(p);self.responses[h]=R.canonical_bytes(sec_payload()['filings']['recent'])
        r=self.run_capture();self.assertIn(h,self.calls);self.assertTrue(r['history_pages_complete']);self.assertEqual(r['indexed_filing_candidates'],1)
    def test_429_halts_collection_and_records_deferral(self):
        def blocked(u,a):self.calls.append(u);raise C.CaptureBlocked('HTTP_429','120')
        r=self.run_capture(fetcher=blocked);self.assertEqual(r['status'],'PARTIAL_BLOCKED');self.assertEqual(r['blockers'][0]['retry_after_seconds'],'120');self.assertEqual(len(self.calls),1)
    def test_missing_history_is_not_complete(self):
        p=sec_payload();h='https://data.sec.gov/submissions/CIK0000111111-submissions-001.json';p['filings']['files']=[{'name':h.split('/')[-1],'filingFrom':'2024-01-01','filingTo':'2024-12-31'}]
        self.responses[URL]=R.canonical_bytes(p)
        def fake(u,a):
            if u==h:raise C.CaptureBlocked('HTTP_403')
            return self.responses[u]
        r=self.run_capture(fetcher=fake);self.assertFalse(r['history_pages_complete']);self.assertIn(h,r['missing_history_urls']);self.assertEqual(r['captured_documents'],0)
    def test_resume_after_partial_reuses_index(self):
        count=[0]
        def fake(u,a):
            count[0]+=1
            if u!=URL:raise C.CaptureBlocked('NETWORK_UNAVAILABLE_OR_TIMEOUT')
            return self.responses[u]
        first=self.run_capture(fetcher=fake);self.assertEqual(first['status'],'PARTIAL_BLOCKED')
        second=self.run_capture(resume=True);self.assertEqual(second['new_requests'],1);self.assertEqual(second['reused_verified_receipts'],1)
    def test_form6k_captured_without_8k_translation(self):
        self.responses[URL]=R.canonical_bytes(sec_payload(form='6-K'))
        r=self.run_capture();m,f,_=S.load_export(Path(r['export_dir']),now=NOW,index_only=True)
        self.assertEqual(S.index_export(m,f)['candidates'][0]['descriptive_event_tags'],['FPI_DISCLOSURE_UNCLASSIFIED'])
    def test_document_budget_does_not_drop_candidates(self):
        p=sec_payload();c=p['filings']['recent']
        for k,v in c.items():v.append(v[0])
        c['accessionNumber'][1]='0000111111-24-000002';self.responses[URL]=R.canonical_bytes(p)
        pl=plan();pl['max_filings']=1;r=self.run_capture(pl);self.assertEqual(r['indexed_filing_candidates'],2);self.assertEqual(r['deferred_document_candidates'],1)
    def test_request_budget_partial_is_safe(self):
        p=plan();p['max_requests']=1;r=self.run_capture(p);self.assertEqual(r['status'],'PARTIAL_BLOCKED');self.assertEqual(r['captured_documents'],0)
    def test_more_than100_filings_blocked(self):
        p=plan();p['max_filings']=101
        with self.assertRaisesRegex(R.ContractError,'FILING_BUDGET'):self.run_capture(p)
        self.assertFalse(self.out.exists())
    def test_more_than10_ciks_blocked(self):
        p=plan();p['ciks']=list(range(1,12))
        with self.assertRaisesRegex(R.ContractError,'CIK_BUDGET'):self.run_capture(p)
    def test_more_than24month_window_blocked(self):
        p=plan();p['window_start']='2010-01-01'
        with self.assertRaisesRegex(R.ContractError,'WINDOW_BUDGET'):self.run_capture(p)
    def test_bad_selection_rule_not_allowed(self):
        p=plan();p['selection_rule']='BEST_RETURN_ONLY'
        with self.assertRaisesRegex(R.ContractError,'SELECTION_RULE'):self.run_capture(p)
    def test_future_capture_cutoff_blocked(self):
        p=plan();p['data_cutoff']='2027-01-01T00:00:00Z'
        with self.assertRaisesRegex(R.ContractError,'CUTOFF'):self.run_capture(p)


class HttpBoundaryTests(unittest.TestCase):
    def test_redirect_handler_does_not_follow(self):self.assertIsNone(C._NoRedirects().redirect_request(None,None,302,'',{},'https://evil.invalid'))
    def test_no_user_agent_stops_before_network(self):
        with patch.object(C,'build_opener') as mock,self.assertRaisesRegex(R.ContractError,'USER_AGENT'):C.fetch_sec(URL,'')
        mock.assert_not_called()
    def test_ua_header_injection_rejected(self):
        with self.assertRaisesRegex(R.ContractError,'USER_AGENT'):C.fetch_sec(URL,'good@example.invalid\r\nX-Bad:1')
    def test_403_not_retried(self):
        with patch.object(C,'build_opener') as mock:
            mock.return_value.open.side_effect=HTTPError(URL,403,'Forbidden',{},None)
            with self.assertRaisesRegex(C.CaptureBlocked,'HTTP_403'):C.fetch_sec(URL,UA)
            self.assertEqual(mock.return_value.open.call_count,1)
    def test_network_failure_sanitized(self):
        with patch.object(C,'build_opener') as mock:
            mock.return_value.open.side_effect=URLError('PRIVATE_DETAIL')
            with self.assertRaises(C.CaptureBlocked) as e:C.fetch_sec(URL,UA)
            self.assertNotIn('PRIVATE_DETAIL',str(e.exception))

if __name__=='__main__':unittest.main(verbosity=2)

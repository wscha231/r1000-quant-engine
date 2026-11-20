"""Offline continuation and source-scope regressions. No real news/price data."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from news_research_cloud_smoke import FakeDrive
from news_event_p0_source_capture_smoke import plan, NOW, URL, UA, Clock, sec_payload
from research.news_event_alpha_v1 import source_capture as C, source_checkpoint as K
from research.news_event_alpha_v1 import shared_reader as X, runtime as R, source_bridge as S
from tools import run_news_research_cloud as W


def corpus(n=3, missing=False):
    p = sec_payload()
    cols = p['filings']['recent']
    for key, val in cols.items():
        cols[key] = val * n
    replies = {}
    for i in range(n):
        acc = f'0000111111-24-{i+1:06d}'
        cols['accessionNumber'][i] = acc
        cols['primaryDocument'][i] = '' if missing and i == n-1 else 'report.htm'
        replies[S.filing_url('111111', acc, 'report.htm')] = f'SYNTHETIC ONLY document {i}'.encode()
    replies[URL] = R.canonical_bytes(p)
    return replies


def progressive(limit=2):
    p = plan()
    p.update(document_progression='REMAINING_UNCAPTURED', max_filings=limit)
    return p


class Transport(FakeDrive):
    """Local directory test double, including exact files-from selection."""
    def call(self, *args):
        if args[0] == 'lsf':
            self.ops.append(args)
            return ''.join(p.name + '/\n' for p in sorted(self.path(args[1]).iterdir()) if p.is_dir()).encode()
        if args[0] == 'copy' and '--files-from-raw' in args:
            self.ops.append(args)
            wanted = Path(args[args.index('--files-from-raw')+1]).read_text().splitlines()
            src, dst = self.path(args[1]), self.path(args[2])
            dst.mkdir(parents=True, exist_ok=True)
            for name in wanted:
                shutil.copyfile(src/name, dst/name)
            return b''
        return super().call(*args)


class CaptureProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.data = corpus(); self.calls = []
    def tearDown(self): self.temp.cleanup()
    def cap(self, p=None, resume=False, fetcher=None, source=None):
        def get(u, a):
            self.calls.append(u); return self.data[u]
        c = Clock()
        return C.capture(p or progressive(), self.root/'capture', user_agent=UA,
                         lock_path=self.root/'lock', resume=resume, clock=lambda: NOW,
                         fetcher=fetcher or get, monotonic=c.mono, sleeper=c.sleep,
                         execution_source_commit=source)
    def test_next_run_moves_past_first_document_limit(self):
        first = self.cap(); second = self.cap(resume=True)
        self.assertEqual(first['coverage_counts'], {'indexed':3,'captured':2,'pending_download':1,'missing_primary_path':0})
        self.assertEqual(second['coverage_counts']['captured'],3)
        self.assertEqual(second['new_requests'],1)
        self.assertEqual(len(self.calls),4)
    def test_completed_run_makes_zero_new_requests(self):
        self.cap(); self.cap(resume=True); r = self.cap(resume=True)
        self.assertEqual(r['new_requests'],0)
        self.assertTrue(r['source_complete_for_declared_selection'])
        self.assertEqual(r['new_documents_captured'],0)
    def test_original_ingestion_time_is_preserved(self):
        self.cap(); before = {p.name:p.read_bytes() for p in (self.root/'capture/receipts').iterdir()}
        self.cap(resume=True)
        self.assertTrue(all((self.root/'capture/receipts'/n).read_bytes()==b for n,b in before.items()))
    def test_missing_primary_is_not_complete(self):
        self.data = corpus(missing=True); r=self.cap()
        self.assertEqual(r['coverage_counts']['missing_primary_path'],1)
        self.assertFalse(r['source_complete_for_declared_selection'])
    def test_request_limit_keeps_pending_denominator(self):
        p=progressive();p['max_requests']=2
        r=self.cap(p);self.assertEqual(r['coverage_counts']['pending_download'],2)
        self.assertEqual(r['status'],'PARTIAL_BLOCKED')
    def test_metadata_completeness_not_changed_by_primary_failure(self):
        def get(u,a):
            if u != URL: raise C.CaptureBlocked('HTTP_429')
            return self.data[u]
        r=self.cap(fetcher=get)
        self.assertTrue(r['history_pages_complete']);self.assertFalse(r['source_complete_for_declared_selection'])
    def test_elapsed_time_budget_stops_before_next_request(self):
        clock=Clock(); calls=[]
        store=C.CaptureStore(self.root/'timed',user_agent=UA,request_budget=150,
            clock=lambda:NOW,fetcher=lambda u,a:calls.append(u),monotonic=clock.mono,sleeper=clock.sleep)
        clock.t=601
        with self.assertRaisesRegex(C.CaptureBlocked,'TIME_BUDGET'):store.get(URL)
        self.assertFalse(calls)
    def test_api_failure_is_not_silently_retried(self):
        calls=[]
        def get(u,a): calls.append(u);raise C.CaptureBlocked('HTTP_403')
        r=self.cap(fetcher=get);self.assertEqual(len(calls),1)
        self.assertFalse(r['history_pages_complete'])
    def test_plan_cannot_hide_secrets(self):
        p=progressive();p['api_key']='NOT_A_REAL_KEY'
        with self.assertRaisesRegex(R.ContractError,'UNKNOWN_PLAN_FIELD'):self.cap(p)
        self.assertFalse(self.calls)
    def test_invalid_progress_mode_rejected(self):
        p=progressive();p['document_progression']='WINNERS_FIRST'
        with self.assertRaisesRegex(R.ContractError,'PROGRESSION'):self.cap(p)
    def test_unrelated_bot_commit_does_not_rewrite_frozen_plan(self):
        self.cap();original=(self.root/'capture/CAPTURE_PLAN.json').read_bytes()
        r=self.cap(resume=True,source='b'*40)
        self.assertEqual((self.root/'capture/CAPTURE_PLAN.json').read_bytes(),original)
        m=json.loads((Path(r['export_dir'])/'export_manifest.json').read_bytes())
        self.assertEqual(m['source_commit'],'b'*40)


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        clock=Clock();data=corpus()
        C.capture(progressive(),self.root/'capture',user_agent=UA,lock_path=self.root/'lock',
                  clock=lambda:NOW,fetcher=lambda u,a:data[u],monotonic=clock.mono,sleeper=clock.sleep)
        self.snap=self.root/'snapshot';self.code='a'*64
        self.cp=K.freeze_cache(self.root/'capture',self.snap,as_of=NOW,code_hash=self.code)
    def tearDown(self):self.temp.cleanup()
    def restore(self, **kw):
        args=dict(expected_hash=self.cp['checkpoint_sha256'],code_hash=self.code,as_of=NOW)
        args.update(kw);return K.restore_cache(self.snap,self.root/'restored',**args)
    def remanifest(self, fn):
        p=self.snap/'CHECKPOINT.json';m=json.loads(p.read_bytes());fn(m)
        p.write_bytes(R.canonical_bytes(m));self.cp['checkpoint_sha256']=K.sha256(p.read_bytes())
    def test_checkpoint_restores_frozen_plan_and_all_receipts(self):
        p=self.restore();self.assertEqual(p,progressive())
        self.assertEqual(len(list((self.root/'restored/receipts').iterdir())),3)
    def test_cache_restored_after72h_not_claimed_as_current_news(self):
        self.assertEqual(self.restore(as_of='2026-10-01T00:00:00Z'),progressive())
    def test_no_export_logs_or_programs_are_snapshotted(self):
        paths={e['path'] for e in self.cp['manifest']['files']}
        self.assertTrue(all(K.cache_path(p) for p in paths))
        self.assertFalse(any('exports' in p or p.endswith('.py') for p in paths))
    def test_source_change_requires_explicit_migration(self):
        with self.assertRaisesRegex(R.ContractError,'CODE_CHANGED'):self.restore(code_hash='b'*64)
        self.assertFalse((self.root/'restored').exists())
    def test_wrong_pin(self):
        with self.assertRaisesRegex(R.ContractError,'MANIFEST_HASH'):self.restore(expected_hash='0'*64)
    def test_pin_required(self):
        with self.assertRaises(R.ContractError):self.restore(expected_hash='')
    def test_missing_blob_is_not_replaced_by_network(self):
        next((self.snap/'objects').iterdir()).unlink()
        with self.assertRaises(R.ContractError):self.restore()
        self.assertFalse((self.root/'restored').exists())
    def test_corrupt_blob_fails_before_target_creation(self):
        next((self.snap/'objects').iterdir()).write_bytes(b'bad')
        with self.assertRaises(R.ContractError):self.restore()
        self.assertFalse((self.root/'restored').exists())
    def test_unlisted_blob_rejected(self):
        (self.snap/'objects'/('f'*64)).write_bytes(b'bad')
        with self.assertRaisesRegex(R.ContractError,'UNDECLARED'):self.restore()
    def test_symlink_rejected(self):
        (self.snap/'escape').symlink_to(self.root)
        with self.assertRaisesRegex(R.ContractError,'REPARSE'):self.restore()
    def test_traversal_in_manifest_rejected(self):
        self.remanifest(lambda m:m['files'][0].update(path='../evil'))
        with self.assertRaisesRegex(R.ContractError,'PATH'):self.restore()
    def test_duplicate_file_reference_rejected(self):
        self.remanifest(lambda m:m['files'].append(m['files'][0]))
        with self.assertRaisesRegex(R.ContractError,'PATH'):self.restore()
    def test_string_boolean_rejected(self):
        self.remanifest(lambda m:m.update(selector_eligible='false'))
        with self.assertRaisesRegex(R.ContractError,'AUTHORITY'):self.restore()
    def test_future_checkpoint_rejected(self):
        with self.assertRaisesRegex(R.ContractError,'FUTURE'):self.restore(as_of='2026-09-01T00:00:00Z')
    def test_existing_target_preserved(self):
        p=self.root/'restored';p.mkdir();(p/'user.txt').write_text('KEEP')
        with self.assertRaises(R.ContractError):self.restore()
        self.assertEqual((p/'user.txt').read_text(),'KEEP')
    def test_orphan_object_never_frozen(self):
        p=self.root/'capture/objects'/('f'*64);p.write_bytes(b'orphan')
        with self.assertRaisesRegex(R.ContractError,'ORPHAN'):
            K.freeze_cache(self.root/'capture',self.root/'other',as_of=NOW,code_hash=self.code)
    def test_receipt_repointed_to_unrelated_cik_rejected(self):
        path=next((self.root/'capture/receipts').iterdir())
        r=json.loads(path.read_bytes());r['source_url']='https://data.sec.gov/submissions/CIK0000999999.json'
        path.write_bytes(R.canonical_bytes(r))
        with self.assertRaisesRegex(R.ContractError,'SOURCE_SCOPE'):
            K.freeze_cache(self.root/'capture',self.root/'other',as_of=NOW,code_hash=self.code)
    def test_future_receipt_rejected(self):
        path=next((self.root/'capture/receipts').iterdir());r=json.loads(path.read_bytes())
        r['ingested_at']='2030-01-01T00:00:00Z';path.write_bytes(R.canonical_bytes(r))
        with self.assertRaisesRegex(R.ContractError,'FUTURE'):
            K.freeze_cache(self.root/'capture',self.root/'other',as_of=NOW,code_hash=self.code)
    def test_missing_plan_blocked(self):
        (self.root/'capture/CAPTURE_PLAN.json').unlink()
        with self.assertRaises(R.ContractError):
            K.freeze_cache(self.root/'capture',self.root/'other',as_of=NOW,code_hash=self.code)
    def test_source_schema_not_model_receipt(self):
        self.assertFalse(self.cp['manifest']['selector_eligible'])
        self.assertFalse(self.cp['manifest']['model_training_eligible'])
    def test_no_secret_in_snapshot(self):
        for p in (self.snap/'objects').iterdir():self.assertNotIn(UA.encode(),p.read_bytes())
    def test_plan_only_checkpoint_valid_after_no_response(self):
        root=self.root/'empty';C.exclusive_bytes(root/'CAPTURE_PLAN.json',R.canonical_bytes(progressive()))
        cp=K.freeze_cache(root,self.root/'empty-snap',as_of=NOW,code_hash=self.code)
        self.assertEqual(len(cp['manifest']['files']),1)


class CloudResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.drive=Transport(self.root/'drive');self.data=corpus();self.calls=[]
    def tearDown(self):self.temp.cleanup()
    def run_cloud(self,key,parent=None,pin=None,fetcher=None,source=None):
        work=self.root/('work-'+key);work.mkdir()
        def get(u,a):self.calls.append(u);return self.data[u]
        real=C.capture
        def cap(p,o,**kwargs):
            clock=Clock();return real(p,o,clock=lambda:NOW,fetcher=fetcher or get,
                                      monotonic=clock.mono,sleeper=clock.sleep,**kwargs)
        with patch.object(W,'now',return_value=NOW),patch.object(W,'capture',side_effect=cap):
            return W.run_capture_to_drive(self.drive,None if parent else progressive(),work,run_key=key,
                    user_agent=UA,resume_from=parent,resume_pin=pin,source_commit=source)
    def test_two_cloud_runs_finish_three_docs_without_refetch(self):
        a=self.run_cloud('100-1')
        self.assertEqual(a['status'],'PARTIAL_SOURCE_CAPTURE')
        self.assertTrue(a['resume_checkpoint_verified'])
        b=self.run_cloud('101-1','100-1',a['checkpoint_sha256'])
        self.assertEqual(b['status'],'SOURCE_CAPTURE_REVIEW_REQUIRED')
        self.assertEqual(b['coverage_counts']['captured'],3)
        self.assertEqual(len(self.calls),4)
        self.assertEqual(len(set(self.calls)),4)
        v=X.read_capture_attempt(self.drive.root/'source_captures/101-1',as_of=NOW)
        self.assertEqual(v['captured_primary_count'],3)
        self.assertEqual(v['official_score_contribution'],0)
    def test_three_runs_do_not_reset_progress(self):
        a=self.run_cloud('100-1');b=self.run_cloud('101-1','100-1',a['checkpoint_sha256'])
        c=self.run_cloud('102-1','101-1',b['checkpoint_sha256'])
        self.assertEqual(c['new_requests'],0);self.assertEqual(c['new_documents_captured'],0)
    def test_reference_pool_has_only_two_new_objects_for_one_new_doc(self):
        a=self.run_cloud('100-1');pool=self.drive.root/'source_captures/_objects';before={p.name for p in pool.iterdir()}
        self.run_cloud('101-1','100-1',a['checkpoint_sha256'])
        after={p.name for p in pool.iterdir()};self.assertEqual(len(after-before),2)
    def test_explicit_parent_hash_is_required(self):
        with self.assertRaisesRegex(R.ContractError,'PARENT_AND_HASH'):
            self.run_cloud('101-1','100-1',None)
        self.assertFalse(self.calls)
    def test_wrong_parent_hash_not_silently_latest(self):
        self.run_cloud('100-1');self.calls.clear()
        with self.assertRaisesRegex(R.ContractError,'NOT_VERIFIED'):self.run_cloud('101-1','100-1','f'*64)
        self.assertFalse(self.calls)
    def test_resuming_parent_twice_cannot_fork(self):
        a=self.run_cloud('100-1');self.run_cloud('101-1','100-1',a['checkpoint_sha256']);self.calls.clear()
        with self.assertRaisesRegex(R.ContractError,'ALREADY_CONTINUED'):self.run_cloud('102-1','100-1',a['checkpoint_sha256'])
        self.assertFalse(self.calls)
    def test_blocked_source_with_checkpoint_can_resume_but_not_feed_consumer(self):
        def bad(u,a):raise C.CaptureBlocked('HTTP_429')
        a=self.run_cloud('100-1',fetcher=bad)
        self.assertEqual(a['status'],'BLOCKED');self.assertTrue(a['resume_checkpoint_verified'])
        with self.assertRaises(R.ContractError):X.read_capture_attempt(self.drive.root/'source_captures/100-1',as_of=NOW)
        b=self.run_cloud('101-1','100-1',a['checkpoint_sha256'])
        self.assertEqual(b['coverage_counts']['captured'],2)
    def test_failed_checkpoint_upload_does_not_authorize_resume(self):
        self.drive.fail_check=True;a=self.run_cloud('100-1')
        self.assertEqual(a['status'],'BLOCKED');self.assertFalse(a['resume_checkpoint_verified'])
        self.assertIsNone(a['checkpoint_sha256'])
    def test_missing_terminal_does_not_guess_a_checkpoint(self):
        a=self.run_cloud('100-1');(self.drive.root/'source_captures/100-1/TERMINAL.json').unlink();self.calls.clear()
        with self.assertRaises((OSError,R.ContractError)):self.run_cloud('101-1','100-1',a['checkpoint_sha256'])
        self.assertFalse(self.calls)
    def test_tampered_parent_start_is_rejected(self):
        a=self.run_cloud('100-1');p=self.drive.root/'source_captures/100-1/STARTED.json';p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaisesRegex(R.ContractError,'ATTEMPT_LINK'):self.run_cloud('101-1','100-1',a['checkpoint_sha256'])
    def test_tampered_pool_blocks_before_sec(self):
        a=self.run_cloud('100-1');next((self.drive.root/'source_captures/_objects').iterdir()).write_bytes(b'bad');self.calls.clear()
        with self.assertRaises(R.ContractError):self.run_cloud('101-1','100-1',a['checkpoint_sha256'])
        self.assertFalse(self.calls)
    def test_bot_commit_change_keeps_data_provenance(self):
        a=self.run_cloud('100-1');b=self.run_cloud('101-1','100-1',a['checkpoint_sha256'],source='b'*40)
        self.assertEqual(b['source_commit'],'b'*40)
        v=X.read_capture_attempt(self.drive.root/'source_captures/101-1',as_of=NOW)
        self.assertEqual(v['source_commit'],'b'*40)
    def test_retry_after_survives_cloud_restart(self):
        def bad(u,a):raise C.CaptureBlocked('HTTP_429','120')
        a=self.run_cloud('100-1',fetcher=bad)
        self.assertIsNotNone(a.get('retry_not_before'));self.calls.clear()
        with self.assertRaisesRegex(R.ContractError,'RETRY_AFTER'):self.run_cloud('101-1','100-1',a['checkpoint_sha256'])
        self.assertFalse(self.calls)
    def test_parent_source_identity_mismatch_rejected(self):
        a=self.run_cloud('100-1');p=self.drive.root/'source_captures/100-1/TERMINAL.json'
        m=json.loads(p.read_bytes());m['source_commit']='f'*40;p.write_bytes(R.canonical_bytes(m))
        with self.assertRaisesRegex(R.ContractError,'SOURCE_AUTHORITY'):self.run_cloud('101-1','100-1',a['checkpoint_sha256'])
    def test_no_credentials_in_remote_pool_or_logs(self):
        self.run_cloud('100-1')
        for p in self.drive.root.rglob('*'):
            if p.is_file():self.assertNotIn(UA.encode(),p.read_bytes())
    def test_manual_only_workflow_for_continuation(self):
        text=(ROOT/'.github/workflows/news_research.yml').read_text()
        self.assertIn('resume_checkpoint:',text);self.assertIn('resume_from:',text)
        self.assertNotIn('schedule:',text);self.assertNotIn('pull_request_target',text)
        self.assertIn('tests/news_research_resume_smoke.py',text)
    def test_local_checkpoint_rerun_does_not_execute_programs(self):
        self.run_cloud('100-1')
        pool=self.drive.root/'source_captures/_objects'
        self.assertTrue(all(len(p.name)==64 for p in pool.iterdir()))
        self.assertFalse(any(p.suffix=='.py' for p in pool.iterdir()))

if __name__ == '__main__': unittest.main(verbosity=2)

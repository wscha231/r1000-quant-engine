"""Source-sharing release boundary regressions; synthetic bytes, no network.

Negative fixtures recompute ALL declared hashes. They test semantic/time links,
not an attack on SHA256. No source evidence, alpha result or independent approval.
"""
from __future__ import annotations
import copy
from datetime import timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from news_event_p0_source_capture_smoke import NOW, UA, URL, plan, Clock, sec_payload
from research.news_event_alpha_v1 import runtime as R, source_capture as C
from research.news_event_alpha_v1 import source_bridge as S, shared_reader as X


def make_capture(root):
    data = {URL: R.canonical_bytes(sec_payload()),
            S.filing_url('111111', '0000111111-24-000001', 'report.htm'): b'SYNTHETIC ONLY'}
    clock = Clock()
    return C.capture(plan(), root, user_agent=UA, lock_path=root.parent/'capture.lock',
                     clock=lambda: NOW, fetcher=lambda u,a:data[u],
                     monotonic=clock.mono, sleeper=clock.sleep)


class ReleaseBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.cap = self.root/'capture'; self.report = make_capture(self.cap)
        self.bundle = self.root/'attempt/bundle'
        self.built = X.build_shared_capture(self.cap, self.report['attempt_id'], self.bundle,
                                           as_of=NOW, synthetic=True)
        self.pin = self.built['manifest_sha256']
    def tearDown(self): self.temp.cleanup()
    def read(self, **kw):
        args = dict(expected_manifest_sha256=self.pin, as_of=NOW, allow_synthetic=True)
        args.update(kw)
        return X.read_shared_capture(self.bundle, **args)
    def repin(self):
        p=self.bundle/'manifest.json';m=json.loads(p.read_bytes())
        for e in m['files']:
            b=(self.bundle/e['path']).read_bytes();e.update(bytes=len(b),sha256=X.sha256(b))
        p.write_bytes(R.canonical_bytes(m));self.pin=X.sha256(p.read_bytes())
    def report_change(self, fn):
        p=self.bundle/X.REPORT_NAME;r=json.loads(p.read_bytes());fn(r)
        p.write_bytes(R.canonical_bytes(r));self.repin()
    def export_change(self, fn):
        p=self.bundle/'source_export/export_manifest.json';m=json.loads(p.read_bytes());fn(m)
        p.write_bytes(R.canonical_bytes(m))
        self.report_change(lambda r:r.update(export_manifest_sha256=X.sha256(p.read_bytes())))
    def outer_change(self, fn):
        p=self.bundle/'manifest.json';m=json.loads(p.read_bytes());fn(m)
        p.write_bytes(R.canonical_bytes(m));self.pin=X.sha256(p.read_bytes())
    def attempt(self):
        parent=self.bundle.parent
        start={'schema':'news-capture-attempt-v1','run_key':'123-1','source_commit':'a'*40,
               'started_at':(R.utc(NOW)-timedelta(minutes=1)).isoformat(),'selector_eligible':False}
        raw=R.canonical_bytes(start);(parent/'STARTED.json').write_bytes(raw)
        end={'schema':'news-capture-terminal-v1','run_key':'123-1','source_commit':'a'*40,
             'started_sha256':X.sha256(raw),'finished_at':NOW,'status':'SOURCE_CAPTURE_REVIEW_REQUIRED',
             'consumer_readback_verified':True,'manifest_sha256':self.pin,'captured_primary_count':1,
             'selector_eligible':False,'model_training_eligible':False}
        (parent/'TERMINAL.json').write_bytes(R.canonical_bytes(end))
        return parent
    def attempt_read(self):
        return X.read_capture_attempt(self.bundle.parent,as_of=NOW,allow_synthetic=True)
    def terminal_change(self, fn):
        p=self.bundle.parent/'TERMINAL.json';v=json.loads(p.read_bytes());fn(v);p.write_bytes(R.canonical_bytes(v))
    def complete_coverage(self):
        return {'indexed':1,'captured':1,'pending_download':0,'missing_primary_path':0}
    def add_raw(self, *, duplicate=False, wrong_cik=False):
        def edit(m):
            orig=next(e for e in m['files'] if e['role']=='raw_object')
            if wrong_cik:
                orig['cik']='0000999999';return
            e=dict(orig);e['path']='raw/extra.bin'
            if not duplicate:e['source_url']=S.filing_url('111111','0000111111-24-000002','other.htm')
            b=b'EXTRA_SYNTHETIC_BYTES';(self.bundle/'source_export'/e['path']).write_bytes(b)
            e.update(sha256=X.sha256(b),bytes=len(b));m['files'].append(e)
            outer=json.loads((self.bundle/'manifest.json').read_bytes())
            outer['files'].append({'path':'source_export/'+e['path'],'sha256':X.sha256(b),'bytes':len(b)})
            (self.bundle/'manifest.json').write_bytes(R.canonical_bytes(outer))
        self.export_change(edit)

    def test_good_frozen_capture_stays_research_only(self):
        r=self.read();self.assertEqual(r['captured_primary_count'],1)
        self.assertFalse(r['selector_eligible']);self.assertFalse(r['model_training_eligible'])
        self.assertIsNone(r['expected_returns'])
    def test_good_attempt_is_accepted_as_reference_only(self):
        self.attempt();self.assertEqual(self.attempt_read()['run_key'],'123-1')
    def test_consistent_coverage_is_recomputed(self):
        self.report_change(lambda r:r.update(coverage_counts=self.complete_coverage(),pending_document_ids=[],source_complete_for_declared_selection=True))
        self.assertEqual(self.read()['coverage_counts'],self.complete_coverage())
    def test_legacy_report_coverage_computed_without_claiming_new_collection(self):
        self.report_change(lambda r:[r.pop(k,None) for k in ('coverage_counts','pending_document_ids','source_complete_for_declared_selection')])
        self.assertEqual(self.read()['coverage_counts'],self.complete_coverage())
    def test_wrong_coverage_count_rejected(self):
        counts=self.complete_coverage();counts['captured']=999
        self.report_change(lambda r:r.update(coverage_counts=counts))
        with self.assertRaises(R.ContractError):self.read()
    def test_incomplete_coverage_fields_rejected(self):
        self.report_change(lambda r:r.update(coverage_counts={'captured':1}))
        with self.assertRaises(R.ContractError):self.read()
    def test_boolean_coverage_count_rejected(self):
        counts=self.complete_coverage();counts['captured']=True
        self.report_change(lambda r:r.update(coverage_counts=counts))
        with self.assertRaises(R.ContractError):self.read()
    def test_boolean_report_count_rejected(self):
        self.report_change(lambda r:r.update(captured_documents=True))
        with self.assertRaises(R.ContractError):self.read()
    def test_fractional_report_count_rejected(self):
        self.report_change(lambda r:r.update(indexed_filing_candidates=1.0))
        with self.assertRaises(R.ContractError):self.read()
    def test_wrong_pending_ids_rejected(self):
        self.report_change(lambda r:r.update(pending_document_ids=['not-pending']))
        with self.assertRaises(R.ContractError):self.read()
    def test_wrong_completion_flag_rejected(self):
        self.report_change(lambda r:r.update(source_complete_for_declared_selection=False))
        with self.assertRaises(R.ContractError):self.read()
    def test_string_history_complete_rejected(self):
        self.report_change(lambda r:r.update(history_pages_complete='true'))
        with self.assertRaises(R.ContractError):self.read()
    def test_null_blocker_list_rejected(self):
        self.report_change(lambda r:r.update(blockers=None))
        with self.assertRaises(R.ContractError):self.read()
    def test_synthetic_inner_cannot_be_labeled_real(self):
        self.export_change(lambda m:m.update(origin='SYNTHETIC_TEST'))
        self.outer_change(lambda m:m.update(synthetic=False))
        with self.assertRaises(R.ContractError):self.read(allow_synthetic=False)
    def test_synthetic_inner_allowed_only_explicitly(self):
        self.export_change(lambda m:m.update(origin='SYNTHETIC_TEST'))
        self.assertTrue(self.read()['synthetic'])
    def test_original_captured_origin_not_forward_observation(self):
        self.export_change(lambda m:m.update(origin='FORWARD_OBSERVED'))
        with self.assertRaises(R.ContractError):self.read()
    def test_raw_ingestion_after_publication_rejected(self):
        def change(m):
            next(e for e in m['files'] if e['role']=='raw_object')['ingested_at']='2026-09-20T00:00:00Z'
        self.export_change(change)
        with self.assertRaises(R.ContractError):self.read()
    def test_raw_missing_ingestion_rejected(self):
        def change(m):next(e for e in m['files'] if e['role']=='raw_object').pop('ingested_at')
        self.export_change(change)
        with self.assertRaises(R.ContractError):self.read()
    def test_primary_url_outside_index_rejected(self):
        self.add_raw()
        with self.assertRaises(R.ContractError):self.read()
    def test_duplicate_primary_url_cannot_hide_different_bytes(self):
        self.add_raw(duplicate=True)
        with self.assertRaises(R.ContractError):self.read()
    def test_primary_cik_mismatch_rejected(self):
        self.add_raw(wrong_cik=True)
        with self.assertRaises(R.ContractError):self.read()
    def test_publication_after_terminal_rejected(self):
        self.attempt();self.terminal_change(lambda r:r.update(finished_at=(R.utc(NOW)-timedelta(seconds=30)).isoformat()))
        with self.assertRaises(R.ContractError):self.attempt_read()
    def test_publication_before_start_rejected(self):
        self.attempt();p=self.bundle.parent/'STARTED.json';r=json.loads(p.read_bytes())
        r['started_at']=(R.utc(NOW)+timedelta(seconds=1)).isoformat();raw=R.canonical_bytes(r);p.write_bytes(raw)
        self.terminal_change(lambda r:r.update(started_sha256=X.sha256(raw),finished_at=(R.utc(NOW)+timedelta(seconds=2)).isoformat()))
        with self.assertRaises(R.ContractError):X.read_capture_attempt(self.bundle.parent,as_of='2026-09-19T12:01:00Z',allow_synthetic=True)
    def test_terminal_boolean_count_rejected(self):
        self.attempt();self.terminal_change(lambda r:r.update(captured_primary_count=True))
        with self.assertRaises(R.ContractError):self.attempt_read()
    def test_terminal_coverage_mismatch_rejected(self):
        self.attempt();self.terminal_change(lambda r:r.update(coverage_counts={'indexed':100}))
        with self.assertRaises(R.ContractError):self.attempt_read()
    def test_hashed_snapshot_cannot_change_during_semantic_read(self):
        original=X._capture_view
        expected=['MATERIAL_AGREEMENT_UNCLASSIFIED','FINANCIAL_OBLIGATION']
        def swapped(*args,**kwargs):
            def edit(m):
                e=next(f for f in m['files'] if f['role']=='sec_submissions')
                p=self.bundle/'source_export'/e['path'];v=json.loads(p.read_bytes())
                v['filings']['recent']['items']=['1.02'];raw=R.canonical_bytes(v);p.write_bytes(raw)
                e.update(sha256=X.sha256(raw),bytes=len(raw))
            self.export_change(edit)
            return original(*args,**kwargs)
        # Pin evaluated before the concurrent producer-like mutation occurs.
        with patch.object(X,'_capture_view',side_effect=swapped):
            r=self.read()
        self.assertEqual(r['filing_preview'][0]['descriptive_event_tags'],expected)
    def test_bad_outer_hash_still_blocked(self):
        with self.assertRaises(R.ContractError):self.read(expected_manifest_sha256='0'*64)
    def test_synthetic_not_allowed_by_default(self):
        with self.assertRaises(R.ContractError):self.read(allow_synthetic=False)
    def test_top_limit_stays_five(self):
        with self.assertRaises(R.ContractError):self.read(top_n=6)
    def test_reader_does_not_write(self):
        before={p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.read()
        self.assertEqual(before,{p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

if __name__=='__main__':unittest.main(verbosity=2)

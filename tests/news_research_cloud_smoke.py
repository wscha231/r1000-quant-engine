"""Offline source publisher/consumer contracts; no real network or investment results."""
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
from news_event_p0_source_capture_smoke import plan, NOW, UA, URL, Clock, sec_payload
from research.news_event_alpha_v1 import runtime as R
from research.news_event_alpha_v1 import source_capture as C
from research.news_event_alpha_v1 import source_bridge as S
from research.news_event_alpha_v1 import shared_reader as X
from tools import run_news_research_cloud as W


def fixture(root):
    responses = {URL: R.canonical_bytes(sec_payload()),
                 S.filing_url('111111','0000111111-24-000001','report.htm'): b'SYNTHETIC_NOT_MARKET_DATA'}
    clock = Clock()
    return C.capture(plan(), root, user_agent=UA, lock_path=root.parent/'lock',
        clock=lambda: NOW, fetcher=lambda u,a: responses[u], monotonic=clock.mono, sleeper=clock.sleep)


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.root = Path(self.t.name)
        self.capture = self.root/'capture'; report = fixture(self.capture)
        self.bundle = self.root/'bundle'
        self.result = X.build_shared_capture(self.capture,report['attempt_id'],self.bundle,as_of=NOW,synthetic=True)
        self.pin = self.result['manifest_sha256']
    def tearDown(self): self.t.cleanup()
    def read(self, **kw):
        args = dict(expected_manifest_sha256=self.pin, as_of=NOW, allow_synthetic=True)
        args.update(kw); return X.read_shared_capture(self.bundle, **args)
    def change_manifest(self,fn):
        p=self.bundle/'manifest.json';m=json.loads(p.read_bytes());fn(m)
        p.write_bytes(R.canonical_bytes(m)); self.pin=X.sha256(p.read_bytes())
    def test_source_to_reader(self):
        v=self.read(); self.assertEqual(v['captured_primary_count'],1)
        self.assertFalse(v['selector_eligible']); self.assertFalse(v['model_training_eligible'])
        self.assertIsNone(v['expected_returns']); self.assertIsNone(v['rs'])
        self.assertEqual(v['status'],'SOURCE_CAPTURE_REVIEW_REQUIRED')
    def test_raw_is_not_investment_pick(self):
        row=self.read()['filing_preview'][0]
        self.assertEqual(row['descriptive_event_tags'],['MATERIAL_AGREEMENT_UNCLASSIFIED','FINANCIAL_OBLIGATION'])
        self.assertIsNone(row['source_public_at']);self.assertNotIn('score',row)
    def test_synthetic_blocked_by_default(self):
        with self.assertRaisesRegex(R.ContractError,'SYNTHETIC_BLOCKED'):self.read(allow_synthetic=False)
    def test_manifest_tampering(self):
        with self.assertRaisesRegex(R.ContractError,'MANIFEST_HASH'):self.read(expected_manifest_sha256='0'*64)
    def test_missing_pin(self):
        with self.assertRaisesRegex(R.ContractError,'MANIFEST_PIN'):self.read(expected_manifest_sha256='')
    def test_member_tampering(self):
        p=self.bundle/'capture_report.json';p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaisesRegex(R.ContractError,'FILE_HASH'):self.read()
    def test_extra_file_rejected(self):
        (self.bundle/'extra.txt').write_text('no')
        with self.assertRaisesRegex(R.ContractError,'UNDECLARED'):self.read()
    def test_missing_file_rejected(self):
        (self.bundle/'capture_report.json').unlink()
        with self.assertRaises(R.ContractError):self.read()
    def test_symlink_rejected(self):
        (self.bundle/'escape').symlink_to(self.root)
        with self.assertRaises(R.ContractError):self.read()
    def test_traversal_rejected(self):
        self.change_manifest(lambda m:m['files'][0].update(path='../outside'))
        with self.assertRaises(R.ContractError):self.read()
    def test_duplicate_path_rejected(self):
        self.change_manifest(lambda m:m['files'].append(m['files'][0]))
        with self.assertRaisesRegex(R.ContractError,'DUPLICATE_PATH'):self.read()
    def test_promotion_flag_rejected(self):
        self.change_manifest(lambda m:m.update(selector_eligible=True))
        with self.assertRaisesRegex(R.ContractError,'AUTHORITY'):self.read()
    def test_string_boolean_rejected(self):
        self.change_manifest(lambda m:m.update(synthetic='false'))
        with self.assertRaisesRegex(R.ContractError,'SYNTHETIC_TYPE'):self.read()
    def test_wrong_source_commit_rejected(self):
        self.change_manifest(lambda m:m.update(source_commit='b'*40))
        with self.assertRaisesRegex(R.ContractError,'PROVENANCE'):self.read()
    def test_future_cutoff_rejected(self):
        self.change_manifest(lambda m:m.update(data_cutoff='2027-01-01T00:00:00Z'))
        with self.assertRaisesRegex(R.ContractError,'CUTOFF'):self.read()
    def test_future_generation_rejected(self):
        with self.assertRaises(R.ContractError):self.read(as_of='2026-09-18T12:00:00Z')
    def test_stale_rejected(self):
        with self.assertRaisesRegex(R.ContractError,'STALE'):self.read(as_of='2026-09-24T12:00:00Z')
    def test_top5_hard_cap(self):
        with self.assertRaises(R.ContractError):self.read(top_n=6)
        with self.assertRaises(R.ContractError):self.read(top_n=True)
        self.assertEqual(self.read(top_n=0)['filing_preview'],[])
    def test_output_not_overwritten(self):
        with self.assertRaises(R.ContractError):X.build_shared_capture(self.capture,'a'*32,self.bundle,as_of=NOW)
    def test_missing_terminal_never_falls_back(self):
        with self.assertRaises(R.ContractError):X.read_capture_attempt(self.root,as_of=NOW)
    def test_failed_terminal_never_falls_back(self):
        (self.root/'STARTED.json').write_bytes(R.canonical_bytes({'schema':'news-capture-attempt-v1'}))
        (self.root/'TERMINAL.json').write_bytes(R.canonical_bytes({'schema':'news-capture-terminal-v1','status':'BLOCKED'}))
        with self.assertRaisesRegex(R.ContractError,'NOT_COMPLETED'):X.read_capture_attempt(self.root,as_of=NOW)


class FakeDrive:
    def __init__(self,root,fail_check=False):self.root=root;self.ops=[];self.fail_check=fail_check
    def parity(self):self.ops.append(('parity',))
    def path(self,p):return self.root/p.removeprefix('gdrive:') if p.startswith('gdrive:') else Path(p)
    def call(self,*args):
        self.ops.append(args);cmd=args[0]
        if cmd=='cat':return self.path(args[1]).read_bytes()
        a,b=self.path(args[1]),self.path(args[2])
        if cmd=='copyto':
            b.parent.mkdir(parents=True,exist_ok=True)
            if b.exists() and a.read_bytes()!=b.read_bytes():raise R.ContractError('IMMUTABLE')
            shutil.copyfile(a,b)
        elif cmd=='copy':shutil.copytree(a,b,dirs_exist_ok=True)
        elif cmd=='check':
            if self.fail_check:raise R.ContractError('CHECK_FAILED')
            for p in a.rglob('*'):
                if p.is_file() and p.read_bytes()!=(b/p.relative_to(a)).read_bytes():raise R.ContractError('CHECK_FAILED')
        else:raise AssertionError(cmd)
        return b''


class CloudTests(unittest.TestCase):
    def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name)
    def tearDown(self):self.t.cleanup()
    def run_cloud(self,fail=False):
        work=self.root/'work';work.mkdir()
        drive=FakeDrive(self.root/'drive',fail_check=fail)
        with patch.object(W,'now',return_value=NOW),patch.object(W,'capture',side_effect=lambda p,o,**kw:fixture(o)):
            out=W.run_capture_to_drive(drive,plan(),work,run_key='123-1',user_agent=UA)
        return out,drive
    def test_full_mocked_capture_upload_restore_consume(self):
        out,d=self.run_cloud();self.assertTrue(out['consumer_readback_verified']);self.assertEqual(out['captured_primary_count'],1)
        v=X.read_capture_attempt(d.root/'source_captures/123-1',as_of=NOW)
        self.assertEqual(v['run_key'],'123-1');self.assertEqual(v['selection_mode'],'PINNED_RUN_NOT_AUTO_LATEST')
        self.assertFalse(v['model_training_eligible'])
    def test_upload_check_failure_terminal_is_blocked(self):
        out,d=self.run_cloud(fail=True);self.assertEqual(out['status'],'BLOCKED')
        with self.assertRaisesRegex(R.ContractError,'NOT_COMPLETED'):X.read_capture_attempt(d.root/'source_captures/123-1',as_of=NOW)
    def test_terminal_hash_link_tampering(self):
        out,d=self.run_cloud();p=d.root/'source_captures/123-1/STARTED.json';p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaisesRegex(R.ContractError,'ATTEMPT_LINK'):X.read_capture_attempt(p.parent,as_of=NOW)
    def test_terminal_promotion_tampering(self):
        out,d=self.run_cloud();p=d.root/'source_captures/123-1/TERMINAL.json';m=json.loads(p.read_bytes());m['selector_eligible']=True;p.write_bytes(R.canonical_bytes(m))
        with self.assertRaisesRegex(R.ContractError,'AUTHORITY'):X.read_capture_attempt(p.parent,as_of=NOW)
    def test_no_credential_in_published_bytes(self):
        _,d=self.run_cloud()
        for p in d.root.rglob('*'):
            if p.is_file():self.assertNotIn(UA.encode(),p.read_bytes())
    def test_bad_run_key_stops_before_network(self):
        d=FakeDrive(self.root/'drive')
        with self.assertRaises(R.ContractError):W.run_capture_to_drive(d,plan(),self.root,run_key='../evil',user_agent=UA)
        self.assertFalse(d.ops)
    def test_plan_budget_and_cik_validation(self):
        p=W.make_plan('111111','2024-01-01','2025-12-31','a'*40,cutoff=NOW)
        self.assertEqual(p['max_filings'],100);self.assertEqual(p['ciks'],['0000111111'])
        for bad in ['','1,1','a',','.join(map(str,range(1,12)))]:
            with self.subTest(bad=bad),self.assertRaises(R.ContractError):W.make_plan(bad,'2024-01-01','2025-12-31','a'*40,cutoff=NOW)
    def test_bad_date_and_sha(self):
        with self.assertRaises(R.ContractError):W.make_plan('1','2020-01-01','2025-12-31','a'*40,cutoff=NOW)
        with self.assertRaises(R.ContractError):W.make_plan('1','2024-01-01','2025-12-31','abc',cutoff=NOW)
    def test_workflow_never_schedules_or_secrets_on_pr(self):
        path=ROOT/'.github/workflows/news_research.yml'
        text=path.read_text()
        self.assertNotIn('schedule:',text);self.assertNotIn('pull_request_target',text)
        self.assertIn('contents: read',text);self.assertIn("github.event_name == 'workflow_dispatch'",text)
        testjob=text.split('  capture:')[0]
        self.assertNotIn('secrets.',testjob)
        self.assertIn('cancel-in-progress: false',text)

if __name__=='__main__':unittest.main(verbosity=2)

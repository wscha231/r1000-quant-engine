"""Five Codex findings: synthetic regression fixtures, never investment evidence."""
from __future__ import annotations
import ast
import copy
from datetime import timedelta
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from news_event_p0_integrity_smoke import CAL, PRICES, EVENTS, checkpoints
from research.news_event_alpha_v1 import runtime as R, walk_forward as WF
from research.news_event_alpha_v1 import source_capture as C
from research.news_event_alpha_v1 import review_guards as G
from tools import run_news_event_alpha_v1 as CLI

NOW = '2026-09-20T12:00:00+00:00'


class TimingTests(unittest.TestCase):
    def current_prior(self):
        current = checkpoints()[1]
        prior = [dict(current, economic_event_id=f'past{i}', stable_security_id=f'S{i}',
                      issuer_id=f'I{i}', horizon=21, outcome_status='RESOLVED', excess_return=.03,
                      outcome_end_session=CAL[74]['session'],
                      label_available_at=CAL[74]['market_close_utc']) for i in range(15)]
        return current, prior
    def estimate(self, current, prior):
        return next(r for r in WF.build_walk_forward_impact_estimates([current], prior) if r['horizon']==21)
    def test_missing_origin_is_not_forward(self):
        event = dict(EVENTS[0]); event.pop('sample_origin')
        with self.assertRaises(R.ContractError): R.normalize_event(event)
    def test_cli_does_not_fill_missing_origin(self):
        event = dict(EVENTS[0]); event.pop('sample_origin')
        with self.assertRaises(R.ContractError): CLI.force_origin([event], 'FORWARD_SHADOW')
    def test_self_declared_forward_receipt_cannot_authorize_learning(self):
        event = dict(EVENTS[0], sample_origin='FORWARD_SHADOW', receipt_sha256='a'*64,
                     ingested_at=EVENTS[0]['available_at'], forward_verified=True)
        with self.assertRaisesRegex(R.ContractError, 'FORWARD_OBSERVATION_BLOCKED'):
            R.run_payload({'schema':R.SCHEMA_VERSION,'events':[event], 'prices':PRICES, 'market_sessions':CAL})
    def test_delayed_labels_do_not_train(self):
        c,p = self.current_prior()
        for r in p: r['label_available_at']=CAL[76]['market_close_utc']
        self.assertEqual(self.estimate(c,p)['analogue_status'],'UNDERPOWERED')
    def test_labels_at_decision_do_not_train(self):
        c,p = self.current_prior()
        for r in p: r['label_available_at']=c['decision_at']
        self.assertEqual(self.estimate(c,p)['analogue_status'],'UNDERPOWERED')
    def test_missing_label_clock_not_inferred(self):
        c,p = self.current_prior()
        for r in p: r.pop('label_available_at')
        self.assertEqual(self.estimate(c,p)['analogue_status'],'UNDERPOWERED')
    def test_mature_labels_still_train(self):
        c,p = self.current_prior(); r=self.estimate(c,p)
        self.assertEqual(r['training_n'],15); self.assertAlmostEqual(r['analogue_median_excess'],.03)
        self.assertLess(R.utc(r['training_latest_label_available_at']),R.utc(c['decision_at']))
    def test_unknown_price_availability_rejected(self):
        p=dict(PRICES[0]);p.pop('available_at')
        with self.assertRaises(R.ContractError):R.validate_price_rows([p])
    def test_naive_price_availability_rejected(self):
        p=dict(PRICES[0],available_at='2024-01-02T21:00:00')
        with self.assertRaises(R.ContractError):R.validate_price_rows([p])
    def test_available_before_close_rejected(self):
        p=dict(PRICES[0],available_at='2024-01-02T20:00:00Z')
        with self.assertRaises(R.ContractError):R.PriceBook([p],CAL)
    def test_endpoint_label_uses_latest_benchmark_publication(self):
        p=copy.deepcopy(PRICES)
        delayed=CAL[110]['market_close_utc']
        for r in p:
            if r['security_id']=='SPY' and r['session']==CAL[96]['session']:r['available_at']=delayed
        rows=R.attach_forward_outcomes(checkpoints(),p,CAL)
        r=next(r for r in rows if r['checkpoint']==5 and r['horizon']==21)
        self.assertEqual(R.utc(r['label_available_at']),R.utc(delayed))
    def test_asof_hides_outcome_before_label_arrival(self):
        p=copy.deepcopy(PRICES)
        for r in p:
            if r['security_id']=='AAA' and r['session']==CAL[96]['session']:
                r['available_at']=CAL[110]['market_close_utc']
        rows=R.attach_forward_outcomes(checkpoints(),p,CAL,as_of=CAL[100]['market_close_utc'])
        r=next(r for r in rows if r['security_id']=='AAA' and r['checkpoint']==5 and r['horizon']==21)
        self.assertEqual(r['outcome_status'],'PENDING_LABEL_AVAILABILITY');self.assertIsNone(r['excess_return'])
    def test_late_pre_event_price_not_used_as_feature(self):
        p=copy.deepcopy(PRICES)
        for r in p:
            if r['security_id']=='AAA' and r['session']==CAL[69]['session']:
                r['available_at']=CAL[95]['market_close_utc']
        c=R.build_checkpoint_rows(EVENTS,p,CAL)
        r=next(r for r in c if r['security_id']=='AAA' and r['checkpoint']==5)
        self.assertIsNone(r['pre_rs20']); self.assertIsNone(r['event_day_excess'])
    def test_valid_observation_return_is_unchanged(self):
        rows=R.attach_forward_outcomes(checkpoints(),PRICES,CAL)
        r=next(r for r in rows if r['security_id']=='AAA' and r['horizon']==21)
        self.assertAlmostEqual(r['absolute_return'],1.002**21-1)


class RetryTests(unittest.TestCase):
    def test_seconds(self):
        r=G.retry_directive('120',received_at=NOW)
        self.assertEqual(R.utc(r['retry_not_before']),R.utc(NOW)+timedelta(seconds=120))
    def test_http_date(self):
        r=G.retry_directive('Sun, 20 Sep 2026 12:02:00 GMT',received_at=NOW)
        self.assertEqual(R.utc(r['retry_not_before']),R.utc(NOW)+timedelta(seconds=120))
    def test_obsolete_http_date(self):
        r=G.retry_directive('Sunday, 20-Sep-26 12:02:00 GMT',received_at=NOW)
        self.assertFalse(r['retry_manual_review_required']);self.assertIsNotNone(r['retry_not_before'])
    def test_asctime_http_date(self):
        r=G.retry_directive('Sun Sep 20 12:02:00 2026',received_at=NOW)
        self.assertFalse(r['retry_manual_review_required']);self.assertIsNotNone(r['retry_not_before'])
    def test_invalid_nonempty_blocks(self):
        self.assertTrue(G.retry_directive('try tomorrow',received_at=NOW)['retry_manual_review_required'])
    def test_negative_delay_blocks(self):
        self.assertTrue(G.retry_directive('-1',received_at=NOW)['retry_manual_review_required'])
    def test_oversized_delay_blocks(self):
        self.assertTrue(G.retry_directive('9'*130,received_at=NOW)['retry_manual_review_required'])
    def test_header_injection_not_logged(self):
        r=G.retry_directive('120\r\nSECRET',received_at=NOW)
        self.assertTrue(r['retry_manual_review_required']);self.assertNotIn('SECRET',json.dumps(r))
    def test_missing_header_does_not_invent_wait(self):
        self.assertEqual(G.retry_directive(None,received_at=NOW),{'retry_not_before':None,'retry_manual_review_required':False})
    def test_past_http_date_is_not_future_delay(self):
        self.assertEqual(R.utc(G.retry_directive('Sat, 19 Sep 2026 12:00:00 GMT',received_at=NOW)['retry_not_before']),R.utc(NOW))
    def test_capture_preserves_http_date(self):
        exc=C.CaptureBlocked('HTTP_429','Sun, 20 Sep 2026 12:02:00 GMT')
        self.assertIsNotNone(C.retry_metadata(exc,NOW)['retry_not_before'])
    def test_unknown_header_disallows_resume(self):
        with self.assertRaisesRegex(R.ContractError,'MANUAL_REVIEW'):
            G.enforce_retry(G.retry_directive('invalid',received_at=NOW),as_of=NOW)
    def test_before_deadline_blocks_resume(self):
        with self.assertRaisesRegex(R.ContractError,'NOT_REACHED'):
            G.enforce_retry(G.retry_directive('120',received_at=NOW),as_of=NOW)
    def test_after_deadline_allows_retry_check_only(self):
        G.enforce_retry(G.retry_directive('120',received_at=NOW),as_of='2026-09-20T12:03:00Z')


class LifetimeTests(unittest.TestCase):
    def test_before_parent_rejected(self):
        with self.assertRaises(R.ContractError):G.checkpoint_lifetime({'started_at':NOW},{'generated_at':'2026-09-20T11:59:00Z'},{'finished_at':NOW})
    def test_after_parent_rejected(self):
        with self.assertRaises(R.ContractError):G.checkpoint_lifetime({'started_at':NOW},{'generated_at':'2026-09-20T12:01:00Z'},{'finished_at':NOW})
    def test_equal_boundaries_allowed(self):G.checkpoint_lifetime({'started_at':NOW},{'generated_at':NOW},{'finished_at':NOW})
    def test_cloud_wires_lifetime_before_restoration(self):
        s=(ROOT/'tools/run_news_research_cloud.py').read_text();ast.parse(s)
        self.assertLess(s.index('checkpoint_lifetime(start, manifest, terminal)'),s.index('return restore_cache('))
        self.assertIn('enforce_retry(terminal, as_of=now())',s)


class MemoryDrive:
    """Unlike a filesystem, can represent multiple objects with the same name."""
    def __init__(self):self.rows={};self.data={};self.calls=[];self.mutate=None
    def add(self,parent,name,oid,isdir=False,data=b'{}'):
        row={'ID':oid,'Name':name,'Path':name,'IsDir':isdir,'Size':-1 if isdir else len(data)}
        self.rows.setdefault(parent,[]).append(row);self.data[oid]=data
        return row
    def call(self,*args):
        self.calls.append(args)
        if args[0]=='lsjson':return R.canonical_bytes(self.rows.get(args[1].split('=')[1].rstrip(':'),[]))
        if args[:2]==('backend','copyid'):
            Path(args[4]).write_bytes(self.data[args[3]])
            if self.mutate:self.mutate()
            return b''
        raise AssertionError(args)


class DriveIdentityTests(unittest.TestCase):
    def setUp(self):
        self.d=MemoryDrive();self.d.add('root','source_captures','cap',True)
        self.d.add('cap','123-1','attempt',True);self.d.add('attempt','STARTED.json','file1',data=b'{"run_key":"123-1"}')
        self.refs=G.DriveReferences(self.d.call,'root')
    def test_file_is_read_by_id_not_name(self):
        raw=self.refs.read_path('gdrive:source_captures/123-1/STARTED.json')
        self.assertEqual(json.loads(raw)['run_key'],'123-1')
        self.assertTrue(any(a[:2]==('backend','copyid') and a[3]=='file1' for a in self.d.calls))
        self.assertFalse(any(a[0] in {'cat','lsf'} for a in self.d.calls))
    def test_duplicate_attempt_name_rejected(self):
        self.d.add('cap','123-1','otherattempt',True)
        with self.assertRaisesRegex(R.ContractError,'DUPLICATE'):self.refs.directory('source_captures/123-1')
    def test_duplicate_source_root_rejected(self):
        self.d.add('root','source_captures','othercap',True)
        with self.assertRaisesRegex(R.ContractError,'DUPLICATE'):self.refs.directory('source_captures')
    def test_duplicate_file_name_rejected(self):
        self.d.add('attempt','STARTED.json','file2')
        with self.assertRaisesRegex(R.ContractError,'DUPLICATE'):self.refs.read_child('attempt','STARTED.json')
    def test_missing_id_rejected(self):
        self.d.rows['cap'][0].pop('ID')
        with self.assertRaises(R.ContractError):self.refs.children('cap')
    def test_shortcut_rejected(self):
        self.d.rows['cap'][0]['OrigID']='target'
        with self.assertRaisesRegex(R.ContractError,'SHORTCUT'):self.refs.children('cap')
    def test_expected_file_id_is_enforced(self):
        with self.assertRaisesRegex(R.ContractError,'ID_MISMATCH'):self.refs.read_child('attempt','STARTED.json',expected_id='other')
    def test_id_change_after_download_rejected(self):
        self.d.mutate=lambda:self.d.rows['attempt'][0].update(ID='changed')
        with self.assertRaisesRegex(R.ContractError,'ID_CHANGED'):self.refs.read_child('attempt','STARTED.json')
    def test_duplicate_introduced_after_download_rejected(self):
        self.d.mutate=lambda:self.d.add('attempt','STARTED.json','late')
        with self.assertRaisesRegex(R.ContractError,'DUPLICATE'):self.refs.read_child('attempt','STARTED.json')
    def test_filename_case_collision_rejected(self):
        self.d.add('attempt','started.json','case')
        with self.assertRaises(R.ContractError):self.refs.children('attempt')
    def test_bad_remote_scope_rejected(self):
        with self.assertRaises(R.ContractError):self.refs.read_path('other:secret')
    def test_id_injection_rejected(self):
        with self.assertRaises(R.ContractError):G.DriveReferences(self.d.call,'id,root_folder_id=elsewhere')
    def test_no_remote_mutating_command(self):
        self.refs.read_child('attempt','STARTED.json')
        self.assertTrue(all(a[0]=='lsjson' or a[:2]==('backend','copyid') for a in self.d.calls))

if __name__=='__main__':unittest.main(verbosity=2)

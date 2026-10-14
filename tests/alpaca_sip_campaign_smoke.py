"""Offline counterexamples; synthetic fixtures are never vendor/PIT proof."""
import copy
from datetime import timedelta
from email import policy
from email.parser import BytesParser
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from tools import alpaca_sip_campaign as c
from tools import alpaca_sip_private_backfill_v1 as cap
from tools import twelve_private_capture as drive_module


def auth():
    return dict(schema='r1000-sip-campaign-authorization-v1',task_key=c.TASK, scope_approved=True, private_noncommercial=True,
                approval_reference="SYNTHETIC_OFFLINE_ONLY", start="2016-01-04", end="2026-10-14",
                seed_sha256=c.SEED_SHA, initial_checkpoint_sha256=c.INITIAL_SHA,
                transfer_definition=c.METRIC, limits=dict(c.LIMITS), workflow_run_floor=1,
                expected_master="1" * 40,
                code_pins={p: c.digest((c.ROOT / p).read_bytes()) for p in c.PINS},
                private_root_folder_id="fixture-root-123", private_data_folder_id="fixture-data-123",
                initial_checkpoint_file_id="fixture-initial-123",
                account_permission_reference="SYNTHETIC_NOT_ACCOUNT_APPROVAL", owner_permission_id="fixture-owner",
                credential_binding=c.digest(b"fixture-key\0fixture-secret"))


def identity():
    return dict(task_key=c.TASK, auth_sha256="a" * 64, source_sha="1" * 40,
                nonce=c.PREFIX + "a" * 24, run_id=1, run_attempt=1,
                parent_checkpoint_sha256=c.INITIAL_SHA, examined_before=16)


class Reply:
    status = 200
    def __init__(self, body, fail=False):
        self.body, self.fail = body, fail
        self.fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=lambda _: None)))
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read1(self, size):
        if self.fail and not self.body:
            raise OSError("PRIVATE_TRANSPORT_CANARY")
        out, self.body = self.body[:size], self.body[size:]
        return out


class Opener:
    def __init__(self, body=b"abc", failure=None):
        self.body, self.failure, self.calls = body, failure, 0
    def open(self, request, **kwargs):
        self.calls += 1
        if self.failure:
            raise self.failure
        return Reply(self.body)


def meter(directory, opener=None, allowance=None, clock=c.utc, seconds=60):
    return c.RuntimeMeter(allowance or dict(c.LIMITS), Path(directory) / "campaign_meter.json",
                          (clock() + timedelta(seconds=seconds)).isoformat(), identity(),
                          opener=opener or Opener(), clock=clock)


class BudgetTests(unittest.TestCase):
    def test_authorization_missing_drift_types_and_rights(self):
        original = auth()
        c.validate_authorization(original)
        for key, value in [("scope_approved", False), ("end", "2026-10-15"),
                           ("seed_sha256", "0" * 64), ("initial_checkpoint_sha256", "0" * 64),
                           ("account_permission_reference", ""), ("credential_binding", "bad"),
                           ("workflow_run_floor", True), ("transfer_definition", "wire-byte-assumption")]:
            changed = copy.deepcopy(original); changed[key] = value
            with self.subTest(key=key), self.assertRaises(c.Refused):
                c.validate_authorization(changed)
        for key in c.LIMITS:
            changed = copy.deepcopy(original); changed['limits'][key] += 1
            with self.subTest(key=key), self.assertRaises(c.Refused): c.validate_authorization(changed)

    def test_public_collector_refuses_missing_control_before_io(self):
        with patch.object(c, 'gh_json', side_effect=AssertionError), patch.object(cap, 'OwnerDrive', side_effect=AssertionError):
            with self.assertRaisesRegex(c.Refused, '^CAMPAIGN_CONTROL_REQUIRED$'):
                cap.run(SimpleNamespace())

    def test_preflight_cannot_bypass_explicit_workflow_consent(self):
        with patch.dict(os.environ,{},clear=True), patch.object(c,'history',side_effect=AssertionError):
            with self.assertRaisesRegex(c.Refused,'^USER_AUTHORIZATION_MISSING$'):
                c.worker(SimpleNamespace(),dict(preflight_only=True),Path('unused'))

    def test_oversized_and_nonregular_local_inputs_refuse(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'input.json';p.write_bytes(b'x'*65537)
            with self.assertRaises(c.Refused):c.bounded_json(p)
            with self.assertRaises((c.Refused,OSError)):c.bounded_json(Path(temp))

    @unittest.skipUnless(hasattr(os,'mkfifo'),'POSIX FIFO counterexample')
    def test_fifo_without_writer_refuses_without_blocking(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'input';os.mkfifo(p)
            with self.assertRaises(c.Refused):c.bounded_json(p)

    def test_provider_exact_limit_next_attempt_never_opens(self):
        with tempfile.TemporaryDirectory() as temp:
            opener = Opener(); limits = dict(c.LIMITS, provider_gets=1)
            m = meter(temp, opener, limits)
            self.assertEqual(m.perform(cap.URL, limit=4), b'abc')
            with self.assertRaisesRegex(c.Refused, '^CAMPAIGN_BUDGET_PROVIDER_GETS$'):
                m.perform(cap.URL, limit=4)
            self.assertEqual(opener.calls, 1)
            self.assertEqual(c.bounded_json(m.journal)['usage']['provider_gets'], 1)

    def test_google_count_bytes_multipart_and_overhead(self):
        with tempfile.TemporaryDirectory() as temp:
            opener = Opener(); m = meter(temp, opener)
            m.perform('https://www.googleapis.com/upload/drive/v3/files', method='POST', body=b'payload', limit=8)
            self.assertEqual(m.used['drive_requests'], 1)
            self.assertEqual(m.used['drive_bytes'], 65536 + 7 + 3)
            self.assertEqual(m.observed_google_body_bytes, 10)

    def test_byte_limit_refuses_before_network(self):
        with tempfile.TemporaryDirectory() as temp:
            opener = Opener(); m = meter(temp, opener, dict(c.LIMITS, drive_bytes=65539))
            with self.assertRaisesRegex(c.Refused, '^CAMPAIGN_BUDGET_DRIVE_BYTES$'):
                m.perform('https://www.googleapis.com/drive/v3/about', limit=4)
            self.assertEqual(opener.calls, 0)
            self.assertEqual(m.used['drive_requests'], 0)

    def test_limit_plus_one_retains_entire_reservation(self):
        with tempfile.TemporaryDirectory() as temp:
            m = meter(temp, Opener(b'12345'))
            with self.assertRaisesRegex(c.Refused, '^RESPONSE_SIZE$'):
                m.perform('https://www.googleapis.com/drive/v3/about', limit=4)
            self.assertEqual(m.used['drive_bytes'], 65541)
            self.assertFalse(c.bounded_json(m.journal)['finalized'])

    def test_partial_body_and_timeout_keep_debit_without_secret_error(self):
        class Partial(Opener):
            def open(self, request, **kwargs): return Reply(b'ab', fail=True)
        for opener in [Partial(), Opener(failure=TimeoutError('PRIVATE_CANARY'))]:
            with self.subTest(kind=type(opener).__name__), tempfile.TemporaryDirectory() as temp:
                m = meter(temp, opener)
                with self.assertRaisesRegex(c.Refused, '^NETWORK$'):
                    m.perform('https://www.googleapis.com/drive/v3/about', limit=4)
                self.assertEqual(m.used['drive_bytes'], 65541)
                self.assertNotIn('PRIVATE', m.journal.read_text())

    def test_auth_permission_quota_failures_are_charged(self):
        for status, code in [(401, 'AUTH'), (402, 'ENTITLEMENT'), (403, 'PERMISSION'), (429, 'RATE_LIMIT')]:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temp:
                failure = HTTPError(cap.URL, status, 'PRIVATE', {}, io.BytesIO(b'private'))
                m = meter(temp, Opener(failure=failure))
                with self.assertRaisesRegex(c.Refused, '^' + code + '$'): m.perform(cap.URL, limit=4)
                self.assertEqual(m.used['provider_gets'], 1)

    def test_storage_failed_upload_is_not_refunded(self):
        with tempfile.TemporaryDirectory() as temp:
            m = meter(temp, allowance=dict(c.LIMITS, storage_bytes=4))
            m.reserve_storage(4)
            with self.assertRaisesRegex(c.Refused, '^CAMPAIGN_BUDGET_STORAGE_BYTES$'): m.reserve_storage(1)
            self.assertEqual(m.used['storage_bytes'], 4)
            self.assertEqual(m.confirmed_storage_bytes, 0)

    def test_deadline_refuses_next_io(self):
        now = [c.utc()]
        with tempfile.TemporaryDirectory() as temp:
            opener = Opener(); m = meter(temp, opener, clock=lambda: now[0], seconds=1)
            now[0] += timedelta(seconds=1)
            with self.assertRaisesRegex(c.Refused, '^CAMPAIGN_DEADLINE$'): m.perform(cap.URL, limit=4)
            self.assertEqual(opener.calls, 0)

    @unittest.skipUnless(hasattr(c.signal, 'setitimer'), 'POSIX live worker alarm;Windows host remains supported')
    def test_alarm_interrupts_slow_header_open(self):
        import time
        class Slow(Opener):
            def open(self, request, **kwargs): time.sleep(2); return Reply(b'a')
        with tempfile.TemporaryDirectory() as temp:
            m = meter(temp, Slow(), seconds=0.03)
            with self.assertRaisesRegex(c.Refused, '^CAMPAIGN_DEADLINE$'), m.process_deadline():
                m.perform(cap.URL, limit=4)
            self.assertEqual(m.used['provider_gets'], 1)

    def test_endpoint_no_broker_or_paid_mutation(self):
        for url in ('https://paper-api.alpaca.markets/v2/orders', 'https://www.googleapis.com.evil/drive/v3/about',
                    'http://data.alpaca.markets/v2/stocks/bars', 'https://data.alpaca.markets/v2/account'):
            with self.subTest(url=url), tempfile.TemporaryDirectory() as temp:
                opener = Opener(); m = meter(temp, opener)
                with self.assertRaises(c.Refused): m.perform(url, limit=4)
                self.assertEqual(opener.calls, 0)

    def test_credential_echo_never_settles_or_enters_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            m = meter(temp, Opener(b'private-credential'))
            with self.assertRaisesRegex(c.Refused, '^CREDENTIAL_ECHO$'):
                m.perform('https://www.googleapis.com/drive/v3/about', limit=20, credentials=('private-credential',))
            self.assertNotIn('private-credential', m.journal.read_text())
            self.assertEqual(m.used['drive_bytes'], 65557)


class JournalTests(unittest.TestCase):
    def test_lock_chain_and_second_writer_refusal(self):
        with tempfile.TemporaryDirectory() as temp:
            first = c.WorkJournal(temp, 'a' * 64)
            try:
                first.append('RESERVED', nonce='n', remaining=dict(c.LIMITS))
                with self.assertRaisesRegex(c.Refused, '^CAMPAIGN_WRITER_LOCK$'): c.WorkJournal(temp, 'a' * 64)
            finally: first.close()
            second = c.WorkJournal(temp, 'a' * 64)
            self.assertEqual(second.entries[0]['kind'], 'RESERVED')
            first.close()  # Must not unlink the new writer's lock.
            self.assertTrue(second.lock.exists())
            second.close()

    def test_unknown_dispatch_reservation_survives_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            j = c.WorkJournal(temp, 'a' * 64); j.append('RESERVED', nonce='unknown', remaining=dict(c.LIMITS)); j.close()
            j = c.WorkJournal(temp, 'a' * 64)
            try:
                with self.assertRaisesRegex(c.Refused, '^CAMPAIGN_JOURNAL_REMOTE_CONFLICT$'): j.reconcile([])
                self.assertEqual(j.entries[-1]['remaining'], c.LIMITS)
            finally: j.close()

    def test_valid_old_prefix_rollback_refused_against_canonical_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            j = c.WorkJournal(temp, 'a' * 64); j.append('RESERVED', nonce='old'); j.close()
            # The older file is intact and correctly hashed, but remote knows
            # a later dispatch. A local hash chain alone would accept this.
            j = c.WorkJournal(temp, 'a' * 64)
            try:
                with self.assertRaisesRegex(c.Refused, '^CAMPAIGN_JOURNAL_REMOTE_CONFLICT$'):
                    j.reconcile([dict(display_title='a1-sip old'), dict(display_title='a1-sip new')])
            finally: j.close()

    def test_corruption_missing_entry_and_wrong_authority(self):
        for mode in ('corrupt', 'gap', 'wrong_auth'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                j = c.WorkJournal(temp, 'a' * 64); j.append('RESERVED', nonce='old'); j.close()
                p = Path(temp) / '000001.json'
                if mode == 'corrupt': p.write_text('{}')
                elif mode == 'gap': p.rename(p.with_name('000002.json'))
                with self.assertRaises(c.Refused): c.WorkJournal(temp, ('b' if mode == 'wrong_auth' else 'a') * 64)


class HistoryTests(unittest.TestCase):
    def test_account_record_requires_actual_owner_and_matching_scope(self):
        bindings=dict(owner_sha256='a'*64,credential_binding='b'*64)
        record=dict(task_key=c.TASK,auth_sha256='c'*64,bindings=bindings,
                    agreement_reviewed=True,account_eligible=True,historical_sip_allowed=True,
                    private_retention_allowed=True,private_noncommercial=True,
                    evidence_reference='SYNTHETIC_OWNER_RECORD',expires_at_utc=(c.utc()+timedelta(hours=1)).isoformat())
        comment=dict(issue_url=f'https://api.github.com/repos/{c.REPO}/issues/448',author_association='OWNER',
                     user=dict(type='User'),created_at=c.utc().isoformat(),
                     body='A1_SIP_ACCOUNT_PERMISSION '+json.dumps(record))
        reference=f'https://github.com/{c.REPO}/issues/448#issuecomment-1'
        with patch.object(c,'gh_json',return_value=comment):
            c.verify_account_permission(reference,'c'*64,bindings)
            for key,value in [('historical_sip_allowed',False),('private_retention_allowed',None),('auth_sha256','d'*64)]:
                bad=dict(record);bad[key]=value
                with self.subTest(key=key),patch.object(c,'gh_json',return_value=dict(comment,body='A1_SIP_ACCOUNT_PERMISSION '+json.dumps(bad))),self.assertRaises(c.Refused):
                    c.verify_account_permission(reference,'c'*64,bindings)
            with patch.object(c,'gh_json',return_value=dict(comment,user=dict(type='Bot'))),self.assertRaises(c.Refused):
                c.verify_account_permission(reference,'c'*64,bindings)
        with patch.object(c,'gh_json',side_effect=AssertionError),self.assertRaises(c.Refused):
            c.verify_account_permission('HTTP200_IS_NOT_LICENSE','c'*64,bindings)
    def test_batch_shape_and_partial_recovery_hits128(self):
        sizes=[]; prefix=16
        while prefix<1009:
            size=c.next_batch(prefix);sizes.append(size);prefix+=size
        self.assertEqual(sizes,[32]*31+[1])
        self.assertEqual(c.next_batch(140),4)
        self.assertEqual(c.next_batch(144),32)

    def test_calibration_excludes_metadata_preflight_from_cost_slope(self):
        receipts=[dict(examined_before=16,examined_after=16,usage=dict(provider_gets=0,drive_requests=3,drive_bytes=200000,storage_bytes=0))]
        prefix=16
        for i in range(4):
            receipts.append(dict(examined_before=prefix,examined_after=prefix+32,
                                 usage=dict(provider_gets=24,drive_requests=260+64*i,drive_bytes=25_000_000+12_000_000*i,storage_bytes=8_000_000)))
            prefix+=32
        used={key:sum(r['usage'][key] for r in receipts) for key in c.LIMITS}
        observed=dict(examined=144,receipts=receipts,durations=[1,30,35,40,45],used=used,
                      active_seconds=151,remaining={k:c.LIMITS[k]-used[k] for k in c.LIMITS})
        forecast=c.forecast_remaining(observed)
        self.assertTrue(forecast['fits_current_budgets'])
        self.assertLess(forecast['estimated_remaining']['drive_requests'],50000)
        observed['remaining']['provider_gets']=1
        self.assertFalse(c.forecast_remaining(observed)['fits_current_budgets'])

    def test_summary_separates_processing_fields_and_eligibility(self):
        observed=dict(examined=48,used={k:1 for k in c.LIMITS},active_seconds=10,
                      runs=[{}],parent_sha='a'*64,first=None,
                      receipts=[dict(new_states=dict(VALID_COLLECTED=28,VERIFIED_NO_DATA=0,QUARANTINED=4),
                                     rows_verified=56,confirmed_storage_bytes=0,observed_google_body_bytes=1)])
        report=c.progress_summary(observed,'BLOCKED')
        self.assertEqual(report['states']['PENDING'],961)
        self.assertEqual(report['total_processed'],48)
        self.assertEqual(report['states']['VALID_COLLECTED'],44)
        self.assertEqual(report['session_grid_coverage'],'NOT_ESTABLISHED')
        self.assertFalse(report['source_admission'])

    def test_duplicate_nonce_or_incomplete_history_refuses(self):
        run = dict(display_title='a1-sip ' + c.PREFIX + 'a' * 24, created_at=c.utc().isoformat(), id=1)
        for payload in (dict(total_count=101, workflow_runs=[]), dict(total_count=2, workflow_runs=[run, dict(run, id=2)])):
            with patch.object(c, 'gh_json', return_value=payload), self.assertRaises(c.Refused): c.campaign_runs()

    def test_run_number_gap_cannot_hide_an_intermediate_job(self):
        payload = dict(total_count=2, workflow_runs=[dict(display_title='offline', run_number=1), dict(display_title='offline2', run_number=3)])
        with patch.object(c, 'gh_json', return_value=payload), self.assertRaisesRegex(c.Refused, '^CAMPAIGN_HISTORY_GAP$'):
            c.campaign_runs(1)

    def test_rerun_or_wrong_current_nonce_refuses_before_io(self):
        a = auth(); nonce = c.PREFIX + 'a' * 24
        for change in (dict(run_attempt=2), dict(head_sha='2' * 40), dict(display_title='a1-sip other')):
            run = dict(id=1, display_title='a1-sip ' + nonce, run_attempt=1, head_sha=a['expected_master'], created_at=c.utc().isoformat())
            run.update(change)
            with patch.object(c, 'campaign_runs', return_value=[run]), self.assertRaisesRegex(c.Refused, '^CAMPAIGN_SINGLE_USE$'):
                c.history(a, 1, nonce)

    def test_complete_receipt_must_chain_allowance_and_progress(self):
        a = auth(); nonce = c.PREFIX + 'a' * 24
        run = dict(id=1, display_title='a1-sip ' + nonce, run_attempt=1, head_sha=a['expected_master'],
                   head_branch='master', created_at=c.utc().isoformat(), status='completed', conclusion='success')
        value = dict(parent_checkpoint_sha256=c.INITIAL_SHA, examined_before=16, examined_after=48,
                     checkpoint_sha256='b' * 64, usage={k: 1 for k in c.LIMITS}, allowance=dict(c.LIMITS), status='COMPLETE')
        with patch.object(c, 'campaign_runs', return_value=[run]), patch.object(c, 'receipt_for_run', return_value=value), patch.object(c, 'job_seconds', return_value=10):
            observed = c.history(a)
            self.assertEqual(observed['examined'], 48)
            self.assertEqual(observed['remaining']['provider_gets'], 1999)
            for key, changed in [('parent_checkpoint_sha256', '0' * 64), ('examined_before', 0), ('examined_after', 49), ('allowance', dict(c.LIMITS, provider_gets=1999))]:
                bad = dict(value); bad[key] = changed
                with self.subTest(key=key), patch.object(c, 'receipt_for_run', return_value=bad), self.assertRaises(c.Refused): c.history(a)

    def test_expiry_and_active_time_do_not_reset_per_job(self):
        a = auth()
        old = dict(id=1, display_title='a1-sip ' + c.PREFIX + 'a' * 24, created_at=(c.utc()-timedelta(hours=49)).isoformat())
        value = dict(parent_checkpoint_sha256=c.INITIAL_SHA, examined_before=16, examined_after=16,
                     checkpoint_sha256=c.INITIAL_SHA, usage={k: 0 for k in c.LIMITS}, allowance=dict(c.LIMITS), status='COMPLETE')
        old['conclusion'] = 'success'
        with patch.object(c, 'campaign_runs', return_value=[old]), patch.object(c, 'receipt_for_run', return_value=value), patch.object(c, 'job_seconds', return_value=10):
            with self.assertRaisesRegex(c.Refused, '^CAMPAIGN_EXPIRED$'): c.history(a)


class Server(Opener):
    """In-memory Google/Alpaca fixture. No real requests or vendor input."""
    def __init__(self, missing=None, invalid=None, lost_post=False):
        self.objects, self.symbols = {}, set()
        self.requests=[]
        self.missing, self.invalid, self.lost_post = missing, invalid, lost_post
    def open(self, request, **kwargs):
        self.requests.append(request.full_url)
        parts = urlsplit(request.full_url); q = parse_qs(parts.query)
        if parts.netloc == 'data.alpaca.markets':
            names = q['symbols'][0].split(','); self.symbols.update(names)
            bars = {n: [dict(t='2016-01-04T05:00:00Z', o=10,h=11,l=9,c=(0 if n == self.invalid else 10),v=10)] for n in names if n != self.missing}
            return Reply(c.encoded(dict(bars=bars, next_page_token=None)))
        if parts.path == '/drive/v3/about':
            return Reply(c.encoded(dict(user=dict(permissionId='fixture-owner'), storageQuota=dict(limit=str(5*1024**3),usage='0'))))
        if parts.path == '/upload/drive/v3/files':
            message = BytesParser(policy=policy.default).parsebytes(('Content-Type: '+request.get_header('Content-type')+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+request.data)
            children=list(message.iter_parts()); metadata=json.loads(children[0].get_payload(decode=True)); body=children[1].get_payload(decode=True)
            file_id='fixture-object-'+str(len(self.objects)+1).zfill(8)
            self.objects[file_id]=(metadata,body)
            if self.lost_post:
                self.lost_post=False
                raise OSError('PRIVATE_ACK_LOST')
            return Reply(c.encoded(dict(id=file_id)))
        if parts.path == '/drive/v3/files':
            query=q['q'][0]; name=query.split("name = '",1)[1].split("'",1)[0]
            found=[dict(id=k,name=v[0]['name'],parents=v[0]['parents']) for k,v in self.objects.items() if v[0]['name']==name]
            return Reply(c.encoded(dict(files=found)))
        file_id=parts.path.rsplit('/',1)[-1]
        if q.get('alt')==['media']: return Reply(self.objects[file_id][1])
        if file_id=='fixture-root-123': parents=[]; mime='application/vnd.google-apps.folder'
        elif file_id=='fixture-data-123': parents=['fixture-root-123']; mime='application/vnd.google-apps.folder'
        else: parents=self.objects[file_id][0]['parents']; mime='application/octet-stream'
        return Reply(c.encoded(dict(id=file_id,mimeType=mime,trashed=False,shared=False,parents=parents,
                                   permissions=[dict(id='fixture-owner',type='user',role='owner')])))


class WorkerIntegrationTests(unittest.TestCase):
    def execute(self, server, preflight=False, unknown=False, expected_precondition=False):
        a=auth(); nonce=c.PREFIX+'a'*24
        if unknown:
            for key in ('owner_permission_id','credential_binding','account_permission_reference'):a[key]=None
        names=cap.cohort(cap.SEED.read_bytes())
        args=SimpleNamespace(private_root_folder_id=a['private_root_folder_id'], private_data_folder_id=a['private_data_folder_id'],
                             resume_file_id=a['initial_checkpoint_file_id'], resume_sha256=c.INITIAL_SHA,
                             start=a['start'], end=a['end'], max_new_symbols=32)
        env=dict(GITHUB_REPOSITORY=c.REPO,GITHUB_REF='refs/heads/master',GITHUB_SHA=a['expected_master'],
                 GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_RUN_ATTEMPT='1',GITHUB_RUN_ID='1',INPUT_CAMPAIGN_NONCE=nonce,
                 A1_PRIVATE_RESEARCH_AUTHORIZED='true',ALPACA_NONCOMMERCIAL_ACKNOWLEDGED='true',
                 ALPACA_API_KEY='fixture-key',ALPACA_API_SECRET='fixture-secret',
                 MACRO_DRIVE_CONFIG='[gdrive]\ntype=drive\ntoken='+json.dumps(dict(access_token='fixture-access',refresh_token='fixture-refresh',expiry='2030-01-01T00:00:00Z'))+'\n')
        prior=dict(file_id=a['initial_checkpoint_file_id'],sha256=c.INITIAL_SHA,bytes=1375)
        original_meter=c.RuntimeMeter
        original_pages=cap.request_pages
        def instrument(*args,**kwargs): return original_meter(*args,opener=server,**kwargs)
        def pages(*args,**kwargs): return original_pages(*args,pause=lambda _: None,**kwargs)
        observed=dict(runs=[{}], active_seconds=0, parent_sha=c.INITIAL_SHA, examined=16,
                      remaining=dict(c.LIMITS),first=c.utc())
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,env,clear=True), \
                patch.object(c,'history',return_value=observed), patch.object(c,'RuntimeMeter',side_effect=instrument), \
                patch.object(c,'worker_deadline',return_value=c.utc()+timedelta(seconds=7100)), \
                patch.object(c,'verify_account_permission'), \
                patch.object(cap,'request_pages',side_effect=pages), \
                patch.object(cap,'resume_state',return_value=(names[:16],names[:16].copy(),[],prior)), \
                patch.object(cap,'time') as clock, patch.object(drive_module.subprocess,'run',side_effect=AssertionError), \
                patch('sys.stdout',new=io.StringIO()):
            path=Path(temp)/'campaign_meter.json'
            # Production Linux uses the exact Git-LF seed. Native CRLF is a
            # different byte context; make that exact LF fixture explicitly.
            seed=Path(temp)/'seed.csv'
            seed.write_bytes(cap.SEED.read_bytes().replace(b'\r\n',b'\n'))
            self.assertEqual(c.digest(seed.read_bytes()),c.SEED_SHA)
            with patch.object(cap,'SEED',seed):
                try: c.worker(args,dict(authorization=a,nonce=nonce,preflight_only=preflight),path)
                except c.Refused as exc: failure=str(exc)
                else: failure=None
            if not path.exists():
                if expected_precondition:return failure,None,names
                raise AssertionError('Worker precondition: ' + str(failure))
            return failure,c.bounded_json(path),names

    def test_real_collector_meter_and_independent_semantic_readback(self):
        server=Server(); failure,receipt,names=self.execute(server)
        self.assertIsNone(failure)
        self.assertEqual(server.symbols,set(names[16:48]))
        self.assertTrue(server.symbols.isdisjoint(names[:16]))
        self.assertEqual(receipt['examined_after'],48)
        self.assertEqual(receipt['rows_verified'],64)
        self.assertEqual(receipt['usage']['provider_gets'],16)
        self.assertEqual(receipt['new_states'],dict(VALID_COLLECTED=32,VERIFIED_NO_DATA=0,QUARANTINED=0))
        self.assertEqual(receipt['usage']['storage_bytes'],receipt['confirmed_storage_bytes'])
        self.assertFalse(receipt['source_admission']); self.assertFalse(receipt['pit_verified'])
        self.assertEqual(receipt['status'],'COMPLETE')

    def test_unknown_bindings_preflight_reads_only_actual_private_metadata(self):
        server=Server();failure,receipt,_=self.execute(server,preflight=True,unknown=True)
        self.assertIsNone(failure);self.assertEqual(server.symbols,set())
        self.assertEqual(receipt['usage']['provider_gets'],0)
        self.assertEqual(receipt['usage']['storage_bytes'],0)
        self.assertEqual(receipt['examined_after'],16)
        self.assertEqual(receipt['bindings']['credential_binding'],c.digest(b'fixture-key\0fixture-secret'))
        self.assertEqual(receipt['free_bytes_at_start'],5*1024**3)
        self.assertIsNone(receipt['account_permission_reference_sha256'])

    def test_unknown_account_proof_cannot_capture_or_bootstrap(self):
        server=Server();failure,receipt,_=self.execute(server,unknown=True,expected_precondition=True)
        self.assertEqual(failure,'CAMPAIGN_ACCOUNT_PROOF_REQUIRED')
        self.assertIsNone(receipt);self.assertEqual(server.requests,[])

    def test_no_data_and_held_are_separate_from_valid(self):
        names=cap.cohort(cap.SEED.read_bytes())
        for server,expected in [(Server(missing=names[16]),dict(VALID_COLLECTED=31,VERIFIED_NO_DATA=1,QUARANTINED=0)),
                                (Server(invalid=names[16]),dict(VALID_COLLECTED=28,VERIFIED_NO_DATA=0,QUARANTINED=4))]:
            with self.subTest(expected=expected):
                failure,receipt,_=self.execute(server)
                self.assertIsNone(failure); self.assertEqual(receipt['new_states'],expected)

    def test_accepted_post_lost_ack_keeps_reservation_and_parent(self):
        server=Server(lost_post=True); failure,receipt,_=self.execute(server)
        self.assertEqual(failure,'NETWORK')
        self.assertTrue(server.objects)
        self.assertGreater(receipt['usage']['storage_bytes'],0)
        self.assertEqual(receipt['confirmed_storage_bytes'],0)
        self.assertEqual(receipt['checkpoint_sha256'],c.INITIAL_SHA)
        self.assertEqual(receipt['examined_after'],16)
        self.assertTrue(receipt['finalized']); self.assertEqual(receipt['status'],'BLOCKED')


if __name__=='__main__': unittest.main()

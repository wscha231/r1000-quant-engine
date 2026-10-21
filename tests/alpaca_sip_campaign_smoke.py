"""Offline counterexamples; synthetic fixtures are never vendor/PIT proof."""
import copy
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from http.client import HTTPResponse
import io
import json
import os
import sys
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


class WireOpener:
    """Real stdlib framing over memory; no socket or network is opened."""
    def __init__(self, wire):
        self.wire, self.closed, self.calls = wire, False, 0
    def settimeout(self, value):
        if self.closed:
            raise OSError("already closed socket")
    def makefile(self, *_):
        owner = self
        class Raw(io.RawIOBase):
            def __init__(self):
                super().__init__()
                self._sock, self.data = owner, io.BytesIO(owner.wire)
            def readable(self): return True
            def readinto(self, target): return self.data.readinto(target)
            def close(self):
                owner.closed = True
                super().close()
        return io.BufferedReader(Raw())
    def open(self, *_args, **_kwargs):
        self.calls += 1
        reply = HTTPResponse(self)
        reply.begin()
        return reply


def meter(directory, opener=None, allowance=None, clock=c.utc, seconds=60):
    return c.RuntimeMeter(allowance or dict(c.LIMITS), Path(directory) / "campaign_meter.json",
                          (clock() + timedelta(seconds=seconds)).isoformat(), identity(),
                          opener=opener or Opener(), clock=clock)


class AlarmSignal:
    """Controlled setup failures; this fixture never sends an OS signal."""
    SIGALRM, ITIMER_REAL = 14, 0

    def __init__(self, on_install=lambda: None, fail=None):
        self.original = self.handler = object()
        self.timer, self.on_install, self.fail = (0, 0), on_install, fail

    def getitimer(self, _): return self.timer
    def getsignal(self, _): return self.handler

    def signal(self, _, handler):
        previous, self.handler = self.handler, handler
        if handler is not self.original:
            self.on_install()
        return previous

    def setitimer(self, _, seconds):
        phase = 'arm' if seconds else 'disarm'
        if self.fail == phase:
            raise OSError('fixture_' + phase)
        previous, self.timer = self.timer, (seconds, 0)
        return previous


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

    def test_real_http_content_length_completion_and_truncation(self):
        for url in ('https://www.googleapis.com/drive/v3/about', cap.URL):
            for length in (2, 99):
                with self.subTest(url=url, length=length), tempfile.TemporaryDirectory() as temp:
                    opener = WireOpener(b'HTTP/1.1 200 OK\r\nContent-Length: ' +
                                        str(length).encode() + b'\r\nConnection: close\r\n\r\n{}')
                    m = meter(temp, opener)
                    if length == 2:
                        self.assertEqual(m.perform(url, limit=100), b'{}')
                    else:
                        with self.assertRaisesRegex(c.Refused, '^NETWORK$'):
                            m.perform(url, limit=100)
                    self.assertTrue(opener.closed)
                    if url == cap.URL:
                        self.assertEqual(m.used['provider_gets'], 1)
                    else:
                        self.assertEqual(m.used['drive_bytes'], 65538 if length == 2 else 65637)
                        self.assertEqual(m.observed_google_body_bytes, 2 if length == 2 else 0)
                        self.assertEqual(c.bounded_json(m.journal)['usage'], m.used)

    def test_real_http_chunked_and_close_delimited_bodies(self):
        for headers, body, complete in (
                (b'Transfer-Encoding: chunked\r\n', b'2\r\n{}\r\n0\r\n\r\n', True),
                (b'Transfer-Encoding: chunked\r\n', b'9\r\n{}', False),
                (b'Transfer-Encoding: chunked\r\n', b'2\r\n{}\r\n', False),
                (b'', b'{}', True)):
            with self.subTest(headers=headers, body=body), tempfile.TemporaryDirectory() as temp:
                opener = WireOpener(b'HTTP/1.1 200 OK\r\n' + headers +
                                    b'Connection: close\r\n\r\n' + body)
                m = meter(temp, opener)
                if complete:
                    self.assertEqual(m.perform('https://www.googleapis.com/drive/v3/about', limit=100), b'{}')
                else:
                    with self.assertRaisesRegex(c.Refused, '^NETWORK$'):
                        m.perform('https://www.googleapis.com/drive/v3/about', limit=100)
                self.assertTrue(opener.closed)
                self.assertEqual(m.used['drive_bytes'], 65538 if complete else 65637)

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
            original = m.journal.read_bytes()
            now[0] += timedelta(seconds=1)
            with self.assertRaisesRegex(c.Refused, '^CAMPAIGN_DEADLINE$'): m.perform(cap.URL, limit=4)
            self.assertEqual(opener.calls, 0)
            self.assertEqual(m.used, {key: 0 for key in c.LIMITS})
            self.assertEqual(m.journal.read_bytes(), original)

    def test_alarm_setup_failures_restore_handler(self):
        for failure in ('expired', 'arm'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                now = [c.utc()]
                opener = Opener(); m = meter(temp, opener, clock=lambda: now[0], seconds=0.03)
                original = m.journal.read_bytes()
                def expire(): now[0] = m.deadline
                signals = AlarmSignal(on_install=expire if failure == 'expired' else lambda: None,
                                      fail='arm' if failure == 'arm' else None)
                error, message = (c.Refused, '^CAMPAIGN_DEADLINE$') if failure == 'expired' else (OSError, '^fixture_arm$')
                with patch.object(c, 'signal', signals), self.assertRaisesRegex(error, message):
                    with m.process_deadline(): self.fail('setup failure entered the body')
                self.assertIs(signals.handler, signals.original)
                self.assertEqual(signals.timer, (0, 0))
                self.assertFalse(m.alarm_active)
                self.assertEqual(opener.calls, 0)
                self.assertEqual(m.used, {key: 0 for key in c.LIMITS})
                self.assertEqual(m.journal.read_bytes(), original)

    def test_alarm_disarm_failure_retains_deadline_handler(self):
        with tempfile.TemporaryDirectory() as temp:
            now = c.utc()
            m = meter(temp, clock=lambda: now, seconds=0.03)
            original = m.journal.read_bytes()
            signals = AlarmSignal(fail='disarm')
            with patch.object(c, 'signal', signals), self.assertRaisesRegex(OSError, '^fixture_disarm$'):
                with m.process_deadline(): self.assertTrue(m.alarm_active)
            self.assertIsNot(signals.handler, signals.original)
            self.assertEqual(signals.timer, (0.03, 0))
            self.assertTrue(m.alarm_active)
            with self.assertRaisesRegex(c.Refused, '^CAMPAIGN_DEADLINE$'):
                signals.handler()
            self.assertEqual(m.used, {key: 0 for key in c.LIMITS})
            self.assertEqual(m.journal.read_bytes(), original)

    @unittest.skipUnless(hasattr(c.signal, 'setitimer'), 'POSIX failed disarm;Windows host remains supported')
    def test_failed_posix_disarm_keeps_pending_signal_safe(self):
        import subprocess
        import sys
        script = '''
import runpy, tempfile, unittest
from unittest.mock import patch
from tools import alpaca_sip_campaign as c
check = unittest.TestCase()
make_meter = runpy.run_path('tests/alpaca_sip_campaign_smoke.py')['meter']
real_setitimer = c.signal.setitimer
old = c.signal.getsignal(c.signal.SIGALRM)
def fail_disarm(which, seconds):
    if seconds == 0:
        raise OSError('fixture_disarm')
    return real_setitimer(which, seconds)
try:
    c.signal.signal(c.signal.SIGALRM, c.signal.SIG_DFL)
    with tempfile.TemporaryDirectory() as temp:
        now = c.utc()
        m = make_meter(temp, clock=lambda: now, seconds=60)
        original = m.journal.read_bytes()
        with patch.object(c.signal, 'setitimer', fail_disarm):
            with check.assertRaisesRegex(OSError, '^fixture_disarm$'):
                with m.process_deadline(): pass
        check.assertTrue(m.alarm_active)
        check.assertTrue(callable(c.signal.getsignal(c.signal.SIGALRM)))
        check.assertGreater(c.signal.getitimer(c.signal.ITIMER_REAL)[0], 0)
        # Defuse the wall timer, then deliver a real SIGALRM deterministically.
        # This isolates retained-handler safety from scheduler timing.
        real_setitimer(c.signal.ITIMER_REAL, 0)
        with check.assertRaisesRegex(c.Refused, '^CAMPAIGN_DEADLINE$'):
            c.signal.raise_signal(c.signal.SIGALRM)
        check.assertEqual(m.used, {key: 0 for key in c.LIMITS})
        check.assertEqual(m.journal.read_bytes(), original)
finally:
    real_setitimer(c.signal.ITIMER_REAL, 0)
    c.signal.signal(c.signal.SIGALRM, old)
print('POSIX_FAILED_DISARM_RETAINED_HANDLER_PASS')
'''
        command = [sys.executable] + ([] if __debug__ else ['-O']) + ['-c', script]
        result = subprocess.run(command, cwd=c.ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('POSIX_FAILED_DISARM_RETAINED_HANDLER_PASS', result.stdout)

    @unittest.skipUnless(hasattr(c.signal, 'setitimer'), 'POSIX alarm setup;Windows host remains supported')
    def test_expired_posix_alarm_setup_restores_handler(self):
        now = [c.utc()]
        with tempfile.TemporaryDirectory() as temp:
            opener = Opener(); m = meter(temp, opener, clock=lambda: now[0], seconds=0.03)
            original = m.journal.read_bytes()
            handler = c.signal.getsignal(c.signal.SIGALRM)
            now[0] = m.deadline
            with self.assertRaisesRegex(c.Refused, '^CAMPAIGN_DEADLINE$'):
                with m.process_deadline(): self.fail('expired setup entered the body')
            self.assertIs(c.signal.getsignal(c.signal.SIGALRM), handler)
            self.assertEqual(c.signal.getitimer(c.signal.ITIMER_REAL), (0, 0))
            self.assertFalse(m.alarm_active)
            self.assertEqual(opener.calls, 0)
            self.assertEqual(m.used, {key: 0 for key in c.LIMITS})
            self.assertEqual(m.journal.read_bytes(), original)

    @unittest.skipUnless(hasattr(c.signal, 'setitimer'), 'POSIX live worker alarm;Windows host remains supported')
    def test_alarm_interrupts_slow_header_open(self):
        import time
        test, now, entered = self, [c.utc()], []
        class Slow(Opener):
            def open(self, request, **kwargs):
                self.calls += 1
                test.assertEqual(c.bounded_json(m.journal)['usage']['provider_gets'], 1)
                entered.append('header')
                # Start the real 30ms alarm at the intended phase, after the
                # durable debit. Journal latency cannot consume this fixture's
                # header interval; pre-I/O expiry is tested independently.
                with m.process_deadline(): time.sleep(2)
                test.fail('blocking header open escaped the POSIX alarm')
        with tempfile.TemporaryDirectory() as temp:
            opener = Slow(); m = meter(temp, opener, clock=lambda: now[0], seconds=0.03)
            handler = c.signal.getsignal(c.signal.SIGALRM)
            with self.assertRaisesRegex(c.Refused, '^CAMPAIGN_DEADLINE$'):
                m.perform(cap.URL, limit=4)
            self.assertEqual(entered, ['header'])
            self.assertEqual(opener.calls, 1)
            self.assertEqual(m.used['provider_gets'], 1)
            self.assertEqual(c.bounded_json(m.journal)['usage'], m.used)
            self.assertIs(c.signal.getsignal(c.signal.SIGALRM), handler)
            self.assertEqual(c.signal.getitimer(c.signal.ITIMER_REAL), (0, 0))
            self.assertFalse(m.alarm_active)
            now[0] = m.deadline
            with self.assertRaisesRegex(c.Refused, '^CAMPAIGN_DEADLINE$'): m.perform(cap.URL, limit=4)
            self.assertEqual(opener.calls, 1)
            self.assertEqual(m.used['provider_gets'], 1)
            self.assertEqual(c.bounded_json(m.journal)['usage'], m.used)

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
                    evidence_reference='SYNTHETIC_OWNER_RECORD',expires_at_utc=(c.utc()+timedelta(hours=3)).isoformat())
        deadline=c.utc()+timedelta(seconds=7100)
        comment=dict(id=1,issue_url=f'https://api.github.com/repos/{c.REPO}/issues/448',author_association='OWNER',
                     user=dict(type='User',id=123),created_at=c.utc().isoformat(),
                     body='A1_SIP_ACCOUNT_PERMISSION '+json.dumps(record))
        reference=f'https://github.com/{c.REPO}/issues/448#issuecomment-1'
        with patch.object(c,'gh_json',return_value=comment):
            original_hash=c.verify_account_permission(reference,'c'*64,bindings,valid_through=deadline)
            self.assertRegex(original_hash,r'^[a-f0-9]{64}$')
            for key,value in [('historical_sip_allowed',False),('private_retention_allowed',None),('auth_sha256','d'*64)]:
                bad=dict(record);bad[key]=value
                with self.subTest(key=key),patch.object(c,'gh_json',return_value=dict(comment,body='A1_SIP_ACCOUNT_PERMISSION '+json.dumps(bad))),self.assertRaises(c.Refused):
                    c.verify_account_permission(reference,'c'*64,bindings,valid_through=deadline)
            with patch.object(c,'gh_json',return_value=dict(comment,user=dict(type='Bot'))),self.assertRaises(c.Refused):
                c.verify_account_permission(reference,'c'*64,bindings,valid_through=deadline)
            expired_soon=dict(record,expires_at_utc=(c.utc()+timedelta(seconds=30)).isoformat())
            with patch.object(c,'gh_json',return_value=dict(comment,body='A1_SIP_ACCOUNT_PERMISSION '+json.dumps(expired_soon))),self.assertRaisesRegex(c.Refused,'^CAMPAIGN_ACCOUNT_EXPIRED$'):
                c.verify_account_permission(reference,'c'*64,bindings,valid_through=deadline)
            for changed in (dict(record,evidence_reference='EDITED_EVIDENCE'),
                            dict(record,expires_at_utc=(c.utc()+timedelta(hours=4)).isoformat())):
                with patch.object(c,'gh_json',return_value=dict(comment,body='A1_SIP_ACCOUNT_PERMISSION '+json.dumps(changed))):
                    self.assertNotEqual(c.verify_account_permission(reference,'c'*64,bindings,valid_through=deadline),original_hash)
            with patch.object(c,'gh_json',return_value=dict(comment,user=dict(type='User',id=124))):
                self.assertNotEqual(c.verify_account_permission(reference,'c'*64,bindings,valid_through=deadline),original_hash)
            with patch.object(c,'gh_json',return_value=dict(comment,body=comment['body']+'\nChanged owner context')):
                self.assertNotEqual(c.verify_account_permission(reference,'c'*64,bindings,valid_through=deadline),original_hash)
            exact=dict(record,expires_at_utc=deadline.isoformat())
            with patch.object(c,'gh_json',return_value=dict(comment,body='A1_SIP_ACCOUNT_PERMISSION '+json.dumps(exact))):
                self.assertRegex(c.verify_account_permission(reference,'c'*64,bindings,valid_through=deadline),r'^[a-f0-9]{64}$')
        with patch.object(c,'gh_json',side_effect=AssertionError),self.assertRaises(c.Refused):
            c.verify_account_permission('HTTP200_IS_NOT_LICENSE','c'*64,bindings,valid_through=deadline)
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

    def test_short_recovery_cannot_replace_full_batch_byte_or_time_forecast(self):
        receipts=[];prefix=16
        for size,cost in ((32,100_000_000),(32,100_000_000),(32,100_000_000),
                          (28,90_000_000),(4,1_000_000)):
            receipts.append(dict(examined_before=prefix,examined_after=prefix+size,
                                 usage=dict(provider_gets=0,drive_requests=0,drive_bytes=cost,storage_bytes=0)))
            prefix+=size
        observed=dict(examined=144,receipts=receipts,durations=[100,100,100,90,1],
                      active_seconds=391,remaining=dict(c.LIMITS,drive_bytes=500_000_000))
        forecast=c.forecast_remaining(observed)
        self.assertFalse(forecast['fits_current_budgets'])
        self.assertGreaterEqual(forecast['estimated_remaining']['drive_bytes'],28*100_000_000*1.25)
        self.assertGreaterEqual(forecast['estimated_remaining_active_seconds'],28*100*1.25)

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
        payload = dict(total_count=2, workflow_runs=[dict(id=1,display_title='offline', run_number=1), dict(id=3,display_title='offline2', run_number=3)])
        with patch.object(c, 'gh_json', return_value=payload), self.assertRaisesRegex(c.Refused, '^CAMPAIGN_HISTORY_GAP$'):
            c.campaign_runs(1)

    def test_floor_must_bind_the_next_first_dispatch_and_observed_sequence(self):
        offline=dict(display_title='offline',run_number=10,id=10,created_at=c.utc().isoformat())
        first=dict(display_title='a1-sip '+c.PREFIX+'a'*24,run_number=11,id=11,created_at=c.utc().isoformat())
        for runs,floor in (([offline],99),([offline,first],99),([offline,first],10)):
            with self.subTest(floor=floor,runs=len(runs)),patch.object(c,'gh_json',return_value=dict(total_count=len(runs),workflow_runs=runs)),self.assertRaisesRegex(c.Refused,'^CAMPAIGN_HISTORY_FLOOR$'):
                c.campaign_runs(floor)
        with patch.object(c,'gh_json',return_value=dict(total_count=1,workflow_runs=[offline])):
            self.assertEqual(c.campaign_runs(11),[])
        with patch.object(c,'gh_json',return_value=dict(total_count=2,workflow_runs=[offline,first])):
            self.assertEqual(c.campaign_runs(11),[first])

    def test_paginated_history_keeps_all_pr_checks_and_original_dispatch_floor(self):
        rows=[dict(id=i,run_number=i,display_title='a1-sip '+c.PREFIX+'a'*24 if i==1 else 'PR check',
                   created_at='2026-10-20T00:00:00Z') for i in range(201,0,-1)]
        pages=[dict(total_count=201,workflow_runs=rows[n:n+100]) for n in (0,100,200)]
        with patch.object(c,'gh_json',side_effect=pages+[pages[0]]) as read:
            self.assertEqual(c.campaign_runs(1),[rows[-1]])
        paths=[call.args[0] for call in read.call_args_list]
        self.assertEqual(len(paths),4)
        self.assertTrue(all('created=%3E%3D2026-10-14&per_page=100' in path for path in paths))
        self.assertTrue(paths[1].endswith('&page=2') and paths[2].endswith('&page=3'))
        self.assertEqual(paths[0],paths[-1])

    def test_paginated_history_refuses_duplicates_incomplete_pages_and_racing_snapshot(self):
        rows=[dict(id=i,run_number=i,display_title='PR check') for i in range(101,0,-1)]
        first=dict(total_count=101,workflow_runs=rows[:100])
        last=dict(total_count=101,workflow_runs=rows[100:])
        for suffix in (
            [dict(total_count=101,workflow_runs=[])],
            [dict(total_count=102,workflow_runs=rows[100:])],
            [dict(total_count=101,workflow_runs=[rows[0]])],
            [last,dict(total_count=102,workflow_runs=rows[:100])],
            [last,dict(total_count=101,workflow_runs=list(reversed(rows[:100])))],
            [last,dict(total_count=101,workflow_runs=rows[:100]+[None])]):
            with self.subTest(suffix=suffix[-1]['total_count']),\
                 patch.object(c,'gh_json',side_effect=[first]+suffix),self.assertRaises(c.Refused):
                c.campaign_runs(1)
        for total in (1001,-1,True):
            with self.subTest(total=total),patch.object(c,'gh_json',return_value=dict(total_count=total,workflow_runs=[])),\
                 self.assertRaisesRegex(c.Refused,'^CAMPAIGN_HISTORY_INCOMPLETE$'):
                c.campaign_runs()

    def test_same_permission_url_with_changed_record_breaks_history(self):
        a=auth();runs=[dict(id=i,display_title='a1-sip '+c.PREFIX+str(i)*24,
                          created_at=c.utc().isoformat(),conclusion='success') for i in (1,2)]
        first=dict(parent_checkpoint_sha256=c.INITIAL_SHA,examined_before=16,examined_after=48,
                   checkpoint_sha256='b'*64,usage={k:1 for k in c.LIMITS},allowance=dict(c.LIMITS),status='COMPLETE',
                   account_permission_reference_sha256='c'*64,account_permission_record_sha256='d'*64)
        second=dict(first,parent_checkpoint_sha256='b'*64,examined_before=48,examined_after=80,
                    allowance={k:c.LIMITS[k]-1 for k in c.LIMITS},account_permission_record_sha256='e'*64)
        with patch.object(c,'campaign_runs',return_value=runs),patch.object(c,'receipt_for_run',side_effect=[first,second]),patch.object(c,'job_seconds',return_value=1),self.assertRaisesRegex(c.Refused,'^CAMPAIGN_RIGHTS_DRIFT$'):
            c.history(a)

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
                patch.object(c,'verify_account_permission',return_value='f'*64), \
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
        self.assertEqual(receipt['account_permission_record_sha256'],'f'*64)
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
        self.assertIsNone(receipt['account_permission_record_sha256'])

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




class DirectCaptureDirectiveTests(unittest.TestCase):
    """Synthetic execution-consent fixtures; never supplier/account evidence."""
    def fixture(self):
        bindings = dict(owner_sha256='a' * 64, credential_binding='b' * 64)
        now = c.utc()
        reference = f'https://github.com/{c.REPO}/issues/448#issuecomment-1'
        record = dict(task_key=c.TASK, auth_sha256='c' * 64, bindings=bindings,
                      mode='DIRECT_HUMAN_CAPTURE_REQUEST', plan='Trading Basic',
                      personal_historical_capture_requested=True, private_noncommercial=True,
                      evidence_procedure_waived=True, supplier_rights_verified=False,
                      approval_reference=reference, expires_at_utc=(now + timedelta(hours=3)).isoformat())
        approval = dict(task_key=c.TASK, plan='Trading Basic',
                        personal_historical_capture_requested=True, private_noncommercial=True,
                        evidence_procedure_waived=True, supplier_rights_verified=False,
                        start='2016-01-04', end='2026-10-14', seed_sha256=c.SEED_SHA,
                        initial_checkpoint_sha256=c.INITIAL_SHA)
        comment = dict(id=1, issue_url=f'https://api.github.com/repos/{c.REPO}/issues/448',
                       author_association='OWNER', user=dict(type='User', id=123),
                       created_at=now.isoformat(), updated_at=now.isoformat(),
                       body='A1_SIP_CAPTURE_DIRECTIVE ' + json.dumps(record)
                       + '\nA1_SIP_CAPTURE_APPROVAL ' + json.dumps(approval))
        return bindings, reference, record, comment, now + timedelta(seconds=7100)

    def test_direct_request_is_distinct_from_supplier_certification(self):
        bindings, reference, record, comment, deadline = self.fixture()
        with patch.object(c, 'gh_json', return_value=comment):
            original = c.verify_account_permission(reference, 'c' * 64, bindings, valid_through=deadline)
            self.assertRegex(original, r'^[a-f0-9]{64}$')
        for key, value in [('supplier_rights_verified', True), ('private_noncommercial', False),
                           ('evidence_procedure_waived', False), ('personal_historical_capture_requested', 1),
                           ('plan', 'OTHER_ACCOUNT'), ('mode', 'ACCOUNT_RIGHTS_CERTIFIED'),
                           ('approval_reference', 'https://example.invalid/'), ('auth_sha256', 'd' * 64),
                           ('bindings', dict(owner_sha256='d' * 64, credential_binding='b' * 64))]:
            changed = dict(record); changed[key] = value
            with self.subTest(key=key), patch.object(c, 'gh_json', return_value=dict(comment, body='A1_SIP_CAPTURE_DIRECTIVE ' + json.dumps(changed))), self.assertRaises(c.Refused):
                c.verify_account_permission(reference, 'c' * 64, bindings, valid_through=deadline)
        for body in [comment['body'] + '\n' + comment['body'],
                     comment['body'] + '\nA1_SIP_ACCOUNT_PERMISSION {}',
                     'A1_SIP_CAPTURE_DIRECTIVE ' + json.dumps(dict(record, private_retention_allowed=True))]:
            with self.subTest(body=body[:30]), patch.object(c, 'gh_json', return_value=dict(comment, body=body)), self.assertRaises(c.Refused):
                c.verify_account_permission(reference, 'c' * 64, bindings, valid_through=deadline)

    def test_direct_request_keeps_identity_deadline_and_comment_drift(self):
        bindings, reference, record, comment, deadline = self.fixture()
        with patch.object(c, 'gh_json', return_value=comment):
            original = c.verify_account_permission(reference, 'c' * 64, bindings, valid_through=deadline)
        for changed in [dict(comment, user=dict(type='Bot', id=123)),
                        dict(comment, author_association='NONE'), dict(comment, id=2),
                        dict(comment, issue_url=f'https://api.github.com/repos/{c.REPO}/issues/590')]:
            with self.subTest(changed=changed.get('author_association')), patch.object(c, 'gh_json', return_value=changed), self.assertRaises(c.Refused):
                c.verify_account_permission(reference, 'c' * 64, bindings, valid_through=deadline)
        for seconds in [30, -1]:
            changed = dict(record, expires_at_utc=(c.utc() + timedelta(seconds=seconds)).isoformat())
            body = 'A1_SIP_CAPTURE_DIRECTIVE ' + json.dumps(changed) + '\n' + comment['body'].splitlines()[1]
            with patch.object(c, 'gh_json', return_value=dict(comment, body=body)), self.assertRaisesRegex(c.Refused, '^CAMPAIGN_ACCOUNT_EXPIRED$'):
                c.verify_account_permission(reference, 'c' * 64, bindings, valid_through=deadline)
        for changed in [dict(comment, body=comment['body'] + '\nChanged execution context'),
                        dict(comment, user=dict(type='User', id=124))]:
            with patch.object(c, 'gh_json', return_value=changed):
                self.assertNotEqual(c.verify_account_permission(reference, 'c' * 64, bindings, valid_through=deadline), original)
        exact = dict(record, expires_at_utc=deadline.isoformat())
        body = 'A1_SIP_CAPTURE_DIRECTIVE ' + json.dumps(exact) + '\n' + comment['body'].splitlines()[1]
        with patch.object(c, 'gh_json', return_value=dict(comment, body=body)):
            self.assertRegex(c.verify_account_permission(reference, 'c' * 64, bindings, valid_through=deadline), r'^[a-f0-9]{64}$')

    def test_cited_approval_is_fetched_checked_and_hash_bound(self):
        bindings, reference, record, comment, deadline = self.fixture()
        record['approval_reference'] = reference[:-1] + '2'
        directive = dict(comment, body='A1_SIP_CAPTURE_DIRECTIVE ' + json.dumps(record))
        approval = dict(comment, id=2, body=comment['body'].splitlines()[1])
        def verify(candidate):
            def fetch(endpoint):
                return directive if endpoint.endswith('/1') else candidate
            with patch.object(c, 'gh_json', side_effect=fetch) as get:
                result = c.verify_account_permission(reference, 'c' * 64, bindings, valid_through=deadline)
                self.assertEqual(get.call_count, 2)
                return result
        original = verify(approval)
        missing = c.Refused('CAMPAIGN_GITHUB_READ')
        with patch.object(c, 'gh_json', side_effect=[directive, missing]), self.assertRaisesRegex(c.Refused, '^CAMPAIGN_GITHUB_READ$'):
            c.verify_account_permission(reference, 'c' * 64, bindings, valid_through=deadline)
        for changed in [dict(approval, body='unrelated owner comment'),
                        dict(approval, author_association='COLLABORATOR'),
                        dict(approval, user=dict(type='Bot', id=123)), dict(approval, id=99),
                        dict(approval, created_at=(c.utc()+timedelta(minutes=1)).isoformat()),
                        dict(approval, body=approval['body']+'\n'+approval['body'])]:
            with self.subTest(changed=changed.get('id')), self.assertRaises(c.Refused):
                verify(changed)
        scope = json.loads(approval['body'].split(' ',1)[1])
        for key,value in [('task_key','OTHER'),('plan','OTHER'),('supplier_rights_verified',True),
                          ('private_noncommercial',False),('evidence_procedure_waived',1),
                          ('seed_sha256','f'*64),('initial_checkpoint_sha256','f'*64),
                          ('start','2000-01-01'),('end','2027-01-01')]:
            bad=dict(scope);bad[key]=value
            with self.subTest(key=key), self.assertRaises(c.Refused):
                verify(dict(approval, body='A1_SIP_CAPTURE_APPROVAL '+json.dumps(bad)))
        self.assertNotEqual(verify(dict(approval, body=approval['body']+'\nEdited owner context')), original)
        self.assertNotEqual(verify(dict(approval, user=dict(type='User',id=124))), original)

    def test_approval_last_update_cannot_postdate_directive(self):
        bindings, reference, record, comment, deadline = self.fixture()
        created = c.utc() - timedelta(minutes=2)
        comment = dict(comment, created_at=created.isoformat(), updated_at=created.isoformat())
        with patch.object(c, 'gh_json', return_value=comment):
            self.assertRegex(c.verify_account_permission(reference, 'c'*64, bindings, valid_through=deadline), r'^[a-f0-9]{64}$')
        for updated in [(created+timedelta(seconds=1)).isoformat(),
                        (created-timedelta(seconds=1)).isoformat(), None]:
            with self.subTest(updated=updated), patch.object(c, 'gh_json', return_value=dict(comment, updated_at=updated)), self.assertRaises(c.Refused):
                c.verify_account_permission(reference, 'c'*64, bindings, valid_through=deadline)



class LocalRejectRecoveryTests(unittest.TestCase):
    """Synthetic local-reject lineage; no original vendor or private auth bytes."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="a1-local-reject-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "journal"
        self.old = auth()
        self.old.update(account_permission_reference=None, owner_permission_id=None, credential_binding=None)
        self.old["code_pins"] = {p: c.digest((c.ROOT / p).read_bytes().replace(b"\r\n", b"\n")) for p in c.PINS}
        self.new = copy.deepcopy(self.old)
        self.new.update(expected_master="2"*40, workflow_run_floor=2)
        self.old_path, self.snapshot, self.receipt = (self.root / p for p in ("old-auth.json", "old-progress.json", "recovery-receipt.json"))
        self.old_path.write_bytes(c.encoded(self.old))
        self.nonce = c.PREFIX + "a"*24
        journal = c.WorkJournal(self.state, c.validate_authorization(self.old))
        journal.append("RESERVED", nonce=self.nonce, remaining=dict(c.LIMITS),
                       active_seconds_remaining=28800, parent_checkpoint_sha256=c.INITIAL_SHA)
        journal.close()
        self.original = (self.state / "000001.json").read_bytes()
        progress = c.encoded(dict(status="BLOCKED", charged_usage={k: 0 for k in c.LIMITS},
                                 first_workflow_created_utc=None, total_processed=16))
        self.snapshot.write_bytes(progress)
        (self.state / "progress").write_bytes(progress)
        constants = dict(c.LOCAL_REJECT, auth=c.validate_authorization(self.old),
                         reservation=c.digest(self.original), progress=c.digest(progress))
        patcher = patch.object(c, "LOCAL_REJECT", constants)
        patcher.start()
        self.addCleanup(patcher.stop)
        scope = {k: v for k, v in self.old.items() if k not in {"expected_master", "code_pins", "workflow_run_floor"}}
        self.record = dict(schema="a1-sip-local-reject-recovery-v1", task_key=c.TASK,
                           prior_auth_sha256=constants["auth"], auth_sha256=c.validate_authorization(self.new),
                           prior_reservation_sha256=constants["reservation"], prior_progress_sha256=constants["progress"],
                           prior_nonce=self.nonce, expected_master=self.new["expected_master"],
                           scope_sha256=c.digest(c.encoded(scope)), code_pins_sha256=c.digest(c.encoded(self.new["code_pins"])),
                           cli_version="2.91.0", cli_binary_sha256=constants["cli_binary"],
                           local_reject_evidence_sha256=constants["cli_evidence"], independent_qa_sha256=constants["independent_qa"],
                           dispatch_post_sent=False, canonical_runs_before_recovery=0, actual_usage={k: 0 for k in c.LIMITS},
                           expires_at_utc=(c.utc()+timedelta(days=1)).isoformat())
        created = c.utc().isoformat()
        self.comment = dict(id=17, issue_url=f"https://api.github.com/repos/{c.REPO}/issues/448",
                            author_association="OWNER", user=dict(type="User", id=123),
                            created_at=created, updated_at=created)
        self.bundle_path = self.root / "bundle.json"
        self.bundle_path.write_bytes(c.encoded(dict(prior_authorization=str(self.old_path),
            prior_progress_snapshot=str(self.snapshot), receipt_path=str(self.receipt),
            proof_reference="https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-17")))

    def proof(self, record=None, comment=None, new=None):
        data = dict(self.comment if comment is None else comment)
        data["body"] = "A1_SIP_LOCAL_REJECT_RECOVERY " + json.dumps(self.record if record is None else record)
        with patch.object(c, "gh_json", return_value=data):
            return c.local_reject_recovery(self.bundle_path, self.new if new is None else new, self.state)

    def deployed(self, route):
        if route.endswith("/branches/master"):
            return dict(commit=dict(sha=self.new["expected_master"]))
        for p in c.PINS:
            if "/contents/"+p+"?ref=" in route:
                import base64
                return dict(encoding="base64", content=base64.b64encode((c.ROOT / p).read_bytes().replace(b"\r\n", b"\n")).decode())
        self.fail("Unexpected GitHub route")

    def apply(self, journal, recovery, runs=None):
        with patch.object(c, "campaign_runs", return_value=[] if runs is None else runs), patch.object(c, "gh_json", side_effect=self.deployed):
            c.apply_local_reject_recovery(journal, self.new, recovery)

    def test_original_prefix_and_scope_are_conserved_without_fake_settlement(self):
        recovery = self.proof()
        old_auth, old_progress = self.old_path.read_bytes(), self.snapshot.read_bytes()
        journal = c.WorkJournal(self.state, c.validate_authorization(self.new), recovery)
        try:
            with self.assertRaises(c.Refused):
                journal.reconcile([])
            self.apply(journal, recovery)
            journal.reconcile([])
            self.assertEqual([v["kind"] for v in journal.entries], ["RESERVED", "LOCAL_REJECT_RECOVERED"])
            self.assertEqual((self.state/"000001.json").read_bytes(), self.original)
            self.assertEqual(self.old_path.read_bytes(), old_auth)
            self.assertEqual(self.snapshot.read_bytes(), old_progress)
            self.assertEqual((self.state/"progress").read_bytes(), old_progress)
            receipt = c.bounded_json(self.receipt)
            self.assertEqual(receipt["actual_usage"], {k:0 for k in c.LIMITS})
            self.assertEqual(receipt["prior_auth_sha256"], c.validate_authorization(self.old))
            self.assertEqual(receipt["auth_sha256"], c.validate_authorization(self.new))
            self.assertEqual(receipt["code_pins_sha256"], c.digest(c.encoded(self.new["code_pins"])))
        finally:
            journal.close()

    def test_reopen_is_idempotent_and_preserves_receipt_and_chain(self):
        recovery = self.proof()
        journal = c.WorkJournal(self.state, c.validate_authorization(self.new), recovery)
        self.apply(journal, recovery)
        journal.close()
        event, receipt = (self.state/"000002.json").read_bytes(), self.receipt.read_bytes()
        journal = c.WorkJournal(self.state, c.validate_authorization(self.new), self.proof())
        try:
            self.apply(journal, recovery)
            self.assertEqual(len(journal.entries), 2)
            self.assertEqual((self.state/"000002.json").read_bytes(), event)
            self.assertEqual(self.receipt.read_bytes(), receipt)
        finally:
            journal.close()

    def test_receipt_creation_crash_can_finish_without_duplicate_closure(self):
        recovery = self.proof()
        journal = c.WorkJournal(self.state, c.validate_authorization(self.new), recovery)
        original_open = Path.open
        receipt_path = self.receipt
        def fail_receipt(path, *args, **kwargs):
            if path == receipt_path:
                raise OSError("SYNTHETIC_BEFORE_RECEIPT_CREATE")
            return original_open(path, *args, **kwargs)
        try:
            with patch.object(Path, "open", fail_receipt), self.assertRaises(OSError):
                self.apply(journal, recovery)
            self.assertEqual(len(journal.entries), 2)
        finally:
            journal.close()
        journal = c.WorkJournal(self.state, c.validate_authorization(self.new), self.proof())
        try:
            self.apply(journal, recovery)
            self.assertEqual(len(journal.entries), 2)
            self.assertTrue(self.receipt.exists())
        finally:
            journal.close()

    def test_missing_or_drifted_proof_cannot_relabel_old_auth(self):
        with self.assertRaises(c.Refused):
            c.WorkJournal(self.state, c.validate_authorization(self.new))
        recovery = self.proof()
        journal = c.WorkJournal(self.state, c.validate_authorization(self.new), recovery)
        self.apply(journal, recovery)
        journal.close()
        data = dict(self.comment)
        data["body"] = "A1_SIP_LOCAL_REJECT_RECOVERY "+json.dumps(self.record)+"\nEDITED"
        with patch.object(c, "gh_json", return_value=data):
            changed = c.local_reject_recovery(self.bundle_path, self.new, self.state)
        with self.assertRaises(c.Refused):
            c.WorkJournal(self.state, c.validate_authorization(self.new), changed)
        self.assertFalse((self.state/"writer.lock").exists())

    def test_fabricated_zero_or_unproven_request_is_rejected(self):
        mutations = [dict(dispatch_post_sent=True), dict(canonical_runs_before_recovery=1),
                     dict(prior_reservation_sha256="0"*64), dict(independent_qa_sha256="0"*64),
                     dict(cli_version="unknown"), dict(actual_usage={k:False for k in c.LIMITS})]
        for delta in mutations:
            with self.subTest(delta=delta), self.assertRaises(c.Refused):
                self.proof(dict(self.record, **delta))
        for key in ("created_at", "updated_at"):
            with self.subTest(clock=key), self.assertRaises(c.Refused):
                self.proof(comment=dict(self.comment, **{key:None}))
        with self.assertRaises(c.Refused):
            self.proof(dict(self.record, expires_at_utc=None))
        with self.assertRaises(c.Refused):
            self.proof(comment=dict(self.comment, author_association="COLLABORATOR"))
        self.assertEqual((self.state/"000001.json").read_bytes(), self.original)
        self.assertFalse((self.state/"000002.json").exists())

    def test_scope_and_bound_snapshot_cannot_change(self):
        for key, value in [("private_data_folder_id","changed-folder-123"),
                           ("approval_reference","NEW_SCOPE"), ("expected_master", self.old["expected_master"]),
                           ("workflow_run_floor",0)]:
            changed = copy.deepcopy(self.new);changed[key]=value
            with self.subTest(key=key), self.assertRaises(c.Refused):
                self.proof(new=changed)
        self.snapshot.write_bytes(b"changed")
        with self.assertRaises(c.Refused):
            self.proof()
        self.assertEqual((self.state/"000001.json").read_bytes(), self.original)

    def test_late_original_run_fails_before_closure_or_new_dispatch(self):
        recovery = self.proof()
        journal = c.WorkJournal(self.state, c.validate_authorization(self.new), recovery)
        try:
            with self.assertRaises(c.Refused):
                self.apply(journal, recovery, runs=[dict(display_title="a1-sip "+self.nonce)])
            self.assertEqual(len(journal.entries),1)
            self.apply(journal,recovery)
            with self.assertRaises(c.Refused):
                journal.reconcile([dict(display_title="a1-sip "+self.nonce)])
        finally:
            journal.close()

    def observed(self):
        return dict(runs=[], receipts=[], used={k:0 for k in c.LIMITS}, remaining=dict(c.LIMITS),
                    examined=16, parent_sha=c.INITIAL_SHA, active_seconds=0, first=None, bindings=None)

    def host_fixture(self):
        recovery=self.proof()
        journal=c.WorkJournal(self.state,c.validate_authorization(self.new),recovery)
        self.apply(journal,recovery);journal.close()
        path=self.root/"new-auth.json";path.write_bytes(c.encoded(self.new))
        return path,recovery

    def test_original_authorization_raw_bytes_are_immutable(self):
        self.old_path.write_text(json.dumps(self.old,indent=2))
        with self.assertRaises(c.Refused):
            self.proof()
        self.assertFalse((self.state/"000002.json").exists())

    def test_receipt_namespace_and_existing_input_collisions_fail_before_closure(self):
        original=self.bundle_path.read_bytes();bundle=json.loads(original)
        for target in [self.state/"000003.json",self.old_path,self.snapshot,self.bundle_path]:
            with self.subTest(target=target):
                self.bundle_path.write_bytes(c.encoded(dict(bundle,receipt_path=str(target))))
                with self.assertRaises(c.Refused):
                    self.proof()
                self.assertFalse((self.state/"000002.json").exists())
        self.bundle_path.write_bytes(original)
        self.receipt.write_bytes(b"existing unrelated file")
        recovery=self.proof();journal=c.WorkJournal(self.state,c.validate_authorization(self.new),recovery)
        try:
            with self.assertRaises(c.Refused):self.apply(journal,recovery)
            self.assertEqual(len(journal.entries),1)
        finally:journal.close()

    def test_closed_local_reservation_is_not_reported_as_unsettled(self):
        path,recovery=self.host_fixture()
        with patch.object(c,"local_reject_recovery",return_value=recovery), \
                patch.object(c,"history",return_value=self.observed()), \
                patch.object(c,"gh_json",return_value=dict(commit=dict(sha="0"*40))),self.assertRaises(c.Refused):
            c.host(path,self.state,predispatch_recovery=self.bundle_path)
        self.assertIsNone(c.bounded_json(self.state/"progress")["unsettled_reservation"])
        self.assertEqual((self.state/"000001.json").read_bytes(),self.original)

    def test_unrelated_network_recovery_id_cannot_annotate_first_dispatch(self):
        path,recovery=self.host_fixture();calls=[]
        with patch.object(c,"local_reject_recovery",return_value=recovery), \
                patch.object(c,"history",return_value=self.observed()), \
                patch.object(c,"gh_json",side_effect=self.deployed), \
                patch.object(c.subprocess,"run",side_effect=lambda *a,**k:calls.append(a)),self.assertRaises(c.Refused):
            c.host(path,self.state,recovery_run=999,predispatch_recovery=self.bundle_path)
        self.assertEqual(calls,[])
        self.assertFalse((self.state/"000003.json").exists())

    def test_bound_latest_network_failure_can_reuse_persisted_bundle(self):
        path,recovery=self.host_fixture()
        observed=self.observed()
        observed.update(runs=[dict(id=999,display_title="a1-sip "+c.PREFIX+"b"*24)],
                        receipts=[dict(status="BLOCKED",reason="NETWORK",new_states={},rows_verified=0,
                                       confirmed_storage_bytes=0,observed_google_body_bytes=0)])
        class DispatchReached(BaseException):pass
        def cli(command,**kwargs):
            self.assertEqual(json.loads(json.loads(kwargs["input"])["campaign_control"])["recovery_run"],999)
            raise DispatchReached()
        with patch.object(c,"local_reject_recovery",return_value=recovery), \
                patch.object(c,"history",return_value=observed),patch.object(c,"gh_json",side_effect=self.deployed), \
                patch.object(c.WorkJournal,"reconcile"),patch.object(c,"campaign_runs",return_value=observed["runs"]), \
                patch.object(c.subprocess,"run",side_effect=cli),self.assertRaises(DispatchReached):
            c.host(path,self.state,recovery_run=999,predispatch_recovery=self.bundle_path)

    def test_delayed_original_during_poll_or_before_settlement_blocks_watch_or_settle(self):
        path,recovery=self.host_fixture()
        observed=self.observed();closed=dict(display_title="a1-sip "+self.nonce)
        for phase in ("predispatch","poll","settlement"):
            with self.subTest(phase=phase):
                # Separate fixture journal; original fixture stays unchanged.
                state=self.root/("race-"+phase);state.mkdir()
                for entry in ("000001.json","000002.json"):
                    (state/entry).write_bytes((self.state/entry).read_bytes())
                calls=[];run=dict(id=987,display_title="",status="completed")
                def cli(command,**kwargs):
                    calls.append(command)
                    if command[1:3]==["workflow","run"]:
                        run["display_title"]="a1-sip "+json.loads(kwargs["input"])["campaign_nonce"]
                    return type("Result",(),{"returncode":0})()
                snapshots=([closed],) if phase=="predispatch" else ([[],[closed,run]] if phase=="poll" else [[],[run],[closed,run]])
                with patch.object(c,"local_reject_recovery",return_value=recovery), \
                        patch.object(c,"history",return_value=observed),patch.object(c,"gh_json",side_effect=self.deployed), \
                        patch.object(c,"campaign_runs",side_effect=snapshots), \
                        patch.object(c.subprocess,"run",side_effect=cli),patch.object(c,"settle_run") as settle, \
                        self.assertRaisesRegex(c.Refused,"CAMPAIGN_LOCAL_REJECT_REMOTE"):
                    c.host(path,state,predispatch_recovery=self.bundle_path)
                settle.assert_not_called()
                self.assertEqual(sum(cmd[1:3]==["run","watch"] for cmd in calls),1 if phase=="settlement" else 0)
                self.assertEqual((state/"000001.json").read_bytes(),self.original)

    def test_receipt_read_race_on_pending_resume_or_postwatch_never_settles(self):
        path,recovery=self.host_fixture()
        for phase in ("resume","postwatch"):
            with self.subTest(phase=phase):
                state=self.root/("receipt-race-"+phase);state.mkdir()
                for entry in ("000001.json","000002.json"):
                    (state/entry).write_bytes((self.state/entry).read_bytes())
                nonce=c.PREFIX+"c"*24
                run=dict(id=987,display_title="a1-sip "+nonce,status="completed",created_at=c.utc().isoformat())
                receipt=dict(nonce=nonce,status="COMPLETE",usage={k:0 for k in c.LIMITS},
                             checkpoint_sha256=c.INITIAL_SHA,parent_checkpoint_sha256=c.INITIAL_SHA,
                             examined_after=16,new_states={},rows_verified=0,
                             confirmed_storage_bytes=0,observed_google_body_bytes=0)
                observed=self.observed()
                if phase=="resume":
                    journal=c.WorkJournal(state,c.validate_authorization(self.new),recovery)
                    journal.append("RESERVED",nonce=nonce,remaining=dict(c.LIMITS),
                                   active_seconds_remaining=28800,parent_checkpoint_sha256=c.INITIAL_SHA)
                    journal.append("RUN_ASSIGNED",nonce=nonce,run_id=987);journal.close()
                    observed.update(runs=[run],receipts=[receipt])
                closed=dict(display_title="a1-sip "+self.nonce)
                def cli(command,**kwargs):
                    if command[1:3]==["workflow","run"]:
                        run["display_title"]="a1-sip "+json.loads(kwargs["input"])["campaign_nonce"]
                        receipt["nonce"]=run["display_title"][7:]
                    return type("Result",(),{"returncode":0})()
                def api(route):
                    if route.endswith("/actions/runs/987"):return run
                    return self.deployed(route)
                snapshots=[[closed,run]] if phase=="resume" else [[],[run],[run],[closed,run]]
                with patch.object(c,"local_reject_recovery",return_value=recovery), \
                        patch.object(c,"history",side_effect=[observed,dict(observed,runs=[run],receipts=[receipt])]), \
                        patch.object(c,"job_seconds",return_value=1),patch.object(c,"gh_json",side_effect=api), \
                        patch.object(c,"campaign_runs",side_effect=snapshots),patch.object(c,"receipt_for_run",return_value=receipt), \
                        patch.object(c.subprocess,"run",side_effect=cli),self.assertRaisesRegex(c.Refused,"CAMPAIGN_LOCAL_REJECT_REMOTE"):
                    c.host(path,state,predispatch_recovery=self.bundle_path)
                kinds=[json.loads(p.read_bytes())["kind"] for p in state.glob("*.json")]
                self.assertNotIn("SETTLED",kinds)
                self.assertEqual((state/"000001.json").read_bytes(),self.original)

    def test_live_progress_cannot_be_the_immutable_snapshot(self):
        bundle=json.loads(self.bundle_path.read_bytes())
        self.bundle_path.write_bytes(c.encoded(dict(bundle,prior_progress_snapshot=str(self.state/"progress"))))
        with self.assertRaises(c.Refused):self.proof()
        self.assertFalse((self.state/"000002.json").exists())

    def test_original_appearing_during_deployed_pin_reads_prevents_closure(self):
        recovery=self.proof();journal=c.WorkJournal(self.state,c.validate_authorization(self.new),recovery)
        try:
            with patch.object(c,"campaign_runs",side_effect=[[],[dict(display_title="a1-sip "+self.nonce)]]), \
                    patch.object(c,"gh_json",side_effect=self.deployed),self.assertRaises(c.Refused):
                c.apply_local_reject_recovery(journal,self.new,recovery)
            self.assertEqual(len(journal.entries),1)
            self.assertFalse(self.receipt.exists())
        finally:journal.close()

    def test_expired_proof_cannot_create_closure_but_applied_closure_can_reopen(self):
        recovery=self.proof();journal=c.WorkJournal(self.state,c.validate_authorization(self.new),recovery)
        self.apply(journal,recovery);journal.close()
        original_event=(self.state/"000002.json").read_bytes();original_receipt=self.receipt.read_bytes()
        real_utc=c.utc;future=real_utc(self.record["expires_at_utc"])+timedelta(seconds=1)
        def later(value=None):return future if value is None else real_utc(value)
        with patch.object(c,"utc",side_effect=later):
            expired=self.proof()
            journal=c.WorkJournal(self.state,c.validate_authorization(self.new),expired)
            try:self.apply(journal,expired)
            finally:journal.close()
            fresh=self.root/"expired-fresh";fresh.mkdir()
            (fresh/"000001.json").write_bytes(self.original)
            (fresh/"progress").write_bytes(self.snapshot.read_bytes())
            journal=c.WorkJournal(fresh,c.validate_authorization(self.new),expired)
            try:
                with self.assertRaises(c.Refused):self.apply(journal,expired)
                self.assertEqual(len(journal.entries),1)
            finally:journal.close()
        self.assertEqual((self.state/"000002.json").read_bytes(),original_event)
        self.assertEqual(self.receipt.read_bytes(),original_receipt)

    def test_recovery_event_reserialization_cannot_change_anchored_bytes(self):
        recovery=self.proof();journal=c.WorkJournal(self.state,c.validate_authorization(self.new),recovery)
        self.apply(journal,recovery);journal.close()
        event=self.state/"000002.json";event.write_text(json.dumps(json.loads(event.read_bytes()),indent=2))
        with self.assertRaises(c.Refused):
            reopened=c.WorkJournal(self.state,c.validate_authorization(self.new),self.proof())
            reopened.close()
        self.assertFalse((self.state/"writer.lock").exists())

    def test_all_outer_cli_values_are_strings_nested_authority_unchanged(self):
        path = self.root / "new-auth.json";path.write_bytes(c.encoded(self.new))
        observed = dict(runs=[], receipts=[], used={k:0 for k in c.LIMITS}, remaining=dict(c.LIMITS),
                        examined=16, parent_sha=c.INITIAL_SHA, active_seconds=0, first=None, bindings=None)
        calls=[]
        class BoundaryReached(BaseException): pass
        def strict_cli(command, **kwargs):
            self.assertEqual(command[:3],["gh","workflow","run"])
            payload=json.loads(kwargs["input"])
            self.assertTrue(all(type(v) is str for v in payload.values()))
            self.assertEqual(json.loads(payload["campaign_control"])["authorization"],self.new)
            calls.append(payload)
            raise BoundaryReached()
        with patch.object(c,"history",return_value=observed), patch.object(c,"gh_json",side_effect=self.deployed), \
                patch.object(c.subprocess,"run",side_effect=strict_cli), self.assertRaises(BoundaryReached):
            c.host(path,self.root/"fresh-journal")
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]["max_new_symbols"],"32")
        self.assertEqual(calls[0]["private_research_authorized"],"true")

class BoundedContinuationTests(unittest.TestCase):
    """Synthetic spent ledger; neither real prices nor supplier attestations."""
    def setUp(self):
        self.local = LocalRejectRecoveryTests()
        self.local.setUp()
        self.addCleanup(self.local.doCleanups)
        self.prior = copy.deepcopy(self.local.new)
        self.recovery = self.local.proof()
        self.state, self.root = self.local.state, self.local.root
        journal = c.WorkJournal(self.state, c.validate_authorization(self.prior), self.recovery)
        self.local.apply(journal, self.recovery)
        first = (c.utc()-timedelta(seconds=1)).isoformat()
        self.runs, self.receipts = [], []
        used = {k:0 for k in c.LIMITS}
        before, parent = 16, c.INITIAL_SHA
        self.bindings = dict(owner_sha256=c.digest(b'fixture-owner'), credential_binding=c.digest(b'fixture-key\0fixture-secret'))
        for index in range(5):
            nonce = c.PREFIX + str(index+1)*24
            run = dict(id=index+1, display_title='a1-sip '+nonce, created_at=first,
                       head_sha=self.prior['expected_master'], head_branch='master',
                       status='completed', conclusion='success', run_attempt=1)
            usage = dict(provider_gets=0 if index==0 else 22, drive_requests=4 if index==0 else 260+64*(index-1),
                         drive_bytes=1000+index*100000, storage_bytes=0 if index==0 else 1000)
            after = before + (0 if index==0 else 32)
            checkpoint = parent if index==0 else str(index+2)*64
            receipt = dict(schema='a1-sip-campaign-meter-v1', task_key=c.TASK,
                           auth_sha256=c.validate_authorization(self.prior), source_sha=self.prior['expected_master'],
                           nonce=nonce, run_id=index+1, run_attempt=1, finalized=True,
                           status='COMPLETE', preflight_only=index==0, bindings=self.bindings,
                           parent_checkpoint_sha256=parent, checkpoint_sha256=checkpoint,
                           examined_before=before, examined_after=after, rows_verified=0 if index==0 else 64,
                           new_states=dict(VALID_COLLECTED=0 if index==0 else 32,VERIFIED_NO_DATA=0,QUARANTINED=0),
                           allowance={k:c.LIMITS[k]-used[k] for k in c.LIMITS}, usage=usage,
                           account_permission_reference_sha256=None if index==0 else 'c'*64,
                           account_permission_record_sha256=None if index==0 else 'd'*64,
                           confirmed_storage_bytes=usage['storage_bytes'], observed_google_body_bytes=0,
                           source_admission=False,pit_verified=False,economic_authority=False,transfer_definition=c.METRIC)
            journal.append('RESERVED',nonce=nonce,remaining=receipt['allowance'],active_seconds_remaining=28800,
                           parent_checkpoint_sha256=parent)
            journal.append('RUN_ASSIGNED',nonce=nonce,run_id=index+1)
            journal.append('SETTLED',nonce=nonce,run_id=index+1,usage=usage,
                           checkpoint=dict(file_id='fixture-checkpoint-'+str(index),sha256=checkpoint,bytes=1375),
                           receipt=receipt,receipt_sha256=c.digest(c.encoded(receipt)),examined_after=after)
            self.runs.append(run);self.receipts.append(receipt)
            used={k:used[k]+usage[k] for k in used}
            before,parent=after,checkpoint
        self.prefix = {p.name:p.read_bytes() for p in self.state.glob('*.json')}
        event_hash = journal.parent
        journal.close()
        progress=c.encoded(dict(status='BLOCKED',new_processed=128,charged_usage=used,active_seconds=872,
                                first_workflow_created_utc=first,last_checkpoint_sha256=parent))
        (self.state/'progress').write_bytes(progress)
        constants=dict(c.CONTINUATION,auth=c.validate_authorization(self.prior),master=self.prior['expected_master'],
                       checkpoint=parent,event=event_hash,progress=c.digest(progress),runs=[r['id'] for r in self.runs],
                       receipts=[c.digest(c.encoded(r)) for r in self.receipts],used=used,bindings=self.bindings,
                       permission_record='d'*64,first=first)
        patcher=patch.object(c,'CONTINUATION',constants);patcher.start();self.addCleanup(patcher.stop)
        self.new=copy.deepcopy(self.prior)
        self.reference='https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-27'
        self.new.update(schema='r1000-sip-campaign-authorization-v2',limits=dict(c.CONTINUED_LIMITS),
                        expected_master='3'*40,continuation=dict(prior_authorization=self.prior,proof_reference=self.reference))
        self.record=dict(schema='a1-sip-bounded-continuation-v1',task_key=c.TASK,
                         prior_auth_sha256=constants['auth'],auth_sha256=c.validate_authorization(self.new),
                         prior_journal_event_sha256=constants['event'],prior_progress_sha256=constants['progress'],
                         checkpoint_sha256=parent,prior_run_ids=constants['runs'],prior_usage=used,
                         prior_active_seconds=872,prior_examined=144,first_canonical_utc=first,
                         expires_at_utc=(c.utc(first)+timedelta(hours=48)).isoformat(),request_sha256=constants['request'],
                         limits=dict(c.CONTINUED_LIMITS),active_seconds_limit=43200,dispatch_limit=40,
                         preserve_seed_order=True,account_rotation=False,expected_master=self.new['expected_master'],
                         code_pins_sha256=c.digest(c.encoded(self.new['code_pins'])))
        now=c.utc().isoformat()
        self.comment=dict(id=27,issue_url=f'https://api.github.com/repos/{c.REPO}/issues/448',author_association='OWNER',
                          user=dict(type='User',id=123),created_at=now,updated_at=now)

    def proof(self, record=None, changed=None):
        comment=dict(self.comment,body='A1_SIP_BOUNDED_CONTINUATION '+json.dumps(self.record if record is None else record))
        if changed:comment.update(changed)
        evidence=dict(body_sha256=c.digest(comment['body'].encode()),record=dict(expires_at_utc=self.record['expires_at_utc']))
        with patch.object(c,'gh_json',return_value=comment),patch.object(c,'account_permission_evidence',return_value=evidence):
            return c.continuation_proof(self.new)

    def observed(self, runs=None, receipts=None, durations=None):
        proof=self.proof()
        with patch.object(c,'continuation_proof',return_value=proof), \
             patch.object(c,'campaign_runs',return_value=self.runs if runs is None else runs), \
             patch.object(c,'receipt_for_run',side_effect=self.receipts if receipts is None else receipts) as read, \
             patch.object(c,'job_seconds',side_effect=[27,159,215,206,265] if durations is None else durations):
            observed=c.history(self.new)
            self.receipt_calls=read.call_args_list
            return observed

    def test_spent_prefix_stays_old_and_all_remaining_allowances_are_cumulative(self):
        observed=self.observed()
        self.assertEqual(observed['active_seconds'],872)
        self.assertEqual(observed['active_limit'],43200)
        self.assertEqual(observed['examined'],144)
        self.assertEqual(observed['parent_sha'],c.CONTINUATION['checkpoint'])
        self.assertEqual(observed['first'],c.utc(c.CONTINUATION['first']))
        self.assertEqual(observed['remaining'],{k:c.CONTINUED_LIMITS[k]-c.CONTINUATION['used'][k] for k in c.LIMITS})
        self.assertTrue(all(call.args[1:]==(c.CONTINUATION['auth'],self.prior['expected_master']) for call in self.receipt_calls))
        self.assertEqual(len(observed['runs']),5)

    def test_no_nested_continuation_scope_account_seed_floor_or_cap_change(self):
        mutations=[dict(workflow_run_floor=self.prior['workflow_run_floor']+1),dict(seed_sha256='0'*64),dict(owner_permission_id='OTHER'),
                   dict(private_data_folder_id='another-private-folder'),dict(credential_binding='0'*64),
                   dict(limits=dict(c.CONTINUED_LIMITS,provider_gets=2001)),dict(limits=dict(c.LIMITS))]
        for change in mutations:
            with self.subTest(change=change),self.assertRaises(c.Refused):c.validate_authorization(dict(self.new,**change))
        prior=copy.deepcopy(self.prior);prior['continuation']={}
        with self.assertRaises(c.Refused):c.validate_authorization(dict(self.new,continuation=dict(self.new['continuation'],prior_authorization=prior)))
        with self.assertRaises(c.Refused):c.validate_authorization(dict(self.prior,limits=dict(c.CONTINUED_LIMITS)))

    def test_real_owner_typed_exact_budget_and_unchanged_scope_are_mandatory(self):
        for change in [dict(active_seconds_limit=43201),dict(prior_active_seconds=0),dict(prior_run_ids=[]),
                       dict(account_rotation=True),dict(preserve_seed_order=False),dict(dispatch_limit=41),
                       dict(prior_usage=dict(c.CONTINUATION['used'],provider_gets=False)),
                       dict(expires_at_utc=(c.utc()+timedelta(hours=49)).isoformat())]:
            with self.subTest(change=change),self.assertRaises(c.Refused):self.proof(dict(self.record,**change))
        for change in [dict(author_association='COLLABORATOR'),dict(user=dict(type='Bot',id=123)),
                       dict(updated_at=(c.utc()+timedelta(minutes=1)).isoformat())]:
            with self.subTest(change=change),self.assertRaises(c.Refused):self.proof(changed=change)

    def test_missing_reordered_or_changed_old_receipt_refuses_without_refund(self):
        for runs in [self.runs[1:],list(reversed(self.runs))]:
            with self.subTest(runs=runs),self.assertRaises(c.Refused):self.observed(runs=runs)
        receipts=copy.deepcopy(self.receipts);receipts[-1]['usage']['provider_gets']-=1
        with self.assertRaisesRegex(c.Refused,'CAMPAIGN_CONTINUATION_PREFIX'):self.observed(receipts=receipts)
        with self.assertRaisesRegex(c.Refused,'CAMPAIGN_CONTINUATION_PREFIX'):self.observed(durations=[27,159,215,206,264])

    def test_suffix_uses_new_auth_but_cannot_reset_cost_clock_or_permission(self):
        observed=self.observed();proof=observed['continuation']
        run=dict(self.runs[-1],id=6,created_at=c.utc().isoformat(),head_sha=self.new['expected_master'],
                 display_title='a1-sip '+c.PREFIX+'6'*24)
        receipt=dict(self.receipts[-1],parent_checkpoint_sha256=c.CONTINUATION['checkpoint'],
                     examined_before=144,examined_after=176,checkpoint_sha256='7'*64,
                     allowance=dict(observed['remaining']),usage={k:1 for k in c.LIMITS},
                     account_permission_reference_sha256=proof['permission_reference_sha256'],
                     account_permission_record_sha256=proof['permission_record_sha256'],
                     continuation_proof_sha256=proof['proof_sha256'])
        result=self.observed(runs=self.runs+[run],receipts=self.receipts+[receipt],durations=[27,159,215,206,265,300])
        self.assertEqual(result['active_seconds'],1172)
        self.assertEqual(result['used']['provider_gets'],c.CONTINUATION['used']['provider_gets']+1)
        self.assertEqual(self.receipt_calls[-1].args[1:],(c.validate_authorization(self.new),self.new['expected_master'],self.new['limits']))
        for change in [dict(allowance=dict(c.CONTINUED_LIMITS)),dict(account_permission_record_sha256='0'*64),
                       dict(account_permission_reference_sha256='0'*64),dict(bindings=dict(self.bindings,owner_sha256='0'*64)),
                       dict(continuation_proof_sha256='0'*64)]:
            with self.subTest(change=change),self.assertRaises(c.Refused):
                self.observed(runs=self.runs+[run],receipts=self.receipts+[dict(receipt,**change)],durations=[27,159,215,206,265,300])

    def test_bridge_is_single_immutable_event_preserving_all17_and_original_recovery_receipt(self):
        proof=self.proof();observed=self.observed()
        old_receipt=self.local.receipt.read_bytes()
        journal=c.WorkJournal(self.state,c.validate_authorization(self.new),self.recovery,proof)
        path=self.root/'continuation-receipt.json'
        def deployed(route):
            import base64
            if route.endswith('/branches/master'):return dict(commit=dict(sha=self.new['expected_master']))
            for name in c.PINS:
                if '/contents/'+name+'?ref=' in route:return dict(encoding='base64',content=base64.b64encode((c.ROOT/name).read_bytes().replace(b'\r\n',b'\n')).decode())
            self.fail('Unexpected offline route')
        try:
            c.apply_local_reject_recovery(journal,self.new,self.recovery)
            with patch.object(c,'gh_json',side_effect=deployed),patch.object(c,'history',return_value=observed), \
                 patch.object(c,'campaign_runs',return_value=self.runs):
                c.apply_continuation(journal,self.new,path,[])
            first=path.read_bytes();event=(self.state/'000018.json').read_bytes()
            c.apply_continuation(journal,self.new,path,[])
            self.assertEqual(len(journal.entries),18)
            self.assertEqual(journal.entries[-1]['kind'],'BUDGET_CONTINUED')
            self.assertEqual(path.read_bytes(),first)
            self.assertEqual((self.state/'000018.json').read_bytes(),event)
            self.assertEqual(self.local.receipt.read_bytes(),old_receipt)
            self.assertTrue(all((self.state/name).read_bytes()==raw for name,raw in self.prefix.items()))
        finally:journal.close()
        changed=dict(proof,proof_sha256='0'*64)
        with self.assertRaisesRegex(c.Refused,'CAMPAIGN_CONTINUATION_DRIFT'):
            c.WorkJournal(self.state,c.validate_authorization(self.new),self.recovery,changed)
        self.assertFalse((self.state/'writer.lock').exists())

    def test_bridge_rejects_receipt_alias_and_changed_progress_before_any_append(self):
        proof=self.proof()
        journal=c.WorkJournal(self.state,c.validate_authorization(self.new),self.recovery,proof)
        try:
            for path,inputs in [(self.state/'000018.json',[]),(self.root/'auth.json',[self.root/'auth.json'])]:
                with self.subTest(path=path),self.assertRaisesRegex(c.Refused,'CAMPAIGN_CONTINUATION_RECEIPT_PATH'):
                    c.apply_continuation(journal,self.new,path,inputs)
            (self.state/'progress').write_bytes(b'{}')
            with self.assertRaisesRegex(c.Refused,'CAMPAIGN_CONTINUATION_PREFIX'):
                c.apply_continuation(journal,self.new,self.root/'continuation.json',[])
            self.assertEqual(len(journal.entries),17)
        finally:journal.close()

    def test_old_meter_stays8gib_and_new_meter_obeys_only_passed_cumulative_allowance(self):
        with tempfile.TemporaryDirectory() as temp:
            remaining=dict(c.CONTINUED_LIMITS,drive_bytes=8*1024**3+1)
            with self.assertRaises(c.Refused):meter(temp,allowance=remaining)
            m=c.RuntimeMeter(remaining,Path(temp)/'continued.json',(c.utc()+timedelta(seconds=60)).isoformat(),
                             identity(),opener=Opener(),limits=c.CONTINUED_LIMITS)
            m.debit(dict(provider_gets=1))
            self.assertEqual(m.used['provider_gets'],1)
            with self.assertRaises(c.Refused):m.debit(dict(provider_gets=2000))
            self.assertEqual(m.used['provider_gets'],1)

    def test_worker_requires_frozen_portable_bridge_before_any_provider_or_drive(self):
        observed=self.observed()
        nonce=c.PREFIX+'6'*24
        env=dict(A1_PRIVATE_RESEARCH_AUTHORIZED='true',ALPACA_NONCOMMERCIAL_ACKNOWLEDGED='true',
                 GITHUB_RUN_ID='6',INPUT_CAMPAIGN_NONCE=nonce)
        base=dict(authorization=self.new,nonce=nonce,account_permission_reference=self.reference)
        for binding in [None,{},dict(observed['continuation'],proof_sha256='0'*64)]:
            control=dict(base)
            if binding is not None:control['continuation_binding']=binding
            with self.subTest(binding=binding),patch.dict(os.environ,env,clear=True), \
                 patch.object(c,'verify_worker_source'),patch.object(c,'history',return_value=observed), \
                 patch.object(c,'RuntimeMeter',side_effect=AssertionError('No I/O allowed')), \
                 self.assertRaisesRegex(c.Refused,'CAMPAIGN_CONTINUATION_DRIFT'):
                c.worker(SimpleNamespace(),control,self.root/'unused-meter.json')

    def deployed(self, route):
        import base64
        if route.endswith('/branches/master'):return dict(commit=dict(sha=self.new['expected_master']))
        for name in c.PINS:
            if '/contents/'+name+'?ref=' in route:return dict(encoding='base64',content=base64.b64encode((c.ROOT/name).read_bytes().replace(b'\r\n',b'\n')).decode())
        self.fail('Unexpected offline deployed route')

    def test_unknown_run_appearing_during_old_meter_reads_stops_before_bridge_append(self):
        proof=self.proof();observed=self.observed()
        journal=c.WorkJournal(self.state,c.validate_authorization(self.new),self.recovery,proof)
        unknown=dict(self.runs[-1],id=99,display_title='a1-sip '+c.PREFIX+'9'*24)
        try:
            with patch.object(c,'gh_json',side_effect=self.deployed),patch.object(c,'history',return_value=observed), \
                 patch.object(c,'campaign_runs',return_value=self.runs+[unknown]), \
                 self.assertRaisesRegex(c.Refused,'CAMPAIGN_CONTINUATION_PREFIX'):
                c.apply_continuation(journal,self.new,self.root/'late-bridge.json',[])
            self.assertEqual(len(journal.entries),17)
            self.assertFalse((self.root/'late-bridge.json').exists())
        finally:journal.close()

    def test_unknown_run_during_proof_query_stops_common_settlement(self):
        from unittest.mock import Mock
        proof=self.proof();remote=list(self.runs)
        receipt=dict(parent_checkpoint_sha256=c.CONTINUATION['checkpoint'],nonce=c.PREFIX+'6'*24,
                     usage={k:0 for k in c.LIMITS},examined_after=176,continuation_proof_sha256=proof['proof_sha256'])
        def reconcile(runs):
            if len(runs)!=5:raise c.Refused('CAMPAIGN_JOURNAL_REMOTE_CONFLICT')
        journal=SimpleNamespace(recovery=self.recovery,continuation=proof,reconcile=reconcile,append=Mock())
        def changing_proof(_):
            remote.append(dict(self.runs[-1],id=99))
            return proof
        with patch.object(c,'settled_parent',return_value=dict(sha256=c.CONTINUATION['checkpoint'])), \
             patch.object(c,'checkpoint_from_log',return_value=dict(sha256='7'*64)), \
             patch.object(c,'continuation_proof',side_effect=changing_proof), \
             patch.object(c,'campaign_runs',side_effect=lambda _:list(remote)), \
             self.assertRaisesRegex(c.Refused,'CAMPAIGN_JOURNAL_REMOTE_CONFLICT'):
            c.settle_run(journal,self.new,dict(id=6),receipt)
        journal.append.assert_not_called()

    def test_unknown_run_during_final_host_proof_query_stops_before_reservation_and_dispatch(self):
        proof=self.proof();observed=self.observed();remote=list(self.runs)
        path=self.root/'new-auth.json';path.write_bytes(c.encoded(self.new))
        proof_calls=[]
        def changing_proof(_):
            proof_calls.append(1)
            if len(proof_calls)==2:remote.append(dict(self.runs[-1],id=99,display_title='a1-sip '+c.PREFIX+'9'*24))
            return proof
        with patch.object(c,'continuation_proof',side_effect=changing_proof), \
             patch.object(c,'local_reject_recovery',return_value=self.recovery), \
             patch.object(c,'apply_local_reject_recovery'),patch.object(c,'apply_continuation'), \
             patch.object(c,'history',return_value=observed),patch.object(c,'gh_json',side_effect=self.deployed), \
             patch.object(c,'campaign_runs',side_effect=lambda _:list(remote)), \
             patch.object(c.subprocess,'run',side_effect=AssertionError('Dispatch forbidden')), \
             self.assertRaisesRegex(c.Refused,'CAMPAIGN_JOURNAL_REMOTE_CONFLICT'):
            c.host(path,self.state,permission_reference=self.reference,predispatch_recovery=self.local.bundle_path,
                   continuation_receipt=self.root/'host-receipt.json')
        self.assertFalse((self.state/'000018.json').exists())
        self.assertFalse((self.state/'writer.lock').exists())

    def test_documented_host_arguments_use_embedded_permission_at_actual_cli_boundary(self):
        proof=self.proof();observed=self.observed();calls=[]
        path=self.root/'documented-auth.json';path.write_bytes(c.encoded(self.new))
        class BoundaryReached(BaseException):pass
        def strict_cli(command,**kwargs):
            self.assertEqual(command[:3],['gh','workflow','run'])
            payload=json.loads(kwargs['input'])
            self.assertTrue(all(type(value) is str for value in payload.values()))
            control=json.loads(payload['campaign_control'])
            self.assertEqual(control['account_permission_reference'],self.reference)
            self.assertEqual(control['continuation_binding'],proof)
            self.assertFalse(control['preflight_only'])
            self.assertEqual(payload['resume_sha256'],c.CONTINUATION['checkpoint'])
            self.assertEqual(payload['max_new_symbols'],'32')
            self.assertLessEqual(len(payload['campaign_control']),16384)
            calls.append(payload)
            raise BoundaryReached()
        with patch.object(c,'continuation_proof',return_value=proof), \
             patch.object(c,'local_reject_recovery',return_value=self.recovery), \
             patch.object(c,'history',return_value=observed),patch.object(c,'gh_json',side_effect=self.deployed), \
             patch.object(c,'campaign_runs',return_value=self.runs), \
             patch.object(c.subprocess,'run',side_effect=strict_cli),self.assertRaises(BoundaryReached):
            c.host(path,self.state,predispatch_recovery=self.local.bundle_path,
                   continuation_receipt=self.root/'documented-continuation-receipt.json')
        self.assertEqual(len(calls),1)
        self.assertEqual(c.decode((self.state/'000018.json').read_bytes())['kind'],'BUDGET_CONTINUED')
        self.assertEqual(c.decode((self.state/'000019.json').read_bytes())['kind'],'RESERVED')
        self.assertFalse((self.state/'writer.lock').exists())

    def test_explicit_conflicting_permission_refuses_before_writer_or_bridge(self):
        proof=self.proof()
        path=self.root/'conflict-auth.json';path.write_bytes(c.encoded(self.new))
        with patch.object(c,'continuation_proof',return_value=proof), \
             patch.object(c,'WorkJournal',side_effect=AssertionError('Writer forbidden')), \
             self.assertRaisesRegex(c.Refused,'CAMPAIGN_CONTINUATION_PERMISSION'):
            c.host(path,self.state,permission_reference=self.reference+'0',predispatch_recovery=self.local.bundle_path,
                   continuation_receipt=self.root/'unused-conflict-receipt.json')
        self.assertFalse((self.state/'000018.json').exists())


class ExternalCohortTests(unittest.TestCase):
    """Synthetic discovery epochs, never actual input/owner/capture proof."""
    def setUp(self):
        self.old = BoundedContinuationTests(); self.old.setUp()
        self.addCleanup(self.old.doCleanups)
        self.prior, self.root, self.state = self.old.prior, self.old.root, self.old.state
        self.names = ['ZZZDISCA', 'ZZZDISCB', 'ZZZDISCC', 'ZZZDISCD']
        raw = ('ticker\n'+'\n'.join(self.names)+'\n').encode()
        self.reference = self.old.reference+'1'
        self.new = copy.deepcopy(self.prior)
        self.new.update(schema='r1000-sip-external-cohort-authorization-v1', limits=dict(c.CONTINUED_LIMITS),
            expected_master='3'*40, account_permission_reference=self.reference,
            owner_permission_id='fixture-owner',credential_binding=c.digest(b'fixture-key\0fixture-secret'),
            code_pins={p:c.digest((c.ROOT/p).read_bytes()) for p in c.PINS},
            external_cohort=dict(scope=dict(task_key='R1000-DISCOVERY-FIXTURE-20261017',
                namespace='fixture-discovery-169', input_sha256=c.digest(raw)), input_csv=raw.decode(),
                intake_manifest_sha256='e'*64, receipt_dedupe_sha256='f'*64, prior_authorization=self.prior,
                prior_epochs=[], proof_reference=self.reference))
        self.input = self.root/'cohort.csv'; self.input.write_bytes(raw)
        self.cohort_state = self.root/'external-cohort-fixture-discovery-169'

    def proof(self, auth_value=None, changed=None):
        a = auth_value or self.new
        comment = dict(self.old.comment, id=int(a['external_cohort']['proof_reference'].rsplit('-',1)[1]),
                       body='A1_SIP_EXTERNAL_COHORT_CONSENT '+json.dumps(c.external_proof_record(a)))
        if changed: comment.update(changed)
        with patch.object(c,'gh_json',return_value=comment): return c.external_proof(a)

    def observed(self, suffix=None, changed_receipts=None, proof=None):
        runs = self.old.runs+([suffix[0]] if suffix else [])
        values = self.old.receipts+([suffix[1]] if suffix else [])
        if changed_receipts is not None: values=changed_receipts
        with patch.object(c,'external_proof',return_value=proof or self.proof()), \
             patch.object(c,'campaign_runs',return_value=runs), \
             patch.object(c,'receipt_for_run',side_effect=values), \
             patch.object(c,'job_seconds',side_effect=[27,159,215,206,265]+([10] if suffix else [])):
            return c.external_history(self.new)

    def suffix(self):
        proof=self.proof(); h=c.validate_authorization(self.new)
        scope=self.new['external_cohort']['scope']; nonce=c.PREFIX+'6'*24
        run=dict(self.old.runs[-1], id=6,display_title='a1-sip '+nonce,head_sha=self.new['expected_master'],
                 created_at=c.utc().isoformat())
        value=dict(self.old.receipts[-1],auth_sha256=h,source_sha=self.new['expected_master'],nonce=nonce,run_id=6,
            parent_checkpoint_sha256=c.external_genesis(scope),checkpoint_sha256='9'*64,
            examined_before=0,examined_after=4,cohort_scope=scope,external_proof_sha256=proof['proof_sha256'],
            new_states=dict(VALID_COLLECTED=4,VERIFIED_NO_DATA=0,QUARANTINED=0),
            allowance={k:c.CONTINUED_LIMITS[k]-c.CONTINUATION['used'][k] for k in c.LIMITS},
            usage=dict(provider_gets=6,drive_requests=10,drive_bytes=100,storage_bytes=100),
            account_permission_reference_sha256=c.digest(self.reference.encode()),
            account_permission_record_sha256=proof['proof_sha256'],confirmed_storage_bytes=100)
        return run,value

    def test_local_zero_does_not_reset_global_cost_clock_or_dispatches(self):
        observed=self.observed()
        self.assertEqual(observed['examined'],0)
        self.assertEqual(observed['parent_sha'],c.external_genesis(self.new['external_cohort']['scope']))
        self.assertEqual(observed['used'],c.CONTINUATION['used'])
        self.assertEqual(observed['active_seconds'],872); self.assertEqual(len(observed['runs']),5)
        self.assertEqual(observed['first'],c.utc(c.CONTINUATION['first']))
        observed=self.observed(self.suffix())
        self.assertEqual(observed['examined'],4)
        self.assertEqual(observed['active_seconds'],882)
        self.assertEqual(observed['used']['provider_gets'],c.CONTINUATION['used']['provider_gets']+6)

    def test_scope_input_budget_account_and_prior_epoch_mutations_refuse(self):
        for mutate in (lambda a:a['limits'].update(provider_gets=2001),
                       lambda a:a.update(credential_binding='0'*64),
                       lambda a:a['external_cohort'].update(input_csv='ticker\nAAPL\n'),
                       lambda a:a['external_cohort'].update(prior_epochs=[self.new,self.new]),
                       lambda a:a['external_cohort']['scope'].update(namespace='../unsafe')):
            a=copy.deepcopy(self.new);mutate(a)
            with self.subTest(mutate=mutate),self.assertRaises(c.Refused):c.validate_authorization(a)
        a=copy.deepcopy(self.new);a['external_cohort']['input_csv']='ticker\nAAPL\n'
        a['external_cohort']['scope']['input_sha256']=c.digest(b'ticker\nAAPL\n')
        with self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOLLECTION'):c.validate_authorization(a)

    def test_unknown_source_namespace_allowance_or_proof_cannot_hide_spending(self):
        for key,value in [('cohort_scope',dict(self.new['external_cohort']['scope'],namespace='other-cohort')),
                          ('parent_checkpoint_sha256',c.INITIAL_SHA),('external_proof_sha256','0'*64),
                          ('source_sha','8'*40),('allowance',dict(c.CONTINUED_LIMITS))]:
            run,receipt=self.suffix();receipt[key]=value
            with self.subTest(key=key),self.assertRaises(c.Refused):self.observed((run,receipt))
        changed=copy.deepcopy(self.old.receipts);changed[0]['usage']['provider_gets']=1
        with self.assertRaisesRegex(c.Refused,'EXTERNAL_BUDGET_PREFIX'):self.observed(changed_receipts=changed)

    def test_second_frozen_epoch_retains_first_epoch_and_all_global_usage(self):
        previous=copy.deepcopy(self.new);a=copy.deepcopy(self.new)
        ex=a['external_cohort'];ex.update(input_csv='ticker\nZZZLATER\n',prior_epochs=[previous],
                                       proof_reference=self.reference+'2')
        ex['scope']=dict(ex['scope'],namespace='fixture-marketcap-500',input_sha256=c.digest(b'ticker\nZZZLATER\n'))
        a['account_permission_reference']=ex['proof_reference']
        c.validate_authorization(a)
        old_run,old_value=self.suffix();proof=self.proof(a)
        run=dict(old_run,id=7,display_title='a1-sip '+c.PREFIX+'7'*24)
        value=dict(old_value,run_id=7,nonce=c.PREFIX+'7'*24,auth_sha256=c.validate_authorization(a),
                   cohort_scope=ex['scope'],external_proof_sha256=proof['proof_sha256'],
                   account_permission_reference_sha256=c.digest(ex['proof_reference'].encode()),
                   account_permission_record_sha256=proof['proof_sha256'],examined_before=0,examined_after=1,
                   parent_checkpoint_sha256=c.external_genesis(ex['scope']),checkpoint_sha256='8'*64,
                   new_states=dict(VALID_COLLECTED=1,VERIFIED_NO_DATA=0,QUARANTINED=0),
                   allowance={k:old_value['allowance'][k]-old_value['usage'][k] for k in c.LIMITS})
        with patch.object(c,'external_proof',side_effect=[self.proof(previous),proof]), \
             patch.object(c,'campaign_runs',return_value=self.old.runs+[old_run,run]), \
             patch.object(c,'receipt_for_run',side_effect=self.old.receipts+[old_value,value]), \
             patch.object(c,'job_seconds',side_effect=[27,159,215,206,265,10,12]):
            observed=c.external_history(a)
        self.assertEqual(observed['examined'],1);self.assertEqual(observed['active_seconds'],894)
        self.assertEqual(observed['used']['provider_gets'],c.CONTINUATION['used']['provider_gets']+12)
        self.assertEqual(len(observed['runs']),7);self.assertEqual(len(observed['cohort_runs']),1)
        a['external_cohort']['input_csv']=previous['external_cohort']['input_csv']
        a['external_cohort']['scope']['input_sha256']=previous['external_cohort']['scope']['input_sha256']
        with self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOLLECTION'):c.validate_authorization(a)

    def test_closed_terminal_failure_can_be_accounted_but_never_recovered_as_auth_error(self):
        run,value=self.suffix();run['conclusion']='failure'
        value.update(status='BLOCKED',reason='AUTH')
        with self.assertRaisesRegex(c.Refused,'CAMPAIGN_EXTERNAL_FAILURE_STOP'):self.observed((run,value))
        with patch.object(c,'external_proof',return_value=self.proof()), \
             patch.object(c,'campaign_runs',return_value=self.old.runs+[run]), \
             patch.object(c,'receipt_for_run',side_effect=self.old.receipts+[value]), \
             patch.object(c,'job_seconds',side_effect=[27,159,215,206,265,10]):
            observed=c.external_history(self.new,allow_stopped=True)
        self.assertEqual(observed['used']['provider_gets'],c.CONTINUATION['used']['provider_gets']+6)
        with patch.object(c,'external_proof',return_value=self.proof()), \
             patch.object(c,'campaign_runs',return_value=self.old.runs+[run]), \
             patch.object(c,'receipt_for_run',side_effect=self.old.receipts+[value]), \
             patch.object(c,'job_seconds',side_effect=[27,159,215,206,265,10]),self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_NOT_AUTHORIZED'):
            c.external_history(self.new,recovery_run=run['id'],allow_stopped=True)

    def test_network_and_price_http_failure_do_not_authorize_another_external_attempt(self):
        for reason in ('NETWORK','HTTP_ERROR'):
            run,value=self.suffix();run['conclusion']='failure';value.update(status='BLOCKED',reason=reason)
            with self.subTest(reason=reason),self.assertRaisesRegex(c.Refused,'CAMPAIGN_EXTERNAL_FAILURE_STOP'):
                self.observed((run,value))
            with patch.object(c,'external_proof',return_value=self.proof()), \
                 patch.object(c,'campaign_runs',return_value=self.old.runs+[run]), \
                 patch.object(c,'receipt_for_run',side_effect=self.old.receipts+[value]), \
                 patch.object(c,'job_seconds',side_effect=[27,159,215,206,265,10]):
                observed=c.external_history(self.new,allow_stopped=True)
            self.assertEqual(observed['used']['provider_gets'],c.CONTINUATION['used']['provider_gets']+6)
            with patch.object(c,'WorkJournal',side_effect=AssertionError('No writer for unauthorized recovery')), \
                 self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_NOT_AUTHORIZED'):
                c.external_host(self.new,self.cohort_state,self.input,self.state,self.old.local.bundle_path,run['id'],1)

    def test_owner_consent_is_exact_input_and_no_supplier_certification(self):
        self.assertTrue(self.proof()['proof_sha256'])
        record=c.external_proof_record(self.new)
        self.assertFalse(record['supplier_rights_verified']);self.assertFalse(record['budget_reset'])
        for changed in [dict(author_association='CONTRIBUTOR'),dict(body='A1_SIP_EXTERNAL_COHORT_CONSENT {}'),
                        dict(updated_at=(c.utc()+timedelta(hours=49)).isoformat())]:
            with self.subTest(changed=changed),self.assertRaises(c.Refused):self.proof(changed=changed)

    def test_global_journal_pure_read_never_recreates_missing_receipt(self):
        recovery=self.old.recovery
        journal=c.WorkJournal(self.state,c.validate_authorization(self.prior),recovery=recovery)
        before={p.name:p.read_bytes() for p in self.state.iterdir() if p.name!='writer.lock'}
        try:
            c.verify_external_budget_journal(journal,self.new,recovery)
            receipt=Path(recovery['receipt_path']);original=receipt.read_bytes();receipt.unlink()
            with self.assertRaisesRegex(c.Refused,'CAMPAIGN_LOCAL_REJECT_RECEIPT'):
                c.verify_external_budget_journal(journal,self.new,recovery)
            self.assertFalse(receipt.exists());receipt.write_bytes(original)
            with self.assertRaises(c.Refused):c.WorkJournal(self.state,c.validate_authorization(self.prior),recovery=recovery)
        finally:journal.close()
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.state.iterdir()})

    def host_patches(self, observed, **kwargs):
        from contextlib import ExitStack
        stack=ExitStack()
        stack.enter_context(patch.object(c,'local_reject_recovery',return_value=self.old.recovery))
        stack.enter_context(patch.object(c,'external_proof',return_value=self.proof()))
        stack.enter_context(patch.object(c,'external_history',side_effect=observed if isinstance(observed,list) else None,
                                         return_value=observed))
        stack.enter_context(patch.object(c,'campaign_runs',return_value=(observed[0] if isinstance(observed,list) else observed)['runs']))
        stack.enter_context(patch.object(c,'external_deployed',return_value=None))
        return stack

    def test_second_namespace_lock_failure_releases_only_global_lock(self):
        with patch.object(c,'external_proof',return_value=self.proof()),patch.object(c,'campaign_runs',return_value=self.old.runs):
            family=c.external_family_registry(self.state,self.new,self.cohort_state)
        family.close()
        self.cohort_state.mkdir();lock=self.cohort_state/'writer.lock';lock.write_text('other-owner')
        with self.host_patches(self.observed()),self.assertRaisesRegex(c.Refused,'CAMPAIGN_WRITER_LOCK'):
            c.external_host(self.new,self.cohort_state,self.input,self.state,self.old.local.bundle_path,None,1)
        self.assertFalse((self.state/'writer.lock').exists());self.assertEqual(lock.read_text(),'other-owner')

    def test_copied_or_renamed_budget_tree_cannot_relocate_its_registry(self):
        import shutil
        proof=self.proof()
        with patch.object(c,'external_proof',return_value=proof),patch.object(c,'campaign_runs',return_value=self.old.runs):
            family=c.external_family_registry(self.state,self.new,self.cohort_state)
        directory=family.directory;family.close()
        before=(directory/'000001.json').read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            copied=Path(temporary)/'copied'
            shutil.copytree(self.root,copied)
            for target in (copied,Path(temporary)/'renamed'):
                if target != copied:
                    copied.rename(target)  # Isolated synthetic tree only.
                budget=target/self.state.relative_to(self.root)
                cohort=target/self.cohort_state.relative_to(self.root)
                with self.subTest(target=target.name),patch.object(c,'external_proof',return_value=proof), \
                     patch.object(c.subprocess,'run',side_effect=AssertionError('Relocation cannot dispatch')), \
                     self.assertRaisesRegex(c.Refused,'EXTERNAL_FAMILY_DRIFT'):
                    relocated=c.external_family_registry(budget,self.new,cohort)
                    relocated.close()
                registry=target/directory.relative_to(self.root)
                self.assertEqual((registry/'000001.json').read_bytes(),before)
                self.assertFalse((registry/'writer.lock').exists())
                self.assertFalse((registry/'000002.json').exists())
        with patch.object(c,'external_proof',return_value=proof):
            original=c.external_family_registry(self.state,self.new,self.cohort_state)
        original.close()
        self.assertEqual((directory/'000001.json').read_bytes(),before)

    def test_expired_new_namespace_never_appends_its_binding(self):
        original=c.utc;proof=self.proof()
        future=original(proof['expires_at_utc'])+timedelta(seconds=1)
        with self.host_patches(self.observed()), \
             patch.object(c,'utc',side_effect=lambda value=None:future if value is None else original(value)), \
             patch.object(c.subprocess,'run',side_effect=AssertionError('Dispatch after expiry')), \
             self.assertRaisesRegex(c.Refused,'EXTERNAL_BINDING_CLOCK'):
            c.external_host(self.new,self.cohort_state,self.input,self.state,self.old.local.bundle_path,None,1)
        self.assertFalse((self.cohort_state/'000001.json').exists())
        self.assertFalse((self.state/'writer.lock').exists());self.assertFalse((self.cohort_state/'writer.lock').exists())

    def test_completed_reserved_run_still_settles_and_accounts_after_expiry(self):
        proof=self.proof();scope=self.new['external_cohort']['scope'];run,value=self.suffix()
        observed=self.observed((run,value))
        with patch.object(c,'external_proof',return_value=proof),patch.object(c,'campaign_runs',return_value=self.old.runs):
            family=c.external_family_registry(self.state,self.new,self.cohort_state)
        family.append('RESERVED',nonce=value['nonce'],capture_auth_sha256=c.validate_authorization(self.new),scope=scope,
                      remaining=value['allowance'],parent_checkpoint_sha256=value['parent_checkpoint_sha256'])
        family.append('RUN_ASSIGNED',nonce=value['nonce'],run_id=run['id'],
                      capture_auth_sha256=c.validate_authorization(self.new),scope=scope)
        family.close()
        journal=c.WorkJournal(self.cohort_state,c.validate_authorization(self.new))
        journal.append('EXTERNAL_COHORT_BOUND',scope=scope,genesis_sha256=c.external_genesis(scope),**proof)
        journal.append('RESERVED',nonce=value['nonce'],remaining=value['allowance'],
                       parent_checkpoint_sha256=value['parent_checkpoint_sha256'])
        journal.append('RUN_ASSIGNED',nonce=value['nonce'],run_id=run['id']);journal.close()
        original=c.utc;future=original(proof['expires_at_utc'])+timedelta(seconds=1)
        with self.host_patches(observed),patch.object(c,'utc',side_effect=lambda value=None:future if value is None else original(value)), \
             patch.object(c,'checkpoint_from_log',return_value=dict(file_id='fixture-checkpoint-final',sha256=value['checkpoint_sha256'],bytes=100)), \
             patch.object(c.subprocess,'run',side_effect=AssertionError('No new dispatch after expiry')):
            result=c.external_host(self.new,self.cohort_state,self.input,self.state,self.old.local.bundle_path,None,1)
        self.assertEqual(result['status'],'COHORT_PROCESSED');self.assertEqual(result['examined'],4)
        self.assertEqual(result['charged_usage']['provider_gets'],c.CONTINUATION['used']['provider_gets']+6)
        self.assertEqual(c.bounded_json(self.cohort_state/'000004.json')['kind'],'SETTLED')
        self.assertFalse((self.state/'writer.lock').exists())

    def test_uncertain_invisible_post_blocks_another_namespace_without_refund(self):
        calls=[]
        def rejected(command,**kwargs):
            calls.append(json.loads(kwargs['input']))
            return SimpleNamespace(returncode=1)
        with self.host_patches(self.observed()),patch.object(c.subprocess,'run',side_effect=rejected), \
             self.assertRaisesRegex(c.Refused,'CAMPAIGN_DISPATCH_UNCERTAIN'):
            c.external_host(self.new,self.cohort_state,self.input,self.state,self.old.local.bundle_path,None,1)
        self.assertEqual(len(calls),1)
        original_global=list(self.root.glob('external-budget-*'))
        self.assertEqual(len(original_global),1)
        global_reserved=c.bounded_json(original_global[0]/'000002.json')
        self.assertEqual(global_reserved['remaining'],self.observed()['remaining'])
        self.assertEqual(c.bounded_json(self.cohort_state/'000002.json')['kind'],'RESERVED')
        # A separately consented first epoch cannot bypass an unobserved A.
        b=copy.deepcopy(self.new);b['external_cohort']['scope']['namespace']='fixture-another-cohort'
        frozen=self.proof(b)
        with self.host_patches(self.observed()),patch.object(c,'external_proof',return_value=frozen), \
             patch.object(c.subprocess,'run',side_effect=AssertionError('Second dispatch forbidden')), \
             self.assertRaisesRegex(c.Refused,'EXTERNAL_FAMILY_DRIFT'):
            c.external_host(b,self.root/'external-cohort-fixture-another-cohort',self.input,self.state,self.old.local.bundle_path,None,1)
        self.assertEqual(c.bounded_json(original_global[0]/'000002.json'),global_reserved)
        self.assertFalse((self.state/'writer.lock').exists())

    def test_registry_only_or_cohort_only_orphan_never_proves_zero_post(self):
        observed=self.observed();proof=self.proof();h=c.validate_authorization(self.new);scope=self.new['external_cohort']['scope']
        with patch.object(c,'external_proof',return_value=proof),patch.object(c,'campaign_runs',return_value=self.old.runs):
            family=c.external_family_registry(self.state,self.new,self.cohort_state)
        journal=c.WorkJournal(self.cohort_state,h)
        journal.append('EXTERNAL_COHORT_BOUND',scope=scope,genesis_sha256=c.external_genesis(scope),**proof)
        # Reserve globally first, then simulate a crash before cohort reserve.
        family.append('RESERVED',nonce=c.PREFIX+'8'*24,scope=scope,capture_auth_sha256=h,
                      remaining=observed['remaining'],parent_checkpoint_sha256=observed['parent_sha'])
        before=family.parent
        try:
            with self.assertRaisesRegex(c.Refused,'CAMPAIGN_JOURNAL_REMOTE_CONFLICT'):
                c.reconcile_external_family(family,journal,self.new,observed)
            self.assertEqual(family.parent,before)
        finally:journal.close();family.close()

    def test_single_side_registry_or_cohort_prefix_rollback_cannot_refund_unknown_post(self):
        # Two independent synthetic namespaces/campaign roots per subcase.
        for target in ('registry','cohort'):
            with self.subTest(target=target):
                fixture=ExternalCohortTests();fixture.setUp()
                try:
                    observed=fixture.observed()
                    with fixture.host_patches(observed),patch.object(c.subprocess,'run',return_value=SimpleNamespace(returncode=1)), \
                         self.assertRaisesRegex(c.Refused,'CAMPAIGN_DISPATCH_UNCERTAIN'):
                        c.external_host(fixture.new,fixture.cohort_state,fixture.input,fixture.state,
                                        fixture.old.local.bundle_path,None,1)
                    family_dir=next(fixture.root.glob('external-budget-*'))
                    truncated=family_dir if target=='registry' else fixture.cohort_state
                    (truncated/'000002.json').unlink()  # Synthetic rollback, never actual journal.
                    with fixture.host_patches(observed),patch.object(c.subprocess,'run',side_effect=AssertionError('No replacement POST')), \
                         self.assertRaisesRegex(c.Refused,'CAMPAIGN_JOURNAL_REMOTE_CONFLICT'):
                        c.external_host(fixture.new,fixture.cohort_state,fixture.input,fixture.state,
                                        fixture.old.local.bundle_path,None,1)
                finally:fixture.doCleanups()

    def test_visible_canonical_run_without_shared_registration_refuses(self):
        observed=self.observed(self.suffix())
        with self.host_patches(observed),patch.object(c.subprocess,'run',side_effect=AssertionError), \
             self.assertRaisesRegex(c.Refused,'EXTERNAL_FAMILY_MISSING'):
            c.external_host(self.new,self.cohort_state,self.input,self.state,self.old.local.bundle_path,None,1)
        self.assertFalse((self.state/'writer.lock').exists())

    def test_whole_registry_missing_cannot_initialize_foreign_namespace_over_pending_cohort(self):
        with self.host_patches(self.observed()),patch.object(c.subprocess,'run',return_value=SimpleNamespace(returncode=1)), \
             self.assertRaisesRegex(c.Refused,'CAMPAIGN_DISPATCH_UNCERTAIN'):
            c.external_host(self.new,self.cohort_state,self.input,self.state,self.old.local.bundle_path,None,1)
        original=(self.cohort_state/'000002.json').read_bytes()
        family_dir=next(self.root.glob('external-budget-*'));preserved=self.root/'preserved-family'
        self.assertEqual(family_dir.resolve().parent,self.root.resolve())
        self.assertEqual(preserved.resolve().parent,self.root.resolve())
        family_dir.rename(preserved)  # Only this isolated synthetic fixture.
        b=copy.deepcopy(self.new);b['external_cohort']['scope']['namespace']='fixture-foreign-cohort'
        frozen=self.proof(b)
        with self.host_patches(self.observed()),patch.object(c,'external_proof',return_value=frozen), \
             patch.object(c.subprocess,'run',side_effect=AssertionError('Missing registry is not zero POST')), \
             self.assertRaisesRegex(c.Refused,'EXTERNAL_FAMILY_MISSING'):
            c.external_host(b,self.root/'external-cohort-fixture-foreign-cohort',self.input,self.state,self.old.local.bundle_path,None,1)
        self.assertEqual((self.cohort_state/'000002.json').read_bytes(),original)
        self.assertTrue((preserved/'000002.json').exists())

    def test_first_family_and_cohort_use_one_consent_snapshot_before_dispatch(self):
        original=self.proof()
        changed=self.proof(changed=dict(body='A1_SIP_EXTERNAL_COHORT_CONSENT '+
                            json.dumps(c.external_proof_record(self.new))+'\nOWNER comment edited'))
        observed=self.observed();observed['external_proof']=changed
        with self.host_patches(observed),patch.object(c,'external_proof',side_effect=[original,changed]) as proof_read, \
             patch.object(c.subprocess,'run',side_effect=AssertionError('Cannot POST across consent drift')), \
             self.assertRaisesRegex(c.Refused,'EXTERNAL_PROOF_DRIFT'):
            c.external_host(self.new,self.cohort_state,self.input,self.state,self.old.local.bundle_path,None,1)
        self.assertEqual(proof_read.call_count,1)
        family_dir=next(self.root.glob('external-budget-*'))
        self.assertEqual(c.bounded_json(family_dir/'000001.json')['proof_sha256'],original['proof_sha256'])
        self.assertEqual(c.bounded_json(self.cohort_state/'000001.json')['proof_sha256'],original['proof_sha256'])
        self.assertFalse((self.cohort_state/'000002.json').exists())

    def seed_pending_epoch(self, run, value):
        proof=self.proof();scope=self.new['external_cohort']['scope'];h=c.validate_authorization(self.new)
        with patch.object(c,'external_proof',return_value=proof),patch.object(c,'campaign_runs',return_value=self.old.runs):
            family=c.external_family_registry(self.state,self.new,self.cohort_state)
        try:
            family.append('RESERVED',nonce=value['nonce'],capture_auth_sha256=h,scope=scope,
                          remaining=value['allowance'],parent_checkpoint_sha256=value['parent_checkpoint_sha256'])
            family.append('RUN_ASSIGNED',nonce=value['nonce'],run_id=run['id'],capture_auth_sha256=h,scope=scope)
        finally:family.close()
        journal=c.WorkJournal(self.cohort_state,h)
        try:
            journal.append('EXTERNAL_COHORT_BOUND',scope=scope,genesis_sha256=c.external_genesis(scope),**proof)
            journal.append('RESERVED',nonce=value['nonce'],remaining=value['allowance'],
                parent_checkpoint_sha256=value['parent_checkpoint_sha256'],external_proof_sha256=proof['proof_sha256'])
            journal.append('RUN_ASSIGNED',nonce=value['nonce'],run_id=run['id'])
        finally:journal.close()

    def test_prior_epoch_loss_or_rebound_conflict_blocks_later_epoch_without_recreation(self):
        for damage in ('intact','missing','empty','bound-only','reserved-only','missing-settled','binding','receipt'):
            with self.subTest(damage=damage):
                f=ExternalCohortTests();f.setUp()
                try:
                    run,value=f.suffix();observed=f.observed((run,value));proof=f.proof()
                    f.seed_pending_epoch(run,value)
                    with f.host_patches(observed),patch.object(c,'checkpoint_from_log',return_value=
                            dict(file_id='fixture-checkpoint-final',sha256=value['checkpoint_sha256'],bytes=100)):
                        c.external_host(f.new,f.cohort_state,f.input,f.state,f.old.local.bundle_path,None,1)
                    b=copy.deepcopy(f.new);ex=b['external_cohort'];raw='ticker\nZZZDISCX\n'
                    ex.update(prior_epochs=[copy.deepcopy(f.new)],input_csv=raw,proof_reference=f.reference+'2')
                    ex['scope']=dict(ex['scope'],namespace='fixture-topcap-cohort',input_sha256=c.digest(raw.encode()))
                    b['account_permission_reference']=ex['proof_reference'];other_proof=f.proof(b)
                    observed=dict(observed,external_proof=other_proof,cohort_runs=[],cohort_receipts=[],
                        examined=0,parent_sha=c.external_genesis(ex['scope']),
                        epoch_proofs={c.validate_authorization(f.new):proof,c.validate_authorization(b):other_proof})
                    other=f.root/'external-cohort-fixture-topcap-cohort'
                    with patch.object(c,'external_proof',return_value=proof):
                        family=c.external_family_registry(f.state,b,other)
                    journal=c.WorkJournal(other,c.validate_authorization(b))
                    journal.append('EXTERNAL_COHORT_BOUND',scope=ex['scope'],
                                   genesis_sha256=c.external_genesis(ex['scope']),**other_proof)
                    try:
                        if damage in ('missing','empty'):
                            f.cohort_state.rename(f.root/'preserved-prior')
                            if damage=='empty':f.cohort_state.mkdir()
                        elif damage in ('bound-only','reserved-only','missing-settled'):
                            keep={'bound-only':1,'reserved-only':2,'missing-settled':3}[damage]
                            for p in f.cohort_state.glob('*.json'):
                                if int(p.stem)>keep:p.unlink()  # Isolated synthetic prefix only.
                        elif damage in ('binding','receipt'):
                            previous=None
                            for p in sorted(f.cohort_state.glob('*.json')):
                                entry=c.bounded_json(p)
                                if damage=='binding' and entry['sequence']==1:entry['proof_sha256']='0'*64
                                if damage=='receipt' and entry['kind']=='SETTLED':entry['receipt_sha256']='0'*64
                                entry['previous_sha256']=previous;p.write_bytes(c.encoded(entry));previous=c.digest(p.read_bytes())
                        before={p.name:p.read_bytes() for p in f.cohort_state.glob('*.json')}
                        with patch.object(c.subprocess,'run',side_effect=AssertionError('No provider or dispatch')):
                            if damage=='intact':self.assertIsNone(c.reconcile_external_family(family,journal,b,observed))
                            else:
                                with self.assertRaises(c.Refused):c.reconcile_external_family(family,journal,b,observed)
                        self.assertEqual(before,{p.name:p.read_bytes() for p in f.cohort_state.glob('*.json')})
                        if damage=='missing':self.assertFalse(f.cohort_state.exists())
                        self.assertFalse((f.cohort_state/'writer.lock').exists())
                        self.assertFalse((other/'000002.json').exists())
                    finally:journal.close();family.close()
                finally:f.doCleanups()

    def test_resumed_success_or_shared_repair_consumes_max_one_without_another_post(self):
        for repair in (False,True):
            with self.subTest(shared_repair=repair):
                f=ExternalCohortTests();f.setUp()
                try:
                    raw='ticker\n'+'\n'.join('ZZZDISC%02d'%i for i in range(40))+'\n'
                    f.new['external_cohort']['input_csv']=raw
                    f.new['external_cohort']['scope']['input_sha256']=c.digest(raw.encode());f.input.write_bytes(raw.encode())
                    run,value=f.suffix();value['examined_after']=32
                    value['new_states']=dict(VALID_COLLECTED=32,VERIFIED_NO_DATA=0,QUARANTINED=0)
                    observed=f.observed((run,value));f.seed_pending_epoch(run,value)
                    ref=dict(file_id='fixture-checkpoint-final',sha256=value['checkpoint_sha256'],bytes=100)
                    if repair:
                        j=c.WorkJournal(f.cohort_state,c.validate_authorization(f.new))
                        try:
                            with f.host_patches(observed),patch.object(c,'checkpoint_from_log',return_value=ref):
                                c.settle_run(j,f.new,run,value)
                        finally:j.close()
                    with f.host_patches(observed),patch.object(c,'checkpoint_from_log',return_value=ref), \
                         patch.object(c.subprocess,'run',side_effect=AssertionError('Unexpected second dispatch')):
                        result=c.external_host(f.new,f.cohort_state,f.input,f.state,f.old.local.bundle_path,None,1)
                    self.assertEqual(result['status'],'BATCH_BOUNDARY');self.assertEqual(result['examined'],32)
                    self.assertEqual(result['charged_usage'],observed['used'])
                    self.assertEqual(len(list(f.cohort_state.glob('*.json'))),4)
                    self.assertFalse((f.state/'writer.lock').exists())
                finally:f.doCleanups()

    def test_actual_cli_empty_physical_parent_and_unchanged_old17(self):
        class Boundary(BaseException):pass
        before={p.name:p.read_bytes() for p in self.state.iterdir()}
        calls=[]
        def dispatch(command,**kwargs):
            self.assertEqual(command[:3],['gh','workflow','run'])
            payload=json.loads(kwargs['input']);calls.append(payload)
            self.assertTrue(all(type(v) is str for v in payload.values()))
            self.assertEqual(payload['resume_file_id'],payload['resume_sha256'])
            self.assertEqual(payload['resume_sha256'],'')
            control=json.loads(payload['campaign_control'])
            self.assertFalse(control['preflight_only']);self.assertEqual(control['authorization'],self.new)
            raise Boundary()
        with self.host_patches(self.observed()),patch.object(c.subprocess,'run',side_effect=dispatch),self.assertRaises(Boundary):
            c.external_host(self.new,self.cohort_state,self.input,self.state,self.old.local.bundle_path,None,1)
        self.assertEqual(len(calls),1)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.state.iterdir()})
        self.assertEqual(c.bounded_json(self.cohort_state/'000002.json')['kind'],'RESERVED')
        self.assertFalse((self.cohort_state/'writer.lock').exists())

    def test_canonical_drift_after_pin_reads_never_reserves_or_dispatches(self):
        before=self.observed();after=copy.deepcopy(before);after['used']['provider_gets']+=1
        with self.host_patches([before,after]),patch.object(c.subprocess,'run',side_effect=AssertionError), \
             self.assertRaisesRegex(c.Refused,'EXTERNAL_CANONICAL_DRIFT'):
            c.external_host(self.new,self.cohort_state,self.input,self.state,self.old.local.bundle_path,None,1)
        self.assertFalse((self.cohort_state/'000002.json').exists())

    def test_asset_404_is_narrow_metered_and_other_errors_terminal(self):
        url='https://paper-api.alpaca.markets/v2/assets/ZZZDISCA'
        with tempfile.TemporaryDirectory() as tmp:
            for code,reason in [(404,'ASSET_NOT_FOUND'),(401,'AUTH'),(403,'PERMISSION'),(429,'RATE_LIMIT'),(500,'HTTP_ERROR')]:
                opener=Opener(failure=HTTPError(url,code,'private',{},io.BytesIO(b'private')))
                m=c.RuntimeMeter(dict(c.LIMITS),Path(tmp)/'meter', (c.utc()+timedelta(seconds=60)).isoformat(),
                                 identity(),opener=opener,asset_symbols=['ZZZDISCA'])
                with self.assertRaisesRegex(c.Refused,'^'+reason+'$'):m.perform(url)
                self.assertEqual(m.used['provider_gets'],1)
            m=meter(tmp)
            with self.assertRaisesRegex(c.Refused,'CAMPAIGN_ENDPOINT'):m.perform(url)
            self.assertEqual(m.used['provider_gets'],0)

    def execute_external_worker(self, unsupported=None, failed_status=None, lost_post=False, drift=False):
        names=self.names
        class AssetServer(Server):
            def open(server,request,**kwargs):
                parts=urlsplit(request.full_url)
                if parts.netloc=='paper-api.alpaca.markets':
                    server.requests.append(request.full_url)
                    name=parts.path.rsplit('/',1)[1]
                    if name==unsupported:
                        raise HTTPError(request.full_url,failed_status or 404,'fixture',{},io.BytesIO(b'fixture'))
                    return Reply(c.encoded(dict(id='00000000-0000-0000-0000-000000000001',
                        symbol=name,exchange='NASDAQ',status='active',**{'class':'us_equity'})))
                return super().open(request,**kwargs)
        server=AssetServer(missing=names[2],lost_post=lost_post)
        observed=self.observed();observed['runs'].append(dict(id=6))
        a=self.new;nonce=c.PREFIX+'6'*24;proof=self.proof()
        args=SimpleNamespace(private_root_folder_id=a['private_root_folder_id'],private_data_folder_id=a['private_data_folder_id'],
                             resume_file_id='',resume_sha256='',start=a['start'],end=a['end'],max_new_symbols=4)
        env=dict(GITHUB_REPOSITORY=c.REPO,GITHUB_REF='refs/heads/master',GITHUB_SHA=a['expected_master'],
            GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_RUN_ATTEMPT='1',GITHUB_RUN_ID='6',INPUT_CAMPAIGN_NONCE=nonce,
            A1_PRIVATE_RESEARCH_AUTHORIZED='true',ALPACA_NONCOMMERCIAL_ACKNOWLEDGED='true',
            ALPACA_API_KEY='fixture-key',ALPACA_API_SECRET='fixture-secret',
            MACRO_DRIVE_CONFIG='[gdrive]\ntype=drive\ntoken='+json.dumps(dict(access_token='fixture-access',
                refresh_token='fixture-refresh',expiry='2030-01-01T00:00:00Z'))+'\n')
        original_meter=c.RuntimeMeter;original_pages=cap.request_pages
        path=self.root/'worker-meter'
        # Historical six-pin authority exercises retained worker semantics;
        # current seven-pin deployment is tested separately below.
        with patch.dict(os.environ,env,clear=True),patch.object(c,'external_history',return_value=observed), \
             patch.object(c,'verify_worker_source'), \
             patch.object(c,'campaign_runs',return_value=observed['runs']), \
             patch.object(c,'external_proof',return_value=dict(proof,proof_sha256='0'*64) if drift else proof), \
             patch.object(c,'worker_deadline',return_value=c.utc()+timedelta(seconds=7100)), \
             patch.object(c,'RuntimeMeter',side_effect=lambda *a,**kw:original_meter(*a,opener=server,**kw)), \
             patch.object(cap,'request_pages',side_effect=lambda *a,**kw:original_pages(*a,pause=lambda _:None,**kw)), \
             patch.object(drive_module.subprocess,'run',side_effect=AssertionError('No external command')), \
             patch('sys.stdout',new=io.StringIO()):
            try:
                result=c.worker(args,dict(authorization=a,nonce=nonce,recovery_run=None,preflight_only=False,
                                         external_binding=proof),path)
            except c.Refused as exc:failure,result=str(exc),None
            else:failure=None
        return failure,c.bounded_json(path) if path.exists() else None,server,result

    def test_real_external_worker_readback_genesis_and_mixed_supported_asset_hold(self):
        failure,m,server,result=self.execute_external_worker(unsupported=self.names[1])
        self.assertIsNone(failure)
        self.assertEqual(m['new_states'],dict(VALID_COLLECTED=2,VERIFIED_NO_DATA=1,QUARANTINED=1))
        self.assertEqual(m['usage']['provider_gets'],8);self.assertEqual(m['examined_before'],0)
        self.assertEqual(m['examined_after'],4);self.assertEqual(m['rows_verified'],4)
        self.assertNotIn(self.names[1],server.symbols)
        self.assertFalse(m['source_admission']);self.assertFalse(m['pit_verified'])
        state=c.decode(server.objects[result['checkpoint']['file_id']][1])
        self.assertEqual(state['cohort_scope'],self.new['external_cohort']['scope'])
        self.assertEqual(state['examined'],self.names)
        self.assertEqual(state['held'],[self.names[1]])
        rawpacks=[v[1] for v in server.objects.values() if v[0]['name'].endswith('.zip')]
        self.assertTrue(rawpacks)
        import zipfile
        with zipfile.ZipFile(io.BytesIO(rawpacks[0])) as z:
            manifest=c.decode(z.read('capture.json'))
            self.assertEqual(manifest['asset_precheck'][0]['symbol'],self.names[0])
            self.assertFalse(manifest['historical_identity_verified'])

    def test_original_observed_owner_hash_needs_no_invented_raw_owner_id(self):
        self.new['owner_permission_id']=None
        failure,m,server,_=self.execute_external_worker()
        self.assertIsNone(failure)
        self.assertEqual(m['bindings'],c.CONTINUATION['bindings'])
        self.assertTrue(server.symbols)

    def test_asset_auth_or_quota_failure_never_becomes_held_or_price_capture(self):
        for code,reason in [(401,'AUTH'),(403,'PERMISSION'),(429,'RATE_LIMIT')]:
            with self.subTest(code=code):
                failure,m,server,_=self.execute_external_worker(unsupported=self.names[1],failed_status=code)
                self.assertEqual(failure,reason);self.assertEqual(server.symbols,set())
                self.assertEqual(m['usage']['provider_gets'],2);self.assertEqual(m['usage']['storage_bytes'],0)
                self.assertEqual(m['examined_after'],0);self.assertEqual(m['status'],'BLOCKED')
                self.assertFalse(server.objects)

    def test_external_lost_upload_and_mutated_consent_preserve_failure_debit(self):
        failure,m,server,_=self.execute_external_worker(lost_post=True)
        self.assertEqual(failure,'NETWORK');self.assertTrue(server.objects)
        self.assertEqual(m['checkpoint_sha256'],c.external_genesis(self.new['external_cohort']['scope']))
        self.assertEqual(m['examined_after'],0);self.assertGreater(m['usage']['storage_bytes'],0)
        self.assertEqual(m['confirmed_storage_bytes'],0)
        (self.root/'worker-meter').unlink()
        failure,m,server,_=self.execute_external_worker(drift=True)
        self.assertEqual(failure,'EXTERNAL_PROOF_DRIFT');self.assertIsNone(m);self.assertFalse(server.requests)


class TransportDiagnosticTests(unittest.TestCase):
    def test_diagnostic_save_failure_suppresses_sensitive_http_context(self):
        import traceback
        with tempfile.TemporaryDirectory() as t:
            url='https://data.alpaca.markets/v2/stocks/bars?PRIVATE_CANARY'
            error=HTTPError(url,502,
                            'PRIVATE_CANARY',{},io.BytesIO(b'PRIVATE_CANARY'))
            m=meter(t,Opener(failure=error))
            with patch.object(m,'save',side_effect=[None,OSError('PRIVATE_CANARY')]):
                try:m.perform(url)
                except c.Refused as exc:
                    self.assertEqual(str(exc),'CAMPAIGN_DIAGNOSTIC_JOURNAL')
                    self.assertNotIn('PRIVATE_CANARY',''.join(traceback.format_exception(exc)))
                else:self.fail('Diagnostic journal failure must stop')
            self.assertTrue(error.fp is None or error.fp.closed)
            self.assertEqual(m.used['provider_gets'],1)

    def test_http_status_phase_and_debit_are_sanitized_and_legacy_meter_unchanged(self):
        for url,category,method in [
                ('https://data.alpaca.markets/v2/stocks/bars?token=PRIVATE_CANARY','ALPACA_BARS','GET'),
                ('https://www.googleapis.com/upload/drive/v3/files?secret=PRIVATE_CANARY','DRIVE_CREATE','POST')]:
            with self.subTest(category=category),tempfile.TemporaryDirectory() as t:
                stream=io.BytesIO(b'PRIVATE_CANARY')
                error=HTTPError(url,502,'PRIVATE_CANARY',{'Authorization':'PRIVATE_CANARY'},stream)
                m=meter(t,Opener(failure=error)); before=c.bounded_json(m.journal)
                self.assertNotIn('last_transport_failure',before)
                with self.assertRaisesRegex(c.Refused,'HTTP_ERROR'):m.perform(url,method=method)
                value=c.bounded_json(m.journal); detail=value['last_transport_failure']
                self.assertEqual(detail,dict(http_status=502,request_category=category,phase='HEADER_OPEN',method=method,request_ordinal=1))
                self.assertTrue(stream.closed);self.assertNotIn('PRIVATE_CANARY',json.dumps(value))
                self.assertEqual(value['usage']['provider_gets']+value['usage']['drive_requests'],1)

    def test_non200_and_body_failure_keep_phase_cleanup_and_full_charge(self):
        for wire,phase,status,reason in [
                (b'HTTP/1.1 503 Unavailable\r\nContent-Length: 1\r\n\r\nx','HEADERS',503,'HTTP_ERROR'),
                (b'HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nx','BODY_READ',200,'NETWORK')]:
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as t:
                opener=WireOpener(wire);m=meter(t,opener)
                with self.assertRaisesRegex(c.Refused,reason):m.perform('https://www.googleapis.com/drive/v3/files/private-id?alt=media',limit=100)
                value=c.bounded_json(m.journal)
                self.assertEqual(value['last_transport_failure']['phase'],phase)
                self.assertEqual(value['last_transport_failure']['http_status'],status)
                self.assertEqual(value['last_transport_failure']['request_category'],'DRIVE_MEDIA')
                self.assertEqual(value['usage']['drive_bytes'],101+65536);self.assertTrue(opener.closed)


class NamedExternalRecoveryTests(unittest.TestCase):
    """Synthetic original13/failed120 revision, never an execution consent."""
    def setUp(self):
        self.base=ExternalCohortTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        b=self.base;self.old=b.new
        raw=('ticker\n'+''.join('ZZZREC%03d\n'%i for i in range(169))).encode()
        self.old['external_cohort']['input_csv']=raw.decode()
        self.old['external_cohort']['scope']['input_sha256']=c.digest(raw);b.input.write_bytes(raw)
        self.old_hash=c.validate_authorization(self.old);self.old_proof=b.proof()
        with patch.object(c,'external_proof',return_value=self.old_proof),patch.object(c,'campaign_runs',return_value=b.old.runs):
            family=c.external_family_registry(b.state,self.old,b.cohort_state)
        self.family_path=family.directory
        journal=c.WorkJournal(b.cohort_state,self.old_hash)
        journal.append('EXTERNAL_COHORT_BOUND',scope=self.old['external_cohort']['scope'],
            genesis_sha256=c.external_genesis(self.old['external_cohort']['scope']),**self.old_proof)
        self.runs=[];self.values=[];used=dict(c.CONTINUATION['used']);before=0
        parent=c.external_genesis(self.old['external_cohort']['scope'])
        for index,end in enumerate((32,64,96,120),6):
            run,value=b.suffix();run.update(id=index,display_title='a1-sip '+c.PREFIX+format(index,'x')*24)
            checkpoint=c.digest(('fixture-checkpoint-%d'%end).encode())
            value.update(run_id=index,nonce=run['display_title'][7:],parent_checkpoint_sha256=parent,
                checkpoint_sha256=checkpoint,examined_before=before,examined_after=end,rows_verified=2*(end-before),
                new_states=dict(VALID_COLLECTED=end-before,VERIFIED_NO_DATA=0,QUARANTINED=0),
                allowance={k:c.CONTINUED_LIMITS[k]-used[k] for k in c.LIMITS})
            if end==120:run['conclusion']='failure';value.update(status='BLOCKED',reason='HTTP_ERROR')
            self.append_pair(journal,family,run,value,self.old_proof)
            self.runs.append(run);self.values.append(value)
            used={k:used[k]+value['usage'][k] for k in c.LIMITS};before,parent=end,checkpoint
        journal.close();family.close()
        specification=dict(c.NAMED_RECOVERY,prior_auth=self.old_hash,run_id=9,
            receipt_sha256=c.digest(c.encoded(self.values[-1])),checkpoint_sha256=parent,
            cohort_event_sha256=c.digest((b.cohort_state/'000013.json').read_bytes()),
            family_event_sha256=c.digest((self.family_path/'000013.json').read_bytes()))
        patcher=patch.dict(c.NAMED_RECOVERY,specification,clear=True);patcher.start();self.addCleanup(patcher.stop)
        self.new=copy.deepcopy(self.old);self.new.update(schema='r1000-sip-external-cohort-authorization-v2',expected_master='4'*40)
        ex=self.new['external_cohort'];ex['proof_reference']=b.reference+'99';self.new['account_permission_reference']=ex['proof_reference']
        ex['named_recovery']=dict(prior_capture_source=dict(expected_master=self.old['expected_master'],
            code_pins=self.old['code_pins'],proof_reference=b.reference),failed_run_id=9,
            failed_receipt_sha256=specification['receipt_sha256'],checkpoint_sha256=parent,examined=120)
        self.new_hash=c.validate_authorization(self.new);self.new_proof=b.proof(self.new)
        self.proofs={self.old_hash:self.old_proof,self.new_hash:self.new_proof}

    def append_pair(self,journal,family,run,value,proof):
        common=dict(nonce=value['nonce'],remaining=value['allowance'],active_seconds_remaining=43200,
                    parent_checkpoint_sha256=value['parent_checkpoint_sha256'])
        family.append('RESERVED',**common,capture_auth_sha256=value['auth_sha256'],scope=value['cohort_scope'])
        journal.append('RESERVED',**common,external_proof_sha256=proof['proof_sha256'])
        family.append('RUN_ASSIGNED',nonce=value['nonce'],run_id=run['id'],capture_auth_sha256=value['auth_sha256'],scope=value['cohort_scope'])
        journal.append('RUN_ASSIGNED',nonce=value['nonce'],run_id=run['id'])
        journal.append('SETTLED',nonce=value['nonce'],run_id=run['id'],receipt=value,
            receipt_sha256=c.digest(c.encoded(value)),usage=value['usage'],examined_after=value['examined_after'],
            checkpoint=dict(file_id='fixture-private-checkpoint-%d'%value['examined_after'],bytes=100,sha256=value['checkpoint_sha256']))
        family.append('SETTLED',nonce=value['nonce'],run_id=run['id'],capture_auth_sha256=value['auth_sha256'],
            scope=value['cohort_scope'],receipt_sha256=c.digest(c.encoded(value)),usage=value['usage'],checkpoint_sha256=value['checkpoint_sha256'])

    def history(self,pairs=(),auth_value=None,**kwargs):
        a=auth_value or self.new;run_values=list(pairs)
        runs=self.base.old.runs+self.runs+[r for r,v in run_values]
        values=self.base.old.receipts+self.values+[v for r,v in run_values]
        with patch.object(c,'external_proof',side_effect=lambda x:self.proofs[c.validate_authorization(x)]), \
             patch.object(c,'campaign_runs',return_value=runs),patch.object(c,'receipt_for_run',side_effect=values), \
             patch.object(c,'job_seconds',side_effect=[27,159,215,206,265]+[10]*(4+len(run_values))):
            return c.external_history(a,**kwargs)

    def next_pair(self,before=120,end=128,index=10,previous=None):
        run=copy.deepcopy(self.runs[-1]);value=copy.deepcopy(self.values[-1])
        run.update(id=index,head_sha=self.new['expected_master'],conclusion='success',display_title='a1-sip '+c.PREFIX+format(index,'x')*24)
        used=dict(c.CONTINUATION['used'])
        for v in self.values+([x[1] for x in previous] if previous else []):
            used={k:used[k]+v['usage'][k] for k in c.LIMITS}
        value.update(run_id=index,auth_sha256=self.new_hash,source_sha=self.new['expected_master'],
            nonce=run['display_title'][7:],status='COMPLETE',reason=None,recovery_run=9 if before==120 else None,
            external_proof_sha256=self.new_proof['proof_sha256'],account_permission_reference_sha256=c.digest(self.new['external_cohort']['proof_reference'].encode()),
            account_permission_record_sha256=self.new_proof['proof_sha256'],examined_before=before,examined_after=end,
            parent_checkpoint_sha256=(previous[-1][1]['checkpoint_sha256'] if previous else self.values[-1]['checkpoint_sha256']),
            checkpoint_sha256=c.digest(('fixture-new-checkpoint-%d'%end).encode()),rows_verified=2*(end-before),
            new_states=dict(VALID_COLLECTED=end-before,VERIFIED_NO_DATA=0,QUARANTINED=0),
            allowance={k:c.CONTINUED_LIMITS[k]-used[k] for k in c.LIMITS})
        return run,value

    def host_context(self,observed):
        from contextlib import ExitStack
        stack=ExitStack();b=self.base
        stack.enter_context(patch.object(c,'local_reject_recovery',return_value=b.old.recovery))
        stack.enter_context(patch.object(c,'external_proof',side_effect=lambda a:self.proofs[c.validate_authorization(a)]))
        stack.enter_context(patch.object(c,'external_history',return_value=observed))
        stack.enter_context(patch.object(c,'campaign_runs',return_value=observed['runs']))
        stack.enter_context(patch.object(c,'external_deployed',return_value=None))
        return stack

    def test_exact_revision_reconstructs_old_auth_without_double_charging(self):
        self.assertEqual(c.external_previous(self.new),self.old)
        observed=self.history(recovery_run=9)
        self.assertEqual(observed['examined'],120);self.assertEqual(observed['active_seconds'],912)
        self.assertEqual(observed['used']['provider_gets'],c.CONTINUATION['used']['provider_gets']+24)
        self.assertEqual(len(observed['runs']),9);self.assertEqual(observed['recovery_required'],9)
        for field in ('failed_run_id','examined','checkpoint_sha256','failed_receipt_sha256'):
            bad=copy.deepcopy(self.new);v=bad['external_cohort']['named_recovery'][field]
            bad['external_cohort']['named_recovery'][field]=v+1 if type(v)is int else '0'*64
            with self.subTest(field=field),self.assertRaises(c.Refused):c.validate_authorization(bad)
        bad=copy.deepcopy(self.new);bad['external_cohort']['input_csv']=bad['external_cohort']['input_csv'].replace('ZZZREC000','ZZZCHANGED')
        bad['external_cohort']['scope']['input_sha256']=c.digest(bad['external_cohort']['input_csv'].encode())
        with self.assertRaises(c.Refused):c.validate_authorization(bad)

    def test_one8_recovery_then_normal_followup_and_no_old_auth_reentry(self):
        first=self.next_pair();observed=self.history([first])
        self.assertEqual(observed['examined'],128);self.assertIsNone(observed['recovery_required'])
        second=self.next_pair(128,160,11,[first]);self.assertEqual(self.history([first,second])['examined'],160)
        for change in [dict(recovery_run=None),dict(examined_after=129),dict(parent_checkpoint_sha256='0'*64)]:
            run,value=copy.deepcopy(first);value.update(change)
            with self.subTest(change=change),self.assertRaises(c.Refused):self.history([(run,value)])
        old_run,old_value=copy.deepcopy(self.runs[-2]),copy.deepcopy(self.values[-2])
        old_run['id']=11
        with self.assertRaisesRegex(c.Refused,'EXTERNAL_AUTH_REVISION_ORDER'):self.history([first,(old_run,old_value)])

    def test_new_failure_never_authorizes_a_second_recovery(self):
        run,value=self.next_pair();run['conclusion']='failure';value.update(status='BLOCKED',reason='HTTP_ERROR',examined_after=120,checkpoint_sha256=value['parent_checkpoint_sha256'],rows_verified=0,new_states=dict(VALID_COLLECTED=0,VERIFIED_NO_DATA=0,QUARANTINED=0))
        with self.assertRaisesRegex(c.Refused,'CAMPAIGN_EXTERNAL_FAILURE_STOP'):self.history([(run,value)])
        accounted=self.history([(run,value)],allow_stopped=True)
        self.assertEqual(accounted['examined'],120);self.assertIsNone(accounted['recovery_required'])
        with self.assertRaises(c.Refused):self.history([(run,value)],recovery_run=9)
        with self.assertRaises(c.Refused):self.history(recovery_run=10)

    def test_first_complete_recovery_must_close_exactly_eight_names(self):
        with self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_CLOSURE'):
            self.history([self.next_pair(end=124)])

    def test_missing_named_failure_refuses_history_and_worker_before_meter(self):
        active,value=self.next_pair();active.update(status='in_progress',conclusion=None)
        self.runs=self.runs[:-1];self.values=self.values[:-1]
        with self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_PARENT'):self.history(recovery_run=9)
        runs=self.base.old.runs+self.runs+[active]
        args=SimpleNamespace(private_root_folder_id=self.new['private_root_folder_id'],
            private_data_folder_id=self.new['private_data_folder_id'],start=self.new['start'],end=self.new['end'],
            max_new_symbols=32,resume_sha256=self.values[-1]['checkpoint_sha256'],resume_file_id='fixture-parent-96')
        control=dict(authorization=self.new,nonce=active['display_title'][7:],recovery_run=9,
                     preflight_only=False,external_binding=self.new_proof)
        env=dict(GITHUB_REPOSITORY=c.REPO,GITHUB_REF='refs/heads/master',GITHUB_SHA=self.new['expected_master'],
            GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_RUN_ATTEMPT='1',GITHUB_RUN_ID=str(active['id']),
            INPUT_CAMPAIGN_NONCE=control['nonce'])
        with patch.dict(os.environ,env),patch.object(c,'campaign_runs',return_value=runs), \
             patch.object(c,'verify_worker_source'), \
             patch.object(c,'receipt_for_run',side_effect=self.base.old.receipts+self.values), \
             patch.object(c,'job_seconds',side_effect=[27,159,215,206,265]+[10]*3), \
             patch.object(c,'external_proof',side_effect=lambda a:self.proofs[c.validate_authorization(a)]), \
             patch.object(c,'RuntimeMeter',side_effect=AssertionError('No meter/I/O before named failure')), \
             self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_PARENT'):
            c.external_worker(args,control,self.base.root/'must-not-create-meter')
        self.assertFalse((self.base.root/'must-not-create-meter').exists())

    def test_revision_binding_preserves_old13_and_rejects_changed_new_proof(self):
        path=self.base.cohort_state;before={p.name:p.read_bytes() for p in path.glob('*.json')}
        j=c.external_journal(path,self.new,self.new_proof)
        j.append('EXTERNAL_RECOVERY_BOUND',**j.revision);j.close()
        self.assertEqual(before,{p.name:p.read_bytes() for p in path.glob('*.json') if p.name in before})
        j=c.external_journal(path,self.new,self.new_proof);j.close()
        with self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_BINDING'):
            c.external_journal(path,self.new,dict(self.new_proof,proof_sha256='0'*64))
        raw=(path/'000013.json').read_bytes();(path/'000013.json').write_bytes(raw+b' ')
        with self.assertRaises(c.Refused):c.external_journal(path,self.new,self.new_proof)

    def test_first_dispatch_requires_max1_and_retains_unknown_post_reservation(self):
        b=self.base;observed=self.history(recovery_run=9)
        for flag,limit in [(None,1),(9,2)]:
            with self.subTest(flag=flag,limit=limit),self.host_context(observed), \
                 patch.object(c.subprocess,'run',side_effect=AssertionError('No dispatch')),self.assertRaises(c.Refused):
                c.external_host(self.new,b.cohort_state,b.input,b.state,b.old.local.bundle_path,flag,limit)
            self.assertFalse((b.cohort_state/'000014.json').exists())
        posted=[]
        def uncertain(args,**kwargs):
            self.assertEqual(args[1:3],['workflow','run']);data=json.loads(kwargs['input'])
            self.assertEqual(data['max_new_symbols'],'8');self.assertEqual(data['resume_sha256'],c.NAMED_RECOVERY['checkpoint_sha256'])
            self.assertEqual(json.loads(data['campaign_control'])['recovery_run'],9);posted.append(data)
            return SimpleNamespace(returncode=1)
        with self.host_context(observed),patch.object(c.subprocess,'run',side_effect=uncertain),self.assertRaisesRegex(c.Refused,'CAMPAIGN_DISPATCH_UNCERTAIN'):
            c.external_host(self.new,b.cohort_state,b.input,b.state,b.old.local.bundle_path,9,1)
        self.assertEqual(len(posted),1)
        self.assertEqual(c.bounded_json(b.cohort_state/'000015.json')['kind'],'RESERVED')
        with self.host_context(observed),patch.object(c.subprocess,'run',side_effect=AssertionError('No second POST')),self.assertRaises(c.Refused):
            c.external_host(self.new,b.cohort_state,b.input,b.state,b.old.local.bundle_path,9,1)
        self.assertFalse((b.cohort_state/'writer.lock').exists());self.assertFalse((self.family_path/'writer.lock').exists())

    def test_success_import_stops_at128_and_uses_effective_revision_proof(self):
        b=self.base;first=self.next_pair();before=self.history(recovery_run=9);after=self.history([first])
        dispatched=[]
        def operation(args,**kwargs):
            if args[1:3]==['workflow','run']:dispatched.append(json.loads(kwargs['input']))
            else:self.assertEqual(args[1:3],['run','watch'])
            return SimpleNamespace(returncode=0)
        with self.host_context(before),patch.object(c,'external_history',side_effect=lambda *a,**k:after if dispatched else before), \
             patch.object(c,'campaign_runs',side_effect=lambda *a:after['runs'] if dispatched else before['runs']), \
             patch.object(c.os,'urandom',side_effect=lambda n:bytes.fromhex('a'*24) if n==12 else b'\x01'*n), \
             patch.object(c.subprocess,'run',side_effect=operation), \
             patch.object(c,'checkpoint_from_log',return_value=dict(file_id='fixture-new-checkpoint-128',sha256=first[1]['checkpoint_sha256'],bytes=100)):
            result=c.external_host(self.new,b.cohort_state,b.input,b.state,b.old.local.bundle_path,9,1)
        self.assertEqual(result['status'],'BATCH_BOUNDARY');self.assertEqual(result['examined'],128);self.assertEqual(len(dispatched),1)
        self.assertEqual(c.bounded_json(b.cohort_state/'000017.json')['kind'],'SETTLED')
        self.assertEqual(c.bounded_json(self.family_path/'000016.json')['kind'],'SETTLED')
        self.assertEqual(c.digest((b.state/'000017.json').read_bytes()),c.CONTINUATION['event'])

    def test_recovery_restart_import_or_family_repair_still_consumes_max1(self):
        b=self.base;first=self.next_pair();after=self.history([first])
        j=c.external_journal(b.cohort_state,self.new,self.new_proof)
        j.append('EXTERNAL_RECOVERY_BOUND',**j.revision);j.close()
        with self.host_context(self.history(recovery_run=9)), \
             patch.object(c.subprocess,'run',side_effect=AssertionError('No POST after binding')):
            for limit in (None,2):
                with self.subTest(stage='bound',limit=limit),self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_BOUNDARY'):
                    c.external_host(self.new,b.cohort_state,b.input,b.state,b.old.local.bundle_path,9,limit)
        j=c.external_journal(b.cohort_state,self.new,self.new_proof)
        with patch.object(c,'external_proof',return_value=self.old_proof):
            family=c.external_family_registry(b.state,self.new,b.cohort_state)
        self.append_pair(j,family,*first,self.new_proof);j.close();family.close()
        # A successful remote recovery exists; neither journal has closed it.
        (b.cohort_state/'000017.json').unlink();(self.family_path/'000016.json').unlink()
        with self.host_context(after),patch.object(c.subprocess,'run',side_effect=AssertionError('No second POST')):
            for limit in (None,2):
                with self.subTest(stage='import',limit=limit),self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_BOUNDARY'):
                    c.external_host(self.new,b.cohort_state,b.input,b.state,b.old.local.bundle_path,9,limit)
            with patch.object(c,'checkpoint_from_log',return_value=dict(file_id='fixture-new-checkpoint-128',sha256=first[1]['checkpoint_sha256'],bytes=100)):
                result=c.external_host(self.new,b.cohort_state,b.input,b.state,b.old.local.bundle_path,9,1)
            self.assertEqual(result['status'],'BATCH_BOUNDARY');self.assertEqual(result['examined'],128)
            # Crash after cohort SETTLED but before shared family SETTLED.
            (self.family_path/'000016.json').unlink()
            with self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_BOUNDARY'):
                c.external_host(self.new,b.cohort_state,b.input,b.state,b.old.local.bundle_path,None,2)
            repaired=c.external_host(self.new,b.cohort_state,b.input,b.state,b.old.local.bundle_path,None,1)
            self.assertEqual(repaired['status'],'BATCH_BOUNDARY');self.assertEqual(repaired['examined'],128)

    def test_later_cohort_verifies_revision_journal_and_control_size(self):
        b=self.base;j=c.external_journal(b.cohort_state,self.new,self.new_proof)
        j.append('EXTERNAL_RECOVERY_BOUND',**j.revision)
        with patch.object(c,'external_proof',return_value=self.old_proof):
            family=c.external_family_registry(b.state,self.new,b.cohort_state)
        pairs=[]
        for start,end,index in [(120,128,10),(128,160,11),(160,169,12)]:
            pair=self.next_pair(start,end,index,pairs);pairs.append(pair)
            self.append_pair(j,family,*pair,self.new_proof)
        j.close();family.close()
        later=copy.deepcopy(self.old);ex=later['external_cohort'];raw='ticker\nZZZLATER\n'
        ex.update(input_csv=raw,prior_epochs=[self.new],proof_reference=b.reference+'999')
        ex['scope']=dict(ex['scope'],namespace='fixture-marketcap-500',input_sha256=c.digest(raw.encode()))
        later['account_permission_reference']=ex['proof_reference'];later_hash=c.validate_authorization(later)
        self.proofs[later_hash]=b.proof(later)
        observed=self.history(pairs,auth_value=later)
        with patch.object(c,'external_proof',return_value=self.old_proof):
            family=c.external_family_registry(b.state,later,b.root/'external-cohort-fixture-marketcap-500')
        try:
            c.verify_external_prior_journals(family,later,observed)
            raw=(b.cohort_state/'000014.json').read_bytes();(b.cohort_state/'000014.json').write_bytes(raw+b' ')
            with self.assertRaises(c.Refused):c.verify_external_prior_journals(family,later,observed)
        finally:family.close()
        self.assertLessEqual(len(c.encoded(later)),15000)
        self.assertLessEqual(len(c.encoded(dict(authorization=later,nonce=c.PREFIX+'a'*24,recovery_run=None,preflight_only=False,external_binding=self.proofs[later_hash]))),16384)

    def test_worker_limits_parent8_and_records_new_failure_without_reset(self):
        active,value=self.next_pair();active.update(status='in_progress',conclusion=None)
        runs=self.base.old.runs+self.runs+[active]
        args=SimpleNamespace(private_root_folder_id=self.new['private_root_folder_id'],
            private_data_folder_id=self.new['private_data_folder_id'],start=self.new['start'],end=self.new['end'],
            max_new_symbols=8,resume_sha256=c.NAMED_RECOVERY['checkpoint_sha256'],resume_file_id='fixture-parent-120')
        control=dict(authorization=self.new,nonce=active['display_title'][7:],recovery_run=9,
                     preflight_only=False,external_binding=self.new_proof)
        env=dict(GITHUB_REPOSITORY=c.REPO,GITHUB_REF='refs/heads/master',GITHUB_SHA=self.new['expected_master'],
            GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_RUN_ATTEMPT='1',GITHUB_RUN_ID=str(active['id']),
            INPUT_CAMPAIGN_NONCE=control['nonce'],ALPACA_API_KEY='fixture-key',ALPACA_API_SECRET='fixture-secret')
        original_meter=c.RuntimeMeter;opener=Opener(failure=HTTPError('https://data.alpaca.markets/PRIVATE_CANARY',502,'PRIVATE_CANARY',{},io.BytesIO(b'PRIVATE_CANARY')))
        def create_meter(*a,**k):return original_meter(*a,opener=opener,**k)
        def collect(a,**k):
            self.assertEqual(k['expected_examined'],120)
            self.assertEqual(cap.external_cohort(k['external']['input_csv'].encode())[120:128],
                             cap.external_cohort(self.new['external_cohort']['input_csv'].encode())[120:128])
            k['get']('https://data.alpaca.markets/v2/stocks/bars?PRIVATE_CANARY')
        def context():
            from contextlib import ExitStack
            stack=ExitStack();stack.enter_context(patch.dict(os.environ,env))
            # Retained six-pin recovery fixture; not current deployment proof.
            stack.enter_context(patch.object(c,'verify_worker_source'))
            stack.enter_context(patch.object(c,'campaign_runs',return_value=runs))
            stack.enter_context(patch.object(c,'receipt_for_run',side_effect=self.base.old.receipts+self.values))
            stack.enter_context(patch.object(c,'job_seconds',side_effect=[27,159,215,206,265]+[10]*4))
            stack.enter_context(patch.object(c,'external_proof',side_effect=lambda a:self.proofs[c.validate_authorization(a)]))
            stack.enter_context(patch.object(c,'worker_deadline',return_value=c.utc()+timedelta(seconds=60)))
            return stack
        path=self.base.root/'new-worker-meter'
        args.max_new_symbols=32
        with context(),patch.object(c,'RuntimeMeter',side_effect=AssertionError('No I/O meter for wrong scope')),self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_PARENT'):
            c.external_worker(args,control,path)
        args.max_new_symbols=8
        with context(),patch.object(c,'RuntimeMeter',side_effect=create_meter),patch.object(cap,'_collect',side_effect=collect),self.assertRaisesRegex(c.Refused,'HTTP_ERROR'):
            c.external_worker(args,control,path)
        meter_value=c.bounded_json(path)
        self.assertEqual(meter_value['usage']['provider_gets'],1);self.assertEqual(opener.calls,1)
        self.assertEqual(meter_value['examined_after'],120);self.assertEqual(meter_value['rows_verified'],0)
        self.assertEqual(meter_value['checkpoint_sha256'],c.NAMED_RECOVERY['checkpoint_sha256'])
        self.assertEqual(meter_value['allowance']['provider_gets'],c.CONTINUED_LIMITS['provider_gets']-c.CONTINUATION['used']['provider_gets']-24)
        self.assertEqual(meter_value['last_transport_failure']['http_status'],502)
        self.assertNotIn('PRIVATE_CANARY',json.dumps(meter_value))

    def test_failed_first_attempt_settles_once_and_restart_cannot_dispatch(self):
        b=self.base;run,value=self.next_pair();run['conclusion']='failure'
        value.update(status='BLOCKED',reason='HTTP_ERROR',examined_after=120,
            checkpoint_sha256=value['parent_checkpoint_sha256'],rows_verified=0,
            new_states=dict(VALID_COLLECTED=0,VERIFIED_NO_DATA=0,QUARANTINED=0))
        before=self.history(recovery_run=9);after=self.history([(run,value)],allow_stopped=True)
        posted=[]
        def operation(args,**kwargs):
            if args[1:3]==['workflow','run']:posted.append(1)
            return SimpleNamespace(returncode=0)
        with self.host_context(before),patch.object(c,'external_history',side_effect=lambda *a,**k:after if posted else before), \
             patch.object(c,'campaign_runs',side_effect=lambda *a:after['runs'] if posted else before['runs']), \
             patch.object(c.os,'urandom',side_effect=lambda n:bytes.fromhex('a'*24) if n==12 else b'\x01'*n), \
             patch.object(c.subprocess,'run',side_effect=operation),self.assertRaisesRegex(c.Refused,'CAMPAIGN_WORKER_BLOCKED'):
            c.external_host(self.new,b.cohort_state,b.input,b.state,b.old.local.bundle_path,9,1)
        self.assertEqual(len(posted),1)
        self.assertEqual(c.bounded_json(b.cohort_state/'000017.json')['receipt'],value)
        with self.host_context(after),patch.object(c.subprocess,'run',side_effect=AssertionError('No second attempt')),self.assertRaisesRegex(c.Refused,'CAMPAIGN_WORKER_BLOCKED'):
            c.external_host(self.new,b.cohort_state,b.input,b.state,b.old.local.bundle_path,None,1)

    def test_expiry_and_missing_family_prefix_never_reset_or_recreate_state(self):
        original=c.utc;future=original(self.new_proof['expires_at_utc'])+timedelta(seconds=1)
        old_receipts=c.encoded(self.values)
        with patch.object(c,'utc',side_effect=lambda value=None:future if value is None else original(value)):
            with self.assertRaisesRegex(c.Refused,'CAMPAIGN_EXPIRED'):self.history(recovery_run=9)
            accounted=self.history(enforce_expiry=False,allow_stopped=True)
        self.assertEqual(accounted['examined'],120);self.assertEqual(c.encoded(self.values),old_receipts)
        prefix=self.family_path/'000013.json';before=prefix.read_bytes();prefix.unlink()
        with patch.object(c,'external_proof',return_value=self.old_proof), \
             self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_FAMILY_PREFIX'):
            c.external_family_registry(self.base.state,self.new,self.base.cohort_state)
        self.assertFalse(prefix.exists());self.assertFalse((self.family_path/'writer.lock').exists())
        prefix.write_bytes(before)


class DriveRevisionTests(unittest.TestCase):
    """A second *named* transition; all evidence here is offline synthetic."""
    def setUp(self):
        n=NamedExternalRecoveryTests(); n.setUp(); self.addCleanup(n.doCleanups)
        self.n=n; self.b=n.base; self.pairs=[]
        j=c.external_journal(self.b.cohort_state,n.new,n.new_proof)
        j.append('EXTERNAL_RECOVERY_BOUND',**j.revision)
        with patch.object(c,'external_proof',return_value=n.old_proof):
            family=c.external_family_registry(self.b.state,n.new,self.b.cohort_state)
        for before,end,index in [(120,128,10),(128,160,11),(160,169,12)]:
            run,value=n.next_pair(before,end,index,self.pairs)
            if index==12:
                run['conclusion']='failure'
                value.update(status='BLOCKED',reason='HTTP_ERROR',examined_after=160,
                    checkpoint_sha256=value['parent_checkpoint_sha256'],rows_verified=0,
                    new_states=dict(VALID_COLLECTED=0,VERIFIED_NO_DATA=0,QUARANTINED=0),
                    last_transport_failure=dict(http_status=502,method='POST',phase='HEADER_OPEN',request_category='DRIVE_CREATE',request_ordinal=343))
            n.append_pair(j,family,run,value,n.new_proof); self.pairs.append((run,value))
        j.close();family.close()
        spec=dict(c.DRIVE_RECOVERY,prior_auth=n.new_hash,master=n.new['expected_master'],run_id=12,
            receipt_sha256=c.digest(c.encoded(self.pairs[-1][1])),checkpoint_sha256=self.pairs[-1][1]['checkpoint_sha256'],
            cohort_event_sha256=c.digest((self.b.cohort_state/'000023.json').read_bytes()),
            family_event_sha256=c.digest((n.family_path/'000022.json').read_bytes()))
        patcher=patch.dict(c.DRIVE_RECOVERY,spec,clear=True);patcher.start();self.addCleanup(patcher.stop)
        self.new=copy.deepcopy(n.new); self.new.update(schema='r1000-sip-external-cohort-authorization-v3',expected_master='5'*40)
        ex=self.new['external_cohort'];old_ref=ex['proof_reference'];ex['proof_reference']=self.b.reference+'9999'
        self.new['account_permission_reference']=ex['proof_reference']
        ex['drive_recovery']=dict(prior_capture_source=dict(expected_master=n.new['expected_master'],
            code_pins=n.new['code_pins'],proof_reference=old_ref),failed_run_id=12,
            failed_receipt_sha256=spec['receipt_sha256'],checkpoint_sha256=spec['checkpoint_sha256'],examined=160)
        self.h=c.validate_authorization(self.new);self.proof=self.b.proof(self.new);n.proofs[self.h]=self.proof

    def history(self,extra=(),**kwargs):
        return self.n.history(self.pairs+list(extra),auth_value=self.new,**kwargs)

    def completion(self,end=169):
        run,value=self.n.next_pair(160,end,13,self.pairs)
        run['head_sha']=self.new['expected_master']
        value.update(auth_sha256=self.h,source_sha=self.new['expected_master'],recovery_run=12,
            external_proof_sha256=self.proof['proof_sha256'],account_permission_record_sha256=self.proof['proof_sha256'],
            account_permission_reference_sha256=c.digest(self.new['external_cohort']['proof_reference'].encode()))
        value['drive_orphan_reuse']=dict(failed_run_id=12,capture_source_sha=c.DRIVE_RECOVERY['master'],
            derivation_source_sha=self.new['expected_master'],raw_sha256='b'*64,normalized_sha256='c'*64,
            external_proof_sha256=self.proof['proof_sha256'],derivation_run_id=run['id'],
            derivation_auth_sha256=self.h,parent_checkpoint_sha256=c.DRIVE_RECOVERY['checkpoint_sha256'],
            derived_at_utc=c.utc().isoformat(),failed_run_observation_window=[c.DRIVE_RECOVERY['window_start'],c.DRIVE_RECOVERY['window_end']])
        return run,value

    def test_exact_three_versions_and_all_spent_costs_preserved(self):
        self.assertEqual(c.external_previous(self.new),self.n.new)
        self.assertEqual(c.external_variants(self.new),[self.n.old,self.n.new,self.new])
        observed=self.history(recovery_run=12)
        self.assertEqual(observed['examined'],160);self.assertEqual(len(observed['runs']),12)
        self.assertEqual(observed['recovery_required'],12)
        expected=c.CONTINUATION['used']['provider_gets']+sum(v['usage']['provider_gets'] for v in self.n.values+[p[1] for p in self.pairs])
        self.assertEqual(observed['used']['provider_gets'],expected)
        self.assertEqual(self.history([self.completion()])['examined'],169)
        for flag in (9,13):
            with self.subTest(flag=flag),self.assertRaises(c.Refused):self.history(recovery_run=flag)
        with self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_CLOSURE'):self.history([self.completion(164)])

    def test_sealed_old23_and_binding24_reject_proof_or_prefix_drift(self):
        before={p.name:p.read_bytes() for p in self.b.cohort_state.glob('*.json')}
        with patch.object(c,'external_proof',side_effect=lambda a:self.n.proofs[c.validate_authorization(a)]):
            j=c.external_journal(self.b.cohort_state,self.new,self.proof)
            j.append('EXTERNAL_DRIVE_RECOVERY_BOUND',**j.drive_revision);j.close()
            self.assertEqual(before,{p.name:p.read_bytes() for p in self.b.cohort_state.glob('*.json') if p.name in before})
            j=c.external_journal(self.b.cohort_state,self.new,self.proof);j.close()
            with self.assertRaisesRegex(c.Refused,'EXTERNAL_DRIVE_BINDING'):
                c.external_journal(self.b.cohort_state,self.new,dict(self.proof,proof_sha256='0'*64))
            (self.b.cohort_state/'000023.json').write_bytes(before['000023.json']+b' ')
            with self.assertRaises(c.Refused):c.external_journal(self.b.cohort_state,self.new,self.proof)

    def test_new_failure_is_terminal_and_wrong_target_cannot_bind(self):
        run,value=self.completion();run['conclusion']='failure'
        value.update(status='BLOCKED',reason='HTTP_ERROR',examined_after=160,checkpoint_sha256=value['parent_checkpoint_sha256'])
        with self.assertRaisesRegex(c.Refused,'CAMPAIGN_EXTERNAL_FAILURE_STOP'):self.history([(run,value)])
        self.assertEqual(self.history([(run,value)],allow_stopped=True)['examined'],160)
        for field in ('failed_run_id','failed_receipt_sha256','checkpoint_sha256','examined'):
            bad=copy.deepcopy(self.new);old=bad['external_cohort']['drive_recovery'][field]
            bad['external_cohort']['drive_recovery'][field]=old+1 if type(old)is int else '0'*64
            with self.subTest(field=field),self.assertRaises(c.Refused):c.validate_authorization(bad)

    def test_max1_unknown_post_and_family22_prefix_guard(self):
        observed=self.history(recovery_run=12);posted=[]
        def operation(args,**kwargs):
            data=json.loads(kwargs['input']);self.assertEqual(data['max_new_symbols'],'9')
            self.assertEqual(json.loads(data['campaign_control'])['recovery_run'],12);posted.append(data)
            return SimpleNamespace(returncode=1)
        with self.n.host_context(observed),patch.object(c.subprocess,'run',side_effect=AssertionError('No POST')):
            with self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_BOUNDARY'):
                c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,self.b.old.local.bundle_path,12,2)
        with self.n.host_context(observed),patch.object(c.subprocess,'run',side_effect=operation),self.assertRaisesRegex(c.Refused,'CAMPAIGN_DISPATCH_UNCERTAIN'):
            c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,self.b.old.local.bundle_path,12,1)
        self.assertEqual(len(posted),1)
        with self.n.host_context(observed),patch.object(c.subprocess,'run',side_effect=AssertionError('No second POST')),self.assertRaises(c.Refused):
            c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,self.b.old.local.bundle_path,12,1)

    def test_prior500_wrapper_checks_both_revision_events_and_control_size(self):
        pair=self.completion()
        with patch.object(c,'external_proof',side_effect=lambda a:self.n.proofs[c.validate_authorization(a)]):
            j=c.external_journal(self.b.cohort_state,self.new,self.proof)
            j.append('EXTERNAL_DRIVE_RECOVERY_BOUND',**j.drive_revision)
            family=c.external_family_registry(self.b.state,self.new,self.b.cohort_state)
            self.n.append_pair(j,family,*pair,self.proof);j.close();family.close()
        later=copy.deepcopy(self.n.old);ex=later['external_cohort']
        raw='ticker\n'+''.join('Q%03d\n'%i for i in range(500))
        ex.update(input_csv=raw,prior_epochs=[self.new],proof_reference=self.b.reference+'99999')
        ex['scope']=dict(ex['scope'],namespace='fixture-marketcap-500',input_sha256=c.digest(raw.encode()))
        later.update(expected_master=self.new['expected_master'],code_pins=self.new['code_pins'],account_permission_reference=ex['proof_reference'])
        h=c.validate_authorization(later);self.n.proofs[h]=self.b.proof(later)
        observed=self.n.history(self.pairs+[pair],auth_value=later)
        with patch.object(c,'external_proof',return_value=self.n.old_proof):
            family=c.external_family_registry(self.b.state,later,self.b.root/'external-cohort-fixture-marketcap-500')
        try:
            with patch.object(c,'external_proof',side_effect=AssertionError('No remote I/O in final local guard')):
                c.verify_external_prior_journals(family,later,observed)
                missing=dict(observed,epoch_proofs={k:v for k,v in observed['epoch_proofs'].items() if k!=self.n.new_hash})
                with self.assertRaisesRegex(c.Refused,'EXTERNAL_PRIOR_JOURNAL_DRIFT'):
                    c.verify_external_prior_journals(family,later,missing)
        finally:family.close()
        self.assertLessEqual(len(c.encoded(dict(authorization=later,nonce=c.PREFIX+'a'*24,
            recovery_run=None,preflight_only=False,external_binding=self.n.proofs[h]))),16384)
        self.assertEqual(c.bounded_json(self.b.cohort_state/'000024.json')['kind'],'EXTERNAL_DRIVE_RECOVERY_BOUND')

    def test_worker_reconciles_before_provider_then_only_remaining_five(self):
        from contextlib import ExitStack
        observed=self.history(recovery_run=12);run,_=self.completion();run.update(status='in_progress',conclusion=None)
        observed['runs']=observed['runs']+[run]
        args=SimpleNamespace(private_root_folder_id=self.new['private_root_folder_id'],private_data_folder_id=self.new['private_data_folder_id'],
            start=self.new['start'],end=self.new['end'],max_new_symbols=9,resume_sha256=c.DRIVE_RECOVERY['checkpoint_sha256'],resume_file_id='fixture-parent-160')
        control=dict(authorization=self.new,nonce=run['display_title'][7:],recovery_run=12,preflight_only=False,external_binding=self.proof)
        env=dict(GITHUB_SHA=self.new['expected_master'],GITHUB_RUN_ID=str(run['id']),INPUT_CAMPAIGN_NONCE=control['nonce'],ALPACA_API_KEY='fixture-key',ALPACA_API_SECRET='fixture-secret')
        original=c.RuntimeMeter;opener=Opener(body=b'{}');meters=[];reconciled=[]
        def create(*a,**k):
            value=original(*a,opener=opener,**k);meters.append(value);return value
        def recover(drive,a,auth_value,meter):
            self.assertEqual(meter.used['provider_gets'],0);reconciled.append(1)
            meter.examined=164;meter.checkpoint_sha='b'*64;return dict(file_id='fixture-parent-164',sha256='b'*64)
        def collect(a,**k):
            k['drive_factory'](a.private_root_folder_id,str(self.b.root))
            self.assertEqual(reconciled,[1]);self.assertEqual(a.max_new_symbols,5);self.assertEqual(a.resume_sha256,'b'*64)
            self.assertEqual(k['expected_examined'],164)
            for symbol in cap.external_cohort(self.new['external_cohort']['input_csv'].encode())[164:169]:
                k['get']('https://paper-api.alpaca.markets/v2/assets/'+symbol)
            meter=meters[-1];meter.examined=169;meter.checkpoint_sha='c'*64
            return dict(checkpoint=dict(sha256='c'*64))
        def context():
            stack=ExitStack();stack.enter_context(patch.dict(os.environ,env))
            stack.enter_context(patch.object(c,'verify_worker_source',return_value=None))
            stack.enter_context(patch.object(c,'external_history',return_value=observed))
            stack.enter_context(patch.object(c,'external_proof',return_value=self.proof))
            stack.enter_context(patch.object(c,'campaign_runs',return_value=observed['runs']))
            stack.enter_context(patch.object(c,'worker_deadline',return_value=c.utc()+timedelta(seconds=60)))
            stack.enter_context(patch.object(c,'RuntimeMeter',side_effect=create))
            stack.enter_context(patch.object(drive_module,'OwnerDrive',return_value=SimpleNamespace(owner=self.new['owner_permission_id'],free=3*1024**3)))
            stack.enter_context(patch.object(cap,'_collect',side_effect=collect));return stack
        with context(),patch.object(c,'recover_drive_orphan',side_effect=c.Refused('EXTERNAL_ORPHAN_MISSING_OR_AMBIGUOUS')),self.assertRaises(c.Refused):
            c.external_worker(args,control,self.b.root/'worker-missing-meter')
        self.assertEqual(opener.calls,0);self.assertEqual(meters[-1].examined,160)
        with context(),patch.object(c,'recover_drive_orphan',side_effect=recover):
            c.external_worker(args,control,self.b.root/'worker-five-meter')
        self.assertEqual(opener.calls,5);self.assertEqual(args.max_new_symbols,9)
        self.assertEqual(c.bounded_json(self.b.root/'worker-five-meter')['examined_after'],169)

    def test_expiry_missing_failure_and_changed_provenance_refuse(self):
        original=c.utc;future=original(self.proof['expires_at_utc'])+timedelta(seconds=1)
        with patch.object(c,'utc',side_effect=lambda value=None:future if value is None else original(value)),self.assertRaisesRegex(c.Refused,'CAMPAIGN_EXPIRED'):
            self.history(recovery_run=12)
        removed=self.pairs.pop()
        try:
            with self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_PARENT'):self.history(recovery_run=12)
        finally:self.pairs.append(removed)
        run,value=self.completion();value['drive_orphan_reuse']['capture_source_sha']='0'*40
        with self.assertRaisesRegex(c.Refused,'EXTERNAL_ORPHAN_PROVENANCE'):self.history([(run,value)])

    def close_host_once(self):
        before=self.history(recovery_run=12);pair=self.completion();after=self.history([pair]);posted=[]
        def operation(args,**kwargs):
            if args[1:3]==['workflow','run']:posted.append(json.loads(kwargs['input']))
            else:self.assertEqual(args[1:3],['run','watch'])
            return SimpleNamespace(returncode=0)
        ref=dict(file_id='fixture-new-checkpoint-169',sha256=pair[1]['checkpoint_sha256'],bytes=100)
        with self.n.host_context(before), \
             patch.object(c,'external_history',side_effect=lambda *a,**k:after if posted else before), \
             patch.object(c,'campaign_runs',side_effect=lambda *a:after['runs'] if posted else before['runs']), \
             patch.object(c.os,'urandom',side_effect=lambda n:bytes.fromhex('d'*24) if n==12 else b'\x01'*n), \
             patch.object(c.subprocess,'run',side_effect=operation),patch.object(c,'checkpoint_from_log',return_value=ref):
            result=c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,self.b.old.local.bundle_path,12,1)
        self.assertEqual(result['status'],'COHORT_PROCESSED');self.assertEqual(result['examined'],169)
        self.assertEqual(len(posted),1);self.assertEqual(posted[0]['max_new_symbols'],'9')
        self.assertEqual(c.bounded_json(self.b.cohort_state/'000027.json')['receipt'],pair[1])
        self.assertEqual(c.bounded_json(self.n.family_path/'000025.json')['kind'],'SETTLED')
        return after,ref

    def test_complete9_host_selects_active_proof_and_restart_never_reposts(self):
        after,ref=self.close_host_once()
        with self.n.host_context(after),patch.object(c.subprocess,'run',side_effect=AssertionError('No second POST')):
            result=c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,self.b.old.local.bundle_path,None,1)
        self.assertEqual(result['examined'],169);self.assertEqual(len(list(self.b.cohort_state.glob('*.json'))),27)

    def test_completed9_import_and_family_repair_consume_one_batch(self):
        after,ref=self.close_host_once()
        (self.b.cohort_state/'000027.json').unlink();(self.n.family_path/'000025.json').unlink()
        with self.n.host_context(after),patch.object(c.subprocess,'run',side_effect=AssertionError('No second POST')), \
             patch.object(c,'checkpoint_from_log',return_value=ref):
            with self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_BOUNDARY'):
                c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,self.b.old.local.bundle_path,None,2)
            self.assertEqual(c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,self.b.old.local.bundle_path,None,1)['examined'],169)
            (self.n.family_path/'000025.json').unlink()
            with self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_BOUNDARY'):
                c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,self.b.old.local.bundle_path,None,2)
            self.assertEqual(c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,self.b.old.local.bundle_path,None,1)['examined'],169)


class DriveOrphanReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.group=['TWST','UBS','UL','UPST'];self.names=['ZZZ%03d'%n for n in range(160)]+self.group+['VCYT','VICR','VIR','VSTM','WULF']
        raw=('ticker\n'+'\n'.join(self.names)+'\n').encode();scope=dict(task_key='R1000-DISCOVERY-EXPANSION-INTAKE-20261017',namespace='discovery169-20261017',input_sha256=c.digest(raw))
        self.auth=dict(expected_master='5'*40,start='2016-01-04',end='2026-10-14',external_cohort=dict(input_csv=raw.decode(),scope=scope))
        self.args=SimpleNamespace(private_data_folder_id='fixture-folder-123',resume_file_id='fixture-checkpoint-160',resume_sha256='a'*64)
        assets=[]
        for symbol in self.group:
            asset=c.encoded(dict(symbol=symbol,**{'class':'us_equity'},id='00000000-0000-0000-0000-000000000001',exchange='NASDAQ',status='active'))
            assets.append(dict(symbol=symbol,url='https://paper-api.alpaca.markets/v2/assets/'+symbol,collected_at_utc='2026-10-17T12:24:00Z',http_status=200,response_utf8=asset.decode(),sha256=c.digest(asset)))
        bar=dict(t='2026-10-01T00:00:00Z',o=1,h=2,l=1,c=2,v=4)
        payload=c.encoded(dict(bars={s:[bar] for s in self.group},next_page_token=None));member=c.digest(payload)+'.json'
        pages=[dict(sha256=c.digest(payload),bytes=len(payload),member=member,page=0,symbols=self.group,adjustment=b) for b in ('raw','split')]
        self.manifest=dict(schema=cap.SCHEMA,source=cap.SOURCE,symbols=self.group,collected=self.group,no_bars=[],start=self.auth['start'],end=self.auth['end'],asof='2026-10-13',
            seed_sha256=scope['input_sha256'],source_sha='4'*40,pages=pages,raw_adjustments=['raw','split'],historical_identity_verified=False,pit_verified=False,source_admission=False,commercial_use_authorized=False,cohort_scope=scope,asset_precheck=assets)
        self.members={member:payload};self.raw=cap.zip_bytes(dict(self.members,**{'capture.json':c.encoded(self.manifest)}))
        rows=[r for s in self.group for b in ('raw','split') for r in cap.normalize([bar],s,b,self.auth['start'],self.auth['end'])]
        self.norm=cap.gzip.compress(b''.join(c.encoded(r) for r in rows),mtime=0)
        self.store={'fixture-raw-123':self.raw,'fixture-norm-123':self.norm};self.suffix={'fixture-raw-123':'.zip','fixture-norm-123':'.jsonl.gz'};self.writes=[]
        self.listing=[dict(id=k,name=c.digest(v)+self.suffix[k],size=str(len(v)),parents=[self.args.private_data_folder_id],createdTime='2026-10-17T12:25:00Z') for k,v in self.store.items()]
        test=self
        class Drive:
            token='OFFLINE_ONLY'; owner='fixture-owner'
            def request(self,url,**kwargs):
                q=parse_qs(urlsplit(url).query)['q'][0]
                if 'createdTime' in q:return c.encoded(test.reply)
                name=q.split("name = '")[1].split("'")[0]
                return c.encoded(dict(files=[dict(id=k,name=name) for k,v in test.store.items() if c.digest(v)+test.suffix[k]==name]))
            def check(self,fid,parent=None,folder=False):
                c.require(fid in test.store and parent==test.args.private_data_folder_id,'OFFLINE_OWNER_REFUSAL')
            def read(self,fid,limit=16_000_000):return test.store[fid]
            def write(self,folder,raw,extension):
                test.assertEqual(extension,'.json');test.writes.append(extension)
                fid='fixture-new-'+str(len(test.writes));test.store[fid]=raw;test.suffix[fid]=extension
                return dict(file_id=fid,sha256=c.digest(raw),bytes=len(raw))
        self.drive=Drive();self.reply=dict(files=self.listing)
        patcher=patch.dict(c.DRIVE_RECOVERY,dict(c.DRIVE_RECOVERY,master='4'*40,checkpoint_sha256='a'*64,raw_bytes=len(self.raw)),clear=True)
        patcher.start();self.addCleanup(patcher.stop)
        meter_identity=dict(identity(),source_sha=self.auth['expected_master'],examined_before=160,parent_checkpoint_sha256='a'*64,recovery_run=c.DRIVE_RECOVERY['run_id'],cohort_scope=scope,external_proof_sha256='e'*64)
        self.meter=c.RuntimeMeter(dict(c.CONTINUED_LIMITS),self.root/'meter',(c.utc()+timedelta(minutes=10)).isoformat(),meter_identity,limits=c.CONTINUED_LIMITS)
        self.parent=dict(file_id=self.args.resume_file_id,sha256='a'*64,bytes=100)

    def recover(self):
        with patch.dict(os.environ,{'GITHUB_SHA':self.auth['expected_master']}), \
             patch.object(cap,'resume_state',return_value=(self.names[:160],self.names[:160],[],self.parent)):
            return c.recover_drive_orphan(self.drive,self.args,self.auth,self.meter)

    def test_exact_existing_originals_admit_four_with_no_provider_or_pack_write(self):
        before=dict(self.store);ref=self.recover();self.assertEqual(self.writes,['.json','.json'])
        self.assertEqual(self.meter.examined,164);self.assertEqual(self.meter.rows,8)
        self.assertEqual(self.meter.used['provider_gets'],0)
        self.assertEqual(before,{k:self.store[k] for k in before})
        state=c.decode(self.store[ref['file_id']]);receipt=c.decode(self.store[state['last_objects'][2]['file_id']])
        self.assertEqual(receipt['source_sha'],'4'*40)
        self.assertEqual(receipt['recovered_from']['derivation_source_sha'],'5'*40)
        self.assertEqual(receipt['asset_precheck'],self.manifest['asset_precheck'])

    def test_missing_duplicate_or_paginated_listing_never_writes(self):
        for files,token in [([],None),(self.listing[:1],None),(self.listing*2,None),(self.listing,'more')]:
            self.reply=dict(files=files,nextPageToken=token)
            with self.subTest(count=len(files),token=token),self.assertRaises(c.Refused):self.recover()
            self.assertEqual(self.writes,[]);self.assertEqual(self.meter.used['provider_gets'],0)

    def test_hash_false_normalization_or_owner_failure_refuses_before_json(self):
        self.store['fixture-norm-123']=self.norm+b'corrupt'
        with self.assertRaisesRegex(c.Refused,'EXTERNAL_ORPHAN_HASH'):self.recover()
        self.store['fixture-norm-123']=cap.gzip.compress(b'{}\n',mtime=0)
        self.listing[1].update(name=c.digest(self.store['fixture-norm-123'])+'.jsonl.gz',size=str(len(self.store['fixture-norm-123'])))
        with self.assertRaisesRegex(c.Refused,'RESUME_NORMALIZED_MISMATCH'):self.recover()
        self.assertEqual(self.writes,[])

    def test_wrong_original_source_scope_or_clock_never_becomes_reusable(self):
        for field,value in [('source_sha','8'*40),('symbols',['VCYT']),('start','2017-01-01')]:
            manifest=dict(self.manifest,**{field:value})
            raw=cap.zip_bytes(dict(self.members,**{'capture.json':c.encoded(manifest)}));self.store['fixture-raw-123']=raw
            self.listing[0].update(name=c.digest(raw)+'.zip',size=str(len(raw)))
            with patch.dict(c.DRIVE_RECOVERY,dict(c.DRIVE_RECOVERY,raw_bytes=len(raw))),self.subTest(field=field),self.assertRaises(c.Refused):self.recover()
            self.assertEqual(self.writes,[])

    def test_parent_or_permission_refusal_and_json_failure_stop_before_provider(self):
        with patch.object(self.drive,'check',side_effect=c.Refused('OFFLINE_OWNER_REFUSAL')),self.assertRaisesRegex(c.Refused,'OFFLINE_OWNER_REFUSAL'):
            self.recover()
        self.assertEqual(self.writes,[])
        with patch.object(self.drive,'write',side_effect=c.Refused('HTTP_ERROR')),self.assertRaisesRegex(c.Refused,'HTTP_ERROR'):
            self.recover()
        self.assertEqual(self.meter.examined,160);self.assertEqual(self.meter.used['provider_gets'],0)

    def test_original_asset_clock_and_parent_mismatch_stop_before_json(self):
        manifest=copy.deepcopy(self.manifest);manifest['asset_precheck'][0]['collected_at_utc']='2030-01-01T00:00:00Z'
        raw=cap.zip_bytes(dict(self.members,**{'capture.json':c.encoded(manifest)}));self.store['fixture-raw-123']=raw
        self.listing[0].update(name=c.digest(raw)+'.zip',size=str(len(raw)))
        with patch.dict(c.DRIVE_RECOVERY,dict(c.DRIVE_RECOVERY,raw_bytes=len(raw))),self.assertRaisesRegex(c.Refused,'EXTERNAL_ORPHAN_CLOCK'):
            self.recover()
        self.assertEqual(self.writes,[])


class MaterializationRevisionTests(unittest.TestCase):
    """Third transition, including the complete host and prior-epoch guards."""
    def setUp(self):
        d=DriveRevisionTests();d.setUp();self.addCleanup(d.doCleanups)
        self.d=d;self.n=d.n;self.b=d.b
        run,value=d.completion(160);run['conclusion']='failure'
        value.pop('drive_orphan_reuse');value.update(status='BLOCKED',reason='EXTERNAL_ORPHAN_MISSING_OR_AMBIGUOUS')
        value['usage']=dict(provider_gets=0,drive_requests=4,drive_bytes=263644,storage_bytes=0)
        self.pairs=d.pairs+[(run,value)]
        with patch.object(c,'external_proof',side_effect=lambda a:self.n.proofs[c.validate_authorization(a)]):
            j=c.external_journal(self.b.cohort_state,d.new,d.proof)
            j.append('EXTERNAL_DRIVE_RECOVERY_BOUND',**j.drive_revision)
            family=c.external_family_registry(self.b.state,d.new,self.b.cohort_state)
            self.n.append_pair(j,family,run,value,d.proof);j.close();family.close()
        spec=dict(c.MATERIALIZATION_RECOVERY,prior_auth=d.h,master=d.new['expected_master'],run_id=13,
            receipt_sha256=c.digest(c.encoded(value)),checkpoint_sha256=value['checkpoint_sha256'],
            cohort_event_sha256=c.digest((self.b.cohort_state/'000027.json').read_bytes()),
            family_event_sha256=c.digest((self.n.family_path/'000025.json').read_bytes()))
        p=patch.dict(c.MATERIALIZATION_RECOVERY,spec,clear=True);p.start();self.addCleanup(p.stop)
        self.new=copy.deepcopy(d.new);ex=self.new['external_cohort'];old_ref=ex['proof_reference']
        ex['proof_reference']=self.b.reference+'999999';self.new.update(schema='r1000-sip-external-cohort-authorization-v4',
            expected_master='6'*40,account_permission_reference=ex['proof_reference'])
        ex['materialization_recovery']=dict(prior_capture_source=dict(expected_master=d.new['expected_master'],
            code_pins=d.new['code_pins'],proof_reference=old_ref),failed_run_id=13,
            failed_receipt_sha256=spec['receipt_sha256'],checkpoint_sha256=spec['checkpoint_sha256'],examined=160)
        self.h=c.validate_authorization(self.new);self.proof=self.b.proof(self.new);self.n.proofs[self.h]=self.proof

    def history(self,extra=(),**kwargs):
        return self.n.history(self.pairs+list(extra),auth_value=self.new,**kwargs)

    def completion(self):
        run,value=self.n.next_pair(160,169,14,self.pairs);run['head_sha']=self.new['expected_master']
        value.update(auth_sha256=self.h,source_sha=self.new['expected_master'],recovery_run=13,
            external_proof_sha256=self.proof['proof_sha256'],account_permission_record_sha256=self.proof['proof_sha256'],
            account_permission_reference_sha256=c.digest(self.new['external_cohort']['proof_reference'].encode()))
        value['orphan_inventory']=dict(schema='a1-bounded-orphan-inventory-v1',observed_at_utc=c.utc().isoformat(),
            window=[c.DRIVE_RECOVERY['window_start'],c.DRIVE_RECOVERY['window_end']],files_count=1,has_more=False,
            entries=[dict(kind='RAW',sha256='b'*64,bytes=505475,created_at_utc=c.DRIVE_RECOVERY['window_end'])])
        reuse=copy.deepcopy(self.d.completion()[1]['drive_orphan_reuse'])
        reuse.update(failed_run_id=13,derivation_source_sha=self.new['expected_master'],derivation_run_id=14,
            derivation_auth_sha256=self.h,external_proof_sha256=self.proof['proof_sha256'],derived_at_utc=c.utc().isoformat())
        reuse['materialization']=dict(capture_failed_run_id=12,rows_sha256='d'*64,codec='EXISTING_GZIP_VERIFIED',
            mode='EXISTING_VERIFIED',created_at_utc='2026-10-16T00:00:00Z',lookup_observed_at_utc=c.utc().isoformat(),
            inventory_sha256=c.digest(c.encoded(value['orphan_inventory'])),original_create_outcome='UNKNOWN')
        reuse['derived_at_utc']=c.utc().isoformat();value['drive_orphan_reuse']=reuse
        return run,value

    def test_four_exact_versions_keep_all_thirteen_costs_and_terminal_failure(self):
        self.assertEqual(c.external_previous(self.new),self.d.new)
        self.assertEqual(c.external_variants(self.new),[self.n.old,self.n.new,self.d.new,self.new])
        observed=self.history(recovery_run=13);self.assertEqual(len(observed['runs']),13)
        self.assertEqual(observed['used']['provider_gets'],self.d.history(recovery_run=12)['used']['provider_gets'])
        self.assertEqual(observed['used']['drive_requests'],self.d.history(recovery_run=12)['used']['drive_requests']+4)
        self.assertEqual(self.history([self.completion()])['examined'],169)
        run,value=self.completion();run['conclusion']='failure'
        value.update(status='BLOCKED',reason='EXTERNAL_ORPHAN_ROLES',examined_after=160,
            checkpoint_sha256=value['parent_checkpoint_sha256'],rows_verified=0,
            new_states=dict(VALID_COLLECTED=0,VERIFIED_NO_DATA=0,QUARANTINED=0));value.pop('drive_orphan_reuse')
        with self.assertRaisesRegex(c.Refused,'CAMPAIGN_EXTERNAL_FAILURE_STOP'):self.history([(run,value)])
        self.assertIsNone(self.history([(run,value)],allow_stopped=True)['recovery_required'])
        for field in ('failed_run_id','failed_receipt_sha256','checkpoint_sha256','examined'):
            bad=copy.deepcopy(self.new);v=bad['external_cohort']['materialization_recovery'][field]
            bad['external_cohort']['materialization_recovery'][field]=v+1 if type(v)is int else '0'*64
            with self.subTest(field=field),self.assertRaises(c.Refused):c.validate_authorization(bad)

    def close_host(self):
        before=self.history(recovery_run=13);pair=self.completion();after=self.history([pair]);posted=[]
        ref=dict(file_id='fixture-new-checkpoint-169',sha256=pair[1]['checkpoint_sha256'],bytes=100)
        def operation(args,**kwargs):
            if args[1:3]==['workflow','run']:posted.append(json.loads(kwargs['input']))
            else:self.assertEqual(args[1:3],['run','watch'])
            return SimpleNamespace(returncode=0)
        with self.n.host_context(before),patch.object(c,'external_history',side_effect=lambda *a,**k:after if posted else before), \
             patch.object(c,'campaign_runs',side_effect=lambda *a:after['runs'] if posted else before['runs']), \
             patch.object(c.os,'urandom',side_effect=lambda n:bytes.fromhex('e'*24) if n==12 else b'\x01'*n), \
             patch.object(c.subprocess,'run',side_effect=operation),patch.object(c,'checkpoint_from_log',return_value=ref):
            result=c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,self.b.old.local.bundle_path,13,1)
        self.assertEqual(result['examined'],169);self.assertEqual(len(posted),1)
        self.assertEqual(json.loads(posted[0]['campaign_control'])['recovery_run'],13)
        self.assertEqual(c.bounded_json(self.b.cohort_state/'000031.json')['receipt'],pair[1])
        self.assertEqual(c.bounded_json(self.n.family_path/'000028.json')['kind'],'SETTLED')
        self.closed_pair=pair
        return after,ref

    def test_active_v4_host_closure_restart_import_and_family_repair_no_second_post(self):
        after,ref=self.close_host()
        with self.n.host_context(after),patch.object(c.subprocess,'run',side_effect=AssertionError('No second POST')), \
             patch.object(c,'checkpoint_from_log',return_value=ref):
            self.assertEqual(c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,
                self.b.old.local.bundle_path,None,1)['examined'],169)
            for path in (self.b.cohort_state/'000031.json',self.n.family_path/'000028.json'):
                path.unlink()
            with self.assertRaisesRegex(c.Refused,'EXTERNAL_RECOVERY_BOUNDARY'):
                c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,self.b.old.local.bundle_path,None,2)
            self.assertEqual(c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,
                self.b.old.local.bundle_path,None,1)['examined'],169)
            (self.n.family_path/'000028.json').unlink()
            self.assertEqual(c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,
                self.b.old.local.bundle_path,None,1)['examined'],169)

    def test_wrong_active_or_historical_proof_and_max1_uncertain_post(self):
        with patch.object(c,'external_proof',side_effect=lambda a:self.n.proofs[c.validate_authorization(a)]):
            j=c.external_journal(self.b.cohort_state,self.new,self.proof)
            j.append('EXTERNAL_MATERIALIZATION_BOUND',**j.material_revision);j.close()
            with self.assertRaisesRegex(c.Refused,'EXTERNAL_MATERIAL_BINDING'):
                c.external_journal(self.b.cohort_state,self.new,self.d.proof)
            saved=self.n.proofs[self.d.h];self.n.proofs[self.d.h]=self.proof
            with self.assertRaisesRegex(c.Refused,'EXTERNAL_DRIVE_BINDING'):
                c.external_journal(self.b.cohort_state,self.new,self.proof)
            self.n.proofs[self.d.h]=saved
        observed=self.history(recovery_run=13);posted=[]
        with self.n.host_context(observed),patch.object(c.subprocess,'run',side_effect=AssertionError('No POST')),self.assertRaises(c.Refused):
            c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,self.b.old.local.bundle_path,13,2)
        def uncertain(*a,**kw):posted.append(1);return SimpleNamespace(returncode=1)
        with self.n.host_context(observed),patch.object(c.subprocess,'run',side_effect=uncertain),self.assertRaisesRegex(c.Refused,'CAMPAIGN_DISPATCH_UNCERTAIN'):
            c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,self.b.old.local.bundle_path,13,1)
        with self.n.host_context(observed),patch.object(c.subprocess,'run',side_effect=AssertionError('No repeat')),self.assertRaises(c.Refused):
            c.external_host(self.new,self.b.cohort_state,self.b.input,self.b.state,self.b.old.local.bundle_path,13,1)
        self.assertEqual(posted,[1])

    def test_prior500_local_guard_requires_all_old_proofs_and_preserves_control_cap(self):
        self.close_host();later=copy.deepcopy(self.n.old);ex=later['external_cohort']
        # Same1749-byte shape as the frozen incremental417 input; synthetic
        # identities only. Do not raise the15KB cap to accommodate the wrapper.
        raw='ticker\n'+''.join('Q'+chr(65+i//26)+chr(65+i%26)+('X' if i>=343 else '')+'\n' for i in range(417))
        self.assertEqual(len(raw.encode()),1749)
        ex.update(input_csv=raw,prior_epochs=[self.new],proof_reference=self.b.reference+'9999999')
        ex['scope']=dict(ex['scope'],namespace='fixture-marketcap-500',input_sha256=c.digest(raw.encode()))
        later.update(expected_master=self.new['expected_master'],code_pins=self.new['code_pins'],account_permission_reference=ex['proof_reference'])
        h=c.validate_authorization(later);self.n.proofs[h]=self.b.proof(later)
        observed=self.n.history(self.pairs+[self.closed_pair],auth_value=later)
        with patch.object(c,'external_proof',return_value=self.n.old_proof):
            family=c.external_family_registry(self.b.state,later,self.b.root/'external-cohort-fixture-marketcap-500')
        try:
            with patch.object(c,'external_proof',side_effect=AssertionError('No remote read in final guard')):
                c.verify_external_prior_journals(family,later,observed)
                for old in (self.n.new_hash,self.d.h,self.h):
                    missing=dict(observed,epoch_proofs={k:v for k,v in observed['epoch_proofs'].items() if k!=old})
                    with self.subTest(proof=old),self.assertRaises(c.Refused):c.verify_external_prior_journals(family,later,missing)
        finally:family.close()
        self.assertLessEqual(len(c.encoded(dict(authorization=later,nonce=c.PREFIX+'a'*24,recovery_run=None,
            preflight_only=False,external_binding=self.n.proofs[h]))),16384)
        self.assertLessEqual(len(c.encoded(c.external_proof_record(self.new))),4096)

    def test_v4_worker_requires_reuse_closure_before_only_the_last_five(self):
        from contextlib import ExitStack
        observed=self.history(recovery_run=13);run,_=self.completion();run.update(status='in_progress',conclusion=None)
        observed['runs']=observed['runs']+[run];meters=[];opener=Opener(body=b'{}');original=c.RuntimeMeter
        args=SimpleNamespace(private_root_folder_id=self.new['private_root_folder_id'],private_data_folder_id=self.new['private_data_folder_id'],
            start=self.new['start'],end=self.new['end'],max_new_symbols=9,resume_sha256=c.MATERIALIZATION_RECOVERY['checkpoint_sha256'],resume_file_id='fixture-parent-160')
        control=dict(authorization=self.new,nonce=run['display_title'][7:],recovery_run=13,preflight_only=False,external_binding=self.proof)
        def create(*a,**k):
            meter=original(*a,opener=opener,**k);meters.append(meter);return meter
        def recover(drive,a,auth_value,meter,**kwargs):
            self.assertEqual(kwargs,dict(materialize=True));self.assertEqual(meter.used['provider_gets'],0)
            meter.examined=164;meter.checkpoint_sha='b'*64;return dict(file_id='fixture-parent-164',sha256='b'*64)
        def collect(a,**k):
            k['drive_factory'](a.private_root_folder_id,str(self.b.root))
            self.assertEqual(a.max_new_symbols,5);self.assertEqual(k['expected_examined'],164)
            for symbol in cap.external_cohort(self.new['external_cohort']['input_csv'].encode())[164:169]:
                k['get']('https://paper-api.alpaca.markets/v2/assets/'+symbol)
            meters[-1].examined=169;meters[-1].checkpoint_sha='c'*64
            return dict(checkpoint=dict(sha256='c'*64))
        def context():
            stack=ExitStack();stack.enter_context(patch.dict(os.environ,dict(GITHUB_SHA=self.new['expected_master'],
                GITHUB_RUN_ID=str(run['id']),INPUT_CAMPAIGN_NONCE=control['nonce'],ALPACA_API_KEY='fixture-key',ALPACA_API_SECRET='fixture-secret')))
            for name,value in [('verify_worker_source',None),('external_history',observed),('external_proof',self.proof),
                               ('campaign_runs',observed['runs']),('worker_deadline',c.utc()+timedelta(seconds=60))]:
                stack.enter_context(patch.object(c,name,return_value=value))
            stack.enter_context(patch.object(c,'RuntimeMeter',side_effect=create))
            stack.enter_context(patch.object(drive_module,'OwnerDrive',return_value=SimpleNamespace(owner=self.new['owner_permission_id'],free=3*1024**3)))
            stack.enter_context(patch.object(cap,'_collect',side_effect=collect));return stack
        with context(),patch.object(c,'recover_drive_orphan',side_effect=c.Refused('CP164_READBACK_FAILED')),self.assertRaises(c.Refused):
            c.external_worker(args,control,self.b.root/'v4-refusal-meter')
        self.assertEqual(opener.calls,0);self.assertEqual(meters[-1].examined,160)
        with context(),patch.object(c,'recover_drive_orphan',side_effect=recover):
            c.external_worker(args,control,self.b.root/'v4-complete-meter')
        self.assertEqual(opener.calls,5);self.assertEqual(args.max_new_symbols,9)

    def test_existing_mode_cannot_claim_new_encoder_provenance(self):
        run,value=self.completion()
        value['drive_orphan_reuse']['materialization']['codec']='GZIP_FILENAME_EMPTY_MTIME0_LEVEL9'
        with self.assertRaisesRegex(c.Refused,'EXTERNAL_MATERIAL_PROVENANCE'):self.history([(run,value)])

    def test_reuse_clocks_require_actual_values_without_now_fallback(self):
        for missing in ('derived','observed','created','lookup','all'):
            run,value=self.completion();reuse=value['drive_orphan_reuse'];material=reuse['materialization']
            if missing in ('derived','all'):reuse['derived_at_utc']=None
            if missing in ('observed','all'):value['orphan_inventory']['observed_at_utc']=None
            if missing in ('created','all'):material['created_at_utc']=None
            if missing in ('lookup','all'):material['lookup_observed_at_utc']=None
            material['inventory_sha256']=c.digest(c.encoded(value['orphan_inventory']))
            with self.subTest(missing=missing),self.assertRaises(c.Refused):self.history([(run,value)])

    def test_normalized_inventory_binds_existing_mode_and_creation_clock(self):
        for mutation in ('none','created','derived'):
            run,value=self.completion();reuse=value['drive_orphan_reuse'];material=reuse['materialization']
            inventory=value['orphan_inventory'];inventory['entries'].append(dict(inventory['entries'][0],
                kind='NORMALIZED',sha256=reuse['normalized_sha256'],bytes=100))
            material['created_at_utc']=inventory['entries'][1]['created_at_utc']
            inventory['files_count']=2;material['inventory_sha256']=c.digest(c.encoded(inventory))
            if mutation=='created':material['created_at_utc']=(c.utc(material['created_at_utc'])+timedelta(seconds=1)).isoformat()
            elif mutation=='derived':
                material.update(mode='DERIVED_NEW',codec='GZIP_FILENAME_EMPTY_MTIME0_LEVEL9',
                    created_at_utc=inventory['observed_at_utc'],lookup_observed_at_utc=reuse['derived_at_utc'])
            if mutation=='none':self.assertEqual(self.history([(run,value)])['examined'],169)
            else:
                with self.subTest(mutation=mutation),self.assertRaisesRegex(c.Refused,'EXTERNAL_MATERIAL_PROVENANCE'):
                    self.history([(run,value)])

    def test_existing_lookup_cannot_predate_inventory_observation(self):
        for earlier_derivation in (False,True):
            run,value=self.completion();reuse=value['drive_orphan_reuse']
            reuse['materialization']['lookup_observed_at_utc']=c.DRIVE_RECOVERY['window_end']
            if earlier_derivation:reuse['derived_at_utc']=c.DRIVE_RECOVERY['window_end']
            with self.subTest(earlier_derivation=earlier_derivation),self.assertRaisesRegex(c.Refused,'EXTERNAL_MATERIAL_PROVENANCE'):
                self.history([(run,value)])

    def test_noninventoried_existing_object_cannot_have_an_in_window_creation(self):
        for clock in (c.DRIVE_RECOVERY['window_start'],'2026-10-17T12:25:00Z',c.DRIVE_RECOVERY['window_end']):
            run,value=self.completion();value['drive_orphan_reuse']['materialization']['created_at_utc']=clock
            with self.subTest(clock=clock),self.assertRaisesRegex(c.Refused,'EXTERNAL_MATERIAL_PROVENANCE'):
                self.history([(run,value)])

    def test_recovery_observations_cannot_predate_the_canonical_run(self):
        run,value=self.completion();run['created_at']=c.utc().isoformat()
        value['orphan_inventory']['observed_at_utc']=c.DRIVE_RECOVERY['window_end']
        reuse=value['drive_orphan_reuse'];reuse['derived_at_utc']=c.DRIVE_RECOVERY['window_end']
        reuse['materialization'].update(lookup_observed_at_utc=c.DRIVE_RECOVERY['window_end'],
            inventory_sha256=c.digest(c.encoded(value['orphan_inventory'])))
        with self.assertRaisesRegex(c.Refused,'EXTERNAL_MATERIAL_RUN_CLOCK'):self.history([(run,value)])

    def test_successful_receipts_must_close_the_same_bounded_inventory(self):
        for mutation in ('pagination','count','missing_raw','two_norm','raw_hash','raw_bytes','norm_hash','clock'):
            run,value=self.completion();inventory=value['orphan_inventory'];entries=inventory['entries']
            if mutation=='pagination':inventory['has_more']=True
            elif mutation=='count':inventory['files_count']=2
            elif mutation=='missing_raw':entries[0]['kind']='JSON'
            elif mutation=='two_norm':entries.extend([dict(entries[0],kind='NORMALIZED')]*2);inventory['files_count']=3
            elif mutation=='raw_hash':entries[0]['sha256']='f'*64
            elif mutation=='raw_bytes':entries[0]['bytes']=1
            elif mutation=='norm_hash':entries.append(dict(entries[0],kind='NORMALIZED'));inventory['files_count']=2
            else:entries[0]['created_at_utc']=(c.utc(c.DRIVE_RECOVERY['window_end'])+timedelta(seconds=1)).isoformat()
            c.verify_orphan_inventory(inventory)  # Valid diagnostic shape, not successful evidence.
            value['drive_orphan_reuse']['materialization']['inventory_sha256']=c.digest(c.encoded(inventory))
            with self.subTest(mutation=mutation),self.assertRaisesRegex(c.Refused,'EXTERNAL_ORPHAN_INVENTORY_CLOSURE'):
                self.history([(run,value)])


class OrphanMaterializationTests(unittest.TestCase):
    def setUp(self):
        f=DriveOrphanReuseTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f
        f.auth['external_cohort']['materialization_recovery']={}
        f.meter.identity['recovery_run']=c.MATERIALIZATION_RECOVERY['run_id']
        self.clock={k:'2026-10-17T12:25:00Z' for k in f.store};test=self
        class Drive(type(f.drive)):
            def request(self,url,**kwargs):
                q=parse_qs(urlsplit(url).query)['q'][0]
                if 'createdTime' in q:return c.encoded(f.reply)
                name=q.split("name = '")[1].split("'")[0]
                return c.encoded(dict(files=[dict(id=k,name=name,size=str(len(v)),parents=[f.args.private_data_folder_id],
                    createdTime=test.clock[k]) for k,v in f.store.items() if c.digest(v)+f.suffix[k]==name]))
            def write(self,folder,raw,extension):
                test.assertIn(extension,('.jsonl.gz','.json'));f.writes.append(extension)
                fid='fixture-new-'+str(len(f.writes));f.store[fid]=raw;f.suffix[fid]=extension;test.clock[fid]=c.utc().isoformat()
                return dict(file_id=fid,sha256=c.digest(raw),bytes=len(raw))
        f.drive=Drive()

    def recover(self):
        f=self.f
        with patch.dict(os.environ,{'GITHUB_SHA':f.auth['expected_master']}), \
             patch.object(cap,'resume_state',return_value=(f.names[:160],f.names[:160],[],f.parent)):
            return c.recover_drive_orphan(f.drive,f.args,f.auth,f.meter,materialize=True)

    def test_raw_only_creates_one_explicit_normalized_derivation_and_keeps_original(self):
        f=self.f;f.reply=dict(files=f.listing[:1]);f.store.pop('fixture-norm-123');before=dict(f.store)
        ref=self.recover();self.assertEqual(f.writes,['.jsonl.gz','.json','.json'])
        self.assertEqual(f.meter.examined,164);self.assertEqual(f.meter.used['provider_gets'],0)
        self.assertEqual(before,{k:f.store[k] for k in before})
        reuse=c.decode(f.store[ref['file_id']])['recovered_from'];self.assertEqual(reuse['materialization']['mode'],'DERIVED_NEW')
        self.assertEqual(reuse['materialization']['original_create_outcome'],'UNKNOWN')
        self.assertNotIn('fixture-',c.encoded(f.meter.identity['orphan_inventory']).decode())

    def test_different_gzip_headers_reuse_by_rows_without_normalized_upload(self):
        f=self.f;f.store['fixture-norm-123']=cap.gzip.compress(cap.gzip.decompress(f.norm),mtime=123)
        f.listing[1].update(name=c.digest(f.store['fixture-norm-123'])+'.jsonl.gz',size=str(len(f.store['fixture-norm-123'])))
        ref=self.recover();self.assertEqual(f.writes,['.json','.json'])
        reuse=c.decode(f.store[ref['file_id']])['recovered_from']
        self.assertEqual(reuse['materialization']['rows_sha256'],c.digest(cap.gzip.decompress(f.norm)))
        self.assertEqual(reuse['normalized_sha256'],c.digest(f.store['fixture-norm-123']))

    def test_exact_content_lookup_outside_window_and_unrelated_json_are_bounded(self):
        f=self.f;f.reply=dict(files=f.listing[:1]);self.clock['fixture-norm-123']=c.utc().isoformat()
        other=dict(f.listing[0],id='fixture-other-json',name='f'*64+'.json');f.reply['files'].append(other)
        self.recover();self.assertEqual(f.writes,['.json','.json'])
        self.assertEqual(f.meter.identity['orphan_inventory']['files_count'],2)
        self.assertEqual([x['kind'] for x in f.meter.identity['orphan_inventory']['entries']],['RAW','JSON'])

    def test_exact_name_older_normalized_object_retains_its_actual_creation_clock(self):
        f=self.f;f.reply=dict(files=f.listing[:1]);self.clock['fixture-norm-123']='2026-10-16T00:00:00Z'
        ref=self.recover();reuse=c.decode(f.store[ref['file_id']])['recovered_from']
        self.assertEqual(f.writes,['.json','.json']);self.assertEqual(f.meter.examined,164)
        self.assertEqual(reuse['materialization']['mode'],'EXISTING_VERIFIED')
        self.assertEqual(reuse['materialization']['created_at_utc'],'2026-10-16T00:00:00Z')
        self.assertEqual(f.meter.used['provider_gets'],0)

    def test_exact_name_in_window_object_missing_from_inventory_refuses(self):
        f=self.f;f.reply=dict(files=f.listing[:1])
        with self.assertRaisesRegex(c.Refused,'EXTERNAL_MATERIAL_PROVENANCE'):self.recover()
        self.assertEqual(f.writes,[]);self.assertEqual(f.meter.examined,160)
        self.assertEqual(f.meter.used['provider_gets'],0)

    def test_older_raw_is_still_outside_the_sealed_original_window(self):
        f=self.f;f.listing[0]['createdTime']='2026-10-16T00:00:00Z'
        with patch.object(f.drive,'read',side_effect=AssertionError('No bytes before original-window closure')), \
             self.assertRaisesRegex(c.Refused,'EXTERNAL_ORPHAN_LISTING'):
            self.recover()
        self.assertEqual(f.writes,[]);self.assertEqual(f.meter.examined,160)

    def test_missing_duplicate_paginated_and_unknown_names_record_safe_diagnostic_no_write(self):
        f=self.f
        for files,token in [([],None),(f.listing*2,None),(f.listing,'more'),([dict(f.listing[0],name='PRIVATE_SECRET_URL')],None)]:
            f.reply=dict(files=files,nextPageToken=token)
            with self.subTest(count=len(files),token=token),self.assertRaises(c.Refused):self.recover()
            evidence=f.meter.identity['orphan_inventory'];c.verify_orphan_inventory(evidence)
            self.assertNotIn('PRIVATE_SECRET_URL',c.encoded(evidence).decode());self.assertEqual(f.writes,[])

    def test_invalid_raw_owner_rows_or_full_parent_refuse_before_normalization_write(self):
        f=self.f
        with patch.object(f.drive,'check',side_effect=c.Refused('OWNER_REFUSAL')),self.assertRaises(c.Refused):self.recover()
        original=f.store['fixture-raw-123'];f.store['fixture-raw-123']=original+b'bad'
        with self.assertRaisesRegex(c.Refused,'EXTERNAL_ORPHAN_HASH'):self.recover()
        f.store['fixture-raw-123']=original
        with patch.object(cap,'resume_state',side_effect=c.Refused('FULL_PARENT_INVALID')):
            # recover() normally supplies the valid fixture parent itself.
            with patch.dict(os.environ,{'GITHUB_SHA':f.auth['expected_master']}),self.assertRaisesRegex(c.Refused,'FULL_PARENT_INVALID'):
                c.recover_drive_orphan(f.drive,f.args,f.auth,f.meter,materialize=True)
        f.store['fixture-norm-123']=cap.gzip.compress(b'{}\n',mtime=0)
        f.listing[1].update(name=c.digest(f.store['fixture-norm-123'])+'.jsonl.gz',size=str(len(f.store['fixture-norm-123'])))
        with self.assertRaisesRegex(c.Refused,'RESUME_NORMALIZED_MISMATCH'):self.recover()
        self.assertEqual(f.writes,[]);self.assertEqual(f.meter.examined,160)

    def test_unknown_create_stops_once_and_checkpoint_readback_failure_never_advances(self):
        f=self.f;f.reply=dict(files=f.listing[:1]);f.store.pop('fixture-norm-123');attempts=[]
        def uncertain(*a,**k):attempts.append(1);raise c.Refused('HTTP_ERROR')
        with patch.object(f.drive,'write',side_effect=uncertain),self.assertRaisesRegex(c.Refused,'HTTP_ERROR'):self.recover()
        self.assertEqual(attempts,[1]);self.assertEqual(f.meter.examined,160)
        write=f.drive.write
        def tamper(folder,raw,ext):
            ref=write(folder,raw,ext)
            if ext=='.json' and c.decode(raw).get('examined'):
                f.store[ref['file_id']]=b'{}'
            return ref
        with patch.object(f.drive,'write',side_effect=tamper),self.assertRaises(c.Refused):self.recover()
        self.assertEqual(f.meter.examined,160);self.assertEqual(f.meter.used['provider_gets'],0)


class NativeRead39085031884Tests(unittest.TestCase):
    """Synthetic runtime integration. No original account/price/network proof."""
    def setUp(self):
        self.base=ExternalCohortTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.a=self.base.new
        self.addCleanup(patch.stopall)
        patch.object(c,'NATIVE_READ_AUTH',c.validate_authorization(self.a)).start()
        self.control=dict(schema='a1-native-drive-read-39085031884-v1',task_key=c.NATIVE_READ_TASK,
            authorization=self.a,expected_master='4'*40,nonce=c.PREFIX+'a'*24,
            pending_external_read_accounting=dict(basis='VERIFIED_TRANSPORT_ACCOUNTING',receipt_sha256='e'*64,
                reference=self.base.reference,usage=dict(provider_gets=0,storage_bytes=0,drive_requests=6,drive_bytes=1000)))
        self.names=['ZZZ%03d'%i for i in range(417)]
        self.scope=dict(task_key='R1000-NATIVE-SYNTHETIC',namespace='fixture-native',input_sha256='f'*64)
        self.raw=c.encoded(dict(examined=self.names[:76],cohort_scope=self.scope)).ljust(2304,b' ')
        self.assertEqual(len(self.raw),2304)
        patch.object(c,'NATIVE_READ_CP',c.digest(self.raw)).start()
        self.read_auth=dict(private_root_folder_id='fixture-root-123',private_data_folder_id='fixture-data-123',
            external_cohort=dict(input_csv='ticker\n'+'\n'.join(self.names)+'\n',scope=self.scope))
        patch.dict(c.CONTINUATION['bindings'],owner_sha256=c.digest(b'fixture-owner')).start()
        self.env=dict(GITHUB_REPOSITORY=c.REPO,GITHUB_REF='refs/heads/master',GITHUB_SHA='4'*40,
            GITHUB_RUN_ID='12345',INPUT_NATIVE_READ_ONLY='true',INPUT_CAMPAIGN_NONCE=self.control['nonce'],
            A1_PRIVATE_RESEARCH_AUTHORIZED='true',ALPACA_NONCOMMERCIAL_ACKNOWLEDGED='true',
            MACRO_DRIVE_CONFIG='[gdrive]\ntype=drive\ntoken='+json.dumps(dict(access_token='fixture-access',
                refresh_token='fixture-refresh',expiry='2030-01-01T00:00:00Z'))+'\n')

    def meter(self,server,allowance=None):
        return c.NativeReadMeter(allowance or c.NATIVE_READ_ALLOWANCE,self.base.root/'native-meter',
            (c.utc()+timedelta(seconds=30)).isoformat(),identity(),opener=server,limits=c.CONTINUED_LIMITS,
            root_id='fixture-root-123',folder_id='fixture-data-123')

    def server(self,mode=None):
        case=self
        class NativeServer(Server):
            def __init__(self):
                super().__init__();self.calls=0
                self.objects[c.NATIVE_READ_CP_ID]=(dict(name=c.NATIVE_READ_CP+'.json',parents=['fixture-data-123']),case.raw)
            def open(self,request,**kwargs):
                self.calls+=1;parts=urlsplit(request.full_url);q=parse_qs(parts.query)
                if parts.path=='/drive/v3/files':
                    self.requests.append(request.full_url)
                    positive=q['q'][0].startswith('name = ')
                    item=dict(id=c.NATIVE_READ_CP_ID,name=c.NATIVE_READ_CP+'.json',parents=['fixture-data-123'],
                        size='2304',createdTime=c.NATIVE_READ_WINDOW[0])
                    if positive:
                        return Reply(c.encoded(dict(files=[] if mode=='missing-control' else [item,item] if mode=='duplicate-control' else [item])))
                    if mode=='paged':return Reply(c.encoded(dict(files=[],nextPageToken='fixture-page')))
                    if mode=='duplicate':return Reply(c.encoded(dict(files=[item,item])))
                    if mode=='wrong-time':item['createdTime']='2026-10-17T00:00:00Z'
                    if mode=='wrong-parent':item['parents']=['fixture-other-123']
                    return Reply(c.encoded(dict(files=[item])))
                return super().open(request,**kwargs)
        return NativeServer()

    def read_objects(self,server):
        meter=self.meter(server)
        with patch.dict(os.environ,self.env,clear=True):
            drive=drive_module.OwnerDrive('fixture-root-123',str(self.base.root),meter=meter)
            result=c.native_read_objects(drive,self.read_auth,meter)
        meter.finish('COMPLETE')
        return result,c.bounded_json(meter.journal),meter

    def test_actual_owner_drive_and_runtime_meter_readback_only(self):
        server=self.server();result,value,meter=self.read_objects(server)
        self.assertTrue(result['positive_control_verified']);self.assertEqual(result['candidate_count'],0)
        self.assertFalse(result['absence_proven']);self.assertFalse(value['capture_allowed'])
        self.assertEqual(value['schema'],'a1-native-drive-read-meter-v1')
        self.assertEqual(value['usage']['drive_requests'],7)
        self.assertEqual(value['usage']['provider_gets'],0);self.assertEqual(value['usage']['storage_bytes'],0)
        self.assertGreater(value['usage']['drive_bytes'],7*65536)
        self.assertNotIn('fixture-access',json.dumps(value));self.assertNotIn(c.NATIVE_READ_CP_ID,json.dumps(value))

    def test_empty_positive_control_never_certifies_absence(self):
        for mode in ('missing-control','duplicate-control','paged','duplicate','wrong-time','wrong-parent'):
            with self.subTest(mode=mode),self.assertRaises(c.Refused):self.read_objects(self.server(mode))

    def test_wrong_owner_stops_before_checkpoint_or_listing(self):
        with patch.dict(c.CONTINUATION['bindings'],owner_sha256='0'*64),self.assertRaisesRegex(c.Refused,'NATIVE_READ_OWNER'):
            self.read_objects(self.server())

    def test_wrong_checkpoint_bytes_stop_before_list(self):
        server=self.server();server.objects[c.NATIVE_READ_CP_ID]=(server.objects[c.NATIVE_READ_CP_ID][0],b'{}')
        with self.assertRaisesRegex(c.Refused,'RESUME_OBJECT_HASH'):self.read_objects(server)
        self.assertFalse(any(urlsplit(u).path=='/drive/v3/files' for u in server.requests))

    def test_provider_create_patch_delete_and_scope_escape_never_open(self):
        server=self.server();meter=self.meter(server)
        for url,method in [('https://data.alpaca.markets/v2/stocks/bars','GET'),
                ('https://www.googleapis.com/upload/drive/v3/files','POST'),
                ('https://www.googleapis.com/drive/v3/files/fixture-data-123','PATCH'),
                ('https://www.googleapis.com/drive/v3/files/fixture-data-123','DELETE'),
                ('https://www.googleapis.com/drive/v3/files/fixture-other-123','GET'),
                ('https://www.googleapis.com/drive/v3/files?q=all','GET')]:
            with self.subTest(url=url,method=method),self.assertRaisesRegex(c.Refused,'NATIVE_READ_ENDPOINT'):
                meter.perform(url,method=method)
        self.assertEqual(server.calls,0);self.assertEqual(meter.used,{k:0 for k in c.LIMITS})
        with self.assertRaisesRegex(c.Refused,'NATIVE_READ_WRITE_BLOCKED'):meter.reserve_storage(1)

    def test_exhausted_suballocation_refuses_before_open(self):
        server=self.server();meter=self.meter(server,dict(c.NATIVE_READ_ALLOWANCE,drive_requests=0))
        with self.assertRaisesRegex(c.Refused,'CAMPAIGN_BUDGET_DRIVE_REQUESTS'):
            meter.perform('https://www.googleapis.com/drive/v3/about?fields=user%28permissionId%29%2CstorageQuota')
        self.assertEqual(server.calls,0)

    def test_oauth_refresh_is_distinct_from_a_drive_write_and_metered(self):
        server=Opener(c.encoded(dict(access_token='fixture-new',token_type='Bearer',expires_in=3600)))
        meter=self.meter(server)
        body=b'grant_type=refresh_token&refresh_token=fixture-refresh'
        meter.perform('https://oauth2.googleapis.com/token',method='POST',body=body,limit=65536)
        self.assertEqual(meter.used['drive_requests'],1);self.assertEqual(meter.used['storage_bytes'],0)
        self.assertGreaterEqual(meter.used['drive_bytes'],len(body)+65536)

    def test_unknown_pending_cost_stops_worker_before_credentials(self):
        self.control['pending_external_read_accounting']=None
        p=self.base.root/'native-control';p.write_bytes(c.encoded(self.control))
        with patch.object(drive_module,'OwnerDrive',side_effect=AssertionError('NO_CREDENTIAL_READ')) as owner, \
             patch.object(c,'gh_json',side_effect=AssertionError('NO_REMOTE_CALL')), \
             self.assertRaisesRegex(c.Refused,'NATIVE_READ_PENDING_COST_UNSETTLED'):
            c.native_read_worker(p,self.base.root/'native-state')
        owner.assert_not_called()

    def test_control_rejects_wrong_auth_mode_zero_cost_and_expiry(self):
        for mutate in (lambda x:x.update(task_key='OTHER'),lambda x:x.update(nonce='bad'),
                lambda x:x['authorization'].update(credential_binding='0'*64),
                lambda x:x['pending_external_read_accounting']['usage'].update(drive_requests=0),
                lambda x:x['pending_external_read_accounting']['usage'].update(provider_gets=1)):
            changed=copy.deepcopy(self.control);mutate(changed)
            with self.subTest(mutate=mutate),self.assertRaises(c.Refused):c.native_read_control(changed)
        old=c.utc
        with patch.object(c,'utc',side_effect=lambda v=None:old(v) if v is not None else old(c.CONTINUATION['first'])+timedelta(hours=48)), \
             self.assertRaisesRegex(c.Refused,'CAMPAIGN_EXPIRED'):c.native_read_control(self.control)

    def test_read_run_exclusion_is_single_exact_current_context_only(self):
        current=dict(id=12345,run_attempt=1,status='in_progress',head_sha='4'*40,head_branch='master',event='workflow_dispatch',
            display_title='a1-sip '+self.control['nonce']+' native-read39085031884')
        runs=[dict(id=i) for i in range(16)]+[dict(id=39085031884),current]
        with patch.dict(os.environ,self.env,clear=True):
            self.assertEqual(c.native_read_prefix(runs,current),runs[:-1])
            for mutate in (lambda x:x.update(run_attempt=2),lambda x:x.update(head_sha='5'*40),
                    lambda x:x.update(status='completed'),lambda x:x.update(status='queued'),
                    lambda x:x.update(id=999),lambda x:x.update(display_title='a1-sip '+self.control['nonce'])):
                changed=copy.deepcopy(current);mutate(changed)
                with self.subTest(mutate=mutate),self.assertRaises(c.Refused):c.native_read_prefix(runs[:-1]+[changed],changed)
            with self.assertRaises(c.Refused):c.native_read_prefix(runs+[current],current)
            reused=copy.deepcopy(runs);reused[0]['display_title']='a1-sip '+self.control['nonce']
            with self.assertRaisesRegex(c.Refused,'NATIVE_READ_NONCE_REUSE'):c.native_read_prefix(reused,current)
        with patch.dict(os.environ,dict(self.env,INPUT_NATIVE_READ_ONLY='false'),clear=True),self.assertRaises(c.Refused):
            c.native_read_prefix(runs,current)

    def test_workflow_separates_secrets_modes_artifacts_and_timeout(self):
        text=(c.ROOT/'.github/workflows/alpaca_sip_private_backfill_v1.yml').read_text()
        read=text.split('      - name: Reconcile exact failed Drive POST',1)[1].split('      - name: Collect immutable',1)[0]
        self.assertIn("if: env.INPUT_NATIVE_READ_ONLY == 'true'",read)
        self.assertIn('secrets.RCLONE_CONFIG_GDRIVE',read)
        self.assertNotIn('secrets.ALPACA_API_KEY',read);self.assertNotIn('secrets.ALPACA_API_SECRET',read)
        self.assertIn('a1-native-drive-read-meter',read);self.assertIn('native_read_meter.json',read)
        self.assertIn("&& 5 || 120",text);self.assertIn("if: env.INPUT_NATIVE_READ_ONLY != 'true'",text)
        self.assertIn('native_read_route_control(value)',text)

    def test_accounting_proof_requires_owner_exact_record_and_clock(self):
        pending=self.control['pending_external_read_accounting']
        expected=dict(schema='a1-native-read-pending-accounting-v1',failed_run_id=39085031884,
            failed_meter_sha256=c.NATIVE_READ_METER,prior_auth_sha256=c.NATIVE_READ_AUTH,
            pending_observation_sha256='c0c9de188852ac7cea996ab506f27e514cfe976f4c467ec4e782303ed5ca7e2f',
            basis=pending['basis'],receipt_sha256=pending['receipt_sha256'],usage=pending['usage'])
        comment=dict(id=int(pending['reference'].rsplit('-',1)[1]),author_association='OWNER',
            issue_url=f'https://api.github.com/repos/{c.REPO}/issues/448',user=dict(type='User'),
            created_at='2026-10-18T01:07:37Z',updated_at='2026-10-18T01:07:37Z',
            body='A1_SIP_NATIVE_READ_ACCOUNTING '+json.dumps(expected))
        with patch.object(c,'gh_json',return_value=comment):self.assertRegex(c.native_read_pending_proof(pending),r'^[0-9a-f]{64}$')
        for mutate in (lambda x:x.update(author_association='MEMBER'),lambda x:x['user'].update(type='Bot'),
                lambda x:x.update(body=x['body']+'\n'+x['body']),
                lambda x:x.update(body=x['body'].replace('39085031884','39085031885')),
                lambda x:x.pop('created_at'),lambda x:x.pop('updated_at'),
                lambda x:x.update(created_at=None),lambda x:x.update(updated_at=None),
                lambda x:x.update(created_at=None,updated_at=None),
                lambda x:x.update(updated_at='2099-01-01T00:00:00Z')):
            changed=copy.deepcopy(comment);mutate(changed)
            with self.subTest(mutate=mutate),patch.object(c,'gh_json',return_value=changed),self.assertRaises(c.Refused):
                c.native_read_pending_proof(pending)

    def observed(self):
        receipt=dict(schema='SYNTHETIC_OFFLINE_ONLY',failed_run=39085031884)
        patch.object(c,'NATIVE_READ_METER',c.digest(c.encoded(receipt))).start()
        return dict(runs=[dict(id=i) for i in range(16)]+[dict(id=39085031884)],receipts=[receipt],
            examined=76,parent_sha=c.NATIVE_READ_CP,first=c.utc(c.CONTINUATION['first']),
            used=dict(provider_gets=542,drive_requests=5269,drive_bytes=842810550,storage_bytes=79426031),active_seconds=3769)

    def test_exact_failed_prefix_and_pending_cost_share_original_caps(self):
        observed=self.observed();pending=self.control['pending_external_read_accounting']
        c.native_read_budget(observed,pending)
        for mutate in (lambda x:x['runs'][-1].update(id=999),lambda x:x.update(examined=75),
                lambda x:x.update(parent_sha='0'*64),lambda x:x['receipts'][-1].update(failed_run=1),
                lambda x:x.update(active_seconds=0),lambda x:x['used'].update(drive_requests=0),
                lambda x:x.update(first=x['first']+timedelta(seconds=1))):
            changed=copy.deepcopy(observed);mutate(changed)
            with self.subTest(mutate=mutate),self.assertRaisesRegex(c.Refused,'NATIVE_READ_CAPTURE_PREFIX'):
                c.native_read_budget(changed,pending)
        pending=copy.deepcopy(pending);pending['usage']['drive_bytes']=c.CONTINUED_LIMITS['drive_bytes']
        with self.assertRaisesRegex(c.Refused,'NATIVE_READ_SHARED_BUDGET'):c.native_read_budget(observed,pending)

    def test_worker_integrates_reviewed_source_history_meter_and_owner_drive(self):
        observed=self.observed();self.a.update(self.read_auth)
        patch.object(c,'validate_authorization',return_value=c.NATIVE_READ_AUTH).start()
        server=self.server();p=self.base.root/'native-control';p.write_bytes(c.encoded(self.control))
        run=dict(id=12345,run_attempt=1)
        def metadata(path):
            if path.endswith('/branches/master'):return dict(protected=True,commit=dict(sha='4'*40))
            if '/contents/' in path:
                import base64
                name=path.split('/contents/',1)[1].split('?ref=',1)[0]
                return dict(encoding='base64',content=base64.b64encode((c.ROOT/name).read_bytes().replace(b'\r\n',b'\n')).decode())
            if '/jobs?' in path:return dict(total_count=2,jobs=[dict(name='offline',status='completed'),
                dict(name='reconcile',status='in_progress',started_at=c.utc().isoformat())])
            return run
        original=c.NativeReadMeter
        with patch.dict(os.environ,self.env,clear=True),patch.object(c,'gh_json',side_effect=metadata), \
             patch.object(c,'external_history',return_value=observed), \
             patch.object(c,'native_read_pending_proof',return_value='a'*64), \
             patch.object(c,'NativeReadMeter',side_effect=lambda *a,**kw:original(*a,opener=server,**kw)), \
             patch('sys.stdout',new=io.StringIO()) as output:
            c.native_read_worker(p,self.base.root/'native-state')
        result=c.bounded_json(self.base.root/'native-state/native_read_meter.json')
        self.assertTrue(result['finalized']);self.assertEqual(result['status'],'COMPLETE')
        self.assertEqual(result['usage']['provider_gets'],0);self.assertEqual(result['usage']['storage_bytes'],0)
        self.assertFalse(result['capture_allowed']);self.assertIn('NATIVE_READ_COMPLETE',output.getvalue())
        self.assertEqual(result['capture_usage_before'],observed['used'])
        self.assertEqual(result['dispatch_reservation'],1);self.assertEqual(result['active_seconds_reservation'],900)

    def test_unreviewed_local_bytes_or_master_drift_cannot_use_native_credentials(self):
        with patch.object(c,'gh_json',return_value=dict(protected=True,commit=dict(sha='0'*40))), \
             self.assertRaisesRegex(c.Refused,'CAMPAIGN_MASTER_DRIFT'):c.native_read_source('4'*40)
        with patch.object(c,'gh_json',side_effect=[dict(protected=True,commit=dict(sha='4'*40)),
                dict(encoding='base64',content='eA==')]),self.assertRaisesRegex(c.Refused,'NATIVE_READ_CODE_DRIFT'):
            c.native_read_source('4'*40)

    def test_native_job_clock_is_actual_not_invented_or_reset(self):
        now=c.utc();first=c.utc(c.CONTINUATION['first'])
        job=dict(name='reconcile',status='in_progress',started_at=now.isoformat())
        jobs=dict(total_count=2,jobs=[dict(name='offline',status='completed'),job])
        deadline=c.native_read_job_deadline(jobs,first)
        self.assertEqual(deadline,min(now+timedelta(seconds=300),first+timedelta(hours=48)))
        for clock in (None,7,(now+timedelta(minutes=1)).isoformat()):
            changed=copy.deepcopy(jobs);changed['jobs'][1]['started_at']=clock
            with self.subTest(clock=clock),self.assertRaisesRegex(c.Refused,'NATIVE_READ_JOB_CLOCK'):
                c.native_read_job_deadline(changed,first)
        changed=copy.deepcopy(jobs);changed['jobs'][1].pop('started_at')
        with self.assertRaisesRegex(c.Refused,'NATIVE_READ_JOB_CLOCK'):c.native_read_job_deadline(changed,first)


class NativeReadExact6ScopeDecisionTests(unittest.TestCase):
    """Focused policy-boundary counterexamples; fixtures issue no real decision."""
    def setUp(self):
        self.native=NativeRead39085031884Tests();self.native.setUp();self.addCleanup(self.native.doCleanups)
        self.control=self.native.control
        self.control['pending_external_read_accounting']=dict(basis=c.NATIVE_READ_SCOPE_BASIS,
            observation_sha256=c.NATIVE_READ_OBSERVATION,status='UNKNOWN_NOT_ZERO',
            usage=dict(provider_gets=0,storage_bytes=0,drive_requests=None,drive_bytes=None),
            reference=self.native.base.reference,decision_sha256='0'*64)
        self.refresh_decision()

    def refresh_decision(self):
        self.record=c.native_read_scope_record(self.control)
        self.pending=self.control['pending_external_read_accounting']
        self.pending['decision_sha256']=c.digest(c.encoded(self.record))
        self.comment=dict(id=int(self.pending['reference'].rsplit('-',1)[1]),author_association='OWNER',
            issue_url=f'https://api.github.com/repos/{c.REPO}/issues/448',user=dict(type='User'),
            created_at='2026-10-18T01:30:00Z',updated_at='2026-10-18T01:30:00Z',
            body='A1_SIP_NATIVE_READ_SCOPE_DECISION '+c.encoded(self.record).decode())

    def proof(self,comment=None):
        with patch.object(c,'gh_json',return_value=self.comment if comment is None else comment):
            return c.native_read_pending_proof(self.pending,self.control)

    def test_explicit_exact_decision_keeps_unknown_and_controlled_balance(self):
        self.assertIs(c.native_read_control(self.control),self.control['authorization'])
        self.assertRegex(self.proof(),r'^[0-9a-f]{64}$')
        observed=self.native.observed();self.refresh_decision()
        balance=c.native_read_budget(observed,self.pending)
        self.assertEqual(balance['controlled_used_before_native'],observed['used'])
        self.assertFalse(balance['total_platform_cost_verified'])
        self.assertEqual(balance['external_diagnostics_status'],'UNKNOWN_NOT_ZERO')
        self.assertIsNone(self.pending['usage']['drive_requests']);self.assertIsNone(self.pending['usage']['drive_bytes'])
        self.assertEqual(self.record['native_dispatches'],1);self.assertEqual(self.record['native_active_seconds'],900)
        self.assertEqual(self.record['unknown_storage_bytes_still_charged'],302101)

    def test_unapproved_template_blocks_before_credentials_or_remote_call(self):
        self.pending['decision_sha256']=None
        p=self.native.base.root/'scope-control';p.write_bytes(c.encoded(self.control))
        with patch.object(drive_module,'OwnerDrive',side_effect=AssertionError('NO_CREDENTIAL')) as owner, \
             patch.object(c,'gh_json',side_effect=AssertionError('NO_REMOTE')),self.assertRaises(c.Refused):
            c.native_read_worker(p,self.native.base.root/'scope-native')
        owner.assert_not_called()

    def test_missing_decision_observation_or_reference_is_rejected(self):
        for key in tuple(self.pending):
            changed=copy.deepcopy(self.control);del changed['pending_external_read_accounting'][key]
            with self.subTest(key=key),self.assertRaises(c.Refused):c.native_read_control(changed)

    def test_unknown_cannot_be_zero_verified_or_arbitrary_upper_bound(self):
        for mutate in (lambda p:p['usage'].update(drive_requests=0),lambda p:p['usage'].update(drive_bytes=0),
                lambda p:p['usage'].update(drive_requests=6,drive_bytes=2304),
                lambda p:p['usage'].update(drive_requests=16,drive_bytes=16000000),
                lambda p:p.update(status='VERIFIED_TRANSPORT_ACCOUNTING'),
                lambda p:p.update(basis='VERIFIED_TRANSPORT_ACCOUNTING'),
                lambda p:p.update(receipt_sha256='e'*64)):
            changed=copy.deepcopy(self.control);mutate(changed['pending_external_read_accounting'])
            with self.subTest(mutate=mutate),self.assertRaises(c.Refused):c.native_read_control(changed)

    def test_other_observation_and_other_six_calls_are_rejected(self):
        changed=copy.deepcopy(self.control);changed['pending_external_read_accounting']['observation_sha256']='f'*64
        with self.assertRaises(c.Refused):c.native_read_control(changed)
        for key,value in [('observation_sha256','f'*64),('connector_calls',5),('connector_calls',7),
                ('platform_materializations',0),('platform_materializations',2)]:
            record=copy.deepcopy(self.record);record[key]=value
            comment=copy.deepcopy(self.comment);comment['body']='A1_SIP_NATIVE_READ_SCOPE_DECISION '+c.encoded(record).decode()
            self.pending['decision_sha256']=c.digest(c.encoded(record))
            with self.subTest(key=key,value=value),self.assertRaises(c.Refused):self.proof(comment)

    def test_owner_decision_is_immutable_actual_user_and_not_accounting_tag(self):
        for mutate in (lambda x:x.update(author_association='MEMBER'),lambda x:x['user'].update(type='Bot'),
                lambda x:x.update(id=99),lambda x:x.update(issue_url='https://api.github.com/repos/other/repo/issues/448'),
                lambda x:x.update(updated_at='2026-10-18T01:31:00Z'),lambda x:x.pop('created_at'),
                lambda x:x.update(created_at=None,updated_at=None),
                lambda x:x.update(body=x['body'].replace('A1_SIP_NATIVE_READ_SCOPE_DECISION','A1_SIP_NATIVE_READ_ACCOUNTING')),
                lambda x:x.update(body=x['body']+'\n'+x['body'])):
            changed=copy.deepcopy(self.comment);mutate(changed)
            with self.subTest(mutate=mutate),self.assertRaises(c.Refused):self.proof(changed)

    def test_policy_signature_cannot_rewrite_failure_owner_source_checkpoint_or_caps(self):
        mutations=[('failed_run_id',39085031885),('failed_meter_sha256','0'*64),('prior_auth_sha256','0'*64),
            ('checkpoint_sha256','0'*64),('owner_sha256','0'*64),('expected_master','5'*40),
            ('nonce',c.PREFIX+'b'*24),('first_canonical_utc','2026-10-18T01:30:00Z'),
            ('expires_at_utc','2099-01-01T00:00:00Z'),('original_receipts',16),
            ('unknown_storage_bytes_still_charged',0),('original_dispatch_cap',41),
            ('original_active_seconds_cap',43201),('native_dispatches',2),('native_active_seconds',901),
            ('budget_reset',True),('capture_authorized',True),('provider_get_authorized',True),
            ('drive_data_write_authorized',True),('failed_post_retry_authorized',True),
            ('extra_payment_authorized',True),('subsequent_native_settlement_required',False),
            ('budget_scope','ALL_PLATFORM_COST_VERIFIED'),('decision','PENDING')]
        for key,value in mutations:
            record=copy.deepcopy(self.record);record[key]=value
            comment=copy.deepcopy(self.comment);comment['body']='A1_SIP_NATIVE_READ_SCOPE_DECISION '+c.encoded(record).decode()
            self.pending['decision_sha256']=c.digest(c.encoded(record))
            with self.subTest(key=key),self.assertRaises(c.Refused):self.proof(comment)

    def test_policy_cannot_invent_controlled_totals_or_increase_allowance(self):
        for field,key,value in [('controlled_capture_usage','drive_requests',0),
                ('controlled_capture_usage','drive_bytes',842810549),('controlled_capture_usage','storage_bytes',0),
                ('native_allowance','provider_gets',1),('native_allowance','drive_requests',17),
                ('native_allowance','drive_bytes',16000001),('native_allowance','storage_bytes',1),
                ('original_limits','drive_requests',50001),('past_diagnostics_usage','drive_bytes',0)]:
            record=copy.deepcopy(self.record);record[field][key]=value
            comment=copy.deepcopy(self.comment);comment['body']='A1_SIP_NATIVE_READ_SCOPE_DECISION '+c.encoded(record).decode()
            self.pending['decision_sha256']=c.digest(c.encoded(record))
            with self.subTest(field=field,key=key),self.assertRaises(c.Refused):self.proof(comment)

    def test_original_authorization_and_expiry_cannot_be_reset(self):
        changed=copy.deepcopy(self.control);changed['authorization']['limits']['drive_requests']+=1
        with self.assertRaises(c.Refused):c.native_read_control(changed)
        old=c.utc
        with patch.object(c,'utc',side_effect=lambda v=None:old(v) if v is not None else old(c.CONTINUATION['first'])+timedelta(hours=48)), \
             self.assertRaisesRegex(c.Refused,'CAMPAIGN_EXPIRED'):c.native_read_control(self.control)

    def test_budget_resets_extra_receipt_or_bad_sum_are_rejected(self):
        observed=self.native.observed();self.refresh_decision()
        for mutate in (lambda x:x['runs'].append(dict(id=999)),lambda x:x['runs'][-1].update(id=999),
                lambda x:x['used'].update(drive_requests=0),lambda x:x['used'].update(drive_bytes=842810549),
                lambda x:x['used'].update(storage_bytes=x['used']['storage_bytes']-302101),
                lambda x:x.update(active_seconds=0),lambda x:x.update(first=c.utc()),
                lambda x:x.update(parent_sha='0'*64)):
            changed=copy.deepcopy(observed);mutate(changed)
            with self.subTest(mutate=mutate),self.assertRaises(c.Refused):c.native_read_budget(changed,self.pending)
        with patch.dict(c.CONTINUED_LIMITS,drive_requests=5284),self.assertRaisesRegex(c.Refused,'NATIVE_READ_SHARED_BUDGET'):
            c.native_read_budget(observed,self.pending)

    def test_exact_decision_does_not_enable_provider_or_drive_post(self):
        self.assertRegex(self.proof(),r'^[0-9a-f]{64}$')
        opener=Opener(b'{}');meter=self.native.meter(opener)
        for url,provider in [('https://data.alpaca.markets/v2/stocks/bars',True),
                ('https://www.googleapis.com/drive/v3/files',False)]:
            with self.subTest(url=url),self.assertRaisesRegex(c.Refused,'NATIVE_READ_ENDPOINT'):
                meter.perform(url,provider=provider,method='POST',body=b'{}',limit=1024)
        self.assertEqual(meter.used['provider_gets'],0);self.assertEqual(meter.used['drive_requests'],0)
        with self.assertRaises(c.Refused):meter.reserve_storage(1)

    def test_worker_uses_real_scope_proof_and_meter_preserving_unknown(self):
        observed=self.native.observed();self.native.a.update(self.native.read_auth);self.refresh_decision()
        patch.object(c,'validate_authorization',return_value=c.NATIVE_READ_AUTH).start()
        server=self.native.server();p=self.native.base.root/'scope-control';p.write_bytes(c.encoded(self.control))
        def metadata(path):
            if '/issues/comments/' in path:return self.comment
            if '/jobs?' in path:return dict(total_count=2,jobs=[dict(name='offline',status='completed'),
                dict(name='reconcile',status='in_progress',started_at=c.utc().isoformat())])
            return dict(id=12345,run_attempt=1)
        original=c.NativeReadMeter
        with patch.dict(os.environ,self.native.env,clear=True),patch.object(c,'gh_json',side_effect=metadata), \
             patch.object(c,'native_read_source',return_value={'SYNTHETIC_OFFLINE_SOURCE':'a'*64}), \
             patch.object(c,'external_history',return_value=observed), \
             patch.object(c,'NativeReadMeter',side_effect=lambda *a,**kw:original(*a,opener=server,**kw)), \
             patch('sys.stdout',new=io.StringIO()):
            c.native_read_worker(p,self.native.base.root/'scope-native')
        result=c.bounded_json(self.native.base.root/'scope-native/native_read_meter.json')
        self.assertTrue(result['finalized']);self.assertEqual(result['status'],'COMPLETE')
        self.assertEqual(result['usage']['drive_requests'],7)
        self.assertEqual(result['usage']['provider_gets'],0);self.assertEqual(result['usage']['storage_bytes'],0)
        self.assertIsNone(result['pending_external_read_accounting']['usage']['drive_bytes'])
        self.assertFalse(result['budget_accounting']['total_platform_cost_verified'])
        self.assertEqual(result['budget_accounting']['controlled_used_before_native'],observed['used'])
        self.assertTrue(result['subsequent_capture_requires_separate_native_meter_settlement'])
        self.assertFalse(result['capture_allowed']);self.assertEqual(result['dispatch_reservation'],1)



# Frozen non-price native meter from run39103855450/artifact12127433913.
# It contains counters/proof references only, no supplier original or credential.
FROZEN_NATIVE18_METER = json.loads(r'''{"active_seconds_reservation":900,"allowance":{"drive_bytes":16000000,"drive_requests":16,"provider_gets":0,"storage_bytes":0},"budget_accounting":{"controlled_used_before_native":{"drive_bytes":842810550,"drive_requests":5269,"provider_gets":542,"storage_bytes":79426031},"external_diagnostics_status":"UNKNOWN_NOT_ZERO","scope":"ORIGINAL17_AND_NEW_CONTROLLED_NATIVE_NOT_TOTAL_PLATFORM_COST","total_platform_cost_verified":false},"capture_allowed":false,"capture_usage_before":{"drive_bytes":842810550,"drive_requests":5269,"provider_gets":542,"storage_bytes":79426031},"dispatch_reservation":1,"economic_authority":false,"examined_before":76,"failed_meter_sha256":"231d256890c209ef5dace024a25cfafc5d6a8714abded3a8cca76f2752818814","failed_run_id":39085031884,"finalized":true,"nonce":"r1000-993-20261015-d823a3d72ee18bb3b41cd454","observed_google_body_bytes":4726,"parent_checkpoint_sha256":"efcea3356688118392fa71612ee2702c4b9ea436ad88bdfdab917ef60e373cfd","pending_external_read_accounting":{"basis":"EXPLICIT_EXACT6_SCOPE_DECISION","decision_sha256":"d8688230eb773fee432bcc8c7dbe180daf49bd9b882f503b2e683fad644f2768","observation_sha256":"c0c9de188852ac7cea996ab506f27e514cfe976f4c467ec4e782303ed5ca7e2f","reference":"https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-6246458080","status":"UNKNOWN_NOT_ZERO","usage":{"drive_bytes":null,"drive_requests":null,"provider_gets":0,"storage_bytes":0}},"pending_external_read_proof_sha256":"e25fca3a43a14d8d44b6615a758cce55fd8c665dbafd6bf653b639a6d3400b1d","pit_verified":false,"reason":null,"result":{"absence_proven":false,"candidate_count":0,"failed_request_body_hash_known":false,"files_count":1,"owner_sha256":"08e29aa6cca772e9319b2aab20ad9fdba5dd0d8fce08a90b9fdbf3253fe9a94e","positive_control_verified":true},"run_attempt":1,"run_id":39103855450,"schema":"a1-native-drive-read-meter-v1","source_admission":false,"source_pins":{".github/workflows/alpaca_sip_private_backfill_v1.yml":"ef76f00eea26b6a65d2fd4722d07042824ddc7267b3d62f157882771fbe68c44","tools/alpaca_sip_campaign.py":"ff122b3f1934703c1e606ebe5bed8c6b4bfc1019b699f5d96bc0d112cc37abd3","tools/alpaca_sip_private_backfill_v1.py":"229fffc8f6fda45fe228efa81b58b71908070b3979aee74d37665d4a1aacacf7","tools/configure_macro_research_drive.py":"51c6210ae63f4e7522d5d73d8eb90c5c03348736a9638461772d116fcf51d2fc","tools/macro_history_sources.py":"029ae7337618211c1520adc78c9199831ed739918070c6b29204e9110aa9ab08","tools/twelve_private_capture.py":"2cfe64847cb6a9d4777247968832dbdf5737eafc1ed5f47a2e7b6877bc27bdac"},"source_sha":"a549c27b1cdd002bdaaa7dd6ab5dfc44fef0aaad","status":"COMPLETE","subsequent_capture_requires_separate_native_meter_settlement":true,"task_key":"R1000-SOURCE39085031884-NATIVE-METERED-READ-PATH-20261018","transfer_definition":"HTTP_BODIES_PLUS_65536_RESERVED_OVERHEAD_PER_GOOGLE_REQUEST","usage":{"drive_bytes":529014,"drive_requests":8,"provider_gets":0,"storage_bytes":0}}''')


class Native18SealedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.value=copy.deepcopy(FROZEN_NATIVE18_METER)
        self.run=dict(id=c.NATIVE18_RUN,run_attempt=1,status="completed",conclusion="success",
            head_sha=c.NATIVE18_MASTER,head_branch="master",event="workflow_dispatch",
            created_at="2026-10-18T06:23:17Z",
            display_title="a1-sip "+self.value["nonce"]+" native-read39085031884")
        self.jobs=dict(total_count=2,jobs=[
            dict(id=117605461102,name="offline",started_at="2026-10-18T06:23:23Z",
                 completed_at="2026-10-18T06:24:47Z",status="completed",conclusion="success"),
            dict(id=117605710106,name="reconcile",started_at="2026-10-18T06:24:50Z",
                 completed_at="2026-10-18T06:26:08Z",status="completed",conclusion="success")])

    def test_exact_typed_native_receipt_and_actual_jobs_not_reservation(self):
        result=c.validate_native18_evidence(self.run,self.value,self.jobs)
        self.assertEqual(c.digest(c.encoded(self.value)),c.NATIVE18_METER)
        self.assertEqual(result["usage"],dict(provider_gets=0,drive_requests=8,drive_bytes=529014,storage_bytes=0))
        self.assertEqual(result["active_seconds"],162);self.assertEqual(result["reserved_active_seconds"],900)
        self.assertEqual(4726+8*65536,529014)
        self.assertIsNone(self.value["pending_external_read_accounting"]["usage"]["drive_requests"])

    def test_changed_meter_owner_cp_source_or_capture_schema_cannot_rebind(self):
        changes=(
            lambda m:m.update(schema="a1-sip-campaign-meter-v1"),
            lambda m:m.update(parent_checkpoint_sha256="0"*64),
            lambda m:m["result"].update(owner_sha256="0"*64),
            lambda m:m["result"].update(absence_proven=True),
            lambda m:m.update(source_sha="0"*40),
            lambda m:m["usage"].update(drive_requests=0),
            lambda m:m.update(active_seconds_reservation=162),
            lambda m:m["pending_external_read_accounting"]["usage"].update(drive_bytes=0))
        for mutate in changes:
            value=copy.deepcopy(self.value);mutate(value)
            with self.subTest(mutate=mutate),self.assertRaises(c.Refused):
                c.validate_native18_evidence(self.run,value,self.jobs)

    def test_foreign_run_retry_source_and_missing_or_changed_job_clocks_refuse(self):
        for key,value in (("id",c.NATIVE18_RUN+1),("run_attempt",2),("run_attempt",True),
                          ("head_sha","4"*40),("conclusion","failure"),("created_at",None)):
            run=dict(self.run,**{key:value})
            with self.subTest(key=key,value=value),self.assertRaises(c.Refused):
                c.validate_native18_evidence(run,self.value,self.jobs)
        for mutation in (lambda j:j["jobs"].pop(),
                         lambda j:j["jobs"][0].update(started_at=None),
                         lambda j:j["jobs"][0].update(completed_at="2026-10-18T06:24:48Z"),
                         lambda j:j["jobs"].append(dict(j["jobs"][0])),
                         lambda j:j["jobs"][1].update(conclusion="failure")):
            jobs=copy.deepcopy(self.jobs);mutation(jobs)
            with self.subTest(mutation=mutation),self.assertRaises(c.Refused):
                c.validate_native18_evidence(self.run,self.value,jobs)

    def test_artifact_slot_is_not_a_capture_artifact_or_generic_native_run(self):
        artifact=dict(id=12127433913,name="a1-native-drive-read-meter",expired=False,size_in_bytes=1724,
                      digest="sha256:b178147404e094b4652c5a56ed9d0a33db3cc58012816bb00eb037c33619b402")
        def gh(path):
            return self.jobs if "/jobs?" in path else dict(total_count=1,artifacts=[artifact])
        def download(argv,**kw):
            directory=Path(argv[argv.index("--dir")+1])
            (directory/"native_read_meter.json").write_bytes(c.encoded(self.value))
            return SimpleNamespace(returncode=0)
        with patch.object(c,"gh_json",side_effect=gh),patch.object(c.subprocess,"run",side_effect=download):
            value,evidence=c.native18_receipt_for_run(self.run)
            self.assertEqual(evidence["active_seconds"],162);self.assertEqual(value,self.value)
        for key,value in (("id",1),("name","a1-campaign-meter"),("expired",True),("digest","sha256:"+"0"*64)):
            wrong=dict(artifact,**{key:value})
            with patch.object(c,"gh_json",return_value=dict(total_count=1,artifacts=[wrong])), \
                 patch.object(c.subprocess,"run") as process,self.assertRaises(c.Refused):
                c.native18_receipt_for_run(self.run)
            process.assert_not_called()

    def test_accounting_cli_mixed_with_dispatch_inputs_refuses_before_any_action(self):
        argv=["campaign","--native18-settle-authorization","fixture.json","--state-dir","fixture-state",
              "--native18-deployed-master","4"*40,"--max-batches","1"]
        with patch("sys.argv",argv),patch("sys.stdout",new=io.StringIO()), \
             patch.object(c,"native18_accounting_host") as host:
            self.assertEqual(c.main(),2);host.assert_not_called()

    def test_missing_native_cohort_never_creates_an_empty_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);budget=root/"budget";budget.mkdir()
            missing=root/"external-cohort-top500-20261017"
            a=dict(external_cohort=dict(input_csv="ticker\nVLO\n",scope=dict(namespace="top500-20261017")))
            with patch.object(c,"bounded_json",return_value=a), \
                 patch.object(c,"validate_authorization",return_value=c.NATIVE18_RECOVERY["prior_auth"]), \
                 patch.object(c,"native_read_source",return_value={p:"a"*64 for p in c.PINS}), \
                 patch.object(c,"bounded_bytes",return_value=b"ticker\nVLO\n"), \
                 patch.object(c,"local_reject_recovery") as recovery,patch.object(c,"WorkJournal") as journal:
                with self.assertRaises(c.Refused):
                    c.native18_accounting_host("fixture-auth",missing,budget,"fixture-csv","fixture-recovery","4"*40)
            recovery.assert_not_called();journal.assert_not_called();self.assertFalse(missing.exists())


class Native18TypedSettlementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"family"
        self.pins={p:c.digest((c.ROOT/p).read_bytes()) for p in c.PINS}
        self.journal=c.WorkJournal(self.path,c.external_family_genesis())
        self.addCleanup(self.journal.close)
        for i in range(37):
            self.journal.append("SETTLED",run_id=c.NATIVE18_RECOVERY["run_id"] if i==36 else i,
                                synthetic_offline_prefix=True)
        self.originals={p.name:p.read_bytes() for p in self.path.glob("*.json")}
        patcher=patch.dict(c.NATIVE18_RECOVERY,family_event_sha256=self.journal.parent)
        patcher.start();self.addCleanup(patcher.stop)

    def append(self):
        return c.append_native18_settlement(self.journal,"4"*40,self.pins)

    def test_directory_failure_never_reports_settled_and_reopen_preserves_exact_event(self):
        with patch.object(c,"sync_native18_settlement",create=True,
                          side_effect=c.Refused("EXTERNAL_NATIVE18_DURABILITY")) as barrier:
            with self.assertRaisesRegex(c.Refused,"EXTERNAL_NATIVE18_DURABILITY"):
                self.append()
            barrier.assert_called_once_with(self.path/"000038.json")
        raw=(self.path/"000038.json").read_bytes()
        self.assertEqual(len(self.journal.entries),38)
        self.assertTrue(all((self.path/k).read_bytes()==v for k,v in self.originals.items()))
        self.journal.close();self.journal=c.WorkJournal(self.path,c.external_family_genesis())
        with patch.object(c,"sync_native18_settlement",create=True,
                          side_effect=c.Refused("EXTERNAL_NATIVE18_DURABILITY")):
            with self.assertRaisesRegex(c.Refused,"EXTERNAL_NATIVE18_DURABILITY"):
                self.append()
        event=self.append()
        self.assertEqual(c.encoded(event),raw)
        self.assertEqual(len(list(self.path.glob("*.json"))),38)

    def test_existing_event_cannot_release_reservation_without_directory_barrier(self):
        event=self.append()
        auth=dict(expected_master="4"*40,code_pins=self.pins,external_cohort=dict(
            native18_recovery=dict(settlement_sha256=c.digest(c.encoded(event)))))
        before={p.name:p.read_bytes() for p in self.path.glob("*.json")}
        with patch.object(c,"sync_native18_settlement",side_effect=c.Refused("EXTERNAL_NATIVE18_DURABILITY")):
            with self.assertRaisesRegex(c.Refused,"EXTERNAL_NATIVE18_DURABILITY"):
                c.verify_native18_shared(self.journal,auth)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.path.glob("*.json")})

    def test_platform_directory_barrier_on_existing_scratch_family(self):
        self.append()
        c.sync_native18_settlement(self.path/"000038.json")
        self.assertTrue(all((self.path/k).read_bytes()==v for k,v in self.originals.items()))

    def test_existing_event_file_fsync_failure_blocks_import_and_consumption(self):
        event=self.append();raw=c.encoded(event)
        auth=dict(expected_master="4"*40,code_pins=self.pins,external_cohort=dict(
            native18_recovery=dict(settlement_sha256=c.digest(raw))))
        with patch.object(c.os,"fsync",side_effect=OSError("synthetic file flush failure")):
            with self.assertRaisesRegex(c.Refused,"EXTERNAL_NATIVE18_DURABILITY"):
                self.append()
            with self.assertRaisesRegex(c.Refused,"EXTERNAL_NATIVE18_DURABILITY"):
                c.verify_native18_shared(self.journal,auth)
        self.assertEqual((self.path/"000038.json").read_bytes(),raw)
        self.assertEqual(c.encoded(self.append()),raw)

    @unittest.skipUnless(os.name=="posix","requires actual POSIX directory descriptor")
    def test_directory_fsync_failure_closes_descriptor_and_refuses(self):
        self.append()
        original_close=c.os.close
        with patch.object(c.os,"fsync",side_effect=[None,OSError("synthetic directory flush failure")]), \
             patch.object(c.os,"close",wraps=original_close) as closed:
            with self.assertRaisesRegex(c.Refused,"EXTERNAL_NATIVE18_DURABILITY"):
                c.sync_native18_settlement(self.path/"000038.json")
        closed.assert_called_once()

    def test_typed_once_only_append_preserves37_and_has_no_fake_capture_reservation(self):
        event=self.append();before={p.name:p.read_bytes() for p in self.path.glob("*.json")}
        self.assertEqual(event,self.append());self.assertEqual(len(self.journal.entries),38)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.path.glob("*.json")})
        self.assertTrue(all((self.path/k).read_bytes()==v for k,v in self.originals.items()))
        self.assertEqual(event["kind"],"NATIVE_READ_SETTLED")
        self.assertEqual(event["usage"],c.NATIVE18_USAGE);self.assertEqual(event["active_seconds"],162)
        self.assertEqual(event["reserved_active_seconds"],900)
        self.assertEqual(event["unknown_storage_bytes_still_charged"],302101)
        self.assertNotIn("nonce",event);self.assertNotIn("receipt",event)
        auth=dict(expected_master="4"*40,code_pins=self.pins,external_cohort=dict(
            native18_recovery=dict(settlement_sha256=c.digest(c.encoded(event)))))
        c.verify_native18_shared(self.journal,auth)
        self.journal.close()
        self.journal=c.WorkJournal(self.path,c.external_family_genesis())
        self.assertEqual(c.append_native18_settlement(self.journal,"4"*40,self.pins),event)

    def test_missing_old_prefix_tampered_or_duplicate_native_event_refuses(self):
        self.journal.parent="0"*64
        with self.assertRaises(c.Refused):self.append()
        self.journal.parent=c.NATIVE18_RECOVERY["family_event_sha256"]
        event=self.append()
        bad=copy.deepcopy(event);bad["usage"]["drive_requests"]=0
        with self.assertRaises(c.Refused):c.verify_native18_event(bad,"4"*40,self.pins)
        with self.assertRaises(c.Refused):c.verify_native18_event(event,"5"*40,self.pins)
        with self.assertRaises(c.Refused):c.verify_native18_event(event,"4"*40,self.pins,"0"*64)
        self.journal.append("NATIVE_READ_SETTLED",**c.native18_event_payload("4"*40,self.pins))
        with self.assertRaises(c.Refused):self.append()

    def test_real_append_precedes_owner_consent_no_predicted_self_hash(self):
        event=self.append();sha=c.digest(c.encoded(event))
        auth=dict(expected_master="4"*40,code_pins=self.pins,
                  external_cohort=dict(native18_recovery=dict(settlement_sha256=sha)))
        clock=c.utc().isoformat()
        comment=dict(created_at=clock,updated_at=clock,
                     body="A1_SIP_NATIVE18_SETTLEMENT "+json.dumps(event))
        self.assertEqual(c.native18_consent_event(auth,comment),event)
        for update in (dict(body=""),dict(updated_at="2026-10-18T06:00:00Z"),
                       dict(created_at="2026-10-18T06:26:08Z",updated_at="2026-10-18T06:26:08Z")):
            with self.subTest(update=update),self.assertRaises(c.Refused):
                c.native18_consent_event(auth,dict(comment,**update))
        self.assertEqual(c.digest(c.encoded(event)),sha)


class Native18ControllerCollectorTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        path=Path(__file__).with_name("alpaca_sip_private_backfill_v1_smoke.py")
        spec=importlib.util.spec_from_file_location("storage_quarantine_fixture",path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.f=module.UncertainStorageQuarantineTests()
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        patcher=patch.dict(c.NATIVE18_RECOVERY,checkpoint_sha256=self.f.prefix["sha256"])
        patcher.start();self.addCleanup(patcher.stop)

    def meter(self):
        info=identity()
        info.update(cohort_scope=self.f.scope,auth_sha256=self.f.evidence["authorization_sha256"],
            external_proof_sha256=self.f.evidence["external_proof_sha256"],
            native18_settlement_sha256=self.f.evidence["native_settlement_sha256"],
            run_id=self.f.evidence["recovery_run_id"],recovery_run=c.NATIVE18_RECOVERY["run_id"],
            parent_checkpoint_sha256=self.f.prefix["sha256"],examined_before=76,source_sha="c"*40)
        return c.RuntimeMeter(dict(c.CONTINUED_LIMITS),Path(self.tmp.name)/"meter",
            (c.utc()+timedelta(seconds=60)).isoformat(),info,opener=Opener(),limits=c.CONTINUED_LIMITS)

    def test_full_collector_readback_advances_held_only_and_preserves_76_valid(self):
        m=self.meter()
        ref=self.f.hold(on_group=lambda d,s,r:c.verify_new_group(d,self.f.drive.folder,s,r,m))
        m.finish("COMPLETE")
        value=c.bounded_json(m.journal)
        self.assertEqual(value["new_states"],dict(VALID_COLLECTED=0,VERIFIED_NO_DATA=0,QUARANTINED=4))
        self.assertEqual(value["rows_verified"],0);self.assertEqual(value["usage"]["provider_gets"],0)
        self.assertEqual(value["examined_before"],76);self.assertEqual(value["examined_after"],80)
        self.assertEqual(value["checkpoint_sha256"],ref["sha256"])
        self.assertFalse(value["source_admission"]);self.assertFalse(value["pit_verified"])
        self.assertEqual(len(self.f.restore(ref)[1]),76)
        self.assertEqual(value["uncertain_storage_hold"]["evidence"],self.f.evidence)

    def test_wrong_canonical_proof_or_run_cannot_verify_a_valid_hashed_hold(self):
        m=self.meter();m.identity["external_proof_sha256"]="0"*64
        with self.assertRaises(c.Refused):
            self.f.hold(on_group=lambda d,s,r:c.verify_new_group(d,self.f.drive.folder,s,r,m))
        self.assertEqual(m.examined,76);self.assertEqual(m.states["VALID_COLLECTED"],0)
        self.assertEqual(m.states["QUARANTINED"],0)
        m.finish("BLOCKED","SYNTHETIC_BAD_HOLD_PROOF")
        self.assertEqual(self.f.restore(self.f.prefix)[2],[])



class Native18RecoveryHistoryTests(unittest.TestCase):
    """Synthetic17+native18+successor metadata through the real history reducer."""
    def setUp(self):
        # A finite historical fixture must not acquire the test runner's date.
        clock=c.utc
        frozen=patch.object(c,'utc',side_effect=lambda value=None:clock(value) if value is not None else clock('2026-10-18T22:30:00Z'))
        frozen.start();self.addCleanup(frozen.stop)
        self.base=ExternalCohortTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.addCleanup(patch.stopall)
        patch.dict(c.CONTINUATION,first="2026-10-17T02:08:51Z").start()
        self.old=copy.deepcopy(self.base.new)
        self.names=["ZQ%03d"%i for i in range(76)]+["VLO","MFG","BP","BTI"]+["SPGI"]+["ZQ%03d"%i for i in range(81,417)]
        raw="ticker\n"+"\n".join(self.names)+"\n"
        self.scope=dict(task_key="R1000-DISCOVERY-EXPANSION-INTAKE-20261017",
                        namespace="top500-20261017",input_sha256=c.digest(raw.encode()))
        patch.dict(cap.STORAGE_QUARANTINE,input_sha256=self.scope["input_sha256"],
                   owner_sha256=c.CONTINUATION["bindings"]["owner_sha256"]).start()
        self.old.update(expected_master="4"*40,account_permission_reference=self.base.reference+"2")
        self.old["external_cohort"]=dict(self.old["external_cohort"],scope=self.scope,input_csv=raw,
            prior_epochs=[self.base.new],proof_reference=self.old["account_permission_reference"])
        oldhash=c.validate_authorization(self.old)
        patch.dict(c.NATIVE18_RECOVERY,prior_auth=oldhash).start()
        patch.object(c,"NATIVE18_PRIOR_SOURCE",dict(expected_master=self.old["expected_master"],
            code_pins=self.old["code_pins"],proof_reference=self.old["external_cohort"]["proof_reference"])).start()
        self.proofs={}
        def proof_for(a,clock="2026-10-17T02:08:52Z"):
            h=c.validate_authorization(a)
            value=dict(proof_sha256=c.digest(c.encoded(dict(fixture_auth=h))),
                proof_updated_utc=clock,expires_at_utc="2026-10-19T02:08:51Z")
            self.proofs[h]=value
            return value
        proof_for(self.base.new);proof_for(self.old)
        self.runs=copy.deepcopy(self.base.old.runs);self.values=copy.deepcopy(self.base.old.receipts)
        for run in self.runs:run["created_at"]=c.CONTINUATION["first"]
        self.seconds={run["id"]:s for run,s in zip(self.runs,[27,159,215,206,265])}
        used=dict(c.CONTINUATION["used"])
        current,parent=0,c.external_genesis(self.scope)
        for index in range(12):
            previous=index==0
            a=self.base.new if previous else self.old
            scope=a["external_cohort"]["scope"];h=c.validate_authorization(a);proof=self.proofs[h]
            if previous:
                before,after,oldparent=0,4,c.external_genesis(scope)
                usage=dict(provider_gets=8,drive_requests=322,drive_bytes=100070480,storage_bytes=5905975)
            else:
                before=current
                after=before+([8]*6+[4]*4+[12])[index-1]
                oldparent=parent
                usage=(dict(provider_gets=46,drive_requests=219,drive_bytes=41735070,storage_bytes=3516056)
                    if index==11 else dict(provider_gets=40,drive_requests=330,drive_bytes=70000000,storage_bytes=7000000))
            runid=c.NATIVE18_RECOVERY["run_id"] if index==11 else index+6
            nonce=c.PREFIX+format(index+10,"024x")
            cp=c.NATIVE18_RECOVERY["checkpoint_sha256"] if index==11 else c.digest(c.encoded(dict(fixture_cp=runid)))
            run=dict(id=runid,display_title="a1-sip "+nonce,head_sha=a["expected_master"],
                head_branch="master",created_at="2026-10-17T04:08:51Z",status="completed",
                conclusion="failure" if index==11 else "success",run_attempt=1,event="workflow_dispatch")
            value=dict(self.base.old.receipts[-1],auth_sha256=h,source_sha=a["expected_master"],
                nonce=nonce,run_id=runid,status="BLOCKED" if index==11 else "COMPLETE",preflight_only=False,
                reason="HTTP_ERROR" if index==11 else None,parent_checkpoint_sha256=oldparent,
                checkpoint_sha256=cp,examined_before=before,examined_after=after,cohort_scope=scope,
                rows_verified=2*(after-before),new_states=dict(VALID_COLLECTED=after-before,VERIFIED_NO_DATA=0,QUARANTINED=0),
                external_proof_sha256=proof["proof_sha256"],recovery_run=None,
                allowance={k:c.CONTINUED_LIMITS[k]-used[k] for k in c.LIMITS},usage=usage,
                account_permission_reference_sha256=c.digest(a["external_cohort"]["proof_reference"].encode()),
                account_permission_record_sha256=proof["proof_sha256"],confirmed_storage_bytes=usage["storage_bytes"])
            if index==11:value["last_transport_failure"]=dict(http_status=502,method="POST",phase="HEADER_OPEN",
                request_category="DRIVE_CREATE",request_ordinal=265)
            self.runs.append(run);self.values.append(value);self.seconds[runid]=697 if index==11 else 200
            used={k:used[k]+usage[k] for k in used}
            if not previous:current,parent=after,cp
        assert used==c.NATIVE18_CAPTURE_USED and current==76
        failedsha=c.digest(c.encoded(self.values[-1]))
        patch.dict(c.NATIVE18_RECOVERY,receipt_sha256=failedsha).start()
        patch.dict(cap.STORAGE_QUARANTINE,failed_meter_sha256=failedsha).start()
        self.native=copy.deepcopy(FROZEN_NATIVE18_METER)
        self.native.update(failed_meter_sha256=failedsha)
        self.native["result"]["owner_sha256"]=c.CONTINUATION["bindings"]["owner_sha256"]
        nativesha=c.digest(c.encoded(self.native))
        patch.object(c,"NATIVE18_METER",nativesha).start()
        patch.dict(cap.STORAGE_QUARANTINE,native_meter_sha256=nativesha).start()
        self.nr=dict(id=c.NATIVE18_RUN,run_attempt=1,status="completed",conclusion="success",
            head_sha=c.NATIVE18_MASTER,head_branch="master",event="workflow_dispatch",
            created_at="2026-10-18T06:23:17Z",display_title="a1-sip "+self.native["nonce"]+" native-read39085031884")
        self.jobs=Native18SealedEvidenceTests();self.jobs.setUp();self.jobs=self.jobs.jobs
        self.runs.append(self.nr)
        self.new=copy.deepcopy(self.old);self.new.update(schema="r1000-sip-external-cohort-authorization-v5",
            expected_master="c"*40,account_permission_reference=self.base.reference+"3")
        self.event=dict(sequence=38,kind="NATIVE_READ_SETTLED",auth_sha256=c.external_family_genesis(),
            previous_sha256=c.NATIVE18_RECOVERY["family_event_sha256"],recorded_utc=c.utc().isoformat(),
            **c.native18_event_payload(self.new["expected_master"],self.new["code_pins"]))
        self.new["external_cohort"].update(proof_reference=self.new["account_permission_reference"],
            native18_recovery=dict(settlement_sha256=c.digest(c.encoded(self.event))))
        self.newproof=proof_for(self.new,c.utc().isoformat())

    def observe(self,a=None,current=None,recovery=None,accounting=False,enforce=True):
        a=a or self.new;values={v["run_id"]:v for v in self.values}
        with patch.object(c,"external_proof",side_effect=lambda x:self.proofs[c.validate_authorization(x)]), \
             patch.object(c,"campaign_runs",return_value=self.runs), \
             patch.object(c,"receipt_for_run",side_effect=lambda r,*args,**kw:values[r["id"]]), \
             patch.object(c,"job_seconds",side_effect=lambda r:self.seconds[r["id"]]), \
             patch.object(c,"native18_receipt_for_run",side_effect=lambda r:
                 (self.native,c.validate_native18_evidence(r,self.native,self.jobs))):
            return c.external_history(a,current_run=current,
                nonce=self.runs[-1]["display_title"][7:] if current else None,recovery_run=recovery,
                allow_stopped=current is None,enforce_expiry=enforce,native18_accounting=accounting)

    def test_old17_plus_typed_native18_cost_time_and_checkpoint_preserved(self):
        got=self.observe()
        self.assertEqual(got["used"],dict(provider_gets=542,drive_requests=5277,drive_bytes=843339564,storage_bytes=79426031))
        self.assertEqual(got["active_seconds"],3931);self.assertEqual(len(got["runs"]),18)
        self.assertEqual(got["examined"],76);self.assertEqual(got["parent_sha"],c.NATIVE18_RECOVERY["checkpoint_sha256"])
        self.assertEqual(len(got["cohort_receipts"]),11)
        self.assertEqual(got["recovery_required"],c.NATIVE18_RECOVERY["run_id"])
        before=self.observe(self.old,accounting=True)
        self.assertEqual(before["used"],c.NATIVE18_CAPTURE_USED);self.assertEqual(before["active_seconds"],3769)
        self.assertEqual(len(before["all_runs"]),18);self.assertEqual(len(before["runs"]),17)
        with self.assertRaises(c.Refused):self.observe(self.old)

    def test_missing_duplicate_native_changed_old_budget_and_expiry_refuse(self):
        original=copy.deepcopy(self.runs)
        self.runs=self.runs[:-1]
        with self.assertRaises(c.Refused):self.observe()
        self.runs=original+[dict(original[-1])]
        with self.assertRaises(c.Refused):self.observe()
        self.runs=original
        self.values[-1]["usage"]["storage_bytes"]-=302101
        with self.assertRaises(c.Refused):self.observe()
        self.values[-1]["usage"]["storage_bytes"]+=302101
        utc=c.utc
        with patch.object(c,"utc",side_effect=lambda v=None:utc(v) if v is not None else utc("2026-10-19T02:08:51Z")):
            with self.assertRaisesRegex(c.Refused,"CAMPAIGN_EXPIRED"):self.observe()
            self.assertEqual(self.observe(enforce=False)["examined"],76)

    def test_four_held_successor_is_not_price_success_and_failed_successor_cannot_retry(self):
        before=self.observe();runid=c.NATIVE18_RUN+1;nonce=c.PREFIX+"f"*24
        run=dict(self.nr,id=runid,head_sha=self.new["expected_master"],created_at=self.newproof["proof_updated_utc"],
                 display_title="a1-sip "+nonce)
        evidence=dict(cap.STORAGE_QUARANTINE,authorization_sha256=c.validate_authorization(self.new),
            external_proof_sha256=self.newproof["proof_sha256"],
            native_settlement_sha256=self.new["external_cohort"]["native18_recovery"]["settlement_sha256"],
            recovery_run_id=runid)
        value=dict(self.values[-1],run_id=runid,nonce=nonce,auth_sha256=c.validate_authorization(self.new),
            source_sha=self.new["expected_master"],status="COMPLETE",reason=None,recovery_run=c.NATIVE18_RECOVERY["run_id"],
            examined_before=76,examined_after=80,parent_checkpoint_sha256=c.NATIVE18_RECOVERY["checkpoint_sha256"],
            checkpoint_sha256="a"*64,rows_verified=0,new_states=dict(VALID_COLLECTED=0,VERIFIED_NO_DATA=0,QUARANTINED=4),
            allowance=before["remaining"],usage=dict(provider_gets=0,drive_requests=20,drive_bytes=1500000,storage_bytes=6000),
            confirmed_storage_bytes=6000,external_proof_sha256=self.newproof["proof_sha256"],
            account_permission_reference_sha256=c.digest(self.new["external_cohort"]["proof_reference"].encode()),
            account_permission_record_sha256=self.newproof["proof_sha256"],
            native18_settlement_sha256=self.new["external_cohort"]["native18_recovery"]["settlement_sha256"],
            uncertain_storage_hold=dict(evidence=evidence,marker_sha256="b"*64,checkpoint_sha256="a"*64))
        value.pop("last_transport_failure",None)
        self.runs.append(run);self.values.append(value);self.seconds[runid]=20
        got=self.observe()
        self.assertEqual(got["examined"],80);self.assertIsNone(got["recovery_required"])
        self.assertEqual(got["used"]["provider_gets"],542)
        for changed in (dict(rows_verified=8),dict(new_states=dict(VALID_COLLECTED=4,VERIFIED_NO_DATA=0,QUARANTINED=0)),
                        dict(usage=dict(value["usage"],provider_gets=1))):
            old=copy.deepcopy(value);value.update(changed)
            with self.subTest(changed=changed),self.assertRaises(c.Refused):self.observe()
            value.clear();value.update(old)
        value.update(status="BLOCKED",reason="HTTP_ERROR",examined_after=76,
            checkpoint_sha256=value["parent_checkpoint_sha256"],new_states=dict(VALID_COLLECTED=0,VERIFIED_NO_DATA=0,QUARANTINED=0))
        value.pop("uncertain_storage_hold")
        run["conclusion"]="failure"
        # A stopped receipt may be accounted; it is not another named recovery.
        self.assertEqual(self.observe()["examined"],76)
        with self.assertRaises(c.Refused):self.observe(recovery=runid)
        self.runs.append(dict(run,id=runid+1,status="in_progress",conclusion=None,
                              display_title="a1-sip "+c.PREFIX+"a"*24))
        with self.assertRaises(c.Refused):
            self.observe(current=runid+1,recovery=c.NATIVE18_RECOVERY["run_id"])


class Native18OwnerIssuanceTests(unittest.TestCase):
    """A server assigns the immutable OWNER locator only after one create."""
    def setUp(self):
        self.h=Native18RecoveryHistoryTests();self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.auth=copy.deepcopy(self.h.new)
        self.calls=[]

    def issue(self,auth):
        body=("A1_SIP_EXTERNAL_COHORT_CONSENT "+json.dumps(c.external_proof_record(auth),separators=(',',':'))
              +"\nA1_SIP_NATIVE18_SETTLEMENT "+json.dumps(self.h.event,separators=(',',':')))
        self.calls.append('POST')
        # The simulated server allocates this ID after receiving the complete body.
        comment_id=7000000000+len(self.calls)
        clock=c.utc().isoformat()
        comment=dict(id=comment_id,issue_url=f"https://api.github.com/repos/{c.REPO}/issues/448",
            author_association='OWNER',user=dict(type='User',id=123),body=body,
            created_at=clock,updated_at=clock)
        reference=f"https://github.com/{c.REPO}/issues/448#issuecomment-{comment_id}"
        actual=copy.deepcopy(auth);actual['account_permission_reference']=reference
        actual['external_cohort']['proof_reference']=reference
        return actual,comment

    def proof(self,auth,comment):
        def get(path):
            requested=auth['external_cohort']['proof_reference'].rsplit('-',1)[1]
            self.assertEqual(path,f"repos/{c.REPO}/issues/comments/{requested}")
            return comment
        with patch.object(c,'gh_json',side_effect=get):return c.external_proof(auth)

    def test_server_assigned_locator_one_create_zero_edits(self):
        before=c.validate_authorization(self.auth)
        actual,comment=self.issue(self.auth)
        self.assertNotEqual(actual['account_permission_reference'],self.auth['account_permission_reference'])
        self.assertNotEqual(c.validate_authorization(actual),before)
        self.assertEqual(comment['created_at'],comment['updated_at'])
        self.assertEqual(self.calls,['POST'])
        self.assertEqual(self.proof(actual,comment)['proof_updated_utc'],comment['created_at'])
        record=c.decode(comment['body'].splitlines()[0].split(' ',1)[1])
        self.assertEqual(record['schema'],'a1-sip-external-cohort-consent-v2')
        self.assertNotIn('auth_sha256',record)
        self.assertEqual(record['authorization_commitment_sha256'],c.native18_consent_commitment(actual))

    def test_only_two_current_locators_are_excluded_from_commitment(self):
        original=copy.deepcopy(self.auth);baseline=c.native18_consent_commitment(original)
        actual,_=self.issue(original)
        self.assertEqual(c.native18_consent_commitment(actual),baseline)
        # Visit every other leaf, including nested ancestor URLs/keys/budgets.
        def leaves(value,path=()):
            if isinstance(value,dict):
                for key,child in value.items():yield from leaves(child,path+(key,))
            elif isinstance(value,list):
                for index,child in enumerate(value):yield from leaves(child,path+(index,))
            else:yield path,value
        excluded={('account_permission_reference',),('external_cohort','proof_reference')}
        for path,value in leaves(original):
            if path in excluded or path==('schema',):continue
            changed=copy.deepcopy(original);parent=changed
            for key in path[:-1]:parent=parent[key]
            parent[path[-1]]=(not value if isinstance(value,bool) else value+1 if isinstance(value,int)
                             else 'changed' if value is None else str(value)+'!')
            with self.subTest(path=path):self.assertNotEqual(c.native18_consent_commitment(changed),baseline)
        self.assertEqual(self.auth,original)

    def test_actual_locator_full_hash_proof_and_journal_cannot_rebind(self):
        first,comment=self.issue(self.auth);proof=self.proof(first,comment)
        second,other=self.issue(self.auth);otherproof=self.proof(second,other)
        self.assertEqual(c.native18_consent_commitment(first),c.native18_consent_commitment(second))
        self.assertNotEqual(c.validate_authorization(first),c.validate_authorization(second))
        self.assertNotEqual(proof['proof_sha256'],otherproof['proof_sha256'])
        with self.assertRaises(c.Refused):self.proof(first,other)
        mismatched=copy.deepcopy(first);mismatched['account_permission_reference']=second['account_permission_reference']
        with self.assertRaisesRegex(c.Refused,'EXTERNAL_PROOF_REFERENCE'):c.external_proof_record(mismatched)
        # A persisted journal authenticates the full hash, not the detached commitment.
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)/'journal'
            journal=c.WorkJournal(directory,c.validate_authorization(first))
            journal.append('FIXTURE_BOUND',proof_sha256=proof['proof_sha256']);journal.close()
            original={p.name:p.read_bytes() for p in directory.glob('*.json')}
            with self.assertRaisesRegex(c.Refused,'CAMPAIGN_JOURNAL_CHAIN'):
                c.WorkJournal(directory,c.validate_authorization(second))
            self.assertEqual(original,{p.name:p.read_bytes() for p in directory.glob('*.json')})

    def test_forged_owner_edited_consent_foreign_event_refuse(self):
        actual,comment=self.issue(self.auth)
        for change in [dict(id=comment['id']+1),dict(author_association='CONTRIBUTOR'),
                       dict(issue_url=f'https://api.github.com/repos/{c.REPO}/issues/590'),
                       dict(updated_at=(c.utc(comment['created_at'])+timedelta(seconds=1)).isoformat())]:
            with self.subTest(change=change),self.assertRaises(c.Refused):self.proof(actual,dict(comment,**change))
        changed=copy.deepcopy(self.h.event);changed['previous_sha256']='0'*64
        body=comment['body'].splitlines()[0]+'\nA1_SIP_NATIVE18_SETTLEMENT '+json.dumps(changed)
        with self.assertRaises(c.Refused):self.proof(actual,dict(comment,body=body))
        changed=copy.deepcopy(actual);changed['external_cohort']['scope']['namespace']='foreign'
        with self.assertRaises(c.Refused):self.proof(changed,comment)

    def test_legacy_record_still_uses_complete_authorization_sha(self):
        old=copy.deepcopy(self.h.old);record=c.external_proof_record(old)
        self.assertEqual(record['schema'],'a1-sip-external-cohort-consent-v1')
        self.assertEqual(record['auth_sha256'],c.validate_authorization(old))
        self.assertNotIn('authorization_commitment_sha256',record)


class TypedCohortForecastTests(unittest.TestCase):
    """Actual six cost/duration observations, with synthetic authority bindings."""
    def setUp(self):
        self.h=Native18RecoveryHistoryTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.a=self.h.new;old=self.h.old;newhash=c.validate_authorization(self.a)
        costs=[(60,228,39143721,8051478),(58,292,49291110,7348843),
               (46,219,41735070,3516056),(0,170,29794102,3922),
               (60,384,67118905,7754873),(26,336,58727660,3425835)]
        windows=[(0,32),(32,64),(64,76),(76,80),(80,112),(112,128)]
        receipts=[]
        for i,((before,after),values) in enumerate(zip(windows,costs)):
            a=old if i<3 else self.a;h=c.validate_authorization(a);proof=self.h.proofs[h]
            r=copy.deepcopy(self.h.values[-1]);r.update(auth_sha256=h,source_sha=a['expected_master'],
                run_id=c.NATIVE18_RUN+i+1,finalized=True,preflight_only=False,status='BLOCKED' if i==2 else 'COMPLETE',
                examined_before=before,examined_after=after,checkpoint_sha256=c.digest(str(i).encode()),
                external_proof_sha256=proof['proof_sha256'],recovery_run=None,
                new_states=dict(VALID_COLLECTED=after-before,VERIFIED_NO_DATA=0,QUARANTINED=0),
                rows_verified=2*(after-before),usage=dict(zip(c.LIMITS,values)))
            if i>=3:r['native18_settlement_sha256']=self.a['external_cohort']['native18_recovery']['settlement_sha256']
            if i==3:
                r.update(recovery_run=c.NATIVE18_RECOVERY['run_id'],rows_verified=0,
                    new_states=dict(VALID_COLLECTED=0,VERIFIED_NO_DATA=0,QUARANTINED=4),
                    uncertain_storage_hold=dict(marker_sha256='b'*64,checkpoint_sha256=r['checkpoint_sha256'],
                        evidence=dict(cap.STORAGE_QUARANTINE,authorization_sha256=newhash,
                            external_proof_sha256=proof['proof_sha256'],
                            native_settlement_sha256=r['native18_settlement_sha256'],recovery_run_id=r['run_id'])))
            receipts.append(r)
        used=dict(provider_gets=628,drive_requests=6167,drive_bytes=998980231,storage_bytes=90610661)
        self.o=dict(examined=128,cohort_receipts=receipts,cohort_durations=[274,305,275,255,380,372],
            epoch_proofs=self.h.proofs,used=used,remaining={k:c.CONTINUED_LIMITS[k]-used[k] for k in c.LIMITS},
            active_seconds=4938,runs=[{}]*21)

    def test_actual_typed_control_and_direct_417_horizon_still_stop_on_time(self):
        before=copy.deepcopy(self.o);result=c.external_forecast(self.a,self.o)
        self.assertEqual(result['projected']['drive_bytes'],5730857188)
        self.assertEqual(result['active_seconds'],38748)
        self.assertEqual(result['dispatches'],10)
        self.assertFalse(result['fits'])  # Actual remaining38262s is486s short.
        self.assertEqual(self.o,before)  # Every real charge, including held, remains.

    def test_failed_short_and_zero_row_price_observations_are_retained(self):
        price,held=c.external_forecast_samples(self.a,self.o)
        self.assertEqual([r['examined_after']-r['examined_before'] for r,_ in price],[32,32,12,32,16])
        self.assertEqual(len(held),1)
        self.assertEqual(price[2][0]['status'],'BLOCKED')
        baseline=c.external_forecast(self.a,self.o)
        for state in ['VERIFIED_NO_DATA','QUARANTINED']:
            altered=copy.deepcopy(self.o);r=altered['cohort_receipts'][1]
            r.update(rows_verified=0,new_states=dict(VALID_COLLECTED=0,VERIFIED_NO_DATA=0,QUARANTINED=0))
            r['new_states'][state]=32;r['usage']['provider_gets']=0
            result=c.external_forecast(self.a,altered)
            self.assertEqual(result['price_samples'],5)
            self.assertEqual(result['projected']['drive_bytes'],baseline['projected']['drive_bytes'])
            self.assertEqual(result['active_seconds'],baseline['active_seconds'])
        altered=copy.deepcopy(self.o);altered['cohort_receipts'][2]['usage']['storage_bytes']+=302101
        self.assertGreater(c.external_forecast(self.a,altered)['projected']['storage_bytes'],
                           baseline['projected']['storage_bytes'])

    def test_unproved_mixed_or_foreign_typed_hold_never_becomes_a_free_sample(self):
        changes=[lambda r:r.pop('uncertain_storage_hold'),
            lambda r:r['uncertain_storage_hold']['evidence'].update(authorization_sha256='0'*64),
            lambda r:r['uncertain_storage_hold']['evidence'].update(native_settlement_sha256='0'*64),
            lambda r:r['uncertain_storage_hold']['evidence'].update(recovery_run_id=r['run_id']+1),
            lambda r:r.update(rows_verified=2),lambda r:r['usage'].update(provider_gets=1),
            lambda r:r.update(new_states=dict(VALID_COLLECTED=1,VERIFIED_NO_DATA=0,QUARANTINED=3)),
            lambda r:r.update(cohort_scope=dict(r['cohort_scope'],namespace='foreign')),
            lambda r:r.update(external_proof_sha256='0'*64),lambda r:r.update(source_sha='0'*40),
            lambda r:r.update(schema='foreign-meter'),lambda r:r.update(task_key='foreign-task')]
        for change in changes:
            altered=copy.deepcopy(self.o);change(altered['cohort_receipts'][3])
            with self.subTest(change=change),self.assertRaises(c.Refused):c.external_forecast(self.a,altered)
        altered=copy.deepcopy(self.o)
        altered['cohort_receipts'][4]['uncertain_storage_hold']=copy.deepcopy(altered['cohort_receipts'][3]['uncertain_storage_hold'])
        with self.assertRaises(c.Refused):c.external_forecast(self.a,altered)
        wrong=copy.deepcopy(self.a);wrong['end']='2026-10-15'
        with self.assertRaises(c.Refused):c.external_forecast(wrong,self.o)

    def test_missing_time_zero_progress_or_insufficient_price_history_blocks(self):
        for changed in [[],self.o['cohort_durations'][:-1],[274,305,275,None,380,372],
                        [274,305,275,0,380,372],[274,305,275,float('nan'),380,372]]:
            altered=copy.deepcopy(self.o);altered['cohort_durations']=changed
            with self.subTest(durations=changed),self.assertRaises(c.Refused):c.external_forecast(self.a,altered)
        altered=copy.deepcopy(self.o);altered['cohort_receipts'][2]['examined_after']=64
        with self.assertRaises(c.Refused):c.external_forecast(self.a,altered)
        altered=copy.deepcopy(self.o);altered.update(examined=32,
            cohort_receipts=altered['cohort_receipts'][:1],cohort_durations=[274])
        with self.assertRaises(c.Refused):c.external_forecast_samples(self.a,altered)

    def test_horizon_growth_roundup_and_resource_fit_are_monotone(self):
        price,_=c.external_forecast_samples(self.a,self.o);captures=[r for r,_ in price]
        values=[r['usage']['drive_bytes'] for r in captures]
        small=c.external_price_envelope(captures,values,9)
        direct=c.external_price_envelope(captures,values,10)
        large=c.external_price_envelope(captures,values,28)
        self.assertLess(small,direct);self.assertLess(direct,large)
        self.assertEqual(c.external_price_envelope(captures,[v*2 for v in values],10),direct*2)
        self.assertGreaterEqual(c.external_forecast(self.a,self.o)['projected']['drive_bytes'],direct*1.25)
        # Synthetic boundary probe only: does not change frozen actual4938s.
        altered=copy.deepcopy(self.o);altered['active_seconds']=4452
        self.assertTrue(c.external_forecast(self.a,altered)['fits'])
        altered['active_seconds']+=1
        self.assertFalse(c.external_forecast(self.a,altered)['fits'])
        altered['active_seconds']=4452;altered['used']['drive_bytes']=c.CONTINUED_LIMITS['drive_bytes']-5730857187
        altered['remaining']['drive_bytes']=5730857187
        self.assertFalse(c.external_forecast(self.a,altered)['fits'])


class SourceRevisionCP128Tests(unittest.TestCase):
    """Synthetic authority; actual frozen six-sample arithmetic, no remote I/O."""
    def setUp(self):
        self.f=TypedCohortForecastTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.s=c._revision_module();self.old=copy.deepcopy(self.f.a);self.o=copy.deepcopy(self.f.o)
        self.o["runs"]=[dict(id=i,status="completed") for i in self.s.BASIS_IDS]
        oldhash=c.validate_authorization(self.old)
        self.o["parent_sha"]=self.o["cohort_receipts"][-1]["checkpoint_sha256"]
        replacements=dict(OLD_SOURCE=self.old["expected_master"],OLD_AUTH=oldhash,
            OLD_PINS=self.old["code_pins"],OLD_REFERENCE=self.old["external_cohort"]["proof_reference"],
            OLD_PROOF=self.f.h.newproof["proof_sha256"],CP=self.o["parent_sha"],
            RECEIPT=c.digest(c.encoded(self.o["cohort_receipts"][-1])),
            SAMPLES=[c.digest(c.encoded(r)) for r in self.o["cohort_receipts"]],
            NATIVE=self.old["external_cohort"]["native18_recovery"]["settlement_sha256"])
        for key,value in replacements.items():
            p=patch.object(self.s,key,value);p.start();self.addCleanup(p.stop)
        p=patch.dict(self.s.POLICY,prior_auth_sha256=oldhash,checkpoint_sha256=self.o["parent_sha"])
        p.start();self.addCleanup(p.stop)
        p=patch.dict(self.s.SPEC,prior_auth=oldhash,checkpoint_sha256=self.o["parent_sha"],
                     receipt_sha256=self.s.RECEIPT);p.start();self.addCleanup(p.stop)
        self.new=copy.deepcopy(self.old);self.new.update(schema="r1000-sip-external-cohort-authorization-v6",
            expected_master="d"*40,account_permission_reference=self.old["account_permission_reference"]+"1")
        self.new["code_pins"][c.REVISION_MODULE]=c.digest((c.ROOT/c.REVISION_MODULE).read_bytes().replace(b"\r\n",b"\n"))
        self.new["external_cohort"].update(proof_reference=self.new["account_permission_reference"],
            source_revision=dict(policy_sha256=self.s.policy_hash(c)))
        self.proof=dict(proof_sha256="f"*64,proof_updated_utc=c.utc().isoformat(),expires_at_utc="2026-10-19T02:08:51Z")

    def test_exact_old_authority_and_full_transitive_pins(self):
        self.assertEqual(c.external_previous(self.new),self.old)
        self.assertEqual(c.validate_authorization(c.external_previous(self.new)),self.s.OLD_AUTH)
        self.assertEqual(c.external_variants(self.new)[-2],self.old)
        self.assertEqual(c.external_transitions(self.new)[-1]["kind"],"SOURCE_REVISION")
        for change in [lambda a:a["code_pins"].pop(c.REVISION_MODULE),
                       lambda a:a["code_pins"].update({c.REVISION_MODULE:"0"*64}),
                       lambda a:a.update(private_root_folder_id="another-root-123"),
                       lambda a:a["external_cohort"]["source_revision"].update(policy_sha256="0"*64),
                       lambda a:a["external_cohort"].update(unknown_transition={})]:
            bad=copy.deepcopy(self.new);change(bad)
            with self.subTest(change=change),self.assertRaises(c.Refused):c.validate_authorization(bad)
        env=dict(GITHUB_REPOSITORY=c.REPO,GITHUB_REF="refs/heads/master",
            GITHUB_SHA=self.new["expected_master"],GITHUB_EVENT_NAME="workflow_dispatch",GITHUB_RUN_ATTEMPT="1")
        with tempfile.TemporaryDirectory() as temp:
            deployed=Path(temp)
            for path in self.new['code_pins']:
                raw=(c.ROOT/path).read_bytes()
                if path==c.REVISION_MODULE:raw=raw.replace(b'\r\n',b'\n')
                target=deployed/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            with patch.dict(os.environ,env,clear=True),patch.object(c,'ROOT',deployed):
                c.verify_worker_source(self.new)
                for remove in (True,False):
                    bad=copy.deepcopy(self.new)
                    if remove:bad["code_pins"].pop(c.REVISION_MODULE)
                    else:bad["code_pins"][c.REVISION_MODULE]="0"*64
                    with self.subTest(remove=remove),self.assertRaises(c.Refused):c.verify_worker_source(bad)
        with patch.dict(os.environ,dict(env,GITHUB_SHA=self.old["expected_master"]),clear=True):
            with self.assertRaisesRegex(c.Refused,"CAMPAIGN_CODE_PINS"):c.verify_worker_source(self.old)
        with patch.object(c,"gh_json",side_effect=AssertionError("No remote reads for old six pins")):
            with self.assertRaisesRegex(c.Refused,"CAMPAIGN_CODE_PINS"):c.external_deployed(self.old)

    def test_actual_model_stays_false_and_only_exact_time_exception_is_accepted(self):
        before=copy.deepcopy(self.o);forecast=c.external_forecast(self.new,self.o)
        self.assertFalse(forecast["fits"]);self.assertEqual(forecast["active_seconds"],38748)
        accepted=self.s.time_acceptance(c,self.new,self.o,forecast)
        self.assertFalse(accepted["forecast_fits"]);self.assertTrue(accepted["actual_limits_unchanged"])
        self.assertEqual(self.o,before)
        for field,value in [("examined",256),("parent_sha","0"*64),("active_seconds",4939)]:
            bad=copy.deepcopy(self.o);bad[field]=value
            with self.subTest(field=field),self.assertRaises(c.Refused):
                self.s.time_acceptance(c,self.new,bad,forecast)
        bad=copy.deepcopy(self.o);bad["remaining"]["drive_bytes"]=forecast["projected"]["drive_bytes"]-1
        with self.assertRaises(c.Refused):self.s.time_acceptance(c,self.new,bad,forecast)
        bad=copy.deepcopy(self.o);bad["cohort_receipts"][0]["usage"]["drive_bytes"]+=1
        with self.assertRaises(c.Refused):self.s.time_acceptance(c,self.new,bad,forecast)
        with self.assertRaises(c.Refused):self.s.time_acceptance(c,self.new,self.o,dict(forecast,active_seconds=38749))
        with self.assertRaises(c.Refused):self.s.time_acceptance(c,self.old,self.o,forecast)
        clock=c.utc
        with patch.object(c,"utc",side_effect=lambda v=None:clock(v) if v is not None else clock("2026-10-19T02:08:51Z")):
            with self.assertRaises(c.Refused):self.s.time_acceptance(c,self.new,self.o,forecast)

    def test_immutable_actual_locator_commitment_is_separate_from_full_auth_hash(self):
        a=self.s.commitment(c,self.new)
        other=copy.deepcopy(self.new);other["account_permission_reference"]+="1"
        other["external_cohort"]["proof_reference"]=other["account_permission_reference"]
        self.assertEqual(a,self.s.commitment(c,other))
        self.assertNotEqual(c.validate_authorization(self.new),c.validate_authorization(other))
        record=c.external_proof_record(self.new)
        self.assertEqual(record["source_revision"]["retained_native_settlement_sha256"],self.s.NATIVE)
        self.assertEqual(record["source_revision"]["policy"]["human_request_sha256"],self.s.REQUEST)
        clock=c.utc().isoformat()
        comment=dict(self.f.h.base.old.comment,id=int(self.new["account_permission_reference"].rsplit("-",1)[1]),
            created_at=clock,updated_at=clock,body="A1_SIP_EXTERNAL_COHORT_CONSENT "+json.dumps(record))
        with patch.object(c,"gh_json",return_value=comment):proof=c.external_proof(self.new)
        self.assertIn("proof_sha256",proof)
        mutations=[lambda x:x.update(updated_at=(c.utc()+timedelta(seconds=1)).isoformat()),
                   lambda x:x.pop("created_at"),lambda x:x.pop("updated_at"),
                   lambda x:(x.pop("created_at"),x.pop("updated_at")),
                   lambda x:x.update(created_at=None),lambda x:x.update(updated_at=None),
                   lambda x:x.update(created_at=None,updated_at=None),
                   lambda x:x.update(created_at=1,updated_at=1)]
        for mutate in mutations:
            bad=copy.deepcopy(comment);mutate(bad)
            with self.subTest(comment=bad),patch.object(c,"gh_json",return_value=bad):
                with self.assertRaisesRegex(c.Refused,"EXTERNAL_SOURCE_REVISION_PROOF"):c.external_proof(self.new)

    def test_first_capture_marker_is_bound_and_cannot_repeat(self):
        forecast=c.external_forecast(self.new,self.o)
        marker=self.s.time_acceptance(c,self.new,self.o,forecast)
        value=dict(examined_before=128,source_revision_policy_sha256=self.s.policy_hash(c),
                   time_forecast_exception=marker)
        self.s.verify_marker(c,self.new,value,self.o)
        for bad in [dict(value,source_revision_policy_sha256="0"*64),dict(value,time_forecast_exception={}),
                    dict(value,examined_before=160)]:
            with self.subTest(bad=bad),self.assertRaises(c.Refused):self.s.verify_marker(c,self.new,bad,self.o)

    def test_worker_rejects_changed_time_basis_before_creating_meter(self):
        nonce=c.PREFIX+"e"*24
        observed=copy.deepcopy(self.o)
        observed.update(active_seconds=4939,external_proof=self.proof,first=c.utc(c.CONTINUATION["first"]),
            runs=[dict(id=i+1,run_attempt=1,head_sha=self.s.OLD_SOURCE,display_title="a1-sip "+nonce) for i in range(21)])
        args=SimpleNamespace(private_root_folder_id=self.new["private_root_folder_id"],
            private_data_folder_id=self.new["private_data_folder_id"],start=self.new["start"],end=self.new["end"],
            max_new_symbols=32,resume_sha256=observed["parent_sha"])
        control=dict(authorization=self.new,nonce=nonce,recovery_run=None,preflight_only=False,external_binding=self.proof)
        env=dict(GITHUB_RUN_ID="99",INPUT_CAMPAIGN_NONCE=nonce,ALPACA_API_KEY="fixture-key",ALPACA_API_SECRET="fixture-secret")
        with patch.dict(os.environ,env,clear=True),patch.object(c,"verify_worker_source"), \
             patch.object(c,"external_history",return_value=observed),patch.object(c,"external_proof",return_value=self.proof), \
             patch.object(c,"worker_deadline",return_value=c.utc()+timedelta(seconds=100)), \
             patch.object(c,"campaign_runs",return_value=observed["runs"]),patch.object(c,"RuntimeMeter") as meter:
            with self.assertRaisesRegex(c.Refused,"EXTERNAL_TIME_FORECAST_ACCEPTANCE"):
                c.external_worker(args,control,Path("unused-synthetic-meter"))
        meter.assert_not_called()

    def make_pair(self):
        root=Path(tempfile.mkdtemp());self.addCleanup(lambda: __import__("shutil").rmtree(root))
        j=c.WorkJournal(root/"cohort",c.NATIVE18_RECOVERY["prior_auth"])
        for i in range(10):
            j.append("SETTLED",run_id=c.NATIVE18_RECOVERY["run_id"],receipt_sha256=c.NATIVE18_RECOVERY["receipt_sha256"])
        p=patch.dict(c.NATIVE18_RECOVERY,cohort_event_sha256=j.parent);p.start();self.addCleanup(p.stop)
        j.close()
        native=dict(prior_auth_sha256=c.NATIVE18_RECOVERY["prior_auth"],**self.proof)
        j=c.WorkJournal(root/"cohort",self.s.OLD_AUTH,native_revision=native)
        j.append("EXTERNAL_NATIVE18_RECOVERY_BOUND",**native)
        for i in range(9):j.append("SETTLED",synthetic=True)
        p=patch.object(self.s,"COHORT_TAIL",j.parent);p.start();self.addCleanup(p.stop)
        j.close()
        family=c.WorkJournal(root/"family",c.external_family_genesis())
        self.addCleanup(family.close)
        for i in range(47):family.append("SETTLED",synthetic=True)
        p=patch.object(self.s,"FAMILY_TAIL",family.parent);p.start();self.addCleanup(p.stop)
        binding=self.s.binding(c,self.new,self.proof)
        j=c.WorkJournal(root/"cohort",c.validate_authorization(self.new),native_revision=native,source_revision=binding)
        self.addCleanup(j.close)
        return j,family,native,binding

    def test_two_durable_events_preserve_prefix_and_once_only_reopen(self):
        j,family,native,binding=self.make_pair()
        before={p:p.read_bytes() for d in [j.directory,family.directory] for p in d.glob("*.json")}
        obs=dict(self.o,external_proof=self.proof)
        c.bind_source_revision(j,family,self.new,obs)
        self.assertEqual((len(j.entries),len(family.entries)),(21,48))
        after={p:p.read_bytes() for d in [j.directory,family.directory] for p in d.glob("*.json")}
        c.bind_source_revision(j,family,self.new,obs)
        self.assertEqual(after,{p:p.read_bytes() for p in after})
        self.assertTrue(all(p.read_bytes()==v for p,v in before.items()))
        j.close()
        reopened=c.WorkJournal(j.directory,c.validate_authorization(self.new),native_revision=native,source_revision=binding)
        self.addCleanup(reopened.close)
        c.bind_source_revision(reopened,family,self.new,obs)
        with self.assertRaises(c.Refused):reopened.append("SOURCE_REVISION_BOUND",**binding)
        with self.assertRaises(c.Refused):c.WorkJournal(reopened.directory,c.validate_authorization(self.new))

    def test_failed_directory_barrier_repairs_exact_visible_first_event_without_dispatch(self):
        j,family,_,_=self.make_pair();obs=dict(self.o,external_proof=self.proof)
        real=c.sync_native18_settlement
        with patch.object(c,"sync_native18_settlement",side_effect=c.Refused("EXTERNAL_NATIVE18_DURABILITY")):
            with self.assertRaises(c.Refused):c.bind_source_revision(j,family,self.new,obs)
        first=(j.directory/"000021.json").read_bytes()
        self.assertEqual(len(family.entries),47)
        c.bind_source_revision(j,family,self.new,obs)
        self.assertEqual(first,(j.directory/"000021.json").read_bytes())
        self.assertEqual((len(j.entries),len(family.entries)),(21,48))
        with patch.object(c,"sync_native18_settlement",side_effect=OSError("synthetic fsync")):
            with self.assertRaises(OSError):c.bind_source_revision(j,family,self.new,obs)



class LiveRunRefusalCorrectionTests(unittest.TestCase):
    """Synthetic authority with actual21/22/23 history shape; no external I/O."""
    def setUp(self):
        self.base=SourceRevisionCP128Tests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.s=self.base.s;self.v6=copy.deepcopy(self.base.new);self.o=copy.deepcopy(self.base.o)
        for key,value in dict(V6_AUTH=c.validate_authorization(self.v6),V6_SOURCE=self.v6['expected_master'],
            V6_PINS=self.v6['code_pins'],V6_REFERENCE=self.v6['account_permission_reference'],V6_PROOF='f'*64).items():
            p=patch.object(self.s,key,value);p.start();self.addCleanup(p.stop)
        self.a=copy.deepcopy(self.v6);self.a.update(schema='r1000-sip-external-cohort-authorization-v7',
            expected_master='e'*40,account_permission_reference=self.v6['account_permission_reference']+'2')
        self.a['external_cohort'].update(proof_reference=self.a['account_permission_reference'],
            source_revision=dict(policy_sha256=self.s.policy_hash(c),refusal_closure_sha256='b'*64,refusal_closure_comment_id=12345))
        self.refused=dict(id=self.s.REFUSAL_RUN,head_sha=self.s.V6_SOURCE,run_attempt=1,
            display_title='a1-sip '+self.s.REFUSAL_NONCE,status='completed',conclusion='failure',created_at='2026-10-18T22:14:28Z')
        self.admin=self.s.refusal_value(c,self.a['external_cohort']['scope'])
        self.o['runs'].append(self.refused);self.o['active_seconds']=5123
        self.o['cohort_receipts'].append(self.admin);self.o['cohort_durations'].append(185)
        self.proof=dict(proof_sha256='a'*64,proof_updated_utc=c.utc().isoformat(),expires_at_utc='2026-10-19T02:08:51+00:00')
        self.o.update(external_proof=self.proof,first=c.utc(c.CONTINUATION['first']))
        self.nonce=c.PREFIX+'e'*24
        self.current=dict(id=999,run_attempt=1,head_sha=self.a['expected_master'],display_title='a1-sip '+self.nonce,
            status='in_progress',conclusion=None,created_at=c.utc().isoformat())

    def live(self):
        o=copy.deepcopy(self.o);o['runs'].append(self.current)
        o.update(current_run=self.current['id'],current_nonce=self.nonce)
        return o

    def test_exact_v6_authority_reconstruction_and_capacity(self):
        self.assertEqual(c.external_previous(self.a),self.v6)
        self.assertEqual(c.validate_authorization(self.v6),self.s.V6_AUTH)
        self.assertEqual(c.external_transitions(self.a)[-1]['kind'],'CORRECTIVE_SOURCE')
        self.assertLessEqual(len(c.encoded(self.a)),15000)
        self.assertLessEqual(len(c.encoded(c.external_proof_record(self.a))),4096)
        for change in [lambda a:a['external_cohort']['source_revision'].update(extra=True),
                       lambda a:a.update(private_root_folder_id='foreign-root-123'),
                       lambda a:a['code_pins'].pop(c.REVISION_MODULE)]:
            a=copy.deepcopy(self.a);change(a)
            with self.assertRaises(c.Refused):c.validate_authorization(a)

    def test_host22_and_worker23_keep_full_canonical_lists_and_same_marker(self):
        before=copy.deepcopy(self.o);host=c.external_forecast(self.a,self.o)
        live=self.live();worker=c.external_forecast(self.a,live)
        self.assertEqual(host,worker);self.assertFalse(host['fits'])
        a=self.s.time_acceptance(c,self.a,self.o,host)
        b=self.s.time_acceptance(c,self.a,live,worker)
        self.assertEqual(a,b);self.assertEqual(a['live_active_seconds'],5123)
        self.assertEqual((len(self.o['runs']),len(live['runs'])),(22,23))
        self.assertEqual(before,self.o)
        self.assertNotIn('new_states',self.admin);self.assertNotIn('rows_verified',self.admin)
        self.assertTrue(self.admin['not_runtime_meter'])
        progress=c.external_progress(self.a,self.o,'VERIFIED')
        self.assertEqual(progress['workflow_dispatches'],22);self.assertEqual(progress['active_seconds'],5123)
        self.assertEqual(progress['rows_verified'],sum(r['rows_verified'] for r in self.base.o['cohort_receipts']))
        self.assertEqual(progress['states']['VALID_COLLECTED'],124)

    def test_original_host21_worker22_boundary_requires_the_bound_current(self):
        host=copy.deepcopy(self.base.o)
        expected=self.s.time_acceptance(c,self.v6,host,c.external_forecast(self.v6,host))
        live=copy.deepcopy(host);r=copy.deepcopy(self.refused)
        r.update(status='in_progress',conclusion=None,created_at=c.utc().isoformat())
        live.update(current_run=self.s.REFUSAL_RUN,current_nonce=self.s.REFUSAL_NONCE,external_proof=self.base.proof)
        live['runs'].append(r)
        self.assertEqual(expected,self.s.time_acceptance(c,self.v6,live,c.external_forecast(self.v6,live)))
        live['current_run']=None
        with self.assertRaises(c.Refused):self.s.time_acceptance(c,self.v6,live,c.external_forecast(self.v6,live))

    def test_refusal_needs_exact_source_control_terminal_jobs_log_and_empty_artifacts(self):
        control=dict(authorization=self.v6,nonce=self.s.REFUSAL_NONCE,preflight_only=False,recovery_run=None,
            external_binding=dict(proof_sha256=self.s.V6_PROOF,proof_updated_utc='2026-10-18T22:11:24+00:00',
                                  expires_at_utc='2026-10-19T02:08:51+00:00'))
        log=('INPUT_CAMPAIGN_CONTROL: '+json.dumps(control)+'\n'+
             '{"status": "BLOCKED", "code": "EXTERNAL_TIME_FORECAST_ACCEPTANCE", "source_admission": false}\n'+
             'No artifacts will be uploaded\n\n').encode()
        blobs={p:(c.ROOT/p).read_bytes().replace(b"\r\n",b"\n") if p==c.REVISION_MODULE
                 else (c.ROOT/p).read_bytes() for p in self.s.V6_PINS}
        jobs=dict(total_count=2,jobs=[dict(id=117804908535,name='offline',status='completed',conclusion='success',
            started_at='2026-10-18T22:14:31Z',completed_at='2026-10-18T22:16:13Z'),
            dict(id=117805290762,name='capture',status='completed',conclusion='failure',
            started_at='2026-10-18T22:16:16Z',completed_at='2026-10-18T22:17:39Z')])
        artifacts=dict(total_count=0,artifacts=[])
        with patch.object(self.s,'REFUSAL_LOG',c.digest(log)):
            value=self.s.verify_refusal(c,self.v6,self.refused,jobs,artifacts,blobs,log)
            self.assertTrue(value['not_runtime_meter']);self.assertEqual(value['active_seconds'],185)
            receipt=dict(payload=dict(source_sha=self.a['expected_master'],code_pins_sha256=c.digest(c.encoded(self.a['code_pins'])),
                                      refusal_evidence_sha256=c.digest(c.encoded(value))))
            with patch.multiple(self.s,V7_AUTH=c.validate_authorization(self.a),V7_SOURCE=self.a['expected_master'],
                V7_PINS=self.a['code_pins'],V7_CLOSURE=c.digest(c.encoded(receipt)),V7_PROOF=self.proof['proof_sha256']):
                self.assertEqual(self.s.verify_sealed_refusal(c,self.a,self.refused,jobs,artifacts,blobs,receipt,self.proof),value)
                for bad in [dict(receipt,payload=dict(receipt['payload'],refusal_evidence_sha256='0'*64)),{}]:
                    with self.assertRaises(c.Refused):self.s.verify_sealed_refusal(c,self.a,self.refused,jobs,artifacts,blobs,bad,self.proof)
                with self.assertRaises(c.Refused):self.s.verify_sealed_refusal(c,self.a,self.refused,jobs,artifacts,blobs,receipt,dict(proof_sha256='0'*64))
            for field,bad in [('run',dict(self.refused,run_attempt=2)),('run',dict(self.refused,display_title='foreign')),
                ('jobs',dict(jobs,total_count=1)),('artifacts',dict(total_count=1,artifacts=[{}])),
                ('blobs',dict(blobs,**{c.REVISION_MODULE:b'foreign source'})),('log',log+b'changed')]:
                values=dict(run=self.refused,jobs=jobs,artifacts=artifacts,source_blobs=blobs,log=log)
                values['source_blobs' if field=='blobs' else field]=bad
                with self.subTest(field=field),self.assertRaises(c.Refused):self.s.verify_refusal(c,self.v6,**values)

    def test_foreign_current_duplicate_future_cost_reset_and_expiry_refuse(self):
        live=self.live();forecast=c.external_forecast(self.a,live)
        mutations=[lambda x:x.update(current_run=998),lambda x:x.update(current_nonce=c.PREFIX+'d'*24),
            lambda x:x['runs'][-1].update(head_sha='d'*40),lambda x:x['runs'][-1].update(run_attempt=2),
            lambda x:x['runs'][-1].update(status='completed',conclusion='success'),
            lambda x:x['runs'].append(copy.deepcopy(x['runs'][-1])),lambda x:x['runs'].pop(21),
            lambda x:x.update(active_seconds=4938),lambda x:x['cohort_durations'].__setitem__(-1,0),
            lambda x:x['cohort_receipts'][-1]['usage'].update(provider_gets=1)]
        for mutate in mutations:
            bad=copy.deepcopy(live);mutate(bad)
            with self.subTest(mutate=mutate),self.assertRaises(c.Refused):self.s.time_acceptance(c,self.a,bad,forecast)
        with patch.object(c,'active_limit',return_value=5123+7799):
            with self.assertRaises(c.Refused):self.s.time_acceptance(c,self.a,live,forecast)
        clock=c.utc
        with patch.object(c,'utc',side_effect=lambda x=None:clock(x) if x is not None else clock('2026-10-19T02:08:51Z')):
            with self.assertRaises(c.Refused):self.s.time_acceptance(c,self.a,live,forecast)

    def test_actual_worker_current_shape_reaches_meter_only_after_valid_guard(self):
        class ReachedMeter(Exception):pass
        live=self.live();args=SimpleNamespace(private_root_folder_id=self.a['private_root_folder_id'],
            private_data_folder_id=self.a['private_data_folder_id'],start=self.a['start'],end=self.a['end'],
            max_new_symbols=32,resume_sha256=live['parent_sha'])
        control=dict(authorization=self.a,nonce=self.nonce,recovery_run=None,preflight_only=False,external_binding=self.proof)
        env=dict(GITHUB_RUN_ID='999',INPUT_CAMPAIGN_NONCE=self.nonce,ALPACA_API_KEY='fixture-key',ALPACA_API_SECRET='fixture-secret')
        from tools import twelve_private_capture as drive
        with patch.dict(os.environ,env,clear=True),patch.object(c,'verify_worker_source'), \
             patch.object(c,'external_history',return_value=live),patch.object(c,'external_proof',return_value=self.proof), \
             patch.object(c,'campaign_runs',return_value=live['runs']), \
             patch.object(c,'worker_deadline',return_value=c.utc()+timedelta(seconds=90)), \
             patch.object(c,'RuntimeMeter',side_effect=ReachedMeter) as meter, \
             patch.object(drive,'OwnerDrive',side_effect=AssertionError('No data I/O')) as owner:
            with self.assertRaises(ReachedMeter):c.external_worker(args,control,Path('not-created'))
            meter.assert_called_once();owner.assert_not_called()

    def comment(self,record,tag,id=345):
        clock=c.utc().isoformat()
        return dict(id=id,issue_url=f'https://api.github.com/repos/{c.REPO}/issues/448',author_association='OWNER',
            user=dict(type='User',id=123),created_at=clock,updated_at=clock,body=tag+json.dumps(record))

    def test_first_corrective_host_reaches_one_bounded_post_after_bound_parent(self):
        """Host dispatch boundary; the separate real-journal test proves both barriers."""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);budget=root/'canonical-journal';budget.mkdir()
            state=root/('external-cohort-'+self.a['external_cohort']['scope']['namespace']);state.mkdir()
            inp=root/'input.csv';inp.write_bytes(self.a['external_cohort']['input_csv'].encode())
            class Journal:
                def __init__(this,entries):this.entries=entries;this.directory=state;this.refusal_revision={'fixture':True}
                def reconcile(this,runs):pass
                def close(this):pass
                def append(this,kind,**data):this.entries.append(dict(kind=kind,**data))
            binding=dict(scope=self.a['external_cohort']['scope'],
                genesis_sha256=c.external_genesis(self.a['external_cohort']['scope']),**self.proof)
            first=dict(kind='EXTERNAL_COHORT_BOUND',recorded_utc=self.proof['proof_updated_utc'],**binding)
            journal=Journal([first,dict(kind='REFUSAL_SOURCE_BOUND')]);family=Journal([])
            observed=dict(self.o,cohort_runs=[self.refused]);posts=[]
            def post(args,**kw):
                self.assertEqual(args[1:3],['workflow','run'])
                data=json.loads(kw['input']);posts.append(data)
                self.assertEqual(data['max_new_symbols'],'32')
                self.assertEqual(data['resume_sha256'],self.s.CP)
                self.assertEqual(json.loads(data['campaign_control'])['authorization'],self.a)
                return SimpleNamespace(returncode=1)  # Unknown POST retains both reservations.
            with patch.object(c,'local_reject_recovery',return_value={}), \
                 patch.object(c,'WorkJournal',return_value=Journal([])),patch.object(c,'verify_external_budget_journal'), \
                 patch.object(c,'external_proof',return_value=self.proof), \
                 patch.object(c,'external_family_registry',return_value=family), \
                 patch.object(c,'external_journal',return_value=journal), \
                 patch.object(c,'external_history',return_value=observed), \
                 patch.object(c,'reconcile_external_family',return_value=None),patch.object(c,'bind_source_revision') as bind, \
                 patch.object(c,'external_deployed'),patch.object(c,'campaign_runs',return_value=observed['runs']), \
                 patch.object(c,'settled_parent',return_value=dict(file_id='fixture-cp128',sha256=self.s.CP)), \
                 patch.object(c.subprocess,'run',side_effect=post), \
                 self.assertRaisesRegex(c.Refused,'CAMPAIGN_DISPATCH_UNCERTAIN'):
                c.external_host(self.a,state,inp,budget,root/'unused',None,16)
            bind.assert_called_once();self.assertEqual(len(posts),1)
            self.assertEqual(journal.entries[-1]['kind'],'RESERVED')
            self.assertEqual(family.entries[-1]['kind'],'RESERVED')

    def test_sealed_closure_is_not_meter_and_rebound_hash_or_null_clock_refuses(self):
        grant=self.comment(self.s.grant_record(c,self.a['expected_master'],self.a['code_pins'],self.a['external_cohort']['scope']),
                           'A1_SIP_NO_METER_REFUSAL_AUTHORIZATION ')
        payload=self.s.closure_payload(c,self.a['expected_master'],self.a['code_pins'],self.a['external_cohort']['scope'],grant)
        clock=c.utc().isoformat();receipt=dict(schema='a1-sip-exact-no-meter-refusal-receipt-v1',payload=payload)
        for field,family in [('cohort_event',False),('family_event',True)]:
            e=self.s.closure_entry(c,payload,clock,family)
            receipt[field]=dict(recorded_utc=clock,sha256=c.digest(c.encoded(e)))
        seal=self.comment(receipt,'A1_SIP_NO_METER_REFUSAL_CLOSED ',12345)
        a=copy.deepcopy(self.a);a['external_cohort']['source_revision']['refusal_closure_sha256']=c.digest(c.encoded(receipt))
        self.s.verify_closure_receipt(c,a,receipt,grant,seal)
        for bad in [dict(grant,created_at=None,updated_at=None),dict(grant,updated_at=(c.utc()+timedelta(seconds=1)).isoformat())]:
            with self.assertRaises(c.Refused):self.s.verify_closure_receipt(c,a,receipt,bad,seal)
        bad=copy.deepcopy(receipt);bad['payload']['actual_job_seconds']=0
        a['external_cohort']['source_revision']['refusal_closure_sha256']=c.digest(c.encoded(bad))
        badseal=self.comment(bad,'A1_SIP_NO_METER_REFUSAL_CLOSED ',12345)
        with self.assertRaises(c.Refused):self.s.verify_closure_receipt(c,a,bad,grant,badseal)
        event=self.s.closure_entry(c,payload,clock)
        binding=self.s.correction_binding(c,self.a,self.proof)
        wrong=dict(event,sequence=25,kind='REFUSAL_SOURCE_BOUND',**binding)
        with self.assertRaises(c.Refused):self.s.verify_correction_entry(c,wrong,binding,receipt)

    def test_accounting_closure_once_preserves_prefix_and_requires_both_barriers(self):
        j,family,native,binding=self.base.make_pair()
        c.bind_source_revision(j,family,self.v6,dict(self.base.o,external_proof=self.base.proof))
        for target in (j,family):
            data=dict(nonce=self.s.REFUSAL_NONCE,remaining=self.o['remaining'],parent_checkpoint_sha256=self.s.CP)
            if target is family:data.update(capture_auth_sha256=self.s.V6_AUTH,scope=self.a['external_cohort']['scope'])
            target.append('RESERVED',**data)
            data=dict(nonce=self.s.REFUSAL_NONCE,run_id=self.s.REFUSAL_RUN)
            if target is family:data.update(capture_auth_sha256=self.s.V6_AUTH,scope=self.a['external_cohort']['scope'])
            target.append('RUN_ASSIGNED',**data)
        for name,val in [('COHORT23',j.parent),('FAMILY50',family.parent)]:
            p=patch.object(self.s,name,val);p.start();self.addCleanup(p.stop)
        root=j.directory.parent;j.close();family.close()
        state=root/('external-cohort-'+self.a['external_cohort']['scope']['namespace'])
        j.directory.rename(state)
        fdir=family.directory;budget=root/'canonical-journal';budget.mkdir()
        before={p:p.read_bytes() for d in [state,fdir] for p in d.glob('*.json')}
        grant=self.comment(self.s.grant_record(c,self.a['expected_master'],self.a['code_pins'],self.a['external_cohort']['scope']),
                           'A1_SIP_NO_METER_REFUSAL_AUTHORIZATION ')
        authpath=root/'old-auth.json';authpath.write_bytes(c.encoded(self.v6))
        grantpath=root/'grant.json';grantpath.write_bytes(c.encoded(dict(source_sha=self.a['expected_master'],
            code_pins=self.a['code_pins'],grant_reference=f'https://github.com/{c.REPO}/issues/448#issuecomment-345')))
        inp=root/'input.csv';inp.write_bytes(self.a['external_cohort']['input_csv'].encode())
        args=SimpleNamespace(authorization=authpath,refusal_close_authorization=grantpath,recovery_run=None,max_batches=None,
            account_permission_reference=None,continuation_receipt=None,native18_deployed_master=None,
            budget_state_dir=budget,state_dir=state,cohort_input=inp,predispatch_recovery=root/'unused')
        obs=copy.deepcopy(self.o);obs['external_proof']=self.base.proof
        obs['epoch_proofs']={c.validate_authorization(v):self.base.proof for v in c.external_variants(self.v6)}
        real_journal=c.WorkJournal
        class Global:
            def close(self):pass
        def factory(directory,*a,**kw):
            return Global() if Path(directory)==budget else real_journal(directory,*a,**kw)
        with patch.object(c,'WorkJournal',side_effect=factory),patch.object(c,'external_deployed'), \
             patch.object(c,'gh_json',return_value=grant),patch.object(c,'local_reject_recovery',return_value={}), \
             patch.object(c,'verify_external_budget_journal'),patch.object(c,'external_history',return_value=obs), \
             patch.object(c,'external_family_registry',side_effect=lambda *a,**kw:real_journal(fdir,c.external_family_genesis())), \
             patch.object(c,'external_journal',side_effect=lambda directory,a,proof,**kw:real_journal(directory,
                 c.validate_authorization(a),native_revision=native,source_revision=binding)), \
             patch.object(c,'campaign_runs',return_value=obs['runs']), \
             patch.object(c,'RuntimeMeter',side_effect=AssertionError('No meter issuance')):
            result=c.refusal_accounting_host(args)
            self.assertEqual(result['actual_active_seconds'],5123)
            self.assertEqual(result['actual_dispatches'],22)
            saved={p:p.read_bytes() for d in [state,fdir] for p in d.glob('*.json')}
            again=c.refusal_accounting_host(args)
            self.assertEqual(result,again);self.assertEqual(saved,{p:p.read_bytes() for p in saved})
        self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))
        receipt=c.bounded_json(root/'REFUSAL_CLOSURE_RECEIPT.private.json')
        seal=self.comment(receipt,'A1_SIP_NO_METER_REFUSAL_CLOSED ',12345)
        a=copy.deepcopy(self.a);a['external_cohort']['source_revision']['refusal_closure_sha256']=c.digest(c.encoded(receipt))
        self.s.verify_closure_receipt(c,a,receipt,grant,seal)
        correction=self.s.correction_binding(c,a,self.proof)
        oldbinding=self.s.binding(c,self.v6,self.base.proof)
        corrected=real_journal(state,c.validate_authorization(a),native_revision=native,source_revision=oldbinding,
            refusal_revision=correction,refusal_closure=receipt);self.addCleanup(corrected.close)
        shared=real_journal(fdir,c.external_family_genesis());self.addCleanup(shared.close)
        # The cohort directory barrier must complete before family52 exists.
        with patch.object(c,'sync_native18_settlement',side_effect=c.Refused('EXTERNAL_NATIVE18_DURABILITY')):
            with self.assertRaises(c.Refused):c.bind_source_revision(corrected,shared,a,dict(obs,external_proof=self.proof))
        self.assertEqual((len(corrected.entries),len(shared.entries)),(24,51))
        c.bind_source_revision(corrected,shared,a,dict(obs,external_proof=self.proof))
        self.assertEqual((len(corrected.entries),len(shared.entries)),(25,52))
        with self.assertRaises(c.Refused):corrected.append('REFUSAL_SOURCE_BOUND',**correction)


class Human24hValidityTests(unittest.TestCase):
    """Synthetic prospective consent; production dates/caps stay fixed."""
    def setUp(self):
        self.p=LiveRunRefusalCorrectionTests();self.p.setUp();self.addCleanup(self.p.doCleanups)
        self.s=self.p.s;self.v7=copy.deepcopy(self.p.a)
        for name,value in dict(V7_AUTH=c.validate_authorization(self.v7),V7_SOURCE=self.v7['expected_master'],
            V7_PINS=self.v7['code_pins'],V7_REFERENCE=self.v7['account_permission_reference'],V7_PROOF=self.p.proof['proof_sha256'],
            V7_CLOSURE=self.v7['external_cohort']['source_revision']['refusal_closure_sha256'],
            V7_CLOSURE_COMMENT=self.v7['external_cohort']['source_revision']['refusal_closure_comment_id']).items():
            patcher=patch.object(self.s,name,value);patcher.start();self.addCleanup(patcher.stop)
        self.a=copy.deepcopy(self.v7);self.grant_id=7000000001
        self.grant_ref=f'https://github.com/{c.REPO}/issues/448#issuecomment-{self.grant_id}'
        self.a.update(schema='r1000-sip-external-cohort-authorization-v8',expected_master='f'*40,
                      account_permission_reference=self.grant_ref)
        self.a['external_cohort'].update(proof_reference=self.grant_ref,source_revision={'validity_reference':self.grant_ref})
        clock=c.utc;self.now=clock('2026-10-19T03:05:00Z')
        patcher=patch.object(c,'utc',side_effect=lambda value=None:clock(value) if value is not None else self.now)
        patcher.start();self.addCleanup(patcher.stop)
        self.server_calls=[];self.issue()

    def comment(self,value,tag,id,clock):
        return dict(id=id,issue_url=f'https://api.github.com/repos/{c.REPO}/issues/448',author_association='OWNER',
            user=dict(type='User',id=123),created_at=clock,updated_at=clock,body=tag+json.dumps(value,separators=(',',':')))

    def issue(self):
        record=self.s.validity_record(c,self.a['expected_master'],self.a['code_pins'],self.a['external_cohort']['scope'])
        self.grant=self.comment(record,'A1_SIP_HUMAN24H_VALIDITY ',self.grant_id,
            (c.utc(self.s.VALIDITY_START)+timedelta(seconds=1)).isoformat())
        terms=c.external_proof_record(self.a)
        self.server_calls.append('POST complete terms')
        returned_id=9000000000+len(self.server_calls)  # Allocated by the fixture server after the body exists.
        self.owner=self.comment(terms,'A1_SIP_EXTERNAL_COHORT_CONSENT ',returned_id,
            (c.utc(self.s.VALIDITY_START)+timedelta(seconds=2)).isoformat())
        self.a['account_permission_reference']=f'https://github.com/{c.REPO}/issues/448#issuecomment-{returned_id}'
        self.a['external_cohort']['proof_reference']=self.a['account_permission_reference']
        with self.proof_context():self.proof=c.external_proof(self.a)
        self.grant_proof=self.s.verify_validity_grant(c,self.a,self.grant)

    def proof_context(self,grant=None,owner=None):
        comments={self.grant_id:grant or self.grant,self.owner['id']:owner or self.owner}
        return patch.object(c,'gh_json',side_effect=lambda path:comments[int(path.rsplit('/',1)[1])])

    def observed(self,live=False):
        result=copy.deepcopy(self.p.o);result['external_proof']=self.proof
        result['epoch_proofs'].update({self.s.V7_AUTH:self.p.proof,self.s.V6_AUTH:self.p.base.proof})
        if live:
            self.nonce=c.PREFIX+'b'*24
            run=dict(id=1001,run_attempt=1,head_sha=self.a['expected_master'],display_title='a1-sip '+self.nonce,
                created_at=self.now.isoformat(),status='in_progress',conclusion=None)
            result['runs'].append(run);result.update(current_run=1001,current_nonce=self.nonce)
        return result

    def test_exact_old_full_authority_capacity_and_fixed_prospective_window(self):
        self.assertEqual(c.external_previous(self.a),self.v7)
        self.assertEqual(c.validate_authorization(self.v7),self.s.V7_AUTH)
        self.assertEqual(self.s.VALIDITY_START,'2026-10-19T02:59:53Z')
        self.assertEqual(self.s.VALIDITY_END,'2026-10-20T02:59:53Z')
        self.assertEqual(c.utc(self.s.VALIDITY_END)-c.utc(self.s.VALIDITY_START),timedelta(hours=24))
        self.assertLessEqual(len(c.encoded(self.a)),15000)
        self.assertLessEqual(len(c.encoded(c.external_proof_record(self.a))),4096)
        self.assertLessEqual(len(c.encoded(self.s.validity_record(c,self.a['expected_master'],self.a['code_pins'],self.a['external_cohort']['scope']))),4096)
        for change in [lambda a:a['external_cohort']['source_revision'].update(expires_at_utc='2099-01-01T00:00:00Z'),
            lambda a:a['limits'].update(provider_gets=2001),lambda a:a.update(end='2026-10-15'),
            lambda a:a['external_cohort']['scope'].update(namespace='foreign'),lambda a:a['code_pins'].pop(c.REVISION_MODULE)]:
            bad=copy.deepcopy(self.a);change(bad)
            with self.subTest(change=change),self.assertRaises(c.Refused):c.validate_authorization(bad)

    def test_before_approval_expired_gap_exact_end_and_old_authority_still_refuse(self):
        for when in ['2026-10-19T02:08:50Z','2026-10-19T02:08:51Z','2026-10-19T02:59:52Z',self.s.VALIDITY_END,'2026-10-20T03:00:00Z']:
            self.now=c.utc(when)
            with self.subTest(when=when),self.assertRaises(c.Refused):self.s.require_window(c,self.a)
        for when in [self.s.VALIDITY_START,'2026-10-20T02:59:52Z']:
            self.now=c.utc(when);self.s.require_window(c,self.a)
        self.now=c.utc('2026-10-19T03:05:00Z')
        with self.assertRaises(c.Refused):self.s.require_window(c,self.v7)

    def test_real_returned_locator_full_proof_and_no_edit_clock_binding(self):
        before=c.validate_authorization(self.a);commitment=self.s.commitment(c,self.a);proof=self.proof
        self.issue()
        self.assertNotEqual(c.validate_authorization(self.a),before)
        self.assertEqual(self.s.commitment(c,self.a),commitment)
        self.assertNotEqual(self.proof['proof_sha256'],proof['proof_sha256'])
        self.assertEqual(c.external_previous(self.a),self.v7)
        for bad in [dict(self.grant,created_at=None,updated_at=None),dict(self.grant,updated_at=self.now.isoformat()),
                    dict(self.grant,created_at='2026-10-19T02:59:52Z',updated_at='2026-10-19T02:59:52Z'),
                    dict(self.grant,created_at='2099-01-01T00:00:00Z',updated_at='2099-01-01T00:00:00Z'),
                    dict(self.grant,user=dict(type='User',id=124))]:
            with self.subTest(bad=bad),self.proof_context(grant=bad),self.assertRaises(c.Refused):c.external_proof(self.a)
        changed=dict(self.owner,updated_at=self.now.isoformat())
        with self.proof_context(owner=changed),self.assertRaises(c.Refused):c.external_proof(self.a)

    def test_canonical_version_jump_only_at_exact_closed_debited_parent(self):
        observed=self.observed();state=dict(examined=128,parent=self.s.CP,receipts=observed['cohort_receipts'],version=2,named_failures=set())
        transitions=c.external_transitions(self.a)
        self.assertIsNone(self.s.revision_recovery(c,self.a,state,4,transitions,observed['used'],5123,observed['runs'],observed['epoch_proofs']))
        for mutate in [lambda x:x.update(examined=127),lambda x:x.update(parent='0'*64),
                       lambda x:x.update(version=1),lambda x:x.update(version=5)]:
            bad=copy.deepcopy(state);mutate(bad)
            with self.subTest(mutate=mutate),self.assertRaises(c.Refused):
                self.s.revision_recovery(c,self.a,bad,4,transitions,observed['used'],5123,observed['runs'],observed['epoch_proofs'])
        for active in [4938,5122,5124]:
            with self.subTest(active=active),self.assertRaises(c.Refused):
                self.s.revision_recovery(c,self.a,state,4,transitions,observed['used'],active,observed['runs'],observed['epoch_proofs'])
        used=dict(observed['used'],provider_gets=0)
        with self.assertRaises(c.Refused):self.s.verify_validity_parent(c,self.a,state,used,5123,observed['runs'],observed['epoch_proofs'])
        self.assertIsNone(self.s.revision_recovery(c,self.a,dict(state,version=4),4,transitions,used,6000,[],{}))

    def test_live_worker23_retains_original_clock_and_reaches_meter_with_new_deadline(self):
        class ReachedMeter(Exception):pass
        observed=self.observed(True);first=c.utc(c.CONTINUATION['first'])
        observed['first']=first
        args=SimpleNamespace(private_root_folder_id=self.a['private_root_folder_id'],private_data_folder_id=self.a['private_data_folder_id'],
            start=self.a['start'],end=self.a['end'],max_new_symbols=32,resume_sha256=observed['parent_sha'])
        control=dict(authorization=self.a,nonce=self.nonce,recovery_run=None,preflight_only=False,external_binding=self.proof)
        env=dict(GITHUB_RUN_ID='1001',INPUT_CAMPAIGN_NONCE=self.nonce,ALPACA_API_KEY='fixture-key',ALPACA_API_SECRET='fixture-secret')
        with patch.dict(os.environ,env,clear=True),patch.object(c,'verify_worker_source'), \
             patch.object(c,'external_history',return_value=observed),patch.object(c,'external_proof',return_value=self.proof), \
             patch.object(c,'campaign_runs',return_value=observed['runs']), \
             patch.object(c,'worker_deadline',return_value=self.now+timedelta(seconds=90)) as deadline, \
             patch.object(c,'RuntimeMeter',side_effect=ReachedMeter) as meter, \
             patch.object(drive_module,'OwnerDrive',side_effect=AssertionError('No data I/O')) as owner:
            with self.assertRaises(ReachedMeter):c.external_worker(args,control,Path('not-created'))
        deadline.assert_called_once_with(1001,first,c.utc(self.s.VALIDITY_END));meter.assert_called_once();owner.assert_not_called()
        identity=meter.call_args.args[3]
        self.assertEqual(identity['validity_authority_sha256'],self.s.VALIDITY_AUTHORITY)
        self.assertEqual(identity['validity_expires_at_utc'],self.s.VALIDITY_END)
        self.assertFalse(identity['time_forecast_exception']['forecast_fits'])
        self.assertEqual(observed['active_seconds'],5123);self.assertEqual(len(observed['runs']),23)
        self.assertEqual(first,c.utc('2026-10-17T02:08:51Z'))

    def test_run_clocks_receipt_binding_and_actual_job_deadline_clamp(self):
        observed=self.observed(True);run=observed['runs'][-1]
        value=dict(validity_authority_sha256=self.s.VALIDITY_AUTHORITY,validity_not_before_utc=self.s.VALIDITY_START,
                   validity_expires_at_utc=self.s.VALIDITY_END)
        self.s.verify_validity_run(c,self.a,run,self.proof,value)
        for when in ['2026-10-19T02:30:00Z',self.s.VALIDITY_END,'2099-01-01T00:00:00Z']:
            with self.subTest(when=when),self.assertRaises(c.Refused):self.s.verify_validity_run(c,self.a,dict(run,created_at=when),self.proof,value)
        with self.assertRaises(c.Refused):self.s.verify_validity_run(c,self.a,run,self.proof,dict(value,validity_authority_sha256='0'*64))
        self.now=c.utc(self.s.VALIDITY_END)-timedelta(seconds=1)
        jobs=dict(total_count=1,jobs=[dict(name='capture',status='in_progress',started_at=(self.now-timedelta(seconds=59)).isoformat())])
        with patch.object(c,'gh_json',return_value=jobs):
            self.assertEqual(c.worker_deadline(1001,c.utc(c.CONTINUATION['first']),c.utc(self.s.VALIDITY_END)),c.utc(self.s.VALIDITY_END))
            self.assertEqual(c.worker_deadline(1001,c.utc(c.CONTINUATION['first'])),c.utc(c.CONTINUATION['first'])+timedelta(hours=48))

    def test_terminal_historical_marker_after_fixed_end_uses_actual_run_clock_only(self):
        observed=self.observed();observed['epoch_proofs'][c.validate_authorization(self.a)]=self.proof
        marker=self.s.time_acceptance(c,self.a,observed,c.external_forecast(self.a,observed))
        value=dict(examined_before=128,run_id=1001,source_revision_policy_sha256=self.s.policy_hash(c),
                   time_forecast_exception=marker)
        run=dict(id=1001,run_attempt=1,head_sha=self.a['expected_master'],created_at=self.now.isoformat())
        self.now=c.utc(self.s.VALIDITY_END)+timedelta(seconds=1)
        self.s.verify_marker(c,self.a,value,observed,run)
        with self.assertRaises(c.Refused):self.s.require_window(c,self.a)
        with self.assertRaises(c.Refused):self.s.time_acceptance(c,self.a,observed,c.external_forecast(self.a,observed))
        for bad in [None,dict(run,id=1002),dict(run,head_sha='0'*40),dict(run,run_attempt=2),
                    dict(run,created_at=self.s.VALIDITY_END),dict(run,created_at='2026-10-19T02:30:00Z')]:
            with self.subTest(run=bad),self.assertRaises(c.Refused):self.s.verify_marker(c,self.a,value,observed,bad)

    def closed_pair(self):
        """Retained v6/v7 prefixes built at their original clock, never renewed."""
        current=self.now;self.now=c.utc('2026-10-18T22:30:00Z')
        j,family,native,source=self.p.base.make_pair()
        c.bind_source_revision(j,family,self.p.v6,dict(self.p.base.o,external_proof=self.p.base.proof))
        for target in (j,family):
            data=dict(nonce=self.s.REFUSAL_NONCE,remaining=self.p.o['remaining'],parent_checkpoint_sha256=self.s.CP)
            if target is family:data.update(capture_auth_sha256=self.s.V6_AUTH,scope=self.a['external_cohort']['scope'])
            target.append('RESERVED',**data)
            data=dict(nonce=self.s.REFUSAL_NONCE,run_id=self.s.REFUSAL_RUN)
            if target is family:data.update(capture_auth_sha256=self.s.V6_AUTH,scope=self.a['external_cohort']['scope'])
            target.append('RUN_ASSIGNED',**data)
        for name,value in [('COHORT23',j.parent),('FAMILY50',family.parent)]:
            patcher=patch.object(self.s,name,value);patcher.start();self.addCleanup(patcher.stop)
        grant=self.p.comment(self.s.grant_record(c,self.v7['expected_master'],self.v7['code_pins'],self.a['external_cohort']['scope']),
                             'A1_SIP_NO_METER_REFUSAL_AUTHORIZATION ')
        payload=self.s.closure_payload(c,self.v7['expected_master'],self.v7['code_pins'],self.a['external_cohort']['scope'],grant)
        receipt=dict(schema='a1-sip-exact-no-meter-refusal-receipt-v1',payload=payload)
        for target,field in [(j,'cohort_event'),(family,'family_event')]:
            target.append('NO_METER_REFUSAL_CLOSED',**payload)
            receipt[field]=dict(recorded_utc=target.entries[-1]['recorded_utc'],sha256=target.parent)
        self.v7['external_cohort']['source_revision']['refusal_closure_sha256']=c.digest(c.encoded(receipt))
        for name,value in [('V7_CLOSURE',c.digest(c.encoded(receipt))),('V7_AUTH',c.validate_authorization(self.v7))]:
            patcher=patch.object(self.s,name,value);patcher.start();self.addCleanup(patcher.stop)
        correction=self.s.correction_binding(c,self.v7,self.p.proof)
        path=j.directory;j.close()
        kw=dict(native_revision=native,source_revision=source,refusal_revision=correction,refusal_closure=receipt)
        j=c.WorkJournal(path,self.s.V7_AUTH,**kw)
        c.bind_source_revision(j,family,self.v7,dict(self.p.o,external_proof=self.p.proof))
        self.assertEqual((len(j.entries),len(family.entries)),(25,52))
        for name,value in [('V7_COHORT',j.parent),('V7_FAMILY',family.parent)]:
            patcher=patch.object(self.s,name,value);patcher.start();self.addCleanup(patcher.stop)
        prefix={p:p.read_bytes() for directory in [j.directory,family.directory] for p in directory.glob('*.json')}
        j.close();self.now=current;self.issue()
        kw['validity_revision']=self.s.validity_binding(c,self.a,self.proof,self.grant_proof)
        j=c.WorkJournal(path,c.validate_authorization(self.a),**kw);self.addCleanup(j.close)
        return j,family,kw,prefix

    def test_two_new_durable_barriers_reopen_once_and_preserve_every_old_byte(self):
        j,family,kw,prefix=self.closed_pair();observed=self.observed()
        def fail_cohort(path):
            if Path(path).parent==j.directory and Path(path).name=='000026.json':raise c.Refused('SYNTHETIC_BARRIER')
        with patch.object(c,'validity_grant_proof',return_value=self.grant_proof):
            with patch.object(c,'sync_native18_settlement',side_effect=fail_cohort),self.assertRaisesRegex(c.Refused,'SYNTHETIC_BARRIER'):
                c.bind_source_revision(j,family,self.a,observed)
            self.assertEqual((len(j.entries),len(family.entries)),(26,52))
            path=j.directory;j.close();j=c.WorkJournal(path,c.validate_authorization(self.a),**kw);self.addCleanup(j.close)
            def fail_family(path):
                if Path(path).parent==family.directory and Path(path).name=='000053.json':raise c.Refused('SYNTHETIC_BARRIER')
            with patch.object(c,'sync_native18_settlement',side_effect=fail_family),self.assertRaisesRegex(c.Refused,'SYNTHETIC_BARRIER'):
                c.bind_source_revision(j,family,self.a,observed)
            self.assertEqual((len(j.entries),len(family.entries)),(26,53))
            family_path=family.directory;family.close();family=c.WorkJournal(family_path,c.external_family_genesis());self.addCleanup(family.close)
            c.bind_source_revision(j,family,self.a,observed)
            after={p:p.read_bytes() for directory in [j.directory,family.directory] for p in directory.glob('*.json')}
            c.bind_source_revision(j,family,self.a,observed)
            self.assertEqual(after,{p:p.read_bytes() for p in after})
        self.assertTrue(all(p.read_bytes()==raw for p,raw in prefix.items()))
        self.assertEqual((len(j.entries),len(family.entries)),(26,53))
        with self.assertRaises(c.Refused):j.append('VALIDITY_SOURCE_BOUND',**j.validity_revision)
        bad=copy.deepcopy(j.entries[25]);bad['new_expiry_utc']='2099-01-01T00:00:00Z'
        with self.assertRaises(c.Refused):self.s.verify_validity_entry(c,bad,j.validity_revision)

    def test_first_v8_host_reaches_one_exact32_post_after_new_bound_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);budget=root/'canonical-journal';budget.mkdir()
            state=root/('external-cohort-'+self.a['external_cohort']['scope']['namespace']);state.mkdir()
            inp=root/'input.csv';inp.write_bytes(self.a['external_cohort']['input_csv'].encode())
            class Journal:
                def __init__(this,entries):this.entries=entries;this.directory=state;this.validity_revision={'fixture':True}
                def reconcile(this,runs):pass
                def close(this):pass
                def append(this,kind,**data):this.entries.append(dict(kind=kind,**data))
            first=dict(kind='EXTERNAL_COHORT_BOUND',recorded_utc=self.proof['proof_updated_utc'],
                scope=self.a['external_cohort']['scope'],genesis_sha256=c.external_genesis(self.a['external_cohort']['scope']),**self.proof)
            journal=Journal([first,dict(kind='VALIDITY_SOURCE_BOUND')]);family=Journal([])
            observed=dict(self.observed(),cohort_runs=[self.p.refused]);posts=[]
            def post(args,**kw):
                self.assertEqual(args[1:3],['workflow','run']);data=json.loads(kw['input']);posts.append(data)
                self.assertEqual(data['max_new_symbols'],'32');self.assertEqual(data['resume_sha256'],self.s.CP)
                self.assertEqual(json.loads(data['campaign_control'])['authorization'],self.a)
                return SimpleNamespace(returncode=1)
            with patch.object(c,'local_reject_recovery',return_value={}),patch.object(c,'WorkJournal',return_value=Journal([])), \
                 patch.object(c,'verify_external_budget_journal'),patch.object(c,'external_proof',return_value=self.proof), \
                 patch.object(c,'external_family_registry',return_value=family),patch.object(c,'external_journal',return_value=journal), \
                 patch.object(c,'external_history',return_value=observed),patch.object(c,'reconcile_external_family',return_value=None), \
                 patch.object(c,'bind_source_revision'),patch.object(c,'external_deployed'), \
                 patch.object(c,'campaign_runs',return_value=observed['runs']), \
                 patch.object(c,'settled_parent',return_value=dict(file_id='fixture-cp128',sha256=self.s.CP)), \
                 patch.object(c.subprocess,'run',side_effect=post),self.assertRaisesRegex(c.Refused,'CAMPAIGN_DISPATCH_UNCERTAIN'):
                c.external_host(self.a,state,inp,budget,root/'unused',None,16)
            self.assertEqual(len(posts),1);self.assertEqual(journal.entries[-1]['kind'],'RESERVED')
            self.assertEqual(family.entries[-1]['kind'],'RESERVED')


class ControlReadFailureTests(unittest.TestCase):
    """Synthetic28/55 closure and returned-ID consent; no external data I/O."""
    def setUp(self):
        self.p=Human24hValidityTests();self.p.setUp();self.addCleanup(self.p.doCleanups)
        self.s=self.p.s;self.p.now=c.utc('2026-10-19T06:00:00Z')
        self.patch_v8();self.comments={};self.creates=[]

    def patch_value(self,name,value):
        p=patch.object(self.s,name,value);p.start();self.addCleanup(p.stop)

    def patch_v8(self):
        self.v8=copy.deepcopy(self.p.a)
        for name,value in dict(V8_AUTH=c.validate_authorization(self.v8),V8_SOURCE=self.v8['expected_master'],
            V8_PINS=self.v8['code_pins'],V8_REFERENCE=self.v8['account_permission_reference'],
            V8_VALIDITY_REFERENCE=self.p.grant_ref,V8_PROOF=self.p.proof['proof_sha256']).items():self.patch_value(name,value)

    def create(self,value,tag):
        body=tag+json.dumps(value,separators=(',',':'))
        self.creates.append(body);id=8100000000+len(self.creates)
        result=self.p.comment(value,tag,id,self.p.now.isoformat());self.comments[id]=result
        return result

    def metadata(self):
        run=dict(id=self.s.CONTROL_RUN,run_attempt=1,head_sha=self.s.V8_SOURCE,head_branch='master',event='workflow_dispatch',
            display_title='a1-sip '+self.s.CONTROL_NONCE,status='completed',conclusion='failure',created_at='2026-10-19T04:35:54Z')
        jobs=dict(total_count=2,jobs=[dict(id=117891606529,name='offline',status='completed',conclusion='success',
            started_at='2026-10-19T04:35:58Z',completed_at='2026-10-19T04:37:53Z'),
            dict(id=117892085699,name='capture',status='completed',conclusion='failure',
            started_at='2026-10-19T04:37:55Z',completed_at='2026-10-19T04:39:15Z')])
        blobs={p:(c.ROOT/p).read_bytes().replace(b'\r\n',b'\n') for p in self.s.V8_PINS}
        self.v8['code_pins']={p:c.digest(b) for p,b in blobs.items()};self.p.a=copy.deepcopy(self.v8);self.patch_v8()
        control=dict(authorization=self.v8,nonce=self.s.CONTROL_NONCE,preflight_only=False,recovery_run=None,
            external_binding=dict(proof_sha256=self.s.V8_PROOF,proof_updated_utc='2026-10-19T04:32:08+00:00',
                                  expires_at_utc=c.utc(self.s.VALIDITY_END).isoformat()))
        log=('INPUT_CAMPAIGN_CONTROL: '+json.dumps(control)+'\n'+
             '{"status": "BLOCKED", "code": "EXTERNAL_REFUSAL_LOG", "source_admission": false}\nNo artifacts will be uploaded\n').encode()
        self.patch_value('CONTROL_LOG',c.digest(log));self.patch_value('CONTROL_JOBS_CANON',c.digest(c.encoded(jobs)))
        self.raw_jobs=json.dumps(jobs,indent=2).encode()+b'\n'
        self.patch_value('CONTROL_JOBS_RAW',c.digest(self.raw_jobs))
        return run,jobs,dict(total_count=0,artifacts=[]),blobs,log

    def test_positive_execution_evidence_exact_identifiers_and_missing_meter(self):
        run,jobs,artifacts,blobs,log=self.metadata()
        value=self.s.verify_control_failure(c,self.v8,run,jobs,artifacts,blobs,log,self.raw_jobs)
        self.assertEqual(value['active_seconds'],195);self.assertTrue(value['not_runtime_meter'])
        self.assertEqual(value['original_meter_observation'],'MISSING')
        self.assertFalse(value['absence_of_meter_is_zero_io_basis']);self.assertEqual(value['original_transport_or_digest_cause'],'UNKNOWN')
        for change in [dict(run,id=run['id']+1),dict(run,run_attempt=2),dict(run,head_sha='0'*40),
                       dict(run,display_title='a1-sip '+c.PREFIX+'0'*24),dict(run,created_at=None)]:
            with self.subTest(run=change),self.assertRaises(c.Refused):self.s.verify_control_failure(c,self.v8,change,jobs,artifacts,blobs,log,self.raw_jobs)
        for bad in [b'',log+b'\n',log.replace(self.s.CONTROL_NONCE.encode(),b'foreign')]:
            with self.subTest(log=len(bad)),self.assertRaises(c.Refused):self.s.verify_control_failure(c,self.v8,run,jobs,artifacts,blobs,bad,self.raw_jobs)
        bad=copy.deepcopy(jobs);bad['jobs'][1]['id']+=1
        with self.assertRaises(c.Refused):self.s.verify_control_failure(c,self.v8,run,bad,artifacts,blobs,log,self.raw_jobs)
        with self.assertRaises(c.Refused):self.s.verify_control_failure(c,self.v8,run,jobs,dict(total_count=1,artifacts=[{}]),blobs,log,self.raw_jobs)
        bad=dict(blobs);bad[c.REVISION_MODULE]+=b'\n'
        with self.assertRaises(c.Refused):self.s.verify_control_failure(c,self.v8,run,jobs,artifacts,bad,log,self.raw_jobs)

    def pair(self):
        j,f,kw,prefix=self.p.closed_pair();self.patch_v8()
        with patch.object(c,'validity_grant_proof',return_value=self.p.grant_proof):
            c.bind_source_revision(j,f,self.v8,self.p.observed())
        for name,value in [('CONTROL_COHORT26',j.parent),('CONTROL_FAMILY53',f.parent)]:self.patch_value(name,value)
        for target in (j,f):
            data=dict(nonce=self.s.CONTROL_NONCE,remaining=self.p.observed()['remaining'],parent_checkpoint_sha256=self.s.CP)
            if target is f:data.update(capture_auth_sha256=self.s.V8_AUTH,scope=self.v8['external_cohort']['scope'])
            target.append('RESERVED',**data)
            data=dict(nonce=self.s.CONTROL_NONCE,run_id=self.s.CONTROL_RUN)
            if target is f:data.update(capture_auth_sha256=self.s.V8_AUTH,scope=self.v8['external_cohort']['scope'])
            target.append('RUN_ASSIGNED',**data)
        self.patch_value('CONTROL_COHORT28',j.parent);self.patch_value('CONTROL_FAMILY55',f.parent)
        prefix.update({p:p.read_bytes() for d in (j.directory,f.directory) for p in d.glob('*.json')})
        return j,f,kw,prefix

    def issue(self,j,f):
        a=copy.deepcopy(self.v8);a.update(schema='r1000-sip-external-cohort-authorization-v9',expected_master='d'*40)
        grant=self.create(self.s.control_grant_record(c,a['expected_master'],a['code_pins'],a['external_cohort']['scope']),
                          'A1_SIP_CONTROL_READ_REFUSAL_AUTHORIZATION ')
        payload=self.s.control_payload(c,a['expected_master'],a['code_pins'],a['external_cohort']['scope'],grant)
        receipt=self.s.append_control_closure(c,j,f,payload)
        seal=self.create(receipt,'A1_SIP_CONTROL_READ_REFUSAL_CLOSED ')
        a['external_cohort']['source_revision']=dict(control_refusal_reference=f'https://github.com/{c.REPO}/issues/448#issuecomment-{seal["id"]}',
                                                    control_refusal_sha256=c.digest(c.encoded(receipt)))
        a['account_permission_reference']=a['external_cohort']['source_revision']['control_refusal_reference']
        a['external_cohort']['proof_reference']=a['account_permission_reference']
        terms=c.external_proof_record(a);owner=self.create(terms,'A1_SIP_EXTERNAL_COHORT_CONSENT ')
        a['account_permission_reference']=f'https://github.com/{c.REPO}/issues/448#issuecomment-{owner["id"]}'
        a['external_cohort']['proof_reference']=a['account_permission_reference']
        self.s.verify_control_closure(c,a,receipt,grant,seal)
        _,sealproof=self.s.human_record(c,seal,'A1_SIP_CONTROL_READ_REFUSAL_CLOSED ')
        proof=self.s.verify_external_proof(c,a,c.external_proof_record(a),owner,self.p.grant,
            dict(receipt=receipt,seal_proof=sealproof,prior_proof=self.p.proof))
        return a,receipt,proof,grant,seal,owner

    def test_full_pair_issue_reopen_ancestor_and_once_only_accounting(self):
        j,f,kw,prefix=self.pair();a,receipt,proof,grant,seal,owner=self.issue(j,f)
        self.assertEqual(c.external_previous(a),self.v8);self.assertEqual(len(self.creates),3)
        self.assertEqual((len(j.entries),len(f.entries)),(29,56));self.assertLessEqual(len(c.encoded(a)),15000)
        self.assertLessEqual(len(c.encoded(c.external_proof_record(a))),4096)
        binding=self.s.control_source_binding(c,a,proof,receipt)
        kw.update(control_revision=binding,control_closure=receipt)
        path=j.directory;j.close();j=c.WorkJournal(path,c.validate_authorization(a),**kw);self.addCleanup(j.close)
        observed=self.p.observed();run=dict(id=self.s.CONTROL_RUN,run_attempt=1,head_sha=self.s.V8_SOURCE,
            display_title='a1-sip '+self.s.CONTROL_NONCE,status='completed',conclusion='failure')
        observed['runs'].append(run);observed['cohort_receipts'].append(self.s.control_value(c,a['external_cohort']['scope']))
        observed.update(active_seconds=5318,external_proof=proof)
        observed['epoch_proofs'][self.s.V8_AUTH]=self.p.proof
        with patch.object(c,'external_deployed'):self.s.bind_control_revision(c,j,f,a,observed)
        before={p:p.read_bytes() for d in (j.directory,f.directory) for p in d.glob('*.json')}
        self.s.bind_control_revision(c,j,f,a,observed)
        self.assertEqual((len(j.entries),len(f.entries)),(30,57));self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))
        self.assertTrue(all(p.read_bytes()==raw for p,raw in prefix.items()))
        with self.assertRaises(c.Refused):j.append('CONTROL_SOURCE_BOUND',**binding)
        with self.assertRaises(c.Refused):self.s.append_control_closure(c,j,f,receipt['payload'])
        for bad in [dict(grant,updated_at='2026-10-19T07:00:00Z'),dict(grant,user=dict(type='User',id=124)),dict(grant,created_at=None)]:
            with self.assertRaises(c.Refused):self.s.verify_control_closure(c,a,receipt,bad,seal)
        bad=copy.deepcopy(receipt);bad['payload']['actual_job_seconds']=0
        with self.assertRaises(c.Refused):self.s.verify_control_closure(c,a,bad,grant,seal)
        for key in ('cohort28_sha256','family55_sha256','old_auth_sha256','old_proof_sha256','nonce_sha256'):
            bad=copy.deepcopy(grant);body=self.s.control_grant_record(c,a['expected_master'],a['code_pins'],a['external_cohort']['scope'])
            body[key]='0'*64;bad['body']='A1_SIP_CONTROL_READ_REFUSAL_AUTHORIZATION '+json.dumps(body)
            with self.subTest(key=key),self.assertRaises(c.Refused):self.s.control_payload(c,a['expected_master'],a['code_pins'],a['external_cohort']['scope'],bad)

    def test_closure_crash_reflush_both_barriers_and_readback_failure(self):
        j,f,kw,prefix=self.pair()
        grant=self.create(self.s.control_grant_record(c,'d'*40,self.v8['code_pins'],self.v8['external_cohort']['scope']),
                          'A1_SIP_CONTROL_READ_REFUSAL_AUTHORIZATION ')
        payload=self.s.control_payload(c,'d'*40,self.v8['code_pins'],self.v8['external_cohort']['scope'],grant)
        for fail_dir,fail_slot,expected in [(j.directory,'000029.json',(29,55)),(f.directory,'000056.json',(29,56))]:
            def barrier(path):
                if Path(path).parent==fail_dir and Path(path).name==fail_slot:raise c.Refused('SYNTHETIC_BARRIER')
            with patch.object(c,'sync_native18_settlement',side_effect=barrier),self.assertRaisesRegex(c.Refused,'SYNTHETIC_BARRIER'):
                self.s.append_control_closure(c,j,f,payload)
            self.assertEqual((len(j.entries),len(f.entries)),expected)
        result=self.s.append_control_closure(c,j,f,payload)
        self.assertEqual(result,self.s.append_control_closure(c,j,f,payload));self.assertTrue(all(p.read_bytes()==raw for p,raw in prefix.items()))
        real=c.bounded_bytes
        def corrupt(path,*args):
            raw=real(path,*args)
            return raw+b' ' if Path(path).name=='000029.json' else raw
        with patch.object(c,'bounded_bytes',side_effect=corrupt),self.assertRaises(c.Refused):self.s.append_control_closure(c,j,f,payload)

    def test_pre_meter_diagnostic_is_not_a_meter_and_original_unknown_stays_unknown(self):
        nonce=c.PREFIX+'0'*24
        control=dict(authorization=self.v8,nonce=nonce,preflight_only=False,recovery_run=None,external_binding=self.p.proof)
        error=self.s.control_log_error(c,'TRANSPORT',1,0,http_status=403)
        for failure,has_diagnostic in [(error,True),(c.Refused('EXTERNAL_REFUSAL_LOG'),False)]:
            with tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/'campaign_meter.json'
                with patch.dict(os.environ,dict(GITHUB_RUN_ID='1001',INPUT_CAMPAIGN_NONCE=nonce)), \
                     patch.object(c,'verify_worker_source'),patch.object(c,'external_history',side_effect=failure), \
                     patch.object(c,'RuntimeMeter',side_effect=AssertionError('No meter')) as meter, \
                     patch.object(drive_module,'OwnerDrive',side_effect=AssertionError('No Drive')) as drive:
                    with self.assertRaises(c.Refused):c.external_worker(SimpleNamespace(),control,path)
                meter.assert_not_called();drive.assert_not_called();self.assertEqual(path.exists(),has_diagnostic)
                if has_diagnostic:
                    record=c.bounded_json(path)
                    self.assertTrue(record['not_runtime_meter']);self.assertFalse(record['provider_usage_certified'])
                    self.assertNotIn('usage',record);self.assertEqual(record['schema'],'a1-sip-pre-meter-control-failure-v1')

    def test_unsealed_history_never_falls_back_to_log_transport(self):
        old=c.external_previous(self.p.v7)
        with patch.object(c,'refusal_closure_for_auth',side_effect=c.Refused('UNSEALED')), \
             patch.object(c.subprocess,'run',side_effect=AssertionError('No transport fallback')) as transport:
            with self.assertRaisesRegex(c.Refused,'UNSEALED'):c.refusal_evidence(old,self.p.p.refused,sealed_auth=self.v8)
        transport.assert_not_called()

    def test_v9_forecast_retains_both_failed_runs_and_one_exact32_host_post(self):
        j,f,kw,prefix=self.pair();a,receipt,proof,grant,seal,owner=self.issue(j,f)
        o=self.p.observed();oldrun=dict(id=self.s.CONTROL_RUN,run_attempt=1,head_sha=self.s.V8_SOURCE,
            display_title='a1-sip '+self.s.CONTROL_NONCE,status='completed',conclusion='failure')
        o['runs'].append(oldrun);o['cohort_receipts'].append(self.s.control_value(c,a['external_cohort']['scope']))
        o['cohort_durations'].append(195);o.update(active_seconds=5318,external_proof=proof,cohort_runs=[oldrun])
        o['epoch_proofs'][self.s.V8_AUTH]=self.p.proof
        forecast=c.external_forecast(a,o);marker=self.s.time_acceptance(c,a,o,forecast)
        self.assertFalse(forecast['fits']);self.assertEqual(marker['live_prior_dispatches'],23)
        self.assertEqual(marker['live_active_seconds'],5318);self.assertEqual(forecast['active_seconds'],38748)
        for seconds in (5123,5317,5319):
            with self.assertRaises(c.Refused):self.s.time_acceptance(c,a,dict(o,active_seconds=seconds),forecast)
        class Journal:
            def __init__(this,entries):this.entries=entries;this.directory=j.directory;this.control_revision=kw.get('control_revision') or proof
            def close(this):pass
            def reconcile(this,runs):pass
            def append(this,kind,**data):this.entries.append(dict(kind=kind,**data))
        initial=dict(kind='EXTERNAL_COHORT_BOUND',recorded_utc=proof['proof_updated_utc'],scope=a['external_cohort']['scope'],
            genesis_sha256=c.external_genesis(a['external_cohort']['scope']),**proof)
        journal=Journal([initial,dict(kind='CONTROL_SOURCE_BOUND')]);family=Journal([]);posts=[]
        root=j.directory.parent;budget=root/'canonical-journal';budget.mkdir(exist_ok=True)
        state=root/('external-cohort-'+a['external_cohort']['scope']['namespace']);state.mkdir(exist_ok=True)
        inp=root/'input.csv';inp.write_bytes(a['external_cohort']['input_csv'].encode())
        def post(args,**kwargs):
            self.assertEqual(args[1:3],['workflow','run']);data=json.loads(kwargs['input']);posts.append(data)
            self.assertEqual(data['max_new_symbols'],'32');self.assertEqual(data['resume_sha256'],self.s.CP)
            self.assertEqual(json.loads(data['campaign_control'])['authorization'],a)
            return SimpleNamespace(returncode=1)
        with patch.object(c,'local_reject_recovery',return_value={}),patch.object(c,'WorkJournal',return_value=Journal([])), \
             patch.object(c,'verify_external_budget_journal'),patch.object(c,'external_proof',return_value=proof), \
             patch.object(c,'external_family_registry',return_value=family),patch.object(c,'external_journal',return_value=journal), \
             patch.object(c,'external_history',return_value=o),patch.object(c,'reconcile_external_family',return_value=None), \
             patch.object(c,'bind_source_revision'),patch.object(c,'external_deployed'),patch.object(c,'campaign_runs',return_value=o['runs']), \
             patch.object(c,'settled_parent',return_value=dict(file_id='fixture-cp128',sha256=self.s.CP)), \
             patch.object(c.subprocess,'run',side_effect=post),self.assertRaisesRegex(c.Refused,'CAMPAIGN_DISPATCH_UNCERTAIN'):
            c.external_host(a,state,inp,budget,root/'unused',None,16)
        self.assertEqual(len(posts),1);self.assertEqual(journal.entries[-1]['kind'],'RESERVED')
        self.assertEqual(family.entries[-1]['kind'],'RESERVED')


class HistoricalControlDiagnosticTests(unittest.TestCase):
    def test_three_bounded_diagnostic_branches_preserve_bom_and_never_raw_stderr(self):
        s=c._revision_module();log=b'\xef\xbb\xbffixture\r\n\r\n';canonical=log.replace(b'\r\n',b'\n')
        with patch.object(s,'REFUSAL_LOG',c.digest(canonical)):
            self.assertEqual(s.canonical_refusal_log(c,log),canonical)
            for result,reason in [(SimpleNamespace(returncode=1,stdout=b'',stderr=b'private-token HTTP 403 private-url'),'TRANSPORT'),
                                  (SimpleNamespace(returncode=0,stdout=b'x'*1_000_001,stderr=b''),'OVERSIZE'),
                                  (SimpleNamespace(returncode=0,stdout=canonical[3:],stderr=b''),'DIGEST')]:
                with self.subTest(reason=reason),self.assertRaises(c.Refused) as caught:s.refusal_log_result(c,result)
                diagnostic=caught.exception.control_read_diagnostic
                self.assertEqual(diagnostic['reason'],reason);self.assertNotIn('private',json.dumps(diagnostic))
                self.assertEqual(diagnostic['stdout_bytes'],len(result.stdout))
            self.assertEqual(s.refusal_log_result(c,SimpleNamespace(returncode=0,stdout=log,stderr=b'')),log)
        self.assertFalse(hasattr(c.Refused('EXTERNAL_REFUSAL_LOG'),'control_read_diagnostic'))


class HostedThreeFindingsTests(unittest.TestCase):
    def setUp(self):
        self.f=ControlReadFailureTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.s=self.f.s

    def test_retained_raw_layout_and_same_bytes_canonical_are_both_required(self):
        run,jobs,artifacts,blobs,log=self.f.metadata();raw=self.f.raw_jobs
        self.assertEqual(self.s.verify_control_jobs(c,jobs,raw),jobs)
        other=json.dumps(jobs,separators=(',',':')).encode()
        self.assertEqual(c.decode(other),jobs);self.assertNotEqual(c.digest(raw),c.digest(other))
        with self.assertRaisesRegex(c.Refused,'JOBS_RAW'):self.s.verify_control_failure(c,self.f.v8,run,jobs,artifacts,blobs,log,other)
        with self.assertRaisesRegex(c.Refused,'JOBS_CANONICAL'):self.s.verify_control_jobs(c,dict(jobs,total_count=3),raw)
        with patch.object(self.s,'CONTROL_JOBS_CANON','0'*64),self.assertRaisesRegex(c.Refused,'JOBS_CANONICAL'):
            self.s.verify_control_jobs(c,jobs,raw)
        with self.assertRaisesRegex(c.Refused,'JOBS_RAW'):self.s.verify_control_jobs(c,jobs,b'x'*1_000_001)

    def test_live_head_drift_no_append_partial_repair_once_and_historical_no_remote(self):
        j,f,kw,prefix=self.f.pair();a,receipt,proof,grant,seal,owner=self.f.issue(j,f)
        kw.update(control_revision=self.s.control_source_binding(c,a,proof,receipt),control_closure=receipt)
        path=j.directory;j.close();j=c.WorkJournal(path,c.validate_authorization(a),**kw);self.addCleanup(j.close)
        o=self.f.p.observed();o['runs'].append(dict(id=self.s.CONTROL_RUN))
        o['cohort_receipts'].append(self.s.control_value(c,a['external_cohort']['scope']))
        o.update(active_seconds=5318,external_proof=proof);o['epoch_proofs'][self.s.V8_AUTH]=self.f.p.proof
        before={p:p.read_bytes() for d in (j.directory,f.directory) for p in d.glob('*.json')}
        with patch.object(c,'external_deployed',side_effect=c.Refused('CAMPAIGN_DEPLOYMENT_DRIFT')) as deployed:
            with self.assertRaisesRegex(c.Refused,'DEPLOYMENT_DRIFT'):self.s.bind_control_revision(c,j,f,a,o)
        deployed.assert_called_once_with(a);self.assertEqual((len(j.entries),len(f.entries)),(29,56))
        self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))
        def barrier(path):
            if Path(path).parent==j.directory and Path(path).name=='000030.json':raise c.Refused('FIXTURE_BARRIER')
        with patch.object(c,'external_deployed') as deployed,patch.object(c,'sync_native18_settlement',side_effect=barrier):
            with self.assertRaisesRegex(c.Refused,'FIXTURE_BARRIER'):self.s.bind_control_revision(c,j,f,a,o)
        self.assertEqual((len(j.entries),len(f.entries)),(30,56));deployed.assert_called_once_with(a)
        source30=j.entries[-1];j.close();j=c.WorkJournal(path,c.validate_authorization(a),**kw);self.addCleanup(j.close)
        with patch.object(c,'external_deployed',side_effect=c.Refused('CAMPAIGN_DEPLOYMENT_DRIFT')) as deployed:
            with self.assertRaisesRegex(c.Refused,'DEPLOYMENT_DRIFT'):self.s.bind_control_revision(c,j,f,a,o)
        deployed.assert_called_once_with(a);self.assertEqual((len(j.entries),len(f.entries)),(30,56))
        self.assertEqual(j.entries[-1],source30)
        with patch.object(c,'external_deployed') as deployed:self.s.bind_control_revision(c,j,f,a,o)
        deployed.assert_called_once_with(a);self.assertEqual((len(j.entries),len(f.entries)),(30,57))
        self.f.p.now=c.utc(self.s.VALIDITY_END)+timedelta(seconds=1)
        with patch.object(c,'external_deployed',side_effect=AssertionError('Historical validation has no live-master gate')):
            self.s.bind_control_revision(c,j,f,a,o)
        self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))

    def test_real_large_stderr_is_discarded_not_buffered_or_revealed(self):
        import ast
        tree=ast.parse((c.ROOT/'tools/alpaca_sip_campaign.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='refusal_evidence')
        call=next(n for n in ast.walk(node) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                  and n.func.attr=='run')
        keyword=next(k.value for k in call.keywords if k.arg=='stderr')
        self.assertEqual(ast.unparse(keyword),'subprocess.DEVNULL')
        # Execute the exact discard policy with a local child, not gh/provider.
        result=c.subprocess.run([sys.executable,'-c',
            'import sys; sys.stderr.write("private-token HTTP 403 private-url\\n"*300000); sys.exit(1)'],
            stdout=c.subprocess.PIPE,stderr=c.subprocess.DEVNULL,timeout=15)
        self.assertIsNone(result.stderr);self.assertEqual(result.stdout,b'')
        with self.assertRaises(c.Refused) as caught:self.s.refusal_log_result(c,result)
        diagnostic=caught.exception.control_read_diagnostic
        self.assertEqual(diagnostic['reason'],'TRANSPORT');self.assertEqual(diagnostic['returncode'],1)
        self.assertIsNone(diagnostic['http_status']);self.assertEqual(diagnostic['stdout_bytes'],0)
        self.assertNotIn('private',json.dumps(diagnostic))
        self.assertNotIn('403',json.dumps(diagnostic))


class NamedRead39235028468Tests(unittest.TestCase):
    """New-case offline witnesses; no private identifiers or actual authority."""
    def setUp(self):
        self.s=c._revision_module();self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.clock=c.utc("2026-10-19T11:00:00Z");real_utc=c.utc
        self.addCleanup(patch.stopall)
        patch.object(c,"utc",side_effect=lambda value=None:real_utc(value) if value is not None else self.clock).start()
        self.names=["ZZZ%03d"%i for i in range(417)]
        self.scope=dict(task_key="R1000-SYNTHETIC",namespace="fixture392",input_sha256="f"*64)
        self.a=dict(expected_master="1"*40,private_root_folder_id="fixture-root-123",
            private_data_folder_id="fixture-data-123",external_cohort=dict(
                input_csv="ticker\n"+"\n".join(self.names)+"\n",scope=self.scope))
        self.raw=c.encoded(dict(examined=self.names[:296],cohort_scope=self.scope)).ljust(5005,b" ")
        patch.object(self.s,"READ392_CP",c.digest(self.raw)).start()
        patch.object(self.s,"READ392_CP_ID_SHA",c.digest(b"fixture-cp296-123")).start()
        patch.object(c,"validate_authorization",return_value=self.s.READ392_AUTH).start()
        patch.dict(c.CONTINUATION["bindings"],owner_sha256=c.digest(b"fixture-owner")).start()
        self.control=dict(schema=self.s.READ392_SCHEMA,task_key=self.s.READ392_TASK,authorization=self.a,
            expected_master="4"*40,code_pins_sha256=c.digest(c.encoded({p:"a"*64 for p in self.s.V6_PINS})),
            nonce=c.PREFIX+"a"*24,checkpoint_file_id="fixture-cp296-123",
            grant_reference=f"https://github.com/{c.REPO}/issues/448#issuecomment-123456789",
            human_authority_sha256="e"*64,deployment=dict(pull_request=123,reviewed_head="5"*40))
        self.env=dict(GITHUB_REPOSITORY=c.REPO,GITHUB_REF="refs/heads/master",GITHUB_SHA="4"*40,
            GITHUB_RUN_ID="40000000000",GITHUB_RUN_ATTEMPT="1",INPUT_NATIVE_READ_ONLY="true",
            INPUT_CAMPAIGN_NONCE=self.control["nonce"],A1_PRIVATE_RESEARCH_AUTHORIZED="true",
            ALPACA_NONCOMMERCIAL_ACKNOWLEDGED="true",INPUT_PRIVATE_ROOT_FOLDER_ID="fixture-root-123",
            INPUT_PRIVATE_DATA_FOLDER_ID="fixture-data-123",MACRO_DRIVE_CONFIG="[gdrive]\ntype=drive\ntoken="+
                json.dumps(dict(access_token="fixture-access",refresh_token="fixture-refresh",
                    expiry="2030-01-01T00:00:00Z"))+"\n")
        self.event_path=self.root/"private-event.json"
        inputs=dict(campaign_control=c.encoded(self.control).decode(),campaign_nonce=self.control["nonce"],
            private_root_folder_id="fixture-root-123",private_data_folder_id="fixture-data-123",
            private_research_authorized="true",noncommercial_terms_acknowledged="true")
        self.event_path.write_bytes(c.encoded(dict(inputs=inputs)))
        self.env.update(GITHUB_EVENT_PATH=str(self.event_path),INPUT_PRIVATE_ROOT_FOLDER_ID="",
            INPUT_PRIVATE_DATA_FOLDER_ID="",INPUT_RESUME_FILE_ID="",INPUT_CAMPAIGN_CONTROL="")
        self.run=dict(id=40000000000,run_attempt=1,head_sha="4"*40,head_branch="master",
            event="workflow_dispatch",display_title="a1-sip "+self.control["nonce"]+" native-read39235028468",
            status="completed",conclusion="success",created_at="2026-10-19T10:30:00Z")
        self.jobs=dict(total_count=2,jobs=[
            dict(name="offline",status="completed",conclusion="success",started_at="2026-10-19T10:30:04Z",completed_at="2026-10-19T10:30:24Z"),
            dict(name="reconcile",status="completed",started_at="2026-10-19T10:30:25Z",completed_at="2026-10-19T10:30:50Z")])

    def make_meter(self,server,**kwargs):
        ident=dict(task_key=self.s.READ392_TASK,run_id=self.run["id"],run_attempt=1,
            nonce=self.control["nonce"],control_sha256=c.digest(c.encoded(self.control)),grant_proof_sha256="b"*64,
            source_sha=self.control["expected_master"],source_pins=getattr(self,"deployment_pins",{p:"a"*64 for p in self.s.V6_PINS}),
            parent_checkpoint_sha256=self.s.READ392_CP,examined_before=296,failed_run_id=39235028468,
            failed_meter_sha256=self.s.READ392_METER,usage_before=self.s.READ392_USED,
            active_seconds_before=8736,dispatches_before=29,active_seconds_reservation=900,dispatch_reservation=1)
        directory=self.root/("meter-"+str(len(list(self.root.iterdir()))));directory.mkdir()
        return self.s.named_read_meter(c,self.s.READ392_ALLOWANCE,directory/"native_read_meter.json",
            "2026-10-19T11:05:00Z",ident,opener=server,limits=c.CONTINUED_LIMITS,
            clock=lambda:c.utc(),control=self.control,**kwargs)

    def server(self,mode=None):
        case=self;s=self.s
        class NamedServer(Server):
            def __init__(self):
                super().__init__();self.calls=0
                self.cp=dict(id="fixture-cp296-123",name=s.READ392_CP+".json",size="5005",
                    parents=["fixture-data-123"],createdTime="2026-10-19T10:14:30Z")
                self.body=case.raw;self.candidate=None;self.candidate_body=None
                if mode in {"candidate","candidate-over","candidate-badhash","two-candidates"}:
                    body=c.encoded(dict(symbols=case.names[296:300],source_sha=case.a["expected_master"],
                        cohort_scope=case.scope)).ljust(434796,b" ")
                    self.candidate_body=body
                    self.candidate=dict(id="fixture-candidate-123",name=c.digest(body)+".json",size="434796",
                        parents=["fixture-data-123"],createdTime="2026-10-19T10:14:40Z")
            def open(self,request,**kw):
                self.calls+=1;p=urlsplit(request.full_url);q=parse_qs(p.query)
                if p.path=="/token":
                    self.requests.append(request.full_url)
                    return Reply(c.encoded(dict(access_token="fixture-fresh",token_type="Bearer",expires_in=3600)))
                if p.path=="/drive/v3/files":
                    self.requests.append(request.full_url)
                    positive=q["q"][0].startswith("name = ")
                    items=[copy.deepcopy(self.cp)]
                    if positive:
                        if mode=="missing-positive":items=[]
                        if mode=="duplicate-positive":items*=2
                        if mode=="positive-clock":items[0]["createdTime"]="2026-10-19T10:14:31Z"
                    else:
                        if self.candidate:items.append(copy.deepcopy(self.candidate))
                        if mode=="zero":items=[]
                        if mode=="two-candidates":
                            other=copy.deepcopy(self.candidate);other["id"]="fixture-candidate-456";items.append(other)
                        if mode=="duplicate":items*=2
                        if mode=="wrong-parent":items[0]["parents"]=["fixture-other-123"]
                        if mode=="missing-clock":items[0].pop("createdTime")
                        if mode=="future":items[0]["createdTime"]="2026-10-19T11:01:00Z"
                        if mode=="old-clock":items[0]["createdTime"]="2026-10-19T09:00:00Z"
                        if mode=="oversized":items*=9
                        if mode=="bad-size":items[0]["size"]="0005005"
                        if mode=="bad-name":items[0]["name"]="private arbitrary name"
                    reply=dict(files=items)
                    if mode=="paged" and not positive:reply["nextPageToken"]="secret-page"
                    return Reply(c.encoded(reply))
                file_id=p.path.rsplit("/",1)[-1]
                if file_id in {"fixture-cp296-123","fixture-candidate-123"}:
                    self.requests.append(request.full_url)
                    item=self.cp if file_id=="fixture-cp296-123" else self.candidate
                    body=self.body if file_id=="fixture-cp296-123" else self.candidate_body
                    if q.get("alt")==["media"]:
                        if mode=="candidate-over" and file_id!="fixture-cp296-123":body+=b"x"
                        if mode=="candidate-badhash" and file_id!="fixture-cp296-123":body=b"x"+body[1:]
                        return Reply(body)
                    value=dict(item,mimeType="application/octet-stream",trashed=False,shared=False,
                        permissions=[dict(id="fixture-owner",type="user",role="owner")])
                    return Reply(c.encoded(value))
                return super().open(request,**kw)
        return NamedServer()

    def read_objects(self,mode=None):
        server=self.server(mode);meter=self.make_meter(server)
        with patch.dict(os.environ,self.env,clear=True):
            drive=drive_module.OwnerDrive("fixture-root-123",str(self.root),meter=meter)
            result=self.s.named_read_objects(c,drive,self.control,meter)
        meter.finish("COMPLETE")
        return result,c.bounded_json(meter.journal),meter,server

    def test_actual_transport_positive_and_unknown_origin(self):
        result,value,m,server=self.read_objects()
        self.assertTrue(result["positive_control_verified"])
        self.assertEqual(value["usage"]["drive_requests"],7)
        self.assertFalse(result["absence_proven"]);self.assertEqual(result["origin_status"],"UNKNOWN")
        self.assertNotIn("fixture-cp",json.dumps(value));self.assertNotIn("fixture-data",json.dumps(value))
        self.assertEqual(value["usage"]["provider_gets"],0);self.assertEqual(value["usage"]["storage_bytes"],0)
        cost=self.s.named_read_cost(c,self.control,self.run,value,self.jobs)
        self.assertEqual(cost["dispatches_after"],30);self.assertEqual(cost["active_seconds_after"],8781)
        self.assertEqual(cost["unknown_storage_bytes_still_charged"],[302101,434796])

    def test_candidate_hash_content_does_not_prove_old_post(self):
        result,value,m,server=self.read_objects("candidate")
        self.assertTrue(result["content_identity_verified"])
        self.assertFalse(result["failed_post_equivalence_verified"]);self.assertFalse(result["failed_request_body_hash_known"])
        self.assertEqual(result["candidate_bytes"],434796)
        self.assertEqual(value["usage"]["drive_requests"],9)
        self.s.named_read_cost(c,self.control,self.run,value,self.jobs)

    def test_inventory_and_positive_counterexamples_stop_before_candidate_media(self):
        for mode in ("missing-positive","duplicate-positive","positive-clock","paged","duplicate",
                     "wrong-parent","missing-clock","future","old-clock","oversized","bad-size","bad-name","zero",
                     "two-candidates"):
            with self.subTest(mode=mode):
                server=self.server(mode);m=self.make_meter(server)
                with patch.dict(os.environ,self.env,clear=True),self.assertRaises(c.Refused):
                    drive=drive_module.OwnerDrive("fixture-root-123",str(self.root),meter=m)
                    self.s.named_read_objects(c,drive,self.control,m)
                self.assertFalse(any("fixture-candidate" in u and "alt=media" in u for u in server.requests))

    def test_true_empty_inventory_when_positive_is_outside_window_is_unknown(self):
        server=self.server("zero");server.cp["createdTime"]="2026-10-19T10:00:00Z";m=self.make_meter(server)
        with patch.dict(os.environ,self.env,clear=True):
            drive=drive_module.OwnerDrive("fixture-root-123",str(self.root),meter=m)
            result=self.s.named_read_objects(c,drive,self.control,m)
        self.assertEqual(result["candidate_count"],0);self.assertFalse(result["absence_proven"])
        self.assertFalse(result["failed_request_body_hash_known"])

    def test_candidate_allocation_clamp_and_hash_failure(self):
        for mode in ("candidate-over","candidate-badhash"):
            with self.subTest(mode=mode):
                with self.assertRaises(c.Refused):self.read_objects(mode)

    def test_cp_hash_scope_and_order_are_independent(self):
        for mode in ("hash","scope","order"):
            server=self.server();m=self.make_meter(server)
            if mode=="hash":server.body=b"x"+server.body[1:]
            else:
                cp=c.decode(server.body)
                if mode=="scope":cp["cohort_scope"]["namespace"]="other"
                else:cp["examined"][0:2]=list(reversed(cp["examined"][0:2]))
                server.body=c.encoded(cp).ljust(5005,b" ")
            with patch.object(self.s,"READ392_CP",c.digest(server.body) if mode!="hash" else self.s.READ392_CP):
                server.cp["name"]=self.s.READ392_CP+".json"
                with patch.dict(os.environ,self.env,clear=True),self.assertRaises(c.Refused):
                    drive=drive_module.OwnerDrive("fixture-root-123",str(self.root),meter=m)
                    self.s.named_read_objects(c,drive,self.control,m)

    def test_endpoint_allowlist_denies_writes_provider_arbitrary_ids_and_queries(self):
        base="https://www.googleapis.com/drive/v3/"
        for url,kw in [
            ("https://data.alpaca.markets/v2/stocks/bars",{}),
            ("https://www.googleapis.com/upload/drive/v3/files",dict(method="POST",body=b"x")),
            (base+"files/fixture-other-123?alt=media",{}),
            (base+"files/fixture-root-123?alt=media",{}),
            (base+"files/fixture-cp296-123?fields=*",{}),
            (base+"files?pageSize=9&q=anything&fields=id",{}),
            (base+"about?fields=user%28permissionId%29%2CstorageQuota#fragment",{}),
            (base+"about?fields=user%28permissionId%29%2CstorageQuota&fields=x",{}),
            ("https://oauth2.googleapis.com/token",dict(method="POST",body=b"x")),
            (base+"files/fixture-cp296-123?alt=media",dict(method="DELETE"))]:
            with self.subTest(url=url):
                server=Opener();m=self.make_meter(server)
                with self.assertRaises(c.Refused):m.perform(url,**kw)
                self.assertEqual(server.calls,0);self.assertEqual(m.used["drive_requests"],0)
                with self.assertRaises(c.Refused):m.reserve_storage(1)

    def test_request_reservation_is_durable_before_first_oauth_attempt(self):
        case=self
        class First(Opener):
            def open(self,request,**kw):
                v=c.bounded_json(m.journal)
                case.assertEqual(v["usage"]["drive_requests"],1)
                case.assertEqual(v["attempts"][0]["status"],"RESERVED")
                case.assertEqual(v["attempts"][0]["kind"],"OAUTH")
                raise OSError("PRIVATE_TOKEN")
        server=First();m=self.make_meter(server,refresh_needed=True)
        with self.assertRaises(c.Refused):m.perform("https://oauth2.googleapis.com/token",method="POST",body=b"x",limit=65536)
        m.finish("BLOCKED","NETWORK")
        self.assertEqual(m.used["drive_bytes"],65536+1+1+65536)
        run=dict(self.run,conclusion="failure")
        cost=self.s.named_read_cost(c,self.control,run,c.bounded_json(m.journal),self.jobs)
        self.assertEqual(cost["usage"]["drive_bytes"],131074)
        with self.assertRaises(c.Refused):m.perform("https://oauth2.googleapis.com/token",method="POST",body=b"x")

    def test_reservation_and_response_save_failures_keep_importable_cost(self):
        url="https://www.googleapis.com/drive/v3/about?fields=user%28permissionId%29%2CstorageQuota"
        original_atomic=c.atomic_json;original_sync=c.sync_native18_settlement
        for phase in ("RESERVED","COMPLETE"):
            for barrier in ("before_replace","after_replace","fsync"):
                with self.subTest(phase=phase,barrier=barrier):
                    server=Opener(b"abc");m=self.make_meter(server);fired=[]
                    def fault(value):
                        return not fired and bool(value["attempts"]) and value["attempts"][-1]["status"]==phase
                    def atomic(path,value,**kwargs):
                        hit=fault(value) and barrier!="fsync"
                        if hit and barrier=="before_replace":
                            fired.append(True);raise OSError("FIXTURE_ATOMIC_WRITE")
                        original_atomic(path,value,**kwargs)
                        if hit:
                            fired.append(True);raise OSError("FIXTURE_AFTER_REPLACE")
                    def sync(path):
                        if barrier=="fsync" and fault(c.bounded_json(path)):
                            fired.append(True);raise OSError("FIXTURE_FSYNC")
                        original_sync(path)
                    with patch.object(c,"atomic_json",side_effect=atomic),patch.object(c,"sync_native18_settlement",side_effect=sync):
                        with self.assertRaises(OSError):m.perform(url)
                        m.finish("BLOCKED","NAMED_READ_INTERNAL")
                    self.assertEqual(fired,[True]);self.assertEqual(server.calls,int(phase=="COMPLETE"))
                    value=c.bounded_json(m.journal)
                    self.assertEqual(value["attempts"][0]["status"],phase)
                    expected=65539 if phase=="COMPLETE" else 2065537
                    self.assertEqual(value["usage"]["drive_bytes"],expected)
                    cost=self.s.named_read_cost(c,self.control,dict(self.run,conclusion="failure"),value,self.jobs)
                    self.assertEqual(cost["usage"]["drive_bytes"],expected)

    def test_response_settlement_interruptions_publish_one_consistent_state(self):
        url="https://www.googleapis.com/drive/v3/about?fields=user%28permissionId%29%2CstorageQuota"
        for boundary in ("before_apply","during_apply","before_clear"):
            with self.subTest(boundary=boundary):
                server=Opener(b"abc");m=self.make_meter(server);fired=[];original_set=type(m).__setattr__
                def assign(obj,name,value):
                    stage=getattr(obj,"response_settlement",None)
                    hit=(not fired and ((boundary=="before_apply" and name=="used" and stage is not None)
                        or (boundary=="during_apply" and name=="observed_google_body_bytes" and stage is not None)
                        or (boundary=="before_clear" and name=="response_settlement" and value is None and stage is not None)))
                    if hit:
                        fired.append(True);raise c.Refused("CAMPAIGN_DEADLINE")
                    original_set(obj,name,value)
                with patch.object(type(m),"__setattr__",new=assign):
                    with self.assertRaisesRegex(c.Refused,"CAMPAIGN_DEADLINE"):m.perform(url)
                    m.finish("BLOCKED","CAMPAIGN_DEADLINE")
                self.assertEqual(fired,[True]);self.assertEqual(server.calls,1)
                value=c.bounded_json(m.journal)
                self.assertEqual(value["attempts"][0]["status"],"COMPLETE")
                self.assertEqual(value["attempts"][0]["response_bytes"],3)
                cost=self.s.named_read_cost(c,self.control,dict(self.run,conclusion="failure"),value,self.jobs)
                self.assertEqual(cost["usage"]["drive_bytes"],65539)

    def test_interrupted_debit_publication_keeps_pending_for_final_save(self):
        server=Opener(b"abc");m=self.make_meter(server);original_set=type(m).__setattr__;fired=[]
        def assign(obj,name,value):
            original_set(obj,name,value)
            if not fired and name=="used" and value["drive_requests"]==1:
                fired.append(True);raise c.Refused("CAMPAIGN_DEADLINE")
        url="https://www.googleapis.com/drive/v3/about?fields=user%28permissionId%29%2CstorageQuota"
        with patch.object(type(m),"__setattr__",new=assign):
            with self.assertRaisesRegex(c.Refused,"CAMPAIGN_DEADLINE"):m.perform(url)
            m.finish("BLOCKED","CAMPAIGN_DEADLINE")
        self.assertEqual(server.calls,0)
        value=c.bounded_json(m.journal)
        self.assertEqual(value["attempts"][0]["status"],"RESERVED")
        cost=self.s.named_read_cost(c,self.control,dict(self.run,conclusion="failure"),value,self.jobs)
        self.assertEqual(cost["usage"]["drive_bytes"],2065537)
        with self.assertRaisesRegex(c.Refused,"NAMED_READ_PENDING"):m.perform(url)

    def test_real_atomic_temporary_write_flush_and_fsync_failures_recover(self):
        original_factory=c.tempfile.NamedTemporaryFile;original_fsync=c.os.fsync
        url="https://www.googleapis.com/drive/v3/about?fields=user%28permissionId%29%2CstorageQuota"
        for phase in ("RESERVED","COMPLETE"):
            for boundary in ("write","flush","fsync"):
                with self.subTest(phase=phase,boundary=boundary):
                    server=Opener(b"abc");m=self.make_meter(server);fired=[];owned=[]
                    foreign=m.journal.with_name(m.journal.name+".new");foreign.write_bytes(b"UNKNOWN_EXISTING_TEMP")
                    def fail(which):
                        if not fired and which==boundary and m.attempts and m.attempts[-1]["status"]==phase:
                            fired.append(True);raise OSError("FIXTURE_REAL_TEMP")
                    class Faulty:
                        def __init__(inner,handle):inner.handle=handle;inner.name=handle.name;owned.append(Path(inner.name))
                        def __enter__(inner):return inner
                        def __exit__(inner,*args):return inner.handle.__exit__(*args)
                        def write(inner,raw):
                            inner.handle.write(raw);fail("write")
                        def flush(inner):
                            inner.handle.flush();fail("flush")
                        def fileno(inner):return inner.handle.fileno()
                    def factory(*args,**kwargs):return Faulty(original_factory(*args,**kwargs))
                    def fsync(fd):
                        fail("fsync");return original_fsync(fd)
                    with patch.object(c.tempfile,"NamedTemporaryFile",side_effect=factory),patch.object(c.os,"fsync",side_effect=fsync):
                        with self.assertRaises(OSError):m.perform(url)
                        m.finish("BLOCKED","NAMED_READ_INTERNAL")
                    self.assertEqual(fired,[True]);self.assertEqual(foreign.read_bytes(),b"UNKNOWN_EXISTING_TEMP")
                    self.assertTrue(owned);self.assertTrue(all(not p.exists() for p in owned))
                    self.assertEqual(server.calls,int(phase=="COMPLETE"))
                    cost=self.s.named_read_cost(c,self.control,dict(self.run,conclusion="failure"),c.bounded_json(m.journal),self.jobs)
                    self.assertEqual(cost["usage"]["drive_bytes"],65539 if phase=="COMPLETE" else 2065537)

    def test_initial_meter_save_failure_records_blocked_zero_io_once(self):
        original_fsync=c.os.fsync
        for permanent in (False,True):
            with self.subTest(permanent=permanent):
                directory=self.root/("initial-permanent" if permanent else "initial-transient");directory.mkdir()
                original_root=self.root;self.root=directory;calls=[];server=Opener()
                def fsync(fd):
                    calls.append(fd)
                    if permanent or len(calls)==1:raise OSError("FIXTURE_INITIAL_SAVE")
                    return original_fsync(fd)
                try:
                    with patch.object(c.os,"fsync",side_effect=fsync),self.assertRaisesRegex(c.Refused,"NAMED_READ_METER_INIT"):
                        self.make_meter(server)
                finally:self.root=original_root
                files=list(directory.rglob("native_read_meter.json"))
                self.assertEqual(server.calls,0);self.assertGreaterEqual(len(calls),2)
                if permanent:
                    self.assertEqual(files,[])
                else:
                    self.assertEqual(len(files),1);value=c.bounded_json(files[0])
                    self.assertTrue(value["finalized"]);self.assertEqual(value["status"],"BLOCKED")
                    self.assertEqual(value["attempts"],[]);self.assertEqual(value["usage"],{k:0 for k in c.LIMITS})
                    cost=self.s.named_read_cost(c,self.control,dict(self.run,conclusion="failure"),value,self.jobs)
                    self.assertEqual(cost["dispatches"],1);self.assertGreater(cost["active_seconds"],0)

    def test_complete_and_blocked_cost_survive_terminal_job_failures(self):
        result,value,m,server=self.read_objects();jobs=copy.deepcopy(self.jobs)
        jobs["jobs"][1]["steps"]=[dict(name="Reconcile exact failed Drive POST with native metered reads",
            status="completed",conclusion="success",started_at=jobs["jobs"][1]["started_at"],
            completed_at=jobs["jobs"][1]["started_at"]),
            dict(name="Preserve native read meter without original bytes or private IDs",status="completed",
                 conclusion="failure",started_at=jobs["jobs"][1]["completed_at"])]
        for conclusion in ("success","failure","cancelled","timed_out"):
            with self.subTest(conclusion=conclusion):
                cost=self.s.named_read_cost(c,self.control,dict(self.run,conclusion=conclusion),value,jobs)
                self.assertEqual(cost["usage"],m.used)
        for change in (lambda j:j["jobs"][1].pop("steps"),
                       lambda j:j["jobs"][1]["steps"][0].update(conclusion="failure"),
                       lambda j:j["jobs"][1]["steps"][1].update(started_at=jobs["jobs"][0]["started_at"])):
            bad=copy.deepcopy(jobs);change(bad)
            with self.assertRaisesRegex(c.Refused,"STEP_PROOF"):
                self.s.named_read_cost(c,self.control,dict(self.run,conclusion="failure"),value,bad)
        blocked=self.make_meter(Opener())
        with self.assertRaises(c.Refused):
            blocked.perform("https://www.googleapis.com/drive/v3/about?fields=user%28permissionId%29%2CstorageQuota",limit=1)
        blocked.finish("BLOCKED","RESPONSE_SIZE")
        for conclusion in ("failure","cancelled","timed_out"):
            cost=self.s.named_read_cost(c,self.control,dict(self.run,conclusion=conclusion),c.bounded_json(blocked.journal),self.jobs)
            self.assertEqual(cost["usage"],blocked.used)
        for meter in (value,c.bounded_json(blocked.journal)):
            with self.assertRaisesRegex(c.Refused,"COST_RUN"):
                self.s.named_read_cost(c,self.control,dict(self.run,conclusion="neutral"),meter,jobs)

    def test_token_refresh_crossing_sixty_seconds_is_admitted_once(self):
        self.env["MACRO_DRIVE_CONFIG"]=self.env["MACRO_DRIVE_CONFIG"].replace(
            "2030-01-01T00:00:00Z",(self.clock+timedelta(seconds=61)).isoformat())+\
            "client_id=fixture-client.apps.googleusercontent.com\nclient_secret=fixture-client-secret\n"
        calls=[];case=self
        class Moving(c.datetime):
            @classmethod
            def now(cls,*args,**kwargs):
                value=case.clock+timedelta(seconds=2 if calls else 0);calls.append(value);return value
        with patch.object(drive_module,"datetime",Moving):
            NamedRead39235028468Tests.test_worker_positive_flow_keeps_collector_outside_read_path(self)
        value=c.bounded_json(self.root/"worker-positive/native_read_meter.json")
        self.assertEqual(sum(a["kind"]=="OAUTH" for a in value["attempts"]),1)
        self.assertEqual(value["usage"]["provider_gets"],0)

    def test_late_master_drift_in_history_or_jobs_refuses_before_secrets(self):
        current=dict(self.run,status="in_progress")
        observed=dict(runs=[dict(id=1)]*28+[dict(id=39235028468)],examined=296,parent_sha=self.s.READ392_CP,
            receipts=[{}],used=dict(self.s.READ392_USED),active_seconds=8736,first=c.utc(c.CONTINUATION["first"]))
        jobs=copy.deepcopy(self.jobs);jobs["jobs"][1].update(status="in_progress",started_at=self.clock.isoformat())
        for phase in ("history","jobs"):
            for protection in (True,False):
                with self.subTest(phase=phase,protection=protection):
                    changed=[];reads=[];env=dict(self.env,MACRO_DRIVE_CONFIG="INVALID_SECRET_CONFIG")
                    def history(*args,**kwargs):
                        if phase=="history":changed.append(True)
                        return observed
                    def gh(path):
                        reads.append(path)
                        if path.endswith("/branches/master"):
                            self.assertTrue(changed)
                            return dict(protected=protection,commit=dict(sha="9"*40 if protection else self.control["expected_master"]))
                        if path.endswith("/jobs?per_page=100"):
                            if phase=="jobs":changed.append(True)
                            return jobs
                        return current
                    with patch.dict(os.environ,env,clear=True),patch.object(c,"gh_json",side_effect=gh),\
                         patch.object(self.s,"named_read_proof",return_value=("b"*64,self.run["created_at"])),\
                         patch.object(self.s,"named_read_deployed",return_value={p:"a"*64 for p in self.s.V6_PINS}),\
                         patch.object(self.s,"READ392_METER",c.digest(c.encoded({}))),patch.object(c,"external_history",side_effect=history),\
                         patch.object(drive_module,"OwnerDrive") as owner,patch.object(c,"build_opener") as opener,\
                         self.assertRaisesRegex(c.Refused,"CAMPAIGN_MASTER_DRIFT"):
                        self.s.named_read_worker(c,self.control,str(self.root/("late-"+phase+str(protection))))
                    owner.assert_not_called();opener.assert_not_called()
                    self.assertTrue(reads[-1].endswith("/branches/master"))

    def test_real_owner_bootstrap_is_metered_and_not_retried(self):
        env=dict(self.env)
        env["MACRO_DRIVE_CONFIG"]=env["MACRO_DRIVE_CONFIG"].replace("2030-01-01","2020-01-01")+\
            "client_id=fixture-client.apps.googleusercontent.com\nclient_secret=fixture-client-secret\n"
        server=self.server();m=self.make_meter(server,refresh_needed=True)
        with patch.dict(os.environ,env,clear=True):
            drive=drive_module.OwnerDrive("fixture-root-123",str(self.root),meter=m)
            self.s.named_read_objects(c,drive,self.control,m)
        self.assertEqual(m.attempts[0]["kind"],"OAUTH")
        self.assertEqual(sum(a["kind"]=="OAUTH" for a in m.attempts),1)
        self.assertNotIn("fixture-client-secret",m.journal.read_text())

    def test_same_canonical_request_cannot_be_reordered_to_retry(self):
        m=self.make_meter(Opener(b"abc"))
        url="https://www.googleapis.com/drive/v3/about?fields=user%28permissionId%29%2CstorageQuota"
        m.perform(url)
        with self.assertRaises(c.Refused):m.perform(url.replace("%2C",","))
        self.assertEqual(m.used["drive_requests"],1)

    def test_budget_and_expiry_denied_before_transport(self):
        server=Opener();m=self.make_meter(server);m.allowance["drive_requests"]=0
        with self.assertRaises(c.Refused):m.perform("https://www.googleapis.com/drive/v3/about?fields=user%28permissionId%29%2CstorageQuota")
        self.assertEqual(server.calls,0)
        with patch.object(c,"utc",return_value=self.clock+timedelta(days=1)):
            with self.assertRaises(c.Refused):self.s.named_read_control(c,self.control)

    def test_new_control_and_old_control_never_interchange(self):
        self.s.named_read_control(c,self.control)
        with self.assertRaises(c.Refused):c.native_read_control(self.control)
        for key,value in (("schema","a1-native-drive-read-unknown-v1"),("checkpoint_file_id","fixture-wrong-123"),
                          ("human_authority_sha256",self.s.VALIDITY_AUTHORITY),
                          ("grant_reference","SYNTHETIC_NOT_APPROVAL")):
            bad=copy.deepcopy(self.control);bad[key]=value
            with self.subTest(key=key),self.assertRaises(c.Refused):self.s.named_read_control(c,bad)

    def test_new_deadline_uses_fixed_validity_without_relabeling_original_first(self):
        jobs=copy.deepcopy(self.jobs)
        jobs["jobs"][1].update(status="in_progress",started_at="2026-10-19T11:00:00Z")
        self.assertEqual(self.s.named_read_job_deadline(c,jobs),self.clock+timedelta(seconds=240))
        workflow=(c.ROOT/'.github/workflows/alpaca_sip_private_backfill_v1.yml').read_text(encoding='utf-8')
        upload=workflow.split('- name: Preserve native read meter without original bytes or private IDs',1)[1].split('- name:',1)[0]
        self.assertIn('timeout-minutes: 1',upload)
        jobs["jobs"][1]["started_at"]=None
        with self.assertRaises(c.Refused):self.s.named_read_job_deadline(c,jobs)
        self.assertEqual(c.CONTINUATION["first"],"2026-10-17T02:08:51Z")

    def test_missing_or_edited_owner_proof_stops_before_oauth(self):
        terms=self.s.named_read_terms(c,self.control)
        comment=dict(id=123456789,issue_url=f"https://api.github.com/repos/{c.REPO}/issues/448",
            author_association="OWNER",user=dict(type="User",id=123),
            body="A1_SIP_NAMED_READ39235028468_AUTHORIZATION "+c.encoded(terms).decode(),
            created_at="2026-10-19T10:20:00Z",updated_at="2026-10-19T10:20:00Z")
        with patch.object(c,"gh_json",return_value=comment):self.s.named_read_proof(c,self.control)
        for bad in ({},dict(comment,updated_at="2026-10-19T10:21:00Z"),
                    dict(comment,author_association="CONTRIBUTOR"),dict(comment,body="old grant")):
            with patch.dict(os.environ,self.env,clear=True),patch.object(c,"gh_json",return_value=bad),\
                 patch.object(drive_module,"OwnerDrive") as constructor,self.assertRaises(c.Refused):
                self.s.named_read_worker(c,self.control,str(self.root/"worker"))
            constructor.assert_not_called()

    def test_exclusive_context_and_actual29_prefix(self):
        ids=self.s.BASIS_IDS+[self.s.REFUSAL_RUN,self.s.CONTROL_RUN,
            39225295971,39227056047,39228995303,39230864255,39232902584,39235028468]
        runs=[dict(id=i) for i in ids]+[self.run]
        self.assertEqual(len(self.s.named_read_prefix(c,runs,self.control,self.run)),29)
        for wrong in (runs[:-1],runs+[dict(id=1)],runs[:-2]+[dict(id=39085031884),self.run]):
            with self.assertRaises(c.Refused):self.s.named_read_prefix(c,wrong,self.control,self.run)
        observed=dict(runs=runs[:-1],examined=296,parent_sha=self.s.READ392_CP,
            receipts=[{}],used=self.s.READ392_USED,active_seconds=8736,first=c.utc(c.CONTINUATION["first"]))
        with patch.object(self.s,"READ392_METER",c.digest(c.encoded({}))):
            self.s.named_read_budget(c,observed)
            for key,value in (("examined",76),("active_seconds",3769),("used",dict(self.s.READ392_USED,provider_gets=0))):
                bad=dict(observed);bad[key]=value
                with self.assertRaises(c.Refused):self.s.named_read_budget(c,bad)

    def test_transitive_revision_pin_is_required(self):
        gh=self.deployment_fixture()
        def wrong(path):
            if "/contents/"+c.REVISION_MODULE in path:
                return dict(encoding="base64",content=c.base64.b64encode(b"wrong").decode())
            return gh(path)
        with patch.object(c,"gh_json",side_effect=wrong):
            with self.assertRaisesRegex(c.Refused,"NAMED_READ_CODE_PINS"):
                self.s.named_read_deployed(c,self.control)

    def test_frozen_original_and_cohort_prefix_cannot_hide_a_missing_or_changed_event(self):
        registry=c.WorkJournal(self.root/"prefix","f"*64)
        self.addCleanup(registry.close)
        for i in range(17):registry.append("FIXTURE",index=i)
        self.s.named_read_frozen_prefix(c,registry.directory,17,registry.parent)
        path=registry.directory/"000003.json";raw=path.read_bytes()
        path.write_bytes(raw.replace(b'FIXTURE',b'ALTERED'))
        with self.assertRaises(c.Refused):self.s.named_read_frozen_prefix(c,registry.directory,17,registry.parent)
        path.write_bytes(raw);path.rename(registry.directory/"000003.hidden")
        with self.assertRaises(c.Refused):self.s.named_read_frozen_prefix(c,registry.directory,17,registry.parent)

    def test_no_missing_nonfinal_or_refunded_cost_receipt(self):
        result,value,m,server=self.read_objects()
        for mutate in (
            lambda v:v.update(finalized=False),
            lambda v:v.update(schema="a1-sip-campaign-meter-v1"),
            lambda v:v["usage"].update(drive_bytes=0),
            lambda v:v["attempts"][0].update(response_bytes=2000001),
            lambda v:v["attempts"][0].update(reservation=0),
            lambda v:v.update(observed_google_body_bytes=0),
            lambda v:v["result"].update(absence_proven=True)):
            bad=copy.deepcopy(value);mutate(bad)
            with self.assertRaises(c.Refused):self.s.named_read_cost(c,self.control,self.run,bad,self.jobs)
        with self.assertRaises(c.Refused):self.s.named_read_cost(c,self.control,self.run,{},self.jobs)

    def test_once_only_cost_append_and_both_durability_barriers(self):
        result,value,m,server=self.read_objects()
        payload=self.s.named_read_cost(c,self.control,self.run,value,self.jobs)
        registry=c.WorkJournal(self.root/"family","f"*64)
        self.addCleanup(registry.close)
        for i in range(74):registry.append("FIXTURE",index=i)
        registry.append("SETTLED",run_id=39235028468)
        with patch.object(self.s,"READ392_FAMILY",registry.parent):
            with patch.object(c,"sync_native18_settlement",side_effect=c.Refused("EXTERNAL_NATIVE18_DURABILITY")):
                with self.assertRaises(c.Refused):self.s.named_read_append_cost(c,registry,payload)
            self.assertEqual(len(registry.entries),76)
            with patch.object(c,"sync_native18_settlement",wraps=c.sync_native18_settlement) as sync:
                first=self.s.named_read_append_cost(c,registry,payload)
                self.assertEqual(self.s.named_read_append_cost(c,registry,payload),first)
                self.assertEqual(sync.call_count,2)
            self.assertEqual(len(registry.entries),76)
            with self.assertRaises(c.Refused):
                self.s.named_read_append_cost(c,registry,dict(payload,meter_sha256="0"*64))


    def test_control_fits_original_bounded_input_with_real_sized_auth(self):
        value=copy.deepcopy(self.control)
        raw=c.encoded(value["authorization"])
        value["authorization"]["fixture_padding"]="x"*(14924-len(raw)-21)
        self.assertLessEqual(len(c.encoded(value)),16384)
        self.assertLess(len(c.encoded(self.s.named_read_terms(c,self.control))),4096)

    def test_worker_positive_flow_keeps_collector_outside_read_path(self):
        server=self.server()
        observed=dict(runs=[dict(id=1)]*28+[dict(id=39235028468)],examined=296,parent_sha=self.s.READ392_CP,
            receipts=[{}],used=dict(self.s.READ392_USED),active_seconds=8736,first=c.utc(c.CONTINUATION["first"]))
        current=dict(self.run,status="in_progress")
        jobs=copy.deepcopy(self.jobs);jobs["jobs"][1].update(status="in_progress",started_at=self.clock.isoformat())
        @c.contextmanager
        def fixture_deadline(meter):
            meter.alarm_active=True
            try:yield
            finally:meter.alarm_active=False
        def gh(path):
            if path.endswith("/branches/master"):return dict(protected=True,commit=dict(sha=self.control["expected_master"]))
            if path.endswith("/jobs?per_page=100"):return jobs
            return current
        with patch.dict(os.environ,self.env,clear=True),\
             patch.object(self.s,"named_read_proof",return_value=("b"*64,self.run["created_at"])),\
             patch.object(self.s,"named_read_deployed",return_value={p:"a"*64 for p in self.s.V6_PINS}),\
             patch.object(self.s,"READ392_METER",c.digest(c.encoded({}))),\
             patch.object(c,"external_history",return_value=observed),patch.object(c,"gh_json",side_effect=gh),\
             patch.object(c,"build_opener",return_value=server),\
             patch.object(c.RuntimeMeter,"process_deadline",fixture_deadline),\
             patch.object(cap,"run",side_effect=AssertionError("Collector invoked by read mode")):
            result=self.s.named_read_worker(c,self.control,str(self.root/"worker-positive"))
        self.assertEqual(result["status"],"NAMED_READ_COMPLETE")
        receipt=c.bounded_json(self.root/"worker-positive/native_read_meter.json")
        self.assertTrue(receipt["finalized"]);self.assertEqual(receipt["usage"]["provider_gets"],0)

    def deployment_fixture(self):
        # Saved genuine gate shapes (649/39223863645), isolated synthetic IDs.
        self.trusted_gate_bytes={p:("isolated-fixture:"+p).encode() for p in self.s.READ392_GATE_PINS}
        patch.object(self.s,"READ392_GATE_PINS",{p:c.digest(b) for p,b in self.trusted_gate_bytes.items()}).start()
        self.deployment_pins={p:c.digest((c.ROOT/p).read_bytes().replace(b"\r\n",b"\n")) for p in self.s.V6_PINS}
        self.control["code_pins_sha256"]=c.digest(c.encoded(self.deployment_pins))
        event=c.bounded_json(self.event_path);event["inputs"]["campaign_control"]=c.encoded(self.control).decode()
        self.event_path.write_bytes(c.encoded(event))
        self.pr=dict(number=123,merged=True,draft=False,base=dict(ref="master",repo=dict(full_name=c.REPO)),
            head=dict(sha="5"*40,repo=dict(full_name=c.REPO)),merge_commit_sha="4"*40)
        self.branch=dict(protected=True,commit=dict(sha="4"*40))
        self.tree=dict(tree=dict(sha="6"*40))
        self.checks=dict(total_count=3,check_runs=[dict(id=100+i,name=n,head_sha="5"*40,status="completed",conclusion="success",
            app=dict(slug="github-actions"),check_suite=dict(id=200+i),started_at="2026-10-19T10:25:41Z",
            completed_at="2026-10-19T10:25:41Z") for i,n in enumerate(("validate","offline","review_complete"))])
        self.checks["check_runs"][2]["output"]=dict(title="PASS_REVIEW_COMPLETE",summary=
            "Evidence: ATTESTED_EXACT_HEAD_REVIEW\n\nFailures: none\n\n"
            "Unresolved conversations are enforced separately by master branch protection.")
        self.gate=dict(id=301,workflow_id=317164841,path=".github/workflows/review_complete_gate.yml",
            event="issue_comment",status="completed",conclusion="success",run_attempt=1,head_sha="7"*40,
            check_suite_id=401,repository=dict(full_name=c.REPO),head_repository=dict(full_name=c.REPO),
            created_at="2026-10-19T10:25:33Z",updated_at="2026-10-19T10:25:44Z")
        self.gate_jobs=dict(total_count=1,jobs=[dict(id=501,run_id=301,name="evaluate",status="completed",conclusion="success",
            started_at="2026-10-19T10:25:35Z",completed_at="2026-10-19T10:25:43Z",steps=[dict(name=n,status="completed",conclusion="success") for n in (
                "Checkout trusted gate implementation","Resolve trusted head observation and maintainer attestation",
                "Evaluate Codex review evidence for current head","Publish required review_complete check on PR head")])])
        self.evaluation=dict(schema_version="run287-review-complete-gate-v2",status="PASS_REVIEW_COMPLETE",passed=True,
            pull_request_number=123,head_sha="5"*40,evidence_type="ATTESTED_EXACT_HEAD_REVIEW",failures=[])
        self.published=copy.deepcopy(self.checks["check_runs"][2])
        def log():
            text="[command]/usr/bin/git log -1 --format=%H\n"+"7"*40+"\n"+json.dumps(self.evaluation,indent=2)+"\n"+json.dumps(self.published)+"\n"
            return "\n".join("2026-10-19T10:25:41.0000000Z "+line for line in text.splitlines())
        self.gate_log=log
        self.github_reads=[]
        def gh(path):
            self.github_reads.append(path)
            if path.endswith("/branches/master"):return self.branch
            if "/contents/" in path:
                file=path.split("/contents/",1)[1].split("?ref=",1)[0]
                raw=self.trusted_gate_bytes[file] if file in self.trusted_gate_bytes else (c.ROOT/file).read_bytes().replace(b"\r\n",b"\n")
                return dict(encoding="base64",content=c.base64.b64encode(raw).decode())
            if path.endswith("/pulls/123"):return self.pr
            if "/git/commits/" in path:return self.tree
            if "/check-runs?" in path:return self.checks
            if "/actions/workflows/317164841/runs?" in path:return dict(total_count=1,workflow_runs=[self.gate])
            if path.endswith("/actions/runs/301/jobs?per_page=100"):return self.gate_jobs
            raise AssertionError("Unexpected GitHub read: "+path)
        return gh

    def test_genuine_deployment_requires_merged_exact_tree_and_real_checks(self):
        gh=self.deployment_fixture()
        with patch.object(c,"gh_json",side_effect=gh),patch.object(self.s,"named_read_gate_log",side_effect=lambda *a:self.gate_log()):
            self.assertEqual(self.s.named_read_deployed(c,self.control),self.deployment_pins)
            self.pr["draft"]=True
            with self.assertRaises(c.Refused):self.s.named_read_deployed(c,self.control)
            self.pr["draft"]=False;self.checks["check_runs"][2]["conclusion"]="skipped"
            with self.assertRaises(c.Refused):self.s.named_read_deployed(c,self.control)

    def test_same_app_named_success_is_not_a_gate_proof_and_denies_before_oauth(self):
        gh=self.deployment_fixture();self.gate["path"]=".github/workflows/other.yml"
        with patch.dict(os.environ,self.env,clear=True),patch.object(c,"gh_json",side_effect=gh),\
             patch.object(self.s,"named_read_proof",return_value=("b"*64,"2026-10-19T10:20:00Z")),\
             patch.object(self.s,"named_read_gate_log",side_effect=lambda *a:self.gate_log()),\
             patch.object(drive_module,"OwnerDrive") as owner,patch.object(c,"build_opener") as opener,\
             self.assertRaises(c.Refused):
            self.s.named_read_worker(c,self.control,str(self.root/"forged"))
        owner.assert_not_called();opener.assert_not_called()

    def test_gate_rejects_wrong_workflow_run_job_head_evaluation_and_publication(self):
        gh=self.deployment_fixture()
        objects=[self.gate,self.gate_jobs,self.evaluation,self.published,self.checks,self.tree,self.pr]
        snapshots=copy.deepcopy(objects)
        mutations=[lambda:self.gate.update(workflow_id=999),lambda:self.gate.update(event="pull_request"),
            lambda:self.gate["repository"].update(full_name="other/repo"),lambda:self.gate.update(status="in_progress"),
            lambda:self.gate_jobs["jobs"][0].update(run_id=999),lambda:self.gate_jobs["jobs"][0].update(conclusion="failure"),
            lambda:self.gate_jobs["jobs"][0]["steps"].pop(),lambda:self.evaluation.update(head_sha="0"*40),
            lambda:self.evaluation.update(pull_request_number=999),lambda:self.evaluation.update(passed=False),
            lambda:self.evaluation.update(failures=["missing_maintainer_attestation"]),
            lambda:self.evaluation.update(evidence_type="LOCAL_A6"),lambda:self.published.update(id=999),
            lambda:self.published["check_suite"].update(id=999),lambda:self.published["output"].update(summary="forged"),
            lambda:self.checks["check_runs"][2].update(check_suite={}),lambda:self.tree["tree"].update(sha="bad"),
            lambda:self.pr["head"].update(sha="0"*40)]
        with patch.object(c,"gh_json",side_effect=gh),patch.object(self.s,"named_read_gate_log",side_effect=lambda *a:self.gate_log()):
            for index,mutate in enumerate(mutations):
                for obj,original in zip(objects,snapshots):obj.clear();obj.update(copy.deepcopy(original))
                mutate()
                with self.subTest(case=index),self.assertRaises(c.Refused):self.s.named_read_deployed(c,self.control)

    def test_new_read_denies_master_advance_but_historical_proof_uses_frozen_source(self):
        gh=self.deployment_fixture();self.branch["commit"]["sha"]="9"*40
        with patch.object(c,"gh_json",side_effect=gh),patch.object(self.s,"named_read_gate_log",side_effect=lambda *a:self.gate_log()):
            with self.assertRaisesRegex(c.Refused,"CAMPAIGN_MASTER_DRIFT"):self.s.named_read_deployed(c,self.control)
            self.github_reads.clear()
            self.assertEqual(self.s.named_read_deployed(c,self.control,accounting=True),self.deployment_pins)
            self.assertFalse(any(p.endswith("/branches/master") for p in self.github_reads))
            self.assertTrue(all("?ref="+"4"*40 in p or "?ref="+"7"*40 in p for p in self.github_reads if "/contents/" in p))

    def test_gate_rejects_missing_malformed_log_or_changed_trusted_implementation(self):
        gh=self.deployment_fixture()
        with patch.object(c,"gh_json",side_effect=gh):
            for text in ("", "malformed",json.dumps(self.evaluation),self.gate_log().replace("7"*40,"bad-sha")):
                with patch.object(self.s,"named_read_gate_log",return_value=text),self.assertRaises(c.Refused):
                    self.s.named_read_deployed(c,self.control)
            self.trusted_gate_bytes[".github/workflows/review_complete_gate.yml"]=b"unreviewed gate replacement"
            with patch.object(self.s,"named_read_gate_log",return_value=self.gate_log()),self.assertRaises(c.Refused):
                self.s.named_read_deployed(c,self.control)

    def test_workflow_worker_token_has_only_required_read_permissions(self):
        text=(c.ROOT/".github/workflows/alpaca_sip_private_backfill_v1.yml").read_text(encoding="utf-8")
        block=text.split("\npermissions:\n",1)[1].split("\nconcurrency:",1)[0]
        self.assertEqual(dict(line.strip().split(": ") for line in block.splitlines()),
            {"contents":"read","actions":"read","issues":"read","checks":"read"})
        self.assertIn("GH_TOKEN: ${{ github.token }}",text)

    def test_historical_settle_host_reopen_reflush_keeps_old_bytes_after_master_advance(self):
        gh=self.deployment_fixture();self.branch["commit"]["sha"]="9"*40
        _,value,_,_=self.read_objects()
        budget=self.root/"original";state=self.root/"external-cohort-top500-20261017"
        original=c.WorkJournal(budget,"a"*64);cohort=c.WorkJournal(state,"b"*64)
        registry=c.WorkJournal(self.root/"family-settle","f"*64)
        for target,count in ((original,17),(cohort,48),(registry,74)):
            for i in range(count):target.append("FIXTURE",index=i)
        registry.append("SETTLED",run_id=39235028468)
        family_tail=registry.parent;original_tail=original.parent;cohort_tail=cohort.parent
        original.close();cohort.close();self.addCleanup(lambda:registry.close())
        before={p:p.read_bytes() for directory in (budget,state,registry.directory) for p in directory.glob("*.json")}
        control_path=self.root/"historical-control.json";control_path.write_bytes(c.encoded(self.control))
        args=SimpleNamespace(native392_settle_control=control_path,native392_run_id=self.run["id"],
            budget_state_dir=budget,state_dir=state)
        observed=dict(runs=[{}]*29,examined=296,parent_sha=self.s.READ392_CP,
            receipts=[{}],used=dict(self.s.READ392_USED),active_seconds=8736,first=c.utc(c.CONTINUATION["first"]))
        def metadata(path):
            if path.endswith("/actions/runs/40000000000"):return self.run
            if path.endswith("/actions/runs/40000000000/jobs?per_page=100"):return self.jobs
            if path.endswith("/artifacts?per_page=100"):
                return dict(total_count=1,artifacts=[dict(name="a1-native-drive-read-meter",id=601,expired=False,size_in_bytes=1000)])
            return gh(path)
        def download(argv,**kwargs):
            Path(argv[argv.index("--dir")+1],"native_read_meter.json").write_bytes(c.encoded(value))
            return SimpleNamespace(returncode=0)
        with patch.object(c,"gh_json",side_effect=metadata),patch.object(self.s,"named_read_gate_log",side_effect=lambda *a:self.gate_log()),\
             patch.object(self.s,"named_read_proof",return_value=("b"*64,"2026-10-19T10:20:00Z")),\
             patch.object(c,"external_history",return_value=observed),patch.object(self.s,"named_read_budget"),\
             patch.dict(c.CONTINUATION,event=original_tail),patch.object(self.s,"READ392_COHORT",cohort_tail),\
             patch.object(self.s,"READ392_FAMILY",family_tail),patch.object(c,"external_family_registry",side_effect=lambda *a:registry),\
             patch.object(c.subprocess,"run",side_effect=download):
            # The event was written, but a file/directory barrier failed.
            with patch.object(c,"sync_native18_settlement",side_effect=c.Refused("SYNTHETIC_BARRIER")):
                with self.assertRaisesRegex(c.Refused,"SYNTHETIC_BARRIER"):self.s.named_read_settle_host(c,args)
            self.assertEqual(len(registry.entries),76)
            appended=(registry.directory/"000076.json").read_bytes()
            registry=c.WorkJournal(registry.directory,"f"*64)
            with patch.object(c,"sync_native18_settlement",wraps=c.sync_native18_settlement) as barrier:
                first=self.s.named_read_settle_host(c,args)
                registry=c.WorkJournal(registry.directory,"f"*64)
                self.assertEqual(self.s.named_read_settle_host(c,args),first)
                self.assertEqual(barrier.call_count,2)
            self.assertEqual(appended,(registry.directory/"000076.json").read_bytes())
            self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))
            self.assertEqual(first["usage_after"],{k:self.s.READ392_USED[k]+value["usage"][k] for k in c.LIMITS})
            self.assertFalse(any(p.endswith("/branches/master") for p in self.github_reads))

    def test_gate_log_is_bounded_and_suppresses_raw_errors(self):
        def output(argv,**kw):
            if argv==["gh","api","--help"]:
                kw["stdout"].write(b"Usage: gh api");return SimpleNamespace(returncode=0)
            self.assertEqual(argv,["gh","api",f"repos/{c.REPO}/actions/jobs/501/logs"])
            self.assertNotEqual(kw["stdout"],c.subprocess.PIPE)
            self.assertNotEqual(kw["stderr"],c.subprocess.PIPE)
            kw["stdout"].write(b"x"*2_000_001);return SimpleNamespace(returncode=0)
        with patch.object(c.subprocess,"run",side_effect=output),self.assertRaisesRegex(c.Refused,"NAMED_READ_GATE_LOG"):
            self.s.named_read_gate_log(c,501)
        with patch.object(c.subprocess,"run",side_effect=OSError("PRIVATE_CANARY")),self.assertRaisesRegex(c.Refused,"NAMED_READ_GATE_LOG") as error:
            self.s.named_read_gate_log(c,501)
        self.assertTrue(error.exception.__suppress_context__)


    def test_private_event_is_bound_to_control_and_never_exported_as_job_env(self):
        with patch.dict(os.environ,self.env,clear=True):
            self.assertEqual(c.native_read_control_from_event(),self.control)
        original=c.bounded_json(self.event_path)
        for key,replacement in (("private_root_folder_id","fixture-other-123"),
                                ("private_data_folder_id","fixture-other-123"),
                                ("campaign_nonce",c.PREFIX+"b"*24),
                                ("private_research_authorized","false"),
                                ("noncommercial_terms_acknowledged",1),
                                ("campaign_control","{}")):
            value=copy.deepcopy(original);value["inputs"][key]=replacement
            self.event_path.write_bytes(c.encoded(value))
            with self.subTest(key=key),patch.dict(os.environ,self.env,clear=True),\
                 patch.object(c,"gh_json",side_effect=AssertionError("Proof lookup before actual event binding")),\
                 patch.object(drive_module,"OwnerDrive") as constructor,self.assertRaises(c.Refused):
                self.s.named_read_worker(c,self.control,str(self.root/"denied-worker"))
            constructor.assert_not_called()
        self.event_path.write_bytes(c.encoded(original))
        for key in ("INPUT_CAMPAIGN_CONTROL","INPUT_PRIVATE_ROOT_FOLDER_ID","INPUT_PRIVATE_DATA_FOLDER_ID","INPUT_RESUME_FILE_ID"):
            env=dict(self.env,**{key:"PRIVATE_CANARY"})
            with patch.dict(os.environ,env,clear=True),self.assertRaises(c.Refused):
                c.native_read_control_from_event()

    def test_private_event_raw_bounds_and_expected_control_binding(self):
        original=self.event_path.read_bytes()
        for raw in (b"x"*65537,c.encoded(dict(inputs=dict(campaign_control="x"*16385))),b'{}'):
            self.event_path.write_bytes(raw)
            with patch.dict(os.environ,self.env,clear=True),self.assertRaises(c.Refused):
                c.native_read_control_from_event()
        self.event_path.write_bytes(original)
        wrong=copy.deepcopy(self.control);wrong["nonce"]=c.PREFIX+"b"*24
        with patch.dict(os.environ,self.env,clear=True),self.assertRaises(c.Refused):
            self.s.named_read_event_control(c,wrong)

    def test_actual_workflow_premeter_block_reads_private_event_silently(self):
        text=(c.ROOT/".github/workflows/alpaca_sip_private_backfill_v1.yml").read_text(encoding="utf-8")
        block=text.split("- name: Prepare bounded control metadata before credentials",1)[1]
        block=block.split("- name: Reconcile exact failed Drive POST",1)[0]
        body=block.split("python - <<'PY'\n",1)[1].rsplit("          PY",1)[0]
        program="\n".join(line[10:] for line in body.splitlines())
        directory=self.root/"premeter";directory.mkdir()
        env=dict(self.env,RUNNER_TEMP=str(directory))
        with patch.dict(os.environ,env,clear=True),patch("sys.stdout",new_callable=io.StringIO) as output:
            exec(compile(program,"<actual-workflow-premeter>","exec"),{})
        self.assertEqual(output.getvalue(),"")
        self.assertEqual(c.bounded_json(directory/"campaign_control.json"),self.control)
        for key in ("INPUT_CAMPAIGN_CONTROL","INPUT_PRIVATE_ROOT_FOLDER_ID","INPUT_PRIVATE_DATA_FOLDER_ID","INPUT_RESUME_FILE_ID"):
            line=next(line for line in text.splitlines() if line.strip().startswith(key+":"))
            self.assertIn("${{ !(",line);self.assertIn("&& inputs.",line)
            self.assertTrue(line.endswith("|| '' }}"))

    def test_workflow_new_schema_has_read_only_route_and_unknown_schema_refusal(self):
        text=(c.ROOT/".github/workflows/alpaca_sip_private_backfill_v1.yml").read_text(encoding="utf-8")
        self.assertEqual(text.count("schema == 'a1-native-drive-read-39235028468-v1'"),8)
        self.assertIn("CAMPAIGN_CONTROL_SCHEMA",text)
        self.assertIn("native_read_route_control(value)",text)
        self.assertIn("if: env.INPUT_NATIVE_READ_ONLY != 'true'",text)
        self.assertIn("' native-read39235028468'",text)

class NamedRead392DeploymentWindowTests(unittest.TestCase):
    """Versioned renewal: real collector remains outside this read-only path."""
    server=NamedRead39235028468Tests.server
    read_objects=NamedRead39235028468Tests.read_objects

    def deployment_fixture(self):
        gh=NamedRead39235028468Tests.deployment_fixture(self)
        patch.object(self.s,"named_read_gate_log",side_effect=lambda *a:self.gate_log()).start()
        return gh

    def setUp(self):
        NamedRead39235028468Tests.setUp(self)
        self.actual_deployment_pr=self.s.READ392_V2_DEPLOYMENT_PR
        patch.object(self.s,"READ392_V2_DEPLOYMENT_PR",123).start()
        self.clock=c.utc("2026-10-20T11:00:00Z")
        self.control.update(schema=self.s.READ392_V2_SCHEMA,human_authority_sha256=self.s.READ392_V2_AUTHORITY,
            deployment_window=dict(deployed_at_utc="2026-10-20T10:00:00Z",expires_at_utc="2026-10-21T10:00:00Z"))
        self.run["created_at"]="2026-10-20T10:30:00Z"
        for job in self.jobs["jobs"]:
            for field in ("started_at","completed_at"):job[field]=job[field].replace("2026-10-19","2026-10-20")
        self.bind_event()

    def bind_event(self):
        event=c.bounded_json(self.event_path)
        event["inputs"]["campaign_control"]=c.encoded(self.control).decode()
        self.event_path.write_bytes(c.encoded(event))

    def make_meter(self,server,**kwargs):
        ident=dict(task_key=self.s.READ392_TASK,run_id=self.run["id"],run_attempt=1,
            nonce=self.control["nonce"],control_sha256=c.digest(c.encoded(self.control)),grant_proof_sha256="b"*64,
            source_sha=self.control["expected_master"],source_pins=getattr(self,"deployment_pins",{p:"a"*64 for p in self.s.V6_PINS}),
            parent_checkpoint_sha256=self.s.READ392_CP,examined_before=296,failed_run_id=39235028468,
            failed_meter_sha256=self.s.READ392_METER,usage_before=self.s.READ392_USED,
            active_seconds_before=8736,dispatches_before=29,active_seconds_reservation=900,dispatch_reservation=1)
        directory=self.root/("meter-"+str(len(list(self.root.iterdir()))));directory.mkdir()
        end=min(self.clock+timedelta(seconds=300),c.utc(self.control["deployment_window"]["expires_at_utc"]))
        return self.s.named_read_meter(c,self.s.READ392_ALLOWANCE,directory/"native_read_meter.json",
            end.isoformat(),ident,opener=server,limits=c.CONTINUED_LIMITS,
            clock=lambda:c.utc(),control=self.control,**kwargs)

    def owner_comment(self):
        return dict(id=123456789,issue_url=f"https://api.github.com/repos/{c.REPO}/issues/448",
            author_association="OWNER",user=dict(type="User",id=123),
            body="A1_SIP_NAMED_READ39235028468_V2_AUTHORIZATION "+c.encoded(self.s.named_read_terms(c,self.control)).decode(),
            created_at="2026-10-20T10:20:00Z",updated_at="2026-10-20T10:20:00Z")

    def test_expired_v1_not_resurrected_by_v2(self):
        self.s.named_read_control(c,self.control)
        old=copy.deepcopy(self.control);old["schema"]=self.s.READ392_SCHEMA;old.pop("deployment_window")
        with self.assertRaisesRegex(c.Refused,"CAMPAIGN_EXPIRED"):self.s.named_read_control(c,old)
        self.assertEqual(self.s.VALIDITY_END,"2026-10-20T02:59:53Z")
        self.assertEqual(c.CONTINUATION["first"],"2026-10-17T02:08:51Z")

    def test_only_actual_renewal_decision_hash_is_accepted(self):
        for authority in (self.s.VALIDITY_AUTHORITY,"0"*64,"d"*64):
            bad=copy.deepcopy(self.control);bad["human_authority_sha256"]=authority
            with self.subTest(authority=authority),self.assertRaises(c.Refused):self.s.named_read_control(c,bad)

    def test_window_shape_and_exact_24h_fail_before_credentials(self):
        windows=[{},dict(deployed_at_utc="2026-10-20T10:00:00Z",expires_at_utc="2026-10-21T10:00:01Z"),
            dict(deployed_at_utc="2026-10-20T10:00:00Z",expires_at_utc="2026-10-20T10:00:00Z"),
            dict(deployed_at_utc="2026-10-21T10:00:00Z",expires_at_utc="2026-10-22T10:00:00Z"),
            dict(deployed_at_utc="2026-10-19T10:00:00Z",expires_at_utc="2026-10-20T10:00:00Z")]
        for window in windows:
            bad=copy.deepcopy(self.control);bad["deployment_window"]=window
            with self.subTest(window=window),patch.object(drive_module,"OwnerDrive") as owner,self.assertRaises(c.Refused):
                self.s.named_read_worker(c,bad,str(self.root/"blocked"))
            owner.assert_not_called()

    def test_real_merged_at_binds_declared_window(self):
        gh=self.deployment_fixture();self.pr["merged_at"]="2026-10-20T10:00:00Z"
        with patch.object(c,"gh_json",side_effect=gh):self.s.named_read_deployed(c,self.control)
        for merged in (None,"2026-10-20T09:59:59Z","2026-10-20T11:00:01Z"):
            self.pr["merged_at"]=merged
            with self.subTest(merged=merged),patch.object(c,"gh_json",side_effect=gh),self.assertRaisesRegex(c.Refused,"DEPLOYMENT_WINDOW"):
                self.s.named_read_deployed(c,self.control)

    def test_relabeling_merge_control_and_window_cannot_extend_time(self):
        gh=self.deployment_fixture();self.pr["merged_at"]="2026-10-20T10:00:00Z"
        self.control["deployment_window"]=dict(deployed_at_utc="2026-10-20T10:30:00Z",expires_at_utc="2026-10-21T10:30:00Z")
        with patch.object(c,"gh_json",side_effect=gh),self.assertRaisesRegex(c.Refused,"DEPLOYMENT_WINDOW"):
            self.s.named_read_deployed(c,self.control)

    def test_v2_approval_is_bound_to_this_one_source_pr(self):
        self.assertEqual(self.actual_deployment_pr,650)
        self.control['deployment']['pull_request']=124
        with patch.object(drive_module,'OwnerDrive') as owner,self.assertRaisesRegex(c.Refused,'DEPLOYMENT_SCOPE'):
            self.s.named_read_worker(c,self.control,str(self.root/'foreign-pr'))
        owner.assert_not_called()

    def test_unused_expired_window_cannot_rearm_on_later_genuine_source_pr(self):
        gh=self.deployment_fixture()
        self.clock=c.utc('2026-10-22T11:00:00Z')
        self.pr.update(number=124,merged_at='2026-10-22T10:00:00Z')
        self.control['deployment']['pull_request']=124
        self.control['deployment_window']=dict(deployed_at_utc='2026-10-22T10:00:00Z',expires_at_utc='2026-10-23T10:00:00Z')
        self.control['nonce']=c.PREFIX+'b'*24
        def later(p):return self.pr if p.endswith('/pulls/124') else gh(p)
        # Other source pins, full tree and genuine gate fixture still match.
        with patch.object(c,'gh_json',side_effect=later),self.assertRaisesRegex(c.Refused,'DEPLOYMENT_SCOPE'):
            self.s.named_read_deployed(c,self.control)
        with self.assertRaisesRegex(c.Refused,'DEPLOYMENT_SCOPE'):self.s.named_read_control(c,self.control)

    def test_v2_grant_is_new_immutable_and_after_actual_deployment(self):
        comment=self.owner_comment()
        with patch.object(c,"gh_json",return_value=comment):self.s.named_read_proof(c,self.control)
        for bad in (dict(comment,updated_at="2026-10-20T10:21:00Z"),dict(comment,author_association="CONTRIBUTOR"),
            dict(comment,body=comment["body"].replace("_V2_AUTHORIZATION","_AUTHORIZATION")),
            dict(comment,created_at="2026-10-20T09:59:59Z",updated_at="2026-10-20T09:59:59Z")):
            with patch.object(c,"gh_json",return_value=bad),self.assertRaises(c.Refused):self.s.named_read_proof(c,self.control)

    def test_v2_terms_bind_priority_without_granting_capture(self):
        terms=self.s.named_read_terms(c,self.control)
        self.assertEqual(terms["schema"],"a1-named-read39235028468-grant-v2")
        self.assertEqual(terms["next_collection_priority_input_sha256"],self.s.READ392_V2_INPUT)
        self.assertEqual(terms["expires_at_utc"],"2026-10-21T10:00:00Z")
        self.assertFalse(terms["capture_authorized"]);self.assertFalse(terms["budget_reset"])
        self.assertEqual(terms["unknown_storage_still_charged"],[302101,434796])

    def test_v2_control_and_terms_fit_original_wire_limits(self):
        NamedRead39235028468Tests.test_control_fits_original_bounded_input_with_real_sized_auth(self)

    def test_new_job_deadline_clamps_to_actual_24h_end(self):
        self.clock=c.utc("2026-10-21T09:59:58Z")
        jobs=copy.deepcopy(self.jobs)
        jobs["jobs"][1].update(status="in_progress",started_at="2026-10-21T09:59:55Z")
        self.assertEqual(self.s.named_read_job_deadline(c,jobs,control=self.control),c.utc("2026-10-21T10:00:00Z"))

    def test_v2_meter_and_cost_cannot_be_substituted_with_v1(self):
        result,value,m,server=self.read_objects()
        self.assertEqual(value["schema"],"a1-named-read39235028468-meter-v2")
        cost=self.s.named_read_cost(c,self.control,self.run,value,self.jobs)
        self.assertEqual(cost["schema"],"a1-named-read39235028468-cost-settlement-v2")
        bad=copy.deepcopy(value);bad["schema"]="a1-named-read39235028468-meter-v1"
        with self.assertRaises(c.Refused):self.s.named_read_cost(c,self.control,self.run,bad,self.jobs)

    def test_accounting_and_cleanup_after_expiry_preserve_spent_costs(self):
        result,value,m,server=self.read_objects();comment=self.owner_comment()
        self.clock=c.utc("2026-10-22T10:00:00Z")
        with self.assertRaisesRegex(c.Refused,"CAMPAIGN_EXPIRED"):self.s.named_read_control(c,self.control)
        self.s.named_read_control(c,self.control,accounting=True)
        with patch.object(c,"gh_json",return_value=comment):self.s.named_read_proof(c,self.control,accounting=True)
        jobs=copy.deepcopy(self.jobs)
        jobs["jobs"][1].update(started_at="2026-10-21T09:59:50Z",completed_at="2026-10-21T10:00:15Z")
        cost=self.s.named_read_cost(c,self.control,self.run,value,jobs)
        self.assertEqual(cost["usage_after"]["drive_bytes"],self.s.READ392_USED["drive_bytes"]+m.used["drive_bytes"])

    def test_v2_endpoint_allowlist_remains_read_only(self):
        NamedRead39235028468Tests.test_endpoint_allowlist_denies_writes_provider_arbitrary_ids_and_queries(self)

    def test_v2_save_failures_and_late_master_drift_remain_fail_closed(self):
        NamedRead39235028468Tests.test_reservation_and_response_save_failures_keep_importable_cost(self)
        NamedRead39235028468Tests.test_response_settlement_interruptions_publish_one_consistent_state(self)
        NamedRead39235028468Tests.test_interrupted_debit_publication_keeps_pending_for_final_save(self)
        NamedRead39235028468Tests.test_late_master_drift_in_history_or_jobs_refuses_before_secrets(self)

    def test_v2_temporary_cleanup_refresh_and_terminal_settlement(self):
        NamedRead39235028468Tests.test_real_atomic_temporary_write_flush_and_fsync_failures_recover(self)
        NamedRead39235028468Tests.test_initial_meter_save_failure_records_blocked_zero_io_once(self)
        NamedRead39235028468Tests.test_complete_and_blocked_cost_survive_terminal_job_failures(self)
        NamedRead39235028468Tests.test_token_refresh_crossing_sixty_seconds_is_admitted_once(self)

    def test_v2_cost_append_remains_exactly_once(self):
        NamedRead39235028468Tests.test_once_only_cost_append_and_both_durability_barriers(self)

    def test_worker_proves_only_named_history_uses_new_window_and_provider_zero(self):
        server=self.server();current=dict(self.run,status="in_progress")
        observed=dict(runs=[dict(id=1)]*28+[dict(id=39235028468)],examined=296,parent_sha=self.s.READ392_CP,
            receipts=[{}],used=dict(self.s.READ392_USED),active_seconds=8736,first=c.utc(c.CONTINUATION["first"]))
        jobs=copy.deepcopy(self.jobs);jobs["jobs"][1].update(status="in_progress",started_at="2026-10-20T11:00:00Z")
        def gh(p):
            if p.endswith('/branches/master'):return dict(protected=True,commit=dict(sha=self.control['expected_master']))
            return jobs if p.endswith('/jobs?per_page=100') else current
        @c.contextmanager
        def deadline(meter):
            meter.alarm_active=True
            try:yield
            finally:meter.alarm_active=False
        with patch.dict(os.environ,self.env,clear=True),patch.object(c,"gh_json",side_effect=gh),\
             patch.object(self.s,"named_read_proof",return_value=("b"*64,"2026-10-20T10:20:00Z")),\
             patch.object(self.s,"named_read_deployed",return_value={p:"a"*64 for p in self.s.V6_PINS}),\
             patch.object(self.s,"READ392_METER",c.digest(c.encoded({}))),patch.object(c,"external_history",return_value=observed) as history,\
             patch.object(c,"build_opener",return_value=server),patch.object(c.RuntimeMeter,"process_deadline",deadline),\
             patch.object(cap,"run",side_effect=AssertionError('Provider capture in read-only mode')):
            self.s.named_read_worker(c,self.control,str(self.root/'worker-v2'))
        self.assertFalse(history.call_args.kwargs['enforce_expiry'])
        self.assertEqual(history.call_args.kwargs['named_read_context'],(self.control,current))
        meter=c.bounded_json(self.root/'worker-v2/native_read_meter.json')
        self.assertEqual(meter['usage']['provider_gets'],0);self.assertEqual(meter['usage']['storage_bytes'],0)

    def test_v2_route_and_event_do_not_accept_unversioned_renewal(self):
        with patch.dict(os.environ,self.env,clear=True):
            self.assertEqual(c.native_read_route_control(self.control),self.a)
            self.assertEqual(c.native_read_control_from_event(),self.control)
        bad=copy.deepcopy(self.control);bad['schema']='a1-native-drive-read-39235028468-v3'
        with self.assertRaises(c.Refused):c.native_read_route_control(bad)

    def test_v2_workflow_has_same_private_reconcile_boundary(self):
        text=(c.ROOT/'.github/workflows/alpaca_sip_private_backfill_v1.yml').read_text(encoding='utf-8')
        self.assertEqual(text.count("schema == 'a1-native-drive-read-39235028468-v2'"),8)
        self.assertEqual(text.count("schema == 'a1-native-drive-read-39235028468-v3'"),8)
        for key in ('INPUT_CAMPAIGN_CONTROL','INPUT_PRIVATE_ROOT_FOLDER_ID','INPUT_PRIVATE_DATA_FOLDER_ID','INPUT_RESUME_FILE_ID'):
            line=next(line for line in text.splitlines() if line.strip().startswith(key+':'))
            self.assertIn("39235028468-v2",line);self.assertTrue(line.endswith("|| '' }}"))


class NamedRead392CorrectiveSourceTests(unittest.TestCase):
    """Correct execution bytes without re-arming650's already started clock."""
    server=NamedRead39235028468Tests.server
    read_objects=NamedRead39235028468Tests.read_objects
    make_meter=NamedRead392DeploymentWindowTests.make_meter
    bind_event=NamedRead392DeploymentWindowTests.bind_event

    def setUp(self):
        NamedRead392DeploymentWindowTests.setUp(self)
        self.control.update(schema=self.s.READ392_V3_SCHEMA,
            window_origin=dict(self.s.READ392_V3_ORIGIN),
            deployment=dict(pull_request=777,reviewed_head="5"*40),
            deployment_window=dict(deployed_at_utc=self.s.READ392_V3_ORIGIN["merged_at_utc"],
                expires_at_utc="2026-10-21T09:59:28Z"))
        self.run['created_at']='2026-10-20T10:45:00Z'
        for j in self.jobs['jobs']:
            j['started_at']='2026-10-20T10:45:05Z';j['completed_at']='2026-10-20T10:45:25Z'
        self.bind_event()

    def deployment_fixture(self):
        base=NamedRead392DeploymentWindowTests.deployment_fixture(self)
        self.pr.update(number=777,merged_at='2026-10-20T10:30:00Z')
        self.evaluation['pull_request_number']=777
        o=self.s.READ392_V3_ORIGIN
        self.origin_pr=copy.deepcopy(self.pr)
        self.origin_pr.update(number=o['pull_request'],merge_commit_sha=o['source_sha'],merged_at=o['merged_at_utc'])
        self.origin_pr['head']['sha']=o['reviewed_head']
        self.origin_tree=dict(tree=dict(sha=o['tree_sha']))
        self.origin_checks=copy.deepcopy(self.checks)
        for check in self.origin_checks['check_runs']:
            check['id']+=1000;check['head_sha']=o['reviewed_head']
        self.origin_gate=dict(self.gate,id=302)
        self.origin_jobs=copy.deepcopy(self.gate_jobs)
        self.origin_jobs['jobs'][0].update(id=502,run_id=302)
        self.origin_evaluation=dict(self.evaluation,pull_request_number=o['pull_request'],head_sha=o['reviewed_head'])
        def log(_c,job):
            if job==501:return self.gate_log()
            self.assertEqual(job,502)
            text='[command]/usr/bin/git log -1 --format=%H\n'+'7'*40+'\n'+json.dumps(self.origin_evaluation)+'\n'+json.dumps(self.origin_checks['check_runs'][2])+'\n'
            return '\n'.join('2026-10-19T10:25:41.0000000Z '+line for line in text.splitlines())
        patch.object(self.s,'named_read_gate_log',side_effect=log).start()
        def gh(path):
            if path.endswith('/pulls/777'):return self.pr
            if path.endswith('/pulls/650'):return self.origin_pr
            if any(path.endswith('/git/commits/'+ref) for ref in (o['reviewed_head'],o['source_sha'])):return self.origin_tree
            if '/commits/'+o['reviewed_head']+'/check-runs?' in path:return self.origin_checks
            if '/actions/workflows/317164841/runs?' in path:return dict(total_count=2,workflow_runs=[self.gate,self.origin_gate])
            if path.endswith('/actions/runs/302/jobs?per_page=100'):return self.origin_jobs
            return base(path)
        return gh

    def owner_comment(self):
        return dict(id=123456789,issue_url=f'https://api.github.com/repos/{c.REPO}/issues/448',
            author_association='OWNER',user=dict(type='User',id=123),
            body='A1_SIP_NAMED_READ39235028468_V3_AUTHORIZATION '+c.encoded(self.s.named_read_terms(c,self.control)).decode(),
            created_at='2026-10-20T10:40:00Z',updated_at='2026-10-20T10:40:00Z')

    def test_corrective_source_and_original_clock_are_independently_verified(self):
        gh=self.deployment_fixture()
        with patch.object(c,'gh_json',side_effect=gh):
            self.assertEqual(self.s.named_read_deployed(c,self.control),self.deployment_pins)
        self.assertEqual(self.s.named_read_window(c,self.control),('2026-10-20T09:59:28Z','2026-10-21T09:59:28Z'))
        self.assertNotEqual(self.pr['merged_at'],self.control['deployment_window']['deployed_at_utc'])

    def test_shifted_window_later_source_and_fresh_nonce_cannot_rearm(self):
        self.clock=c.utc('2026-10-22T11:00:00Z')
        with self.assertRaisesRegex(c.Refused,'CAMPAIGN_EXPIRED'):self.s.named_read_control(c,self.control)
        bad=copy.deepcopy(self.control)
        bad['deployment']['pull_request']=778;bad['nonce']=c.PREFIX+'b'*24
        bad['deployment_window']=dict(deployed_at_utc='2026-10-22T10:00:00Z',expires_at_utc='2026-10-23T10:00:00Z')
        with patch.object(drive_module,'OwnerDrive') as owner,self.assertRaisesRegex(c.Refused,'DEPLOYMENT_WINDOW'):
            self.s.named_read_worker(c,bad,str(self.root/'rearmed'))
        owner.assert_not_called()

    def test_origin_identity_has_exact_typed_fields_and_source_cannot_be650(self):
        for key,value in [('pull_request',650.0),('source_sha','a'*40),('reviewed_head','b'*40),('tree_sha','c'*40),('merged_at_utc','2026-10-20T10:30:00Z')]:
            bad=copy.deepcopy(self.control);bad['window_origin'][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(c.Refused,'DEPLOYMENT_SCOPE'):self.s.named_read_control(c,bad)
        bad=copy.deepcopy(self.control);bad['window_origin']['extra']=True
        with self.assertRaises(c.Refused):self.s.named_read_control(c,bad)
        bad=copy.deepcopy(self.control);bad['deployment']['pull_request']=650
        with self.assertRaises(c.Refused):self.s.named_read_control(c,bad)

    def test_missing_or_changed_genuine650_deployment_is_rejected(self):
        gh=self.deployment_fixture()
        mutations=[lambda:self.origin_pr.update(merged=False),lambda:self.origin_pr.update(draft=True),
            lambda:self.origin_pr.update(merged_at='2026-10-20T10:30:00Z'),
            lambda:self.origin_pr.update(merge_commit_sha='a'*40),
            lambda:self.origin_pr['head'].update(sha='b'*40),
            lambda:self.origin_tree['tree'].update(sha='c'*40)]
        for mutation in mutations:
            old_pr=copy.deepcopy(self.origin_pr);old_tree=copy.deepcopy(self.origin_tree)
            mutation()
            with self.subTest(mutation=mutation),patch.object(c,'gh_json',side_effect=gh),self.assertRaisesRegex(c.Refused,'WINDOW_ORIGIN'):
                self.s.named_read_deployed(c,self.control)
            self.origin_pr=old_pr;self.origin_tree=old_tree

    def test_both_origin_and_corrective_source_need_genuine_gate_proofs(self):
        gh=self.deployment_fixture()
        for target in (self.origin_evaluation,self.evaluation):
            old=target['passed'];target['passed']=False
            with patch.object(c,'gh_json',side_effect=gh),self.assertRaisesRegex(c.Refused,'GATE_PROVENANCE'):
                self.s.named_read_deployed(c,self.control)
            target['passed']=old
        self.origin_checks['check_runs'][0]['conclusion']='failure'
        with patch.object(c,'gh_json',side_effect=gh),self.assertRaisesRegex(c.Refused,'NAMED_READ_CHECKS'):
            self.s.named_read_deployed(c,self.control)

    def test_corrective_merge_must_be_inside_original_window(self):
        gh=self.deployment_fixture()
        for merged in (None,'2026-10-20T09:59:27Z','2026-10-21T09:59:28Z','2026-10-21T10:30:00Z'):
            self.pr['merged_at']=merged
            with self.subTest(merged=merged),patch.object(c,'gh_json',side_effect=gh),self.assertRaisesRegex(c.Refused,'DEPLOYMENT_WINDOW'):
                self.s.named_read_deployed(c,self.control)

    def test_fresh_owner_record_follows_corrective_deployment(self):
        gh=self.deployment_fixture();comment=self.owner_comment()
        def fetch(path):return comment if '/issues/comments/' in path else gh(path)
        with patch.object(c,'gh_json',side_effect=fetch):self.s.named_read_proof(c,self.control)
        for mutate in (lambda:comment.update(created_at='2026-10-20T10:29:59Z',updated_at='2026-10-20T10:29:59Z'),
                       lambda:comment.update(updated_at='2026-10-20T10:41:00Z')):
            old=copy.deepcopy(comment);mutate()
            with patch.object(c,'gh_json',side_effect=fetch),self.assertRaises(c.Refused):self.s.named_read_proof(c,self.control)
            comment=old

    def test_terms_meter_and_cost_version_do_not_substitute_v2(self):
        terms=self.s.named_read_terms(c,self.control)
        self.assertEqual(terms['schema'],'a1-named-read39235028468-grant-v3')
        self.assertEqual(terms['window_origin'],self.s.READ392_V3_ORIGIN)
        self.assertEqual(terms['expires_at_utc'],'2026-10-21T09:59:28Z')
        result,value,m,server=self.read_objects()
        self.assertEqual(value['schema'],'a1-named-read39235028468-meter-v3')
        cost=self.s.named_read_cost(c,self.control,self.run,value,self.jobs)
        self.assertEqual(cost['schema'],'a1-named-read39235028468-cost-settlement-v3')
        for schema in ('a1-named-read39235028468-meter-v1','a1-named-read39235028468-meter-v2'):
            bad=dict(value,schema=schema)
            with self.assertRaises(c.Refused):self.s.named_read_cost(c,self.control,self.run,bad,self.jobs)
        self.assertEqual(cost['usage']['provider_gets'],0);self.assertEqual(cost['usage']['storage_bytes'],0)
        self.assertEqual(cost['unknown_storage_bytes_still_charged'],[302101,434796])

    def test_new_control_fits_original_wire_limit_and_private_event_route(self):
        NamedRead39235028468Tests.test_control_fits_original_bounded_input_with_real_sized_auth(self)
        with patch.dict(os.environ,self.env,clear=True):
            self.assertEqual(c.native_read_route_control(self.control),self.a)
            self.assertEqual(c.native_read_control_from_event(),self.control)

    def test_actual_workflow_embedded_premeter_accepts_v3_without_secret_environment(self):
        NamedRead39235028468Tests.test_actual_workflow_premeter_block_reads_private_event_silently(self)

    def test_same_single_use_history_and_accounting_after_expiry_remain(self):
        NamedRead39235028468Tests.test_exclusive_context_and_actual29_prefix(self)
        result,value,m,server=self.read_objects()
        self.clock=c.utc('2026-10-22T11:00:00Z')
        with self.assertRaisesRegex(c.Refused,'CAMPAIGN_EXPIRED'):self.s.named_read_control(c,self.control)
        self.s.named_read_control(c,self.control,accounting=True)
        cost=self.s.named_read_cost(c,self.control,self.run,value,self.jobs)
        self.assertEqual(cost['dispatches_after'],30)

    def test_same_endpoint_and_failure_invariants_stay_read_only(self):
        NamedRead39235028468Tests.test_endpoint_allowlist_denies_writes_provider_arbitrary_ids_and_queries(self)
        NamedRead39235028468Tests.test_late_master_drift_in_history_or_jobs_refuses_before_secrets(self)
        NamedRead39235028468Tests.test_once_only_cost_append_and_both_durability_barriers(self)

    def test_corrective_worker_uses_new_source_and_original_window_without_provider(self):
        NamedRead392DeploymentWindowTests.test_worker_proves_only_named_history_uses_new_window_and_provider_zero(self)
        meter=c.bounded_json(self.root/'worker-v2/native_read_meter.json')
        self.assertEqual(meter['schema'],'a1-named-read39235028468-meter-v3')


class HistoricalRevisionLoaderCompatibilityTests(unittest.TestCase):
    def test_unknown_stale_auth_cannot_acquire_exact_historical_exception(self):
        value=dict(schema='r1000-sip-external-cohort-authorization-v9',code_pins={c.REVISION_MODULE:'0'*64})
        with self.assertRaisesRegex(c.Refused,'CAMPAIGN_CODE_DRIFT'):c._revision_module(value)
        value['claimed_auth_sha256']='2a1339c50cad5971d4ea06d9a01d430e9ea28a5f22a1c6b031b79e6aab52a02e'
        with self.assertRaisesRegex(c.Refused,'CAMPAIGN_CODE_DRIFT'):c._revision_module(value)

    def test_current_pin_loader_still_does_not_validate_authorization_shape(self):
        value=dict(schema='r1000-sip-external-cohort-authorization-v9',code_pins={c.REVISION_MODULE:
            c.digest(c.bounded_bytes(c.ROOT/c.REVISION_MODULE,262144).replace(b'\r\n',b'\n'))})
        self.assertIs(c._revision_module(value),c._revision_module())
        with self.assertRaises(c.Refused):c.validate_authorization(value)


class GateLogPRTransportProbeTests(unittest.TestCase):
    def _execute_probe(self, body=b'fixture trusted log', error=b'', returncode=0, timeout=False, supports_flag=True):
        import contextlib, subprocess
        from tools import alpaca_sip_source_revision as revision
        calls=[]
        def fake_run(args,**kwargs):
            if args==['gh','api','--help']:
                self.assertEqual(kwargs['timeout'],10)
                kwargs['stdout'].write(b'Usage: gh api'+(b' --allow-escape-sequences' if supports_flag else b''))
                return SimpleNamespace(returncode=0)
            calls.append(args)
            self.assertEqual(kwargs['timeout'],45)
            self.assertIsNotNone(kwargs['stdout'])
            self.assertNotEqual(kwargs['stdout'],subprocess.PIPE)
            self.assertNotEqual(kwargs['stderr'],subprocess.PIPE)
            kwargs['stdout'].write(body)
            kwargs['stderr'].write(error)
            if timeout:raise subprocess.TimeoutExpired(args,45)
            return SimpleNamespace(returncode=returncode)
        output=io.StringIO()
        with patch('subprocess.run',side_effect=fake_run),contextlib.redirect_stdout(output):
            responses=[revision.named_read_gate_transport(c,i) for i in (501,502)]
        rows=[row for raw,row in responses]
        self.assertTrue(all(raw==(body if row['reason']=='OK' else b'') for raw,row in responses))
        self.assertEqual(output.getvalue(),'')
        self.assertEqual(calls,[['gh','api']+(['--allow-escape-sequences'] if supports_flag else [])+[
                                    'repos/wscha231/r1000-quant-engine/actions/jobs/'+str(i)+'/logs']
                                for i in (501,502)])
        self.assertEqual(len(rows),2)
        for row in rows:
            self.assertFalse(row['raw_or_headers_emitted'])
            self.assertIsNone(row['hard_capture_byte_limit'])
        return rows,any(row['reason']!='OK' for row in rows),json.dumps(rows)

    def test_pr_validation_has_no_read_token_or_expiring_log_dependency(self):
        workflow=(c.ROOT/'.github/workflows/alpaca_sip_private_backfill_v1.yml').read_text(encoding='utf-8')
        paths=workflow.split('  pull_request:\n',1)[1].split('  workflow_dispatch:',1)[0]
        self.assertIn("'tools/alpaca_sip_source_revision.py'",paths)
        offline=workflow.split('  offline:\n',1)[1].split('  capture:',1)[0]
        for forbidden in ('GH_TOKEN','GITHUB_TOKEN','secrets.','118566905053','119037766237','gh api'):
            self.assertNotIn(forbidden,offline)
        self.assertIn('persist-credentials: false',offline)
        self.assertIn('python -O -m unittest discover -s tests -p alpaca_sip_private_backfill_v1_smoke.py',offline)
        loader=(c.ROOT/'tests/alpaca_sip_private_backfill_v1_smoke.py').read_text(encoding='utf-8').split('def load_tests(',1)[1]
        self.assertIn("with_name('alpaca_sip_campaign_smoke.py')",loader)

    def test_history_implementation_is_in_always_authenticated_controller(self):
        import inspect
        self.assertIn('tools/alpaca_sip_campaign.py',c.PINS)
        self.assertEqual(c.campaign_run_pages.__module__,c.__name__)
        self.assertNotIn('alpaca_sip_source_revision',inspect.getsource(c.campaign_runs))

    def test_success_reports_hashes_without_log_body(self):
        body=b'SOURCE_LOG_PRIVATE_BODY_CANARY'
        rows,failed,printed=self._execute_probe(body)
        self.assertFalse(failed)
        self.assertNotIn(body.decode(),printed)
        self.assertTrue(all(r['reason']=='OK' and r['stdout_prefix_sha256']==c.digest(body) for r in rows))

    def test_error_classifies_http_without_tokens_headers_or_redirect_urls(self):
        error=b'gh: Resource not accessible by integration (HTTP 403) TOKEN_PRIVATE_CANARY Location: https://private.invalid/sas-secret'
        rows,failed,printed=self._execute_probe(b'PRIVATE_RESPONSE_CANARY',error,1)
        self.assertTrue(failed)
        self.assertTrue(all(r['http_status']==403 and r['reason']=='INTEGRATION_FORBIDDEN' for r in rows))
        for value in ('TOKEN_PRIVATE_CANARY','Location:','private.invalid','sas-secret','PRIVATE_RESPONSE_CANARY'):
            self.assertNotIn(value,printed)

    def test_body_size_encoding_timeout_and_rate_limit_remain_distinct_failures(self):
        for body,error,code,timeout,expected in (
                (b'x'*2000002,b'',0,False,'BODY_TOO_LARGE'),
                (b'\xffPRIVATE_BINARY_CANARY',b'',0,False,'UTF8'),
                (b'',b'',0,True,'TIMEOUT'),
                (b'valid',b'x'*8193,0,False,'STDERR_TOO_LARGE'),
                (b'',b'gh: API rate limit exceeded (HTTP 403)',1,False,'RATE_LIMIT')):
            with self.subTest(expected=expected):
                rows,failed,printed=self._execute_probe(body,error,code,timeout)
                self.assertTrue(failed)
                self.assertTrue(all(r['reason']==expected for r in rows))
                self.assertNotIn('PRIVATE_BINARY_CANARY',printed)

    def test_old_cli_never_receives_unsupported_flag_or_retries_get(self):
        rows,failed,_=self._execute_probe(supports_flag=False)
        self.assertFalse(failed)
        self.assertTrue(all(not row['escape_flag'] for row in rows))

    def test_original_ansi_bom_and_utf8_bytes_are_preserved(self):
        from tools import alpaca_sip_source_revision as revision
        body=b'\xef\xbb\xbf\x1b[36m'+ '\uac80\uc99d'.encode()+b'\x1b[0m\r\n'
        calls=[]
        def run(argv,**kw):
            self.assertNotEqual(kw['stdout'],c.subprocess.PIPE)
            self.assertIsNotNone(kw['stdout'])
            if argv==['gh','api','--help']:
                kw['stdout'].write(b'--allow-escape-sequences')
            else:
                calls.append(argv)
                self.assertEqual(argv,['gh','api','--allow-escape-sequences',f'repos/{c.REPO}/actions/jobs/501/logs'])
                kw['stdout'].write(body)
            return SimpleNamespace(returncode=0)
        with patch.object(c.subprocess,'run',side_effect=run):
            self.assertEqual(revision.named_read_gate_log(c,501).encode('utf-8'),body)
        self.assertEqual(len(calls),1)

    def test_help_errors_or_oversize_stop_before_network_without_raw_error(self):
        from tools import alpaca_sip_source_revision as revision
        for outcome in ('failed','oversize','timeout','exception'):
            def run(argv,**kw):
                self.assertEqual(argv,['gh','api','--help'])
                if outcome=='timeout':raise c.subprocess.TimeoutExpired(argv,10)
                if outcome=='exception':raise OSError('PRIVATE_HELP_CANARY')
                kw['stdout'].write(b'--allow-escape-sequences'+(b'x'*65537 if outcome=='oversize' else b''))
                return SimpleNamespace(returncode=1 if outcome=='failed' else 0)
            with self.subTest(outcome=outcome),patch.object(c.subprocess,'run',side_effect=run) as called:
                with self.assertRaisesRegex(c.Refused,'^NAMED_READ_GATE_LOG_CLI_HELP$') as error:
                    revision.named_read_gate_log(c,501)
                self.assertEqual(called.call_count,1)
                self.assertNotIn('PRIVATE_HELP_CANARY',str(error.exception))


if __name__=='__main__': unittest.main()

"""Offline resume/partition/budget counterexamples; no fixture is provider evidence."""
import copy
import json
import sys
import os
import subprocess
import io
import gzip
import zipfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import twelve_private_capture as m
from tools import twelve_private_cohort as c

FOLDERS = {x: x for x in ('00-control', '01-provider-raw', '02-normalized',
                         '06-receipts', '05-checkpoints')}
ACCOUNT = dict(plan_category='basic', current_usage=0, plan_limit=8,
               daily_usage=0, plan_daily_limit=800)


class Drive:
    def __init__(self):
        self.objects, self.parents = {}, {}
        self.free = 100_000_000

    def write(self, folder, raw, extension):
        key = 'fixture-file-%06d' % len(self.objects)
        self.objects[key], self.parents[key] = raw, folder
        self.free -= len(raw)
        return dict(file_id=key, sha256=m.digest(raw), bytes=len(raw))

    def check(self, key, parent=None, folder=False):
        m.require(key in self.objects and self.parents[key] == parent, 'DRIVE_PARENT')

    def read(self, key, limit=m.MAX_PACK):
        raw = self.objects[key]
        m.require(len(raw) <= limit, 'RESPONSE_SIZE')
        return raw


def provider(endpoint, query, key):
    if endpoint == '/api_usage':
        return m.encoded(ACCOUNT), copy.deepcopy(ACCOUNT)
    data = dict(meta=dict(symbol=query['symbol'], mic_code=query['mic_code'], currency='USD',
                          interval='1day'), values=[dict(datetime='2026-10-09', open='10',
                          high='12', low='9', close='11', volume='8')])
    return m.encoded(data), data


def fixture(drive):
    pilot = m.capture(drive, FOLDERS, 'offline-credential-canary', {'sha256': 'a'*64},
                      provider, lambda _: None)
    initial = {k: pilot['receipt'][k] for k in ('file_id', 'sha256')}
    pairs = list(m.SYMBOLS) + [('TEST%02d' % i, 'XNGS') for i in range(12)]
    value = dict(schema='twelve-private-collection-scope-v1',
                 window=dict(start=m.START, end_exclusive=m.END, interval='1day',
                             adjustments=['none', 'splits']),
                 requested_targets=[dict(symbol=s) for s, _ in pairs],
                 instruments=[dict(symbol=s, mic=mic, currency='USD',
                                   provider_reported_type='Common Stock',
                                   provider_reported_figi='BBG000000001') for s, mic in pairs],
                 unresolved=[], identity_snapshot=dict(authority='CURRENT_VENDOR_REPORTED_INSTRUMENT_ONLY',
                 sha256='f'*64, source_url='https://api.twelvedata.com/stocks?country=United%20States'),
                 initial_receipt=initial, historical_index_membership_verified=False,
                 **{f: False for f in c.FLAGS})
    ref = drive.write(FOLDERS['00-control'], m.encoded(value), '.json')
    ref = {k: ref[k] for k in ('file_id', 'sha256')}
    return initial, value, ref


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.drive = Drive()
        self.initial, self.value, self.ref = fixture(self.drive)
        self.patch = patch.object(c, 'INITIAL', self.initial)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.calls, self.progress = [], []

    def capture(self, *args, **kwargs):
        self.calls.extend(kwargs['symbols'])
        return m.capture(*args, provider=provider, pause=lambda _: None, **kwargs)

    def collect(self, maximum=5, resume=None, usage=provider):
        return c.collect(self.drive, FOLDERS, 'offline-credential-canary', {'sha256':'a'*64},
                         ACCOUNT, self.ref, resume, maximum, provider=usage,
                         capture=self.capture, progress=self.progress.append)

    def test_resume_restores_prior_bytes_and_never_recollects_completed(self):
        first = self.collect()
        self.assertEqual(first['new_symbols'], 5)
        self.assertEqual(first['total_completed_symbols'], 9)
        previous = set(self.calls)
        self.calls.clear()
        second = self.collect(4, first['checkpoint'])
        self.assertEqual(second['new_symbols'], 4)
        self.assertFalse(previous & set(self.calls))
        self.assertFalse(set(m.SYMBOLS) & set(self.calls))
        state = json.loads(self.drive.read(second['checkpoint']['file_id']))
        self.assertEqual(len(state['completed']), 13)
        for flag in c.FLAGS:
            self.assertIs(state[flag], False)
        self.assertNotIn('offline-credential-canary', json.dumps(self.progress))

    def test_known_bad_generation_stops_each_subject_before_resume_provider_and_write(self):
        bad_sha = '3950bf63d87e280d62fc5ea9fb35f2e76643db669961658ebd5db4cea2ca86b5'
        self.assertEqual(c.BAD_IDENTITY_SCOPE_SHA, bad_sha)
        # The immutable generation is refused even if a caller renames a subject.
        for symbol in ('A', 'KKR', 'HBAN', 'MTB', 'S', 'TEST00'):
            for resume in (None, {'file_id': 'fixture-resume', 'sha256': 'e' * 64}):
                ref = dict(self.ref, sha256=bad_sha)
                instrument = dict(symbol=symbol, mic='XNYS')
                original = copy.deepcopy((ref, instrument, self.drive.objects,
                                          self.drive.parents, self.drive.free))
                fetch, capture = Mock(), Mock()
                with self.subTest(symbol=symbol, resume=resume is not None), \
                        patch.object(c, 'read', return_value=self.value) as read_scope, \
                        patch.object(c, 'scope', return_value=[instrument]) as parse_scope, \
                        patch.object(c, 'verify_initial') as initial, \
                        patch.object(c, 'resume_completed') as restored, \
                        patch.object(self.drive, 'write', wraps=self.drive.write) as write:
                    with self.assertRaisesRegex(m.Refused, '^CURRENT_IDENTITY_MISMATCH$'):
                        c.collect(self.drive, FOLDERS, 'offline-credential-canary', {}, ACCOUNT,
                                  ref, resume, 1, provider=fetch, capture=capture,
                                  progress=self.progress.append)
                    read_scope.assert_called_once_with(self.drive, ref, FOLDERS['00-control'])
                    parse_scope.assert_called_once_with(self.value)
                    initial.assert_not_called()
                    restored.assert_not_called()
                    fetch.assert_not_called()
                    capture.assert_not_called()
                    write.assert_not_called()
                self.assertEqual((ref, instrument, self.drive.objects,
                                  self.drive.parents, self.drive.free), original)
                self.assertEqual(self.progress, [])

    def test_different_generation_does_not_bypass_existing_identity_checks(self):
        value = copy.deepcopy(self.value)
        value['instruments'][0]['currency'] = 'TWD'
        ref = self.drive.write(FOLDERS['00-control'], m.encoded(value), '.json')
        self.assertNotEqual(ref['sha256'], c.BAD_IDENTITY_SCOPE_SHA)
        fetch, capture = Mock(), Mock()
        before = copy.deepcopy((self.drive.objects, self.drive.parents, self.drive.free))
        with patch.object(self.drive, 'write', wraps=self.drive.write) as write:
            with self.assertRaisesRegex(m.Refused, '^CURRENT_IDENTITY_MISMATCH$'):
                c.collect(self.drive, FOLDERS, 'offline-credential-canary', {}, ACCOUNT,
                          ref, None, 1, provider=fetch, capture=capture,
                          progress=self.progress.append)
            write.assert_not_called()
        fetch.assert_not_called()
        capture.assert_not_called()
        self.assertEqual((self.drive.objects, self.drive.parents, self.drive.free), before)
        self.assertEqual(self.progress, [])

    def test_actual_run_refuses_bad_scope_before_account_or_drive_preflight(self):
        ref = dict(self.ref, sha256=c.BAD_IDENTITY_SCOPE_SHA)
        env = dict(A1_PRIVATE_RESEARCH_AUTHORIZED='true', TWELVE_KEY_NAME='TWELVE_API_KEY',
                   TWELVE_API_KEY='offline-credential-canary')
        with patch.dict(os.environ, env, clear=True), \
                patch.object(m, 'twelve') as fetch, \
                patch.object(m, 'OwnerDrive') as drive, \
                patch.object(c, 'collect') as collect:
            with self.assertRaisesRegex(m.Refused, '^CURRENT_IDENTITY_MISMATCH$'):
                m.run(True, ref)
            fetch.assert_not_called()
            drive.assert_not_called()
            collect.assert_not_called()

    def test_real_cli_quarantines_bad_scope_without_credentials_or_network(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/twelve_private_capture.py'),
            '--capture-history', '--cohort-file-id', 'fixture-scope-123',
            '--cohort-sha256', c.BAD_IDENTITY_SCOPE_SHA],
            env={'PATH': os.environ.get('PATH', ''), 'A1_PRIVATE_RESEARCH_AUTHORIZED': 'true'},
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['reason'], 'CURRENT_IDENTITY_MISMATCH')
        self.assertEqual(result.stderr, '')

    def test_scope_must_partition_targets_and_preserve_unknowns(self):
        for mutation in ('duplicate', 'missing', 'identity', 'pit'):
            value = copy.deepcopy(self.value)
            if mutation == 'duplicate': value['instruments'].append(value['instruments'][0])
            if mutation == 'missing': value['instruments'].pop()
            if mutation == 'identity': value['instruments'][0]['currency'] = 'TWD'
            if mutation == 'pit': value['pit_verified'] = True
            with self.subTest(mutation=mutation), self.assertRaises(m.Refused): c.scope(value)
        value = copy.deepcopy(self.value)
        row = value['instruments'].pop()
        value['unresolved'].append(dict(symbol=row['symbol'], reason='UNKNOWN'))
        self.assertEqual(len(c.scope(value)), len(value['requested_targets']) - 1)

    def test_checkpoint_scope_hash_duplicate_and_unreceipted_completion_are_refused(self):
        out = self.collect(4)
        state = json.loads(self.drive.read(out['checkpoint']['file_id']))
        for mutation in ('scope', 'duplicate', 'foreign_symbol'):
            x = copy.deepcopy(state)
            if mutation == 'scope': x['collection_scope']['sha256'] = 'f'*64
            if mutation == 'duplicate': x['completed'].append(x['completed'][0])
            if mutation == 'foreign_symbol': x['completed'][0]['symbol'] = 'OTHER'
            ref = self.drive.write(FOLDERS['05-checkpoints'], m.encoded(x), '.json')
            with self.subTest(mutation=mutation), self.assertRaises(m.Refused): self.collect(4, ref)

    def test_raw_tampering_blocks_resume_before_new_provider_capture(self):
        out = self.collect(4)
        receipt = json.loads(self.drive.read(self.initial['file_id']))
        self.drive.objects[receipt['raw_object']['file_id']] = b'corrupted'
        self.calls.clear()
        with self.assertRaisesRegex(m.Refused, 'MEMBER_HASH'): self.collect(4, out['checkpoint'])
        self.assertEqual(self.calls, [])

    def test_new_scoped_pilot_receipt_cannot_replace_the_pinned_initial_anchor(self):
        out = self.collect(4)
        state = json.loads(self.drive.read(out['checkpoint']['file_id']))
        replacement = m.capture(self.drive, FOLDERS, 'offline-credential-canary', {'sha256':'a'*64},
                                provider, lambda _: None, collection_scope=self.ref)
        for row in state['completed']:
            if (row['symbol'], row['mic']) in set(m.SYMBOLS): row['receipt'] = replacement['receipt']
        ref = self.drive.write(FOLDERS['05-checkpoints'], m.encoded(state), '.json')
        self.calls.clear()
        with self.assertRaisesRegex(m.Refused, 'SOURCE_FIELDS'): self.collect(4, ref)
        self.assertEqual(self.calls, [])

    def test_restore_rejects_rebound_raw_split_session_mismatch(self):
        value = json.loads(self.drive.read(self.initial['file_id']))
        members, normalized = {}, []
        with zipfile.ZipFile(io.BytesIO(self.drive.read(value['raw_object']['file_id']))) as old:
            for e in value['evidence']:
                data = json.loads(old.read(e['member']))
                if e['adjustment'] == 'splits': data['values'][0]['datetime'] = '2026-10-08'
                raw = m.encoded(data)
                e['sha256'], e['bytes'] = m.digest(raw), len(raw)
                e['member'] = e['sha256'] + '.json'
                e['first'] = e['last'] = data['values'][0]['datetime']
                members[e['member']] = raw
                normalized.extend(m.rows(data, e['symbol'], e['mic'], e['adjustment']))
        members['capture.json'] = m.encoded(dict(evidence=value['evidence'], rights_sha256='a'*64))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as pack:
            for name, raw in members.items(): pack.writestr(name, raw)
        value['raw_object'] = self.drive.write(FOLDERS['01-provider-raw'], stream.getvalue(), '.zip')
        value['normalized_object'] = self.drive.write(FOLDERS['02-normalized'],
             gzip.compress(b''.join(m.encoded(r) for r in normalized), mtime=0), '.jsonl.gz')
        with self.assertRaisesRegex(m.Refused, 'RAW_SPLIT_SESSION_MISMATCH'):
            c.restore_receipt(self.drive, FOLDERS, value)

    def test_daily_reserve_stops_before_fetch_and_preserves_completed_checkpoint(self):
        usages = iter([dict(ACCOUNT, daily_usage=711), dict(ACCOUNT, daily_usage=719)])
        def usage(endpoint, query, key):
            d = next(usages)
            return m.encoded(d), d
        out = self.collect(8, usage=usage)
        self.assertEqual(out['new_symbols'], 4)
        self.assertEqual(out['stop_reason'], 'DAILY_BUDGET')
        self.assertEqual(len(self.progress), 1)
        self.assertIsNotNone(out['checkpoint'])

    def bad_first_group(self, *args, **kwargs):
        self.calls.extend(kwargs['symbols'])
        def data(endpoint, query, key):
            raw, value = provider(endpoint, query, key)
            if query.get('symbol') == 'TEST00':
                value['values'][0]['low'] = '0'
                raw = m.encoded(value)
            return raw, value
        return m.capture(*args, provider=data, pause=lambda _: None, **kwargs)

    def test_invalid_fresh_group_is_unretained_and_later_groups_resume_without_retry(self):
        with patch.object(self, 'capture', self.bad_first_group):
            first = self.collect(8)
        self.assertEqual(first['new_symbols'], 4)
        self.assertEqual(first['total_completed_symbols'], 8)
        self.assertEqual(first['quarantined_symbols'], 4)
        self.assertEqual(first['pending_symbols'], 4)
        self.assertEqual(first['quality_status'], 'PARTIAL_WITH_HELD_GROUPS')
        self.assertEqual(first['retained_provider_raw_objects'], 1)
        self.assertEqual([p['status'] for p in self.progress],
                         ['COHORT_GROUP_QUARANTINED', 'COHORT_GROUP_CAPTURE_RESTORED'])
        held_state = json.loads(self.drive.read(self.progress[0]['checkpoint']['file_id']))
        self.assertEqual(len(held_state['completed']), 4)
        group = held_state['quarantined_groups'][0]
        self.assertFalse(group['individual_invalidity_verified'])
        self.assertFalse(group['original_body_retained'])
        self.assertNotIn('offline-credential-canary', json.dumps(held_state))
        self.assertEqual(sum(p == FOLDERS['01-provider-raw'] for p in self.drive.parents.values()), 2)
        attempted = set(self.calls)
        self.calls.clear()
        second = self.collect(4, first['checkpoint'])
        self.assertEqual(second['new_symbols'], 4)
        self.assertEqual(second['pending_symbols'], 0)
        self.assertEqual(second['remaining_symbols'], 4)
        self.assertEqual(second['quarantined_symbols'], 4)
        self.assertFalse(attempted & set(self.calls))

    def test_hold_only_checkpoint_and_daily_reserve_remain_durable(self):
        usages = iter([dict(ACCOUNT, daily_usage=700), dict(ACCOUNT, daily_usage=719)])
        def usage(*args):
            value = next(usages)
            return m.encoded(value), value
        with patch.object(self, 'capture', self.bad_first_group):
            out = self.collect(8, usage=usage)
        self.assertEqual(out['new_symbols'], 0)
        self.assertEqual(out['retained_provider_raw_objects'], 0)
        self.assertEqual(out['quarantined_symbols'], 4)
        self.assertEqual(out['stop_reason'], 'DAILY_BUDGET')
        self.assertIsNotNone(out['checkpoint'])
        self.calls.clear()
        resumed = self.collect(4, out['checkpoint'])
        self.assertEqual(resumed['new_symbols'], 4)
        self.assertNotIn(('TEST00', 'XNGS'), self.calls)

    def test_non_numeric_refusal_and_checkpoint_upload_failure_are_terminal(self):
        for reason in ('RATE_LIMIT', 'AUTH', 'NETWORK', 'CREDENTIAL_ECHO', 'MEMBER_HASH',
                       'CURRENT_IDENTITY_MISMATCH', 'RAW_SPLIT_SESSION_MISMATCH'):
            before = len(self.drive.objects)
            with self.subTest(reason=reason), patch.object(self, 'capture', side_effect=m.Refused(reason)):
                with self.assertRaisesRegex(m.Refused, reason): self.collect(8)
            self.assertEqual(len(self.drive.objects), before)
            self.assertEqual(self.progress, [])
        original_write = self.drive.write
        def write(folder, *args):
            if folder == FOLDERS['05-checkpoints']: raise m.Refused('NETWORK')
            return original_write(folder, *args)
        with patch.object(self, 'capture', self.bad_first_group), patch.object(self.drive, 'write', write):
            with self.assertRaisesRegex(m.Refused, 'NETWORK'): self.collect(8)
        self.assertEqual(self.progress, [])

    def test_rebound_quarantine_metadata_cannot_suppress_foreign_or_completed_symbols(self):
        with patch.object(self, 'capture', self.bad_first_group): out = self.collect(4)
        state = json.loads(self.drive.read(out['checkpoint']['file_id']))
        for mutation in ('duplicate', 'foreign', 'completed', 'flag', 'reason', 'body', 'v1', 'missing'):
            value = copy.deepcopy(state)
            group = value['quarantined_groups'][0]
            if mutation == 'duplicate': value['quarantined_groups'].append(copy.deepcopy(group))
            if mutation == 'foreign': group['instruments'][0]['symbol'] = 'OTHER'
            if mutation == 'completed': group['instruments'][0] = dict(symbol='AAPL', mic='XNGS')
            if mutation == 'flag': group['source_admission'] = True
            if mutation == 'reason': group['reason'] = 'NETWORK'
            if mutation == 'body': group['raw'] = 'untrusted-body-canary'
            if mutation == 'v1': value['schema'] = 'twelve-private-cohort-checkpoint-v1'
            if mutation == 'missing': value.pop('quarantined_groups')
            ref = self.drive.write(FOLDERS['05-checkpoints'], m.encoded(value), '.json')
            self.calls.clear()
            with self.subTest(mutation=mutation), self.assertRaises(m.Refused): self.collect(4, ref)
            self.assertEqual(self.calls, [])

    def test_v1_checkpoint_remains_compatible_and_resume_bar_refusal_is_terminal(self):
        out = self.collect(4)
        state = json.loads(self.drive.read(out['checkpoint']['file_id']))
        state['schema'] = 'twelve-private-cohort-checkpoint-v1'
        state.pop('quarantined_groups')
        ref = self.drive.write(FOLDERS['05-checkpoints'], m.encoded(state), '.json')
        self.assertEqual(self.collect(4, ref)['new_symbols'], 4)
        self.calls.clear()
        before = len(self.progress)
        with patch.object(c, 'restore_receipt', side_effect=m.Refused('BAR_VALUE')):
            with self.assertRaisesRegex(m.Refused, 'BAR_VALUE'): self.collect(4, ref)
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.progress), before)

    def test_credential_or_rate_error_never_falls_back_and_keeps_previous_progress(self):
        calls = []
        def usage(endpoint, query, key):
            calls.append(key)
            if len(calls) == 2: raise m.Refused('RATE_LIMIT')
            return provider(endpoint, query, key)
        with self.assertRaisesRegex(m.Refused, 'RATE_LIMIT'): self.collect(8, usage=usage)
        self.assertEqual(calls, ['offline-credential-canary'] * 2)
        self.assertEqual(len(self.progress), 1)
        state = json.loads(self.drive.read(self.progress[0]['checkpoint']['file_id']))
        self.assertEqual(len(state['completed']), 8)

    def test_invalid_scope_reference_and_batch_limit_refuse(self):
        for file_id, sha in [('', 'f'*64), ('private-file-123', ''), ('invalid/url', 'f'*64)]:
            with self.assertRaises(m.Refused): c.reference(file_id, sha)
        for maximum in (0, 361, True):
            with self.assertRaises(m.Refused): self.collect(maximum)

    def test_real_cli_keeps_worker_refusal_class_and_does_not_need_credentials(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/twelve_private_capture.py')],
                                env={'PATH': os.environ.get('PATH', '')}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['reason'], 'USER_AUTHORIZATION_MISSING')
        self.assertEqual(result.stderr, '')

    def test_workflow_checkout_and_inputs_include_resume_worker_before_credentials(self):
        # The live sparse runner is stdlib-only; loaded YAML checks remain in
        # the registered private-capture suite where PyYAML is already installed.
        raw = (ROOT / '.github/workflows/twelve_private_capture.yml').read_text()
        self.assertIn('/tools/twelve_private_cohort.py', raw)
        self.assertIn('python3 tests/twelve_private_cohort_smoke.py', raw)
        self.assertIn('COHORT_FILE_ID: ${{ inputs.cohort_file_id }}', raw)
        self.assertIn('RESUME_SHA256: ${{ inputs.resume_sha256 }}', raw)
        self.assertLess(raw.index('Offline contract checks before credentials'), raw.index('TWELVE_KEY_NAME:'))
        self.assertNotIn('upload-artifact', raw)


if __name__ == '__main__':
    unittest.main()

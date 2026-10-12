"""Private account/storage/capture boundaries; offline fixtures are not live proof."""
import copy
import io
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
import zipfile
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import twelve_private_capture as m


def bar(symbol='AAPL', mic='XNGS', day='2026-10-09'):
    return dict(meta=dict(symbol=symbol, mic_code=mic, currency='USD', interval='1day'),
                values=[dict(datetime=day, open='10', high='12', low='9', close='11', volume='8')])


class Drive:
    def __init__(self):
        self.objects = {}
        self.calls = []

    def write(self, folder, raw, extension):
        key = 'file-' + str(len(self.objects))
        self.objects[key] = raw
        self.calls.append(folder)
        return dict(file_id=key, sha256=m.digest(raw), bytes=len(raw))

    def read(self, key):
        return self.objects[key]


FOLDERS = {x: x for x in ('01-provider-raw', '02-normalized', '06-receipts', '05-checkpoints')}


class PrivateCaptureTests(unittest.TestCase):
    def test_workflow_is_manual_master_only_no_public_price_output(self):
        # The actual YAML is parsed by the registered credentials suite (PyYAML).
        raw = (ROOT / '.github/workflows/twelve_private_capture.yml').read_text()
        self.assertIn("github.ref == 'refs/heads/master'", raw)
        self.assertIn('persist-credentials: false', raw)
        self.assertIn('cancel-in-progress: false', raw)
        self.assertIn('private_research_authorized:', raw)
        for forbidden in ('upload-artifact', 'schedule:', 'pull_request:', 'GITHUB_STEP_SUMMARY', 'continue-on-error'):
            self.assertNotIn(forbidden, raw)

    def test_user_authorization_refuses_before_credentials_or_network(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(m, 'twelve', side_effect=AssertionError):
            with self.assertRaisesRegex(m.Refused, 'USER_AUTHORIZATION_MISSING'):
                m.run(True)

    def test_selected_secret_missing_never_rotates(self):
        for selected, other in [('TWELVE_API_KEY', 'TWELVE_API_KEY2'), ('TWELVE_API_KEY2', 'TWELVE_API_KEY')]:
            env = dict(A1_PRIVATE_RESEARCH_AUTHORIZED='true', TWELVE_KEY_NAME=selected)
            env[other] = 'unselected-credential'
            with patch.dict(os.environ, env, clear=True), patch.object(m, 'twelve', side_effect=AssertionError):
                with self.assertRaisesRegex(m.Refused, 'SELECTED_SECRET_MISSING'):
                    m.run(True)

    def test_account_usage_requires_known_individual_plan_and_real_integer_quota(self):
        sample = dict(plan_category='basic', current_usage=1, plan_limit=8, daily_usage=10, plan_daily_limit=800)
        self.assertEqual(m.usage(sample)['plan'], 'Basic')
        self.assertEqual(m.usage(dict(sample, plan_category='individual'))['plan'], 'Basic')
        for changed in [dict(plan_category='Unknown'), dict(plan_category='Business'), dict(plan_limit=True),
                        dict(current_usage=-1), dict(daily_usage=795), dict(plan_daily_limit=None),
                        dict(plan_limit=55)]:
            with self.subTest(changed=changed), self.assertRaises(m.Refused):
                m.usage(dict(sample, **changed))

    def test_current_identity_strictly_matches_instrument(self):
        self.assertEqual(len(m.rows(bar(), 'AAPL', 'XNGS', 'none')), 1)
        for field, value in [('symbol', 'TSM'), ('mic_code', 'XNAS'), ('currency', 'TWD'), ('interval', '1min')]:
            data = bar()
            data['meta'][field] = value
            with self.assertRaises(m.Refused):
                m.rows(data, 'AAPL', 'XNGS', 'none')

    def test_dates_and_values_refuse_duplicates_weekends_nonfinite_and_bool(self):
        invalid = []
        d = bar(); d['values'] *= 2; invalid.append(d)
        for day in ['2026-10-10', '2015-10-09', '2026-09-31']:
            invalid.append(bar(day=day))
        for field, value in [('open', True), ('high', 'NaN'), ('low', '13'), ('volume', '0.5')]:
            d = bar(); d['values'][0][field] = value; invalid.append(d)
        for d in invalid:
            with self.assertRaises(m.Refused):
                m.rows(d, 'AAPL', 'XNGS', 'none')

    def test_unexpected_source_fields_cannot_archive_credentials_or_vendor_text(self):
        for location in ('top', 'meta', 'row'):
            data = bar()
            target = data if location == 'top' else data['meta'] if location == 'meta' else data['values'][0]
            target['access_token'] = 'different-private-credential'
            with self.assertRaisesRegex(m.Refused, 'SOURCE_FIELDS'):
                m.rows(data, 'AAPL', 'XNGS', 'none')

    def test_terminal_quota_saves_no_raw_or_success_receipt(self):
        drive = Drive()
        calls = []
        def provider(endpoint, query, key):
            calls.append(query['symbol'])
            raise m.Refused('RATE_LIMIT')
        with self.assertRaisesRegex(m.Refused, 'RATE_LIMIT'):
            m.capture(drive, FOLDERS, 'credential-canary', {'sha256': 'a'*64}, provider, lambda _: None)
        self.assertEqual(calls, ['AAPL'])
        self.assertEqual(drive.calls, [])

    def test_credential_echo_and_basis_session_mismatch_save_nothing(self):
        for echo in (True, False):
            drive = Drive()
            def provider(endpoint, query, key):
                d = bar(query['symbol'], query['mic_code'],
                        '2026-10-08' if query['adjust'] == 'splits' else '2026-10-09')
                return key.encode() if echo else m.encoded(d), d
            with self.assertRaises(m.Refused):
                m.capture(drive, FOLDERS, 'credential-canary', {'sha256': 'a'*64}, provider, lambda _: None)
            self.assertEqual(drive.calls, [])

    def test_actual_archive_restore_binds_raw_members_and_receipt(self):
        drive, queries, pauses = Drive(), [], []
        def provider(endpoint, query, key):
            queries.append((endpoint, copy.deepcopy(query), key))
            data = bar(query['symbol'], query['mic_code'])
            return m.encoded(data), data
        out = m.capture(drive, FOLDERS, 'credential-canary', {'sha256': 'a'*64}, provider, pauses.append)
        self.assertEqual(len(queries), 8)
        self.assertEqual(pauses, [10]*8)
        self.assertEqual({q[1]['adjust'] for q in queries}, {'none', 'splits'})
        self.assertTrue(all(q[1]['outputsize'] == 5000 and q[1]['end_date'] == '2026-10-10'
                            and q[1]['order'] == 'asc' for q in queries))
        self.assertEqual(out['rows'], 8)
        receipt = json.loads(drive.read(out['receipt']['file_id']))
        self.assertTrue(receipt['restored_from_drive'])
        for flag in ('historical_identity_verified', 'pit_verified', 'source_admission',
                     'immutable_reader_e2e', 'economic_authority'):
            self.assertIs(receipt[flag], False)
        self.assertNotIn('credential-canary', json.dumps(receipt))
        checkpoint = json.loads(drive.read(out['checkpoint']['file_id']))
        self.assertEqual(checkpoint['receipt'], out['receipt'])
        self.assertIs(checkpoint['bulk_enabled'], False)

    def test_unicode_escaped_credential_in_json_keys_or_values_is_refused(self):
        key = 'credential-canary'
        escaped = ''.join('\\u%04x' % ord(char) for char in key)
        for data in ({'meta': {'type': key}}, {key: 'value'}, {'nested': [key]}):
            raw = json.dumps(data).replace(key, escaped).encode()
            self.assertNotIn(key.encode(), raw)
            with self.assertRaisesRegex(m.Refused, 'CREDENTIAL_ECHO'):
                m.credential_safe_json(raw, (key,))
        drive = Drive()
        def provider(endpoint, query, selected):
            data = bar(query['symbol'], query['mic_code'])
            data['meta']['type'] = selected
            raw = json.dumps(data).replace(selected, escaped).encode()
            return raw, data
        with self.assertRaisesRegex(m.Refused, 'CREDENTIAL_ECHO'):
            m.capture(drive, FOLDERS, key, {'sha256': 'a'*64}, provider, lambda _: None)
        self.assertEqual(drive.calls, [])

    def test_valid_zip_with_changed_capture_metadata_blocks_success(self):
        class ChangedDrive(Drive):
            def read(self, key):
                raw = super().read(key)
                changed = io.BytesIO()
                with zipfile.ZipFile(io.BytesIO(raw)) as old, \
                        zipfile.ZipFile(changed, 'w', zipfile.ZIP_DEFLATED) as new:
                    for name in old.namelist():
                        member = old.read(name)
                        if name == 'capture.json':
                            data = json.loads(member)
                            data['rights_sha256'] = 'f'*64
                            member = m.encoded(data)
                        new.writestr(name, member)
                return changed.getvalue()
        drive = ChangedDrive()
        def provider(endpoint, query, key):
            data = bar(query['symbol'], query['mic_code'])
            return m.encoded(data), data
        with self.assertRaisesRegex(m.Refused, 'PACK_HASH'):
            m.capture(drive, FOLDERS, 'credential-canary', {'sha256': 'a'*64}, provider, lambda _: None)
        self.assertEqual(drive.calls, ['01-provider-raw'])

    def test_duplicate_json_keys_cannot_hide_an_escaped_credential_before_archive(self):
        key = 'credential-canary'
        escaped = ''.join('\\u%04x' % ord(char) for char in key)
        drive = Drive()
        def provider(endpoint, query, selected):
            data = bar(query['symbol'], query['mic_code'])
            raw = m.encoded(data).replace(b'"mic_code":',
                 ('"type":"'+escaped+'","type":"Common Stock","mic_code":').encode(), 1)
            self.assertNotIn(key.encode(), raw)
            return raw, data
        with self.assertRaisesRegex(m.Refused, 'INVALID_JSON'):
            m.capture(drive, FOLDERS, key, {'sha256':'a'*64}, provider, lambda _: None)
        self.assertEqual(drive.calls, [])
        for raw in (b'{"x":1,"x":2}', b'{"meta":{"x":1,"x":2}}'):
            with self.assertRaisesRegex(m.Refused, 'INVALID_JSON'): m.decode(raw)

    def test_corrupted_drive_restore_cannot_publish_normalization_or_success(self):
        drive = Drive()
        def provider(endpoint, query, key):
            d = bar(query['symbol'], query['mic_code'])
            return m.encoded(d), d
        drive.read = lambda _: b'corrupted'
        with self.assertRaises(Exception):
            m.capture(drive, FOLDERS, 'credential-canary', {'sha256': 'a'*64}, provider, lambda _: None)
        self.assertEqual(drive.calls, ['01-provider-raw'])

    def test_drive_shared_wrong_owner_parent_or_trash_are_refused(self):
        drive = object.__new__(m.OwnerDrive)
        drive.owner = 'owner-canary'
        good = dict(id='file-canary', mimeType='application/vnd.google-apps.folder',
                    trashed=False, shared=False, parents=['root-canary'],
                    permissions=[dict(id='owner-canary', type='user', role='owner')])
        drive.get = lambda *args: good
        self.assertEqual(drive.check('file-canary', 'root-canary'), good)
        changes = [dict(shared=True), dict(trashed=True), dict(parents=['different-root']),
                   dict(permissions=[dict(id='different-owner', type='user', role='owner')]),
                   dict(permissions=[])]
        for changed in changes:
            drive.get = lambda *args, changed=changed: dict(good, **changed)
            with self.assertRaises(m.Refused):
                drive.check('file-canary', 'root-canary')

    def test_production_upload_bypasses_domain_default_visibility(self):
        drive = object.__new__(m.OwnerDrive)
        drive.root_id = 'root-canary'
        drive.free = 32_000_000
        checks, requests = [], []
        drive.check = lambda *args, **kwargs: checks.append((args, kwargs))
        raw = b'private-storage-canary'
        drive.read = lambda _: raw
        def request(url, **kwargs):
            requests.append((url, kwargs))
            return m.encoded(dict(id='file-canary'))
        drive.request = request
        out = drive.write('folder-canary', raw, '.json')
        self.assertEqual(out['sha256'], m.digest(raw))
        self.assertEqual(len(requests), 1)
        query = parse_qs(urlsplit(requests[0][0]).query)
        self.assertEqual(query['ignoreDefaultVisibility'], ['true'])
        self.assertEqual(query['uploadType'], ['multipart'])
        self.assertEqual(requests[0][1]['method'], 'POST')
        self.assertEqual(checks[0][0], ('folder-canary', 'root-canary'))
        self.assertEqual(checks[1][0], ('file-canary', 'folder-canary'))

    def test_invalid_or_service_account_config_refuses_without_child_process(self):
        import tempfile
        for config in ('', '[gdrive]\ntype=drive\nservice_account_file=private-canary\n'):
            with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'MACRO_DRIVE_CONFIG': config}, clear=True), \
                    patch.object(m.subprocess, 'run', side_effect=AssertionError):
                with self.assertRaises(m.Refused):
                    m.OwnerDrive('root-canary-123', temp)

    def test_known_provider_or_configuration_failure_is_safe_at_cli_boundary(self):
        from contextlib import redirect_stdout
        for failure, expected in [(m.Refused('RATE_LIMIT'), 'RATE_LIMIT'),
                                  (m.Refused('PRIVATE_CREDENTIAL_CANARY'), 'UNCLASSIFIED_REFUSAL'),
                                  (ValueError('private-credential-canary'), 'UNEXPECTED_FAILURE')]:
            with patch.object(sys, 'argv', ['capture']), patch.object(m, 'run', side_effect=failure), \
                    redirect_stdout(io.StringIO()) as output:
                self.assertEqual(m.main(), 1)
            report = json.loads(output.getvalue())
            self.assertEqual(report['reason'], expected)
            self.assertNotIn('credential-canary', output.getvalue().lower())

    def test_reviewed_workflow_inputs_and_only_selected_key_are_bound(self):
        # PyYAML is already a dependency of the registered Tier-1 suite.
        try:
            import yaml
        except ImportError:
            self.skipTest('YAML checks run in registered Tier-1 suite')
        value = yaml.safe_load((ROOT / '.github/workflows/twelve_private_capture.yml').read_text())
        self.assertEqual(set(value.get('on', value.get(True))), {'workflow_dispatch'})
        self.assertEqual(value['permissions'], {'contents': 'read'})
        env = value['jobs']['capture']['steps'][-1]['env']
        self.assertEqual(env['TWELVE_API_KEY'], "${{ inputs.twelve_key_name == 'TWELVE_API_KEY' && secrets.TWELVE_API_KEY || '' }}")
        self.assertEqual(env['TWELVE_API_KEY2'], "${{ inputs.twelve_key_name == 'TWELVE_API_KEY2' && secrets.TWELVE_API_KEY2 || '' }}")
        self.assertEqual(env['R1000_PRIVATE_RESEARCH_FOLDER_ID'], '${{ inputs.private_root_folder_id }}')
        self.assertEqual(env['A1_PRIVATE_RESEARCH_AUTHORIZED'], '${{ inputs.private_research_authorized }}')
        self.assertEqual(value['jobs']['capture']['timeout-minutes'], 180)


def load_tests(loader, tests, pattern):
    # api_credentials_check_smoke already loads this suite in frozen Tier-1.
    # Extend that entrypoint without changing the protected runner/workflow.
    path = ROOT / 'tests/twelve_private_cohort_smoke.py'
    spec = importlib.util.spec_from_file_location('twelve_cohort_registered', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tests.addTests(loader.loadTestsFromModule(module))
    return tests


if __name__ == '__main__':
    unittest.main()

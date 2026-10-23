"""Offline contracts; no real OAuth, Drive, Sheets or market provider calls."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import unquote
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import etf116_private_sheet_probe_h2 as probe

ENV = {'ETF116_PRIVATE_PROBE_AUTHORIZED': 'true', 'GITHUB_ACTIONS': 'true',
       'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REPOSITORY': probe.REPOSITORY,
       'GITHUB_SHA': 'a' * 40, 'ETF116_EXPECTED_CODE_SHA': 'a' * 40,
       'GITHUB_RUN_ID': '12345', 'GITHUB_RUN_ATTEMPT': '1'}


class DriveFixture:
    owner, token = 'CONTRACT_FIXTURE_OWNER', 'CONTRACT_FIXTURE_SECRET'

    def __init__(self):
        self.tabs={probe.TAB_ID:{'title':probe.TAB,'sheetId':probe.TAB_ID,
                                'gridProperties':{'rowCount':20,'columnCount':3}}}
        self.values={probe.TAB_ID:[['CONNECTOR_PROOF','KEEP','UNCHANGED']]}
        self.calls=[]
        self.can_edit, self.wrong_tab, self.mismatch = True, False, False
        self.race=False
        self.fail_after_apply=False

    def install(self,binding,values,title_override=None):
        sheet_id,title,_=probe.run_target(binding)
        self.tabs[sheet_id]={'sheetId':sheet_id,'title':title_override or title,
                            'gridProperties':{'rowCount':9,'columnCount':3}}
        self.values[sheet_id]=copy.deepcopy(values)
        return sheet_id

    def check(self, sheet, parent, folder=False):
        if (sheet, parent, folder) != (probe.PRIVATE_SHEET, probe.PRIVATE_ROOT, False):
            raise RuntimeError('BAD_TARGET')
        return {'mimeType': 'application/vnd.google-apps.spreadsheet'}

    def get(self, path, query):
        return {'id': probe.PRIVATE_SHEET, 'capabilities': {'canEdit': self.can_edit}}

    def request(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith(':batchUpdate'):
            requests=json.loads(kwargs['body'])['requests']
            if kwargs.get('method')!='POST' or len(requests)!=2 or set(requests[0])!={'addSheet'} or set(requests[1])!={'updateCells'}:
                raise AssertionError('NON_ATOMIC_CREATE')
            props=requests[0]['addSheet']['properties'];sid=props['sheetId']
            update=requests[1]['updateCells']
            if update['range']['sheetId']!=sid or update['fields']!='userEnteredValue':
                raise AssertionError('WRONG_ATOMIC_TARGET')
            values=[[v['userEnteredValue']['stringValue'] for v in row['values']] for row in update['rows']]
            if self.race:
                self.tabs[sid]=copy.deepcopy(props);self.values[sid]=[['FOREIGN_RACING_WRITER']]
            if sid in self.tabs or any(p['title']==props['title'] for p in self.tabs.values()):
                raise ValueError('SIMULATED_ATOMIC_COLLISION')
            self.tabs[sid]=copy.deepcopy(props);self.values[sid]=values
            if self.fail_after_apply:raise ValueError('AMBIGUOUS_BATCH_RESULT')
            result={'spreadsheetId':probe.PRIVATE_SHEET,'replies':[{'addSheet':{'properties':props}},{}]}
        elif '/values/' not in url:
            properties=copy.deepcopy(list(self.tabs.values()))
            if self.wrong_tab:properties[0]['sheetId']=1
            result={'spreadsheetId':probe.PRIVATE_SHEET,'sheets':[{'properties':p} for p in properties]}
        else:
            title=unquote(url.split('/values/',1)[1].split('?',1)[0]).split('!',1)[0]
            ids=[sid for sid,p in self.tabs.items() if p['title']==title]
            if len(ids)!=1:raise ValueError('FIXTURE_TAB_MISSING')
            result={'values':[['WRONG']] if self.mismatch else self.values[ids[0]]}
        return json.dumps(result).encode()


class PrivateSheetProbeTests(unittest.TestCase):
    def setUp(self):
        self.binding = probe.actions_binding(ENV)
        self.drive = DriveFixture()

    def test_exact_private_write_and_independent_readback(self):
        receipt = probe.run_probe(self.drive, self.binding)
        posts = [(u, k) for u, k in self.drive.calls if k.get('method') == 'POST']
        self.assertEqual(len(posts), 1)
        requests=json.loads(posts[0][1]['body'])['requests']
        self.assertEqual([list(r)[0] for r in requests],['addSheet','updateCells'])
        reads = [u for u, k in self.drive.calls if '/values/' in u and k.get('method') != 'PUT']
        self.assertEqual(len(reads),1)
        self.assertIn('valueRenderOption=UNFORMATTED_VALUE', reads[0])
        sid,_,_=probe.run_target(self.binding)
        self.assertEqual(len(self.drive.values[sid]), 9)
        self.assertEqual(self.drive.values[probe.TAB_ID],[['CONNECTOR_PROOF','KEEP','UNCHANGED']])
        self.assertEqual(receipt['state'], 'CREATE_AND_READBACK_VERIFIED')
        self.assertFalse(receipt['automatic_refresh_enabled'])
        self.assertFalse(receipt['source_admission'])
        self.assertNotIn(self.drive.token, json.dumps(receipt))
        self.assertTrue(all(probe.PRIVATE_SHEET in u for u, _ in self.drive.calls))
        self.assertTrue(all('1qTBZZP' not in u for u, _ in self.drive.calls))

    def test_identical_same_attempt_is_read_only(self):
        self.drive.install(self.binding,probe.marker(self.binding,self.drive.owner))
        receipt = probe.run_probe(self.drive, self.binding)
        self.assertEqual(receipt['write_requests'], 0)
        self.assertEqual(receipt['state'], 'IDENTICAL_MARKER_READBACK')
        self.assertFalse(any(k.get('method') in ('PUT','POST') for _, k in self.drive.calls))

    def test_different_attempt_cannot_overwrite_prior_proof(self):
        old = copy.deepcopy(self.binding)
        old['GITHUB_RUN_ATTEMPT'] = '2'
        old_id=self.drive.install(old,probe.marker(old,self.drive.owner))
        prior=copy.deepcopy(self.drive.values[old_id])
        receipt=probe.run_probe(self.drive,self.binding)
        self.assertEqual(receipt['write_requests'],1)
        self.assertEqual(self.drive.values[old_id],prior)
        self.assertNotEqual(receipt['sheet_id'],old_id)

    def test_nonempty_foreign_or_formula_cells_refuse(self):
        for values in ([['KEEP']], [['=NOW()']], [['=""']], [['', 'X']], [None]):
            with self.subTest(values=values):
                self.drive.install(self.binding,values)
                with self.assertRaisesRegex(probe.ProbeRefused, 'PROBE_READBACK'):
                    probe.run_probe(self.drive, self.binding)
        self.assertFalse(any(k.get('method') in ('PUT','POST') for _, k in self.drive.calls))

    def test_no_edit_or_wrong_tab_refuses_before_write(self):
        for attr in ('can_edit', 'wrong_tab'):
            self.drive = DriveFixture()
            setattr(self.drive, attr, attr != 'can_edit')
            with self.assertRaises(probe.ProbeRefused):
                probe.run_probe(self.drive, self.binding)
            self.assertFalse(any(k.get('method') in ('PUT','POST') for _, k in self.drive.calls))

    def test_post_write_mismatch_has_no_retry_or_cleanup(self):
        self.drive.mismatch = True
        with self.assertRaisesRegex(probe.ProbeRefused, 'PROBE_READBACK'):
            probe.run_probe(self.drive, self.binding)
        self.assertEqual(sum(k.get('method') == 'POST' for _, k in self.drive.calls), 1)

    def test_actions_authorization_and_exact_code_binding(self):
        for field in ENV:
            bad = dict(ENV, **{field: 'WRONG'})
            with self.subTest(field=field), self.assertRaises(probe.ProbeRefused):
                probe.actions_binding(bad)

    def test_cli_preserves_existing_receipt_before_auth(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / 'proof.json'
            output.write_text('KEEP')
            with patch.object(sys, 'argv', ['probe', '--output', str(output)]), \
                    patch('tools.twelve_private_capture.OwnerDrive') as owner:
                with self.assertRaises(FileExistsError):
                    probe.main()
                owner.assert_not_called()
            self.assertEqual(output.read_text(), 'KEEP')

    def test_cli_missing_oauth_does_not_fallback_to_service_account(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / 'proof.json'
            with patch.object(sys, 'argv', ['probe', '--output', str(output)]), \
                    patch.dict(os.environ, dict(ENV, GOOGLE_SERVICE_ACCOUNT_KEY='NOT_USED'), clear=True), \
                    patch('tools.twelve_private_capture.OwnerDrive') as owner, \
                    patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(probe.main(), 2)
                owner.assert_not_called()
            self.assertEqual(json.loads(output.read_text())['reason'], 'OWNER_OAUTH_CONFIG_REQUIRED')

    def test_cli_exception_text_never_enters_receipt_or_stdout(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / 'proof.json'
            with patch.object(sys, 'argv', ['probe', '--output', str(output)]), \
                    patch.dict(os.environ, dict(ENV, RCLONE_CONFIG_GDRIVE='CONTRACT_FIXTURE_CONFIG'), clear=True), \
                    patch('tools.twelve_private_capture.OwnerDrive', side_effect=ValueError('SECRET_URL_TOKEN')), \
                    patch('sys.stdout', new_callable=io.StringIO) as stdout:
                self.assertEqual(probe.main(), 2)
            self.assertNotIn('SECRET_URL_TOKEN', output.read_text() + stdout.getvalue())

    def test_cli_owner_refusal_exposes_only_fixed_category_and_stage(self):
        from tools.twelve_private_capture import Refused
        for reason, expected in [('DRIVE_NOT_OWNER_ONLY', 'DRIVE_NOT_OWNER_ONLY'),
                                 ('SECRET_URL_TOKEN', 'UNCLASSIFIED_OWNER_REFUSAL')]:
            with tempfile.TemporaryDirectory() as td:
                output = Path(td) / 'proof.json'
                with patch.object(sys, 'argv', ['probe', '--output', str(output)]), \
                        patch.dict(os.environ, dict(ENV, RCLONE_CONFIG_GDRIVE='FIXTURE'), clear=True), \
                        patch('tools.twelve_private_capture.OwnerDrive', side_effect=Refused(reason)), \
                        patch('sys.stdout', new_callable=io.StringIO) as stdout:
                    self.assertEqual(probe.main(), 2)
                receipt = json.loads(output.read_text())
                self.assertEqual(receipt['failed_stage'], 'OWNER_DRIVE_INITIALIZATION')
                self.assertEqual(receipt['access_reason'], expected)
                self.assertNotIn('SECRET_URL_TOKEN', output.read_text() + stdout.getvalue())

    def test_owner_privacy_is_rechecked_after_write(self):
        with patch.object(self.drive, 'check', side_effect=[
                {'mimeType': 'application/vnd.google-apps.spreadsheet'},
                {'mimeType': 'application/vnd.google-apps.spreadsheet'},
                ValueError('PRIVACY_CHANGED')]):
            with self.assertRaisesRegex(ValueError, 'PRIVACY_CHANGED'):
                probe.run_probe(self.drive, self.binding)
        self.assertEqual(sum(k.get('method') == 'POST' for _, k in self.drive.calls), 1)

    def test_racing_external_writer_is_not_overwritten(self):
        self.drive.race=True
        with self.assertRaisesRegex(ValueError,'SIMULATED_ATOMIC_COLLISION'):
            probe.run_probe(self.drive,self.binding)
        sid,_,_=probe.run_target(self.binding)
        self.assertEqual(self.drive.values[sid],[['FOREIGN_RACING_WRITER']])
        self.assertEqual(sum(k.get('method')=='POST' for _,k in self.drive.calls),1)
        self.assertFalse(any(k.get('method')=='PUT' for _,k in self.drive.calls))

    def test_preexisting_id_collision_refuses_without_write(self):
        self.drive.install(self.binding,[['FOREIGN']],title_override='FOREIGN_TAB')
        with self.assertRaisesRegex(probe.ProbeRefused,'PROBE_TAB_COLLISION'):
            probe.run_probe(self.drive,self.binding)
        self.assertFalse(any(k.get('method') in ('PUT','POST') for _,k in self.drive.calls))

    def test_ambiguous_batch_has_no_retry_or_cleanup(self):
        self.drive.fail_after_apply=True
        with self.assertRaisesRegex(ValueError,'AMBIGUOUS_BATCH_RESULT'):
            probe.run_probe(self.drive,self.binding)
        sid,_,_=probe.run_target(self.binding)
        self.assertEqual(self.drive.values[sid],probe.marker(self.binding,self.drive.owner))
        self.assertEqual(sum(k.get('method')=='POST' for _,k in self.drive.calls),1)
        self.assertFalse(any(k.get('method') in ('PUT','DELETE') for _,k in self.drive.calls))

    def test_existing_owner_check_refuses_before_sheet_calls(self):
        with patch.object(self.drive, 'check', side_effect=ValueError('NOT_OWNER_ONLY')):
            with self.assertRaisesRegex(ValueError, 'NOT_OWNER_ONLY'):
                probe.run_probe(self.drive, self.binding)
        self.assertEqual(self.drive.calls, [])

    def cli_failure(self, drive, *, initialization_error=None):
        """Exercise the native CLI boundary, with no credentials or service calls."""
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / 'proof.json'
            with patch.object(sys, 'argv', ['probe', '--output', str(output)]), \
                    patch.dict(os.environ, dict(ENV, RCLONE_CONFIG_GDRIVE='FIXTURE_CONFIG'), clear=True), \
                    patch('tools.twelve_private_capture.OwnerDrive', return_value=drive,
                          side_effect=initialization_error), \
                    patch('sys.stdout', new_callable=io.StringIO) as stdout, \
                    patch('sys.stderr', new_callable=io.StringIO) as stderr:
                self.assertEqual(probe.main(), 2)
            raw = output.read_text() + stdout.getvalue() + stderr.getvalue()
            for private in (drive.token, 'FIXTURE_PRIVATE_MESSAGE', 'FIXTURE_CONFIG',
                            'https://user:FIXTURE_PRIVATE_MESSAGE@example.invalid'):
                self.assertNotIn(private, raw)
            receipt = json.loads(output.read_text())
            self.assertFalse(receipt['verified'])
            self.assertFalse(receipt['automatic_refresh_enabled'])
            self.assertFalse(any(k.get('method') in ('PUT', 'DELETE', 'PATCH') for _, k in drive.calls))
            self.assertLessEqual(sum(k.get('method') == 'POST' for _, k in drive.calls), 1)
            return receipt

    def post_failure(self, mode):
        from tools import twelve_private_capture as transport
        drive = DriveFixture()
        original = drive.request

        class Reply:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return b''

        class Opener:
            def open(self, *args, **kwargs):
                if mode == 'HTTP_ERROR':
                    raise HTTPError('https://example.invalid', 503, 'FIXTURE_PRIVATE_MESSAGE', {}, None)
                if mode == 'RESPONSE_SIZE': return Reply()
                raise OSError('https://user:FIXTURE_PRIVATE_MESSAGE@example.invalid')

        def request(url, **kwargs):
            result = original(url, **kwargs)
            if kwargs.get('method') == 'POST':
                # The server fixture commits before its response is lost/unusable.
                if mode in ('NETWORK', 'HTTP_ERROR', 'RESPONSE_SIZE'):
                    with patch.object(transport, 'build_opener', return_value=Opener()):
                        return transport.http(url, **kwargs, credentials=(drive.token,))
                if mode == 'INVALID_JSON': return b'not-json FIXTURE_PRIVATE_MESSAGE'
                if mode == 'CREDENTIAL_ECHO': return json.dumps({'echo': drive.token}).encode()
                if mode == 'UNCLASSIFIED': raise transport.Refused('FIXTURE_PRIVATE_MESSAGE')
                raise RuntimeError('https://user:FIXTURE_PRIVATE_MESSAGE@example.invalid')
            return result

        with patch.object(drive, 'request', side_effect=request):
            receipt = self.cli_failure(drive)
        self.assertEqual(receipt['reason'], 'ATOMIC_POST_OUTCOME_UNKNOWN')
        self.assertEqual(receipt['failed_stage'], 'SHEETS_ATOMIC_POST')
        self.assertEqual(receipt['access_reason'], mode if mode in ('NETWORK', 'HTTP_ERROR')
                         else None if mode == 'GENERIC' else 'UNCLASSIFIED_OWNER_REFUSAL')
        self.assertEqual(sum(k.get('method') == 'POST' for _, k in drive.calls), 1)
        self.assertFalse(any('/values/' in u for u, _ in drive.calls))
        sid, title, _ = probe.run_target(self.binding)
        expected = probe.marker(self.binding, drive.owner)
        self.assertEqual(drive.values[sid], expected)
        calls_before = len(drive.calls)
        reconciled = probe.literal_private_tab(drive, sid, title, expected, existing_only=True)
        self.assertTrue(reconciled['unchanged'])
        self.assertEqual(reconciled['write_requests'], 0)
        self.assertEqual(reconciled['values_sha256'], probe.digest(expected))
        self.assertEqual(len(drive.calls[calls_before:]), 3)
        self.assertTrue(all(k.get('method', 'GET') == 'GET' for _, k in drive.calls[calls_before:]))
        self.assertEqual(drive.values[probe.TAB_ID], [['CONNECTOR_PROOF', 'KEEP', 'UNCHANGED']])

    def test_cli_post_typed_transport_failures_are_unknown(self):
        for mode in ('NETWORK', 'HTTP_ERROR', 'RESPONSE_SIZE', 'INVALID_JSON', 'CREDENTIAL_ECHO'):
            with self.subTest(mode=mode): self.post_failure(mode)

    def test_cli_post_generic_and_unclassified_refusal_are_unknown(self):
        for mode in ('GENERIC', 'UNCLASSIFIED'):
            with self.subTest(mode=mode): self.post_failure(mode)

    def test_cli_get_failures_keep_their_stage_and_never_write(self):
        from tools.twelve_private_capture import Refused
        for existing in (False, True):
            drive = DriveFixture()
            if existing: drive.install(self.binding, probe.marker(self.binding, drive.owner))
            request = drive.request
            def fail(url, **kwargs):
                if ('/values/' in url) == existing:
                    drive.calls.append((url, kwargs))
                    raise Refused('NETWORK')
                return request(url, **kwargs)
            with self.subTest(existing=existing), patch.object(drive, 'request', side_effect=fail):
                receipt = self.cli_failure(drive)
                self.assertEqual(receipt['failed_stage'], 'SHEETS_EXISTING_GET' if existing else 'SHEETS_METADATA_GET')
                self.assertEqual(receipt['reason'], 'OWNER_OAUTH_ACCESS_BLOCKED')
                self.assertEqual(receipt['access_reason'], 'NETWORK')
                self.assertFalse(any(k.get('method', 'GET') != 'GET' for _, k in drive.calls))

    def test_cli_owner_initialization_failure_is_safe(self):
        from tools.twelve_private_capture import Refused
        receipt = self.cli_failure(self.drive, initialization_error=Refused('NETWORK'))
        self.assertEqual(receipt['failed_stage'], 'OWNER_DRIVE_INITIALIZATION')
        self.assertEqual(receipt['access_reason'], 'NETWORK')
        self.assertEqual(receipt['reason'], 'OWNER_OAUTH_ACCESS_BLOCKED')
        self.assertEqual(self.drive.calls, [])

    def test_private_checks_and_readback_fail_at_their_own_stage(self):
        from tools.twelve_private_capture import Refused
        for check_number, stage, posts in [(1, 'PRIVATE_DRIVE_CHECK', 0),
                (2, 'PRIVATE_DRIVE_RECHECK', 0), (3, 'PRIVATE_DRIVE_FINAL_CHECK', 1)]:
            drive = DriveFixture()
            info = {'mimeType': 'application/vnd.google-apps.spreadsheet'}
            with self.subTest(stage=stage), patch.object(drive, 'check',
                    side_effect=[info] * (check_number - 1) + [Refused('NETWORK')]):
                receipt = self.cli_failure(drive)
                self.assertEqual(receipt['failed_stage'], stage)
                self.assertEqual(receipt['reason'], 'OWNER_OAUTH_ACCESS_BLOCKED')
                self.assertEqual(sum(k.get('method') == 'POST' for _, k in drive.calls), posts)
        drive = DriveFixture()
        original = drive.request
        def fail_readback(url, **kwargs):
            if '/values/' in url:
                drive.calls.append((url, kwargs))
                raise Refused('NETWORK')
            return original(url, **kwargs)
        with patch.object(drive, 'request', side_effect=fail_readback):
            receipt = self.cli_failure(drive)
        self.assertEqual(receipt['failed_stage'], 'SHEETS_READBACK_GET')
        self.assertEqual(receipt['reason'], 'OWNER_OAUTH_ACCESS_BLOCKED')
        self.assertEqual(sum(k.get('method') == 'POST' for _, k in drive.calls), 1)

    def test_stage_order_for_new_and_existing_markers(self):
        for existing in (False, True):
            drive, stages = DriveFixture(), []
            if existing: drive.install(self.binding, probe.marker(self.binding, drive.owner))
            probe.run_probe(drive, self.binding, stage_cb=stages.append)
            self.assertEqual(stages, ['PRIVATE_DRIVE_CHECK', 'SHEETS_METADATA_GET'] +
                (['SHEETS_EXISTING_GET'] if existing else ['PRIVATE_DRIVE_RECHECK', 'SHEETS_ATOMIC_POST']) +
                ['SHEETS_READBACK_GET', 'PRIVATE_DRIVE_FINAL_CHECK'])

    def test_existing_only_absent_mismatch_or_rebound_marker_refuses_without_write(self):
        sid, title, _ = probe.run_target(self.binding)
        expected = probe.marker(self.binding, self.drive.owner)
        for mode in ('absent', 'mismatch', 'rebound', 'foreign_id'):
            drive = DriveFixture()
            if mode != 'absent':
                wrong = copy.deepcopy(expected)
                wrong[2][1] = '99999' if mode == 'rebound' else 'WRONG'
                drive.install(self.binding, wrong, title_override='FOREIGN' if mode == 'foreign_id' else None)
            with self.subTest(mode=mode), self.assertRaises(probe.ProbeRefused):
                probe.literal_private_tab(drive, sid, title, expected, existing_only=True)
            self.assertTrue(all(k.get('method', 'GET') == 'GET' for _, k in drive.calls))


if __name__ == '__main__':
    unittest.main()

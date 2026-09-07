"""Offline checks of credential diagnostics and non-disclosure boundaries."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / '.github/workflows/api_credentials_check.yml').read_text())
STEP = WORKFLOW['jobs']['probe']['steps'][0]
SOURCE = STEP['run'].split('\n', 1)[1].rsplit('PYTHON', 1)[0]
NS = {'__name__': 'probe_under_test'}
exec(compile(SOURCE, 'embedded_probe', 'exec'), NS)


class CredentialCheckTests(unittest.TestCase):
    def test_reviewed_master_only_no_write_workflow(self):
        self.assertEqual(WORKFLOW.get('on', WORKFLOW.get(True)), {
            'workflow_dispatch': None,
            'push': {'branches': ['master'], 'paths': ['.github/workflows/api_credentials_check.yml']},
        })
        self.assertEqual(WORKFLOW['permissions'], {})
        self.assertEqual(WORKFLOW['jobs']['probe']['if'], "github.ref == 'refs/heads/master'")
        self.assertEqual(len(WORKFLOW['jobs']['probe']['steps']), 1)
        self.assertNotIn('uses', STEP)
        self.assertLessEqual(WORKFLOW['jobs']['probe']['timeout-minutes'], 6)

    def test_error_classification(self):
        cases = [('Alpaca', 401, {}, 'AUTH_REJECTED'),
                 ('FMP', 402, {}, 'PLAN_RESTRICTED'),
                 ('Finnhub', 403, {}, 'FORBIDDEN_CHECK_KEY_PLAN_IP'),
                 ('FRED', 429, {}, 'RATE_LIMITED'),
                 ('FRED', 400, {'error_code': 400, 'error_message': 'Bad Request. The value for variable api_key is not registered.'}, 'AUTH_REJECTED'),
                 ('FRED', 400, {'error_code': 400, 'error_message': 'Bad Request. The value for variable api_key must be a 32 character string.'}, 'AUTH_REJECTED'),
                 ('FRED', 400, {'error_code': 400, 'error_message': 'Bad Request. The series does not exist.'}, 'PROVIDER_ERROR'),
                 ('FRED', 400, {'error_code': 400, 'error_message': None}, 'HTTP_ERROR'),
                 ('DART', 200, {'status': '010'}, 'AUTH_REJECTED'),
                 ('AlphaVantage', 200, {'Information': 'sensitive'}, 'PROVIDER_NOTICE_CHECK_QUOTA_PLAN'),
                 ('Finnhub', 200, {}, 'EMPTY_OR_UNEXPECTED_RESPONSE')]
        for provider, code, data, expected in cases:
            with self.subTest(provider=provider, code=code):
                self.assertEqual(NS['classify'](provider, code, data), expected)

    def test_missing_keys_make_no_requests(self):
        def forbidden(*args):
            self.fail('network called without credentials')
        with patch.dict(os.environ, {}, clear=True), patch.dict(NS, request=forbidden), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(NS['run'](), 1)
        report = json.loads(out.getvalue())
        self.assertEqual(len(report['results']), 10)
        self.assertTrue(all(r['result'] == 'MISSING_SECRET' for r in report['results']))

    def test_vendor_echo_and_exception_never_logged(self):
        canary = 'credential-canary-never-publish'
        def raises(*args):
            raise RuntimeError(canary)
        for reply in [lambda *a: (200, {'error': canary}),
                      lambda *a: (400, {'error_code': 400, 'error_message': 'The value for variable api_key ' + canary + ' is not registered.'}),
                      raises]:
            with tempfile.TemporaryDirectory() as tmp:
                summary = Path(tmp) / 'summary.md'
                env = {name: canary for name in STEP['env']}
                env['GITHUB_STEP_SUMMARY'] = str(summary)
                with patch.dict(os.environ, env, clear=True), patch.dict(NS, request=reply), contextlib.redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(NS['run'](), 1)
                self.assertNotIn(canary, out.getvalue() + summary.read_text())

    def test_krx_wrong_date_is_not_success(self):
        self.assertEqual(NS['classify']('KRX', 200, {'OutBlock_1': [{'BAS_DD': '20260904', 'ISU_CD': '005930'}]}), 'PASS')
        self.assertNotEqual(NS['classify']('KRX', 200, {'OutBlock_1': [{'BAS_DD': '20260903', 'ISU_CD': '005930'}]}), 'PASS')

    def test_redirects_cannot_forward_credentials(self):
        handler = NS['NoRedirect']()
        self.assertIsNone(handler.redirect_request(None, None, 302, '', {}, 'https://example.invalid'))

    def test_success_fixtures_and_fixed_query_destinations(self):
        fixtures = [{'bars': [{'t': '2026-09-04', 'c': 1}]},
                    {'ticker': 'AAPL', 'name': 'Apple'}, {'data': [{'epsAvg': 1}]},
                    [{'symbol': 'AAPL'}], [{'symbol': 'AAPL'}],
                    {'observations': [{'value': '1'}]}, {'Symbol': 'IBM'},
                    {'status': '000', 'stock_code': '005930'},
                    {'StatisticTableList': {'row': [{}]}},
                    {'OutBlock_1': [{'BAS_DD': '20260904', 'ISU_CD': '005930'}]}]
        destinations = []
        def fake(url, *args):
            destinations.append(url)
            return 200, fixtures.pop(0)
        with patch.dict(os.environ, {name: 'dummy' for name in STEP['env']}, clear=True), patch.dict(NS, request=fake), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(NS['run'](), 0)
        self.assertEqual(len(destinations), 10)
        self.assertTrue(all(url.startswith('https://') for url in destinations))
        self.assertFalse(any('/orders' in url or '/account' in url for url in destinations))

    def test_successful_fallback_aliases_do_not_fail(self):
        for missing in [('ALPHAVANTAGE_API_KEY',), ('BOK_ECOS_API_KEY',),
                        ('ALPHAVANTAGE_API_KEY', 'BOK_ECOS_API_KEY')]:
            with self.subTest(missing=missing):
                env = {name: 'dummy' for name in STEP['env'] if name not in missing}
                with patch.dict(os.environ, env, clear=True), patch.dict(NS, request=lambda *a: (200, {}), classify=lambda *a: 'PASS'), contextlib.redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(NS['run'](), 0)
                report = json.loads(out.getvalue())
                self.assertEqual(report['alias_warnings'], [])
                self.assertEqual(report['alias_notices'], [name + ': FALLBACK_USED' for name in missing])
                self.assertTrue(all(r['result'] == 'PASS' for r in report['results']))

    def test_conflicting_alias_is_visible_without_value(self):
        env = {name: 'dummy' for name in STEP['env']}
        env.update({'ECOS_API_KEY': 'alternate-canary', 'BOK_ECOS_API_KEY': 'primary-canary'})
        with patch.dict(os.environ, env, clear=True), patch.dict(NS, request=lambda *a: (200, {}), classify=lambda *a: 'PASS'), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(NS['run'](), 1)
        self.assertEqual(json.loads(out.getvalue())['alias_warnings'], ['BOK_ECOS_API_KEY: CONFLICT_PRIMARY_USED'])
        self.assertTrue(all(r['result'] == 'PASS' for r in json.loads(out.getvalue())['results']))
        self.assertNotIn('alternate-canary', out.getvalue())
        self.assertNotIn('primary-canary', out.getvalue())


if __name__ == '__main__':
    unittest.main()

"""Offline IEX-only preflight guard tests; does not contact Alpaca."""
import contextlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / '.github/workflows/alpaca_iex_credential_preflight.yml').read_text())
STEP = WORKFLOW['jobs']['iex_probe']['steps'][0]
SOURCE = STEP['run'].split('\n', 1)[1].rsplit('PYTHON', 1)[0]
NS = {'__name__': 'offline_probe_fixture'}
exec(compile(SOURCE, 'embedded_a1_alpaca_iex_probe', 'exec'), NS)


def fixture(session='2026-10-09', volume=100):
    return json.dumps({'bars': {'AAPL': [
        {'t': session + 'T04:00:00Z', 'o': 10.0, 'h': 11.0, 'l': 9.0,
         'c': 10.5, 'v': volume}
    ]}}).encode()


class PreflightTests(unittest.TestCase):
    def test_only_manual_master_read_without_artifacts(self):
        self.assertEqual(WORKFLOW.get('on', WORKFLOW.get(True)), {'workflow_dispatch': None})
        self.assertEqual(WORKFLOW['permissions'], {})
        job = WORKFLOW['jobs']['iex_probe']
        self.assertEqual(job['if'], "github.ref == 'refs/heads/master'")
        self.assertEqual(len(job['steps']), 1)
        self.assertLessEqual(job['timeout-minutes'], 3)
        self.assertFalse(any(x in STEP for x in ('uses', 'with')))
        self.assertEqual(set(STEP['env']), {'ALPACA_API_KEY', 'ALPACA_API_SECRET'})
        self.assertNotIn('upload-artifact', STEP['run'])
        self.assertNotIn('/orders', STEP['run'])
        self.assertNotIn('/account', STEP['run'])

    def test_missing_runner_env_blocks_network_not_repo_inventory_claim(self):
        with patch.dict(os.environ, {}, clear=True), patch.dict(NS, request_status_body=lambda *a: self.fail('network attempted')), contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = NS['run']()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout.getvalue())['result'], 'MISSING_SECRET_IN_RUNNER')

    def test_safe_classifications(self):
        cases = [(0, 'NETWORK'), (401, 'AUTH'), (402, 'ENTITLEMENT_OR_SCOPE'),
                 (403, 'ENTITLEMENT_OR_SCOPE'), (400, 'REQUEST_OR_ENTITLEMENT'),
                 (422, 'REQUEST_OR_ENTITLEMENT'), (429, 'RATE_LIMIT'),
                 (307, 'REDIRECT_REFUSED'), (502, 'PROVIDER_ERROR'),
                 (404, 'HTTP_ERROR')]
        for status, expected in cases:
            with self.subTest(status=status):
                self.assertEqual(NS['classify'](status, None), expected)

    def test_success_and_no_raw_in_stdout(self):
        key, secret = 'KEY-CANARY-1', 'SECRET-CANARY-2'
        body = fixture()
        with patch.dict(os.environ, {'ALPACA_API_KEY': key, 'ALPACA_API_SECRET': secret}, clear=True), patch.dict(NS, request_status_body=lambda *a: (200, body)), contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = NS['run']()
        z = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(z['result'], 'IEX_ACCESS_CONFIRMED')
        self.assertEqual(z['http_status'], 200)
        self.assertFalse(z['raw_bytes_persisted'])
        self.assertFalse(z['provider_rights_verified'])
        self.assertFalse(z['source_admission'])
        self.assertNotIn(key, stdout.getvalue())
        self.assertNotIn(secret, stdout.getvalue())
        self.assertNotIn(body.decode(), stdout.getvalue())

    def test_payload_errors_and_no_data(self):
        for raw, expected in [(b'{', 'INVALID_RESPONSE'),
                              (b'{"bars":{}}', 'INVALID_RESPONSE'),
                              (b'{"bars":{"AAPL":[]}}', 'NO_DATA'),
                              (fixture('2026-10-08'), 'INVALID_RESPONSE'),
                              (fixture(volume=-1), 'INVALID_RESPONSE'),
                              (b'x' * 65537, 'INVALID_OR_OVERSIZE_RESPONSE')]:
            with self.subTest(expected=expected, raw=raw[:10]):
                self.assertEqual(NS['classify'](200, raw), expected)

    def test_no_redirect(self):
        self.assertIsNone(NS['NoRedirect']().redirect_request(None, None, 302, '', {}, 'https://other.invalid'))

    def test_fixed_iex_single_symbol_request_and_secret_headers(self):
        captured = {}
        class DummyResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, limit):
                captured['limit'] = limit
                return fixture()
        class DummyOpener:
            def open(self, req, timeout):
                captured['url'] = req.full_url
                captured['headers'] = dict(req.header_items())
                captured['timeout'] = timeout
                return DummyResponse()
        with patch.dict(NS, build_opener=lambda *a: DummyOpener()):
            status, raw = NS['request_status_body']('example-key', 'example-secret')
        self.assertEqual(status, 200)
        self.assertEqual(raw, fixture())
        parsed = urlparse(captured['url'])
        self.assertEqual((parsed.scheme, parsed.hostname, parsed.path),
                         ('https', 'data.alpaca.markets', '/v2/stocks/bars'))
        q = parse_qs(parsed.query)
        self.assertEqual({k: v[0] for k, v in q.items()},
                         {k: str(v) for k, v in NS['QUERY'].items()})
        self.assertEqual(captured['headers']['Apca-api-key-id'], 'example-key')
        self.assertEqual(captured['headers']['Apca-api-secret-key'], 'example-secret')
        self.assertEqual(captured['limit'], 65537)
        self.assertEqual(captured['timeout'], 15)

    def test_transport_error_string_redacted(self):
        class BadOpener:
            def open(self, *args, **kwargs):
                raise RuntimeError('SENSITIVE-URL-OR-TOKEN-CANARY')
        with patch.dict(NS, build_opener=lambda *a: BadOpener()), patch.dict(os.environ, {'ALPACA_API_KEY': 'KEY', 'ALPACA_API_SECRET': 'SECRET'}, clear=True), contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(NS['run'](), 1)
        self.assertEqual(json.loads(stdout.getvalue())['result'], 'NETWORK')
        self.assertNotIn('SENSITIVE', stdout.getvalue())

    def test_empty_page_or_invalid_value_never_passes(self):
        self.assertEqual(NS['classify'](200, b'{"bars":{"AAPL":[{"t":"2026-10-09T04:00:00Z"}]}}'), 'INVALID_RESPONSE')
        self.assertFalse(NS['valid_bar']({'t':'2026-10-09T04:00:00Z', 'o': True,'h':11,'l':9,'c':10,'v':100}))
        self.assertFalse(NS['valid_bar']({'t':'2026-10-09T04:00:00Z', 'o':10**500,'h':11,'l':9,'c':10,'v':100}))

    def test_invalid_or_unzoned_clock_never_confirms_access(self):
        for timestamp in ('2026-10-09Tgarbage', '2026-10-09T25:00:00Z',
                          '2026-10-09T04:00:00', '2026-10-09T04:00:00+03:00'):
            data = json.loads(fixture())
            data['bars']['AAPL'][0]['t'] = timestamp
            with self.subTest(timestamp=timestamp):
                self.assertEqual(NS['classify'](200, json.dumps(data).encode()), 'INVALID_RESPONSE')

    def test_inconsistent_ohlc_never_confirms_access(self):
        for field, value in (('h', 9.5), ('l', 10.6)):
            data = json.loads(fixture())
            data['bars']['AAPL'][0][field] = value
            with self.subTest(field=field):
                self.assertEqual(NS['classify'](200, json.dumps(data).encode()), 'INVALID_RESPONSE')

    def test_fractional_or_nonfinite_volume_never_confirms_access(self):
        for volume in (0.5, True, float('nan'), float('inf')):
            with self.subTest(volume=volume):
                self.assertEqual(NS['classify'](200, fixture(volume=volume)), 'INVALID_RESPONSE')
        self.assertEqual(NS['classify'](200, fixture(volume=0)), 'IEX_ACCESS_CONFIRMED')

    def test_recursive_response_is_finite_refusal(self):
        raw = b'[' * 2_000 + b'0' + b']' * 2_000
        self.assertEqual(NS['classify'](200, raw), 'INVALID_RESPONSE')


if __name__ == '__main__':
    unittest.main()

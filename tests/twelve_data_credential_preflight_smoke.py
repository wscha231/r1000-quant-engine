"""Offline refusals and non-disclosure tests; fixtures never certify real data."""
import contextlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / '.github/workflows/twelve_data_credential_preflight.yml').read_text())
STEP = WORKFLOW['jobs']['probe']['steps'][0]
SOURCE = STEP['run'].split('\n', 1)[1].rsplit('PYTHON', 1)[0]
NS = {'__name__': 'twelve_probe_under_test'}
exec(compile(SOURCE, 'embedded_twelve_probe', 'exec'), NS)


def raw(data):
    return json.dumps(data).encode()


def bar(symbol='AAPL', mic='XNAS'):
    return {'meta': {'symbol': symbol, 'mic_code': mic, 'currency': 'USD', 'interval': '1day'},
            'values': [{'datetime': '2026-10-09', 'open': '10', 'high': '12',
                        'low': '9', 'close': '11', 'volume': '0'}]}


def invoke(request, key='offline-canary'):
    with patch.dict(os.environ, {'TWELVE_API_KEY': key}, clear=True), patch.dict(NS, request_body=request), contextlib.redirect_stdout(io.StringIO()) as out:
        code = NS['run']()
    return code, json.loads(out.getvalue()), out.getvalue()


class TwelvePreflightTests(unittest.TestCase):
    def test_manual_master_only_exact_secret_and_no_persistence(self):
        self.assertEqual(WORKFLOW.get('on', WORKFLOW.get(True)), {'workflow_dispatch': None})
        self.assertEqual(WORKFLOW['permissions'], {})
        self.assertEqual(WORKFLOW['jobs']['probe']['if'], "github.ref == 'refs/heads/master'")
        self.assertEqual(STEP['env'], {'TWELVE_API_KEY': '${{ secrets.TWELVE_API_KEY }}'})
        self.assertEqual(len(WORKFLOW['jobs']['probe']['steps']), 1)
        self.assertNotIn('uses', STEP)
        for forbidden in ('open(', 'write(', 'GITHUB_STEP_SUMMARY', 'upload-artifact', 'checkout@'):
            # Network opener is the sole open call, inside a no-redirect handler.
            if forbidden != 'open(':
                self.assertNotIn(forbidden, SOURCE)
        self.assertLessEqual(WORKFLOW['jobs']['probe']['timeout-minutes'], 4)

    def test_missing_secret_never_calls_network(self):
        def forbidden(*args):
            self.fail('network without Secret')
        code, report, _ = invoke(forbidden, key='')
        self.assertEqual(code, 1)
        self.assertEqual(report['request_count'], 0)
        self.assertTrue(all(r['access'] == 'MISSING_SECRET_IN_RUNNER' for r in report['results']))

    def test_fixed_queries_max_eight_and_distinct_listing_histories(self):
        calls = []
        def fake(endpoint, query, key):
            calls.append((endpoint, query.copy()))
            if endpoint == '/time_series':
                return 200, raw(bar(query['symbol'], query['mic_code']))
            return 200, raw({'datetime': '2018-07-25' if query['symbol'] == 'BE' else '1980-12-12'})
        code, report, output = invoke(fake)
        self.assertEqual(code, 0)
        self.assertEqual(report['request_count'], 8)
        self.assertEqual([r['symbol'] for r in report['results']], ['AAPL', 'MSFT', 'BE', 'TSM'])
        self.assertEqual([r['ten_year_span_reported'] for r in report['results']], [True, True, False, True])
        self.assertNotIn('offline-canary', output)
        self.assertNotIn('open', output)
        for endpoint, query in calls:
            self.assertEqual(query['interval'], '1day')
            self.assertNotIn('apikey', query)
            if endpoint == '/time_series':
                self.assertEqual(query['adjust'], 'none')
                self.assertEqual(query['outputsize'], 1)
                self.assertEqual(query['start_date'], query['end_date'])
                self.assertEqual(query['start_date'], '2026-10-09')
        for field in ('raw_bytes_persisted', 'full_history_collected', 'continuous_history_verified',
                      'provider_rights_verified', 'historical_identity_verified', 'pit_verified', 'source_admission'):
            self.assertIs(report[field], False)

    def test_auth_quota_network_and_redirect_stop_without_retry(self):
        cases = [(401, None, 'AUTH'), (429, None, 'RATE_LIMIT'), (0, None, 'NETWORK'),
                 (302, None, 'REDIRECT_REFUSED'),
                 (200, raw({'status': 'error', 'code': 429, 'message': 'offline-canary'}), 'RATE_LIMIT')]
        for status, body, expected in cases:
            with self.subTest(expected=expected):
                code, report, output = invoke(lambda *a: (status, body))
                self.assertEqual(code, 1)
                self.assertEqual(report['request_count'], 1)
                self.assertEqual(report['results'][0]['access'], expected)
                self.assertTrue(all(r['access'] == 'SKIPPED_AFTER_STOP' for r in report['results'][1:]))
                self.assertNotIn('offline-canary', output)

    def test_history_quota_stops_remaining_symbols(self):
        replies = iter([(200, raw(bar())), (200, raw({'status': 'error', 'code': 429}))])
        _, report, _ = invoke(lambda *a: next(replies))
        self.assertEqual(report['request_count'], 2)
        self.assertEqual(report['results'][0]['history'], 'RATE_LIMIT')
        self.assertEqual(report['results'][1]['access'], 'SKIPPED_AFTER_STOP')

    def test_vendor_echo_invalid_error_code_and_parser_failures_are_sanitized(self):
        bodies = [raw({'status': 'error', 'code': [], 'message': 'offline-canary'}),
                  b'not-json-offline-canary', b'[' * 2000, b'x' * (NS['MAX_BYTES'] + 1),
                  b'{"values": NaN}', raw(['offline-canary'])]
        for body in bodies:
            with self.subTest(body_length=len(body)):
                code, report, output = invoke(lambda *a: (200, body))
                self.assertEqual(code, 1)
                self.assertEqual(report['request_count'], 4)
                self.assertNotIn('offline-canary', output)
                self.assertTrue(all(r['reported_earliest_date'] is None for r in report['results']))

    def test_identity_currency_interval_and_exact_session_required(self):
        mutations = [('meta', 'symbol', 'TSM'), ('meta', 'mic_code', 'XNYS'),
                     ('meta', 'currency', 'TWD'), ('meta', 'interval', '1min'),
                     ('values', 'datetime', '2026-10-08')]
        for section, name, value in mutations:
            data = bar()
            target = data[section][0] if section == 'values' else data[section]
            target[name] = value
            self.assertNotEqual(NS['access_result'](data, 'AAPL', 'XNAS'), 'DAILY_ACCESS_CONFIRMED')

    def test_ohlcv_refusals_and_genuine_zero_volume(self):
        self.assertEqual(NS['access_result'](bar(), 'AAPL', 'XNAS'), 'DAILY_ACCESS_CONFIRMED')
        for name, value in [('open', True), ('open', '0'), ('close', 'NaN'), ('high', '8'),
                            ('low', '12'), ('volume', '-1'), ('volume', '1.5'), ('close', 'offline-canary')]:
            data = bar()
            data['values'][0][name] = value
            self.assertEqual(NS['access_result'](data, 'AAPL', 'XNAS'), 'INVALID_RESPONSE')

    def test_empty_or_multiple_bars_do_not_confirm_access(self):
        for values, expected in [([], 'NO_DATA'), ([bar()['values'][0]] * 2, 'INVALID_RESPONSE')]:
            data = bar()
            data['values'] = values
            self.assertEqual(NS['access_result'](data, 'AAPL', 'XNAS'), expected)

    def test_invalid_future_or_vendor_text_earliest_date_not_published(self):
        for value in ('2026-10-10', '1899-12-31', '2016-02-30', '2016-01-01T00:00:00', 'offline-canary', None, True):
            def fake(endpoint, query, key):
                return 200, raw(bar(query['symbol'], query['mic_code']) if endpoint == '/time_series' else {'datetime': value})
            code, report, output = invoke(fake)
            self.assertEqual(code, 1)
            self.assertTrue(all(r['history'] == 'INVALID_RESPONSE' and r['reported_earliest_date'] is None for r in report['results']))
            self.assertNotIn('offline-canary', output)

    def test_header_auth_no_redirect_and_bounded_read(self):
        requests = []
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, count):
                self_count.append(count)
                return b'{}'
        class Opener:
            def open(self, req, timeout):
                requests.append((req, timeout))
                return Response()
        self_count = []
        with patch.dict(NS, build_opener=lambda *a: Opener()):
            self.assertEqual(NS['request_body']('/earliest_timestamp', {'symbol': 'AAPL', 'interval': '1day'}, 'offline-canary'), (200, b'{}'))
        req, timeout = requests[0]
        self.assertEqual(req.get_header('Authorization'), 'apikey offline-canary')
        self.assertNotIn('offline-canary', req.full_url)
        self.assertTrue(req.full_url.startswith('https://api.twelvedata.com/earliest_timestamp?'))
        self.assertEqual(timeout, 15)
        self.assertEqual(self_count, [65_537])
        self.assertIsNone(NS['NoRedirect']().redirect_request(None, None, 302, '', {}, 'https://example.invalid'))

    def test_transport_exception_does_not_emit_credential(self):
        class Opener:
            def open(self, *args, **kwargs):
                raise RuntimeError('offline-canary')
        with patch.dict(NS, build_opener=lambda *a: Opener()), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(NS['request_body']('/earliest_timestamp', {}, 'offline-canary'), (0, None))
        self.assertEqual(out.getvalue(), '')


if __name__ == '__main__':
    unittest.main()

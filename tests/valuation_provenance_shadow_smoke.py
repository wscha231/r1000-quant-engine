"""Deterministic research-only provenance audit tests: normal and python -O."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'tools' / 'audit_valuation_provenance_shadow.py'
spec = importlib.util.spec_from_file_location('audit_valuation_provenance_shadow', FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

HEADER = ('ticker,rebalance_date,forward_pe_final,forward_pe_source,peg_final,'
          'eps_est_fy1,eps_est_fy2,roic_approx,fcf_ttm\n')

def make_csv(*rows):
    return (HEADER + ''.join(rows)).encode('utf-8')

SAMPLE = 'AAA,2026-06-24,25,ep_ttm,2,1.0,2.0,0.15,120\n'


class AuditTests(unittest.TestCase):
    def test_actual_concentrated_archive_subset(self):
        p = ROOT / 'tests' / 'fixtures' / 'valuation_provenance' / 'concentrated_4rows_extracted.csv'
        out = mod.audit_bytes(p.read_bytes(), source_name=p.name, decision_cutoff='2026-06-24')
        self.assertEqual(out['row_count'], 4)
        self.assertEqual(out['observed_field_presence']['legacy_peg'], 4)
        self.assertEqual(out['observed_field_presence']['forward_pe'], 4)
        self.assertEqual(out['observed_field_presence']['roic_approx'], 0)
        self.assertEqual(out['observed_field_presence']['fcf_ttm'], 4)
        self.assertEqual(out['observed_field_presence']['fcfy_ttm'], 4)
        self.assertEqual(out['status_counts']['forward_peg_v2_status:FY1_FY2_ESTIMATES_MISSING'], 4)
        self.assertEqual(out['status_counts']['pe_status:TRAILING_MISLABELED_FORWARD'], 4)
        self.assertNotIn('pe_status:PROVIDER_ONLY_UNVERIFIED', out['status_counts'])
        self.assertEqual({x['ticker'] for x in out['results']}, {'TKR','AMD','AMAT','WDC'})
        self.assertTrue(all(x['forward_peg_v2'] is None for x in out['results']))

    def test_actual_main_archive_subset(self):
        p = ROOT / 'tests' / 'fixtures' / 'valuation_provenance' / 'main_19rows_extracted.csv'
        out = mod.audit_bytes(p.read_bytes(), source_name=p.name)
        self.assertEqual(out['row_count'], 18)
        self.assertEqual(out['excluded_non_equity_rows'], 1)
        self.assertEqual(out['observed_field_presence']['legacy_peg'], 14)
        self.assertEqual(out['observed_field_presence']['forward_pe'], 18)
        self.assertEqual(out['observed_field_presence']['roic_approx'], 0)
        self.assertEqual(out['observed_field_presence']['fcf_ttm'], 0)
        self.assertEqual(out['observed_field_presence']['fcfy_ttm'], 15)
        self.assertEqual(out['status_counts']['fcfy_status:PRESENT_SOURCE_PROOF_UNVERIFIED'], 15)
        self.assertEqual(out['status_counts']['fcfy_status:MISSING'], 3)
        self.assertLess(next(x['fcfy_ttm'] for x in out['results'] if x['ticker']=='NUE'), 0)
        self.assertTrue(all(x['pe_status'] == 'ORIGIN_UNKNOWN_UNVERIFIED' for x in out['results']))
        self.assertGreater(next(x['legacy_peg'] for x in out['results'] if x['ticker']=='BE'), 70)

    def test_external_expected_checksum_matches(self):
        raw = make_csv(SAMPLE)
        sha = hashlib.sha256(raw).hexdigest()
        self.assertEqual(mod.audit_bytes(raw, expected_sha256=sha)['source_sha256'], sha)

    def test_wrong_checksum_fails(self):
        with self.assertRaisesRegex(mod.AuditInputError, 'SOURCE_BYTES_HASH_MISMATCH'):
            mod.audit_bytes(make_csv(SAMPLE),expected_sha256='a'*64)

    def test_malformed_expected_checksum_fails(self):
        with self.assertRaisesRegex(mod.AuditInputError,'SOURCE_BYTES_HASH_MISMATCH'):
            mod.audit_bytes(make_csv(SAMPLE),expected_sha256='hello')

    def test_current_actual_fy_fields_are_not_native_certification(self):
        row = mod.classify(dict(zip(HEADER.strip().split(','),SAMPLE.strip().split(','))))
        self.assertEqual(row['forward_peg_v2_status'], 'VALUES_PRESENT_NATIVE_IDENTITY_AND_PIT_UNVERIFIED')
        self.assertIsNone(row['forward_peg_v2'])
        self.assertEqual(row['pe_status'], 'TRAILING_MISLABELED_FORWARD')
        self.assertEqual(row['roic_status'],'PROXY_NOT_ACTUAL_ROIC')

    def test_fy2_lower_not_growth(self):
        row = mod.classify({'ticker':'AAA','eps_est_fy1':'3','eps_est_fy2':'2'})
        self.assertEqual(row['forward_peg_v2_status'],'FY1_FY2_NOT_POSITIVE_GROWTH')

    def test_fy1_zero_not_growth(self):
        row = mod.classify({'ticker':'AAA','eps_est_fy1':'0','eps_est_fy2':'2'})
        self.assertEqual(row['forward_peg_v2_status'],'FY1_FY2_NOT_POSITIVE_GROWTH')

    def test_negative_fy1_no_peg(self):
        row = mod.classify({'ticker':'AAA','eps_est_fy1':'-1','eps_est_fy2':'2'})
        self.assertEqual(row['forward_peg_v2_status'],'FY1_FY2_NOT_POSITIVE_GROWTH')

    def test_non_gaap_not_inferred_from_pe(self):
        row = mod.classify({'ticker':'AAA','forward_pe_final':'30','forward_pe_source':'alpha_vantage','peg_final':'0.25'})
        self.assertEqual(row['peg_status'],'LEGACY_PRESENT_UNVERIFIED')
        self.assertEqual(row['pe_status'],'PROVIDER_ONLY_UNVERIFIED')
        self.assertIsNone(row['forward_peg_v2'])

    def test_no_source_pe_stays_unknown(self):
        row=mod.classify({'ticker':'AAA','forward_pe_final':'20'})
        self.assertEqual(row['pe_status'],'ORIGIN_UNKNOWN_UNVERIFIED')

    def test_source_missing_markers_and_real_source_controls(self):
        for source in [None, *mod._INVALID_TOKENS, ' UNKNOWN ', ' NaN ', ' N/A ']:
            with self.subTest(source=source):
                row = mod.classify({'ticker': 'AAA', 'forward_pe_final': '20',
                                    'forward_pe_source': source})
                self.assertEqual(row['pe_status'], 'ORIGIN_UNKNOWN_UNVERIFIED')
                self.assertIsNone(row['forward_pe_source'])
        for source in (' alpha_vantage ', ' FINNHUB ', 'ep_ttm', 'TTM', 'trailing'):
            with self.subTest(source=source):
                row = mod.classify({'ticker': 'AAA', 'forward_pe_final': '20',
                                    'forward_pe_source': source})
                expected = ('PROVIDER_ONLY_UNVERIFIED' if source.strip() == 'alpha_vantage'
                            else 'TRAILING_MISLABELED_FORWARD')
                self.assertEqual(row['pe_status'], expected)
                self.assertEqual(row['forward_pe_source'], source.strip().lower())

    def test_forward_peg_requires_usable_pe_with_positive_growth(self):
        for pe, status in ((None, 'FORWARD_PE_MISSING'), ('nan', 'FORWARD_PE_MISSING'),
                           ('inf', 'FORWARD_PE_MISSING'), ('0', 'FORWARD_PE_NONPOSITIVE_UNUSABLE'),
                           ('-1', 'FORWARD_PE_NONPOSITIVE_UNUSABLE'),
                           ('20', 'VALUES_PRESENT_NATIVE_IDENTITY_AND_PIT_UNVERIFIED')):
            with self.subTest(pe=pe):
                row = mod.classify({'ticker': 'AAA', 'eps_est_fy1': '1',
                                    'eps_est_fy2': '2', 'forward_pe_final': pe})
                self.assertEqual(row['forward_peg_v2_status'], status)
                self.assertIsNone(row['forward_peg_v2'])
                self.assertFalse(row['current_valuation_comparison_allowed'])
        raw = make_csv('AAA,2026-06-24,,,2,1,2,,\n')
        out = mod.audit_bytes(raw)
        self.assertEqual(out['status_counts']['forward_peg_v2_status:FORWARD_PE_MISSING'], 1)

    def test_estimate_blockers_remain_specific_when_pe_is_unusable(self):
        for pe in (None, '0', '20'):
            for fy1, fy2, expected in ((None, '2', 'FY1_FY2_ESTIMATES_MISSING'),
                                       ('1', None, 'FY1_FY2_ESTIMATES_MISSING'),
                                       ('0', '2', 'FY1_FY2_NOT_POSITIVE_GROWTH'),
                                       ('2', '1', 'FY1_FY2_NOT_POSITIVE_GROWTH')):
                with self.subTest(pe=pe, fy1=fy1, fy2=fy2):
                    row = mod.classify({'ticker': 'AAA', 'forward_pe_final': pe,
                                        'eps_est_fy1': fy1, 'eps_est_fy2': fy2})
                    self.assertEqual(row['forward_peg_v2_status'], expected)

    def test_pe_missing_not_zero(self):
        row=mod.classify({'ticker':'AAA','forward_pe_final':'nan'})
        self.assertEqual(row['pe_status'],'MISSING')
        self.assertIsNone(row['forward_pe'])

    def test_pe_zero_unusable(self):
        row=mod.classify({'ticker':'AAA','forward_pe_final':'0'})
        self.assertEqual(row['pe_status'],'NONPOSITIVE_UNUSABLE')
        self.assertEqual(row['forward_pe'],0.0)

    def test_peg_zero_unusable(self):
        row=mod.classify({'ticker':'AAA','peg_final':'0'})
        self.assertEqual(row['peg_status'],'NONPOSITIVE_UNUSABLE')

    def test_peg_negative_unusable(self):
        row=mod.classify({'ticker':'AAA','peg_final':'-1'})
        self.assertEqual(row['peg_status'],'NONPOSITIVE_UNUSABLE')

    def test_peg_nan_missing(self):
        row=mod.classify({'ticker':'AAA','peg_final':'nan'})
        self.assertEqual(row['peg_status'],'MISSING')

    def test_peg_inf_missing(self):
        row=mod.classify({'ticker':'AAA','peg_final':'Inf'})
        self.assertEqual(row['peg_status'],'MISSING')

    def test_peg_large_not_capped(self):
        row=mod.classify({'ticker':'AAA','peg_final':'87.04'})
        self.assertEqual(row['legacy_peg'],87.04)

    def test_roic_missing_not_imputed(self):
        row=mod.classify({'ticker':'AAA'})
        self.assertEqual(row['roic_status'],'MISSING')

    def test_roic_zero_is_proxy(self):
        row=mod.classify({'ticker':'AAA','roic_approx':'0'})
        self.assertEqual(row['roic_status'],'PROXY_NOT_ACTUAL_ROIC')

    def test_fcf_negative_preserved(self):
        row=mod.classify({'ticker':'AAA','fcf_ttm':'-123'})
        self.assertEqual(row['fcf_ttm'],-123)

    def test_fcf_zero_present(self):
        row=mod.classify({'ticker':'AAA','fcf_ttm':'0'})
        self.assertEqual(row['fcf_status'],'PRESENT_SOURCE_PROOF_UNVERIFIED')

    def test_fcf_yield_values_and_missing_inputs_preserved(self):
        for value, expected in ((None, None), ('', None), ('nan', None), ('inf', None),
                                ('0', 0.0), ('-0.01', -0.01), ('0.02', 0.02)):
            with self.subTest(value=value):
                row = mod.classify({'ticker': 'AAA', 'fcfy_ttm': value})
                self.assertEqual(row['fcfy_ttm'], expected)
                self.assertEqual(row['fcfy_status'], 'MISSING' if expected is None
                                 else 'PRESENT_SOURCE_PROOF_UNVERIFIED')
                self.assertIsNone(row['fcf_ttm'])
                self.assertEqual(row['fcf_status'], 'MISSING')
                self.assertFalse(row['current_valuation_comparison_allowed'])
        row = mod.classify({'ticker': 'AAA', 'fcf_ttm': '100', 'fcfy_ttm': '0.02'})
        self.assertEqual(row['fcf_ttm'], 100)
        self.assertEqual(row['fcfy_ttm'], 0.02)

    def test_yield_only_csv_api_and_cli_preserve_independent_metric(self):
        raw = b'ticker,fcfy_ttm\nAAA,0.02\nBBB,-0.01\nCCC,\n'
        out = mod.audit_bytes(raw)
        self.assertEqual(out['observed_field_presence']['fcf_ttm'], 0)
        self.assertEqual(out['observed_field_presence']['fcfy_ttm'], 2)
        self.assertEqual(out['status_counts']['fcfy_status:PRESENT_SOURCE_PROOF_UNVERIFIED'], 2)
        self.assertEqual(out['status_counts']['fcfy_status:MISSING'], 1)
        self.assertEqual([r['fcfy_ttm'] for r in out['results']], [0.02, -0.01, None])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'yield-only.csv'
            path.write_bytes(raw)
            for flags in ([], ['-O']):
                run = subprocess.run([sys.executable, '-B', *flags, str(FILE),
                                      '--input-csv', str(path)], capture_output=True,
                                     text=True, check=False)
                self.assertEqual(run.returncode, 0)
                self.assertEqual(json.loads(run.stdout), mod.audit_bytes(raw, source_name=path.name))
                self.assertEqual(run.stderr, '')

    def test_no_issuer_source_claim(self):
        row=mod.classify({'ticker':'AAA','fund_source':'companyfacts','fcf_ttm':'10'})
        self.assertEqual(row['fundamental_publication_proof'],'NOT_ESTABLISHED_BY_SCORE_CSV')

    def test_bad_ticker_fail(self):
        with self.assertRaisesRegex(mod.AuditInputError,'INVALID_TICKER'):
            mod.classify({'ticker':'BAD:STOCK'})

    def test_empty_csv_fails(self):
        with self.assertRaisesRegex(mod.AuditInputError,'INPUT_BYTE_BUDGET_OR_EMPTY'):
            mod.audit_bytes(b'')

    def test_only_cash_fails(self):
        with self.assertRaisesRegex(mod.AuditInputError,'NO_CANDIDATES'):
            mod.audit_bytes(make_csv('CASH,2026-01-01,,,,,,,\n'))

    def test_row_budget_counts_cash_and_equities(self):
        limit = mod._MAX_ROWS
        payloads = [b'ticker\n' + b'CASH\n' * (limit + 1),
                    b'ticker\n' + b'CASH\n' * limit + b'AAA\n',
                    ('ticker\n' + ''.join(f'CASH\nA{i}\n' for i in range(limit // 2))
                     + 'CASH\n').encode(),
                    ('ticker\n' + ''.join(f'A{i}\n' for i in range(limit + 1))).encode()]
        for raw in payloads:
            with self.subTest(size=len(raw)):
                with self.assertRaisesRegex(mod.AuditInputError, '^ROW_BUDGET_EXCEEDED$'):
                    mod.audit_bytes(raw)

    def test_row_budget_boundary_preserves_candidate_and_cash_counts(self):
        limit = mod._MAX_ROWS
        out = mod.audit_bytes(b'ticker\n' + b'CASH\n' * (limit - 1) + b'AAA\n')
        self.assertEqual(out['row_count'], 1)
        self.assertEqual(out['excluded_non_equity_rows'], limit - 1)
        raw = ('ticker\n' + ''.join(f'A{i}\n' for i in range(limit))).encode()
        self.assertEqual(mod.audit_bytes(raw)['row_count'], limit)
        with self.assertRaisesRegex(mod.AuditInputError, '^NO_CANDIDATES$'):
            mod.audit_bytes(b'ticker\n' + b'CASH\n' * limit)

    def test_cli_cash_rows_exceed_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'cash-over-budget.csv'
            path.write_bytes(b'ticker\n' + b'CASH\n' * (mod._MAX_ROWS + 1))
            for flags in ([], ['-O']):
                run = subprocess.run([sys.executable, '-B', *flags, str(FILE),
                                      '--input-csv', str(path)], capture_output=True,
                                     text=True, check=False)
                self.assertEqual(run.returncode, 2)
                out = json.loads(run.stdout)
                self.assertEqual(out['reason'], 'ROW_BUDGET_EXCEEDED')
                self.assertFalse(out['authority']['ranking_allowed'])
                self.assertEqual(run.stderr, '')

    def test_duplicate_header_fails(self):
        with self.assertRaisesRegex(mod.AuditInputError,'INVALID_OR_DUPLICATE_HEADERS'):
            mod.audit_bytes(b'ticker,ticker\nAAPL,AAPL\n')

    def test_no_ticker_header_fails(self):
        with self.assertRaisesRegex(mod.AuditInputError,'TICKER_COLUMN_REQUIRED'):
            mod.audit_bytes(b'price\n100\n')

    def test_duplicate_security_date_fails(self):
        with self.assertRaisesRegex(mod.AuditInputError,'DUPLICATE_SECURITY_DATE'):
            mod.audit_bytes(make_csv(SAMPLE,SAMPLE))

    def test_future_decision_fails(self):
        with self.assertRaisesRegex(mod.AuditInputError,'FUTURE_ARCHIVED_OBSERVATION'):
            mod.audit_bytes(make_csv(SAMPLE),decision_cutoff='2026-01-01')

    def test_same_day_decision_allowed_for_diag_only(self):
        d=mod.audit_bytes(make_csv(SAMPLE),decision_cutoff='2026-06-24')
        self.assertFalse(d['authority']['source_authenticated'])

    def test_invalid_cutoff_rejected_even_when_absent_dates(self):
        with self.assertRaisesRegex(mod.AuditInputError,'BAD_DECISION_CUTOFF_DATE'):
            mod.audit_bytes(make_csv('AAA,,,,,,,,\n'),decision_cutoff='nonsense')

    def test_observation_dates_validated_without_or_with_cutoff(self):
        for date in ('not-a-date', '2026-6-24', '2026-02-30', ' 2026-06-24',
                     '2026-06-24 ', '20260624', '2026-06-24T00:00:00'):
            for cutoff in (None, '2026-06-24'):
                with self.subTest(date=date, cutoff=cutoff):
                    with self.assertRaisesRegex(mod.AuditInputError, '^BAD_OBSERVATION_DATE$'):
                        mod.audit_bytes(make_csv(SAMPLE.replace('2026-06-24', date)),
                                        decision_cutoff=cutoff)
            with self.assertRaisesRegex(mod.AuditInputError, '^BAD_OBSERVATION_DATE$'):
                mod.classify({'ticker': 'AAA', 'rebalance_date': date})

    def test_observation_date_controls_and_separate_cutoff_error(self):
        for date in ('2024-02-29', '2026-06-24', ''):
            for cutoff in (None, '2026-06-24'):
                with self.subTest(date=date, cutoff=cutoff):
                    out = mod.audit_bytes(make_csv(SAMPLE.replace('2026-06-24', date)),
                                          decision_cutoff=cutoff)
                    self.assertEqual(out['observation_dates'], [date] if date else [])
                    self.assertEqual(out['results'][0]['observation_date'], date or None)
        for cutoff in ('2026-6-24', '2026-02-30', 'not-a-date'):
            with self.assertRaisesRegex(mod.AuditInputError, '^BAD_DECISION_CUTOFF_DATE$'):
                mod.audit_bytes(make_csv(SAMPLE), decision_cutoff=cutoff)

    def test_cli_observation_date_refusal_is_independent_of_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'malformed-date.csv'
            path.write_bytes(make_csv(SAMPLE.replace('2026-06-24', 'not-a-date')))
            for extra in ([], ['--cutoff-date', '2026-06-24']):
                run = subprocess.run([sys.executable, '-B', str(FILE), '--input-csv', str(path),
                                      *extra], capture_output=True, text=True, check=False)
                self.assertEqual(run.returncode, 2)
                self.assertEqual(json.loads(run.stdout)['reason'], 'BAD_OBSERVATION_DATE')
                self.assertEqual(run.stderr, '')

    def test_malformed_csv_extra_field(self):
        with self.assertRaisesRegex(mod.AuditInputError,'MALFORMED_CSV_EXTRA_FIELD'):
            mod.audit_bytes(make_csv('AAA,2026-06-24,20,ep_ttm,1,,,,10,unexpected\n'))

    def test_malformed_csv_short_row(self):
        with self.assertRaisesRegex(mod.AuditInputError,'MALFORMED_CSV_SHORT_ROW'):
            mod.audit_bytes(make_csv('AAA,2026-06-24\n'))

    def test_utf8_decode_failure(self):
        with self.assertRaisesRegex(mod.AuditInputError,'CSV_NOT_UTF8'):
            mod.audit_bytes(b'ticker\nAAA\xff\n')

    def test_unclosed_quote_failure(self):
        with self.assertRaisesRegex(mod.AuditInputError,'CSV_PARSING_FAILURE'):
            mod.audit_bytes(b'ticker\n"AAPL\n')

    def test_unclosed_header_quote_has_structured_api_and_cli_refusal(self):
        raw = b'"ticker\nAAPL\n'
        with self.assertRaisesRegex(mod.AuditInputError, 'CSV_PARSING_FAILURE'):
            mod.audit_bytes(raw)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'malformed.csv'
            path.write_bytes(raw)
            for flags in ([], ['-O']):
                with self.subTest(flags=flags):
                    proc = subprocess.run(
                        [sys.executable, '-B', *flags, str(FILE), '--input-csv', str(path)],
                        capture_output=True, text=True, check=False,
                    )
                    self.assertEqual(proc.returncode, 2)
                    result = json.loads(proc.stdout)
                    self.assertEqual(result['status'], 'BLOCKED')
                    self.assertEqual(result['reason'], 'CSV_PARSING_FAILURE')
                    self.assertFalse(result['authority']['ranking_allowed'])
                    self.assertNotIn('Traceback', proc.stderr)

    def test_size_limit(self):
        with self.assertRaisesRegex(mod.AuditInputError,'INPUT_BYTE_BUDGET_OR_EMPTY'):
            mod.audit_bytes(b'X'*(mod._MAX_BYTES+1))

    def test_cli_sparse_oversize_refusal_before_reading_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'oversize.csv'
            with path.open('wb') as stream:
                stream.truncate(mod._MAX_BYTES + 1)
            run = subprocess.run([sys.executable, '-B', str(FILE), '--input-csv', str(path)],
                                 capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(json.loads(run.stdout)['reason'], 'INPUT_BYTE_BUDGET_OR_EMPTY')
            self.assertEqual(run.stderr, '')
            fake_path = MagicMock()
            with patch.object(mod.os, 'open', return_value=42), \
                 patch.object(mod.os, 'fstat', return_value=SimpleNamespace(
                     st_size=mod._MAX_BYTES + 1, st_mode=mod.stat.S_IFREG)), \
                 patch.object(mod.os, 'fdopen') as fdopen, patch.object(mod.os, 'close') as close:
                with self.assertRaisesRegex(mod.AuditInputError, '^INPUT_BYTE_BUDGET_OR_EMPTY$'):
                    mod._read_input(fake_path)
                fdopen.assert_not_called()
                close.assert_called_once_with(42)

    def test_bounded_read_detects_growth_after_size_check(self):
        raw = make_csv(SAMPLE)
        fake_path = MagicMock()
        manager = MagicMock()
        fake_stream = manager.__enter__.return_value
        fake_stream.read.side_effect = lambda limit: (raw + b'x')[:limit]
        with patch.object(mod, '_MAX_BYTES', len(raw)), \
             patch.object(mod.os, 'open', return_value=42) as opened, \
             patch.object(mod.os, 'fstat', return_value=SimpleNamespace(
                 st_size=len(raw), st_mode=mod.stat.S_IFREG)), \
             patch.object(mod.os, 'fdopen', return_value=manager), patch.object(mod.os, 'close') as close:
            with self.assertRaisesRegex(mod.AuditInputError, '^INPUT_BYTE_BUDGET_OR_EMPTY$'):
                mod._read_input(fake_path)
            close.assert_not_called()
            opened.assert_called_once_with(fake_path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
        fake_stream.read.assert_called_once_with(len(raw) + 1)
        manager.__exit__.assert_called_once()

    def test_bounded_read_exact_limit_and_empty_controls(self):
        raw = make_csv(SAMPLE)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.csv'
            path.write_bytes(raw)
            with patch.object(mod, '_MAX_BYTES', len(raw)):
                self.assertEqual(mod._read_input(path), raw)
                self.assertEqual(mod.audit_bytes(mod._read_input(path))['row_count'], 1)
            path.write_bytes(b'')
            with self.assertRaisesRegex(mod.AuditInputError, '^INPUT_BYTE_BUDGET_OR_EMPTY$'):
                mod._read_input(path)

    def test_cli_read_failures_redact_private_path(self):
        with tempfile.TemporaryDirectory(prefix='private-account-marker-') as tmp:
            for path, reason in ((Path(tmp) / 'missing-token-marker.csv', 'INPUT_READ_FAILURE'),
                                 (Path(tmp), 'INPUT_NOT_REGULAR_FILE')):
                run = subprocess.run([sys.executable, '-B', str(FILE), '--input-csv', str(path)],
                                     capture_output=True, text=True, check=False)
                self.assertEqual(run.returncode, 2)
                result = json.loads(run.stdout)
                self.assertEqual(result['reason'], reason)
                self.assertFalse(result['authority']['orders_allowed'])
                self.assertNotIn(tmp, run.stdout)
                self.assertNotIn('private-account-marker', run.stdout)
                self.assertNotIn('token-marker', run.stdout)
                self.assertEqual(run.stderr, '')
        with patch.object(mod, '_read_input', side_effect=PermissionError('private-denied-marker')), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(mod.main(['--input-csv', '/private-denied-marker/file.csv']), 2)
            self.assertEqual(json.loads(output.getvalue())['reason'], 'INPUT_READ_FAILURE')
            self.assertNotIn('private-denied-marker', output.getvalue())

    def test_failed_open_classifies_only_proven_directory_without_path_leak(self):
        path = Path('synthetic-private-directory-marker')
        failure = PermissionError('synthetic-private-open-marker')
        with patch.object(mod.os, 'open', side_effect=failure), \
             patch.object(mod.os, 'stat', return_value=SimpleNamespace(st_mode=mod.stat.S_IFDIR)) as probe, \
             patch.object(mod.os, 'fstat') as fstat, patch.object(mod.os, 'close') as close:
            with self.assertRaisesRegex(mod.AuditInputError, '^INPUT_NOT_REGULAR_FILE$'):
                mod._read_input(path)
            probe.assert_called_once_with(path)
            fstat.assert_not_called()
            close.assert_not_called()
            with patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(mod.main(['--input-csv', str(path)]), 2)
            result = json.loads(output.getvalue())
            self.assertEqual(result['reason'], 'INPUT_NOT_REGULAR_FILE')
            self.assertFalse(result['authority']['orders_allowed'])
            self.assertNotIn('synthetic-private', output.getvalue())

    def test_non_directory_open_failures_preserve_original_error(self):
        path = Path('synthetic-private-file-marker')
        for failure in (FileNotFoundError('synthetic-private-missing'),
                        PermissionError('synthetic-private-denied'), OSError('synthetic-private-io')):
            for probe in (SimpleNamespace(st_mode=mod.stat.S_IFREG),
                          SimpleNamespace(st_mode=mod.stat.S_IFLNK),
                          SimpleNamespace(st_mode=mod.stat.S_IFIFO),
                          FileNotFoundError('synthetic-private-probe-missing'),
                          PermissionError('synthetic-private-probe-denied')):
                with self.subTest(error=type(failure).__name__, probe=type(probe).__name__), \
                     patch.object(mod.os, 'open', side_effect=failure), \
                     patch.object(mod.os, 'stat', side_effect=probe if isinstance(probe, OSError) else None,
                                  return_value=probe), \
                     patch.object(mod.os, 'fstat') as fstat, patch.object(mod.os, 'close') as close:
                    with self.assertRaises(type(failure)) as caught:
                        mod._read_input(path)
                    self.assertIs(caught.exception, failure)
                    fstat.assert_not_called()
                    close.assert_not_called()
                    with patch('sys.stdout', new_callable=io.StringIO) as output:
                        self.assertEqual(mod.main(['--input-csv', str(path)]), 2)
                    self.assertEqual(json.loads(output.getvalue())['reason'], 'INPUT_READ_FAILURE')
                    self.assertNotIn('synthetic-private', output.getvalue())

    def test_successful_open_still_requires_regular_descriptor_and_closes(self):
        for mode in (mod.stat.S_IFDIR, mod.stat.S_IFIFO, mod.stat.S_IFLNK):
            with self.subTest(mode=mode), patch.object(mod.os, 'open', return_value=42), \
                 patch.object(mod.os, 'stat') as probe, \
                 patch.object(mod.os, 'fstat', return_value=SimpleNamespace(st_mode=mode, st_size=0)), \
                 patch.object(mod.os, 'fdopen') as fdopen, patch.object(mod.os, 'close') as close:
                with self.assertRaisesRegex(mod.AuditInputError, '^INPUT_NOT_REGULAR_FILE$'):
                    mod._read_input(Path('synthetic-private-special-marker'))
                probe.assert_not_called()
                fdopen.assert_not_called()
                close.assert_called_once_with(42)

    def test_real_symlinks_keep_regular_directory_and_missing_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            regular = root / 'regular.csv'
            regular.write_bytes(make_csv(SAMPLE))
            link = root / 'regular-link.csv'
            try:
                link.symlink_to(regular)
            except OSError:
                self.skipTest('OS symlink creation unavailable')
            self.assertEqual(mod._read_input(link), regular.read_bytes())
            directory_link = root / 'directory-link'
            directory_link.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(mod.AuditInputError, '^INPUT_NOT_REGULAR_FILE$'):
                mod._read_input(directory_link)
            broken = root / 'broken-link'
            broken.symlink_to(root / 'absent.csv')
            with self.assertRaises(OSError):
                mod._read_input(broken)

    def test_csv_record_and_column_budgets(self):
        for raw in (b'ticker,' + b',' * mod._MAX_RECORD_CHARS + b'\nAAA,1\n',
                    b'ticker,"' + b'a\n' * mod._MAX_RECORD_CHARS + b'"\nAAA,1\n',
                    b'ticker\nAAA' + b',x' * mod._MAX_RECORD_CHARS + b'\n'):
            with self.assertRaisesRegex(mod.AuditInputError, '^CSV_RECORD_CHARACTER_BUDGET_EXCEEDED$'):
                mod.audit_bytes(raw)
        columns = ['ticker'] + [f'field{i}' for i in range(mod._MAX_COLUMNS - 1)]
        valid = (','.join(columns) + '\nAAA' + ',' * (len(columns) - 1) + '\n').encode()
        self.assertEqual(mod.audit_bytes(valid)['row_count'], 1)
        with self.assertRaisesRegex(mod.AuditInputError, '^CSV_COLUMN_BUDGET_EXCEEDED$'):
            mod.audit_bytes((','.join(columns + ['extra']) + '\nAAA\n').encode())

    def test_csv_quoted_multiline_and_blank_record_controls(self):
        raw = b'ticker,"unused,\nheader"\n\nAAA,"two\nlines"\n\n'
        self.assertEqual(mod.audit_bytes(raw)['row_count'], 1)
        boundary = b'ticker\n' + b'\n' * (mod._MAX_ROWS - 1) + b'AAA\n'
        self.assertEqual(mod.audit_bytes(boundary)['row_count'], 1)
        with self.assertRaisesRegex(mod.AuditInputError, '^ROW_BUDGET_EXCEEDED$'):
            mod.audit_bytes(b'ticker\n' + b'\n' * mod._MAX_ROWS + b'AAA\n')

    def test_cli_oversized_header_has_structured_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'wide-header.csv'
            path.write_bytes(b'ticker,' + b',' * mod._MAX_RECORD_CHARS + b'\nAAA,1\n')
            for flags in ([], ['-O']):
                run = subprocess.run([sys.executable, '-B', *flags, str(FILE), '--input-csv',
                                      str(path)], capture_output=True, text=True, check=False, timeout=3)
                self.assertEqual(run.returncode, 2)
                self.assertEqual(json.loads(run.stdout)['reason'], 'CSV_RECORD_CHARACTER_BUDGET_EXCEEDED')
                self.assertEqual(run.stderr, '')

    @unittest.skipUnless(hasattr(os, 'mkfifo') and hasattr(os, 'O_NONBLOCK'), 'Unix FIFO control')
    def test_cli_special_inputs_refuse_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            fifo = Path(tmp) / 'no-writer.fifo'
            os.mkfifo(fifo)
            link = Path(tmp) / 'fifo-link'
            link.symlink_to(fifo)
            valid = Path(tmp) / 'regular.csv'
            valid.write_bytes(make_csv(SAMPLE))
            valid_link = Path(tmp) / 'regular-link.csv'
            valid_link.symlink_to(valid)
            for path in (fifo, link, Path(tmp), Path('/dev/null')):
                for flags in ([], ['-O']):
                    run = subprocess.run([sys.executable, '-B', *flags, str(FILE), '--input-csv',
                                          str(path)], capture_output=True, text=True, check=False, timeout=3)
                    self.assertEqual(run.returncode, 2)
                    self.assertEqual(json.loads(run.stdout)['reason'], 'INPUT_NOT_REGULAR_FILE')
                    self.assertEqual(run.stderr, '')
            self.assertEqual(mod._read_input(valid_link), valid.read_bytes())

    def test_source_category_redaction_and_known_label_controls(self):
        for value in ('Authorization: Bearer synthetic-private-marker', 'api_key=synthetic-private-marker',
                      'sk-proj-synthetic-private-marker', 'unknown_provider', 'x' * 65, None):
            row = mod.classify({'ticker': 'AAA', 'forward_pe_final': '20',
                                'forward_pe_source': value, 'fund_source': value})
            self.assertIsNone(row['forward_pe_source'])
            self.assertIsNone(row['fundamental_source'])
            self.assertEqual(row['pe_status'], 'ORIGIN_UNKNOWN_UNVERIFIED')
            self.assertNotIn('synthetic-private-marker', json.dumps(row))
        row = mod.classify({'ticker': 'AAA', 'forward_pe_final': '20',
                            'forward_pe_source': ' ALPHA_VANTAGE ', 'fund_source': ' COMPANYFACTS '})
        self.assertEqual(row['forward_pe_source'], 'alpha_vantage')
        self.assertEqual(row['fundamental_source'], 'companyfacts')
        self.assertEqual(row['pe_status'], 'PROVIDER_ONLY_UNVERIFIED')

    def test_cli_source_categories_never_echo_unknown_values(self):
        raw = (b'ticker,forward_pe_final,forward_pe_source,fund_source\n'
               b'AAA,20,Authorization: Bearer synthetic-private-marker,api_key=synthetic-private-marker\n')
        out = mod.audit_bytes(raw)
        self.assertIsNone(out['results'][0]['fundamental_source'])
        self.assertIsNone(out['results'][0]['forward_pe_source'])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'redaction.csv'
            path.write_bytes(raw)
            for flags in ([], ['-O']):
                run = subprocess.run([sys.executable, '-B', *flags, str(FILE), '--input-csv', str(path)],
                                     capture_output=True, text=True, check=False)
                self.assertEqual(run.returncode, 0)
                self.assertNotIn('synthetic-private-marker', run.stdout)
                self.assertEqual(json.loads(run.stdout), mod.audit_bytes(raw, source_name=path.name))
                self.assertEqual(run.stderr, '')

    def test_regular_descriptor_closes_after_read_and_size_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.csv'
            captured = []
            original_open = os.open
            def capture(*args, **kwargs):
                descriptor = original_open(*args, **kwargs)
                captured.append(descriptor)
                return descriptor
            path.write_bytes(make_csv(SAMPLE))
            with patch.object(mod.os, 'open', side_effect=capture):
                self.assertEqual(mod._read_input(path), make_csv(SAMPLE))
            with self.assertRaises(OSError):
                os.fstat(captured[-1])
            with path.open('wb') as stream:
                stream.truncate(mod._MAX_BYTES + 1)
            with patch.object(mod.os, 'open', side_effect=capture):
                with self.assertRaisesRegex(mod.AuditInputError, '^INPUT_BYTE_BUDGET_OR_EMPTY$'):
                    mod._read_input(path)
            with self.assertRaises(OSError):
                os.fstat(captured[-1])

    def test_no_fallback_valuation(self):
        d=mod.audit_bytes(make_csv(SAMPLE))
        for x in d['results']:
            self.assertIsNone(x['forward_peg_v2'])
            self.assertFalse(x['ranking_effect_allowed'])

    def test_authority_immutable(self):
        d=mod.audit_bytes(make_csv(SAMPLE))
        self.assertEqual(d['authority']['portfolio_weight_effect'],0)
        for f in ['orders_allowed','ranking_allowed','historical_pit_certified','er_calculated', 'backtest_acceptance_allowed']:
            self.assertIs(d['authority'][f],False)

    def test_hash_determinism(self):
        self.assertEqual(mod.audit_bytes(make_csv(SAMPLE)),mod.audit_bytes(make_csv(SAMPLE)))

    def test_archived_unverified_values_cannot_authorize_current_comparison(self):
        d=mod.audit_bytes(make_csv(SAMPLE))
        self.assertEqual(d['source_scope'], 'ARCHIVED_RESEARCH_CSV_DIAGNOSTIC_ONLY')
        self.assertFalse(d['results'][0]['current_valuation_comparison_allowed'])
        self.assertFalse(d['results'][0]['ranking_effect_allowed'])

    def test_source_name_basename_only(self):
        d=mod.audit_bytes(make_csv(SAMPLE),source_name='/secret/private/name.csv')
        self.assertEqual(d['source_name'],'name.csv')

    def test_cli_real_archived_csv_success(self):
        p=ROOT/'tests'/'fixtures'/'valuation_provenance'/'concentrated_4rows_extracted.csv'
        run=subprocess.run([sys.executable,str(FILE),'--input-csv',str(p),'--cutoff-date','2026-06-24'],capture_output=True,text=True,check=False)
        self.assertEqual(run.returncode,0,run.stderr)
        d=json.loads(run.stdout)
        self.assertEqual(d['row_count'],4)
        self.assertEqual(d['status_counts']['peg_status:LEGACY_PRESENT_UNVERIFIED'],4)

    def test_cli_bad_hash_blocked(self):
        p=ROOT/'tests'/'fixtures'/'valuation_provenance'/'concentrated_4rows_extracted.csv'
        run=subprocess.run([sys.executable,str(FILE),'--input-csv',str(p),'--expected-sha256','a'*64],capture_output=True,text=True,check=False)
        self.assertEqual(run.returncode,2)
        d=json.loads(run.stdout)
        self.assertEqual(d['status'],'BLOCKED')
        self.assertFalse(d['authority']['orders_allowed'])


if __name__=='__main__':
    unittest.main(verbosity=2)

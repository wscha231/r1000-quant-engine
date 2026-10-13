"""Deterministic research-only provenance audit tests: normal and python -O."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

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
        self.assertEqual(out['status_counts']['forward_peg_v2_status:FY1_FY2_ESTIMATES_MISSING'], 4)
        self.assertEqual(out['status_counts']['pe_status:TRAILING_MISLABELED_FORWARD'], 1)
        self.assertEqual(out['status_counts']['pe_status:PROVIDER_ONLY_UNVERIFIED'], 3)
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
        row = mod.classify({'ticker':'AAA','forward_pe_final':'30','forward_pe_source':'finnhub','peg_final':'0.25'})
        self.assertEqual(row['peg_status'],'LEGACY_PRESENT_UNVERIFIED')
        self.assertEqual(row['pe_status'],'PROVIDER_ONLY_UNVERIFIED')
        self.assertIsNone(row['forward_peg_v2'])

    def test_no_source_pe_stays_unknown(self):
        row=mod.classify({'ticker':'AAA','forward_pe_final':'20'})
        self.assertEqual(row['pe_status'],'ORIGIN_UNKNOWN_UNVERIFIED')

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

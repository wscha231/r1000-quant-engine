"""Offline invariant tests; synthetic fixtures are never performance evidence."""
from copy import deepcopy
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('subscription_readiness', ROOT / 'tools/subscription_manager/readiness.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture():
    cohort = {'data_kind': 'REAL', 'candidate_count': 1001, 'as_of': '2026-09-09', 'rows': []}
    financials = {'schema_version': 'whole-cohort-financial-coverage-v1', 'data_kind': 'REAL_CURRENT_OBSERVATIONS',
        'requested_securities': 1001, 'filing_cutoff_date': '2026-09-11', 'analysis_at': '2026-09-12T01:00:00+00:00',
        'cohort_price_as_of': '2026-09-09', 'orders_allowed': False, 'portfolio_weights': None, 'rows': []}
    fact = {'accn': '0000000001-26-000001', 'namespace': 'us-gaap', 'tag': 'Revenues', 'currency': 'USD',
            'start': '2026-04-01', 'end': '2026-06-30', 'filed': '2026-08-01', 'val': 0}
    for n in range(1001):
        cohort['rows'].append({'ticker': 'T' + str(n), 'sector': 'Synthetic sector', 'horizons': {}})
        financials['rows'].append({'ticker': 'T' + str(n), 'cik': str(n + 1).zfill(10), 'status': 'COLLECTED',
            'raw_sha256': 'a' * 64, 'financials': {'current_quarter_usable': True, 'quarter_end': '2026-06-30',
            'fcf_ttm': 0, 'revenue_yoy': 0, 'revenue_growth_acceleration_pp': None}})
    financials['rows'][0]['financials']['revenue_source'] = fact
    return cohort, financials


def build(c, f, **kwargs):
    ch = m.digest(m.canonical(c))
    f['cohort_sha256'] = ch
    fh = m.digest(m.canonical(f))
    return m.build(c, f, ch, fh, '2026-09-13T00:00:00+00:00', **kwargs)


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.c, self.f = fixture()

    def test_complete_identity_not_subscription_release(self):
        r = build(self.c, self.f)
        self.assertEqual(r['coverage']['requested_securities'], 1001)
        self.assertFalse(r['subscription_release_allowed'])
        self.assertFalse(r['orders_allowed'])
        self.assertIsNone(r['performance'])
        self.assertIsNone(r['portfolio_weights'])

    def test_real_zero_is_observed(self):
        r = build(self.c, self.f)
        self.assertEqual(r['coverage']['fcf_ttm_observed'], 1001)
        self.assertEqual(r['retained_facts'][0]['value'], '0')

    def test_integer_date_not_1970(self):
        self.assertEqual(m.date_value(20260630), '2026-06-30')
        self.assertEqual(m.date_value('20260630'), '2026-06-30')

    def test_bad_dates_rejected(self):
        for v in [True, 20260230, 20260630.0, '0', '2026-6-3', None]:
            with self.subTest(v=v), self.assertRaises(ValueError):
                m.date_value(v)

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            m.timestamp('2026-09-13T00:00:00')

    def test_missing_identity_stays_in_denominator(self):
        self.f['rows'][0] = {'ticker': 'T0', 'status': 'MISSING_IDENTITY', 'reason': 'CIK_MISSING'}
        r = build(self.c, self.f)
        self.assertEqual(len(r['security_rows']), 1001)
        self.assertEqual(r['coverage']['collected_securities'], 1000)
        self.assertEqual(r['issuer_queue'][0]['first_action'], 'RESOLVE_IDENTITY')

    def test_share_classes_deduplicate_issuer_requests(self):
        self.f['rows'][1]['cik'] = self.f['rows'][0]['cik']
        r = build(self.c, self.f)
        self.assertEqual(r['coverage']['mapped_unique_issuers'], 1000)
        self.assertEqual(r['issuer_queue'][0]['tickers'], ['T0', 'T1'])

    def test_mismatching_symbol_sets_fail(self):
        self.f['rows'][0]['ticker'] = 'MISSING'
        with self.assertRaisesRegex(ValueError, 'identity_mismatch'): build(self.c, self.f)

    def test_duplicate_symbols_fail(self):
        self.c['rows'][1]['ticker'] = 'T0'
        with self.assertRaisesRegex(ValueError, 'duplicate_security'): build(self.c, self.f)

    def test_small_watchlist_cannot_impersonate_universe(self):
        self.c['rows'] = self.c['rows'][:8]
        self.f['rows'] = self.f['rows'][:8]
        with self.assertRaisesRegex(ValueError, 'broad_universe'): build(self.c, self.f)

    def test_counts_must_reconcile(self):
        self.c['candidate_count'] += 1
        with self.assertRaisesRegex(ValueError, 'count_mismatch'): build(self.c, self.f)

    def test_synthetic_source_cannot_launder(self):
        self.c['data_kind'] = 'SYNTHETIC'
        with self.assertRaisesRegex(ValueError, 'real_data'): build(self.c, self.f)

    def test_future_observation_rejected(self):
        self.f['analysis_at'] = '2026-09-14T00:00:00Z'
        with self.assertRaisesRegex(ValueError, 'future_input'): build(self.c, self.f)

    def test_future_filing_rejected(self):
        self.f['rows'][0]['financials']['revenue_source']['filed'] = '2026-09-12'
        with self.assertRaisesRegex(ValueError, 'availability'): build(self.c, self.f)

    def test_period_timestamp_is_not_acceptance_time(self):
        r = build(self.c, self.f)
        self.assertIsNone(r['retained_facts'][0]['accepted_at'])
        self.assertEqual(r['retained_facts'][0]['observed_at'], '2026-09-12T01:00:00+00:00')
        self.assertFalse(r['retained_facts'][0]['historical_pit_verified'])

    def test_old_quarter_count_is_not_history_coverage(self):
        self.f['rows'][0]['financials']['quarters_observed'] = 99
        r = build(self.c, self.f)
        self.assertIsNone(r['coverage']['historical_cell_coverage'])
        self.assertIsNone(r['security_rows'][0]['history_coverage'])

    def test_duplicate_excerpt_not_double_counted(self):
        first = self.f['rows'][0]['financials']
        first['ttm'] = {'revenue': {'components': [deepcopy(first['revenue_source'])]}}
        r = build(self.c, self.f)
        self.assertEqual(len(r['retained_facts']), 1)

    def test_conflicting_same_accession_fails(self):
        first = self.f['rows'][0]['financials']
        newer = {**first['revenue_source'], 'val': 10}
        first['ttm'] = {'revenue': {'components': [newer]}}
        with self.assertRaisesRegex(ValueError, 'conflicting_fact'): build(self.c, self.f)

    def test_amended_versions_both_retained_not_backdated(self):
        first = self.f['rows'][0]['financials']
        revision = {**first['revenue_source'], 'val': 10, 'accn': '0000000001-26-000002', 'filed': '2026-09-01'}
        first['amended_excerpt'] = revision
        r = build(self.c, self.f)
        self.assertEqual(len(r['retained_facts']), 2)
        self.assertEqual({o['filed_date'] for o in r['retained_facts']}, {'2026-08-01','2026-09-01'})
        self.assertTrue(all(o['accepted_at'] is None for o in r['retained_facts']))

    def test_cross_currency_not_merged(self):
        first = self.f['rows'][0]['financials']
        first['local_excerpt'] = {**first['revenue_source'], 'currency': 'TWD', 'val': 100}
        self.assertEqual(len(build(self.c, self.f)['retained_facts']), 2)

    def test_string_boolean_not_a_valid_quarter(self):
        self.f['rows'][0]['financials']['current_quarter_usable'] = 'true'
        with self.assertRaisesRegex(ValueError, 'packet'): build(self.c, self.f)

    def test_boolean_value_rejected(self):
        self.f['rows'][0]['financials']['revenue_source']['val'] = True
        with self.assertRaisesRegex(ValueError, 'numeric'): build(self.c, self.f)

    def test_rs_end_date_mismatch(self):
        self.c['rows'][0]['horizons']['20'] = {'status': 'available', 'end': '2026-09-08'}
        with self.assertRaisesRegex(ValueError, 'rs_end'): build(self.c, self.f)

    def test_price_financial_lineage_dates_mismatch(self):
        self.f['cohort_price_as_of'] = '2026-09-08'
        with self.assertRaisesRegex(ValueError, 'lineage_date'): build(self.c, self.f)

    def test_export_roundtrip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base) / 'original'
            r = build(self.c, self.f)
            inputs = {'cohort': m.canonical(self.c), 'financials': m.canonical(self.f)}
            m.export(r, root, inputs)
            pinned = m.digest((root/'export_manifest.json').read_bytes())
            copied = Path(base)/'restored'
            shutil.copytree(root, copied)
            proof = m.verify_export(copied, pinned)
            self.assertGreater(proof['verified_files'], 5)
            self.assertFalse(proof['subscription_release_allowed'])
            with closing(sqlite3.connect(copied/'private/observations.sqlite')) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM securities').fetchone()[0], 1001)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM fact_versions WHERE accepted_at IS NOT NULL').fetchone()[0], 0)
            with self.assertRaisesRegex(ValueError, 'new_output'): m.export(r, root, inputs)

    def test_tamper_detected_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as base:
            root=Path(base)/'original'
            r=build(self.c,self.f)
            m.export(r,root,{'cohort':m.canonical(self.c),'financials':m.canonical(self.f)})
            pinned=m.digest((root/'export_manifest.json').read_bytes())
            (root/'readiness.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'member_hash'): m.verify_export(root,pinned)

    def test_manifest_is_pinned_not_self_trusted(self):
        with tempfile.TemporaryDirectory() as base:
            root=Path(base)/'original'
            r=build(self.c,self.f)
            m.export(r,root,{'cohort':m.canonical(self.c),'financials':m.canonical(self.f)})
            with self.assertRaisesRegex(ValueError,'input_hash'):m.verify_export(root,'0'*64)

    def test_unlisted_file_rejected(self):
        with tempfile.TemporaryDirectory() as base:
            root=Path(base)/'original'
            r=build(self.c,self.f)
            m.export(r,root,{'cohort':m.canonical(self.c),'financials':m.canonical(self.f)})
            pinned=m.digest((root/'export_manifest.json').read_bytes())
            (root/'secret.txt').write_text('synthetic')
            with self.assertRaisesRegex(ValueError,'unlisted'):m.verify_export(root,pinned)

    def test_symlink_output_rejected(self):
        with tempfile.TemporaryDirectory() as base:
            root=Path(base)/'link'
            root.symlink_to(Path(base),target_is_directory=True)
            r=build(self.c,self.f)
            with self.assertRaisesRegex(ValueError,'symlink'):m.export(r,root/'child',{})

    def test_pinned_json_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as base:
            path=Path(base)/'input.json';raw=b'{"a":1,"a":2}'
            path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError,'duplicate_json'):m.read_pinned(path,m.digest(raw))

    def test_pinned_json_rejects_nan(self):
        with tempfile.TemporaryDirectory() as base:
            path=Path(base)/'input.json';raw=b'{"a":NaN}'
            path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError,'nonfinite_json'):m.read_pinned(path,m.digest(raw))

    def test_wrong_input_hash(self):
        with tempfile.TemporaryDirectory() as base:
            path=Path(base)/'input.json';path.write_text('{}')
            with self.assertRaisesRegex(ValueError,'hash_mismatch'):m.read_pinned(path,'f'*64)

    def test_nested_unlisted_manifest_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as base:
            root=Path(base)/'original'
            r=build(self.c,self.f)
            m.export(r,root,{'cohort':m.canonical(self.c),'financials':m.canonical(self.f)})
            pinned=m.digest((root/'export_manifest.json').read_bytes())
            (root/'private/export_manifest.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'unlisted'):m.verify_export(root,pinned)

    def test_source_commit_and_config_are_explicit(self):
        r=build(self.c,self.f,source_commit='a'*40)
        self.assertEqual(r['source_commit'],'a'*40)
        self.assertEqual(len(r['config_sha256']),64)
        with self.assertRaisesRegex(ValueError,'source_commit'):build(self.c,self.f,source_commit='master')

    def test_extra_input_bytes_are_not_exported(self):
        with tempfile.TemporaryDirectory() as base:
            r=build(self.c,self.f)
            with self.assertRaisesRegex(ValueError,'unexpected_source'):
                m.export(r,Path(base)/'new',{'cohort':m.canonical(self.c),'financials':m.canonical(self.f),'other':b'fixture'})

    def test_program_contains_no_network_or_trade_clients(self):
        import ast
        code=(ROOT/'tools/subscription_manager/readiness.py').read_text()
        tree=ast.parse(code)
        imported=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):imported.extend(a.name.split('.')[0] for a in node.names)
            if isinstance(node,ast.ImportFrom):imported.append(node.module.split('.')[0])
        self.assertFalse(set(imported)&{'requests','urllib','http','socket','alpaca','openai','subprocess'})


if __name__=='__main__':
    unittest.main()

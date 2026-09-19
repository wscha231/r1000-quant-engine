"""Synthetic fault injection for real-archive admission, never performance."""
from copy import deepcopy
import gzip
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.long_history_lake import Lake, LocalTransport, diagnostics, issuer_queue, fact_coverage
from tools.macro_history_sources import digest, encoded
from tools.subscription_manager.history_adapter import (
    build_input, prepare_history, ReadOnlyTransport, ReadOnlyRcloneTransport, read_pinned,
)
from tools.subscription_manager.run_model_cycle import run
from tools.subscription_manager.continuous import ZERO

SOURCE = '1' * 40
AT = '2026-01-06T09:00:00+00:00'
DECISION = '2026-01-06T12:00:00+00:00'


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / 'archive'
        self.transport = LocalTransport(self.archive)
        self.cohort = self.root / 'cohort.json'
        self.rows = [dict(security_id=f'US:T{i}', ticker=f'T{i}') for i in range(1000)]
        self.payload = dict(rows=self.rows, candidate_count=1000, as_of='2026-01-05')
        self.raw = encoded(self.payload)
        self.cohort.write_bytes(self.raw)
        self.mapping = {str(i): dict(ticker=f'T{i}', cik_str=1 if i < 500 else 2)
                        for i in range(998)}

    def fixture(self, mutate=None, study=True, quality_mutate=None):
        with patch('tools.long_history_lake.utc_now', return_value=AT), \
             patch.dict(os.environ, {'GITHUB_SHA': SOURCE}):
            lake = Lake(self.transport, self.root / 'writer')
            groups, missing = issuer_queue(self.rows, self.mapping)
            lake.dataset('universe/cohort', [self.raw, encoded(self.mapping)], self.rows,
                dict(evidence='CURRENT_COHORT_NOT_HISTORICAL_MEMBERSHIP', rows=1000,
                     requested_securities=1000, mapped_issuers=len(groups), missing=missing,
                     active_issuer_keys=sorted('sec/' + key for key in groups)))
            for cik, tickers in groups.items():
                records = [dict(end='2025-09-30', filed='2025-11-01', start='2025-01-01',
                                duration_days=273, unit='USD', concept='Revenue', value=100,
                                evidence='SEC_FILED_DATE_CURRENT_ARCHIVE_NOT_CERTIFIED_PIT')]
                lake.dataset('sec/' + cik, [b'fixture-' + cik.encode()], records,
                    dict(cik=cik, tickers=tickers, retrieved_at=AT, through='2026-01-06',
                         evidence='SEC_FILED_DATE_CURRENT_ARCHIVE_NOT_CERTIFIED_PIT',
                         **fact_coverage(records, '2016-01-01', '2026-01-06')))
            if mutate:
                mutate(lake)
            quality = diagnostics(lake)
            if quality_mutate:
                quality_mutate(quality)
            result = lake.publish('fixture', dict(cohort_sha256=digest(self.raw),
                                  financial_start='2016-01-01', through='2026-01-06'))
            report_raw = encoded(quality)
            self.transport.write('long-history-v1/reports/' + digest(report_raw), report_raw)
            execution = dict(schema='long-history-execution-v1', run_id='fixture', created_at=AT,
                commit_sha256=result['commit_sha256'], catalog_sha256=result['catalog_sha256'],
                reports={'quality.json': digest(report_raw)}, consumer_rows=0,
                study_recomputed_from_drive=study, quality_status=quality['status'],
                eligible_for_selector=False)
            execution_raw = encoded(execution)
            self.execution = digest(execution_raw)
            self.transport.write('long-history-v1/executions/' + self.execution, execution_raw)
            self.args = dict(cohort=self.cohort, cohort_sha256=digest(self.raw),
                commit_sha256=result['commit_sha256'], catalog_sha256=result['catalog_sha256'],
                execution_sha256=self.execution, source_commit=SOURCE, decision_at=DECISION)
        return Lake(ReadOnlyTransport(self.transport), self.root / 'reader')

    def build(self, lake, **overrides):
        return build_input(lake, **(self.args | overrides))

    def test_whole_cohort_and_missing_are_preserved(self):
        result = self.build(self.fixture())
        self.assertEqual(len(result['securities']), 1000)
        self.assertEqual(result['coverage']['mapped_issuers'], 2)
        self.assertEqual(result['coverage']['securities_research_readable'], 998)
        self.assertEqual(sum(row['cik'] is None for row in result['securities']), 2)
        self.assertEqual(result['status'], 'PARTIAL_RESEARCH_INPUT')
        self.assertFalse(result['provenance']['remote_verified'])
        self.assertFalse(result['historical_training_allowed'])
        self.assertFalse(result['model_execution_allowed'])

    def test_partial_policy_cannot_silently_pass_complete(self):
        lake = self.fixture()
        with self.assertRaisesRegex(ValueError, 'partial_history'):
            self.build(lake, partial_policy='reject')

    def test_stale_execution(self):
        lake = self.fixture()
        with self.assertRaisesRegex(ValueError, 'stale_execution'):
            self.build(lake, decision_at='2026-01-10T12:00:00Z')

    def test_stale_dataset_not_hidden_by_fresh_execution(self):
        def stale(lake):
            lake.catalog['datasets']['sec/0000000001'].update(
                checked_at='2026-01-01T09:00:00Z', retrieved_at='2026-01-01T09:00:00Z')
        lake = self.fixture(mutate=stale)
        result = self.build(lake)
        self.assertEqual(result['coverage']['securities_research_readable'], 498)
        with self.assertRaisesRegex(ValueError, 'required_dataset_unavailable'):
            self.build(lake, required_datasets=['sec/0000000001'])

    def test_stale_retained_and_blocked_never_consumed(self):
        def blocked(lake):
            lake.blocked('sec/0000000001', ValueError('HTTP_404'))
            lake.catalog['datasets']['sec/0000000002'] = dict(status='BLOCKED', checked_at=AT)
        lake = self.fixture(mutate=blocked)
        result = self.build(lake)
        self.assertEqual(result['coverage']['securities_research_readable'], 0)
        self.assertEqual(len(result['securities']), 1000)
        for key in ['sec/0000000001', 'sec/0000000002']:
            with self.assertRaisesRegex(ValueError, 'required_dataset_unavailable'):
                self.build(lake, required_datasets=[key])

    def test_same_count_different_security_set(self):
        lake = self.fixture()
        payload = deepcopy(self.payload)
        payload['rows'][-1] = dict(ticker='OTHER', security_id='US:OTHER')
        raw = encoded(payload)
        self.cohort.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'cohort_identity_mismatch'):
            self.build(lake, cohort_sha256=digest(raw))

    def test_duplicate_security_and_small_cohort(self):
        lake = self.fixture()
        for rows, error in [(self.rows[:2], 'whole_cohort_required'),
                             (self.rows[:-1] + [self.rows[0]], 'duplicate_security')]:
            raw = encoded(dict(self.payload, rows=rows, candidate_count=len(rows)))
            self.cohort.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, error):
                self.build(lake, cohort_sha256=digest(raw))

    def test_wrong_cohort_bytes(self):
        lake = self.fixture()
        self.cohort.write_bytes(self.raw + b' ')
        with self.assertRaisesRegex(ValueError, 'checkpoint_hash'):
            self.build(lake)

    def test_input_pins_are_all_required(self):
        lake = self.fixture()
        for key, value, error in [('commit_sha256', '0'*64, 'history_head_mismatch'),
            ('catalog_sha256', '0'*64, 'history_catalog_mismatch'),
            ('execution_sha256', '0'*64, 'history_execution_mismatch'),
            ('source_commit', '0'*40, 'history_source_mismatch')]:
            with self.assertRaisesRegex(ValueError, error):
                self.build(lake, **{key: value})

    def test_study_must_have_completed(self):
        with self.assertRaisesRegex(ValueError, 'study_not_completed'):
            self.build(self.fixture(study=False))

    def test_missing_execution_no_fallback(self):
        lake = self.fixture()
        (self.archive / 'long-history-v1/executions' / self.execution).unlink()
        with self.assertRaisesRegex(ValueError, 'execution_receipt_missing'):
            self.build(lake)

    def test_report_hash_and_semantic_counts(self):
        lake = self.fixture(quality_mutate=lambda q: q.update(financial_fact_rows=999))
        with self.assertRaisesRegex(ValueError, 'quality_coverage_mismatch'):
            self.build(lake)
        report = next((self.archive / 'long-history-v1/reports').iterdir())
        report.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'remote_hash'):
            self.build(lake)

    def test_in_memory_catalog_mutation_fails(self):
        lake = self.fixture()
        lake.catalog['datasets']['sec/0000000001']['rows'] = 999
        with self.assertRaisesRegex(ValueError, 'mutated_catalog'):
            self.build(lake)

    def test_future_execution_or_dataset_check(self):
        lake = self.fixture()
        with self.assertRaisesRegex(ValueError, 'history_availability'):
            self.build(lake, decision_at='2026-01-06T08:00:00Z')

    def test_freshness_limit_and_timezone(self):
        lake = self.fixture()
        for age in [0, -1, True, 169]:
            with self.assertRaisesRegex(ValueError, 'freshness_window'):
                self.build(lake, max_age_hours=age)
        with self.assertRaisesRegex(ValueError, 'timezone_required'):
            self.build(lake, decision_at='2026-01-06T12:00:00')

    def test_issuer_mapping_and_security_relationship(self):
        def wrong(lake):
            lake.catalog['datasets']['sec/0000000001']['tickers'] = ['OTHER']
        with self.assertRaisesRegex(ValueError, 'issuer_security_mismatch'):
            self.build(self.fixture(mutate=wrong))

    def test_requested_records_are_actual_verified_bytes(self):
        result = self.build(self.fixture(), required_datasets=['sec/0000000001'])
        selected = result['selected_records']['sec/0000000001']
        self.assertEqual(selected['rows'][0]['value'], 100)
        self.assertEqual(selected['records_sha256'], digest(encoded(selected['rows'])))

    def test_new_head_during_read_blocks_output(self):
        lake = self.fixture()
        original = lake.transport.names
        def names(prefix):
            result = original(prefix)
            return result + ['0'*64] if prefix.endswith('/commits') else result
        with patch.object(lake.transport, 'names', side_effect=names):
            with self.assertRaisesRegex(ValueError, 'history_changed_during_read'):
                self.build(lake)

    def test_prepare_preserves_archive_and_emits_only_input(self):
        self.fixture()
        before = {p.relative_to(self.archive): digest(p.read_bytes())
                  for p in self.archive.rglob('*') if p.is_file()}
        kwargs = dict(self.args, output=self.root/'output', workspace=self.root/'cache',
                      local_archive=self.archive)
        result = prepare_history(**kwargs)
        after = {p.relative_to(self.archive): digest(p.read_bytes())
                 for p in self.archive.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        packet, _ = read_pinned(self.root/'output/history-input.json',
                               result['files']['history-input.json'])
        self.assertEqual(len(packet['securities']), 1000)
        self.assertFalse(result['model_cycle_events_executed'])
        with self.assertRaisesRegex(ValueError, 'new_run_directory_required'):
            prepare_history(**kwargs)

    def test_no_artifact_on_failed_prerequisite(self):
        self.fixture()
        with self.assertRaisesRegex(ValueError, 'partial_history'):
            prepare_history(**self.args, output=self.root/'output', workspace=self.root/'cache',
                            local_archive=self.archive, partial_policy='reject')
        self.assertFalse((self.root/'output').exists())

    def test_output_cannot_write_inside_archive(self):
        self.fixture()
        with self.assertRaisesRegex(ValueError, 'history_archive_is_read_only'):
            prepare_history(**self.args, output=self.archive/'output', workspace=self.root/'cache',
                            local_archive=self.archive)

    def test_full_pack_restore_is_not_skipped(self):
        self.fixture()
        next((self.archive/'long-history-v1/packs').iterdir()).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'remote_hash'):
            prepare_history(**self.args, output=self.root/'output', workspace=self.root/'cache',
                            local_archive=self.archive)

    def test_transport_rejects_write_and_constructor_mkdir(self):
        with self.assertRaisesRegex(ValueError, 'read_only_transport'):
            ReadOnlyTransport(self.transport).write('arbitrary', b'no')
        with patch.object(ReadOnlyRcloneTransport, 'read_call', return_value=b'[]'), \
             patch('tools.macro_research_checkpoint.RcloneTransport.call') as remote_call:
            with self.assertRaisesRegex(ValueError, 'read_only_transport'):
                ReadOnlyRcloneTransport('gdrive:research/macro_technical_evidence/v1/scheduled')
            remote_call.assert_not_called()

    def test_real_events_cannot_bypass_unfinished_adapters(self):
        path = self.root/'events.json'
        raw = encoded(dict(schema='subscription-model-events-v1', data_kind='REAL', events=[]))
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'real_model_event_adapters_not_integrated'):
            run(path, digest(raw), self.root/'model', ZERO, DECISION, AT)
        self.assertFalse((self.root/'model').exists())

    def test_duplicate_json_keys_rejected(self):
        raw = b'{"data_kind":"REAL","data_kind":"SYNTHETIC"}'
        self.cohort.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'duplicate_json_key'):
            read_pinned(self.cohort, digest(raw))

    def test_model_cycle_cli_consumes_history_adapter(self):
        self.fixture()
        args = [sys.executable, str(ROOT/'tools/subscription_manager/run_model_cycle.py'),
                'prepare-history', '--local-archive', str(self.archive),
                '--workspace', str(self.root/'cli-cache'), '--output', str(self.root/'cli-output')]
        for key, value in self.args.items():
            args += ['--' + key.replace('_', '-'), str(value)]
        completed = subprocess.run(args, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result['coverage']['requested_securities'], 1000)
        self.assertFalse(result['model_cycle_events_executed'])

    def test_synthetic_cycle_still_restores_without_parent_mutation(self):
        raw = encoded(dict(schema='subscription-model-events-v1', data_kind='SYNTHETIC', events=[
            dict(event_id='open', type='OPEN', at=AT, payload=dict(book_kind='MODEL_PAPER',
                 data_kind='SYNTHETIC', currency='USD', cash='1000', policy_sha256='a'*64))]))
        path = self.root/'events.json'
        path.write_bytes(raw)
        result = run(path, digest(raw), self.root/'first', ZERO, DECISION, AT)
        parent = self.root/'first/model_snapshot.sqlite'
        before = parent.read_bytes()
        second = run(path, digest(raw), self.root/'second', result['journal_head'],
                     DECISION, AT, parent, digest(before))
        self.assertEqual(result['journal_head'], second['journal_head'])
        self.assertEqual(parent.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()

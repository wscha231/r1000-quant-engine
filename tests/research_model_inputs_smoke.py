#!/usr/bin/env python3
"""Shared-model metadata regressions; synthetic sources, no provider/admission."""
from pathlib import Path
import ast
from dataclasses import replace
from types import MappingProxyType
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tests'))
import research_data_access_smoke as reader_fixtures
from tools.macro_history_sources import digest, encoded
from tools.research_data_access import ContractError, ResearchDataReader
from tools.research_model_inputs import (
    prepare_model_inputs, store_model_inputs, replay_model_inputs, plan_model_input_reuse,
    MAX_METADATA_BYTES,
)
DECISION, SESSIONS = reader_fixtures.DECISION, reader_fixtures.SESSIONS


def model(version='v1', **changes):
    result = dict(model_id='R1000-research', model_version=version, code_sha='a' * 40,
                  config_sha256='b' * 64, feature_recipe_sha256='c' * 64)
    result.update(changes)
    return result


class ModelInputsTest(unittest.TestCase):
    def setUp(self):
        self.fixture = reader_fixtures.ReaderTest('test_schema_and_discovery_map_match_native_contract')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.reader = self.fixture.reader
        self.generation = self.fixture.generation()
        self.components = [dict(component_id='spy', instrument_id='FIXTURE:US:SPY',
            required_start=SESSIONS[0], required_end=SESSIONS[-1], minimum_rows=3,
            required_sessions=SESSIONS, optional=False)]

    def prepare(self, **changes):
        args = dict(decision_time=DECISION, components=self.components,
                    consumer_id='fixture_feature_application', models=[model()])
        args.update(changes)
        return prepare_model_inputs(self.reader, 'ds.us.prices.daily', self.generation, **args)

    def test_two_models_share_one_actual_read_and_source_objects(self):
        with patch.object(self.reader, 'read_components', wraps=self.reader.read_components) as read:
            bundle = self.prepare(models=[model(), model('v2')])
        self.assertEqual(read.call_count, 1)
        self.assertEqual(len(bundle.binding_bytes), 2)
        from json import loads
        bindings = [loads(raw) for raw in bundle.binding_bytes]
        self.assertEqual({b['input_id'] for b in bindings}, {bundle.input_id})
        self.assertNotEqual(digest(bundle.binding_bytes[0]), digest(bundle.binding_bytes[1]))
        self.assertEqual(bundle.input_id, self.prepare(models=[model('v3')]).input_id)
        self.assertEqual(bundle.read.results['spy'].receipt['provider_refresh_count'], 0)
        for binding in bindings:
            self.assertEqual(binding['evaluation_status'], 'NOT_RUN')
            self.assertFalse(binding['eligible_for_economics'])
        self.assertNotIn(b'"close":', bundle.input_bytes)

    def test_identity_config_recipe_changes_are_model_bindings_only(self):
        first = self.prepare()
        for changes in ({'code_sha': 'd' * 40}, {'config_sha256': 'e' * 64},
                        {'feature_recipe_sha256': 'f' * 64}):
            with self.subTest(changes=changes):
                changed = self.prepare(models=[model(**changes)])
                self.assertEqual(first.input_id, changed.input_id)
                self.assertNotEqual(first.binding_bytes, changed.binding_bytes)
        changed = self.prepare(decision_time='2026-10-08T08:00:00Z')
        self.assertNotEqual(first.input_id, changed.input_id)

    def test_metadata_storage_is_idempotent_private_local_and_does_not_copy_raw(self):
        bundle = self.prepare(models=[model(), model('v2')])
        root = self.fixture.root / 'private-shared-metadata'
        first = store_model_inputs(bundle, root)
        self.assertEqual(first, store_model_inputs(bundle, root))
        self.assertEqual(len(list(root.rglob('*/*/*'))), 3)
        self.assertEqual(len([p for p in root.rglob('*') if p.is_file()]), 3)
        self.assertEqual(first['source_objects_copied'], 0)
        self.assertFalse(first['durable_publication_verified'])
        self.assertEqual(first['accepted_write_count'], 0)
        path = root / first['paths'][0]
        path.write_bytes(b'conflict')
        with self.assertRaisesRegex(ValueError, 'immutable_path_conflict'):
            store_model_inputs(bundle, root)

    def test_replay_revalidates_original_reader_and_detects_corruption(self):
        bundle = self.prepare()
        with patch.object(self.reader, 'read_components', wraps=self.reader.read_components) as read:
            replay = replay_model_inputs(self.reader, bundle.input_bytes,
                expected_input_id=bundle.input_id, models=[model('v2')])
        self.assertEqual(read.call_count, 1); self.assertEqual(replay.input_id, bundle.input_id)
        with self.assertRaisesRegex(ContractError, 'MODEL_INPUT_HASH'):
            replay_model_inputs(self.reader, bundle.input_bytes + b' ',
                expected_input_id=bundle.input_id, models=[model()])
        sha = self.fixture.spec['files'][0]['sha256']
        (self.fixture.transport.root / ('shared-research-v1/objects/' + sha)).write_bytes(b'corrupt')
        with self.assertRaises(ContractError):
            replay_model_inputs(self.reader, bundle.input_bytes,
                expected_input_id=bundle.input_id, models=[model()])

    def test_new_cutoff_does_not_inherit_old_source_freshness(self):
        old = self.prepare()
        with self.assertRaisesRegex(ContractError, 'STALE_GENERATION'):
            self.prepare(decision_time='2026-10-10T08:00:00Z')
        plan = plan_model_input_reuse(old, [dict(component_id='spy', required_sessions=SESSIONS)],
                                    decision_time='2026-10-10T08:00:00Z')
        self.assertEqual(plan['components'][0]['reason'], 'NEW_DECISION_REQUIRES_READER')
        self.assertFalse(plan['collection_approved'])

    def test_verified_subset_reuses_but_outside_slice_is_not_a_missing_data_claim(self):
        bundle = self.prepare()
        def plan(sessions):
            return plan_model_input_reuse(bundle, [dict(component_id='spy', required_sessions=sessions)],
                                         decision_time=DECISION)['components'][0]
        self.assertEqual(plan(SESSIONS[1:])['status'], 'REUSE_EXISTING')
        expanded = plan(SESSIONS + ['2026-07-07'])
        self.assertEqual(expanded['status'], 'REVALIDATION_REQUIRED')
        self.assertEqual(expanded['unverified_sessions'], ('2026-07-07',))
        self.assertEqual(expanded['collection_sessions'], ())
        self.assertFalse(expanded['collection_approved'])
        no_grid = self.prepare(components=[dict(self.components[0], required_sessions=None)])
        unknown = plan_model_input_reuse(no_grid, [dict(component_id='spy', required_sessions=SESSIONS)],
                                        decision_time=DECISION)
        self.assertEqual(unknown['components'][0]['reason'], 'COVERAGE_UNKNOWN')

    def test_bad_models_and_future_session_requests_fail_without_reading(self):
        for models in ([], [model(), model()], [model(model_id='../bad')],
                       [model(config_sha256='secret')], [dict(model(), purpose='backtest')]):
            with self.subTest(models=models), patch.object(self.reader, 'read_components') as read:
                with self.assertRaises(ContractError): self.prepare(models=models)
                read.assert_not_called()
        bundle = self.prepare()
        for sessions in ([SESSIONS[0], SESSIONS[0]], ['2026-10-09'], list(reversed(SESSIONS))):
            with self.subTest(sessions=sessions), self.assertRaises(ContractError):
                plan_model_input_reuse(bundle, [dict(component_id='spy', required_sessions=sessions)],
                                      decision_time=DECISION)

    def test_required_failure_cannot_create_binding_and_optional_refusal_is_preserved(self):
        missing = dict(self.components[0], component_id='unavailable', instrument_id='FIXTURE:US:ABSENT')
        with self.assertRaises(ContractError): self.prepare(components=[missing])
        bundle = self.prepare(components=self.components + [dict(missing, optional=True)])
        self.assertIn('unavailable', bundle.read.refusals)
        self.assertIn(b'"unavailable"', bundle.input_bytes)
        plan = plan_model_input_reuse(bundle, [dict(component_id='unavailable', required_sessions=SESSIONS)],
                                     decision_time=DECISION)
        self.assertEqual(plan['components'][0]['status'], 'BLOCKED')

    def test_typed_financial_trust_stays_external_and_periods_are_not_sessions(self):
        holder, trust, blobs, calls, read = self.fixture.financial_reader_fixture()
        class Transport:
            def read(_, path):
                if path == 'shared-research-v1/generations/' + digest(holder['manifest']):
                    return holder['manifest']
                return blobs[path.rsplit('/', 1)[-1]]
        reader = ResearchDataReader(Transport())
        args = dict(decision_time='2026-10-31T18:01:00Z',
            components=[dict(component_id='financial', issuer_cik=trust.issuer_cik,
                required_period_end_start='2016-01-01', required_period_end_end='2026-10-23')],
            consumer_id='CONTRACT_FIXTURE:financial_consumer', models=[model()])
        with self.assertRaises(ContractError):
            prepare_model_inputs(reader, 'ds.us.financials.sec.companyfacts',
                                 digest(holder['manifest']), **args)
        bundle = prepare_model_inputs(reader, 'ds.us.financials.sec.companyfacts',
            digest(holder['manifest']), financial_trust=trust, **args)
        self.assertNotIn(b'"value":', bundle.input_bytes)
        plan = plan_model_input_reuse(bundle, [dict(component_id='financial', required_sessions=SESSIONS)],
                                     decision_time=args['decision_time'])
        self.assertEqual(plan['components'][0]['reason'], 'DATASET_SPECIFIC_COVERAGE_REQUIRED')

    def test_model_name_cannot_replace_qualified_provider_consumer(self):
        manifest, blobs, original_read = self.fixture.observed_revision_reader_fixture()
        raw = encoded(manifest)
        class Transport:
            def read(_, path):
                if path == 'shared-research-v1/generations/' + digest(raw): return raw
                return blobs[path.rsplit('/', 1)[-1]]
        reader = ResearchDataReader(Transport())
        args = dict(decision_time='2026-10-30T07:20:00Z',
            components=[dict(component_id='mu', instrument_id='US.TEST.MU',
                required_start='2026-10-23', required_end='2026-10-29')], models=[model()])
        with self.assertRaisesRegex(ContractError, 'COMPOSITION_USE_SCOPE'):
            prepare_model_inputs(reader, 'ds.us.prices.daily', digest(raw),
                consumer_id=model()['model_id'], **args)
        bundle = prepare_model_inputs(reader, 'ds.us.prices.daily', digest(raw),
            consumer_id='ohlcv-technical-feature-h1', **args)
        self.assertEqual(len(bundle.read.results['mu'].rows), 5)

    def test_fake_reader_and_cross_bundle_results_cannot_borrow_verified_status(self):
        first = self.prepare()
        class FakeReader:
            def read_components(_, *args, **kwargs):
                raise AssertionError('must refuse before invocation')
        with self.assertRaisesRegex(ContractError, 'MODEL_INPUT_READER'):
            prepare_model_inputs(FakeReader(), 'ds.us.prices.daily', self.generation,
                decision_time=DECISION, components=self.components,
                consumer_id='fixture_feature_application', models=[model()])
        second = self.prepare(decision_time='2026-10-08T08:00:00Z')
        detached = replace(first, read=second.read)
        for forged in (detached, self.changed_row_bundle(first)):
            with self.subTest(forged=forged.input_id):
                with self.assertRaisesRegex(ContractError, 'MODEL_INPUT_(READ|ROW)_BINDING'):
                    plan_model_input_reuse(forged, [dict(component_id='spy', required_sessions=SESSIONS)],
                                          decision_time=DECISION)
                with self.assertRaisesRegex(ContractError, 'MODEL_INPUT_(READ|ROW)_BINDING'):
                    store_model_inputs(forged, self.fixture.root / 'must-not-write')
        self.assertFalse((self.fixture.root / 'must-not-write').exists())

    def changed_row_bundle(self, bundle):
        item = bundle.read.results['spy']
        row = dict(item.rows[0]); row['close'] = 100.5
        changed = replace(item, rows=(MappingProxyType(row),) + item.rows[1:])
        read = replace(bundle.read, results=MappingProxyType(dict(spy=changed)))
        return replace(bundle, read=read)

    def test_oversized_metadata_fails_before_reader_decode_or_write(self):
        with patch.object(self.reader, 'read_components') as read:
            with self.assertRaisesRegex(ContractError, 'MODEL_INPUT_METADATA_LIMIT'):
                self.prepare(components=[dict(self.components[0],
                    required_sessions=['x' * MAX_METADATA_BYTES])])
            read.assert_not_called()
        bundle = self.prepare()
        oversized = replace(bundle, input_bytes=b'x' * (MAX_METADATA_BYTES + 1))
        with patch('tools.research_model_inputs.decode', side_effect=AssertionError('decode forbidden')):
            with self.assertRaisesRegex(ContractError, 'MODEL_INPUT_HASH'):
                store_model_inputs(oversized, self.fixture.root / 'must-not-write')
            with self.assertRaisesRegex(ContractError, 'MODEL_INPUT_HASH'):
                plan_model_input_reuse(oversized, [dict(component_id='spy', required_sessions=SESSIONS)],
                                      decision_time=DECISION)

    def test_binding_cannot_claim_evaluation_or_selector_authority(self):
        import json
        bundle = self.prepare(); binding = json.loads(bundle.binding_bytes[0])
        binding['eligible_for_selector'] = True
        with self.assertRaisesRegex(ContractError, 'MODEL_BINDING_AUTHORITY'):
            store_model_inputs(replace(bundle, binding_bytes=(encoded(binding),)),
                               self.fixture.root / 'must-not-write')
        self.assertFalse((self.fixture.root / 'must-not-write').exists())

    def test_existing_registered_suite_includes_model_inputs_once(self):
        tree = ast.parse((ROOT / 'tests/long_history_lake_smoke.py').read_bytes())
        loader = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'load_tests')
        loaded = [n.args[0].id for n in ast.walk(loader) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == 'loadTestsFromTestCase'
            and n.args and isinstance(n.args[0], ast.Name)]
        self.assertEqual(loaded.count('ModelInputsTest'), 1)


if __name__ == '__main__':
    unittest.main()

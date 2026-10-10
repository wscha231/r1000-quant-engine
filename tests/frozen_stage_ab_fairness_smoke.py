#!/usr/bin/env python3
"""Offline synthetic H1 contracts; unittest checks remain active under -O."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from research import evaluation_v2_admission as admission
from tools import frozen_stage_ab_fairness as fairness


class Fixture:
    def __init__(self, root: Path, *, sec: bool = False):
        self.root = root
        self.frozen, self.a, self.b, self.evidence, self.environment = (
            root / p for p in ('frozen', 'a', 'b', 'evidence', 'environment'))
        for p in (self.frozen, self.a, self.b, self.evidence, self.environment):
            p.mkdir()
        self.groups = {g: {'basis': 'SYNTHETIC declared ' + g, 'sources': []}
                       for g in fairness.GROUPS}
        shared = {}
        for role, group in fairness.ROLE_GROUP.items():
            raw = admission.canonical({'synthetic_role': role, 'value': 1})
            source = self.source(role, raw)
            self.groups[group]['sources'].append(source)
            shared[role] = source['ref']
            (self.environment / role).write_bytes(raw)
        for group in ('candidates', 'fundamentals', 'strategy_model_parameters'):
            self.groups[group]['sources'].append(self.source(group, b'{"value":2}'))
        for ident, group in {'ohlcv': 'prices', 'vix': 'macro', 'consensus': 'fundamentals',
            'earnings': 'fundamentals', 'guidance': 'fundamentals',
            'tax': 'cost_slippage_tax_fx', 'slippage': 'cost_slippage_tax_fx',
            'model_params': 'strategy_model_parameters'}.items():
            self.groups[group]['sources'].append(self.source(ident, b'{"value":4}'))
        if sec:
            self.groups['sec_event']['sources'].append(self.source('sec-event', b'{"value":3}'))
        self.context = {'schema': admission.SCHEMA, 'window_start': '2026-10-01',
            'window_end': '2026-10-08', 'base_currency': 'USD', 'initial_capital': 100000,
            'official_metric_mode': 'broker_ledger_next_close', 'data_scope': 'SYNTHETIC',
            'shared_refs': shared}
        context_raw = admission.canonical(self.context)
        (self.environment / 'context').write_bytes(context_raw)
        self.context_ref = {'artifact_id': 'context', 'sha256': admission.digest(context_raw)}
        (self.environment / 'strategy').write_bytes(b'SYNTHETIC strategy')
        strategy_ref = {'artifact_id': 'strategy', 'sha256': admission.digest(b'SYNTHETIC strategy')}
        self.control, self.challenger = ({'schema': admission.SCHEMA, 'role': role,
            'context_ref': self.context_ref, 'strategy_ref': strategy_ref}
            for role in ('CONTROL', 'CHALLENGER'))
        active = sorted(g for g in fairness.GROUPS if self.groups[g]['sources'])
        self.contract = {'schema': fairness.SCHEMA, 'data_scope': 'SYNTHETIC',
            'price_generation_sha256': shared['data_release']['sha256'],
            'code_sha': fairness.runtime.git_head(), 'session': '2026-10-08',
            'decision_time': '2026-10-08T22:00:00Z', 'context_sha256': self.context_ref['sha256'],
            'groups': self.groups,
            'consumers': {'A': {'engine': active, 'broker': ['macro', 'prices',
                'calendar_pit', 'cost_slippage_tax_fx', 'capital_cash_accounting',
                'code_evaluator', 'session_decision']}, 'B': {'replay': active}}}
        self.rebind()

    def source(self, ident: str, raw: bytes) -> dict:
        for root in (self.frozen, self.a, self.b):
            (root / ident).write_bytes(raw)
        return {'ref': {'artifact_id': ident, 'sha256': admission.digest(raw)}, 'bytes': len(raw),
            'available_at': '2026-10-08T20:00:00Z', 'collected_at': '2026-10-08T21:00:00Z',
            'expires_at': '2026-10-09T20:00:00Z'}

    def rebind(self):
        self.raw = admission.canonical(self.contract); self.pin = admission.digest(self.raw)

    def save(self, raw: bytes) -> dict:
        ident = 'ev-' + admission.digest(raw)
        path = self.evidence / ident
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError('synthetic evidence collision')
        else:
            path.write_bytes(raw)
        return {'artifact_id': ident, 'sha256': admission.digest(raw)}

    def stage(self, name: str) -> fairness.FrozenStage:
        return fairness.FrozenStage(self.raw, expected_generation_sha256=self.pin, stage=name,
            runtime_root=self.a if name == 'A' else self.b, frozen_root=self.frozen,
            save_evidence=self.save, run_id='workflow-' + name,
            control=self.control, challenger=self.challenger, environment_root=self.environment)

    def consume(self, view):
        result = []
        for group in view.groups:
            for source in self.groups[group]['sources']:
                result.append(view.read(group, source['ref']['artifact_id']))
        return tuple(result)

    def receipts(self):
        result = []
        for stage_name in ('A', 'B'):
            stage = self.stage(stage_name)
            for name in fairness.CONSUMERS[stage_name]:
                stage.run_consumer(name, self.consume)
            result.append(stage.finish())
        return result

    def verify(self, a: bytes, b: bytes, **overrides):
        kwargs = dict(expected_generation_sha256=self.pin, expected_stage_a_sha256=admission.digest(a),
            expected_stage_b_sha256=admission.digest(b), frozen_root=self.frozen,
            evidence_root=self.evidence, control=self.control, challenger=self.challenger,
            environment_root=self.environment)
        kwargs.update(overrides)
        return fairness.verify(self.raw, a, b, **kwargs)

    def cli(self, a: bytes, b: bytes):
        for name, raw in (('contract', self.raw), ('stage-a', a), ('stage-b', b),
                          ('control', admission.canonical(self.control)),
                          ('challenger', admission.canonical(self.challenger))):
            (self.root / name).write_bytes(raw)
        command = [sys.executable, '-B', *(['-O'] if sys.flags.optimize else []),
            str(ROOT / 'tools/frozen_stage_ab_fairness.py')]
        for name in ('contract', 'stage-a', 'stage-b', 'control', 'challenger'):
            command += ['--' + name, str(self.root / name)]
        command += ['--generation-sha256', self.pin, '--stage-a-sha256', admission.digest(a),
            '--stage-b-sha256', admission.digest(b), '--frozen-root', str(self.frozen),
            '--evidence-root', str(self.evidence), '--environment-root', str(self.environment)]
        return subprocess.run(command, capture_output=True, text=True, timeout=30)


class FrozenFairnessTests(unittest.TestCase):
    OVERFLOW_CLOCKS = ('0001-01-01T00:00:00+01:00', '9999-12-31T23:59:59-01:00')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = Fixture(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_generation_and_different_run_ids_pass_without_authority(self):
        a, b = self.f.receipts(); result = self.f.verify(a, b)
        self.assertEqual(result['status'], 'FROZEN_CONTRACT_BYTE_PASS_RESEARCH_ONLY')
        self.assertEqual(len(result['common_group_sha256']), 12)
        self.assertNotEqual(json.loads(a)['run_id'], json.loads(b)['run_id'])
        for key, value in fairness.AUTHORITY.items():
            self.assertIs(result[key], value)

    def test_optional_sec_used_and_unused_have_exact_coverage(self):
        self.assertEqual(self.f.groups['sec_event']['sources'], [])
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(Path(tmp), sec=True)
            a, b = f.receipts(); self.assertEqual(f.verify(a, b)['data_scope'], 'SYNTHETIC')

    def test_f01_price_cache_generation_mixed(self):
        (self.f.b / 'ohlcv').write_bytes(b'SYNTHETIC other cache generation')
        with self.assertRaisesRegex(admission.AdmissionError, 'RUNTIME_SOURCE_BYTES_MISMATCH'):
            self.f.stage('B')

    def test_f02_provider_refresh_and_stale_repair_block_before_result(self):
        for operation in ('provider_refresh', 'refresh_stale_days_2', 'latest_cache', 'cache_prefix'):
            with self.subTest(operation=operation):
                stage = self.f.stage('A')
                with self.assertRaisesRegex(admission.AdmissionError, 'STRICT_EXTERNAL_INPUT_FORBIDDEN'):
                    stage.run_consumer('engine', lambda view: view.external_input(operation))
                with self.assertRaisesRegex(admission.AdmissionError, 'STAGE_INCOMPLETE_OR_BLOCKED'):
                    stage.finish()

    def test_f03_candidates_and_archived_targets_cannot_fallback(self):
        for operation in ('failed_runs_candidate', 'archived_target_book'):
            with self.subTest(operation=operation):
                stage = self.f.stage('B')
                with self.assertRaisesRegex(admission.AdmissionError, 'STRICT_EXTERNAL_INPUT_FORBIDDEN'):
                    stage.run_consumer('replay', lambda view: view.external_input(operation))
        (self.f.b / 'candidates').unlink()
        with self.assertRaises(admission.AdmissionError):
            self.f.stage('B')

    def test_f04_stage_a_original_post_change(self):
        stage = self.f.stage('A')
        stage.run_consumer('engine', self.f.consume); stage.run_consumer('broker', self.f.consume)
        (self.f.a / 'candidates').write_bytes(b'changed')
        with self.assertRaises(admission.AdmissionError):
            stage.finish()

    def test_f05_session_and_decision_time_receipt_drift(self):
        a, b = self.f.receipts()
        for key, value in (('session', '2026-10-07'), ('decision_time', '2026-10-08T23:00:00Z')):
            with self.subTest(key=key):
                receipt = json.loads(b); receipt[key] = value
                with self.assertRaisesRegex(admission.AdmissionError, 'STAGE_IDENTITY_MISMATCH'):
                    self.f.verify(a, admission.canonical(receipt))

    def test_f06_equal_prices_macro_vix_consensus_drift(self):
        price = (self.f.b / 'ohlcv').read_bytes()
        for name in ('benchmark', 'vix', 'consensus', 'earnings', 'guidance'):
            with self.subTest(name=name):
                path = self.f.b / name; original = path.read_bytes(); path.write_bytes(b'changed')
                self.assertEqual((self.f.b / 'ohlcv').read_bytes(), price)
                with self.assertRaises(admission.AdmissionError):
                    self.f.stage('B')
                path.write_bytes(original)

    def test_f07_retained_runtime_bytes_missing(self):
        a, b = self.f.receipts()
        next(self.f.evidence.iterdir()).unlink()
        with self.assertRaisesRegex(admission.AdmissionError, 'ARTIFACT_UNAVAILABLE'):
            self.f.verify(a, b)

    def test_f07_declared_hash_without_consumer_read_is_not_proof(self):
        stage = self.f.stage('B')
        with self.assertRaisesRegex(admission.AdmissionError, 'RUNTIME_CONSUMPTION_INCOMPLETE'):
            stage.run_consumer('replay', lambda view: {'declared_hash': self.f.pin})
        with self.assertRaises(admission.AdmissionError):
            stage.finish()

    def test_f08_adjustment_and_corporate_actions_drift(self):
        (self.f.b / 'corporate_actions').write_bytes(b'raw replaces adjusted')
        with self.assertRaises(admission.AdmissionError):
            self.f.stage('B')
        original_pin = self.f.pin
        self.f.contract['groups']['prices']['basis'] = 'different adjusted basis'
        self.f.rebind()
        with self.assertRaisesRegex(admission.AdmissionError, 'GENERATION_BYTES_MISMATCH'):
            fairness.validate_contract(self.f.raw, original_pin)

    def test_f09_capital_cost_fx_tax_evaluator_config_drift(self):
        for name in ('reference_initial_capital', 'cash_accounting', 'cost_contract', 'fx',
                     'tax', 'slippage', 'metric_contract', 'evaluator_source',
                     'strategy_model_parameters', 'model_params'):
            with self.subTest(name=name):
                p = self.f.b / name; original = p.read_bytes(); p.write_bytes(b'changed')
                with self.assertRaises(admission.AdmissionError):
                    self.f.stage('B')
                p.write_bytes(original)

    def test_f10_engine_to_broker_price_and_candidate_change(self):
        for name in ('ohlcv', 'candidates'):
            with self.subTest(name=name):
                stage = self.f.stage('A'); stage.run_consumer('engine', self.f.consume)
                p = self.f.a / name; original = p.read_bytes(); p.write_bytes(b'changed')
                called = []
                with self.assertRaises(admission.AdmissionError):
                    stage.run_consumer('broker', lambda view: called.append(True))
                self.assertEqual(called, [])
                p.write_bytes(original)

    def test_inflight_changes_fail_even_when_final_hash_is_restored(self):
        stage = self.f.stage('B')
        def altered(view):
            path = self.f.b / 'candidates'; original = path.read_bytes()
            path.write_bytes(b'changed')
            try:
                view.read('candidates', 'candidates')
            finally:
                path.write_bytes(original)
        with self.assertRaises(admission.AdmissionError):
            stage.run_consumer('replay', altered)

    def test_change_after_read_before_consumer_returns(self):
        stage = self.f.stage('B')
        def altered(view):
            result = self.f.consume(view)
            (self.f.b / 'candidates').write_bytes(b'changed')
            return result
        with self.assertRaises(admission.AdmissionError):
            stage.run_consumer('replay', altered)

    def test_unknown_input_cannot_be_added_to_consumer(self):
        stage = self.f.stage('B')
        with self.assertRaisesRegex(admission.AdmissionError, 'UNDECLARED_CONSUMER_INPUT'):
            stage.run_consumer('replay', lambda view: view.read('prices', 'unknown'))

    def test_runtime_receipt_rebinding_cannot_hide_missing_groups(self):
        a, b = self.f.receipts()
        receipt = json.loads(b); receipt['phases'][3]['groups'].pop('macro')
        with self.assertRaisesRegex(admission.AdmissionError, 'RUNTIME_GROUP_COVERAGE'):
            self.f.verify(a, admission.canonical(receipt))

    def test_evidence_rebinding_cannot_hide_different_actual_bytes(self):
        a, b = self.f.receipts(); receipt = json.loads(b)
        row = receipt['phases'][3]['groups']['macro'][0]
        row['evidence_ref'] = self.f.save(b'other actual bytes')
        row['sha256'] = admission.digest(b'other actual bytes'); row['size_bytes'] = len(b'other actual bytes')
        with self.assertRaisesRegex(admission.AdmissionError, 'RECONSTRUCTED_SOURCE_MISMATCH'):
            self.f.verify(a, admission.canonical(receipt))

    def test_missing_duplicate_and_reordered_phase_fail(self):
        a, b = self.f.receipts()
        for mutation in ('missing', 'duplicate', 'reorder'):
            with self.subTest(mutation=mutation):
                r = json.loads(b)
                if mutation == 'missing': r['phases'].pop(1)
                if mutation == 'duplicate': r['phases'][2] = copy.deepcopy(r['phases'][1])
                if mutation == 'reorder': r['phases'][2], r['phases'][3] = r['phases'][3], r['phases'][2]
                with self.assertRaises(admission.AdmissionError):
                    self.f.verify(a, admission.canonical(r))

    def test_receipt_and_generation_pins_required(self):
        a, b = self.f.receipts()
        with self.assertRaises(admission.AdmissionError):
            self.f.verify(a, b, expected_stage_b_sha256='0' * 64)
        with self.assertRaises(admission.AdmissionError):
            fairness.validate_contract(self.f.raw, '')

    def test_source_availability_and_expiry_fail_closed(self):
        source = self.f.contract['groups']['candidates']['sources'][0]
        original = dict(source)
        for key, value in (('available_at', '2026-10-09T21:00:00Z'),
            ('collected_at', '2026-10-09T21:00:00Z'), ('expires_at', '2026-10-07T21:00:00Z'),
            ('available_at', 'UNKNOWN'), ('available_at', '2026-10-08T20:00:00-00:00'),
            ('available_at', '2026-10-08T20:00:00+01:99')):
            with self.subTest(key=key, value=value):
                source.update(original); source[key] = value; self.f.rebind()
                with self.assertRaises(admission.AdmissionError):
                    fairness.validate_contract(self.f.raw, self.f.pin)

    def rebound_clock_receipts(self, a: bytes, b: bytes, value: str):
        self.f.contract['groups']['candidates']['sources'][0]['available_at'] = value
        self.f.rebind()
        # Bind both receipts to the changed contract so stale pins cannot mask
        # the clock failure. Retained source/evidence bytes remain unchanged.
        rebound = []
        for raw in (a, b):
            receipt = json.loads(raw)
            receipt['generation_sha256'] = self.f.pin
            rebound.append(admission.canonical(receipt))
        return rebound

    def test_clock_api_normalizes_lower_and_upper_utc_overflow(self):
        for value in self.OVERFLOW_CLOCKS:
            with self.subTest(value=value):
                with self.assertRaisesRegex(admission.AdmissionError, r'\ACLOCK_INVALID\Z'):
                    fairness.clock(value)

    def test_verify_normalizes_lower_and_upper_utc_overflow(self):
        a, b = self.f.receipts()
        for value in self.OVERFLOW_CLOCKS:
            with self.subTest(value=value):
                changed_a, changed_b = self.rebound_clock_receipts(a, b, value)
                with self.assertRaisesRegex(admission.AdmissionError, r'\ACLOCK_INVALID\Z'):
                    self.f.verify(changed_a, changed_b)

    def test_cli_blocks_lower_and_upper_utc_overflow_with_json(self):
        a, b = self.f.receipts()
        for value in self.OVERFLOW_CLOCKS:
            with self.subTest(value=value):
                changed_a, changed_b = self.rebound_clock_receipts(a, b, value)
                result = self.f.cli(changed_a, changed_b)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stderr, '')
                blocked = json.loads(result.stdout)
                self.assertEqual(blocked['status'], 'BLOCKED_FROZEN_FAIRNESS')
                self.assertEqual(blocked['reason'], 'CLOCK_INVALID')
                for key, expected in fairness.AUTHORITY.items():
                    self.assertIs(blocked[key], expected)

    def test_valid_utc_offset_session_and_pit_clocks_remain_admitted(self):
        expected = datetime(2026, 10, 8, 22, tzinfo=timezone.utc)
        for value in ('2026-10-08T22:00:00Z', '2026-10-08T23:00:00+01:00',
                      '2026-10-08T21:00:00-01:00'):
            with self.subTest(value=value):
                self.assertEqual(fairness.clock(value), expected)
        self.assertEqual(fairness.clock('0001-01-01T00:00:00Z'),
                         datetime.min.replace(tzinfo=timezone.utc))
        self.assertEqual(fairness.clock('9999-12-31T23:59:59.999999Z'),
                         datetime.max.replace(tzinfo=timezone.utc))
        self.f.contract['decision_time'] = '2026-10-08T23:00:00+01:00'
        for group in self.f.contract['groups'].values():
            for source in group['sources']:
                source.update(available_at='2026-10-09T05:00:00+09:00',
                              collected_at='2026-10-08T22:00:00+01:00',
                              expires_at='2026-10-09T21:00:00+01:00')
        self.f.rebind()
        a, b = self.f.receipts()
        result = self.f.verify(a, b)
        self.assertEqual(result['status'], 'FROZEN_CONTRACT_BYTE_PASS_RESEARCH_ONLY')
        cli = self.f.cli(a, b)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(cli.stderr, '')
        for output in (result, json.loads(cli.stdout)):
            for key, expected in fairness.AUTHORITY.items():
                self.assertIs(output[key], expected)

    def test_source_manifest_and_environment_cannot_disagree(self):
        self.f.contract['price_generation_sha256'] = '0' * 64; self.f.rebind()
        with self.assertRaisesRegex(admission.AdmissionError, 'PRICE_GENERATION_BINDING'):
            self.f.stage('A')
        self.f.contract['price_generation_sha256'] = self.f.context['shared_refs']['data_release']['sha256']
        self.f.contract['groups']['cost_slippage_tax_fx']['sources'][0]['ref']['sha256'] = '1' * 64
        self.f.rebind()
        with self.assertRaisesRegex(admission.AdmissionError, 'ENVIRONMENT_SOURCE_BINDING'):
            self.f.stage('A')

    def test_all_source_groups_and_consumer_closure_are_mandatory(self):
        self.f.contract['groups'].pop('macro'); self.f.rebind()
        with self.assertRaisesRegex(admission.AdmissionError, 'ALL_SOURCE_GROUPS_REQUIRED'):
            fairness.validate_contract(self.f.raw, self.f.pin)

    def test_missing_group_from_both_stage_plans_fails(self):
        self.f.contract['consumers']['B']['replay'].remove('fundamentals'); self.f.rebind()
        with self.assertRaisesRegex(admission.AdmissionError, 'CONSUMED_GROUP_COVERAGE'):
            fairness.validate_contract(self.f.raw, self.f.pin)

    def test_symlink_runtime_and_evidence_are_rejected(self):
        path = self.f.b / 'candidates'; path.unlink(); path.symlink_to(self.f.frozen / 'candidates')
        with self.assertRaises(admission.AdmissionError):
            self.f.stage('B')

    def test_executed_code_must_match(self):
        self.f.contract['code_sha'] = '0' * 40; self.f.rebind()
        with self.assertRaisesRegex(admission.AdmissionError, 'EXECUTED_CODE_SHA_MISMATCH'):
            self.f.stage('A')

    def test_out_of_order_or_partial_stage_cannot_finish(self):
        stage = self.f.stage('A')
        with self.assertRaises(admission.AdmissionError):
            stage.run_consumer('broker', self.f.consume)
        with self.assertRaises(admission.AdmissionError):
            stage.finish()
        with self.assertRaises(admission.AdmissionError):
            stage.run_consumer('engine', self.f.consume)

    def test_sealed_stage_cannot_be_reused(self):
        stage = self.f.stage('B'); stage.run_consumer('replay', self.f.consume); stage.finish()
        with self.assertRaises(admission.AdmissionError):
            stage.finish()

    def test_callback_economic_result_is_unchanged(self):
        stage = self.f.stage('B')
        expected = {'cash': 100000, 'cost_bps': 25, 'mode': 'next_close', 'orders': []}
        def consume(view):
            self.f.consume(view)
            return expected
        self.assertIs(stage.run_consumer('replay', consume), expected)
        self.assertEqual(expected, {'cash': 100000, 'cost_bps': 25, 'mode': 'next_close', 'orders': []})

    def test_cli_pass_and_negative_nonzero_under_actual_mode(self):
        a, b = self.f.receipts()
        for name, raw in (('contract', self.f.raw), ('stage-a', a), ('stage-b', b),
                          ('control', admission.canonical(self.f.control)),
                          ('challenger', admission.canonical(self.f.challenger))):
            (self.f.root / name).write_bytes(raw)
        command = [sys.executable, *(['-O'] if sys.flags.optimize else []),
            str(ROOT / 'tools/frozen_stage_ab_fairness.py')]
        for name in ('contract', 'stage-a', 'stage-b', 'control', 'challenger'):
            command += ['--' + name, str(self.f.root / name)]
        command += ['--generation-sha256', self.f.pin, '--stage-a-sha256', admission.digest(a),
            '--stage-b-sha256', admission.digest(b), '--frozen-root', str(self.f.frozen),
            '--evidence-root', str(self.f.evidence), '--environment-root', str(self.f.environment)]
        success = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertFalse(json.loads(success.stdout)['fairness_certified'])
        next(self.f.evidence.iterdir()).unlink()
        failure = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(failure.returncode, 2, failure.stderr)
        self.assertEqual(json.loads(failure.stdout)['status'], 'BLOCKED_FROZEN_FAIRNESS')


if __name__ == '__main__':
    print('frozen_stage_ab_fairness: Python optimize=' + str(sys.flags.optimize), flush=True)
    unittest.main(verbosity=2)

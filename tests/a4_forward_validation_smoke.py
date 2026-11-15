"""Independent A4 recording and delayed-scoring contract; synthetic evidence."""
import copy
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import a4_forward_validation as forward
from tools import a4_macro_learning as learning
from tools.macro_history_sources import digest, encoded
from tests.a4_macro_learning_smoke import fixture


def protocol(start):
    return dict(schema='a4-forward-validation-protocol-v1', purpose='FIXED_FORECAST_RESEARCH_ONLY',
        available_at=(learning.free.utc(start)-timedelta(minutes=1)).isoformat(),
        expires_at=(learning.free.utc(start)+timedelta(days=365)).isoformat(),
        targets=list(learning.analysis.TARGETS), horizons=list(learning.analysis.HORIZONS),
        outcomes=list(learning.OUTCOMES), embargo_contract='PRESERVE_ORIGIN_FAMILY_NOT_CHANGED_BY_SCORING')


def record_fixture(horizons=(1,)):
    payload, policy, resolver = fixture(20)
    first = payload['sessions'][0]
    created = (learning.free.utc(first['close_utc'])+timedelta(minutes=1)).isoformat()
    p = protocol(first['close_utc'])
    inputs = dict(schema='a4-forward-record-input-v1', decision_session=first['session'],
        report_sha256='a'*64, trial_sha256='b'*64, release_policy_sha256='c'*64,
        predictions=[dict(target='SPY', horizon_sessions=horizon, outcome='return',
            feature='funding:sofr_minus_iorb', evidence_family='FUNDING', estimate=.01,
            contribution_vs_training_mean=.004, created_at=created, decision_session=first['session'],
            reviewed_trial_sha256='b'*64, qualified_company_er=False) for horizon in horizons])
    with patch.object(forward, 'now', return_value=created):
        record = forward.record_forecasts(inputs, p, digest(encoded(p)))
    return payload, policy, resolver, p, inputs, record


class ForwardTests(unittest.TestCase):
    def score(self, record, p, payload, policy, resolver):
        return forward.score_record(record, digest(encoded(record)), digest(encoded(p)),
            payload, policy, digest(encoded(policy)), resolver, cutoff=payload['cutoff'])

    def test_record_does_not_read_labels_and_keeps_local_clock_limits(self):
        payload, policy, resolver, p, inputs, record = record_fixture()
        with patch.object(learning, 'score_predictions', side_effect=AssertionError('label access')):
            with patch.object(forward, 'now', return_value=record['recorded_at']):
                repeated = forward.record_forecasts(inputs, p, digest(encoded(p)))
        self.assertEqual(record, repeated)
        self.assertFalse(record['outcome_inputs_read'])
        self.assertFalse(record['independently_timestamped'])
        self.assertFalse(record['human_blindness_certified'])
        poisoned = copy.deepcopy(inputs); poisoned['actual_returns'] = [1, 2]
        with patch.object(forward, 'now', return_value=record['recorded_at']):
            with self.assertRaisesRegex(ValueError, 'INPUT_SCHEMA'):
                forward.record_forecasts(poisoned, p, digest(encoded(p)))

    def test_late_duplicate_foreign_target_and_unregistered_horizon_refuse(self):
        payload, policy, resolver, p, inputs, record = record_fixture()
        for change in ('late', 'duplicate', 'target', 'horizon', 'trial', 'feature', 'estimate'):
            q = copy.deepcopy(inputs); at = record['recorded_at']
            if change == 'late': at = record['entry_close_utc']
            if change == 'duplicate': q['predictions'].append(copy.deepcopy(q['predictions'][0]))
            if change == 'target': q['predictions'][0]['target'] = 'FOREIGN'
            if change == 'horizon': q['predictions'][0]['horizon_sessions'] = 504
            if change == 'trial': q['predictions'][0]['reviewed_trial_sha256'] = 'd'*64
            if change == 'feature': q['predictions'][0]['evidence_family'] = 'FOREIGN'
            if change == 'estimate': q['predictions'][0]['estimate'] = float('inf')
            with self.subTest(change=change), patch.object(forward, 'now', return_value=at):
                with self.assertRaises(ValueError): forward.record_forecasts(q, p, digest(encoded(p)))

    def test_external_protocol_and_full_family_are_mandatory(self):
        payload, policy, resolver, p, inputs, record = record_fixture()
        with self.assertRaisesRegex(ValueError, 'EXTERNAL_PROTOCOL_PIN'):
            forward.record_forecasts(inputs, p, '0'*64)
        for key, value in [('targets', ['SPY','QQQ']), ('horizons', [1,5]), ('embargo_contract', 'ZERO')]:
            q = copy.deepcopy(p); q[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                forward.record_forecasts(inputs, q, digest(encoded(q)))

    def test_matured_error_matches_existing_scorer_and_frozen_baseline(self):
        payload, policy, resolver, p, inputs, record = record_fixture()
        result = self.score(record, p, payload, policy, resolver)
        original = learning.score_predictions(inputs['predictions'], payload['prices'], payload['sessions'], payload['cutoff'])[0]
        row = result['results'][0]
        self.assertEqual(row['status'], 'MATURED_RESEARCH_OBSERVATION')
        self.assertEqual(row['actual'], original['actual'])
        self.assertEqual(row['squared_error'], original['squared_error'])
        self.assertAlmostEqual(row['baseline_squared_error'], (row['actual']-.006)**2)
        self.assertEqual(len(result['horizon_coverage']), 14*7)
        self.assertTrue(all(r['status']=='INSUFFICIENT_EVIDENCE' and r['calibrated_direction'] is None
                            for r in result['horizon_coverage']))
        self.assertFalse(result['validated_backtest'])
        self.assertFalse(result['model_fit_performed'])

    def test_immaturity_missing_path_and_negative_evidence_stay_distinct(self):
        payload, policy, resolver, p, inputs, record = record_fixture((1,252))
        result = self.score(record, p, payload, policy, resolver)
        self.assertEqual([r['status'] for r in result['results']], ['MATURED_RESEARCH_OBSERVATION','PENDING_MATURITY'])
        broken = copy.deepcopy(payload); broken['prices']['SPY'].pop(1)
        revised = copy.deepcopy(policy); revised['input_pins'] = [digest(encoded(broken))]
        result = self.score(record, p, broken, revised, resolver)
        self.assertEqual(result['results'][0]['status'], 'MISSING_COMPLETE_PRICE_PATH')
        self.assertEqual(result['results'][1]['status'], 'PENDING_MATURITY')

    def test_flat_realized_return_is_not_scored_as_a_down_move(self):
        payload, policy, resolver, p, inputs, record = record_fixture()
        for row in payload['prices']['SPY']: row['value']=100.
        policy['input_pins']=[digest(encoded(payload))]
        inputs['predictions'][0]['estimate']=-.01
        with patch.object(forward,'now',return_value=record['recorded_at']):
            record=forward.record_forecasts(inputs,p,digest(encoded(p)))
        result=self.score(record,p,payload,policy,resolver)
        self.assertEqual(result['results'][0]['actual'],0.)
        self.assertFalse(result['results'][0]['direction_correct'])
        self.assertEqual(result['direction_metric'],'THREE_WAY_RETURN_SIGN_WITH_EXACT_ZERO')

    def test_tampering_future_prices_expiry_and_missing_rights_block_scoring(self):
        payload, policy, resolver, p, inputs, record = record_fixture()
        changed = copy.deepcopy(record); changed['forecast_input']['predictions'][0]['estimate'] = .9
        with self.assertRaisesRegex(ValueError, 'EXTERNAL_RECORD_PIN'):
            forward.score_record(changed, digest(encoded(record)), digest(encoded(p)), payload, policy,
                digest(encoded(policy)), resolver, cutoff=payload['cutoff'])
        for change in ('future_price', 'rights', 'expired', 'bytes'):
            data, q, resolve = copy.deepcopy(payload), copy.deepcopy(policy), resolver
            if change == 'future_price':
                data['prices']['SPY'][-1]['available_at'] = (learning.free.utc(data['cutoff'])+timedelta(days=1)).isoformat()
                q['input_pins'] = [digest(encoded(data))]
            if change == 'rights': q['reviewed_rights_pins'] = []
            if change == 'expired': q['expires_at'] = data['cutoff']
            if change == 'bytes': resolve = lambda _: b'foreign'
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.score(record, p, data, q, resolve)

    def test_record_remains_scorable_after_its_original_protocol_expires(self):
        payload, policy, resolver, p, inputs, record = record_fixture()
        p['expires_at'] = (learning.free.utc(record['recorded_at'])+timedelta(minutes=1)).isoformat()
        with patch.object(forward, 'now', return_value=record['recorded_at']):
            record = forward.record_forecasts(inputs, p, digest(encoded(p)))
        self.assertEqual(self.score(record, p, payload, policy, resolver)['matured_count'], 1)

    def test_changed_math_identity_is_not_reauthorized_by_repinning_record(self):
        payload, policy, resolver, p, inputs, record = record_fixture()
        changed = copy.deepcopy(record)
        changed['implementation']['macro_technical_study.py'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'IMPLEMENTATION_CHANGED'):
            self.score(changed, p, payload, policy, resolver)

    def test_immutable_recovery_and_tampered_output_refusal(self):
        payload, policy, resolver, p, inputs, record = record_fixture()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'records'
            first = forward.write_result(root, record)
            self.assertEqual(first, forward.write_result(root, record))
            (root/first['path']).write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'OUTPUT_CONFLICT'): forward.write_result(root, record)

    def test_same_input_resumes_original_record_without_renewing_clock(self):
        payload, policy, resolver, p, inputs, record = record_fixture()
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(forward,'now',return_value=record['recorded_at']):
                first, first_ref, reused = forward.record_once(inputs,p,digest(encoded(p)),folder)
            self.assertFalse(reused)
            after_entry=(learning.free.utc(p['expires_at'])+timedelta(days=1)).isoformat()
            with patch.object(forward,'now',return_value=after_entry), \
                 patch.object(forward,'record_forecasts',side_effect=AssertionError('new record on recovery')):
                second, second_ref, reused = forward.record_once(inputs,p,digest(encoded(p)),folder)
            self.assertTrue(reused)
            self.assertEqual(first,second)
            self.assertEqual(first_ref,second_ref)
            references=list((Path(folder)/'record-references').glob('*.json'))
            self.assertEqual(len(references),1)
            references[0].write_bytes(b'corrupt')
            with self.assertRaises(ValueError): forward.record_once(inputs,p,digest(encoded(p)),folder)

    def test_inspection_separates_expired_report_from_forecast_readiness(self):
        payload, policy, resolver, p, inputs, record = record_fixture()
        start = payload['sessions'][0]
        cutoff = (learning.free.utc(start['close_utc'])+timedelta(minutes=20)).isoformat()
        report = dict(schema='market-analysis-report-v2', cutoff=start['close_utc'], session=start['session'],
            status='READY_RESEARCH_ONLY', market_assessment=dict(required_axes_ready=True,ready_axis_count=8),
            enhanced_readiness=dict(funding=True,liquidity=True,bank_credit=True,macro=True),
            candidate_reassessment_snapshot=dict(expires_at=(learning.free.utc(cutoff)+timedelta(minutes=2)).isoformat()),
            source_and_pit_admission=False,source_admission_allowed=False,ledger_mutation_allowed=False,
            order_generation_allowed=False,target_book_write_allowed=False,historical_evidence={})
        report['content_sha256'] = forward.market.context.digest(report)
        result = forward.inspect_report(report,digest(encoded(report)),cutoff=cutoff)
        self.assertEqual(result['diagnosis_status'],'READY_RESEARCH_ONLY')
        self.assertEqual(result['forward_validation_status'],'NO_FIXED_FORECASTS')
        self.assertFalse(result['standalone_operation_complete'])
        later = (learning.free.utc(cutoff)+timedelta(minutes=3)).isoformat()
        result = forward.inspect_report(report,digest(encoded(report)),cutoff=later)
        self.assertEqual(result['diagnosis_status'],'BLOCKED')
        self.assertTrue(result['report_expired'])

    def test_external_cwd_cli_empty_record_is_not_a_forecast_or_completion(self):
        current = forward.now(); session = forward.market.current_session(current)
        first, entry = forward.entry_close(session)
        p = protocol(first)
        p['expires_at'] = (learning.free.utc(entry)+timedelta(minutes=1)).isoformat()
        inputs = dict(schema='a4-forward-record-input-v1', decision_session=session,
            report_sha256='a'*64, trial_sha256=None, release_policy_sha256=None, predictions=[])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, value in [('input', inputs), ('protocol', p)]: (root/(name+'.json')).write_bytes(encoded(value))
            script = Path(forward.__file__).resolve()
            process = subprocess.run([sys.executable, str(script), 'record', '--input', str(root/'input.json'),
                '--input-sha256', digest(encoded(inputs)), '--protocol', str(root/'protocol.json'),
                '--protocol-sha256', digest(encoded(p)), '--output-dir', str(root/'output')],
                cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stdout+process.stderr)
            metadata = json.loads(process.stdout)
            self.assertEqual(metadata['status'], 'NO_FIXED_FORECASTS')
            body = json.loads((root/'output'/metadata['path']).read_bytes())
            self.assertFalse(body['independently_timestamped'])
            self.assertNotIn('forecast_input', metadata)

    def test_cli_failure_has_private_diagnostic_and_metadata_only_console(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); bad=root/'bad.json';bad.write_bytes(b'private invalid input')
            process=subprocess.run([sys.executable,str(Path(forward.__file__).resolve()),'inspect',
                '--report',str(bad),'--report-sha256','0'*64,'--output-dir',str(root/'failure')],
                cwd=root,capture_output=True,text=True,timeout=30)
            self.assertEqual(process.returncode,2)
            metadata=json.loads(process.stdout)
            self.assertEqual(metadata['status'],'BLOCKED')
            self.assertNotIn('private invalid input',process.stdout+process.stderr)
            failure=json.loads((root/'failure'/metadata['path']).read_bytes())
            self.assertEqual(failure['schema'],'a4-forward-validation-failure-v1')
            self.assertEqual(failure['detail'],'A4_FORWARD_FILE_HASH')
            self.assertFalse(failure['accepted_model_changed'])

    def test_cli_expired_report_is_a_failed_readiness_check(self):
        report=dict(schema='market-analysis-report-v2',cutoff='2018-01-02T21:20:00Z',session='2018-01-02',
            status='READY_RESEARCH_ONLY',market_assessment=dict(required_axes_ready=True,ready_axis_count=8),
            enhanced_readiness=dict(funding=True,liquidity=True,bank_credit=True,macro=True),
            candidate_reassessment_snapshot=dict(expires_at='2018-01-03T21:00:00Z'),
            source_and_pit_admission=False,source_admission_allowed=False,ledger_mutation_allowed=False,
            order_generation_allowed=False,target_book_write_allowed=False,historical_evidence={})
        report['content_sha256']=forward.market.context.digest(report)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'expired.json';source.write_bytes(encoded(report))
            process=subprocess.run([sys.executable,str(Path(forward.__file__).resolve()),'inspect',
                '--report',str(source),'--report-sha256',digest(encoded(report)),
                '--output-dir',str(root/'diagnostics')],cwd=root,capture_output=True,text=True,timeout=30)
            self.assertEqual(process.returncode,2)
            metadata=json.loads(process.stdout)
            self.assertEqual(metadata['status'],'BLOCKED')
            result=json.loads((root/'diagnostics'/metadata['path']).read_bytes())
            self.assertTrue(result['report_expired'])
            self.assertFalse(result['standalone_operation_complete'])


if __name__ == '__main__':
    unittest.main()

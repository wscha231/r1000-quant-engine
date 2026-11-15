#!/usr/bin/env python3
"""Independent A4 fixed-forecast records and maturity-only research scoring.

Recording accepts no price/label input. Scoring reuses the existing original,
rights, policy, calendar and next-close gates. A local clock/hash is not an
independent timestamp, human blindness, Source admission or model promotion.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import a4_macro_learning as learning
from tools import market_analysis_engine as market
from tools.macro_history_sources import digest, encoded, exclusive
from tools.run_a4_research_cycle import load_learning

MAX_BYTES = 8 * 1024**2
MAX_PREDICTIONS = 4096
SAFETY = dict(source_admitted=False, historical_pit_certified=False,
    independently_timestamped=False, human_blindness_certified=False,
    validated_backtest=False, eligible_for_selector=False,
    accepted_model_changed=False, accepted_portfolio_changed=False,
    a3_executed=False, a5_executed=False, orders_generated=False)
PREDICTION_KEYS = frozenset(('target', 'horizon_sessions', 'outcome', 'feature',
    'evidence_family', 'estimate', 'contribution_vs_training_mean', 'created_at',
    'decision_session', 'reviewed_trial_sha256', 'qualified_company_er'))
INPUT_KEYS = frozenset(('schema', 'decision_session', 'report_sha256',
    'trial_sha256', 'release_policy_sha256', 'predictions'))
PROTOCOL_KEYS = frozenset(('schema', 'purpose', 'available_at', 'expires_at',
    'targets', 'horizons', 'outcomes', 'embargo_contract'))


def need(condition, code):
    market.need(condition, 'A4_FORWARD_' + code)


def pin(value):
    need(type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None, 'HASH')
    return value


def now():
    return datetime.now(timezone.utc).isoformat()


def implementation():
    paths = [Path(__file__), *(Path(module.__file__) for module in
        (learning, learning.study, learning.analysis, learning.vintage, learning.free, market, market.context))]
    return {path.name: digest(path.read_bytes()) for path in paths}


def exact(value, keys, code):
    need(type(value) is dict and set(value) == set(keys), code)


def entry_close(session):
    day = learning.free.iso_date(session)
    schedule = learning.mcal.get_calendar('NYSE').schedule(
        start_date=day, end_date=day + timedelta(days=14))
    need(len(schedule) >= 2 and schedule.index[0].date() == day, 'DECISION_SESSION')
    return schedule.market_close.iloc[0].isoformat(), schedule.market_close.iloc[1].isoformat()


def validate_protocol(protocol, expected_pin):
    exact(protocol, PROTOCOL_KEYS, 'PROTOCOL_SCHEMA')
    need(digest(encoded(protocol)) == pin(expected_pin), 'EXTERNAL_PROTOCOL_PIN')
    need(protocol['schema'] == 'a4-forward-validation-protocol-v1'
         and protocol['purpose'] == 'FIXED_FORECAST_RESEARCH_ONLY', 'PROTOCOL_PURPOSE')
    need(protocol['targets'] == list(learning.analysis.TARGETS)
         and protocol['horizons'] == list(learning.analysis.HORIZONS)
         and protocol['outcomes'] == list(learning.OUTCOMES), 'DECLARED_FAMILY')
    need(protocol['embargo_contract'] == 'PRESERVE_ORIGIN_FAMILY_NOT_CHANGED_BY_SCORING',
         'EMBARGO_CONTRACT')
    need(learning.free.utc(protocol['available_at']) < learning.free.utc(protocol['expires_at']),
         'PROTOCOL_CLOCK')


def validate_forecasts(payload, protocol, recorded_at):
    exact(payload, INPUT_KEYS, 'INPUT_SCHEMA')
    need(payload['schema'] == 'a4-forward-record-input-v1', 'INPUT_SCHEMA')
    pin(payload['report_sha256'])
    predictions = payload['predictions']
    need(type(predictions) is list and len(predictions) <= MAX_PREDICTIONS, 'PREDICTION_BUDGET')
    start, entry = entry_close(payload['decision_session'])
    recorded = learning.free.utc(recorded_at)
    need(learning.free.utc(start) <= recorded < learning.free.utc(entry), 'RECORD_ENTRY_WINDOW')
    need(learning.free.utc(protocol['available_at']) <= recorded < learning.free.utc(protocol['expires_at']),
         'PROTOCOL_EXPIRED')
    if predictions:
        pin(payload['trial_sha256']); pin(payload['release_policy_sha256'])
    else:
        need(payload['trial_sha256'] is None and payload['release_policy_sha256'] is None,
             'EMPTY_FORECAST_ORIGIN')
    identities = set()
    for prediction in predictions:
        exact(prediction, PREDICTION_KEYS, 'PREDICTION_SCHEMA')
        target, horizon, outcome = (prediction[k] for k in ('target', 'horizon_sessions', 'outcome'))
        need(target in protocol['targets'] and type(horizon) is int
             and horizon in protocol['horizons'] and outcome in protocol['outcomes'], 'PREDICTION_SCOPE')
        need(prediction['feature'] in learning.FEATURES
             and prediction['evidence_family'] == learning.FEATURES[prediction['feature']]['family'],
             'FEATURE_FAMILY')
        need(prediction['decision_session'] == payload['decision_session']
             and prediction['reviewed_trial_sha256'] == payload['trial_sha256']
             and prediction['qualified_company_er'] is False, 'PREDICTION_ORIGIN')
        created = learning.free.utc(prediction['created_at'])
        need(learning.free.utc(start) <= created <= recorded
             and learning.free.utc(protocol['available_at']) <= created, 'PREDICTION_CLOCK')
        need(type(prediction['estimate']) in (int, float)
             and type(prediction['contribution_vs_training_mean']) in (int, float), 'PREDICTION_NUMERIC_TYPE')
        estimate = learning.free.number(prediction['estimate'])
        contribution = learning.free.number(prediction['contribution_vs_training_mean'])
        need(estimate is not None and contribution is not None, 'PREDICTION_VALUE')
        learning.free.number(estimate - contribution)
        identity = (target, horizon, outcome, prediction['feature'])
        need(identity not in identities, 'DUPLICATE_PREDICTION')
        identities.add(identity)
    return entry


def record_forecasts(payload, protocol, expected_protocol_pin):
    """No price argument or resolver exists in this recording interface."""
    validate_protocol(protocol, expected_protocol_pin)
    recorded_at = now()  # CLI deliberately provides no historical clock override.
    entry = validate_forecasts(payload, protocol, recorded_at)
    result = dict(schema='a4-local-forward-record-v1',
        status='FIXED_LOCAL_RECORD' if payload['predictions'] else 'NO_FIXED_FORECASTS',
        recorded_at=recorded_at, entry_close_utc=entry,
        protocol_sha256=expected_protocol_pin, protocol=copy.deepcopy(protocol),
        forecast_input_sha256=digest(encoded(payload)), forecast_input=copy.deepcopy(payload),
        implementation=implementation(),
        timing_scope='LOCAL_PROCESS_CLOCK_ONLY_NOT_INDEPENDENT_PUBLICATION_PROOF',
        outcome_inputs_read=False, **SAFETY)
    need(len(encoded(result)) <= MAX_BYTES, 'RECORD_SIZE')
    return result


def verify_record(record, expected_record_pin, expected_protocol_pin, cutoff):
    keys = {'schema', 'status', 'recorded_at', 'entry_close_utc', 'protocol_sha256',
            'protocol', 'forecast_input_sha256', 'forecast_input', 'timing_scope',
            'implementation', 'outcome_inputs_read', *SAFETY}
    exact(record, keys, 'RECORD_SCHEMA')
    need(digest(encoded(record)) == pin(expected_record_pin), 'EXTERNAL_RECORD_PIN')
    need(record['schema'] == 'a4-local-forward-record-v1'
         and all(record[k] is False for k in SAFETY) and record['outcome_inputs_read'] is False,
         'RECORD_AUTHORITY')
    need(record['protocol_sha256'] == expected_protocol_pin, 'RECORD_PROTOCOL_BINDING')
    need(record['implementation'] == implementation(), 'IMPLEMENTATION_CHANGED')
    validate_protocol(record['protocol'], expected_protocol_pin)
    need(record['forecast_input_sha256'] == digest(encoded(record['forecast_input'])), 'INPUT_HASH')
    entry = validate_forecasts(record['forecast_input'], record['protocol'], record['recorded_at'])
    need(record['entry_close_utc'] == entry
         and learning.free.utc(record['recorded_at']) <= learning.free.utc(cutoff), 'RECORD_CLOCK')
    expected_status = 'FIXED_LOCAL_RECORD' if record['forecast_input']['predictions'] else 'NO_FIXED_FORECASTS'
    need(record['status'] == expected_status
         and record['timing_scope'] == 'LOCAL_PROCESS_CLOCK_ONLY_NOT_INDEPENDENT_PUBLICATION_PROOF',
         'RECORD_SCOPE')


def score_record(record, expected_record_pin, expected_protocol_pin,
                 payload, policy, expected_policy_pin, resolver, *, cutoff):
    """A separate caller supplies qualified prices only after recording."""
    verify_record(record, expected_record_pin, expected_protocol_pin, cutoff)
    learning.validate_inputs(payload, policy, expected_policy_pin, resolver)
    need(learning.free.utc(policy['available_at']) <= learning.free.utc(cutoff)
         < learning.free.utc(policy['expires_at'])
         and learning.free.utc(payload['cutoff']) <= learning.free.utc(cutoff), 'SCORING_POLICY_CLOCK')
    for rows in payload['prices'].values():
        for row in rows:
            need(learning.free.utc(row['available_at']) <= learning.free.utc(payload['cutoff']),
                 'PRICE_AFTER_INPUT_CUTOFF')
    predictions = record['forecast_input']['predictions']
    scores = learning.score_predictions(predictions, payload['prices'], payload['sessions'], cutoff)
    sessions = [s['session'] for s in payload['sessions']]
    rows = []
    for prediction, score in zip(predictions, scores):
        position = sessions.index(prediction['decision_session'])
        mark = position + prediction['horizon_sessions'] + 1
        baseline = prediction['estimate'] - prediction['contribution_vs_training_mean']
        actual = score['actual']
        status = ('MATURED_RESEARCH_OBSERVATION' if actual is not None else
                  'PENDING_MATURITY' if mark >= len(sessions) else 'MISSING_COMPLETE_PRICE_PATH')
        rows.append(dict(prediction_sha256=score['prediction_sha256'], target=prediction['target'],
            horizon_sessions=prediction['horizon_sessions'], outcome=prediction['outcome'],
            feature=prediction['feature'], status=status, actual=actual,
            squared_error=score['squared_error'],
            baseline_squared_error=None if actual is None else (actual - baseline)**2,
            absolute_error=None if actual is None else abs(actual - prediction['estimate']),
            direction_correct=None if actual is None or prediction['outcome'] != 'return' else
                ((actual > 0)-(actual < 0)) == ((prediction['estimate'] > 0)-(prediction['estimate'] < 0)),
            independent_sample_count=None, eligible_for_selector=False))
    coverage = []
    for target in learning.analysis.TARGETS:
        for horizon in learning.analysis.HORIZONS:
            members = [r for r in rows if r['target'] == target and r['horizon_sessions'] == horizon]
            matured = sum(r['status'] == 'MATURED_RESEARCH_OBSERVATION' for r in members)
            coverage.append(dict(target=target, horizon_sessions=horizon, forecast_count=len(members),
                matured_count=matured, pending_count=sum(r['status'] == 'PENDING_MATURITY' for r in members),
                missing_path_count=sum(r['status'] == 'MISSING_COMPLETE_PRICE_PATH' for r in members),
                status='INSUFFICIENT_EVIDENCE', calibrated_direction=None,
                independent_sample_count=None))
    result = dict(schema='a4-forward-validation-score-v1',
        status='FIXED_FORECAST_ERRORS_RESEARCH_ONLY' if predictions else 'NO_FIXED_FORECASTS',
        cutoff=cutoff, record_sha256=expected_record_pin, protocol_sha256=expected_protocol_pin,
        learning_input_sha256=digest(encoded(payload)), learning_policy_sha256=expected_policy_pin,
        results=rows, horizon_coverage=coverage, forecasts_checked=len(scores),
        forecasts_scored=sum(r['status'] == 'MATURED_RESEARCH_OBSERVATION' for r in rows),
        matured_count=sum(r['status'] == 'MATURED_RESEARCH_OBSERVATION' for r in rows),
        implementation=implementation(),
        model_fit_performed=False, portfolio_cost_or_return_claim=False,
        direction_metric='THREE_WAY_RETURN_SIGN_WITH_EXACT_ZERO',
        retrospective_outcome_blindness_claim=False,
        observation_count_is_independent_sample_count=False, **SAFETY)
    need(len(encoded(result)) <= MAX_BYTES, 'SCORE_SIZE')
    return result


def inspect_report(report, expected_report_pin, *, cutoff):
    """Current diagnosis is distinct from a release or completed operation."""
    need(digest(encoded(report)) == pin(expected_report_pin), 'REPORT_PIN')
    need(report.get('schema') == 'market-analysis-report-v2', 'REPORT_SCHEMA')
    need(report.get('content_sha256') == market.context.digest(
        {k:v for k,v in report.items() if k != 'content_sha256'}), 'REPORT_CONTENT_HASH')
    need(learning.free.utc(report['cutoff']) <= learning.free.utc(cutoff), 'FUTURE_REPORT')
    for key in ('source_and_pit_admission', 'source_admission_allowed', 'ledger_mutation_allowed',
                'order_generation_allowed', 'target_book_write_allowed'):
        need(report.get(key) is False, 'REPORT_AUTHORITY')
    current = report['session'] == market.current_session(cutoff)
    assessment = report.get('market_assessment', {})
    enhanced = report.get('enhanced_readiness', {})
    snapshot = report.get('candidate_reassessment_snapshot', {})
    need(type(snapshot) is dict and 'expires_at' in snapshot
         and learning.free.utc(snapshot['expires_at']) > learning.free.utc(report['cutoff']), 'REPORT_EXPIRY')
    expired = learning.free.utc(cutoff) >= learning.free.utc(snapshot['expires_at'])
    ready = (current and not expired and report['status'] == 'READY_RESEARCH_ONLY'
             and assessment.get('required_axes_ready') is True
             and set(enhanced) == {'funding', 'liquidity', 'bank_credit', 'macro'}
             and all(value is True for value in enhanced.values()))
    predictions = report.get('historical_evidence', {}).get('predictions', [])
    need(type(predictions) is list and len(predictions) <= MAX_PREDICTIONS, 'REPORT_PREDICTIONS')
    return dict(schema='a4-independent-readiness-v1', cutoff=cutoff,
        report_sha256=expected_report_pin, report_cutoff=report['cutoff'], session=report['session'],
        current_session=current, report_expired=expired, report_expires_at=snapshot['expires_at'],
        diagnosis_status='READY_RESEARCH_ONLY' if ready else 'BLOCKED',
        native_ready_axes=assessment.get('ready_axis_count'), enhanced_readiness=enhanced,
        forecast_count=len(predictions), forward_validation_status='RECORD_AND_SCORE_REQUIRED' if predictions else 'NO_FIXED_FORECASTS',
        standalone_operation_complete=False, scheduled_operation_verified=False,
        historical_price_clock_verified=False, source_requests=0, model_fit_performed=False, **SAFETY)


def read_json(path, expected_pin, limit=MAX_BYTES):
    path = Path(path)
    need(not any(p.is_symlink() for p in (path, *path.parents)), 'INPUT_SYMLINK')
    raw = market.bounded(path, limit)
    need(digest(raw) == pin(expected_pin), 'FILE_HASH')
    return market.clock.decode(raw)


def write_result(root, value):
    root = Path(root)
    need(not any(p.is_symlink() for p in (root, *root.parents)), 'OUTPUT_SYMLINK')
    root.mkdir(parents=True, exist_ok=True)
    body = encoded(value)
    path = root / (digest(body) + '.json')
    if path.exists():
        need(market.bounded(path, MAX_BYTES) == body, 'OUTPUT_CONFLICT')
    else:
        exclusive(path, body)
    need(market.bounded(path, MAX_BYTES) == body, 'OUTPUT_READBACK')
    return dict(path=path.name, sha256=digest(body), bytes=len(body), durable_remote_verified=False)


def record_once(payload, protocol, expected_protocol_pin, output_dir):
    """Commit data before a bounded local recovery reference, never a model head."""
    validate_protocol(protocol, expected_protocol_pin)
    root = Path(output_dir)
    need(not any(p.is_symlink() for p in (root, *root.parents)), 'OUTPUT_SYMLINK')
    identity = dict(forecast_input_sha256=digest(encoded(payload)), protocol_sha256=expected_protocol_pin)
    reference_path = root / 'record-references' / (digest(encoded(identity)) + '.json')
    if reference_path.exists():
        need(not any(p.is_symlink() for p in (reference_path, *reference_path.parents)), 'REFERENCE_SYMLINK')
        reference = market.clock.decode(market.bounded(reference_path, 4096))
        exact(reference, {'schema', 'forecast_input_sha256', 'protocol_sha256', 'record_sha256'}, 'REFERENCE_SCHEMA')
        need(reference['schema'] == 'a4-local-forward-reference-v1'
             and all(reference[k] == v for k,v in identity.items()), 'REFERENCE_IDENTITY')
        record_path = root / (pin(reference['record_sha256']) + '.json')
        record = read_json(record_path, reference['record_sha256'])
        verify_record(record, reference['record_sha256'], expected_protocol_pin, now())
        need(record['forecast_input'] == payload, 'REFERENCE_INPUT_BINDING')
        return record, write_result(root, record), True
    record = record_forecasts(payload, protocol, expected_protocol_pin)
    result_ref = write_result(root, record)
    reference = dict(schema='a4-local-forward-reference-v1', **identity, record_sha256=result_ref['sha256'])
    body = encoded(reference)
    exclusive(reference_path, body)
    need(market.bounded(reference_path, 4096) == body, 'REFERENCE_READBACK')
    return record, result_ref, False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    record = sub.add_parser('record')
    record.add_argument('--input', required=True); record.add_argument('--input-sha256', required=True)
    record.add_argument('--protocol', required=True); record.add_argument('--protocol-sha256', required=True)
    score = sub.add_parser('score')
    score.add_argument('--record', required=True); score.add_argument('--record-sha256', required=True)
    score.add_argument('--protocol-content-sha256', required=True)
    score.add_argument('--learning-input-root', required=True); score.add_argument('--learning-policy-sha256', required=True)
    inspect = sub.add_parser('inspect')
    inspect.add_argument('--report', required=True); inspect.add_argument('--report-sha256', required=True)
    for command in (record, score, inspect): command.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    try:
        ref = None
        reused = False
        if args.command == 'record':
            inputs = read_json(args.input, args.input_sha256)
            protocol = read_json(args.protocol, args.protocol_sha256, 64*1024)
            result, ref, reused = record_once(inputs, protocol, digest(encoded(protocol)), args.output_dir)
        elif args.command == 'score':
            item = read_json(args.record, args.record_sha256)
            payload, policy, resolver = load_learning(args.learning_input_root, args.learning_policy_sha256)
            result = score_record(item, digest(encoded(item)), args.protocol_content_sha256,
                payload, policy, digest(encoded(policy)), resolver, cutoff=now())
        else:
            report = read_json(args.report, args.report_sha256)
            result = inspect_report(report, digest(encoded(report)), cutoff=now())
        if ref is None:
            ref = write_result(args.output_dir, result)
        # Public console contains metadata only; full numerical output is private.
        print(json.dumps(dict(status=result.get('status', result.get('diagnosis_status')), reused=reused, **ref)))
        if args.command == 'inspect' and result['diagnosis_status'] == 'BLOCKED':
            return 2
    except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError) as error:
        detail = str(error) if isinstance(error, ValueError) else None
        if type(detail) is not str or re.fullmatch('[A-Z][A-Z0-9_]{0,100}', detail) is None:
            detail = None
        failure = dict(schema='a4-forward-validation-failure-v1', status='BLOCKED',
            command=args.command, recorded_at=now(), detail=detail,
            blocker='A4_FORWARD_INPUT_CLOCK_POLICY_OR_IO_NOT_VERIFIED', **SAFETY)
        try:
            reference = write_result(args.output_dir, failure)
        except (ValueError, OSError, TypeError, OverflowError, RecursionError):
            reference = dict(diagnostic_persisted=False)
        print(json.dumps(dict(status='BLOCKED', blocker=failure['blocker'], **reference)))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

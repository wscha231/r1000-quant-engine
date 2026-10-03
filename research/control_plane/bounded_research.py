"""A bounded, offline A8 preview of the existing forward risk-outcome archive.

This is an adapter for A0's existing board, not a worker or another registry.
It has no API, shell, notification, accepted-state, or experiment execution path.
Producer metadata must be refreshed by a trusted caller; local hashes do not
authenticate GitHub/Drive or certify the underlying price/PIT semantics.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import time
from bisect import bisect_right
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from tools import run_agent_board as board
from tools.check_run287_do_not_repeat import evaluate_candidate
from tools.manage_run287_risk_outcome_accepted_heads import OUTCOME_FALSE_SAFETY_FIELDS

SCHEMA = 'bounded-research-preview-v1'
ARCHIVE = 'run287-risk-outcome-archive-v1'
FLAGS = ('portfolio_transition_allowed', 'orders_generated', 'target_books_mutated',
         'historical_cagr_mdd_evidence_changed', 'production_activation_allowed',
         'live_trading_enabled')
# Required diagnostics in docs/run287_risk_outcome_archive_contract.json.
CORE_METRICS = ('ticker_total_return', 'benchmark_total_return', 'spy_excess_total_return',
                'ticker_max_drawdown', 'ticker_recovery_from_trough', 'ticker_max_gain')
ACTIONABLE_METRICS = ('actionable_ticker_total_return', 'actionable_spy_excess_total_return',
                      'actionable_ticker_max_drawdown')
ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'research/control_plane/bounded_research_v1.json'
REGISTRY = ROOT / 'docs/run287_do_not_repeat_registry.json'


def require(value, reason):
    if not value:
        raise board.ContractError(reason)


def strict_json(raw):
    def pairs(rows):
        value = {}
        for key, item in rows:
            require(key not in value, 'duplicate_json_key')
            value[key] = item
        return value
    def invalid(_):
        raise board.ContractError('nonfinite_json')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def raw_hash(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical_hash(value):
    return raw_hash(json.dumps(value, sort_keys=True, separators=(',', ':'),
                               ensure_ascii=False, allow_nan=False).encode())


def native_path(path):
    namespaces = ('\\\\?\\', '\\\\.\\', '\\??\\')
    if os.name == 'nt':
        require(not str(Path(path)).startswith(namespaces), 'noncanonical_path_namespace')
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        try:
            st = part.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(st.st_mode) and not (getattr(st, 'st_file_attributes', 0) & 1024),
                'reparse_path')
        if part == path and stat.S_ISREG(st.st_mode):
            require(st.st_nlink == 1, 'nonregular_or_linked_file')
    canonical = path.resolve()
    if os.name == 'nt':
        require(not str(canonical).startswith(namespaces), 'noncanonical_path_namespace')
    return canonical


def output_geometry(root, out):
    root, out = native_path(root), native_path(out)
    require(not out.is_relative_to(root) and not root.is_relative_to(out), 'input_output_overlap')
    return root, out


@contextmanager
def exclusive_lock(out):
    # Same O_EXCL/no-expiry-stealing pattern as the existing outcome producer.
    with board.exclusive_output_lock(native_path(out)):
        yield


def configuration(path=CONFIG):
    value = board.read_json(path)
    require(value.get('schema_version') == 'bounded-research-config-v1' and
            value.get('enabled') is False and value.get('mode') == 'RESEARCH_ONLY',
            'activation_requires_separate_scoped_contract')
    limits = value['preview']
    require(set(limits) == {'timeout_seconds', 'max_input_bytes', 'max_output_bytes', 'max_events',
            'max_model_calls', 'max_tokens', 'daily_cost_usd', 'monthly_cost_usd',
            'io_retries', 'comparisons'}, 'budget_schema')
    bounded_names = {'timeout_seconds', 'max_input_bytes', 'max_output_bytes', 'max_events'}
    for name, maximum in [('timeout_seconds', 30), ('max_input_bytes', 4194304),
                          ('max_output_bytes', 4194304), ('max_events', 10000)]:
        require(type(limits[name]) is int and 0 < limits[name] <= maximum, 'invalid_finite_budget:' + name)
    for name in set(limits) - bounded_names:
        require(type(limits[name]) is int and limits[name] == 0, 'unapproved_paid_or_execution_budget')
    return value


def bounded_read(path, limit):
    path = native_path(path)
    require(path.is_file() and path.stat().st_size <= limit, 'input_missing_or_byte_budget')
    with path.open('rb') as stream:
        raw = stream.read(limit)
    # Detect growth/short reads without spending a byte beyond the allowance.
    require(len(raw) == path.stat().st_size, 'input_changed_during_read')
    return raw


def write_scratch(path, value):
    native_path(path)
    native_path(path.with_name(path.name + '.tmp'))
    board.write_json(path, value)


def metric(value):
    if value is None:
        return {'status': 'NOT_AVAILABLE', 'value': None}
    require(type(value) in (int, float) and math.isfinite(value), 'invalid_metric')
    return {'status': 'PRODUCER_DIAGNOSTIC_ONLY', 'value': value}


def inspect_events(events, sessions, now, limit, check_deadline=lambda: None):
    """Preserve producer cohort and intent; never derive intent from outcomes."""
    require(len(events) <= limit, 'event_budget_exhausted')
    require(isinstance(sessions, list) and len(sessions) <= 20000 and
            sessions == sorted(set(sessions)), 'calendar_conflict')
    for session in sessions:
        check_deadline()
        require(date.fromisoformat(session).isoformat() == session, 'calendar_date_invalid')
    signals, outcomes, ids = {}, {}, set()
    for event in events:
        check_deadline()
        require(isinstance(event, dict) and event.get('schema_version') == ARCHIVE, 'producer_event_schema')
        eid = event.get('event_id')
        require(isinstance(eid, str) and re.fullmatch('[0-9a-f]{64}', eid), 'event_id_missing')
        require(eid not in ids, 'duplicate_event_delivery_in_snapshot')
        ids.add(eid)
        require(event.get('review_only') is True and all(event.get(flag) is False for flag in FLAGS),
                'source_authority_conflict')
        require(event.get('data_class', 'Model Proposal') == 'Model Proposal', 'data_class_mix')
        require(board.timestamp(event['recorded_at_utc']) <= now, 'future_event')
        recorded = board.timestamp(event['recorded_at_utc'])
        decision = event['decision_date']
        require(date.fromisoformat(decision).isoformat() == decision and decision <= now.date().isoformat(),
                'future_or_invalid_decision')
        require(decision <= recorded.date().isoformat(), 'event_clock_conflict')
        first_later = bisect_right(sessions, decision)
        require(first_later > 0 and sessions[first_later - 1] == decision, 'decision_calendar_missing')
        oid = event['observation_id']
        require(isinstance(oid, str) and re.fullmatch('[0-9a-f]{24}', oid), 'observation_id_invalid')
        require(event['family'] in ('candidate', 'held') and event['benchmark_ticker'] == 'SPY',
                'cohort_or_benchmark_conflict')
        portfolio = event.get('portfolio_kind', '')
        require(isinstance(portfolio, str) and
                (portfolio == '' if event['family'] == 'candidate' else
                 portfolio == portfolio.strip().lower() and portfolio not in ('', 'nan', 'none', 'null')),
                'family_portfolio_identity_conflict')
        ticker = event['ticker']
        require(isinstance(ticker, str) and ticker == ticker.strip().upper().replace('.', '-') and
                ticker not in ('', 'NAN', 'NONE', 'NULL', 'CASH', '__CASH__'), 'security_identity_conflict')
        expected_oid = raw_hash(f"{ARCHIVE}|{event['family']}|{decision}|{portfolio}|{ticker}".encode())[:24]
        require(oid == expected_oid, 'security_observation_conflict')
        if event['event_type'] == 'risk_signal_observed':
            require(oid not in signals, 'conflicting_decision')
            if event['family'] == 'held':
                weight = event.get('marked_weight')
                require(type(weight) in (int, float) and math.isfinite(weight) and weight > 1e-12,
                        'held_weight_identity_conflict')
            snapshot_keys = ('family', 'decision_date', 'ticker', 'risk_state', 'advisory_action', 'reason_codes')
            snapshot_keys += (('history_observations', 'signal_return_1d', 'signal_spy_excess_return_1d',
                'signal_return_21d', 'signal_spy_excess_return_21d', 'signal_drawdown_63d', 'proposed_entries')
                if event['family'] == 'candidate' else
                ('portfolio_kind', 'marked_weight', 'official_prior_weight', 'scenario_keys'))
            snapshot = {key: event[key] for key in snapshot_keys}
            require(event['signal_snapshot_sha256'] == canonical_hash(snapshot), 'immutable_intent_conflict')
            expected = raw_hash(f'{ARCHIVE}|risk_signal_observed|{oid}'.encode())
            require(eid == expected, 'signal_identity_conflict')
            signals[oid] = event
        elif event['event_type'] == 'forward_outcome_observed':
            horizon = event['horizon_trading_days']
            require(type(horizon) is int and horizon in (1, 5, 21, 63, 126), 'unregistered_horizon')
            require((oid, horizon) not in outcomes, 'conflicting_outcome')
            expected = raw_hash(f'{ARCHIVE}|forward_outcome_observed|{oid}|{horizon}'.encode())
            require(eid == expected, 'outcome_identity_conflict')
            require(event['outcome_status'] == 'completed' and event['price_basis'] == 'adjusted_close',
                    'unresolved_outcome')
            for name in CORE_METRICS + ACTIONABLE_METRICS:
                value = event.get(name)
                if name in ACTIONABLE_METRICS and horizon == 1:
                    require(name in event and value is None, 'invalid_1d_actionable_metric:' + name)
                else:
                    require(type(value) in (int, float) and math.isfinite(value),
                            'incomplete_completed_outcome:' + name)
            require(event.get('actionable_metrics_status') ==
                    ('not_applicable_at_1d' if horizon == 1 else 'completed'), 'actionable_status_conflict')
            require(decision < event['outcome_date'] <= event['evaluated_as_of_date'] <= now.date().isoformat(),
                    'future_outcome')
            require(event['evaluated_as_of_date'] <= recorded.date().isoformat(), 'event_clock_conflict')
            require(first_later + horizon <= len(sessions) and
                    sessions[first_later + horizon - 1] == event['outcome_date'], 'label_immature')
            require(event['actionable_start_date'] == sessions[first_later], 'execution_clock_conflict')
            for name in ('ticker_price_path_sha256', 'benchmark_price_path_sha256'):
                require(isinstance(event.get(name), str) and re.fullmatch('[0-9a-f]{64}', event[name]),
                        'price_provenance_missing')
            outcomes[(oid, horizon)] = event
        else:
            raise board.ContractError('unknown_producer_event')
    for (oid, _), outcome in outcomes.items():
        check_deadline()
        require(oid in signals, 'outcome_outside_original_cohort')
        require(all(outcome.get(k) == signals[oid].get(k) for k in
                    ('family', 'decision_date', 'ticker', 'risk_state', 'benchmark_ticker')),
                'outcome_decision_conflict')
        require(board.timestamp(outcome['recorded_at_utc']) >=
                board.timestamp(signals[oid]['recorded_at_utc']), 'event_clock_conflict')
    rows = []
    for oid, signal in sorted(signals.items()):
        check_deadline()
        row = {'decision_id': oid, 'ticker': signal['ticker'], 'family': signal['family'],
            'data_class': 'Model Proposal' if signal['family'] == 'candidate' else 'UNKNOWN',
            'decision_date': signal['decision_date'], 'action': signal['advisory_action'] or 'UNKNOWN',
            'reason': signal['reason_codes'] or 'UNKNOWN', 'intent_sha256': signal['signal_snapshot_sha256'],
            'intent_origin': 'ORIGINAL_PRODUCER_SNAPSHOT', 'thesis': 'UNKNOWN', 'er': 'UNKNOWN',
            'security_identity': 'UNKNOWN', 'public_available_at': 'UNKNOWN', 'currency': 'UNKNOWN',
            'cohort_inclusion': 'ORIGINAL_RECORDED_COHORT', 'outcomes': {}}
        for horizon in (1, 5, 21, 63, 126):
            outcome = outcomes.get((oid, horizon))
            elapsed = bisect_right(sessions, now.date().isoformat()) - bisect_right(sessions, signal['decision_date'])
            status = ('LABEL_IMMATURE' if elapsed < horizon else 'NOT_AVAILABLE') if outcome is None else 'PRODUCER_DIAGNOSTIC_ONLY'
            values = {name: metric(outcome[name] if outcome else None) for name in CORE_METRICS}
            row['outcomes'][str(horizon)] = {'status': status, 'metrics': values,
                'mfe_mae_use': 'DIAGNOSTIC_ONLY_NEVER_DECISION_FEATURE', 'costs': metric(None)}
        rows.append(row)
    return rows


def unavailable_metrics():
    return {name: {'status': 'NOT_AVAILABLE', 'value': None} for name in
        ('realized_pnl', 'unrealized_pnl', 'net_excess_return', 'execution_costs', 'turnover',
         'portfolio_drawdown_recovery', 'winner_discovery', 'winner_allocation', 'upside_capture',
         'premature_exit', 'failed_breakout', 'wrong_entry', 'replacement_incremental_benefit', 'er_calibration')}


def readback(path, key):
    if not path.is_file():
        return None
    value = board.read_json(path)
    require(value.get('schema_version') == SCHEMA, 'partial_or_conflicting_cached_result')
    require(value.get('content_sha256') == board.digest({k: v for k, v in value.items() if k != 'content_sha256'}),
            'cached_result_corrupt')
    return value if value.get('identity') == key else None


def prepare(root, out, intake_path, *, now, code_sha, config_hash, board_blockers,
            config_path=CONFIG, registry_path=REGISTRY, dependency_identity=None):
    """Explicit T1/T2 scratch preview; all execution and persistence gates stay false."""
    root, out = output_geometry(root, out)
    start = time.monotonic()
    cfg = configuration(config_path)
    budget = cfg['preview']
    def check_deadline():
        require(time.monotonic() - start <= budget['timeout_seconds'], 'preview_timeout')
    inputs = {}
    total = 0
    def read_input(path):
        nonlocal total
        raw = bounded_read(path, budget['max_input_bytes'] - total)
        total += len(raw)
        return raw
    with exclusive_lock(out):
        write_scratch(out / 'manifest.json', {'schema_version': SCHEMA, 'status': 'BLOCKED',
                          'reason': 'BUILD_STARTED', 'authority': board.AUTHORITY})
        try:
            intake_path = native_path(intake_path)
            require(intake_path.is_relative_to(root), 'intake_outside_source_root')
            intake_bytes = read_input(intake_path)
            intake = strict_json(intake_bytes)
            require(set(intake) == {'schema_version', 'producer', 'inputs'}, 'intake_schema')
            require(intake['schema_version'] == 'bounded-research-intake-v1', 'intake_schema')
            producer = intake['producer']
            require(set(producer) == {'repository', 'branch', 'head_sha', 'workflow', 'run_id', 'attempt',
                                      'conclusion', 'artifact_sha256'}, 'producer_schema')
            require(producer['repository'] == 'wscha231/r1000-quant-engine' and producer['branch'] == 'master'
                    and producer['workflow'] == 'Daily Operating Selection Refresh'
                    and producer['conclusion'] == 'success', 'producer_not_eligible')
            require(re.fullmatch('[0-9a-f]{40}', producer['head_sha']) and
                    re.fullmatch('[0-9a-f]{64}', producer['artifact_sha256']), 'producer_identity')
            require(type(producer['run_id']) is int and producer['run_id'] > 0 and
                    type(producer['attempt']) is int and producer['attempt'] > 0, 'producer_identity')
            require(set(intake['inputs']) == {'events', 'summary', 'calendar'}, 'source_roles')
            # Admit all clocks before reading any declared source file.
            for role, descriptor in intake['inputs'].items():
                check_deadline()
                board.schema_validate(descriptor, 'system_state_schema.json', 'artifact')
                require(descriptor['status'] == 'VERIFIED', 'source_not_verified')
                board.verify_artifact_time(descriptor, now, now)
            for role, descriptor in intake['inputs'].items():
                check_deadline()
                path = native_path(board.artifact_path(root, descriptor['path']))
                raw = read_input(path)
                require(raw_hash(raw) == descriptor['sha256'], 'source_hash_conflict')
                inputs[role] = raw
            summary = strict_json(inputs['summary'])
            require(isinstance(summary, dict) and summary.get('schema_version') == ARCHIVE and summary.get('status') in
                    ('READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY', 'SKIPPED_NO_DECISION_OBSERVATIONS'), 'source_failure')
            require(summary.get('review_only') is True and
                    all(summary.get(flag) is False for flag in OUTCOME_FALSE_SAFETY_FIELDS),
                    'source_authority_conflict')
            require(summary.get('blockers') == [], 'source_summary_blockers')
            require(isinstance(summary.get('outputs'), dict) and
                    summary['outputs'].get('event_log_sha256') == raw_hash(inputs['events']),
                    'producer_event_hash_conflict')
            source_date = summary['as_of_date']
            require(date.fromisoformat(source_date).isoformat() == source_date and
                    source_date <= now.date().isoformat(), 'future_source')
            if summary['status'] == 'SKIPPED_NO_DECISION_OBSERVATIONS':
                require(not inputs['events'] and all(type(summary.get(k)) is int and summary[k] == 0
                        for k in ('signal_observation_count', 'forward_outcome_event_count')), 'empty_summary_conflict')
                # The native skipped branch has no generation clock; never invent it.
                generated = None
            if summary['status'] != 'SKIPPED_NO_DECISION_OBSERVATIONS' or 'generated_at_utc' in summary:
                require(isinstance(summary.get('generated_at_utc'), str), 'producer_clock_missing')
                generated = board.timestamp(summary['generated_at_utc'])
                require(generated <= now, 'future_source')
                require(all(generated <= board.timestamp(item['collected_at']) for role, item in
                            intake['inputs'].items() if role != 'calendar'), 'producer_clock_conflict')
            events = []
            for line in inputs['events'].splitlines():
                check_deadline()
                if line.strip():
                    require(len(events) < budget['max_events'], 'event_budget_exhausted')
                    event = strict_json(line)
                    require(generated is not None and board.timestamp(event['recorded_at_utc']) <= generated and
                            event['decision_date'] <= source_date and
                            event.get('evaluated_as_of_date', source_date) <= source_date,
                            'producer_clock_conflict')
                    events.append(event)
            for field, kind in (('signal_observation_count', 'risk_signal_observed'),
                                ('forward_outcome_event_count', 'forward_outcome_observed')):
                require(type(summary.get(field)) is int and summary[field] >= 0 and
                        summary[field] == sum(event.get('event_type') == kind for event in events),
                        'summary_event_count_conflict')
            require(summary['signal_observation_count'] + summary['forward_outcome_event_count'] == len(events),
                    'summary_event_count_conflict')
            rows = inspect_events(events, strict_json(inputs['calendar'])['sessions'], now,
                                  budget['max_events'], check_deadline)
            registry = board.read_json(registry_path)
            require(registry.get('schema_version') == 'run287-do-not-repeat-registry-v1', 'registry_missing')
            key = board.digest({'intake': raw_hash(intake_bytes), 'code_sha': code_sha, 'config_hash': config_hash,
                'config': board.file_hash(config_path), 'registry': board.file_hash(registry_path),
                'date': now.date().isoformat(), 'board_blockers': board_blockers,
                'dependencies': dependency_identity,
                'temporal': [{k: item[k] for k in ('available_at', 'collected_at', 'expires_at')}
                             for item in intake['inputs'].values()]})
            previous = readback(out / 'a8_research.json', key) if (out / 'a8_research.json').is_file() else None
            if previous:
                result = previous
                reused = True
            else:
                # One H1 evidence-gap hypothesis, no economic-policy modification.
                issue = {'signal': 'decision_outcome_provenance', 'mechanism': 'missing_cost_intent_admission',
                         'book': 'model_proposal', 'window': 'forward_only'}
                repetition = evaluate_candidate(registry, **issue)
                hypothesis = {'hypothesis_id': board.digest(issue), 'classification': 'H1',
                    'observed_phenomenon': 'Recorded cohort lacks complete costs, identity, thesis and PIT evidence',
                    'hypothesis': 'Complete original provenance is necessary to attribute selection and execution outcomes',
                    'alternative_explanation': 'Missing producer fields may reflect reporting gaps rather than decision errors',
                    'required_data': ['original decision intent', 'security identity', 'availability', 'costs', 'A1 admission'],
                    'verification': 'Existing A1 admission, immutable intent fixture, independent A6',
                    'expected_improvement': 'Evaluation integrity; economic improvement UNKNOWN',
                    'cost_risk': 'No paid call or economic mutation; provenance gaps remain blocking',
                    'rejection_condition': 'Conflicting original provenance or inadmissible source',
                    'status': 'WAIT_DEPENDENCY', 'do_not_repeat': repetition}
                result = {'schema_version': SCHEMA, 'identity': key, 'status': 'BLOCKED',
                    'stage': 'WAIT_DEPENDENCY', 'rows': rows, 'metrics': unavailable_metrics(),
                    'hypotheses': [hypothesis] if rows else [],
                    'blockers': sorted(set(board_blockers + ['BLOCKED_MODEL_RUNTIME', 'WAIT_A1_RESEARCH_ADMISSION',
                        'WAIT_EVALUATOR_INTEGRITY', 'WAIT_INDEPENDENT_A6', 'WAIT_DURABLE_RESEARCH_CONTRACT'] +
                        ([] if rows else ['NO_DECISION_OBSERVATIONS']))),
                    'experiment': {'status': 'NOT_RUN', 'control': None, 'challenger': None,
                        'reason': 'No admitted named pair; existing experiment ledger remains the authority'},
                    'producer': producer, 'input_hashes': {k: raw_hash(v) for k, v in inputs.items()},
                    'a0_route': {'agent': 'A8', 'status': 'BLOCKED', 'dispatch_eligible': False},
                    'authority': board.AUTHORITY, 'economic_validated': False,
                    'real_input_verified': False, 'automatic_operation_verified': False,
                    'durable_readback': 'NOT_RUN', 'ai_invoked': False, 'model_calls': 0,
                    'notifications': 0, 'budget_consumed': {'comparisons': 0, 'tokens': 0, 'cost_usd': 0}}
                result['content_sha256'] = board.digest(result)
                require(len(json.dumps(result, indent=2, sort_keys=True, allow_nan=False).encode()) <=
                        budget['max_output_bytes'], 'output_byte_budget_exhausted')
                check_deadline()
                native_path(out / 'a8_research.json')
                write_scratch(out / 'a8_research.json', result)
                require(readback(out / 'a8_research.json', key) == result, 'scratch_readback_failed')
                reused = False
            # Recheck actual input bytes and current expiry before committing the manifest.
            for role, descriptor in intake['inputs'].items():
                check_deadline()
                require(raw_hash(read_input(board.artifact_path(root, descriptor['path'])))
                        == raw_hash(inputs[role]), 'source_changed_during_preview')
                board.verify_artifact_time(descriptor, now, now + timedelta(seconds=time.monotonic() - start))
            manifest = {'schema_version': SCHEMA, 'status': 'BLOCKED', 'reuse': 'SKIP_UNCHANGED' if reused else 'PREPARED',
                        'identity': key, 'authority': board.AUTHORITY,
                        'members': {'a8_research.json': board.file_hash(out / 'a8_research.json')}}
            check_deadline()
            write_scratch(out / 'manifest.json', manifest)
            require(board.read_json(out / 'manifest.json') == manifest, 'scratch_manifest_readback_failed')
            return result
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
            result = {'schema_version': SCHEMA, 'status': 'BLOCKED', 'stage': 'WAIT_DEPENDENCY',
                      'blockers': [str(error) if isinstance(error, board.ContractError) else type(error).__name__],
                      'authority': board.AUTHORITY, 'economic_validated': False, 'ai_invoked': False,
                      'model_calls': 0, 'durable_readback': 'NOT_RUN', 'real_input_verified': False}
            write_scratch(out / 'manifest.json', result)
            return result

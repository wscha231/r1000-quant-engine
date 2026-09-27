#!/usr/bin/env python3
"""Build an artifact-only A0 task proposal board; never invoke specialists.

The v1 CLI/output names are retained. Without an explicit, current v2 state,
legacy metric files cannot establish readiness. No baseline performance,
investment calculation, scheduler, model call or accepted book is changed.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_DIR = REPO_ROOT / 'research/control_plane'
AUTHORITY = dict(research_only=True, execute=False, target=False, broker=False,
                 scheduler=False, promotion=False, peer_dispatch=False)


class ContractError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ContractError('duplicate_json_key')
            result[key] = value
        return result
    def invalid(_):
        raise ContractError('nonfinite_json')
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ContractError('state_too_large')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=invalid)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True,
                                    allow_nan=False) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def schema_validate(payload: Any, filename: str, definition: str | None = None) -> None:
    schema = read_json(CONTRACT_DIR / filename)
    if definition is not None:
        schema = {'$schema': schema['$schema'], '$defs': schema['$defs'], '$ref': '#/$defs/' + definition}
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
    if errors:
        raise ContractError('schema_invalid:' + filename + ':' + '/'.join(map(str, errors[0].absolute_path)))


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError('naive_timestamp')
    return parsed.astimezone(timezone.utc)


def source_identity() -> tuple[str, str]:
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO_ROOT, text=True).strip()
    # Bind actual local bytes too: a dirty tree cannot reuse a clean-head task.
    paths = ['tools/run_agent_board.py', 'r1000_config.py', 'requirements_github.txt']
    paths += ['research/control_plane/' + name for name in
              ('agent_contracts_v2.yaml', 'task_packet_schema.json', 'system_state_schema.json')]
    identity = {name: file_hash(REPO_ROOT / name) for name in paths}
    # Cover dirty tracked specialist code and its transitive local dependencies,
    # not only the board's own files. Never print or publish patch contents.
    delta = subprocess.check_output(['git', 'diff', '--no-ext-diff', '--no-textconv', '--binary', 'HEAD', '--'], cwd=REPO_ROOT)
    identity['tracked_worktree_diff'] = hashlib.sha256(delta).hexdigest()
    untracked = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=REPO_ROOT).decode().split('\0')
    identity['untracked_files'] = {name: file_hash(REPO_ROOT / name) for name in sorted(untracked)
                                   if name and Path(name).suffix in ('.py', '.pyi', '.sh', '.so', '.pyd')
                                   and (REPO_ROOT / name).is_file()}
    return sha, digest(identity)


def mission_targets() -> dict[str, Any]:
    # Read the authoritative mission literal without importing investment runtime.
    path = REPO_ROOT / 'r1000_config.py'
    nodes = [node for node in ast.parse(path.read_text(encoding='utf-8')).body
             if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
             t.id == 'PORTFOLIO_MISSION_TARGETS' for t in node.targets)]
    if len(nodes) != 1:
        raise ContractError('ambiguous_mission_target')
    return {'source': 'r1000_config.py:PORTFOLIO_MISSION_TARGETS',
            'source_sha256': file_hash(path), 'values': ast.literal_eval(nodes[0].value),
            'meaning': 'Authoritative project mission objective; headline pass is not production authority'}


def operating_gates() -> dict[str, Any]:
    # Read the existing literal without importing the investment runtime.
    path = REPO_ROOT / 'r1000_config.py'
    nodes = [node for node in ast.parse(path.read_text(encoding='utf-8')).body
             if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
             t.id == 'PORTFOLIO_GOAL_TARGETS' for t in node.targets)]
    if len(nodes) != 1:
        raise ContractError('ambiguous_operating_gate')
    return {'source': 'r1000_config.py:PORTFOLIO_GOAL_TARGETS',
            'source_sha256': file_hash(path), 'values': ast.literal_eval(nodes[0].value),
            'meaning': 'Legacy/interim challenger diagnostic only; not authoritative mission or accepted performance'}


def artifact_path(root: Path, name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts or relative == Path('.'):
        raise ContractError('unsafe_artifact_path')
    candidate = root / relative
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ContractError('artifact_path_escape')
    if any((root / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts)+1)):
        raise ContractError('artifact_symlink')
    return candidate


def verify_artifact(root: Path, artifact: dict, cutoff: datetime, now: datetime) -> None:
    if file_hash(artifact_path(root, artifact['path'])) != artifact['sha256']:
        raise ContractError('artifact_hash_mismatch')
    observed, available, collected, expires = [timestamp(artifact[k]) for k in
                    ('observed_at', 'available_at', 'collected_at', 'expires_at')]
    if not (observed <= available <= collected <= cutoff <= now < expires):
        raise ContractError('artifact_time_boundary')


def receipt_dependencies(dependencies: dict) -> dict:
    return {agent: {'task_key': receipt['task_key'],
                    'output_hashes': {role: item['sha256'] for role, item in receipt['outputs'].items()}}
            for agent, receipt in dependencies.items()}


def verify_completion(receipt: dict, packet_identity: dict, request: dict,
                      dependencies: dict, causal_ready: datetime, cutoff: datetime) -> None:
    """Verify a completed_tasks V2 row; declarations alone do not grant merge authority."""
    hashes = {role: item['sha256'] for role, item in request['inputs'].items()}
    expected = {'identity': packet_identity, 'source_hashes': hashes, 'input_hashes': hashes,
                'dependency_identities': receipt_dependencies(dependencies),
                'code_sha': packet_identity['code_sha'], 'config_hash': packet_identity['config_hash'],
                'model': packet_identity['model'], 'parameter_hash': digest(packet_identity['parameters'])}
    if any(receipt[name] != value for name, value in expected.items()):
        raise ContractError('receipt_identity_mismatch')
    if receipt['side_effects'] or receipt['verification_status'] != 'VERIFIED':
        raise ContractError('receipt_unverified_or_mutating')
    for name in ('runtime_verification', 'focused_tests', 'ci'):
        if receipt[name]['status'] != 'PASS':
            raise ContractError('receipt_' + name + '_not_pass')
    if receipt['ci']['head_sha'] != packet_identity['code_sha']:
        raise ContractError('receipt_ci_old_head')
    created, available = timestamp(receipt['created_at']), timestamp(receipt['available_at'])
    if not causal_ready <= created <= available <= cutoff:
        raise ContractError('receipt_time_boundary')
    if receipt['reviewed_head'] is not None and receipt['reviewed_head'] != packet_identity['code_sha']:
        raise ContractError('receipt_old_review_head')


APPROVAL_ACTIONS = frozenset({'fullrun', 'actual_broker', 'paper_book', 'target_book',
    'production_activation', 'live_trading', 'new_alpha_logic', 'er_weight_change',
    'risk_limit_relaxation', 'review_gate_relaxation', 'protected_evidence_change'})
NOTIFY_STATES = frozenset({'BLOCKED', 'HUMAN_APPROVAL_REQUIRED', 'CORRECTION_REQUIRED',
                           'READY_TO_MERGE', 'DONE'})


def lifecycle_state(packet: dict | None, event: dict | None = None) -> dict:
    """Pure event reducer. Caller must obtain CI/review/merge facts from GitHub.

    No event fetching, scheduling, specialist invocation, notification or mutation.
    An unverified worker report is deliberately not an input to this reducer.
    """
    event = event or {}
    action = event.get('action')
    effects = event.get('side_effects', [])
    if not isinstance(effects, list) or not isinstance(action, (str, type(None))):
        state = 'BLOCKED'
    elif action in APPROVAL_ACTIONS or effects:
        state = 'HUMAN_APPROVAL_REQUIRED'
    elif packet is None:
        state = 'QUEUED'
    elif packet['status'] == 'BLOCKED' or event.get('integrity_failure'):
        state = 'BLOCKED'
    elif not isinstance(event.get('unresolved_findings', 0), int):
        state = 'BLOCKED'
    elif event.get('unexpected_regression') or event.get('ci') == 'FAIL' or event.get('unresolved_findings', 0) > 0:
        state = 'CORRECTION_REQUIRED'
    elif packet['status'] == 'SKIP_UNCHANGED' and not event:
        state = 'SKIP_UNCHANGED'
    elif packet['status'] == 'READY' and not event:
        state = 'READY'
    elif event.get('running'):
        state = 'RUNNING'
    elif (event.get('ci') != 'PASS' or event.get('ci_head') != packet['identity']['code_sha']
          or event.get('ci_checks') != {'validate': 'PASS', 'portfolio_guard': 'PASS'}):
        state = 'WAITING_CI'
    elif (event.get('review') != 'CLEAN' or event.get('review_head') != packet['identity']['code_sha']
          or event.get('unresolved_findings') != 0):
        state = 'WAITING_REVIEW'
    elif packet['status'] != 'SKIP_UNCHANGED':
        state = 'READY'
    elif event.get('review_complete') == 'PASS' and event.get('review_complete_head') == packet['identity']['code_sha']:
        if event.get('merged'):
            state = 'DONE' if event.get('post_merge_verified') else 'POST_MERGE_VERIFY'
        else:
            state = 'READY_TO_MERGE'
    elif event.get('merged'):
        state = 'BLOCKED'
    else:
        state = 'READY_FOR_ATTESTATION'
    return {'state': state, 'notification_worthy': state in NOTIFY_STATES or
            bool(event.get('integrity_failure') or event.get('unexpected_regression')),
            'polling_required': False}


def contracts() -> dict:
    # JSON is a YAML subset; use strict duplicate/nonfinite parsing with no YAML tags.
    value = read_json(CONTRACT_DIR / 'agent_contracts_v2.yaml')
    agents = value['agents']
    if set(agents) != {f'A{i}' for i in range(9)} or value['authority'] != AUTHORITY:
        raise ContractError('contract_authority')
    if value['orchestrator'] != 'A0' or value['specialist_dispatch_enabled'] is not False:
        raise ContractError('contract_dispatch')
    seen = set()
    def visit(agent):
        if agent in seen:
            return
        if agent in stack:
            raise ContractError('contract_cycle')
        stack.add(agent)
        row = agents[agent]
        if row['dispatch_via'] != 'A0' or row['can_call_agents'] is not False:
            raise ContractError('peer_dispatch')
        for dep in row['dependencies']:
            if dep not in agents or dep == 'A0':
                raise ContractError('unknown_dependency')
            visit(dep)
        stack.remove(agent)
        seen.add(agent)
    stack = set()
    for agent in agents:
        visit(agent)
    if agents['A6']['mode'] != 'READ_ONLY':
        raise ContractError('qa_not_read_only')
    if value.get('mission_source') != 'r1000_config.py:PORTFOLIO_MISSION_TARGETS':
        raise ContractError('mission_source')
    mission = mission_targets()['values']
    value['mission'] = {
        name: {'net_cagr_min': float(target['cagr']), 'mdd_loss_max': abs(float(target['max_dd']))}
        for name, target in mission.items()
    }
    return value


def build_tasks(state: dict, root: Path, contract: dict, now: datetime,
                code_sha: str, config_hash: str) -> list[dict]:
    schema_validate(state, 'system_state_schema.json')
    cutoff = timestamp(state['as_of'])
    if not cutoff <= now < timestamp(state['expires_at']):
        raise ContractError('state_stale_or_future')
    for name in ('current_status_as_of', 'data_as_of'):
        value = state['context'][name]
        if value is not None and timestamp(value) > cutoff:
            raise ContractError('context_future:' + name)
    if state['context']['current_status_freshness'] == 'VERIFIED' and state['context']['current_status_as_of'] is None:
        raise ContractError('current_status_time_missing')
    if state['code_sha'] != code_sha:
        raise ContractError('state_code_sha_mismatch')
    if state['g0']['status'] == 'PASS' and state['g0']['reasons']:
        raise ContractError('g0_conflicting_reasons')
    requests = {r['agent']: r for r in state['requests']}
    if len(requests) != len(state['requests']):
        raise ContractError('duplicate_agent_request')
    receipts = {r['agent']: r for r in state['completed_tasks']}
    if len(receipts) != len(state['completed_tasks']):
        raise ContractError('duplicate_completion_receipt')
    tasks, completed, visiting, qa_reports = {}, {}, set(), {}
    def plan(agent):
        if agent in tasks:
            return tasks[agent]
        if agent in visiting:
            raise ContractError('task_cycle')
        visiting.add(agent)
        spec, request = contract['agents'][agent], requests[agent]
        reasons = []
        if set(request['inputs']) != set(spec['inputs']):
            raise ContractError('input_roles_mismatch:' + agent)
        for role, artifact in request['inputs'].items():
            try:
                verify_artifact(root, artifact, cutoff, now)
            except (OSError, ValueError):
                reasons.append('input_invalid:' + role)
        reviewed_inputs = {}
        if agent == 'A6':
            try:
                bundle = read_json(artifact_path(root, request['inputs']['review_bundle']['path']))
                schema_validate(bundle, 'system_state_schema.json', 'qa_bundle')
                reviewed_inputs = bundle['artifacts']
                for artifact in reviewed_inputs.values():
                    if file_hash(artifact_path(root, artifact['path'])) != artifact['sha256']:
                        raise ContractError('qa_reviewed_bytes_mismatch')
                    if timestamp(artifact['collected_at']) > timestamp(request['inputs']['review_bundle']['collected_at']):
                        raise ContractError('qa_bundle_predates_reviewed_input')
            except (OSError, ValueError, KeyError):
                reasons.append('QA_BUNDLE_INVALID')
        if state['context']['data_as_of'] is None and agent not in ('A1', 'A6'):
            reasons.append('DATA_AS_OF_MISSING')
        if state['g0']['status'] != 'PASS' and agent not in ('A1', 'A6'):
            reasons.append('G0_NOT_PASS')
        if state['context']['blockers'] and agent not in ('A1', 'A6'):
            reasons.append('CONTEXT_BLOCKED')
        if state['context']['current_status_freshness'] != 'VERIFIED' and agent not in ('A1', 'A6'):
            reasons.append('CURRENT_STATUS_NOT_VERIFIED')
        if agent == 'A5' and any(state['context'][k] != 'VERIFIED' for k in ('actual_book', 'approved_target', 'thesis')):
            reasons.append('PORTFOLIO_CONTEXT_NOT_VERIFIED')
        dependencies = {}
        for dep in spec['dependencies']:
            if dep in requests:
                plan(dep)
            if dep not in completed:
                reasons.append('dependency_incomplete:' + dep)
            else:
                dependencies[dep] = completed[dep]
                for role, artifact in completed[dep]['outputs'].items():
                    if request['inputs'].get(role) != artifact:
                        reasons.append('dependency_input_mismatch:' + dep + ':' + role)
        if 'A6' in spec['dependencies'] and 'A6' in completed:
            report = qa_reports['A6']
            if report['verdict'] != 'PASS':
                reasons.append('QA_NOT_PASS')
            for role, artifact in request['inputs'].items():
                if role != 'qa_report' and report['reviewed_artifacts'].get(role) != artifact:
                    reasons.append('QA_INPUT_NOT_REVIEWED:' + role)
        identity = {'input_hash': digest({'inputs': request['inputs'], 'dependencies': dependencies,
                    'context': state['context'], 'g0': state['g0'], 'master_sha': state['master_sha']}),
                    'code_sha': code_sha, 'config_hash': config_hash,
                    'model': request['model'], 'parameters': request['parameters']}
        key = digest({'agent': agent, **identity})
        status = 'BLOCKED' if reasons else 'READY'
        receipt = receipts.get(agent)
        if not reasons and receipt and receipt['task_key'] == key:
            try:
                if set(receipt['outputs']) != set(spec['outputs']):
                    raise ContractError('output_roles_mismatch')
                causal_inputs = list(request['inputs'].values()) + list(reviewed_inputs.values())
                causal_inputs += [artifact for dependency in dependencies.values()
                                  for artifact in dependency['outputs'].values()]
                causal_ready = max(timestamp(artifact['collected_at']) for artifact in causal_inputs)
                verify_completion(receipt, identity, request, dependencies, causal_ready, cutoff)
                for artifact in receipt['outputs'].values():
                    verify_artifact(root, artifact, cutoff, now)
                    if timestamp(artifact['available_at']) < timestamp(receipt['available_at']):
                        raise ContractError('completion_predates_inputs')
                if agent == 'A6':
                    report = read_json(artifact_path(root, receipt['outputs']['qa_report']['path']))
                    schema_validate(report, 'system_state_schema.json', 'qa_report')
                    if report['review_bundle_sha256'] != request['inputs']['review_bundle']['sha256'] or report['reviewed_artifacts'] != reviewed_inputs:
                        raise ContractError('qa_report_scope_mismatch')
                    qa_reports[agent] = report
                completed[agent] = receipt
                status = 'SKIP_UNCHANGED'
            except (OSError, ValueError):
                status = 'BLOCKED'
                reasons.append('completion_output_invalid')
        packet = {'schema_version': 'task-packet-v2', 'agent': agent,
                  'assigned_by': 'A0', 'return_to': 'A0', 'status': status,
                  'reasons': reasons, 'inputs': request['inputs'], 'outputs': spec['outputs'],
                  'authority': AUTHORITY.copy(), 'mode': spec['mode'],
                  'dependencies': spec['dependencies'], 'dependency_outputs': dependencies,
                  'identity': identity, 'task_key': key,
                  'dispatch_eligible': agent in ('A1', 'A2', 'A4', 'A6') and status == 'READY'
                      and spec['mode'] in ('READ_ONLY', 'PROPOSAL_ONLY')}
        schema_validate(packet, 'task_packet_schema.json')
        tasks[agent] = packet
        visiting.remove(agent)
        return packet
    for agent in sorted(requests):
        plan(agent)
    return list(tasks.values())


def run(args: argparse.Namespace) -> dict[str, Any]:
    root, out = repo_path(args.latest_run), repo_path(args.output_dir)
    state_path = repo_path(args.system_state) if getattr(args, 'system_state', None) else root / 'control_plane/system_state.json'
    now = datetime.now(timezone.utc)
    # Revoke a previous success before reading any new input.
    write_json(out / 'manifest.json', {'schema_version': 'agent-board-manifest-v2',
               'status': 'BLOCKED', 'reason': 'BUILD_STARTED', 'authority': AUTHORITY})
    tasks, reasons, state = [], [], None
    contract, gates, mission_contract, code_sha, config_hash = {}, {}, {}, None, None
    try:
        contract = contracts()
        code_sha, config_hash = source_identity()
        mission_contract = mission_targets()
        gates = operating_gates()
        state = read_json(state_path)
        tasks = build_tasks(state, root, contract, now, code_sha, config_hash)
        cap = getattr(args, 'max_tasks', 0)
        if cap < 0 or (cap and len(tasks) > cap):
            raise ContractError('task_cap_would_drop_dependencies')
    except (OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.SubprocessError) as error:
        tasks = []
        reasons = [str(error) if isinstance(error, ContractError) else type(error).__name__]
    blocked = bool(reasons or any(t['status'] == 'BLOCKED' for t in tasks))
    status = 'BLOCKED' if blocked else 'PROPOSAL_ONLY'
    gate = {'production_activation_allowed': False, 'automatic_promotion_allowed': False,
            'human_promotion_review_candidate': False, 'blockers': ['PHASE1_HAS_NO_PROMOTION_AUTHORITY']}
    board = {'schema_version': 'agent-board-v2', 'status': status,
             'generated_at_utc': now.isoformat(), 'latest_run': str(root),
             'run_url': args.run_url or '', 'code_sha': code_sha, 'config_hash': config_hash,
             'state_sha256': file_hash(state_path) if state_path.is_file() else None,
             'state_as_of': state.get('as_of') if isinstance(state, dict) else None,
             'mission': contract.get('mission'), 'mission_contract': mission_contract,
             'operating_gate': gates,
             'agent_contracts': contract.get('agents'), 'authority': AUTHORITY,
             'specialist_dispatch_enabled': False,
             'lifecycle': {t['agent']: lifecycle_state(t) for t in tasks},
             'production_activation_allowed': False, 'promotion_gate': gate,
             'task_count': len(tasks), 'blockers': reasons,
             'evidence_scope': 'Local bytes and declared timestamps only; not authenticated economic or book readiness'}
    write_json(out / 'board_summary.json', board)
    write_json(out / 'agent_task_queue.json', tasks)
    write_json(out / 'promotion_gate_review.json', gate)
    lines = ['# Agent Board v2', '', f'Status: {status}. A0 proposals only; no specialist was executed.',
             '', 'Mission: Main net CAGR >=35%, MDD loss <=25%; Concentrated >=50%, <=25%.',
             'Mission source: r1000_config.py:PORTFOLIO_MISSION_TARGETS (authoritative objective).',
             'Operating gates are separately reported legacy/interim challenger diagnostics only.', '',
             '| Agent | Status | Blockers |', '| --- | --- | --- |']
    lines += [f"| {t['agent']} | {t['status']} | {', '.join(t['reasons'])} |" for t in tasks]
    lines += ['', *reasons, '', 'Next P0: connect the complete US equity universe and Multi-Asset candidates to one verified ER1/3/6/12m flow.', '']
    (out / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    files = ['board_summary.json', 'agent_task_queue.json', 'promotion_gate_review.json', 'report.md']
    manifest = {'schema_version': 'agent-board-manifest-v2', 'status': status,
                'output_dir': str(out), 'task_count': len(tasks), 'authority': AUTHORITY,
                'members': {name: file_hash(out / name) for name in files},
                'pro_packets': [], 'note': 'Only manifest members belong to this attempt; retained v1 Pro packets are obsolete'}
    write_json(out / 'manifest.json', manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--latest-run', default='outputs')
    parser.add_argument('--output-dir', default='outputs/agent_board')
    parser.add_argument('--run-url', default='')
    parser.add_argument('--max-tasks', type=int, default=0)
    parser.add_argument('--system-state', help='Explicit current v2 state; otherwise <latest-run>/control_plane/system_state.json')
    return parser.parse_args()


def main() -> int:
    result = run(parse_args())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())

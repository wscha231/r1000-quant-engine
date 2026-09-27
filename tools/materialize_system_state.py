#!/usr/bin/env python3
"""Materialize the existing system-state-v2 from hash-pinned, read-only evidence.

The intake manifest is supplied by a trusted caller after refreshing GitHub and
Drive. It is not a receipt, authorization, or a replacement canonical store.
Consumers require a separately refreshed intake; a saved state never proves its
own currency. No network, collector, account, or scheduler is invoked here.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import run_agent_board as board

ROLES = ('code', 'mission', 'execution', 'commit', 'catalog', 'quality',
         'drive_readback', 'control', 'current_status', 'actual_broker',
         'approved_target', 'verified_paper', 'model_portfolio', 'regime')
BOOKS = ('actual_broker', 'approved_target', 'verified_paper', 'model_portfolio')
SHA = re.compile(r'[0-9a-f]{64}')
REPOSITORY = 'wscha231/r1000-quant-engine'
# State/current-source observations expire promptly. Artifact historical dates
# are independent; collecting a snapshot cannot advance its observation date.
MAX_INTAKE_AGE = timedelta(hours=1)
MAX_STATE_AGE = timedelta(hours=1)


def need(condition, reason):
    if not condition:
        raise board.ContractError(reason)


def semantic_hash(state):
    return board.digest({k: v for k, v in state.items()
                         if k not in ('generated_at', 'state_sha256')})


def intake_validate(manifest, now):
    board.schema_validate(manifest, 'system_state_schema.json', 'source_intake')
    observed, expires = (board.timestamp(manifest[k]) for k in ('observed_at', 'expires_at'))
    need(observed <= now < expires <= observed + MAX_INTAKE_AGE, 'intake_stale_or_future')
    return observed, expires


class Sources:
    def __init__(self, root, manifest, now):
        self.root, self.manifest, self.now = root, manifest, now
        self.observed, self.expires = intake_validate(manifest, now)
        self.identities, self.states, self.payloads = {}, {}, {}

    def read(self, role):
        refs = self.manifest['sources'].get(role, [])
        self.identities[role] = copy.deepcopy(refs)
        summary = dict(status='UNKNOWN', artifact_identity=None, sha256=None,
                       as_of=None, availability=None, reason='source_missing')
        self.states[role] = summary
        if not refs:
            return None
        if len(refs) != 1:
            summary.update(status='BLOCKED', reason='conflicting_sources')
            return None
        ref = refs[0]
        summary.update(artifact_identity=ref['identity'], sha256=ref['sha256'],
                       as_of=ref['observed_at'], availability=ref['available_at'])
        try:
            path = board.artifact_path(self.root, ref['path'])
            need(board.file_hash(path) == ref['sha256'], 'hash_mismatch')
            observed, available, collected, expires = [board.timestamp(ref[k]) for k in
                ('observed_at', 'available_at', 'collected_at', 'expires_at')]
            need(observed <= available <= collected <= self.observed, 'source_time_conflict')
            if self.now >= expires:
                summary.update(status='STALE', reason='source_expired')
                return None
            need(expires > collected, 'source_expiry_conflict')
            payload = path.read_text(encoding='utf-8') if role == 'current_status' else board.read_json(path)
            if role != 'current_status':
                need(isinstance(payload, dict), 'source_not_object')
            summary.update(status='VERIFIED', reason='hash_and_time_verified')
            self.payloads[role] = payload
            return payload
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
            summary.update(status='BLOCKED', reason=str(exc) if isinstance(exc, board.ContractError)
                           else 'malformed_or_unavailable_source')
            return None

    def block(self, role, reason):
        self.states[role].update(status='BLOCKED', reason=reason)


def data_state(src):
    run = src.payloads.get('code', {}).get('g0_run')
    data = dict(g0_status='UNKNOWN', g0_reasons=[],
                workflow_conclusion=run.get('conclusion') if isinstance(run, dict) else None,
                execution_identity=None, execution_sha256=None, catalog_identity=None,
                catalog_sha256=None, quality_identity=None, quality_sha256=None,
                data_as_of=None, availability=None, dataset_as_of={}, research_dataset_keys=[],
                drive_readback_status='UNKNOWN', drive_readback_identity=None,
                drive_readback_sha256=None, eligible_for_selector=False,
                universe_evidence_class='UNKNOWN', official_r1000_membership_proven=False,
                historical_universe_pit_clean=False, final_8y_certification_allowed=False)
    for role in ('execution', 'catalog', 'quality'):
        data[role + '_identity'] = src.states[role]['artifact_identity']
        data[role + '_sha256'] = src.states[role]['sha256']
    data['drive_readback_identity'] = src.states['drive_readback']['artifact_identity']
    data['drive_readback_sha256'] = src.states['drive_readback']['sha256']
    required = ('execution', 'commit', 'catalog', 'quality', 'drive_readback')
    failures = [role + ':' + src.states[role]['reason'] for role in required
                if src.states[role]['status'] != 'VERIFIED']
    if failures:
        statuses = {src.states[role]['status'] for role in required}
        data['g0_status'] = 'BLOCKED' if 'BLOCKED' in statuses else 'STALE' if 'STALE' in statuses else 'UNKNOWN'
        data['g0_reasons'] = failures
        return data
    ex, commit, catalog, quality, readback = (src.payloads[k] for k in required)
    try:
        need(ex.get('schema') == 'long-history-execution-v1', 'execution_schema')
        need(commit.get('schema') == 'long-history-commit-v1', 'commit_schema')
        need(catalog.get('schema') == 'long-history-catalog-v1', 'catalog_schema')
        need(quality.get('schema') == 'long-history-quality-v1', 'quality_schema')
        need(ex.get('catalog_sha256') == commit.get('catalog') == data['catalog_sha256'], 'catalog_link_mismatch')
        need(ex.get('commit_sha256') == src.states['commit']['sha256'], 'commit_link_mismatch')
        need(ex.get('reports', {}).get('quality.json') == data['quality_sha256'], 'quality_link_mismatch')
        need(ex.get('run_id') == commit.get('run_id') == catalog.get('run_id') and
             isinstance(ex.get('run_id'), str), 'execution_identity_mismatch')
        need(quality.get('status') == ex.get('quality_status') and quality.get('status') in
             {'PARTIAL', 'PARTIAL_COVERAGE', 'COLLECTED_NOT_PIT_CERTIFIED'}, 'quality_status_conflict')
        # Reuse the existing long-history contract: it never grants selector/PIT.
        need(all(item.get('eligible_for_selector') is False for item in (ex, catalog, quality, readback)),
             'long_history_selector_conflict')
        for key in ('catalog_sha256', 'commit_sha256'):
            need(readback.get(key) == ex.get(key), 'readback_' + key + '_mismatch')
        need(readback.get('execution_receipt_sha256') == data['execution_sha256'], 'readback_execution_mismatch')
        need(readback.get('quality_status') == quality['status'], 'readback_quality_conflict')
        need(readback.get('remote_verified') is True and readback.get('study_recomputed_from_drive') is True
             and ex.get('study_recomputed_from_drive') is True, 'readback_not_verified')
        need(type(ex.get('consumer_rows')) is int and ex['consumer_rows'] > 0 and
             readback.get('consumer_rows') == ex['consumer_rows'], 'consumer_evidence_mismatch')
        for role, field in (('execution', 'created_at'), ('commit', 'created_at'),
                            ('catalog', 'created_at'), ('quality', 'as_of')):
            need(board.timestamp(src.payloads[role][field]) <=
                 board.timestamp(src.states[role]['availability']), role + '_availability_conflict')
        need(board.timestamp(catalog['created_at']) <= board.timestamp(commit['created_at']) <=
             board.timestamp(ex['created_at']), 'data_causal_time_conflict')
        code = src.payloads.get('code')
        need(code is not None and code.get('g0_run', {}).get('run_id') == ex['run_id'], 'github_run_mismatch')
        need(code['g0_run'].get('head_sha') == catalog.get('code_sha'), 'github_run_code_mismatch')
        need(code['g0_run'].get('conclusion') in ('failure', 'success', 'cancelled', 'timed_out'),
             'workflow_conclusion_unknown')
        data.update(g0_status=quality['status'], drive_readback_status='VERIFIED',
                    availability=src.states['execution']['availability'],
                    workflow_conclusion=code['g0_run']['conclusion'],
                    universe_evidence_class='PROXY_CURRENT_SNAPSHOT_HISTORY')
        for role in ('provider_failures', 'provider_coverage_gaps'):
            gaps = quality.get(role, {})
            need(isinstance(gaps, dict), 'quality_reasons_malformed')
            data['g0_reasons'] += [str(k) + ':' + str(v) for k, v in sorted(gaps.items())]
        need(isinstance(catalog.get('datasets'), dict) and bool(catalog['datasets']), 'datasets_missing')
        data['dataset_as_of'] = {k: {'latest': v.get('latest'), 'status': v.get('status'),
                                       'evidence': v.get('evidence')}
                                 for k, v in sorted(catalog['datasets'].items())}
        data['research_dataset_keys'] = sorted(k for k, v in catalog['datasets'].items()
            if v.get('status') in ('COLLECTED', 'UNCHANGED') and
            isinstance(v.get('normalized'), str) and SHA.fullmatch(v['normalized']))
        # No single observation date is implied by a mixed-frequency lake.
        data['g0_reasons'] = sorted(set(data['g0_reasons']))
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        data.update(g0_status='BLOCKED', drive_readback_status='BLOCKED', eligible_for_selector=False,
                    g0_reasons=[str(exc) if isinstance(exc, board.ContractError) else 'malformed_data_chain'])
    return data


def book_state(src, role):
    """Never promote a simulation/QA report to an accepted economic receipt.

    No canonical current-cycle book verifier is bound in the existing A0
    contract. Preserve missing/stale/conflicting identity; present unadmitted
    receipts explicitly as BLOCKED until their existing domain verifier is
    connected in the dedicated book slice (#537), not via a boolean here.
    """
    result = copy.deepcopy(src.states[role])
    if result['status'] == 'VERIFIED':
        result.update(status='BLOCKED', reason='accepted_domain_receipt_verifier_not_bound')
    if role == 'model_portfolio':
        result['claim_boundary'] = 'NOT_ACTUAL_HOLDINGS'
    return result


def materialize(manifest, root, now=None, code_sha=None):
    now = now or datetime.now(timezone.utc)
    code_sha = code_sha or board.source_identity()[0]
    src = Sources(root, manifest, now)
    for role in ROLES:
        src.read(role)
    code = src.payloads.get('code', {})
    master = code.get('master_sha')
    if not (isinstance(master, str) and re.fullmatch('[0-9a-f]{40}', master)
            and code.get('repository') == REPOSITORY and code.get('default_branch') == 'master'):
        src.block('code', 'canonical_code_observation_missing_or_invalid')
        master = None
    elif code.get('observed_at') != manifest['observed_at']:
        src.block('code', 'code_observation_not_current_intake')
    if not isinstance(code.get('g0_run'), dict):
        src.block('code', 'github_run_malformed')
    mission = board.mission_targets()
    mission_payload = src.payloads.get('mission')
    expected_mission = {k: mission[k] for k in
        ('mission_contract_id', 'mission_contract_sha256', 'official_metric_mode', 'mission_contract_values')}
    if mission_payload != expected_mission:
        src.block('mission', 'mission_identity_mismatch_or_missing')
    data = data_state(src)
    control = src.payloads.get('control', {})
    refs, dependencies = [], []
    try:
        need(control.get('observed_at') == manifest['observed_at'], 'control_observation_not_current_intake')
        issues = control['issues']
        need(isinstance(issues, list) and all(isinstance(x, dict) for x in issues), 'issues_malformed')
        need(len({x['number'] for x in issues}) == len(issues), 'conflicting_issue_states')
        for item in issues:
            need(type(item['number']) is int and item['number'] > 0 and item['state'] in ('open', 'closed'),
                 'issue_state_invalid')
            need(item['url'] == 'https://github.com/' + REPOSITORY + '/issues/' + str(item['number']), 'issue_scope')
        refs = sorted(item['url'] for item in issues if item['state'] == 'open')
        dependencies = sorted(copy.deepcopy(issues), key=lambda x: x['number'])
        need(isinstance(control['handoff_ref'], str) and bool(control['handoff_ref']), 'handoff_missing')
    except (ValueError, KeyError, TypeError):
        src.block('control', 'control_missing_or_conflicting')
    # #531 closure is coordination, not membership certification. Until an
    # existing domain certification verifier is bound all three flags stay false.
    current_status_as_of, freshness = None, src.states['current_status']['status']
    if 'current_status' in src.payloads:
        match = re.search(r'Status snapshot:.*?`(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC`',
                          src.payloads['current_status'])
        if match:
            current_status_as_of = match[1].replace(' ', 'T') + ':00+00:00'
            freshness = ('STALE' if now - board.timestamp(current_status_as_of) > timedelta(days=1)
                         else 'UNKNOWN')
        else:
            freshness = 'UNKNOWN'
    if freshness == 'BLOCKED':
        freshness = 'UNKNOWN'
    books = {role: book_state(src, role) for role in BOOKS}
    regime = book_state(src, 'regime')
    regime['value'] = 'UNKNOWN'
    identity_ready = all(src.states[k]['status'] == 'VERIFIED' for k in ('code', 'mission', 'control'))
    research = identity_ready and bool(data['research_dataset_keys']) and data['drive_readback_status'] == 'VERIFIED' and data['g0_status'] in (
        'PARTIAL', 'PARTIAL_COVERAGE', 'COLLECTED_NOT_PIT_CERTIFIED')
    reasons = [k + ':' + v['reason'] for k, v in src.states.items() if v['status'] != 'VERIFIED']
    reasons += data['g0_reasons'] + ['HISTORICAL_R1000_PIT_UNCERTIFIED']
    if freshness != 'VERIFIED':
        reasons.append('CURRENT_STATUS_' + freshness)
    reasons += [role + ':' + books[role]['reason'] for role in BOOKS if books[role]['status'] == 'BLOCKED']
    authority = {**board.AUTHORITY, 'research_allowed': research,
                 'selector_allowed': False, 'model_portfolio_allowed': research,
                 'account_rebalance_allowed': False, 'target_mutation_allowed': False,
                 'paper_mutation_allowed': False, 'broker_mutation_allowed': False,
                 'fullrun_allowed': False, 'production_activation_allowed': False}
    state = dict(schema_version='system-state-v2', generated_at=now.isoformat(),
        as_of=manifest['observed_at'], expires_at=min(src.expires, src.observed + MAX_STATE_AGE).isoformat(),
        repository=REPOSITORY, master_sha=master, code_sha=code_sha,
        default_branch=code.get('default_branch') if master else None,
        mission={**expected_mission, 'targets': mission['mission_contract_values'],
                 'status': src.states['mission']['status']}, data=data, books=books, regime=regime,
        context=dict(current_status_as_of=current_status_as_of, current_status_freshness=freshness,
                     data_as_of=None, actual_book=books['actual_broker']['status'],
                     approved_target=books['approved_target']['status'], thesis='UNKNOWN', market_regime='UNKNOWN',
                     open_refs=refs, handoff_ref=control.get('handoff_ref') or 'UNKNOWN',
                     blockers=sorted(set(reasons))),
        blockers=sorted(set(reasons)), dependencies=dependencies, open_refs=refs,
        g0={'status': data['g0_status'], 'reasons': data['g0_reasons']},
        requests=copy.deepcopy(manifest.get('requests', [])),
        completed_tasks=copy.deepcopy(manifest.get('completed_tasks', [])), authority=authority,
        source_identity=src.identities, source_status=src.states,
        dependency_identity=board.digest({'sources':src.identities, 'issues':dependencies,
            'mission':expected_mission, 'master_sha':master, 'code_sha':code_sha}),
        materialization={'method':'canonical-source-readback',
                         'intake_sha256':board.digest(manifest),
                         'runtime_sha256':board.digest({name:board.file_hash(ROOT/name) for name in
                             ('tools/materialize_system_state.py','tools/run_agent_board.py',
                              'mission_contract.py','r1000_config.py',
                              'research/control_plane/system_state_schema.json')}),
                         'research_scope':'ADMITTED_DATASETS_ONLY_NOT_RANKING_OR_A5_READINESS'})
    state['state_sha256'] = semantic_hash(state)
    board.schema_validate(state, 'system_state_schema.json')
    return state


def verify_state(state, manifest, root, now, code_sha):
    """Re-materialize against a newly obtained intake, never the state's own pins."""
    need(isinstance(state, dict) and state.get('materialization', {}).get('method') ==
         'canonical-source-readback', 'state_not_materialized')
    need(state.get('state_sha256') == semantic_hash(state), 'state_semantic_hash_mismatch')
    current = materialize(manifest, root, now, code_sha)
    need(state['state_sha256'] == current['state_sha256'], 'state_sources_changed_or_expired')
    need(current['source_status']['code']['status'] == 'VERIFIED' and
         current['source_status']['mission']['status'] == 'VERIFIED', 'state_identity_blocked')
    return current


def projection(state):
    lines = ['# SYSTEM_STATE projection', '', 'Read-only evidence summary; no economic mutation authority.',
             '', '| Field | Value |', '| --- | --- |',
             '| State hash | `' + state['state_sha256'] + '` |',
             '| Master | `' + str(state['master_sha']) + '` |',
             '| Mission | `' + state['mission']['mission_contract_sha256'] + '` |',
             '| G0 quality | ' + state['data']['g0_status'] + ' |',
             '| Workflow conclusion | ' + str(state['data']['workflow_conclusion']) + ' |',
             '| Drive readback | ' + state['data']['drive_readback_status'] + ' |',
             '| Selector allowed | false |',
             '| CURRENT_STATUS freshness | ' + state['context']['current_status_freshness'] + ' |']
    lines += ['| ' + role + ' | ' + row['status'] + ' |' for role, row in state['books'].items()]
    lines += ['', 'Model research permission is limited to admitted data; it is not A5 readiness.',
              'Model proposals are NOT_ACTUAL_HOLDINGS. Fullrun and all economic mutations remain false.',
              '', 'Blockers:', *['- ' + x for x in state['blockers']], '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--canonical-inputs', required=True, type=Path)
    parser.add_argument('--evidence-root', required=True, type=Path)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs/control_plane')
    args = parser.parse_args()
    # Output must not alias inputs or accepted books. Only a dedicated scratch
    # output directory is supported; no durable remote writer exists.
    out = args.output_dir.resolve()
    need(not args.evidence_root.resolve().is_relative_to(out) and
         not out.is_relative_to(args.evidence_root.resolve()) and
         not args.canonical_inputs.resolve().is_relative_to(out), 'output_overlaps_sources')
    need(not args.output_dir.is_symlink() and
         not any((out/name).is_symlink() for name in ('system_state.json','CURRENT_STATUS.md','manifest.json')),
         'output_symlink')
    need(not (out.is_relative_to(ROOT.resolve()) and not out.is_relative_to((ROOT/'outputs').resolve())),
         'output_must_be_scratch')
    board.write_json(out/'manifest.json', {'status':'BLOCKED', 'reason':'BUILD_STARTED'})
    try:
        state = materialize(board.read_json(args.canonical_inputs), args.evidence_root)
        board.write_json(out/'system_state.json', state)
        (out/'CURRENT_STATUS.md').write_text(projection(state), encoding='utf-8')
        board.write_json(out/'manifest.json', {'status':'MATERIALIZED', 'state_sha256':state['state_sha256'],
            'members':{name:board.file_hash(out/name) for name in ('system_state.json','CURRENT_STATUS.md')},
            'side_effects':[]})
        print(json.dumps({'state_sha256':state['state_sha256'], 'g0':state['data']['g0_status'],
                          'books':{k:v['status'] for k,v in state['books'].items()}}))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        board.write_json(out/'manifest.json', {'status':'BLOCKED', 'reason':str(exc)})
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

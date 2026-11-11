#!/usr/bin/env python3
"""Build an artifact-only A0 task proposal board; never invoke specialists.

The v1 CLI/output names are retained. Without an explicit, current v2 state,
legacy metric files cannot establish readiness. No baseline performance,
investment calculation, scheduler, model call or accepted book is changed.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from mission_contract import mission_identity

CONTRACT_DIR = REPO_ROOT / 'research/control_plane'
AUTHORITY = dict(research_only=True, execute=False, target=False, broker=False,
                 scheduler=False, promotion=False, peer_dispatch=False)
A5_PORTFOLIO_MODES = ('ACCOUNT_REBALANCE', 'MODEL_PORTFOLIO')
A5_ACCOUNT_SOURCE_ROLES = ('actual_broker', 'approved_target', 'verified_paper')


def portfolio_mode(request: dict) -> str:
    """The task's proposal mode is separate from its immutable authority."""
    value = request['parameters'].get('portfolio_mode', 'ACCOUNT_REBALANCE')
    if type(value) is not str or value not in A5_PORTFOLIO_MODES:
        raise ContractError('invalid_portfolio_mode')
    return value


def account_only_blockers(state: dict) -> set[str]:
    """Classify only exact reasons backed by canonical account-source states."""
    known = {'source_missing', 'source_expired', 'conflicting_sources', 'hash_mismatch',
             'source_time_conflict', 'source_expiry_conflict', 'malformed_or_unavailable_source',
             'accepted_domain_receipt_verifier_not_bound'}
    result = set()
    for role in A5_ACCOUNT_SOURCE_ROLES:
        for section in ('source_status', 'books'):
            value = state.get(section, {}).get(role, {})
            if value.get('status') in ('UNKNOWN', 'STALE', 'BLOCKED') and value.get('reason') in known:
                result.add(role + ':' + value['reason'])
    return result


def verify_current_model_incumbents(context: dict, root: Path, cutoff: datetime,
                                    now: datetime, *, policy: dict, code_sha: str) -> dict:
    return _verify_model_allocation_receipt(context, root, cutoff, now,
        policy=policy, code_sha=code_sha, lineage_policy=None)


def verify_model_parent_lineage(context: dict, root: Path, cutoff: datetime,
                                now: datetime, *, policy: dict, code_sha: str) -> dict:
    """Past acceptance, explicitly anchored by CURRENT policy, for comparison.

    Current Source/ER/risk/QA authority is not supplied by this parent. Original
    proof clocks are replayed at its actual accepted observation; current byte
    reads have separate inventory descriptors and cannot renew those proofs.
    """
    if type(policy) is not dict:
        raise ContractError('a5_model_external_review_required')
    parent = policy.get('model_lineage_parent')
    fields = {'schema', 'purpose', 'acceptance', 'accepted_at', 'state_sha256',
              'model_identity_sha256', 'available_at', 'expires_at'}
    if (type(parent) is not dict or set(parent) != fields
            or parent['schema'] != 'model-lineage-parent-policy-v1'
            or parent['purpose'] != 'PARENT_LINEAGE_ONLY'
            or not timestamp(parent['available_at']) <= cutoff < timestamp(parent['expires_at'])):
        raise ContractError('a5_model_explicit_last_parent_required')
    schema_validate(parent['acceptance'], 'task_packet_schema.json', 'artifact')
    if (parent['accepted_at'] != parent['acceptance']['collected_at']
            or timestamp(parent['accepted_at']) > timestamp(parent['available_at'])):
        raise ContractError('a5_model_parent_acceptance_clock')
    return _verify_model_allocation_receipt(context, root, cutoff, now,
        policy=policy, code_sha=code_sha, lineage_policy=parent)


def _verify_model_allocation_receipt(context: dict, root: Path, cutoff: datetime,
                                     now: datetime, *, policy: dict, code_sha: str,
                                     lineage_policy: dict | None) -> dict:
    """Replay an externally pinned MODEL allocation, never an executed book.

    The policy is an external review authority, as for existing position pins;
    it must not be manufactured from this context. Runtime calls this only
    after its current A3 profile has authenticated the complete context.
    """
    from research.multi_asset_v1.contracts import pinned, number, identifier, digest as position_digest
    from r1000_legacy_input_guard import latest_completed_close
    if type(policy) is not dict:
        raise ContractError('a5_model_external_review_required')
    if type(code_sha) is not str or re.fullmatch('[0-9a-f]{40}', code_sha) is None:
        raise ContractError('a5_model_consumer_identity_required')
    schema_validate(context, 'system_state_schema.json', 'a5_portfolio_context')
    model = context['model_state']
    expected_kind = 'PARENT_LINEAGE_ONLY' if lineage_policy is not None else 'INCUMBENTS'
    if model['kind'] != expected_kind:
        raise ContractError('a5_model_incumbents_required')
    proof_cutoff = timestamp(lineage_policy['accepted_at']) if lineage_policy is not None else cutoff
    proof_now = proof_cutoff if lineage_policy is not None else now
    acceptance_ref = lineage_policy['acceptance'] if lineage_policy is not None else model['artifact']
    if (lineage_policy is not None and (model['artifact']['path'] != acceptance_ref['path']
            or model['artifact']['sha256'] != acceptance_ref['sha256'])):
        raise ContractError('a5_model_last_parent_identity')
    inventory = context['artifact_inventory']
    originals, total, loaded, used, observations = {}, 0, {}, {}, {}
    for artifact in inventory.values():
        previous = originals.setdefault(artifact['path'], artifact)
        if digest(previous) != digest(artifact):
            raise ContractError('a5_model_artifact_conflict')

    def read_original(artifact):
        nonlocal total
        schema_validate(artifact, 'task_packet_schema.json', 'artifact')
        observation = originals.get(artifact['path'])
        if lineage_policy is None:
            if digest(observation) != digest(artifact):
                raise ContractError('a5_model_original_not_in_inventory')
        elif observation is not None and observation['sha256'] != artifact['sha256']:
            raise ContractError('a5_model_parent_original_not_in_inventory')
        elif observation is None and artifact['path'] == acceptance_ref['path']:
            raise ContractError('a5_model_parent_original_not_in_inventory')
        key = digest(artifact)
        if key not in loaded:
            path = artifact_path(root, artifact['path'])
            size = path.stat().st_size
            if size > 4 * 1024 * 1024 or total + size > 32 * 1024 * 1024:
                raise ContractError('a5_model_artifact_budget')
            total += size
            verify_artifact(root, artifact, proof_cutoff, proof_now)
            if lineage_policy is not None and observation is not None:
                verify_artifact(root, observation, cutoff, now)
            with path.open('rb') as stream:
                raw = stream.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024 or digest_bytes(raw) != artifact['sha256']:
                raise ContractError('a5_model_artifact_changed')
            loaded[key] = raw
            used[key] = artifact
            observations[key] = observation
        return loaded[key]

    def load(artifact):
        # QA operands may be CSV, Parquet or other opaque source bytes. Decode
        # JSON only for the packet/state/receipt/bundle/report schema roles.
        try:
            return json.loads(read_original(artifact), object_pairs_hook=_review_pairs,
                              parse_constant=_review_invalid)
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            raise ContractError('a5_model_original_json') from None

    acceptance = load(acceptance_ref)
    schema_validate(acceptance, 'system_state_schema.json', 'model_incumbents_acceptance')
    # A successful A5 proposal or QA receipt is not acceptance. This external
    # policy pin binds the final allocation-state receipt and all original refs.
    pinned(acceptance, policy, 'positions', proof_cutoff.isoformat())
    if (digest(acceptance['model_identity']) != digest(model['model_identity'])
            or acceptance['as_of'] > context['market_session_date']
            or latest_completed_close(cutoff)[0] != context['market_session_date']
            or latest_completed_close(timestamp(acceptance['decision_time']))[0] != acceptance['as_of']
            or timestamp(context['decision_time']) != cutoff
            or not timestamp(acceptance['decision_time']) <= proof_cutoff < timestamp(acceptance['expires_at'])
            or timestamp(acceptance['collected_at']) > timestamp(acceptance_ref['observed_at'])
            or timestamp(acceptance_ref['expires_at']) > timestamp(acceptance['expires_at'])):
        raise ContractError('a5_model_identity_or_clock_mismatch')
    if lineage_policy is not None and (position_digest(acceptance['model_identity']) != lineage_policy['model_identity_sha256']
            or acceptance['proofs']['state']['sha256'] != lineage_policy['state_sha256']):
        raise ContractError('a5_model_parent_state_identity')
    principals = acceptance['principals']
    if principals['A5'] == principals['A6']:
        raise ContractError('a5_model_review_not_independent')
    for principal in principals.values():
        identifier(principal)
    proof = {role: load(ref) for role, ref in acceptance['proofs'].items()}
    state = proof['state']
    schema_validate(state, 'system_state_schema.json', 'model_allocation_state')
    for field in ('model_identity', 'as_of', 'decision_time', 'positions', 'cash_weight'):
        if digest(state[field]) != digest(acceptance[field]):
            raise ContractError('a5_model_original_state_mismatch')
    state_ref = acceptance['proofs']['state']
    if (acceptance['raw_sha256'] != state_ref['sha256']
            or position_digest(state['positions']) != acceptance['positions_sha256']
            or timestamp(state['decision_time']) > timestamp(state_ref['observed_at'])):
        raise ContractError('a5_model_original_state_identity')
    positions = {}
    for row in state['positions']:
        identifier(row['asset_id'])
        if row['asset_id'] in positions or row['asset_id'] not in context['requested_security_ids']:
            raise ContractError('a5_model_position_identity')
        number(row['weight'], 0, 1)
        positions[row['asset_id']] = row['weight']
    cash_weight = number(state['cash_weight'], 0, 1)
    if (not positions and cash_weight != 1) or abs(sum(positions.values()) + cash_weight - 1) > 1e-9:
        raise ContractError('a5_model_position_weights')
    parent_roles = ('parent_acceptance', 'parent_state')
    has_parent = 'parent_state_sha256' in state or 'parent_acceptance_sha256' in state
    if has_parent:
        if not all(role in proof for role in parent_roles):
            raise ContractError('a5_model_parent_physical_proofs_required')
        parent_acceptance, parent_state = (proof[role] for role in parent_roles)
        schema_validate(parent_acceptance, 'system_state_schema.json', 'model_incumbents_acceptance')
        schema_validate(parent_state, 'system_state_schema.json', 'model_allocation_state')
        if (state['parent_state_sha256'] != acceptance['proofs']['parent_state']['sha256']
                or state['parent_acceptance_sha256'] != acceptance['proofs']['parent_acceptance']['sha256']
                or parent_acceptance['raw_sha256'] != state['parent_state_sha256']
                or any(digest(parent_acceptance[k]) != digest(parent_state[k])
                       for k in ('model_identity', 'positions', 'cash_weight', 'as_of', 'decision_time'))
                or digest(parent_state['model_identity']) != digest(state['model_identity'])
                or timestamp(parent_state['decision_time']) >= timestamp(state['decision_time'])
                or parent_state['origin_a5_task_key'] == state['origin_a5_task_key']):
            raise ContractError('a5_model_parent_lineage_identity')
        if lineage_policy is None:
            expected_parent = policy.get('model_lineage_parent', {})
            if ((expected_parent and (expected_parent.get('acceptance', {}).get('sha256') != state['parent_acceptance_sha256']
                    or expected_parent.get('state_sha256') != state['parent_state_sha256']))
                    or position_digest(parent_acceptance) not in policy['reviewed_pins'].get('positions', [])):
                raise ContractError('a5_model_parent_external_last_pin_required')
        if state.get('assessment_kind') == 'HOLD_REAFFIRMATION' and any(
                digest(state[k]) != digest(parent_state[k]) for k in ('positions', 'cash_weight')):
            raise ContractError('a5_model_hold_reaffirmation_changed_weights')
    elif any(role in proof for role in parent_roles):
        raise ContractError('a5_model_unbound_parent_proof')
    schema = read_json(CONTRACT_DIR / 'system_state_schema.json')
    receipt_schema = {**schema['properties']['completed_tasks']['items'], '$defs': schema['$defs']}
    qa_packet, qa_receipt = proof['a6_packet'], proof['a6_receipt']
    for agent in ('A5', 'A6'):
        packet, receipt = proof[agent.lower() + '_packet'], proof[agent.lower() + '_receipt']
        schema_validate(packet, 'task_packet_schema.json')
        if list(Draft202012Validator(receipt_schema, format_checker=FormatChecker()).iter_errors(receipt)):
            raise ContractError('a5_model_completion_schema')
        spec = contracts()['agents'][agent]
        if (packet['agent'] != agent or receipt['agent'] != agent
                or packet['task_key'] != receipt['task_key']
                or packet['task_key'] != digest({'agent': agent, **packet['identity']})
                or packet['status'] not in ('READY', 'SKIP_UNCHANGED')
                or receipt['status'] != 'SUCCEEDED'
                or packet['authority'] != AUTHORITY or packet['reasons']
                or packet['mode'] != spec['mode'] or packet['outputs'] != spec['outputs']
                or set(packet['inputs']) != set(spec['inputs'])
                or packet['dependencies'] != spec['dependencies']
                or set(packet['dependency_outputs']) != set(spec['dependencies'])
                or packet['identity']['code_sha'] != acceptance['producer_code_sha']
                or packet['identity']['config_hash'] != acceptance['producer_config_hash']
                or set(receipt['outputs']) != set(spec['outputs'])):
            raise ContractError('a5_model_original_task_identity')
        if agent == 'A5':
            if portfolio_mode({'parameters': packet['identity']['parameters']}) != 'MODEL_PORTFOLIO':
                raise ContractError('a5_model_original_account_proposal')
            original_context = load(packet['inputs']['portfolio_context'])
            schema_validate(original_context, 'system_state_schema.json', 'a5_portfolio_context')
            if (original_context['decision_time'] != state['decision_time']
                    or original_context['market_session_date'] != state['as_of']
                    or not set(positions) <= set(original_context['requested_security_ids'])):
                raise ContractError('a5_model_original_selection')
        causal = list(packet['inputs'].values())
        for dependency_agent, dependency in packet['dependency_outputs'].items():
            if dependency.get('agent') != dependency_agent:
                raise ContractError('a5_model_dependency_agent')
            for role, artifact in dependency['outputs'].items():
                if digest(packet['inputs'].get(role)) != digest(artifact):
                    raise ContractError('a5_model_dependency_operand_mismatch')
            causal.extend(dependency['outputs'].values())
        if agent == 'A6':
            bundle = load(packet['inputs']['review_bundle'])
            schema_validate(bundle, 'system_state_schema.json', 'qa_bundle')
            causal.extend(bundle['artifacts'].values())
        for artifact in causal + list(receipt['outputs'].values()):
            read_original(artifact)
        request = dict(agent=agent, inputs=packet['inputs'], model=packet['identity']['model'],
                       parameters=packet['identity']['parameters'])
        ready = max(timestamp(a['collected_at']) for a in causal)
        verify_completion(receipt, packet['identity'], request, packet['dependency_outputs'], ready, proof_cutoff)
        receipt_ref = acceptance['proofs'][agent.lower() + '_receipt']
        if timestamp(receipt['available_at']) > timestamp(receipt_ref['observed_at']):
            raise ContractError('a5_model_completion_descriptor_clock')
        for artifact in receipt['outputs'].values():
            if (timestamp(artifact['available_at']) <= ready
                    or timestamp(artifact['collected_at']) >= timestamp(receipt['created_at'])):
                raise ContractError('a5_model_completion_output_clock')
    target = proof['a5_receipt']['outputs']['target_proposal']
    if ('assessment_inputs_sha256' in state and
            state['assessment_inputs_sha256'] != position_digest(proof['a5_packet']['inputs'])):
        raise ContractError('a5_model_assessment_original_inputs_changed')
    if has_parent and (original_context['model_state']['kind'] not in ('INCUMBENTS', 'PARENT_LINEAGE_ONLY')
            or original_context['model_state']['artifact']['sha256'] != state['parent_acceptance_sha256']):
        raise ContractError('a5_model_parent_not_original_a5_comparison')
    if (state['origin_a5_task_key'] != proof['a5_packet']['task_key']
            or timestamp(proof['a5_receipt']['available_at']) > timestamp(state_ref['available_at'])):
        raise ContractError('a5_model_state_predates_proposal')
    report = load(qa_receipt['outputs']['qa_report'])
    schema_validate(report, 'system_state_schema.json', 'qa_report')
    bundle = load(qa_packet['inputs']['review_bundle'])
    # A6 has no agent-dispatch dependencies. Its existing review-bundle source
    # hash instead binds these exact A5 causal operands, including provenance.
    required = [state_ref, target, acceptance['proofs']['a5_packet'],
                acceptance['proofs']['a5_receipt']] + list(proof['a5_packet']['inputs'].values())
    if has_parent:
        required += [acceptance['proofs'][role] for role in parent_roles]
    scope = {digest(a) for a in report['reviewed_artifacts'].values()}
    if (report['verdict'] != 'PASS' or report['reviewed_artifacts'] != bundle['artifacts']
            or report['review_bundle_sha256'] != qa_packet['inputs']['review_bundle']['sha256']
            or not all(digest(a) in scope for a in required)
            or timestamp(qa_receipt['available_at']) > timestamp(acceptance['available_at'])):
        raise ContractError('a5_model_original_qa_scope_or_clock')
    proof_expiry = [timestamp(a['expires_at']) for key, a in used.items()
                    if key != digest(acceptance_ref)]
    if timestamp(acceptance['expires_at']) > min(proof_expiry):
        raise ContractError('a5_model_acceptance_expiry_extension')
    result = dict(status='PARENT_LINEAGE_ONLY_VERIFIED' if lineage_policy is not None else 'CURRENT_MODEL_ALLOCATION_VERIFIED', book_kind='MODEL',
        model_identity=acceptance['model_identity'], as_of=acceptance['as_of'],
        decision_time=acceptance['decision_time'], producer_code_sha=acceptance['producer_code_sha'],
        producer_config_hash=acceptance['producer_config_hash'], consumer_code_sha=code_sha,
        comparison_session=context['market_session_date'], expires_at=acceptance['expires_at'],
        allocation_relation=('PARENT_LINEAGE_ONLY' if lineage_policy is not None else
                            'PRIOR_ACTIVE_MODEL_ALLOCATION' if acceptance['as_of'] < context['market_session_date']
                             else 'SAME_SESSION_MODEL_ALLOCATION'),
        current_weights=positions, cash_weight=state['cash_weight'],
        origin_a5_task_key=state['origin_a5_task_key'],
        original_a5_inputs_sha256=position_digest(proof['a5_packet']['inputs']),
        acceptance_sha256=model['artifact']['sha256'],
        parent_acceptance=model['artifact'], parent_state=state_ref,
        actual_holdings_claimed=False, execution_or_performance_claimed=False,
        eligible_for_economics=False, accepted_book_write_allowed=False)
    if lineage_policy is not None:
        result.update(historical_acceptance_verified_at=lineage_policy['accepted_at'],
            comparison_authorization_expires_at=lineage_policy['expires_at'],
            parent_acceptance=observations[digest(acceptance_ref)] or acceptance_ref,
            parent_state=observations[digest(state_ref)] or state_ref,
            original_acceptance_descriptor=acceptance_ref,
            parent_source_or_er_freshness_granted=False)
    return result


def a5_model_preparation(request: dict, root: Path, cutoff: datetime, now: datetime, *,
                         model_policy=None, code_sha=None):
    """Replay candidate references for task preparation, never domain admission.

    The existing Registry deliberately keeps current selection, independent
    review and economic admission closed. A READY A0 task cannot override it.
    """
    from research.candidate_registry_v1 import build_reference_index
    context = read_json(artifact_path(root, request['inputs']['portfolio_context']['path']))
    schema_validate(context, 'system_state_schema.json', 'a5_portfolio_context')
    if context['portfolio_mode'] != 'MODEL_PORTFOLIO' or timestamp(context['decision_time']) != cutoff:
        raise ContractError('a5_context_mode_or_cutoff_mismatch')
    requested = context['requested_security_ids']
    entries = context['a3_reference_entries']
    if set(requested) != {entry['asset_id'] for entry in entries} or len(entries) != len(requested):
        raise ContractError('a5_candidate_roster_mismatch')
    incumbents = None
    parent_lineage = None
    if context['model_state']['kind'] == 'INCUMBENTS':
        incumbents = verify_current_model_incumbents(context, root, cutoff, now,
                                                   policy=model_policy, code_sha=code_sha)
    elif context['model_state']['kind'] == 'PARENT_LINEAGE_ONLY':
        parent_lineage = verify_model_parent_lineage(context, root, cutoff, now,
                                                    policy=model_policy, code_sha=code_sha)
    from tools import market_analysis_engine as market
    a4 = context['a4_request']
    request_path = artifact_path(root, a4['path'])
    if request_path.stat().st_size > 256 * 1024:
        raise ContractError('a5_a4_request_budget')
    verify_artifact(root, a4, cutoff, now)
    with request_path.open('rb') as handle:
        request_raw = handle.read(256 * 1024 + 1)
    a4_request = market.verify_request(request_raw, a4['sha256'], context['decision_time'],
                                       context['market_session_date'])
    artifacts = context['artifact_inventory']
    a4_sources = {}
    for spec in a4_request['inputs']:
        path = (Path(context['a4_source_root']) / market.safe_path(spec['path'])).as_posix()
        matches = [a for a in artifacts.values() if a['path'] == path and a['sha256'] == spec['sha256']]
        if len(matches) != 1:
            raise ContractError('a5_a4_original_not_in_review_inventory')
        a4_sources[(path, spec['sha256'])] = spec
    values, a3_total, a4_total = {}, 0, 0
    for aid, artifact in artifacts.items():
        path = artifact_path(root, artifact['path'])
        size = path.stat().st_size
        spec = a4_sources.get((artifact['path'], artifact['sha256']))
        limit = market.input_limit(spec) if spec is not None else 4 * 1024 * 1024
        if spec is None:
            a3_total += size
        else:
            a4_total += size
        if size > limit or a3_total > 32 * 1024 * 1024 or a4_total > market.MAX_TOTAL_BYTES:
            raise ContractError('a5_candidate_artifact_budget')
        verify_artifact(root, artifact, cutoff, now)
        with path.open('rb') as handle:
            raw = handle.read(limit + 1)
        if len(raw) > limit or digest_bytes(raw) != artifact['sha256']:
            raise ContractError('a5_candidate_artifact_changed')
        values[(aid, artifact['sha256'])] = raw
    def resolve(aid, sha):
        try:
            return values[(aid, sha)]
        except KeyError:
            raise ContractError('a5_original_artifact_missing') from None
    index = build_reference_index(entries, cutoff=context['decision_time'], artifact_resolver=resolve)
    if any(row['reference_status'] != 'A3_REFERENCE_REPLAY_VERIFIED'
           or row['declared_expiry_state'] != 'UNEXPIRED'
           or row['validated_er_ref'] is None for row in index['records']):
        raise ContractError('a5_candidate_reference_or_er_blocked')
    sessions = {row['metadata']['market_session_date'] for row in index['records']}
    if sessions != {context['market_session_date']}:
        raise ContractError('a5_candidate_session_mismatch')
    from r1000_legacy_input_guard import latest_completed_close
    if latest_completed_close(cutoff)[0] != context['market_session_date']:
        raise ContractError('a5_session_not_current_completed_close')
    original = read_json(artifact_path(root, request['inputs']['expected_return']['path']))
    if digest(original) != digest(index):
        raise ContractError('a5_expected_return_reference_set_mismatch')
    risk = market.load_report(artifact_path(root, a4['path']), artifact_path(root, context['a4_source_root']),
                       a4['sha256'], cutoff=context['decision_time'], session=context['market_session_date'])
    if risk.get('status') != 'READY_RESEARCH_ONLY':
        raise ContractError('a5_a4_native_inputs_not_ready')
    if digest(read_json(artifact_path(root, request['inputs']['regime']['path']))) != digest(risk):
        raise ContractError('a5_a4_original_report_mismatch')
    reviewed = {'a3:' + aid: artifact for aid, artifact in artifacts.items()}
    reviewed['a4:request'] = a4
    info = dict(portfolio_mode='MODEL_PORTFOLIO', preparation_scope='A0_TASK_PREPARATION_ONLY',
        model_state_kind=context['model_state']['kind'],
        requested_security_ids=requested, reference_index_sha256=index['index_sha256'],
        economic_input_admission='BLOCKED', domain_blockers=sorted({reason for row in index['records']
            for reason in row['consumption_blockers']}), current_a3_review_admitted=False,
        dispatch_allowed=False, target_write_allowed=False, account_rebalance_allowed=False,
        actual_holdings_claimed=False)
    if incumbents is not None:
        info['model_incumbents'] = incumbents
    if parent_lineage is not None:
        info['model_parent_lineage'] = parent_lineage
    return info, reviewed


def digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def current_a3_reference_admission(binding: dict, policy: dict, root: Path,
                                   cutoff: datetime, code_sha: str,
                                   requested: list, entries: list,
                                   feature_sha256: str, risk: dict) -> dict:
    """Replay an externally reviewed, purpose-specific A0/A3/A6 graph.

    This is deliberately not materializer.verify_state: its global canonical
    readiness/PIT restrictions remain unchanged. An independently pinned policy
    authenticates this exact forward-only selection and its principals. Existing
    completion, QA, original A3/ER and native A4 verifiers still have to pass.
    """
    from research.multi_asset_v1.contracts import current_a3_profile
    schema_validate(binding, 'system_state_schema.json', 'current_a3_review_binding')
    profile = current_a3_profile(policy, binding, feature_sha256, risk, cutoff.isoformat(), code_sha)
    if root is None:
        raise ContractError('a3_review_original_root_required')
    root = Path(root)
    snapshots = {}
    for role, artifact in binding.items():
        schema_validate(artifact, 'task_packet_schema.json', 'artifact')
        path = artifact_path(root, artifact['path'])
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ContractError('a3_review_graph_budget')
        verify_artifact(root, artifact, cutoff, cutoff)
        with path.open('rb') as stream:
            raw = stream.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024 or digest_bytes(raw) != artifact['sha256']:
            raise ContractError('a3_review_graph_changed')
        snapshots[role] = json.loads(raw, object_pairs_hook=_review_pairs,
                                    parse_constant=_review_invalid)
    context, graph = snapshots['portfolio_context'], snapshots['review_graph']
    schema_validate(context, 'system_state_schema.json', 'a5_portfolio_context')
    if (type(graph) is not dict or set(graph) != {'schema_version', 'state', 'task_packets', 'principals'}
            or graph['schema_version'] != 'current-a3-review-graph-v1'
            or graph['principals'] != profile['principals']):
        raise ContractError('a3_review_graph_contract')
    state = graph['state']
    schema_validate(state, 'system_state_schema.json')
    if (timestamp(state['as_of']) != cutoff or state['code_sha'] != code_sha
            or state['master_sha'] != code_sha or timestamp(state['expires_at']) <= cutoff
            or timestamp(profile['available_at']) < max(timestamp(a['collected_at']) for a in binding.values())
            or context['requested_security_ids'] != requested
            or context['a3_reference_entries'] != entries
            or timestamp(context['decision_time']) != cutoff):
        raise ContractError('a3_review_selection_or_clock')
    requests = {r['agent']: r for r in state['requests']}
    if set(requests) != {'A1', 'A2', 'A3', 'A4', 'A5', 'A6'}:
        raise ContractError('a3_review_complete_graph_required')
    request = requests['A5']
    if (portfolio_mode(request) != 'MODEL_PORTFOLIO'
            or request['inputs']['portfolio_context'] != binding['portfolio_context']):
        raise ContractError('a3_review_selected_context_mismatch')
    # Bound every original before the legacy planner's hash/read operations.
    originals = list(context['artifact_inventory'].values()) + [context['a4_request']]
    originals += [a for r in state['requests'] for a in r['inputs'].values()]
    originals += [a for r in state['completed_tasks'] for a in r['outputs'].values()]
    # The planner hashes every QA operand, including optional extra evidence.
    # Inspect its bounded original bundle before any transitive body hash/read.
    bundle_ref = requests['A6']['inputs']['review_bundle']
    bundle_path = artifact_path(root, bundle_ref['path'])
    if bundle_path.stat().st_size > 4 * 1024 * 1024:
        raise ContractError('a3_review_qa_bundle_budget')
    with bundle_path.open('rb') as stream:
        bundle_raw = stream.read(4 * 1024 * 1024 + 1)
    if len(bundle_raw) > 4 * 1024 * 1024 or digest_bytes(bundle_raw) != bundle_ref['sha256']:
        raise ContractError('a3_review_qa_bundle_changed')
    bundle = json.loads(bundle_raw, object_pairs_hook=_review_pairs, parse_constant=_review_invalid)
    if (type(bundle) is not dict or type(bundle.get('artifacts')) is not dict
            or len(bundle['artifacts']) > 256):
        raise ContractError('a3_review_original_count')
    schema_validate(bundle, 'system_state_schema.json', 'qa_bundle')
    originals += list(bundle['artifacts'].values())
    unique_originals = {}
    for artifact in originals:
        schema_validate(artifact, 'task_packet_schema.json', 'artifact')
        key = artifact['path']
        if key in unique_originals and unique_originals[key] != artifact:
            raise ContractError('a3_review_conflicting_original')
        unique_originals[key] = artifact
    if len(unique_originals) > 256:
        raise ContractError('a3_review_original_count')
    # A4 kind budgets are checked by the incumbent preparation verifier below;
    # this enclosing bound accounts for the entire transitive graph as well.
    total = 0
    for artifact in unique_originals.values():
        size = artifact_path(root, artifact['path']).stat().st_size
        total += size
        if size > 32 * 1024 * 1024 or total > 96 * 1024 * 1024:
            raise ContractError('a3_review_original_budget')
    for artifact in unique_originals.values():
        verify_artifact(root, artifact, cutoff, cutoff)
    index = read_json(artifact_path(root, request['inputs']['expected_return']['path']))
    refs = [entry[role] for entry in entries for role in ('a3_packet_ref', 'a3_result_ref')]
    refs += [ref for row in index['records'] for ref in row['upstream_artifact_refs'].values() if ref is not None]
    for ref in refs:
        original = context['artifact_inventory'].get(ref['artifact_id'])
        if (original is None or original['sha256'] != ref['sha256']
                or timestamp(original['available_at']) < timestamp(ref['available_at'])
                or timestamp(original['collected_at']) < timestamp(ref.get('collected_at', ref['available_at']))):
            raise ContractError('a3_review_original_reference_clock_or_identity')
    code_configs = {r['config_hash'] for r in state['completed_tasks']}
    if len(code_configs) != 1:
        raise ContractError('a3_review_config_conflict')
    packets = _plan_tasks(state, root, contracts(), cutoff, code_sha, next(iter(code_configs)),
                          model_policy=policy)
    if digest(packets) != digest(graph['task_packets']):
        raise ContractError('a3_review_original_task_packets_mismatch')
    by_agent = {p['agent']: p for p in packets}
    if (any(by_agent[a]['status'] != 'SKIP_UNCHANGED' for a in ('A1', 'A2', 'A3', 'A4', 'A6'))
            or by_agent['A5']['status'] != 'READY'):
        raise ContractError('a3_review_original_completion_blocked')
    qa = next(r for r in state['completed_tasks'] if r['agent'] == 'A6')
    report = read_json(artifact_path(root, qa['outputs']['qa_report']['path']))
    # QA must cover the actual operands, not only the reference index/summary.
    scope = {digest(a) for a in report['reviewed_artifacts'].values()}
    # _plan_tasks already replayed a5_model_preparation and its QA scope.
    # Reuse that original scope here; do not run the expensive A4 replay twice.
    required = list(context['artifact_inventory'].values()) + [context['a4_request']]
    for agent in ('A1', 'A2', 'A3', 'A4'):
        required.extend(requests[agent]['inputs'].values())
        required.extend(next(r for r in state['completed_tasks'] if r['agent'] == agent)['outputs'].values())
    if not all(digest(a) in scope for a in required):
        raise ContractError('a3_review_transitive_original_not_reviewed')
    if timestamp(qa['available_at']) > timestamp(profile['available_at']):
        raise ContractError('a3_review_profile_predates_qa')
    graph_ref = binding['review_graph']
    causal_end = max([timestamp(r['available_at']) for r in state['completed_tasks']]
                    + [timestamp(a['collected_at']) for a in unique_originals.values()])
    if (timestamp(graph_ref['observed_at']) < causal_end
            or timestamp(graph_ref['available_at']) < causal_end
            or timestamp(graph_ref['collected_at']) < causal_end
            or timestamp(graph_ref['expires_at']) > min(timestamp(state['expires_at']),
                *(timestamp(a['expires_at']) for a in unique_originals.values()))
            or timestamp(profile['expires_at']) > min(timestamp(a['expires_at']) for a in binding.values())):
        raise ContractError('a3_review_graph_causal_or_expiry_boundary')
    for artifact in unique_originals.values():
        verify_artifact(root, artifact, cutoff, cutoff)
    result = dict(status='CURRENT_REFERENCE_REVIEW_VERIFIED', purpose=profile['purpose'],
        task_keys={a: by_agent[a]['task_key'] for a in ('A3', 'A5', 'A6')},
        profile_sha256=digest(profile), graph_sha256=binding['review_graph']['sha256'],
        context_sha256=binding['portfolio_context']['sha256'],
        historical_pit_certified=False, source_admission_granted=False,
        portfolio_write_allowed=False)
    incumbents = by_agent['A5']['identity']['parameters']['a5_preparation'].get('model_incumbents')
    if incumbents is not None:
        result['model_incumbents'] = incumbents
    prepared = by_agent['A5']['identity']['parameters']['a5_preparation']
    result['model_state_kind'] = prepared['model_state_kind']
    if prepared.get('model_parent_lineage') is not None:
        result['model_parent_lineage'] = prepared['model_parent_lineage']
    return result


def _review_pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise ContractError('duplicate_json_key')
        result[key] = value
    return result


def _review_invalid(_):
    raise ContractError('nonfinite_json')


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
    values = ast.literal_eval(nodes[0].value)
    return {'source': 'r1000_config.py:PORTFOLIO_MISSION_TARGETS',
            'source_sha256': file_hash(path), 'values': values,
            **mission_identity(values),
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


def evidence_identity(kind: str, reference: str, task_key: str,
                      packet_identity: dict, head_sha: str,
                      outputs: dict[str, dict], available_at: str) -> str:
    """Scope test/run evidence to the task, output descriptors, and causal time."""
    return digest({'kind': kind, 'reference': reference, 'task_key': task_key,
                   'packet_identity': packet_identity, 'head_sha': head_sha,
                   'outputs': outputs, 'available_at': available_at})


def verify_completion(receipt: dict, packet_identity: dict, request: dict,
                      dependencies: dict, causal_ready: datetime, cutoff: datetime) -> None:
    """Verify a completed_tasks V2 row; declarations alone do not grant merge authority."""
    hashes = {role: item['sha256'] for role, item in request['inputs'].items()}
    expected = {'identity': packet_identity, 'source_hashes': hashes, 'input_hashes': hashes,
                'dependency_identities': receipt_dependencies(dependencies),
                'code_sha': packet_identity['code_sha'], 'config_hash': packet_identity['config_hash'],
                'model': packet_identity['model'], 'parameter_hash': digest(packet_identity['parameters'])}
    if (receipt['task_key'] != digest({'agent': request['agent'], **packet_identity})
            or any(receipt[name] != value for name, value in expected.items())):
        raise ContractError('receipt_identity_mismatch')
    if receipt['side_effects'] or receipt['verification_status'] != 'VERIFIED':
        raise ContractError('receipt_unverified_or_mutating')
    ai_mode = receipt['execution_mode'] in ('GENERAL_CHATGPT', 'WORK', 'CODEX')
    if receipt['ai_invoked'] != ai_mode:
        raise ContractError('receipt_ai_provenance_conflict')
    if ai_mode != (receipt['ai_invocation_reason'] is not None):
        raise ContractError('receipt_ai_reason_conflict')
    if ai_mode and not receipt['model'].get('provider'):
        raise ContractError('receipt_ai_provider_missing')
    created, available = timestamp(receipt['created_at']), timestamp(receipt['available_at'])
    if not causal_ready <= created <= available <= cutoff:
        raise ContractError('receipt_time_boundary')
    output_collected = max(timestamp(item['collected_at']) for item in receipt['outputs'].values())
    for name in ('runtime_verification', 'focused_tests', 'ci'):
        evidence = receipt[name]
        if evidence['status'] != 'PASS':
            raise ContractError('receipt_' + name + '_not_pass')
        evidence_available = timestamp(evidence['available_at'])
        if not output_collected < evidence_available < created:
            raise ContractError('receipt_' + name + '_time_boundary')
        if (evidence['head_sha'] != packet_identity['code_sha']
                or evidence['identity'] != evidence_identity(
                    name, evidence['reference'], receipt['task_key'], packet_identity,
                    evidence['head_sha'], receipt['outputs'], evidence['available_at'])):
            raise ContractError('receipt_' + name + '_identity_mismatch')
    if receipt['reviewed_head'] is not None and receipt['reviewed_head'] != packet_identity['code_sha']:
        raise ContractError('receipt_old_review_head')


APPROVAL_ACTIONS = frozenset({'fullrun', 'actual_broker', 'paper_book', 'target_book',
    'production_activation', 'live_trading', 'new_alpha_logic', 'er_weight_change',
    'risk_limit_relaxation', 'review_gate_relaxation', 'protected_evidence_change'})
SAFE_ACTION_TIERS = {'read': 'T0_READ', 'compute': 'T1_COMPUTE',
                     'prepare': 'T2_PREPARE', 'reversible_repo_write': 'T3_REVERSIBLE_WRITE'}
RISK_TIERS = frozenset({'T0_READ', 'T1_COMPUTE', 'T2_PREPARE', 'T3_REVERSIBLE_WRITE',
                        'T4_ECONOMIC_MUTATION', 'T5_IRREVERSIBLE_OR_PROTECTED'})
NOTIFY_STATES = frozenset({'BLOCKED', 'HUMAN_APPROVAL_REQUIRED', 'CORRECTION_REQUIRED',
                           'READY_TO_MERGE', 'DONE'})


def post_merge_pass(event: dict, expected_pr_head: str, expected_scope: dict | None) -> bool:
    """Use only a typed pass bound to the observed merge and default-branch head."""
    evidence = event.get('post_merge_verified')
    merge_sha, default_head = event.get('merge_sha'), event.get('default_branch_head')
    return (expected_scope is not None and event.get('merge_scope') == expected_scope
            and isinstance(evidence, dict) and evidence.get('review_scope') == expected_scope
            and evidence.get('status') == 'PASS'
            and isinstance(evidence.get('identity'), str) and bool(evidence['identity'].strip())
            and isinstance(merge_sha, str) and re.fullmatch(r'[0-9a-f]{40}', merge_sha) is not None
            and event.get('merged_pr_head') == expected_pr_head
            and evidence.get('pr_head_sha') == expected_pr_head
            and merge_sha == default_head == evidence.get('merge_sha')
            == evidence.get('default_branch_head'))


def current_required_checks_pass(event: dict, packet: dict) -> bool:
    """Consume a trusted, current ruleset observation, including check app identity."""
    policy = event.get('required_checks_policy')
    if not isinstance(policy, dict) or policy.get('source') != 'GITHUB_RULESET':
        return False
    try:
        updated = timestamp(policy['ruleset_updated_at'])
        observed = timestamp(policy['observed_at'])
    except (KeyError, ValueError, TypeError, AttributeError, ContractError):
        return False
    head, scope = packet['identity']['code_sha'], packet.get('review_scope')
    base = event.get('current_base_sha')
    checks = policy.get('checks')
    if (scope is None or policy.get('scope') != scope or policy.get('pr_head_sha') != head
            or not isinstance(base, str) or re.fullmatch(r'[0-9a-f]{40}', base) is None
            or policy.get('base_sha') != base or policy.get('strict') is not True
            or event.get('base_ancestor_verified') is not True
            or type(policy.get('ruleset_id')) is not int or policy['ruleset_id'] <= 0
            or observed < updated
            or not isinstance(policy.get('identity'), str) or not policy['identity'].strip()
            or not isinstance(checks, list) or not isinstance(event.get('ci_checks'), dict)):
        return False
    keys = []
    for check in checks:
        if (not isinstance(check, dict) or set(check) != {'context', 'integration_id'}
                or not isinstance(check['context'], str) or not check['context']
                or type(check['integration_id']) is not int or check['integration_id'] <= 0):
            return False
        keys.append(f"{check['context']}@{check['integration_id']}")
    if len(set(keys)) != len(keys) or not {'validate@15368', 'portfolio_guard@15368'}.issubset(keys):
        return False
    return all(event['ci_checks'].get(key) == 'PASS' for key in keys
               if key != 'review_complete@15368')


def review_complete_pass(event: dict, packet: dict) -> bool:
    """Evaluate the attestation check after review, bound to its GitHub App."""
    evidence = event.get('review_complete_evidence')
    policy = event.get('required_checks_policy')
    if not isinstance(evidence, dict) or not isinstance(policy, dict):
        return False
    checks = policy.get('checks')
    if not isinstance(checks, list):
        return False
    attestation = [row for row in checks if isinstance(row, dict)
                   and row.get('context') == 'review_complete']
    if attestation and attestation != [{'context': 'review_complete', 'integration_id': 15368}]:
        return False
    if event.get('ci_checks', {}).get('review_complete@15368') != 'PASS':
        return False
    return (evidence.get('context') == 'review_complete'
            and evidence.get('integration_id') == 15368
            and evidence.get('status') == 'PASS'
            and evidence.get('head_sha') == packet['identity']['code_sha']
            and evidence.get('scope') == packet.get('review_scope')
            and isinstance(evidence.get('identity'), str) and bool(evidence['identity'].strip()))


def lifecycle_state(packet: dict | None, event: dict | None = None) -> dict:
    """Pure event reducer. Caller must obtain CI/review/merge facts from GitHub.

    No event fetching, scheduling, specialist invocation, notification or mutation.
    An unverified worker report is deliberately not an input to this reducer.
    """
    event = event or {}
    action = event.get('action')
    effects = event.get('side_effects', [])
    tier = event.get('risk_tier')
    if (not isinstance(effects, list) or not isinstance(action, (str, type(None)))
            or (tier is not None and (not isinstance(tier, str) or tier not in RISK_TIERS))):
        state = 'BLOCKED'
    elif (action in APPROVAL_ACTIONS or tier in ('T4_ECONOMIC_MUTATION', 'T5_IRREVERSIBLE_OR_PROTECTED')
          or any(effect in APPROVAL_ACTIONS for effect in effects if isinstance(effect, str))
          or (effects and (tier != 'T3_REVERSIBLE_WRITE' or effects != ['reversible_repo_write']))
          or (action is not None and action not in SAFE_ACTION_TIERS)):
        state = 'HUMAN_APPROVAL_REQUIRED'
    elif ((action is not None and tier is not None and tier != SAFE_ACTION_TIERS[action])
          or (action == 'reversible_repo_write' and
              (tier != 'T3_REVERSIBLE_WRITE' or effects != ['reversible_repo_write']))):
        state = 'BLOCKED'
    elif packet is None:
        state = 'QUEUED'
    elif packet['status'] == 'BLOCKED' or event.get('integrity_failure'):
        state = 'BLOCKED'
    elif type(event.get('unresolved_findings', 0)) is not int:
        state = 'BLOCKED'
    elif (('review' in event or 'review_complete' in event)
          and (packet.get('review_scope') is None
               or event.get('review_scope') != packet['review_scope']
               or ('review_complete' in event and
                   event.get('review_complete_scope') != packet['review_scope']))):
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
          or not current_required_checks_pass(event, packet)):
        state = 'WAITING_CI'
    elif (event.get('review') != 'CLEAN' or event.get('review_head') != packet['identity']['code_sha']
          or event.get('unresolved_findings') != 0):
        state = 'WAITING_REVIEW'
    elif packet['status'] != 'SKIP_UNCHANGED':
        state = 'READY'
    elif (event.get('review_complete') == 'PASS'
          and event.get('review_complete_head') == packet['identity']['code_sha']
          and review_complete_pass(event, packet)):
        if event.get('merged') is True:
            state = ('DONE' if post_merge_pass(event, packet['identity']['code_sha'],
                                               packet.get('review_scope'))
                     else 'POST_MERGE_VERIFY')
        elif event.get('merged') is False or event.get('merged') is None:
            state = 'READY_TO_MERGE'
        else:
            state = 'BLOCKED'
    elif event.get('merged'):
        state = 'BLOCKED'
    else:
        state = 'READY_FOR_ATTESTATION'
    return {'state': state, 'notification_worthy': state in NOTIFY_STATES or
            bool(event.get('integrity_failure') or event.get('unexpected_regression')),
            'polling_required': False, 'ai_invocation_required': False}


def contracts() -> dict:
    # JSON is a YAML subset; use strict duplicate/nonfinite parsing with no YAML tags.
    value = read_json(CONTRACT_DIR / 'agent_contracts_v2.yaml')
    agents = value['agents']
    if set(agents) != {f'A{i}' for i in range(9)} or value['authority'] != AUTHORITY:
        raise ContractError('contract_authority')
    if value['orchestrator'] != 'A0' or value['specialist_dispatch_enabled'] is not False:
        raise ContractError('contract_dispatch')
    if (agents['A5'].get('portfolio_modes') != list(A5_PORTFOLIO_MODES)
            or agents['A5'].get('default_portfolio_mode') != 'ACCOUNT_REBALANCE'):
        raise ContractError('contract_portfolio_modes')
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


def ohlcv_parameters(request: dict, root: Path, cutoff: datetime, now: datetime):
    """Derive DRY_RUN payload inside the existing A1 packet, never another queue.

    The public build_tasks path still requires freshly materialized canonical
    evidence. Byte/time verification here does not authenticate provider rights,
    event identity, exchange calendars or a worker's own review declarations.
    """
    if 'a2_a1_ohlcv' in request['parameters']:
        raise ContractError('reserved_ohlcv_parameter')
    if request['agent'] != 'A1':
        return None
    ref = request['inputs']['source_inventory']
    path = artifact_path(root, ref['path'])
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ContractError('ohlcv_inventory_size')
    with path.open('rb') as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ContractError('ohlcv_inventory_size')
    if hashlib.sha256(raw).hexdigest() != ref['sha256']:
        raise ContractError('ohlcv_inventory_changed')
    try:
        marker = json.loads(raw)
    except (ValueError, UnicodeError):
        return None  # Preserve the existing generic artifact-only A1 path.
    if not isinstance(marker, dict) or marker.get('schema') not in {
            'a2-a1-ohlcv-source-inventory-v1', 'a2-a1-readiness-lookup-v1'}:
        return None
    from research import a2_a1_ohlcv_handoff_v1 as handoff
    inventory = handoff.h.decode(raw)
    refs = inventory.get('artifacts')
    if type(refs) is not dict or len(refs) > 128:
        raise ContractError('ohlcv_artifact_count')
    values = {}
    total = 0
    for aid, artifact in refs.items():
        handoff.h.identifier(aid)
        schema_validate(artifact, 'task_packet_schema.json', 'artifact')
        child = artifact_path(root, artifact['path'])
        size = child.stat().st_size
        if size > handoff.h.MAX_BYTES or total + size > handoff.h.MAX_TOTAL_BYTES:
            raise ContractError('ohlcv_artifact_bytes')
        with child.open('rb') as stream:
            content = stream.read(handoff.h.MAX_BYTES + 1)
        total += len(content)
        if (len(content) > handoff.h.MAX_BYTES or total > handoff.h.MAX_TOTAL_BYTES
                or hashlib.sha256(content).hexdigest() != artifact['sha256']):
            raise ContractError('ohlcv_artifact_changed_or_budget')
        # The capped snapshot is the bytes consumed by the planner. Reuse the
        # established descriptor clock checks without another unbounded read.
        observed, available, collected, expires = [timestamp(artifact[k]) for k in
                    ('observed_at', 'available_at', 'collected_at', 'expires_at')]
        if not observed <= available <= collected <= cutoff <= now < expires:
            raise ContractError('artifact_time_boundary')
        values[aid] = content
    memory = handoff.h.MemoryArtifacts(values)
    if inventory['schema'] == 'a2-a1-readiness-lookup-v1':
        from tools.run_a2_a1_readiness import lookup
        return lookup(inventory, memory, cutoff=cutoff.isoformat())
    return handoff.build_plan(inventory, memory, cutoff=cutoff.isoformat())


def _plan_tasks(state: dict, root: Path, contract: dict, now: datetime,
                code_sha: str, config_hash: str, *, model_policy=None) -> list[dict]:
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
    model_research = 'A5' in requests and portfolio_mode(requests['A5']) == 'MODEL_PORTFOLIO'
    model_genesis = False
    model_incumbents = None
    if model_research:
        try:
            artifact = requests['A5']['inputs']['portfolio_context']
            verify_artifact(root, artifact, cutoff, now)
            context = read_json(artifact_path(root, artifact['path']))
            schema_validate(context, 'system_state_schema.json', 'a5_portfolio_context')
            model_genesis = (context['model_state']['kind'] == 'GENESIS'
                             and timestamp(context['decision_time']) == cutoff)
            if context['model_state']['kind'] == 'INCUMBENTS':
                model_incumbents = verify_current_model_incumbents(context, root, cutoff, now,
                    policy=model_policy, code_sha=code_sha)
            elif context['model_state']['kind'] == 'PARENT_LINEAGE_ONLY':
                model_incumbents = verify_model_parent_lineage(context, root, cutoff, now,
                    policy=model_policy, code_sha=code_sha)
        except (OSError, ValueError, KeyError, TypeError):
            pass
    receipts = {r['agent']: r for r in state['completed_tasks']}
    mission_hash = mission_targets()['mission_contract_sha256']
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
        a5_mode = portfolio_mode(request) if agent == 'A5' else None
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
        context_reasons = state['context']['blockers']
        if model_research and agent in ('A2', 'A3', 'A4', 'A5'):
            context_reasons = [r for r in context_reasons if r not in account_only_blockers(state)]
            prior = state.get('source_status', {}).get('model_portfolio', {})
            if model_genesis and prior.get('status') == 'UNKNOWN' and prior.get('reason') == 'source_missing':
                context_reasons = [r for r in context_reasons if r != 'model_portfolio:source_missing']
            if model_incumbents is not None:
                for section in ('source_status', 'books'):
                    prior = state.get(section, {}).get('model_portfolio', {})
                    if (prior.get('status') in ('UNKNOWN', 'BLOCKED') and prior.get('reason') in
                            ('source_missing', 'accepted_domain_receipt_verifier_not_bound')):
                        context_reasons = [r for r in context_reasons
                                           if r != 'model_portfolio:' + prior['reason']]
        if context_reasons and agent not in ('A1', 'A6'):
            reasons.append('CONTEXT_BLOCKED')
        if state['context']['current_status_freshness'] != 'VERIFIED' and agent not in ('A1', 'A6'):
            reasons.append('CURRENT_STATUS_NOT_VERIFIED')
        if a5_mode == 'ACCOUNT_REBALANCE' and any(state['context'][k] != 'VERIFIED' for k in ('actual_book', 'approved_target', 'thesis')):
            reasons.append('PORTFOLIO_CONTEXT_NOT_VERIFIED')
        parameters = dict(request['parameters'])
        a5_reviewed = {}
        if 'a5_preparation' in parameters:
            raise ContractError('reserved_a5_preparation_parameter')
        if agent == 'A5':
            try:
                context = read_json(artifact_path(root, request['inputs']['portfolio_context']['path']))
                if 'portfolio_mode' in context and context['portfolio_mode'] != a5_mode:
                    raise ContractError('a5_context_mode_mismatch')
            except (OSError, ValueError, KeyError, TypeError):
                reasons.append('A5_MODEL_CONTEXT_NOT_VERIFIED' if a5_mode == 'MODEL_PORTFOLIO'
                               else 'A5_CONTEXT_MODE_NOT_VERIFIED')
        ohlcv = None
        if 'a2_a1_ohlcv' in parameters:
            raise ContractError('reserved_ohlcv_parameter')
        if not reasons:
            ohlcv = ohlcv_parameters(request, root, cutoff, now)
            if ohlcv is not None:
                parameters['a2_a1_ohlcv'] = ohlcv
                if any(row['status'] == 'BLOCKED' for row in ohlcv['coverage_results']):
                    reasons.append('OHLCV_INPUT_PROOF_REQUIRED')
                if ohlcv.get('event_connection') == 'EVENT_INPUT_MISSING':
                    reasons.append('READINESS_EVENT_INPUT_MISSING')
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
        if a5_mode == 'MODEL_PORTFOLIO' and not reasons:
            try:
                parameters['a5_preparation'], a5_reviewed = a5_model_preparation(request, root, cutoff, now,
                    model_policy=model_policy, code_sha=code_sha)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                reasons.append('A5_MODEL_CONTEXT_NOT_VERIFIED')
                reason = str(exc) if re.fullmatch(r'a5_[a-z_]+', str(exc)) else type(exc).__name__
                parameters['a5_preparation'] = dict(preparation_scope='A0_TASK_PREPARATION_ONLY',
                    preparation_status='BLOCKED', reason=reason, economic_input_admission='BLOCKED',
                    current_a3_review_admitted=False, dispatch_allowed=False)
        if 'A6' in spec['dependencies'] and 'A6' in completed:
            report = qa_reports['A6']
            if report['verdict'] != 'PASS':
                reasons.append('QA_NOT_PASS')
            for role, artifact in request['inputs'].items():
                if role != 'qa_report' and report['reviewed_artifacts'].get(role) != artifact:
                    reasons.append('QA_INPUT_NOT_REVIEWED:' + role)
            for role, artifact in a5_reviewed.items():
                if report['reviewed_artifacts'].get(role) != artifact:
                    reasons.append('QA_INPUT_NOT_REVIEWED:' + role)
        identity = {'input_hash': digest({'inputs': request['inputs'],
                    'dependencies': receipt_dependencies(dependencies),
                    'context': state['context'], 'g0': state['g0'], 'master_sha': state['master_sha'],
                    'mission_contract_sha256': mission_hash,
                    'system_state_identity': state.get('dependency_identity')}),
                    'code_sha': code_sha, 'config_hash': config_hash,
                    'mission_contract_sha256': mission_hash,
                    'model': request['model'], 'parameters': parameters}
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
                    if (timestamp(artifact['available_at']) <= causal_ready
                            or timestamp(artifact['collected_at']) >= timestamp(receipt['created_at'])):
                        raise ContractError('completion_output_time_boundary')
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
                  'review_scope': ({'repository': state['repository'],
                                    'pr_number': state['review_pr_number']}
                                   if state.get('review_pr_number') is not None else None),
                  'dispatch_eligible': agent in ('A1', 'A2', 'A4', 'A6') and status == 'READY'
                      and spec['mode'] in ('READ_ONLY', 'PROPOSAL_ONLY') and ohlcv is None and agent != 'A5'}
        schema_validate(packet, 'task_packet_schema.json')
        tasks[agent] = packet
        visiting.remove(agent)
        return packet
    for agent in sorted(requests):
        plan(agent)
    return list(tasks.values())



def build_tasks(state: dict, root: Path, contract: dict, now: datetime,
                code_sha: str, config_hash: str, *, canonical_inputs=None,
                evidence_root=None, model_policy=None,
                expected_model_policy_sha256=None) -> list[dict]:
    # The public consumer cannot reuse a self-declared or self-pinned old state.
    from tools.materialize_system_state import verify_state
    if canonical_inputs is None or evidence_root is None:
        raise ContractError('current_canonical_inputs_required')
    verify_state(state, canonical_inputs, evidence_root, now, code_sha)
    if model_policy is not None or expected_model_policy_sha256 is not None:
        from research.multi_asset_v1.contracts import digest as policy_digest
        model_policy = copy.deepcopy(model_policy)
        if (type(model_policy) is not dict or type(expected_model_policy_sha256) is not str
                or re.fullmatch('[0-9a-f]{64}', expected_model_policy_sha256) is None
                or policy_digest(model_policy) != expected_model_policy_sha256):
            raise ContractError('model_policy_review_pin_mismatch')
    return _plan_tasks(state, root, contract, now, code_sha, config_hash,model_policy=model_policy)


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
        inputs_path = getattr(args, 'canonical_inputs', None)
        evidence_root = getattr(args, 'evidence_root', None)
        policy_path = getattr(args, 'model_policy', None)
        expected_policy = getattr(args, 'expected_model_policy_sha256', None)
        model_policy = model_policy_digest = None
        if policy_path is not None or expected_policy is not None:
            from research.multi_asset_v1.contracts import digest as policy_digest
            if (not policy_path or type(expected_policy) is not str or
                    re.fullmatch('[0-9a-f]{64}', expected_policy) is None):
                raise ContractError('model_policy_external_hash_required')
            path = repo_path(policy_path)
            if not path.is_file() or path.is_symlink() or path.stat().st_size > 4*1024*1024:
                raise ContractError('model_policy_file_bounds')
            raw = path.read_bytes()
            if digest_bytes(raw) != expected_policy:
                raise ContractError('model_policy_file_hash_mismatch')
            model_policy = json.loads(raw,object_pairs_hook=_review_pairs,parse_constant=_review_invalid)
            model_policy_digest = policy_digest(model_policy)
        tasks = build_tasks(state, root, contract, now, code_sha, config_hash,
                            canonical_inputs=read_json(repo_path(inputs_path)) if inputs_path else None,
                            evidence_root=repo_path(evidence_root) if evidence_root else None,
                            model_policy=model_policy,expected_model_policy_sha256=model_policy_digest)
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
    parser.add_argument('--canonical-inputs', help='Separately refreshed trusted source intake; never derive from saved state')
    parser.add_argument('--evidence-root', help='Read-only local materialization of canonical source bytes')
    parser.add_argument('--system-state', help='Explicit current v2 state; otherwise <latest-run>/control_plane/system_state.json')
    parser.add_argument('--model-policy', help='External reviewed MODEL policy; never extracted from task/context parameters')
    parser.add_argument('--expected-model-policy-sha256',help='External SHA256 of exact policy file bytes (not economic permission)')
    return parser.parse_args()


def main() -> int:
    result = run(parse_args())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    # The lazy materializer imports this canonical name. Preserve the same
    # ContractError class when this file is the CLI entrypoint.
    sys.modules['tools.run_agent_board'] = sys.modules[__name__]
    raise SystemExit(main())

#!/usr/bin/env python3
"""Offline manual pinning/preflight only; no worker, board or accepted-state writes."""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import run_agent_board as board
from tools.check_run287_do_not_repeat import evaluate_candidate

MANIFEST = 'research/control_plane/manual_playbooks_v1.json'
SCHEMA = 'research/control_plane/manual_task_packet_schema.json'
CATALOG = 'docs/pr_reuse_catalog.json'
DNR = 'docs/run287_do_not_repeat_registry.json'
PLAYBOOK_IDS = {'L0_RESUME_HANDOFF': 'A0', 'A1_SOURCE_ADMISSION_REFRESH': 'A1',
                'A6_INDEPENDENT_QA': 'A6'}
CLASSES = {'REUSE_NOW', 'SELECTIVE_PORT', 'HISTORICAL_LESSON', 'DO_NOT_REPEAT', 'SUPERSEDED'}
TIERS = ('T0_READ', 'T1_COMPUTE', 'T2_PREPARE')
REVIEW_REPOSITORY = 'wscha231/r1000-quant-engine'
ContractError = board.ContractError


def path_at(root: Path, value: str) -> Path:
    """Repository-relative exact paths, never traversal/globs/symlink aliases."""
    if not isinstance(value, str) or not value or any(c in value for c in '\\:*?[]\x00'):
        raise ContractError('invalid_path')
    parts = value.split('/')
    if PurePosixPath(value).is_absolute() or any(p in ('', '.', '..') for p in parts):
        raise ContractError('invalid_path')
    root = root.resolve()
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ContractError('symlink_path')
    return path


def allowed_file_at(root: Path, value: str) -> Path:
    """Validate one explicit allowed file; existing directories are never file scope."""
    path = path_at(root, value)
    if path.exists() and path.is_dir():
        raise ContractError('allowed_file_is_directory')
    return path


def semantic_version(value: str) -> tuple[int, int, int]:
    if (not isinstance(value, str) or re.fullmatch(
            r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', value) is None):
        raise ContractError('invalid_playbook_version')
    return tuple(int(part) for part in value.split('.'))


def payload_hash(value: dict, hash_field: str) -> str:
    return board.digest({key: item for key, item in value.items() if key != hash_field})


def validate_shape(value: dict, *, scope: bool = False, root: Path = ROOT) -> None:
    schema = board.read_json(path_at(root, SCHEMA))
    # Resolve this one existing contract locally; never retrieve a schema URL.
    authority = board.read_json(path_at(root, 'research/control_plane/task_packet_schema.json'))['properties']['authority']
    schema['properties']['authority'] = authority
    schema['$defs']['scope']['properties']['authority'] = authority
    if scope:
        schema = {'$schema': schema['$schema'], '$defs': schema['$defs'], '$ref': '#/$defs/scope'}
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    if errors:
        raise ContractError('manual_schema_invalid:' + '/'.join(map(str, errors[0].absolute_path)))


def load_playbook(playbook_id: str, root: Path = ROOT) -> tuple[dict, dict]:
    manifest = board.read_json(path_at(root, MANIFEST))
    if (manifest.get('schema_version') != 'manual-playbooks-v1'
            or set(manifest.get('current_versions', {})) != set(PLAYBOOK_IDS)):
        raise ContractError('manual_manifest_invalid')
    current = {}
    seen = set()
    rows_by_identity = {}
    for row in manifest.get('playbooks', []):
        identity = (row['playbook_id'], row['playbook_version'])
        semantic_version(row['playbook_version'])
        if identity in seen or row['playbook_id'] not in PLAYBOOK_IDS:
            raise ContractError('duplicate_or_unknown_playbook')
        seen.add(identity)
        rows_by_identity[identity] = row
        if row['playbook_sha256'] != payload_hash(row, 'playbook_sha256'):
            raise ContractError('playbook_hash_mismatch')
        if (row['owner'] != PLAYBOOK_IDS[row['playbook_id']]
                or board.digest(row['authority']) != board.digest(board.AUTHORITY)
                or row['authority_tier_max'] not in TIERS
                or row['mode'] != ('READ_ONLY' if row['owner'] == 'A6' else 'PROPOSAL_ONLY')):
            raise ContractError('playbook_authority')
        if not all(isinstance(row.get(k), dict) and row[k] for k in ('process', 'proof', 'learning')):
            raise ContractError('manual_layers_missing')
        if row['status'] == 'CURRENT':
            if row['playbook_id'] in current:
                raise ContractError('multiple_current_playbooks')
            current[row['playbook_id']] = row
    if set(current) != set(PLAYBOOK_IDS):
        raise ContractError('missing_current_playbook')
    for key, row in current.items():
        if row['playbook_version'] != manifest['current_versions'][key]:
            raise ContractError('stale_current_version')
        semantic_version(manifest['current_versions'][key])
        if row.get('supersedes') is not None:
            previous = (key, row['supersedes'])
            if previous not in seen or previous == (key, row['playbook_version']):
                raise ContractError('invalid_supersedes')
            predecessor = rows_by_identity[previous]
            if predecessor.get('status') != 'SUPERSEDED':
                raise ContractError('predecessor_not_superseded')
            if semantic_version(row['playbook_version']) <= semantic_version(row['supersedes']):
                raise ContractError('playbook_version_not_increasing')
    if playbook_id not in current:
        raise ContractError('unknown_playbook')
    return manifest, current[playbook_id]


def load_catalog(root: Path = ROOT) -> dict:
    value = board.read_json(path_at(root, CATALOG))
    if (value.get('schema_version') != 'pr-reuse-catalog-v1'
            or value.get('do_not_repeat_registry') != DNR
            or value.get('lessons_ledger') != 'docs/AGENT_SHARED_LESSONS_LEDGER.md'):
        raise ContractError('catalog_contract')
    entries = value.get('entries')
    if not isinstance(entries, list):
        raise ContractError('catalog_entries')
    seen = set()
    for row in entries:
        if not isinstance(row, dict):
            raise ContractError('catalog_entry_shape')
        entry_id, classification = row.get('entry_id'), row.get('classification')
        if not isinstance(entry_id, str) or not entry_id or entry_id in seen or classification not in CLASSES:
            raise ContractError('catalog_duplicate_or_classification')
        seen.add(entry_id)

        has_successor = row.get('superseded_by') is not None
        if (classification == 'SUPERSEDED') != has_successor:
            raise ContractError('catalog_supersedes_invariant')

        expiry = row.get('expiry')
        if expiry is not None:
            # Check the original clock/offset before datetime can normalize it.
            if (not isinstance(expiry, str) or re.fullmatch(
                    r'[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt ][0-9]{2}:[0-9]{2}:[0-9]{2}'
                    r'(?:[.,][0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])',
                    expiry) is None):
                raise ContractError('catalog_expiry_invalid')
            try:
                expiry_at = board.timestamp(expiry)
            except (ContractError, ValueError, TypeError, AttributeError):
                raise ContractError('catalog_expiry_invalid')
            if classification == 'REUSE_NOW' and expiry_at <= datetime.now(timezone.utc):
                raise ContractError('catalog_reuse_expired')

        source_kind = row.get('source_kind')
        metadata, heads = row.get('source_metadata'), row.get('source_heads')
        if (source_kind not in {'PR', 'ISSUE'} or not isinstance(metadata, dict)
                or not metadata or not isinstance(heads, dict)):
            raise ContractError('catalog_source_identity')
        for ref, item in metadata.items():
            if (not isinstance(ref, str) or re.fullmatch(r'#\d+', ref) is None
                    or not isinstance(item, dict) or item.get('kind') != source_kind):
                raise ContractError('catalog_source_identity')
        if source_kind == 'ISSUE':
            if heads:
                raise ContractError('catalog_issue_has_source_head')
        else:
            if set(heads) != set(metadata):
                raise ContractError('catalog_pr_head_identity')
            if any(not isinstance(sha, str) or re.fullmatch('[0-9a-f]{40}', sha) is None
                   for sha in heads.values()):
                raise ContractError('catalog_pr_head_identity')

        for field in ('current_equivalent', 'toolbox_refs'):
            paths = row.get(field)
            if (not isinstance(paths, list) or not all(isinstance(item, str) and item for item in paths)
                    or len(set(paths)) != len(paths)):
                raise ContractError('catalog_path_set')
            for item in paths:
                path_at(root, item)

        dependencies = row.get('dependency_hashes')
        if not isinstance(dependencies, dict):
            raise ContractError('catalog_dependency_hash')
        for path, sha in dependencies.items():
            path_at(root, path)
            if not isinstance(sha, str) or re.fullmatch('[0-9a-f]{64}', sha) is None:
                raise ContractError('catalog_dependency_hash')
        if classification == 'REUSE_NOW':
            consumed = set(row['current_equivalent']) | set(row['toolbox_refs'])
            if not consumed or not consumed.issubset(dependencies):
                raise ContractError('catalog_unpinned_reuse_path')

    for row in entries:
        if row.get('superseded_by') and (row['superseded_by'] not in seen or row['superseded_by'] == row['entry_id']):
            raise ContractError('catalog_invalid_supersedes')
    return value


def lookup_reuse(entry_id: str, root: Path = ROOT) -> dict:
    catalog = load_catalog(root)
    matches = [row for row in catalog['entries'] if row['entry_id'] == entry_id]
    if len(matches) != 1:
        raise ContractError('catalog_entry_unknown')
    row = matches[0]
    if row['classification'] == 'SUPERSEDED' or row.get('superseded_by') is not None:
        raise ContractError('catalog_superseded')
    registry = board.read_json(path_at(root, DNR))
    indexed = {item['id']: item for item in registry['entries']}
    blocked = []
    for ref in row['do_not_repeat_refs']:
        if ref not in indexed:
            raise ContractError('do_not_repeat_ref_missing')
        if indexed[ref].get('blocked_reuse') is True:
            blocked.append(ref)
    if row['classification'] == 'DO_NOT_REPEAT' and not blocked:
        raise ContractError('do_not_repeat_unbound')
    for path, sha in row['dependency_hashes'].items():
        if board.file_hash(path_at(root, path)) != sha:
            raise ContractError('catalog_dependency_changed:' + path)
    return {'entry': row, 'allowed': row['classification'] == 'REUSE_NOW' and not blocked,
            'blocked_registry_ids': blocked, 'economic_authority': False}


def required_dependencies(playbook_id: str, root: Path = ROOT) -> list[str]:
    manifest, playbook = load_playbook(playbook_id, root)
    return sorted(set(manifest['policy_refs'] + playbook['toolbox_refs'] + [
        MANIFEST, SCHEMA, CATALOG, DNR, 'docs/AGENT_SHARED_LESSONS_LEDGER.md',
        'tools/manual_foundation.py', 'tools/run_agent_board.py',
        'tools/check_run287_do_not_repeat.py',
        'research/control_plane/agent_contracts_v2.yaml',
        'research/control_plane/task_packet_schema.json']))


def validate_packet(packet: dict, scope: dict, *, expected_base: str,
                    expected_review_head: str | None = None, root: Path = ROOT) -> dict:
    """Scope/base come from the independently verified task, never from packet claims.

    Consistent JSON/hash proves pinning, not human approval or completed work.
    """
    validate_shape(packet, root=root)
    validate_shape(scope, scope=True, root=root)
    if not re.fullmatch('[0-9a-f]{40}', expected_base):
        raise ContractError('expected_base_invalid')
    if packet['base_sha'] != expected_base or scope['base_sha'] != expected_base:
        raise ContractError('wrong_base')
    _, playbook = load_playbook(packet['playbook_id'], root)
    is_a6 = playbook['owner'] == 'A6'
    if is_a6:
        if expected_review_head is None:
            raise ContractError('expected_review_head_required')
        if re.fullmatch('[0-9a-f]{40}', expected_review_head) is None:
            raise ContractError('expected_review_head_invalid')
        if packet['review_identity'] != scope['review_identity'] or packet['review_identity'] is None:
            raise ContractError('wrong_review_identity')
        if packet['review_identity']['head_sha'] != expected_review_head:
            raise ContractError('stale_review_head')
    elif packet['review_identity'] is not None or scope['review_identity'] is not None:
        raise ContractError('unexpected_review_identity')
    if (packet['playbook_version'] != playbook['playbook_version']
            or packet['playbook_sha256'] != playbook['playbook_sha256']):
        raise ContractError('stale_playbook')
    if packet['packet_sha256'] != payload_hash(packet, 'packet_sha256'):
        raise ContractError('packet_hash_mismatch')
    if packet['owner'] != playbook['owner'] or packet['owner'] != scope['owner']:
        raise ContractError('wrong_owner')
    if packet['mode'] != playbook['mode']:
        raise ContractError('wrong_mode')
    for authority in (packet['authority'], scope['authority']):
        if board.digest(authority) != board.digest(board.AUTHORITY):
            raise ContractError('authority_escalation')
    if TIERS.index(packet['authority_tier']) > min(TIERS.index(scope['authority_tier']), TIERS.index(playbook['authority_tier_max'])):
        raise ContractError('authority_tier_escalation')
    if packet['dependencies'] != scope['dependencies']:
        raise ContractError('wrong_dependency')
    if not set(required_dependencies(packet['playbook_id'], root)).issubset(packet['dependencies']):
        raise ContractError('missing_dependency')
    for path, sha in packet['dependencies'].items():
        if board.file_hash(path_at(root, path)) != sha:
            raise ContractError('dependency_bytes_changed:' + path)
    for path in scope['allowed_files'] + packet['allowed_files']:
        allowed_file_at(root, path)
    if not set(packet['allowed_files']).issubset(scope['allowed_files']):
        raise ContractError('file_scope_escalation')
    if packet['owner'] == 'A6' and packet['allowed_files']:
        raise ContractError('qa_source_write')
    if (packet['toolbox_refs'] != playbook['toolbox_refs']
            or packet['proof_set'] != playbook['proof_set']
            or not set(playbook['process']['stop_condition']).issubset(packet['stop_condition'])):
        raise ContractError('manual_contract_changed')
    reuse = [lookup_reuse(key, root) for key in packet['reuse_entries']]
    if any(not row['allowed'] for row in reuse):
        raise ContractError('catalog_reuse_not_allowed')
    if 'do_not_repeat_candidate' in packet:
        result = evaluate_candidate(board.read_json(path_at(root, DNR)), **packet['do_not_repeat_candidate'])
        if not result['allowed']:
            raise ContractError('BLOCKED_DO_NOT_REPEAT')
    return {'schema_version': 'manual-packet-preflight-v1', 'status': 'VALIDATED_PREPARE_ONLY',
            'task_key': packet['task_key'], 'packet_sha256': packet['packet_sha256'],
            'playbook_id': packet['playbook_id'], 'playbook_version': packet['playbook_version'],
            'playbook_sha256': packet['playbook_sha256'], 'base_sha': expected_base,
            'review_identity': copy.deepcopy(packet['review_identity']),
            'dependency_sha256': board.digest(packet['dependencies']),
            'proof_results': {key: 'NOT_RUN' for key in packet['proof_set']},
            'output_receipt': copy.deepcopy(packet['output_receipt']),
            'authority': copy.deepcopy(board.AUTHORITY), 'worker_invoked': False,
            'completed_task': False, 'economic_authority': False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', type=Path, required=True)
    parser.add_argument('--scope', type=Path, required=True, help='Independently verified task scope; not approval authentication')
    parser.add_argument('--expected-base', required=True, help='Independently verified live master SHA')
    parser.add_argument('--expected-review-head', help='Independently verified exact implementation PR HEAD for A6')
    args = parser.parse_args()
    try:
        result = validate_packet(board.read_json(args.packet), board.read_json(args.scope),
                                 expected_base=args.expected_base,
                                 expected_review_head=args.expected_review_head)
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({'status': 'BLOCKED_INPUT', 'reason': str(exc), 'worker_invoked': False}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

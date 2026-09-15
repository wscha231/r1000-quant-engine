#!/usr/bin/env python3
"""Research-only H2 13F manager skill and cohort proposal review.

Consumes reviewed, PIT-valid post-disclosure clone scorecards. It does not
estimate manager skill from AUM, current holdings size, seed priority, or fame;
it does not modify the active roster or emit stock orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.sec_13f_manager_policy import (
    COMPONENT_WEIGHTS,
    IntegrityError,
    Policy,
    digest,
    instant,
    propose_cohort,
    required_text,
    score_managers,
    source_influence,
)

INPUT_LIMIT = 64 * 1024 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise IntegrityError('duplicate_json_key')
        result[key] = value
    return result


def _invalid_constant(value):
    raise IntegrityError('nonfinite_json_number')


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode('utf-8')


def read_json(path: Path) -> tuple[dict, str]:
    with path.open('rb') as stream:
        raw = stream.read(INPUT_LIMIT + 1)
    if len(raw) > INPUT_LIMIT:
        raise IntegrityError('input_size_limit')
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object,
                           parse_constant=_invalid_constant)
    except (ValueError, UnicodeError) as exc:
        raise IntegrityError('invalid_json_input') from exc
    if not isinstance(value, dict):
        raise IntegrityError('json_object_required')
    return value, hashlib.sha256(raw).hexdigest()


def list_field(value: Mapping, key: str) -> list:
    data = value.get(key, [])
    if not isinstance(data, list):
        raise IntegrityError(f'list_required:{key}')
    return data


def code_hashes(names: tuple[str, ...]) -> dict:
    return {name: hashlib.sha256((REPO_ROOT / name).read_bytes()).hexdigest()
            for name in names}


def publish_new(output_dir: Path, files: Mapping[str, object], metadata: Mapping) -> dict:
    """Write a new immutable diagnostic directory; manifest is written last."""
    if not files or any(Path(name).name != name or name == 'manifest.json' for name in files):
        raise IntegrityError('flat_nonmanifest_output_names_required')
    output_dir = Path(output_dir)
    if output_dir.is_symlink() or any(p.is_symlink() for p in output_dir.parents):
        raise IntegrityError('symlink_output_path_forbidden')
    payloads = {name: json_bytes(value) for name, value in files.items()}
    manifest = dict(
        metadata,
        artifact_kind='RESEARCH_DIAGNOSTIC_NOT_ACCEPTED_STATE',
        research_only=True,
        active_roster_changed=False,
        portfolio_target_changed=False,
        automatic_trade_allowed=False,
        production_promotion_allowed=False,
        files={name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(payloads.items())},
    )
    payloads['manifest.json'] = json_bytes(manifest)
    if output_dir.exists():
        if not output_dir.is_dir() or {p.name for p in output_dir.iterdir()} != set(payloads):
            raise IntegrityError('existing_output_incomplete_or_different')
        for name, raw in payloads.items():
            path = output_dir / name
            if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
                raise IntegrityError('existing_output_hash_or_content_mismatch')
        return dict(manifest, publication='IDENTICAL_RERUN_VERIFIED')
    output_dir.mkdir(parents=True, exist_ok=False)
    for name in list(sorted(files)) + ['manifest.json']:
        with (output_dir / name).open('xb') as stream:
            stream.write(payloads[name])
            stream.flush()
            os.fsync(stream.fileno())
    return dict(manifest, publication='NEW_LOCAL_DIAGNOSTIC')


def evaluate(bundle: dict) -> dict:
    if bundle.get('schema_version') != '13f-manager-review-v1':
        raise IntegrityError('manager_schema_version_invalid')
    cutoff = required_text(bundle, 'decision_cutoff')
    instant(cutoff)
    policy_args = bundle.get('policy', {})
    if not isinstance(policy_args, dict):
        raise IntegrityError('policy_object_required')
    policy = Policy(**policy_args)
    scored = score_managers(
        list_field(bundle, 'records'),
        cutoff=cutoff,
        expected_manager_ids=list_field(bundle, 'expected_manager_ids'),
        policy=policy,
    )
    cohort = propose_cohort(
        scored,
        list_field(bundle, 'active_members'),
        list_field(bundle, 'quarterly_history'),
        list_field(bundle, 'decision_ledger'),
        review_kind=required_text(bundle, 'review_kind'),
        history_complete=bundle.get('history_complete') is True,
        decision_ledger_complete=bundle.get('decision_ledger_complete') is True,
        policy=policy,
    )
    active_ids = {
        r['economic_manager_id']
        for r in list_field(bundle, 'active_members')
        if r.get('data_valid') is True and r.get('critical_event') is not True
    }
    active_ranked = [r for r in scored['ranking'] if r['economic_manager_id'] in active_ids]
    influence = source_influence(active_ranked, policy) if scored['population_complete'] else {
        'weights': {},
        'unallocated_influence': 1.0,
        'status': 'BLOCKED_INCOMPLETE_EVIDENCE',
        'weights_are_broker_allocations': False,
        'research_only': True,
    }
    overall_status = (
        'BLOCKED_COHORT_REVIEW'
        if cohort['status'].startswith('BLOCKED_') and scored['status'] == 'READY_FOR_RESEARCH_REVIEW'
        else scored['status']
    )
    return {
        'status': overall_status,
        'fixture_kind': bundle.get('fixture_kind', 'REVIEWED_INPUT_REQUIRED'),
        'decision_cutoff': cutoff,
        'ranking': scored,
        'cohort_review': cohort,
        'existing_cohort_influence_diagnostic': influence,
        'policy': asdict(policy),
        'component_weights': COMPONENT_WEIGHTS,
        'skill_inputs_exclude_aum_and_seed_priority': True,
        'full_clone_backtest_executed': False,
        'active_roster_changed': False,
        'research_only': True,
        'automatic_trade_allowed': False,
    }


def run(input_path: Path, output_dir: Path) -> tuple[dict, int]:
    bundle, raw_hash = read_json(input_path)
    result = evaluate(bundle)
    manifest = publish_new(output_dir, {'manager_review.json': result}, {
        'decision_cutoff': result['decision_cutoff'],
        'status': result['status'],
        'input_sha256': raw_hash,
        'config_hash': digest({'policy': result['policy'], 'components': COMPONENT_WEIGHTS}),
        'code_sha256': code_hashes((
            'tools/sec_13f_manager_policy.py',
            'tools/run_sec_13f_manager_review.py',
        )),
    })
    blocked = (
        result['status'] != 'READY_FOR_RESEARCH_REVIEW'
        or result['cohort_review']['status'].startswith('BLOCKED_')
    )
    return manifest, 2 if blocked else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        manifest, code = run(args.input, args.output_dir)
        print(json.dumps({
            'status': manifest['status'],
            'publication': manifest['publication'],
            'research_only': True,
        }))
        return code
    except (IntegrityError, OSError, TypeError, KeyError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, IntegrityError) else type(exc).__name__
        print(json.dumps({
            'status': 'BLOCKED_INTEGRITY',
            'reason': reason,
            'accepted_publication': False,
        }), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

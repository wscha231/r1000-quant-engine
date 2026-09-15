#!/usr/bin/env python3
"""H1 offline evidence review. No collection, canonical write or trade authority.

Input envelopes must come from reviewed adapters. Their boolean attestations
are necessary contracts, not cryptographic proof of the reviewer's judgment.
The separate raw XML adapter verifies numeric transport when supplied bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.sec_13f_evidence_gate import (
    IntegrityError, build_snapshot, compare_snapshots, digest, instant,
    mature_outcomes, prior_quarter, required_text, resolve_reporting_filer,
)

AUDIT_BASE = 'bcb14c06613e34420ce7988e5bb1ac5547b22b57'
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
    """Create a new diagnostic directory; write manifest LAST, never overwrite.

    Identical reruns verify bytes. A changed or partially written existing
    directory fails closed. No cleanup of existing/user-owned files is attempted.
    A crash before the last write leaves an explicitly unaccepted directory.
    """
    if not files or any(Path(name).name != name or name == 'manifest.json' for name in files):
        raise IntegrityError('flat_nonmanifest_output_names_required')
    output_dir = Path(output_dir)
    if output_dir.is_symlink() or any(p.is_symlink() for p in output_dir.parents):
        raise IntegrityError('symlink_output_path_forbidden')
    payloads = {name: json_bytes(value) for name, value in files.items()}
    manifest = dict(metadata, artifact_kind='RESEARCH_DIAGNOSTIC_NOT_ACCEPTED_STATE',
                    research_only=True, active_roster_changed=False,
                    portfolio_target_changed=False, automatic_trade_allowed=False,
                    production_promotion_allowed=False,
                    files={name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(payloads.items())})
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
            stream.write(payloads[name]); stream.flush(); os.fsync(stream.fileno())
    return dict(manifest, publication='NEW_LOCAL_DIAGNOSTIC')


def evaluate(bundle: Mapping) -> dict:
    cutoff = required_text(bundle, 'decision_cutoff'); instant(cutoff)
    mode = required_text(bundle, 'availability_mode')
    if mode not in {'FORWARD', 'DISCLOSURE_REPLAY'}:
        raise IntegrityError('availability_mode_invalid')
    if bundle.get('schema_version') != '13f-evidence-review-v1':
        raise IntegrityError('evidence_schema_version_invalid')
    filings = list_field(bundle, 'filings')
    requests = list_field(bundle, 'snapshot_requests')
    if not requests:
        raise IntegrityError('snapshot_requests_required')
    snapshots, unique = [], set()
    for request in requests:
        mid, period = required_text(request, 'economic_manager_id'), required_text(request, 'report_period')
        if (mid, period) in unique:
            raise IntegrityError('duplicate_snapshot_request')
        unique.add((mid, period))
        snapshots.append(build_snapshot(filings, economic_manager_id=mid, report_period=period,
                                        cutoff=cutoff, mode=mode))
    lookup = {(s['economic_manager_id'], s['report_period']): s for s in snapshots}
    events, blocked_comparisons = [], []
    for current in snapshots:
        key = current['economic_manager_id'], prior_quarter(current['report_period'])
        if key not in lookup:
            continue
        try:
            changes = compare_snapshots(lookup[key], current)
            events.append({'economic_manager_id': current['economic_manager_id'],
                           'report_period': current['report_period'], 'changes': changes})
        except IntegrityError as exc:
            blocked_comparisons.append({'economic_manager_id': current['economic_manager_id'],
                                        'report_period': current['report_period'], 'reason': str(exc)})
    resolved_links = [resolve_reporting_filer(required_text(r, 'cik'), required_text(r, 'report_period'),
                                             list_field(bundle, 'reporting_links'), cutoff, mode)
                      for r in list_field(bundle, 'reporting_requests')]
    units_missing = [s['economic_manager_id'] + ':' + s['report_period'] for s in snapshots if not s['unit_verified']]
    return {'status': 'REVIEW_REQUIRED' if blocked_comparisons or units_missing else 'EVIDENCE_CHECKS_PASSED_NOT_INVESTMENT_APPROVAL',
            'fixture_kind': bundle.get('fixture_kind', 'USER_SUPPLIED_REVIEW_ENVELOPES'),
            'decision_cutoff': cutoff, 'availability_mode': mode,
            'snapshots': snapshots, 'quantity_events': events,
            'comparison_blocks': blocked_comparisons, 'unverified_units': units_missing,
            'reporting_links': resolved_links,
            'mature_outcomes': mature_outcomes(list_field(bundle, 'outcomes'), cutoff, mode),
            'research_only': True, 'automatic_trade_allowed': False}


def run(input_path: Path, output_dir: Path) -> tuple[dict, int]:
    bundle, raw_hash = read_json(input_path)
    result = evaluate(bundle)
    manifest = publish_new(output_dir, {'evidence_review.json': result}, {
        'audit_base_commit_not_candidate_commit': AUDIT_BASE,
        'decision_cutoff': result['decision_cutoff'], 'status': result['status'],
        'input_sha256': raw_hash,
        'config_hash': digest({'version': bundle['schema_version'], 'mode': bundle['availability_mode']}),
        'code_sha256': code_hashes(('tools/sec_13f_evidence_gate.py', 'tools/run_sec_13f_evidence_review.py')),
    })
    return manifest, 0 if result['status'].startswith('EVIDENCE_CHECKS_PASSED') else 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        manifest, code = run(args.input, args.output_dir)
        print(json.dumps({'status': manifest['status'], 'publication': manifest['publication'],
                          'research_only': True}))
        return code
    except (IntegrityError, OSError, TypeError, KeyError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, IntegrityError) else type(exc).__name__
        print(json.dumps({'status': 'BLOCKED_INTEGRITY', 'reason': reason,
                          'accepted_publication': False}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

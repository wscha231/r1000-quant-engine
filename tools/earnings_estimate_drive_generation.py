#!/usr/bin/env python3
"""Publish/restore a complete immutable earnings source generation on Drive.

Only the final head points to an accepted generation. Incomplete uploads remain
unreferenced; an ordinary restore can still read the prior complete generation.
This helper does not collect vendors, repair accepted state or dispatch jobs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.build_earnings_estimate_archive_manifest import (
    require_valid_snapshot_archive, require_verified_collector_state,
    require_verified_no_collection_plan, sha256_file,
)

ARCHIVE = 'data_pit/events/earnings_estimates'
SIGNALS = 'data_pit/events/earnings_revision_signals.parquet'
DAILY = 'outputs/earnings_estimates_daily'
# Generic data workflows copy data_pit/events in both directions. Keep the
# accepted authority outside that independently written compatibility tree.
GENERATIONS = 'research_state/earnings_estimate_generations'
HEAD = 'research_state/earnings_estimates_generation_head.json'
SCHEMA = 'earnings-estimate-drive-generation-v1'
HEX = re.compile(r'[0-9a-f]{64}')


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def files(directory):
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('generation_symlink_forbidden')
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = {
                'size_bytes': path.stat().st_size, 'sha256': sha256_file(path)}
    return result


def validate_payload(payload):
    archive, daily = payload / ARCHIVE, payload / DAILY
    history = require_valid_snapshot_archive(archive)
    if not history:
        raise ValueError('generation_empty_snapshot_archive')
    publication = json.loads((daily / 'archive_manifest.json').read_text())
    if (publication.get('schema_version') != 'earnings-estimate-archive-manifest-v1'
            or publication.get('publishable') is not True):
        raise ValueError('generation_nonpublishable_manifest')
    arguments = dict(summary_path=daily / 'summary.json',
        checkpoint_path=archive / 'collection_checkpoint.json',
        queue_path=daily / 'collection_queue.csv', signals_path=payload / SIGNALS)
    state = require_verified_collector_state(archive, **arguments)
    if state['state'] not in {'accepted', 'planned'}:
        raise ValueError('generation_requires_bound_collector_transaction')
    if type(publication.get('collection_required')) is not bool:
        raise ValueError('generation_invalid_collection_prerequisite')
    summary = json.loads((daily / 'summary.json').read_text())
    snapshot_name = Path(str(summary.get('snapshot_path') or '')).name
    bindings = {'snapshot': archive / snapshot_name, 'signals': payload / SIGNALS,
        'summary': daily / 'summary.json', 'collector_transaction': archive / 'collector_transaction.json',
        'collection_queue_checkpoint': archive / 'collection_checkpoint.json',
        'collection_queue_csv': daily / 'collection_queue.csv'}
    publication_files = publication.get('files')
    if not isinstance(publication_files, dict):
        raise ValueError('generation_manifest_component_binding_missing')
    for key, path in bindings.items():
        record = publication_files.get(key)
        if (not path.is_file() or not isinstance(record, dict)
                or record.get('sha256') != sha256_file(path)
                or type(record.get('size_bytes')) is not int
                or record['size_bytes'] != path.stat().st_size):
            raise ValueError('generation_manifest_component_binding_mismatch')
    if (publication['collection_required']
            and publication.get('run_id') != summary.get('collection_attempt_logical_id')):
        raise ValueError('generation_manifest_producer_mismatch')
    if publication['collection_required']:
        if state['state'] != 'accepted':
            raise ValueError('generation_unaccepted_collection_plan')
    else:
        if state['state'] != 'planned':
            raise ValueError('no_collection_requires_bound_plan')
        require_verified_no_collection_plan(archive, **arguments,
            universe_path=archive / 'collection_universe.csv',
            plan_summary=json.loads((daily / 'incremental_universe_summary.json').read_text()),
            run_id=publication['run_id'], expected_universe_count=993)


def prepare(root, stage):
    payload = stage / 'payload'
    payload.mkdir()
    for relative in (ARCHIVE, SIGNALS, DAILY):
        source, target = root / relative, payload / relative
        if source.is_symlink() or not source.exists():
            raise ValueError('generation_missing_or_symlink_component')
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            # Reject nested symlinks before copytree can follow one.
            if any(path.is_symlink() for path in source.rglob('*')):
                raise ValueError('generation_symlink_forbidden')
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    validate_payload(payload)
    body = {'schema_version': SCHEMA, 'files': files(payload)}
    generation = hashlib.sha256(encoded(body)).hexdigest()
    manifest = {**body, 'generation_id': generation, 'status': 'committed'}
    (stage / 'generation.json').write_bytes(encoded(manifest))
    head = {'schema_version': SCHEMA, 'status': 'committed',
            'generation_id': generation, 'manifest_sha256': sha256_file(stage / 'generation.json')}
    (stage / 'head.json').write_bytes(encoded(head))
    return generation


def verify(stage, head):
    if (not isinstance(head, dict) or head.get('schema_version') != SCHEMA
            or head.get('status') != 'committed'
            or not isinstance(head.get('generation_id'), str)
            or HEX.fullmatch(head['generation_id']) is None
            or not isinstance(head.get('manifest_sha256'), str)
            or HEX.fullmatch(head['manifest_sha256']) is None):
        raise ValueError('generation_invalid_head')
    path = stage / 'generation.json'
    if sha256_file(path) != head['manifest_sha256']:
        raise ValueError('generation_manifest_hash_mismatch')
    manifest = json.loads(path.read_text())
    if (manifest.get('schema_version') != SCHEMA or manifest.get('status') != 'committed'
            or manifest.get('generation_id') != head['generation_id']):
        raise ValueError('generation_manifest_identity_mismatch')
    records = manifest.get('files')
    if not isinstance(records, dict) or not records:
        raise ValueError('generation_empty_file_set')
    for relative, record in records.items():
        parts = PurePosixPath(relative)
        if (parts.is_absolute() or '..' in parts.parts or '\\' in relative
                or not (relative.startswith(ARCHIVE + '/') or relative.startswith(DAILY + '/')
                        or relative == SIGNALS)
                or not isinstance(record, dict) or type(record.get('size_bytes')) is not int
                or record['size_bytes'] < 0 or not isinstance(record.get('sha256'), str)
                or HEX.fullmatch(record['sha256']) is None):
            raise ValueError('generation_invalid_file_record')
    body = {'schema_version': SCHEMA, 'files': records}
    if hashlib.sha256(encoded(body)).hexdigest() != head['generation_id']:
        raise ValueError('generation_content_identity_mismatch')
    if files(stage / 'payload') != records:
        raise ValueError('generation_payload_file_set_or_hash_mismatch')
    validate_payload(stage / 'payload')


def transfer(*args, timeout=480, allow_missing=False):
    result = subprocess.run(['rclone', *map(str, args)], capture_output=True, timeout=timeout)
    if allow_missing and result.returncode in (3, 4):
        return None
    if result.returncode:
        # Do not print credential-bearing backend errors or remote config.
        raise RuntimeError(f'generation_transfer_failed:{args[0]}:exit{result.returncode}')
    return result.stdout.decode('utf-8')


def publish(root, base):
    with tempfile.TemporaryDirectory(prefix='earnings-publish-') as temporary:
        stage = Path(temporary)
        generation = prepare(root, stage)
        remote = base + GENERATIONS + '/' + generation + '/'
        transfer('copy', stage / 'payload', remote + 'payload', '--checksum', '--immutable')
        # Fresh remote bytes prove every file, including all historical vintages.
        readback = stage / 'readback'
        readback.mkdir()
        transfer('copy', remote + 'payload', readback / 'payload', '--checksum')
        shutil.copy2(stage / 'generation.json', readback / 'generation.json')
        head = json.loads((stage / 'head.json').read_text())
        verify(readback, head)
        # The generation manifest is its commit marker; publish it last.
        transfer('copyto', stage / 'generation.json', remote + 'generation.json', '--checksum', '--immutable')
        transfer('copyto', remote + 'generation.json', readback / 'generation.json', '--checksum')
        verify(readback, head)
        # Advance accepted authority only after complete generation readback.
        transfer('copyto', stage / 'head.json', base + HEAD, '--checksum')
        transfer('copyto', base + HEAD, readback / 'head.json', '--checksum')
        if (readback / 'head.json').read_bytes() != (stage / 'head.json').read_bytes():
            raise ValueError('generation_head_readback_mismatch')
        return generation


def restore(root, base):
    listing = transfer('lsf', base + str(PurePosixPath(HEAD).parent), '--files-only', '--max-depth', '1', allow_missing=True)
    if listing is None or Path(HEAD).name not in listing.splitlines():
        return False  # Strict existing legacy restore remains in the workflow.
    with tempfile.TemporaryDirectory(prefix='earnings-restore-') as temporary:
        stage = Path(temporary)
        transfer('copyto', base + HEAD, stage / 'head.json', '--checksum')
        head = json.loads((stage / 'head.json').read_text())
        generation = head.get('generation_id')
        if not isinstance(generation, str) or HEX.fullmatch(generation) is None:
            raise ValueError('generation_invalid_head')
        remote = base + GENERATIONS + '/' + generation + '/'
        transfer('copyto', remote + 'generation.json', stage / 'generation.json', '--checksum')
        transfer('copy', remote + 'payload', stage / 'payload', '--checksum')
        verify(stage, head)
        # Replace only the three owned source components after full verification.
        # A local interruption blocks this step; retry rereads the same remote
        # generation rather than consuming mixed local cache components.
        for relative in (ARCHIVE, SIGNALS, DAILY):
            target = root / relative
            resolved = target.resolve()
            parents = [target, *list(target.parents)[:len(PurePosixPath(relative).parts)]]
            if (not resolved.is_relative_to(root.resolve()) or resolved == root.resolve()
                    or any(path.is_symlink() for path in parents)):
                raise ValueError('generation_unsafe_local_destination')
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            shutil.move(str(stage / 'payload' / relative), str(target))
        return generation


LEGACY_20261003 = {
    'run_id': 37100587799, 'artifact_id': 11266510471,
    'head_sha': '30915e05c1ffe3cecd2c46b229af20844e514f3d',
    'zip_bytes': 4478824,
    'zip_sha256': '314f3560b512bd5f8762d049a3781251d1ecb5099df155a3422dd3e201503a91',
    'snapshot_files': 63, 'queue_rows': 993, 'source_files': 70,
}


def prepare_legacy_handoff(archive_path, output_root):
    """Prepare one pinned legacy baseline in a new, unpublished local directory.

    Original snapshots, queue, checkpoint, signals and clocks remain unchanged.
    No collector marker is created. A separately scoped genuine forward
    collection must establish the new transaction through the existing writer.
    Normal current-state/publication guards remain unchanged and still refuse.
    """
    archive_path, output = Path(archive_path), Path(output_root)
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ValueError('legacy_archive_identity_mismatch')
    with archive_path.open('rb') as stream:
        raw_archive = stream.read(8 * 1024 * 1024 + 1)
    if (len(raw_archive) != LEGACY_20261003['zip_bytes'] or len(raw_archive) > 8 * 1024 * 1024
            or hashlib.sha256(raw_archive).hexdigest() != LEGACY_20261003['zip_sha256']):
        raise ValueError('legacy_archive_identity_mismatch')
    if (output.exists() or output.is_symlink()
            or archive_path.resolve().is_relative_to(output.resolve())):
        raise ValueError('legacy_output_must_be_new_and_separate')
    required = {
        ARCHIVE + '/collection_checkpoint.json', ARCHIVE + '/archive_index.jsonl',
        SIGNALS, DAILY + '/summary.json', DAILY + '/collection_queue.csv',
        DAILY + '/archive_manifest.json',
    }
    selected = {}
    with zipfile.ZipFile(io.BytesIO(raw_archive)) as source:
        members = source.infolist()
        names = [m.filename for m in members]
        if (len(names) != len(set(names)) or len(names) > 1000
                or sum(m.file_size for m in members) > 64 * 1024 * 1024):
            raise ValueError('legacy_archive_inventory')
        for member in members:
            name = member.filename
            if (PurePosixPath(name).is_absolute() or '\\' in name or ':' in name
                    or '..' in PurePosixPath(name).parts
                    or ((member.external_attr >> 16) & 0o170000) == 0o120000):
                raise ValueError('legacy_archive_member_path')
            if name.endswith('/collector_transaction.json'):
                raise ValueError('legacy_archive_already_has_transaction_marker')
            if member.is_dir():
                continue
            if name.startswith(ARCHIVE + '/') or name in required:
                if member.file_size > 2 * 1024 * 1024:
                    raise ValueError('legacy_source_member_budget')
                selected[name] = source.read(member)
        if source.testzip() is not None:
            raise ValueError('legacy_archive_crc')
    if (not required <= set(selected) or len(selected) != LEGACY_20261003['source_files']
            or sum(map(len, selected.values())) > 16 * 1024 * 1024):
        raise ValueError('legacy_source_inventory')
    summary = json.loads(selected[DAILY + '/summary.json'])
    if summary.get('transaction_commit') or summary.get('legacy_handoff'):
        raise ValueError('legacy_summary_is_not_markerless_baseline')
    snapshot = PurePosixPath(str(summary.get('snapshot_path', '')).replace('\\', '/')).name
    if not re.fullmatch(r'estimates_[0-9]{8}\.parquet', snapshot) or ARCHIVE + '/' + snapshot not in selected:
        raise ValueError('legacy_summary_snapshot_missing')
    # Reserve a fresh owned candidate. Never merge an import into an existing tree.
    output.mkdir(parents=True)
    payload = output / 'payload'
    input_records = {}
    for name, raw in sorted(selected.items()):
        path = payload / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)
        input_records[name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}
    archive, daily = payload / ARCHIVE, payload / DAILY
    history = require_valid_snapshot_archive(archive)
    if len(history) != LEGACY_20261003['snapshot_files']:
        raise ValueError('legacy_archive_history_count')
    checkpoint, queue = archive / 'collection_checkpoint.json', daily / 'collection_queue.csv'
    from tools.build_earnings_estimate_archive_manifest import require_consistent_collection_acknowledgement
    require_consistent_collection_acknowledgement(checkpoint, queue)
    with queue.open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    tickers = [str(row.get('ticker') or '').strip().upper() for row in rows]
    if (len(rows) != LEGACY_20261003['queue_rows'] or not all(tickers)
            or len(set(tickers)) != len(tickers)):
        raise ValueError('legacy_queue_identity_or_count')
    try:
        require_verified_collector_state(archive, summary_path=daily / 'summary.json',
            checkpoint_path=checkpoint, queue_path=queue, signals_path=payload / SIGNALS)
    except ValueError as exc:
        if str(exc) != 'missing_collector_transaction_marker':
            raise
        current_refusal = str(exc)
    else:
        raise ValueError('legacy_baseline_unexpected_current_state')
    for name, record in input_records.items():
        if sha256_file(payload / name) != record['sha256']:
            raise ValueError('legacy_input_changed_during_prepare')
    result = {
        'schema': 'earnings-prepared-legacy-handoff-v1',
        'status': 'VERIFIED_LEGACY_BASELINE_PREPARED_NOT_CURRENT',
        'prepared_at': datetime.now(timezone.utc).isoformat(),
        'payload': str(payload), 'original_archive': str(archive_path), 'source_artifact': dict(LEGACY_20261003),
        'snapshot_files': len(history), 'queue_rows': len(rows), 'preserved_files': input_records,
        'original_status': summary.get('status'), 'current_state_refusal': current_refusal,
        'adapter_sha256': sha256_file(Path(__file__)), 'live_source_base_verified': False,
        'collector_transaction_created': False, 'forward_collection_executed': False,
        'provider_calls': 0, 'source_admitted': False, 'source_clock_renewed': False,
        'publisher_allowed': False, 'canonical_write_performed': False, 'research_only': True,
        'next_action': 'VERIFY_LIVE_SOURCE_BASE_AND_RUN_SCOPED_FORWARD_COLLECTION_SEPARATELY',
    }
    (output / 'prepared_handoff.json').write_bytes(encoded(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('publish', 'restore', 'prepare-legacy'))
    parser.add_argument('--base')
    parser.add_argument('--workspace', default=str(ROOT))
    parser.add_argument('--legacy-archive')
    parser.add_argument('--output-dir')
    args = parser.parse_args()
    if args.operation == 'prepare-legacy':
        if not args.legacy_archive or not args.output_dir or args.base:
            parser.error('prepare-legacy requires --legacy-archive and --output-dir only; no remote base')
        result = prepare_legacy_handoff(args.legacy_archive, args.output_dir)
        print(json.dumps(result, sort_keys=True))
        return 0
    if not args.base:
        parser.error('--base is required for publish and restore')
    root = Path(args.workspace).resolve()
    if args.operation == 'publish':
        print(json.dumps({'schema_version': SCHEMA, 'generation_id': publish(root, args.base),
            'status': 'PERSISTED_READBACK_VERIFIED', 'research_only': True}))
        return 0
    restored = restore(root, args.base)
    if restored:
        print(json.dumps({'schema_version': SCHEMA, 'generation_id': restored,
            'status': 'RESTORED_READBACK_VERIFIED', 'research_only': True}))
    # Exit10 is the sole legacy fallback signal, not a transfer failure.
    return 0 if restored else 10


if __name__ == '__main__':
    raise SystemExit(main())

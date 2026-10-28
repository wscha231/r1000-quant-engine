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
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import time
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


def publish(root, base, *, before_head=None):
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
        if before_head is not None:
            before_head()
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


def verify_legacy_handoff(receipt_path, *, snapshot_dir, summary_path, signals_path,
                          checkpoint_path, queue_path):
    """Bind one new local candidate to the pinned original, never a live base.

    Reuse preparation's positive whole-archive validation in disposable storage.
    A consumed, changed or relocated candidate cannot reuse this entry proof.
    Only the existing collector may create its genuine next transaction.
    """
    receipt_path = Path(receipt_path)
    if (receipt_path.is_symlink() or not receipt_path.is_file()
            or receipt_path.stat().st_size > 256 * 1024):
        raise ValueError('legacy_prepared_receipt_required')
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    payload = receipt_path.parent / 'payload'
    expected_paths = {
        'snapshot': payload / ARCHIVE, 'summary': payload / DAILY / 'summary.json',
        'signals': payload / SIGNALS, 'checkpoint': payload / ARCHIVE / 'collection_checkpoint.json',
        'queue': payload / DAILY / 'collection_queue.csv',
    }
    supplied = dict(snapshot=snapshot_dir, summary=summary_path, signals=signals_path,
                    checkpoint=checkpoint_path, queue=queue_path)
    if (not isinstance(receipt, dict) or receipt_path.name != 'prepared_handoff.json'
            or payload.is_symlink() or payload.resolve().parent != receipt_path.parent.resolve()
            or receipt.get('schema') != 'earnings-prepared-legacy-handoff-v1'
            or receipt.get('status') != 'VERIFIED_LEGACY_BASELINE_PREPARED_NOT_CURRENT'
            or receipt.get('source_artifact') != LEGACY_20261003
            or receipt.get('adapter_sha256') != sha256_file(Path(__file__))
            or Path(str(receipt.get('payload', ''))).resolve() != payload.resolve()
            or any(Path(supplied[key]).resolve() != path.resolve() for key, path in expected_paths.items())):
        raise ValueError('legacy_prepared_binding_mismatch')
    with tempfile.TemporaryDirectory(prefix='earnings-legacy-verify-') as temp:
        expected = prepare_legacy_handoff(receipt.get('original_archive', ''), Path(temp) / 'checked')
    if (receipt.get('preserved_files') != expected['preserved_files']
            or files(payload) != expected['preserved_files']):
        raise ValueError('legacy_prepared_bytes_changed_or_consumed')
    original_summary = json.loads((payload / DAILY / 'summary.json').read_text(encoding='utf-8'))
    return {
        'schema': 'earnings-verified-legacy-forward-parent-v1',
        'prepared_receipt_sha256': hashlib.sha256(receipt_bytes).hexdigest(),
        'original_artifact': dict(LEGACY_20261003),
        'baseline_inventory_sha256': hashlib.sha256(encoded(expected['preserved_files'])).hexdigest(),
        'baseline_checkpoint_sha256': sha256_file(checkpoint_path),
        'baseline_queue_sha256': sha256_file(queue_path),
        'baseline_summary_sha256': sha256_file(summary_path),
        'baseline_status': original_summary.get('status'),
        'baseline_generated_at_utc': original_summary.get('generated_at_utc'),
        'baseline_is_current_transaction': False, 'live_source_base_verified': False,
    }


def preflight_legacy_base(base, archive_path, output_root, expected_archive_folder_id):
    """Read the configured Source only; never restore into a consumer or publish.

    The expected folder ID comes from a separately grounded Drive read, not
    from the connection being tested. Matching bytes do not grant collection.
    """
    output = Path(output_root)
    if (not isinstance(base, str) or re.fullmatch(r'gdrive:(?:[A-Za-z0-9_/-]+/)?', base) is None
            or '..' in PurePosixPath(base.split(':', 1)[1]).parts
            or re.fullmatch(r'[A-Za-z0-9_-]{10,150}', str(expected_archive_folder_id)) is None):
        raise ValueError('source_preflight_invalid_binding')
    if output.exists() or output.is_symlink():
        raise ValueError('source_preflight_output_must_be_new')
    output = output.resolve()  # An rclone destination must be an absolute local path.
    output.mkdir(parents=True)
    receipt = {
        'schema': 'earnings-source-readonly-preflight-v1', 'status': 'BLOCKED',
        'observed_at': datetime.now(timezone.utc).isoformat(), 'base': base,
        'expected_archive_folder_id': expected_archive_folder_id,
        'namespace_verified': False, 'generation_head_absence_verified': False,
        'legacy_bytes_verified': False, 'observation_is_atomic': False,
        'provider_calls': 0, 'provider_credentials_probed': False,
        'provider_rights_verified': None, 'collection_executed': False,
        'source_published': False, 'source_admitted': False,
        'paper_consumer_executed': False, 'paper_state_restored_or_mutated': False,
        'canonical_write_performed': False,
        'recovery_execution_authorized': False, 'research_only': True,
        'adapter_sha256': sha256_file(Path(__file__)),
        'execution': {key: os.environ.get(key) for key in (
            'GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')},
    }

    def listing(remote, *, directory=False):
        raw = transfer('lsjson', remote, '--max-depth', '1', '--no-modtime', '--no-mimetype',
                       *(() if directory else ('--stat',)))
        if len(raw.encode('utf-8')) > 1024 * 1024:
            raise ValueError('source_preflight_metadata_budget')
        value = json.loads(raw)
        if directory:
            if not isinstance(value, list) or len(value) > 1000:
                raise ValueError('source_preflight_invalid_listing')
        elif not isinstance(value, dict):
            raise ValueError('source_preflight_invalid_stat')
        return value

    def head_absent():
        value = transfer('lsf', base + str(PurePosixPath(HEAD).parent),
                         '--files-only', '--max-depth', '1', allow_missing=True)
        if value is not None and Path(HEAD).name in value.splitlines():
            raise ValueError('source_preflight_current_head_requires_normal_verification')

    try:
        expected = prepare_legacy_handoff(archive_path, output / 'expected')
        records = expected['preserved_files']
        parent = listing(base + str(PurePosixPath(ARCHIVE).parent), directory=True)
        folders = [row for row in parent if row.get('Name') == PurePosixPath(ARCHIVE).name]
        if (len(folders) != 1 or folders[0].get('IsDir') is not True
                or folders[0].get('ID') != expected_archive_folder_id):
            raise ValueError('source_preflight_namespace_mismatch')
        receipt['observed_archive_folder_id'] = folders[0]['ID']
        receipt['namespace_verified'] = True
        head_absent()
        archive_records = {name.removeprefix(ARCHIVE + '/'): record for name, record in records.items()
                           if name.startswith(ARCHIVE + '/')}

        def archive_inventory():
            inventory = listing(base + ARCHIVE, directory=True)
            names = [row.get('Path') for row in inventory]
            if (len(names) != len(set(names)) or set(names) != set(archive_records)
                    or any(row.get('IsDir') is not False
                           or type(row.get('Size')) is not int
                           or row['Size'] != archive_records[row['Path']]['size_bytes']
                           for row in inventory)):
                raise ValueError('source_preflight_archive_inventory_changed')
            return sorted((row['Path'], row.get('ID'), row['Size']) for row in inventory)

        before = archive_inventory()
        observed = output / 'observed'
        target = observed / ARCHIVE
        target.mkdir(parents=True)
        # The exact census and hard read budget precede a fresh remote-to-local copy.
        transfer('copy', base + ARCHIVE, target, '--checksum', '--max-depth', '1',
                 '--max-size', '2MiB', '--max-transfer', '16MiB', '--transfers', '1', '--checkers', '1')
        for name, record in records.items():
            if name.startswith(ARCHIVE + '/'):
                continue
            stat = listing(base + name)
            if (stat.get('IsDir') is not False or type(stat.get('Size')) is not int
                    or stat['Size'] != record['size_bytes']):
                raise ValueError('source_preflight_component_size_changed')
            target = observed / name
            target.parent.mkdir(parents=True, exist_ok=True)
            transfer('copyto', base + name, target, '--checksum', '--max-transfer', '2MiB')
        if files(observed) != records:
            raise ValueError('source_preflight_original_bytes_mismatch')
        if before != archive_inventory():
            raise ValueError('source_preflight_archive_changed_during_read')
        head_absent()
        summary = json.loads((observed / DAILY / 'summary.json').read_text(encoding='utf-8'))
        receipt.update(status='LEGACY_SOURCE_BYTES_VERIFIED_READ_ONLY',
            generation_head_absence_verified=True, legacy_bytes_verified=True,
            source_files=len(records), snapshot_files=expected['snapshot_files'], queue_rows=expected['queue_rows'],
            source_inventory_sha256=hashlib.sha256(encoded(records)).hexdigest(),
            original_artifact=dict(LEGACY_20261003), files=records,
            original_status=summary.get('status'), original_generated_at_utc=summary.get('generated_at_utc'),
            next_action='VERIFY_PROVIDER_RIGHTS_BUDGET_AND_EXACT_FORWARD_ATTEMPT_SEPARATELY')
    except Exception as exc:
        reason = str(exc)
        receipt['reason'] = reason if re.fullmatch(r'[A-Za-z0-9_:.-]{1,160}', reason) else type(exc).__name__
    receipt['completed_at'] = datetime.now(timezone.utc).isoformat()
    (output / 'source_preflight.json').write_bytes(encoded(receipt))
    return receipt


FORWARD_SCHEMA = 'earnings-source-bounded-forward-contract-v1'
FORWARD_INVENTORY = '997d8b2881ca3eeb495fa3a961d59507ac28022d8f801c5e630d686ca6bc5db5'
FORWARD_CODE = ('.github/workflows/earnings_estimates_daily.yml',
    'tools/earnings_estimate_drive_generation.py',
    'tools/collect_earnings_estimates_finnhub.py',
    'tools/build_earnings_estimate_archive_manifest.py')
FORWARD_CEILINGS = dict(provider_gets=1, provider_response_bytes=2*1024*1024,
    drive_processes=64, transfer_reservation_bytes=128*1024*1024, active_seconds=600)


def forward_now():
    return datetime.now(timezone.utc)


def forward_contract(path, expected_sha256):
    """Validate fixed execution information; a hash is not execution authority."""
    path = Path(path)
    if (not isinstance(expected_sha256, str) or HEX.fullmatch(expected_sha256) is None
            or path.is_symlink() or not path.is_file() or path.stat().st_size > 32768):
        raise ValueError('source_forward_execution_info_required')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('source_forward_contract_hash')
    value = json.loads(raw)
    fields = {'schema','task_key','repository','head_sha','issued_at','expires_at','tickers',
        'provider','credential_name','account_reference','purpose','entitlement_reference',
        'budget_reference','expected_archive_folder_id','expected_inventory_sha256',
        'expected_head','code_pins','budget'}
    if (not isinstance(value, dict) or set(value) != fields or value['schema'] != FORWARD_SCHEMA
            or value['repository'] != 'wscha231/r1000-quant-engine' or value['tickers'] != ['MU']
            or value['provider'] != 'fmp' or value['credential_name'] not in ('FMP_API_KEY','FMP_API_KEY2')
            or value['purpose'] != 'PRIVATE_NONCOMMERCIAL_RESEARCH' or value['expected_head'] is not None
            or value['expected_inventory_sha256'] != FORWARD_INVENTORY
            or re.fullmatch(r'[A-Za-z0-9_-]{10,150}', str(value['expected_archive_folder_id'])) is None):
        raise ValueError('source_forward_contract_scope')
    for key in ('task_key','account_reference','entitlement_reference','budget_reference'):
        if not isinstance(value[key], str) or not 1 <= len(value[key]) <= 300:
            raise ValueError('source_forward_contract_reference')
    try:
        issued = datetime.fromisoformat(value['issued_at'].replace('Z','+00:00'))
        expires = datetime.fromisoformat(value['expires_at'].replace('Z','+00:00'))
        now = forward_now()
        if (issued.utcoffset() != timezone.utc.utcoffset(None)
                or expires.utcoffset() != timezone.utc.utcoffset(None)
                or not issued <= now < expires or not 0 < (expires-issued).total_seconds() <= 86400):
            raise ValueError('source_forward_contract_clock')
    except (TypeError, AttributeError, OverflowError):
        raise ValueError('source_forward_contract_clock') from None
    budget = value['budget']
    if (not isinstance(budget,dict) or set(budget) != set(FORWARD_CEILINGS)
            or any(type(budget[k]) is not int or not 0 < budget[k] <= cap
                   for k,cap in FORWARD_CEILINGS.items())):
        raise ValueError('source_forward_explicit_budget_required')
    context = {k:os.environ.get(k,'') for k in ('GITHUB_REPOSITORY','GITHUB_SHA','GITHUB_REF',
        'GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT')}
    if (context['GITHUB_REPOSITORY'] != value['repository'] or context['GITHUB_REF'] != 'refs/heads/master'
            or re.fullmatch(r'[a-f0-9]{40}', str(value['head_sha'])) is None
            or context['GITHUB_SHA'] != value['head_sha'] or not context['GITHUB_RUN_ID'].isdigit()
            or context['GITHUB_RUN_ATTEMPT'] != '1'
            or os.environ.get('FMP_KEY_NAME') != value['credential_name']):
        raise ValueError('source_forward_execution_binding')
    pins = value['code_pins']
    if (not isinstance(pins,dict) or set(pins) != set(FORWARD_CODE)
            or any(pins[p] != sha256_file(ROOT/p) for p in FORWARD_CODE)):
        raise ValueError('source_forward_code_pins')
    return value, context


class ForwardBudget:
    """Finite attempt reservations, not a claim to measure backend HTTP calls."""
    def __init__(self, contract, output):
        self.contract,self.output = contract,output
        self.started = time.monotonic()
        self.usage = dict(provider_gets=0, provider_response_bytes=0, drive_processes=0,
            transfer_reservation_bytes=0, drive_http_requests=None, head_write_attempted=False)

    def save(self):
        target=self.output/'attempt_meter.json'
        with target.open('wb') as stream:
            stream.write(encoded(self.usage)); stream.flush(); os.fsync(stream.fileno())

    def remaining(self):
        value=min(self.contract['budget']['active_seconds']-(time.monotonic()-self.started),
            (datetime.fromisoformat(self.contract['expires_at'].replace('Z','+00:00'))-forward_now()).total_seconds())
        if value <= 0:
            raise ValueError('source_forward_deadline')
        return value

    def check(self):
        self.remaining()

    def reserve(self, key, amount):
        self.check()
        if self.usage[key]+amount > self.contract['budget'][key]:
            raise ValueError('source_forward_budget_'+key)
        self.usage[key]+=amount; self.save()

    def transfer(self, original, *args, **kwargs):
        self.check()
        verb=str(args[0]); remote_indexes={'copy':(1,2),'copyto':(1,2),'lsf':(1,), 'lsjson':(1,)}
        if verb not in remote_indexes:
            raise ValueError('source_forward_transfer_scope')
        # Reserve the existing hard download cap; failed/uncertain transfers keep it.
        bound=1024*1024
        if verb in ('copy','copyto'):
            source=Path(args[1])
            if not str(args[1]).startswith('gdrive:'):
                records=files(source) if source.is_dir() else {'file':{'size_bytes':source.stat().st_size}}
                bound=sum(r['size_bytes'] for r in records.values())
            elif '--max-transfer' in args:
                cap=str(args[args.index('--max-transfer')+1])
                if cap not in ('2MiB','16MiB'):
                    raise ValueError('source_forward_transfer_cap')
                bound=int(cap[:-3])*1024*1024
            else:
                # Publication readback is bounded by its already prepared payload.
                bound=self.publication_bytes
            if verb=='copyto' and str(args[2]).endswith(HEAD):
                self.usage['head_write_attempted']=True
        self.reserve('drive_processes',1)
        self.reserve('transfer_reservation_bytes',max(1,bound))
        kwargs['timeout']=min(kwargs.get('timeout',480),self.remaining())
        if verb in ('copy','copyto'):
            if '--max-transfer' not in args:
                args=(*args,'--max-transfer',str(max(1,bound))+'B')
            if '--cutoff-mode' not in args:
                args=(*args,'--cutoff-mode','HARD')
        result=original(*args,**kwargs)
        self.check()
        return result


def bounded_forward_legacy(base, archive_path, output_root, contract_path, expected_sha256):
    """One opt-in MU/FMP forward attempt through the unchanged collector."""
    from tools import collect_earnings_estimates_finnhub as collector
    from tools import build_earnings_estimate_archive_manifest as manifest
    from urllib.parse import urlsplit, parse_qs
    import contextlib
    contract,context=forward_contract(contract_path,expected_sha256)
    output=Path(output_root)
    if output.exists() or output.is_symlink():
        raise ValueError('source_forward_output_must_be_new')
    if not os.environ.get(contract['credential_name']):
        raise ValueError('source_forward_named_credential_missing')
    output=output.resolve(); output.mkdir(parents=True)
    meter=ForwardBudget(contract,output); meter.save()
    receipt=dict(schema='earnings-source-bounded-forward-result-v1',status='BLOCKED',
        contract_sha256=expected_sha256,execution=context,collection_executed=False,
        publication_attempted=False,source_published=False,source_admitted=False,
        pit_admitted=False,paper_consumer_executed=False,canonical_research_admission=False)
    original_transfer,original_session,original_argv=transfer,collector.requests.Session,sys.argv

    class BoundedSession(original_session):
        def send(self, request, **kwargs):
            parsed=urlsplit(request.url); query=parse_qs(parsed.query)
            if (request.method!='GET' or parsed.scheme!='https' or parsed.netloc!='financialmodelingprep.com'
                    or parsed.path!='/stable/analyst-estimates' or set(query) != {'symbol','period','page','limit','apikey'}
                    or query['symbol'] != ['MU'] or query['period'] != ['annual']
                    or query['page'] != ['0'] or query['limit'] != ['10']
                    or query['apikey'] != [os.environ[contract['credential_name']]]):
                raise ValueError('source_forward_provider_scope')
            meter.reserve('provider_gets',1)
            kwargs.update(allow_redirects=False,stream=True,timeout=min(20,meter.remaining()))
            response=super().send(request,**kwargs)
            try:
                if not 200 <= response.status_code < 300:
                    raise ValueError('source_forward_provider_http_failure')
                body=bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    meter.reserve('provider_response_bytes',len(chunk)); body.extend(chunk)
                response._content=bytes(body); response._content_consumed=True
                meter.usage['provider_body_sha256']=hashlib.sha256(body).hexdigest(); meter.save()
                # Kept in the private local attempt only, never in public diagnostics.
                (output/'provider_response.private.json').write_bytes(body)
                return response
            finally:
                response.close()

    session=BoundedSession()
    globals()['transfer']=lambda *a,**k:meter.transfer(original_transfer,*a,**k)
    collector.requests.Session=lambda:session
    try:
        def parent_check(label):
            meter.check()
            result=preflight_legacy_base(base,archive_path,output/label,contract['expected_archive_folder_id'])
            if (not result.get('legacy_bytes_verified')
                    or result.get('source_inventory_sha256') != contract['expected_inventory_sha256']):
                raise ValueError('source_forward_parent_changed_or_unverified')
            return result
        parent_check('initial_parent')
        prepared=output/'initial_parent/expected'; payload=prepared/'payload'
        sys.argv=['collector','--tickers','MU','--vendor-order','fmp',
            '--fmp-key-name',contract['credential_name'],'--api-key','','--alphavantage-api-key','',
            '--fetch-date',forward_now().date().isoformat(),'--sleep-seconds','1.1','--max-errors','1',
            '--snapshot-dir',str(payload/ARCHIVE),'--signals-output',str(payload/SIGNALS),
            '--summary',str(payload/DAILY/'summary.json'),
            '--collection-checkpoint',str(payload/ARCHIVE/'collection_checkpoint.json'),
            '--collection-queue',str(payload/DAILY/'collection_queue.csv'),
            '--collection-attempt-id',context['GITHUB_RUN_ID'],'--plan-manual-collection',
            '--legacy-baseline-receipt',str(prepared/'prepared_handoff.json')]
        with (output/'collector.private.log').open('w',encoding='utf-8') as log, contextlib.redirect_stdout(log):
            receipt['collection_executed']=True
            code=collector.main()
        summary=json.loads((payload/DAILY/'summary.json').read_text())
        if (code != 0 or summary.get('status') != 'completed' or summary.get('error_count') != 0
                or summary.get('ticker_count_requested') != 1
                or summary.get('request_has_forward_estimate_rows') != 1 or meter.usage['provider_gets'] != 1):
            raise ValueError('source_forward_vendor_or_quality_failed')
        publication=manifest.build_manifest(snapshot_dir=str(payload/ARCHIVE),signals=str(payload/SIGNALS),
            summary=str(payload/DAILY/'summary.json'),collector_log=str(output/'collector.private.log'),
            manifest=str(payload/DAILY/'archive_manifest.json'),index=str(payload/DAILY/'archive_index.jsonl'),
            run_id=context['GITHUB_RUN_ID'],run_attempt='1',head_sha=context['GITHUB_SHA'],
            ref='refs/heads/master',workflow='Earnings Estimates Daily Archive',
            artifact_name='earnings-source-forward-'+context['GITHUB_RUN_ID'],
            queue_checkpoint=str(payload/ARCHIVE/'collection_checkpoint.json'),
            queue_csv=str(payload/DAILY/'collection_queue.csv'),
            queue_summary=str(payload/DAILY/'manual_plan_summary.json'),
            queue_report=str(payload/DAILY/'manual_plan_report.md'),
            queue_universe=str(payload/ARCHIVE/'collection_universe.csv'),collection_required=True)
        if publication.get('publishable') is not True:
            raise ValueError('source_forward_manifest_blocked')
        validate_payload(payload)
        meter.publication_bytes=sum(r['size_bytes'] for r in files(payload).values())+65536
        parent_check('before_publication')
        meter.check();receipt['publication_attempted']=True
        generation=publish(payload,base,before_head=lambda:parent_check('before_head'))
        receipt.update(status='SOURCE_PERSISTED_READBACK_VERIFIED_RESEARCH_ONLY',source_published=True,
            generation_id=generation,legacy_original_preserved=True)
    except Exception as exc:
        reason=str(exc)
        receipt['reason']=reason if re.fullmatch(r'[A-Za-z0-9_:.-]{1,160}',reason) else type(exc).__name__
        if meter.usage['head_write_attempted']:
            receipt['status']='PUBLICATION_OUTCOME_UNCERTAIN_STOP'
    finally:
        globals()['transfer']=original_transfer;collector.requests.Session=original_session;sys.argv=original_argv
        session.close();meter.save()
        receipt['meter']=dict(meter.usage);receipt['completed_at']=forward_now().isoformat()
        (output/'forward_result.json').write_bytes(encoded(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('publish', 'restore', 'prepare-legacy', 'preflight-legacy', 'check-forward-contract', 'forward-legacy'))
    parser.add_argument('--base')
    parser.add_argument('--workspace', default=str(ROOT))
    parser.add_argument('--legacy-archive')
    parser.add_argument('--output-dir')
    parser.add_argument('--expected-archive-folder-id')
    parser.add_argument('--recovery-contract')
    parser.add_argument('--contract-sha256')
    args = parser.parse_args()
    if args.operation in ('check-forward-contract', 'forward-legacy'):
        if not args.recovery_contract or not args.contract_sha256:
            parser.error('forward operations require fixed recovery contract and byte SHA256')
        if args.operation == 'check-forward-contract':
            forward_contract(args.recovery_contract, args.contract_sha256)
            print('SOURCE_FORWARD_CONTRACT_VERIFIED_NOT_EXECUTED')
            return 0
        if not all((args.base, args.legacy_archive, args.output_dir)):
            parser.error('forward-legacy requires base, pinned archive and new output')
        result = bounded_forward_legacy(args.base, args.legacy_archive, args.output_dir,
            args.recovery_contract, args.contract_sha256)
        print(json.dumps({key:result.get(key) for key in ('status','reason','source_published')}))
        return 0 if result['source_published'] else 2
    if args.operation == 'preflight-legacy':
        if not all((args.base, args.legacy_archive, args.output_dir, args.expected_archive_folder_id)):
            parser.error('preflight-legacy requires base, pinned archive, new output and independently known folder ID')
        result = preflight_legacy_base(args.base, args.legacy_archive, args.output_dir, args.expected_archive_folder_id)
        print(json.dumps({key: result.get(key) for key in ('status', 'reason', 'namespace_verified',
            'generation_head_absence_verified', 'source_files', 'legacy_bytes_verified')}))
        return 0 if result['legacy_bytes_verified'] else 2
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

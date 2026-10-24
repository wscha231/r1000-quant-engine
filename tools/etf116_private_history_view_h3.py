"""Private research-history archive/view, guarded by a real Actions probe.

Uses OwnerDrive and the existing atomic private-tab writer. No cron, original
research Sheet, approved-source namespace or mutable current pointer.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import io
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import tempfile
import zipfile
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import etf116_private_sheet_probe_h2 as probe
from tools.etf116_dated_history_h3 import (
    read_bytes, strict_json, encoded, raw_hash, verify_snapshot, verify_source_binding,
    verify_calculation_binding, require, MAX_BYTES)

MAX_ARCHIVE_BYTES = 16_000_000
MAX_PRIVATE_VIEWS = 16
MAX_PRIVATE_CELLS = 1_000_000
WORKFLOW = '.github/workflows/gdrive_smoke_test.yml'
JOB = 'etf116_private_sheet_probe'
GROUP = 'etf116-private-sheet-probe'


def _workflow_bytes(sha):
    root = Path(__file__).resolve().parents[1]
    head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    require(head == sha, 'PRIVATE_SERIALIZED_JOB_REQUIRED')
    committed = subprocess.check_output(['git', '-C', str(root), 'show', sha + ':' + WORKFLOW])
    require(committed == (root / WORKFLOW).read_bytes(), 'PRIVATE_SERIALIZED_JOB_REQUIRED')
    # All tracked validators/dependencies must match the declared code SHA.
    subprocess.check_call(['git', '-C', str(root), 'diff', '--quiet', 'HEAD', '--'],
                          stderr=subprocess.DEVNULL)
    return committed


def _serialized_job(env):
    require(env.get('ETF116_PRIVATE_METRICS_AUTHORIZED') == 'true', 'PRIVATE_VIEW_AUTHORIZATION_REQUIRED')
    binding = probe.actions_binding(env)
    ref = env.get('GITHUB_REF', '')
    require(re.fullmatch(r'refs/heads/[A-Za-z0-9_./-]+', ref)
            and env.get('GITHUB_WORKFLOW_REF') == probe.REPOSITORY + '/' + WORKFLOW + '@' + ref
            and env.get('GITHUB_WORKFLOW_SHA') == binding['GITHUB_SHA']
            and env.get('GITHUB_JOB') == JOB, 'PRIVATE_SERIALIZED_JOB_REQUIRED')
    import yaml
    contract = yaml.safe_load(_workflow_bytes(binding['GITHUB_SHA']))
    concurrency = contract.get('jobs', {}).get(JOB, {}).get('concurrency', {})
    require(concurrency.get('group') == GROUP and concurrency.get('cancel-in-progress') is False,
            'PRIVATE_SERIALIZED_JOB_REQUIRED')
    return binding


@contextmanager
def private_publish_lock(env):
    binding = _serialized_job(env)
    temp = Path(env.get('RUNNER_TEMP', ''))
    require(temp.is_absolute() and temp.is_dir() and not temp.is_symlink(), 'PRIVATE_RUNNER_LOCK')
    directory = os.open(temp, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open('.etf116-private-sheet.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
    finally:
        os.close(directory)
    with os.fdopen(fd, 'a') as lock:
        import stat
        require(stat.S_ISREG(os.fstat(lock.fileno()).st_mode), 'PRIVATE_RUNNER_LOCK')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('PRIVATE_PUBLISH_BUSY') from None
        yield binding


def private_view_capacity(drive, plan):
    probe._private(drive)
    base = 'https://sheets.googleapis.com/v4/spreadsheets/' + probe.PRIVATE_SHEET
    meta = probe._json(drive, base + '?fields=spreadsheetId,sheets(properties)')
    require(meta.get('spreadsheetId') == probe.PRIVATE_SHEET and isinstance(meta.get('sheets'), list),
            'PRIVATE_VIEW_CAPACITY_UNKNOWN')
    properties = [s.get('properties') for s in meta['sheets'] if isinstance(s, dict)]
    require(len(properties) == len(meta['sheets']) and all(isinstance(p, dict) for p in properties),
            'PRIVATE_VIEW_CAPACITY_UNKNOWN')
    matches = [p for p in properties if p.get('sheetId') == plan['sheet_id'] or p.get('title') == plan['title']]
    if matches:
        require(len(matches) == 1 and matches[0].get('sheetId') == plan['sheet_id']
                and matches[0].get('title') == plan['title'], 'PRIVATE_VIEW_COLLISION')
        probe.literal_private_tab(drive, plan['sheet_id'], plan['title'], plan['values'], existing_only=True)
        return True
    cells = 0
    for props in properties:
        grid = props.get('gridProperties', {})
        require(all(type(grid.get(k)) is int and grid[k] > 0 for k in ('rowCount', 'columnCount')),
                'PRIVATE_VIEW_CAPACITY_UNKNOWN')
        cells += grid['rowCount'] * grid['columnCount']
    views = sum(str(p.get('title', '')).startswith('ETF116_RESEARCH_') for p in properties)
    claims = sum(str(p.get('title', '')).startswith('ETF116_ARCHIVE_') for p in properties)
    added = len(plan['values']) * len(plan['values'][0]) + 18  # two immutable3×3 CREATE claims
    require(views < MAX_PRIVATE_VIEWS and claims + 2 <= 2 * MAX_PRIVATE_VIEWS
            and cells + added <= MAX_PRIVATE_CELLS, 'PRIVATE_VIEW_ROTATION_REQUIRED')
    return False

HEADERS = ['session', 'ticker', 'basis', 'daily_return', 'daily_status', 'months',
           'window_status', 'anchor_session', 'total_return', 'cagr', 'sharpe', 'sortino', 'mdd',
           'volatility', 'spy_excess_return', 'log_relative_rs_spy', 'rf_status',
           'benchmark_status', 'snapshot_sha256', 'research_status']


def text(value):
    return 'NULL' if value is None else json.dumps(value, allow_nan=False) if not isinstance(value, str) else value


def view_plan(snapshot, *, evaluation_time=None):
    verify_snapshot(snapshot, evaluation_time=evaluation_time)
    digest = snapshot['snapshot_sha256']
    title = 'ETF116_RESEARCH_' + snapshot['session'].replace('-', '') + '_' + digest[:12].upper()
    rows = [HEADERS]
    for ticker, result in sorted(snapshot['ticker_results'].items()):
        daily = result['daily_return']
        for months, window in sorted(result['horizons'].items(), key=lambda p: int(p[0])):
            risk = window.get('risk', {})
            values = [snapshot['session'], ticker, result['basis'],
                daily['total_return'] if daily else None, result['daily_return_status'], months,
                window['status'], window.get('anchor_session'), window.get('total_return'), window.get('cagr'),
                risk.get('sharpe'), risk.get('sortino'), window.get('matched_window_mdd'),
                risk.get('ann_volatility'), window.get('spy_excess_cumulative_return'),
                window.get('log_relative_rs_spy'), risk.get('risk_free_status'),
                window.get('benchmark_status'), digest,
                'RESEARCH_CANDIDATE_NO_AUTHORITY']
            rows.append([text(v) for v in values])
    require(len(rows) == 929, 'PRIVATE_VIEW_116_BY_8_REQUIRED')
    return {'schema': 'etf116-private-dated-view-plan-v1', 'session': snapshot['session'],
            'snapshot_sha256': digest, 'sheet_id': (int(digest[:8], 16) & 0x7fffffff) or 1,
            'title': title, 'values': rows, 'values_sha256': probe.digest(rows),
            'private_candidate_view_only': True, 'allowed_for_original_sheet': False,
            'automatic_refresh_enabled': False, 'economic_authority': False}


def verify_existing_probe(drive, receipt):
    """A caller-supplied success label alone is insufficient: GET actual marker."""
    require(isinstance(receipt, dict) and receipt.get('schema') == 'etf116-private-actions-sheet-probe-v1'
            and receipt.get('state') == 'CREATE_AND_READBACK_VERIFIED'
            and receipt.get('auth_mode') == 'EXISTING_OWNER_OAUTH'
            and receipt.get('principal_sha256') == probe.digest(drive.owner)
            and receipt.get('test_sheet_sha256') == probe.digest(probe.PRIVATE_SHEET)
            and receipt.get('private_test_only') is True
            and receipt.get('automatic_refresh_enabled') is False, 'PRIVATE_ACTIONS_PROOF_REQUIRED')
    binding = receipt.get('binding')
    require(isinstance(binding, dict), 'PRIVATE_ACTIONS_PROOF_REQUIRED')
    env = dict(binding, GITHUB_ACTIONS='true', GITHUB_EVENT_NAME='workflow_dispatch',
               ETF116_PRIVATE_PROBE_AUTHORIZED='true', ETF116_EXPECTED_CODE_SHA=binding.get('GITHUB_SHA'))
    checked = probe.actions_binding(env)
    sid, title, cell_range = probe.run_target(checked)
    expected = probe.marker(checked, drive.owner)
    require(receipt.get('sheet_id') == sid and receipt.get('range') == cell_range
            and receipt.get('values_sha256') == probe.digest(expected)
            and receipt.get('cell_count') == 27 and receipt.get('write_requests') == 1,
            'PRIVATE_ACTIONS_PROOF_REQUIRED')
    # Existing-only means missing/corrupted proof cannot itself cause any write.
    return probe.literal_private_tab(drive, sid, title, expected, existing_only=True)


def archive_object(drive, folder, raw, extension='.json', *, binding, allow_create=True):
    """Dedupe exact hash-name objects; ambiguous CREATE remains a manual blocker."""
    require(extension in ('.json', '.zip') and 0 < len(raw) <= MAX_ARCHIVE_BYTES,
            'PRIVATE_ARCHIVE_SIZE_OR_CODEC')
    require(isinstance(folder, str) and re.fullmatch(r'[A-Za-z0-9_-]{10,100}', folder)
            and drive.root_id == probe.PRIVATE_ROOT, 'PRIVATE_HISTORY_FOLDER')
    drive.check(folder, probe.PRIVATE_ROOT)
    digest = raw_hash(raw)
    query = {'q': "'" + folder + "' in parents and trashed=false and name='" + digest + extension + "'",
             'pageSize': 2, 'fields': 'files(id,name,mimeType),nextPageToken,incompleteSearch'}
    result = probe._json(drive, 'https://www.googleapis.com/drive/v3/files?' + urlencode(query))
    files = result.get('files')
    require(isinstance(files, list) and len(files) <= 1 and not result.get('nextPageToken')
            and result.get('incompleteSearch', False) is False, 'PRIVATE_ARCHIVE_AMBIGUOUS')
    if files:
        item = files[0]
        require(isinstance(item, dict) and item.get('name') == digest + extension
                and re.fullmatch(r'[A-Za-z0-9_-]+', item.get('id', '')), 'PRIVATE_ARCHIVE_METADATA')
        drive.check(item['id'], folder, folder=False)
        require(drive.read(item['id'], limit=len(raw) + 1) == raw, 'PRIVATE_ARCHIVE_READBACK')
        return {'file_id': item['id'], 'sha256': digest, 'bytes': len(raw), 'reused': True}
    require(allow_create, 'PRIVATE_ARCHIVE_MISSING_FOR_EXISTING_VIEW')
    # Drive names are not unique. A permanent atomic Sheet claim precedes CREATE;
    # an uncertain CREATE can only be reconciled by GET, never issued again.
    claim = {'archive_sha256': digest, 'extension': extension, 'purpose': 'ETF116_ARCHIVE'}
    sid = (int(probe.digest(claim)[:8], 16) & 0x7fffffff) or 1
    title = 'ETF116_ARCHIVE_' + digest[:32].upper()
    values = [['archive_sha256', digest, extension],
              ['run_binding', probe.digest(binding), 'CLAIM_BEFORE_CREATE'],
              ['state', 'RESERVED_CREATE_ONLY', 'MANUAL_RECONCILIATION_IF_UNKNOWN']]
    reservation = probe.literal_private_tab(drive, sid, title, values)
    require(reservation['write_requests'] == 1, 'PRIVATE_ARCHIVE_MANUAL_RECONCILIATION_REQUIRED')
    # Existing OwnerDrive performs private-owner checks and independent byte readback.
    receipt = drive.write(folder, raw, extension)
    require(receipt.get('sha256') == digest and receipt.get('bytes') == len(raw),
            'PRIVATE_ARCHIVE_RECEIPT')
    return dict(receipt, reused=False, claim_sheet_id=sid)


def source_archive_bytes(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_BYTES, 'PRIVATE_ARCHIVE_SIZE_OR_CODEC')
    # ZIP preserves the exact JSON bytes. Fixed metadata is a codec constant,
    # never an invented source/collection/PIT clock.
    out = io.BytesIO()
    info = zipfile.ZipInfo('candidate-input.json', date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(info, raw)
    payload = out.getvalue()
    require(0 < len(payload) <= MAX_ARCHIVE_BYTES, 'PRIVATE_ARCHIVE_SIZE_OR_CODEC')
    return payload


def publish_private(drive, snapshot, source_bytes, proof, folder, env, *, evaluation_time=None):
    evaluated = evaluation_time if evaluation_time is not None else datetime.now(timezone.utc)
    with private_publish_lock(env) as binding:
        return _publish_locked(drive, snapshot, source_bytes, proof, folder, binding, evaluated)


def _publish_locked(drive, snapshot, source_bytes, proof, folder, binding, evaluated):
    plan = view_plan(snapshot, evaluation_time=evaluated)
    verify_source_binding(snapshot, source_bytes, evaluation_time=evaluated)
    verify_calculation_binding(snapshot, source_bytes, evaluation_time=evaluated)
    source_zip = source_archive_bytes(source_bytes)
    snapshot_bytes = encoded(snapshot)
    require(len(snapshot_bytes) <= MAX_ARCHIVE_BYTES, 'PRIVATE_ARCHIVE_SIZE_OR_CODEC')
    verify_existing_probe(drive, proof)
    existing_view = private_view_capacity(drive, plan)
    source_receipt = dict(archive_object(drive, folder, source_zip, '.zip',
                          binding=binding, allow_create=not existing_view),
                          original_sha256=raw_hash(source_bytes), original_bytes=len(source_bytes),
                          codec='ZIP_DEFLATE_FIXED_METADATA', member='candidate-input.json')
    snapshot_receipt = archive_object(drive, folder, snapshot_bytes,
                                     binding=binding, allow_create=not existing_view)
    result = probe.literal_private_tab(drive, plan['sheet_id'], plan['title'], plan['values'],
                                       existing_only=existing_view)
    return {'schema': 'etf116-private-dated-view-receipt-v1', 'binding': binding,
            'evaluated_at_utc': evaluated.astimezone(timezone.utc).isoformat(),
            'state': 'IDENTICAL_PRIVATE_VIEW_READ_ONLY' if result['unchanged'] else 'PRIVATE_VIEW_READBACK_VERIFIED',
            'session': snapshot['session'], 'snapshot_sha256': snapshot['snapshot_sha256'],
            'source_archive': source_receipt, 'snapshot_archive': snapshot_receipt,
            'sheet': result, 'private_candidate_view_only': True, 'preview_view_limit': MAX_PRIVATE_VIEWS,
            'serialization': {'workflow': WORKFLOW, 'job': JOB, 'concurrency_group': GROUP,
                              'runner_lock': True, 'immutable_archive_claims': True},
            'source_admission': False, 'original_research_sheet_updated': False,
            'automatic_refresh_enabled': False, 'economic_authority': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--publish-private', action='store_true')
    parser.add_argument('--source-input')
    parser.add_argument('--probe-receipt')
    parser.add_argument('--private-history-folder')
    args = parser.parse_args()
    evaluated = datetime.now(timezone.utc)
    # Parse/validate local inputs before reserving output; no malformed-input tombstone.
    try:
        snapshot = strict_json(read_bytes(args.snapshot))
        plan = view_plan(snapshot, evaluation_time=evaluated)
        if args.publish_private:
            require(all((args.source_input, args.probe_receipt, args.private_history_folder)),
                    'PRIVATE_PUBLICATION_ARGUMENTS')
            source = read_bytes(args.source_input)
            proof = strict_json(read_bytes(args.probe_receipt))
    except (OSError, ValueError, RecursionError, KeyError, TypeError, AttributeError):
        print('BLOCKED_PRIVATE_HISTORY_INPUT')
        return 2
    # Reserve before any OAuth or remote action; retain a sanitized blocked receipt.
    with Path(args.output).open('x', encoding='utf-8') as out:
        try:
            if not args.publish_private:
                result = plan
            else:
                require(os.environ.get('ETF116_PRIVATE_METRICS_AUTHORIZED') == 'true',
                        'PRIVATE_VIEW_AUTHORIZATION_REQUIRED')
                probe.actions_binding(os.environ)
                _serialized_job(os.environ)
                probe.require(bool(os.environ.get('RCLONE_CONFIG_GDRIVE')), 'OWNER_OAUTH_CONFIG_REQUIRED')
                from tools.twelve_private_capture import OwnerDrive
                os.environ['MACRO_DRIVE_CONFIG'] = os.environ['RCLONE_CONFIG_GDRIVE']
                with tempfile.TemporaryDirectory(prefix='etf116-private-history-') as temp:
                    result = publish_private(OwnerDrive(probe.PRIVATE_ROOT, temp), snapshot,
                        source, proof, args.private_history_folder, os.environ, evaluation_time=evaluated)
        except Exception:
            # Never expose credential-bearing errors or retry/clean up uncertain POST.
            json.dump({'state': 'BLOCKED_PRIVATE_HISTORY_ACCESS',
                       'automatic_refresh_enabled': False}, out)
            print('BLOCKED_PRIVATE_HISTORY_ACCESS')
            return 2
        json.dump(result, out, sort_keys=True, allow_nan=False)
    print(json.dumps({'state': result.get('state', 'PRIVATE_PLAN_ONLY'),
                      'session': result['session'], 'automatic_refresh_enabled': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

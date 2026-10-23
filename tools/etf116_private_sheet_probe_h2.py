"""One-shot owner-OAuth probe of the fixed PRIVATE ETF116 Sheet, never a publisher."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
PRIVATE_ROOT = '1-_lMwtgQCS66eKlUmUZtMeCOGfsnHYo7'
PRIVATE_SHEET = '1y7WsMt5nzYKhNYByj16Fe7ekrwEJsMdYn2AQBHiwxZo'
TAB, TAB_ID = 'ETF116_CONNECTOR_PROBE', 116202610
REPOSITORY = 'wscha231/r1000-quant-engine'
SAFE = frozenset('ACTIONS_BINDING AUTHORIZATION_REQUIRED OWNER_OAUTH_CONFIG_REQUIRED '
                 'PRIVATE_METADATA PROBE_TAB PROBE_TAB_COLLISION PROBE_RESPONSE '
                 'PROBE_UPDATE PROBE_READBACK OWNER_OAUTH_ACCESS_BLOCKED INTERNAL_REFUSAL '
                 'ATOMIC_POST_OUTCOME_UNKNOWN'.split())


class ProbeRefused(ValueError):
    def __init__(self, code):
        super().__init__(code if code in SAFE else 'INTERNAL_REFUSAL')


def require(ok, code):
    if not ok:
        raise ProbeRefused(code)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def actions_binding(env):
    require(env.get('ETF116_PRIVATE_PROBE_AUTHORIZED') == 'true', 'AUTHORIZATION_REQUIRED')
    sha = env.get('GITHUB_SHA', '')
    require(env.get('GITHUB_ACTIONS') == 'true'
            and env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and env.get('GITHUB_REPOSITORY') == REPOSITORY
            and re.fullmatch(r'[0-9a-f]{40}', sha)
            and env.get('ETF116_EXPECTED_CODE_SHA') == sha
            and re.fullmatch(r'[1-9][0-9]{0,19}', env.get('GITHUB_RUN_ID', ''))
            and re.fullmatch(r'[1-9][0-9]{0,5}', env.get('GITHUB_RUN_ATTEMPT', '')),
            'ACTIONS_BINDING')
    return {k: env[k] for k in ('GITHUB_REPOSITORY', 'GITHUB_SHA',
                                'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')}


def marker(binding, owner):
    require(isinstance(owner, str) and bool(owner), 'PRIVATE_METADATA')
    first = [
        ['ETF116_ACTIONS_PRIVATE_PROBE_V1', 'RESEARCH_ONLY', 'NO_ACTIVATION'],
        ['repository', binding['GITHUB_REPOSITORY'], 'PRIVATE_COPY_ONLY'],
        ['run_id', binding['GITHUB_RUN_ID'], 'attempt:' + binding['GITHUB_RUN_ATTEMPT']],
        ['code_sha', binding['GITHUB_SHA'], 'FROZEN_PROBE_CODE'],
        ['principal_sha256', digest(owner), 'OWNER_OAUTH'],
        ['nonce', digest(binding), 'RUN_BOUND'],
    ]
    return first + [['payload_sha256', digest(first), 'RAW_VALUES'],
                    ['status', 'TEST_MARKER', 'NOT_ACCEPTED_RESEARCH'],
                    ['eligible_for_target', 'FALSE', 'AUTOMATION_DISABLED']]


def _private(drive):
    info = drive.check(PRIVATE_SHEET, PRIVATE_ROOT, folder=False)
    require(isinstance(info, dict)
            and info.get('mimeType') == 'application/vnd.google-apps.spreadsheet', 'PRIVATE_METADATA')
    capabilities = drive.get('files/' + PRIVATE_SHEET, {'fields': 'id,capabilities(canEdit)'})
    require(isinstance(capabilities, dict) and capabilities.get('id') == PRIVATE_SHEET
            and capabilities.get('capabilities', {}).get('canEdit') is True, 'PRIVATE_METADATA')


def _json(drive, url, *, limit=65536, **kwargs):
    from tools.twelve_private_capture import credential_safe_json
    require(type(limit) is int and 0 < limit <= 2_000_000, 'PROBE_RESPONSE')
    value = credential_safe_json(drive.request(url, limit=limit, **kwargs), (drive.token,))
    require(isinstance(value, dict), 'PROBE_RESPONSE')
    return value


def run_target(binding):
    title = 'ETF116_ACTIONS_PROBE_' + binding['GITHUB_RUN_ID'] + '_' + binding['GITHUB_RUN_ATTEMPT']
    sheet_id = (int(digest(binding)[:8], 16) & 0x7fffffff) or 1
    return sheet_id, title, title + '!A1:C9'


def run_probe(drive, binding, *, stage_cb=None):
    sheet_id, title, cell_range = run_target(binding)
    expected = marker(binding, drive.owner)
    result = literal_private_tab(drive, sheet_id, title, expected, stage_cb=stage_cb)
    return {'schema': 'etf116-private-actions-sheet-probe-v1',
            'state': 'IDENTICAL_MARKER_READBACK' if result['unchanged'] else 'CREATE_AND_READBACK_VERIFIED',
            'binding': binding, 'auth_mode': 'EXISTING_OWNER_OAUTH',
            'principal_sha256': digest(drive.owner), 'test_sheet_sha256': digest(PRIVATE_SHEET),
            'range': cell_range, 'sheet_id': sheet_id, 'cell_count': 27, 'values_sha256': digest(expected),
            'write_requests': result['write_requests'], 'private_test_only': True,
            'source_admission': False, 'research_snapshot_published': False,
            'automatic_refresh_enabled': False, 'economic_authority': False}


def literal_private_tab(drive, sheet_id, title, expected, *, existing_only=False, stage_cb=None):
    """Atomically CREATE a run-owned tab and its marker in the fixed copy.

    addSheet fails on either ID/name collision. updateCells is in that SAME
    atomic batch, so a racing external client cannot turn a blank-cell check
    into an overwrite of an existing sheet. No existing-sheet update path.
    """
    require(type(sheet_id) is int and 0 < sheet_id <= 0x7fffffff
            and isinstance(title, str) and re.fullmatch(r'ETF116_[A-Z0-9_]{1,90}', title)
            and isinstance(expected, list) and 1 <= len(expected) <= 1000
            and all(isinstance(row, list) and 1 <= len(row) <= 24 for row in expected)
            and all(len(row) == len(expected[0]) for row in expected)
            and all(isinstance(v, str) and 1 <= len(v) <= 256 for row in expected for v in row)
            and len(json.dumps(expected).encode()) <= 1_000_000, 'PROBE_UPDATE')
    if stage_cb is not None:
        require(callable(stage_cb), 'INTERNAL_REFUSAL')
    def stage(label):
        if stage_cb is not None:
            stage_cb(label)
    rows, cols = len(expected), len(expected[0])
    cell_range = title + '!A1:' + chr(64 + cols) + str(rows)
    stage('PRIVATE_DRIVE_CHECK')
    _private(drive)
    base = 'https://sheets.googleapis.com/v4/spreadsheets/' + PRIVATE_SHEET
    stage('SHEETS_METADATA_GET')
    meta = _json(drive, base + '?fields=spreadsheetId,sheets(properties)')
    require(meta.get('spreadsheetId') == PRIVATE_SHEET, 'PROBE_TAB')
    tabs = [s.get('properties') for s in meta.get('sheets', []) if isinstance(s, dict)
            and isinstance(s.get('properties'), dict) and s['properties'].get('title') == TAB]
    require(len(tabs) == 1 and tabs[0].get('sheetId') == TAB_ID, 'PROBE_TAB')
    properties = [s['properties'] for s in meta.get('sheets', []) if isinstance(s, dict)
                  and isinstance(s.get('properties'), dict)]
    matches = [p for p in properties if p.get('sheetId') == sheet_id or p.get('title') == title]
    require(not matches or (len(matches) == 1 and matches[0].get('sheetId') == sheet_id
                            and matches[0].get('title') == title), 'PROBE_TAB_COLLISION')
    url = base + '/values/' + quote(cell_range, safe='')
    unchanged = bool(matches)
    require(not existing_only or unchanged, 'PROBE_READBACK')
    if unchanged:
        # Reconciliation is GET-only and never establishes a new write proof.
        stage('SHEETS_EXISTING_GET')
        before = _json(drive, url + '?valueRenderOption=FORMULA', limit=2_000_000).get('values')
        require(before == expected, 'PROBE_READBACK')
    else:
        stage('PRIVATE_DRIVE_RECHECK')
        _private(drive)
        props = {'sheetId': sheet_id, 'title': title,
                 'gridProperties': {'rowCount': rows, 'columnCount': cols}}
        payload = {'requests': [
            {'addSheet': {'properties': props}},
            {'updateCells': {'range': {'sheetId': sheet_id, 'startRowIndex': 0,
                'endRowIndex': rows, 'startColumnIndex': 0, 'endColumnIndex': cols},
                'rows': [{'values': [{'userEnteredValue': {'stringValue': v}}
                                     for v in row]} for row in expected],
                'fields': 'userEnteredValue'}}]}
        # One non-retried atomic create+populate; no standalone values PUT.
        stage('SHEETS_ATOMIC_POST')
        result = _json(drive, base + ':batchUpdate', method='POST',
                       body=json.dumps(payload).encode(),
                       headers={'Content-Type': 'application/json'})
        replies = result.get('replies')
        require(result.get('spreadsheetId') == PRIVATE_SHEET
                and isinstance(replies, list) and len(replies) == 2
                and replies[0].get('addSheet', {}).get('properties', {}).get('sheetId') == sheet_id
                and replies[0].get('addSheet', {}).get('properties', {}).get('title') == title,
                'PROBE_UPDATE')
    stage('SHEETS_READBACK_GET')
    after = _json(drive, url + '?valueRenderOption=UNFORMATTED_VALUE', limit=2_000_000).get('values')
    require(after == expected, 'PROBE_READBACK')
    stage('PRIVATE_DRIVE_FINAL_CHECK')
    _private(drive)
    return {'unchanged': unchanged, 'range': cell_range, 'sheet_id': sheet_id,
            'values_sha256': digest(after), 'write_requests': 0 if unchanged else 1}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    # Reserve receipt before auth/network, preserving any existing proof.
    with Path(args.output).open('x', encoding='utf-8') as handle:
        stage = 'LOCAL_AUTHORIZATION'
        access_reason = None
        def record_stage(label):
            nonlocal stage
            require(label in {'PRIVATE_DRIVE_CHECK', 'SHEETS_METADATA_GET',
                              'SHEETS_EXISTING_GET', 'PRIVATE_DRIVE_RECHECK',
                              'SHEETS_ATOMIC_POST', 'SHEETS_READBACK_GET',
                              'PRIVATE_DRIVE_FINAL_CHECK'}, 'INTERNAL_REFUSAL')
            stage = label
        try:
            binding = actions_binding(os.environ)
            require(bool(os.environ.get('RCLONE_CONFIG_GDRIVE')), 'OWNER_OAUTH_CONFIG_REQUIRED')
            from tools.twelve_private_capture import OwnerDrive, Refused as OwnerRefused
            os.environ['MACRO_DRIVE_CONFIG'] = os.environ['RCLONE_CONFIG_GDRIVE']
            with tempfile.TemporaryDirectory(prefix='etf116-private-probe-') as temp:
                try:
                    stage = 'OWNER_DRIVE_INITIALIZATION'
                    drive = OwnerDrive(PRIVATE_ROOT, temp)
                    stage = 'PRIVATE_SHEET_PROBE'
                    receipt = run_probe(drive, binding, stage_cb=record_stage)
                except ProbeRefused:
                    raise
                except OwnerRefused as exc:
                    # Only literal reviewed categories, never arbitrary exception text.
                    known = frozenset('DRIVE_AUTH DRIVE_AUTH_OR_QUOTA_PROBE_FAILED '
                        'DRIVE_CONFIGURATION DRIVE_CREDENTIALS_MISSING_OR_INVALID '
                        'DRIVE_NOT_OWNER_ONLY DRIVE_OWNER_UNVERIFIED DRIVE_PARENT '
                        'DRIVE_QUOTA_UNVERIFIED DRIVE_SPACE OWNER_OAUTH_REQUIRED '
                        'HTTP_ERROR NETWORK PERMISSION'.split())
                    access_reason = str(exc) if str(exc) in known else 'UNCLASSIFIED_OWNER_REFUSAL'
                    reason = ('ATOMIC_POST_OUTCOME_UNKNOWN'
                              if stage == 'SHEETS_ATOMIC_POST'
                              else 'OWNER_OAUTH_ACCESS_BLOCKED')
                    raise ProbeRefused(reason) from None
                except Exception:
                    # Unknown POST outcome may have committed; never automatically replay.
                    reason = ('ATOMIC_POST_OUTCOME_UNKNOWN'
                              if stage == 'SHEETS_ATOMIC_POST'
                              else 'OWNER_OAUTH_ACCESS_BLOCKED')
                    raise ProbeRefused(reason) from None
        except ProbeRefused as exc:
            json.dump({'schema': 'etf116-private-actions-sheet-probe-v1',
                       'state': 'BLOCKED', 'reason': str(exc), 'verified': False,
                       'failed_stage': stage, 'access_reason': access_reason,
                       'automatic_refresh_enabled': False}, handle, sort_keys=True)
            print('BLOCKED_ETF116_PRIVATE_PROBE:' + str(exc))
            return 2
        json.dump(receipt, handle, sort_keys=True)
    print(json.dumps({'state': receipt['state'], 'cell_count': receipt['cell_count'],
                      'automatic_refresh_enabled': False}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

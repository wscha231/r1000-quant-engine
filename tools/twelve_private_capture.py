#!/usr/bin/env python3
"""Bounded Twelve research capture into the existing owner-only Drive layout.

This is not Alpaca IEX concordance, Russell membership, PIT or source admission.
No credential-bearing diagnostic or price body may enter Actions output.
"""
from __future__ import annotations

import argparse
import configparser
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import gzip
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.configure_macro_research_drive import validate_drive_config
from tools.macro_history_sources import NoRedirect, digest, encoded

CONTRACT_ID = '1XRv5H30jSJ-sIaCpwys9Va8UefE1bYHB'
CONTRACT_SHA = 'e27710b80d16b2e85661c23e0108315c5f97d59ded907958581b7c72b6c164c6'
KEYS = {'TWELVE_API_KEY', 'TWELVE_API_KEY2'}
SYMBOLS = (('AAPL', 'XNGS'), ('MSFT', 'XNGS'), ('BE', 'XNYS'), ('TSM', 'XNYS'))
START, END = '2016-10-09', '2026-10-10'
MAX_BYTES = 2_000_000
MAX_PACK = 16_000_000
TERMS = ('https://twelvedata.com/terms',
         'https://twelvedata.com/pricing',
         'https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage',
         'https://support.twelvedata.com/en/articles/9935903-us-equities-market-data')
SAFE_CODES = frozenset('ACCOUNT_PLAN_UNVERIFIED ACCOUNT_QUOTA_UNVERIFIED BAR_DATE BAR_SHAPE BAR_VALUE '
                      'CREDENTIAL_ECHO CURRENT_IDENTITY_MISMATCH DAILY_BUDGET DRIVE_AUTH '
                      'DRIVE_AUTH_OR_QUOTA_PROBE_FAILED DRIVE_CONFIGURATION DRIVE_CREDENTIALS_MISSING_OR_INVALID '
                      'DRIVE_ENDPOINT DRIVE_FOLDER DRIVE_ID DRIVE_NOT_OWNER_ONLY DRIVE_OWNER_UNVERIFIED '
                      'DRIVE_PARENT DRIVE_QUOTA_UNVERIFIED DRIVE_READBACK DRIVE_SPACE DRIVE_UPLOAD ENDPOINT '
                      'HISTORY_SIZE HTTP_ERROR INVALID_JSON KEY_SELECTION MEMBER_HASH NETWORK OWNER_OAUTH_REQUIRED '
                      'PACK_CRC_OR_MEMBERSHIP PACK_HASH PACK_SIZE PRIVATE_ROOT_MISSING PROVIDER_SHAPE PROVIDER_ERROR '
                      'RAW_RESTORE_NORMALIZATION RAW_SPLIT_SESSION_MISMATCH RESPONSE_SIZE SELECTED_SECRET_MISSING '
                      'STORAGE_CONTRACT_HASH STORAGE_ROOT_BINDING USER_AUTHORIZATION_MISSING SOURCE_FIELDS AUTH ENTITLEMENT '
                      'PERMISSION RATE_LIMIT'.split())


class Refused(ValueError):
    pass


def require(value, code):
    if not value:
        raise Refused(code)


def now():
    return datetime.now(timezone.utc).isoformat()


def decode(raw):
    def constant(_):
        raise Refused('INVALID_JSON')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'INVALID_JSON')
            value[key] = item
        return value
    try:
        return json.loads(raw, parse_constant=constant, object_pairs_hook=unique)
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise Refused('INVALID_JSON') from None


def credential_safe_json(raw, credentials):
    """Inspect original JSON strings and keys after escape decoding, before storage."""
    require(all(not value or value.encode() not in raw for value in credentials), 'CREDENTIAL_ECHO')
    data = decode(raw)
    pending = [data]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            require(all(not key or key not in value for key in credentials), 'CREDENTIAL_ECHO')
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return data


def http(url, *, method='GET', headers=None, body=None, limit=MAX_BYTES, credentials=()):
    """No redirects/retries; do not expose vendor bodies, exception text or URLs."""
    try:
        with build_opener(NoRedirect()).open(Request(url, data=body, method=method,
                                                    headers=headers or {}), timeout=25) as reply:
            status, raw = reply.status, reply.read(limit + 1)
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise Refused({401: 'AUTH', 402: 'ENTITLEMENT', 403: 'PERMISSION',
                       429: 'RATE_LIMIT'}.get(status, 'HTTP_ERROR')) from None
    except Exception:
        raise Refused('NETWORK') from None
    require(status == 200, 'HTTP_ERROR')
    require(0 < len(raw) <= limit, 'RESPONSE_SIZE')
    require(all(not value or value.encode() not in raw for value in credentials), 'CREDENTIAL_ECHO')
    return raw


def twelve(endpoint, query, key):
    require(endpoint in ('/api_usage', '/time_series'), 'ENDPOINT')
    raw = http('https://api.twelvedata.com' + endpoint + '?' + urlencode(query),
               headers={'Authorization': 'apikey ' + key, 'Accept': 'application/json'},
               credentials=(key,))
    data = credential_safe_json(raw, (key,))
    require(isinstance(data, dict), 'PROVIDER_SHAPE')
    if data.get('status') == 'error' or ('code' in data and data['code'] != 200):
        raise Refused({401: 'AUTH', 402: 'ENTITLEMENT', 403: 'ENTITLEMENT',
                       429: 'RATE_LIMIT'}.get(data.get('code'), 'PROVIDER_ERROR'))
    return raw, data


def usage(data):
    # Official SDK JSON names are plan_category and plan_daily_limit, not plan
    # and daily_limit. This free-account pilot accepts the documented Basic
    # quota signature only; other tiers require their own explicit binding.
    category = data.get('plan_category')
    require(isinstance(category, str) and category.lower() in ('basic', 'individual'), 'ACCOUNT_PLAN_UNVERIFIED')
    fields = {name: data.get(name) for name in
              ('current_usage', 'plan_limit', 'daily_usage', 'plan_daily_limit')}
    require(type(fields['current_usage']) is int and fields['current_usage'] >= 0
            and type(fields['plan_limit']) is int and fields['plan_limit'] == 8
            and type(fields['plan_daily_limit']) is int and fields['plan_daily_limit'] == 800,
            'ACCOUNT_QUOTA_UNVERIFIED')
    require(type(fields['daily_usage']) is int and fields['daily_usage'] >= 0, 'ACCOUNT_QUOTA_UNVERIFIED')
    require(fields['plan_daily_limit'] - fields['daily_usage'] >= 12, 'DAILY_BUDGET')
    return dict(plan='Basic', plan_binding='PROVIDER_CATEGORY_AND_8_PER_MINUTE_800_PER_DAY',
                plan_category=category.lower(), **fields)


def rows(data, symbol, mic, adjustment):
    require(set(data) <= {'meta', 'values', 'status'} and data.get('status', 'ok') == 'ok', 'SOURCE_FIELDS')
    meta, values = data.get('meta'), data.get('values')
    require(isinstance(meta, dict) and meta.get('symbol') == symbol
            and meta.get('mic_code') == mic and meta.get('currency') == 'USD'
            and meta.get('interval') == '1day', 'CURRENT_IDENTITY_MISMATCH')
    require(set(meta) <= {'symbol', 'mic_code', 'currency', 'interval', 'exchange',
                          'exchange_timezone', 'type'}, 'SOURCE_FIELDS')
    require(isinstance(values, list) and 0 < len(values) < 5000, 'HISTORY_SIZE')
    result, seen = [], set()
    for row in values:
        require(isinstance(row, dict), 'BAR_SHAPE')
        require(set(row) == {'datetime', 'open', 'high', 'low', 'close', 'volume'}, 'SOURCE_FIELDS')
        session = row.get('datetime')
        require(isinstance(session, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', session), 'BAR_DATE')
        try:
            d = date.fromisoformat(session)
        except ValueError:
            raise Refused('BAR_DATE') from None
        require(START <= session < END and d.weekday() < 5 and session not in seen, 'BAR_DATE')
        seen.add(session)
        try:
            fields = [row[name] for name in ('open', 'high', 'low', 'close', 'volume')]
            require(all(type(v) in (str, int, float) for v in fields), 'BAR_VALUE')
            o, h, l, c, v = [Decimal(str(value)) for value in fields]
            require(all(x.is_finite() for x in (o, h, l, c, v)) and min(o, h, l, c) > 0
                    and l <= min(o, c) <= max(o, c) <= h and v >= 0
                    and v == v.to_integral_value(), 'BAR_VALUE')
        except (KeyError, InvalidOperation, OverflowError):
            raise Refused('BAR_VALUE') from None
        result.append(dict(symbol=symbol, mic=mic, currency='USD', date=session,
                           adjustment=adjustment, **{name: str(value) for name, value in
                           zip(('open', 'high', 'low', 'close', 'volume'), (o, h, l, c, v))}))
    return sorted(result, key=lambda x: x['date'])


class OwnerDrive:
    """Reuse reviewed rclone OAuth validation/refresh, then narrow Drive REST scope."""
    def __init__(self, root_id, temp, *, meter=None):
        require(re.fullmatch(r'[A-Za-z0-9_-]{10,100}', root_id or ''), 'PRIVATE_ROOT_MISSING')
        self.root_id = root_id
        self.meter = meter
        supplied = configparser.ConfigParser(interpolation=None)
        try:
            supplied.read_string(os.environ.get('MACRO_DRIVE_CONFIG', ''))
            require(supplied.has_section('gdrive') and supplied['gdrive'].get('type') == 'drive',
                    'DRIVE_CREDENTIALS_MISSING_OR_INVALID')
            source = supplied['gdrive']
            require(not any(source.get(k) for k in
                            ('service_account_file', 'service_account_credentials', 'team_drive')),
                    'OWNER_OAUTH_REQUIRED')
            validate_drive_config(source)
            if meter is not None:
                self.oauth_source = dict(source)
                token = decode(source['token'])
                self.token = token.get('access_token', token.get('AccessToken'))
                expiry = token.get('expiry', token.get('Expiry'))
                self.token_expiry = datetime.fromisoformat(expiry.replace('Z', '+00:00'))
                self.ensure_metered_token()
            else:
                conf = configparser.ConfigParser(interpolation=None)
                conf['gdrive'] = {k: source[k] for k in ('type', 'scope', 'token', 'client_id', 'client_secret')
                                  if k in source}
                conf['gdrive']['root_folder_id'] = root_id
                path = Path(temp) / 'private-rclone.conf'
                with path.open('x') as handle:
                    conf.write(handle)
                path.chmod(0o600)
                env = {k: os.environ[k] for k in ('PATH', 'HOME', 'SSL_CERT_FILE', 'TMPDIR') if k in os.environ}
                env['RCLONE_CONFIG'] = str(path)
                reply = subprocess.run([os.environ.get('MACRO_RCLONE_BIN', 'rclone'), 'about', 'gdrive:',
                                        '--json', '--retries', '1', '--low-level-retries', '1'],
                                       env=env, capture_output=True, timeout=45)
                require(reply.returncode == 0, 'DRIVE_AUTH_OR_QUOTA_PROBE_FAILED')
                refreshed = configparser.ConfigParser(interpolation=None)
                refreshed.read(path)
                token = decode(refreshed['gdrive']['token'])
                self.token = token.get('access_token', token.get('AccessToken'))
            require(isinstance(self.token, str) and bool(self.token), 'DRIVE_AUTH')
        except Refused:
            raise
        except Exception:
            raise Refused('DRIVE_CONFIGURATION') from None
        about = self.get('about', {'fields': 'user(permissionId),storageQuota'})
        self.owner = about.get('user', {}).get('permissionId')
        require(isinstance(self.owner, str) and bool(self.owner), 'DRIVE_OWNER_UNVERIFIED')
        quota = about.get('storageQuota', {})
        require(isinstance(quota.get('limit'), str) and quota['limit'].isdigit()
                and isinstance(quota.get('usage'), str) and quota['usage'].isdigit(), 'DRIVE_QUOTA_UNVERIFIED')
        self.free = int(quota['limit']) - int(quota['usage'])
        require(self.free >= 32_000_000, 'DRIVE_SPACE')
        self.check(root_id)

    def ensure_metered_token(self):
        if datetime.now(timezone.utc) + timedelta(seconds=60) < self.token_expiry:
            return
        source = self.oauth_source
        require(source.get('client_id') and source.get('client_secret'),
                'CAMPAIGN_OAUTH_CLIENT_REQUIRED')
        old = decode(source['token'])
        refresh = old.get('refresh_token', old.get('RefreshToken'))
        credentials = (self.token, refresh, source['client_secret'])
        body = urlencode(dict(grant_type='refresh_token', refresh_token=refresh,
                              client_id=source['client_id'], client_secret=source['client_secret'])).encode()
        raw = self.meter.perform('https://oauth2.googleapis.com/token', method='POST', body=body,
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'},
                                 limit=65536, credentials=credentials)
        result = credential_safe_json(raw, credentials)
        require(isinstance(result, dict) and isinstance(result.get('access_token'), str)
                and bool(result['access_token']) and result.get('token_type') == 'Bearer'
                and type(result.get('expires_in')) is int
                and 60 < result['expires_in'] <= 86400, 'DRIVE_AUTH')
        self.token = result['access_token']
        self.token_expiry = datetime.now(timezone.utc) + timedelta(seconds=result['expires_in'])

    def request(self, url, **kwargs):
        meter = getattr(self, 'meter', None)
        if meter is not None:
            self.ensure_metered_token()
        headers = kwargs.pop('headers', {})
        headers['Authorization'] = 'Bearer ' + self.token
        get = http if meter is None else meter.perform
        return get(url, headers=headers, credentials=(self.token,), **kwargs)

    def get(self, path, query):
        require(re.fullmatch(r'about|files/[A-Za-z0-9_-]+', path), 'DRIVE_ENDPOINT')
        return decode(self.request('https://www.googleapis.com/drive/v3/' + path + '?' + urlencode(query)))

    def check(self, file_id, parent=None, folder=True):
        info = self.get('files/' + file_id, {'fields': 'id,mimeType,trashed,shared,parents,permissions(id,type,role)'})
        permissions = info.get('permissions')
        require(info.get('id') == file_id and info.get('trashed') is False
                and info.get('shared') is False and isinstance(permissions, list) and len(permissions) == 1
                and permissions[0].get('role') == 'owner' and permissions[0].get('type') == 'user'
                and permissions[0].get('id') == self.owner, 'DRIVE_NOT_OWNER_ONLY')
        if folder:
            require(info.get('mimeType') == 'application/vnd.google-apps.folder', 'DRIVE_FOLDER')
        if parent:
            require(info.get('parents') == [parent], 'DRIVE_PARENT')
        return info

    def read(self, file_id, limit=MAX_PACK):
        require(re.fullmatch(r'[A-Za-z0-9_-]+', file_id), 'DRIVE_ID')
        return self.request('https://www.googleapis.com/drive/v3/files/' + file_id + '?alt=media', limit=limit)

    def write(self, folder_id, raw, extension):
        require(0 < len(raw) <= MAX_PACK and extension in ('.json', '.zip', '.jsonl.gz'), 'PACK_SIZE')
        require(self.free >= len(raw), 'DRIVE_SPACE')
        meter = getattr(self, 'meter', None)
        if meter is not None:
            meter.reserve_storage(len(raw))
        self.check(folder_id, self.root_id)
        boundary = 'r1000-' + digest(raw)
        metadata = encoded(dict(name=digest(raw) + extension, parents=[folder_id]))
        body = (('--' + boundary + '\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n').encode()
                + metadata + ('\r\n--' + boundary + '\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
                + raw + ('\r\n--' + boundary + '--\r\n').encode())
        result = decode(self.request('https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart'
                                    '&ignoreDefaultVisibility=true&fields=id',
                                    method='POST', body=body,
                                    headers={'Content-Type': 'multipart/related; boundary=' + boundary}))
        file_id = result.get('id')
        require(isinstance(file_id, str), 'DRIVE_UPLOAD')
        self.check(file_id, folder_id, folder=False)
        require(self.read(file_id) == raw, 'DRIVE_READBACK')
        if meter is not None:
            meter.confirmed_storage_bytes += len(raw)
            meter.save()
        self.free -= len(raw)
        return dict(file_id=file_id, sha256=digest(raw), bytes=len(raw))


def capture(drive, folders, key, rights, provider=twelve, pause=time.sleep,
            symbols=SYMBOLS, collection_scope=None):
    require(isinstance(symbols, (list, tuple)) and 1 <= len(symbols) <= 4
            and all(isinstance(p, tuple) and len(p) == 2 for p in symbols)
            and len(set(symbols)) == len(symbols)
            and all(isinstance(s, str) and re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,14}', s)
                    and mic in {'XNGS', 'XNGM', 'XNCM', 'XNYS', 'XASE'} for s, mic in symbols),
            'SOURCE_FIELDS')
    raw_members, normalized, evidence = {}, [], []
    for symbol, mic in symbols:
        bases = {}
        for adjustment in ('none', 'splits'):
            pause(10)
            query = dict(symbol=symbol, mic_code=mic, interval='1day', start_date=START,
                         end_date=END, outputsize=5000, order='asc', adjust=adjustment)
            raw, _ = provider('/time_series', query, key)
            data = credential_safe_json(raw, (key,))
            normalized_rows = rows(data, symbol, mic, adjustment)
            member = digest(raw) + '.json'
            raw_members[member] = raw
            bases[adjustment] = {r['date'] for r in normalized_rows}
            normalized.extend(normalized_rows)
            evidence.append(dict(symbol=symbol, mic=mic, adjustment=adjustment,
                                 request=query, member=member, sha256=digest(raw), bytes=len(raw),
                                 rows=len(normalized_rows), first=normalized_rows[0]['date'],
                                 last=normalized_rows[-1]['date'], retrieved_at=now()))
        require(bases['none'] == bases['splits'], 'RAW_SPLIT_SESSION_MISMATCH')
    require(sum(map(len, raw_members.values())) <= MAX_PACK, 'PACK_SIZE')
    raw_members['capture.json'] = encoded(dict(evidence=evidence, rights_sha256=rights['sha256']))
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as pack:
        for name, raw in sorted(raw_members.items()):
            pack.writestr(name, raw)
    raw_object = drive.write(folders['01-provider-raw'], stream.getvalue(), '.zip')
    restored = drive.read(raw_object['file_id'])
    require(len(restored) == raw_object['bytes'] and digest(restored) == raw_object['sha256'], 'PACK_HASH')
    rebuilt = []
    with zipfile.ZipFile(io.BytesIO(restored)) as pack:
        require(pack.testzip() is None and len(pack.namelist()) == len(raw_members)
                and set(pack.namelist()) == set(raw_members), 'PACK_CRC_OR_MEMBERSHIP')
        for name, original in raw_members.items():
            require(pack.read(name) == original, 'MEMBER_HASH')
        for e in evidence:
            raw = pack.read(e['member'])
            require(digest(raw) == e['sha256'], 'MEMBER_HASH')
            rebuilt.extend(rows(decode(raw), e['symbol'], e['mic'], e['adjustment']))
    require(rebuilt == normalized, 'RAW_RESTORE_NORMALIZATION')
    normalized_bytes = gzip.compress(b''.join(encoded(r) for r in normalized), mtime=0)
    normalized_object = drive.write(folders['02-normalized'], normalized_bytes, '.jsonl.gz')
    receipt = dict(schema='twelve-private-capture-v1', evidence=evidence, rights=rights,
                   raw_object=raw_object, normalized_object=normalized_object, rows=len(normalized),
                   restored_from_drive=True, historical_session_completeness='NOT_CERTIFIED',
                   historical_identity_verified=False, pit_verified=False, source_admission=False,
                   immutable_reader_e2e=False, economic_authority=False,
                   run_id=os.environ.get('GITHUB_RUN_ID'), code_sha=os.environ.get('GITHUB_SHA'))
    if collection_scope is not None:
        receipt['collection_scope'] = collection_scope
    saved = drive.write(folders['06-receipts'], encoded(receipt), '.json')
    checkpoint = drive.write(folders['05-checkpoints'], encoded(dict(schema='twelve-private-pilot-checkpoint-v1',
                             receipt=saved, status='PILOT_CAPTURE_RESTORED', bulk_enabled=False)), '.json')
    return dict(receipt=saved, checkpoint=checkpoint, rows=len(normalized), raw_objects=1,
                history=[{k: e[k] for k in ('symbol', 'adjustment', 'rows', 'first', 'last')} for e in evidence])


def run(capture_history=False, cohort_reference=None, resume_reference=None, max_new_symbols=32):
    require(cohort_reference is None or capture_history, 'SOURCE_FIELDS')
    require(os.environ.get('A1_PRIVATE_RESEARCH_AUTHORIZED') == 'true', 'USER_AUTHORIZATION_MISSING')
    selected = os.environ.get('TWELVE_KEY_NAME')
    require(selected in KEYS, 'KEY_SELECTION')
    key = os.environ.get(selected, '').strip()
    require(bool(key), 'SELECTED_SECRET_MISSING')
    _, account = twelve('/api_usage', {}, key)
    budget = usage(account)
    with tempfile.TemporaryDirectory(prefix='r1000-private-') as temp:
        drive = OwnerDrive(os.environ.get('R1000_PRIVATE_RESEARCH_FOLDER_ID'), temp)
        contract_raw = drive.read(CONTRACT_ID, MAX_BYTES)
        require(digest(contract_raw) == CONTRACT_SHA, 'STORAGE_CONTRACT_HASH')
        contract = decode(contract_raw)
        require(contract['destination']['root_id'] == drive.root_id, 'STORAGE_ROOT_BINDING')
        folders = contract['destination']['folders']
        drive.check(CONTRACT_ID, folders['00-control'], folder=False)
        for folder in folders.values():
            drive.check(folder, drive.root_id)
        rights = dict(schema='twelve-private-conditional-rights-v1', permitted_use='PRIVATE_NONCOMMERCIAL_RESEARCH',
                      user_authorized_at='2026-10-11T09:05:18Z', provider='twelve_data',
                      selected_repository_secret=selected, repository='wscha231/r1000-quant-engine',
                      dataset='US_LISTED_EQUITY_DAILY_HISTORY', account_plan=budget,
                      subscription_status_verified_at=now(), terms_urls=list(TERMS),
                      permitted_storage_locations=[drive.root_id], perpetual_retention_explicit=False,
                      permitted_retention_until='ONLY_WHILE_ACCOUNT_SUBSCRIPTION_AND_PROVIDER_RIGHTS_PERMIT',
                      deletion_on_termination='DELETE_ALL_DATA_WITHIN_30_DAYS_OR_EARLIER_PROVIDER_REQUIREMENT',
                      redistribution=False, commercial_use=False, automatic_key_switch=False)
        rights_object = drive.write(folders['00-control'], encoded(rights), '.json')
        canary_raw = encoded(dict(schema='r1000-private-binding-canary-v1', synthetic=True,
                                 rights_sha256=rights_object['sha256'], run_id=os.environ.get('GITHUB_RUN_ID')))
        canary = drive.write(folders['07-recovery-tests'], canary_raw, '.json')
        result = dict(status='PRIVATE_STORAGE_BOUND', selected_secret_name=selected, account=budget,
                      rights=rights_object, canary=canary, available_drive_bytes=drive.free,
                      retained_provider_raw_objects=0, full_r1000_collection=False,
                      source_admission=False, pointer_promotion=False, economic_authority=False,
                      fullrun=False, auto_merge=False, automatic_key_switch=False)
        if capture_history:
            if cohort_reference is None:
                result.update(capture(drive, folders, key, rights_object))
                result['status'] = 'FOUR_SYMBOL_HISTORY_CAPTURE_RESTORED'
                result['retained_provider_raw_objects'] = 1
            else:
                from tools.twelve_private_cohort import collect
                result.update(collect(drive, folders, key, rights_object, budget,
                                      cohort_reference, resume_reference, max_new_symbols))
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--capture-history', action='store_true')
    parser.add_argument('--cohort-file-id', default='')
    parser.add_argument('--cohort-sha256', default='')
    parser.add_argument('--resume-file-id', default='')
    parser.add_argument('--resume-sha256', default='')
    parser.add_argument('--max-new-symbols', type=int, default=32)
    args = parser.parse_args()
    try:
        from tools.twelve_private_cohort import reference
        cohort = reference(args.cohort_file_id, args.cohort_sha256)
        resume = reference(args.resume_file_id, args.resume_sha256)
        require(resume is None or cohort is not None, 'SOURCE_FIELDS')
        report = run(args.capture_history, cohort, resume, args.max_new_symbols)
    except Refused as exc:
        # Only this module's constant diagnostic codes are emitted.
        code = str(exc)
        if code not in SAFE_CODES:
            code = 'UNCLASSIFIED_REFUSAL'
        print(json.dumps(dict(status='BLOCKED', reason=code, full_r1000_collection=False,
                              source_admission=False, economic_authority=False), sort_keys=True))
        return 1
    except Exception:
        print('{"status":"BLOCKED","reason":"UNEXPECTED_FAILURE","source_admission":false}')
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    # The resume worker must share this module's refusal type at the real CLI.
    sys.modules.setdefault('tools.twelve_private_capture', sys.modules[__name__])
    raise SystemExit(main())

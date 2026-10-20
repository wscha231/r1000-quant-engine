"""Append-only, bounded capture queue; current vendor identities are never PIT."""
from __future__ import annotations

import json
import re
import gzip
import io
import zipfile

from tools import twelve_private_capture as m

INITIAL = dict(file_id='1mx4ibR_WJ-vLqmKernah5sAWnf70O3o6',
               sha256='1a42a1d8447bf927c1982cce0f8355321a18537e925b6b65ddd271863ba680cb')
MICS = {'XNGS', 'XNGM', 'XNCM', 'XNYS', 'XASE'}
FLAGS = ('historical_identity_verified', 'pit_verified', 'source_admission', 'economic_authority')
# Immutable planned scope with independently verified cross-issuer conflicts.
BAD_IDENTITY_SCOPE_SHA = '3950bf63d87e280d62fc5ea9fb35f2e76643db669961658ebd5db4cea2ca86b5'


def reference(file_id, sha):
    if not file_id and not sha:
        return None
    m.require(isinstance(file_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{10,100}', file_id)
              and isinstance(sha, str) and re.fullmatch(r'[a-f0-9]{64}', sha), 'SOURCE_FIELDS')
    return dict(file_id=file_id, sha256=sha)


def require_capture_identity(cohort_ref):
    m.require(isinstance(cohort_ref, dict) and {'file_id', 'sha256'} <= set(cohort_ref),
              'SOURCE_FIELDS')
    reference(cohort_ref['file_id'], cohort_ref['sha256'])
    m.require(cohort_ref['sha256'] != BAD_IDENTITY_SCOPE_SHA, 'CURRENT_IDENTITY_MISMATCH')


def read(drive, ref, parent):
    m.require(isinstance(ref, dict) and {'file_id', 'sha256'} <= set(ref), 'SOURCE_FIELDS')
    reference(ref['file_id'], ref['sha256'])
    drive.check(ref['file_id'], parent, folder=False)
    raw = drive.read(ref['file_id'], m.MAX_BYTES)
    m.require(m.digest(raw) == ref['sha256'], 'MEMBER_HASH')
    return m.decode(raw)


def scope(value):
    m.require(isinstance(value, dict) and value.get('schema') == 'twelve-private-collection-scope-v1'
              and all(value.get(flag) is False for flag in FLAGS)
              and value.get('historical_index_membership_verified') is False, 'SOURCE_FIELDS')
    m.require(value.get('window') == dict(start=m.START, end_exclusive=m.END, interval='1day',
                                         adjustments=['none', 'splits']), 'SOURCE_FIELDS')
    identity = value.get('identity_snapshot', {})
    m.require(identity.get('authority') == 'CURRENT_VENDOR_REPORTED_INSTRUMENT_ONLY'
              and re.fullmatch(r'[a-f0-9]{64}', identity.get('sha256', ''))
              and identity.get('source_url') == 'https://api.twelvedata.com/stocks?country=United%20States',
              'SOURCE_FIELDS')
    requested, instruments, unresolved = (value.get(k) for k in
                                          ('requested_targets', 'instruments', 'unresolved'))
    m.require(isinstance(requested, list) and 1 <= len(requested) <= 1500
              and isinstance(instruments, list) and isinstance(unresolved, list), 'SOURCE_FIELDS')
    names = [r.get('symbol') for r in requested if isinstance(r, dict)]
    m.require(len(names) == len(requested) == len(set(names))
              and all(isinstance(s, str) and re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,14}', s)
                      for s in names), 'SOURCE_FIELDS')
    resolved = []
    for row in instruments:
        m.require(isinstance(row, dict) and row.get('symbol') in names and row.get('mic') in MICS
                  and row.get('currency') == 'USD'
                  and row.get('provider_reported_type') in
                  {'Common Stock', 'Depositary Receipt', 'American Depositary Receipt', 'REIT'}
                  and re.fullmatch(r'BBG[A-Z0-9]{9}', row.get('provider_reported_figi', '')),
                  'CURRENT_IDENTITY_MISMATCH')
        resolved.append(row['symbol'])
    missing = [r.get('symbol') for r in unresolved if isinstance(r, dict)]
    m.require(len(resolved) == len(set(resolved)) and len(missing) == len(unresolved) == len(set(missing))
              and not set(resolved) & set(missing) and set(resolved) | set(missing) == set(names)
              and resolved == [s for s in names if s in set(resolved)], 'SOURCE_FIELDS')
    m.require({k: value.get('initial_receipt', {}).get(k) for k in INITIAL} == INITIAL, 'SOURCE_FIELDS')
    return instruments


def receipt_symbols(value, ref, cohort_ref=None):
    m.require(isinstance(value, dict) and value.get('schema') == 'twelve-private-capture-v1'
              and value.get('restored_from_drive') is True
              and all(value.get(flag) is False for flag in FLAGS)
              and value.get('immutable_reader_e2e') is False, 'SOURCE_FIELDS')
    if {k: ref.get(k) for k in INITIAL} == INITIAL:
        m.require(cohort_ref is None or 'collection_scope' not in value, 'SOURCE_FIELDS')
    else:
        m.require(cohort_ref is not None and value.get('collection_scope') == cohort_ref, 'SOURCE_FIELDS')
    evidence = value.get('evidence')
    m.require(isinstance(evidence, list) and 2 <= len(evidence) <= 8, 'SOURCE_FIELDS')
    bases = {}
    for row in evidence:
        m.require(isinstance(row, dict) and row.get('mic') in MICS
                  and row.get('adjustment') in ('none', 'splits'), 'SOURCE_FIELDS')
        pair = (row.get('symbol'), row['mic'])
        query = row.get('request', {})
        m.require(query == dict(symbol=pair[0], mic_code=pair[1], interval='1day', start_date=m.START,
                                end_date=m.END, outputsize=5000, order='asc', adjust=row['adjustment']),
                  'SOURCE_FIELDS')
        m.require(row['adjustment'] not in bases.setdefault(pair, set()), 'SOURCE_FIELDS')
        bases[pair].add(row['adjustment'])
    m.require(all(b == {'none', 'splits'} for b in bases.values()), 'SOURCE_FIELDS')
    return set(bases)


def verify_initial(drive, folders, instruments):
    value = read(drive, INITIAL, folders['06-receipts'])
    done = receipt_symbols(value, INITIAL)
    m.require(done == set(m.SYMBOLS), 'CURRENT_IDENTITY_MISMATCH')
    restore_receipt(drive, folders, value)
    m.require(done <= {(r['symbol'], r['mic']) for r in instruments}, 'CURRENT_IDENTITY_MISMATCH')
    return [dict(symbol=s, mic=mic, receipt=INITIAL) for s, mic in sorted(done)]


def restore_receipt(drive, folders, value):
    bodies = {}
    for field, folder in (('raw_object', '01-provider-raw'), ('normalized_object', '02-normalized')):
        ref = value.get(field, {})
        drive.check(ref.get('file_id'), folders[folder], folder=False)
        raw = drive.read(ref['file_id'])
        m.require(len(raw) == ref.get('bytes') and m.digest(raw) == ref.get('sha256'), 'MEMBER_HASH')
        bodies[field] = raw
    rebuilt, sessions = [], {}
    with zipfile.ZipFile(io.BytesIO(bodies['raw_object'])) as pack:
        expected = {e['member'] for e in value['evidence']} | {'capture.json'}
        m.require(len(pack.namelist()) == len(expected) and set(pack.namelist()) == expected
                  and all(0 < p.file_size <= m.MAX_BYTES for p in pack.infolist())
                  and sum(p.file_size for p in pack.infolist()) <= m.MAX_PACK + m.MAX_BYTES,
                  'PACK_CRC_OR_MEMBERSHIP')
        m.require(pack.testzip() is None, 'PACK_CRC_OR_MEMBERSHIP')
        m.require(m.decode(pack.read('capture.json')) ==
                  dict(evidence=value['evidence'], rights_sha256=value['rights']['sha256']), 'MEMBER_HASH')
        for e in value['evidence']:
            raw = pack.read(e['member'])
            m.require(len(raw) == e['bytes'] and m.digest(raw) == e['sha256'], 'MEMBER_HASH')
            rows = m.rows(m.decode(raw), e['symbol'], e['mic'], e['adjustment'])
            m.require(len(rows) == e['rows'] and rows[0]['date'] == e['first']
                      and rows[-1]['date'] == e['last'], 'RAW_RESTORE_NORMALIZATION')
            sessions.setdefault((e['symbol'], e['mic']), {})[e['adjustment']] = {r['date'] for r in rows}
            rebuilt.extend(rows)
    m.require(all(set(bases) == {'none', 'splits'} and bases['none'] == bases['splits']
                  for bases in sessions.values()), 'RAW_SPLIT_SESSION_MISMATCH')
    with gzip.GzipFile(fileobj=io.BytesIO(bodies['normalized_object'])) as compressed:
        normalized = compressed.read(m.MAX_PACK * 2 + 1)
    m.require(len(normalized) <= m.MAX_PACK * 2 and len(rebuilt) == value.get('rows')
              and b''.join(m.encoded(r) for r in rebuilt) == normalized, 'RAW_RESTORE_NORMALIZATION')


def quarantined_pairs(groups, allowed, completed):
    """A hold identifies an unretained group, never an individual invalid bar."""
    m.require(isinstance(groups, list) and len(groups) <= len(allowed), 'SOURCE_FIELDS')
    pairs = set()
    for group in groups:
        m.require(isinstance(group, dict)
                  and set(group) == {'status', 'reason', 'instruments', 'individual_invalidity_verified',
                                     'original_body_retained', 'code_sha', 'run_id', 'recorded_at', *FLAGS}
                  and group.get('status') == 'GROUP_CAPTURE_BLOCKED_CULPRIT_UNKNOWN'
                  and group.get('reason') == 'BAR_VALUE'
                  and group.get('individual_invalidity_verified') is False
                  and group.get('original_body_retained') is False
                  and all(group.get(flag) is False for flag in FLAGS), 'SOURCE_FIELDS')
        m.require((group['code_sha'] is None or isinstance(group['code_sha'], str)
                   and re.fullmatch(r'[a-f0-9]{40}', group['code_sha']))
                  and (group['run_id'] is None or isinstance(group['run_id'], str)
                       and re.fullmatch(r'[0-9]{1,20}', group['run_id']))
                  and isinstance(group['recorded_at'], str)
                  and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+\+00:00',
                                   group['recorded_at']), 'SOURCE_FIELDS')
        members = group.get('instruments')
        m.require(isinstance(members, list) and 1 <= len(members) <= 4, 'SOURCE_FIELDS')
        for row in members:
            m.require(isinstance(row, dict) and set(row) == {'symbol', 'mic'}
                      and all(isinstance(row[k], str) for k in row), 'SOURCE_FIELDS')
            pair = (row.get('symbol'), row.get('mic'))
            m.require(pair in allowed and pair not in completed and pair not in pairs,
                      'CURRENT_IDENTITY_MISMATCH')
            pairs.add(pair)
    return pairs


def resume_completed(drive, folders, ref, cohort_ref, instruments, with_quarantine=False):
    state = read(drive, ref, folders['05-checkpoints'])
    m.require(state.get('schema') in ('twelve-private-cohort-checkpoint-v1',
                                     'twelve-private-cohort-checkpoint-v2')
              and state.get('collection_scope') == cohort_ref
              and all(state.get(flag) is False for flag in FLAGS), 'SOURCE_FIELDS')
    if state['schema'] == 'twelve-private-cohort-checkpoint-v1':
        m.require('quarantined_groups' not in state, 'SOURCE_FIELDS')
        quarantine = []
    else:
        quarantine = state.get('quarantined_groups')
    completed = state.get('completed')
    m.require(isinstance(completed, list) and len(completed) <= len(instruments), 'SOURCE_FIELDS')
    allowed = {(r['symbol'], r['mic']) for r in instruments}
    pairs, receipts = set(), {}
    for row in completed:
        m.require(isinstance(row, dict), 'SOURCE_FIELDS')
        pair = (row.get('symbol'), row.get('mic'))
        m.require(pair in allowed and pair not in pairs, 'CURRENT_IDENTITY_MISMATCH')
        source = row.get('receipt', {})
        if pair in set(m.SYMBOLS):
            m.require({k: source.get(k) for k in INITIAL} == INITIAL, 'SOURCE_FIELDS')
        cache_key = (source.get('file_id'), source.get('sha256'))
        if cache_key not in receipts:
            value = read(drive, source, folders['06-receipts'])
            receipts[cache_key] = receipt_symbols(value, source, cohort_ref)
            if {k: source.get(k) for k in INITIAL} == INITIAL:
                m.require(receipts[cache_key] == set(m.SYMBOLS), 'CURRENT_IDENTITY_MISMATCH')
            # Verify each receipt and its raw/normalized bodies once per resume.
            restore_receipt(drive, folders, value)
        m.require(pair in receipts[cache_key], 'SOURCE_FIELDS')
        pairs.add(pair)
    for source_pairs in receipts.values():
        m.require(source_pairs <= pairs, 'SOURCE_FIELDS')
    m.require(set(m.SYMBOLS) <= pairs, 'SOURCE_FIELDS')
    m.require((INITIAL['file_id'], INITIAL['sha256']) in receipts, 'SOURCE_FIELDS')
    quarantined_pairs(quarantine, allowed, pairs)
    return (completed, quarantine) if with_quarantine else completed


def collect(drive, folders, key, rights, account, cohort_ref, resume_ref, maximum,
            provider=m.twelve, capture=m.capture, progress=None):
    m.require(type(maximum) is int and 1 <= maximum <= 360, 'SOURCE_FIELDS')
    value = read(drive, cohort_ref, folders['00-control'])
    instruments = scope(value)
    require_capture_identity(cohort_ref)
    completed, quarantine = (resume_completed(drive, folders, resume_ref, cohort_ref, instruments,
                                              with_quarantine=True) if resume_ref
                             else (verify_initial(drive, folders, instruments), []))
    done = {(r['symbol'], r['mic']) for r in completed}
    allowed = {(r['symbol'], r['mic']) for r in instruments}
    held = quarantined_pairs(quarantine, allowed, done)
    pending = [(r['symbol'], r['mic']) for r in instruments
               if (r['symbol'], r['mic']) not in done | held]
    added, raw_objects, latest, reason = 0, 0, resume_ref, None
    progress = progress or (lambda item: print(json.dumps(item, sort_keys=True), flush=True))
    for offset in range(0, min(len(pending), maximum), 4):
        group = pending[offset:min(offset + 4, maximum)]
        _, current = provider('/api_usage', {}, key)
        budget = m.usage(current)
        if budget['plan_daily_limit'] - budget['daily_usage'] - 80 < len(group) * 2:
            reason = 'DAILY_BUDGET'
            break
        # Each group retains the reviewed 16 MiB raw/normalized object limits.
        m.require(drive.free >= 32_000_000, 'DRIVE_SPACE')
        try:
            # The production capture validates all bars before its first upload.
            # Resume/restore validation stays outside this exception boundary.
            out = capture(drive, folders, key, rights, symbols=tuple(group), collection_scope=cohort_ref)
        except m.Refused as exc:
            if str(exc) != 'BAR_VALUE':
                raise
            quarantine.append(dict(status='GROUP_CAPTURE_BLOCKED_CULPRIT_UNKNOWN', reason='BAR_VALUE',
                instruments=[dict(symbol=s, mic=mic) for s, mic in group],
                individual_invalidity_verified=False, original_body_retained=False,
                code_sha=m.os.environ.get('GITHUB_SHA'), run_id=m.os.environ.get('GITHUB_RUN_ID'),
                recorded_at=m.now(), **{flag: False for flag in FLAGS}))
            held.update(group)
            status = 'COHORT_GROUP_QUARANTINED'
        else:
            completed.extend(dict(symbol=s, mic=mic, receipt=out['receipt']) for s, mic in group)
            added += len(group)
            raw_objects += out['raw_objects']
            status = 'COHORT_GROUP_CAPTURE_RESTORED'
        state = dict(schema='twelve-private-cohort-checkpoint-v2', collection_scope=cohort_ref,
                     completed=completed, quarantined_groups=quarantine, current_identity_only=True,
                     historical_identity_verified=False, pit_verified=False, source_admission=False,
                     economic_authority=False, code_sha=m.os.environ.get('GITHUB_SHA'),
                     run_id=m.os.environ.get('GITHUB_RUN_ID'), recorded_at=m.now())
        latest = drive.write(folders['05-checkpoints'], m.encoded(state), '.json')
        progress(dict(status=status, new_symbols=added,
                      total_completed_symbols=len(completed), checkpoint=latest,
                      quarantined_symbols=len(held),
                      symbols=[s for s, _ in group]))
    remaining = len(instruments) - len(completed)
    return dict(status='COHORT_BATCH_CAPTURE_RESTORED' if added else 'COHORT_BATCH_NO_NEW_CAPTURE',
                collection_scope=cohort_ref, checkpoint=latest, new_symbols=added,
                total_completed_symbols=len(completed), remaining_symbols=remaining,
                pending_symbols=remaining - len(held), quarantined_symbols=len(held),
                quarantined_group_count=len(quarantine),
                quality_status='PARTIAL_WITH_HELD_GROUPS' if held else 'NO_HELD_GROUPS',
                unresolved_symbols=len(value['unresolved']), requested_symbols=len(value['requested_targets']),
                stop_reason=reason, retained_provider_raw_objects=raw_objects,
                full_r1000_collection=False, source_admission=False, pointer_promotion=False,
                economic_authority=False, pit_verified=False, historical_identity_verified=False,
                immutable_reader_e2e=False)

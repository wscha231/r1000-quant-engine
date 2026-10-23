"""A0's non-executable OHLCV request/coverage proposals over sealed evidence.

No collector, scheduler, ledger or authentication service is introduced. Raw
Alpaca archives use the deployed Source verifier. KR normalized caches are not
silently relabeled as raw/split evidence. Calendar/catalog/policy declarations
remain unauthenticated even when their bytes are internally consistent.
"""
from __future__ import annotations

from datetime import date, timedelta
from calendar import monthrange
import gzip
import io
import re

if __package__:
    from . import a2_a1_discovery_gate_v1 as discovery
else:
    import a2_a1_discovery_gate_v1 as discovery

h = discovery.intake
SCHEMA = 'a2-a1-ohlcv-source-inventory-v1'
PARAMETER = 'a2_a1_ohlcv'


def _day(value):
    h.need(type(value) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), 'SESSION_DATE')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise h.IntakeError('SESSION_DATE') from None


def _hash(value):
    h.need(type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value), 'HASH')
    return value


def _json(raw):
    return h.decode(raw, max_entries=10000)


def _calendar(value, country, start, end, cutoff):
    h._fields(value, ('schema', 'country', 'covered_start', 'covered_end_exclusive',
                     'as_of', 'source_url', 'sessions'))
    h.need(value['schema'] == 'a1-ohlcv-session-calendar-v1'
           and value['country'] == country and h.stamp(value['as_of']) <= cutoff,
           'CALENDAR_IDENTITY')
    discovery._url(value['source_url'])
    h.need(_day(value['covered_start']) <= start < end
           <= _day(value['covered_end_exclusive']), 'CALENDAR_WINDOW')
    h.need(type(value['sessions']) is list and len(value['sessions']) <= 10000,
           'CALENDAR_BUDGET')
    days = []
    for row in value['sessions']:
        h._fields(row, ('date', 'close_at'))
        day, close = _day(row['date']), h.stamp(row['close_at'])
        h.need(day.weekday() < 5 and close.date() == day
               and close <= h.stamp(value['as_of']) <= cutoff,
               'CALENDAR_CLOCK')
        h.need(_day(value['covered_start']) <= day < _day(value['covered_end_exclusive']),
               'CALENDAR_ROW_WINDOW')
        days.append(day)
    h.need(days == sorted(set(days)), 'CALENDAR_GRID')
    result = [x for x in days if start <= x < end]
    h.need(bool(result), 'CALENDAR_EMPTY')
    h.need(end == result[-1] + timedelta(days=1), 'CALENDAR_COMPLETED_ENDPOINT')
    return result


def _ranges(missing, expected):
    groups = []
    previous = -2
    for index, day in enumerate(expected):
        if day not in missing:
            continue
        if groups and index == previous + 1:
            groups[-1].append(day)
        else:
            groups.append([day])
        previous = index
    return [dict(start=g[0].isoformat(), end_exclusive=(g[-1]+timedelta(days=1)).isoformat())
            for g in groups]


def _prices(record, candidate, read, artifacts):
    """Verify archived provider rows, not a ticker list or a receipt boolean."""
    if record['state'] == 'UNKNOWN':
        raise h.IntakeError('COVERAGE_UNKNOWN')
    if record['state'] == 'NOT_STORED':
        h.need(record['receipt_ids'] == [], 'ABSENCE_RECEIPT_CONFLICT')
        return {}, [], 'CATALOG_ASSERTION_ONLY', []
    h.need(record['state'] == 'AVAILABLE' and candidate['country'] == 'US',
           'COVERAGE_ADAPTER_NOT_VERIFIED')
    from tools import alpaca_sip_private_backfill_v1 as source
    h.need(0 < len(record['receipt_ids']) <= 32, 'RECEIPT_BUDGET')
    prices, refs, lineage, empty_windows, verified = {}, [], set(), [], set()
    sha_to_ids = {}
    for aid, ref in artifacts.items():
        sha_to_ids.setdefault(ref['sha256'], []).append(aid)
    for aid in record['receipt_ids']:
        receipt_hash = artifacts[aid]['sha256']
        if receipt_hash in verified:
            continue
        receipt = _json(read(aid))
        h.need(receipt.get('schema') == source.SCHEMA
               and receipt.get('source') == source.SOURCE
               and receipt.get('readback_verified') is True
               and receipt.get('source_admission') is False
               and receipt.get('pit_verified') is False
               and receipt.get('historical_identity_verified') is False
               and receipt.get('commercial_use_authorized') is False
               and type(receipt.get('rows')) is int and receipt['rows'] >= 0
               and type(receipt.get('source_sha')) is str
               and re.fullmatch(r'[0-9a-f]{40}', receipt['source_sha'])
               and type(receipt.get('seed_sha256')) is str
               and re.fullmatch(r'[0-9a-f]{64}', receipt['seed_sha256'])
               and candidate['ticker'] in receipt.get('symbols', []), 'PRICE_RECEIPT')
        pair = []
        for role in ('raw_object', 'normalized_object'):
            digest = _hash(receipt[role]['sha256'])
            h.need(digest in sha_to_ids, 'PRICE_OBJECT_MISSING')
            pair.append(read(sha_to_ids[digest][0]))
        try:
            source.verify_archived_group(pair[0], pair[1], receipt)
        except source.Refused:
            raise h.IntakeError('PRICE_ARCHIVE_REFUSED') from None
        verified.add(receipt_hash)
        lineage.add((receipt['source_sha'], receipt['seed_sha256']))
        h.need(len(lineage) == 1, 'PRICE_GENERATION_CONFLICT')
        if candidate['ticker'] in receipt['no_bars']:
            empty_windows.append((_day(receipt['start']), _day(receipt['end'])))
        with gzip.GzipFile(fileobj=io.BytesIO(pair[1]), mode='rb') as handle:
            raw = handle.read(32_000_001)
        h.need(len(raw) <= 32_000_000, 'PRICE_DECOMPRESSED_LIMIT')
        for line in raw.splitlines():
            row = h.decode(line)
            if row['ticker'] != candidate['ticker']:
                continue
            key = (row['adjustment'], _day(row['date']))
            h.need(key not in prices or prices[key] == row, 'PRICE_ROW_CONFLICT')
            prices[key] = row
        refs.append(artifacts[aid]['sha256'])
    return prices, sorted(set(refs)), 'ARCHIVED_BYTES_REBUILT_NOT_ADMITTED', empty_windows


def build_plan(inventory, memory, *, cutoff):
    h._memory(memory)
    h._fields(inventory, ('schema', 'events_id', 'context_id', 'catalog_id',
        'targets', 'prior_requests_id', 'artifacts'))
    h.need(inventory['schema'] == SCHEMA, 'INVENTORY_SCHEMA')
    refs = inventory['artifacts']
    h.need(type(refs) is dict and len(refs) <= 128, 'ARTIFACT_COUNT')
    def read(aid):
        h.identifier(aid)
        h.need(aid in refs, 'ARTIFACT_REFERENCE')
        return memory.read(aid, _hash(refs[aid]['sha256']))
    selection = discovery.select_discovery(read(inventory['events_id']),
        read(inventory['context_id']), cutoff=cutoff, artifact_resolver=memory)
    context = _json(read(inventory['context_id']))
    identities = {x['security_id']: x for x in context['identities']}
    catalog = _json(read(inventory['catalog_id']))
    h._fields(catalog, ('schema', 'as_of', 'securities'))
    h.need(catalog['schema'] == 'a1-ohlcv-catalog-snapshot-v1'
           and h.stamp(catalog['as_of']) <= h.stamp(cutoff), 'CATALOG_CLOCK')
    h.need(type(catalog['securities']) is list and len(catalog['securities']) <= 1000,
           'CATALOG_BUDGET')
    records = {}
    for row in catalog['securities']:
        h._fields(row, ('security_id', 'state', 'receipt_ids'))
        sid = h.identifier(row['security_id'])
        h.need(sid not in records and row['state'] in {'AVAILABLE', 'NOT_STORED', 'UNKNOWN'},
               'CATALOG_CONFLICT')
        discovery._strings(row['receipt_ids'], 'RECEIPT_IDS', 32)
        records[sid] = row
    h.need(type(inventory['targets']) is list and len(inventory['targets']) <= 30,
           'TARGET_BUDGET')
    targets = {}
    for target in inventory['targets']:
        h._fields(target, ('security_id', 'start', 'end_exclusive', 'calendar_id', 'policy_id'))
        sid = h.identifier(target['security_id'])
        h.need(sid not in targets, 'TARGET_CONFLICT'); targets[sid] = target
    prior = {}
    if inventory['prior_requests_id'] is not None:
        old = _json(read(inventory['prior_requests_id']))
        h._fields(old, ('schema', 'as_of', 'requests'))
        h.need(old['schema'] == 'a0-ohlcv-request-snapshot-v1'
               and h.stamp(old['as_of']) <= h.stamp(cutoff), 'PRIOR_REQUEST_CLOCK')
        h.need(type(old['requests']) is list and len(old['requests']) <= 1000, 'PRIOR_BUDGET')
        for row in old['requests']:
            h._fields(row, ('request_id', 'status'))
            key = _hash(row['request_id'])
            h.need(key not in prior and row['status'] in
                   {'PENDING', 'RUNNING', 'COMPLETE', 'FAILED', 'UNKNOWN'}, 'PRIOR_CONFLICT')
            prior[key] = row['status']
    requests, results, candidates = [], [], {}
    for item in selection['candidates']:
        candidates.setdefault(item['security_id'], []).append(item)
    for sid, events in sorted(candidates.items()):
        first = events[0]
        result = dict(schema='A1_OHLCV_COVERAGE_RESULT', security_id=sid,
            status='PLANNED_ONLY', coverage_action='BLOCKED', consumer_eligible=False,
            source_authentication='NOT_VERIFIED', identity_authentication='NOT_VERIFIED',
            calendar_authentication='NOT_VERIFIED', authority=h.closed())
        try:
            h.need(sid in targets and sid in records, 'TARGET_OR_COVERAGE_MISSING')
            target = targets[sid]
            end = _day(target['end_exclusive'])
            default = end.replace(year=end.year-10,
                day=min(end.day, monthrange(end.year-10, end.month)[1]))
            start = _day(target['start']) if target['start'] is not None else default
            start = max(start, h.stamp(identities[sid]['valid_from']).date())
            h.need(start < end <= h.stamp(cutoff).date()+timedelta(days=1), 'REQUEST_WINDOW')
            expected = _calendar(_json(read(target['calendar_id'])), first['country'],
                                 start, end, h.stamp(cutoff))
            prices, receipt_hashes, evidence, empty_windows = _prices(records[sid], first, read, refs)
            raw_days = {day for basis, day in prices if basis == 'raw'}
            split_days = {day for basis, day in prices if basis == 'split'}
            h.need(raw_days == split_days, 'PRICE_BASIS_GRID')
            h.need({x for x in raw_days if start <= x < end} <= set(expected),
                   'SOURCE_CALENDAR_CONFLICT')
            covered = set(expected) & raw_days
            missing = set(expected) - covered
            if not prices and any(left <= start < end <= right for left, right in empty_windows):
                action = 'NO_DATA'
            elif not missing:
                action = 'REUSE_EXISTING'
            elif covered and covered == set(expected[:len(covered)]):
                action = 'INCREMENTAL_ONLY'
            else:
                action = 'BACKFILL_REQUIRED'
            policy = None
            if target['policy_id'] is not None:
                policy = _json(read(target['policy_id']))
                h._fields(policy, ('schema', 'campaign_key', 'provider', 'feed',
                    'authorization_sha256', 'usage_evidence_sha256', 'scope_start',
                    'scope_end_exclusive', 'remaining_provider_gets'))
                h.need(policy['schema'] == 'a1-ohlcv-request-policy-v1', 'POLICY_SCHEMA')
                for field in ('campaign_key', 'provider', 'feed'): h.identifier(policy[field])
                h.need((first['country'] == 'US' and policy['provider'] ==
                        'ALPACA_STOCK_BARS_V2_HISTORICAL_SIP' and policy['feed'] == 'sip')
                       or (first['country'] == 'KR' and policy['provider'] ==
                        'KR_PYKRX_EXISTING_CLIENT' and policy['feed'] == 'KRX'), 'POLICY_SOURCE')
                for field in ('authorization_sha256', 'usage_evidence_sha256'):
                    if policy[field] is not None: _hash(policy[field])
                h.need(type(policy['remaining_provider_gets']) is int
                       and 0 <= policy['remaining_provider_gets'] <= 1000000, 'POLICY_BUDGET')
                h.need(_day(policy['scope_start']) <= start < end
                       <= _day(policy['scope_end_exclusive']), 'POLICY_WINDOW')
            identity = {k: identities[sid][k] for k in discovery.IDENTITY_FIELDS[:6]}
            key = h.digest(h.canonical(dict(identity=identity, start=start.isoformat(),
                end_exclusive=end.isoformat(), adjustments=['raw', 'split'],
                provider=policy['provider'] if policy else None,
                feed=policy['feed'] if policy else None,
                campaign_key=policy['campaign_key'] if policy else None,
                authorization_sha256=policy['authorization_sha256'] if policy else None)))
            blockers = ['A0_AUTHENTICATED_EVENT_IDENTITY_REQUIRED',
                'SOURCE_RIGHTS_CALENDAR_CA_PIT_REVIEW_REQUIRED']
            if policy is None or policy['authorization_sha256'] is None:
                blockers.append('AUTHORIZED_CAPTURE_SCOPE_REQUIRED')
            if policy is None or policy['usage_evidence_sha256'] is None:
                blockers.append('ACTUAL_REMAINING_BUDGET_REQUIRED')
            lower_bound = (0 if not missing or action == 'NO_DATA' else
                1 + 2*((len(missing)+9999)//10000)) if first['country'] == 'US' else None
            if policy is not None and lower_bound is not None and lower_bound > policy['remaining_provider_gets']:
                blockers.append('PROVIDER_BUDGET_INSUFFICIENT_LOWER_BOUND')
            if key in prior:
                blockers.append('PRIOR_REQUEST_' + prior[key] + '_RECONCILE_REQUIRED')
            result.update(coverage_action=action, expected_sessions=len(expected),
                covered_sessions=len(covered), missing_sessions=sorted(x.isoformat() for x in missing),
                missing_ranges=_ranges(missing, expected), receipt_sha256s=receipt_hashes,
                coverage_evidence=evidence, request_id=key, blockers=blockers)
            if key not in prior and action != 'NO_DATA':
                requests.append(dict(schema='A2_TO_A1_OHLCV_REQUEST', request_id=key,
                    assigned_by='A0', return_to='A0', mode='DRY_RUN', identity=identity,
                    source_event_keys=sorted(x['event_key'] for x in events),
                    event_sources=[{k: e[k] for k in ('original_url', 'source_sha256',
                        'published_at', 'available_at', 'collected_at', 'materiality_basis')}
                        for e in events], priority='HIGH' if any(e['materiality']=='HIGH' for e in events) else 'MEDIUM',
                    action=action, start=start.isoformat(), end_exclusive=end.isoformat(),
                    missing_ranges=result['missing_ranges'], policy=policy,
                    minimum_provider_gets_estimate=lower_bound, ready_for_collection=False,
                    blockers=blockers, authority=h.closed()))
        except h.IntakeError as exc:
            result.update(status='BLOCKED', blockers=[str(exc)])
        except (KeyError, TypeError, ValueError, OSError, EOFError):
            # Never echo private archive content, file IDs, URLs or provider diagnostics.
            result.update(status='BLOCKED', blockers=['OHLCV_INPUT_PROOF_REQUIRED'])
        results.append(result)
    return dict(schema='a0-a1-ohlcv-proposals-v1', mode='DRY_RUN', requests=requests,
        coverage_results=results, discovery_other_events=selection['other_events'],
        canonical_write_performed=False, dispatch_count=0, authority=h.closed())

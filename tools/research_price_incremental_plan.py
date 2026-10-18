"""Bounded supplied-byte daily-close gap and research-delta planning; no I/O."""
from __future__ import annotations

from datetime import date
import math

from research import a2_research_intake_v1 as intake

SCHEMA = 'research-price-incremental-plan-v1'
IDENTITY = ('security_id', 'issuer_id', 'provider_security_id', 'mic', 'calendar_id', 'country', 'currency')
SCOPE = ('identity', 'provider', 'feed', 'adjustment', 'window')
CLOCK = ('observed_at', 'available_at', 'collected_at')


class PricePlanError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise PricePlanError(reason)


def fields(value, names):
    need(type(value) is dict and set(value) == set(names), 'FIELDS')


def day(value):
    need(type(value) is str, 'DATE')
    try:
        need(date.fromisoformat(value).isoformat() == value, 'DATE')
    except ValueError:
        raise PricePlanError('DATE') from None
    return value


def clock(value, cutoff):
    times = tuple(intake.stamp(value[k]) for k in CLOCK)
    need(times[0] <= times[1] <= times[2] <= cutoff, 'CLOCK_OR_FUTURE')
    return times


def window(value):
    fields(value, ('start', 'end_exclusive'))
    need(day(value['start']) < day(value['end_exclusive']), 'WINDOW')


def identity(value):
    fields(value, IDENTITY)
    for k in IDENTITY:
        intake.identifier(value[k])
    need(value['country'] == 'US' and value['currency'] == 'USD', 'US_USD_REQUIRED')


def scope(value):
    identity(value['identity'])
    for k in ('provider', 'feed', 'adjustment'):
        intake.identifier(value[k])
    need(value['adjustment'] in ('raw', 'split'), 'ADJUSTMENT')
    window(value['window'])


def read_blob(memory, sha):
    # MemoryArtifacts enforces immutable bounded bytes; no arbitrary resolver.
    need(type(memory) is intake.MemoryArtifacts, 'MEMORY_REQUIRED')
    need(type(sha) is str and len(sha) == 64 and all(c in '0123456789abcdef' for c in sha), 'HASH')
    return memory.read('SHA256:' + sha, sha)


def read_json(memory, sha):
    return intake.decode(read_blob(memory, sha), max_entries=10000)


def scope_matches(value, subject):
    scope(value)
    need(value['identity'] == subject['identity'], 'IDENTITY_MISMATCH')
    need(all(value[k] == subject[k] for k in SCOPE if k != 'identity'), 'SCOPE_MISMATCH')


def calendar_for(subject, memory, cutoff):
    cal = read_json(memory, subject['calendar_sha256'])
    fields(cal, ('schema', 'mic', 'calendar_id', 'country', 'currency', 'coverage', 'sessions', *CLOCK))
    need(cal['schema'] == 'supplied-price-session-calendar-v1', 'CALENDAR_SCHEMA')
    for k in ('mic', 'calendar_id', 'country', 'currency'):
        need(cal[k] == subject['identity'][k], 'CALENDAR_IDENTITY')
    clock(cal, cutoff); window(cal['coverage'])
    w = subject['window']
    need(cal['coverage']['start'] <= w['start'] and w['end_exclusive'] <= cal['coverage']['end_exclusive'], 'CALENDAR_COVERAGE')
    need(type(cal['sessions']) is list and len(cal['sessions']) <= 10000, 'CALENDAR_BUDGET')
    out = {}; previous = None; previous_close = None
    for row in cal['sessions']:
        fields(row, ('session', 'close_at'))
        d, close = day(row['session']), intake.stamp(row['close_at'])
        need(cal['coverage']['start'] <= d < cal['coverage']['end_exclusive'], 'CALENDAR_SESSION')
        need(close.date().isoformat() == d, 'CALENDAR_CLOSE_DATE')
        need(previous is None or (previous < d and previous_close < close), 'CALENDAR_ORDER')
        previous, previous_close = d, close
        if w['start'] <= d < w['end_exclusive']:
            out[d] = close
    return out


def prices(sha, subject, memory, sessions, cutoff):
    value = read_json(memory, sha)
    fields(value, ('schema', *SCOPE, *CLOCK, 'expires_at', 'bars'))
    need(value['schema'] == 'supplied-daily-close-inventory-v1', 'PRICE_SCHEMA')
    scope_matches(value, subject)
    outer = clock(value, cutoff)
    need(intake.stamp(value['expires_at']) > outer[2], 'PRICE_EXPIRY')
    need(type(value['bars']) is list and len(value['bars']) <= 10000, 'PRICE_BUDGET')
    bars = {}; previous = None
    for bar in value['bars']:
        fields(bar, ('session', 'close', *CLOCK))
        d = day(bar['session'])
        need(previous is None or previous < d, 'DUPLICATE_OR_UNORDERED_SESSION')
        previous = d
        need(d in sessions, 'PRICE_OUTSIDE_CALENDAR_WINDOW')
        times = clock(bar, cutoff)
        need(sessions[d] <= times[0] and all(a <= b for a, b in zip(times, outer)), 'PRICE_CLOSE_CLOCK')
        v = bar['close']
        need(type(v) in (int, float) and math.isfinite(v) and v > 0, 'PRICE_NUMBER')
        bars[d] = v
    return value, bars


def _close_ratio(value):
    # Exact stored-number equality; never round an integer through float.
    need(type(value) in (int, float) and math.isfinite(value) and value > 0, 'PRICE_NUMBER')
    numerator, denominator = value.as_integer_ratio()
    return [str(numerator), str(denominator)]


def price_fingerprint(value):
    """Clock-only recollection is not a changed economic price observation."""
    return intake.digest(intake.canonical({
        **{k: value[k] for k in SCOPE},
        'numeric_encoding': 'exact-integer-ratio-v1',
        'bars': [{'session': b['session'], 'close': _close_ratio(b['close'])} for b in value['bars']],
    }))


def check_transition(before, after):
    """An older capture or conflicting same-clock vintage cannot replace truth."""
    need(all(intake.stamp(before[k]) <= intake.stamp(after[k]) for k in CLOCK), 'PRICE_TIME_REGRESSION')
    old = {bar['session']: bar for bar in before['bars']}
    for bar in after['bars']:
        prior = old.get(bar['session'])
        if prior is None:
            continue
        need(all(intake.stamp(prior[k]) <= intake.stamp(bar[k]) for k in CLOCK), 'PRICE_TIME_REGRESSION')
        same_clocks = all(intake.stamp(prior[k]) == intake.stamp(bar[k]) for k in CLOCK)
        need(not same_clocks or prior['close'] == bar['close'], 'CONFLICTING_PRICE_VINTAGE')


def failure_for(subject, memory, cutoff):
    sha = subject['failure_sha256']
    if sha is None:
        return False
    failure = read_json(memory, sha)
    fields(failure, ('schema', *SCOPE, *CLOCK))
    need(failure['schema'] == 'supplied-price-source-failure-v1', 'FAILURE_SCHEMA')
    scope_matches(failure, subject); clock(failure, cutoff)
    return True


def delta_for(subject, memory, before, after, *, cutoff, failure):
    refs = subject['delta']
    if refs is None:
        return {'status': 'BLOCKED', 'reason': 'SUPPLIED_RESEARCH_DELTA_CONTEXT_REQUIRED', 'result': None}
    fields(refs, ('previous_sha256', 'current_sha256'))
    need(after is not None, 'DELTA_CURRENT_PRICE_REQUIRED')
    current_raw = read_blob(memory, refs['current_sha256'])
    current = intake.decode(current_raw)
    need(type(current.get('fingerprints')) is dict and type(current.get('exceptions')) is dict, 'DELTA_CONTEXT')
    # No fabricated source/model/accounting fingerprints or research expiry.
    for k in ('security_id', 'issuer_id'):
        need(current.get(k) == subject['identity'][k], 'DELTA_IDENTITY')
    need(current.get('fingerprints', {}).get('market_price') == price_fingerprint(after), 'DELTA_PRICE_HASH')
    need(current.get('expires_at') == after['expires_at'], 'DELTA_EXPIRY')
    need(not failure or current.get('exceptions', {}).get('source_failure') is True, 'DELTA_FAILURE_EXCEPTION')
    previous_raw = None
    if refs['previous_sha256'] is not None:
        need(before is not None, 'DELTA_BEFORE_PRICE_REQUIRED')
        previous_raw = read_blob(memory, refs['previous_sha256'])
        prior = intake.decode(previous_raw)
        need(type(prior.get('fingerprints')) is dict, 'DELTA_CONTEXT')
        for k in ('security_id', 'issuer_id'):
            need(prior.get(k) == subject['identity'][k], 'DELTA_IDENTITY')
        need(prior.get('fingerprints', {}).get('market_price') == price_fingerprint(before), 'DELTA_PRIOR_PRICE_HASH')
        need(prior.get('expires_at') == before['expires_at'], 'DELTA_PRIOR_EXPIRY')
        need(all(prior.get('fingerprints', {}).get(k) == current.get('fingerprints', {}).get(k)
                 for k in intake.FINGERPRINTS if k != 'market_price'), 'PRICE_ONLY_DELTA_SCOPE')
    else:
        need(before is None, 'DELTA_PRIOR_CONTEXT_REQUIRED')
    result = intake.plan_delta(previous_raw, current_raw, cutoff=cutoff)
    return {'status': 'LOCAL_REVIEW_PLAN_ONLY', 'reason': None, 'result': result}


def plan_incremental(inventory_raw, inventory_sha256, *, artifact_resolver, cutoff):
    """Return independent per-subject plans, never fetch, persist or dispatch.

    Calendar bytes claim complete listed-session coverage; their source authority
    is NOT authenticated here. A hash proves supplied-byte consistency only.
    """
    need(type(artifact_resolver) is intake.MemoryArtifacts, 'MEMORY_REQUIRED')
    intake.stamp(cutoff)
    need(type(inventory_raw) is bytes and intake.digest(inventory_raw) == inventory_sha256, 'INVENTORY_HASH')
    inventory = intake.decode(inventory_raw, max_entries=1000)
    fields(inventory, ('schema', *CLOCK, 'subjects'))
    need(inventory['schema'] == 'supplied-price-incremental-inventory-v1', 'INVENTORY_SCHEMA')
    limit = intake.stamp(cutoff); inventory_seen = clock(inventory, limit)[2]
    need(type(inventory['subjects']) is list and len(inventory['subjects']) <= 1000, 'SUBJECT_BUDGET')
    ids = set(); scopes = set(); results = []
    for subject in inventory['subjects']:
        need(type(subject) is dict, 'SUBJECT')
        rid = intake.identifier(subject.get('request_id'))
        need(rid not in ids, 'DUPLICATE_REQUEST'); ids.add(rid)
        row = dict(request_id=rid, status='BLOCKED', reason=None, expected_sessions=None,
                   reusable_sessions=[], reusable_sources={}, missing_sessions=None, collection_plan=None,
                   delta={'status': 'BLOCKED', 'reason': 'PRICE_PREREQUISITES', 'result': None})
        try:
            fields(subject, ('request_id', *SCOPE, 'calendar_sha256', 'prior_sha256', 'current_sha256', 'failure_sha256', 'delta'))
            scope(subject)
            key = intake.digest(intake.canonical({k: subject[k] for k in SCOPE}))
            need(key not in scopes, 'DUPLICATE_SCOPE'); scopes.add(key)
            sessions = calendar_for(subject, artifact_resolver, inventory_seen)
            expected = [d for d, close in sessions.items() if close <= limit]
            need(expected, 'NO_CLOSED_SESSION')
            failure = failure_for(subject, artifact_resolver, inventory_seen)
            current, bars = (None, {}) if subject['current_sha256'] is None else prices(subject['current_sha256'], subject, artifact_resolver, sessions, inventory_seen)
            before = None; prior_bars = {}
            if subject['prior_sha256'] is not None:
                before, prior_bars = prices(subject['prior_sha256'], subject, artifact_resolver, sessions, inventory_seen)
                if current is not None:
                    check_transition(before, current)
            reusable = {d: subject['prior_sha256'] for d in prior_bars}
            reusable.update({d: subject['current_sha256'] for d in bars})
            missing = sorted(set(expected) - reusable.keys())
            used = {sha for sha in reusable.values()}
            expired = any(v is not None and source_sha in used and intake.stamp(v['expires_at']) <= limit
                          for source_sha, v in ((subject['prior_sha256'], before), (subject['current_sha256'], current)))
            status = 'BLOCKED' if failure else 'MISSING' if not reusable else 'STALE' if missing or expired else 'FRESH'
            row.update(status=status, reason='SOURCE_FAILURE' if failure else 'MISSING_SESSIONS' if missing else 'SOURCE_EXPIRED' if expired else None,
                       expected_sessions=expected, reusable_sessions=sorted(reusable), reusable_sources=reusable, missing_sessions=missing,
                       collection_plan={'scope': {k: subject[k] for k in SCOPE}, 'sessions': missing,
                                        'calendar_sha256': subject['calendar_sha256'], 'execute': False})
            # Data gaps block this review stage, without erasing the gap plan.
            if not missing and current is not None and set(expected) <= bars.keys():
                try:
                    row['delta'] = delta_for(subject, artifact_resolver, before, current, cutoff=cutoff, failure=failure)
                except (PricePlanError, intake.IntakeError) as exc:
                    row['delta'] = {'status': 'BLOCKED', 'reason': str(exc), 'result': None}
            elif not missing:
                row['delta']['reason'] = 'CURRENT_PRICE_SNAPSHOT_INCOMPLETE_FOR_DELTA'
        except (PricePlanError, intake.IntakeError) as exc:
            row['reason'] = str(exc)
            if str(exc) in {'IDENTITY_MISMATCH', 'SCOPE_MISMATCH', 'DUPLICATE_OR_UNORDERED_SESSION', 'PRICE_NUMBER', 'CLOCK_OR_FUTURE', 'PRICE_CLOSE_CLOCK', 'PRICE_TIME_REGRESSION', 'CONFLICTING_PRICE_VINTAGE'}:
                row['status'] = 'CONFLICTING'
        results.append(row)
    return {'schema': SCHEMA, 'inventory_sha256': inventory_sha256, 'cutoff': cutoff,
            'status': 'LOCAL_PLAN_ONLY', 'rows': results, 'authority': intake.closed(),
            'identity_authentication': 'NOT_VERIFIED', 'source_authenticated': False,
            'validated_er': None, 'orders': None}

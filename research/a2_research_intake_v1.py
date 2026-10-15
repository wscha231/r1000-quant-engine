"""Pure US research intake proposals. No current-pointer or economic authority.

Only bounded bytes already held by MemoryArtifacts may be resolved. Schema
bytes are exact reviewed dependencies supplied by the caller, never file reads.
Caller identities and review labels are assertions, not authenticated admission.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import math
import re
from types import MappingProxyType

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry
from referencing.exceptions import NoSuchResource

if __package__:
    from . import a3_candidate_packet_v1 as a3
    from . import candidate_registry_v1 as registry
else:
    import a3_candidate_packet_v1 as a3
    import candidate_registry_v1 as registry

MAX_BYTES = 4 * 1024 * 1024
MAX_DEPTH = 32
MAX_TOKENS = 50000
MAX_ARTIFACTS = 10000
MAX_TOTAL_BYTES = 32 * 1024 * 1024
FLAGS = tuple('selector er target portfolio paper broker orders promotion execute production dispatch admission ledger canonical_write learning'.split())
HORIZONS = ('1D', '1W', '2W', '1M', '3M', '6M', '12M')
SCHEMAS = {
    'events': ('a2_event_handoff_v1.schema.json', 'd3ab9835538ddb5058be66603a27b21b906d4a6dc63141bc000eeb9f4aa67214'),
    'queue': ('candidate_data_queue_v1.schema.json', 'c5d144b510144670008c6b883a6fbda17d115b8f33634251d10867647a561df5'),
    'cohort': ('matured_outcome_cohort_v1.schema.json', 'ef739e847145987e55e78b56f346da5237d64af459e79c2b682c55b917003f02'),
}
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,199}\Z')
_HASH = re.compile(r'[0-9a-f]{64}\Z')


class IntakeError(ValueError):
    """Bounded contract refusal; no provider text or secret-bearing details."""


def need(ok, reason):
    if not ok:
        raise IntakeError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def closed():
    return {key: False for key in FLAGS}


def identifier(value):
    need(type(value) is str and _ID.fullmatch(value) is not None, 'IDENTIFIER')
    return value


def stamp(value):
    try:
        return registry._stamp(value)
    except (ValueError, TypeError):
        raise IntakeError('TIMESTAMP') from None


def _fields(value, fields):
    need(type(value) is dict and set(value) == set(fields), 'FIELDS')


def decode(raw):
    """Bound bytes and lexical structure before allocating the JSON tree.

    Tokens include object keys and containers: intentionally stricter than
    A3's post-decode value-node budget. Escaped quotes do not add depth/tokens.
    """
    need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'BYTE_BUDGET')
    depth = tokens = 0
    string = escaped = scalar = False
    for ch in raw:
        if string:
            if escaped:
                escaped = False
            elif ch == 92:
                escaped = True
            elif ch == 34:
                string = False
            continue
        if ch == 34:
            string = True
            scalar = False
            tokens += 1
        elif ch in (123, 91):
            depth += 1
            tokens += 1
            scalar = False
        elif ch in (125, 93):
            depth -= 1
            scalar = False
            need(depth >= 0, 'JSON_STRUCTURE')
        elif ch in (44, 58, 9, 10, 13, 32):
            scalar = False
        elif not scalar:
            tokens += 1
            scalar = True
        need(depth <= MAX_DEPTH, 'DEPTH_BUDGET')
        need(tokens <= MAX_TOKENS, 'TOKEN_BUDGET')
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, 'DUPLICATE_KEY')
            result[key] = value
        return result
    def number(value):
        out = float(value)
        need(math.isfinite(out), 'FINITE_NUMBER')
        return out
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_float=number,
                           parse_constant=lambda x: (_ for _ in ()).throw(IntakeError('FINITE_NUMBER')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, IntakeError):
            raise
        raise IntakeError('JSON') from None
    need(type(value) is dict, 'OBJECT')
    return value


class MemoryArtifacts:
    """Sealed bounded byte inventory, never an arbitrary callback or fetcher."""
    __slots__ = ('_values',)

    def __init__(self, values):
        need(type(values) is dict and len(values) <= MAX_ARTIFACTS, 'ARTIFACT_COUNT')
        total = 0
        for key, raw in values.items():
            identifier(key)
            need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'ARTIFACT_BYTES')
            total += len(raw)
            need(total <= MAX_TOTAL_BYTES, 'ARTIFACT_TOTAL_BUDGET')
        object.__setattr__(self, '_values', MappingProxyType(dict(values)))

    def __setattr__(self, name, value):
        raise IntakeError('MEMORY_INVENTORY_SEALED')

    def read(self, aid, sha):
        identifier(aid)
        need(type(sha) is str and _HASH.fullmatch(sha) is not None, 'HASH')
        raw = self._values.get(aid)
        need(raw is not None, 'ARTIFACT_MISSING')
        need(digest(raw) == sha, 'ARTIFACT_HASH')
        return raw


def _memory(value):
    need(type(value) is MemoryArtifacts, 'MEMORY_RESOLVER_REQUIRED')
    return value


def _no_resource(uri):
    raise NoSuchResource(ref=uri)


def _typed(kind, raw, memory):
    name, sha = SCHEMAS[kind]
    schema = decode(memory.read('SCHEMA:' + name, sha))
    value = decode(raw)
    validator = Draft202012Validator(schema, format_checker=FormatChecker(),
                                    registry=Registry(retrieve=_no_resource))
    need(next(validator.iter_errors(value), None) is None, 'SCHEMA_FIELDS_OR_TYPES')
    return value


def _identities(raw):
    value = decode(raw)
    _fields(value, ('scope', 'rows'))
    need(value['scope'] == 'SUPPLIED_US_IDENTITY_ASSERTIONS', 'IDENTITY_SCOPE')
    need(type(value['rows']) is list and len(value['rows']) <= 10000, 'IDENTITY_COUNT')
    out = {}
    for row in value['rows']:
        _fields(row, ('security_id', 'issuer_id', 'tickers', 'country', 'currency'))
        sid, issuer = identifier(row['security_id']), identifier(row['issuer_id'])
        need(sid not in out, 'DUPLICATE_SECURITY')
        need(row['country'] == 'US' and row['currency'] == 'USD', 'US_USD_REQUIRED')
        tickers = row['tickers']
        need(type(tickers) is list and 0 < len(tickers) <= 100, 'TICKER_MAPPING')
        need(len(tickers) == len(set(identifier(x) for x in tickers)), 'TICKER_MAPPING')
        out[sid] = (issuer, frozenset(tickers))
    return out


def _subject(sid, issuer, ticker, identities):
    identifier(sid); identifier(issuer); identifier(ticker)
    need(sid in identities and identities[sid][0] == issuer
         and ticker in identities[sid][1], 'IDENTITY_MAPPING')


def _reference(ref, cutoff, memory, *, unexpired=True):
    _fields(ref, ('artifact_id', 'sha256', 'available_at', 'collected_at', 'expires_at'))
    available, collected = stamp(ref['available_at']), stamp(ref['collected_at'])
    need(available <= collected <= cutoff, 'REFERENCE_CLOCK')
    expiry = ref['expires_at']
    if expiry is not None:
        need(stamp(expiry) >= collected, 'REFERENCE_EXPIRY')
    if unexpired:
        need(expiry is not None and stamp(expiry) > cutoff, 'REFERENCE_NOT_CURRENT')
    return memory.read(ref['artifact_id'], ref['sha256'])


def _proposal(kind, raw, **values):
    return {'schema': 'a2-a8-research-intake-v1-result', 'kind': kind,
            'status': 'VALID_RESEARCH_PROPOSAL', 'scope': 'SUPPLIED_BYTES_ONLY',
            'input_sha256': digest(raw), 'identity_authentication': 'NOT_VERIFIED',
            'review_authentication': 'NOT_VERIFIED', 'canonical_verified': False,
            'A5_eligible_input': False, 'authority': closed(), **values}


def _graph(event, memory):
    aid, sha = event['source_graph_artifact_id'], event['source_graph_sha256']
    need((aid is None) == (sha is None), 'GRAPH_REFERENCE')
    if event['verification_level'] == 'V0':
        need(not event['assessment_eligible'] and event['verified_fact'] is None, 'V0_DISCOVERY_ONLY')
        need(event['state'] in {'DISCOVERED', 'WATCH', 'REJECTED', 'STALE', 'BLOCKED'}, 'V0_STATE')
        need(aid is None, 'V0_GRAPH_NOT_ASSESSMENT_REFERENCE')
        return 'DISCOVERY_ONLY'
    need(aid is not None, 'GRAPH_REQUIRED')
    need(event['primary_source'] in a3.SOURCE_GRAPH_TYPES, 'PRIMARY_SOURCE_TYPE')
    graph = decode(memory.read(aid, sha))
    _fields(graph, ('schema', 'asset_id', 'issuer_id', 'review_status', 'research_only', 'as_of', 'sources'))
    need(len(event['security_ids']) == 1 and graph['asset_id'] == event['security_ids'][0]
         and graph['issuer_id'] == event['issuer_ids'][0], 'GRAPH_SUBJECT')
    rows = graph['sources']
    need(type(rows) is list and 0 < len(rows) <= 1000, 'GRAPH_ROWS')
    groups, families, raw_hashes = set(), set(), set()
    for row in rows:
        _fields(row, ('source_id', 'claim_id', 'source_type', 'source_affiliation', 'verification_tier',
                      'independence_group', 'published_at', 'available_at', 'raw_artifact_id', 'raw_sha256',
                      'claim', 'supports_pillars', 'used_for_assessment', 'investment_score_contribution_allowed'))
        if row['used_for_assessment'] is True:
            family = 'ISSUER' if row['source_affiliation'] == 'ISSUER' else row['source_type']
            need(family not in families and row['raw_sha256'] not in raw_hashes, 'MIRROR_NOT_INDEPENDENT')
            groups.add(row['independence_group']); families.add(family); raw_hashes.add(row['raw_sha256'])
    try:
        a3._validate_source_graph(graph, stamp(event['available_at']), memory.read)
    except a3.A3CandidatePacketError:
        raise IntakeError('A3_SOURCE_GRAPH_REFUSED') from None
    return 'GRAPH_BYTES_CONSISTENT_REVIEW_UNAUTHENTICATED'


def validate_events(raw, *, cutoff, artifact_resolver, identities):
    memory = _memory(artifact_resolver)
    value = _typed('events', raw, memory)
    limit = stamp(cutoff)
    as_of = stamp(value['as_of'])
    need(as_of <= limit, 'FUTURE_AS_OF')
    subjects = _identities(identities)
    ids, active, themes, normalized = set(), set(), set(), []
    for event in value['events']:
        eid = identifier(event['event_id'])
        need(eid not in ids, 'DUPLICATE_EVENT'); ids.add(eid)
        for key in ('cohort_id', 'event_family', 'primary_source', 'transmission_channel', 'horizon'):
            identifier(event[key])
        pub, avail, collected = (stamp(event[k]) for k in ('published_at', 'available_at', 'collected_at'))
        observed, expiry = stamp(event['observed_at']), stamp(event['expires_at'])
        need(pub <= avail <= collected <= as_of, 'EVENT_CLOCK')
        need(observed <= collected and expiry >= collected, 'EVENT_OBSERVATION_EXPIRY')
        sids, issuers, tickers = event['security_ids'], event['issuer_ids'], event['tickers']
        need(len(sids) == len(tickers) and set(event['asset_ids']) == set(sids), 'EVENT_SUBJECTS')
        need(set(issuers) == {subjects[s][0] for s in sids if s in subjects}
             and all(s in subjects for s in sids), 'IDENTITY_MAPPING')
        for sid, ticker in zip(sids, tickers):
            _subject(sid, subjects[sid][0], ticker, subjects)
        for key in ('themes', 'industry_ids', 'underlyings', 'affected_pillars'):
            for ident in event[key]: identifier(ident)
        need(set(event['affected_pillars']) <= a3.CANONICAL_PILLARS, 'PILLARS')
        telegram = 'TELEGRAM' in event['primary_source'].upper() or 'COMMUNITY' in event['primary_source'].upper()
        if telegram:
            need(event['assessment_eligible'] is False and event['verified_fact'] is None
                 and event['state'] in {'DISCOVERED', 'WATCH', 'REJECTED', 'STALE', 'BLOCKED'}, 'TELEGRAM_DISCOVERY_ONLY')
        graph_status = _graph(event, memory)
        is_active = expiry > limit and event['state'] not in {'REJECTED', 'STALE', 'BLOCKED'}
        if is_active:
            active.update(sids); themes.update(event['themes'])
        normalized.append({'event': event, 'active': is_active, 'graph_status': graph_status,
                           'subject_key': tuple(sorted((subjects[s][0], s) for s in sids))})
    need(len(active) <= 30, 'ACTIVE_SECURITY_CAP')
    need(len(themes) <= 10, 'ACTIVE_THEME_CAP')
    clusters = []
    latest = {}
    for item in sorted(normalized, key=lambda x: (stamp(x['event']['available_at']), x['event']['event_id'])):
        event = item['event']
        key = (item['subject_key'], event['event_family'])
        t = stamp(event['available_at'])
        group = latest.get(key)
        if group is None or t - group['_anchor'] > timedelta(hours=24):
            group = {'anchor_event_id': event['event_id'], 'event_ids': [], '_anchor': t}
            clusters.append(group); latest[key] = group
        group['event_ids'].append(event['event_id'])
    for group in clusters: del group['_anchor']
    return _proposal('events', raw, clusters=clusters, active_security_count=len(active), active_theme_count=len(themes),
        events=[{'event_id': i['event']['event_id'], 'active': i['active'], 'graph_status': i['graph_status'],
                 'assessment_eligible': False, 'score_contribution': 0, 'include_in_denominator': True,
                 'authority': closed()} for i in sorted(normalized, key=lambda x: x['event']['event_id'])])


def validate_queue(raw, *, cutoff, artifact_resolver, identities):
    memory = _memory(artifact_resolver)
    value = _typed('queue', raw, memory)
    limit, subjects = stamp(cutoff), _identities(identities)
    as_of = stamp(value['as_of']); need(as_of <= limit, 'FUTURE_AS_OF')
    ids = set()
    for item in value['items']:
        sid = item['security_id']
        _subject(sid, item['issuer_id'], item['ticker'], subjects)
        need(item['asset_id'] == sid and sid not in ids, 'DUPLICATE_OR_CONFLICTING_SECURITY'); ids.add(sid)
        need(stamp(item['first_seen_at']) <= stamp(item['last_checked_at']) <= as_of, 'QUEUE_CLOCK')
        need(set(item['required_channels']) == set(item['channel_status']), 'QUEUE_CHANNELS')
        for reason in item['membership_reasons']:
            need(reason['security_id'] == sid and reason['ticker'] in subjects[sid][1], 'REASON_IDENTITY')
            need(stamp(reason['first_seen_at']) <= stamp(reason['last_observed_at']) <= as_of, 'REASON_CLOCK')
            if reason['valid_until']:
                expiry = stamp(reason['valid_until'])
                need(expiry >= stamp(reason['last_observed_at']), 'REASON_EXPIRY')
                need((reason['status'] == 'ACTIVE') == (expiry > limit), 'REASON_EXPIRY_STATE')
            else:
                need(item['state'] == 'DATA_PENDING', 'UNKNOWN_EXPIRY_PENDING')
    return _proposal('queue', raw, items=deepcopy(value['items']), current_selection_status='NOT_VERIFIED',
                     reuse_authorized=False)


def reference_preview(raw, *, cutoff, artifact_resolver):
    memory = _memory(artifact_resolver)
    value = decode(raw); _fields(value, ('entries',))
    if value['entries'] is None:
        return _proposal('references', raw, reference_status='RECONCILE_PENDING', records=[])
    need(type(value['entries']) is list and len(value['entries']) <= 1000, 'REFERENCE_ENTRIES')
    try:
        result = registry.build_reference_index(value['entries'], cutoff=cutoff, artifact_resolver=memory.read)
    except registry.ReferenceIndexError:
        raise IntakeError('REFERENCE_SET_REFUSED') from None
    return _proposal('references', raw, reference_index=result)


FINGERPRINTS = tuple('source fundamental methodology market_price earnings_consensus industry regime code config model parameter accounting'.split())
EXCEPTIONS = tuple('expiry catalyst correction source_failure outcome_maturity retraction'.split())


def plan_delta(previous_raw, current_raw, *, cutoff):
    def read(raw):
        value = decode(raw)
        _fields(value, ('security_id', 'issuer_id', 'fingerprints', 'expires_at', 'exceptions', 'research_reuse_ready', 'affected_pillars'))
        identifier(value['security_id']); identifier(value['issuer_id'])
        _fields(value['fingerprints'], FINGERPRINTS)
        for sha in value['fingerprints'].values():
            need(type(sha) is str and _HASH.fullmatch(sha) is not None, 'HASH')
        _fields(value['exceptions'], EXCEPTIONS)
        need(all(type(v) is bool for v in value['exceptions'].values()) and type(value['research_reuse_ready']) is bool, 'BOOLEAN')
        need(type(value['affected_pillars']) is list and set(value['affected_pillars']) <= a3.CANONICAL_PILLARS, 'PILLARS')
        stamp(value['expires_at'])
        return value
    current = read(current_raw)
    limit = stamp(cutoff)
    if previous_raw is None:
        return _proposal('delta', current_raw, plan='RECONCILE_PENDING', refresh=[], execution_permitted=False)
    prior = read(previous_raw)
    changed = {k for k in FINGERPRINTS if prior['fingerprints'][k] != current['fingerprints'][k]}
    integrity = (prior['security_id'], prior['issuer_id']) != (current['security_id'], current['issuer_id']) or bool(changed & {'source', 'accounting'})
    exceptions = {k for k in EXCEPTIONS if current['exceptions'][k] or current['exceptions'][k] != prior['exceptions'][k]}
    if stamp(current['expires_at']) <= limit: exceptions.add('expiry')
    refresh = set()
    if integrity:
        plan, refresh = 'BLOCKED_FULL_A3_REVIEW', {'full_a3_review'}
    else:
        if 'market_price' in changed: refresh.update(('market', 'valuation', 'ER'))
        if changed & {'earnings_consensus', 'fundamental'}: refresh.update(('earnings', 'valuation', 'ER'))
        if changed & {'industry', 'methodology'}: refresh.update(current['affected_pillars'] or ('methodology', 'moat'))
        if 'regime' in changed: refresh.update(('downside', 'portfolio_overlay'))
        if changed & {'code', 'config', 'model', 'parameter'}: refresh.add('dependency_revalidation')
        if exceptions: refresh.add('freshness_catalyst_outcome_review')
        if not current['research_reuse_ready'] or not prior['research_reuse_ready']: refresh.add('reuse_gate_review')
        plan = 'REFRESH_REQUIRED' if refresh else 'SKIP_UNCHANGED'
    return _proposal('delta', current_raw, prior_input_sha256=digest(previous_raw), plan=plan,
                     refresh=sorted(refresh), changed=sorted(changed), exceptions=sorted(exceptions), execution_permitted=False)


def er_preview(ref_raw, *, cutoff, artifact_resolver, security_id, issuer_id, benchmark_id):
    memory = _memory(artifact_resolver)
    for v in (security_id, issuer_id, benchmark_id): identifier(v)
    limit = stamp(cutoff)
    if ref_raw is None:
        return _proposal('ER', b'null', status='BLOCKED_RESEARCH_ONLY', declared_er=None, validated_er=None,
                         blocker='ORIGINAL_NET_WF_REVIEW_IDENTITY_PIT_REQUIRED')
    ref = decode(ref_raw)
    value = decode(_reference(ref, limit, memory))
    expected = {'asset_id', 'issuer_id', 'validation_status', 'benchmark_id', 'net_of_costs', 'unit', 'expected_drawdown', 'downside_probability'}
    expected.update(f'{prefix}{h}' for h in a3.ER_HORIZONS for prefix in ('expected_return_', 'benchmark_expected_return_'))
    _fields(value, expected)
    need(value['asset_id'] == security_id and value['issuer_id'] == issuer_id, 'ER_IDENTITY')
    try:
        declared = a3._validate_validated_er(value, benchmark_id)
    except a3.A3CandidatePacketError:
        raise IntakeError('A3_ER_REFUSED') from None
    return _proposal('ER', ref_raw, status='BLOCKED_RESEARCH_ONLY', declared_er=declared, validated_er=None,
                     blocker='INDEPENDENT_REVIEW_MODEL_CONFIG_DATA_PIT_ADMISSION_REQUIRED')


def validate_cohort(raw, *, cutoff, artifact_resolver, identities):
    memory = _memory(artifact_resolver)
    value = _typed('cohort', raw, memory)
    limit, subjects = stamp(cutoff), _identities(identities)
    generated = stamp(value['generated_at']); need(generated <= limit, 'FUTURE_GENERATED')
    calendar_bytes = _reference(value['calendar_ref'], generated, memory, unexpired=False)
    calendar = decode(calendar_bytes); _fields(calendar, ('schema', 'targets'))
    need(calendar['schema'] == 'h1-supplied-target-calendar-v1' and type(calendar['targets']) is dict, 'CALENDAR_FIELDS')
    for key, target in calendar['targets'].items():
        identifier(key); _fields(target, ('session', 'close_at'))
        need(type(target['session']) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}', target['session']) is not None, 'CALENDAR_SESSION')
        try:
            session_date = date.fromisoformat(target['session'])
        except ValueError:
            raise IntakeError('CALENDAR_SESSION') from None
        need(stamp(target['close_at']).date() == session_date, 'CALENDAR_CLOSE')
    base_fields = ('event_id', 'cohort_id', 'security_id', 'issuer_id', 'asset_id', 'benchmark_id', 'decision_at',
                   'target_calendar_sha256', 'data_manifest_sha256', 'config_sha256', 'model_sha256', 'model_id', 'code_sha256', 'session_clock', 'selection_status')
    outcome_fields = set(base_fields) | {'decision_id', 'horizon', 'target_session', 'asset_return', 'benchmark_return', 'excess_return', 'outcome_session', 'outcome_available_at'}
    outcomes = {}
    if value['outcome_ref'] is not None:
        out = decode(_reference(value['outcome_ref'], generated, memory, unexpired=False))
        _fields(out, ('schema', 'rows')); need(out['schema'] == 'h1-supplied-outcomes-v1' and type(out['rows']) is list, 'OUTCOME_FIELDS')
        need(len(out['rows']) <= 1000, 'OUTCOME_COUNT')
        for row in out['rows']:
            _fields(row, outcome_fields)
            key = identifier(row['decision_id']) + ':' + identifier(row['horizon'])
            need(key not in outcomes, 'DUPLICATE_OUTCOME'); outcomes[key] = row
    keys, groups, matured = set(), {}, 0
    for row in value['rows']:
        for k in ('event_id', 'cohort_id', 'security_id', 'issuer_id', 'asset_id', 'benchmark_id', 'decision_id', 'model_id'):
            identifier(row[k])
        sid = row['security_id']
        need(sid in subjects and subjects[sid][0] == row['issuer_id'] and row['asset_id'] == sid, 'COHORT_IDENTITY')
        need(row['target_calendar_sha256'] == digest(calendar_bytes), 'CALENDAR_HASH')
        decision = stamp(row['decision_at']); need(decision <= generated, 'DECISION_CLOCK')
        key = row['decision_id'] + ':' + row['horizon']
        need(key not in keys, 'DUPLICATE_HORIZON'); keys.add(key)
        target = calendar['targets'].get(key)
        need(target is not None and target['session'] == row['target_session'], 'EXACT_TARGET_SESSION')
        need(date.fromisoformat(row['target_session']) > decision.date(), 'TARGET_AFTER_DECISION')
        group = groups.setdefault(row['decision_id'], {'base': tuple(row[k] for k in base_fields), 'horizons': set()})
        need(group['base'] == tuple(row[k] for k in base_fields), 'COHORT_BINDINGS')
        group['horizons'].add(row['horizon'])
        if row['status'] == 'MATURED':
            need(value['outcome_ref'] is not None and row['source_sha256'] == value['outcome_ref']['sha256'], 'OUTCOME_HASH')
            outcome = outcomes.get(key)
            need(outcome is not None, 'OUTCOME_MISSING'); _fields(outcome, outcome_fields)
            need(all(canonical(outcome[k]) == canonical(row[k]) for k in outcome_fields), 'OUTCOME_BINDINGS')
            need(row['outcome_session'] == row['target_session'], 'LATE_SESSION_SUBSTITUTION')
            need(row['outcome_available_at'] is not None and decision < stamp(row['outcome_available_at']) <= generated, 'OUTCOME_AVAILABILITY')
            need(stamp(row['outcome_available_at']).date() >= date.fromisoformat(row['target_session']), 'PRE_SESSION_OUTCOME')
            need(stamp(row['outcome_available_at']) >= stamp(target['close_at']), 'PRE_CLOSE_OUTCOME')
            vals = [row[k] for k in ('asset_return', 'benchmark_return', 'excess_return')]
            need(all(type(v) in (int, float) and math.isfinite(v) for v in vals), 'MATURED_NUMBERS')
            need(math.isclose(vals[0] - vals[1], vals[2], rel_tol=1e-12, abs_tol=1e-12), 'EXCESS_RETURN')
            matured += 1
        else:
            need(all(row[k] is None for k in ('asset_return', 'benchmark_return', 'excess_return', 'source_sha256', 'outcome_session', 'outcome_available_at')), 'UNRESOLVED_MUST_BE_NULL')
    complete = bool(groups) and matured == len(value['rows']) and all(g['horizons'] == set(HORIZONS) for g in groups.values())
    need((value['coverage_status'] == 'COMPLETE_EXACT') == complete, 'COVERAGE_STATUS')
    return _proposal('cohort', raw, coverage_status=value['coverage_status'], maturity_candidate=complete,
                     outcome_admission_status='NOT_VERIFIED', learning_eligible=False,
                     denominator_count=len(value['rows']), rows=deepcopy(value['rows']))

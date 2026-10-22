"""Stage 2 supplied-byte discovery selection. No network, dispatch or admission.

Reuse the existing A2 schema/parser and A3-backed source graph validator. The
additional identity/origin records are assertions checked against supplied
bytes, not an authentication service. Successful rows are DRY_RUN proposals;
stage 3 must authenticate current A0 evidence and plan actual price coverage.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from urllib.parse import parse_qs, urlsplit

if __package__:
    from . import a2_research_intake_v1 as intake
else:
    import a2_research_intake_v1 as intake

SCHEMA = 'a2-a1-discovery-context-v1'
FAMILIES = frozenset(('EARNINGS', 'GUIDANCE', 'OPERATING_KPI', 'CONTRACT',
    'REGULATORY', 'CORPORATE_ACTION', 'CAPACITY', 'CAPEX', 'PRODUCT', 'LITIGATION'))
PRIMARY = frozenset(('SEC_FILING', 'COMPANY_IR', 'CUSTOMER_DISCLOSURE',
    'GOVERNMENT', 'REGULATOR', 'EXCHANGE', 'COURT', 'REUTERS',
    'OTHER_INDEPENDENT_MEDIA'))
IDENTITY_FIELDS = ('security_id', 'issuer_id', 'ticker', 'country', 'currency',
    'mic', 'valid_from', 'valid_until')


def _url(value):
    intake.need(type(value) is str and 0 < len(value) <= 1800
                and '\\' not in value
                and not any(ord(c) <= 32 or ord(c) == 127 for c in value), 'ORIGINAL_URL')
    try:
        url = urlsplit(value)
        dart_query = (url.hostname == 'dart.fss.or.kr' and url.path == '/dsaf001/main.do'
            and re.fullmatch(r'rcpNo=[0-9]{14}', url.query) is not None
            and set(parse_qs(url.query)) == {'rcpNo'})
        intake.need(url.scheme == 'https' and bool(url.hostname) and url.username is None
                    and url.password is None and (not url.query or dart_query) and not url.fragment
                    and url.port in (None, 443), 'ORIGINAL_URL')
    except ValueError:
        raise intake.IntakeError('ORIGINAL_URL') from None
    return value


def _strings(values, code, maximum):
    intake.need(type(values) is list and len(values) <= maximum, code)
    intake.need(all(type(x) is str for x in values) and len(set(values)) == len(values), code)
    for value in values:
        intake.identifier(value)
    return set(values)


def _context(raw):
    value = intake.decode(raw)
    intake._fields(value, ('schema', 'identities', 'origins', 'prior_event_keys',
        'prior_request_event_keys', 'registry_security_ids', 'registry_theme_ids'))
    intake.need(value['schema'] == SCHEMA, 'CONTEXT_SCHEMA')
    intake.need(type(value['identities']) is list and len(value['identities']) <= 1000,
                'IDENTITY_COUNT')
    intake.need(type(value['origins']) is list and len(value['origins']) <= 1000,
                'ORIGIN_COUNT')
    identities, origins, ticker_keys = {}, {}, set()
    for row in value['identities']:
        intake._fields(row, (*IDENTITY_FIELDS, 'evidence_ref'))
        sid = intake.identifier(row['security_id'])
        intake.need(sid not in identities, 'DUPLICATE_SECURITY')
        for key in ('issuer_id', 'ticker', 'country', 'currency', 'mic'):
            intake.identifier(row[key])
        ticker_key = (row['country'], row['ticker'])
        intake.need(ticker_key not in ticker_keys, 'AMBIGUOUS_TICKER')
        ticker_keys.add(ticker_key)
        identities[sid] = row
    for row in value['origins']:
        intake._fields(row, ('event_id', 'primary_source_id', 'original_url',
                            'materiality_basis'))
        eid = intake.identifier(row['event_id'])
        intake.need(eid not in origins, 'DUPLICATE_ORIGIN')
        origins[eid] = row
    prior = _strings(value['prior_event_keys'], 'PRIOR_EVENT_KEYS', 1000)
    requested = _strings(value['prior_request_event_keys'], 'PRIOR_REQUEST_KEYS', 1000)
    registry = _strings(value['registry_security_ids'], 'REGISTRY_SECURITIES', 30)
    themes = _strings(value['registry_theme_ids'], 'REGISTRY_THEMES', 10)
    return identities, origins, prior, requested, registry, themes


def _identity(event, identities, cutoff, memory):
    intake.need(len(event['security_ids']) == len(event['issuer_ids'])
                == len(event['tickers']) == 1
                and event['asset_ids'] == event['security_ids'], 'SINGLE_SECURITY_REQUIRED')
    sid, issuer, ticker = (event[k][0] for k in ('security_ids', 'issuer_ids', 'tickers'))
    row = identities.get(sid)
    intake.need(row is not None and row['issuer_id'] == issuer
                and row['ticker'] == ticker, 'IDENTITY_MAPPING')
    intake.identifier(issuer)
    if row['country'] == 'US':
        intake.need(row['currency'] == 'USD' and sid.startswith('US:')
                    and re.fullmatch(r'CIK:[0-9]{1,10}', issuer) is not None
                    and re.fullmatch(r'[A-Z][A-Z0-9.-]{0,13}', ticker) is not None
                    and row['mic'] in {'XNYS', 'XNAS', 'XASE', 'ARCX', 'BATS'}, 'US_IDENTITY')
    elif row['country'] == 'KR':
        intake.need(row['currency'] == 'KRW' and sid.startswith('KR:')
                    and re.fullmatch(r'DART:[0-9]{8}', issuer) is not None
                    and re.fullmatch(r'[0-9]{6}', ticker) is not None
                    and row['mic'] in {'XKRX', 'XKOS'}, 'KR_IDENTITY')
    else:
        raise intake.IntakeError('MARKET_UNSUPPORTED')
    start = intake.stamp(row['valid_from'])
    end = intake.stamp(row['valid_until']) if row['valid_until'] is not None else None
    intake.need(start <= intake.stamp(event['published_at'])
                and (end is None or end > cutoff), 'IDENTITY_LIFECYCLE')
    ref = row['evidence_ref']
    proof = intake.decode(intake._reference(ref, cutoff, memory))
    intake._fields(proof, ('schema', *IDENTITY_FIELDS, 'as_of', 'source_url'))
    intake.need(proof['schema'] == 'a2-discovery-security-identity-v1'
                and all(proof[k] == row[k] for k in IDENTITY_FIELDS), 'IDENTITY_EVIDENCE')
    intake.need(intake.stamp(proof['as_of']) <= intake.stamp(ref['available_at']),
                'IDENTITY_EVIDENCE_CLOCK')
    _url(proof['source_url'])
    return row


def _select(event, identities, origins, cutoff, memory):
    intake.need(event['verification_level'] in {'V1', 'V2'}, 'V0_BLOCKED')
    intake.need(event['primary_source'] in PRIMARY and event['event_family'] in FAMILIES,
                'RUMOR_OR_PRICE_ONLY')
    intake.need(set(event['affected_pillars']) <= intake.a3.CANONICAL_PILLARS, 'PILLARS')
    intake.need(event['materiality'] in {'MEDIUM', 'HIGH'}
                and type(event['verified_fact']) is str
                and bool(event['verified_fact'].strip()), 'MATERIALITY_REQUIRED')
    intake.need(event['state'] in {'TRACK', 'A3_RESEARCH', 'WATCH'}, 'EVENT_STATE')
    pub, avail, collected = (intake.stamp(event[k]) for k in
                             ('published_at', 'available_at', 'collected_at'))
    intake.need(pub <= avail <= collected <= cutoff
                and intake.stamp(event['observed_at']) <= collected
                and intake.stamp(event['expires_at']) > cutoff, 'EVENT_CLOCK')
    identity = _identity(event, identities, cutoff, memory)
    intake._graph(event, memory)
    graph = intake.decode(memory.read(event['source_graph_artifact_id'],
                                     event['source_graph_sha256']))
    origin = origins.get(event['event_id'])
    intake.need(origin is not None, 'ORIGIN_MISSING')
    original_url = _url(origin['original_url'])
    basis = origin['materiality_basis']
    intake.need(type(basis) is str and 0 < len(basis.strip()) <= 1800,
                'MATERIALITY_BASIS')
    matches = [r for r in graph['sources'] if r['source_id'] == origin['primary_source_id']]
    intake.need(len(matches) == 1, 'PRIMARY_SOURCE_BINDING')
    primary = matches[0]
    intake.need(primary['source_type'] == event['primary_source']
                and primary['verification_tier'] in {'V1', 'V2'}
                and primary['used_for_assessment'] is True
                and intake.stamp(primary['published_at']) == pub, 'PRIMARY_SOURCE_BINDING')
    intake.need(bool(set(event['affected_pillars']) & set(primary['supports_pillars'])),
                'MATERIALITY_PILLAR_BINDING')
    # URL/time/label metadata remains supplied, even though every referenced
    # raw byte and reviewed-graph invariant was checked. No account/PIT admission.
    key = intake.digest(intake.canonical(dict(security_id=identity['security_id'],
        issuer_id=identity['issuer_id'], event_family=event['event_family'],
        source_sha256=primary['raw_sha256'], published_at=pub.isoformat())))
    return dict(event_key=key, upstream_event_id=event['event_id'],
        security_id=identity['security_id'], issuer_id=identity['issuer_id'],
        ticker=identity['ticker'], country=identity['country'], mic=identity['mic'],
        original_url=original_url, source_sha256=primary['raw_sha256'],
        source_graph_sha256=event['source_graph_sha256'], published_at=event['published_at'],
        available_at=event['available_at'], collected_at=event['collected_at'],
        materiality=event['materiality'], materiality_basis=basis,
        verification_level=event['verification_level'],
        identity_evidence_sha256=identity['evidence_ref']['sha256'],
        identity_authentication='NOT_VERIFIED', source_authentication='NOT_VERIFIED',
        status='DRY_RUN_CANDIDATE', authority=intake.closed())


def select_discovery(events_raw, context_raw, *, cutoff, artifact_resolver):
    """Return candidate/blocked/dedup proposals over one sealed supplied bundle.

    Prior keys and Registry context are supplied assertions, not trusted live
    pointers. A duplicate proposal cannot be reported as an executed/reused A1
    request. This function never creates an A1 request or touches persistent state.
    """
    memory = intake._memory(artifact_resolver)
    value = intake._typed('events', events_raw, memory)
    limit = intake.stamp(cutoff)
    intake.need(intake.stamp(value['as_of']) <= limit <= datetime.now(timezone.utc),
                'FUTURE_CUTOFF')
    identities, origins, prior, requested, registry, themes = _context(context_raw)
    ids = _strings([e['event_id'] for e in value['events']], 'DUPLICATE_EVENT', 1000)
    intake.need(set(origins) <= ids, 'ORPHAN_ORIGIN')
    candidates, rows, seen = [], [], set()
    active, active_themes = set(registry), set(themes)
    for event in sorted(value['events'], key=lambda x: x['event_id']):
        try:
            intake.need(intake.stamp(event['collected_at']) <= intake.stamp(value['as_of']),
                        'EVENT_AS_OF')
            item = _select(event, identities, origins, limit, memory)
        except intake.IntakeError as exc:
            rows.append(dict(upstream_event_id=event['event_id'], status='BLOCKED',
                             reason=str(exc), authority=intake.closed()))
            continue
        key = item['event_key']
        if key in seen or key in prior or key in requested:
            rows.append(dict(upstream_event_id=event['event_id'], event_key=key,
                status='DUPLICATE_PROPOSAL_ONLY', authority=intake.closed()))
            continue
        seen.add(key)
        active.add(item['security_id']); active_themes.update(event['themes'])
        intake.need(len(active) <= 30 and len(active_themes) <= 10, 'ACTIVE_CAP')
        item['existing_registry_candidate'] = item['security_id'] in registry
        candidates.append(item)
    return dict(schema='a2-a1-discovery-selection-v1', mode='DRY_RUN',
        scope='SUPPLIED_BYTES_ONLY', cutoff=cutoff, candidates=candidates, other_events=rows,
        events_sha256=intake.digest(events_raw), context_sha256=intake.digest(context_raw),
        request_count=0, dispatch_count=0, canonical_write_performed=False,
        A2_Technical_eligible=False, A3_input_eligible=False, authority=intake.closed(),
        next_gate='A0_AUTHENTICATED_IDENTITY_SOURCE_AND_COVERAGE_REQUIRED')

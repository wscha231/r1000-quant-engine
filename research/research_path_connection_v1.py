"""Connect existing research validators over supplied bytes without admission.

This pure, single-candidate adapter performs no collection, persistence, AI
research, ER modeling or current selection. DONE describes a local research
validation stage only. Supplied REVIEWED/WALK_FORWARD labels are declarations;
even an internally consistent complete path retains null admitted ER.
"""
from __future__ import annotations

import re

if __package__:
    from . import a2_research_intake_v1 as intake
    from . import a3_candidate_packet_v1 as a3
    from . import candidate_registry_v1 as registry
else:
    import a2_research_intake_v1 as intake
    import a3_candidate_packet_v1 as a3
    import candidate_registry_v1 as registry

MemoryArtifacts = intake.MemoryArtifacts
BYTE_FIELDS = ('identities', 'events', 'registry', 'er', 'cohort',
               'delta_previous', 'delta_current', 'a3_packet')
ID_FIELDS = ('case_id', 'security_id', 'issuer_id', 'benchmark_id')
STAGES = ('identities', 'events', 'a3_packet', 'registry', 'er', 'cohort', 'delta')
_REFUSALS = (intake.IntakeError, a3.A3CandidatePacketError, registry.ReferenceIndexError)
_REASON = re.compile(r'[A-Za-z0-9_: .-]{1,120}\Z')


def _reason(exc):
    code = str(exc)
    return code if _REASON.fullmatch(code) else 'CONTRACT_REFUSED'


def build_research_path(request: dict, *, cutoff: str,
                        artifact_resolver: MemoryArtifacts) -> dict:
    """Validate supplied candidate bytes using the original APIs and policies.

    Optional absent stages do not become complete. Null Registry and ER take
    the original reconciliation branches. A missing formal packet is never
    manufactured from a note/event. Contract refusals remain bounded BLOCKED
    stages; unexpected programming exceptions propagate to the caller.
    """
    out = {
        'schema': 'research-path-connection-v1', 'scope': 'SUPPLIED_BYTES_ONLY',
        'evidence_level': 'SUPPLIED_BYTES_ONLY', 'status': 'NOT_RUN',
        'cutoff': None, 'case_id': None, 'input_sha256': {},
        'calls': [], 'stages': {name: {'status': 'NOT_RUN', 'reason': 'INPUT_MISSING',
                                    'called': False, 'result': None} for name in STAGES},
        'precheck': {'status': 'NOT_RUN', 'reason': None},
        'authority': intake.closed(), 'ER_admission': False,
        'A5_eligible_input': False, 'current_write_allowed': False,
        'canonical_write_performed': False, 'learning_eligible': False,
        'historical_pit_certified': False, 'validated_er': None,
        'source_admission_status': 'NOT_VERIFIED',
        'review_authentication_status': 'NOT_VERIFIED',
        'current_selection_status': 'NOT_VERIFIED',
        'connections': {},
    }
    try:
        intake.need(type(request) is dict, 'REQUEST_OBJECT')
        intake.need(set(request) <= set(ID_FIELDS + BYTE_FIELDS), 'REQUEST_FIELDS')
        for field in ID_FIELDS:
            try:
                intake.identifier(request.get(field))
            except intake.IntakeError:
                raise intake.IntakeError('REQUEST_' + field.upper()) from None
        limit = intake.stamp(cutoff)
        intake._memory(artifact_resolver)
        total = 0
        for field in BYTE_FIELDS:
            raw = request.get(field)
            if raw is not None:
                intake.need(type(raw) is bytes and 0 < len(raw) <= intake.MAX_BYTES,
                            'INPUT_BYTES_' + field.upper())
                total += len(raw)
                intake.need(total <= intake.MAX_TOTAL_BYTES, 'INPUT_TOTAL_BUDGET')
            out['input_sha256'][field] = None if raw is None else intake.digest(raw)
    except _REFUSALS as exc:
        out['status'] = 'BLOCKED'
        out['precheck'] = {'status': 'BLOCKED', 'reason': _reason(exc)}
        for stage in out['stages'].values():
            stage['reason'] = 'PRECHECK_BLOCKED'
        return out
    out.update({field: request[field] for field in ID_FIELDS})
    out['cutoff'] = limit.isoformat()
    out['precheck']['status'] = 'DONE'
    out['request_sha256'] = intake.digest(intake.canonical({
        **{field: request[field] for field in ID_FIELDS},
        'cutoff': out['cutoff'], 'input_sha256': out['input_sha256']}))
    stages = out['stages']
    sid, issuer, benchmark = (request[field] for field in ID_FIELDS[1:])
    decoded_events = decoded_packet = None

    def mark(name, status, reason=None):
        stages[name].update(status=status, reason=reason)

    def invoke(name, api, function):
        call = {'stage': name, 'api': api, 'status': 'CALLED',
                'result_status': None, 'result_sha256': None, 'refusal': None}
        out['calls'].append(call)
        stages[name]['called'] = True
        try:
            result = function()
        except _REFUSALS as exc:
            code = _reason(exc)
            call.update(status='BLOCKED', refusal=code)
            mark(name, 'BLOCKED', code)
            return None
        call['status'] = 'DONE'
        if api != 'a2._identities':
            call['result_sha256'] = intake.digest(intake.canonical(result))
        if type(result) is dict:
            call['result_status'] = result.get('status')
        return result

    def bound(name, valid, reason):
        if not valid:
            mark(name, 'BLOCKED', reason)
        return valid

    identities = request.get('identities')
    identity_ok = False
    if identities is not None:
        subjects = invoke('identities', 'a2._identities', lambda: intake._identities(identities))
        # The existing identity parser returns frozensets; retain only a closed
        # summary instead of treating assertions as authenticated identities.
        if subjects is not None and bound('identities', sid in subjects and subjects[sid][0] == issuer,
                                          'REQUEST_IDENTITY_MAPPING'):
            identity_ok = True
            stages['identities']['result'] = {'security_id': sid, 'issuer_id': issuer,
                                              'authentication': 'NOT_VERIFIED'}
            mark('identities', 'DONE')

    for name, api, validator in (
        ('events', 'a2.validate_events', intake.validate_events),
        ('cohort', 'a2.validate_cohort', intake.validate_cohort),
    ):
        raw = request.get(name)
        if raw is None:
            continue
        if not identity_ok:
            mark(name, 'BLOCKED', 'IDENTITIES_REQUIRED_OR_REFUSED')
            continue
        result = invoke(name, api, lambda raw=raw, validator=validator: validator(
            raw, cutoff=cutoff, artifact_resolver=artifact_resolver, identities=identities))
        if result is None:
            continue
        stages[name]['result'] = result
        if name == 'events':
            envelope = invoke(name, 'a2.decode', lambda: intake.decode(raw))
            decoded_events = envelope
            if envelope is not None and bound(name, all(
                sid in row['security_ids'] and issuer in row['issuer_ids'] for row in envelope['events']),
                'REQUEST_EVENT_IDENTITY'):
                mark(name, 'DONE' if result['active_security_count'] else 'BLOCKED',
                     None if result['active_security_count'] else 'NO_ACTIVE_EVENTS')
        elif bound(name, all(row['security_id'] == sid and row['issuer_id'] == issuer
                            and row['benchmark_id'] == benchmark for row in result['rows']),
                   'REQUEST_COHORT_IDENTITY'):
            mark(name, 'DONE' if result['denominator_count'] else 'NOT_RUN',
                 None if result['denominator_count'] else 'EMPTY_COHORT')

    raw = request.get('a3_packet')
    if raw is not None:
        packet = invoke('a3_packet', 'a2.decode', lambda: intake.decode(raw))
        decoded_packet = packet
        if packet is not None:
            # Reuse A3's verified cache for strict structured dependencies and
            # immutable-ID conflict accounting; no alternative evaluator.
            reader = artifact_resolver.read
            cache = a3._VerifiedArtifactCache(reader)
            result = invoke('a3_packet', 'a3.evaluate_packet', lambda: a3.evaluate_packet(
                packet, cutoff, reader, _artifact_cache=cache))
            if result is not None:
                projected = dict(result)
                projected['declared_er'] = projected['validated_er']
                projected['validated_er'] = None
                projected['validated_expected_return_available'] = False
                projected['ER_admission'] = False
                projected['A5_eligible_input'] = False
                stages['a3_packet']['result'] = projected
                if bound('a3_packet', result['asset_id'] == sid and result['issuer_id'] == issuer
                         and result['benchmark_id'] == benchmark, 'REQUEST_A3_IDENTITY'):
                    mark('a3_packet', 'DONE')

    registry_raw = request.get('registry')
    result = invoke('registry', 'a2.reference_preview', lambda: intake.reference_preview(
        intake.canonical({'entries': None}) if registry_raw is None else registry_raw,
        cutoff=cutoff, artifact_resolver=artifact_resolver))
    if result is not None:
        stages['registry']['result'] = result
        index = result.get('reference_index')
        if index is None or not index['input_count']:
            mark('registry', 'NOT_RUN', 'REFERENCE_RECONCILE_PENDING')
        elif bound('registry', all(row['asset_id'] == sid and row['issuer_id'] == issuer
                                  and (row['metadata'] is None or row['metadata']['benchmark_id'] == benchmark)
                                  for row in index['records']), 'REQUEST_REGISTRY_IDENTITY'):
            valid = index['blocked_count'] == 0 and all(
                row['declared_expiry_state'] == 'UNEXPIRED' for row in index['records'])
            mark('registry', 'DONE' if valid else 'BLOCKED',
                 None if valid else 'REFERENCE_BLOCKED_EXPIRED_OR_UNKNOWN')

    result = invoke('er', 'a2.er_preview', lambda: intake.er_preview(
        request.get('er'), cutoff=cutoff, artifact_resolver=artifact_resolver,
        security_id=sid, issuer_id=issuer, benchmark_id=benchmark))
    if result is not None:
        stages['er']['result'] = result
        mark('er', 'BLOCKED', result['blocker'])

    current = request.get('delta_current')
    if current is not None:
        result = invoke('delta', 'a2.plan_delta', lambda: intake.plan_delta(
            request.get('delta_previous'), current, cutoff=cutoff))
        if result is not None:
            stages['delta']['result'] = result
            value = invoke('delta', 'a2.decode', lambda: intake.decode(current))
            if value is not None and bound('delta', value['security_id'] == sid and value['issuer_id'] == issuer,
                                           'REQUEST_DELTA_IDENTITY'):
                plan = result['plan']
                mark('delta', 'BLOCKED' if plan == 'BLOCKED_FULL_A3_REVIEW' else
                     'NOT_RUN' if plan == 'RECONCILE_PENDING' else 'DONE',
                     None if plan in {'SKIP_UNCHANGED', 'REFRESH_REQUIRED'} else plan)
    elif request.get('delta_previous') is not None:
        mark('delta', 'BLOCKED', 'DELTA_CURRENT_REQUIRED')

    # Bind independently valid stages to the same supplied revision/event.
    # These checks add no producer authentication or current-selection claim.
    def connect(name, ready, valid, blocked_stage, reason):
        status = 'NOT_RUN' if not ready else 'DONE' if valid else 'BLOCKED'
        out['connections'][name] = {'status': status, 'reason': reason if ready and not valid else None}
        if status == 'BLOCKED':
            mark(blocked_stage, 'BLOCKED', reason)

    registry_result = stages['registry']['result']
    index = None if registry_result is None else registry_result.get('reference_index')
    packet_result = stages['a3_packet']['result']
    ready = stages['a3_packet']['status'] == stages['registry']['status'] == 'DONE'
    connect('a3_to_registry', ready, ready and all(
        row['a3_packet_ref']['sha256'] == out['input_sha256']['a3_packet']
        and row['packet_semantic_sha256'] == packet_result['packet_sha256']
        for row in index['records']), 'registry', 'A3_REGISTRY_REVISION_MISMATCH')

    er_result = stages['er']['result']
    er_ref = None
    if request.get('er') is not None and er_result is not None:
        er_ref = invoke('er', 'a2.decode', lambda: intake.decode(request['er']))
    declared_ref = None if packet_result is None else decoded_packet['artifacts'].get('validated_er')
    ready = declared_ref is not None and er_ref is not None and packet_result is not None
    connect('a3_to_er', ready, ready and all(declared_ref.get(key) == er_ref.get(key)
        for key in ('artifact_id', 'sha256')), 'er', 'A3_ER_REVISION_MISMATCH')

    cohort_result = stages['cohort']['result']
    ready = stages['events']['status'] == stages['cohort']['status'] == 'DONE'
    event_rows = {} if decoded_events is None else {
        (row['event_id'], row['cohort_id']): row for row in decoded_events['events']}
    linked = ready
    if ready:
        for row in cohort_result['rows']:
            event = event_rows.get((row['event_id'], row['cohort_id']))
            if event is None or any(intake.stamp(event[field]) > intake.stamp(row['decision_at'])
                                    for field in ('published_at', 'available_at', 'collected_at')):
                linked = False
                break
    connect('events_to_cohort', ready, linked, 'cohort', 'EVENT_COHORT_IDENTITY_OR_DECISION_CLOCK')

    states = [stage['status'] for stage in stages.values()]
    out['status'] = 'BLOCKED' if 'BLOCKED' in states else 'DONE' if all(
        state == 'DONE' for state in states) else 'NOT_RUN'
    return out


__all__ = ['MemoryArtifacts', 'build_research_path']

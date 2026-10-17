"""Synthetic/local connection controls; never actual Source/PIT evidence."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'research'))
sys.path.insert(0, str(ROOT / 'tests'))
import research_path_connection_v1 as connection
import a2_research_intake_v1_smoke as fixtures
import a3_candidate_packet_v1_smoke as a3fixtures
import candidate_registry_v1_smoke as registryfixtures

h = connection.intake
CUTOFF = fixtures.CUTOFF


def request():
    return {'case_id': 'SYNTHETIC:LOCAL', 'security_id': 'US:S0',
            'issuer_id': 'CIK:0', 'benchmark_id': 'US:SPY'}


def full_fixture():
    # Existing valid A3 producer/result/replay fixtures are reused unchanged.
    store = registryfixtures.RegistryTests()
    store.setUp()
    entry = store.fixture('US:S0', 'CIK:0')
    for ref in (entry['a3_packet_ref'], entry['a3_result_ref']):
        ref['expires_at'] = '2026-10-20T00:00:00Z'
    cohort, memory = fixtures.cohort(True)
    memory.update({aid: raw for (aid, sha), raw in store.raw.items()})
    packet = store.resolve(entry['a3_packet_ref']['artifact_id'], entry['a3_packet_ref']['sha256'])
    _, erref, ermem = fixtures.IntakeTests().er_fixture()
    memory.update(ermem)
    value = request()
    event_time = '2025-09-01T20:00:00Z'
    value.update(identities=fixtures.identities(),
                 events=h.canonical(fixtures.envelope([fixtures.event(
                     observed_at=event_time, published_at=event_time,
                     available_at=event_time, collected_at=event_time)])),
                 registry=h.canonical({'entries': [entry]}), er=h.canonical(erref),
                 cohort=h.canonical(cohort), delta_previous=h.canonical(fixtures.delta()),
                 delta_current=h.canonical(fixtures.delta()), a3_packet=packet)
    return value, memory


def run(value=None, memory=None, *, cutoff=CUTOFF):
    return connection.build_research_path(request() if value is None else value,
        cutoff=cutoff, artifact_resolver=connection.MemoryArtifacts(memory or {}))


class ResearchPathTests(unittest.TestCase):
    def test_01_existing_validators_actually_called(self):
        value, memory = full_fixture()
        with patch.object(h, 'validate_events', wraps=h.validate_events) as events, \
             patch.object(h, 'validate_cohort', wraps=h.validate_cohort) as cohort, \
             patch.object(connection.a3, 'evaluate_packet', wraps=connection.a3.evaluate_packet) as a3, \
             patch.object(connection.registry, 'build_reference_index',
                          wraps=connection.registry.build_reference_index) as registry:
            result = run(value, memory)
        self.assertEqual((events.call_count, cohort.call_count, a3.call_count, registry.call_count), (1, 1, 1, 1))
        self.assertEqual(result['status'], 'BLOCKED')
        for name in ('identities', 'events', 'a3_packet', 'registry', 'cohort', 'delta'):
            self.assertEqual(result['stages'][name]['status'], 'DONE', name)
        self.assertEqual(result['stages']['er']['status'], 'BLOCKED')
        self.assertEqual(result['connections']['a3_to_registry']['status'], 'DONE')
        self.assertEqual(result['connections']['events_to_cohort']['status'], 'DONE')
        self.assertEqual(result['stages']['delta']['result']['plan'], 'SKIP_UNCHANGED')
        self.assertTrue(result['stages']['cohort']['result']['maturity_candidate'])
        self.assertEqual(result['stages']['er']['result']['declared_er']['1m']['expected_return'], 0)
        for field in connection.BYTE_FIELDS:
            self.assertEqual(result['input_sha256'][field], h.digest(value[field]))

    def test_02_absence_runs_only_original_null_branches(self):
        result = run()
        self.assertEqual([call['api'] for call in result['calls']],
                         ['a2.reference_preview', 'a2.er_preview'])
        self.assertEqual(result['stages']['registry']['status'], 'NOT_RUN')
        self.assertEqual(result['stages']['registry']['result']['reference_status'], 'RECONCILE_PENDING')
        self.assertIsNone(result['stages']['er']['result']['validated_er'])
        self.assertEqual(result['status'], 'BLOCKED')
        for name in ('events', 'cohort', 'a3_packet', 'delta'):
            self.assertEqual(result['stages'][name]['status'], 'NOT_RUN')
            self.assertFalse(result['stages'][name]['called'])

    def test_03_missing_identities_does_not_call_typed_validators(self):
        value, memory = full_fixture()
        value['identities'] = None
        with patch.object(h, 'validate_events', side_effect=RuntimeError('must not run')), \
             patch.object(h, 'validate_cohort', side_effect=RuntimeError('must not run')):
            result = run(value, memory)
        for name in ('events', 'cohort'):
            self.assertEqual(result['stages'][name]['status'], 'BLOCKED')
            self.assertFalse(result['stages'][name]['called'])
        self.assertEqual(result['stages']['a3_packet']['status'], 'DONE')

    def test_04_invalid_cutoff_has_zero_calls(self):
        for cutoff in ('2026-10-15T00:00:00', 'not-a-clock', None, '2026-02-30T00:00:00Z'):
            with self.subTest(cutoff=cutoff):
                result = run(cutoff=cutoff)
                self.assertEqual(result['precheck']['status'], 'BLOCKED')
                self.assertEqual(result['precheck']['reason'], 'TIMESTAMP')
                self.assertEqual(result['calls'], [])

    def test_05_request_shape_and_byte_budget(self):
        cases = [[], {**request(), 'unknown': b'{}'}, {**request(), 'case_id': 'bad space'},
                 {**request(), 'events': {}}, {**request(), 'registry': b''}]
        for value in cases:
            with self.subTest(value_type=type(value).__name__):
                result = run(value)
                self.assertEqual(result['precheck']['status'], 'BLOCKED')
                self.assertEqual(result['calls'], [])
        with patch.object(h, 'MAX_BYTES', 2):
            self.assertEqual(run({**request(), 'events': b'123'})['precheck']['reason'], 'INPUT_BYTES_EVENTS')
        with patch.object(h, 'MAX_TOTAL_BYTES', 3):
            self.assertEqual(run({**request(), 'events': b'{}', 'cohort': b'{}'})['precheck']['reason'], 'INPUT_TOTAL_BUDGET')
        result = connection.build_research_path(request(), cutoff=CUTOFF, artifact_resolver=lambda a, s: b'{}')
        self.assertEqual(result['precheck']['reason'], 'MEMORY_RESOLVER_REQUIRED')

    def test_06_programming_errors_propagate(self):
        value, memory = full_fixture()
        with patch.object(h, 'validate_events', side_effect=RuntimeError('internal bug')):
            with self.assertRaisesRegex(RuntimeError, 'internal bug'):
                run(value, memory)

    def test_07_event_clock_fields_refused_individually(self):
        for field in ('published_at', 'available_at', 'collected_at', 'observed_at'):
            value, memory = full_fixture()
            envelope = h.decode(value['events'])
            envelope['events'][0][field] = '2026-10-16T00:00:00Z'
            value['events'] = h.canonical(envelope)
            with self.subTest(field=field):
                stage = run(value, memory)['stages']['events']
                self.assertEqual(stage['status'], 'BLOCKED')
                self.assertTrue(stage['called'])

    def test_08_missing_or_tampered_schema(self):
        for tamper in (False, True):
            value, memory = full_fixture()
            name = 'SCHEMA:' + h.SCHEMAS['events'][0]
            if tamper:
                memory[name] += b' '
            else:
                del memory[name]
            stage = run(value, memory)['stages']['events']
            self.assertEqual(stage['status'], 'BLOCKED')
            self.assertEqual(stage['reason'], 'ARTIFACT_HASH' if tamper else 'ARTIFACT_MISSING')

    def test_09_stale_events_remain_in_results(self):
        value, memory = full_fixture()
        envelope = h.decode(value['events'])
        envelope['events'][0]['expires_at'] = CUTOFF
        value['events'] = h.canonical(envelope)
        stage = run(value, memory)['stages']['events']
        self.assertEqual(stage['status'], 'BLOCKED')
        self.assertEqual(stage['reason'], 'NO_ACTIVE_EVENTS')
        self.assertEqual(len(stage['result']['events']), 1)
        self.assertTrue(stage['result']['events'][0]['include_in_denominator'])

    def test_10_registry_expiry_is_not_current(self):
        for expiry in (CUTOFF, None):
            value, memory = full_fixture()
            data = h.decode(value['registry'])
            data['entries'][0]['a3_result_ref']['expires_at'] = expiry
            value['registry'] = h.canonical(data)
            stage = run(value, memory)['stages']['registry']
            self.assertEqual(stage['status'], 'BLOCKED')
            row = stage['result']['reference_index']['records'][0]
            self.assertEqual(row['reference_status'], 'A3_REFERENCE_REPLAY_VERIFIED')
            self.assertFalse(row['A5_eligible_input'])
            self.assertEqual(row['current_selection_status'], 'NOT_VERIFIED')

    def test_11_registry_immutable_hash_conflict_is_preserved(self):
        value, memory = full_fixture()
        data = h.decode(value['registry'])
        entry = data['entries'][0]
        entry['a3_result_ref']['artifact_id'] = entry['a3_packet_ref']['artifact_id']
        value['registry'] = h.canonical(data)
        stage = run(value, memory)['stages']['registry']
        self.assertEqual(stage['status'], 'BLOCKED')
        self.assertEqual(stage['reason'], 'REFERENCE_SET_REFUSED')

    def test_12_registry_tampered_result_remains_blocked_row(self):
        value, memory = full_fixture()
        data = h.decode(value['registry'])
        memory[data['entries'][0]['a3_result_ref']['artifact_id']] += b' '
        stage = run(value, memory)['stages']['registry']
        self.assertEqual(stage['status'], 'BLOCKED')
        row = stage['result']['reference_index']['records'][0]
        self.assertEqual(row['reference_status'], 'BLOCKED')
        self.assertTrue(row['blockers'])

    def test_13_partial_note_never_becomes_formal_packet(self):
        value = {**request(), 'a3_packet': h.canonical({'note': 'Synthetic partial research'})}
        stage = run(value)['stages']['a3_packet']
        self.assertEqual(stage['status'], 'BLOCKED')
        self.assertEqual(stage['reason'], 'schema')
        result = run({**request(), 'events': h.canonical(fixtures.envelope([])),
                      'identities': fixtures.identities()}, fixtures.inventory())
        self.assertFalse(any(call['api'] == 'a3.evaluate_packet' for call in result['calls']))
        for bad in (None, [], 0):
            value, memory = full_fixture()
            packet = h.decode(value['a3_packet'])
            packet['artifacts'] = bad
            value['a3_packet'] = h.canonical(packet)
            self.assertEqual(run(value, memory)['stages']['a3_packet']['reason'], 'artifacts_object')

    def test_14_formal_a3_missing_or_tampered_dependency(self):
        for tamper in (False, True):
            value, memory = full_fixture()
            packet = h.decode(value['a3_packet'])
            aid = packet['artifacts']['methodology']['artifact_id']
            if tamper:
                memory[aid] += b' '
            else:
                del memory[aid]
            stage = run(value, memory)['stages']['a3_packet']
            self.assertEqual(stage['status'], 'BLOCKED')
            self.assertIn('artifact_unavailable', stage['reason'])

    def test_15_a3_review_clock_and_request_identity(self):
        for field, bad in (('reviewed_at', '2026-10-16T00:00:00Z'),
                           ('reviewed_at', '2026-09-19T01:00:00')):
            value, memory = full_fixture()
            packet = h.decode(value['a3_packet'])
            packet[field] = bad
            value['a3_packet'] = h.canonical(packet)
            self.assertEqual(run(value, memory)['stages']['a3_packet']['status'], 'BLOCKED')
        value, memory = full_fixture()
        value['benchmark_id'] = 'US:QQQ'
        self.assertEqual(run(value, memory)['stages']['a3_packet']['reason'], 'REQUEST_A3_IDENTITY')

    def test_16_linked_er_is_declaration_only(self):
        a3fixtures.RAW.clear()
        packet = a3fixtures.packet(True)
        value = {**request(), 'security_id': 'US:EXAMPLE', 'issuer_id': 'CIK:1',
                 'a3_packet': h.canonical(packet)}
        memory = {aid: raw for (aid, sha), raw in a3fixtures.RAW.items()}
        result = run(value, memory)
        stage = result['stages']['a3_packet']
        self.assertEqual(stage['status'], 'DONE')
        self.assertEqual(stage['result']['status'], 'VALIDATED_ER_LINKED')
        self.assertIsNotNone(stage['result']['declared_er'])
        self.assertIsNone(stage['result']['validated_er'])
        self.assertFalse(stage['result']['validated_expected_return_available'])
        self.assertFalse(stage['result']['ER_admission'])

    def test_17_er_reference_clock_expiry_hash_and_identity(self):
        for field, bad in (('available_at', '2026-10-16T00:00:00Z'),
                           ('collected_at', '2026-10-16T00:00:00Z'),
                           ('expires_at', CUTOFF), ('sha256', 'f' * 64)):
            value, memory = full_fixture()
            ref = h.decode(value['er'])
            ref[field] = bad
            value['er'] = h.canonical(ref)
            with self.subTest(field=field):
                self.assertEqual(run(value, memory)['stages']['er']['status'], 'BLOCKED')
                self.assertIsNone(run(value, memory)['stages']['er']['result'])
        for field, bad in (('net_of_costs', False), ('issuer_id', 'OTHER'), ('benchmark_id', 'OTHER')):
            value, memory = full_fixture()
            ref = h.decode(value['er'])
            er = h.decode(memory[ref['artifact_id']])
            er[field] = bad
            memory[ref['artifact_id']] = h.canonical(er)
            ref['sha256'] = h.digest(memory[ref['artifact_id']])
            value['er'] = h.canonical(ref)
            self.assertIsNone(run(value, memory)['stages']['er']['result'])

    def test_18_cohort_refusal_and_unresolved_denominator(self):
        value, memory = full_fixture()
        cohort = h.decode(value['cohort'])
        cohort['generated_at'] = '2026-10-16T00:00:00Z'
        value['cohort'] = h.canonical(cohort)
        self.assertEqual(run(value, memory)['stages']['cohort']['reason'], 'FUTURE_GENERATED')
        for status in ('WATCH', 'REJECT', 'BLOCKED', 'NOT_SELECTED'):
            cohort, memory = fixtures.cohort(False)
            for row in cohort['rows']:
                row['selection_status'] = status
            value = {**request(), 'identities': fixtures.identities(), 'cohort': h.canonical(cohort)}
            stage = run(value, memory)['stages']['cohort']
            self.assertEqual(stage['status'], 'DONE')
            self.assertEqual(stage['result']['denominator_count'], 7)
            self.assertFalse(stage['result']['learning_eligible'])
            self.assertTrue(all(row['asset_return'] is None for row in stage['result']['rows']))

    def test_19_delta_reuses_planner_and_missing_stays_pending(self):
        value, memory = full_fixture()
        for field, expected in (('market_price', {'market', 'valuation', 'ER'}),
                                ('regime', {'downside', 'portfolio_overlay'})):
            delta = fixtures.delta()
            delta['fingerprints'][field] = 'b' * 64
            value['delta_current'] = h.canonical(delta)
            stage = run(value, memory)['stages']['delta']
            self.assertEqual(set(stage['result']['refresh']), expected)
            self.assertFalse(stage['result']['execution_permitted'])
        value['delta_previous'] = None
        self.assertEqual(run(value, memory)['stages']['delta']['status'], 'NOT_RUN')
        value['delta_previous'], value['delta_current'] = h.canonical(fixtures.delta()), None
        self.assertEqual(run(value, memory)['stages']['delta']['reason'], 'DELTA_CURRENT_REQUIRED')

    def test_20_authority_injection_and_no_mutation(self):
        value, memory = full_fixture()
        before_value, before_memory = deepcopy(value), deepcopy(memory)
        result = run(value, memory)
        self.assertEqual(value, before_value)
        self.assertEqual(memory, before_memory)
        self.assertEqual(result, run(value, memory))
        self.assertTrue(all(flag is False for flag in result['authority'].values()))
        for field in ('ER_admission', 'A5_eligible_input', 'current_write_allowed',
                      'canonical_write_performed', 'learning_eligible', 'historical_pit_certified'):
            self.assertIs(result[field], False)
        self.assertIsNone(result['validated_er'])
        for flag in h.FLAGS:
            envelope = h.decode(value['events'])
            envelope['events'][0]['authority'][flag] = True
            attacked = {**value, 'events': h.canonical(envelope)}
            self.assertEqual(run(attacked, memory)['stages']['events']['status'], 'BLOCKED', flag)

    def test_21_duplicate_keys_never_normalized(self):
        value, memory = full_fixture()
        for field in ('events', 'registry', 'cohort', 'delta_current', 'a3_packet'):
            attacked = {**value, field: b'{"x":0,"x":1}'}
            stage_name = 'delta' if field == 'delta_current' else field
            self.assertEqual(run(attacked, memory)['stages'][stage_name]['status'], 'BLOCKED', field)

    def test_22_validation_has_no_io(self):
        value, memory = full_fixture()
        with patch('builtins.open', side_effect=RuntimeError('file IO forbidden')), \
             patch('pathlib.Path.read_bytes', side_effect=RuntimeError('file IO forbidden')), \
             patch('pathlib.Path.write_bytes', side_effect=RuntimeError('file IO forbidden')), \
             patch('socket.create_connection', side_effect=RuntimeError('network forbidden')), \
             patch('subprocess.Popen', side_effect=RuntimeError('subprocess forbidden')):
            result = run(value, memory)
        self.assertEqual(result['stages']['a3_packet']['status'], 'DONE')
        self.assertEqual(result['stages']['registry']['status'], 'DONE')

    def test_23_formal_required_reference_fields_are_not_relaxed(self):
        for role in ('methodology', 'market_valuation', 'source_graph', 'moat'):
            for field, bad in (('available_at', '2026-10-16T00:00:00Z'),
                               ('review_status', 'UNREVIEWED'), ('sha256', 'f' * 64),
                               ('kind', 'UNKNOWN')):
                value, memory = full_fixture()
                packet = h.decode(value['a3_packet'])
                packet['artifacts'][role][field] = bad
                value['a3_packet'] = h.canonical(packet)
                with self.subTest(role=role, field=field):
                    stage = run(value, memory)['stages']['a3_packet']
                    self.assertEqual(stage['status'], 'BLOCKED')
                    self.assertTrue(stage['called'])

    def test_24_different_valid_a3_revisions_do_not_connect(self):
        value, memory = full_fixture()
        packet = h.decode(value['a3_packet'])
        packet['thesis']['counter_thesis'] = 'Another internally valid revision'
        value['a3_packet'] = h.canonical(packet)
        result = run(value, memory)
        self.assertEqual(result['stages']['a3_packet']['status'], 'DONE')
        self.assertEqual(result['stages']['registry']['reason'], 'A3_REGISTRY_REVISION_MISMATCH')
        self.assertEqual(result['connections']['a3_to_registry']['status'], 'BLOCKED')

    def test_25_event_and_cohort_cross_stage_binding(self):
        for field, bad in (('cohort_id', 'OTHER'), ('event_id', 'OTHER'),
                           ('collected_at', '2025-09-01T22:00:00Z')):
            value, memory = full_fixture()
            envelope = h.decode(value['events'])
            envelope['events'][0][field] = bad
            value['events'] = h.canonical(envelope)
            result = run(value, memory)
            self.assertEqual(result['stages']['events']['status'], 'DONE')
            self.assertEqual(result['stages']['cohort']['reason'], 'EVENT_COHORT_IDENTITY_OR_DECISION_CLOCK')

    def test_26_original_er_must_match_linked_a3_reference(self):
        a3fixtures.RAW.clear()
        packet = a3fixtures.packet(True)
        er = a3fixtures.valid_er()
        er['issuer_id'] = 'CIK:1'
        raw = h.canonical(er)
        value = {**request(), 'security_id': 'US:EXAMPLE', 'issuer_id': 'CIK:1',
                 'a3_packet': h.canonical(packet), 'er': h.canonical(fixtures.reference('ER:OTHER', raw))}
        memory = {aid: payload for (aid, sha), payload in a3fixtures.RAW.items()}
        memory['ER:OTHER'] = raw
        result = run(value, memory)
        self.assertEqual(result['stages']['a3_packet']['status'], 'DONE')
        self.assertEqual(result['stages']['er']['reason'], 'A3_ER_REVISION_MISMATCH')
        self.assertEqual(result['connections']['a3_to_er']['status'], 'BLOCKED')
        memory['ER'] = raw
        packet['artifacts']['validated_er']['sha256'] = h.digest(raw)
        value['a3_packet'] = h.canonical(packet)
        value['er'] = h.canonical(fixtures.reference('ER', raw))
        result = run(value, memory)
        self.assertEqual(result['connections']['a3_to_er']['status'], 'DONE')
        self.assertEqual(result['stages']['er']['status'], 'BLOCKED')
        self.assertIsNone(result['validated_er'])


if __name__ == '__main__':
    unittest.main(verbosity=2)

"""Stage2 synthetic supplied-byte controls. No actual news/capture/admission QA."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'research'))
sys.path.insert(0, str(ROOT / 'tests'))
import a2_research_intake_v1_smoke as fixtures
import a2_a1_discovery_gate_v1 as gate

h = gate.intake
CUTOFF = fixtures.CUTOFF


def bundle(country='US'):
    event, graph, memory = fixtures.graph_event()
    event.update(materiality='HIGH', published_at=graph['sources'][0]['published_at'])
    sid, issuer, ticker, currency, mic = ('US:S0', 'CIK:0', 'S0', 'USD', 'XNAS')
    url = 'https://example.test/issuer/earnings'
    if country == 'KR':
        sid, issuer, ticker, currency, mic = ('KR:005930', 'DART:00000001', '005930', 'KRW', 'XKRX')
        event.update(security_ids=[sid], issuer_ids=[issuer], asset_ids=[sid], tickers=[ticker],
                     primary_source='REGULATOR')
        graph.update(asset_id=sid, issuer_id=issuer)
        graph['sources'][0].update(source_type='REGULATOR', source_affiliation='REGULATOR')
        url = 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260918000001'
    memory['GRAPH'] = h.canonical(graph)
    event['source_graph_sha256'] = h.digest(memory['GRAPH'])
    identity = dict(security_id=sid, issuer_id=issuer, ticker=ticker, country=country,
        currency=currency, mic=mic, valid_from='2010-01-04T00:00:00Z', valid_until=None)
    proof = dict(schema='a2-discovery-security-identity-v1', **identity,
        as_of=fixtures.T, source_url='https://example.test/security-identity')
    memory['IDENTITY'] = h.canonical(proof)
    identity['evidence_ref'] = fixtures.reference('IDENTITY', memory['IDENTITY'])
    context = dict(schema=gate.SCHEMA, identities=[identity], origins=[dict(
        event_id=event['event_id'], primary_source_id=graph['sources'][0]['source_id'],
        original_url=url, materiality_basis='Supplied operating-acceleration claim, not real research')],
        prior_event_keys=[], prior_request_event_keys=[], registry_security_ids=[], registry_theme_ids=[])
    return [event], context, memory


def select(events, context, memory, cutoff=CUTOFF):
    return gate.select_discovery(h.canonical(fixtures.envelope(events)), h.canonical(context),
        cutoff=cutoff, artifact_resolver=h.MemoryArtifacts(memory))


class DiscoveryGateTests(unittest.TestCase):
    def test_US_KR_preserve_identity_and_closed_authority(self):
        for country in ('US', 'KR'):
            with self.subTest(country=country):
                result = select(*bundle(country))
                self.assertEqual(len(result['candidates']), 1)
                row = result['candidates'][0]
                self.assertEqual(row['country'], country)
                self.assertEqual(row['identity_authentication'], 'NOT_VERIFIED')
                self.assertEqual(row['source_authentication'], 'NOT_VERIFIED')
                self.assertEqual(result['request_count'], 0)
                self.assertEqual(result['dispatch_count'], 0)
                self.assertFalse(any(result['authority'].values()))
                self.assertFalse(result['A2_Technical_eligible'])
                self.assertFalse(result['A3_input_eligible'])
        self.assertEqual(select(*bundle('KR'))['candidates'][0]['ticker'], '005930')

    def test_V1_and_V2_are_proposals_not_authentication(self):
        for tier in ('V1', 'V2'):
            events, context, memory = bundle()
            events[0]['verification_level'] = tier
            self.assertEqual(len(select(events, context, memory)['candidates']), 1)

    def test_V0_community_and_price_only_blocked(self):
        for patch in (dict(verification_level='V0'), dict(primary_source='TELEGRAM_SECONDARY'),
                      dict(primary_source='MARKET_DATA'), dict(event_family='PRICE_SPIKE')):
            events, context, memory = bundle()
            events[0].update(patch)
            result = select(events, context, memory)
            self.assertEqual(result['candidates'], [])
            self.assertEqual(result['other_events'][0]['status'], 'BLOCKED')

    def test_materiality_requires_fact_basis_and_supported_pillar(self):
        for change in ('low', 'no_fact', 'blank_fact', 'no_basis', 'wrong_pillar'):
            events, context, memory = bundle()
            if change == 'low': events[0]['materiality'] = 'LOW'
            if change == 'no_fact': events[0]['verified_fact'] = None
            if change == 'blank_fact': events[0]['verified_fact'] = ' '
            if change == 'no_basis': context['origins'][0]['materiality_basis'] = ' '
            if change == 'wrong_pillar': events[0]['affected_pillars'] = ['moat_durability']
            self.assertEqual(select(events, context, memory)['candidates'], [])

    def test_wrong_ticker_issuer_and_unknown_security_blocked(self):
        for field in ('tickers', 'issuer_ids', 'security_ids'):
            events, context, memory = bundle()
            events[0][field] = ['WRONG']
            self.assertEqual(select(events, context, memory)['candidates'], [])

    def test_currency_mic_and_KR_ticker_are_not_coerced(self):
        for field, value in (('ticker', '5930'), ('currency', 'USD'), ('mic', 'XNAS')):
            events, context, memory = bundle('KR')
            context['identities'][0][field] = value
            self.assertEqual(select(events, context, memory)['candidates'], [])

    def test_identity_hash_and_proof_subject_are_checked(self):
        for change in ('bytes', 'subject', 'expired', 'future'):
            events, context, memory = bundle()
            if change == 'bytes': memory['IDENTITY'] += b' '
            if change == 'subject':
                proof = h.decode(memory['IDENTITY']); proof['issuer_id'] = 'CIK:99'
                memory['IDENTITY'] = h.canonical(proof)
                context['identities'][0]['evidence_ref']['sha256'] = h.digest(memory['IDENTITY'])
            if change == 'expired': context['identities'][0]['evidence_ref']['expires_at'] = CUTOFF
            if change == 'future': context['identities'][0]['evidence_ref']['available_at'] = '2027-01-01T00:00:00Z'
            self.assertEqual(select(events, context, memory)['candidates'], [])

    def test_lifecycle_does_not_redirect_a_delisted_name(self):
        events, context, memory = bundle()
        context['identities'][0]['valid_until'] = CUTOFF
        self.assertEqual(select(events, context, memory)['candidates'], [])

    def test_original_publication_is_not_collection_time(self):
        for change in ('substitute', 'naive', 'future', 'expired', 'asof'):
            events, context, memory = bundle()
            if change == 'substitute': events[0]['published_at'] = events[0]['collected_at']
            if change == 'naive': events[0]['published_at'] = '2026-09-18T18:00:00'
            if change == 'future': events[0]['available_at'] = '2027-01-01T00:00:00Z'
            if change == 'expired': events[0]['expires_at'] = CUTOFF
            if change == 'asof': events[0]['collected_at'] = CUTOFF.replace('00:00:00Z', '00:00:01Z')
            try:
                result = select(events, context, memory)
            except h.IntakeError:
                continue  # Schema rejects naive clocks before row selection.
            self.assertEqual(result['candidates'], [])

    def test_graph_raw_and_primary_binding_are_checked(self):
        for change in ('raw', 'graph', 'source'):
            events, context, memory = bundle()
            if change == 'raw': memory['RAW:IR'] = b'tampered'
            if change == 'graph': memory['GRAPH'] += b' '
            if change == 'source': context['origins'][0]['primary_source_id'] = 'NEWS:1'
            self.assertEqual(select(events, context, memory)['candidates'], [])

    def test_safe_original_URL_and_exact_DART_query(self):
        for url in ('http://example.test/a', 'https://u:p@example.test/a',
                    'https://example.test/a?token=secret', 'https://example.test/a#fragment',
                    'https://example.test/a\n', 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260918000001&key=secret'):
            events, context, memory = bundle()
            context['origins'][0]['original_url'] = url
            self.assertEqual(select(events, context, memory)['candidates'], [])
        self.assertEqual(len(select(*bundle('KR'))['candidates']), 1)

    def test_duplicate_alias_events_do_not_multiply_candidates(self):
        events, context, memory = bundle()
        events.append(copy.deepcopy(events[0])); events[1]['event_id'] = 'ALIAS:1'
        origin = copy.deepcopy(context['origins'][0]); origin['event_id'] = 'ALIAS:1'
        context['origins'].append(origin)
        result = select(events, context, memory)
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(result['other_events'][0]['status'], 'DUPLICATE_PROPOSAL_ONLY')
        reordered = select(list(reversed(events)), context, memory)
        self.assertEqual(result['candidates'], reordered['candidates'])
        self.assertEqual(result['other_events'], reordered['other_events'])
        self.assertNotEqual(result['events_sha256'], reordered['events_sha256'])

    def test_retry_prior_keys_and_registry_reuse_keep_authority_closed(self):
        for field in ('prior_event_keys', 'prior_request_event_keys'):
            events, context, memory = bundle()
            key = select(events, context, memory)['candidates'][0]['event_key']
            context[field] = [key]
            result = select(events, context, memory)
            self.assertEqual(result['candidates'], [])
            self.assertEqual(result['other_events'][0]['status'], 'DUPLICATE_PROPOSAL_ONLY')
            self.assertEqual(result['request_count'], 0)
        events, context, memory = bundle()
        context['registry_security_ids'] = ['US:S0']
        self.assertTrue(select(events, context, memory)['candidates'][0]['existing_registry_candidate'])

    def test_caps_include_existing_registry_and_themes(self):
        for field, values in (('registry_security_ids', [f'US:OTHER{i}' for i in range(30)]),
                              ('registry_theme_ids', [f'OTHER{i}' for i in range(10)])):
            events, context, memory = bundle()
            context[field] = values
            with self.assertRaises(h.IntakeError): select(events, context, memory)

    def test_ambiguous_ticker_duplicate_keys_and_unknown_fields_refuse(self):
        events, context, memory = bundle()
        row = copy.deepcopy(context['identities'][0]); row['security_id'] = 'US:OTHER'
        context['identities'].append(row)
        with self.assertRaises(h.IntakeError): select(events, context, memory)
        events, context, memory = bundle(); context['extra'] = True
        with self.assertRaises(h.IntakeError): select(events, context, memory)
        with self.assertRaises(h.IntakeError):
            gate.select_discovery(h.canonical(fixtures.envelope(events)), b'{"schema":0,"schema":1}',
                cutoff=CUTOFF, artifact_resolver=h.MemoryArtifacts(memory))


if __name__ == '__main__':
    unittest.main(verbosity=2)

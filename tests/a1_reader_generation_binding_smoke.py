"""Synthetic producer/trust fixtures only, including the REAL_SOURCE code branch.

Injected trust and documents below are NOT actual accepted Source/rights proof.
No real Source/Drive/provider calls, publication or consumer ACK occur.
"""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alpaca_sip_private_backfill_v1_smoke import FakePrivateDrive
from tools import alpaca_sip_private_backfill_v1 as capture
from tools import prepare_a1_reader_generation as binding
from tools.macro_history_sources import digest, encoded
from tools.research_data_access import ContractError, PRICE_COLUMNS, ResearchDataReader

SESSIONS = ['2016-01-04', '2016-01-05']
OBSERVED = '2026-10-24T08:00:00Z'
DECISION = '2026-10-24T09:00:00Z'


def fixture(*, split_volume_override=None, missing_open=False):
    drive = FakePrivateDrive()
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        adjustment = parse_qs(urlparse(url).query)['adjustment'][0]
        rows = []
        for i, session in enumerate(SESSIONS):
            factor = 2 if i == 0 and adjustment == 'raw' else 1
            rows.append(dict(t=session + 'T05:00:00Z', o=10 * factor,
                             h=12 * factor, l=9 * factor, c=11 * factor,
                             v=100 if factor == 2 else (200 if i == 0 else 100)))
            if adjustment == 'split' and split_volume_override is not None and i == 0:
                rows[-1]['v'] = split_volume_override
            if missing_open:
                rows[-1].pop('o')
        return encoded(dict(bars={'AAPL': rows}, next_page_token=None))
    # Every source call is injected fake bytes. The existing archival primitive
    # and verifier, not a new parallel parser/collector, generate the fixture.
    refs, _, _, _ = capture.capture_one_group(
        drive, drive.folder, ['AAPL'], '2016-01-04', '2016-01-06',
        'fixture-key', 'fixture-secret', digest(b'CONTRACT_FIXTURE_SEED'),
        hashlib.sha1(b'CONTRACT_FIXTURE_SOURCE_CODE').hexdigest(), get=get)
    raw, norm, rec = (drive.objects[r['file_id']] for r in refs)
    evidence = dict(
        schema='a1-reader-binding-contract-fixture-v1', fixture_only=True,
        owner_rights='CONTRACT_FIXTURE_ONLY', corporate_actions='CONTRACT_FIXTURE_ONLY',
        lifecycle='CONTRACT_FIXTURE_ONLY', original_run_id='CONTRACT_FIXTURE:original',
        derivation_run_id='CONTRACT_FIXTURE:derivation',
        derivation_code_sha=hashlib.sha1(b'CONTRACT_FIXTURE_DERIVATION_CODE').hexdigest(),
        original_public_available_at=None, original_provider_collected_at=None,
        first_observed_readback=dict(kind='FIRST_OBSERVED_COMPLETE_READBACK', at=OBSERVED,
            objects=dict(raw_sha256=digest(raw), normalized_sha256=digest(norm),
                         capture_receipt_sha256=digest(rec))),
        created_at='2026-10-24T08:30:00Z', research_fresh_until='2026-10-25T09:00:00Z',
        identity={'AAPL': dict(instrument_id='CONTRACT_FIXTURE:US:AAPL', ticker='AAPL',
            market='US', mic='XNAS', timezone='America/New_York', calendar='NYSE',
            currency='USD', valid_from=SESSIONS[0], valid_through=SESSIONS[-1])},
        split_factors={'AAPL': {SESSIONS[0]: '2', SESSIONS[1]: '1'}})
    return raw, norm, rec, evidence, calls


class FixtureOwnerRead:
    def __init__(self, objects):
        self.objects, self.calls = dict(objects), []
        self.owner = 'fixture_owner'
    # Real production method/signature, with pure in-memory metadata below.
    # OwnerDrive is never constructed and get never makes a request.
    check = capture.OwnerDrive.check
    def get(self, path, query):
        file_id = path.removeprefix('files/')
        self.calls.append(('check', file_id))
        if path != 'files/' + file_id or file_id not in self.objects:
            raise ValueError('FIXTURE_PERMISSION')
        return dict(id=file_id, mimeType='application/json', trashed=False, shared=False,
                    parents=['fixture_parent'], permissions=[dict(id=self.owner, role='owner', type='user')])
    def read(self, file_id, limit):
        self.calls.append(('read', file_id))
        return self.objects[file_id][:limit]


def fixture_transport(basis):
    objects = [('shared-research-v1/generations/' + basis.generation_id, basis.manifest)]
    objects.extend(('shared-research-v1/objects/' + sha, raw) for sha, raw in basis.objects)
    refs, memory = [], {}
    for i, (logical, raw) in enumerate(objects):
        file_id = 'fixture_file_' + str(i)
        refs.append(binding.OwnerReference(logical, file_id, 'fixture_parent', digest(raw), len(raw)))
        memory[file_id] = raw
    owner = FixtureOwnerRead(memory)
    return binding.OwnerReferenceReadTransport(owner, tuple(refs)), owner, tuple(refs)


def real_fixture():
    """Explicit synthetic positive for strict real-code machinery, never actual proof."""
    raw, norm, rec, evidence, _ = fixture()
    receipt = json.loads(rec)
    objects = {}
    def add(value):
        value = value if type(value) is bytes else encoded(value)
        h = digest(value)
        objects[h] = value
        return dict(sha256=h, bytes=len(value))
    credential = digest(b'SYNTHETIC_TEST_EXISTING_ACCOUNT_REFERENCE')
    terms = add(b'SYNTHETIC_TEST_TERMS_NOT_AN_ACTUAL_MARKET_DATA_AGREEMENT')
    rights = add(dict(schema='a1-reviewed-account-rights-v1', provider='alpaca',
        credential_binding=credential, purpose='PRIVATE_NONCOMMERCIAL_RESEARCH',
        historical_sip_allowed=True, private_retention_allowed=True,
        source_documents=[terms], supplier_expiry=None))
    checkpoint = add(dict(schema=capture.SCHEMA, state='PRIVATE_RESEARCH_ONLY',
        source=capture.SOURCE, source_sha=receipt['source_sha'], seed_sha256=receipt['seed_sha256'],
        start=receipt['start'], end=receipt['end'], last_status='VERIFIED_RAW_SPLIT',
        last_objects=[receipt['raw_object'], receipt['normalized_object'],
                      dict(file_id='synthetic_receipt', sha256=digest(rec), bytes=len(rec))]))
    meter = add(dict(schema='a1-sip-campaign-meter-v1', run_id=987654321,
        run_attempt=1, source_sha=receipt['source_sha'], bindings=dict(credential_binding=credential),
        status='COMPLETE', finalized=True, preflight_only=False,
        checkpoint_sha256=checkpoint['sha256']))
    evidence.update(schema='a1-reader-real-evidence-v1', fixture_only=False,
        owner_rights=rights, original_execution=meter, original_checkpoint=checkpoint,
        original_run_id='987654321', derivation_run_id='synthetic-test-derivation',
        identity_evidence=add(b'SYNTHETIC_TEST_IDENTITY_DOCUMENT'),
        corporate_actions=add(b'SYNTHETIC_TEST_SPLIT_DOCUMENT'),
        lifecycle=add(b'SYNTHETIC_TEST_LIFECYCLE_DOCUMENT'),
        identity_status='VERIFIED', corporate_action_status='VERIFIED', lifecycle_status='VERIFIED',
        rights_capture_scope=dict(capture_receipt_sha256=digest(rec), start=receipt['start'],
            end_exclusive=receipt['end'], credential_binding=credential, original_run_id=987654321))
    evidence['identity']['AAPL']['instrument_id'] = 'US.TEST.AAPL'
    event = evidence['first_observed_readback']
    event['evidence_ref'] = add(encoded(event))
    review = add(b'SYNTHETIC_TEST_EXTERNALLY_INJECTED_TRUST_ANCHOR_NOT_ACTUAL_ACCEPTANCE')
    trusted = binding.TrustedSourceBinding(
        review_reference='https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-1',
        review_receipt_sha256=review['sha256'], evidence_sha256=digest(encoded(evidence)),
        proof_sha256=tuple(sorted(objects)), original_run_id=987654321, original_run_attempt=1,
        original_source_sha=receipt['source_sha'], credential_binding=credential,
        derivation_run_id=evidence['derivation_run_id'], derivation_code_sha=evidence['derivation_code_sha'],
        adapter_file_sha256=digest(Path(binding.__file__).read_bytes()))
    return raw, norm, rec, evidence, trusted, objects


def ancestor_fixture(*, held_sibling=False):
    """Synthetic path; unselected price/marker bytes deliberately do not exist."""
    state = list(real_fixture())
    raw, norm, rec, e, trusted, objects = state
    receipt = json.loads(rec)
    old = json.loads(objects.pop(e['original_checkpoint']['sha256']))
    meter = json.loads(objects.pop(e['original_execution']['sha256']))
    def add(value, file_id):
        b = encoded(value); h = digest(b); objects[h] = b
        return dict(file_id=file_id, sha256=h, bytes=len(b))
    def dummy(label):
        return dict(file_id='synthetic_' + label, sha256=digest(label.encode()), bytes=7)
    def node(names, completed, held, group, previous, *, selected=False, hold=False):
        value = dict(old, asof=receipt['asof'], examined=names, completed=completed,
            held=held, last_collected=[] if hold else group, last_no_bars=[],
            last_held=group if hold else [], previous_checkpoint=previous,
            source_admission=False, pit_verified=False, historical_identity_verified=False,
            commercial_use_authorized=False,
            last_status='HELD_BAR_VALUE' if hold else 'VERIFIED_RAW_SPLIT')
        if not selected:
            value['last_objects'] = ([dummy('held_marker')] if hold else
                [dummy('sibling_raw'), dummy('sibling_norm'), dummy('sibling_receipt')])
        return value
    parent = add(node(['PRIOR'], ['PRIOR'], [], ['PRIOR'], None), 'synthetic_parent_checkpoint')
    selected = add(node(['PRIOR', 'AAPL'], ['PRIOR', 'AAPL'], [], ['AAPL'], parent,
                        selected=True), 'synthetic_selected_checkpoint')
    previous = selected
    path = [selected]
    names, done, held = ['PRIOR', 'AAPL'], ['PRIOR', 'AAPL'], []
    if held_sibling:
        names = names + ['HELD']; held = ['HELD']
        previous = add(node(names, done, held, ['HELD'], selected, hold=True),
                       'synthetic_held_checkpoint')
        path.insert(0, previous)
    final = add(node(names + ['SIBLING'], done + ['SIBLING'], held, ['SIBLING'], previous),
                'synthetic_final_checkpoint')
    meter.update(checkpoint_sha256=final['sha256'], parent_checkpoint_sha256=parent['sha256'],
                 examined_before=1, examined_after=len(names) + 1)
    e.update(original_checkpoint=final, original_checkpoint_path=path,
             original_parent_checkpoint=parent,
             original_execution=add(meter, 'synthetic_original_meter'))
    return state


def rewrite_ancestor(state, transform, *, relink=True):
    """Rehash synthetic ancestors so negative tests exercise semantics, not stale pins."""
    e, objects = state[3], state[5]
    refs = [e['original_checkpoint']] + e['original_checkpoint_path']
    nodes = [json.loads(objects.pop(r['sha256'])) for r in refs]
    transform(nodes)
    changed = [None] * len(refs)
    for i in reversed(range(len(refs))):
        if relink and i + 1 < len(refs):
            nodes[i]['previous_checkpoint'] = changed[i + 1]
        b = encoded(nodes[i]); h = digest(b); objects[h] = b
        changed[i] = dict(refs[i], sha256=h, bytes=len(b))
    e['original_checkpoint'], e['original_checkpoint_path'] = changed[0], changed[1:]
    meter = json.loads(objects.pop(e['original_execution']['sha256']))
    meter['checkpoint_sha256'] = changed[0]['sha256']
    b = encoded(meter); h = digest(b); objects[h] = b
    e['original_execution'] = dict(e['original_execution'], sha256=h, bytes=len(b))


class BindingTest(unittest.TestCase):
    def setUp(self):
        self.raw, self.norm, self.rec, self.evidence, self.calls = fixture()

    def prepare(self, **kwargs):
        options = dict(classification='CONTRACT_FIXTURE', decision_time=DECISION)
        options.update(kwargs)
        with patch.object(capture, 'http', side_effect=AssertionError('PROVIDER_REQUEST')), \
             patch.object(capture, 'OwnerDrive', side_effect=AssertionError('OWNER_CONSTRUCTION')):
            return binding.prepare(self.raw, self.norm, self.rec, encoded(self.evidence), **options)

    def blocked(self, code, **kwargs):
        with self.assertRaisesRegex(binding.BindingError, '^' + code + '$'):
            self.prepare(**kwargs)

    def read(self, basis, **kwargs):
        transport, owner, _ = fixture_transport(basis)
        self.assertEqual(owner.calls, [])  # constructing transport does no I/O
        options = dict(decision_time=DECISION, purpose='research',
                       instrument_ids=['CONTRACT_FIXTURE:US:AAPL'], required_start=SESSIONS[0],
                       required_end=SESSIONS[-1], minimum_rows=2, required_sessions=SESSIONS,
                       consumer_id='CONTRACT_FIXTURE:reader')
        options.update(kwargs)
        return ResearchDataReader(transport).read('ds.us.prices.daily', basis.generation_id, **options)

    def test_both_typed_bases_read_without_network_or_publication(self):
        result = self.prepare()
        self.assertEqual(len(self.calls), 2)  # fake source, not actual provider GETs
        self.assertEqual(result.status, 'CONTRACT_FIXTURE_PREPARED')
        self.assertEqual(result.blockers, ())
        self.assertEqual([b.basis for b in result.bases], ['RAW', 'SPLIT_ADJUSTED'])
        self.assertNotEqual(result.bases[0].generation_id, result.bases[1].generation_id)
        for basis in result.bases:
            a = self.read(basis, consumer_id='CONTRACT_FIXTURE:coverage')
            b = self.read(basis, consumer_id='CONTRACT_FIXTURE:feature-interface')
            self.assertEqual(a.rows, b.rows)
            self.assertEqual(a.receipt['row_set_sha256'], b.receipt['row_set_sha256'])
            self.assertEqual(a.receipt['classification'], 'CONTRACT_FIXTURE')
            self.assertEqual(a.receipt['pit_status'], 'PIT_PROXY')
            self.assertFalse(a.receipt['eligible_for_economics'])
            self.assertFalse(a.receipt['eligible_for_selector'])
            self.assertEqual(a.receipt['provider_refresh_count'], 0)
            self.assertEqual(set(a.rows[0]), set(PRICE_COLUMNS))
            self.assertEqual(a.rows[0]['available_from'], OBSERVED)
            self.assertIs(type(a.rows[0]['open']), float)

    def test_provenance_precedes_manifest_without_hash_cycle(self):
        for basis in self.prepare().bases:
            manifest, provenance = json.loads(basis.manifest), json.loads(basis.provenance)
            source = manifest['datasets'][0]['source']
            self.assertEqual(source['source_receipt_sha256'], digest(basis.provenance))
            self.assertEqual(provenance['derived_objects'], [sha for sha, _ in basis.objects])
            self.assertEqual(provenance['original_objects']['raw_sha256'], digest(self.raw))
            self.assertEqual(provenance['original_objects']['capture_receipt_sha256'], digest(self.rec))
            self.assertNotEqual(provenance['original_source_sha'], provenance['derivation_code_sha'])
            self.assertEqual(source['producer_code_sha'], provenance['derivation_code_sha'])
            self.assertEqual(provenance['adapter_file_sha256'], digest(Path(binding.__file__).read_bytes()))
            self.assertNotIn('manifest_sha256', provenance)
            self.assertEqual(provenance['original_clocks_status'], 'UNKNOWN')
            self.assertIsNone(provenance['supplier_rights_expiry'])
            self.assertEqual(provenance['storage_publication'], 'NOT_RUN')
            self.assertEqual(provenance['consumer_ack'], 'NOT_RUN')

    def test_integrated_component_reader_two_consumers_and_optional_spy(self):
        basis = self.prepare().bases[0]
        transport, owner, _ = fixture_transport(basis)
        options = dict(decision_time=DECISION, purpose='research', components=[
            dict(component_id='subject', instrument_id='CONTRACT_FIXTURE:US:AAPL',
                 required_start=SESSIONS[0], required_end=SESSIONS[-1], minimum_rows=2,
                 required_sessions=SESSIONS, optional=False),
            dict(component_id='spy', instrument_id='CONTRACT_FIXTURE:US:SPY',
                 required_start=SESSIONS[0], required_end=SESSIONS[-1], minimum_rows=2,
                 required_sessions=SESSIONS, optional=True)])
        results = []
        for consumer in ('coverage', 'feature-interface'):
            before = len(owner.calls)
            result = ResearchDataReader(transport).read_components(
                'ds.us.prices.daily', basis.generation_id,
                consumer_id='CONTRACT_FIXTURE:' + consumer, **options)
            self.assertEqual(result.refusals['spy'], 'MISSING_INSTRUMENT')
            self.assertNotIn('spy', result.results)
            self.assertFalse(result.receipt['whole_generation_verified'])
            self.assertEqual(result.receipt['validation_scope'], 'REQUESTED_COMPONENTS_ONLY')
            # One exact manifest and one price object per independent call.
            self.assertEqual(len(owner.calls) - before, 4)
            subject = result.results['subject']
            self.assertEqual(subject.receipt['classification'], 'CONTRACT_FIXTURE')
            self.assertFalse(subject.receipt['eligible_for_economics'])
            results.append(subject)
        self.assertEqual(results[0].rows, results[1].rows)
        self.assertEqual(results[0].receipt['row_set_sha256'], results[1].receipt['row_set_sha256'])

    def test_required_spy_absence_cannot_become_successful_component_batch(self):
        basis = self.prepare().bases[0]
        transport, owner, _ = fixture_transport(basis)
        with self.assertRaisesRegex(ContractError, '^MISSING_INSTRUMENT$'):
            ResearchDataReader(transport).read_components(
                'ds.us.prices.daily', basis.generation_id, decision_time=DECISION,
                purpose='research', consumer_id='CONTRACT_FIXTURE:required-spy',
                components=[dict(component_id='spy', instrument_id='CONTRACT_FIXTURE:US:SPY',
                    required_start=SESSIONS[0], required_end=SESSIONS[-1], minimum_rows=2,
                    required_sessions=SESSIONS, optional=False)])
        self.assertEqual([kind for kind, _ in owner.calls], ['check', 'read'])

    def paired_component_fixture(self, basis=None):
        """Reader-only synthetic sibling; not another original capture or ACK."""
        basis = basis or self.prepare().bases[0]
        manifest = json.loads(basis.manifest)
        item = json.loads(encoded(manifest['datasets'][0]['files'][0]))
        item['instrument'].update(instrument_id='CONTRACT_FIXTURE:US:MSFT', ticker='MSFT')
        rows = [json.loads(line) for line in basis.objects[0][1].splitlines()]
        for row in rows:
            row.update(instrument_id='CONTRACT_FIXTURE:US:MSFT', ticker='MSFT')
        raw = b''.join(encoded(row) for row in rows)
        item.update(sha256=digest(raw), bytes=len(raw))
        manifest['datasets'][0]['files'].append(item)
        basis = replace(basis, manifest=encoded(manifest),
                        objects=basis.objects + ((digest(raw), raw),))
        options = dict(decision_time=DECISION, purpose='research',
            consumer_id='CONTRACT_FIXTURE:transport-integrity', components=[
                dict(component_id='subject', instrument_id='CONTRACT_FIXTURE:US:AAPL',
                     required_start=SESSIONS[0], required_end=SESSIONS[-1], minimum_rows=2,
                     required_sessions=SESSIONS, optional=False),
                dict(component_id='sibling', instrument_id='CONTRACT_FIXTURE:US:MSFT',
                     required_start=SESSIONS[0], required_end=SESSIONS[-1], minimum_rows=2,
                     required_sessions=SESSIONS, optional=True)])
        return basis, options

    def test_owner_transport_normal_components_preserve_both_bases(self):
        for original in self.prepare().bases:
            with self.subTest(basis=original.basis):
                basis, options = self.paired_component_fixture(original)
                transport, owner, _ = fixture_transport(basis)
                self.assertEqual(owner.calls, [])
                result = ResearchDataReader(transport).read_components(
                    'ds.us.prices.daily', basis.generation_id, **options)
                self.assertEqual(set(result.results), {'subject', 'sibling'})
                self.assertEqual(result.refusals, {})
                self.assertTrue(all(len(x.rows) == 2 for x in result.results.values()))
                self.assertFalse(result.receipt['eligible_for_economics'])

    def test_owner_transport_component_hash_mismatch_is_global_like_plain_transport(self):
        basis, options = self.paired_component_fixture()
        for optional in (True, False):
            for mode in ('owner', 'plain'):
                with self.subTest(optional=optional, transport=mode):
                    transport, owner, refs = fixture_transport(basis)
                    target = refs[-1]
                    raw = owner.objects[target.file_id]
                    owner.objects[target.file_id] = bytes([raw[0] ^ 1]) + raw[1:]
                    if mode == 'plain':
                        class Plain:
                            def read(self, path):
                                ref = next(r for r in refs if r.logical_path == path)
                                return owner.objects[ref.file_id]
                        transport = Plain()
                    options['components'][1]['optional'] = optional
                    with self.assertRaisesRegex(ContractError, '^HASH_MISMATCH$'):
                        ResearchDataReader(transport).read_components(
                            'ds.us.prices.daily', basis.generation_id, **options)

    def test_owner_transport_component_readback_type_and_size_are_global(self):
        basis, options = self.paired_component_fixture()
        for optional in (True, False):
            for kind in ('nonbytes', 'empty', 'short', 'over', 'reference_size'):
                with self.subTest(optional=optional, corruption=kind):
                    transport, owner, refs = fixture_transport(basis)
                    target, original_read = refs[-1], owner.read
                    raw = owner.objects[target.file_id]
                    if kind == 'reference_size':
                        transport = binding.OwnerReferenceReadTransport(owner,
                            refs[:-1] + (replace(target, bytes=target.bytes + 1),))
                        payload = None
                    else:
                        payload = {'nonbytes': bytearray(raw), 'empty': b'',
                                   'short': raw[:-1], 'over': raw + b'!'}[kind]
                    def returned(file_id, limit):
                        if file_id == target.file_id and payload is not None:
                            return payload
                        return original_read(file_id, limit)
                    options['components'][1]['optional'] = optional
                    with patch.object(owner, 'read', side_effect=returned), \
                         self.assertRaisesRegex(ContractError, '^OBJECT_SIZE$'):
                        ResearchDataReader(transport).read_components(
                            'ds.us.prices.daily', basis.generation_id, **options)

    def test_owner_transport_actual_unavailability_keeps_optional_semantics(self):
        basis, options = self.paired_component_fixture()
        for optional in (True, False):
            for error in (OSError('SYNTHETIC_UNAVAILABLE'), ValueError('SYNTHETIC_UNAVAILABLE')):
                with self.subTest(optional=optional, error=type(error).__name__):
                    transport, owner, refs = fixture_transport(basis)
                    target, original_read = refs[-1], owner.read
                    def unavailable(file_id, limit):
                        if file_id == target.file_id:
                            raise error
                        return original_read(file_id, limit)
                    options['components'][1]['optional'] = optional
                    with patch.object(owner, 'read', side_effect=unavailable):
                        if optional:
                            result = ResearchDataReader(transport).read_components(
                                'ds.us.prices.daily', basis.generation_id, **options)
                            self.assertEqual(set(result.results), {'subject'})
                            self.assertEqual(result.refusals, {'sibling': 'ARCHIVE_UNAVAILABLE'})
                        else:
                            with self.assertRaisesRegex(ContractError, '^ARCHIVE_UNAVAILABLE$'):
                                ResearchDataReader(transport).read_components(
                                    'ds.us.prices.daily', basis.generation_id, **options)

    def test_reader_preserves_transport_contract_integrity_codes(self):
        basis, options = self.paired_component_fixture()
        for code in ('HASH_MISMATCH', 'OBJECT_SIZE'):
            for optional in (True, False):
                with self.subTest(code=code, optional=optional):
                    transport, owner, refs = fixture_transport(basis)
                    target, original_read = refs[-1], owner.read
                    def integrity_failure(file_id, limit):
                        if file_id == target.file_id:
                            raise ContractError(code)
                        return original_read(file_id, limit)
                    options['components'][1]['optional'] = optional
                    with patch.object(owner, 'read', side_effect=integrity_failure), \
                         self.assertRaisesRegex(ContractError, '^' + code + '$'):
                        ResearchDataReader(transport).read_components(
                            'ds.us.prices.daily', basis.generation_id, **options)

    def test_stable_replay_and_immutable_return(self):
        one, two = self.prepare(), self.prepare()
        self.assertEqual(one, two)
        with self.assertRaises(FrozenInstanceError):
            one.status = 'VERIFIED'
        with self.assertRaises(TypeError):
            one.bases[0].objects[0] = ('bad', b'bad')

    def test_real_source_reports_missing_gates_without_generation(self):
        self.evidence = {}
        result = self.prepare(classification='REAL_SOURCE')
        self.assertEqual(result.status, 'BLOCKED')
        self.assertEqual(result.bases, ())
        self.assertIn('MISSING_OWNER_RIGHTS', result.blockers)
        self.assertIn('MISSING_DECISION_WINDOW', result.blockers)

    def test_caller_verified_claims_do_not_create_real_acceptance(self):
        self.evidence = {k: 'VERIFIED' for k in binding.REAL_GATES}
        result = self.prepare(classification='REAL_SOURCE')
        self.assertEqual(result.blockers, ('TRUSTED_SOURCE_BINDING_REQUIRED',))
        self.assertEqual(result.bases, ())

    def test_fixture_evidence_cannot_be_omitted(self):
        for key in ('owner_rights', 'corporate_actions', 'lifecycle'):
            with self.subTest(key=key):
                original = self.evidence.pop(key)
                self.blocked('FIXTURE_EVIDENCE_REQUIRED')
                self.evidence[key] = original

    def test_fixture_marker_and_real_identity_refused(self):
        self.evidence['fixture_only'] = False
        self.blocked('FIXTURE_MARKER')
        self.evidence['fixture_only'] = True
        self.evidence['identity']['AAPL']['instrument_id'] = 'REAL:AAPL'
        self.blocked('IDENTITY_SCOPE')

    def test_missing_raw_bytes_or_rebound_receipt_is_not_proof(self):
        self.raw = self.raw[:-1]
        self.blocked('CAPTURE_OBJECT_BINDING')
        receipt = json.loads(self.rec)
        receipt['raw_object'].update(sha256=digest(self.raw), bytes=len(self.raw))
        self.rec = encoded(receipt)
        self.blocked('ORIGINAL_CAPTURE_VERIFICATION')

    def test_rebound_normalized_bytes_still_need_original_agreement(self):
        import gzip
        rows = gzip.decompress(self.norm).replace(b'"open":"20"', b'"open":"21"')
        self.norm = gzip.compress(rows, mtime=0)
        receipt = json.loads(self.rec)
        receipt['normalized_object'].update(sha256=digest(self.norm), bytes=len(self.norm))
        self.rec = encoded(receipt)
        self.blocked('ORIGINAL_CAPTURE_VERIFICATION')

    def test_readback_clock_must_bind_all_three_originals(self):
        self.evidence['first_observed_readback']['objects']['capture_receipt_sha256'] = '0' * 64
        self.blocked('FIRST_OBSERVED_BINDING')

    def test_original_clock_cannot_be_invented_from_bar_date(self):
        self.evidence['original_public_available_at'] = '2016-01-04T21:00:00Z'
        self.blocked('UNKNOWN_ORIGINAL_CLOCKS_ONLY')

    def test_old_cutoff_and_expired_research_window_refuse(self):
        self.blocked('DECISION_WINDOW', decision_time='2016-01-06T00:00:00Z')
        self.blocked('DECISION_WINDOW', decision_time='2026-10-26T00:00:00Z')

    def test_naive_clock_refused(self):
        self.evidence['first_observed_readback']['at'] = '2026-10-24T08:00:00'
        self.blocked('EXPLICIT_CLOCK_REQUIRED')

    def test_lifecycle_window_cannot_cover_outside_identity(self):
        self.evidence['identity']['AAPL']['valid_from'] = '2016-01-05'
        self.blocked('LIFECYCLE_WINDOW')

    def test_exchange_calendar_and_close_are_used(self):
        self.evidence['first_observed_readback']['at'] = '2016-01-04T19:00:00Z'
        self.blocked('ROW_NOT_AVAILABLE')
        with self.assertRaisesRegex(binding.BindingError, 'EXCHANGE_SESSION'):
            with patch.object(binding, '_session_close', side_effect=ContractError('INVALID_EXCHANGE_SESSION')):
                self.evidence['first_observed_readback']['at'] = OBSERVED
                self.prepare()

    def test_split_factors_must_cover_exact_grid(self):
        self.evidence['split_factors']['AAPL'].pop(SESSIONS[1])
        self.blocked('SPLIT_FACTOR_COVERAGE')

    def test_inverse_volume_and_price_factor_cannot_be_relabelled(self):
        self.evidence['split_factors']['AAPL'][SESSIONS[0]] = '1'
        self.blocked('SPLIT_FACTOR_RELATION')

    def test_volume_relation_refused_even_when_all_prices_match(self):
        self.raw, self.norm, self.rec, self.evidence, self.calls = fixture(split_volume_override=199)
        self.blocked('SPLIT_FACTOR_RELATION')

    def test_actual_missing_open_is_refused_by_original_parser(self):
        with self.assertRaisesRegex(capture.Refused, '^BAR_VALUE$'):
            fixture(missing_open=True)

    def test_decoded_row_and_view_budgets_refuse(self):
        for name, value, code in (('MAX_DECODED', 1, 'DECODED_BOUND'),
                                  ('MAX_ROWS', 1, 'ROW_BOUND'),
                                  ('MAX_VIEW', 1, 'VIEW_BOUND')):
            with self.subTest(name=name), patch.object(binding, name, value):
                self.blocked(code)

    def test_decimal_context_is_not_an_implicit_parameter(self):
        from decimal import localcontext
        with localcontext() as context:
            context.prec = 1
            result = self.prepare()
        self.assertEqual(result.status, 'CONTRACT_FIXTURE_PREPARED')

    def test_decimal_exponents_rounding_and_traps_are_not_implicit(self):
        from decimal import Inexact, ROUND_FLOOR, localcontext
        with localcontext() as context:
            context.prec, context.Emax, context.Emin, context.clamp = 1, 0, 0, 1
            context.rounding = ROUND_FLOOR
            context.traps[Inexact] = True
            result = self.prepare()
        self.assertEqual(result, self.prepare())

    def test_numeric_policy_does_not_fill_open_or_round_prices(self):
        for value, volume, code in ((None, False, 'DECIMAL_STRING_REQUIRED'),
                ('0', False, 'NUMERIC_VALUE'), ('NaN', False, 'NUMERIC_VALUE'),
                ('1.234567890123456789', False, 'PRICE_PRECISION'),
                ('0.1', True, 'VOLUME_PRECISION'), ('9007199254740993', True, 'VOLUME_PRECISION')):
            with self.subTest(value=value):
                with self.assertRaisesRegex(binding.BindingError, '^' + code + '$'):
                    binding._decimal(value, volume=volume)

    def test_pit_proxy_fixture_cannot_train_or_backtest(self):
        basis = self.prepare().bases[0]
        for purpose in ('training', 'backtest'):
            with self.subTest(purpose=purpose), self.assertRaisesRegex(ContractError, 'PURPOSE_NOT_LICENSED'):
                self.read(basis, purpose=purpose)

    def test_optional_spy_absence_cannot_be_substituted(self):
        with self.assertRaisesRegex(ContractError, 'MISSING_INSTRUMENT'):
            self.read(self.prepare().bases[0], instrument_ids=['CONTRACT_FIXTURE:US:SPY'])

    def test_transport_only_reads_exact_bound_refs(self):
        transport, owner, refs = fixture_transport(self.prepare().bases[0])
        self.assertEqual(owner.calls, [])
        self.assertEqual(transport.read(refs[0].logical_path), owner.objects[refs[0].file_id])
        self.assertEqual([x[0] for x in owner.calls], ['check', 'read'])
        for logical in ('shared-research-v1/generations/latest', '../escape',
                        'shared-research-v1/objects/' + '0' * 64):
            with self.assertRaisesRegex(binding.BindingError, 'UNBOUND_LOGICAL_REFERENCE'):
                transport.read(logical)
        with self.assertRaisesRegex(binding.BindingError, 'READ_ONLY_TRANSPORT'):
            transport.write('anything', b'anything')

    def test_real_owner_check_requires_explicit_file_mode(self):
        transport, owner, refs = fixture_transport(self.prepare().bases[0])
        with self.assertRaisesRegex(capture.Refused, '^DRIVE_FOLDER$'):
            owner.check(refs[0].file_id, refs[0].parent_id)
        self.assertEqual(transport.read(refs[0].logical_path), owner.objects[refs[0].file_id])

    def test_transport_readback_hash_and_size_must_match(self):
        transport, owner, refs = fixture_transport(self.prepare().bases[0])
        original = owner.objects[refs[0].file_id]
        for raw, code in ((b'bad', 'OBJECT_SIZE'),
                          (bytes([original[0] ^ 1]) + original[1:], 'HASH_MISMATCH')):
            owner.objects[refs[0].file_id] = raw
            with self.subTest(code=code), self.assertRaisesRegex(ContractError, '^' + code + '$'):
                transport.read(refs[0].logical_path)

    def test_reference_snapshot_does_not_follow_mutable_inputs(self):
        _, owner, refs = fixture_transport(self.prepare().bases[0])
        with self.assertRaisesRegex(binding.BindingError, 'REFERENCE_BOUND'):
            binding.OwnerReferenceReadTransport(owner, list(refs))
        for bad, code in ((replace(refs[0], bytes=True), 'REFERENCE_SIZE'),
                          (replace(refs[0], bytes=2 ** 30), 'REFERENCE_SIZE'),
                          (replace(refs[0], logical_path='../escape'), 'LOGICAL_REFERENCE'),
                          (replace(refs[0], sha256='0' * 64), 'LOGICAL_REFERENCE')):
            with self.subTest(code=code), self.assertRaisesRegex(binding.BindingError, code):
                binding.OwnerReferenceReadTransport(owner, (bad,))
        with self.assertRaisesRegex(binding.BindingError, 'DUPLICATE_REFERENCE'):
            binding.OwnerReferenceReadTransport(owner, (refs[0], refs[0]))

    def test_duplicate_json_keys_and_decode_bounds_refuse(self):
        with self.assertRaisesRegex(binding.BindingError, 'DUPLICATE_JSON_KEY'):
            binding.prepare(b'', b'', b'', b'{"fixture_only":true,"fixture_only":false}',
                            decision_time=DECISION, classification='CONTRACT_FIXTURE')
        with self.assertRaisesRegex(binding.BindingError, 'INPUT_BYTE_BOUND'):
            binding.prepare(b'', b'', b'', b'x' * (1024 * 1024 + 1), decision_time=DECISION,
                            classification='CONTRACT_FIXTURE')

    def prepare_real(self, state=None, *, repin=False, decision=DECISION):
        raw, norm, rec, e, trusted, objects = state or real_fixture()
        if repin:
            trusted = replace(trusted, evidence_sha256=digest(encoded(e)), proof_sha256=tuple(sorted(objects)))
        with patch.object(capture, 'http', side_effect=AssertionError('PROVIDER_REQUEST')), \
             patch.object(capture, 'OwnerDrive', side_effect=AssertionError('OWNER_CONSTRUCTION')):
            return binding.prepare(raw, norm, rec, encoded(e), decision_time=decision,
                trusted_source=trusted, proof_objects=tuple(sorted(objects.items())))

    def assert_real_blocked(self, state, code, **kwargs):
        result = self.prepare_real(state, **kwargs)
        self.assertEqual(result.status, 'BLOCKED')
        self.assertEqual(result.blockers, (code,))
        self.assertEqual(result.bases, ())

    def replace_real_proof(self, state, field, transform):
        raw, norm, rec, e, trusted, objects = state
        ref = e[field]
        value = json.loads(objects.pop(ref['sha256']))
        transform(value)
        changed = encoded(value)
        ref.update(sha256=digest(changed), bytes=len(changed))
        objects[digest(changed)] = changed

    def test_synthetic_real_branch_prepares_both_bases_without_admission(self):
        state = real_fixture()
        result = self.prepare_real(state)
        self.assertEqual(result.status, 'REAL_SOURCE_PREPARED_UNADMITTED')
        self.assertEqual(result.blockers, ())
        self.assertEqual(result, self.prepare_real(state))
        for basis in result.bases:
            source = json.loads(basis.manifest)['datasets'][0]['source']
            provenance = json.loads(basis.provenance)
            self.assertEqual(source['classification'], 'REAL_SOURCE')
            self.assertEqual(source['pit_status'], 'PIT_PROXY')
            self.assertEqual(source['admission_state'], 'RESEARCH_BYTES_ONLY')
            self.assertEqual(source['eligible_purposes'], ['research', 'discovery'])
            self.assertEqual(source['source_receipt_sha256'], digest(basis.provenance))
            self.assertIsNone(provenance['original_public_available_at'])
            self.assertIsNone(provenance['supplier_rights_expiry'])
            self.assertFalse(provenance['fixture_only'])
            self.assertEqual(provenance['consumer_ack'], 'NOT_RUN')
            transport, _, _ = fixture_transport(basis)
            result = ResearchDataReader(transport).read('ds.us.prices.daily', basis.generation_id,
                decision_time=DECISION, purpose='research', instrument_ids=['US.TEST.AAPL'],
                required_start=SESSIONS[0], required_end=SESSIONS[-1], minimum_rows=2,
                required_sessions=SESSIONS, consumer_id='SYNTHETIC_TEST_CONSUMER_NOT_ACTUAL_ACK')
            self.assertFalse(result.receipt['eligible_for_economics'])
            self.assertEqual(result.receipt['pit_status'], 'PIT_PROXY')

    def test_real_evidence_substitution_cannot_update_its_trust_anchor(self):
        state = real_fixture();state[3]['created_at'] = '2026-10-24T08:31:00Z'
        self.assert_real_blocked(state, 'REVIEWED_EVIDENCE_HASH')

    def test_real_untrusted_review_boolean_or_mapping_is_refused(self):
        state = list(real_fixture());state[4] = dict(reviewed=True, **state[4].__dict__)
        self.assert_real_blocked(state, 'TRUSTED_SOURCE_BINDING_REQUIRED')

    def test_real_missing_or_changed_proof_bytes_are_refused(self):
        for change in ('missing', 'changed', 'extra'):
            state = real_fixture();objects = state[5];h = state[3]['owner_rights']['sha256']
            if change == 'missing': objects.pop(h)
            elif change == 'changed': objects[h] += b'x'
            else: objects[digest(b'extra')] = b'extra'
            self.assert_real_blocked(state, 'PROOF_OBJECT_HASH' if change == 'changed' else 'REVIEWED_PROOF_SET')

    def test_real_existing_account_binding_must_match_rights_and_meter(self):
        for field in ('owner_rights', 'original_execution'):
            state = real_fixture()
            def alter(value):
                target = value if field == 'owner_rights' else value['bindings']
                target['credential_binding'] = digest(b'SYNTHETIC_OTHER_ACCOUNT')
            self.replace_real_proof(state, field, alter)
            self.assert_real_blocked(state, 'WAIT_OWNER_EVIDENCE' if field == 'owner_rights'
                                     else 'ORIGINAL_EXECUTION_BINDING', repin=True)

    def test_real_provider_or_rights_purpose_cannot_be_relabelled(self):
        for key, value in (('provider', 'twelve'), ('purpose', 'COMMERCIAL'),
                           ('private_retention_allowed', False), ('historical_sip_allowed', False)):
            state = real_fixture()
            self.replace_real_proof(state, 'owner_rights', lambda d: d.update({key:value}))
            self.assert_real_blocked(state, 'WAIT_OWNER_EVIDENCE', repin=True)

    def test_real_source_run_code_checkpoint_and_capture_scope_are_bound(self):
        for field, key, value, code in (
            ('original_execution','run_id',123,'ORIGINAL_EXECUTION_BINDING'),
            ('original_execution','finalized',False,'ORIGINAL_EXECUTION_BINDING'),
            ('original_execution','preflight_only',True,'ORIGINAL_EXECUTION_BINDING'),
            ('original_execution','source_sha','0'*40,'ORIGINAL_EXECUTION_BINDING'),
            ('original_checkpoint','start','2017-01-01','ORIGINAL_EXECUTION_BINDING')):
            state = real_fixture()
            self.replace_real_proof(state, field, lambda d: d.update({key:value}))
            self.assert_real_blocked(state, code, repin=True)
        state=real_fixture();state[3]['rights_capture_scope']['end_exclusive']='2026-01-01'
        self.assert_real_blocked(state,'RIGHTS_CAPTURE_SCOPE',repin=True)

    def test_real_fixture_marker_or_identity_cannot_be_promoted(self):
        state=real_fixture();state[3]['fixture_only']=True
        self.assert_real_blocked(state,'REAL_EVIDENCE_SCHEMA',repin=True)
        state=real_fixture();state[3]['identity']['AAPL']['instrument_id']='CONTRACT_FIXTURE:US:AAPL'
        self.assert_real_blocked(state,'IDENTITY_SCOPE',repin=True)

    def test_real_unknown_window_proofs_or_missing_source_document_block(self):
        for field in ('identity_status','corporate_action_status','lifecycle_status'):
            state=real_fixture();state[3][field]='UNKNOWN'
            self.assert_real_blocked(state,'WINDOW_PROOF_UNKNOWN',repin=True)
        state=real_fixture();state[3].pop('corporate_actions')
        self.assert_real_blocked(state,'MISSING_OR_UNTRUSTED_PROOF',repin=True)

    def test_real_first_observed_clock_and_original_unknown_boundary(self):
        state=real_fixture();state[3]['first_observed_readback']['objects']['raw_sha256']='0'*64
        self.assert_real_blocked(state,'FIRST_OBSERVED_BINDING',repin=True)
        state=real_fixture();state[3]['original_public_available_at']='2016-01-04T21:00:00Z'
        self.assert_real_blocked(state,'UNKNOWN_ORIGINAL_CLOCKS_ONLY',repin=True)
        self.assert_real_blocked(real_fixture(),'DECISION_WINDOW',decision='2016-01-06T00:00:00Z')
        self.assert_real_blocked(real_fixture(),'DECISION_WINDOW',decision='2026-10-26T00:00:00Z')

    def test_real_actual_supplier_expiry_separate_from_research_freshness(self):
        state=real_fixture()
        self.replace_real_proof(state,'owner_rights',lambda d:d.update(supplier_expiry='2026-10-24T08:59:59Z'))
        self.assert_real_blocked(state,'SUPPLIER_RIGHTS_EXPIRED',repin=True)

    def test_real_reader_reuse_cannot_outlive_supplied_supplier_expiry(self):
        state=real_fixture()
        expiry='2026-10-24T10:00:00Z'
        self.replace_real_proof(state,'owner_rights',lambda d:d.update(supplier_expiry=expiry))
        prepared=self.prepare_real(state,repin=True)
        self.assertEqual(prepared.status,'REAL_SOURCE_PREPARED_UNADMITTED')
        for basis in prepared.bases:
            source=json.loads(basis.manifest)['datasets'][0]['source']
            provenance=json.loads(basis.provenance)
            self.assertEqual(source['expires_at'],expiry)
            self.assertEqual(provenance['supplier_rights_expiry'],expiry)
            self.assertEqual(provenance['research_fresh_until'],state[3]['research_fresh_until'])
            self.assertEqual(provenance['effective_reader_expires_at'],expiry)
            transport,_,_=fixture_transport(basis)
            reader=ResearchDataReader(transport)
            options=dict(purpose='research',instrument_ids=['US.TEST.AAPL'],
                required_start=SESSIONS[0],required_end=SESSIONS[-1],minimum_rows=2,
                consumer_id='SYNTHETIC_TEST_EXPIRY')
            self.assertEqual(len(reader.read('ds.us.prices.daily',basis.generation_id,
                decision_time=DECISION,**options).rows),2)
            with self.assertRaisesRegex(ContractError,'^STALE_GENERATION$'):
                reader.read('ds.us.prices.daily',basis.generation_id,
                    decision_time='2026-10-24T11:00:00Z',**options)

    def test_real_corrupt_deflate_returns_blocked_without_partial_bases(self):
        state=list(real_fixture())
        # Valid gzip header, reserved DEFLATE block type, synthetic footer.
        state[1]=b'\x1f\x8b\x08\x00'+b'\x00'*6+b'\x07'+b'\x00'*8
        receipt=json.loads(state[2])
        receipt['normalized_object'].update(sha256=digest(state[1]),bytes=len(state[1]))
        state[2]=encoded(receipt)
        self.assert_real_blocked(state,'ORIGINAL_CAPTURE_VERIFICATION')

    def test_real_ca_numeric_and_lifecycle_checks_remain_mandatory(self):
        state=real_fixture();state[3]['split_factors']['AAPL'][SESSIONS[0]]='1'
        self.assert_real_blocked(state,'SPLIT_FACTOR_RELATION',repin=True)
        state=real_fixture();state[3]['identity']['AAPL']['valid_from']=SESSIONS[1]
        self.assert_real_blocked(state,'LIFECYCLE_WINDOW',repin=True)

    def test_real_derivation_code_and_loaded_adapter_are_pinned(self):
        state=real_fixture();state[3]['derivation_code_sha']='0'*40
        self.assert_real_blocked(state,'DERIVATION_BINDING',repin=True)
        state=list(real_fixture());state[4]=replace(state[4],adapter_file_sha256='0'*64)
        self.assert_real_blocked(state,'REVIEWED_ADAPTER_HASH')

    def test_real_malformed_evidence_is_finite_and_has_no_partial_output(self):
        for raw in (b'{',b'{"x":1,"x":2}',b'[]'):
            result=binding.prepare(b'',b'',b'',raw,decision_time=DECISION)
            self.assertEqual(result.status,'BLOCKED');self.assertEqual(result.bases,())

    def test_real_proof_resource_limits_apply_before_preparation(self):
        state=real_fixture()
        with patch.object(binding,'MAX_PROOF_BYTES',1):
            self.assert_real_blocked(state,'PROOF_TOTAL_BOUND')

    def test_ancestor_prepares_only_selected_prices_and_records_exact_path(self):
        state = ancestor_fixture()
        with patch.object(capture, 'resume_state', side_effect=AssertionError('WHOLE_CHAIN')), \
             patch.object(capture, '_private_object', side_effect=AssertionError('SIBLING_READ')), \
             patch.object(capture, 'verify_archived_group', wraps=capture.verify_archived_group) as verify:
            prepared = self.prepare_real(state, repin=True)
        self.assertEqual(prepared.status, 'REAL_SOURCE_PREPARED_UNADMITTED')
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(verify.call_args.args[:2], tuple(state[:2]))
        for basis in prepared.bases:
            lineage = json.loads(basis.provenance)['original_checkpoint_lineage']
            self.assertEqual(lineage['kind'], 'BOUNDED_ANCESTOR')
            self.assertEqual(lineage['checkpoint_sha256'], [state[3]['original_checkpoint']['sha256'],
                state[3]['original_checkpoint_path'][0]['sha256']])
            self.assertEqual(lineage['unselected_price_reads'], 0)
            self.assertEqual(lineage['examined_before'], 1)
            self.assertEqual(lineage['examined_after'], 3)
            self.assertNotIn('SIBLING', basis.manifest.decode())

    def test_ancestor_held_sibling_is_metadata_only_and_never_priced(self):
        state = ancestor_fixture(held_sibling=True)
        with patch.object(capture, '_private_object', side_effect=AssertionError('MARKER_READ')):
            prepared = self.prepare_real(state, repin=True)
        self.assertEqual(prepared.status, 'REAL_SOURCE_PREPARED_UNADMITTED')
        for basis in prepared.bases:
            self.assertEqual(len(json.loads(basis.provenance)['original_checkpoint_lineage']
                                 ['checkpoint_sha256']), 3)
            self.assertNotIn('HELD', basis.manifest.decode())

    def test_ancestor_missing_or_malformed_path_is_finite(self):
        for value in ([], {}, 'latest', [dict()] * 32):
            state = ancestor_fixture(); state[3]['original_checkpoint_path'] = value
            self.assert_real_blocked(state, 'CHECKPOINT_PATH_BOUND', repin=True)
        state = ancestor_fixture()
        state[5].pop(state[3]['original_checkpoint_path'][0]['sha256'])
        self.assert_real_blocked(state, 'MISSING_OR_UNTRUSTED_PROOF', repin=True)
        state = ancestor_fixture(); state[3].pop('original_checkpoint_path')
        self.assert_real_blocked(state, 'ORIGINAL_CHECKPOINT_BINDING', repin=True)

    def test_ancestor_cycle_or_orphan_or_omitted_node_refuses(self):
        state = ancestor_fixture(); state[3]['original_checkpoint_path'] *= 2
        self.assert_real_blocked(state, 'CHECKPOINT_PATH_CYCLE', repin=True)
        state = ancestor_fixture(); state[3]['original_checkpoint_path'][0] = dict(
            state[3]['original_parent_checkpoint'], file_id='synthetic_orphan_checkpoint')
        self.assert_real_blocked(state, 'CHECKPOINT_PATH_LINK', repin=True)
        state = ancestor_fixture(held_sibling=True); state[3]['original_checkpoint_path'].pop(0)
        self.assert_real_blocked(state, 'CHECKPOINT_PATH_LINK', repin=True)
        state = ancestor_fixture(); state[3]['original_checkpoint_path'][0] = dict(
            state[3]['original_checkpoint_path'][0], bytes=True)
        self.assert_real_blocked(state, 'CHECKPOINT_PATH_REFERENCE', repin=True)

    def test_ancestor_rehashed_shortcut_still_requires_exact_prefix(self):
        state = ancestor_fixture(held_sibling=True)
        skipped = state[3]['original_checkpoint_path'].pop(0)
        state[5].pop(skipped['sha256'])
        selected = state[3]['original_checkpoint_path'][0]
        rewrite_ancestor(state, lambda nodes: nodes[0].update(previous_checkpoint=selected), relink=False)
        self.assert_real_blocked(state, 'CHECKPOINT_PATH_PREFIX', repin=True)

    def test_ancestor_rehashed_context_or_authority_substitution_refuses(self):
        for key, value in (('source_sha', '0'*40), ('seed_sha256', '0'*64),
                           ('start', '2015-01-01'), ('end', '2026-01-01'),
                           ('asof', '2025-12-31'), ('cohort_scope', {}),
                           ('pit_verified', True), ('source_admission', True)):
            state = ancestor_fixture()
            rewrite_ancestor(state, lambda nodes: nodes[-1].update({key:value}))
            self.assert_real_blocked(state, 'CHECKPOINT_PATH_CONTEXT', repin=True)

    def test_ancestor_partition_and_order_remain_exact(self):
        for update in (dict(completed=['AAPL', 'PRIOR']),
                       dict(examined=['PRIOR', 'AAPL', 'AAPL']),
                       dict(held=['AAPL']), dict(last_collected=['OTHER'])):
            state = ancestor_fixture()
            rewrite_ancestor(state, lambda nodes: nodes[-1].update(update))
            result = self.prepare_real(state, repin=True)
            self.assertEqual(result.status, 'BLOCKED'); self.assertEqual(result.bases, ())
            self.assertIn(result.blockers[0], ('CHECKPOINT_PATH_MEMBERSHIP', 'CHECKPOINT_PATH_GROUP'))

    def test_ancestor_selected_held_or_no_data_cannot_become_prices(self):
        state = ancestor_fixture()
        rewrite_ancestor(state, lambda nodes: nodes[-1].update(last_collected=[], last_no_bars=['AAPL']))
        self.assert_real_blocked(state, 'ORIGINAL_CHECKPOINT_BINDING', repin=True)
        state = ancestor_fixture()
        def hold(nodes):
            for node in nodes:
                node['completed'].remove('AAPL'); node['held'] = ['AAPL']
            nodes[-1].update(last_status='HELD_BAR_VALUE', last_collected=[], last_held=['AAPL'],
                             last_objects=[dict(sha256=digest(b'held'), bytes=4)])
        rewrite_ancestor(state, hold)
        self.assert_real_blocked(state, 'ORIGINAL_CHECKPOINT_BINDING', repin=True)

    def test_ancestor_original_run_and_resource_bounds_remain_mandatory(self):
        for key, value, code in (
            ('run_id', 1, 'ORIGINAL_EXECUTION_BINDING'),
            ('run_attempt', True, 'ORIGINAL_EXECUTION_BINDING'),
            ('source_sha', '0'*40, 'ORIGINAL_EXECUTION_BINDING'),
            ('examined_before', True, 'CHECKPOINT_RUN_BOUND'),
            ('examined_after', 34, 'CHECKPOINT_RUN_BOUND'),
            ('examined_after', 4, 'CHECKPOINT_RUN_BOUND'),
            ('parent_checkpoint_sha256', '0'*64, 'CHECKPOINT_PARENT_BOUND')):
            state = ancestor_fixture()
            self.replace_real_proof(state, 'original_execution', lambda d: d.update({key:value}))
            self.assert_real_blocked(state, code, repin=True)
        state = ancestor_fixture()
        with patch.object(binding, 'MAX_PROOF_BYTES', 1):
            self.assert_real_blocked(state, 'PROOF_TOTAL_BOUND', repin=True)
        self.assertEqual(binding.MAX_PROOFS, 32)
        self.assertEqual(binding.MAX_PROOF_BYTES, 16*1024*1024)

    def test_ancestor_original_parent_proof_cannot_be_missing_or_rebound(self):
        state = ancestor_fixture(); state[3].pop('original_parent_checkpoint')
        self.assert_real_blocked(state, 'CHECKPOINT_PATH_REFERENCE', repin=True)
        state = ancestor_fixture(); state[5].pop(state[3]['original_parent_checkpoint']['sha256'])
        self.assert_real_blocked(state, 'MISSING_OR_UNTRUSTED_PROOF', repin=True)
        state = ancestor_fixture()
        self.replace_real_proof(state, 'original_parent_checkpoint', lambda d: d.update(source_sha='0'*40))
        self.assert_real_blocked(state, 'CHECKPOINT_PARENT_BOUND', repin=True)

    def test_ancestor_external_logical_genesis_uses_existing_pure_helper(self):
        # Helper-only synthetic metadata test, not a positive source/rights proof.
        state = ancestor_fixture(); e, objects = state[3], state[5]
        receipt = json.loads(state[2]); scope = dict(task_key='R1000-SYNTHETIC-ANCESTOR-PROOF',
            namespace='synthetic-ancestor-20261024', input_sha256=receipt['seed_sha256'])
        receipt.update(cohort_scope=scope, end='2026-10-14', asof='2026-10-13')
        def change(nodes):
            for node in nodes:
                node.update(cohort_scope=scope, end=receipt['end'], asof=receipt['asof'])
                node['examined'].remove('PRIOR'); node['completed'].remove('PRIOR')
            nodes[-1]['previous_checkpoint'] = None
        rewrite_ancestor(state, change)
        meter = json.loads(objects[e['original_execution']['sha256']])
        meter.update(examined_before=0, examined_after=2, cohort_scope=scope,
            parent_checkpoint_sha256=binding.external_genesis(capture, scope))
        e.pop('original_parent_checkpoint')
        final = json.loads(objects[e['original_checkpoint']['sha256']])
        selected, lineage = binding._selected_checkpoint(e, meter, final, receipt,
                                                        lambda ref: objects[ref['sha256']])
        self.assertEqual(selected['last_collected'], ['AAPL'])
        self.assertEqual(lineage['examined_before'], 0)
        meter['parent_checkpoint_sha256'] = '0'*64
        with self.assertRaisesRegex(binding.BindingError, '^CHECKPOINT_PARENT_BOUND$'):
            binding._selected_checkpoint(e, meter, final, receipt, lambda ref: objects[ref['sha256']])

    def test_ancestor_unreferenced_proof_is_not_silently_consumed(self):
        state = ancestor_fixture(); state[5][digest(b'unused')] = b'unused'
        self.assert_real_blocked(state, 'UNREFERENCED_REVIEWED_PROOF', repin=True)

    def test_ancestor_parent_and_path_ids_cannot_alias_different_bytes(self):
        for kind in ('final', 'selected', 'unread_previous'):
            state = ancestor_fixture()
            parent = state[3]['original_parent_checkpoint']
            earlier = dict(file_id='synthetic_earlier_checkpoint',
                           sha256=digest(b'SYNTHETIC_UNREAD_EARLIER'), bytes=31)
            if kind == 'unread_previous':
                earlier['file_id'] = parent['file_id']
            def insert_earlier(nodes):
                for node in nodes:
                    node['examined'].insert(1, 'EARLIER')
                    node['completed'].insert(1, 'EARLIER')
                nodes[-1]['previous_checkpoint'] = earlier
            rewrite_ancestor(state, insert_earlier)
            self.replace_real_proof(state, 'original_execution', lambda d:d.update(examined_after=4))
            if kind == 'final':
                parent['file_id'] = state[3]['original_checkpoint']['file_id']
            elif kind == 'selected':
                parent['file_id'] = state[3]['original_checkpoint_path'][-1]['file_id']
            with self.subTest(alias=kind):
                self.assert_real_blocked(state, 'CHECKPOINT_PARENT_BOUND', repin=True)


if __name__ == '__main__':
    unittest.main()

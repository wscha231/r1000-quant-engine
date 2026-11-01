"""Synthetic producer/trust fixtures only, including the REAL_SOURCE code branch.

Injected trust and documents below are NOT actual accepted Source/rights proof.
No real Source/Drive/provider calls, publication or consumer ACK occur.
"""
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from functools import lru_cache
import copy
import ast
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
from tools import research_data_access as access

SESSIONS = ['2016-01-04', '2016-01-05']
OBSERVED = '2026-10-24T08:00:00Z'
DECISION = '2026-10-24T09:00:00Z'


def fixture_capture_group(*args, **kwargs):
    """Fake provider/storage only: do not sleep for a real provider RPM quota."""
    if not callable(kwargs.get('get')):
        raise AssertionError('EXPLICIT_SYNTHETIC_PROVIDER_REQUIRED')
    original = capture.request_pages
    def pages(*a, **k):
        return original(*a, **k, pause=lambda _: None)
    with patch.object(capture, 'request_pages', side_effect=pages):
        return capture.capture_one_group(*args, **kwargs)


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
    refs, _, _, _ = fixture_capture_group(
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


def financial_fixture(*, rows_override=None, durable=False, supplier_expires_at=None):
    """Synthetic R9-shaped evidence and fake execution/publication, never actual proof."""
    from tools.long_history_lake import sec_rows, packed, extraction_identity
    original = dict(cik=1, facts={'us-gaap': {
        'Revenues': {'units': {'USD': [dict(start='2025-09-01', end='2026-08-31',
            filed='2026-10-09', accn='0000000001-26-000001', form='10-K', val=0, fy=2026, fp='FY'),
            dict(start='2025-09-01', end='2026-08-31', filed='2026-10-12',
                 accn='0000000001-26-000002', form='10-K/A', val=-7, fy=2026, fp='FY')]}},
        'CommonStockSharesOutstanding': {'units': {'shares': [dict(end='2026-08-31',
            filed='2026-10-09', accn='0000000001-26-000001', form='10-K', val=8)]}},
        'EarningsPerShareDiluted': {'units': {'USD/shares': [dict(start='2025-09-01', end='2026-08-31',
            filed='2026-10-09', accn='0000000001-26-000001', form='10-K', val=-0.5)]}}}})
    original_bytes = encoded(original)
    rows, rejected = sec_rows(original_bytes, '0000000001', '2016-01-01', '2026-10-23')
    if rejected: raise AssertionError('synthetic extraction failed')
    raw, norm = packed(original_bytes), packed(b''.join(encoded(r) for r in (rows_override or rows)))
    proof = {}
    def put(value):
        b = value if type(value) is bytes else encoded(value)
        h = digest(b); proof[h] = b; return h
    review = put(b'CONTRACT_FIXTURE_INDEPENDENT_REVIEW_NOT_REAL_AUTHORITY')
    rights = put(b'CONTRACT_FIXTURE_SEC_RIGHTS_NOT_LEGAL_EVIDENCE')
    identity = put(b'CONTRACT_FIXTURE_IDENTITY_NOT_REAL_AUTHORITY')
    origin = dict(provider='SEC_COMPANYFACTS', dataset_key='sec/0000000001',
        commit_sha256='1'*64, catalog_sha256='2'*64, run_id='CONTRACT_FIXTURE:old_failed_run',
        source_code_sha='3'*40, config_sha256='4'*64, extraction_sha256=extraction_identity(),
        start='2016-01-01', through='2026-10-23', retrieved_at='2026-10-23T12:00:00Z',
        checked_at='2026-10-23T12:00:01Z', status='COLLECTED',
        matching_execution_receipt_sha256=None, original_public_available_at=None)
    frozen = put(dict(schema='mu-frozen-g29-selected-dataset-projection-v1', dataset_key=origin['dataset_key'],
        commit_sha256=origin['commit_sha256'], catalog_sha256=origin['catalog_sha256'],
        accepted_g29_producer_execution=False, original_catalog_header=dict(code_sha=origin['source_code_sha'],
            config_sha256=origin['config_sha256'], run_id=origin['run_id']),
        dataset=dict(cik='0000000001', status='COLLECTED', raw_objects=[digest(raw)], normalized=digest(norm),
            extraction_sha256=extraction_identity(), rows=len(rows),
            **{k: origin[k] for k in ('start', 'through', 'retrieved_at', 'checked_at')})))
    ack = put(dict(schema='mu-financial-diagnostic-consumer-ack-v1', status='DONE_DIAGNOSTIC_ONLY_UNADMITTED',
        matching_producer_execution=False, reads=[dict(kind='financial',sha256=digest(raw),bytes=len(raw)),
            dict(kind='financial',sha256=digest(norm),bytes=len(norm)),
            dict(kind='metadata',sha256=frozen,bytes=len(proof[frozen]))]))
    result = put(dict(raw_normalized_exact_equal=True, normalized_rows=len(rows), rejected_rows=0,
        output_refs=[dict(sha256=ack,bytes=len(proof[ack]))]))
    e = dict(schema='a1-financial-reuse-evidence-v1', task_key='CONTRACT_FIXTURE:financial_reuse_task',
        raw=dict(sha256=digest(raw),bytes=len(raw)),
        normalized=dict(sha256=digest(norm),bytes=len(norm)), origin=origin,
        issuer=dict(identity_scope='ISSUER_FINANCIAL_FACTS',cik='0000000001',
            issuer_name='CONTRACT_FIXTURE_ISSUER',archive_start='2016-01-01',archive_through='2026-10-23'),
        rights=dict(provider='SEC_COMPANYFACTS',status='REVIEWED',eligible_purposes=['research'],
            access_policy='PRIVATE_RESEARCH',license_reference='CONTRACT_FIXTURE_ONLY',
            supplier_expires_at=None,supplier_expiry_state='NOT_STATED'),
        proofs=dict(rights=rights,issuer_identity=identity,source_origin=frozen,reconstruction=ack,
                    reconstruction_result=result), source_documents=[rights,identity,frozen,ack,result],
        first_verified_readback_at='2026-10-24T12:00:00Z', research_valid_from='2026-10-24T12:00:00Z',
        research_expires_at='2026-11-02T00:00:00Z',reuse_run_id='CONTRACT_FIXTURE:new_reuse',reuse_code_sha='5'*40)
    if supplier_expires_at is not None:
        e['rights'].update(supplier_expires_at=supplier_expires_at,supplier_expiry_state='STATED')
    trust = binding.TrustedFinancialSourceBinding(review_reference='CONTRACT_FIXTURE:review',
        review_receipt_sha256=review,evidence_sha256=digest(encoded(e)),proof_sha256=tuple(sorted(proof)),
        issuer_cik='0000000001',raw_sha256=digest(raw),normalized_sha256=digest(norm),normalized_rows=len(rows),
        original_source_sha=origin['source_code_sha'],original_config_sha256=origin['config_sha256'],
        original_start=origin['start'],original_through=origin['through'],
        extraction_sha256=extraction_identity(),reconstruction_receipt_sha256=ack,
        reuse_run_id=e['reuse_run_id'],reuse_code_sha=e['reuse_code_sha'],
        adapter_file_sha256=digest(Path(binding.__file__).read_bytes()),classification='CONTRACT_FIXTURE',
        publication_scope='DURABLE_READBACK' if durable else 'LOCAL_ONLY')
    return raw,norm,e,trust,proof,rows


def bound_financial_fixture(*, durable=False, supplier_expires_at=None):
    raw,norm,e,t,proof,rows=financial_fixture(durable=durable,supplier_expires_at=supplier_expires_at)
    prepared=binding.prepare_financial_reuse(raw,norm,encoded(e),trusted_source=t,
        proof_objects=tuple(sorted(proof.items())),decision_time='2026-10-31T18:01:00Z')
    if prepared.blockers:raise AssertionError(prepared.blockers)
    p=encoded(dict(schema='a1-financial-reuse-execution-v1',status='COMPLETED_REUSE_ONLY',
        task_key=e['task_key'],run_id=t.reuse_run_id,code_sha=t.reuse_code_sha,adapter_file_sha256=t.adapter_file_sha256,
        config_sha256=t.evidence_sha256,raw_sha256=t.raw_sha256,normalized_sha256=t.normalized_sha256,
        quality_sha256=digest(prepared.quality),rows=t.normalized_rows,provider_gets=0,
        original_matching_execution=False,historical_pit=False,
        started_at='2026-10-31T18:00:00Z',finished_at='2026-10-31T18:00:01Z'))
    t=replace(t,execution_receipt_sha256=digest(p))
    bound=binding.bind_financial_reuse(prepared,p,trusted_source=t,
        created_at='2026-10-31T18:00:02Z',decision_time='2026-10-31T18:01:00Z')
    if bound.blockers:raise AssertionError(bound.blockers)
    blobs=dict(bound.objects);generation=digest(bound.manifest)
    pub=encoded(dict(schema='a1-financial-reuse-publication-v1',status='PUBLISHED_READBACK',
        storage='OWNER_PRIVATE_DURABLE',generation_sha256=generation,execution_receipt_sha256=digest(p),
        objects=json.loads(bound.manifest)['datasets'][0]['objects'],completed_at='2026-10-31T18:00:03Z'))
    if durable:
        t=replace(t,publication_receipt_sha256=digest(pub));blobs[digest(pub)]=pub
    return bound,t,blobs,p,pub


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


def private_view_fixture(*, names=('AAPL',), sessions=None, omit=None,
                         view_start='2016-01-05', view_end='2016-01-06', selected_only=True,
                         capture_scope=None, capture_start='2016-01-04',
                         price_offset=0, first_factor='2',asset_clock=OBSERVED,
                         clocks=None, volumes=None, provider_ids=None, run_id=987654321):
    """Local fake capture + injected synthetic trust, never actual original4 bytes."""
    sessions = list(sessions or ['2016-01-04', '2016-01-05', '2016-01-06'])
    clocks = clocks or dict(observed=OBSERVED,created='2026-10-24T08:30:00Z',
        expires='2026-10-25T09:00:00Z',decision=DECISION)
    observed = clocks['observed']
    drive = FakePrivateDrive()
    def get(url, **kwargs):
        bars = {}
        for ticker in names:
            bars[ticker] = [dict(t=s + 'T05:00:00Z', o=10 + (i+price_offset) % 17,
                h=12 + (i+price_offset) % 17, l=9 + (i+price_offset) % 17,
                c=11 + (i+price_offset) % 17,
                v=(volumes or {}).get(s,100 + (i+price_offset) % 7))
                for i, s in enumerate(sessions) if (ticker, s) != omit]
        return encoded(dict(bars=bars, next_page_token=None))
    source_sha = hashlib.sha1(b'CONTRACT_FIXTURE_SOURCE_CODE').hexdigest()
    end = (binding.day(sessions[-1]) + timedelta(days=1)).isoformat()
    assets = None
    if capture_scope is not None:
        assets = []
        for index, name in enumerate(names):
            body = encoded(dict(symbol=name, **{'class':'us_equity'},
                id='00000000-0000-0000-0000-' + str(index+1).zfill(12),
                exchange='NASDAQ',status='active'))
            assets.append(dict(symbol=name,url='https://paper-api.alpaca.markets/v2/assets/'+name,
                collected_at_utc=asset_clock,http_status=200,response_utf8=body.decode(),sha256=digest(body)))
    refs, _, _, _ = fixture_capture_group(drive, drive.folder, list(names),
        capture_start, end, 'fixture-key', 'fixture-secret',
        digest(b'CONTRACT_FIXTURE_SEED'), source_sha, get=get, scope=capture_scope,
        asset_evidence=assets)
    raw, norm, rec = (drive.objects[r['file_id']] for r in refs)
    receipt, objects = json.loads(rec), {}
    def add(value):
        value = value if type(value) is bytes else encoded(value)
        objects[digest(value)] = value
        return dict(sha256=digest(value), bytes=len(value))
    credential = digest(b'SYNTHETIC_TEST_EXISTING_ACCOUNT_REFERENCE')
    terms = add(b'SYNTHETIC_TEST_TERMS_NOT_AN_ACTUAL_MARKET_DATA_AGREEMENT')
    rights = add(dict(schema='a1-reviewed-account-rights-v1', provider='alpaca',
        credential_binding=credential, purpose='PRIVATE_NONCOMMERCIAL_RESEARCH',
        historical_sip_allowed=True, private_retention_allowed=True,
        source_documents=[terms], supplier_expiry=None))
    checkpoint = add(dict(schema=capture.SCHEMA, state='PRIVATE_RESEARCH_ONLY',
        source=capture.SOURCE, source_sha=source_sha, seed_sha256=receipt['seed_sha256'],
        start=receipt['start'], end=receipt['end'], last_status='VERIFIED_RAW_SPLIT',
        last_objects=[receipt['raw_object'], receipt['normalized_object'],
                      dict(file_id='synthetic_receipt', sha256=digest(rec), bytes=len(rec))]))
    meter = add(dict(schema='a1-sip-campaign-meter-v1', run_id=run_id,
        run_attempt=1, source_sha=source_sha, bindings=dict(credential_binding=credential),
        status='COMPLETE', finalized=True, preflight_only=False,
        checkpoint_sha256=checkpoint['sha256']))
    identity_doc = add(b'SYNTHETIC_TEST_IDENTITY_DOCUMENT')
    ca_doc = add(b'SYNTHETIC_TEST_SPLIT_DOCUMENT')
    lifecycle_doc = add(b'SYNTHETIC_TEST_LIFECYCLE_DOCUMENT')
    event = dict(kind='FIRST_OBSERVED_COMPLETE_READBACK', at=observed,
        objects=dict(raw_sha256=digest(raw), normalized_sha256=digest(norm),
                     capture_receipt_sha256=digest(rec)))
    event['evidence_ref'] = add(encoded(event))
    evidence = dict(schema='a1-reader-real-evidence-v1', fixture_only=False,
        owner_rights=rights, original_execution=meter, original_checkpoint=checkpoint,
        original_run_id=str(run_id), derivation_run_id='synthetic-test-derivation',
        derivation_code_sha=hashlib.sha1(b'CONTRACT_FIXTURE_DERIVATION_CODE').hexdigest(),
        identity_evidence=identity_doc, corporate_actions=ca_doc, lifecycle=lifecycle_doc,
        identity_status='VERIFIED', corporate_action_status='VERIFIED', lifecycle_status='VERIFIED',
        rights_capture_scope=dict(capture_receipt_sha256=digest(rec), start=receipt['start'],
            end_exclusive=receipt['end'], credential_binding=credential, original_run_id=run_id),
        first_observed_readback=event, created_at=clocks['created'],
        research_fresh_until=clocks['expires'], original_public_available_at=None,
        original_provider_collected_at=None, identity={}, split_factors={},
        private_view=dict(start=view_start, end=view_end, selection_reason='SOURCE_EXACT_COMPATIBILITY'),
        technical_metadata={})
    for index, ticker in enumerate(names):
        ident = dict(instrument_id='US.TEST.' + ticker, ticker=ticker,
            market='US', mic='XNAS' if ticker in ('AAPL', 'MU') else 'XNYS',
            timezone='America/New_York', calendar='NYSE', currency='USD',
            valid_from=view_start if selected_only else sessions[0],
            valid_through=view_end if selected_only else sessions[-1])
        evidence['identity'][ticker] = ident
        evidence['split_factors'][ticker] = {s: (first_factor if s == sessions[0] else '1')
            for s in sessions if (ticker, s) != omit
            and (not selected_only or view_start <= s <= view_end)}
        common = dict(provider=capture.SOURCE, capture_receipt_sha256=digest(rec),
            available_from=observed, collected_at=observed, expires_at=clocks['expires'])
        typed = dict(ident, **common, schema='ohlcv-security-identity-evidence-v1',
            provider_security_id=(provider_ids or {}).get(ticker,'synthetic-test-asset-' + str(index + 1)),
            asset_class='EQUITY', source_documents=[identity_doc])
        status = dict(common, schema='a1-ohlcv-status-volume-evidence-v1',
            instrument_id=ident['instrument_id'], ticker=ticker,
            provider_security_id=typed['provider_security_id'],
            valid_from=ident['valid_from'], valid_through=ident['valid_through'],
            halt_coverage='COMPLETE_FOR_WINDOW', halted_sessions=[],
            volume_basis=dict(raw='RAW', split='SPLIT_ADJUSTED'),
            halt_source_documents=[lifecycle_doc], volume_source_documents=[ca_doc])
        evidence['technical_metadata'][ticker] = dict(identity_evidence=add(typed),
                                                       status_evidence=add(status))
    review = add(b'SYNTHETIC_TEST_EXTERNALLY_INJECTED_TRUST_ANCHOR_NOT_ACTUAL_ACCEPTANCE')
    trusted = binding.TrustedSourceBinding(
        review_reference='https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-1',
        review_receipt_sha256=review['sha256'], evidence_sha256=digest(encoded(evidence)),
        proof_sha256=tuple(sorted(objects)), original_run_id=run_id, original_run_attempt=1,
        original_source_sha=source_sha, credential_binding=credential,
        derivation_run_id=evidence['derivation_run_id'], derivation_code_sha=evidence['derivation_code_sha'],
        adapter_file_sha256=digest(Path(binding.__file__).read_bytes()))
    return raw, norm, rec, evidence, trusted, objects


def provider_close_fixture(*, names=('AAPL',), known=None, sessions=None,
                           view_start=None, price_offset=0, first_factor='2',
                           capture_start='2016-01-04',clocks=None,volumes=None,
                           provider_ids=None,run_id=987654321,capture_scope=None,asset_clock=OBSERVED):
    """Small, externally injected SYNTHETIC qualification; no real admission."""
    sessions = sessions or ['2016-01-04', '2016-01-05', '2016-01-06', '2016-01-07',
                           '2016-01-08', '2016-01-11', '2016-01-12']
    view_start = view_start or sessions[1]
    state = list(private_view_fixture(names=names, sessions=sessions,
        view_start=view_start, view_end=sessions[-1],price_offset=price_offset,
        first_factor=first_factor,capture_start=capture_start,clocks=clocks,volumes=volumes,
        provider_ids=provider_ids,run_id=run_id,capture_scope=capture_scope,asset_clock=asset_clock))
    raw, norm, rec, e, trust, objects = state
    decision = clocks['decision'] if clocks else DECISION
    observed = e['first_observed_readback']['at']
    baseline = binding.prepare(raw, norm, rec, encoded(e), decision_time=decision,
        trusted_source=trust, proof_objects=tuple(sorted(objects.items())))
    if baseline.status != 'REAL_SOURCE_PREPARED_UNADMITTED':
        raise RuntimeError('SYNTHETIC_QUALIFICATION_BASELINE_FAILED')
    def add(value):
        value = value if type(value) is bytes else encoded(value)
        h = digest(value); objects[h] = value
        return dict(sha256=h, bytes=len(value))
    policy = add(b'SYNTHETIC_PROVIDER_CLOSE_POLICY_NOT_ACTUAL_PROVIDER_OR_RIGHTS_EVIDENCE')
    q = dict(schema='a1-provider-daily-close-qualification-v1',
        meaning='PROVIDER_SIP_DAILY_CLOSE_ARCHIVAL_RESEARCH', purpose='research',
        admission_state='RESEARCH_BYTES_ONLY', pit_status='PIT_PROXY',
        consumer_id='ohlcv-technical-feature-h1', provider=capture.SOURCE,
        feed='SIP', timeframe='1Day', volume_scope='PROVIDER_NEW_YORK_DAY_TRADE_CONDITIONS',
        source_run_id=e['original_run_id'],
        original_objects=dict(raw_sha256=digest(raw), normalized_sha256=digest(norm),
                              capture_receipt_sha256=digest(rec)),
        window=dict(start=view_start, end=sessions[-1],
                    sessions_sha256=digest(encoded([s for s in sessions if s >= view_start]))),
        observed_at=observed, available_from=observed, collected_at=observed,
        created_at=e['created_at'], review_decision_at=decision,
        expires_at=e['research_fresh_until'], original_public_available_at=None,
        original_provider_collected_at=None, physical_halt_coverage='UNKNOWN',
        instruments={}, source_documents=[policy])
    for base in baseline.bases:
        for f in json.loads(base.manifest)['datasets'][0]['files']:
            ident = f['instrument']; iid = ident['instrument_id']
            dates = list((known or {}).get(ident['ticker'], ()))
            item = q['instruments'].setdefault(iid, dict(ticker=ident['ticker'],
                provider_security_id=ident['provider_security_id'],
                identity_evidence_sha256=ident['identity_evidence_sha256'], basis_sha256={},
                known_halted_sessions=dates,
                known_halt_source_documents=[e['lifecycle']] if dates else []))
            item['basis_sha256'][base.basis] = f['sha256']
    qref = add(q)
    for pair in e['technical_metadata'].values():
        status = json.loads(objects.pop(pair['status_evidence']['sha256']))
        status.update(halt_coverage='UNKNOWN', halted_sessions=None,
                      provider_close_qualification=qref)
        status.pop('halt_source_documents')
        pair['status_evidence'] = add(status)
    state[4] = replace(trust, evidence_sha256=digest(encoded(e)),
                       proof_sha256=tuple(sorted(objects)))
    return state


def rewrite_provider_qualification(state, transform):
    """Rebind synthetic reviewed bytes so negatives exercise actual predicates."""
    e, objects = state[3], state[5]
    first = next(iter(e['technical_metadata'].values()))
    status = json.loads(objects[first['status_evidence']['sha256']])
    qref = status['provider_close_qualification']
    q = json.loads(objects.pop(qref['sha256']))
    transform(q)
    raw = encoded(q); objects[digest(raw)] = raw
    ref = dict(sha256=digest(raw), bytes=len(raw))
    for pair in e['technical_metadata'].values():
        doc = json.loads(objects.pop(pair['status_evidence']['sha256']))
        doc['provider_close_qualification'] = ref
        raw = encoded(doc); objects[digest(raw)] = raw
        pair['status_evidence'] = dict(sha256=digest(raw), bytes=len(raw))
    state[4] = replace(state[4], evidence_sha256=digest(encoded(e)),
                       proof_sha256=tuple(sorted(objects)))


def composition_fixture(*, tail_offset=6, tail_start='2016-01-12',old_input=None,
                        tail_days=None,rights_expiry=None,observed='2026-10-26T01:00:00Z',
                        created='2026-10-26T01:30:00Z',decision='2026-10-26T02:00:00Z',
                        old_known=None,states=None,decisions=None,revision_factory=None,
                        fresh_until='2026-10-27T02:00:00Z'):
    """Synthetic two-parent review only; no actual rights or current data."""
    tail_days = tail_days or [tail_start,'2016-01-13','2016-01-14','2016-01-15']
    if states is None:
        states = (provider_close_fixture(known=old_known),
            provider_close_fixture(sessions=tail_days,view_start=tail_start,
                capture_start=tail_start,price_offset=tail_offset,first_factor='1'))
    old,tail=states
    decisions=decisions or (DECISION,DECISION)
    parents = tuple(binding.prepare(*s[:3],encoded(s[3]),decision_time=dt,
        trusted_source=s[4],proof_objects=tuple(sorted(s[5].items()))).bases for s,dt in zip(states,decisions))
    if any(len(p) != 2 for p in parents):
        raise RuntimeError('SYNTHETIC_PARENT_FAILED')
    bindings=tuple(s[4] for s in states)
    parent_decisions=decisions
    if old_input is not None:
        parents=(old_input[0],parents[1]);bindings=(old_input[1],bindings[1])
        parent_decisions=(old_input[2],DECISION)
    revision,extra = None,{}
    if revision_factory is not None:
        parents,revision,extra = revision_factory(parents,states,decisions)
    pairs = tuple(tuple(b.generation_id for b in p) for p in parents)
    trust = binding.TrustedCompositionBinding(
        review_reference=old[4].review_reference,review_receipt_sha256='0'*64,
        evidence_sha256='0'*64,proof_sha256=(),credential_binding=old[4].credential_binding,
        derivation_run_id='synthetic-two-parent-research',derivation_code_sha='e'*40,
        adapter_file_sha256=digest(Path(binding.__file__).read_bytes()),
        parent_generation_pairs=pairs,parent_decisions=parent_decisions,
        parent_bindings=bindings,observed_revision_sha256=digest(encoded(revision)) if revision else None)
    # A negative anchor fixture needs no candidate review: the same actual
    # read/anchor predicate must refuse before a new qualification is issued.
    ticker = next(iter(old[3]['identity']));iid = old[3]['identity'][ticker]['instrument_id']
    data = binding._composition_material(parents,trust,iid,
        revision_bytes=encoded(revision) if revision else None,
        revision_context='synthetic-two-parent-context',decision=access.clock(decision),
        proof=lambda r,limit=65536:extra[r['sha256']])
    objects = dict(extra)
    def add(value):
        raw = value if type(value) is bytes else encoded(value)
        objects[digest(raw)] = raw
        return dict(sha256=digest(raw),bytes=len(raw))
    review = add(b'SYNTHETIC_FRESH_COMPOSITION_REVIEW_NOT_ACTUAL_ACCEPTANCE')
    doc = add(b'SYNTHETIC_CURRENT_BASIS_RIGHTS_IDENTITY_SOURCE_NOT_ACTUAL_EVIDENCE')
    rights = add(dict(schema='a1-reviewed-account-rights-v1',provider='alpaca',
        credential_binding=trust.credential_binding,purpose='PRIVATE_NONCOMMERCIAL_RESEARCH',
        historical_sip_allowed=True,private_retention_allowed=True,
        source_documents=[doc],supplier_expiry=rights_expiry))
    clocks = dict(available_from=observed,collected_at=observed,
                  expires_at=fresh_until)
    common = dict(composition_context_id='synthetic-two-parent-context',
        parent_generation_pairs=[list(p) for p in pairs],**clocks)
    ident = {k:data['identity'][k] for k in ('instrument_id','provider_security_id','ticker',
             'asset_class','market','mic','calendar','timezone','currency')}
    start=data['rows']['RAW'][0]['session_date']
    identity = add(dict(ident,**common,schema='ohlcv-security-identity-evidence-v1',
        provider=capture.SOURCE,valid_from=start,valid_through=tail_days[-1],
        source_documents=[doc]))
    status = add(dict(common,schema='a1-ohlcv-status-volume-evidence-v1',provider=capture.SOURCE,
        instrument_id=ident['instrument_id'],provider_security_id=ident['provider_security_id'],
        ticker=ticker,valid_from=start,valid_through=tail_days[-1],halt_coverage='UNKNOWN',
        halted_sessions=None,known_halted_sessions=data['known_halted_sessions'],
        known_halt_source_documents=[doc] if data['known_halted_sessions'] else [],
        volume_basis=dict(raw='RAW',split='SPLIT_ADJUSTED'),volume_source_documents=[doc]))
    anchor_fields = ('instrument_id','ticker','session_date','open','high','low','close','volume')
    anchor = {b:next(r for r in rows if r['session_date']==data['anchor'])
              for b,rows in data['rows'].items()}
    basis = add(dict(schema='a1-reviewed-common-split-basis-v1',
        context_id='synthetic-two-parent-context',**common,
        instrument_id=ident['instrument_id'],provider_security_id=ident['provider_security_id'],
        anchor_session=data['anchor'],common_split_basis_verified=True,rebase_allowed=False,
        physical_halt_coverage='UNKNOWN',historical_revision_certified=False,split_factor=data['factor'],
        raw_anchor_sha256=digest(encoded({k:anchor['RAW'][k] for k in anchor_fields})),
        split_anchor_sha256=digest(encoded({k:anchor['SPLIT_ADJUSTED'][k] for k in anchor_fields})),
        source_documents=[doc]))
    for parent in data['parents']:
        for name in ('raw_manifest','split_manifest','qualification'):
            ref=parent[name];objects[ref['sha256']]=data['objects'][ref['sha256']]
    q = dict(schema=access.PROVIDER_COMPOSITION_SCHEMA,
        meaning=access.PROVIDER_CLOSE_MEANING,purpose='research',admission_state='RESEARCH_BYTES_ONLY',
        pit_status='PIT_PROXY',consumer_id=access.PROVIDER_CLOSE_CONSUMER,provider=capture.SOURCE,
        feed='SIP',timeframe='1Day',volume_scope='PROVIDER_NEW_YORK_DAY_TRADE_CONDITIONS',
        source_run_id=trust.derivation_run_id,parents=data['parents'],
        context_id='synthetic-two-parent-context',common_basis=basis,owner_rights=rights,
        window=dict(start=start,end=tail_days[-1],
            sessions_sha256=digest(encoded([r['session_date'] for r in data['rows']['RAW']]))),
        observed_at=clocks['available_from'],**clocks,created_at=created,
        review_decision_at=decision,original_public_available_at=None,
        original_provider_collected_at=None,physical_halt_coverage='UNKNOWN',
        source_documents=[review,identity,status,doc],instruments={iid:dict(
            ticker=ticker,provider_security_id=ident['provider_security_id'],
            identity_evidence_sha256=identity['sha256'],known_halted_sessions=data['known_halted_sessions'],
            known_halt_source_documents=[doc] if data['known_halted_sessions'] else [],
            basis_sha256={b:digest(b''.join(encoded(r) for r in rows))
                                                       for b,rows in data['rows'].items()})})
    e = dict(schema='a1-reader-composition-evidence-v1',fixture_only=False,
        derivation_run_id=trust.derivation_run_id,derivation_code_sha=trust.derivation_code_sha,
        created_at=q['created_at'],research_fresh_until=q['expires_at'],security_id=iid,
        context_id=q['context_id'],qualification=add(q),common_basis=basis,owner_rights=rights,
        identity_evidence=identity,status_evidence=status)
    if revision is not None:
        revision_ref=add(revision)
        q['observed_revision_selection']=revision_ref
        q['source_documents'] += [dict(sha256=h,bytes=len(raw)) for h,raw in sorted(extra.items())]
        q['source_documents'].append(revision_ref)
        objects.pop(e['qualification']['sha256'])
        e['qualification']=add(q)
        e['observed_revision_selection']=revision_ref
    trust=replace(trust,review_receipt_sha256=review['sha256'],evidence_sha256=digest(encoded(e)),
                  proof_sha256=tuple(sorted(objects)))
    return parents,e,trust,objects


def rewrite_composition_doc(state,key,transform):
    """Rebind only synthetic external pins to exercise semantic refusals."""
    parents,e,trust,objects=state
    q=json.loads(objects.pop(e['qualification']['sha256']))
    if key=='qualification':
        transform(q)
    else:
        ref=e[key];doc=json.loads(objects.pop(ref['sha256']));transform(doc)
        raw=encoded(doc);new=dict(sha256=digest(raw),bytes=len(raw));objects[new['sha256']]=raw
        def rebind(value):
            if type(value) is dict:
                return new if value==ref else {k:rebind(v) for k,v in value.items()}
            return [rebind(v) for v in value] if type(value) is list else value
        q=rebind(q);e[key]=new
    raw=encoded(q);objects[digest(raw)]=raw;e['qualification']=dict(sha256=digest(raw),bytes=len(raw))
    return parents,e,replace(trust,evidence_sha256=digest(encoded(e)),
                            proof_sha256=tuple(sorted(objects))),objects


@lru_cache(maxsize=2)
def _observed_volume_fixture(new_price_offset=1):
    """Synthetic numbers/identity only; mirrors the bounded actual observation shape."""
    old_clocks=dict(observed='2026-10-27T02:00:00Z',created='2026-10-27T02:10:00Z',
        decision='2026-10-27T02:20:00Z',expires='2026-10-27T14:00:00Z')
    new_clocks=dict(observed='2026-10-30T06:40:00Z',created='2026-10-30T06:45:00Z',
        decision='2026-10-30T06:50:00Z',expires='2026-10-30T14:00:00Z')
    dates=(['2026-10-23','2026-10-26'],
           ['2026-10-26','2026-10-27','2026-10-28','2026-10-29'])
    scope=dict(task_key='R1000-SYNTHETIC-OBSERVED-VOLUME-NOT-ACTUAL-CAPTURE',
        namespace='managed-refresh-v1',input_sha256=digest(b'CONTRACT_FIXTURE_SEED'))
    states=tuple(provider_close_fixture(names=('MU',),sessions=days,view_start=days[0],
        capture_start=days[0],price_offset=0 if index==0 else new_price_offset,first_factor='1',clocks=clocks,
        volumes=({'2026-10-23':10000,'2026-10-26':10001} if index==0 else {'2026-10-26':6831}),
        provider_ids={'MU':'00000000-0000-0000-0000-000000000001'},capture_scope=scope,
        run_id=987654321 if index==0 else 41014284082)
        for index,(days,clocks) in enumerate(zip(dates,(old_clocks,new_clocks))))
    def factory(parents,states,decisions):
        extra={};captures=[];updated=[]
        def add(value):
            raw=value if type(value) is bytes else encoded(value)
            extra[digest(raw)]=raw;return dict(sha256=digest(raw),bytes=len(raw))
        for index,(pair,state,clocks) in enumerate(zip(parents,states,(old_clocks,new_clocks))):
            raw,norm,rb=state[:3];receipt=json.loads(rb)
            refs={k:add(v) for k,v in zip(('raw','normalized','receipt'),(raw,norm,rb))}
            at=access.clock(clocks['observed'])
            start=(at-timedelta(minutes=2)).isoformat();finish=(at-timedelta(minutes=1)).isoformat()
            leg=dict(objects=[receipt['raw_object'],receipt['normalized_object'],
                dict(file_id='synthetic_receipt_123',**refs['receipt'])],
                collection_started_at=start,collection_finished_at=finish,public_available_at=None)
            cp=dict(schema='a1-managed-run-checkpoint-v1',state='COMPLETE',
                run_id=state[4].original_run_id,source_sha=receipt['source_sha'],
                control_sha256=digest(b'SYNTHETIC_CONTROL'),session=dates[index][-1],
                coverage_updates={'MU':dates[index][-1]},held={},receipts=[leg],
                completed_at=(at-timedelta(seconds=30)).isoformat())
            refs['checkpoint']=add(cp)
            lineage=dict(kind='MANAGED_MAINTENANCE',managed_control_sha256=cp['control_sha256'],
                final_checkpoint_sha256=refs['checkpoint']['sha256'],
                selected_capture_receipt_sha256=refs['receipt']['sha256'],
                collection_started_at=start,collection_finished_at=finish)
            old_provenances={digest(b.provenance) for b in pair};provenances={}
            for b in pair:
                v=json.loads(b.provenance);v['original_checkpoint_lineage']=lineage
                provenances[b.basis]=encoded(v)
            new_provenances={digest(b):b for b in provenances.values()}
            changed=[]
            for b in pair:
                manifest=json.loads(b.manifest);source=manifest['datasets'][0]['source']
                source['basis_derivation_receipt_sha256']=digest(provenances[b.basis])
                source['raw_source_sha256']=sorted((set(source['raw_source_sha256'])-old_provenances)
                    |set(new_provenances)|{refs['checkpoint']['sha256']})
                blobs={h:raw for h,raw in b.objects if h not in old_provenances}
                blobs.update(new_provenances);blobs[refs['checkpoint']['sha256']]=extra[refs['checkpoint']['sha256']]
                changed.append(replace(b,manifest=encoded(manifest),provenance=provenances[b.basis],
                    objects=tuple(sorted(blobs.items()))))
            updated.append(tuple(changed))
            refs.update(derivations={b.basis:add(b.provenance) for b in changed},
                run_id=cp['run_id'],collection_started_at=start,collection_finished_at=finish,
                public_available_at=None)
            captures.append(refs)
        pairs=[[b.generation_id for b in pair] for pair in updated]
        manifests=[json.loads(pair[0].manifest) for pair in updated]
        parent_clocks=[]
        for manifest,decision in zip(manifests,decisions):
            src=manifest['datasets'][0]['source']
            parent_clocks.append(dict(source_available_from=src['available_from'],
                source_collected_at=src['collected_at'],source_expires_at=src['expires_at'],
                review_decision_at=decision))
        anchors={};differences=[]
        for basis in ('RAW','SPLIT_ADJUSTED'):
            rows=[]
            for pair in updated:
                b=next(b for b in pair if b.basis==basis);f=json.loads(b.manifest)['datasets'][0]['files'][0]
                records=[json.loads(x) for x in dict(b.objects)[f['sha256']].splitlines()]
                rows.append(next(r for r in records if r['session_date']=='2026-10-26'))
            anchors[basis]=dict(old_row_sha256=digest(encoded(rows[0])),new_row_sha256=digest(encoded(rows[1])))
            differences.append(dict(basis=basis,field='volume',old=rows[0]['volume'],
                new=rows[1]['volume'],delta=-3170))
        identity=manifests[0]['datasets'][0]['files'][0]['instrument']
        revision=dict(schema=access.OBSERVED_VOLUME_SCHEMA,profile='MU_20261026_VOLUME_ONLY',
            context_id='synthetic-two-parent-context',
            **{k:identity[k] for k in ('instrument_id','ticker','provider_security_id','market','mic','currency')},
            anchor_session='2026-10-26',parent_generation_pairs=pairs,parent_clocks=parent_clocks,
            captures=captures,anchors=anchors,differences=differences,
            comparison_report=add(b'SYNTHETIC_INDEPENDENT_20_FIELD_CONTEXT_NOT_ACTUAL_DATA'),
            selection=dict(old_start='2026-10-23',old_end='2026-10-23',
                           new_start='2026-10-26',new_end='2026-10-29'),supplier_correction_at=None)
        return tuple(updated),revision,extra
    return composition_fixture(states=states,decisions=(old_clocks['decision'],new_clocks['decision']),
        tail_start=dates[1][0],tail_days=dates[1],revision_factory=factory,
        observed='2026-10-30T07:00:00Z',created='2026-10-30T07:10:00Z',
        decision='2026-10-30T07:20:00Z',fresh_until='2026-10-30T14:00:00Z')


def observed_volume_fixture(new_price_offset=1):
    # Cache only synthetic fixture construction, never a Source/Reader operation.
    return copy.deepcopy(_observed_volume_fixture(new_price_offset))


def rewrite_observed_revision(state, transform, *, repin=True):
    parents,e,trust,objects=copy.deepcopy(state)
    old=e['observed_revision_selection'];revision=json.loads(objects.pop(old['sha256']))
    transform(revision)
    raw=encoded(revision);new=dict(sha256=digest(raw),bytes=len(raw));objects[new['sha256']]=raw
    q=json.loads(objects.pop(e['qualification']['sha256']))
    q['observed_revision_selection']=new
    q['source_documents']=[new if r==old else r for r in q['source_documents']]
    raw=encoded(q);objects[digest(raw)]=raw
    e.update(qualification=dict(sha256=digest(raw),bytes=len(raw)),observed_revision_selection=new)
    trust=replace(trust,evidence_sha256=digest(encoded(e)),proof_sha256=tuple(sorted(objects)),
                  observed_revision_sha256=new['sha256'] if repin else trust.observed_revision_sha256)
    return parents,e,trust,objects


def managed_fixture(*,asset_clock='2016-01-06T23:30:01Z',technical_security_id=None):
    """Pure synthetic managed contract, not an execution or rights approval."""
    from tools import alpaca_sip_managed_refresh as managed
    inventory = digest(b'CONTRACT_FIXTURE_SEED')
    task = 'R1000-SYNTHETIC-MANAGED-BINDING-ONLY'
    state = list(private_view_fixture(asset_clock=asset_clock,capture_scope=dict(task_key=task,
        namespace='managed-refresh-v1', input_sha256=inventory)))
    raw, norm, rec, e, trust, objects = state
    receipt = json.loads(rec)
    objects.pop(e['original_execution']['sha256'])
    objects.pop(e['original_checkpoint']['sha256'])
    def add(value):
        b = encoded(value); objects[digest(b)] = b
        return dict(file_id='synthetic_object_123', sha256=digest(b), bytes=len(b))
    for name,pair in e['technical_metadata'].items():
        asset=next(a for a in receipt['asset_precheck'] if a['symbol']==name)
        provider_id=technical_security_id or json.loads(asset['response_utf8'])['id']
        for role in ('identity_evidence','status_evidence'):
            document=json.loads(objects.pop(pair[role]['sha256']))
            document['provider_security_id']=provider_id
            pair[role]=add(document)
    def ref(label):
        return dict(file_id='synthetic_ref_123', sha256=digest(label.encode()), bytes=1)
    allowance = dict(provider_gets=3, drive_requests=256, drive_bytes=134217728, storage_bytes=8388608)
    control = dict(schema=managed.SCHEMA, repository=managed.REPO, task_key=task,
        inventory_sha256=inventory, policy_sha256='a'*64,
        not_before='2016-01-06T23:00:00Z', expires_at='2016-01-07T23:00:00Z',
        max_runs=1, max_symbols_per_run=1, max_active_seconds_per_run=900,
        private_noncommercial=True, supplier_rights_verified=True, source_admission=False,
        rights_ref=ref('rights'), bootstrap_ref=ref('bootstrap'), opening_evidence_ref=ref('opening'),
        opening_evidence_sha256=digest(b'opening'), source_history_sha256='b'*64,
        owner_sha256='c'*64, credential_binding=trust.credential_binding,
        private_root_folder_id='synthetic_root_123', private_data_folder_id='synthetic_data_123',
        evidence_folder_id='synthetic_evidence_123', journal_folder_id='synthetic_journal_123',
        opening_usage={k:0 for k in managed.TOTAL_KEYS}, per_run_allowance=allowance,
        cumulative_ceiling=dict(allowance, active_seconds=5400, dispatches=1),
        authorized_tickers=['AAPL'], execution_tickers=['AAPL'], backfill_tickers=[],
        deployment=dict(pull_request=1, reviewed_head=trust.original_source_sha,
                        merge_sha=trust.original_source_sha),
        code_pins={p:'d'*64 for p in managed.PIN_PATHS},
        approval_reference=managed.managed.A0+'#issuecomment-1')
    ch = managed.validate_control(control, inventory, 'a'*64,
                                  managed.campaign.utc('2016-01-06T23:30:00Z'))
    reserved = dict(schema='a1-managed-run-checkpoint-v1', control_sha256=ch,
        run_id=trust.original_run_id, source_sha=trust.original_source_sha, slot=1,
        state='RESERVED', parent_sha256=None, reserved_allowance=allowance,
        created_at='2016-01-06T23:30:01Z')
    reserve_ref = add(reserved)
    group = dict(objects=[receipt['raw_object'], receipt['normalized_object'],
                           dict(file_id='synthetic_receipt',sha256=digest(rec),bytes=len(rec))],
        collection_started_at='2016-01-06T23:30:02Z', collection_finished_at='2016-01-06T23:30:03Z',
        public_available_at=None, historical_identity_verified=False,
        corporate_action_chain_verified=False, source_admission=False, pit_verified=False)
    terminal = dict(reserved, state='COMPLETE', parent_sha256=reserve_ref['sha256'],
        coverage_updates={'AAPL':'2016-01-06'}, held={}, reused=[], receipts=[group],
        reason=None, session='2016-01-06', completed_at='2016-01-06T23:30:04Z',
        meter_usage_before_checkpoint_publication=dict(provider_gets=1,drive_requests=0,
                                                       drive_bytes=1,storage_bytes=1))
    terminal_ref = add(terminal)
    meter = dict(schema='a1-sip-campaign-meter-v1', run_id=trust.original_run_id, run_attempt=1,
        source_sha=trust.original_source_sha, managed_control_sha256=ch,
        managed_checkpoint_sha256=terminal_ref['sha256'], finalized=True, status='COMPLETE',
        allowance=allowance, usage={k:1 for k in allowance}, transfer_definition=managed.campaign.METRIC,
        source_admission=False, pit_verified=False, economic_authority=False,
        managed_worker_started_at='2016-01-06T23:30:00Z',
        managed_worker_deadline='2016-01-06T23:45:00Z')
    approval = dict(id=1,author_association='OWNER',user=dict(type='User'),
        issue_url='https://api.github.com/repos/'+managed.REPO+'/issues/448',
        created_at='2016-01-06T23:29:59Z',updated_at='2016-01-06T23:29:59Z',
        body=managed.TAG+encoded(dict(control_sha256=ch,rights_sha256=control['rights_ref']['sha256'],
            opening_evidence_sha256=control['opening_evidence_sha256'],expires_at=control['expires_at'],
            private_retention_reviewed=True,historical_sip_reviewed=True,standing_budget_approved=True)).decode().strip())
    run = dict(id=trust.original_run_id,run_attempt=1,head_sha=trust.original_source_sha,
        head_branch='master',event='workflow_dispatch',status='completed',conclusion='success',
        path='.github/workflows/free_data_daily_update.yml',repository=dict(full_name=managed.REPO),
        created_at='2016-01-06T23:30:00Z',updated_at='2016-01-06T23:31:00Z')
    e.update(original_execution=add(meter),original_checkpoint=terminal_ref,
        managed_control=add(control),managed_reservation=reserve_ref,managed_run=add(run),
        managed_approval=add(approval),managed_deployment=add(dict(number=1,merged=True,
            merge_commit_sha=trust.original_source_sha,head=dict(sha=trust.original_source_sha),
            base=dict(ref='master'),merged_at='2016-01-06T23:00:00Z')),
        managed_master=add(dict(name='master',protected=True,commit=dict(sha=trust.original_source_sha))),
        managed_job=add(dict(id=123,run_id=trust.original_run_id,head_sha=trust.original_source_sha,
            name=managed.JOB,status='completed',conclusion='success',
            started_at='2016-01-06T23:30:00Z',completed_at='2016-01-06T23:30:59Z')))
    state[4]=replace(trust,evidence_sha256=digest(encoded(e)),proof_sha256=tuple(sorted(objects)))
    return state, ch


class BindingTest(unittest.TestCase):
    def financial_prepare(self, raw, norm, evidence, trust, proofs):
        return binding.prepare_financial_reuse(raw,norm,encoded(evidence),trusted_source=trust,
            proof_objects=tuple(sorted(proofs.items())),decision_time='2026-10-31T18:01:00Z')

    def test_financial_prepare_never_invents_execution_or_publication(self):
        raw,norm,e,t,proof,_=financial_fixture()
        blocked=self.financial_prepare(raw,norm,e,None,proof)
        self.assertEqual((blocked.status,blocked.manifest),('BLOCKED',None))
        with patch('tools.long_history_lake.extraction_identity',return_value=t.extraction_sha256), \
             patch('tools.long_history_lake.sec_rows',side_effect=AssertionError('no re-extraction')):
            prepared=self.financial_prepare(raw,norm,e,t,proof)
        self.assertEqual(prepared.status,'VERIFIED_INPUTS_AWAITING_ACTUAL_REUSE_RECEIPT')
        self.assertIsNone(prepared.manifest)
        self.assertNotIn('execution_receipt_sha256',json.loads(prepared.quality))
        bound,t,_,_,_=bound_financial_fixture()
        s=json.loads(bound.manifest)['datasets'][0]['source']
        self.assertIsNone(s['reuse_origin']['matching_execution_receipt_sha256'])
        self.assertEqual(s['availability_meaning'],'CURRENT_REUSE_EXECUTION_COMPLETED')
        self.assertIsNone(s['original_public_available_at'])
        self.assertEqual(s['original_collected_at'],'2026-10-23T12:00:00Z')
        self.assertEqual(s['currentness'],'NOT_CURRENT')
        self.assertIsNone(t.publication_receipt_sha256)

    def test_financial_raw_norm_config_window_and_extract_must_match_old_r9(self):
        raw,norm,e,t,proof,_=financial_fixture()
        for field,value in (('config_sha256','f'*64),('start','2017-01-01'),('through','2026-10-22')):
            changed=copy.deepcopy(e);changed['origin'][field]=value
            kwargs={'evidence_sha256':digest(encoded(changed))}
            kwargs[{'config_sha256':'original_config_sha256','start':'original_start',
                    'through':'original_through'}[field]]=value
            result=self.financial_prepare(raw,norm,changed,replace(t,**kwargs),proof)
            self.assertEqual(result.status,'BLOCKED',field)
        self.assertEqual(self.financial_prepare(raw+b'x',norm,e,t,proof).status,'BLOCKED')
        self.assertEqual(self.financial_prepare(raw,norm+b'x',e,t,proof).status,'BLOCKED')
        self.assertEqual(self.financial_prepare(raw,norm,e,replace(t,extraction_sha256='0'*64),proof).status,'BLOCKED')

    def test_financial_rights_unknown_and_expiry_do_not_become_perpetual_permission(self):
        raw,norm,e,t,proof,_=financial_fixture()
        for section,key,value in (('rights','status','UNKNOWN'),('rights','eligible_purposes',['backtest']),
                ('rights','supplier_expiry_state','UNKNOWN'),('rights','supplier_expires_at','2026-10-25T00:00:00Z'),
                ('issuer','cik','0000000002'),('issuer','issuer_name','UNKNOWN'),
                ('issuer','identity_scope','MARKET_SECURITY')):
            changed=copy.deepcopy(e);changed[section][key]=value
            if key=='supplier_expires_at':changed['rights']['supplier_expiry_state']='STATED'
            result=self.financial_prepare(raw,norm,changed,replace(t,evidence_sha256=digest(encoded(changed))),proof)
            self.assertEqual(result.status,'BLOCKED',(section,key))
        changed=copy.deepcopy(e);changed['research_expires_at']='2026-10-25T00:00:00Z'
        self.assertEqual(self.financial_prepare(raw,norm,changed,
            replace(t,evidence_sha256=digest(encoded(changed))),proof).status,'BLOCKED')
        bound,_,_,_,_=bound_financial_fixture(supplier_expires_at='2026-11-01T00:00:00Z')
        source=json.loads(bound.manifest)['datasets'][0]['source']
        self.assertEqual(source['expires_at'],'2026-11-01T00:00:00Z')
        self.assertEqual(source['supplier_expires_at'],'2026-11-01T00:00:00Z')
        self.assertEqual(source['research_expires_at'],'2026-11-02T00:00:00Z')

    def test_financial_schema_preserves_zero_negative_null_units_and_versions(self):
        raw,norm,e,t,proof,rows=financial_fixture()
        result=self.financial_prepare(raw,norm,e,t,proof)
        self.assertEqual([dict(r) for r in result.rows],rows)
        self.assertEqual(json.loads(result.quality)['row_set_sha256'],digest(encoded(rows)))
        self.assertIn(0,[r['value'] for r in result.rows]);self.assertIn(-7,[r['value'] for r in result.rows])
        self.assertIn(None,[r['start'] for r in result.rows])
        self.assertEqual({r['unit'] for r in result.rows},{'USD','shares','USD/shares'})
        self.assertEqual(len([r for r in result.rows if r['concept']=='Revenues']),2)
        with self.assertRaises(TypeError):result.rows[0]['value']=999
        for kind in ('bool','nullvalue','duration','duplicate','unsorted','issuer'):
            changed=copy.deepcopy(rows)
            if kind=='bool':changed[0]['value']=False
            elif kind=='nullvalue':changed[0]['value']=None
            elif kind=='duration':changed[0]['duration_days']=False
            elif kind=='duplicate':changed[1]=copy.deepcopy(changed[0])
            elif kind=='unsorted':changed.reverse()
            else:changed[0]['cik']='0000000002'
            r,n,ev,tr,pr,_=financial_fixture(rows_override=changed)
            self.assertEqual(self.financial_prepare(r,n,ev,tr,pr).status,'BLOCKED',kind)

    def test_financial_resources_cancellation_and_external_proof_pins(self):
        from tools.twelve_private_capture import Refused
        raw,norm,e,t,proof,_=financial_fixture()
        with patch.object(access,'MAX_GENERATION_DECOMPRESSED_BYTES',1024):
            self.assertEqual(self.financial_prepare(raw,norm,e,t,proof).status,'BLOCKED')
        with patch.object(access,'MAX_GENERATION_ROWS',3):
            self.assertEqual(self.financial_prepare(raw,norm,e,t,proof).status,'BLOCKED')
        failure=Refused('synthetic cancellation')
        with patch.object(ResearchDataReader,'_rows',side_effect=failure),self.assertRaises(Refused) as caught:
            self.financial_prepare(raw,norm,e,t,proof)
        self.assertIs(caught.exception,failure)
        with patch.object(access.gzip.GzipFile,'read',side_effect=failure),self.assertRaises(Refused) as caught:
            self.financial_prepare(raw,norm,e,t,proof)
        self.assertIs(caught.exception,failure)
        missing=dict(proof);missing.pop(t.review_receipt_sha256)
        self.assertEqual(self.financial_prepare(raw,norm,e,t,missing).status,'BLOCKED')
        self.assertEqual(self.financial_prepare(raw,norm,e,{},proof).status,'BLOCKED')

    def test_financial_binding_requires_actual_new_receipt_with_no_future_claims(self):
        raw,norm,e,t,proof,_=financial_fixture();prepared=self.financial_prepare(raw,norm,e,t,proof)
        _,trusted,_,p,_=bound_financial_fixture()
        for field,value in (('schema','long-history-execution-v1'),('provider_gets',1),
                ('finished_at','2026-11-01T00:00:00Z'),('original_matching_execution',True),
                ('quality_sha256','0'*64),('code_sha','f'*40),('rows',True)):
            changed=json.loads(p);changed[field]=value;b=encoded(changed)
            result=binding.bind_financial_reuse(prepared,b,
                trusted_source=replace(trusted,execution_receipt_sha256=digest(b)),
                created_at='2026-10-31T18:00:02Z',decision_time='2026-10-31T18:01:00Z')
            self.assertEqual((result.status,result.manifest),('BLOCKED',None),field)
        result=binding.bind_financial_reuse(prepared,p,trusted_source=t,
            created_at='2026-10-31T18:00:02Z',decision_time='2026-10-31T18:01:00Z')
        self.assertEqual(result.status,'BLOCKED')

    def test_financial_bind_rechecks_mutable_carrier_objects_context_quality_and_rows(self):
        raw,norm,e,t,proof,_=financial_fixture();prepared=self.financial_prepare(raw,norm,e,t,proof)
        _,trusted,_,p,_=bound_financial_fixture()
        objects=dict(prepared.objects)
        bad_rows=[dict(r) for r in prepared.rows];bad_rows[0]['value']=123
        cases=[replace(prepared,objects=tuple((h,b'x' if h==t.raw_sha256 else b) for h,b in prepared.objects)),
            replace(prepared,objects=prepared.objects+(prepared.objects[0],)),
            replace(prepared,objects=tuple(pair for pair in prepared.objects if pair[0]!=t.raw_sha256)),
            replace(prepared,objects=prepared.objects+((digest(b'extra'),b'extra'),)),
            replace(prepared,context=b'{}'),replace(prepared,quality=b'{}'),
            replace(prepared,rows=tuple(bad_rows)),replace(prepared,rows=()),
            replace(prepared,decoded_retained_bytes_charged='invalid')]
        with patch.object(ResearchDataReader,'_rows',side_effect=AssertionError('bind must not decode again')):
            for candidate in cases:
                with self.subTest(candidate=candidate.status):
                    result=binding.bind_financial_reuse(candidate,p,trusted_source=trusted,
                        created_at='2026-10-31T18:00:02Z',decision_time='2026-10-31T18:01:00Z')
                    self.assertEqual((result.status,result.manifest),('BLOCKED',None))

    def test_financial_preparation_failure_retains_already_charged_work(self):
        raw,norm,e,t,proof,_=financial_fixture()
        # All metadata is inspected before a requested source row-count mismatch.
        changed=replace(t,normalized_rows=t.normalized_rows+1)
        result=self.financial_prepare(raw,norm,e,changed,proof)
        self.assertEqual(result.status,'BLOCKED')
        self.assertGreater(result.decoded_retained_bytes_charged,0)
        self.assertIsNone(result.manifest)

    def test_financial_bind_explicit_remaining_cannot_reset_prior_charge(self):
        raw,norm,e,t,proof,_=financial_fixture();prepared=self.financial_prepare(raw,norm,e,t,proof)
        _,trusted,_,p,_=bound_financial_fixture()
        prior=prepared.decoded_retained_bytes_charged
        self.assertGreater(prior,0)
        cap=access.MAX_GENERATION_DECOMPRESSED_BYTES
        for allowance in (cap,cap-prior+1):
            result=binding.bind_financial_reuse(prepared,p,trusted_source=trusted,
                created_at='2026-10-31T18:00:02Z',decision_time='2026-10-31T18:01:00Z',
                remaining_bytes=allowance)
            self.assertEqual((result.status,result.manifest),('BLOCKED',None))
            self.assertIn('FINANCIAL_RESOURCE_LIMIT',result.blockers)
            self.assertGreaterEqual(result.decoded_retained_bytes_charged,prior)
        result=binding.bind_financial_reuse(prepared,p,trusted_source=trusted,
            created_at='2026-10-31T18:00:02Z',decision_time='2026-10-31T18:01:00Z',remaining_bytes=cap-prior)
        self.assertEqual(result.status,'FINANCIAL_REUSE_PREPARED_UNADMITTED',result.blockers)
        self.assertLessEqual(result.decoded_retained_bytes_charged,cap)

    def setUp(self):
        self.raw, self.norm, self.rec, self.evidence, self.calls = fixture()

    def test_observed_volume_revision_selects_new_row_without_mutating_parents(self):
        parents,e,trust,objects=observed_volume_fixture()
        original=tuple((b.manifest,b.provenance,b.objects) for pair in parents for b in pair)
        result=binding.compose_prepared(parents,encoded(e),decision_time='2026-10-30T07:20:00Z',
            trusted_source=trust,proof_objects=tuple(sorted(objects.items())))
        self.assertEqual(result.status,'REAL_SOURCE_COMPOSED_UNADMITTED',result.blockers)
        for b in result.bases:
            transport,_,_=fixture_transport(b)
            out=ResearchDataReader(transport).read_components('ds.us.prices.daily',b.generation_id,
                decision_time='2026-10-30T07:20:00Z',purpose='research',
                components=[dict(component_id='mu',instrument_id='US.TEST.MU',
                    required_start='2026-10-23',required_end='2026-10-29',minimum_rows=5)],
                consumer_id=access.PROVIDER_CLOSE_CONSUMER)
            rows=out.results['mu'].rows
            self.assertEqual([r['volume'] for r in rows[:2]],[10000,6831])
            self.assertEqual(rows[0]['available_from'],'2026-10-27T02:00:00Z')
            self.assertEqual(rows[1]['available_from'],'2026-10-30T06:40:00Z')
            self.assertEqual(out.receipt['observed_revision_selection_sha256'],trust.observed_revision_sha256)
            self.assertFalse(out.receipt['eligible_for_economics'])
            self.assertFalse(out.receipt['eligible_for_selector'])
        self.assertEqual(original,tuple((b.manifest,b.provenance,b.objects) for pair in parents for b in pair))

    def compose_observed(self,state,**kwargs):
        parents,e,trust,objects=state
        return binding.compose_prepared(parents,encoded(e),
            decision_time=kwargs.get('decision','2026-10-30T07:20:00Z'),
            trusted_source=trust,proof_objects=tuple(sorted(objects.items())))

    def test_observed_volume_requires_external_exact_pin_and_legacy_stays_strict(self):
        parents,e,trust,objects=observed_volume_fixture()
        for h in (None,'0'*64):
            result=self.compose_observed((parents,e,replace(trust,observed_revision_sha256=h),objects))
            self.assertEqual(result.status,'BLOCKED')
        e.pop('observed_revision_selection')
        trust=replace(trust,observed_revision_sha256=None,evidence_sha256=digest(encoded(e)))
        result=self.compose_observed((parents,e,trust,objects))
        self.assertEqual(result.blockers,('COMPOSITION_ANCHOR_CONFLICT',))
        state=rewrite_observed_revision(observed_volume_fixture(),
            lambda d:d.update(supplier_correction_at='2026-10-30T00:00:00Z'),repin=False)
        self.assertEqual(self.compose_observed(state).blockers,('REVISION_EXTERNAL_PIN_REQUIRED',))

    def test_observed_volume_nested_proofs_must_be_qualification_bound(self):
        state=observed_volume_fixture()
        revision=json.loads(state[3][state[1]['observed_revision_selection']['sha256']])
        targets=[('comparison_report',revision['comparison_report'])]
        for index,capture_record in enumerate(revision['captures']):
            for key in ('raw','normalized','receipt','checkpoint'):
                targets.append((f'capture{index}_{key}',capture_record[key]))
            for basis,ref in capture_record['derivations'].items():
                targets.append((f'capture{index}_{basis}_derivation',ref))
        for name,ref in targets:
            with self.subTest(proof=name):
                def omit(q):
                    q['source_documents']=[r for r in q['source_documents'] if r!=ref]
                changed=rewrite_composition_doc(copy.deepcopy(state),'qualification',omit)
                result=self.compose_observed(changed)
                self.assertEqual(result.status,'BLOCKED')
                self.assertEqual(result.blockers,('REVISION_NOT_SOURCE_BOUND',))
                self.assertEqual(result.bases,())

    def test_observed_volume_nested_proof_size_must_match_qualification(self):
        state=observed_volume_fixture()
        revision=json.loads(state[3][state[1]['observed_revision_selection']['sha256']])
        ref=revision['comparison_report']
        def wrong_size(q):
            q['source_documents']=[dict(r,bytes=r['bytes']+1) if r==ref else r
                                   for r in q['source_documents']]
        result=self.compose_observed(rewrite_composition_doc(state,'qualification',wrong_size))
        self.assertEqual(result.status,'BLOCKED')
        self.assertEqual(result.blockers,('REVISION_NOT_SOURCE_BOUND',))
        self.assertEqual(result.bases,())

    def test_observed_volume_rejects_unreviewed_shape_extra_changes_and_clocks(self):
        cases=[
            (lambda d:d.update(REVIEWED=True),'REVISION_SCHEMA'),
            (lambda d:d.update(ticker='AAPL'),'REVISION_IDENTITY'),
            (lambda d:d.update(supplier_correction_at='2026-10-30T00:00:00Z'),'REVISION_UNKNOWN_PUBLICATION'),
            (lambda d:d['selection'].update(old_end='2026-10-26'),'REVISION_SELECTION_WINDOW'),
            (lambda d:d['selection'].update(new_start='2026-10-27'),'REVISION_SELECTION_WINDOW'),
            (lambda d:d['parent_clocks'][0].update(source_expires_at='2030-01-01T00:00:00Z'),
                'REVISION_ORIGINAL_CLOCKS'),
            (lambda d:d['captures'][1].update(collection_finished_at='2026-10-31T00:00:00Z'),
                'REVISION_CAPTURE_CLOCKS'),
            (lambda d:d['captures'][1].update(run_id=41014284083),'REVISION_CAPTURE_SCOPE'),
            (lambda d:d['differences'][0].update(field='close'),'REVISION_CHANGE_SET'),
            (lambda d:d['differences'][0].update(old=10002,new=6832),'REVISION_CHANGE_SET'),
            (lambda d:d['anchors']['RAW'].update(old_row_sha256='0'*64),'REVISION_ANCHOR_BINDING'),
        ]
        for change,code in cases:
            with self.subTest(code=code):
                state=rewrite_observed_revision(observed_volume_fixture(),change)
                self.assertEqual(self.compose_observed(state).blockers,(code,))
        self.assertEqual(self.compose_observed(observed_volume_fixture(),
            decision='2026-10-30T14:00:01Z').blockers,('COMPOSITION_FRESH_REVIEW',))

    def test_observed_volume_cannot_authorize_changed_price_or_bad_original_bytes(self):
        with self.assertRaisesRegex(binding.BindingError,'REVISION_CHANGE_SET'):
            observed_volume_fixture(new_price_offset=2)
        state=observed_volume_fixture()
        revision=json.loads(state[3][state[1]['observed_revision_selection']['sha256']])
        state[3][revision['captures'][1]['raw']['sha256']]=b'not original'
        self.assertEqual(self.compose_observed(state).blockers,('COMPOSITION_PROOF_HASH',))

    def test_observed_volume_rejects_foreign_checkpoint_and_ancestor(self):
        state=observed_volume_fixture()
        revision=json.loads(state[3][state[1]['observed_revision_selection']['sha256']])
        ref=revision['captures'][1]['checkpoint']
        checkpoint=json.loads(state[3][ref['sha256']]);checkpoint['source_sha']='0'*40
        raw=encoded(checkpoint);changed=dict(sha256=digest(raw),bytes=len(raw))
        state[3][changed['sha256']]=raw
        rebound=rewrite_observed_revision(state,lambda d:d['captures'][1].update(checkpoint=changed))
        self.assertEqual(self.compose_observed(rebound).blockers,('REVISION_CHECKPOINT',))
        state=rewrite_observed_revision(observed_volume_fixture(),
            lambda d:d['captures'][1]['derivations'].update(RAW=d['captures'][0]['derivations']['RAW']))
        self.assertEqual(self.compose_observed(state).blockers,('REVISION_ORIGINAL_LINEAGE',))

    def test_registered_lake_loads_reader_and_source_suites_without_duplicate_entries(self):
        tree=ast.parse((ROOT/'tests/long_history_lake_smoke.py').read_bytes())
        loader=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='load_tests')
        loaded=[n.args[0].id for n in ast.walk(loader) if isinstance(n,ast.Call)
            and isinstance(n.func,ast.Attribute) and n.func.attr=='loadTestsFromTestCase'
            and n.args and isinstance(n.args[0],ast.Name)]
        self.assertEqual(loaded.count('ReaderTest'),1)
        self.assertEqual(loaded.count('BindingTest'),1)
        tree=ast.parse((ROOT/'tools/run_pr_validation.py').read_bytes())
        paths=ast.literal_eval(next(n.value for n in tree.body
            if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name)
            and n.target.id=='DEFAULT_TESTS'))
        names=[name for name,_ in paths]
        self.assertEqual(names.count('tests/long_history_lake_smoke.py'),1)
        self.assertNotIn('tests/a1_reader_generation_binding_smoke.py',names)
        self.assertNotIn('tests/research_data_access_smoke.py',names)

    def test_composition_preserves_parent_bytes_clocks_and_expiry(self):
        parents,e,trust,objects=composition_fixture()
        result=binding.compose_prepared(parents,encoded(e),decision_time='2026-10-26T02:00:00Z',
            trusted_source=trust,proof_objects=tuple(sorted(objects.items())))
        self.assertEqual(result.status,'REAL_SOURCE_COMPOSED_UNADMITTED',result.blockers)
        self.assertEqual(result,binding.compose_prepared(parents,encoded(e),
            decision_time='2026-10-26T02:00:00Z',trusted_source=trust,
            proof_objects=tuple(sorted(objects.items()))))
        for base in result.bases:
            transport,_,_=fixture_transport(base)
            batch=ResearchDataReader(transport).read_components('ds.us.prices.daily',base.generation_id,
                decision_time='2026-10-26T02:00:00Z',purpose='research',
                components=[dict(component_id='subject',instrument_id='US.TEST.AAPL',
                    required_start='2016-01-05',required_end='2016-01-15',minimum_rows=9)],
                consumer_id=access.PROVIDER_CLOSE_CONSUMER)
            rows=batch.results['subject'].rows
            self.assertEqual(len(rows),9)
            self.assertEqual(rows[0]['available_from'],OBSERVED)
            self.assertEqual(rows[-1]['available_from'],OBSERVED)
            source=json.loads(base.manifest)['datasets'][0]['source']
            q=json.loads(dict(base.objects)[source['provider_close_qualification_sha256']])
            self.assertEqual(q['parents'][0]['source_expires_at'],'2026-10-25T09:00:00Z')
            self.assertTrue(binding.qualification_trust_matches(trust,json.loads(base.manifest),source,q))
            self.assertFalse(batch.results['subject'].receipt['eligible_for_economics'])
            for pair in parents:
                for parent in pair:
                    self.assertEqual(dict(base.objects)[parent.generation_id],parent.manifest)

    def test_composition_rejects_anchor_conflict_before_new_review(self):
        with self.assertRaisesRegex(binding.BindingError,'^COMPOSITION_ANCHOR_CONFLICT$'):
            composition_fixture(tail_offset=7)

    def test_composition_requires_external_current_review_and_original_parent_pin(self):
        parents,e,trust,objects=composition_fixture()
        for bad in (None,replace(trust,evidence_sha256='0'*64),
                    replace(trust,parent_generation_pairs=(('0'*64,'1'*64),trust.parent_generation_pairs[1]))):
            with self.subTest(trust=type(bad).__name__):
                result=binding.compose_prepared(parents,encoded(e),decision_time='2026-10-26T02:00:00Z',
                    trusted_source=bad,proof_objects=tuple(sorted(objects.items())))
                self.assertEqual(result.status,'BLOCKED')
        result=binding.compose_prepared(parents,encoded(e),decision_time='2026-10-28T02:00:00Z',
            trusted_source=trust,proof_objects=tuple(sorted(objects.items())))
        self.assertEqual(result.blockers,('COMPOSITION_FRESH_REVIEW',))

    def test_composition_rejects_unbound_split_provenance(self):
        parents,e,trust,objects=composition_fixture()
        bad=replace(parents[0][1],provenance=b'{}')
        result=binding.compose_prepared(((parents[0][0],bad),parents[1]),encoded(e),
            decision_time='2026-10-26T02:00:00Z',trusted_source=trust,
            proof_objects=tuple(sorted(objects.items())))
        self.assertEqual(result.blockers,('COMPOSITION_PARENT_DERIVATION',))

    def test_composition_rejects_detached_parent_blob(self):
        parents,e,trust,objects=composition_fixture()
        blob=b'SYNTHETIC_DETACHED_NOT_DECLARED_IN_ACCEPTED_PARENT'
        bad=replace(parents[0][0],objects=parents[0][0].objects+((digest(blob),blob),))
        result=binding.compose_prepared(((bad,parents[0][1]),parents[1]),encoded(e),
            decision_time='2026-10-26T02:00:00Z',trusted_source=trust,
            proof_objects=tuple(sorted(objects.items())))
        self.assertEqual(result.blockers,('COMPOSITION_DETACHED_PARENT_OBJECT',))

    def test_managed_asset_clock_must_belong_to_the_actual_collection_window(self):
        for badclock in ('2016-01-06T23:29:59Z',OBSERVED):
            with self.subTest(clock=badclock):
                s,ch=managed_fixture(asset_clock=badclock)
                result=binding.prepare_managed(*s[:3],encoded(s[3]),decision_time=DECISION,
                    trusted_source=s[4],expected_managed_control_sha256=ch,
                    proof_objects=tuple(sorted(s[5].items())))
                self.assertEqual(result.blockers,('MANAGED_ASSET_CLOCKS',))

    def test_managed_asset_id_must_match_current_technical_identity(self):
        s,ch=managed_fixture(technical_security_id='00000000-0000-0000-0000-999999999999')
        result=binding.prepare_managed(*s[:3],encoded(s[3]),decision_time=DECISION,
            trusted_source=s[4],expected_managed_control_sha256=ch,
            proof_objects=tuple(sorted(s[5].items())))
        self.assertEqual(result.blockers,('MANAGED_ASSET_IDENTITY',))

    def test_composition_fresh_basis_rights_clocks_and_unknown_status_fail_closed(self):
        cases=[('common_basis',lambda d:d.update(common_split_basis_verified=False),'COMPOSITION_COMMON_BASIS'),
               ('common_basis',lambda d:d.update(rebase_allowed=True),'COMPOSITION_COMMON_BASIS'),
               ('common_basis',lambda d:d.update(split_factor='nonnumeric'),'NUMERIC_VALUE'),
               ('status_evidence',lambda d:d.update(halted_sessions=[]),'COMPOSITION_CURRENT_STATUS'),
               ('identity_evidence',lambda d:d.update(provider_security_id='wrong'),'COMPOSITION_CURRENT_IDENTITY'),
               ('identity_evidence',lambda d:d.update(expires_at='2026-10-26T01:59:59Z'),
                'COMPOSITION_CURRENT_DOCUMENT_CLOCK'),
               ('owner_rights',lambda d:d.update(supplier_expiry='2026-10-26T01:59:59Z'),
                'COMPOSITION_SUPPLIER_EXPIRED'),
               ('qualification',lambda d:d.update(observed_at='2026-10-23T01:00:00Z'),
                'COMPOSITION_BEFORE_INPUT')]
        for key,change,code in cases:
            with self.subTest(key=key,code=code):
                parents,e,trust,objects=rewrite_composition_doc(composition_fixture(),key,change)
                result=binding.compose_prepared(parents,encoded(e),decision_time='2026-10-26T02:00:00Z',
                    trusted_source=trust,proof_objects=tuple(sorted(objects.items())))
                self.assertEqual(result.blockers,(code,))

    def test_composition_preserves_known_halt_facts_and_rejects_dropped_fact(self):
        state=composition_fixture(old_known={'AAPL':['2016-01-08']})
        parents,e,trust,objects=state
        good=binding.compose_prepared(parents,encoded(e),decision_time='2026-10-26T02:00:00Z',
            trusted_source=trust,proof_objects=tuple(sorted(objects.items())))
        self.assertEqual(good.status,'REAL_SOURCE_COMPOSED_UNADMITTED',good.blockers)
        self.assertEqual(json.loads(good.bases[0].manifest)['datasets'][0]['files'][0]
                         ['instrument']['known_halted_sessions'],['2016-01-08'])
        parents,e,trust,objects=rewrite_composition_doc(state,'status_evidence',
            lambda d:d.update(known_halted_sessions=[],known_halt_source_documents=[]))
        bad=binding.compose_prepared(parents,encoded(e),decision_time='2026-10-26T02:00:00Z',
            trusted_source=trust,proof_objects=tuple(sorted(objects.items())))
        self.assertEqual(bad.blockers,('COMPOSITION_CURRENT_STATUS',))

    def test_composition_preserves_supplier_expiry_across_repeated_composition(self):
        parents,e,trust,objects=composition_fixture(rights_expiry='2026-10-26T04:00:00Z')
        first=binding.compose_prepared(parents,encoded(e),decision_time='2026-10-26T02:00:00Z',
            trusted_source=trust,proof_objects=tuple(sorted(objects.items())))
        self.assertEqual(first.status,'REAL_SOURCE_COMPOSED_UNADMITTED',first.blockers)
        p2,e2,t2,o2=composition_fixture(old_input=(first.bases,trust,'2026-10-26T02:00:00Z'),
            tail_start='2016-01-15',tail_days=['2016-01-15','2016-01-19','2016-01-20'],
            tail_offset=9,observed='2026-10-26T02:30:00Z',created='2026-10-26T03:00:00Z',
            decision='2026-10-26T03:30:00Z')
        second=binding.compose_prepared(p2,encoded(e2),decision_time='2026-10-26T03:30:00Z',
            trusted_source=t2,proof_objects=tuple(sorted(o2.items())))
        self.assertEqual(second.status,'REAL_SOURCE_COMPOSED_UNADMITTED',second.blockers)
        for base in second.bases:
            self.assertEqual(json.loads(base.provenance)['supplier_rights_expiry'],
                             '2026-10-26T04:00:00+00:00')
        p3,e3,t3,o3=composition_fixture(old_input=(second.bases,t2,'2026-10-26T03:30:00Z'),
            tail_start='2016-01-20',tail_days=['2016-01-20','2016-01-21','2016-01-22'],
            tail_offset=11,observed='2026-10-26T04:30:00Z',created='2026-10-26T05:00:00Z',
            decision='2026-10-26T05:30:00Z')
        third=binding.compose_prepared(p3,encoded(e3),decision_time='2026-10-26T05:30:00Z',
            trusted_source=t3,proof_objects=tuple(sorted(o3.items())))
        self.assertEqual(third.blockers,('COMPOSITION_SUPPLIER_EXPIRED',))

    def test_managed_rejects_regressed_meter_wrong_job_and_unprotected_master(self):
        cases=[('managed_master',lambda d:d.update(protected=False),'MANAGED_PROTECTED_MASTER'),
               ('managed_job',lambda d:d.update(name='wrong'),'MANAGED_ORIGINAL_JOB'),
               ('managed_job',lambda d:d.update(completed_at='2016-01-06T23:29:59Z'),'MANAGED_JOB_WINDOW'),
               ('original_execution',lambda d:d.pop('managed_worker_started_at'),'EXPLICIT_CLOCK_REQUIRED'),
               ('original_execution',lambda d:d.update(managed_worker_deadline='2016-01-06T23:46:00Z'),
                'MANAGED_JOB_WINDOW')]
        for key,change,code in cases:
            with self.subTest(key=key,code=code):
                s,ch=managed_fixture();oldref=s[3][key]
                doc=json.loads(s[5].pop(oldref['sha256']));change(doc);raw=encoded(doc)
                s[5][digest(raw)]=raw;s[3][key]=dict(oldref,sha256=digest(raw),bytes=len(raw))
                s[4]=replace(s[4],evidence_sha256=digest(encoded(s[3])),proof_sha256=tuple(sorted(s[5])))
                result=binding.prepare_managed(*s[:3],encoded(s[3]),decision_time=DECISION,
                    trusted_source=s[4],expected_managed_control_sha256=ch,
                    proof_objects=tuple(sorted(s[5].items())))
                self.assertEqual(result.blockers,(code,))

    def test_managed_proof_is_distinct_and_does_not_forge_legacy_checkpoint(self):
        s, ch = managed_fixture()
        args = dict(decision_time=DECISION, trusted_source=s[4], proof_objects=tuple(sorted(s[5].items())))
        legacy = binding.prepare(*s[:3], encoded(s[3]), **args)
        self.assertEqual(legacy.status, 'BLOCKED')
        result = binding.prepare_managed(*s[:3], encoded(s[3]),
                    expected_managed_control_sha256=ch, **args)
        self.assertEqual(result.status, 'REAL_SOURCE_PREPARED_UNADMITTED', result.blockers)
        for b in result.bases:
            lineage=json.loads(b.provenance)['original_checkpoint_lineage']
            self.assertEqual(lineage['kind'],'MANAGED_MAINTENANCE')
            self.assertEqual(lineage['managed_control_sha256'],ch)
            self.assertEqual(lineage['collection_started_at'],'2016-01-06T23:30:02Z')

    def test_managed_proof_needs_independent_exact_control_pin(self):
        s, ch = managed_fixture()
        result=binding.prepare_managed(*s[:3],encoded(s[3]),decision_time=DECISION,
            trusted_source=s[4],expected_managed_control_sha256='0'*64,
            proof_objects=tuple(sorted(s[5].items())))
        self.assertEqual(result.status,'BLOCKED')
        self.assertIn('MANAGED_REVIEWED_CONTROL',result.blockers)

    def test_close_batch_matches_authoritative_dst_early_close_and_invalid_dates(self):
        # Reader-only tiny cases: no Source.prepare, provider or actual archive.
        import pandas_market_calendars as mcal
        dates = ['2026-03-06', '2026-03-09', '2026-07-02', '2026-11-27']
        lookup = access._SessionCloseMap(allow_batch=True)
        lookup.include(access.day(dates[0]), access.day(dates[-1]))
        calendar = mcal.get_calendar('NYSE')
        with patch.object(calendar, 'schedule', wraps=calendar.schedule) as schedule, \
             patch.object(mcal, 'get_calendar', return_value=calendar):
            closes = [lookup[access.day(v)] for v in dates]
            self.assertEqual(schedule.call_count, 2)  # authority anchor plus range
            for v, close in zip(dates, closes):
                self.assertEqual(close, access._session_close(access.day(v)))
        self.assertEqual([v.hour for v in closes], [21, 20, 20, 18])
        for value in ('2026-07-03', '2026-07-04'):
            with self.subTest(value=value), self.assertRaisesRegex(
                    ContractError, '^INVALID_EXCHANGE_SESSION$'):
                lookup[access.day(value)]

    def test_close_batch_bounds_failure_and_call_lifetime_keep_original_fallback(self):
        import pandas_market_calendars as mcal
        session = access.day('2026-03-09')
        for start, end in ((access.day('1700-01-01'), access.day('2300-01-01')),
                           (session, session)):
            with self.subTest(start=start):
                lookup = access._SessionCloseMap(allow_batch=True)
                lookup.include(start, end)
                with patch.object(mcal, 'get_calendar', side_effect=RuntimeError('calendar')), \
                     self.assertRaisesRegex(ContractError, '^SESSION_CALENDAR_UNAVAILABLE$'):
                    lookup[session]
                self.assertIsNone(lookup.sessions(session, session))
        # An out-of-envelope day uses its real close; it cannot be accepted
        # merely because some other date was present in the batch map.
        lookup = access._SessionCloseMap(allow_batch=True)
        lookup.include(session, session)
        prior = access.day('2026-03-06')
        self.assertEqual(lookup[prior], access._session_close(prior))
        with patch.object(mcal, 'get_calendar', side_effect=RuntimeError('later outage')):
            fresh = access._SessionCloseMap(allow_batch=True)
            fresh.include(session, session)
            with self.assertRaisesRegex(ContractError, '^SESSION_CALENDAR_UNAVAILABLE$'):
                fresh[session]

    def close_batch_reader_fixture(self):
        from research_data_access_smoke import ReaderTest
        case = ReaderTest('runTest')
        case.setUp()
        self.addCleanup(case.doCleanups)
        for item in case.spec['files']:
            item['instrument']['calendar'] = 'XNYS'
        return case

    def test_close_batch_nonresearch_keeps_each_date_authority(self):
        from r1000_legacy_input_guard import latest_completed_close
        for purpose in ('training', 'backtest', 'discovery'):
            with self.subTest(purpose=purpose):
                case = self.close_batch_reader_fixture()
                case.spec['source'].update(classification='REAL_SOURCE', pit_status='VERIFIED',
                    eligible_purposes=['training', 'backtest', 'discovery', 'research'])
                dates = []
                def authority(now=None):
                    dates.append(now.date().isoformat())
                    if dates[-1] == '2026-07-02':
                        raise RuntimeError('second session authority unavailable')
                    return latest_completed_close(now)
                with patch('r1000_legacy_input_guard.latest_completed_close', side_effect=authority), \
                     self.assertRaisesRegex(ContractError, '^SESSION_CALENDAR_UNAVAILABLE$'):
                    case.read(purpose=purpose)
                self.assertEqual(dates, ['2026-07-01', '2026-07-02'])

    def test_close_batch_research_first_authority_failure_precedes_range(self):
        import pandas_market_calendars as mcal
        case = self.close_batch_reader_fixture()
        with patch('r1000_legacy_input_guard.latest_completed_close',
                   side_effect=RuntimeError('schedule absent')) as authority, \
             patch.object(mcal, 'get_calendar', side_effect=AssertionError('RANGE_BEFORE_AUTHORITY')) as calendar, \
             self.assertRaisesRegex(ContractError, '^SESSION_CALENDAR_UNAVAILABLE$'):
            case.read(purpose='research')
        self.assertEqual(authority.call_count, 1)
        calendar.assert_not_called()

    def test_close_batch_include_is_lazy_and_anchor_is_once_per_range(self):
        import pandas_market_calendars as mcal
        first, last = access.day('2026-07-01'), access.day('2026-07-06')
        lookup = access._SessionCloseMap(allow_batch=True)
        with patch.object(access, '_session_close', wraps=access._session_close) as authority, \
             patch.object(mcal, 'get_calendar', wraps=mcal.get_calendar) as calendar:
            lookup.include(first, last)
            authority.assert_not_called()
            calendar.assert_not_called()
            lookup[first]
            lookup[access.day('2026-07-02')]
            lookup[last]
            self.assertEqual(authority.call_count, 1)
            self.assertEqual(calendar.call_count, 2)  # legacy anchor, then range
        self.assertEqual(lookup.sessions(first, last),
                         [first, access.day('2026-07-02'), last])

    def test_close_batch_anchor_mismatch_disables_range_without_overriding_authority(self):
        first, last = access.day('2026-07-01'), access.day('2026-07-02')
        original = access._session_close
        actual_first = original(first) + timedelta(minutes=1)
        def authority(session):
            if session == first:
                return actual_first
            raise ContractError('SESSION_CALENDAR_UNAVAILABLE')
        lookup = access._SessionCloseMap(allow_batch=True)
        lookup.include(first, last)
        with patch.object(access, '_session_close', side_effect=authority) as calls:
            self.assertEqual(lookup[first], actual_first)
            self.assertIsNone(lookup.sessions(first, last))
            with self.assertRaisesRegex(ContractError, '^SESSION_CALENDAR_UNAVAILABLE$'):
                lookup[last]
            self.assertEqual(calls.call_count, 2)

    def test_close_batch_row_identity_and_clock_still_precede_first_anchor(self):
        for code, change in (('ROW_IDENTITY', dict(ticker='FOREIGN')),
                             ('FUTURE_AVAILABLE_FROM', dict(available_from='2027-07-01T21:00:00Z'))):
            with self.subTest(code=code):
                case = self.close_batch_reader_fixture()
                item = case.spec['files'][0]
                raw = case.transport.read(f'{access.PREFIX_V1}/objects/{item["sha256"]}')
                rows = [json.loads(v) for v in raw.splitlines()]
                rows[0].update(change)
                raw = b''.join(encoded(r) for r in rows)
                item.update(sha256=digest(raw), bytes=len(raw))
                case.transport.write(f'{access.PREFIX_V1}/objects/{digest(raw)}', raw)
                with patch('r1000_legacy_input_guard.latest_completed_close',
                           side_effect=RuntimeError('schedule absent')) as authority, \
                     self.assertRaisesRegex(ContractError, '^'+code+'$'):
                    case.read(purpose='research')
                authority.assert_not_called()

    def test_close_batch_range_failure_retains_original_per_date_checks(self):
        import pandas_market_calendars as mcal
        first, last = access.day('2026-07-01'), access.day('2026-07-06')
        dates = [first, access.day('2026-07-02'), last]
        expected = [access._session_close(value) for value in dates]
        calendar = mcal.get_calendar('NYSE')
        original_schedule = calendar.schedule
        def schedule(*args, **kwargs):
            if kwargs.get('start_date') == first and kwargs.get('end_date') == last:
                raise RuntimeError('only the range is unavailable')
            return original_schedule(*args, **kwargs)
        lookup = access._SessionCloseMap(allow_batch=True)
        lookup.include(first, last)
        with patch.object(mcal, 'get_calendar', return_value=calendar), \
             patch.object(calendar, 'schedule', side_effect=schedule), \
             patch.object(access, '_session_close', wraps=access._session_close) as authority:
            self.assertEqual([lookup[value] for value in dates], expected)
            self.assertEqual(authority.call_count, 3)
        self.assertIsNone(lookup.sessions(first, last))

    def test_close_batch_reader_exact_bytes_and_schedule_count(self):
        import pandas_market_calendars as mcal
        class OriginalLookup:
            def __init__(self, **_): self.cache = {}
            def include(self, *_): pass
            def __getitem__(self, value):
                if value not in self.cache:
                    self.cache[value] = access._session_close(value)
                return self.cache[value]
        case = self.close_batch_reader_fixture()
        generation = case.generation()
        options = dict(decision_time='2026-10-08T07:30:00Z', purpose='research',
            consumer_id='SYNTHETIC_CLOSE_BATCH_PARITY', components=[
                dict(component_id=t, instrument_id='FIXTURE:US:'+t,
                     required_start='2026-07-01', required_end='2026-07-06', minimum_rows=3)
                for t in ('SPY', 'QQQ')])
        calendar = mcal.get_calendar('NYSE')
        def run():
            with patch.object(calendar, 'schedule', wraps=calendar.schedule) as schedule, \
                 patch.object(mcal, 'get_calendar', return_value=calendar):
                batch = case.reader.read_components('ds.us.prices.daily', generation, **options)
                return batch, schedule.call_count
        with patch.object(access, '_SessionCloseMap', OriginalLookup):
            before, old_calls = run()
        after, new_calls = run()
        again, replay_calls = run()
        # One original first-session authority call plus one range per read.
        self.assertEqual((old_calls, new_calls, replay_calls), (3, 2, 2))
        self.assertEqual(before.receipt_bytes, after.receipt_bytes)
        self.assertEqual(after.receipt_bytes, again.receipt_bytes)
        for key in ('SPY', 'QQQ'):
            self.assertEqual(before.results[key].rows, after.results[key].rows)
            self.assertEqual(before.results[key].files, after.results[key].files)
            self.assertEqual(before.results[key].receipt_bytes, after.results[key].receipt_bytes)
        # The public full-read route keeps the same exact rows/receipt as well.
        with patch.object(access, '_SessionCloseMap', OriginalLookup):
            full_before = case.read(generation)
        full_after = case.read(generation)
        self.assertEqual(full_before.rows, full_after.rows)
        self.assertEqual(full_before.receipt_bytes, full_after.receipt_bytes)

    def test_close_batch_reader_preserves_first_global_clock_and_session_refusals(self):
        for code, changes in (
                ('FUTURE_AVAILABLE_FROM', dict(session_date='2026-07-04',
                                              available_from='2027-07-04T21:00:00Z')),
                ('PRE_CLOSE_AVAILABLE_FROM', dict(session_date='2026-07-02',
                                                 available_from='2026-07-02T16:59:59Z')),
                ('INVALID_EXCHANGE_SESSION', dict(session_date='2026-07-03',
                                                 available_from='2026-07-03T21:00:00Z')),
                ('ROW_IDENTITY', dict(ticker='FOREIGN', session_date='2026-07-04'))):
            with self.subTest(code=code):
                case = self.close_batch_reader_fixture()
                item = case.spec['files'][1]
                raw = case.transport.read(f'{access.PREFIX_V1}/objects/{item["sha256"]}')
                rows = [json.loads(v) for v in raw.splitlines()]
                rows[0].update(changes)
                raw = b''.join(encoded(r) for r in rows)
                item.update(sha256=digest(raw), bytes=len(raw))
                case.transport.write(f'{access.PREFIX_V1}/objects/{digest(raw)}', raw)
                with self.assertRaisesRegex(ContractError, '^'+code+'$'):
                    case.reader.read_components('ds.us.prices.daily', case.generation(),
                        decision_time='2026-10-08T07:30:00Z', purpose='research',
                        consumer_id='SYNTHETIC_GLOBAL_NOT_OPTIONAL', components=[
                            dict(component_id=t, instrument_id='FIXTURE:US:'+t,
                                 required_start='2026-07-01', required_end='2026-07-06',
                                 optional=t == 'QQQ') for t in ('SPY', 'QQQ')])

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

    def test_real_arcx_identity_survives_both_bases_and_reader_without_authority(self):
        state = real_fixture()
        state[3]['identity']['AAPL']['mic'] = 'ARCX'
        prepared = self.prepare_real(state, repin=True)
        self.assertEqual(prepared.status, 'REAL_SOURCE_PREPARED_UNADMITTED')
        self.assertEqual([b.basis for b in prepared.bases], ['RAW', 'SPLIT_ADJUSTED'])
        for basis in prepared.bases:
            spec = json.loads(basis.manifest)['datasets'][0]
            self.assertEqual(spec['files'][0]['instrument']['mic'], 'ARCX')
            self.assertEqual(spec['source']['eligible_purposes'], ['research', 'discovery'])
            transport, _, _ = fixture_transport(basis)
            result = ResearchDataReader(transport).read('ds.us.prices.daily', basis.generation_id,
                decision_time=DECISION, purpose='research', instrument_ids=['US.TEST.AAPL'],
                required_start=SESSIONS[0], required_end=SESSIONS[-1], minimum_rows=2,
                required_sessions=SESSIONS, consumer_id='SYNTHETIC_ARCX_NOT_ACTUAL_ACK')
            self.assertEqual(len(result.rows), 2)
            self.assertEqual(result.receipt['pit_status'], 'PIT_PROXY')
            self.assertFalse(result.receipt['eligible_for_economics'])
            self.assertFalse(result.receipt['eligible_for_selector'])

    def test_provider_exchange_alias_and_unknown_mic_remain_refused(self):
        for mic in ('ARCA', 'XASE', 'UNKNOWN'):
            with self.subTest(mic=mic):
                state = real_fixture()
                state[3]['identity']['AAPL']['mic'] = mic
                self.assert_real_blocked(state, 'IDENTITY_SCOPE', repin=True)

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


    def replace_view_proof(self, state, role, transform, ticker='AAPL'):
        ref = state[3]['technical_metadata'][ticker][role]
        value = json.loads(state[5].pop(ref['sha256']))
        transform(value)
        changed = encoded(value)
        ref.update(sha256=digest(changed), bytes=len(changed))
        state[5][digest(changed)] = changed

    def without_private_view(self, state):
        state = list(state)
        for pair in state[3].pop('technical_metadata').values():
            for ref in pair.values():
                state[5].pop(ref['sha256'])
        state[3].pop('private_view')
        return state

    def test_explicit_view_preserves_default_fullspan_refusal_and_original_capture(self):
        self.assert_real_blocked(self.without_private_view(private_view_fixture(selected_only=False)),
                                 'SPLIT_FACTOR_RELATION', repin=True)
        state = private_view_fixture()
        result = self.prepare_real(state)
        self.assertEqual(result.status, 'REAL_SOURCE_PREPARED_UNADMITTED')
        self.assertEqual(result, self.prepare_real(state))
        sources, provenance_hashes = [], []
        for basis in result.bases:
            manifest, provenance = json.loads(basis.manifest), json.loads(basis.provenance)
            source = manifest['datasets'][0]['source']
            sources.append(source)
            provenance_hashes.append(digest(basis.provenance))
            self.assertEqual(source['source_receipt_sha256'], digest(state[2]))
            self.assertEqual(source['source_receipt_role'], 'ORIGINAL_VERIFIED_CAPTURE_RECEIPT')
            self.assertEqual(manifest['source_run_id'], state[3]['original_run_id'])
            self.assertEqual(source['derivation_run_id'], state[3]['derivation_run_id'])
            self.assertEqual(source['basis_derivation_receipt_sha256'], digest(basis.provenance))
            self.assertEqual(dict(basis.objects)[digest(state[2])], state[2])
            self.assertEqual(dict(basis.objects)[digest(basis.provenance)], basis.provenance)
            for role in ('identity_evidence', 'corporate_actions', 'lifecycle'):
                ref = state[3][role]
                self.assertIn(ref['sha256'], source['raw_source_sha256'])
                self.assertEqual(dict(basis.objects)[ref['sha256']], state[5][ref['sha256']])
            view = provenance['explicit_private_view']
            self.assertEqual(view['obv_anchor_session'], '2016-01-05')
            self.assertEqual(view['original_symbols'], ['AAPL'])
            self.assertEqual(view['original_normalized_rows'], 6)
            self.assertEqual((view['selected_rows'], view['excluded_rows']), (2, 1))
            self.assertEqual(view['inventory']['AAPL']['original']['start'], '2016-01-04')
            self.assertEqual(view['inventory']['AAPL']['selected']['start'], '2016-01-05')
            self.assertEqual(view['inventory']['AAPL']['excluded']['rows'], 1)
            self.assertEqual(source['pit_status'], 'PIT_PROXY')
            self.assertFalse(provenance['source_admission'])
            self.assertEqual(provenance['consumer_ack'], 'NOT_RUN')
        self.assertNotEqual(*provenance_hashes)
        self.assertEqual(sources[0]['raw_source_sha256'], sources[1]['raw_source_sha256'])
        self.assertTrue(set(provenance_hashes) <= set(sources[0]['raw_source_sha256']))

    def test_explicit_view_outputs_reach_actual_component_reader_with_pinned_metadata(self):
        prepared = self.prepare_real(private_view_fixture())
        for basis in prepared.bases:
            transport, _, _ = fixture_transport(basis)
            result = ResearchDataReader(transport).read_components('ds.us.prices.daily',
                basis.generation_id, decision_time=DECISION, purpose='research',
                components=[dict(component_id='subject', instrument_id='US.TEST.AAPL',
                    required_start='2016-01-05', required_end='2016-01-06', minimum_rows=2),
                    dict(component_id='spy', instrument_id='US.TEST.SPY',
                         required_start='2016-01-05', required_end='2016-01-06', optional=True)],
                consumer_id='SYNTHETIC_VIEW_CONSUMER_NOT_ACTUAL_ACK')
            self.assertEqual(len(result.results['subject'].rows), 2)
            self.assertIn('spy', result.refusals)
            identity = result.results['subject'].receipt['instrument_identity']
            self.assertEqual(identity['asset_class'], 'EQUITY')
            self.assertEqual(identity['provider_security_id'], 'synthetic-test-asset-1')
            self.assertEqual(identity['halted_sessions'], ())  # Existing Reader freezes lists.
            self.assertEqual(identity['volume_basis'], basis.basis)
            identity_raw = transport.read('shared-research-v1/objects/' + identity['identity_evidence_sha256'])
            self.assertEqual(digest(identity_raw), identity['identity_evidence_sha256'])
            self.assertEqual(json.loads(identity_raw)['instrument_id'], 'US.TEST.AAPL')
            self.assertFalse(result.receipt['eligible_for_economics'])

    def test_explicit_view_original4_contract_fixture_has_657_sessions_each(self):
        import pandas_market_calendars as mcal
        sessions = [i.date().isoformat() for i in mcal.get_calendar('NYSE').schedule(
            start_date='2016-01-04', end_date='2026-10-13').index]
        state = private_view_fixture(names=('MU', 'WMT', 'JPM', 'XOM'), sessions=sessions,
            view_start='2024-03-01', view_end='2026-10-13')
        result = self.prepare_real(state)
        self.assertEqual(result.status, 'REAL_SOURCE_PREPARED_UNADMITTED')
        for basis in result.bases:
            files = json.loads(basis.manifest)['datasets'][0]['files']
            self.assertEqual({v['instrument']['ticker'] for v in files}, {'MU', 'WMT', 'JPM', 'XOM'})
            self.assertTrue(all(v['rows'] == 657 and v['start'] == '2024-03-01'
                                and v['end'] == '2026-10-13' for v in files))
            view = json.loads(basis.provenance)['explicit_private_view']
            self.assertEqual(view['selected_rows'], 2628)
            self.assertEqual(view['original_normalized_rows'], len(sessions) * 8)
            self.assertEqual(view['obv_anchor_session'], '2024-03-01')
            self.assertTrue(all(v['original']['rows'] == len(sessions)
                                for v in view['inventory'].values()))

    def test_explicit_view_missing_inverted_outside_and_weekend_bounds_refuse(self):
        for view, code in ((None, 'VIEW_SCHEMA'), ({}, 'VIEW_SCHEMA'),
                (dict(start='bad', end='2016-01-06', selection_reason='SOURCE_EXACT_COMPATIBILITY'), 'VIEW_WINDOW'),
                (dict(start='2016-01-06', end='2016-01-05', selection_reason='SOURCE_EXACT_COMPATIBILITY'), 'VIEW_WINDOW'),
                (dict(start='2016-01-01', end='2016-01-05', selection_reason='SOURCE_EXACT_COMPATIBILITY'), 'VIEW_WINDOW')):
            state = private_view_fixture(); state[3]['private_view'] = view
            with self.subTest(view=view):
                self.assert_real_blocked(state, code, repin=True)
        state = private_view_fixture(sessions=['2016-01-04', '2016-01-05', '2016-01-11'],
                                     view_start='2016-01-09', view_end='2016-01-10')
        self.assert_real_blocked(state, 'VIEW_EXCHANGE_SESSION')

    def test_explicit_view_future_and_unavailable_bounds_refuse(self):
        state = private_view_fixture(sessions=['2016-01-04', '2026-10-26'],
            view_start='2026-10-26', view_end='2026-10-26')
        self.assert_real_blocked(state, 'VIEW_FUTURE')
        state = private_view_fixture()
        state[3]['first_observed_readback']['at'] = '2016-01-05T21:00:00Z'
        self.assert_real_blocked(state, 'VIEW_NOT_AVAILABLE', repin=True)

    def test_explicit_view_empty_or_uneven_session_grid_cannot_shorten(self):
        state = private_view_fixture(sessions=['2016-01-04', '2016-01-05', '2016-01-11'],
            view_start='2016-01-06', view_end='2016-01-08')
        self.assert_real_blocked(state, 'VIEW_SESSION_GRID')
        state = private_view_fixture(names=('MU', 'WMT', 'JPM', 'XOM'),
                                     omit=('WMT', '2016-01-05'))
        self.assert_real_blocked(state, 'VIEW_SESSION_GRID')

    def test_explicit_view_outside_bytes_and_duplicate_rows_still_verify_originals(self):
        import gzip
        for kind in ('raw', 'duplicate_normalized', 'outside_unknown_ticker', 'raw_hash_mismatch'):
            state = list(private_view_fixture())
            rec = json.loads(state[2])
            if kind == 'raw_hash_mismatch':
                state[0] += b'SYNTHETIC_HASH_CONFLICT'
            elif kind == 'raw':
                state[0] = b'SYNTHETIC_CORRUPT_ORIGINAL_ZIP'
                rec['raw_object'].update(sha256=digest(state[0]), bytes=len(state[0]))
            else:
                decoded = gzip.decompress(state[1])
                if kind == 'outside_unknown_ticker':
                    rows = decoded.splitlines()
                    outside = json.loads(rows[0]); outside['ticker'] = 'UNLISTED'
                    changed = encoded(outside) + b'\n'.join(rows[1:]) + b'\n'
                else:
                    changed = decoded + decoded.splitlines()[0] + b'\n'
                state[1] = gzip.compress(changed, mtime=0)
                rec['normalized_object'].update(sha256=digest(state[1]), bytes=len(state[1]))
            state[2] = encoded(rec)
            with self.subTest(kind=kind):
                self.assert_real_blocked(state, 'CAPTURE_OBJECT_BINDING' if kind == 'raw_hash_mismatch'
                                         else 'ORIGINAL_CAPTURE_VERIFICATION', repin=True)

    def test_explicit_view_selected_only_identity_lifecycle_and_factors_are_sufficient(self):
        state = private_view_fixture()
        self.assertEqual(set(state[3]['split_factors']['AAPL']), {'2016-01-05', '2016-01-06'})
        self.assertEqual(state[3]['identity']['AAPL']['valid_from'], '2016-01-05')
        prepared = self.prepare_real(state)
        self.assertEqual(prepared.status, 'REAL_SOURCE_PREPARED_UNADMITTED')
        for basis in prepared.bases:
            view = json.loads(basis.provenance)['explicit_private_view']
            self.assertEqual(view['excluded_rows_scope'], 'VERIFIED_ORIGINAL_BYTES_NOT_TECHNICALLY_ADMITTED')
            self.assertEqual(view['inventory']['AAPL']['original']['rows'], 3)
            self.assertEqual(view['inventory']['AAPL']['selected']['rows'], 2)
        # Explicitly unconsumed old factor values are not certified or parsed.
        state = private_view_fixture(selected_only=False)
        state[3]['split_factors']['AAPL']['2016-01-04'] = 'UNKNOWN'
        self.assertEqual(self.prepare_real(state, repin=True).status, 'REAL_SOURCE_PREPARED_UNADMITTED')
        state = private_view_fixture(); state[3]['identity']['AAPL']['valid_from'] = '2016-01-06'
        self.assert_real_blocked(state, 'LIFECYCLE_WINDOW', repin=True)
        state = private_view_fixture()
        self.replace_view_proof(state, 'identity_evidence', lambda d:d.update(valid_from='2016-01-06'))
        self.assert_real_blocked(state, 'TECHNICAL_IDENTITY_WINDOW', repin=True)

    def test_explicit_view_selected_factor_missing_or_tampered_refuses_without_fullspan_fallback(self):
        state = private_view_fixture(); state[3]['split_factors']['AAPL'].pop('2016-01-05')
        self.assert_real_blocked(state, 'SPLIT_FACTOR_COVERAGE', repin=True)
        state = private_view_fixture(); state[3]['split_factors']['AAPL']['2016-01-05'] = '2'
        self.assert_real_blocked(state, 'SPLIT_FACTOR_RELATION', repin=True)
        self.assert_real_blocked(self.without_private_view(private_view_fixture()),
                                 'SPLIT_FACTOR_COVERAGE', repin=True)

    def test_explicit_view_missing_or_untrusted_typed_proof_cannot_supply_identity(self):
        state = private_view_fixture(); state[3].pop('technical_metadata')
        self.assert_real_blocked(state, 'TECHNICAL_METADATA_REQUIRED', repin=True)
        state = private_view_fixture()
        state[3]['technical_metadata']['AAPL']['identity_evidence']['sha256'] = '0' * 64
        self.assert_real_blocked(state, 'MISSING_OR_UNTRUSTED_PROOF', repin=True)
        state = private_view_fixture()
        self.replace_view_proof(state, 'identity_evidence', lambda d:d.update(provider_security_id='different-real-looking-id'))
        self.assert_real_blocked(state, 'REVIEWED_EVIDENCE_HASH')

    def test_explicit_view_unknown_inferred_or_conflicting_identity_metadata_refuses(self):
        cases = [('provider_security_id', None, 'PROVIDER_SECURITY_ID'),
                 ('provider_security_id', 'UNKNOWN', 'PROVIDER_SECURITY_ID'),
                 ('provider_security_id', 'AAPL', 'PROVIDER_SECURITY_ID'),
                 ('provider_security_id', 'CONTRACT_FIXTURE:asset', 'PROVIDER_SECURITY_ID'),
                 ('asset_class', 'UNKNOWN', 'TECHNICAL_ASSET_CLASS'),
                 ('mic', 'XNYS', 'TECHNICAL_IDENTITY_MISMATCH'),
                 ('provider', 'other-provider', 'TECHNICAL_ORIGINAL_BINDING'),
                 ('capture_receipt_sha256', '0' * 64, 'TECHNICAL_ORIGINAL_BINDING')]
        for key, value, code in cases:
            state = private_view_fixture()
            self.replace_view_proof(state, 'identity_evidence', lambda d:d.update({key:value}))
            with self.subTest(key=key, value=value):
                self.assert_real_blocked(state, code, repin=True)

    def test_explicit_view_halt_and_volume_unknown_never_default_to_empty_or_labels(self):
        cases = [('halted_sessions', None, 'HALT_COVERAGE_UNKNOWN'),
                 ('halt_coverage', 'UNKNOWN', 'HALT_COVERAGE_UNKNOWN'),
                 ('halted_sessions', ['2016-01-05', '2016-01-05'], 'HALT_COVERAGE_INVALID'),
                 ('halted_sessions', ['2016-01-09'], 'HALT_COVERAGE_INVALID'),
                 ('volume_basis', None, 'VOLUME_BASIS_UNKNOWN'),
                 ('volume_basis', dict(raw='RAW', split='RAW'), 'VOLUME_BASIS_UNKNOWN'),
                 ('halt_source_documents', [], 'TECHNICAL_SOURCE_DOCUMENTS'),
                 ('volume_source_documents', [], 'TECHNICAL_SOURCE_DOCUMENTS'),
                 ('provider_security_id', 'other-source-id', 'TECHNICAL_STATUS_IDENTITY')]
        for key, value, code in cases:
            state = private_view_fixture()
            self.replace_view_proof(state, 'status_evidence', lambda d:d.update({key:value}))
            with self.subTest(key=key, value=value):
                self.assert_real_blocked(state, code, repin=True)

    def test_explicit_view_typed_proof_clocks_and_halt_scope_are_enforced(self):
        for role in ('identity_evidence', 'status_evidence'):
            for key, value, code in (
                    ('available_from', None, 'EXPLICIT_CLOCK_REQUIRED'),
                    ('collected_at', '2026-10-24T08:00:00', 'EXPLICIT_CLOCK_REQUIRED'),
                    ('expires_at', '2026-10-24T08:59:00Z', 'TECHNICAL_EVIDENCE_CLOCK'),
                    ('collected_at', '2026-10-24T08:31:00Z', 'TECHNICAL_EVIDENCE_CLOCK')):
                state = private_view_fixture()
                self.replace_view_proof(state, role, lambda d:d.update({key:value}))
                with self.subTest(role=role, key=key):
                    self.assert_real_blocked(state, code, repin=True)
        state = private_view_fixture()
        self.replace_view_proof(state, 'status_evidence', lambda d:d.update(valid_from='2016-01-06'))
        self.assert_real_blocked(state, 'TECHNICAL_STATUS_WINDOW', repin=True)

    def test_explicit_view_known_halts_and_actual_evidence_expiry_survive_reader(self):
        state = private_view_fixture()
        self.replace_view_proof(state, 'status_evidence', lambda d:d.update(
            halted_sessions=['2016-01-05'], expires_at='2026-10-24T09:30:00Z'))
        prepared = self.prepare_real(state, repin=True)
        self.assertEqual(prepared.status, 'REAL_SOURCE_PREPARED_UNADMITTED')
        for basis in prepared.bases:
            spec = json.loads(basis.manifest)['datasets'][0]
            self.assertEqual(spec['files'][0]['instrument']['halted_sessions'], ['2016-01-05'])
            self.assertEqual(spec['source']['expires_at'], '2026-10-24T09:30:00Z')
            transport, _, _ = fixture_transport(basis)
            with self.assertRaisesRegex(ContractError, '^STALE_GENERATION$'):
                ResearchDataReader(transport).read_components('ds.us.prices.daily', basis.generation_id,
                    decision_time='2026-10-24T10:00:00Z', purpose='research',
                    components=[dict(component_id='subject', instrument_id='US.TEST.AAPL',
                                     required_start='2016-01-05', required_end='2016-01-06')],
                    consumer_id='SYNTHETIC_EXPIRED_VIEW_NOT_ACTUAL_ACK')


    def test_provider_close_source_and_actual_reader_keep_unknown_separate(self):
        state = provider_close_fixture()
        prepared = self.prepare_real(state)
        self.assertEqual(prepared.status, 'REAL_SOURCE_PREPARED_UNADMITTED')
        self.assertEqual(prepared, self.prepare_real(state))
        for base in prepared.bases:
            source = json.loads(base.manifest)['datasets'][0]['source']
            transport, _, _ = fixture_transport(base)
            result = ResearchDataReader(transport).read_components('ds.us.prices.daily',
                base.generation_id, decision_time=DECISION, purpose='research',
                components=[dict(component_id='subject', instrument_id='US.TEST.AAPL',
                    required_start='2016-01-05', required_end='2016-01-12', minimum_rows=6)],
                consumer_id='ohlcv-technical-feature-h1')
            receipt = result.results['subject'].receipt
            self.assertEqual(receipt['provider_close_qualification_sha256'],
                             source['provider_close_qualification_sha256'])
            self.assertEqual(receipt['physical_halt_coverage'], 'UNKNOWN')
            self.assertIsNone(receipt['instrument_identity']['halted_sessions'])
            self.assertFalse(receipt['eligible_for_economics'])
            self.assertFalse(receipt['eligible_for_selector'])
            self.assertEqual(len(result.results['subject'].rows), 6)

    def test_provider_close_self_review_does_not_replace_external_trust(self):
        state = provider_close_fixture()
        state[3]['reviewed'] = True
        self.assert_real_blocked(state, 'REVIEWED_EVIDENCE_HASH')
        state = provider_close_fixture()
        state[4] = {'reviewed': True}
        self.assert_real_blocked(state, 'TRUSTED_SOURCE_BINDING_REQUIRED')

    def test_provider_close_never_relabels_physical_complete_or_empty(self):
        for change in [dict(halt_coverage='COMPLETE_FOR_WINDOW', halted_sessions=[]),
                       dict(halt_coverage='UNKNOWN', halted_sessions=[])]:
            state = provider_close_fixture()
            self.replace_view_proof(state, 'status_evidence', lambda d:d.update(change))
            self.assert_real_blocked(state, 'PROVIDER_CLOSE_PHYSICAL_UNKNOWN', repin=True)

    def test_provider_close_reviewed_semantic_and_clock_counterexamples(self):
        cases = [
            ('meaning', 'PHYSICAL_HALTS_COMPLETE', 'PROVIDER_CLOSE_SCHEMA'),
            ('schema', 'unknown-v0', 'PROVIDER_CLOSE_SCHEMA'),
            ('consumer_id', 'BUY', 'PROVIDER_CLOSE_USE_SCOPE'),
            ('purpose', 'training', 'PROVIDER_CLOSE_USE_SCOPE'),
            ('physical_halt_coverage', 'COMPLETE_FOR_WINDOW', 'PROVIDER_CLOSE_PHYSICAL_UNKNOWN'),
            ('feed', 'IEX', 'PROVIDER_CLOSE_SOURCE_BINDING'),
            ('source_run_id', 'other-run', 'PROVIDER_CLOSE_SOURCE_BINDING'),
            ('original_public_available_at', OBSERVED, 'PROVIDER_CLOSE_PHYSICAL_UNKNOWN'),
            ('available_from', '2026-10-24T10:00:00Z', 'PROVIDER_CLOSE_CLOCK'),
            ('expires_at', '2026-10-24T08:59:59Z', 'PROVIDER_CLOSE_CLOCK')]
        for field, value, code in cases:
            with self.subTest(field=field):
                state = provider_close_fixture()
                rewrite_provider_qualification(state, lambda q:q.update({field:value}))
                self.assert_real_blocked(state, code)

    def test_provider_close_basis_identity_and_known_positive_bindings(self):
        changes = [
            (lambda q:q['instruments']['US.TEST.AAPL'].update(provider_security_id='wrong'),
             'PROVIDER_CLOSE_IDENTITY'),
            (lambda q:q['instruments']['US.TEST.AAPL']['basis_sha256'].update(RAW='0'*64),
             'PROVIDER_CLOSE_BASIS_ROWS'),
            (lambda q:q['window'].update(sessions_sha256='0'*64), 'PROVIDER_CLOSE_SESSION_GRID'),
            (lambda q:q['instruments']['US.TEST.AAPL'].update(known_halted_sessions=['2016-01-06']),
             'PROVIDER_CLOSE_KNOWN_HALTS')]
        for change, code in changes:
            with self.subTest(code=code):
                state = provider_close_fixture()
                rewrite_provider_qualification(state, change)
                self.assert_real_blocked(state, code)
        state = provider_close_fixture(known={'AAPL':['2016-01-08']})
        prepared = self.prepare_real(state)
        self.assertEqual(prepared.status, 'REAL_SOURCE_PREPARED_UNADMITTED')
        for base in prepared.bases:
            identity = json.loads(base.manifest)['datasets'][0]['files'][0]['instrument']
            self.assertEqual(identity['known_halted_sessions'], ['2016-01-08'])
            self.assertIsNone(identity['halted_sessions'])

    def test_provider_close_actual_reader_rejects_unsupported_use_and_restore(self):
        base = self.prepare_real(provider_close_fixture()).bases[0]
        for change in [dict(purpose='training'), dict(purpose='backtest'),
                       dict(purpose='discovery'), dict(consumer_id='BUY'),
                       dict(restore_to='SYNTHETIC_MUST_NOT_BE_CREATED')]:
            with self.subTest(change=change):
                transport, _, _ = fixture_transport(base)
                args = dict(decision_time=DECISION, purpose='research',
                    instrument_ids=['US.TEST.AAPL'], required_start='2016-01-05',
                    required_end='2016-01-12', consumer_id='ohlcv-technical-feature-h1')
                args.update(change)
                with self.assertRaises(ContractError):
                    ResearchDataReader(transport).read('ds.us.prices.daily', base.generation_id, **args)
        self.assertFalse(Path('SYNTHETIC_MUST_NOT_BE_CREATED').exists())
        manifest = json.loads(base.manifest)
        manifest['datasets'][0]['files'][0]['instrument']['adjustment_basis'] = 'TOTAL_RETURN'
        malformed = replace(base, manifest=encoded(manifest))
        transport, _, _ = fixture_transport(malformed)
        with self.assertRaisesRegex(ContractError, '^PROVIDER_CLOSE_BASIS_ROWS$'):
            ResearchDataReader(transport).read('ds.us.prices.daily', malformed.generation_id,
                decision_time=DECISION, purpose='research', instrument_ids=['US.TEST.AAPL'],
                required_start='2016-01-05', required_end='2016-01-12',
                consumer_id='ohlcv-technical-feature-h1')


if __name__ == '__main__':
    unittest.main()

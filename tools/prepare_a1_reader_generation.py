"""Offline T2 Source -> Reader contract preparation; no publication or capture.

Real preparation requires an independently supplied trusted Source binding and
the exact already-reviewed proof bytes. No trust anchor is built from input
claims, capture success or VERIFIED strings. Preparation grants no admission.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import (Context, Decimal, DivisionByZero, InvalidOperation, Overflow,
                     ROUND_HALF_EVEN, localcontext)
import gzip
import io
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
import zlib
import zipfile

from tools import alpaca_sip_private_backfill_v1 as capture
from tools.alpaca_sip_source_revision import external_genesis
from tools.macro_history_sources import digest, encoded
from tools.research_data_access import (ContractError, PRICE_COLUMNS, _session_close, clock, day,
    PROVIDER_CLOSE_CONSUMER, PROVIDER_COMPOSITION_SCHEMA,
    _provider_close_references, _validate_provider_close_qualification,
    _observed_volume_references, _validate_observed_volume_selection,
    FINANCIAL_DATASET, FINANCIAL_SCHEMA, FINANCIAL_COLUMNS)

MAX_ROWS = 100_000
MAX_DECODED = 32_000_000
MAX_VIEW = 18 * 1024 * 1024
MAX_REFS = 258
MAX_REFERENCE_BYTES = 128 * 1024 * 1024
MAX_PROOFS = 32
MAX_PROOF_BYTES = 16 * 1024 * 1024
REAL_GATES = (
    'owner_rights', 'decision_window', 'identity', 'corporate_actions',
    'lifecycle', 'first_observed_readback', 'producer_binding',
)
HASH = re.compile(r'[0-9a-f]{64}')
LOGICAL = re.compile(r'shared-research-v1/(generations|objects)/([0-9a-f]{64})')


class BindingError(ValueError):
    """Finite refusal, never an input payload or credential-bearing response."""


def require(ok, code):
    if not ok:
        raise BindingError(code)


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, 'DUPLICATE_JSON_KEY')
        out[key] = value
    return out


def _decode(raw, limit):
    require(type(raw) is bytes and 0 < len(raw) <= limit, 'INPUT_BYTE_BOUND')
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              BindingError('NONFINITE_JSON')))
    except BindingError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise BindingError('INVALID_JSON') from None


def _hash(value):
    require(type(value) is str and HASH.fullmatch(value), 'HASH_REFERENCE')
    return value


def _clock(value):
    try:
        return clock(value)
    except ValueError:
        raise BindingError('EXPLICIT_CLOCK_REQUIRED') from None


def _decimal(value, *, volume=False):
    require(type(value) is str and 0 < len(value) <= 80, 'DECIMAL_STRING_REQUIRED')
    try:
        number = Decimal(value)
        require(number.is_finite() and (number >= 0 if volume else number > 0),
                'NUMERIC_VALUE')
        if volume:
            require(number == number.to_integral_value() and number <= 2 ** 53,
                    'VOLUME_PRECISION')
            return number, int(number)
        typed = float(number)
        require(Decimal(str(typed)) == number and typed > 0, 'PRICE_PRECISION')
        return number, typed
    except (InvalidOperation, OverflowError):
        raise BindingError('NUMERIC_VALUE') from None


@dataclass(frozen=True)
class PreparedBasis:
    basis: str
    manifest: bytes
    provenance: bytes
    objects: tuple[tuple[str, bytes], ...]

    @property
    def generation_id(self):
        return digest(self.manifest)


@dataclass(frozen=True)
class Preparation:
    status: str
    blockers: tuple[str, ...]
    bases: tuple[PreparedBasis, ...] = ()


@dataclass(frozen=True)
class TrustedSourceBinding:
    """Trust input from the existing Source's independently accepted evidence.

    The caller must obtain these pins from its canonical reviewed Source record,
    never from the untrusted evidence packet. This module neither authenticates
    a reviewer nor creates this authority. No default/config/CLI auto-trust exists.
    The review receipt can retain its original format; its exact bytes are pinned.
    credential_binding is the existing non-secret Source reference, not a newly
    computed auth hash. All positive tests inject synthetic trust explicitly.
    """
    review_reference: str
    review_receipt_sha256: str
    evidence_sha256: str
    proof_sha256: tuple[str, ...]
    original_run_id: int
    original_run_attempt: int
    original_source_sha: str
    credential_binding: str
    derivation_run_id: str
    derivation_code_sha: str
    adapter_file_sha256: str


@dataclass(frozen=True)
class TrustedCompositionBinding:
    """Fresh external review of two exact immutable parent pairs, research only."""
    review_reference: str
    review_receipt_sha256: str
    evidence_sha256: str
    proof_sha256: tuple[str, ...]
    credential_binding: str
    derivation_run_id: str
    derivation_code_sha: str
    adapter_file_sha256: str
    parent_generation_pairs: tuple[tuple[str, str], tuple[str, str]]
    parent_decisions: tuple[str, str]
    parent_bindings: tuple[object, object]
    observed_revision_sha256: str | None = None


def qualification_trust_matches(trust, manifest, source, qualification):
    """Consistency with an external caller pin; never self-create authority."""
    if type(trust) not in (TrustedSourceBinding, TrustedCompositionBinding):
        return False
    composed = type(trust) is TrustedCompositionBinding
    pins = trust.proof_sha256
    if not (type(pins) is tuple and 1 <= len(pins) <= (64 if composed else MAX_PROOFS)
            and len(set(pins)) == len(pins)
            and all(type(h) is str and HASH.fullmatch(h) for h in pins)):
        return False
    if not (source.get('provider_close_qualification_sha256') in pins
            and trust.review_receipt_sha256 in pins
            and trust.review_receipt_sha256 in source.get('raw_source_sha256', [])
            and source.get('qualification_review_receipt_sha256') == trust.review_receipt_sha256
            and source.get('qualification_adapter_file_sha256') == trust.adapter_file_sha256
            and source.get('producer_config_sha256') == trust.evidence_sha256
            and source.get('producer_code_sha') == trust.derivation_code_sha
            and source.get('derivation_run_id') == trust.derivation_run_id):
        return False
    if not composed:
        return (qualification.get('schema') != PROVIDER_COMPOSITION_SCHEMA
                and manifest.get('source_run_id') == str(trust.original_run_id))
    pairs = [[p['raw_manifest']['sha256'], p['split_manifest']['sha256']]
             for p in qualification.get('parents', [])]
    revision = qualification.get('observed_revision_selection')
    if ((trust.observed_revision_sha256 is None and (revision is not None
            or 'observed_revision_selection_sha256' in source))
            or (trust.observed_revision_sha256 is not None and
                (type(revision) is not dict or revision.get('sha256') != trust.observed_revision_sha256
                 or source.get('observed_revision_selection_sha256') != trust.observed_revision_sha256))):
        return False
    return (qualification.get('schema') == PROVIDER_COMPOSITION_SCHEMA
            and manifest.get('source_run_id') == trust.derivation_run_id
            and pairs == [list(p) for p in trust.parent_generation_pairs])


def _reviewed_volume_selection(legs, descriptors, identities, parents, memory,
                              trusted, revision_bytes, context_id, decision, proof):
    require(type(revision_bytes) is bytes
            and digest(revision_bytes) == _hash(trusted.observed_revision_sha256)
            and callable(proof), 'REVISION_EXTERNAL_PIN_REQUIRED')
    revision = _decode(revision_bytes,64*1024)
    _validate_observed_volume_selection(revision,descriptors,identities[0],context_id,decision)
    proof(revision['comparison_report'],64*1024)
    fields = ('open','high','low','close','volume')
    for index, record in enumerate(revision['captures']):
        raw, normalized, receipt_raw, checkpoint_raw = (
            proof(record[k],64*1024) for k in ('raw','normalized','receipt','checkpoint'))
        receipt, checkpoint = _decode(receipt_raw,64*1024), _decode(checkpoint_raw,64*1024)
        require(receipt.get('source') == capture.SOURCE and receipt.get('symbols') == ['MU']
                and receipt.get('source_admission') is False and receipt.get('pit_verified') is False
                and all({k:receipt[name][k] for k in ('sha256','bytes')} == record[role]
                    for role,name in (('raw','raw_object'),('normalized','normalized_object'))),
                'REVISION_CAPTURE_BINDING')
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                require(sum(i.file_size for i in archive.infolist()) <= 64*1024,
                        'REVISION_ARCHIVE_BOUND')
            with gzip.GzipFile(fileobj=io.BytesIO(normalized)) as stream:
                decoded = stream.read(64*1024+1)
            require(len(decoded) <= 64*1024, 'REVISION_ARCHIVE_BOUND')
            capture.verify_archived_group(raw,normalized,receipt)
        except (capture.Refused,zipfile.BadZipFile,OSError,EOFError):
            raise BindingError('REVISION_ORIGINAL_ARCHIVE') from None
        normalized_rows = [_decode(line,64*1024) for line in decoded.splitlines() if line]
        records = checkpoint.get('receipts')
        require(checkpoint.get('schema') == 'a1-managed-run-checkpoint-v1'
                and checkpoint.get('state') == 'COMPLETE'
                and checkpoint.get('run_id') == record['run_id']
                and checkpoint.get('source_sha') == receipt.get('source_sha')
                and type(records) is list and 1 <= len(records) <= 2
                and checkpoint.get('coverage_updates',{}).get('MU') == checkpoint.get('session')
                and 'MU' not in checkpoint.get('held',{'MU':'UNKNOWN'}), 'REVISION_CHECKPOINT')
        matches = [r for r in records if type(r) is dict and type(r.get('objects')) is list
                   and len(r['objects']) == 3
                   and r['objects'][2].get('sha256') == record['receipt']['sha256']
                   and r['objects'][2].get('bytes') == record['receipt']['bytes']]
        require(len(matches) == 1 and matches[0]['objects'][:2] ==
                    [receipt['raw_object'],receipt['normalized_object']]
                and matches[0].get('collection_started_at') == record['collection_started_at']
                and matches[0].get('collection_finished_at') == record['collection_finished_at']
                and matches[0].get('public_available_at') is None
                and _clock(record['collection_finished_at']) <= _clock(checkpoint.get('completed_at'))
                    <= _clock(descriptors[index]['source_collected_at'])
                and receipt.get('end') == (day(checkpoint['session'])+timedelta(days=1)).isoformat(),
                'REVISION_CHECKPOINT')
        assets = receipt.get('asset_precheck')
        require(type(assets) is list and len(assets) == 1, 'REVISION_ASSET')
        asset = capture.asset_record(assets[0]['response_utf8'].encode(),'MU')
        require(asset['id'] == identities[index]['provider_security_id']
                and asset['exchange'] == 'NASDAQ'
                and _clock(assets[0]['collected_at_utc']) <= _clock(record['collection_started_at']),
                'REVISION_ASSET')
        for basis, adjustment in (('RAW','raw'),('SPLIT_ADJUSTED','split')):
            parent = parents[index][0 if basis == 'RAW' else 1]
            spec = _decode(parent.manifest,1024*1024)['datasets'][0]
            derivation_ref = record['derivations'][basis]
            h = derivation_ref['sha256']
            require(h in memory and (h == digest(parent.provenance)
                    or h in spec['source']['raw_source_sha256'])
                    and record['receipt']['sha256'] in spec['source']['raw_source_sha256'],
                    'REVISION_ORIGINAL_LINEAGE')
            derivation_raw = proof(derivation_ref,64*1024)
            require(derivation_raw == memory[h], 'REVISION_ORIGINAL_LINEAGE')
            derivation = _decode(derivation_raw,64*1024)
            lineage = derivation.get('original_checkpoint_lineage',{})
            require(derivation.get('schema') == 'a1-reader-derivation-v1'
                    and derivation.get('basis') == basis
                    and derivation.get('original_objects') == dict(
                        raw_sha256=record['raw']['sha256'], normalized_sha256=record['normalized']['sha256'],
                        capture_receipt_sha256=record['receipt']['sha256'])
                    and str(record['run_id']) == derivation.get('original_run_id')
                    and lineage.get('kind') == 'MANAGED_MAINTENANCE'
                    and lineage.get('final_checkpoint_sha256') == record['checkpoint']['sha256']
                    and lineage.get('selected_capture_receipt_sha256') == record['receipt']['sha256']
                    and lineage.get('managed_control_sha256') == checkpoint.get('control_sha256')
                    and all(lineage.get(k) == record[k] for k in
                            ('collection_started_at','collection_finished_at')),
                    'REVISION_ORIGINAL_LINEAGE')
            row = legs[index][basis][-1 if index == 0 else 0]
            selected = [r for r in normalized_rows if r['date'] == revision['anchor_session']
                        and r['adjustment'] == adjustment and r['ticker'] == 'MU']
            require(len(selected) == 1 and selected[0]['currency'] == 'USD'
                    and all(Decimal(str(row[k])) == Decimal(str(selected[0][k])) for k in fields)
                    and digest(encoded(row)) == revision['anchors'][basis][
                        'old_row_sha256' if index == 0 else 'new_row_sha256'], 'REVISION_ANCHOR_BINDING')
    for index,basis in enumerate(('RAW','SPLIT_ADJUSTED')):
        old, new = legs[0][basis][-1], legs[1][basis][0]
        change = revision['differences'][index]
        require(all(Decimal(str(old[k])) == Decimal(str(new[k])) for k in fields[:-1])
                and old['volume'] == change['old'] and new['volume'] == change['new'],
                'REVISION_CHANGE_SET')
    require(len(legs[0]['RAW']) >= 2 and legs[0]['RAW'][-2]['session_date'] ==
            revision['selection']['old_end'], 'REVISION_SELECTION_WINDOW')
    return {b:legs[0][b][:-1]+legs[1][b] for b in ('RAW','SPLIT_ADJUSTED')}


def _composition_material(parents, trusted, security_id, *, revision_bytes=None,
                          revision_context=None, decision=None, proof=None):
    """Read the selected immutable inputs at their original admitted cutoffs.

    A past qualification is historical provenance here. Fresh composition
    rights/identity/basis/status review below is still mandatory for current use.
    This helper creates no qualified manifest or admission.
    """
    from tools.research_data_access import ResearchDataReader, PREFIX_V1
    require(type(trusted) is TrustedCompositionBinding and type(parents) is tuple
            and len(parents) == 2 and type(trusted.parent_generation_pairs) is tuple
            and len(trusted.parent_generation_pairs) == 2
            and type(trusted.parent_decisions) is tuple and len(trusted.parent_decisions) == 2
            and type(trusted.parent_bindings) is tuple and len(trusted.parent_bindings) == 2,
            'COMPOSITION_TRUST_REQUIRED')
    require(type(security_id) is str and 0 < len(security_id) <= 200, 'COMPOSITION_IDENTITY')
    memory, total = {}, 0
    for pair, expected in zip(parents, trusted.parent_generation_pairs):
        require(type(pair) is tuple and len(pair) == 2 and type(expected) is tuple
                and len(expected) == 2, 'COMPOSITION_PARENT_PAIR')
        for basis, wanted, h in zip(pair, ('RAW','SPLIT_ADJUSTED'), expected):
            require(type(basis) is PreparedBasis and basis.basis == wanted
                    and digest(basis.manifest) == _hash(h)
                    and type(basis.objects) is tuple and len(basis.objects) <= MAX_REFS,
                    'COMPOSITION_PARENT_PAIR')
            parent_manifest = _decode(basis.manifest,1024*1024)
            price_specs = [s for s in parent_manifest.get('datasets',[]) if type(s) is dict
                           and s.get('dataset_id') == 'ds.us.prices.daily']
            require(len(price_specs) == 1 and type(basis.provenance) is bytes
                    and 0 < len(basis.provenance) <= 1024*1024
                    and digest(basis.provenance) == price_specs[0]['source'].get('basis_derivation_receipt_sha256'),
                    'COMPOSITION_PARENT_DERIVATION')
            derivation = _decode(basis.provenance,1024*1024)
            require(derivation.get('schema') in ('a1-reader-derivation-v1','a1-reviewed-source-composition-v1')
                    and derivation.get('basis') == basis.basis
                    and type(derivation.get('derived_objects')) is list
                    and all(f['sha256'] in derivation['derived_objects'] for f in price_specs[0]['files']),
                    'COMPOSITION_PARENT_DERIVATION')
            declared = set(price_specs[0]['source']['raw_source_sha256']) | {
                f['sha256'] for f in price_specs[0]['files']} | {h,digest(basis.provenance)}
            require(all(type(item) is tuple and len(item) == 2 and item[0] in declared
                        for item in basis.objects), 'COMPOSITION_DETACHED_PARENT_OBJECT')
            for key, raw in ((h,basis.manifest),(digest(basis.provenance),basis.provenance),*basis.objects):
                _hash(key)
                require(type(raw) is bytes and 0 < len(raw) <= MAX_VIEW and digest(raw) == key,
                        'COMPOSITION_INPUT_HASH')
                require(key not in memory or memory[key] == raw, 'COMPOSITION_INPUT_COLLISION')
                if key not in memory:
                    total += len(raw)
                    require(total <= MAX_REFERENCE_BYTES, 'COMPOSITION_INPUT_BOUND')
                    memory[key] = raw
    class LocalInputs:
        def read(self, path):
            require(type(path) is str and LOGICAL.fullmatch(path), 'COMPOSITION_INPUT_PATH')
            h = path.rsplit('/',1)[-1]
            require(h in memory, 'COMPOSITION_MISSING_INPUT')
            return memory[h]
    reader = ResearchDataReader(LocalInputs())
    legs, descriptors, identities = [], [], []
    for index, pair in enumerate(parents):
        arrays, refs, specs, manifests, qualifications = {}, {}, [], [], []
        for basis in pair:
            manifest = _decode(basis.manifest, 1024*1024)
            candidates = [s for s in manifest.get('datasets', [])
                          if type(s) is dict and s.get('dataset_id') == 'ds.us.prices.daily']
            require(len(candidates) == 1, 'COMPOSITION_PARENT_DATASET')
            spec = candidates[0]
            files = [f for f in spec.get('files', []) if type(f) is dict
                     and f.get('instrument', {}).get('instrument_id') == security_id]
            require(len(files) == 1 and files[0]['instrument']['adjustment_basis'] == basis.basis,
                    'COMPOSITION_PARENT_INSTRUMENT')
            f = files[0]; qh = spec['source'].get('provider_close_qualification_sha256')
            require(qh in memory, 'COMPOSITION_PARENT_QUALIFICATION')
            q = _decode(memory[qh], 64*1024)
            binding = trusted.parent_bindings[index]
            require(qualification_trust_matches(binding, manifest, spec['source'], q)
                    and binding.credential_binding == trusted.credential_binding,
                    'COMPOSITION_PARENT_REVIEW')
            batch = reader.read_components('ds.us.prices.daily', basis.generation_id,
                decision_time=trusted.parent_decisions[index], purpose='research',
                components=[dict(component_id=security_id,instrument_id=security_id,
                                 required_start=f['start'],required_end=f['end'])],
                consumer_id=PROVIDER_CLOSE_CONSUMER)
            require(not batch.refusals, 'COMPOSITION_PARENT_READ')
            arrays[basis.basis] = [dict(r) for r in batch.results[security_id].rows]
            refs[basis.basis] = dict(sha256=basis.generation_id, bytes=len(basis.manifest))
            specs.append(spec); manifests.append(manifest); qualifications.append(q)
            require(f['instrument']['volume_basis'] == basis.basis,
                    'COMPOSITION_PARENT_VOLUME_BASIS')
        require(qualifications[0] == qualifications[1]
                and specs[0]['source']['raw_source_sha256'] == specs[1]['source']['raw_source_sha256']
                and manifests[0]['source_run_id'] == manifests[1]['source_run_id']
                and specs[0]['source']['source_receipt_sha256'] == specs[1]['source']['source_receipt_sha256'],
                'COMPOSITION_PARENT_RAW_SPLIT_LINEAGE')
        derivations = [_decode(b.provenance,1024*1024) for b in pair]
        require(derivations[0].get('supplier_rights_expiry') == derivations[1].get('supplier_rights_expiry')
                and all(specs[0]['source'].get(k) == specs[1]['source'].get(k) for k in
                    ('producer_code_sha','producer_config_sha256','derivation_run_id')),
                'COMPOSITION_PARENT_RAW_SPLIT_LINEAGE')
        source = specs[0]['source']; q = qualifications[0]
        identity = next(f['instrument'] for f in specs[0]['files']
                        if f['instrument']['instrument_id'] == security_id)
        provenance = _decode(pair[0].provenance, 1024*1024)
        require(digest(pair[0].provenance) == source.get('basis_derivation_receipt_sha256'),
                'COMPOSITION_PARENT_DERIVATION')
        supplier = provenance.get('supplier_rights_expiry')
        if supplier is not None:
            _clock(supplier)
        qh = source['provider_close_qualification_sha256']
        descriptors.append(dict(raw_manifest=refs['RAW'],split_manifest=refs['SPLIT_ADJUSTED'],
            qualification=dict(sha256=qh,bytes=len(memory[qh])),source_run_id=manifests[0]['source_run_id'],
            review_decision_at=trusted.parent_decisions[index],source_available_from=source['available_from'],
            source_collected_at=source['collected_at'],source_expires_at=source['expires_at'],
            supplier_expiry=supplier,original_review_receipt_sha256=trusted.parent_bindings[index].review_receipt_sha256,
            original_adapter_file_sha256=trusted.parent_bindings[index].adapter_file_sha256,
            window=dict(start=arrays['RAW'][0]['session_date'],end=arrays['RAW'][-1]['session_date'])))
        require([r['session_date'] for r in arrays['RAW']] ==
                [r['session_date'] for r in arrays['SPLIT_ADJUSTED']], 'COMPOSITION_PARENT_GRID')
        legs.append(arrays); identities.append(identity)
    for key in ('instrument_id','provider_security_id','ticker','asset_class','provider',
                'market','mic','calendar','timezone','currency'):
        if key == 'provider':
            require(all(_decode(p[0].manifest,1024*1024)['datasets'][0]['source']['provider'] == capture.SOURCE
                        for p in parents), 'COMPOSITION_PROVIDER')
        else:
            require(identities[0].get(key) == identities[1].get(key)
                    and identities[0].get(key) is not None, 'COMPOSITION_IDENTITY')
    anchor = legs[0]['RAW'][-1]['session_date']
    require(legs[1]['RAW'][0]['session_date'] == anchor and len(legs[1]['RAW']) >= 2
            and legs[1]['RAW'][-1]['session_date'] > anchor, 'COMPOSITION_OVERLAP')
    fields = ('open','high','low','close','volume')
    if revision_bytes is None:
        require(trusted.observed_revision_sha256 is None, 'REVISION_EXTERNAL_PIN_REQUIRED')
        for basis in ('RAW','SPLIT_ADJUSTED'):
            before, after = legs[0][basis][-1], legs[1][basis][0]
            require(all(Decimal(str(before[k])) == Decimal(str(after[k])) for k in fields),
                    'COMPOSITION_ANCHOR_CONFLICT')
        rows = {b: legs[0][b] + legs[1][b][1:] for b in ('RAW','SPLIT_ADJUSTED')}
        raw_anchor, split_anchor = legs[0]['RAW'][-1], legs[0]['SPLIT_ADJUSTED'][-1]
    else:
        rows = _reviewed_volume_selection(legs,descriptors,identities,parents,memory,trusted,
            revision_bytes,revision_context,decision,proof)
        raw_anchor, split_anchor = legs[1]['RAW'][0], legs[1]['SPLIT_ADJUSTED'][0]
    with localcontext(Context(prec=200,rounding=ROUND_HALF_EVEN,
            Emin=-999999,Emax=999999,capitals=1,clamp=0,flags=[],
            traps=[InvalidOperation,DivisionByZero,Overflow])):
        factor = Decimal(str(raw_anchor['close'])) / Decimal(str(split_anchor['close']))
        require(all(Decimal(str(raw_anchor[k])) == Decimal(str(split_anchor[k]))*factor
                    for k in fields[:-1])
                and Decimal(str(split_anchor['volume'])) == Decimal(str(raw_anchor['volume']))*factor,
                'COMPOSITION_ANCHOR_FACTOR')
    dates = [r['session_date'] for r in rows['RAW']]
    require(len(dates) <= MAX_ROWS and len(dates) == len(set(dates)), 'COMPOSITION_ROW_BOUND')
    import pandas_market_calendars as mcal
    expected = list(mcal.get_calendar('NYSE').schedule(start_date=dates[0],end_date=dates[-1])
                    .index.strftime('%Y-%m-%d'))
    require(dates == expected and dates == [r['session_date'] for r in rows['SPLIT_ADJUSTED']],
            'COMPOSITION_SESSION_GRID')
    known = set()
    for index, pair in enumerate(parents):
        manifest = _decode(pair[0].manifest,1024*1024)
        qh = manifest['datasets'][0]['source']['provider_close_qualification_sha256']
        known.update(_decode(memory[qh],64*1024)['instruments'][security_id]['known_halted_sessions'])
    return dict(rows=rows,parents=descriptors,identity=identities[0],objects=memory,
                anchor=anchor,factor=str(factor),known_halted_sessions=sorted(known))


def _checkpoint_reference(ref):
    require(type(ref) is dict and set(ref) == {'file_id', 'sha256', 'bytes'}
            and type(ref['file_id']) is str
            and re.fullmatch(r'[A-Za-z0-9_-]{10,100}', ref['file_id'])
            and type(ref['bytes']) is int and 0 < ref['bytes'] <= 1024 * 1024,
            'CHECKPOINT_PATH_REFERENCE')
    _hash(ref['sha256'])


def _checkpoint_prefix(state, receipt):
    """Reuse the capture resume membership rules without reading sibling prices."""
    require(type(state) is dict and state.get('schema') == capture.SCHEMA
            and state.get('state') == 'PRIVATE_RESEARCH_ONLY'
            and state.get('source') == capture.SOURCE
            and all(state.get(k) == receipt.get(k) for k in
                    ('source_sha', 'seed_sha256', 'cohort_scope', 'start', 'end', 'asof'))
            and all(state.get(k) is False for k in
                    ('source_admission', 'pit_verified', 'historical_identity_verified',
                     'commercial_use_authorized')), 'CHECKPOINT_PATH_CONTEXT')
    names = [state.get(k) for k in ('examined', 'completed', 'held',
                                  'last_collected', 'last_no_bars', 'last_held')]
    require(all(type(a) is list and len(a) <= 1500
                and all(type(s) is str and capture.SYMBOL.fullmatch(s) for s in a)
                and len(set(a)) == len(a) for a in names), 'CHECKPOINT_PATH_MEMBERSHIP')
    examined, done, held, collected, absent, last_held = names
    held_set = set(held)
    require(examined and set(done).isdisjoint(held)
            and set(examined) == set(done) | set(held)
            and [s for s in examined if s not in held_set] == done
            and [s for s in examined if s in held_set] == held,
            'CHECKPOINT_PATH_MEMBERSHIP')
    refs = state.get('last_objects')
    status = state.get('last_status')
    if status == 'VERIFIED_RAW_SPLIT':
        count = len(collected) + len(absent)
        require(1 <= count <= capture.GROUP_SIZE and not last_held
                and set(collected).isdisjoint(absent)
                and set(examined[-count:]) == set(collected) | set(absent)
                and done[-count:] == examined[-count:]
                and type(refs) is list and len(refs) == 3,
                'CHECKPOINT_PATH_GROUP')
        prefix = (examined[:-count], done[:-count], held)
    else:
        allowed = ('HELD_BAR_VALUE', 'HELD_PROVIDER_ASSET', 'HELD_UNCERTAIN_STORAGE')
        require(status in allowed and (receipt.get('cohort_scope') is not None
                or status == 'HELD_BAR_VALUE')
                and 1 <= len(last_held) <= capture.GROUP_SIZE
                and not collected and not absent
                and examined[-len(last_held):] == held[-len(last_held):] == last_held
                and type(refs) is list and len(refs) == 1, 'CHECKPOINT_PATH_GROUP')
        count = len(last_held)
        prefix = (examined[:-count], done, held[:-count])
    # Sibling references are metadata only. Their raw/normalized/marker payloads
    # are not read or claimed verified by this selected-path operation.
    require(all(type(ref) is dict and type(ref.get('bytes')) is int
                and 0 < ref['bytes'] <= MAX_REFERENCE_BYTES
                and type(ref.get('sha256')) is str and HASH.fullmatch(ref['sha256'])
                for ref in refs), 'CHECKPOINT_PATH_OBJECTS')
    return prefix


def _selected_checkpoint(evidence, meter, final, receipt, proof):
    final_ref = evidence['original_checkpoint']
    path = evidence.get('original_checkpoint_path')
    if path is None:
        return final, dict(kind='FINAL_GROUP', final_checkpoint_sha256=final_ref['sha256'],
                           selected_checkpoint_sha256=final_ref['sha256'],
                           checkpoint_sha256=[final_ref['sha256']], unselected_price_reads=0)
    require(type(path) is list and 1 <= len(path) < MAX_PROOFS, 'CHECKPOINT_PATH_BOUND')
    before, after = meter.get('examined_before'), meter.get('examined_after')
    require(type(before) is int and type(after) is int and 0 <= before < after <= 1500
            and after - before <= 32
            and meter.get('cohort_scope') == receipt.get('cohort_scope'),
            'CHECKPOINT_RUN_BOUND')
    parent_hash = _hash(meter.get('parent_checkpoint_sha256'))
    scope = receipt.get('cohort_scope')
    if scope is not None:
        try:
            capture.external_scope(scope)
        except ValueError:
            raise BindingError('CHECKPOINT_PATH_CONTEXT') from None
        require(scope['input_sha256'] == receipt['seed_sha256'], 'CHECKPOINT_PATH_CONTEXT')
    parent_ref = evidence.get('original_parent_checkpoint')
    if before == 0:
        require(parent_ref is None and scope is not None
                and receipt['start'] == '2016-01-04' and receipt['end'] == '2026-10-14',
                'CHECKPOINT_PARENT_BOUND')
        try:
            require(external_genesis(capture, scope) == parent_hash, 'CHECKPOINT_PARENT_BOUND')
        except ValueError:
            raise BindingError('CHECKPOINT_PARENT_BOUND') from None
    else:
        _checkpoint_reference(parent_ref)
        require(parent_ref['sha256'] == parent_hash, 'CHECKPOINT_PARENT_BOUND')
        parent_state = _decode(proof(parent_ref), 1024 * 1024)
        _checkpoint_prefix(parent_state, receipt)
        require(len(parent_state['examined']) == before
                and final.get('examined', [])[:before] == parent_state['examined']
                and [s for s in final.get('completed', []) if s in set(parent_state['examined'])]
                    == parent_state['completed']
                and [s for s in final.get('held', []) if s in set(parent_state['examined'])]
                    == parent_state['held'], 'CHECKPOINT_PARENT_BOUND')
    ids = set()
    if 'file_id' in final_ref:
        _checkpoint_reference(final_ref)
        ids.add(final_ref['file_id'])
    parent_id = parent_ref['file_id'] if before else None
    require(parent_id not in ids, 'CHECKPOINT_PARENT_BOUND')
    current, hashes = final, [final_ref['sha256']]
    prefix = _checkpoint_prefix(current, receipt)
    require(len(current['examined']) == after, 'CHECKPOINT_RUN_BOUND')
    for ref in path:
        _checkpoint_reference(ref)
        require(ref['file_id'] != parent_id, 'CHECKPOINT_PARENT_BOUND')
        require(ref['sha256'] not in hashes and ref['file_id'] not in ids,
                'CHECKPOINT_PATH_CYCLE')
        require(len(prefix[0]) > before and current.get('previous_checkpoint') == ref,
                'CHECKPOINT_PATH_LINK')
        current = _decode(proof(ref), 1024 * 1024)
        next_prefix = _checkpoint_prefix(current, receipt)
        require((current['examined'], current['completed'], current['held']) == prefix,
                'CHECKPOINT_PATH_PREFIX')
        hashes.append(ref['sha256']); ids.add(ref['file_id'])
        prefix = next_prefix
    require(len(prefix[0]) >= before, 'CHECKPOINT_RUN_BOUND')
    previous = current.get('previous_checkpoint')
    if previous is None:
        # The existing external controller uses a logical genesis, not a stored
        # empty checkpoint. Reuse that pure helper; never invent a Drive object.
        require(before == len(prefix[0]) == 0 and scope is not None
                and receipt['start'] == '2016-01-04' and receipt['end'] == '2026-10-14',
                'CHECKPOINT_PARENT_BOUND')
    else:
        _checkpoint_reference(previous)
        require(previous['sha256'] not in hashes and previous['file_id'] not in ids
                and ((previous == parent_ref) if len(prefix[0]) == before
                     else (previous['sha256'] != parent_hash
                           and previous['file_id'] != parent_id)), 'CHECKPOINT_PARENT_BOUND')
    require(current.get('last_collected') == receipt.get('collected')
            and current.get('last_no_bars') == receipt.get('no_bars')
            and current.get('last_held') == []
            and current['examined'][-len(receipt['symbols']):] == receipt['symbols'],
            'ORIGINAL_CHECKPOINT_BINDING')
    return current, dict(kind='BOUNDED_ANCESTOR', final_checkpoint_sha256=hashes[0],
                         selected_checkpoint_sha256=hashes[-1], checkpoint_sha256=hashes,
                         examined_before=before, examined_after=after,
                         parent_checkpoint_sha256=parent_hash, unselected_price_reads=0)


def _technical_document_refs(role, document):
    if role == 'provider_close_qualification':
        try:
            return [dict(sha256=h, bytes=n) for h, n in
                    _provider_close_references(document).items()]
        except ContractError as exc:
            raise BindingError(str(exc)) from None
    fields = (('source_documents',) if role == 'identity_evidence' else
              ('volume_source_documents',) if 'provider_close_qualification' in document else
              ('halt_source_documents', 'volume_source_documents'))
    refs = []
    for field in fields:
        sources = document.get(field)
        require(type(sources) is list and 1 <= len(sources) <= 8,
                'TECHNICAL_SOURCE_DOCUMENTS')
        refs.extend(sources)
    return refs


def _technical_proofs(evidence, receipt, proof):
    """Resolve reviewed local bytes, not caller booleans or ticker enrichment."""
    if 'private_view' not in evidence:
        require('technical_metadata' not in evidence, 'EXPLICIT_VIEW_REQUIRED')
        return {}
    refs = evidence.get('technical_metadata')
    require(type(refs) is dict and set(refs) == set(receipt['collected']),
            'TECHNICAL_METADATA_REQUIRED')
    out = {}
    for ticker, pair in refs.items():
        require(type(pair) is dict and set(pair) == {'identity_evidence', 'status_evidence'},
                'TECHNICAL_METADATA_SCHEMA')
        documents = {}
        for role in ('identity_evidence', 'status_evidence'):
            raw = proof(pair[role])
            document = _decode(raw, 64 * 1024)
            require(type(document) is dict, 'TECHNICAL_EVIDENCE_SCHEMA')
            for ref in _technical_document_refs(role, document):
                proof(ref)
            if role == 'identity_evidence':
                require(any(ref['sha256'] == evidence['identity_evidence']['sha256']
                            for ref in document['source_documents']),
                        'IDENTITY_ORIGINAL_PROOF_BINDING')
            documents[role] = (document, raw, digest(raw))
            if role == 'status_evidence' and 'provider_close_qualification' in document:
                qraw = proof(document['provider_close_qualification'])
                qualification = _decode(qraw, 64 * 1024)
                for ref in _technical_document_refs('provider_close_qualification', qualification):
                    proof(ref)
                documents['provider_close_qualification'] = (qualification, qraw, digest(qraw))
        out[ticker] = documents
    return out


def _private_view(evidence, receipt, observed, decision, real):
    if 'private_view' not in evidence:
        return None, None
    require(real, 'VIEW_REVIEWED_PROOFS_REQUIRED')
    view = evidence['private_view']
    require(type(view) is dict and set(view) == {'start', 'end', 'selection_reason'}
            and view['selection_reason'] == 'SOURCE_EXACT_COMPATIBILITY', 'VIEW_SCHEMA')
    try:
        start, end = day(view['start']), day(view['end'])
        original_start, original_end = day(receipt['start']), day(receipt['end'])
    except ValueError:
        raise BindingError('VIEW_WINDOW') from None
    require(original_start <= start <= end < original_end, 'VIEW_WINDOW')
    require(end <= decision.date(), 'VIEW_FUTURE')
    require(0 < (original_end - original_start).days <= MAX_ROWS, 'VIEW_CALENDAR_BOUND')
    # The same offline NYSE library used by Reader._session_close, once for the
    # complete original envelope. No alternate holiday/calendar fallback.
    try:
        import pandas_market_calendars as mcal
        schedule = mcal.get_calendar('NYSE').schedule(
            start_date=original_start, end_date=original_end - timedelta(days=1))
        closes = {index.date().isoformat(): _clock(close.isoformat())
                  for index, close in schedule['market_close'].items()}
    except Exception:
        raise BindingError('VIEW_CALENDAR_UNAVAILABLE') from None
    require(view['start'] in closes and view['end'] in closes, 'VIEW_EXCHANGE_SESSION')
    require(closes[view['end']] <= observed, 'VIEW_NOT_AVAILABLE')
    return dict(view), closes


def _technical_metadata(documents, identities, grids, view, closes, original, created, decision):
    """Validate supplied typed proof semantics; absent facts never become defaults."""
    metadata = {}
    expected = {session for session in closes if view['start'] <= session <= view['end']}
    require(expected, 'VIEW_EMPTY')
    for ticker, ident in identities.items():
        sessions = {session for name, session in grids['raw'] if name == ticker}
        selected = {session for session in sessions if view['start'] <= session <= view['end']}
        require(selected == expected, 'VIEW_SESSION_GRID')
        record, _, identity_sha = documents[ticker]['identity_evidence']
        status, _, status_sha = documents[ticker]['status_evidence']
        require(record.get('schema') == 'ohlcv-security-identity-evidence-v1',
                'TECHNICAL_IDENTITY_SCHEMA')
        require(status.get('schema') == 'a1-ohlcv-status-volume-evidence-v1',
                'TECHNICAL_STATUS_SCHEMA')
        for key in ('instrument_id', 'ticker', 'market', 'mic', 'timezone', 'calendar', 'currency'):
            require(record.get(key) == ident[key], 'TECHNICAL_IDENTITY_MISMATCH')
        provider_id = record.get('provider_security_id')
        require(type(provider_id) is str and len(provider_id) <= 200
                and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]+', provider_id)
                and provider_id.upper() not in {'UNKNOWN', 'UNVERIFIED', 'NONE', 'NULL', 'N/A'}
                and 'FIXTURE' not in provider_id.upper()
                and provider_id not in (ticker, ident['instrument_id']), 'PROVIDER_SECURITY_ID')
        require(record.get('asset_class') in {'EQUITY', 'ETF'}, 'TECHNICAL_ASSET_CLASS')
        for document in (record, status):
            require(document.get('provider') == capture.SOURCE
                    and document.get('capture_receipt_sha256') == original['capture_receipt_sha256'],
                    'TECHNICAL_ORIGINAL_BINDING')
            require(_clock(document.get('available_from')) <= _clock(document.get('collected_at'))
                    <= created <= decision <= _clock(document.get('expires_at')),
                    'TECHNICAL_EVIDENCE_CLOCK')
        try:
            require(day(record.get('valid_from')) <= day(min(selected))
                    <= day(max(selected)) <= day(record.get('valid_through')),
                    'TECHNICAL_IDENTITY_WINDOW')
            require(day(status.get('valid_from')) <= day(view['start'])
                    <= day(view['end']) <= day(status.get('valid_through')),
                    'TECHNICAL_STATUS_WINDOW')
        except ValueError as exc:
            if isinstance(exc, BindingError):
                raise
            raise BindingError('TECHNICAL_EFFECTIVE_WINDOW') from None
        for key in ('instrument_id', 'provider_security_id', 'ticker'):
            require(status.get(key) == record[key], 'TECHNICAL_STATUS_IDENTITY')
        qualification = documents[ticker].get('provider_close_qualification')
        halts = status.get('halted_sessions')
        if qualification is None:
            require(status.get('halt_coverage') == 'COMPLETE_FOR_WINDOW'
                    and type(halts) is list and len(halts) <= MAX_ROWS
                    and all(type(s) is str for s in halts), 'HALT_COVERAGE_UNKNOWN')
            require(halts == sorted(set(halts)) and all(s in closes
                    and status['valid_from'] <= s <= status['valid_through'] for s in halts),
                    'HALT_COVERAGE_INVALID')
        else:
            require(status.get('halt_coverage') == 'UNKNOWN' and halts is None,
                    'PROVIDER_CLOSE_PHYSICAL_UNKNOWN')
        require(status.get('volume_basis') == {'raw': 'RAW', 'split': 'SPLIT_ADJUSTED'},
                'VOLUME_BASIS_UNKNOWN')
        metadata[ticker] = dict(asset_class=record['asset_class'],
            provider_security_id=provider_id, identity_evidence_sha256=identity_sha,
            status_evidence_sha256=status_sha,
            halted_sessions=([s for s in halts if view['start'] <= s <= view['end']]
                             if qualification is None else None))
        if qualification is not None:
            q, _, qsha = qualification
            known = q['instruments'][ident['instrument_id']]
            metadata[ticker].update(halt_coverage='UNKNOWN',
                provider_close_qualification_sha256=qsha,
                known_halted_sessions=known['known_halted_sessions'],
                known_halt_source_documents=known['known_halt_source_documents'])
    return metadata


def _managed_execution(evidence, meter, terminal, receipt, original, trusted, proof, expected):
    """Verify managed provenance as managed provenance, never legacy receipts."""
    from tools import alpaca_sip_managed_refresh as managed
    control = _decode(proof(evidence.get('managed_control')), 64 * 1024)
    run = _decode(proof(evidence.get('managed_run')), 1024 * 1024)
    approval = _decode(proof(evidence.get('managed_approval')), 64 * 1024)
    deployment = _decode(proof(evidence.get('managed_deployment')), 1024 * 1024)
    master = _decode(proof(evidence.get('managed_master')), 1024 * 1024)
    job = _decode(proof(evidence.get('managed_job')), 1024 * 1024)
    reserved = _decode(proof(evidence.get('managed_reservation')), 1024 * 1024)
    _hash(expected)
    require(type(run) is dict and run.get('id') == trusted.original_run_id
            and type(run.get('id')) is int
            and run.get('run_attempt') == trusted.original_run_attempt == 1
            and run.get('head_sha') == trusted.original_source_sha
            and run.get('head_branch') == 'master'
            and run.get('event') in {'schedule', 'workflow_dispatch'}
            and run.get('status') == 'completed' and run.get('conclusion') == 'success'
            and run.get('path') == '.github/workflows/free_data_daily_update.yml'
            and type(run.get('repository')) is dict
            and run['repository'].get('full_name') == managed.REPO,
            'MANAGED_ORIGINAL_RUN')
    started, ended = _clock(run.get('created_at')), _clock(run.get('updated_at'))
    worker_start = _clock(meter.get('managed_worker_started_at'))
    worker_deadline = _clock(meter.get('managed_worker_deadline'))
    try:
        require(managed.validate_control(control, receipt['seed_sha256'],
                    control.get('policy_sha256'), worker_start) == expected,
                'MANAGED_REVIEWED_CONTROL')
        require(control['credential_binding'] == trusted.credential_binding,
                'MANAGED_CREDENTIAL_BINDING')
        grant_at = managed.owner_grant(control, expected, lambda path: approval, worker_start)
        managed.verify_final_meter(meter, run, evidence['original_checkpoint']['sha256'],
                                   expected, control['per_run_allowance'])
    except ValueError as exc:
        if isinstance(exc, BindingError):
            raise
        raise BindingError('MANAGED_EXECUTION_PROOF') from None
    d = control['deployment']
    require(type(deployment) is dict and deployment.get('number') == d['pull_request']
            and deployment.get('merged') is True
            and deployment.get('base', {}).get('ref') == 'master'
            and deployment.get('merge_commit_sha') == d['merge_sha']
            and type(deployment.get('head')) is dict
            and deployment['head'].get('sha') == d['reviewed_head']
            and _clock(deployment.get('merged_at')) <= grant_at <= worker_start <= ended,
            'MANAGED_PROTECTED_DEPLOYMENT')
    require(type(master) is dict and master.get('name') == 'master'
            and master.get('protected') is True and type(master.get('commit')) is dict,
            'MANAGED_PROTECTED_MASTER')
    master_head = master['commit'].get('sha')
    require(type(master_head) is str and re.fullmatch('[a-f0-9]{40}', master_head),
            'MANAGED_PROTECTED_MASTER')
    if master_head != run['head_sha']:
        successor = _decode(proof(evidence.get('managed_master_ancestry')), 1024 * 1024)
        require(type(successor) is dict and successor.get('status') == 'ahead'
                and successor.get('merge_base_commit', {}).get('sha') == run['head_sha']
                and type(successor.get('commits')) is list and successor['commits']
                and successor['commits'][-1].get('sha') == master_head,
                'MANAGED_MASTER_ANCESTRY')
    require(type(job) is dict and type(job.get('id')) is int and job['id'] > 0
            and job.get('run_id') == run['id'] and job.get('head_sha') == run['head_sha']
            and job.get('name') == managed.JOB and job.get('status') == 'completed'
            and job.get('conclusion') == 'success', 'MANAGED_ORIGINAL_JOB')
    job_start, job_end = _clock(job.get('started_at')), _clock(job.get('completed_at'))
    require(started <= job_start <= job_end <= ended
            and job_start <= worker_start < worker_deadline
            and worker_deadline <= min(_clock(control['expires_at']),
                worker_start + timedelta(seconds=control['max_active_seconds_per_run']))
            and (job_end-job_start).total_seconds() <= managed.JOB_RESERVATION_SECONDS,
            'MANAGED_JOB_WINDOW')
    if run['head_sha'] != d['merge_sha']:
        ancestry = _decode(proof(evidence.get('managed_ancestry')), 1024 * 1024)
        require(type(ancestry) is dict and ancestry.get('status') == 'ahead'
                and type(ancestry.get('merge_base_commit')) is dict
                and ancestry['merge_base_commit'].get('sha') == d['merge_sha']
                and type(ancestry.get('commits')) is list and ancestry['commits']
                and ancestry['commits'][-1].get('sha') == run['head_sha'],
                'MANAGED_DEPLOYMENT_ANCESTRY')
    require(type(terminal) is dict and type(reserved) is dict
            and all(v.get('schema') == 'a1-managed-run-checkpoint-v1'
                    and v.get('run_id') == run['id']
                    and v.get('source_sha') == run['head_sha']
                    and v.get('control_sha256') == expected for v in (terminal, reserved))
            and reserved.get('state') == 'RESERVED' and terminal.get('state') == 'COMPLETE'
            and terminal.get('reason') is None
            and type(terminal.get('slot')) is int
            and terminal['slot'] == reserved.get('slot')
            and 1 <= terminal['slot'] <= control['max_runs']
            and reserved.get('reserved_allowance') == control['per_run_allowance']
            and terminal.get('parent_sha256') == evidence['managed_reservation']['sha256']
            and worker_start <= _clock(reserved.get('created_at'))
            <= _clock(terminal.get('completed_at')) < worker_deadline
            and _clock(terminal['completed_at']) <= job_end
            and _clock(control['not_before']) <= _clock(reserved['created_at'])
            <= _clock(terminal['completed_at']) < _clock(control['expires_at'])
            and (_clock(terminal['completed_at'])-_clock(reserved['created_at'])).total_seconds()
                <= control['max_active_seconds_per_run'],
            'MANAGED_CHECKPOINT_BINDING')
    prior_usage = terminal.get('meter_usage_before_checkpoint_publication')
    require(type(prior_usage) is dict and set(prior_usage) == set(managed.KEYS)
            and all(type(prior_usage[k]) is int and 0 <= prior_usage[k] <= meter['usage'][k]
                    for k in managed.KEYS)
            and prior_usage['provider_gets'] == meter['usage']['provider_gets']
            and prior_usage['drive_requests'] < meter['usage']['drive_requests'],
            'MANAGED_PUBLICATION_METER')
    scopes = set(control['authorized_tickers'])
    subset = managed.execution_scope(control)
    if subset is not None:
        scopes &= subset
    names = set(receipt['collected'])
    require(names and set(receipt['symbols']) <= scopes
            and receipt.get('cohort_scope') == dict(task_key=control['task_key'],
                namespace='managed-refresh-v1', input_sha256=control['inventory_sha256'])
            and type(terminal.get('coverage_updates')) is dict
            and type(terminal.get('held')) is dict
            and all(t not in terminal['held'] and
                    terminal['coverage_updates'].get(t) == terminal.get('session') for t in names)
            and receipt.get('end') == (day(terminal.get('session')) + timedelta(days=1)).isoformat(),
            'MANAGED_CAPTURE_COVERAGE')
    records = terminal.get('receipts')
    require(type(records) is list and 1 <= len(records) <= 1500,
            'MANAGED_RECEIPT_MEMBERSHIP')
    matches = [r for r in records if type(r) is dict and type(r.get('objects')) is list
               and len(r['objects']) == 3
               and r['objects'][2].get('sha256') == original['capture_receipt_sha256']]
    require(len(matches) == 1 and matches[0]['objects'][0] == receipt['raw_object']
            and matches[0]['objects'][1] == receipt['normalized_object'],
            'MANAGED_RECEIPT_MEMBERSHIP')
    selected = matches[0]
    collected_from, collected_to = (_clock(selected.get(k)) for k in
        ('collection_started_at', 'collection_finished_at'))
    assets = receipt.get('asset_precheck')
    require(type(assets) is list and len(assets) == len(receipt['symbols'])
            and all(type(a) is dict and _clock(reserved['created_at'])
                    <= _clock(a.get('collected_at_utc')) <= collected_from for a in assets),
            'MANAGED_ASSET_CLOCKS')
    require(_clock(reserved['created_at']) <= collected_from <= collected_to
            <= _clock(terminal['completed_at']) <= ended
            and _clock(control['not_before']) <= collected_from <= collected_to
                < _clock(control['expires_at'])
            and _clock(evidence.get('first_observed_readback', {}).get('at'))
                >= _clock(terminal['completed_at'])
            and selected.get('public_available_at') is None
            and all(selected.get(k) is False for k in
                ('historical_identity_verified', 'corporate_action_chain_verified',
                 'source_admission', 'pit_verified')),
            'MANAGED_CAPTURE_CLOCKS')
    gate = managed.managed.evaluate_market_session(now_utc=collected_from, min_close_age_minutes=120)
    require(gate['ready'] and gate['session_date'] == terminal['session'], 'MANAGED_CAPTURE_SESSION')
    return dict(kind='MANAGED_MAINTENANCE', managed_control_sha256=expected,
                final_checkpoint_sha256=evidence['original_checkpoint']['sha256'],
                selected_capture_receipt_sha256=original['capture_receipt_sha256'],
                reservation_sha256=evidence['managed_reservation']['sha256'],
                collection_started_at=selected['collection_started_at'],
                collection_finished_at=selected['collection_finished_at'],
                source_public_available_at=None, unselected_price_reads=0)


def _real_evidence(evidence, evidence_bytes, receipt, original, trusted, proof_objects, *,
                   managed_control_sha256=None):
    require(type(trusted) is TrustedSourceBinding, 'TRUSTED_SOURCE_BINDING_REQUIRED')
    require(type(trusted.review_reference) is str and len(trusted.review_reference) <= 200
            and re.fullmatch(
        r'https://github\.com/wscha231/r1000-quant-engine/issues/(448|590)#issuecomment-[0-9]+',
        trusted.review_reference), 'TRUSTED_REVIEW_REFERENCE')
    for pin in (trusted.review_receipt_sha256, trusted.evidence_sha256,
                trusted.credential_binding, trusted.adapter_file_sha256):
        _hash(pin)
    require(digest(evidence_bytes) == trusted.evidence_sha256, 'REVIEWED_EVIDENCE_HASH')
    require(digest(Path(__file__).read_bytes()) == trusted.adapter_file_sha256,
            'REVIEWED_ADAPTER_HASH')
    require(type(trusted.proof_sha256) is tuple and 1 <= len(trusted.proof_sha256) <= MAX_PROOFS
            and all(type(h) is str and HASH.fullmatch(h) for h in trusted.proof_sha256)
            and len(set(trusted.proof_sha256)) == len(trusted.proof_sha256), 'TRUSTED_PROOF_PINS')
    require(type(proof_objects) is tuple and 1 <= len(proof_objects) <= MAX_PROOFS,
            'PROOF_OBJECT_BOUND')
    objects = {}
    total = 0
    for item in proof_objects:
        require(type(item) is tuple and len(item) == 2, 'PROOF_OBJECT_SCHEMA')
        h, raw = item
        _hash(h)
        require(type(raw) is bytes and 0 < len(raw) <= 4 * 1024 * 1024
                and digest(raw) == h and h not in objects, 'PROOF_OBJECT_HASH')
        total += len(raw)
        require(total <= MAX_PROOF_BYTES, 'PROOF_TOTAL_BOUND')
        objects[h] = raw
    require(set(objects) == set(trusted.proof_sha256)
            and trusted.review_receipt_sha256 in objects, 'REVIEWED_PROOF_SET')
    used = {trusted.review_receipt_sha256}
    def proof(ref):
        require(type(ref) is dict and type(ref.get('bytes')) is int
                and type(ref.get('sha256')) is str and ref['sha256'] in objects,
                'MISSING_OR_UNTRUSTED_PROOF')
        h = ref['sha256']
        require(len(objects[h]) == ref['bytes'], 'PROOF_REFERENCE_SIZE')
        used.add(h)
        return objects[h]
    require(evidence.get('schema') == 'a1-reader-real-evidence-v1'
            and evidence.get('fixture_only') is False, 'REAL_EVIDENCE_SCHEMA')
    require(type(trusted.original_run_id) is int and trusted.original_run_id > 0
            and type(trusted.original_run_attempt) is int and trusted.original_run_attempt > 0,
            'ORIGINAL_RUN_BINDING')
    require(type(trusted.original_source_sha) is str
            and re.fullmatch('[a-f0-9]{40}', trusted.original_source_sha)
            and receipt.get('source_sha') == trusted.original_source_sha,
            'ORIGINAL_CODE_BINDING')
    require(evidence.get('original_run_id') == str(trusted.original_run_id)
            and evidence.get('derivation_run_id') == trusted.derivation_run_id
            and type(trusted.derivation_run_id) is str
            and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}', trusted.derivation_run_id)
            and 'FIXTURE' not in trusted.derivation_run_id.upper()
            and type(trusted.derivation_code_sha) is str
            and re.fullmatch('[a-f0-9]{40}', trusted.derivation_code_sha)
            and evidence.get('derivation_code_sha') == trusted.derivation_code_sha,
            'DERIVATION_BINDING')
    meter = _decode(proof(evidence.get('original_execution')), 1024 * 1024)
    checkpoint = _decode(proof(evidence.get('original_checkpoint')), 1024 * 1024)
    if managed_control_sha256 is not None:
        lineage = _managed_execution(evidence, meter, checkpoint, receipt, original,
                                     trusted, proof, managed_control_sha256)
    else:
        require(type(meter) is dict and meter.get('schema') == 'a1-sip-campaign-meter-v1'
                and meter.get('status') == 'COMPLETE' and meter.get('finalized') is True
                and meter.get('preflight_only') is False
                and meter.get('run_id') == trusted.original_run_id
                and type(meter.get('run_id')) is int
                and meter.get('run_attempt') == trusted.original_run_attempt
                and type(meter.get('run_attempt')) is int
                and meter.get('source_sha') == receipt['source_sha']
                and type(meter.get('bindings')) is dict
                and meter['bindings'].get('credential_binding') == trusted.credential_binding
                and meter.get('checkpoint_sha256') == evidence['original_checkpoint']['sha256'],
                'ORIGINAL_EXECUTION_BINDING')
        checkpoint, lineage = _selected_checkpoint(evidence, meter, checkpoint, receipt, proof)
        require(type(checkpoint) is dict and checkpoint.get('schema') == capture.SCHEMA
                and checkpoint.get('state') == 'PRIVATE_RESEARCH_ONLY'
                and checkpoint.get('source') == capture.SOURCE
                and checkpoint.get('last_status') == 'VERIFIED_RAW_SPLIT'
                and all(checkpoint.get(k) == receipt.get(k)
                        for k in ('source_sha', 'seed_sha256', 'start', 'end'))
                and type(checkpoint.get('last_objects')) is list
                and len(checkpoint['last_objects']) == 3
                and checkpoint['last_objects'][0] == receipt['raw_object']
                and checkpoint['last_objects'][1] == receipt['normalized_object']
                and type(checkpoint['last_objects'][2]) is dict
                and checkpoint['last_objects'][2].get('sha256') == original['capture_receipt_sha256'],
                'ORIGINAL_CHECKPOINT_BINDING')
    rights = _decode(proof(evidence.get('owner_rights')), 1024 * 1024)
    require(type(rights) is dict and rights.get('schema') == 'a1-reviewed-account-rights-v1'
            and rights.get('provider') == 'alpaca'
            and rights.get('credential_binding') == trusted.credential_binding
            and rights.get('purpose') == 'PRIVATE_NONCOMMERCIAL_RESEARCH'
            and rights.get('historical_sip_allowed') is True
            and rights.get('private_retention_allowed') is True, 'WAIT_OWNER_EVIDENCE')
    docs = rights.get('source_documents')
    require(type(docs) is list and 1 <= len(docs) <= 8, 'RIGHTS_SOURCE_DOCUMENTS')
    for ref in docs:
        proof(ref)
    require(evidence.get('rights_capture_scope') == dict(
        capture_receipt_sha256=original['capture_receipt_sha256'],
        start=receipt['start'], end_exclusive=receipt['end'],
        credential_binding=trusted.credential_binding, original_run_id=trusted.original_run_id),
        'RIGHTS_CAPTURE_SCOPE')
    for key in ('identity_evidence', 'corporate_actions', 'lifecycle'):
        proof(evidence.get(key))
    require(evidence.get('identity_status') == evidence.get('corporate_action_status')
            == evidence.get('lifecycle_status') == 'VERIFIED', 'WINDOW_PROOF_UNKNOWN')
    event = evidence.get('first_observed_readback')
    require(type(event) is dict, 'FIRST_OBSERVED_BINDING')
    proof(event.get('evidence_ref'))
    technical = _technical_proofs(evidence, receipt, proof)
    require(used == set(objects), 'UNREFERENCED_REVIEWED_PROOF')
    return rights, lineage, technical


def prepare(raw_zip, normalized_gzip, capture_receipt, evidence_bytes, *,
            classification='REAL_SOURCE', decision_time, trusted_source=None, proof_objects=()):
    """Return unadmitted prepared bytes or explicit real-evidence BLOCKED.

    All arguments are already-local bytes. No environment, credentials, provider,
    Drive construction, persistence, registry mutation, or wall-clock inference.
    """
    try:
        return _prepare(raw_zip, normalized_gzip, capture_receipt, evidence_bytes,
                        classification=classification, decision_time=decision_time,
                        trusted_source=trusted_source, proof_objects=proof_objects)
    except BindingError as exc:
        if classification != 'REAL_SOURCE':
            raise
        return Preparation('BLOCKED', (str(exc),))
    except (KeyError, TypeError, AttributeError, OverflowError, RecursionError):
        if classification != 'REAL_SOURCE':
            raise
        return Preparation('BLOCKED', ('REAL_EVIDENCE_SCHEMA',))


def prepare_managed(raw_zip, normalized_gzip, capture_receipt, evidence_bytes, *,
                    decision_time, trusted_source, expected_managed_control_sha256,
                    proof_objects=()):
    """Explicit managed lineage; the legacy prepare() route is unchanged.

    The expected control pin is supplied independently by the reviewed caller,
    not inferred from the capture or manifest. No network or wall-clock reads.
    """
    try:
        _hash(expected_managed_control_sha256)
        return _prepare(raw_zip, normalized_gzip, capture_receipt, evidence_bytes,
            classification='REAL_SOURCE', decision_time=decision_time,
            trusted_source=trusted_source, proof_objects=proof_objects,
            managed_control_sha256=expected_managed_control_sha256)
    except BindingError as exc:
        return Preparation('BLOCKED', (str(exc),))
    except (KeyError, TypeError, AttributeError, OverflowError, RecursionError):
        return Preparation('BLOCKED', ('REAL_EVIDENCE_SCHEMA',))


def _prepare(raw_zip, normalized_gzip, capture_receipt, evidence_bytes, *,
             classification, decision_time, trusted_source, proof_objects,
             managed_control_sha256=None):
    evidence = _decode(evidence_bytes, 1024 * 1024)
    require(type(evidence) is dict, 'EVIDENCE_SCHEMA')
    require(classification in ('REAL_SOURCE', 'CONTRACT_FIXTURE'), 'CLASSIFICATION')
    if classification == 'REAL_SOURCE':
        if trusted_source is None:
            missing = tuple('MISSING_' + k.upper() for k in REAL_GATES if not evidence.get(k))
            return Preparation('BLOCKED', missing + ('TRUSTED_SOURCE_BINDING_REQUIRED',))
    else:
        require(trusted_source is None and proof_objects == (), 'FIXTURE_TRUST_SCOPE')
        require(evidence.get('schema') == 'a1-reader-binding-contract-fixture-v1'
                and evidence.get('fixture_only') is True, 'FIXTURE_MARKER')
    receipt = _decode(capture_receipt, 1024 * 1024)
    require(type(receipt) is dict and receipt.get('schema') == capture.SCHEMA
            and receipt.get('source') == capture.SOURCE
            and receipt.get('scope') == 'PRIVATE_RESEARCH_ONLY'
            and receipt.get('readback_verified') is True
            and receipt.get('source_admission') is False
            and receipt.get('pit_verified') is False
            and receipt.get('historical_identity_verified') is False
            and receipt.get('commercial_use_authorized') is False, 'CAPTURE_RECEIPT_SCOPE')
    for key, raw in (('raw_object', raw_zip), ('normalized_object', normalized_gzip)):
        ref = receipt.get(key)
        require(type(ref) is dict and type(raw) is bytes
                and type(ref.get('bytes')) is int and ref['bytes'] == len(raw)
                and ref.get('sha256') == digest(raw), 'CAPTURE_OBJECT_BINDING')
    try:
        capture.verify_archived_group(raw_zip, normalized_gzip, receipt)
    except (ValueError, OSError, EOFError, zlib.error):
        raise BindingError('ORIGINAL_CAPTURE_VERIFICATION') from None
    original = dict(raw_sha256=digest(raw_zip), normalized_sha256=digest(normalized_gzip),
                    capture_receipt_sha256=digest(capture_receipt))
    real = classification == 'REAL_SOURCE'
    rights, lineage, technical = (_real_evidence(
        evidence, evidence_bytes, receipt, original, trusted_source, proof_objects,
        managed_control_sha256=managed_control_sha256)
        if real else (None, None, {}))
    event = evidence.get('first_observed_readback')
    require(type(event) is dict and event.get('kind') == 'FIRST_OBSERVED_COMPLETE_READBACK'
            and event.get('objects') == original, 'FIRST_OBSERVED_BINDING')
    observed = _clock(event.get('at'))
    created = _clock(evidence.get('created_at'))
    decision = _clock(decision_time)
    fresh_until = _clock(evidence.get('research_fresh_until'))
    require(observed <= created <= decision <= fresh_until, 'DECISION_WINDOW')
    view, closes = _private_view(evidence, receipt, observed, decision, real)
    reader_expires_at = evidence['research_fresh_until']
    if real and rights.get('supplier_expiry') is not None:
        supplier_expiry = _clock(rights['supplier_expiry'])
        require(decision <= supplier_expiry, 'SUPPLIER_RIGHTS_EXPIRED')
        if supplier_expiry < fresh_until:
            reader_expires_at = rights['supplier_expiry']
    require(evidence.get('original_public_available_at') is None
            and evidence.get('original_provider_collected_at') is None,
            'UNKNOWN_ORIGINAL_CLOCKS_ONLY')
    require(real or (type(evidence.get('derivation_run_id')) is str
            and evidence['derivation_run_id'].startswith('CONTRACT_FIXTURE:')
            and len(evidence['derivation_run_id']) <= 160), 'FIXTURE_RUN_ID')
    require(real or (type(evidence.get('original_run_id')) is str
            and evidence['original_run_id'].startswith('CONTRACT_FIXTURE:')
            and len(evidence['original_run_id']) <= 160), 'FIXTURE_RUN_ID')
    for key in ('owner_rights', 'corporate_actions', 'lifecycle'):
        require(real or evidence.get(key) == 'CONTRACT_FIXTURE_ONLY', 'FIXTURE_EVIDENCE_REQUIRED')
    require(type(receipt.get('source_sha')) is str
            and re.fullmatch('[a-f0-9]{40}', receipt['source_sha']), 'ORIGINAL_CODE_PIN')
    require(type(evidence.get('derivation_code_sha')) is str
            and re.fullmatch('[a-f0-9]{40}', evidence['derivation_code_sha']), 'DERIVATION_CODE_PIN')
    _hash(receipt.get('seed_sha256'))
    identities = evidence.get('identity')
    factors = evidence.get('split_factors')
    require(type(identities) is dict and type(factors) is dict
            and set(identities) == set(factors) == set(receipt['collected'])
            and identities, 'IDENTITY_INVENTORY')
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(normalized_gzip)) as stream:
            decoded = stream.read(MAX_DECODED + 1)
    except (OSError, EOFError, ValueError, zlib.error):
        raise BindingError('NORMALIZED_FORMAT') from None
    require(len(decoded) <= MAX_DECODED, 'DECODED_BOUND')
    lines = decoded.splitlines()
    require(0 < len(lines) <= MAX_ROWS, 'ROW_BOUND')
    grids = {basis: {} for basis in ('raw', 'split')}
    expected_keys = {'ticker', 'date', 'adjustment', 'currency', 'open', 'high',
                     'low', 'close', 'volume'}
    for line in lines:
        row = _decode(line, 64 * 1024)
        require(type(row) is dict and set(row) == expected_keys
                and row.get('adjustment') in grids and row.get('ticker') in identities
                and row.get('currency') == 'USD', 'NORMALIZED_SCHEMA')
        key = (row['ticker'], row['date'])
        require(key not in grids[row['adjustment']], 'DUPLICATE_SESSION')
        grids[row['adjustment']][key] = row
    require(grids['raw'] and set(grids['raw']) == set(grids['split']), 'BASIS_GRID')
    for ticker in identities:
        ident = identities[ticker]
        require(type(ident) is dict and set(ident) == {
            'instrument_id', 'ticker', 'market', 'mic', 'timezone', 'calendar',
            'currency', 'valid_from', 'valid_through'}, 'IDENTITY_SCHEMA')
        require(type(ident['instrument_id']) is str
                and (('FIXTURE' not in ident['instrument_id'].upper()
                      and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]+', ident['instrument_id']))
                     if real else ident['instrument_id'].startswith('CONTRACT_FIXTURE:'))
                and len(ident['instrument_id']) <= 200
                and ident['ticker'] == ticker and ident['market'] == 'US'
                and ident['currency'] == 'USD' and ident['mic'] in ('XNYS', 'XNAS', 'ARCX')
                and ident['timezone'] == 'America/New_York'
                and ident['calendar'] == 'NYSE', 'IDENTITY_SCOPE')
        sessions = {date for name, date in grids['raw'] if name == ticker}
        consumed_sessions = ({s for s in sessions if view['start'] <= s <= view['end']}
                             if view else sessions)
        require(type(factors[ticker]) is dict and
                ((consumed_sessions <= set(factors[ticker]) <= sessions) if view
                 else set(factors[ticker]) == sessions),
                'SPLIT_FACTOR_COVERAGE')
    require(len({ident['instrument_id'] for ident in identities.values()}) == len(identities),
            'IDENTITY_COLLISION')
    metadata = (_technical_metadata(technical, identities, grids, view, closes, original,
                                   created, decision) if view else {})
    if managed_control_sha256 is not None:
        require(view is not None and set(metadata) == set(receipt['collected']),
                'MANAGED_TECHNICAL_VIEW_REQUIRED')
        captured_ids = {a['symbol']:capture.asset_record(a['response_utf8'].encode(),a['symbol'])['id']
                        for a in receipt['asset_precheck'] if a['http_status'] == 200}
        require(all(captured_ids.get(t) == metadata[t]['provider_security_id'] for t in metadata),
                'MANAGED_ASSET_IDENTITY')
    qualifications = [documents['provider_close_qualification'] for documents in technical.values()
                      if 'provider_close_qualification' in documents]
    if qualifications:
        require(len(qualifications) == len(technical) and
                len({qsha for _, _, qsha in qualifications}) == 1,
                'PROVIDER_CLOSE_SHARED_SCOPE')
        require(qualifications[0][0]['original_objects'] == original,
                'PROVIDER_CLOSE_SOURCE_BINDING')
    if view:
        for documents in technical.values():
            for document, _, _ in documents.values():
                if _clock(document['expires_at']) < _clock(reader_expires_at):
                    reader_expires_at = document['expires_at']
    typed = {'raw': {}, 'split': {}}
    for key in sorted(grids['raw']):
        ticker, session = key
        ident = identities[ticker]
        consumed = not view or view['start'] <= session <= view['end']
        try:
            date = day(session)
            if consumed:
                require(day(ident['valid_from']) <= date <= day(ident['valid_through']),
                        'LIFECYCLE_WINDOW')
            if view:
                require(session in closes, 'EXCHANGE_SESSION')
                close = closes[session]
            else:
                close = _session_close(date)
            require(close <= observed, 'ROW_NOT_AVAILABLE')
        except ValueError as exc:
            if isinstance(exc, BindingError):
                raise
            raise BindingError('EXCHANGE_SESSION') from None
        if not consumed:
            continue  # Verified original bytes; no excluded technical admission.
        factor, _ = _decimal(factors[ticker][session])
        decimal = {}
        for basis in ('raw', 'split'):
            source = grids[basis][key]
            row = dict(instrument_id=ident['instrument_id'], ticker=ticker,
                       session_date=session, available_from=event['at'])
            decimal[basis] = {}
            for field in ('open', 'high', 'low', 'close', 'volume'):
                number, value = _decimal(source[field], volume=field == 'volume')
                decimal[basis][field], row[field] = number, value
            if not view or view['start'] <= session <= view['end']:
                typed[basis].setdefault(ticker, []).append(row)
        # Fixed precision, independent of a caller's ambient Decimal context.
        # Inputs <=80 chars; products below need at most160 significant digits.
        with localcontext(Context(prec=200, rounding=ROUND_HALF_EVEN,
                                  Emin=-999999, Emax=999999, capitals=1, clamp=0,
                                  flags=[], traps=[InvalidOperation, DivisionByZero, Overflow])):
            if not view or view['start'] <= session <= view['end']:
                require(all(decimal['raw'][k] == decimal['split'][k] * factor
                            for k in ('open', 'high', 'low', 'close'))
                        and decimal['split']['volume'] == decimal['raw']['volume'] * factor,
                        'SPLIT_FACTOR_RELATION')
    pending = []
    for adjustment, basis in (('raw', 'RAW'), ('split', 'SPLIT_ADJUSTED')):
        files, objects = [], []
        for ticker, rows in sorted(typed[adjustment].items()):
            raw = b''.join(encoded(row) for row in rows)
            require(0 < len(raw) <= MAX_VIEW, 'VIEW_BOUND')
            sha = digest(raw)
            ident = {k: v for k, v in identities[ticker].items()
                     if k not in ('valid_from', 'valid_through')}
            ident['adjustment_basis'] = basis
            if view:
                ident.update(metadata[ticker], volume_basis=basis)
            files.append(dict(storage='archive', format='jsonl', sha256=sha,
                              bytes=len(raw), rows=len(rows), start=rows[0]['session_date'],
                              end=rows[-1]['session_date'], columns=PRICE_COLUMNS,
                              instrument=ident))
            objects.append((sha, raw))
        provenance_record = dict(
            schema=('a1-reader-derivation-v1' if real else 'a1-reader-derivation-contract-fixture-v1'),
            fixture_only=not real,
            original_objects=original, original_run_id=evidence['original_run_id'],
            original_checkpoint_lineage=lineage,
            original_source_sha=receipt['source_sha'], original_seed_sha256=receipt['seed_sha256'],
            original_no_data_symbols=receipt['no_bars'],
            derivation_run_id=evidence['derivation_run_id'],
            derivation_code_sha=evidence['derivation_code_sha'],
            code_identity_kind=('EXTERNALLY_REVIEWED_SOURCE_CODE_PINS' if real
                                else 'CONTRACT_FIXTURE_ID_NOT_GIT_COMMIT'),
            adapter_file_sha256=digest(Path(__file__).read_bytes()),
            evidence_sha256=digest(evidence_bytes), first_observed_readback=event,
            original_public_available_at=None, original_provider_collected_at=None,
            original_clocks_status='UNKNOWN', basis=basis,
            derived_objects=[sha for sha, _ in objects],
            research_fresh_until=evidence['research_fresh_until'],
            supplier_rights_expiry=(rights.get('supplier_expiry') if real else None),
            effective_reader_expires_at=reader_expires_at,
            reviewed_evidence=(dict(review_reference=trusted_source.review_reference,
                review_receipt_sha256=trusted_source.review_receipt_sha256,
                proof_sha256=list(trusted_source.proof_sha256)) if real else None),
            source_admission=False, pit_verified=False,
            storage_publication='NOT_RUN', consumer_ack='NOT_RUN', economic_validation='NOT_RUN')
        if view:
            inventory = {}
            for ticker in sorted(identities):
                dates = sorted(session for name, session in grids[adjustment] if name == ticker)
                selected = [s for s in dates if view['start'] <= s <= view['end']]
                selected_set = set(selected)
                excluded = [s for s in dates if s not in selected_set]
                def subset(sessions):
                    return dict(rows=len(sessions), start=sessions[0] if sessions else None,
                        end=sessions[-1] if sessions else None,
                        normalized_rows_sha256=digest(b''.join(
                            encoded(grids[adjustment][ticker, s]) for s in sessions)),
                        sessions_sha256=digest(encoded(sessions)))
                inventory[ticker] = dict(original=subset(dates), selected=subset(selected),
                                         excluded=subset(excluded))
            provenance_record['explicit_private_view'] = dict(
                **view, obv_anchor_session=view['start'], inventory=inventory,
                original_capture_window=dict(start=receipt['start'], end_exclusive=receipt['end']),
                original_symbols=receipt['symbols'], original_collected=receipt['collected'],
                original_normalized_rows=len(lines), selected_rows=sum(v['selected']['rows'] for v in inventory.values()),
                excluded_rows=sum(v['excluded']['rows'] for v in inventory.values()),
                factor_validation_scope='EXPLICIT_SELECTED_GRID_ONLY',
                technical_validation_scope='EXPLICIT_SELECTED_GRID_ONLY',
                excluded_rows_scope='VERIFIED_ORIGINAL_BYTES_NOT_TECHNICALLY_ADMITTED',
                original_archive_verification='COMPLETE_BEFORE_SELECTION',
                technical_evidence=metadata)
        provenance = encoded(provenance_record)
        source = dict(provider=capture.SOURCE,
                      license=('REVIEWED_ACCOUNT_RIGHTS:' + evidence['owner_rights']['sha256']
                               if real else 'CONTRACT_FIXTURE_ONLY'),
                      access_policy=('PRIVATE_NONCOMMERCIAL_RESEARCH' if real else 'CONTRACT_FIXTURE_ONLY'),
                      classification=classification,
                      admission_state='RESEARCH_BYTES_ONLY', eligible_purposes=['research', 'discovery'],
                      pit_status='PIT_PROXY', corporate_action_status='VERIFIED',
                      lifecycle_status='VERIFIED', producer_code_sha=evidence['derivation_code_sha'],
                      producer_config_sha256=digest(evidence_bytes),
                      source_receipt_sha256=digest(provenance),
                      raw_source_sha256=list(original.values()), available_from=event['at'],
                      collected_at=event['at'], expires_at=reader_expires_at)
        pending.append((basis, files, objects, provenance, source))
    common = {}
    if view:
        # A real common origin is the original verified capture receipt, not
        # either distinct basis derivation. Keep both derivations independently
        # addressable and source-bound; no digest is renamed or forced equal.
        common[digest(capture_receipt)] = capture_receipt
        reviewed_objects = dict(proof_objects)
        if qualifications:
            common[trusted_source.review_receipt_sha256] = reviewed_objects[
                trusted_source.review_receipt_sha256]
        for documents in technical.values():
            for role, (document, raw, sha) in documents.items():
                common[sha] = raw
                for ref in _technical_document_refs(role, document):
                    common[ref['sha256']] = reviewed_objects[ref['sha256']]
        for _, _, _, provenance, _ in pending:
            common[digest(provenance)] = provenance
    bases = []
    for basis, files, objects, provenance, source in pending:
        if view:
            source.update(source_receipt_sha256=original['capture_receipt_sha256'],
                source_receipt_role='ORIGINAL_VERIFIED_CAPTURE_RECEIPT',
                basis_derivation_receipt_sha256=digest(provenance),
                derivation_run_id=evidence['derivation_run_id'],
                raw_source_sha256=sorted(set(original.values()) | set(common)))
            objects.extend(sorted(common.items()))
        if qualifications:
            source.update(eligible_purposes=['research'],
                provider_close_qualification_sha256=qualifications[0][2],
                qualification_review_receipt_sha256=trusted_source.review_receipt_sha256,
                qualification_adapter_file_sha256=trusted_source.adapter_file_sha256)
        manifest_value = dict(schema='research-data-generation-v1', eligible_for_selector=False,
                                created_at=evidence['created_at'],
                                source_run_id=(evidence['original_run_id'] if view
                                               else evidence['derivation_run_id']),
                                datasets=[dict(dataset_id='ds.us.prices.daily', schema='price-daily-v1',
                                                source=source, files=files)])
        if qualifications:
            q = qualifications[0][0]
            try:
                _validate_provider_close_qualification(q, manifest_value,
                    manifest_value['datasets'][0], decision, purpose='research',
                    consumer_id=PROVIDER_CLOSE_CONSUMER)
                for ticker, rows in typed['raw' if basis == 'RAW' else 'split'].items():
                    dates = [r['session_date'] for r in rows]
                    require(digest(encoded(dates)) == q['window']['sessions_sha256'] and
                            set(q['instruments'][identities[ticker]['instrument_id']]
                                ['known_halted_sessions']) <= set(dates),
                            'PROVIDER_CLOSE_SESSION_GRID')
            except ContractError as exc:
                raise BindingError(str(exc)) from None
        manifest = encoded(manifest_value)
        require(len(manifest) <= 1024 * 1024, 'MANIFEST_BOUND')
        bases.append(PreparedBasis(basis, manifest, provenance, tuple(objects)))
    return Preparation('REAL_SOURCE_PREPARED_UNADMITTED' if real else 'CONTRACT_FIXTURE_PREPARED',
                       (), tuple(bases))


def compose_prepared(parents, evidence_bytes, *, decision_time, trusted_source, proof_objects):
    """Two immutable price inputs -> one freshly reviewed research derivation.

    This never changes a capture receipt, a parent's qualification/expiry, or
    its rows' original availability. Fresh current review is an explicit input.
    """
    try:
        return _compose_prepared(parents, evidence_bytes, decision_time,
                                 trusted_source, proof_objects)
    except (BindingError, ContractError) as exc:
        return Preparation('BLOCKED', (str(exc),))
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError, RecursionError):
        return Preparation('BLOCKED', ('COMPOSITION_EVIDENCE_SCHEMA',))


def _compose_prepared(parents, evidence_bytes, decision_time, trusted, proof_objects):
    require(type(trusted) is TrustedCompositionBinding, 'COMPOSITION_TRUST_REQUIRED')
    e = _decode(evidence_bytes,64*1024)
    require(type(trusted.review_reference) is str and re.fullmatch(
        r'https://github\.com/wscha231/r1000-quant-engine/issues/(448|590)#issuecomment-[0-9]+',
        trusted.review_reference), 'TRUSTED_REVIEW_REFERENCE')
    require(digest(evidence_bytes) == _hash(trusted.evidence_sha256)
            and digest(Path(__file__).read_bytes()) == _hash(trusted.adapter_file_sha256),
            'COMPOSITION_REVIEW_PIN')
    _hash(trusted.credential_binding); _hash(trusted.review_receipt_sha256)
    require(type(trusted.derivation_code_sha) is str
            and re.fullmatch('[a-f0-9]{40}',trusted.derivation_code_sha)
            and type(trusted.derivation_run_id) is str and len(trusted.derivation_run_id) <= 160
            and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:/-]*',trusted.derivation_run_id)
            and 'FIXTURE' not in trusted.derivation_run_id.upper(), 'COMPOSITION_DERIVATION')
    require(type(trusted.proof_sha256) is tuple and 1 <= len(trusted.proof_sha256) <= 64
            and len(set(trusted.proof_sha256)) == len(trusted.proof_sha256)
            and type(proof_objects) is tuple and len(proof_objects) == len(trusted.proof_sha256),
            'COMPOSITION_PROOF_BOUND')
    proofs, total = {}, 0
    for item in proof_objects:
        require(type(item) is tuple and len(item) == 2, 'COMPOSITION_PROOF_BOUND')
        h, raw = item; _hash(h)
        require(type(raw) is bytes and 0 < len(raw) <= 4*1024*1024 and digest(raw) == h
                and h not in proofs, 'COMPOSITION_PROOF_HASH')
        total += len(raw); require(total <= MAX_PROOF_BYTES, 'COMPOSITION_PROOF_BOUND')
        proofs[h] = raw
    require(set(proofs) == set(trusted.proof_sha256)
            and trusted.review_receipt_sha256 in proofs, 'COMPOSITION_REVIEWED_PROOFS')
    used = {trusted.review_receipt_sha256}
    def proof(ref, limit=4*1024*1024):
        require(type(ref) is dict and type(ref.get('sha256')) is str
                and ref['sha256'] in proofs and type(ref.get('bytes')) is int
                and 0 < ref['bytes'] <= limit and len(proofs[ref['sha256']]) == ref['bytes'],
                'COMPOSITION_PROOF_REFERENCE')
        used.add(ref['sha256']); return proofs[ref['sha256']]
    require(type(e) is dict and e.get('schema') == 'a1-reader-composition-evidence-v1'
            and e.get('fixture_only') is False
            and e.get('derivation_run_id') == trusted.derivation_run_id
            and e.get('derivation_code_sha') == trusted.derivation_code_sha,
            'COMPOSITION_EVIDENCE_SCHEMA')
    decision, created = _clock(decision_time), _clock(e.get('created_at'))
    require(created <= decision <= _clock(e.get('research_fresh_until')), 'COMPOSITION_FRESH_REVIEW')
    revision_ref = e.get('observed_revision_selection')
    revision_bytes = None
    if revision_ref is not None or trusted.observed_revision_sha256 is not None:
        require(type(revision_ref) is dict and revision_ref.get('sha256') ==
                _hash(trusted.observed_revision_sha256), 'REVISION_EXTERNAL_PIN_REQUIRED')
        revision_bytes = proof(revision_ref,64*1024)
    data = _composition_material(parents,trusted,e.get('security_id'),revision_bytes=revision_bytes,
        revision_context=e.get('context_id'),decision=decision,proof=proof)
    iid = e['security_id']; dates = [r['session_date'] for r in data['rows']['RAW']]
    qraw = proof(e.get('qualification'),64*1024); q = _decode(qraw,64*1024); qsha = digest(qraw)
    require(q.get('schema') == PROVIDER_COMPOSITION_SCHEMA and q.get('parents') == data['parents']
            and q.get('context_id') == e.get('context_id')
            and q.get('source_run_id') == trusted.derivation_run_id,
            'COMPOSITION_QUALIFICATION_BINDING')
    require(q.get('observed_revision_selection') == revision_ref, 'REVISION_QUALIFICATION_BINDING')
    refs = _provider_close_references(q)
    if revision_bytes is not None:
        for ref in _observed_volume_references(_decode(revision_bytes,64*1024)):
            require(refs.get(ref['sha256']) == ref['bytes'], 'REVISION_NOT_SOURCE_BOUND')
    require(trusted.review_receipt_sha256 in refs, 'COMPOSITION_CURRENT_REVIEW_UNBOUND')
    for h, size in refs.items():
        proof(dict(sha256=h,bytes=size))
    require(q.get('common_basis') == e.get('common_basis')
            and q.get('owner_rights') == e.get('owner_rights'), 'COMPOSITION_QUALIFICATION_BINDING')
    rights = _decode(proof(e.get('owner_rights')),1024*1024)
    require(rights.get('schema') == 'a1-reviewed-account-rights-v1' and rights.get('provider') == 'alpaca'
            and rights.get('credential_binding') == trusted.credential_binding
            and rights.get('purpose') == 'PRIVATE_NONCOMMERCIAL_RESEARCH'
            and rights.get('historical_sip_allowed') is True
            and rights.get('private_retention_allowed') is True, 'WAIT_OWNER_EVIDENCE')
    rights_docs = rights.get('source_documents')
    require(type(rights_docs) is list and 1 <= len(rights_docs) <= 8, 'RIGHTS_SOURCE_DOCUMENTS')
    for r in rights_docs: proof(r)
    basis = _decode(proof(e.get('common_basis'),64*1024),64*1024)
    pairs = [list(p) for p in trusted.parent_generation_pairs]
    require(basis.get('schema') == 'a1-reviewed-common-split-basis-v1'
            and basis.get('context_id') == e['context_id']
            and basis.get('parent_generation_pairs') == pairs
            and basis.get('instrument_id') == iid
            and basis.get('provider_security_id') == data['identity']['provider_security_id']
            and basis.get('anchor_session') == data['anchor']
            and basis.get('common_split_basis_verified') is True and basis.get('rebase_allowed') is False
            and basis.get('physical_halt_coverage') == 'UNKNOWN'
            and basis.get('historical_revision_certified') is False
            and _decimal(str(basis.get('split_factor')))[0] == Decimal(data['factor']),
            'COMPOSITION_COMMON_BASIS')
    anchor_fields = ('instrument_id','ticker','session_date','open','high','low','close','volume')
    for name, adjustment in (('raw_anchor_sha256','RAW'),('split_anchor_sha256','SPLIT_ADJUSTED')):
        row = next(r for r in data['rows'][adjustment] if r['session_date'] == data['anchor'])
        require(basis.get(name) == digest(encoded({k:row[k] for k in anchor_fields})),
                'COMPOSITION_COMMON_BASIS')
    sources = basis.get('source_documents')
    require(type(sources) is list and 1 <= len(sources) <= 8, 'COMPOSITION_BASIS_SOURCES')
    for r in sources: proof(r)
    identity_raw = proof(e.get('identity_evidence'),64*1024)
    status_raw = proof(e.get('status_evidence'),64*1024)
    identity, status = _decode(identity_raw,64*1024), _decode(status_raw,64*1024)
    require(identity.get('schema') == 'ohlcv-security-identity-evidence-v1'
            and status.get('schema') == 'a1-ohlcv-status-volume-evidence-v1',
            'COMPOSITION_TECHNICAL_SCHEMA')
    expires = _clock(e['research_fresh_until'])
    for document in (basis,identity,status):
        require(document.get('composition_context_id', document.get('context_id')) == e['context_id']
                and document.get('parent_generation_pairs') == pairs
                and _clock(document.get('available_from')) <= _clock(document.get('collected_at'))
                <= created <= decision <= _clock(document.get('expires_at')),
                'COMPOSITION_CURRENT_DOCUMENT_CLOCK')
        expires = min(expires,_clock(document['expires_at']))
    for document in (identity,status):
        require(day(document.get('valid_from')) <= day(dates[0]) <= day(dates[-1])
                <= day(document.get('valid_through')), 'COMPOSITION_CURRENT_IDENTITY_WINDOW')
        require(document.get('provider') == capture.SOURCE
                and all(document.get(k) == data['identity'][k] for k in
                    ('instrument_id','provider_security_id','ticker')), 'COMPOSITION_CURRENT_IDENTITY')
        doc_refs = (document.get('source_documents') if document is identity
                    else document.get('volume_source_documents'))
        require(type(doc_refs) is list and 1 <= len(doc_refs) <= 8, 'COMPOSITION_CURRENT_SOURCES')
        for r in doc_refs: proof(r)
    for key in ('asset_class','market','mic','calendar','timezone','currency'):
        require(identity.get(key) == data['identity'][key], 'COMPOSITION_CURRENT_IDENTITY')
    known = status.get('known_halted_sessions')
    require(status.get('halt_coverage') == 'UNKNOWN' and status.get('halted_sessions') is None
            and status.get('volume_basis') == {'raw':'RAW','split':'SPLIT_ADJUSTED'}
            and type(known) is list and known == sorted(set(known))
            and set(data['known_halted_sessions']) <= set(known), 'COMPOSITION_CURRENT_STATUS')
    halt_refs = status.get('known_halt_source_documents')
    require(type(halt_refs) is list and len(halt_refs) <= 8 and (not known or halt_refs),
            'COMPOSITION_CURRENT_STATUS')
    for r in halt_refs: proof(r)
    supplier_expiries = []
    for expiry in [rights.get('supplier_expiry'),*[p['supplier_expiry'] for p in data['parents']]]:
        if expiry is not None:
            require(decision <= _clock(expiry), 'COMPOSITION_SUPPLIER_EXPIRED')
            supplier_expiries.append(_clock(expiry))
            expires = min(expires,_clock(expiry))
    supplier_expiry = min(supplier_expiries).isoformat() if supplier_expiries else None
    require(used == set(proofs), 'UNREFERENCED_REVIEWED_PROOF')
    require(q['window'] == dict(start=dates[0],end=dates[-1],sessions_sha256=digest(encoded(dates)))
            and _clock(q['created_at']) == created and _clock(q['expires_at']) >= expires,
            'COMPOSITION_WINDOW_OR_CLOCK')
    require(_clock(q['observed_at']) >= max(_clock(p['source_collected_at']) for p in data['parents']),
            'COMPOSITION_BEFORE_INPUT')
    item = q['instruments'].get(iid)
    require(type(item) is dict and item.get('identity_evidence_sha256') == digest(identity_raw)
            and item.get('known_halted_sessions') == known
            and item.get('known_halt_source_documents') == halt_refs,
            'COMPOSITION_CURRENT_STATUS')
    blobs = {}
    for adjustment, rows in data['rows'].items():
        raw = b''.join(encoded(r) for r in rows)
        require(0 < len(raw) <= MAX_VIEW and item['basis_sha256'][adjustment] == digest(raw),
                'COMPOSITION_TYPED_ROWS')
        blobs[adjustment] = raw
    record = dict(schema='a1-reviewed-source-composition-v1',context_id=e['context_id'],
        parents=data['parents'],composition_evidence_sha256=digest(evidence_bytes),
        qualification_sha256=qsha,anchor_session=data['anchor'],parent_row_clocks_preserved=True,
        supplier_rights_expiry=supplier_expiry,source_admission=False,pit_verified=False,
        economics=False,orders=False)
    if revision_ref is not None:
        record['observed_revision_selection'] = revision_ref
    envelope = encoded(record); common = dict(data['objects']); common.update(proofs)
    common[digest(evidence_bytes)] = evidence_bytes;common[digest(envelope)] = envelope
    provenance = {}
    for adjustment in blobs:
        provenance[adjustment] = encoded(dict(record,basis=adjustment,
            derived_objects=[digest(blobs[adjustment])],supplier_rights_expiry=supplier_expiry))
        common[digest(provenance[adjustment])] = provenance[adjustment]
    require(len(common) + 1 <= MAX_REFS
            and sum(len(b) for b in common.values()) + max(len(b) for b in blobs.values()) <= MAX_REFERENCE_BYTES,
            'COMPOSITION_OUTPUT_BOUND')
    output = []
    for adjustment, blob in blobs.items():
        ident = {k:identity[k] for k in ('instrument_id','ticker','asset_class','provider_security_id',
                  'market','mic','calendar','timezone','currency')}
        ident.update(adjustment_basis=adjustment,volume_basis=adjustment,
            identity_evidence_sha256=digest(identity_raw),status_evidence_sha256=digest(status_raw),
            halt_coverage='UNKNOWN',halted_sessions=None,known_halted_sessions=known,
            known_halt_source_documents=halt_refs,provider_close_qualification_sha256=qsha)
        f = dict(storage='archive',format='jsonl',sha256=digest(blob),bytes=len(blob),rows=len(dates),
                 start=dates[0],end=dates[-1],columns=PRICE_COLUMNS,instrument=ident)
        source = dict(provider=capture.SOURCE,license='OWNER_ACCEPTED_PRIVATE_RESEARCH',
            access_policy='PRIVATE_NONCOMMERCIAL_RESEARCH',classification='REAL_SOURCE',
            admission_state='RESEARCH_BYTES_ONLY',eligible_purposes=['research'],pit_status='PIT_PROXY',
            corporate_action_status='VERIFIED',lifecycle_status='VERIFIED',
            producer_code_sha=trusted.derivation_code_sha,producer_config_sha256=digest(evidence_bytes),
            source_receipt_sha256=digest(envelope),source_receipt_role='REVIEWED_SOURCE_COMPOSITION',
            basis_derivation_receipt_sha256=digest(provenance[adjustment]),
            raw_source_sha256=sorted(common),available_from=q['observed_at'],collected_at=q['collected_at'],
            expires_at=expires.isoformat(),derivation_run_id=trusted.derivation_run_id,
            composition_input_generations=pairs,provider_close_qualification_sha256=qsha,
            qualification_review_receipt_sha256=trusted.review_receipt_sha256,
            qualification_adapter_file_sha256=trusted.adapter_file_sha256)
        if revision_ref is not None:
            source['observed_revision_selection_sha256'] = revision_ref['sha256']
        manifest = dict(schema='research-data-generation-v1',eligible_for_selector=False,
            created_at=e['created_at'],source_run_id=trusted.derivation_run_id,
            datasets=[dict(dataset_id='ds.us.prices.daily',schema='price-daily-v1',source=source,files=[f])])
        _validate_provider_close_qualification(q,manifest,manifest['datasets'][0],decision,
            purpose='research',consumer_id=PROVIDER_CLOSE_CONSUMER)
        objects = dict(common);objects[digest(blob)] = blob
        output.append(PreparedBasis(adjustment,encoded(manifest),provenance[adjustment],tuple(sorted(objects.items()))))
    return Preparation('REAL_SOURCE_COMPOSED_UNADMITTED',(),tuple(output))


@dataclass(frozen=True)
class OwnerReference:
    logical_path: str
    file_id: str
    parent_id: str
    sha256: str
    bytes: int


class OwnerReferenceReadTransport:
    """Read exact, bounded references through an already configured owner client.

    Construction never authenticates/constructs OwnerDrive, lists, searches,
    creates directories, falls back to latest, or writes. Runtime read costs and
    account/private-folder authorization remain the calling Source's duty.
    """
    def __init__(self, owner_drive, references):
        require(type(references) is tuple and 0 < len(references) <= MAX_REFS, 'REFERENCE_BOUND')
        refs = {}
        for ref in references:
            require(type(ref) is OwnerReference and type(ref.logical_path) is str,
                    'REFERENCE_SCHEMA')
            match = LOGICAL.fullmatch(ref.logical_path)
            require(match and match[2] == _hash(ref.sha256), 'LOGICAL_REFERENCE')
            require(type(ref.bytes) is int and 0 < ref.bytes <= (
                1024 * 1024 if match[1] == 'generations' else MAX_VIEW), 'REFERENCE_SIZE')
            require(all(type(x) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,200}', x)
                        for x in (ref.file_id, ref.parent_id)), 'OWNER_REFERENCE_ID')
            require(ref.logical_path not in refs, 'DUPLICATE_REFERENCE')
            refs[ref.logical_path] = ref
        require(sum(r.bytes for r in refs.values()) <= MAX_REFERENCE_BYTES, 'REFERENCE_TOTAL')
        self._drive, self._refs = owner_drive, MappingProxyType(refs)

    def read(self, logical_path):
        require(type(logical_path) is str and LOGICAL.fullmatch(logical_path)
                and logical_path in self._refs, 'UNBOUND_LOGICAL_REFERENCE')
        ref = self._refs[logical_path]
        self._drive.check(ref.file_id, ref.parent_id, folder=False)
        raw = self._drive.read(ref.file_id, limit=ref.bytes)
        if type(raw) is not bytes or len(raw) != ref.bytes:
            raise ContractError('OBJECT_SIZE')
        if digest(raw) != ref.sha256:
            raise ContractError('HASH_MISMATCH')
        return raw

    def write(self, *args, **kwargs):
        raise BindingError('READ_ONLY_TRANSPORT')


@dataclass(frozen=True)
class TrustedFinancialSourceBinding:
    """Independent Source-owner acceptance, never constructed from the packet.

    Reconstruction semantics and legal/identity documents are accepted by that
    external review. These pins only authenticate exact bytes and consistency.
    No Alpaca meter, credential binding, trust factory or network lookup exists.
    Execution/publication pins are supplied only after their actual reviewed runs.
    """
    review_reference: str
    review_receipt_sha256: str
    evidence_sha256: str
    proof_sha256: tuple[str, ...]
    issuer_cik: str
    raw_sha256: str
    normalized_sha256: str
    normalized_rows: int
    original_source_sha: str
    original_config_sha256: str
    original_start: str
    original_through: str
    extraction_sha256: str
    reconstruction_receipt_sha256: str
    reuse_run_id: str
    reuse_code_sha: str
    adapter_file_sha256: str
    classification: str
    execution_receipt_sha256: str | None = None
    publication_receipt_sha256: str | None = None
    publication_scope: str = 'LOCAL_ONLY'


@dataclass(frozen=True)
class FinancialPreparation:
    status: str
    blockers: tuple[str, ...]
    context: bytes = b''
    quality: bytes = b''
    objects: tuple[tuple[str, bytes], ...] = ()
    rows: tuple = ()
    manifest: bytes | None = None
    decoded_retained_bytes_charged: int = 0


def _financial_text(value, code):
    require(type(value) is str and 0 < len(value) <= 200 and value.strip() == value, code)
    return value


def _financial_known_text(value, code):
    _financial_text(value, code)
    require(value.upper() not in {'UNKNOWN', 'MISSING', 'N/A'}, code)
    return value


def _financial_inputs(raw, normalized, evidence_bytes, trust, proof_objects, decision_time, *, verify_loaded_adapter=True):
    from tools.long_history_lake import extraction_identity, FORMS
    from tools.research_data_access import (ResearchDataReader, MAX_GENERATION_ROWS,
        MAX_GENERATION_DECOMPRESSED_BYTES, _json_retained_bytes)
    require(type(trust) is TrustedFinancialSourceBinding, 'FINANCIAL_TRUST')
    _financial_known_text(trust.review_reference, 'FINANCIAL_TRUST')
    require(trust.classification in {'REAL_SOURCE', 'CONTRACT_FIXTURE'}, 'FINANCIAL_TRUST')
    require(trust.publication_scope in {'LOCAL_ONLY', 'DURABLE_READBACK'}, 'FINANCIAL_TRUST')
    for h in (trust.review_receipt_sha256, trust.evidence_sha256, trust.raw_sha256,
              trust.normalized_sha256, trust.extraction_sha256, trust.reconstruction_receipt_sha256):
        _hash(h)
    require(trust.extraction_sha256 == extraction_identity(), 'FINANCIAL_ORIGIN')
    require(type(proof_objects) is tuple and 0 < len(proof_objects) <= MAX_PROOFS,
            'FINANCIAL_TRUST')
    proofs = {}
    for pair in proof_objects:
        require(type(pair) is tuple and len(pair) == 2, 'FINANCIAL_TRUST')
        h, body = pair
        require(type(body) is bytes and 0 < len(body) <= 4 * 1024 * 1024 and
                _hash(h) == digest(body) and h not in proofs, 'FINANCIAL_TRUST')
        proofs[h] = body
    require(sum(map(len, proofs.values())) <= MAX_PROOF_BYTES, 'FINANCIAL_RESOURCE_LIMIT')
    require(type(trust.proof_sha256) is tuple and len(set(trust.proof_sha256)) == len(trust.proof_sha256)
            and set(proofs) == set(trust.proof_sha256) and
            {trust.review_receipt_sha256, trust.reconstruction_receipt_sha256} <= set(proofs),
            'FINANCIAL_TRUST')
    require(type(raw) is bytes and type(normalized) is bytes and
            0 < len(raw) <= MAX_VIEW and 0 < len(normalized) <= MAX_VIEW,
            'FINANCIAL_RESOURCE_LIMIT')
    require(digest(raw) == trust.raw_sha256 and digest(normalized) == trust.normalized_sha256,
            'FINANCIAL_ORIGIN')
    require(digest(evidence_bytes) == trust.evidence_sha256, 'FINANCIAL_TRUST')
    e = _decode(evidence_bytes, 1024 * 1024)
    require(e['schema'] == 'a1-financial-reuse-evidence-v1', 'FINANCIAL_TRUST')
    require(e['raw'] == dict(sha256=trust.raw_sha256, bytes=len(raw)) and
            e['normalized'] == dict(sha256=trust.normalized_sha256, bytes=len(normalized)),
            'FINANCIAL_ORIGIN')
    origin, rights, identity = e['origin'], e['rights'], e['issuer']
    require(type(identity) is dict and type(trust.issuer_cik) is str and
            re.fullmatch(r'[0-9]{10}', trust.issuer_cik) and identity['cik'] == trust.issuer_cik,
            'FINANCIAL_IDENTITY')
    for k in ('ticker', 'security_id', 'share_class', 'mic'):
        _financial_known_text(identity[k], 'FINANCIAL_IDENTITY')
    require(identity['lifecycle_status'] == 'VERIFIED', 'FINANCIAL_IDENTITY')
    require(day(identity['valid_from']) <= day(origin['start']) <= day(origin['through']) <=
            day(identity['valid_through']), 'FINANCIAL_IDENTITY')
    require(origin['provider'] == 'SEC_COMPANYFACTS' and origin['dataset_key'] == 'sec/' + trust.issuer_cik
            and origin['source_code_sha'] == trust.original_source_sha and
            re.fullmatch('[a-f0-9]{40}', trust.original_source_sha) and
            origin['extraction_sha256'] == trust.extraction_sha256 and
            origin['matching_execution_receipt_sha256'] is None and
            origin['status'] == 'COLLECTED', 'FINANCIAL_ORIGIN')
    for k in ('commit_sha256', 'catalog_sha256', 'config_sha256'):
        _hash(origin[k])
    require(origin['config_sha256'] == _hash(trust.original_config_sha256) and
            origin['start'] == trust.original_start and origin['through'] == trust.original_through,
            'FINANCIAL_ORIGIN')
    _financial_known_text(origin['run_id'], 'FINANCIAL_ORIGIN')
    decision = _clock(decision_time)
    require(_clock(origin['retrieved_at']) <= _clock(origin['checked_at']) <=
            _clock(e['first_verified_readback_at']) <= decision and
            day(origin['through']) <= _clock(origin['retrieved_at']).date(), 'FINANCIAL_CLOCK')
    # This route has no original publication evidence or historical-use authority.
    require(origin['original_public_available_at'] is None, 'FINANCIAL_HISTORY_PROHIBITED')
    require(rights['provider'] == 'SEC_COMPANYFACTS' and rights['status'] == 'REVIEWED' and
            rights['eligible_purposes'] == ['research'] and rights['access_policy'] == 'PRIVATE_RESEARCH',
            'FINANCIAL_RIGHTS')
    _financial_known_text(rights['license_reference'], 'FINANCIAL_RIGHTS')
    until = _clock(e['research_expires_at'])
    require(_clock(e['research_valid_from']) <= decision <= until, 'FINANCIAL_CLOCK')
    supplier = rights['supplier_expires_at']
    require(rights['supplier_expiry_state'] == ('NOT_STATED' if supplier is None else 'STATED'),
            'FINANCIAL_RIGHTS')
    if supplier is not None:
        require(decision <= _clock(supplier), 'FINANCIAL_RIGHTS')
    for role in ('rights', 'issuer_security', 'source_origin'):
        h = _hash(e['proofs'][role])
        require(h in proofs, 'FINANCIAL_TRUST')
    require(e['proofs']['reconstruction'] == trust.reconstruction_receipt_sha256,
            'FINANCIAL_TRUST')
    # Reuse existing R9 ACK/result and frozen-origin evidence, not a new claim
    # that an unchanged diagnostic hash covers different objects/config/windows.
    ack = _decode(proofs[trust.reconstruction_receipt_sha256], 4 * 1024 * 1024)
    frozen = _decode(proofs[e['proofs']['source_origin']], 4 * 1024 * 1024)
    result = _decode(proofs[_hash(e['proofs']['reconstruction_result'])], 4 * 1024 * 1024)
    actual_inputs = [r for r in ack['reads'] if r['kind'] == 'financial']
    require(ack['schema'] == 'mu-financial-diagnostic-consumer-ack-v1' and
            ack['status'] == 'DONE_DIAGNOSTIC_ONLY_UNADMITTED' and
            ack['matching_producer_execution'] is False and len(actual_inputs) == 2 and
            {(r['sha256'], r['bytes']) for r in actual_inputs} ==
            {(trust.raw_sha256, len(raw)), (trust.normalized_sha256, len(normalized))} and
            result['raw_normalized_exact_equal'] is True and result['normalized_rows'] == trust.normalized_rows and
            result['rejected_rows'] == 0 and any(r['sha256'] == trust.reconstruction_receipt_sha256 and
            r['bytes'] == len(proofs[trust.reconstruction_receipt_sha256]) for r in result['output_refs']),
            'FINANCIAL_ORIGIN')
    ds, header = frozen['dataset'], frozen['original_catalog_header']
    require(frozen['schema'] == 'mu-frozen-g29-selected-dataset-projection-v1' and
            frozen['dataset_key'] == origin['dataset_key'] and
            frozen['commit_sha256'] == origin['commit_sha256'] and
            frozen['catalog_sha256'] == origin['catalog_sha256'] and
            frozen['accepted_g29_producer_execution'] is False and
            header['code_sha'] == trust.original_source_sha and header['config_sha256'] == trust.original_config_sha256 and
            header['run_id'] == origin['run_id'] and ds['cik'] == trust.issuer_cik and ds['status'] == 'COLLECTED' and
            ds['raw_objects'] == [trust.raw_sha256] and ds['normalized'] == trust.normalized_sha256 and
            ds['extraction_sha256'] == trust.extraction_sha256 and ds['rows'] == trust.normalized_rows and
            all(ds[k] == origin[k] for k in ('start', 'through', 'retrieved_at', 'checked_at')) and
            any(r['kind'] == 'metadata' and r['sha256'] == e['proofs']['source_origin'] and
                r['bytes'] == len(proofs[e['proofs']['source_origin']]) for r in ack['reads']), 'FINANCIAL_ORIGIN')
    documents = e['source_documents']
    require(type(documents) is list and bool(documents) and len(documents) <= MAX_PROOFS and
            len(set(documents)) == len(documents) and all(_hash(h) in proofs for h in documents),
            'FINANCIAL_TRUST')
    require(e['reuse_run_id'] == trust.reuse_run_id and e['reuse_code_sha'] == trust.reuse_code_sha and
            re.fullmatch('[a-f0-9]{40}', trust.reuse_code_sha), 'FINANCIAL_ORIGIN')
    _hash(trust.adapter_file_sha256)
    if verify_loaded_adapter:
        require(trust.adapter_file_sha256 == digest(Path(__file__).read_bytes()), 'FINANCIAL_ORIGIN')
    _financial_known_text(trust.reuse_run_id, 'FINANCIAL_ORIGIN')
    _financial_known_text(e['task_key'], 'FINANCIAL_ORIGIN')
    charge = len(raw) + len(normalized) + len(evidence_bytes) + sum(map(len, proofs.values()))
    charge += _json_retained_bytes(e, MAX_GENERATION_DECOMPRESSED_BYTES - charge)
    for metadata in (ack, frozen, result):
        charge += _json_retained_bytes(metadata, MAX_GENERATION_DECOMPRESSED_BYTES - charge)
    rows, retained = ResearchDataReader._rows(normalized, 'gzip_jsonl',
        remaining_bytes=MAX_GENERATION_DECOMPRESSED_BYTES - charge, remaining_rows=MAX_GENERATION_ROWS,
        preserve_cancellation=True)
    charge += retained
    require(type(trust.normalized_rows) is int and 0 < len(rows) == trust.normalized_rows <= MAX_ROWS,
            'FINANCIAL_FACT_SCHEMA')
    seen, previous = set(), None
    for row in rows:
        require(type(row) is dict and set(row) == set(FINANCIAL_COLUMNS) and
                row['cik'] == trust.issuer_cik and row['namespace'] in {'us-gaap', 'ifrs-full', 'dei'} and
                row['form'] in FORMS and row['evidence'] ==
                'SEC_FILED_DATE_CURRENT_ARCHIVE_NOT_CERTIFIED_PIT', 'FINANCIAL_FACT_SCHEMA')
        for k in ('concept', 'unit', 'accession', 'form'):
            _financial_text(row[k], 'FINANCIAL_FACT_SCHEMA')
        require(re.fullmatch(r'[0-9]{10}-[0-9]{2}-[0-9]{6}', row['accession']) and
                type(row['value']) in (int, float) and math.isfinite(row['value']), 'FINANCIAL_FACT_SCHEMA')
        end, filed = day(row['end']), day(row['filed'])
        require(day(origin['start']) <= end <= day(origin['through']) and filed <= day(origin['through']),
                'FINANCIAL_FACT_SCHEMA')
        begin = day(row['start']) if row['start'] is not None else None
        require((begin is None and row['duration_days'] is None) or
                (begin is not None and begin <= end and type(row['duration_days']) is int and
                 row['duration_days'] == (end - begin).days + 1), 'FINANCIAL_FACT_SCHEMA')
        require(row['fy'] is None or type(row['fy']) is int, 'FINANCIAL_FACT_SCHEMA')
        for k in ('fp', 'frame'):
            require(row[k] is None or type(row[k]) is str, 'FINANCIAL_FACT_SCHEMA')
        key = tuple(row[k] for k in ('namespace', 'concept', 'unit', 'start', 'end', 'filed',
                                     'accession', 'form', 'fy', 'fp', 'frame'))
        charge += _json_retained_bytes(list(key), MAX_GENERATION_DECOMPRESSED_BYTES - charge) + 64
        require(charge <= MAX_GENERATION_DECOMPRESSED_BYTES and key not in seen, 'FINANCIAL_FACT_SCHEMA')
        seen.add(key)
        order = (row['end'], row['filed'], row['namespace'], row['concept'], row['unit'],
                 row['accession'], row['start'] or '', str(row['fy']), row['fp'] or '', row['frame'] or '')
        require(previous is None or previous <= order, 'FINANCIAL_FACT_SCHEMA')
        previous = order
    body = encoded(rows)
    require(charge + len(body) <= MAX_GENERATION_DECOMPRESSED_BYTES, 'FINANCIAL_RESOURCE_LIMIT')
    quality = encoded(dict(schema='a1-financial-reuse-quality-v1', status='VERIFIED_ARCHIVAL_BYTES',
        issuer_cik=trust.issuer_cik, raw_sha256=trust.raw_sha256, normalized_sha256=trust.normalized_sha256,
        rows=len(rows), row_set_sha256=digest(body), start=min(r['end'] for r in rows),
        end=max(r['end'] for r in rows), units=sorted({r['unit'] for r in rows}),
        extraction_sha256=trust.extraction_sha256, reconstruction_receipt_sha256=trust.reconstruction_receipt_sha256,
        raw_reextracted=False,
        statement_completeness='NOT_CERTIFIED', quarter_completeness='NOT_CERTIFIED',
        historical_pit=False, eligible_for_selector=False))
    objects = dict(proofs)
    objects.update({trust.raw_sha256: raw, trust.normalized_sha256: normalized,
                    trust.evidence_sha256: evidence_bytes, digest(quality): quality})
    return FinancialPreparation('VERIFIED_INPUTS_AWAITING_ACTUAL_REUSE_RECEIPT', (), evidence_bytes,
        quality, tuple(sorted(objects.items())), tuple(MappingProxyType(r) for r in rows),
        decoded_retained_bytes_charged=charge + len(body))


def prepare_financial_reuse(raw, normalized, evidence_bytes, *, trusted_source=None,
                            proof_objects=(), decision_time):
    """Pure reuse verification; no producer/publication receipt or manifest invented."""
    return _financial_preparation(raw, normalized, evidence_bytes, trusted_source, proof_objects, decision_time)


def _replay_financial_reuse(raw, normalized, evidence_bytes, execution_receipt, *,
                           trusted_source, proof_objects, decision_time):
    # The producer's loaded-byte hash remains evidence, not the current verifier
    # file hash (which can differ across versions/platform line endings).
    if (type(trusted_source) is not TrustedFinancialSourceBinding or type(execution_receipt) is not bytes or
            digest(execution_receipt) != trusted_source.execution_receipt_sha256):
        return FinancialPreparation('BLOCKED', ('FINANCIAL_REUSE_RECEIPT',))
    return _financial_preparation(raw, normalized, evidence_bytes, trusted_source,
                                 proof_objects, decision_time, verify_loaded_adapter=False)


def _financial_preparation(raw, normalized, evidence_bytes, trusted_source, proof_objects,
                           decision_time, *, verify_loaded_adapter=True):
    try:
        return _financial_inputs(raw, normalized, evidence_bytes, trusted_source, proof_objects,
                                 decision_time, verify_loaded_adapter=verify_loaded_adapter)
    except (BindingError, ContractError) as exc:
        return FinancialPreparation('BLOCKED', (str(exc),))
    except (KeyError, TypeError, AttributeError, OverflowError, RecursionError):
        return FinancialPreparation('BLOCKED', ('FINANCIAL_FACT_SCHEMA',))
    except MemoryError:
        return FinancialPreparation('BLOCKED', ('FINANCIAL_RESOURCE_LIMIT',))


def bind_financial_reuse(prepared, execution_receipt, *, trusted_source, created_at, decision_time):
    """Bind an independently accepted *actual* new execution; never write one here."""
    try:
        t = trusted_source
        require(type(t) is TrustedFinancialSourceBinding and type(prepared) is FinancialPreparation and
                prepared.status == 'VERIFIED_INPUTS_AWAITING_ACTUAL_REUSE_RECEIPT' and
                digest(prepared.context) == t.evidence_sha256, 'FINANCIAL_TRUST')
        require(type(t.execution_receipt_sha256) is str and type(execution_receipt) is bytes and
                digest(execution_receipt) == _hash(t.execution_receipt_sha256), 'FINANCIAL_REUSE_RECEIPT')
        p = _decode(execution_receipt, 1024 * 1024)
        e = _decode(prepared.context, 1024 * 1024)
        q = _decode(prepared.quality, 1024 * 1024)
        require(p['schema'] == 'a1-financial-reuse-execution-v1' and p['status'] == 'COMPLETED_REUSE_ONLY' and
                p['task_key'] == e['task_key'] and p['run_id'] == t.reuse_run_id and p['code_sha'] == t.reuse_code_sha and
                p['adapter_file_sha256'] == t.adapter_file_sha256 and p['config_sha256'] == t.evidence_sha256 and
                p['raw_sha256'] == t.raw_sha256 and p['normalized_sha256'] == t.normalized_sha256 and
                p['quality_sha256'] == digest(prepared.quality) and type(p['rows']) is int and
                p['rows'] == t.normalized_rows and
                p['provider_gets'] == 0 and type(p['provider_gets']) is int and
                p['original_matching_execution'] is False and p['historical_pit'] is False,
                'FINANCIAL_REUSE_RECEIPT')
        require(q['schema'] == 'a1-financial-reuse-quality-v1' and q['status'] == 'VERIFIED_ARCHIVAL_BYTES' and
                q['raw_sha256'] == t.raw_sha256 and q['normalized_sha256'] == t.normalized_sha256 and
                q['rows'] == t.normalized_rows and q['extraction_sha256'] == t.extraction_sha256,
                'FINANCIAL_REUSE_QUALITY')
        decision, created, finished = _clock(decision_time), _clock(created_at), _clock(p['finished_at'])
        require(_clock(e['first_verified_readback_at']) <= _clock(p['started_at']) <= finished <= created <=
                decision <= _clock(e['research_expires_at']) and
                _clock(e['research_valid_from']) <= _clock(p['started_at']), 'FINANCIAL_CLOCK')
        supplier = e['rights']['supplier_expires_at']
        require(supplier is None or decision <= _clock(supplier), 'FINANCIAL_RIGHTS')
        source = dict(provider='SEC_COMPANYFACTS', classification=t.classification,
            admission_state='RESEARCH_BYTES_ONLY', eligible_purposes=['research'], pit_status='PIT_PROXY',
            usage='ARCHIVAL_RESEARCH_FORWARD_ONLY', currentness='NOT_CURRENT', historical_pit=False,
            license=e['rights']['license_reference'], access_policy=e['rights']['access_policy'],
            supplier_expires_at=supplier, supplier_expiry_state=e['rights']['supplier_expiry_state'],
            available_from=p['finished_at'], availability_meaning='CURRENT_REUSE_EXECUTION_COMPLETED',
            original_collected_at=e['origin']['retrieved_at'], original_public_available_at=None,
            research_expires_at=e['research_expires_at'],
            expires_at=min((e['research_expires_at'], supplier), key=_clock) if supplier else e['research_expires_at'],
            producer_code_sha=t.reuse_code_sha, producer_config_sha256=t.evidence_sha256,
            source_receipt_sha256=t.execution_receipt_sha256, quality_sha256=digest(prepared.quality),
            evidence_sha256=t.evidence_sha256, review_receipt_sha256=t.review_receipt_sha256,
            reuse_origin=e['origin'])
        objects = dict(prepared.objects)
        objects[t.execution_receipt_sha256] = execution_receipt
        spec = dict(dataset_id=FINANCIAL_DATASET, schema=FINANCIAL_SCHEMA, source=source,
            files=[dict(storage='archive', format='gzip_jsonl', sha256=t.normalized_sha256,
                bytes=len(objects[t.normalized_sha256]), rows=t.normalized_rows, start=q['start'], end=q['end'],
                columns=FINANCIAL_COLUMNS, issuer=e['issuer'])],
            objects=[dict(sha256=h, bytes=len(b)) for h, b in sorted(objects.items())])
        manifest = encoded(dict(schema='research-data-generation-v1', eligible_for_selector=False,
            created_at=created_at, source_run_id=t.reuse_run_id, datasets=[spec]))
        return FinancialPreparation('FINANCIAL_REUSE_PREPARED_UNADMITTED', (), prepared.context,
            prepared.quality, tuple(sorted(objects.items())), prepared.rows, manifest,
            prepared.decoded_retained_bytes_charged)
    except (BindingError, ContractError) as exc:
        return FinancialPreparation('BLOCKED', (str(exc),))
    except (KeyError, TypeError, AttributeError, OverflowError, RecursionError):
        return FinancialPreparation('BLOCKED', ('FINANCIAL_REUSE_RECEIPT',))

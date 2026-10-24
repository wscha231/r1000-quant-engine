"""Offline T2 Source -> Reader contract preparation; no publication or capture.

Real preparation requires an independently supplied trusted Source binding and
the exact already-reviewed proof bytes. No trust anchor is built from input
claims, capture success or VERIFIED strings. Preparation grants no admission.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import (Context, Decimal, DivisionByZero, InvalidOperation, Overflow,
                     ROUND_HALF_EVEN, localcontext)
import gzip
import io
import json
from pathlib import Path
import re
from types import MappingProxyType
import zlib

from tools import alpaca_sip_private_backfill_v1 as capture
from tools.macro_history_sources import digest, encoded
from tools.research_data_access import PRICE_COLUMNS, _session_close, clock, day

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


def _real_evidence(evidence, evidence_bytes, receipt, original, trusted, proof_objects):
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
    require(used == set(objects), 'UNREFERENCED_REVIEWED_PROOF')
    return rights


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


def _prepare(raw_zip, normalized_gzip, capture_receipt, evidence_bytes, *,
             classification, decision_time, trusted_source, proof_objects):
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
    rights = (_real_evidence(evidence, evidence_bytes, receipt, original, trusted_source,
                             proof_objects) if real else None)
    event = evidence.get('first_observed_readback')
    require(type(event) is dict and event.get('kind') == 'FIRST_OBSERVED_COMPLETE_READBACK'
            and event.get('objects') == original, 'FIRST_OBSERVED_BINDING')
    observed = _clock(event.get('at'))
    created = _clock(evidence.get('created_at'))
    decision = _clock(decision_time)
    fresh_until = _clock(evidence.get('research_fresh_until'))
    require(observed <= created <= decision <= fresh_until, 'DECISION_WINDOW')
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
                and ident['currency'] == 'USD' and ident['mic'] in ('XNYS', 'XNAS')
                and ident['timezone'] == 'America/New_York'
                and ident['calendar'] == 'NYSE', 'IDENTITY_SCOPE')
        sessions = {date for name, date in grids['raw'] if name == ticker}
        require(type(factors[ticker]) is dict and set(factors[ticker]) == sessions,
                'SPLIT_FACTOR_COVERAGE')
    require(len({ident['instrument_id'] for ident in identities.values()}) == len(identities),
            'IDENTITY_COLLISION')
    typed = {'raw': {}, 'split': {}}
    for key in sorted(grids['raw']):
        ticker, session = key
        ident = identities[ticker]
        try:
            date = day(session)
            require(day(ident['valid_from']) <= date <= day(ident['valid_through']),
                    'LIFECYCLE_WINDOW')
            require(_session_close(date) <= observed, 'ROW_NOT_AVAILABLE')
        except ValueError as exc:
            if isinstance(exc, BindingError):
                raise
            raise BindingError('EXCHANGE_SESSION') from None
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
            typed[basis].setdefault(ticker, []).append(row)
        # Fixed precision, independent of a caller's ambient Decimal context.
        # Inputs <=80 chars; products below need at most160 significant digits.
        with localcontext(Context(prec=200, rounding=ROUND_HALF_EVEN,
                                  Emin=-999999, Emax=999999, capitals=1, clamp=0,
                                  flags=[], traps=[InvalidOperation, DivisionByZero, Overflow])):
            require(all(decimal['raw'][k] == decimal['split'][k] * factor
                        for k in ('open', 'high', 'low', 'close'))
                    and decimal['split']['volume'] == decimal['raw']['volume'] * factor,
                    'SPLIT_FACTOR_RELATION')
    bases = []
    for adjustment, basis in (('raw', 'RAW'), ('split', 'SPLIT_ADJUSTED')):
        files, objects = [], []
        for ticker, rows in sorted(typed[adjustment].items()):
            raw = b''.join(encoded(row) for row in rows)
            require(0 < len(raw) <= MAX_VIEW, 'VIEW_BOUND')
            sha = digest(raw)
            ident = {k: v for k, v in identities[ticker].items()
                     if k not in ('valid_from', 'valid_through')}
            ident['adjustment_basis'] = basis
            files.append(dict(storage='archive', format='jsonl', sha256=sha,
                              bytes=len(raw), rows=len(rows), start=rows[0]['session_date'],
                              end=rows[-1]['session_date'], columns=PRICE_COLUMNS,
                              instrument=ident))
            objects.append((sha, raw))
        provenance = encoded(dict(
            schema=('a1-reader-derivation-v1' if real else 'a1-reader-derivation-contract-fixture-v1'),
            fixture_only=not real,
            original_objects=original, original_run_id=evidence['original_run_id'],
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
            storage_publication='NOT_RUN', consumer_ack='NOT_RUN', economic_validation='NOT_RUN'))
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
        manifest = encoded(dict(schema='research-data-generation-v1', eligible_for_selector=False,
                                created_at=evidence['created_at'], source_run_id=evidence['derivation_run_id'],
                                datasets=[dict(dataset_id='ds.us.prices.daily', schema='price-daily-v1',
                                               source=source, files=files)]))
        require(len(manifest) <= 1024 * 1024, 'MANIFEST_BOUND')
        bases.append(PreparedBasis(basis, manifest, provenance, tuple(objects)))
    return Preparation('REAL_SOURCE_PREPARED_UNADMITTED' if real else 'CONTRACT_FIXTURE_PREPARED',
                       (), tuple(bases))


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
        require(type(raw) is bytes and len(raw) == ref.bytes and digest(raw) == ref.sha256,
                'OWNER_READBACK_MISMATCH')
        return raw

    def write(self, *args, **kwargs):
        raise BindingError('READ_ONLY_TRANSPORT')

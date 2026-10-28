#!/usr/bin/env python3
"""Explicit frozen research reads. No collectors, latest fallback or admission.

The generation ID is the SHA256 of the exact manifest bytes. The caller supplies
an already configured archive transport; this module never constructs a remote
transport (the legacy RcloneTransport constructor can create directories).
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from contextlib import ExitStack
import gzip
from datetime import date, datetime, time, timezone
import importlib.util
import inspect
import io
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
from types import MappingProxyType

from tools.long_history_lake import Lake, PREFIX, MAX_OBJECT
from tools.macro_history_sources import digest, encoded, exclusive
from tools.macro_research_checkpoint import safe_path
from tools.run_data_freshness_contract import DATA_SOURCES, parse_dt, sha256_file

REGISTRY = Path(__file__).resolve().parents[1] / 'data_static/research_dataset_registry_v1.json'
PREFIX_V1 = 'shared-research-v1'
PROVIDER_CLOSE_SCHEMA = 'a1-provider-daily-close-qualification-v1'
PROVIDER_COMPOSITION_SCHEMA = 'a1-provider-daily-close-composition-v1'
PROVIDER_CLOSE_MEANING = 'PROVIDER_SIP_DAILY_CLOSE_ARCHIVAL_RESEARCH'
PROVIDER_CLOSE_CONSUMER = 'ohlcv-technical-feature-h1'
SCHEMA = 'research-data-generation-v1'
# Per-read ceilings across every file in the pinned generation.
MAX_GENERATION_DECOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_GENERATION_ROWS = 1_000_000
# A fixed primitive price record needs far less than this. Bound each JSON
# decode before allocating its Python objects, including malformed schemas.
MAX_JSONL_LINE_BYTES = 64 * 1024
# Linux RLIMIT_AS bounds even native allocations made before a batch is yielded.
# This is a separate interpreter/decoder ceiling, not the decoded-byte charge.
PARQUET_WORKER_AS_BYTES = 512 * 1024 * 1024
PARQUET_WORKER_SECONDS = 30
_PARQUET_REFUSALS = (
    'PARQUET_ENGINE_UNAVAILABLE', 'PARQUET_RESOURCE_GUARD_UNAVAILABLE',
    'INVALID_PARQUET', 'PARQUET_SCHEMA', 'PARQUET_ROW_BUDGET',
    'BLOCKED_GENERATION_ROWS', 'BLOCKED_GENERATION_DECOMPRESSED_BYTES',
    'PARQUET_ROW_COUNT',
)
PRICE_COLUMNS = {
    'instrument_id': 'string', 'ticker': 'string', 'session_date': 'date',
    'available_from': 'timestamp', 'open': 'positive_number',
    'high': 'positive_number', 'low': 'positive_number',
    'close': 'positive_number', 'volume': 'nonnegative_number',
}


class ContractError(ValueError):
    """Finite public refusal code, without provider responses or credentials."""


def check(condition, code):
    if not condition:
        raise ContractError(code)


def _parquet_retained_row_bytes(row):
    """Conservative Python-retention charge for the *fixed primitive* schema.

    Arrow batch nbytes is charged separately. Count Python dictionaries, every
    key/value object (even when shared), and list/reference slack; do not use
    a JSON payload length as a substitute for retained object memory.
    """
    check(type(row) is dict and set(row) == set(PRICE_COLUMNS), 'ROW_SCHEMA')
    return (sys.getsizeof(row) + 32 + sys.getsizeof(MappingProxyType({})) +
            sum(sys.getsizeof(k) + sys.getsizeof(v) for k, v in row.items()))


def _json_retained_bytes(value, remaining_bytes):
    """Charge every retained JSON object, including malformed nested rows."""
    charge, pending = 32 + sys.getsizeof(MappingProxyType({})), [value]
    while pending:
        current = pending.pop()
        charge += sys.getsizeof(current)
        check(charge <= remaining_bytes, 'BLOCKED_GENERATION_DECOMPRESSED_BYTES')
        if type(current) is dict:
            pending.extend(current.keys())
            pending.extend(current.values())
        elif type(current) is list:
            pending.extend(current)
    return charge


def _session_close(session):
    """Use the existing offline NYSE holiday/half-day schedule, never a fallback."""
    try:
        from r1000_legacy_input_guard import latest_completed_close
        completed, close, _ = latest_completed_close(
            datetime.combine(session, time.max, timezone.utc))
        check(completed == session.isoformat(), 'INVALID_EXCHANGE_SESSION')
        return clock(close.isoformat())
    except ContractError:
        raise
    except Exception:
        raise ContractError('SESSION_CALENDAR_UNAVAILABLE') from None


class _SessionCloseMap:
    """Bounded, lazy NYSE schedule for exactly one read/snapshot invocation.

    The 100,000-day optimization ceiling is the existing Source explicit-view
    envelope. It is not an eligibility limit: unsupported/oversized ranges,
    schedule errors, missing sessions and out-of-envelope rows still use the
    original finite lookup at the original row-validation position.
    """
    _MAX_DAYS = 100_000

    def __init__(self, *, allow_batch=False):
        self._allow_batch = allow_batch
        self._start = self._end = None
        self._closes = None
        self._attempted = False
        self._individual = {}

    def include(self, start, end):
        # Callers supply only already validated retained/request date bounds.
        start = min(self._start, start) if self._start is not None else start
        end = max(self._end, end) if self._end is not None else end
        if (start, end) != (self._start, self._end):
            self._start, self._end = start, end
            self._closes, self._attempted = None, False

    def __getitem__(self, session):
        if not self._allow_batch:
            if session not in self._individual:
                self._individual[session] = _session_close(session)
            return self._individual[session]
        if not self._attempted:
            # Research reuse starts only after the original authority accepts
            # the first actual session, at the original row-validation boundary.
            if session not in self._individual:
                self._individual[session] = _session_close(session)
            self._attempted = True
            if (self._start is not None and self._start <= self._end and
                    (self._end - self._start).days < self._MAX_DAYS):
                try:
                    import pandas_market_calendars as mcal
                    schedule = mcal.get_calendar('NYSE').schedule(
                        start_date=self._start, end_date=self._end)
                    self._closes = {index.date(): clock(close.isoformat())
                                   for index, close in schedule['market_close'].items()}
                    if self._closes.get(session) != self._individual[session]:
                        self._closes = None
                except Exception:
                    # Do not replace the first row's original refusal, or move
                    # a calendar failure ahead of schema/identity/clock checks.
                    self._closes = None
        if session in self._individual:
            return self._individual[session]
        if self._closes is not None and session in self._closes:
            return self._closes[session]
        if session not in self._individual:
            self._individual[session] = _session_close(session)
        return self._individual[session]

    def sessions(self, start, end):
        # Coverage reuses the authoritative date index only when it is complete
        # for this range. A failed/unsupported batch retains the original path.
        if (self._closes is not None and
                self._start <= start <= end <= self._end):
            return sorted(d for d in self._closes if start <= d <= end)
        return None


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _decode_parquet(raw, remaining_bytes, remaining_rows, emit):
    """Worker-only decode; metadata is a precheck, never actual size evidence."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        raise ContractError('PARQUET_ENGINE_UNAVAILABLE') from None
    try:
        pa.set_cpu_count(1)
        pa.set_io_thread_count(1)
        options = dict(pre_buffer=False, thrift_string_size_limit=1024 * 1024,
                       thrift_container_size_limit=10000)
        # PyArrow 15-20 satisfy the repository dependency contract but predate
        # this keyword. The fixed primitive schema remains mandatory on all versions.
        if 'arrow_extensions_enabled' in inspect.signature(pq.ParquetFile).parameters:
            options['arrow_extensions_enabled'] = False
        parquet = pq.ParquetFile(io.BytesIO(raw), **options)
        meta = parquet.metadata
        check(meta is not None and type(meta.num_rows) is int and
              0 < meta.num_rows <= MAX_GENERATION_ROWS, 'PARQUET_ROW_BUDGET')
        check(meta.num_rows <= remaining_rows, 'BLOCKED_GENERATION_ROWS')
        check(type(meta.num_row_groups) is int and
              0 < meta.num_row_groups <= meta.num_rows, 'INVALID_PARQUET')
        declared_bytes = 0
        for i in range(meta.num_row_groups):
            nbytes = meta.row_group(i).total_byte_size
            check(type(nbytes) is int and nbytes >= 0, 'INVALID_PARQUET')
            declared_bytes += nbytes
            check(declared_bytes <= remaining_bytes, 'BLOCKED_GENERATION_DECOMPRESSED_BYTES')
        check(declared_bytes > 0, 'INVALID_PARQUET')
        expected = pa.schema([(key, pa.string() if not kind.endswith('number') else pa.float64())
                              for key, kind in PRICE_COLUMNS.items()])
        check(parquet.schema_arrow.equals(expected, check_metadata=False), 'PARQUET_SCHEMA')
        row_count, charged_bytes = 0, 0
        for batch in parquet.iter_batches(batch_size=64, use_threads=False):
            check(0 < batch.num_rows <= remaining_rows - row_count, 'BLOCKED_GENERATION_ROWS')
            check(type(batch.nbytes) is int and batch.nbytes >= 0, 'INVALID_PARQUET')
            charged_bytes += batch.nbytes
            check(charged_bytes <= remaining_bytes, 'BLOCKED_GENERATION_DECOMPRESSED_BYTES')
            columns = [batch.column(i) for i in range(len(PRICE_COLUMNS))]
            for row_i in range(batch.num_rows):
                row = {name: columns[i][row_i].as_py() for i, name in enumerate(PRICE_COLUMNS)}
                wire = encoded(row)
                # Account for actual Arrow buffers, retained Python rows, and
                # transfer bytes. Shared objects are deliberately overcharged.
                charged_bytes += _parquet_retained_row_bytes(row) + len(wire)
                check(charged_bytes <= remaining_bytes, 'BLOCKED_GENERATION_DECOMPRESSED_BYTES')
                emit(wire)
                row_count += 1
        check(row_count == meta.num_rows, 'PARQUET_ROW_COUNT')
        return max(declared_bytes, charged_bytes), row_count
    except ContractError:
        raise
    except (MemoryError, pa.ArrowMemoryError):
        raise ContractError('BLOCKED_GENERATION_DECOMPRESSED_BYTES') from None
    except Exception:
        raise ContractError('INVALID_PARQUET') from None


def _parquet_worker(remaining_bytes, remaining_rows):
    """Only entered by the resource-limited fresh interpreter below."""
    try:
        raw = sys.stdin.buffer.read(MAX_OBJECT + 1)
        check(0 < len(raw) <= MAX_OBJECT, 'INVALID_PARQUET')
        output = sys.stdout.buffer
        output.write(b'\0' * 16)
        charge, count = _decode_parquet(raw, remaining_bytes, remaining_rows, output.write)
        output.seek(0)
        output.write(struct.pack('!QQ', charge, count))
        output.flush()
    except MemoryError:
        sys.exit(20 + _PARQUET_REFUSALS.index('BLOCKED_GENERATION_DECOMPRESSED_BYTES'))
    except ContractError as exc:
        sys.exit(20 + _PARQUET_REFUSALS.index(str(exc)))


def _isolated_parquet_rows(raw, remaining_bytes, remaining_rows):
    """No native Parquet allocation in the caller, and no unbounded IPC.

    Unsupported enforcement platforms refuse Parquet, never fall back to an
    in-process decoder. CPU/wall/output limits cover malformed/error paths.
    """
    check(importlib.util.find_spec('pyarrow') is not None, 'PARQUET_ENGINE_UNAVAILABLE')
    check(sys.platform == 'linux', 'PARQUET_RESOURCE_GUARD_UNAVAILABLE')
    check(type(raw) is bytes and 0 < len(raw) <= MAX_OBJECT, 'INVALID_PARQUET')
    bootstrap = '''import json, sys
try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (int(sys.argv[4]), int(sys.argv[4])))
    resource.setrlimit(resource.RLIMIT_FSIZE, (int(sys.argv[2]) + 16, int(sys.argv[2]) + 16))
    resource.setrlimit(resource.RLIMIT_CPU, (int(sys.argv[5]), int(sys.argv[5])))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
except Exception:
    sys.exit(21)
sys.path[:] = json.loads(sys.argv[1])
from tools.research_data_access import _parquet_worker
_parquet_worker(int(sys.argv[2]), int(sys.argv[3]))
'''
    command = [sys.executable] + ([] if __debug__ else ['-O']) + ['-B', '-c', bootstrap,
        json.dumps(sys.path), str(remaining_bytes), str(remaining_rows),
        str(PARQUET_WORKER_AS_BYTES), str(PARQUET_WORKER_SECONDS)]
    environment = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1',
                       MKL_NUM_THREADS='1', ARROW_NUM_THREADS='1')
    try:
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(command, input=raw, stdout=output, stderr=subprocess.DEVNULL,
                                    env=environment, timeout=PARQUET_WORKER_SECONDS + 5)
            if 20 <= result.returncode < 20 + len(_PARQUET_REFUSALS):
                raise ContractError(_PARQUET_REFUSALS[result.returncode - 20])
            check(result.returncode == 0, 'BLOCKED_PARQUET_RESOURCE_LIMIT')
            check(os.fstat(output.fileno()).st_size <= remaining_bytes + 16,
                  'BLOCKED_GENERATION_DECOMPRESSED_BYTES')
            output.seek(0)
            header = output.read(16)
            check(len(header) == 16, 'INVALID_PARQUET')
            charge, count = struct.unpack('!QQ', header)
            check(0 < charge <= remaining_bytes, 'BLOCKED_GENERATION_DECOMPRESSED_BYTES')
            check(0 < count <= remaining_rows, 'BLOCKED_GENERATION_ROWS')
            parsed, retained = [], 0
            for line in output:
                check(len(parsed) < count, 'PARQUET_ROW_COUNT')
                row = decode(line)
                retained += _parquet_retained_row_bytes(row) + len(line)
                check(retained <= charge, 'BLOCKED_GENERATION_DECOMPRESSED_BYTES')
                parsed.append(row)
            check(len(parsed) == count, 'PARQUET_ROW_COUNT')
            return parsed, charge
    except ContractError:
        raise
    except MemoryError:
        raise ContractError('BLOCKED_GENERATION_DECOMPRESSED_BYTES') from None
    except (OSError, subprocess.TimeoutExpired):
        raise ContractError('BLOCKED_PARQUET_RESOURCE_LIMIT') from None


def sha(value):
    check(isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value), 'INVALID_SHA256')
    return value


def text(value, code='MISSING_METADATA'):
    check(isinstance(value, str) and value.strip() == value and
          0 < len(value) <= 200 and value.upper() not in {'UNKNOWN', 'MISSING', 'N/A'}, code)
    return value


def clock(value):
    # The existing freshness parser accepts naive dates. This API requires the
    # original aware timestamp and valid offset before using that shared parser,
    # which otherwise normalizes invalid offset minutes. RFC3339 -00:00 denotes
    # an unknown local offset and cannot establish availability.
    check(isinstance(value, str) and re.fullmatch(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?'
        r'(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)', value) and not value.endswith('-00:00'),
        'INVALID_AVAILABILITY')
    try:
        result = parse_dt(value)
    except (OverflowError, ValueError):
        raise ContractError('INVALID_AVAILABILITY') from None
    check(isinstance(result, datetime), 'INVALID_AVAILABILITY')
    return result


def day(value):
    check(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), 'INVALID_DATE')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ContractError('INVALID_DATE') from None


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            check(key not in result, 'DUPLICATE_JSON_KEY')
            result[key] = value
        return result

    def constant(_):
        raise ContractError('NONFINITE_VALUE')

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError('INVALID_JSON') from None


def read_object(transport, path, expected, limit=MAX_OBJECT):
    sha(expected)
    try:
        raw = transport.read(path)
    except ContractError:
        raise
    except (OSError, ValueError):
        raise ContractError('ARCHIVE_UNAVAILABLE') from None
    check(isinstance(raw, bytes) and 0 < len(raw) <= limit, 'OBJECT_SIZE')
    check(digest(raw) == expected, 'HASH_MISMATCH')
    return raw


def _provider_close_references(qualification):
    """Bounded original documents, not a reviewer/authentication mechanism."""
    check(type(qualification) is dict and type(qualification.get('instruments')) is dict,
          'PROVIDER_CLOSE_SCHEMA')
    groups = [qualification.get('source_documents')]
    composed = qualification.get('schema') == PROVIDER_COMPOSITION_SCHEMA
    if composed:
        parents = qualification.get('parents')
        check(type(parents) is list and len(parents) == 2, 'COMPOSITION_PARENTS')
        groups.append([qualification.get('common_basis'), qualification.get('owner_rights')])
        for parent in parents:
            check(type(parent) is dict, 'COMPOSITION_PARENTS')
            groups.append([parent.get('qualification'), parent.get('raw_manifest'),
                           parent.get('split_manifest')])
    for item in qualification['instruments'].values():
        check(type(item) is dict, 'PROVIDER_CLOSE_IDENTITY')
        groups.append(item.get('known_halt_source_documents'))
    refs = {}
    for index, group in enumerate(groups):
        check(type(group) is list and (1 if index == 0 else 0) <= len(group) <= (32 if composed else 8),
              'PROVIDER_CLOSE_SOURCE_DOCUMENTS')
        for ref in group:
            check(type(ref) is dict and set(ref) == {'sha256', 'bytes'},
                  'PROVIDER_CLOSE_SOURCE_DOCUMENTS')
            h = sha(ref['sha256'])
            check(type(ref['bytes']) is int and 0 < ref['bytes'] <= 4 * 1024 * 1024,
                  'PROVIDER_CLOSE_SOURCE_DOCUMENTS')
            check(h not in refs or refs[h] == ref['bytes'], 'PROVIDER_CLOSE_SOURCE_DOCUMENTS')
            refs[h] = ref['bytes']
    check(len(refs) <= (64 if composed else 32) and sum(refs.values()) <= 16 * 1024 * 1024,
          'PROVIDER_CLOSE_PROOF_BOUND')
    return refs


def _validate_provider_close_qualification(q, manifest, spec, decision, *,
                                           purpose, consumer_id, restore_to=None):
    """Validate one distinct research meaning; never certify physical halts.

    Source calls this after its existing external trust/proof checks. Reader
    authenticates bytes, not the reviewer. Main additionally requires the
    independently supplied trusted Source record and expected qualification pin.
    """
    if type(q) is dict and q.get('schema') == PROVIDER_COMPOSITION_SCHEMA:
        return _validate_provider_close_composition(q, manifest, spec, decision,
            purpose=purpose, consumer_id=consumer_id, restore_to=restore_to)
    fields = {'schema', 'meaning', 'purpose', 'admission_state', 'pit_status', 'consumer_id',
              'provider', 'feed', 'timeframe', 'volume_scope', 'source_run_id',
              'original_objects', 'window', 'observed_at', 'available_from', 'collected_at',
              'created_at', 'review_decision_at', 'expires_at', 'original_public_available_at',
              'original_provider_collected_at', 'physical_halt_coverage', 'instruments',
              'source_documents'}
    check(type(q) is dict and set(q) == fields and q['schema'] == PROVIDER_CLOSE_SCHEMA
          and q['meaning'] == PROVIDER_CLOSE_MEANING, 'PROVIDER_CLOSE_SCHEMA')
    source = spec['source']
    check(purpose == q['purpose'] == 'research' and
          consumer_id == q['consumer_id'] == PROVIDER_CLOSE_CONSUMER and restore_to is None,
          'PROVIDER_CLOSE_USE_SCOPE')
    check(q['admission_state'] == source['admission_state'] == 'RESEARCH_BYTES_ONLY' and
          q['pit_status'] == source['pit_status'] == 'PIT_PROXY' and
          source['eligible_purposes'] == ['research'] and
          source['classification'] == 'REAL_SOURCE', 'PROVIDER_CLOSE_USE_SCOPE')
    check(q['provider'] == source['provider'] and q['feed'] == 'SIP' and
          q['timeframe'] == '1Day' and
          q['volume_scope'] == 'PROVIDER_NEW_YORK_DAY_TRADE_CONDITIONS' and
          q['source_run_id'] == manifest['source_run_id'], 'PROVIDER_CLOSE_SOURCE_BINDING')
    original = q['original_objects']
    check(type(original) is dict and set(original) == {
        'raw_sha256', 'normalized_sha256', 'capture_receipt_sha256'},
        'PROVIDER_CLOSE_SOURCE_BINDING')
    check(all(sha(h) in source['raw_source_sha256'] for h in original.values()) and
          original['capture_receipt_sha256'] == source['source_receipt_sha256'],
          'PROVIDER_CLOSE_SOURCE_BINDING')
    check(q['physical_halt_coverage'] == 'UNKNOWN' and
          q['original_public_available_at'] is None and
          q['original_provider_collected_at'] is None, 'PROVIDER_CLOSE_PHYSICAL_UNKNOWN')
    check(clock(q['observed_at']) == clock(source['available_from']) and
          clock(q['observed_at']) <= clock(q['available_from']) <= clock(q['collected_at']) <=
          clock(q['created_at']) == clock(manifest['created_at']) <=
          clock(q['review_decision_at']) <= decision <= clock(q['expires_at']) and
          clock(source['expires_at']) <= clock(q['expires_at']), 'PROVIDER_CLOSE_CLOCK')
    window = q['window']
    check(type(window) is dict and set(window) == {'start', 'end', 'sessions_sha256'} and
          day(window['start']) <= day(window['end']) <= decision.date(),
          'PROVIDER_CLOSE_WINDOW')
    sha(window['sessions_sha256'])
    instruments = q['instruments']
    files = spec['files']
    check(type(instruments) is dict and bool(instruments) and
          set(instruments) == {f['instrument']['instrument_id'] for f in files},
          'PROVIDER_CLOSE_IDENTITY')
    seen = set()
    for f in files:
        identity = f['instrument']
        iid = identity['instrument_id']
        item = instruments[iid]
        check(type(item) is dict and set(item) == {'ticker', 'provider_security_id',
              'identity_evidence_sha256', 'basis_sha256', 'known_halted_sessions',
              'known_halt_source_documents'}, 'PROVIDER_CLOSE_IDENTITY')
        check(all(item[k] == identity.get(k) for k in
                  ('ticker', 'provider_security_id', 'identity_evidence_sha256')),
              'PROVIDER_CLOSE_IDENTITY')
        check(f['start'] == window['start'] and f['end'] == window['end'],
              'PROVIDER_CLOSE_WINDOW')
        hashes = item['basis_sha256']
        check(type(hashes) is dict and set(hashes) == {'RAW', 'SPLIT_ADJUSTED'} and
              all(sha(h) for h in hashes.values()) and
              identity['adjustment_basis'] in hashes and
              hashes[identity['adjustment_basis']] == f['sha256'] and iid not in seen,
              'PROVIDER_CLOSE_BASIS_ROWS')
        seen.add(iid)
        known = item['known_halted_sessions']
        check(type(known) is list and all(type(s) is str for s in known) and
              known == sorted(set(known)) and all(
                  day(window['start']) <= day(s) <= day(window['end']) for s in known),
              'PROVIDER_CLOSE_KNOWN_HALTS')
        check(not known or bool(item['known_halt_source_documents']),
              'PROVIDER_CLOSE_KNOWN_HALTS')
        check(identity.get('halt_coverage') == 'UNKNOWN' and
              identity.get('halted_sessions') is None and
              identity.get('provider_close_qualification_sha256') ==
                  source.get('provider_close_qualification_sha256') and
              identity.get('known_halted_sessions') == known and
              identity.get('known_halt_source_documents') == item['known_halt_source_documents'],
              'PROVIDER_CLOSE_PHYSICAL_UNKNOWN')
    _provider_close_references(q)


def _validate_provider_close_composition(q, manifest, spec, decision, *,
                                         purpose, consumer_id, restore_to=None):
    """A new research derivation; its parents never become a new capture."""
    fields = {'schema','meaning','purpose','admission_state','pit_status','consumer_id',
        'provider','feed','timeframe','volume_scope','source_run_id','window','observed_at',
        'available_from','collected_at','created_at','review_decision_at','expires_at',
        'original_public_available_at','original_provider_collected_at','physical_halt_coverage',
        'instruments','source_documents','parents','context_id','common_basis','owner_rights'}
    check(type(q) is dict and set(q) == fields and q['schema'] == PROVIDER_COMPOSITION_SCHEMA
          and q['meaning'] == PROVIDER_CLOSE_MEANING, 'COMPOSITION_SCHEMA')
    source = spec['source']
    check(purpose == q['purpose'] == 'research' and restore_to is None
          and consumer_id == q['consumer_id'] == PROVIDER_CLOSE_CONSUMER
          and q['admission_state'] == source['admission_state'] == 'RESEARCH_BYTES_ONLY'
          and q['pit_status'] == source['pit_status'] == 'PIT_PROXY'
          and source['classification'] == 'REAL_SOURCE'
          and source['eligible_purposes'] == ['research'], 'COMPOSITION_USE_SCOPE')
    check(q['provider'] == source['provider'] and q['feed'] == 'SIP' and q['timeframe'] == '1Day'
          and q['volume_scope'] == 'PROVIDER_NEW_YORK_DAY_TRADE_CONDITIONS'
          and q['source_run_id'] == manifest['source_run_id'] == source.get('derivation_run_id')
          and source.get('source_receipt_role') == 'REVIEWED_SOURCE_COMPOSITION'
          and sha(source['source_receipt_sha256']) in source['raw_source_sha256'],
          'COMPOSITION_SOURCE_BINDING')
    text(q['context_id'], 'COMPOSITION_CONTEXT')
    check(q['physical_halt_coverage'] == 'UNKNOWN' and q['original_public_available_at'] is None
          and q['original_provider_collected_at'] is None, 'PROVIDER_CLOSE_PHYSICAL_UNKNOWN')
    check(clock(q['observed_at']) == clock(source['available_from'])
          and clock(q['observed_at']) <= clock(q['available_from']) <= clock(q['collected_at'])
          <= clock(q['created_at']) == clock(manifest['created_at'])
          <= clock(q['review_decision_at']) <= decision <= clock(q['expires_at'])
          and clock(source['expires_at']) <= clock(q['expires_at']), 'COMPOSITION_CLOCK')
    parents = q['parents']
    check(type(parents) is list and len(parents) == 2, 'COMPOSITION_PARENTS')
    parent_fields = {'raw_manifest','split_manifest','qualification','source_run_id',
        'review_decision_at','source_available_from','source_collected_at','source_expires_at',
        'supplier_expiry','original_review_receipt_sha256','original_adapter_file_sha256','window'}
    for parent in parents:
        check(type(parent) is dict and set(parent) == parent_fields, 'COMPOSITION_PARENTS')
        for key in ('raw_manifest','split_manifest','qualification'):
            ref = parent[key]
            check(type(ref) is dict and set(ref) == {'sha256','bytes'}
                  and sha(ref['sha256']) in source['raw_source_sha256']
                  and type(ref['bytes']) is int and 0 < ref['bytes'] <= 1024*1024,
                  'COMPOSITION_PARENT_REFERENCE')
        check(parent['raw_manifest']['sha256'] != parent['split_manifest']['sha256'],
              'COMPOSITION_PARENT_REFERENCE')
        sha(parent['original_review_receipt_sha256']); sha(parent['original_adapter_file_sha256'])
        text(parent['source_run_id'], 'COMPOSITION_PARENT_SOURCE')
        check(clock(parent['source_available_from']) <= clock(parent['source_collected_at'])
              <= clock(parent['review_decision_at']) <= clock(parent['source_expires_at'])
              and clock(parent['review_decision_at']) <= clock(q['observed_at']),
              'COMPOSITION_PARENT_CLOCK')
        if parent['supplier_expiry'] is not None:
            check(decision <= clock(parent['supplier_expiry']), 'COMPOSITION_SUPPLIER_EXPIRED')
        window = parent['window']
        check(type(window) is dict and set(window) == {'start','end'}
              and day(window['start']) <= day(window['end']), 'COMPOSITION_PARENT_WINDOW')
    pairs = [[p['raw_manifest']['sha256'],p['split_manifest']['sha256']] for p in parents]
    check(source.get('composition_input_generations') == pairs
          and len({h for pair in pairs for h in pair}) == 4, 'COMPOSITION_INPUT_BINDING')
    window = q['window']
    check(type(window) is dict and set(window) == {'start','end','sessions_sha256'}
          and window['start'] == parents[0]['window']['start']
          and parents[1]['window']['start'] == parents[0]['window']['end']
          and window['end'] == parents[1]['window']['end']
          and day(window['start']) <= day(parents[0]['window']['end']) < day(window['end'])
          <= decision.date(), 'COMPOSITION_WINDOW')
    sha(window['sessions_sha256'])
    instruments = q['instruments']
    check(type(instruments) is dict and len(instruments) == 1 and len(spec['files']) == 1,
          'COMPOSITION_SELECTED_INSTRUMENT')
    f = spec['files'][0]; identity = f['instrument']; iid = identity['instrument_id']
    check(set(instruments) == {iid}, 'COMPOSITION_SELECTED_INSTRUMENT')
    item = instruments[iid]
    check(type(item) is dict and set(item) == {'ticker','provider_security_id',
          'identity_evidence_sha256','basis_sha256','known_halted_sessions','known_halt_source_documents'}
          and all(item[k] == identity.get(k) for k in
                  ('ticker','provider_security_id','identity_evidence_sha256')),
          'COMPOSITION_IDENTITY')
    hashes = item['basis_sha256']
    check(type(hashes) is dict and set(hashes) == {'RAW','SPLIT_ADJUSTED'}
          and all(sha(h) for h in hashes.values())
          and hashes.get(identity['adjustment_basis']) == f['sha256']
          and f['start'] == window['start'] and f['end'] == window['end'], 'COMPOSITION_BASIS_ROWS')
    known = item['known_halted_sessions']
    check(type(known) is list and known == sorted(set(known))
          and all(type(s) is str and day(window['start']) <= day(s) <= day(window['end']) for s in known)
          and (not known or bool(item['known_halt_source_documents'])), 'PROVIDER_CLOSE_KNOWN_HALTS')
    check(identity.get('halt_coverage') == 'UNKNOWN' and identity.get('halted_sessions') is None
          and identity.get('provider_close_qualification_sha256') == source.get('provider_close_qualification_sha256')
          and identity.get('known_halted_sessions') == known
          and identity.get('known_halt_source_documents') == item['known_halt_source_documents'],
          'PROVIDER_CLOSE_PHYSICAL_UNKNOWN')
    _provider_close_references(q)


class _PinnedTransport:
    """Feed the unchanged Lake only the ancestors of an explicit commit."""
    def __init__(self, transport, commit_sha256, execution_receipt_sha256):
        self.transport = transport
        self.execution = sha(execution_receipt_sha256)
        self.commits = []
        current = sha(commit_sha256)
        while current is not None:
            check(current not in self.commits and len(self.commits) < 20000, 'LAKE_CHAIN')
            raw = read_object(transport, f'{PREFIX}/commits/{current}', current)
            commit = decode(raw)
            check(isinstance(commit, dict), 'LAKE_CHAIN')
            self.commits.append(current)
            current = commit.get('parent')
            if current is not None:
                sha(current)

    def read(self, path):
        return self.transport.read(path)

    def names(self, prefix):
        if prefix == f'{PREFIX}/commits':
            return sorted(self.commits)
        if prefix == f'{PREFIX}/executions':
            return [self.execution]
        raise ContractError('LAKE_READ_SCOPE')

    def write(self, *_):
        raise ContractError('READ_ONLY')


def pinned_lake(transport, workspace, *, commit_sha256, catalog_sha256, execution_receipt_sha256):
    """Preserve Lake's chain/pack/report/receipt validators at a named old head."""
    pinned = _PinnedTransport(transport, commit_sha256, execution_receipt_sha256)
    try:
        lake = Lake(pinned, safe_path(workspace))
        check(lake.parent == commit_sha256, 'LAKE_COMMIT_MISMATCH')
        commit = decode(lake.read_hash('commits', lake.parent))
        check(commit['catalog'] == sha(catalog_sha256), 'LAKE_CATALOG_MISMATCH')
        receipt = lake.verified_execution()
        check(receipt['execution_receipt_sha256'] == execution_receipt_sha256, 'LAKE_RECEIPT_MISMATCH')
        lake._reader_execution_receipt = _freeze(receipt)
        return lake
    except (OSError, ValueError, KeyError, TypeError):
        raise ContractError('LAKE_VERIFICATION_FAILED') from None


@dataclass(frozen=True)
class ReadResult:
    rows: tuple
    files: tuple  # (SHA256, exact immutable bytes); never legacy cache bytes.
    receipt: Mapping
    receipt_bytes: bytes  # Canonical JSON for serialization, with immutable public views.


@dataclass(frozen=True)
class ComponentReadResult:
    results: Mapping  # component_id -> immutable ReadResult; no partial required result.
    refusals: Mapping  # explicitly optional component_id -> finite refusal code.
    receipt: Mapping
    receipt_bytes: bytes


class ResearchDataReader:
    def __init__(self, transport, *, registry_path=REGISTRY):
        self.transport = transport
        registry_raw = Path(registry_path).read_bytes()
        self.registry_sha256 = digest(registry_raw)
        self.registry = decode(registry_raw)
        check(isinstance(self.registry, dict) and
              self.registry.get('schema') == 'research-dataset-registry-v1' and
              self.registry.get('eligible_for_selector') is False, 'REGISTRY_SCHEMA')
        check(self.registry.get('datasets') == {'ds.us.prices.daily': {
            'schema': 'price-daily-v1', 'existing_catalog_key': 'price_cache_manifest',
            'existing_producer': 'tools/build_replay_price_cache.py'}}, 'REGISTRY_DATASETS')

    def read(self, dataset_id, data_generation_id, *, decision_time, purpose,
             instrument_ids, required_start, required_end, minimum_rows=1,
             required_sessions=None, consumer_id, restore_to=None):
        """Read and optionally restore verified bytes; never approve economics.

        required_sessions is an explicit caller-supplied calendar window. Without
        it this slice validates bounds and counts, not complete exchange sessions.
        """
        # Lake needs a cache workspace, not a consumer restore destination.
        # Cleanup also covers every refusal path; no persistent restore is implied.
        with ExitStack() as resources:
            return self._read(dataset_id, data_generation_id, decision_time=decision_time,
                purpose=purpose, instrument_ids=instrument_ids, required_start=required_start,
                required_end=required_end, minimum_rows=minimum_rows,
                required_sessions=required_sessions, consumer_id=consumer_id,
                restore_to=restore_to, resources=resources)

    def read_components(self, dataset_id, data_generation_id, *, decision_time,
                        purpose, components, consumer_id):
        """One bounded research read, with one window per distinct instrument.

        No persistent context/cache, restore authority or training/backtest mode.
        Every invocation revalidates the original manifest and global inventory.
        Only explicitly optional local refusals may return alongside results.
        """
        check(type(purpose) is str and purpose == 'research', 'COMPONENT_PURPOSE_RESEARCH_ONLY')
        decision = clock(decision_time)
        check(isinstance(components, (list, tuple)) and 0 < len(components) <= 256,
              'COMPONENT_REQUESTS')
        requests, names, instruments, session_count = [], set(), set(), 0
        fields = {'component_id', 'instrument_id', 'required_start', 'required_end',
                  'minimum_rows', 'required_sessions', 'optional'}
        for item in components:
            check(type(item) is dict and set(item) <= fields, 'COMPONENT_REQUESTS')
            name = text(item.get('component_id'), 'COMPONENT_REQUESTS')
            iid = text(item.get('instrument_id'), 'INVALID_INSTRUMENT_SET')
            check(name not in names and iid not in instruments, 'DUPLICATE_COMPONENT')
            names.add(name); instruments.add(iid)
            start, end = day(item.get('required_start')), day(item.get('required_end'))
            check(start <= end <= decision.date(), 'REQUEST_WINDOW')
            minimum = item.get('minimum_rows', 1)
            check(type(minimum) is int and 1 <= minimum <= MAX_GENERATION_ROWS, 'MINIMUM_ROWS')
            optional = item.get('optional', False)
            check(type(optional) is bool, 'COMPONENT_REQUESTS')
            sessions = item.get('required_sessions')
            if sessions is not None:
                check(isinstance(sessions, (list, tuple)) and bool(sessions), 'CALENDAR_WINDOW')
                session_count += len(sessions)
                check(session_count <= MAX_GENERATION_ROWS, 'BLOCKED_GENERATION_ROWS')
                parsed = [day(s) for s in sessions]
                check(parsed == sorted(set(parsed)) and
                      all(start <= s <= end for s in parsed), 'CALENDAR_WINDOW')
                sessions = list(sessions)  # detach the caller's mutable request.
            requests.append(dict(component_id=name, instrument_id=iid,
                required_start=start.isoformat(), required_end=end.isoformat(),
                minimum_rows=minimum, required_sessions=sessions, optional=optional))
        request_bytes = _json_retained_bytes(requests, MAX_GENERATION_DECOMPRESSED_BYTES)
        with ExitStack() as resources:
            return self._read(dataset_id, data_generation_id, decision_time=decision_time,
                purpose=purpose, instrument_ids=sorted(instruments),
                required_start=min(r['required_start'] for r in requests),
                required_end=max(r['required_end'] for r in requests), minimum_rows=1,
                required_sessions=None, consumer_id=consumer_id, restore_to=None,
                resources=resources, component_requests=requests,
                component_request_bytes=request_bytes)

    def _read(self, dataset_id, data_generation_id, *, decision_time, purpose,
              instrument_ids, required_start, required_end, minimum_rows,
              required_sessions, consumer_id, restore_to, resources,
              component_requests=None, component_request_bytes=0):
        check(type(dataset_id) is str and dataset_id in self.registry['datasets'], 'UNKNOWN_DATASET')
        generation = sha(data_generation_id)
        decision = clock(decision_time)
        check(type(purpose) is str and purpose in {'discovery', 'research', 'training', 'backtest'}, 'INVALID_PURPOSE')
        text(consumer_id, 'INVALID_CONSUMER')
        check(isinstance(instrument_ids, (list, tuple)) and len(instrument_ids) > 0 and
              all(isinstance(x, str) and x for x in instrument_ids) and
              len(set(instrument_ids)) == len(instrument_ids), 'INVALID_INSTRUMENT_SET')
        requested = set(instrument_ids)
        start, end = day(required_start), day(required_end)
        check(start <= end <= decision.date(), 'REQUEST_WINDOW')
        check(type(minimum_rows) is int and minimum_rows >= 1, 'MINIMUM_ROWS')
        sessions = None
        if required_sessions is not None:
            check(isinstance(required_sessions, (list, tuple)) and bool(required_sessions), 'CALENDAR_WINDOW')
            sessions = [day(x) for x in required_sessions]
            check(sessions == sorted(set(sessions)) and
                  all(start <= x <= end for x in sessions), 'CALENDAR_WINDOW')

        manifest_raw = read_object(self.transport,
            f'{PREFIX_V1}/generations/{generation}', generation, 1024 * 1024)
        manifest = decode(manifest_raw)
        check(isinstance(manifest, dict) and manifest.get('schema') == SCHEMA and
              manifest.get('eligible_for_selector') is False, 'GENERATION_SCHEMA')
        check(clock(manifest.get('created_at')) <= decision, 'FUTURE_GENERATION')
        text(manifest.get('source_run_id'))
        datasets = manifest.get('datasets')
        check(isinstance(datasets, list) and 0 < len(datasets) <= 32 and
              all(isinstance(x, dict) and isinstance(x.get('dataset_id'), str) for x in datasets),
              'GENERATION_DATASETS')
        check(len({x['dataset_id'] for x in datasets}) == len(datasets), 'DUPLICATE_DATASET')
        check(all(x['dataset_id'] in self.registry['datasets'] for x in datasets), 'UNKNOWN_DATASET')
        matches = [x for x in datasets if x['dataset_id'] == dataset_id]
        check(len(matches) == 1, 'DATASET_NOT_IN_GENERATION')
        spec = matches[0]
        check(spec.get('schema') == 'price-daily-v1', 'DATASET_SCHEMA')
        source = spec.get('source')
        check(isinstance(source, dict), 'SOURCE_METADATA')
        for key in ('provider', 'license', 'access_policy'):
            text(source.get(key))
        classification = source.get('classification')
        check(type(classification) is str and
              classification in {'REAL_SOURCE', 'CONTRACT_FIXTURE'}, 'SOURCE_CLASSIFICATION')
        check(source.get('admission_state') == 'RESEARCH_BYTES_ONLY', 'ADMISSION_SCOPE')
        purposes = source.get('eligible_purposes')
        check(type(purposes) is list and bool(purposes) and
              all(type(x) is str and x in {'discovery', 'research', 'training', 'backtest'}
                  for x in purposes), 'PURPOSE_NOT_LICENSED')
        # Member types are now known-safe for hashing.
        check(len(purposes) == len(set(purposes)), 'DUPLICATE_PURPOSE')
        check(purpose in purposes, 'PURPOSE_NOT_LICENSED')
        pit_status = source.get('pit_status')
        check(type(pit_status) is str and pit_status in {'VERIFIED', 'PIT_PROXY'}, 'PIT_UNKNOWN')
        if purpose in {'training', 'backtest'}:
            check(source['pit_status'] == 'VERIFIED' and source['classification'] == 'REAL_SOURCE',
                  'PIT_NOT_VERIFIED')
        for key in ('corporate_action_status', 'lifecycle_status'):
            check(source.get(key) == 'VERIFIED', 'IDENTITY_OR_ADJUSTMENT_UNKNOWN')
        check(isinstance(source.get('producer_code_sha'), str) and
              re.fullmatch('[a-f0-9]{40}', source['producer_code_sha']), 'PRODUCER_CODE_SHA')
        for key in ('producer_config_sha256', 'source_receipt_sha256'):
            sha(source.get(key))
        hashes = source.get('raw_source_sha256')
        check(isinstance(hashes, list) and bool(hashes), 'RAW_SOURCE_HASHES')
        for h in hashes:
            sha(h)
        available, collected = clock(source.get('available_from')), clock(source.get('collected_at'))
        check(available <= collected <= decision, 'FUTURE_SOURCE')
        check(collected <= clock(manifest['created_at']), 'GENERATION_SOURCE_CLOCK')
        check(decision <= clock(source.get('expires_at')), 'STALE_GENERATION')

        files = spec.get('files')
        check(isinstance(files, list) and 0 < len(files) <= 256 and
              all(isinstance(x, dict) for x in files), 'FILE_INVENTORY')
        check(all(type(x.get('bytes')) is int and 0 < x['bytes'] <= MAX_OBJECT for x in files)
              and sum(x['bytes'] for x in files) <= 128 * 1024 * 1024, 'FILE_SIZE')
        check(len({sha(x.get('sha256')) for x in files}) == len(files), 'DUPLICATE_FILE')
        check(all(type(x.get('rows')) is int and x['rows'] > 0 for x in files), 'ROW_COUNT')
        check(sum(x['rows'] for x in files) <= MAX_GENERATION_ROWS, 'BLOCKED_GENERATION_ROWS')
        # Inventory metadata is global even for the explicitly scoped API.
        # Never select a subset manifest or silently drop invalid identities.
        identity_map, symbol_map, inventory = {}, {}, []
        for item in files:
            check(item.get('columns') == PRICE_COLUMNS, 'FILE_SCHEMA')
            identity = item.get('instrument')
            check(isinstance(identity, dict), 'INSTRUMENT_IDENTITY')
            for key in ('instrument_id', 'ticker', 'market', 'mic', 'timezone', 'calendar', 'currency'):
                text(identity.get(key), 'INSTRUMENT_IDENTITY')
            check(identity['market'] == 'US' and identity['currency'] == 'USD', 'DATASET_MARKET')
            scheduled = (identity['calendar'] in {'NYSE', 'XNYS'} and
                         identity['timezone'] == 'America/New_York' and
                         identity['mic'] in {'XNYS', 'XNAS'})
            if purpose in {'training', 'backtest'}:
                check(scheduled, 'UNSUPPORTED_SESSION_CALENDAR')
            else:
                # Arca research bars use the same completed-session checks.
                # Keep the existing training/backtest venue support unchanged.
                scheduled = scheduled or (identity['calendar'] in {'NYSE', 'XNYS'} and
                    identity['timezone'] == 'America/New_York' and identity['mic'] == 'ARCX')
            basis = identity.get('adjustment_basis')
            check(type(basis) is str and basis in {'RAW', 'SPLIT_ADJUSTED', 'TOTAL_RETURN'},
                  'ADJUSTMENT_BASIS')
            iid = identity['instrument_id']
            check(iid not in identity_map or identity_map[iid] == identity, 'IDENTITY_DRIFT')
            symbol = (identity['market'], identity['ticker'].upper())
            check(symbol not in symbol_map or symbol_map[symbol] == iid, 'SYMBOL_COLLISION')
            identity_map[iid], symbol_map[symbol] = identity, iid
            file_sha = item['sha256']
            check(type(item.get('format')) is str and
                  item['format'] in {'jsonl', 'gzip_jsonl', 'parquet'}, 'UNSUPPORTED_FORMAT')
            check(item.get('storage') in ('archive', 'lake'), 'UNTRUSTED_STORAGE')
            check(day(item.get('start')) <= day(item.get('end')), 'FILE_PERIOD')
            if item['storage'] == 'lake':
                binding = spec.get('lake_binding')
                check(isinstance(binding, dict), 'LAKE_BINDING')
                for key in ('commit_sha256', 'catalog_sha256', 'execution_receipt_sha256'):
                    sha(binding.get(key))
                text(item.get('lake_key'), 'LAKE_DATASET_BINDING')
            inventory.append((item, identity, scheduled, iid, file_sha))
        qualification = None
        if 'provider_close_qualification_sha256' in source:
            qualification_sha = sha(source['provider_close_qualification_sha256'])
            check(qualification_sha in hashes, 'PROVIDER_CLOSE_NOT_SOURCE_BOUND')
            qualification = decode(read_object(self.transport,
                f'{PREFIX_V1}/objects/{qualification_sha}', qualification_sha, 64 * 1024))
            _validate_provider_close_qualification(qualification, manifest, spec, decision,
                purpose=purpose, consumer_id=consumer_id, restore_to=restore_to)
            for h, size in _provider_close_references(qualification).items():
                check(h in hashes, 'PROVIDER_CLOSE_NOT_SOURCE_BOUND')
                raw_proof = read_object(self.transport, f'{PREFIX_V1}/objects/{h}', h, size)
                check(len(raw_proof) == size, 'PROVIDER_CLOSE_PROOF_SIZE')
        decompressed_total, row_total = component_request_bytes, 0
        lake, session_closes = None, _SessionCloseMap(allow_batch=purpose == 'research')
        request_by_iid = {r['instrument_id']: r for r in component_requests or []}
        for item, _, scheduled, iid, _ in inventory:
            request = request_by_iid.get(iid)
            if scheduled and (component_requests is None or
                    (request is not None and item['end'] >= request['required_start'] and
                     item['start'] <= request['required_end'])):
                session_closes.include(day(item['start']), day(item['end']))
        rows, verified, seen, failures = [], [], set(), {}
        required_iids = {r['instrument_id'] for r in component_requests or [] if not r['optional']}
        local_refusals = {'ARCHIVE_UNAVAILABLE', 'ROW_COUNT', 'INVALID_PRICE_VALUE',
                          'OHLC_INCONSISTENT', 'DUPLICATE_SESSION', 'UNSORTED_SESSIONS', 'FILE_PERIOD'}

        def ensure_lake():
            nonlocal lake
            if lake is not None:
                return
            binding = spec.get('lake_binding')
            check(isinstance(binding, dict), 'LAKE_BINDING')
            if restore_to is not None:
                workspace = Path(restore_to) / generation / 'lake-cache'
            else:
                try:
                    workspace = resources.enter_context(
                        tempfile.TemporaryDirectory(prefix='research-reader-'))
                except OSError:
                    raise ContractError('LAKE_WORKSPACE_UNAVAILABLE') from None
            lake = pinned_lake(self.transport, workspace,
                commit_sha256=binding.get('commit_sha256'), catalog_sha256=binding.get('catalog_sha256'),
                execution_receipt_sha256=binding.get('execution_receipt_sha256'))
            check(lake._reader_execution_receipt['study_recomputed_from_drive'] is True,
                  'LAKE_STUDY_INCOMPLETE')
            try:
                lake.verify_pack_dependencies({p: {s for s, loc in lake.catalog['locations'].items() if loc == p}
                    for p in set(lake.catalog['locations'].values())})
            except (OSError, ValueError, KeyError, TypeError):
                raise ContractError('LAKE_VERIFICATION_FAILED') from None

        if component_requests is not None and any(item['storage'] == 'lake' for item in files):
            # Shared provenance is a call prerequisite, even when every selected
            # object is archive-backed. Keep setup outside optional object handling.
            try:
                ensure_lake()
                for item in files:
                    if item['storage'] == 'lake':
                        entry = lake.catalog['datasets'][item['lake_key']]
                        status = entry['status']
                        check(type(status) is str and status in {'COLLECTED', 'UNCHANGED'} and
                              entry['normalized'] == item['sha256'] and item['format'] == 'gzip_jsonl',
                              'LAKE_DATASET_BINDING')
            except ContractError as exc:
                if str(exc) == 'ARCHIVE_UNAVAILABLE':
                    raise ContractError('LAKE_VERIFICATION_FAILED') from None
                raise
            except (OSError, ValueError, KeyError, TypeError):
                raise ContractError('LAKE_DATASET_BINDING') from None
        for item, identity, scheduled, iid, file_sha in inventory:
            if component_requests is not None:
                request = request_by_iid.get(iid)
                if (request is None or item['end'] < request['required_start']
                        or item['start'] > request['required_end']):
                    continue
            try:
                if item.get('storage') == 'archive':
                    raw = read_object(self.transport, f'{PREFIX_V1}/objects/{file_sha}', file_sha)
                elif item.get('storage') == 'lake':
                    ensure_lake()
                    try:
                        entry = lake.catalog['datasets'][item.get('lake_key')]
                        status = entry['status']
                        check(type(status) is str and status in {'COLLECTED', 'UNCHANGED'} and
                              entry['normalized'] == file_sha and item.get('format') == 'gzip_jsonl',
                              'LAKE_DATASET_BINDING')
                        raw = lake.get_bytes(file_sha)
                    except (OSError, ValueError, KeyError, TypeError):
                        raise ContractError('LAKE_VERIFICATION_FAILED') from None
                else:
                    raise ContractError('UNTRUSTED_STORAGE')
                check(len(raw) == item['bytes'] and digest(raw) == file_sha, 'FILE_BYTES')
                parsed, expanded_bytes = self._rows(
                    raw, item.get('format'),
                    remaining_bytes=MAX_GENERATION_DECOMPRESSED_BYTES - decompressed_total,
                    remaining_rows=MAX_GENERATION_ROWS - row_total)
                decompressed_total += expanded_bytes
                row_total += len(parsed)
                dates = []
                # Validate every decoded row's global schema/identity/clock before
                # any optional local data failure can short-circuit this file.
                for row in parsed:
                    check(isinstance(row, dict) and set(row) == set(PRICE_COLUMNS), 'ROW_SCHEMA')
                    check(row['instrument_id'] == iid and row['ticker'] == identity['ticker'], 'ROW_IDENTITY')
                    session = day(row['session_date'])
                    row_available = clock(row['available_from'])
                    check(session <= row_available.date() and row_available <= available and
                          row_available <= decision, 'FUTURE_AVAILABLE_FROM')
                    if scheduled:
                        check(session_closes[session] <= row_available, 'PRE_CLOSE_AVAILABLE_FROM')
                    dates.append(session)
                check(len(parsed) == item['rows'], 'ROW_COUNT')
                for row, session in zip(parsed, dates):
                    for key, kind in PRICE_COLUMNS.items():
                        if kind.endswith('number'):
                            value = row[key]
                            try:
                                check(type(value) in (int, float) and math.isfinite(value) and
                                      (value > 0 if kind == 'positive_number' else value >= 0), 'INVALID_PRICE_VALUE')
                            except OverflowError:
                                raise ContractError('INVALID_PRICE_VALUE') from None
                    check(row['low'] <= min(row['open'], row['close']) <=
                          max(row['open'], row['close']) <= row['high'], 'OHLC_INCONSISTENT')
                    row_key = (iid, session)
                    check(row_key not in seen, 'DUPLICATE_SESSION')
                    seen.add(row_key)
                check(dates == sorted(dates), 'UNSORTED_SESSIONS')
                check(min(dates) == day(item.get('start')) and max(dates) == day(item.get('end')), 'FILE_PERIOD')
                if qualification is not None:
                    check(digest(encoded([d.isoformat() for d in dates])) ==
                          qualification['window']['sessions_sha256'] and
                          set(qualification['instruments'][iid]['known_halted_sessions']) <=
                          {d.isoformat() for d in dates}, 'PROVIDER_CLOSE_SESSION_GRID')
                rows.extend(parsed)  # publish rows only after the entire partition validates.
                verified.append((file_sha, raw))
            except ContractError as exc:
                if (component_requests is not None and iid not in required_iids
                        and str(exc) in local_refusals
                        and (str(exc) != 'ARCHIVE_UNAVAILABLE' or item['storage'] == 'archive')):
                    # Failed decode/resource/hash/identity/clock checks are not
                    # local refusals. Parsed work remains charged on semantic failure.
                    # The component stays refused, but every later requested
                    # partition must still pass global guards and be charged.
                    failures.setdefault(iid, str(exc))
                    continue
                raise

        if component_requests is not None:
            return self._components_result(dataset_id, generation, manifest, source,
                decision_time, purpose, consumer_id, component_requests, identity_map,
                rows, verified, failures, lake, files, decompressed_total, row_total)

        check(requested <= set(identity_map), 'MISSING_INSTRUMENT')
        selected = [r for r in rows if r['instrument_id'] in requested and
                    required_start <= r['session_date'] <= required_end]
        for iid in sorted(requested):
            dates = sorted(day(r['session_date']) for r in selected if r['instrument_id'] == iid)
            check(len(dates) >= minimum_rows, 'SHORT_HISTORY')
            check(dates[0] == start and dates[-1] == end, 'MISSING_PERIOD')
            if sessions is not None:
                check(dates == sessions, 'MISSING_SESSION')
        selected.sort(key=lambda r: (r['instrument_id'], r['session_date']))
        if restore_to is not None:
            destination = safe_path(Path(restore_to) / generation)
            for file_sha, raw in verified:
                path = destination / 'objects' / file_sha
                exclusive(path, raw)
                check(sha256_file(path, max_bytes=MAX_OBJECT) == file_sha, 'RESTORE_HASH_MISMATCH')
            exclusive(destination / 'manifest.json', manifest_raw)
        return self._result(dataset_id, generation, manifest, source, decision_time,
            purpose, consumer_id, required_start, required_end, minimum_rows,
            required_sessions, requested, selected, verified, lake)

    def _result(self, dataset_id, generation, manifest, source, decision_time, purpose,
                consumer_id, required_start, required_end, minimum_rows, required_sessions,
                requested, selected, verified, lake, *, component_request=None,
                component_identity=None, reader_code_sha256=None):
        receipt = dict(schema='research-data-read-receipt-v1', status='VERIFIED_RESEARCH_BYTES',
            dataset_id=dataset_id, data_generation_id=generation, manifest_sha256=generation,
            source_run_id=manifest['source_run_id'], consumer_id=consumer_id, purpose=purpose,
            decision_time=decision_time, required_start=required_start, required_end=required_end,
            file_sha256=[h for h, _ in verified], rows=len(selected),
            row_set_sha256=digest(encoded(selected)), classification=source['classification'],
            pit_status=source['pit_status'], admission_state=source['admission_state'],
            source_receipt_sha256=source['source_receipt_sha256'],
            producer_code_sha=source['producer_code_sha'], producer_config_sha256=source['producer_config_sha256'],
            requested_session_coverage_verified=required_sessions is not None, calendar_source_verified=False,
            instrument_ids=sorted(requested), minimum_rows=minimum_rows,
            required_sessions_sha256=digest(encoded(required_sessions)) if required_sessions is not None else None,
            raw_source_sha256=list(source['raw_source_sha256']),
            source_available_from=source['available_from'], source_collected_at=source['collected_at'],
            source_expires_at=source['expires_at'], reader_code_sha256=reader_code_sha256 or sha256_file(Path(__file__)),
            registry_sha256=self.registry_sha256, provider_refresh_count=0,
            cache_prices_authority=False, eligible_for_economics=False, eligible_for_selector=False,
            freshness_contract_source=next(x['path'] for x in DATA_SOURCES if x['name'] == 'prices'))
        if lake is not None:
            evidence = lake._reader_execution_receipt
            receipt['lake_evidence'] = {key: evidence[key] for key in
                ('commit_sha256', 'catalog_sha256', 'execution_receipt_sha256',
                 'quality_status', 'study_recomputed_from_drive', 'consumer_rows', 'run_id')}
            receipt['lake_evidence']['reports'] = dict(evidence['reports'])
        if component_request is not None:
            receipt.update(validation_scope='REQUESTED_COMPONENTS_ONLY',
                whole_generation_verified=False, component_id=component_request['component_id'],
                optional=component_request['optional'], instrument_identity=dict(component_identity))
        if 'provider_close_qualification_sha256' in source:
            receipt.update(provider_close_qualification_sha256=source['provider_close_qualification_sha256'],
                qualification_meaning=PROVIDER_CLOSE_MEANING, physical_halt_coverage='UNKNOWN')
        receipt['receipt_sha256'] = digest(encoded(receipt))
        return ReadResult(tuple(MappingProxyType(row) for row in selected),
                          tuple(verified), _freeze(receipt), encoded(receipt))

    def _components_result(self, dataset_id, generation, manifest, source, decision_time,
                           purpose, consumer_id, requests, identities, rows, verified,
                           failures, lake, files, charged_bytes, row_total):
        results, refusals = {}, {}
        reader_sha = sha256_file(Path(__file__))
        rows_by_instrument, hashes_by_instrument = {}, {}
        for row in rows:
            rows_by_instrument.setdefault(row['instrument_id'], []).append(row)
        for item in files:
            hashes_by_instrument.setdefault(item['instrument']['instrument_id'], set()).add(item['sha256'])
        verified_by_hash = dict(verified)
        for request in requests:
            name, iid = request['component_id'], request['instrument_id']
            try:
                check(iid in identities, 'MISSING_INSTRUMENT')
                if iid in failures:
                    raise ContractError(failures[iid])
                selected = [r for r in rows_by_instrument.get(iid, ()) if
                            request['required_start'] <= r['session_date'] <= request['required_end']]
                selected.sort(key=lambda r: r['session_date'])
                dates = [r['session_date'] for r in selected]
                check(len(dates) >= request['minimum_rows'], 'SHORT_HISTORY')
                check(dates[0] == request['required_start'] and dates[-1] == request['required_end'],
                      'MISSING_PERIOD')
                if request['required_sessions'] is not None:
                    check(dates == request['required_sessions'], 'MISSING_SESSION')
            except ContractError as exc:
                if not request['optional']:
                    raise
                refusals[name] = str(exc)
                continue
            component_files = [(h, verified_by_hash[h]) for h in sorted(hashes_by_instrument[iid])
                               if h in verified_by_hash]
            results[name] = self._result(dataset_id, generation, manifest, source,
                decision_time, purpose, consumer_id, request['required_start'], request['required_end'],
                request['minimum_rows'], request['required_sessions'], {iid}, selected,
                component_files, lake, component_request=request,
                component_identity=identities[iid], reader_code_sha256=reader_sha)
        verified_hashes = [h for h, _ in verified]
        declared_hashes = [f['sha256'] for f in files]
        request_receipts = [{k: v for k, v in r.items() if k != 'required_sessions'} |
            {'required_sessions_sha256': digest(encoded(r['required_sessions']))
                if r['required_sessions'] is not None else None} for r in requests]
        receipt = dict(schema='research-data-component-read-receipt-v1',
            status=('NO_VERIFIED_COMPONENTS' if not results else
                    'VERIFIED_REQUESTED_COMPONENTS_WITH_REFUSALS' if refusals else
                    'VERIFIED_REQUESTED_COMPONENTS'),
            validation_scope='REQUESTED_COMPONENTS_ONLY', generation_envelope_verified=True,
            whole_generation_verified=False, dataset_id=dataset_id, data_generation_id=generation,
            manifest_sha256=generation, source_run_id=manifest['source_run_id'],
            decision_time=decision_time, purpose=purpose, consumer_id=consumer_id,
            requests=request_receipts, component_receipts={k: v.receipt['receipt_sha256']
                for k, v in results.items()}, refusals=refusals,
            declared_file_sha256=declared_hashes, verified_file_sha256=verified_hashes,
            unverified_file_sha256=[h for h in declared_hashes if h not in set(verified_hashes)],
            validated_rows=len(rows), decoded_rows_charged=row_total,
            failed_partition_decoded_rows=row_total - len(rows),
            decoded_retained_bytes_charged=charged_bytes,
            source_receipt_sha256=source['source_receipt_sha256'],
            registry_sha256=self.registry_sha256, reader_code_sha256=reader_sha,
            source_available_from=source['available_from'], source_collected_at=source['collected_at'],
            source_expires_at=source['expires_at'], provider_refresh_count=0,
            calendar_source_verified=False, cache_prices_authority=False,
            eligible_for_economics=False, eligible_for_selector=False)
        if 'provider_close_qualification_sha256' in source:
            receipt.update(provider_close_qualification_sha256=source['provider_close_qualification_sha256'],
                qualification_meaning=PROVIDER_CLOSE_MEANING, physical_halt_coverage='UNKNOWN')
        receipt['receipt_sha256'] = digest(encoded(receipt))
        return ComponentReadResult(MappingProxyType(results), _freeze(refusals),
                                   _freeze(receipt), encoded(receipt))

    @staticmethod
    def _rows(raw, format_name, *, remaining_bytes, remaining_rows):
        check(remaining_bytes > 0, 'BLOCKED_GENERATION_DECOMPRESSED_BYTES')
        check(remaining_rows > 0, 'BLOCKED_GENERATION_ROWS')
        check(type(format_name) is str and
              format_name in {'jsonl', 'gzip_jsonl', 'parquet'}, 'UNSUPPORTED_FORMAT')
        if format_name in {'jsonl', 'gzip_jsonl'}:
            if format_name == 'gzip_jsonl':
                try:
                    # Refuse on the first byte above the remaining generation
                    # limit; preserve the old 128 MiB per-object decode ceiling.
                    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                        raw = stream.read(min(128 * 1024 * 1024, remaining_bytes) + 1)
                except MemoryError:
                    raise ContractError('BLOCKED_GENERATION_DECOMPRESSED_BYTES') from None
                except (OSError, EOFError, ValueError):
                    raise ContractError('INVALID_GZIP') from None
            check(len(raw) <= 128 * 1024 * 1024, 'DECODE_SIZE')
            check(len(raw) <= remaining_bytes, 'BLOCKED_GENERATION_DECOMPRESSED_BYTES')
            parsed, charged_bytes = [], len(raw)
            try:
                stream = io.BytesIO(raw)
                while line := stream.readline(MAX_JSONL_LINE_BYTES + 1):
                    check(len(parsed) < remaining_rows, 'BLOCKED_GENERATION_ROWS')
                    check(len(line) <= MAX_JSONL_LINE_BYTES,
                          'BLOCKED_GENERATION_DECOMPRESSED_BYTES')
                    row = decode(line)
                    charged_bytes += _json_retained_bytes(row, remaining_bytes - charged_bytes)
                    parsed.append(row)
                return parsed, charged_bytes
            except MemoryError:
                raise ContractError('BLOCKED_GENERATION_DECOMPRESSED_BYTES') from None
        if format_name == 'parquet':
            return _isolated_parquet_rows(raw, remaining_bytes, remaining_rows)
        raise ContractError('UNSUPPORTED_FORMAT')

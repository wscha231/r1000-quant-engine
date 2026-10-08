#!/usr/bin/env python3
"""Explicit frozen research reads. No collectors, latest fallback or admission.

The generation ID is the SHA256 of the exact manifest bytes. The caller supplies
an already configured archive transport; this module never constructs a remote
transport (the legacy RcloneTransport constructor can create directories).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import io
import json
import math
from pathlib import Path
import re

from tools.long_history_lake import Lake, PREFIX, MAX_OBJECT, unpacked
from tools.macro_history_sources import digest, encoded, exclusive
from tools.macro_research_checkpoint import safe_path
from tools.run_data_freshness_contract import DATA_SOURCES, parse_dt, sha256_file

REGISTRY = Path(__file__).resolve().parents[1] / 'data_static/research_dataset_registry_v1.json'
PREFIX_V1 = 'shared-research-v1'
SCHEMA = 'research-data-generation-v1'
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
    except (OSError, ValueError):
        raise ContractError('ARCHIVE_UNAVAILABLE') from None
    check(isinstance(raw, bytes) and 0 < len(raw) <= limit, 'OBJECT_SIZE')
    check(digest(raw) == expected, 'HASH_MISMATCH')
    return raw


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
        return lake
    except (OSError, ValueError, KeyError, TypeError):
        raise ContractError('LAKE_VERIFICATION_FAILED') from None


@dataclass(frozen=True)
class ReadResult:
    rows: tuple
    files: tuple  # (SHA256, exact immutable bytes); never legacy cache bytes.
    receipt: dict


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
        check(dataset_id in self.registry['datasets'], 'UNKNOWN_DATASET')
        generation = sha(data_generation_id)
        decision = clock(decision_time)
        check(purpose in {'discovery', 'research', 'training', 'backtest'}, 'INVALID_PURPOSE')
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
        check(source.get('classification') in {'REAL_SOURCE', 'CONTRACT_FIXTURE'}, 'SOURCE_CLASSIFICATION')
        check(source.get('admission_state') == 'RESEARCH_BYTES_ONLY', 'ADMISSION_SCOPE')
        purposes = source.get('eligible_purposes')
        check(isinstance(purposes, list) and bool(purposes) and
              len(purposes) == len(set(purposes)) and
              all(x in {'discovery', 'research', 'training', 'backtest'} for x in purposes) and
              purpose in purposes, 'PURPOSE_NOT_LICENSED')
        check(source.get('pit_status') in {'VERIFIED', 'PIT_PROXY'}, 'PIT_UNKNOWN')
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
        lake = None
        rows, verified, identity_map, symbol_map, seen = [], [], {}, {}, set()
        for item in files:
            check(item.get('columns') == PRICE_COLUMNS, 'FILE_SCHEMA')
            identity = item.get('instrument')
            check(isinstance(identity, dict), 'INSTRUMENT_IDENTITY')
            for key in ('instrument_id', 'ticker', 'market', 'mic', 'timezone', 'calendar', 'currency'):
                text(identity.get(key), 'INSTRUMENT_IDENTITY')
            check(identity['market'] == 'US' and identity['currency'] == 'USD', 'DATASET_MARKET')
            check(identity.get('adjustment_basis') in {'RAW', 'SPLIT_ADJUSTED', 'TOTAL_RETURN'}, 'ADJUSTMENT_BASIS')
            iid = identity['instrument_id']
            check(iid not in identity_map or identity_map[iid] == identity, 'IDENTITY_DRIFT')
            symbol = (identity['market'], identity['ticker'])
            check(symbol not in symbol_map or symbol_map[symbol] == iid, 'SYMBOL_COLLISION')
            identity_map[iid], symbol_map[symbol] = identity, iid
            file_sha = item['sha256']
            if item.get('storage') == 'archive':
                raw = read_object(self.transport, f'{PREFIX_V1}/objects/{file_sha}', file_sha)
            elif item.get('storage') == 'lake':
                binding = spec.get('lake_binding')
                check(isinstance(binding, dict) and restore_to is not None, 'LAKE_BINDING')
                if lake is None:
                    lake = pinned_lake(self.transport, Path(restore_to) / generation / 'lake-cache',
                        commit_sha256=binding.get('commit_sha256'), catalog_sha256=binding.get('catalog_sha256'),
                        execution_receipt_sha256=binding.get('execution_receipt_sha256'))
                try:
                    entry = lake.catalog['datasets'][item.get('lake_key')]
                    check(entry['status'] in {'COLLECTED', 'UNCHANGED'} and
                          entry['normalized'] == file_sha and item.get('format') == 'gzip_jsonl',
                          'LAKE_DATASET_BINDING')
                    lake.verify_pack_dependencies({p: {s for s, loc in lake.catalog['locations'].items() if loc == p}
                        for p in set(lake.catalog['locations'].values())})
                    raw = lake.get_bytes(file_sha)
                except (OSError, ValueError, KeyError, TypeError):
                    raise ContractError('LAKE_VERIFICATION_FAILED') from None
            else:
                raise ContractError('UNTRUSTED_STORAGE')
            check(len(raw) == item['bytes'] and digest(raw) == file_sha, 'FILE_BYTES')
            parsed = self._rows(raw, item.get('format'))
            check(type(item.get('rows')) is int and item['rows'] > 0 and len(parsed) == item['rows'], 'ROW_COUNT')
            dates = []
            for row in parsed:
                check(isinstance(row, dict) and set(row) == set(PRICE_COLUMNS), 'ROW_SCHEMA')
                check(row['instrument_id'] == iid and row['ticker'] == identity['ticker'], 'ROW_IDENTITY')
                session = day(row['session_date'])
                row_available = clock(row['available_from'])
                check(session <= row_available.date() and row_available <= available and
                      row_available <= decision, 'FUTURE_AVAILABLE_FROM')
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
                dates.append(session)
                rows.append(row)
            check(dates == sorted(dates), 'UNSORTED_SESSIONS')
            check(min(dates) == day(item.get('start')) and max(dates) == day(item.get('end')), 'FILE_PERIOD')
            verified.append((file_sha, raw))

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
        receipt = dict(schema='research-data-read-receipt-v1', status='VERIFIED_RESEARCH_BYTES',
            dataset_id=dataset_id, data_generation_id=generation, manifest_sha256=generation,
            source_run_id=manifest['source_run_id'], consumer_id=consumer_id, purpose=purpose,
            decision_time=decision_time, required_start=required_start, required_end=required_end,
            file_sha256=[h for h, _ in verified], rows=len(selected),
            row_set_sha256=digest(encoded(selected)), classification=source['classification'],
            pit_status=source['pit_status'], admission_state=source['admission_state'],
            source_receipt_sha256=source['source_receipt_sha256'],
            producer_code_sha=source['producer_code_sha'], producer_config_sha256=source['producer_config_sha256'],
            requested_session_coverage_verified=sessions is not None, calendar_source_verified=False,
            instrument_ids=sorted(requested), minimum_rows=minimum_rows,
            required_sessions_sha256=digest(encoded(required_sessions)) if sessions is not None else None,
            raw_source_sha256=list(source['raw_source_sha256']),
            source_available_from=source['available_from'], source_collected_at=source['collected_at'],
            source_expires_at=source['expires_at'], reader_code_sha256=sha256_file(Path(__file__)),
            registry_sha256=self.registry_sha256, provider_refresh_count=0,
            cache_prices_authority=False, eligible_for_economics=False, eligible_for_selector=False,
            freshness_contract_source=next(x['path'] for x in DATA_SOURCES if x['name'] == 'prices'))
        receipt['receipt_sha256'] = digest(encoded(receipt))
        return ReadResult(tuple(selected), tuple(verified), receipt)

    @staticmethod
    def _rows(raw, format_name):
        if format_name in {'jsonl', 'gzip_jsonl'}:
            if format_name == 'gzip_jsonl':
                try:
                    raw = unpacked(raw)
                except (OSError, EOFError, ValueError):
                    raise ContractError('INVALID_GZIP') from None
            check(len(raw) <= 128 * 1024 * 1024, 'DECODE_SIZE')
            return [decode(line) for line in raw.splitlines()]
        if format_name == 'parquet':
            try:
                import pyarrow as pa
                import pyarrow.parquet as pq
            except ImportError:
                raise ContractError('PARQUET_ENGINE_UNAVAILABLE') from None
            try:
                parquet = pq.ParquetFile(io.BytesIO(raw))
                check(0 < parquet.metadata.num_rows <= 1_000_000, 'PARQUET_ROW_BUDGET')
                expected = pa.schema([(key, pa.string() if not kind.endswith('number') else pa.float64())
                                      for key, kind in PRICE_COLUMNS.items()])
                check(parquet.schema_arrow.equals(expected, check_metadata=False), 'PARQUET_SCHEMA')
                return parquet.read().to_pylist()
            except pa.ArrowException:
                raise ContractError('INVALID_PARQUET') from None
        raise ContractError('UNSUPPORTED_FORMAT')

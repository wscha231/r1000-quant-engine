"""ETF research adapters around the existing holdings normalizer and Reader.

No collectors, transport configuration, Source admission, canonical Registry
writes or economic mutations. Current merged Reader.read is the only Reader
API used; the unmerged component API is not imported.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict

from tools.etf116_research_metrics_h1 import BASIS, d, require
from tools.etf_top3_holdings_overlay_h1 import TOP3, build_lookthrough


def prepare_holdings(records, seed_symbols, *, decision_at, evaluation_time=None):
    """Normalize one dated top10 snapshot per ETF without claiming PIT time."""
    import pandas as pd
    from tools.run_etf_holdings_refresh import normalize_holding_rows

    overlay = build_lookthrough(records, seed_symbols, reviewed_at_utc=decision_at,
                               evaluation_time=evaluation_time)
    grouped = defaultdict(list)
    for row in records:
        grouped[row['etf']].append(row)
    normalized = []
    for fund in TOP3:
        rows = sorted(grouped[fund], key=lambda r: r['rank'])
        frame = pd.DataFrame([{'ticker': r['ticker'], 'weight': r['weight_pct']} for r in rows])
        result = normalize_holding_rows(frame,
            {'etf_ticker': fund, 'etf_label': fund, 'theme': 'ETF_TOP10_RESEARCH'},
            as_of=rows[0]['holdings_asof'], source='SUPPLIED_DATED_RESEARCH_SNAPSHOT',
            max_holdings=10, weight_unit='PERCENT', coverage_kind='TOP_ONLY')
        require(len(result) == 10, 'EXISTING_NORMALIZER_REFUSED_HOLDINGS')
        for normalized_row, source in zip(result.to_dict('records'), rows):
            require(normalized_row['holding_ticker'] == source['ticker'], 'NORMALIZER_IDENTITY_CHANGED')
            # The old normalizer copies as_of into available_from. A missing
            # issuer release clock must remain missing in this research adapter.
            normalized_row['available_from'] = source.get('published_at_utc')
            normalized_row['source_url'] = source['source_url']
            normalized_row['eligible_for_pit'] = False
            normalized.append(normalized_row)
    return {**overlay, 'normalized_holdings': normalized,
            'normalizer': 'tools.run_etf_holdings_refresh.normalize_holding_rows',
            'canonical_registry_written': False, 'sheet_publisher_allowed': False,
            'economic_authority': False}


def read_total_return_component(reader, *, dataset_id, generation, ticker,
                                instrument_id, sessions, decision_at):
    """Read an explicitly declared TR source through the existing hash Reader.

    TOTAL_RETURN identity alone does not distinguish issuer NAV from market
    TR. The immutable generation source must declare that basis plus a pinned
    methodology hash. Existing RAW/SPLIT_ADJUSTED OHLCV therefore refuses.
    The adapter's per-row source_sha256 references immutable Reader receipt
    bytes; provider-original digests stay separately labeled in that receipt.
    """
    from tools.research_data_access import ResearchDataReader, PREFIX_V1, read_object, decode, sha

    require(isinstance(reader, ResearchDataReader), 'CONFIGURED_RESEARCH_READER_REQUIRED')
    generation = sha(generation)
    raw = read_object(reader.transport, f'{PREFIX_V1}/generations/{generation}', generation,
                      1024 * 1024)
    manifest = decode(raw)
    require(isinstance(manifest, dict), 'TR_MANIFEST_NOT_OBJECT')
    datasets = manifest.get('datasets')
    require(isinstance(datasets, list), 'TR_DATASETS_NOT_LIST')
    matches = [r for r in datasets if isinstance(r, dict) and r.get('dataset_id') == dataset_id]
    require(len(matches) == 1, 'TR_DATASET_NOT_UNIQUE')
    source = matches[0].get('source')
    require(isinstance(source, dict), 'TR_SOURCE_NOT_OBJECT')
    basis = source.get('total_return_basis')
    require(type(basis) is str and basis in BASIS, 'EXPLICIT_DAILY_TR_BASIS_REQUIRED')
    methodology_hash = sha(source.get('total_return_methodology_sha256'))
    series_hash = sha(source.get('total_return_series_sha256'))
    files = matches[0].get('files')
    require(isinstance(files, list), 'TR_FILES_NOT_LIST')
    identities = [r.get('instrument') for r in files if isinstance(r, dict)
                  and isinstance(r.get('instrument'), dict)
                  and r['instrument'].get('instrument_id') == instrument_id]
    require(bool(identities), 'TR_INSTRUMENT_MISSING')
    require(all(i.get('ticker') == ticker and i.get('adjustment_basis') == 'TOTAL_RETURN'
                for i in identities), 'TR_IDENTITY_OR_ADJUSTMENT_MISMATCH')
    require(isinstance(sessions, list) and bool(sessions), 'TR_SESSIONS_REQUIRED')
    result = reader.read(dataset_id, generation, decision_time=decision_at,
        purpose='research', instrument_ids=[instrument_id], required_start=sessions[0],
        required_end=sessions[-1], minimum_rows=len(sessions), required_sessions=sessions,
        consumer_id='etf116_research', restore_to=None)
    receipt = json.loads(result.receipt_bytes)
    rows = [{'ticker': ticker, 'date': r['session_date'], 'tr_index': r['close'],
             'basis': basis, 'available_at_utc': r['available_from'],
             'source_sha256': receipt['receipt_sha256'],
             'total_return_series_sha256': series_hash,
             'total_return_methodology_sha256': methodology_hash} for r in result.rows]
    return {'rows': rows, 'reader_receipt': receipt,
            'reader_receipt_bytes_sha256': hashlib.sha256(result.receipt_bytes).hexdigest(),
            'source_reference_kind': 'READER_RECEIPT_SHA256_NOT_PROVIDER_BYTES',
            'total_return_methodology_sha256': methodology_hash,
            'total_return_series_sha256': series_hash,
            'research_only': True, 'a1_source_admitted': False,
            'sheet_publisher_allowed': False, 'economic_authority': False}


def classify_spmo_nav_reference(records):
    """Keep restored issuer NAV as valuation context, never an executable TR."""
    require(isinstance(records, list) and bool(records), 'NAV_REFERENCE_EMPTY')
    seen = set()
    for row in records:
        require(isinstance(row, dict), 'NAV_ROW_NOT_OBJECT')
        day = row.get('date_nyse')
        d(day)
        require(day not in seen, 'NAV_DUPLICATE_DATE')
        seen.add(day)
        require(row.get('source_basis') == 'ISSUER_NAV', 'NAV_BASIS_REQUIRED')
        require(row.get('trade_close_eligible') in (False, 'FALSE'), 'NAV_CANNOT_BE_TRADE_CLOSE')
        require(type(row.get('issuer_nav_usd')) in (str, float, int), 'NAV_VALUE_INVALID')
        try:
            nav = float(row['issuer_nav_usd'])
        except (KeyError, TypeError, ValueError):
            require(False, 'NAV_VALUE_INVALID')
        require(math.isfinite(nav) and nav > 0, 'NAV_VALUE_INVALID')
    return {'status': 'RESEARCH_NAV_REFERENCE_ONLY', 'ticker': 'SPMO',
            'reference_rows': len(records), 'start': min(seen), 'end': max(seen),
            'daily_total_return_verified': False, 'executable_market_price': False,
            'dividend_and_availability_status': 'BLOCKED_PENDING_A1_RECEIPT',
            'sheet_publisher_allowed': False, 'economic_authority': False}

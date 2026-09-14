"""Verified-history adapter and immutable research diagnostics, never paper state.

The caller supplies the existing Lake; this module never constructs a transport,
creates a Drive folder, publishes a Lake commit, or runs a portfolio workflow.
"""
from __future__ import annotations
import argparse
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.liquidity_driver_context import (INPUT_SCHEMA, SOURCES, ContractError,
    attach_to_canonical, encoded, evaluate, require, stamp)

MAX_BYTES = 32 * 1024 * 1024
UNIT_MAP = {'millions_usd': 'USD_MILLIONS', 'billions_usd': 'USD_BILLIONS',
            'percent': 'PERCENT', 'index': 'INDEX_1982_84_100'}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse_json(raw: bytes) -> Any:
    require(0 < len(raw) <= MAX_BYTES, 'INPUT_SIZE')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    def invalid(_value):
        raise ContractError('NONFINITE_JSON')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def read_bounded(path: Path) -> bytes:
    require(not any(p.is_symlink() for p in [path, *path.parents]), 'SYMLINK_PATH')
    with path.open('rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    require(0 < len(raw) <= MAX_BYTES, 'INPUT_SIZE')
    return raw


def write_once(path: Path, raw: bytes) -> None:
    require(not any(p.is_symlink() for p in [path, *path.parents]), 'SYMLINK_PATH')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as handle:
            handle.write(raw)
    except FileExistsError:
        require(read_bounded(path) == raw, 'IMMUTABLE_CONFLICT')
    require(read_bounded(path) == raw, 'WRITE_READBACK_MISMATCH')


def from_verified_lake(lake: Any, *, mode: str = 'current') -> dict:
    """Reuse canonical restore+receipt validation; do not silently fall back.

    A macro subset still requires Lake's complete archive restore to succeed.
    This adapter does not relabel current histories as archived vintages. It
    rehydrates the availability fields intentionally removed by collect_macros.
    """
    require(mode in {'current', 'alfred'}, 'MODE')
    require(not getattr(lake, 'pending', {}), 'UNPUBLISHED_LAKE_INPUT')
    receipt = lake.verified_execution()  # Existing contract verifies graph and reports.
    commit = parse_json(lake.read_hash('commits', lake.parent))
    require(receipt.get('commit_sha256') == lake.parent and
            receipt.get('catalog_sha256') == commit['catalog'], 'LAKE_IDENTITY')
    require(receipt.get('eligible_for_selector') is False and
            receipt.get('study_recomputed_from_drive') is True, 'LAKE_EXECUTION_INCOMPLETE')
    require(receipt.get('quality_status') in {'PARTIAL', 'COLLECTED_NOT_PIT_CERTIFIED'}, 'LAKE_QUALITY')
    packet = dict(schema=INPUT_SCHEMA, datasets={}, policy_events=[],
                  archive_identity={k: receipt[k] for k in ('commit_sha256', 'catalog_sha256',
                      'execution_receipt_sha256', 'quality_status')},
                  input_evidence='VERIFIED_LAKE_RESEARCH_SUBSET', missing_sources=[])
    for sid, (unit, freq, _, _) in SOURCES.items():
        key = mode + '/' + sid
        entry = lake.catalog['datasets'].get(key)
        if entry is None or entry.get('status') not in {'COLLECTED', 'UNCHANGED'}:
            packet['missing_sources'].append(dict(series=sid,
                reason='MISSING' if entry is None else 'BLOCKED_OR_STALE_RETAINED'))
            continue
        expected_evidence = 'current_only' if mode == 'current' else 'alfred_date_archive'
        require(entry.get('series') == sid and entry.get('frequency') == freq and
                UNIT_MAP.get(entry.get('unit'), entry.get('unit')) == unit and
                entry.get('evidence') == expected_evidence, 'LAKE_SOURCE_CONTRACT')
        require(bool(entry.get('raw_objects')) and bool(entry.get('normalized')), 'LAKE_OBJECTS')
        raw_hashes = []
        for object_id in entry['raw_objects']:
            compressed = lake.get_bytes(object_id)
            require(sha(compressed) == object_id, 'RAW_OBJECT_HASH')
            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as handle:
                raw = handle.read(MAX_BYTES + 1)
            require(0 < len(raw) <= MAX_BYTES, 'RAW_SIZE')
            raw_hashes.append(sha(raw))
        rows = copy.deepcopy(lake.get_records(key))
        retrieved = entry['retrieved_at']; stamp(retrieved)
        for row in rows:
            row['retrieved_at'] = retrieved
            if mode == 'current':
                # Current vintage is usable no earlier than this retrieval.
                old = row.get('available_at')
                row['available_at'] = max(stamp(old), stamp(retrieved)).isoformat() if old else retrieved
        # Do not let the parser's omitted missing observations become clean growth.
        if mode == 'current':
            dates = {r['observation_date'] for r in rows}
            for day in entry.get('missing_observation_dates', []):
                if day not in dates:
                    rows.append(dict(series=sid, observation_date=day, value=None,
                        retrieved_at=retrieved, available_at=retrieved, evidence='current_only'))
        packet['datasets'][sid] = dict(unit=unit, frequency=freq, status=entry['status'],
            raw_sha256=raw_hashes, normalized_object_sha256=entry['normalized'], rows=rows)
    return packet


def stage_liquidity_sources(lake: Any, start: str, through: str) -> dict:
    """Optional callback for the EXISTING collector, before its single publish.

    Reuse the bounded FRED fetch/parser, stage five bank series plus the inflation breakeven proxy.
    No transport, schedule, key handling, commit or execution receipt is added.
    The original collector remains responsible for persist/restore/study/receipt.
    """
    from tools.macro_history_sources import fetch, parse_graph
    outcomes = {}
    for sid in ('TOTCI', 'DPSACBW027SBOG', 'DRTSCILM', 'DRSDCILM', 'WLCFLPCL', 'T10YIE'):
        key = 'current/' + sid
        try:
            pages, retrieved = fetch(sid, start, through, 'current')
            require(len(pages) == 1, 'SOURCE_PAGES')
            rows, missing = parse_graph(pages[0], sid, start, through, retrieved)
            unit, freq, _, _ = SOURCES[sid]
            lake.dataset(key, pages, rows, dict(series=sid, unit=unit, frequency=freq,
                group=('inflation' if sid == 'T10YIE' else 'funding' if sid == 'WLCFLPCL' else 'bank_credit'), evidence='current_only', retrieved_at=retrieved,
                missing_observation_dates=missing, rows=len(rows),
                earliest=min(r['observation_date'] for r in rows),
                latest=max(r['observation_date'] for r in rows)))
            outcomes[sid] = 'STAGED_NOT_PUBLISHED'
        except Exception:
            # Provider messages may contain key URLs; never serialize exceptions.
            lake.blocked(key, ValueError('liquidity_source_blocked'))
            outcomes[sid] = 'BLOCKED'
    return dict(mode='RESEARCH_ONLY', outcomes=outcomes, published=False)


def report(result: dict) -> bytes:
    rows = ['# Liquidity driver research diagnostic', '',
        '**Not an order, portfolio target, current-market certification, or OOS result.**', '',
        f"Input kind: {result['input_kind']}", f"As of: {result['as_of']}", f"Source commit: {result['source_commit']}",
        f"Data hash: {result['data_hash']}", f"Quality: {result['quality_status']}", '',
        '| Evidence gate | Review candidate |', '|---|---|',
        f"| Cash defense | {result['cash_defense_review']} |",
        f"| Treasury duration extension | {result['duration_extension_review']} |",
        f"| Equity reentry | {result['equity_reentry_review']} |", '',
        '## Source coverage', '', '| Source | Status | Observation |', '|---|---|---|']
    rows += [f"| {sid} | {a['status']} | {a.get('observation_date', '')} |"
             for sid, a in sorted(result['source_quality'].items())]
    rows += ['', '## Explicit limitations', '', *result['coverage_limits'], '']
    return '\n'.join(rows).encode()


def publish_diagnostic(directory: Path, result: dict, *, writer=write_once) -> dict:
    """Immutable research run; manifest last. No mutable latest/accepted pointer."""
    payloads = {'context.json': encoded(result), 'report.md': report(result)}
    identity = sha(payloads['context.json'])
    destination = directory / identity
    for name, raw in payloads.items():
        writer(destination / name, raw)
        require(read_bounded(destination / name) == raw, 'PAYLOAD_READBACK')
    manifest = dict(schema='liquidity-diagnostic-manifest-v1', research_only=True,
        context_sha256=identity, members={name: sha(raw) for name, raw in payloads.items()},
        accepted_state=False, source_commit=result['source_commit'],
        data_hash=result['data_hash'], config_hash=result['config_hash'])
    writer(destination / 'manifest.json', encoded(manifest))
    require(read_bounded(destination / 'manifest.json') == encoded(manifest), 'MANIFEST_READBACK')
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--prior', type=Path)
    parser.add_argument('--expected-input-sha256')
    args = parser.parse_args()
    try:
        raw = read_bounded(args.input)
        if args.expected_input_sha256:
            require(sha(raw) == args.expected_input_sha256, 'INPUT_HASH_MISMATCH')
        packet = parse_json(raw)
        prior = parse_json(read_bounded(args.prior)) if args.prior else None
        result = evaluate(packet, as_of=args.as_of, source_commit=args.source_commit, prior=prior)
        # Raw-file identity is distinct from the canonical decoded data hash.
        result['input_file_sha256'] = sha(raw)
        manifest = publish_diagnostic(args.output_dir, result)
        print(json.dumps(dict(status='RESEARCH_DIAGNOSTIC_WRITTEN',
            quality=result['quality_status'], context_sha256=manifest['context_sha256'],
            fixture_only=packet.get('fixture_only') is True, accepted_state=False)))
        return 0 if result['quality_status'] == 'COMPLETE_INPUT' else 2
    except Exception:
        print(json.dumps(dict(status='BLOCKED_INPUT_OR_PERSISTENCE', accepted_state=False)))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())

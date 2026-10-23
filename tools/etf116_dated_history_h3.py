"""Immutable dated RESEARCH candidates using the existing ETF116 calculator.

No provider, admission, scheduler, accepted account or original Sheet writes.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import fcntl
import hashlib
from importlib.metadata import version, PackageNotFoundError
import json
import os
import platform
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.run_etf116_offline_research_h1 import run as calculate, validate_metadata
from tools.etf116_eod_gate import validate_universe, EXPECTED_UNIVERSE_SHA256
from tools.etf116_research_metrics_h1 import canonical_hash, RefuseInput, HORIZONS_M, verified_session_close

MAX_BYTES = 128_000_000
FALSE_FLAGS = ('source_rights_verified', 'allowed_for_sheet_publisher', 'a1_pit_admitted',
               'eligible_for_er_buy', 'eligible_for_target', 'economic_authority',
               'automatic_refresh_enabled')


def require(ok, reason):
    if not ok:
        raise RefuseInput(reason)


def raw_hash(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'HISTORY_DUPLICATE_JSON_KEY')
            out[key] = value
        return out
    def invalid(_):
        raise RefuseInput('HISTORY_NONFINITE_JSON')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except RecursionError:
        raise RefuseInput('HISTORY_JSON_RECURSION') from None
    except (json.JSONDecodeError, UnicodeError):
        raise RefuseInput('HISTORY_JSON_INVALID') from None


def read_bytes(path):
    # Caller-owned inputs and history objects are regular files, never symlinks.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        import stat
        require(stat.S_ISREG(os.fstat(handle.fileno()).st_mode), 'HISTORY_REGULAR_FILE_REQUIRED')
        raw = handle.read(MAX_BYTES + 1)
    require(0 < len(raw) <= MAX_BYTES, 'HISTORY_SIZE')
    return raw


def code_hash():
    root = Path(__file__).parent
    names = ('etf116_dated_history_h3.py', 'run_etf116_offline_research_h1.py',
             'etf116_research_metrics_h1.py', 'etf116_eod_gate.py', 'research_data_access.py')
    dependencies = {name: raw_hash((root / name).read_bytes()) for name in names}
    dependencies['r1000_legacy_input_guard.py'] = raw_hash(
        (root.parent / 'r1000_legacy_input_guard.py').read_bytes())
    try:
        runtime = {name: version(name) for name in ('pandas_market_calendars', 'pandas')}
    except PackageNotFoundError:
        raise RefuseInput('HISTORY_CALENDAR_RUNTIME_UNVERIFIED') from None
    runtime['python'] = platform.python_version()
    return canonical_hash({'code': dependencies, 'runtime': runtime})


def verify_snapshot(value, *, evaluation_time=None):
    require(isinstance(value, dict) and value.get('schema') == 'etf116-dated-research-v1',
            'HISTORY_SCHEMA')
    require(all(value.get(k) is False for k in FALSE_FLAGS), 'HISTORY_AUTHORITY')
    unsigned = {k: v for k, v in value.items() if k != 'snapshot_sha256'}
    require(value.get('snapshot_sha256') == canonical_hash(unsigned), 'HISTORY_HASH')
    require(value.get('universe_sha256') == EXPECTED_UNIVERSE_SHA256, 'HISTORY_SCOPE')
    symbols = validate_universe(list(value.get('ticker_results', {})))
    require(len(symbols) == 116, 'HISTORY_TICKERS')
    require(date.fromisoformat(value['session']).isoformat() == value['session'], 'HISTORY_SESSION')
    require(all(isinstance(value.get(k), str) for k in ('computed_at_utc', 'decision_at_utc')),
            'HISTORY_STORED_CLOCK')
    computed = datetime.fromisoformat(value['computed_at_utc'].replace('Z', '+00:00'))
    decision = datetime.fromisoformat(value['decision_at_utc'].replace('Z', '+00:00'))
    evaluated = evaluation_time if evaluation_time is not None else datetime.now(timezone.utc)
    require(isinstance(evaluated, datetime) and evaluated.tzinfo is not None
            and evaluated.utcoffset() is not None, 'HISTORY_EVALUATION_CLOCK')
    require(all(c.tzinfo is not None and c.utcoffset() is not None for c in (computed, decision))
            and computed >= decision
            and date.fromisoformat(value['session']) <= decision.astimezone(timezone.utc).date(),
            'HISTORY_STORED_CLOCK')
    require(computed <= evaluated, 'HISTORY_COMPUTED_AFTER_EVALUATION')
    require(decision >= verified_session_close(value['session']), 'HISTORY_STORED_PRE_CLOSE')
    for key in ('source_input_bytes_sha256', 'calculator_sha256', 'candidate_receipt_sha256'):
        require(isinstance(value.get(key), str) and re.fullmatch('[0-9a-f]{64}', value[key]),
                'HISTORY_PROVENANCE')
    for result in value['ticker_results'].values():
        require(isinstance(result, dict) and isinstance(result.get('horizons'), dict)
                and set(result['horizons']) == {str(m) for m in HORIZONS_M}
                and all(isinstance(w, dict) and isinstance(w.get('status'), str)
                        for w in result['horizons'].values()), 'HISTORY_METRIC_SHAPE')
    return value


def verify_source_binding(snapshot, source_bytes, *, evaluation_time=None):
    require(isinstance(source_bytes, bytes) and 0 < len(source_bytes) <= MAX_BYTES, 'HISTORY_SIZE')
    require(raw_hash(source_bytes) == snapshot['source_input_bytes_sha256'], 'HISTORY_SOURCE_HASH')
    original = strict_json(source_bytes)
    require(isinstance(original, dict)
            and original.get('schema') == 'etf116-metrics-candidate-input-v1'
            and original.get('scope_sha256') == snapshot['universe_sha256']
            and original.get('session') == snapshot['session']
            and isinstance(original.get('decision_at_utc'), str), 'HISTORY_SOURCE_CLOCK_BINDING')
    validate_metadata(original, evaluation_time=evaluation_time)
    decision = datetime.fromisoformat(original['decision_at_utc'].replace('Z', '+00:00'))
    require(decision.tzinfo is not None and decision.utcoffset() is not None
            and decision == datetime.fromisoformat(snapshot['decision_at_utc']),
            'HISTORY_SOURCE_CLOCK_BINDING')


def _put(path, raw):
    """Exclusive atomic publication. Identical objects are read-only reuse."""
    if path.exists() or path.is_symlink():
        require(read_bytes(path) == raw, 'HISTORY_EXISTING_OBJECT_CONFLICT')
        return
    fd, tmp = tempfile.mkstemp(prefix='.etf116-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(tmp, path)  # Never replace an existing receipt or a racing writer.
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(tmp)


def calculate_candidate(source, frozen, *, evaluation_time=None):
    # Reuse the existing calculator on the consumed bytes, never reread inputs.
    with tempfile.TemporaryDirectory(prefix='etf116-history-') as temp:
        base = Path(temp)
        (base / 'input.json').write_bytes(source)
        (base / 'frozen.txt').write_bytes(frozen)
        calculate(base / 'input.json', base / 'frozen.txt', base / 'candidate.json',
                  evaluation_time=evaluation_time)
        return strict_json(read_bytes(base / 'candidate.json'))


def project_candidate(candidate, session):
    results = {}
    for ticker, result in candidate['ticker_results'].items():
        daily = [r for r in result.get('daily_returns', []) if r['session'] == session]
        require(len(daily) <= 1, 'HISTORY_DUPLICATE_DAILY_RETURN')
        results[ticker] = {
            'basis': result.get('series_basis'),
            'state': result.get('state', 'RESEARCH_CANDIDATE'),
            'reason': result.get('reason'),
            'daily_return': daily[0] if daily else None,
            'daily_return_status': 'RESEARCH_CANDIDATE' if daily else 'BLOCKED_DAILY_TR_GAP',
            'horizons': {str(m): result.get('horizons', {}).get(str(m),
                {'status': result.get('reason', 'BLOCKED_RESEARCH_INPUT')}) for m in HORIZONS_M}}
    return results


def verify_calculation_binding(snapshot, source_bytes, *, evaluation_time=None):
    verify_snapshot(snapshot, evaluation_time=evaluation_time)
    verify_source_binding(snapshot, source_bytes, evaluation_time=evaluation_time)
    require(snapshot['calculator_sha256'] == code_hash(), 'HISTORY_CALCULATOR_CHANGED')
    symbols = validate_universe(list(snapshot['ticker_results']))
    frozen = ('\n'.join(symbols) + '\n').encode()
    candidate = calculate_candidate(source_bytes, frozen, evaluation_time=evaluation_time)
    require(candidate['candidate_receipt_sha256'] == snapshot['candidate_receipt_sha256'],
            'HISTORY_CANDIDATE_RECEIPT_MISMATCH')
    require(canonical_hash(project_candidate(candidate, snapshot['session']))
            == canonical_hash(snapshot['ticker_results']), 'HISTORY_CALCULATED_METRICS_MISMATCH')


def append_history(input_path, frozen_path, history_dir, *, now=None):
    source = read_bytes(input_path)
    frozen = read_bytes(frozen_path)
    validate_universe(frozen.decode().splitlines())
    packet = strict_json(source)
    require(isinstance(packet, dict), 'HISTORY_INPUT')
    session = packet.get('session')
    require(isinstance(session, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', session)
            and date.fromisoformat(session).isoformat() == session, 'HISTORY_SESSION')
    calendar = packet.get('verified_nyse_sessions')
    require(isinstance(calendar, list) and calendar and calendar[-1] == session
            and all(isinstance(s, str) and date.fromisoformat(s).isoformat() == s
                    and date.fromisoformat(s).weekday() < 5 for s in calendar)
            and calendar == sorted(set(calendar)), 'HISTORY_CALENDAR')
    clock = now or datetime.now(timezone.utc)
    require(clock.tzinfo is not None and clock.utcoffset() is not None, 'HISTORY_COMPUTED_CLOCK')
    require(isinstance(packet.get('decision_at_utc'), str), 'HISTORY_DECISION_CLOCK')
    decision = datetime.fromisoformat(packet['decision_at_utc'].replace('Z', '+00:00'))
    require(decision.tzinfo is not None and decision.utcoffset() is not None, 'HISTORY_DECISION_CLOCK')
    require(clock >= decision, 'HISTORY_COMPUTED_BEFORE_DECISION')
    require(date.fromisoformat(session) <= decision.astimezone(timezone.utc).date(),
            'HISTORY_SESSION_AFTER_DECISION')
    validate_metadata(packet, evaluation_time=clock)
    root = Path(history_dir)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    require(not root.is_symlink(), 'HISTORY_DIRECTORY_SYMLINK')
    objects = root / 'objects'
    objects.mkdir(exist_ok=True, mode=0o700)
    require(not objects.is_symlink(), 'HISTORY_DIRECTORY_SYMLINK')
    lock_fd = os.open(root / '.etf116.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = None
        existing = {}
        for path in sorted(root.glob('????-??-??.json')):
            record = verify_snapshot(strict_json(read_bytes(path)), evaluation_time=clock)
            require(path.stem == record['session'], 'HISTORY_FILENAME')
            require(record.get('previous_snapshot_sha256') == previous, 'HISTORY_CHAIN')
            raw_source = read_bytes(objects / (record['source_input_bytes_sha256'] + '.json'))
            verify_source_binding(record, raw_source, evaluation_time=clock)
            previous = record['snapshot_sha256']
            existing[record['session']] = record
        identity = {'source_input_bytes_sha256': raw_hash(source), 'calculator_sha256': code_hash()}
        if session in existing:
            record = existing[session]
            require(all(record[k] == v for k, v in identity.items()), 'HISTORY_SAME_SESSION_CONFLICT')
            return {'state': 'IDENTICAL_HISTORY_READ_ONLY', 'snapshot': record}
        if existing:
            latest = max(existing)
            require(session > latest, 'HISTORY_BACKWARD_SESSION')
            require(latest in calendar and calendar.index(session) == calendar.index(latest) + 1,
                    'HISTORY_MISSING_NYSE_SESSION')
        candidate = calculate_candidate(source, frozen, evaluation_time=clock)
        require(candidate['source_input_bytes_sha256'] == identity['source_input_bytes_sha256'],
                'HISTORY_INPUT_HASH')
        results = project_candidate(candidate, session)
        snapshot = {'schema': 'etf116-dated-research-v1', 'session': session,
                    'computed_at_utc': clock.astimezone(timezone.utc).isoformat(),
                    'decision_at_utc': decision.astimezone(timezone.utc).isoformat(),
                    'universe_sha256': EXPECTED_UNIVERSE_SHA256, **identity,
                    'candidate_receipt_sha256': candidate['candidate_receipt_sha256'],
                    'previous_snapshot_sha256': previous,
                    'research_status': 'PREPARED_ONLY_NO_AUTHORITY',
                    **{k: False for k in FALSE_FLAGS}, 'ticker_results': results}
        snapshot['snapshot_sha256'] = canonical_hash(snapshot)
        verify_snapshot(snapshot, evaluation_time=clock)
        _put(objects / (identity['source_input_bytes_sha256'] + '.json'), source)
        _put(root / (session + '.json'), encoded(snapshot))
        return {'state': 'APPENDED_RESEARCH_HISTORY', 'snapshot': snapshot}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--frozen', required=True)
    parser.add_argument('--history-dir', required=True)
    args = parser.parse_args()
    try:
        result = append_history(Path(args.input), Path(args.frozen), Path(args.history_dir))
    except (OSError, ValueError, RecursionError, KeyError, TypeError, AttributeError):
        print('BLOCKED_ETF116_HISTORY_INPUT')
        return 2
    print(json.dumps({k: v for k, v in result.items() if k != 'snapshot'} | {
        'session': result['snapshot']['session'],
        'snapshot_sha256': result['snapshot']['snapshot_sha256'],
        'automatic_refresh_enabled': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

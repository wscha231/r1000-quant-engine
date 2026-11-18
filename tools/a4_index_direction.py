"""Observed market direction from two FRED price indices on the same XNYS grid."""
from __future__ import annotations

from datetime import date, timedelta
import math
from pathlib import Path
import re
from urllib.parse import urlencode

from tools import market_analysis_engine as market
from tools import macro_history_sources as fred

SERIES = ('SP500', 'NASDAQ100')
HORIZONS = (1, 5, 10, 21, 63, 126, 252, 504)
LOOKBACK_DAYS = 820
MAX_CSV = 256 * 1024
GRAPH_CSV = 'https://fred.stlouisfed.org/graph/fredgraph.csv'
POLICY = 'a4-fred-index-access-v1'
VERIFICATION = 'a4-fred-index-publication-verification-v1'


def require(condition, code):
    if not condition:
        raise ValueError(code)


def window(cutoff):
    through = date.fromisoformat(market.current_session(cutoff))
    return (through - timedelta(days=LOOKBACK_DAYS)).isoformat(), through.isoformat()


def parse_csv(body, series, start, through, observed_at):
    require(type(body) is bytes and 0 < len(body) <= MAX_CSV, 'INDEX_CSV_SIZE')
    rows, _ = fred.parse_graph(body, series, start, through, observed_at)
    require(all(row['value'] > 0 for row in rows), 'INDEX_CLOSE_POSITIVE')
    return {row['observation_date']: row['value'] for row in rows}


def movement(value):
    return 'UP' if value > 0 else 'DOWN' if value < 0 else 'FLAT'


def describe(captures, *, cutoff):
    """Compute realized price changes without compressing gaps or backdating CSVs."""
    start, through = window(cutoff)
    schedule = market.clock.mcal.get_calendar('NYSE').schedule(start, through)
    days = [session.date().isoformat() for session in schedule.index]
    positions = {day: index for index, day in enumerate(days)}
    require(set(captures) == set(SERIES), 'INDEX_PAIR_REQUIRED')
    prices, sources = {}, {}
    for series in SERIES:
        capture = captures[series]
        if capture is None:
            prices[series] = {}
            sources[series] = dict(status='UNAVAILABLE', latest_session=None, lag_sessions=None)
            continue
        body, observed_at = capture
        require(fred.stamp(observed_at) <= fred.stamp(cutoff)
                and market.current_session(observed_at) == through, 'INDEX_CAPTURE_CLOCK')
        prices[series] = parse_csv(body, series, start, through, observed_at)
        require(set(prices[series]) <= positions.keys(), 'INDEX_NON_XNYS_CLOSE')
        latest = max(prices[series])
        lag = positions[through] - positions[latest]
        sources[series] = dict(status='CURRENT' if lag == 0 else 'DELAYED',
            latest_session=latest, lag_sessions=lag, observed_at=observed_at,
            original_sha256=fred.digest(body),
            source_url=GRAPH_CSV + '?' + urlencode(dict(id=series, cosd=start, coed=through)))

    common_days = prices[SERIES[0]].keys() & prices[SERIES[1]].keys()
    anchor = max(common_days, default=None)
    horizons = []
    if anchor is not None:
        end = positions[anchor]
        for horizon in HORIZONS:
            first = end - horizon
            # A holiday is absent from XNYS; an actual missing session breaks the window.
            if first < 0 or not all(day in common_days for day in days[first:end + 1]):
                horizons.append(dict(sessions=horizon, status='INCOMPLETE_WINDOW'))
                continue
            previous = days[first]
            returns = {series: prices[series][anchor] / prices[series][previous] - 1 for series in SERIES}
            require(all(math.isfinite(value) for value in returns.values()), 'INDEX_RETURN_NONFINITE')
            signs = {series: movement(value) for series, value in returns.items()}
            label = signs[SERIES[0]] if len(set(signs.values())) == 1 else 'MIXED'
            horizons.append(dict(sessions=horizon, status='OBSERVED', from_session=previous,
                                 through_session=anchor, price_returns=returns,
                                 per_index_direction=signs, direction=label))
    status = ('NO_COMMON_SESSION' if anchor is None else
              'CURRENT_COMMON_SESSION' if anchor == through else 'DELAYED_COMMON_SESSION')
    return dict(schema='a4-index-direction-v1', status=status,
                expected_session=through, common_session=anchor,
                common_lag_sessions=None if anchor is None else positions[through] - positions[anchor],
                cutoff=fred.stamp(cutoff).isoformat(), series=sources, horizons=horizons,
                basis='PRICE_INDEX_CLOSE', attribution='S&P Dow Jones Indices and Nasdaq via FRED',
                historical_pit_certified=False, predictive_forecast=False, training_admitted=False)


def read_policy(root, expected_sha256, cutoff):
    """Bind the owner-reviewed permissions for the two recurring uses."""
    require(type(expected_sha256) is str and re.fullmatch('[a-f0-9]{64}', expected_sha256),
            'INDEX_POLICY_PIN')
    root = Path(root)

    def read(name, limit):
        path = root / name
        require(not any(item.is_symlink() for item in (path, *path.parents)), 'INDEX_POLICY_SYMLINK')
        return market.bounded(path, limit)

    body = read('policy.json', 16 * 1024)
    require(fred.digest(body) == expected_sha256, 'INDEX_POLICY_HASH')
    policy = market.free.strict_json(body)
    require(type(policy) is dict and set(policy) ==
        {'schema', 'available_at', 'expires_at', 'purpose', 'permissions', 'evidence_sha256'},
        'INDEX_POLICY_SCHEMA')
    require(policy['schema'] == POLICY and policy['purpose'] == 'PRIVATE_DESCRIPTIVE_RESEARCH'
            and policy['permissions'] == ['KEYLESS_SCHEDULED_FRED_CSV', 'PRIVATE_DRIVE_RAW_AND_REPORT'],
            'INDEX_POLICY_SCOPE')
    now = fred.stamp(cutoff)
    require(fred.stamp(policy['available_at']) <= now < fred.stamp(policy['expires_at']),
            'INDEX_POLICY_EXPIRED')
    evidence = policy['evidence_sha256']
    names = {'fred', 'sp500', 'nasdaq100'}
    require(type(evidence) is dict and set(evidence) == names, 'INDEX_RIGHTS_SCOPE')
    for name in sorted(names):
        notice = read(name + '-permission.txt', 64 * 1024)
        require(bool(notice.strip()) and fred.digest(notice) == evidence[name], 'INDEX_RIGHTS_HASH')
    return body


def collect_approved(root, policy_sha256):
    """Two bounded official CSV requests. The existing A4 publisher owns writes."""
    now = fred.utc_now()
    read_policy(root, policy_sha256, now)
    start, through = window(now)
    captured = {}
    for series in SERIES:
        read_policy(root, policy_sha256, fred.utc_now())
        try:
            body = fred.request_bytes(GRAPH_CSV + '?' + urlencode(dict(id=series, cosd=start, coed=through)))
            observed_at = fred.utc_now()
            parse_csv(body, series, start, through, observed_at)
        except (OSError, ValueError):
            captured[series] = None
        else:
            captured[series] = (body, observed_at)
    return captured

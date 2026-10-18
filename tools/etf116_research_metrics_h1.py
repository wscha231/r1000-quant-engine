"""ETF116 research-only, deterministic total-return/risk recomputation.

No provider calls, order placement, Sheets/Drive writes, portfolio targeting,
source/PIT admission or activation. Accept *daily total-return index*, never
price-only OHLCV, NAV and market TR are kept as separate bases. Numbers are
research candidates even if they are mathematically reproducible.

Integration target: existing A1 verified research reader and preflight packet,
NOT a duplicate market data collector or standalone scheduled service.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import math
import statistics
from bisect import bisect_right
from datetime import date, datetime, timezone
from typing import Any

HORIZONS_M = (1, 3, 6, 12, 24, 36, 60, 120)
RISK_HORIZONS_M = (12, 36, 60, 120)
BASIS = {"NAV_TR_INDEX", "MARKET_TR_INDEX"}
MAX_RF_LAG_CALENDAR_DAYS = 7

class RefuseInput(ValueError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RefuseInput(code)


def d(value: str) -> date:
    require(type(value) is str and len(value) == 10 and value[4] == '-' and value[7] == '-', 'DATE_NOT_ISO')
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise RefuseInput('DATE_INVALID') from exc
    require(result.isoformat() == value, 'DATE_NOT_CANONICAL')
    return result


def ts(value: str) -> datetime:
    require(type(value) is str, 'CLOCK_NOT_TEXT')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise RefuseInput('CLOCK_INVALID') from exc
    require(result.tzinfo is not None and result.utcoffset() is not None, 'CLOCK_MISSING_TZ')
    return result.astimezone(timezone.utc)


def subtract_months(day: date, months: int) -> date:
    require(type(months) is int and months > 0, 'MONTH_WINDOW_INVALID')
    target = day.year * 12 + day.month - months - 1
    yr, zero_mo = divmod(target, 12)
    mo = zero_mo + 1
    return date(yr, mo, min(day.day, calendar.monthrange(yr, mo)[1]))


def official_session_dates(rows: list[str], *, asof: str) -> list[str]:
    """Validate caller-provided exchange-session GRID, not its provenance.

    Live exchange authority / holidays and special closures must be externally
    receipt-verified by the existing A1 calendar; this helper does not invent it.
    """
    end = d(asof)
    require(isinstance(rows, list) and bool(rows), 'CALENDAR_EMPTY')
    require(len(rows) == len(set(rows)) and rows == sorted(rows), 'CALENDAR_UNSORTED_OR_DUPLICATE')
    for s in rows:
        day = d(s)
        require(day.weekday() < 5 and day <= end, 'CALENDAR_INVALID_SESSION')
    require(rows[-1] == asof, 'CALENDAR_ASOF_SESSION_MISSING')
    return rows


def validate_series(rows: list[dict[str, Any]], sessions: list[str], *,
                    ticker: str, asof: str, decision_at: str,
                    rights_allowed: bool = False) -> dict[str, Any]:
    require(isinstance(rows, list), 'SERIES_NOT_LIST')
    dec = ts(decision_at)
    require(d(asof) <= dec.date(), 'SERIES_REVIEW_BEFORE_ASOF')
    all_sessions = set(sessions)
    entries: dict[str, float] = {}
    sources: set[str] = set()
    per_day_source: list[tuple[str,str]] = []
    bases: set[str] = set()
    for row in rows:
        require(isinstance(row, dict) and row.get('ticker') == ticker, 'SERIES_IDENTITY_CONFLICT')
        dt = row.get('date')
        d(dt)
        require(dt in all_sessions and dt <= asof, 'SERIES_INVALID_SESSION')
        require(dt not in entries, 'SERIES_DUPLICATE_SESSION')
        basis = row.get('basis')
        require(type(basis) is str and basis in BASIS, 'SERIES_NOT_TOTAL_RETURN_INDEX')
        bases.add(basis)
        value = row.get('tr_index')
        require(type(value) in (int, float) and math.isfinite(value) and value > 0, 'SERIES_BAD_TR_VALUE')
        availability = ts(row.get('available_at_utc'))
        require(availability.date() >= d(dt), 'SERIES_AVAILABLE_BEFORE_OBSERVATION')
        require(availability <= dec, 'SERIES_DATA_NOT_AVAILABLE_BY_REVIEW')
        source = row.get('source_sha256')
        require(type(source) is str and len(source) == 64 and all(k in '0123456789abcdef' for k in source),
                'SOURCE_DIGEST_MISSING')
        sources.add(source)
        per_day_source.append((dt, source))
        entries[dt] = float(value)
    require(len(bases) <= 1, 'SERIES_MIXED_TR_BASIS')
    # Each incremental NYSE date may reference distinct immutable raw bytes.
    # Pin the entire dated source-map; never require one file SHA for 10 years.
    dated_sources = sorted(per_day_source)
    composite_sha = (hashlib.sha256(json.dumps(dated_sources, separators=(',',':')).encode()).hexdigest()
                     if dated_sources else None)
    return {'ticker': ticker, 'basis': next(iter(bases)) if bases else None,
            'observations': entries, 'source_digest': composite_sha,
            'source_objects': len(sources), 'rights_allowed': rights_allowed}


def anchor_session(sessions: list[str], day: date) -> str | None:
    i = bisect_right(sessions, day.isoformat()) - 1
    return sessions[i] if i >= 0 else None


def aligned_window(sessions: list[str], series: dict[str, Any], anchor: str,
                   end: str, *, verified_listing_date: str | None = None) -> dict[str, Any]:
    require(anchor in sessions and end in sessions and anchor <= end, 'WINDOW_GRID_INVALID')
    if verified_listing_date is not None and d(verified_listing_date) > d(anchor):
        return {'status': 'INELIGIBLE_SHORT_LIFE', 'anchor_session': anchor, 'observed_days': 0}
    selected = [s for s in sessions if anchor <= s <= end]
    readings = series['observations']
    absent = [s for s in selected if s not in readings]
    if absent:
        return {'status': 'BLOCKED_DAILY_TR_GAPS', 'anchor_session': anchor,
                'observed_days': len(selected) - len(absent), 'expected_days': len(selected),
                'first_missing': absent[0], 'missing_count': len(absent)}
    return {'status': 'RESEARCH_DAILY_TR_COMPLETE', 'anchor_session': anchor,
            'expected_days': len(selected), 'observed_days': len(selected),
            'dates': selected, 'indices': [readings[s] for s in selected]}


def annualization_years(start: str, end: str) -> float:
    days = (d(end) - d(start)).days
    require(days >= 1, 'WINDOW_ZERO_DAYS')
    return days / 365.2425


def max_drawdown(index: list[float]) -> float:
    require(len(index) >= 2 and all(v > 0 and math.isfinite(v) for v in index), 'MDD_INPUT_INVALID')
    peak = index[0]
    trough = 0.0
    for v in index:
        peak = max(peak, v)
        trough = min(trough, v / peak - 1)
    return trough


def _sample_sd(values: list[float]) -> float | None:
    return statistics.stdev(values) if len(values) > 1 else None


def riskfree_lag_series(sessions: list[str], rf_rows: list[dict[str, Any]], *,
                        decision_at: str) -> list[float]:
    """DGS3MO annual percentage yield; prior observation only, never today/future.

    The *provided* available_at_utc must be genuine release evidence, not a
    fabricated publication time. Even a valid numeric rate is RESEARCH_ONLY.
    """
    decision = ts(decision_at)
    require(isinstance(rf_rows, list), 'RF_NOT_LIST')
    require(all(isinstance(r, dict) for r in rf_rows), 'RF_NOT_OBJECTS')
    rf: dict[str, tuple[float, datetime]] = {}
    for row in rf_rows:
        day = row.get('observation_date')
        d(day)
        require(day not in rf, 'RF_DUPLICATE_DATE')
        raw = row.get('dgs3mo_pct')
        require(type(raw) in (int, float) and math.isfinite(raw) and raw > -100, 'RF_NONNUMERIC')
        when = ts(row.get('available_at_utc'))
        require(when.date() >= d(day), 'RF_AVAILABLE_BEFORE_OBSERVATION')
        require(when <= decision, 'RF_NOT_AVAILABLE_AT_REVIEW')
        rf[day] = (float(raw), when)
    sorted_dates = sorted(rf)
    result = []
    for day in sessions[1:]:
        previous_calendar_date = date.fromordinal(d(day).toordinal() - 1).isoformat()
        idx = bisect_right(sorted_dates, previous_calendar_date) - 1
        if idx < 0:
            raise RefuseInput('RF_PRIOR_DATE_MISSING')
        # This API has date-only sessions, not verified intraday close clocks.
        # Conservatively require release by the start of the UTC return date.
        # A later report/review date cannot make a late release historical PIT.
        cutoff = ts(day + 'T00:00:00Z')
        prior = next((p for p in reversed(sorted_dates[:idx + 1]) if rf[p][1] <= cutoff), None)
        if prior is None:
            raise RefuseInput('RF_NOT_AVAILABLE_FOR_RETURN_SESSION')
        if (d(day) - d(prior)).days > MAX_RF_LAG_CALENDAR_DAYS:
            raise RefuseInput('RF_PRIOR_DATE_STALE')
        annual = rf[prior][0] / 100.0
        result.append((1.0 + annual) ** (1.0 / 252.0) - 1.0)
    return result


def risk_metrics(index: list[float], sessions: list[str], rf_rows: list[dict[str, Any]] | None, *,
                 decision_at: str, benchmark: list[float] | None = None) -> dict[str, Any]:
    require(len(index) == len(sessions) and len(index) >= 3, 'RISK_TR_WINDOW_TOO_SHORT')
    returns = [index[i] / index[i-1] - 1.0 for i in range(1, len(index))]
    vol_sd = _sample_sd(returns)
    out = {'mdd': max_drawdown(index), 'sharpe': None, 'sortino': None,
           'ann_volatility': vol_sd * math.sqrt(252.0) if vol_sd is not None else None,
           'trading_sessions': len(sessions)}
    # RF affects excess-return ratios, not total-return volatility or beta.
    try:
        if rf_rows is None:
            raise RefuseInput('RF_NOT_SUPPLIED')
        rf_daily = riskfree_lag_series(sessions, rf_rows, decision_at=decision_at)
        excess = [a-b for a,b in zip(returns, rf_daily)]
        e_avg = statistics.mean(excess)
        e_sd = _sample_sd(excess)
        downside_dev = math.sqrt(statistics.mean(min(0.0, x) ** 2 for x in excess))
        out['sharpe'] = e_avg * math.sqrt(252.0) / e_sd if e_sd and e_sd > 0 else None
        out['sortino'] = e_avg * math.sqrt(252.0) / downside_dev if downside_dev > 0 else None
        out['risk_free_status'] = 'RESEARCH_RF_AVAILABLE'
    except RefuseInput as exc:
        out['risk_free_status'] = 'BLOCKED_' + str(exc)
    if benchmark is not None:
        require(len(benchmark) == len(index) and all(v > 0 for v in benchmark), 'BENCHMARK_UNALIGNED')
        spy = [benchmark[i]/benchmark[i-1]-1 for i in range(1,len(benchmark))]
        spy_var = statistics.variance(spy) if len(spy) >= 2 else 0
        cov = statistics.covariance(returns,spy) if len(spy) >= 2 else 0
        out['beta_vs_spy'] = cov / spy_var if spy_var>0 else None
        out['corr_vs_spy'] = statistics.correlation(returns,spy) if vol_sd and vol_sd>0 and spy_var>0 else None
    return out


def compute_horizons(*, ticker: str, asof: str, decision_at: str,
                     official_sessions: list[str], tr_rows: list[dict[str, Any]],
                     issuer_listing_date: str | None,
                     rf_rows: list[dict[str, Any]] | None = None,
                     benchmark_rows: list[dict[str, Any]] | None = None,
                     source_rights_verified: bool = False,
                     benchmark_source_rights_verified: bool = False,
                     benchmark_present: bool = False) -> dict[str, Any]:
    official_session_dates(official_sessions, asof=asof)
    series = validate_series(tr_rows, official_sessions, ticker=ticker, asof=asof,
                             decision_at=decision_at, rights_allowed=source_rights_verified)
    bench = None
    benchmark_input_status = None
    if benchmark_rows is not None or benchmark_present:
        try:
            bench = validate_series(benchmark_rows, official_sessions, ticker='SPY',
                                    asof=asof, decision_at=decision_at,
                                    rights_allowed=benchmark_source_rights_verified)
        except RefuseInput as exc:
            # SPY is an optional comparison; invalid subject input still refuses.
            benchmark_input_status = 'BLOCKED_OPTIONAL_BENCHMARK_' + str(exc)
    if issuer_listing_date is not None:
        d(issuer_listing_date)
    report = {'ticker':ticker,'asof':asof,'series_basis':series['basis'],
              'candidate_source_sha256':series['source_digest'],
              'source_rights_verified':source_rights_verified,
              'research_only':True,'a1_source_admitted':False,
              'portfolio_approval':False,'rank_promotion':False,
              'data_complete_windows':0, 'horizons':{}}
    observations = series['observations']
    report['daily_returns'] = [
        {'session': end, 'previous_session': start,
         'total_return': observations[end] / observations[start] - 1.0}
        for start, end in zip(official_sessions, official_sessions[1:])
        if start in observations and end in observations]
    report['blocked_daily_intervals'] = max(0, len(official_sessions) - 1) - len(report['daily_returns'])
    for months in HORIZONS_M:
        target = subtract_months(d(asof), months)
        a = anchor_session(official_sessions, target)
        if a is None:
            report['horizons'][str(months)] = {'status':'BLOCKED_CALENDAR_ANCHOR_MISSING'}
            continue
        w = aligned_window(official_sessions,series,a,asof,verified_listing_date=issuer_listing_date)
        if w['status'] != 'RESEARCH_DAILY_TR_COMPLETE':
            report['horizons'][str(months)] = w
            continue
        indexes = w['indices']
        if len(indexes) < 2:
            report['horizons'][str(months)] = {'status':'BLOCKED_TOO_FEW_DATES'}
            continue
        y = annualization_years(a,asof)
        return_val = indexes[-1] / indexes[0]-1.0
        result = {'status':'RESEARCH_DAILY_TR_COMPLETE','basis':series['basis'],
                  'anchor_session':a,'expected_days':len(indexes),
                  'total_return':return_val,
                  'matched_window_mdd': max_drawdown(indexes),
                  'cagr':(indexes[-1]/indexes[0]) ** (1/y)-1.0 if months in (12,36,60,120) else None}
        if benchmark_input_status is not None:
            result['benchmark_status'] = benchmark_input_status
        if bench is not None and bench['basis'] == series['basis']:
            vw = aligned_window(official_sessions,bench,a,asof)
            if vw['status']=='RESEARCH_DAILY_TR_COMPLETE':
                result['spy_excess_cumulative_return'] = return_val - (vw['indices'][-1]/vw['indices'][0]-1)
                result['log_relative_rs_spy'] = math.log(indexes[-1]/indexes[0]) - math.log(vw['indices'][-1]/vw['indices'][0])
            else:
                result['benchmark_status']=vw['status']
        elif bench is not None:
            result['benchmark_status']='BENCHMARK_BASIS_MISMATCH'
        if months in RISK_HORIZONS_M:
            benchmark_index = None
            if bench is not None and bench['basis'] == series['basis']:
                bw = aligned_window(official_sessions,bench,a,asof)
                if bw['status'] == 'RESEARCH_DAILY_TR_COMPLETE':
                    benchmark_index=bw['indices']
            result['risk'] = risk_metrics(indexes,w['dates'],rf_rows,decision_at=decision_at,
                                         benchmark=benchmark_index)
        report['horizons'][str(months)] = result
        report['data_complete_windows'] += 1
    return report


def canonical_hash(data: Any) -> str:
    return hashlib.sha256(json.dumps(data,ensure_ascii=True,sort_keys=True,
                                     separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()

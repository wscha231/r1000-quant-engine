"""Offline contextual hypotheses; supplied provenance is not authenticated here."""
from datetime import date
import math
import numpy as np
import pandas as pd

def require(ok, reason):
    if not ok:
        raise ValueError('A4_REGIME_CONTEXT_' + reason)

def stamp(value):
    ts = pd.Timestamp(value)
    require(ts.tzinfo is not None and (not pd.isna(ts)), 'AWARE_CLOCK')
    return ts.tz_convert('UTC')

def monthly(series):
    require(isinstance(series, pd.Series) and isinstance(series.index, pd.PeriodIndex) and (series.index.freqstr == 'M'), 'MONTHLY_INDEX')
    require(series.index.is_unique and series.index.is_monotonic_increasing and (not series.index.hasnans) and (1 <= len(series) <= 2000), 'MONTHLY_ORDER')
    require(series.index[-1].ordinal - series.index[0].ordinal + 1 <= 2000, 'MONTHLY_EXPANSION_BUDGET')
    require(not np.isinf(series.to_numpy(float)).any(), 'MONTHLY_NONFINITE')
    return series.reindex(pd.period_range(series.index[0], series.index[-1], freq='M'))

def lei(monthly_values, diffusion, *, method_version, annualized_threshold):
    """Already-as-of native monthly LEI; no date or proprietary history inference."""
    require(type(method_version) is str and 1 <= len(method_version) <= 128, 'LEI_METHOD_VERSION')
    require(type(annualized_threshold) in (int, float) and math.isfinite(annualized_threshold) and (-1 < annualized_threshold < 0), 'LEI_THRESHOLD_FRACTION')
    values = monthly(monthly_values)
    require(len(values) >= 7, 'LEI_HISTORY')
    require((values.dropna() > 0).all(), 'LEI_NONPOSITIVE')
    require(diffusion is None or (type(diffusion) in (int, float) and math.isfinite(diffusion) and (0 <= diffusion <= 100)), 'DIFFUSION_UNIT')
    delta = values.diff()
    streak = 0
    for change in reversed(delta.to_list()):
        if pd.isna(change) or change >= 0:
            break
        streak += 1
    growth = None if values.iloc[-7:].isna().any() else float((values.iloc[-1] / values.iloc[-7]) ** 2 - 1)
    six_declines = None if delta.iloc[-6:].isna().any() else bool((delta.iloc[-6:] < 0).all())
    return dict(method_version=method_version, annualized_threshold=annualized_threshold, consecutive_decline_months=streak, decline_count_basis='CONFIRMED_CONTIGUOUS_SUFFIX_ONLY', six_consecutive_declines_USER_HYPOTHESIS=six_declines, six_month_annualized_growth=growth, six_month_diffusion=diffusion, depth_diffusion_threshold_condition=None if growth is None or diffusion is None else growth < annualized_threshold and diffusion <= 50, official_recession_prediction=False)

def valuation(cape, *, up_revisions, down_revisions, unchanged_revisions, eligible_estimates):
    """CAPE context and dated consensus-count arithmetic; no short-horizon timer."""
    values = monthly(cape)
    require((values.dropna() > 0).all(), 'CAPE_NONPOSITIVE')
    last = values.iloc[-1]
    reference = values.iloc[max(0, len(values) - 121):-1].dropna()
    counts = (up_revisions, down_revisions, unchanged_revisions, eligible_estimates)
    require(all((type(v) is int and v >= 0 for v in counts)) and eligible_estimates > 0, 'REVISION_COUNTS')
    require(up_revisions + down_revisions + unchanged_revisions == eligible_estimates, 'REVISION_COVERAGE')
    return dict(cape=None if pd.isna(last) else float(last), cape_prior_120m_percentile=None if pd.isna(last) or len(reference) < 60 else float((reference < last).mean()), earnings_revision_breadth=(up_revisions - down_revisions) / eligible_estimates, unchanged_fraction=unchanged_revisions / eligible_estimates, revision_denominator=eligible_estimates, automatic_valuation_bear_trigger=False)

def policy(events, sessions):
    """Rate announcements and effective targets stay distinct; no QE probability."""
    require(type(events) is list and len(events) <= 2000 and (type(sessions) is list) and (2 <= len(sessions) <= 10000), 'EVENT_BUDGET')
    seen = {}
    announcements = {}
    ordered = []
    for event in events:
        announced = stamp(event['announced_at'])
        available = stamp(event['available_at'])
        effective = date.fromisoformat(event['effective_on'])
        require(announced <= available, 'AVAILABILITY_BEFORE_ANNOUNCEMENT')
        require(effective >= announced.tz_convert('America/New_York').date(), 'EFFECTIVE_BEFORE_ANNOUNCEMENT')
        lo, hi = (event['target_lower'], event['target_upper'])
        require(all((type(x) in (int, float) and math.isfinite(x) for x in (lo, hi))) and lo <= hi, 'TARGET_RANGE')
        require(event['balance_sheet_action'] in ('QE', 'QT', 'NO_CHANGE'), 'REVIEWED_BALANCE_SHEET_LABEL')
        pin = event['original_sha256']
        require(type(pin) is str and len(pin) == 64 and all((c in '0123456789abcdef' for c in pin)), 'ORIGINAL_REF')
        require(available not in seen or seen[available] == event, 'CONFLICTING_EVENT')
        require(announced not in announcements or announcements[announced] == event, 'CONFLICTING_ANNOUNCEMENT')
        announcements[announced] = event
        if available not in seen:
            seen[available] = event
            ordered.append((available, event))
    ordered.sort(key=lambda x: x[0])
    closes = [stamp(s['close_utc']) for s in sessions]
    require(all((a < b for a, b in zip(closes, closes[1:]))), 'SESSION_ORDER')
    require(all((date.fromisoformat(s['session']) == clock.tz_convert('America/New_York').date() for s, clock in zip(sessions, closes))), 'SESSION_DATE')
    out = []
    visible = []
    position = 0
    last_mid = None
    last_direction = None
    first_cut = None
    hikes = cuts = 0
    latest_change = None
    first_cut_event = None
    for session, cutoff in zip(sessions, closes):
        changed = False
        while position < len(ordered) and ordered[position][0] <= cutoff:
            _, e = ordered[position]
            position += 1
            visible.append(e)
            changed = True
        if changed:
            # Availability gates visibility; announcement chronology determines
            # the decision sequence, including a newly visible older decision.
            visible.sort(key=lambda e: stamp(e['announced_at']))
            last_mid = last_direction = first_cut = first_cut_event = latest_change = None
            hikes = cuts = 0
            for e in visible:
                mid = (e['target_lower'] + e['target_upper']) / 2
                change = None if last_mid is None else round((mid - last_mid) * 100, 10)
                direction = None if change is None else 1 if change > 0 else -1 if change < 0 else 0
                if direction == -1:
                    first_cut_event = None if last_direction is None else last_direction == 1
                    if first_cut_event:
                        first_cut = stamp(e['announced_at']).tz_convert('America/New_York').date()
                    cuts += 1
                    hikes = 0
                elif direction == 1:
                    hikes += 1
                    cuts = 0
                    first_cut_event = False
                    first_cut = None
                elif direction == 0:
                    hikes = cuts = 0
                    first_cut_event = False
                else:
                    first_cut_event = None
                if direction in (-1, 1):
                    last_direction = direction
                last_mid = mid
                latest_change = change
        day = date.fromisoformat(session['session'])
        effective = [e for e in visible if date.fromisoformat(e['effective_on']) <= day]
        latest = visible[-1] if visible else None
        active = max(effective, key=lambda e: (e['effective_on'], stamp(e['announced_at']))) if effective else None
        out.append(dict(announced_target_mid=last_mid, effective_target_mid=None if active is None else (active['target_lower'] + active['target_upper']) / 2, latest_announced_change_bp=latest_change, first_cut_of_known_cycle=first_cut_event, consecutive_hike_decisions=hikes if latest else None, consecutive_cut_decisions=cuts if latest else None, days_since_known_first_cut=None if first_cut is None else (day - first_cut).days, latest_announced_balance_sheet_action=None if latest is None else latest['balance_sheet_action'], qe_probability=None, source_or_PIT_certified=False))
    result = pd.DataFrame(out, index=pd.DatetimeIndex([s['session'] for s in sessions]))
    for column in ('announced_target_mid', 'effective_target_mid', 'latest_announced_change_bp', 'consecutive_hike_decisions', 'consecutive_cut_decisions', 'days_since_known_first_cut', 'qe_probability'):
        result[column] = result[column].astype(float)
    result['first_cut_of_known_cycle'] = result.first_cut_of_known_cycle.astype('boolean')
    return result

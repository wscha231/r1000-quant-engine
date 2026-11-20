"""Offline contextual hypotheses; supplied provenance is not authenticated here."""
from datetime import date
from datetime import timedelta
from io import StringIO
import math
import numpy as np
import pandas as pd
from tools.macro_history_sources import digest, encoded

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


def shiller_workbook(raw, *, collected_at, cutoff):
    """Read the publisher's current CAPE sheet with the actual capture clock."""
    import xlrd
    from xlrd.compdoc import CompDocError
    from struct import error as StructError

    require(collected_at is not None and stamp(collected_at) <= stamp(cutoff), 'CAPE_CLOCK')
    require(type(raw) is bytes and 0 < len(raw) <= 4 * 1024**2
            and raw.startswith(bytes.fromhex('D0CF11E0A1B11AE1')), 'CAPE_WORKBOOK')
    require(xlrd.__version__ == '2.0.2', 'CAPE_XLS_PARSER_VERSION')
    book = None
    try:
        book = xlrd.open_workbook(file_contents=raw, on_demand=True, logfile=StringIO())
        sheet = book.sheet_by_name('Data')
        require(8 < sheet.nrows <= 2500 and 13 <= sheet.ncols <= 40, 'CAPE_SHEET_SIZE')
        require([sheet.cell_value(7, i).strip() for i in (0, 1, 3, 4, 12)] ==
                ['Date', 'P', 'E', 'CPI', 'CAPE'], 'CAPE_HEADER')
        months, values, notes = [], [], []
        last_month = stamp(collected_at).tz_convert('America/New_York').date().replace(day=1)
        for i in range(8, sheet.nrows):
            key = sheet.cell_value(i, 0)
            if key == '':
                for j in (1, 4, 6):
                    note = sheet.cell_value(i, j)
                    require(type(note) is str and len(note) <= 160 and len(notes) < 12, 'CAPE_NOTE')
                    if note.strip():
                        notes.append(note.strip())
                continue
            require(type(key) is float and math.isfinite(key) and not notes, 'CAPE_MONTH')
            year = int(key)
            fraction = (key-year)*100
            month = round(fraction)
            require(1871 <= year <= last_month.year and 1 <= month <= 12
                    and abs(fraction-month) < 1e-6, 'CAPE_MONTH')
            when = date(year, month, 1)
            require(when <= last_month and (not months or months[-1] < when), 'CAPE_MONTH_ORDER')
            value = sheet.cell_value(i, 12)
            require(value in ('', 'NA', '#N/A') or
                    (type(value) is float and math.isfinite(value) and value > 0), 'CAPE_VALUE')
            values.append(value if type(value) is float else np.nan)
            months.append(when)
    except (xlrd.XLRDError, CompDocError, StructError, AttributeError, IndexError, OverflowError):
        raise ValueError('A4_REGIME_CONTEXT_CAPE_INVALID') from None
    finally:
        if book is not None:
            book.release_resources()

    require(bool(months), 'CAPE_NO_ROWS')
    series = monthly(pd.Series(values, index=pd.PeriodIndex(months, freq='M'), dtype=float))
    last = series.iloc[-1]
    prior = series.iloc[-121:-1].dropna()
    stale = (stamp(cutoff).date() - months[-1]) > timedelta(days=90)
    status = 'MISSING' if pd.isna(last) else 'STALE' if stale else 'OBSERVED'
    publisher_notes = [note for note in notes if note]
    return dict(status=status, observation_month=months[-1].isoformat()[:7],
        value=float(last) if status == 'OBSERVED' else None,
        prior_120_month_percentile=float((prior < last).mean()) if status == 'OBSERVED' and len(prior)>=60 else None,
        prior_month_count=len(prior), available_at=collected_at, collected_at=collected_at, published_at=None,
        publisher_notes=publisher_notes, source_id='shiller:ie_data', original_sha256=digest(raw),
        source_uri='https://shillerdata.com/', basis='PUBLISHER_CURRENT_MONTHLY_VINTAGE',
        historical_pit_certified=False, training_admitted=False)


def treasury_three_month(raw, *, collected_at, start, through):
    """Read the 3-month leg from the already validated nominal Treasury original."""
    from tools import a4_primary_macro_sources as treasury
    from tools import free_market_context as f
    from xml.etree.ElementTree import ParseError

    rows = []
    property_tag = '{'+treasury.META+'}properties'
    value_tag = '{'+treasury.DATA+'}BC_3MONTH'
    date_tag = '{'+treasury.DATA+'}NEW_DATE'
    null_tag = '{'+treasury.META+'}null'
    try:
        for event, element, parents in treasury._xml_events(raw):
            if event != 'end' or element.tag != '{'+treasury.ATOM+'}entry':
                continue
            props = element.find('.//'+property_tag)
            observed = props.find(date_tag).text[:10]
            cell = props.find(value_tag)
            if cell is not None and start <= observed <= through:
                value = None if cell.get(null_tag) == 'true' else f.number(cell.text)
                rows.append(dict(observation_date=observed, value=value))
            element.clear()
            if len(parents) > 1:
                parents[-2].remove(element)
    except (ParseError, AttributeError, TypeError, RuntimeError):
        raise ValueError('A4_REGIME_CONTEXT_TREASURY_3M_INVALID') from None
    if not rows:
        return []
    original, normalized = digest(raw), digest(encoded(rows))
    return [dict(row, source_id='ust:DGS3MO', logical_id='yield_3m', unit='percent',
                 frequency='daily', measurement_basis='PAR_YIELD_CURVE', seasonal_basis='NSA',
                 family='RATES', max_age_days=7, original_sha256=original, normalized_sha256=normalized,
                 available_at=collected_at, collected_at=collected_at, published_at=None,
                 truth_class='PRIMARY_CURRENT_VINTAGE', historical_pit_certified=False) for row in rows]

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
        require(announced not in announcements or announcements[announced] == event, 'CONFLICTING_ANNOUNCEMENT')
        if announced not in announcements:
            announcements[announced] = event
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

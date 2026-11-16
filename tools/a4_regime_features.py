"""Pure bear/bull hypothesis transforms. No publisher, fit, forecast or weights."""
import numpy as np
import pandas as pd

def require(ok, reason):
    if not ok:
        raise ValueError('A4_REGIME_' + reason)

def grid(frame):
    require(isinstance(frame, (pd.DataFrame, pd.Series)) and isinstance(frame.index, pd.DatetimeIndex) and frame.index.is_unique and frame.index.is_monotonic_increasing and (not frame.index.hasnans), 'DATE_GRID')
    require(len(frame) <= 10000 and (not np.isinf(frame.to_numpy(float)).any()), 'PANEL_VALUES')
    if isinstance(frame, pd.DataFrame):
        require(frame.columns.is_unique and len(frame.columns) <= 128, 'COLUMNS')

def yield_curve(frame):
    """Native yields in percent. Re-steepening is not a bear classification."""
    grid(frame)
    require(set(frame) == {'yield_10y', 'yield_2y', 'yield_3m'}, 'YIELD_COLUMNS')
    out = pd.DataFrame(index=frame.index)
    for short in ('yield_2y', 'yield_3m'):
        suffix = short.removeprefix('yield_')
        spread = frame.yield_10y - frame[short]
        out['curve_10y_' + suffix + '_bp'] = spread * 100
        out['curve_10y_' + suffix + '_inverted'] = spread.lt(0).astype(float).where(spread.notna())
        out['curve_10y_' + suffix + '_re_cross'] = ((spread >= 0) & (spread.shift(1) < 0)).astype(float).where(spread.notna() & spread.shift(1).notna())
        streak = []
        since = []
        run = 0
        last_cross = None
        for position, value in enumerate(spread):
            if pd.isna(value):
                run = 0
                last_cross = None
                streak.append(np.nan)
                since.append(np.nan)
                continue
            run = run + 1 if value < 0 else 0
            if position and value >= 0 and (spread.iloc[position - 1] < 0):
                last_cross = position
            streak.append(float(run))
            since.append(np.nan if last_cross is None or value < 0 else float(position - last_cross))
        out['curve_10y_' + suffix + '_inverted_sessions'] = streak
        out['curve_10y_' + suffix + '_sessions_since_re_cross'] = since
        for n in (21, 63):
            long_change = frame.yield_10y - frame.yield_10y.shift(n)
            short_change = frame[short] - frame[short].shift(n)
            out[f'curve_10y_{suffix}_change_{n}_bp'] = (long_change - short_change) * 100
            out[f'curve_10y_{suffix}_short_fall_{n}_bp'] = -short_change * 100
            out[f'curve_10y_{suffix}_long_rise_{n}_bp'] = long_change * 100
    return out

def credit(frame):
    """OAS in percentage points; a 4pp threshold is a user hypothesis only."""
    grid(frame)
    require(set(frame) == {'hy_oas', 'ig_oas', 'ccc_oas'}, 'CREDIT_COLUMNS')
    out = pd.DataFrame(index=frame.index)
    for name in frame:
        out[name + '_bp'] = frame[name] * 100
        for n in (5, 21, 63):
            out[name + f'_change_{n}_bp'] = frame[name].diff(n) * 100
        out[name + '_past_252_z'] = (frame[name] - frame[name].shift(1).rolling(252, min_periods=252).mean()) / frame[name].shift(1).rolling(252, min_periods=252).std(ddof=1).replace(0, np.nan)
    out['hy_above_4pp_USER_HYPOTHESIS'] = frame.hy_oas.gt(4).astype(float).where(frame.hy_oas.notna())
    out['ccc_minus_hy_bp'] = (frame.ccc_oas - frame.hy_oas) * 100
    return out

def implied_volatility(frame):
    """Index tenor ratio, distinct from the listed futures curve and direction."""
    grid(frame)
    require(set(frame) == {'vix', 'vix3m', 'vvix', 'equity_put_call'}, 'VOLATILITY_COLUMNS')
    require((frame[['vix', 'vix3m', 'vvix']].fillna(1) > 0).all().all(), 'VOLATILITY_NONPOSITIVE')
    require((frame.equity_put_call.dropna() >= 0).all(), 'NEGATIVE_PUT_CALL')
    out = frame.copy()
    out['vix_vix3m'] = frame.vix / frame.vix3m
    out['vix_above_past_50d_mean'] = frame.vix / frame.vix.shift(1).rolling(50, min_periods=50).mean() - 1
    out['equity_put_call_5d'] = frame.equity_put_call.rolling(5, min_periods=5).mean()
    return out
DEFENSIVE = ('XLP', 'XLU', 'XLV')
CYCLICAL = ('XLY', 'XLI', 'XLF')
SECTORS = ('XLC', 'XLY', 'XLP', 'XLE', 'XLF', 'XLV', 'XLI', 'XLB', 'XLRE', 'XLK', 'XLU')

def sectors(frame):
    """Same-basis sector prices; absent pre-launch observations remain missing."""
    grid(frame)
    require(set(frame) == set(SECTORS + ('SPY',)), 'SECTOR_COLUMNS')
    require((frame.dropna(how='all').fillna(1) > 0).all().all(), 'SECTOR_NONPOSITIVE')
    out = pd.DataFrame(index=frame.index)
    for n in (21, 63):
        ret = frame / frame.shift(n) - 1
        for symbol in SECTORS:
            out[f'sector_{symbol}_return_{n}'] = ret[symbol]
        defensive = ret[list(DEFENSIVE)].mean(axis=1, skipna=False)
        cyclical = ret[list(CYCLICAL)].mean(axis=1, skipna=False)
        out[f'cyclical_minus_defensive_{n}'] = cyclical - defensive
        out[f'technology_minus_defensive_{n}'] = ret.XLK - defensive
        out[f'energy_minus_spy_{n}'] = ret.XLE - ret.SPY
    return out

def breadth(frame, index_price, *, population_id):
    """Counts for the supplied population; no inferred NYSE or PIT membership."""
    grid(frame)
    grid(index_price)
    require(frame.index.equals(index_price.index), 'BREADTH_GRID')
    require(type(population_id) is str and 1 <= len(population_id) <= 128, 'BREADTH_POPULATION')
    require(set(frame) == {'advances', 'declines', 'unchanged', 'new_highs', 'new_lows', 'eligible', 'above_ma50', 'above_ma200', 'eligible_ma50', 'eligible_ma200'}, 'BREADTH_COLUMNS')
    require((frame.dropna(how='all').fillna(0) >= 0).all().all(), 'BREADTH_NEGATIVE')
    require((frame.dropna(how='all').fillna(0) % 1 == 0).all().all(), 'BREADTH_COUNTS')
    count_columns = ['advances', 'declines', 'unchanged']
    coverage = frame[count_columns + ['eligible']].notna().all(axis=1)
    require((frame.loc[coverage, count_columns].sum(axis=1) == frame.loc[coverage, 'eligible']).all(), 'BREADTH_COVERAGE')
    require((frame.eligible.dropna() > 0).all(), 'EMPTY_BREADTH_POPULATION')
    require((frame[count_columns].sum(axis=1) <= frame.eligible).where(frame.eligible.notna(), True).all(), 'BREADTH_COVERAGE')
    for column in count_columns + ['new_highs', 'new_lows', 'eligible_ma50', 'eligible_ma200']:
        known = frame[[column, 'eligible']].notna().all(axis=1)
        require((frame.loc[known, column] <= frame.loc[known, 'eligible']).all(), 'BREADTH_LIMIT')
    for n in (50, 200):
        known = frame[[f'above_ma{n}', f'eligible_ma{n}']].notna().all(axis=1)
        require((frame.loc[known, f'above_ma{n}'] <= frame.loc[known, f'eligible_ma{n}']).all(), 'BREADTH_MA_LIMIT')
    eligible = frame.eligible.replace(0, np.nan)
    ad = (frame.advances - frame.declines).where(coverage).cumsum(skipna=False)
    out = pd.DataFrame(dict(ad_line=ad, advance_fraction=frame.advances / eligible, new_high_low_net_fraction=(frame.new_highs - frame.new_lows) / eligible, new_high_low_ratio=frame.new_highs / frame.new_lows.replace(0, np.nan), above_ma50_fraction=frame.above_ma50 / frame.eligible_ma50.replace(0, np.nan), above_ma200_fraction=frame.above_ma200 / frame.eligible_ma200.replace(0, np.nan)), index=frame.index)
    prior_price_high = index_price.shift(1).rolling(252, min_periods=252).max()
    prior_ad_high = ad.shift(1).rolling(252, min_periods=252).max()
    price_high = index_price >= prior_price_high
    ad_high = ad >= prior_ad_high
    known = index_price.notna() & ad.notna() & prior_price_high.notna() & prior_ad_high.notna()
    out['index_new_high_without_ad_confirmation'] = (price_high & ~ad_high).astype(float).where(known)
    return out
ECON_COLUMNS = ('delayed_sahm_gap_pp', 'delayed_sahm_above_05pp', 'unemployment_3m_change_pp', 'payroll_3m_annualized', 'payroll_12m_growth', 'cpi_12m_inflation', 'cpi_3m_annualized', 'cpi_yoy_change_3m')

def dated_economy(observations, sessions):
    """Full visible RTDSM vintages; RUC is a delayed proxy, never official Sahm."""
    from tools import a4_daily_multifactor as daily
    from tools import a4_rtdsm_sources as rtdsm
    from tools import free_market_context as f
    daily.macro_state(observations, sessions)
    specs = {'rtdsm:' + k: v for k, v in rtdsm.register().items()}
    groups = {}
    for row in observations:
        require(row['source_id'] in specs, 'DATED_SOURCE')
        key = row['logical_id']
        stamp = f.utc(row['available_at'])
        require(row['observation_date'].endswith('-01'), 'MONTH_PERIOD')
        identity = (key, stamp)
        group = groups.setdefault(identity, {})
        period = pd.Period(row['observation_date'], freq='M')
        require(period not in group or group[period] == row, 'VINTAGE_DUPLICATE')
        group[period] = row
    events = sorted(((stamp, key, rows) for (key, stamp), rows in groups.items()))
    position = 0
    visible = {}
    out = []
    for session in sessions:
        cutoff = f.utc(session['close_utc'])
        while position < len(events) and events[position][0] <= cutoff:
            stamp, key, rows = events[position]
            visible[key] = rows
            position += 1
        point = dict.fromkeys(ECON_COLUMNS, np.nan)
        for key, history in visible.items():
            latest = max(history)
            r = history[latest]
            if (cutoff.date() - f.iso_date(r['observation_date'])).days > r['max_age_days']:
                continue
            needed = 15 if key in ('unemployment', 'cpi') else 13
            periods = pd.period_range(latest - (needed - 1), latest, freq='M')
            if any((p not in history or history[p]['value'] is None for p in periods)):
                continue
            values = np.array([history[p]['value'] for p in periods], dtype=float)
            if key == 'unemployment':
                ma = np.convolve(values, np.ones(3) / 3, mode='valid')
                gap = round(float(ma[-1] - np.min(ma[:-1])), 12)
                point.update(delayed_sahm_gap_pp=gap, delayed_sahm_above_05pp=float(gap >= 0.5), unemployment_3m_change_pp=float(values[-1] - values[-4]))
            elif key == 'payrolls':
                require((values > 0).all(), 'PAYROLL_NONPOSITIVE')
                point.update(payroll_3m_annualized=float((values[-1] / values[-4]) ** 4 - 1), payroll_12m_growth=float(values[-1] / values[-13] - 1))
            elif key == 'cpi':
                require((values > 0).all(), 'CPI_NONPOSITIVE')
                point.update(cpi_12m_inflation=float(values[-1] / values[-13] - 1), cpi_3m_annualized=float((values[-1] / values[-4]) ** 4 - 1))
                prior = latest - 15
                if prior in history and history[prior]['value'] is not None:
                    require(history[prior]['value'] > 0, 'CPI_NONPOSITIVE')
                    point['cpi_yoy_change_3m'] = point['cpi_12m_inflation'] - (history[latest - 3]['value'] / history[prior]['value'] - 1)
        out.append(point)
    return pd.DataFrame(out, index=pd.DatetimeIndex([s['session'] for s in sessions]), columns=ECON_COLUMNS)

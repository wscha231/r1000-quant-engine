"""Offline, pinned-input index research; never a portfolio or admission engine."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, time
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time as timer
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import scipy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.macro_technical_study import technical_features, labels, archive_release_changes, evaluate, adjust_family

PRICE_IDS = ('SP500', 'NASDAQCOM', 'NASDAQ100')
MACRO_IDS = ('UNRATE', 'PAYEMS', 'CPIAUCSL')
LIMITS = dict(research_only=True, historical_pit_certified=False, source_admitted=False,
              full_lake_chain_verified=False, net_er=False, portfolio_backtest=False,
              selector_eligible=False, model_promoted=False, economic_activation=False,
              price_basis='FREE_PROXY_PRICE_INDEX_EXCLUDES_DIVIDENDS_AND_COSTS',
              prior_exposed_families=336, fresh_holdout=False, interpretation='EXPLORATORY_POST_SELECTION')
REQUIRED = ('dataset_id path sha256 byte_count row_count identity_type source_name '
            'source_url_or_drive_object_id source_file_path source_file_sha256 frequency units '
            'calendar_or_period_rule date_start date_end observation_clock_definition '
            'availability_clock_definition vintage_policy retrieved_at_utc rights_status '
            'purpose_limit producer_or_normalizer_code_sha').split()


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def read_json(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            need(k not in result, 'DUPLICATE_JSON_KEY')
            result[k] = v
        return result
    def invalid(_):
        raise ValueError('NONFINITE_JSON')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def instant(value):
    t = pd.Timestamp(value)
    need(t.tzinfo is not None and not pd.isna(t), 'AWARE_CLOCK_REQUIRED')
    return t.tz_convert('UTC')


def date_value(value):
    need(type(value) is str and len(value) == 10, 'ISO_DATE_REQUIRED')
    d = datetime.strptime(value, '%Y-%m-%d').date()
    need(d.isoformat() == value, 'ISO_DATE_REQUIRED')
    return d


def peak_rss():
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
        c = Counters(); c.cb = ctypes.sizeof(c)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        measure = ctypes.WinDLL('psapi', use_last_error=True).GetProcessMemoryInfo
        measure.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        measure.restype = wintypes.BOOL
        ok = measure(kernel.GetCurrentProcess(), ctypes.byref(c), c.cb)
        need(bool(ok), 'RSS_UNAVAILABLE')
        return int(c.PeakWorkingSetSize)
    import resource
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == 'darwin' else value * 1024)


class Budget:
    def __init__(self, config):
        self.start = timer.monotonic(); self.config = config

    def check(self):
        need(timer.monotonic()-self.start <= self.config['max_seconds'], 'RUNTIME_BUDGET')
        need(peak_rss() < self.config['max_rss_bytes'], 'MEMORY_BUDGET')


def validate_config(c):
    need(c.get('schema') == 'macro-index-research-config-v1', 'CONFIG_SCHEMA')
    fixed = dict(horizons=[21, 63, 126, 252], entry_delay=1, min_train=504, macro_min_train=60, initial=756,
                 fold_size=252, comparison_start='2016-01-01', primary_metric='oos_mse_improvement',
                 max_seconds=300, max_rss_bytes=1073741824, prior_exposed_families=336,
                 parameter_search=False, start='1996-01-01')
    for key, value in fixed.items():
        need(type(c.get(key)) is type(value) and c[key] == value, 'FIXED_CONFIG_'+key)
    need(date_value(c['end']) >= date_value(c['comparison_start']), 'END_BEFORE_COMPARISON')
    need(instant(c['preregistered_at_utc']) <= instant(c['as_of']), 'PREREGISTRATION_CLOCK')


def verified_file(path, expected_hash, count=None):
    p = Path(path)
    need(p.is_file() and not p.is_symlink(), 'INPUT_PATH')
    raw = p.read_bytes()
    need(sha(raw) == expected_hash, 'INPUT_HASH')
    need(count is None or len(raw) == count, 'INPUT_BYTES')
    return raw


def price_frame(raw):
    rows = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
    need(bool(rows) and len(rows[0]) == len(set(rows[0])), 'CSV_HEADER')
    need('date' in rows[0] and 'close' in rows[0], 'PRICE_COLUMNS')
    need(all(len(r) == len(rows[0]) for r in rows[1:]), 'CSV_ROW')
    frame = pd.DataFrame(rows[1:], columns=rows[0])
    need(len(frame) > 0, 'EMPTY_PRICE')
    days = pd.DatetimeIndex([date_value(d) for d in frame.date])
    need(days.is_unique and days.is_monotonic_increasing, 'PRICE_ORDER_DUPLICATE')
    values = pd.to_numeric(frame.close, errors='raise').to_numpy(float)
    need(np.isfinite(values).all() and (values > 0).all(), 'PRICE_NONFINITE_NONPOSITIVE')
    return pd.Series(values, index=days, name='close')


def load_inputs(manifest, config):
    need(manifest.get('schema') == 'macro-index-research-input-v1', 'MANIFEST_SCHEMA')
    rows = manifest.get('datasets', [])
    need(len(rows) == 6 and {r.get('dataset_id') for r in rows} == set(PRICE_IDS+MACRO_IDS), 'DATASET_SET')
    prices, macros, audit, bindings = {}, {}, {}, []
    raw_cache = {}
    for r in rows:
        sid = r['dataset_id']
        need(all(k in r and r[k] is not None and r[k] != '' for k in REQUIRED), 'MANIFEST_METADATA')
        need(r['rights_status'] == 'PRIVATE_RESEARCH_REFERENCE_ONLY' and
             r['purpose_limit'] == 'EXPLORATORY_RESEARCH_ONLY', 'PURPOSE_RIGHTS_BOUNDARY')
        need(type(r['calendar_or_period_rule']) is str and
             ('XNYS' in r['calendar_or_period_rule'] or r['calendar_or_period_rule'] == 'MONTHLY_ALFRED_VINTAGE'), 'CALENDAR_RULE')
        need(instant(r['retrieved_at_utc']) <= instant(config['as_of']), 'FUTURE_RETRIEVAL')
        code = r['producer_or_normalizer_code_sha']
        need(type(code) is str and len(code) in (40, 64) and all(ch in '0123456789abcdef' for ch in code), 'NORMALIZER_HASH')
        raw = verified_file(r['path'], r['sha256'], r['byte_count'])
        verified_file(r['source_file_path'], r['source_file_sha256'])
        bindings.append({k:r[k] for k in REQUIRED})
        if sid in PRICE_IDS:
            need(r['identity_type'] == 'PRICE_INDEX' and r['frequency'] == 'daily', 'PRICE_IDENTITY')
            price = price_frame(raw)
            need(price.index[-1].date() <= instant(config['as_of']).date(), 'FUTURE_PRICE')
            need(len(price) == r['row_count'], 'PRICE_ROWS')
            need(str(price.index[0].date()) == r['date_start'] and str(price.index[-1].date()) == r['date_end'], 'PRICE_RANGE')
            prices[sid] = price
        else:
            need(r['identity_type'] == 'MACRO_SERIES' and r['frequency'] == 'monthly', 'MACRO_IDENTITY')
            if r['sha256'] not in raw_cache:
                raw_cache[r['sha256']] = [read_json(line) for line in raw.splitlines() if line.strip()]
            all_records = raw_cache[r['sha256']]
            need(all(x.get('series') in MACRO_IDS for x in all_records), 'UNKNOWN_MACRO_IDENTITY')
            records = [x for x in all_records if x['series'] == sid]
            need(len(records) == r['row_count'] and bool(records), 'MACRO_ROWS')
            keys = [(x['observation_date'], x['vintage_date']) for x in records]
            need(len(keys) == len(set(keys)), 'MACRO_DUPLICATE')
            need(min(k[0] for k in keys) == r['date_start'] and max(k[0] for k in keys) == r['date_end'], 'MACRO_RANGE')
            for x in records:
                need(x.get('evidence') == 'alfred_date_archive', 'CURRENT_ONLY_MACRO_REFUSED')
                obs, vintage = date_value(x['observation_date']), date_value(x['vintage_date'])
                need(obs <= vintage <= instant(config['as_of']).date(), 'FUTURE_MACRO')
                conservative = pd.Timestamp(datetime.combine(vintage+timedelta(days=1), time(), ZoneInfo('America/New_York')))
                need(instant(x['available_at']) >= conservative and instant(x['available_at']) <= instant(config['as_of']), 'MACRO_AVAILABILITY')
                need(date_value(x['realtime_end']) >= vintage, 'VINTAGE_END')
                need(x['value'] is None or type(x['value']) in (int, float) and math.isfinite(x['value']), 'MACRO_NONFINITE')
                if x.get('published_at') is not None:
                    need(instant(x['published_at']) <= instant(x['available_at']), 'PUBLICATION_CLOCK')
            macros[sid] = records
            audit[sid] = dict(rows=len(records), missing_values=sum(x['value'] is None for x in records),
                             source_order_sorted=keys == sorted(keys), frequency='monthly', revisions_retained=True)
    schedule = mcal.get_calendar('NYSE').schedule(start_date=config['start'], end_date=config['end'])
    need(len(schedule) > 0 and (schedule.market_close <= instant(config['as_of'])).all(), 'UNCOMPLETED_SESSION')
    sessions = pd.DatetimeIndex(schedule.index).tz_localize(None)
    for sid, price in prices.items():
        window = price.loc[config['start']:config['end']]
        extra = window.index.difference(sessions)
        need(len(extra) == 0, 'OFF_CALENDAR_PRICE')
        missing = sessions.difference(window.index)
        audit[sid] = dict(source_rows=len(price), study_rows=len(window), first=str(price.index[0].date()),
                          last=str(price.index[-1].date()), missing_sessions=[str(d.date()) for d in missing],
                          forward_filled=False, source_kind='FREE_PROXY', historical_price_pit=False)
        if sid == 'SP500':
            full_episodes = drawdowns(price, 'SP500_FULL_HISTORY_DESCRIPTIVE')
            for episode in full_episodes:
                episode['duration_observed_rows'] = episode.pop('duration_sessions')
                episode['calendar_session_completeness'] = 'NOT_VERIFIED_PRE1996'
            audit[sid]['full_history_descriptive'] = dict(first=str(price.index[0].date()),
                last=str(price.index[-1].date()), rows=len(price),
                price_change=float(price.iloc[-1]/price.iloc[0]-1), episodes=full_episodes,
                pre1996_calendar_completeness='NOT_VERIFIED', predictive_study_uses_1996_only=True)
        prices[sid] = price.reindex(sessions)
    need(prices['SP500'].first_valid_index() == sessions[0], 'SP500_1996_NOT_AVAILABLE')
    max_available = max(instant(x['available_at']) for records in macros.values() for x in records)
    availability_schedule = mcal.get_calendar('NYSE').schedule(start_date=config['start'], end_date=(max_available+pd.Timedelta(days=10)).date())
    opens = availability_schedule.market_open
    for records in macros.values():
        for x in records:
            eligible = opens.index[opens >= instant(x['available_at'])]
            need(len(eligible) > 0 and x.get('effective_session') == str(eligible[0].date()), 'EFFECTIVE_SESSION')
    return prices, macros, schedule, audit, bindings


def macro_features(macros, schedule):
    features, events = {}, []
    sessions = pd.DatetimeIndex(schedule.index).tz_localize(None)
    close_times = [t.to_pydatetime() for t in schedule.market_close]
    for sid, records in macros.items():
        feature = archive_release_changes(records, sessions, close_times, 'monthly')
        features['macro_change_'+sid] = feature
        ordered = sorted(records, key=lambda x:(instant(x['available_at']), x['observation_date']))
        state, cursor = {}, 0
        for day, cutoff in zip(sessions, close_times):
            while cursor < len(ordered) and instant(ordered[cursor]['available_at']) <= cutoff:
                x = ordered[cursor]; state[x['observation_date']] = x; cursor += 1
            if pd.notna(feature.loc[day]):
                keys = sorted(state); a, b = state[keys[-1]], state[keys[-2]]
                events.append(dict(series=sid, decision_session=str(day.date()), decision_cutoff=cutoff.isoformat(),
                    observation_date=a['observation_date'], vintage_date=a['vintage_date'], available_at=a['available_at'],
                    previous_observation_date=b['observation_date'], previous_vintage_date=b['vintage_date'],
                    previous_available_at=b['available_at'], value=float(feature.loc[day])))
    return features, events


def evaluate_pinned(feature, target, horizon, config, start, train_start=0, kind='continuous'):
    """Use the existing evaluator with a conservative253-session training purge.

    Its entry_delay only sets the train maturity/HAC span for already built labels.
    Labels themselves always use t+1. Preserve both meanings in explicit fields.
    """
    embargo = max(config['horizons']) + config['entry_delay']
    y = target.copy(); y.iloc[:train_start] = np.nan
    minimum = config['macro_min_train'] if kind == 'release' else config['min_train']
    result = evaluate(feature, y, horizon, kind=kind, min_train=minimum,
        initial=start, fold_size=config['fold_size'], entry_delay=embargo-horizon)
    result.update(entry_delay_sessions=config['entry_delay'], training_purge_sessions=embargo,
                  evaluator_maturity_delay_sessions=embargo-horizon, min_train_samples=minimum)
    predictions = []
    x = feature.to_numpy(float); values = y.to_numpy(float); positions = np.arange(len(x))
    for fold in result['folds']:
        first = fold['first_test_position']
        train = (positions+embargo < first) & np.isfinite(x) & np.isfinite(values)
        test = (positions >= first) & (positions < first+config['fold_size']) & np.isfinite(x) & np.isfinite(values)
        baseline, mean, sd = float(values[train].mean()), float(x[train].mean()), float(x[train].std())
        need(int(train.sum()) == fold['n_train'] and fold['last_training_label_position'] < first, 'TRAIN_MATURITY')
        fold.update(training_feature_mean=mean, training_feature_sd=sd, training_target_mean=baseline,
                    actual_last_training_outcome_position=int(np.flatnonzero(train)[-1]+horizon+1))
        for pos in np.flatnonzero(test):
            forecast = baseline + fold['coefficient_per_train_sd'] * (x[pos]-mean)/sd
            predictions.append(dict(date=str(feature.index[pos].date()), position=int(pos), fold_start=fold['start'],
                target=float(values[pos]), forecast=float(forecast), baseline=baseline,
                mse_improvement=float((values[pos]-baseline)**2-(values[pos]-forecast)**2)))
    if predictions:
        need(math.isclose(float(np.mean([p['mse_improvement'] for p in predictions])),
                          result['oos_mse_improvement'], rel_tol=1e-8, abs_tol=1e-12), 'PREDICTION_PARITY')
    return result, predictions


def drawdowns(close, asset):
    episodes = []; peak = trough = None; active = False
    for pos, value in enumerate(close):
        if not np.isfinite(value):
            continue
        if peak is None:
            peak = trough = pos
        elif value >= close.iloc[peak]:
            if active:
                episodes.append(_episode(close, asset, peak, trough, pos, False)); active = False
            peak = trough = pos
        else:
            active = True
            if value < close.iloc[trough]:
                trough = pos
    if active:
        episodes.append(_episode(close, asset, peak, trough, len(close)-1, True))
    return episodes


def _episode(close, asset, peak, trough, end, censored):
    return dict(asset=asset, peak_date=str(close.index[peak].date()), trough_date=str(close.index[trough].date()),
        drawdown=float(close.iloc[trough]/close.iloc[peak]-1),
        recovery_date=None if censored else str(close.index[end].date()), censored=censored,
        observed_through=str(close.index[end].date()), duration_sessions=end-peak,
        missing_sessions_in_episode=int(close.iloc[peak:end+1].isna().sum()))


def paired_comparison(short, long, block=253):
    a = {p['date']:p for p in short}; b = {p['date']:p for p in long}
    common = sorted(set(a) & set(b)); x = np.array([a[d]['mse_improvement'] for d in common]); y = np.array([b[d]['mse_improvement'] for d in common])
    result = dict(matched_rows=len(common), short_only_rows=len(set(a)-set(b)), long_only_rows=len(set(b)-set(a)),
                  first=common[0] if common else None, last=common[-1] if common else None,
                  status='INDETERMINATE', block_sessions=block, bootstrap_draws=1000)
    if len(common) < 60:
        return result
    positions = np.array([a[d]['position'] for d in common], dtype=int)
    need(all(a[d]['position'] == b[d]['position'] for d in common) and
         (np.diff(positions) > 0).all(), 'MATCHED_SESSION_POSITIONS')
    span = int(positions[-1]-positions[0]+1)
    if span < 3*block:
        return result
    delta = y-x; mean = float(delta.mean()); pooled = float(np.sqrt((np.var(x)+np.var(y))/2))
    # Blocks remain on the ORIGINAL XNYS grid, including unscored sessions.
    grid = np.zeros(span); weights = np.zeros(span)
    grid[positions-positions[0]] = delta; weights[positions-positions[0]] = 1
    rng = np.random.default_rng(0); extended = np.r_[grid, grid[:block]]
    counts = np.r_[weights, weights[:block]]
    sums = np.r_[0., np.cumsum(extended)]; total = np.r_[0., np.cumsum(counts)]
    starts = rng.integers(0, span, size=(1000, math.ceil(span/block)))
    denominators = (total[starts+block]-total[starts]).sum(axis=1)
    valid = denominators > 0
    draws = (sums[starts+block]-sums[starts]).sum(axis=1)[valid]/denominators[valid]
    need(len(draws) >= 950, 'BOOTSTRAP_COVERAGE')
    low, high = np.quantile(draws, [.025, .975])
    reversal = float(x.mean())*float(y.mean()) < 0
    material = reversal or ((low > 0 or high < 0) and abs(mean) >= .2*pooled)
    result.update(delta=mean, original_session_span=span, short_mean=float(x.mean()), long_mean=float(y.mean()), ci95=[float(low), float(high)],
                  pooled_oos_sd=pooled, sign_reversal=reversal,
                  status='MATERIAL_EXPLORATORY' if material else 'NO_MATERIAL_CHANGE_DETECTED')
    return result


def study(manifest, config, budget):
    prices, macros, schedule, coverage, bindings = load_inputs(manifest, config); budget.check()
    macro, events = macro_features(macros, schedule); budget.check()
    sessions = schedule.index
    short_start = int(sessions.searchsorted(pd.Timestamp(config['comparison_start'])))
    first_test = short_start+config['initial']
    need(first_test < len(sessions), 'MATCHED_TEST_PERIOD_REQUIRED')
    results, predictions, comparisons = [], [], []
    dd = coverage['SP500']['full_history_descriptive'].pop('episodes')
    for sid, close in prices.items():
        reference = 'NASDAQCOM' if sid == 'SP500' else 'SP500'
        features, kinds = technical_features(close, prices[reference]); features.update(macro)
        need(len(features) == 24, 'FIXED_FEATURE_COUNT')
        dd.extend(drawdowns(close, sid))
        for name, feature in features.items():
            kind = 'release' if name.startswith('macro_change_') else kinds.get(name, 'continuous')
            for horizon in config['horizons']:
                target = labels(close, horizon, entry_delay=config['entry_delay'])
                row, pred = evaluate_pinned(feature, target, horizon, config, first_test, kind=kind)
                row.update(asset=sid, feature=name, benchmark=reference, training_view='1996_EXTENSION',
                           historically_exposed_family=sid != 'NASDAQ100', eligible_for_selector=False)
                results.append(row)
                append_predictions(predictions, pred, asset=sid, feature=name, horizon=horizon, view='1996_EXTENSION')
                if sid == 'SP500':
                    original, old_pred = evaluate_pinned(feature, target, horizon, config, first_test, short_start, kind)
                    original.update(asset=sid, feature=name, benchmark=reference, training_view='2016_ORIGINAL',
                                    historically_exposed_family=True, eligible_for_selector=False)
                    results.append(original)
                    append_predictions(predictions, old_pred, asset=sid, feature=name, horizon=horizon, view='2016_ORIGINAL')
                    comparison = (dict(status='INDETERMINATE_SPARSE_MONTHLY_RELEASES', matched_rows=len(set(p['date'] for p in old_pred) & set(p['date'] for p in pred)),
                                       block_sessions=253, bootstrap_draws=0) if kind == 'release' else paired_comparison(old_pred, pred))
                    comparisons.append(dict(asset=sid, feature=name, horizon=horizon, **comparison))
                budget.check()
    adjust_family(results)
    common = pd.DataFrame(prices).dropna()
    need(len(common) > 0, 'COMMON_INDEX_PERIOD')
    relative = []
    for sid in PRICE_IDS:
        relative.append(dict(asset=sid, first=str(common.index[0].date()), last=str(common.index[-1].date()),
            common_rows=len(common), price_return=float(common[sid].iloc[-1]/common[sid].iloc[0]-1),
            relative_to_sp500=float((common[sid].iloc[-1]/common[sid].iloc[0])/(common.SP500.iloc[-1]/common.SP500.iloc[0])-1)))
    increment = {}
    for sid, close in prices.items():
        old = close.loc[:'2015-12-31'].dropna()
        increment[sid] = dict(rows=len(old), first=str(old.index[0].date()) if len(old) else None,
            last=str(old.index[-1].date()) if len(old) else None,
            price_change=float(old.iloc[-1]/old.iloc[0]-1) if len(old) else None,
            meaning='DESCRIPTIVE_TRAINING_HISTORY_INCREMENT_NOT_ADDITIONAL_OPTIMIZED_SCORING')
    return dict(schema='macro-index-research-results-v1', limits=LIMITS, coverage=coverage,
        input_bindings=bindings, calendar_sha256=sha(schedule.to_csv().encode()),
        first_test_session=str(sessions[first_test].date()), training_purge_sessions=253,
        fixed_feature_count=24, metrics=results, comparisons=comparisons,
        increment_1996_2015=increment, macro_event_count=len(events),
        multiple_testing='Existing BY adjustment over all384 declared comparisons including insufficient families; exploratory prior-exposed holdout',
        univariate_hypotheses_not_a_strategy=True), b''.join(predictions), events, dd, relative


def csv_bytes(rows):
    if not rows:
        return b''
    keys = sorted(set().union(*(r.keys() for r in rows)))
    output = io.StringIO(newline=''); writer = csv.DictWriter(output, fieldnames=keys, lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({k:json.dumps(v, sort_keys=True, allow_nan=False) if isinstance(v, (dict, list)) else v for k,v in row.items()})
    return output.getvalue().encode()


def append_predictions(chunks, rows, **identity):
    if rows:
        raw = csv_bytes([dict(row, **identity) for row in rows])
        chunks.append(raw if not chunks else raw.split(b'\n', 1)[1])


def run(manifest_path, manifest_sha, config_path, config_sha, output):
    output = Path(output).resolve()
    need(not output.exists() and not output.is_relative_to(ROOT), 'NEW_EXTERNAL_OUTPUT_REQUIRED')
    manifest_raw = verified_file(manifest_path, manifest_sha); config_raw = verified_file(config_path, config_sha)
    manifest, config = read_json(manifest_raw), read_json(config_raw); validate_config(config)
    budget = Budget(config)
    result, predictions, events, dd, relative = study(manifest, config, budget)
    code_files = ('tools/macro_index_research_engine.py', 'tools/macro_technical_study.py', 'tools/macro_history_sources.py',
                  'docs/macro_indicator_registry.json')
    code = {p:sha((ROOT/p).read_bytes()) for p in code_files}
    code_sha = subprocess.check_output(['git','-c','safe.directory='+ROOT.as_posix(),'-C',str(ROOT),'rev-parse','HEAD'], text=True).strip()
    files = {'metrics.json':encoded(result), 'metrics.csv':csv_bytes(result['metrics']),
             'predictions.csv':predictions if isinstance(predictions, bytes) else csv_bytes(predictions), 'macro_events.csv':csv_bytes(events),
             'drawdowns.csv':csv_bytes(dd), 'relative_performance.csv':csv_bytes(relative)}
    dependencies = dict(python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__,
                        scipy=scipy.__version__, pandas_market_calendars=mcal.__version__)
    receipt = dict(schema='macro-index-research-receipt-v1', status='COMPLETED_RESEARCH_REFERENCE_ONLY',
        code_sha=code_sha, code_file_sha256=code, config_sha256=config_sha, manifest_sha256=manifest_sha,
        dependencies=dependencies, calendar_sha256=result['calendar_sha256'],
        output_sha256={name:sha(raw) for name,raw in files.items()}, input_bindings=result['input_bindings'], limits=LIMITS)
    files['receipt.json'] = encoded(receipt)
    budget.check()
    runtime = dict(status='PASS', wall_seconds=timer.monotonic()-budget.start, peak_rss_bytes=peak_rss(),
        platform=platform.platform(), dependencies=dependencies, rows=sum(x['study_rows'] for k,x in result['coverage'].items() if k in PRICE_IDS),
        receipt_sha256=sha(files['receipt.json']), provider_calls=0, drive_calls=0, portfolio_runs=0)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='macro-research-', dir=output.parent) as temporary:
        staged = Path(temporary)/'result'; staged.mkdir()
        for name, raw in files.items():
            (staged/name).write_bytes(raw)
        (staged/'runtime.json').write_bytes(encoded(runtime)); budget.check()
        need(not output.exists(), 'OUTPUT_RACE')
        os.rename(staged, output)
    return runtime


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True); parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--config', required=True); parser.add_argument('--config-sha256', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args.manifest, args.manifest_sha256, args.config, args.config_sha256, args.output)
        print(json.dumps(result, sort_keys=True)); return 0
    except (ValueError, OSError, KeyError, TypeError, OverflowError):
        # Never print paths, source rows, provider responses or partially scored metrics.
        print(json.dumps(dict(status='BLOCKED_RESEARCH_RUN', completed=False))); return 2


if __name__ == '__main__':
    raise SystemExit(main())

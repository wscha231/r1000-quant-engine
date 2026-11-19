"""Point-in-time daily benchmark replay and private forward research journal."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from tools import a4_daily_multifactor as daily
from tools import a4_guarded_regression as guarded
from tools import a4_macro_learning as learning
from tools import free_market_context as free
from tools import macro_technical_study as study
from tools.check_run287_do_not_repeat import evaluate_candidate, load_registry
from tools.macro_history_sources import digest, encoded, exclusive

TARGETS = ('SPY', 'QQQ')
HORIZONS = (21, 63, 126)
PRICE_FEATURES = daily.CORE + tuple(name for name in daily.RISK if name not in daily.CORE) + (
    'distance_sma20', 'distance_sma100', 'slope_sma50_20', 'slope_sma200_20')
FEATURES = PRICE_FEATURES + daily.ECON
SCHEMA = 'a4-daily-direction-journal-v1'
MINIMUM_WINDOWS = 20
MAX_CHECKPOINT_BYTES = 1024**2
MISSING_TIME = np.iinfo(np.int64).max


def require(condition, reason):
    if not condition:
        raise ValueError('A4_DAILY_DIRECTION_' + reason)


def specification():
    modules = {Path(module.__file__) for module in (daily, guarded, learning, study, free)} | {Path(__file__)}
    code = {path.name: digest(path.read_bytes().replace(b'\r\n', b'\n')) for path in modules}
    return dict(schema='a4-daily-direction-spec-v1', targets=TARGETS, horizons=HORIZONS,
                features=FEATURES, price_lookback=252, decision_delay_minutes=60,
                macro_anchor='NYSE_CLOSE', entry_delay_sessions=1,
                initial_session_count=756, minimum_train_rows=504, refit_sessions=21,
                minimum_nonoverlap_windows=MINIMUM_WINDOWS,
                model=guarded.specification(), baselines=['ALWAYS_UP', 'PAST_TRAINING_MEAN'],
                regime='RESEARCH_ONLY', code_sha256=code)


def timestamps(values):
    return np.array([pd.Timestamp(free.utc(value)).value if value is not None else MISSING_TIME
                     for value in values], dtype=np.int64)


def prepare(payload, policy, policy_pin, resolver):
    """Consume the existing pinned Reader request, with a stricter price clock gate."""
    require(digest(encoded(specification())) == policy.get('daily_direction_protocol_sha256'), 'PROTOCOL_PIN')
    days = learning.validate_inputs(payload, policy, policy_pin, resolver)
    identity = policy.get('trial_identity', {})
    require(set(identity) == {'signal', 'mechanism', 'book', 'window'}
            and evaluate_candidate(load_registry(), **identity)['allowed'], 'EXPERIMENT_PREFLIGHT')
    require(set(TARGETS) <= set(payload['prices']), 'BENCHMARK_PAIR')
    observations = [row for row in payload['observations'] if row['logical_id'] in {'payrolls', 'cpi', 'unemployment'}]
    require({'payrolls', 'cpi', 'unemployment'} == {row['logical_id'] for row in observations}
            and all(row['source_id'].startswith('rtdsm:') for row in observations), 'DATED_ECONOMY_REQUIRED')
    sessions = payload['sessions']
    require(sessions[0]['session'] == policy.get('daily_direction_calendar_origin_session'), 'CALENDAR_ORIGIN')
    macro = daily.macro_state(observations, sessions).loc[:, list(daily.ECON)]
    anchors = [free.utc(row['close_utc']) + timedelta(minutes=60) for row in sessions]
    clocks = timestamps([anchor.isoformat() for anchor in anchors])
    closes, times, panels, bases, feeds = {}, {}, {}, {}, {}
    for target in TARGETS:
        rows = payload['prices'][target]
        require(bool(rows), 'PRICE_ROWS_MISSING')
        for row in rows:
            binding = policy['source_bindings'][row['original_sha256']]
            evidence = binding.get('price_publication_clock_evidence_sha256')
            require(isinstance(evidence, str) and len(evidence) == 64 and
                    all(c in '0123456789abcdef' for c in evidence) and evidence in policy['reviewed_source_receipt_pins'],
                    'PRICE_PUBLICATION_EVIDENCE')
            if binding['historical_use'] == 'FORWARD_CAPTURE_ONLY':
                require(free.utc(row['collected_at']) <= free.utc(row['available_at']), 'PRICE_BACKDATED_CAPTURE')
            feed = binding.get('price_series_id')
            require(isinstance(feed, str) and 0 < len(feed) <= 128 and
                    feeds.setdefault(target, feed) == feed, 'PRICE_SERIES_IDENTITY')
        closes[target] = learning.price_series(rows, sessions, payload['cutoff'])
        bases[target] = rows[0]['return_basis']
        by_day = {row['session']: row['available_at'] for row in rows if row['value'] is not None}
        times[target] = timestamps([by_day.get(row['session']) for row in sessions])
        # Keep every calendar session, including missing or late closes. The
        # features below are all trailing and use at most 252 closes.
        ready = np.zeros(len(days), dtype=bool)
        if len(days) >= 252:
            windows = np.lib.stride_tricks.sliding_window_view(times[target], 252)
            ready[251:] = windows.max(axis=1) <= clocks[251:]
        prices = daily.price_features(closes[target], closes[target]).loc[:, list(PRICE_FEATURES)]
        panels[target] = prices.where(ready[:, None].repeat(len(PRICE_FEATURES), axis=1)).join(macro)
    return dict(days=days, anchors=anchors, clocks=clocks, closes=closes, times=times, panels=panels, bases=bases,
                feeds=feeds, cutoff=free.utc(payload['cutoff']), input_sha256=digest(encoded(payload)),
                policy_sha256=policy_pin, policy_expires_at=free.utc(policy['expires_at']))


def forecast(prepared, *, only_last=False):
    """Forecast every eligible session, fitting once per fixed 21-session block."""
    days, clocks = prepared['days'], prepared['clocks']
    position = np.arange(len(days))
    complete = np.logical_and.reduce([np.isfinite(prepared['panels'][target]).all(axis=1) for target in TARGETS])
    rows = []
    for target in TARGETS:
        x = prepared['panels'][target].to_numpy(float)
        for horizon in HORIZONS:
            y = study.labels(prepared['closes'][target], horizon).to_numpy(float)
            path_clocks = np.full(len(days), MISSING_TIME)
            if len(days) >= horizon+2:
                windows = np.lib.stride_tricks.sliding_window_view(prepared['times'][target], horizon+2)
                path_clocks[:len(windows)] = windows.max(axis=1)
            blocks = range(756, len(days), 21)
            if only_last:
                blocks = blocks[-1:]
            for first in blocks:
                train = complete & np.isfinite(y) & (position+horizon+1 < first) & (path_clocks < clocks[first])
                test = complete & (position >= first) & (position < first+21)
                if only_last:
                    test &= position == len(days)-1
                if train.sum() < 504 or not test.any():
                    continue
                prediction, fit = guarded.predictions(x[train], y[train], x[test])
                mean = float(y[train].mean())
                last_label_clock = pd.Timestamp(int(path_clocks[train].max()), tz='UTC').isoformat()
                train_rows = int(train.sum())
                for i, estimate in zip(position[test], prediction):
                    anchor = prepared['anchors'][i]
                    if anchor > prepared['cutoff']:
                        continue
                    rows.append(dict(decision_session=days[i].date().isoformat(), decision_at=anchor.isoformat(),
                        target=target, horizon_sessions=horizon, estimate=float(estimate), past_mean=mean,
                        return_basis=prepared['bases'][target], price_series_id=prepared['feeds'][target],
                        model_sha256=fit['parameter_sha256'],
                        train_rows=train_rows, fit_session=days[first].date().isoformat(),
                        last_label_available_at=last_label_clock))
    return rows


def row_key(row):
    return (row['decision_session'], row['target'], row['horizon_sessions'])


def score(rows, prepared):
    """Only complete next-close paths observable at the evaluation clock mature."""
    days = prepared['days']
    read_at = pd.Timestamp(prepared['cutoff']).value
    returns = {(target, h): study.labels(prepared['closes'][target], h).to_numpy(float)
               for target in TARGETS for h in HORIZONS}
    scored = []
    for row in rows:
        session, target, horizon = row_key(row)
        location = pd.Timestamp(session)
        require(location in days and target in TARGETS and horizon in HORIZONS, 'SCORE_SCOPE')
        require(row['return_basis'] == prepared['bases'][target] and
                row['price_series_id'] == prepared['feeds'][target], 'SCORE_PRICE_SERIES_CHANGED')
        i = days.get_loc(location)
        end = i+horizon+1
        if end >= len(days):
            continue
        available = int(prepared['times'][target][i:end+1].max())
        if available > read_at:
            continue
        actual = returns[target, horizon][i]
        if np.isfinite(actual):
            scored.append(dict(row, evaluation_session=days[end].date().isoformat(), realized_return=float(actual),
                               outcome_available_at=pd.Timestamp(available, tz='UTC').isoformat()))
    return scored


def summarize(predictions, scored, days):
    summary = []
    for target in TARGETS:
        for horizon in HORIZONS:
            matching = [row for row in scored if row['target'] == target and row['horizon_sessions'] == horizon]
            opened = sum(row['target'] == target and row['horizon_sessions'] == horizon for row in predictions)
            positions = sorted(days.get_loc(pd.Timestamp(row['decision_session'])) for row in matching)
            independent = study.independent_windows(positions, horizon)
            actual, estimate, baseline = (np.array([row[name] for row in matching])
                                          for name in ('realized_return', 'estimate', 'past_mean'))
            summary.append(dict(target=target, horizon_sessions=horizon, forecasts=opened, matured=len(matching),
                pending=opened-len(matching), nonoverlap_windows=independent,
                status='RESEARCH_SCORED' if independent >= MINIMUM_WINDOWS else 'INSUFFICIENT_EVIDENCE',
                direction_accuracy=float(np.mean(np.sign(estimate) == np.sign(actual))) if matching else None,
                mean_direction_accuracy=float(np.mean(np.sign(baseline) == np.sign(actual))) if matching else None,
                always_up_accuracy=float(np.mean(actual > 0)) if matching else None,
                rmse=float(np.sqrt(np.mean((actual-estimate)**2))) if matching else None,
                past_mean_rmse=float(np.sqrt(np.mean((actual-baseline)**2))) if matching else None))
    return summary


def replay(prepared):
    rows = forecast(prepared)
    scored = score(rows, prepared)
    return dict(schema='a4-daily-direction-replay-v1', regime='RESEARCH_ONLY',
                retrospective=True, input_sha256=prepared['input_sha256'], policy_sha256=prepared['policy_sha256'],
                protocol_sha256=digest(encoded(specification())), predictions=rows, scores=scored,
                summary=summarize(rows, scored, prepared['days']))


def daily_journal(prepared, state_root, *, clock=lambda: datetime.now(timezone.utc)):
    """Create one checkpoint per decision session, retaining first observed scores."""
    root = Path(state_root) / 'daily_direction'
    require(not any(path.is_symlink() for path in (root, *root.parents)), 'STATE_SYMLINK')
    days = prepared['days']
    actual_clock = clock()
    session = days[-1].date().isoformat()
    schedule = learning.mcal.get_calendar('NYSE').schedule(start_date=days[-1], end_date=days[-1]+pd.Timedelta(days=14))
    deadline = min(schedule.market_close.iloc[1].to_pydatetime(), prepared['policy_expires_at'])
    require(prepared['anchors'][-1] <= prepared['cutoff'] <= actual_clock < deadline,
            'FORWARD_ENTRY_CLOCK')
    paths = sorted(root.iterdir()) if root.exists() else []
    require(len(paths) <= guarded.MAX_ROWS, 'STATE_BUDGET')
    protocol = digest(encoded(specification()))
    prior, settled = {}, {}
    for path in paths:
        require(not path.is_symlink() and path.is_file() and path.stat().st_size <= MAX_CHECKPOINT_BYTES, 'STATE_FILE')
        item = json.loads(path.read_bytes())
        content_pin = item.pop('content_sha256')
        require(item['schema'] == SCHEMA and content_pin == digest(encoded(item)) and item['protocol_sha256'] == protocol
                and path.name == item['session']+'.json' and item['session'] <= session
                and item['calendar_origin_session'] == days[0].date().isoformat()
                and free.utc(item['created_at']) <= actual_clock, 'STATE_IDENTITY')
        location = pd.Timestamp(item['session'])
        require(location in days, 'STATE_CALENDAR_COVERAGE')
        i = days.get_loc(location)
        next_anchor = prepared['anchors'][i+1] if i+1 < len(days) else None
        require(prepared['anchors'][i] <= free.utc(item['created_at']) and
                (next_anchor is None or free.utc(item['created_at']) < next_anchor-timedelta(minutes=60)),
                'STATE_ENTRY_CLOCK')
        for row in item['predictions']:
            key = row_key(row)
            require(key not in prior and row['decision_session'] == item['session'], 'STATE_DUPLICATE_PREDICTION')
            target = row['target']
            require(target in TARGETS and row['horizon_sessions'] in HORIZONS and
                    row['price_series_id'] == prepared['feeds'][target] and row['return_basis'] == prepared['bases'][target],
                    'STATE_PRICE_SERIES_CHANGED')
            prior[key] = row
        for row in item['new_scores']:
            key = row_key(row)
            require(key in prior and key not in settled and
                    {k:v for k,v in row.items() if k not in {'evaluation_session', 'realized_return', 'outcome_available_at'}} == prior[key]
                    and free.utc(row['outcome_available_at']) <= free.utc(item['created_at']),
                    'STATE_SCORE_LINK')
            settled[key] = row
    path = root / (session+'.json')
    if not path.exists():
        rows = forecast(prepared, only_last=True)
        scores = score([row for key,row in prior.items() if key not in settled], prepared)
        created_at = clock()
        require(actual_clock <= created_at < deadline, 'FORWARD_ENTRY_CLOCK')
        item = dict(schema=SCHEMA, session=session, created_at=created_at.isoformat(), protocol_sha256=protocol,
                    calendar_origin_session=days[0].date().isoformat(),
                    input_sha256=prepared['input_sha256'], policy_sha256=prepared['policy_sha256'],
                    predictions=rows, new_scores=scores)
        raw = encoded(dict(item, content_sha256=digest(encoded(item))))
        require(len(raw) <= MAX_CHECKPOINT_BYTES, 'STATE_SIZE')
        exclusive(path, raw)
        require(path.read_bytes() == raw, 'STATE_READBACK')
        prior.update((row_key(row), row) for row in rows)
        settled.update((row_key(row), row) for row in scores)
    return dict(session=session, checkpoint_sha256=digest(path.read_bytes()),
                current_forecasts=sum(key[0] == session for key in prior),
                summary=summarize(list(prior.values()), list(settled.values()), days))


def main():
    from tools.run_a4_research_cycle import load_learning

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-root', type=Path, required=True)
    parser.add_argument('--policy-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    payload, policy, resolver = load_learning(args.input_root, args.policy_sha256)
    prepared = prepare(payload, policy, digest(encoded(policy)), resolver)
    result = replay(prepared)
    require(not args.output.resolve().is_relative_to(args.input_root.resolve()), 'OUTPUT_OVERLAPS_INPUT')
    exclusive(args.output, encoded(result))


if __name__ == '__main__':
    main()

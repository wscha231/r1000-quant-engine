#!/usr/bin/env python3
"""Historical, purged walk-forward evidence for index technical/macro hypotheses.

Fixed single-feature models are compared with training-only unconditional means.
These are predictive associations, not causal effects or executable portfolios.
Current-vintage index history remains FREE_PROXY; current-only macro rows are
never assigned fictional historical release times.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.macro_history_sources import (REGISTRY, digest, encoded, exclusive,
    load_bundle, registry, require, stamp, utc_now)


def crossing(left, right, up=True):
    valid = left.notna() & right.notna() & left.shift(1).notna() & right.shift(1).notna()
    event = ((left > right) & (left.shift(1) <= right.shift(1))) if up else (
        (left < right) & (left.shift(1) >= right.shift(1)))
    return event.astype(float).where(valid)


def technical_features(close, benchmark):
    features, kinds = {}, {}
    averages = {n: close.rolling(n, min_periods=n).mean() for n in (20, 50, 100, 200)}
    for n, average in averages.items():
        features[f"distance_sma{n}"] = close/average - 1
        features[f"slope_sma{n}_20"] = average/average.shift(20) - 1
    features["above_sma200"] = (close > averages[200]).astype(float).where(averages[200].notna() & close.notna())
    kinds["above_sma200"] = "state"
    for name, up in (("golden_cross_50_200", True), ("death_cross_50_200", False)):
        features[name] = crossing(averages[50], averages[200], up)
        kinds[name] = "event"
    for n in (20, 60):
        # Exclude today's close from the breakout reference; count first entry.
        previous_high = close.shift(1).rolling(n, min_periods=n).max()
        state = (close > previous_high).astype(float).where(previous_high.notna() & close.notna())
        features[f"breakout_{n}"] = ((state == 1) & (state.shift(1) == 0)).astype(float).where(
            state.notna() & state.shift(1).notna())
        kinds[f"breakout_{n}"] = "event"
    for n in (20, 60, 120, 240):
        own = close.pct_change(n, fill_method=None)
        features[f"momentum_{n}"] = own
        features[f"relative_strength_{n}"] = own - benchmark.pct_change(n, fill_method=None)
    return features, kinds


def labels(close, horizon, entry_delay=1):
    """Signal at t close; entry at t+1 close; exit h sessions after entry.

    Preserve the complete exchange-session grid. Gaps invalidate the entire
    holding path instead of compressing trading time or forward filling prices.
    """
    require(horizon > 0 and entry_delay >= 1, "label_window")
    length = horizon + entry_delay + 1
    valid_path = close.notna().rolling(length, min_periods=length).sum().shift(-(length-1)) == length
    return (close.shift(-(horizon+entry_delay))/close.shift(-entry_delay)-1).where(valid_path)


def archive_release_changes(records, sessions, close_times, frequency):
    """One sample on each NEW reference-period release, not one per repeated day.

    Same-day old-period revisions update the baseline before a new period is
    differenced. Revision-only events are retained in the source but not counted
    as independent new releases. Values are changes, not consensus surprises.
    """
    require(all(r["evidence"] == "alfred_date_archive" for r in records), "historical_vintage_required")
    result = pd.Series(np.nan, index=sessions, dtype=float)
    ordered = sorted(records, key=lambda r: (stamp(r["available_at"]), r["observation_date"]))
    state, position, last_latest = {}, 0, None
    for day, cutoff in zip(sessions, close_times):
        while position < len(ordered) and stamp(ordered[position]["available_at"]) <= cutoff:
            record = ordered[position]
            state[record["observation_date"]] = record
            position += 1
        if not state:
            continue
        latest = max(state)
        if latest == last_latest:
            continue
        # A first snapshot exposing many old periods is not many new releases.
        if last_latest is not None and latest > last_latest:
            periods = sorted(state)
            previous = periods[-2] if len(periods) > 1 else None
            if frequency == "monthly":
                contiguous = previous is not None and pd.Period(latest, freq="M")-1 == pd.Period(previous, freq="M")
            elif frequency == "quarterly":
                contiguous = previous is not None and pd.Period(latest, freq="Q")-1 == pd.Period(previous, freq="Q")
            elif frequency == "weekly":
                contiguous = previous is not None and (pd.Timestamp(latest)-pd.Timestamp(previous)).days == 7
            else:
                contiguous = previous is not None and (pd.Timestamp(latest)-pd.Timestamp(previous)).days <= 4
            a, b = state[latest], state.get(previous, {})
            def active(record):
                if record.get("value") is None:
                    return False
                end = record["realtime_end"]
                if end == "9999-12-31":
                    return True
                # Start dates were delayed until end-of-date; interval ends
                # must use the same delay. Never reject an old value early
                # just because a later, not-yet-admitted revision is known.
                expires = datetime.combine(date.fromisoformat(end)+timedelta(days=2),
                                           time(), ZoneInfo("America/New_York"))
                return cutoff < expires
            valid = all(active(r) for r in (a, b))
            if contiguous and valid:
                result.loc[day] = a["value"]-b["value"]
        last_latest = latest
    return result


def independent_windows(positions, horizon):
    count, end = 0, -1
    for position in positions:
        if position > end:
            count += 1
            end = position + horizon
    return count


def hac_association(x, y, lag):
    """OLS sandwich CI with Bartlett HAC lags on the ORIGINAL session grid."""
    valid = np.isfinite(x) & np.isfinite(y)
    if valid.sum() < 5 or np.std(x[valid]) < 1e-12:
        return None
    design = np.column_stack([np.ones(valid.sum()), x[valid]])
    beta = np.linalg.lstsq(design, y[valid], rcond=None)[0]
    inverse = np.linalg.pinv(design.T @ design)
    scores = np.zeros((len(x), 2))
    scores[valid] = design * (y[valid]-design@beta)[:, None]
    meat = scores.T @ scores
    for k in range(1, min(lag, len(x)-1)+1):
        gamma = scores[k:].T @ scores[:-k]
        meat += (1-k/(lag+1)) * (gamma + gamma.T)
    covariance = inverse @ meat @ inverse * valid.sum()/(valid.sum()-2)
    se = np.sqrt(max(0, covariance[1, 1]))
    p = float(2*norm.sf(abs(beta[1]/se))) if se > 1e-15 else None
    return dict(effect=float(beta[1]), low=float(beta[1]-1.96*se), high=float(beta[1]+1.96*se), p=p)


def evaluate(feature, target, horizon, *, kind="continuous", min_train=504,
             initial=756, fold_size=252, entry_delay=1):
    x, y = feature.to_numpy(float), target.to_numpy(float)
    positions = np.arange(len(x))
    forecast, baseline, z_oos = [np.full(len(x), np.nan) for _ in range(3)]
    folds = []
    for start in range(initial, len(x), fold_size):
        train = (positions + entry_delay + horizon < start) & np.isfinite(x) & np.isfinite(y)
        test = (positions >= start) & (positions < start+fold_size) & np.isfinite(x) & np.isfinite(y)
        if train.sum() < min_train or not test.any() or np.std(x[train]) < 1e-12:
            continue
        mean, sd = float(np.mean(x[train])), float(np.std(x[train]))
        z_train, z_test = (x[train]-mean)/sd, (x[test]-mean)/sd
        design = np.column_stack([np.ones(train.sum()), z_train])
        coefficients = np.linalg.lstsq(design, y[train], rcond=None)[0]
        forecast[test] = coefficients[0]+coefficients[1]*z_test
        baseline[test] = np.mean(y[train])
        z_oos[test] = z_test
        folds.append(dict(start=feature.index[start].date().isoformat(), n_train=int(train.sum()),
            n_test=int(test.sum()), last_training_label_position=int(np.flatnonzero(train)[-1]+entry_delay+horizon),
            first_test_position=start, coefficient_per_train_sd=float(coefficients[1]),
            mse_improvement=float(np.mean((y[test]-baseline[test])**2-(y[test]-forecast[test])**2))))
    valid = np.isfinite(forecast)
    n = int(valid.sum())
    result = dict(horizon_sessions=horizon, entry_delay_sessions=entry_delay, sample_kind=kind,
        oos_rows=n, oos_start=feature.index[valid][0].date().isoformat() if n else None,
        oos_end=feature.index[valid][-1].date().isoformat() if n else None,
        nonoverlap_windows=independent_windows(np.flatnonzero(valid & (x == 1)) if kind == "event" else np.flatnonzero(valid), horizon), folds=folds,
        event_count=int(np.sum((x == 1) & valid)) if kind == "event" else None,
        effect_per_training_sd_pp=None, effect_ci95_pp=None, p_value=None,
        oos_mse_improvement=None, oos_direction_accuracy=None, baseline_direction_accuracy=None,
        state_or_event_mean_return_pct=None, non_event_mean_return_pct=None,
        status="INSUFFICIENT_DATA", eligible_for_selector=False)
    if not n:
        return result
    result.update(oos_mse_improvement=float(np.mean((y[valid]-baseline[valid])**2-(y[valid]-forecast[valid])**2)),
        oos_direction_accuracy=float(np.mean((forecast[valid] > 0) == (y[valid] > 0))),
        baseline_direction_accuracy=float(np.mean((baseline[valid] > 0) == (y[valid] > 0))))
    if kind in ("event", "state"):
        positive, negative = valid & (x == 1), valid & (x == 0)
        result["state_or_event_mean_return_pct"] = float(y[positive].mean()*100) if positive.any() else None
        result["non_event_mean_return_pct"] = float(y[negative].mean()*100) if negative.any() else None
    association = hac_association(z_oos, y, horizon+entry_delay)
    if association:
        result.update(effect_per_training_sd_pp=association["effect"]*100,
                      effect_ci95_pp=[association["low"]*100, association["high"]*100])
    enough_events = kind != "event" or result["event_count"] >= 20
    if len(folds) >= 3 and result["nonoverlap_windows"] >= 20 and enough_events and association:
        result.update(p_value=association["p"], status="TESTED_SHADOW")
    else:
        result["status"] = "INSUFFICIENT_INDEPENDENT_EVIDENCE"
    return result


def adjust_family(results):
    """Benjamini-Yekutieli across all declared tests, including failed tests."""
    m = len(results)
    if not m:
        return
    values = [r.get("p_value") if r.get("p_value") is not None else 1.0 for r in results]
    order = np.argsort(values)
    harmonic = sum(1/k for k in range(1, m+1))
    running = 1.0
    for rank in range(m, 0, -1):
        index = int(order[rank-1])
        running = min(running, values[index]*m*harmonic/rank)
        row = results[index]
        row["family_q_value"] = running if row.get("p_value") is not None else None
        if row["status"] == "TESTED_SHADOW":
            improvements = [f["mse_improvement"] > 0 for f in row["folds"]]
            row["status"] = ("SHADOW_CANDIDATE" if running <= .05 and row["oos_mse_improvement"] > 0
                and np.mean(improvements) >= .6 else "NO_INCREMENTAL_EVIDENCE")


def study(store, receipt_path, as_of, macro_receipts=()):
    import pandas_market_calendars as mcal  # Optional until actual calendar use.
    receipt, all_records = load_bundle(store, receipt_path)
    require(stamp(as_of) >= stamp(receipt["created_at"]), "as_of_before_collection")
    input_hashes = [digest(Path(receipt_path).read_bytes())]
    for path in macro_receipts:
        extra, records = load_bundle(store, path)
        require(extra["mode"] == "alfred" and stamp(as_of) >= stamp(extra["created_at"]), "macro_receipt_mode")
        require(extra["requested_start"] <= receipt["requested_start"] and
                extra["requested_through"] >= receipt["requested_through"], "macro_receipt_window")
        for series, rows in records.items():
            require(series not in ("SP500", "NASDAQCOM", "NASDAQ100"), "macro_receipt_price_override")
            all_records[series] = rows
        input_hashes.append(digest(Path(path).read_bytes()))
    schedule = mcal.get_calendar("NYSE").schedule(start_date=receipt["requested_start"],
        end_date=min(stamp(as_of).date().isoformat(), receipt["requested_through"]))
    schedule = schedule[schedule["market_close"] <= stamp(as_of)]
    sessions = pd.DatetimeIndex(schedule.index).tz_localize(None)
    close_times = [t.to_pydatetime() for t in schedule["market_close"]]
    specs = {s["id"]: s for s in registry()["series"]}
    prices, off_calendar = {}, {}
    for sid in ("SP500", "NASDAQCOM", "NASDAQ100"):
        records = all_records.get(sid)
        if records:
            require(all(r["evidence"] == "current_only" for r in records), "price_lane_requires_current_graph")
            prices[sid] = pd.Series({pd.Timestamp(r["observation_date"]): r["value"] for r in records}, dtype=float).reindex(sessions)
            off_calendar[sid] = sorted(r["observation_date"] for r in records
                                       if pd.Timestamp(r["observation_date"]) not in sessions)
            require((prices[sid].dropna() > 0).all(), "nonpositive_index")
    results, gaps, coverage = [], [], {}
    for sid, close in prices.items():
        reference = "SP500" if sid != "SP500" else "NASDAQCOM"
        benchmark = prices.get(reference, pd.Series(np.nan, index=sessions))
        features, kinds = technical_features(close, benchmark)
        for macro, records in all_records.items():
            if specs[macro]["group"] == "price":
                continue
            if all(r["evidence"] == "alfred_date_archive" for r in records):
                features["macro_change_"+macro] = archive_release_changes(
                    records, sessions, close_times, specs[macro]["frequency"])
                kinds["macro_change_"+macro] = "release"
        available = close.dropna()
        coverage[sid] = dict(rows=len(available), first=str(available.index.min().date()),
            last=str(available.index.max().date()), missing_sessions_inside_history=int(
                close.loc[available.index.min():available.index.max()].isna().sum()),
            calendar_excluded_source_dates=off_calendar[sid],
            requested_last_session=str(sessions[-1].date()),
            missing_tail_sessions=int((sessions > available.index.max()).sum()),
            return_basis="PRICE_INDEX_EXCLUDING_DIVIDENDS_AND_COSTS", evidence="FREE_PROXY")
        for name, feature in features.items():
            kind = kinds.get(name, "continuous")
            for horizon in registry()["study"]["horizons"]:
                row = evaluate(feature, labels(close, horizon), horizon, kind=kind,
                    min_train=60 if kind == "release" else 504)
                row.update(asset=sid, feature=name, benchmark=reference,
                    feature_evidence="ALFRED_DATE_ARCHIVE" if kind == "release" else "FREE_PROXY")
                results.append(row)
    for sid, records in all_records.items():
        if specs[sid]["group"] != "price" and any(r["evidence"] == "current_only" for r in records):
            gaps.append(dict(series=sid, reason="CURRENT_VINTAGE_NOT_HISTORICAL_RELEASE_EVIDENCE"))
    adjust_family(results)
    try:
        code_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        code_sha = None
    code_hashes = {name: digest((ROOT/name).read_bytes()) for name in (
        "tools/macro_history_sources.py", "tools/macro_technical_study.py", "docs/macro_indicator_registry.json")}
    return dict(schema="macro-technical-evidence-v1", as_of=as_of, code_sha=code_sha,
        code_file_sha256=code_hashes, input_receipt_sha256=digest(encoded(input_hashes)),
        calendar_sha256=digest(schedule.to_csv().encode()), coverage=coverage, blocked_macro=gaps,
        tests_declared=len(results), results=results, data_kind="REAL_PROVIDER_DATA",
        historical_pit_certified=False, full_portfolio_backtest_executed=False,
        causal_effect_identified=False, model_promoted=False, eligible_for_selector=False,
        durable_remote_verified=False, evaluation_scope="single_feature_purged_walk_forward",
        multiple_testing_scope="current_run_only; canonical historical experiment census still required")


def compare(previous, current):
    require(previous["schema"] == current["schema"], "comparison_schema")
    old = {(r["asset"], r["feature"], r["horizon_sessions"]): r for r in previous["results"]}
    same_code = previous["code_file_sha256"] == current["code_file_sha256"]
    same_input = previous["input_receipt_sha256"] == current["input_receipt_sha256"]
    changes = []
    for row in current["results"]:
        prior = old.get((row["asset"], row["feature"], row["horizon_sessions"]))
        if prior:
            a, b = prior["effect_per_training_sd_pp"], row["effect_per_training_sd_pp"]
            changes.append(dict(asset=row["asset"], feature=row["feature"], horizon_sessions=row["horizon_sessions"],
                old_status=prior["status"], new_status=row["status"],
                effect_change_pp=b-a if a is not None and b is not None else None,
                old_oos_rows=prior["oos_rows"], new_oos_rows=row["oos_rows"]))
    return dict(same_code=same_code, same_receipt=same_input,
        attribution="NO_CHANGE" if same_code and same_input else "INPUT_RECEIPT_CHANGED_CHECK_VALUES" if same_code else "CODE_AND_POSSIBLY_DATA_CHANGED",
        structural_break_proven=False, changes=changes)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--store", required=True)
    p.add_argument("--receipt", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--previous")
    p.add_argument("--macro-receipt", action="append", default=[])
    args = p.parse_args()
    result = study(args.store, args.receipt, utc_now(), args.macro_receipt)
    if args.previous:
        result["comparison"] = compare(json.loads(Path(args.previous).read_bytes()), result)
    exclusive(args.output, encoded(result))
    print(json.dumps({"tests_declared":result["tests_declared"], "coverage":result["coverage"],
        "macro_blocked":len(result["blocked_macro"]), "selector_enabled":False}))
    return 0 if result["coverage"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

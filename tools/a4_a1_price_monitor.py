"""Read a pinned A1 snapshot for the existing A4 scheduled workflow."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import re
import tempfile

import pandas as pd
import pandas_market_calendars as mcal

from tools import alpaca_sip_private_backfill_v1 as capture
from tools import build_run287_chameleon_macro_inputs as native
from tools import run287_etf_rotation as rotation
from tools.twelve_private_capture import OwnerDrive, decode, digest, encoded, require

BASIS = "ALPACA_SIP_SPLIT_ADJUSTED_USD"
BENCHMARKS = ("SPY", "QQQ")
BREADTH_BUNDLE = "a4-a1-breadth-bundle-v1"
PRICE_BUNDLE = "a4-a1-price-bundle-v1"
COHORT_SIZE = 606
HISTORY = 252
MAX_BUNDLE = 8_000_000
BREADTH = ("pct_above_ma50", "pct_above_ma200", "new_high_minus_new_low",
           "adv_decl_dollar_volume_ratio")
SHA = re.compile(r"[0-9a-f]{64}")


def read_ref(drive, parent, ref, limit):
    require(isinstance(ref, dict) and set(ref) == {"file_id", "sha256", "bytes"}
            and isinstance(ref["sha256"], str) and SHA.fullmatch(ref["sha256"])
            and type(ref["bytes"]) is int and 0 < ref["bytes"] <= limit, "A4_A1_REFERENCE")
    drive.check(ref["file_id"], parent, folder=False)
    raw = drive.read(ref["file_id"], ref["bytes"])
    require(len(raw) == ref["bytes"] and digest(raw) == ref["sha256"], "A4_A1_HASH")
    return raw


def frames(bundle):
    schema = bundle.get("schema")
    require(schema in (PRICE_BUNDLE, BREADTH_BUNDLE) and bundle.get("price_basis") == BASIS,
            "A4_A1_BASIS")
    benchmarks = set(BENCHMARKS) if schema == PRICE_BUNDLE else set()
    days, prices = bundle["sessions"], bundle["prices"]
    require(isinstance(days, list) and len(days) == HISTORY and days == sorted(set(days))
            and isinstance(prices, dict) and set(BENCHMARKS).intersection(prices) == benchmarks
            and len(prices) == COHORT_SIZE + len(benchmarks), "A4_A1_COHORT_OR_SESSIONS")
    for ticker, columns in prices.items():
        require(re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,14}", ticker)
                and set(columns) == {"close", "raw_close", "volume"}, "A4_A1_COLUMNS")
        for key, vals in columns.items():
            require(isinstance(vals, list) and len(vals) == HISTORY, "A4_A1_BAR_COUNT")
            require(all(v is None or (type(v) in (float, int) and math.isfinite(v)
                and (v >= 0 if key == "volume" else v > 0)) for v in vals), "A4_A1_BAR")
            if schema == BREADTH_BUNDLE:
                require(vals[-1] is not None, "A4_A1_BREADTH_LATEST_MISSING")
    index = pd.DatetimeIndex(days)
    require(list(index.strftime("%Y-%m-%d")) == days, "A4_A1_DATE_FORMAT")
    return {key: pd.DataFrame({s: cols[key] for s, cols in prices.items()}, index=index, dtype=float)
            for key in ("close", "raw_close", "volume")}


def benchmark_report(close, calendar):
    expected = calendar[-1]
    positions = {day: pos for pos, day in enumerate(calendar)}
    latest = {ticker: close[ticker].last_valid_index() for ticker in BENCHMARKS}
    lag = {ticker: None if day is None else positions[expected] - positions[day]
           for ticker, day in latest.items()}
    lagging = [ticker for ticker, day in latest.items()
               if day is not None and all(other is not None for other in latest.values())
               and day < max(latest.values())]
    common_dates = close.dropna().index
    common = common_dates[-1] if len(common_dates) else None
    status = ("NO_COMMON_SESSION" if common is None else "ONE_SIDE_DELAYED" if lagging
              else "CURRENT_COMMON_SESSION" if common == expected else "DELAYED_COMMON_SESSION")
    rs = {str(period): None for period in rotation.WINDOWS}
    window = ()
    if common is not None:
        end = positions[common] + 1
        window = tuple(d.date().isoformat() for d in calendar[max(0, end - rotation.POINTS):end])
        matched = {ticker: rotation.exact_closes(zip(close.index.strftime("%Y-%m-%d"), close[ticker]),
                    window[-(max(rotation.WINDOWS) + 1):])[0] for ticker in BENCHMARKS}
        if all(v is not None and len(v) > max(rotation.WINDOWS) for v in matched.values()):
            rs = rotation.relative(matched["QQQ"], matched["SPY"])
    show = lambda day: None if day is None else day.date().isoformat()
    return dict(status=status, expected_session=show(expected), common_session=show(common),
                latest_session_by_symbol={k: show(v) for k, v in latest.items()},
                lag_sessions=lag, lagging_symbols=lagging, relative_strength_qqq_vs_spy=rs,
                relative_strength_window_status="COMPLETE" if all(v is not None for v in rs.values()) else "WINDOW_GAP",
                common_sessions_in_window=len(set(window) & set(common_dates.strftime("%Y-%m-%d"))))


def evaluate(bundle, source, cutoff, *, verify_lag=False):
    require(cutoff.utcoffset() is not None, "A4_A1_CUTOFF")
    data = frames(bundle)
    close = data["close"]
    source_day = close.index[-1]
    cutoff = cutoff.astimezone(timezone.utc)
    available = datetime.fromisoformat(source["completed_at"].replace("Z", "+00:00"))
    require(available.utcoffset() is not None and available <= cutoff and source["state"] == "COMPLETE"
            and source["session"] == source_day.date().isoformat()
            and source["run_id"] == bundle["a1_run_id"]
            and source["coverage_updates"] == dict.fromkeys(close.columns, source["session"]),
            "A4_A1_CHECKPOINT_SCOPE")
    settled, _ = rotation.session_window(cutoff)
    schedule = mcal.get_calendar("NYSE").schedule(start_date=close.index[0], end_date=settled[-1])
    calendar = pd.DatetimeIndex(schedule.index)
    require(len(calendar) >= HISTORY and calendar[calendar <= source_day].equals(close.index),
            "A4_A1_NYSE_SESSIONS")
    equities = sorted(set(close.columns) - set(BENCHMARKS))
    contract = decode(native.DEFAULT_CONTRACT.read_bytes())
    minimum_symbols = contract["history"]["minimum_breadth_symbols"]
    values, counts = native.compute_universe_components(
        close[equities], data["volume"][equities], minimum_symbols, data["raw_close"][equities])
    values_at_close = {name: None if pd.isna(values[name].iloc[-1]) else float(values[name].iloc[-1])
                       for name in BREADTH}
    breadth = dict(status="CURRENT" if source_day == calendar[-1] else "DELAYED",
                   as_of_session=source["session"], cohort_size=len(equities), values=values_at_close,
                   valid_symbols={name: int(counts[name].iloc[-1]) for name in BREADTH})
    report = dict(schema="a4-a1-price-report-v1", purpose="PRIVATE_RESEARCH_ONLY",
                  a1_run_id=source["run_id"], a1_checkpoint_sha256=bundle["a1_checkpoint_sha256"],
                  verified_source_readback_sha256=bundle["readback_sha256"], cutoff=cutoff.isoformat(),
                  price_basis=BASIS, breadth=breadth)
    if bundle["schema"] == BREADTH_BUNDLE:
        breadth.update(expected_session=calendar[-1].date().isoformat(),
                       lag_sessions=len(calendar) - 1 - calendar.get_loc(source_day),
                       coverage_ready=all(count >= minimum_symbols for count in breadth["valid_symbols"].values()))
        return dict(report, schema="a4-a1-breadth-report-v1", benchmark=None,
                    native_risk_admitted=False, historical_pit_certified=False)
    pair = benchmark_report(close[list(BENCHMARKS)], calendar)
    report["benchmark"] = pair
    if verify_lag:
        require(pair["common_session"] == source["session"]
                and pair["latest_session_by_symbol"] == dict.fromkeys(BENCHMARKS, source["session"]),
                "A4_A1_LAG_FIXTURE_NEEDS_COMMON_CLOSE")
        fixture = close[list(BENCHMARKS)].copy()
        fixture.loc[source_day, "QQQ"] = float("nan")
        observed = benchmark_report(fixture, calendar)
        require(observed["status"] == "ONE_SIDE_DELAYED" and observed["lagging_symbols"] == ["QQQ"]
                and observed["common_session"] == close.index[-2].date().isoformat()
                and observed["lag_sessions"]["QQQ"] == observed["lag_sessions"]["SPY"] + 1
                and all(value is not None for value in observed["relative_strength_qqq_vs_spy"].values()),
                "A4_A1_LAG_VERIFICATION")
        report["isolated_lag_check"] = {k: observed[k] for k in
            ("status", "expected_session", "common_session", "lagging_symbols", "lag_sessions")}
    return report


def run(drive, scope, pin, *, cutoff, run_id, attempt, code_sha, verify_lag=False):
    require(SHA.fullmatch(pin) and scope["bundle"]["sha256"] == pin, "A4_A1_BUNDLE_PIN")
    require(digest(drive.owner.encode()) == scope["owner_sha256"], "A4_A1_OWNER")
    require(scope["analysis_folder"] != scope["source_journal"], "A4_A1_FOLDER_SCOPE")
    drive.check(scope["analysis_folder"], drive.root_id)
    drive.check(scope["source_journal"], drive.root_id)
    bundle = decode(read_ref(drive, scope["analysis_folder"], scope["bundle"], MAX_BUNDLE))
    source = decode(read_ref(drive, scope["source_journal"], scope["checkpoint"], 1_000_000))
    require(bundle["a1_checkpoint_sha256"] == scope["checkpoint"]["sha256"], "A4_A1_CHECKPOINT_PIN")
    report = evaluate(bundle, source, cutoff, verify_lag=verify_lag)
    report.update(bundle_sha256=pin, run_id=run_id, attempt=attempt, code_sha=code_sha)
    raw = encoded(report)
    ref = capture.persist_object(drive, scope["analysis_folder"], raw, ".json")
    require(read_ref(drive, scope["analysis_folder"], ref, 256_000) == raw, "A4_A1_REPORT_READBACK")
    receipt = dict(status="PRIVATE_REPORT_READBACK_VERIFIED", run_id=run_id, attempt=attempt,
                code_sha=code_sha, report_sha256=ref["sha256"], bundle_sha256=pin,
                source_checkpoint_sha256=scope["checkpoint"]["sha256"],
                breadth_symbols=report["breadth"]["valid_symbols"], breadth_status=report["breadth"]["status"],
                breadth_session=report["breadth"]["as_of_session"])
    pair = report["benchmark"]
    if pair is None:
        breadth = report["breadth"]
        return dict(receipt, schema="a4-a1-breadth-receipt-v1", price_basis=report["price_basis"],
                    expected_session=breadth["expected_session"], lag_sessions=breadth["lag_sessions"],
                    coverage_ready=breadth["coverage_ready"], benchmark=None)
    return dict(receipt, benchmark={key: pair[key] for key in (
                    "status", "expected_session", "common_session", "lag_sessions", "lagging_symbols",
                    "common_sessions_in_window", "relative_strength_window_status")},
                relative_strength_horizons=[int(key) for key, value in
                    pair["relative_strength_qqq_vs_spy"].items() if value is not None],
                isolated_lag_check=report.get("isolated_lag_check"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--verify-lag", action="store_true")
    args = parser.parse_args()
    try:
        scope = decode(os.environ["A4_A1_PRICE_SCOPE"].encode())
        with tempfile.TemporaryDirectory(prefix="a4-a1-price-") as temp:
            drive = OwnerDrive(scope["root_folder"], temp)
            result = run(drive, scope, os.environ["A4_A1_PRICE_BUNDLE_SHA256"],
                         cutoff=datetime.now(timezone.utc), run_id=os.environ["GITHUB_RUN_ID"],
                         attempt=os.environ["GITHUB_RUN_ATTEMPT"], code_sha=os.environ["GITHUB_SHA"],
                         verify_lag=args.verify_lag)
        args.receipt.write_bytes(encoded(result))
        print(encoded(result).decode().strip())
    except (ValueError, OSError, KeyError, TypeError, OverflowError) as exc:
        reason = str(exc)
        if not re.fullmatch(r"(A4_A1|DRIVE)_[A-Z_]+", reason):
            reason = "A4_A1_PRICE_VERIFICATION_BLOCKED"
        raise SystemExit(reason) from None


if __name__ == "__main__":
    main()

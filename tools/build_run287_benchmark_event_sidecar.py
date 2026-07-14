#!/usr/bin/env python3
"""Build a bounded current benchmark/live-event sidecar for Run287.

The frozen Phase 4 schema uses the registered FRED SP500 benchmark rather than
an SPY substitution. This tool refreshes at most that single official series,
copies the already-pinned macro caches into an isolated engine directory, and
reuses the engine's benchmark and live-event formulas. It never scores a
security or runs a selector, backtest, fullrun, production, or trading path.

FRED graph CSV is the current vintage. The output is current-decision-only and
cannot be used as historical point-in-time evidence.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_config import (  # noqa: E402
    EngineConfig,
    LIVE_EVENT_ALERT_COLUMNS,
    MACRO_FRED_SERIES,
)
from r1000_helpers import get_paths  # noqa: E402
import r1000_pipeline as pipeline  # noqa: E402
from tools.build_run287_macro_sidecar import (  # noqa: E402
    clean_date,
    fetch_fred_csv,
    fingerprint,
    fred_available_from,
    market_close_final_utc,
    normalize_fred_frame,
    read_json,
    repo_path,
    sha256_bytes,
    sha256_file,
    utc_timestamp,
    write_json,
)


SCHEMA_VERSION = "run287-current-benchmark-event-sidecar-v1"
DEFAULT_MACRO_MANIFEST = (
    "outputs/run287_macro_sidecar_20260711_commit_0d97c720/manifest.json"
)
DEFAULT_BENCHMARK_SOURCE = (
    "G:/내 드라이브/r1000_top30_institutional/cache_macro/"
    "fred_benchmark_sp500_SP500.parquet"
)
DEFAULT_OUTPUT = "outputs/run287_benchmark_event_sidecar_20260711"


def git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def directory_hashes(directory: Path) -> dict[str, str]:
    if not directory.is_dir():
        return {}
    return {
        str(path.relative_to(directory)): sha256_file(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def copy_cache_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.glob("*")):
        if path.is_file():
            shutil.copy2(path, destination / path.name)


def read_benchmark_source(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame(columns=["date", "value"])
    try:
        if path.suffix.lower() == ".parquet":
            return normalize_fred_frame(pd.read_parquet(path))
        return normalize_fred_frame(pd.read_csv(path))
    except Exception:
        return pd.DataFrame(columns=["date", "value"])


def latest_available_benchmark_session(
    valuation_date: str, decision_time: pd.Timestamp
) -> pd.Timestamp:
    valuation = pd.Timestamp(valuation_date).normalize()
    try:
        import pandas_market_calendars as mcal

        schedule = mcal.get_calendar("NYSE").schedule(
            start_date=(valuation - pd.Timedelta(days=14)).date().isoformat(),
            end_date=valuation.date().isoformat(),
        )
        candidates = pd.Series(pd.to_datetime(schedule.index).tz_localize(None))
    except ImportError:
        candidates = pd.Series(pd.bdate_range(valuation - pd.Timedelta(days=14), valuation))
    available = fred_available_from("vix", candidates)
    eligible = candidates[pd.to_datetime(available, errors="coerce", utc=True) <= decision_time]
    if eligible.empty:
        raise ValueError("no benchmark session is available by decision time")
    return pd.Timestamp(eligible.max()).normalize()


def source_sufficient(
    frame: pd.DataFrame, valuation_date: str, decision_time: pd.Timestamp
) -> bool:
    if frame.empty:
        return False
    latest = pd.to_datetime(frame["date"], errors="coerce").max()
    if pd.isna(latest):
        return False
    return pd.Timestamp(latest).normalize() >= latest_available_benchmark_session(
        valuation_date, decision_time
    )


def verify_manifest_output(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    key: str,
) -> dict[str, Any]:
    record = (manifest.get("outputs") or {}).get(key) or {}
    path = Path(str(record.get("path") or ""))
    if path and not path.is_absolute():
        path = manifest_path.parent / path
    actual = fingerprint(path)
    actual["expected_sha256"] = record.get("sha256")
    actual["hash_matches"] = bool(
        actual.get("exists")
        and record.get("sha256")
        and actual.get("sha256") == record.get("sha256")
    )
    return actual


def blocked_payload(
    output_dir: Path,
    *,
    status: str,
    blockers: list[str],
    decision_time: pd.Timestamp,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "blockers": blockers,
        "decision_time_utc": decision_time.isoformat(),
        "research_only": True,
        "current_decision_only": True,
        "benchmark_event_merge_allowed": False,
        "decision_ranking_allowed": False,
        "historical_backtest_acceptance_allowed": False,
        "fullrun_executed": False,
        "selector_executed": False,
        "backtest_executed": False,
        "network_requests_executed": 0,
        "source_inputs_mutated": False,
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def build(args: argparse.Namespace, *, observed_at_utc: str | None = None) -> dict[str, Any]:
    macro_manifest_path = repo_path(args.macro_manifest)
    benchmark_source_path = repo_path(args.benchmark_source)
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    decision_time = utc_timestamp(
        observed_at_utc
        or getattr(args, "decision_time_utc", "")
        or datetime.now(timezone.utc).isoformat()
    )
    if not macro_manifest_path.is_file():
        return blocked_payload(
            output_dir,
            status="BLOCKED_BENCHMARK_MACRO_INPUT",
            blockers=["macro_manifest_missing"],
            decision_time=decision_time,
        )

    macro = read_json(macro_manifest_path)
    valuation_date = clean_date(macro.get("valuation_close_date"))
    macro_available_from = pd.to_datetime(
        macro.get("macro_available_from"), errors="coerce", utc=True
    )
    macro_checks = {
        "ready_status": macro.get("status") == "READY_CONSERVATIVE_MACRO_SIDECAR",
        "no_blockers": not bool(macro.get("blockers")),
        "valuation_date": bool(valuation_date),
        "available_by_decision": bool(
            pd.notna(macro_available_from) and macro_available_from <= decision_time
        ),
        "source_inputs_unchanged": macro.get("source_inputs_mutated") is False,
        "no_fullrun": macro.get("fullrun_executed") is False,
        "no_selector": macro.get("selector_executed") is False,
        "no_backtest": macro.get("backtest_executed") is False,
        "macro_current_hash": verify_manifest_output(
            macro_manifest_path, macro, "macro_current"
        ).get("hash_matches")
        is True,
    }
    if not all(macro_checks.values()):
        return blocked_payload(
            output_dir,
            status="BLOCKED_BENCHMARK_MACRO_INPUT",
            blockers=[key for key, value in macro_checks.items() if not value],
            decision_time=decision_time,
        )

    source_base = macro_manifest_path.parent / "inputs" / "isolated_engine"
    source_price_cache = source_base / "cache_prices"
    source_macro_cache = source_base / "cache_macro"
    source_price_hashes_before = directory_hashes(source_price_cache)
    source_macro_hashes_before = directory_hashes(source_macro_cache)
    if not source_price_hashes_before or not source_macro_hashes_before:
        return blocked_payload(
            output_dir,
            status="BLOCKED_BENCHMARK_MACRO_INPUT",
            blockers=["pinned_macro_isolated_cache_missing"],
            decision_time=decision_time,
        )

    isolated_base = output_dir / "inputs" / "isolated_engine"
    destination_price_cache = isolated_base / "cache_prices"
    destination_macro_cache = isolated_base / "cache_macro"
    copy_cache_tree(source_price_cache, destination_price_cache)
    copy_cache_tree(source_macro_cache, destination_macro_cache)

    benchmark_source_hash_before = (
        sha256_file(benchmark_source_path) if benchmark_source_path.is_file() else ""
    )
    frame = read_benchmark_source(benchmark_source_path)
    frame["available_from"] = fred_available_from("vix", frame["date"])
    usable = frame[
        (pd.to_datetime(frame["date"], errors="coerce") <= pd.Timestamp(valuation_date))
        & (
            pd.to_datetime(frame["available_from"], errors="coerce", utc=True)
            <= decision_time
        )
    ].copy()
    raw_path = output_dir / "inputs" / "raw_fred" / "SP500.csv"
    raw_path.parent.mkdir(parents=True)
    raw_sha = ""
    source_mode = "existing_cache"
    network_requests = 0
    if not source_sufficient(usable, valuation_date, decision_time) and not bool(args.offline):
        if int(args.max_network_requests) < 1:
            return blocked_payload(
                output_dir,
                status="BLOCKED_BENCHMARK_REQUEST_BUDGET",
                blockers=["benchmark_refresh_requires_one_request"],
                decision_time=decision_time,
            )
        raw, fetched = fetch_fred_csv(
            MACRO_FRED_SERIES["sp500"], int(args.http_timeout_seconds)
        )
        raw_path.write_bytes(raw)
        raw_sha = sha256_bytes(raw)
        frame = fetched
        frame["available_from"] = fred_available_from("vix", frame["date"])
        usable = frame[
            (pd.to_datetime(frame["date"], errors="coerce") <= pd.Timestamp(valuation_date))
            & (
                pd.to_datetime(frame["available_from"], errors="coerce", utc=True)
                <= decision_time
            )
        ].copy()
        source_mode = "official_fred_graph_csv"
        network_requests = 1

    if not source_sufficient(usable, valuation_date, decision_time):
        payload = blocked_payload(
            output_dir,
            status="BLOCKED_BENCHMARK_COMPONENT_COVERAGE",
            blockers=["fred_sp500_missing_or_stale"],
            decision_time=decision_time,
        )
        payload["network_requests_executed"] = network_requests
        write_json(output_dir / "manifest.json", payload)
        return payload

    benchmark_cache_path = (
        destination_macro_cache
        / f"fred_benchmark_sp500_{MACRO_FRED_SERIES['sp500']}.parquet"
    )
    usable[["date", "value"]].to_parquet(benchmark_cache_path, index=False)
    latest_observation_date = clean_date(usable["date"].max())
    latest_available_from = pd.to_datetime(
        usable["available_from"], errors="coerce", utc=True
    ).max()

    cfg = EngineConfig()
    cfg.base_dir = str(isolated_base)
    cfg.start_date = (
        pd.Timestamp(valuation_date) - pd.DateOffset(years=3)
    ).date().isoformat()
    cfg.end_date = valuation_date
    cfg.macro_refresh_days = 99999
    cfg.fred_api_key = ""
    cfg.yf_retry = 0
    cfg.yf_sleep = 0.0
    paths = get_paths(cfg)
    original_ensure = pipeline.ensure_prices_cached_incremental
    pipeline.ensure_prices_cached_incremental = lambda *_args, **_kwargs: None
    try:
        benchmark_table = pipeline.build_benchmark_feature_table(cfg, paths)
        live_event_table = pipeline.build_live_event_alert_table(cfg, paths)
    finally:
        pipeline.ensure_prices_cached_incremental = original_ensure

    benchmark_table["bench_date"] = pd.to_datetime(
        benchmark_table["bench_date"], errors="coerce"
    )
    benchmark_eligible = benchmark_table[
        benchmark_table["bench_date"] <= pd.Timestamp(valuation_date)
    ]
    live_event_table["event_date"] = pd.to_datetime(
        live_event_table["event_date"], errors="coerce"
    )
    live_eligible = live_event_table[
        live_event_table["event_date"] <= pd.Timestamp(valuation_date)
    ]
    if benchmark_eligible.empty or live_eligible.empty:
        return blocked_payload(
            output_dir,
            status="BLOCKED_BENCHMARK_ENGINE_OUTPUT",
            blockers=[
                *( ["empty_benchmark_table"] if benchmark_eligible.empty else [] ),
                *( ["empty_live_event_table"] if live_eligible.empty else [] ),
            ],
            decision_time=decision_time,
        )

    benchmark_current = benchmark_eligible.sort_values("bench_date").tail(1).copy()
    live_event_current = live_eligible.sort_values("event_date").tail(1).copy()
    benchmark_current["valuation_close_date"] = valuation_date
    benchmark_current["benchmark_observation_date"] = latest_observation_date
    benchmark_current["benchmark_available_from"] = latest_available_from.isoformat()
    live_event_current["valuation_close_date"] = valuation_date
    global_available_from = max(
        pd.Timestamp(macro_available_from),
        pd.Timestamp(latest_available_from),
        market_close_final_utc(valuation_date),
    )
    live_event_current["benchmark_event_available_from"] = global_available_from.isoformat()

    # The global sidecar supplies benchmark-only values. Stock-relative
    # rs_benchmark_* and dd_gap_benchmark are calculated after ticker features
    # join the benchmark in the feature-frame builder.
    critical_benchmark = [
        "bench_ret_1m",
        "bench_ret_3m",
        "bench_ret_6m",
        "bench_ret_12m",
        "bench_dd_1y",
        "bench_above_ma200",
    ]
    critical_live = list(LIVE_EVENT_ALERT_COLUMNS)
    missing_benchmark = [
        column
        for column in critical_benchmark
        if column not in benchmark_current.columns
        or not math.isfinite(
            float(pd.to_numeric(benchmark_current.iloc[0][column], errors="coerce"))
        )
    ]
    missing_live = [
        column
        for column in critical_live
        if column not in live_event_current.columns
        or not math.isfinite(
            float(pd.to_numeric(live_event_current.iloc[0][column], errors="coerce"))
        )
    ]
    final_blockers = [
        *[f"critical_benchmark_missing:{column}" for column in missing_benchmark],
        *[f"critical_live_event_missing:{column}" for column in missing_live],
    ]
    if global_available_from > decision_time:
        final_blockers.append("benchmark_event_available_after_decision")
    if network_requests > int(args.max_network_requests):
        final_blockers.append("network_request_budget_exceeded")

    source_price_unchanged = source_price_hashes_before == directory_hashes(
        source_price_cache
    )
    source_macro_unchanged = source_macro_hashes_before == directory_hashes(
        source_macro_cache
    )
    benchmark_source_hash_after = (
        sha256_file(benchmark_source_path) if benchmark_source_path.is_file() else ""
    )
    benchmark_source_unchanged = (
        benchmark_source_hash_before == benchmark_source_hash_after
    )
    if not (source_price_unchanged and source_macro_unchanged and benchmark_source_unchanged):
        final_blockers.append("source_cache_mutated")

    benchmark_path = output_dir / "benchmark_current.csv"
    live_event_path = output_dir / "live_event_current.csv"
    benchmark_current.to_csv(benchmark_path, index=False)
    live_event_current.to_csv(live_event_path, index=False)
    status = (
        "READY_CONSERVATIVE_BENCHMARK_EVENT_SIDECAR"
        if not final_blockers
        else "BLOCKED_BENCHMARK_EVENT_CONTRACT"
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "blockers": final_blockers,
        "valuation_close_date": valuation_date,
        "decision_time_utc": decision_time.isoformat(),
        "benchmark_observation_date": latest_observation_date,
        "benchmark_available_from": latest_available_from.isoformat(),
        "benchmark_event_available_from": global_available_from.isoformat(),
        "research_only": True,
        "current_decision_only": True,
        "benchmark_event_merge_allowed": not final_blockers,
        "decision_ranking_allowed": False,
        "fred_vintage_clean": False,
        "historical_backtest_acceptance_allowed": False,
        "fullrun_executed": False,
        "selector_executed": False,
        "backtest_executed": False,
        "network_requests_executed": network_requests,
        "network_request_budget": int(args.max_network_requests),
        "source_inputs_mutated": not (
            source_price_unchanged
            and source_macro_unchanged
            and benchmark_source_unchanged
        ),
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "coverage": {
            "benchmark_required_count": len(critical_benchmark),
            "benchmark_finite_count": len(critical_benchmark) - len(missing_benchmark),
            "live_event_required_count": len(critical_live),
            "live_event_finite_count": len(critical_live) - len(missing_live),
            "future_available_row_count": int(global_available_from > decision_time),
        },
        "benchmark_source": {
            "series_id": MACRO_FRED_SERIES["sp500"],
            "source_mode": source_mode,
            "source_path": str(benchmark_source_path),
            "source_sha256": benchmark_source_hash_before,
            "raw_response": fingerprint(raw_path),
            "raw_response_sha256": raw_sha,
            "latest_usable_observation_date": latest_observation_date,
            "availability_policy": "observation_plus_one_business_day_end_utc",
            "availability_exact": False,
            "availability_conservative": True,
            "vintage_clean": False,
        },
        "source_inputs": {
            "macro_manifest": fingerprint(macro_manifest_path),
            "source_isolated_price_cache": str(source_price_cache),
            "source_isolated_macro_cache": str(source_macro_cache),
        },
        "source_immutability": {
            "macro_price_cache_unchanged": source_price_unchanged,
            "macro_fred_cache_unchanged": source_macro_unchanged,
            "benchmark_source_cache_unchanged": benchmark_source_unchanged,
        },
        "outputs": {
            "benchmark_current": {
                **fingerprint(benchmark_path),
                "row_count": int(len(benchmark_current)),
            },
            "live_event_current": {
                **fingerprint(live_event_path),
                "row_count": int(len(live_event_current)),
            },
            "isolated_benchmark_cache": fingerprint(benchmark_cache_path),
            "isolated_live_event_table": fingerprint(
                isolated_base / "feature_store" / "live_event_alert_latest.parquet"
            ),
        },
        "code": {
            "git_head": git_head(),
            "builder": fingerprint(Path(__file__).resolve()),
        },
    }
    write_json(output_dir / "manifest.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def render_report(payload: Mapping[str, Any]) -> str:
    coverage = payload.get("coverage") or {}
    lines = [
        "# Run287 current benchmark and live-event sidecar",
        "",
        f"- status: `{payload.get('status')}`",
        f"- valuation close: `{payload.get('valuation_close_date')}`",
        f"- benchmark observation: `{payload.get('benchmark_observation_date')}`",
        f"- benchmark/event available from: `{payload.get('benchmark_event_available_from')}`",
        f"- benchmark finite: `{coverage.get('benchmark_finite_count')}` / "
        f"`{coverage.get('benchmark_required_count')}`",
        f"- live event finite: `{coverage.get('live_event_finite_count')}` / "
        f"`{coverage.get('live_event_required_count')}`",
        f"- network requests: `{payload.get('network_requests_executed')}`",
        "",
        "## Decision",
        "",
        "This sidecar restores the registered benchmark and live-event formula inputs",
        "for the isolated current feature-frame pilot. It is not a rank, alpha,",
        "historical PIT reconstruction, portfolio action, or trading instruction.",
        "",
    ]
    if payload.get("blockers"):
        lines.extend(["## Blockers", "", *[f"- `{item}`" for item in payload["blockers"]], ""])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--macro-manifest", default=DEFAULT_MACRO_MANIFEST)
    parser.add_argument("--benchmark-source", default=DEFAULT_BENCHMARK_SOURCE)
    parser.add_argument("--decision-time-utc", default="")
    parser.add_argument("--http-timeout-seconds", type=int, default=30)
    parser.add_argument("--max-network-requests", type=int, default=1)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") in {
        "READY_CONSERVATIVE_BENCHMARK_EVENT_SIDECAR",
        "BLOCKED_BENCHMARK_EVENT_CONTRACT",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())

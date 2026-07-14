#!/usr/bin/env python3
"""Build an isolated, bounded current-macro sidecar for Run287 research.

The tool acquires at most nine public market proxies and thirteen official FRED
series, applies conservative availability dates before the decision timestamp,
and reuses the engine's macro-regime formula in an isolated directory. It does
not run a portfolio, backtest, selector, fullrun, production path, or live
trading path, and it never writes to the source Google Drive cache.

FRED graph CSV contains the current vintage. Consequently this artifact is
eligible only for the current research decision; it is never valid evidence for
a historical backtest or a point-in-time historical macro reconstruction.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import shutil
import subprocess
import sys
from datetime import datetime, time as datetime_time, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from pandas.tseries.holiday import USFederalHolidayCalendar


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_config import (  # noqa: E402
    EngineConfig,
    MACRO_FRED_SERIES,
    MACRO_PRICE_TICKERS,
    MACRO_REGIME_COLUMNS,
)
from r1000_helpers import get_paths, px_cache_name  # noqa: E402
import r1000_pipeline as pipeline  # noqa: E402


SCHEMA_VERSION = "run287-current-macro-sidecar-v1"
DEFAULT_SNAPSHOT = (
    "outputs/run287_fresh_decision_snapshot_20260711/"
    "close_20260710_drive_cache_v4/manifest.json"
)
DEFAULT_TECHNICAL_PILOT = (
    "outputs/run287_latest_feature_pilot_20260711_commit_bfbc1276/manifest.json"
)
DEFAULT_PRICE_CACHE = "G:/내 드라이브/r1000_top30_institutional/cache_prices"
DEFAULT_MACRO_SOURCES = [
    "H:/codex/tmp_r1000_grossfloor_20260625/cache_macro",
    "G:/내 드라이브/r1000_top30_institutional/cache_macro",
]
DEFAULT_OUTPUT = "outputs/run287_macro_sidecar_20260711_v3"
FRED_GRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
USER_AGENT = "run287-bounded-macro-sidecar/1.0 research-contact"
MARKET_CLOSE_BUFFER_MINUTES = 15

# build_macro_regime_table consumes these 13 series. DGS3MO is used by the cash
# ledger, and SP500 by a separate benchmark fallback, so neither belongs in this
# current regime sidecar.
REQUIRED_FRED_NAMES = (
    "vix",
    "dgs10",
    "dxy",
    "m2",
    "fed_assets",
    "reverse_repo",
    "tga",
    "hy_oas",
    "cpi",
    "core_cpi",
    "ppi",
    "unrate",
    "sahm",
)

DAILY_FRED_NAMES = {"vix", "dgs10", "reverse_repo", "hy_oas"}
# DTWEXBGS contains daily observations, but the Federal Reserve H.10 release
# publishes the preceding business week's values as a weekly batch, normally
# Monday at 16:15 US Eastern. Treating it as a next-business-day series makes a
# valid current H.10 release look stale and misstates when the value was known.
H10_WEEKLY_BATCH_FRED_NAMES = {"dxy"}
WEEKLY_FRED_NAMES = {"fed_assets", "tga"}
MONTHLY_AVAILABILITY_LAG_DAYS = {
    "m2": 30,
    "cpi": 20,
    "core_cpi": 20,
    "ppi": 20,
    "unrate": 7,
    "sahm": 7,
}

CRITICAL_MACRO_COLUMNS = (
    "spy_ret_1m",
    "spy_ret_3m",
    "spy_above_ma200",
    "qqq_rel_spy_1m",
    "smh_rel_spy_1m",
    "vix_z_63d",
    "dgs10_change_1m",
    "hy_oas_level",
    "dxy_ret_1m",
    "liquidity_impulse_score",
    "liquidity_drain_score",
    "macro_risk_off_score",
    "market_regime_score",
    "inflation_pressure_score",
    "liquidity_regime_score",
    "growth_liquidity_reentry_score",
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "bytes": 0, "sha256": None}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "bytes": int(stat.st_size),
        "sha256": sha256_file(path),
        "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return loaded


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    return str(value)


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


def clean_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else parsed.date().isoformat()


def utc_timestamp(value: Any) -> pd.Timestamp:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        raise ValueError(f"invalid UTC timestamp: {value!r}")
    return pd.Timestamp(parsed)


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def normalize_price_frame(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    if output.empty:
        return output
    if not isinstance(output.index, pd.DatetimeIndex):
        date_column = next(
            (column for column in ("Date", "date", "Datetime", "datetime") if column in output.columns),
            None,
        )
        if date_column is None:
            return pd.DataFrame()
        output = output.set_index(date_column)
    output.index = pd.to_datetime(output.index, errors="coerce", utc=True).tz_convert(None).normalize()
    output = output[output.index.notna()].sort_index()
    if isinstance(output.columns, pd.MultiIndex):
        output.columns = output.columns.get_level_values(0)
    keep = [
        column
        for column in ("Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits")
        if column in output.columns
    ]
    output = output[keep].copy()
    if "Close" not in output.columns and "Adj Close" not in output.columns:
        return pd.DataFrame()
    if "Dividends" not in output.columns:
        output["Dividends"] = 0.0
    if "Stock Splits" not in output.columns:
        output["Stock Splits"] = 0.0
    return output[~output.index.duplicated(keep="last")]


def market_close_final_utc(valuation_date: str) -> pd.Timestamp:
    date = pd.Timestamp(valuation_date)
    try:
        import pandas_market_calendars as mcal

        schedule = mcal.get_calendar("NYSE").schedule(
            start_date=date.date().isoformat(),
            end_date=date.date().isoformat(),
        )
        if schedule.empty:
            raise ValueError(f"valuation date is not an NYSE session: {valuation_date}")
        close = pd.Timestamp(schedule.iloc[-1]["market_close"]).tz_convert("UTC")
    except ImportError:
        # July is daylight-saving time; this fallback is only for fixture
        # environments without pandas_market_calendars.
        close = pd.Timestamp.combine(date.date(), datetime_time(20, 0), tzinfo=timezone.utc)
    return close + pd.Timedelta(minutes=MARKET_CLOSE_BUFFER_MINUTES)


def price_frame_ready(frame: pd.DataFrame, valuation_date: str, min_rows: int) -> bool:
    if frame.empty or len(frame) < int(min_rows):
        return False
    return pd.Timestamp(frame.index.max()).date().isoformat() == valuation_date


def load_source_price(
    source_cache: Path,
    ticker: str,
    valuation_date: str,
    min_rows: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = source_cache / px_cache_name(ticker)
    audit = {"ticker": ticker, "source_path": str(path), "source_used": False, **fingerprint(path)}
    if not path.is_file():
        return pd.DataFrame(), audit
    try:
        frame = normalize_price_frame(pd.read_parquet(path))
        frame = frame[frame.index <= pd.Timestamp(valuation_date)]
        if price_frame_ready(frame, valuation_date, min_rows):
            audit["source_used"] = True
            return frame, audit
    except Exception as exc:
        audit["read_error"] = type(exc).__name__
    return pd.DataFrame(), audit


def acquire_market_prices(
    *,
    source_cache: Path,
    destination_cache: Path,
    valuation_date: str,
    start_date: str,
    min_rows: int,
    allow_network: bool,
    network_budget: dict[str, int],
) -> tuple[pd.DataFrame, int]:
    destination_cache.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    frames: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    for ticker in MACRO_PRICE_TICKERS.values():
        frame, source_audit = load_source_price(
            source_cache,
            ticker,
            valuation_date,
            min_rows,
        )
        records.append(source_audit)
        if frame.empty:
            missing.append(ticker)
        else:
            frames[ticker] = frame

    requests_used = 0
    if missing and allow_network:
        if network_budget["used"] >= network_budget["maximum"]:
            raise RuntimeError("network request budget exhausted before market-price batch")
        fetched = pipeline.download_yf_price_batch(
            missing,
            start=start_date,
            end=(pd.Timestamp(valuation_date) + pd.Timedelta(days=1)).date().isoformat(),
            interval="1d",
        )
        network_budget["used"] += 1
        requests_used += 1
        for ticker in missing:
            frame = normalize_price_frame(fetched.get(ticker, pd.DataFrame()))
            frame = frame[frame.index <= pd.Timestamp(valuation_date)]
            if price_frame_ready(frame, valuation_date, min_rows):
                frames[ticker] = frame

    still_missing = [ticker for ticker in MACRO_PRICE_TICKERS.values() if ticker not in frames]
    for ticker in list(still_missing):
        if not allow_network or network_budget["used"] >= network_budget["maximum"]:
            continue
        fetched = pipeline.download_yf_price_batch(
            [ticker],
            start=start_date,
            end=(pd.Timestamp(valuation_date) + pd.Timedelta(days=1)).date().isoformat(),
            interval="1d",
        )
        network_budget["used"] += 1
        requests_used += 1
        frame = normalize_price_frame(fetched.get(ticker, pd.DataFrame()))
        frame = frame[frame.index <= pd.Timestamp(valuation_date)]
        if price_frame_ready(frame, valuation_date, min_rows):
            frames[ticker] = frame

    output_rows: list[dict[str, Any]] = []
    source_by_ticker = {str(row["ticker"]): row for row in records}
    for name, ticker in MACRO_PRICE_TICKERS.items():
        frame = frames.get(ticker, pd.DataFrame())
        destination = destination_cache / px_cache_name(ticker)
        if not frame.empty:
            frame.to_parquet(destination, index=True)
        source_record = source_by_ticker.get(ticker, {})
        output_rows.append(
            {
                "component": name,
                "ticker": ticker,
                "status": "ready" if price_frame_ready(frame, valuation_date, min_rows) else "missing_or_stale",
                "row_count": int(len(frame)),
                "date_min": clean_date(frame.index.min()) if not frame.empty else "",
                "date_max": clean_date(frame.index.max()) if not frame.empty else "",
                "source_mode": "existing_exact_cache" if source_record.get("source_used") else ("bounded_yfinance" if not frame.empty else "unavailable"),
                "source_path": source_record.get("source_path", ""),
                "source_sha256": source_record.get("sha256"),
                "isolated_path": str(destination),
                "isolated_sha256": sha256_file(destination) if destination.is_file() else "",
            }
        )
    return pd.DataFrame(output_rows), requests_used


def normalize_fred_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["date", "value"])
    columns = {str(column).strip().lower(): column for column in frame.columns}
    date_column = columns.get("date") or columns.get("observation_date") or frame.columns[0]
    value_column = columns.get("value")
    if value_column is None:
        candidates = [column for column in frame.columns if column != date_column]
        if not candidates:
            return pd.DataFrame(columns=["date", "value"])
        value_column = candidates[0]
    output = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_column], errors="coerce"),
            "value": pd.to_numeric(frame[value_column], errors="coerce"),
        }
    )
    return output.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last")


def fred_available_from(name: str, dates: pd.Series) -> pd.Series:
    normalized = pd.to_datetime(dates, errors="coerce").dt.normalize()
    if name in H10_WEEKLY_BATCH_FRED_NAMES:
        federal_business_day = pd.offsets.CustomBusinessDay(
            calendar=USFederalHolidayCalendar()
        )
        eastern = ZoneInfo("America/New_York")
        available: list[pd.Timestamp] = []
        for value in normalized:
            if pd.isna(value):
                available.append(pd.NaT)
                continue
            observation = pd.Timestamp(value).normalize()
            days_until_next_monday = 7 - int(observation.weekday())
            release_date = observation + pd.Timedelta(days=days_until_next_monday)
            if not federal_business_day.is_on_offset(release_date):
                release_date = release_date + federal_business_day
            local_release = pd.Timestamp(
                datetime.combine(release_date.date(), datetime_time(16, 15)),
                tz=eastern,
            )
            available.append(local_release.tz_convert("UTC"))
        return pd.Series(pd.to_datetime(available, utc=True), index=dates.index)
    if name in DAILY_FRED_NAMES or name in WEEKLY_FRED_NAMES:
        next_business_day = normalized + pd.offsets.BDay(1)
        return (
            pd.to_datetime(next_business_day, errors="coerce", utc=True)
            + pd.Timedelta(hours=23, minutes=59, seconds=59)
        )
    lag_days = int(MONTHLY_AVAILABILITY_LAG_DAYS[name])
    month_end = normalized + pd.offsets.MonthEnd(0)
    lag_date = month_end + pd.to_timedelta(lag_days, unit="D")
    return (
        pd.to_datetime(lag_date, errors="coerce", utc=True)
        + pd.Timedelta(hours=23, minutes=59, seconds=59)
    )


def read_fred_source(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame(columns=["date", "value"])
    try:
        if path.suffix.lower() == ".parquet":
            return normalize_fred_frame(pd.read_parquet(path))
        return normalize_fred_frame(pd.read_csv(path))
    except Exception:
        return pd.DataFrame(columns=["date", "value"])


def best_fred_source(source_dirs: list[Path], filename: str) -> tuple[Path | None, pd.DataFrame]:
    best_path: Path | None = None
    best_frame = pd.DataFrame(columns=["date", "value"])
    best_latest = pd.Timestamp.min
    for directory in source_dirs:
        path = directory / filename
        frame = read_fred_source(path)
        latest = pd.to_datetime(frame["date"], errors="coerce").max() if not frame.empty else pd.NaT
        if pd.notna(latest) and pd.Timestamp(latest) > best_latest:
            best_path = path
            best_frame = frame
            best_latest = pd.Timestamp(latest)
    return best_path, best_frame


def fred_source_sufficient(name: str, usable: pd.DataFrame, valuation_date: str) -> bool:
    if usable.empty:
        return False
    latest = pd.Timestamp(usable["date"].max()).normalize()
    valuation = pd.Timestamp(valuation_date).normalize()
    if name in H10_WEEKLY_BATCH_FRED_NAMES:
        # One H.10 batch can legitimately be eight calendar days behind a
        # Friday valuation before the following Monday release. Ten days keeps
        # that documented interval valid while still failing a missed release.
        return latest >= valuation - pd.Timedelta(days=10)
    if name in DAILY_FRED_NAMES:
        return latest >= valuation - pd.offsets.BDay(5)
    if name in WEEKLY_FRED_NAMES:
        return latest >= valuation - pd.Timedelta(days=21)
    return latest >= valuation - pd.Timedelta(days=90)


def fetch_fred_csv(series_id: str, timeout_seconds: int) -> tuple[bytes, pd.DataFrame]:
    response = requests.get(
        FRED_GRAPH_URL.format(series_id=series_id),
        headers={"User-Agent": USER_AGENT},
        timeout=int(timeout_seconds),
    )
    response.raise_for_status()
    raw = response.content
    frame = normalize_fred_frame(pd.read_csv(io.BytesIO(raw)))
    if frame.empty:
        raise RuntimeError(f"FRED returned no observations for {series_id}")
    return raw, frame


def consumed_source_files_unchanged(audit: pd.DataFrame) -> bool:
    for _, row in audit.iterrows():
        expected = str(row.get("source_sha256") or "")
        if not expected:
            continue
        path = Path(str(row.get("source_path") or ""))
        if not path.is_file() or sha256_file(path) != expected:
            return False
    return True


def acquire_fred_series(
    *,
    source_dirs: list[Path],
    destination_cache: Path,
    raw_dir: Path,
    valuation_date: str,
    decision_time_utc: pd.Timestamp,
    allow_network: bool,
    timeout_seconds: int,
    network_budget: dict[str, int],
) -> tuple[pd.DataFrame, int]:
    destination_cache.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    requests_used = 0
    for name in REQUIRED_FRED_NAMES:
        series_id = MACRO_FRED_SERIES[name]
        filename = f"fred_{name}_{series_id}.parquet"
        source_path, source_frame = best_fred_source(source_dirs, filename)
        source_fingerprint = fingerprint(source_path) if source_path is not None else {}
        frame = source_frame
        source_mode = "existing_cache"
        raw_path = raw_dir / f"{series_id}.csv"
        raw_sha = ""

        if not frame.empty:
            probe = frame.copy()
            probe["available_from"] = fred_available_from(name, probe["date"])
            usable_probe = probe[
                pd.to_datetime(probe["available_from"], errors="coerce", utc=True)
                <= decision_time_utc
            ]
        else:
            usable_probe = frame
        if (
            not fred_source_sufficient(name, usable_probe, valuation_date)
            and allow_network
        ):
            if network_budget["used"] >= network_budget["maximum"]:
                raise RuntimeError(f"network request budget exhausted before FRED {series_id}")
            raw, fetched = fetch_fred_csv(series_id, timeout_seconds)
            raw_path.write_bytes(raw)
            raw_sha = sha256_bytes(raw)
            frame = fetched
            source_mode = "official_fred_graph_csv"
            network_budget["used"] += 1
            requests_used += 1

        normalized = frame.copy()
        normalized["available_from"] = fred_available_from(name, normalized["date"])
        available_utc = pd.to_datetime(normalized["available_from"], errors="coerce", utc=True)
        usable = normalized[
            (pd.to_datetime(normalized["date"], errors="coerce") <= pd.Timestamp(valuation_date))
            & available_utc.le(decision_time_utc)
        ].copy()
        future_excluded = int(len(normalized) - len(usable))
        destination = destination_cache / filename
        usable[["date", "value"]].to_parquet(destination, index=False)
        latest_raw = clean_date(normalized["date"].max()) if not normalized.empty else ""
        latest_usable = clean_date(usable["date"].max()) if not usable.empty else ""
        latest_available = (
            pd.to_datetime(usable["available_from"], errors="coerce", utc=True).max().isoformat()
            if not usable.empty
            else ""
        )
        rows.append(
            {
                "name": name,
                "series_id": series_id,
                "status": "ready" if fred_source_sufficient(name, usable, valuation_date) else "missing_or_stale",
                "source_mode": source_mode,
                "source_path": str(source_path or ""),
                "source_sha256": source_fingerprint.get("sha256"),
                "raw_response_path": str(raw_path) if raw_path.is_file() else "",
                "raw_response_sha256": raw_sha,
                "raw_row_count": int(len(normalized)),
                "usable_row_count": int(len(usable)),
                "future_or_unavailable_row_count": future_excluded,
                "latest_raw_observation_date": latest_raw,
                "latest_usable_observation_date": latest_usable,
                "latest_usable_available_from": latest_available,
                "availability_policy": (
                    "next_h10_release_day_1615_us_eastern"
                    if name in H10_WEEKLY_BATCH_FRED_NAMES
                    else "observation_plus_one_business_day_end_utc"
                    if name in DAILY_FRED_NAMES or name in WEEKLY_FRED_NAMES
                    else f"observation_month_end_plus_{MONTHLY_AVAILABILITY_LAG_DAYS[name]}_calendar_days_end_utc"
                ),
                "availability_exact": False,
                "availability_conservative": True,
                "vintage_clean": False,
                "isolated_path": str(destination),
                "isolated_sha256": sha256_file(destination),
            }
        )
    return pd.DataFrame(rows), requests_used


def prepare_cnn_proxy_cache(destination_cache: Path, start_date: str) -> Path:
    path = destination_cache / "cnn_fear_greed.parquet"
    # A nonempty NaN row prevents a network request. The engine then fills the
    # series with its documented VIX/market-return proxy.
    pd.DataFrame(
        {"date": [pd.Timestamp(start_date)], "fear_greed_score": [np.nan]}
    ).to_parquet(path, index=False)
    return path


def build_isolated_macro_table(
    isolated_base: Path,
    valuation_date: str,
) -> pd.DataFrame:
    cfg = EngineConfig()
    cfg.base_dir = str(isolated_base)
    cfg.start_date = (pd.Timestamp(valuation_date) - pd.DateOffset(years=3)).date().isoformat()
    cfg.end_date = valuation_date
    cfg.use_macro_regime_features = True
    cfg.macro_refresh_days = 99999
    cfg.macro_m2_release_lag_months = 1
    cfg.macro_slow_release_lag_months = 1
    cfg.yf_retry = 0
    cfg.yf_sleep = 0.0
    cfg.sec_sleep = 0.0
    cfg.fred_api_key = ""
    paths = get_paths(cfg)
    original_ensure = pipeline.ensure_prices_cached_incremental
    pipeline.ensure_prices_cached_incremental = lambda *_args, **_kwargs: None
    try:
        return pipeline.build_macro_regime_table(cfg, paths)
    finally:
        pipeline.ensure_prices_cached_incremental = original_ensure


def technical_pilot_tickers(manifest_path: Path) -> tuple[list[str], dict[str, Any]]:
    if not manifest_path.is_file():
        return [], {}
    manifest = read_json(manifest_path)
    outputs = manifest.get("outputs") or {}
    # The original technical-pilot packet exposes ``ticker_audit``. The
    # bounded scored-latest refresher exposes the same hashed ticker contract
    # as ``ticker_refresh_audit.csv``. Accept both without trusting an
    # unverified path or inferring tickers from a scored output.
    record = outputs.get("ticker_audit") or outputs.get("ticker_refresh_audit.csv") or {}
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or str(record.get("sha256") or "") != sha256_file(path):
        return [], manifest
    frame = pd.read_csv(path, low_memory=False)
    if "status" in frame.columns:
        frame = frame[frame["status"].astype(str).str.upper().eq("PASS")]
    if "exact_session_close" in frame.columns:
        exact = frame["exact_session_close"]
        if exact.dtype != bool:
            exact = exact.astype(str).str.strip().str.lower().isin({"1", "true", "yes"})
        frame = frame[exact]
    tickers = sorted(
        {
            str(value).upper().strip()
            for value in frame.get("ticker", pd.Series(dtype=str)).dropna()
            if str(value).strip()
        }
    )
    return tickers, manifest


def blocked_payload(
    output_dir: Path,
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
        "macro_merge_allowed": False,
        "fullrun_executed": False,
        "selector_executed": False,
        "backtest_executed": False,
        "source_inputs_mutated": False,
        "target_books_mutated": False,
        "historical_backtest_acceptance_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def build(args: argparse.Namespace, *, observed_at_utc: str | None = None) -> dict[str, Any]:
    snapshot_path = repo_path(args.snapshot_manifest)
    technical_pilot_path = repo_path(args.technical_pilot_manifest)
    source_price_cache = repo_path(args.source_price_cache)
    source_macro_dirs = [repo_path(value) for value in args.source_macro_dirs]
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)

    snapshot = read_json(snapshot_path)
    valuation_date = str(args.valuation_close_date or snapshot.get("valuation_close_date") or "")
    valuation_date = clean_date(valuation_date)
    if not valuation_date:
        raise ValueError("valuation_close_date is required")
    decision_time = utc_timestamp(
        observed_at_utc or args.decision_time_utc or datetime.now(timezone.utc).isoformat()
    )
    market_final = market_close_final_utc(valuation_date)
    if decision_time < market_final:
        return blocked_payload(
            output_dir,
            "BLOCKED_MARKET_CLOSE_NOT_FINAL",
            [f"decision_time_before_close_final:{decision_time.isoformat()}<{market_final.isoformat()}"],
            decision_time,
        )

    isolated_base = output_dir / "inputs" / "isolated_engine"
    destination_price_cache = isolated_base / "cache_prices"
    destination_macro_cache = isolated_base / "cache_macro"
    raw_fred_dir = output_dir / "inputs" / "raw_fred"
    destination_price_cache.mkdir(parents=True)
    destination_macro_cache.mkdir(parents=True)
    network_budget = {"used": 0, "maximum": int(args.max_network_requests)}
    allow_network = not bool(args.offline)

    price_start = str(
        args.price_start
        or (pd.Timestamp(valuation_date) - pd.DateOffset(years=3)).date().isoformat()
    )
    price_audit, price_requests = acquire_market_prices(
        source_cache=source_price_cache,
        destination_cache=destination_price_cache,
        valuation_date=valuation_date,
        start_date=price_start,
        min_rows=int(args.min_market_rows),
        allow_network=allow_network,
        network_budget=network_budget,
    )
    fred_audit, fred_requests = acquire_fred_series(
        source_dirs=source_macro_dirs,
        destination_cache=destination_macro_cache,
        raw_dir=raw_fred_dir,
        valuation_date=valuation_date,
        decision_time_utc=decision_time,
        allow_network=allow_network,
        timeout_seconds=int(args.http_timeout_seconds),
        network_budget=network_budget,
    )
    cnn_path = prepare_cnn_proxy_cache(destination_macro_cache, price_start)

    price_audit_path = output_dir / "market_component_audit.csv"
    fred_audit_path = output_dir / "fred_component_audit.csv"
    price_audit.to_csv(price_audit_path, index=False)
    fred_audit.to_csv(fred_audit_path, index=False)
    source_price_unchanged = consumed_source_files_unchanged(price_audit)
    source_macro_unchanged = consumed_source_files_unchanged(fred_audit)

    acquisition_blockers: list[str] = []
    for ticker in price_audit.loc[price_audit["status"].ne("ready"), "ticker"].astype(str):
        acquisition_blockers.append(f"market_component_not_ready:{ticker}")
    for series_id in fred_audit.loc[fred_audit["status"].ne("ready"), "series_id"].astype(str):
        acquisition_blockers.append(f"fred_component_not_ready:{series_id}")
    if acquisition_blockers:
        payload = blocked_payload(
            output_dir,
            "BLOCKED_MACRO_COMPONENT_COVERAGE",
            acquisition_blockers,
            decision_time,
        )
        payload["network_requests_executed"] = int(price_requests + fred_requests)
        payload["source_inputs_mutated"] = not (
            source_price_unchanged and source_macro_unchanged
        )
        payload["source_immutability"] = {
            "consumed_source_price_files_unchanged": source_price_unchanged,
            "consumed_source_macro_files_unchanged": source_macro_unchanged,
        }
        payload["outputs"] = {
            "market_component_audit": fingerprint(price_audit_path),
            "fred_component_audit": fingerprint(fred_audit_path),
        }
        write_json(output_dir / "manifest.json", payload)
        return payload

    macro_table = build_isolated_macro_table(isolated_base, valuation_date)
    macro_table["macro_date"] = pd.to_datetime(macro_table["macro_date"], errors="coerce")
    eligible_macro = macro_table[macro_table["macro_date"] <= pd.Timestamp(valuation_date)]
    if eligible_macro.empty:
        return blocked_payload(
            output_dir,
            "BLOCKED_EMPTY_MACRO_TABLE",
            ["engine_macro_table_has_no_row_on_or_before_valuation"],
            decision_time,
        )
    current = eligible_macro.sort_values("macro_date").tail(1).copy()
    current_date = clean_date(current.iloc[0]["macro_date"])
    current["valuation_close_date"] = valuation_date
    current["decision_time_utc"] = decision_time.isoformat()
    current["market_close_final_utc"] = market_final.isoformat()
    fred_available = pd.to_datetime(
        fred_audit["latest_usable_available_from"], errors="coerce", utc=True
    ).dropna()
    macro_available_from = max(
        [market_final, *(pd.Timestamp(value) for value in fred_available)]
    )
    current["macro_available_from"] = macro_available_from.isoformat()
    current["feature_price_cutoff_date"] = valuation_date
    current["availability_policy"] = "market_close_final_plus_conservative_fred_release_lags"
    current["fred_vintage_clean"] = False
    current["historical_backtest_acceptance_allowed"] = False

    critical_missing = [
        column
        for column in CRITICAL_MACRO_COLUMNS
        if column not in current.columns
        or not math.isfinite(float(pd.to_numeric(current.iloc[0][column], errors="coerce")))
    ]
    macro_values = current[[column for column in MACRO_REGIME_COLUMNS if column in current]].apply(
        pd.to_numeric, errors="coerce"
    )
    finite_ratio = float(np.isfinite(macro_values.to_numpy(dtype=float)).mean())
    range_violation_columns = [
        column
        for column in macro_values.columns
        if macro_values[column].notna().any()
        and (
            float(macro_values[column].min()) < -6.0000001
            or float(macro_values[column].max()) > 6.0000001
        )
    ]
    future_fred_rows = int(
        (
            pd.to_datetime(fred_audit["latest_usable_available_from"], errors="coerce", utc=True)
            > decision_time
        ).sum()
    )
    final_blockers: list[str] = []
    if current_date != valuation_date:
        final_blockers.append(f"macro_row_not_exact_close:{current_date}!={valuation_date}")
    final_blockers.extend(f"critical_macro_missing:{column}" for column in critical_missing)
    if finite_ratio < float(args.min_macro_finite_ratio):
        final_blockers.append(
            f"macro_finite_ratio:{finite_ratio:.6f}<{float(args.min_macro_finite_ratio):.6f}"
        )
    final_blockers.extend(f"macro_range_violation:{column}" for column in range_violation_columns)
    if future_fred_rows:
        final_blockers.append(f"future_fred_available_from_rows:{future_fred_rows}")
    if macro_available_from > decision_time:
        final_blockers.append("macro_available_from_after_decision_time")

    macro_path = output_dir / "macro_current.csv"
    current.to_csv(macro_path, index=False)
    pilot_tickers, technical_pilot = technical_pilot_tickers(technical_pilot_path)
    if pilot_tickers:
        ticker_macro = pd.DataFrame({"ticker": pilot_tickers})
        for column in current.columns:
            if column != "ticker":
                ticker_macro[column] = current.iloc[0][column]
        ticker_macro["macro_refresh_ready"] = not final_blockers
        ticker_macro["decision_ranking_allowed"] = False
    else:
        ticker_macro = pd.DataFrame(columns=["ticker", *current.columns, "macro_refresh_ready", "decision_ranking_allowed"])
    ticker_macro_path = output_dir / "ticker_macro_features.csv"
    ticker_macro.to_csv(ticker_macro_path, index=False)

    status = "READY_CONSERVATIVE_MACRO_SIDECAR" if not final_blockers else "BLOCKED_MACRO_CONTRACT"
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "blockers": final_blockers,
        "valuation_close_date": valuation_date,
        "decision_time_utc": decision_time.isoformat(),
        "market_close_final_utc": market_final.isoformat(),
        "macro_available_from": macro_available_from.isoformat(),
        "research_only": True,
        "current_decision_only": True,
        "macro_merge_allowed": not final_blockers,
        "decision_ranking_allowed": False,
        "fred_vintage_clean": False,
        "fred_availability_exact": False,
        "fred_availability_conservative": True,
        "missing_evidence_policy": "neutral_and_block_if_critical",
        "fullrun_executed": False,
        "selector_executed": False,
        "backtest_executed": False,
        "network_requests_executed": int(price_requests + fred_requests),
        "network_request_budget": int(args.max_network_requests),
        "source_inputs_mutated": not (
            source_price_unchanged and source_macro_unchanged
        ),
        "target_books_mutated": False,
        "historical_backtest_acceptance_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "coverage": {
            "market_component_ready_count": int(price_audit["status"].eq("ready").sum()),
            "market_component_required_count": int(len(MACRO_PRICE_TICKERS)),
            "fred_component_ready_count": int(fred_audit["status"].eq("ready").sum()),
            "fred_component_required_count": int(len(REQUIRED_FRED_NAMES)),
            "macro_regime_column_count": int(len(MACRO_REGIME_COLUMNS)),
            "macro_finite_ratio": finite_ratio,
            "critical_missing_columns": critical_missing,
            "future_fred_available_from_rows": future_fred_rows,
        },
        "technical_pilot": {
            "path": str(technical_pilot_path),
            "status": technical_pilot.get("status"),
            "ticker_count": int(len(pilot_tickers)),
        },
        "sources": {
            "market_provider": "Yahoo Finance via yfinance or exact preexisting cache",
            "fred_provider": "Federal Reserve Bank of St. Louis FRED graph CSV",
            "fred_observations_documentation": "https://fred.stlouisfed.org/docs/api/fred/series_observations.html",
            "nyse_hours_documentation": "https://www.nyse.com/markets/hours-calendars",
            "source_price_cache": str(source_price_cache),
            "source_macro_dirs": [str(path) for path in source_macro_dirs],
        },
        "source_immutability": {
            "consumed_source_price_files_unchanged": source_price_unchanged,
            "consumed_source_macro_files_unchanged": source_macro_unchanged,
        },
        "outputs": {
            "macro_current": {**fingerprint(macro_path), "row_count": int(len(current))},
            "ticker_macro_features": {
                **fingerprint(ticker_macro_path),
                "row_count": int(len(ticker_macro)),
            },
            "market_component_audit": {
                **fingerprint(price_audit_path),
                "row_count": int(len(price_audit)),
            },
            "fred_component_audit": {
                **fingerprint(fred_audit_path),
                "row_count": int(len(fred_audit)),
            },
            "isolated_engine_macro_table": fingerprint(
                isolated_base / "feature_store" / "macro_regime_latest.parquet"
            ),
            "cnn_proxy_cache": fingerprint(cnn_path),
        },
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__).resolve())},
    }
    write_json(output_dir / "manifest.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def render_report(payload: Mapping[str, Any]) -> str:
    coverage = payload.get("coverage") or {}
    lines = [
        "# Run287 current macro sidecar",
        "",
        f"- status: `{payload.get('status')}`",
        f"- valuation close: `{payload.get('valuation_close_date')}`",
        f"- decision time UTC: `{payload.get('decision_time_utc')}`",
        f"- macro available from: `{payload.get('macro_available_from')}`",
        f"- market components: `{coverage.get('market_component_ready_count')}` / `{coverage.get('market_component_required_count')}`",
        f"- FRED components: `{coverage.get('fred_component_ready_count')}` / `{coverage.get('fred_component_required_count')}`",
        f"- macro finite ratio: `{float(coverage.get('macro_finite_ratio') or 0.0):.1%}`",
        f"- network requests: `{payload.get('network_requests_executed')}` / `{payload.get('network_request_budget')}`",
        "",
        "FRED values use conservative availability lags and the current FRED",
        "vintage. The sidecar may feed only this current research decision; it",
        "cannot be used for historical backtest acceptance. Ticker ranking remains",
        "disabled until the separate 8-K actual/event refresh is complete.",
        "",
    ]
    if payload.get("blockers"):
        lines.extend(["## Blockers", "", *[f"- `{item}`" for item in payload["blockers"]], ""])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-manifest", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--technical-pilot-manifest", default=DEFAULT_TECHNICAL_PILOT)
    parser.add_argument("--valuation-close-date", default="")
    parser.add_argument("--decision-time-utc", default="")
    parser.add_argument("--source-price-cache", default=DEFAULT_PRICE_CACHE)
    parser.add_argument("--source-macro-dirs", nargs="+", default=DEFAULT_MACRO_SOURCES)
    parser.add_argument("--price-start", default="")
    parser.add_argument("--min-market-rows", type=int, default=400)
    parser.add_argument("--min-macro-finite-ratio", type=float, default=0.90)
    parser.add_argument("--http-timeout-seconds", type=int, default=45)
    parser.add_argument("--max-network-requests", type=int, default=24)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=json_default))
    return 0 if payload.get("status") == "READY_CONSERVATIVE_MACRO_SIDECAR" else 2


if __name__ == "__main__":
    raise SystemExit(main())

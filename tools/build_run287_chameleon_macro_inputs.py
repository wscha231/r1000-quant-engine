#!/usr/bin/env python3
"""Normalize official/free macro sources for the Chameleon report-only engine.

Historical FRED graph, Cboe close, and local daily-bar inputs are deliberately
classified FREE_PROXY because their archived publication timestamps or
vintages are not proven. Missing sources remain missing. This tool cannot
select securities, write targets, create orders, mutate ledgers, run a
backtest/fullrun, or promote a policy.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import requests


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_helpers import px_cache_name  # noqa: E402
from tools import build_run287_chameleon_macro_risk as risk_engine  # noqa: E402


SCHEMA_VERSION = "run287-chameleon-macro-inputs-v1"
DEFAULT_CONTRACT = ROOT / "docs" / "run287_chameleon_macro_inputs_contract.json"
CANONICAL_CONTRACT_SEMANTIC_SHA256 = (
    "b2eada9dcb7e8ec9e46fbad06a2ef1477f79545778167f4d1a9a0ae7c08c7da2"
)
FRED_GRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
USER_AGENT = "run287-chameleon-report-only/1.0 research-contact"
BLOCKED_STATUS = "BLOCKED_CHAMELEON_MACRO_INPUT_NORMALIZER"
READY_STATUS = "READY_CHAMELEON_MACRO_INPUTS_REPORT_ONLY"
DEFAULT_PRICE_CACHE = "G:/내 드라이브/r1000_top30_institutional/cache_prices"

SAFETY = {
    "report_only": True,
    "selector_executed": False,
    "target_books_mutated": False,
    "trade_intents_written": False,
    "orders_generated": False,
    "ledger_mutated": False,
    "backtest_executed": False,
    "fullrun_executed": False,
    "production_activation_allowed": False,
    "live_trading_enabled": False,
    "automatic_promotion_allowed": False,
}


class InputContractError(ValueError):
    """Raised when a source or output could misstate provenance."""


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_sha256(payload: Any) -> str:
    raw = json.dumps(
        json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256_bytes(raw)


def json_safe(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        return value
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(json_safe(payload), indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    head = result.stdout.strip().lower()
    if result.returncode != 0 or len(head) != 40:
        raise InputContractError("git_head_unavailable_or_invalid")
    return head


def load_contract(path: Path) -> dict[str, Any]:
    if path.resolve() != DEFAULT_CONTRACT.resolve():
        raise InputContractError(f"noncanonical_contract_path:{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputContractError(f"contract_unreadable:{path}") from exc
    if not isinstance(payload, dict):
        raise InputContractError("contract_root_not_object")
    observed = semantic_sha256(payload)
    if observed != CANONICAL_CONTRACT_SEMANTIC_SHA256:
        raise InputContractError(
            f"canonical_contract_semantic_hash_mismatch:{observed}"
        )
    if payload.get("mode") != "RESEARCH_ONLY_REPORT_ONLY":
        raise InputContractError("contract_mode_not_report_only")
    if payload.get("truth_policy", {}).get("historical_outputs") != "FREE_PROXY":
        raise InputContractError("historical_truth_policy_not_free_proxy")
    if any(value is not False for key, value in payload.get("safety", {}).items() if key != "report_only"):
        raise InputContractError("unsafe_contract_permission")
    if payload.get("safety", {}).get("report_only") is not True:
        raise InputContractError("report_only_not_frozen")
    return payload


def build_calendar(as_of: pd.Timestamp, contract: Mapping[str, Any]) -> pd.DataFrame:
    years = int(contract["history"]["calendar_years"])
    buffer_minutes = int(
        contract["history"]["decision_delay_after_xnys_close_minutes"]
    )
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=(as_of - pd.DateOffset(years=years)).date().isoformat(),
        end_date=as_of.date().isoformat(),
    )
    if schedule.empty:
        raise InputContractError("no_xnys_sessions_on_or_before_as_of")
    dates = pd.DatetimeIndex(schedule.index).tz_localize(None).normalize()
    decision_times = pd.to_datetime(schedule["market_close"], utc=True) + pd.Timedelta(
        minutes=buffer_minutes
    )
    return pd.DataFrame(
        {
            "decision_date": dates.date.astype(str),
            "decision_time_utc": [value.isoformat() for value in decision_times],
            "nyse_session_ordinal": np.arange(len(dates), dtype=int),
        }
    )


def normalize_fred(raw: bytes) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(raw))
    if frame.empty:
        return pd.DataFrame(columns=["observation_date", "value"])
    columns = {str(column).strip().lower(): column for column in frame.columns}
    date_column = columns.get("observation_date") or columns.get("date") or frame.columns[0]
    value_candidates = [column for column in frame.columns if column != date_column]
    if not value_candidates:
        raise InputContractError("fred_value_column_missing")
    value_column = columns.get("value") or value_candidates[0]
    output = pd.DataFrame(
        {
            "observation_date": pd.to_datetime(frame[date_column], errors="coerce"),
            "value": pd.to_numeric(frame[value_column], errors="coerce"),
        }
    )
    return (
        output.dropna(subset=["observation_date", "value"])
        .sort_values("observation_date")
        .drop_duplicates("observation_date", keep="last")
        .reset_index(drop=True)
    )


def normalize_cboe(raw: bytes) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(raw))
    columns = {str(column).replace("\ufeff", "").strip().upper(): column for column in frame.columns}
    date_column = columns.get("DATE")
    close_column = columns.get("CLOSE")
    if date_column is None or close_column is None:
        raise InputContractError("cboe_date_or_close_column_missing")
    output = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_column], errors="coerce"),
            "value": pd.to_numeric(frame[close_column], errors="coerce"),
        }
    )
    return (
        output.dropna(subset=["date", "value"])
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )


def copy_or_fetch(
    *,
    fixture: Path | None,
    url: str,
    destination: Path,
    allow_network: bool,
    timeout_seconds: int,
) -> tuple[bytes | None, str]:
    if fixture is not None and fixture.is_file():
        raw = fixture.read_bytes()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        return raw, "provided_source_bundle"
    if not allow_network:
        return None, "missing_network_disabled"
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=int(timeout_seconds),
    )
    response.raise_for_status()
    raw = response.content
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    return raw, "official_network_download"


def fred_available_from(
    observations: pd.Series,
    policy: str,
) -> pd.Series:
    normalized = pd.to_datetime(observations, errors="coerce").dt.normalize()
    if policy == "NEXT_BUSINESS_DAY_END_UTC":
        dates = normalized + pd.offsets.BDay(1)
    elif policy == "OBSERVATION_MONTH_END_PLUS_35_DAYS_END_UTC":
        dates = normalized + pd.offsets.MonthEnd(0) + pd.Timedelta(days=35)
    else:
        raise InputContractError(f"unknown_fred_availability_policy:{policy}")
    return pd.to_datetime(dates, utc=True) + pd.Timedelta(
        hours=23, minutes=59, seconds=59
    )


def align_releases(
    calendar: pd.DataFrame,
    observations: pd.DataFrame,
    available_from: pd.Series,
) -> pd.DataFrame:
    left = calendar[["decision_date", "decision_time_utc"]].copy()
    left["decision_date"] = pd.to_datetime(left["decision_date"])
    left["decision_time_utc"] = pd.to_datetime(left["decision_time_utc"], utc=True)
    right = observations[["observation_date", "value"]].copy()
    right["available_from"] = pd.to_datetime(available_from, utc=True)
    right = right.dropna().sort_values("available_from")
    if right.empty:
        return pd.DataFrame(
            index=pd.DatetimeIndex(left["decision_date"]),
            columns=["value", "source_observation_date", "available_from"],
        )
    merged = pd.merge_asof(
        left.sort_values("decision_time_utc"),
        right,
        left_on="decision_time_utc",
        right_on="available_from",
        direction="backward",
        allow_exact_matches=True,
    )
    merged = merged.set_index("decision_date")
    return merged.rename(columns={"observation_date": "source_observation_date"})[
        ["value", "source_observation_date", "available_from"]
    ]


def normalize_price_frame(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    if isinstance(output.index, pd.DatetimeIndex):
        output = output.reset_index().rename(columns={output.index.name or "index": "date"})
    columns = {str(column).strip().lower(): column for column in output.columns}
    date_column = columns.get("date") or columns.get("datetime") or columns.get("timestamp")
    close_column = columns.get("close") or columns.get("adj close") or columns.get("adj_close")
    if date_column is None or close_column is None:
        raise InputContractError("price_date_or_close_column_missing")
    normalized = pd.DataFrame(
        {
            "date": pd.to_datetime(output[date_column], errors="coerce", utc=True)
            .dt.tz_localize(None)
            .dt.normalize(),
            "close": pd.to_numeric(output[close_column], errors="coerce"),
        }
    )
    volume_column = columns.get("volume")
    normalized["volume"] = (
        pd.to_numeric(output[volume_column], errors="coerce")
        if volume_column is not None
        else np.nan
    )
    return (
        normalized.dropna(subset=["date", "close"])
        .query("close > 0")
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .set_index("date")
    )


def read_price(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return normalize_price_frame(pd.read_parquet(path))
    return normalize_price_frame(pd.read_csv(path))


def read_price_stable(path: Path) -> tuple[pd.DataFrame, str]:
    before = sha256_file(path)
    frame = read_price(path)
    after = sha256_file(path)
    if after != before:
        raise InputContractError(f"price_source_changed_during_read:{path}")
    return frame, before


def resolve_price_path(
    ticker: str,
    source_bundle: Path | None,
    price_cache: Path | None,
) -> Path | None:
    candidates: list[Path] = []
    if source_bundle is not None:
        candidates.extend(
            [
                source_bundle / "prices" / f"{ticker}.parquet",
                source_bundle / "prices" / f"{ticker}.csv",
            ]
        )
    if price_cache is not None:
        candidates.append(price_cache / px_cache_name(ticker))
    return next((path for path in candidates if path.is_file()), None)


def daily_aligned(
    calendar: pd.DataFrame,
    values: pd.Series,
) -> pd.DataFrame:
    dates = pd.to_datetime(calendar["decision_date"])
    decision_time = pd.Series(
        pd.to_datetime(calendar["decision_time_utc"], utc=True).to_numpy(),
        index=pd.DatetimeIndex(dates),
    )
    aligned_values = values.reindex(pd.DatetimeIndex(dates))
    return pd.DataFrame(
        {
            "value": aligned_values,
            "source_observation_date": pd.DatetimeIndex(dates),
            "available_from": decision_time,
        },
        index=pd.DatetimeIndex(dates),
    )


def trailing_midrank(series: pd.Series, window: int = 63, minimum: int = 20) -> pd.Series:
    def percentile(values: np.ndarray) -> float:
        current = values[-1]
        finite = values[np.isfinite(values)]
        if not math.isfinite(current) or len(finite) < minimum:
            return math.nan
        return float(
            100.0
            * (np.sum(finite < current) + 0.5 * np.sum(finite == current))
            / len(finite)
        )

    return series.rolling(window, min_periods=minimum).apply(percentile, raw=True)


def combine_meta(*frames: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    observations = pd.concat(
        [pd.to_datetime(frame["source_observation_date"]) for frame in frames],
        axis=1,
    ).max(axis=1)
    available = pd.concat(
        [pd.to_datetime(frame["available_from"], utc=True) for frame in frames],
        axis=1,
    ).max(axis=1)
    return observations, available


def add_component(
    rows: list[dict[str, Any]],
    calendar_map: pd.DataFrame,
    *,
    axis: str,
    component: str,
    direction: str,
    value: pd.Series,
    observation: pd.Series,
    available: pd.Series,
    source_kind: str,
    source_sha256: str,
    calendar_sha256: str,
) -> None:
    frame = pd.DataFrame(
        {
            "raw_value": pd.to_numeric(value, errors="coerce"),
            "source_observation_date": pd.to_datetime(observation, errors="coerce"),
            "available_from": pd.to_datetime(available, errors="coerce", utc=True),
        }
    ).join(calendar_map, how="inner")
    frame = frame[
        np.isfinite(frame["raw_value"])
        & frame["source_observation_date"].notna()
        & frame["available_from"].notna()
    ]
    for date, row in frame.iterrows():
        rows.append(
            {
                "decision_date": date.date().isoformat(),
                "decision_time_utc": pd.Timestamp(row["decision_time_utc"]).isoformat(),
                "nyse_session_ordinal": int(row["nyse_session_ordinal"]),
                "calendar_source_sha256": calendar_sha256,
                "axis": axis,
                "component": component,
                "raw_value": float(row["raw_value"]),
                "risk_direction": direction,
                "source_observation_date": row["source_observation_date"].date().isoformat(),
                "available_from": pd.Timestamp(row["available_from"]).isoformat(),
                "source_kind": source_kind,
                "source_sha256": source_sha256,
                "truth_class": "FREE_PROXY",
            }
        )


def source_record(
    *,
    name: str,
    provider: str,
    status: str,
    mode: str,
    path: Path | None,
    row_count: int,
    first_date: Any = None,
    last_date: Any = None,
    note: str = "",
    source_sha256_override: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "provider": provider,
        "status": status,
        "source_mode": mode,
        "source_path": str(path or ""),
        "source_sha256": source_sha256_override
        or (sha256_file(path) if path is not None and path.is_file() else ""),
        "row_count": int(row_count),
        "first_observation_date": "" if first_date is None or pd.isna(first_date) else pd.Timestamp(first_date).date().isoformat(),
        "last_observation_date": "" if last_date is None or pd.isna(last_date) else pd.Timestamp(last_date).date().isoformat(),
        "truth_class": "FREE_PROXY",
        "note": note,
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise InputContractError(f"output_dir_already_exists:{output_dir}")
    output_dir.mkdir(parents=True)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir()
    try:
        contract_path = repo_path(args.contract)
        contract = load_contract(contract_path)
        requested_as_of = pd.to_datetime(str(args.as_of).strip(), errors="coerce")
        if pd.isna(requested_as_of):
            raise InputContractError(f"invalid_as_of:{args.as_of}")
        calendar = build_calendar(pd.Timestamp(requested_as_of), contract)
        resolved_as_of = pd.Timestamp(calendar["decision_date"].iloc[-1])
        calendar_path = output_dir / "xnys_calendar.csv"
        calendar.to_csv(calendar_path, index=False)
        calendar_sha = sha256_file(calendar_path)
        dates = pd.to_datetime(calendar["decision_date"])
        calendar_map = calendar.copy()
        calendar_map["decision_date"] = dates
        calendar_map["decision_time_utc"] = pd.to_datetime(
            calendar_map["decision_time_utc"], utc=True
        )
        calendar_map = calendar_map.set_index("decision_date")

        source_bundle = repo_path(args.source_bundle) if args.source_bundle else None
        price_cache = repo_path(args.price_cache) if args.price_cache else None
        source_rows: list[dict[str, Any]] = []
        consumed_inputs: dict[str, str] = {}
        aligned: dict[str, pd.DataFrame] = {}
        price_frames: dict[str, pd.DataFrame] = {}

        for name, spec in contract["fred"].items():
            series_id = spec["series_id"]
            fixture = (
                source_bundle / "fred" / f"{series_id}.csv"
                if source_bundle is not None
                else None
            )
            destination = raw_dir / "fred" / f"{series_id}.csv"
            try:
                raw, mode = copy_or_fetch(
                    fixture=fixture,
                    url=FRED_GRAPH_URL.format(series_id=series_id),
                    destination=destination,
                    allow_network=bool(args.allow_network),
                    timeout_seconds=int(args.http_timeout_seconds),
                )
                if raw is None:
                    source_rows.append(
                        source_record(
                            name=name,
                            provider="FRED",
                            status="missing",
                            mode=mode,
                            path=None,
                            row_count=0,
                            note="component omitted; no carry or imputation",
                        )
                    )
                    continue
                observations = normalize_fred(raw)
                aligned[name] = align_releases(
                    calendar,
                    observations,
                    fred_available_from(observations["observation_date"], spec["availability"]),
                )
                source_rows.append(
                    source_record(
                        name=name,
                        provider="FRED graph current vintage",
                        status="ready" if not observations.empty else "empty",
                        mode=mode,
                        path=destination,
                        row_count=len(observations),
                        first_date=observations["observation_date"].min(),
                        last_date=observations["observation_date"].max(),
                        note="current vintage; historical use is FREE_PROXY only",
                    )
                )
            except Exception as exc:
                source_rows.append(
                    source_record(
                        name=name,
                        provider="FRED",
                        status="invalid_or_unavailable",
                        mode="error",
                        path=destination if destination.is_file() else None,
                        row_count=0,
                        note=f"{type(exc).__name__}; component omitted",
                    )
                )

        for symbol, url in contract["cboe"].items():
            fixture = (
                source_bundle / "cboe" / f"{symbol}.csv"
                if source_bundle is not None
                else None
            )
            destination = raw_dir / "cboe" / f"{symbol}.csv"
            key = symbol.lower()
            try:
                raw, mode = copy_or_fetch(
                    fixture=fixture,
                    url=url,
                    destination=destination,
                    allow_network=bool(args.allow_network),
                    timeout_seconds=int(args.http_timeout_seconds),
                )
                if raw is None:
                    source_rows.append(
                        source_record(
                            name=key,
                            provider="Cboe",
                            status="missing",
                            mode=mode,
                            path=None,
                            row_count=0,
                        )
                    )
                    continue
                observations = normalize_cboe(raw)
                series = observations.set_index("date")["value"]
                aligned[key] = daily_aligned(calendar, series)
                source_rows.append(
                    source_record(
                        name=key,
                        provider="Cboe historical index close",
                        status="ready" if not observations.empty else "empty",
                        mode=mode,
                        path=destination,
                        row_count=len(observations),
                        first_date=observations["date"].min(),
                        last_date=observations["date"].max(),
                        note="historical publication time not archived; FREE_PROXY only",
                    )
                )
            except Exception as exc:
                source_rows.append(
                    source_record(
                        name=key,
                        provider="Cboe",
                        status="invalid_or_unavailable",
                        mode="error",
                        path=destination if destination.is_file() else None,
                        row_count=0,
                        note=f"{type(exc).__name__}; component omitted",
                    )
                )

        for ticker in contract["prices"]:
            path = resolve_price_path(ticker, source_bundle, price_cache)
            if path is None:
                source_rows.append(
                    source_record(
                        name=f"price_{ticker}",
                        provider="local daily-bar cache",
                        status="missing",
                        mode="missing",
                        path=None,
                        row_count=0,
                    )
                )
                continue
            try:
                frame, stable_sha = read_price_stable(path)
                consumed_inputs[str(path.resolve())] = stable_sha
                price_frames[ticker] = frame
                aligned[f"price_{ticker}"] = daily_aligned(calendar, frame["close"])
                source_rows.append(
                    source_record(
                        name=f"price_{ticker}",
                        provider="local daily-bar cache",
                        status="ready",
                        mode="provided_or_existing_cache",
                        path=path,
                        row_count=len(frame),
                        first_date=frame.index.min(),
                        last_date=frame.index.max(),
                        note="publication time not archived; FREE_PROXY only",
                        source_sha256_override=stable_sha,
                    )
                )
            except Exception as exc:
                source_rows.append(
                    source_record(
                        name=f"price_{ticker}",
                        provider="local daily-bar cache",
                        status="invalid",
                        mode="error",
                        path=path,
                        row_count=0,
                        note=f"{type(exc).__name__}; component omitted",
                    )
                )

        universe_close = pd.DataFrame(index=pd.DatetimeIndex(dates))
        universe_volume = pd.DataFrame(index=pd.DatetimeIndex(dates))
        sector_by_ticker: dict[str, str] = {}
        universe_path = repo_path(args.universe_file) if args.universe_file else None
        if universe_path is not None and universe_path.is_file():
            universe_sha = sha256_file(universe_path)
            universe = pd.read_csv(universe_path, low_memory=False)
            if sha256_file(universe_path) != universe_sha:
                raise InputContractError("universe_file_changed_during_read")
            consumed_inputs[str(universe_path.resolve())] = universe_sha
            columns = {str(column).strip().lower(): column for column in universe.columns}
            ticker_column = columns.get("ticker") or columns.get("symbol")
            sector_column = columns.get("sector") or columns.get("gics_sector")
            if ticker_column is None:
                raise InputContractError("universe_ticker_column_missing")
            tickers = sorted(
                {
                    str(value).strip().upper()
                    for value in universe[ticker_column]
                    if str(value).strip() and str(value).lower() != "nan"
                }
            )[: int(contract["history"]["maximum_universe_symbols"])]
            if sector_column is not None:
                sector_by_ticker = {
                    str(row[ticker_column]).strip().upper(): str(row[sector_column]).strip()
                    for _, row in universe.iterrows()
                }
            loaded = 0
            close_columns: dict[str, pd.Series] = {}
            volume_columns: dict[str, pd.Series] = {}
            for ticker in tickers:
                path = resolve_price_path(ticker, source_bundle, price_cache)
                if path is None:
                    continue
                try:
                    frame, stable_sha = read_price_stable(path)
                except Exception:
                    continue
                consumed_inputs[str(path.resolve())] = stable_sha
                close_columns[ticker] = frame["close"].reindex(
                    pd.DatetimeIndex(dates)
                )
                volume_columns[ticker] = frame["volume"].reindex(
                    pd.DatetimeIndex(dates)
                )
                loaded += 1
            if close_columns:
                universe_close = pd.DataFrame(
                    close_columns,
                    index=pd.DatetimeIndex(dates),
                )
                universe_volume = pd.DataFrame(
                    volume_columns,
                    index=pd.DatetimeIndex(dates),
                )
            source_rows.append(
                source_record(
                    name="universe_daily_bars",
                    provider="explicit hashed universe and local daily-bar cache",
                    status="ready" if loaded else "missing",
                    mode="bounded_explicit_universe",
                    path=universe_path,
                    row_count=loaded,
                    first_date=universe_close.dropna(how="all").index.min() if loaded else None,
                    last_date=universe_close.dropna(how="all").index.max() if loaded else None,
                    note=f"loaded_tickers={loaded}; minimum_breadth_symbols={contract['history']['minimum_breadth_symbols']}",
                    source_sha256_override=universe_sha,
                )
            )
        else:
            source_rows.append(
                source_record(
                    name="universe_daily_bars",
                    provider="explicit universe",
                    status="missing",
                    mode="missing",
                    path=universe_path,
                    row_count=0,
                    note="market breadth and correlation components omitted",
                )
            )

        source_audit = pd.DataFrame(source_rows).sort_values("name").reset_index(drop=True)
        source_audit_path = output_dir / "source_audit.csv"
        source_audit.to_csv(source_audit_path, index=False)
        lineage = {
            "schema_version": "run287-chameleon-source-lineage-v1",
            "contract_semantic_sha256": CANONICAL_CONTRACT_SEMANTIC_SHA256,
            "calendar_sha256": calendar_sha,
            "requested_as_of": pd.Timestamp(requested_as_of).date().isoformat(),
            "resolved_as_of": resolved_as_of.date().isoformat(),
            "truth_class": "FREE_PROXY",
            "historical_ab_allowed": False,
            "sources": source_rows,
            "consumed_external_inputs": [
                {"path": path, "sha256": digest}
                for path, digest in sorted(consumed_inputs.items())
            ],
        }
        lineage_path = output_dir / "source_lineage.json"
        write_json(lineage_path, lineage)
        lineage_sha = sha256_file(lineage_path)

        metric_rows: list[dict[str, Any]] = []

        def emit(
            axis: str,
            component: str,
            direction: str,
            value: pd.Series,
            frames: tuple[pd.DataFrame, ...],
            kind: str,
        ) -> None:
            observation, available = combine_meta(*frames)
            add_component(
                metric_rows,
                calendar_map,
                axis=axis,
                component=component,
                direction=direction,
                value=value,
                observation=observation,
                available=available,
                source_kind=kind,
                source_sha256=lineage_sha,
                calendar_sha256=calendar_sha,
            )

        spy = aligned.get("price_SPY")
        if spy is not None:
            close = spy["value"]
            ma200 = close.rolling(200, min_periods=200).mean()
            emit("trend_drawdown", "spy_return_5d", "LOW", close.pct_change(5, fill_method=None), (spy,), "LOCAL_DAILY_CLOSE_FREE_PROXY")
            emit("trend_drawdown", "spy_return_20d", "LOW", close.pct_change(20, fill_method=None), (spy,), "LOCAL_DAILY_CLOSE_FREE_PROXY")
            emit("trend_drawdown", "spy_return_63d", "LOW", close.pct_change(63, fill_method=None), (spy,), "LOCAL_DAILY_CLOSE_FREE_PROXY")
            emit("trend_drawdown", "spy_above_ma200", "LOW", (close >= ma200).where(ma200.notna()).astype(float), (spy,), "LOCAL_DAILY_CLOSE_FREE_PROXY")
            emit("trend_drawdown", "spy_ma200_distance", "LOW", close / ma200 - 1.0, (spy,), "LOCAL_DAILY_CLOSE_FREE_PROXY")
            emit("trend_drawdown", "drawdown_velocity", "HIGH", -(close / close.rolling(20, min_periods=20).max() - 1.0), (spy,), "LOCAL_DAILY_CLOSE_FREE_PROXY")

        vix = aligned.get("vix")
        if vix is not None:
            emit("volatility", "vix_level", "HIGH", vix["value"], (vix,), "CBOE_HISTORICAL_CLOSE_FREE_PROXY")
            emit("volatility", "vix_change_5d", "HIGH", vix["value"].pct_change(5, fill_method=None), (vix,), "CBOE_HISTORICAL_CLOSE_FREE_PROXY")
            emit("volatility", "vix_percentile_63d", "HIGH", trailing_midrank(vix["value"]), (vix,), "CBOE_HISTORICAL_CLOSE_FREE_PROXY")
        vix3m = aligned.get("vix3m")
        if vix is not None and vix3m is not None:
            emit("volatility_structure", "vix_vix3m_inversion", "HIGH", vix["value"] / vix3m["value"] - 1.0, (vix, vix3m), "CBOE_COMPOSITE_HISTORICAL_CLOSE_FREE_PROXY")
        vvix = aligned.get("vvix")
        if vvix is not None:
            emit("volatility_structure", "vvix_level", "HIGH", vvix["value"], (vvix,), "CBOE_HISTORICAL_CLOSE_FREE_PROXY")

        hy = aligned.get("hy_oas")
        ig = aligned.get("ig_oas")
        if hy is not None:
            emit("credit", "hy_oas_level", "HIGH", hy["value"], (hy,), "FRED_GRAPH_CURRENT_VINTAGE_FREE_PROXY")
            emit("credit", "hy_oas_change_5d", "HIGH", hy["value"].diff(5), (hy,), "FRED_GRAPH_CURRENT_VINTAGE_FREE_PROXY")
            emit("credit", "hy_oas_change_20d", "HIGH", hy["value"].diff(20), (hy,), "FRED_GRAPH_CURRENT_VINTAGE_FREE_PROXY")
        if ig is not None:
            emit("credit", "ig_oas_level", "HIGH", ig["value"], (ig,), "FRED_GRAPH_CURRENT_VINTAGE_FREE_PROXY")
            emit("credit", "ig_oas_change_20d", "HIGH", ig["value"].diff(20), (ig,), "FRED_GRAPH_CURRENT_VINTAGE_FREE_PROXY")
        hyg = aligned.get("price_HYG")
        lqd = aligned.get("price_LQD")
        if hyg is not None and lqd is not None:
            emit("credit", "hyg_lqd_weakness", "HIGH", -(hyg["value"] / lqd["value"]).pct_change(20, fill_method=None), (hyg, lqd), "LOCAL_DAILY_CLOSE_COMPOSITE_FREE_PROXY")

        dgs2, dgs10, dgs3mo = aligned.get("dgs2"), aligned.get("dgs10"), aligned.get("dgs3mo")
        if dgs2 is not None and dgs10 is not None:
            emit("rates_liquidity", "curve_2y10y_stress", "HIGH", dgs2["value"] - dgs10["value"], (dgs2, dgs10), "FRED_GRAPH_CURRENT_VINTAGE_COMPOSITE_FREE_PROXY")
        if dgs3mo is not None and dgs10 is not None:
            emit("rates_liquidity", "curve_3m10y_stress", "HIGH", dgs3mo["value"] - dgs10["value"], (dgs3mo, dgs10), "FRED_GRAPH_CURRENT_VINTAGE_COMPOSITE_FREE_PROXY")
        real10 = aligned.get("real10")
        if real10 is not None:
            emit("rates_liquidity", "real_yield_shock", "HIGH", real10["value"].diff(20), (real10,), "FRED_GRAPH_CURRENT_VINTAGE_FREE_PROXY")
        fed_assets, tga, reverse_repo = aligned.get("fed_assets"), aligned.get("tga"), aligned.get("reverse_repo")
        if fed_assets is not None:
            emit("rates_liquidity", "fed_assets_contraction", "HIGH", -fed_assets["value"].pct_change(20, fill_method=None), (fed_assets,), "FRED_GRAPH_CURRENT_VINTAGE_FREE_PROXY")
        if tga is not None:
            emit("rates_liquidity", "tga_drain", "HIGH", tga["value"].pct_change(20, fill_method=None), (tga,), "FRED_GRAPH_CURRENT_VINTAGE_FREE_PROXY")
        if fed_assets is not None and tga is not None and reverse_repo is not None:
            net_contraction = (
                -fed_assets["value"].pct_change(20, fill_method=None)
                + tga["value"].pct_change(20, fill_method=None)
                + reverse_repo["value"].pct_change(20, fill_method=None)
            )
            emit("rates_liquidity", "net_liquidity_contraction", "HIGH", net_contraction, (fed_assets, tga, reverse_repo), "FRED_GRAPH_CURRENT_VINTAGE_COMPOSITE_FREE_PROXY")

        if spy is not None:
            for ticker, component, formula in (
                ("TLT", "treasury_risk_off_rotation", lambda asset: asset.pct_change(20, fill_method=None) - spy["value"].pct_change(20, fill_method=None)),
                ("UUP", "dollar_risk_off_rotation", lambda asset: asset.pct_change(20, fill_method=None)),
                ("GLD", "gold_risk_off_rotation", lambda asset: asset.pct_change(20, fill_method=None) - spy["value"].pct_change(20, fill_method=None)),
                ("HYG", "high_yield_risk_off_rotation", lambda asset: -(asset.pct_change(20, fill_method=None) - spy["value"].pct_change(20, fill_method=None))),
            ):
                asset = aligned.get(f"price_{ticker}")
                if asset is not None:
                    emit("cross_asset", component, "HIGH", formula(asset["value"]), (asset, spy), "LOCAL_DAILY_CLOSE_COMPOSITE_FREE_PROXY")

        for source_name, component, transform in (
            ("initial_claims", "initial_claims_stress", lambda value: value.pct_change(20, fill_method=None)),
            ("nfci", "nfci_stress", lambda value: value),
            ("unrate", "employment_stress", lambda value: value.diff(63)),
            ("payems", "economic_diffusion_stress", lambda value: -value.pct_change(63, fill_method=None)),
        ):
            source = aligned.get(source_name)
            if source is not None:
                emit("economic_stress", component, "HIGH", transform(source["value"]), (source,), "FRED_GRAPH_CURRENT_VINTAGE_FREE_PROXY")

        minimum_breadth = int(contract["history"]["minimum_breadth_symbols"])
        breadth_values: dict[str, pd.Series] = {}
        if not universe_close.empty:
            coverage = universe_close.notna().sum(axis=1)
            eligible = coverage >= minimum_breadth
            ma50 = universe_close.rolling(50, min_periods=50).mean()
            ma200 = universe_close.rolling(200, min_periods=200).mean()
            breadth_values["pct_above_ma50"] = ((universe_close > ma50).sum(axis=1) / coverage).where(eligible)
            breadth_values["pct_above_ma200"] = ((universe_close > ma200).sum(axis=1) / coverage).where(eligible)
            high252 = universe_close.rolling(252, min_periods=200).max()
            low252 = universe_close.rolling(252, min_periods=200).min()
            breadth_values["new_high_minus_new_low"] = ((
                (universe_close >= high252).sum(axis=1)
                - (universe_close <= low252).sum(axis=1)
            ) / coverage).where(eligible)
            returns = universe_close.pct_change(fill_method=None)
            dollar_volume = universe_close * universe_volume
            advancing = dollar_volume.where(returns > 0).sum(axis=1, min_count=1)
            declining = dollar_volume.where(returns < 0).sum(axis=1, min_count=1)
            breadth_values["adv_decl_dollar_volume_ratio"] = (
                advancing / declining.replace(0.0, np.nan)
            ).where(eligible)
            meta = daily_aligned(calendar, universe_close.mean(axis=1))
            for component, value in breadth_values.items():
                emit("market_breadth", component, "LOW", value, (meta,), "EXPLICIT_UNIVERSE_DAILY_BARS_FREE_PROXY")
            vol20 = returns.rolling(20, min_periods=15).std()
            vol63 = returns.rolling(63, min_periods=40).std()
            vol_breadth = (vol20 > vol63).sum(axis=1) / coverage
            emit("volatility_structure", "volatility_spike_breadth", "HIGH", vol_breadth.where(eligible), (meta,), "EXPLICIT_UNIVERSE_DAILY_BARS_FREE_PROXY")
            market_return = returns.mean(axis=1)
            mean_stock = returns.rolling(63, min_periods=40).mean()
            mean_market = market_return.rolling(63, min_periods=40).mean()
            covariance = returns.mul(market_return, axis=0).rolling(63, min_periods=40).mean() - mean_stock.mul(mean_market, axis=0)
            correlation = covariance.div(returns.rolling(63, min_periods=40).std().mul(market_return.rolling(63, min_periods=40).std(), axis=0)).mean(axis=1)
            emit("correlation_dispersion", "stock_correlation", "HIGH", correlation.where(eligible), (meta,), "EXPLICIT_UNIVERSE_DAILY_BARS_FREE_PROXY")
            dollar_total = dollar_volume.sum(axis=1, min_count=1)
            top10 = dollar_volume.apply(lambda row: row.nlargest(10).sum(), axis=1)
            emit("correlation_dispersion", "index_concentration", "HIGH", (top10 / dollar_total).where(eligible), (meta,), "EXPLICIT_UNIVERSE_DAILY_BARS_FREE_PROXY")
            if sector_by_ticker:
                returns20 = universe_close.pct_change(20, fill_method=None)
                sectors = pd.Series(sector_by_ticker)
                common = [column for column in returns20.columns if column in sectors.index and sectors[column] not in {"", "nan"}]
                if common:
                    sector_returns = returns20[common].T.groupby(sectors[common]).mean().T
                    emit("correlation_dispersion", "sector_return_dispersion", "HIGH", sector_returns.std(axis=1).where(eligible), (meta,), "EXPLICIT_UNIVERSE_DAILY_BARS_FREE_PROXY")

        metrics = pd.DataFrame(metric_rows)
        if metrics.empty:
            raise InputContractError("no_normalized_metric_rows")
        metrics = metrics.sort_values(["decision_date", "axis", "component"]).reset_index(drop=True)
        metrics_path = output_dir / "input_metrics.csv"
        metrics.to_csv(metrics_path, index=False)

        context_rows: list[dict[str, Any]] = []
        context_dates = sorted(pd.to_datetime(metrics["decision_date"].unique()))
        for date in context_dates:
            row: dict[str, Any] = {
                "decision_date": date.date().isoformat(),
                "decision_time_utc": calendar_map.loc[date, "decision_time_utc"].isoformat(),
                "nyse_session_ordinal": int(calendar_map.loc[date, "nyse_session_ordinal"]),
                "calendar_source_sha256": calendar_sha,
                "source_kind": "COMPOSITE_CURRENT_VINTAGE_FREE_PROXY",
                "source_sha256": lineage_sha,
                "truth_class": "FREE_PROXY",
            }
            context_observations: list[pd.Timestamp] = []
            context_availability: list[pd.Timestamp] = []
            if spy is not None and date in spy.index and pd.notna(spy.loc[date, "value"]):
                spy_close = spy["value"]
                context_observations.append(pd.Timestamp(spy.loc[date, "source_observation_date"]))
                context_availability.append(pd.Timestamp(spy.loc[date, "available_from"]))
                row["spy_close"] = float(spy_close.loc[date])
                prior = spy_close.loc[:date].iloc[:-1].tail(2)
                if len(prior) == 2 and prior.notna().all():
                    row["spy_prior_2d_high"] = float(prior.max())
                ma20_value = spy_close.rolling(20, min_periods=20).mean().loc[date]
                if pd.notna(ma20_value):
                    row["spy_ma20"] = float(ma20_value)
                rolling_low = spy_close.rolling(252, min_periods=200).min().loc[date]
                if pd.notna(rolling_low):
                    row["market_new_low"] = bool(spy_close.loc[date] <= rolling_low)
            if hy is not None and date in hy.index:
                hy_history = hy.loc[:date].dropna(subset=["value", "source_observation_date"])
                if len(hy_history) >= 2:
                    latest = hy_history.iloc[-1]
                    prior = hy_history.iloc[-2]
                    if pd.Timestamp(latest["source_observation_date"]) != pd.Timestamp(
                        prior["source_observation_date"]
                    ):
                        row["hy_spread_widening"] = bool(latest["value"] > prior["value"])
                        context_observations.append(pd.Timestamp(latest["source_observation_date"]))
                        context_availability.append(pd.Timestamp(latest["available_from"]))
            breadth50 = breadth_values.get("pct_above_ma50")
            if breadth50 is not None and date in breadth50.index:
                history = breadth50.loc[:date].dropna()
                if len(history) >= 2:
                    row["breadth_improving"] = bool(history.iloc[-1] > history.iloc[-2])
                    context_observations.append(date)
                    context_availability.append(
                        pd.Timestamp(calendar_map.loc[date, "decision_time_utc"])
                    )
                if spy is not None:
                    spy_history = spy["value"].loc[:date].dropna()
                    if len(spy_history) >= 252 and len(history) >= 20:
                        row["index_new_high_breadth_narrowing"] = bool(
                            spy_history.iloc[-1] >= spy_history.tail(252).max()
                            and history.iloc[-1] < history.tail(20).max()
                        )
            optional_columns = set(row) - {
                "decision_date",
                "decision_time_utc",
                "nyse_session_ordinal",
                "calendar_source_sha256",
                "source_kind",
                "source_sha256",
                "truth_class",
            }
            if not optional_columns or not context_observations or not context_availability:
                continue
            row["source_observation_date"] = max(context_observations).date().isoformat()
            row["available_from"] = max(context_availability).isoformat()
            context_rows.append(row)
        context = pd.DataFrame(context_rows)
        context_path = output_dir / "input_context.csv"
        context.to_csv(context_path, index=False)

        engine_result: dict[str, Any] | None = None
        if bool(args.run_engine):
            engine_result = risk_engine.build(
                argparse.Namespace(
                    calendar=str(calendar_path),
                    input_metrics=str(metrics_path),
                    input_context=str(context_path),
                    as_of=resolved_as_of.date().isoformat(),
                    contract=str(risk_engine.DEFAULT_CONTRACT),
                    output_dir=str(output_dir / "shadow_engine"),
                )
            )

        changed_inputs = [
            path
            for path, expected_sha in consumed_inputs.items()
            if not Path(path).is_file() or sha256_file(Path(path)) != expected_sha
        ]
        if changed_inputs:
            raise InputContractError(
                "consumed_input_changed_after_read:" + ",".join(changed_inputs)
            )

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "status": READY_STATUS,
            "requested_as_of": pd.Timestamp(requested_as_of).date().isoformat(),
            "resolved_as_of": resolved_as_of.date().isoformat(),
            "git_head": git_head(),
            "builder_sha256": sha256_file(Path(__file__).resolve()),
            "contract_semantic_sha256": CANONICAL_CONTRACT_SEMANTIC_SHA256,
            "truth_class": "FREE_PROXY",
            "historical_ab_allowed": False,
            "source_ready_count": int(source_audit["status"].eq("ready").sum()),
            "source_total_count": int(len(source_audit)),
            "metric_row_count": int(len(metrics)),
            "metric_component_count": int(metrics["component"].nunique()),
            "context_row_count": int(len(context)),
            "engine_status": None if engine_result is None else engine_result.get("status"),
            "outputs": {
                "calendar": {"path": str(calendar_path), "sha256": calendar_sha},
                "source_audit": {"path": str(source_audit_path), "sha256": sha256_file(source_audit_path)},
                "source_lineage": {"path": str(lineage_path), "sha256": lineage_sha},
                "metrics": {"path": str(metrics_path), "sha256": sha256_file(metrics_path)},
                "context": {"path": str(context_path), "sha256": sha256_file(context_path)},
                "shadow_engine_manifest": None
                if engine_result is None
                else {
                    "path": str(output_dir / "shadow_engine" / "manifest.json"),
                    "sha256": sha256_file(output_dir / "shadow_engine" / "manifest.json"),
                },
            },
            **SAFETY,
        }
        write_json(output_dir / "manifest.json", manifest)
        return manifest
    except Exception as exc:
        blocked = {
            "schema_version": SCHEMA_VERSION,
            "status": BLOCKED_STATUS,
            "blockers": [f"{type(exc).__name__}:{exc}"],
            **SAFETY,
        }
        write_json(output_dir / "manifest.json", blocked)
        return blocked


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--as-of", required=True)
    result.add_argument("--output-dir", required=True)
    result.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    result.add_argument("--source-bundle", default="")
    result.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    result.add_argument("--universe-file", default="")
    result.add_argument("--allow-network", action="store_true")
    result.add_argument("--http-timeout-seconds", type=int, default=30)
    result.add_argument("--run-engine", action=argparse.BooleanOptionalAction, default=True)
    return result


def main() -> int:
    manifest = build(parser().parse_args())
    print(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False))
    return 0 if manifest.get("status") == READY_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())

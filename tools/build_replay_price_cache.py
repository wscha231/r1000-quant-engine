#!/usr/bin/env python3
"""Build a minimal price cache for artifact-only replay workflows.

Full rebuild runners normally have cache_prices from the collector cache. A
fast replay run may not. This helper downloads only the tickers needed by
monthly books plus a bounded set of latest scored names, then writes the same
hashed parquet cache format consumed by run_weekly_evaluation.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import CASH_TICKERS, px_cache_name
from tools.validate_daily_close_prices import (  # noqa: E402
    collect_required_tickers as collect_close_required_tickers,
)


DEFAULT_OUTPUT = "cache_prices"
MAX_DOWNLOAD_RETRIES = 2
MAX_DOWNLOAD_ATTEMPTS = 1 + MAX_DOWNLOAD_RETRIES
PRICE_CACHE_TRANSACTION_JOURNAL = "replay_price_cache_transaction.json"
PRICE_CACHE_TRANSACTION_SCHEMA = "run287-price-cache-transaction-v1"

DownloadFn = Callable[
    [list[str], str, str],
    tuple[dict[str, pd.DataFrame], dict[str, Any]],
]

# Floor the auto-derived cache start so it always covers the official backtest
# start with warmup. Without this the cache started ~2019-06-14 (min_dt-14d) and
# the engine's first monthly fill snapped to 2019-07-01, yielding a 6.965y
# broker-ledger window < the 7.0y acceptance gate. Anchoring to
# OFFICIAL_BACKTEST_START_DATE - 25d lands the first month-end rebalance on
# 2019-05-31 -> fill 2019-06-03 -> ~7.04y (inside the [7.0, 7.05] band that also
# keeps the pit-universe-label gate moot). Guarded import + literal fallback so
# this tool never hard-fails on the heavy config import.
try:
    from r1000_config import OFFICIAL_BACKTEST_START_DATE as _OFFICIAL_BACKTEST_START_DATE
except Exception:  # pragma: no cover - config import is best-effort here
    _OFFICIAL_BACKTEST_START_DATE = "2019-06-03"
OFFICIAL_START_WARMUP_DAYS = 25


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def normalize_ticker(value: Any) -> str:
    ticker = str(value or "").upper().strip()
    if not ticker or ticker in CASH_TICKERS or ticker == "NAN":
        return ""
    return ticker


def yfinance_symbol(ticker: str) -> str:
    # Yahoo uses dashes for class-share tickers such as BRK.B.
    return str(ticker).replace(".", "-")


def collect_book_tickers(paths: list[Path]) -> tuple[set[str], pd.Timestamp | None, pd.Timestamp | None]:
    tickers: set[str] = set()
    min_dt: pd.Timestamp | None = None
    max_dt: pd.Timestamp | None = None
    for path in paths:
        frame = read_csv(path)
        if frame.empty or "ticker" not in frame.columns:
            continue
        for ticker in frame["ticker"].map(normalize_ticker):
            if ticker:
                tickers.add(ticker)
        if "rebalance_date" in frame.columns:
            dates = pd.to_datetime(frame["rebalance_date"], errors="coerce").dropna()
            if not dates.empty:
                cur_min = pd.Timestamp(dates.min()).normalize()
                cur_max = pd.Timestamp(dates.max()).normalize()
                min_dt = cur_min if min_dt is None else min(min_dt, cur_min)
                max_dt = cur_max if max_dt is None else max(max_dt, cur_max)
    return tickers, min_dt, max_dt


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if math.isfinite(out):
            return out
    except (TypeError, ValueError):
        pass
    return default


def collect_scored_tickers(path: Path, max_scored: int) -> set[str]:
    frame = read_csv(path)
    if frame.empty or "ticker" not in frame.columns or max_scored <= 0:
        return set()
    d = frame.copy()
    score_cols = [
        col
        for col in [
            "score",
            "raw_score",
            "portfolio_monster_early_score",
            "rs_acceleration_score",
            "h6_dynamic_leader_score",
            "relative_strength_composite",
            "dollar_volume_20d",
        ]
        if col in d.columns
    ]
    if score_cols:
        rank_score = pd.Series(0.0, index=d.index)
        for col in score_cols:
            series = pd.to_numeric(d[col], errors="coerce")
            if series.notna().any():
                rank_score = rank_score + series.rank(pct=True).fillna(0.0)
        d["_rank_score"] = rank_score
        d = d.sort_values("_rank_score", ascending=False)
    out: set[str] = set()
    for ticker in d["ticker"].map(normalize_ticker).head(max_scored):
        if ticker:
            out.add(ticker)
    return out


def parse_required_tickers(values: list[str] | str | None) -> set[str]:
    if not values:
        return set()
    if isinstance(values, str):
        raw_values = [values]
    else:
        raw_values = values
    out: set[str] = set()
    for value in raw_values:
        for token in str(value or "").replace(";", ",").split(","):
            ticker = normalize_ticker(token)
            if ticker:
                out.add(ticker)
    return out


def existing_cache_count(output_dir: Path, tickers: set[str]) -> int:
    return sum(1 for ticker in tickers if (output_dir / px_cache_name(ticker)).exists())


def naive_datetime_index(values: Any) -> pd.DatetimeIndex:
    """Preserve each timestamp's wall-clock date while removing its timezone."""

    normalized: list[pd.Timestamp] = []
    for value in values:
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError, OverflowError):
            timestamp = pd.NaT
        if pd.isna(timestamp):
            normalized.append(pd.NaT)
            continue
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_localize(None)
        normalized.append(timestamp)
    return pd.DatetimeIndex(normalized)


def naive_normalized_timestamp(value: Any, *, field: str) -> pd.Timestamp:
    timestamp = naive_datetime_index([value])[0]
    if pd.isna(timestamp):
        raise ValueError(f"{field}_invalid")
    return pd.Timestamp(timestamp).normalize()


def cached_max_date(output_dir: Path, ticker: str) -> pd.Timestamp | None:
    path = output_dir / px_cache_name(ticker)
    if not path.exists():
        return None
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return None
    if frame.empty:
        return None
    idx = naive_datetime_index(frame.index).dropna()
    if idx.empty:
        return None
    return pd.Timestamp(idx.max()).normalize()


def has_valid_exact_close(
    frame: pd.DataFrame,
    required_date: pd.Timestamp,
) -> bool:
    if frame is None or frame.empty:
        return False
    dates = naive_datetime_index(frame.index)
    required = pd.Timestamp(required_date)
    if required.tzinfo is not None:
        required = required.tz_localize(None)
    required = required.normalize()
    mask = dates.normalize() == required
    if int(mask.sum()) != 1:
        return False
    close_column = "Adj Close" if "Adj Close" in frame.columns else "Close"
    if close_column not in frame.columns:
        return False
    close_values = pd.to_numeric(
        frame.loc[mask, close_column],
        errors="coerce",
    ).dropna()
    if len(close_values) != 1:
        return False
    close = float(close_values.iloc[0])
    return math.isfinite(close) and close > 0.0


def cached_date_range(output_dir: Path, tickers: set[str]) -> tuple[pd.Timestamp | None, pd.Timestamp | None, int]:
    dates: list[pd.Timestamp] = []
    for ticker in sorted(tickers):
        path = output_dir / px_cache_name(ticker)
        if not path.exists():
            continue
        try:
            frame = pd.read_parquet(path)
        except Exception:
            continue
        if frame.empty:
            continue
        idx = naive_datetime_index(frame.index).dropna()
        if idx.empty:
            continue
        dates.append(pd.Timestamp(idx.min()).normalize())
        dates.append(pd.Timestamp(idx.max()).normalize())
    if not dates:
        return None, None, 0
    return min(dates), max(dates), len(dates) // 2


def common_cached_end(
    output_dir: Path,
    tickers: set[str],
) -> pd.Timestamp | None:
    if not tickers:
        return None
    dates = [cached_max_date(output_dir, ticker) for ticker in sorted(tickers)]
    if any(value is None for value in dates):
        return None
    return min(value for value in dates if value is not None)


def stale_cache_tickers(
    output_dir: Path,
    tickers: set[str],
    *,
    today: pd.Timestamp,
    refresh_stale_days: int,
) -> list[str]:
    if refresh_stale_days < 0:
        return []
    stale: list[str] = []
    for ticker in sorted(tickers):
        path = output_dir / px_cache_name(ticker)
        if not path.exists():
            continue
        max_dt = cached_max_date(output_dir, ticker)
        if max_dt is None:
            stale.append(ticker)
            continue
        if (today - max_dt).days > int(refresh_stale_days):
            stale.append(ticker)
    return stale


def cache_tickers_behind_date(
    output_dir: Path,
    tickers: set[str],
    required_through_date: pd.Timestamp | None,
) -> list[str]:
    if required_through_date is None:
        return []
    behind: list[str] = []
    for ticker in sorted(tickers):
        path = output_dir / px_cache_name(ticker)
        try:
            frame = pd.read_parquet(path)
        except Exception:
            frame = pd.DataFrame()
        if not has_valid_exact_close(frame, required_through_date):
            behind.append(ticker)
    return behind


def normalize_download_frame(data: pd.DataFrame, ticker: str, symbol: str) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame()
    frame = data.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        if ticker in frame.columns.get_level_values(0):
            frame = frame[ticker].copy()
        elif symbol in frame.columns.get_level_values(0):
            frame = frame[symbol].copy()
        elif ticker in frame.columns.get_level_values(-1):
            frame = frame.xs(ticker, axis=1, level=-1).copy()
        elif symbol in frame.columns.get_level_values(-1):
            frame = frame.xs(symbol, axis=1, level=-1).copy()
        else:
            return pd.DataFrame()
    keep = [col for col in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if col in frame.columns]
    if "Close" not in keep and "Adj Close" not in keep:
        return pd.DataFrame()
    out = frame[keep].copy()
    out.index = naive_datetime_index(out.index)
    out = out[out.index.notna()].sort_index()
    return out.dropna(how="all")


def download_yfinance(
    tickers: list[str],
    start: str,
    end: str,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    import yfinance as yf

    symbol_to_ticker = {yfinance_symbol(ticker): ticker for ticker in tickers}
    symbols = list(symbol_to_ticker.keys())
    try:
        data = yf.download(
            symbols if len(symbols) > 1 else symbols[0],
            start=start,
            end=end,
            auto_adjust=False,
            group_by="ticker",
            threads=True,
            progress=False,
            timeout=30,
        )
        error = ""
    except Exception as exc:
        data = pd.DataFrame()
        error = f"{type(exc).__name__}:{exc}"
    frames = {
        ticker: normalize_download_frame(data, ticker, symbol)
        for symbol, ticker in symbol_to_ticker.items()
    }
    return frames, {
        "provider": "yfinance",
        "provider_version": str(getattr(yf, "__version__", "")),
        "ticker_count": len(tickers),
        "start": start,
        "end_exclusive": end,
        "error": error,
    }


def run_download_batches(
    tickers: list[str],
    *,
    start: str,
    end: str,
    batch_size: int,
    attempt: int,
    download_fn: DownloadFn,
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    frames: dict[str, pd.DataFrame] = {}
    audits: list[dict[str, Any]] = []
    size = max(int(batch_size), 1)
    for offset in range(0, len(tickers), size):
        batch = tickers[offset : offset + size]
        try:
            downloaded, audit = download_fn(batch, start, end)
        except Exception as exc:
            downloaded = {}
            audit = {
                "provider": "download_fn",
                "error": f"{type(exc).__name__}:{exc}",
            }
        frames.update(downloaded)
        audits.append(
            {
                **audit,
                "attempt": int(attempt),
                "batch_index": offset // size + 1,
                "requested_tickers": list(batch),
            }
        )
    return frames, audits


def normalized_frame_for_required_date(
    frame: pd.DataFrame,
    required_through_date: pd.Timestamp | None,
) -> tuple[pd.DataFrame, str, str]:
    if frame is None or frame.empty:
        return pd.DataFrame(), "", "empty_download"
    normalized = frame.copy()
    normalized.index = naive_datetime_index(normalized.index)
    normalized = normalized.loc[normalized.index.notna()].sort_index()
    normalized = normalized.loc[~normalized.index.duplicated(keep="last")]
    if normalized.empty:
        return pd.DataFrame(), "", "invalid_download_index"
    latest = pd.Timestamp(normalized.index.max()).normalize()
    if required_through_date is None:
        return normalized, latest.date().isoformat(), ""
    normalized = normalized.loc[
        normalized.index.normalize() <= required_through_date
    ].copy()
    if normalized.empty:
        return (
            pd.DataFrame(),
            latest.date().isoformat(),
            "required_date_before_provider_start",
        )
    dates = pd.DatetimeIndex(normalized.index).normalize()
    if required_through_date not in dates:
        return (
            pd.DataFrame(),
            latest.date().isoformat(),
            "missing_exact_required_date",
        )
    if not has_valid_exact_close(normalized, required_through_date):
        return (
            pd.DataFrame(),
            latest.date().isoformat(),
            "invalid_exact_required_close",
        )
    return normalized, latest.date().isoformat(), ""


def normalize_price_history(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    normalized = frame.copy()
    normalized.index = naive_datetime_index(normalized.index)
    normalized = normalized.loc[normalized.index.notna()].sort_index()
    normalized = normalized.loc[~normalized.index.duplicated(keep="last")]
    if isinstance(normalized.columns, pd.MultiIndex):
        normalized.columns = normalized.columns.get_level_values(0)
    return normalized


def merge_price_history(
    existing: pd.DataFrame,
    provider: pd.DataFrame,
) -> pd.DataFrame:
    """Fill cache gaps from the provider without revising accepted history."""

    provider_normalized = normalize_price_history(provider)
    if provider_normalized.empty:
        raise ValueError("provider_price_history_empty")
    existing_normalized = normalize_price_history(existing)
    if existing_normalized.empty:
        return provider_normalized
    columns = list(existing_normalized.columns)
    columns.extend(
        column for column in provider_normalized.columns if column not in columns
    )
    merged = existing_normalized.reindex(columns=columns).combine_first(
        provider_normalized.reindex(columns=columns)
    )
    merged = merged.sort_index().reindex(columns=columns)
    merged.index.name = (
        existing_normalized.index.name
        or provider_normalized.index.name
    )
    return merged


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.parent.resolve() != path.parent.resolve():
        raise ValueError("json_stage_outside_output_dir")
    if temporary.exists():
        raise FileExistsError("json_stage_path_exists")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def price_cache_transaction_journal(output_dir: Path) -> Path:
    return output_dir / PRICE_CACHE_TRANSACTION_JOURNAL


def transaction_record_path(output_dir: Path, name: Any) -> Path:
    token = str(name or "")
    relative = Path(token)
    if (
        not token
        or relative.is_absolute()
        or relative.name != token
        or len(relative.parts) != 1
    ):
        raise ValueError("price_cache_transaction_path_invalid")
    path = output_dir / relative
    if path.parent.resolve() != output_dir.resolve():
        raise ValueError("price_cache_transaction_path_outside_output_dir")
    return path


def transaction_payload(transaction: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": PRICE_CACHE_TRANSACTION_SCHEMA,
        "transaction_id": transaction["transaction_id"],
        "phase": transaction["phase"],
        "records": transaction["records"],
    }


def validate_price_cache_transaction(
    transaction: dict[str, Any],
) -> None:
    output_dir = transaction.get("output_dir")
    if not isinstance(output_dir, Path):
        raise ValueError("price_cache_transaction_output_dir_invalid")
    transaction_id = str(transaction.get("transaction_id") or "")
    if re.fullmatch(r"[0-9a-f]{32}", transaction_id) is None:
        raise ValueError("price_cache_transaction_id_invalid")
    if transaction.get("phase") not in {"prepared", "committed"}:
        raise ValueError("price_cache_transaction_phase_invalid")
    records = transaction.get("records")
    if (
        not isinstance(records, list)
        or not records
        or len(records) > 5_000
    ):
        raise ValueError("price_cache_transaction_records_invalid")
    expected_keys = {
        "kind",
        "destination",
        "temporary",
        "backup",
        "had_destination",
        "original_sha256",
        "original_bytes",
        "staged_sha256",
        "staged_bytes",
    }
    used_paths: set[str] = set()
    manifest_count = 0
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != expected_keys:
            raise ValueError("price_cache_transaction_record_invalid")
        kind = record["kind"]
        destination_name = str(record["destination"])
        if kind == "price_parquet":
            if re.fullmatch(r"[0-9a-f]{16}\.parquet", destination_name) is None:
                raise ValueError(
                    "price_cache_transaction_price_destination_invalid"
                )
        elif kind == "manifest_json":
            manifest_count += 1
            if (
                destination_name != "replay_price_cache_manifest.json"
                or index != len(records) - 1
            ):
                raise ValueError(
                    "price_cache_transaction_manifest_destination_invalid"
                )
        else:
            raise ValueError("price_cache_transaction_kind_invalid")
        expected_temporary = (
            f".{destination_name}.{transaction_id}.{index}.tmp"
        )
        expected_backup = (
            f".{destination_name}.{transaction_id}.{index}.bak"
        )
        if (
            record["temporary"] != expected_temporary
            or record["backup"] != expected_backup
        ):
            raise ValueError("price_cache_transaction_stage_name_invalid")
        for field in ("destination", "temporary", "backup"):
            path = transaction_record_path(output_dir, record[field])
            if path.name in used_paths:
                raise ValueError("price_cache_transaction_path_duplicate")
            used_paths.add(path.name)
        if not isinstance(record["had_destination"], bool):
            raise ValueError(
                "price_cache_transaction_had_destination_invalid"
            )
        original_sha256 = str(record["original_sha256"])
        original_bytes = record["original_bytes"]
        if record["had_destination"]:
            if (
                re.fullmatch(r"[0-9a-f]{64}", original_sha256) is None
                or not isinstance(original_bytes, int)
                or isinstance(original_bytes, bool)
                or original_bytes <= 0
            ):
                raise ValueError(
                    "price_cache_transaction_original_identity_invalid"
                )
        elif original_sha256 != "" or original_bytes != 0:
            raise ValueError(
                "price_cache_transaction_absent_original_invalid"
            )
        if (
            re.fullmatch(r"[0-9a-f]{64}", str(record["staged_sha256"]))
            is None
            or not isinstance(record["staged_bytes"], int)
            or isinstance(record["staged_bytes"], bool)
            or record["staged_bytes"] <= 0
        ):
            raise ValueError(
                "price_cache_transaction_staged_identity_invalid"
            )
    if manifest_count > 1:
        raise ValueError("price_cache_transaction_manifest_count_invalid")


def persist_price_cache_transaction(transaction: dict[str, Any]) -> None:
    validate_price_cache_transaction(transaction)
    write_json_atomic(
        price_cache_transaction_journal(transaction["output_dir"]),
        transaction_payload(transaction),
    )


def new_transaction_record(
    output_dir: Path,
    destination: Path,
    *,
    transaction_id: str,
    index: int,
    kind: str,
) -> dict[str, Any]:
    if destination.parent.resolve() != output_dir.resolve():
        raise ValueError("price_cache_destination_outside_output_dir")
    suffix = f"{transaction_id}.{index}"
    temporary = destination.with_name(f".{destination.name}.{suffix}.tmp")
    backup = destination.with_name(f".{destination.name}.{suffix}.bak")
    for path in (temporary, backup):
        if path.parent.resolve() != output_dir.resolve():
            raise ValueError("price_cache_stage_outside_output_dir")
        if path.exists():
            raise FileExistsError("price_cache_stage_path_exists")
    if destination.exists() and not destination.is_file():
        raise ValueError("price_cache_destination_not_file")
    had_destination = destination.is_file()
    return {
        "kind": kind,
        "destination": destination.name,
        "temporary": temporary.name,
        "backup": backup.name,
        "had_destination": had_destination,
        "original_sha256": (
            sha256_file(destination)
            if had_destination
            else ""
        ),
        "original_bytes": (
            destination.stat().st_size
            if had_destination
            else 0
        ),
        "staged_sha256": "",
        "staged_bytes": 0,
    }


def require_file_identity(
    path: Path,
    *,
    expected_sha256: str,
    expected_bytes: int,
    label: str,
) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label}_missing:{path.name}")
    if (
        path.stat().st_size != expected_bytes
        or sha256_file(path) != expected_sha256
    ):
        raise ValueError(f"{label}_identity_mismatch:{path.name}")


def validate_transaction_install_state(
    transaction: dict[str, Any],
    records: list[dict[str, Any]],
) -> None:
    validate_price_cache_transaction(transaction)
    output_dir = transaction["output_dir"]
    record_ids = {id(record) for record in transaction["records"]}
    if any(id(record) not in record_ids for record in records):
        raise ValueError("price_cache_install_record_not_registered")
    for record in records:
        destination = transaction_record_path(
            output_dir,
            record["destination"],
        )
        temporary = transaction_record_path(
            output_dir,
            record["temporary"],
        )
        backup = transaction_record_path(output_dir, record["backup"])
        require_file_identity(
            temporary,
            expected_sha256=record["staged_sha256"],
            expected_bytes=record["staged_bytes"],
            label="price_cache_staged_file",
        )
        if backup.exists():
            raise ValueError(
                f"price_cache_backup_exists_before_install:{backup.name}"
            )
        if record["had_destination"]:
            require_file_identity(
                destination,
                expected_sha256=record["original_sha256"],
                expected_bytes=record["original_bytes"],
                label="price_cache_original",
            )
        elif destination.exists():
            raise ValueError(
                f"price_cache_new_destination_exists:{destination.name}"
            )


def install_price_cache_transaction(
    transaction: dict[str, Any],
    records: list[dict[str, Any]] | None = None,
    *,
    replace_fn: Callable[[str | Path, str | Path], Any] | None = None,
) -> None:
    output_dir = transaction["output_dir"]
    replacer = replace_fn or os.replace
    selected_records = (
        records if records is not None else transaction["records"]
    )
    validate_transaction_install_state(transaction, selected_records)
    for record in selected_records:
        destination = transaction_record_path(
            output_dir,
            record["destination"],
        )
        temporary = transaction_record_path(
            output_dir,
            record["temporary"],
        )
        backup = transaction_record_path(output_dir, record["backup"])
        if record["had_destination"]:
            replacer(destination, backup)
        replacer(temporary, destination)


def validate_transaction_rollback_state(
    transaction: dict[str, Any],
) -> None:
    validate_price_cache_transaction(transaction)
    output_dir = transaction["output_dir"]
    for record in transaction["records"]:
        destination = transaction_record_path(
            output_dir,
            record["destination"],
        )
        temporary = transaction_record_path(
            output_dir,
            record["temporary"],
        )
        backup = transaction_record_path(output_dir, record["backup"])
        if temporary.exists():
            require_file_identity(
                temporary,
                expected_sha256=record["staged_sha256"],
                expected_bytes=record["staged_bytes"],
                label="price_cache_staged_file",
            )
        if record["had_destination"]:
            if backup.exists():
                require_file_identity(
                    backup,
                    expected_sha256=record["original_sha256"],
                    expected_bytes=record["original_bytes"],
                    label="price_cache_backup",
                )
                if destination.exists():
                    require_file_identity(
                        destination,
                        expected_sha256=record["staged_sha256"],
                        expected_bytes=record["staged_bytes"],
                        label="price_cache_installed_file",
                    )
            else:
                require_file_identity(
                    destination,
                    expected_sha256=record["original_sha256"],
                    expected_bytes=record["original_bytes"],
                    label="price_cache_untouched_original",
                )
        else:
            if backup.exists():
                raise ValueError(
                    f"unexpected_price_cache_backup:{backup.name}"
                )
            if destination.exists():
                require_file_identity(
                    destination,
                    expected_sha256=record["staged_sha256"],
                    expected_bytes=record["staged_bytes"],
                    label="price_cache_installed_new_file",
                )


def rollback_price_cache_transaction(
    transaction: dict[str, Any],
    *,
    replace_fn: Callable[[str | Path, str | Path], Any] | None = None,
) -> None:
    validate_transaction_rollback_state(transaction)
    output_dir = transaction["output_dir"]
    replacer = replace_fn or os.replace
    rollback_errors: list[str] = []
    for record in reversed(transaction["records"]):
        destination = transaction_record_path(
            output_dir,
            record["destination"],
        )
        temporary = transaction_record_path(
            output_dir,
            record["temporary"],
        )
        backup = transaction_record_path(output_dir, record["backup"])
        try:
            if record["had_destination"]:
                if backup.is_file():
                    destination.unlink(missing_ok=True)
                    replacer(backup, destination)
                elif not destination.is_file():
                    raise FileNotFoundError(
                        f"price_cache_original_and_backup_missing:{destination.name}"
                    )
            else:
                destination.unlink(missing_ok=True)
                if backup.exists():
                    raise ValueError(
                        f"unexpected_price_cache_backup:{backup.name}"
                    )
            temporary.unlink(missing_ok=True)
        except Exception as exc:
            rollback_errors.append(
                f"{destination.name}:{type(exc).__name__}:{exc}"
            )
    if rollback_errors:
        raise RuntimeError(
            "price_cache_atomic_rollback_failed:"
            + ",".join(rollback_errors)
        )
    price_cache_transaction_journal(output_dir).unlink(missing_ok=True)


def verify_installed_price_cache_transaction(
    transaction: dict[str, Any],
) -> None:
    validate_price_cache_transaction(transaction)
    output_dir = transaction["output_dir"]
    manifest_payload: dict[str, Any] | None = None
    price_records: list[dict[str, Any]] = []
    for record in transaction["records"]:
        destination = transaction_record_path(
            output_dir,
            record["destination"],
        )
        require_file_identity(
            destination,
            expected_sha256=record["staged_sha256"],
            expected_bytes=record["staged_bytes"],
            label="price_cache_committed_file",
        )
        if record["kind"] == "manifest_json":
            try:
                manifest_payload = json.loads(
                    destination.read_text(encoding="utf-8")
                )
            except Exception as exc:
                raise ValueError(
                    "price_cache_committed_manifest_unreadable"
                ) from exc
        else:
            price_records.append(record)
    if manifest_payload is None:
        return
    if (
        manifest_payload.get("schema_version")
        != "run287-replay-price-cache-manifest-v2"
        or manifest_payload.get("status")
        not in {"already_cached", "completed"}
    ):
        raise ValueError("price_cache_manifest_contract_invalid")
    required_session = str(
        manifest_payload.get("refresh_through_date") or ""
    )
    if required_session and (
        manifest_payload.get("refresh_through_exact_coverage") is not True
        or manifest_payload.get("refresh_through_missing_tickers") != []
        or manifest_payload.get("refresh_through_exact_ticker_count")
        != manifest_payload.get("refresh_through_ticker_count")
    ):
        raise ValueError("price_cache_manifest_exact_coverage_invalid")
    cache_files = manifest_payload.get("cache_files")
    if not isinstance(cache_files, dict):
        raise ValueError("price_cache_manifest_cache_files_invalid")
    manifest_files: dict[str, dict[str, Any]] = {}
    for ticker, entry in cache_files.items():
        if not isinstance(entry, dict):
            raise ValueError("price_cache_manifest_cache_entry_invalid")
        normalized_ticker = normalize_ticker(ticker)
        filename = str(entry.get("file") or "")
        sha256 = str(entry.get("sha256") or "")
        size = entry.get("bytes")
        if (
            re.fullmatch(r"[0-9a-f]{16}\.parquet", filename) is None
            or not normalized_ticker
            or normalized_ticker != str(ticker)
            or filename != px_cache_name(normalized_ticker)
            or filename in manifest_files
            or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
        ):
            raise ValueError("price_cache_manifest_cache_entry_invalid")
        require_file_identity(
            transaction_record_path(output_dir, filename),
            expected_sha256=sha256,
            expected_bytes=size,
            label="price_cache_manifest_bound_file",
        )
        manifest_files[filename] = entry
    if required_session:
        expected_count = len(cache_files)
        if (
            expected_count <= 0
            or manifest_payload.get("ticker_count") != expected_count
            or manifest_payload.get("refresh_through_ticker_count")
            != expected_count
            or manifest_payload.get("refresh_through_exact_ticker_count")
            != expected_count
        ):
            raise ValueError(
                "price_cache_manifest_exact_count_parity_invalid"
            )
        required_date = naive_normalized_timestamp(
            required_session,
            field="manifest_refresh_through_date",
        )
        for ticker, entry in cache_files.items():
            path = transaction_record_path(output_dir, entry["file"])
            try:
                frame = pd.read_parquet(path)
            except Exception as exc:
                raise ValueError(
                    f"price_cache_manifest_exact_file_unreadable:{ticker}"
                ) from exc
            if not has_valid_exact_close(frame, required_date):
                raise ValueError(
                    f"price_cache_manifest_exact_close_missing:{ticker}"
                )
    for record in price_records:
        entry = manifest_files.get(record["destination"])
        if (
            entry is None
            or entry["sha256"] != record["staged_sha256"]
            or entry["bytes"] != record["staged_bytes"]
        ):
            raise ValueError(
                "price_cache_manifest_transaction_parity_invalid"
            )


def finalize_price_cache_transaction(
    transaction: dict[str, Any],
) -> None:
    verify_installed_price_cache_transaction(transaction)
    output_dir = transaction["output_dir"]
    for record in transaction["records"]:
        transaction_record_path(
            output_dir,
            record["temporary"],
        ).unlink(missing_ok=True)
        transaction_record_path(
            output_dir,
            record["backup"],
        ).unlink(missing_ok=True)
    price_cache_transaction_journal(output_dir).unlink(missing_ok=True)


def mark_price_cache_transaction_committed(
    transaction: dict[str, Any],
) -> None:
    verify_installed_price_cache_transaction(transaction)
    candidate = {**transaction, "phase": "committed"}
    persist_price_cache_transaction(candidate)
    transaction["phase"] = "committed"


def settle_price_cache_transaction(
    transaction: dict[str, Any],
    *,
    replace_fn: Callable[[str | Path, str | Path], Any] | None = None,
) -> None:
    if transaction["phase"] == "committed":
        finalize_price_cache_transaction(transaction)
    else:
        rollback_price_cache_transaction(
            transaction,
            replace_fn=replace_fn,
        )


def recover_price_cache_transaction(output_dir: Path) -> str:
    journal = price_cache_transaction_journal(output_dir)
    if not journal.is_file():
        return "none"
    try:
        payload = json.loads(journal.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("price_cache_transaction_journal_unreadable") from exc
    if payload.get("schema_version") != PRICE_CACHE_TRANSACTION_SCHEMA:
        raise ValueError("price_cache_transaction_schema_invalid")
    phase = str(payload.get("phase") or "")
    if phase not in {"prepared", "committed"}:
        raise ValueError("price_cache_transaction_phase_invalid")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("price_cache_transaction_records_invalid")
    transaction = {
        "output_dir": output_dir,
        "transaction_id": str(payload.get("transaction_id") or ""),
        "phase": phase,
        "records": records,
    }
    if not transaction["transaction_id"]:
        raise ValueError("price_cache_transaction_id_missing")
    validate_price_cache_transaction(transaction)
    if phase == "committed":
        finalize_price_cache_transaction(transaction)
        return "finalized_committed"
    rollback_price_cache_transaction(transaction)
    return "rolled_back_prepared"


def begin_price_cache_transaction(
    frames: dict[str, pd.DataFrame],
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    recover_price_cache_transaction(output_dir)
    transaction = {
        "output_dir": output_dir,
        "transaction_id": uuid.uuid4().hex,
        "phase": "prepared",
        "records": [],
    }
    try:
        for index, ticker in enumerate(sorted(frames)):
            destination = output_dir / px_cache_name(ticker)
            record = new_transaction_record(
                output_dir,
                destination,
                transaction_id=transaction["transaction_id"],
                index=index,
                kind="price_parquet",
            )
            transaction["records"].append(record)
            temporary = transaction_record_path(
                output_dir,
                record["temporary"],
            )
            frames[ticker].to_parquet(temporary)
            verified = pd.read_parquet(temporary)
            if verified.empty:
                raise ValueError(f"price_cache_stage_empty:{ticker}")
            record["staged_sha256"] = sha256_file(temporary)
            record["staged_bytes"] = temporary.stat().st_size
        if not transaction["records"]:
            raise ValueError("price_cache_transaction_empty")
        persist_price_cache_transaction(transaction)
        return transaction
    except BaseException:
        for record in transaction["records"]:
            transaction_record_path(
                output_dir,
                record["temporary"],
            ).unlink(missing_ok=True)
            transaction_record_path(
                output_dir,
                record["backup"],
            ).unlink(missing_ok=True)
        price_cache_transaction_journal(output_dir).unlink(missing_ok=True)
        raise


def publish_price_cache_manifest_transaction(
    transaction: dict[str, Any],
    manifest: Path,
    payload: dict[str, Any],
    *,
    replace_fn: Callable[[str | Path, str | Path], Any] | None = None,
) -> None:
    output_dir = transaction["output_dir"]
    record = new_transaction_record(
        output_dir,
        manifest,
        transaction_id=transaction["transaction_id"],
        index=len(transaction["records"]),
        kind="manifest_json",
    )
    temporary = transaction_record_path(output_dir, record["temporary"])
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        json.loads(temporary.read_text(encoding="utf-8"))
        record["staged_sha256"] = sha256_file(temporary)
        record["staged_bytes"] = temporary.stat().st_size
        candidate = {
            **transaction,
            "records": [*transaction["records"], record],
        }
        persist_price_cache_transaction(candidate)
        transaction["records"].append(record)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    install_price_cache_transaction(
        transaction,
        [record],
        replace_fn=replace_fn,
    )
    mark_price_cache_transaction_committed(transaction)
    finalize_price_cache_transaction(transaction)


def write_price_frames_atomically(
    frames: dict[str, pd.DataFrame],
    output_dir: Path,
    *,
    replace_fn: Callable[[str | Path, str | Path], Any] | None = None,
) -> None:
    """Journal, install, and recover a multi-parquet transaction."""

    transaction = begin_price_cache_transaction(frames, output_dir)
    try:
        install_price_cache_transaction(
            transaction,
            replace_fn=replace_fn,
        )
        mark_price_cache_transaction_committed(transaction)
        finalize_price_cache_transaction(transaction)
    except BaseException:
        settle_price_cache_transaction(
            transaction,
            replace_fn=replace_fn,
        )
        raise


def download_prices(
    tickers: list[str],
    start: str,
    end: str,
    output_dir: Path,
    batch_size: int,
    *,
    required_through_date: pd.Timestamp | None = None,
    download_fn: DownloadFn | None = None,
) -> dict[str, Any]:
    """Fetch once plus at most two retries; never publish a stale session."""

    downloader = download_fn or download_yfinance
    pending = sorted(set(tickers))
    accepted: dict[str, pd.DataFrame] = {}
    observed_latest_dates: dict[str, str] = {}
    failure_reasons: dict[str, str] = {}
    audits: list[dict[str, Any]] = []
    attempts = 0
    for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
        if not pending:
            break
        attempts = attempt
        attempt_size = (
            max(int(batch_size), 1)
            if attempt == 1
            else 1
        )
        downloaded, batch_audits = run_download_batches(
            pending,
            start=start,
            end=end,
            batch_size=attempt_size,
            attempt=attempt,
            download_fn=downloader,
        )
        audits.extend(batch_audits)
        next_pending: list[str] = []
        for ticker in pending:
            frame, latest, reason = normalized_frame_for_required_date(
                downloaded.get(ticker, pd.DataFrame()),
                required_through_date,
            )
            if latest:
                prior_latest = observed_latest_dates.get(ticker, "")
                observed_latest_dates[ticker] = max(prior_latest, latest)
            if frame.empty:
                failure_reasons[ticker] = reason or "download_rejected"
                next_pending.append(ticker)
            else:
                accepted[ticker] = frame
                failure_reasons.pop(ticker, None)
        pending = next_pending

    write_aborted = bool(required_through_date is not None and pending)
    if write_aborted:
        accepted = {}
    transaction: dict[str, Any] | None = None
    if accepted:
        merged_frames: dict[str, pd.DataFrame] = {}
        for ticker, provider in accepted.items():
            existing_path = output_dir / px_cache_name(ticker)
            if existing_path.exists():
                try:
                    existing = pd.read_parquet(existing_path)
                except Exception as exc:
                    raise ValueError(
                        f"existing_price_cache_unreadable:{ticker}"
                    ) from exc
            else:
                existing = pd.DataFrame()
            merged = merge_price_history(existing, provider)
            if (
                required_through_date is not None
                and not has_valid_exact_close(merged, required_through_date)
            ):
                raise ValueError(
                    f"merged_exact_required_close_invalid:{ticker}"
                )
            merged_frames[ticker] = merged
        transaction = begin_price_cache_transaction(
            merged_frames,
            output_dir,
        )
        try:
            install_price_cache_transaction(transaction)
        except BaseException:
            settle_price_cache_transaction(transaction)
            raise
    return {
        "written": len(accepted),
        "written_tickers": sorted(accepted),
        "failed": pending[:50],
        "failed_count": len(pending),
        "download_attempt_count": attempts,
        "download_retry_count": max(0, attempts - 1),
        "download_batch_audits": audits,
        "download_observed_latest_dates": {
            ticker: observed_latest_dates.get(ticker, "")
            for ticker in sorted(set(tickers))
        },
        "download_failure_reasons": {
            ticker: failure_reasons.get(ticker, "download_rejected")
            for ticker in pending
        },
        "required_through_write_aborted": write_aborted,
        "existing_cache_preserved_on_block": write_aborted,
        "_price_cache_transaction": transaction,
    }


def finalize_run_result(
    result: dict[str, Any],
    *,
    args: argparse.Namespace,
    output_dir: Path,
    tickers: list[str],
    refresh_through_date: pd.Timestamp | None,
    book_paths: list[Path],
    transaction: dict[str, Any] | None,
) -> dict[str, Any]:
    try:
        behind_required_date_after = cache_tickers_behind_date(
            output_dir,
            set(tickers),
            refresh_through_date,
        )
        result["behind_refresh_through_after"] = len(
            behind_required_date_after
        )
        result["refresh_through_missing_tickers"] = (
            behind_required_date_after[:50]
        )
        result["refresh_through_ticker_count"] = len(tickers)
        result["refresh_through_exact_ticker_count"] = (
            len(tickers) - len(behind_required_date_after)
            if refresh_through_date is not None
            else 0
        )
        result["refresh_through_exact_coverage"] = (
            not behind_required_date_after
            if refresh_through_date is not None
            else None
        )
        if (
            not args.dry_run
            and refresh_through_date is not None
            and behind_required_date_after
        ):
            result["status"] = "blocked_missing_required_through_date"
        result["existing_cache_count_after"] = existing_cache_count(
            output_dir,
            set(tickers),
        )
        actual_start, actual_end, actual_ticker_count = cached_date_range(
            output_dir,
            set(tickers),
        )
        actual_common_end = common_cached_end(output_dir, set(tickers))
        result["start"] = (
            actual_start.date().isoformat()
            if actual_start is not None
            else result["requested_start"]
        )
        result["end"] = (
            actual_end.date().isoformat()
            if actual_end is not None
            else ""
        )
        result["common_coverage_end"] = (
            actual_common_end.date().isoformat()
            if actual_common_end is not None
            else ""
        )
        result["actual_cached_ticker_count"] = int(actual_ticker_count)
        result["manifest_end_source"] = (
            "actual_cached_bars"
            if actual_end is not None
            else "missing_cache"
        )
        result.update(
            {
                "schema_version": "run287-replay-price-cache-manifest-v2",
                "book_inputs": [
                    {
                        "path": str(path),
                        "sha256": sha256_file(path),
                        "bytes": path.stat().st_size,
                    }
                    for path in book_paths
                    if path.is_file()
                ],
                "cache_files": {
                    ticker: {
                        "file": px_cache_name(ticker),
                        "sha256": sha256_file(
                            output_dir / px_cache_name(ticker)
                        ),
                        "bytes": (
                            output_dir / px_cache_name(ticker)
                        ).stat().st_size,
                    }
                    for ticker in tickers
                    if (output_dir / px_cache_name(ticker)).is_file()
                },
                "review_only": True,
                "production_mutation_allowed": False,
                "live_trading_enabled": False,
            }
        )
        manifest = output_dir / "replay_price_cache_manifest.json"
        if transaction is None:
            write_json_atomic(manifest, result)
        else:
            publish_price_cache_manifest_transaction(
                transaction,
                manifest,
                result,
            )
            transaction = None
        return result
    except BaseException:
        if transaction is not None:
            settle_price_cache_transaction(transaction)
        raise


def run(
    args: argparse.Namespace,
    *,
    download_fn: DownloadFn | None = None,
) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    transaction_recovery = recover_price_cache_transaction(output_dir)
    book_paths = [repo_path(x) for x in args.books]
    book_tickers, min_dt, max_dt = collect_book_tickers(book_paths)
    scored_tickers = collect_scored_tickers(repo_path(args.scored), args.max_scored) if args.scored else set()
    required_tickers = parse_required_tickers(getattr(args, "required_tickers", None))
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    refresh_through_raw = str(getattr(args, "refresh_through_date", "") or "").strip()
    refresh_through_date = (
        naive_normalized_timestamp(
            refresh_through_raw,
            field="refresh_through_date",
        )
        if refresh_through_raw
        else None
    )
    account_paths = [
        repo_path(path)
        for path in getattr(args, "accounts", [])
    ]
    state_dir_raw = str(getattr(args, "state_dir", "") or "").strip()
    state_dir = (
        repo_path(state_dir_raw)
        if state_dir_raw
        else output_dir / "__no_operating_state__"
    )
    operating_tickers: set[str] = set()
    operating_ticker_sources: dict[str, list[str]] = {}
    if bool(getattr(args, "exact_operating_universe", False)):
        operating_tickers, operating_ticker_sources = (
            collect_close_required_tickers(
                targets=book_paths,
                accounts=account_paths,
                state_dir=state_dir,
                required_tickers=required_tickers,
                session_date=refresh_through_date or today,
            )
        )
        book_tickers = set().union(
            *(
                set(values)
                for name, values in operating_ticker_sources.items()
                if name.startswith("target:")
            )
        ) if operating_ticker_sources else set()
        tickers = sorted(operating_tickers | scored_tickers)
    else:
        tickers = sorted(
            book_tickers | scored_tickers | required_tickers
        )
    if args.max_tickers and args.max_tickers > 0:
        tickers = sorted(
            set(tickers[: int(args.max_tickers)])
            | required_tickers
            | operating_tickers
        )
    if args.start:
        start_dt = naive_normalized_timestamp(args.start, field="start")
    else:
        derived = (min_dt or today - pd.DateOffset(years=8)) - pd.Timedelta(days=14)
        # Never start later than the official backtest start (minus warmup), so the
        # realized broker-ledger window reaches >=7.0y regardless of the prior
        # run's book min_dt.
        official_floor = pd.Timestamp(_OFFICIAL_BACKTEST_START_DATE).normalize() - pd.Timedelta(days=OFFICIAL_START_WARMUP_DAYS)
        start_dt = min(derived, official_floor)
    end_dt = (
        naive_normalized_timestamp(args.end, field="end")
        if args.end
        else today + pd.Timedelta(days=2)
    )
    missing = [ticker for ticker in tickers if not (output_dir / px_cache_name(ticker)).exists()]
    stale = stale_cache_tickers(
        output_dir,
        set(tickers),
        today=today,
        refresh_stale_days=args.refresh_stale_days,
    )
    behind_required_date = cache_tickers_behind_date(output_dir, set(tickers), refresh_through_date)
    download_targets = sorted(set(missing) | set(stale) | set(behind_required_date))
    result: dict[str, Any] = {
        "books": [str(path) for path in book_paths],
        "scored": str(repo_path(args.scored)) if args.scored else "",
        "ticker_count": len(tickers),
        "book_ticker_count": len(book_tickers),
        "scored_ticker_count": len(scored_tickers),
        "required_tickers": sorted(required_tickers),
        "required_ticker_count": len(required_tickers),
        "exact_operating_universe": bool(
            getattr(args, "exact_operating_universe", False)
        ),
        "operating_required_ticker_count": len(operating_tickers),
        "operating_ticker_sources": operating_ticker_sources,
        "accounts": [str(path) for path in account_paths],
        "state_dir": str(state_dir) if state_dir_raw else "",
        "existing_cache_count": existing_cache_count(output_dir, set(tickers)),
        "missing_before": len(missing),
        "stale_before": len(stale),
        "refresh_stale_days": int(args.refresh_stale_days),
        "refresh_through_date": refresh_through_date.date().isoformat() if refresh_through_date is not None else "",
        "behind_refresh_through_before": len(behind_required_date),
        "download_target_count": len(download_targets),
        "requested_start": start_dt.date().isoformat(),
        "requested_end": end_dt.date().isoformat(),
        "output_dir": str(output_dir),
        "transaction_recovery": transaction_recovery,
    }
    transaction: dict[str, Any] | None = None
    if args.dry_run or not download_targets:
        result.update({"downloaded": 0, "failed_count": 0, "failed": [], "status": "dry_run" if args.dry_run else "already_cached"})
    else:
        download_result = download_prices(
            download_targets,
            result["requested_start"],
            result["requested_end"],
            output_dir,
            args.batch_size,
            required_through_date=refresh_through_date,
            download_fn=download_fn,
        )
        transaction = download_result.pop(
            "_price_cache_transaction",
            None,
        )
        result.update(download_result)
        result["status"] = "completed"
    return finalize_run_result(
        result,
        args=args,
        output_dir=output_dir,
        tickers=tickers,
        refresh_through_date=refresh_through_date,
        book_paths=book_paths,
        transaction=transaction,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", nargs="+", required=True)
    parser.add_argument("--scored", default="")
    parser.add_argument("--max-scored", type=int, default=250)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--max-tickers", type=int, default=0)
    parser.add_argument(
        "--account",
        dest="accounts",
        action="append",
        default=[],
        help="Account JSON included by the shared exact-close ticker union.",
    )
    parser.add_argument(
        "--state-dir",
        default="",
        help="Paper state directory whose accounts and pending orders are included.",
    )
    parser.add_argument(
        "--exact-operating-universe",
        action="store_true",
        help="Use the same latest targets/accounts/pending-order ticker union as the exact-close gate.",
    )
    parser.add_argument(
        "--required-tickers",
        nargs="*",
        default=[],
        help="Tickers that must be included even if they are not in target books, e.g. SPY QQQ.",
    )
    parser.add_argument(
        "--refresh-stale-days",
        type=int,
        default=2,
        help="Refresh cached tickers whose latest cached bar is older than this many calendar days; use -1 to disable.",
    )
    parser.add_argument(
        "--refresh-through-date",
        default="",
        help="Refresh every selected ticker whose latest cached bar is before this required session date.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def exit_code_for_payload(payload: dict[str, Any]) -> int:
    status = str(payload.get("status") or "")
    if status == "blocked_missing_required_through_date":
        return 2
    if status in {"already_cached", "completed", "dry_run"}:
        return 0
    return 1


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return exit_code_for_payload(payload)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Audit data readiness before relying on a full rebuild or broker replay.

This tool is intentionally diagnostic. It does not mutate data and it does not
make strategy decisions. It answers the operational questions that caused the
recent stale replay problem:

* Is the free price cache populated and fresh enough?
* Is the SEC companyfacts archive present in the canonical free-data path?
* Do the latest target books and operating books reach the latest target date?
* Did the run leave a dated target snapshot that future replays can use?
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent


DATE_COLUMNS = [
    "rebalance_date",
    "feature_date",
    "as_of_date",
    "last_trade_date",
    "date",
    "Date",
]


CASH_TICKERS = {"CASH", "USD", "BIL", "SHV", "SGOV"}


FEATURE_SOURCE_GROUPS = {
    "price_momentum": [
        "ticker_ret_1m",
        "ticker_ret_3m",
        "ticker_ret_6m",
        "rs_benchmark_1m",
        "rs_benchmark_3m",
        "relative_strength_composite",
        "mom_3m",
        "mom_6m",
        "mom_12m",
        "atr14_pct",
        "volatility_contraction",
    ],
    "macro_regime": [
        "spy_1m_return",
        "qqq_1m_return",
        "market_style_regime_label",
        "regime_state",
        "regime_capacity_regime",
        "crisis_state",
        "macro_circuit_state",
        "macro_risk_score",
    ],
    "theme_leadership": [
        "theme_primary",
        "leadership_theme",
        "theme_phase_primary",
        "theme_horizon_primary",
        "theme_structural_growth_primary",
        "theme_leadership_score",
        "theme_state",
        "theme_rank",
    ],
    "sec_smart_money": [
        "smart_money_score",
        "sec_evidence_score",
        "sec_form4_score",
        "form4_net_buy_score",
        "institutional_13f_score",
        "institutional_accumulation_score",
        "rows_with_smart_money_evidence",
    ],
    "quality_confirmation": [
        "selection_confirmation_score",
        "breakout_setup_quality_score",
        "leader_quality_score",
        "quality_score",
        "fundamental_quality_score",
    ],
    "broker_policy": [
        "target_n",
        "weighting_mode",
        "action",
        "action_status",
        "entry_reason",
        "policy_reason",
        "rebalance_interval_months",
    ],
}


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, pd.Timestamp)):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def file_stats(path: Path) -> dict[str, Any]:
    exists = path.exists()
    if not exists:
        return {"exists": False, "path": str(path)}
    stat = path.stat()
    return {
        "exists": True,
        "path": str(path),
        "size_bytes": int(stat.st_size),
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            rows = sum(1 for _ in reader)
    except Exception:
        return 0
    return max(rows - 1, 0)


def read_csv_light(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, usecols=columns, low_memory=False) if columns else pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def latest_date_from_columns(frame: pd.DataFrame, columns: list[str] = DATE_COLUMNS) -> str:
    dates: list[pd.Timestamp] = []
    if frame.empty:
        return ""
    for col in columns:
        if col not in frame.columns:
            continue
        parsed = pd.to_datetime(frame[col], errors="coerce").dropna()
        if not parsed.empty:
            dates.append(pd.Timestamp(parsed.max()).normalize())
    if not dates:
        return ""
    return max(dates).date().isoformat()


def latest_observable_close_date(
    prices: dict[str, Any],
    operating_summary: dict[str, Any],
) -> str:
    operating_close_dates: list[date] = []
    for book in operating_summary.get("books") or []:
        if not isinstance(book, dict):
            continue
        close_dt = parse_date(book.get("latest_price_close_date"))
        if close_dt is not None:
            operating_close_dates.append(close_dt)
    if operating_close_dates:
        return max(operating_close_dates).isoformat()
    price_end = parse_date(prices.get("selected_manifest_end"))
    return price_end.isoformat() if price_end is not None else ""


def min_date_from_columns(frame: pd.DataFrame, columns: list[str] = DATE_COLUMNS) -> str:
    dates: list[pd.Timestamp] = []
    if frame.empty:
        return ""
    for col in columns:
        if col not in frame.columns:
            continue
        parsed = pd.to_datetime(frame[col], errors="coerce").dropna()
        if not parsed.empty:
            dates.append(pd.Timestamp(parsed.min()).normalize())
    if not dates:
        return ""
    return min(dates).date().isoformat()


def csv_summary(path: Path) -> dict[str, Any]:
    frame = read_csv_light(path)
    weight_sum = None
    ticker_count = None
    if not frame.empty and "weight" in frame.columns:
        weight_sum = float(pd.to_numeric(frame["weight"], errors="coerce").fillna(0.0).sum())
    if not frame.empty and "ticker" in frame.columns:
        ticker_count = int(frame["ticker"].astype(str).str.upper().nunique())
    return {
        "path": str(path),
        "exists": path.exists(),
        "row_count": int(len(frame)) if not frame.empty else count_csv_rows(path),
        "min_date": min_date_from_columns(frame),
        "max_date": latest_date_from_columns(frame),
        "ticker_count": ticker_count,
        "weight_sum": weight_sum,
    }


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).date()


def days_old(value: Any, today: date | None = None) -> int | None:
    dt = parse_date(value)
    if dt is None:
        return None
    base = today or datetime.now(timezone.utc).date()
    return int((base - dt).days)


def non_empty_mask(series: pd.Series) -> pd.Series:
    mask = series.notna()
    if series.dtype == object:
        text = series.astype(str).str.strip().str.lower()
        mask &= ~text.isin({"", "nan", "none", "null"})
    return mask.fillna(False)


def first_existing_column(frame: pd.DataFrame, columns: list[str]) -> str:
    for column in columns:
        if column in frame.columns:
            return column
    return ""


def parse_datetime_series(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce", utc=True)
    if not isinstance(parsed, pd.Series):
        return pd.Series(dtype="datetime64[ns]")
    return parsed.dt.tz_convert(None).dt.normalize()


def feature_category_coverage(frame: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    present = [column for column in columns if column in frame.columns]
    missing = [column for column in columns if column not in frame.columns]
    if frame.empty or not present:
        return {
            "present_columns": present,
            "missing_columns": missing,
            "present_count": int(len(present)),
            "missing_count": int(len(missing)),
            "row_any_feature_coverage_ratio": None,
            "average_present_column_coverage_ratio": None,
            "per_column_coverage_ratio": {},
        }
    coverage = pd.DataFrame({column: non_empty_mask(frame[column]) for column in present})
    per_column = {column: float(coverage[column].mean()) for column in present}
    return {
        "present_columns": present,
        "missing_columns": missing,
        "present_count": int(len(present)),
        "missing_count": int(len(missing)),
        "row_any_feature_coverage_ratio": float(coverage.any(axis=1).mean()),
        "average_present_column_coverage_ratio": float(coverage.mean().mean()),
        "per_column_coverage_ratio": per_column,
    }


def monthly_feature_coverage(frame: pd.DataFrame, date_column: str) -> list[dict[str, Any]]:
    if frame.empty or not date_column:
        return []
    dated = frame.copy()
    dated["_coverage_date"] = parse_datetime_series(dated[date_column])
    dated = dated.dropna(subset=["_coverage_date"])
    if dated.empty:
        return []
    rows: list[dict[str, Any]] = []
    for coverage_date, group in dated.groupby("_coverage_date", sort=True):
        ticker_count = None
        if "ticker" in group.columns:
            ticker_count = int(group["ticker"].astype(str).str.upper().nunique())
        category_rows = {}
        for name, columns in FEATURE_SOURCE_GROUPS.items():
            present = [column for column in columns if column in group.columns]
            if present:
                coverage = pd.DataFrame({column: non_empty_mask(group[column]) for column in present})
                category_rows[name] = {
                    "present_count": int(len(present)),
                    "row_any_feature_coverage_ratio": float(coverage.any(axis=1).mean()),
                    "average_present_column_coverage_ratio": float(coverage.mean().mean()),
                }
            else:
                category_rows[name] = {
                    "present_count": 0,
                    "row_any_feature_coverage_ratio": None,
                    "average_present_column_coverage_ratio": None,
                }
        rows.append(
            {
                "rebalance_date": pd.Timestamp(coverage_date).date().isoformat(),
                "row_count": int(len(group)),
                "ticker_count": ticker_count,
                "categories": category_rows,
            }
        )
    return rows


def available_from_columns(frame: pd.DataFrame) -> list[str]:
    columns: list[str] = []
    for column in frame.columns:
        lowered = column.lower()
        if lowered in {"available_from", "latest_available_from", "evidence_available_from"} or lowered.endswith("_available_from"):
            columns.append(column)
    return columns


def pit_available_from_check(frame: pd.DataFrame, date_column: str) -> dict[str, Any]:
    columns = available_from_columns(frame)
    if frame.empty or not date_column or not columns:
        return {
            "date_column": date_column,
            "available_from_columns": columns,
            "rows_with_any_future_available_from": 0,
            "future_available_from_by_column": {},
            "max_future_days": 0,
            "examples": [],
        }
    rebalance_dates = parse_datetime_series(frame[date_column])
    any_future = pd.Series(False, index=frame.index)
    by_column: dict[str, int] = {}
    max_future_days = 0
    examples: list[dict[str, Any]] = []
    for column in columns:
        available_dates = parse_datetime_series(frame[column])
        deltas = (available_dates - rebalance_dates).dt.days
        future = deltas > 0
        count = int(future.fillna(False).sum())
        by_column[column] = count
        if count <= 0:
            continue
        any_future |= future.fillna(False)
        column_max = deltas[future].max()
        if pd.notna(column_max):
            max_future_days = max(max_future_days, int(column_max))
        for idx in list(frame.index[future])[:5]:
            row = frame.loc[idx]
            examples.append(
                {
                    "column": column,
                    "rebalance_date": pd.Timestamp(rebalance_dates.loc[idx]).date().isoformat()
                    if pd.notna(rebalance_dates.loc[idx])
                    else "",
                    "available_from": pd.Timestamp(available_dates.loc[idx]).date().isoformat()
                    if pd.notna(available_dates.loc[idx])
                    else "",
                    "days_future": int(deltas.loc[idx]) if pd.notna(deltas.loc[idx]) else None,
                    "ticker": str(row.get("ticker", "")),
                }
            )
    return {
        "date_column": date_column,
        "available_from_columns": columns,
        "rows_with_any_future_available_from": int(any_future.sum()),
        "future_available_from_by_column": by_column,
        "max_future_days": int(max_future_days),
        "examples": examples[:20],
    }


def price_cache_summary(price_cache: Path, free_data_root: Path) -> dict[str, Any]:
    files = sorted(path for path in price_cache.glob("*.parquet") if path.is_file()) if price_cache.exists() else []
    root_manifest = read_json(price_cache / "replay_price_cache_manifest.json")
    free_manifest = read_json(free_data_root / "prices" / "replay_price_cache_manifest.json")
    manifest = free_manifest or root_manifest
    latest_mtime = ""
    if files:
        latest = max(path.stat().st_mtime for path in files)
        latest_mtime = datetime.fromtimestamp(latest, timezone.utc).isoformat()
    return {
        "cache_path": str(price_cache),
        "file_count": int(len(files)),
        "latest_file_modified_utc": latest_mtime,
        "root_manifest": {
            "path": str(price_cache / "replay_price_cache_manifest.json"),
            "exists": bool(root_manifest),
            "start": root_manifest.get("start"),
            "end": root_manifest.get("end"),
            "ticker_count": root_manifest.get("ticker_count"),
            "failed_count": root_manifest.get("failed_count"),
            "status": root_manifest.get("status"),
        },
        "free_data_manifest": {
            "path": str(free_data_root / "prices" / "replay_price_cache_manifest.json"),
            "exists": bool(free_manifest),
            "start": free_manifest.get("start"),
            "end": free_manifest.get("end"),
            "ticker_count": free_manifest.get("ticker_count"),
            "failed_count": free_manifest.get("failed_count"),
            "status": free_manifest.get("status"),
        },
        "selected_manifest_end": manifest.get("end"),
        "selected_manifest_ticker_count": manifest.get("ticker_count"),
        "selected_manifest_failed_count": manifest.get("failed_count"),
        "selected_manifest_status": manifest.get("status"),
    }


def fundamentals_summary(free_data_root: Path, latest_run: Path) -> dict[str, Any]:
    candidates = [
        free_data_root / "sec" / "companyfacts.zip",
        REPO_ROOT / "companyfacts.zip",
        latest_run / "companyfacts.zip",
        latest_run / "outputs" / "companyfacts.zip",
    ]
    return {
        "canonical_path": str(free_data_root / "sec" / "companyfacts.zip"),
        "candidates": [file_stats(path) for path in candidates],
        "canonical_available": (free_data_root / "sec" / "companyfacts.zip").exists(),
        "any_available": any(path.exists() for path in candidates),
    }


def sec_evidence_store_summary(latest_run: Path) -> dict[str, Any]:
    root = latest_run.parent
    files = {
        "form4_transactions": [
            root / "data_pit" / "sec" / "form4_transactions.parquet",
            latest_run / "data_pit" / "sec" / "form4_transactions.parquet",
            REPO_ROOT / "data_pit" / "sec" / "form4_transactions.parquet",
        ],
        "institutional_13f_holdings": [
            root / "data_pit" / "sec" / "institutional_13f_holdings.parquet",
            latest_run / "data_pit" / "sec" / "institutional_13f_holdings.parquet",
            REPO_ROOT / "data_pit" / "sec" / "institutional_13f_holdings.parquet",
        ],
        "etf_holdings": [
            root / "data_pit" / "etf_holdings" / "etf_holdings.parquet",
            latest_run / "data_pit" / "etf_holdings" / "etf_holdings.parquet",
            REPO_ROOT / "data_pit" / "etf_holdings" / "etf_holdings.parquet",
        ],
        "sec_enriched_candidate": [
            latest_run / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv",
            root / "outputs" / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv",
            REPO_ROOT / "outputs" / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv",
        ],
    }
    entries: dict[str, Any] = {}
    for name, candidates in files.items():
        entries[name] = {
            "candidates": [file_stats(path) for path in candidates],
            "any_available": any(path.exists() for path in candidates),
        }
    return {
        "files": entries,
        "any_available": any(item["any_available"] for item in entries.values()),
    }


def macro_summary(free_data_root: Path, latest_run: Path) -> dict[str, Any]:
    candidates = [
        free_data_root / "macro",
        latest_run.parent / "data_pit" / "macro",
        latest_run / "data_pit" / "macro",
        REPO_ROOT / "data_pit" / "macro",
        REPO_ROOT / "cache_macro",
        latest_run / "macro",
        latest_run / "macro_policy_engine",
    ]
    rows: list[dict[str, Any]] = []
    for path in candidates:
        if path.exists() and path.is_dir():
            file_count = sum(1 for item in path.rglob("*") if item.is_file())
            rows.append({"path": str(path), "exists": True, "file_count": int(file_count)})
        else:
            rows.append({"path": str(path), "exists": path.exists(), "file_count": 0})
    return {"candidates": rows, "any_available": any(row["file_count"] > 0 for row in rows)}


def target_snapshot_summary(latest_run: Path) -> dict[str, Any]:
    root = latest_run / "target_snapshots"
    latest_manifest = read_json(root / "latest_manifest.json")
    dated_dirs = sorted([path for path in root.iterdir() if path.is_dir()]) if root.exists() else []
    return {
        "path": str(root),
        "exists": root.exists(),
        "dated_snapshot_count": int(len(dated_dirs)),
        "latest_manifest_exists": bool(latest_manifest),
        "latest_snapshot_date": latest_manifest.get("snapshot_date", ""),
        "latest_manifest_path": str(root / "latest_manifest.json"),
    }


def feature_source_coverage_for_book(path: Path, portfolio: str) -> dict[str, Any]:
    frame = read_csv_light(path)
    date_column = first_existing_column(frame, DATE_COLUMNS)
    if frame.empty:
        return {
            "portfolio": portfolio,
            "path": str(path),
            "exists": path.exists(),
            "row_count": int(count_csv_rows(path)),
            "non_cash_row_count": 0,
            "date_column": date_column,
            "min_date": "",
            "max_date": "",
            "categories": {
                name: feature_category_coverage(pd.DataFrame(), columns)
                for name, columns in FEATURE_SOURCE_GROUPS.items()
            },
            "monthly": [],
            "pit_available_from_check": pit_available_from_check(pd.DataFrame(), date_column),
        }
    non_cash = frame
    if "ticker" in frame.columns:
        tickers = frame["ticker"].astype(str).str.upper().str.strip()
        non_cash = frame.loc[~tickers.isin(CASH_TICKERS)].copy()
    categories = {
        name: feature_category_coverage(non_cash, columns)
        for name, columns in FEATURE_SOURCE_GROUPS.items()
    }
    pit_check = pit_available_from_check(non_cash, date_column)
    ticker_count = None
    non_cash_ticker_count = None
    if "ticker" in frame.columns:
        ticker_count = int(frame["ticker"].astype(str).str.upper().nunique())
        non_cash_ticker_count = int(non_cash["ticker"].astype(str).str.upper().nunique()) if not non_cash.empty else 0
    return {
        "portfolio": portfolio,
        "path": str(path),
        "exists": path.exists(),
        "row_count": int(len(frame)),
        "non_cash_row_count": int(len(non_cash)),
        "ticker_count": ticker_count,
        "non_cash_ticker_count": non_cash_ticker_count,
        "date_column": date_column,
        "min_date": min_date_from_columns(frame, [date_column] if date_column else DATE_COLUMNS),
        "max_date": latest_date_from_columns(frame, [date_column] if date_column else DATE_COLUMNS),
        "categories": categories,
        "monthly": monthly_feature_coverage(non_cash, date_column),
        "pit_available_from_check": pit_check,
    }


def feature_source_coverage_summary(latest_run: Path) -> dict[str, Any]:
    books = {
        "main": feature_source_coverage_for_book(latest_run / "reports" / "operating_main_target_book.csv", "main"),
        "concentrated": feature_source_coverage_for_book(
            latest_run / "reports" / "operating_concentrated_target_book.csv",
            "concentrated",
        ),
    }
    future_rows = sum(
        int((book.get("pit_available_from_check") or {}).get("rows_with_any_future_available_from") or 0)
        for book in books.values()
    )
    available_from_column_count = sum(
        len((book.get("pit_available_from_check") or {}).get("available_from_columns") or [])
        for book in books.values()
    )
    missing_by_category: dict[str, list[str]] = {}
    for category in FEATURE_SOURCE_GROUPS:
        missing_by_category[category] = [
            portfolio
            for portfolio, book in books.items()
            if not ((book.get("categories") or {}).get(category) or {}).get("present_columns")
        ]
    return {
        "schema_version": "feature-source-coverage-v1",
        "status": "pit_review" if future_rows else "ok",
        "books": books,
        "overall": {
            "pit_future_available_from_rows": int(future_rows),
            "available_from_column_count": int(available_from_column_count),
            "missing_feature_groups_by_portfolio": missing_by_category,
        },
        "rules": {
            "coverage_scope": "operating target books, non-cash rows",
            "pit_rule": "available_from/latest_available_from columns must be on or before rebalance_date",
            "missing_feature_group_policy": "reported for review; not a blocker until a group is required by production policy",
        },
    }


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    free_data_root = repo_path(args.free_data_root)
    coverage_path = repo_path(args.coverage)
    manifest_path = repo_path(args.manifest)

    prices = price_cache_summary(price_cache, free_data_root)
    fundamentals = fundamentals_summary(free_data_root, latest_run)
    sec_evidence_store = sec_evidence_store_summary(latest_run)
    macro = macro_summary(free_data_root, latest_run)
    coverage = read_json(coverage_path)
    manifest = read_json(manifest_path)

    scored = csv_summary(latest_run / "scored_latest.csv")
    main_latest = csv_summary(latest_run / "portfolio_latest.csv")
    concentrated_latest = csv_summary(latest_run / "concentrated_portfolio_latest.csv")
    main_history = csv_summary(latest_run / "reports" / "main_monthly_weights.csv")
    concentrated_history = csv_summary(latest_run / "reports" / "concentrated_strategy_holdings.csv")
    operating_main = csv_summary(latest_run / "reports" / "operating_main_target_book.csv")
    operating_concentrated = csv_summary(latest_run / "reports" / "operating_concentrated_target_book.csv")
    operating_summary = read_json(latest_run / "reports" / "operating_target_books_summary.json")
    snapshots = target_snapshot_summary(latest_run)
    feature_source_coverage = feature_source_coverage_summary(latest_run)

    blockers: list[str] = []
    warnings: list[str] = []
    next_actions: list[str] = []

    price_file_count = int(prices.get("file_count") or 0)
    if price_file_count < int(args.min_price_files):
        warnings.append(f"price cache has only {price_file_count} parquet files; collector or Drive restore is required before skip_collector runs")
        next_actions.append("Restore/cache price parquet files from Google Drive or run tools/build_replay_price_cache.py before replay.")
    manifest_age = days_old(prices.get("selected_manifest_end"))
    if manifest_age is None:
        warnings.append("price cache manifest end date is missing")
    elif manifest_age > int(args.max_stale_days):
        warnings.append(f"price cache manifest is stale by {manifest_age} calendar days")
        next_actions.append("Run free_data_daily_update or a collector refresh after the latest market close.")

    if not fundamentals["canonical_available"]:
        warnings.append("canonical data_raw/free/sec/companyfacts.zip is missing")
        next_actions.append("Restore root companyfacts.zip into data_raw/free/sec or run the SEC companyfacts bootstrap.")
    companyfacts_blocker = "no SEC companyfacts archive was found in canonical, root, or latest-run paths"
    if not fundamentals["any_available"]:
        blockers.append(companyfacts_blocker)
    if not macro.get("any_available"):
        blockers.append("macro data was not found in data_raw/free/macro, data_pit/macro, cache_macro, or latest-run outputs")

    if int(scored.get("row_count") or 0) < int(args.min_scored_rows):
        blockers.append(f"scored_latest.csv row count is below threshold: {scored.get('row_count')}")
    if not main_latest.get("exists"):
        blockers.append("portfolio_latest.csv is missing")
    if not concentrated_latest.get("exists"):
        blockers.append("concentrated_portfolio_latest.csv is missing")

    latest_target_dates = [
        parse_date(main_latest.get("max_date")),
        parse_date(concentrated_latest.get("max_date")),
    ]
    latest_target_dates = [dt for dt in latest_target_dates if dt is not None]
    latest_target_date = max(latest_target_dates).isoformat() if latest_target_dates else ""
    observable_close_date = latest_observable_close_date(prices, operating_summary)
    effective_target_dt = parse_date(latest_target_date)
    observable_dt = parse_date(observable_close_date)
    if effective_target_dt and observable_dt and effective_target_dt > observable_dt:
        effective_target_dt = observable_dt
        warnings.append(
            f"latest target date {latest_target_date} is after latest observable close {observable_close_date}; freshness gate uses observable close"
        )
    effective_latest_target_date = effective_target_dt.isoformat() if effective_target_dt else ""
    for portfolio, book in [("main", operating_main), ("concentrated", operating_concentrated)]:
        if not book.get("exists"):
            warnings.append(f"{portfolio} operating target book is missing")
            continue
        book_dt = parse_date(book.get("max_date"))
        target_dt = parse_date(effective_latest_target_date)
        if book_dt and target_dt and book_dt < target_dt:
            blockers.append(f"{portfolio} operating target book max date {book_dt} is older than latest target date {target_dt}")

    if not snapshots["latest_manifest_exists"]:
        warnings.append("dated target snapshot archive is missing for this run")
        next_actions.append("Run tools/archive_target_snapshots.py after operating target books are built.")

    known_gaps = coverage.get("known_gaps") or []
    if known_gaps:
        warnings.extend(f"free-data gap: {gap}" for gap in known_gaps)
    future_available_from_rows = int((feature_source_coverage.get("overall") or {}).get("pit_future_available_from_rows") or 0)
    if future_available_from_rows:
        warnings.append(
            f"feature source coverage found {future_available_from_rows} target-book rows with available_from after rebalance_date"
        )

    policy_replay_blockers = list(blockers)
    if sec_evidence_store.get("any_available") and companyfacts_blocker in policy_replay_blockers:
        policy_replay_blockers.remove(companyfacts_blocker)
    ready_for_fullrun = not blockers
    ready_for_policy_replay = not policy_replay_blockers and price_file_count >= int(args.min_price_files)
    status = "ready" if ready_for_fullrun and not warnings else ("blocked" if blockers else "warn")
    payload = {
        "schema_version": "data-readiness-v1",
        "generated_at_utc": now_utc(),
        "status": status,
        "ready_for_fullrun": bool(ready_for_fullrun),
        "ready_for_skip_collector_replay": bool(ready_for_fullrun and price_file_count >= int(args.min_price_files)),
        "ready_for_policy_replay": bool(ready_for_policy_replay),
        "policy_replay_blockers": policy_replay_blockers,
        "latest_target_date": latest_target_date,
        "latest_observable_close_date": observable_close_date,
        "effective_latest_target_date": effective_latest_target_date,
        "latest_run": str(latest_run),
        "price_cache": prices,
        "fundamentals": fundamentals,
        "sec_evidence_store": sec_evidence_store,
        "macro": macro,
        "free_data_coverage": {
            "path": str(coverage_path),
            "exists": bool(coverage),
            "readiness": coverage.get("readiness"),
            "pit_label": coverage.get("pit_label"),
            "known_gaps": known_gaps,
        },
        "free_data_manifest": {
            "path": str(manifest_path),
            "exists": bool(manifest),
            "generated_at_utc": manifest.get("generated_at_utc"),
            "status": manifest.get("status"),
        },
        "latest_outputs": {
            "scored_latest": scored,
            "portfolio_latest": main_latest,
            "concentrated_portfolio_latest": concentrated_latest,
        },
        "target_books": {
            "main_history": main_history,
            "concentrated_history": concentrated_history,
            "operating_main": operating_main,
            "operating_concentrated": operating_concentrated,
            "operating_summary": operating_summary,
        },
        "feature_source_coverage": feature_source_coverage,
        "target_snapshots": snapshots,
        "blockers": blockers,
        "warnings": warnings,
        "next_actions": sorted(set(next_actions)),
    }
    return payload


def render_report(payload: dict[str, Any]) -> str:
    prices = payload.get("price_cache", {})
    latest = payload.get("latest_outputs", {})
    books = payload.get("target_books", {})
    lines = [
        "# Data Readiness Audit",
        "",
        f"- status: `{payload.get('status')}`",
        f"- ready_for_fullrun: `{str(payload.get('ready_for_fullrun')).lower()}`",
        f"- ready_for_skip_collector_replay: `{str(payload.get('ready_for_skip_collector_replay')).lower()}`",
        f"- ready_for_policy_replay: `{str(payload.get('ready_for_policy_replay')).lower()}`",
        f"- latest_target_date: `{payload.get('latest_target_date') or ''}`",
        f"- latest_observable_close_date: `{payload.get('latest_observable_close_date') or ''}`",
        f"- effective_latest_target_date: `{payload.get('effective_latest_target_date') or ''}`",
        "",
        "## Prices",
        "",
        f"- cache files: `{prices.get('file_count')}`",
        f"- manifest end: `{prices.get('selected_manifest_end') or ''}`",
        f"- manifest tickers: `{prices.get('selected_manifest_ticker_count') or ''}`",
        "",
        "## Latest Outputs",
        "",
        "| File | Rows | Max date | Weight sum |",
        "| --- | ---: | --- | ---: |",
    ]
    for name in ["scored_latest", "portfolio_latest", "concentrated_portfolio_latest"]:
        row = latest.get(name, {})
        lines.append(
            f"| {name} | {row.get('row_count', 0)} | {row.get('max_date') or ''} | {row.get('weight_sum') if row.get('weight_sum') is not None else ''} |"
        )
    lines.extend(["", "## Target Books", "", "| Book | Rows | Min date | Max date | Weight sum |", "| --- | ---: | --- | --- | ---: |"])
    for name in ["main_history", "concentrated_history", "operating_main", "operating_concentrated"]:
        row = books.get(name, {})
        lines.append(
            f"| {name} | {row.get('row_count', 0)} | {row.get('min_date') or ''} | {row.get('max_date') or ''} | {row.get('weight_sum') if row.get('weight_sum') is not None else ''} |"
        )
    feature_coverage = payload.get("feature_source_coverage") or {}
    feature_overall = feature_coverage.get("overall") or {}
    lines.extend(
        [
            "",
            "## Feature Source Coverage",
            "",
            f"- status: `{feature_coverage.get('status') or ''}`",
            f"- pit_future_available_from_rows: `{feature_overall.get('pit_future_available_from_rows', 0)}`",
            "",
            "| Portfolio | Rows | Non-cash rows | Date range | Available-from columns |",
            "| --- | ---: | ---: | --- | ---: |",
        ]
    )
    for portfolio, book in (feature_coverage.get("books") or {}).items():
        pit = book.get("pit_available_from_check") or {}
        lines.append(
            f"| {portfolio} | {book.get('row_count', 0)} | {book.get('non_cash_row_count', 0)} | {book.get('min_date') or ''} to {book.get('max_date') or ''} | {len(pit.get('available_from_columns') or [])} |"
        )
    lines.extend(["", "## Blockers", ""])
    blockers = payload.get("blockers") or []
    lines.extend([f"- {item}" for item in blockers] if blockers else ["- none"])
    lines.extend(["", "## Warnings", ""])
    warnings = payload.get("warnings") or []
    lines.extend([f"- {item}" for item in warnings] if warnings else ["- none"])
    lines.extend(["", "## Next Actions", ""])
    actions = payload.get("next_actions") or []
    lines.extend([f"- {item}" for item in actions] if actions else ["- none"])
    lines.append("")
    return "\n".join(lines)


def write_feature_source_coverage_csv(path: Path, payload: dict[str, Any]) -> None:
    feature_coverage = payload.get("feature_source_coverage") or {}
    rows: list[dict[str, Any]] = []
    for portfolio, book in (feature_coverage.get("books") or {}).items():
        for month in book.get("monthly") or []:
            for category, coverage in (month.get("categories") or {}).items():
                rows.append(
                    {
                        "portfolio": portfolio,
                        "rebalance_date": month.get("rebalance_date"),
                        "row_count": month.get("row_count"),
                        "ticker_count": month.get("ticker_count"),
                        "category": category,
                        "present_count": coverage.get("present_count"),
                        "row_any_feature_coverage_ratio": coverage.get("row_any_feature_coverage_ratio"),
                        "average_present_column_coverage_ratio": coverage.get("average_present_column_coverage_ratio"),
                    }
                )
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "portfolio",
        "rebalance_date",
        "row_count",
        "ticker_count",
        "category",
        "present_count",
        "row_any_feature_coverage_ratio",
        "average_present_column_coverage_ratio",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--free-data-root", default="data_raw/free")
    parser.add_argument("--coverage", default="data_pit/free/coverage_audit.json")
    parser.add_argument("--manifest", default="manifests/free_data/latest_manifest.json")
    parser.add_argument("--output-dir", default="outputs/data_readiness")
    parser.add_argument("--max-stale-days", type=int, default=3)
    parser.add_argument("--min-price-files", type=int, default=500)
    parser.add_argument("--min-scored-rows", type=int, default=500)
    parser.add_argument("--strict", action="store_true", help="Exit nonzero when blockers are present.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_payload(args)
    output_dir = repo_path(args.output_dir)
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload))
    write_feature_source_coverage_csv(output_dir / "feature_source_coverage.csv", payload)
    print(json.dumps(payload, indent=2, sort_keys=True, default=json_default))
    if args.strict and payload.get("blockers"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

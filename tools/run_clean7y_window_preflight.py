#!/usr/bin/env python3
"""Preflight the clean 7Y decision/fill window before expensive rebuild use.

This tool is intentionally diagnostic. It does not promote results, mutate
targets, or run broker replay.

The default mode validates regenerated candidate/target books.  ``--source-only``
is a fail-fast pre-run check for expensive workflows: it verifies the clean 7Y
anchor, next-close bridge, replay-cache start, and projected calendar trading
days before paying for a full rebuild.  It cannot prove generated books moved;
the default post-book mode still must run after book generation.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_pipeline import (
    _estimated_next_close_fill_date,
    decision_session_close_utc,
    month_end_trading_days,
    monthly_test_dates,
)


DATE_COLUMNS = (
    "available_from",
    "feature_available_from",
    "feature_available_from_max",
    "fund_available_from",
    "membership_available_from",
    "universe_available_from",
    "accepted",
    "fund_accepted",
    "fund_effective_accepted",
    "fund_latest_accepted_overall",
)
PIT_REQUIRED_COLUMNS = (
    "valuation_price_cutoff_date",
    "feature_available_from",
)

FEATURE_COMPLETENESS_COLUMNS = (
    "ticker",
    "px",
    "score",
    "mom_1m",
    "mom_3m",
    "mom_6m",
    "mom_12m",
    "relative_strength_composite",
    "valuation_price_cutoff_date",
    "feature_available_from",
)
FEATURE_NUMERIC_COLUMNS = {
    "px",
    "score",
    "mom_1m",
    "mom_3m",
    "mom_6m",
    "mom_12m",
    "relative_strength_composite",
}
FEATURE_DATETIME_COLUMNS = {
    "valuation_price_cutoff_date",
    "feature_available_from",
}
FEATURE_HARD_INTEGRITY_COLUMNS = {
    "ticker",
    "px",
    "valuation_price_cutoff_date",
    "feature_available_from",
}
INVALID_TICKERS = {"", "N/A", "NA", "NAN", "NONE", "NULL", "UNKNOWN"}
FEATURE_NONZERO_COLUMNS = (
    "score",
    "mom_1m",
    "mom_3m",
    "mom_6m",
    "mom_12m",
    "relative_strength_composite",
)
MIN_FEATURE_COMPLETENESS_RATIO = 0.98
MIN_BROKER_LEDGER_TRADING_DAYS = int(252 * 7)
DEFAULT_CACHE_START_FLOOR = "2019-05-09"


def repo_path(raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else Path.cwd() / path


def read_first_rebalance(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "rows": 0,
        "first_rebalance_date": None,
    }
    if not path.exists():
        return payload
    try:
        df = pd.read_csv(path, usecols=lambda c: c == "rebalance_date")
    except Exception as exc:
        payload["error"] = str(exc)
        return payload
    payload["rows"] = int(len(df))
    if not df.empty and "rebalance_date" in df.columns:
        dates = pd.to_datetime(df["rebalance_date"], errors="coerce").dropna()
        if not dates.empty:
            payload["first_rebalance_date"] = pd.Timestamp(dates.min()).date().isoformat()
    return payload


def estimate_calendar_trading_days(start_date: str | None, end_date: str | None) -> int | None:
    start = pd.to_datetime(start_date, errors="coerce")
    end = pd.to_datetime(end_date, errors="coerce")
    if pd.isna(start) or pd.isna(end) or end < start:
        return None
    return int(round((pd.Timestamp(end).normalize() - pd.Timestamp(start).normalize()).days * 252.0 / 365.25))


def read_cache_manifest(latest_run: Path, cache_start_floor: str) -> dict[str, Any]:
    candidates = [
        latest_run / "manifests" / "replay_price_cache_manifest.json",
        latest_run / "replay_price_cache_manifest.json",
        REPO_ROOT / "cache_prices" / "replay_price_cache_manifest.json",
    ]
    status: dict[str, Any] = {
        "checked": True,
        "path": None,
        "exists": False,
        "start": None,
        "required_start_or_before": cache_start_floor,
        "start_pass": False,
    }
    for path in candidates:
        if not path.exists():
            continue
        status["path"] = str(path)
        status["exists"] = True
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            status["error"] = str(exc)
            return status
        start_value = payload.get("start") or payload.get("requested_start")
        status["start"] = start_value
        start = pd.to_datetime(start_value, errors="coerce")
        floor = pd.to_datetime(cache_start_floor, errors="coerce")
        status["start_pass"] = bool(pd.notna(start) and pd.notna(floor) and start <= floor)
        status["manifest_end"] = payload.get("end")
        status["manifest_status"] = payload.get("status")
        return status
    return status


def first_decision_pit_status(candidate_book: Path, first_decision: str | None) -> dict[str, Any]:
    status: dict[str, Any] = {
        "path": str(candidate_book),
        "first_decision_date": first_decision,
        "checked": False,
        "available_from_columns": [],
        "required_columns": list(PIT_REQUIRED_COLUMNS),
        "missing_required_columns": [],
        "future_available_from_rows": None,
        "pit_status": "missing_candidate_book",
    }
    if not candidate_book.exists() or not first_decision:
        return status
    try:
        header = pd.read_csv(candidate_book, nrows=0)
        usecols = [
            c
            for c in [
                "rebalance_date",
                "ticker",
                "portfolio_candidate_minimum_pass",
                "portfolio_candidate_gate_label",
                "valuation_price_cutoff_date",
                *DATE_COLUMNS,
                *FEATURE_COMPLETENESS_COLUMNS,
            ]
            if c in header.columns
        ]
        df = pd.read_csv(candidate_book, usecols=usecols)
    except Exception as exc:
        status["pit_status"] = "read_error"
        status["error"] = str(exc)
        return status
    if "rebalance_date" not in df.columns:
        status["pit_status"] = "missing_rebalance_date"
        return status
    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"], errors="coerce")
    first_dt = pd.Timestamp(first_decision).normalize()
    first_rows = df[df["rebalance_date"].dt.normalize().eq(first_dt)].copy()
    status["checked"] = True
    status["first_decision_rows"] = int(len(first_rows))
    available_cols = [c for c in DATE_COLUMNS if c in first_rows.columns]
    status["available_from_columns"] = available_cols
    if first_rows.empty:
        status["pit_status"] = "missing_first_decision_rows"
        return status
    missing_required = [c for c in PIT_REQUIRED_COLUMNS if c not in first_rows.columns]
    status["missing_required_columns"] = missing_required
    if missing_required:
        status["pit_status"] = "fail_missing_required_pit_columns"
        status["future_available_from_rows"] = None
        return status
    if "portfolio_candidate_minimum_pass" not in first_rows.columns:
        status["pit_status"] = "fail_missing_candidate_gate_column"
        status["first_decision_post_gate_rows"] = 0
        status["feature_completeness"] = {
            "status": "missing_candidate_gate_column",
            "required_gate_column": "portfolio_candidate_minimum_pass",
        }
        return status
    if "portfolio_candidate_gate_label" not in first_rows.columns:
        status["pit_status"] = "fail_missing_candidate_gate_label"
        status["first_decision_post_gate_rows"] = 0
        status["feature_completeness"] = {
            "status": "missing_candidate_gate_label",
            "required_gate_column": "portfolio_candidate_gate_label",
        }
        return status
    gate_labels = (
        first_rows["portfolio_candidate_gate_label"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )
    blank_label_mask = gate_labels.eq("")
    status["candidate_gate_blank_label_rows"] = int(blank_label_mask.sum())
    if blank_label_mask.any():
        status["pit_status"] = "fail_blank_candidate_gate_label"
        status["first_decision_post_gate_rows"] = 0
        status["feature_completeness"] = {
            "status": "blank_candidate_gate_label",
            "blank_label_rows": int(blank_label_mask.sum()),
        }
        return status
    fallback_mask = gate_labels.str.startswith("audit_fallback")
    status["candidate_gate_fallback_rows"] = int(fallback_mask.sum())
    if fallback_mask.any():
        status["pit_status"] = "fail_candidate_gate_fallback"
        status["first_decision_post_gate_rows"] = 0
        status["feature_completeness"] = {
            "status": "candidate_gate_fallback",
            "fallback_rows": int(fallback_mask.sum()),
        }
        return status
    raw_gate = first_rows["portfolio_candidate_minimum_pass"]
    if raw_gate.dtype == bool:
        gate_mask = raw_gate.fillna(False)
        invalid_gate_value_mask = pd.Series(False, index=first_rows.index)
    else:
        normalized_gate = raw_gate.fillna("").astype(str).str.strip().str.lower()
        true_values = {"1", "true", "yes"}
        false_values = {"0", "false", "no"}
        gate_mask = normalized_gate.isin(true_values)
        invalid_gate_value_mask = ~normalized_gate.isin(true_values | false_values)
    status["candidate_gate_invalid_boolean_rows"] = int(invalid_gate_value_mask.sum())
    if invalid_gate_value_mask.any():
        status["pit_status"] = "fail_invalid_candidate_gate_boolean"
        status["first_decision_post_gate_rows"] = 0
        status["feature_completeness"] = {
            "status": "invalid_candidate_gate_boolean",
            "invalid_boolean_rows": int(invalid_gate_value_mask.sum()),
        }
        return status
    allowed_pass_labels = {
        "core_strict",
        "future_relaxed",
        "early_relaxed",
        "adr_global_alpha_fallback",
    }
    inconsistent_pass_mask = gate_mask & ~gate_labels.isin(allowed_pass_labels)
    inconsistent_reject_mask = ~gate_mask & gate_labels.ne("rejected")
    inconsistent_label_mask = inconsistent_pass_mask | inconsistent_reject_mask
    status["candidate_gate_inconsistent_label_rows"] = int(
        inconsistent_label_mask.sum()
    )
    if inconsistent_label_mask.any():
        status["pit_status"] = "fail_inconsistent_candidate_gate_label"
        status["first_decision_post_gate_rows"] = 0
        status["feature_completeness"] = {
            "status": "inconsistent_candidate_gate_label",
            "inconsistent_label_rows": int(inconsistent_label_mask.sum()),
            "allowed_pass_labels": sorted(allowed_pass_labels),
            "required_reject_label": "rejected",
        }
        return status
    post_gate_rows = first_rows.loc[gate_mask].copy()
    status["first_decision_post_gate_rows"] = int(len(post_gate_rows))
    if post_gate_rows.empty:
        status["pit_status"] = "fail_missing_post_gate_candidate_rows"
        status["feature_completeness"] = {
            "status": "missing_post_gate_candidate_rows",
            "required_gate_column": "portfolio_candidate_minimum_pass",
        }
        return status
    first_utc = first_dt.tz_localize("UTC")
    decision_close = decision_session_close_utc(
        pd.Series([first_dt], index=["first_decision"])
    ).iloc[0]
    valuation_dates = pd.to_datetime(
        first_rows["valuation_price_cutoff_date"], errors="coerce", utc=True
    )
    valuation_invalid = valuation_dates.isna() | ~valuation_dates.dt.normalize().eq(first_utc)
    feature_available = pd.to_datetime(
        first_rows["feature_available_from"], errors="coerce", utc=True
    )
    feature_missing = feature_available.isna()
    feature_close_mismatch = feature_available.notna() & (
        pd.isna(decision_close) | ~feature_available.eq(decision_close)
    )
    feature_future = feature_available.notna() & (
        pd.isna(decision_close) | feature_available.gt(decision_close)
    )
    future_mask = pd.Series(False, index=first_rows.index)
    for col in available_cols:
        values = pd.to_datetime(first_rows[col], errors="coerce", utc=True)
        future_mask = future_mask | (
            values.notna()
            & (pd.isna(decision_close) | values.gt(decision_close))
        )
    invalid_mask = (
        future_mask
        | valuation_invalid
        | feature_missing
        | feature_close_mismatch
    )
    future_rows = first_rows[invalid_mask]
    status["future_available_from_rows"] = int(len(future_rows))
    status["valuation_cutoff_invalid_rows"] = int(valuation_invalid.sum())
    status["feature_available_from_missing_rows"] = int(feature_missing.sum())
    status["feature_available_from_close_mismatch_rows"] = int(
        feature_close_mismatch.sum()
    )
    status["feature_available_from_after_close_rows"] = int(feature_future.sum())
    status["decision_market_close_utc"] = (
        "" if pd.isna(decision_close) else pd.Timestamp(decision_close).isoformat()
    )
    status["pit_status"] = "pass" if future_rows.empty else "fail_pit_provenance"
    if not future_rows.empty and "ticker" in future_rows.columns:
        status["future_available_from_sample"] = future_rows["ticker"].astype(str).head(20).tolist()
    completeness = feature_completeness_status(post_gate_rows)
    status["feature_completeness"] = completeness
    if status["pit_status"] == "pass" and completeness["status"] != "pass":
        status["pit_status"] = "fail_feature_completeness"
    return status


def feature_completeness_status(first_rows: pd.DataFrame) -> dict[str, Any]:
    status: dict[str, Any] = {
        "status": "pass",
        "required_columns": list(FEATURE_COMPLETENESS_COLUMNS),
        "missing_columns": [],
        "column_stats": {},
        "minimum_complete_row_ratio": MIN_FEATURE_COMPLETENESS_RATIO,
        "coverage_denominator_count": int(len(first_rows)),
        "complete_row_count": 0,
        "coverage_ratio": 0.0,
        "hard_integrity_invalid_by_column": {},
    }
    if first_rows.empty:
        status["status"] = "missing_first_decision_rows"
        return status
    blockers: list[str] = []
    valid_masks: dict[str, pd.Series] = {}
    for col in FEATURE_COMPLETENESS_COLUMNS:
        if col not in first_rows.columns:
            status["missing_columns"].append(col)
            blockers.append(f"missing:{col}")
            valid_masks[col] = pd.Series(False, index=first_rows.index)
            continue
        raw = first_rows[col]
        if col == "ticker":
            normalized = raw.fillna("").astype(str).str.upper().str.strip()
            valid = ~normalized.isin(INVALID_TICKERS)
            non_zero = valid
        elif col in FEATURE_NUMERIC_COLUMNS:
            values = pd.to_numeric(raw, errors="coerce")
            finite = values.map(lambda value: bool(pd.notna(value) and math.isfinite(float(value))))
            valid = finite & ~values.isin([-999.0, -9999.0])
            if col == "px":
                valid = valid & values.gt(0.0)
            non_zero = valid & values.ne(0.0)
        elif col in FEATURE_DATETIME_COLUMNS:
            values = pd.to_datetime(raw, errors="coerce", utc=True)
            valid = values.notna()
            non_zero = valid
        else:
            valid = raw.notna()
            non_zero = valid
        valid_masks[col] = valid
        complete_ratio = float(valid.mean()) if len(valid) else 0.0
        stat = {
            "valid_count": int(valid.sum()),
            "invalid_count": int((~valid).sum()),
            "complete_ratio": complete_ratio,
            "non_zero_ratio": float(non_zero.mean()) if len(valid) else 0.0,
        }
        status["column_stats"][col] = stat
        if col in FEATURE_NONZERO_COLUMNS and float(non_zero.sum()) <= 0.0:
            blockers.append(f"all_zero_or_placeholder:{col}")

    complete_mask = pd.Series(True, index=first_rows.index)
    for col in FEATURE_COMPLETENESS_COLUMNS:
        complete_mask &= valid_masks[col]
    complete_count = int(complete_mask.sum())
    coverage_ratio = float(complete_count / len(first_rows))
    status["complete_row_count"] = complete_count
    status["coverage_ratio"] = coverage_ratio
    if coverage_ratio < MIN_FEATURE_COMPLETENESS_RATIO:
        blockers.append(
            f"complete_row_coverage:{coverage_ratio:.6f}<{MIN_FEATURE_COMPLETENESS_RATIO:.6f}"
        )

    hard_invalid = {
        col: int((~valid_masks[col]).sum())
        for col in FEATURE_HARD_INTEGRITY_COLUMNS
        if col in valid_masks and int((~valid_masks[col]).sum()) > 0
    }
    status["hard_integrity_invalid_by_column"] = hard_invalid
    for col, count in hard_invalid.items():
        blockers.append(f"hard_integrity_invalid:{col}:{count}")

    if "ticker" in first_rows.columns:
        normalized = first_rows["ticker"].fillna("").astype(str).str.upper().str.strip()
        duplicate_count = int(normalized.duplicated().sum())
        status["duplicate_ticker_count"] = duplicate_count
        if duplicate_count:
            blockers.append(f"duplicate_tickers:{duplicate_count}")
    if blockers:
        status["status"] = "fail"
        status["blockers"] = sorted(set(blockers))
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/clean7y_window_preflight")
    parser.add_argument("--feature-start-date", default="2016-01-01")
    parser.add_argument("--evaluation-start-date", default="2019-06-03")
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--expected-first-decision", default="2019-05-31")
    parser.add_argument("--cache-start-floor", default=DEFAULT_CACHE_START_FLOOR)
    parser.add_argument("--min-calendar-trading-days", type=int, default=MIN_BROKER_LEDGER_TRADING_DAYS)
    parser.add_argument("--not-before", default=None, help="Earliest allowed actual first decision; defaults to expected first decision.")
    parser.add_argument("--must-be-before", default="2019-06-28")
    parser.add_argument(
        "--target-book-scope",
        choices=("operating", "all"),
        default="operating",
        help=(
            "Validate run_local operating books before sidecars, or include "
            "AlphaOps official books after their producer has run."
        ),
    )
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="Check only cache/date/calendar pre-run invariants. Skip candidate/target/PIT checks.",
    )
    parser.add_argument("--strict", action="store_true")
    parser.add_argument(
        "--allow-missing-cache-in-source-only",
        action="store_true",
        help=(
            "Allow source-only mode to defer the replay cache start check when "
            "the workflow is about to build/cache data on a fresh runner. "
            "Post-book mode still enforces the cache manifest."
        ),
    )
    args = parser.parse_args()

    latest = repo_path(args.latest_run)
    out_dir = repo_path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    generated_dates = month_end_trading_days(args.feature_start_date, args.end_date)
    generated_iso = [pd.Timestamp(x).date().isoformat() for x in generated_dates]
    probe_frame = pd.DataFrame({"rebalance_date": generated_iso})
    filtered = monthly_test_dates(probe_frame, args.evaluation_start_date)
    filtered_iso = [pd.Timestamp(x).date().isoformat() for x in filtered]
    expected_fill = _estimated_next_close_fill_date(args.expected_first_decision)
    expected_fill_iso = pd.Timestamp(expected_fill).date().isoformat() if expected_fill is not None else None
    projected_calendar_trading_days = estimate_calendar_trading_days(expected_fill_iso, args.end_date)
    projected_calendar_pass = bool(
        projected_calendar_trading_days is not None
        and projected_calendar_trading_days >= int(args.min_calendar_trading_days)
    )
    cache_manifest = read_cache_manifest(latest, args.cache_start_floor)

    must_before = pd.Timestamp(args.must_be_before).normalize()
    expected_first = str(args.expected_first_decision)
    not_before_raw = str(args.not_before or expected_first)
    not_before = pd.Timestamp(not_before_raw).normalize()
    generated_pass = expected_first in generated_iso
    filtered_pass = bool(filtered_iso and filtered_iso[0] == expected_first)
    files = {
        "candidate_replay_book": latest / "reports" / "candidate_replay_book.csv",
        "operating_main_target_book": latest / "reports" / "operating_main_target_book.csv",
        "operating_concentrated_target_book": latest / "reports" / "operating_concentrated_target_book.csv",
        "official_main_target_book": latest / "alphaops_vnext" / "official_main_target_book.csv",
        "official_concentrated_target_book": latest / "alphaops_vnext" / "official_concentrated_target_book.csv",
    }
    file_status: dict[str, dict[str, Any]] = {}
    target_checks: dict[str, bool] = {}
    first_candidate = None
    actual_candidate_pass = None
    target_pass = None
    pit_status: dict[str, Any] = {"checked": False, "pit_status": "skipped_source_only" if args.source_only else "not_checked"}
    if not args.source_only:
        file_status = {name: read_first_rebalance(path) for name, path in files.items()}
        first_candidate = file_status["candidate_replay_book"].get("first_rebalance_date")
        pit_status = first_decision_pit_status(files["candidate_replay_book"], first_candidate)
        actual_candidate_pass = bool(first_candidate and not_before <= pd.Timestamp(first_candidate) < must_before)
        target_pass = True
        target_names = [
            "operating_main_target_book",
            "operating_concentrated_target_book",
        ]
        if args.target_book_scope == "all":
            target_names.extend(
                ["official_main_target_book", "official_concentrated_target_book"]
            )
        for name in target_names:
            first = file_status[name].get("first_rebalance_date")
            ok = bool(first and not_before <= pd.Timestamp(first) < must_before)
            target_checks[name] = ok
            target_pass = target_pass and ok

    blockers: list[str] = []
    if not generated_pass:
        blockers.append("generated_month_end_missing_expected_first_decision")
    if not filtered_pass:
        blockers.append("monthly_test_dates_missing_next_close_bridge_decision")
    if not args.source_only:
        if not actual_candidate_pass:
            blockers.append("candidate_replay_book_not_in_expected_clean7y_decision_window")
        if not target_pass:
            blockers.append("target_books_not_in_expected_clean7y_decision_window")
        if pit_status.get("pit_status") != "pass":
            blockers.append("first_decision_pit_check_failed")
    cache_check_deferred = bool(
        args.source_only
        and args.allow_missing_cache_in_source_only
        and not cache_manifest.get("exists")
    )
    if cache_check_deferred:
        cache_manifest["deferred"] = True
        cache_manifest["deferred_reason"] = "source_only_missing_cache_collector_will_build"
    if not cache_manifest.get("start_pass") and not cache_check_deferred:
        blockers.append("replay_price_cache_start_after_clean7y_floor")
    if not projected_calendar_pass:
        blockers.append("projected_calendar_trading_days_below_7y")

    payload = {
        "schema_version": "clean7y-window-preflight-v3",
        "production_promotion_allowed": False,
        "purpose": "research_7y_window_preflight",
        "mode": "source_only" if args.source_only else "post_book",
        "target_book_scope": args.target_book_scope,
        "post_book_validation_required": bool(args.source_only),
        "feature_start_date": args.feature_start_date,
        "evaluation_start_date": args.evaluation_start_date,
        "end_date": args.end_date,
        "expected_first_decision": expected_first,
        "expected_first_decision_next_close_fill": expected_fill_iso,
        "cache_manifest": cache_manifest,
        "cache_check_deferred": cache_check_deferred,
        "projected_calendar_trading_days": {
            "start_date": expected_fill_iso,
            "end_date": args.end_date,
            "count": projected_calendar_trading_days,
            "min_required": int(args.min_calendar_trading_days),
            "pass": projected_calendar_pass,
            "portfolios": {
                "main": projected_calendar_trading_days,
                "concentrated": projected_calendar_trading_days,
            },
        },
        "not_before": not_before_raw,
        "must_be_before": args.must_be_before,
        "generated_month_end_contains_expected": generated_pass,
        "monthly_test_dates_first": filtered_iso[0] if filtered_iso else None,
        "monthly_test_dates_contains_expected_first": filtered_pass,
        "actual_candidate_first_pass": actual_candidate_pass,
        "target_books_first_pass": target_pass,
        "target_book_checks": target_checks,
        "files": file_status,
        "first_decision_pit": pit_status,
        "blockers": blockers,
        "status": "pass" if not blockers else "blocked",
    }

    (out_dir / "status.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Clean 7Y Window Preflight",
        "",
        f"- status: `{payload['status']}`",
        f"- mode: `{payload['mode']}`",
        f"- feature_start_date: `{args.feature_start_date}`",
        f"- evaluation_start_date: `{args.evaluation_start_date}`",
        f"- expected first decision: `{expected_first}`",
        f"- expected next-close fill: `{payload['expected_first_decision_next_close_fill']}`",
        f"- cache manifest start: `{cache_manifest.get('start')}` (required <= `{args.cache_start_floor}`)",
        f"- cache check deferred: `{payload['cache_check_deferred']}`",
        f"- projected calendar trading days: `{projected_calendar_trading_days}` / `{args.min_calendar_trading_days}`",
        f"- accepted first-decision range: `[{not_before_raw}, {args.must_be_before})`",
        f"- monthly_test_dates first: `{payload['monthly_test_dates_first']}`",
        f"- candidate first: `{first_candidate}`",
        f"- post_book_validation_required: `{payload['post_book_validation_required']}`",
        f"- target_book_scope: `{payload['target_book_scope']}`",
        f"- production_promotion_allowed: `{payload['production_promotion_allowed']}`",
        "",
        "## Blockers",
    ]
    lines.extend([f"- {b}" for b in blockers] or ["- none"])
    lines.extend(["", "## Target Book Checks"])
    lines.extend([f"- {k}: `{v}`" for k, v in target_checks.items()])
    lines.extend(["", "## PIT"])
    lines.append(f"- pit_status: `{pit_status.get('pit_status')}`")
    lines.append(f"- future_available_from_rows: `{pit_status.get('future_available_from_rows')}`")
    lines.append(f"- feature_completeness_status: `{(pit_status.get('feature_completeness') or {}).get('status')}`")
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return 1 if args.strict and blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())

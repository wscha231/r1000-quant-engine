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
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_pipeline import _estimated_next_close_fill_date, month_end_trading_days, monthly_test_dates


DATE_COLUMNS = (
    "available_from",
    "feature_available_from",
    "feature_available_from_max",
    "fund_available_from",
    "membership_available_from",
    "universe_available_from",
    "accepted",
    "fund_effective_accepted",
)

FEATURE_COMPLETENESS_COLUMNS = (
    "mom_1m",
    "mom_3m",
    "mom_6m",
    "relative_strength_composite",
    "price_above_ma200",
    "rsi14",
)
FEATURE_NONZERO_COLUMNS = (
    "mom_1m",
    "mom_3m",
    "mom_6m",
    "relative_strength_composite",
    "rsi14",
)
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
        "future_available_from_rows": None,
        "pit_status": "missing_candidate_book",
    }
    if not candidate_book.exists() or not first_decision:
        return status
    try:
        header = pd.read_csv(candidate_book, nrows=0)
        usecols = [c for c in ["rebalance_date", "ticker", *DATE_COLUMNS, *FEATURE_COMPLETENESS_COLUMNS] if c in header.columns]
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
    if not available_cols:
        status["pit_status"] = "review_required_no_available_from_columns"
        status["future_available_from_rows"] = None
        return status
    future_mask = pd.Series(False, index=first_rows.index)
    for col in available_cols:
        values = pd.to_datetime(first_rows[col], errors="coerce")
        future_mask = future_mask | (values > first_dt)
    future_rows = first_rows[future_mask]
    status["future_available_from_rows"] = int(len(future_rows))
    status["pit_status"] = "pass" if future_rows.empty else "fail_future_available_from"
    if not future_rows.empty and "ticker" in future_rows.columns:
        status["future_available_from_sample"] = future_rows["ticker"].astype(str).head(20).tolist()
    completeness = feature_completeness_status(first_rows)
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
        "min_non_placeholder_ratio": 0.80,
    }
    if first_rows.empty:
        status["status"] = "missing_first_decision_rows"
        return status
    blockers: list[str] = []
    for col in FEATURE_COMPLETENESS_COLUMNS:
        if col not in first_rows.columns:
            status["missing_columns"].append(col)
            blockers.append(f"missing:{col}")
            continue
        values = pd.to_numeric(first_rows[col], errors="coerce")
        non_null = values.notna()
        non_placeholder = non_null & ~values.isin([-999.0, -9999.0])
        non_zero = non_placeholder & values.ne(0.0)
        non_placeholder_ratio = float(non_placeholder.mean()) if len(values) else 0.0
        stat = {
            "non_null_ratio": float(non_null.mean()) if len(values) else 0.0,
            "non_placeholder_ratio": non_placeholder_ratio,
            "non_zero_ratio": float(non_zero.mean()) if len(values) else 0.0,
        }
        status["column_stats"][col] = stat
        if non_placeholder_ratio < status["min_non_placeholder_ratio"]:
            blockers.append(f"low_non_placeholder:{col}")
        if col in FEATURE_NONZERO_COLUMNS and float(non_zero.sum()) <= 0.0:
            blockers.append(f"all_zero_or_placeholder:{col}")
    if blockers:
        status["status"] = "fail"
        status["blockers"] = blockers
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/clean7y_window_preflight")
    parser.add_argument("--feature-start-date", default="2016-01-01")
    parser.add_argument("--evaluation-start-date", default="2019-06-03")
    parser.add_argument("--end-date", default="2026-06-23")
    parser.add_argument("--expected-first-decision", default="2019-05-31")
    parser.add_argument("--cache-start-floor", default=DEFAULT_CACHE_START_FLOOR)
    parser.add_argument("--min-calendar-trading-days", type=int, default=MIN_BROKER_LEDGER_TRADING_DAYS)
    parser.add_argument("--not-before", default=None, help="Earliest allowed actual first decision; defaults to expected first decision.")
    parser.add_argument("--must-be-before", default="2019-06-28")
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
        for name in (
            "operating_main_target_book",
            "operating_concentrated_target_book",
            "official_main_target_book",
            "official_concentrated_target_book",
        ):
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
        "schema_version": "clean7y-window-preflight-v2",
        "production_promotion_allowed": False,
        "purpose": "research_7y_window_preflight",
        "mode": "source_only" if args.source_only else "post_book",
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

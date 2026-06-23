#!/usr/bin/env python3
"""Preflight the clean 7Y decision/fill window before expensive rebuild use.

This tool is intentionally diagnostic. It does not promote results, mutate
targets, or run broker replay. It checks whether regenerated candidate/target
books actually moved the first decision before 2019-06-28, and whether the
first included decision is PIT-clean when available_from columns are present.
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
        usecols = [c for c in ["rebalance_date", "ticker", *DATE_COLUMNS] if c in header.columns]
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
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/clean7y_window_preflight")
    parser.add_argument("--feature-start-date", default="2016-01-01")
    parser.add_argument("--evaluation-start-date", default="2019-06-03")
    parser.add_argument("--end-date", default="2026-06-23")
    parser.add_argument("--expected-first-decision", default="2019-05-31")
    parser.add_argument("--must-be-before", default="2019-06-28")
    parser.add_argument("--strict", action="store_true")
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

    files = {
        "candidate_replay_book": latest / "reports" / "candidate_replay_book.csv",
        "operating_main_target_book": latest / "reports" / "operating_main_target_book.csv",
        "operating_concentrated_target_book": latest / "reports" / "operating_concentrated_target_book.csv",
        "official_main_target_book": latest / "alphaops_vnext" / "official_main_target_book.csv",
        "official_concentrated_target_book": latest / "alphaops_vnext" / "official_concentrated_target_book.csv",
    }
    file_status = {name: read_first_rebalance(path) for name, path in files.items()}
    first_candidate = file_status["candidate_replay_book"].get("first_rebalance_date")
    pit_status = first_decision_pit_status(files["candidate_replay_book"], first_candidate)

    must_before = pd.Timestamp(args.must_be_before).normalize()
    expected_first = str(args.expected_first_decision)
    generated_pass = expected_first in generated_iso
    filtered_pass = bool(filtered_iso and filtered_iso[0] == expected_first)
    actual_candidate_pass = bool(first_candidate and pd.Timestamp(first_candidate) < must_before)
    target_pass = True
    target_checks: dict[str, bool] = {}
    for name in (
        "operating_main_target_book",
        "operating_concentrated_target_book",
        "official_main_target_book",
        "official_concentrated_target_book",
    ):
        first = file_status[name].get("first_rebalance_date")
        ok = bool(first and pd.Timestamp(first) < must_before)
        target_checks[name] = ok
        target_pass = target_pass and ok

    blockers: list[str] = []
    if not generated_pass:
        blockers.append("generated_month_end_missing_expected_first_decision")
    if not filtered_pass:
        blockers.append("monthly_test_dates_missing_next_close_bridge_decision")
    if not actual_candidate_pass:
        blockers.append("candidate_replay_book_not_rebuilt_to_expected_window")
    if not target_pass:
        blockers.append("target_books_not_rebuilt_to_expected_window")
    if pit_status.get("pit_status") not in {"pass", "review_required_no_available_from_columns"}:
        blockers.append("first_decision_pit_check_failed")

    payload = {
        "schema_version": "clean7y-window-preflight-v1",
        "production_promotion_allowed": False,
        "purpose": "research_7y_window_preflight",
        "feature_start_date": args.feature_start_date,
        "evaluation_start_date": args.evaluation_start_date,
        "end_date": args.end_date,
        "expected_first_decision": expected_first,
        "expected_first_decision_next_close_fill": (
            pd.Timestamp(expected_fill).date().isoformat() if expected_fill is not None else None
        ),
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
        f"- feature_start_date: `{args.feature_start_date}`",
        f"- evaluation_start_date: `{args.evaluation_start_date}`",
        f"- expected first decision: `{expected_first}`",
        f"- expected next-close fill: `{payload['expected_first_decision_next_close_fill']}`",
        f"- monthly_test_dates first: `{payload['monthly_test_dates_first']}`",
        f"- candidate first: `{first_candidate}`",
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
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return 1 if args.strict and blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())

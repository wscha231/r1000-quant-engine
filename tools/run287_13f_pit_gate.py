#!/usr/bin/env python3
"""PIT audit gate for the run287 pure-13F Concentrated source candidate.

This is a pre-A/B evidence tool. It proves that the 13F source is gated by
filing availability (`available_from`), not report period end. It does not run a
broker replay, add a hook, dispatch a fullrun, or mutate production state.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_run287_w4_form4_13f_source_screen import DEFAULT_13F_PATH  # noqa: E402

SCHEMA_VERSION = "run287-13f-pit-gate-v1"
DEFAULT_MISS_SET = "outputs/run287_conc_alpha_source_packet/miss_set_candidates.csv"
DEFAULT_OUTPUT_DIR = "outputs/run287_13f_pit_gate"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def miss_set_decision_audit(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "miss_set_path": str(path),
            "miss_set_status": "missing",
            "rows_with_available_from_after_decision_date": None,
        }
    frame = pd.read_csv(path, low_memory=False)
    if frame.empty or "rebalance_date" not in frame.columns:
        return {
            "miss_set_path": str(path),
            "miss_set_status": "empty_or_missing_rebalance_date",
            "rows_with_available_from_after_decision_date": None,
        }
    d = frame.copy()
    d["decision_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    if "latest_13f_available_from" not in d.columns:
        d["latest_13f_available_from"] = pd.NaT
    d["latest_13f_available_ts"] = pd.to_datetime(d["latest_13f_available_from"], errors="coerce", utc=True)
    d["latest_13f_available_date"] = d["latest_13f_available_ts"].dt.tz_convert(None).dt.normalize()
    valid = d["decision_date"].notna() & d["latest_13f_available_date"].notna()
    after = valid & d["latest_13f_available_date"].gt(d["decision_date"])
    same_day = valid & d["latest_13f_available_date"].eq(d["decision_date"])
    return {
        "miss_set_path": str(path),
        "miss_set_status": "completed",
        "miss_set_rows": int(len(d)),
        "miss_set_rows_with_13f_available_from": int(valid.sum()),
        "rows_with_available_from_after_decision_date": int(after.sum()),
        "rows_with_same_day_available_from_as_decision_date": int(same_day.sum()),
        "latest_13f_available_from_min": d.loc[valid, "latest_13f_available_date"].min().date().isoformat()
        if valid.any()
        else None,
        "latest_13f_available_from_max": d.loc[valid, "latest_13f_available_date"].max().date().isoformat()
        if valid.any()
        else None,
    }


def audit_13f_pit(holdings_path: Path, miss_set_path: Path) -> dict[str, Any]:
    holdings = read_table(holdings_path)
    if holdings.empty:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked",
            "pit_gate_status": "blocked",
            "reason": "missing_or_empty_13f_holdings",
            "sec13f_path": str(holdings_path),
            "research_only": True,
            "fullrun_dispatched": False,
            "production_promotion_allowed": False,
        }

    required = {"report_period", "available_from"}
    missing = sorted(required - set(holdings.columns))
    if missing:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked",
            "pit_gate_status": "blocked",
            "reason": "missing_required_13f_time_columns",
            "missing_columns": missing,
            "sec13f_path": str(holdings_path),
            "research_only": True,
            "fullrun_dispatched": False,
            "production_promotion_allowed": False,
        }

    d = holdings.copy()
    d["report_period_ts"] = pd.to_datetime(d["report_period"], errors="coerce").dt.normalize()
    d["available_ts"] = pd.to_datetime(d["available_from"], errors="coerce", utc=True)
    d["available_date"] = d["available_ts"].dt.tz_convert(None).dt.normalize()
    valid = d["report_period_ts"].notna() & d["available_date"].notna()
    lag_days = (d.loc[valid, "available_date"] - d.loc[valid, "report_period_ts"]).dt.days
    negative_lag_count = int(lag_days.lt(0).sum()) if not lag_days.empty else 0
    zero_to_ten_lag_rate = float(lag_days.le(10).mean()) if not lag_days.empty else 1.0
    median_lag = float(lag_days.median()) if not lag_days.empty else 0.0
    p10_lag = float(lag_days.quantile(0.10)) if not lag_days.empty else 0.0
    p90_lag = float(lag_days.quantile(0.90)) if not lag_days.empty else 0.0
    miss = miss_set_decision_audit(miss_set_path)

    # The source screen builder explicitly materializes `available_date` from
    # `available_from`. Treat a period-end-like lag distribution as leaky even
    # if the field name exists, because that would make the source unusable.
    uses_period_end = bool(median_lag < 30.0 or zero_to_ten_lag_rate > 0.25)
    rows_after_decision = miss.get("rows_with_available_from_after_decision_date")
    after_count = int(rows_after_decision) if rows_after_decision is not None else 0
    if uses_period_end:
        pit_status = "leaky_period_end"
    elif negative_lag_count > 0 or after_count > 0:
        pit_status = "blocked"
    else:
        pit_status = "clean"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed" if pit_status == "clean" else "blocked",
        "pit_gate_status": pit_status,
        "sec13f_path": str(holdings_path),
        "available_from_field": "available_from",
        "report_period_field": "report_period",
        "accepted_time_field": "accepted_at" if "accepted_at" in holdings.columns else "",
        "source_screen_event_date_source": "available_from",
        "uses_period_end": uses_period_end,
        "strict_same_day_disclosure_policy": "exclude_same_day_by_searchsorted_side_left",
        "raw_rows": int(len(holdings)),
        "valid_time_rows": int(valid.sum()),
        "median_lag_days_period_end_to_available_from": median_lag,
        "p10_lag_days_period_end_to_available_from": p10_lag,
        "p90_lag_days_period_end_to_available_from": p90_lag,
        "negative_lag_count": negative_lag_count,
        "zero_to_ten_day_lag_rate": zero_to_ten_lag_rate,
        **miss,
        "research_only": True,
        "fullrun_dispatched": False,
        "production_promotion_allowed": False,
        "live_trading_enabled": False,
    }
    return payload


def render_report(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Run287 13F PIT Gate",
            "",
            f"- status: `{payload.get('status')}`",
            f"- pit_gate_status: `{payload.get('pit_gate_status')}`",
            f"- available_from_field: `{payload.get('available_from_field')}`",
            f"- uses_period_end: `{payload.get('uses_period_end')}`",
            f"- median lag days: `{safe_float(payload.get('median_lag_days_period_end_to_available_from')):.1f}`",
            f"- rows with available_from after decision date: `{payload.get('rows_with_available_from_after_decision_date')}`",
            "",
            "This is a pre-A/B PIT audit. It does not dispatch a fullrun, add a hook, or change production state.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sec13f-path", default=DEFAULT_13F_PATH)
    parser.add_argument("--miss-set", default=DEFAULT_MISS_SET)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = audit_13f_pit(repo_path(args.sec13f_path), repo_path(args.miss_set))
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("pit_gate_status") == "clean" else 2


if __name__ == "__main__":
    raise SystemExit(main())

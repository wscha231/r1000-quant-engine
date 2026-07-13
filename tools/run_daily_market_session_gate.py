#!/usr/bin/env python3
"""Resolve the latest completed NYSE session for the daily review workflow.

Scheduled runs are allowed only after a completed NYSE close has had a short
data-settlement buffer and while that close is still recent.  The exchange
calendar supplies weekends, holidays, and early closes.  Manual ``--force``
may replay an older completed session, but it can never select a future close.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pandas_market_calendars as mcal


def utc_timestamp(value: str | datetime | pd.Timestamp | None = None) -> pd.Timestamp:
    if value in (None, ""):
        stamp = pd.Timestamp.now(tz="UTC")
    else:
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        else:
            stamp = stamp.tz_convert("UTC")
    return stamp


def evaluate_market_session(
    *,
    now_utc: str | datetime | pd.Timestamp | None = None,
    force: bool = False,
    min_close_age_minutes: int = 90,
    max_close_age_hours: float = 18.0,
) -> dict[str, Any]:
    now = utc_timestamp(now_utc)
    calendar = mcal.get_calendar("NYSE")
    schedule = calendar.schedule(
        start_date=(now - pd.Timedelta(days=12)).date(),
        end_date=(now + pd.Timedelta(days=1)).date(),
    )
    completed = schedule[schedule["market_close"] <= now]
    if completed.empty:
        return {
            "schema_version": "daily-market-session-gate-v1",
            "status": "SKIP_NO_COMPLETED_SESSION",
            "ready": False,
            "forced": bool(force),
            "checked_at_utc": now.isoformat(),
            "session_date": "",
            "market_close_utc": "",
            "close_age_minutes": None,
            "min_close_age_minutes": int(min_close_age_minutes),
            "max_close_age_hours": float(max_close_age_hours),
            "calendar": "NYSE",
        }

    session_label = completed.index[-1]
    close = pd.Timestamp(completed.iloc[-1]["market_close"])
    close = close.tz_localize("UTC") if close.tzinfo is None else close.tz_convert("UTC")
    age = now - close
    age_minutes = float(age.total_seconds() / 60.0)
    old = age > pd.Timedelta(hours=float(max_close_age_hours))
    too_soon = age < pd.Timedelta(minutes=int(min_close_age_minutes))
    if force:
        ready = age >= pd.Timedelta(0)
        status = "READY_FORCED" if ready else "SKIP_FUTURE_SESSION"
    elif too_soon:
        ready = False
        status = "SKIP_CLOSE_SETTLEMENT_BUFFER"
    elif old:
        ready = False
        status = "SKIP_STALE_SESSION"
    else:
        ready = True
        status = "READY_COMPLETED_SESSION"

    return {
        "schema_version": "daily-market-session-gate-v1",
        "status": status,
        "ready": bool(ready),
        "forced": bool(force),
        "checked_at_utc": now.isoformat(),
        "session_date": pd.Timestamp(session_label).date().isoformat(),
        "market_close_utc": close.isoformat(),
        "close_age_minutes": round(age_minutes, 3),
        "min_close_age_minutes": int(min_close_age_minutes),
        "max_close_age_hours": float(max_close_age_hours),
        "calendar": "NYSE",
        "weekend_and_holiday_aware": True,
        "early_close_aware": True,
    }


def write_github_file(path_value: str, rows: dict[str, str]) -> None:
    if not path_value:
        return
    with Path(path_value).open("a", encoding="utf-8") as handle:
        for key, value in rows.items():
            handle.write(f"{key}={value}\n")


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload = evaluate_market_session(
        now_utc=args.now_utc,
        force=bool(args.force),
        min_close_age_minutes=int(args.min_close_age_minutes),
        max_close_age_hours=float(args.max_close_age_hours),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    ready = "yes" if payload["ready"] else "no"
    env_rows = {
        "MARKET_READY": ready,
        "MARKET_GATE_STATUS": str(payload["status"]),
        "LAST_NYSE_SESSION_DATE": str(payload["session_date"]),
        "LAST_NYSE_CLOSE_UTC": str(payload["market_close_utc"]),
        "MARKET_SESSION_GATE_FILE": str(output),
    }
    output_rows = {
        "ready": ready,
        "status": str(payload["status"]),
        "session_date": str(payload["session_date"]),
        "last_close": str(payload["market_close_utc"]),
    }
    write_github_file(os.environ.get("GITHUB_ENV", ""), env_rows)
    write_github_file(os.environ.get("GITHUB_OUTPUT", ""), output_rows)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--now-utc", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--min-close-age-minutes", type=int, default=90)
    parser.add_argument("--max-close-age-hours", type=float, default=18.0)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

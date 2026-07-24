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
    session_date: str | None = None,
    min_close_age_minutes: int = 90,
    max_close_age_hours: float = 18.0,
) -> dict[str, Any]:
    now = utc_timestamp(now_utc)
    selected_raw = str(session_date or "").strip()
    selected_date = None
    if selected_raw:
        try:
            selected_date = pd.Timestamp(selected_raw)
        except Exception as exc:
            raise ValueError(
                "--session-date must use canonical YYYY-MM-DD"
            ) from exc
        if (
            selected_date.tzinfo is not None
            or selected_date.strftime("%Y-%m-%d") != selected_raw
        ):
            raise ValueError("--session-date must use canonical YYYY-MM-DD")
        selected_date = selected_date.normalize()
    if selected_date is not None and not force:
        raise ValueError("--session-date requires --force")
    calendar = mcal.get_calendar("NYSE")
    schedule_start = now - pd.Timedelta(days=12)
    if selected_date is not None:
        schedule_start = min(
            schedule_start.tz_localize(None),
            selected_date - pd.Timedelta(days=2),
        ).tz_localize("UTC")
    schedule = calendar.schedule(
        start_date=schedule_start.date(),
        end_date=(now + pd.Timedelta(days=1)).date(),
    )
    completed = schedule[schedule["market_close"] <= now]
    if completed.empty:
        return {
            "schema_version": "daily-market-session-gate-v1",
            "status": "SKIP_NO_COMPLETED_SESSION",
            "ready": False,
            "forced": bool(force),
            "selected_session_explicit": bool(selected_date is not None),
            "catchup_mode": False,
            "checked_at_utc": now.isoformat(),
            "session_date": "",
            "latest_completed_session_date": "",
            "market_close_utc": "",
            "close_age_minutes": None,
            "min_close_age_minutes": int(min_close_age_minutes),
            "max_close_age_hours": float(max_close_age_hours),
            "calendar": "NYSE",
        }

    latest_session_label = completed.index[-1]
    if selected_date is not None:
        matching = schedule.loc[
            pd.DatetimeIndex(schedule.index).normalize()
            == selected_date
        ]
        if matching.empty:
            raise ValueError("--session-date must be an NYSE session")
        selected_close = pd.Timestamp(matching.iloc[0]["market_close"])
        selected_close = (
            selected_close.tz_localize("UTC")
            if selected_close.tzinfo is None
            else selected_close.tz_convert("UTC")
        )
        if selected_close > now:
            raise ValueError("--session-date must be a completed NYSE session")
        session_label = matching.index[0]
        close = selected_close
    else:
        session_label = latest_session_label
        close = pd.Timestamp(completed.iloc[-1]["market_close"])
    close = close.tz_localize("UTC") if close.tzinfo is None else close.tz_convert("UTC")
    age = now - close
    age_minutes = float(age.total_seconds() / 60.0)
    old = age > pd.Timedelta(hours=float(max_close_age_hours))
    too_soon = age < pd.Timedelta(minutes=int(min_close_age_minutes))
    if force:
        ready = age >= pd.Timedelta(0)
        catchup_mode = bool(
            pd.Timestamp(session_label).normalize()
            < pd.Timestamp(latest_session_label).normalize()
        )
        status = (
            "READY_FORCED_CATCHUP_SESSION"
            if ready and catchup_mode
            else "READY_FORCED"
            if ready
            else "SKIP_FUTURE_SESSION"
        )
    elif too_soon:
        ready = False
        status = "SKIP_CLOSE_SETTLEMENT_BUFFER"
        catchup_mode = False
    elif old:
        ready = False
        status = "SKIP_STALE_SESSION"
        catchup_mode = False
    else:
        ready = True
        status = "READY_COMPLETED_SESSION"
        catchup_mode = False

    return {
        "schema_version": "daily-market-session-gate-v1",
        "status": status,
        "ready": bool(ready),
        "forced": bool(force),
        "selected_session_explicit": bool(selected_date is not None),
        "catchup_mode": catchup_mode,
        "checked_at_utc": now.isoformat(),
        "session_date": pd.Timestamp(session_label).date().isoformat(),
        "latest_completed_session_date": (
            pd.Timestamp(latest_session_label).date().isoformat()
        ),
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
        session_date=args.session_date,
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
        "LATEST_COMPLETED_NYSE_SESSION_DATE": str(
            payload.get("latest_completed_session_date") or ""
        ),
        "LAST_NYSE_CLOSE_UTC": str(payload["market_close_utc"]),
        "PAPER_CATCHUP_MODE": (
            "yes" if payload.get("catchup_mode") is True else "no"
        ),
        "MARKET_SESSION_GATE_FILE": str(output),
    }
    output_rows = {
        "ready": ready,
        "status": str(payload["status"]),
        "session_date": str(payload["session_date"]),
        "latest_completed_session_date": str(
            payload.get("latest_completed_session_date") or ""
        ),
        "catchup_mode": (
            "yes" if payload.get("catchup_mode") is True else "no"
        ),
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
    parser.add_argument("--session-date", default="")
    parser.add_argument("--min-close-age-minutes", type=int, default=90)
    parser.add_argument("--max-close-age-hours", type=float, default=18.0)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

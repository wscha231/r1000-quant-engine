#!/usr/bin/env python3
"""Audit whether the SEC 13F data lake contains the latest officially due quarter."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_SCHEDULE = "research/sec_13f_filing_schedule.json"
DEFAULT_FILINGS_INDEX = "data_pit/sec/13f_latest/sec_filings_index.parquet"
DEFAULT_MANAGER_CIKS = "outputs/sec_institutional_signals/manager_ciks.txt"
DEFAULT_OUTPUT_JSON = "outputs/sec_institutional_signals/13f_filing_freshness.json"
DEFAULT_OUTPUT_REPORT = "outputs/sec_institutional_signals/13f_filing_freshness.md"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_table(path: str | Path) -> pd.DataFrame:
    resolved = repo_path(path)
    if resolved.suffix.lower() == ".parquet":
        return pd.read_parquet(resolved)
    return pd.read_csv(resolved, low_memory=False)


def normalize_cik(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    digits = "".join(char for char in text if char.isdigit())
    if not digits:
        return ""
    return digits[-10:].zfill(10)


def manager_ciks_from_text(text: str) -> set[str]:
    values: set[str] = set()
    for token in str(text or "").replace("\n", ",").split(","):
        value = token.split(":", 1)[-1].strip()
        normalized = normalize_cik(value)
        if normalized and normalized != "0000000000":
            values.add(normalized)
    return values


def load_schedule(path: str | Path) -> dict[str, Any]:
    payload = json.loads(repo_path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "sec-13f-filing-schedule-v1":
        raise ValueError("unexpected 13F filing schedule schema")
    deadlines = payload.get("deadlines")
    if not isinstance(deadlines, list) or not deadlines:
        raise ValueError("13F filing schedule has no deadlines")
    seen: set[str] = set()
    previous_period: date | None = None
    for item in deadlines:
        period_end = date.fromisoformat(str(item["period_end"]))
        filing_deadline = date.fromisoformat(str(item["filing_deadline"]))
        if filing_deadline <= period_end:
            raise ValueError(f"invalid 13F filing deadline for {period_end}")
        if str(period_end) in seen or (previous_period is not None and period_end <= previous_period):
            raise ValueError("13F filing schedule periods must be unique and ascending")
        seen.add(str(period_end))
        previous_period = period_end
    return payload


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with repo_path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    value = numerator / denominator
    return float(value) if math.isfinite(value) else None


def evaluate_freshness(
    *,
    schedule: dict[str, Any],
    filings: pd.DataFrame,
    selected_manager_ciks: set[str],
    as_of: date,
    minimum_manager_coverage: float = 0.80,
    minimum_future_deadlines: int = 2,
) -> dict[str, Any]:
    deadlines = [
        {
            **item,
            "period_date": date.fromisoformat(str(item["period_end"])),
            "deadline_date": date.fromisoformat(str(item["filing_deadline"])),
        }
        for item in schedule["deadlines"]
    ]
    due = [item for item in deadlines if item["deadline_date"] <= as_of]
    future = [item for item in deadlines if item["deadline_date"] > as_of]
    next_deadline = future[0] if future else None
    latest_due = due[-1] if due else None
    open_periods = [
        item for item in future if item["period_date"] <= as_of
    ]
    monitored = open_periods[0] if open_periods else latest_due

    frame = filings.copy()
    for column in ["period_of_report", "accepted_at", "available_from", "form_type", "cik10"]:
        if column not in frame.columns:
            frame[column] = ""
        frame[column] = frame[column].fillna("").astype(str).str.strip()
    frame["cik10"] = frame["cik10"].map(normalize_cik)
    frame["form_type"] = frame["form_type"].str.upper()
    base = frame[frame["form_type"].eq("13F-HR")].copy()
    amendments = frame[frame["form_type"].eq("13F-HR/A")].copy()

    required_period_end = str(latest_due["period_end"]) if latest_due else ""
    monitored_period_end = str(monitored["period_end"]) if monitored else ""
    required_rows = frame[frame["period_of_report"].eq(required_period_end)] if required_period_end else frame.iloc[0:0]
    required_base = base[base["period_of_report"].eq(required_period_end)] if required_period_end else base.iloc[0:0]
    monitored_rows = frame[frame["period_of_report"].eq(monitored_period_end)] if monitored_period_end else frame.iloc[0:0]
    monitored_base = base[base["period_of_report"].eq(monitored_period_end)] if monitored_period_end else base.iloc[0:0]
    monitored_amendments = amendments[amendments["period_of_report"].eq(monitored_period_end)] if monitored_period_end else amendments.iloc[0:0]

    required_manager_ciks = set(required_base["cik10"]) - {""}
    covered_selected = required_manager_ciks & selected_manager_ciks if selected_manager_ciks else set()
    coverage = _finite_ratio(len(covered_selected), len(selected_manager_ciks))
    latest_accepted = pd.to_datetime(frame["accepted_at"], errors="coerce", utc=True).max()
    newest_period = pd.to_datetime(frame["period_of_report"], errors="coerce").max()

    blockers: list[str] = []
    if not selected_manager_ciks:
        blockers.append("selected_manager_universe_empty")
    if latest_due is not None and required_base.empty:
        blockers.append(f"missing_due_period:{required_period_end}")
    if latest_due is not None and selected_manager_ciks:
        if coverage is None or coverage < float(minimum_manager_coverage):
            blockers.append(
                "manager_coverage_below_threshold:"
                f"{0.0 if coverage is None else coverage:.6f}<{float(minimum_manager_coverage):.6f}"
            )
    if len(future) < int(minimum_future_deadlines):
        blockers.append(
            f"official_schedule_horizon_low:{len(future)}<{int(minimum_future_deadlines)}"
        )

    if blockers:
        status = "blocked"
    elif open_periods:
        status = "collecting_pre_deadline"
    else:
        status = "ready"

    monitored_deadline = str(monitored["filing_deadline"]) if monitored else ""
    return {
        "schema_version": "sec-13f-filing-freshness-v1",
        "status": status,
        "freshness_ready": not blockers,
        "as_of_date": as_of.isoformat(),
        "official_schedule_source": schedule.get("source", {}),
        "publication_model": (schedule.get("rule") or {}).get("publication_model", ""),
        "required_due_period_end": required_period_end,
        "required_due_deadline": str(latest_due["filing_deadline"]) if latest_due else "",
        "monitored_period_end": monitored_period_end,
        "monitored_deadline": monitored_deadline,
        "days_to_monitored_deadline": (
            (monitored["deadline_date"] - as_of).days if monitored else None
        ),
        "next_scheduled_period_end": str(next_deadline["period_end"]) if next_deadline else "",
        "next_scheduled_deadline": str(next_deadline["filing_deadline"]) if next_deadline else "",
        "days_to_next_scheduled_deadline": (
            (next_deadline["deadline_date"] - as_of).days if next_deadline else None
        ),
        "upcoming_deadlines": [
            {
                "period_end": str(item["period_end"]),
                "filing_deadline": str(item["filing_deadline"]),
            }
            for item in future[:4]
        ],
        "required_period_filing_rows": int(len(required_rows)),
        "required_period_base_filing_rows": int(len(required_base)),
        "required_period_manager_count": int(len(required_manager_ciks)),
        "selected_manager_count": int(len(selected_manager_ciks)),
        "covered_selected_manager_count": int(len(covered_selected)),
        "selected_manager_coverage": coverage,
        "minimum_manager_coverage": float(minimum_manager_coverage),
        "monitored_period_filing_rows": int(len(monitored_rows)),
        "monitored_period_base_filing_rows": int(len(monitored_base)),
        "monitored_period_amendment_rows": int(len(monitored_amendments)),
        "newest_period_of_report": "" if pd.isna(newest_period) else newest_period.date().isoformat(),
        "latest_accepted_at": "" if pd.isna(latest_accepted) else latest_accepted.isoformat(),
        "future_deadline_count": int(len(future)),
        "minimum_future_deadlines": int(minimum_future_deadlines),
        "blockers": blockers,
        "research_only": True,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "score_consumption": "confirmation_and_research_ranking_only",
    }


def render_report(payload: dict[str, Any]) -> str:
    coverage = payload.get("selected_manager_coverage")
    coverage_text = "n/a" if coverage is None else f"{float(coverage):.1%}"
    blockers = payload.get("blockers") or []
    lines = [
        "# SEC 13F Filing Freshness",
        "",
        f"- status: `{payload.get('status')}`",
        f"- as of: `{payload.get('as_of_date')}`",
        f"- latest officially due period: `{payload.get('required_due_period_end')}`",
        f"- official filing deadline: `{payload.get('required_due_deadline')}`",
        f"- monitored period: `{payload.get('monitored_period_end')}`",
        f"- monitored period base filings: {payload.get('monitored_period_base_filing_rows', 0)}",
        f"- next scheduled period/deadline: `{payload.get('next_scheduled_period_end')}` / `{payload.get('next_scheduled_deadline')}`",
        f"- selected-manager coverage for due period: {coverage_text}",
        f"- newest period in data: `{payload.get('newest_period_of_report')}`",
        f"- latest accepted at: `{payload.get('latest_accepted_at')}`",
        f"- score use: `{payload.get('score_consumption')}`",
        "",
        "13F filings are disclosed manager by manager through EDGAR; the official deadline is not a single announcement timestamp.",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- `{item}`" for item in blockers)
    if not blockers:
        lines.append("- none")
    source = payload.get("official_schedule_source") or {}
    lines.extend(["", f"Official source: {source.get('url', '')}"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedule", default=DEFAULT_SCHEDULE)
    parser.add_argument("--filings-index", default=DEFAULT_FILINGS_INDEX)
    parser.add_argument("--manager-ciks-file", default=DEFAULT_MANAGER_CIKS)
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--minimum-manager-coverage", type=float, default=0.80)
    parser.add_argument("--minimum-future-deadlines", type=int, default=2)
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-report", default=DEFAULT_OUTPUT_REPORT)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    schedule = load_schedule(args.schedule)
    filings_path = repo_path(args.filings_index)
    filings = read_table(filings_path)
    manager_path = repo_path(args.manager_ciks_file)
    manager_ciks = manager_ciks_from_text(
        manager_path.read_text(encoding="utf-8") if manager_path.exists() else ""
    )
    payload = evaluate_freshness(
        schedule=schedule,
        filings=filings,
        selected_manager_ciks=manager_ciks,
        as_of=date.fromisoformat(args.as_of),
        minimum_manager_coverage=float(args.minimum_manager_coverage),
        minimum_future_deadlines=int(args.minimum_future_deadlines),
    )
    payload["filings_index"] = str(filings_path)
    payload["filings_index_sha256"] = sha256_file(filings_path)
    output_json = repo_path(args.output_json)
    output_report = repo_path(args.output_report)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_report.write_text(render_report(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 2 if args.strict and not payload["freshness_ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

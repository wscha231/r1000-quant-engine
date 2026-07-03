#!/usr/bin/env python3
"""Append forward-service paper ledger rows from a hash-stamped snapshot seed.

This is research-only paper tracking. It never edits historical rows in place:
corrections are appended as new rows with ``event_type=correction`` and a
``correction_of_row_id`` reference.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = "outputs/forward_service_ledger/forward_paper_ledger.csv"
DEFAULT_SUMMARY = "outputs/forward_service_ledger/summary.json"
SCHEMA_VERSION = "forward-paper-ledger-v1"
HASH_FIELDS = [
    "schema_version",
    "event_type",
    "as_of_date",
    "portfolio_kind",
    "nav_usd",
    "period_return",
    "starting_nav_usd",
    "snapshot_hash",
    "public_snapshot_hash",
    "target_snapshot_hash",
    "broker_state_hash",
    "source_metric_mode",
    "research_only",
    "review_only",
    "correction_of_row_id",
    "correction_reason",
    "previous_row_hash",
]
FIELDNAMES = [
    "row_id",
    *HASH_FIELDS,
    "created_at_utc",
    "row_hash",
]


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in FIELDNAMES})


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def stable_hash(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def canonical_row_hash(row: dict[str, Any]) -> str:
    return stable_hash({key: str(row.get(key, "")) for key in HASH_FIELDS})


def row_id(row: dict[str, Any]) -> str:
    return stable_hash(
        {
            "event_type": row.get("event_type", ""),
            "as_of_date": row.get("as_of_date", ""),
            "portfolio_kind": row.get("portfolio_kind", ""),
            "snapshot_hash": row.get("snapshot_hash", ""),
            "nav_usd": row.get("nav_usd", ""),
            "correction_of_row_id": row.get("correction_of_row_id", ""),
            "correction_reason": row.get("correction_reason", ""),
        }
    )[:24]


def validate_chain(rows: list[dict[str, str]]) -> list[str]:
    issues: list[str] = []
    previous = ""
    for idx, row in enumerate(rows, start=1):
        if row.get("previous_row_hash", "") != previous:
            issues.append(f"row_{idx}_previous_hash_mismatch")
        expected = canonical_row_hash(row)
        if row.get("row_hash", "") != expected:
            issues.append(f"row_{idx}_row_hash_mismatch")
        previous = row.get("row_hash", "")
    return issues


def seed_rows(seed_csv: Path) -> list[dict[str, Any]]:
    rows = []
    for row in read_csv(seed_csv):
        nav = safe_float(row.get("starting_nav_usd"))
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "event_type": "seed",
                "as_of_date": row.get("freeze_date", ""),
                "portfolio_kind": row.get("portfolio_kind", ""),
                "nav_usd": f"{nav:.10f}",
                "period_return": "0.0000000000",
                "starting_nav_usd": f"{nav:.10f}",
                "snapshot_hash": row.get("snapshot_hash", ""),
                "public_snapshot_hash": row.get("public_snapshot_hash", row.get("snapshot_hash", "")),
                "target_snapshot_hash": row.get("target_snapshot_hash", ""),
                "broker_state_hash": row.get("broker_state_hash", ""),
                "source_metric_mode": row.get("source_metric_mode", ""),
                "research_only": str(row.get("research_only", "True")),
                "review_only": str(row.get("review_only", "True")),
                "correction_of_row_id": "",
                "correction_reason": "",
            }
        )
    return rows


def latest_seed_by_portfolio(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    seeds: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.get("event_type") == "seed":
            seeds[row.get("portfolio_kind", "")] = row
    return seeds


def valuation_rows(nav_csv: Path, existing: list[dict[str, str]], correction_reason: str) -> list[dict[str, Any]]:
    seeds = latest_seed_by_portfolio(existing)
    out = []
    for row in read_csv(nav_csv):
        portfolio = row.get("portfolio_kind", "")
        seed = seeds.get(portfolio)
        if not seed:
            raise ValueError(f"missing seed row for portfolio_kind={portfolio}")
        nav = safe_float(row.get("nav_usd"))
        starting = safe_float(seed.get("starting_nav_usd"))
        period_return = (nav / starting - 1.0) if starting else 0.0
        correction_of = row.get("correction_of_row_id", "")
        event_type = "correction" if correction_of or correction_reason else "valuation"
        out.append(
            {
                "schema_version": SCHEMA_VERSION,
                "event_type": event_type,
                "as_of_date": row.get("as_of_date", ""),
                "portfolio_kind": portfolio,
                "nav_usd": f"{nav:.10f}",
                "period_return": f"{period_return:.10f}",
                "starting_nav_usd": f"{starting:.10f}",
                "snapshot_hash": row.get("snapshot_hash", seed.get("snapshot_hash", "")),
                "public_snapshot_hash": row.get("public_snapshot_hash", seed.get("public_snapshot_hash", "")),
                "target_snapshot_hash": row.get("target_snapshot_hash", seed.get("target_snapshot_hash", "")),
                "broker_state_hash": row.get("broker_state_hash", seed.get("broker_state_hash", "")),
                "source_metric_mode": row.get("source_metric_mode", seed.get("source_metric_mode", "")),
                "research_only": "True",
                "review_only": "True",
                "correction_of_row_id": correction_of,
                "correction_reason": correction_reason or row.get("correction_reason", ""),
            }
        )
    return out


def duplicate_issues(existing: list[dict[str, str]], pending: list[dict[str, Any]]) -> list[str]:
    seen = {
        (row.get("event_type"), row.get("portfolio_kind"), row.get("as_of_date"))
        for row in existing
        if row.get("event_type") != "correction"
    }
    issues = []
    for row in pending:
        key = (row.get("event_type"), row.get("portfolio_kind"), row.get("as_of_date"))
        if row.get("event_type") != "correction" and key in seen:
            issues.append(f"duplicate_{row.get('event_type')}_{row.get('portfolio_kind')}_{row.get('as_of_date')}")
    return issues


def append_rows(existing: list[dict[str, str]], pending: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows = [dict(row) for row in existing]
    previous = rows[-1].get("row_hash", "") if rows else ""
    created_at = datetime.now(timezone.utc).isoformat()
    for row in pending:
        row["previous_row_hash"] = previous
        row["created_at_utc"] = created_at
        row["row_id"] = row_id(row)
        row["row_hash"] = canonical_row_hash(row)
        rows.append({key: str(row.get(key, "")) for key in FIELDNAMES})
        previous = row["row_hash"]
    return rows


def run(args: argparse.Namespace) -> dict[str, Any]:
    ledger = repo_path(args.ledger)
    summary_path = repo_path(args.summary)
    existing = read_csv(ledger)
    chain_issues = validate_chain(existing)
    if chain_issues:
        payload = {
            "status": "blocked",
            "schema_version": "forward-paper-ledger-update-v1",
            "reason": "existing_ledger_hash_chain_invalid",
            "issues": chain_issues,
            "ledger": str(ledger),
        }
        write_json(summary_path, payload)
        return payload

    pending: list[dict[str, Any]] = []
    if not existing:
        if not args.seed_csv:
            raise ValueError("--seed-csv is required when initializing a new ledger")
        pending.extend(seed_rows(repo_path(args.seed_csv)))
    if args.nav_csv:
        pending.extend(valuation_rows(repo_path(args.nav_csv), append_rows(existing, pending), args.correction_reason))

    dupes = duplicate_issues(existing, pending)
    if dupes:
        payload = {
            "status": "blocked",
            "schema_version": "forward-paper-ledger-update-v1",
            "reason": "duplicate_event_requires_correction_record",
            "issues": dupes,
            "ledger": str(ledger),
        }
        write_json(summary_path, payload)
        return payload

    rows = append_rows(existing, pending)
    write_csv(ledger, rows)
    payload = {
        "status": "completed",
        "schema_version": "forward-paper-ledger-update-v1",
        "ledger": str(ledger),
        "appended_rows": len(pending),
        "total_rows": len(rows),
        "last_row_hash": rows[-1].get("row_hash", "") if rows else "",
        "research_only": True,
        "review_only": True,
        "append_only": True,
        "retroactive_edits_allowed": False,
        "corrections_are_append_only": True,
    }
    write_json(summary_path, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-csv", default="", help="forward_ledger_seed.csv from run_forward_service_snapshot.py")
    parser.add_argument("--nav-csv", default="", help="Optional new NAV rows: as_of_date,portfolio_kind,nav_usd")
    parser.add_argument("--ledger", default=DEFAULT_LEDGER)
    parser.add_argument("--summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--correction-reason", default="")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Audit historical universe membership for PIT-safe production evidence.

This tool is diagnostic. It does not fetch data, mutate target books, change
scoring, or enable production. A clean label is emitted only when the supplied
membership file proves that historical membership was known at each rebalance
date and is not a current-constituents backfill.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_COLUMNS = (
    "rebalance_date",
    "ticker",
    "membership_source",
    "membership_available_from",
    "universe_label",
    "official_r1000_membership_proven",
    "proxy_universe_flag",
    "survivorship_status",
    "delisted_coverage_status",
    "ticker_change_coverage_status",
    "membership_pit_status",
)
OPTIONAL_COLUMNS = (
    "membership_end_date",
    "source_provenance_status",
)
CLEAN_SOURCE_KINDS = {"official_historical_membership", "historical_membership_file"}
TRUTHY = {"1", "true", "yes", "y", "clean", "pit_clean"}
CURRENT_PROXY_TOKENS = ("current_constituents", "current_constituents_proxy")
STATIC_SEED_TOKENS = ("static_seed", "iwb_static_seed", "static_iwb_seed")
PROXY_TOKENS = ("proxy", "pit_proxy_universe")
OFFICIAL_TOKENS = ("official_pit_r1000", "official_historical_membership")
CLEAN_STATUS_VALUES = {"", "clean", "covered", "pass", "known", "ok", "pit_clean"}
UNKNOWN_STATUS_VALUES = {"unknown", "missing", "unclean", "blocked", "not_covered", "gap"}
PROVENANCE_CLEAN_VALUES = {"reviewed", "verified", "audited", "official", "licensed", "clean", "pass"}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_default(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return list(reader.fieldnames or []), rows


def parse_date(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text[:10]).date().isoformat()
    except ValueError:
        return ""


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in TRUTHY


def lower_join(row: dict[str, Any], *columns: str) -> str:
    return " ".join(str(row.get(column) or "").strip().lower() for column in columns)


def contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def source_kind_for_row(row: dict[str, Any]) -> str:
    text = lower_join(row, "membership_source", "universe_label")
    if contains_any(text, CURRENT_PROXY_TOKENS):
        return "current_constituents_proxy"
    if contains_any(text, STATIC_SEED_TOKENS):
        return "static_seed"
    if contains_any(text, OFFICIAL_TOKENS) or truthy(row.get("official_r1000_membership_proven")):
        return "official_historical_membership"
    if "historical_membership_file" in text:
        return "historical_membership_file"
    if contains_any(text, PROXY_TOKENS) or truthy(row.get("proxy_universe_flag")):
        return "pit_proxy_universe"
    return "unknown"


def file_source_kind(row_kinds: Counter[str]) -> str:
    if not row_kinds:
        return "missing"
    for kind in ("current_constituents_proxy", "static_seed", "pit_proxy_universe"):
        if row_kinds.get(kind, 0):
            return kind
    if row_kinds and all(kind == "official_historical_membership" for kind in row_kinds):
        return "official_historical_membership"
    if row_kinds and all(kind in CLEAN_SOURCE_KINDS for kind in row_kinds):
        return "historical_membership_file"
    return row_kinds.most_common(1)[0][0]


def status_bad(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if text in CLEAN_STATUS_VALUES:
        return False
    return text in UNKNOWN_STATUS_VALUES


def provenance_clean(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in PROVENANCE_CLEAN_VALUES


def normalized_membership_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        rebalance_date = parse_date(row.get("rebalance_date"))
        membership_available_from = parse_date(row.get("membership_available_from"))
        source_kind = source_kind_for_row(row)
        universe_label = str(row.get("universe_label") or source_kind or "").strip()
        output.append(
            {
                "rebalance_date": rebalance_date,
                "ticker": str(row.get("ticker") or "").strip().upper(),
                "membership_source": str(row.get("membership_source") or "").strip(),
                "membership_available_from": membership_available_from,
                "membership_end_date": parse_date(row.get("membership_end_date")),
                "universe_label": universe_label,
                "official_r1000_membership_proven": bool(truthy(row.get("official_r1000_membership_proven"))),
                "proxy_universe_flag": bool(truthy(row.get("proxy_universe_flag")) or source_kind in {"pit_proxy_universe", "current_constituents_proxy", "static_seed"}),
                "survivorship_status": str(row.get("survivorship_status") or "").strip(),
                "delisted_coverage_status": str(row.get("delisted_coverage_status") or "").strip(),
                "ticker_change_coverage_status": str(row.get("ticker_change_coverage_status") or "").strip(),
                "membership_pit_status": str(row.get("membership_pit_status") or "").strip(),
                "source_provenance_status": str(row.get("source_provenance_status") or "").strip(),
                "_source_kind": source_kind,
            }
        )
    return output


def audit_membership_file(
    membership_file: Path,
    output_dir: Path,
    *,
    coverage_floor: int = 400,
) -> dict[str, Any]:
    fields, raw_rows = read_csv_rows(membership_file)
    rows = normalized_membership_rows(raw_rows)
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in fields]
    row_kinds = Counter(row["_source_kind"] for row in rows)
    source_kind = file_source_kind(row_kinds)
    by_date: dict[str, set[str]] = defaultdict(set)
    violations: list[dict[str, Any]] = []

    future_rows = 0
    unknown_available_from_rows = 0
    current_proxy_rows = 0
    static_seed_rows = 0
    proxy_rows = 0
    official_rows = 0
    survivorship_bad_rows = 0
    delisted_bad_rows = 0
    ticker_change_bad_rows = 0
    source_provenance_unreviewed_rows = 0
    membership_end_date_violation_rows = 0
    same_day_available_from_rows = 0

    for row in rows:
        date_key = row["rebalance_date"]
        ticker = row["ticker"]
        if date_key and ticker:
            by_date[date_key].add(ticker)
        kind = row["_source_kind"]
        if kind == "current_constituents_proxy":
            current_proxy_rows += 1
            violations.append({"type": "current_constituents_proxy", "rebalance_date": date_key, "ticker": ticker})
        if kind == "static_seed":
            static_seed_rows += 1
            violations.append({"type": "static_seed", "rebalance_date": date_key, "ticker": ticker})
        if kind in {"pit_proxy_universe", "current_constituents_proxy", "static_seed"} or row["proxy_universe_flag"]:
            proxy_rows += 1
        if kind == "official_historical_membership" or row["official_r1000_membership_proven"]:
            official_rows += 1
        if not row["membership_available_from"]:
            unknown_available_from_rows += 1
            violations.append({"type": "missing_membership_available_from", "rebalance_date": date_key, "ticker": ticker})
        elif row["rebalance_date"] and row["membership_available_from"] > row["rebalance_date"]:
            future_rows += 1
            violations.append(
                {
                    "type": "future_membership_available_from",
                    "rebalance_date": row["rebalance_date"],
                    "membership_available_from": row["membership_available_from"],
                    "ticker": ticker,
                }
            )
        elif row["rebalance_date"] and row["membership_available_from"] == row["rebalance_date"]:
            same_day_available_from_rows += 1
        if row["membership_end_date"] and row["rebalance_date"] and row["rebalance_date"] > row["membership_end_date"]:
            membership_end_date_violation_rows += 1
            violations.append(
                {
                    "type": "membership_after_membership_end_date",
                    "rebalance_date": row["rebalance_date"],
                    "membership_end_date": row["membership_end_date"],
                    "ticker": ticker,
                }
            )
        if status_bad(row["survivorship_status"]):
            survivorship_bad_rows += 1
        if status_bad(row["delisted_coverage_status"]):
            delisted_bad_rows += 1
        if status_bad(row["ticker_change_coverage_status"]):
            ticker_change_bad_rows += 1
        if kind in CLEAN_SOURCE_KINDS and not provenance_clean(row.get("source_provenance_status")):
            source_provenance_unreviewed_rows += 1

    coverage_by_date = [
        {"rebalance_date": date_key, "membership_count": len(tickers), "coverage_pass": len(tickers) >= coverage_floor}
        for date_key, tickers in sorted(by_date.items())
    ]
    coverage_pass = bool(coverage_by_date) and all(row["coverage_pass"] for row in coverage_by_date)
    blockers: list[str] = []
    if not membership_file.exists():
        blockers.append("membership_file_missing")
    if missing_columns:
        blockers.append("required_columns_missing")
    if source_kind not in CLEAN_SOURCE_KINDS:
        blockers.append(f"membership_source_kind_not_clean:{source_kind}")
    if future_rows:
        blockers.append("future_membership_available_from")
    if unknown_available_from_rows:
        blockers.append("unknown_membership_available_from")
    if current_proxy_rows:
        blockers.append("current_constituents_proxy_rows_present")
    if static_seed_rows:
        blockers.append("static_seed_rows_present")
    if not coverage_pass:
        blockers.append("membership_coverage_floor_failed")
    if survivorship_bad_rows or delisted_bad_rows or ticker_change_bad_rows:
        blockers.append("membership_lifecycle_coverage_not_clean")
    if membership_end_date_violation_rows:
        blockers.append("membership_end_date_violated")
    if source_provenance_unreviewed_rows:
        blockers.append("source_provenance_review_required")

    clean = not blockers
    official_clean = clean and source_kind == "official_historical_membership"
    manifest = {
        "schema_version": "pit-membership-manifest-v1",
        "generated_at_utc": now_utc(),
        "membership_file": str(membership_file),
        "membership_source": source_kind,
        "membership_source_kind": source_kind,
        "universe_label": "official_pit_r1000" if official_clean else ("historical_membership_file" if clean else source_kind),
        "official_r1000_membership_proven": bool(official_clean),
        "proxy_universe_flag": bool(proxy_rows or source_kind in {"pit_proxy_universe", "current_constituents_proxy", "static_seed"}),
        "start_date": min(by_date) if by_date else "",
        "end_date": max(by_date) if by_date else "",
        "rebalance_date_count": int(len(by_date)),
        "ticker_count": int(len({row["ticker"] for row in rows if row["ticker"]})),
        "coverage_by_date": coverage_by_date,
        "known_gaps": blockers,
        "promotion_eligible": bool(clean),
        "production_mutation_allowed": False,
    }
    audit = {
        "schema_version": "pit-membership-audit-v1",
        "generated_at_utc": manifest["generated_at_utc"],
        "status": "pass" if clean else "blocked",
        "pit_universe_label_clean": bool(clean),
        "historical_universe_pit_clean": bool(clean),
        "official_pit_r1000": bool(official_clean),
        "membership_source_kind": source_kind,
        "no_future_membership_violations": int(future_rows),
        "membership_available_from_future_rows": int(future_rows),
        "unknown_membership_available_from_rows": int(unknown_available_from_rows),
        "current_constituents_proxy_rows": int(current_proxy_rows),
        "static_seed_rows": int(static_seed_rows),
        "proxy_rows": int(proxy_rows),
        "official_rows": int(official_rows),
        "survivorship_bad_rows": int(survivorship_bad_rows),
        "delisted_coverage_bad_rows": int(delisted_bad_rows),
        "ticker_change_coverage_bad_rows": int(ticker_change_bad_rows),
        "source_provenance_unreviewed_rows": int(source_provenance_unreviewed_rows),
        "membership_end_date_violation_rows": int(membership_end_date_violation_rows),
        "same_day_membership_available_from_rows": int(same_day_available_from_rows),
        "recommended_production_coverage_floor": int(max(coverage_floor, 900)),
        "recommended_production_coverage_pass": bool(
            coverage_by_date
            and all(row["membership_count"] >= max(coverage_floor, 900) for row in coverage_by_date)
        ),
        "production_review_warnings": [
            warning
            for warning, active in [
                ("same_day_membership_available_from_rows_present", bool(same_day_available_from_rows)),
                (
                    "membership_count_below_recommended_production_floor",
                    bool(
                        coverage_by_date
                        and any(row["membership_count"] < max(coverage_floor, 900) for row in coverage_by_date)
                    ),
                ),
            ]
            if active
        ],
        "coverage_floor": int(coverage_floor),
        "coverage_pass": bool(coverage_pass),
        "coverage_by_date": coverage_by_date,
        "missing_required_columns": missing_columns,
        "violations_sample": violations[:25],
        "blockers": blockers,
        "production_mutation_allowed": False,
        "production_promotion_allowed": bool(clean),
    }
    public_rows = [{key: value for key, value in row.items() if not key.startswith("_")} for row in rows]
    write_json(output_dir / "pit_membership_manifest.json", manifest)
    write_json(output_dir / "pit_membership_audit.json", audit)
    write_csv(
        output_dir / "pit_membership_by_month.csv",
        public_rows,
        list(REQUIRED_COLUMNS[:4]) + ["membership_end_date"] + list(REQUIRED_COLUMNS[4:]) + ["source_provenance_status"],
    )
    write_report(output_dir / "pit_membership_audit.md", manifest, audit)
    return {"manifest": manifest, "audit": audit}


def write_report(path: Path, manifest: dict[str, Any], audit: dict[str, Any]) -> None:
    lines = [
        "# PIT Membership Audit",
        "",
        f"- status: `{audit.get('status')}`",
        f"- pit_universe_label_clean: `{str(audit.get('pit_universe_label_clean')).lower()}`",
        f"- historical_universe_pit_clean: `{str(audit.get('historical_universe_pit_clean')).lower()}`",
        f"- official_pit_r1000: `{str(audit.get('official_pit_r1000')).lower()}`",
        f"- membership_source_kind: `{audit.get('membership_source_kind')}`",
        f"- universe_label: `{manifest.get('universe_label')}`",
        f"- production_promotion_allowed: `{str(audit.get('production_promotion_allowed')).lower()}`",
        "",
        "## Counts",
        "",
        f"- future membership rows: `{audit.get('membership_available_from_future_rows')}`",
        f"- unknown available_from rows: `{audit.get('unknown_membership_available_from_rows')}`",
        f"- current constituents proxy rows: `{audit.get('current_constituents_proxy_rows')}`",
        f"- static seed rows: `{audit.get('static_seed_rows')}`",
        f"- proxy rows: `{audit.get('proxy_rows')}`",
        f"- official rows: `{audit.get('official_rows')}`",
        f"- source provenance unreviewed rows: `{audit.get('source_provenance_unreviewed_rows')}`",
        f"- membership end-date violation rows: `{audit.get('membership_end_date_violation_rows')}`",
        f"- same-day available_from rows: `{audit.get('same_day_membership_available_from_rows')}`",
        f"- recommended production coverage floor: `{audit.get('recommended_production_coverage_floor')}`",
        f"- recommended production coverage pass: `{str(audit.get('recommended_production_coverage_pass')).lower()}`",
        "",
        "## Production Review Warnings",
        "",
    ]
    warnings = audit.get("production_review_warnings") or []
    lines.extend([f"- {item}" for item in warnings] if warnings else ["- none"])
    lines.extend(
        [
        "",
        "## Blockers",
        "",
        ]
    )
    blockers = audit.get("blockers") or []
    lines.extend([f"- {item}" for item in blockers] if blockers else ["- none"])
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--membership-file", required=True)
    parser.add_argument("--output-dir", default="outputs/universe_health")
    parser.add_argument("--coverage-floor", type=int, default=400)
    parser.add_argument("--strict", action="store_true", help="Exit nonzero when the PIT membership audit is blocked.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = audit_membership_file(
        repo_path(args.membership_file),
        repo_path(args.output_dir),
        coverage_floor=int(args.coverage_floor),
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=json_default))
    if args.strict and not payload["audit"].get("pit_universe_label_clean"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

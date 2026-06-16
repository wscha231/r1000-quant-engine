#!/usr/bin/env python3
"""Audit the R1000/IWB universe substrate used by a run.

This tool is diagnostic only. It does not fetch data, rewrite target books,
or mutate strategy state. It exists to make the INVALID_UNIVERSE class
actionable by recording which universe source chain was visible to the run and
whether the scored R1000 base is broad enough for official promotion.
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
DATE_COLUMNS = ("rebalance_date", "feature_date", "as_of_date", "date", "Date")
SOURCE_COLUMNS = ("universe_source", "source_universe")
R1000_SOURCE_TOKENS = (
    "current_constituents_proxy",
    "historical_membership_file",
    "iwb_static_seed",
    "static_seed",
)
FUNDAMENTAL_COLUMNS = (
    "cik10",
    "revenues_ttm",
    "sales_growth_yoy",
    "gross_profit_ttm",
    "gross_margin",
    "quality_score",
    "fundamental_quality_score",
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")


def json_default(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def safe_upper(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.strip().upper()


def non_empty(value: Any) -> bool:
    text = "" if value is None else str(value).strip()
    return bool(text and text.lower() not in {"nan", "none", "null"})


def parse_date_text(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text[:10]).date().isoformat()
    except ValueError:
        return ""


def first_present(fields: list[str], candidates: tuple[str, ...]) -> str:
    for column in candidates:
        if column in fields:
            return column
    return ""


def is_r1000_source(source: Any) -> bool:
    lowered = str(source or "").lower()
    return any(token in lowered for token in R1000_SOURCE_TOKENS)


def path_stats(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path)}
    if path.is_dir():
        files = [item for item in path.rglob("*") if item.is_file()]
        latest_mtime = max((item.stat().st_mtime for item in files), default=None)
        return {
            "exists": True,
            "path": str(path),
            "kind": "dir",
            "file_count": int(len(files)),
            "size_bytes": int(sum(item.stat().st_size for item in files)),
            "modified_utc": datetime.fromtimestamp(latest_mtime, timezone.utc).isoformat()
            if latest_mtime
            else "",
        }
    stat = path.stat()
    return {
        "exists": True,
        "path": str(path),
        "kind": "file",
        "size_bytes": int(stat.st_size),
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def iter_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = [dict(row) for row in reader]
            return list(reader.fieldnames or []), rows
    except Exception:
        return [], []


def csv_source_summary(path: Path) -> dict[str, Any]:
    fields, rows = iter_csv_rows(path)
    source_column = first_present(fields, SOURCE_COLUMNS)
    date_column = first_present(fields, DATE_COLUMNS)
    tickers = {safe_upper(row.get("ticker")) for row in rows if safe_upper(row.get("ticker"))}
    source_counts: Counter[str] = Counter()
    dates: list[str] = []
    r1000_tickers: set[str] = set()
    fundamental_rows = 0
    for row in rows:
        source = row.get(source_column, "") if source_column else ""
        if source:
            source_counts[str(source)] += 1
        if date_column:
            parsed = parse_date_text(row.get(date_column))
            if parsed:
                dates.append(parsed)
        ticker = safe_upper(row.get("ticker"))
        if ticker and is_r1000_source(source):
            r1000_tickers.add(ticker)
        if any(non_empty(row.get(column)) for column in FUNDAMENTAL_COLUMNS):
            fundamental_rows += 1
    return {
        "path": str(path),
        "exists": path.exists(),
        "row_count": int(len(rows)),
        "ticker_count": int(len(tickers)),
        "source_column": source_column,
        "date_column": date_column,
        "min_date": min(dates) if dates else "",
        "max_date": max(dates) if dates else "",
        "r1000_base_count": int(len(r1000_tickers)),
        "source_counts": dict(source_counts.most_common(25)),
        "fundamental_coverage_pct": (float(fundamental_rows / len(rows)) if rows else None),
    }


def source_counts_from_rows(rows: list[dict[str, str]], source_column: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        value = str(row.get(source_column, "")).strip()
        if value:
            counts[value] += 1
    return counts


def price_symbols(price_cache: Path) -> set[str]:
    if not price_cache.exists():
        return set()
    symbols: set[str] = set()
    for suffix in ("*.parquet", "*.csv"):
        for path in price_cache.glob(suffix):
            if path.name.startswith("replay_price_cache_manifest"):
                continue
            stem = path.stem.upper().replace("-", ".")
            if stem:
                symbols.add(stem)
    return symbols


def coverage_ratio(tickers: set[str], covered: set[str]) -> float | None:
    if not tickers or not covered:
        return None
    return float(len(tickers & covered) / len(tickers))


def count_rows_by_date(scored_path: Path, candidate_path: Path, price_cache: Path) -> list[dict[str, Any]]:
    scored_fields, scored_rows = iter_csv_rows(scored_path)
    candidate_fields, candidate_rows = iter_csv_rows(candidate_path)
    scored_date_col = first_present(scored_fields, DATE_COLUMNS)
    scored_source_col = first_present(scored_fields, SOURCE_COLUMNS)
    candidate_date_col = first_present(candidate_fields, DATE_COLUMNS)
    price_set = price_symbols(price_cache)

    candidate_counts: dict[str, int] = defaultdict(int)
    for row in candidate_rows:
        date_key = parse_date_text(row.get(candidate_date_col)) if candidate_date_col else ""
        if date_key:
            candidate_counts[date_key] += 1

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in scored_rows:
        date_key = parse_date_text(row.get(scored_date_col)) if scored_date_col else ""
        grouped[date_key or "undated"].append(row)

    output: list[dict[str, Any]] = []
    for date_key in sorted(grouped):
        rows = grouped[date_key]
        tickers = {safe_upper(row.get("ticker")) for row in rows if safe_upper(row.get("ticker"))}
        r1000_tickers = {
            safe_upper(row.get("ticker"))
            for row in rows
            if safe_upper(row.get("ticker")) and is_r1000_source(row.get(scored_source_col, "") if scored_source_col else "")
        }
        fundamental_rows = sum(1 for row in rows if any(non_empty(row.get(column)) for column in FUNDAMENTAL_COLUMNS))
        source_counts = dict(source_counts_from_rows(rows, scored_source_col).most_common(10)) if scored_source_col else {}
        output.append(
            {
                "date": "" if date_key == "undated" else date_key,
                "r1000_base_count": int(len(r1000_tickers)),
                "scored_count": int(len(rows)),
                "candidate_count": int(candidate_counts.get(date_key, 0)),
                "price_coverage_pct": coverage_ratio(tickers, price_set),
                "fundamental_coverage_pct": float(fundamental_rows / len(rows)) if rows else None,
                "universe_source": ";".join(source_counts.keys())[:500],
                "fallback_used": any("static_seed" in key.lower() or "previous_healthy" in key.lower() for key in source_counts),
                "promotion_allowed": bool(len(r1000_tickers) >= 400),
            }
        )
    return output


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def safe_parquet_summary(path: Path) -> dict[str, Any]:
    stats = path_stats(path)
    stats["row_count"] = 0
    stats["r1000_base_count"] = 0
    if not path.exists() or path.suffix.lower() != ".parquet":
        return stats
    try:
        import pandas as pd  # type: ignore

        frame = pd.read_parquet(path)
    except Exception as exc:
        stats["read_error"] = str(exc)
        return stats
    stats["row_count"] = int(len(frame))
    if "ticker" in frame.columns:
        stats["ticker_count"] = int(frame["ticker"].astype(str).str.upper().nunique())
    source_col = "universe_source" if "universe_source" in frame.columns else "source_universe" if "source_universe" in frame.columns else ""
    if source_col and "ticker" in frame.columns:
        mask = frame[source_col].fillna("").astype(str).map(is_r1000_source)
        stats["r1000_base_count"] = int(frame.loc[mask, "ticker"].astype(str).str.upper().nunique())
    return stats


def fallback_source_audit(latest_run: Path) -> dict[str, Any]:
    paths = {
        "restored_drive_iwb_parquet": REPO_ROOT / "aggressive" / "cache" / "universe" / "iwb_holdings.parquet",
        "restored_drive_iwb_csv": REPO_ROOT / "aggressive" / "cache" / "universe" / "iwb_holdings.csv",
        "data_raw_iwb_seed": REPO_ROOT / "data_raw" / "iwb_holdings_seed.csv",
        "data_static_iwb_seed": REPO_ROOT / "data_static" / "iwb_holdings_seed.csv",
        "previous_healthy_candidate_universe": REPO_ROOT / "feature_store" / "candidate_universe_latest.parquet",
        "latest_run_candidate_universe": latest_run / "feature_store" / "candidate_universe_latest.parquet",
    }
    historical_candidates = sorted(
        set(REPO_ROOT.glob("**/historical_universe_membership*.csv"))
        | set(REPO_ROOT.glob("**/*historical*membership*.csv"))
    )
    audited_paths = {name: path_stats(path) for name, path in paths.items()}
    previous_summary = safe_parquet_summary(paths["previous_healthy_candidate_universe"])
    historical_summary = {
        "file_count": int(len(historical_candidates)),
        "paths": [str(path) for path in historical_candidates[:25]],
    }
    return {
        "live_iwb_fetch_status": "inferred_from_run_outputs",
        "restored_drive_iwb": {
            "available": bool(paths["restored_drive_iwb_parquet"].exists() or paths["restored_drive_iwb_csv"].exists()),
            "paths": {
                "parquet": audited_paths["restored_drive_iwb_parquet"],
                "csv": audited_paths["restored_drive_iwb_csv"],
            },
        },
        "previous_healthy_universe_cache": previous_summary,
        "static_iwb_seed": {
            "available": bool(paths["data_static_iwb_seed"].exists() or paths["data_raw_iwb_seed"].exists()),
            "paths": {
                "data_static": audited_paths["data_static_iwb_seed"],
                "data_raw": audited_paths["data_raw_iwb_seed"],
            },
        },
        "historical_universe_membership": historical_summary,
        "all_checked_paths": audited_paths,
    }


def infer_primary_source(scored_summary: dict[str, Any]) -> str:
    counts = scored_summary.get("source_counts") or {}
    if not counts:
        return "missing"
    lowered = {str(key).lower(): value for key, value in counts.items()}
    if any("historical_membership_file" in key for key in lowered):
        return "historical_membership_file"
    if any("current_constituents_proxy" in key and "static_seed" not in key for key in lowered):
        return "current_constituents_proxy"
    if any("static_seed" in key for key in lowered):
        return "static_iwb_seed"
    return next(iter(counts.keys()))


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    scored_path = latest_run / "scored_latest.csv"
    candidate_paths = [
        latest_run / "reports" / "candidate_replay_book.csv",
        latest_run / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv",
    ]
    candidate_path = next((path for path in candidate_paths if path.exists()), candidate_paths[0])
    scored = csv_source_summary(scored_path)
    candidate = csv_source_summary(candidate_path)
    fallback = fallback_source_audit(latest_run)
    rows_by_date = count_rows_by_date(scored_path, candidate_path, price_cache)

    r1000_base_count = int(scored.get("r1000_base_count") or 0)
    scored_count = int(scored.get("row_count") or 0)
    promotion_allowed = bool(args.universe_mode == "adr" or r1000_base_count >= int(args.min_r1000_base))
    status = "pass" if promotion_allowed else "invalid_universe"
    primary_source = infer_primary_source(scored)
    fallback_used = bool(
        primary_source == "static_iwb_seed"
        or any(row.get("fallback_used") for row in rows_by_date)
        or int((fallback.get("previous_healthy_universe_cache") or {}).get("r1000_base_count") or 0) >= int(args.min_r1000_base)
    )
    blockers: list[str] = []
    if args.universe_mode != "adr" and r1000_base_count < int(args.min_r1000_base):
        blockers.append(
            f"scored R1000 base below floor: {r1000_base_count} < {int(args.min_r1000_base)}"
        )
    if not scored_path.exists():
        blockers.append("scored_latest.csv missing")
    if not candidate_path.exists():
        blockers.append("candidate_replay_book.csv missing")

    next_actions = []
    if blockers:
        next_actions.extend(
            [
                "Stop T3/recovery A/B until universe health passes.",
                "Check live IWB fetch logs and restored Drive/cache IWB holdings.",
                "Use previous healthy universe or committed static IWB seed only with explicit fallback metadata.",
                "Rerun 8-year rebuild only after data_readiness.ready_for_policy_replay=true.",
            ]
        )

    payload = {
        "schema_version": "universe-health-v1",
        "generated_at_utc": now_utc(),
        "production_mutation_allowed": False,
        "latest_run": str(latest_run),
        "price_cache": str(price_cache),
        "output_dir": str(output_dir),
        "universe_mode": args.universe_mode,
        "status": status,
        "promotion_allowed": promotion_allowed,
        "min_r1000_base": int(args.min_r1000_base),
        "r1000_base_count": r1000_base_count,
        "scored_count": scored_count,
        "candidate_count": int(candidate.get("row_count") or 0),
        "primary_universe_source": primary_source,
        "fallback_used": fallback_used,
        "scored_latest": scored,
        "candidate_replay_book": candidate,
        "fallback_source_chain": fallback,
        "blockers": blockers,
        "next_actions": next_actions,
        "rules": {
            "fallback_order": [
                "live_iShares_IWB_holdings_fetch",
                "restored_Drive_or_cache_IWB_holdings",
                "previous_healthy_current_constituents_proxy",
                "committed_static_IWB_seed",
                "hard_fail",
            ],
            "promotion_rule": "non-ADR runs require scored R1000 base >= min_r1000_base and valid 8-year broker-ledger evidence",
            "do_not_use_for": "strategy promotion or A/B baseline when status != pass",
        },
    }
    write_json(output_dir / "universe_source_audit.json", payload)
    write_json(output_dir / "summary.json", payload)
    write_csv(
        output_dir / "scored_row_count_by_date.csv",
        rows_by_date,
        [
            "date",
            "r1000_base_count",
            "scored_count",
            "candidate_count",
            "price_coverage_pct",
            "fundamental_coverage_pct",
            "universe_source",
            "fallback_used",
            "promotion_allowed",
        ],
    )
    write_csv(
        output_dir / "universe_membership_by_month.csv",
        rows_by_date,
        [
            "date",
            "r1000_base_count",
            "scored_count",
            "candidate_count",
            "price_coverage_pct",
            "fundamental_coverage_pct",
            "universe_source",
            "fallback_used",
            "promotion_allowed",
        ],
    )
    write_json(output_dir / "iwb_fetch_status.json", fallback)
    write_json(output_dir / "iwd_iwb_fetch_status.json", fallback)
    write_report(output_dir / "universe_fallback_decision.md", payload)
    return payload


def write_report(path: Path, payload: dict[str, Any]) -> None:
    action = "ALLOW_REVIEW_ONLY" if payload.get("promotion_allowed") else "DO_NOT_PROMOTE"
    lines = [
        "# Universe Fallback Decision",
        "",
        f"- status: `{payload.get('status')}`",
        f"- action: `{action}`",
        f"- promotion_allowed: `{str(payload.get('promotion_allowed')).lower()}`",
        f"- universe_mode: `{payload.get('universe_mode')}`",
        f"- r1000_base_count: `{payload.get('r1000_base_count')}`",
        f"- scored_count: `{payload.get('scored_count')}`",
        f"- candidate_count: `{payload.get('candidate_count')}`",
        f"- primary_universe_source: `{payload.get('primary_universe_source')}`",
        f"- fallback_used: `{str(payload.get('fallback_used')).lower()}`",
        "",
        "## Blockers",
        "",
    ]
    blockers = payload.get("blockers") or []
    lines.extend([f"- {item}" for item in blockers] if blockers else ["- none"])
    lines.extend(
        [
            "",
            "## Required Fallback Order",
            "",
        ]
    )
    for idx, item in enumerate((payload.get("rules") or {}).get("fallback_order") or [], start=1):
        lines.append(f"{idx}. {item}")
    lines.extend(["", "## Next Actions", ""])
    actions = payload.get("next_actions") or []
    lines.extend([f"- {item}" for item in actions] if actions else ["- none"])
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/universe_health")
    parser.add_argument("--min-r1000-base", type=int, default=400)
    parser.add_argument("--universe-mode", default="global_alpha_universe")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero when universe promotion is not allowed.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_payload(args)
    print(json.dumps(payload, indent=2, sort_keys=True, default=json_default))
    if args.strict and not payload.get("promotion_allowed"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

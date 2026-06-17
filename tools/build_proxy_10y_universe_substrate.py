#!/usr/bin/env python3
"""Build a review-only monthly ``pit_proxy_universe`` substrate manifest.

This tool turns the review-only universe recovery candidate into a monthly
proxy membership artifact for 10Y robustness work. It is intentionally not an
official Russell 1000 history builder: current or fallback membership repeated
back in time carries survivorship risk and stays labelled ``pit_proxy_universe``.

No production universe, scored file, target book, broker replay input, strategy
parameter, or trading state is mutated.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REQUIRED_BENCHMARKS = ("SPY", "QQQ", "SMH", "SOXX")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def clean_ticker(value: Any) -> str:
    ticker = str(value or "").strip().upper()
    if ticker in {"", "NAN", "NONE", "NULL"}:
        return ""
    return ticker.replace("-", ".")


def truthy(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1", "yes", "y"}


def falsey(value: Any) -> bool:
    return value is False or str(value).strip().lower() in {"false", "0", "no", "n"}


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def month_iter(start: date, end: date) -> list[str]:
    months: list[str] = []
    current = month_start(start)
    stop = month_start(end)
    while current <= stop:
        months.append(current.strftime("%Y-%m"))
        year = current.year + (1 if current.month == 12 else 0)
        month = 1 if current.month == 12 else current.month + 1
        current = date(year, month, 1)
    return months


def read_candidate_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        rows = []
        for row in csv.DictReader(handle):
            ticker = clean_ticker(row.get("ticker"))
            if ticker:
                row["ticker"] = ticker
                rows.append(dict(row))
        return rows


def candidate_safety_issues(rows: list[dict[str, Any]]) -> list[str]:
    counts = {
        "candidate_rows_not_review_only": 0,
        "candidate_rows_allow_canonical_production_sync": 0,
        "candidate_rows_allow_production_mutation": 0,
        "candidate_rows_allow_promotion": 0,
        "candidate_rows_allow_production_promotion": 0,
        "candidate_rows_allow_live_trading": 0,
        "candidate_rows_missing_human_approval_required": 0,
    }
    for row in rows:
        if not truthy(row.get("review_only")):
            counts["candidate_rows_not_review_only"] += 1
        if not falsey(row.get("canonical_production_sync")):
            counts["candidate_rows_allow_canonical_production_sync"] += 1
        if not falsey(row.get("production_mutation_allowed")):
            counts["candidate_rows_allow_production_mutation"] += 1
        if row.get("promotion_allowed") not in {None, ""} and not falsey(row.get("promotion_allowed")):
            counts["candidate_rows_allow_promotion"] += 1
        if not falsey(row.get("production_promotion_allowed")):
            counts["candidate_rows_allow_production_promotion"] += 1
        if not falsey(row.get("live_trading_enabled")):
            counts["candidate_rows_allow_live_trading"] += 1
        if not truthy(row.get("human_approval_required")):
            counts["candidate_rows_missing_human_approval_required"] += 1
    return [f"{key}:{value}" for key, value in counts.items() if value]


def manifest_symbols(payload: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for key in ("symbols", "tickers", "requested_symbols", "requested_tickers", "price_symbols"):
        value = payload.get(key)
        if isinstance(value, list):
            out.update(clean_ticker(item) for item in value if clean_ticker(item))
    return out


def price_manifest(price_cache: Path) -> dict[str, Any]:
    return read_json(price_cache / "replay_price_cache_manifest.json") or read_json(
        REPO_ROOT / "data_raw" / "free" / "prices" / "replay_price_cache_manifest.json"
    )


def csv_price_range(path: Path) -> tuple[date | None, date | None]:
    dates: list[date] = []
    if not path.exists():
        return None, None
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        date_col = "date" if "date" in fields else "Date" if "Date" in fields else ""
        if not date_col:
            return None, None
        for row in reader:
            dt = parse_date(row.get(date_col))
            if dt:
                dates.append(dt)
    return (min(dates), max(dates)) if dates else (None, None)


def parquet_price_range(path: Path) -> tuple[date | None, date | None]:
    try:
        import pandas as pd  # type: ignore
    except Exception:
        return None, None
    try:
        frame = pd.read_parquet(path, columns=["date"])
    except Exception:
        try:
            frame = pd.read_parquet(path)
        except Exception:
            return None, None
    if frame.empty:
        return None, None
    date_col = "date" if "date" in frame.columns else "Date" if "Date" in frame.columns else ""
    if not date_col:
        return None, None
    dates = pd.to_datetime(frame[date_col], errors="coerce").dropna()
    if dates.empty:
        return None, None
    return dates.min().date(), dates.max().date()


def price_ranges(price_cache: Path) -> dict[str, dict[str, Any]]:
    ranges: dict[str, dict[str, Any]] = {}
    if not price_cache.is_dir():
        return ranges
    for pattern in ("*.csv", "*.parquet"):
        for path in price_cache.glob(pattern):
            if path.name.startswith("replay_price_cache_manifest"):
                continue
            ticker = clean_ticker(path.stem)
            if not ticker:
                continue
            start, end = csv_price_range(path) if path.suffix.lower() == ".csv" else parquet_price_range(path)
            ranges[ticker] = {
                "path": str(path),
                "start": start.isoformat() if start else "",
                "end": end.isoformat() if end else "",
                "start_date": start,
                "end_date": end,
            }
    manifest = price_manifest(price_cache)
    start = parse_date(manifest.get("start"))
    end = parse_date(manifest.get("end"))
    for ticker in manifest_symbols(manifest):
        ranges.setdefault(
            ticker,
            {
                "path": str(price_cache / f"{ticker}.manifest"),
                "start": start.isoformat() if start else "",
                "end": end.isoformat() if end else "",
                "start_date": start,
                "end_date": end,
            },
        )
    return ranges


def candidate_csv_path(latest_run: Path, recovery_summary: dict[str, Any]) -> Path:
    outputs = recovery_summary.get("outputs") if isinstance(recovery_summary.get("outputs"), dict) else {}
    path = str(outputs.get("candidate_csv") or "").strip()
    if path:
        return repo_path(path)
    return latest_run / "universe_recovery_candidate" / "candidate_universe_recovery.csv"


def range_covers_month(row: dict[str, Any], month: str, *, window_start: date, window_end: date) -> bool:
    start = row.get("start_date")
    end = row.get("end_date")
    if not isinstance(start, date) or not isinstance(end, date):
        return False
    month_dt = datetime.fromisoformat(f"{month}-01").date()
    ref_dt = max(month_dt, window_start)
    if month == window_end.strftime("%Y-%m"):
        ref_dt = min(ref_dt, window_end)
    return start <= ref_dt <= end


def classify_proxy_10y_universe_substrate(
    latest_run: str | Path,
    *,
    price_cache: str | Path = "cache_prices",
    start_date: str = "2016-08-26",
    end_date: str = "",
    min_membership_count: int = 400,
    min_price_coverage_pct: float = 0.95,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run_dir = repo_path(latest_run)
    price_dir = repo_path(price_cache)
    recovery = read_json(run_dir / "universe_recovery_candidate" / "summary.json")
    recovery_readiness = read_json(run_dir / "universe_recovery_candidate_readiness" / "summary.json")
    candidate_path = candidate_csv_path(run_dir, recovery)
    candidates = read_candidate_rows(candidate_path)
    tickers = sorted({clean_ticker(row.get("ticker")) for row in candidates if clean_ticker(row.get("ticker"))})
    prices = price_ranges(price_dir)
    manifest = price_manifest(price_dir)
    start = parse_date(start_date) or date(2016, 8, 26)
    end = parse_date(end_date) or parse_date(manifest.get("end")) or datetime.now(timezone.utc).date()

    blockers: list[str] = []
    warnings: list[str] = []
    if recovery.get("status") not in {"candidate_ready", "none_required"}:
        blockers.append(f"universe_recovery_candidate_status:{recovery.get('status') or 'missing'}")
    if recovery.get("status") == "candidate_ready" and recovery_readiness.get("status") != "candidate_readiness_pass":
        blockers.append(f"universe_recovery_candidate_readiness_status:{recovery_readiness.get('status') or 'missing'}")
    blockers.extend(candidate_safety_issues(candidates))
    if len(tickers) < int(min_membership_count):
        blockers.append(f"candidate_membership_below_floor:{len(tickers)}<{int(min_membership_count)}")
    if not prices:
        blockers.append("price_cache_missing")
    benchmark_missing = [ticker for ticker in REQUIRED_BENCHMARKS if ticker not in prices]
    if benchmark_missing:
        blockers.append("required_benchmark_price_missing:" + ",".join(benchmark_missing))

    months = month_iter(start, end)
    rows: list[dict[str, Any]] = []
    failed_months: list[str] = []
    for month in months:
        covered = [ticker for ticker in tickers if range_covers_month(prices.get(ticker, {}), month, window_start=start, window_end=end)]
        coverage = 0.0 if not tickers else len(covered) / len(tickers)
        pass_month = len(covered) >= int(min_membership_count) and coverage >= float(min_price_coverage_pct)
        if not pass_month:
            failed_months.append(month)
        rows.append(
            {
                "month": month,
                "membership_count": len(tickers),
                "price_covered_count": len(covered),
                "price_coverage_pct": round(coverage, 6),
                "tradeable_count_proxy": len(covered),
                "universe_source": recovery.get("recommended_recovery_source") or "review_only_recovery_candidate",
                "pit_label": "pit_proxy_universe",
                "official_russell_1000": False,
                "review_only": True,
                "canonical_production_sync": False,
                "production_mutation_allowed": False,
                "production_promotion_allowed": False,
                "live_trading_enabled": False,
                "human_approval_required": True,
                "survivorship_status": "proxy_current_or_fallback_membership_replayed_back_in_time",
                "delisted_coverage": "not_available_in_free_proxy",
                "ticker_change_coverage": "not_available_in_free_proxy",
                "promotion_allowed": False,
                "proxy_month_pass": pass_month,
            }
        )

    if failed_months:
        sample = ",".join(failed_months[:8])
        blockers.append(f"monthly_proxy_universe_coverage_failed:{len(failed_months)} months:{sample}")
    if recovery.get("recommended_recovery_source") in {"committed_static_IWB_seed", "previous_healthy_current_constituents_proxy"}:
        warnings.append("proxy universe uses current/fallback membership and is subject to survivorship bias")

    status = "proxy_10y_universe_ready" if not blockers else "not_ready"
    payload = {
        "schema_version": "proxy-10y-universe-substrate-v1",
        "generated_at_utc": now_utc(),
        "latest_run": str(run_dir),
        "status": status,
        "evidence_label": "proxy_10y",
        "pit_label": "pit_proxy_universe",
        "official_russell_1000": False,
        "review_only": True,
        "canonical_production_sync": False,
        "production_mutation_allowed": False,
        "production_promotion_allowed": False,
        "promotion_allowed": False,
        "promotion_allowed_scope": "proxy_10y_universe_substrate_review_only",
        "live_trading_enabled": False,
        "human_approval_required": True,
        "ready_for_proxy_10y_rebuild_review": status == "proxy_10y_universe_ready",
        "candidate_csv": str(candidate_path),
        "candidate_row_count": len(tickers),
        "price_cache": str(price_dir),
        "price_symbol_count": len(prices),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "month_count": len(months),
        "failed_month_count": len(failed_months),
        "min_membership_count": int(min_membership_count),
        "min_price_coverage_pct": float(min_price_coverage_pct),
        "benchmark_coverage": {
            "required": list(REQUIRED_BENCHMARKS),
            "missing": benchmark_missing,
            "pass": not benchmark_missing,
        },
        "recovery_candidate_status": recovery.get("status"),
        "recovery_candidate_readiness_status": recovery_readiness.get("status"),
        "recommended_recovery_source": recovery.get("recommended_recovery_source"),
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "allowed_uses": ["proxy_10y_rebuild_review"] if not blockers else ["diagnostics"],
        "blocked_uses": [
            "official_russell_1000_claim",
            "official_promotion",
            "production_universe_mutation",
            "target_book_mutation",
            "live_trading",
            "automatic_workflow_dispatch",
        ],
        "notes": [
            "proxy_10y_universe_ready is not official Russell 1000 membership evidence.",
            "Use this only as a robustness substrate until PIT-safe historical membership, delisting, and ticker-change coverage exist.",
        ],
    }
    return payload, rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "month",
        "membership_count",
        "price_covered_count",
        "price_coverage_pct",
        "tradeable_count_proxy",
        "universe_source",
        "pit_label",
            "official_russell_1000",
            "review_only",
            "canonical_production_sync",
            "production_mutation_allowed",
            "production_promotion_allowed",
            "live_trading_enabled",
            "human_approval_required",
            "survivorship_status",
        "delisted_coverage",
        "ticker_change_coverage",
        "promotion_allowed",
        "proxy_month_pass",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Proxy 10Y Universe Substrate",
        "",
        f"- status: `{payload.get('status')}`",
        f"- evidence_label: `{payload.get('evidence_label')}`",
        f"- pit_label: `{payload.get('pit_label')}`",
        f"- official_russell_1000: `{payload.get('official_russell_1000')}`",
        f"- review_only: `{payload.get('review_only')}`",
        f"- canonical_production_sync: `{payload.get('canonical_production_sync')}`",
        f"- production_mutation_allowed: `{payload.get('production_mutation_allowed')}`",
        f"- production_promotion_allowed: `{payload.get('production_promotion_allowed')}`",
        f"- promotion_allowed_scope: `{payload.get('promotion_allowed_scope')}`",
        f"- live_trading_enabled: `{payload.get('live_trading_enabled')}`",
        f"- human_approval_required: `{payload.get('human_approval_required')}`",
        f"- ready_for_proxy_10y_rebuild_review: `{payload.get('ready_for_proxy_10y_rebuild_review')}`",
        f"- month_count: `{payload.get('month_count')}`",
        f"- failed_month_count: `{payload.get('failed_month_count')}`",
        "",
        "## Blockers",
        "",
    ]
    blockers = payload.get("blockers") or []
    lines.extend(f"- `{item}`" for item in blockers) if blockers else lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    warnings = payload.get("warnings") or []
    lines.extend(f"- {item}" for item in warnings) if warnings else lines.append("- none")
    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {item}" for item in payload.get("notes", []))
    return "\n".join(lines) + "\n"


def write_outputs(payload: dict[str, Any], rows: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", payload)
    write_csv(output_dir / "proxy_universe_membership_by_month.csv", rows)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/proxy_10y_universe_substrate")
    parser.add_argument("--start-date", default="2016-08-26")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--min-membership-count", type=int, default=400)
    parser.add_argument("--min-price-coverage-pct", type=float, default=0.95)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload, rows = classify_proxy_10y_universe_substrate(
        args.latest_run,
        price_cache=args.price_cache,
        start_date=args.start_date,
        end_date=args.end_date,
        min_membership_count=args.min_membership_count,
        min_price_coverage_pct=args.min_price_coverage_pct,
    )
    write_outputs(payload, rows, repo_path(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

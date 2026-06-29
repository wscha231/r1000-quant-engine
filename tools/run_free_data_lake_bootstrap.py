#!/usr/bin/env python3
"""Bootstrap and audit the free-first data lake.

This tool is intentionally a coordinator, not a second data engine. It calls
existing collectors where possible, writes a durable manifest, and labels the
resulting data as PIT-safe, proxy, or research-only so backtests cannot hide
data-quality assumptions.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUTPUT_DIR = "outputs/free_data_lake_bootstrap"
DEFAULT_MANIFEST_DIR = "manifests/free_data"
DEFAULT_PIT_LABEL = "pit_proxy_universe"
REQUIRED_BENCHMARK_PRICE_TICKERS = ("SPY", "QQQ")


@dataclass
class CommandResult:
    name: str
    command: list[str]
    exit_code: int
    status: str
    required: bool
    stdout_tail: str


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def path_stats(path: Path) -> dict[str, Any]:
    exists = path.exists()
    file_count = 0
    size_bytes = 0
    if exists and path.is_file():
        file_count = 1
        size_bytes = path.stat().st_size
    elif exists and path.is_dir():
        for item in path.rglob("*"):
            if item.is_file():
                file_count += 1
                try:
                    size_bytes += item.stat().st_size
                except OSError:
                    pass
    return {
        "path": rel(path),
        "exists": exists,
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
        "file_count": file_count,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / 1024 / 1024, 3),
    }


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def run_command(name: str, command: list[str], required: bool) -> CommandResult:
    proc = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    out = proc.stdout or ""
    tail = out[-6000:]
    status = "passed" if proc.returncode == 0 else "failed"
    print(f"[free-data] {name}: {status} exit_code={proc.returncode}", flush=True)
    if tail.strip():
        print(tail, flush=True)
    if required and proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return CommandResult(
        name=name,
        command=command,
        exit_code=proc.returncode,
        status=status,
        required=required,
        stdout_tail=tail,
    )


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            total = sum(1 for _ in handle)
        return max(total - 1, 0)
    except OSError:
        return 0


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def latest_run_summary(latest_run: Path) -> dict[str, Any]:
    reports = latest_run / "reports"
    backtest = read_json(latest_run / "backtest_metrics.json", {}) or {}
    concentrated = read_json(latest_run / "concentrated_backtest_metrics.json", {}) or {}
    dataset_audit = read_json(reports / "dataset_coverage_audit.json", {}) or {}
    return {
        "latest_run": rel(latest_run),
        "exists": latest_run.exists(),
        "scored_latest_rows": count_csv_rows(latest_run / "scored_latest.csv"),
        "candidate_replay_rows": count_csv_rows(reports / "candidate_replay_book.csv"),
        "main_monthly_weight_rows": count_csv_rows(reports / "main_monthly_weights.csv"),
        "concentrated_holding_rows": count_csv_rows(reports / "concentrated_strategy_holdings.csv"),
        "main_cagr": backtest.get("cagr"),
        "main_sharpe": backtest.get("sharpe"),
        "main_max_drawdown": backtest.get("max_drawdown"),
        "concentrated_cagr": concentrated.get("cagr"),
        "concentrated_sharpe": concentrated.get("sharpe"),
        "concentrated_max_drawdown": concentrated.get("max_drawdown"),
        "dataset_audit_status": dataset_audit.get("status"),
        "dataset_audit_label": dataset_audit.get("dataset_label") or dataset_audit.get("pit_label"),
    }


def copy_price_manifest(cache_dir: Path, price_raw_dir: Path) -> None:
    src = cache_dir / "replay_price_cache_manifest.json"
    if src.exists():
        price_raw_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, price_raw_dir / src.name)


def price_cache_data_file_count(cache_dir: Path) -> int:
    if not cache_dir.exists() or not cache_dir.is_dir():
        return 0
    return sum(1 for path in cache_dir.glob("*.parquet") if path.is_file())


def build_coverage_audit(
    args: argparse.Namespace,
    actions: list[CommandResult],
    latest_summary: dict[str, Any],
) -> dict[str, Any]:
    data_root = repo_path(args.data_root)
    cache_dir = repo_path(args.price_cache)
    sec_zip = data_root / "data_raw" / "free" / "sec" / "companyfacts.zip"
    macro_dir = data_root / "data_raw" / "free" / "macro"
    price_manifest = data_root / "data_raw" / "free" / "prices" / "replay_price_cache_manifest.json"
    price_manifest_payload = read_json(price_manifest, {}) or {}
    price_cache_files = price_cache_data_file_count(cache_dir)
    required_price_tickers = safe_int(price_manifest_payload.get("book_ticker_count"))
    requested_price_tickers = safe_int(price_manifest_payload.get("ticker_count"))
    price_coverage_ratio = (
        float(price_cache_files) / float(required_price_tickers)
        if required_price_tickers > 0
        else (1.0 if price_cache_files > 0 else 0.0)
    )
    price_ready = required_price_tickers > 0 and price_cache_files >= required_price_tickers
    latest_exists = bool(latest_summary.get("exists"))
    has_target_books = (
        int(latest_summary.get("main_monthly_weight_rows") or 0) > 0
        and int(latest_summary.get("concentrated_holding_rows") or 0) > 0
    )
    known_gaps: list[str] = []
    if args.pit_label != "pit_safe":
        known_gaps.append("historical Russell 1000 membership is not proven PIT-safe in the free tier")
    if not sec_zip.exists():
        known_gaps.append("SEC companyfacts bulk archive is not present in data_raw/free/sec")
    if price_cache_files <= 0:
        known_gaps.append("free price cache is not populated yet")
    elif not price_ready:
        known_gaps.append(
            f"free price cache coverage incomplete: {price_cache_files}/{required_price_tickers} required target-book tickers"
        )
    if not has_target_books:
        known_gaps.append("monthly target books are missing, so proxy replay cannot run")
    readiness = "ready_for_proxy_replay" if latest_exists and has_target_books and price_ready else "manifest_only"
    return {
        "schema_version": "free-data-coverage-v1",
        "generated_at_utc": now_utc(),
        "pit_label": args.pit_label,
        "readiness": readiness,
        "latest_run": latest_summary,
        "sources": {
            "sec_companyfacts": {
                "tier": "official_free",
                "status": "available" if sec_zip.exists() else "missing",
                "path": rel(sec_zip),
            },
            "macro": {
                "tier": "official_free_plus_market_proxy",
                "status": "available" if macro_dir.exists() and path_stats(macro_dir)["file_count"] > 0 else "missing",
                "path": rel(macro_dir),
            },
            "prices": {
                "tier": "free_provider_reconciled_later",
                "status": "available" if price_cache_files > 0 else "missing",
                "cache_path": rel(cache_dir),
                "manifest_path": rel(price_manifest),
                "cache_data_file_count": price_cache_files,
                "required_target_book_ticker_count": required_price_tickers,
                "requested_ticker_count": requested_price_tickers,
                "coverage_ratio": round(price_coverage_ratio, 6),
            },
            "universe": {
                "tier": "proxy_until_historical_constituents_added",
                "status": "available" if has_target_books else "missing",
                "label": "proxy_large_cap_target_books",
            },
        },
        "actions": [asdict(action) for action in actions],
        "known_gaps": known_gaps,
    }


def build_manifest(
    args: argparse.Namespace,
    actions: list[CommandResult],
    latest_summary: dict[str, Any],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    data_root = repo_path(args.data_root)
    paths = [
        data_root / "data_raw" / "free",
        data_root / "data_raw" / "free" / "sec",
        data_root / "data_raw" / "free" / "prices",
        data_root / "data_raw" / "free" / "macro",
        data_root / "data_raw" / "free" / "universe_proxy",
        data_root / "data_pit" / "free",
        repo_path(args.price_cache),
        repo_path(args.manifest_dir),
    ]
    return {
        "schema_version": "free-data-lake-manifest-v1",
        "generated_at_utc": now_utc(),
        "repo_root": str(REPO_ROOT.resolve()),
        "pit_label": args.pit_label,
        "requested": {
            "latest_run": rel(repo_path(args.latest_run)),
            "sec_companyfacts": bool(args.sec_companyfacts),
            "macro_snapshot": not bool(args.skip_macro_snapshot),
            "price_mode": args.price_mode,
            "price_start": args.price_start,
            "max_price_tickers": int(args.max_price_tickers),
            "max_scored": int(args.max_scored),
            "required_benchmark_price_tickers": list(REQUIRED_BENCHMARK_PRICE_TICKERS),
            "required_downloads": bool(args.required_downloads),
        },
        "latest_run": latest_summary,
        "coverage": {
            "readiness": coverage.get("readiness"),
            "known_gaps": coverage.get("known_gaps", []),
        },
        "paths": [path_stats(path) for path in paths],
        "actions": [asdict(action) for action in actions],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    data_root = repo_path(args.data_root)
    output_dir = repo_path(args.output_dir)
    manifest_dir = repo_path(args.manifest_dir)
    pit_dir = data_root / "data_pit" / "free"
    raw_sec_dir = data_root / "data_raw" / "free" / "sec"
    raw_price_dir = data_root / "data_raw" / "free" / "prices"
    raw_macro_dir = data_root / "data_raw" / "free" / "macro" / "daily_snapshot"
    raw_universe_dir = data_root / "data_raw" / "free" / "universe_proxy"
    cache_dir = repo_path(args.price_cache)

    for path in [output_dir, manifest_dir, pit_dir, raw_sec_dir, raw_price_dir, raw_macro_dir, raw_universe_dir, cache_dir]:
        path.mkdir(parents=True, exist_ok=True)

    latest_run = repo_path(args.latest_run)
    latest_summary = latest_run_summary(latest_run)
    actions: list[CommandResult] = []

    if args.sec_companyfacts:
        command = [
            sys.executable,
            str(REPO_ROOT / "tools" / "refresh_companyfacts_bulk.py"),
            "--base-dir",
            str(raw_sec_dir),
            "--max-age-days",
            str(args.sec_max_age_days),
        ]
        if args.required_downloads:
            command.append("--required")
        actions.append(run_command("sec_companyfacts", command, required=args.required_downloads))

    if not args.skip_macro_snapshot:
        command = [
            sys.executable,
            str(REPO_ROOT / "tools" / "macro_daily_snapshot.py"),
            "--out-dir",
            str(raw_macro_dir),
        ]
        actions.append(run_command("macro_snapshot", command, required=False))

    if args.price_mode != "none":
        reports = latest_run / "reports"
        books = [reports / "main_monthly_weights.csv", reports / "concentrated_strategy_holdings.csv"]
        missing_books = [str(path) for path in books if not path.exists()]
        if missing_books:
            actions.append(
                CommandResult(
                    name="price_cache",
                    command=[],
                    exit_code=0,
                    status="skipped_missing_books",
                    required=False,
                    stdout_tail="\n".join(missing_books),
                )
            )
        else:
            command = [
                sys.executable,
                str(REPO_ROOT / "tools" / "build_replay_price_cache.py"),
                "--books",
                str(books[0]),
                str(books[1]),
                "--scored",
                str(latest_run / "scored_latest.csv"),
                "--max-scored",
                str(args.max_scored),
                "--output-dir",
                str(cache_dir),
                "--start",
                args.price_start,
                "--batch-size",
                str(args.batch_size),
                "--required-tickers",
                *REQUIRED_BENCHMARK_PRICE_TICKERS,
            ]
            if int(args.max_price_tickers) > 0:
                command += ["--max-tickers", str(args.max_price_tickers)]
            if args.price_mode == "dry_run":
                command.append("--dry-run")
            actions.append(run_command("price_cache", command, required=args.required_downloads and args.price_mode == "target_books"))
            copy_price_manifest(cache_dir, raw_price_dir)

    coverage = build_coverage_audit(args, actions, latest_summary)
    manifest = build_manifest(args, actions, latest_summary, coverage)

    coverage_path = pit_dir / "coverage_audit.json"
    manifest_path = manifest_dir / "latest_manifest.json"
    summary_path = output_dir / "summary.json"
    write_json(coverage_path, coverage)
    write_json(manifest_path, manifest)
    write_json(summary_path, {"manifest": manifest, "coverage": coverage})

    print(json.dumps({"summary": rel(summary_path), "manifest": rel(manifest_path), "coverage": rel(coverage_path), "readiness": coverage["readiness"]}, indent=2))
    return {"manifest": manifest, "coverage": coverage}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--data-root", default=".")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest-dir", default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--pit-label", default=DEFAULT_PIT_LABEL, choices=["pit_safe", "pit_proxy_universe", "research_proxy"])
    parser.add_argument("--sec-companyfacts", action="store_true")
    parser.add_argument("--sec-max-age-days", type=float, default=7.0)
    parser.add_argument("--skip-macro-snapshot", action="store_true")
    parser.add_argument("--price-mode", choices=["none", "dry_run", "target_books"], default="dry_run")
    parser.add_argument("--price-start", default="2016-01-01")
    parser.add_argument("--max-price-tickers", type=int, default=80)
    parser.add_argument("--max-scored", type=int, default=250)
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--required-downloads", action="store_true")
    return parser.parse_args()


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate review-only universe recovery candidates before repair review.

``prepare_universe_recovery_candidate.py`` materializes the fallback universe
recommended by the universe-health audit. This tool is the next safety layer:
it checks whether that candidate is broad enough and price-covered enough to
be reviewed as a clean-7Y substrate repair candidate.

It does not mutate scored files, production universes, target books, broker
replay inputs, cash policy, strategy parameters, or live trading state.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
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


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def manifest_symbols(payload: dict[str, Any]) -> set[str]:
    symbols: set[str] = set()
    for key in ("symbols", "tickers", "requested_symbols", "requested_tickers", "price_symbols"):
        value = payload.get(key)
        if isinstance(value, list):
            symbols.update(clean_ticker(item) for item in value if clean_ticker(item))
    return symbols


def price_cache_symbols(price_cache: Path) -> set[str]:
    symbols: set[str] = set()
    if price_cache.is_dir():
        for pattern in ("*.csv", "*.parquet"):
            for item in price_cache.glob(pattern):
                if item.name.startswith("replay_price_cache_manifest"):
                    continue
                ticker = clean_ticker(item.stem)
                if ticker:
                    symbols.add(ticker)
        symbols.update(manifest_symbols(read_json(price_cache / "replay_price_cache_manifest.json")))
    symbols.update(manifest_symbols(read_json(REPO_ROOT / "data_raw" / "free" / "prices" / "replay_price_cache_manifest.json")))
    return symbols


def coverage_ratio(numer: int, denom: int) -> float:
    return 0.0 if denom <= 0 else float(numer / denom)


def candidate_csv_from_summary(latest_run: Path, summary: dict[str, Any]) -> Path:
    outputs = summary.get("outputs") if isinstance(summary.get("outputs"), dict) else {}
    path = str(outputs.get("candidate_csv") or "").strip()
    if path:
        return repo_path(path)
    return latest_run / "universe_recovery_candidate" / "candidate_universe_recovery.csv"


def classify_universe_recovery_candidate_readiness(
    latest_run: str | Path,
    *,
    price_cache: str | Path = "cache_prices",
    min_r1000_base: int = 400,
    min_price_coverage_pct: float = 0.95,
) -> dict[str, Any]:
    run_dir = repo_path(latest_run)
    price_dir = repo_path(price_cache)
    recovery_summary_path = run_dir / "universe_recovery_candidate" / "summary.json"
    recovery = read_json(recovery_summary_path)
    candidate_csv = candidate_csv_from_summary(run_dir, recovery)
    rows = read_csv_rows(candidate_csv)

    blockers: list[str] = []
    warnings: list[str] = []
    status = "not_ready"

    if not recovery:
        blockers.append("universe_recovery_candidate_summary_missing")
    elif recovery.get("status") == "none_required":
        status = "none_required"
    elif recovery.get("status") != "candidate_ready":
        blockers.append(f"universe_recovery_candidate_status:{recovery.get('status') or 'missing'}")

    tickers: list[str] = []
    seen: set[str] = set()
    duplicate_count = 0
    review_only_bad = 0
    canonical_sync_bad = 0
    production_mutation_bad = 0
    promotion_bad = 0
    production_promotion_bad = 0
    live_trading_bad = 0
    human_approval_bad = 0
    for row in rows:
        ticker = clean_ticker(row.get("ticker"))
        if not ticker:
            continue
        if ticker in seen:
            duplicate_count += 1
            continue
        seen.add(ticker)
        tickers.append(ticker)
        if not truthy(row.get("review_only")):
            review_only_bad += 1
        if row.get("canonical_production_sync") not in {None, ""} and not falsey(row.get("canonical_production_sync")):
            canonical_sync_bad += 1
        if not falsey(row.get("production_mutation_allowed")):
            production_mutation_bad += 1
        if row.get("promotion_allowed") not in {None, ""} and not falsey(row.get("promotion_allowed")):
            promotion_bad += 1
        if row.get("production_promotion_allowed") not in {None, ""} and not falsey(row.get("production_promotion_allowed")):
            production_promotion_bad += 1
        if row.get("live_trading_enabled") not in {None, ""} and not falsey(row.get("live_trading_enabled")):
            live_trading_bad += 1
        if row.get("human_approval_required") not in {None, ""} and not truthy(row.get("human_approval_required")):
            human_approval_bad += 1

    if status != "none_required":
        if not candidate_csv.exists():
            blockers.append("candidate_universe_recovery_csv_missing")
        if len(tickers) < int(min_r1000_base):
            blockers.append(f"candidate_row_count_below_floor:{len(tickers)}<{int(min_r1000_base)}")
        if duplicate_count:
            warnings.append(f"duplicate_ticker_rows_dropped:{duplicate_count}")
        if review_only_bad:
            blockers.append(f"candidate_rows_not_review_only:{review_only_bad}")
        if canonical_sync_bad:
            blockers.append(f"candidate_rows_allow_canonical_production_sync:{canonical_sync_bad}")
        if production_mutation_bad:
            blockers.append(f"candidate_rows_allow_production_mutation:{production_mutation_bad}")
        if promotion_bad:
            blockers.append(f"candidate_rows_allow_promotion:{promotion_bad}")
        if production_promotion_bad:
            blockers.append(f"candidate_rows_allow_production_promotion:{production_promotion_bad}")
        if live_trading_bad:
            blockers.append(f"candidate_rows_allow_live_trading:{live_trading_bad}")
        if human_approval_bad:
            blockers.append(f"candidate_rows_missing_human_approval_required:{human_approval_bad}")

    price_symbols = price_cache_symbols(price_dir)
    available = sorted(ticker for ticker in tickers if ticker in price_symbols)
    missing = sorted(ticker for ticker in tickers if ticker not in price_symbols)
    price_coverage_pct = coverage_ratio(len(available), len(tickers))
    benchmark_missing = [ticker for ticker in REQUIRED_BENCHMARKS if ticker not in price_symbols]

    if status != "none_required":
        if not price_symbols:
            blockers.append("price_cache_symbols_missing")
        if price_coverage_pct < float(min_price_coverage_pct):
            blockers.append(
                f"candidate_price_coverage_below_floor:{price_coverage_pct:.4f}<"
                f"{float(min_price_coverage_pct):.4f}"
            )
        if benchmark_missing:
            blockers.append("required_benchmark_price_missing:" + ",".join(benchmark_missing))

    if status != "none_required":
        status = "candidate_readiness_pass" if not blockers else "not_ready"

    return {
        "schema_version": "universe-recovery-candidate-readiness-v1",
        "generated_at_utc": now_utc(),
        "latest_run": str(run_dir),
        "status": status,
        "review_only": True,
        "canonical_production_sync": False,
        "production_mutation_allowed": False,
        "production_promotion_allowed": False,
        "promotion_allowed": False,
        "promotion_allowed_scope": "universe_recovery_candidate_readiness_only",
        "live_trading_enabled": False,
        "automatic_repair_allowed": False,
        "human_approval_required": True,
        "ready_for_clean_7y_substrate_repair_review": status == "candidate_readiness_pass",
        "recovery_candidate_summary_path": str(recovery_summary_path),
        "candidate_csv": str(candidate_csv),
        "recovery_candidate_status": recovery.get("status"),
        "recommended_recovery_source": recovery.get("recommended_recovery_source"),
        "recovery_action": recovery.get("recovery_action"),
        "candidate_row_count": len(tickers),
        "min_r1000_base": int(min_r1000_base),
        "price_cache": str(price_dir),
        "price_symbol_count": len(price_symbols),
        "candidate_price_coverage_pct": round(price_coverage_pct, 6),
        "min_price_coverage_pct": float(min_price_coverage_pct),
        "candidate_price_covered_count": len(available),
        "candidate_price_missing_count": len(missing),
        "candidate_price_missing_sample": missing[:25],
        "benchmark_coverage": {
            "required": list(REQUIRED_BENCHMARKS),
            "missing": benchmark_missing,
            "pass": not benchmark_missing,
        },
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "allowed_uses": ["review_universe_recovery_candidate"] if status == "candidate_readiness_pass" else ["diagnostics"],
        "blocked_uses": [
            "production_universe_mutation",
            "target_book_mutation",
            "broker_replay_input_mutation",
            "production_promotion",
            "live_trading",
            "automatic_workflow_dispatch",
        ],
        "notes": [
            "candidate_readiness_pass means the fallback candidate can be reviewed for clean 7Y substrate repair.",
            "It does not authorize automatic repair, broker replay, promotion, or live trading.",
        ],
    }


def write_missing_price_csv(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"ticker": ticker} for ticker in payload.get("candidate_price_missing_sample", [])]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker"])
        writer.writeheader()
        writer.writerows(rows)


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Universe Recovery Candidate Readiness",
        "",
        f"- status: `{payload.get('status')}`",
        f"- ready_for_clean_7y_substrate_repair_review: `{payload.get('ready_for_clean_7y_substrate_repair_review')}`",
        f"- review_only: `{payload.get('review_only')}`",
        f"- canonical_production_sync: `{payload.get('canonical_production_sync')}`",
        f"- production_mutation_allowed: `{payload.get('production_mutation_allowed')}`",
        f"- production_promotion_allowed: `{payload.get('production_promotion_allowed')}`",
        f"- promotion_allowed_scope: `{payload.get('promotion_allowed_scope')}`",
        f"- automatic_repair_allowed: `{payload.get('automatic_repair_allowed')}`",
        f"- live_trading_enabled: `{payload.get('live_trading_enabled')}`",
        f"- human_approval_required: `{payload.get('human_approval_required')}`",
        f"- candidate_row_count: `{payload.get('candidate_row_count')}`",
        f"- candidate_price_coverage_pct: `{payload.get('candidate_price_coverage_pct')}`",
        "",
        "## Blockers",
        "",
    ]
    blockers = payload.get("blockers") or []
    lines.extend(f"- `{item}`" for item in blockers) if blockers else lines.append("- none")
    lines.extend(["", "## Benchmark Coverage", ""])
    coverage = payload.get("benchmark_coverage") if isinstance(payload.get("benchmark_coverage"), dict) else {}
    lines.append(f"- pass: `{coverage.get('pass')}`")
    lines.append(f"- missing: `{', '.join(coverage.get('missing') or [])}`")
    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {item}" for item in payload.get("notes", []))
    return "\n".join(lines) + "\n"


def write_outputs(payload: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    write_missing_price_csv(output_dir / "missing_price_tickers.csv", payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/universe_recovery_candidate_readiness")
    parser.add_argument("--min-r1000-base", type=int, default=400)
    parser.add_argument("--min-price-coverage-pct", type=float, default=0.95)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = classify_universe_recovery_candidate_readiness(
        args.latest_run,
        price_cache=args.price_cache,
        min_r1000_base=args.min_r1000_base,
        min_price_coverage_pct=args.min_price_coverage_pct,
    )
    write_outputs(payload, repo_path(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

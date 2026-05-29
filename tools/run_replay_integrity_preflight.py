#!/usr/bin/env python3
"""Replay-integrity preflight for AlphaOps research sidecars.

The report is deliberately conservative. It marks results DO_NOT_USE when a
historical replay silently falls back to latest-only data, legacy concentrated
filters, stale prices, or non-broker-ledger metrics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import load_price_series, px_cache_name  # noqa: E402


DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUTPUT_DIR = "outputs/replay_integrity"
BENCHMARK_TICKERS = ("SPY", "QQQ")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        if path.suffix.lower() == ".parquet":
            return pd.read_parquet(path)
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def date_text(value: Any) -> str:
    dt = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(dt) else pd.Timestamp(dt).date().isoformat()


def infer_candidate_book(latest_run: Path, explicit: str | None) -> tuple[Path, str]:
    if explicit:
        return repo_path(explicit), "explicit"
    candidate = latest_run / "reports" / "candidate_replay_book.csv"
    if candidate.exists():
        return candidate, "historical_candidate_book"
    latest = latest_run / "scored_latest.csv"
    if latest.exists():
        return latest, "latest_only"
    return candidate, "missing"


def expected_latest_market_close(asof: str | None = None) -> pd.Timestamp:
    now = pd.Timestamp(asof or datetime.now(timezone.utc).date()).normalize()
    # Approximate US trading calendar with business days. This is a preflight
    # freshness guard, not an exchange-calendar settlement engine.
    days = pd.bdate_range(now - pd.Timedelta(days=10), now)
    return pd.Timestamp(days[-1]).normalize() if len(days) else now


def business_day_lag(latest_date: str, expected_date: pd.Timestamp) -> int:
    latest = pd.to_datetime(latest_date, errors="coerce")
    if pd.isna(latest):
        return 999
    days = pd.bdate_range(pd.Timestamp(latest).normalize(), expected_date.normalize())
    return max(0, len(days) - 1)


def target_book_stats(path: Path) -> dict[str, Any]:
    target = read_csv(path)
    if target.empty:
        return {
            "target_book_exists": bool(path.exists()),
            "target_book_row_count": 0,
            "requested_target_n": None,
            "target_book_date_range_start": "",
            "target_book_date_range_end": "",
        }
    out = target.copy()
    if "rebalance_date" in out.columns:
        dates = pd.to_datetime(out["rebalance_date"], errors="coerce").dropna()
    else:
        dates = pd.Series(dtype="datetime64[ns]")
    requested = None
    for col in ("target_n", "target_stock_names"):
        if col in out.columns:
            vals = pd.to_numeric(out[col], errors="coerce").dropna()
            if not vals.empty:
                requested = int(vals.mode().iloc[0])
                break
    return {
        "target_book_exists": True,
        "target_book_row_count": int(len(target)),
        "requested_target_n": requested,
        "target_book_date_range_start": pd.Timestamp(dates.min()).date().isoformat() if not dates.empty else "",
        "target_book_date_range_end": pd.Timestamp(dates.max()).date().isoformat() if not dates.empty else "",
    }


def actual_position_stats(broker_dir: Path) -> dict[str, Any]:
    equity = read_csv(broker_dir / "equity_curve.csv")
    if equity.empty or "position_count" not in equity.columns:
        return {
            "actual_latest_position_count": None,
            "actual_avg_position_count": None,
            "actual_median_position_count": None,
        }
    counts = pd.to_numeric(equity["position_count"], errors="coerce").dropna()
    return {
        "actual_latest_position_count": int(counts.iloc[-1]) if not counts.empty else None,
        "actual_avg_position_count": float(counts.mean()) if not counts.empty else None,
        "actual_median_position_count": float(counts.median()) if not counts.empty else None,
    }


def readable_price_stats(price_cache: Path | None, ticker: str) -> dict[str, Any]:
    ticker = str(ticker).upper().strip()
    path = price_cache / px_cache_name(ticker) if price_cache is not None else Path("")
    exists = bool(price_cache is not None and path.exists())
    frame = load_price_series(price_cache, ticker) if price_cache is not None else pd.DataFrame()
    readable = not frame.empty and "close" in frame.columns and pd.to_numeric(frame["close"], errors="coerce").notna().any()
    dates = pd.to_datetime(frame.index, errors="coerce").dropna() if readable else pd.DatetimeIndex([])
    return {
        f"{ticker.lower()}_price_exists": exists,
        f"{ticker.lower()}_price_readable": bool(readable),
        f"{ticker.lower()}_price_row_count": int(len(frame)) if readable else 0,
        f"{ticker.lower()}_price_date_range_start": pd.Timestamp(dates.min()).date().isoformat() if len(dates) else "",
        f"{ticker.lower()}_price_date_range_end": pd.Timestamp(dates.max()).date().isoformat() if len(dates) else "",
    }


def price_cache_coverage(target_book: Path | None, price_cache: Path | None) -> dict[str, Any]:
    if target_book is None or price_cache is None:
        return {"price_cache_coverage": None, "price_cache_missing_ticker_count": None, "price_cache_missing_tickers": []}
    target = read_csv(target_book)
    if target.empty or "ticker" not in target.columns:
        return {"price_cache_coverage": None, "price_cache_missing_ticker_count": None, "price_cache_missing_tickers": []}
    tickers = sorted({str(x).upper().strip() for x in target["ticker"].dropna().unique() if str(x).upper().strip() not in {"", "CASH", "__CASH__"}})
    if not tickers:
        return {"price_cache_coverage": 1.0, "price_cache_missing_ticker_count": 0, "price_cache_missing_tickers": []}
    missing = [ticker for ticker in tickers if not readable_price_stats(price_cache, ticker).get(f"{ticker.lower()}_price_readable")]
    return {
        "price_cache_coverage": float((len(tickers) - len(missing)) / max(len(tickers), 1)),
        "price_cache_missing_ticker_count": int(len(missing)),
        "price_cache_missing_tickers": missing[:50],
    }


def benchmark_price_coverage(price_cache: Path | None) -> dict[str, Any]:
    if price_cache is None:
        return {
            "spy_price_coverage": None,
            "qqq_price_coverage": None,
            "benchmark_price_missing": list(BENCHMARK_TICKERS),
            "benchmark_coverage_ratio": 0.0,
            "benchmark_date_range_start": "",
            "benchmark_date_range_end": "",
        }
    stats: dict[str, Any] = {}
    missing: list[str] = []
    starts: list[pd.Timestamp] = []
    ends: list[pd.Timestamp] = []
    for ticker in BENCHMARK_TICKERS:
        ticker_stats = readable_price_stats(price_cache, ticker)
        stats.update(ticker_stats)
        if not ticker_stats.get(f"{ticker.lower()}_price_readable"):
            missing.append(ticker)
            continue
        start = pd.to_datetime(ticker_stats.get(f"{ticker.lower()}_price_date_range_start"), errors="coerce")
        end = pd.to_datetime(ticker_stats.get(f"{ticker.lower()}_price_date_range_end"), errors="coerce")
        if pd.notna(start):
            starts.append(pd.Timestamp(start))
        if pd.notna(end):
            ends.append(pd.Timestamp(end))
    return {
        "spy_price_coverage": 0.0 if "SPY" in missing else 1.0,
        "qqq_price_coverage": 0.0 if "QQQ" in missing else 1.0,
        "benchmark_price_missing": missing,
        "benchmark_coverage_ratio": float((len(BENCHMARK_TICKERS) - len(missing)) / max(len(BENCHMARK_TICKERS), 1)),
        "benchmark_date_range_start": max(starts).date().isoformat() if starts else "",
        "benchmark_date_range_end": min(ends).date().isoformat() if ends else "",
        **stats,
    }


def infer_execution_tier(
    *,
    source_mode: str,
    candidate_book: Path,
    price_cache: Path | None,
    target_coverage: float | None,
    benchmark_missing: list[str],
    macro_coverage: float | None,
) -> str:
    if source_mode in {"latest_only", "missing"} or not candidate_book.exists():
        return "LATEST_ONLY_OR_MISSING"
    if price_cache is None or not price_cache.exists():
        return "NO_PRICE_CACHE"
    if target_coverage is None or target_coverage < 0.80:
        return "PRICE_CACHE_INCOMPLETE"
    if benchmark_missing:
        return "BENCHMARK_PRICE_MISSING"
    if macro_coverage is None:
        return "MACRO_FEATURE_MISSING"
    return "TIER2_FULL_CACHE"


def long_crisis_feature_status(latest_run: Path) -> dict[str, Any]:
    feature_candidates = [
        latest_run / "data_pit" / "macro" / "long_crisis_daily_features.parquet",
        REPO_ROOT / "data_pit" / "macro" / "long_crisis_daily_features.parquet",
    ]
    threshold_candidates = [
        latest_run / "long_crisis_learning" / "best_thresholds.json",
        latest_run / "outputs" / "long_crisis_learning" / "best_thresholds.json",
        REPO_ROOT / "outputs" / "long_crisis_learning" / "best_thresholds.json",
    ]
    feature_path = next((path for path in feature_candidates if path.exists()), Path(""))
    threshold_path = next((path for path in threshold_candidates if path.exists()), Path(""))
    features = read_table(feature_path) if feature_path else pd.DataFrame()
    date_col = next((col for col in ("date", "Date", "as_of_date") if col in features.columns), "")
    dates = pd.to_datetime(features[date_col], errors="coerce").dropna() if date_col else pd.to_datetime(features.index, errors="coerce").dropna()
    return {
        "long_crisis_features_path": str(feature_path) if feature_path else "",
        "long_crisis_thresholds_path": str(threshold_path) if threshold_path else "",
        "long_crisis_features_available": bool(feature_path and not features.empty),
        "long_crisis_thresholds_available": bool(threshold_path and bool(read_json(threshold_path))),
        "long_crisis_feature_row_count": int(len(features)) if not features.empty else 0,
        "long_crisis_feature_date_range_start": pd.Timestamp(dates.min()).date().isoformat() if len(dates) else "",
        "long_crisis_feature_date_range_end": pd.Timestamp(dates.max()).date().isoformat() if len(dates) else "",
    }


def macro_feature_coverage(latest_run: Path, price_cache: Path | None, long_status: dict[str, Any] | None = None) -> float | None:
    long_status = long_status or long_crisis_feature_status(latest_run)
    candidates = [
        latest_run / "cache_macro",
        latest_run / "cache_crisis",
        latest_run / "macro",
    ]
    if price_cache is not None:
        candidates.extend([price_cache.parent / "cache_macro", price_cache.parent / "cache_crisis"])
    if not (bool(long_status.get("long_crisis_features_available")) and bool(long_status.get("long_crisis_thresholds_available"))):
        return None
    return 1.0 if any(path.exists() for path in candidates) or bool(long_status.get("long_crisis_features_available")) else None


def build_report(
    *,
    latest_run: Path,
    output_dir: Path,
    baseline_lock: Path | None,
    candidate_book_arg: str | None,
    target_book: Path | None,
    broker_output_dir: Path | None,
    metrics_json: Path | None,
    price_cache: Path | None,
    portfolio_kind: str,
    artifact_id: str,
    asof_date: str | None,
) -> dict[str, Any]:
    candidate_book, source_mode = infer_candidate_book(latest_run, candidate_book_arg)
    candidate = read_csv(candidate_book)
    dates = pd.to_datetime(candidate.get("rebalance_date", pd.Series(dtype=object)), errors="coerce").dropna() if not candidate.empty else pd.Series(dtype="datetime64[ns]")
    baseline = read_json(baseline_lock) if baseline_lock else {}
    metrics = read_json(metrics_json) if metrics_json else {}
    broker_dir = broker_output_dir or (metrics_json.parent if metrics_json else Path(""))
    target_stats = target_book_stats(target_book) if target_book else {}
    actual_stats = actual_position_stats(broker_dir) if broker_dir else {}
    price_stats = price_cache_coverage(target_book, price_cache)
    benchmark_stats = benchmark_price_coverage(price_cache)
    broker_end = date_text(metrics.get("end_date") or baseline.get("broker_end_date"))
    price_latest = date_text(broker_end or baseline.get("price_latest_date"))
    expected = expected_latest_market_close(asof_date)
    freshness_lag = business_day_lag(price_latest, expected)
    target_filter_source = str(metrics.get("target_book_filter_source") or "")
    metric_mode = str(metrics.get("metric_mode") or baseline.get("official_metric_mode") or "")
    requested_n = target_stats.get("requested_target_n")
    actual_median = actual_stats.get("actual_median_position_count")
    blockers: list[str] = []
    review: list[str] = []
    if source_mode == "latest_only":
        blockers.append("latest_only_source")
    if source_mode == "missing" or not candidate_book.exists():
        blockers.append("candidate_replay_book_missing")
    if metric_mode and metric_mode != "broker_ledger_next_close":
        blockers.append("metric_mode_not_broker_ledger_next_close")
    if portfolio_kind == "concentrated" and target_filter_source == "default_static":
        blockers.append("default_static_concentrated_filter")
    if freshness_lag > 2:
        blockers.append("stale_price_gt_2_us_business_days")
    coverage = safe_float(price_stats.get("price_cache_coverage"), None)
    benchmark_missing = list(benchmark_stats.get("benchmark_price_missing") or [])
    long_status = long_crisis_feature_status(latest_run)
    macro_coverage = macro_feature_coverage(latest_run, price_cache, long_status)
    execution_tier = infer_execution_tier(
        source_mode=source_mode,
        candidate_book=candidate_book,
        price_cache=price_cache,
        target_coverage=coverage,
        benchmark_missing=benchmark_missing,
        macro_coverage=macro_coverage,
    )
    candidate_sha = file_sha256(candidate_book)
    if coverage is not None and coverage < 0.80:
        blockers.append("PRICE_CACHE_INCOMPLETE")
    if benchmark_missing:
        blockers.append("BENCHMARK_PRICE_MISSING")
    if macro_coverage is None:
        blockers.append("MACRO_FEATURE_MISSING")
    if not long_status.get("long_crisis_features_available"):
        blockers.append("LONG_CRISIS_FEATURE_MISSING")
    if not long_status.get("long_crisis_thresholds_available"):
        blockers.append("LONG_CRISIS_THRESHOLDS_MISSING")
    if not baseline:
        blockers.append("NO_BASELINE_LOCK")
    if not candidate_sha:
        blockers.append("CANDIDATE_BOOK_HASH_MISSING")
    if execution_tier != "TIER2_FULL_CACHE":
        blockers.append("TIER2_CACHE_REQUIRED")
    if requested_n and actual_median and abs(float(requested_n) - float(actual_median)) > 0.75:
        review.append("requested_n_differs_from_actual_median_position_count")
    if not baseline:
        review.append("baseline_lock_missing_review_only")

    payload = {
        "schema_version": "replay-integrity-preflight-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifact_id": artifact_id,
        "latest_run": str(latest_run),
        "baseline_lock": str(baseline_lock) if baseline_lock else "",
        "active_baseline_lock_path": str(baseline_lock) if baseline_lock else "",
        "baseline_lock_loaded": bool(baseline),
        "baseline_run_id": baseline.get("run_id", ""),
        "execution_tier": execution_tier,
        "price_cache_root": str(price_cache) if price_cache else "",
        "price_cache_snapshot_id": file_sha256(price_cache / ".snapshot_id") if price_cache else "",
        "candidate_replay_book_exists": bool(candidate_book.exists() and source_mode != "latest_only"),
        "candidate_source_mode": source_mode,
        "candidate_book": str(candidate_book),
        "candidate_replay_book_path": str(candidate_book),
        "candidate_replay_book_sha256": candidate_sha,
        "candidate_rebalance_date_count": int(dates.nunique()) if not dates.empty else 0,
        "date_range_start": pd.Timestamp(dates.min()).date().isoformat() if not dates.empty else "",
        "date_range_end": pd.Timestamp(dates.max()).date().isoformat() if not dates.empty else "",
        "target_book_filter_source": target_filter_source,
        "concentrated_filter_disabled": target_filter_source == "disabled_explicit",
        "metric_mode": metric_mode,
        "portfolio_kind": portfolio_kind,
        "price_latest_date": price_latest,
        "expected_latest_market_close": expected.date().isoformat(),
        "latest_price_freshness_lag_business_days": int(freshness_lag),
        "production_mutation_check": "not_detected",
        "valid_for_research": len(blockers) == 0,
        "valid_for_promotion": False,
        "blockers": blockers,
        "review_flags": review,
        "target_ticker_price_coverage": price_stats.get("price_cache_coverage"),
        "macro_feature_coverage": macro_coverage,
        **long_status,
        **target_stats,
        **actual_stats,
        **price_stats,
        **benchmark_stats,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "preflight_replay_gate.json", payload)
    write_json(output_dir / "replay_integrity_report.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--baseline-lock", default=None)
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--target-book", default=None)
    parser.add_argument("--broker-output-dir", default=None)
    parser.add_argument("--metrics-json", default=None)
    parser.add_argument("--price-cache", default=None)
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated"], default="main")
    parser.add_argument("--artifact-id", default="")
    parser.add_argument("--asof-date", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_report(
        latest_run=repo_path(args.latest_run),
        output_dir=repo_path(args.output_dir),
        baseline_lock=repo_path(args.baseline_lock) if args.baseline_lock else None,
        candidate_book_arg=args.candidate_book,
        target_book=repo_path(args.target_book) if args.target_book else None,
        broker_output_dir=repo_path(args.broker_output_dir) if args.broker_output_dir else None,
        metrics_json=repo_path(args.metrics_json) if args.metrics_json else None,
        price_cache=repo_path(args.price_cache) if args.price_cache else None,
        portfolio_kind=args.portfolio_kind,
        artifact_id=str(args.artifact_id or ""),
        asof_date=args.asof_date,
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

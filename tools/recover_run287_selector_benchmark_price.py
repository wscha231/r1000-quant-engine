#!/usr/bin/env python3
"""Recover one missing current selector benchmark price series.

The bounded recovery is restricted to SOXX, uses an exact existing cache when
available, otherwise spends at most one Yahoo Finance batch request, and writes
only an isolated research artifact.  It never runs a score, selector, target
book, backtest, fullrun, production, or live-trading path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import r1000_pipeline as pipeline  # noqa: E402
from r1000_helpers import px_cache_name  # noqa: E402


SCHEMA_VERSION = "run287-selector-benchmark-price-recovery-v1"
ALLOWED_TICKER = "SOXX"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": bool(path.exists()),
        "bytes": int(path.stat().st_size) if path.exists() and path.is_file() else 0,
        "sha256": sha256(path) if path.exists() and path.is_file() else "",
    }


def expected_input(path: Path, expected: str, label: str) -> dict[str, Any]:
    audit = fingerprint(path)
    audit.update(
        {
            "label": label,
            "expected_sha256": expected,
            "hash_matches": bool(audit.get("sha256") == expected),
        }
    )
    return audit


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def normalize_price_frame(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    if output.empty:
        return output
    if not isinstance(output.index, pd.DatetimeIndex):
        date_column = next(
            (
                column
                for column in ("Date", "date", "Datetime", "datetime")
                if column in output.columns
            ),
            None,
        )
        if date_column is None:
            return pd.DataFrame()
        output = output.set_index(date_column)
    output.index = (
        pd.to_datetime(output.index, errors="coerce", utc=True)
        .tz_convert(None)
        .normalize()
    )
    output = output[output.index.notna()].sort_index()
    if isinstance(output.columns, pd.MultiIndex):
        output.columns = output.columns.get_level_values(0)
    aliases = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "adj_close": "Adj Close",
        "volume": "Volume",
    }
    for source, destination in aliases.items():
        if destination not in output.columns and source in output.columns:
            output[destination] = output[source]
    keep = [
        column
        for column in (
            "Open",
            "High",
            "Low",
            "Close",
            "Adj Close",
            "Volume",
            "Dividends",
            "Stock Splits",
        )
        if column in output.columns
    ]
    output = output[keep].copy()
    if "Close" not in output.columns and "Adj Close" not in output.columns:
        return pd.DataFrame()
    if "Dividends" not in output.columns:
        output["Dividends"] = 0.0
    if "Stock Splits" not in output.columns:
        output["Stock Splits"] = 0.0
    return output[~output.index.duplicated(keep="last")]


def frame_ready(
    frame: pd.DataFrame,
    *,
    valuation_date: str,
    minimum_rows: int,
) -> bool:
    return bool(
        not frame.empty
        and len(frame) >= int(minimum_rows)
        and pd.Timestamp(frame.index.max()).date().isoformat() == valuation_date
    )


def blocked(
    output_dir: Path,
    *,
    failures: list[str],
    input_audits: Mapping[str, Any],
    started: float,
    valuation_date: str,
    network_requests: int = 0,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED_SELECTOR_BENCHMARK_PRICE_RECOVERY",
        "price_recovery_passed": False,
        "contract_failures": failures,
        "blockers": failures,
        "ticker": ALLOWED_TICKER,
        "valuation_price_cutoff_date": valuation_date,
        "research_only": True,
        "current_decision_only": True,
        "score_sort_executed": False,
        "rank_assignment_executed": False,
        "top_n_executed": False,
        "selector_executed": False,
        "target_book_generation_allowed": False,
        "target_books_mutated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_request_budget": 1,
        "network_requests_executed": int(network_requests),
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "source_inputs": dict(input_audits),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def build(
    args: argparse.Namespace,
    *,
    downloader: Callable[..., Mapping[str, pd.DataFrame]] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ticker = str(args.ticker).upper().strip()
    crisis_manifest_path = repo_path(args.crisis_manifest)
    input_audits = {
        "crisis_manifest": expected_input(
            crisis_manifest_path,
            args.expected_crisis_sha256,
            "crisis_manifest",
        )
    }
    failures: list[str] = []
    if ticker != ALLOWED_TICKER:
        failures.append(f"ticker_not_allowed:{ticker}")
    if not input_audits["crisis_manifest"].get("hash_matches"):
        failures.append("crisis_manifest_hash_mismatch")
    if failures:
        return blocked(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=args.valuation_date,
        )
    crisis_manifest = json.loads(crisis_manifest_path.read_text(encoding="utf-8"))
    if crisis_manifest.get("status") != "READY_CURRENT_CRISIS_STATE_NONSELECTING":
        failures.append(f"crisis_status:{crisis_manifest.get('status')}")
    if crisis_manifest.get("valuation_price_cutoff_date") != args.valuation_date:
        failures.append("crisis_valuation_date_mismatch")

    source_cache = repo_path(args.source_cache)
    source_path = source_cache / px_cache_name(ticker)
    source_audit = fingerprint(source_path)
    source_audit["label"] = "existing_source_price"
    input_audits["existing_source_price"] = source_audit
    frame = pd.DataFrame()
    source_mode = ""
    if source_path.is_file():
        try:
            candidate = normalize_price_frame(pd.read_parquet(source_path))
            candidate = candidate[candidate.index <= pd.Timestamp(args.valuation_date)]
            if frame_ready(
                candidate,
                valuation_date=args.valuation_date,
                minimum_rows=args.minimum_rows,
            ):
                frame = candidate
                source_mode = "existing_exact_current_cache"
        except Exception as exc:
            source_audit["read_error"] = f"{type(exc).__name__}:{exc}"

    network_requests = 0
    if frame.empty:
        if not bool(args.allow_network):
            failures.append("network_required_but_not_allowed")
        else:
            fetch = downloader or pipeline.download_yf_price_batch
            fetched = fetch(
                [ticker],
                start=args.start_date,
                end=(
                    pd.Timestamp(args.valuation_date) + pd.Timedelta(days=1)
                ).date().isoformat(),
                interval="1d",
            )
            network_requests = 1
            frame = normalize_price_frame(fetched.get(ticker, pd.DataFrame()))
            frame = frame[frame.index <= pd.Timestamp(args.valuation_date)]
            source_mode = "bounded_yfinance_one_batch"
    if not frame_ready(
        frame,
        valuation_date=args.valuation_date,
        minimum_rows=args.minimum_rows,
    ):
        failures.append("benchmark_price_missing_stale_or_short")
    if network_requests > 1:
        failures.append("network_budget_exceeded")
    if failures:
        return blocked(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=args.valuation_date,
            network_requests=network_requests,
        )

    price_dir = output_dir / "cache_prices"
    price_dir.mkdir(parents=True, exist_ok=True)
    output_path = price_dir / px_cache_name(ticker)
    frame.to_parquet(output_path, index=True)
    audit_path = output_dir / "benchmark_price_audit.csv"
    audit_frame = pd.DataFrame(
        [
            {
                "ticker": ticker,
                "status": "ready",
                "source_mode": source_mode,
                "row_count": int(len(frame)),
                "date_min": pd.Timestamp(frame.index.min()).date().isoformat(),
                "date_max": pd.Timestamp(frame.index.max()).date().isoformat(),
                "network_requests_executed": network_requests,
                "output_path": str(output_path),
                "output_sha256": sha256(output_path),
            }
        ]
    )
    audit_frame.to_csv(audit_path, index=False)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_SELECTOR_BENCHMARK_PRICE_NONSELECTING",
        "price_recovery_passed": True,
        "contract_failures": [],
        "ticker": ticker,
        "valuation_price_cutoff_date": args.valuation_date,
        "source_mode": source_mode,
        "coverage": {
            "row_count": int(len(frame)),
            "date_min": pd.Timestamp(frame.index.min()).date().isoformat(),
            "date_max": pd.Timestamp(frame.index.max()).date().isoformat(),
            "minimum_rows": int(args.minimum_rows),
        },
        "research_only": True,
        "current_decision_only": True,
        "score_sort_executed": False,
        "rank_assignment_executed": False,
        "top_n_executed": False,
        "selector_executed": False,
        "target_book_generation_allowed": False,
        "target_books_mutated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_request_budget": 1,
        "network_requests_executed": network_requests,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "source_inputs": dict(input_audits),
        "outputs": {
            "price_file": fingerprint(output_path),
            "benchmark_price_audit": fingerprint(audit_path),
        },
        "recommended_next_step": "resolve and hash the 353 eligible equity price files plus SPY, QQQ, SMH, and SOXX into a read-only selector price map",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--crisis-manifest",
        default="outputs/run287_current_crisis_state_20260712_commit_466b9baf/manifest.json",
    )
    parser.add_argument(
        "--expected-crisis-sha256",
        default="6d7b0f053fdbfaa52e5c70708465029884a9a77e48a2df458258e03822893c0e",
    )
    parser.add_argument("--ticker", default=ALLOWED_TICKER)
    parser.add_argument(
        "--source-cache",
        default=r"G:\내 드라이브\r1000_top30_institutional\cache_prices",
    )
    parser.add_argument("--valuation-date", default="2026-07-10")
    parser.add_argument("--start-date", default="2023-07-01")
    parser.add_argument("--minimum-rows", type=int, default=252)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument(
        "--output-dir",
        default="outputs/run287_selector_benchmark_price_20260712",
    )
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "price_recovery_passed": payload.get("price_recovery_passed"),
                "ticker": payload.get("ticker"),
                "network_requests_executed": payload.get(
                    "network_requests_executed", 0
                ),
                "selector_executed": payload.get("selector_executed"),
            },
            sort_keys=True,
        )
    )
    return 0 if payload.get("price_recovery_passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())

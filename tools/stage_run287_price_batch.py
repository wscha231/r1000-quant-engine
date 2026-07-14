#!/usr/bin/env python3
"""Stage one Run287 price batch in an isolated append-only cache.

The first checkpoint lane intentionally supports exact, already-current source
files only. It verifies the pinned feature-frame gate, preflight queue, snapshot
price manifest, and every selected source parquet before copying. A batch that
contains a missing or stale price row fails closed; a later, separately tested
network lane must handle those rows.

This tool never writes to the source cache, downloads data, scores or ranks a
security, builds a target book, runs a backtest/fullrun, or changes trading
state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


SCHEMA_VERSION = "run287-isolated-price-batch-checkpoint-v1"
DEFAULT_PREFLIGHT = (
    "outputs/run287_decision_refresh_preflight_20260711_commit_62154c17/manifest.json"
)
DEFAULT_FEATURE_GATE = (
    "outputs/run287_feature_frame_pilot_20260711_commit_4bd556f8/manifest.json"
)
DEFAULT_OUTPUT = "outputs/run287_price_batch_B001_20260711"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "bytes": 0, "sha256": None}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "bytes": int(stat.st_size),
        "sha256": sha256_file(path),
        "modified_at_utc": datetime.fromtimestamp(
            stat.st_mtime, timezone.utc
        ).isoformat(),
    }


def read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return loaded


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def clean_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else pd.Timestamp(parsed).date().isoformat()


def record_path(record: Mapping[str, Any], manifest_path: Path) -> Path:
    raw = str(record.get("path") or "").strip()
    if not raw:
        return Path("")
    path = Path(raw)
    if path.is_absolute():
        return path
    return (manifest_path.parent / path).resolve()


def verify_record(
    record: Mapping[str, Any], manifest_path: Path, *, label: str
) -> tuple[Path, dict[str, Any]]:
    path = record_path(record, manifest_path)
    current = fingerprint(path)
    expected = str(record.get("sha256") or "").strip().lower()
    current_hash = str(current.get("sha256") or "").lower()
    current.update(
        {
            "label": label,
            "expected_sha256": expected or None,
            "hash_matches": bool(expected and expected == current_hash),
        }
    )
    return path, current


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return ""


def price_frame_audit(path: Path, valuation_date: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "readable": False,
        "row_count": 0,
        "first_price_date": "",
        "latest_price_date": "",
        "future_price_row_count": 0,
        "valuation_date_exact": False,
        "read_error": "",
    }
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        base["read_error"] = f"{type(exc).__name__}:{exc}"
        return base
    if frame.empty:
        base["read_error"] = "empty_price_frame"
        return base
    dates = pd.to_datetime(frame.index, errors="coerce", utc=True).tz_localize(None)
    valid = pd.Series(dates).dropna()
    if valid.empty:
        base["read_error"] = "no_valid_price_dates"
        return base
    cutoff = pd.Timestamp(valuation_date).normalize()
    latest = pd.Timestamp(valid.max()).normalize()
    first = pd.Timestamp(valid.min()).normalize()
    base.update(
        {
            "readable": True,
            "row_count": int(len(frame)),
            "first_price_date": first.date().isoformat(),
            "latest_price_date": latest.date().isoformat(),
            "future_price_row_count": int((valid > cutoff).sum()),
            "valuation_date_exact": latest == cutoff,
        }
    )
    return base


def blocked_payload(
    *,
    args: argparse.Namespace,
    failures: list[str],
    output_dir: Path,
    input_audits: Mapping[str, Any],
    started: float,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED_ISOLATED_PRICE_BATCH_CHECKPOINT",
        "batch_id": str(args.batch_id),
        "contract_failures": failures,
        "batch_checkpoint_ready": False,
        "batch_feature_compute_allowed": False,
        "next_batch_dispatch_allowed": False,
        "decision_ranking_allowed": False,
        "model_scoring_allowed": False,
        "target_book_generation_allowed": False,
        "network_requests_executed": 0,
        "source_inputs_mutated": False,
        "fullrun_executed": False,
        "backtest_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "source_inputs": dict(input_audits),
        "output_dir": str(output_dir),
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"append-only output already exists: {output_dir}")

    preflight_path = repo_path(args.preflight_manifest)
    feature_path = repo_path(args.feature_gate_manifest)
    preflight = read_json(preflight_path)
    feature = read_json(feature_path)
    input_audits: dict[str, Any] = {
        "preflight_manifest": fingerprint(preflight_path),
        "feature_gate_manifest": fingerprint(feature_path),
    }
    failures: list[str] = []

    feature_checks = {
        "ready_status": feature.get("status")
        == "PILOT_SCHEMA_READY_FULL_UNIVERSE_BLOCKED",
        "schema_ready": feature.get("schema_assembly_ready") is True,
        "bounded_refresh_allowed": feature.get("bounded_price_refresh_allowed") is True,
        "decision_ranking_disabled": feature.get("decision_ranking_allowed") is False,
        "model_scoring_disabled": feature.get("model_scoring_allowed") is False,
        "no_network": feature.get("network_requests_executed") == 0,
        "no_mutation": feature.get("source_inputs_mutated") is False,
        "no_fullrun": feature.get("fullrun_executed") is False,
    }
    failures.extend(
        f"feature_gate:{name}" for name, passed in feature_checks.items() if not passed
    )
    preflight_checks = {
        "expected_status": preflight.get("status") == "BLOCKED_BOUNDED_DECISION_REFRESH",
        "no_network": preflight.get("network_requests_executed") == 0,
        "no_mutation": preflight.get("source_inputs_mutated") is False,
        "no_fullrun": preflight.get("fullrun_executed") is False,
    }
    failures.extend(
        f"preflight:{name}" for name, passed in preflight_checks.items() if not passed
    )

    batch_record = (preflight.get("outputs") or {}).get("refresh_batches") or {}
    batch_path, batch_input = verify_record(
        batch_record, preflight_path, label="refresh_batches"
    )
    input_audits["refresh_batches"] = batch_input
    snapshot_record = (preflight.get("source_inputs") or {}).get("snapshot_manifest") or {}
    snapshot_path, snapshot_input = verify_record(
        snapshot_record, preflight_path, label="snapshot_manifest"
    )
    input_audits["snapshot_manifest"] = snapshot_input
    if not batch_input.get("hash_matches"):
        failures.append("input_hash_mismatch:refresh_batches")
    if not snapshot_input.get("hash_matches"):
        failures.append("input_hash_mismatch:snapshot_manifest")

    snapshot: dict[str, Any] = {}
    price_manifest_path = Path("")
    price_manifest_input: dict[str, Any] = {}
    source_root_manifest_path = Path("")
    source_root_manifest_input: dict[str, Any] = {}
    if not failures:
        snapshot = read_json(snapshot_path)
        price_record = (snapshot.get("outputs") or {}).get("price_file_manifest") or {}
        price_manifest_path, price_manifest_input = verify_record(
            price_record, snapshot_path, label="price_file_manifest"
        )
        root_record = (snapshot.get("source_inputs") or {}).get(
            "price_cache_manifest"
        ) or {}
        source_root_manifest_path, source_root_manifest_input = verify_record(
            root_record, snapshot_path, label="source_price_cache_manifest"
        )
        input_audits["price_file_manifest"] = price_manifest_input
        input_audits["source_price_cache_manifest"] = source_root_manifest_input
        if not price_manifest_input.get("hash_matches"):
            failures.append("input_hash_mismatch:price_file_manifest")
        if not source_root_manifest_input.get("hash_matches"):
            failures.append("input_hash_mismatch:source_price_cache_manifest")

    valuation_dates = {
        clean_date(preflight.get("decision_date")),
        clean_date(feature.get("valuation_price_cutoff_date")),
        clean_date(snapshot.get("valuation_close_date")) if snapshot else "",
    }
    if len(valuation_dates) != 1 or "" in valuation_dates:
        failures.append(f"valuation_date_mismatch:{sorted(valuation_dates)}")
    valuation_date = next(iter(valuation_dates)) if len(valuation_dates) == 1 else ""

    batch = pd.DataFrame()
    price_manifest = pd.DataFrame()
    if not failures:
        batch_all = pd.read_csv(batch_path, low_memory=False)
        batch = batch_all.loc[
            batch_all["batch_id"].astype(str) == str(args.batch_id)
        ].copy()
        if len(batch) != int(args.expected_batch_size):
            failures.append(
                f"batch_size:{len(batch)}!={int(args.expected_batch_size)}"
            )
        if batch.empty or batch["ticker"].astype(str).str.strip().duplicated().any():
            failures.append("batch_tickers_empty_or_duplicated")
        network_rows = batch.loc[batch["needs_price_refresh"].map(boolish)]
        if not network_rows.empty:
            failures.append(
                "network_refresh_rows_not_supported:"
                + ",".join(network_rows["ticker"].astype(str).tolist())
            )
        nonexact = batch.loc[~batch["price_date_exact"].map(boolish)]
        if not nonexact.empty:
            failures.append(
                "nonexact_source_rows:" + ",".join(nonexact["ticker"].astype(str))
            )
        price_manifest = pd.read_csv(price_manifest_path, low_memory=False)
        if price_manifest["ticker"].astype(str).str.upper().duplicated().any():
            failures.append("price_manifest_duplicate_tickers")

    selected = pd.DataFrame()
    if not failures:
        tickers = batch["ticker"].astype(str).str.upper().str.strip()
        selected = batch.assign(ticker=tickers).merge(
            price_manifest.assign(
                ticker=price_manifest["ticker"].astype(str).str.upper().str.strip()
            ),
            on="ticker",
            how="left",
            validate="one_to_one",
            suffixes=("_queue", "_snapshot"),
        )
        if selected["price_file"].isna().any():
            failures.append("batch_ticker_missing_from_price_manifest")

    source_before: dict[str, dict[str, Any]] = {}
    row_audits: list[dict[str, Any]] = []
    if not failures:
        for row in selected.to_dict(orient="records"):
            ticker = str(row["ticker"])
            source_path = Path(str(row.get("price_file") or ""))
            source_fp = fingerprint(source_path)
            source_before[ticker] = source_fp
            expected_hash = str(row.get("price_file_sha256") or "").lower()
            if not source_fp.get("exists"):
                failures.append(f"source_price_missing:{ticker}")
                continue
            if str(source_fp.get("sha256") or "").lower() != expected_hash:
                failures.append(f"source_price_hash_mismatch:{ticker}")
                continue
            audit = price_frame_audit(source_path, valuation_date)
            if not audit.get("readable"):
                failures.append(f"source_price_unreadable:{ticker}")
            if not audit.get("valuation_date_exact"):
                failures.append(f"source_price_not_exact:{ticker}")
            if int(audit.get("future_price_row_count") or 0) != 0:
                failures.append(f"source_price_future_rows:{ticker}")
            row_audits.append(
                {
                    "ticker": ticker,
                    "source_price_file": str(source_path),
                    "source_sha256_before": source_fp.get("sha256"),
                    **audit,
                }
            )

    if failures:
        output_dir.mkdir(parents=True, exist_ok=False)
        payload = blocked_payload(
            args=args,
            failures=failures,
            output_dir=output_dir,
            input_audits=input_audits,
            started=started,
        )
        write_json(output_dir / "manifest.json", payload)
        return payload

    cache_dir = output_dir / "cache_prices"
    cache_dir.mkdir(parents=True, exist_ok=False)
    for audit in row_audits:
        source_path = Path(audit["source_price_file"])
        destination = cache_dir / source_path.name
        shutil.copy2(source_path, destination)
        destination_fp = fingerprint(destination)
        audit.update(
            {
                "isolated_price_file": str(destination),
                "isolated_sha256": destination_fp.get("sha256"),
                "copy_hash_matches": destination_fp.get("sha256")
                == audit.get("source_sha256_before"),
            }
        )

    source_after = {
        ticker: fingerprint(Path(str(before.get("path") or "")))
        for ticker, before in source_before.items()
    }
    source_files_unchanged = all(
        source_before[ticker].get("sha256") == source_after[ticker].get("sha256")
        for ticker in source_before
    )
    root_after = fingerprint(source_root_manifest_path)
    root_manifest_unchanged = (
        source_root_manifest_input.get("sha256") == root_after.get("sha256")
    )
    copy_hashes_match = all(bool(row.get("copy_hash_matches")) for row in row_audits)

    audit_path = output_dir / "batch_ticker_audit.csv"
    pd.DataFrame(row_audits).sort_values("ticker").to_csv(audit_path, index=False)
    cache_manifest_path = output_dir / "batch_price_cache_manifest.json"
    cache_manifest = {
        "schema_version": SCHEMA_VERSION,
        "batch_id": str(args.batch_id),
        "valuation_close_date": valuation_date,
        "ticker_count": int(len(row_audits)),
        "tickers": sorted(row["ticker"] for row in row_audits),
        "files": {
            row["ticker"]: fingerprint(Path(row["isolated_price_file"]))
            for row in row_audits
        },
    }
    write_json(cache_manifest_path, cache_manifest)

    checkpoint_ready = bool(
        len(row_audits) == int(args.expected_batch_size)
        and copy_hashes_match
        and source_files_unchanged
        and root_manifest_unchanged
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "READY_ISOLATED_PRICE_BATCH_CHECKPOINT"
            if checkpoint_ready
            else "BLOCKED_ISOLATED_PRICE_BATCH_CHECKPOINT"
        ),
        "batch_id": str(args.batch_id),
        "valuation_close_date": valuation_date,
        "research_only": True,
        "copy_only": True,
        "batch_checkpoint_ready": checkpoint_ready,
        "batch_feature_compute_allowed": checkpoint_ready,
        "full_universe_decision_allowed": False,
        "next_batch_dispatch_allowed": False,
        "decision_ranking_allowed": False,
        "model_scoring_allowed": False,
        "target_book_generation_allowed": False,
        "network_refresh_supported": False,
        "network_requests_executed": 0,
        "source_inputs_mutated": not (
            source_files_unchanged and root_manifest_unchanged
        ),
        "target_books_mutated": False,
        "fullrun_executed": False,
        "selector_executed": False,
        "backtest_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "contract_failures": [] if checkpoint_ready else ["post_copy_checkpoint_failed"],
        "coverage": {
            "expected_batch_ticker_count": int(args.expected_batch_size),
            "batch_ticker_count": int(len(row_audits)),
            "exact_valuation_price_count": int(
                sum(bool(row.get("valuation_date_exact")) for row in row_audits)
            ),
            "future_price_row_count": int(
                sum(int(row.get("future_price_row_count") or 0) for row in row_audits)
            ),
            "copied_file_count": int(len(row_audits)),
            "network_refresh_row_count": 0,
            "new_full_universe_price_coverage_count": 0,
        },
        "source_immutability": {
            "selected_source_files_unchanged": source_files_unchanged,
            "source_root_manifest_unchanged": root_manifest_unchanged,
        },
        "recommended_next_step": (
            "implement and test the separately opt-in network lane for B002; "
            "B002 contains 29 exact-copy rows and 11 stale-price rows; do not dispatch it yet"
        ),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
        "source_inputs": {
            **input_audits,
            "selected_source_file_count": int(len(source_before)),
        },
        "outputs": {
            "batch_ticker_audit": {
                **fingerprint(audit_path),
                "row_count": int(len(row_audits)),
            },
            "batch_price_cache_manifest": fingerprint(cache_manifest_path),
            "isolated_cache_dir": str(cache_dir),
        },
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-manifest", default=DEFAULT_PREFLIGHT)
    parser.add_argument("--feature-gate-manifest", default=DEFAULT_FEATURE_GATE)
    parser.add_argument("--batch-id", default="B001")
    parser.add_argument("--expected-batch-size", type=int, default=40)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") in {
        "READY_ISOLATED_PRICE_BATCH_CHECKPOINT",
        "BLOCKED_ISOLATED_PRICE_BATCH_CHECKPOINT",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())

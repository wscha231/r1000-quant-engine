#!/usr/bin/env python3
"""Audit run287 runner/local price-cache and target-book parity.

This is a measurement-only R1 tool. It does not dispatch a workflow, download
new market data, regenerate target books, tune thresholds, or promote a policy.
It compares the run287 runner manifest and committed target books against a
local cache/book substrate and emits an explicit runner_parity_status.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


PORTFOLIOS = ("main", "concentrated")
DEFAULT_RUN_ROOT = "cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe"
DEFAULT_CANDIDATE_BOOK = DEFAULT_RUN_ROOT + "/reports/candidate_replay_book.csv"
DEFAULT_RUNNER_BOOK_ROOT = DEFAULT_RUN_ROOT + "/alphaops_vnext"
DEFAULT_MANIFEST = DEFAULT_RUNNER_BOOK_ROOT + "/target_generation_input_manifest.json"
DEFAULT_OUTPUT_DIR = "outputs/run287_parity"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def path_ref(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def required_tickers(candidate_book: Path, runner_book_root: Path) -> list[str]:
    tickers: set[str] = set()
    if candidate_book.exists():
        d = pd.read_csv(candidate_book, usecols=["ticker"])
        tickers.update(str(x).upper().strip() for x in d["ticker"].dropna().tolist())
    for portfolio in PORTFOLIOS:
        path = runner_book_root / f"official_{portfolio}_target_book.csv"
        if path.exists():
            d = pd.read_csv(path, usecols=["ticker"])
            tickers.update(str(x).upper().strip() for x in d["ticker"].dropna().tolist())
    return sorted(t for t in tickers if t and t != "CASH")


def price_file_bounds(path: Path) -> tuple[str, str, int]:
    if not path.exists():
        return "", "", 0
    try:
        d = pd.read_parquet(path)
    except Exception:
        return "", "", 0
    if d.empty:
        return "", "", 0
    idx = pd.to_datetime(d.index, errors="coerce")
    idx = idx[idx.notna()]
    if len(idx) == 0:
        return "", "", 0
    return pd.Timestamp(idx.min()).date().isoformat(), pd.Timestamp(idx.max()).date().isoformat(), int(len(idx))


def audit_cache(candidate_book: Path, runner_book_root: Path, local_price_cache: Path, manifest: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame]:
    tickers = required_tickers(candidate_book, runner_book_root)
    rows: list[dict[str, Any]] = []
    local_cache_exists = local_price_cache.exists()
    for ticker in tickers:
        file_name = px_cache_name(ticker)
        path = local_price_cache / file_name
        first_date, last_date, row_count = price_file_bounds(path)
        missing_file = not path.exists()
        rows.append(
            {
                "ticker": ticker,
                "expected_cache_file": file_name,
                "local_file_exists": bool(path.exists()),
                "local_first_bar_date": first_date,
                "local_last_bar_date": last_date,
                "local_bar_count": row_count,
                "missing_reason": "local_cache_missing" if not local_cache_exists else ("missing_price_file" if missing_file else ""),
            }
        )
    missing = [row for row in rows if not row["local_file_exists"]]
    local_manifest = read_json(local_price_cache / "replay_price_cache_manifest.json")
    runner_manifest_price = manifest.get("price_cache") if isinstance(manifest.get("price_cache"), dict) else {}
    summary = {
        "runner_required_ticker_count": int(runner_manifest_price.get("required_ticker_count") or len(tickers)),
        "runner_required_price_file_count": int(runner_manifest_price.get("required_price_file_count") or len(tickers)),
        "runner_existing_price_file_count": int(runner_manifest_price.get("existing_price_file_count") or 0),
        "runner_missing_price_file_count": int(runner_manifest_price.get("missing_price_file_count") or 0),
        "runner_price_cache_manifest_sha256": (runner_manifest_price.get("manifest") or {}).get("sha256", ""),
        "local_price_cache": str(local_price_cache),
        "local_price_cache_exists": local_cache_exists,
        "local_manifest_exists": (local_price_cache / "replay_price_cache_manifest.json").exists(),
        "local_manifest_status": local_manifest.get("status", ""),
        "local_manifest_ticker_count": int(local_manifest.get("ticker_count") or local_manifest.get("actual_cached_ticker_count") or 0),
        "local_required_ticker_count_from_candidate_and_books": len(tickers),
        "local_missing_price_file_count": len(missing),
        "local_present_price_file_count": len(rows) - len(missing),
    }
    return summary, pd.DataFrame(rows)


def normalize_book(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["rebalance_date", "ticker", "target_weight"])
    d = pd.read_csv(path, usecols=lambda c: c in {"rebalance_date", "ticker", "target_weight", "weight"})
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    weight_col = "target_weight" if "target_weight" in d.columns else "weight"
    d["target_weight"] = pd.to_numeric(d[weight_col], errors="coerce").fillna(0.0)
    d = d.dropna(subset=["rebalance_date"])
    d = d[d["ticker"].ne("")]
    return (
        d.groupby(["rebalance_date", "ticker"], as_index=False)["target_weight"]
        .sum()
        .sort_values(["rebalance_date", "ticker"])
        .reset_index(drop=True)
    )


def local_book_path(local_book_root: Path, portfolio: str) -> Path:
    candidates = [
        local_book_root / f"official_{portfolio}_target_book.csv",
        local_book_root / "alphaops_vnext" / f"official_{portfolio}_target_book.csv",
        local_book_root / "outputs" / "alphaops_vnext" / f"official_{portfolio}_target_book.csv",
    ]
    return next((path for path in candidates if path.exists()), candidates[0])


def compare_book_pair(runner: pd.DataFrame, local: pd.DataFrame, portfolio: str) -> dict[str, Any]:
    if runner.empty or local.empty:
        return {
            "portfolio": portfolio,
            "status": "blocked_missing_book",
            "runner_rows": int(len(runner)),
            "local_rows": int(len(local)),
            "common_date_count": 0,
            "runner_only_date_count": 0,
            "local_only_date_count": 0,
            "ticker_mismatch_date_count": 0,
            "max_weight_delta_abs": 0.0,
        }
    runner_dates = set(pd.to_datetime(runner["rebalance_date"]).dt.normalize())
    local_dates = set(pd.to_datetime(local["rebalance_date"]).dt.normalize())
    common_dates = sorted(runner_dates & local_dates)
    ticker_mismatch_dates = 0
    max_delta = 0.0
    l1_values: list[float] = []
    for date in common_dates:
        r = runner[pd.to_datetime(runner["rebalance_date"]).dt.normalize().eq(date)].set_index("ticker")["target_weight"]
        l = local[pd.to_datetime(local["rebalance_date"]).dt.normalize().eq(date)].set_index("ticker")["target_weight"]
        tickers = sorted(set(r.index) | set(l.index))
        r2 = r.reindex(tickers).fillna(0.0)
        l2 = l.reindex(tickers).fillna(0.0)
        if set(r.index) != set(l.index):
            ticker_mismatch_dates += 1
        delta = (r2 - l2).abs()
        max_delta = max(max_delta, safe_float(delta.max()))
        l1_values.append(safe_float(delta.sum()))
    exact = (
        len(runner_dates - local_dates) == 0
        and len(local_dates - runner_dates) == 0
        and ticker_mismatch_dates == 0
        and max_delta <= 1e-9
    )
    return {
        "portfolio": portfolio,
        "status": "parity_exact" if exact else "parity_gap",
        "runner_rows": int(len(runner)),
        "local_rows": int(len(local)),
        "common_date_count": len(common_dates),
        "runner_only_date_count": len(runner_dates - local_dates),
        "local_only_date_count": len(local_dates - runner_dates),
        "ticker_mismatch_date_count": ticker_mismatch_dates,
        "max_weight_delta_abs": max_delta,
        "average_l1_weight_diff": safe_float(pd.Series(l1_values).mean()) if l1_values else 0.0,
        "max_l1_weight_diff": safe_float(pd.Series(l1_values).max()) if l1_values else 0.0,
    }


def audit_books(runner_book_root: Path, local_book_root: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    for portfolio in PORTFOLIOS:
        runner = normalize_book(runner_book_root / f"official_{portfolio}_target_book.csv")
        local = normalize_book(local_book_path(local_book_root, portfolio))
        rows.append(compare_book_pair(runner, local, portfolio))
    frame = pd.DataFrame(rows)
    exact = bool((frame["status"] == "parity_exact").all()) if not frame.empty else False
    blocked = bool((frame["status"] == "blocked_missing_book").any()) if not frame.empty else True
    return {"book_parity_exact": exact, "book_parity_blocked": blocked, "portfolios": rows}, frame


def render_report(payload: dict[str, Any]) -> str:
    cache = payload["cache_audit"]
    lines = [
        "# Run287 Runner Parity Cache Audit",
        "",
        "Status: `completed`",
        "",
        "Research-only R1 audit. No fullrun was dispatched, no market data was downloaded,",
        "and no target book was regenerated.",
        "",
        "## Verdict",
        "",
        f"- runner_parity_status: `{payload['runner_parity_status']}`",
        f"- reason: `{payload['runner_parity_reason']}`",
        "",
        "## Price Cache",
        "",
        f"- runner_required_ticker_count: `{cache['runner_required_ticker_count']}`",
        f"- runner_existing_price_file_count: `{cache['runner_existing_price_file_count']}`",
        f"- local_manifest_ticker_count: `{cache['local_manifest_ticker_count']}`",
        f"- local_present_price_file_count: `{cache['local_present_price_file_count']}`",
        f"- local_missing_price_file_count: `{cache['local_missing_price_file_count']}`",
        "",
        "## Book Parity",
        "",
        "| Portfolio | Status | Common dates | Ticker mismatch dates | Max weight delta | Avg L1 diff |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in payload["book_audit"]["portfolios"]:
        lines.append(
            "| {portfolio} | {status} | {common} | {mismatch} | {max_delta:.3g} | {avg_l1:.4f} |".format(
                portfolio=row["portfolio"],
                status=row["status"],
                common=int(row["common_date_count"]),
                mismatch=int(row["ticker_mismatch_date_count"]),
                max_delta=safe_float(row["max_weight_delta_abs"]),
                avg_l1=safe_float(row["average_l1_weight_diff"]),
            )
        )
    lines.extend(
        [
            "",
            "Anti-leakage: missing cache entries are listed explicitly in `missing_bars.csv`.",
            "No ticker was dropped to force a parity match.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = repo_path(args.runner_manifest)
    candidate_book = repo_path(args.candidate_book)
    runner_book_root = repo_path(args.runner_book_root)
    local_price_cache = repo_path(args.local_price_cache)
    local_book_root = repo_path(args.local_book_root)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_json(manifest_path)
    cache_summary, missing_bars = audit_cache(candidate_book, runner_book_root, local_price_cache, manifest)
    cache_summary["local_price_cache"] = path_ref(local_price_cache)
    book_summary, book_frame = audit_books(runner_book_root, local_book_root)
    if not cache_summary["local_price_cache_exists"] or book_summary["book_parity_blocked"]:
        status = "blocked"
        reason = "local_cache_or_book_missing"
    elif cache_summary["local_missing_price_file_count"] == 0 and book_summary["book_parity_exact"]:
        status = "parity_exact"
        reason = "cache_and_book_match_runner_manifest"
    else:
        status = "parity_documented_gap"
        reason = "local_cache_or_book_differs_from_runner_manifest"

    missing_bars.to_csv(output_dir / "missing_bars.csv", index=False)
    book_frame.to_csv(output_dir / "book_parity.csv", index=False)
    payload = {
        "schema_version": "run287-runner-parity-v1",
        "status": "completed",
        "runner_parity_status": status,
        "runner_parity_reason": reason,
        "research_only": True,
        "fullrun_dispatched": False,
        "market_data_downloaded": False,
        "target_book_regenerated": False,
        "threshold_tuning_performed": False,
        "runner_manifest": path_ref(manifest_path),
        "candidate_book": path_ref(candidate_book),
        "runner_book_root": path_ref(runner_book_root),
        "local_price_cache": path_ref(local_price_cache),
        "local_book_root": path_ref(local_book_root),
        "cache_audit": cache_summary,
        "book_audit": book_summary,
        "artifacts": {
            "summary": path_ref(output_dir / "summary.json"),
            "report": path_ref(output_dir / "report.md"),
            "missing_bars": path_ref(output_dir / "missing_bars.csv"),
            "book_parity": path_ref(output_dir / "book_parity.csv"),
        },
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--runner-book-root", default=DEFAULT_RUNNER_BOOK_ROOT)
    parser.add_argument("--local-price-cache", default="outputs/run287_price_cache_latest/cache_prices")
    parser.add_argument("--local-book-root", default="outputs/run287_w1_determinism_exact/repro_a")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps({"status": payload["status"], "runner_parity_status": payload["runner_parity_status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

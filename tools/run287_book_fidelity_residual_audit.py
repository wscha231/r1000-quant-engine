#!/usr/bin/env python3
"""Audit the residual run287 runner-fidelity gap after cache coverage is complete.

This is a research-only Phase 0/R1 diagnostic. It does not dispatch a fullrun,
download market data, regenerate target books, tune thresholds, or promote a
policy. It compares the official runner manifest/books with a local regenerated
book substrate and classifies what still prevents runner fidelity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


PORTFOLIOS = ("main", "concentrated")
DEFAULT_RUN_ROOT = "cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe"
DEFAULT_RUNNER_BOOK_ROOT = DEFAULT_RUN_ROOT + "/alphaops_vnext"
DEFAULT_RUNNER_MANIFEST = DEFAULT_RUNNER_BOOK_ROOT + "/target_generation_input_manifest.json"
DEFAULT_LOCAL_BOOK_ROOT = "outputs/run287_w1_full_candidate_cache_repro"
DEFAULT_LOCAL_MANIFEST = DEFAULT_LOCAL_BOOK_ROOT + "/target_generation_input_manifest.json"
DEFAULT_PARITY_SUMMARY = "outputs/run287_parity/summary.json"
DEFAULT_OUTPUT_DIR = "outputs/run287_book_fidelity_residual"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def path_ref(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get_nested(payload: dict[str, Any], dotted: str) -> Any:
    cur: Any = payload
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


def manifest_rows(runner: dict[str, Any], local: dict[str, Any]) -> pd.DataFrame:
    paths = [
        "schema_version",
        "code.github_ref",
        "code.github_sha",
        "candidate_book.sha256",
        "candidate_row_count",
        "candidate_rebalance_date_min",
        "candidate_rebalance_date_max",
        "price_cache.required_ticker_count",
        "price_cache.existing_price_file_count",
        "price_cache.missing_price_file_count",
        "price_cache.manifest.sha256",
        "macro_crisis_inputs.long_crisis_features.sha256",
        "macro_crisis_inputs.long_crisis_thresholds.sha256",
        "operating_append_end_date",
    ]
    env_keys = sorted(set((runner.get("env") or {}).keys()) | set((local.get("env") or {}).keys()))
    rows: list[dict[str, Any]] = []
    for path in paths:
        r = normalize_value(get_nested(runner, path))
        l = normalize_value(get_nested(local, path))
        rows.append(
            {
                "field": path,
                "runner_value": r,
                "local_value": l,
                "matches": bool(r == l),
                "diff_class": "match" if r == l else "mismatch",
            }
        )
    for key in env_keys:
        r = normalize_value((runner.get("env") or {}).get(key))
        l = normalize_value((local.get("env") or {}).get(key))
        if r == l:
            diff_class = "match"
        elif not r or not l:
            diff_class = "missing_or_blank_env"
        else:
            diff_class = "env_mismatch"
        rows.append(
            {
                "field": f"env.{key}",
                "runner_value": r,
                "local_value": l,
                "matches": bool(r == l),
                "diff_class": diff_class,
            }
        )
    return pd.DataFrame(rows)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def normalize_book(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["rebalance_date", "ticker", "target_weight"])
    d = pd.read_csv(path, usecols=lambda c: c in {"rebalance_date", "ticker", "target_weight", "weight"})
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    weight_col = "target_weight" if "target_weight" in d.columns else "weight"
    d["target_weight"] = pd.to_numeric(d[weight_col], errors="coerce").fillna(0.0)
    d = d.dropna(subset=["rebalance_date"])
    d = d[d["ticker"].ne("") & d["ticker"].ne("NAN")]
    return (
        d.groupby(["rebalance_date", "ticker"], as_index=False)["target_weight"]
        .sum()
        .sort_values(["rebalance_date", "ticker"])
        .reset_index(drop=True)
    )


def book_path(root: Path, portfolio: str) -> Path:
    candidates = [
        root / f"official_{portfolio}_target_book.csv",
        root / "alphaops_vnext" / f"official_{portfolio}_target_book.csv",
        root / "outputs" / "alphaops_vnext" / f"official_{portfolio}_target_book.csv",
    ]
    return next((path for path in candidates if path.exists()), candidates[0])


def compare_books(runner_book: Path, local_book: Path, portfolio: str) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    runner = normalize_book(runner_book)
    local = normalize_book(local_book)
    if runner.empty or local.empty:
        summary = {
            "portfolio": portfolio,
            "status": "blocked_missing_book",
            "runner_book": path_ref(runner_book),
            "local_book": path_ref(local_book),
            "runner_book_sha256": sha256_file(runner_book),
            "local_book_sha256": sha256_file(local_book),
            "runner_rows": int(len(runner)),
            "local_rows": int(len(local)),
            "common_date_count": 0,
            "ticker_mismatch_date_count": 0,
            "max_weight_delta_abs": 0.0,
            "average_l1_weight_diff": 0.0,
            "max_l1_weight_diff": 0.0,
        }
        return summary, pd.DataFrame(), pd.DataFrame()

    merged = runner.merge(local, on=["rebalance_date", "ticker"], how="outer", suffixes=("_runner", "_local"))
    merged["target_weight_runner"] = pd.to_numeric(merged["target_weight_runner"], errors="coerce").fillna(0.0)
    merged["target_weight_local"] = pd.to_numeric(merged["target_weight_local"], errors="coerce").fillna(0.0)
    merged["weight_delta"] = merged["target_weight_local"] - merged["target_weight_runner"]
    merged["abs_weight_delta"] = merged["weight_delta"].abs()
    merged["in_runner"] = merged["target_weight_runner"].ne(0.0)
    merged["in_local"] = merged["target_weight_local"].ne(0.0)

    date_rows: list[dict[str, Any]] = []
    for dt, day in merged.groupby("rebalance_date", dropna=False):
        runner_tickers = set(day.loc[day["in_runner"], "ticker"])
        local_tickers = set(day.loc[day["in_local"], "ticker"])
        l1 = safe_float(day["abs_weight_delta"].sum())
        date_rows.append(
            {
                "portfolio": portfolio,
                "rebalance_date": dt,
                "runner_ticker_count": len(runner_tickers),
                "local_ticker_count": len(local_tickers),
                "ticker_set_equal": bool(runner_tickers == local_tickers),
                "ticker_overlap": len(runner_tickers & local_tickers),
                "runner_only_tickers": ",".join(sorted(runner_tickers - local_tickers)),
                "local_only_tickers": ",".join(sorted(local_tickers - runner_tickers)),
                "l1_weight_diff": l1,
                "max_weight_delta_abs": safe_float(day["abs_weight_delta"].max()),
            }
        )
    by_date = pd.DataFrame(date_rows).sort_values(["portfolio", "l1_weight_diff"], ascending=[True, False])
    by_ticker = (
        merged.groupby("ticker", as_index=False)
        .agg(
            abs_weight_delta=("abs_weight_delta", "sum"),
            net_weight_delta=("weight_delta", "sum"),
            changed_dates=("rebalance_date", "nunique"),
        )
        .sort_values("abs_weight_delta", ascending=False)
    )
    exact = bool((not by_date.empty) and by_date["ticker_set_equal"].all() and safe_float(merged["abs_weight_delta"].max()) <= 1e-9)
    summary = {
        "portfolio": portfolio,
        "status": "parity_exact" if exact else "parity_gap",
        "runner_book": path_ref(runner_book),
        "local_book": path_ref(local_book),
        "runner_book_sha256": sha256_file(runner_book),
        "local_book_sha256": sha256_file(local_book),
        "runner_rows": int(len(runner)),
        "local_rows": int(len(local)),
        "common_date_count": int(len(set(runner["rebalance_date"]) & set(local["rebalance_date"]))),
        "ticker_mismatch_date_count": int((~by_date["ticker_set_equal"]).sum()) if not by_date.empty else 0,
        "max_weight_delta_abs": safe_float(merged["abs_weight_delta"].max()),
        "average_l1_weight_diff": safe_float(by_date["l1_weight_diff"].mean()) if not by_date.empty else 0.0,
        "max_l1_weight_diff": safe_float(by_date["l1_weight_diff"].max()) if not by_date.empty else 0.0,
    }
    return summary, by_date, by_ticker


def classify_sources(manifest_diff: pd.DataFrame, parity: dict[str, Any], book_summaries: list[dict[str, Any]]) -> list[str]:
    sources: list[str] = []
    by_field = {str(row["field"]): row for _, row in manifest_diff.iterrows()}
    if not bool(parity.get("cache_audit", {}).get("cache_coverage_complete")):
        sources.append("cache_coverage_gap")
    if not bool(parity.get("cache_audit", {}).get("cache_manifest_sha_matches_runner")):
        sources.append("price_cache_manifest_sha_mismatch")
    code_row = by_field.get("code.github_sha")
    if code_row is not None and not bool(code_row.get("matches")):
        sources.append("code_provenance_missing_or_mismatch")
    candidate_row = by_field.get("candidate_book.sha256")
    if candidate_row is not None and not bool(candidate_row.get("matches")):
        sources.append("candidate_book_sha_mismatch")
    macro_fields = [
        "macro_crisis_inputs.long_crisis_features.sha256",
        "macro_crisis_inputs.long_crisis_thresholds.sha256",
    ]
    if any(field in by_field and not bool(by_field[field].get("matches")) for field in macro_fields):
        sources.append("macro_input_sha_mismatch")
    append_row = by_field.get("operating_append_end_date")
    if append_row is not None and not bool(append_row.get("matches")):
        sources.append("operating_append_end_date_mismatch")
    env_mismatches = manifest_diff[manifest_diff["field"].astype(str).str.startswith("env.") & ~manifest_diff["matches"].astype(bool)]
    if not env_mismatches.empty:
        sources.append("env_mismatch_or_blank")
    if any(row.get("status") != "parity_exact" for row in book_summaries):
        sources.append("book_generation_gap")
    return sources or ["none"]


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Run287 Book Fidelity Residual Audit",
        "",
        "Status: `completed`",
        "",
        "Research-only R1 diagnostic. No fullrun was dispatched, no market data was",
        "downloaded, no target book was regenerated, and no threshold was tuned.",
        "",
        "## Verdict",
        "",
        f"- runner_parity_status: `{payload['runner_parity_status']}`",
        f"- runner_fidelity_status: `{payload['runner_fidelity_status']}`",
        f"- residual_gap_classification: `{payload['residual_gap_classification']}`",
        f"- residual_source_candidates: `{','.join(payload['residual_source_candidates'])}`",
        "",
        "## Manifest",
        "",
        f"- manifest_mismatch_count: `{payload['manifest_mismatch_count']}`",
        f"- env_mismatch_count: `{payload['env_mismatch_count']}`",
        "",
        "## Books",
        "",
        "| Portfolio | Status | Ticker mismatch dates | Max weight delta | Avg L1 diff | Max L1 diff |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in payload["book_audit"]["portfolios"]:
        lines.append(
            "| {portfolio} | {status} | {mismatch} | {max_delta:.6g} | {avg_l1:.6g} | {max_l1:.6g} |".format(
                portfolio=row["portfolio"],
                status=row["status"],
                mismatch=int(row["ticker_mismatch_date_count"]),
                max_delta=safe_float(row["max_weight_delta_abs"]),
                avg_l1=safe_float(row["average_l1_weight_diff"]),
                max_l1=safe_float(row["max_l1_weight_diff"]),
            )
        )
    lines.extend(
        [
            "",
            "Interpretation:",
            "",
            "- Cache coverage can be complete while runner fidelity is still not exact.",
            "- Treat this as residual provenance/book-generation evidence, not a strategy pass.",
            "- Regeneration-based attribution remains blocked until this residual is resolved",
            "  or explicitly carried as a caveat.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    runner_book_root = repo_path(args.runner_book_root)
    local_book_root = repo_path(args.local_book_root)
    runner_manifest_path = repo_path(args.runner_manifest)
    local_manifest_path = repo_path(args.local_manifest)
    parity_summary_path = repo_path(args.parity_summary)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    runner_manifest = read_json(runner_manifest_path)
    local_manifest = read_json(local_manifest_path)
    parity = read_json(parity_summary_path)
    manifest_diff = manifest_rows(runner_manifest, local_manifest)
    manifest_diff.to_csv(output_dir / "manifest_diff.csv", index=False)

    book_summaries: list[dict[str, Any]] = []
    date_frames: list[pd.DataFrame] = []
    ticker_frames: list[pd.DataFrame] = []
    for portfolio in PORTFOLIOS:
        summary, by_date, by_ticker = compare_books(
            runner_book_root / f"official_{portfolio}_target_book.csv",
            book_path(local_book_root, portfolio),
            portfolio,
        )
        book_summaries.append(summary)
        if not by_date.empty:
            date_frames.append(by_date)
        if not by_ticker.empty:
            by_ticker.insert(0, "portfolio", portfolio)
            ticker_frames.append(by_ticker)
    book_gap_by_date = pd.concat(date_frames, ignore_index=True) if date_frames else pd.DataFrame()
    ticker_gap = pd.concat(ticker_frames, ignore_index=True) if ticker_frames else pd.DataFrame()
    book_gap_by_date.to_csv(output_dir / "book_gap_by_date.csv", index=False)
    ticker_gap.to_csv(output_dir / "ticker_gap.csv", index=False)

    residual_sources = classify_sources(manifest_diff, parity, book_summaries)
    exact = all(row.get("status") == "parity_exact" for row in book_summaries)
    cache_complete = bool(parity.get("cache_audit", {}).get("cache_coverage_complete"))
    payload = {
        "schema_version": "run287-book-fidelity-residual-v1",
        "status": "completed",
        "research_only": True,
        "fullrun_dispatched": False,
        "market_data_downloaded": False,
        "target_book_regenerated": False,
        "threshold_tuning_performed": False,
        "production_promotion_allowed": False,
        "runner_parity_status": "parity_exact" if exact and cache_complete else "parity_documented_gap",
        "runner_fidelity_status": "established" if exact and cache_complete else "residual_documented",
        "residual_gap_classification": "none" if exact and cache_complete else "book_generation_gap",
        "residual_source_candidates": residual_sources,
        "runner_manifest": path_ref(runner_manifest_path),
        "local_manifest": path_ref(local_manifest_path),
        "parity_summary": path_ref(parity_summary_path),
        "runner_book_root": path_ref(runner_book_root),
        "local_book_root": path_ref(local_book_root),
        "cache_coverage_status": parity.get("cache_audit", {}).get("cache_coverage_status", ""),
        "cache_manifest_sha_matches_runner": bool(parity.get("cache_audit", {}).get("cache_manifest_sha_matches_runner")),
        "manifest_mismatch_count": int((~manifest_diff["matches"].astype(bool)).sum()) if not manifest_diff.empty else 0,
        "env_mismatch_count": int(
            ((manifest_diff["field"].astype(str).str.startswith("env.")) & (~manifest_diff["matches"].astype(bool))).sum()
        )
        if not manifest_diff.empty
        else 0,
        "book_audit": {
            "book_parity_exact": bool(exact),
            "portfolios": book_summaries,
        },
        "artifacts": {
            "summary": path_ref(output_dir / "summary.json"),
            "report": path_ref(output_dir / "report.md"),
            "manifest_diff": path_ref(output_dir / "manifest_diff.csv"),
            "book_gap_by_date": path_ref(output_dir / "book_gap_by_date.csv"),
            "ticker_gap": path_ref(output_dir / "ticker_gap.csv"),
        },
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-book-root", default=DEFAULT_RUNNER_BOOK_ROOT)
    parser.add_argument("--local-book-root", default=DEFAULT_LOCAL_BOOK_ROOT)
    parser.add_argument("--runner-manifest", default=DEFAULT_RUNNER_MANIFEST)
    parser.add_argument("--local-manifest", default=DEFAULT_LOCAL_MANIFEST)
    parser.add_argument("--parity-summary", default=DEFAULT_PARITY_SUMMARY)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(
        json.dumps(
            {
                "status": payload["status"],
                "runner_fidelity_status": payload["runner_fidelity_status"],
                "residual_source_candidates": payload["residual_source_candidates"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

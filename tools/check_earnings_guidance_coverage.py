#!/usr/bin/env python3
"""Check readiness tiers for PIT earnings revision / guidance coverage.

The tiers intentionally separate plumbing from research, service, and policy
readiness. A tiny file can prove that the pipeline works, but it must not make
the market-state dial or policy hooks believe forward earnings coverage exists.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

COVERAGE_ELIGIBLE_SOURCE_TYPES = {
    "historical_revision",
    "vendor_estimate_revision",
    "company_guidance",
    "manual_research_import",
}
NON_COVERAGE_SOURCE_TYPES = {
    "sec_actual_snapshot",
    "current_snapshot",
    "internal_proxy_score",
    "actual_results_score",
    "eps_revision_score_proxy",
    "earnings_call_keyword",
}
REVISION_COLUMNS = ["eps_revision_4w", "eps_revision_13w", "eps_revision_26w", "revenue_revision_13w", "margin_revision_score"]
ESTIMATE_OBSERVATION_COLUMNS = ["eps_estimate", "revenue_estimate", "margin_estimate", "old_estimate", "new_estimate", "guidance_mid"]
GUIDANCE_COLUMNS = ["positive_guidance_flag", "negative_guidance_flag", "guidance_vs_consensus_score"]
WEIGHT_COLUMNS = ["weight", "target_weight", "current_weight", "portfolio_weight", "canonical_target_weight"]
BUCKET_COLUMNS = ["ai_capex_value_chain_bucket", "ai_bucket", "bucket", "theme_bucket"]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def _source_eligible_mask(frame: pd.DataFrame) -> pd.Series:
    if "is_coverage_eligible" in frame.columns:
        return frame["is_coverage_eligible"].astype(str).str.lower().isin({"1", "true", "yes"})
    if "source_type_coverage_eligible" in frame.columns:
        return frame["source_type_coverage_eligible"].astype(str).str.lower().isin({"1", "true", "yes"})
    if "source_type" in frame.columns:
        return frame["source_type"].astype(str).str.lower().str.strip().isin(COVERAGE_ELIGIBLE_SOURCE_TYPES)
    return pd.Series(False, index=frame.index)


def _normalize_frame(frame: pd.DataFrame, as_of: pd.Timestamp | None) -> tuple[pd.DataFrame, dict[str, int]]:
    if frame.empty:
        d = frame.copy()
        d["ticker"] = pd.Series(dtype=str)
        d["available_from"] = pd.Series(dtype="datetime64[ns]")
        d["source_type"] = pd.Series(dtype=str)
        d["is_coverage_eligible"] = pd.Series(dtype=bool)
        return d, {"input_rows": 0, "invalid_available_from_rows": 0, "future_available_from_rows": 0}
    d = frame.copy()
    if "ticker" in d.columns:
        d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    else:
        d["ticker"] = ""
    if "available_from" in d.columns:
        d["available_from"] = pd.to_datetime(d["available_from"], errors="coerce").dt.normalize()
    else:
        d["available_from"] = pd.NaT
    invalid_available_from = int(d["available_from"].isna().sum())
    future_available_from = int((d["available_from"] > as_of).sum()) if as_of is not None else 0
    d = d[d["ticker"].ne("") & d["available_from"].notna()].copy()
    if as_of is not None:
        d = d[d["available_from"] <= as_of].copy()
    d["source_type"] = d.get("source_type", pd.Series([""] * len(d), index=d.index)).astype(str).str.lower().str.strip()
    d["is_coverage_eligible"] = _source_eligible_mask(d)
    return d, {
        "input_rows": int(len(frame)),
        "invalid_available_from_rows": invalid_available_from,
        "future_available_from_rows": future_available_from,
    }


def _observed_revision_mask(frame: pd.DataFrame) -> pd.Series:
    mask = pd.Series(False, index=frame.index)
    for col in ESTIMATE_OBSERVATION_COLUMNS:
        if col in frame.columns:
            mask = mask | pd.to_numeric(frame[col], errors="coerce").notna()
    for col in REVISION_COLUMNS:
        if col in frame.columns:
            mask = mask | (pd.to_numeric(frame[col], errors="coerce").fillna(0.0).abs() > 1e-12)
    return mask


def _directional_guidance_mask(frame: pd.DataFrame) -> pd.Series:
    mask = pd.Series(False, index=frame.index)
    for col in GUIDANCE_COLUMNS:
        if col in frame.columns:
            mask = mask | (pd.to_numeric(frame[col], errors="coerce").fillna(0.0).abs() > 0.0)
    if "guidance_direction" in frame.columns:
        direction = frame["guidance_direction"].astype(str).str.lower().str.strip()
        mask = mask | direction.isin(
            ["positive", "raise", "raised", "up", "beat", "above", "negative", "cut", "lower", "lowered", "down", "miss", "below"]
        )
    if "direction" in frame.columns:
        direction = frame["direction"].astype(str).str.lower().str.strip()
        mask = mask | direction.isin(["positive", "up", "raise", "negative", "down", "cut"])
    return mask


def _ticker_depth_count(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    depth = frame.groupby("ticker")["available_from"].nunique()
    return int((depth >= 2).sum())


def _span_days(frame: pd.DataFrame) -> int:
    if frame.empty or "available_from" not in frame.columns:
        return 0
    values = frame["available_from"].dropna()
    if values.empty:
        return 0
    return int((values.max() - values.min()).days)


def _recency_days(frame: pd.DataFrame, as_of: pd.Timestamp | None) -> int | None:
    if as_of is None or frame.empty:
        return None
    latest = frame["available_from"].dropna().max()
    if pd.isna(latest):
        return None
    return int((as_of.normalize() - latest.normalize()).days)


def _find_col(frame: pd.DataFrame, names: list[str]) -> str | None:
    for name in names:
        if name in frame.columns:
            return name
    return None


def _book_coverage(path: str | Path | None, covered_tickers: set[str], *, top_n: int | None = None) -> dict[str, Any]:
    if not path:
        return {"status": "not_supplied", "coverage_weight": 0.0, "covered_ticker_count": 0, "bucket_count": 0}
    frame = read_table(repo_path(path))
    if frame.empty or "ticker" not in frame.columns:
        return {"status": "missing_or_empty", "path": str(repo_path(path)), "coverage_weight": 0.0, "covered_ticker_count": 0, "bucket_count": 0}
    d = frame.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d = d[d["ticker"].ne("")]
    if top_n is not None:
        score_col = _find_col(d, ["alphaops_score", "score_total", "score", "rank_score"])
        if score_col:
            d = d.sort_values(score_col, ascending=False).head(top_n)
        else:
            d = d.head(top_n)
    weight_col = _find_col(d, WEIGHT_COLUMNS)
    if weight_col:
        weights = pd.to_numeric(d[weight_col], errors="coerce").fillna(0.0).abs()
        denom = float(weights.sum())
        coverage_weight = float(weights[d["ticker"].isin(covered_tickers)].sum() / denom) if denom > 0 else 0.0
    else:
        coverage_weight = float(d["ticker"].isin(covered_tickers).mean()) if len(d) else 0.0
    bucket_col = _find_col(d, BUCKET_COLUMNS)
    bucket_count = 0
    if bucket_col:
        bucket_count = int(d[d["ticker"].isin(covered_tickers)][bucket_col].astype(str).str.strip().replace("", pd.NA).dropna().nunique())
    return {
        "status": "available",
        "path": str(repo_path(path)),
        "row_count": int(len(d)),
        "coverage_weight": coverage_weight,
        "covered_ticker_count": int(d["ticker"].isin(covered_tickers).sum()),
        "bucket_count": bucket_count,
    }


def coverage_summary_from_frame(
    frame: pd.DataFrame,
    *,
    as_of: pd.Timestamp | None = None,
    current_holdings: str | Path | None = None,
    target_book: str | Path | None = None,
    candidate_book: str | Path | None = None,
) -> dict[str, Any]:
    d, base = _normalize_frame(frame, as_of)
    eligible = d[d["is_coverage_eligible"]].copy()
    revision_mask = _observed_revision_mask(eligible)
    guidance_mask = _directional_guidance_mask(eligible)
    observed = eligible[revision_mask | guidance_mask].copy()
    covered_tickers = set(observed["ticker"].astype(str).str.upper().str.strip())
    coverage_eligible_rows = int(len(observed))
    coverage_eligible_tickers = int(len(covered_tickers))
    history_depth_ticker_count = _ticker_depth_count(eligible[_observed_revision_mask(eligible)])
    observation_span_days = _span_days(eligible)
    data_recency_days = _recency_days(observed, as_of)
    directional_guidance_rows = int(guidance_mask.sum())
    directional_guidance_tickers = int(eligible.loc[guidance_mask, "ticker"].nunique()) if not eligible.empty else 0
    revision_history_research_ready = (
        history_depth_ticker_count >= 10
        and observation_span_days >= 14
        and (data_recency_days is not None and data_recency_days <= 30)
    )
    guidance_research_ready = (
        directional_guidance_rows >= 10
        and directional_guidance_tickers >= 5
        and (data_recency_days is not None and data_recency_days <= 30)
    )
    plumbing_ready = coverage_eligible_rows >= 5 or coverage_eligible_tickers >= 5
    research_ready = bool(plumbing_ready and (revision_history_research_ready or guidance_research_ready))
    current_cov = _book_coverage(current_holdings, covered_tickers)
    target_cov = _book_coverage(target_book, covered_tickers)
    top50_cov = _book_coverage(candidate_book, covered_tickers, top_n=50)
    max_current_or_target_weight = max(float(current_cov.get("coverage_weight", 0.0)), float(target_cov.get("coverage_weight", 0.0)))
    max_service_weight = max(max_current_or_target_weight, float(top50_cov.get("coverage_weight", 0.0)))
    bucket_count = max(int(current_cov.get("bucket_count", 0)), int(target_cov.get("bucket_count", 0)), int(top50_cov.get("bucket_count", 0)))
    service_ready = bool(research_ready and (max_current_or_target_weight >= 0.60 or top50_cov.get("coverage_weight", 0.0) >= 0.40) and bucket_count >= 2)
    policy_ready = bool(research_ready and max_current_or_target_weight >= 0.70 and coverage_eligible_tickers >= 15 and bucket_count >= 3 and observation_span_days >= 180)
    status = "POLICY_READY" if policy_ready else "SERVICE_READY" if service_ready else "RESEARCH_READY" if research_ready else "PLUMBING_READY" if plumbing_ready else "DATA_INSUFFICIENT"
    source_counts = d.get("source_type", pd.Series([], dtype=str)).value_counts().to_dict()
    return {
        "schema_version": "earnings-guidance-coverage-v1",
        "status": status,
        "research_only": True,
        "production_activation_allowed": False,
        **base,
        "coverage_eligible_source_types": sorted(COVERAGE_ELIGIBLE_SOURCE_TYPES),
        "non_coverage_source_types": sorted(NON_COVERAGE_SOURCE_TYPES),
        "source_type_counts": {str(k): int(v) for k, v in source_counts.items()},
        "coverage_eligible_rows": coverage_eligible_rows,
        "coverage_eligible_tickers": coverage_eligible_tickers,
        "history_depth_ticker_count": history_depth_ticker_count,
        "directional_guidance_rows": directional_guidance_rows,
        "directional_guidance_tickers": directional_guidance_tickers,
        "observation_span_days": observation_span_days,
        "data_recency_days": data_recency_days,
        "plumbing_ready": bool(plumbing_ready),
        "research_ready": bool(research_ready),
        "service_ready": bool(service_ready),
        "policy_ready": bool(policy_ready),
        "revision_history_research_ready": bool(revision_history_research_ready),
        "guidance_research_ready": bool(guidance_research_ready),
        "current_holdings_coverage": current_cov,
        "target_book_coverage": target_cov,
        "top50_candidate_coverage": top50_cov,
        "bucket_coverage_count": bucket_count,
        "earnings_guidance_group_status": status if research_ready else "DATA_INSUFFICIENT",
        "actuals_context_available": bool((d["source_type"].isin({"sec_actual_snapshot", "current_snapshot"})).any()) if not d.empty else False,
        "proxy_context_available": bool((d["source_type"].isin({"internal_proxy_score", "actual_results_score", "eps_revision_score_proxy"})).any()) if not d.empty else False,
    }


def write_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Earnings Guidance Coverage",
        "",
        f"- status: `{payload['status']}`",
        f"- plumbing_ready: `{str(payload['plumbing_ready']).lower()}`",
        f"- research_ready: `{str(payload['research_ready']).lower()}`",
        f"- service_ready: `{str(payload['service_ready']).lower()}`",
        f"- policy_ready: `{str(payload['policy_ready']).lower()}`",
        f"- production_activation_allowed: `{str(payload['production_activation_allowed']).lower()}`",
        "",
        "## Counts",
        "",
        f"- coverage_eligible_rows: `{payload['coverage_eligible_rows']}`",
        f"- coverage_eligible_tickers: `{payload['coverage_eligible_tickers']}`",
        f"- history_depth_ticker_count: `{payload['history_depth_ticker_count']}`",
        f"- directional_guidance_rows: `{payload['directional_guidance_rows']}`",
        f"- observation_span_days: `{payload['observation_span_days']}`",
        f"- data_recency_days: `{payload['data_recency_days']}`",
        "",
        "Actual/current snapshots and internal proxy scores can appear as context, but do not count toward coverage readiness.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--earnings-signals", default="data_pit/events/earnings_revision_signals.parquet")
    parser.add_argument("--raw-feed", default=None)
    parser.add_argument("--current-holdings", default=None)
    parser.add_argument("--target-book", default=None)
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--output-dir", default="outputs/earnings_guidance_coverage")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    as_of = pd.Timestamp(args.as_of).normalize() if args.as_of else None
    input_path = repo_path(args.earnings_signals)
    if input_path.exists():
        frame = read_table(input_path)
        input_used = str(input_path)
    elif args.raw_feed:
        raw_path = repo_path(args.raw_feed)
        frame = read_table(raw_path)
        input_used = str(raw_path)
    else:
        frame = pd.DataFrame()
        input_used = str(input_path)
    payload = {
        "generated_at_utc": utc_now(),
        "input_used": input_used,
        **coverage_summary_from_frame(
            frame,
            as_of=as_of,
            current_holdings=args.current_holdings,
            target_book=args.target_book,
            candidate_book=args.candidate_book,
        ),
    }
    output_dir = repo_path(args.output_dir)
    write_json(output_dir / "summary.json", payload)
    write_report(output_dir / "report.md", payload)
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

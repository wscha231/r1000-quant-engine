#!/usr/bin/env python3
"""Build PIT earnings revision and guidance signals from dated estimates."""

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

SCHEMA_VERSION = "earnings-revision-signals-v1"
DEFAULT_INPUT = "data_raw/events/earnings_revisions.csv"
DEFAULT_OUTPUT = "data_pit/events/earnings_revision_signals.parquet"
COVERAGE_ELIGIBLE_SOURCE_TYPES = {
    "historical_revision",
    "vendor_estimate_revision",
    "company_guidance",
    "manual_research_import",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if pd.notna(out) else default
    except (TypeError, ValueError):
        return default


def pct_change(current: float, previous: float) -> float:
    if previous == 0 or pd.isna(previous) or pd.isna(current):
        return 0.0
    return float((current - previous) / abs(previous))


def nearest_prior_value(group: pd.DataFrame, row_idx: int, column: str, days: int) -> float:
    current_date = group.loc[row_idx, "available_from"]
    cutoff = current_date - pd.Timedelta(days=days)
    prior = group[(group["available_from"] <= cutoff) & (group.index < row_idx)]
    if prior.empty or column not in prior.columns:
        return float("nan")
    return safe_float(prior.iloc[-1].get(column), float("nan"))


def normalize_guidance(value: Any) -> int:
    text = str(value or "").strip().lower()
    if text in {"positive", "raise", "raised", "up", "beat", "above"}:
        return 1
    if text in {"negative", "cut", "lower", "lowered", "down", "miss", "below"}:
        return -1
    return 0


def build_signals(raw: pd.DataFrame, *, as_of: pd.Timestamp | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = {"ticker", "available_from"}
    missing = sorted(required - set(raw.columns))
    if missing:
        return pd.DataFrame(), {"status": "blocked", "reason": f"missing_required_columns:{','.join(missing)}"}
    d = raw.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["available_from"] = pd.to_datetime(d["available_from"], errors="coerce").dt.normalize()
    if "estimate_date" in d.columns:
        d["estimate_date"] = pd.to_datetime(d["estimate_date"], errors="coerce").dt.normalize()
    else:
        d["estimate_date"] = d["available_from"]
    for col in ["eps_estimate", "revenue_estimate", "margin_estimate", "forward_pe", "forward_pe_5y_avg", "forward_pe_10y_avg"]:
        if col not in d.columns:
            d[col] = pd.NA
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d["guidance_direction"] = d.get("guidance_direction", pd.Series(index=d.index, dtype=str)).fillna("")
    d["source_type"] = d.get("source_type", pd.Series(index=d.index, dtype=str)).fillna("").astype(str).str.lower().str.strip()
    d["source_type_coverage_eligible"] = d["source_type"].isin(COVERAGE_ELIGIBLE_SOURCE_TYPES)
    d["guidance_score_raw"] = d["guidance_direction"].map(normalize_guidance)
    invalid_available_from = int(d["available_from"].isna().sum())
    future_available_from = int((d["available_from"] > as_of).sum()) if as_of is not None else 0
    d = d[d["available_from"].notna() & d["ticker"].ne("")]
    if as_of is not None:
        d = d[d["available_from"] <= as_of]
    d = d.sort_values(["ticker", "available_from", "estimate_date"]).reset_index(drop=True)
    input_history_depth_ticker_count = 0
    coverage_eligible_history_depth_ticker_count = 0
    if not d.empty:
        evidence_mask = pd.Series(False, index=d.index)
        for col in ["eps_estimate", "revenue_estimate", "margin_estimate"]:
            evidence_mask = evidence_mask | d[col].notna()
        depth = d[evidence_mask].groupby("ticker")["available_from"].nunique()
        input_history_depth_ticker_count = int((depth >= 2).sum())
        eligible_depth = d[evidence_mask & d["source_type_coverage_eligible"]].groupby("ticker")["available_from"].nunique()
        coverage_eligible_history_depth_ticker_count = int((eligible_depth >= 2).sum())
    rows: list[dict[str, Any]] = []
    for _, group in d.groupby("ticker", sort=False):
        group = group.reset_index(drop=True)
        for idx, row in group.iterrows():
            eps = safe_float(row.get("eps_estimate"), float("nan"))
            rev = safe_float(row.get("revenue_estimate"), float("nan"))
            margin = safe_float(row.get("margin_estimate"), float("nan"))
            prior_eps_4w = nearest_prior_value(group, idx, "eps_estimate", 28)
            prior_eps_13w = nearest_prior_value(group, idx, "eps_estimate", 91)
            prior_eps_26w = nearest_prior_value(group, idx, "eps_estimate", 182)
            prior_rev_13w = nearest_prior_value(group, idx, "revenue_estimate", 91)
            prior_margin_13w = nearest_prior_value(group, idx, "margin_estimate", 91)
            forward_pe = safe_float(row.get("forward_pe"), float("nan"))
            pe_5y = safe_float(row.get("forward_pe_5y_avg"), float("nan"))
            pe_10y = safe_float(row.get("forward_pe_10y_avg"), float("nan"))
            out = row.to_dict()
            out.update(
                {
                    "eps_revision_4w": pct_change(eps, prior_eps_4w),
                    "eps_revision_13w": pct_change(eps, prior_eps_13w),
                    "eps_revision_26w": pct_change(eps, prior_eps_26w),
                    "revenue_revision_13w": pct_change(rev, prior_rev_13w),
                    "margin_revision_score": margin - prior_margin_13w if pd.notna(margin) and pd.notna(prior_margin_13w) else 0.0,
                    "positive_guidance_flag": int(row.get("guidance_score_raw", 0) > 0),
                    "negative_guidance_flag": int(row.get("guidance_score_raw", 0) < 0),
                    "guidance_vs_consensus_score": int(row.get("guidance_score_raw", 0)),
                    "forward_pe_vs_5y_avg": pct_change(forward_pe, pe_5y),
                    "forward_pe_vs_10y_avg": pct_change(forward_pe, pe_10y),
                }
            )
            rows.append(out)
    out = pd.DataFrame(rows)
    nonzero_revision_ticker_count = 0
    coverage_eligible_nonzero_revision_ticker_count = 0
    directional_guidance_ticker_count = 0
    coverage_eligible_directional_guidance_ticker_count = 0
    if not out.empty:
        revision_mask = pd.Series(False, index=out.index)
        for col in ["eps_revision_4w", "eps_revision_13w", "eps_revision_26w", "revenue_revision_13w", "margin_revision_score"]:
            if col in out.columns:
                revision_mask = revision_mask | (pd.to_numeric(out[col], errors="coerce").fillna(0.0).abs() > 1e-12)
        nonzero_revision_ticker_count = int(out.loc[revision_mask, "ticker"].nunique()) if "ticker" in out.columns else 0
        eligible_mask = out.get("source_type_coverage_eligible", pd.Series(False, index=out.index)).astype(bool)
        coverage_eligible_nonzero_revision_ticker_count = (
            int(out.loc[revision_mask & eligible_mask, "ticker"].nunique()) if "ticker" in out.columns else 0
        )
        guidance_mask = pd.to_numeric(out.get("guidance_score_raw", 0), errors="coerce").fillna(0.0).abs() > 0.0
        directional_guidance_ticker_count = int(out.loc[guidance_mask, "ticker"].nunique()) if "ticker" in out.columns else 0
        coverage_eligible_directional_guidance_ticker_count = (
            int(out.loc[guidance_mask & eligible_mask, "ticker"].nunique()) if "ticker" in out.columns else 0
        )
    if not out.empty and "sector" in out.columns:
        sector_keys = ["available_from", "sector"]
        sector = out.groupby(sector_keys).agg(
            sector_eps_revision_breadth=("eps_revision_13w", lambda x: float((pd.to_numeric(x, errors="coerce") > 0).mean())),
            sector_positive_guidance_ratio=("positive_guidance_flag", "mean"),
        )
        out = out.merge(sector.reset_index(), on=sector_keys, how="left")
    else:
        out["sector_eps_revision_breadth"] = 0.0
        out["sector_positive_guidance_ratio"] = 0.0
    summary = {
        "status": "completed",
        "input_rows": int(len(raw)),
        "output_rows": int(len(out)),
        "invalid_available_from_rows": invalid_available_from,
        "future_available_from_rows_filtered": future_available_from,
        "available_from_required": True,
        "missing_evidence_policy": "neutral",
        "input_history_depth_ticker_count": input_history_depth_ticker_count,
        "coverage_eligible_history_depth_ticker_count": coverage_eligible_history_depth_ticker_count,
        "nonzero_revision_ticker_count": nonzero_revision_ticker_count,
        "coverage_eligible_nonzero_revision_ticker_count": coverage_eligible_nonzero_revision_ticker_count,
        "directional_guidance_ticker_count": directional_guidance_ticker_count,
        "coverage_eligible_directional_guidance_ticker_count": coverage_eligible_directional_guidance_ticker_count,
        "coverage_eligible_source_types": sorted(COVERAGE_ELIGIBLE_SOURCE_TYPES),
        "regime_nowcast_coverage_ready": bool(
            coverage_eligible_nonzero_revision_ticker_count >= 5
            or coverage_eligible_directional_guidance_ticker_count >= 5
        ),
    }
    return out, summary


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", default="outputs/earnings_revision_signals/summary.json")
    parser.add_argument("--as-of", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = repo_path(args.input)
    output_path = repo_path(args.output)
    summary_path = repo_path(args.summary)
    if not input_path.exists():
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked",
            "reason": "missing_input",
            "input": str(input_path),
            "research_only": True,
        }
        write_json(summary_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    raw = pd.read_csv(input_path, low_memory=False)
    as_of = pd.Timestamp(args.as_of).normalize() if args.as_of else None
    out, summary = build_signals(raw, as_of=as_of)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "input": str(input_path),
        "output": str(output_path),
        "research_only": True,
        "production_activation_allowed": False,
        **summary,
    }
    if out.empty:
        payload["status"] = "blocked"
        payload["reason"] = payload.get("reason") or "no_output_rows"
        write_json(summary_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(output_path, index=False)
    write_json(summary_path, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""AI Capex bucket / revision diagnostic for fixed official books.

This is a research-only diagnostic. Forward returns, when present, are written
only as audit labels and are never used for live ranking or selection.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.ai_capex_taxonomy import enrich_frame  # noqa: E402

SCHEMA_VERSION = "ai-capex-bucket-revision-audit-v1"
DEFAULT_OUTPUT_DIR = "outputs/ai_capex_bucket_revision_audit"
CASH_TICKERS = {"CASH", "USD", "BIL", "SGOV", "SHV"}


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return ""
    cols = list(frame.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in frame.to_dict("records"):
        cells = []
        for col in cols:
            value = row.get(col, "")
            if isinstance(value, float):
                value = f"{value:.6g}"
            cells.append(str(value).replace("|", "/"))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def first_numeric(frame: pd.DataFrame, columns: list[str], default: float = 0.0) -> pd.Series:
    for col in columns:
        if col in frame.columns:
            return pd.to_numeric(frame[col], errors="coerce").fillna(default)
    return pd.Series([default] * len(frame), index=frame.index, dtype=float)


def normalize_dates(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "rebalance_date" not in out.columns:
        for col in ["decision_date", "as_of_date", "date"]:
            if col in out.columns:
                out["rebalance_date"] = out[col]
                break
    out["rebalance_date"] = pd.to_datetime(out.get("rebalance_date"), errors="coerce").dt.date.astype(str)
    out["ticker"] = out.get("ticker", pd.Series(index=out.index, dtype=str)).astype(str).str.upper().str.strip()
    return out


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    out = normalize_dates(frame)
    out = enrich_frame(out) if "ai_capex_value_chain_bucket" not in out.columns else out
    out["weight"] = first_numeric(out, ["weight", "target_weight"], 0.0)
    out["is_cash"] = out["ticker"].isin(CASH_TICKERS) | out["ticker"].str.upper().str.contains("CASH", na=False)
    out["forward_return_audit_only"] = first_numeric(
        out,
        [
            "forward_126d_excess",
            "excess_forward_126d",
            "period_forward_return",
            "raw_period_forward_return",
            "forward_126d_return",
        ],
        0.0,
    )
    out["rs_3m"] = first_numeric(out, ["rs_benchmark_3m", "rs_spy_3m", "relative_strength_3m", "mom_3m"], 0.0)
    out["rs_6m"] = first_numeric(out, ["rs_benchmark_6m", "rs_spy_6m", "relative_strength_6m", "mom_6m"], 0.0)
    out["eps_revision_proxy_diag"] = first_numeric(
        out,
        ["eps_revision_13w", "eps_revision_score", "revision_score", "eps_revision_proxy", "actual_results_score"],
        0.0,
    )
    out["guidance_proxy_diag"] = first_numeric(
        out,
        ["positive_guidance_flag", "guidance_vs_consensus_score", "event_reaction_score", "actual_results_score"],
        0.0,
    )
    out["momentum_positive"] = (out["rs_3m"] > 0) | (out["rs_6m"] > 0)
    out["revision_positive"] = (out["eps_revision_proxy_diag"] > 0) | (out["guidance_proxy_diag"] > 0)
    out["ai_bottleneck_high"] = pd.to_numeric(out.get("ai_capex_bottleneck_score"), errors="coerce").fillna(0.0) >= 0.5
    return out


def bucket_exposure(selected: pd.DataFrame) -> pd.DataFrame:
    stock = selected[~selected["is_cash"]].copy()
    if stock.empty:
        return pd.DataFrame()
    rows = []
    for (dt, bucket), group in stock.groupby(["rebalance_date", "ai_capex_value_chain_bucket"], dropna=False):
        weight = float(group["weight"].sum())
        rows.append(
            {
                "rebalance_date": dt,
                "ai_capex_value_chain_bucket": bucket,
                "weight": weight,
                "name_count": int(group["ticker"].nunique()),
                "avg_bottleneck_score": float(pd.to_numeric(group.get("ai_capex_bottleneck_score"), errors="coerce").fillna(0.0).mean()),
                "revision_positive_weight": float(group.loc[group["revision_positive"], "weight"].sum()),
                "momentum_positive_weight": float(group.loc[group["momentum_positive"], "weight"].sum()),
            }
        )
    return pd.DataFrame(rows).sort_values(["rebalance_date", "weight"], ascending=[True, False])


def bucket_contribution(selected: pd.DataFrame) -> pd.DataFrame:
    stock = selected[~selected["is_cash"]].copy()
    if stock.empty:
        return pd.DataFrame()
    stock["weighted_forward_return_audit_only"] = stock["weight"] * stock["forward_return_audit_only"]
    rows = []
    for bucket, group in stock.groupby("ai_capex_value_chain_bucket", dropna=False):
        rows.append(
            {
                "ai_capex_value_chain_bucket": bucket,
                "row_count": int(len(group)),
                "unique_tickers": int(group["ticker"].nunique()),
                "avg_weight": float(group["weight"].mean()),
                "avg_forward_return_audit_only": float(group["forward_return_audit_only"].mean()),
                "weighted_forward_return_audit_only": float(group["weighted_forward_return_audit_only"].sum()),
                "positive_forward_rate_audit_only": float((group["forward_return_audit_only"] > 0).mean()),
                "revision_positive_rate": float(group["revision_positive"].mean()),
                "momentum_positive_rate": float(group["momentum_positive"].mean()),
                "top_tickers": ",".join(group["ticker"].value_counts().head(10).index.astype(str)),
            }
        )
    return pd.DataFrame(rows).sort_values("weighted_forward_return_audit_only", ascending=False)


def missed_candidates(selected: pd.DataFrame, candidates: pd.DataFrame, top_n: int) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    cand = prepare(candidates)
    selected_keys = set(zip(selected["rebalance_date"].astype(str), selected["ticker"].astype(str)))
    cand["_selected_key"] = list(zip(cand["rebalance_date"].astype(str), cand["ticker"].astype(str)))
    cand = cand[~cand["_selected_key"].isin(selected_keys)].copy()
    cand = cand[~cand["is_cash"] & cand["ai_bottleneck_high"] & cand["momentum_positive"]].copy()
    if cand.empty:
        return pd.DataFrame()
    cand["candidate_quality_score_diag"] = (
        first_numeric(cand, ["alphaops_vnext_score", "concentrated_score", "score"], 0.0)
        + 0.25 * cand["rs_3m"]
        + 0.25 * cand["eps_revision_proxy_diag"]
        + 0.25 * pd.to_numeric(cand.get("ai_capex_bottleneck_score"), errors="coerce").fillna(0.0)
    )
    cols = [
        "rebalance_date",
        "ticker",
        "Name",
        "sector",
        "industry_group",
        "ai_capex_value_chain_bucket",
        "ai_capex_bottleneck_score",
        "candidate_quality_score_diag",
        "rs_3m",
        "rs_6m",
        "eps_revision_proxy_diag",
        "guidance_proxy_diag",
        "forward_return_audit_only",
        "selection_reason",
    ]
    existing = [c for c in cols if c in cand.columns]
    return cand.sort_values(["rebalance_date", "candidate_quality_score_diag"], ascending=[True, False])[existing].groupby("rebalance_date").head(top_n)


def run(args: argparse.Namespace) -> dict[str, Any]:
    target_book = repo_path(args.target_book)
    candidate_book = repo_path(args.candidate_book) if args.candidate_book else None
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = prepare(read_table(target_book))
    candidates = read_table(candidate_book) if candidate_book else pd.DataFrame()

    exposure = bucket_exposure(selected)
    contribution = bucket_contribution(selected)
    missed = missed_candidates(selected, candidates, args.top_missed_per_date)
    exposure.to_csv(output_dir / "bucket_exposure_by_rebalance.csv", index=False)
    contribution.to_csv(output_dir / "bucket_contribution.csv", index=False)
    missed.to_csv(output_dir / "missed_bucket_candidates.csv", index=False)

    ai_stock = selected[(~selected["is_cash"]) & selected["ai_capex_value_chain_bucket"].astype(str).ne("AI_OTHER")]
    payload = {
        "status": "completed",
        "schema_version": SCHEMA_VERSION,
        "target_book": str(target_book),
        "candidate_book": str(candidate_book) if candidate_book else "",
        "row_count": int(len(selected)),
        "ai_selected_row_count": int(len(ai_stock)),
        "ai_selected_ratio": float(len(ai_stock) / max(1, len(selected[~selected["is_cash"]]))),
        "bucket_count": int(ai_stock["ai_capex_value_chain_bucket"].nunique()) if not ai_stock.empty else 0,
        "top_bucket_by_weighted_forward_audit": contribution.iloc[0].to_dict() if not contribution.empty else {},
        "missed_candidate_count": int(len(missed)),
        "forward_returns_audit_only": True,
        "used_forward_return_in_ranking": False,
        "research_only": True,
        "production_activation_allowed": False,
    }
    write_json(output_dir / "summary.json", payload)
    lines = ["# AI Capex Bucket / Revision Audit", ""]
    lines.append(f"- Target book: `{target_book}`")
    if candidate_book:
        lines.append(f"- Candidate book: `{candidate_book}`")
    lines.append(f"- AI selected rows: {payload['ai_selected_row_count']} ({payload['ai_selected_ratio']:.2%})")
    lines.append(f"- Bucket count: {payload['bucket_count']}")
    lines.append(f"- Missed bucket candidates: {payload['missed_candidate_count']}")
    lines.append("")
    lines.append("Forward returns in this report are audit labels only.")
    lines.append("")
    lines.append("## Bucket Contribution")
    if contribution.empty:
        lines.append("No bucket contribution rows.")
    else:
        lines.append(markdown_table(contribution.head(12)))
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--candidate-book", default="")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-missed-per-date", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Cheap screen for AI capex bottleneck + revision + momentum candidates."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.ai_capex_taxonomy import enrich_frame  # noqa: E402

SCHEMA_VERSION = "ai-capex-bottleneck-screen-v1"
DEFAULT_OUTPUT_DIR = "outputs/ai_capex_bottleneck_screen"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
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
    try:
        if path.suffix.lower() in {".parquet", ".pq"}:
            return pd.read_parquet(path)
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def first_existing(frame: pd.DataFrame, columns: list[str], default: float = 0.0) -> pd.Series:
    for col in columns:
        if col in frame.columns:
            return pd.to_numeric(frame[col], errors="coerce").fillna(default)
    return pd.Series([default] * len(frame), index=frame.index, dtype=float)


def date_series(frame: pd.DataFrame) -> pd.Series:
    for col in ["rebalance_date", "decision_date", "as_of_date", "date"]:
        if col in frame.columns:
            return pd.to_datetime(frame[col], errors="coerce").dt.normalize()
    return pd.Series([pd.NaT] * len(frame), index=frame.index)


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    if "ai_capex_value_chain_bucket" not in d.columns:
        d = enrich_frame(d)
    d["screen_date"] = date_series(d)
    d["ticker"] = d.get("ticker", pd.Series(index=d.index, dtype=str)).astype(str).str.upper().str.strip()
    d["forward_126d_excess_audit_only"] = first_existing(
        d,
        ["forward_126d_excess", "excess_forward_126d", "forward_126d_return", "period_forward_return", "raw_period_forward_return"],
        0.0,
    )
    d["forward_63d_excess_audit_only"] = first_existing(
        d,
        ["forward_63d_excess", "excess_forward_63d", "forward_63d_return"],
        d["forward_126d_excess_audit_only"],
    )
    d["eps_revision_13w"] = first_existing(d, ["eps_revision_13w", "revision_eps_13w", "eps_estimate_revision_13w"], 0.0)
    d["revenue_revision_13w"] = first_existing(d, ["revenue_revision_13w", "sales_revision_13w"], 0.0)
    d["positive_guidance_flag"] = first_existing(d, ["positive_guidance_flag", "guidance_raise_flag"], 0.0)
    d["actual_results_score"] = first_existing(d, ["actual_results_score", "earnings_actual_results_score"], 0.0)
    d["rs_3m"] = first_existing(
        d,
        ["rs_benchmark_3m", "rs_spy_3m", "relative_strength_3m", "momentum_3m", "return_63d"],
        0.0,
    )
    d["momentum_rank_proxy"] = d["rs_3m"].rank(pct=True).fillna(0.5)
    d["ai_bottleneck_high"] = pd.to_numeric(d.get("ai_capex_bottleneck_score"), errors="coerce").fillna(0.0) >= 0.5
    d["eps_revision_positive"] = (d["eps_revision_13w"] > 0) | (d["revenue_revision_13w"] > 0)
    d["earnings_confirmation_positive"] = (
        d["eps_revision_positive"] | (d["positive_guidance_flag"] > 0) | (d["actual_results_score"] > 0)
    )
    d["earnings_confirmation_source"] = "neutral"
    d.loc[d["actual_results_score"] > 0, "earnings_confirmation_source"] = "actual_results_score"
    d.loc[d["positive_guidance_flag"] > 0, "earnings_confirmation_source"] = "positive_guidance"
    d.loc[d["eps_revision_positive"], "earnings_confirmation_source"] = "eps_or_revenue_revision"
    d["momentum_high"] = (d["rs_3m"] > 0) | (d["momentum_rank_proxy"] >= 0.6)
    d["is_ai_capex_bucket"] = d["ai_capex_value_chain_bucket"].astype(str).ne("AI_OTHER")
    d["screen_group"] = (
        d["is_ai_capex_bucket"].map({True: "ai", False: "non_ai"})
        + "|bottleneck_"
        + d["ai_bottleneck_high"].map({True: "high", False: "low"})
        + "|revision_"
        + d["earnings_confirmation_positive"].map({True: "pos", False: "nonpos"})
        + "|momentum_"
        + d["momentum_high"].map({True: "high", False: "low"})
    )
    return d


def group_stats(frame: pd.DataFrame, *, oos_start: pd.Timestamp | None = None) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for group, g in frame.groupby("screen_group", dropna=False):
        for label, subset in [
            ("full", g),
            ("is", g[g["screen_date"] < oos_start] if oos_start is not None else g.iloc[0:0]),
            ("oos", g[g["screen_date"] >= oos_start] if oos_start is not None else g.iloc[0:0]),
        ]:
            if subset.empty and label != "full":
                rows.append({"screen_group": group, "split": label, "count": 0})
                continue
            y126 = pd.to_numeric(subset["forward_126d_excess_audit_only"], errors="coerce").fillna(0.0)
            y63 = pd.to_numeric(subset["forward_63d_excess_audit_only"], errors="coerce").fillna(0.0)
            rows.append(
                {
                    "screen_group": group,
                    "split": label,
                    "count": int(len(subset)),
                    "positive_rate_126d": float((y126 > 0).mean()) if len(subset) else 0.0,
                    "mean_126d_excess": float(y126.mean()) if len(subset) else 0.0,
                    "median_126d_excess": float(y126.median()) if len(subset) else 0.0,
                    "mean_63d_excess": float(y63.mean()) if len(subset) else 0.0,
                    "unique_tickers": int(subset["ticker"].nunique()) if "ticker" in subset.columns else 0,
                    "unique_buckets": int(subset["ai_capex_value_chain_bucket"].nunique()) if "ai_capex_value_chain_bucket" in subset.columns else 0,
                }
            )
    return pd.DataFrame(rows)


def decide(stats: pd.DataFrame, target_group: str, min_count: int, min_oos_count: int) -> dict[str, Any]:
    target = stats[stats["screen_group"].eq(target_group)].copy()
    full = target[target["split"].eq("full")]
    oos = target[target["split"].eq("oos")]
    if full.empty:
        return {"screen_pass": False, "verdict": "blocked_missing_target_group", "target_group": target_group}
    full_row = full.iloc[0].to_dict()
    oos_row = oos.iloc[0].to_dict() if not oos.empty else {"count": 0, "mean_126d_excess": 0.0, "positive_rate_126d": 0.0}
    pass_gate = (
        int(full_row.get("count") or 0) >= min_count
        and int(oos_row.get("count") or 0) >= min_oos_count
        and safe_float(full_row.get("mean_126d_excess")) > 0
        and safe_float(oos_row.get("mean_126d_excess")) >= 0
        and safe_float(full_row.get("positive_rate_126d")) >= 0.50
        and int(full_row.get("unique_tickers") or 0) >= 3
    )
    return {
        "screen_pass": bool(pass_gate),
        "verdict": "screen_pass_design_default_off_hook" if pass_gate else "reject_or_inconclusive",
        "target_group": target_group,
        "target_full": full_row,
        "target_oos": oos_row,
    }


def best_group(stats: pd.DataFrame, split: str, min_count: int) -> dict[str, Any]:
    d = stats[stats["split"].eq(split)].copy()
    if d.empty:
        return {}
    d["count"] = pd.to_numeric(d["count"], errors="coerce").fillna(0)
    d["mean_126d_excess"] = pd.to_numeric(d["mean_126d_excess"], errors="coerce").fillna(float("-inf"))
    d = d[d["count"] >= min_count]
    if d.empty:
        return {}
    return d.sort_values("mean_126d_excess", ascending=False).iloc[0].to_dict()


def render_report(payload: dict[str, Any], stats: pd.DataFrame) -> str:
    lines = [
        "# AI Capex Bottleneck Cheap Screen",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Verdict: `{payload.get('verdict')}`",
        f"- Screen pass: `{payload.get('screen_pass')}`",
        f"- Target group: `{payload.get('target_group')}`",
        "",
        "Forward returns are audit labels only and are not used for live ranking.",
        "",
        "| Group | Split | Count | Mean 126d excess | Positive rate | Unique tickers |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for _, row in stats.iterrows():
        lines.append(
            f"| {row.get('screen_group')} | {row.get('split')} | {int(safe_float(row.get('count')))} | "
            f"{safe_float(row.get('mean_126d_excess')):.2%} | {safe_float(row.get('positive_rate_126d')):.2%} | "
            f"{int(safe_float(row.get('unique_tickers')))} |"
        )
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--oos-start", default="2024-06-03")
    parser.add_argument("--min-count", type=int, default=20)
    parser.add_argument("--min-oos-count", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = repo_path(args.input)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source = read_table(input_path)
    if source.empty:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked",
            "reason": "missing_or_empty_input",
            "input": str(input_path),
            "research_only": True,
        }
        write_json(output_dir / "summary.json", payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    prepared = prepare(source)
    oos_start = pd.Timestamp(args.oos_start).normalize()
    stats = group_stats(prepared, oos_start=oos_start)
    target_group = "ai|bottleneck_high|revision_pos|momentum_high"
    decision = decide(stats, target_group, int(args.min_count), int(args.min_oos_count))
    enriched_path = output_dir / "screen_input_enriched.csv"
    stats_path = output_dir / "group_stats.csv"
    prepared.to_csv(enriched_path, index=False)
    stats.to_csv(stats_path, index=False)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "input": str(input_path),
        "research_only": True,
        "production_activation_allowed": False,
        "used_forward_return_in_ranking": False,
        "forward_returns_audit_only": True,
        "oos_start": oos_start.date().isoformat(),
        "row_count": int(len(prepared)),
        "earnings_confirmation_source_counts": prepared["earnings_confirmation_source"].value_counts().to_dict()
        if "earnings_confirmation_source" in prepared.columns
        else {},
        "stats_csv": str(stats_path),
        "best_full_group": best_group(stats, "full", int(args.min_count)),
        "best_oos_group": best_group(stats, "oos", int(args.min_oos_count)),
        **decision,
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload, stats), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Research-only cross-sector leadership rotation screen.

This sidecar answers a narrow question: if the next market leadership
rotation is not AI capex, can the existing sector-neutral RS / momentum /
theme evidence surface the new leaders without hardcoded tickers?

The tool does not select, score, weight, trade, or mutate production policy.
Forward returns, when present, are audit labels only.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


PIT_SCORE_COLUMNS = (
    "relative_strength_composite",
    "market_leader_lane_score",
    "oneil_leadership_score",
    "industry_group_strength_score",
    "sector_leadership_score",
    "rs_benchmark_1m",
    "rs_benchmark_3m",
    "rs_benchmark_6m",
    "rs_spy_3m",
    "rs_qqq_3m",
    "rs_sector_3m",
    "rs_industry_12m",
    "mom_3m",
    "mom_6m",
    "theme_phase_multiplier_primary",
    "theme_phase_multiplier_max",
    "eps_revision_score",
    "revision_score",
    "actual_results_score",
    "entry_quality_score",
    "alphaops_vnext_score",
)

FORWARD_LABEL_CANDIDATES = (
    "forward_126d_excess",
    "fwd_126d_excess_spy",
    "forward_126d_excess_spy",
    "period_forward_return",
    "risk_adjusted_forward_return",
    "raw_period_forward_return",
)

FORWARD_63D_CANDIDATES = (
    "forward_63d_excess",
    "fwd_63d_excess_spy",
    "forward_return_63d",
)

GROUP_FIELDS = (
    "sector",
    "industry_group",
    "theme_phase_primary",
    "sector_thesis_bucket",
)


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(out) or math.isinf(out):
        return default
    return out


def _first_present(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
    available = set(columns)
    for col in candidates:
        if col in available:
            return col
    return None


def _numeric_series(df: pd.DataFrame, *candidates: str, default: float = 0.0) -> pd.Series:
    for col in candidates:
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce").fillna(default)
    return pd.Series(default, index=df.index, dtype="float64")


def _text(row: pd.Series, *cols: str) -> str:
    values: list[str] = []
    for col in cols:
        if col in row.index and pd.notna(row[col]):
            values.append(str(row[col]))
    return " ".join(values).lower()


def classify_sector_thesis(row: pd.Series) -> tuple[str, str, str]:
    """Return (bucket, risk_flags, source_confidence) from PIT-visible labels.

    This is deliberately taxonomy-level. It does not turn specific tickers
    into buy lists, and it should not be interpreted as production evidence.
    """

    text = _text(
        row,
        "sector",
        "industry_group",
        "subindustry",
        "theme_phase_primary",
        "theme_reason",
        "lane_reason",
        "Name",
    )
    flags: list[str] = []

    if any(k in text for k in ("biotech", "biotechnology", "therapeutic", "pharma", "drug", "life sciences")):
        flags.extend(["binary_event_risk", "trial_fda_risk", "cash_runway_check_required"])
        if any(k in text for k in ("approved", "commercial", "revenue", "diagnostic", "device")):
            return "BIOTECH_REVENUE_INFLECTION", ",".join(flags), "taxonomy_label"
        return "BIOTECH_PLATFORM", ",".join(flags), "taxonomy_label"
    if any(k in text for k in ("health care", "healthcare", "medical", "diagnostic")):
        flags.append("reimbursement_or_regulatory_risk")
        return "HEALTHCARE_NON_BIOTECH", ",".join(flags), "taxonomy_label"
    if any(k in text for k in ("oil", "gas", "energy", "uranium", "nuclear", "power", "utility")):
        flags.extend(["commodity_cycle_risk", "rate_sensitivity_check"])
        return "ENERGY_POWER_SUPPLY", ",".join(flags), "taxonomy_label"
    if any(k in text for k in ("bank", "insurance", "capital markets", "financial")):
        flags.extend(["credit_cycle_risk", "rate_curve_risk"])
        return "FINANCIAL_RATE_CYCLE", ",".join(flags), "taxonomy_label"
    if any(k in text for k in ("industrial", "aerospace", "defense", "machinery", "electrical")):
        flags.extend(["order_cycle_risk", "backlog_quality_check"])
        return "INDUSTRIAL_RESHORING_CAPEX", ",".join(flags), "taxonomy_label"
    if any(k in text for k in ("material", "chemical", "steel", "copper", "mining", "metal")):
        flags.extend(["commodity_price_risk", "china_demand_risk"])
        return "MATERIALS_COMMODITY", ",".join(flags), "taxonomy_label"
    if any(k in text for k in ("software", "cloud", "cyber", "platform", "application")):
        flags.extend(["multiple_compression_risk", "growth_durability_check"])
        return "SOFTWARE_PLATFORM", ",".join(flags), "taxonomy_label"
    if any(k in text for k in ("semiconductor", "memory", "storage", "network", "datacenter", "ai", "accelerator")):
        flags.extend(["capex_cycle_risk", "customer_concentration_check"])
        return "AI_CAPEX_SUPPLY_CHAIN", ",".join(flags), "taxonomy_label"
    if any(k in text for k in ("consumer", "retail", "restaurant", "apparel")):
        flags.extend(["consumer_demand_risk", "margin_pressure_check"])
        return "CONSUMER_DISCRETIONARY", ",".join(flags), "taxonomy_label"

    return "OTHER_CROSS_SECTOR_LEADER", "", "taxonomy_label"


def _percentile_by_date(df: pd.DataFrame, col: str) -> pd.Series:
    numeric = pd.to_numeric(df[col], errors="coerce")
    if "rebalance_date" not in df.columns:
        return numeric.rank(pct=True).fillna(0.5)
    return numeric.groupby(df["rebalance_date"]).rank(pct=True).fillna(0.5)


def enrich_leadership(df: pd.DataFrame, leader_quantile: float) -> pd.DataFrame:
    out = df.copy()
    if "ticker" in out.columns:
        out = out[out["ticker"].astype(str).str.upper() != "CASH"].copy()
    if "rebalance_date" in out.columns:
        out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")

    thesis = out.apply(classify_sector_thesis, axis=1, result_type="expand")
    thesis.columns = ["sector_thesis_bucket", "sector_thesis_risk_flags", "sector_thesis_source_confidence"]
    out = pd.concat([out.reset_index(drop=True), thesis.reset_index(drop=True)], axis=1)

    score_parts: list[pd.Series] = []
    used_cols: list[str] = []
    for col in PIT_SCORE_COLUMNS:
        if col not in out.columns:
            continue
        score_parts.append(_percentile_by_date(out, col))
        used_cols.append(col)
    if score_parts:
        out["cross_sector_leadership_score"] = pd.concat(score_parts, axis=1).mean(axis=1).fillna(0.0)
    else:
        out["cross_sector_leadership_score"] = 0.0
    out["cross_sector_leadership_score_columns"] = ",".join(used_cols)

    rs_3m = _numeric_series(out, "rs_benchmark_3m", "rs_spy_3m")
    rs_6m = _numeric_series(out, "rs_benchmark_6m", "rs_spy_6m")
    mom_3m = _numeric_series(out, "mom_3m")
    leader_tier = out.get("leader_tier", pd.Series("", index=out.index)).astype(str)
    strong_tier = leader_tier.isin(["DUAL_LEADER", "SECTOR_LEADER", "EMERGING_LEADER"])
    threshold = out["cross_sector_leadership_score"].quantile(leader_quantile) if len(out) else 1.0
    out["cross_sector_leadership_threshold"] = float(threshold) if pd.notna(threshold) else 1.0
    out["cross_sector_leadership_candidate"] = (
        (out["cross_sector_leadership_score"] >= out["cross_sector_leadership_threshold"])
        & ((rs_3m > 0) | (rs_6m > 0) | (mom_3m > 0) | strong_tier)
    )
    out["used_forward_return_in_ranking"] = False
    out["forward_returns_audit_only"] = True
    return out


@dataclass(frozen=True)
class Split:
    name: str
    frame: pd.DataFrame


def _splits(df: pd.DataFrame, oos_start: str) -> list[Split]:
    if "rebalance_date" not in df.columns or df["rebalance_date"].isna().all():
        return [Split("full", df)]
    start = pd.Timestamp(oos_start)
    return [
        Split("full", df),
        Split("is", df[df["rebalance_date"] < start]),
        Split("oos", df[df["rebalance_date"] >= start]),
    ]


def build_group_stats(df: pd.DataFrame, oos_start: str, min_group_count: int) -> pd.DataFrame:
    forward_col = _first_present(df.columns, FORWARD_LABEL_CANDIDATES)
    rows: list[dict[str, object]] = []
    for group_field in GROUP_FIELDS:
        if group_field not in df.columns:
            continue
        for split in _splits(df, oos_start):
            frame = split.frame.copy()
            if frame.empty:
                continue
            for group_value, grp in frame.groupby(group_field, dropna=False):
                candidates = grp[grp["cross_sector_leadership_candidate"]]
                row: dict[str, object] = {
                    "group_field": group_field,
                    "group_value": "" if pd.isna(group_value) else str(group_value),
                    "split": split.name,
                    "row_count": int(len(grp)),
                    "candidate_count": int(len(candidates)),
                    "avg_leadership_score": float(grp["cross_sector_leadership_score"].mean()) if len(grp) else None,
                    "max_leadership_score": float(grp["cross_sector_leadership_score"].max()) if len(grp) else None,
                    "min_group_count": int(min_group_count),
                    "passes_min_group_count": bool(len(candidates) >= min_group_count),
                }
                if forward_col:
                    audit = pd.to_numeric(candidates[forward_col], errors="coerce").dropna()
                    row.update(
                        {
                            "forward_label_column": forward_col,
                            "mean_forward_label": float(audit.mean()) if len(audit) else None,
                            "median_forward_label": float(audit.median()) if len(audit) else None,
                            "positive_rate_forward_label": float((audit > 0).mean()) if len(audit) else None,
                            "forward_label_count": int(len(audit)),
                        }
                    )
                rows.append(row)
    return pd.DataFrame(rows)


def _summarize(
    enriched: pd.DataFrame,
    stats: pd.DataFrame,
    *,
    input_path: Path,
    output_dir: Path,
    oos_start: str,
    min_group_count: int,
) -> dict[str, object]:
    forward_col = _first_present(enriched.columns, FORWARD_LABEL_CANDIDATES)
    candidates = enriched[enriched["cross_sector_leadership_candidate"]]
    screen_pass = False
    best_groups: list[dict[str, object]] = []
    if forward_col and not stats.empty:
        full = stats[
            (stats["split"] == "full")
            & (stats["passes_min_group_count"])
            & (pd.to_numeric(stats.get("mean_forward_label"), errors="coerce") > 0)
        ].copy()
        oos = stats[
            (stats["split"] == "oos")
            & (stats["passes_min_group_count"])
            & (pd.to_numeric(stats.get("mean_forward_label"), errors="coerce") > 0)
        ].copy()
        if not full.empty and not oos.empty:
            screen_pass = True
        ranked = full.sort_values(["mean_forward_label", "candidate_count"], ascending=[False, False]).head(10)
        best_groups = ranked.to_dict(orient="records")

    return {
        "schema_version": "cross-sector-leadership-rotation-v1",
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "row_count": int(len(enriched)),
        "candidate_count": int(len(candidates)),
        "candidate_rate": float(len(candidates) / len(enriched)) if len(enriched) else 0.0,
        "oos_start": oos_start,
        "min_group_count": int(min_group_count),
        "forward_label_column": forward_col,
        "forward_returns_audit_only": True,
        "used_forward_return_in_ranking": False,
        "production_activation_allowed": False,
        "policy_mutation_allowed": False,
        "live_trading_enabled": False,
        "screen_pass": bool(screen_pass),
        "status": "screen_passed" if screen_pass else ("telemetry_only_no_forward_label" if not forward_col else "no_group_passed_oos_audit"),
        "best_groups": best_groups,
        "thesis_bucket_counts": enriched["sector_thesis_bucket"].value_counts().to_dict()
        if "sector_thesis_bucket" in enriched.columns
        else {},
    }


def write_report(summary: dict[str, object], stats: pd.DataFrame, output_dir: Path) -> None:
    lines = [
        "# Cross-Sector Leadership Rotation Screen",
        "",
        "Research-only sidecar. It does not change selection, weights, cash, live trading, or production gates.",
        "",
        f"- status: `{summary['status']}`",
        f"- rows: `{summary['row_count']}`",
        f"- leadership candidates: `{summary['candidate_count']}` ({summary['candidate_rate']:.2%})",
        f"- forward label: `{summary.get('forward_label_column')}`",
        f"- used_forward_return_in_ranking: `{summary['used_forward_return_in_ranking']}`",
        f"- production_activation_allowed: `{summary['production_activation_allowed']}`",
        "",
        "## Thesis Buckets",
        "",
    ]
    for bucket, count in (summary.get("thesis_bucket_counts") or {}).items():
        lines.append(f"- `{bucket}`: {count}")
    lines.extend(["", "## Top Full-Period Groups", ""])
    if stats.empty or "mean_forward_label" not in stats.columns:
        lines.append("No forward-label group ranking available.")
    else:
        ranked = stats[stats["split"] == "full"].copy()
        ranked["mean_forward_label"] = pd.to_numeric(ranked["mean_forward_label"], errors="coerce")
        ranked = ranked.sort_values(["mean_forward_label", "candidate_count"], ascending=[False, False]).head(12)
        for _, row in ranked.iterrows():
            lines.append(
                "- "
                f"{row['group_field']}=`{row['group_value']}` "
                f"candidates={int(row['candidate_count'])} "
                f"mean_forward={_safe_float(row.get('mean_forward_label')):.4f} "
                f"positive_rate={_safe_float(row.get('positive_rate_forward_label')):.2%}"
            )
    output_dir.joinpath("report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_screen(input_path: Path, output_dir: Path, *, oos_start: str, min_group_count: int, leader_quantile: float) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(input_path)
    enriched = enrich_leadership(df, leader_quantile)
    stats = build_group_stats(enriched, oos_start, min_group_count)
    summary = _summarize(enriched, stats, input_path=input_path, output_dir=output_dir, oos_start=oos_start, min_group_count=min_group_count)

    leader_cols = [
        col
        for col in [
            "rebalance_date",
            "ticker",
            "Name",
            "sector",
            "industry_group",
            "theme_phase_primary",
            "sector_thesis_bucket",
            "sector_thesis_risk_flags",
            "cross_sector_leadership_score",
            "cross_sector_leadership_candidate",
            "leader_tier",
            "rs_benchmark_3m",
            "rs_benchmark_6m",
            "relative_strength_composite",
            "period_forward_return",
        ]
        if col in enriched.columns
    ]
    enriched[leader_cols].to_csv(output_dir / "candidate_leaders.csv", index=False)
    stats.to_csv(output_dir / "group_leadership_stats.csv", index=False)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    write_report(summary, stats, output_dir)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Candidate or target book CSV.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--oos-start", default="2024-06-03")
    parser.add_argument("--min-group-count", type=int, default=3)
    parser.add_argument("--leader-quantile", type=float, default=0.70)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_screen(
        args.input,
        args.output_dir,
        oos_start=args.oos_start,
        min_group_count=args.min_group_count,
        leader_quantile=args.leader_quantile,
    )
    print(json.dumps({"status": summary["status"], "candidate_count": summary["candidate_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

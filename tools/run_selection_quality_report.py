#!/usr/bin/env python3
"""Measure whether selection scores predict future returns in replay data."""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/selection_quality"

FACTOR_COLUMNS = [
    "score_total",
    "score",
    "concentrated_score",
    "portfolio_monster_early_score",
    "portfolio_future_winner_engine_score",
    "portfolio_early_scout_engine_score",
    "leader_onset_score",
    "leader_onset_sec_v2_score",
    "leader_onset_sec_v3_score",
    "leader_onset_sec_v4_support_score",
    "early_evidence_score",
    "sec_combined_evidence_score",
    "sec_support_boost_score",
    "evidence_confidence_score",
    "sec_form4_open_market_buy_score",
    "sec_form4_cluster_buy_score",
    "sec_form4_ceo_cfo_buy_score",
    "sec_form4_net_buy_score",
    "sec_form4_sale_pressure_score",
    "sec_form4_sale_risk_score",
    "institutional_evidence_score",
    "institutional_evidence_confidence_score",
    "sec_13f_consensus_buy_score",
    "sec_13f_accumulation_score",
    "sec_13f_conviction_score",
    "sec_13f_new_position_score",
    "sec_13f_breadth_score",
    "sec_13f_smart_money_score",
    "sec_13f_value_delta_to_mcap",
    "relative_strength_composite",
    "oneil_leadership_score",
    "rs_acceleration_score",
    "industry_group_strength_score",
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def safe_float(value: Any, default: float = math.nan) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def load_candidate_book(latest_run: Path) -> pd.DataFrame:
    for rel in ["reports/candidate_replay_book.csv", "scored_latest.csv"]:
        frame = read_csv(latest_run / rel)
        if not frame.empty and "ticker" in frame.columns:
            return frame.copy()
    return pd.DataFrame()


def prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    d = frame.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    if "rebalance_date" not in d.columns:
        d["rebalance_date"] = "latest"
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("latest")
    return_col = "period_forward_return" if "period_forward_return" in d.columns else ""
    if not return_col:
        for col in ["forward_return", "next_return", "fwd_return"]:
            if col in d.columns:
                return_col = col
                break
    if not return_col:
        return pd.DataFrame()
    d["forward_return"] = pd.to_numeric(d[return_col], errors="coerce")
    d = d[d["ticker"].ne("") & d["forward_return"].notna()].copy()
    if "leader_onset_score" not in d.columns:
        components = {
            "portfolio_monster_early_score": 0.22,
            "portfolio_future_winner_engine_score": 0.18,
            "portfolio_early_scout_engine_score": 0.14,
            "rs_acceleration_score": 0.14,
            "h6_dynamic_leader_score": 0.12,
            "industry_group_strength_score": 0.08,
            "relative_strength_composite": 0.05,
            "oneil_leadership_score": 0.04,
            "governance_catalyst_score": 0.03,
        }
        score = pd.Series(0.0, index=d.index, dtype=float)
        used_weight = 0.0
        for col, weight in components.items():
            if col in d.columns:
                score += float(weight) * pd.to_numeric(d[col], errors="coerce").fillna(0.0).clip(0.0, 1.0)
                used_weight += float(weight)
        if "dollar_vol_20d" in d.columns:
            dollar_rank = d.groupby("rebalance_date")["dollar_vol_20d"].rank(pct=True).fillna(0.5)
            score += 0.05 * dollar_rank
            used_weight += 0.05
        d["leader_onset_score"] = (score / used_weight).fillna(0.0).clip(0.0, 1.0) if used_weight else 0.0
    for col in FACTOR_COLUMNS:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    return d


def factor_ic(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for factor in FACTOR_COLUMNS:
        if factor not in frame.columns:
            continue
        valid = frame[[factor, "forward_return", "rebalance_date"]].dropna()
        if len(valid) < 20:
            continue
        overall = valid[factor].corr(valid["forward_return"], method="spearman")
        by_month = []
        for _, group in valid.groupby("rebalance_date"):
            if len(group) >= 8 and group[factor].nunique(dropna=True) > 1:
                corr = group[factor].corr(group["forward_return"], method="spearman")
                if pd.notna(corr):
                    by_month.append(float(corr))
        rows.append(
            {
                "factor": factor,
                "rows": int(len(valid)),
                "months": int(valid["rebalance_date"].nunique()),
                "overall_spearman_ic": float(overall) if pd.notna(overall) else math.nan,
                "avg_monthly_spearman_ic": float(sum(by_month) / len(by_month)) if by_month else math.nan,
                "positive_ic_month_share": float(sum(1 for x in by_month if x > 0) / len(by_month)) if by_month else math.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("avg_monthly_spearman_ic", ascending=False, na_position="last") if rows else pd.DataFrame()


def topk_hit_rate(frame: pd.DataFrame, topks: list[int]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for factor in FACTOR_COLUMNS:
        if factor not in frame.columns:
            continue
        valid = frame[[factor, "forward_return", "rebalance_date"]].dropna()
        if valid.empty:
            continue
        for k in topks:
            month_rows = []
            for dt, group in valid.groupby("rebalance_date"):
                if len(group) < max(3, min(k, 5)):
                    continue
                universe_mean = float(group["forward_return"].mean())
                top = group.sort_values(factor, ascending=False).head(k)
                month_rows.append(
                    {
                        "rebalance_date": dt,
                        "top_mean_return": float(top["forward_return"].mean()),
                        "universe_mean_return": universe_mean,
                        "hit_rate_positive": float((top["forward_return"] > 0).mean()),
                        "hit_rate_above_universe": float((top["forward_return"] > universe_mean).mean()),
                    }
                )
            if not month_rows:
                continue
            rows.append(
                {
                    "factor": factor,
                    "top_k": k,
                    "months": len(month_rows),
                    "avg_top_mean_return": float(sum(r["top_mean_return"] for r in month_rows) / len(month_rows)),
                    "avg_universe_mean_return": float(sum(r["universe_mean_return"] for r in month_rows) / len(month_rows)),
                    "avg_excess_return": float(sum(r["top_mean_return"] - r["universe_mean_return"] for r in month_rows) / len(month_rows)),
                    "avg_hit_rate_positive": float(sum(r["hit_rate_positive"] for r in month_rows) / len(month_rows)),
                    "avg_hit_rate_above_universe": float(sum(r["hit_rate_above_universe"] for r in month_rows) / len(month_rows)),
                }
            )
    return pd.DataFrame(rows).sort_values("avg_excess_return", ascending=False, na_position="last") if rows else pd.DataFrame()


def decile_spread(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for factor in FACTOR_COLUMNS:
        if factor not in frame.columns:
            continue
        valid = frame[[factor, "forward_return", "rebalance_date"]].dropna()
        if len(valid) < 50 or valid[factor].nunique(dropna=True) < 5:
            continue
        month_spreads = []
        for _, group in valid.groupby("rebalance_date"):
            if len(group) < 20 or group[factor].nunique(dropna=True) < 5:
                continue
            try:
                decile = pd.qcut(group[factor].rank(method="first"), q=10, labels=False, duplicates="drop")
            except Exception:
                continue
            g = group.assign(decile=decile)
            top = g[g["decile"].eq(g["decile"].max())]["forward_return"].mean()
            bottom = g[g["decile"].eq(g["decile"].min())]["forward_return"].mean()
            if pd.notna(top) and pd.notna(bottom):
                month_spreads.append(float(top - bottom))
        rows.append(
            {
                "factor": factor,
                "months": len(month_spreads),
                "avg_top_minus_bottom_return": float(sum(month_spreads) / len(month_spreads)) if month_spreads else math.nan,
                "positive_spread_month_share": float(sum(1 for x in month_spreads if x > 0) / len(month_spreads)) if month_spreads else math.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("avg_top_minus_bottom_return", ascending=False, na_position="last") if rows else pd.DataFrame()


def sleeve_attribution(frame: pd.DataFrame) -> pd.DataFrame:
    sleeve_col = "portfolio_sleeve_label" if "portfolio_sleeve_label" in frame.columns else ""
    if not sleeve_col:
        return pd.DataFrame()
    d = frame.copy()
    d[sleeve_col] = d[sleeve_col].fillna("unassigned").astype(str)
    grouped = d.groupby(sleeve_col, dropna=False)["forward_return"].agg(["count", "mean", "median"]).reset_index()
    grouped = grouped.rename(columns={sleeve_col: "sleeve", "count": "rows", "mean": "avg_forward_return", "median": "median_forward_return"})
    return grouped.sort_values("avg_forward_return", ascending=False)


def missed_winner_onset(frame: pd.DataFrame, top_n: int) -> pd.DataFrame:
    d = frame.copy()
    if d.empty:
        return pd.DataFrame()
    latest_dates = pd.to_datetime(d["rebalance_date"], errors="coerce")
    if latest_dates.notna().any():
        d = d.loc[latest_dates.eq(latest_dates.max())].copy()
    d["monster_score"] = pd.to_numeric(
        d["portfolio_monster_early_score"] if "portfolio_monster_early_score" in d.columns else pd.Series(0.0, index=d.index),
        errors="coerce",
    ).fillna(0.0)
    score_source = "score_total" if "score_total" in d.columns else "score" if "score" in d.columns else ""
    d["score_proxy"] = pd.to_numeric(d[score_source] if score_source else pd.Series(0.0, index=d.index), errors="coerce").fillna(0.0)
    selected = pd.Series(False, index=d.index)
    for col in ["selected_main_current", "selected_concentrated_current", "in_main_portfolio", "in_concentrated_portfolio"]:
        if col in d.columns:
            selected = selected | d[col].astype(str).str.lower().isin(["true", "1", "yes"])
    d["selected_flag"] = selected
    d = d.sort_values("forward_return", ascending=False).head(int(top_n)).copy()
    keep = [
        "rebalance_date",
        "ticker",
        "Name",
        "sector",
        "portfolio_sleeve_label",
        "forward_return",
        "selected_flag",
        "monster_score",
        "score_proxy",
        "portfolio_candidate_gate_label",
        "portfolio_risk_entry_block_score",
        "portfolio_stale_mega_leader_score",
    ]
    return d[[col for col in keep if col in d.columns]]


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Selection Quality Report",
        "",
        "Research-only diagnostics. This report does not change portfolio weights.",
        "",
        f"- status: `{summary.get('status')}`",
        f"- rows: {summary.get('rows')}",
        f"- months: {summary.get('months')}",
        f"- best factor by IC: `{summary.get('best_factor_by_monthly_ic', '')}`",
        f"- best factor by top-k excess: `{summary.get('best_factor_by_topk_excess', '')}`",
        "",
        "Use this to decide whether weak performance is selection quality, broker conversion, or execution churn.",
        "",
    ]
    return "\n".join(lines)


def run(latest_run: str | Path = DEFAULT_LATEST_RUN, output_dir: str | Path = DEFAULT_OUTPUT_DIR, top_n: int = 30) -> dict[str, Any]:
    latest = repo_path(latest_run)
    out = repo_path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    frame = prepare_frame(load_candidate_book(latest))
    if frame.empty:
        payload = {
            "status": "blocked",
            "reason": "missing candidate replay book with forward returns",
            "latest_run": str(latest),
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(out / "selection_quality_summary.json", payload)
        (out / "selection_quality_report.md").write_text(render_report(payload), encoding="utf-8")
        return payload

    ic = factor_ic(frame)
    topk = topk_hit_rate(frame, [5, 10, 20])
    deciles = decile_spread(frame)
    sleeves = sleeve_attribution(frame)
    missed = missed_winner_onset(frame, top_n)
    ic.to_csv(out / "factor_ic_by_horizon.csv", index=False)
    topk.to_csv(out / "topk_forward_hit_rate.csv", index=False)
    deciles.to_csv(out / "score_decile_spread.csv", index=False)
    sleeves.to_csv(out / "sleeve_alpha_attribution.csv", index=False)
    missed.to_csv(out / "missed_winner_onset.csv", index=False)

    best_ic = str(ic.iloc[0]["factor"]) if not ic.empty else ""
    best_topk = str(topk.iloc[0]["factor"]) if not topk.empty else ""
    payload = {
        "status": "completed",
        "schema_version": "selection-quality-v1",
        "research_only": True,
        "production_activation_allowed": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest),
        "rows": int(len(frame)),
        "months": int(frame["rebalance_date"].nunique()),
        "best_factor_by_monthly_ic": best_ic,
        "best_factor_by_topk_excess": best_topk,
        "factor_count": int(len(ic)),
        "topk_rows": int(len(topk)),
        "decile_rows": int(len(deciles)),
        "sleeve_rows": int(len(sleeves)),
        "missed_winner_rows": int(len(missed)),
        "outputs": {
            "summary_json": str(out / "selection_quality_summary.json"),
            "factor_ic_by_horizon_csv": str(out / "factor_ic_by_horizon.csv"),
            "topk_forward_hit_rate_csv": str(out / "topk_forward_hit_rate.csv"),
            "score_decile_spread_csv": str(out / "score_decile_spread.csv"),
            "sleeve_alpha_attribution_csv": str(out / "sleeve_alpha_attribution.csv"),
            "missed_winner_onset_csv": str(out / "missed_winner_onset.csv"),
            "report_md": str(out / "selection_quality_report.md"),
        },
        "notes": [
            "Positive IC and top-k excess mean the score ranks are useful before broker conversion.",
            "If IC is strong but broker-ledger CAGR is weak, focus on execution churn, cash, and replacement-swap mechanics.",
            "If IC is weak, selection features or universe admission need priority before more execution tuning.",
        ],
    }
    write_json(out / "selection_quality_summary.json", payload)
    (out / "selection_quality_report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-n", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(args.latest_run, args.output_dir, args.top_n)
    print(json.dumps({"status": payload.get("status"), "rows": payload.get("rows")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Audit Form 4 and 13F shadow evidence before strategy integration.

This tool is deliberately research-only. It measures whether SEC evidence rows
were followed by better forward returns in the candidate replay book, and it
keeps Form 4 sales and 13F crowding as separate diagnostics instead of treating
them as automatic sell/avoid signals.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_sec_enriched_candidate_replay import (  # noqa: E402
    DEFAULT_13F,
    DEFAULT_CANDIDATE_BOOK,
    DEFAULT_FORM4,
    enrich_candidate_book,
    map_13f_tickers_from_candidates,
    market_cap_series,
    read_table,
    repo_path,
)
from tools.run_sec_institutional_signals import add_13f_position_deltas  # noqa: E402

DEFAULT_OUTPUT_DIR = "outputs/sec_evidence_signal_audit"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def forward_return_series(frame: pd.DataFrame) -> pd.Series:
    for col in ["period_forward_return", "forward_return", "next_return", "fwd_return"]:
        if col in frame.columns:
            return pd.to_numeric(frame[col], errors="coerce")
    return pd.Series(math.nan, index=frame.index, dtype=float)


def utc_end_of_day(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce").dt.normalize() + pd.Timedelta(hours=23, minutes=59, seconds=59)
    return dt.dt.tz_localize("UTC")


def prepare_audit_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns or "rebalance_date" not in frame.columns:
        return pd.DataFrame()
    d = frame.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["forward_return"] = forward_return_series(d)
    d = d[d["ticker"].ne("") & d["rebalance_date"].notna() & d["forward_return"].notna()].copy()
    if d.empty:
        return pd.DataFrame()
    d["universe_forward_return"] = d.groupby("rebalance_date")["forward_return"].transform("mean")
    d["excess_forward_return"] = d["forward_return"] - d["universe_forward_return"]
    d["market_cap_for_audit"] = market_cap_series(d)
    return d


def bucket_numeric(values: pd.Series, bins: list[float], labels: list[str]) -> pd.Series:
    out = pd.cut(pd.to_numeric(values, errors="coerce").fillna(0.0), bins=bins, labels=labels, include_lowest=True)
    return out.astype("string").fillna("missing").astype(str)


def add_signal_buckets(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    buy_value = numeric(d, "insider_buy_value", 0.0)
    sale_value = numeric(d, "insider_sale_value", 0.0)
    if "sec_form4_sale_risk_score" not in d.columns:
        sale_pressure = numeric(d, "sec_form4_sale_pressure_score", 0.0).clip(0.0, 1.0)
        d["sec_form4_sale_risk_score"] = np.where(buy_value <= 0.0, sale_pressure, 0.35 * sale_pressure)
    if "sec_form4_net_buy_score" not in d.columns:
        d["sec_form4_net_buy_score"] = ((buy_value - sale_value) / (buy_value + sale_value).clip(lower=1.0)).clip(0.0, 1.0)
    has_buy = buy_value > 0.0
    has_sale = sale_value > 0.0
    d["form4_buy_sell_bucket"] = np.select(
        [has_buy & ~has_sale, has_buy & has_sale, ~has_buy & has_sale],
        ["buy_only", "buy_and_sale", "sale_only"],
        default="no_form4",
    )
    d["form4_cluster_bucket"] = bucket_numeric(
        numeric(d, "sec_form4_cluster_buy_score", 0.0),
        [-0.001, 0.0, 0.25, 0.60, 1.0],
        ["none", "weak", "medium", "strong"],
    )
    d["form4_sale_risk_bucket"] = bucket_numeric(
        numeric(d, "sec_form4_sale_risk_score", 0.0),
        [-0.001, 0.0, 0.20, 0.60, 1.0],
        ["none", "low", "medium", "high"],
    )

    manager_count = numeric(d, "sec_13f_manager_count", 0.0)
    buying_count = numeric(d, "sec_13f_buying_manager_count", 0.0)
    value_delta = numeric(d, "sec_13f_value_delta_usd", 0.0)
    value_to_mcap = numeric(d, "sec_13f_value_delta_to_mcap", 0.0)
    has_13f = numeric(d, "institutional_evidence_confidence_score", 0.0) > 0.0
    if not has_13f.any() and "institutional_evidence_score" in d.columns:
        has_13f = (manager_count > 0.0) | (numeric(d, "institutional_evidence_score", 0.0) > 0.0)
    d["13f_flow_bucket"] = np.select(
        [has_13f & (value_delta > 0.0), has_13f & (value_delta < 0.0), has_13f],
        ["accumulation", "distribution", "flat"],
        default="no_13f",
    )
    d["13f_manager_count_bucket"] = bucket_numeric(
        manager_count,
        [-0.001, 0.0, 1.0, 4.0, 9.0, 999.0],
        ["0", "1", "2-4", "5-9", "10+"],
    )
    d["13f_buying_manager_bucket"] = bucket_numeric(
        buying_count,
        [-0.001, 0.0, 1.0, 3.0, 7.0, 999.0],
        ["0", "1", "2-3", "4-7", "8+"],
    )
    d["13f_value_delta_to_mcap_bucket"] = bucket_numeric(
        value_to_mcap.clip(lower=0.0),
        [-0.001, 0.0, 0.0025, 0.0100, 1.0],
        ["none", "small", "medium", "large"],
    )
    if "sec_13f_breadth_score" in d.columns:
        breadth = numeric(d, "sec_13f_breadth_score", 0.0).clip(0.0, 1.0)
    else:
        breadth = (manager_count / 12.0).clip(0.0, 1.0)
        d["sec_13f_breadth_score"] = breadth
    crowding = (manager_count - 20.0).clip(lower=0.0).div(25.0).clip(0.0, 1.0)
    d["sec_13f_crowding_score"] = crowding
    d["13f_breadth_crowding_bucket"] = np.select(
        [~has_13f, crowding >= 0.30, breadth >= 0.50, breadth > 0.0],
        ["no_13f", "overcrowded_risk", "broad_support", "narrow_support"],
        default="no_13f",
    )
    return d


def performance_by_bucket(frame: pd.DataFrame, bucket_col: str, score_col: str = "") -> pd.DataFrame:
    if frame.empty or bucket_col not in frame.columns:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for bucket, group in frame.groupby(bucket_col, dropna=False):
        payload: dict[str, Any] = {
            "bucket": str(bucket),
            "rows": int(len(group)),
            "months": int(group["rebalance_date"].nunique()),
            "tickers": int(group["ticker"].nunique()),
            "avg_forward_return": float(group["forward_return"].mean()),
            "median_forward_return": float(group["forward_return"].median()),
            "avg_universe_return": float(group["universe_forward_return"].mean()),
            "avg_excess_return": float(group["excess_forward_return"].mean()),
            "hit_rate_positive": float((group["forward_return"] > 0.0).mean()),
            "hit_rate_excess_positive": float((group["excess_forward_return"] > 0.0).mean()),
        }
        if score_col and score_col in group.columns:
            payload["avg_score"] = float(pd.to_numeric(group[score_col], errors="coerce").fillna(0.0).mean())
        rows.append(payload)
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["avg_excess_return", "rows"], ascending=[False, False])
    return out


def form4_owner_activity(form4: pd.DataFrame) -> pd.DataFrame:
    if form4.empty:
        return pd.DataFrame()
    d = form4.copy()
    d["ticker"] = d.get("issuer_ticker", "").astype(str).str.upper().str.strip()
    d["owner_cik"] = d.get("reporting_owner_cik", "").astype(str).str.strip()
    d["owner_name"] = d.get("reporting_owner_name", "").astype(str).str.strip()
    d["officer_title"] = d.get("officer_title", "").astype(str).str.strip()
    d["transaction_code"] = d.get("transaction_code", "").astype(str).str.upper().str.strip()
    d["transaction_value_num"] = numeric(d, "transaction_value", 0.0).clip(lower=0.0)
    d = d[d["ticker"].ne("") & d["owner_cik"].ne("")].copy()
    if d.empty:
        return pd.DataFrame()
    grouped = (
        d.groupby(["ticker", "owner_cik", "owner_name", "officer_title"], dropna=False)
        .agg(
            transactions=("transaction_code", "size"),
            buy_transactions=("transaction_code", lambda s: int(s.eq("P").sum())),
            sale_transactions=("transaction_code", lambda s: int(s.eq("S").sum())),
            buy_value=("transaction_value_num", lambda s: float(s[d.loc[s.index, "transaction_code"].eq("P")].sum())),
            sale_value=("transaction_value_num", lambda s: float(s[d.loc[s.index, "transaction_code"].eq("S")].sum())),
        )
        .reset_index()
    )
    grouped["net_buy_value"] = grouped["buy_value"] - grouped["sale_value"]
    return grouped.sort_values(["net_buy_value", "buy_value"], ascending=False)


def manager_alpha(
    candidates: pd.DataFrame,
    holdings_13f: pd.DataFrame,
    *,
    lookback_days: int,
    min_observations: int,
) -> pd.DataFrame:
    if candidates.empty or holdings_13f.empty:
        return pd.DataFrame()
    mapped = map_13f_tickers_from_candidates(holdings_13f, candidates)
    holdings = add_13f_position_deltas(mapped)
    if holdings.empty:
        return pd.DataFrame()
    if "manager_name" not in holdings.columns:
        holdings["manager_name"] = ""
    holdings = holdings[holdings["ticker"].astype(str).str.strip().ne("")].copy()
    if holdings.empty:
        return pd.DataFrame()

    cand = candidates[["rebalance_date", "ticker", "forward_return", "excess_forward_return", "market_cap_for_audit"]].copy()
    cand["candidate_row_id"] = np.arange(len(cand))
    cand["rebalance_asof_ts"] = utc_end_of_day(cand["rebalance_date"])
    merged = cand.merge(holdings, on="ticker", how="inner", suffixes=("_candidate", "_13f"))
    if merged.empty:
        return pd.DataFrame()
    start = merged["rebalance_asof_ts"] - pd.Timedelta(days=int(lookback_days))
    mask = (
        merged["available_from_ts"].notna()
        & (merged["available_from_ts"] <= merged["rebalance_asof_ts"])
        & (merged["available_from_ts"] >= start)
    )
    merged = merged[mask].copy()
    if merged.empty:
        return pd.DataFrame()
    merged = merged.sort_values(["candidate_row_id", "manager_cik", "available_from_ts", "report_period_ts"])
    merged = merged.drop_duplicates(["candidate_row_id", "manager_cik"], keep="last")
    mcap = pd.to_numeric(merged["market_cap_for_audit"], errors="coerce").replace(0.0, np.nan)
    merged["market_value_delta_to_mcap"] = (pd.to_numeric(merged["market_value_delta_usd"], errors="coerce") / mcap).fillna(0.0)
    rows: list[dict[str, Any]] = []
    for (manager_cik, manager_name), group in merged.groupby(["manager_cik", "manager_name"], dropna=False):
        observations = int(len(group))
        avg_excess = float(group["excess_forward_return"].mean())
        hit_rate = float((group["excess_forward_return"] > 0.0).mean())
        flow_score = float(np.clip(0.5 + group["market_value_delta_to_mcap"].mean() * 25.0, 0.0, 1.0))
        return_score = float(np.clip(0.5 + avg_excess * 5.0, 0.0, 1.0))
        sample_score = float(np.clip(observations / 50.0, 0.0, 1.0))
        quality = 0.45 * return_score + 0.25 * hit_rate + 0.15 * flow_score + 0.15 * sample_score
        rows.append(
            {
                "manager_cik": manager_cik,
                "manager_name": manager_name,
                "observations": observations,
                "unique_tickers": int(group["ticker"].nunique()),
                "buying_observations": int((pd.to_numeric(group["shares_delta"], errors="coerce") > 0.0).sum()),
                "new_position_observations": int(group["new_position"].astype(bool).sum()),
                "avg_forward_return": float(group["forward_return"].mean()),
                "avg_excess_return": avg_excess,
                "hit_rate_excess_positive": hit_rate,
                "avg_market_value_delta_usd": float(pd.to_numeric(group["market_value_delta_usd"], errors="coerce").mean()),
                "avg_market_value_delta_to_mcap": float(group["market_value_delta_to_mcap"].mean()),
                "avg_manager_position_weight": float(pd.to_numeric(group["manager_position_weight"], errors="coerce").mean()),
                "avg_manager_conviction_rank": float(pd.to_numeric(group["manager_conviction_rank"], errors="coerce").mean()),
                "manager_quality_score": float(quality) if observations >= int(min_observations) else math.nan,
                "research_only": True,
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["manager_quality_score", "observations", "avg_excess_return"], ascending=[False, False, False])
    return out


def render_report(summary: dict[str, Any], form4_perf: pd.DataFrame, inst_perf: pd.DataFrame, managers: pd.DataFrame) -> str:
    lines = [
        "# SEC Evidence Signal Audit",
        "",
        "Research-only audit for Form 4 and 13F evidence. Production `score_total` is not changed.",
        "",
        f"- candidate rows: {summary.get('candidate_rows', 0)}",
        f"- Form 4 evidence rows: {summary.get('rows_with_form4_evidence', 0)}",
        f"- 13F evidence rows: {summary.get('rows_with_13f_evidence', 0)}",
        f"- manager alpha rows: {summary.get('manager_alpha_rows', 0)}",
        "",
        "## Policy Takeaway",
        "",
        "- Form 4 code `P` remains the buy trigger.",
        "- Form 4 sales stay as a light risk flag, not an automatic sell signal.",
        "- 13F manager breadth and accumulation are support signals; overcrowding risk is measured separately.",
        "- SEC evidence should be used as an overlay on future-winner / market-confirmed selectors, not as a standalone model.",
        "",
    ]
    if not form4_perf.empty:
        lines.extend(["## Form 4 Buy/Sell Buckets", "", "| bucket | rows | avg excess | hit rate |", "| --- | ---: | ---: | ---: |"])
        for _, row in form4_perf.head(8).iterrows():
            lines.append(
                f"| {row.get('bucket')} | {int(row.get('rows', 0))} | {float(row.get('avg_excess_return', 0.0)):.3%} | {float(row.get('hit_rate_excess_positive', 0.0)):.1%} |"
            )
        lines.append("")
    if not inst_perf.empty:
        lines.extend(["## 13F Flow Buckets", "", "| bucket | rows | avg excess | hit rate |", "| --- | ---: | ---: | ---: |"])
        for _, row in inst_perf.head(8).iterrows():
            lines.append(
                f"| {row.get('bucket')} | {int(row.get('rows', 0))} | {float(row.get('avg_excess_return', 0.0)):.3%} | {float(row.get('hit_rate_excess_positive', 0.0)):.1%} |"
            )
        lines.append("")
    if not managers.empty:
        lines.extend(["## Top 13F Managers", "", "| manager | obs | avg excess | quality |", "| --- | ---: | ---: | ---: |"])
        for _, row in managers.head(10).iterrows():
            quality = row.get("manager_quality_score")
            quality_text = "" if pd.isna(quality) else f"{float(quality):.3f}"
            lines.append(
                f"| {row.get('manager_name', '')} | {int(row.get('observations', 0))} | {float(row.get('avg_excess_return', 0.0)):.3%} | {quality_text} |"
            )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    candidate_path = repo_path(args.candidate_book)
    form4_path = repo_path(args.form4)
    institutional_13f_path = repo_path(args.institutional_13f)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = read_table(candidate_path)
    form4 = read_table(form4_path)
    holdings_13f = read_table(institutional_13f_path)
    if bool(getattr(args, "already_enriched", False)):
        enriched = candidates
    else:
        enriched = enrich_candidate_book(
            candidates,
            form4,
            holdings_13f,
            lookback_days=int(args.form4_lookback_days),
            institutional_lookback_days=int(args.institutional_lookback_days),
        )
    audit = add_signal_buckets(prepare_audit_frame(enriched))

    form4_perf = performance_by_bucket(audit, "form4_buy_sell_bucket", "early_evidence_score")
    form4_sale_perf = performance_by_bucket(audit, "form4_sale_risk_bucket", "sec_form4_sale_risk_score")
    form4_cluster_perf = performance_by_bucket(audit, "form4_cluster_bucket", "sec_form4_cluster_buy_score")
    inst_flow_perf = performance_by_bucket(audit, "13f_flow_bucket", "institutional_evidence_score")
    inst_manager_perf = performance_by_bucket(audit, "13f_manager_count_bucket", "sec_13f_manager_count")
    inst_breadth_perf = performance_by_bucket(audit, "13f_breadth_crowding_bucket", "sec_13f_breadth_score")
    owners = form4_owner_activity(form4)
    managers = manager_alpha(
        audit,
        holdings_13f,
        lookback_days=int(args.institutional_lookback_days),
        min_observations=int(args.min_manager_observations),
    )

    form4_perf.to_csv(output_dir / "form4_buy_sell_performance.csv", index=False)
    form4_sale_perf.to_csv(output_dir / "form4_sale_risk_performance.csv", index=False)
    form4_cluster_perf.to_csv(output_dir / "form4_cluster_performance.csv", index=False)
    inst_flow_perf.to_csv(output_dir / "13f_flow_performance.csv", index=False)
    inst_manager_perf.to_csv(output_dir / "13f_manager_count_performance.csv", index=False)
    inst_breadth_perf.to_csv(output_dir / "13f_breadth_crowding_performance.csv", index=False)
    owners.to_csv(output_dir / "form4_owner_activity.csv", index=False)
    managers.to_csv(output_dir / "13f_manager_alpha.csv", index=False)

    summary = {
        "status": "completed" if not audit.empty else "blocked",
        "reason": "" if not audit.empty else "missing candidate replay rows with forward returns",
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "candidate_book": str(candidate_path),
        "form4_transactions": str(form4_path),
        "institutional_13f_holdings": str(institutional_13f_path),
        "candidate_rows": int(len(audit)),
        "rows_with_form4_evidence": int((numeric(audit, "evidence_confidence_score", 0.0) > 0.0).sum()) if not audit.empty else 0,
        "rows_with_13f_evidence": int((numeric(audit, "institutional_evidence_confidence_score", 0.0) > 0.0).sum())
        if not audit.empty
        else 0,
        "manager_alpha_rows": int(len(managers)),
        "form4_policy": "P purchases are trigger candidates; S sales are light risk flags only.",
        "institutional_policy": "13F accumulation and breadth support existing selectors; overcrowding risk is separate.",
        "outputs": {
            "form4_buy_sell_performance": str(output_dir / "form4_buy_sell_performance.csv"),
            "form4_sale_risk_performance": str(output_dir / "form4_sale_risk_performance.csv"),
            "13f_flow_performance": str(output_dir / "13f_flow_performance.csv"),
            "13f_manager_alpha": str(output_dir / "13f_manager_alpha.csv"),
            "report": str(output_dir / "report.md"),
        },
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, form4_perf, inst_flow_perf, managers), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "candidate_rows": summary["candidate_rows"]}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--form4", default=DEFAULT_FORM4)
    parser.add_argument("--institutional-13f", default=DEFAULT_13F)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--form4-lookback-days", type=int, default=90)
    parser.add_argument("--institutional-lookback-days", type=int, default=210)
    parser.add_argument("--already-enriched", action="store_true")
    parser.add_argument("--min-manager-observations", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

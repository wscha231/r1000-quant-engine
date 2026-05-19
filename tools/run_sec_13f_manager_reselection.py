#!/usr/bin/env python3
"""Build a semiannual research-only SEC 13F manager reselection candidate list.

This tool does not overwrite the active manager universe. It combines the
reviewed seed list with repo-learned 13F manager-alpha diagnostics and latest
13F AUM/coverage so the next refresh can add or retire managers from evidence
instead of a static hand-picked list.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_sec_13f_manager_universe import DEFAULT_MANAGER_UNIVERSE, load_manager_universe  # noqa: E402
from tools.run_sec_submissions_collector import cik10, repo_path  # noqa: E402

DEFAULT_HOLDINGS = "data_pit/sec/institutional_13f_holdings.parquet"
DEFAULT_MANAGER_ALPHA = "outputs/sec_evidence_signal_audit/13f_manager_alpha.csv"
DEFAULT_OUTPUT_DIR = "outputs/sec_institutional_signals"


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def safe_num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        out = float(str(value).replace(",", "").replace("%", ""))
        return out if math.isfinite(out) else default
    except Exception:
        return default


def minmax(series: pd.Series, *, default: float = 0.0) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").fillna(default).astype(float)
    lo = float(s.min()) if len(s) else 0.0
    hi = float(s.max()) if len(s) else 0.0
    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        return pd.Series(default, index=s.index, dtype=float)
    return ((s - lo) / (hi - lo)).clip(0.0, 1.0)


def numeric_column(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default).astype(float)


def holdings_manager_stats(holdings: pd.DataFrame) -> pd.DataFrame:
    if holdings.empty:
        return pd.DataFrame(columns=["manager_cik"])
    d = holdings.copy()
    if "manager_name" not in d.columns:
        d["manager_name"] = ""
    if "issuer_name" not in d.columns:
        d["issuer_name"] = d.get("ticker_mapped", "")
    d = d[d["manager_cik"].astype(str).str.strip().ne("")].copy()
    if d.empty:
        return pd.DataFrame(columns=["manager_cik"])
    d["manager_cik"] = d["manager_cik"].map(cik10)
    d["report_period_ts"] = pd.to_datetime(d.get("report_period"), errors="coerce").dt.normalize()
    d["available_from_ts"] = pd.to_datetime(d.get("available_from"), errors="coerce", utc=True)
    d["market_value_usd"] = pd.to_numeric(d.get("market_value_usd", 0.0), errors="coerce").fillna(0.0).clip(lower=0.0)
    d = d[d["report_period_ts"].notna()].copy()
    if d.empty:
        return pd.DataFrame(columns=["manager_cik"])
    d = d.sort_values(["manager_cik", "issuer_name", "report_period_ts", "available_from_ts"])
    d = d.drop_duplicates(["manager_cik", "issuer_name", "report_period_ts"], keep="last")
    latest_period = d.groupby("manager_cik")["report_period_ts"].transform("max")
    latest = d[d["report_period_ts"].eq(latest_period)].copy()
    total = latest.groupby("manager_cik")["market_value_usd"].transform("sum").replace(0.0, pd.NA)
    latest["manager_position_weight"] = (latest["market_value_usd"] / total).fillna(0.0).clip(0.0, 1.0)
    grouped = (
        latest.groupby("manager_cik", dropna=False)
        .agg(
            manager_name_holdings=("manager_name", lambda s: next((str(v) for v in s if str(v).strip()), "")),
            latest_report_period=("report_period_ts", "max"),
            latest_available_from=("available_from_ts", "max"),
            latest_13f_aum_usd=("market_value_usd", "sum"),
            latest_holdings_count=("issuer_name", "nunique"),
            latest_top_position_weight=("manager_position_weight", "max"),
        )
        .reset_index()
    )
    return grouped


def build_candidates(
    universe: pd.DataFrame,
    manager_alpha: pd.DataFrame,
    holdings: pd.DataFrame,
    *,
    max_managers: int,
    min_observations: int,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if not universe.empty:
        base = universe.copy()
        base["manager_cik"] = base["cik10"].map(cik10)
        base["manager_name_seed"] = base.get("manager_name", "").astype(str)
        base["label"] = base.get("label", "").astype(str).str.upper().str.strip()
        frames.append(base)
    else:
        base = pd.DataFrame(columns=["manager_cik", "manager_name_seed", "label"])
        frames.append(base)

    stats = holdings_manager_stats(holdings)
    alpha = manager_alpha.copy() if not manager_alpha.empty else pd.DataFrame(columns=["manager_cik"])
    if not alpha.empty:
        alpha["manager_cik"] = alpha["manager_cik"].map(cik10)
    known = pd.concat([frame[["manager_cik"]] for frame in [base, stats, alpha] if "manager_cik" in frame.columns], ignore_index=True)
    known = known.dropna().drop_duplicates()
    if known.empty:
        return pd.DataFrame()
    out = known.merge(base, on="manager_cik", how="left")
    out = out.merge(stats, on="manager_cik", how="left")
    out = out.merge(alpha, on="manager_cik", how="left", suffixes=("", "_alpha"))
    out["manager_name"] = (
        out.get("manager_name_seed", pd.Series("", index=out.index)).fillna("").astype(str).str.strip()
    )
    if "manager_name_alpha" in out.columns:
        out.loc[out["manager_name"].eq(""), "manager_name"] = out.loc[out["manager_name"].eq(""), "manager_name_alpha"].fillna("")
    if "manager_name_holdings" in out.columns:
        out.loc[out["manager_name"].eq(""), "manager_name"] = out.loc[out["manager_name"].eq(""), "manager_name_holdings"].fillna("")
    out.loc[out["manager_name"].eq(""), "manager_name"] = "CIK" + out.loc[out["manager_name"].eq(""), "manager_cik"].astype(str)
    out["observations"] = numeric_column(out, "observations", 0.0)
    out["hit_rate_excess_positive"] = numeric_column(out, "hit_rate_excess_positive", 0.0).clip(0.0, 1.0)
    out["manager_quality_score"] = numeric_column(out, "manager_quality_score", 0.0).clip(0.0, 1.0)
    if "latest_13f_aum_usd" not in out.columns and "aum_13f_usd_num" in out.columns:
        out["latest_13f_aum_usd"] = out["aum_13f_usd_num"]
    if "latest_holdings_count" not in out.columns and "holdings_count" in out.columns:
        out["latest_holdings_count"] = out["holdings_count"]
    out["latest_13f_aum_usd"] = numeric_column(out, "latest_13f_aum_usd", 0.0)
    out["latest_holdings_count"] = numeric_column(out, "latest_holdings_count", 0.0)
    out["latest_top_position_weight"] = numeric_column(out, "latest_top_position_weight", 0.0).clip(0.0, 1.0)
    out["user_priority_num"] = numeric_column(out, "user_priority_num", 999.0)
    out["active_flag"] = out.get("active_flag", False).fillna(False).astype(bool) if "active_flag" in out.columns else False
    out["verified_flag"] = out.get("verified_flag", False).fillna(False).astype(bool) if "verified_flag" in out.columns else False

    out["sample_score"] = (out["observations"] / max(float(min_observations), 1.0)).clip(0.0, 1.0)
    out["aum_score"] = minmax(out["latest_13f_aum_usd"].map(lambda v: math.log1p(max(float(v), 0.0))))
    out["coverage_score"] = minmax(out["latest_holdings_count"])
    out["concentration_score"] = out["latest_top_position_weight"].clip(0.0, 1.0)
    out["seed_priority_score"] = (1.0 - (out["user_priority_num"].clip(1.0, 100.0) - 1.0) / 99.0).clip(0.0, 1.0)
    out["manager_reselection_score"] = (
        0.40 * out["manager_quality_score"]
        + 0.18 * out["aum_score"]
        + 0.14 * out["hit_rate_excess_positive"]
        + 0.12 * out["sample_score"]
        + 0.08 * out["concentration_score"]
        + 0.05 * out["coverage_score"]
        + 0.03 * out["seed_priority_score"]
    ).clip(0.0, 1.0)
    out["reselection_action"] = "watch"
    out.loc[out["manager_reselection_score"].ge(0.62) & out["observations"].ge(min_observations), "reselection_action"] = "candidate_include"
    out.loc[out["active_flag"] & out["verified_flag"] & out["manager_reselection_score"].lt(0.25), "reselection_action"] = "candidate_review_or_retire"
    out.loc[out["active_flag"] & out["verified_flag"] & out["manager_reselection_score"].ge(0.25), "reselection_action"] = "keep_active"
    out["research_only"] = True
    out["production_activation_allowed"] = False
    out = out.sort_values(
        ["manager_reselection_score", "manager_quality_score", "latest_13f_aum_usd", "observations"],
        ascending=[False, False, False, False],
    )
    if max_managers > 0:
        out = out.head(int(max_managers)).copy()
    keep_cols = [
        "manager_cik",
        "label",
        "manager_name",
        "reselection_action",
        "manager_reselection_score",
        "manager_quality_score",
        "observations",
        "hit_rate_excess_positive",
        "avg_excess_return",
        "latest_13f_aum_usd",
        "latest_holdings_count",
        "latest_top_position_weight",
        "latest_report_period",
        "latest_available_from",
        "active_flag",
        "verified_flag",
        "user_priority_num",
        "research_only",
        "production_activation_allowed",
    ]
    for col in keep_cols:
        if col not in out.columns:
            out[col] = ""
    return out[keep_cols]


def render_report(summary: dict[str, Any], candidates: pd.DataFrame) -> str:
    lines = [
        "# SEC 13F Manager Reselection",
        "",
        "Research-only semiannual manager universe review. The active manager CSV is not overwritten.",
        "",
        f"- status: {summary.get('status')}",
        f"- candidates: {summary.get('candidate_rows', 0)}",
        f"- selected include candidates: {summary.get('candidate_include_count', 0)}",
        f"- next review due: {summary.get('next_review_due')}",
        "",
        "## Top Candidates",
        "",
        "| manager | action | score | quality | obs | hit rate | latest AUM |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, row in candidates.head(25).iterrows():
        lines.append(
            "| {name} | {action} | {score:.3f} | {quality:.3f} | {obs:.0f} | {hit:.1%} | ${aum:,.0f} |".format(
                name=row.get("manager_name", ""),
                action=row.get("reselection_action", ""),
                score=safe_num(row.get("manager_reselection_score")),
                quality=safe_num(row.get("manager_quality_score")),
                obs=safe_num(row.get("observations")),
                hit=safe_num(row.get("hit_rate_excess_positive")),
                aum=safe_num(row.get("latest_13f_aum_usd")),
            )
        )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = repo_path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    universe = load_manager_universe(repo_path(args.manager_universe), extra=str(args.extra or ""))
    manager_alpha = read_table(repo_path(args.manager_alpha))
    holdings = read_table(repo_path(args.holdings))
    candidates = build_candidates(
        universe,
        manager_alpha,
        holdings,
        max_managers=int(args.max_managers),
        min_observations=int(args.min_observations),
    )
    candidates_csv = out_dir / "manager_reselection_candidates.csv"
    candidates.to_csv(candidates_csv, index=False)
    candidate_review_csv = repo_path(args.output_candidate_universe)
    if str(args.output_candidate_universe).strip():
        candidate_review_csv.parent.mkdir(parents=True, exist_ok=True)
        candidates.to_csv(candidate_review_csv, index=False)
    today = date.today()
    next_review = today + timedelta(days=int(args.review_interval_days))
    summary = {
        "status": "completed" if not candidates.empty else "blocked",
        "reason": "" if not candidates.empty else "missing manager universe, manager alpha, and 13F holdings evidence",
        "research_only": True,
        "production_activation_allowed": False,
        "active_manager_universe_changed": False,
        "review_interval_days": int(args.review_interval_days),
        "next_review_due": next_review.isoformat(),
        "candidate_rows": int(len(candidates)),
        "candidate_include_count": int((candidates.get("reselection_action", pd.Series(dtype=str)) == "candidate_include").sum())
        if not candidates.empty
        else 0,
        "manager_universe": str(repo_path(args.manager_universe)),
        "manager_alpha": str(repo_path(args.manager_alpha)),
        "holdings": str(repo_path(args.holdings)),
        "outputs": {
            "manager_reselection_candidates": str(candidates_csv),
            "manager_review_candidate_universe": str(candidate_review_csv) if str(args.output_candidate_universe).strip() else "",
            "report": str(out_dir / "manager_reselection_report.md"),
        },
    }
    write_json(out_dir / "manager_reselection_summary.json", summary)
    (out_dir / "manager_reselection_report.md").write_text(render_report(summary, candidates), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "candidate_rows": summary["candidate_rows"]}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manager-universe", default=DEFAULT_MANAGER_UNIVERSE)
    parser.add_argument("--manager-alpha", default=DEFAULT_MANAGER_ALPHA)
    parser.add_argument("--holdings", default=DEFAULT_HOLDINGS)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-candidate-universe", default="research/sec_13f_manager_universe_20260519/managers_candidate.csv")
    parser.add_argument("--extra", default="")
    parser.add_argument("--max-managers", type=int, default=40)
    parser.add_argument("--min-observations", type=int, default=10)
    parser.add_argument("--review-interval-days", type=int, default=183)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

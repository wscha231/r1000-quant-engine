#!/usr/bin/env python3
"""Audit current selection, omitted leaders, and historical holding continuity.

This research-only sidecar answers one operational question after each full
rebuild:

    Why is this name in the current portfolio, and why did strong alternatives
    stay out?

It does not change production weights. It joins the latest candidate book,
current main/concentrated portfolios, and monthly holding history so selection
debugging is not based on the current portfolio CSV alone.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from historical_replay_lib import read_table, repo_path, safe_float, write_json, write_text


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/selection_audit"
CASH_TICKER = "CASH"

PRESSURE_WEIGHTS = {
    "score": 0.25,
    "concentrated_score": 0.25,
    "portfolio_monster_early_score": 0.20,
    "portfolio_future_winner_engine_score": 0.10,
    "portfolio_early_scout_engine_score": 0.08,
    "relative_strength_composite": 0.07,
    "oneil_leadership_score": 0.05,
}

AUDIT_COLUMNS = [
    "ticker",
    "Name",
    "sector",
    "industry_group",
    "source_universe",
    "selected_main_current",
    "selected_concentrated_current",
    "current_main_weight",
    "current_concentrated_weight",
    "decision_bucket",
    "selection_pressure_score",
    "score",
    "concentrated_score",
    "portfolio_monster_early_score",
    "portfolio_future_winner_engine_score",
    "portfolio_early_scout_engine_score",
    "relative_strength_composite",
    "oneil_leadership_score",
    "portfolio_candidate_minimum_pass",
    "portfolio_candidate_gate_label",
    "portfolio_risk_entry_block_score",
    "portfolio_stale_mega_leader_score",
    "portfolio_stale_leader_reason",
    "portfolio_defensive_rotation_action",
    "entry_quality_score",
    "concentrated_entry_quality_gate_pass",
    "selection_confirmation_score",
    "trend_template_full",
    "breakout_setup_quality_score",
    "price_above_ma50",
    "price_above_ma200",
    "market_cap_live",
    "dollar_vol_20d",
    "sales_growth_yoy",
    "eps_growth_yoy",
    "revenues_ttm",
    "months_held_main",
    "first_held_main",
    "last_held_main",
    "months_held_concentrated",
    "first_held_concentrated",
    "last_held_concentrated",
]


def _normalize_ticker_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.upper().str.strip()


def _with_ticker(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["ticker"] = _normalize_ticker_series(out["ticker"])
    out = out[(out["ticker"] != "") & (out["ticker"] != CASH_TICKER)].copy()
    return out


def _latest_candidates(latest_run: Path) -> pd.DataFrame:
    for rel in ("reports/candidate_replay_book.csv", "scored_latest.csv"):
        frame = _with_ticker(read_table(latest_run / rel))
        if frame.empty:
            continue
        if "rebalance_date" in frame.columns:
            dates = pd.to_datetime(frame["rebalance_date"], errors="coerce")
            if dates.notna().any():
                latest_date = dates.max()
                frame = frame.loc[dates.eq(latest_date)].copy()
        return frame.drop_duplicates("ticker", keep="first").copy()
    return pd.DataFrame()


def _current_weights(path: Path) -> dict[str, float]:
    frame = _with_ticker(read_table(path))
    if frame.empty or "weight" not in frame.columns:
        return {}
    weights = pd.to_numeric(frame["weight"], errors="coerce").fillna(0.0)
    return {
        str(ticker): float(weight)
        for ticker, weight in zip(frame["ticker"].astype(str), weights)
        if float(weight) > 1e-10
    }


def _history_summary(path: Path, prefix: str) -> pd.DataFrame:
    frame = _with_ticker(read_table(path))
    if frame.empty:
        return pd.DataFrame(columns=["ticker", f"months_held_{prefix}", f"first_held_{prefix}", f"last_held_{prefix}"])
    if "rebalance_date" not in frame.columns:
        return pd.DataFrame(columns=["ticker", f"months_held_{prefix}", f"first_held_{prefix}", f"last_held_{prefix}"])
    frame["rebalance_date"] = pd.to_datetime(frame["rebalance_date"], errors="coerce")
    frame = frame.dropna(subset=["rebalance_date"])
    if frame.empty:
        return pd.DataFrame(columns=["ticker", f"months_held_{prefix}", f"first_held_{prefix}", f"last_held_{prefix}"])
    frame["_weight"] = pd.to_numeric(frame.get("weight", 0.0), errors="coerce").fillna(0.0)
    frame = frame[frame["_weight"] > 1e-10].copy()
    if frame.empty:
        return pd.DataFrame(columns=["ticker", f"months_held_{prefix}", f"first_held_{prefix}", f"last_held_{prefix}"])
    grouped = frame.groupby("ticker", dropna=False).agg(
        **{
            f"months_held_{prefix}": ("rebalance_date", "nunique"),
            f"first_held_{prefix}": ("rebalance_date", "min"),
            f"last_held_{prefix}": ("rebalance_date", "max"),
            f"avg_weight_{prefix}": ("_weight", "mean"),
            f"max_weight_{prefix}": ("_weight", "max"),
        }
    ).reset_index()
    for col in (f"first_held_{prefix}", f"last_held_{prefix}"):
        grouped[col] = pd.to_datetime(grouped[col], errors="coerce").dt.strftime("%Y-%m-%d")
    return grouped


def _numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default).astype(float)


def _boolish(value: Any, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return default


def _add_pressure_score(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    pressure = pd.Series(0.0, index=out.index, dtype=float)
    for col, weight in PRESSURE_WEIGHTS.items():
        values = _numeric(out, col, 0.0)
        if values.nunique(dropna=True) <= 1:
            pct = pd.Series(0.0, index=out.index, dtype=float)
        else:
            pct = values.rank(pct=True, method="average").fillna(0.0)
        pressure += float(weight) * pct
    out["selection_pressure_score"] = pressure.clip(lower=0.0, upper=1.0)
    return out


def _decision_bucket(row: pd.Series) -> str:
    if bool(row.get("selected_main_current")) and bool(row.get("selected_concentrated_current")):
        return "selected_both"
    if bool(row.get("selected_concentrated_current")):
        return "selected_concentrated"
    if bool(row.get("selected_main_current")):
        stale = safe_float(row.get("portfolio_stale_mega_leader_score"), 0.0)
        if stale >= 0.55:
            return "selected_main_stale_review"
        return "selected_main"
    if not _boolish(row.get("portfolio_candidate_minimum_pass"), default=True):
        return "omitted_candidate_gate_block"
    if safe_float(row.get("portfolio_risk_entry_block_score"), 0.0) >= 0.55:
        return "omitted_risk_entry_block"
    if safe_float(row.get("portfolio_stale_mega_leader_score"), 0.0) >= 0.55:
        return "omitted_stale_leader"
    if safe_float(row.get("portfolio_monster_early_score"), 0.0) >= 0.62:
        return "omitted_monster_candidate"
    if safe_float(row.get("concentrated_score"), 0.0) >= 0.0 and safe_float(row.get("selection_pressure_score"), 0.0) >= 0.85:
        return "omitted_high_pressure_or_cap"
    return "not_selected_low_priority"


def run(latest_run: Path, output_dir: Path, top_n: int = 100) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = _latest_candidates(latest_run)
    if candidates.empty:
        payload = {
            "status": "blocked",
            "reason": "missing reports/candidate_replay_book.csv and scored_latest.csv",
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "selection_audit_summary.json", payload)
        write_text(output_dir / "selection_audit_report.md", "# Selection Audit\n\nBlocked: missing candidate data.\n")
        return payload

    main_w = _current_weights(latest_run / "portfolio_latest.csv")
    conc_w = _current_weights(latest_run / "concentrated_portfolio_latest.csv")
    main_hist = _history_summary(latest_run / "reports" / "main_monthly_weights.csv", "main")
    conc_hist = _history_summary(latest_run / "reports" / "concentrated_strategy_holdings.csv", "concentrated")

    audit = candidates.copy()
    audit["selected_main_current"] = audit["ticker"].isin(main_w)
    audit["selected_concentrated_current"] = audit["ticker"].isin(conc_w)
    audit["current_main_weight"] = audit["ticker"].map(main_w).fillna(0.0)
    audit["current_concentrated_weight"] = audit["ticker"].map(conc_w).fillna(0.0)
    audit = _add_pressure_score(audit)
    if not main_hist.empty:
        audit = audit.merge(main_hist, on="ticker", how="left")
    if not conc_hist.empty:
        audit = audit.merge(conc_hist, on="ticker", how="left")
    for col in ("months_held_main", "months_held_concentrated"):
        if col not in audit.columns:
            audit[col] = 0
        audit[col] = pd.to_numeric(audit[col], errors="coerce").fillna(0).astype(int)
    for col in ("first_held_main", "last_held_main", "first_held_concentrated", "last_held_concentrated"):
        if col not in audit.columns:
            audit[col] = ""
        audit[col] = audit[col].fillna("").astype(str)
    audit["decision_bucket"] = audit.apply(_decision_bucket, axis=1)

    for col in AUDIT_COLUMNS:
        if col not in audit.columns:
            audit[col] = ""
    audit_out = audit[AUDIT_COLUMNS].sort_values(
        ["selected_main_current", "selected_concentrated_current", "selection_pressure_score"],
        ascending=[False, False, False],
    )
    current_selected = audit_out.loc[
        audit_out["selected_main_current"].astype(bool) | audit_out["selected_concentrated_current"].astype(bool)
    ].copy()
    omitted = audit_out.loc[
        ~(audit_out["selected_main_current"].astype(bool) | audit_out["selected_concentrated_current"].astype(bool))
    ].copy()
    omitted = omitted.sort_values("selection_pressure_score", ascending=False).head(int(max(1, top_n))).copy()

    hist = main_hist
    if not conc_hist.empty:
        hist = hist.merge(conc_hist, on="ticker", how="outer") if not hist.empty else conc_hist
    if hist.empty:
        hist = pd.DataFrame(columns=["ticker", "months_held_main", "months_held_concentrated"])
    hist = hist.fillna("")

    audit_out.head(max(int(top_n) * 3, 200)).to_csv(output_dir / "ticker_decision_audit.csv", index=False)
    current_selected.to_csv(output_dir / "current_selected_audit.csv", index=False)
    omitted.to_csv(output_dir / "omitted_high_potential_candidates.csv", index=False)
    hist.to_csv(output_dir / "historical_hold_persistence.csv", index=False)

    bucket_counts = audit_out["decision_bucket"].value_counts(dropna=False).to_dict()
    stale_selected = current_selected.loc[current_selected["decision_bucket"].eq("selected_main_stale_review")]
    omitted_monster = omitted.loc[omitted["decision_bucket"].eq("omitted_monster_candidate")]
    summary = {
        "status": "completed",
        "experiment_id": "selection_audit",
        "latest_candidate_rows": int(len(candidates)),
        "current_main_count": int(len(main_w)),
        "current_concentrated_count": int(len(conc_w)),
        "decision_bucket_counts": {str(k): int(v) for k, v in bucket_counts.items()},
        "selected_stale_review_count": int(len(stale_selected)),
        "omitted_monster_candidate_count_top_n": int(len(omitted_monster)),
        "top_selected": _preview_rows(current_selected, 15),
        "top_omitted": _preview_rows(omitted, 20),
        "research_only": True,
        "production_activation_allowed": False,
    }
    write_json(output_dir / "selection_audit_summary.json", summary)
    write_text(output_dir / "selection_audit_report.md", _render_report(summary))
    return summary


def _preview_rows(frame: pd.DataFrame, n: int) -> list[dict[str, Any]]:
    cols = [
        "ticker",
        "Name",
        "decision_bucket",
        "selection_pressure_score",
        "current_main_weight",
        "current_concentrated_weight",
        "score",
        "concentrated_score",
        "portfolio_monster_early_score",
        "portfolio_stale_mega_leader_score",
        "portfolio_risk_entry_block_score",
        "portfolio_candidate_gate_label",
        "months_held_main",
        "months_held_concentrated",
    ]
    out = frame.copy()
    for col in cols:
        if col not in out.columns:
            out[col] = ""
    return out[cols].head(n).to_dict(orient="records")


def _pct(value: Any) -> str:
    return f"{safe_float(value, 0.0):.1%}"


def _render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Selection Audit",
        "",
        "Research-only diagnostic. It does not change production weights.",
        "",
        "## Summary",
        "",
        f"- latest candidate rows: {summary.get('latest_candidate_rows', 0)}",
        f"- current main names: {summary.get('current_main_count', 0)}",
        f"- current concentrated names: {summary.get('current_concentrated_count', 0)}",
        f"- selected stale review count: {summary.get('selected_stale_review_count', 0)}",
        f"- omitted monster candidates in top list: {summary.get('omitted_monster_candidate_count_top_n', 0)}",
        "",
        "## Decision Buckets",
        "",
    ]
    for key, value in sorted((summary.get("decision_bucket_counts") or {}).items()):
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Current Selected", "", "| ticker | bucket | main | concentrated | pressure | months main / conc |", "|---|---|---:|---:|---:|---:|"])
    for row in summary.get("top_selected", []):
        lines.append(
            f"| {row.get('ticker')} | `{row.get('decision_bucket')}` | "
            f"{_pct(row.get('current_main_weight'))} | {_pct(row.get('current_concentrated_weight'))} | "
            f"{safe_float(row.get('selection_pressure_score')):.3f} | "
            f"{row.get('months_held_main', 0)} / {row.get('months_held_concentrated', 0)} |"
        )
    lines.extend(["", "## Top Omitted Candidates", "", "| ticker | bucket | pressure | score | conc score | monster | risk block | gate |", "|---|---|---:|---:|---:|---:|---:|---|"])
    for row in summary.get("top_omitted", []):
        lines.append(
            f"| {row.get('ticker')} | `{row.get('decision_bucket')}` | "
            f"{safe_float(row.get('selection_pressure_score')):.3f} | "
            f"{safe_float(row.get('score')):.3f} | {safe_float(row.get('concentrated_score')):.3f} | "
            f"{safe_float(row.get('portfolio_monster_early_score')):.3f} | "
            f"{safe_float(row.get('portfolio_risk_entry_block_score')):.3f} | "
            f"{row.get('portfolio_candidate_gate_label', '')} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Use `current_selected_audit.csv` to explain why current holdings were selected and whether any are stale-review names.",
            "- Use `omitted_high_potential_candidates.csv` to inspect high-pressure candidates that were excluded by gates, risk blocks, caps, or lower priority.",
            "- Use `historical_hold_persistence.csv` to distinguish long-held winners from newly selected names.",
            "- This audit is intentionally explanatory only; it must not be used as a promotion gate without historical replay.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-n", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(repo_path(args.latest_run), repo_path(args.output_dir), top_n=int(args.top_n))
    print(f"[selection-audit] {payload.get('status')} -> {repo_path(args.output_dir)}")
    return 0 if payload.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

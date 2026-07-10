#!/usr/bin/env python3
"""Rank current candidates with durable free-data evidence.

This is a research-only latest-selection overlay. It does not mutate target
books, dispatch fullruns, or use vendor historical snapshots as backtest
features. Missing evidence is neutral; lifecycle risks are explicit.
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
SCHEMA_VERSION = "free-data-selection-overlay-v1"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def normalize_ticker(value: Any) -> str:
    return str(value or "").upper().strip().replace(".", "-")


def safe_num(series: pd.Series | Any, default: float = 0.0) -> pd.Series:
    if isinstance(series, pd.Series):
        return pd.to_numeric(series, errors="coerce").fillna(default)
    return pd.Series(dtype=float)


def first_col(frame: pd.DataFrame, names: list[str]) -> str | None:
    lower = {str(c).lower(): c for c in frame.columns}
    for name in names:
        if name in frame.columns:
            return name
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def robust_rank_score(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().sum() <= 1:
        return pd.Series(0.0, index=values.index)
    return numeric.rank(pct=True).fillna(0.0)


def latest_signal_by_ticker(signals: pd.DataFrame, decision_date: pd.Timestamp) -> pd.DataFrame:
    if signals.empty or "ticker" not in signals.columns:
        return pd.DataFrame(columns=["ticker"])
    d = signals.copy()
    d["ticker"] = d["ticker"].map(normalize_ticker)
    if "available_from" in d.columns:
        d["_available_from"] = pd.to_datetime(d["available_from"], errors="coerce").dt.normalize()
        d = d[d["_available_from"].notna() & (d["_available_from"] <= decision_date)]
    if d.empty:
        return pd.DataFrame(columns=["ticker"])
    return d.sort_values(["ticker", "_available_from" if "_available_from" in d.columns else "ticker"]).groupby("ticker", as_index=False).tail(1)


def latest_earnings_by_ticker(calendar: pd.DataFrame, decision_date: pd.Timestamp) -> pd.DataFrame:
    if calendar.empty or "ticker" not in calendar.columns or "event_date" not in calendar.columns:
        return pd.DataFrame(columns=["ticker"])
    d = calendar.copy()
    d["ticker"] = d["ticker"].map(normalize_ticker)
    d["_event_date"] = pd.to_datetime(d["event_date"], errors="coerce").dt.normalize()
    d = d[d["ticker"].ne("") & d["_event_date"].notna() & (d["_event_date"] <= decision_date)]
    if d.empty:
        return pd.DataFrame(columns=["ticker"])
    return d.sort_values(["ticker", "_event_date"]).groupby("ticker", as_index=False).tail(1)


def lifecycle_by_ticker(listing: pd.DataFrame, decision_date: pd.Timestamp) -> pd.DataFrame:
    if listing.empty:
        return pd.DataFrame(columns=["ticker", "free_data_lifecycle_ok", "free_data_lifecycle_risk"])
    d = listing.copy()
    symbol_col = first_col(d, ["symbol", "ticker"])
    if symbol_col is None:
        return pd.DataFrame(columns=["ticker", "free_data_lifecycle_ok", "free_data_lifecycle_risk"])
    d["ticker"] = d[symbol_col].map(normalize_ticker)
    status_col = first_col(d, ["status", "source_state"])
    delist_col = first_col(d, ["delisting_date"])
    d["_status"] = d[status_col].astype(str).str.lower() if status_col else ""
    d["_delisting_date"] = pd.to_datetime(d[delist_col], errors="coerce").dt.normalize() if delist_col else pd.NaT
    d["free_data_lifecycle_risk"] = d["_status"].str.contains("delist", na=False) | (
        d["_delisting_date"].notna() & (d["_delisting_date"] <= decision_date)
    )
    d = d.sort_values(["ticker", "free_data_lifecycle_risk"]).drop_duplicates("ticker", keep="last")
    d["free_data_lifecycle_ok"] = ~d["free_data_lifecycle_risk"].fillna(False)
    return d[["ticker", "free_data_lifecycle_ok", "free_data_lifecycle_risk"]]


def add_base_scores(scored: pd.DataFrame) -> pd.DataFrame:
    out = scored.copy()
    score_cols = [
        "alphaops_vnext_score",
        "concentrated_score",
        "score",
        "score_total",
        "market_leader_lane_score",
        "relative_strength_composite",
        "sec_13f_score",
        "actual_results_score",
    ]
    present = [c for c in score_cols if c in out.columns]
    if not present:
        out["free_data_base_rank_score"] = 0.0
        return out
    weighted = pd.Series(0.0, index=out.index)
    weights = {
        "alphaops_vnext_score": 0.25,
        "concentrated_score": 0.20,
        "score": 0.15,
        "score_total": 0.15,
        "market_leader_lane_score": 0.12,
        "relative_strength_composite": 0.10,
        "sec_13f_score": 0.10,
        "actual_results_score": 0.08,
    }
    weight_sum = 0.0
    for col in present:
        w = weights.get(col, 0.05)
        weighted = weighted + w * robust_rank_score(out[col])
        weight_sum += w
    out["free_data_base_rank_score"] = (weighted / max(weight_sum, 1e-9)).clip(0.0, 1.0)
    return out


def build_overlay(
    scored: pd.DataFrame,
    *,
    decision_date: pd.Timestamp,
    signals: pd.DataFrame,
    listing: pd.DataFrame,
    earnings_calendar: pd.DataFrame,
    top_n: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if scored.empty:
        return pd.DataFrame(), {"status": "blocked", "reason": "empty_scored"}
    out = scored.copy()
    ticker_col = first_col(out, ["ticker", "symbol"])
    if ticker_col is None:
        return pd.DataFrame(), {"status": "blocked", "reason": "missing_ticker_column"}
    out["ticker"] = out[ticker_col].map(normalize_ticker)
    out = out[out["ticker"].ne("")].copy()
    out = add_base_scores(out)

    latest_signals = latest_signal_by_ticker(signals, decision_date)
    if not latest_signals.empty:
        keep = [
            "ticker",
            *[
                c
                for c in [
                    "estimate_revision_confirmed",
                    "estimate_revision_replacement_gate_pass",
                    "estimate_revision_future_winner_multiplier",
                    "est_eps_revision_breadth",
                    "est_eps_revision_30d",
                    "est_eps_revision_90d",
                    "est_dispersion_change_30d",
                    "earnings_surprise_last",
                    "surprise_streak",
                    "has_forward_estimate",
                ]
                if c in latest_signals.columns
            ],
        ]
        out = out.merge(latest_signals[keep].drop_duplicates("ticker"), on="ticker", how="left")

    lifecycle = lifecycle_by_ticker(listing, decision_date)
    if not lifecycle.empty:
        out = out.merge(lifecycle, on="ticker", how="left")
    lifecycle_ok = out.get("free_data_lifecycle_ok", pd.Series(True, index=out.index, dtype=bool))
    lifecycle_risk = out.get("free_data_lifecycle_risk", pd.Series(False, index=out.index, dtype=bool))
    out["free_data_lifecycle_ok"] = lifecycle_ok.astype("boolean").fillna(True).astype(bool)
    out["free_data_lifecycle_risk"] = lifecycle_risk.astype("boolean").fillna(False).astype(bool)

    latest_earn = latest_earnings_by_ticker(earnings_calendar, decision_date)
    if not latest_earn.empty:
        keep = [c for c in ["ticker", "estimated_eps", "actual_eps", "event_date"] if c in latest_earn.columns]
        out = out.merge(latest_earn[keep].drop_duplicates("ticker"), on="ticker", how="left", suffixes=("", "_earnings_calendar"))

    for col in [
        "estimate_revision_confirmed",
        "estimate_revision_replacement_gate_pass",
        "estimate_revision_future_winner_multiplier",
        "est_eps_revision_breadth",
        "est_eps_revision_30d",
        "est_eps_revision_90d",
        "est_dispersion_change_30d",
        "earnings_surprise_last",
        "surprise_streak",
        "has_forward_estimate",
        "estimated_eps",
        "actual_eps",
    ]:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)

    denom = out["estimated_eps"].abs()
    eps_surprise_ratio = (out["actual_eps"] - out["estimated_eps"]) / denom.mask(denom.eq(0.0))
    eps_surprise_ratio = pd.to_numeric(eps_surprise_ratio, errors="coerce").fillna(0.0).clip(-1.0, 1.0)

    out["free_data_forward_estimate_score"] = (
        0.35 * out["estimate_revision_replacement_gate_pass"].clip(0.0, 1.0)
        + 0.25 * out["estimate_revision_confirmed"].clip(0.0, 1.0)
        + 0.20 * out["est_eps_revision_breadth"].clip(-1.0, 1.0).clip(lower=0.0)
        + 0.10 * out["est_eps_revision_30d"].clip(-0.5, 0.5).clip(lower=0.0) * 2.0
        + 0.10 * (-out["est_dispersion_change_30d"].clip(-0.5, 0.5)).clip(lower=0.0) * 2.0
    ).clip(0.0, 1.0)
    out["free_data_recent_actual_score"] = (
        0.65 * eps_surprise_ratio.clip(lower=0.0)
        + 0.20 * out["earnings_surprise_last"].clip(-1.0, 1.0).clip(lower=0.0)
        + 0.15 * (out["surprise_streak"].clip(lower=0.0, upper=4.0) / 4.0)
    ).clip(0.0, 1.0)
    out["free_data_evidence_coverage_count"] = (
        out["has_forward_estimate"].gt(0).astype(int)
        + out["estimated_eps"].ne(0).astype(int)
        + out["actual_eps"].ne(0).astype(int)
        + out["free_data_lifecycle_ok"].notna().astype(int)
    )
    lifecycle_penalty = out["free_data_lifecycle_risk"].astype(float)
    out["free_data_selection_score"] = (
        0.64 * out["free_data_base_rank_score"]
        + 0.22 * out["free_data_forward_estimate_score"]
        + 0.14 * out["free_data_recent_actual_score"]
        - 0.75 * lifecycle_penalty
    ).clip(lower=0.0)
    out["free_data_selection_rank"] = out["free_data_selection_score"].rank(method="first", ascending=False).astype(int)
    out["free_data_selection_label"] = "research_only_latest_overlay"
    out["production_promotion_allowed"] = False
    out["historical_backtest_acceptance_allowed"] = False
    out = out.sort_values("free_data_selection_score", ascending=False).reset_index(drop=True)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "decision_date": str(decision_date.date()),
        "input_rows": int(len(scored)),
        "ranked_rows": int(len(out)),
        "top_n": int(top_n),
        "forward_signal_matched_rows": int(out["has_forward_estimate"].gt(0).sum()) if "has_forward_estimate" in out.columns else 0,
        "lifecycle_risk_rows": int(out["free_data_lifecycle_risk"].sum()),
        "earnings_calendar_matched_rows": int(out["estimated_eps"].ne(0).sum()),
        "production_promotion_allowed": False,
        "historical_backtest_acceptance_allowed": False,
        "missing_evidence_policy": "neutral",
    }
    return out, summary


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_report(path: Path, summary: dict[str, Any], top: pd.DataFrame) -> None:
    lines = [
        "# Free Data Selection Overlay",
        "",
        f"Generated UTC: `{summary.get('generated_at_utc')}`",
        f"Status: `{summary.get('status')}`",
        f"Decision date: `{summary.get('decision_date')}`",
        "",
        "This is a research-only latest-selection overlay. It does not mutate target books.",
        "",
        "## Coverage",
        "",
        f"- Ranked rows: `{summary.get('ranked_rows')}`",
        f"- Forward signal matched rows: `{summary.get('forward_signal_matched_rows')}`",
        f"- Earnings-calendar matched rows: `{summary.get('earnings_calendar_matched_rows')}`",
        f"- Lifecycle risk rows: `{summary.get('lifecycle_risk_rows')}`",
        "",
        "## Top Candidates",
        "",
    ]
    cols = [
        "free_data_selection_rank",
        "ticker",
        "free_data_selection_score",
        "free_data_base_rank_score",
        "free_data_forward_estimate_score",
        "free_data_recent_actual_score",
        "free_data_lifecycle_risk",
    ]
    available = [c for c in cols if c in top.columns]
    if top.empty:
        lines.append("_No candidates._")
    else:
        lines.append("| " + " | ".join(available) + " |")
        lines.append("| " + " | ".join(["---"] * len(available)) + " |")
        for row in top[available].to_dict("records"):
            values = []
            for col in available:
                value = row.get(col, "")
                if isinstance(value, float):
                    value = round(value, 6)
                values.append(str(value))
            lines.append("| " + " | ".join(values) + " |")
    lines += [
        "",
        "## Rules",
        "",
        "- Missing evidence is neutral.",
        "- Forward estimates are used only when available by decision date.",
        "- Vendor historical earnings snapshots are not historical revision features.",
        "- Production promotion remains blocked.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    scored = read_table(repo_path(args.scored))
    signals = read_table(repo_path(args.estimate_signals))
    listing = read_table(repo_path(args.listing_status))
    earnings = read_table(repo_path(args.earnings_calendar))
    decision_date = pd.Timestamp(args.decision_date).normalize() if args.decision_date else pd.Timestamp.utcnow().normalize().tz_localize(None)
    ranked, summary = build_overlay(
        scored,
        decision_date=decision_date,
        signals=signals,
        listing=listing,
        earnings_calendar=earnings,
        top_n=args.top_n,
    )
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not ranked.empty:
        ranked.to_csv(output_dir / "ranked_universe.csv", index=False)
        ranked.head(args.top_n).to_csv(output_dir / "selected_candidates.csv", index=False)
    write_json(output_dir / "summary.json", summary)
    write_report(output_dir / "report.md", summary, ranked.head(args.top_n))
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored", default="cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv")
    parser.add_argument("--estimate-signals", default="data_pit/events/earnings_revision_signals.parquet")
    parser.add_argument("--listing-status", default="data_pit/free/av_listing_status.parquet")
    parser.add_argument("--earnings-calendar", default="data_pit/events/earnings_calendar_history.parquet")
    parser.add_argument("--decision-date", default="")
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--output-dir", default="outputs/free_data_selection_overlay")
    return parser.parse_args()


def main() -> int:
    summary = run(parse_args())
    return 0 if summary.get("status") == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Era leadership sidecar for factor IC and top-name contribution.

This is a diagnostic sidecar only. It does not alter production scores, target
books, or broker actions. Promotion requires a separate A/B and review gate.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ERA_BUCKETS = [
    ("2019_2021_pre_ai_bull", "2019-01-01", "2021-12-31"),
    ("2022_bear", "2022-01-01", "2022-12-31"),
    ("2023_2024_ai_bull", "2023-01-01", "2024-12-31"),
    ("2025_plus", "2025-01-01", "2099-12-31"),
]
FEATURE_CANDIDATES = [
    "alphaops_vnext_score",
    "selection_confirmation_score",
    "breakout_setup_quality_score",
    "theme_leadership_score",
    "etf_theme_leadership_score",
    "mom_6m",
    "mom_12m",
    "rs_benchmark_3m",
    "rs_3m",
]
RETURN_CANDIDATES = [
    "forward_return_63d",
    "fwd_63d_return",
    "next_63d_return",
    "ret_fwd_63d",
    "target_return",
    "return_63d",
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO / path


def first_col(frame: pd.DataFrame, names: list[str]) -> str | None:
    lower = {str(c).lower(): c for c in frame.columns}
    for name in names:
        if name.lower() in lower:
            return str(lower[name.lower()])
    return None


def read_input(args: argparse.Namespace) -> pd.DataFrame:
    path = repo_path(args.input_csv) if args.input_csv else repo_path(args.latest_run) / "scored_latest.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def assign_era(date_value: Any) -> str | None:
    ts = pd.to_datetime(date_value, errors="coerce")
    if pd.isna(ts):
        return None
    for name, start, end in ERA_BUCKETS:
        if pd.Timestamp(start) <= ts <= pd.Timestamp(end):
            return name
    return None


def rank_corr(a: pd.Series, b: pd.Series) -> float | None:
    frame = pd.DataFrame({"a": pd.to_numeric(a, errors="coerce"), "b": pd.to_numeric(b, errors="coerce")}).dropna()
    if len(frame) < 3 or frame["a"].nunique() < 2 or frame["b"].nunique() < 2:
        return None
    value = frame["a"].rank().corr(frame["b"].rank())
    if pd.isna(value):
        return None
    return float(value)


def build_sidecar(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if frame.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "missing_input"}
    date_col = first_col(frame, ["date", "rebalance_date", "as_of_date", "month"])
    ticker_col = first_col(frame, ["ticker", "symbol"])
    return_col = first_col(frame, RETURN_CANDIDATES)
    weight_col = first_col(frame, ["weight", "target_weight", "portfolio_weight", "current_weight"])
    regime_col = first_col(frame, ["regime", "regime_state", "market_regime"])
    if not date_col or not ticker_col or not return_col:
        return pd.DataFrame(), pd.DataFrame(), {
            "status": "missing_required_columns",
            "date_col": date_col,
            "ticker_col": ticker_col,
            "return_col": return_col,
        }

    work = frame.copy()
    work["_era"] = work[date_col].map(assign_era)
    work = work[work["_era"].notna()].copy()
    feature_cols = [c for c in FEATURE_CANDIDATES if c in work.columns]
    ic_rows: list[dict[str, Any]] = []
    for era, era_frame in work.groupby("_era"):
        for feature in feature_cols:
            ic_rows.append(
                {
                    "era": era,
                    "feature": feature,
                    "rank_ic": rank_corr(era_frame[feature], era_frame[return_col]),
                    "n": int(pd.DataFrame({"x": era_frame[feature], "y": era_frame[return_col]}).dropna().shape[0]),
                }
            )
        if regime_col:
            for regime, regime_frame in era_frame.groupby(regime_col):
                for feature in feature_cols:
                    ic_rows.append(
                        {
                            "era": era,
                            "regime": regime,
                            "feature": feature,
                            "rank_ic": rank_corr(regime_frame[feature], regime_frame[return_col]),
                            "n": int(pd.DataFrame({"x": regime_frame[feature], "y": regime_frame[return_col]}).dropna().shape[0]),
                        }
                    )
    leader_rows: list[dict[str, Any]] = []
    work["_return"] = pd.to_numeric(work[return_col], errors="coerce")
    if weight_col:
        work["_contribution"] = pd.to_numeric(work[weight_col], errors="coerce").fillna(0.0) * work["_return"].fillna(0.0)
    else:
        work["_contribution"] = work["_return"].fillna(0.0)
    for era, era_frame in work.groupby("_era"):
        contrib = era_frame.groupby(ticker_col)["_contribution"].sum().sort_values(ascending=False).head(20)
        for ticker, value in contrib.items():
            leader_rows.append({"era": era, "ticker": ticker, "contribution": float(value)})
    summary = {
        "schema_version": "era-leadership-sidecar-v1",
        "status": "completed",
        "production_activation_allowed": False,
        "era_buckets": [{"name": n, "start": s, "end": e} for n, s, e in ERA_BUCKETS],
        "date_col": date_col,
        "ticker_col": ticker_col,
        "return_col": return_col,
        "weight_col": weight_col,
        "feature_count": len(feature_cols),
        "row_count": int(len(work)),
    }
    return pd.DataFrame(ic_rows), pd.DataFrame(leader_rows), summary


def render_markdown(ic: pd.DataFrame, leaders: pd.DataFrame, summary: dict[str, Any]) -> str:
    lines = [
        "# Era Leadership Sidecar",
        "",
        "- production_activation_allowed: `false`",
        f"- status: `{summary.get('status')}`",
        f"- rows: `{summary.get('row_count', 0)}`",
        "",
        "## Top Factor IC By Era",
        "",
        "| Era | Feature | Rank IC | N |",
        "| --- | --- | ---: | ---: |",
    ]
    if not ic.empty:
        top = ic.dropna(subset=["rank_ic"]).sort_values(["era", "rank_ic"], ascending=[True, False]).groupby("era").head(5)
        for _, row in top.iterrows():
            lines.append(f"| {row.get('era')} | {row.get('feature')} | {float(row.get('rank_ic')):.4f} | {int(row.get('n'))} |")
    lines.extend(["", "## Top Name Contribution By Era", "", "| Era | Ticker | Contribution |", "| --- | --- | ---: |"])
    if not leaders.empty:
        for _, row in leaders.groupby("era").head(10).iterrows():
            lines.append(f"| {row.get('era')} | {row.get('ticker')} | {float(row.get('contribution')):.6f} |")
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    frame = read_input(args)
    ic, leaders, summary = build_sidecar(frame)
    summary["generated_at_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    ic.to_csv(output_dir / "era_feature_ic.csv", index=False)
    leaders.to_csv(output_dir / "era_leaders.csv", index=False)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "summary.md").write_text(render_markdown(ic, leaders, summary), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--input-csv", default="")
    parser.add_argument("--output-dir", default="outputs/era_leadership")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    run(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Latest governance/ownership catalyst diagnostics.

This report surfaces existing flow/event columns; it does not scrape news and
does not alter scores. It is meant to show whether the engine is even seeing
ownership, insider, event, and revision catalysts before we promote any rule.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import pandas as pd

from historical_replay_lib import read_table, repo_path, safe_float, write_json, write_rows, write_text


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUT_DIR = "outputs/governance_catalyst"


FLOW_COLUMNS = [
    "ownership_flow_pillar_score",
    "insider_cluster_boost_score",
    "event_revision_pillar_score",
    "selection_flow_confirmation_score",
    "event_reaction_score",
    "live_event_growth_reentry_score",
    "live_event_defensive_score",
    "live_event_risk_score",
    "focus_live_event_growth_score",
    "focus_event_stress_penalty",
]


def normalize_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def latest_scored(latest_run: Path) -> pd.DataFrame:
    frame = read_table(latest_run / "scored_latest.csv")
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["ticker"] = out["ticker"].map(normalize_ticker)
    out = out[out["ticker"] != ""]
    return out.drop_duplicates("ticker", keep="first")


def row_score(row: pd.Series) -> float:
    ownership = safe_float(row.get("ownership_flow_pillar_score"), 0.0)
    insider = safe_float(row.get("insider_cluster_boost_score"), 0.0)
    revision = safe_float(row.get("event_revision_pillar_score"), 0.0)
    reaction = safe_float(row.get("event_reaction_score"), 0.0)
    growth = safe_float(row.get("live_event_growth_reentry_score"), 0.0)
    risk = safe_float(row.get("live_event_risk_score"), 0.0) + safe_float(row.get("focus_event_stress_penalty"), 0.0)
    return max(0.0, 0.30 * ownership + 0.25 * insider + 0.20 * revision + 0.15 * reaction + 0.10 * growth - 0.25 * risk)


def classify(row: pd.Series) -> str:
    parts = []
    if safe_float(row.get("ownership_flow_pillar_score"), 0.0) >= 0.60:
        parts.append("ownership_flow")
    if safe_float(row.get("insider_cluster_boost_score"), 0.0) >= 0.25:
        parts.append("insider_cluster")
    if safe_float(row.get("event_revision_pillar_score"), 0.0) >= 0.60:
        parts.append("revision_event")
    if safe_float(row.get("live_event_growth_reentry_score"), 0.0) >= 0.30:
        parts.append("growth_reentry")
    if safe_float(row.get("live_event_risk_score"), 0.0) >= 0.60:
        parts.append("event_risk")
    return "+".join(parts) if parts else "none"


def build_rows(frame: pd.DataFrame, watchlist: list[str], top_n: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if frame.empty:
        return [], {"status": "blocked", "reason": "scored_latest.csv missing or empty"}
    rows: list[dict[str, Any]] = []
    data = frame.copy()
    for col in FLOW_COLUMNS:
        if col not in data.columns:
            data[col] = 0.0
    for col in ("portfolio_monster_early_score", "score"):
        if col not in data.columns:
            data[col] = 0.0
    data["governance_catalyst_score"] = data.apply(row_score, axis=1)
    data["governance_catalyst_label"] = data.apply(classify, axis=1)
    selected = data.sort_values(
        ["governance_catalyst_score", "portfolio_monster_early_score", "score"],
        ascending=[False, False, False],
    ).head(max(int(top_n), 1))
    watch = {normalize_ticker(t) for t in watchlist if normalize_ticker(t)}
    if watch:
        selected = pd.concat([selected, data[data["ticker"].isin(watch)]], ignore_index=True).drop_duplicates("ticker")
    for _, row in selected.iterrows():
        out = {
            "ticker": row.get("ticker"),
            "Name": row.get("Name", row.get("name", "")),
            "sector": row.get("sector", ""),
            "portfolio_sleeve_label": row.get("portfolio_sleeve_label", ""),
            "portfolio_candidate_gate_label": row.get("portfolio_candidate_gate_label", ""),
            "governance_catalyst_score": row.get("governance_catalyst_score"),
            "governance_catalyst_label": row.get("governance_catalyst_label"),
            "event_regime_label": row.get("event_regime_label", ""),
            "live_event_alert_label": row.get("live_event_alert_label", ""),
            "portfolio_monster_early_score": row.get("portfolio_monster_early_score", ""),
            "rs_acceleration_score": row.get("rs_acceleration_score", ""),
            "market_cap_live": row.get("market_cap_live", row.get("mktcap", "")),
        }
        for col in FLOW_COLUMNS:
            out[col] = row.get(col, "")
        rows.append(out)
    label_counts: dict[str, int] = {}
    for label in data["governance_catalyst_label"].astype(str).tolist():
        label_counts[label] = label_counts.get(label, 0) + 1
    summary = {
        "status": "completed",
        "rows": len(rows),
        "scored_rows": int(len(data)),
        "nonzero_catalyst_rows": int((data["governance_catalyst_score"] > 0).sum()),
        "label_counts": label_counts,
        "available_columns": [col for col in FLOW_COLUMNS if col in frame.columns],
        "watchlist_count": len(watch),
        "research_only": True,
        "production_activation_allowed": False,
    }
    return rows, summary


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Governance Catalyst Report",
        "",
        "Latest scored-universe view of ownership, insider, event, and revision catalyst columns.",
        "",
        f"- Status: `{summary.get('status')}`",
        f"- Scored rows: {summary.get('scored_rows')}",
        f"- Nonzero catalyst rows: {summary.get('nonzero_catalyst_rows')}",
        f"- Watchlist count: {summary.get('watchlist_count')}",
        "",
        "This is a diagnostic surface only; government/strategic stake detection still needs a future SEC 8-K/news event parser before it can become a rule.",
        "",
    ]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    watchlist = [normalize_ticker(t) for t in str(args.watchlist or "").replace(";", ",").split(",") if normalize_ticker(t)]
    rows, summary = build_rows(latest_scored(latest_run), watchlist, int(args.top_n))
    write_rows(output_dir / "governance_catalyst_latest.csv", rows)
    write_json(output_dir / "summary.json", summary)
    write_text(output_dir / "report.md", render_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--top-n", type=int, default=80)
    parser.add_argument("--watchlist", default="")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps({"status": payload.get("status"), "rows": payload.get("rows")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

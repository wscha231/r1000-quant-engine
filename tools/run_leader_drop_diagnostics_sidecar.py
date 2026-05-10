#!/usr/bin/env python3
"""Fallback latest leader diagnostics when the in-pipeline report is absent.

The primary pipeline diagnostic runs before the scoring universe is finalized.
This sidecar is intentionally narrower: it guarantees a latest-run artifact from
the files that are always expected after a full rebuild. It never changes
selection behavior.
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
DEFAULT_OUT_DIR = "outputs/reports"


def normalize_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def load_ticker_set(path: Path) -> set[str]:
    frame = read_table(path)
    if frame.empty or "ticker" not in frame.columns:
        return set()
    return {normalize_ticker(t) for t in frame["ticker"].dropna().tolist() if normalize_ticker(t)}


def latest_by_ticker(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    if "rebalance_date" in out.columns:
        dates = pd.to_datetime(out["rebalance_date"], errors="coerce")
        if dates.notna().any():
            out = out.loc[dates.eq(dates.max())].copy()
    out["ticker"] = out["ticker"].map(normalize_ticker)
    out = out[out["ticker"] != ""]
    return out.drop_duplicates("ticker", keep="first").set_index("ticker", drop=False)


def reason_for_row(row: pd.Series, in_main: bool, in_concentrated: bool) -> str:
    if in_main:
        return "selected_main"
    if in_concentrated:
        return "selected_concentrated"
    gate = str(row.get("portfolio_candidate_gate_label", "") or "").lower()
    if gate and "reject" in gate:
        return "candidate_gate_rejected"
    if safe_float(row.get("portfolio_risk_entry_block_score"), 0.0) >= 0.75:
        return "risk_entry_blocked"
    if safe_float(row.get("portfolio_stale_mega_leader_score"), 0.0) >= 0.75:
        return "stale_leader_blocked"
    if safe_float(row.get("portfolio_monster_early_score"), 0.0) >= 0.58:
        return "monster_candidate_not_selected"
    sleeve = str(row.get("portfolio_sleeve_label", "") or "").lower()
    if sleeve == "unassigned":
        return "unassigned_score_not_selected"
    return "rank_or_cap_not_selected"


def build_rows(latest_run: Path, watchlist: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scored = latest_by_ticker(read_table(latest_run / "scored_latest.csv"))
    replay = latest_by_ticker(read_table(latest_run / "reports" / "candidate_replay_book.csv"))
    if scored.empty and not replay.empty:
        scored = replay
    main_tickers = load_ticker_set(latest_run / "portfolio_latest.csv")
    concentrated_tickers = load_ticker_set(latest_run / "concentrated_portfolio_latest.csv")

    rows: list[dict[str, Any]] = []
    for ticker, row in scored.iterrows():
        in_main = ticker in main_tickers
        in_concentrated = ticker in concentrated_tickers
        rows.append(
            {
                "ticker": ticker,
                "Name": row.get("Name", row.get("name", "")),
                "sector": row.get("sector", ""),
                "diagnostic_mode": "latest_scored_fallback",
                "in_latest_scored_universe": True,
                "in_main_portfolio": in_main,
                "in_concentrated_portfolio": in_concentrated,
                "portfolio_sleeve_label": row.get("portfolio_sleeve_label", ""),
                "portfolio_candidate_gate_label": row.get("portfolio_candidate_gate_label", ""),
                "portfolio_defensive_rotation_action": row.get("portfolio_defensive_rotation_action", ""),
                "portfolio_monster_early_score": row.get("portfolio_monster_early_score", ""),
                "portfolio_stale_mega_leader_score": row.get("portfolio_stale_mega_leader_score", ""),
                "portfolio_risk_entry_block_score": row.get("portfolio_risk_entry_block_score", ""),
                "rs_acceleration_score": row.get("rs_acceleration_score", ""),
                "oneil_leadership_score": row.get("oneil_leadership_score", ""),
                "industry_group_strength_score": row.get("industry_group_strength_score", ""),
                "price_above_ma50": row.get("price_above_ma50", ""),
                "price_above_ma200": row.get("price_above_ma200", ""),
                "near_52w_high_pct": row.get("near_52w_high_pct", ""),
                "market_cap_live": row.get("market_cap_live", row.get("mktcap", "")),
                "period_forward_return": row.get("period_forward_return", ""),
                "drop_reason": reason_for_row(row, in_main, in_concentrated),
            }
        )

    existing = {str(row.get("ticker")) for row in rows}
    for ticker in watchlist:
        t = normalize_ticker(ticker)
        if not t or t in existing:
            continue
        rows.append(
            {
                "ticker": t,
                "diagnostic_mode": "watchlist_missing_fallback",
                "in_latest_scored_universe": False,
                "in_main_portfolio": t in main_tickers,
                "in_concentrated_portfolio": t in concentrated_tickers,
                "drop_reason": "not_in_latest_scored_universe_or_filtered_before_scoring",
            }
        )

    reason_counts: dict[str, int] = {}
    for row in rows:
        reason = str(row.get("drop_reason") or "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    summary = {
        "rows": len(rows),
        "diagnostic_mode": "fallback_latest_scored",
        "source_files": {
            "scored_latest": str(latest_run / "scored_latest.csv"),
            "candidate_replay_book": str(latest_run / "reports" / "candidate_replay_book.csv"),
            "portfolio_latest": str(latest_run / "portfolio_latest.csv"),
            "concentrated_portfolio_latest": str(latest_run / "concentrated_portfolio_latest.csv"),
        },
        "watchlist_count": len(watchlist),
        "reason_counts": reason_counts,
        "production_activation_allowed": False,
    }
    return rows, summary


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Leader Drop Diagnostics Fallback",
        "",
        "Research/report-only fallback generated after the full rebuild from latest scored and portfolio artifacts.",
        "",
        f"- Rows: {summary.get('rows')}",
        f"- Mode: `{summary.get('diagnostic_mode')}`",
        f"- Watchlist count: {summary.get('watchlist_count')}",
        "",
        "## Drop Reasons",
        "",
    ]
    for reason, count in sorted((summary.get("reason_counts") or {}).items(), key=lambda item: (-int(item[1]), item[0])):
        lines.append(f"- `{reason}`: {count}")
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    detail_path = output_dir / "leader_drop_diagnostics_latest.csv"
    summary_path = output_dir / "leader_drop_diagnostics_summary.json"
    if detail_path.exists() and summary_path.exists() and not args.force:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    watchlist = [normalize_ticker(t) for t in str(args.watchlist or "").replace(";", ",").split(",") if normalize_ticker(t)]
    rows, summary = build_rows(latest_run, watchlist)
    write_rows(detail_path, rows)
    write_json(summary_path, summary)
    write_text(output_dir / "leader_drop_diagnostics_report.md", render_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--watchlist", default="")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    summary = run(parse_args())
    print(json.dumps({"rows": summary.get("rows"), "mode": summary.get("diagnostic_mode")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

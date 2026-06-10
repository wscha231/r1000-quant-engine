#!/usr/bin/env python3
"""Research-only market style regime report.

Summarizes when the engine thinks the tape favors:
  - breakout/growth leaders near highs
  - bottoming turnaround accumulation
  - quality compounders
  - cash-defense/risk reduction

This is diagnostic only. It does not alter production weights or orders.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from historical_replay_lib import read_table, repo_path, safe_float, write_json, write_rows, write_text


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUT_DIR = "outputs/style_regime_report"


STYLE_COLS = [
    "style_breakout_preference",
    "style_turnaround_preference",
    "style_quality_compounder_preference",
    "style_cash_defense_preference",
    "style_liquidity_tailwind_score",
    "style_rate_pressure_score",
    "style_inflation_pressure_score",
    "style_overheat_risk_score",
]


def _mean(rows: list[dict[str, Any]], col: str) -> float:
    vals = [safe_float(row.get(col), 0.0) for row in rows]
    return sum(vals) / max(len(vals), 1)


def _mode(rows: list[dict[str, Any]], col: str, default: str = "unknown") -> str:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(col) or "").strip() or default
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return default
    return max(counts.items(), key=lambda item: item[1])[0]


def _top(rows: list[dict[str, Any]], col: str, limit: int = 8) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda row: safe_float(row.get(col), 0.0), reverse=True)[:limit]
    out: list[dict[str, Any]] = []
    for row in ranked:
        out.append(
            {
                "ticker": row.get("ticker", ""),
                "Name": row.get("Name", ""),
                "sector": row.get("sector", ""),
                "portfolio_sleeve_label": row.get("portfolio_sleeve_label", ""),
                "score": row.get("score", ""),
                col: row.get(col, ""),
                "market_style_regime_label": row.get("market_style_regime_label", ""),
            }
        )
    return out


def run(latest_run: Path, output_dir: Path) -> dict[str, Any]:
    book_path = latest_run / "reports" / "candidate_replay_book.csv"
    latest_path = latest_run / "scored_latest.csv"
    book = read_table(book_path)
    latest = read_table(latest_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    if book.empty:
        payload = {
            "status": "blocked",
            "reason": "missing candidate_replay_book",
            "candidate_replay_book": str(book_path),
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "summary.json", payload)
        write_text(output_dir / "report.md", "# Style Regime Report\n\nBlocked: missing candidate replay book.\n")
        return payload

    if "rebalance_date" not in book.columns:
        payload = {
            "status": "blocked",
            "reason": "candidate_replay_book lacks rebalance_date",
            "candidate_replay_book": str(book_path),
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "summary.json", payload)
        write_text(output_dir / "report.md", "# Style Regime Report\n\nBlocked: no rebalance_date.\n")
        return payload

    frame = book.copy()
    frame["rebalance_date"] = frame["rebalance_date"].astype(str).str[:10]
    monthly_rows: list[dict[str, Any]] = []
    for dt, group in frame.groupby("rebalance_date", sort=True):
        rows = group.to_dict("records")
        monthly_rows.append(
            {
                "rebalance_date": dt,
                "market_style_regime_label": _mode(rows, "market_style_regime_label"),
                **{col: _mean(rows, col) for col in STYLE_COLS},
                "n_candidates": len(rows),
                "top_breakout": ",".join(row["ticker"] for row in _top(rows, "style_row_breakout_fit", 5)),
                "top_turnaround": ",".join(row["ticker"] for row in _top(rows, "style_row_turnaround_fit", 5)),
                "top_compounder": ",".join(row["ticker"] for row in _top(rows, "style_row_compounder_fit", 5)),
            }
        )

    latest_rows = latest.to_dict("records") if not latest.empty else frame[frame["rebalance_date"] == frame["rebalance_date"].max()].to_dict("records")
    latest_summary = {
        "market_style_regime_label": _mode(latest_rows, "market_style_regime_label"),
        **{col: _mean(latest_rows, col) for col in STYLE_COLS},
        "top_breakout": _top(latest_rows, "style_row_breakout_fit"),
        "top_turnaround": _top(latest_rows, "style_row_turnaround_fit"),
        "top_compounder": _top(latest_rows, "style_row_compounder_fit"),
    }
    payload = {
        "status": "completed",
        "candidate_replay_book": str(book_path),
        "latest_scored": str(latest_path),
        "months": len(monthly_rows),
        "latest": latest_summary,
        "research_only": True,
        "production_activation_allowed": False,
    }
    write_json(output_dir / "summary.json", payload)
    write_rows(output_dir / "monthly.csv", monthly_rows)
    write_rows(output_dir / "latest_top_breakout.csv", latest_summary["top_breakout"])
    write_rows(output_dir / "latest_top_turnaround.csv", latest_summary["top_turnaround"])
    write_rows(output_dir / "latest_top_compounder.csv", latest_summary["top_compounder"])
    write_text(output_dir / "report.md", render_report(payload))
    return payload


def render_report(payload: dict[str, Any]) -> str:
    latest = payload.get("latest") or {}
    lines = [
        "# Style Regime Report",
        "",
        "Research-only diagnostic. It does not change production weights.",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Months: {payload.get('months')}",
        f"- Latest style regime: `{latest.get('market_style_regime_label', 'unknown')}`",
        f"- Breakout preference: {safe_float(latest.get('style_breakout_preference')):.2f}",
        f"- Turnaround preference: {safe_float(latest.get('style_turnaround_preference')):.2f}",
        f"- Quality preference: {safe_float(latest.get('style_quality_compounder_preference')):.2f}",
        f"- Cash-defense preference: {safe_float(latest.get('style_cash_defense_preference')):.2f}",
        "",
        "Use this report to compare whether high-breakout leaders or bottoming",
        "turnaround candidates should receive more capital in a separate A/B.",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out = run(repo_path(args.latest_run), repo_path(args.output_dir))
    print(f"[style-regime] {out.get('status')} -> {repo_path(args.output_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

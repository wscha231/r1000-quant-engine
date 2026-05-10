#!/usr/bin/env python3
"""Generate research-only Alpha Sprint latest shadow outputs."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from r1000_alpha_sprint import (  # noqa: E402
    ALPHA_SPRINT_POLICY,
    build_alpha_sprint_snapshot,
    safe_float,
)


DEFAULT_SCORED = "cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv_rows(path_like: str | Path) -> list[dict[str, str]]:
    path = repo_path(path_like)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def candidate_csv_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, item in enumerate(snapshot.get("candidates") or [], start=1):
        row = {key: value for key, value in item.items() if key != "gate_detail"}
        row["rank"] = rank
        row["regime_state"] = snapshot.get("regime_state")
        row["activation_capacity"] = snapshot.get("portfolio", {}).get("activation", {}).get("capacity")
        row["active_weight"] = (snapshot.get("portfolio", {}).get("weights") or {}).get(row.get("ticker"), 0.0)
        rows.append(row)
    return rows


def portfolio_csv_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    regime_state = snapshot.get("regime_state")
    weights = snapshot.get("portfolio", {}).get("weights") or {}
    for rank, (ticker, weight) in enumerate(weights.items(), start=1):
        rows.append(
            {
                "rank": rank,
                "ticker": ticker,
                "target_weight": weight,
                "regime_state": regime_state,
                "row_type": "equity",
            }
        )
    rows.append(
        {
            "rank": len(rows) + 1,
            "ticker": "CASH",
            "target_weight": snapshot.get("portfolio", {}).get("cash_target", 1.0),
            "regime_state": regime_state,
            "row_type": "cash",
        }
    )
    return rows


def risk_action_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    activation = snapshot.get("portfolio", {}).get("activation") or {}
    weights = snapshot.get("portfolio", {}).get("weights") or {}
    rows: list[dict[str, Any]] = []
    for item in snapshot.get("candidates") or []:
        ticker = item.get("ticker")
        rows.append(
            {
                "ticker": ticker,
                "alpha_sprint_score": item.get("alpha_sprint_score"),
                "target_weight": weights.get(ticker, 0.0),
                "action": "paper_candidate" if not activation.get("active") else "shadow_entry_candidate",
                "reason": activation.get("reason"),
                "hard_stop": snapshot.get("portfolio", {}).get("risk_policy", {}).get("hard_stop"),
                "trailing_stop": snapshot.get("portfolio", {}).get("risk_policy", {}).get("trailing_stop"),
                "time_stop_days": snapshot.get("portfolio", {}).get("risk_policy", {}).get("time_stop_days"),
            }
        )
    return rows


def render_report(snapshot: dict[str, Any]) -> str:
    activation = snapshot.get("portfolio", {}).get("activation") or {}
    audit = snapshot.get("audit") or {}
    lines = [
        "# Alpha Sprint Shadow Report",
        "",
        "This is a research-only sidecar. It does not place orders and is not included in production defaults.",
        "",
        "## Latest State",
        "",
        f"- Regime: `{snapshot.get('regime_state')}`",
        f"- Activation capacity: {safe_float(activation.get('capacity')):.2%}",
        f"- Active: {activation.get('active')}",
        f"- Reason: `{activation.get('reason')}`",
        f"- Candidates: {audit.get('candidate_count')}",
        f"- Shadow positions: {audit.get('n_positions')}",
        "",
        "## Top Candidates",
        "",
    ]
    for item in (snapshot.get("candidates") or [])[:10]:
        lines.append(
            "- {ticker}: score {score:.3f}, RS {rs:.3f}, breakout {breakout:.3f}, catalyst {catalyst:.3f}".format(
                ticker=item.get("ticker"),
                score=safe_float(item.get("alpha_sprint_score")),
                rs=safe_float(item.get("rs_acceleration_score")),
                breakout=safe_float(item.get("breakout_setup_quality_score")),
                catalyst=safe_float(item.get("earnings_revision_or_surprise")),
            )
        )
    lines.extend(
        [
            "",
            "## Backtest Status",
            "",
            "Historical performance is intentionally marked not backtested until a weekly/historical scored snapshot runner is added.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored", default=DEFAULT_SCORED)
    parser.add_argument("--out-dir", default="outputs/alpha_sprint")
    parser.add_argument("--regime", default=None)
    args = parser.parse_args()

    scored_path = repo_path(args.scored)
    if not scored_path.exists():
        print(f"[alpha-sprint] missing scored input: {scored_path}")
        return 2
    rows = read_csv_rows(scored_path)
    snapshot = build_alpha_sprint_snapshot(rows, regime_state=args.regime, policy=ALPHA_SPRINT_POLICY)

    out_dir = repo_path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "alpha_sprint_latest.json", snapshot)
    write_json(
        out_dir / "backtest_metrics.json",
        {
            "status": "not_backtested_missing_historical_scored_snapshot",
            "research_only": True,
            "production_activation_allowed": False,
            "required_next_runner": "weekly_or_monthly_alpha_sprint_historical_backtest",
        },
    )
    write_csv_rows(
        out_dir / "candidates_latest.csv",
        candidate_csv_rows(snapshot),
        [
            "rank",
            "ticker",
            "name",
            "sector",
            "industry_group",
            "alpha_sprint_score",
            "rs_acceleration_score",
            "breakout_setup_quality_score",
            "volatility_contraction_score",
            "explosion_entry_score",
            "h6_dynamic_leader_score",
            "theme_phase_term",
            "earnings_revision_or_surprise",
            "industry_group_strength_score",
            "stage2_overext_penalty",
            "explosion_exit_score",
            "live_event_risk_score",
            "atr14_pct",
            "rsi14",
            "regime_state",
            "activation_capacity",
            "active_weight",
        ],
    )
    write_csv_rows(
        out_dir / "portfolio_latest.csv",
        portfolio_csv_rows(snapshot),
        ["rank", "ticker", "target_weight", "regime_state", "row_type"],
    )
    write_csv_rows(
        out_dir / "risk_actions.csv",
        risk_action_rows(snapshot),
        ["ticker", "alpha_sprint_score", "target_weight", "action", "reason", "hard_stop", "trailing_stop", "time_stop_days"],
    )
    write_csv_rows(out_dir / "weekly_returns.csv", [], ["date", "return", "note"])
    (out_dir / "alpha_sprint_report.md").write_text(render_report(snapshot), encoding="utf-8")
    print(f"[alpha-sprint] wrote {out_dir / 'alpha_sprint_latest.json'}")
    print(f"[alpha-sprint] wrote {out_dir / 'alpha_sprint_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

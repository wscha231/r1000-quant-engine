#!/usr/bin/env python3
"""Aggregate AlphaOps strategy variant outcomes and decision attribution.

The ledger is research-only. It records what logic was run, how it performed,
and the available buy/sell/hold/crisis reasons so future tuning is evidence
based rather than based on headline CAGR alone.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUTPUT_DIR = "outputs/strategy_logic_ledger"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


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


def official_rows(latest_run: Path, run_id: str, commit_sha: str, artifact_id: str) -> list[dict[str, Any]]:
    payload = read_json(latest_run / "account_evaluation" / "official_metrics.json")
    rows: list[dict[str, Any]] = []
    portfolios = payload.get("portfolios") if isinstance(payload.get("portfolios"), dict) else {}
    for portfolio, metrics in portfolios.items():
        rows.append(
            {
                "run_id": run_id,
                "commit_sha": commit_sha,
                "artifact_id": artifact_id,
                "strategy_family": "production_baseline",
                "portfolio_kind": portfolio,
                "case_id": "A",
                "variant_id": "production_baseline",
                "selection_layer": "production",
                "lane_allocator_enabled": False,
                "crisis_overlay_enabled": False,
                "hold_replace_enabled": False,
                "hold_policy_enabled": False,
                "theme_enabled": False,
                "top7_enabled": False,
                "target_n": metrics.get("position_count"),
                "caps": "",
                "cagr": metrics.get("cagr"),
                "max_dd": metrics.get("max_dd"),
                "covid_mdd": "",
                "rate_2022_mdd": "",
                "green_avg_cash": "",
                "reentry_lag": "",
                "cash_trap_days": "",
                "sharpe": metrics.get("sharpe"),
                "avg_cash": metrics.get("avg_cash_weight"),
                "latest_cash": metrics.get("latest_cash_weight"),
                "trade_count": metrics.get("broker_trade_count") or metrics.get("trade_count"),
                "fees": metrics.get("total_fees_usd"),
                "metric_mode": metrics.get("official_metric_mode") or payload.get("official_metric_mode"),
                "buy_reason": "production_baseline",
                "sell_reason": "production_baseline",
                "hold_reason": "production_baseline",
                "replace_reason": "",
                "crisis_action_reason": "",
                "lane_reason": "production_baseline",
                "theme_reason": "",
                "evidence_reason": "",
            }
        )
    return rows


def market_leader_rows(latest_run: Path, run_id: str, commit_sha: str, artifact_id: str) -> list[dict[str, Any]]:
    grid = read_csv(latest_run / "market_leader_challenger" / "grid_results.csv")
    if grid.empty:
        grid = read_csv(REPO_ROOT / "outputs" / "market_leader_challenger" / "grid_results.csv")
    rows: list[dict[str, Any]] = []
    for rec in grid.to_dict("records"):
        rows.append(
            {
                "run_id": run_id,
                "commit_sha": commit_sha,
                "artifact_id": artifact_id,
                "strategy_family": "market_leader_risk_managed" if str(rec.get("risk_mode") or "") != "none" else "market_leader",
                "portfolio_kind": rec.get("portfolio_kind"),
                "case_id": "",
                "variant_id": rec.get("variant_id"),
                "target_n": rec.get("target_n"),
                "single_cap": rec.get("single_cap"),
                "subindustry_cap": rec.get("subindustry_cap"),
                "caps": f"single={rec.get('single_cap')};subindustry={rec.get('subindustry_cap')}",
                "selection_layer": "market_leader",
                "lane_allocator_enabled": False,
                "crisis_overlay_enabled": False,
                "hold_replace_enabled": True,
                "hold_policy_enabled": True,
                "theme_enabled": True,
                "top7_enabled": True,
                "cagr": rec.get("cagr"),
                "max_dd": rec.get("max_dd"),
                "covid_mdd": rec.get("covid_mdd"),
                "rate_2022_mdd": rec.get("rate_2022_mdd"),
                "green_avg_cash": rec.get("green_avg_cash"),
                "reentry_lag": rec.get("reentry_lag_days"),
                "cash_trap_days": rec.get("cash_trap_days"),
                "sharpe": rec.get("sharpe"),
                "avg_cash": rec.get("avg_cash_weight"),
                "trade_count": rec.get("trade_count"),
                "fees": rec.get("total_fees_usd"),
                "metric_mode": rec.get("metric_mode"),
                "buy_reason": "leader_selection_score",
                "sell_reason": "target_exit_or_rebalance",
                "hold_reason": "leader_state_persistence",
                "replace_reason": "stronger_leader_replacement",
                "crisis_action_reason": "",
                "lane_reason": "MARKET_LEADER",
                "theme_reason": "leader_broad_theme",
                "evidence_reason": "smart_money_positive_boost",
            }
        )
    return rows


def integrated_rows(output_dir: Path, run_id: str, commit_sha: str, artifact_id: str) -> list[dict[str, Any]]:
    ab = read_csv(output_dir / "ab_matrix.csv")
    rows: list[dict[str, Any]] = []
    for rec in ab.to_dict("records"):
        rows.append(
            {
                "run_id": run_id,
                "commit_sha": commit_sha,
                "artifact_id": artifact_id,
                "strategy_family": rec.get("purpose") or "integrated_replay",
                "portfolio_kind": rec.get("portfolio_kind"),
                "case_id": rec.get("case_id"),
                "variant_id": rec.get("case_id"),
                "selection_layer": rec.get("selection_layer"),
                "lane_allocator_enabled": bool(rec.get("lane_allocator_enabled")),
                "crisis_overlay_enabled": bool(rec.get("crisis_overlay")),
                "hold_replace_enabled": bool(rec.get("hold_replace_enabled")),
                "hold_policy_enabled": bool(rec.get("hold_replace_enabled")),
                "theme_enabled": str(rec.get("selection_layer")) in {"market_leader", "multi_lane"},
                "top7_enabled": str(rec.get("selection_layer")) == "multi_lane",
                "target_n": rec.get("requested_target_n"),
                "caps": rec.get("caps", ""),
                "cagr": rec.get("cagr"),
                "max_dd": rec.get("max_dd"),
                "covid_mdd": rec.get("covid_mdd"),
                "rate_2022_mdd": rec.get("rate_2022_mdd"),
                "green_avg_cash": rec.get("green_avg_cash"),
                "reentry_lag": rec.get("reentry_lag_days"),
                "cash_trap_days": rec.get("cash_trap_days"),
                "sharpe": rec.get("sharpe"),
                "avg_cash": rec.get("avg_cash_weight"),
                "trade_count": rec.get("trade_count"),
                "fees": rec.get("total_fees_usd"),
                "metric_mode": rec.get("metric_mode"),
                "buy_reason": "case_selection_rule",
                "sell_reason": "broker_target_exit",
                "hold_reason": "hold_replace_enabled" if bool(rec.get("hold_replace_enabled")) else "",
                "replace_reason": "leader_or_lane_replacement",
                "crisis_action_reason": "lane_aware_crisis_overlay" if bool(rec.get("crisis_overlay")) else "",
                "lane_reason": rec.get("selection_layer"),
                "theme_reason": "theme_or_leader_selection",
                "evidence_reason": "top7_or_smart_money_confirmation" if str(rec.get("selection_layer")) == "multi_lane" else "",
            }
        )
    return rows


def summarize(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame()
    d = rows.copy()
    d["cagr"] = pd.to_numeric(d["cagr"], errors="coerce")
    d["max_dd"] = pd.to_numeric(d["max_dd"], errors="coerce")
    d["avg_cash"] = pd.to_numeric(d["avg_cash"], errors="coerce")
    out = (
        d.groupby(["strategy_family", "portfolio_kind"], dropna=False)
        .agg(
            variant_count=("variant_id", "count"),
            median_cagr=("cagr", "median"),
            best_cagr=("cagr", "max"),
            median_max_dd=("max_dd", "median"),
            best_max_dd=("max_dd", "max"),
            median_avg_cash=("avg_cash", "median"),
        )
        .reset_index()
    )
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--integrated-output", default="outputs/integrated_theme_leader_crisis_replay")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--commit-sha", default="")
    parser.add_argument("--artifact-id", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    integrated = repo_path(args.integrated_output)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    rows.extend(official_rows(latest_run, args.run_id, args.commit_sha, args.artifact_id))
    rows.extend(market_leader_rows(latest_run, args.run_id, args.commit_sha, args.artifact_id))
    rows.extend(integrated_rows(integrated, args.run_id, args.commit_sha, args.artifact_id))
    ledger = pd.DataFrame(rows)
    if not ledger.empty:
        ledger.insert(0, "generated_at_utc", datetime.now(timezone.utc).isoformat())
    ledger.to_csv(output_dir / "strategy_logic_ledger.csv", index=False)
    summary = summarize(ledger)
    summary.to_csv(output_dir / "logic_family_summary.csv", index=False)
    summary.to_csv(output_dir / "strategy_outcome_matrix.csv", index=False)
    summary.to_csv(output_dir / "best_logic_by_regime.csv", index=False)
    write_json(
        output_dir / "summary.json",
        {
            "status": "completed",
            "row_count": int(len(ledger)),
            "research_only": True,
            "production_activation_allowed": False,
            "ledger_path": str(output_dir / "strategy_logic_ledger.csv"),
        },
    )
    (output_dir / "report.md").write_text(
        "# Strategy Logic Ledger\n\n"
        f"- Rows: `{len(ledger)}`\n"
        "- Records strategy family, metrics, cash, fees, and decision attribution reasons.\n",
        encoding="utf-8",
    )
    print(f"[strategy-ledger] wrote {output_dir / 'strategy_logic_ledger.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

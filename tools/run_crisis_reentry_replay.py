#!/usr/bin/env python3
"""Replay crisis cash ladders and staged bargain re-entry policies.

Research-only sidecar. It starts from the exported main monthly holdings,
aligns the book to reported backtest cash, then applies macro-policy cash
floors and staged re-entry rules. It is designed to test the user's desired
behavior:

  - keep cash low in normal markets,
  - raise cash quickly in red/crisis regimes,
  - redeploy cash gradually when recovery/bottoming evidence appears.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from run_main_cash_drag_replay import (
    CASH_TICKER,
    align_to_reported_cash,
    approx_turnover,
    monthly_return,
    performance_metrics,
    repo_path,
    safe_float,
    write_json,
)


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/crisis_reentry_replay"


POLICIES: dict[str, dict[str, Any]] = {
    "crisis_ladder": {
        "green_floor": 0.03,
        "yellow_floor": 0.10,
        "red_floor": 0.30,
        "crisis_floor": 0.50,
        "recovery_floor": 0.10,
        "reentry_release_step": 0.20,
        "single_name_cap": 0.22,
    },
    "bargain_reentry": {
        "green_floor": 0.02,
        "yellow_floor": 0.10,
        "red_floor": 0.32,
        "crisis_floor": 0.52,
        "recovery_floor": 0.05,
        "reentry_release_step": 0.25,
        "single_name_cap": 0.25,
    },
    "fast_reentry": {
        "green_floor": 0.00,
        "yellow_floor": 0.08,
        "red_floor": 0.28,
        "crisis_floor": 0.50,
        "recovery_floor": 0.03,
        "reentry_release_step": 0.35,
        "single_name_cap": 0.25,
    },
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def calc_equity_rows(monthly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    rows_by_policy: dict[str, list[dict[str, Any]]] = {}
    for row in monthly_rows:
        rows_by_policy.setdefault(str(row.get("policy_id", "unknown")), []).append(row)
    for policy_id in sorted(rows_by_policy):
        equity = 1.0
        peak = 1.0
        policy_rows = sorted(rows_by_policy[policy_id], key=lambda row: str(row.get("rebalance_date", "")))
        for row in policy_rows:
            ret = safe_float(row.get("net_return"), 0.0)
            equity *= 1.0 + ret
            peak = max(peak, equity)
            out.append({**row, "equity": equity, "drawdown": equity / peak - 1.0})
    return out


def policy_floor(state: str, policy: dict[str, Any]) -> float:
    key = str(state or "green").lower()
    if key == "crisis":
        return safe_float(policy.get("crisis_floor"), 0.50)
    if key == "red":
        return safe_float(policy.get("red_floor"), 0.30)
    if key == "yellow":
        return safe_float(policy.get("yellow_floor"), 0.10)
    if key == "recovery":
        return safe_float(policy.get("recovery_floor"), 0.10)
    return safe_float(policy.get("green_floor"), 0.03)


def target_cash_for_month(
    *,
    state: str,
    policy: dict[str, Any],
    prev_target_cash: float,
    drawdown_before: float,
    drawdown_after: float,
) -> tuple[float, str]:
    state = str(state or "green").lower()
    floor = policy_floor(state, policy)
    if state in {"red", "crisis"}:
        return max(prev_target_cash, floor), f"raise_or_hold_{state}_floor"
    if state == "yellow":
        release = safe_float(policy.get("reentry_release_step"), 0.20)
        return max(floor, prev_target_cash - release), "yellow_partial_redeploy"
    if state == "recovery":
        release = safe_float(policy.get("reentry_release_step"), 0.20)
        target = max(floor, prev_target_cash - release)
        return target, "bargain_reentry_step"
    if prev_target_cash > floor and drawdown_before > -0.05 and drawdown_after > -0.05:
        release = safe_float(policy.get("reentry_release_step"), 0.20)
        return max(floor, prev_target_cash - release), "green_redeploy_step"
    return floor, "normal_low_cash"


def adjust_group_to_cash(group: pd.DataFrame, target_cash: float, single_name_cap: float) -> pd.DataFrame:
    g = group.copy()
    g["ticker"] = g["ticker"].astype(str).str.upper()
    g["weight"] = pd.to_numeric(g["weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
    cash_mask = g["ticker"].eq(CASH_TICKER)
    stocks = g.loc[~cash_mask].copy()
    target_cash = float(np.clip(target_cash, 0.0, 1.0))
    target_stock_total = max(0.0, 1.0 - target_cash)
    stock_sum = float(stocks["weight"].sum())
    if stock_sum > 1e-12:
        if target_stock_total <= stock_sum:
            stocks["weight"] = stocks["weight"] * (target_stock_total / stock_sum)
            final_cash = target_cash
        else:
            headroom = (float(single_name_cap) - stocks["weight"]).clip(lower=0.0)
            add_total = min(target_stock_total - stock_sum, float(headroom.sum()))
            if add_total > 1e-12 and float(headroom.sum()) > 1e-12:
                stocks["weight"] = stocks["weight"] + add_total * (headroom / float(headroom.sum()))
            final_cash = max(0.0, 1.0 - float(stocks["weight"].sum()))
    else:
        final_cash = 1.0

    cash_row = {col: "" for col in g.columns}
    cash_row.update({
        "rebalance_date": str(g["rebalance_date"].iloc[0]) if not g.empty and "rebalance_date" in g.columns else "",
        "ticker": CASH_TICKER,
        "Name": "Cash" if "Name" in g.columns else "",
        "sector": "Cash" if "sector" in g.columns else "",
        "weight": final_cash,
        "portfolio_sleeve_label": "cash" if "portfolio_sleeve_label" in g.columns else "",
        "portfolio_sleeve_role": "cash" if "portfolio_sleeve_role" in g.columns else "",
        "period_forward_return": 0.0 if "period_forward_return" in g.columns else "",
        "weighted_forward_return": 0.0 if "weighted_forward_return" in g.columns else "",
    })
    return pd.concat([stocks, pd.DataFrame([cash_row])], ignore_index=True)


def load_macro_policy(latest_run: Path) -> pd.DataFrame:
    for rel in ("macro_policy_engine/macro_policy_by_month.csv", "outputs/macro_policy_engine/macro_policy_by_month.csv"):
        path = latest_run / rel
        if path.exists():
            frame = pd.read_csv(path)
            frame["rebalance_date"] = pd.to_datetime(frame["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
            return frame
    return pd.DataFrame()


def replay(
    df: pd.DataFrame,
    macro: pd.DataFrame,
    policy_id: str,
    policy: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], pd.DataFrame]:
    d = df.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    d = d.dropna(subset=["rebalance_date", "ticker"])
    macro_idx = {str(row["rebalance_date"]): row for _, row in macro.iterrows()} if not macro.empty else {}
    monthly_rows: list[dict[str, Any]] = []
    policy_rows: list[dict[str, Any]] = []
    holdings_rows: list[pd.DataFrame] = []
    prev_cash = 0.03
    weights_by_month: dict[str, dict[str, float]] = {}
    for date, group in d.groupby("rebalance_date", sort=True):
        macro_row = macro_idx.get(str(date), {})
        state = str(macro_row.get("macro_risk_state", "green") or "green")
        dd_before = safe_float(macro_row.get("drawdown_before_month"), 0.0)
        dd_after = safe_float(macro_row.get("drawdown_after_month"), 0.0)
        target_cash, action = target_cash_for_month(
            state=state,
            policy=policy,
            prev_target_cash=prev_cash,
            drawdown_before=dd_before,
            drawdown_after=dd_after,
        )
        adj = adjust_group_to_cash(group, target_cash, safe_float(policy.get("single_name_cap"), 0.22))
        realized_cash = float(adj.loc[adj["ticker"].astype(str).str.upper().eq(CASH_TICKER), "weight"].sum())
        ret = monthly_return(adj)
        monthly_rows.append({
            "policy_id": policy_id,
            "rebalance_date": date,
            "macro_risk_state": state,
            "macro_style_state": macro_row.get("macro_style_state", ""),
            "target_cash": target_cash,
            "realized_cash": realized_cash,
            "policy_action": action,
            "net_return": ret,
        })
        policy_rows.append({
            "policy_id": policy_id,
            "rebalance_date": date,
            "macro_risk_state": state,
            "macro_style_state": macro_row.get("macro_style_state", ""),
            "recommended_action": macro_row.get("recommended_action", ""),
            "target_cash": target_cash,
            "realized_cash": realized_cash,
            "policy_action": action,
            "single_name_cap": safe_float(policy.get("single_name_cap"), 0.22),
        })
        weights_by_month[str(date)] = {
            str(row["ticker"]).upper(): safe_float(row["weight"], 0.0)
            for _, row in adj.iterrows()
        }
        h = adj.copy()
        h["policy_id"] = policy_id
        holdings_rows.append(h)
        prev_cash = realized_cash
    metrics = performance_metrics(pd.Series([row["net_return"] for row in monthly_rows]))
    metrics.update({
        "policy_id": policy_id,
        "avg_cash_weight": float(np.mean([row["realized_cash"] for row in monthly_rows])) if monthly_rows else float("nan"),
        "avg_turnover_monthly": approx_turnover(weights_by_month),
        "research_only": True,
        "production_activation_allowed": False,
    })
    holdings = pd.concat(holdings_rows, ignore_index=True) if holdings_rows else pd.DataFrame()
    return metrics, monthly_rows, policy_rows, holdings


def render_report(summary: dict[str, Any], ranking: list[dict[str, Any]]) -> str:
    lines = [
        "# Crisis Ladder + Bargain Reentry Replay",
        "",
        "Research-only replay. Production weights are unchanged.",
        "",
        f"- Status: `{summary.get('status')}`",
        f"- Source cash: `{summary.get('cash_alignment', {}).get('cash_source', '')}`",
        f"- Production CAGR / MaxDD: {safe_float(summary.get('production_metrics', {}).get('cagr')):.2%} / {safe_float(summary.get('production_metrics', {}).get('max_dd')):.2%}",
        "",
        "| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in ranking:
        lines.append(
            f"| `{row.get('policy_id')}` | {safe_float(row.get('cagr')):.2%} | "
            f"{safe_float(row.get('sharpe')):.3f} | {safe_float(row.get('max_dd')):.2%} | "
            f"{safe_float(row.get('avg_cash_weight')):.2%} | {safe_float(row.get('avg_turnover_monthly')):.2%} | "
            f"{str(row.get('production_activation_allowed')).lower()} |"
        )
    lines.extend([
        "",
        "## Limits",
        "",
        "- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.",
        "- It tests cash timing only; it does not discover new tickers.",
        "- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.",
        "",
    ])
    return "\n".join(lines)


def run(latest_run: Path, output_dir: Path) -> dict[str, Any]:
    holdings_path = latest_run / "reports" / "main_monthly_weights.csv"
    regime_path = latest_run / "reports" / "regime_by_month.csv"
    if not holdings_path.exists() or not regime_path.exists():
        payload = {
            "status": "blocked",
            "reason": "missing reports/main_monthly_weights.csv or reports/regime_by_month.csv",
            "research_only": True,
            "production_activation_allowed": False,
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "metrics.json", payload)
        (output_dir / "replay_report.md").write_text("# Crisis Reentry Replay\n\nBlocked: missing monthly artifacts.\n", encoding="utf-8")
        return payload

    holdings = pd.read_csv(holdings_path)
    regime = pd.read_csv(regime_path)
    aligned, cash_alignment = align_to_reported_cash(holdings, regime)
    macro = load_macro_policy(latest_run)
    if macro.empty:
        payload = {
            "status": "blocked",
            "reason": "missing macro_policy_engine/macro_policy_by_month.csv",
            "research_only": True,
            "production_activation_allowed": False,
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "metrics.json", payload)
        (output_dir / "replay_report.md").write_text("# Crisis Reentry Replay\n\nBlocked: missing macro policy output.\n", encoding="utf-8")
        return payload

    output_dir.mkdir(parents=True, exist_ok=True)
    ranking: list[dict[str, Any]] = []
    all_monthly: list[dict[str, Any]] = []
    all_policy: list[dict[str, Any]] = []
    holdings_parts: list[pd.DataFrame] = []
    for policy_id, policy in POLICIES.items():
        metrics, monthly_rows, policy_rows, holdings_out = replay(aligned, macro, policy_id, policy)
        ranking.append(metrics)
        all_monthly.extend(monthly_rows)
        all_policy.extend(policy_rows)
        if not holdings_out.empty:
            holdings_parts.append(holdings_out)
    ranking = sorted(ranking, key=lambda row: safe_float(row.get("cagr"), -1.0), reverse=True)
    monthly_curve = calc_equity_rows(all_monthly)
    production = read_json(latest_run / "backtest_metrics.json")
    summary = {
        "status": "completed",
        "experiment_id": "crisis_reentry_replay",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cash_alignment": cash_alignment,
        "production_metrics": {
            key: production.get(key)
            for key in ["cagr", "sharpe", "max_dd", "avg_cash_weight", "avg_turnover_monthly", "months"]
            if key in production
        },
        "ranking": ranking,
        "best_by_cagr": ranking[0] if ranking else {},
        "research_only": True,
        "production_activation_allowed": False,
    }
    pd.DataFrame(ranking).to_csv(output_dir / "comparison.csv", index=False)
    pd.DataFrame(all_policy).to_csv(output_dir / "policy_by_month.csv", index=False)
    pd.DataFrame(all_monthly).to_csv(output_dir / "monthly.csv", index=False)
    pd.DataFrame(monthly_curve).to_csv(output_dir / "equity_curve.csv", index=False)
    if holdings_parts:
        pd.concat(holdings_parts, ignore_index=True).to_csv(output_dir / "holdings.csv", index=False)
    write_json(output_dir / "metrics.json", summary)
    (output_dir / "replay_report.md").write_text(render_report(summary, ranking), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(repo_path(args.latest_run), repo_path(args.output_dir))
    print(json.dumps({
        "status": payload.get("status"),
        "best_by_cagr": payload.get("best_by_cagr"),
        "production_activation_allowed": payload.get("production_activation_allowed"),
    }, indent=2, sort_keys=True))
    return 0 if payload.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

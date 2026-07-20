#!/usr/bin/env python3
"""Evaluate one fixed Run287 crisis-policy replay without tuning thresholds."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STRESS_WINDOWS = {
    "2011_us_downgrade": ("2011-07-01", "2011-10-31"),
    "2015_2016_growth_credit": ("2015-08-01", "2016-03-31"),
    "2018_q4": ("2018-09-01", "2018-12-31"),
    "2020_covid": ("2020-02-01", "2020-06-30"),
    "2022_bear": ("2022-01-01", "2022-12-31"),
}
DEFENSE_STATES = {"DEFENSE", "CRISIS", "DEGRADED_DATA"}
REENTRY_STATES = {"REENTRY_STAGE_1", "REENTRY_STAGE_2", "REENTRY_STAGE_3"}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def load_curve(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["equity_usd"] = pd.to_numeric(frame["equity_usd"], errors="coerce")
    return frame.dropna(subset=["date", "equity_usd"]).sort_values("date")


def max_drawdown(frame: pd.DataFrame) -> float | None:
    if frame.empty:
        return None
    equity = frame["equity_usd"].astype(float)
    return float((equity / equity.cummax() - 1.0).min())


def stress_metrics(base: pd.DataFrame, policy: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, (start, end) in STRESS_WINDOWS.items():
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        base_slice = base[base["date"].between(start_ts, end_ts)]
        policy_slice = policy[policy["date"].between(start_ts, end_ts)]
        base_dd = max_drawdown(base_slice)
        policy_dd = max_drawdown(policy_slice)
        rows.append(
            {
                "stress_window": label,
                "start": start,
                "end": end,
                "baseline_mdd": base_dd,
                "policy_mdd": policy_dd,
                "mdd_delta": (
                    policy_dd - base_dd
                    if base_dd is not None and policy_dd is not None
                    else None
                ),
                "available": bool(not base_slice.empty and not policy_slice.empty),
            }
        )
    return rows


def state_metrics(audit: pd.DataFrame, baseline: pd.DataFrame) -> dict[str, Any]:
    d = audit.copy()
    d["date"] = pd.to_datetime(d["snapshot_date"], errors="coerce").dt.normalize()
    d = d.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last")
    d["state"] = d["canonical_crisis_state"].astype(str)
    d["stock_weight"] = pd.to_numeric(d["stock_weight"], errors="coerce").fillna(0.0)
    transitions = d["state"].ne(d["state"].shift(1))
    defense_entries = d[transitions & d["state"].isin(DEFENSE_STATES)]
    reentries = d[transitions & d["state"].isin(REENTRY_STATES)]
    base = baseline.set_index("date")["equity_usd"].sort_index()
    false_defense = 0
    episode_rows: list[dict[str, Any]] = []
    for row in defense_entries.itertuples(index=False):
        forward = base[base.index >= row.date].iloc[:64]
        drawdown = float((forward / forward.iloc[0] - 1.0).min()) if len(forward) >= 2 else None
        false = drawdown is not None and drawdown > -0.05
        false_defense += int(false)
        episode_rows.append(
            {
                "entry_date": row.date.date().isoformat(),
                "state": row.state,
                "baseline_forward_63_session_drawdown": drawdown,
                "false_defense_no_5pct_drawdown": false,
            }
        )
    false_reentry = 0
    for row in reentries.itertuples(index=False):
        future = d[d["date"] > row.date].head(3)
        false_reentry += int(future["state"].isin(DEFENSE_STATES).any())
    recovery_days: dict[str, list[int]] = {key: [] for key in ("25", "50", "75", "95")}
    for row in defense_entries.itertuples(index=False):
        prior_green = d[(d["date"] < row.date) & d["state"].eq("GREEN")]
        normal_gross = float(prior_green.iloc[-1]["stock_weight"]) if not prior_green.empty else 1.0
        future = d[d["date"] > row.date]
        for pct in (25, 50, 75, 95):
            reached = future[future["stock_weight"] >= normal_gross * pct / 100.0]
            if not reached.empty:
                recovery_days[str(pct)].append(
                    int(np.busday_count(row.date.date(), reached.iloc[0]["date"].date()))
                )
    green = d[d["state"].eq("GREEN")]
    cash_trap_rows = green[pd.to_numeric(green["cash_weight"], errors="coerce").fillna(0.0) > 0.25]
    return {
        "state_counts": {str(k): int(v) for k, v in d["state"].value_counts().items()},
        "defense_episode_count": int(len(defense_entries)),
        "false_defense_episode_count": false_defense,
        "reentry_episode_count": int(len(reentries)),
        "false_reentry_redefense_count": false_reentry,
        "cash_trap_snapshot_count": int(len(cash_trap_rows)),
        "reentry_recovery_business_days": {
            pct: {
                "observations": len(values),
                "median": float(np.median(values)) if values else None,
                "maximum": int(max(values)) if values else None,
            }
            for pct, values in recovery_days.items()
        },
        "episode_metrics": episode_rows,
    }


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    baseline = load_curve(Path(args.baseline_equity))
    policy = load_curve(Path(args.policy_equity))
    audit = pd.read_csv(args.state_audit, low_memory=False)
    broker = read_json(Path(args.broker_metrics))
    baseline_metrics = read_json(Path(args.baseline_metrics)) if args.baseline_metrics else {}
    stress = stress_metrics(baseline, policy)
    states = state_metrics(audit, baseline)
    full_mdd_base = max_drawdown(baseline)
    full_mdd_policy = max_drawdown(policy)
    cagr_delta = (
        float(broker.get("cagr")) - float(baseline_metrics.get("cagr"))
        if broker.get("cagr") is not None and baseline_metrics.get("cagr") is not None
        else None
    )
    promotion_failures: list[str] = []
    if cagr_delta is not None and cagr_delta < 0:
        promotion_failures.append("negative_full_period_cagr_delta")
    if any(
        row["available"] and row["mdd_delta"] is not None and row["mdd_delta"] < -0.03
        for row in stress
    ):
        promotion_failures.append("stress_window_mdd_worse_than_3pp")
    if states["cash_trap_snapshot_count"] > 0:
        promotion_failures.append("green_cash_trap_detected")
    payload = {
        "schema_version": "run287-crisis-policy-evaluation-v1",
        "status": "REJECTED_POLICY_PROMOTION" if promotion_failures else "REVIEW_READY",
        "promotion_failures": promotion_failures,
        "full_period": {
            "baseline_cagr": baseline_metrics.get("cagr"),
            "policy_cagr": broker.get("cagr"),
            "cagr_delta": cagr_delta,
            "baseline_mdd": full_mdd_base,
            "policy_mdd": full_mdd_policy,
            "mdd_delta": (
                full_mdd_policy - full_mdd_base
                if full_mdd_policy is not None and full_mdd_base is not None
                else None
            ),
            "policy_sharpe": broker.get("sharpe"),
            "turnover_gross_traded_usd": broker.get("gross_traded_usd"),
            "trade_count": broker.get("trade_count"),
            "fees_usd": broker.get("total_fees_usd"),
        },
        "stress_windows": stress,
        "state_evaluation": states,
        "research_only": True,
        "production_enabled": False,
        "live_trading_enabled": False,
        "threshold_grid_search_executed": False,
        "fullrun_executed": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-audit", required=True)
    parser.add_argument("--baseline-equity", required=True)
    parser.add_argument("--policy-equity", required=True)
    parser.add_argument("--broker-metrics", required=True)
    parser.add_argument("--baseline-metrics", default="")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    result = evaluate(parse_args())
    print(json.dumps({"status": result["status"], "promotion_failures": result["promotion_failures"]}, indent=2))

#!/usr/bin/env python3
"""Position-aware monthly risk replay for challenger holdings.

This is a monthly proxy, not an intraday stop simulator. It answers whether
position-level stop/decay rules are likely to reduce drawdown without the
large CAGR drag seen in blunt portfolio cash breakers.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from historical_replay_lib import (
    blocked_payload,
    calc_metrics,
    equity_curve_rows,
    read_table,
    repo_path,
    safe_float,
    worst_month_rows,
    write_json,
    write_rows,
    write_text,
)


DEFAULT_INPUT = "outputs/main_v2_backtest/monthly_holdings.csv"
DEFAULT_OUT_DIR = "outputs/position_aware_risk_replay"


def exit_signal(row: dict[str, Any], cumulative_return: float, peak_return: float, hard_stop: float, trailing_stop: float) -> tuple[bool, str]:
    period_return = safe_float(row.get("period_forward_return"), 0.0)
    drawdown_from_peak = (1.0 + cumulative_return) / max(1.0 + peak_return, 1e-8) - 1.0
    exit_risk = max(
        safe_float(row.get("explosion_exit_score"), 0.0),
        safe_float(row.get("stage2_overext_penalty"), 0.0),
        safe_float(row.get("risk_penalty"), 0.0),
    )
    rs_accel = safe_float(row.get("rs_acceleration_score"), 0.0)
    if period_return <= hard_stop:
        return True, "hard_stop"
    if drawdown_from_peak <= trailing_stop and cumulative_return > 0.15:
        return True, "trailing_stop_after_profit"
    if exit_risk >= 0.85 and rs_accel < 0:
        return True, "distribution_risk_decay"
    return False, "hold"


def replay(holdings_path: Path, output_dir: Path, hard_stop: float, trailing_stop: float) -> dict[str, Any]:
    frame = read_table(holdings_path)
    if frame.empty:
        return blocked_payload("monthly holdings input is empty or missing", holdings_path, output_dir, "position_aware_risk_replay")
    if "rebalance_date" not in frame.columns or "ticker" not in frame.columns or "weight" not in frame.columns:
        return blocked_payload("monthly holdings input lacks rebalance_date/ticker/weight", holdings_path, output_dir, "position_aware_risk_replay")

    frame = frame.copy()
    frame["rebalance_date"] = frame["rebalance_date"].astype(str).str[:10]
    state: dict[str, dict[str, float]] = {}
    monthly_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    for dt, group in frame.groupby("rebalance_date", sort=True):
        original_return = 0.0
        adjusted_return = 0.0
        exit_count = 0
        for _, row_obj in group.iterrows():
            row = row_obj.to_dict()
            ticker = str(row.get("ticker") or "").upper()
            if not ticker or ticker == "CASH":
                continue
            weight = safe_float(row.get("weight"), 0.0)
            period_return = safe_float(row.get("period_forward_return"), 0.0)
            prior = state.get(ticker, {"cum": 0.0, "peak": 0.0})
            should_exit, reason = exit_signal(row, prior["cum"], prior["peak"], hard_stop, trailing_stop)
            risk_return = max(period_return, hard_stop) if should_exit else period_return
            original_return += weight * period_return
            adjusted_return += weight * risk_return
            new_cum = (1.0 + prior["cum"]) * (1.0 + period_return) - 1.0
            state[ticker] = {"cum": new_cum, "peak": max(prior["peak"], new_cum)}
            if should_exit:
                exit_count += 1
            action_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "weight": weight,
                    "period_forward_return": period_return,
                    "risk_adjusted_return": risk_return,
                    "action": "risk_exit_proxy" if should_exit else "hold",
                    "reason": reason,
                    "cum_return_before": prior["cum"],
                    "peak_return_before": prior["peak"],
                }
            )
        monthly_rows.append(
            {
                "rebalance_date": dt,
                "original_return": original_return,
                "net_return": adjusted_return,
                "return_delta": adjusted_return - original_return,
                "risk_exit_count": exit_count,
            }
        )

    original_metrics = calc_metrics([safe_float(row.get("original_return")) for row in monthly_rows])
    adjusted_metrics = calc_metrics([safe_float(row.get("net_return")) for row in monthly_rows])
    payload = {
        "experiment_id": "position_aware_risk_replay",
        "status": "completed",
        "data_mode": "monthly_position_proxy",
        "input": str(holdings_path),
        "hard_stop": hard_stop,
        "trailing_stop": trailing_stop,
        "original": original_metrics,
        "with_position_risk": adjusted_metrics,
        "delta": {
            "cagr": safe_float(adjusted_metrics.get("cagr")) - safe_float(original_metrics.get("cagr")),
            "sharpe": safe_float(adjusted_metrics.get("sharpe")) - safe_float(original_metrics.get("sharpe")),
            "max_dd": safe_float(adjusted_metrics.get("max_dd")) - safe_float(original_metrics.get("max_dd")),
        },
        "research_only": True,
        "production_activation_allowed": False,
    }
    curve = equity_curve_rows(monthly_rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metrics.json", payload)
    write_rows(output_dir / "monthly.csv", monthly_rows)
    write_rows(output_dir / "actions.csv", action_rows)
    write_rows(output_dir / "equity_curve.csv", curve)
    write_rows(output_dir / "stress_windows.csv", worst_month_rows(curve))
    write_text(output_dir / "replay_report.md", render_report(payload))
    return payload


def render_report(payload: dict[str, Any]) -> str:
    original = payload.get("original") or {}
    adjusted = payload.get("with_position_risk") or {}
    delta = payload.get("delta") or {}
    return "\n".join(
        [
            "# Position-Aware Risk Replay",
            "",
            "Monthly proxy for hard stop, trailing stop, and distribution-risk exits.",
            "",
            f"- Original CAGR: {safe_float(original.get('cagr')):.2%}",
            f"- Risk CAGR: {safe_float(adjusted.get('cagr')):.2%}",
            f"- CAGR delta: {safe_float(delta.get('cagr')):.2%}",
            f"- Original MaxDD: {safe_float(original.get('max_dd')):.2%}",
            f"- Risk MaxDD: {safe_float(adjusted.get('max_dd')):.2%}",
            f"- MaxDD delta: {safe_float(delta.get('max_dd')):.2%}",
            "",
            "Promotion requires intramonth or weekly confirmation; this is not a broker execution rule.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings", default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--hard-stop", type=float, default=-0.08)
    parser.add_argument("--trailing-stop", type=float, default=-0.15)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    holdings_path = repo_path(args.holdings)
    output_dir = repo_path(args.output_dir)
    replay(holdings_path, output_dir, hard_stop=args.hard_stop, trailing_stop=args.trailing_stop)
    print(f"[position-aware-risk] wrote {output_dir / 'metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

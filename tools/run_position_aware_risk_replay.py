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
DEFAULT_BENCHMARK = "outputs/equity_curve.csv"
DEFAULT_OUT_DIR = "outputs/position_aware_risk_replay"


def load_benchmark_returns(path: Path) -> dict[str, float]:
    frame = read_table(path)
    if frame.empty or "rebalance_date" not in frame.columns or "bench_return" not in frame.columns:
        return {}
    out: dict[str, float] = {}
    for _, row in frame.iterrows():
        dt = str(row.get("rebalance_date") or "")[:10]
        if dt:
            out[dt] = safe_float(row.get("bench_return"), 0.0)
    return out


def is_long_hold_protected(row: dict[str, Any], cumulative_return: float, relative_return: float) -> bool:
    """Keep true winners from getting shaken out by one weak relative window."""
    monster_score = safe_float(row.get("portfolio_monster_early_score"), 0.0)
    stale_score = safe_float(row.get("portfolio_stale_mega_leader_score"), 0.0)
    risk_block = safe_float(row.get("portfolio_risk_entry_block_score"), 0.0)
    rs_accel = safe_float(row.get("rs_acceleration_score"), 0.0)
    event_risk = max(
        safe_float(row.get("theme_event_risk_sensitivity_max"), 0.35),
        safe_float(row.get("theme_event_risk_sensitivity_primary"), 0.35),
    )
    structural_growth = max(
        safe_float(row.get("theme_structural_growth_max"), 0.35),
        safe_float(row.get("theme_structural_growth_primary"), 0.35),
    )
    if risk_block >= 0.70 or stale_score >= 0.75:
        return False
    if event_risk >= 0.70 and structural_growth < 0.70:
        return False
    if monster_score >= 0.70 and rs_accel >= -0.60:
        return True
    if structural_growth >= 0.75 and cumulative_return >= 0.25 and relative_return >= -0.12 and rs_accel >= -0.85:
        return True
    if cumulative_return >= 0.50 and relative_return >= -0.08 and rs_accel >= -0.75:
        return True
    return False


def relative_underperformance_action(
    row: dict[str, Any],
    cumulative_return: float,
    benchmark_cumulative_return: float,
    trim_threshold: float,
    exit_threshold: float,
) -> tuple[str, str, float]:
    relative_return = (1.0 + cumulative_return) / max(1.0 + benchmark_cumulative_return, 1e-8) - 1.0
    protected = is_long_hold_protected(row, cumulative_return, relative_return)
    if relative_return <= exit_threshold and not protected:
        return "relative_exit_to_cash", "relative_underperformance_exit", 0.0
    if relative_return <= trim_threshold:
        return "relative_trim_50", "relative_underperformance_trim50" + ("_protected" if protected else ""), 0.50
    return "hold", "hold", 1.0


def exit_signal(
    row: dict[str, Any],
    cumulative_return: float,
    peak_return: float,
    benchmark_cumulative_return: float,
    hard_stop: float,
    trailing_stop: float,
    trim_threshold: float,
    exit_threshold: float,
) -> tuple[str, str, float, float]:
    period_return = safe_float(row.get("period_forward_return"), 0.0)
    drawdown_from_peak = (1.0 + cumulative_return) / max(1.0 + peak_return, 1e-8) - 1.0
    exit_risk = max(
        safe_float(row.get("explosion_exit_score"), 0.0),
        safe_float(row.get("stage2_overext_penalty"), 0.0),
        safe_float(row.get("risk_penalty"), 0.0),
    )
    rs_accel = safe_float(row.get("rs_acceleration_score"), 0.0)
    if period_return <= hard_stop:
        return "risk_exit_proxy", "hard_stop", 0.0, max(period_return, hard_stop)
    if drawdown_from_peak <= trailing_stop and cumulative_return > 0.15:
        return "risk_exit_proxy", "trailing_stop_after_profit", 0.0, max(period_return, hard_stop)
    if exit_risk >= 0.85 and rs_accel < 0:
        return "risk_exit_proxy", "distribution_risk_decay", 0.0, max(period_return, hard_stop)
    action, reason, multiplier = relative_underperformance_action(
        row,
        cumulative_return,
        benchmark_cumulative_return,
        trim_threshold,
        exit_threshold,
    )
    return action, reason, multiplier, period_return


def rolling_metric_rows(monthly_rows: list[dict[str, Any]], window_months: int = 36) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if len(monthly_rows) < window_months:
        return out
    for idx in range(window_months - 1, len(monthly_rows)):
        window = monthly_rows[idx - window_months + 1 : idx + 1]
        metrics = calc_metrics([safe_float(row.get("net_return")) for row in window])
        out.append(
            {
                "start_date": window[0].get("rebalance_date"),
                "end_date": window[-1].get("rebalance_date"),
                "months": window_months,
                "cagr": metrics.get("cagr"),
                "sharpe": metrics.get("sharpe"),
                "max_dd": metrics.get("max_dd"),
                "ending_equity": metrics.get("ending_equity"),
            }
        )
    return out


def cost_sensitivity_rows(monthly_rows: list[dict[str, Any]], bps_values: list[float]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for bps in bps_values:
        returns = [
            safe_float(row.get("gross_defended_return"))
            - safe_float(row.get("defense_turnover")) * (float(bps) / 10000.0)
            for row in monthly_rows
        ]
        metrics = calc_metrics(returns)
        out.append(
            {
                "cost_bps": float(bps),
                "cagr": metrics.get("cagr"),
                "sharpe": metrics.get("sharpe"),
                "max_dd": metrics.get("max_dd"),
                "ending_equity": metrics.get("ending_equity"),
            }
        )
    return out


def replay(
    holdings_path: Path,
    output_dir: Path,
    hard_stop: float,
    trailing_stop: float,
    benchmark_path: Path | None = None,
    trim_threshold: float = -0.06,
    exit_threshold: float = -0.12,
    trim_weight: float = 0.50,
    cost_bps: float = 25.0,
) -> dict[str, Any]:
    frame = read_table(holdings_path)
    if frame.empty:
        return blocked_payload("monthly holdings input is empty or missing", holdings_path, output_dir, "position_aware_risk_replay")
    if "rebalance_date" not in frame.columns or "ticker" not in frame.columns or "weight" not in frame.columns:
        return blocked_payload("monthly holdings input lacks rebalance_date/ticker/weight", holdings_path, output_dir, "position_aware_risk_replay")

    frame = frame.copy()
    frame["rebalance_date"] = frame["rebalance_date"].astype(str).str[:10]
    benchmark_returns = load_benchmark_returns(benchmark_path) if benchmark_path is not None else {}
    state: dict[str, dict[str, float]] = {}
    monthly_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    defensive_rows: list[dict[str, Any]] = []
    for dt, group in frame.groupby("rebalance_date", sort=True):
        original_return = 0.0
        gross_defended_return = 0.0
        defense_turnover = 0.0
        exit_count = 0
        trim_count = 0
        cash_after_defense = 0.0
        bench_return = safe_float(benchmark_returns.get(str(dt), 0.0), 0.0)
        for _, row_obj in group.iterrows():
            row = row_obj.to_dict()
            ticker = str(row.get("ticker") or "").upper()
            if not ticker or ticker == "CASH":
                continue
            weight = safe_float(row.get("weight"), 0.0)
            period_return = safe_float(row.get("period_forward_return"), 0.0)
            prior = state.get(ticker, {"cum": 0.0, "peak": 0.0, "bench_cum": 0.0})
            action, reason, multiplier, risk_return = exit_signal(
                row,
                prior["cum"],
                prior["peak"],
                prior["bench_cum"],
                hard_stop,
                trailing_stop,
                trim_threshold,
                exit_threshold,
            )
            if action == "relative_trim_50":
                multiplier = min(max(trim_weight, 0.0), 1.0)
            defended_weight = weight * multiplier
            reduced_weight = max(weight - defended_weight, 0.0)
            cash_after_defense += reduced_weight
            defense_turnover += reduced_weight
            original_return += weight * period_return
            if action == "risk_exit_proxy":
                gross_defended_return += weight * risk_return
            else:
                gross_defended_return += defended_weight * period_return
            new_cum = (1.0 + prior["cum"]) * (1.0 + period_return) - 1.0
            new_bench_cum = (1.0 + prior["bench_cum"]) * (1.0 + bench_return) - 1.0
            if multiplier <= 0.0:
                state[ticker] = {"cum": 0.0, "peak": 0.0, "bench_cum": 0.0}
            else:
                state[ticker] = {"cum": new_cum, "peak": max(prior["peak"], new_cum), "bench_cum": new_bench_cum}
            if action in {"risk_exit_proxy", "relative_exit_to_cash"}:
                exit_count += 1
            if action == "relative_trim_50":
                trim_count += 1
            relative_return_before = (1.0 + prior["cum"]) / max(1.0 + prior["bench_cum"], 1e-8) - 1.0
            action_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "weight": weight,
                    "defended_weight": defended_weight,
                    "period_forward_return": period_return,
                    "bench_return": bench_return,
                    "risk_adjusted_return": risk_return,
                    "action": action,
                    "reason": reason,
                    "cum_return_before": prior["cum"],
                    "peak_return_before": prior["peak"],
                    "benchmark_cum_return_before": prior["bench_cum"],
                    "relative_return_before": relative_return_before,
                }
            )
            defensive_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "original_weight": weight,
                    "defended_weight": defended_weight,
                    "cash_after_defense": "",
                    "list_action": action,
                    "reason": reason,
                    "period_forward_return": period_return,
                    "bench_return": bench_return,
                    "risk_adjusted_return": risk_return,
                    "risk_return_cap": hard_stop,
                    "risk_exit_proxy": action == "risk_exit_proxy",
                    "relative_trim_or_exit": action in {"relative_trim_50", "relative_exit_to_cash"},
                    "sector": row.get("sector", ""),
                    "regime_state": row.get("regime_state", ""),
                    "theme_horizon_primary": row.get("theme_horizon_primary", ""),
                    "theme_holding_profile_primary": row.get("theme_holding_profile_primary", ""),
                    "theme_event_risk_sensitivity_max": row.get("theme_event_risk_sensitivity_max", ""),
                    "theme_structural_growth_max": row.get("theme_structural_growth_max", ""),
                    "score": row.get("score", ""),
                    "main_v2_score": row.get("main_v2_score", ""),
                    "risk_penalty": row.get("risk_penalty", ""),
                    "stage2_overext_penalty": row.get("stage2_overext_penalty", ""),
                    "explosion_exit_score": row.get("explosion_exit_score", ""),
                    "rs_acceleration_score": row.get("rs_acceleration_score", ""),
                }
            )
        if cash_after_defense > 0:
            defensive_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": "CASH",
                    "original_weight": 0.0,
                    "defended_weight": cash_after_defense,
                    "cash_after_defense": cash_after_defense,
                    "list_action": "cash_from_risk_exits",
                    "reason": "risk_exit_proxy_cash",
                    "period_forward_return": 0.0,
                    "bench_return": bench_return,
                    "risk_adjusted_return": 0.0,
                    "risk_return_cap": hard_stop,
                    "risk_exit_proxy": False,
                    "relative_trim_or_exit": False,
                    "sector": "Cash",
                    "regime_state": "",
                    "theme_horizon_primary": "",
                    "theme_holding_profile_primary": "",
                    "theme_event_risk_sensitivity_max": "",
                    "theme_structural_growth_max": "",
                    "score": "",
                    "main_v2_score": "",
                    "risk_penalty": "",
                    "stage2_overext_penalty": "",
                    "explosion_exit_score": "",
                    "rs_acceleration_score": "",
                }
            )
        cost = defense_turnover * (cost_bps / 10000.0)
        adjusted_return = gross_defended_return - cost
        monthly_rows.append(
            {
                "rebalance_date": dt,
                "original_return": original_return,
                "gross_defended_return": gross_defended_return,
                "defense_turnover": defense_turnover,
                "cost": cost,
                "net_return": adjusted_return,
                "return_delta": adjusted_return - original_return,
                "risk_exit_count": exit_count,
                "relative_trim_count": trim_count,
            }
        )

    original_metrics = calc_metrics([safe_float(row.get("original_return")) for row in monthly_rows])
    adjusted_metrics = calc_metrics([safe_float(row.get("net_return")) for row in monthly_rows])
    total_positions = len(action_rows)
    risk_exit_count = sum(1 for row in action_rows if row.get("action") == "risk_exit_proxy")
    latest_date = max((str(row.get("rebalance_date")) for row in defensive_rows), default="")
    latest_defensive_rows = [row for row in defensive_rows if str(row.get("rebalance_date")) == latest_date]
    payload = {
        "experiment_id": "position_aware_risk_replay",
        "status": "completed",
        "data_mode": "monthly_position_proxy",
        "input": str(holdings_path),
        "hard_stop": hard_stop,
        "trailing_stop": trailing_stop,
        "benchmark_path": str(benchmark_path) if benchmark_path is not None else "",
        "benchmark_rows": len(benchmark_returns),
        "relative_trim_threshold": trim_threshold,
        "relative_exit_threshold": exit_threshold,
        "relative_trim_weight": trim_weight,
        "cost_bps": cost_bps,
        "cagr": adjusted_metrics.get("cagr"),
        "sharpe": adjusted_metrics.get("sharpe"),
        "max_dd": adjusted_metrics.get("max_dd"),
        "calmar": adjusted_metrics.get("calmar"),
        "vol_ann": adjusted_metrics.get("vol_ann"),
        "ending_equity": adjusted_metrics.get("ending_equity"),
        "metric_mode": "position_aware_risk_proxy",
        "list_defense_mode": "risk_exit_trim50_exit_proxy",
        "defensive_holdings_path": str(output_dir / "defensive_holdings.csv"),
        "latest_defensive_holdings_path": str(output_dir / "defensive_latest.csv"),
        "cost_sensitivity_path": str(output_dir / "cost_sensitivity.csv"),
        "rolling_3y_path": str(output_dir / "rolling_3y.csv"),
        "risk_exit_count": risk_exit_count,
        "relative_trim_count": sum(1 for row in action_rows if row.get("action") == "relative_trim_50"),
        "relative_exit_count": sum(1 for row in action_rows if row.get("action") == "relative_exit_to_cash"),
        "risk_exit_rate": risk_exit_count / max(total_positions, 1),
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
    sensitivity = cost_sensitivity_rows(monthly_rows, [25.0, 50.0, 75.0])
    rolling = rolling_metric_rows(monthly_rows, 36)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metrics.json", payload)
    write_rows(output_dir / "monthly.csv", monthly_rows)
    write_rows(output_dir / "actions.csv", action_rows)
    write_rows(output_dir / "defensive_holdings.csv", defensive_rows)
    write_rows(output_dir / "defensive_latest.csv", latest_defensive_rows)
    write_rows(output_dir / "equity_curve.csv", curve)
    write_rows(output_dir / "cost_sensitivity.csv", sensitivity)
    write_rows(output_dir / "rolling_3y.csv", rolling)
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
            f"- Relative trims: {int(safe_float(payload.get('relative_trim_count'), 0))}",
            f"- Relative exits: {int(safe_float(payload.get('relative_exit_count'), 0))}",
            f"- Cost bps: {safe_float(payload.get('cost_bps')):.1f}",
            f"- List defense mode: `{payload.get('list_defense_mode')}`",
            f"- Defensive latest: `{payload.get('latest_defensive_holdings_path')}`",
            f"- Cost sensitivity: `{payload.get('cost_sensitivity_path', 'cost_sensitivity.csv')}`",
            f"- Rolling 3y: `{payload.get('rolling_3y_path', 'rolling_3y.csv')}`",
            "",
            "Promotion requires intramonth or weekly confirmation; this is not a broker execution rule.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings", default=DEFAULT_INPUT)
    parser.add_argument("--benchmark", default=DEFAULT_BENCHMARK)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--hard-stop", type=float, default=-0.08)
    parser.add_argument("--trailing-stop", type=float, default=-0.15)
    parser.add_argument("--relative-trim-threshold", type=float, default=-0.06)
    parser.add_argument("--relative-exit-threshold", type=float, default=-0.12)
    parser.add_argument("--relative-trim-weight", type=float, default=0.50)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    holdings_path = repo_path(args.holdings)
    benchmark_path = repo_path(args.benchmark) if args.benchmark else None
    output_dir = repo_path(args.output_dir)
    replay(
        holdings_path,
        output_dir,
        hard_stop=args.hard_stop,
        trailing_stop=args.trailing_stop,
        benchmark_path=benchmark_path,
        trim_threshold=args.relative_trim_threshold,
        exit_threshold=args.relative_exit_threshold,
        trim_weight=args.relative_trim_weight,
        cost_bps=args.cost_bps,
    )
    print(f"[position-aware-risk] wrote {output_dir / 'metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

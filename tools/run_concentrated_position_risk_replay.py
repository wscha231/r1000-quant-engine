#!/usr/bin/env python3
"""Position-risk proxy replay for historical concentrated strategy grids.

This runner uses the full concentrated holdings grid emitted by a rebuild and
caps monthly position losses at configurable hard-stop levels. It is a research
proxy, not broker execution evidence, but it makes the concentrated CAGR/DD
tradeoff visible in the same goal-search layer as the champion artifacts.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUT_DIR = "outputs/concentrated_position_risk_replay"
try:
    from r1000_config import PORTFOLIO_GOAL_TARGETS
except Exception:
    PORTFOLIO_GOAL_TARGETS = {"concentrated": {"cagr": 0.50, "max_dd": -0.18}}
TARGET = dict(PORTFOLIO_GOAL_TARGETS.get("concentrated", {"cagr": 0.50, "max_dd": -0.18}))


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if math.isnan(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_floats(value: str) -> list[float]:
    return [float(x.strip()) for x in value.split(",") if x.strip()]


def calc_metrics(monthly_returns: list[float]) -> dict[str, Any]:
    returns = [float(x) for x in monthly_returns if math.isfinite(float(x))]
    if not returns:
        return {
            "months": 0,
            "cagr": None,
            "sharpe": None,
            "max_dd": None,
            "calmar": None,
            "vol_ann": None,
            "ending_equity": 1.0,
        }
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for ret in returns:
        equity *= 1.0 + ret
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1.0)
    years = len(returns) / 12.0
    cagr = equity ** (1.0 / years) - 1.0 if years > 0 and equity > 0 else None
    mean = sum(returns) / len(returns)
    variance = sum((ret - mean) ** 2 for ret in returns) / len(returns)
    std = math.sqrt(variance)
    sharpe = (mean * 12.0) / (std * math.sqrt(12.0)) if std > 0 else 0.0
    vol_ann = std * math.sqrt(12.0)
    calmar = cagr / abs(max_dd) if cagr is not None and max_dd < 0 else None
    return {
        "months": len(returns),
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "calmar": calmar,
        "vol_ann": vol_ann,
        "ending_equity": equity,
    }


def equity_curve_rows(monthly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    equity = 1.0
    peak = 1.0
    out: list[dict[str, Any]] = []
    for row in monthly_rows:
        ret = safe_float(row.get("net_return"))
        equity *= 1.0 + ret
        peak = max(peak, equity)
        out.append(
            {
                "rebalance_date": row.get("rebalance_date"),
                "net_return": ret,
                "equity": equity,
                "drawdown": equity / peak - 1.0,
            }
        )
    return out


def worst_month_rows(curve: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    return sorted(curve, key=lambda row: safe_float(row.get("net_return")))[:limit]


def rolling_window_rows(monthly_rows: list[dict[str, Any]], months: int = 36) -> list[dict[str, Any]]:
    ordered = sorted(monthly_rows, key=lambda row: str(row.get("rebalance_date") or ""))
    if len(ordered) < months:
        return []
    out: list[dict[str, Any]] = []
    for idx in range(0, len(ordered) - months + 1):
        window = ordered[idx : idx + months]
        metrics = calc_metrics([safe_float(row.get("net_return")) for row in window])
        cagr = metrics.get("cagr")
        max_dd = metrics.get("max_dd")
        out.append(
            {
                "window_start": window[0].get("rebalance_date"),
                "window_end": window[-1].get("rebalance_date"),
                "months": months,
                "cagr": cagr,
                "sharpe": metrics.get("sharpe"),
                "max_dd": max_dd,
                "calmar": metrics.get("calmar"),
                "target_cagr": TARGET["cagr"],
                "target_max_dd": TARGET["max_dd"],
                "target_pass": bool(
                    cagr is not None
                    and cagr >= TARGET["cagr"]
                    and max_dd is not None
                    and max_dd >= TARGET["max_dd"]
                ),
            }
        )
    return out


def rolling_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "rolling_3y_windows": 0,
            "rolling_3y_pass_rate": None,
            "rolling_3y_min_cagr": None,
            "rolling_3y_worst_max_dd": None,
        }
    cagrs = [safe_float(row.get("cagr"), float("nan")) for row in rows]
    dds = [safe_float(row.get("max_dd"), float("nan")) for row in rows]
    cagrs = [value for value in cagrs if math.isfinite(value)]
    dds = [value for value in dds if math.isfinite(value)]
    return {
        "rolling_3y_windows": len(rows),
        "rolling_3y_pass_rate": sum(1 for row in rows if str(row.get("target_pass")).lower() == "true") / max(len(rows), 1),
        "rolling_3y_min_cagr": min(cagrs) if cagrs else None,
        "rolling_3y_worst_max_dd": min(dds) if dds else None,
    }


def build_defensive_holdings(
    grouped: dict[tuple[float, str, str, str, str], list[dict[str, str]]],
    best_key: tuple[float, str, str, str, float],
    monthly_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hard_stop, target_n, weighting_mode, interval = best_key[:4]
    defensive_rows: list[dict[str, Any]] = []
    for month in monthly_rows:
        dt = str(month.get("rebalance_date") or "")[:10]
        rows = grouped.get((hard_stop, target_n, weighting_mode, interval, dt), [])
        cash_after_defense = 0.0
        for row in rows:
            weight = safe_float(row.get("weight"))
            period_return = safe_float(row.get("period_forward_return"))
            should_exit = period_return < hard_stop
            risk_return = max(period_return, hard_stop)
            defended_weight = 0.0 if should_exit else weight
            if should_exit:
                cash_after_defense += weight
            defensive_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": row.get("ticker"),
                    "Name": row.get("Name", ""),
                    "sector": row.get("sector", ""),
                    "original_weight": weight,
                    "defended_weight": defended_weight,
                    "cash_after_defense": "",
                    "list_action": "move_to_cash_proxy" if should_exit else "hold",
                    "reason": "hard_stop_proxy" if should_exit else "hold",
                    "period_forward_return": period_return,
                    "risk_adjusted_return": risk_return,
                    "hard_stop": hard_stop,
                    "risk_exit_proxy": should_exit,
                    "target_n": target_n,
                    "weighting_mode": weighting_mode,
                    "active_rebalance_interval_months": interval,
                    "raw_score": row.get("raw_score", ""),
                    "concentrated_score": row.get("concentrated_score", ""),
                    "portfolio_sleeve_label": row.get("portfolio_sleeve_label", ""),
                }
            )
        if cash_after_defense > 0:
            defensive_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": "CASH",
                    "Name": "Cash from risk exits",
                    "sector": "Cash",
                    "original_weight": 0.0,
                    "defended_weight": cash_after_defense,
                    "cash_after_defense": cash_after_defense,
                    "list_action": "cash_from_risk_exits",
                    "reason": "hard_stop_proxy_cash",
                    "period_forward_return": 0.0,
                    "risk_adjusted_return": 0.0,
                    "hard_stop": hard_stop,
                    "risk_exit_proxy": False,
                    "target_n": target_n,
                    "weighting_mode": weighting_mode,
                    "active_rebalance_interval_months": interval,
                    "raw_score": "",
                    "concentrated_score": "",
                    "portfolio_sleeve_label": "cash",
                }
            )
    latest_date = max((str(row.get("rebalance_date")) for row in defensive_rows), default="")
    return defensive_rows, [row for row in defensive_rows if str(row.get("rebalance_date")) == latest_date]


def strategy_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("target_stock_names") or row.get("target_n") or ""),
        str(row.get("weighting_mode") or ""),
        str(row.get("active_rebalance_interval_months") or row.get("rebalance_interval_months") or ""),
    )


def variant_rank(metrics: dict[str, Any]) -> float:
    cagr = safe_float(metrics.get("cagr"), -1.0)
    max_dd = safe_float(metrics.get("max_dd"), -1.0)
    sharpe = safe_float(metrics.get("sharpe"))
    cagr_gap = max(0.0, TARGET["cagr"] - cagr)
    dd_gap = max(0.0, TARGET["max_dd"] - max_dd)
    target_bonus = 1000.0 if cagr_gap == 0 and dd_gap == 0 else 0.0
    return target_bonus - (cagr_gap + dd_gap) * 100.0 + cagr * 10.0 + sharpe - abs(max_dd)


def replay(
    holdings_path: Path,
    monthly_path: Path,
    output_dir: Path,
    hard_stops: list[float],
    cost_bps_grid: list[float],
) -> dict[str, Any]:
    holdings = read_rows(holdings_path)
    monthly = read_rows(monthly_path)
    if not holdings or not monthly:
        payload = {
            "experiment_id": "concentrated_position_risk_replay",
            "status": "blocked_missing_inputs",
            "data_mode": "concentrated_monthly_position_proxy",
            "holdings_path": str(holdings_path),
            "monthly_path": str(monthly_path),
            "research_only": True,
            "production_activation_allowed": False,
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "metrics.json", payload)
        write_text(output_dir / "replay_report.md", "# Concentrated Position Risk Replay\n\nBlocked: missing inputs.\n")
        return payload

    monthly_turnover: dict[tuple[str, str, str, str], float] = {}
    for row in monthly:
        key = (*strategy_key(row), str(row.get("rebalance_date") or "")[:10])
        monthly_turnover[key] = safe_float(row.get("turnover"))

    grouped: dict[tuple[float, str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in holdings:
        dt = str(row.get("rebalance_date") or "")[:10]
        if not dt:
            continue
        for hard_stop in hard_stops:
            grouped[(hard_stop, *strategy_key(row), dt)].append(row)

    variants: dict[tuple[float, str, str, str, float], list[dict[str, Any]]] = defaultdict(list)
    action_rows: list[dict[str, Any]] = []
    for key, rows in grouped.items():
        hard_stop, target_n, weighting_mode, interval, dt = key
        original_gross = 0.0
        adjusted_gross = 0.0
        exit_count = 0
        for row in rows:
            weight = safe_float(row.get("weight"))
            ret = safe_float(row.get("period_forward_return"))
            risk_ret = max(ret, hard_stop)
            original_gross += weight * ret
            adjusted_gross += weight * risk_ret
            if risk_ret != ret:
                exit_count += 1
                action_rows.append(
                    {
                        "rebalance_date": dt,
                        "ticker": row.get("ticker"),
                        "target_n": target_n,
                        "weighting_mode": weighting_mode,
                        "interval": interval,
                        "hard_stop": hard_stop,
                        "weight": weight,
                        "period_forward_return": ret,
                        "risk_adjusted_return": risk_ret,
                        "action": "hard_stop_proxy",
                    }
                )
        turn = monthly_turnover.get((target_n, weighting_mode, interval, dt), 0.0)
        for cost_bps in cost_bps_grid:
            cost = turn * (cost_bps / 10000.0)
            variants[(hard_stop, target_n, weighting_mode, interval, cost_bps)].append(
                {
                    "rebalance_date": dt,
                    "hard_stop": hard_stop,
                    "target_n": target_n,
                    "weighting_mode": weighting_mode,
                    "active_rebalance_interval_months": interval,
                    "cost_bps": cost_bps,
                    "gross_return": adjusted_gross,
                    "original_gross_return": original_gross,
                    "cost": cost,
                    "turnover": turn,
                    "net_return": adjusted_gross - cost,
                    "return_delta": adjusted_gross - original_gross,
                    "risk_exit_count": exit_count,
                    "n_positions": len(rows),
                }
            )

    comparison: list[dict[str, Any]] = []
    best_key: tuple[float, str, str, str, float] | None = None
    best_metrics: dict[str, Any] | None = None
    for key, rows in variants.items():
        ordered = sorted(rows, key=lambda row: str(row.get("rebalance_date")))
        if len(ordered) < 12:
            continue
        metrics = calc_metrics([safe_float(row.get("net_return")) for row in ordered])
        hard_stop, target_n, weighting_mode, interval, cost_bps = key
        row = {
            "hard_stop": hard_stop,
            "target_n": target_n,
            "weighting_mode": weighting_mode,
            "active_rebalance_interval_months": interval,
            "cost_bps": cost_bps,
            "cagr": metrics.get("cagr"),
            "sharpe": metrics.get("sharpe"),
            "max_dd": metrics.get("max_dd"),
            "calmar": metrics.get("calmar"),
            "ending_equity": metrics.get("ending_equity"),
            "months": metrics.get("months"),
            "target_cagr": TARGET["cagr"],
            "target_max_dd": TARGET["max_dd"],
            "target_pass": bool(
                metrics.get("cagr") is not None
                and metrics.get("cagr") >= TARGET["cagr"]
                and metrics.get("max_dd") is not None
                and metrics.get("max_dd") >= TARGET["max_dd"]
            ),
            "rank_score": variant_rank(metrics),
        }
        comparison.append(row)
        if best_metrics is None or row["rank_score"] > variant_rank(best_metrics):
            best_key = key
            best_metrics = dict(metrics)
            best_metrics.update(row)

    assert best_key is not None and best_metrics is not None
    best_monthly = sorted(variants[best_key], key=lambda row: str(row.get("rebalance_date")))
    curve = equity_curve_rows(best_monthly)
    rolling_3y = rolling_window_rows(best_monthly, months=36)
    defensive_rows, latest_defensive_rows = build_defensive_holdings(grouped, best_key, best_monthly)
    best_metrics.update(
        {
            "experiment_id": "concentrated_position_risk_replay",
            "status": "completed",
            "data_mode": "concentrated_monthly_position_proxy",
            "metric_mode": "hard_stop_proxy",
            "list_defense_mode": "hard_stop_to_cash_proxy",
            "target_cagr": TARGET["cagr"],
            "target_max_dd": TARGET["max_dd"],
            "cost_bps": best_key[4],
            "cost_bps_grid": cost_bps_grid,
            "defensive_holdings_path": str(output_dir / "defensive_holdings.csv"),
            "latest_defensive_holdings_path": str(output_dir / "defensive_latest.csv"),
            "holdings_path": str(holdings_path),
            "monthly_path": str(monthly_path),
            "research_only": True,
            "production_activation_allowed": False,
            "proxy_warning": "Monthly position-loss capping is not execution evidence; validate with weekly/intramonth prices before promotion.",
        }
    )
    best_metrics.update(rolling_summary(rolling_3y))
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metrics.json", best_metrics)
    write_rows(output_dir / "comparison.csv", sorted(comparison, key=lambda row: safe_float(row.get("rank_score")), reverse=True))
    write_rows(output_dir / "monthly.csv", best_monthly)
    write_rows(output_dir / "actions.csv", action_rows)
    write_rows(output_dir / "defensive_holdings.csv", defensive_rows)
    write_rows(output_dir / "defensive_latest.csv", latest_defensive_rows)
    write_rows(output_dir / "equity_curve.csv", curve)
    write_rows(output_dir / "rolling_3y.csv", rolling_3y)
    write_rows(output_dir / "stress_windows.csv", worst_month_rows(curve))
    write_text(output_dir / "replay_report.md", render_report(best_metrics))
    return best_metrics


def render_report(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Concentrated Position Risk Replay",
            "",
            "Research-only monthly proxy for concentrated hard-stop behavior.",
            "",
            f"- Status: `{metrics.get('status')}`",
            f"- Target N: {metrics.get('target_n')}",
            f"- Weighting: `{metrics.get('weighting_mode')}`",
            f"- Interval: {metrics.get('active_rebalance_interval_months')} month(s)",
            f"- Cost bps: {safe_float(metrics.get('cost_bps')):.1f}",
            f"- Hard stop: {safe_float(metrics.get('hard_stop')):.2%}",
            f"- Target: CAGR {safe_float(metrics.get('target_cagr')):.2%}, MaxDD {safe_float(metrics.get('target_max_dd')):.2%}",
            f"- CAGR: {safe_float(metrics.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
            f"- Target pass: {str(metrics.get('target_pass')).lower()}",
            f"- Rolling 3y pass rate: {safe_float(metrics.get('rolling_3y_pass_rate')):.2%}",
            f"- Rolling 3y min CAGR: {safe_float(metrics.get('rolling_3y_min_cagr')):.2%}",
            f"- Rolling 3y worst MaxDD: {safe_float(metrics.get('rolling_3y_worst_max_dd')):.2%}",
            f"- List defense mode: `{metrics.get('list_defense_mode')}`",
            f"- Defensive latest: `{metrics.get('latest_defensive_holdings_path')}`",
            "",
            "Promotion requires weekly/intramonth confirmation and explicit execution assumptions.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--holdings", default=None)
    parser.add_argument("--monthly", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--hard-stops", default="-0.08,-0.10,-0.12")
    parser.add_argument("--cost-bps-grid", default="25,50,75")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    holdings = repo_path(args.holdings) if args.holdings else latest_run / "reports" / "concentrated_strategy_holdings.csv"
    monthly = repo_path(args.monthly) if args.monthly else latest_run / "reports" / "concentrated_strategy_monthly.csv"
    output_dir = repo_path(args.output_dir)
    replay(holdings, monthly, output_dir, parse_floats(args.hard_stops), parse_floats(args.cost_bps_grid))
    print(f"[concentrated-position-risk] wrote {output_dir / 'metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

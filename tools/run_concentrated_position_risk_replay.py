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
from collections import defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUT_DIR = "outputs/concentrated_position_risk_replay"
TARGET = {"cagr": 0.40, "max_dd": -0.22}


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

    monthly_cost: dict[tuple[str, str, str, str], float] = {}
    for row in monthly:
        key = (*strategy_key(row), str(row.get("rebalance_date") or "")[:10])
        monthly_cost[key] = safe_float(row.get("cost"))

    grouped: dict[tuple[float, str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in holdings:
        dt = str(row.get("rebalance_date") or "")[:10]
        if not dt:
            continue
        for hard_stop in hard_stops:
            grouped[(hard_stop, *strategy_key(row), dt)].append(row)

    variants: dict[tuple[float, str, str, str], list[dict[str, Any]]] = defaultdict(list)
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
        cost = monthly_cost.get((target_n, weighting_mode, interval, dt), 0.0)
        variants[(hard_stop, target_n, weighting_mode, interval)].append(
            {
                "rebalance_date": dt,
                "hard_stop": hard_stop,
                "target_n": target_n,
                "weighting_mode": weighting_mode,
                "active_rebalance_interval_months": interval,
                "gross_return": adjusted_gross,
                "original_gross_return": original_gross,
                "cost": cost,
                "net_return": adjusted_gross - cost,
                "return_delta": adjusted_gross - original_gross,
                "risk_exit_count": exit_count,
                "n_positions": len(rows),
            }
        )

    comparison: list[dict[str, Any]] = []
    best_key: tuple[float, str, str, str] | None = None
    best_metrics: dict[str, Any] | None = None
    for key, rows in variants.items():
        ordered = sorted(rows, key=lambda row: str(row.get("rebalance_date")))
        if len(ordered) < 12:
            continue
        metrics = calc_metrics([safe_float(row.get("net_return")) for row in ordered])
        hard_stop, target_n, weighting_mode, interval = key
        row = {
            "hard_stop": hard_stop,
            "target_n": target_n,
            "weighting_mode": weighting_mode,
            "active_rebalance_interval_months": interval,
            "cagr": metrics.get("cagr"),
            "sharpe": metrics.get("sharpe"),
            "max_dd": metrics.get("max_dd"),
            "calmar": metrics.get("calmar"),
            "ending_equity": metrics.get("ending_equity"),
            "months": metrics.get("months"),
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
    best_metrics.update(
        {
            "experiment_id": "concentrated_position_risk_replay",
            "status": "completed",
            "data_mode": "concentrated_monthly_position_proxy",
            "metric_mode": "hard_stop_proxy",
            "holdings_path": str(holdings_path),
            "monthly_path": str(monthly_path),
            "research_only": True,
            "production_activation_allowed": False,
            "proxy_warning": "Monthly position-loss capping is not execution evidence; validate with weekly/intramonth prices before promotion.",
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metrics.json", best_metrics)
    write_rows(output_dir / "comparison.csv", sorted(comparison, key=lambda row: safe_float(row.get("rank_score")), reverse=True))
    write_rows(output_dir / "monthly.csv", best_monthly)
    write_rows(output_dir / "actions.csv", action_rows)
    write_rows(output_dir / "equity_curve.csv", curve)
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
            f"- Hard stop: {safe_float(metrics.get('hard_stop')):.2%}",
            f"- CAGR: {safe_float(metrics.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
            f"- Target pass: {str(metrics.get('target_pass')).lower()}",
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    holdings = repo_path(args.holdings) if args.holdings else latest_run / "reports" / "concentrated_strategy_holdings.csv"
    monthly = repo_path(args.monthly) if args.monthly else latest_run / "reports" / "concentrated_strategy_monthly.csv"
    output_dir = repo_path(args.output_dir)
    replay(holdings, monthly, output_dir, parse_floats(args.hard_stops))
    print(f"[concentrated-position-risk] wrote {output_dir / 'metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

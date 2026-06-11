#!/usr/bin/env python3
"""Historical concentrated policy replay from the candidate replay book."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from historical_replay_lib import (
    blocked_payload,
    calc_metrics,
    equity_curve_rows,
    infer_return_col,
    normalize_rebalance_frame,
    read_table,
    repo_path,
    safe_float,
    score_power_weights,
    turnover,
    worst_month_rows,
    write_json,
    write_rows,
    write_text,
)
from tools.run_broker_ledger_replay import DISABLE_CONCENTRATED_CHAMPION_FILTERS
from tools.run_broker_ledger_replay import replay as broker_ledger_replay
from r1000_concentrated_policy import (
    CONCENTRATED_POLICY_BY_REGIME,
    concentrated_conviction_score,
    entry_gate_flags,
    monster_early_score,
    risk_gate_flags,
    risk_entry_block_score,
)


DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUT_DIR = "outputs/concentrated_policy_replay"
POLICY_ID = "concentrated_balanced_research_policy"


def candidate_passes(row: dict[str, Any]) -> bool:
    return all(entry_gate_flags(row, CONCENTRATED_POLICY_BY_REGIME.get("entry")).values()) and all(risk_gate_flags(row).values())


def select_candidates(rows: list[dict[str, Any]], target_n: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        if not ticker or ticker == "CASH":
            continue
        item = dict(row)
        item["concentrated_conviction_score"] = concentrated_conviction_score(item)
        if item["concentrated_conviction_score"] <= 0:
            continue
        if not candidate_passes(item):
            continue
        selected.append(item)
    selected.sort(key=lambda row: safe_float(row.get("concentrated_conviction_score")), reverse=True)
    return selected[:target_n]


def run_variant(frame, return_col: str, target_n: int, single_cap: float, cost_bps: float) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    monthly_rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []
    prev_weights: dict[str, float] = {}
    for dt, group in frame.groupby("rebalance_date", sort=True):
        rows = group.to_dict("records")
        selected = select_candidates(rows, target_n=target_n)
        weights = score_power_weights(selected, "concentrated_conviction_score", single_name_cap=single_cap)
        turn = turnover(prev_weights, weights)
        gross_return = 0.0
        for item in selected:
            ticker = str(item.get("ticker") or "").upper()
            weight = safe_float(weights.get(ticker), 0.0)
            if weight <= 0:
                continue
            ret = safe_float(item.get(return_col), 0.0)
            gross_return += weight * ret
            holding_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "weight": weight,
                    "period_forward_return": ret,
                    "weighted_forward_return": weight * ret,
                    "concentrated_conviction_score": item.get("concentrated_conviction_score"),
                    "sector": item.get("sector", ""),
                    "regime_state": item.get("regime_state", ""),
                    "rs_acceleration_score": item.get("rs_acceleration_score", ""),
                    "stage2_overext_penalty": item.get("stage2_overext_penalty", ""),
                    "explosion_exit_score": item.get("explosion_exit_score", ""),
                    "portfolio_monster_early_score": item.get("portfolio_monster_early_score", monster_early_score(item)),
                    "portfolio_risk_entry_block_score": item.get("portfolio_risk_entry_block_score", risk_entry_block_score(item)),
                    "portfolio_defensive_rotation_action": item.get("portfolio_defensive_rotation_action", ""),
                    "target_stock_names": target_n,
                    "single_name_cap": single_cap,
                    "weighting_mode": "concentrated_conviction_score_power",
                    "active_rebalance_interval_months": 1,
                    "research_policy": POLICY_ID,
                }
            )
        cost = turn * (cost_bps / 10000.0)
        monthly_rows.append(
            {
                "rebalance_date": dt,
                "target_n": target_n,
                "single_name_cap": single_cap,
                "gross_return": gross_return,
                "cost": cost,
                "turnover": turn,
                "net_return": gross_return - cost,
                "cash_weight": max(0.0, 1.0 - sum(weights.values())),
                "n_positions": len(weights),
                "selected_tickers": ",".join(weights.keys()),
            }
        )
        prev_weights = weights
    metrics = calc_metrics([safe_float(row.get("net_return")) for row in monthly_rows])
    metrics.update(
        {
            "target_n": target_n,
            "single_name_cap": single_cap,
            "avg_turnover_monthly": sum(safe_float(row.get("turnover")) for row in monthly_rows) / max(len(monthly_rows), 1),
            "avg_cash_weight": sum(safe_float(row.get("cash_weight")) for row in monthly_rows) / max(len(monthly_rows), 1),
        }
    )
    return metrics, monthly_rows, holding_rows


def build_target_book_rows(
    holding_rows: list[dict[str, Any]],
    monthly_rows: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    cash_by_date = {str(row.get("rebalance_date")): safe_float(row.get("cash_weight")) for row in monthly_rows}
    out: list[dict[str, Any]] = []
    target_n = int(safe_float(metrics.get("target_n"), 0))
    single_cap = safe_float(metrics.get("single_name_cap"))
    for row in holding_rows:
        rebalance_date = str(row.get("rebalance_date") or "")
        ticker = str(row.get("ticker") or "").upper()
        weight = safe_float(row.get("weight"))
        if not rebalance_date or not ticker or ticker == "CASH" or weight <= 0:
            continue
        out.append(
            {
                **row,
                "rebalance_date": rebalance_date,
                "ticker": ticker,
                "weight": weight,
                "target_stock_names": target_n,
                "single_name_cap": single_cap,
                "weighting_mode": "concentrated_conviction_score_power",
                "active_rebalance_interval_months": 1,
                "research_policy": POLICY_ID,
                "metric_source": "historical_candidate_replay_book",
                "production_activation_allowed": False,
            }
        )
    for rebalance_date, cash_weight in sorted(cash_by_date.items()):
        if cash_weight <= 1e-12:
            continue
        out.append(
            {
                "rebalance_date": rebalance_date,
                "ticker": "CASH",
                "weight": cash_weight,
                "target_stock_names": target_n,
                "single_name_cap": single_cap,
                "weighting_mode": "concentrated_conviction_score_power",
                "active_rebalance_interval_months": 1,
                "research_policy": POLICY_ID,
                "metric_source": "historical_candidate_replay_book",
                "production_activation_allowed": False,
            }
        )
    return out


def attach_broker_replay_metrics(
    *,
    metrics: dict[str, Any],
    target_book: Path,
    price_cache: Path | None,
    output_dir: Path,
    run_broker_replay: bool,
    cost_bps: float,
    starting_capital: float,
    max_fill_lag_days: int,
) -> dict[str, Any]:
    metrics.update(
        {
            "broker_replay_target_book": str(target_book),
            "official_metric_required": "broker_ledger_next_close",
            "broker_replay_requested": bool(run_broker_replay),
        }
    )
    if not run_broker_replay:
        metrics.update(
            {
                "broker_replay_status": "not_requested",
                "broker_replay_notes": "Run with --run-broker-replay --price-cache cache_prices before using this candidate as production evidence.",
            }
        )
        return metrics
    if price_cache is None or not price_cache.exists():
        broker_blocked = {
            "status": "blocked",
            "reason": "missing price cache",
            "target_book": str(target_book),
            "price_cache": str(price_cache) if price_cache is not None else "",
            "metric_mode": "DO_NOT_USE",
            "valid_for_production": False,
            "research_only": True,
            "production_activation_allowed": False,
            "official_metric_required": "broker_ledger_next_close",
        }
        write_json(output_dir / "broker_replay" / "metrics.json", broker_blocked)
        metrics.update(
            {
                "broker_replay_status": "blocked",
                "broker_replay_reason": "missing price cache",
                "broker_price_cache": str(price_cache) if price_cache is not None else "",
            }
        )
        return metrics

    broker_metrics = broker_ledger_replay(
        target_book=target_book,
        price_cache=price_cache,
        output_dir=output_dir / "broker_replay",
        portfolio_kind="concentrated",
        starting_capital=starting_capital,
        fill_mode="next_close",
        cost_bps=cost_bps,
        integer_shares=True,
        max_fill_lag_days=max_fill_lag_days,
        concentrated_champion_filters=DISABLE_CONCENTRATED_CHAMPION_FILTERS.copy(),
    )
    metrics.update(
        {
            "broker_replay_status": broker_metrics.get("status"),
            "broker_metric_mode": broker_metrics.get("metric_mode"),
            "broker_valid_for_production": broker_metrics.get("valid_for_production"),
            "broker_target_book_filter_source": broker_metrics.get("target_book_filter_source"),
            "broker_cagr": broker_metrics.get("cagr"),
            "broker_sharpe": broker_metrics.get("sharpe"),
            "broker_max_dd": broker_metrics.get("max_dd"),
            "broker_avg_cash_weight": broker_metrics.get("avg_cash_weight"),
            "broker_trade_count": broker_metrics.get("trade_count"),
            "broker_total_fees_usd": broker_metrics.get("total_fees_usd"),
        }
    )
    return metrics


def pct_or_na(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    return f"{safe_float(value):.2%}"


def replay(
    candidate_book: Path,
    output_dir: Path,
    target_ns: list[int],
    single_caps: list[float],
    cost_bps: float,
    price_cache: Path | None = None,
    run_broker_replay: bool = False,
    starting_capital: float = 100000.0,
    max_fill_lag_days: int = 7,
) -> dict[str, Any]:
    frame = normalize_rebalance_frame(read_table(candidate_book))
    if frame.empty:
        return blocked_payload("candidate replay book is empty", candidate_book, output_dir, "concentrated_policy_replay")
    return_col = infer_return_col(frame)
    if return_col is None:
        return blocked_payload("candidate replay book has no period return column", candidate_book, output_dir, "concentrated_policy_replay")

    comparison: list[dict[str, Any]] = []
    best: tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]] | None = None
    for target_n in target_ns:
        for single_cap in single_caps:
            metrics, monthly_rows, holding_rows = run_variant(frame, return_col, target_n, single_cap, cost_bps)
            row = {
                "target_n": target_n,
                "single_name_cap": single_cap,
                "cagr": metrics.get("cagr"),
                "sharpe": metrics.get("sharpe"),
                "max_dd": metrics.get("max_dd"),
                "calmar": metrics.get("calmar"),
                "avg_turnover_monthly": metrics.get("avg_turnover_monthly"),
                "avg_cash_weight": metrics.get("avg_cash_weight"),
            }
            comparison.append(row)
            if best is None or safe_float(metrics.get("cagr"), -99.0) > safe_float(best[0].get("cagr"), -99.0):
                best = (metrics, monthly_rows, holding_rows)

    assert best is not None
    best_metrics, best_monthly, best_holdings = best
    best_metrics.update(
        {
            "experiment_id": "concentrated_policy_replay",
            "status": "completed",
            "data_mode": "historical_candidate_replay_book",
            "candidate_book": str(candidate_book),
            "return_column": return_col,
            "research_only": True,
            "production_activation_allowed": False,
            "max_single_cap_tested": max(single_caps) if single_caps else None,
            "policy_id": POLICY_ID,
        }
    )
    curve = equity_curve_rows(best_monthly)
    output_dir.mkdir(parents=True, exist_ok=True)
    target_book_rows = build_target_book_rows(best_holdings, best_monthly, best_metrics)
    target_book_path = output_dir / "target_book.csv"
    write_rows(target_book_path, target_book_rows)
    best_metrics = attach_broker_replay_metrics(
        metrics=best_metrics,
        target_book=target_book_path,
        price_cache=price_cache,
        output_dir=output_dir,
        run_broker_replay=run_broker_replay,
        cost_bps=cost_bps,
        starting_capital=starting_capital,
        max_fill_lag_days=max_fill_lag_days,
    )
    write_json(output_dir / "metrics.json", best_metrics)
    write_rows(output_dir / "comparison.csv", comparison)
    write_rows(output_dir / "monthly.csv", best_monthly)
    write_rows(output_dir / "holdings.csv", best_holdings)
    write_rows(output_dir / "equity_curve.csv", curve)
    write_rows(output_dir / "stress_windows.csv", worst_month_rows(curve))
    write_text(output_dir / "replay_report.md", render_report(best_metrics))
    return best_metrics


def render_report(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Concentrated Policy Replay",
            "",
            "Research-only concentrated replay from historical candidate rows.",
            "",
            f"- Status: `{metrics.get('status')}`",
            f"- Target N: {metrics.get('target_n')}",
            f"- Single cap: {pct_or_na(metrics.get('single_name_cap'))}",
            f"- CAGR: {pct_or_na(metrics.get('cagr'))}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {pct_or_na(metrics.get('max_dd'))}",
            f"- Broker replay: `{metrics.get('broker_replay_status', 'not_requested')}`",
            f"- Broker CAGR: {pct_or_na(metrics.get('broker_cagr'))}",
            f"- Broker MaxDD: {pct_or_na(metrics.get('broker_max_dd'))}",
            "",
            "Weight-level metrics are research-only. Use broker_replay/metrics.json when this candidate is compared to production evidence.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--target-ns", default="3,5,7")
    parser.add_argument("--single-caps", default="0.25,0.35,0.50")
    parser.add_argument("--cost-bps", type=float, default=50.0)
    parser.add_argument("--price-cache", default=None)
    parser.add_argument("--run-broker-replay", action="store_true")
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    return parser.parse_args()


def parse_ints(value: str) -> list[int]:
    return [int(x.strip()) for x in value.split(",") if x.strip()]


def parse_floats(value: str) -> list[float]:
    return [float(x.strip()) for x in value.split(",") if x.strip()]


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    candidate_book = repo_path(args.candidate_book) if args.candidate_book else latest_run / "reports" / "candidate_replay_book.csv"
    output_dir = repo_path(args.output_dir)
    if not candidate_book.exists():
        blocked_payload("missing reports/candidate_replay_book.csv from full rebuild", candidate_book, output_dir, "concentrated_policy_replay")
        return 0
    price_cache = repo_path(args.price_cache) if args.price_cache else None
    replay(
        candidate_book,
        output_dir,
        parse_ints(args.target_ns),
        parse_floats(args.single_caps),
        args.cost_bps,
        price_cache=price_cache,
        run_broker_replay=args.run_broker_replay,
        starting_capital=args.starting_capital,
        max_fill_lag_days=args.max_fill_lag_days,
    )
    print(f"[concentrated-policy-replay] wrote {output_dir / 'metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

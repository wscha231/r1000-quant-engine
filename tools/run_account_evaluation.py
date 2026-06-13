#!/usr/bin/env python3
"""Build the official account-level evaluation summary.

This report is the management layer for the broker-ledger replay. It treats the
account-like replay as the production evidence source and keeps legacy
weight-level backtest metrics as comparison-only context.

Inputs expected under --latest-run:
  broker_replay/<portfolio>/metrics.json
  broker_replay/<portfolio>/account_state_latest.json
  account_ledger_preview/<portfolio>/preview_metrics.json
  broker_trade_journal/<portfolio>/summary.json
  portfolio_goal_search/goal_search_summary.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from r1000_config import PORTFOLIO_GOAL_TARGETS
except Exception:  # pragma: no cover - fallback for isolated smoke contexts
    PORTFOLIO_GOAL_TARGETS = {
        "main": {"cagr": 0.35, "max_dd": -0.25},
        "concentrated": {"cagr": 0.50, "max_dd": -0.25},
    }


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/account_evaluation"
PORTFOLIOS = ("main", "concentrated")


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    out = safe_float(value)
    if out is None:
        return default
    return int(out)


def pct(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2%}"


def pp(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 100.0, 4)


def metric(row: dict[str, Any], *names: str) -> float | None:
    for name in names:
        if name in row:
            value = safe_float(row.get(name))
            if value is not None:
                return value
    return None


def legacy_metrics(latest_run: Path, portfolio: str) -> dict[str, Any]:
    if portfolio == "main":
        return read_json(latest_run / "backtest_metrics.json")
    return read_json(latest_run / "concentrated_backtest_metrics.json")


def target_for(portfolio: str) -> dict[str, float]:
    target = PORTFOLIO_GOAL_TARGETS.get(portfolio, {})
    return {
        "cagr": float(target.get("cagr", 0.30 if portfolio == "main" else 0.45)),
        "max_dd": float(target.get("max_dd", -0.25)),
    }


def summarize_portfolio(latest_run: Path, portfolio: str) -> dict[str, Any]:
    broker_metrics = read_json(latest_run / "broker_replay" / portfolio / "metrics.json")
    account_state = read_json(latest_run / "broker_replay" / portfolio / "account_state_latest.json")
    preview = read_json(latest_run / "account_ledger_preview" / portfolio / "preview_metrics.json")
    journal = read_json(latest_run / "broker_trade_journal" / portfolio / "summary.json")
    legacy = legacy_metrics(latest_run, portfolio)
    target = target_for(portfolio)

    cagr = metric(broker_metrics, "cagr", "strategy_cagr")
    max_dd = metric(broker_metrics, "max_dd", "max_drawdown")
    sharpe = metric(broker_metrics, "sharpe")
    valid_for_production = bool(broker_metrics.get("valid_for_production")) and broker_metrics.get("status") == "completed"
    cagr_pass = valid_for_production and cagr is not None and cagr >= target["cagr"]
    dd_pass = valid_for_production and max_dd is not None and max_dd >= target["max_dd"]
    cagr_gap = None if cagr is None else max(0.0, target["cagr"] - cagr)
    dd_gap = None if max_dd is None else max(0.0, target["max_dd"] - max_dd)

    return {
        "portfolio": portfolio,
        "official_metric_mode": broker_metrics.get("metric_mode") or "broker_ledger_next_close",
        "official_source": f"broker_replay/{portfolio}/metrics.json",
        "status": broker_metrics.get("status") or "missing",
        "valid_for_production": valid_for_production,
        "target_pass": bool(cagr_pass and dd_pass),
        "cagr": cagr,
        "cagr_target": target["cagr"],
        "cagr_gap_pp": pp(cagr_gap),
        "max_dd": max_dd,
        "max_dd_target": target["max_dd"],
        "max_dd_gap_pp": pp(dd_gap),
        "sharpe": sharpe,
        "total_return": metric(broker_metrics, "total_return"),
        "start_date": broker_metrics.get("start_date"),
        "end_date": broker_metrics.get("end_date"),
        "years": metric(broker_metrics, "years"),
        "starting_capital_usd": metric(broker_metrics, "starting_capital_usd"),
        "ending_capital_usd": metric(broker_metrics, "ending_capital_usd"),
        "avg_cash_weight": metric(broker_metrics, "avg_cash_weight"),
        "latest_equity_usd": metric(account_state, "equity_usd"),
        "latest_cash_usd": metric(account_state, "cash_usd"),
        "latest_cash_weight": metric(account_state, "cash_weight"),
        "latest_position_count": safe_int(account_state.get("position_count")),
        "broker_trade_count": safe_int(broker_metrics.get("trade_count")),
        "total_fees_usd": metric(broker_metrics, "total_fees_usd"),
        "gross_traded_usd": metric(broker_metrics, "gross_traded_usd"),
        "order_preview_status": preview.get("status") or "missing",
        "order_preview_count": safe_int(preview.get("order_count")),
        "order_preview_buy_count": safe_int(preview.get("buy_count")),
        "order_preview_sell_count": safe_int(preview.get("sell_count")),
        "order_preview_blocked_count": safe_int(preview.get("blocked_order_count")),
        "journal_status": journal.get("status") or "missing",
        "journal_trade_count": safe_int(journal.get("trade_count")),
        "journal_win_rate": metric(journal, "win_rate"),
        "journal_avg_realized_return": metric(journal, "avg_realized_return"),
        "journal_avg_holding_days": metric(journal, "avg_holding_days"),
        "journal_profit_factor": metric(journal, "profit_factor"),
        "legacy_metric_mode": "weight_level_research_comparison",
        "legacy_cagr": metric(legacy, "cagr", "strategy_cagr"),
        "legacy_max_dd": metric(legacy, "max_dd", "max_drawdown"),
        "legacy_sharpe": metric(legacy, "sharpe"),
    }


def summarize_goal_search(latest_run: Path) -> dict[str, Any]:
    goal = read_json(latest_run / "portfolio_goal_search" / "goal_search_summary.json")
    if not goal:
        goal = read_json(REPO_ROOT / "outputs" / "portfolio_goal_search" / "goal_search_summary.json")
    return goal


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "portfolio",
        "official_metric_mode",
        "status",
        "valid_for_production",
        "target_pass",
        "cagr",
        "cagr_target",
        "cagr_gap_pp",
        "max_dd",
        "max_dd_target",
        "max_dd_gap_pp",
        "sharpe",
        "start_date",
        "end_date",
        "years",
        "ending_capital_usd",
        "avg_cash_weight",
        "latest_cash_weight",
        "latest_position_count",
        "broker_trade_count",
        "total_fees_usd",
        "order_preview_count",
        "order_preview_buy_count",
        "order_preview_sell_count",
        "journal_trade_count",
        "journal_win_rate",
        "journal_avg_realized_return",
        "journal_avg_holding_days",
        "journal_profit_factor",
        "legacy_cagr",
        "legacy_max_dd",
        "legacy_sharpe",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def render_report(payload: dict[str, Any]) -> str:
    rows = payload.get("portfolios") or []
    lines = [
        "# Account Evaluation",
        "",
        "Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.",
        "Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.",
        "",
        "## Official Targets",
        "",
        "| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {portfolio} | {cagr} | {cagr_target} | {cagr_gap}pp | {max_dd} | {max_dd_target} | {dd_gap}pp | {sharpe:.3f} | {avg_cash} | {passed} |".format(
                portfolio=row.get("portfolio"),
                cagr=pct(row.get("cagr")),
                cagr_target=pct(row.get("cagr_target")),
                cagr_gap="" if row.get("cagr_gap_pp") is None else f"{safe_float(row.get('cagr_gap_pp'), 0.0):.2f}",
                max_dd=pct(row.get("max_dd")),
                max_dd_target=pct(row.get("max_dd_target")),
                dd_gap="" if row.get("max_dd_gap_pp") is None else f"{safe_float(row.get('max_dd_gap_pp'), 0.0):.2f}",
                sharpe=safe_float(row.get("sharpe"), 0.0) or 0.0,
                avg_cash=pct(row.get("avg_cash_weight")),
                passed=str(row.get("target_pass")).lower(),
            )
        )
    lines.extend(["", "## Account State And Orders", ""])
    lines.extend(["| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for row in rows:
        lines.append(
            "| {portfolio} | {end_date} | ${equity:,.0f} | {cash} | {positions} | {orders} | {buys} | {sells} | {blocked} |".format(
                portfolio=row.get("portfolio"),
                end_date=row.get("end_date") or "",
                equity=safe_float(row.get("ending_capital_usd"), 0.0) or 0.0,
                cash=pct(row.get("latest_cash_weight")),
                positions=row.get("latest_position_count"),
                orders=row.get("order_preview_count"),
                buys=row.get("order_preview_buy_count"),
                sells=row.get("order_preview_sell_count"),
                blocked=row.get("order_preview_blocked_count"),
            )
        )
    lines.extend(["", "## Broker Trade Journal", ""])
    lines.extend(["| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for row in rows:
        lines.append(
            "| {portfolio} | {trades} | {win_rate} | {avg_return} | {holding:.1f} | {pf:.2f} | ${fees:,.0f} |".format(
                portfolio=row.get("portfolio"),
                trades=row.get("journal_trade_count"),
                win_rate=pct(row.get("journal_win_rate")),
                avg_return=pct(row.get("journal_avg_realized_return")),
                holding=safe_float(row.get("journal_avg_holding_days"), 0.0) or 0.0,
                pf=safe_float(row.get("journal_profit_factor"), 0.0) or 0.0,
                fees=safe_float(row.get("total_fees_usd"), 0.0) or 0.0,
            )
        )
    lines.extend(["", "## Governance", ""])
    lines.append(f"- Official metric mode: `{payload.get('official_metric_mode')}`")
    lines.append(f"- Production target pass: `{str(payload.get('production_target_pass')).lower()}`")
    lines.append(f"- Research target pass: `{str(payload.get('research_target_pass')).lower()}`")
    lines.append(f"- Generated at: `{payload.get('generated_at_utc')}`")
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    portfolios = [summarize_portfolio(latest_run, name) for name in PORTFOLIOS]
    goal_search = summarize_goal_search(latest_run)
    production_target_pass = all(bool(row.get("target_pass")) for row in portfolios)
    research_target_pass = bool(goal_search.get("research_target_pass"))
    payload = {
        "schema_version": "account-evaluation-v1",
        "official_metric_mode": "broker_ledger_next_close",
        "latest_run": str(latest_run),
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "production_target_pass": production_target_pass,
        "research_target_pass": research_target_pass,
        "portfolios": portfolios,
        "goal_search_summary": goal_search,
    }
    official_metrics = {
        "schema_version": payload["schema_version"],
        "official_metric_mode": payload["official_metric_mode"],
        "production_target_pass": production_target_pass,
        "portfolios": {row["portfolio"]: row for row in portfolios},
    }
    write_json(output_dir / "account_evaluation_summary.json", payload)
    write_json(output_dir / "official_metrics.json", official_metrics)
    write_csv(output_dir / "portfolio_account_metrics.csv", portfolios)
    write_text(output_dir / "account_evaluation_report.md", render_report(payload))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    result = run(parse_args())
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

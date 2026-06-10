#!/usr/bin/env python3
"""Summarize current-vs-target execution lag and account-aware replay impact.

This is an operator-review sidecar. It does not change target books or live
score defaults. It compares the official broker-ledger replay with the
research-only account-aware execution replay so a large current/target drift can
be inspected without promoting a new production policy.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


PORTFOLIOS = ("main", "concentrated")


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def pp(value: float | None) -> float | None:
    return None if value is None else float(value) * 100.0


def metric_delta(candidate: dict[str, Any], base: dict[str, Any], key: str) -> float | None:
    lhs = safe_float(candidate.get(key), None)
    rhs = safe_float(base.get(key), None)
    if lhs is None or rhs is None:
        return None
    return float(lhs - rhs)


def preview_turnover(preview: dict[str, Any]) -> float | None:
    equity = safe_float(preview.get("equity_usd"), None)
    if equity is None or equity <= 0:
        return None
    buy = safe_float(preview.get("buy_gross_usd"), 0.0) or 0.0
    sell = safe_float(preview.get("sell_gross_usd"), 0.0) or 0.0
    return float((buy + sell) / equity)


def decision_for(row: dict[str, Any]) -> str:
    if row.get("execution_policy_status") != "completed":
        return "NO_EXECUTION_POLICY_REPLAY"
    cagr_delta = safe_float(row.get("execution_policy_cagr_delta"), None)
    mdd_improvement = safe_float(row.get("execution_policy_mdd_improvement"), None)
    trade_delta = safe_float(row.get("execution_policy_trade_count_delta"), None)
    if cagr_delta is None or mdd_improvement is None:
        return "REVIEW_REQUIRED"
    if mdd_improvement >= 0.03 and cagr_delta >= -0.005:
        return "RESEARCH_CANDIDATE_MDD_IMPROVED"
    if trade_delta is not None and trade_delta < 0 and cagr_delta >= -0.01:
        return "RESEARCH_CANDIDATE_CHURN_REDUCED"
    return "REVIEW_REQUIRED"


def build_review(latest_run: Path) -> dict[str, Any]:
    official = load_json(latest_run / "account_evaluation" / "official_metrics.json")
    cash = load_json(latest_run / "user_current" / "02_cash_summary.json")
    by_cash = cash.get("by_portfolio") if isinstance(cash.get("by_portfolio"), dict) else {}
    portfolios = official.get("portfolios") if isinstance(official.get("portfolios"), dict) else {}

    rows: list[dict[str, Any]] = []
    for portfolio in PORTFOLIOS:
        base = portfolios.get(portfolio) if isinstance(portfolios.get(portfolio), dict) else {}
        exec_metrics = load_json(latest_run / "broker_execution_policy_replay" / portfolio / "metrics.json")
        preview = load_json(latest_run / "account_ledger_preview" / portfolio / "preview_metrics.json")
        cash_row = by_cash.get(portfolio) if isinstance(by_cash.get(portfolio), dict) else {}

        cagr_delta = metric_delta(exec_metrics, base, "cagr")
        mdd_delta = metric_delta(exec_metrics, base, "max_dd")
        trade_delta = metric_delta(exec_metrics, base, "trade_count")
        fee_delta = metric_delta(exec_metrics, base, "total_fees_usd")
        row = {
            "portfolio_kind": portfolio,
            "official_metric_mode": base.get("official_metric_mode") or official.get("official_metric_mode"),
            "base_status": base.get("status", ""),
            "base_cagr": safe_float(base.get("cagr"), None),
            "base_max_dd": safe_float(base.get("max_dd"), None),
            "base_sharpe": safe_float(base.get("sharpe"), None),
            "base_trade_count": safe_float(base.get("broker_trade_count", base.get("trade_count")), None),
            "base_latest_cash_weight": safe_float(base.get("latest_cash_weight"), None),
            "execution_policy_status": exec_metrics.get("status", "missing"),
            "execution_policy_metric_mode": exec_metrics.get("metric_mode", ""),
            "execution_policy_broker_ledger_valid": bool(exec_metrics.get("broker_ledger_valid")),
            "execution_policy_valid_for_production": bool(exec_metrics.get("valid_for_production")),
            "execution_policy_research_only": bool(exec_metrics.get("research_only", True)),
            "execution_policy_cagr": safe_float(exec_metrics.get("cagr"), None),
            "execution_policy_max_dd": safe_float(exec_metrics.get("max_dd"), None),
            "execution_policy_sharpe": safe_float(exec_metrics.get("sharpe"), None),
            "execution_policy_trade_count": safe_float(exec_metrics.get("trade_count"), None),
            "execution_policy_avg_cash_weight": safe_float(exec_metrics.get("avg_cash_weight"), None),
            "execution_policy_cagr_delta": cagr_delta,
            "execution_policy_mdd_improvement": None if mdd_delta is None else float(mdd_delta),
            "execution_policy_trade_count_delta": trade_delta,
            "execution_policy_fee_delta_usd": fee_delta,
            "current_cash_weight": safe_float(cash_row.get("cash_weight"), None),
            "projected_cash_weight_after_ready_orders": safe_float(cash_row.get("projected_cash_weight"), None),
            "order_preview_turnover_estimate": preview_turnover(preview),
            "ready_order_count": safe_float(preview.get("ready_order_count"), None),
            "blocked_order_count": safe_float(preview.get("blocked_order_count"), None),
        }
        row["decision"] = decision_for(row)
        rows.append(row)

    return {
        "schema_version": "execution-lag-review-v1",
        "research_only": True,
        "production_activation_allowed": False,
        "official_metric_required": "broker_ledger_next_close",
        "summary": {
            "cash_policy_flag": cash.get("cash_policy_flag", ""),
            "combined_projected_cash_weight_after_ready_orders": cash.get(
                "combined_projected_cash_weight_after_ready_orders"
            ),
        },
        "rows": rows,
    }


def pct(value: Any) -> str:
    number = safe_float(value, None)
    return "" if number is None else f"{number:.2%}"


def number(value: Any) -> str:
    number_value = safe_float(value, None)
    return "" if number_value is None else f"{number_value:,.0f}"


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Execution Lag Review",
        "",
        "Research-only review of whether account-aware execution replay reduces current/target drift, churn, or drawdown.",
        "",
        f"- Production activation allowed: `{str(payload.get('production_activation_allowed')).lower()}`",
        f"- Official metric required: `{payload.get('official_metric_required')}`",
        f"- Cash policy flag: `{payload.get('summary', {}).get('cash_policy_flag', '')}`",
        "",
        "| Portfolio | Decision | Base CAGR | Exec CAGR | CAGR Delta | Base MDD | Exec MDD | MDD Improvement | Base Trades | Exec Trades | Preview Turnover | Current Cash | Projected Cash |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload.get("rows", []):
        lines.append(
            "| {portfolio} | `{decision}` | {base_cagr} | {exec_cagr} | {cagr_delta} | {base_mdd} | {exec_mdd} | {mdd_improvement} | {base_trades} | {exec_trades} | {turnover} | {cash} | {projected_cash} |".format(
                portfolio=row.get("portfolio_kind", ""),
                decision=row.get("decision", ""),
                base_cagr=pct(row.get("base_cagr")),
                exec_cagr=pct(row.get("execution_policy_cagr")),
                cagr_delta=pct(row.get("execution_policy_cagr_delta")),
                base_mdd=pct(row.get("base_max_dd")),
                exec_mdd=pct(row.get("execution_policy_max_dd")),
                mdd_improvement=pct(row.get("execution_policy_mdd_improvement")),
                base_trades=number(row.get("base_trade_count")),
                exec_trades=number(row.get("execution_policy_trade_count")),
                turnover=pct(row.get("order_preview_turnover_estimate")),
                cash=pct(row.get("current_cash_weight")),
                projected_cash=pct(row.get("projected_cash_weight_after_ready_orders")),
            )
        )
    lines.extend(
        [
            "",
            "Rules:",
            "- This file is operator review only; it is not a trade instruction.",
            "- `broker_ledger_execution_policy_next_close` is a research challenger metric, not the official production metric.",
            "- Promotion still requires the official broker-ledger path, stress windows, cost sensitivity, and human approval.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(payload: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "execution_lag_review.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (output_dir / "execution_lag_review.md").write_text(render_markdown(payload), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/operator_review")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_review(repo_path(args.latest_run))
    write_outputs(payload, repo_path(args.output_dir))
    print(json.dumps({"schema_version": payload["schema_version"], "rows": len(payload["rows"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

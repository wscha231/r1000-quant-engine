#!/usr/bin/env python3
"""Cost-sensitivity sidecar for broker-ledger replays.

Reruns ``run_broker_ledger_replay`` at multiple ``cost_bps`` levels and
emits a single summary JSON / Markdown table so the auto policy
challenger's ``cost_sensitivity_25_50_75_bps`` next-required-backtests
entry can be satisfied without changing strategy logic.

Default cost levels: 25, 50, 75, 100 bps per side. The sidecar is
deliberately read-only: it does not modify the source target book or
mutate any policy.

Usage
=====

    py -3 tools/run_cost_sensitivity_sidecar.py \
        --target-book outputs/reports/operating_main_target_book.csv \
        --price-cache cache_prices \
        --portfolio-kind main \
        --output-dir outputs/cost_sensitivity/main

Outputs
=======
``outputs/cost_sensitivity/<portfolio>/summary.json``
    {
      "schema_version": "cost-sensitivity-sidecar-v1",
      "portfolio_kind": "main",
      "target_book": "...",
      "baseline_cost_bps": 25.0,
      "levels": [
        {"cost_bps": 25.0, "cagr": 0.211, "sharpe": 1.003, "max_dd": -0.317,
         "ending_capital_usd": 383221.87, "total_fees_usd": 39505.43,
         "cagr_delta_pp_vs_baseline": 0.0, ...},
        ...
      ],
      "breakeven_cost_bps": 100.0
    }

``outputs/cost_sensitivity/<portfolio>/report.md``
    Human-readable comparison table.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import replay  # noqa: E402


DEFAULT_COST_BPS = [25.0, 50.0, 75.0, 100.0]
DEFAULT_BASELINE_BPS = 25.0


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def run_level(
    *,
    target_book: Path,
    price_cache: Path,
    portfolio_kind: str,
    cost_bps: float,
    starting_capital: float,
    fill_mode: str,
    max_fill_lag_days: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        metrics = replay(
            target_book=target_book,
            price_cache=price_cache,
            output_dir=tmp_path,
            portfolio_kind=portfolio_kind,
            starting_capital=starting_capital,
            fill_mode=fill_mode,
            cost_bps=cost_bps,
            integer_shares=True,
            max_fill_lag_days=max_fill_lag_days,
        )
    return metrics


def summarize(metrics: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    cagr = safe_float(metrics.get("cagr"))
    sharpe = safe_float(metrics.get("sharpe"))
    max_dd = safe_float(metrics.get("max_dd"))
    ending = safe_float(metrics.get("ending_capital_usd"))
    fees = safe_float(metrics.get("total_fees_usd"))
    row: dict[str, Any] = {
        "cost_bps": safe_float(metrics.get("cost_bps_per_side")),
        "status": metrics.get("status"),
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "ending_capital_usd": ending,
        "total_fees_usd": fees,
        "trade_count": int(safe_float(metrics.get("trade_count"))),
        "avg_cash_weight": safe_float(metrics.get("avg_cash_weight")),
        "gross_traded_usd": safe_float(metrics.get("gross_traded_usd")),
    }
    if baseline:
        row["cagr_delta_pp_vs_baseline"] = (cagr - safe_float(baseline.get("cagr"))) * 100.0
        row["sharpe_delta_vs_baseline"] = sharpe - safe_float(baseline.get("sharpe"))
        row["maxdd_delta_pp_vs_baseline"] = (max_dd - safe_float(baseline.get("max_dd"))) * 100.0
        row["ending_delta_usd_vs_baseline"] = ending - safe_float(baseline.get("ending_capital_usd"))
    return row


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        f"# Cost Sensitivity Sidecar — {payload.get('portfolio_kind')}",
        "",
        f"- Target book: `{payload.get('target_book')}`",
        f"- Baseline cost: `{payload.get('baseline_cost_bps')} bps`",
        f"- Levels run: `{', '.join(str(lv['cost_bps']) for lv in payload.get('levels') or [])} bps`",
        f"- Breakeven cost (first level where CAGR < 0): `{payload.get('breakeven_cost_bps')}`",
        "",
        "| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for level in payload.get("levels") or []:
        lines.append(
            "| {cost_bps:.0f} | {cagr:.2%} | {sharpe:.3f} | {max_dd:.2%} | {trade_count} | {fees:.0f} | {dcagr:+.2f} |".format(
                cost_bps=safe_float(level.get("cost_bps")),
                cagr=safe_float(level.get("cagr")),
                sharpe=safe_float(level.get("sharpe")),
                max_dd=safe_float(level.get("max_dd")),
                trade_count=int(level.get("trade_count") or 0),
                fees=safe_float(level.get("total_fees_usd")),
                dcagr=safe_float(level.get("cagr_delta_pp_vs_baseline")),
            )
        )
    lines.extend([
        "",
        "Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.",
        "",
    ])
    return "\n".join(lines)


def run(
    *,
    target_book: Path,
    price_cache: Path,
    output_dir: Path,
    portfolio_kind: str,
    cost_bps_list: list[float],
    starting_capital: float,
    fill_mode: str,
    max_fill_lag_days: int,
    baseline_cost_bps: float,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    levels: list[dict[str, Any]] = []
    baseline_row: dict[str, Any] | None = None
    breakeven_cost: float | None = None
    sorted_levels = sorted({float(x) for x in cost_bps_list})
    for cost_bps in sorted_levels:
        metrics = run_level(
            target_book=target_book,
            price_cache=price_cache,
            portfolio_kind=portfolio_kind,
            cost_bps=cost_bps,
            starting_capital=starting_capital,
            fill_mode=fill_mode,
            max_fill_lag_days=max_fill_lag_days,
        )
        row = summarize(metrics, baseline_row)
        if math.isclose(cost_bps, baseline_cost_bps):
            baseline_row = row
            row = summarize(metrics, baseline_row)
        levels.append(row)
        if breakeven_cost is None and metrics.get("status") == "completed" and safe_float(metrics.get("cagr")) <= 0:
            breakeven_cost = cost_bps
    payload: dict[str, Any] = {
        "schema_version": "cost-sensitivity-sidecar-v1",
        "portfolio_kind": portfolio_kind,
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "starting_capital_usd": float(starting_capital),
        "fill_mode": fill_mode,
        "max_fill_lag_days": int(max_fill_lag_days),
        "baseline_cost_bps": float(baseline_cost_bps),
        "cost_bps_list": sorted_levels,
        "breakeven_cost_bps": breakeven_cost,
        "levels": levels,
        "research_only": True,
        "production_activation_allowed": False,
    }
    (output_dir / "summary.json").write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/cost_sensitivity")
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated"], default="main")
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--fill-mode", choices=["next_close", "next_open", "same_close"], default="next_close")
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument(
        "--cost-bps-list",
        nargs="+",
        type=float,
        default=DEFAULT_COST_BPS,
        help="Per-side transaction-cost levels to sweep (bps).",
    )
    parser.add_argument("--baseline-cost-bps", type=float, default=DEFAULT_BASELINE_BPS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(
        target_book=repo_path(args.target_book),
        price_cache=repo_path(args.price_cache),
        output_dir=repo_path(args.output_dir),
        portfolio_kind=args.portfolio_kind,
        cost_bps_list=args.cost_bps_list,
        starting_capital=args.starting_capital,
        fill_mode=args.fill_mode,
        max_fill_lag_days=args.max_fill_lag_days,
        baseline_cost_bps=args.baseline_cost_bps,
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("levels") else 2


if __name__ == "__main__":
    raise SystemExit(main())

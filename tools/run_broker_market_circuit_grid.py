#!/usr/bin/env python3
"""Grid search for broker-compatible market-circuit exposure multipliers.

This is a research-only wrapper around ``run_broker_market_circuit_replay``.
It runs several caution/crisis multiplier pairs on the same target book and
price cache, writes every account-ledger result, and emits a best candidate
that can be ranked by the goal-search sidecar.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_config import PORTFOLIO_GOAL_TARGETS  # noqa: E402
from tools.run_broker_market_circuit_replay import run as run_market_circuit  # noqa: E402
from tools.run_broker_ledger_replay import repo_path, safe_float  # noqa: E402


DEFAULT_OUT_DIR = "outputs/broker_market_circuit_grid"
DEFAULT_GRID = "0.90:0.70,0.85:0.60,0.80:0.50,0.70:0.40,0.60:0.25"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def parse_grid(value: str) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for raw in str(value or "").split(","):
        item = raw.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"Invalid grid item {item!r}; expected caution:crisis")
        left, right = item.split(":", 1)
        caution = float(left)
        crisis = float(right)
        if not (0.0 <= crisis <= caution <= 1.0):
            raise ValueError(f"Invalid multiplier pair {item!r}; require 0 <= crisis <= caution <= 1")
        pairs.append((caution, crisis))
    if not pairs:
        raise ValueError("At least one caution:crisis pair is required")
    # Preserve caller order while removing duplicates.
    seen: set[tuple[float, float]] = set()
    out: list[tuple[float, float]] = []
    for pair in pairs:
        if pair not in seen:
            out.append(pair)
            seen.add(pair)
    return out


def variant_id(caution: float, crisis: float) -> str:
    def fmt(x: float) -> str:
        return f"{x:.2f}".replace(".", "p")

    return f"caution_{fmt(caution)}_crisis_{fmt(crisis)}"


def target_distance(portfolio_kind: str, metrics: dict[str, Any]) -> float:
    target = PORTFOLIO_GOAL_TARGETS.get(portfolio_kind, {})
    target_cagr = safe_float(target.get("cagr"), math.nan)
    target_dd = safe_float(target.get("max_dd"), math.nan)
    cagr = safe_float(metrics.get("cagr"), math.nan)
    max_dd = safe_float(metrics.get("max_dd", metrics.get("max_drawdown")), math.nan)
    if not all(math.isfinite(x) for x in [target_cagr, target_dd, cagr, max_dd]):
        return math.inf
    return max(0.0, target_cagr - cagr) + max(0.0, target_dd - max_dd)


def rank_key(portfolio_kind: str, metrics: dict[str, Any]) -> tuple[float, float, float]:
    distance = target_distance(portfolio_kind, metrics)
    cagr = safe_float(metrics.get("cagr"), -1.0)
    max_dd = safe_float(metrics.get("max_dd", metrics.get("max_drawdown")), -1.0)
    return (distance, -cagr, abs(max_dd))


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pairs = parse_grid(args.grid)
    rows: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []

    for caution, crisis in pairs:
        vid = variant_id(caution, crisis)
        variant_dir = output_dir / vid
        variant_args = argparse.Namespace(
            target_book=args.target_book,
            price_cache=args.price_cache,
            output_dir=str(variant_dir),
            portfolio_kind=args.portfolio_kind,
            starting_capital=float(args.starting_capital),
            fill_mode=args.fill_mode,
            cost_bps=float(args.cost_bps),
            no_integer_shares=bool(args.no_integer_shares),
            max_fill_lag_days=int(args.max_fill_lag_days),
            caution_multiplier=float(caution),
            crisis_multiplier=float(crisis),
        )
        metrics = run_market_circuit(variant_args)
        metrics.update(
            {
                "market_circuit_grid_variant": vid,
                "caution_multiplier": float(caution),
                "crisis_multiplier": float(crisis),
                "source_variant_dir": str(variant_dir),
            }
        )
        write_json(variant_dir / "metrics.json", metrics)
        row = {
            "variant_id": vid,
            "status": metrics.get("status"),
            "portfolio_kind": args.portfolio_kind,
            "caution_multiplier": caution,
            "crisis_multiplier": crisis,
            "cagr": metrics.get("cagr"),
            "max_dd": metrics.get("max_dd", metrics.get("max_drawdown")),
            "sharpe": metrics.get("sharpe"),
            "trade_count": metrics.get("trade_count"),
            "avg_cash_weight": metrics.get("avg_cash_weight"),
            "total_fees_usd": metrics.get("total_fees_usd"),
            "target_distance": target_distance(args.portfolio_kind, metrics),
            "reason": metrics.get("reason", ""),
            "valid_for_production": bool(metrics.get("valid_for_production")),
        }
        rows.append(row)
        if metrics.get("status") == "completed" and metrics.get("valid_for_production"):
            completed.append(metrics)

    summary = pd.DataFrame(rows)
    if not summary.empty:
        summary = summary.sort_values(["target_distance", "cagr"], ascending=[True, False]).reset_index(drop=True)
    summary.to_csv(output_dir / "summary.csv", index=False)

    if completed:
        best = sorted(completed, key=lambda m: rank_key(args.portfolio_kind, m))[0]
        best_payload = dict(best)
        best_payload.update(
            {
                "status": "completed",
                "portfolio_kind": args.portfolio_kind,
                "metric_mode": "broker_market_circuit_grid_best_next_close",
                "market_circuit_grid": True,
                "variant_count": len(pairs),
                "production_activation_allowed": False,
                "research_only": True,
                "valid_for_production": True,
            }
        )
    else:
        best_payload = {
            "status": "blocked",
            "reason": "no completed market-circuit grid variants",
            "portfolio_kind": args.portfolio_kind,
            "variant_count": len(pairs),
            "production_activation_allowed": False,
            "research_only": True,
            "valid_for_production": False,
        }
    write_json(output_dir / "best_metrics.json", best_payload)
    report = [
        f"# Broker Market Circuit Grid: {args.portfolio_kind}",
        "",
        f"- variants: {len(pairs)}",
        f"- best_variant: {best_payload.get('market_circuit_grid_variant', '')}",
        f"- best_cagr: {safe_float(best_payload.get('cagr'), math.nan):.2%}" if best_payload.get("cagr") is not None else "- best_cagr: n/a",
        f"- best_max_dd: {safe_float(best_payload.get('max_dd', best_payload.get('max_drawdown')), math.nan):.2%}"
        if best_payload.get("max_dd", best_payload.get("max_drawdown")) is not None
        else "- best_max_dd: n/a",
        f"- best_sharpe: {safe_float(best_payload.get('sharpe'), math.nan):.3f}" if best_payload.get("sharpe") is not None else "- best_sharpe: n/a",
        "",
        "This sidecar is research-only. It ranks account-ledger-compatible variants but does not change production defaults.",
    ]
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return best_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated"], required=True)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--grid", default=DEFAULT_GRID)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--fill-mode", default="next_close")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--no-integer-shares", action="store_true")
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

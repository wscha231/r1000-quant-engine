#!/usr/bin/env python3
"""Market-circuit grid across top alpha-selector target books.

This wrapper avoids hard-coding one alpha-selector variant. It reads an
``alpha_selector_broker_grid`` directory, selects a small set of completed
target books from the grid ranking, applies the broker-compatible benchmark
trend circuit to each target book, and writes one best metrics file for goal
search.

The output is research-only. It does not change production defaults.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_config import PORTFOLIO_GOAL_TARGETS  # noqa: E402
from tools.run_broker_ledger_replay import repo_path, safe_float  # noqa: E402
from tools.run_broker_market_circuit_grid import run as run_market_circuit_grid  # noqa: E402


DEFAULT_OUT_DIR = "outputs/alpha_selector_market_circuit_grid"
DEFAULT_GRID = "0.90:0.70,0.80:0.50,0.70:0.40,0.60:0.25"
DEFAULT_TRIGGER_MODES = "ma50,ma50_200,trend60"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def clean_label(value: Any) -> str:
    text = str(value or "").strip()
    return "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in text).strip("_") or "na"


def target_distance(portfolio_kind: str, metrics: dict[str, Any]) -> float:
    target = PORTFOLIO_GOAL_TARGETS.get(portfolio_kind, PORTFOLIO_GOAL_TARGETS["main"])
    cagr = safe_float(metrics.get("cagr"), math.nan)
    max_dd = safe_float(metrics.get("max_dd", metrics.get("max_drawdown")), math.nan)
    if not math.isfinite(cagr) or not math.isfinite(max_dd):
        return math.inf
    return max(0.0, target["cagr"] - cagr) + max(0.0, target["max_dd"] - max_dd)


def rank_key(portfolio_kind: str, metrics: dict[str, Any]) -> tuple[float, float, float]:
    cagr = safe_float(metrics.get("cagr"), -1.0)
    max_dd = safe_float(metrics.get("max_dd", metrics.get("max_drawdown")), -1.0)
    return (target_distance(portfolio_kind, metrics), -cagr, abs(max_dd))


def target_path_for_variant(alpha_selector_dir: Path, variant_id: str) -> Path:
    return alpha_selector_dir / clean_label(variant_id) / "target_book.csv"


def resolve_target_books(alpha_selector_dir: Path, explicit_target_book: str, top_variants: int) -> list[tuple[str, Path]]:
    if explicit_target_book:
        path = repo_path(explicit_target_book)
        return [(path.parent.name or "explicit", path)] if path.exists() else []

    selected: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for metrics_name in ["best_target_distance_metrics.json", "best_metrics.json"]:
        payload = read_json(alpha_selector_dir / metrics_name)
        target = payload.get("target_book")
        variant = str(payload.get("alpha_selector_variant") or payload.get("variant_id") or metrics_name.replace("_metrics.json", ""))
        if target:
            path = repo_path(str(target))
            if path.exists() and path not in seen:
                selected.append((clean_label(variant), path))
                seen.add(path)

    summary_path = alpha_selector_dir / "summary.csv"
    if summary_path.exists() and len(selected) < int(top_variants):
        try:
            summary = pd.read_csv(summary_path)
        except Exception:
            summary = pd.DataFrame()
        if not summary.empty and "variant_id" in summary.columns:
            if "status" in summary.columns:
                summary = summary[summary["status"].astype(str).eq("completed")].copy()
            for col in ["target_distance", "cagr"]:
                if col not in summary.columns:
                    summary[col] = np.nan
                summary[col] = pd.to_numeric(summary[col], errors="coerce")
            ranked = summary.sort_values(["target_distance", "cagr"], ascending=[True, False])
            # Add the best by target distance plus the best by CAGR. This keeps
            # the search small while preserving the user's growth-first objective.
            cagr_ranked = summary.sort_values(["cagr", "target_distance"], ascending=[False, True])
            for frame in [ranked, cagr_ranked]:
                for _, row in frame.iterrows():
                    variant = clean_label(row.get("variant_id"))
                    path = target_path_for_variant(alpha_selector_dir, variant)
                    if path.exists() and path not in seen:
                        selected.append((variant, path))
                        seen.add(path)
                    if len(selected) >= int(top_variants):
                        break
                if len(selected) >= int(top_variants):
                    break
    return selected[: max(1, int(top_variants))]


def run(args: argparse.Namespace) -> dict[str, Any]:
    alpha_selector_dir = repo_path(args.alpha_selector_dir)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    targets = resolve_target_books(alpha_selector_dir, str(getattr(args, "target_book", "") or ""), int(args.top_variants))
    rows: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []

    if not targets:
        payload = {
            "status": "blocked",
            "reason": "no alpha-selector target books found",
            "alpha_selector_dir": str(alpha_selector_dir),
            "portfolio_kind": args.portfolio_kind,
            "valid_for_production": False,
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "best_metrics.json", payload)
        return payload

    for variant, target_book in targets:
        variant_dir = output_dir / clean_label(variant)
        grid_args = argparse.Namespace(
            target_book=str(target_book),
            price_cache=args.price_cache,
            portfolio_kind=args.portfolio_kind,
            output_dir=str(variant_dir),
            grid=args.grid,
            trigger_modes=args.trigger_modes,
            starting_capital=float(args.starting_capital),
            fill_mode=args.fill_mode,
            cost_bps=float(args.cost_bps),
            no_integer_shares=bool(args.no_integer_shares),
            max_fill_lag_days=int(args.max_fill_lag_days),
        )
        metrics = run_market_circuit_grid(grid_args)
        metrics.update(
            {
                "alpha_selector_market_circuit_variant": variant,
                "alpha_selector_source_target_book": str(target_book),
                "source_variant_dir": str(variant_dir),
                "metric_mode": "alpha_selector_market_circuit_grid_best_next_close",
            }
        )
        write_json(variant_dir / "best_metrics.json", metrics)
        rows.append(
            {
                "alpha_selector_variant": variant,
                "status": metrics.get("status"),
                "portfolio_kind": args.portfolio_kind,
                "cagr": metrics.get("cagr"),
                "max_dd": metrics.get("max_dd", metrics.get("max_drawdown")),
                "sharpe": metrics.get("sharpe"),
                "avg_cash_weight": metrics.get("avg_cash_weight"),
                "trade_count": metrics.get("trade_count"),
                "target_distance": target_distance(args.portfolio_kind, metrics),
                "market_circuit_grid_variant": metrics.get("market_circuit_grid_variant"),
                "trigger_mode": metrics.get("trigger_mode"),
                "valid_for_production": bool(metrics.get("valid_for_production")),
                "source_target_book": str(target_book),
            }
        )
        if metrics.get("status") == "completed" and metrics.get("valid_for_production"):
            completed.append(metrics)

    summary = pd.DataFrame(rows)
    if not summary.empty:
        summary = summary.sort_values(["target_distance", "cagr"], ascending=[True, False]).reset_index(drop=True)
    summary.to_csv(output_dir / "summary.csv", index=False)

    if completed:
        best = sorted(completed, key=lambda item: rank_key(args.portfolio_kind, item))[0]
        payload = dict(best)
        payload.update(
            {
                "status": "completed",
                "candidate_id": f"{args.portfolio_kind}_alpha_selector_market_circuit_grid",
                "metric_mode": "alpha_selector_market_circuit_grid_best_next_close",
                "portfolio_kind": args.portfolio_kind,
                "variant_count": int(len(rows)),
                "research_only": True,
                "production_activation_allowed": False,
                "valid_for_production": True,
            }
        )
    else:
        payload = {
            "status": "blocked",
            "reason": "no completed alpha-selector market-circuit variants",
            "portfolio_kind": args.portfolio_kind,
            "variant_count": int(len(rows)),
            "research_only": True,
            "production_activation_allowed": False,
            "valid_for_production": False,
        }
    write_json(output_dir / "best_metrics.json", payload)
    report = [
        f"# Alpha Selector Market Circuit Grid: {args.portfolio_kind}",
        "",
        f"- alpha selector variants tested: {len(rows)}",
        f"- best selector variant: {payload.get('alpha_selector_market_circuit_variant', '')}",
        f"- best market circuit variant: {payload.get('market_circuit_grid_variant', '')}",
        f"- CAGR: {safe_float(payload.get('cagr'), math.nan):.2%}" if payload.get("cagr") is not None else "- CAGR: n/a",
        f"- MaxDD: {safe_float(payload.get('max_dd', payload.get('max_drawdown')), math.nan):.2%}"
        if payload.get("max_dd", payload.get("max_drawdown")) is not None
        else "- MaxDD: n/a",
        f"- Sharpe: {safe_float(payload.get('sharpe'), math.nan):.3f}" if payload.get("sharpe") is not None else "- Sharpe: n/a",
        "",
        "Research-only account-ledger sidecar. No production defaults are changed.",
    ]
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alpha-selector-dir", required=True)
    parser.add_argument("--target-book", default="")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated"], required=True)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--top-variants", type=int, default=3)
    parser.add_argument("--grid", default=DEFAULT_GRID)
    parser.add_argument("--trigger-modes", default=DEFAULT_TRIGGER_MODES)
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

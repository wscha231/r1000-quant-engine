#!/usr/bin/env python3
"""Broker-ledger replay grid for concentrated strategy variants.

The concentrated research comparison file often contains several attractive
weight-level variants (N3/N4/N5/N7/N10, weighting modes, intervals). The
official broker replay evaluates only the selected champion filter. This
sidecar converts the top research variants into the same next-close,
integer-share broker ledger so the target gap is not judged from proxy metrics.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_config import PORTFOLIO_GOAL_TARGETS  # noqa: E402
from tools.run_broker_ledger_replay import replay as broker_replay, repo_path, safe_float  # noqa: E402


DEFAULT_OUT_DIR = "outputs/concentrated_broker_grid"
DEFAULT_TARGET_BOOK = "outputs/reports/operating_concentrated_target_book.csv"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def clean_label(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return text.strip("_") or "na"


def filter_value(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        out = float(value)
        if math.isfinite(out) and abs(out - round(out)) < 1e-9:
            return str(int(round(out)))
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def comparison_path(target_book: Path) -> Path:
    return target_book.parent / "concentrated_strategy_comparison.csv"


def load_variants(target_book: Path, max_variants: int) -> list[dict[str, Any]]:
    comparison = read_csv(comparison_path(target_book))
    if comparison.empty:
        return [
            {"target_stock_names": 3, "weighting_mode": "score_power", "active_rebalance_interval_months": 1},
            {"target_stock_names": 4, "weighting_mode": "winner_take_all", "active_rebalance_interval_months": 1},
            {"target_stock_names": 5, "weighting_mode": "winner_take_all", "active_rebalance_interval_months": 1},
            {"target_stock_names": 7, "weighting_mode": "winner_take_all", "active_rebalance_interval_months": 1},
        ][:max_variants]
    d = comparison.copy()
    if "portfolio_mode" in d.columns:
        d = d[d["portfolio_mode"].astype(str).eq("concentrated_alpha")].copy()
    for col in ["target_stock_names", "strategy_cagr", "max_dd", "sharpe"]:
        if col not in d.columns:
            d[col] = pd.NA
        d[col] = pd.to_numeric(d[col], errors="coerce")
    if "weighting_mode" not in d.columns:
        d["weighting_mode"] = "score_power"
    if "rebalance_interval_months" not in d.columns:
        d["rebalance_interval_months"] = 1
    target = PORTFOLIO_GOAL_TARGETS["concentrated"]
    d["_target_pass"] = (d["strategy_cagr"] >= target["cagr"]) & (d["max_dd"] >= target["max_dd"])
    d["_distance"] = (target["cagr"] - d["strategy_cagr"]).clip(lower=0) + (target["max_dd"] - d["max_dd"]).clip(lower=0)
    d = d.sort_values(["_target_pass", "_distance", "strategy_cagr", "sharpe"], ascending=[False, True, False, False])
    def row_to_variant(row: pd.Series) -> dict[str, Any] | None:
        n = filter_value(row.get("target_stock_names"))
        mode = filter_value(row.get("weighting_mode") or "score_power")
        interval = filter_value(row.get("rebalance_interval_months") or row.get("active_rebalance_interval_months") or 1)
        if not n or not mode:
            return None
        return {
            "target_stock_names": n,
            "weighting_mode": mode,
            "active_rebalance_interval_months": interval or "1",
            "research_strategy_cagr": safe_float(row.get("strategy_cagr"), math.nan),
            "research_max_dd": safe_float(row.get("max_dd"), math.nan),
            "research_sharpe": safe_float(row.get("sharpe"), math.nan),
        }

    variants: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add_variant(row: pd.Series) -> None:
        variant = row_to_variant(row)
        if variant is None:
            return
        key = (
            str(variant["target_stock_names"]),
            str(variant["weighting_mode"]),
            str(variant["active_rebalance_interval_months"]),
        )
        if key in seen:
            return
        variants.append(variant)
        seen.add(key)

    # Ensure the grid tests representative concentration levels. Pure top-N
    # sorting often selects many N2-N5 rows because their proxy CAGR is highest,
    # which can hide whether N7/N10 variants reduce broker-ledger drawdown.
    for n in [2, 3, 4, 5, 7, 10]:
        bucket = d[d["target_stock_names"].round().eq(float(n))].copy()
        if bucket.empty:
            continue
        add_variant(bucket.iloc[0])
        if len(variants) >= max_variants:
            return variants

    for _, row in d.iterrows():
        add_variant(row)
        if len(variants) >= max_variants:
            break
    return variants


def variant_id(row: dict[str, Any]) -> str:
    return "N{n}_{mode}_I{interval}".format(
        n=clean_label(row.get("target_stock_names")),
        mode=clean_label(row.get("weighting_mode")),
        interval=clean_label(row.get("active_rebalance_interval_months") or "1"),
    )


def target_distance(metrics: dict[str, Any]) -> float:
    target = PORTFOLIO_GOAL_TARGETS["concentrated"]
    cagr = safe_float(metrics.get("cagr"), math.nan)
    max_dd = safe_float(metrics.get("max_dd", metrics.get("max_drawdown")), math.nan)
    if not math.isfinite(cagr) or not math.isfinite(max_dd):
        return math.inf
    return max(0.0, target["cagr"] - cagr) + max(0.0, target["max_dd"] - max_dd)


def run(args: argparse.Namespace) -> dict[str, Any]:
    target_book = repo_path(args.target_book)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    variants = load_variants(target_book, max(1, int(args.max_variants)))
    rows: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    for variant in variants:
        vid = variant_id(variant)
        variant_dir = output_dir / vid
        filters = {
            "target_stock_names": variant.get("target_stock_names"),
            "weighting_mode": variant.get("weighting_mode"),
            "active_rebalance_interval_months": variant.get("active_rebalance_interval_months") or "1",
        }
        metrics = broker_replay(
            target_book=target_book,
            price_cache=price_cache,
            output_dir=variant_dir,
            portfolio_kind="concentrated",
            starting_capital=float(args.starting_capital),
            fill_mode=args.fill_mode,
            cost_bps=float(args.cost_bps),
            integer_shares=not bool(args.no_integer_shares),
            max_fill_lag_days=int(args.max_fill_lag_days),
            concentrated_champion_filters=filters,
            tail_row_fill_fallback_same_close=bool(args.tail_row_fill_fallback_same_close),
        )
        metrics.update(
            {
                "concentrated_broker_grid_variant": vid,
                "research_only": True,
                "production_activation_allowed": False,
                "variant_filter": filters,
                "research_strategy_cagr": variant.get("research_strategy_cagr"),
                "research_max_dd": variant.get("research_max_dd"),
                "research_sharpe": variant.get("research_sharpe"),
            }
        )
        write_json(variant_dir / "metrics.json", metrics)
        row = {
            "variant_id": vid,
            "status": metrics.get("status"),
            "target_stock_names": filters["target_stock_names"],
            "weighting_mode": filters["weighting_mode"],
            "active_rebalance_interval_months": filters["active_rebalance_interval_months"],
            "cagr": metrics.get("cagr"),
            "max_dd": metrics.get("max_dd", metrics.get("max_drawdown")),
            "sharpe": metrics.get("sharpe"),
            "trade_count": metrics.get("trade_count"),
            "avg_cash_weight": metrics.get("avg_cash_weight"),
            "total_fees_usd": metrics.get("total_fees_usd"),
            "target_distance": target_distance(metrics),
            "valid_for_production": bool(metrics.get("valid_for_production")),
            "research_strategy_cagr": variant.get("research_strategy_cagr"),
            "research_max_dd": variant.get("research_max_dd"),
            "research_sharpe": variant.get("research_sharpe"),
            "reason": metrics.get("reason", ""),
        }
        rows.append(row)
        if metrics.get("status") == "completed" and metrics.get("valid_for_production"):
            completed.append(metrics)
    summary = pd.DataFrame(rows)
    if not summary.empty:
        summary = summary.sort_values(["target_distance", "cagr", "max_dd"], ascending=[True, False, False]).reset_index(drop=True)
    summary.to_csv(output_dir / "summary.csv", index=False)
    if completed:
        best = sorted(
            completed,
            key=lambda m: (
                target_distance(m),
                -safe_float(m.get("cagr"), -1.0),
                abs(safe_float(m.get("max_dd", m.get("max_drawdown")), -1.0)),
            ),
        )[0]
        best_payload = dict(best)
        best_payload.update(
            {
                "status": "completed",
                "portfolio_kind": "concentrated",
                "metric_mode": "concentrated_broker_grid_best_next_close",
                "variant_count": len(variants),
                "research_only": True,
                "production_activation_allowed": False,
                "valid_for_production": True,
            }
        )
    else:
        best_payload = {
            "status": "blocked",
            "reason": "no completed concentrated broker grid variants",
            "portfolio_kind": "concentrated",
            "variant_count": len(variants),
            "research_only": True,
            "production_activation_allowed": False,
            "valid_for_production": False,
        }
    write_json(output_dir / "best_metrics.json", best_payload)
    report = [
        "# Concentrated Broker Grid",
        "",
        f"- variants: {len(variants)}",
        f"- best_variant: {best_payload.get('concentrated_broker_grid_variant', '')}",
        f"- best_cagr: {safe_float(best_payload.get('cagr'), math.nan):.2%}" if best_payload.get("cagr") is not None else "- best_cagr: n/a",
        f"- best_max_dd: {safe_float(best_payload.get('max_dd', best_payload.get('max_drawdown')), math.nan):.2%}"
        if best_payload.get("max_dd", best_payload.get("max_drawdown")) is not None
        else "- best_max_dd: n/a",
        f"- best_sharpe: {safe_float(best_payload.get('sharpe'), math.nan):.3f}" if best_payload.get("sharpe") is not None else "- best_sharpe: n/a",
        "",
        "This sidecar is production-compatible evidence but research-only. It does not change the selected concentrated champion.",
    ]
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return best_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", default=DEFAULT_TARGET_BOOK)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--max-variants", type=int, default=10)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--fill-mode", default="next_close")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--no-integer-shares", action="store_true")
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--tail-row-fill-fallback-same-close", action="store_true")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

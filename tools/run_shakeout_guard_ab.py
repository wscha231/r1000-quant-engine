#!/usr/bin/env python3
"""Measure SHAKEOUT_GUARD as a research-only broker-ledger A/B.

This tool does not replace operating target books and does not dispatch any
workflow.  It builds two AlphaOps vNext shadow books from the same inputs:

* baseline: ``PHASE_SHAKEOUT_GUARD_PROD_ENABLED=0``
* shakeout_on: ``PHASE_SHAKEOUT_GUARD_PROD_ENABLED=1``

Each arm is then replayed with the broker-ledger next-close mechanics.  Proxy
or weight-level metrics are intentionally not used for acceptance.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_alphaops_vnext_policy_replay import (  # noqa: E402
    DEFAULT_CONCENTRATED_TARGET_N,
    DEFAULT_MAIN_TARGET_N,
    build as build_vnext,
)
from tools.run_broker_ledger_replay import replay as broker_replay  # noqa: E402


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if pd.isna(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


@contextmanager
def patched_env(updates: dict[str, str | None]) -> Iterator[None]:
    old = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def count_bool(frame: pd.DataFrame, column: str) -> int:
    if column not in frame.columns or frame.empty:
        return 0
    return int(frame[column].astype(str).str.lower().isin({"1", "true", "yes"}).sum())


def value_counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if column not in frame.columns or frame.empty:
        return {}
    counts = Counter(str(value or "unknown") for value in frame[column].fillna("unknown").tolist())
    return dict(sorted(counts.items()))


def sample_applied(frame: pd.DataFrame, portfolio: str, limit: int = 20) -> list[dict[str, Any]]:
    if frame.empty or "shakeout_guard_prod_applied" not in frame.columns:
        return []
    applied = frame[frame["shakeout_guard_prod_applied"].astype(str).str.lower().isin({"1", "true", "yes"})].copy()
    if applied.empty:
        return []
    cols = [
        "rebalance_date",
        "ticker",
        "leader_tier",
        "holding_state_reason",
        "shakeout_guard_prod_reason",
        "shakeout_guard_prod_classifier_reason",
        "shakeout_guard_prod_fallback_source",
        "rs_benchmark_1m",
        "rs_benchmark_3m",
        "rs_benchmark_6m",
        "rs_qqq_1m",
        "rs_qqq_3m",
        "rs_qqq_6m",
        "sector_leadership_score",
        "crisis_state",
    ]
    out: list[dict[str, Any]] = []
    for row in applied.head(limit).to_dict("records"):
        item = {"portfolio": portfolio}
        for col in cols:
            if col in row:
                item[col] = row.get(col)
        out.append(item)
    return out


def summarize_target_book(path: Path, portfolio: str) -> dict[str, Any]:
    frame = read_csv(path)
    applied_count = count_bool(frame, "shakeout_guard_prod_applied")
    return {
        "portfolio": portfolio,
        "target_book": str(path),
        "row_count": int(len(frame)),
        "shakeout_guard_applied_count": applied_count,
        "shakeout_guard_block_reason_counts": value_counts(frame, "shakeout_guard_prod_block_reason"),
        "shakeout_guard_fallback_source_counts": value_counts(frame, "shakeout_guard_prod_fallback_source"),
        "shakeout_guard_classifier_state_counts": value_counts(frame, "shakeout_guard_prod_classifier_state"),
        "applied_samples": sample_applied(frame, portfolio),
    }


def extract_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": metrics.get("status"),
        "metric_mode": metrics.get("metric_mode"),
        "cagr": safe_float(metrics.get("cagr")),
        "max_dd": safe_float(metrics.get("max_dd")),
        "sharpe": safe_float(metrics.get("sharpe")),
        "years": safe_float(metrics.get("years")),
        "avg_cash_weight": safe_float(metrics.get("avg_cash_weight")),
        "trade_count": int(safe_float(metrics.get("trade_count"))),
        "total_fees_usd": safe_float(metrics.get("total_fees_usd")),
        "gross_traded_usd": safe_float(metrics.get("gross_traded_usd")),
        "start_date": metrics.get("start_date"),
        "end_date": metrics.get("end_date"),
    }


def delta_metrics(base: dict[str, Any], treatment: dict[str, Any]) -> dict[str, Any]:
    return {
        "delta_cagr_pp": (safe_float(treatment.get("cagr")) - safe_float(base.get("cagr"))) * 100.0,
        "delta_max_dd_pp": (safe_float(treatment.get("max_dd")) - safe_float(base.get("max_dd"))) * 100.0,
        "delta_sharpe": safe_float(treatment.get("sharpe")) - safe_float(base.get("sharpe")),
        "delta_avg_cash_weight_pp": (safe_float(treatment.get("avg_cash_weight")) - safe_float(base.get("avg_cash_weight"))) * 100.0,
        "delta_trade_count": int(safe_float(treatment.get("trade_count")) - safe_float(base.get("trade_count"))),
    }


def build_arm(args: argparse.Namespace, arm: str, enabled: bool) -> dict[str, Any]:
    arm_root = Path(args.output_dir) / arm
    vnext_dir = arm_root / "vnext"
    broker_root = arm_root / "broker"
    env_value = "1" if enabled else "0"
    with patched_env(
        {
            "PHASE_SHAKEOUT_GUARD_PROD_ENABLED": env_value,
            "PHASE_SHAKEOUT_GUARD_WARNING_SUPPRESS_ENABLED": "0",
        }
    ):
        build_payload = build_vnext(
            argparse.Namespace(
                latest_run=str(args.latest_run),
                candidate_book=args.candidate_book,
                price_cache=str(args.price_cache),
                output_dir=str(vnext_dir),
                portfolio_kind="both",
                main_target_n=int(args.main_target_n),
                concentrated_target_n=int(args.concentrated_target_n),
                production_output_mode="shadow_only",
                skip_broker_replay=True,
                run_current_report=False,
                cost_bps=float(args.cost_bps),
                max_fill_lag_days=int(args.max_fill_lag_days),
                long_crisis_features=str(args.long_crisis_features),
                long_crisis_thresholds=str(args.long_crisis_thresholds),
            )
        )
    metrics: dict[str, dict[str, Any]] = {}
    diagnostics: dict[str, Any] = {}
    for portfolio, filename in (
        ("main", "official_main_target_book.csv"),
        ("concentrated", "official_concentrated_target_book.csv"),
    ):
        target_book = vnext_dir / filename
        metrics[portfolio] = broker_replay(
            target_book=target_book,
            price_cache=Path(args.price_cache),
            output_dir=broker_root / portfolio,
            portfolio_kind=portfolio,
            starting_capital=float(args.starting_capital),
            fill_mode="next_close",
            cost_bps=float(args.cost_bps),
            integer_shares=True,
            max_fill_lag_days=int(args.max_fill_lag_days),
            disable_concentrated_champion_filter=portfolio == "concentrated",
        )
        diagnostics[portfolio] = summarize_target_book(target_book, portfolio)
    return {
        "arm": arm,
        "shakeout_guard_enabled": bool(enabled),
        "vnext_output_dir": str(vnext_dir),
        "broker_output_dir": str(broker_root),
        "build": build_payload,
        "metrics": {key: extract_metrics(value) for key, value in metrics.items()},
        "raw_metric_paths": {
            "main": str(broker_root / "main" / "metrics.json"),
            "concentrated": str(broker_root / "concentrated" / "metrics.json"),
        },
        "diagnostics": diagnostics,
    }


def classify_result(summary: dict[str, Any], min_years: float) -> str:
    arms = summary.get("arms", {})
    baseline = arms.get("baseline", {})
    treatment = arms.get("shakeout_on", {})
    for arm in (baseline, treatment):
        for portfolio_metrics in (arm.get("metrics") or {}).values():
            if portfolio_metrics.get("metric_mode") != "broker_ledger_next_close":
                return "blocked_invalid_metric"
            if safe_float(portfolio_metrics.get("years")) < min_years:
                return "blocked_invalid_window"
    applied = safe_float(summary.get("guard_diagnostics", {}).get("shakeout_guard_applied_count"))
    if applied <= 0:
        return "no_op"
    main_delta = summary.get("deltas", {}).get("main", {})
    conc_delta = summary.get("deltas", {}).get("concentrated", {})
    if safe_float(main_delta.get("delta_max_dd_pp")) < -0.5:
        return "cagr_up_mdd_bad" if safe_float(main_delta.get("delta_cagr_pp")) > 0 else "mdd_bad"
    if safe_float(conc_delta.get("delta_cagr_pp")) < 0 and safe_float(conc_delta.get("delta_max_dd_pp")) < 0:
        return "mdd_up_cagr_bad"
    return "research_pass"


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Shakeout Guard Broker-Ledger A/B",
        "",
        f"- Generated: `{summary.get('generated_at_utc')}`",
        f"- Conclusion: `{summary.get('conclusion')}`",
        f"- Metric source: `broker_ledger_next_close` only",
        f"- Applied count: `{summary.get('guard_diagnostics', {}).get('shakeout_guard_applied_count')}`",
        "",
        "| Portfolio | Baseline CAGR | Shakeout CAGR | Delta CAGR pp | Baseline MDD | Shakeout MDD | Delta MDD pp | Baseline Sharpe | Shakeout Sharpe |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    baseline = summary.get("arms", {}).get("baseline", {}).get("metrics", {})
    treatment = summary.get("arms", {}).get("shakeout_on", {}).get("metrics", {})
    deltas = summary.get("deltas", {})
    for portfolio in ("main", "concentrated"):
        base = baseline.get(portfolio, {})
        treat = treatment.get(portfolio, {})
        delta = deltas.get(portfolio, {})
        lines.append(
            "| {portfolio} | {base_cagr:.2%} | {treat_cagr:.2%} | {dcagr:.2f} | {base_mdd:.2%} | {treat_mdd:.2%} | {dmdd:.2f} | {base_sharpe:.3f} | {treat_sharpe:.3f} |".format(
                portfolio=portfolio,
                base_cagr=safe_float(base.get("cagr")),
                treat_cagr=safe_float(treat.get("cagr")),
                dcagr=safe_float(delta.get("delta_cagr_pp")),
                base_mdd=safe_float(base.get("max_dd")),
                treat_mdd=safe_float(treat.get("max_dd")),
                dmdd=safe_float(delta.get("delta_max_dd_pp")),
                base_sharpe=safe_float(base.get("sharpe")),
                treat_sharpe=safe_float(treat.get("sharpe")),
            )
        )
    lines.extend(
        [
            "",
            "## Block Reasons",
            "",
            "```json",
            json.dumps(summary.get("guard_diagnostics", {}).get("shakeout_guard_block_reason_counts", {}), indent=2, default=str),
            "```",
            "",
            "## Fallback Sources",
            "",
            "```json",
            json.dumps(summary.get("guard_diagnostics", {}).get("shakeout_guard_fallback_source_counts", {}), indent=2, default=str),
            "```",
            "",
            "Production promotion remains blocked; this report is research-only.",
        ]
    )
    return "\n".join(lines) + "\n"


def combine_guard_diagnostics(arm: dict[str, Any]) -> dict[str, Any]:
    diagnostics = arm.get("diagnostics", {})
    applied_by_portfolio: dict[str, int] = {}
    block_counts: Counter[str] = Counter()
    fallback_counts: Counter[str] = Counter()
    classifier_counts: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    for portfolio, payload in diagnostics.items():
        count = int(payload.get("shakeout_guard_applied_count") or 0)
        applied_by_portfolio[portfolio] = count
        block_counts.update(payload.get("shakeout_guard_block_reason_counts") or {})
        fallback_counts.update(payload.get("shakeout_guard_fallback_source_counts") or {})
        classifier_counts.update(payload.get("shakeout_guard_classifier_state_counts") or {})
        samples.extend(payload.get("applied_samples") or [])
    return {
        "shakeout_guard_applied_count": int(sum(applied_by_portfolio.values())),
        "shakeout_guard_applied_count_by_portfolio": applied_by_portfolio,
        "shakeout_guard_block_reason_counts": dict(sorted(block_counts.items())),
        "shakeout_guard_fallback_source_counts": dict(sorted(fallback_counts.items())),
        "shakeout_guard_classifier_state_counts": dict(sorted(classifier_counts.items())),
        "applied_samples": samples[:20],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/shakeout_guard_ab")
    parser.add_argument("--main-target-n", type=int, default=DEFAULT_MAIN_TARGET_N)
    parser.add_argument("--concentrated-target-n", type=int, default=DEFAULT_CONCENTRATED_TARGET_N)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--min-years", type=float, default=7.0)
    parser.add_argument("--long-crisis-features", default="data_pit/macro/long_crisis_daily_features.parquet")
    parser.add_argument("--long-crisis-thresholds", default="outputs/long_crisis_learning/best_thresholds.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline = build_arm(args, "baseline", enabled=False)
    treatment = build_arm(args, "shakeout_on", enabled=True)
    deltas = {
        portfolio: delta_metrics(baseline["metrics"].get(portfolio, {}), treatment["metrics"].get(portfolio, {}))
        for portfolio in ("main", "concentrated")
    }
    guard_diagnostics = combine_guard_diagnostics(treatment)
    summary: dict[str, Any] = {
        "schema_version": "shakeout-guard-ab-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "metric_source": "broker_ledger_next_close",
        "arms": {
            "baseline": baseline,
            "shakeout_on": treatment,
        },
        "deltas": deltas,
        "guard_diagnostics": guard_diagnostics,
    }
    summary["conclusion"] = classify_result(summary, min_years=float(args.min_years))
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary["conclusion"] not in {"blocked_invalid_metric"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

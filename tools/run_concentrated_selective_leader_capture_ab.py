#!/usr/bin/env python3
"""Measure Concentrated selective leader capture as a broker-ledger A/B.

This is research-only. It compares two shadow AlphaOps vNext books from the
same input data:

* baseline: ``PHASE_CONCENTRATED_SELECTIVE_LEADER_CAPTURE_ENABLED=0``
* selective_capture_on: ``PHASE_CONCENTRATED_SELECTIVE_LEADER_CAPTURE_ENABLED=1``

The lever is intentionally narrow: it can only lower the Concentrated
replacement gap for PIT-visible current leaders. Forward return labels are not
read by this tool or by the policy replay.
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


def bool_mask(frame: pd.DataFrame, column: str) -> pd.Series:
    if frame.empty or column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[column].astype(str).str.lower().isin({"1", "true", "yes"})


def count_bool(frame: pd.DataFrame, column: str) -> int:
    return int(bool_mask(frame, column).sum())


def value_counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    counts = Counter(str(value or "unknown") for value in frame[column].fillna("unknown").tolist())
    return dict(sorted(counts.items()))


def sample_rows(frame: pd.DataFrame, applied_column: str, source: str, limit: int = 20) -> list[dict[str, Any]]:
    if frame.empty or applied_column not in frame.columns:
        return []
    applied = frame[bool_mask(frame, applied_column)].copy()
    if applied.empty:
        return []
    cols = [
        "rebalance_date",
        "ticker",
        "replacement_ticker",
        "replacement_test_weakest_ticker",
        "leader_tier",
        "rs_spy_3m",
        "rs_spy_6m",
        "alphaops_vnext_score",
        "candidate_score",
        "replacement_test_weakest_score",
        "hold_replace_required_gap_before_selective_capture",
        "hold_replace_required_gap",
        "concentrated_selective_leader_capture_reason",
        "concentrated_selective_leader_capture_gap_credit",
        "rejection_reason",
    ]
    out: list[dict[str, Any]] = []
    for row in applied.head(limit).to_dict("records"):
        item = {"source": source}
        for col in cols:
            if col in row:
                item[col] = row.get(col)
        out.append(item)
    return out


def summarize_selective_capture(vnext_dir: Path) -> dict[str, Any]:
    target = read_csv(vnext_dir / "official_concentrated_target_book.csv")
    rejected = read_csv(vnext_dir / "rejected_by_reason.csv")
    if not rejected.empty and "portfolio_kind" in rejected.columns:
        rejected = rejected[rejected["portfolio_kind"].astype(str).eq("concentrated")].copy()
    applied_column = "concentrated_selective_leader_capture_applied"
    target_applied = count_bool(target, applied_column)
    reject_applied = count_bool(rejected, applied_column)
    return {
        "target_book": str(vnext_dir / "official_concentrated_target_book.csv"),
        "rejected_by_reason": str(vnext_dir / "rejected_by_reason.csv"),
        "target_row_count": int(len(target)),
        "rejected_row_count": int(len(rejected)),
        "target_applied_count": target_applied,
        "reject_applied_count": reject_applied,
        "total_applied_count": int(target_applied + reject_applied),
        "target_reason_counts": value_counts(target, "concentrated_selective_leader_capture_reason"),
        "reject_reason_counts": value_counts(rejected, "concentrated_selective_leader_capture_reason"),
        "target_samples": sample_rows(target, applied_column, "target_book"),
        "reject_samples": sample_rows(rejected, applied_column, "rejected_by_reason"),
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
        "delta_avg_cash_weight_pp": (
            safe_float(treatment.get("avg_cash_weight")) - safe_float(base.get("avg_cash_weight"))
        )
        * 100.0,
        "delta_trade_count": int(safe_float(treatment.get("trade_count")) - safe_float(base.get("trade_count"))),
    }


def build_arm(args: argparse.Namespace, arm: str, enabled: bool) -> dict[str, Any]:
    arm_root = Path(args.output_dir) / arm
    vnext_dir = arm_root / "vnext"
    broker_root = arm_root / "broker"
    env_value = "1" if enabled else "0"
    with patched_env(
        {
            "PHASE_CONCENTRATED_SELECTIVE_LEADER_CAPTURE_ENABLED": env_value,
            "PHASE_CONCENTRATED_SELECTIVE_LEADER_CAPTURE_GAP_CREDIT": str(args.gap_credit),
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
    return {
        "arm": arm,
        "selective_capture_enabled": bool(enabled),
        "vnext_output_dir": str(vnext_dir),
        "broker_output_dir": str(broker_root),
        "build": build_payload,
        "metrics": {key: extract_metrics(value) for key, value in metrics.items()},
        "raw_metric_paths": {
            "main": str(broker_root / "main" / "metrics.json"),
            "concentrated": str(broker_root / "concentrated" / "metrics.json"),
        },
        "selective_capture_diagnostics": summarize_selective_capture(vnext_dir),
    }


def classify_result(summary: dict[str, Any], min_years: float) -> str:
    arms = summary.get("arms", {})
    baseline = arms.get("baseline", {})
    treatment = arms.get("selective_capture_on", {})
    for arm in (baseline, treatment):
        for portfolio_metrics in (arm.get("metrics") or {}).values():
            if portfolio_metrics.get("metric_mode") != "broker_ledger_next_close":
                return "blocked_invalid_metric"
            if safe_float(portfolio_metrics.get("years")) < min_years:
                return "blocked_invalid_window"
    applied = safe_float(summary.get("selective_capture_diagnostics", {}).get("total_applied_count"))
    if applied <= 0:
        return "no_op"
    conc_delta = summary.get("deltas", {}).get("concentrated", {})
    main_delta = summary.get("deltas", {}).get("main", {})
    if safe_float(main_delta.get("delta_cagr_pp")) < -0.10 or safe_float(main_delta.get("delta_max_dd_pp")) < -0.10:
        return "main_regression"
    if safe_float(conc_delta.get("delta_cagr_pp")) <= 0:
        return "concentrated_cagr_not_improved"
    if safe_float(conc_delta.get("delta_max_dd_pp")) < -0.50:
        return "concentrated_cagr_up_mdd_bad"
    return "research_pass"


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Concentrated Selective Leader Capture A/B",
        "",
        f"- Generated: `{summary.get('generated_at_utc')}`",
        f"- Conclusion: `{summary.get('conclusion')}`",
        f"- Metric source: `{summary.get('metric_source')}`",
        f"- Total applied count: `{summary.get('selective_capture_diagnostics', {}).get('total_applied_count')}`",
        "",
        "| Portfolio | Baseline CAGR | Treatment CAGR | Delta CAGR pp | Baseline MDD | Treatment MDD | Delta MDD pp | Baseline Sharpe | Treatment Sharpe |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    baseline = summary.get("arms", {}).get("baseline", {}).get("metrics", {})
    treatment = summary.get("arms", {}).get("selective_capture_on", {}).get("metrics", {})
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
            "## Diagnostics",
            "",
            "```json",
            json.dumps(summary.get("selective_capture_diagnostics", {}), indent=2, default=str),
            "```",
            "",
            "Production promotion remains blocked; this report is research-only.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/concentrated_selective_leader_capture_ab")
    parser.add_argument("--main-target-n", type=int, default=DEFAULT_MAIN_TARGET_N)
    parser.add_argument("--concentrated-target-n", type=int, default=DEFAULT_CONCENTRATED_TARGET_N)
    parser.add_argument("--gap-credit", type=float, default=0.07)
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
    treatment = build_arm(args, "selective_capture_on", enabled=True)
    deltas = {
        portfolio: delta_metrics(baseline["metrics"].get(portfolio, {}), treatment["metrics"].get(portfolio, {}))
        for portfolio in ("main", "concentrated")
    }
    diagnostics = treatment.get("selective_capture_diagnostics", {})
    summary: dict[str, Any] = {
        "schema_version": "concentrated-selective-leader-capture-ab-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "policy_mutation_allowed": False,
        "live_trading_enabled": False,
        "forward_returns_used_for_ranking": False,
        "metric_source": "broker_ledger_next_close",
        "arms": {
            "baseline": baseline,
            "selective_capture_on": treatment,
        },
        "deltas": deltas,
        "selective_capture_diagnostics": diagnostics,
    }
    summary["conclusion"] = classify_result(summary, min_years=float(args.min_years))
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary["conclusion"] not in {"blocked_invalid_metric"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

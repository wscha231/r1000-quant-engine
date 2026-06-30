#!/usr/bin/env python3
"""Verify AlphaOps research/fullrun artifacts against the active CAGR/MDD goal.

This is a read-only verifier. It does not promote production, dispatch
workflows, or mutate target books. It exists to prevent manual interpretation
mistakes after a cheap broker replay or a long full rebuild.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


TARGETS = {
    "main": {"cagr_min": 0.35, "max_dd_min": -0.25},
    "concentrated": {"cagr_min": 0.50, "max_dd_min": -0.25},
}
EXPECTED_MODE = "broker_ledger_next_close"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


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


def pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def resolve_metrics(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    if args.latest_run:
        latest = Path(args.latest_run)
        official = read_json(latest / "account_evaluation" / "official_metrics.json")
        portfolios = official.get("portfolios")
        if isinstance(portfolios, dict):
            for portfolio in ("main", "concentrated"):
                if isinstance(portfolios.get(portfolio), dict):
                    metrics[portfolio] = dict(portfolios[portfolio])
        for portfolio in ("main", "concentrated"):
            broker_path = latest / "broker_replay" / portfolio / "metrics.json"
            broker = read_json(broker_path)
            if broker:
                metrics[portfolio] = broker
    explicit = {"main": args.main_metrics, "concentrated": args.concentrated_metrics}
    for portfolio, raw in explicit.items():
        if raw:
            metrics[portfolio] = read_json(Path(raw))
    return metrics


def evaluate_portfolio(portfolio: str, metrics: dict[str, Any]) -> dict[str, Any]:
    target = TARGETS[portfolio]
    cagr = safe_float(metrics.get("cagr"))
    max_dd = safe_float(metrics.get("max_dd"))
    years = safe_float(metrics.get("years"))
    mode = str(metrics.get("metric_mode") or "")
    checks = {
        "metrics_present": bool(metrics),
        "metric_mode_ok": mode == EXPECTED_MODE,
        "years_ok": years is not None and years >= 7.0,
        "cagr_ok": cagr is not None and cagr >= target["cagr_min"],
        "max_dd_ok": max_dd is not None and max_dd >= target["max_dd_min"],
    }
    return {
        "portfolio": portfolio,
        "cagr": cagr,
        "max_dd": max_dd,
        "sharpe": safe_float(metrics.get("sharpe")),
        "years": years,
        "metric_mode": mode,
        "checks": checks,
        "pass": all(checks.values()),
    }


def count_csv_rows(path: Path, column: str | None = None, truthy: bool = False) -> int:
    if not path.exists():
        return 0
    try:
        frame = pd.read_csv(path)
    except Exception:
        return 0
    if column and column in frame.columns:
        if truthy:
            values = frame[column].astype(str).str.strip().str.lower()
            return int(values.isin({"1", "true", "yes"}).sum())
        return int(pd.to_numeric(frame[column], errors="coerce").fillna(0.0).gt(0.0).sum())
    return int(len(frame))


def hook_checks(args: argparse.Namespace) -> dict[str, Any]:
    target_dir = Path(args.target_dir) if args.target_dir else None
    if not target_dir:
        return {"checked": False, "pass": True, "reason": "no_target_dir_supplied"}

    hedge_summary = read_json(target_dir / "main_fast_crash_hedge.json")
    hedge_actions = target_dir / "main_fast_crash_hedge_actions.csv"
    concentrated_book = target_dir / "official_concentrated_target_book.csv"
    main_hedge_dates = int(safe_float(hedge_summary.get("hedge_dates"), 0) or 0)
    main_action_rows = count_csv_rows(hedge_actions)
    conc_applied_rows = count_csv_rows(
        concentrated_book,
        column="concentrated_cashfunded_early_entry_applied",
        truthy=True,
    )
    checks = {
        "target_dir_exists": target_dir.exists(),
        "main_hedge_summary_completed": hedge_summary.get("status") == "completed",
        "main_hedge_dates_positive": main_hedge_dates > 0,
        "main_hedge_actions_present": main_action_rows > 0,
        "concentrated_early_entry_applied_positive": conc_applied_rows > 0,
    }
    return {
        "checked": True,
        "target_dir": str(target_dir),
        "main_hedge_dates": main_hedge_dates,
        "main_hedge_action_rows": main_action_rows,
        "concentrated_early_entry_applied_rows": conc_applied_rows,
        "checks": checks,
        "pass": all(checks.values()),
    }


def production_blocker_check(args: argparse.Namespace) -> dict[str, Any]:
    if args.expect_pit_unclean:
        return {
            "checked": True,
            "pit_universe_label_clean": False,
            "production_promotion_allowed": False,
            "pass": True,
            "reason": "caller_expect_pit_unclean",
        }
    if not args.latest_run:
        return {"checked": False, "pass": True, "reason": "no_latest_run_supplied"}
    official = read_json(Path(args.latest_run) / "account_evaluation" / "official_metrics.json")
    pit_clean = bool(official.get("pit_universe_label_clean") or official.get("historical_universe_pit_clean"))
    production_allowed = bool(official.get("production_promotion_allowed"))
    return {
        "checked": True,
        "pit_universe_label_clean": pit_clean,
        "production_promotion_allowed": production_allowed,
        "pass": (pit_clean or not production_allowed),
        "reason": "production_must_not_be_allowed_when_pit_unclean",
    }


def build_report(payload: dict[str, Any]) -> str:
    lines = ["# AlphaOps Goal Verification", ""]
    lines.append(f"Overall status: **{payload['status']}**")
    lines.append("")
    lines.append("| Portfolio | CAGR | MaxDD | Sharpe | Years | Metric mode | Pass |")
    lines.append("|---|---:|---:|---:|---:|---|---|")
    for item in payload["portfolios"].values():
        lines.append(
            "| {portfolio} | {cagr} | {max_dd} | {sharpe} | {years} | {mode} | {passed} |".format(
                portfolio=item["portfolio"],
                cagr=pct(item["cagr"]),
                max_dd=pct(item["max_dd"]),
                sharpe="n/a" if item["sharpe"] is None else f"{item['sharpe']:.3f}",
                years="n/a" if item["years"] is None else f"{item['years']:.3f}",
                mode=item["metric_mode"] or "n/a",
                passed="PASS" if item["pass"] else "FAIL",
            )
        )
    hooks = payload["hook_checks"]
    if hooks.get("checked"):
        lines.extend(
            [
                "",
                "## Hook Telemetry",
                "",
                f"- Main hedge dates: {hooks.get('main_hedge_dates')}",
                f"- Main hedge action rows: {hooks.get('main_hedge_action_rows')}",
                f"- Concentrated early-entry applied rows: {hooks.get('concentrated_early_entry_applied_rows')}",
                f"- Hook telemetry pass: {hooks.get('pass')}",
            ]
        )
    prod = payload["production_blocker"]
    if prod.get("checked"):
        lines.extend(
            [
                "",
                "## Production Blocker",
                "",
                f"- PIT clean: {prod.get('pit_universe_label_clean')}",
                f"- Production promotion allowed: {prod.get('production_promotion_allowed')}",
                f"- Blocker check pass: {prod.get('pass')}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="")
    parser.add_argument("--main-metrics", default="")
    parser.add_argument("--concentrated-metrics", default="")
    parser.add_argument("--target-dir", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--expect-pit-unclean", action="store_true")
    args = parser.parse_args()

    raw_metrics = resolve_metrics(args)
    portfolios = {p: evaluate_portfolio(p, raw_metrics.get(p, {})) for p in ("main", "concentrated")}
    hooks = hook_checks(args)
    production_blocker = production_blocker_check(args)
    payload = {
        "schema_version": "alphaops-goal-verifier-v1",
        "status": "pass" if all(item["pass"] for item in portfolios.values()) and hooks["pass"] and production_blocker["pass"] else "fail",
        "targets": TARGETS,
        "portfolios": portfolios,
        "hook_checks": hooks,
        "production_blocker": production_blocker,
    }
    report = build_report(payload)
    if args.output_dir:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        (out / "report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

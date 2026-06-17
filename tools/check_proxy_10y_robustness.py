#!/usr/bin/env python3
"""Validate proxy 10Y robustness without promoting it as official evidence."""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_policy import OFFICIAL_METRIC_MODE, read_json, repo_path, safe_float, write_json  # noqa: E402

MAIN_CAGR_MIN = 0.35
MAIN_MDD_MIN = -0.25
CONC_CAGR_MIN = 0.50
CONC_MDD_MIN = -0.25
OOS_IS_RATIO_MAX = 3.0
IS_CAGR_MIN = 0.20
MIN_PROXY_YEARS = 9.8
MIN_PROXY_MONTHS = 118


def _metric(row: dict[str, Any], key: str) -> float | None:
    value = safe_float(row.get(key))
    if value is not None:
        return value
    gates = row.get("tier2_gates") if isinstance(row.get("tier2_gates"), dict) else {}
    return safe_float(gates.get(key))


def _years(row: dict[str, Any]) -> float:
    value = safe_float(row.get("years"))
    if value is not None:
        return value
    gate = row.get("broker_ledger_window_gate") if isinstance(row.get("broker_ledger_window_gate"), dict) else {}
    return safe_float(gate.get("years"), 0.0) or 0.0


def _portfolio_items(latest_run: Path, official: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nested = official.get("portfolios") if isinstance(official.get("portfolios"), dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for name in sorted(set(nested.keys()) | {"main", "concentrated"}):
        broker = read_json(latest_run / "broker_replay" / name / "metrics.json")
        row = nested.get(name) if isinstance(nested.get(name), dict) else {}
        merged = {**broker, **row}
        if merged:
            out[name] = merged
    return out


def _mode(official: dict[str, Any], portfolios: dict[str, dict[str, Any]]) -> str:
    mode = str(official.get("official_metric_mode") or official.get("metric_mode") or "")
    if mode:
        return mode
    for row in portfolios.values():
        value = str(row.get("official_metric_mode") or row.get("metric_mode") or "")
        if value:
            return value
    return ""


def _cash_trap_false(latest_run: Path) -> tuple[bool, bool, list[str]]:
    payload = read_json(latest_run / "cash_reentry_quality" / "summary.json")
    if not payload:
        return False, False, ["cash_trap_evidence_missing"]
    reasons: list[str] = []
    if payload.get("cash_trap_flag") is True:
        reasons.append("cash_trap_flag=true")
    rows = payload.get("cash_trap_rows")
    try:
        if rows is not None and int(float(rows)) > 0:
            reasons.append(f"cash_trap_rows={rows}")
    except (TypeError, ValueError):
        reasons.append(f"cash_trap_rows_unparseable={rows}")
    by_portfolio = payload.get("by_portfolio") if isinstance(payload.get("by_portfolio"), dict) else {}
    for name, row in by_portfolio.items():
        if isinstance(row, dict) and row.get("cash_trap_flag") is True:
            reasons.append(f"{name}.cash_trap_flag=true")
    return True, not reasons, reasons


def _ratio(row: dict[str, Any]) -> float | None:
    for key in ("oos_is_cagr_ratio", "oos_is_ratio", "oos_to_is_cagr_ratio"):
        value = safe_float(row.get(key))
        if value is not None:
            return value
    is_cagr = safe_float(row.get("is_cagr"))
    oos_cagr = safe_float(row.get("oos_cagr"))
    if is_cagr and oos_cagr is not None:
        return oos_cagr / is_cagr
    return None


def _int_value(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def classify_proxy_10y_robustness(latest_run: str | Path) -> dict[str, Any]:
    run_dir = repo_path(latest_run)
    readiness = read_json(run_dir / "ten_year_backtest_readiness" / "summary.json")
    universe_substrate = read_json(run_dir / "proxy_10y_universe_substrate" / "summary.json")
    official = read_json(run_dir / "account_evaluation" / "official_metrics.json")
    portfolios = _portfolio_items(run_dir, official)
    mode = _mode(official, portfolios)
    cash_available, cash_ok, cash_reasons = _cash_trap_false(run_dir)

    checks: dict[str, bool] = {
        "ten_year_readiness_present": bool(readiness),
        "ten_year_readiness_schema": readiness.get("schema_version") == "backtest-window-readiness-v2",
        "readiness_label_is_proxy_10y": readiness.get("evidence_label") == "proxy_10y",
        "official_russell_1000_false": readiness.get("official_russell_1000") is False,
        "proxy_10y_acceptance_pass": bool((readiness.get("proxy_10y_acceptance") or {}).get("pass")),
        "proxy_10y_universe_schema": universe_substrate.get("schema_version") == "proxy-10y-universe-substrate-v1",
        "proxy_10y_universe_substrate_pass": universe_substrate.get("status") == "proxy_10y_universe_ready",
        "proxy_10y_universe_ready_flag": universe_substrate.get("ready_for_proxy_10y_rebuild_review") is True,
        "proxy_10y_universe_no_blockers": not bool(universe_substrate.get("blockers") or []),
        "proxy_10y_universe_label": universe_substrate.get("pit_label") == "pit_proxy_universe",
        "proxy_10y_universe_not_official": universe_substrate.get("official_russell_1000") is False,
        "proxy_10y_universe_month_count_pass": _int_value(universe_substrate.get("month_count")) >= MIN_PROXY_MONTHS,
        "proxy_10y_universe_failed_month_count_zero": _int_value(universe_substrate.get("failed_month_count")) == 0,
        "proxy_10y_universe_candidate_floor_pass": _int_value(universe_substrate.get("candidate_row_count"))
        >= _int_value(universe_substrate.get("min_membership_count"), 400),
        "proxy_10y_universe_benchmark_coverage_pass": bool(
            (universe_substrate.get("benchmark_coverage") or {}).get("pass")
        ),
        "future_available_from_zero": ((readiness.get("future_available_from") or {}).get("future_available_from_rows") in (0, "0", 0.0)),
        "benchmark_coverage_pass": bool((readiness.get("benchmark_coverage") or {}).get("pass")),
        "metric_mode_broker_ledger_next_close": mode == OFFICIAL_METRIC_MODE,
        "portfolios_present": bool(portfolios),
        "cash_trap_audit_available": cash_available,
        "cash_trap_false": cash_ok,
    }

    portfolio_results: dict[str, dict[str, Any]] = {}
    for name, row in portfolios.items():
        years = _years(row)
        cagr = safe_float(row.get("cagr"))
        mdd = safe_float(row.get("max_dd"), safe_float(row.get("mdd")))
        is_cagr = safe_float(row.get("is_cagr"))
        ratio = _ratio(row)
        cagr_min = MAIN_CAGR_MIN if name == "main" else CONC_CAGR_MIN
        mdd_min = MAIN_MDD_MIN if name == "main" else CONC_MDD_MIN
        result = {
            "years": years,
            "cagr": cagr,
            "max_dd": mdd,
            "is_cagr": is_cagr,
            "oos_is_cagr_ratio": ratio,
            "years_pass": years >= MIN_PROXY_YEARS,
            "cagr_pass": cagr is not None and cagr >= cagr_min,
            "mdd_pass": mdd is not None and mdd >= mdd_min,
            "is_cagr_pass": is_cagr is not None and is_cagr >= IS_CAGR_MIN,
            "oos_is_ratio_pass": ratio is not None and math.isfinite(ratio) and ratio <= OOS_IS_RATIO_MAX,
            "metric_mode": row.get("official_metric_mode") or row.get("metric_mode") or mode,
        }
        result["pass"] = all(
            bool(result[key])
            for key in ("years_pass", "cagr_pass", "mdd_pass", "is_cagr_pass", "oos_is_ratio_pass")
        )
        portfolio_results[name] = result

    checks["portfolio_metric_gates_pass"] = bool(portfolio_results) and all(bool(row.get("pass")) for row in portfolio_results.values())

    blockers = sorted(key for key, value in checks.items() if not value)
    blockers.extend(cash_reasons)
    for name, row in portfolio_results.items():
        for key in ("years_pass", "cagr_pass", "mdd_pass", "is_cagr_pass", "oos_is_ratio_pass"):
            if row.get(key) is not True:
                blockers.append(f"{name}.{key}=false")
    blockers = sorted(set(blockers))
    passed = not blockers

    return {
        "schema_version": "proxy-10y-robustness-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "latest_run": str(run_dir),
        "status": "proxy_10y_robustness_pass" if passed else "not_ready",
        "proxy_10y_robustness_pass": passed,
        "evidence_label": "proxy_10y",
        "official_russell_1000": False,
        "promotion_allowed": False,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "human_approval_required": True,
        "allowed_uses": ["robust_human_review", "ready_for_human_review"] if passed else ["diagnostics"],
        "blocked_uses": ["official_promotion", "automatic_production_mutation", "live_trading"],
        "checks": checks,
        "blockers": blockers,
        "portfolio_results": portfolio_results,
        "thresholds": {
            "main_cagr_min": MAIN_CAGR_MIN,
            "main_max_dd_min": MAIN_MDD_MIN,
            "concentrated_cagr_min": CONC_CAGR_MIN,
            "concentrated_max_dd_min": CONC_MDD_MIN,
            "is_cagr_min": IS_CAGR_MIN,
            "oos_is_cagr_ratio_max": OOS_IS_RATIO_MAX,
            "min_proxy_years": MIN_PROXY_YEARS,
            "min_proxy_months": MIN_PROXY_MONTHS,
        },
        "source_files": {
            "ten_year_backtest_readiness": str(run_dir / "ten_year_backtest_readiness" / "summary.json"),
            "proxy_10y_universe_substrate": str(run_dir / "proxy_10y_universe_substrate" / "summary.json"),
            "official_metrics": str(run_dir / "account_evaluation" / "official_metrics.json"),
            "cash_reentry_quality": str(run_dir / "cash_reentry_quality" / "summary.json"),
        },
        "notes": [
            "proxy_10y robustness is not official Russell 1000 promotion evidence",
            "successful proxy_10y robustness can support Tier 3 robust human review only",
        ],
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Proxy 10Y Robustness",
        "",
        f"- status: `{payload.get('status')}`",
        f"- pass: `{payload.get('proxy_10y_robustness_pass')}`",
        f"- evidence label: `{payload.get('evidence_label')}`",
        f"- official Russell 1000: `{payload.get('official_russell_1000')}`",
        f"- promotion allowed: `{payload.get('promotion_allowed')}`",
        "",
        "## Checks",
        "",
        "| Check | Pass |",
        "| --- | --- |",
    ]
    for key, value in payload.get("checks", {}).items():
        lines.append(f"| `{key}` | `{bool(value)}` |")
    lines.extend(["", "## Portfolio Gates", "", "| Portfolio | Years | CAGR | MaxDD | IS CAGR | OOS/IS | Pass |", "| --- | ---: | ---: | ---: | ---: | ---: | --- |"])
    for name, row in payload.get("portfolio_results", {}).items():
        lines.append(
            f"| `{name}` | `{row.get('years')}` | `{row.get('cagr')}` | `{row.get('max_dd')}` | "
            f"`{row.get('is_cagr')}` | `{row.get('oos_is_cagr_ratio')}` | `{row.get('pass')}` |"
        )
    lines.extend(["", "## Blockers", ""])
    blockers = payload.get("blockers") or []
    if blockers:
        lines.extend(f"- `{item}`" for item in blockers)
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def write_outputs(payload: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check proxy 10Y robustness gate")
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/proxy_10y_robustness")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = classify_proxy_10y_robustness(args.latest_run)
    write_outputs(payload, repo_path(args.output_dir))
    evidence_policy_path = repo_path(args.latest_run) / "evidence_policy" / "proxy_10y_robustness.json"
    write_json(evidence_policy_path, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

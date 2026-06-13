#!/usr/bin/env python3
"""Separate official broker-ledger metrics from legacy research metrics.

This report is intentionally conservative: official performance evidence can
only come from broker replay metrics with next-close fills, integer shares,
cash, and costs. Legacy weight-level files are preserved as research context
but are wrapped with explicit DO_NOT_USE metadata so artifact readers do not
mistake them for production ship gates.
"""
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

try:
    from r1000_config import PORTFOLIO_GOAL_TARGETS
except Exception:  # pragma: no cover - isolated smoke fallback
    PORTFOLIO_GOAL_TARGETS = {
        "main": {"cagr": 0.35, "max_dd": -0.25},
        "concentrated": {"cagr": 0.50, "max_dd": -0.25},
    }


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/metric_hygiene"
OFFICIAL_METRIC_MODE = "broker_ledger_next_close"
PORTFOLIOS = ("main", "concentrated")
LEGACY_FILES = {
    "main": "backtest_metrics.json",
    "concentrated": "concentrated_backtest_metrics.json",
}
DEPRECATED_OUTPUTS = {
    "main": "deprecated_legacy_backtest_metrics.json",
    "concentrated": "deprecated_concentrated_weight_level_metrics.json",
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


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


def metric(row: dict[str, Any], *names: str) -> float | None:
    for name in names:
        if name in row:
            out = safe_float(row.get(name))
            if out is not None:
                return out
    return None


def pp(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 100.0, 4)


def pct(value: float | None) -> str:
    return "" if value is None else f"{value:.2%}"


def target_for(portfolio: str) -> dict[str, float]:
    target = PORTFOLIO_GOAL_TARGETS.get(portfolio, {})
    return {
        "cagr": float(target.get("cagr", 0.30 if portfolio == "main" else 0.50)),
        "max_dd": float(target.get("max_dd", -0.20 if portfolio == "main" else -0.25)),
    }


def load_account_row(latest_run: Path, portfolio: str) -> dict[str, Any]:
    official = read_json(latest_run / "account_evaluation" / "official_metrics.json")
    portfolios = official.get("portfolios") or {}
    row = portfolios.get(portfolio)
    return row if isinstance(row, dict) else {}


def cash_trap_status(portfolio: str, official: dict[str, Any], account_state: dict[str, Any]) -> dict[str, Any]:
    target = target_for(portfolio)
    avg_cash = metric(official, "avg_cash_weight")
    latest_cash = metric(account_state, "cash_weight")
    max_dd = metric(official, "max_dd", "max_drawdown")
    cagr = metric(official, "cagr", "strategy_cagr")
    mdd_gap = None if max_dd is None else max(0.0, target["max_dd"] - max_dd)
    cagr_gap = None if cagr is None else max(0.0, target["cagr"] - cagr)
    avg_cash_high = bool(avg_cash is not None and avg_cash >= (0.20 if portfolio == "main" else 0.25))
    latest_cash_high = bool(latest_cash is not None and latest_cash >= 0.50)
    no_mdd_defense = bool(mdd_gap is not None and mdd_gap >= 0.05)
    cagr_miss = bool(cagr_gap is not None and cagr_gap > 0.0)
    trapped = bool((avg_cash_high and no_mdd_defense) or latest_cash_high)
    reasons: list[str] = []
    if avg_cash_high and no_mdd_defense:
        reasons.append("avg_cash_high_without_mdd_target_pass")
    if latest_cash_high:
        reasons.append("latest_cash_above_50pct_requires_crisis_state_review")
    if cagr_miss and avg_cash_high:
        reasons.append("cash_drag_with_cagr_gap")
    return {
        "cash_trap": trapped,
        "severity": "warn" if trapped else "ok",
        "avg_cash_weight": avg_cash,
        "latest_cash_weight": latest_cash,
        "mdd_gap_pp": pp(mdd_gap),
        "cagr_gap_pp": pp(cagr_gap),
        "reasons": reasons,
    }


def official_portfolio(latest_run: Path, portfolio: str) -> dict[str, Any]:
    broker_path = latest_run / "broker_replay" / portfolio / "metrics.json"
    broker = read_json(broker_path)
    account_row = load_account_row(latest_run, portfolio)
    account_state = read_json(latest_run / "broker_replay" / portfolio / "account_state_latest.json")
    target = target_for(portfolio)
    cagr = metric(broker, "cagr", "strategy_cagr")
    max_dd = metric(broker, "max_dd", "max_drawdown")
    metric_mode = str(broker.get("metric_mode") or "")
    valid = bool(broker.get("status") == "completed" and broker.get("valid_for_production") and metric_mode == OFFICIAL_METRIC_MODE)
    cagr_pass = bool(valid and cagr is not None and cagr >= target["cagr"])
    dd_pass = bool(valid and max_dd is not None and max_dd >= target["max_dd"])
    return {
        "portfolio": portfolio,
        "official_source": f"broker_replay/{portfolio}/metrics.json",
        "official_source_exists": broker_path.exists(),
        "official_metric_mode": metric_mode or OFFICIAL_METRIC_MODE,
        "production_valid": valid,
        "status": broker.get("status") or "missing",
        "target_pass": bool(cagr_pass and dd_pass),
        "cagr": cagr,
        "cagr_target": target["cagr"],
        "cagr_gap_pp": pp(None if cagr is None else max(0.0, target["cagr"] - cagr)),
        "max_dd": max_dd,
        "max_dd_target": target["max_dd"],
        "max_dd_gap_pp": pp(None if max_dd is None else max(0.0, target["max_dd"] - max_dd)),
        "sharpe": metric(broker, "sharpe"),
        "avg_cash_weight": metric(broker, "avg_cash_weight"),
        "latest_cash_weight": metric(account_state, "cash_weight"),
        "account_evaluation_target_pass": account_row.get("target_pass"),
        "account_evaluation_source": "account_evaluation/official_metrics.json" if account_row else "",
        "cash_trap_guard": cash_trap_status(portfolio, broker, account_state),
    }


def deprecated_portfolio(latest_run: Path, output_dir: Path, portfolio: str, official: dict[str, Any]) -> dict[str, Any]:
    legacy_name = LEGACY_FILES[portfolio]
    legacy_path = latest_run / legacy_name
    legacy = read_json(legacy_path)
    legacy_cagr = metric(legacy, "cagr", "strategy_cagr")
    legacy_dd = metric(legacy, "max_dd", "max_drawdown")
    wrapper = {
        "schema_version": "deprecated-metric-wrapper-v1",
        "DO_NOT_USE_FOR_PRODUCTION": True,
        "production_valid": False,
        "official_metric_required": OFFICIAL_METRIC_MODE,
        "deprecated_source": legacy_name,
        "deprecated_reason": "legacy_weight_level_or_proxy_metric_without_broker_ledger_fills_cash_integer_shares_and_costs",
        "portfolio": portfolio,
        "legacy_metric_mode": "weight_level_research_deprecated",
        "legacy_cagr": legacy_cagr,
        "legacy_max_dd": legacy_dd,
        "official_source": official.get("official_source"),
        "official_cagr": official.get("cagr"),
        "official_max_dd": official.get("max_dd"),
        "legacy_minus_official_cagr_pp": pp(None if legacy_cagr is None or official.get("cagr") is None else legacy_cagr - float(official["cagr"])),
        "legacy_minus_official_max_dd_pp": pp(None if legacy_dd is None or official.get("max_dd") is None else legacy_dd - float(official["max_dd"])),
        "original_payload": legacy,
    }
    write_json(output_dir / DEPRECATED_OUTPUTS[portfolio], wrapper)
    return {
        "portfolio": portfolio,
        "source": legacy_name,
        "exists": legacy_path.exists(),
        "deprecated_output": DEPRECATED_OUTPUTS[portfolio],
        "DO_NOT_USE_FOR_PRODUCTION": True,
        "production_valid": False,
        "official_metric_required": OFFICIAL_METRIC_MODE,
        "legacy_cagr": legacy_cagr,
        "legacy_max_dd": legacy_dd,
        "legacy_minus_official_cagr_pp": wrapper["legacy_minus_official_cagr_pp"],
        "legacy_minus_official_max_dd_pp": wrapper["legacy_minus_official_max_dd_pp"],
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Metric Hygiene Report",
        "",
        "Official performance evidence is broker-ledger only: next-close fills, integer shares, cash, and costs.",
        "Legacy/proxy/weight-level metrics are retained as deprecated research context and cannot produce a production verdict.",
        "",
        "## Official Metrics",
        "",
        "| Portfolio | CAGR | Target | MDD | Target | Sharpe | Avg Cash | Target Pass | Production Valid | Cash Trap |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload.get("official_portfolios", {}).values():
        cash = row.get("cash_trap_guard") or {}
        lines.append(
            "| {portfolio} | {cagr} | {cagr_target} | {max_dd} | {dd_target} | {sharpe:.3f} | {avg_cash} | {target_pass} | {prod_valid} | {cash_trap} |".format(
                portfolio=row.get("portfolio"),
                cagr=pct(row.get("cagr")),
                cagr_target=pct(row.get("cagr_target")),
                max_dd=pct(row.get("max_dd")),
                dd_target=pct(row.get("max_dd_target")),
                sharpe=safe_float(row.get("sharpe"), 0.0) or 0.0,
                avg_cash=pct(row.get("avg_cash_weight")),
                target_pass=str(row.get("target_pass")).lower(),
                prod_valid=str(row.get("production_valid")).lower(),
                cash_trap=str(cash.get("cash_trap")).lower(),
            )
        )
    lines.extend(["", "## Deprecated Metrics", ""])
    for row in payload.get("deprecated_metrics", []):
        lines.append(
            "- `{source}` -> `{deprecated_output}`: DO_NOT_USE_FOR_PRODUCTION=true, production_valid=false".format(
                source=row.get("source"),
                deprecated_output=row.get("deprecated_output"),
            )
        )
    lines.extend(["", "## Cash Trap Guard", ""])
    for row in payload.get("official_portfolios", {}).values():
        cash = row.get("cash_trap_guard") or {}
        reasons = ", ".join(cash.get("reasons") or []) or "none"
        lines.append(f"- `{row.get('portfolio')}`: severity=`{cash.get('severity')}`, reasons={reasons}")
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    official = {portfolio: official_portfolio(latest_run, portfolio) for portfolio in PORTFOLIOS}
    deprecated = [deprecated_portfolio(latest_run, output_dir, portfolio, official[portfolio]) for portfolio in PORTFOLIOS]
    cash_trap_warnings = [
        portfolio
        for portfolio, row in official.items()
        if bool((row.get("cash_trap_guard") or {}).get("cash_trap"))
    ]
    official_missing = [
        portfolio
        for portfolio, row in official.items()
        if not row.get("official_source_exists") or row.get("official_metric_mode") != OFFICIAL_METRIC_MODE
    ]
    payload = {
        "schema_version": "metric-hygiene-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "latest_run": str(latest_run),
        "official_metric_mode": OFFICIAL_METRIC_MODE,
        "official_metric_required": OFFICIAL_METRIC_MODE,
        "official_portfolios": official,
        "production_target_pass": all(bool(row.get("target_pass")) for row in official.values()),
        "production_valid_all": all(bool(row.get("production_valid")) for row in official.values()),
        "deprecated_metrics": deprecated,
        "cash_trap_warning_count": int(len(cash_trap_warnings)),
        "cash_trap_warning_portfolios": cash_trap_warnings,
        "official_metric_issue_count": int(len(official_missing)),
        "official_metric_issue_portfolios": official_missing,
    }
    write_json(output_dir / "summary.json", payload)
    write_json(output_dir / "official_metrics.json", {
        "schema_version": payload["schema_version"],
        "official_metric_mode": OFFICIAL_METRIC_MODE,
        "production_target_pass": payload["production_target_pass"],
        "production_valid_all": payload["production_valid_all"],
        "portfolios": official,
    })
    write_json(output_dir / "deprecated_metric_manifest.json", {
        "schema_version": payload["schema_version"],
        "official_metric_required": OFFICIAL_METRIC_MODE,
        "deprecated_metrics": deprecated,
    })
    write_text(output_dir / "report.md", render_report(payload))
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

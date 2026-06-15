#!/usr/bin/env python3
"""Audit the locked IS/OOS split for broker-ledger promotion evidence.

The broker replay already stores IS/OOS windows, but promotion needs a separate
artifact with fixed lock parameters so repeated tuning on the same 8-year
window cannot silently pass as forward-robust evidence.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.run_broker_ledger_replay import (  # noqa: E402
    DEFAULT_OOS2_START,
    DEFAULT_OOS_START,
    calc_metrics_with_oos,
)


PORTFOLIOS = ("main", "concentrated")
DEFAULT_CONFIG = {
    "schema_version": "oos-lock-v1",
    "oos_start": DEFAULT_OOS_START,
    "oos2_start": DEFAULT_OOS2_START,
    "max_degradation_floor_pp": 5.0,
    "max_degradation_is_fraction": 0.20,
    "max_oos_is_cagr_ratio": 3.0,
    "min_oos_trading_days": 252,
    "baseline_is_cagr": {"main": 0.25, "concentrated": 0.30},
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO / path


def clean_value(value: str) -> Any:
    value = value.split("#", 1)[0].strip().strip("\"'")
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        number = float(value)
    except ValueError:
        return value
    return int(number) if number.is_integer() else number


def load_lock_config(path: Path) -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if not path.exists():
        config["config_path"] = str(path)
        config["config_missing"] = True
        return config
    active_section = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith((" ", "\t")):
            if active_section == "baseline_is_cagr" and ":" in raw:
                key, value = raw.split(":", 1)
                config["baseline_is_cagr"][key.strip()] = float(clean_value(value))
            continue
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        if value.strip():
            config[key] = clean_value(value)
            active_section = ""
        else:
            active_section = key
            if key == "baseline_is_cagr":
                config[key] = dict(config.get(key) or {})
    config["config_path"] = str(path)
    config["config_missing"] = False
    return config


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


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def threshold_pp(config: dict[str, Any], portfolio: str, is_cagr: float | None) -> tuple[float, str, float | None]:
    floor = float(config.get("max_degradation_floor_pp", 5.0))
    fraction = float(config.get("max_degradation_is_fraction", 0.20))
    baselines = config.get("baseline_is_cagr") if isinstance(config.get("baseline_is_cagr"), dict) else {}
    baseline = safe_float(baselines.get(portfolio), is_cagr)
    if baseline is None:
        return floor, "floor_only", None
    derived = baseline * fraction * 100.0
    return max(floor, derived), "max_floor_or_baseline_fraction", baseline


def audit_portfolio(latest_run: Path, portfolio: str, config: dict[str, Any]) -> dict[str, Any]:
    broker_dir = latest_run / "broker_replay" / portfolio
    equity_path = broker_dir / "equity_curve.csv"
    trades_path = broker_dir / "trades.csv"
    broker_metrics = read_json(broker_dir / "metrics.json")
    equity = read_csv_or_empty(equity_path)
    trades = read_csv_or_empty(trades_path)
    failures: list[str] = []
    if equity.empty:
        return {
            "portfolio": portfolio,
            "status": "fail",
            "pass": False,
            "failures": ["equity_curve_missing_or_empty"],
            "equity_curve_path": str(equity_path),
            "trades_path": str(trades_path),
        }
    if "equity_usd" not in equity.columns or "date" not in equity.columns:
        return {
            "portfolio": portfolio,
            "status": "fail",
            "pass": False,
            "failures": ["equity_curve_required_columns_missing"],
            "equity_curve_path": str(equity_path),
            "columns": list(equity.columns),
        }
    equity_values = pd.to_numeric(equity["equity_usd"], errors="coerce").dropna()
    starting_capital = safe_float(broker_metrics.get("starting_capital_usd"))
    if starting_capital is None:
        starting_capital = safe_float(equity_values.iloc[0] if not equity_values.empty else None)
    if starting_capital is None or starting_capital <= 0:
        return {
            "portfolio": portfolio,
            "status": "fail",
            "pass": False,
            "failures": ["starting_capital_invalid"],
            "equity_curve_path": str(equity_path),
        }
    windows = calc_metrics_with_oos(
        equity,
        trades,
        float(starting_capital),
        oos_start=str(config.get("oos_start") or ""),
        oos2_start=str(config.get("oos2_start") or "") if config.get("oos2_start") else None,
    )
    full = windows.get("full") if isinstance(windows.get("full"), dict) else {}
    is_window = windows.get("is") if isinstance(windows.get("is"), dict) else {}
    oos_window = windows.get("oos") if isinstance(windows.get("oos"), dict) else {}
    if full.get("status") != "completed":
        failures.append("full_window_not_completed")
    if is_window.get("status") != "completed":
        failures.append("is_window_not_completed")
    if oos_window.get("status") != "completed":
        failures.append("oos_window_not_completed")
    if full.get("metric_mode") != "broker_ledger_next_close":
        failures.append("metric_mode_not_broker_ledger_next_close")
    is_cagr = safe_float(is_window.get("cagr"))
    oos_cagr = safe_float(oos_window.get("cagr"))
    threshold, threshold_source, baseline = threshold_pp(config, portfolio, is_cagr)
    degradation_pp = None if is_cagr is None or oos_cagr is None else (is_cagr - oos_cagr) * 100.0
    ratio = None
    if is_cagr is not None and oos_cagr is not None and is_cagr > 0.01:
        ratio = oos_cagr / is_cagr
    if degradation_pp is None:
        failures.append("oos_degradation_not_computable")
    elif degradation_pp > threshold + 1e-12:
        failures.append("oos_cagr_degradation_above_lock")
    max_ratio = safe_float(config.get("max_oos_is_cagr_ratio"), 3.0)
    if ratio is not None and max_ratio is not None and ratio > max_ratio + 1e-12:
        failures.append("oos_is_cagr_ratio_above_lock")
    min_oos_days = int(float(config.get("min_oos_trading_days", 252)))
    oos_days = int(float(oos_window.get("days") or 0))
    if oos_days < min_oos_days:
        failures.append("oos_trading_days_below_min")
    broker_mode = str(broker_metrics.get("metric_mode") or "")
    if broker_metrics and broker_mode != "broker_ledger_next_close":
        failures.append("broker_metrics_mode_not_broker_ledger_next_close")
    passed = not failures
    return {
        "portfolio": portfolio,
        "status": "pass" if passed else "fail",
        "pass": passed,
        "failures": failures,
        "equity_curve_path": str(equity_path),
        "trades_path": str(trades_path),
        "metric_mode": full.get("metric_mode"),
        "broker_metrics_mode": broker_mode,
        "oos_start": config.get("oos_start"),
        "oos2_start": config.get("oos2_start"),
        "cagr_is": is_cagr,
        "cagr_oos": oos_cagr,
        "mdd_is": safe_float(is_window.get("max_dd")),
        "mdd_oos": safe_float(oos_window.get("max_dd")),
        "oos_degradation_pp": degradation_pp,
        "oos_is_cagr_ratio": ratio,
        "max_allowed_degradation_pp": threshold,
        "max_oos_is_cagr_ratio": max_ratio,
        "threshold_source": threshold_source,
        "baseline_is_cagr": baseline,
        "min_oos_trading_days": min_oos_days,
        "oos_trading_days": oos_days,
        "windows": windows,
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# OOS Lock Audit",
        "",
        f"- status: `{payload.get('status')}`",
        f"- lock_pass: `{str(payload.get('lock_pass')).lower()}`",
        f"- oos_start: `{payload.get('config', {}).get('oos_start')}`",
        f"- production_activation_allowed: `{str(payload.get('production_activation_allowed')).lower()}`",
        "",
        "| Portfolio | Status | IS CAGR | OOS CAGR | OOS/IS | Degradation | Max Allowed | OOS Days | Failures |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for portfolio, row in sorted((payload.get("portfolios") or {}).items()):
        deg = row.get("oos_degradation_pp")
        max_allowed = row.get("max_allowed_degradation_pp")
        lines.append(
            "| {p} | {status} | {is_cagr:.2%} | {oos_cagr:.2%} | {ratio} | {deg} | {allowed} | {days} | {failures} |".format(
                p=portfolio,
                status=row.get("status"),
                is_cagr=safe_float(row.get("cagr_is"), 0.0) or 0.0,
                oos_cagr=safe_float(row.get("cagr_oos"), 0.0) or 0.0,
                ratio="" if row.get("oos_is_cagr_ratio") is None else f"{float(row.get('oos_is_cagr_ratio')):.2f}x",
                deg="" if deg is None else f"{float(deg):.2f}pp",
                allowed="" if max_allowed is None else f"{float(max_allowed):.2f}pp",
                days=row.get("oos_trading_days") or 0,
                failures=", ".join(row.get("failures") or []) or "none",
            )
        )
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    config = load_lock_config(repo_path(args.config))
    portfolios = [p.strip() for p in str(args.portfolios).split(",") if p.strip()]
    rows = {portfolio: audit_portfolio(latest_run, portfolio, config) for portfolio in portfolios}
    failures = {
        portfolio: row.get("failures") or []
        for portfolio, row in rows.items()
        if row.get("status") != "pass"
    }
    payload = {
        "schema_version": "oos-lock-audit-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "latest_run": str(latest_run),
        "config": config,
        "status": "pass" if not failures else "fail",
        "lock_pass": not failures,
        "production_activation_allowed": False,
        "hard_blocker_count": sum(len(v) for v in failures.values()),
        "portfolios": rows,
        "failures": failures,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", payload)
    write_json(output_dir / "oos_report.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "hard_blockers": payload["hard_blocker_count"]}, indent=2))
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/oos_lock")
    parser.add_argument("--config", default="research/oos_lock.yaml")
    parser.add_argument("--portfolios", default="main,concentrated")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    run(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

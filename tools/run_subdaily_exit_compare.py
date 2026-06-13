#!/usr/bin/env python3
"""Sub-monthly exit comparison overlay (Stage T2).

Compares the OFFICIAL monthly broker-ledger replay vs the daily-stop overlay
already produced by `run_position_risk_weekly_validation.py`. The PRWV tool
walks daily closes between monthly rebalances and fires hard / trailing /
relative-strength stops; broker_replay only fills on monthly target_rebalance.

This tool surfaces the trade-off (CAGR vs MaxDD) and the activity volume
(hard_stop / trailing_stop / relative_exit / trim counts) on both portfolios
side-by-side. Promotion to production is NOT done here — that requires a
parameter sweep (T2b) and broker-ledger gate confirmation. This is the
measurement layer that makes the trade-off visible.

Inputs:
  outputs/broker_replay/{portfolio}/metrics.json     (monthly baseline)
  outputs/position_risk_weekly_validation/{portfolio}/{metrics.json,trade_log.csv,actions.csv}

Outputs:
  outputs/subdaily_exit_compare/comparison.json
  outputs/subdaily_exit_compare/comparison_report.md
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def repo_path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else REPO_ROOT / p


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if math.isnan(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def baseline_metrics(broker_metrics: dict[str, Any]) -> dict[str, Any]:
    """Pull the broker-ledger monthly baseline numbers for comparison."""
    if not broker_metrics:
        return {"status": "missing"}
    return {
        "status": broker_metrics.get("status") or "unknown",
        "label": broker_metrics.get("label") or "full",
        "cagr": safe_float(broker_metrics.get("cagr")),
        "sharpe": safe_float(broker_metrics.get("sharpe")),
        "max_dd": safe_float(broker_metrics.get("max_dd")),
        "avg_cash_weight": safe_float(broker_metrics.get("avg_cash_weight")),
        "trade_count": int(safe_float(broker_metrics.get("trade_count"))),
        "total_fees_usd": safe_float(broker_metrics.get("total_fees_usd")),
        "start_date": broker_metrics.get("start_date"),
        "end_date": broker_metrics.get("end_date"),
        "years": safe_float(broker_metrics.get("years")),
        "metric_mode": broker_metrics.get("metric_mode"),
    }


def overlay_metrics(prwv_metrics: dict[str, Any]) -> dict[str, Any]:
    """Daily-stop overlay numbers (from position_risk_weekly_validation)."""
    if not prwv_metrics:
        return {"status": "missing"}
    return {
        "status": prwv_metrics.get("status") or "unknown",
        "cagr": safe_float(prwv_metrics.get("cagr")),
        "sharpe": safe_float(prwv_metrics.get("sharpe")),
        "max_dd": safe_float(prwv_metrics.get("max_dd")),
        "avg_cash_weight": safe_float(prwv_metrics.get("avg_cash_weight")),
        "exit_count": int(safe_float(prwv_metrics.get("exit_count"))),
        "trim_count": int(safe_float(prwv_metrics.get("trim_count"))),
        "hard_stop": safe_float(prwv_metrics.get("hard_stop")),
        "trailing_stop": safe_float(prwv_metrics.get("trailing_stop")),
        "trailing_activation": safe_float(prwv_metrics.get("trailing_activation")),
        "relative_exit_threshold": safe_float(prwv_metrics.get("relative_exit_threshold")),
        "relative_trim_threshold": safe_float(prwv_metrics.get("relative_trim_threshold")),
        "months": int(safe_float(prwv_metrics.get("months"))),
        "metric_mode": prwv_metrics.get("metric_mode"),
        "research_only": bool(prwv_metrics.get("research_only", True)),
        "valid_for_production": bool(prwv_metrics.get("valid_for_production", False)),
    }


def exit_reason_breakdown(trade_log: pd.DataFrame) -> dict[str, int]:
    if trade_log.empty:
        return {}
    df = trade_log.copy()
    reasons = df.get("reason", pd.Series(dtype=str)).astype(str).fillna("unknown")
    sides = df.get("side", pd.Series(dtype=str)).astype(str).str.upper()
    sell_mask = sides.eq("SELL")
    if not bool(sell_mask.any()):
        return {}
    return dict(Counter(reasons[sell_mask].tolist()))


def compute_delta(baseline: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    if baseline.get("status") == "missing" or overlay.get("status") == "missing":
        return {"status": "incomplete"}
    return {
        "status": "ok",
        "delta_cagr_pp": (overlay["cagr"] - baseline["cagr"]) * 100.0,
        "delta_max_dd_pp": (overlay["max_dd"] - baseline["max_dd"]) * 100.0,
        "delta_sharpe": overlay["sharpe"] - baseline["sharpe"],
        "delta_avg_cash_pp": (overlay["avg_cash_weight"] - baseline["avg_cash_weight"]) * 100.0,
        "interpretation": _interpret_trade_off(
            (overlay["cagr"] - baseline["cagr"]) * 100.0,
            (overlay["max_dd"] - baseline["max_dd"]) * 100.0,
        ),
    }


def _interpret_trade_off(delta_cagr_pp: float, delta_max_dd_pp: float) -> str:
    # max_dd is negative; positive delta = less drawdown
    if delta_max_dd_pp >= 3.0 and delta_cagr_pp >= -2.0:
        return "favourable: meaningful MDD reduction, small CAGR cost"
    if delta_max_dd_pp >= 3.0 and delta_cagr_pp >= -5.0:
        return "trade-off: real MDD reduction but tangible CAGR drag"
    if delta_max_dd_pp >= 3.0:
        return "expensive: MDD better but CAGR cost too large to promote as-is"
    if delta_max_dd_pp < 0.0:
        return "no win: overlay made MDD worse"
    return "marginal"


def evaluate_portfolio(portfolio: str, latest: Path) -> dict[str, Any]:
    broker = load_json(latest / "broker_replay" / portfolio / "metrics.json")
    prwv = load_json(latest / "position_risk_weekly_validation" / portfolio / "metrics.json")
    trade_log = load_csv(latest / "position_risk_weekly_validation" / portfolio / "trade_log.csv")

    baseline = baseline_metrics(broker)
    overlay = overlay_metrics(prwv)
    delta = compute_delta(baseline, overlay)
    reasons = exit_reason_breakdown(trade_log)

    return {
        "portfolio": portfolio,
        "schema_version": "subdaily_exit_compare_v1",
        "baseline_broker_ledger_monthly": baseline,
        "overlay_daily_stop": overlay,
        "delta": delta,
        "overlay_exit_reason_counts": reasons,
        "production_activation_allowed": False,
    }


def render_report(summary: dict[str, Any]) -> str:
    lines = ["# Sub-Monthly Exit Comparison (Stage T2)", ""]
    lines.append("Compares the official monthly broker-ledger replay vs the daily-stop")
    lines.append("overlay already produced by `run_position_risk_weekly_validation.py`.")
    lines.append("Research-only — no production change. Use this to decide whether the")
    lines.append("stops are tuned correctly (too tight = CAGR drag; too loose = no MDD")
    lines.append("improvement) before promoting any sub-monthly exit logic.")
    lines.append("")
    for portfolio in ("main", "concentrated"):
        block = summary.get(portfolio)
        if not block:
            continue
        lines.append(f"## {portfolio}")
        lines.append("")
        b = block.get("baseline_broker_ledger_monthly") or {}
        o = block.get("overlay_daily_stop") or {}
        d = block.get("delta") or {}
        if b.get("status") == "missing":
            lines.append("- baseline broker-ledger metrics MISSING — cannot compare")
            lines.append("")
            continue
        if o.get("status") == "missing":
            lines.append("- daily-stop overlay metrics MISSING — run position_risk_weekly_validation first")
            lines.append("")
            continue
        lines.append("| metric | baseline (monthly) | overlay (daily stops) | delta |")
        lines.append("|---|---:|---:|---:|")
        lines.append(
            f"| CAGR | {b['cagr']:.2%} | {o['cagr']:.2%} | {d['delta_cagr_pp']:+.2f}pp |"
        )
        lines.append(
            f"| MaxDD | {b['max_dd']:.2%} | {o['max_dd']:.2%} | {d['delta_max_dd_pp']:+.2f}pp |"
        )
        lines.append(
            f"| Sharpe | {b['sharpe']:.4f} | {o['sharpe']:.4f} | {d['delta_sharpe']:+.4f} |"
        )
        lines.append(
            f"| avg_cash | {b['avg_cash_weight']:.2%} | {o['avg_cash_weight']:.2%} | {d['delta_avg_cash_pp']:+.2f}pp |"
        )
        lines.append(f"| trades | {b['trade_count']} | overlay exits {o['exit_count']} / trims {o['trim_count']} | — |")
        lines.append("")
        lines.append(
            f"- overlay stops: hard {o['hard_stop']:.0%} | trailing {o['trailing_stop']:.0%} after +{o['trailing_activation']:.0%} | relative_exit {o['relative_exit_threshold']:.0%}"
        )
        lines.append(f"- interpretation: **{d.get('interpretation', 'n/a')}**")
        reasons = block.get("overlay_exit_reason_counts") or {}
        if reasons:
            top = sorted(reasons.items(), key=lambda kv: kv[1], reverse=True)[:8]
            lines.append("- overlay exit reasons (top): " + ", ".join(f"{k}={v}" for k, v in top))
        lines.append("")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/subdaily_exit_compare")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest = repo_path(args.latest_run)
    out_dir = repo_path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "schema_version": "subdaily_exit_compare_v1",
        "latest_run": str(latest),
    }
    for portfolio in ("main", "concentrated"):
        summary[portfolio] = evaluate_portfolio(portfolio, latest)
    write_json(out_dir / "comparison.json", summary)
    write_text(out_dir / "comparison_report.md", render_report(summary))
    print(f"[subdaily_exit_compare] wrote {out_dir / 'comparison.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

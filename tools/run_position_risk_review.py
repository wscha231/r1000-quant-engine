#!/usr/bin/env python3
"""Summarize broker-ledger position-risk replay impact.

This is an operator-review sidecar for deciding whether daily risk exits/trims
deserve deeper broker-ledger testing. It compares the official account replay
against the position-risk challenger without changing production defaults.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


PORTFOLIOS = ("main", "concentrated")


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def metric_delta(candidate: dict[str, Any], base: dict[str, Any], key: str) -> float | None:
    lhs = safe_float(candidate.get(key), None)
    rhs = safe_float(base.get(key), None)
    if lhs is None or rhs is None:
        return None
    return float(lhs - rhs)


def base_trade_count(base: dict[str, Any]) -> float | None:
    return safe_float(base.get("broker_trade_count", base.get("trade_count")), None)


def decision_for(row: dict[str, Any]) -> str:
    if row.get("official_metric_mode") != "broker_ledger_next_close":
        return "DO_NOT_USE"
    if not row.get("base_valid_for_production"):
        return "DO_NOT_USE"
    if row.get("position_risk_status") != "completed":
        return "NO_POSITION_RISK_REPLAY"
    if row.get("position_risk_metric_mode") != "broker_ledger_position_risk_next_close":
        return "DO_NOT_USE"
    if not row.get("position_risk_valid_for_production"):
        return "DO_NOT_USE"
    cagr_delta = safe_float(row.get("position_risk_cagr_delta"), None)
    mdd_improvement = safe_float(row.get("position_risk_mdd_improvement"), None)
    if cagr_delta is None or mdd_improvement is None:
        return "REVIEW_REQUIRED"
    if mdd_improvement >= 0.05 and cagr_delta >= -0.005:
        return "BROKER_LEDGER_CANDIDATE"
    if mdd_improvement >= 0.05:
        return "REJECT_CAGR_DRAG"
    if cagr_delta >= 0.005 and mdd_improvement >= 0.0:
        return "BROKER_LEDGER_CANDIDATE"
    return "REVIEW_REQUIRED"


def build_review(latest_run: Path) -> dict[str, Any]:
    official = load_json(latest_run / "account_evaluation" / "official_metrics.json")
    portfolios = official.get("portfolios") if isinstance(official.get("portfolios"), dict) else {}
    rows: list[dict[str, Any]] = []
    for portfolio in PORTFOLIOS:
        base = portfolios.get(portfolio) if isinstance(portfolios.get(portfolio), dict) else {}
        risk = load_json(latest_run / "broker_position_risk_replay" / portfolio / "metrics.json")
        cagr_delta = metric_delta(risk, base, "cagr")
        mdd_delta = metric_delta(risk, base, "max_dd")
        base_trades = base_trade_count(base)
        risk_trades = safe_float(risk.get("trade_count"), None)
        trade_delta = None if base_trades is None or risk_trades is None else float(risk_trades - base_trades)
        official_mode = base.get("official_metric_mode") or official.get("official_metric_mode")
        row = {
            "portfolio_kind": portfolio,
            "official_metric_mode": official_mode,
            "base_status": base.get("status", ""),
            "base_valid_for_production": bool(base.get("valid_for_production")),
            "base_cagr": safe_float(base.get("cagr"), None),
            "base_max_dd": safe_float(base.get("max_dd"), None),
            "base_sharpe": safe_float(base.get("sharpe"), None),
            "base_trade_count": base_trades,
            "base_total_fees_usd": safe_float(base.get("total_fees_usd"), None),
            "position_risk_status": risk.get("status", "missing"),
            "position_risk_metric_mode": risk.get("metric_mode", ""),
            "position_risk_valid_for_production": bool(risk.get("valid_for_production")),
            "position_risk_cagr": safe_float(risk.get("cagr"), None),
            "position_risk_max_dd": safe_float(risk.get("max_dd"), None),
            "position_risk_sharpe": safe_float(risk.get("sharpe"), None),
            "position_risk_trade_count": risk_trades,
            "position_risk_total_fees_usd": safe_float(risk.get("total_fees_usd"), None),
            "position_risk_risk_exit_count": safe_float(risk.get("risk_exit_count"), None),
            "position_risk_risk_trim_count": safe_float(risk.get("risk_trim_count"), None),
            "position_risk_cagr_delta": cagr_delta,
            "position_risk_mdd_improvement": None if mdd_delta is None else float(mdd_delta),
            "position_risk_trade_count_delta": trade_delta,
            "position_risk_fee_delta_usd": metric_delta(risk, base, "total_fees_usd"),
        }
        row["decision"] = decision_for(row)
        rows.append(row)

    return {
        "schema_version": "position-risk-review-v1",
        "production_activation_allowed": False,
        "research_only": True,
        "official_metric_required": "broker_ledger_next_close",
        "challenger_metric_required": "broker_ledger_position_risk_next_close",
        "rows": rows,
    }


def pct(value: Any) -> str:
    number = safe_float(value, None)
    return "" if number is None else f"{number:.2%}"


def number(value: Any) -> str:
    number_value = safe_float(value, None)
    return "" if number_value is None else f"{number_value:,.0f}"


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Position Risk Review",
        "",
        "Research-only review of daily risk exits/trims against official broker-ledger base replay.",
        "",
        f"- Production activation allowed: `{str(payload.get('production_activation_allowed')).lower()}`",
        f"- Official metric required: `{payload.get('official_metric_required')}`",
        f"- Challenger metric required: `{payload.get('challenger_metric_required')}`",
        "",
        "| Portfolio | Decision | Base CAGR | Risk CAGR | CAGR Delta | Base MDD | Risk MDD | MDD Improvement | Base Trades | Risk Trades | Risk Exits | Risk Trims |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload.get("rows", []):
        lines.append(
            "| {portfolio} | `{decision}` | {base_cagr} | {risk_cagr} | {cagr_delta} | {base_mdd} | {risk_mdd} | {mdd_improvement} | {base_trades} | {risk_trades} | {risk_exits} | {risk_trims} |".format(
                portfolio=row.get("portfolio_kind", ""),
                decision=row.get("decision", ""),
                base_cagr=pct(row.get("base_cagr")),
                risk_cagr=pct(row.get("position_risk_cagr")),
                cagr_delta=pct(row.get("position_risk_cagr_delta")),
                base_mdd=pct(row.get("base_max_dd")),
                risk_mdd=pct(row.get("position_risk_max_dd")),
                mdd_improvement=pct(row.get("position_risk_mdd_improvement")),
                base_trades=number(row.get("base_trade_count")),
                risk_trades=number(row.get("position_risk_trade_count")),
                risk_exits=number(row.get("position_risk_risk_exit_count")),
                risk_trims=number(row.get("position_risk_risk_trim_count")),
            )
        )
    lines.extend(
        [
            "",
            "Rules:",
            "- This file is operator review only; it is not a trade instruction.",
            "- Passing this review does not activate production.",
            "- Promotion still requires target gates, cost sensitivity, stress windows, and human approval.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(payload: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "position_risk_review.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (output_dir / "position_risk_review.md").write_text(render_markdown(payload), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/operator_review")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_review(repo_path(args.latest_run))
    write_outputs(payload, repo_path(args.output_dir))
    print(json.dumps({"schema_version": payload["schema_version"], "rows": len(payload["rows"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

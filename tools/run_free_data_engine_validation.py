#!/usr/bin/env python3
"""Summarize free-data engine validation metrics and next actions."""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_PROXY_DIR = "outputs/free_data_proxy_backtest"
DEFAULT_COVERAGE = "data_pit/free/coverage_audit.json"
DEFAULT_OUTPUT_DIR = "outputs/free_data_engine_validation"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def metric_row(label: str, portfolio: str, metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": label,
        "portfolio": portfolio,
        "status": metrics.get("status") or ("missing" if not metrics else "unknown"),
        "start_date": metrics.get("start_date"),
        "end_date": metrics.get("end_date"),
        "years": safe_float(metrics.get("years")),
        "cagr": safe_float(metrics.get("cagr")),
        "sharpe": safe_float(metrics.get("sharpe")),
        "max_dd": safe_float(metrics.get("max_dd") if "max_dd" in metrics else metrics.get("max_drawdown")),
        "ending_capital_usd": safe_float(metrics.get("ending_capital_usd")),
        "trade_count": safe_float(metrics.get("trade_count")),
        "avg_cash_weight": safe_float(metrics.get("avg_cash_weight")),
        "valid_for_production": metrics.get("valid_for_production"),
        "metric_mode": metrics.get("metric_mode"),
    }


def read_metric_pair(base: Path, label: str) -> list[dict[str, Any]]:
    return [
        metric_row(label, "main", read_json(base / "main" / "metrics.json", {}) or {}),
        metric_row(label, "concentrated", read_json(base / "concentrated" / "metrics.json", {}) or {}),
    ]


def load_policy_queue(latest_run: Path, limit: int = 5) -> list[dict[str, Any]]:
    payload = read_json(latest_run / "policy_fusion" / "policy_fusion_summary.json", {}) or {}
    queue = payload.get("activation_queue")
    if not isinstance(queue, list):
        return []
    out: list[dict[str, Any]] = []
    for row in queue[:limit]:
        if isinstance(row, dict):
            out.append(
                {
                    "policy_id": row.get("policy_id"),
                    "portfolio": row.get("portfolio"),
                    "priority": row.get("priority"),
                    "activation_stage": row.get("activation_stage"),
                    "fusion_score": row.get("fusion_score"),
                    "target_pass": row.get("target_pass"),
                }
            )
    return out


def classify_validation(coverage: dict[str, Any], metrics: list[dict[str, Any]]) -> str:
    proxy_rows = [row for row in metrics if row["label"] == "free_proxy_replay" and row["cagr"] is not None]
    if not coverage:
        return "missing_coverage"
    if coverage.get("readiness") != "ready_for_proxy_replay":
        return "data_not_ready"
    if len(proxy_rows) < 2:
        return "metrics_not_ready"
    return "ready_for_learning_review"


def next_actions(status: str, coverage: dict[str, Any]) -> list[str]:
    if status == "missing_coverage":
        return ["Run free_data_lake_bootstrap.yml so coverage_audit.json is created."]
    if status == "data_not_ready":
        actions = ["Populate free price cache with price_mode=target_books and sync it to Drive."]
        known_gaps = coverage.get("known_gaps") if isinstance(coverage, dict) else []
        if any("SEC companyfacts" in str(gap) for gap in known_gaps or []):
            actions.append("Enable sec_companyfacts=true after Drive sync is confirmed.")
        return actions
    if status == "metrics_not_ready":
        return ["Run broker-ledger proxy replay after price cache is populated."]
    return [
        "Run AutoLearning and policy-fusion review against the validated replay evidence.",
        "Promote only challenger rules that improve CAGR/Sharpe/MaxDD or reduce churn without raising drawdown.",
        "Keep outputs labeled pit_proxy_universe until historical Russell membership and delisted coverage are solved.",
    ]


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Free Data Engine Validation",
        "",
        f"- Generated UTC: {payload['generated_at_utc']}",
        f"- Status: `{payload['validation_status']}`",
        f"- PIT label: `{payload.get('pit_label')}`",
        "",
        "## Metrics",
        "",
        "| Label | Portfolio | Period | CAGR | Sharpe | MaxDD | Trades |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in payload["metrics"]:
        period = f"{row.get('start_date') or '?'} to {row.get('end_date') or '?'}"
        cagr = "" if row.get("cagr") is None else f"{row['cagr']:.2%}"
        sharpe = "" if row.get("sharpe") is None else f"{row['sharpe']:.3f}"
        max_dd = "" if row.get("max_dd") is None else f"{row['max_dd']:.2%}"
        trades = "" if row.get("trade_count") is None else f"{row['trade_count']:.0f}"
        lines.append(f"| {row['label']} | {row['portfolio']} | {period} | {cagr} | {sharpe} | {max_dd} | {trades} |")
    lines += ["", "## Learning Queue", ""]
    queue = payload.get("policy_queue") or []
    if queue:
        for row in queue:
            lines.append(
                f"- `{row.get('policy_id')}` ({row.get('portfolio')}): {row.get('priority')} / {row.get('activation_stage')} / score={row.get('fusion_score')}"
            )
    else:
        lines.append("- No policy-fusion queue available yet.")
    lines += ["", "## Next Actions", ""]
    for action in payload.get("next_actions", []):
        lines.append(f"- {action}")
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    proxy_dir = repo_path(args.proxy_backtest_dir)
    output_dir = repo_path(args.output_dir)
    coverage = read_json(repo_path(args.coverage), {}) or {}

    metrics = read_metric_pair(latest_run / "broker_replay", "latest_full_rebuild_broker")
    metrics.extend(read_metric_pair(proxy_dir, "free_proxy_replay"))

    status = classify_validation(coverage, metrics)
    payload = {
        "schema_version": "free-data-engine-validation-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "validation_status": status,
        "pit_label": coverage.get("pit_label"),
        "coverage_readiness": coverage.get("readiness"),
        "known_gaps": coverage.get("known_gaps", []),
        "metrics": metrics,
        "auto_learning_promotion": read_json(latest_run / "auto_learning_v2" / "promotion_decision.json", {}) or {},
        "policy_queue": load_policy_queue(latest_run),
    }
    payload["next_actions"] = next_actions(status, coverage)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    print(json.dumps({"status": status, "summary": str(output_dir / "summary.json")}, indent=2))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--proxy-backtest-dir", default=DEFAULT_PROXY_DIR)
    parser.add_argument("--coverage", default=DEFAULT_COVERAGE)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

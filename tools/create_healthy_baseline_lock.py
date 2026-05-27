#!/usr/bin/env python3
"""Create a healthy baseline lock from a completed full-rebuild artifact.

The lock is deliberately conservative. It is not created unless the run has a
broad scored universe and broker-ledger next-close official metrics. Challenger
tools can still run research-only without it, but promotion comparison remains
blocked.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


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


def broker_period_years(metrics: dict[str, Any]) -> float | None:
    years = safe_float(metrics.get("years"))
    if years is not None:
        return years
    start = pd.to_datetime(metrics.get("start_date"), errors="coerce")
    end = pd.to_datetime(metrics.get("end_date"), errors="coerce")
    if pd.isna(start) or pd.isna(end) or end <= start:
        return None
    return float((end - start).days / 365.25)


def guard_hard_error_count(guard: dict[str, Any]) -> int:
    explicit = safe_float(guard.get("hard_error_count"))
    if explicit is not None:
        return int(explicit)
    checks = guard.get("checks")
    if not isinstance(checks, list):
        return 0
    count = 0
    for item in checks:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "").lower()
        passed = bool(item.get("passed"))
        if not passed and severity in {"hard", "error", "critical"}:
            count += 1
    return count


def extract_portfolio_metrics(official: dict[str, Any], latest_run: Path, portfolio: str) -> dict[str, Any]:
    portfolios = official.get("portfolios")
    if isinstance(portfolios, dict) and isinstance(portfolios.get(portfolio), dict):
        src = portfolios[portfolio]
    else:
        src = {}
    broker_path = latest_run / "broker_replay" / portfolio / "metrics.json"
    broker = read_json(broker_path)
    metric_mode = str(broker.get("metric_mode") or src.get("official_metric_mode") or src.get("metric_mode") or "")
    official_source = str(src.get("official_source") or f"broker_replay/{portfolio}/metrics.json")
    position_count = src.get("position_count") or src.get("latest_position_count") or broker.get("position_count")
    return {
        "cagr": safe_float(broker.get("cagr"), safe_float(src.get("cagr"))),
        "max_dd": safe_float(broker.get("max_dd"), safe_float(src.get("max_dd"))),
        "sharpe": safe_float(broker.get("sharpe"), safe_float(src.get("sharpe"))),
        "position_count": safe_float(position_count),
        "start_date": broker.get("start_date") or src.get("start_date"),
        "end_date": broker.get("end_date") or src.get("end_date"),
        "years": broker_period_years(broker or src),
        "metric_mode": metric_mode,
        "official_source": official_source,
        "broker_metrics_path": str(broker_path),
        "status": broker.get("status") or src.get("status"),
        "valid_for_production": bool(broker.get("valid_for_production")) and bool(src.get("valid_for_production", True)),
        "trade_count": safe_float(broker.get("trade_count") or src.get("broker_trade_count")),
        "total_fees_usd": safe_float(broker.get("total_fees_usd") or src.get("total_fees_usd")),
    }


def universe_source_summary(scored: pd.DataFrame) -> dict[str, Any]:
    if scored.empty:
        return {"scored_row_count": 0, "r1000_base_count": 0, "source_counts": {}, "healthy_source_present": False}
    source_col = "universe_source" if "universe_source" in scored.columns else "source_universe" if "source_universe" in scored.columns else ""
    counts: dict[str, int] = {}
    healthy = False
    r1000_base_count = 0
    if source_col:
        values = scored[source_col].astype(str).fillna("")
        counts = {str(k): int(v) for k, v in values.value_counts(dropna=False).to_dict().items()}
        r1000_mask = values.str.contains("current_constituents_proxy|historical_membership|static_seed", case=False, regex=True)
        r1000_base_count = int(r1000_mask.sum())
        healthy = bool(r1000_base_count > 0)
    return {
        "scored_row_count": int(len(scored)),
        "r1000_base_count": int(r1000_base_count),
        "source_counts": counts,
        "healthy_source_present": healthy,
    }


def build_lock(latest_run: Path, run_id: str, branch: str, head_sha: str, row_floor: int) -> tuple[dict[str, Any], list[str]]:
    official = read_json(latest_run / "account_evaluation" / "official_metrics.json")
    scored = read_csv(latest_run / "scored_latest.csv")
    guard_path = latest_run / "portfolio_system_guard" / "error_check.json"
    guard = read_json(guard_path)
    universe = universe_source_summary(scored)
    metric_mode = str(official.get("official_metric_mode") or official.get("metric_mode") or "")
    main = extract_portfolio_metrics(official, latest_run, "main")
    concentrated = extract_portfolio_metrics(official, latest_run, "concentrated")
    blockers: list[str] = []
    if metric_mode != "broker_ledger_next_close":
        blockers.append("official_metric_mode_not_broker_ledger_next_close")
    if int(universe["scored_row_count"]) < int(row_floor):
        blockers.append("scored_row_count_below_floor")
    if int(universe["r1000_base_count"]) < int(row_floor):
        blockers.append("r1000_base_count_below_floor")
    if not bool(universe.get("healthy_source_present")):
        blockers.append("healthy_universe_source_missing")
    if not guard_path.exists():
        blockers.append("portfolio_system_guard_missing")
    if not main.get("cagr") and main.get("cagr") != 0.0:
        blockers.append("main_official_metrics_missing")
    if not concentrated.get("cagr") and concentrated.get("cagr") != 0.0:
        blockers.append("concentrated_official_metrics_missing")
    for portfolio, metrics in (("main", main), ("concentrated", concentrated)):
        if metrics.get("metric_mode") != "broker_ledger_next_close":
            blockers.append(f"{portfolio}_broker_metric_mode_not_next_close")
        if not bool(metrics.get("valid_for_production")):
            blockers.append(f"{portfolio}_broker_not_valid_for_production")
        if "broker_replay" not in str(metrics.get("official_source") or ""):
            blockers.append(f"{portfolio}_official_source_not_broker_replay")
        years = safe_float(metrics.get("years"), 0.0) or 0.0
        if years < 6.8:
            blockers.append(f"{portfolio}_broker_period_below_6p8y")
    if guard and guard_hard_error_count(guard) > 0:
        blockers.append("portfolio_system_guard_hard_errors")

    payload = {
        "schema_version": "healthy-baseline-lock-v1",
        "run_id": str(run_id),
        "head_sha": str(head_sha or ""),
        "branch": str(branch or ""),
        "latest_run": str(latest_run),
        "universe_healthy": not any(
            x in blockers for x in ["scored_row_count_below_floor", "r1000_base_count_below_floor", "healthy_universe_source_missing"]
        ),
        "scored_row_count": universe["scored_row_count"],
        "source_counts": universe["source_counts"],
        "r1000_base_count": universe["r1000_base_count"],
        "official_metric_mode": metric_mode,
        "official_source": "broker_replay",
        "portfolio_system_guard_path": str(guard_path),
        "broker_period_years": min(safe_float(main.get("years"), 0.0) or 0.0, safe_float(concentrated.get("years"), 0.0) or 0.0),
        "valid_for_production": len(blockers) == 0,
        "promotion_eligible": len(blockers) == 0,
        "promotion_blockers": blockers,
        "main": main,
        "concentrated": concentrated,
        "research_only": False,
        "production_activation_allowed": False,
    }
    return payload, blockers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/baseline_lock")
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "local"))
    parser.add_argument("--branch", default=os.environ.get("GITHUB_REF_NAME", ""))
    parser.add_argument("--head-sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--row-floor", type=int, default=400)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload, blockers = build_lock(
        latest_run=latest_run,
        run_id=str(args.run_id),
        branch=str(args.branch),
        head_sha=str(args.head_sha),
        row_floor=int(args.row_floor),
    )
    status_path = output_dir / "latest_status.json"
    if blockers:
        blocked_path = output_dir / f"blocked_baseline_{args.run_id}.json"
        blocked_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        status = {**payload, "status": "blocked", "baseline_lock_path": str(blocked_path)}
        status_path.write_text(json.dumps(status, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        print(f"[baseline-lock] blocked: {','.join(blockers)}")
        return 0
    lock_path = output_dir / f"healthy_baseline_{args.run_id}.json"
    lock_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    status = {**payload, "status": "healthy", "baseline_lock_path": str(lock_path)}
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"[baseline-lock] wrote {lock_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

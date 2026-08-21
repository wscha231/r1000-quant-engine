#!/usr/bin/env python3
"""Combine daily data, virtual-account, and rebalance-cadence evidence.

The report is deliberately read-only. It does not rebuild a model, mutate a
target book, promote a challenger, or place an order. Its purpose is to stop a
green collector workflow from being mistaken for a current, validated model.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_METRIC_MODE = "broker_ledger_next_close"
PORTFOLIOS = ("main", "concentrated")
REQUIRED_DAILY_DATASETS = (
    "price_cache_dir",
    "macro_daily_snapshot",
    "companyfacts_zip",
    "sec_13f_holdings",
    "form4_transactions",
    "forward_earnings_estimate_snapshots",
    "forward_earnings_revision_signals",
)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def iso_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:10])
    except ValueError:
        return None


def canonical_check(
    name: str,
    metrics: dict[str, Any],
    mission: dict[str, Any],
) -> dict[str, Any]:
    cagr = safe_float(metrics.get("cagr"))
    max_dd = safe_float(metrics.get("max_dd"))
    cagr_target = safe_float(mission.get("cagr"))
    max_dd_target = safe_float(mission.get("max_dd"))
    evidence_valid = bool(metrics.get("valid_for_production"))
    cagr_pass = bool(
        evidence_valid
        and cagr is not None
        and cagr_target is not None
        and cagr >= cagr_target
    )
    max_dd_pass = bool(
        evidence_valid
        and max_dd is not None
        and max_dd_target is not None
        and max_dd >= max_dd_target
    )
    return {
        "portfolio": name,
        "evidence_valid": evidence_valid,
        "end_date": metrics.get("end_date"),
        "cagr": cagr,
        "cagr_target": cagr_target,
        "cagr_gap_pp": (
            None
            if cagr is None or cagr_target is None
            else round(max(0.0, cagr_target - cagr) * 100.0, 4)
        ),
        "cagr_pass": cagr_pass,
        "max_dd": max_dd,
        "max_dd_target": max_dd_target,
        "max_dd_gap_pp": (
            None
            if max_dd is None or max_dd_target is None
            else round(max(0.0, max_dd_target - max_dd) * 100.0, 4)
        ),
        "max_dd_pass": max_dd_pass,
        "tier2_strengthened_pass": bool(metrics.get("strengthened_pass")),
        "tier2_failing": metrics.get("tier2_failing") or [],
        "canonical_mission_pass": bool(cagr_pass and max_dd_pass),
    }


def build_review(
    readiness: dict[str, Any],
    weekly: dict[str, Any],
    account: dict[str, Any],
    cadence: dict[str, Any],
    catalog: dict[str, Any] | None = None,
    *,
    sources: dict[str, str],
) -> dict[str, Any]:
    blockers: list[str] = []
    review_items: list[str] = []

    if not readiness:
        blockers.append("missing_current_data_readiness")
    elif not bool(readiness.get("ready_for_policy_replay")):
        blockers.append("current_data_not_ready_for_policy_replay")

    catalog = catalog or {}
    catalog_rows = {
        str(row.get("name")): row
        for row in catalog.get("datasets") or []
        if isinstance(row, dict) and row.get("name")
    }
    feed_status: dict[str, dict[str, Any]] = {}
    if not catalog:
        blockers.append("missing_current_data_catalog")
    for name in REQUIRED_DAILY_DATASETS:
        row = catalog_rows.get(name) or {}
        status = str(row.get("status") or "missing")
        freshness = str(row.get("freshness") or "unknown")
        feed_status[name] = {
            "status": status,
            "freshness": freshness,
            "modified_utc": row.get("modified_utc"),
            "age_days": row.get("age_days"),
            "owner_workflow": row.get("owner_workflow"),
        }
        if status != "ok":
            blockers.append(f"daily_dataset_{name}_{status}")
        elif freshness != "fresh":
            blockers.append(f"daily_dataset_{name}_{freshness.lower()}")

    weekly_status = str(weekly.get("status") or "missing")
    if weekly_status != "ok":
        blockers.append(f"weekly_mark_to_market_{weekly_status}")

    observable_date = iso_date(readiness.get("latest_observable_close_date"))
    weekly_date = iso_date(weekly.get("primary_weekly_eval_date"))
    weekly_close_lag_days = None
    if observable_date and weekly_date:
        weekly_close_lag_days = (observable_date - weekly_date).days
        if weekly_close_lag_days > 7:
            blockers.append("weekly_mark_to_market_not_aligned_with_latest_observable_close")

    metric_mode = account.get("official_metric_mode")
    if metric_mode != EXPECTED_METRIC_MODE:
        blockers.append("official_metric_mode_is_not_broker_ledger_next_close")

    target_contract = account.get("target_contract") or {}
    mission = target_contract.get("canonical_mission") or {}
    account_portfolios = account.get("portfolios") or {}
    canonical_checks: dict[str, dict[str, Any]] = {}
    for name in PORTFOLIOS:
        metrics = account_portfolios.get(name) or {}
        if not metrics:
            blockers.append(f"missing_{name}_virtual_account_metrics")
        check = canonical_check(name, metrics, mission.get(name) or {})
        canonical_checks[name] = check
        if metrics and not check["evidence_valid"]:
            blockers.append(f"{name}_official_evidence_invalid")
        if metrics and not check["canonical_mission_pass"]:
            review_items.append(f"{name}_canonical_mission_not_met")
        if metrics and not check["tier2_strengthened_pass"]:
            review_items.append(f"{name}_strengthened_gates_not_met")

    target_contract_status = str(account.get("target_contract_status") or "missing")
    if target_contract_status != "canonical_mission_confirmed":
        review_items.append(f"target_contract_{target_contract_status}")

    cadence_contract = cadence.get("abcd_cadence_challenger") or {}
    if not bool(cadence_contract.get("contract_ready")):
        blockers.append("cadence_challenger_contract_not_ready")
    if bool(cadence_contract.get("historical_backtest_executed")):
        blockers.append("unexpected_cadence_fullrun_in_report_only_review")
    if bool(cadence.get("production_mutated")):
        blockers.append("unexpected_production_mutation")

    blockers = list(dict.fromkeys(blockers))
    review_items = list(dict.fromkeys(review_items))
    if blockers:
        status = "BLOCKED_EVIDENCE"
    elif review_items:
        status = "RESEARCH_REVIEW_REQUIRED"
    else:
        status = "READY_RESEARCH_REVIEW"

    return {
        "schema_version": "run287-operating-model-review-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": status,
        "research_only": True,
        "virtual_trading_only": True,
        "live_trading_enabled": False,
        "production_mutated": False,
        "fullrun_executed": False,
        "automatic_promotion_allowed": False,
        "blockers": blockers,
        "review_items": review_items,
        "data_freshness": {
            "readiness_status": readiness.get("status") or "missing",
            "ready_for_policy_replay": bool(readiness.get("ready_for_policy_replay")),
            "ready_for_fullrun": bool(readiness.get("ready_for_fullrun")),
            "latest_observable_close_date": readiness.get("latest_observable_close_date"),
            "latest_target_date": readiness.get("latest_target_date"),
            "weekly_status": weekly_status,
            "primary_weekly_eval_date": weekly.get("primary_weekly_eval_date"),
            "weekly_close_lag_days": weekly_close_lag_days,
            "policy_replay_blockers": readiness.get("policy_replay_blockers") or [],
            "required_daily_datasets": feed_status,
            "macro": readiness.get("macro") or {},
        },
        "official_evaluation": {
            "metric_mode": metric_mode,
            "target_contract_status": target_contract_status,
            "active_target_type": account.get("target_type"),
            "canonical_mission_checks": canonical_checks,
            "strengthened_pass": bool(account.get("strengthened_pass")),
            "production_promotion_allowed": False,
        },
        "rebalance_plan": {
            "daily": cadence.get("daily_decision_scope") or [],
            "weekly": cadence.get("weekly_decision_scope") or [],
            "monthly_or_event": cadence.get("monthly_or_event_decision_scope") or [],
            "full_universe_rerank_frequency": cadence.get("full_universe_rerank_frequency"),
            "mid_month_reentry_allowed": cadence.get("mid_month_reentry_allowed"),
            "accepted_champion": cadence_contract.get("accepted_champion"),
            "recommended_research_candidate": cadence_contract.get("recommended_operating_candidate"),
            "historical_backtest_executed": False,
            "automatic_promotion_allowed": False,
        },
        "sources": sources,
    }


def pct(value: Any) -> str:
    number = safe_float(value)
    return "?" if number is None else f"{number * 100.0:.2f}%"


def render_markdown(payload: dict[str, Any]) -> str:
    freshness = payload.get("data_freshness") or {}
    official = payload.get("official_evaluation") or {}
    cadence = payload.get("rebalance_plan") or {}
    lines = [
        "# Daily Operating Model Review",
        "",
        f"- status: `{payload.get('status')}`",
        "- scope: `research-only virtual trading`",
        f"- latest observable close: `{freshness.get('latest_observable_close_date')}`",
        f"- weekly mark-to-market date: `{freshness.get('primary_weekly_eval_date')}`",
        f"- official metric mode: `{official.get('metric_mode')}`",
        f"- target contract status: `{official.get('target_contract_status')}`",
        "- fullrun executed: `false`",
        "- production/live trading enabled: `false`",
        "- automatic promotion allowed: `false`",
        "",
        "## Canonical Mission Check",
        "",
        "| Portfolio | Evidence valid | CAGR | Target | MaxDD | Limit | Tier-2 | Mission pass |",
        "| --- | :---: | ---: | ---: | ---: | ---: | :---: | :---: |",
    ]
    for name, check in (official.get("canonical_mission_checks") or {}).items():
        lines.append(
            f"| {name} | {str(bool(check.get('evidence_valid'))).lower()} | "
            f"{pct(check.get('cagr'))} | {pct(check.get('cagr_target'))} | "
            f"{pct(check.get('max_dd'))} | {pct(check.get('max_dd_target'))} | "
            f"{str(bool(check.get('tier2_strengthened_pass'))).lower()} | "
            f"{str(bool(check.get('canonical_mission_pass'))).lower()} |"
        )
    lines.extend(
        [
            "",
            "## Rebalance Plan",
            "",
            "- Daily: crisis/re-entry and current-holding warning/no-add checks.",
            "- Weekly: holdings/watchlist momentum, technical, valuation and vacancy review.",
            f"- Monthly or event-triggered: full-universe rerank and target rebuild (`{cadence.get('full_universe_rerank_frequency')}`).",
            f"- Accepted champion: `{cadence.get('accepted_champion')}`; research candidate: `{cadence.get('recommended_research_candidate')}`.",
            "- The cadence challenger still requires a separately approved historical fullrun before any promotion.",
            "",
            "## Blockers",
            "",
        ]
    )
    lines.extend([f"- `{item}`" for item in payload.get("blockers") or []] or ["- none"])
    lines.extend(["", "## Review Items", ""])
    lines.extend([f"- `{item}`" for item in payload.get("review_items") or []] or ["- none"])
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-readiness", type=Path, required=True)
    parser.add_argument("--data-catalog", type=Path, required=True)
    parser.add_argument("--weekly-evaluation", type=Path, required=True)
    parser.add_argument("--account-evaluation", type=Path, required=True)
    parser.add_argument("--decision-cadence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/operating_model_review"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_paths = {
        "data_readiness": str(args.data_readiness),
        "data_catalog": str(args.data_catalog),
        "weekly_evaluation": str(args.weekly_evaluation),
        "account_evaluation": str(args.account_evaluation),
        "decision_cadence": str(args.decision_cadence),
    }
    payload = build_review(
        read_json(args.data_readiness),
        read_json(args.weekly_evaluation),
        read_json(args.account_evaluation),
        read_json(args.decision_cadence),
        read_json(args.data_catalog),
        sources=source_paths,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "report.md").write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "blockers": payload["blockers"], "review_items": payload["review_items"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

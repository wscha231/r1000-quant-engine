#!/usr/bin/env python3
"""Aggregate system acceptance evidence for the CAGR/MDD operating loop.

This is a governance sidecar. It does not trade, mutate target books, or promote
variants. It reads the other sidecars and tells operators whether the system is
ready, not-ready, or merely review-ready against the current objective:

- official broker-ledger next-close metrics
- 8-year window readiness
- locked IS/OOS holdout evidence
- data readiness
- target-book / broker cash-contract evidence
- operational paper-order bridge evidence
- attribution package evidence for year leaks, MDD trough holdings, and per-name contribution
- era-aware challenger evidence
- daily crisis/paper-action guardrails
- self-correction queue
- ADR review automation
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

try:
    from r1000_config import PORTFOLIO_GOAL_TARGETS
except Exception:  # pragma: no cover - smoke fallback
    PORTFOLIO_GOAL_TARGETS = {
        "main": {"cagr": 0.30, "max_dd": -0.25},
        "concentrated": {"cagr": 0.50, "max_dd": -0.28},
    }


PORTFOLIOS = ("main", "concentrated")
OFFICIAL_METRIC_MODE = "broker_ledger_next_close"
MIN_YEARS = 8.0
CRISIS_ALLOWED_ACTION_TYPES = {"raise_cash", "trim_position", "block_new_buys", "reentry_watch", "no_op"}
CONCENTRATED_RECOVERY_EXPERIMENTS = [
    {
        "plan_id": "ab_conc_continuation_winner_relaxation",
        "experiment_id": "conc_continuation_winner_relaxation",
        "reason": "Concentrated CAGR or Tier-2 gate is short; relax continuation-winner filters only as a review A/B.",
        "env": {"PHASE_CONCENTRATED_CONTINUATION_RELAX_ENABLED": "1"},
    },
    {
        "plan_id": "ab_conc_bull_floor_stock_min",
        "experiment_id": "conc_bull_floor_stock_min",
        "reason": "Concentrated CAGR or Tier-2 gate is short; measure bull/strong_bull stock-floor exposure as an isolated A/B.",
        "env": {"PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED": "1"},
    },
    {
        "plan_id": "ab_conc_reentry_quality",
        "experiment_id": "conc_reentry_quality",
        "reason": "Concentrated CAGR or Tier-2 gate is short; measure reentry quality after cash/defense states as an isolated A/B.",
        "env": {"PHASE_CONCENTRATED_REENTRY_QUALITY_ENABLED": "1"},
    },
    {
        "plan_id": "ab_conc_theme_leadership_boost",
        "experiment_id": "conc_theme_leadership_boost",
        "reason": "Concentrated CAGR or Tier-2 gate is short; test theme-leadership confirmation boost as an isolated A/B.",
        "env": {"PHASE_THEME_LEADERSHIP_BOOST_ENABLED": "1"},
    },
    {
        "plan_id": "ab_conc_concentration_cap_relaxation",
        "experiment_id": "conc_concentration_cap_relaxation",
        "reason": "Concentrated CAGR or Tier-2 gate is short; test confirmed-winner cap relaxation while preserving broker-ledger gates.",
        "env": {"PHASE_CONCENTRATED_CAP_RELAX_ENABLED": "1"},
    },
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def stable_payload_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def csv_info(path: Path, required_columns: set[str] | None = None) -> dict[str, Any]:
    required_columns = required_columns or set()
    if not path.exists():
        return {
            "exists": False,
            "row_count": 0,
            "columns": [],
            "missing_columns": sorted(required_columns),
        }
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = list(reader.fieldnames or [])
            row_count = sum(1 for _ in reader)
    except Exception as exc:
        return {
            "exists": True,
            "read_error": str(exc),
            "row_count": 0,
            "columns": [],
            "missing_columns": sorted(required_columns),
        }
    return {
        "exists": True,
        "row_count": int(row_count),
        "columns": columns,
        "missing_columns": sorted(required_columns.difference(columns)),
    }


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def target_for(portfolio: str) -> dict[str, float]:
    target = PORTFOLIO_GOAL_TARGETS.get(portfolio, {})
    return {
        "cagr": float(target.get("cagr", 0.30 if portfolio == "main" else 0.50)),
        "max_dd": float(target.get("max_dd", -0.25 if portfolio == "main" else -0.28)),
    }


def requirement(
    requirement_id: str,
    *,
    status: str,
    summary: str,
    hard_blocker: bool,
    evidence: dict[str, Any] | None = None,
    next_action: str = "",
) -> dict[str, Any]:
    return {
        "requirement_id": requirement_id,
        "status": status,
        "hard_blocker": bool(hard_blocker),
        "summary": summary,
        "evidence": evidence or {},
        "next_action": next_action,
    }


def account_evidence(latest_run: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    official = read_json(latest_run / "account_evaluation" / "official_metrics.json")
    portfolios = official.get("portfolios") if isinstance(official.get("portfolios"), dict) else {}
    rows: dict[str, Any] = {}
    for portfolio in PORTFOLIOS:
        row = portfolios.get(portfolio) if isinstance(portfolios.get(portfolio), dict) else {}
        broker = read_json(latest_run / "broker_replay" / portfolio / "metrics.json")
        target = target_for(portfolio)
        cagr = safe_float(row.get("cagr"), safe_float(broker.get("cagr")))
        max_dd = safe_float(row.get("max_dd"), safe_float(broker.get("max_dd")))
        years = safe_float(row.get("years"), safe_float(broker.get("years")))
        mode = str(row.get("official_metric_mode") or broker.get("metric_mode") or "")
        rows[portfolio] = {
            "status": row.get("status") or broker.get("status") or "missing",
            "metric_mode": mode,
            "valid_for_production": bool(row.get("valid_for_production", broker.get("valid_for_production"))),
            "target_pass": bool(row.get("target_pass", False)),
            "strengthened_pass": bool(row.get("strengthened_pass", False)),
            "tier2_failing": row.get("tier2_failing") or [],
            "cagr": cagr,
            "cagr_target": target["cagr"],
            "max_dd": max_dd,
            "max_dd_target": target["max_dd"],
            "years": years,
            "start_date": row.get("start_date") or broker.get("start_date"),
            "end_date": row.get("end_date") or broker.get("end_date"),
            "integer_shares": broker.get("integer_shares"),
            "fill_mode": broker.get("fill_mode"),
            "cost_bps_per_side": broker.get("cost_bps_per_side"),
            "max_fill_lag_days": broker.get("max_fill_lag_days"),
            "target_book": broker.get("target_book"),
        }
    return official, rows


def evaluate_official_metrics(latest_run: Path) -> dict[str, Any]:
    official, rows = account_evidence(latest_run)
    missing = [p for p, row in rows.items() if row["status"] != "completed" or row["metric_mode"] != OFFICIAL_METRIC_MODE]
    if missing:
        return requirement(
            "official_broker_ledger_metrics",
            status="fail",
            hard_blocker=True,
            summary=f"missing official broker-ledger metrics for {','.join(missing)}",
            evidence={"portfolios": rows, "official_metric_mode": official.get("official_metric_mode")},
            next_action="Run broker-ledger replay for both portfolios with next_close fills.",
        )
    return requirement(
        "official_broker_ledger_metrics",
        status="pass",
        hard_blocker=False,
        summary="official broker-ledger next-close metrics exist for both portfolios",
        evidence={"portfolios": rows, "official_metric_mode": official.get("official_metric_mode")},
    )


def evaluate_goal_contract(latest_run: Path) -> dict[str, Any]:
    official, rows = account_evidence(latest_run)
    failing = []
    for portfolio, row in rows.items():
        if not row.get("target_pass"):
            failing.append(f"{portfolio}:tier1_target")
        if not row.get("strengthened_pass"):
            failing.append(f"{portfolio}:tier2_strengthened")
    status = "pass" if not failing else "fail"
    return requirement(
        "goal_contract_main30_conc50_mdd",
        status=status,
        hard_blocker=bool(failing),
        summary="all portfolios pass Tier-1 and Tier-2 gates" if not failing else "goal contract is not yet met",
        evidence={
            "production_target_pass": official.get("production_target_pass"),
            "strengthened_pass": official.get("strengthened_pass"),
            "failing": failing,
            "portfolios": rows,
        },
        next_action="Use IS attribution and challenger queues; do not promote until Tier-2 gates pass." if failing else "",
    )


def evaluate_eight_year(latest_run: Path) -> dict[str, Any]:
    readiness = read_json(latest_run / "eight_year_backtest_readiness" / "summary.json")
    _, rows = account_evidence(latest_run)
    broker_years = {p: rows[p].get("years") for p in PORTFOLIOS}
    years_ok = all((safe_float(value, 0.0) or 0.0) >= MIN_YEARS for value in broker_years.values())
    readiness_ok = bool(readiness.get("official_window_ready"))
    if readiness and readiness_ok and years_ok:
        status = "pass"
        blocker = False
        summary = "official 8-year broker-ledger window is ready"
    else:
        status = "fail"
        blocker = True
        summary = "official 8-year broker-ledger window is not proven"
    return requirement(
        "eight_year_broker_ledger_window",
        status=status,
        hard_blocker=blocker,
        summary=summary,
        evidence={
            "readiness_status": readiness.get("status"),
            "official_window_ready": readiness.get("official_window_ready"),
            "broker_years": broker_years,
            "blockers": readiness.get("blockers") or [],
        },
        next_action="Extend price/universe/cache and target books back to at least mid-2018, then rerun full rebuild." if blocker else "",
    )


def evaluate_oos_lock(latest_run: Path) -> dict[str, Any]:
    lock = read_json(latest_run / "oos_lock" / "summary.json")
    if not lock:
        return requirement(
            "oos_holdout_lock",
            status="fail",
            hard_blocker=True,
            summary="OOS holdout lock audit is missing",
            evidence={},
            next_action="Run tools/run_oos_lock_audit.py after broker replay and before system acceptance.",
        )
    failures = lock.get("failures") if isinstance(lock.get("failures"), dict) else {}
    portfolios = lock.get("portfolios") if isinstance(lock.get("portfolios"), dict) else {}
    passed = lock.get("status") == "pass" and lock.get("lock_pass") is True and not failures
    return requirement(
        "oos_holdout_lock",
        status="pass" if passed else "fail",
        hard_blocker=not passed,
        summary="locked IS/OOS holdout audit passed" if passed else "locked IS/OOS holdout audit failed",
        evidence={
            "status": lock.get("status"),
            "lock_pass": lock.get("lock_pass"),
            "oos_start": (lock.get("config") or {}).get("oos_start") if isinstance(lock.get("config"), dict) else None,
            "failures": failures,
            "portfolios": {
                portfolio: {
                    "status": row.get("status"),
                    "cagr_is": row.get("cagr_is"),
                    "cagr_oos": row.get("cagr_oos"),
                    "oos_is_cagr_ratio": row.get("oos_is_cagr_ratio"),
                    "oos_degradation_pp": row.get("oos_degradation_pp"),
                    "max_allowed_degradation_pp": row.get("max_allowed_degradation_pp"),
                    "max_oos_is_cagr_ratio": row.get("max_oos_is_cagr_ratio"),
                    "oos_trading_days": row.get("oos_trading_days"),
                }
                for portfolio, row in portfolios.items()
                if isinstance(row, dict)
            },
        },
        next_action="Treat the candidate as non-promotable; inspect outputs/oos_lock/report.md before another SHIP retry." if not passed else "",
    )


def evaluate_data_readiness(latest_run: Path) -> dict[str, Any]:
    data = read_json(latest_run / "data_readiness" / "summary.json")
    blockers = data.get("blockers") or data.get("policy_replay_blockers") or []
    ready = bool(data.get("ready_for_policy_replay", not blockers)) and not blockers
    if not data:
        return requirement(
            "data_readiness_price_macro_sec_etf",
            status="fail",
            hard_blocker=True,
            summary="data readiness summary is missing",
            evidence={},
            next_action="Run tools/audit_data_readiness.py before account evaluation.",
        )
    return requirement(
        "data_readiness_price_macro_sec_etf",
        status="pass" if ready else "fail",
        hard_blocker=not ready,
        summary="data readiness has no hard blockers" if ready else "data readiness has hard blockers",
        evidence={
            "status": data.get("status"),
            "ready_for_policy_replay": data.get("ready_for_policy_replay"),
            "blockers": blockers,
            "warnings": data.get("warnings") or [],
            "effective_latest_target_date": data.get("effective_latest_target_date"),
        },
        next_action="Resolve data readiness blockers before treating any backtest as official." if not ready else "",
    )


def evaluate_broker_realism(latest_run: Path) -> dict[str, Any]:
    _, rows = account_evidence(latest_run)
    failures = []
    for portfolio, row in rows.items():
        if row.get("fill_mode") != "next_close":
            failures.append(f"{portfolio}:fill_mode")
        if row.get("integer_shares") is not True:
            failures.append(f"{portfolio}:integer_shares")
        if safe_float(row.get("cost_bps_per_side"), -1.0) != 25.0:
            failures.append(f"{portfolio}:cost_bps")
        if safe_float(row.get("max_fill_lag_days"), 999.0) != 7.0:
            failures.append(f"{portfolio}:max_fill_lag_days")
    return requirement(
        "broker_realism_next_close_integer_cash_costs",
        status="pass" if not failures else "fail",
        hard_blocker=bool(failures),
        summary="broker replay uses next-close, integer shares, costs, and 7-day fill lag" if not failures else "broker replay realism contract is incomplete",
        evidence={"failures": failures, "portfolios": rows},
        next_action="Rerun broker replay with next_close, integer shares, 25bps costs, and max_fill_lag_days=7." if failures else "",
    )


def evaluate_cash_contract(latest_run: Path) -> dict[str, Any]:
    cash = read_json(latest_run / "cash_contract" / "cash_contract_summary.json")
    failures: list[str] = []
    portfolios: dict[str, Any] = {}
    if not cash:
        failures.append("cash_contract_summary_missing")
    if cash and cash.get("cash_contract_pass") is not True:
        failures.append("overall_cash_contract_not_pass")
    for portfolio in PORTFOLIOS:
        row = ((cash.get("portfolios") or {}).get(portfolio) or {}) if cash else {}
        target = row.get("target") if isinstance(row.get("target"), dict) else {}
        broker = row.get("broker") if isinstance(row.get("broker"), dict) else {}
        drift = row.get("drift") if isinstance(row.get("drift"), dict) else {}
        portfolios[portfolio] = {
            "status": row.get("status") or "missing",
            "cash_contract_pass": row.get("cash_contract_pass"),
            "target_cash_contract_pass": target.get("target_cash_contract_pass"),
            "missing_explicit_cash_date_count": target.get("missing_explicit_cash_date_count"),
            "invalid_total_weight_date_count": target.get("invalid_total_weight_date_count"),
            "negative_cash_date_count": target.get("negative_cash_date_count"),
            "broker_status": broker.get("status"),
            "cash_drift_pass": drift.get("cash_drift_pass"),
            "rebalance_day_cash_drift_pass": drift.get("rebalance_day_cash_drift_pass"),
            "month_mean_cash_drift_pass": drift.get("month_mean_cash_drift_pass"),
            "rebalance_day_mean_cash_drift_pp": drift.get("rebalance_day_mean_cash_drift_pp"),
            "month_mean_cash_drift_pp": drift.get("month_mean_cash_drift_pp"),
        }
        if row.get("cash_contract_pass") is not True:
            failures.append(f"{portfolio}:cash_contract_not_pass")
        if target.get("target_cash_contract_pass") is not True:
            failures.append(f"{portfolio}:target_cash_contract_not_pass")
        if broker.get("status") != "completed":
            failures.append(f"{portfolio}:broker_cash_ledger_not_completed")
        if drift.get("cash_drift_pass") is not True:
            failures.append(f"{portfolio}:cash_drift_not_pass")
        if drift.get("rebalance_day_cash_drift_pass") is not True:
            failures.append(f"{portfolio}:rebalance_day_cash_drift_not_pass")
        if drift.get("month_mean_cash_drift_pass") is not True:
            failures.append(f"{portfolio}:month_mean_cash_drift_not_pass")
    return requirement(
        "target_book_broker_cash_contract",
        status="pass" if not failures else "fail",
        hard_blocker=bool(failures),
        summary="target books have explicit CASH rows and broker cash drift is within limits" if not failures else "target-book or broker cash contract is incomplete",
        evidence={
            "failures": failures,
            "cash_contract_pass": cash.get("cash_contract_pass"),
            "mean_drift_limit_pp": cash.get("mean_drift_limit_pp"),
            "max_drift_limit_pp": cash.get("max_drift_limit_pp"),
            "portfolios": portfolios,
        },
        next_action="Run validate_target_book_cash_contract.py and fix explicit CASH rows or cash-ledger drift before treating results as official." if failures else "",
    )


def evaluate_operational_order_bridge(latest_run: Path) -> dict[str, Any]:
    previews: dict[str, Any] = {}
    failures: list[str] = []
    for portfolio in PORTFOLIOS:
        preview_dir = latest_run / "account_ledger_preview" / portfolio
        metrics = read_json(preview_dir / "preview_metrics.json")
        manifest = read_json(preview_dir / "order_batch_manifest.json")
        orders_path = preview_dir / "orders_preview.csv"
        positions_path = preview_dir / "positions_current.csv"
        projected_path = preview_dir / "projected_positions_after_orders.csv"
        target_path = str(metrics.get("target") or "")
        account_state_path = str(metrics.get("account_state") or "")
        row = {
            "status": metrics.get("status") or "missing",
            "preview_semantics": metrics.get("preview_semantics"),
            "account_source_kind": metrics.get("account_source_kind"),
            "target": target_path,
            "account_state": account_state_path,
            "cost_bps_per_side": metrics.get("cost_bps_per_side"),
            "integer_shares": metrics.get("integer_shares"),
            "blocked_order_count": metrics.get("blocked_order_count"),
            "ready_order_count": metrics.get("ready_order_count"),
            "order_count": metrics.get("order_count"),
            "orders_preview_exists": orders_path.exists(),
            "positions_current_exists": positions_path.exists(),
            "projected_positions_exists": projected_path.exists(),
            "order_batch_manifest_exists": bool(manifest),
        }
        previews[portfolio] = row
        normalized_target = target_path.replace("\\", "/")
        normalized_account = account_state_path.replace("\\", "/")
        if metrics.get("status") != "completed":
            failures.append(f"{portfolio}:preview_missing_or_not_completed")
        if metrics.get("preview_semantics") != "order_preview_not_operating_snapshot":
            failures.append(f"{portfolio}:preview_semantics_invalid")
        if "operating_" not in normalized_target or "target_book.csv" not in normalized_target:
            failures.append(f"{portfolio}:not_operating_target_book")
        if "broker_replay" not in normalized_account:
            failures.append(f"{portfolio}:not_broker_replay_account_state")
        if safe_float(metrics.get("cost_bps_per_side"), -1.0) != 25.0:
            failures.append(f"{portfolio}:cost_bps_not_25")
        if metrics.get("integer_shares") is not True:
            failures.append(f"{portfolio}:integer_shares_not_true")
        if int(safe_float(metrics.get("blocked_order_count"), 0.0) or 0) > 0:
            failures.append(f"{portfolio}:blocked_orders_present")
        for exists_key in ("orders_preview_exists", "positions_current_exists", "projected_positions_exists", "order_batch_manifest_exists"):
            if not row[exists_key]:
                failures.append(f"{portfolio}:{exists_key}_missing")

    safety = read_json(latest_run / "live_trading_safety" / "safety_audit_summary.json")
    risk = read_json(latest_run / "live_trading_risk_controls" / "risk_controls_summary.json")
    if safety.get("status") != "pass" or int(safe_float(safety.get("error_count"), 999.0)) != 0:
        failures.append("live_trading_safety:not_pass")
    if risk.get("status") != "pass" or int(safe_float(risk.get("error_count"), 999.0)) != 0:
        failures.append("live_trading_risk_controls:not_pass")
    if risk and risk.get("strict_live") is not False:
        failures.append("live_trading_risk_controls:strict_live_unexpected")
    return requirement(
        "operational_order_preview_safety_bridge",
        status="pass" if not failures else "fail",
        hard_blocker=bool(failures),
        summary="operating target books are bridged to safe paper order manifests" if not failures else "operating target book order bridge is missing or unsafe",
        evidence={
            "failures": failures,
            "previews": previews,
            "safety_status": safety.get("status"),
            "safety_error_count": safety.get("error_count"),
            "risk_controls_status": risk.get("status"),
            "risk_controls_error_count": risk.get("error_count"),
            "risk_controls_account_mode": risk.get("account_mode"),
            "risk_controls_manifest_order_count": risk.get("manifest_order_count"),
            "live_order_submission_allowed": False,
        },
        next_action="" if not failures else "Run account order previews, live trading safety audit, and risk controls before treating results as operationally ready.",
    )


def evaluate_attribution_package(latest_run: Path) -> dict[str, Any]:
    is_summary = read_json(latest_run / "is_attribution" / "summary.json")
    era_summary = read_json(latest_run / "era_leadership" / "summary.json")
    era_leaders = csv_info(latest_run / "era_leadership" / "era_leaders.csv", {"era", "ticker", "contribution"})
    mdd_summary = read_json(latest_run / "mdd_cash_overlay_research" / "summary.json")
    failures: list[str] = []
    if not is_summary:
        failures.append("is_attribution_summary_missing")
    if era_summary.get("status") != "completed":
        failures.append("era_leadership_summary_not_completed")
    if not era_leaders["exists"] or era_leaders["row_count"] <= 0 or era_leaders["missing_columns"]:
        failures.append("era_leaders_per_name_contribution_missing")
    if not mdd_summary:
        failures.append("mdd_cash_overlay_summary_missing")

    portfolios: dict[str, Any] = {}
    for portfolio in PORTFOLIOS:
        is_row = is_summary.get(portfolio) if isinstance(is_summary.get(portfolio), dict) else {}
        yearly = csv_info(
            latest_run / "is_attribution" / f"{portfolio}_yearly.csv",
            {"year", "year_return", "year_cagr", "max_dd_in_year", "leak_tag"},
        )
        trade_findings = read_json(latest_run / "trade_attribution" / portfolio / "findings.json")
        mdd_window = trade_findings.get("mdd_window") if isinstance(trade_findings.get("mdd_window"), dict) else {}
        mdd_contributors = mdd_window.get("top_position_pnl_contributors")
        trade_csv = csv_info(
            latest_run / "trade_attribution" / portfolio / "mdd_position_pnl_by_ticker.csv",
            {"ticker"},
        )
        mdd_metrics = read_json(latest_run / "mdd_cash_overlay_research" / portfolio / "metrics.json")
        mdd_base = mdd_metrics.get("base_metrics") if isinstance(mdd_metrics.get("base_metrics"), dict) else {}
        trough_csv = csv_info(
            latest_run / "mdd_cash_overlay_research" / portfolio / "mdd_holdings_contributors.csv",
            {"ticker", "trough_weight", "peak_to_trough_value_delta_usd"},
        )
        portfolios[portfolio] = {
            "is_status": is_row.get("status") or "completed" if is_row else "missing",
            "is_cagr": is_row.get("is_cagr"),
            "oos_is_ratio": is_row.get("oos_is_ratio"),
            "leak_year_tag_count": len(is_row.get("leak_year_tags") or {}) if isinstance(is_row, dict) else 0,
            "yearly_rows": yearly["row_count"],
            "trade_attribution_status": trade_findings.get("status") or "missing",
            "trade_mdd_peak_date": mdd_window.get("peak_date"),
            "trade_mdd_trough_date": mdd_window.get("trough_date"),
            "trade_mdd_contributor_count": len(mdd_contributors) if isinstance(mdd_contributors, list) else 0,
            "trade_mdd_position_rows": trade_csv["row_count"],
            "mdd_research_status": mdd_metrics.get("status") or "completed" if mdd_metrics else "missing",
            "mdd_peak_date": mdd_base.get("max_dd_peak_date"),
            "mdd_trough_date": mdd_base.get("max_dd_trough_date"),
            "mdd_trough_holding_rows": trough_csv["row_count"],
        }
        if not is_row or is_row.get("status") == "missing_equity_curve":
            failures.append(f"{portfolio}:is_attribution_missing")
        if is_row and safe_float(is_row.get("is_cagr")) is None:
            failures.append(f"{portfolio}:is_cagr_missing")
        if is_row and not is_row.get("leak_year_tags"):
            failures.append(f"{portfolio}:leak_year_tags_missing")
        if not yearly["exists"] or yearly["row_count"] <= 0 or yearly["missing_columns"]:
            failures.append(f"{portfolio}:yearly_attribution_csv_missing")
        if trade_findings.get("status") != "completed":
            failures.append(f"{portfolio}:trade_attribution_not_completed")
        if not (mdd_window.get("peak_date") and mdd_window.get("trough_date")):
            failures.append(f"{portfolio}:trade_mdd_window_missing")
        if not isinstance(mdd_contributors, list) or not mdd_contributors:
            failures.append(f"{portfolio}:trade_mdd_per_name_contributors_missing")
        if not trade_csv["exists"] or trade_csv["row_count"] <= 0 or trade_csv["missing_columns"]:
            failures.append(f"{portfolio}:trade_mdd_position_csv_missing")
        if not mdd_metrics:
            failures.append(f"{portfolio}:mdd_research_metrics_missing")
        if not (mdd_base.get("max_dd_peak_date") and mdd_base.get("max_dd_trough_date")):
            failures.append(f"{portfolio}:mdd_trough_window_missing")
        if not trough_csv["exists"] or trough_csv["row_count"] <= 0 or trough_csv["missing_columns"]:
            failures.append(f"{portfolio}:mdd_trough_holdings_missing")

    return requirement(
        "attribution_package_year_mdd_name",
        status="pass" if not failures else "fail",
        hard_blocker=bool(failures),
        summary="year leak, MDD trough holdings, and per-name contribution evidence are present" if not failures else "attribution evidence package is incomplete",
        evidence={
            "failures": failures,
            "is_attribution_exists": bool(is_summary),
            "era_leadership_status": era_summary.get("status"),
            "era_leader_rows": era_leaders["row_count"],
            "era_leader_missing_columns": era_leaders["missing_columns"],
            "mdd_cash_overlay_summary_exists": bool(mdd_summary),
            "portfolios": portfolios,
        },
        next_action="Run IS attribution, era leadership, trade attribution, and MDD cash overlay sidecars before treating any promoted result as official." if failures else "",
    )


def evaluate_era(latest_run: Path) -> dict[str, Any]:
    leadership = read_json(latest_run / "era_leadership" / "summary.json")
    challenger = read_json(latest_run / "era_aware_scoring_challenger" / "summary.json")
    ok = bool(leadership) and bool(challenger) and challenger.get("production_activation_allowed") is False
    if not ok:
        return requirement(
            "era_leadership_and_challenger",
            status="warn",
            hard_blocker=False,
            summary="era diagnostics or review challenger are missing from this run",
            evidence={"era_leadership_exists": bool(leadership), "era_aware_challenger_exists": bool(challenger)},
            next_action="Run era leadership and era-aware challenger sidecars before reviewing selection-regime changes.",
        )
    return requirement(
        "era_leadership_and_challenger",
        status="pass",
        hard_blocker=False,
        summary="era diagnostics and review-only challenger are present",
        evidence={
            "era_feature_count": leadership.get("feature_count"),
            "era_rows": leadership.get("row_count"),
            "challenger_status": challenger.get("status"),
            "challenger_rebalance_dates": challenger.get("rebalance_date_count"),
            "goal_verdicts": challenger.get("goal_verdicts") or {},
        },
    )


def evaluate_crisis(latest_run: Path) -> dict[str, Any]:
    monitor = read_json(latest_run / "daily_crisis_monitor" / "summary.json")
    bridge = read_json(latest_run / "crisis_paper_order_bridge" / "summary.json")
    monitor_candidates = monitor.get("paper_action_candidates") if isinstance(monitor.get("paper_action_candidates"), list) else []
    monitor_action_types = sorted(
        {
            str(item.get("action_type") or "")
            for item in monitor_candidates
            if isinstance(item, dict) and item.get("action_type")
        }
    )
    monitor_allowed_declared = monitor.get("allowed_action_types") if isinstance(monitor.get("allowed_action_types"), list) else []
    monitor_declared_unknown = sorted({str(item) for item in monitor_allowed_declared if str(item) not in CRISIS_ALLOWED_ACTION_TYPES})
    monitor_unknown_actions = sorted({item for item in monitor_action_types if item not in CRISIS_ALLOWED_ACTION_TYPES})
    bridge_action_types = sorted({str(item) for item in (bridge.get("paper_action_types") or []) if str(item)})
    bridge_unknown_actions = sorted({item for item in bridge_action_types if item not in CRISIS_ALLOWED_ACTION_TYPES})
    unsafe_portfolio_previews: list[str] = []
    for row in bridge.get("portfolios") or []:
        if not isinstance(row, dict):
            continue
        portfolio = str(row.get("portfolio") or "unknown")
        if (
            row.get("auto_trade_allowed") is not False
            or row.get("paper_only") is not True
            or row.get("approval_required") is not True
        ):
            unsafe_portfolio_previews.append(portfolio)

    monitor_has_unsafe_flags = bool(monitor) and (
        monitor.get("auto_trade_allowed") is True
        or monitor.get("paper_actions_only") is False
    )
    bridge_has_unsafe_flags = bool(bridge) and (
        bridge.get("auto_trade_allowed") is True
        or bridge.get("paper_only") is not True
        or bridge.get("approval_required") is not True
    )
    unsafe = bool(
        monitor_has_unsafe_flags
        or bridge_has_unsafe_flags
        or monitor_unknown_actions
        or monitor_declared_unknown
        or bridge_unknown_actions
        or unsafe_portfolio_previews
    )
    monitor_ok = bool(monitor) and monitor.get("auto_trade_allowed") is False and monitor.get("paper_actions_only") is True
    bridge_ok = (
        bool(bridge)
        and bridge.get("status") == "completed"
        and bridge.get("auto_trade_allowed") is False
        and bridge.get("paper_only") is True
        and bridge.get("approval_required") is True
    )
    if unsafe:
        status = "fail"
        hard_blocker = True
        summary = "crisis monitor or paper-order bridge contains unsafe action or execution flags"
        next_action = "Keep crisis actions limited to raise_cash, trim_position, block_new_buys, reentry_watch, and no_op; keep every output paper-only with user approval required."
    elif monitor_ok and bridge_ok:
        status = "pass"
        hard_blocker = False
        summary = "crisis monitor and paper-order bridge are wired with approval gates"
        next_action = ""
    elif monitor_ok:
        status = "warn"
        hard_blocker = False
        summary = "crisis monitor is wired, but paper-order bridge output is missing"
        next_action = "Run run_crisis_paper_order_bridge.py after daily crisis monitor."
    else:
        status = "warn"
        hard_blocker = False
        summary = "daily crisis monitor output is missing"
        next_action = "Run run_daily_crisis_monitor.py and keep auto_trade_allowed=false."
    return requirement(
        "daily_crisis_paper_action_wire",
        status=status,
        hard_blocker=hard_blocker,
        summary=summary,
        evidence={
            "monitor_state": monitor.get("state"),
            "monitor_raw_state": monitor.get("raw_state"),
            "auto_trade_allowed": monitor.get("auto_trade_allowed"),
            "paper_actions_only": monitor.get("paper_actions_only"),
            "monitor_action_types": monitor_action_types,
            "monitor_unknown_actions": monitor_unknown_actions,
            "monitor_declared_unknown_action_types": monitor_declared_unknown,
            "bridge_status": bridge.get("status"),
            "bridge_auto_trade_allowed": bridge.get("auto_trade_allowed"),
            "bridge_paper_only": bridge.get("paper_only"),
            "bridge_approval_required": bridge.get("approval_required"),
            "bridge_action_types": bridge_action_types,
            "bridge_unknown_actions": bridge_unknown_actions,
            "unsafe_portfolio_previews": unsafe_portfolio_previews,
        },
        next_action=next_action,
    )


def evaluate_self_correction(latest_run: Path) -> dict[str, Any]:
    router = read_json(latest_run / "self_correction_router" / "router_queue.json")
    if not router:
        return requirement(
            "self_correction_router_queue",
            status="warn",
            hard_blocker=False,
            summary="self-correction router output is missing from this run",
            evidence={},
            next_action="Run performance ledger and self-correction router after IS attribution.",
        )
    dispatch_payloads = read_json_list(latest_run / "self_correction_router" / "workflow_dispatch_payloads.json")
    dispatcher = read_json(latest_run / "review_dispatcher_self_correction" / "summary.json")
    review_tasks = router.get("queued_review_tasks") if isinstance(router.get("queued_review_tasks"), list) else []
    queued_experiments = router.get("queued_experiments") if isinstance(router.get("queued_experiments"), list) else []
    queued_experiment_ids = {
        str(item.get("experiment_id") or item.get("plan_id"))
        for item in queued_experiments
        if isinstance(item, dict) and (item.get("experiment_id") or item.get("plan_id"))
    }
    unsafe_queued_experiments = [
        str(item.get("experiment_id") or item.get("plan_id") or idx)
        for idx, item in enumerate(queued_experiments)
        if isinstance(item, dict)
        and (
            item.get("production_mutation_allowed") is not False
            or item.get("requires_user_approval") is not True
            or str(item.get("dispatch_mode") or "") != "workflow_dispatch_payload_only"
        )
    ]
    expected_payload_count = int(safe_float(router.get("dispatch_payload_count"), 0.0) or 0)
    dispatch_payload_count_mismatch = expected_payload_count != len(dispatch_payloads)
    unsafe_dispatch_payloads = []
    unknown_dispatch_payloads = []
    for idx, payload in enumerate(dispatch_payloads):
        payload_id = str(payload.get("plan_id") or payload.get("experiment_id") or payload.get("id") or idx)
        if queued_experiment_ids and payload_id not in queued_experiment_ids:
            unknown_dispatch_payloads.append(payload_id)
        inputs = payload.get("inputs")
        unsafe = (
            payload.get("production_mutation_allowed") is not False
            or payload.get("requires_user_approval") is not True
            or str(payload.get("workflow_id") or "") != "full_rebuild_manual.yml"
            or not isinstance(inputs, dict)
        )
        if isinstance(inputs, dict):
            unsafe = unsafe or str(inputs.get("backtest_years") or "") != "8"
            unsafe = unsafe or str(inputs.get("portfolio_policy") or "") != "alphaops_vnext_production"
        if unsafe:
            unsafe_dispatch_payloads.append(payload_id)
    unsafe_review_tasks = [
        str(task.get("task_id") or task.get("failure") or idx)
        for idx, task in enumerate(review_tasks)
        if isinstance(task, dict)
        and (
            task.get("production_mutation_allowed") is not False
            or task.get("requires_user_approval") is not True
            or str(task.get("dispatch_mode") or "") != "manual_review_no_workflow_dispatch"
        )
    ]
    dispatcher_plan_rows = dispatcher.get("plan_rows") if isinstance(dispatcher.get("plan_rows"), list) else []
    dispatcher_plan_ids = [
        str(row.get("id") or idx)
        for idx, row in enumerate(dispatcher_plan_rows)
        if isinstance(row, dict)
    ]
    dispatch_payload_ids = [
        str(payload.get("plan_id") or payload.get("experiment_id") or payload.get("id") or idx)
        for idx, payload in enumerate(dispatch_payloads)
    ]
    dispatcher_selected_count = int(safe_float(dispatcher.get("selected_count"), 0.0) or 0) if dispatcher else 0
    dispatcher_dispatched_count = int(safe_float(dispatcher.get("dispatched_count"), 0.0) or 0) if dispatcher else 0
    dispatcher_summary_missing = expected_payload_count > 0 and not dispatcher
    dispatcher_schema_invalid = bool(dispatcher) and dispatcher.get("schema_version") != "review-dispatcher-v1"
    dispatcher_status_invalid = bool(dispatcher) and dispatcher.get("status") not in {"dry_run_ready", "dry_run_blocked"}
    dispatcher_execution_requested = bool(dispatcher) and dispatcher.get("execute_requested") is not False
    dispatcher_dispatched = bool(dispatcher) and dispatcher_dispatched_count != 0
    dispatcher_selected_count_mismatch = bool(dispatcher) and dispatcher_selected_count != len(dispatch_payloads)
    dispatcher_plan_id_mismatch = bool(dispatcher) and sorted(dispatcher_plan_ids) != sorted(dispatch_payload_ids)
    safe = (
        router.get("production_mutation_allowed") is False
        and not unsafe_queued_experiments
        and not unsafe_review_tasks
        and not dispatch_payload_count_mismatch
        and not unsafe_dispatch_payloads
        and not unknown_dispatch_payloads
        and not dispatcher_summary_missing
        and not dispatcher_schema_invalid
        and not dispatcher_status_invalid
        and not dispatcher_execution_requested
        and not dispatcher_dispatched
        and not dispatcher_selected_count_mismatch
        and not dispatcher_plan_id_mismatch
    )
    oos_robustness = router.get("oos_robustness") if isinstance(router.get("oos_robustness"), dict) else {}
    return requirement(
        "self_correction_router_queue",
        status="pass" if safe else "fail",
        hard_blocker=not safe,
        summary=(
            "self-correction queue and dispatcher dry-run are review-only"
            if safe
            else "self-correction queue or dispatcher may mutate production, skip review, or lack persisted dry-run evidence"
        ),
        evidence={
            "latest_focus": router.get("latest_focus"),
            "repeat_confirmed": router.get("repeat_confirmed"),
            "queued_count": len(queued_experiments),
            "queued_review_task_count": len(review_tasks),
            "unsafe_queued_experiments": unsafe_queued_experiments,
            "dispatch_payload_file_count": len(dispatch_payloads),
            "dispatch_payload_count_mismatch": dispatch_payload_count_mismatch,
            "unsafe_dispatch_payloads": unsafe_dispatch_payloads,
            "unknown_dispatch_payloads": unknown_dispatch_payloads,
            "unsafe_review_tasks": unsafe_review_tasks,
            "oos_lock_status_seen": oos_robustness.get("status"),
            "oos_robustness_task_count": oos_robustness.get("queued_review_task_count"),
            "dispatch_payload_count": router.get("dispatch_payload_count"),
            "production_mutation_allowed": router.get("production_mutation_allowed"),
            "dispatcher_summary_exists": bool(dispatcher),
            "dispatcher_schema_version": dispatcher.get("schema_version"),
            "dispatcher_status": dispatcher.get("status"),
            "dispatcher_execute_requested": dispatcher.get("execute_requested"),
            "dispatcher_dispatched_count": dispatcher.get("dispatched_count"),
            "dispatcher_selected_count": dispatcher.get("selected_count"),
            "dispatcher_plan_ids": dispatcher_plan_ids,
            "dispatcher_summary_missing": dispatcher_summary_missing,
            "dispatcher_schema_invalid": dispatcher_schema_invalid,
            "dispatcher_status_invalid": dispatcher_status_invalid,
            "dispatcher_execution_requested": dispatcher_execution_requested,
            "dispatcher_dispatched": dispatcher_dispatched,
            "dispatcher_selected_count_mismatch": dispatcher_selected_count_mismatch,
            "dispatcher_plan_id_mismatch": dispatcher_plan_id_mismatch,
        },
        next_action=(
            ""
            if safe
            else "Set production_mutation_allowed=false, require user approval, run review_dispatcher_self_correction in dry-run mode, and keep manual review tasks out of workflow dispatch."
        ),
    )


def adr_manifest_state(latest_run: Path) -> dict[str, Any]:
    manifest_path = latest_run / "adr_candidates" / "adr_universe_update_manifest.json"
    manifest = read_json(manifest_path)
    if not manifest:
        return {
            "manifest_path": str(manifest_path),
            "manifest_exists": False,
            "proposed_add_count": None,
            "placeholder_proposed_count": None,
            "manual_review_required": None,
            "proposed_tickers": [],
        }
    additions = manifest.get("proposed_additions") if isinstance(manifest.get("proposed_additions"), list) else []
    placeholder_count = 0
    tickers: list[str] = []
    for record in additions:
        if not isinstance(record, dict):
            continue
        tickers.append(str(record.get("ticker") or "").upper())
        entry = record.get("proposed_entry") if isinstance(record.get("proposed_entry"), dict) else {}
        missing_required = any(not str(entry.get(field) or "").strip() for field in ("name", "country", "sector", "sub_sector", "listed_since"))
        if missing_required or str(entry.get("sector") or "").strip() == "ADR_REVIEW_REQUIRED":
            placeholder_count += 1
    return {
        "manifest_path": str(manifest_path),
        "manifest_exists": True,
        "proposed_add_count": int(manifest.get("proposed_add_count") or len(additions)),
        "placeholder_proposed_count": placeholder_count,
        "manual_review_required": manifest.get("manual_review_required"),
        "proposed_tickers": [ticker for ticker in tickers if ticker],
        "review_steps": manifest.get("review_steps") if isinstance(manifest.get("review_steps"), list) else [],
    }


def evaluate_adr_automation(latest_run: Path) -> dict[str, Any]:
    workflow = REPO / ".github" / "workflows" / "adr_candidate_monthly.yml"
    scanner = REPO / "tools" / "run_adr_candidate_scanner.py"
    updater = REPO / "tools" / "apply_adr_universe_update.py"
    run_manifest = latest_run / "adr_candidates" / "adr_universe_update_manifest.json"
    scanner_text = scanner.read_text(encoding="utf-8", errors="ignore") if scanner.exists() else ""
    updater_text = updater.read_text(encoding="utf-8", errors="ignore") if updater.exists() else ""
    workflow_text = workflow.read_text(encoding="utf-8", errors="ignore") if workflow.exists() else ""
    manifest_state = adr_manifest_state(latest_run)
    wired = (
        workflow.exists()
        and scanner.exists()
        and updater.exists()
        and "adr_universe_update_manifest.json" in scanner_text
        and "production_mutation_allowed" in scanner_text
        and "APPROVE_ADR_UNIVERSE_UPDATE" in updater_text
        and "placeholder_sector_not_reviewed" in updater_text
        and "schedule:" in workflow_text
    )
    proposed_add_count = safe_float(manifest_state.get("proposed_add_count"), 0.0)
    if not wired:
        status = "warn"
        summary = "ADR review automation is incomplete"
        next_action = "Wire ADR scanner, guarded updater, and monthly workflow."
    elif not manifest_state.get("manifest_exists"):
        status = "warn"
        summary = "ADR review automation is wired, but this run has no ADR candidate manifest"
        next_action = "Run the full rebuild ADR scanner sidecar or adr_candidate_monthly.yml so acceptance has current universe review evidence."
    elif proposed_add_count and proposed_add_count > 0:
        status = "warn"
        summary = "ADR candidate manifest has proposed additions requiring metadata review"
        next_action = "Review ADR candidate metadata, dry-run apply_adr_universe_update.py, and merge only fully reviewed entries."
    else:
        status = "pass"
        summary = "monthly ADR candidate review and guarded apply automation are present"
        next_action = ""
    return requirement(
        "adr_universe_review_automation",
        status=status,
        hard_blocker=False,
        summary=summary,
        evidence={
            "workflow_exists": workflow.exists(),
            "scanner_exists": scanner.exists(),
            "updater_exists": updater.exists(),
            "run_manifest_exists": run_manifest.exists(),
            "run_manifest_path": str(run_manifest),
            "proposed_add_count": manifest_state.get("proposed_add_count"),
            "placeholder_proposed_count": manifest_state.get("placeholder_proposed_count"),
            "manual_review_required": manifest_state.get("manual_review_required"),
            "proposed_tickers": manifest_state.get("proposed_tickers"),
            "scanner_target_mutation_allowed": False if "production_mutation_allowed" in scanner_text else None,
            "updater_requires_approval_token": "APPROVE_ADR_UNIVERSE_UPDATE" in updater_text,
            "updater_blocks_placeholders": "placeholder_sector_not_reviewed" in updater_text,
        },
        next_action=next_action,
    )


def evaluate_guard(latest_run: Path) -> dict[str, Any]:
    guard = read_json(latest_run / "portfolio_system_guard" / "error_check.json")
    if not guard:
        return requirement(
            "portfolio_system_guard",
            status="warn",
            hard_blocker=False,
            summary="portfolio system guard output is missing",
            evidence={},
            next_action="Run portfolio system guard before publishing artifacts.",
        )
    hard_errors = int(safe_float(guard.get("hard_error_count"), 0.0) or 0)
    return requirement(
        "portfolio_system_guard",
        status="pass" if hard_errors == 0 else "fail",
        hard_blocker=hard_errors > 0,
        summary="portfolio system guard has no hard errors" if hard_errors == 0 else "portfolio system guard found hard errors",
        evidence={"hard_error_count": hard_errors, "check_count": len(guard.get("checks") or [])},
        next_action="Resolve portfolio system guard hard errors." if hard_errors else "",
    )


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    checks = [
        evaluate_official_metrics(latest_run),
        evaluate_goal_contract(latest_run),
        evaluate_eight_year(latest_run),
        evaluate_oos_lock(latest_run),
        evaluate_data_readiness(latest_run),
        evaluate_broker_realism(latest_run),
        evaluate_cash_contract(latest_run),
        evaluate_attribution_package(latest_run),
        evaluate_operational_order_bridge(latest_run),
        evaluate_era(latest_run),
        evaluate_crisis(latest_run),
        evaluate_self_correction(latest_run),
        evaluate_adr_automation(latest_run),
        evaluate_guard(latest_run),
    ]
    hard_blockers = [row for row in checks if row["hard_blocker"] and row["status"] != "pass"]
    warnings = [row for row in checks if row["status"] == "warn"]
    if hard_blockers:
        status = "not_ready"
    elif warnings:
        status = "review_ready_with_warnings"
    else:
        status = "production_evidence_ready"
    manual_review_tasks = collect_manual_review_tasks(latest_run)
    return {
        "schema_version": "system-acceptance-audit-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "latest_run": str(latest_run),
        "status": status,
        "production_activation_allowed": False,
        "live_trading_allowed": False,
        "hard_blocker_count": len(hard_blockers),
        "warning_count": len(warnings),
        "requirements": checks,
        "next_actions": [row["next_action"] for row in checks if row.get("next_action")],
        "manual_review_tasks": manual_review_tasks,
        "manual_review_task_count": len(manual_review_tasks),
    }


def requirement_by_id(payload: dict[str, Any], requirement_id: str) -> dict[str, Any]:
    for row in payload.get("requirements") or []:
        if row.get("requirement_id") == requirement_id:
            return row
    return {}


def collect_manual_review_tasks(latest_run: Path) -> list[dict[str, Any]]:
    router = read_json(latest_run / "self_correction_router" / "router_queue.json")
    tasks = router.get("queued_review_tasks") if isinstance(router.get("queued_review_tasks"), list) else []
    out: list[dict[str, Any]] = []
    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue
        out.append(
            {
                "task_id": task.get("task_id") or f"review_task_{idx}",
                "source": task.get("source") or "self_correction_router",
                "portfolio": task.get("portfolio"),
                "failure": task.get("failure"),
                "description": task.get("description"),
                "next_action": task.get("next_action"),
                "review_artifacts": task.get("review_artifacts") or [],
                "dispatch_mode": task.get("dispatch_mode"),
                "requires_user_approval": task.get("requires_user_approval"),
                "production_mutation_allowed": task.get("production_mutation_allowed"),
                "metrics": task.get("metrics") if isinstance(task.get("metrics"), dict) else {},
            }
        )
    out.extend(collect_adr_review_tasks(latest_run))
    return out


def collect_adr_review_tasks(latest_run: Path) -> list[dict[str, Any]]:
    state = adr_manifest_state(latest_run)
    if not state.get("manifest_exists"):
        return [
            {
                "task_id": "adr_candidate_manifest_missing",
                "source": "adr_universe_review_automation",
                "portfolio": "",
                "failure": "adr_candidate_manifest_missing",
                "description": "ADR scanner output is missing from this run, so universe expansion review is not current.",
                "next_action": "Run the ADR scanner sidecar or monthly workflow and inspect outputs/adr_candidates before treating ADR automation as current.",
                "review_artifacts": ["adr_candidates/summary.json", "adr_candidates/adr_universe_update_manifest.json"],
                "dispatch_mode": "manual_review_no_workflow_dispatch",
                "requires_user_approval": True,
                "production_mutation_allowed": False,
                "metrics": {},
            }
        ]
    proposed = int(safe_float(state.get("proposed_add_count"), 0.0) or 0)
    if proposed <= 0:
        return []
    return [
        {
            "task_id": "adr_universe_metadata_review",
            "source": "adr_universe_review_automation",
            "portfolio": "",
            "failure": "adr_metadata_review_required",
            "description": "ADR scanner found candidate additions that require human metadata review before adr_universe.yaml changes.",
            "next_action": "Fill name, country, sector, sub_sector, listed_since, and themes; then dry-run apply_adr_universe_update.py before any PR.",
            "review_artifacts": [
                "adr_candidates/adr_candidate_review.csv",
                "adr_candidates/adr_candidate_review.md",
                "adr_candidates/adr_universe_update_manifest.json",
                "adr_candidates/adr_universe_additions.yaml",
            ],
            "dispatch_mode": "manual_review_no_workflow_dispatch",
            "requires_user_approval": True,
            "production_mutation_allowed": False,
            "metrics": {
                "proposed_add_count": proposed,
                "placeholder_proposed_count": state.get("placeholder_proposed_count"),
                "proposed_tickers": state.get("proposed_tickers"),
            },
        }
    ]


def concentrated_goal_needs_recovery(payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    goal = requirement_by_id(payload, "goal_contract_main30_conc50_mdd")
    evidence = goal.get("evidence") if isinstance(goal.get("evidence"), dict) else {}
    portfolios = evidence.get("portfolios") if isinstance(evidence.get("portfolios"), dict) else {}
    concentrated = portfolios.get("concentrated") if isinstance(portfolios.get("concentrated"), dict) else {}
    if not concentrated:
        return False, {}
    target_pass = bool(concentrated.get("target_pass"))
    strengthened_pass = bool(concentrated.get("strengthened_pass"))
    cagr = safe_float(concentrated.get("cagr"))
    cagr_target = safe_float(concentrated.get("cagr_target"), PORTFOLIO_GOAL_TARGETS["concentrated"]["cagr"])
    tier2_failing = concentrated.get("tier2_failing") if isinstance(concentrated.get("tier2_failing"), list) else []
    needs_recovery = (not target_pass) or (not strengthened_pass) or bool(tier2_failing)
    if cagr is not None and cagr_target is not None:
        needs_recovery = needs_recovery or cagr < cagr_target - 1e-12
    return needs_recovery, {
        "cagr": cagr,
        "cagr_target": cagr_target,
        "max_dd": safe_float(concentrated.get("max_dd")),
        "max_dd_target": safe_float(concentrated.get("max_dd_target"), PORTFOLIO_GOAL_TARGETS["concentrated"]["max_dd"]),
        "target_pass": target_pass,
        "strengthened_pass": strengthened_pass,
        "tier2_failing": tier2_failing,
    }


def full_rebuild_ab_inputs(plan_id: str, env_payload: dict[str, str]) -> dict[str, str]:
    return {
        "universe_mode": "global_alpha_universe",
        "backtest_years": "8",
        "skip_collector": "true",
        "fast_mode": "true",
        "sidecar_profile": "operating_minimal",
        "artifact_profile": "minimal",
        "gdrive_sync_mode": "minimal",
        "portfolio_policy": "alphaops_vnext_production",
        "cache_key_suffix": plan_id,
        "experiment_env_json": json.dumps(env_payload, sort_keys=True),
    }


def build_dispatch_payloads(payload: dict[str, Any], *, ref: str) -> list[dict[str, Any]]:
    dispatches: list[dict[str, Any]] = []
    eight_year = requirement_by_id(payload, "eight_year_broker_ledger_window")
    if eight_year.get("status") != "pass":
        dispatches.append(
            {
                "plan_id": "bootstrap_free_data_for_8y_window",
                "workflow_id": "free_data_lake_bootstrap.yml",
                "ref": ref,
                "requires_user_approval": True,
                "production_mutation_allowed": False,
                "reason": "8-year broker-ledger window is not ready; extend/restore price and free-data cache first.",
                "inputs": {
                    "latest_run": "cloud_results/full_rebuild/latest_global_alpha_universe",
                    "sec_companyfacts": "true",
                    "price_mode": "target_books",
                    "max_price_tickers": "0",
                    "run_proxy_replay": "true",
                    "sync_to_gdrive": "true",
                },
            }
        )
        dispatches.append(
            {
                "plan_id": "full_rebuild_8y_official_after_data_bootstrap",
                "workflow_id": "full_rebuild_manual.yml",
                "ref": ref,
                "requires_user_approval": True,
                "production_mutation_allowed": False,
                "depends_on_plan_ids": ["bootstrap_free_data_for_8y_window"],
                "reason": "After free-data bootstrap, run the official 8-year broker-ledger rebuild with the production policy.",
                "inputs": {
                    "universe_mode": "global_alpha_universe",
                    "backtest_years": "8",
                    "skip_collector": "false",
                    "fast_mode": "true",
                    "sidecar_profile": "operating_minimal",
                    "artifact_profile": "minimal",
                    "gdrive_sync_mode": "minimal",
                    "portfolio_policy": "alphaops_vnext_production",
                    "cache_key_suffix": "official-8y-window",
                    "experiment_env_json": "",
                },
            }
        )
    needs_concentrated_recovery, concentrated_evidence = concentrated_goal_needs_recovery(payload)
    if needs_concentrated_recovery:
        depends_on = ["full_rebuild_8y_official_after_data_bootstrap"] if eight_year.get("status") != "pass" else []
        for experiment in CONCENTRATED_RECOVERY_EXPERIMENTS:
            plan_id = str(experiment["plan_id"])
            experiment_id = str(experiment.get("experiment_id") or plan_id)
            inputs = full_rebuild_ab_inputs(plan_id, dict(experiment["env"]))
            payload_hash = stable_payload_hash(
                {
                    "plan_id": plan_id,
                    "experiment_id": experiment_id,
                    "workflow_id": "full_rebuild_manual.yml",
                    "ref": ref,
                    "inputs": inputs,
                    "source_requirement_id": "goal_contract_main30_conc50_mdd",
                    "source_portfolio": "concentrated",
                }
            )
            dispatches.append(
                {
                    "plan_id": plan_id,
                    "experiment_id": experiment_id,
                    "workflow_id": "full_rebuild_manual.yml",
                    "ref": ref,
                    "requires_user_approval": True,
                    "production_mutation_allowed": False,
                    "depends_on_plan_ids": depends_on,
                    "reason": experiment["reason"],
                    "source_requirement_id": "goal_contract_main30_conc50_mdd",
                    "source_portfolio": "concentrated",
                    "source_evidence": concentrated_evidence,
                    "payload_hash": payload_hash,
                    "post_run_review": {
                        "tool": "tools/run_ab_result_verifier.py",
                        "experiment_id": experiment_id,
                        "payload_hash": payload_hash,
                        "workflow_run_id": "<candidate_workflow_run_id>",
                        "dispatch_run_id": plan_id,
                        "baseline_run": "cloud_results/full_rebuild/latest_global_alpha_universe",
                        "candidate_run": "cloud_results/full_rebuild/<candidate_run_dir>",
                        "portfolio": "concentrated",
                        "verifier_output_dir": f"outputs/ab_result_verifier/{experiment_id}",
                        "queue_closure_output_dir": "outputs/self_correction_queue",
                        "verifier_args": [
                            "--baseline-run",
                            "cloud_results/full_rebuild/latest_global_alpha_universe",
                            "--candidate-run",
                            "cloud_results/full_rebuild/<candidate_run_dir>",
                            "--portfolio",
                            "concentrated",
                            "--experiment-id",
                            experiment_id,
                            "--payload-hash",
                            payload_hash,
                            "--workflow-run-id",
                            "<candidate_workflow_run_id>",
                            "--dispatch-run-id",
                            plan_id,
                            "--output-dir",
                            f"outputs/ab_result_verifier/{experiment_id}",
                        ],
                        "production_mutation_allowed": False,
                    },
                    "inputs": inputs,
                }
            )
    return dispatches


def render_dispatch_script(payloads: list[dict[str, Any]], repo: str) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "# Review-only generated commands. Inspect before running.",
        "",
    ]
    for payload in payloads:
        dependencies = [str(item) for item in payload.get("depends_on_plan_ids") or []]
        workflow_id = shlex.quote(str(payload.get("workflow_id") or ""))
        ref = shlex.quote(str(payload.get("ref") or "master"))
        parts = ["gh", "workflow", "run", workflow_id, "--repo", shlex.quote(repo), "--ref", ref]
        for key, value in sorted((payload.get("inputs") or {}).items()):
            parts.extend(["-f", shlex.quote(f"{key}={value}")])
        lines.append("# " + str(payload.get("plan_id") or payload.get("workflow_id")))
        lines.append("# " + str(payload.get("reason") or ""))
        command = " ".join(parts)
        if dependencies:
            lines.append("# blocked until completed_plan_id: " + ",".join(dependencies))
            lines.append("# " + command)
        else:
            lines.append(command)
        lines.append("")
    return "\n".join(lines)


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# System Acceptance Audit",
        "",
        f"- status: `{payload.get('status')}`",
        f"- production_activation_allowed: `{str(payload.get('production_activation_allowed')).lower()}`",
        f"- live_trading_allowed: `{str(payload.get('live_trading_allowed')).lower()}`",
        f"- hard_blocker_count: `{payload.get('hard_blocker_count')}`",
        f"- warning_count: `{payload.get('warning_count')}`",
        "",
        "| Requirement | Status | Hard Blocker | Summary |",
        "| --- | --- | :---: | --- |",
    ]
    for row in payload.get("requirements") or []:
        lines.append(
            f"| {row.get('requirement_id')} | {row.get('status')} | {str(row.get('hard_blocker')).lower()} | {row.get('summary')} |"
        )
    lines.extend(["", "## Next Actions", ""])
    actions = payload.get("next_actions") or []
    if actions:
        lines.extend(f"- {item}" for item in actions)
    else:
        lines.append("- none")
    lines.extend(["", "## Manual Review Tasks", ""])
    tasks = payload.get("manual_review_tasks") or []
    if tasks:
        lines.extend(
            [
                "- These tasks are review-only and must not dispatch workflows or mutate production.",
                "",
                "| Task | Source | Portfolio | Failure | Dispatch Mode | Next Action |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for item in tasks:
            lines.append(
                "| {task} | {source} | {portfolio} | {failure} | {mode} | {next_action} |".format(
                    task=item.get("task_id"),
                    source=item.get("source"),
                    portfolio=item.get("portfolio") or "",
                    failure=item.get("failure") or "",
                    mode=item.get("dispatch_mode") or "",
                    next_action=item.get("next_action") or "",
                )
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Review Dispatch Plan", ""])
    dispatches = payload.get("workflow_dispatch_payloads") or []
    if dispatches:
        lines.extend(
            [
                "- `workflow_dispatch_payloads.json` and `workflow_dispatch_commands.sh` are review-only.",
                "- They require explicit user approval before use.",
                "",
                "| Plan | Workflow | Dependencies | Reason |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in dispatches:
            deps = ",".join(item.get("depends_on_plan_ids") or [])
            lines.append(f"| {item.get('plan_id')} | {item.get('workflow_id')} | {deps} | {item.get('reason')} |")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload = build_payload(args)
    ref = getattr(args, "ref", "master")
    repo = getattr(args, "repo", "wscha231/r1000-quant-engine")
    dispatch_payloads = build_dispatch_payloads(payload, ref=ref)
    payload["workflow_dispatch_payloads"] = dispatch_payloads
    payload["workflow_dispatch_payload_count"] = len(dispatch_payloads)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", payload)
    write_json(output_dir / "workflow_dispatch_payloads.json", dispatch_payloads)
    write_json(output_dir / "manual_review_tasks.json", payload.get("manual_review_tasks") or [])
    (output_dir / "workflow_dispatch_commands.sh").write_text(
        render_dispatch_script(dispatch_payloads, repo) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "hard_blockers": payload["hard_blocker_count"]}, indent=2))
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/system_acceptance_audit")
    parser.add_argument("--ref", default="master")
    parser.add_argument("--repo", default="wscha231/r1000-quant-engine")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    run(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build the minimal current-holdings user report.

This report is intentionally not a recommendation book.  It only exposes the
current simulated broker-ledger holdings, cash, official broker-ledger metrics,
and period returns needed for daily operator review.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import load_price_series  # noqa: E402


HORIZONS: list[tuple[str, pd.DateOffset | None, bool]] = [
    ("1M", pd.DateOffset(months=1), False),
    ("3M", pd.DateOffset(months=3), False),
    ("6M", pd.DateOffset(months=6), False),
    ("YTD", None, True),
    ("1Y", pd.DateOffset(years=1), False),
    ("2Y", pd.DateOffset(years=2), False),
    ("FULL", None, False),
]
PORTFOLIOS = ("main", "concentrated")
BENCHMARKS = ("SPY", "QQQ")
REQUIRED_USER_FILES = [
    "README_FIRST.md",
    "01_current_holdings.csv",
    "02_cash_summary.json",
    "03_period_returns.csv",
    "04_official_metrics.json",
    "05_action_summary.md",
    "06_benchmark_comparison.csv",
    "07_research_sidecar_context.json",
    "08_broker_rule_backtest.json",
]


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


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def clean_ticker(value: Any) -> str:
    text = str(value or "").upper().strip()
    return "" if text in {"", "NAN", "NONE"} else text


def max_drawdown(values: pd.Series) -> float:
    d = pd.to_numeric(values, errors="coerce").dropna()
    if d.empty:
        return 0.0
    peak = d.cummax()
    dd = d / peak.replace(0.0, np.nan) - 1.0
    return float(dd.min()) if not dd.empty else 0.0


def score_window(frame: pd.DataFrame, label: str, offset: pd.DateOffset | None, ytd: bool) -> dict[str, Any]:
    if frame.empty or "date" not in frame.columns or "equity_usd" not in frame.columns:
        return {"horizon": label, "status": "missing"}
    d = frame.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["equity_usd"] = pd.to_numeric(d["equity_usd"], errors="coerce")
    d = d.dropna(subset=["date", "equity_usd"]).sort_values("date")
    if len(d) < 2:
        return {"horizon": label, "status": "missing"}
    end = pd.Timestamp(d["date"].iloc[-1])
    if ytd:
        window = d[d["date"] >= pd.Timestamp(year=end.year, month=1, day=1)].copy()
    elif offset is not None:
        window = d[d["date"] >= end - offset].copy()
    else:
        window = d.copy()
    if len(window) < 2:
        window = d.copy()
    start = pd.Timestamp(window["date"].iloc[0])
    end = pd.Timestamp(window["date"].iloc[-1])
    start_value = float(window["equity_usd"].iloc[0])
    end_value = float(window["equity_usd"].iloc[-1])
    years = max((end - start).days / 365.25, 1 / 252)
    returns = window["equity_usd"].pct_change().dropna()
    vol = float(returns.std(ddof=0) * math.sqrt(252.0)) if not returns.empty else 0.0
    sharpe = float((returns.mean() * 252.0) / (vol + 1e-12)) if not returns.empty else 0.0
    return {
        "horizon": label,
        "status": "completed",
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "period_return": end_value / max(start_value, 1e-12) - 1.0,
        "cagr": (end_value / max(start_value, 1e-12)) ** (1.0 / years) - 1.0,
        "max_dd": max_drawdown(window["equity_usd"]),
        "sharpe": sharpe,
        "realized_volatility": vol,
        "start_equity_usd": start_value,
        "end_equity_usd": end_value,
        "avg_cash_weight": float(pd.to_numeric(window.get("cash_weight", pd.Series(dtype=float)), errors="coerce").mean())
        if "cash_weight" in window.columns
        else np.nan,
        "end_cash_weight": safe_float(window["cash_weight"].iloc[-1], np.nan) if "cash_weight" in window.columns else np.nan,
    }


def portfolio_period_returns(latest_run: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for portfolio in PORTFOLIOS:
        equity = read_csv(latest_run / "broker_replay" / portfolio / "equity_curve.csv")
        for label, offset, ytd in HORIZONS:
            row = score_window(equity, label, offset, ytd)
            row["series"] = portfolio
            row["series_type"] = "portfolio"
            rows.append(row)
    return pd.DataFrame(rows)


def benchmark_period_returns(price_cache: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for ticker in BENCHMARKS:
        px = load_price_series(price_cache, ticker) if price_cache.exists() else pd.DataFrame()
        if px.empty:
            for label, _, _ in HORIZONS:
                rows.append({"series": ticker, "series_type": "benchmark", "horizon": label, "status": "missing"})
            continue
        d = px.reset_index()
        date_col = "date" if "date" in d.columns else d.columns[0]
        value_col = "close" if "close" in d.columns else d.columns[-1]
        equity = d[[date_col, value_col]].rename(columns={date_col: "date", value_col: "equity_usd"})
        for label, offset, ytd in HORIZONS:
            row = score_window(equity, label, offset, ytd)
            row["series"] = ticker
            row["series_type"] = "benchmark"
            rows.append(row)
    return pd.DataFrame(rows)


def normalize_current_holdings(latest_run: Path) -> pd.DataFrame:
    candidates = [
        latest_run / "operating_snapshot" / "current_operating_holdings_latest.csv",
        latest_run / "user_portfolio_reports" / "main_current_operating_holdings_latest.csv",
    ]
    frame = next((read_csv(path) for path in candidates if path.exists()), pd.DataFrame())
    if frame.empty:
        return frame
    out = frame.copy()
    if "ticker" in out.columns:
        out["ticker"] = out["ticker"].map(clean_ticker)
    wanted = [
        "as_of_date",
        "snapshot_semantics",
        "portfolio_kind",
        "row_type",
        "ticker",
        "current_shares",
        "current_price",
        "current_value_usd",
        "current_weight",
        "unrealized_pnl_usd",
        "realized_pnl_usd",
        "first_entry_date",
        "latest_entry_date",
        "holding_days",
        "avg_entry_price",
        "entry_reasons",
        "entry_sleeves",
        "daily_review_action",
        "daily_review_reason",
        "risk_state",
        "account_source",
        "approval_status",
    ]
    for col in wanted:
        if col not in out.columns:
            out[col] = ""
    return out[wanted].copy()


def load_official_metrics(latest_run: Path) -> dict[str, Any]:
    metrics = read_json(latest_run / "account_evaluation" / "official_metrics.json")
    if not metrics:
        metrics = {
            "status": "missing",
            "official_metric_mode": "",
            "valid_for_production": False,
            "note": "outputs/account_evaluation/official_metrics.json not found",
        }
    return metrics


def production_valid(metrics: dict[str, Any]) -> bool:
    if metrics.get("valid_for_production") is False:
        return False
    for key in PORTFOLIOS:
        item = metrics.get(key)
        if isinstance(item, dict) and item.get("valid_for_production") is False:
            return False
    return True


def official_metric_mode(metrics: dict[str, Any]) -> str:
    return str(metrics.get("official_metric_mode") or metrics.get("metric_mode") or "")


def optional_float(value: Any) -> float | None:
    out = safe_float(value, np.nan)
    return float(out) if math.isfinite(out) else None


def metric_payload(metrics: dict[str, Any], *, source: str = "", default_mode: str = "") -> dict[str, Any]:
    mode = str(metrics.get("official_metric_mode") or metrics.get("metric_mode") or default_mode or "")
    return {
        "status": metrics.get("status", "missing") if metrics else "missing",
        "metric_mode": mode,
        "source": source,
        "valid_for_production": bool(metrics.get("valid_for_production", False)) if metrics else False,
        "start_date": metrics.get("start_date", "") if metrics else "",
        "end_date": metrics.get("end_date", "") if metrics else "",
        "cagr": optional_float(metrics.get("cagr")) if metrics else None,
        "max_dd": optional_float(metrics.get("max_dd")) if metrics else None,
        "sharpe": optional_float(metrics.get("sharpe")) if metrics else None,
        "avg_cash_weight": optional_float(metrics.get("avg_cash_weight")) if metrics else None,
        "ending_capital_usd": optional_float(metrics.get("ending_capital_usd")) if metrics else None,
        "trade_count": int(safe_float(metrics.get("broker_trade_count", metrics.get("trade_count")), 0)) if metrics else 0,
        "total_fees_usd": optional_float(metrics.get("total_fees_usd")) if metrics else None,
        "fill_mode": metrics.get("fill_mode", "") if metrics else "",
        "integer_shares": metrics.get("integer_shares", None) if metrics else None,
        "cost_bps_per_side": optional_float(metrics.get("cost_bps_per_side")) if metrics else None,
    }


def official_portfolio_metric(latest_run: Path, metrics: dict[str, Any], portfolio: str) -> dict[str, Any]:
    portfolios = metrics.get("portfolios") if isinstance(metrics.get("portfolios"), dict) else {}
    item = portfolios.get(portfolio) if isinstance(portfolios, dict) else {}
    if not isinstance(item, dict) or not item:
        item = metrics.get(portfolio) if isinstance(metrics.get(portfolio), dict) else {}
    if isinstance(item, dict) and item:
        broker = read_json(latest_run / "broker_replay" / portfolio / "metrics.json")
        merged = {**broker, **item} if broker else dict(item)
        source = str(item.get("official_source") or "account_evaluation/official_metrics.json")
        return metric_payload(merged, source=source, default_mode=official_metric_mode(metrics))
    broker = read_json(latest_run / "broker_replay" / portfolio / "metrics.json")
    return metric_payload(broker, source=f"broker_replay/{portfolio}/metrics.json", default_mode="broker_ledger_next_close")


def event_backtest_row(summary: dict[str, Any], portfolio: str) -> dict[str, Any]:
    rows = summary.get("portfolios") if isinstance(summary.get("portfolios"), list) else []
    for row in rows:
        if isinstance(row, dict) and str(row.get("portfolio") or "").lower() == portfolio:
            return row
    return {}


def build_broker_rule_backtest(latest_run: Path, metrics: dict[str, Any]) -> dict[str, Any]:
    event_summary = read_json(latest_run / "operating_event_backtest" / "operating_event_backtest_summary.json")
    payload: dict[str, Any] = {
        "schema_version": "user-current-broker-rule-backtest-v1",
        "official_metric_mode": official_metric_mode(metrics) or "missing",
        "display_rule": {
            "current_holdings_backtest": "official broker-ledger replay only",
            "official_rule": "next-close fills, integer shares, explicit cash ledger, trading costs included",
            "daily_monitoring_rule": "daily close risk signals with next-close risk fills are shown as a separate monitoring overlay",
            "deprecated_weight_level_metrics_allowed": False,
        },
        "daily_monitoring_status": "validated" if event_summary.get("daily_risk_overlay_validated") else "missing_or_unvalidated",
        "daily_risk_overlay_validated": bool(event_summary.get("daily_risk_overlay_validated", False)),
        "daily_risk_action_evidence_count": int(safe_float(event_summary.get("daily_risk_action_evidence_count"), 0)),
        "full_nonmonthly_entry_replacement_validated": bool(event_summary.get("full_nonmonthly_entry_replacement_validated", False)),
        "operating_event_backtest_source": "operating_event_backtest/operating_event_backtest_summary.json"
        if event_summary
        else "",
        "portfolios": {},
    }
    for portfolio in PORTFOLIOS:
        event_row = event_backtest_row(event_summary, portfolio)
        event_broker = read_json(latest_run / "event_broker_replay" / portfolio / "metrics.json")
        position_risk = read_json(latest_run / "broker_position_risk_replay" / portfolio / "metrics.json")
        execution_policy = read_json(latest_run / "broker_execution_policy_replay" / portfolio / "metrics.json")
        payload["portfolios"][portfolio] = {
            "official_broker_ledger": official_portfolio_metric(latest_run, metrics, portfolio),
            "daily_monitoring_backtest": {
                "status": event_row.get("operating_event_backtest_status", "missing"),
                "daily_risk_engine_backtest_completed": bool(event_row.get("daily_risk_engine_backtest_completed", False)),
                "daily_risk_action_evidence": bool(event_row.get("daily_risk_action_evidence", False)),
                "risk_action_count": int(safe_float(event_row.get("risk_action_count"), 0)),
                "nonmonthly_risk_action_count": int(safe_float(event_row.get("nonmonthly_risk_action_count"), 0)),
                "target_book_submonthly_decisions_validated": bool(event_row.get("target_book_submonthly_decisions_validated", False)),
                "full_nonmonthly_entry_replacement_validated": bool(event_row.get("full_nonmonthly_entry_replacement_validated", False)),
                "position_risk_broker_ledger": metric_payload(
                    position_risk,
                    source=f"broker_position_risk_replay/{portfolio}/metrics.json",
                    default_mode="broker_ledger_position_risk_next_close",
                ),
                "event_target_book_broker_ledger": metric_payload(
                    event_broker,
                    source=f"event_broker_replay/{portfolio}/metrics.json",
                    default_mode="broker_ledger_next_close",
                ),
                "execution_policy_broker_ledger": metric_payload(
                    execution_policy,
                    source=f"broker_execution_policy_replay/{portfolio}/metrics.json",
                    default_mode="broker_ledger_execution_policy_next_close",
                ),
            },
        }
    return payload


def attach_broker_rule_columns(current: pd.DataFrame, broker_rule: dict[str, Any]) -> pd.DataFrame:
    if current.empty:
        return current
    out = current.copy()
    for col in [
        "backtest_metric_mode",
        "official_broker_cagr",
        "official_broker_max_dd",
        "official_broker_sharpe",
        "official_broker_avg_cash_weight",
        "daily_monitoring_backtest_status",
        "daily_monitoring_position_risk_cagr",
        "daily_monitoring_position_risk_max_dd",
        "daily_monitoring_risk_action_count",
    ]:
        out[col] = ""
    portfolios = broker_rule.get("portfolios") if isinstance(broker_rule.get("portfolios"), dict) else {}
    for idx, row in out.iterrows():
        portfolio = str(row.get("portfolio_kind") or "").lower().strip()
        item = portfolios.get(portfolio) if isinstance(portfolios, dict) else {}
        if not isinstance(item, dict):
            continue
        official = item.get("official_broker_ledger") if isinstance(item.get("official_broker_ledger"), dict) else {}
        daily = item.get("daily_monitoring_backtest") if isinstance(item.get("daily_monitoring_backtest"), dict) else {}
        position = daily.get("position_risk_broker_ledger") if isinstance(daily.get("position_risk_broker_ledger"), dict) else {}
        out.at[idx, "backtest_metric_mode"] = official.get("metric_mode", "")
        out.at[idx, "official_broker_cagr"] = official.get("cagr", "")
        out.at[idx, "official_broker_max_dd"] = official.get("max_dd", "")
        out.at[idx, "official_broker_sharpe"] = official.get("sharpe", "")
        out.at[idx, "official_broker_avg_cash_weight"] = official.get("avg_cash_weight", "")
        out.at[idx, "daily_monitoring_backtest_status"] = daily.get("status", "")
        out.at[idx, "daily_monitoring_position_risk_cagr"] = position.get("cagr", "")
        out.at[idx, "daily_monitoring_position_risk_max_dd"] = position.get("max_dd", "")
        out.at[idx, "daily_monitoring_risk_action_count"] = daily.get("nonmonthly_risk_action_count", "")
    return out


def alphaops_vnext_activation(latest_run: Path) -> dict[str, Any]:
    activation = read_json(latest_run / "alphaops_vnext" / "production_activation.json")
    if not activation:
        activation = read_json(latest_run / "promotion_review" / "alphaops_vnext_production_activation.json")
    return activation


def research_sidecar_context(latest_run: Path) -> dict[str, Any]:
    integrated_summary = read_json(latest_run / "integrated_theme_leader_crisis_replay" / "summary.json")
    replay_gate = read_json(latest_run / "integrated_theme_leader_crisis_replay" / "replay_gate_status.json")
    promotion_gate = read_json(latest_run / "integrated_theme_leader_crisis_replay" / "promotion_gate_status.json")
    mutation = read_json(latest_run / "integrated_theme_leader_crisis_replay" / "production_mutation_check.json")
    market_leader = read_json(latest_run / "market_leader_challenger" / "summary.json")
    patch_manifest = read_json(latest_run / "patch_application_manifest.json")
    promotion_check = read_json(latest_run / "promotion_review" / "integrated_target_promotion_check.json")
    production_audit = read_json(latest_run / "promotion_review" / "production_mutation_audit.json")
    decision_cadence = read_json(latest_run / "decision_cadence" / "decision_cadence_summary.json")
    alphaops_activation = alphaops_vnext_activation(latest_run)
    approved_policy_path = str(
        patch_manifest.get("approved_target_policy_path")
        or latest_run / "promotion_review" / "approved_target_policy.json"
    )
    production_policy = str(patch_manifest.get("portfolio_policy") or "production_baseline")
    if production_policy == "production_baseline" and alphaops_activation:
        production_policy = str(alphaops_activation.get("production_policy") or "alphaops_vnext_production")
    sidecar_applied = bool(
        patch_manifest.get("sidecar_applied_to_production")
        or str(production_audit.get("status") or "").lower() == "applied"
        or str(alphaops_activation.get("status") or "").lower() == "applied"
    )
    shadow_path = latest_run / "shadow_operating"
    integrated_projected_path = latest_run / "operator_review" / "projected_holdings_after_integrated_target.csv"
    market_leader_projected_path = latest_run / "operator_review" / "projected_holdings_after_market_leader_target.csv"
    projected_path = market_leader_projected_path if production_policy == "market_leader_shadow" and market_leader_projected_path.exists() else integrated_projected_path
    policy = read_json(repo_path(approved_policy_path))
    source_run_id = str(production_audit.get("source_run_id") or policy.get("source_run_id") or "")
    source_case_id = str(
        production_audit.get("source_case_id_main")
        or policy.get("source_case_id_main")
        or policy.get("source_case_id")
        or ""
    )
    return {
        "schema_version": "user-current-research-sidecar-context-v1",
        "production_applied": bool(sidecar_applied),
        "sidecar_only": not bool(sidecar_applied),
        "production_policy": production_policy,
        "sidecar_applied_to_production": bool(sidecar_applied),
        "current_holdings_source": alphaops_activation.get("current_holdings_source") or "production_operating_target_book",
        "source_target_run_id": source_run_id,
        "source_target_case_id": source_case_id,
        "approved_policy_path": approved_policy_path,
        "promotion_status": alphaops_activation.get("status") or promotion_check.get("status") or promotion_gate.get("status", "missing"),
        "shadow_available": bool(shadow_path.exists()),
        "projected_holdings_path": str(projected_path) if projected_path.exists() else "",
        "projected_integrated_holdings_path": str(integrated_projected_path) if integrated_projected_path.exists() else "",
        "projected_market_leader_holdings_path": str(market_leader_projected_path) if market_leader_projected_path.exists() else "",
        "decision_cadence_available": bool(decision_cadence),
        "decision_cadence_path": str(latest_run / "decision_cadence" / "decision_cadence_summary.json") if decision_cadence else "",
        "mid_month_reentry_allowed": bool(decision_cadence.get("mid_month_reentry_allowed", False)),
        "target_mutation_policy": decision_cadence.get("target_mutation_policy", ""),
        "message": (
            "AlphaOps vNext production replaced operating target books before broker replay."
            if str(alphaops_activation.get("status") or "").lower() == "applied"
            else "Market Leader / Multi-Lane / Crisis sidecars did not alter current holdings unless sidecar_applied_to_production=true."
        ),
        "research_outputs_not_applied": [
            "market_leader_challenger",
            "integrated_theme_leader_crisis_replay",
            "multi_lane_allocator",
            "crisis_overlay",
        ],
        "market_leader_challenger_status": market_leader.get("status", "missing"),
        "integrated_replay_status": integrated_summary.get("status", "missing"),
        "replay_gate_status": replay_gate.get("status", "missing"),
        "promotion_gate_status": promotion_gate.get("status", "missing"),
        "promotion_review_status": promotion_check.get("status", "missing"),
        "production_mutation_check_status": mutation.get("status", "missing"),
        "production_mutation_allowed": bool(production_audit.get("mode") == "approved_integrated" or alphaops_activation),
        "production_mutation_audit_status": alphaops_activation.get("status") or production_audit.get("status", "missing"),
        "production_activation_allowed": bool(promotion_gate.get("production_activation_allowed", False) or alphaops_activation),
        "alphaops_vnext_activation_status": alphaops_activation.get("status", "missing"),
        "alphaops_vnext_summary_path": str(latest_run / "alphaops_vnext" / "summary.json") if alphaops_activation else "",
        "patch_application_manifest_status": "present" if patch_manifest else "missing",
        "reason_not_applied_to_current_holdings": patch_manifest.get(
            "reason_not_applied_to_current_holdings",
            "alphaops_vnext_production_replaced_operating_books" if alphaops_activation else "research_only_sidecar_current_holdings_use_production_operating_book",
        ),
    }


def turnover_estimate(latest_run: Path) -> float:
    deltas = read_csv(latest_run / "operating_snapshot" / "proposed_target_deltas_latest.csv")
    if deltas.empty:
        return 0.0
    for col in ["delta_portfolio_weight", "delta_weight", "weight_delta"]:
        if col in deltas.columns:
            vals = pd.to_numeric(deltas[col], errors="coerce").abs().fillna(0.0)
            return float(vals.sum() / 2.0)
    for col in ["review_trade_value_delta_usd", "trade_value_delta_usd"]:
        if col in deltas.columns:
            vals = pd.to_numeric(deltas[col], errors="coerce").abs().fillna(0.0)
            denom = pd.to_numeric(deltas.get("current_value_usd", pd.Series(dtype=float)), errors="coerce").abs().sum()
            return float(vals.sum() / max(denom, 1e-12))
    return 0.0


def safety_hard_fail(latest_run: Path) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    guard = read_json(latest_run / "portfolio_system_guard" / "error_check.json")
    hard_errors = int(safe_float(guard.get("hard_error_count"), 0.0)) if guard else 0
    if hard_errors > 0:
        reasons.append(f"portfolio_system_guard hard_error_count={hard_errors}")
    safety = read_json(latest_run / "live_trading_safety" / "safety_audit_summary.json")
    status = str(safety.get("status") or safety.get("overall_status") or "").lower()
    if status in {"failed", "fail", "blocked"}:
        reasons.append(f"live_trading_safety status={status}")
    return bool(reasons), reasons


def build_cash_summary(latest_run: Path, current: pd.DataFrame) -> dict[str, Any]:
    snapshot = read_json(latest_run / "operating_snapshot" / "current_portfolio_snapshot_summary.json")
    out: dict[str, Any] = {
        "schema_version": "user-current-cash-summary-v1",
        "source": "outputs/operating_snapshot/current_portfolio_snapshot_summary.json",
        "combined_current_cash_weight": snapshot.get("combined_current_cash_weight"),
        "combined_target_cash_weight": snapshot.get("combined_target_cash_weight"),
        "combined_cash_gap_weight": snapshot.get("combined_cash_gap_weight"),
        "cash_policy_review_action": snapshot.get("cash_policy_review_action"),
        "cash_policy_flag": snapshot.get("cash_policy_flag"),
        "macro_recommended_cash_floor": snapshot.get("macro_recommended_cash_floor"),
        "macro_cash_raise_gate": snapshot.get("macro_cash_raise_gate"),
        "macro_cash_raise_confirmation_count": snapshot.get("macro_cash_raise_confirmation_count"),
        "by_portfolio": {},
    }
    projected_cash_usd = 0.0
    projected_equity_usd = 0.0
    target_cash_weighted = 0.0
    preview_found = False
    if not current.empty and {"portfolio_kind", "row_type", "current_weight"}.issubset(current.columns):
        cash = current[current["row_type"].astype(str).str.lower().eq("cash")].copy()
        for _, row in cash.iterrows():
            portfolio = str(row.get("portfolio_kind"))
            item = {
                "cash_weight": safe_float(row.get("current_weight")),
                "cash_value_usd": safe_float(row.get("current_value_usd")),
            }
            preview = read_json(latest_run / "account_ledger_preview" / portfolio / "preview_metrics.json")
            if preview:
                preview_found = True
                equity = safe_float(preview.get("equity_usd"))
                projected_equity = safe_float(preview.get("projected_equity_usd"), equity)
                item.update(
                    {
                        "target_cash_weight": safe_float(preview.get("target_cash_weight"), np.nan),
                        "projected_cash_weight": safe_float(preview.get("projected_cash_weight"), np.nan),
                        "projected_cash_usd": safe_float(preview.get("projected_cash_usd"), np.nan),
                        "order_count": int(safe_float(preview.get("order_count"), 0.0)),
                        "ready_order_count": int(safe_float(preview.get("ready_order_count"), 0.0)),
                        "blocked_order_count": int(safe_float(preview.get("blocked_order_count"), 0.0)),
                    }
                )
                projected_cash_usd += safe_float(preview.get("projected_cash_usd"))
                projected_equity_usd += projected_equity
                target_cash_weighted += safe_float(preview.get("target_cash_weight")) * equity
            out["by_portfolio"][portfolio] = item
    if preview_found:
        out["combined_projected_cash_weight_after_ready_orders"] = projected_cash_usd / max(projected_equity_usd, 1e-12)
        out["combined_preview_target_cash_weight"] = target_cash_weighted / max(projected_equity_usd, 1e-12)
        out["preview_order_semantics"] = "projected after order preview; no orders are placed by this report"
    return out


def build_action_summary(latest_run: Path, metrics: dict[str, Any], cash: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    mode = official_metric_mode(metrics)
    if mode and mode != "broker_ledger_next_close":
        return "DO_NOT_USE", [f"official_metric_mode is {mode}, not broker_ledger_next_close"]
    if not production_valid(metrics):
        return "DO_NOT_USE", ["official metrics are missing or valid_for_production=false"]
    hard_fail, safety_reasons = safety_hard_fail(latest_run)
    if hard_fail:
        return "DO_NOT_TRADE", safety_reasons
    if str(cash.get("cash_policy_flag") or "").strip():
        reasons.append(f"cash_policy_flag={cash.get('cash_policy_flag')}")
    turnover = turnover_estimate(latest_run)
    if turnover > 0.30:
        reasons.append(f"current-vs-target implied turnover {turnover:.2%} > 30%")
    if reasons:
        return "REVIEW_REQUIRED", reasons
    if turnover > 0.05:
        return "REBALANCE_CANDIDATE", [f"current-vs-target implied turnover {turnover:.2%}"]
    return "HOLD", ["no hard review flags"]


def pct_text(value: Any) -> str:
    number = safe_float(value, np.nan)
    return "missing" if not math.isfinite(number) else f"{number:.2%}"


def render_action_summary(
    status: str,
    reasons: list[str],
    metrics: dict[str, Any],
    cash: dict[str, Any],
    research: dict[str, Any],
    broker_rule: dict[str, Any],
) -> str:
    lines = [
        "# User Current Action Summary",
        "",
        f"- action_status: `{status}`",
        f"- official_metric_mode: `{official_metric_mode(metrics) or 'missing'}`",
        f"- valid_for_production: `{production_valid(metrics)}`",
        f"- production_applied: `{str(research.get('production_applied')).lower()}`",
        f"- sidecar_only: `{str(research.get('sidecar_only')).lower()}`",
        f"- production_policy: `{research.get('production_policy')}`",
        f"- sidecar_applied_to_production: `{str(research.get('sidecar_applied_to_production')).lower()}`",
        f"- current_holdings_source: `{research.get('current_holdings_source')}`",
        f"- source_target_run_id: `{research.get('source_target_run_id') or ''}`",
        f"- source_target_case_id: `{research.get('source_target_case_id') or ''}`",
        f"- promotion_status: `{research.get('promotion_status')}`",
        f"- shadow_available: `{str(research.get('shadow_available')).lower()}`",
        f"- projected_holdings_path: `{research.get('projected_holdings_path') or ''}`",
        f"- projected_market_leader_holdings_path: `{research.get('projected_market_leader_holdings_path') or ''}`",
        f"- decision_cadence_available: `{str(research.get('decision_cadence_available')).lower()}`",
        f"- decision_cadence_path: `{research.get('decision_cadence_path') or ''}`",
        f"- mid_month_reentry_allowed: `{str(research.get('mid_month_reentry_allowed')).lower()}`",
        f"- cash_policy_flag: `{cash.get('cash_policy_flag') or ''}`",
        f"- combined_projected_cash_after_ready_orders: `{safe_float(cash.get('combined_projected_cash_weight_after_ready_orders'), np.nan):.2%}`",
        "",
        "## Broker Rule Backtest",
        "",
        f"- current_holdings_backtest_rule: `{broker_rule.get('official_metric_mode') or 'missing'}`",
        "- broker_rule_detail: `next_close_fills + integer_shares + cash_ledger + trading_costs`",
        f"- daily_monitoring_backtest_status: `{broker_rule.get('daily_monitoring_status')}`",
        f"- daily_risk_overlay_validated: `{str(broker_rule.get('daily_risk_overlay_validated')).lower()}`",
        f"- daily_risk_action_evidence_count: `{broker_rule.get('daily_risk_action_evidence_count')}`",
        f"- full_nonmonthly_entry_replacement_validated: `{str(broker_rule.get('full_nonmonthly_entry_replacement_validated')).lower()}`",
        "",
        "| Portfolio | Official Broker CAGR | Official Broker MaxDD | Official Sharpe | Daily Position-Risk CAGR | Daily Position-Risk MaxDD | Daily Risk Actions |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    portfolios = broker_rule.get("portfolios") if isinstance(broker_rule.get("portfolios"), dict) else {}
    for portfolio in PORTFOLIOS:
        item = portfolios.get(portfolio) if isinstance(portfolios, dict) else {}
        official = item.get("official_broker_ledger") if isinstance(item, dict) and isinstance(item.get("official_broker_ledger"), dict) else {}
        daily = item.get("daily_monitoring_backtest") if isinstance(item, dict) and isinstance(item.get("daily_monitoring_backtest"), dict) else {}
        position = daily.get("position_risk_broker_ledger") if isinstance(daily.get("position_risk_broker_ledger"), dict) else {}
        lines.append(
            "| {portfolio} | {cagr} | {mdd} | {sharpe:.3f} | {risk_cagr} | {risk_mdd} | {actions} |".format(
                portfolio=portfolio,
                cagr=pct_text(official.get("cagr")),
                mdd=pct_text(official.get("max_dd")),
                sharpe=safe_float(official.get("sharpe"), float("nan")),
                risk_cagr=pct_text(position.get("cagr")),
                risk_mdd=pct_text(position.get("max_dd")),
                actions=int(safe_float(daily.get("nonmonthly_risk_action_count"), 0)),
            )
        )
    lines.extend(
        [
            "",
            "- Official current-holding performance must be judged by the broker-ledger row, not deprecated weight-level research metrics.",
            "- Daily monitoring results are displayed separately so a risk overlay cannot be mistaken for the monthly production target-book result.",
            "",
        ]
    )
    lines.extend(
        [
            "## Research Sidecar Context",
            "",
            "- Market Leader / Multi-Lane / Crisis outputs alter current holdings only after production activation.",
            f"- replay_gate_status: `{research.get('replay_gate_status')}`",
            f"- promotion_gate_status: `{research.get('promotion_gate_status')}`",
            f"- promotion_review_status: `{research.get('promotion_review_status')}`",
            f"- production_mutation_check_status: `{research.get('production_mutation_check_status')}`",
            f"- production_mutation_audit_status: `{research.get('production_mutation_audit_status')}`",
            "",
            "## Reasons",
            "",
        ]
    )
    lines.extend([f"- {item}" for item in reasons] if reasons else ["- none"])
    lines.extend(
        [
            "",
            "## Operating Rules",
            "",
            "- This report shows current simulated broker-ledger holdings only.",
            "- Current holdings follow the production operating book generated before broker replay.",
            "- If integrated_shadow is enabled, projected holdings show what the H-case target would do before approval.",
            "- If market_leader_shadow is enabled, projected holdings show what the Market Leader target would do before approval.",
            "- If alphaops_vnext_production or approved_integrated is active before broker replay, current holdings can change in the same run.",
            "- Crisis defense does not force month-end waiting; decision_cadence can flag mid-month staged reentry review.",
            "- Target recommendation books are hidden by default.",
            "- REVIEW_REQUIRED is not an auto-trade instruction.",
            "- Research metrics are not promotion evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def write_readme(path: Path) -> None:
    text = """# README FIRST

This folder is the default user-facing operating view.

- `01_current_holdings.csv` is the current simulated broker-ledger book.
- `03_period_returns.csv` uses broker replay equity curves and includes drawdown.
- `04_official_metrics.json` is the official broker-ledger metric payload.
- `07_research_sidecar_context.json` explains whether AlphaOps vNext or research sidecars altered current holdings.
- `08_broker_rule_backtest.json` summarizes official broker-rule backtests and the separate daily monitoring overlay.
- Target recommendation books are not current holdings and are hidden by default.
- Market Leader / Multi-Lane / Crisis sidecars are research-only unless explicitly promoted; `alphaops_vnext_production` replaces the operating book before broker replay.
- `outputs/operator_review/projected_holdings_after_integrated_target.csv` shows the shadow target delta when available.
- `outputs/operator_review/projected_holdings_after_market_leader_target.csv` shows the Market Leader shadow delta when available.
- `outputs/decision_cadence/decision_cadence_summary.json` explains daily/weekly/monthly review cadence and mid-month reentry rules when available.
- Deprecated/research backtests are not copied here and are not promotion evidence.
- Do not trade rows or portfolios marked REVIEW_REQUIRED or DO_NOT_TRADE.
"""
    path.write_text(text, encoding="utf-8")


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    price_cache = repo_path(args.price_cache)
    output_dir.mkdir(parents=True, exist_ok=True)

    current = normalize_current_holdings(latest_run)
    metrics = load_official_metrics(latest_run)
    broker_rule = build_broker_rule_backtest(latest_run, metrics)
    current = attach_broker_rule_columns(current, broker_rule)
    current.to_csv(output_dir / "01_current_holdings.csv", index=False)

    cash = build_cash_summary(latest_run, current)
    write_json(output_dir / "02_cash_summary.json", cash)

    period = pd.concat([portfolio_period_returns(latest_run), benchmark_period_returns(price_cache)], ignore_index=True)
    period.to_csv(output_dir / "03_period_returns.csv", index=False)
    benchmarks = period[period["series_type"].astype(str).eq("benchmark")].copy() if not period.empty else pd.DataFrame()
    benchmarks.to_csv(output_dir / "06_benchmark_comparison.csv", index=False)

    write_json(output_dir / "04_official_metrics.json", metrics)
    research = research_sidecar_context(latest_run)
    write_json(output_dir / "07_research_sidecar_context.json", research)
    write_json(output_dir / "08_broker_rule_backtest.json", broker_rule)

    status, reasons = build_action_summary(latest_run, metrics, cash)
    (output_dir / "05_action_summary.md").write_text(
        render_action_summary(status, reasons, metrics, cash, research, broker_rule),
        encoding="utf-8",
    )
    write_readme(output_dir / "README_FIRST.md")

    payload = {
        "status": "completed",
        "schema_version": "user-current-report-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest_run),
        "output_dir": str(output_dir),
        "action_status": status,
        "reason_count": len(reasons),
        "current_holding_rows": int(len(current)),
        "period_return_rows": int(len(period)),
        "production_applied": bool(research.get("production_applied")),
        "sidecar_only": bool(research.get("sidecar_only")),
        "production_policy": research.get("production_policy"),
        "sidecar_applied_to_production": bool(research.get("sidecar_applied_to_production")),
        "source_target_run_id": research.get("source_target_run_id"),
        "source_target_case_id": research.get("source_target_case_id"),
        "approved_policy_path": research.get("approved_policy_path"),
        "promotion_status": research.get("promotion_status"),
        "shadow_available": bool(research.get("shadow_available")),
        "projected_holdings_path": research.get("projected_holdings_path"),
        "decision_cadence_available": bool(research.get("decision_cadence_available")),
        "decision_cadence_path": research.get("decision_cadence_path"),
        "mid_month_reentry_allowed": bool(research.get("mid_month_reentry_allowed")),
        "current_holdings_source": research.get("current_holdings_source"),
        "research_sidecar_message": research.get("message"),
        "broker_rule_backtest_path": str(output_dir / "08_broker_rule_backtest.json"),
        "official_metric_mode": broker_rule.get("official_metric_mode"),
        "daily_monitoring_backtest_status": broker_rule.get("daily_monitoring_status"),
        "daily_risk_overlay_validated": bool(broker_rule.get("daily_risk_overlay_validated")),
        "daily_risk_action_evidence_count": int(safe_float(broker_rule.get("daily_risk_action_evidence_count"), 0)),
        "full_nonmonthly_entry_replacement_validated": bool(broker_rule.get("full_nonmonthly_entry_replacement_validated")),
        "required_files": REQUIRED_USER_FILES,
        "missing_required_files": [name for name in REQUIRED_USER_FILES if not (output_dir / name).exists()],
    }
    write_json(output_dir / "summary.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/user_current")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_report(args)
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.strict and payload.get("missing_required_files"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

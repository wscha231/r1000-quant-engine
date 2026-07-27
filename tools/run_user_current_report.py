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
import os
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
from tools.build_daily_user_current_contract import (  # noqa: E402
    append_review_only_notice as append_daily_review_only_notice,
    build_decision as build_daily_rebalance_decision,
    freshness_state as daily_freshness_state,
    load_order_preview as load_daily_order_preview,
    load_target_weights as load_daily_target_weights,
)
from tools.run287_promotion_gate import gate_for_consumer  # noqa: E402


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
    "02_target_weights.csv",
    "02_cash_summary.json",
    "03_order_preview.csv",
    "03_period_returns.csv",
    "04_official_metrics.json",
    "05_action_summary.md",
    "06_benchmark_comparison.csv",
    "07_name_rationales.csv",
    "07_research_sidecar_context.json",
    "08_rebalance_decision.json",
    "08_broker_rule_backtest.json",
]
LATEST_CLOSE_PERFORMANCE_FILE = "10_latest_close_performance.json"


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


def snapshot_max_date(frame: pd.DataFrame) -> str:
    if frame.empty or "as_of_date" not in frame.columns:
        return ""
    dates = pd.to_datetime(frame["as_of_date"], errors="coerce")
    if not dates.notna().any():
        return ""
    return pd.Timestamp(dates.max()).date().isoformat()


def snapshot_date_rank(value: str) -> pd.Timestamp:
    if not value:
        return pd.Timestamp.min
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return pd.Timestamp.min
    return pd.Timestamp(parsed)


def load_current_holdings_source(latest_run: Path, output_dir: Path) -> tuple[pd.DataFrame, str, str]:
    committed_cloud_paths = [
        latest_run.parent
        / "cloud_results"
        / "full_rebuild"
        / "latest_global_alpha_universe"
        / "user_current"
        / "01_current_holdings.csv"
    ]
    try:
        latest_inside_repo = latest_run.resolve().is_relative_to(REPO_ROOT.resolve())
    except Exception:
        latest_inside_repo = False
    if latest_inside_repo:
        committed_cloud_paths.append(
            REPO_ROOT
            / "cloud_results"
            / "full_rebuild"
            / "latest_global_alpha_universe"
            / "user_current"
            / "01_current_holdings.csv"
        )
    candidates: list[tuple[str, str, int, list[Path]]] = [
        (
            "operating_snapshot",
            "fresh operating_snapshot/current_operating_holdings_latest.csv",
            40,
            [latest_run / "operating_snapshot" / "current_operating_holdings_latest.csv"],
        ),
        (
            "committed_cloud_results_snapshot",
            "committed cloud_results latest user_current/01_current_holdings.csv",
            30,
            committed_cloud_paths,
        ),
        (
            "restored_user_current_snapshot",
            "restored user_current/01_current_holdings.csv",
            20,
            [output_dir / "01_current_holdings.csv", latest_run / "user_current" / "01_current_holdings.csv"],
        ),
        (
            "user_portfolio_reports",
            "restored user_portfolio_reports current holdings",
            10,
            [
                latest_run / "user_portfolio_reports" / "main_current_operating_holdings_latest.csv",
                latest_run / "user_portfolio_reports" / "concentrated_current_operating_holdings_latest.csv",
                latest_run / "user_portfolio_reports" / "main" / "current_operating_holdings_latest.csv",
                latest_run / "user_portfolio_reports" / "concentrated" / "current_operating_holdings_latest.csv",
            ],
        ),
    ]
    seen: set[Path] = set()
    usable: list[tuple[pd.Timestamp, int, pd.DataFrame, str, str]] = []
    for mode, detail, priority, paths in candidates:
        frames: list[pd.DataFrame] = []
        used: list[str] = []
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            frame = read_csv(path)
            if frame.empty:
                continue
            frames.append(frame)
            used.append(str(path))
            if mode != "user_portfolio_reports":
                break
        if frames:
            combined = pd.concat(frames, ignore_index=True)
            as_of = snapshot_max_date(combined)
            source_detail = f"{detail}: {'; '.join(used)}"
            if as_of:
                source_detail = f"{source_detail}; as_of_date={as_of}"
            usable.append((snapshot_date_rank(as_of), priority, combined, mode, source_detail))
    if usable:
        _, _, frame, mode, detail = max(usable, key=lambda item: (item[0], item[1]))
        return frame, mode, detail
    return pd.DataFrame(), "missing", "no non-empty current holdings snapshot found"


def normalize_current_holdings(latest_run: Path, output_dir: Path | None = None) -> tuple[pd.DataFrame, str, str]:
    frame, source_mode, source_detail = load_current_holdings_source(latest_run, output_dir or latest_run / "user_current")
    if frame.empty:
        return frame, source_mode, source_detail
    out = frame.copy()
    if "ticker" in out.columns:
        out["ticker"] = out["ticker"].map(clean_ticker)
    if "portfolio_kind" not in out.columns:
        out["portfolio_kind"] = out.get("portfolio", "")
    if "portfolio" not in out.columns:
        out["portfolio"] = out["portfolio_kind"]
    out["portfolio_kind"] = out["portfolio_kind"].astype(str).str.lower().str.strip()
    out["portfolio"] = out["portfolio"].astype(str).str.lower().str.strip()
    wanted = [
        "as_of_date",
        "snapshot_semantics",
        "portfolio",
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
    return out[wanted].copy(), source_mode, source_detail


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


def load_latest_close_performance(latest_run: Path) -> dict[str, Any]:
    scorecard = read_json(
        latest_run
        / "run287_operating_scorecard"
        / "operating_scorecard.json"
    )
    payload = scorecard.get("latest_close_performance")
    if (
        scorecard.get("scorecard_trusted") is not True
        or not isinstance(payload, dict)
        or payload.get("status") != "READY_LATEST_CLOSE_REVIEW_ONLY"
        or payload.get("latest_close_exact") is not True
        or payload.get("review_only") is not True
        or payload.get("live_trading_enabled") is not False
        or payload.get("production_activation_allowed") is not False
        or payload.get(
            "historical_cagr_mdd_replacement_allowed"
        ) is not False
        or payload.get("promotion_evidence_allowed") is not False
    ):
        return {}
    return payload


def production_valid(metrics: dict[str, Any]) -> bool:
    return not production_blockers(metrics)


def portfolio_metric_items(metrics: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    items: list[tuple[str, dict[str, Any]]] = []
    nested = metrics.get("portfolios") if isinstance(metrics.get("portfolios"), dict) else {}
    for portfolio in PORTFOLIOS:
        item = nested.get(portfolio) if isinstance(nested, dict) else {}
        if isinstance(item, dict) and item:
            items.append((portfolio, item))
    seen = {portfolio for portfolio, _ in items}
    for portfolio in PORTFOLIOS:
        if portfolio in seen:
            continue
        item = metrics.get(portfolio)
        if isinstance(item, dict) and item:
            items.append((portfolio, item))
    return items


def bad_status(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return bool(text) and text not in {"ok", "pass", "passed", "ready", "completed"}


def production_blockers(metrics: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not metrics or metrics.get("status") == "missing":
        return ["official_metrics_missing"]
    mode = official_metric_mode(metrics)
    if not mode:
        blockers.append("official_metric_mode_missing")
    elif mode != "broker_ledger_next_close":
        blockers.append(f"official_metric_mode={mode}")
    if metrics.get("valid_for_production") is False:
        blockers.append("official_metrics.valid_for_production=false")
    if metrics.get("production_target_pass") is False:
        blockers.append("official_metrics.production_target_pass=false")
    if metrics.get("strengthened_pass") is False:
        blockers.append("official_metrics.strengthened_pass=false")
    for portfolio, item in portfolio_metric_items(metrics):
        if item.get("valid_for_production") is False:
            blockers.append(f"{portfolio}.valid_for_production=false")
        if bad_status(item.get("verdict_status")):
            blockers.append(f"{portfolio}.verdict_status={item.get('verdict_status')}")
        if bad_status(item.get("data_readiness_status")):
            blockers.append(f"{portfolio}.data_readiness_status={item.get('data_readiness_status')}")
        if item.get("data_readiness_policy_replay_ready") is False:
            blockers.append(f"{portfolio}.data_readiness_policy_replay_ready=false")
        if item.get("target_pass") is False:
            blockers.append(f"{portfolio}.target_pass=false")
        if item.get("strengthened_pass") is False:
            blockers.append(f"{portfolio}.strengthened_pass=false")
        gate = item.get("broker_ledger_window_gate")
        if isinstance(gate, dict):
            if gate.get("valid") is False:
                blockers.append(f"{portfolio}.broker_ledger_window_gate.valid=false")
            if bad_status(gate.get("status")):
                blockers.append(f"{portfolio}.broker_ledger_window_gate.status={gate.get('status')}")
            readiness = gate.get("data_readiness")
            if isinstance(readiness, dict):
                if bad_status(readiness.get("status")):
                    blockers.append(f"{portfolio}.broker_ledger_window_gate.data_readiness.status={readiness.get('status')}")
                if readiness.get("ready_for_policy_replay") is False:
                    blockers.append(f"{portfolio}.broker_ledger_window_gate.data_readiness.ready_for_policy_replay=false")
    return blockers


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
        out[col] = pd.Series([""] * len(out), index=out.index, dtype=object)
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


def canonical_cash_targets(target_weights: pd.DataFrame | None) -> dict[str, float]:
    if target_weights is None or target_weights.empty:
        return {}
    out: dict[str, float] = {}
    for row in target_weights.to_dict("records"):
        portfolio = str(row.get("portfolio") or row.get("portfolio_kind") or "").lower().strip()
        ticker = clean_ticker(row.get("ticker"))
        if portfolio and ticker == "CASH":
            out[portfolio] = safe_float(row.get("target_weight"), 0.0)
    return out


def build_cash_summary(latest_run: Path, current: pd.DataFrame, target_weights: pd.DataFrame | None = None) -> dict[str, Any]:
    snapshot = read_json(latest_run / "operating_snapshot" / "current_portfolio_snapshot_summary.json")
    canonical_cash_by_portfolio = canonical_cash_targets(target_weights)
    out: dict[str, Any] = {
        "schema_version": "user-current-cash-summary-v1",
        "source": "outputs/operating_snapshot/current_portfolio_snapshot_summary.json; outputs/user_current/02_target_weights.csv",
        "combined_current_cash_weight": snapshot.get("combined_current_cash_weight"),
        "combined_target_cash_weight": snapshot.get("combined_target_cash_weight"),
        "combined_cash_gap_weight": snapshot.get("combined_cash_gap_weight"),
        "combined_canonical_target_cash_weight": None,
        "combined_current_vs_canonical_cash_gap_weight": None,
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
    current_cash_weighted = 0.0
    canonical_cash_weighted = 0.0
    canonical_equity_weight = 0.0
    if not current.empty and {"portfolio_kind", "row_type", "current_weight"}.issubset(current.columns):
        cash = current[current["row_type"].astype(str).str.lower().eq("cash")].copy()
        for _, row in cash.iterrows():
            portfolio = str(row.get("portfolio_kind"))
            current_cash_weight = safe_float(row.get("current_weight"))
            canonical_target_cash = canonical_cash_by_portfolio.get(portfolio, np.nan)
            item = {
                "cash_weight": current_cash_weight,
                "cash_value_usd": safe_float(row.get("current_value_usd")),
                "canonical_target_cash_weight": canonical_target_cash,
                "current_vs_canonical_cash_gap_weight": canonical_target_cash - current_cash_weight
                if math.isfinite(canonical_target_cash)
                else np.nan,
                "target_cash_weight": canonical_target_cash,
                "target_cash_weight_semantics": "canonical target cash from 02_target_weights.csv",
            }
            current_cash_weighted += current_cash_weight
            if math.isfinite(canonical_target_cash):
                canonical_cash_weighted += canonical_target_cash
                canonical_equity_weight += 1.0
            preview = read_json(latest_run / "account_ledger_preview" / portfolio / "preview_metrics.json")
            if preview:
                preview_found = True
                equity = safe_float(preview.get("equity_usd"))
                projected_equity = safe_float(preview.get("projected_equity_usd"), equity)
                item.update(
                    {
                        "preview_target_cash_weight": safe_float(preview.get("target_cash_weight"), np.nan),
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
    if canonical_equity_weight > 0:
        out["combined_canonical_target_cash_weight"] = canonical_cash_weighted / max(canonical_equity_weight, 1e-12)
        out["combined_current_vs_canonical_cash_gap_weight"] = (
            canonical_cash_weighted - current_cash_weighted
        ) / max(canonical_equity_weight, 1e-12)
    if preview_found:
        out["combined_projected_cash_weight_after_ready_orders"] = projected_cash_usd / max(projected_equity_usd, 1e-12)
        out["combined_preview_target_cash_weight"] = target_cash_weighted / max(projected_equity_usd, 1e-12)
        out["preview_order_semantics"] = "projected after order preview; no orders are placed by this report"
    return out


def first_nonempty(row: dict[str, Any], names: list[str], default: Any = "") -> Any:
    for name in names:
        value = row.get(name)
        if value is None:
            continue
        if isinstance(value, float) and math.isnan(value):
            continue
        text = str(value).strip()
        if text and text.lower() != "nan":
            return value
    return default


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "blocked", "pass"}


def representative_selected_rows(latest_run: Path) -> dict[tuple[str, str], dict[str, Any]]:
    selected = read_csv(latest_run / "alphaops_vnext" / "selected_latest.csv")
    if selected.empty or "ticker" not in selected.columns:
        return {}
    frame = selected.copy()
    if "portfolio_kind" not in frame.columns:
        frame["portfolio_kind"] = frame.get("portfolio", "")
    frame["portfolio_key"] = frame["portfolio_kind"].astype(str).str.lower().str.strip()
    frame["ticker_key"] = frame["ticker"].map(clean_ticker)
    weight_source = frame.get("target_weight", frame.get("weight", pd.Series(dtype=float)))
    frame["_sort_weight"] = pd.to_numeric(weight_source, errors="coerce").fillna(0.0)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for _, row in frame.sort_values("_sort_weight", ascending=False).iterrows():
        portfolio = str(row.get("portfolio_key") or "").lower()
        ticker = clean_ticker(row.get("ticker_key"))
        if not portfolio or not ticker or (portfolio, ticker) in out:
            continue
        out[(portfolio, ticker)] = row.to_dict()
    return out


def rationale_flag(score: Any, *, positive_label: str, missing_label: str = "missing_or_neutral") -> str:
    value = safe_float(score, np.nan)
    if not math.isfinite(value):
        return missing_label
    if value > 0.0:
        return positive_label
    if value < 0.0:
        return "negative"
    return missing_label


def pit_status_from_selected(selected: dict[str, Any]) -> str:
    if not selected:
        return "missing_selected_latest_row"
    if boolish(selected.get("pit_evidence_blocked")):
        reason = str(selected.get("pit_evidence_block_reason") or "blocked").strip()
        return f"blocked:{reason}"
    available_from = first_nonempty(
        selected,
        [
            "latest_available_from",
            "feature_available_from_max",
            "latest_13f_available_from",
            "latest_etf_available_from",
            "latest_top_manager_available_from",
        ],
        "",
    )
    return "pit_available_from_present" if available_from else "unknown_pit_available_from"


def membership_status_from_selected(selected: dict[str, Any]) -> str:
    if not selected:
        return "unknown_membership_pit"
    explicit = first_nonempty(selected, ["membership_pit_status"], "")
    if explicit:
        return str(explicit)
    if boolish(selected.get("official_r1000_membership_proven")):
        return "official_r1000_membership_proven"
    universe = first_nonempty(selected, ["universe_label", "source_universe"], "")
    if universe:
        return f"unlabeled_or_proxy_source:{universe}"
    return "unknown_membership_pit"


def target_weight_map(target_weights: pd.DataFrame) -> dict[tuple[str, str], float]:
    if target_weights.empty:
        return {}
    out: dict[tuple[str, str], float] = {}
    for row in target_weights.to_dict("records"):
        portfolio = str(row.get("portfolio") or row.get("portfolio_kind") or "").lower().strip()
        ticker = clean_ticker(row.get("ticker"))
        if portfolio and ticker:
            out[(portfolio, ticker)] = safe_float(row.get("target_weight"), 0.0)
    return out


def target_row_map(target_weights: pd.DataFrame) -> dict[tuple[str, str], dict[str, Any]]:
    if target_weights.empty:
        return {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in target_weights.to_dict("records"):
        portfolio = str(row.get("portfolio") or row.get("portfolio_kind") or "").lower().strip()
        ticker = clean_ticker(row.get("ticker"))
        if portfolio and ticker:
            out[(portfolio, ticker)] = row
    return out


def build_name_rationales(
    latest_run: Path,
    current: pd.DataFrame,
    output_dir: Path,
    target_weights: pd.DataFrame | None = None,
) -> pd.DataFrame:
    selected_by_key = representative_selected_rows(latest_run)
    target_frame = target_weights if target_weights is not None else pd.DataFrame()
    target_by_key = target_weight_map(target_frame)
    target_rows_by_key = target_row_map(target_frame)
    rows: list[dict[str, Any]] = []
    if current.empty and not target_rows_by_key:
        columns = [
            "portfolio",
            "ticker",
            "current_weight",
            "target_weight",
            "canonical_target_weight",
            "replay_retention_weight",
            "selected_vs_retained",
            "lane",
            "theme",
            "sector",
            "subindustry",
            "leader_state",
            "selection_reason",
            "hold_reason",
            "risk_reason",
            "rs_spy_1m",
            "rs_spy_3m",
            "rs_spy_6m",
            "rs_qqq_1m",
            "rs_qqq_3m",
            "rs_qqq_6m",
            "rs_smh_soxx_if_applicable",
            "valuation_flag",
            "quality_flag",
            "evidence_flag",
            "top7_score",
            "form4_score",
            "etf_score",
            "gate_status",
            "is_new_buy_signal",
            "is_replay_retention",
            "data_pit_status",
            "membership_pit_status",
        ]
        return pd.DataFrame(columns=columns)

    current_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    if not current.empty:
        for row in current.to_dict("records"):
            portfolio = str(row.get("portfolio_kind") or row.get("portfolio") or "").lower().strip()
            ticker = clean_ticker(row.get("ticker"))
            if portfolio and ticker:
                current_by_key[(portfolio, ticker)] = row

    for key in sorted(set(current_by_key) | set(target_rows_by_key)):
        portfolio, ticker = key
        current_row = current_by_key.get(key, {})
        target_row = target_rows_by_key.get(key, {})
        selected = selected_by_key.get((portfolio, ticker), {})
        canonical_target_weight = target_by_key.get((portfolio, ticker), 0.0)
        current_weight = safe_float(current_row.get("current_weight"), 0.0)
        row_type = str(current_row.get("row_type") or "").lower()
        selection_reason = str(
            selected.get("selection_reason")
            or target_row.get("selection_reason")
            or current_row.get("entry_reasons")
            or ""
        ).strip()
        gate_status = str(selected.get("portfolio_candidate_gate_label") or selected.get("gate_status") or "").strip()
        hold_reason = str(
            selected.get("holding_state_reason")
            or current_row.get("daily_review_reason")
            or target_row.get("review_reason")
            or ""
        ).strip()
        replay_retention = (
            ticker == "CASH"
            or "hold_forward_to_latest_close" in selection_reason
            or gate_status.lower() == "rejected"
            or (bool(current_row) and canonical_target_weight <= 1e-12)
            or safe_float(current_row.get("holding_days"), 0.0) > 0
        )
        if ticker == "CASH" or row_type == "cash":
            selected_vs_retained = "cash_position"
        elif bool(target_row) and not current_row:
            selected_vs_retained = "new_target_candidate"
        elif not selected:
            selected_vs_retained = "current_holding_without_selected_latest_row"
        elif replay_retention:
            selected_vs_retained = "replay_retained_holding"
        else:
            selected_vs_retained = "current_policy_selected"
        replay_retention_weight = current_weight if replay_retention or (current_row and not target_row) else 0.0
        evidence_score = safe_float(
            first_nonempty(
                selected,
                ["evidence_support_score", "sec_combined_evidence_score", "evidence_fusion_score", "smart_money_shadow_score"],
                np.nan,
            ),
            np.nan,
        )
        rows.append(
            {
                "portfolio": portfolio,
                "ticker": ticker,
                "current_weight": current_weight,
                "target_weight": canonical_target_weight,
                "canonical_target_weight": canonical_target_weight,
                "replay_retention_weight": replay_retention_weight,
                "selected_vs_retained": selected_vs_retained,
                "lane": first_nonempty(
                    selected,
                    ["primary_lane", "lane", "portfolio_sleeve_label"],
                    first_nonempty(target_row, ["lane"], "CASH" if ticker == "CASH" else ""),
                ),
                "theme": first_nonempty(selected, ["theme_phase_primary", "theme", "etf_themes"], target_row.get("theme", "")),
                "sector": first_nonempty(selected, ["sector"], first_nonempty(target_row, ["sector"], current_row.get("sector", ""))),
                "subindustry": first_nonempty(selected, ["subindustry", "industry_group"], current_row.get("industry", "")),
                "leader_state": first_nonempty(selected, ["leader_tier", "holding_state"], current_row.get("risk_state", "")),
                "selection_reason": selection_reason or ("cash_position" if ticker == "CASH" else ""),
                "hold_reason": hold_reason,
                "risk_reason": str(current_row.get("risk_state") or selected.get("crisis_defense_cut_reason") or "").strip(),
                "rs_spy_1m": safe_float(selected.get("rs_spy_1m"), np.nan),
                "rs_spy_3m": safe_float(selected.get("rs_spy_3m"), np.nan),
                "rs_spy_6m": safe_float(selected.get("rs_spy_6m"), np.nan),
                "rs_qqq_1m": safe_float(selected.get("rs_qqq_1m"), np.nan),
                "rs_qqq_3m": safe_float(selected.get("rs_qqq_3m"), np.nan),
                "rs_qqq_6m": safe_float(selected.get("rs_qqq_6m"), np.nan),
                "rs_smh_soxx_if_applicable": max(
                    safe_float(selected.get("rs_smh_6m"), -999.0),
                    safe_float(selected.get("rs_soxx_6m"), -999.0),
                )
                if selected
                else np.nan,
                "valuation_flag": rationale_flag(selected.get("valuation_support_score"), positive_label="valuation_support"),
                "quality_flag": rationale_flag(
                    first_nonempty(selected, ["quality_compounder_lane_score", "sector_adjusted_quality_score"], np.nan),
                    positive_label="quality_support",
                ),
                "evidence_flag": "positive_evidence" if math.isfinite(evidence_score) and evidence_score > 0 else "missing_or_neutral",
                "top7_score": safe_float(first_nonempty(selected, ["top7_manager_discovery_score", "top7_score"], np.nan), np.nan),
                "form4_score": safe_float(first_nonempty(selected, ["sec_form4_score", "form4_score"], np.nan), np.nan),
                "etf_score": safe_float(first_nonempty(selected, ["etf_holdings_score", "etf_score"], np.nan), np.nan),
                "gate_status": gate_status,
                "is_new_buy_signal": bool(selected_vs_retained in {"current_policy_selected", "new_target_candidate"}),
                "is_replay_retention": bool(replay_retention),
                "data_pit_status": pit_status_from_selected(selected),
                "membership_pit_status": membership_status_from_selected(selected),
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(output_dir / "07_name_rationales.csv", index=False)
    return out


def build_operating_contract_files(latest_run: Path, output_dir: Path, current: pd.DataFrame) -> dict[str, Any]:
    state = daily_freshness_state(latest_run)
    if not state["selection_allowed"]:
        review_reason = "; ".join(state["blockers"]) or state["recommendation_status"]
    else:
        review_reason = "review-only operating output; human approval required"
    target_weights = load_daily_target_weights(latest_run, True, review_reason, current)
    order_preview = load_daily_order_preview(latest_run, target_weights, True, review_reason, current)
    decision = build_daily_rebalance_decision(
        state=state,
        target_weights=target_weights,
        order_preview=order_preview,
        source_run_id=str(os.environ.get("GITHUB_RUN_ID") or "local"),
        source_commit_sha=str(os.environ.get("GITHUB_SHA") or ""),
        source_branch=str(os.environ.get("GITHUB_REF_NAME") or ""),
        source_artifact_name=f"{os.environ.get('ARTIFACT_PROFILE', '')}_{os.environ.get('SIDECAR_PROFILE', '')}_{os.environ.get('GITHUB_RUN_ID', 'local')}",
    )
    target_path = output_dir / "02_target_weights.csv"
    order_path = output_dir / "03_order_preview.csv"
    decision_path = output_dir / "08_rebalance_decision.json"
    target_weights.to_csv(target_path, index=False)
    order_preview.to_csv(order_path, index=False)
    write_json(decision_path, decision)
    append_daily_review_only_notice(output_dir / "DAILY_REVIEW_ONLY.md")
    summary = {
        "schema_version": "user-current-operating-contract-v1",
        "status": "completed",
        "target_weight_rows": int(len(target_weights)),
        "order_preview_rows": int(len(order_preview)),
        "current_snapshot_rows": int(len(current)),
        "current_snapshot_used_for_order_preview": not current.empty,
        "decision": decision.get("decision"),
        "selection_allowed": bool(state["selection_allowed"]),
        "promotion_allowed": bool(state["promotion_allowed"]),
        "recommendation_status": state["recommendation_status"],
        "review_only": True,
        "canonical_production_sync": False,
        "live_trading_enabled": False,
        "production_mutation_allowed": False,
        "human_approval_required": True,
        "outputs": {
            "target_weights": str(target_path),
            "order_preview": str(order_path),
            "rebalance_decision": str(decision_path),
        },
    }
    write_json(output_dir / "09_daily_output_contract_summary.json", summary)
    return summary


def build_action_summary(latest_run: Path, metrics: dict[str, Any], cash: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    mode = official_metric_mode(metrics)
    if mode and mode != "broker_ledger_next_close":
        return "DO_NOT_USE", [f"official_metric_mode is {mode}, not broker_ledger_next_close"]
    blockers = production_blockers(metrics)
    if blockers:
        return "DO_NOT_TRADE", [f"production_promotion_blocker={item}" for item in blockers]
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
    latest_close: dict[str, Any],
) -> str:
    promotion_allowed = production_valid(metrics)
    production_promotion_allowed = promotion_allowed and status not in {"DO_NOT_USE", "DO_NOT_TRADE"}
    recommendation_status = "DO_NOT_USE_REVIEW_REQUIRED" if not promotion_allowed else "REVIEW_REQUIRED"
    lines = [
        "# User Current Action Summary",
        "",
        f"- action_status: `{status}`",
        f"- recommendation_status: `{recommendation_status}`",
        f"- official_metric_mode: `{official_metric_mode(metrics) or 'missing'}`",
        f"- valid_for_production: `{promotion_allowed}`",
        f"- production_promotion_allowed: `{production_promotion_allowed}`",
        f"- production_applied: `{str(research.get('production_applied')).lower()}`",
        f"- sidecar_only: `{str(research.get('sidecar_only')).lower()}`",
        f"- production_policy: `{research.get('production_policy')}`",
        f"- sidecar_applied_to_production: `{str(research.get('sidecar_applied_to_production')).lower()}`",
        f"- current_holdings_source: `{research.get('current_holdings_source')}`",
        f"- current_holdings_snapshot_source_mode: `{research.get('current_holdings_snapshot_source_mode') or ''}`",
        f"- current_holdings_snapshot_restored: `{str(research.get('current_holdings_snapshot_restored')).lower()}`",
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
            "## Latest Accepted Close",
            "",
            f"- status: `{latest_close.get('status') or 'UNAVAILABLE'}`",
            f"- as_of_date: `{latest_close.get('as_of_date') or 'UNAVAILABLE'}`",
            "- Operating return/MDD includes accepted durable catch-up marks.",
            "- Chain-linked CAGR is exact at the endpoints; its MDD value is an optimistic lower bound on loss magnitude and the exact MDD can be more negative.",
            "- The historical baseline remains separately locked.",
            "",
            "| Portfolio | Locked historical CAGR/MDD | Operating return/MDD since $100k seed | Latest-close chain CAGR/optimistic MDD bound |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for portfolio in PORTFOLIOS:
        current = latest_close.get("portfolios", {}).get(portfolio, {})
        historical = current.get("historical_locked", {})
        operating = current.get("operating_since_seed", {})
        chain = current.get("latest_close_chain_linked", {})
        lines.append(
            "| {portfolio} | {hist_cagr} / {hist_mdd} | "
            "{operating_return} / {operating_mdd} | "
            "{chain_cagr} / {chain_mdd} |".format(
                portfolio=portfolio,
                hist_cagr=pct_text(historical.get("cagr")),
                hist_mdd=pct_text(historical.get("max_drawdown")),
                operating_return=pct_text(operating.get("total_return")),
                operating_mdd=pct_text(operating.get("max_drawdown")),
                chain_cagr=pct_text(chain.get("cagr")),
                chain_mdd=pct_text(chain.get("max_drawdown")),
            )
        )
    lines.extend([""])
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
            "- This is NOT a live broker account and must not be treated as live holdings.",
            "- Do not trade while action_status is DO_NOT_TRADE or recommendation_status is DO_NOT_USE_REVIEW_REQUIRED.",
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
- `02_target_weights.csv` is the review-only target-weight bridge for operator inspection.
- `03_order_preview.csv` is the review-only current-vs-target delta preview; it is not an order ticket.
- `03_period_returns.csv` uses broker replay equity curves and includes drawdown.
- `04_official_metrics.json` is the official broker-ledger metric payload.
- `10_latest_close_performance.json` separates the locked historical baseline,
  accepted paper return/MDD, and latest-close chain-linked diagnostics.
- `07_name_rationales.csv` explains whether each visible holding is a new policy selection or replay retention.
- `07_research_sidecar_context.json` explains whether AlphaOps vNext or research sidecars altered current holdings.
- `08_rebalance_decision.json` is the review-only rebalance decision contract.
- `08_broker_rule_backtest.json` summarizes official broker-rule backtests and the separate daily monitoring overlay.
- This is NOT a live broker account. It is a simulated broker-ledger holdings snapshot from AlphaOps target-book replay.
- Do not trade while `action_status=DO_NOT_TRADE` or `recommendation_status=DO_NOT_USE_REVIEW_REQUIRED`.
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
    (output_dir / LATEST_CLOSE_PERFORMANCE_FILE).unlink(
        missing_ok=True
    )
    require_latest_close = bool(
        getattr(args, "require_latest_close", False)
    )
    explicit_promotion = getattr(args, "promotion_state", "")
    promotion = gate_for_consumer(
        latest_run,
        explicit=repo_path(explicit_promotion) if explicit_promotion else None,
    )

    current, current_source_mode, current_source_detail = normalize_current_holdings(latest_run, output_dir)
    metrics = load_official_metrics(latest_run)
    latest_close = load_latest_close_performance(latest_run)
    broker_rule = build_broker_rule_backtest(latest_run, metrics)
    current = attach_broker_rule_columns(current, broker_rule)
    current.to_csv(output_dir / "01_current_holdings.csv", index=False)

    operating_contract = build_operating_contract_files(latest_run, output_dir, current)
    contract_target_weights = read_csv(output_dir / "02_target_weights.csv")
    cash = build_cash_summary(latest_run, current, contract_target_weights)
    write_json(output_dir / "02_cash_summary.json", cash)
    name_rationales = build_name_rationales(latest_run, current, output_dir, contract_target_weights)

    period = pd.concat([portfolio_period_returns(latest_run), benchmark_period_returns(price_cache)], ignore_index=True)
    period.to_csv(output_dir / "03_period_returns.csv", index=False)
    benchmarks = period[period["series_type"].astype(str).eq("benchmark")].copy() if not period.empty else pd.DataFrame()
    benchmarks.to_csv(output_dir / "06_benchmark_comparison.csv", index=False)

    metrics_for_output = {
        **metrics,
        "historical_baseline_locked": True,
        "latest_close_performance": latest_close,
    }
    write_json(output_dir / "04_official_metrics.json", metrics_for_output)
    if latest_close:
        write_json(
            output_dir / LATEST_CLOSE_PERFORMANCE_FILE,
            latest_close,
        )
    research = research_sidecar_context(latest_run)
    research["legacy_promotion_status"] = research.get("promotion_status")
    research["promotion_status"] = promotion["promotion_state"]
    research["promotion_state_source_sha256"] = promotion["source_sha256"]
    research["promotion_rollback_triggered"] = promotion["rollback_triggered"]
    research["current_holdings_snapshot_source_mode"] = current_source_mode
    research["current_holdings_snapshot_source_detail"] = current_source_detail
    research["current_holdings_snapshot_restored"] = current_source_mode in {
        "restored_user_current_snapshot",
        "committed_cloud_results_snapshot",
        "user_portfolio_reports",
    }
    research["current_holdings_missing"] = current.empty
    write_json(output_dir / "07_research_sidecar_context.json", research)
    write_json(output_dir / "08_broker_rule_backtest.json", broker_rule)

    status, reasons = build_action_summary(latest_run, metrics, cash)
    blockers = production_blockers(metrics)
    legacy_promotion_valid = not blockers
    blockers = [*blockers, f"promotion_state:{promotion['promotion_state']}"]
    promotion_valid = False
    production_promotion_allowed = False
    recommendation_status = "DO_NOT_USE_REVIEW_REQUIRED" if not legacy_promotion_valid else "REVIEW_REQUIRED"
    (output_dir / "05_action_summary.md").write_text(
        render_action_summary(
            status,
            reasons,
            metrics,
            cash,
            research,
            broker_rule,
            latest_close,
        ),
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
        "recommendation_status": recommendation_status,
        "valid_for_production": promotion_valid,
        "production_promotion_allowed": production_promotion_allowed,
        "legacy_metric_gate_passed": legacy_promotion_valid,
        "production_blockers": blockers,
        "reason_count": len(reasons),
        "current_holding_rows": int(len(current)),
        "current_holdings_source_mode": current_source_mode,
        "current_holdings_source_detail": current_source_detail,
        "current_holdings_snapshot_restored": current_source_mode
        in {"restored_user_current_snapshot", "committed_cloud_results_snapshot", "user_portfolio_reports"},
        "current_holdings_missing": current.empty,
        "period_return_rows": int(len(period)),
        "name_rationale_rows": int(len(name_rationales)),
        "target_weight_rows": int(operating_contract.get("target_weight_rows", 0)),
        "order_preview_rows": int(operating_contract.get("order_preview_rows", 0)),
        "current_snapshot_used_for_order_preview": bool(operating_contract.get("current_snapshot_used_for_order_preview")),
        "daily_contract_decision": operating_contract.get("decision"),
        "review_only": True,
        "canonical_production_sync": False,
        "live_trading_enabled": False,
        "production_mutation_allowed": False,
        "human_approval_required": True,
        "production_applied": bool(research.get("production_applied")),
        "sidecar_only": bool(research.get("sidecar_only")),
        "production_policy": research.get("production_policy"),
        "sidecar_applied_to_production": bool(research.get("sidecar_applied_to_production")),
        "source_target_run_id": research.get("source_target_run_id"),
        "source_target_case_id": research.get("source_target_case_id"),
        "approved_policy_path": research.get("approved_policy_path"),
        "promotion_status": research.get("promotion_status"),
        "promotion_state_source_sha256": promotion["source_sha256"],
        "promotion_rollback_triggered": promotion["rollback_triggered"],
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
        "latest_close_performance_status": latest_close.get(
            "status", "UNAVAILABLE"
        ),
        "latest_close_as_of_date": latest_close.get("as_of_date"),
        "latest_close_performance_path": (
            str(output_dir / "10_latest_close_performance.json")
            if latest_close
            else ""
        ),
        "latest_close_performance_required": require_latest_close,
        "required_files": [
            *REQUIRED_USER_FILES,
            *(
                [LATEST_CLOSE_PERFORMANCE_FILE]
                if require_latest_close
                else []
            ),
        ],
        "missing_required_files": [
            name
            for name in [
                *REQUIRED_USER_FILES,
                *(
                    [LATEST_CLOSE_PERFORMANCE_FILE]
                    if require_latest_close
                    else []
                ),
            ]
            if not (output_dir / name).exists()
        ],
    }
    write_json(output_dir / "summary.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/user_current")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument(
        "--require-latest-close",
        action="store_true",
        help=(
            "Require the accepted exact-close performance artifact. "
            "Use only in the daily accepted-close workflow."
        ),
    )
    parser.add_argument("--promotion-state", default="")
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

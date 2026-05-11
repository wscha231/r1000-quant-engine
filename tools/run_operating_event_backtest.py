#!/usr/bin/env python3
"""Summarize operating event backtest evidence from broker replay artifacts.

This sidecar is deliberately explicit about what is and is not verified:

- broker ledger proves account-like daily equity, shares, cash, and costs;
- broker position-risk replay proves daily/weekly risk exits and trims when
  those artifacts contain risk actions;
- execution-policy replay proves account-aware target execution;
- full historical non-monthly entry/replacement is only marked validated when
  target books contain more than one decision date inside at least one month.

It does not promote a policy or fabricate daily target decisions from monthly
research books.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/operating_event_backtest"
PORTFOLIOS = ("main", "concentrated")


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def date_text(value: Any) -> str:
    dt = pd.to_datetime(value, errors="coerce")
    if pd.isna(dt):
        return ""
    return pd.Timestamp(dt).date().isoformat()


def target_book_path(latest_run: Path, portfolio: str) -> Path:
    operating = latest_run / "reports" / f"operating_{portfolio}_target_book.csv"
    if operating.exists():
        return operating
    if portfolio == "main":
        return latest_run / "reports" / "main_monthly_weights.csv"
    return latest_run / "reports" / "concentrated_strategy_holdings.csv"


def target_decision_profile(path: Path) -> dict[str, Any]:
    rows = read_csv(path)
    if rows.empty or "rebalance_date" not in rows.columns:
        return {
            "target_book_path": str(path),
            "target_book_exists": path.exists(),
            "target_book_rows": int(len(rows)),
            "target_book_unique_date_count": 0,
            "target_book_min_date": "",
            "target_book_max_date": "",
            "target_book_multi_decision_month_count": 0,
            "target_book_max_decisions_per_month": 0,
            "target_book_submonthly_decisions_validated": False,
            "operating_latest_append_detected": False,
            "target_dates": [],
        }
    dates = pd.to_datetime(rows["rebalance_date"], errors="coerce").dropna().dt.normalize()
    unique_dates = sorted(pd.Timestamp(x) for x in dates.drop_duplicates().tolist())
    month_counts = pd.Series(unique_dates, dtype="datetime64[ns]").dt.to_period("M").value_counts() if unique_dates else pd.Series(dtype=int)
    max_decisions = int(month_counts.max()) if not month_counts.empty else 0
    multi_months = int((month_counts > 1).sum()) if not month_counts.empty else 0
    operating_appended = False
    if "operating_appended" in rows.columns:
        appended_text = rows["operating_appended"].astype(str).str.lower().str.strip()
        operating_appended = bool(appended_text.isin({"true", "1", "yes"}).any())
    return {
        "target_book_path": str(path),
        "target_book_exists": path.exists(),
        "target_book_rows": int(len(rows)),
        "target_book_unique_date_count": int(len(unique_dates)),
        "target_book_min_date": date_text(min(unique_dates) if unique_dates else None),
        "target_book_max_date": date_text(max(unique_dates) if unique_dates else None),
        "target_book_multi_decision_month_count": multi_months,
        "target_book_max_decisions_per_month": max_decisions,
        "target_book_submonthly_decisions_validated": bool(max_decisions > 1),
        "operating_latest_append_detected": operating_appended,
        "target_dates": [date_text(x) for x in unique_dates],
    }


def csv_count(path: Path) -> int:
    frame = read_csv(path)
    return int(len(frame))


def metrics_subset(metrics: dict[str, Any], prefix: str) -> dict[str, Any]:
    return {
        f"{prefix}_status": metrics.get("status", "missing") if metrics else "missing",
        f"{prefix}_metric_mode": metrics.get("metric_mode", "") if metrics else "",
        f"{prefix}_cagr": safe_float(metrics.get("cagr")) if metrics else 0.0,
        f"{prefix}_max_dd": safe_float(metrics.get("max_dd")) if metrics else 0.0,
        f"{prefix}_sharpe": safe_float(metrics.get("sharpe")) if metrics else 0.0,
        f"{prefix}_end_date": metrics.get("end_date", "") if metrics else "",
        f"{prefix}_trade_count": int(safe_float(metrics.get("trade_count"), 0)) if metrics else 0,
    }


def nonmonthly_risk_evidence(
    *,
    portfolio: str,
    latest_run: Path,
    target_dates: set[str],
) -> tuple[list[dict[str, Any]], int, int]:
    risk_actions = read_csv(latest_run / "broker_position_risk_replay" / portfolio / "risk_actions.csv")
    if risk_actions.empty:
        return [], 0, 0
    if "signal_date" not in risk_actions.columns:
        return [], int(len(risk_actions)), 0
    out: list[dict[str, Any]] = []
    for row in risk_actions.to_dict("records"):
        signal_date = date_text(row.get("signal_date"))
        if not signal_date or signal_date in target_dates:
            continue
        out.append(
            {
                "portfolio": portfolio,
                "signal_date": signal_date,
                "fill_date": date_text(row.get("fill_date") or row.get("date")),
                "ticker": str(row.get("ticker", "")).upper(),
                "reason": row.get("reason") or row.get("risk_rule_action") or "",
                "price_return": safe_float(row.get("price_return")),
                "relative_return": safe_float(row.get("relative_return")),
                "gross_value": safe_float(row.get("gross_value")),
            }
        )
    return out, int(len(risk_actions)), int(len(out))


def summarize_portfolio(latest_run: Path, portfolio: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    target_profile = target_decision_profile(target_book_path(latest_run, portfolio))
    target_dates = set(target_profile.pop("target_dates", []))
    broker_metrics = read_json(latest_run / "broker_replay" / portfolio / "metrics.json")
    risk_metrics = read_json(latest_run / "broker_position_risk_replay" / portfolio / "metrics.json")
    execution_metrics = read_json(latest_run / "broker_execution_policy_replay" / portfolio / "metrics.json")
    risk_evidence, risk_action_count, nonmonthly_risk_action_count = nonmonthly_risk_evidence(
        portfolio=portfolio,
        latest_run=latest_run,
        target_dates=target_dates,
    )
    broker_equity_rows = csv_count(latest_run / "broker_replay" / portfolio / "equity_curve.csv")
    risk_equity_rows = csv_count(latest_run / "broker_position_risk_replay" / portfolio / "equity_curve.csv")
    execution_equity_rows = csv_count(latest_run / "broker_execution_policy_replay" / portfolio / "equity_curve.csv")
    daily_risk_engine_completed = bool(risk_metrics.get("status") == "completed" and risk_equity_rows > 0)
    daily_risk_action_evidence = bool(nonmonthly_risk_action_count > 0)
    full_nonmonthly_entries = bool(
        target_profile["target_book_submonthly_decisions_validated"]
        and broker_metrics.get("status") == "completed"
    )
    if full_nonmonthly_entries:
        status = "full_nonmonthly_entry_replacement_validated"
    elif daily_risk_engine_completed:
        status = "partial_daily_risk_overlay_validated"
    else:
        status = "blocked_missing_daily_risk_backtest"
    row = {
        "portfolio": portfolio,
        **target_profile,
        **metrics_subset(broker_metrics, "broker_ledger"),
        **metrics_subset(risk_metrics, "position_risk"),
        **metrics_subset(execution_metrics, "execution_policy"),
        "broker_daily_equity_rows": broker_equity_rows,
        "position_risk_daily_equity_rows": risk_equity_rows,
        "execution_policy_daily_equity_rows": execution_equity_rows,
        "risk_action_count": risk_action_count,
        "nonmonthly_risk_action_count": nonmonthly_risk_action_count,
        "daily_risk_engine_backtest_completed": daily_risk_engine_completed,
        "daily_risk_action_evidence": daily_risk_action_evidence,
        "full_nonmonthly_entry_replacement_validated": full_nonmonthly_entries,
        "operating_event_backtest_status": status,
    }
    return row, risk_evidence


def render_report(payload: dict[str, Any]) -> str:
    rows = payload.get("portfolios", [])
    lines = [
        "# Operating Event Backtest Verification",
        "",
        "This report separates daily risk-management evidence from full historical non-monthly entry/replacement evidence.",
        "",
        "| Portfolio | Status | Daily risk engine | Non-monthly risk actions | Full non-monthly entries | Target max decisions/month | Broker CAGR | Broker MaxDD |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {portfolio} | `{status}` | {risk_engine} | {risk_actions} | {full_entries} | {max_decisions} | {cagr:.2%} | {maxdd:.2%} |".format(
                portfolio=row.get("portfolio"),
                status=row.get("operating_event_backtest_status"),
                risk_engine=str(row.get("daily_risk_engine_backtest_completed")).lower(),
                risk_actions=int(row.get("nonmonthly_risk_action_count", 0)),
                full_entries=str(row.get("full_nonmonthly_entry_replacement_validated")).lower(),
                max_decisions=int(row.get("target_book_max_decisions_per_month", 0)),
                cagr=safe_float(row.get("broker_ledger_cagr")),
                maxdd=safe_float(row.get("broker_ledger_max_dd")),
            )
        )
    lines.extend(
        [
            "",
            "Interpretation:",
            "- `partial_daily_risk_overlay_validated` means daily/weekly risk exits or trims can be replayed through an account ledger, but entry/replacement targets are still sourced from monthly or latest operating target books.",
            "- `full_nonmonthly_entry_replacement_validated` requires target books with more than one decision date in at least one calendar month.",
            "- If non-monthly risk actions are zero, the engine path can still be valid, but the latest artifacts did not encounter an observable daily/weekly risk trigger.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for portfolio in PORTFOLIOS:
        row, risk_evidence = summarize_portfolio(latest_run, portfolio)
        rows.append(row)
        evidence.extend(risk_evidence)
    payload = {
        "status": "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest_run),
        "daily_risk_overlay_validated": all(bool(row.get("daily_risk_engine_backtest_completed")) for row in rows),
        "daily_risk_action_evidence_count": int(sum(int(row.get("nonmonthly_risk_action_count", 0)) for row in rows)),
        "full_nonmonthly_entry_replacement_validated": all(bool(row.get("full_nonmonthly_entry_replacement_validated")) for row in rows),
        "portfolios": rows,
        "outputs": {
            "summary_json": str(output_dir / "operating_event_backtest_summary.json"),
            "status_csv": str(output_dir / "portfolio_event_backtest_status.csv"),
            "nonmonthly_trade_evidence_csv": str(output_dir / "nonmonthly_trade_evidence.csv"),
            "report_md": str(output_dir / "operating_event_backtest_report.md"),
        },
    }
    write_json(output_dir / "operating_event_backtest_summary.json", payload)
    write_csv(output_dir / "portfolio_event_backtest_status.csv", rows)
    write_csv(output_dir / "nonmonthly_trade_evidence.csv", evidence)
    (output_dir / "operating_event_backtest_report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

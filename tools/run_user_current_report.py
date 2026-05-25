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
    if not current.empty and {"portfolio_kind", "row_type", "current_weight"}.issubset(current.columns):
        cash = current[current["row_type"].astype(str).str.lower().eq("cash")].copy()
        for _, row in cash.iterrows():
            out["by_portfolio"][str(row.get("portfolio_kind"))] = {
                "cash_weight": safe_float(row.get("current_weight")),
                "cash_value_usd": safe_float(row.get("current_value_usd")),
            }
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


def render_action_summary(status: str, reasons: list[str], metrics: dict[str, Any], cash: dict[str, Any]) -> str:
    lines = [
        "# User Current Action Summary",
        "",
        f"- action_status: `{status}`",
        f"- official_metric_mode: `{official_metric_mode(metrics) or 'missing'}`",
        f"- valid_for_production: `{production_valid(metrics)}`",
        f"- cash_policy_flag: `{cash.get('cash_policy_flag') or ''}`",
        "",
        "## Reasons",
        "",
    ]
    lines.extend([f"- {item}" for item in reasons] if reasons else ["- none"])
    lines.extend(
        [
            "",
            "## Operating Rules",
            "",
            "- This report shows current simulated broker-ledger holdings only.",
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
- Target recommendation books are not current holdings and are hidden by default.
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
    current.to_csv(output_dir / "01_current_holdings.csv", index=False)

    cash = build_cash_summary(latest_run, current)
    write_json(output_dir / "02_cash_summary.json", cash)

    period = pd.concat([portfolio_period_returns(latest_run), benchmark_period_returns(price_cache)], ignore_index=True)
    period.to_csv(output_dir / "03_period_returns.csv", index=False)
    benchmarks = period[period["series_type"].astype(str).eq("benchmark")].copy() if not period.empty else pd.DataFrame()
    benchmarks.to_csv(output_dir / "06_benchmark_comparison.csv", index=False)

    metrics = load_official_metrics(latest_run)
    write_json(output_dir / "04_official_metrics.json", metrics)

    status, reasons = build_action_summary(latest_run, metrics, cash)
    (output_dir / "05_action_summary.md").write_text(render_action_summary(status, reasons, metrics, cash), encoding="utf-8")
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

#!/usr/bin/env python3
"""Audit paper/live order-preview artifacts before any execution.

This tool is deliberately conservative. It does not place orders and it does
not change portfolio targets. It checks the account-ledger bridge for common
ways a realistic trading system can become unsafe:

- actionable files carrying forward-return/leakage columns
- stale or missing prices
- target weights that imply leverage or invalid caps
- order previews that buy before selling or spend more cash than available
- account states with negative cash, short positions, or date mismatches
- legacy executor paths that can bypass the new account-ledger preview
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_OUTPUT_DIR = "outputs/live_trading_safety"
FORWARD_EXACT = {
    "period_forward_return",
    "weighted_forward_return",
    "raw_period_forward_return",
    "raw_weighted_forward_return",
    "risk_adjusted_forward_return",
    "future_return",
    "forward_return",
}
FORWARD_PREFIXES = ("bench_r_",)
FORWARD_SUFFIXES = ("_forward_return",)
FORWARD_REGEXES = (re.compile(r"^r_\d+[mdy]$"),)
MAX_REASONABLE_PRICE_STALE_DAYS = 5


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


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
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


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


def normalize_ticker(value: Any) -> str:
    ticker = str(value or "").upper().strip()
    return "" if ticker in {"", "NAN"} else ticker


def banned_columns(columns: list[str]) -> list[str]:
    out: list[str] = []
    for col in columns:
        c = str(col)
        lower = c.lower()
        if (
            lower in FORWARD_EXACT
            or any(lower.startswith(prefix) for prefix in FORWARD_PREFIXES)
            or any(lower.endswith(suffix) for suffix in FORWARD_SUFFIXES)
            or any(pattern.match(lower) for pattern in FORWARD_REGEXES)
        ):
            out.append(c)
    return sorted(set(out))


def issue(rows: list[dict[str, Any]], severity: str, check_id: str, message: str, path: Path | str = "", details: dict[str, Any] | None = None) -> None:
    rows.append(
        {
            "severity": severity,
            "check_id": check_id,
            "message": message,
            "path": str(path),
            "details": json.dumps(details or {}, sort_keys=True, default=str),
        }
    )


def latest_known_date(*frames: pd.DataFrame) -> pd.Timestamp | None:
    dates: list[pd.Timestamp] = []
    for frame in frames:
        if frame.empty:
            continue
        for col in ["as_of_date", "date", "price_date", "account_state_as_of_date"]:
            if col not in frame.columns:
                continue
            vals = pd.to_datetime(frame[col], errors="coerce").dropna()
            if not vals.empty:
                dates.append(pd.Timestamp(vals.max()).normalize())
    return max(dates) if dates else None


def audit_target(
    *,
    latest_run: Path,
    portfolio: str,
    target_path: Path,
    issues: list[dict[str, Any]],
    max_weight_sum: float,
    max_single_weight: float,
) -> pd.DataFrame:
    target = read_csv(target_path)
    if target.empty:
        issue(issues, "error", f"{portfolio}_target_missing", "target portfolio is missing or empty", target_path)
        return target
    banned = banned_columns(list(target.columns))
    if banned:
        issue(issues, "error", f"{portfolio}_target_leakage_columns", "actionable target contains forward-return columns", target_path, {"columns": banned})
    if "ticker" not in target.columns:
        issue(issues, "error", f"{portfolio}_target_no_ticker", "target portfolio has no ticker column", target_path)
        return target
    weight_col = "target_weight" if "target_weight" in target.columns else "weight" if "weight" in target.columns else ""
    if not weight_col:
        issue(issues, "error", f"{portfolio}_target_no_weight", "target portfolio has no weight column", target_path)
        return target
    t = target.copy()
    if "rebalance_date" in t.columns:
        t["rebalance_date"] = pd.to_datetime(t["rebalance_date"], errors="coerce").dt.normalize()
        if t["rebalance_date"].notna().any():
            t = t[t["rebalance_date"].eq(t["rebalance_date"].max())].copy()
    if portfolio == "concentrated":
        for col, expected in {"target_stock_names": "3", "weighting_mode": "score_power", "active_rebalance_interval_months": "1"}.items():
            if col in t.columns:
                mask = t[col].astype(str).str.strip().eq(expected)
                if mask.any():
                    t = t[mask].copy()
    t["ticker_norm"] = t["ticker"].map(normalize_ticker)
    t["weight_norm"] = pd.to_numeric(t[weight_col], errors="coerce")
    t = t[(t["ticker_norm"] != "") & (t["ticker_norm"] != "CASH")].copy()
    if t["weight_norm"].isna().any() or (t["weight_norm"] < 0).any():
        issue(issues, "error", f"{portfolio}_target_invalid_weight", "target has NaN or negative weights", target_path)
    duplicated_tickers = sorted(t.loc[t["ticker_norm"].duplicated(keep=False), "ticker_norm"].unique().tolist())
    if duplicated_tickers:
        issue(issues, "error", f"{portfolio}_target_duplicate_ticker", "target has duplicate tickers after normalization", target_path, {"tickers": duplicated_tickers[:20]})
    grouped = t.groupby("ticker_norm", as_index=False)["weight_norm"].sum()
    weight_sum = float(grouped["weight_norm"].sum()) if not grouped.empty else 0.0
    max_weight = float(grouped["weight_norm"].max()) if not grouped.empty else 0.0
    if weight_sum > max_weight_sum:
        issue(issues, "error", f"{portfolio}_target_leverage", "target stock weights exceed allowed total exposure", target_path, {"weight_sum": weight_sum, "limit": max_weight_sum})
    if max_weight > max_single_weight:
        issue(issues, "error", f"{portfolio}_target_single_cap", "target single-name weight exceeds safety cap", target_path, {"max_weight": max_weight, "limit": max_single_weight})
    if grouped.empty:
        issue(issues, "warning", f"{portfolio}_target_no_stock", "target has no stock tickers after filtering", target_path)
    return grouped.rename(columns={"ticker_norm": "ticker", "weight_norm": "target_weight"})


def audit_account_preview(
    *,
    latest_run: Path,
    portfolio: str,
    issues: list[dict[str, Any]],
    target: pd.DataFrame,
    max_stale_days: int,
    max_order_notional_pct: float,
) -> None:
    preview_dir = latest_run / "account_ledger_preview" / portfolio
    metrics_path = preview_dir / "preview_metrics.json"
    metrics = read_json(metrics_path)
    if not metrics:
        issue(issues, "error", f"{portfolio}_preview_missing", "account order preview metrics missing", metrics_path)
        return
    if metrics.get("status") != "completed":
        issue(issues, "error", f"{portfolio}_preview_not_completed", "account order preview did not complete", metrics_path, {"status": metrics.get("status"), "reason": metrics.get("reason")})
    equity = safe_float(metrics.get("equity_usd"))
    cash = safe_float(metrics.get("cash_usd"))
    if equity is None or equity <= 0:
        issue(issues, "error", f"{portfolio}_preview_bad_equity", "preview equity is missing or non-positive", metrics_path, {"equity": equity})
    if cash is None:
        issue(issues, "error", f"{portfolio}_preview_missing_cash", "preview cash is missing", metrics_path)
    elif cash < -1e-6:
        issue(issues, "error", f"{portfolio}_preview_negative_cash", "preview account cash is negative", metrics_path, {"cash": cash})
    if bool(metrics.get("fractional_shares", False)):
        issue(issues, "warning", f"{portfolio}_fractional_flag_unknown", "fractional share handling should be explicitly reviewed before broker execution", metrics_path)

    orders_path = preview_dir / "orders_preview.csv"
    orders = read_csv(orders_path)
    positions_path = preview_dir / "positions_current.csv"
    positions = read_csv(positions_path)
    target_weights_path = preview_dir / "target_weights.csv"
    preview_target = read_csv(target_weights_path)
    for path, frame, check_id in [
        (orders_path, orders, "orders"),
        (positions_path, positions, "positions"),
        (target_weights_path, preview_target, "target_weights"),
    ]:
        banned = banned_columns(list(frame.columns)) if not frame.empty else []
        if banned:
            issue(issues, "error", f"{portfolio}_{check_id}_leakage_columns", f"{check_id} contains forward-return columns", path, {"columns": banned})

    if not positions.empty and "shares" in positions.columns:
        shares = pd.to_numeric(positions["shares"], errors="coerce")
        if shares.isna().any():
            issue(issues, "error", f"{portfolio}_position_bad_shares", "positions_current has non-numeric shares", positions_path)
        if (shares < -1e-12).any():
            issue(issues, "error", f"{portfolio}_position_short", "positions_current contains short shares", positions_path)
    if not positions.empty and "price_date" in positions.columns:
        as_of = pd.to_datetime(metrics.get("as_of_date"), errors="coerce")
        price_dates = pd.to_datetime(positions["price_date"], errors="coerce")
        stale = []
        for row, price_dt in zip(positions.to_dict("records"), price_dates):
            if pd.isna(price_dt):
                stale.append({"ticker": row.get("ticker"), "reason": "missing_price_date"})
                continue
            if pd.notna(as_of):
                lag = int((pd.Timestamp(as_of).normalize() - pd.Timestamp(price_dt).normalize()).days)
                if lag < 0:
                    stale.append({"ticker": row.get("ticker"), "lag_days": lag, "reason": "price_date_after_as_of"})
                elif lag > max_stale_days:
                    stale.append({"ticker": row.get("ticker"), "lag_days": lag, "reason": "stale_price"})
        if stale:
            issue(issues, "error", f"{portfolio}_stale_prices", "positions_current uses stale/mismatched prices", positions_path, {"examples": stale[:10], "max_stale_days": max_stale_days})

    if not target.empty and not positions.empty and "ticker" in positions.columns:
        target_tickers = set(target["ticker"].astype(str).str.upper()) - {"CASH"}
        position_tickers = set(positions["ticker"].astype(str).str.upper())
        missing = sorted(target_tickers - position_tickers)
        if missing:
            issue(issues, "error", f"{portfolio}_target_missing_price_rows", "some target tickers are absent from positions_current, usually missing price cache", positions_path, {"missing": missing[:20]})

    if orders.empty:
        return
    if "side" not in orders.columns or "quantity" not in orders.columns:
        issue(issues, "error", f"{portfolio}_orders_bad_schema", "orders_preview missing side or quantity", orders_path)
        return
    sides = orders["side"].astype(str).str.upper().tolist()
    first_buy_idx = next((i for i, side in enumerate(sides) if side == "BUY"), None)
    last_sell_idx = max([i for i, side in enumerate(sides) if side == "SELL"], default=-1)
    if first_buy_idx is not None and last_sell_idx > first_buy_idx:
        issue(issues, "error", f"{portfolio}_orders_not_sell_first", "orders must be sorted sell-first before buys", orders_path)
    qty = pd.to_numeric(orders["quantity"], errors="coerce").fillna(-1)
    if (qty <= 0).any():
        issue(issues, "error", f"{portfolio}_orders_nonpositive_qty", "orders contain non-positive quantities", orders_path)
    if "status" in orders.columns:
        blocked = orders[orders["status"].astype(str).str.startswith("blocked", na=False)]
        if not blocked.empty:
            issue(issues, "error", f"{portfolio}_orders_blocked", "orders_preview contains blocked orders", orders_path, {"count": int(len(blocked))})
    if "estimated_cash_after_usd" in orders.columns:
        min_cash_after = safe_float(pd.to_numeric(orders["estimated_cash_after_usd"], errors="coerce").min())
        if min_cash_after is not None and min_cash_after < -1e-6:
            issue(issues, "error", f"{portfolio}_orders_negative_cash_after", "orders would drive cash negative", orders_path, {"min_cash_after": min_cash_after})
    if equity and "gross_value_usd" in orders.columns:
        gross = pd.to_numeric(orders["gross_value_usd"], errors="coerce").fillna(0.0)
        max_gross = float(gross.max()) if len(gross) else 0.0
        if max_gross > float(equity) * float(max_order_notional_pct):
            issue(issues, "warning", f"{portfolio}_large_order", "single order exceeds review threshold", orders_path, {"max_gross": max_gross, "equity": equity, "limit_pct": max_order_notional_pct})


def audit_legacy_executor(issues: list[dict[str, Any]]) -> None:
    paper = REPO_ROOT / "r1000_paper_executor.py"
    if not paper.exists():
        return
    src = paper.read_text(encoding="utf-8", errors="replace")
    required = [
        "--execute",
        "--confirm",
        "HALT_NEW",
        "override-regime-halt",
        "skip-regime-check",
        "allow-deprecated-v4",
        "allow-legacy-execute",
    ]
    missing = [token for token in required if token not in src]
    if missing:
        issue(issues, "error", "legacy_executor_guard_missing", "legacy paper executor is missing safety guard markers", paper, {"missing": missing})


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Live Trading Safety Audit",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Error count: {payload.get('error_count')}",
        f"- Warning count: {payload.get('warning_count')}",
        "",
        "This audit is pre-trade only. It does not place broker orders.",
        "",
    ]
    issues = payload.get("issues") or []
    if not issues:
        lines.append("No issues found.")
        lines.append("")
        return "\n".join(lines)
    lines.extend(["| Severity | Check | Message | Path |", "| --- | --- | --- | --- |"])
    for row in issues:
        lines.append(f"| {row.get('severity')} | `{row.get('check_id')}` | {row.get('message')} | `{row.get('path')}` |")
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    issues: list[dict[str, Any]] = []
    main_target = audit_target(
        latest_run=latest_run,
        portfolio="main",
        target_path=latest_run / "portfolio_latest.csv",
        issues=issues,
        max_weight_sum=args.main_max_weight_sum,
        max_single_weight=args.main_max_single_weight,
    )
    concentrated_target = audit_target(
        latest_run=latest_run,
        portfolio="concentrated",
        target_path=latest_run / "concentrated_portfolio_latest.csv",
        issues=issues,
        max_weight_sum=args.concentrated_max_weight_sum,
        max_single_weight=args.concentrated_max_single_weight,
    )
    audit_account_preview(
        latest_run=latest_run,
        portfolio="main",
        issues=issues,
        target=main_target,
        max_stale_days=args.max_stale_days,
        max_order_notional_pct=args.main_max_order_notional_pct,
    )
    audit_account_preview(
        latest_run=latest_run,
        portfolio="concentrated",
        issues=issues,
        target=concentrated_target,
        max_stale_days=args.max_stale_days,
        max_order_notional_pct=args.concentrated_max_order_notional_pct,
    )
    audit_legacy_executor(issues)
    error_count = sum(1 for row in issues if row.get("severity") == "error")
    warning_count = sum(1 for row in issues if row.get("severity") == "warning")
    payload = {
        "status": "pass" if error_count == 0 else "blocked",
        "latest_run": str(latest_run),
        "schema_version": "live-trading-safety-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "error_count": error_count,
        "warning_count": warning_count,
        "issues": issues,
        "strict": bool(args.strict),
    }
    write_json(output_dir / "safety_audit_summary.json", payload)
    write_csv(output_dir / "safety_audit_issues.csv", issues, ["severity", "check_id", "message", "path", "details"])
    (output_dir / "safety_audit_report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-stale-days", type=int, default=MAX_REASONABLE_PRICE_STALE_DAYS)
    parser.add_argument("--main-max-weight-sum", type=float, default=1.05)
    parser.add_argument("--main-max-single-weight", type=float, default=0.33)
    parser.add_argument("--main-max-order-notional-pct", type=float, default=0.35)
    parser.add_argument("--concentrated-max-weight-sum", type=float, default=1.05)
    parser.add_argument("--concentrated-max-single-weight", type=float, default=0.50)
    parser.add_argument("--concentrated-max-order-notional-pct", type=float, default=0.60)
    parser.add_argument("--strict", action="store_true", help="return non-zero when any error is found")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(args)
    print(json.dumps({"status": payload["status"], "error_count": payload["error_count"], "warning_count": payload["warning_count"]}, indent=2))
    return 2 if args.strict and payload.get("status") != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())

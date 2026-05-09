#!/usr/bin/env python3
"""Generate live/paper trading risk controls from account-ledger previews.

This tool is still preview-only: it does not call a broker and it does not
place, cancel, or modify orders. It creates the operational artifacts that
should exist before any paper/live order submission:

- order manifests with deterministic client_order_id values
- duplicate-order/idempotency checks against prior manifests
- optional broker snapshot reconciliation
- optional open-order conflict and cash-reservation checks
- as-of/freshness and corporate-action anomaly checks
- fill reconciliation templates for partial/no-fill handling
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

from tools.run_weekly_evaluation import load_price_series


DEFAULT_OUTPUT_DIR = "outputs/live_trading_risk_controls"
PORTFOLIOS = ("main", "concentrated")


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


def broker_file(snapshot_dir: Path, portfolio: str, filename: str) -> Path:
    nested = snapshot_dir / portfolio / filename
    if nested.exists():
        return nested
    return snapshot_dir / f"{portfolio}_{filename}"


def read_previous_manifest(path: Path) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    if path.is_file():
        return read_csv(path)
    if path.is_dir():
        frames: list[pd.DataFrame] = []
        for csv_path in path.rglob("order_manifest.csv"):
            frame = read_csv(csv_path)
            if not frame.empty:
                frames.append(frame)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return pd.DataFrame()


def normalize_order_frame(orders: pd.DataFrame) -> pd.DataFrame:
    if orders.empty:
        return pd.DataFrame()
    out = orders.copy()
    for col in ["ticker", "side", "status", "client_order_id"]:
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].astype(str)
    out["ticker"] = out["ticker"].map(normalize_ticker)
    out["side"] = out["side"].str.upper().str.strip()
    for col in ["quantity", "gross_value_usd", "estimated_fee_usd", "cash_impact_usd", "reference_price", "limit_price"]:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    return out


def make_order_manifest(
    *,
    latest_run: Path,
    portfolio: str,
    preview_dir: Path,
    issues: list[dict[str, Any]],
    previous_manifest: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    orders_path = preview_dir / "orders_preview.csv"
    metrics_path = preview_dir / "preview_metrics.json"
    orders = normalize_order_frame(read_csv(orders_path))
    metrics = read_json(metrics_path)
    if orders.empty:
        return [], []
    if "client_order_id" not in orders.columns or orders["client_order_id"].astype(str).str.strip().eq("").any():
        issue(issues, "error", f"{portfolio}_missing_client_order_id", "orders must have deterministic client_order_id before execution", orders_path)
    dupes = sorted(orders.loc[orders["client_order_id"].duplicated(keep=False), "client_order_id"].astype(str).unique().tolist())
    if dupes:
        issue(issues, "error", f"{portfolio}_duplicate_client_order_id", "orders contain duplicate client_order_id values", orders_path, {"examples": dupes[:10]})

    previous_ids: set[str] = set()
    if not previous_manifest.empty and "client_order_id" in previous_manifest.columns:
        prev = previous_manifest.copy()
        if "lifecycle_status" in prev.columns:
            active_mask = ~prev["lifecycle_status"].astype(str).str.lower().isin({"filled", "cancelled", "canceled", "expired", "rejected"})
            prev = prev[active_mask]
        previous_ids = set(prev["client_order_id"].astype(str))
    overlap = sorted(set(orders["client_order_id"].astype(str)) & previous_ids)
    if overlap:
        issue(issues, "error", f"{portfolio}_duplicate_prior_manifest", "planned orders overlap a previous active manifest", orders_path, {"client_order_ids": overlap[:20]})

    rows: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    as_of = str(metrics.get("as_of_date") or "")
    batch = str(metrics.get("order_batch_id") or "")
    for row in orders.to_dict("records"):
        status = str(row.get("status", ""))
        executable = status in {"ready", "cash_scaled"}
        manifest_row = {
            "portfolio": portfolio,
            "as_of_date": as_of,
            "order_batch_id": batch,
            "client_order_id": row.get("client_order_id", ""),
            "ticker": row.get("ticker", ""),
            "side": row.get("side", ""),
            "quantity": row.get("quantity", 0.0),
            "reference_price": row.get("reference_price", 0.0),
            "limit_price": row.get("limit_price", 0.0),
            "gross_value_usd": row.get("gross_value_usd", 0.0),
            "estimated_fee_usd": row.get("estimated_fee_usd", 0.0),
            "cash_impact_usd": row.get("cash_impact_usd", 0.0),
            "preview_status": status,
            "lifecycle_status": "planned" if executable else "blocked",
            "source_orders_preview": str(orders_path),
        }
        rows.append(manifest_row)
        if executable:
            fills.append(
                {
                    "portfolio": portfolio,
                    "client_order_id": row.get("client_order_id", ""),
                    "broker_order_id": "",
                    "ticker": row.get("ticker", ""),
                    "side": row.get("side", ""),
                    "submitted_qty": row.get("quantity", 0.0),
                    "filled_qty": "",
                    "remaining_qty": "",
                    "avg_fill_price": "",
                    "fees_usd": "",
                    "fill_status": "pending",
                    "submitted_at": "",
                    "last_update_at": "",
                    "notes": "",
                }
            )
    return rows, fills


def audit_open_orders(
    *,
    snapshot_dir: Path | None,
    portfolio: str,
    planned: pd.DataFrame,
    issues: list[dict[str, Any]],
    strict_live: bool,
) -> float:
    if snapshot_dir is None:
        return 0.0
    path = broker_file(snapshot_dir, portfolio, "open_orders.csv")
    open_orders = read_csv(path)
    if open_orders.empty:
        if strict_live:
            issue(issues, "error", f"{portfolio}_open_orders_missing", "strict live mode requires broker open_orders.csv snapshot", path)
        else:
            issue(issues, "warning", f"{portfolio}_open_orders_missing", "open order snapshot missing; duplicate broker orders cannot be ruled out", path)
        return 0.0
    for col in ["ticker", "side", "status"]:
        if col not in open_orders.columns:
            open_orders[col] = ""
        open_orders[col] = open_orders[col].astype(str)
    open_orders["ticker"] = open_orders["ticker"].map(normalize_ticker)
    open_orders["side"] = open_orders["side"].str.upper().str.strip()
    for col in ["quantity", "remaining_qty", "limit_price", "gross_value_usd"]:
        if col not in open_orders.columns:
            open_orders[col] = 0.0
        open_orders[col] = pd.to_numeric(open_orders[col], errors="coerce").fillna(0.0)
    planned_pairs = set(zip(planned.get("ticker", pd.Series(dtype=str)).astype(str), planned.get("side", pd.Series(dtype=str)).astype(str)))
    conflicts = []
    reserved = 0.0
    for row in open_orders.to_dict("records"):
        pair = (row.get("ticker", ""), row.get("side", ""))
        status = str(row.get("status", "")).lower()
        if status in {"filled", "cancelled", "canceled", "expired", "rejected"}:
            continue
        if pair in planned_pairs:
            conflicts.append({"ticker": pair[0], "side": pair[1], "status": status})
        if pair[1] == "BUY":
            gross = safe_float(row.get("gross_value_usd"), 0.0) or 0.0
            if gross <= 0:
                qty = safe_float(row.get("remaining_qty"), safe_float(row.get("quantity"), 0.0)) or 0.0
                px = safe_float(row.get("limit_price"), 0.0) or 0.0
                gross = qty * px
            reserved += gross
    if conflicts:
        issue(issues, "error", f"{portfolio}_open_order_conflict", "planned orders overlap existing broker open orders", path, {"examples": conflicts[:20]})
    return float(reserved)


def audit_broker_reconciliation(
    *,
    snapshot_dir: Path | None,
    portfolio: str,
    preview_dir: Path,
    issues: list[dict[str, Any]],
    strict_live: bool,
    share_tolerance: float,
    cash_tolerance_usd: float,
    equity_tolerance_pct: float,
) -> None:
    if snapshot_dir is None:
        return
    account_path = broker_file(snapshot_dir, portfolio, "broker_account.json")
    positions_path = broker_file(snapshot_dir, portfolio, "broker_positions.csv")
    broker_account = read_json(account_path)
    broker_positions = read_csv(positions_path)
    if not broker_account:
        severity = "error" if strict_live else "warning"
        issue(issues, severity, f"{portfolio}_broker_account_missing", "broker account snapshot missing", account_path)
    if broker_positions.empty:
        severity = "error" if strict_live else "warning"
        issue(issues, severity, f"{portfolio}_broker_positions_missing", "broker position snapshot missing", positions_path)
        return
    current = read_csv(preview_dir / "positions_current.csv")
    if current.empty:
        issue(issues, "error", f"{portfolio}_internal_positions_missing", "internal positions_current.csv missing", preview_dir / "positions_current.csv")
        return
    for frame in [current, broker_positions]:
        if "ticker" not in frame.columns:
            frame["ticker"] = ""
        if "shares" not in frame.columns:
            frame["shares"] = 0.0
        frame["ticker"] = frame["ticker"].map(normalize_ticker)
        frame["shares"] = pd.to_numeric(frame["shares"], errors="coerce").fillna(0.0)
    current_map = current.groupby("ticker")["shares"].sum().to_dict()
    broker_map = broker_positions.groupby("ticker")["shares"].sum().to_dict()
    mismatches = []
    for ticker in sorted(set(current_map) | set(broker_map)):
        diff = float(broker_map.get(ticker, 0.0) - current_map.get(ticker, 0.0))
        if abs(diff) > float(share_tolerance):
            mismatches.append({"ticker": ticker, "internal_shares": current_map.get(ticker, 0.0), "broker_shares": broker_map.get(ticker, 0.0), "diff": diff})
    if mismatches:
        issue(issues, "error", f"{portfolio}_broker_position_mismatch", "broker positions differ from internal account state", positions_path, {"examples": mismatches[:20]})

    metrics = read_json(preview_dir / "preview_metrics.json")
    broker_cash = safe_float(broker_account.get("cash_usd"), None)
    internal_cash = safe_float(metrics.get("cash_usd"), None)
    if broker_cash is not None and internal_cash is not None and abs(broker_cash - internal_cash) > float(cash_tolerance_usd):
        issue(issues, "error", f"{portfolio}_broker_cash_mismatch", "broker cash differs from internal preview cash", account_path, {"broker_cash": broker_cash, "internal_cash": internal_cash})
    broker_equity = safe_float(broker_account.get("equity_usd"), None)
    internal_equity = safe_float(metrics.get("equity_usd"), None)
    if broker_equity is not None and internal_equity and internal_equity > 0:
        drift = abs(broker_equity - internal_equity) / internal_equity
        if drift > float(equity_tolerance_pct):
            issue(issues, "error", f"{portfolio}_broker_equity_mismatch", "broker equity differs from internal preview equity", account_path, {"broker_equity": broker_equity, "internal_equity": internal_equity, "drift": drift})


def audit_as_of_and_corporate_actions(
    *,
    preview_dir: Path,
    price_cache: Path,
    portfolio: str,
    issues: list[dict[str, Any]],
    max_stale_days: int,
    corporate_action_jump_pct: float,
) -> None:
    metrics = read_json(preview_dir / "preview_metrics.json")
    as_of = pd.to_datetime(metrics.get("as_of_date"), errors="coerce")
    if pd.isna(as_of):
        issue(issues, "error", f"{portfolio}_missing_as_of_date", "preview metrics missing valid as_of_date", preview_dir / "preview_metrics.json")
        return
    as_of = pd.Timestamp(as_of).normalize()
    if as_of.weekday() >= 5:
        issue(issues, "warning", f"{portfolio}_as_of_weekend", "preview as_of_date is a weekend; verify market-close date", preview_dir / "preview_metrics.json", {"as_of_date": as_of.date().isoformat()})
    today_utc = pd.Timestamp.utcnow().tz_localize(None).normalize()
    if as_of > today_utc:
        issue(issues, "error", f"{portfolio}_as_of_future", "preview as_of_date is in the future", preview_dir / "preview_metrics.json", {"as_of_date": as_of.date().isoformat()})
    elif (today_utc - as_of).days > int(max_stale_days):
        issue(issues, "error", f"{portfolio}_as_of_stale", "preview as_of_date is too stale for live/paper execution", preview_dir / "preview_metrics.json", {"as_of_date": as_of.date().isoformat(), "max_stale_days": max_stale_days})

    positions = read_csv(preview_dir / "positions_current.csv")
    if positions.empty or "ticker" not in positions.columns:
        return
    positions["ticker"] = positions["ticker"].map(normalize_ticker)
    for row in positions.to_dict("records"):
        ticker = row.get("ticker", "")
        if not ticker:
            continue
        px = load_price_series(price_cache, ticker)
        if px.empty or len(px) < 2:
            continue
        recent = px.sort_index().tail(2)
        closes = pd.to_numeric(recent["close"], errors="coerce").dropna() if "close" in recent.columns else pd.Series(dtype=float)
        if len(closes) < 2:
            continue
        prev_px = float(closes.iloc[-2])
        last_px = float(closes.iloc[-1])
        if prev_px <= 0:
            continue
        move = (last_px / prev_px) - 1.0
        if abs(move) >= float(corporate_action_jump_pct):
            issue(
                issues,
                "warning",
                f"{portfolio}_large_price_jump_review",
                "large latest price jump may require split/corporate-action or news review before trading",
                price_cache / f"{ticker}.parquet",
                {"ticker": ticker, "prev_close": prev_px, "last_close": last_px, "one_day_move": move},
            )
        cost_basis = safe_float(row.get("cost_basis"), None)
        current_price = safe_float(row.get("price"), None)
        if cost_basis and current_price and cost_basis > 0:
            ratio = current_price / cost_basis
            if ratio >= 4.0 or ratio <= 0.25:
                issue(
                    issues,
                    "warning",
                    f"{portfolio}_cost_basis_price_ratio_review",
                    "current price versus stored cost basis is extreme; verify splits, transfers, and cost basis before execution",
                    preview_dir / "positions_current.csv",
                    {"ticker": ticker, "price": current_price, "cost_basis": cost_basis, "ratio": ratio},
                )


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Live Trading Risk Controls",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Error count: {payload.get('error_count')}",
        f"- Warning count: {payload.get('warning_count')}",
        f"- Manifest orders: {payload.get('manifest_order_count')}",
        "",
        "This is preview/reconciliation only. It does not submit broker orders.",
        "",
    ]
    issues = payload.get("issues") or []
    if issues:
        lines.extend(["| Severity | Check | Message | Path |", "| --- | --- | --- | --- |"])
        for row in issues:
            lines.append(f"| {row.get('severity')} | `{row.get('check_id')}` | {row.get('message')} | `{row.get('path')}` |")
        lines.append("")
    else:
        lines.append("No issues found.")
        lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    price_cache = repo_path(args.price_cache)
    snapshot_dir = repo_path(args.broker_snapshot_dir) if args.broker_snapshot_dir else None
    previous_manifest = read_previous_manifest(repo_path(args.previous_manifest)) if args.previous_manifest else pd.DataFrame()
    issues: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    fill_rows: list[dict[str, Any]] = []
    if bool(args.strict_live) and snapshot_dir is None:
        issue(issues, "error", "broker_snapshot_required", "strict live mode requires --broker-snapshot-dir for account/open-order reconciliation")
    elif snapshot_dir is None:
        issue(issues, "warning", "broker_snapshot_not_supplied", "broker snapshot not supplied; account/open-order reconciliation was skipped")

    for portfolio in PORTFOLIOS:
        preview_dir = latest_run / "account_ledger_preview" / portfolio
        rows, fills = make_order_manifest(
            latest_run=latest_run,
            portfolio=portfolio,
            preview_dir=preview_dir,
            issues=issues,
            previous_manifest=previous_manifest,
        )
        manifest_rows.extend(rows)
        fill_rows.extend(fills)
        planned = pd.DataFrame(rows)
        reserved_buy_cash = audit_open_orders(
            snapshot_dir=snapshot_dir,
            portfolio=portfolio,
            planned=planned,
            issues=issues,
            strict_live=bool(args.strict_live),
        )
        if reserved_buy_cash > 0:
            issue(issues, "warning", f"{portfolio}_open_order_cash_reserved", "existing open buy orders reserve cash outside this preview", snapshot_dir, {"reserved_buy_cash_usd": reserved_buy_cash})
        audit_broker_reconciliation(
            snapshot_dir=snapshot_dir,
            portfolio=portfolio,
            preview_dir=preview_dir,
            issues=issues,
            strict_live=bool(args.strict_live),
            share_tolerance=float(args.share_tolerance),
            cash_tolerance_usd=float(args.cash_tolerance_usd),
            equity_tolerance_pct=float(args.equity_tolerance_pct),
        )
        audit_as_of_and_corporate_actions(
            preview_dir=preview_dir,
            price_cache=price_cache,
            portfolio=portfolio,
            issues=issues,
            max_stale_days=int(args.max_stale_days),
            corporate_action_jump_pct=float(args.corporate_action_jump_pct),
        )

    write_csv(
        output_dir / "order_manifest.csv",
        manifest_rows,
        [
            "portfolio",
            "as_of_date",
            "order_batch_id",
            "client_order_id",
            "ticker",
            "side",
            "quantity",
            "reference_price",
            "limit_price",
            "gross_value_usd",
            "estimated_fee_usd",
            "cash_impact_usd",
            "preview_status",
            "lifecycle_status",
            "source_orders_preview",
        ],
    )
    write_csv(
        output_dir / "fill_reconciliation_template.csv",
        fill_rows,
        [
            "portfolio",
            "client_order_id",
            "broker_order_id",
            "ticker",
            "side",
            "submitted_qty",
            "filled_qty",
            "remaining_qty",
            "avg_fill_price",
            "fees_usd",
            "fill_status",
            "submitted_at",
            "last_update_at",
            "notes",
        ],
    )
    error_count = sum(1 for row in issues if row.get("severity") == "error")
    warning_count = sum(1 for row in issues if row.get("severity") == "warning")
    payload = {
        "status": "pass" if error_count == 0 else "blocked",
        "schema_version": "live-trading-risk-controls-v1",
        "latest_run": str(latest_run),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "strict_live": bool(args.strict_live),
        "error_count": int(error_count),
        "warning_count": int(warning_count),
        "manifest_order_count": int(len(manifest_rows)),
        "fill_template_order_count": int(len(fill_rows)),
        "issues": issues,
    }
    write_json(output_dir / "risk_controls_summary.json", payload)
    write_csv(output_dir / "risk_controls_issues.csv", issues, ["severity", "check_id", "message", "path", "details"])
    (output_dir / "risk_controls_report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--broker-snapshot-dir", default="")
    parser.add_argument("--previous-manifest", default="")
    parser.add_argument("--strict-live", action="store_true")
    parser.add_argument("--max-stale-days", type=int, default=5)
    parser.add_argument("--share-tolerance", type=float, default=1e-8)
    parser.add_argument("--cash-tolerance-usd", type=float, default=5.0)
    parser.add_argument("--equity-tolerance-pct", type=float, default=0.005)
    parser.add_argument("--corporate-action-jump-pct", type=float, default=0.50)
    parser.add_argument("--strict", action="store_true", help="return non-zero when blocked")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(args)
    print(json.dumps({"status": payload["status"], "error_count": payload["error_count"], "warning_count": payload["warning_count"]}, indent=2))
    return 2 if args.strict and payload.get("status") != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())

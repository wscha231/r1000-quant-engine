#!/usr/bin/env python3
"""Review tiny current positions and projected cleanup weights.

This is an operator-review sidecar. It never writes production target books or
trade instructions.
"""
from __future__ import annotations

import argparse
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


CASH_TICKERS = {"CASH", "__CASH__"}
PROTECTED_STATES = {"HOLD", "SHAKEOUT_GUARD"}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


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


def current_holdings(latest_run: Path) -> pd.DataFrame:
    for path in [
        latest_run / "operating_snapshot" / "current_operating_holdings_latest.csv",
        latest_run / "user_current" / "01_current_holdings.csv",
        latest_run / "user_portfolio_reports" / "main_current_operating_holdings_latest.csv",
    ]:
        frame = read_csv(path)
        if not frame.empty:
            return frame
    return pd.DataFrame()


def latest_targets(latest_run: Path, portfolio_kind: str) -> pd.DataFrame:
    path = latest_run / ("concentrated_portfolio_latest.csv" if portfolio_kind == "concentrated" else "portfolio_latest.csv")
    frame = read_csv(path)
    if frame.empty:
        book = latest_run / "reports" / (
            "operating_concentrated_target_book.csv" if portfolio_kind == "concentrated" else "operating_main_target_book.csv"
        )
        frame = read_csv(book)
        if not frame.empty and "rebalance_date" in frame.columns:
            dates = pd.to_datetime(frame["rebalance_date"], errors="coerce")
            latest = dates.max()
            frame = frame[dates.eq(latest)].copy()
    if frame.empty:
        return pd.DataFrame(columns=["ticker", "target_weight"])
    out = frame.copy()
    out["ticker"] = out.get("ticker", "").map(clean_ticker) if "ticker" in out.columns else ""
    weight_col = "target_weight" if "target_weight" in out.columns else "weight" if "weight" in out.columns else ""
    out["target_weight"] = pd.to_numeric(out[weight_col], errors="coerce").fillna(0.0) if weight_col else 0.0
    return out[["ticker", "target_weight"]].groupby("ticker", as_index=False)["target_weight"].sum()


def protected_state(row: dict[str, Any]) -> bool:
    values = [
        row.get("leader_state"),
        row.get("winner_state"),
        row.get("daily_review_action"),
        row.get("risk_state"),
        row.get("approval_status"),
    ]
    haystack = " ".join(str(x or "").upper() for x in values)
    return any(token in haystack for token in PROTECTED_STATES)


def position_state(row: dict[str, Any]) -> str:
    for key in ("leader_state", "winner_state", "daily_review_action", "risk_state", "approval_status"):
        text = str(row.get(key) or "").strip()
        if text:
            return text
    return ""


def normalize_current(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["portfolio_kind", "ticker", "current_weight"])
    out = frame.copy()
    if "portfolio_kind" not in out.columns:
        out["portfolio_kind"] = "main"
    if "ticker" not in out.columns:
        out["ticker"] = ""
    out["ticker"] = out["ticker"].map(clean_ticker)
    if "current_weight" not in out.columns:
        weight_col = "weight" if "weight" in out.columns else ""
        out["current_weight"] = pd.to_numeric(out[weight_col], errors="coerce").fillna(0.0) if weight_col else 0.0
    out["current_weight"] = pd.to_numeric(out["current_weight"], errors="coerce").fillna(0.0)
    if "current_shares" not in out.columns:
        out["current_shares"] = out.get("shares", 0.0)
    if "current_value_usd" not in out.columns:
        out["current_value_usd"] = out.get("market_value_usd", 0.0)
    return out


def action_for(row: dict[str, Any], *, main_dust: float, main_min: float, emerging_min: float, concentrated_min: float) -> tuple[str, str, float]:
    portfolio = str(row.get("portfolio_kind") or "main")
    ticker = clean_ticker(row.get("ticker"))
    current_w = safe_float(row.get("current_weight"))
    target_w = safe_float(row.get("target_weight"))
    if ticker in CASH_TICKERS:
        return "CASH_NO_ACTION", "cash row", current_w
    min_target = concentrated_min if portfolio == "concentrated" else emerging_min if bool(row.get("is_emerging_seat")) else main_min
    if protected_state(row):
        return "HOLD_REVIEW", "protected HOLD/SHAKEOUT state", max(current_w, target_w)
    if portfolio == "main" and current_w < main_dust and target_w < main_dust:
        return "FULL_EXIT_REVIEW", "main dust current<0.50% and target<0.50%", 0.0
    if portfolio == "concentrated" and current_w < concentrated_min and target_w < concentrated_min:
        return "FULL_EXIT_REVIEW", "concentrated position below minimum meaningful weight", 0.0
    if target_w <= 0.0 and current_w > 0.0:
        return "FULL_EXIT_REVIEW", "no current production target weight", 0.0
    if 0.0 < target_w < min_target:
        return "TARGET_BELOW_MIN_REVIEW", f"target weight below minimum {min_target:.2%}", target_w
    if target_w >= min_target and current_w + 1e-9 < target_w:
        return "INCREASE_TO_MEANINGFUL_WEIGHT_REVIEW", "target is meaningful and current is under target", target_w
    if current_w > target_w + main_dust and target_w > 0.0:
        return "TRIM_REVIEW", "current weight materially above target", target_w
    return "HOLD_REVIEW", "current weight already aligned enough for review", current_w if target_w <= 0.0 else target_w


def build_review(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    current = normalize_current(current_holdings(latest_run))
    target_by_portfolio = {
        "main": latest_targets(latest_run, "main"),
        "concentrated": latest_targets(latest_run, "concentrated"),
    }
    target_maps = {
        portfolio: dict(zip(frame["ticker"], frame["target_weight"])) if not frame.empty else {}
        for portfolio, frame in target_by_portfolio.items()
    }

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for rec in current.to_dict("records"):
        portfolio = str(rec.get("portfolio_kind") or "main")
        if portfolio not in target_maps:
            portfolio = "main"
        ticker = clean_ticker(rec.get("ticker"))
        if not ticker:
            continue
        row = dict(rec)
        row["portfolio_kind"] = portfolio
        row["ticker"] = ticker
        row["target_weight"] = safe_float(target_maps.get(portfolio, {}).get(ticker, 0.0))
        row["position_state"] = position_state(row)
        row["is_emerging_seat"] = "EMERGING" in str(row.get("entry_sleeves") or row.get("entry_reasons") or "").upper()
        action, reason, projected = action_for(
            row,
            main_dust=args.main_dust_threshold,
            main_min=args.main_min_target_weight,
            emerging_min=args.emerging_min_target_weight,
            concentrated_min=args.concentrated_min_target_weight,
        )
        row["cleanup_action"] = action
        row["cleanup_reason"] = reason
        row["projected_weight_after_cleanup_review"] = projected
        row["operator_review_only"] = True
        rows.append(row)
        seen.add((portfolio, ticker))

    for portfolio, frame in target_by_portfolio.items():
        for rec in frame.to_dict("records"):
            ticker = clean_ticker(rec.get("ticker"))
            if not ticker or ticker in CASH_TICKERS or (portfolio, ticker) in seen:
                continue
            target_w = safe_float(rec.get("target_weight"))
            min_target = args.concentrated_min_target_weight if portfolio == "concentrated" else args.main_min_target_weight
            action = "NEW_POSITION_REVIEW" if target_w >= min_target else "TARGET_BELOW_MIN_REVIEW"
            rows.append(
                {
                    "portfolio_kind": portfolio,
                    "ticker": ticker,
                    "current_weight": 0.0,
                    "current_shares": 0.0,
                    "current_value_usd": 0.0,
                    "target_weight": target_w,
                    "position_state": "",
                    "is_emerging_seat": False,
                    "cleanup_action": action,
                    "cleanup_reason": "target-only position from production target",
                    "projected_weight_after_cleanup_review": target_w,
                    "operator_review_only": True,
                }
            )

    report = pd.DataFrame(rows)
    if report.empty:
        report = pd.DataFrame(
            columns=[
                "portfolio_kind",
                "ticker",
                "current_weight",
                "target_weight",
                "cleanup_action",
                "cleanup_reason",
                "projected_weight_after_cleanup_review",
                "operator_review_only",
            ]
        )
    report.to_csv(output_dir / "dust_positions_report.csv", index=False)
    orders = report[report["cleanup_action"].astype(str).isin(["FULL_EXIT_REVIEW", "INCREASE_TO_MEANINGFUL_WEIGHT_REVIEW", "TRIM_REVIEW", "NEW_POSITION_REVIEW"])].copy()
    orders.to_csv(output_dir / "dust_cleanup_orders.csv", index=False)
    projected = report[
        [
            col
            for col in [
                "portfolio_kind",
                "ticker",
                "current_weight",
                "target_weight",
                "cleanup_action",
                "cleanup_reason",
                "projected_weight_after_cleanup_review",
            ]
            if col in report.columns
        ]
    ].copy()
    projected.to_csv(output_dir / "projected_holdings_after_ready_orders.csv", index=False)
    payload = {
        "schema_version": "position-cleanup-review-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "latest_run": str(latest_run),
        "main_dust_threshold": args.main_dust_threshold,
        "main_min_target_weight": args.main_min_target_weight,
        "emerging_min_target_weight": args.emerging_min_target_weight,
        "concentrated_min_target_weight": args.concentrated_min_target_weight,
        "row_count": int(len(report)),
        "full_exit_review_count": int(report["cleanup_action"].astype(str).eq("FULL_EXIT_REVIEW").sum()),
        "increase_review_count": int(report["cleanup_action"].astype(str).eq("INCREASE_TO_MEANINGFUL_WEIGHT_REVIEW").sum()),
        "order_review_count": int(len(orders)),
        "outputs": {
            "dust_positions_report": str(output_dir / "dust_positions_report.csv"),
            "dust_cleanup_orders": str(output_dir / "dust_cleanup_orders.csv"),
            "projected_holdings_after_ready_orders": str(output_dir / "projected_holdings_after_ready_orders.csv"),
        },
    }
    write_json(output_dir / "position_cleanup_review.json", payload)
    (output_dir / "position_cleanup_review.md").write_text(render_markdown(payload, report), encoding="utf-8")
    return payload


def pct(value: Any) -> str:
    return f"{safe_float(value):.2%}"


def render_markdown(payload: dict[str, Any], report: pd.DataFrame) -> str:
    lines = [
        "# Position Cleanup Review",
        "",
        "Operator-review only. This file does not place orders or change production target books.",
        "",
        f"- Full exit reviews: `{payload.get('full_exit_review_count')}`",
        f"- Meaningful increase reviews: `{payload.get('increase_review_count')}`",
        "",
        "| Portfolio | Ticker | Current | Target | Action | Reason | Projected |",
        "| --- | --- | ---: | ---: | --- | --- | ---: |",
    ]
    for row in report.head(80).to_dict("records"):
        lines.append(
            "| {portfolio} | {ticker} | {current} | {target} | `{action}` | {reason} | {projected} |".format(
                portfolio=row.get("portfolio_kind", ""),
                ticker=row.get("ticker", ""),
                current=pct(row.get("current_weight")),
                target=pct(row.get("target_weight")),
                action=row.get("cleanup_action", ""),
                reason=row.get("cleanup_reason", ""),
                projected=pct(row.get("projected_weight_after_cleanup_review")),
            )
        )
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/operator_review")
    parser.add_argument("--main-dust-threshold", type=float, default=0.005)
    parser.add_argument("--main-min-target-weight", type=float, default=0.01)
    parser.add_argument("--emerging-min-target-weight", type=float, default=0.0075)
    parser.add_argument("--concentrated-min-target-weight", type=float, default=0.08)
    return parser.parse_args()


def main() -> int:
    payload = build_review(parse_args())
    print(json.dumps({"schema_version": payload["schema_version"], "rows": payload["row_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

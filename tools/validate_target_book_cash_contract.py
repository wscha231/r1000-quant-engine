#!/usr/bin/env python3
"""Validate target-book cash accounting against broker-ledger realized cash.

The production contract is simple:

* every rebalance date must have explicit CASH exposure, either as a CASH row or
  an explicit cash_weight column;
* stock_weight + cash_weight must be approximately 1.0;
* broker realized cash should stay close to target-book cash.

This tool is diagnostic by default and writes machine-readable outputs for
portfolio_system_guard and broker gap attribution.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CASH_TICKERS = {"CASH", "__CASH__"}
DEFAULT_OUTPUT_DIR = "outputs/cash_contract"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


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


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def target_cash_by_date(target_book: Path, *, weight_tolerance: float = 1e-6) -> tuple[dict[str, Any], pd.DataFrame]:
    raw = read_csv(target_book)
    if raw.empty or "rebalance_date" not in raw.columns or "ticker" not in raw.columns or "weight" not in raw.columns:
        return {
            "status": "blocked",
            "reason": "target book missing rebalance_date/ticker/weight",
            "target_book": str(target_book),
        }, pd.DataFrame()

    d = raw.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0)
    d = d.dropna(subset=["rebalance_date"])
    if d.empty:
        return {"status": "blocked", "reason": "target book has no valid dates", "target_book": str(target_book)}, pd.DataFrame()

    cash_weight_col = None
    for candidate in ("cash_weight", "target_cash_weight", "cash_target_weight"):
        if candidate in d.columns:
            cash_weight_col = candidate
            d[candidate] = pd.to_numeric(d[candidate], errors="coerce")
            break

    rows: list[dict[str, Any]] = []
    for dt, group in d.groupby("rebalance_date"):
        tickers = group["ticker"]
        cash_mask = tickers.isin(CASH_TICKERS)
        stock_weight = float(group.loc[~cash_mask, "weight"].sum())
        cash_from_rows = float(group.loc[cash_mask, "weight"].sum())
        cash_from_column = None
        if cash_weight_col is not None and group[cash_weight_col].notna().any():
            cash_from_column = float(group[cash_weight_col].dropna().iloc[-1])
        explicit_cash = cash_mask.any() or cash_from_column is not None
        cash_weight = cash_from_rows if cash_mask.any() else (cash_from_column if cash_from_column is not None else max(0.0, 1.0 - stock_weight))
        total_weight = stock_weight + float(cash_weight)
        rows.append(
            {
                "rebalance_date": pd.Timestamp(dt).date().isoformat(),
                "stock_weight": stock_weight,
                "cash_weight": float(cash_weight),
                "total_weight": total_weight,
                "total_weight_error": total_weight - 1.0,
                "explicit_cash": bool(explicit_cash),
                "cash_row_count": int(cash_mask.sum()),
                "row_count": int(len(group)),
                "contract_pass": bool(
                    explicit_cash
                    and cash_weight is not None
                    and float(cash_weight) >= -weight_tolerance
                    and abs(total_weight - 1.0) <= weight_tolerance
                ),
            }
        )

    by_date = pd.DataFrame(rows)
    total_errors = pd.to_numeric(by_date["total_weight_error"], errors="coerce").abs()
    summary = {
        "status": "completed",
        "target_book": str(target_book),
        "date_count": int(len(by_date)),
        "explicit_cash_date_count": int(by_date["explicit_cash"].sum()),
        "missing_explicit_cash_date_count": int((~by_date["explicit_cash"]).sum()),
        "invalid_total_weight_date_count": int((total_errors > weight_tolerance).sum()),
        "negative_cash_date_count": int((pd.to_numeric(by_date["cash_weight"], errors="coerce") < -weight_tolerance).sum()),
        "avg_target_cash_weight": safe_float(by_date["cash_weight"].mean()),
        "max_total_weight_abs_error": safe_float(total_errors.max()),
        "target_cash_contract_pass": bool(by_date["contract_pass"].all()),
    }
    return summary, by_date


def broker_cash_frames(broker_dir: Path) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    cash = read_csv(broker_dir / "cash_ledger.csv")
    metrics = read_json(broker_dir / "metrics.json")
    if cash.empty:
        return {
            "status": "missing_cash_ledger",
            "broker_dir": str(broker_dir),
            "avg_broker_cash_weight": safe_float(metrics.get("avg_cash_weight")),
        }, pd.DataFrame(), pd.DataFrame()
    if "date" not in cash.columns or "cash_weight" not in cash.columns:
        return {"status": "invalid_cash_ledger", "broker_dir": str(broker_dir)}, pd.DataFrame(), pd.DataFrame()
    cash = cash.copy()
    cash["date"] = pd.to_datetime(cash["date"], errors="coerce").dt.normalize()
    cash["cash_weight"] = pd.to_numeric(cash["cash_weight"], errors="coerce")
    cash = cash.dropna(subset=["date", "cash_weight"]).sort_values("date")
    if cash.empty:
        return {"status": "empty_cash_ledger", "broker_dir": str(broker_dir)}, pd.DataFrame(), pd.DataFrame()
    agg = {"broker_cash_weight": ("cash_weight", "last")}
    if "equity_usd" in cash.columns:
        agg["broker_equity_usd"] = ("equity_usd", "last")
    daily = cash.groupby("date", as_index=False).agg(**agg).sort_values("date")
    monthly = (
        cash.set_index("date")["cash_weight"]
        .resample("ME")
        .mean()
        .reset_index()
        .rename(columns={"date": "month_end", "cash_weight": "broker_cash_weight"})
    )
    return {
        "status": "completed",
        "broker_dir": str(broker_dir),
        "avg_broker_cash_weight": safe_float(metrics.get("avg_cash_weight"), safe_float(cash["cash_weight"].mean())),
    }, daily, monthly


def broker_cash_by_month(broker_dir: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    summary, _daily, monthly = broker_cash_frames(broker_dir)
    return summary, monthly


def cash_drift_summary(
    target_by_date: pd.DataFrame,
    broker_daily: pd.DataFrame,
    broker_monthly: pd.DataFrame,
    *,
    mean_drift_limit_pp: float,
    max_drift_limit_pp: float,
    month_mean_drift_limit_pp: float = 5.0,
    month_max_drift_limit_pp: float = 10.0,
) -> tuple[dict[str, Any], pd.DataFrame]:
    if target_by_date.empty or broker_daily.empty or broker_monthly.empty:
        return {
            "status": "missing_target_or_broker_cash",
            "mean_cash_drift_pp": None,
            "max_monthly_cash_drift_pp": None,
            "rebalance_day_cash_drift_pass": False,
            "month_mean_cash_drift_pass": False,
            "cash_drift_pass": False,
        }, pd.DataFrame()
    target = target_by_date.copy()
    target["rebalance_date"] = pd.to_datetime(target["rebalance_date"], errors="coerce")
    target = target.dropna(subset=["rebalance_date"]).sort_values("rebalance_date")

    broker_daily = broker_daily.copy()
    broker_daily["date"] = pd.to_datetime(broker_daily["date"], errors="coerce")
    broker_daily["broker_cash_weight"] = pd.to_numeric(broker_daily["broker_cash_weight"], errors="coerce")
    broker_daily = broker_daily.dropna(subset=["date", "broker_cash_weight"]).sort_values("date")

    rebal = pd.merge_asof(
        target[["rebalance_date", "cash_weight", "stock_weight"]].sort_values("rebalance_date"),
        broker_daily[["date", "broker_cash_weight"]].sort_values("date"),
        left_on="rebalance_date",
        right_on="date",
        direction="forward",
        tolerance=pd.Timedelta(days=2),
    )
    rebal = rebal.rename(
        columns={
            "cash_weight": "target_cash_weight",
            "stock_weight": "target_stock_weight",
            "date": "broker_cash_date",
        }
    )
    rebal = rebal.dropna(subset=["broker_cash_weight"])
    if rebal.empty:
        rebalance_summary = {
            "status": "no_overlapping_rebalance_dates",
            "rebalance_day_mean_cash_drift_pp": None,
            "rebalance_day_max_cash_drift_pp": None,
            "rebalance_day_cash_drift_pass": False,
        }
    else:
        rebal["cash_drift"] = pd.to_numeric(rebal["broker_cash_weight"], errors="coerce") - pd.to_numeric(
            rebal["target_cash_weight"], errors="coerce"
        )
        rebal_abs_pp = rebal["cash_drift"].abs() * 100.0
        rebalance_mean_pp = float(rebal_abs_pp.mean())
        rebalance_max_pp = float(rebal_abs_pp.max())
        rebalance_summary = {
            "status": "completed",
            "rebalance_overlap_count": int(len(rebal)),
            "rebalance_day_mean_cash_drift_pp": round(rebalance_mean_pp, 4),
            "rebalance_day_max_cash_drift_pp": round(rebalance_max_pp, 4),
            "rebalance_day_mean_drift_limit_pp": float(mean_drift_limit_pp),
            "rebalance_day_max_drift_limit_pp": float(max_drift_limit_pp),
            "rebalance_day_cash_drift_pass": bool(
                rebalance_mean_pp <= mean_drift_limit_pp and rebalance_max_pp <= max_drift_limit_pp
            ),
        }

    target_for_daily = target[["rebalance_date", "cash_weight", "stock_weight"]].rename(
        columns={"cash_weight": "target_cash_weight", "stock_weight": "target_stock_weight"}
    )
    daily_target = pd.merge_asof(
        broker_daily[["date"]].sort_values("date"),
        target_for_daily.sort_values("rebalance_date"),
        left_on="date",
        right_on="rebalance_date",
        direction="backward",
    ).dropna(subset=["target_cash_weight"])
    daily_target["month_end"] = daily_target["date"].dt.to_period("M").dt.to_timestamp("M")
    target_monthly = (
        daily_target.groupby("month_end", as_index=False)
        .agg(target_cash_weight=("target_cash_weight", "mean"), target_stock_weight=("target_stock_weight", "mean"))
    )
    merged = target_monthly.merge(broker_monthly, on="month_end", how="inner")
    if merged.empty:
        month_summary = {
            "status": "no_overlapping_months",
            "month_mean_cash_drift_pp": None,
            "month_max_cash_drift_pp": None,
            "month_mean_cash_drift_pass": False,
        }
    else:
        merged["cash_drift"] = pd.to_numeric(merged["broker_cash_weight"], errors="coerce") - pd.to_numeric(
            merged["target_cash_weight"], errors="coerce"
        )
        drift_abs_pp = merged["cash_drift"].abs() * 100.0
        month_mean_pp = float(drift_abs_pp.mean())
        month_max_pp = float(drift_abs_pp.max())
        month_summary = {
            "status": "completed",
            "overlap_month_count": int(len(merged)),
            "month_mean_cash_drift_pp": round(month_mean_pp, 4),
            "month_max_cash_drift_pp": round(month_max_pp, 4),
            "month_mean_drift_limit_pp": float(month_mean_drift_limit_pp),
            "month_max_drift_limit_pp": float(month_max_drift_limit_pp),
            "month_mean_cash_drift_pass": bool(
                month_mean_pp <= month_mean_drift_limit_pp and month_max_pp <= month_max_drift_limit_pp
            ),
        }

    drift_frames: list[pd.DataFrame] = []
    if not rebal.empty:
        rebal_out = rebal.copy()
        rebal_out.insert(0, "comparison_method", "rebalance_day_next_close")
        drift_frames.append(rebal_out)
    if not merged.empty:
        month_out = merged.rename(columns={"month_end": "rebalance_date"}).copy()
        month_out.insert(0, "comparison_method", "month_mean")
        drift_frames.append(month_out)
    drift_table = pd.concat(drift_frames, ignore_index=True, sort=False) if drift_frames else pd.DataFrame()

    rebalance_pass = bool(rebalance_summary.get("rebalance_day_cash_drift_pass"))
    month_pass = bool(month_summary.get("month_mean_cash_drift_pass"))
    month_status = month_summary.pop("status", "unknown")
    return {
        "status": "completed",
        "month_mean_status": month_status,
        "mean_cash_drift_pp": rebalance_summary.get("rebalance_day_mean_cash_drift_pp"),
        "max_monthly_cash_drift_pp": rebalance_summary.get("rebalance_day_max_cash_drift_pp"),
        "mean_drift_limit_pp": float(mean_drift_limit_pp),
        "max_drift_limit_pp": float(max_drift_limit_pp),
        **{key: value for key, value in rebalance_summary.items() if key != "status"},
        **month_summary,
        "cash_drift_pass": bool(rebalance_pass and month_pass),
    }, drift_table


def validate_contract(
    *,
    target_book: Path,
    broker_dir: Path | None = None,
    mean_drift_limit_pp: float = 2.0,
    max_drift_limit_pp: float = 5.0,
    weight_tolerance: float = 1e-6,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    target_summary, target_by_date = target_cash_by_date(target_book, weight_tolerance=weight_tolerance)
    broker_summary: dict[str, Any] = {"status": "not_checked"}
    drift_summary: dict[str, Any] = {"status": "not_checked", "cash_drift_pass": True}
    drift = pd.DataFrame()
    if broker_dir is not None:
        broker_summary, broker_daily, broker_monthly = broker_cash_frames(broker_dir)
        drift_summary, drift = cash_drift_summary(
            target_by_date,
            broker_daily,
            broker_monthly,
            mean_drift_limit_pp=mean_drift_limit_pp,
            max_drift_limit_pp=max_drift_limit_pp,
        )
    target_pass = bool(target_summary.get("target_cash_contract_pass"))
    drift_pass = bool(drift_summary.get("cash_drift_pass"))
    summary = {
        "status": "passed" if target_pass and drift_pass else "failed",
        "target_book": str(target_book),
        "broker_dir": "" if broker_dir is None else str(broker_dir),
        "target": target_summary,
        "broker": broker_summary,
        "drift": drift_summary,
        "cash_contract_pass": bool(target_pass and drift_pass),
    }
    return summary, target_by_date, drift


def validate_latest_run(
    latest_run: Path,
    output_dir: Path,
    *,
    mean_drift_limit_pp: float = 2.0,
    max_drift_limit_pp: float = 5.0,
    weight_tolerance: float = 1e-6,
) -> dict[str, Any]:
    specs = {
        "main": latest_run / "reports" / "operating_main_target_book.csv",
        "concentrated": latest_run / "reports" / "operating_concentrated_target_book.csv",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "latest_run": str(latest_run),
        "mean_drift_limit_pp": float(mean_drift_limit_pp),
        "max_drift_limit_pp": float(max_drift_limit_pp),
        "portfolios": {},
    }
    for portfolio, target_book in specs.items():
        summary, by_date, drift = validate_contract(
            target_book=target_book,
            broker_dir=latest_run / "broker_replay" / portfolio,
            mean_drift_limit_pp=mean_drift_limit_pp,
            max_drift_limit_pp=max_drift_limit_pp,
            weight_tolerance=weight_tolerance,
        )
        payload["portfolios"][portfolio] = summary
        if not by_date.empty:
            by_date.to_csv(output_dir / f"{portfolio}_cash_contract_by_date.csv", index=False)
        if not drift.empty:
            drift.to_csv(output_dir / f"{portfolio}_cash_drift_by_month.csv", index=False)
    payload["cash_contract_pass"] = all(
        bool(item.get("cash_contract_pass")) for item in payload["portfolios"].values()
    )
    write_json(output_dir / "cash_contract_summary.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--target-book", default="")
    parser.add_argument("--broker-dir", default="")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mean-drift-limit-pp", type=float, default=2.0)
    parser.add_argument("--max-drift-limit-pp", type=float, default=5.0)
    parser.add_argument("--weight-tolerance", type=float, default=1e-6)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = repo_path(args.output_dir)
    if args.target_book:
        summary, by_date, drift = validate_contract(
            target_book=repo_path(args.target_book),
            broker_dir=repo_path(args.broker_dir) if args.broker_dir else None,
            mean_drift_limit_pp=args.mean_drift_limit_pp,
            max_drift_limit_pp=args.max_drift_limit_pp,
            weight_tolerance=args.weight_tolerance,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "cash_contract_summary.json", summary)
        if not by_date.empty:
            by_date.to_csv(output_dir / "cash_contract_by_date.csv", index=False)
        if not drift.empty:
            drift.to_csv(output_dir / "cash_drift_by_month.csv", index=False)
        payload = summary
    else:
        payload = validate_latest_run(
            repo_path(args.latest_run),
            output_dir,
            mean_drift_limit_pp=args.mean_drift_limit_pp,
            max_drift_limit_pp=args.max_drift_limit_pp,
            weight_tolerance=args.weight_tolerance,
        )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if bool(payload.get("cash_contract_pass")) else 2


if __name__ == "__main__":
    raise SystemExit(main())

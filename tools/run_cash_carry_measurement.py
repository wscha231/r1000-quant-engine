#!/usr/bin/env python3
"""Measure research-only broker cash carry against the same target books."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_CARRY_MODE_NONE,
    CASH_CARRY_MODE_RISK_FREE,
    CashCarryConfig,
    load_cash_rate_series,
    replay,
)
from tools.run_weekly_evaluation import load_price_series  # noqa: E402


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def metric(metrics: dict[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def arm_row(portfolio: str, arm: str, metrics: dict[str, Any]) -> dict[str, Any]:
    row = {
        "portfolio": portfolio,
        "arm": arm,
        "status": metrics.get("status"),
        "reason": metrics.get("reason", ""),
        "metric_mode": metrics.get("metric_mode", ""),
        "cagr": metrics.get("cagr"),
        "max_dd": metrics.get("max_dd"),
        "sharpe": metrics.get("sharpe"),
        "years": metrics.get("years"),
        "avg_cash_weight": metrics.get("avg_cash_weight"),
        "cash_interest_accrued_usd": metrics.get("cash_interest_accrued_usd", 0.0),
        "cash_interest_accrued_pct_starting_capital": metrics.get("cash_interest_accrued_pct_starting_capital", 0.0),
        "valid_for_production": metrics.get("valid_for_production", False),
        "research_only": metrics.get("research_only", False),
    }
    windows = metrics.get("windows") if isinstance(metrics.get("windows"), dict) else {}
    for label in ["is", "oos", "oos2"]:
        window = windows.get(label) if isinstance(windows.get(label), dict) else {}
        for key in ["cagr", "max_dd", "sharpe", "years", "status"]:
            row[f"{label}_{key}"] = window.get(key)
    return row


def find_target_books(latest_run: Path) -> dict[str, Path]:
    candidates = {
        "main": [
            latest_run / "reports" / "operating_main_target_book.csv",
            latest_run / "alphaops_vnext" / "official_main_target_book.csv",
        ],
        "concentrated": [
            latest_run / "reports" / "operating_concentrated_target_book.csv",
            latest_run / "alphaops_vnext" / "official_concentrated_target_book.csv",
        ],
    }
    out: dict[str, Path] = {}
    for portfolio, paths in candidates.items():
        out[portfolio] = next((path for path in paths if path.exists()), paths[0])
    return out


def latest_price_date(price_cache: Path, tickers: list[str]) -> str | None:
    dates: list[pd.Timestamp] = []
    for ticker in tickers:
        frame = load_price_series(price_cache, ticker)
        if frame.empty:
            continue
        raw_dates = pd.to_datetime(frame.index if frame.index.name else frame.get("date", frame.index), errors="coerce")
        valid_dates = pd.Series(raw_dates).dropna()
        if not valid_dates.empty:
            dates.append(pd.Timestamp(valid_dates.max()).normalize())
    if not dates:
        return None
    return max(dates).date().isoformat()


def target_book_max_date(target_books: dict[str, Path]) -> str | None:
    dates: list[pd.Timestamp] = []
    for path in target_books.values():
        frame = pd.read_csv(path) if path.exists() else pd.DataFrame()
        if frame.empty or "rebalance_date" not in frame.columns:
            continue
        parsed = pd.to_datetime(frame["rebalance_date"], errors="coerce").dropna()
        if not parsed.empty:
            dates.append(pd.Timestamp(parsed.max()).normalize())
    if not dates:
        return None
    return max(dates).date().isoformat()


def official_end_date(latest_run: Path) -> str | None:
    metrics = read_json(latest_run / "account_evaluation" / "official_metrics.json")
    candidates: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in {"end_date", "broker_end", "window_end"} and item:
                    candidates.append(str(item))
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(metrics)
    parsed = pd.to_datetime(pd.Series(candidates), errors="coerce").dropna()
    if parsed.empty:
        return None
    return pd.Timestamp(parsed.max()).date().isoformat()


def alignment_payload(
    *,
    latest_run: Path,
    price_cache: Path,
    target_books: dict[str, Path],
    rate_table: pd.DataFrame,
) -> dict[str, Any]:
    required_end = official_end_date(latest_run) or target_book_max_date(target_books)
    price_max = latest_price_date(price_cache, ["SPY", "QQQ"])
    rate_max = None
    if not rate_table.empty and "available_from" in rate_table.columns:
        parsed = pd.to_datetime(rate_table["available_from"], errors="coerce").dropna()
        if not parsed.empty:
            rate_max = pd.Timestamp(parsed.max()).date().isoformat()
    required_ts = pd.to_datetime(required_end, errors="coerce") if required_end else pd.NaT
    price_ts = pd.to_datetime(price_max, errors="coerce") if price_max else pd.NaT
    rate_ts = pd.to_datetime(rate_max, errors="coerce") if rate_max else pd.NaT
    price_aligned = bool(pd.notna(required_ts) and pd.notna(price_ts) and price_ts >= required_ts)
    rate_aligned = bool(pd.notna(required_ts) and pd.notna(rate_ts) and rate_ts >= required_ts)
    return {
        "required_end_date": required_end,
        "price_cache_max_date": price_max,
        "price_cache_aligned": price_aligned,
        "rate_cache_max_available_from": rate_max,
        "rate_cache_aligned": rate_aligned,
    }


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or abs(denominator) < 1e-12:
        return None
    return float(numerator / denominator)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rate_path = repo_path(args.rate_path) if args.rate_path else None
    oos_start = getattr(args, "oos_start", "2024-07-01")
    oos_end = getattr(args, "oos_end", "")
    oos2_start = getattr(args, "oos2_start", "2023-01-01")
    oos2_end = getattr(args, "oos2_end", "")
    carry_cfg = CashCarryConfig(
        mode=CASH_CARRY_MODE_RISK_FREE,
        rate_source=args.rate_source,
        rate_lag_days=args.rate_lag_days,
        haircut_bps=args.haircut_bps,
        day_count=args.day_count,
        rate_path=rate_path,
    )
    rate_table = load_cash_rate_series(carry_cfg, price_cache)
    target_books = find_target_books(latest_run)
    if rate_table.empty:
        payload = {
            "status": "blocked",
            "reason": "cash_rate_series_unavailable",
            "rate_source": args.rate_source,
            "rate_path": str(rate_path) if rate_path else "",
            "output_dir": str(output_dir),
            "production_activation_allowed": False,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_json(output_dir / "summary.json", payload)
        return payload
    alignment = alignment_payload(latest_run=latest_run, price_cache=price_cache, target_books=target_books, rate_table=rate_table)
    if not bool(alignment.get("price_cache_aligned")) or not bool(alignment.get("rate_cache_aligned")):
        payload = {
            "status": "blocked",
            "reason": "blocked_stale_price_cache_for_cash_carry",
            "latest_run": str(latest_run),
            "price_cache": str(price_cache),
            "rate_source": args.rate_source,
            "rate_path": str(rate_path) if rate_path else "",
            **alignment,
            "production_activation_allowed": False,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_json(output_dir / "summary.json", payload)
        return payload
    rows: list[dict[str, Any]] = []
    deltas: dict[str, Any] = {}
    for portfolio, target_book in target_books.items():
        if not target_book.exists():
            rows.append({"portfolio": portfolio, "arm": "blocked", "status": "blocked", "reason": "missing_target_book"})
            continue
        base_dir = output_dir / portfolio / "baseline"
        carry_dir = output_dir / portfolio / "cash_carry"
        base = replay(
            target_book=target_book,
            price_cache=price_cache,
            output_dir=base_dir,
            portfolio_kind=portfolio,
            fill_mode="next_close",
            cost_bps=args.cost_bps,
            max_fill_lag_days=args.max_fill_lag_days,
            oos_start=oos_start or None,
            oos_end=oos_end or None,
            oos2_start=oos2_start or None,
            oos2_end=oos2_end or None,
            cash_carry_config=CashCarryConfig(mode=CASH_CARRY_MODE_NONE),
        )
        carry = replay(
            target_book=target_book,
            price_cache=price_cache,
            output_dir=carry_dir,
            portfolio_kind=portfolio,
            fill_mode="next_close",
            cost_bps=args.cost_bps,
            max_fill_lag_days=args.max_fill_lag_days,
            oos_start=oos_start or None,
            oos_end=oos_end or None,
            oos2_start=oos2_start or None,
            oos2_end=oos2_end or None,
            cash_carry_config=carry_cfg,
        )
        rows.append(arm_row(portfolio, "baseline", base))
        rows.append(arm_row(portfolio, "cash_carry", carry))
        base_cagr = metric(base, "cagr")
        carry_cagr = metric(carry, "cagr")
        base_dd = metric(base, "max_dd")
        carry_dd = metric(carry, "max_dd")
        accrued = metric(carry, "cash_interest_accrued_usd") or 0.0
        base_windows = base.get("windows") if isinstance(base.get("windows"), dict) else {}
        carry_windows = carry.get("windows") if isinstance(carry.get("windows"), dict) else {}
        base_is_cagr = metric(base_windows.get("is", {}) if isinstance(base_windows.get("is"), dict) else {}, "cagr")
        base_oos_cagr = metric(base_windows.get("oos", {}) if isinstance(base_windows.get("oos"), dict) else {}, "cagr")
        carry_is_cagr = metric(carry_windows.get("is", {}) if isinstance(carry_windows.get("is"), dict) else {}, "cagr")
        carry_oos_cagr = metric(carry_windows.get("oos", {}) if isinstance(carry_windows.get("oos"), dict) else {}, "cagr")
        deltas[portfolio] = {
            "baseline_status": base.get("status"),
            "cash_carry_status": carry.get("status"),
            "cagr_delta_pp": (carry_cagr - base_cagr) * 100.0 if carry_cagr is not None and base_cagr is not None else None,
            "max_dd_delta_pp": (carry_dd - base_dd) * 100.0 if carry_dd is not None and base_dd is not None else None,
            "cash_interest_accrued_usd": accrued,
            "no_op_guard_pass": bool(carry.get("status") == "completed" and accrued > 0.0),
            "metric_mode": carry.get("metric_mode"),
            "baseline_oos_is_cagr_ratio": ratio(base_oos_cagr, base_is_cagr),
            "cash_carry_oos_is_cagr_ratio": ratio(carry_oos_cagr, carry_is_cagr),
            "is_cagr_delta_pp": (carry_is_cagr - base_is_cagr) * 100.0 if carry_is_cagr is not None and base_is_cagr is not None else None,
            "oos_cagr_delta_pp": (carry_oos_cagr - base_oos_cagr) * 100.0 if carry_oos_cagr is not None and base_oos_cagr is not None else None,
        }
    pd.DataFrame(rows).to_csv(output_dir / "arm_metrics.csv", index=False)
    no_op_pass = all(v.get("no_op_guard_pass") for v in deltas.values()) if deltas else False
    payload = {
        "status": "completed" if no_op_pass else "blocked",
        "schema_version": "cash-carry-measurement-v1",
        "latest_run": str(latest_run),
        "price_cache": str(price_cache),
        "rate_source": args.rate_source,
        "rate_path": str(rate_path) if rate_path else "",
        "rate_row_count": int(len(rate_table)),
        "rate_min_available_from": pd.to_datetime(rate_table["available_from"], errors="coerce").min().date().isoformat(),
        "rate_max_available_from": pd.to_datetime(rate_table["available_from"], errors="coerce").max().date().isoformat(),
        **alignment,
        "oos_start": oos_start,
        "oos_end": oos_end,
        "oos2_start": oos2_start,
        "oos2_end": oos2_end,
        "deltas": deltas,
        "cash_carry_measurement_pass": bool(no_op_pass),
        "production_activation_allowed": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    report = ["# Cash Carry Measurement", ""]
    report.append(f"- Status: `{payload['status']}`")
    report.append(f"- Rate source: `{args.rate_source}`")
    report.append(f"- Rate rows: {payload['rate_row_count']}")
    report.append(f"- Price cache aligned: `{payload['price_cache_aligned']}` ({payload['price_cache_max_date']} vs required {payload['required_end_date']})")
    report.append(f"- Rate cache aligned: `{payload['rate_cache_aligned']}` ({payload['rate_cache_max_available_from']})")
    report.append("")
    report.append("| Portfolio | CAGR delta pp | MDD delta pp | IS CAGR delta pp | OOS CAGR delta pp | Cash interest | No-op guard |")
    report.append("| --- | ---: | ---: | ---: | ---: | ---: | --- |")
    for portfolio, row in deltas.items():
        report.append(
            f"| {portfolio} | {row.get('cagr_delta_pp')} | {row.get('max_dd_delta_pp')} | "
            f"{row.get('is_cagr_delta_pp')} | {row.get('oos_cagr_delta_pp')} | "
            f"{row.get('cash_interest_accrued_usd')} | {row.get('no_op_guard_pass')} |"
        )
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    write_json(output_dir / "summary.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/cash_carry_measurement")
    parser.add_argument("--rate-source", default="DGS3MO")
    parser.add_argument("--rate-path", default="")
    parser.add_argument("--rate-lag-days", type=int, default=1)
    parser.add_argument("--haircut-bps", type=float, default=50.0)
    parser.add_argument("--day-count", type=int, default=365)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--oos-start", default="2024-07-01")
    parser.add_argument("--oos-end", default="")
    parser.add_argument("--oos2-start", default="2023-01-01")
    parser.add_argument("--oos2-end", default="")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

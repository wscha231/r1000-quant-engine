#!/usr/bin/env python3
"""Bounded same-stock-book evaluation of Run287 Reserve modes.

This is not a fullrun and never mutates an operating target or paper account.
It replays the exact same stock books under broker cash, PIT DGS3MO carry, BIL
adjusted-close total return, and SGOV adjusted-close total return (or an
explicit short-history block).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.reserve_asset_policy import (  # noqa: E402
    BIL_TOTAL_RETURN,
    BLOCKED_SHORT_HISTORY,
    BROKER_CASH_OR_MMF,
    DEFAULT_CURRENT_PAPER_MODE,
    DEFAULT_HISTORICAL_MODE,
    DGS3MO_CARRY,
    RESERVE_MODES,
    SGOV_TOTAL_RETURN,
)
from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_CARRY_MODE_NONE,
    CASH_CARRY_MODE_RISK_FREE,
    CashCarryConfig,
    replay,
)


SCHEMA_VERSION = "run287-reserve-asset-evaluation-v1"
STRESS_WINDOWS = {
    "2020": ("2020-02-03", "2020-12-31"),
    "2022": ("2022-01-03", "2022-12-30"),
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def max_drawdown(curve: pd.DataFrame, start: str, end: str) -> float | None:
    if curve.empty or not {"date", "equity_usd"}.issubset(curve.columns):
        return None
    dates = pd.to_datetime(curve["date"], errors="coerce")
    values = pd.to_numeric(curve["equity_usd"], errors="coerce")
    selected = values.loc[dates.between(pd.Timestamp(start), pd.Timestamp(end))].dropna()
    if selected.empty:
        return None
    return float((selected / selected.cummax() - 1.0).min())


def legacy_parity(
    *,
    target_book: Path,
    price_cache: Path,
    output_dir: Path,
    portfolio: str,
    starting_capital: float,
    cost_bps: float,
) -> dict[str, Any]:
    legacy = replay(
        target_book=target_book,
        price_cache=price_cache,
        output_dir=output_dir / "legacy_zero_yield",
        portfolio_kind=portfolio,
        starting_capital=starting_capital,
        fill_mode="next_close",
        cost_bps=cost_bps,
        integer_shares=True,
        max_fill_lag_days=7,
        disable_concentrated_champion_filter=True,
        cash_carry_config=CashCarryConfig(mode=CASH_CARRY_MODE_NONE),
    )
    canonical = replay(
        target_book=target_book,
        price_cache=price_cache,
        output_dir=output_dir / BROKER_CASH_OR_MMF,
        portfolio_kind=portfolio,
        starting_capital=starting_capital,
        fill_mode="next_close",
        cost_bps=cost_bps,
        integer_shares=True,
        max_fill_lag_days=7,
        disable_concentrated_champion_filter=True,
        cash_carry_config=CashCarryConfig(mode=CASH_CARRY_MODE_NONE),
        reserve_mode=BROKER_CASH_OR_MMF,
    )
    metric_fields = (
        "cagr",
        "max_dd",
        "sharpe",
        "ending_capital_usd",
        "trade_count",
        "total_fees_usd",
        "gross_traded_usd",
    )
    metric_match = all(
        abs(float(legacy.get(field, 0.0)) - float(canonical.get(field, 0.0))) <= 1e-12
        for field in metric_fields
    )
    legacy_trades = output_dir / "legacy_zero_yield" / "trades.csv"
    canonical_trades = output_dir / BROKER_CASH_OR_MMF / "trades.csv"
    trade_hash_match = (
        legacy_trades.is_file()
        and canonical_trades.is_file()
        and file_hash(legacy_trades) == file_hash(canonical_trades)
    )
    return {
        "legacy": legacy,
        "canonical": canonical,
        "metric_fields": list(metric_fields),
        "metric_match": metric_match,
        "trade_hash_match": trade_hash_match,
        "passed": bool(metric_match and trade_hash_match),
        "legacy_trade_sha256": file_hash(legacy_trades) if legacy_trades.is_file() else "",
        "canonical_trade_sha256": file_hash(canonical_trades) if canonical_trades.is_file() else "",
    }


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    price_cache = repo_path(args.price_cache)
    rate_path = repo_path(args.cash_rate_path)
    books = {
        "main": repo_path(args.main_target_book),
        "concentrated": repo_path(args.concentrated_target_book),
    }
    inputs = {
        portfolio: {"path": str(path), "sha256": file_hash(path)}
        for portfolio, path in books.items()
    }
    rows: list[dict[str, Any]] = []
    parity: dict[str, Any] = {}
    raw: dict[str, dict[str, Any]] = {}
    for portfolio, book in books.items():
        portfolio_dir = output_dir / portfolio
        parity[portfolio] = legacy_parity(
            target_book=book,
            price_cache=price_cache,
            output_dir=portfolio_dir,
            portfolio=portfolio,
            starting_capital=float(args.starting_capital),
            cost_bps=float(args.cost_bps),
        )
        raw[portfolio] = {
            BROKER_CASH_OR_MMF: parity[portfolio]["canonical"]
        }
        for mode in (DGS3MO_CARRY, BIL_TOTAL_RETURN, SGOV_TOTAL_RETURN):
            cash_config = CashCarryConfig(
                mode=CASH_CARRY_MODE_RISK_FREE if mode == DGS3MO_CARRY else CASH_CARRY_MODE_NONE,
                rate_path=rate_path if mode == DGS3MO_CARRY else None,
                haircut_bps=float(args.cash_haircut_bps),
                day_count=365,
                rate_lag_days=1,
            )
            raw[portfolio][mode] = replay(
                target_book=book,
                price_cache=price_cache,
                output_dir=portfolio_dir / mode,
                portfolio_kind=portfolio,
                starting_capital=float(args.starting_capital),
                fill_mode="next_close",
                cost_bps=float(args.cost_bps),
                integer_shares=True,
                max_fill_lag_days=7,
                disable_concentrated_champion_filter=True,
                cash_carry_config=cash_config,
                reserve_mode=mode,
            )
        baseline = raw[portfolio][BROKER_CASH_OR_MMF]
        baseline_cagr = safe_float(baseline.get("cagr")) or 0.0
        baseline_mdd = safe_float(baseline.get("max_dd")) or 0.0
        baseline_ending = safe_float(baseline.get("ending_capital_usd")) or 0.0
        for mode in RESERVE_MODES:
            metrics = raw[portfolio][mode]
            completed = metrics.get("status") == "completed"
            curve_path = portfolio_dir / mode / "equity_curve.csv"
            curve = pd.read_csv(curve_path) if completed and curve_path.is_file() else pd.DataFrame()
            cagr = safe_float(metrics.get("cagr"))
            mdd = safe_float(metrics.get("max_dd"))
            ending = safe_float(metrics.get("ending_capital_usd"))
            tradeable = mode in {BIL_TOTAL_RETURN, SGOV_TOTAL_RETURN}
            mdd_not_worse = bool(completed and mdd is not None and mdd >= baseline_mdd - 1e-12)
            rows.append(
                {
                    "portfolio": portfolio,
                    "mode": mode,
                    "status": metrics.get("status"),
                    "cagr": cagr,
                    "max_dd": mdd,
                    "sharpe": safe_float(metrics.get("sharpe")),
                    "delta_cagr_pp_vs_broker_cash": (cagr - baseline_cagr) * 100.0 if cagr is not None else None,
                    "delta_mdd_pp_vs_broker_cash": (mdd - baseline_mdd) * 100.0 if mdd is not None else None,
                    "average_reserve_weight": safe_float(metrics.get("average_reserve_weight")),
                    "latest_reserve_weight": safe_float(metrics.get("latest_reserve_weight")),
                    "reserve_return_contribution_usd_vs_broker_cash": (ending - baseline_ending) if ending is not None else None,
                    "cash_interest_accrued_usd": safe_float(metrics.get("cash_interest_accrued_usd")),
                    "trade_count": safe_float(metrics.get("trade_count")),
                    "reserve_trade_count": safe_float(metrics.get("reserve_trade_count")),
                    "gross_traded_usd": safe_float(metrics.get("gross_traded_usd")),
                    "reserve_turnover_usd": safe_float(metrics.get("reserve_turnover_usd")),
                    "fees_usd": safe_float(metrics.get("total_fees_usd")),
                    "reserve_fees_usd": safe_float(metrics.get("reserve_fees_usd")),
                    "stress_2020_mdd": max_drawdown(curve, *STRESS_WINDOWS["2020"]),
                    "stress_2022_mdd": max_drawdown(curve, *STRESS_WINDOWS["2022"]),
                    "double_count_check": metrics.get("reserve_double_count_check", "NOT_APPLICABLE"),
                    "short_history_blocked": metrics.get("status") == BLOCKED_SHORT_HISTORY,
                    "adoption_allowed_by_mdd_gate": bool(completed and (not tradeable or mdd_not_worse)),
                    "production_enabled": False,
                    "live_trading_enabled": False,
                }
            )
    results = pd.DataFrame(rows)
    results.to_csv(output_dir / "reserve_mode_metrics.csv", index=False, lineterminator="\n")
    parity_passed = all(item["passed"] for item in parity.values())
    double_count_passed = bool(
        results.loc[results["status"].eq("completed"), "double_count_check"]
        .isin({"PASS", "NOT_APPLICABLE"})
        .all()
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_RESERVE_ASSET_RESEARCH" if parity_passed and double_count_passed else "BLOCKED_RESERVE_ASSET_INTEGRITY",
        "reserve_modes_tested": list(RESERVE_MODES),
        "default_historical_mode": DEFAULT_HISTORICAL_MODE,
        "default_current_paper_mode": DEFAULT_CURRENT_PAPER_MODE,
        "inputs": inputs,
        "price_cache": str(price_cache),
        "cash_rate_path": str(rate_path),
        "cash_rate_sha256": file_hash(rate_path),
        "fill_mode": "next_close",
        "integer_shares": True,
        "cost_bps_per_side": float(args.cost_bps),
        "zero_yield_exact_parity": {
            portfolio: {
                key: value
                for key, value in item.items()
                if key not in {"legacy", "canonical"}
            }
            for portfolio, item in parity.items()
        },
        "reason_reconciliation_passed": bool(
            all(
                metrics.get("reserve_reason_reconciled_all_dates") is True
                for modes in raw.values()
                for metrics in modes.values()
                if metrics.get("status") == "completed" and "reserve_asset_policy" in metrics
            )
        ),
        "double_count_check_passed": double_count_passed,
        "metrics_path": str(output_dir / "reserve_mode_metrics.csv"),
        "fullrun_executed": False,
        "production_enabled": False,
        "live_trading_enabled": False,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-target-book", required=True)
    parser.add_argument("--concentrated-target-book", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--cash-rate-path", required=True)
    parser.add_argument("--output-dir", default="outputs/run287_reserve_asset_policy")
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--cash-haircut-bps", type=float, default=50.0)
    return parser.parse_args()


def main() -> int:
    payload = evaluate(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "READY_RESERVE_ASSET_RESEARCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())

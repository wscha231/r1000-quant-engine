#!/usr/bin/env python3
"""Evaluate the single P6 sector-RS materialization remediation."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_CARRY_MODE_RISK_FREE,
    DEFAULT_OOS2_START,
    DEFAULT_OOS_START,
    CashCarryConfig,
    replay,
)
from tools.run287_hold_exit_policy import file_sha256, safe_float  # noqa: E402
from tools.reserve_asset_policy import DGS3MO_CARRY  # noqa: E402


SCHEMA_VERSION = "run287-sector-rs-materialization-evaluation-v1"
COSTS = (25.0, 50.0, 100.0)
CASH = {"CASH", "__CASH__"}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def normalize_book(path: Path, end_date: pd.Timestamp) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    frame["rebalance_date"] = pd.to_datetime(frame["rebalance_date"], errors="coerce").dt.normalize()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    weight_column = "weight" if "weight" in frame else "target_weight"
    frame["weight"] = pd.to_numeric(frame[weight_column], errors="coerce")
    frame = frame[frame["rebalance_date"].le(end_date)].copy()
    if frame[["rebalance_date", "ticker", "weight"]].isna().any().any():
        raise ValueError("invalid target book")
    if frame.duplicated(["rebalance_date", "ticker"]).any():
        raise ValueError("duplicate target row")
    totals = frame.groupby("rebalance_date")["weight"].sum()
    if not totals.sub(1.0).abs().le(1e-8).all():
        raise ValueError("target book weights do not sum to one")
    return frame.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)


def behavior_delta(control: pd.DataFrame, treatment: pd.DataFrame) -> dict[str, Any]:
    dates = sorted(set(control["rebalance_date"]) & set(treatment["rebalance_date"]))
    if set(control["rebalance_date"]) != set(treatment["rebalance_date"]):
        raise ValueError("control/treatment decision dates differ")
    rows = []
    for day in dates:
        lhs = control[control["rebalance_date"].eq(day)].set_index("ticker")["weight"]
        rhs = treatment[treatment["rebalance_date"].eq(day)].set_index("ticker")["weight"]
        tickers = lhs.index.union(rhs.index)
        absolute = lhs.reindex(tickers, fill_value=0.0).sub(
            rhs.reindex(tickers, fill_value=0.0)
        ).abs()
        rows.append({
            "rebalance_date": pd.Timestamp(day).date().isoformat(),
            "one_way_weight_delta": float(absolute.sum() / 2.0),
            "changed_ticker_count": int(absolute.gt(1e-12).sum()),
            "control_cash": float(lhs.reindex(CASH).fillna(0.0).sum()),
            "treatment_cash": float(rhs.reindex(CASH).fillna(0.0).sum()),
        })
    frame = pd.DataFrame(rows)
    return {
        "rows": frame,
        "decision_count": len(frame),
        "changed_decision_count": int(frame["one_way_weight_delta"].gt(1e-12).sum()),
        "total_one_way_weight_delta": float(frame["one_way_weight_delta"].sum()),
        "average_control_cash": float(frame["control_cash"].mean()),
        "average_treatment_cash": float(frame["treatment_cash"].mean()),
    }


def cash_config(path: Path) -> CashCarryConfig:
    return CashCarryConfig(
        mode=CASH_CARRY_MODE_RISK_FREE,
        rate_path=path,
        haircut_bps=50.0,
        day_count=365,
        rate_lag_days=1,
    )


def run_replay(
    book: Path,
    *,
    price_cache: Path,
    rate_path: Path,
    output_dir: Path,
    portfolio: str,
    cost_bps: float,
) -> dict[str, Any]:
    return replay(
        target_book=book,
        price_cache=price_cache,
        output_dir=output_dir,
        portfolio_kind=portfolio,
        starting_capital=100000.0,
        fill_mode="next_close",
        cost_bps=cost_bps,
        integer_shares=True,
        max_fill_lag_days=7,
        disable_concentrated_champion_filter=True,
        oos_start=DEFAULT_OOS_START,
        oos2_start=DEFAULT_OOS2_START,
        cash_carry_config=cash_config(rate_path),
        reserve_mode=DGS3MO_CARRY,
    )


def window(metrics: dict[str, Any], name: str) -> dict[str, Any]:
    windows = metrics.get("windows") or {}
    return windows.get(name) or (metrics if name == "full" else {})


def delta(treatment: dict[str, Any], control: dict[str, Any], key: str) -> float | None:
    lhs, rhs = safe_float(treatment.get(key)), safe_float(control.get(key))
    return lhs - rhs if math.isfinite(lhs) and math.isfinite(rhs) else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    for prefix in ("control-main", "treatment-main", "control-concentrated", "treatment-concentrated"):
        parser.add_argument(f"--{prefix}", required=True)
    parser.add_argument("--candidate-artifact", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--cash-rate-path", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    candidate_path = repo_path(args.candidate_artifact)
    candidate_dates = pd.to_datetime(
        pd.read_csv(candidate_path, usecols=["rebalance_date"])["rebalance_date"],
        errors="coerce",
    ).dropna()
    end_date = pd.Timestamp(candidate_dates.max()).normalize()
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"append-only output exists:{output_dir}")
    output_dir.mkdir(parents=True)
    price_cache = repo_path(args.price_cache)
    rate_path = repo_path(args.cash_rate_path)
    sources = {
        "main": (repo_path(args.control_main), repo_path(args.treatment_main)),
        "concentrated": (
            repo_path(args.control_concentrated),
            repo_path(args.treatment_concentrated),
        ),
    }
    portfolios: dict[str, Any] = {}
    for portfolio, (control_source, treatment_source) in sources.items():
        control = normalize_book(control_source, end_date)
        treatment = normalize_book(treatment_source, end_date)
        behavior = behavior_delta(control, treatment)
        behavior_rows = behavior.pop("rows")
        behavior_rows.to_csv(output_dir / f"{portfolio}_behavior_delta.csv", index=False)
        book_dir = output_dir / portfolio
        book_dir.mkdir(parents=True)
        control_book = book_dir / "control_target_book.csv"
        treatment_book = book_dir / "treatment_target_book.csv"
        control.to_csv(control_book, index=False, lineterminator="\n")
        treatment.to_csv(treatment_book, index=False, lineterminator="\n")
        cost_results: dict[str, Any] = {}
        primary_windows: dict[str, Any] = {}
        for cost in COSTS:
            label = f"{int(cost)}bps"
            control_metrics = run_replay(
                control_book, price_cache=price_cache, rate_path=rate_path,
                output_dir=book_dir / label / "control", portfolio=portfolio, cost_bps=cost,
            )
            treatment_metrics = run_replay(
                treatment_book, price_cache=price_cache, rate_path=rate_path,
                output_dir=book_dir / label / "treatment", portfolio=portfolio, cost_bps=cost,
            )
            cost_results[label] = {
                "control": control_metrics,
                "treatment": treatment_metrics,
                "delta_cagr": delta(treatment_metrics, control_metrics, "cagr"),
                "delta_max_dd": delta(treatment_metrics, control_metrics, "max_dd"),
                "delta_sharpe": delta(treatment_metrics, control_metrics, "sharpe"),
                "delta_fees_usd": delta(treatment_metrics, control_metrics, "total_fees_usd"),
                "delta_trade_count": int(treatment_metrics.get("trade_count", 0)) - int(control_metrics.get("trade_count", 0)),
            }
            if cost == 25.0:
                for name in ("full", "oos", "oos2"):
                    lhs, rhs = window(control_metrics, name), window(treatment_metrics, name)
                    primary_windows[name] = {
                        "control": lhs,
                        "treatment": rhs,
                        "delta_cagr": delta(rhs, lhs, "cagr"),
                        "delta_max_dd": delta(rhs, lhs, "max_dd"),
                        "delta_sharpe": delta(rhs, lhs, "sharpe"),
                    }
        primary = cost_results["25bps"]
        gates = {
            "not_noop": behavior["changed_decision_count"] > 0,
            "full_delta_cagr_positive": safe_float(primary["delta_cagr"], -math.inf) > 0.0,
            "full_delta_sharpe_ge_minus_0_05": safe_float(primary["delta_sharpe"], -math.inf) >= -0.05,
            "full_delta_mdd_ge_minus_3pp": safe_float(primary["delta_max_dd"], -math.inf) >= -0.03,
            "oos_delta_cagr_nonnegative": safe_float(primary_windows["oos"]["delta_cagr"], -math.inf) >= 0.0,
            "oos2_delta_cagr_nonnegative": safe_float(primary_windows["oos2"]["delta_cagr"], -math.inf) >= 0.0,
            "100bps_delta_cagr_positive": safe_float(cost_results["100bps"]["delta_cagr"], -math.inf) > 0.0,
            "turnover_cost_not_exceed_alpha": safe_float(primary["delta_cagr"], -math.inf) > 0.0,
        }
        portfolios[portfolio] = {
            "behavior": behavior,
            "control_target_sha256": file_sha256(control_book),
            "treatment_target_sha256": file_sha256(treatment_book),
            "cost_sensitivity": cost_results,
            "windows_25bps": primary_windows,
            "gates": gates,
            "passed": all(gates.values()),
        }
    overall = all(record["passed"] for record in portfolios.values())
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_RESEARCH_ONLY" if overall else "REJECT_REMEDIATION",
        "single_remediation": "canonical_rs_sector_3m_materialization",
        "common_decision_end_date": end_date.date().isoformat(),
        "candidate_artifact_sha256": file_sha256(candidate_path),
        "cash_rate_sha256": file_sha256(rate_path),
        "portfolios": portfolios,
        "threshold_grid_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    write_json(output_dir / "summary.json", payload)
    return payload


def main() -> int:
    payload = evaluate(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

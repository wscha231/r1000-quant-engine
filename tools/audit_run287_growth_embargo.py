#!/usr/bin/env python3
"""Audit a fixed Run287 growth arm on disjoint 126-session embargoed segments.

This is a measurement-only sidecar.  It does not retrain a model, tune the
fixed arm, replay trades, mutate target books, dispatch fullrun, or create
orders.  The output explicitly distinguishes fixed-policy segment evidence
from a walk-forward retraining claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = "docs/run287_growth_embargo_contract_v1.json"
DEFAULT_REPLAY_ROOT = (
    "outputs/run287_cagr_first_growth_confirmation_tilt10_sensitivity_20260716/"
    "replays/cash_carry/25bps"
)
DEFAULT_TARGET_BOOK = (
    "outputs/run287_multisource_fusion_broker_ab/signal_replays/"
    "growth_confirmation_score/main/growth_confirmation_top_quintile_tilt10/target_book.csv"
)
DEFAULT_SOURCE_SUMMARY = (
    "outputs/run287_multisource_fusion_broker_ab/signal_replays/"
    "growth_confirmation_score/main/summary.json"
)
DEFAULT_OUTPUT_DIR = "outputs/run287_growth_embargo_walk_forward_20260718"
DATE_PROVENANCE_COLUMNS = (
    "latest_available_from",
    "latest_13f_available_from",
    "latest_etf_available_from",
    "latest_top_manager_available_from",
    "fusion_score_source_rebalance_date",
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def read_equity(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    lower = {str(column).strip().lower(): column for column in frame.columns}
    date_column = lower.get("date")
    equity_column = next(
        (lower[name] for name in ("equity_usd", "equity", "account_value", "portfolio_value") if name in lower),
        None,
    )
    if date_column is None or equity_column is None:
        raise ValueError(f"equity curve missing date/equity columns: {path}")
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_column], errors="coerce").dt.normalize(),
            "equity": pd.to_numeric(frame[equity_column], errors="coerce"),
        }
    ).dropna(subset=["date", "equity"])
    out = out.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    if len(out) < 2 or (out["equity"] <= 0).any():
        raise ValueError(f"invalid equity curve: {path}")
    return out


def align_equity(baseline: pd.DataFrame, candidate: pd.DataFrame) -> pd.DataFrame:
    joined = baseline.merge(candidate, on="date", how="inner", suffixes=("_baseline", "_candidate"))
    joined = joined.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    if len(joined) < 2:
        raise ValueError("baseline and candidate have insufficient overlapping equity dates")
    return joined


def cagr(start: float, end: float, days: int) -> float | None:
    if start <= 0 or end <= 0 or days <= 0:
        return None
    years = days / 365.25
    result = (end / start) ** (1.0 / years) - 1.0
    return result if math.isfinite(result) else None


def sharpe(values: pd.Series) -> float | None:
    returns = pd.to_numeric(values, errors="coerce").dropna()
    if len(returns) < 2:
        return None
    volatility = float(returns.std(ddof=1))
    if not math.isfinite(volatility) or volatility <= 0:
        return None
    result = float(returns.mean()) / volatility * math.sqrt(252.0)
    return result if math.isfinite(result) else None


def max_drawdown(values: pd.Series) -> float | None:
    equity = pd.to_numeric(values, errors="coerce").dropna()
    if equity.empty:
        return None
    result = float((equity / equity.cummax() - 1.0).min())
    return result if math.isfinite(result) else None


def segment_metrics(frame: pd.DataFrame, equity_column: str) -> dict[str, Any]:
    start = frame.iloc[0]
    end = frame.iloc[-1]
    days = int((pd.Timestamp(end["date"]) - pd.Timestamp(start["date"])).days)
    returns = pd.to_numeric(frame[equity_column], errors="coerce").pct_change()
    return {
        "start_equity": float(start[equity_column]),
        "end_equity": float(end[equity_column]),
        "total_return": float(end[equity_column] / start[equity_column] - 1.0),
        "cagr": cagr(float(start[equity_column]), float(end[equity_column]), days),
        "sharpe": sharpe(returns),
        "max_dd": max_drawdown(frame[equity_column]),
    }


def audit_provenance(target_book_path: Path, source_summary: dict[str, Any]) -> dict[str, Any]:
    frame = pd.read_csv(target_book_path, low_memory=False)
    required = {"rebalance_date", "ticker"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"target book missing columns: {missing}")
    decision = pd.to_datetime(frame["rebalance_date"], errors="coerce").dt.normalize()
    non_cash = ~frame["ticker"].astype(str).str.upper().isin({"CASH", "USD", "CASH_USD"})
    violations: list[dict[str, Any]] = []
    violation_count = 0
    checked_columns: list[str] = []
    for column in DATE_PROVENANCE_COLUMNS:
        if column not in frame.columns:
            continue
        checked_columns.append(column)
        available = pd.to_datetime(frame[column], errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
        mask = non_cash & available.notna() & decision.notna() & available.gt(decision)
        violation_count += int(mask.sum())
        remaining_sample_slots = max(0, 20 - len(violations))
        for index in frame.index[mask][:remaining_sample_slots]:
            violations.append(
                {
                    "row": int(index),
                    "ticker": str(frame.at[index, "ticker"]),
                    "rebalance_date": str(decision.at[index].date()),
                    "column": column,
                    "available_from": str(available.at[index].date()),
                }
            )
    return {
        "target_book_rows": int(len(frame)),
        "non_cash_rows": int(non_cash.sum()),
        "checked_date_columns": checked_columns,
        "future_row_violation_count": violation_count,
        "future_row_violation_sample": violations,
        "used_forward_return_in_ranking": source_summary.get("used_forward_return_in_ranking"),
        "period_forward_return_present_but_audit_only": "period_forward_return" in frame.columns,
    }


def evaluate_fold(
    aligned: pd.DataFrame,
    fold: dict[str, Any],
    *,
    embargo_sessions: int,
    minimum_test_sessions: int,
    minimum_delta_sharpe: float,
) -> dict[str, Any]:
    name = str(fold.get("name") or "")
    train_end = pd.Timestamp(fold["train_end"]).normalize()
    requested_test_end = pd.Timestamp(fold["test_end"]).normalize()
    after_train = aligned.index[aligned["date"].gt(train_end)].tolist()
    if len(after_train) <= embargo_sessions:
        return {"name": name, "status": "BLOCKED_INSUFFICIENT_EMBARGO_SESSIONS", "pass": False}
    anchor_index = after_train[embargo_sessions - 1]
    test_start_index = after_train[embargo_sessions]
    test_end_candidates = aligned.index[
        aligned["date"].ge(aligned.at[test_start_index, "date"])
        & aligned["date"].le(requested_test_end)
    ].tolist()
    if not test_end_candidates:
        return {"name": name, "status": "BLOCKED_EMPTY_TEST_WINDOW", "pass": False}
    test_end_index = test_end_candidates[-1]
    segment = aligned.loc[anchor_index:test_end_index].copy()
    test_sessions = int(len(segment) - 1)
    baseline = segment_metrics(segment, "equity_baseline")
    candidate = segment_metrics(segment, "equity_candidate")
    delta_cagr = None
    if baseline["cagr"] is not None and candidate["cagr"] is not None:
        delta_cagr = float(candidate["cagr"] - baseline["cagr"])
    delta_sharpe = None
    if baseline["sharpe"] is not None and candidate["sharpe"] is not None:
        delta_sharpe = float(candidate["sharpe"] - baseline["sharpe"])
    passed = bool(
        test_sessions >= minimum_test_sessions
        and delta_cagr is not None
        and delta_cagr > 0.0
        and delta_sharpe is not None
        and delta_sharpe >= minimum_delta_sharpe
    )
    return {
        "name": name,
        "status": "PASS" if passed else "REJECT_FOLD_GATE",
        "pass": passed,
        "train_end": train_end.date().isoformat(),
        "embargo_sessions": embargo_sessions,
        "embargo_start": str(aligned.at[after_train[0], "date"].date()),
        "embargo_end": str(aligned.at[anchor_index, "date"].date()),
        "test_start": str(aligned.at[test_start_index, "date"].date()),
        "test_end": str(aligned.at[test_end_index, "date"].date()),
        "test_sessions": test_sessions,
        "baseline": baseline,
        "candidate": candidate,
        "delta_cagr_pp": None if delta_cagr is None else delta_cagr * 100.0,
        "delta_sharpe": delta_sharpe,
        "delta_max_dd_pp_diagnostic": (
            None
            if baseline["max_dd"] is None or candidate["max_dd"] is None
            else (candidate["max_dd"] - baseline["max_dd"]) * 100.0
        ),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    contract_path = repo_path(args.contract)
    replay_root = repo_path(args.replay_root)
    baseline_path = replay_root / "baseline" / "equity_curve.csv"
    candidate_path = replay_root / "candidate" / "equity_curve.csv"
    target_book_path = repo_path(args.target_book)
    source_summary_path = repo_path(args.source_summary)
    input_paths = {
        "contract": contract_path,
        "baseline_equity": baseline_path,
        "candidate_equity": candidate_path,
        "target_book": target_book_path,
        "source_summary": source_summary_path,
    }
    missing = [str(path) for path in input_paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing required inputs: {missing}")

    contract = read_json(contract_path)
    source_summary = read_json(source_summary_path)
    gates = contract.get("gates") if isinstance(contract.get("gates"), dict) else {}
    embargo_sessions = int(gates.get("embargo_sessions", 126))
    minimum_test_sessions = int(gates.get("minimum_test_sessions_per_fold", 60))
    minimum_delta_sharpe = float(gates.get("each_fold_minimum_delta_sharpe", -0.05))
    aligned = align_equity(read_equity(baseline_path), read_equity(candidate_path))
    provenance = audit_provenance(target_book_path, source_summary)
    fold_rows = [
        evaluate_fold(
            aligned,
            fold,
            embargo_sessions=embargo_sessions,
            minimum_test_sessions=minimum_test_sessions,
            minimum_delta_sharpe=minimum_delta_sharpe,
        )
        for fold in contract.get("folds", [])
        if isinstance(fold, dict)
    ]
    provenance_pass = bool(
        provenance["future_row_violation_count"] == int(gates.get("future_row_violation_count", 0))
        and provenance["used_forward_return_in_ranking"] is bool(gates.get("used_forward_return_in_ranking", False))
    )
    all_folds_pass = bool(fold_rows and all(row.get("pass") for row in fold_rows))
    passed = bool(provenance_pass and all_folds_pass)
    status = "PASS_FIXED_POLICY_EMBARGO" if passed else (
        "BLOCKED_FUTURE_ROW_LEAKAGE" if not provenance_pass else "REJECT_EMBARGO_FOLD"
    )
    payload = {
        "schema_version": "run287-growth-embargo-audit-v1",
        "code_git_head": git_head(),
        "status": status,
        "fixed_policy_embargo_pass": passed,
        "walk_forward_retraining_completed": False,
        "walk_forward_retraining_claimed": False,
        "interpretation": (
            "Disjoint fixed-policy forward segments after a complete 126-session embargo; "
            "this is not a claim that a model was retrained per fold."
        ),
        "policy": contract.get("policy"),
        "provenance": provenance,
        "provenance_pass": provenance_pass,
        "folds": fold_rows,
        "inputs": {name: fingerprint(path) for name, path in input_paths.items()},
        "research_only": True,
        "fullrun_dispatched": False,
        "target_books_mutated": False,
        "orders_generated": False,
        "threshold_tuning_performed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "pit_universe_label_clean": False,
    }
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", payload)
    pd.DataFrame(fold_rows).to_csv(output_dir / "fold_results.csv", index=False)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT)
    parser.add_argument("--replay-root", default=DEFAULT_REPLAY_ROOT)
    parser.add_argument("--target-book", default=DEFAULT_TARGET_BOOK)
    parser.add_argument("--source-summary", default=DEFAULT_SOURCE_SUMMARY)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("fixed_policy_embargo_pass") else 2


if __name__ == "__main__":
    raise SystemExit(main())

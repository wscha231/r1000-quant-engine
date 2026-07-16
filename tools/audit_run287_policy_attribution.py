#!/usr/bin/env python3
"""Audit Run287 policy attribution without changing scores, books, cash, or orders."""

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
HORIZONS = (1, 5, 21, 63, 126, 252)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else 0,
        "sha256": sha256_file(path) if path.is_file() else "",
    }


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=False, capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def completed(group: pd.DataFrame, horizon: int) -> pd.DataFrame:
    status = f"outcome_{horizon}d_status"
    ret = f"outcome_{horizon}d_ticker_total_return"
    if status not in group or ret not in group:
        return group.iloc[0:0].copy()
    out = group[group[status].eq("completed")].copy()
    out[ret] = pd.to_numeric(out[ret], errors="coerce")
    return out[out[ret].notna()]


def distance(selected: pd.Series, controls: pd.DataFrame) -> pd.Series:
    result = pd.Series(0.0, index=controls.index)
    terms = 0
    for column, log_scale in (("published_rank", False), ("mktcap", True), ("vol_252d", False)):
        target = finite(selected.get(column))
        values = pd.to_numeric(controls.get(column), errors="coerce")
        if target is None or values.notna().sum() == 0:
            continue
        if log_scale:
            values = np.log1p(values.clip(lower=0))
            target = math.log1p(max(target, 0.0))
        scale = float(values.std(ddof=0))
        scale = scale if math.isfinite(scale) and scale > 1e-12 else 1.0
        result += (values.fillna(values.median()) - target).abs() / scale
        terms += 1
    return result if terms else pd.Series(np.arange(len(controls)), index=controls.index, dtype=float)


def selection_attribution(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    keys = ["decision_date", "portfolio_kind", "scenario"]
    for key, group in frame.groupby(keys, dropna=False, sort=True):
        for horizon in HORIZONS:
            eligible = completed(group, horizon)
            ret_col = f"outcome_{horizon}d_ticker_total_return"
            selected = eligible[eligible["selector_selected"].fillna(False).astype(bool)].copy()
            controls = eligible[
                ~eligible["selector_selected"].fillna(False).astype(bool)
                & eligible["published_ranking_eligible"].fillna(False).astype(bool)
            ].copy()
            matches: list[tuple[float, float]] = []
            available = set(controls.index)
            for _, chosen in selected.sort_values("ticker", kind="mergesort").iterrows():
                pool = controls.loc[sorted(available)] if available else controls.iloc[0:0]
                same_sector = pool[pool["sector"].eq(chosen.get("sector"))]
                if not same_sector.empty:
                    pool = same_sector
                if pool.empty:
                    break
                best = distance(chosen, pool).sort_values(kind="mergesort").index[0]
                matches.append((float(chosen[ret_col]), float(pool.loc[best, ret_col])))
                available.discard(best)
            status = "COMPLETED_MATCHED_CONTROL" if matches else "UNDERPOWERED_NO_COMPLETED_MATCH"
            selected_mean = float(np.mean([x[0] for x in matches])) if matches else None
            control_mean = float(np.mean([x[1] for x in matches])) if matches else None
            rows.append(
                {
                    "status": status,
                    "decision_date": key[0],
                    "portfolio_kind": key[1],
                    "scenario": key[2],
                    "horizon_sessions": horizon,
                    "completed_selected_count": int(len(selected)),
                    "completed_control_count": int(len(controls)),
                    "matched_pair_count": int(len(matches)),
                    "selected_mean_return": selected_mean,
                    "matched_control_mean_return": control_mean,
                    "selection_spread": selected_mean - control_mean if matches else None,
                    "matching_policy": "same_sector_then_nearest_published_rank_log_mktcap_vol252d_without_replacement",
                }
            )
    return pd.DataFrame(rows)


def entry_timing_attribution(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    keys = ["decision_date", "portfolio_kind", "scenario"]
    for key, group in frame.groupby(keys, dropna=False, sort=True):
        for horizon in HORIZONS:
            ret_col = f"outcome_{horizon}d_ticker_total_return"
            delayed_col = f"outcome_{horizon}d_entry_plus_5d_total_return"
            eligible = completed(group, horizon)
            selected = eligible[eligible["selector_selected"].fillna(False).astype(bool)]
            identified = delayed_col in selected and selected[delayed_col].notna().any()
            exact_mean = float(selected[ret_col].mean()) if not selected.empty else None
            delayed_mean = float(pd.to_numeric(selected[delayed_col], errors="coerce").mean()) if identified else None
            rows.append(
                {
                    "status": "COMPLETED_ENTRY_COUNTERFACTUAL" if identified else "UNDERPOWERED_ALTERNATE_ENTRY_PATH_NOT_OBSERVED",
                    "decision_date": key[0],
                    "portfolio_kind": key[1],
                    "scenario": key[2],
                    "horizon_sessions": horizon,
                    "completed_selected_count": int(len(selected)),
                    "next_close_mean_return": exact_mean,
                    "entry_plus_5d_mean_return": delayed_mean,
                    "entry_timing_spread": exact_mean - delayed_mean if identified else None,
                    "execution_basis": "next_close",
                }
            )
    return pd.DataFrame(rows)


def hold_exit_attribution(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    keys = ["decision_date", "portfolio_kind", "scenario"]
    for key, group in frame.groupby(keys, dropna=False, sort=True):
        for horizon in HORIZONS:
            ret_col = f"outcome_{horizon}d_ticker_total_return"
            eligible = completed(group, horizon)
            eligible = eligible[eligible["prior_holding"].fillna(False).astype(bool)]
            for action, action_group in eligible.groupby("hold_replace_decision", dropna=False, sort=True):
                rows.append(
                    {
                        "status": "COMPLETED_OBSERVED_PATH" if len(action_group) else "UNDERPOWERED_NO_COMPLETED_PATH",
                        "decision_date": key[0],
                        "portfolio_kind": key[1],
                        "scenario": key[2],
                        "horizon_sessions": horizon,
                        "hold_replace_decision": action,
                        "completed_count": int(len(action_group)),
                        "mean_forward_return": float(action_group[ret_col].mean()) if len(action_group) else None,
                        "median_forward_return": float(action_group[ret_col].median()) if len(action_group) else None,
                        "causal_identification": "descriptive_only_until_fixed_policy_counterfactual_exists",
                    }
                )
            if eligible.empty:
                rows.append(
                    {
                        "status": "UNDERPOWERED_NO_COMPLETED_HOLD_EXIT_PATH",
                        "decision_date": key[0],
                        "portfolio_kind": key[1],
                        "scenario": key[2],
                        "horizon_sessions": horizon,
                        "hold_replace_decision": "",
                        "completed_count": 0,
                        "mean_forward_return": None,
                        "median_forward_return": None,
                        "causal_identification": "descriptive_only_until_fixed_policy_counterfactual_exists",
                    }
                )
    return pd.DataFrame(rows)


def weighted_return(group: pd.DataFrame, weight_col: str, return_col: str) -> float | None:
    if weight_col not in group or return_col not in group:
        return None
    weights = pd.to_numeric(group[weight_col], errors="coerce").fillna(0.0).clip(lower=0)
    returns = pd.to_numeric(group[return_col], errors="coerce")
    mask = weights.gt(0) & returns.notna()
    total = float(weights[mask].sum())
    return float((weights[mask] * returns[mask]).sum() / total) if total > 0 else None


def sizing_cash_attribution(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    keys = ["decision_date", "portfolio_kind", "scenario"]
    for key, group in frame.groupby(keys, dropna=False, sort=True):
        for horizon in HORIZONS:
            ret_col = f"outcome_{horizon}d_ticker_total_return"
            spy_col = f"outcome_{horizon}d_spy_total_return"
            eligible = completed(group, horizon)
            selected = eligible[eligible["selector_selected"].fillna(False).astype(bool)]
            equal = float(selected[ret_col].mean()) if len(selected) else None
            advisory = weighted_return(eligible, "advisory_weight", ret_col)
            operating = weighted_return(eligible, "operating_target_weight", ret_col)
            fill = weighted_return(eligible, "simulated_fill_weight", ret_col)
            cash = finite(group["advisory_cash_weight"].dropna().iloc[0]) if group["advisory_cash_weight"].notna().any() else None
            spy = float(pd.to_numeric(eligible.get(spy_col), errors="coerce").mean()) if spy_col in eligible and len(eligible) else None
            rows.append(
                {
                    "status": "COMPLETED_OBSERVED_WEIGHT_PATH" if len(selected) else "UNDERPOWERED_NO_COMPLETED_SELECTED_PATH",
                    "decision_date": key[0],
                    "portfolio_kind": key[1],
                    "scenario": key[2],
                    "horizon_sessions": horizon,
                    "completed_selected_count": int(len(selected)),
                    "equal_weight_selected_return": equal,
                    "advisory_invested_weight_return": advisory,
                    "operating_invested_weight_return": operating,
                    "simulated_fill_invested_weight_return": fill,
                    "advisory_sizing_minus_equal": advisory - equal if advisory is not None and equal is not None else None,
                    "advisory_cash_weight": cash,
                    "zero_yield_cash_vs_spy_opportunity_cost": -cash * spy if cash is not None and spy is not None else None,
                    "causal_identification": "descriptive_decomposition_not_a_policy_ab_test",
                }
            )
    return pd.DataFrame(rows)


def execution_attribution(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    keys = ["decision_date", "portfolio_kind", "scenario"]
    for key, group in frame.groupby(keys, dropna=False, sort=True):
        a2o = pd.to_numeric(group["advisory_to_operating_weight_delta"], errors="coerce").fillna(0.0)
        o2f = pd.to_numeric(group["operating_to_fill_weight_delta"], errors="coerce").fillna(0.0)
        cash_error = pd.to_numeric(group["paper_cash_reconciliation_error_usd"], errors="coerce").abs()
        path_counts = group["path_reconciliation_status"].fillna("missing").value_counts().to_dict()
        rows.append(
            {
                "status": "RECONCILED_REVIEW_ONLY" if cash_error.dropna().le(0.01).all() else "BLOCKED_CASH_RECONCILIATION",
                "decision_date": key[0],
                "portfolio_kind": key[1],
                "scenario": key[2],
                "ticker_count": int(group["ticker"].nunique()),
                "advisory_to_operating_gross_abs_weight": float(a2o.abs().sum()),
                "operating_to_fill_gross_abs_weight": float(o2f.abs().sum()),
                "operating_position_count": int(group["operating_target_weight"].fillna(0).gt(0).sum()),
                "simulated_fill_position_count": int(group["simulated_fill_shares"].fillna(0).gt(0).sum()),
                "max_cash_reconciliation_error_usd": float(cash_error.max()) if cash_error.notna().any() else None,
                "path_status_counts_json": json.dumps(path_counts, sort_keys=True, separators=(",", ":")),
                "orders_generated": False,
                "live_trading_enabled": False,
            }
        )
    return pd.DataFrame(rows)


def run(args: argparse.Namespace) -> dict[str, Any]:
    ledger_dir = repo_path(args.ledger_dir)
    input_path = repo_path(args.current_status) if args.current_status else ledger_dir / "current_status.parquet"
    output_dir = repo_path(args.output_dir) if args.output_dir else ledger_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    blockers: list[str] = []
    if not input_path.is_file():
        blockers.append("current_status_missing")
        frame = pd.DataFrame()
    else:
        frame = pd.read_parquet(input_path)
    required = {
        "decision_date", "ticker", "portfolio_kind", "scenario", "selector_selected",
        "published_ranking_eligible", "advisory_weight", "operating_target_weight",
        "simulated_fill_weight", "path_reconciliation_status",
    }
    missing = sorted(required - set(frame.columns))
    blockers.extend(f"missing_column:{column}" for column in missing)
    products = {
        "selection_attribution.csv": selection_attribution(frame) if not blockers else pd.DataFrame(),
        "entry_timing_attribution.csv": entry_timing_attribution(frame) if not blockers else pd.DataFrame(),
        "hold_exit_attribution.csv": hold_exit_attribution(frame) if not blockers else pd.DataFrame(),
        "sizing_cash_attribution.csv": sizing_cash_attribution(frame) if not blockers else pd.DataFrame(),
        "execution_attribution.csv": execution_attribution(frame) if not blockers else pd.DataFrame(),
    }
    for name, product in products.items():
        product.to_csv(output_dir / name, index=False, lineterminator="\n")
    completed_63d = int(frame.get("outcome_63d_status", pd.Series(dtype=str)).eq("completed").sum()) if not frame.empty else 0
    executed = products["execution_attribution.csv"]
    cash_ok = bool(executed.empty or executed["status"].eq("RECONCILED_REVIEW_ONLY").all())
    status = "BLOCKED_POLICY_ATTRIBUTION" if blockers or not cash_ok else (
        "READY_POLICY_ATTRIBUTION_REVIEW_ONLY" if completed_63d else "UNDERPOWERED_POLICY_ATTRIBUTION_WAITING_63D"
    )
    payload = {
        "schema_version": "run287-policy-attribution-v1",
        "status": status,
        "generated_at_utc": args.generated_at_utc,
        "git_head": git_head(),
        "blockers": blockers,
        "current_status_row_count": int(len(frame)),
        "unique_ticker_count": int(frame["ticker"].nunique()) if "ticker" in frame else 0,
        "completed_63d_row_count": completed_63d,
        "cash_reconciliation_within_one_cent": cash_ok,
        "outputs": {name: fingerprint(output_dir / name) for name in products},
        "model_mutated": False,
        "score_mutated": False,
        "rank_mutated": False,
        "selector_mutated": False,
        "target_books_mutated": False,
        "cash_policy_mutated": False,
        "orders_generated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    write_json(output_dir / "policy_attribution_manifest.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-dir", default="outputs/run287_decision_outcome_ledger")
    parser.add_argument("--current-status")
    parser.add_argument("--output-dir")
    parser.add_argument("--generated-at-utc", default="2026-07-16T00:00:00Z")
    return parser.parse_args()


if __name__ == "__main__":
    result = run(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(2 if result["status"].startswith("BLOCKED") else 0)

#!/usr/bin/env python3
"""Run the pinned Run287 core selector as a current advisory-only audit.

The tool executes the exact official policy's single-date lane, hold/replace,
top-N, risk-cap, and sizing functions on the verified 2026-07-10 cross-section.
New entries are restricted to the registered 353-name eligible set.  Main is
run under both strict eligibility and a diagnostic prior-hold bridge so the six
newly ineligible legacy holdings cannot be silently sold or grandfathered.

Outputs are advisory projections and transition audits, never target books or
orders.  Historical post-book controls that require a policy-book sequence are
left for the next explicit gate; no backtest, fullrun, production, or live
trading path is called.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run287_pinned_git_import import pinned_import_context  # noqa: E402


SCHEMA_VERSION = "run287-current-advisory-selector-v1"
FORBIDDEN_COLUMNS = {
    "period_forward_return",
    "y_blend",
    "forward_return",
    "future_return",
    "future_21d_return",
    "future_63d_return",
    "future_126d_return",
}
SCENARIOS = (
    ("main", "strict_registered_current", 15, False),
    ("main", "prior_hold_transition_bridge", 15, True),
    ("concentrated", "strict_registered_current", 5, False),
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": bool(path.exists()),
        "bytes": int(path.stat().st_size) if path.exists() and path.is_file() else 0,
        "sha256": sha256(path) if path.exists() and path.is_file() else "",
    }


def expected_input(path: Path, expected: str, label: str) -> dict[str, Any]:
    audit = fingerprint(path)
    audit.update(
        {
            "label": label,
            "expected_sha256": expected,
            "hash_matches": bool(audit.get("sha256") == expected),
        }
    )
    return audit


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def verify_manifest_record(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    name: str,
) -> tuple[Path, dict[str, Any]]:
    record = (manifest.get("outputs") or {}).get(name) or {}
    raw = str(record.get("path") or "")
    path = Path(raw)
    if raw and not path.is_absolute():
        path = manifest_path.parent / path
    audit = fingerprint(path)
    expected = str(record.get("sha256") or "")
    audit.update(
        {
            "label": name,
            "expected_sha256": expected,
            "hash_matches": bool(expected and audit.get("sha256") == expected),
        }
    )
    if not audit["exists"] or not audit["hash_matches"]:
        raise ValueError(f"manifest record mismatch: {name}")
    return path, audit


def clean_tickers(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.upper().str.strip()


@contextmanager
def exact_environment(values: Mapping[str, Any]) -> Iterator[None]:
    prior = {str(key): os.environ.get(str(key)) for key in values}
    try:
        for key, value in values.items():
            os.environ[str(key)] = str(value or "")
        yield
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def merge_stack_precedence(context: pd.DataFrame, stack: pd.DataFrame) -> pd.DataFrame:
    left = context.copy()
    right = stack.copy()
    left["ticker"] = clean_tickers(left["ticker"])
    right["ticker"] = clean_tickers(right["ticker"])
    for column in right.columns:
        if column != "ticker" and column in left.columns:
            left = left.drop(columns=[column])
    return left.merge(right, on="ticker", how="inner", validate="one_to_one", sort=False)


def enrich_relative_strength_from_map(
    policy: Any,
    candidate: pd.DataFrame,
    prices: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Pinned enrich_relative_strength semantics with an immutable path map."""
    if candidate.empty:
        return candidate
    rows: list[pd.DataFrame] = []
    for raw_dt, month in candidate.groupby("rebalance_date", sort=True):
        dt = pd.Timestamp(raw_dt).normalize()
        frame = month.copy()
        benchmark_returns: dict[tuple[str, str], tuple[float, bool]] = {}
        for benchmark in policy.BENCHMARKS:
            price = prices.get(benchmark, pd.DataFrame())
            for label, (mode, amount) in policy.WINDOWS.items():
                benchmark_returns[(benchmark, label)] = policy.price_return_window(
                    price, dt, mode, amount
                )
        ticker_series = frame["ticker"].map(policy.clean_ticker)
        for label, (mode, amount) in policy.WINDOWS.items():
            ticker_returns: list[float] = []
            coverage: list[bool] = []
            for ticker in ticker_series:
                value, ready = policy.price_return_window(
                    prices.get(ticker, pd.DataFrame()), dt, mode, amount
                )
                fallback_columns = [
                    f"mom_{label}",
                    f"ret_{label}",
                    f"ticker_ret_{label}",
                ]
                if not ready:
                    fallback = next(
                        (
                            policy.safe_float(
                                frame.loc[ticker_series.eq(ticker), column].iloc[0]
                            )
                            for column in fallback_columns
                            if column in frame.columns
                        ),
                        0.0,
                    )
                    value = fallback
                ticker_returns.append(value)
                coverage.append(ready)
            frame[f"ticker_ret_{label}"] = ticker_returns
            frame[f"rs_price_coverage_{label}"] = coverage
            for benchmark in policy.BENCHMARKS:
                benchmark_return, _benchmark_ready = benchmark_returns[
                    (benchmark, label)
                ]
                frame[f"rs_{benchmark.lower()}_{label}"] = (
                    frame[f"ticker_ret_{label}"] - float(benchmark_return)
                )
            core_columns = [
                f"rs_{benchmark.lower()}_{label}"
                for benchmark in policy.CORE_BENCHMARKS
                if f"rs_{benchmark.lower()}_{label}" in frame.columns
            ]
            semis_columns = [
                f"rs_{benchmark.lower()}_{label}"
                for benchmark in policy.SEMIS_BENCHMARKS
                if f"rs_{benchmark.lower()}_{label}" in frame.columns
            ]
            if core_columns:
                frame[f"rs_benchmark_{label}"] = frame[core_columns].mean(axis=1)
            if semis_columns:
                frame[f"rs_semis_{label}"] = frame[semis_columns].mean(axis=1)
        frame["rs_price_coverage_flag"] = frame[
            [f"rs_price_coverage_{label}" for label in policy.WINDOWS]
        ].any(axis=1)
        frame["rs_benchmark_source"] = "verified_current_selector_price_map"
        rows.append(frame)
    return pd.concat(rows, ignore_index=True) if rows else candidate


def current_prior_book(book: pd.DataFrame) -> pd.DataFrame:
    dates = pd.to_datetime(book["rebalance_date"], errors="coerce")
    latest = dates.max()
    result = book.loc[dates.eq(latest)].copy()
    result["ticker"] = clean_tickers(result["ticker"])
    return result.loc[~result["ticker"].isin({"CASH", "__CASH__"})].copy()


def run_core_selector(
    policy: Any,
    *,
    month_input: pd.DataFrame,
    prior_book: pd.DataFrame,
    portfolio_kind: str,
    scenario: str,
    target_n: int,
    crisis_states: pd.DataFrame,
    prices: Mapping[str, pd.DataFrame],
    registered_eligible: set[str],
    apply_postbook: bool = False,
    stage_audit_sink: list[dict[str, Any]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    valuation = pd.Timestamp(month_input["rebalance_date"].iloc[0]).normalize()
    variant_id = f"advisory_{scenario}_{portfolio_kind}_N{target_n}"
    stage_sequence = 0

    def weight_map(rows: Any) -> dict[str, float]:
        records = rows.to_dict("records") if isinstance(rows, pd.DataFrame) else list(rows)
        result: dict[str, float] = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            ticker = policy.clean_ticker(record.get("ticker"))
            if not ticker:
                continue
            result[ticker] = policy.safe_float(
                record.get("weight"), policy.safe_float(record.get("target_weight"))
            )
        return result

    def apply_weight_stage(
        stage_name: str, function: Any, rows: Any, *stage_args: Any, **stage_kwargs: Any
    ) -> Any:
        nonlocal stage_sequence
        stage_sequence += 1
        before = weight_map(rows)
        result = function(rows, *stage_args, **stage_kwargs)
        after_rows = result[0] if isinstance(result, tuple) else result
        after = weight_map(after_rows)
        if stage_audit_sink is not None:
            for ticker in sorted(set(before) | set(after)):
                before_weight = before.get(ticker, 0.0)
                after_weight = after.get(ticker, 0.0)
                presence_changed = (ticker in before) != (ticker in after)
                if not presence_changed and abs(after_weight - before_weight) <= 1e-12:
                    continue
                transition = (
                    "added"
                    if ticker not in before and after_weight > 1e-12
                    else "removed"
                    if before_weight > 1e-12 and after_weight <= 1e-12
                    else "reweighted"
                )
                stage_audit_sink.append(
                    {
                        "date": valuation.date().isoformat(),
                        "scenario": scenario,
                        "portfolio_kind": portfolio_kind,
                        "stage_sequence": stage_sequence,
                        "stage_name": stage_name,
                        "ticker": ticker,
                        "before_weight": before_weight,
                        "after_weight": after_weight,
                        "weight_delta": after_weight - before_weight,
                        "transition": transition,
                        "execution_allowed": False,
                    }
                )
        return result

    month = policy.score_month(month_input.copy())
    crisis_row = policy.crisis_state_for_date(crisis_states, valuation)
    month = policy.apply_crisis_lane_policy(month, crisis_row, portfolio_kind)
    month = policy.apply_concentrated_leader_gate_annotations(
        month, portfolio_kind, target_n
    )
    score_sigma = float(
        pd.to_numeric(month["alphaops_vnext_score"], errors="coerce").std(ddof=0)
        or 0.0
    )
    score_median = float(
        pd.to_numeric(month["alphaops_vnext_score"], errors="coerce").median()
        or 0.0
    )
    month_records = month.to_dict("records")
    by_ticker = {
        policy.clean_ticker(record.get("ticker")): record for record in month_records
    }
    new_entry_records = [
        record
        for record in month_records
        if policy.clean_ticker(record.get("ticker")) in registered_eligible
    ]
    prior = {
        policy.clean_ticker(record.get("ticker")): record
        for record in prior_book.to_dict("records")
    }
    selected: list[dict[str, Any]] = []
    selected_tickers: set[str] = set()
    rejects: list[dict[str, Any]] = []
    emerging_count = 0
    for ticker, old in sorted(
        prior.items(), key=lambda item: -policy.safe_float(item[1].get("weight"))
    ):
        record = by_ticker.get(ticker)
        if not record:
            rejects.append(
                {
                    "date": valuation.date().isoformat(),
                    "scenario": scenario,
                    "portfolio_kind": portfolio_kind,
                    "ticker": ticker,
                    "rejection_reason": "not_in_current_policy_evaluation_universe",
                    "prior_holding": True,
                }
            )
            continue
        state_record = dict(record)
        state_record["shakeout_guard_prior_holding"] = True
        state, state_reason = policy.holding_state(
            state_record, score_median, score_sigma
        )
        if state == "EXIT":
            rejects.append(
                {
                    "date": valuation.date().isoformat(),
                    "scenario": scenario,
                    "portfolio_kind": portfolio_kind,
                    "ticker": ticker,
                    "rejection_reason": state_reason,
                    "prior_holding": True,
                }
            )
            continue
        allowed, reason = policy.allowed_candidate(
            record, portfolio_kind, emerging_count, is_new_buy=False
        )
        if not allowed:
            rejects.append(
                {
                    "date": valuation.date().isoformat(),
                    "scenario": scenario,
                    "portfolio_kind": portfolio_kind,
                    "ticker": ticker,
                    "rejection_reason": reason,
                    "prior_holding": True,
                }
            )
            continue
        output = dict(record)
        output["holding_state"] = state
        output["hold_replace_decision"] = "keep_prior_holding"
        output["holding_state_reason"] = state_reason
        output.update(policy.shakeout_guard_prod_telemetry(state_record, state_reason))
        output["prior_weight"] = policy.safe_float(old.get("weight"))
        output["leadership_persistence_hold_enabled"] = bool(
            policy.leadership_persistence_hold_enabled()
        )
        protected, protection_reason = policy.leadership_persistence_hold_protected(
            output, portfolio_kind=portfolio_kind
        )
        output["leadership_persistence_hold_protected"] = bool(
            policy.leadership_persistence_hold_enabled() and protected
        )
        output["leadership_persistence_hold_reason"] = protection_reason
        selected.append(output)
        selected_tickers.add(ticker)
        if str(record.get("primary_lane")) in {
            "EMERGING_TENBAGGER",
            "TOP7_MANAGER_DISCOVERY",
        }:
            emerging_count += 1
        if len(selected) >= target_n:
            break

    ranked = sorted(
        new_entry_records,
        key=lambda record: policy.safe_float(
            record.get("alphaops_vnext_weight_score"),
            policy.safe_float(record.get("alphaops_vnext_score")),
        ),
        reverse=True,
    )
    threshold_normal = max(0.15, 0.75 * max(score_sigma, 0.20))
    threshold_broken = max(0.08, 0.35 * max(score_sigma, 0.20))
    for record in ranked:
        ticker = policy.clean_ticker(record.get("ticker"))
        if not ticker or ticker in selected_tickers:
            continue
        allowed, reason = policy.allowed_candidate(
            record, portfolio_kind, emerging_count, is_new_buy=True
        )
        if not allowed:
            rejects.append(
                {
                    "date": valuation.date().isoformat(),
                    "scenario": scenario,
                    "portfolio_kind": portfolio_kind,
                    "ticker": ticker,
                    "rejection_reason": reason,
                    "prior_holding": False,
                }
            )
            continue
        output = dict(record)
        output["holding_state"] = "NEW"
        output["holding_state_reason"] = "new_candidate_cleared_vnext_gates"
        output["hold_replace_threshold_sigma"] = threshold_normal
        output["hold_replace_broken_threshold_sigma"] = threshold_broken
        output["hold_replace_decision"] = "new_entry"
        output["prior_weight"] = 0.0
        if len(selected) < target_n:
            selected.append(output)
            selected_tickers.add(ticker)
            if str(record.get("primary_lane")) in {
                "EMERGING_TENBAGGER",
                "TOP7_MANAGER_DISCOVERY",
            }:
                emerging_count += 1
            continue
        weakest_index = min(
            range(len(selected)),
            key=lambda index: policy.safe_float(
                selected[index].get("alphaops_vnext_score")
            ),
        )
        weakest = selected[weakest_index]
        required_gap, gap_reason, persistence_applied = (
            policy.replacement_gap_for_weakest(
                weakest,
                portfolio_kind=portfolio_kind,
                threshold_normal=threshold_normal,
                threshold_broken=threshold_broken,
                score_sigma=score_sigma,
            )
        )
        output["hold_replace_required_gap"] = required_gap
        output["hold_replace_required_gap_reason"] = gap_reason
        output["leadership_persistence_hold_applied_to_replacement_test"] = bool(
            persistence_applied
        )
        output["replacement_test_weakest_ticker"] = policy.clean_ticker(
            weakest.get("ticker")
        )
        output["replacement_test_weakest_score"] = policy.safe_float(
            weakest.get("alphaops_vnext_score")
        )
        if policy.safe_float(record.get("alphaops_vnext_score")) >= policy.safe_float(
            weakest.get("alphaops_vnext_score")
        ) + required_gap:
            rejects.append(
                {
                    "date": valuation.date().isoformat(),
                    "scenario": scenario,
                    "portfolio_kind": portfolio_kind,
                    "ticker": policy.clean_ticker(weakest.get("ticker")),
                    "rejection_reason": "replaced_by_higher_vnext_score",
                    "replacement_ticker": ticker,
                    "prior_holding": policy.clean_ticker(weakest.get("ticker"))
                    in prior,
                    "hold_replace_required_gap": required_gap,
                    "hold_replace_required_gap_reason": gap_reason,
                    "leadership_persistence_hold_applied": bool(
                        persistence_applied
                    ),
                }
            )
            selected_tickers.discard(policy.clean_ticker(weakest.get("ticker")))
            selected[weakest_index] = output
            selected_tickers.add(ticker)
        else:
            rejects.append(
                {
                    "date": valuation.date().isoformat(),
                    "scenario": scenario,
                    "portfolio_kind": portfolio_kind,
                    "ticker": ticker,
                    "rejection_reason": (
                        "leadership_persistence_hold_threshold_not_met"
                        if persistence_applied
                        else "hold_replace_threshold_not_met"
                    ),
                    "prior_holding": False,
                    "replacement_test_weakest_ticker": policy.clean_ticker(
                        weakest.get("ticker")
                    ),
                    "replacement_test_weakest_score": policy.safe_float(
                        weakest.get("alphaops_vnext_score")
                    ),
                    "candidate_score": policy.safe_float(
                        record.get("alphaops_vnext_score")
                    ),
                    "hold_replace_required_gap": required_gap,
                    "hold_replace_required_gap_reason": gap_reason,
                    "leadership_persistence_hold_applied": bool(
                        persistence_applied
                    ),
                }
            )

    cash_target = policy.crisis_cash_target(
        str(crisis_row.get("crisis_state") or "GREEN"), portfolio_kind
    )
    weighted = apply_weight_stage(
        "assign_weights", policy.assign_weights, selected, portfolio_kind, cash_target
    )
    weighted = apply_weight_stage(
        "apply_vnext_benchmark_guard",
        policy.apply_vnext_benchmark_guard,
        weighted,
        portfolio_kind=portfolio_kind,
        target_n=target_n,
        prices=dict(prices),
        rebalance_date=valuation,
    )
    weighted = apply_weight_stage(
        "apply_concentrated_risk_state_new_entry_cap",
        policy.apply_concentrated_risk_state_new_entry_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_main_high_volatility_new_entry_cap",
        policy.apply_main_high_volatility_new_entry_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_main_watch_unconfirmed_market_leader_new_entry_cap",
        policy.apply_main_watch_unconfirmed_market_leader_new_entry_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_main_green_bull_low_confirm_high_vol_new_entry_cap",
        policy.apply_main_green_bull_low_confirm_high_vol_new_entry_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_main_balanced_bull_qqq_damage_low_confirm_leader_cap",
        policy.apply_main_balanced_bull_qqq_damage_low_confirm_leader_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_main_balanced_neutral_soft_qqq_damage_weak_leader_cap",
        policy.apply_main_balanced_neutral_soft_qqq_damage_weak_leader_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_main_quality_bull_low_confirm_new_entry_cap",
        policy.apply_main_quality_bull_low_confirm_new_entry_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_main_green_neutral_cyclical_high_vol_new_entry_cap",
        policy.apply_main_green_neutral_cyclical_high_vol_new_entry_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_main_quality_hold_weak_timing_trim",
        policy.apply_main_quality_hold_weak_timing_trim,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_concentrated_hold_decay_trim",
        policy.apply_concentrated_hold_decay_trim,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_concentrated_watch_unconfirmed_high_vol_new_entry_cap",
        policy.apply_concentrated_watch_unconfirmed_high_vol_new_entry_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_concentrated_watch_unconfirmed_market_leader_new_entry_cap",
        policy.apply_concentrated_watch_unconfirmed_market_leader_new_entry_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_concentrated_watch_damaged_weak_market_leader_cap",
        policy.apply_concentrated_watch_damaged_weak_market_leader_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_concentrated_green_bull_qqq_down_new_entry_cap",
        policy.apply_concentrated_green_bull_qqq_down_new_entry_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_concentrated_green_consumer_overheat_new_entry_cap",
        policy.apply_concentrated_green_consumer_overheat_new_entry_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_concentrated_green_confirmed_market_leader_weak_rs_new_entry_cap",
        policy.apply_concentrated_green_confirmed_market_leader_weak_rs_new_entry_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_concentrated_green_neutral_cyclical_high_vol_new_entry_cap",
        policy.apply_concentrated_green_neutral_cyclical_high_vol_new_entry_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_concentrated_defense_neutral_quality_new_entry_cap",
        policy.apply_concentrated_defense_neutral_quality_new_entry_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_concentrated_unconfirmed_quality_bull_new_entry_cap",
        policy.apply_concentrated_unconfirmed_quality_bull_new_entry_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_concentrated_unconfirmed_high_vol_new_entry_cap",
        policy.apply_concentrated_unconfirmed_high_vol_new_entry_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_concentrated_high_vol_weak_timing_new_entry_cap",
        policy.apply_concentrated_high_vol_weak_timing_new_entry_cap,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_main_post_selection_topn_filter",
        policy.apply_main_post_selection_topn_filter,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_main_ai_capex_momentum_tilt",
        policy.apply_main_ai_capex_momentum_tilt,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_concentrated_score_sizing_reweight",
        policy.apply_concentrated_score_sizing_reweight,
        weighted,
        portfolio_kind,
    )
    weighted = apply_weight_stage(
        "apply_concentrated_replacement_quality_swap",
        policy.apply_concentrated_replacement_quality_swap,
        weighted,
        new_entry_records,
        portfolio_kind,
        rejects,
    )
    weighted = apply_weight_stage(
        "apply_concentrated_cashfunded_early_entry",
        policy.apply_concentrated_cashfunded_early_entry,
        weighted,
        new_entry_records,
        portfolio_kind,
    )

    prior_weights = {
        policy.clean_ticker(record.get("ticker")): policy.safe_float(
            record.get("weight")
        )
        for record in prior_book.to_dict("records")
    }
    full_rows = [
        policy.row_for_target(
            record,
            valuation,
            portfolio_kind,
            variant_id,
            target_n,
            crisis_row,
        )
        for record in weighted
    ]
    invested_before_postbook = sum(
        policy.safe_float(record.get("weight")) for record in full_rows
    )
    full_rows.append(
        {
            "rebalance_date": valuation.date().isoformat(),
            "ticker": "CASH",
            "Name": "Cash",
            "sector": "Cash",
            "weight": max(0.0, 1.0 - invested_before_postbook),
            "target_weight": max(0.0, 1.0 - invested_before_postbook),
            "portfolio_kind": portfolio_kind,
            "variant_id": variant_id,
            "target_n": int(target_n),
            "target_stock_names": int(target_n),
            "weighting_mode": "alphaops_vnext_score_power",
            "primary_lane": "CASH",
            "selection_reason": "advisory_residual_cash",
            "crisis_state": str(crisis_row.get("crisis_state") or "GREEN"),
            "crisis_overlay_status": str(
                crisis_row.get("crisis_overlay_status") or "applied"
            ),
        }
    )
    full_book = pd.DataFrame(full_rows)
    postbook_summaries: dict[str, Any] = {}
    if apply_postbook:
        full_book, capacity_summary, capacity_audit = apply_weight_stage(
            "apply_regime_capacity_overlay",
            policy.apply_regime_capacity_overlay,
            full_book,
            portfolio_kind=portfolio_kind,
        )
        postbook_summaries["regime_capacity_overlay"] = capacity_summary
        postbook_summaries["regime_capacity_audit_rows"] = int(
            len(capacity_audit)
        )
        if portfolio_kind == "main":
            full_book, churn_summary = apply_weight_stage(
                "apply_main_neutral_regime_churn_filter",
                policy.apply_main_neutral_regime_churn_filter,
                full_book,
                "main",
            )
            postbook_summaries["main_neutral_regime_churn_filter"] = churn_summary
            full_book, metals_summary = apply_weight_stage(
                "apply_neutral_metals_new_entry_block",
                policy.apply_neutral_metals_new_entry_block,
                full_book,
                "main",
            )
            postbook_summaries["neutral_metals_new_entry_block"] = metals_summary
            full_book, turnaround_summary = apply_weight_stage(
                "apply_main_defense_review_turnaround_new_entry_block",
                policy.apply_main_defense_review_turnaround_new_entry_block,
                full_book,
                "main",
            )
            postbook_summaries[
                "main_defense_review_turnaround_new_entry_block"
            ] = turnaround_summary
            full_book, balanced_summary = apply_weight_stage(
                "apply_main_defense_review_balanced_new_entry_block",
                policy.apply_main_defense_review_balanced_new_entry_block,
                full_book,
                "main",
            )
            postbook_summaries[
                "main_defense_review_balanced_new_entry_block"
            ] = balanced_summary
            if policy.main_fast_crash_hedge_enabled():
                raise RuntimeError(
                    "pinned environment unexpectedly enables path-dependent main fast-crash hedge"
                )
            postbook_summaries["main_fast_crash_hedge"] = {
                "status": "disabled_by_pinned_environment"
            }
        else:
            full_book, metals_summary = apply_weight_stage(
                "apply_neutral_metals_new_entry_block",
                policy.apply_neutral_metals_new_entry_block,
                full_book,
                "concentrated",
            )
            postbook_summaries["neutral_metals_new_entry_block"] = metals_summary
            full_book, benchmark_summary = apply_weight_stage(
                "apply_concentrated_green_benchmark_risk_cyclical_new_entry_block",
                policy.apply_concentrated_green_benchmark_risk_cyclical_new_entry_block,
                full_book,
                "concentrated",
            )
            postbook_summaries[
                "concentrated_green_benchmark_risk_cyclical_new_entry_block"
            ] = benchmark_summary

    selected_rows: list[dict[str, Any]] = []
    prior_cash_weight = max(0.0, 1.0 - sum(prior_weights.values()))
    for record in full_book.to_dict("records"):
        ticker = policy.clean_ticker(record.get("ticker"))
        selected_rows.append(
            {
                "date": valuation.date().isoformat(),
                "scenario": scenario,
                "portfolio_kind": portfolio_kind,
                "ticker": ticker,
                "advisory_weight": policy.safe_float(record.get("weight")),
                "prior_weight": (
                    prior_cash_weight
                    if ticker == "CASH"
                    else prior_weights.get(ticker, 0.0)
                ),
                "registered_eligible": ticker in registered_eligible,
                "prior_holding": ticker in prior_weights or ticker == "CASH",
                "holding_state": str(
                    record.get("holding_state")
                    or ("CASH" if ticker == "CASH" else "")
                ),
                "hold_replace_decision": str(
                    record.get("hold_replace_decision")
                    or ("residual_cash" if ticker == "CASH" else "")
                ),
                "holding_state_reason": str(
                    record.get("holding_state_reason") or ""
                ),
                "primary_lane": str(
                    record.get("primary_lane")
                    or ("CASH" if ticker == "CASH" else "")
                ),
                "leader_tier": str(record.get("leader_tier") or ""),
                "dual_leader_gate": bool(record.get("dual_leader_gate", False)),
                "alphaops_vnext_score": policy.safe_float(
                    record.get("alphaops_vnext_score")
                ),
                "alphaops_vnext_weight_score": policy.safe_float(
                    record.get("alphaops_vnext_weight_score"),
                    policy.safe_float(record.get("alphaops_vnext_score")),
                ),
                "selection_reason": str(
                    record.get("selection_reason")
                    or ("advisory_residual_cash" if ticker == "CASH" else "")
                ),
                "crisis_state": str(crisis_row.get("crisis_state") or "GREEN"),
                "execution_allowed": False,
            }
        )
    projection = pd.DataFrame(selected_rows)
    projection["weight_delta_vs_prior"] = (
        projection["advisory_weight"] - projection["prior_weight"]
    )
    all_tickers = sorted((set(prior_weights) | set(projection["ticker"])) - {"CASH"})
    selected_weights = projection.set_index("ticker")["advisory_weight"].to_dict()
    transitions = []
    for ticker in all_tickers:
        before = prior_weights.get(ticker, 0.0)
        after = float(selected_weights.get(ticker, 0.0))
        transitions.append(
            {
                "date": valuation.date().isoformat(),
                "scenario": scenario,
                "portfolio_kind": portfolio_kind,
                "ticker": ticker,
                "prior_weight": before,
                "advisory_weight": after,
                "weight_delta": after - before,
                "transition": "new_entry"
                if before <= 1e-12 and after > 1e-12
                else "exit"
                if before > 1e-12 and after <= 1e-12
                else "hold_or_reweight",
                "registered_eligible": ticker in registered_eligible,
                "execution_allowed": False,
            }
        )
    telemetry = {
        "scenario": scenario,
        "portfolio_kind": portfolio_kind,
        "target_n": target_n,
        "evaluation_pool_count": int(len(month)),
        "new_entry_pool_count": int(len(new_entry_records)),
        "prior_holding_count": int(len(prior_weights)),
        "selected_stock_count": int(projection["ticker"].ne("CASH").sum()),
        "cash_weight": float(
            projection.loc[projection["ticker"].eq("CASH"), "advisory_weight"].sum()
        ),
        "total_weight": float(projection["advisory_weight"].sum()),
        "score_sigma": score_sigma,
        "score_median": score_median,
        "crisis_state": str(crisis_row.get("crisis_state") or "GREEN"),
        "base_crisis_cash_target": cash_target,
        "rejection_count": int(len(rejects)),
        "postbook_controls_applied": bool(apply_postbook),
        "postbook_control_summaries": postbook_summaries,
    }
    return projection, pd.DataFrame(transitions), pd.DataFrame(rejects), telemetry


def deterministic_projection(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    columns = [
        "scenario",
        "portfolio_kind",
        "ticker",
        "advisory_weight",
        "prior_weight",
        "registered_eligible",
        "prior_holding",
        "holding_state",
        "hold_replace_decision",
        "primary_lane",
        "alphaops_vnext_score",
        "alphaops_vnext_weight_score",
        "crisis_state",
    ]
    a = left[columns].sort_values(["scenario", "portfolio_kind", "ticker"]).reset_index(drop=True)
    b = right[columns].sort_values(["scenario", "portfolio_kind", "ticker"]).reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(a, b, check_dtype=True, atol=1e-12, rtol=0.0)
        return True
    except AssertionError:
        return False


def blocked(
    output_dir: Path,
    *,
    failures: list[str],
    input_audits: Mapping[str, Any],
    started: float,
    valuation_date: str,
    selector_executed: bool = False,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED_CURRENT_ADVISORY_SELECTOR",
        "advisory_selector_passed": False,
        "contract_failures": failures,
        "blockers": failures,
        "valuation_price_cutoff_date": valuation_date,
        "research_only": True,
        "advisory_only": True,
        "execution_allowed": False,
        "score_sort_executed": bool(selector_executed),
        "rank_assignment_executed": False,
        "top_n_executed": bool(selector_executed),
        "selector_executed": bool(selector_executed),
        "position_sizing_executed": bool(selector_executed),
        "target_book_generation_allowed": False,
        "target_book_file_written": False,
        "target_books_mutated": False,
        "orders_generated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_requests_executed": 0,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "source_inputs": dict(input_audits),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "feature_manifest": repo_path(args.feature_manifest),
        "score_stack_manifest": repo_path(args.score_stack_manifest),
        "selector_contract_manifest": repo_path(args.selector_contract_manifest),
        "crisis_manifest": repo_path(args.crisis_manifest),
        "price_map_manifest": repo_path(args.price_map_manifest),
        "pinned_import_manifest": repo_path(args.pinned_import_manifest),
        "target_generation_manifest": repo_path(args.target_generation_manifest),
        "main_prior_book": repo_path(args.main_prior_book),
        "concentrated_prior_book": repo_path(args.concentrated_prior_book),
    }
    expected = {
        "feature_manifest": args.expected_feature_sha256,
        "score_stack_manifest": args.expected_score_stack_sha256,
        "selector_contract_manifest": args.expected_selector_contract_sha256,
        "crisis_manifest": args.expected_crisis_sha256,
        "price_map_manifest": args.expected_price_map_sha256,
        "pinned_import_manifest": args.expected_pinned_import_sha256,
        "target_generation_manifest": args.expected_target_generation_sha256,
        "main_prior_book": args.expected_main_prior_book_sha256,
        "concentrated_prior_book": args.expected_concentrated_prior_book_sha256,
    }
    input_audits = {
        name: expected_input(path, expected[name], name)
        for name, path in paths.items()
    }
    failures = [
        f"input_hash_mismatch:{name}"
        for name, row in input_audits.items()
        if not row.get("exists") or not row.get("hash_matches")
    ]
    if failures:
        return blocked(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=args.valuation_date,
        )

    manifests = {
        name: load_json(paths[name])
        for name in (
            "feature_manifest",
            "score_stack_manifest",
            "selector_contract_manifest",
            "crisis_manifest",
            "price_map_manifest",
            "pinned_import_manifest",
            "target_generation_manifest",
        )
    }
    required_statuses = {
        "score_stack_manifest": "READY_CURRENT_SCORE_STACK_ELIGIBILITY_AUDIT_NONRANKING",
        "selector_contract_manifest": "READY_CURRENT_SELECTOR_CONTRACT_AUDIT_NONSELECTING",
        "crisis_manifest": "READY_CURRENT_CRISIS_STATE_NONSELECTING",
        "price_map_manifest": "READY_CURRENT_SELECTOR_PRICE_MAP_NONSELECTING",
        "pinned_import_manifest": "READY_PINNED_POLICY_IMPORT_NONSELECTING",
    }
    for name, required in required_statuses.items():
        actual = manifests[name].get("status")
        if actual != required:
            failures.append(f"{name}_status:{actual}!={required}")
    pinned_commit = str(manifests["pinned_import_manifest"].get("pinned_source_commit") or "")
    if pinned_commit != args.expected_policy_commit:
        failures.append(f"pinned_commit:{pinned_commit}!={args.expected_policy_commit}")
    if manifests["target_generation_manifest"].get("code", {}).get("github_sha") != pinned_commit:
        failures.append("target_generation_policy_commit_mismatch")

    try:
        context_path, context_record = verify_manifest_record(
            paths["feature_manifest"], manifests["feature_manifest"], "pilot_selection_context"
        )
        stack_path, stack_record = verify_manifest_record(
            paths["score_stack_manifest"],
            manifests["score_stack_manifest"],
            "ticker_order_score_stack",
        )
        crisis_path, crisis_record = verify_manifest_record(
            paths["crisis_manifest"], manifests["crisis_manifest"], "current_crisis_state"
        )
        price_map_path, price_map_record = verify_manifest_record(
            paths["price_map_manifest"], manifests["price_map_manifest"], "selector_price_map"
        )
        input_audits.update(
            {
                "selection_context": context_record,
                "ticker_order_score_stack": stack_record,
                "current_crisis_state": crisis_record,
                "selector_price_map": price_map_record,
            }
        )
    except Exception as exc:
        failures.append(f"manifest_record:{type(exc).__name__}:{exc}")
        return blocked(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=args.valuation_date,
        )

    context = pd.read_parquet(context_path)
    stack = pd.read_csv(stack_path, low_memory=False)
    candidate = merge_stack_precedence(context, stack)
    candidate["rebalance_date"] = pd.Timestamp(args.valuation_date)
    forbidden_present = sorted(FORBIDDEN_COLUMNS & set(candidate.columns))
    if forbidden_present:
        failures.append(f"forbidden_future_columns:{','.join(forbidden_present)}")
    registered_mask = candidate["registered_ranking_eligible"].fillna(False).astype(bool)
    registered = set(candidate.loc[registered_mask, "ticker"])
    if len(candidate) != int(args.expected_context_count):
        failures.append(f"context_count:{len(candidate)}!={args.expected_context_count}")
    if len(registered) != int(args.expected_eligible_count):
        failures.append(f"eligible_count:{len(registered)}!={args.expected_eligible_count}")
    if "DD" in registered:
        failures.append("quarantined_dd_in_registered_set")
    crisis_states = pd.read_csv(crisis_path, low_memory=False)
    price_map = pd.read_csv(price_map_path, low_memory=False)
    main_prior = current_prior_book(pd.read_csv(paths["main_prior_book"], low_memory=False))
    concentrated_prior = current_prior_book(
        pd.read_csv(paths["concentrated_prior_book"], low_memory=False)
    )
    prior_by_kind = {"main": main_prior, "concentrated": concentrated_prior}
    prior_ineligible = {
        ticker
        for ticker in set(main_prior["ticker"]) | set(concentrated_prior["ticker"])
        if ticker not in registered
    }
    if len(prior_ineligible) != int(args.expected_prior_ineligible_count):
        failures.append(
            f"prior_ineligible_count:{len(prior_ineligible)}!={args.expected_prior_ineligible_count}"
        )
    if failures:
        return blocked(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=args.valuation_date,
        )

    environment = manifests["target_generation_manifest"].get("env") or {}
    projections_a: list[pd.DataFrame] = []
    projections_b: list[pd.DataFrame] = []
    transitions: list[pd.DataFrame] = []
    rejections: list[pd.DataFrame] = []
    telemetry_rows: list[dict[str, Any]] = []
    stage_audit_rows: list[dict[str, Any]] = []
    pit_rows: list[pd.DataFrame] = []
    runtime_modules = pd.DataFrame()
    try:
        with exact_environment(environment):
            with pinned_import_context(pinned_commit, REPO_ROOT) as loader:
                policy = importlib.import_module(
                    "tools.run_alphaops_vnext_policy_replay"
                )
                prices: dict[str, pd.DataFrame] = {}
                for record in price_map.to_dict("records"):
                    ticker = policy.clean_ticker(record.get("ticker"))
                    path = Path(str(record.get("path") or ""))
                    prices[ticker] = policy.load_price_series(path.parent, ticker)
                    if prices[ticker].empty:
                        raise ValueError(f"pinned price loader returned empty: {ticker}")
                candidate_pit, pit_audit = policy.enforce_pit_available(candidate)
                if not pit_audit.empty:
                    pit_rows.append(pit_audit)
                candidate_rs = enrich_relative_strength_from_map(
                    policy, candidate_pit, prices
                )
                eligible_frame = candidate_rs[
                    candidate_rs["ticker"].isin(registered)
                ].copy()
                bridge_frame = candidate_rs[
                    candidate_rs["ticker"].isin(registered | prior_ineligible)
                ].copy()
                for portfolio_kind, scenario, target_n, bridge in SCENARIOS:
                    month = bridge_frame if bridge else eligible_frame
                    prior_book = prior_by_kind[portfolio_kind]
                    projection_a, transition, rejection, telemetry = run_core_selector(
                        policy,
                        month_input=month,
                        prior_book=prior_book,
                        portfolio_kind=portfolio_kind,
                        scenario=scenario,
                        target_n=target_n,
                        crisis_states=crisis_states,
                        prices=prices,
                        registered_eligible=registered,
                        apply_postbook=True,
                        stage_audit_sink=stage_audit_rows,
                    )
                    projection_b, _transition_b, _rejection_b, _telemetry_b = run_core_selector(
                        policy,
                        month_input=month,
                        prior_book=prior_book,
                        portfolio_kind=portfolio_kind,
                        scenario=scenario,
                        target_n=target_n,
                        crisis_states=crisis_states,
                        prices=prices,
                        registered_eligible=registered,
                        apply_postbook=True,
                    )
                    projections_a.append(projection_a)
                    projections_b.append(projection_b)
                    transitions.append(transition)
                    rejections.append(rejection)
                    telemetry_rows.append(telemetry)
                runtime_modules = pd.DataFrame(loader.loaded)
    except Exception as exc:
        failures.append(f"pinned_selector_runtime:{type(exc).__name__}:{exc}")
        return blocked(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=args.valuation_date,
            selector_executed=True,
        )

    projection = pd.concat(projections_a, ignore_index=True)
    projection_repeat = pd.concat(projections_b, ignore_index=True)
    transition_frame = pd.concat(transitions, ignore_index=True)
    rejection_frame = pd.concat(rejections, ignore_index=True)
    telemetry_frame = pd.DataFrame(telemetry_rows)
    stage_audit_frame = pd.DataFrame(stage_audit_rows)
    deterministic = deterministic_projection(projection, projection_repeat)
    if not deterministic:
        failures.append("advisory_projection_nondeterministic")
    totals = projection.groupby(["scenario", "portfolio_kind"])[
        "advisory_weight"
    ].sum()
    if not bool(np.isclose(totals.to_numpy(dtype=float), 1.0, atol=1e-9).all()):
        failures.append("advisory_weight_conservation_failure")
    invalid_new = projection.loc[
        projection["ticker"].ne("CASH")
        & ~projection["registered_eligible"]
        & ~projection["prior_holding"]
    ]
    if not invalid_new.empty:
        failures.append(f"ineligible_new_entry_count:{len(invalid_new)}")
    if projection["ticker"].eq("DD").any():
        failures.append("quarantined_dd_selected")
    if failures:
        return blocked(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=args.valuation_date,
            selector_executed=True,
        )

    projection = projection.sort_values(
        ["portfolio_kind", "scenario", "advisory_weight"],
        ascending=[True, True, False],
    ).reset_index(drop=True)
    projection_path = output_dir / "advisory_policy_projection.csv"
    transition_path = output_dir / "advisory_transition_audit.csv"
    rejection_path = output_dir / "advisory_rejection_audit.csv"
    telemetry_path = output_dir / "advisory_scenario_summary.csv"
    stage_audit_path = output_dir / "advisory_policy_stage_audit.csv"
    runtime_path = output_dir / "pinned_selector_runtime_module_audit.csv"
    pit_path = output_dir / "pit_evidence_audit.csv"
    projection.to_csv(projection_path, index=False)
    transition_frame.to_csv(transition_path, index=False)
    rejection_frame.to_csv(rejection_path, index=False)
    telemetry_frame.to_csv(telemetry_path, index=False)
    stage_audit_frame.to_csv(stage_audit_path, index=False)
    runtime_modules.to_csv(runtime_path, index=False)
    pd.concat(pit_rows, ignore_index=True).to_csv(pit_path, index=False) if pit_rows else pd.DataFrame().to_csv(pit_path, index=False)

    scenario_summary = {
        f"{row['portfolio_kind']}:{row['scenario']}": {
            "selected_stock_count": int(row["selected_stock_count"]),
            "cash_weight": float(row["cash_weight"]),
            "evaluation_pool_count": int(row["evaluation_pool_count"]),
            "new_entry_pool_count": int(row["new_entry_pool_count"]),
            "crisis_state": str(row["crisis_state"]),
        }
        for row in telemetry_rows
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_CURRENT_FULL_POLICY_ADVISORY_REVIEW_REQUIRED",
        "advisory_selector_passed": True,
        "contract_failures": [],
        "valuation_price_cutoff_date": args.valuation_date,
        "pinned_policy_commit": pinned_commit,
        "scenario_summary": scenario_summary,
        "transition_contract": {
            "registered_new_entry_pool_count": int(len(registered)),
            "prior_ineligible_count": int(len(prior_ineligible)),
            "prior_ineligible_tickers": sorted(prior_ineligible),
            "strict_scenario": "ineligible prior holdings are absent and therefore exit",
            "bridge_scenario": "ineligible prior holdings may be evaluated only as prior holdings and never as new entries",
            "scenario_is_policy_sensitivity_not_parameter_grid": True,
        },
        "determinism": {
            "projection_rerun_match": deterministic,
            "tolerance": 1e-12,
        },
        "postbook_gate": {
            "postbook_controls_executed": True,
            "single_date_history_available": False,
            "history_dependent_churn_interpretation": "diagnostic_no_prior_policy_sequence_in_current_adapter",
            "final_current_advisory_claim_allowed": True,
            "execution_or_target_book_claim_allowed": False,
        },
        "policy_stage_audit": {
            "changed_weight_rows": int(len(stage_audit_frame)),
            "removed_rows": int(
                stage_audit_frame["transition"].eq("removed").sum()
                if "transition" in stage_audit_frame.columns
                else 0
            ),
            "row_level_stage_lineage_recorded": True,
        },
        "research_only": True,
        "advisory_only": True,
        "execution_allowed": False,
        "historical_cagr_mdd_evidence_changed": False,
        "score_sort_executed": True,
        "rank_assignment_executed": False,
        "top_n_executed": True,
        "selector_executed": True,
        "position_sizing_executed": True,
        "target_book_generation_allowed": False,
        "target_book_file_written": False,
        "target_books_mutated": False,
        "orders_generated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_requests_executed": 0,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "pit_universe_label_clean": False,
        "source_inputs": dict(input_audits),
        "pinned_runtime": {
            "loaded_module_count": int(len(runtime_modules)),
            "all_modules_from_pinned_git_objects": bool(
                runtime_modules["source_mode"].eq("pinned_git_object").all()
                and runtime_modules["source_commit"].eq(pinned_commit).all()
            ),
        },
        "outputs": {
            "advisory_policy_projection": fingerprint(projection_path),
            "advisory_transition_audit": fingerprint(transition_path),
            "advisory_rejection_audit": fingerprint(rejection_path),
            "advisory_scenario_summary": fingerprint(telemetry_path),
            "advisory_policy_stage_audit": fingerprint(stage_audit_path),
            "pinned_selector_runtime_module_audit": fingerprint(runtime_path),
            "pit_evidence_audit": fingerprint(pit_path),
        },
        "recommended_next_step": "compare strict and prior-hold bridge turnover, concentration, cash and policy reasons; retain both as advisory until a separate reviewed transition rule is chosen, with no target or order generation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    artifact = Path(
        r"H:\codex\tmp_r1000_grossfloor_20260625\outputs\run_28725350727_official_broker_artifact"
    )
    alphaops = artifact / "outputs/alphaops_vnext"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--feature-manifest",
        default="outputs/run287_feature_frame_full_selection_context_20260712_commit_61f1b36b/manifest.json",
    )
    parser.add_argument(
        "--expected-feature-sha256",
        default="54a5f3c14a6796859c7048cbd29c5a43cc67170197604c1efd4e19a35c859f82",
    )
    parser.add_argument(
        "--score-stack-manifest",
        default="outputs/run287_current_score_stack_audit_20260712_commit_09f76972/manifest.json",
    )
    parser.add_argument(
        "--expected-score-stack-sha256",
        default="2322a668a2b500f217b780ad28763e93ac5f6773a6f98b56438123caf561f2da",
    )
    parser.add_argument(
        "--selector-contract-manifest",
        default="outputs/run287_current_selector_contract_audit_20260712_commit_0d07efea/manifest.json",
    )
    parser.add_argument(
        "--expected-selector-contract-sha256",
        default="647475ceaf2109d7dc7c7dfd18865679de86dc5afd102a090481e118bab4a02f",
    )
    parser.add_argument(
        "--crisis-manifest",
        default="outputs/run287_current_crisis_state_20260712_commit_466b9baf/manifest.json",
    )
    parser.add_argument(
        "--expected-crisis-sha256",
        default="6d7b0f053fdbfaa52e5c70708465029884a9a77e48a2df458258e03822893c0e",
    )
    parser.add_argument(
        "--price-map-manifest",
        default="outputs/run287_current_selector_price_map_20260712_commit_86df01e0/manifest.json",
    )
    parser.add_argument(
        "--expected-price-map-sha256",
        default="cfb22d3b82ed32915973ee4f1ec3ea1d536f90de6dfc04f0a2d48327bcce92cf",
    )
    parser.add_argument(
        "--pinned-import-manifest",
        default="outputs/run287_pinned_policy_import_audit_20260712_commit_e871541c/manifest.json",
    )
    parser.add_argument(
        "--expected-pinned-import-sha256",
        default="b59db75e6eea74989fd72946cb3b72af65a401dddb5738970ddd2b3d4febab6d",
    )
    parser.add_argument(
        "--target-generation-manifest",
        default=str(alphaops / "target_generation_input_manifest.json"),
    )
    parser.add_argument(
        "--expected-target-generation-sha256",
        default="7451166d8132c7e3fbd3eb75f7ecdd095e86e482b9202c2e0e0a2b1189ba6ff7",
    )
    parser.add_argument(
        "--main-prior-book", default=str(alphaops / "official_main_target_book.csv")
    )
    parser.add_argument(
        "--expected-main-prior-book-sha256",
        default="3e863068e118af3f832b9490defc38baa9f4b0718e024e2870f44bd27a979f22",
    )
    parser.add_argument(
        "--concentrated-prior-book",
        default=str(alphaops / "official_concentrated_target_book.csv"),
    )
    parser.add_argument(
        "--expected-concentrated-prior-book-sha256",
        default="3fa0f6fa0aa41aa3ec830f476dae5e94882527a7f520531b80390bfbddb26a78",
    )
    parser.add_argument(
        "--expected-policy-commit",
        default="15176b588d5bb0792bce1df6367758d795a8a33a",
    )
    parser.add_argument("--valuation-date", default="2026-07-10")
    parser.add_argument("--expected-context-count", type=int, default=989)
    parser.add_argument("--expected-eligible-count", type=int, default=353)
    parser.add_argument("--expected-prior-ineligible-count", type=int, default=6)
    parser.add_argument(
        "--output-dir", default="outputs/run287_current_advisory_selector_20260712"
    )
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "advisory_selector_passed": payload.get(
                    "advisory_selector_passed"
                ),
                "scenario_summary": payload.get("scenario_summary", {}),
                "target_book_file_written": payload.get(
                    "target_book_file_written"
                ),
                "orders_generated": payload.get("orders_generated"),
            },
            sort_keys=True,
        )
    )
    return 0 if payload.get("advisory_selector_passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())

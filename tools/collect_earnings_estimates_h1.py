#!/usr/bin/env python3
"""H1 wrapper for the forward-estimate collector.

This module reuses the legacy network/vendor orchestration but replaces snapshot
normalization and revision calculation with fail-closed semantics from
``earnings_consensus_h1``. It is intentionally not wired into the scheduled
workflow yet; workflow activation is a separate reviewed change.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

import tools.collect_earnings_estimates_finnhub as legacy
from r1000_config import PHASE18_ESTIMATE_REVISION_COLUMNS
from tools.earnings_consensus_h1 import build_snapshot, optional_float


def _nullable_pct_change(current: Any, previous: Any) -> float | None:
    c = optional_float(current)
    p = optional_float(previous)
    if c is None or p is None or p == 0:
        return None
    return (c - p) / abs(p)


def parse_snapshot_row(
    ticker: str,
    *,
    fetch_date: pd.Timestamp,
    eps_payload: Any,
    revenue_payload: Any,
    earnings_payload: Any,
    recommendation_payload: Any,
    eps_estimate_access: bool = True,
    revenue_estimate_access: bool = True,
    fetch_source: str = "finnhub",
) -> dict[str, Any]:
    observed = pd.Timestamp(fetch_date)
    if observed.tzinfo is None:
        observed = observed.tz_localize("UTC")
    else:
        observed = observed.tz_convert("UTC")
    snapshot = build_snapshot(
        ticker,
        eps_payload=eps_payload,
        revenue_payload=revenue_payload,
        recommendation_payload=recommendation_payload,
        observed_at=observed.to_pydatetime(),
        collected_at=observed.to_pydatetime(),
        first_seen_at=observed.to_pydatetime(),
        fetch_source=fetch_source,
        eps_estimate_access=eps_estimate_access,
        revenue_estimate_access=revenue_estimate_access,
    )
    earnings, surprise_streak = legacy.latest_earnings_record(earnings_payload)
    actual = optional_float(earnings.get("actual"))
    surprise = optional_float(earnings.get("surprisePercent", earnings.get("surprise")))
    snapshot.update(
        {
            # Compatibility names consumed by the current pipeline.
            "as_of_date": observed.date().isoformat(),
            "available_from": snapshot.get("available_at"),
            "est_eps_fy1": snapshot.get("eps_fy1_avg"),
            "est_eps_fy2": snapshot.get("eps_fy2_avg"),
            "est_rev_fy1": snapshot.get("rev_fy1_avg"),
            "n_analysts": max(
                [
                    x
                    for x in (
                        snapshot.get("eps_fy1_analyst_count"),
                        snapshot.get("rev_fy1_analyst_count"),
                    )
                    if x is not None
                ],
                default=None,
            ),
            "est_dispersion": snapshot.get("eps_fy1_dispersion"),
            "actual_eps_last": actual,
            "actual_report_date": str(earnings.get("period") or "") or None,
            "earnings_surprise_last": surprise,
            "surprise_streak": int(surprise_streak),
        }
    )
    return snapshot


def _prior_same_period_value(
    group: pd.DataFrame,
    idx: int,
    *,
    value_column: str,
    period_column: str,
    days: int,
) -> float | None:
    current_date = group.loc[idx, "as_of_date"]
    current_period = group.loc[idx, period_column] if period_column in group.columns else None
    if pd.isna(current_date) or current_period in (None, "") or pd.isna(current_period):
        return None
    cutoff = current_date - pd.Timedelta(days=days)
    prior = group[(group.index < idx) & (group["as_of_date"] <= cutoff)]
    if period_column not in prior.columns:
        return None
    prior = prior[prior[period_column].astype(str) == str(current_period)]
    if prior.empty:
        return None
    value = pd.to_numeric(prior.iloc[-1].get(value_column), errors="coerce")
    return None if pd.isna(value) else float(value)


def compute_estimate_revision_features(
    snapshots: pd.DataFrame,
    *,
    as_of_date: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if snapshots.empty:
        return pd.DataFrame(), {"status": "blocked", "reason": "no_snapshot_rows"}
    d = snapshots.copy()
    required = {"ticker", "as_of_date", "available_from"}
    missing = sorted(required - set(d.columns))
    if missing:
        return pd.DataFrame(), {"status": "blocked", "reason": f"missing_required_columns:{','.join(missing)}"}

    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["as_of_date"] = pd.to_datetime(d["as_of_date"], errors="coerce", utc=True)
    d["available_from"] = pd.to_datetime(d["available_from"], errors="coerce", utc=True)
    if as_of_date:
        cutoff = pd.Timestamp(as_of_date)
        if cutoff.tzinfo is None:
            cutoff = cutoff.tz_localize("UTC")
        else:
            cutoff = cutoff.tz_convert("UTC")
        # A date-only cutoff means end-of-day UTC for research replay compatibility.
        if len(str(as_of_date)) <= 10:
            cutoff = cutoff + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        d = d[d["available_from"] <= cutoff]

    nullable_numeric = [
        "est_eps_fy1",
        "est_eps_fy2",
        "est_rev_fy1",
        "est_dispersion",
        "earnings_surprise_last",
        "recommendation_balance",
        "est_eps_revision_breadth",
        "surprise_streak",
        "has_forward_estimate",
    ]
    for column in nullable_numeric:
        if column not in d.columns:
            d[column] = pd.NA
        d[column] = pd.to_numeric(d[column], errors="coerce")

    for column in ["eps_fy1_period_end", "rev_fy1_period_end"]:
        if column not in d.columns:
            d[column] = pd.NA

    d = d[d["ticker"].ne("") & d["as_of_date"].notna() & d["available_from"].notna()]
    d = d.sort_values(["ticker", "as_of_date", "available_from"], kind="stable").reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    for _, group in d.groupby("ticker", sort=False):
        group = group.reset_index(drop=True)
        for idx, row in group.iterrows():
            current_eps = optional_float(row.get("est_eps_fy1"))
            current_rev = optional_float(row.get("est_rev_fy1"))
            current_dispersion = optional_float(row.get("est_dispersion"))
            prior_eps_30 = _prior_same_period_value(group, idx, value_column="est_eps_fy1", period_column="eps_fy1_period_end", days=30)
            prior_eps_90 = _prior_same_period_value(group, idx, value_column="est_eps_fy1", period_column="eps_fy1_period_end", days=90)
            prior_rev_30 = _prior_same_period_value(group, idx, value_column="est_rev_fy1", period_column="rev_fy1_period_end", days=30)
            prior_dispersion_30 = _prior_same_period_value(group, idx, value_column="est_dispersion", period_column="eps_fy1_period_end", days=30)

            eps_revision_30 = _nullable_pct_change(current_eps, prior_eps_30)
            eps_revision_90 = _nullable_pct_change(current_eps, prior_eps_90)
            rev_revision_30 = _nullable_pct_change(current_rev, prior_rev_30)
            dispersion_change_30 = (
                current_dispersion - prior_dispersion_30
                if current_dispersion is not None and prior_dispersion_30 is not None
                else None
            )

            out = row.to_dict()
            out.update(
                {
                    "est_eps_revision_30d": eps_revision_30,
                    "est_eps_revision_90d": eps_revision_90,
                    "est_rev_revision_30d": rev_revision_30,
                    "est_dispersion_change_30d": dispersion_change_30,
                    "revision_period_status": (
                        "SAME_PERIOD_COMPARABLE"
                        if any(x is not None for x in (eps_revision_30, eps_revision_90, rev_revision_30))
                        else "NO_SAME_PERIOD_LOOKBACK"
                    ),
                }
            )
            has_forward = optional_float(out.get("has_forward_estimate"))
            positive_revision = any(
                value is not None and value > 0
                for value in (eps_revision_30, eps_revision_90, rev_revision_30)
            )
            dispersion_ok = dispersion_change_30 is not None and dispersion_change_30 <= 0
            confirmed = bool(has_forward and has_forward > 0 and positive_revision and dispersion_ok)
            out["estimate_revision_confirmed"] = int(confirmed)
            out["estimate_revision_replacement_gate_pass"] = int(confirmed)
            # H1 does not create alpha leverage. H2 may study a multiplier later.
            out["estimate_revision_future_winner_multiplier"] = 1.0
            rows.append(out)

    out_df = pd.DataFrame(rows)
    for column in PHASE18_ESTIMATE_REVISION_COLUMNS:
        if column not in out_df.columns:
            out_df[column] = pd.NA
    summary = {
        "status": "completed",
        "schema_version": "forward-earnings-estimates-h1-v1",
        "input_rows": int(len(snapshots)),
        "output_rows": int(len(out_df)),
        "ticker_count": int(out_df["ticker"].nunique()) if not out_df.empty else 0,
        "forward_only": True,
        "missing_numeric_policy": "nullable_not_zero",
        "revision_period_policy": "same_fiscal_period_only",
        "recommendation_separate_from_revision_breadth": True,
        "backtest_acceptance_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    return out_df, summary


def main() -> None:
    legacy.parse_snapshot_row = parse_snapshot_row
    legacy.compute_estimate_revision_features = compute_estimate_revision_features
    legacy.main()


if __name__ == "__main__":
    main()

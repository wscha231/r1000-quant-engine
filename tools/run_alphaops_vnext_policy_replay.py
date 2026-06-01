#!/usr/bin/env python3
"""Build AlphaOps vNext production target books from historical candidates.

This is the production bridge for the lane/leader/crisis research work.  It
does not place live trades.  In ``replace_operating`` mode it replaces the
official broker-ledger target books so the subsequent broker replay and
``user_current`` report reflect vNext from the first historical rebalance date.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_candidate_lanes import lane_feature_mapping_payload, score_candidate_lanes  # noqa: E402
from r1000_market_leader_engine import BENCHMARKS, safe_float  # noqa: E402
from tools.run_broker_ledger_replay import DISABLE_CONCENTRATED_CHAMPION_FILTERS, replay as broker_replay  # noqa: E402
from tools.run_integrated_theme_leader_crisis_replay import (  # noqa: E402
    CRISIS_HYSTERESIS,
    CRISIS_SETTINGS,
    build_daily_crisis_state,
    crisis_state_audit,
)
from tools.run_market_leader_challenger import normalize_candidate_frame, read_table, resolve_candidate_book  # noqa: E402
from tools.run_user_current_report import build_report as build_user_current_report  # noqa: E402
from tools.run_weekly_evaluation import load_price_series, price_on_or_before  # noqa: E402


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/alphaops_vnext"
CASH_TICKERS = {"CASH", "__CASH__"}
CORE_BENCHMARKS = ("SPY", "QQQ")
SEMIS_BENCHMARKS = ("SMH", "SOXX")
WINDOWS = {
    "1w": ("days", 5),
    "1m": ("months", 1),
    "3m": ("months", 3),
    "6m": ("months", 6),
}
MAIN_VARIANTS = (12, 15, 18)
CONCENTRATED_VARIANTS = (3, 5)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> pd.DataFrame:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return frame


def clean_ticker(value: Any) -> str:
    text = str(value or "").upper().strip()
    return "" if text in {"", "NAN", "NONE"} else text


def date_text(value: Any) -> str:
    dt = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(dt) else pd.Timestamp(dt).date().isoformat()


def numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def robust_z(values: pd.Series) -> pd.Series:
    x = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if not x.notna().any():
        return pd.Series(0.0, index=values.index, dtype=float)
    med = float(x.median(skipna=True))
    mad = float((x - med).abs().median(skipna=True))
    if math.isfinite(mad) and mad > 1e-12:
        return ((x - med) / (1.4826 * mad)).fillna(0.0).clip(-6, 6)
    std = float(x.std(skipna=True, ddof=0))
    denom = std if math.isfinite(std) and std > 1e-12 else 1.0
    return ((x - med) / denom).fillna(0.0).clip(-6, 6)


def price_return_window(px: pd.DataFrame, as_of_date: Any, mode: str, amount: int) -> tuple[float, bool]:
    if px.empty:
        return 0.0, False
    end_dt, end_px = price_on_or_before(px, as_of_date, "close")
    if end_dt is None or end_px is None:
        return 0.0, False
    if mode == "days":
        start_target = pd.Timestamp(end_dt) - pd.Timedelta(days=int(amount))
    else:
        start_target = pd.Timestamp(end_dt) - pd.DateOffset(months=int(amount))
    start_dt, start_px = price_on_or_before(px, start_target, "close")
    if start_dt is None or start_px is None or start_px <= 0:
        return 0.0, False
    return float(end_px / start_px - 1.0), True


def price_map(price_cache: Path, candidate: pd.DataFrame) -> dict[str, pd.DataFrame]:
    tickers = {clean_ticker(x) for x in candidate.get("ticker", pd.Series(dtype=str)).dropna().unique()}
    tickers.update(BENCHMARKS)
    tickers = {t for t in tickers if t and t not in CASH_TICKERS}
    return {ticker: load_price_series(price_cache, ticker) for ticker in sorted(tickers)}


def enrich_relative_strength(candidate: pd.DataFrame, price_cache: Path) -> pd.DataFrame:
    if candidate.empty:
        return candidate
    prices = price_map(price_cache, candidate)
    rows: list[pd.DataFrame] = []
    for raw_dt, month in candidate.groupby("rebalance_date", sort=True):
        dt = pd.Timestamp(raw_dt).normalize()
        d = month.copy()
        benchmark_returns: dict[tuple[str, str], tuple[float, bool]] = {}
        for bench in BENCHMARKS:
            px = prices.get(bench, pd.DataFrame())
            for label, (mode, amount) in WINDOWS.items():
                benchmark_returns[(bench, label)] = price_return_window(px, dt, mode, amount)
        for label, (mode, amount) in WINDOWS.items():
            ticker_returns: list[float] = []
            coverage: list[bool] = []
            for ticker in d["ticker"].map(clean_ticker):
                ret, ok = price_return_window(prices.get(ticker, pd.DataFrame()), dt, mode, amount)
                fallback_cols = [f"mom_{label}", f"ret_{label}", f"ticker_ret_{label}"]
                if not ok:
                    fallback = next((safe_float(d.loc[d["ticker"].map(clean_ticker).eq(ticker), col].iloc[0]) for col in fallback_cols if col in d.columns), 0.0)
                    ret = fallback
                ticker_returns.append(ret)
                coverage.append(ok)
            d[f"ticker_ret_{label}"] = ticker_returns
            d[f"rs_price_coverage_{label}"] = coverage
            for bench in BENCHMARKS:
                bench_ret, _bench_ok = benchmark_returns[(bench, label)]
                d[f"rs_{bench.lower()}_{label}"] = d[f"ticker_ret_{label}"] - float(bench_ret)
            core_cols = [f"rs_{bench.lower()}_{label}" for bench in CORE_BENCHMARKS if f"rs_{bench.lower()}_{label}" in d.columns]
            semis_cols = [f"rs_{bench.lower()}_{label}" for bench in SEMIS_BENCHMARKS if f"rs_{bench.lower()}_{label}" in d.columns]
            if core_cols:
                d[f"rs_benchmark_{label}"] = d[core_cols].mean(axis=1)
            if semis_cols:
                d[f"rs_semis_{label}"] = d[semis_cols].mean(axis=1)
        d["rs_price_coverage_flag"] = d[[f"rs_price_coverage_{label}" for label in WINDOWS]].any(axis=1)
        d["rs_benchmark_source"] = "price_cache_or_candidate_fallback"
        rows.append(d)
    return pd.concat(rows, ignore_index=True) if rows else candidate


def enforce_pit_available(candidate: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Zero evidence fields whose availability is after the signal date."""

    if candidate.empty:
        return candidate, pd.DataFrame()
    d = candidate.copy()
    if "rebalance_date" not in d.columns:
        return d, pd.DataFrame()
    signal_dt = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    availability_cols = [col for col in ["available_from", "latest_available_from", "evidence_available_from"] if col in d.columns]
    if not availability_cols:
        d["pit_evidence_blocked"] = False
        return d, pd.DataFrame()
    blocked = pd.Series(False, index=d.index)
    for col in availability_cols:
        available = pd.to_datetime(d[col], errors="coerce").dt.normalize()
        blocked = blocked | (available.notna() & signal_dt.notna() & available.gt(signal_dt))
    evidence_cols = [
        col
        for col in d.columns
        if col.startswith(("sec_", "etf_", "top7_", "post_disclosure_"))
        or col in {"issuer_float_impact_score", "top_manager_discovery_score"}
    ]
    for col in evidence_cols:
        d.loc[blocked, col] = 0.0
    d["pit_evidence_blocked"] = blocked
    d["pit_evidence_block_reason"] = np.where(blocked, "evidence_available_after_rebalance_date", "")
    audit_cols = ["rebalance_date", "ticker", *availability_cols, "pit_evidence_blocked", "pit_evidence_block_reason"]
    return d, d.loc[blocked, [col for col in audit_cols if col in d.columns]].copy()


def alphaops_score(frame: pd.DataFrame) -> pd.Series:
    return (
        pd.to_numeric(frame.get("lane_confidence", 0.0), errors="coerce").fillna(0.0)
        + 0.18 * robust_z(numeric(frame, "market_leader_lane_score")).clip(lower=0.0)
        + 0.12 * robust_z(numeric(frame, "valuation_support_score")).clip(lower=0.0)
        + 0.12 * robust_z(numeric(frame, "rs_benchmark_1w")).clip(lower=0.0)
        + 0.10 * robust_z(numeric(frame, "rs_semis_3m")).clip(lower=0.0)
        + 0.08 * pd.to_numeric(frame.get("top7_support_boost", 0.0), errors="coerce").fillna(0.0)
    )


def score_month(month: pd.DataFrame) -> pd.DataFrame:
    d = score_candidate_lanes(month.copy())
    d["alphaops_vnext_score"] = alphaops_score(d)
    d["dual_leader_gate"] = (
        numeric(d, "rs_spy_3m").gt(0.0)
        & numeric(d, "rs_qqq_3m").gt(0.0)
        & (numeric(d, "rs_spy_6m").gt(0.0) | numeric(d, "rs_qqq_6m").gt(0.0))
    )
    d["negative_fcf_risk_cap"] = numeric(d, "emerging_tenbagger_risk_cap", 1.0)
    return d


def first_text(row: dict[str, Any] | pd.Series, columns: tuple[str, ...], default: str = "unknown") -> str:
    for col in columns:
        value = str(row.get(col) or "").strip()
        if value and value.lower() not in {"nan", "none"}:
            return value
    return default


def holding_state(row: dict[str, Any], score_median: float, score_sigma: float) -> tuple[str, str]:
    lane = str(row.get("primary_lane") or "")
    score = safe_float(row.get("alphaops_vnext_score"))
    hard_reject = str(row.get("emerging_tenbagger_hard_reject_reason") or "")
    price_alive = safe_float(row.get("price_above_ma200"), 1.0) + safe_float(row.get("price_above_ma50"), 1.0)
    if hard_reject or bool(row.get("top7_standalone_blocked")):
        return "EXIT", hard_reject or "top7_support_without_confirmation"
    if price_alive <= 0.0:
        return "EXIT", "price_trend_not_alive"
    if score < score_median - max(score_sigma, 0.25):
        return "TRIM", "score_below_monthly_peer_band"
    if numeric(pd.DataFrame([row]), "rs_benchmark_1w").iloc[0] < 0 and numeric(pd.DataFrame([row]), "rs_benchmark_3m").iloc[0] < 0:
        return "WARNING", "short_and_medium_relative_strength_negative"
    if lane == "EMERGING_TENBAGGER" and safe_float(row.get("negative_fcf_risk_cap"), 1.0) < 0.75:
        return "WARNING", "emerging_negative_fcf_or_dilution_risk_cap"
    return "HOLD", "vnext_score_and_risk_intact"


def crisis_state_for_date(crisis_states: pd.DataFrame, dt: pd.Timestamp) -> dict[str, Any]:
    if crisis_states.empty or "date" not in crisis_states.columns:
        return {"crisis_state": "GREEN", "crisis_overlay_status": "missing"}
    d = crisis_states.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    eligible = d[d["date"].le(dt.normalize())]
    if eligible.empty:
        return {"crisis_state": "GREEN", "crisis_overlay_status": "before_first_state"}
    row = eligible.sort_values("date").iloc[-1].to_dict()
    row["crisis_overlay_status"] = "applied"
    return row


def crisis_cash_target(state: str, portfolio_kind: str) -> float:
    base = float(CRISIS_SETTINGS.get(state, CRISIS_SETTINGS["GREEN"]).get("cash", 0.03))
    if portfolio_kind == "concentrated" and state == "CRISIS_DEFENSE":
        return max(base, 0.35)
    return min(max(base, 0.0), 0.50)


def allowed_candidate(rec: dict[str, Any], portfolio_kind: str, emerging_count: int) -> tuple[bool, str]:
    ticker = clean_ticker(rec.get("ticker"))
    if not ticker or ticker in CASH_TICKERS:
        return False, "invalid_ticker"
    if str(rec.get("emerging_tenbagger_hard_reject_reason") or ""):
        return False, str(rec.get("emerging_tenbagger_hard_reject_reason"))
    if bool(rec.get("pit_evidence_blocked")) and max(
        safe_float(rec.get("rs_benchmark_1w")),
        safe_float(rec.get("rs_benchmark_3m")),
        safe_float(rec.get("rs_benchmark_6m")),
        safe_float(rec.get("theme_phase_multiplier_primary")),
        safe_float(rec.get("relative_strength_composite")),
    ) <= 0.05:
        return False, "pit_future_evidence_blocked_without_independent_confirmation"
    if bool(rec.get("top7_standalone_blocked")):
        return False, "top7_support_without_price_or_theme_confirmation"
    lane = str(rec.get("primary_lane") or "")
    if portfolio_kind == "concentrated":
        if lane in {"EMERGING_TENBAGGER", "TOP7_MANAGER_DISCOVERY"}:
            if emerging_count >= 1:
                return False, "concentrated_emerging_or_top7_seat_cap"
        elif not bool(rec.get("dual_leader_gate")):
            return False, "concentrated_requires_dual_leader"
    return True, ""


def cap_group_key(row: dict[str, Any], kind: str) -> str:
    if kind == "theme":
        return first_text(row, ("leader_broad_theme", "theme_horizon_primary", "theme_phase_primary", "industry_group", "sector"))
    return first_text(row, ("leader_subindustry", "subindustry", "sub_industry", "industry_group", "industry", "sector"))


def target_caps(portfolio_kind: str) -> dict[str, float]:
    if portfolio_kind == "concentrated":
        return {"single": 0.35, "subindustry": 0.70, "theme": 1.0}
    return {"single": 0.15, "subindustry": 0.40, "theme": 0.60}


def assign_weights(selected: list[dict[str, Any]], portfolio_kind: str, cash_target: float) -> list[dict[str, Any]]:
    if not selected:
        return []
    caps = target_caps(portfolio_kind)
    gross = min(max(1.0 - cash_target, 0.0), 1.0)
    scores = pd.Series([safe_float(row.get("alphaops_vnext_score")) for row in selected], dtype=float)
    raw = (scores - float(scores.min()) + 0.25).clip(lower=1e-6) ** 2
    raw = raw / max(float(raw.sum()), 1e-12) * gross
    weights = {clean_ticker(row.get("ticker")): min(float(raw.iloc[i]), caps["single"]) for i, row in enumerate(selected)}
    for _ in range(6):
        sub_totals: dict[str, float] = {}
        theme_totals: dict[str, float] = {}
        for row in selected:
            ticker = clean_ticker(row.get("ticker"))
            sub_totals[cap_group_key(row, "subindustry")] = sub_totals.get(cap_group_key(row, "subindustry"), 0.0) + weights.get(ticker, 0.0)
            theme_totals[cap_group_key(row, "theme")] = theme_totals.get(cap_group_key(row, "theme"), 0.0) + weights.get(ticker, 0.0)
        changed = False
        for row in selected:
            ticker = clean_ticker(row.get("ticker"))
            sub = cap_group_key(row, "subindustry")
            theme = cap_group_key(row, "theme")
            cap = min(caps["single"], max(0.0, weights[ticker] + caps["subindustry"] - sub_totals[sub]), max(0.0, weights[ticker] + caps["theme"] - theme_totals[theme]))
            if weights[ticker] > cap + 1e-12:
                weights[ticker] = cap
                changed = True
        residual = gross - sum(weights.values())
        if residual <= 1e-8:
            break
        rooms: list[tuple[str, float]] = []
        sub_totals = {}
        theme_totals = {}
        for row in selected:
            ticker = clean_ticker(row.get("ticker"))
            sub_totals[cap_group_key(row, "subindustry")] = sub_totals.get(cap_group_key(row, "subindustry"), 0.0) + weights.get(ticker, 0.0)
            theme_totals[cap_group_key(row, "theme")] = theme_totals.get(cap_group_key(row, "theme"), 0.0) + weights.get(ticker, 0.0)
        for row in selected:
            ticker = clean_ticker(row.get("ticker"))
            sub = cap_group_key(row, "subindustry")
            theme = cap_group_key(row, "theme")
            room = min(caps["single"] - weights[ticker], caps["subindustry"] - sub_totals[sub], caps["theme"] - theme_totals[theme])
            if room > 1e-9:
                rooms.append((ticker, room))
        if not rooms or not changed and residual < 1e-6:
            break
        add_each = residual / max(len(rooms), 1)
        for ticker, room in rooms:
            weights[ticker] += min(room, add_each)
    out: list[dict[str, Any]] = []
    for row in selected:
        ticker = clean_ticker(row.get("ticker"))
        weight = max(0.0, weights.get(ticker, 0.0))
        if weight <= 1e-12:
            continue
        item = dict(row)
        item["weight"] = weight
        item["target_weight"] = weight
        item["effective_single_weight_cap"] = caps["single"]
        item["subindustry_cap"] = caps["subindustry"]
        item["theme_cap"] = caps["theme"]
        out.append(item)
    return out


def row_for_target(rec: dict[str, Any], dt: pd.Timestamp, portfolio_kind: str, variant_id: str, target_n: int, crisis_row: dict[str, Any]) -> dict[str, Any]:
    ticker = clean_ticker(rec.get("ticker"))
    return {
        **rec,
        "rebalance_date": dt.date().isoformat(),
        "ticker": ticker,
        "weight": safe_float(rec.get("weight")),
        "target_weight": safe_float(rec.get("target_weight"), safe_float(rec.get("weight"))),
        "portfolio_kind": portfolio_kind,
        "variant_id": variant_id,
        "target_n": int(target_n),
        "target_stock_names": int(target_n),
        "weighting_mode": "alphaops_vnext_score_power",
        "active_rebalance_interval_months": 1,
        "operating_target_source": "alphaops_vnext_policy_replay",
        "operating_decision_semantics": "historical_vnext_policy_from_candidate_replay_book",
        "decision_frequency": "monthly_replay_plus_crisis_hysteresis",
        "production_policy": "alphaops_vnext_production",
        "selection_reason": str(rec.get("selection_reason") or rec.get("primary_lane") or "alphaops_vnext_score"),
        "crisis_state": str(crisis_row.get("crisis_state") or "GREEN"),
        "crisis_overlay_status": str(crisis_row.get("crisis_overlay_status") or "applied"),
        "crisis_hysteresis_minimum_action_gap_days": CRISIS_HYSTERESIS["minimum_action_gap_days"],
        "current_holdings_source": "alphaops_vnext_policy_target_book",
    }


def build_variant_book(
    candidate: pd.DataFrame,
    *,
    portfolio_kind: str,
    target_n: int,
    crisis_states: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    variant_id = f"alphaops_vnext_{portfolio_kind}_N{target_n}"
    rows: list[dict[str, Any]] = []
    lane_rows: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    exposure_rows: list[dict[str, Any]] = []
    prev: dict[str, dict[str, Any]] = {}
    for raw_dt in sorted(pd.to_datetime(candidate["rebalance_date"], errors="coerce").dropna().unique()):
        dt = pd.Timestamp(raw_dt).normalize()
        month = score_month(candidate[candidate["rebalance_date"].eq(dt)].copy())
        if month.empty:
            continue
        score_sigma = float(pd.to_numeric(month["alphaops_vnext_score"], errors="coerce").std(ddof=0) or 0.0)
        score_median = float(pd.to_numeric(month["alphaops_vnext_score"], errors="coerce").median() or 0.0)
        month_records = month.to_dict("records")
        lane_rows.extend([{**rec, "rebalance_date": dt.date().isoformat()} for rec in month_records])
        by_ticker = {clean_ticker(rec.get("ticker")): rec for rec in month_records}
        selected: list[dict[str, Any]] = []
        selected_tickers: set[str] = set()
        emerging_count = 0
        for ticker, old in sorted(prev.items(), key=lambda item: -safe_float(item[1].get("weight"))):
            rec = by_ticker.get(ticker)
            if not rec:
                continue
            state, state_reason = holding_state(rec, score_median, score_sigma)
            if state == "EXIT":
                rejects.append({"rebalance_date": dt.date().isoformat(), "ticker": ticker, "portfolio_kind": portfolio_kind, "variant_id": variant_id, "rejection_reason": state_reason, "prior_holding": True})
                continue
            ok, reason = allowed_candidate(rec, portfolio_kind, emerging_count)
            if not ok:
                rejects.append({"rebalance_date": dt.date().isoformat(), "ticker": ticker, "portfolio_kind": portfolio_kind, "variant_id": variant_id, "rejection_reason": reason, "prior_holding": True})
                continue
            out = dict(rec)
            out["holding_state"] = state
            out["hold_replace_decision"] = "keep_prior_holding"
            out["holding_state_reason"] = state_reason
            out["prior_weight"] = safe_float(old.get("weight"))
            selected.append(out)
            selected_tickers.add(ticker)
            if str(rec.get("primary_lane")) in {"EMERGING_TENBAGGER", "TOP7_MANAGER_DISCOVERY"}:
                emerging_count += 1
            if len(selected) >= target_n:
                break
        ranked = sorted(month_records, key=lambda rec: safe_float(rec.get("alphaops_vnext_score")), reverse=True)
        threshold_normal = max(0.15, 0.75 * max(score_sigma, 0.20))
        threshold_broken = max(0.08, 0.35 * max(score_sigma, 0.20))
        for rec in ranked:
            ticker = clean_ticker(rec.get("ticker"))
            if not ticker or ticker in selected_tickers:
                continue
            ok, reason = allowed_candidate(rec, portfolio_kind, emerging_count)
            if not ok:
                rejects.append({"rebalance_date": dt.date().isoformat(), "ticker": ticker, "portfolio_kind": portfolio_kind, "variant_id": variant_id, "rejection_reason": reason, "prior_holding": False})
                continue
            out = dict(rec)
            out["holding_state"] = "NEW"
            out["holding_state_reason"] = "new_candidate_cleared_vnext_gates"
            out["hold_replace_threshold_sigma"] = threshold_normal
            out["hold_replace_broken_threshold_sigma"] = threshold_broken
            out["hold_replace_decision"] = "new_entry"
            if len(selected) < target_n:
                selected.append(out)
                selected_tickers.add(ticker)
                if str(rec.get("primary_lane")) in {"EMERGING_TENBAGGER", "TOP7_MANAGER_DISCOVERY"}:
                    emerging_count += 1
                continue
            weakest_idx = min(range(len(selected)), key=lambda i: safe_float(selected[i].get("alphaops_vnext_score")))
            weakest = selected[weakest_idx]
            weak_state = str(weakest.get("holding_state") or "")
            required_gap = threshold_broken if weak_state in {"WARNING", "TRIM"} else threshold_normal
            if safe_float(rec.get("alphaops_vnext_score")) >= safe_float(weakest.get("alphaops_vnext_score")) + required_gap:
                rejects.append({"rebalance_date": dt.date().isoformat(), "ticker": clean_ticker(weakest.get("ticker")), "portfolio_kind": portfolio_kind, "variant_id": variant_id, "rejection_reason": "replaced_by_higher_vnext_score", "replacement_ticker": ticker, "prior_holding": clean_ticker(weakest.get("ticker")) in prev})
                selected_tickers.discard(clean_ticker(weakest.get("ticker")))
                selected[weakest_idx] = out
                selected_tickers.add(ticker)
            else:
                rejects.append({"rebalance_date": dt.date().isoformat(), "ticker": ticker, "portfolio_kind": portfolio_kind, "variant_id": variant_id, "rejection_reason": "hold_replace_threshold_not_met", "prior_holding": False})
        crisis_row = crisis_state_for_date(crisis_states, dt)
        cash_target = crisis_cash_target(str(crisis_row.get("crisis_state") or "GREEN"), portfolio_kind)
        weighted = assign_weights(selected, portfolio_kind, cash_target)
        prev = {clean_ticker(row.get("ticker")): row for row in weighted}
        lane_totals: dict[str, float] = {}
        for rec in weighted:
            lane = str(rec.get("primary_lane") or "")
            lane_totals[lane] = lane_totals.get(lane, 0.0) + safe_float(rec.get("weight"))
            rows.append(row_for_target(rec, dt, portfolio_kind, variant_id, target_n, crisis_row))
        invested = sum(safe_float(rec.get("weight")) for rec in weighted)
        cash_weight = max(0.0, 1.0 - invested)
        if cash_weight > 1e-8:
            rows.append(
                {
                    "rebalance_date": dt.date().isoformat(),
                    "ticker": "CASH",
                    "Name": "Cash",
                    "sector": "Cash",
                    "weight": cash_weight,
                    "target_weight": cash_weight,
                    "portfolio_kind": portfolio_kind,
                    "variant_id": variant_id,
                    "target_n": int(target_n),
                    "target_stock_names": int(target_n),
                    "weighting_mode": "alphaops_vnext_score_power",
                    "primary_lane": "CASH",
                    "operating_target_source": "alphaops_vnext_policy_replay",
                    "production_policy": "alphaops_vnext_production",
                    "selection_reason": "cash_from_crisis_overlay_or_position_caps",
                    "crisis_state": str(crisis_row.get("crisis_state") or "GREEN"),
                    "crisis_overlay_status": str(crisis_row.get("crisis_overlay_status") or "applied"),
                    "current_holdings_source": "alphaops_vnext_policy_target_book",
                }
            )
        exposure_rows.append({"rebalance_date": dt.date().isoformat(), "portfolio_kind": portfolio_kind, "variant_id": variant_id, "cash_weight": cash_weight, **lane_totals})
    target = pd.DataFrame(rows)
    if not target.empty:
        target["rebalance_date"] = pd.to_datetime(target["rebalance_date"], errors="coerce").dt.date.astype(str)
        target = target.sort_values(["rebalance_date", "weight"], ascending=[True, False]).reset_index(drop=True)
    return target, pd.DataFrame(lane_rows), pd.DataFrame(rejects), pd.DataFrame(exposure_rows)


def copy_operating_books(latest_run: Path, main_book: pd.DataFrame, concentrated_book: pd.DataFrame) -> dict[str, str]:
    reports = latest_run / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    main_path = reports / "operating_main_target_book.csv"
    concentrated_path = reports / "operating_concentrated_target_book.csv"
    write_csv(main_path, main_book)
    write_csv(concentrated_path, concentrated_book)
    return {"main": str(main_path), "concentrated": str(concentrated_path)}


def run_broker_replays(args: argparse.Namespace, latest_run: Path) -> dict[str, Any]:
    price_cache = repo_path(args.price_cache)
    metrics: dict[str, Any] = {}
    specs = [
        ("main", latest_run / "reports" / "operating_main_target_book.csv", latest_run / "broker_replay" / "main", None),
        ("concentrated", latest_run / "reports" / "operating_concentrated_target_book.csv", latest_run / "broker_replay" / "concentrated", DISABLE_CONCENTRATED_CHAMPION_FILTERS.copy()),
    ]
    for portfolio_kind, target_book, output_dir, filters in specs:
        metrics[portfolio_kind] = broker_replay(
            target_book=target_book,
            price_cache=price_cache,
            output_dir=output_dir,
            portfolio_kind=portfolio_kind,
            fill_mode="next_close",
            cost_bps=float(args.cost_bps),
            integer_shares=True,
            max_fill_lag_days=int(args.max_fill_lag_days),
            concentrated_champion_filters=filters,
        )
    return metrics


def build(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    price_cache = repo_path(args.price_cache)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_book, source_mode = resolve_candidate_book(latest_run, args.candidate_book)
    candidate = normalize_candidate_frame(read_table(candidate_book))
    if candidate.empty or source_mode == "latest_only_blocked":
        payload = {
            "schema_version": "alphaops-vnext-production-replay-v1",
            "status": "blocked",
            "reason": "historical candidate_replay_book.csv is required",
            "candidate_book": str(candidate_book),
            "candidate_source_mode": source_mode,
            "production_policy": "alphaops_vnext_production",
            "production_applied": False,
            "sidecar_only": False,
        }
        write_json(output_dir / "summary.json", payload)
        return payload

    candidate, pit_audit = enforce_pit_available(candidate)
    write_csv(output_dir / "pit_evidence_audit.csv", pit_audit)
    candidate = enrich_relative_strength(candidate, price_cache)
    dates = pd.to_datetime(candidate["rebalance_date"], errors="coerce").dropna()
    crisis_states = build_daily_crisis_state(
        price_cache,
        pd.Timestamp(dates.min()),
        pd.Timestamp(dates.max()),
        long_crisis_features=repo_path(args.long_crisis_features),
        long_crisis_thresholds=repo_path(args.long_crisis_thresholds),
    )
    crisis_audit, crisis_window_report, crisis_audit_payload = crisis_state_audit(crisis_states)
    if bool(crisis_audit_payload.get("daily_crisis_state_all_green")) and bool(crisis_audit_payload.get("missing_data_only_trigger")):
        crisis_states = pd.DataFrame()
        crisis_status = "skipped_missing_crisis_inputs"
    else:
        crisis_status = "applied"
    write_csv(output_dir / "daily_crisis_state.csv", crisis_states)
    write_csv(output_dir / "crisis_state_audit.csv", crisis_audit)
    write_csv(output_dir / "crisis_window_detection_report.csv", crisis_window_report)
    write_json(output_dir / "lane_feature_mapping.json", lane_feature_mapping_payload())
    write_json(output_dir / "crisis_hysteresis_config.json", CRISIS_HYSTERESIS)

    variants: dict[str, pd.DataFrame] = {}
    lane_frames: list[pd.DataFrame] = []
    reject_frames: list[pd.DataFrame] = []
    exposure_frames: list[pd.DataFrame] = []
    portfolios = ["main", "concentrated"] if args.portfolio_kind == "both" else [args.portfolio_kind]
    for portfolio_kind in portfolios:
        target_ns = MAIN_VARIANTS if portfolio_kind == "main" else CONCENTRATED_VARIANTS
        for target_n in target_ns:
            target, lanes, rejected, exposure = build_variant_book(
                candidate,
                portfolio_kind=portfolio_kind,
                target_n=int(target_n),
                crisis_states=crisis_states,
            )
            key = f"{portfolio_kind}_N{target_n}"
            variants[key] = target
            write_csv(output_dir / "variants" / f"{key}_target_book.csv", target)
            if not lanes.empty:
                lanes["variant_id"] = key
                lane_frames.append(lanes)
            if not rejected.empty:
                reject_frames.append(rejected)
            if not exposure.empty:
                exposure_frames.append(exposure)

    main_key = f"main_N{int(args.main_target_n)}"
    concentrated_key = f"concentrated_N{int(args.concentrated_target_n)}"
    main_book = variants.get(main_key, pd.DataFrame()) if "main" in portfolios else pd.DataFrame()
    concentrated_book = variants.get(concentrated_key, pd.DataFrame()) if "concentrated" in portfolios else pd.DataFrame()
    write_csv(output_dir / "official_main_target_book.csv", main_book)
    write_csv(output_dir / "official_concentrated_target_book.csv", concentrated_book)
    lane_history = pd.concat(lane_frames, ignore_index=True) if lane_frames else pd.DataFrame()
    rejected = pd.concat(reject_frames, ignore_index=True) if reject_frames else pd.DataFrame()
    exposure = pd.concat(exposure_frames, ignore_index=True) if exposure_frames else pd.DataFrame()
    write_csv(output_dir / "lane_scores_history.csv", lane_history)
    write_csv(output_dir / "rejected_by_reason.csv", rejected)
    write_csv(output_dir / "lane_exposure_by_month.csv", exposure)
    latest_rows = []
    for key, book in variants.items():
        if book.empty:
            continue
        d = book.copy()
        d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
        latest_dt = d["rebalance_date"].max()
        latest_rows.append(d[d["rebalance_date"].eq(latest_dt)].assign(variant_key=key))
    write_csv(output_dir / "selected_latest.csv", pd.concat(latest_rows, ignore_index=True) if latest_rows else pd.DataFrame())

    copied: dict[str, str] = {}
    production_applied = False
    if args.production_output_mode == "replace_operating":
        copied = copy_operating_books(latest_run, main_book, concentrated_book)
        production_applied = True
    broker_metrics = {} if args.skip_broker_replay else run_broker_replays(args, latest_run)
    activation = {
        "schema_version": "alphaops-vnext-production-activation-v1",
        "status": "applied" if production_applied else "shadow_only",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "production_policy": "alphaops_vnext_production",
        "production_output_mode": args.production_output_mode,
        "current_holdings_source": "alphaops_vnext_policy_target_book" if production_applied else "alphaops_vnext_shadow_target_book",
        "production_applied": bool(production_applied),
        "sidecar_only": False,
        "sidecar_applied_to_production": bool(production_applied),
        "official_target_books": copied,
        "candidate_book": str(candidate_book),
        "candidate_source_mode": source_mode,
        "first_rebalance_date": date_text(dates.min()),
        "last_rebalance_date": date_text(dates.max()),
        "crisis_overlay_status": crisis_status,
    }
    write_json(output_dir / "production_activation.json", activation)
    if production_applied:
        write_json(latest_run / "promotion_review" / "alphaops_vnext_production_activation.json", activation)
    if args.run_current_report:
        build_user_current_report(
            argparse.Namespace(
                latest_run=str(latest_run),
                price_cache=str(price_cache),
                output_dir=str(latest_run / "user_current"),
                strict=False,
            )
        )
    payload = {
        "schema_version": "alphaops-vnext-production-replay-v1",
        "status": "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_book": str(candidate_book),
        "candidate_source_mode": source_mode,
        "rebalance_date_count": int(dates.nunique()),
        "production_policy": "alphaops_vnext_production",
        "production_output_mode": args.production_output_mode,
        "production_applied": bool(production_applied),
        "sidecar_only": False,
        "sidecar_applied_to_production": bool(production_applied),
        "current_holdings_source": activation["current_holdings_source"],
        "main_target_n": int(args.main_target_n),
        "concentrated_target_n": int(args.concentrated_target_n),
        "main_rows": int(len(main_book)),
        "concentrated_rows": int(len(concentrated_book)),
        "lane_score_rows": int(len(lane_history)),
        "rejected_rows": int(len(rejected)),
        "pit_evidence_blocked_rows": int(len(pit_audit)),
        "crisis_overlay_status": crisis_status,
        "broker_replay_ran": not bool(args.skip_broker_replay),
        "broker_metrics": broker_metrics,
        "official_target_books": copied,
        "outputs": {
            "summary_json": str(output_dir / "summary.json"),
            "production_activation_json": str(output_dir / "production_activation.json"),
            "official_main_target_book": str(output_dir / "official_main_target_book.csv"),
            "official_concentrated_target_book": str(output_dir / "official_concentrated_target_book.csv"),
        },
    }
    write_json(output_dir / "summary.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated", "both"], default="both")
    parser.add_argument("--main-target-n", type=int, choices=MAIN_VARIANTS, default=15)
    parser.add_argument("--concentrated-target-n", type=int, choices=CONCENTRATED_VARIANTS, default=5)
    parser.add_argument("--production-output-mode", choices=["replace_operating", "shadow_only"], default="replace_operating")
    parser.add_argument("--skip-broker-replay", action="store_true")
    parser.add_argument("--run-current-report", action="store_true")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--long-crisis-features", default="data_pit/macro/long_crisis_daily_features.parquet")
    parser.add_argument("--long-crisis-thresholds", default="outputs/long_crisis_learning/best_thresholds.json")
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

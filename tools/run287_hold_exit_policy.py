#!/usr/bin/env python3
"""Canonical Run287 hold, sell-taxonomy, and replacement research policy.

The module is deliberately target-book preserving.  It never reconstructs a
candidate pool from selected names.  The frozen control book supplies the
control decisions and an independently restored PIT scored-candidate cache
supplies the evidence used to decide whether a departing incumbent deserves a
leadership-persistence hold.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tools.run_alphaops_vnext_policy_replay import holding_state
from tools.security_lifecycle import SecurityLifecycleSnapshot, resolve_security_lifecycle


SCHEMA_VERSION = "run287-hold-exit-policy-v1"
POLICY_ID = "leadership_persistence_v2_strict"
SELL_TAXONOMY = (
    "THESIS_EXIT",
    "RISK_EXIT",
    "REPLACEMENT_EXIT",
    "LIFECYCLE_EXIT",
    "EXECUTION_RECONCILIATION",
)
CASH_TICKERS = {"CASH", "__CASH__"}
REQUIRED_SCORED_COLUMNS = {
    "rebalance_date",
    "ticker",
    "alphaops_vnext_score",
    "rs_benchmark_1w",
    "rs_benchmark_3m",
    "price_above_ma50",
    "price_above_ma200",
    "leader_tier",
    "rs_sector_3m",
    "industry_group_strength_score",
    "portfolio_risk_entry_block_score",
    "portfolio_stale_mega_leader_score",
    "emerging_tenbagger_hard_reject_reason",
    "top7_standalone_blocked",
    "pit_evidence_blocked",
    "primary_lane",
    "sector",
    "industry_group",
}
FUTURE_LABEL_TOKENS = ("forward_return", "future_return", "outcome", "label_")


@dataclass(frozen=True)
class LeadershipPersistencePolicy:
    score_sigma_multiplier: float = 1.10
    minimum_score_gap: float = 0.22
    round_trip_cost_penalty: float = 0.005
    rs_percentile_floor: float = 0.90
    risk_block_ceiling: float = 0.55

    def required_gap(self, score_sigma: float) -> float:
        return max(
            float(self.minimum_score_gap),
            float(self.score_sigma_multiplier) * max(float(score_sigma), 0.20),
        ) + float(self.round_trip_cost_penalty)

    def audit(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "policy_id": POLICY_ID,
            "score_sigma_multiplier": self.score_sigma_multiplier,
            "minimum_score_gap": self.minimum_score_gap,
            "round_trip_cost_penalty": self.round_trip_cost_penalty,
            "rs_percentile_floor": self.rs_percentile_floor,
            "risk_block_ceiling": self.risk_block_ceiling,
            "grid_search_allowed": False,
            "used_forward_return": False,
        }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_ticker(value: Any) -> str:
    text = str(value or "").upper().strip()
    return "" if text in {"", "NAN", "NONE"} else text


def safe_float(value: Any, default: float = math.nan) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def clean_text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"", "nan", "none", "null"} else text


def normalize_target_book(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or not {"rebalance_date", "ticker"}.issubset(frame.columns):
        raise ValueError("target book requires rebalance_date and ticker")
    out = frame.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.normalize()
    out["ticker"] = out["ticker"].map(clean_ticker)
    weight_col = "weight" if "weight" in out.columns else "target_weight"
    if weight_col not in out.columns:
        raise ValueError("target book requires weight or target_weight")
    out["weight"] = pd.to_numeric(out[weight_col], errors="coerce")
    if out["rebalance_date"].isna().any() or out["ticker"].eq("").any() or out["weight"].isna().any():
        raise ValueError("target book contains invalid key or weight")
    if out.duplicated(["rebalance_date", "ticker"]).any():
        raise ValueError("target book contains duplicate date/ticker rows")
    return out.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)


def load_scored_candidate_cache(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    header = pd.read_csv(path, nrows=0).columns.tolist()
    future_columns = [
        column for column in header
        if any(token in str(column).lower() for token in FUTURE_LABEL_TOKENS)
    ]
    usecols = [column for column in header if column in REQUIRED_SCORED_COLUMNS or column in {
        "theme_phase_primary", "theme_horizon_primary", "leader_broad_theme",
        "subindustry", "sub_industry", "negative_fcf_risk_cap",
    }]
    frame = pd.read_csv(path, usecols=usecols, low_memory=False)
    missing = sorted(REQUIRED_SCORED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError("scored candidate cache missing columns:" + ",".join(missing))
    frame["rebalance_date"] = pd.to_datetime(frame["rebalance_date"], errors="coerce").dt.normalize()
    frame["ticker"] = frame["ticker"].map(clean_ticker)
    frame = frame.dropna(subset=["rebalance_date"])
    frame = frame[(frame["ticker"] != "") & ~frame["ticker"].isin(CASH_TICKERS)]
    comparison_columns = [column for column in frame.columns if column not in {"rebalance_date", "ticker"}]
    inconsistent = []
    grouped = frame.groupby(["rebalance_date", "ticker"], sort=False)
    for column in comparison_columns:
        if bool((grouped[column].nunique(dropna=False) > 1).any()):
            inconsistent.append(column)
    if inconsistent:
        raise ValueError("scored candidate duplicates disagree:" + ",".join(inconsistent))
    frame = frame.drop_duplicates(["rebalance_date", "ticker"], keep="first")
    frame.attrs["future_columns_physically_excluded"] = future_columns
    return frame.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)


def _decision_time_utc(day: pd.Timestamp) -> pd.Timestamp:
    local_close = (pd.Timestamp(day).normalize() + pd.Timedelta(hours=16)).tz_localize("America/New_York")
    return local_close.tz_convert("UTC")


def lifecycle_for_date(
    lifecycle_path: Path,
    day: pd.Timestamp,
    active_tickers: set[str],
) -> SecurityLifecycleSnapshot:
    return resolve_security_lifecycle(
        lifecycle_path,
        session_date=pd.Timestamp(day).normalize(),
        decision_time_utc=_decision_time_utc(day),
        active_tickers=active_tickers,
    )


def _record_required_finite(record: dict[str, Any]) -> tuple[bool, list[str]]:
    required_numeric = (
        "alphaops_vnext_score",
        "rs_benchmark_1w",
        "rs_benchmark_3m",
        "price_above_ma50",
        "price_above_ma200",
        "rs_sector_3m",
        "industry_group_strength_score",
        "portfolio_risk_entry_block_score",
        "portfolio_stale_mega_leader_score",
    )
    missing = [column for column in required_numeric if not math.isfinite(safe_float(record.get(column)))]
    for column in ("leader_tier", "sector", "industry_group"):
        if not clean_text(record.get(column)):
            missing.append(column)
    return not missing, missing


def _risk_freeze_reason(record: dict[str, Any], policy: LeadershipPersistencePolicy) -> str:
    if safe_float(record.get("portfolio_risk_entry_block_score"), math.inf) >= policy.risk_block_ceiling:
        return "risk_entry_block"
    if safe_float(record.get("portfolio_stale_mega_leader_score"), math.inf) > 0.0:
        return "stale_leader_break"
    if clean_text(record.get("emerging_tenbagger_hard_reject_reason")):
        return "hard_reject"
    if safe_bool(record.get("top7_standalone_blocked")):
        return "top7_standalone_block"
    if safe_bool(record.get("pit_evidence_blocked")):
        return "pit_future_evidence_block"
    return ""


def incumbent_protection(
    record: dict[str, Any] | None,
    *,
    portfolio: str,
    score_median: float,
    score_sigma: float,
    rs_percentile: float,
    lifecycle_terminal: bool,
    policy: LeadershipPersistencePolicy,
) -> tuple[bool, str, str]:
    """Return protected, reason, and the exit taxonomy when not protected."""

    if record is None:
        return False, "missing_exact_candidate_row", "EXECUTION_RECONCILIATION"
    complete, missing = _record_required_finite(record)
    if not complete:
        return False, "missing_required_evidence:" + ",".join(missing), "EXECUTION_RECONCILIATION"
    if lifecycle_terminal:
        return False, "lifecycle_terminal", "LIFECYCLE_EXIT"
    risk_reason = _risk_freeze_reason(record, policy)
    if risk_reason:
        taxonomy = "THESIS_EXIT" if risk_reason in {"hard_reject", "stale_leader_break"} else "RISK_EXIT"
        return False, risk_reason, taxonomy
    state, state_reason = holding_state(record, score_median, score_sigma)
    if str(state).upper() != "HOLD":
        taxonomy = "THESIS_EXIT" if str(state).upper() == "EXIT" else "RISK_EXIT"
        return False, f"canonical_holding_state:{state}:{state_reason}", taxonomy
    if rs_percentile < policy.rs_percentile_floor:
        return False, "rs_not_top_decile", "REPLACEMENT_EXIT"
    if safe_float(record.get("price_above_ma200"), -math.inf) < 0.5:
        return False, "below_ma200", "RISK_EXIT"
    allowed_tiers = {"DUAL_LEADER"} if portfolio == "concentrated" else {"DUAL_LEADER", "SECTOR_LEADER"}
    if clean_text(record.get("leader_tier")).upper() not in allowed_tiers:
        return False, "leader_tier_not_approved", "REPLACEMENT_EXIT"
    if safe_float(record.get("rs_sector_3m"), -math.inf) <= 0.0:
        return False, "sector_rs_not_positive", "REPLACEMENT_EXIT"
    if safe_float(record.get("industry_group_strength_score"), -math.inf) <= 0.0:
        return False, "industry_strength_not_positive", "REPLACEMENT_EXIT"
    return True, "strict_confirmed_leader", "REPLACEMENT_EXIT"


def challenger_eligible(
    record: dict[str, Any] | None,
    *,
    lifecycle_terminal: bool,
    policy: LeadershipPersistencePolicy,
) -> tuple[bool, str]:
    if record is None:
        return False, "missing_exact_candidate_row"
    complete, missing = _record_required_finite(record)
    if not complete:
        return False, "missing_required_evidence:" + ",".join(missing)
    if lifecycle_terminal:
        return False, "lifecycle_terminal"
    risk_reason = _risk_freeze_reason(record, policy)
    if risk_reason:
        return False, risk_reason
    if safe_float(record.get("price_above_ma200"), -math.inf) < 0.5:
        return False, "trend_not_alive"
    if safe_float(record.get("rs_benchmark_3m"), -math.inf) <= 0.0:
        return False, "relative_strength_not_alive"
    return True, "frozen_selector_selected_and_gate_clear"


def _theme_key(record: dict[str, Any]) -> str:
    for column in ("leader_broad_theme", "theme_horizon_primary", "theme_phase_primary", "industry_group", "sector"):
        value = clean_text(record.get(column))
        if value:
            return value
    return "UNKNOWN"


def _exposure_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sectors: dict[str, float] = {}
    themes: dict[str, float] = {}
    for row in rows:
        ticker = clean_ticker(row.get("ticker"))
        if ticker in CASH_TICKERS:
            continue
        weight = max(0.0, safe_float(row.get("weight"), 0.0))
        sector = clean_text(row.get("sector")) or "UNKNOWN"
        theme = _theme_key(row)
        sectors[sector] = sectors.get(sector, 0.0) + weight
        themes[theme] = themes.get(theme, 0.0) + weight
    return {
        "sector_weights": sectors,
        "theme_weights": themes,
        "sector_hhi": sum(value * value for value in sectors.values()),
        "theme_hhi": sum(value * value for value in themes.values()),
        "max_sector": max(sectors.values(), default=0.0),
        "max_theme": max(themes.values(), default=0.0),
    }


def concentration_not_worse(
    control_rows: list[dict[str, Any]],
    proposed_rows: list[dict[str, Any]],
    *,
    portfolio: str,
) -> tuple[bool, str, dict[str, Any], dict[str, Any]]:
    before = _exposure_stats(control_rows)
    after = _exposure_stats(proposed_rows)
    theme_cap = 1.0 if portfolio == "concentrated" else 0.60
    sector_cap = 0.70 if portfolio == "concentrated" else 0.40
    checks = {
        "sector_hhi": after["sector_hhi"] <= before["sector_hhi"] + 1e-12,
        "theme_hhi": after["theme_hhi"] <= before["theme_hhi"] + 1e-12,
        "sector_cap": after["max_sector"] <= sector_cap + 1e-12,
        "theme_cap": after["max_theme"] <= theme_cap + 1e-12,
    }
    failed = [key for key, value in checks.items() if not value]
    return not failed, ("pass" if not failed else "failed:" + ",".join(failed)), before, after


def _copy_candidate_fields(target_row: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    out = dict(target_row)
    for column, value in candidate.items():
        if column in out and column not in {"rebalance_date", "ticker", "weight", "target_weight"}:
            out[column] = value
    return out


def build_leadership_persistence_book(
    control_book: pd.DataFrame,
    scored_candidates: pd.DataFrame,
    *,
    portfolio: str,
    lifecycle_path: Path,
    policy: LeadershipPersistencePolicy | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    policy = policy or LeadershipPersistencePolicy()
    control = normalize_target_book(control_book)
    scored = scored_candidates.copy()
    scored["rebalance_date"] = pd.to_datetime(scored["rebalance_date"], errors="coerce").dt.normalize()
    scored["ticker"] = scored["ticker"].map(clean_ticker)
    scored_by_date = {
        pd.Timestamp(day).normalize(): group.set_index("ticker", drop=False)
        for day, group in scored.groupby("rebalance_date", sort=True)
    }
    dates = sorted(control["rebalance_date"].unique())
    treatment_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    exit_rows: list[dict[str, Any]] = []
    previous: dict[str, dict[str, Any]] = {}
    applied_count = 0
    protected_test_count = 0
    behavior_delta_dates: set[str] = set()
    reason_counts: dict[str, int] = {}

    for raw_day in dates:
        day = pd.Timestamp(raw_day).normalize()
        base_day = control[control["rebalance_date"].eq(day)].copy()
        base_records = base_day.to_dict("records")
        base_stocks = {clean_ticker(row["ticker"]): row for row in base_records if clean_ticker(row["ticker"]) not in CASH_TICKERS}
        candidate_day = scored_by_date.get(day, pd.DataFrame())
        if candidate_day.empty and previous and set(previous) != set(base_stocks):
            raise ValueError(f"missing scored candidate date for changed book:{day.date().isoformat()}")
        score_series = pd.to_numeric(candidate_day.get("alphaops_vnext_score", pd.Series(dtype=float)), errors="coerce").dropna()
        score_median = float(score_series.median()) if not score_series.empty else 0.0
        score_sigma = float(score_series.std(ddof=0)) if not score_series.empty else 0.0
        rs_series = pd.to_numeric(candidate_day.get("rs_benchmark_3m", pd.Series(dtype=float)), errors="coerce")
        rs_percentiles = rs_series.rank(method="average", pct=True) if not rs_series.empty else pd.Series(dtype=float)
        candidate_records = candidate_day.to_dict("index") if not candidate_day.empty else {}
        percentile_map = {
            clean_ticker(candidate_day.loc[index, "ticker"]): safe_float(rs_percentiles.loc[index], 0.0)
            for index in candidate_day.index
        } if not candidate_day.empty else {}

        active = set(previous) | set(base_stocks)
        lifecycle = lifecycle_for_date(lifecycle_path, day, active)
        terminal = set(lifecycle.terminal_tickers)
        proposed = [dict(row) for row in base_records]
        proposed_index = {clean_ticker(row["ticker"]): idx for idx, row in enumerate(proposed)}
        departing = sorted(set(previous) - set(base_stocks))
        incoming = sorted(set(base_stocks) - set(previous))

        protected: list[tuple[str, dict[str, Any], float]] = []
        exit_taxonomy_by_ticker: dict[str, tuple[str, str]] = {}
        for ticker in departing:
            record = candidate_records.get(ticker)
            ok, reason, taxonomy = incumbent_protection(
                record,
                portfolio=portfolio,
                score_median=score_median,
                score_sigma=score_sigma,
                rs_percentile=percentile_map.get(ticker, 0.0),
                lifecycle_terminal=ticker in terminal,
                policy=policy,
            )
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            exit_taxonomy_by_ticker[ticker] = (taxonomy, reason)
            if ok and record is not None:
                protected.append((ticker, record, safe_float(record.get("alphaops_vnext_score"), -math.inf)))

        incoming_ranked = sorted(
            incoming,
            key=lambda ticker: (
                safe_float((candidate_records.get(ticker) or {}).get("alphaops_vnext_score"), math.inf),
                ticker,
            ),
        )
        protected.sort(key=lambda item: (-item[2], item[0]))
        used_incoming: set[str] = set()
        for incumbent, incumbent_record, incumbent_score in protected:
            challenger = next((ticker for ticker in incoming_ranked if ticker not in used_incoming), "")
            if not challenger:
                decision_rows.append({
                    "rebalance_date": day.date().isoformat(), "portfolio": portfolio,
                    "incumbent_ticker": incumbent, "challenger_ticker": "",
                    "action": "NO_PAIR", "reason": "no_new_control_challenger",
                })
                continue
            used_incoming.add(challenger)
            challenger_record = candidate_records.get(challenger)
            eligible, challenger_reason = challenger_eligible(
                challenger_record,
                lifecycle_terminal=challenger in terminal,
                policy=policy,
            )
            challenger_score = safe_float((challenger_record or {}).get("alphaops_vnext_score"), math.inf)
            advantage = challenger_score - incumbent_score
            required_gap = policy.required_gap(score_sigma)
            retained_weight = safe_float(base_stocks.get(challenger, {}).get("weight"), 0.0)
            protected_test_count += 1
            action = "ALLOW_REPLACEMENT"
            reason = "challenger_clears_fixed_margin"
            concentration_reason = "not_tested"
            before_stats: dict[str, Any] = {}
            after_stats: dict[str, Any] = {}
            if not eligible:
                action = "RETAIN_INCUMBENT"
                reason = "challenger_not_eligible:" + challenger_reason
            elif advantage < required_gap:
                action = "RETAIN_INCUMBENT"
                reason = "fixed_margin_not_met"
            if action == "RETAIN_INCUMBENT":
                challenger_idx = proposed_index.get(challenger)
                if challenger_idx is None:
                    action = "ALLOW_REPLACEMENT"
                    reason = "missing_control_challenger_row"
                else:
                    replacement = _copy_candidate_fields(proposed[challenger_idx], incumbent_record)
                    replacement["ticker"] = incumbent
                    replacement["p5_policy_id"] = POLICY_ID
                    replacement["p5_action"] = "RETAINED_LEADER"
                    replacement["p5_displaced_challenger"] = challenger
                    replacement["p5_required_gap"] = required_gap
                    replacement["p5_observed_score_advantage"] = advantage
                    candidate_proposal = list(proposed)
                    candidate_proposal[challenger_idx] = replacement
                    concentration_ok, concentration_reason, before_stats, after_stats = concentration_not_worse(
                        base_records, candidate_proposal, portfolio=portfolio,
                    )
                    if concentration_ok:
                        proposed = candidate_proposal
                        proposed_index.pop(challenger, None)
                        proposed_index[incumbent] = challenger_idx
                        applied_count += 1
                        behavior_delta_dates.add(day.date().isoformat())
                        exit_taxonomy_by_ticker.pop(incumbent, None)
                    else:
                        action = "ALLOW_REPLACEMENT"
                        reason = "concentration_would_worsen"
            if action == "ALLOW_REPLACEMENT":
                exit_taxonomy_by_ticker[incumbent] = ("REPLACEMENT_EXIT", reason)
            decision_rows.append({
                "rebalance_date": day.date().isoformat(),
                "portfolio": portfolio,
                "incumbent_ticker": incumbent,
                "challenger_ticker": challenger,
                "incumbent_score": incumbent_score,
                "challenger_score": challenger_score,
                "challenger_advantage": advantage,
                "required_gap": required_gap,
                "retained_weight": retained_weight,
                "score_sigma": score_sigma,
                "incumbent_rs_percentile": percentile_map.get(incumbent, 0.0),
                "challenger_eligible": eligible,
                "challenger_eligibility_reason": challenger_reason,
                "concentration_reason": concentration_reason,
                "control_sector_hhi": before_stats.get("sector_hhi"),
                "proposed_sector_hhi": after_stats.get("sector_hhi"),
                "control_theme_hhi": before_stats.get("theme_hhi"),
                "proposed_theme_hhi": after_stats.get("theme_hhi"),
                "action": action,
                "reason": reason,
                "used_forward_return": False,
            })

        proposed_stocks = {
            clean_ticker(row["ticker"]): row for row in proposed
            if clean_ticker(row["ticker"]) not in CASH_TICKERS
        }
        for ticker in sorted(set(previous) - set(proposed_stocks)):
            taxonomy, reason = exit_taxonomy_by_ticker.get(ticker, ("REPLACEMENT_EXIT", "control_membership_replacement"))
            if taxonomy not in SELL_TAXONOMY:
                raise ValueError(f"invalid sell taxonomy:{taxonomy}")
            exit_rows.append({
                "rebalance_date": day.date().isoformat(),
                "portfolio": portfolio,
                "ticker": ticker,
                "sell_taxonomy": taxonomy,
                "sell_taxonomy_reason": reason,
                "prior_weight": safe_float(previous[ticker].get("weight"), 0.0),
                "replacement_tickers": "|".join(sorted(set(proposed_stocks) - set(previous))),
            })

        control_total = float(sum(safe_float(row.get("weight"), 0.0) for row in base_records))
        proposed_total = float(sum(safe_float(row.get("weight"), 0.0) for row in proposed))
        control_cash = float(sum(safe_float(row.get("weight"), 0.0) for row in base_records if clean_ticker(row.get("ticker")) in CASH_TICKERS))
        proposed_cash = float(sum(safe_float(row.get("weight"), 0.0) for row in proposed if clean_ticker(row.get("ticker")) in CASH_TICKERS))
        if abs(control_total - proposed_total) > 1e-12 or abs(control_cash - proposed_cash) > 1e-12:
            raise ValueError(f"weight or Reserve conservation failed:{day.date().isoformat()}")
        if len(proposed_stocks) != len(base_stocks):
            raise ValueError(f"position count changed:{day.date().isoformat()}")
        treatment_rows.extend(proposed)
        previous = proposed_stocks

    treatment = pd.DataFrame(treatment_rows)
    decisions = pd.DataFrame(decision_rows)
    exits = pd.DataFrame(exit_rows)
    audit = {
        "schema_version": SCHEMA_VERSION,
        "policy": policy.audit(),
        "portfolio": portfolio,
        "status": "APPLIED" if applied_count else "NO_OP",
        "date_count": len(dates),
        "protected_replacement_tests": protected_test_count,
        "applied_retention_count": applied_count,
        "behavior_delta_date_count": len(behavior_delta_dates),
        "sell_taxonomy_counts": exits.get("sell_taxonomy", pd.Series(dtype=str)).value_counts().sort_index().to_dict(),
        "protection_reason_counts": dict(sorted(reason_counts.items())),
        "weight_conservation_passed": True,
        "cash_reserve_conservation_passed": True,
        "position_count_conservation_passed": True,
        "missing_is_neutral": True,
        "used_forward_return": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    return treatment, decisions, exits, audit


def classify_execution_sell(
    *,
    ticker: str,
    target_weight: float,
    target_gross_reduced: bool,
    replacement_tickers: set[str] | None = None,
    lifecycle_terminal: bool = False,
    explicit_taxonomy: str = "",
    thesis_break: bool = False,
    risk_break: bool = False,
) -> tuple[str, str]:
    """Classify any sell without using catch-all rank/rebalance labels."""

    if explicit_taxonomy:
        if explicit_taxonomy not in SELL_TAXONOMY:
            raise ValueError(f"invalid explicit sell taxonomy:{explicit_taxonomy}")
        return explicit_taxonomy, "explicit_target_intent"
    if lifecycle_terminal:
        return "LIFECYCLE_EXIT", "verified_security_lifecycle"
    if thesis_break:
        return "THESIS_EXIT", "explicit_thesis_break"
    if risk_break or target_gross_reduced:
        return "RISK_EXIT", "risk_or_gross_reduction"
    if target_weight <= 1e-12 and replacement_tickers:
        return "REPLACEMENT_EXIT", "target_membership_replacement"
    return "EXECUTION_RECONCILIATION", "weight_or_quantity_reconciliation"

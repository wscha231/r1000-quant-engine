"""Aggregate matured PIT 13F clone-event evidence into manager research scorecards.

This is an event-study scorecard, not a continuous clone account/NAV and not a
production manager rank. It deliberately preserves that distinction so event
averages cannot be misrepresented as account CAGR.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, asdict
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


class ScorecardError(ValueError):
    pass


@dataclass(frozen=True)
class ScorecardConfig:
    horizons: tuple[int, ...] = (63, 126, 252, 504)
    base_delay: int = 0
    robustness_delays: tuple[int, ...] = (2, 5)
    minimum_events_per_horizon: int = 5
    recent_window_months: int = 36
    minimum_unique_tickers: int = 3

    def __post_init__(self) -> None:
        if tuple(sorted(set(self.horizons))) != self.horizons or not self.horizons:
            raise ScorecardError("invalid_horizons")
        if self.base_delay < 0 or any(x < 0 for x in self.robustness_delays):
            raise ScorecardError("invalid_delay")
        if self.base_delay in self.robustness_delays or len(set(self.robustness_delays)) != len(self.robustness_delays):
            raise ScorecardError("delay_overlap")
        if self.minimum_events_per_horizon <= 0 or self.minimum_unique_tickers <= 0:
            raise ScorecardError("invalid_minimum_sample")
        if self.recent_window_months <= 0:
            raise ScorecardError("invalid_recent_window")


def _stamp(value: Any) -> pd.Timestamp:
    stamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(stamp):
        raise ScorecardError("timestamp_invalid")
    return pd.Timestamp(stamp)


def _finite(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ScorecardError("number_invalid") from exc
    if not math.isfinite(number):
        raise ScorecardError("number_nonfinite")
    return number


def _percentile(values: pd.Series, q: float) -> float:
    data = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if not len(data):
        raise ScorecardError("percentile_empty")
    return float(np.quantile(data, q))


def _ci_mean(values: pd.Series) -> tuple[float, float]:
    """Deterministic normal-approximation CI; descriptive, not a causal p-value."""
    data = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if not len(data):
        raise ScorecardError("ci_empty")
    mean = float(data.mean())
    if len(data) == 1:
        return mean, mean
    se = float(data.std(ddof=1) / math.sqrt(len(data)))
    return mean - 1.96 * se, mean + 1.96 * se


def _validate_rows(rows: Iterable[Mapping[str, Any]], cutoff: str) -> pd.DataFrame:
    cut = _stamp(cutoff)
    frame = pd.DataFrame([dict(r) for r in rows])
    if frame.empty:
        return frame
    required = {
        "event_id", "economic_manager_id", "ticker", "event_type", "available_from",
        "entry_delay_sessions", "horizon_sessions", "status", "net_return",
        "benchmark_total_return", "net_excess_return", "max_drawdown_from_entry",
        "target_date", "outcome_available_at", "price_snapshot_id", "cost_model_id",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ScorecardError("missing_columns:" + ",".join(missing))
    for col in ("event_id", "economic_manager_id", "ticker", "event_type", "status", "price_snapshot_id", "cost_model_id"):
        if frame[col].isna().any() or frame[col].astype(str).str.strip().eq("").any():
            raise ScorecardError(f"missing_value:{col}")
    if not frame["status"].eq("MATURED").all():
        raise ScorecardError("only_matured_rows_allowed")
    frame["available_ts"] = pd.to_datetime(frame["available_from"], utc=True, errors="coerce")
    frame["outcome_ts"] = pd.to_datetime(frame["outcome_available_at"], utc=True, errors="coerce")
    if frame[["available_ts", "outcome_ts"]].isna().any().any():
        raise ScorecardError("invalid_availability_timestamp")
    if (frame["available_ts"] > frame["outcome_ts"]).any() or (frame["outcome_ts"] > cut).any():
        raise ScorecardError("future_or_inverted_outcome_availability")
    for col in ("entry_delay_sessions", "horizon_sessions"):
        frame[col] = pd.to_numeric(frame[col], errors="raise").astype(int)
    for col in ("net_return", "benchmark_total_return", "net_excess_return", "max_drawdown_from_entry"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
        if not np.isfinite(frame[col]).all():
            raise ScorecardError(f"nonfinite:{col}")
    duplicate_key = ["event_id", "entry_delay_sessions", "horizon_sessions"]
    if frame.duplicated(duplicate_key).any():
        raise ScorecardError("duplicate_event_delay_horizon")
    # One event_id must describe one manager/ticker/type disclosure, never drift across rows.
    identity = frame.groupby("event_id")[["economic_manager_id", "ticker", "event_type", "available_from"]].nunique(dropna=False)
    if (identity > 1).any().any():
        raise ScorecardError("event_identity_inconsistent")
    return frame.sort_values(["economic_manager_id", "available_ts", "event_id", "entry_delay_sessions", "horizon_sessions"]).reset_index(drop=True)


def _horizon_stats(group: pd.DataFrame) -> dict[str, Any]:
    excess = group["net_excess_return"]
    net = group["net_return"]
    dd = group["max_drawdown_from_entry"]
    lo, hi = _ci_mean(excess)
    return {
        "events": int(group["event_id"].nunique()),
        "unique_tickers": int(group["ticker"].nunique()),
        "mean_net_return": float(net.mean()),
        "median_net_return": float(net.median()),
        "mean_net_excess_return": float(excess.mean()),
        "median_net_excess_return": float(excess.median()),
        "excess_hit_rate": float((excess > 0).mean()),
        "mean_excess_ci95_low": float(lo),
        "mean_excess_ci95_high": float(hi),
        "median_max_drawdown_from_entry": float(dd.median()),
        "p10_max_drawdown_from_entry": _percentile(dd, .10),
    }


def build_manager_event_scorecards(
    rows: Iterable[Mapping[str, Any]], *, decision_cutoff: str,
    source_evidence_id: str, config: ScorecardConfig = ScorecardConfig(),
) -> dict[str, Any]:
    if not isinstance(source_evidence_id, str) or not source_evidence_id.strip():
        raise ScorecardError("source_evidence_id_required")
    cut = _stamp(decision_cutoff)
    frame = _validate_rows(rows, decision_cutoff)
    if frame.empty:
        return {
            "schema_version": "13f-manager-event-scorecard-v1",
            "status": "NO_MATURED_EVENT_EVIDENCE",
            "decision_cutoff": cut.isoformat(),
            "scorecards": [],
            "event_study_not_account_nav": True,
            "continuous_clone_nav_built": False,
            "production_promotion_allowed": False,
            "research_only": True,
        }
    allowed_horizons = set(config.horizons)
    if not set(frame["horizon_sessions"]).issubset(allowed_horizons):
        raise ScorecardError("unexpected_horizon")
    allowed_delays = {config.base_delay, *config.robustness_delays}
    if not set(frame["entry_delay_sessions"]).issubset(allowed_delays):
        raise ScorecardError("unexpected_delay")

    recent_start = cut - pd.DateOffset(months=config.recent_window_months)
    scorecards = []
    for manager, mgr in frame.groupby("economic_manager_id", sort=True):
        primary = mgr[mgr["entry_delay_sessions"].eq(config.base_delay)].copy()
        primary_recent = primary[primary["available_ts"].between(recent_start, cut, inclusive="both")]
        horizons: dict[str, Any] = {}
        ineligible_reasons: list[str] = []
        for horizon in config.horizons:
            h = primary_recent[primary_recent["horizon_sessions"].eq(horizon)]
            if h.empty:
                horizons[str(horizon)] = {"status": "NO_SAMPLE", "events": 0}
                ineligible_reasons.append(f"NO_SAMPLE_{horizon}D")
                continue
            stats = _horizon_stats(h)
            stats["status"] = "READY" if stats["events"] >= config.minimum_events_per_horizon and stats["unique_tickers"] >= config.minimum_unique_tickers else "INSUFFICIENT_SAMPLE"
            if stats["status"] != "READY":
                ineligible_reasons.append(f"INSUFFICIENT_SAMPLE_{horizon}D")
            horizons[str(horizon)] = stats

        robustness: dict[str, Any] = {}
        base_keys = primary_recent[["event_id", "horizon_sessions", "net_excess_return"]].rename(columns={"net_excess_return": "base_excess"})
        for delay in config.robustness_delays:
            delayed = mgr[(mgr["entry_delay_sessions"].eq(delay)) & mgr["available_ts"].between(recent_start, cut, inclusive="both")]
            joined = base_keys.merge(delayed[["event_id", "horizon_sessions", "net_excess_return"]], on=["event_id", "horizon_sessions"], how="inner")
            if joined.empty:
                robustness[str(delay)] = {"status": "NO_PAIRED_SAMPLE", "pairs": 0}
                continue
            erosion = joined["net_excess_return"] - joined["base_excess"]
            robustness[str(delay)] = {
                "status": "READY",
                "pairs": int(len(joined)),
                "mean_excess_change_vs_base": float(erosion.mean()),
                "median_excess_change_vs_base": float(erosion.median()),
                "share_not_worse_than_200bps": float((erosion >= -.02).mean()),
            }

        # New/add decomposition remains descriptive; no synthetic skill score is created here.
        type_stats = {}
        for event_type in ("new", "add"):
            typed = primary_recent[primary_recent["event_type"].eq(event_type)]
            type_stats[event_type] = {
                "event_horizon_rows": int(len(typed)),
                "unique_events": int(typed["event_id"].nunique()),
                "mean_net_excess_return": float(typed["net_excess_return"].mean()) if not typed.empty else None,
            }

        tickers = set(primary_recent["ticker"].astype(str))
        other = frame[(frame["economic_manager_id"].ne(manager)) & frame["entry_delay_sessions"].eq(config.base_delay) & frame["available_ts"].between(recent_start, cut, inclusive="both")]
        other_tickers = set(other["ticker"].astype(str))
        union = tickers | other_tickers
        jaccard_overlap = len(tickers & other_tickers) / len(union) if union else 0.0

        scorecard = {
            "economic_manager_id": manager,
            "review_window_start": recent_start.isoformat(),
            "review_window_end": cut.isoformat(),
            "source_evidence_id": source_evidence_id,
            "price_snapshot_ids": sorted(set(mgr["price_snapshot_id"].astype(str))),
            "cost_model_ids": sorted(set(mgr["cost_model_id"].astype(str))),
            "horizons": horizons,
            "delay_robustness": robustness,
            "event_type_stats": type_stats,
            "unique_events_primary": int(primary_recent["event_id"].nunique()),
            "unique_tickers_primary": int(primary_recent["ticker"].nunique()),
            "ticker_overlap_jaccard_vs_other_managers": float(jaccard_overlap),
            "independence_proxy": float(1.0 - jaccard_overlap),
            "eligible_for_skill_ranking": len(ineligible_reasons) == 0,
            "ineligible_reasons": sorted(set(ineligible_reasons)),
            "outcome_overlap_adjusted": False,
            "correlation_adjusted_effective_sample_built": False,
            "event_study_not_account_nav": True,
            "continuous_clone_nav_built": False,
            "research_only": True,
            "production_promotion_allowed": False,
        }
        scorecards.append(scorecard)

    payload = {
        "schema_version": "13f-manager-event-scorecard-v1",
        "decision_cutoff": cut.isoformat(),
        "config": asdict(config),
        "source_evidence_id": source_evidence_id,
        "scorecards": scorecards,
        "event_study_not_account_nav": True,
        "continuous_clone_nav_built": False,
        "manager_skill_rank_built": False,
        "production_promotion_allowed": False,
        "research_only": True,
    }
    payload["scorecard_evidence_id"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    payload["status"] = "READY_DESCRIPTIVE_SCORECARDS" if scorecards else "NO_MATURED_EVENT_EVIDENCE"
    return payload

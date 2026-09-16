"""PIT event-level evidence for following disclosed 13F new/add positions.

This module is research-only. It creates matured event outcomes after a filing
became public. It is deliberately *not* a manager ranking and not a continuous
clone NAV. A separate reviewed aggregation step is required before H2 manager
skill policy can consume these rows.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Callable, Iterable, Mapping, Any

import pandas as pd


class CloneEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class CloneEvidenceConfig:
    horizons: tuple[int, ...] = (63, 126, 252, 504)
    entry_delays: tuple[int, ...] = (0, 2, 5)
    per_side_cost_bps: float = 10.0
    benchmark_ticker: str = "SPY"

    def __post_init__(self) -> None:
        if not self.horizons or any(isinstance(x, bool) or not isinstance(x, int) or x <= 0 for x in self.horizons):
            raise CloneEvidenceError("invalid_horizons")
        if tuple(sorted(set(self.horizons))) != self.horizons:
            raise CloneEvidenceError("horizons_must_be_unique_sorted")
        if not self.entry_delays or any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in self.entry_delays):
            raise CloneEvidenceError("invalid_entry_delays")
        if tuple(sorted(set(self.entry_delays))) != self.entry_delays:
            raise CloneEvidenceError("entry_delays_must_be_unique_sorted")
        if not math.isfinite(float(self.per_side_cost_bps)) or not 0 <= float(self.per_side_cost_bps) <= 500:
            raise CloneEvidenceError("invalid_cost_bps")
        if not str(self.benchmark_ticker).strip():
            raise CloneEvidenceError("benchmark_required")


def _instant(value: str) -> pd.Timestamp:
    if not isinstance(value, str) or not value.strip():
        raise CloneEvidenceError("timestamp_missing")
    stamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(stamp):
        raise CloneEvidenceError("timestamp_invalid")
    return pd.Timestamp(stamp)


def _required_text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CloneEvidenceError(f"missing:{key}")
    return value.strip()


def _verify_provenance(provenance: Mapping[str, Any]) -> None:
    for key in (
        "adjusted_close_total_return_proxy_verified",
        "benchmark_total_return_verified",
        "calendar_verified",
        "prices_pit_or_frozen_snapshot_verified",
    ):
        if provenance.get(key) is not True:
            raise CloneEvidenceError(f"not_verified:{key}")
    for key in ("price_snapshot_id", "calendar_id", "benchmark_id", "cost_model_id"):
        _required_text(provenance, key)


def _normalize_price(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty:
        raise CloneEvidenceError("price_series_missing")
    if "close" not in frame.columns:
        raise CloneEvidenceError("price_close_missing")
    out = pd.to_numeric(frame["close"], errors="coerce")
    out.index = pd.to_datetime(frame.index, errors="coerce")
    out = out[out.index.notna() & out.notna() & (out > 0)].sort_index()
    out = out[~out.index.duplicated(keep="last")]
    if len(out) < 2:
        raise CloneEvidenceError("insufficient_price_series")
    return out.astype(float)


def _strict_first_session_after(series: pd.Series, available_at: pd.Timestamp, delay: int) -> tuple[int, pd.Timestamp, float]:
    # Entry cannot use the disclosure calendar day's close even if accepted pre-close.
    day_after = available_at.tz_convert(None).normalize() + pd.Timedelta(days=1)
    idx = pd.DatetimeIndex(series.index).tz_localize(None)
    pos = int(idx.searchsorted(day_after, side="left")) + int(delay)
    if pos >= len(series):
        raise CloneEvidenceError("entry_price_unavailable")
    return pos, pd.Timestamp(idx[pos]), float(series.iloc[pos])


def _exact_price(series: pd.Series, when: pd.Timestamp) -> float:
    idx = pd.DatetimeIndex(series.index).tz_localize(None)
    target = pd.Timestamp(when).tz_localize(None) if pd.Timestamp(when).tzinfo is not None else pd.Timestamp(when)
    pos = int(idx.searchsorted(target, side="left"))
    if pos >= len(idx) or pd.Timestamp(idx[pos]).normalize() != target.normalize():
        raise CloneEvidenceError("benchmark_calendar_mismatch")
    return float(series.iloc[pos])


def _net_return(entry: float, exit_: float, per_side_cost_bps: float) -> float:
    cost = float(per_side_cost_bps) / 10000.0
    return float((exit_ * (1.0 - cost)) / (entry * (1.0 + cost)) - 1.0)


def _max_drawdown_from_entry(window: pd.Series, entry_price: float, entry_cost_bps: float) -> float:
    cost = float(entry_cost_bps) / 10000.0
    basis = entry_price * (1.0 + cost)
    values = pd.to_numeric(window, errors="coerce").dropna()
    if values.empty:
        raise CloneEvidenceError("drawdown_window_missing")
    return float((values / basis - 1.0).min())


def _event_manager_id(event: Mapping[str, Any], manager_map: Mapping[str, str]) -> str:
    explicit = str(event.get("economic_manager_id") or "").strip()
    if explicit:
        return explicit
    cik = str(event.get("manager_cik") or "").strip().lstrip("0") or "0"
    # Accept either exact supplied form or zero-padded form, but never guess a person from a name.
    for key in (str(event.get("manager_cik") or "").strip(), cik, cik.zfill(10)):
        if key in manager_map and str(manager_map[key]).strip():
            return str(manager_map[key]).strip()
    raise CloneEvidenceError("economic_manager_mapping_missing")


def build_event_clone_evidence(
    events: Iterable[Mapping[str, Any]],
    *,
    price_loader: Callable[[str], pd.DataFrame],
    manager_map: Mapping[str, str],
    decision_cutoff: str,
    provenance: Mapping[str, Any],
    config: CloneEvidenceConfig = CloneEvidenceConfig(),
) -> dict[str, Any]:
    """Build only outcomes that were fully matured by decision_cutoff.

    Duplicate event IDs, future disclosures, unverified prices, missing manager
    mappings, benchmark calendar mismatch, and missing required fields fail closed.
    Pending horizons remain explicit rows rather than becoming zero returns.
    """
    _verify_provenance(provenance)
    cutoff = _instant(decision_cutoff)
    benchmark = _normalize_price(price_loader(config.benchmark_ticker.upper()))
    price_cache: dict[str, pd.Series] = {config.benchmark_ticker.upper(): benchmark}
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for original in events:
        event = dict(original)
        event_id = _required_text(event, "event_id")
        if event_id in seen:
            raise CloneEvidenceError("duplicate_event_id")
        seen.add(event_id)
        event_type = _required_text(event, "event_type").lower()
        if event_type not in {"new", "add"}:
            continue
        ticker = _required_text(event, "ticker").upper()
        available = _instant(_required_text(event, "available_from"))
        if available > cutoff:
            continue
        normalized.append({
            "event_id": event_id,
            "economic_manager_id": _event_manager_id(event, manager_map),
            "manager_cik": str(event.get("manager_cik") or ""),
            "ticker": ticker,
            "event_type": event_type,
            "report_period": str(event.get("report_period") or ""),
            "available_from": available,
        })
    normalized.sort(key=lambda x: (x["available_from"], x["economic_manager_id"], x["ticker"], x["event_id"]))
    rows: list[dict[str, Any]] = []
    for event in normalized:
        ticker = event["ticker"]
        if ticker not in price_cache:
            price_cache[ticker] = _normalize_price(price_loader(ticker))
        px = price_cache[ticker]
        for delay in config.entry_delays:
            try:
                entry_pos, entry_date, entry_price = _strict_first_session_after(px, event["available_from"], delay)
                benchmark_entry = _exact_price(benchmark, entry_date)
            except CloneEvidenceError as exc:
                rows.append({
                    **{k: (v.isoformat() if isinstance(v, pd.Timestamp) else v) for k, v in event.items()},
                    "entry_delay_sessions": delay,
                    "status": "BLOCKED_ENTRY",
                    "reason": str(exc),
                    "research_only": True,
                    "production_activation_allowed": False,
                })
                continue
            for horizon in config.horizons:
                target_pos = entry_pos + horizon
                base = {
                    **{k: (v.isoformat() if isinstance(v, pd.Timestamp) else v) for k, v in event.items()},
                    "entry_delay_sessions": delay,
                    "horizon_sessions": horizon,
                    "entry_date": entry_date.date().isoformat(),
                    "entry_price": entry_price,
                    "benchmark_ticker": config.benchmark_ticker.upper(),
                    "per_side_cost_bps": float(config.per_side_cost_bps),
                    "cost_model_id": provenance["cost_model_id"],
                    "price_snapshot_id": provenance["price_snapshot_id"],
                    "research_only": True,
                    "production_activation_allowed": False,
                }
                if target_pos >= len(px):
                    rows.append({**base, "status": "PENDING_PRICE_HISTORY", "reason": "target_session_unavailable"})
                    continue
                target_date = pd.Timestamp(pd.DatetimeIndex(px.index).tz_localize(None)[target_pos])
                # Outcome cannot be used before the target session has closed.
                target_available = pd.Timestamp(target_date, tz="UTC") + pd.Timedelta(hours=23, minutes=59, seconds=59)
                if target_available > cutoff:
                    rows.append({**base, "status": "PENDING_MATURITY", "reason": "target_after_decision_cutoff",
                                 "target_date": target_date.date().isoformat()})
                    continue
                target_price = float(px.iloc[target_pos])
                try:
                    benchmark_target = _exact_price(benchmark, target_date)
                except CloneEvidenceError as exc:
                    rows.append({**base, "status": "BLOCKED_BENCHMARK", "reason": str(exc),
                                 "target_date": target_date.date().isoformat()})
                    continue
                gross_return = target_price / entry_price - 1.0
                net_return = _net_return(entry_price, target_price, config.per_side_cost_bps)
                benchmark_return = benchmark_target / benchmark_entry - 1.0
                max_dd = _max_drawdown_from_entry(px.iloc[entry_pos: target_pos + 1], entry_price, config.per_side_cost_bps)
                rows.append({
                    **base,
                    "status": "MATURED",
                    "reason": "",
                    "target_date": target_date.date().isoformat(),
                    "outcome_available_at": target_available.isoformat(),
                    "target_price": target_price,
                    "gross_return": float(gross_return),
                    "net_return": float(net_return),
                    "benchmark_total_return": float(benchmark_return),
                    "net_excess_return": float(net_return - benchmark_return),
                    "max_drawdown_from_entry": float(max_dd),
                })
    payload_for_hash = {
        "cutoff": cutoff.isoformat(),
        "config": asdict(config),
        "provenance": dict(provenance),
        "rows": rows,
    }
    evidence_id = hashlib.sha256(json.dumps(payload_for_hash, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return {
        "schema_version": "13f-manager-clone-event-evidence-v1",
        "status": "READY_EVENT_EVIDENCE" if any(r.get("status") == "MATURED" for r in rows) else "NO_MATURED_EVENT_EVIDENCE",
        "decision_cutoff": cutoff.isoformat(),
        "config": asdict(config),
        "provenance": dict(provenance),
        "event_rows": rows,
        "matured_rows": sum(r.get("status") == "MATURED" for r in rows),
        "pending_rows": sum(str(r.get("status", "")).startswith("PENDING") for r in rows),
        "blocked_rows": sum(str(r.get("status", "")).startswith("BLOCKED") for r in rows),
        "evidence_id": evidence_id,
        "continuous_clone_nav_built": False,
        "manager_skill_rank_built": False,
        "research_only": True,
        "production_promotion_allowed": False,
        "automatic_trade_allowed": False,
    }

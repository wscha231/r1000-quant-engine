"""Research-only news/business-event impact runtime.

This module turns normalized business events into point-in-time event features,
forward SPY-relative outcomes, cohort impact estimates, and manual challenger
proposals. It deliberately has no selector, target-book, order, portfolio, or
production authority.

The core contract is checkpoint based so that post-event confirmation never
leaks into an earlier decision. For example, a +5-session confirmation feature
is only evaluated against returns after that +5-session checkpoint.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import statistics
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = "news-event-alpha-v1"
RESULT_SCHEMA = "news-event-alpha-result-v1"
HORIZONS = (5, 10, 21, 63, 126, 252)
CHECKPOINTS = (0, 5, 10, 20)
ROLES = {"DIRECT", "ENABLER", "INDIRECT", "NARRATIVE"}
ELIGIBLE_INSTRUMENTS = {"COMMON", "ADR"}
ELIGIBLE_EXCHANGES = {"XNYS", "XNAS", "XASE"}
SOURCE_TIERS = {"OFFICIAL", "PRIMARY", "TIER1_NEWS", "OTHER"}
SAMPLE_ORIGINS = {"HISTORICAL_BACKFILL", "FORWARD_SHADOW"}
PROMOTION_HORIZONS = (21, 63, 126)
POWER_MINIMUMS = {21: 200, 63: 100, 126: 50}


class ContractError(ValueError):
    """Raised when an input violates a point-in-time research contract."""


def utc(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"invalid timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        raise ContractError(f"timezone required: {value!r}")
    return dt.astimezone(timezone.utc)


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _finite_float(value: Any, *, label: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or value in (None, ""):
        raise ContractError(f"{label} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{label} must be numeric") from exc
    if not math.isfinite(out):
        raise ContractError(f"{label} must be finite")
    if minimum is not None and out < minimum:
        raise ContractError(f"{label} must be >= {minimum}")
    if maximum is not None and out > maximum:
        raise ContractError(f"{label} must be <= {maximum}")
    return out


def _optional_float(value: Any, *, label: str, minimum: float | None = None, maximum: float | None = None) -> float | None:
    if value in (None, ""):
        return None
    return _finite_float(value, label=label, minimum=minimum, maximum=maximum)


def validate_sessions(rows: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    previous_close: datetime | None = None
    for raw in rows:
        session = str(raw.get("session") or "").strip()
        close_at = str(raw.get("market_close_utc") or "").strip()
        if not session or not close_at:
            raise ContractError("session and market_close_utc are required")
        if session in seen:
            raise ContractError(f"duplicate market session: {session}")
        close_dt = utc(close_at)
        if previous_close is not None and close_dt <= previous_close:
            raise ContractError("market sessions must be strictly chronological")
        if close_dt.date().isoformat() != session:
            raise ContractError(f"session/close date mismatch: {session} vs {close_at}")
        out.append({"session": session, "market_close_utc": close_dt.isoformat()})
        seen.add(session)
        previous_close = close_dt
    if not out:
        raise ContractError("at least one explicit market session is required")
    return out


def validate_price_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in rows:
        security_id = str(raw.get("security_id") or "").strip().upper()
        session = str(raw.get("session") or "").strip()
        if not security_id or not session:
            raise ContractError("price row security_id and session are required")
        key = (security_id, session)
        if key in seen:
            raise ContractError(f"duplicate price row: {security_id} {session}")
        tri = _finite_float(raw.get("total_return_index"), label="total_return_index", minimum=1e-12)
        volume = _optional_float(raw.get("volume"), label="volume", minimum=0.0)
        out.append({
            "security_id": security_id,
            "session": session,
            "total_return_index": tri,
            "volume": volume,
        })
        seen.add(key)
    return out


def normalize_event(raw: dict[str, Any]) -> dict[str, Any]:
    event_id = str(raw.get("event_id") or "").strip()
    economic_event_id = str(raw.get("economic_event_id") or event_id).strip()
    security_id = str(raw.get("security_id") or raw.get("ticker") or "").strip().upper()
    available_at = str(raw.get("available_at") or "").strip()
    if not event_id or not economic_event_id or not security_id or not available_at:
        raise ContractError("event_id, economic_event_id, security_id, available_at required")
    utc(available_at)
    role = str(raw.get("role") or "INDIRECT").strip().upper()
    if role not in ROLES:
        raise ContractError(f"unsupported role: {role}")
    source_tier = str(raw.get("source_tier") or "OTHER").strip().upper()
    if source_tier not in SOURCE_TIERS:
        raise ContractError(f"unsupported source_tier: {source_tier}")
    sample_origin = str(raw.get("sample_origin") or "FORWARD_SHADOW").strip().upper()
    if sample_origin not in SAMPLE_ORIGINS:
        raise ContractError(f"unsupported sample_origin: {sample_origin}")
    instrument = str(raw.get("instrument") or "").strip().upper()
    exchange = str(raw.get("exchange") or "").strip().upper()
    listing_country = str(raw.get("listing_country") or "").strip().upper()
    if instrument not in ELIGIBLE_INSTRUMENTS:
        raise ContractError(f"ineligible instrument: {instrument!r}")
    if exchange not in ELIGIBLE_EXCHANGES:
        raise ContractError(f"ineligible exchange: {exchange!r}")
    if listing_country != "US":
        raise ContractError(f"non-US listing is not eligible: {listing_country!r}")
    if not bool(raw.get("eligibility_verified_asof", False)):
        raise ContractError("eligibility_verified_asof=true required")

    amount = _optional_float(raw.get("economic_amount_usd"), label="economic_amount_usd", minimum=0.0)
    amount_kind = str(raw.get("economic_amount_kind") or "UNKNOWN").strip().upper()
    if amount is None:
        amount_kind = "UNKNOWN"
    source_groups = sorted({
        str(x).strip()
        for x in (raw.get("independent_source_groups") or [])
        if str(x).strip()
    })
    peers = sorted({
        str(x).strip().upper()
        for x in (raw.get("theme_peer_ids") or [])
        if str(x).strip() and str(x).strip().upper() != security_id
    })
    risk_fields = {}
    for key in ("dilution_risk", "cashflow_risk", "balance_sheet_risk"):
        risk_fields[key] = _optional_float(raw.get(key), label=key, minimum=0.0, maximum=1.0)

    out = {
        "event_id": event_id,
        "economic_event_id": economic_event_id,
        "security_id": security_id,
        "issuer_id": str(raw.get("issuer_id") or security_id).strip(),
        "instrument": instrument,
        "exchange": exchange,
        "listing_country": listing_country,
        "eligibility_verified_asof": True,
        "available_at": utc(available_at).isoformat(),
        "event_type": str(raw.get("event_type") or "OTHER").strip().upper(),
        "role": role,
        "source_tier": source_tier,
        "official_evidence": bool(raw.get("official_evidence", source_tier == "OFFICIAL")),
        "business_relation_new": bool(raw.get("business_relation_new", False)),
        "economic_value_confirmed": bool(raw.get("economic_value_confirmed", amount is not None)),
        "economic_amount_usd": amount,
        "economic_amount_kind": amount_kind,
        "theme_id": str(raw.get("theme_id") or "UNASSIGNED").strip(),
        "independent_source_groups": source_groups,
        "source_family": str(raw.get("source_family") or "").strip(),
        "story_id": str(raw.get("story_id") or "").strip(),
        "theme_peer_ids": peers,
        "sample_origin": sample_origin,
        **risk_fields,
    }
    out["event_sha256"] = digest(out)
    return out


def normalize_events(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize and deduplicate multiple source mentions of one economic event.

    economic_event_id is the anti-double-counting key. If multiple source
    documents refer to the same economic event, only the strongest normalized
    record is retained and source groups are unioned. Independent article
    rewrites therefore do not become extra statistical observations.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_event_ids: set[str] = set()
    for raw in rows:
        event = normalize_event(raw)
        if event["event_id"] in seen_event_ids:
            raise ContractError(f"duplicate event_id: {event['event_id']}")
        seen_event_ids.add(event["event_id"])
        grouped[event["economic_event_id"]].append(event)

    tier_rank = {"OFFICIAL": 4, "PRIMARY": 3, "TIER1_NEWS": 2, "OTHER": 1}
    role_rank = {"DIRECT": 4, "ENABLER": 3, "INDIRECT": 2, "NARRATIVE": 1}
    out: list[dict[str, Any]] = []
    for economic_id, events in grouped.items():
        security_ids = {e["security_id"] for e in events}
        if len(security_ids) != 1:
            raise ContractError(f"economic_event_id spans multiple securities: {economic_id}")
        events.sort(
            key=lambda e: (
                bool(e["official_evidence"]),
                tier_rank[e["source_tier"]],
                role_rank[e["role"]],
                bool(e["economic_value_confirmed"]),
                len(e["independent_source_groups"]),
            ),
            reverse=True,
        )
        best = dict(events[0])
        best["source_record_count"] = len(events)
        best["independent_source_groups"] = sorted(
            {g for e in events for g in e["independent_source_groups"]}
        )
        best["event_sha256"] = digest({k: v for k, v in best.items() if k != "event_sha256"})
        out.append(best)
    out.sort(key=lambda e: (e["available_at"], e["economic_event_id"]))
    return out


class PriceBook:
    def __init__(self, rows: Iterable[dict[str, Any]], sessions: Sequence[dict[str, str]]):
        self.sessions = [r["session"] for r in sessions]
        self.session_pos = {s: i for i, s in enumerate(self.sessions)}
        self.close_at = {r["session"]: utc(r["market_close_utc"]) for r in sessions}
        self.data: dict[str, dict[str, dict[str, float | None]]] = defaultdict(dict)
        for row in validate_price_rows(rows):
            if row["session"] not in self.session_pos:
                raise ContractError(f"price session missing from calendar: {row['session']}")
            self.data[row["security_id"]][row["session"]] = {
                "tri": float(row["total_return_index"]),
                "volume": row["volume"],
            }

    def decision_session(self, available_at: str) -> str | None:
        ts = utc(available_at)
        for session in self.sessions:
            if ts <= self.close_at[session]:
                return session
        return None

    def shift(self, session: str, steps: int) -> str | None:
        pos = self.session_pos.get(session)
        if pos is None:
            return None
        target = pos + steps
        if target < 0 or target >= len(self.sessions):
            return None
        return self.sessions[target]

    def tri(self, security_id: str, session: str) -> float | None:
        row = self.data.get(security_id.upper(), {}).get(session)
        return None if row is None else float(row["tri"])

    def volume(self, security_id: str, session: str) -> float | None:
        row = self.data.get(security_id.upper(), {}).get(session)
        if row is None or row["volume"] is None:
            return None
        return float(row["volume"])

    def ret(self, security_id: str, start: str, end: str) -> float | None:
        p0 = self.tri(security_id, start)
        p1 = self.tri(security_id, end)
        if p0 is None or p1 is None or p0 <= 0:
            return None
        return p1 / p0 - 1.0

    def excess(self, security_id: str, benchmark_id: str, start: str, end: str) -> float | None:
        a = self.ret(security_id, start, end)
        b = self.ret(benchmark_id, start, end)
        if a is None or b is None:
            return None
        return a - b

    def volume_ratio(self, security_id: str, session: str, trailing: int = 20) -> float | None:
        pos = self.session_pos.get(session)
        if pos is None or pos < 1:
            return None
        current = self.volume(security_id, session)
        if current is None:
            return None
        hist: list[float] = []
        for idx in range(max(0, pos - trailing), pos):
            v = self.volume(security_id, self.sessions[idx])
            if v is not None and v > 0:
                hist.append(v)
        if len(hist) < max(5, trailing // 2):
            return None
        median = statistics.median(hist)
        return None if median <= 0 else current / median


def _pre_excess(book: PriceBook, security_id: str, benchmark_id: str, decision_session: str, horizon: int) -> float | None:
    end = book.shift(decision_session, -1)
    if end is None:
        return None
    start = book.shift(end, -horizon)
    if start is None:
        return None
    return book.excess(security_id, benchmark_id, start, end)


def _breadth(
    book: PriceBook,
    peers: Sequence[str],
    benchmark_id: str,
    start: str,
    end: str,
    *,
    min_peers: int = 3,
) -> tuple[float | None, int]:
    values: list[float] = []
    for peer in peers:
        value = book.excess(peer, benchmark_id, start, end)
        if value is not None:
            values.append(value)
    if len(values) < min_peers:
        return None, len(values)
    return sum(v > 0 for v in values) / len(values), len(values)


def _max_path_excursion(
    book: PriceBook,
    security_id: str,
    benchmark_id: str,
    start: str,
    horizon: int,
) -> tuple[float | None, float | None]:
    start_pos = book.session_pos.get(start)
    if start_pos is None or start_pos + horizon >= len(book.sessions):
        return None, None
    path: list[float] = []
    for step in range(1, horizon + 1):
        end = book.sessions[start_pos + step]
        x = book.excess(security_id, benchmark_id, start, end)
        if x is None:
            return None, None
        path.append(x)
    return max(path), min(path)


def build_checkpoint_rows(
    events: Iterable[dict[str, Any]],
    price_rows: Iterable[dict[str, Any]],
    market_sessions: Iterable[dict[str, Any]],
    *,
    benchmark_id: str = "SPY",
) -> list[dict[str, Any]]:
    sessions = validate_sessions(market_sessions)
    book = PriceBook(price_rows, sessions)
    benchmark_id = benchmark_id.upper()
    if benchmark_id not in book.data:
        raise ContractError(f"benchmark price series missing: {benchmark_id}")
    normalized = normalize_events(events)
    rows: list[dict[str, Any]] = []

    for event in normalized:
        security_id = event["security_id"]
        event_session = book.decision_session(event["available_at"])
        if event_session is None:
            continue
        previous_session = book.shift(event_session, -1)
        if previous_session is None:
            continue
        event_day_excess = book.excess(security_id, benchmark_id, previous_session, event_session)
        event_day_return = book.ret(security_id, previous_session, event_session)
        event_volume_ratio = book.volume_ratio(security_id, event_session)
        event_breadth, event_breadth_n = _breadth(
            book,
            event["theme_peer_ids"],
            benchmark_id,
            previous_session,
            event_session,
        )
        pre_rs20 = _pre_excess(book, security_id, benchmark_id, event_session, 20)
        pre_rs60 = _pre_excess(book, security_id, benchmark_id, event_session, 60)

        for checkpoint in CHECKPOINTS:
            checkpoint_session = book.shift(event_session, checkpoint)
            if checkpoint_session is None:
                continue
            if checkpoint == 0:
                post_rs = event_day_excess
                breadth = event_breadth
                breadth_n = event_breadth_n
            else:
                post_rs = book.excess(security_id, benchmark_id, event_session, checkpoint_session)
                breadth, breadth_n = _breadth(
                    book,
                    event["theme_peer_ids"],
                    benchmark_id,
                    event_session,
                    checkpoint_session,
                )

            official_direct = bool(event["official_evidence"] and event["role"] == "DIRECT")
            business_substance = bool(
                event["economic_value_confirmed"] or event["business_relation_new"]
            )
            price_confirmed = bool(post_rs is not None and post_rs > 0)
            breadth_confirmed = bool(breadth is not None and breadth >= 0.50)
            combo = bool(
                checkpoint in {5, 10, 20}
                and official_direct
                and business_substance
                and price_confirmed
                and breadth_confirmed
            )
            risk_values = [
                x for x in (
                    event["dilution_risk"],
                    event["cashflow_risk"],
                    event["balance_sheet_risk"],
                ) if x is not None
            ]
            max_risk = max(risk_values) if risk_values else None
            row = {
                **event,
                "benchmark_id": benchmark_id,
                "event_session": event_session,
                "checkpoint": checkpoint,
                "checkpoint_session": checkpoint_session,
                "pre_rs20": pre_rs20,
                "pre_rs60": pre_rs60,
                "event_day_return": event_day_return,
                "event_day_excess": event_day_excess,
                "event_volume_ratio20": event_volume_ratio,
                "post_rs_checkpoint": post_rs,
                "theme_breadth_checkpoint": breadth,
                "theme_breadth_peer_count": breadth_n,
                "official_direct": official_direct,
                "business_substance": business_substance,
                "price_confirmed": price_confirmed,
                "breadth_confirmed": breadth_confirmed,
                "confirmed_combo": combo,
                "max_financing_risk": max_risk,
            }
            row["row_sha256"] = digest({k: v for k, v in row.items() if k != "row_sha256"})
            rows.append(row)
    return rows


def attach_forward_outcomes(
    checkpoint_rows: Iterable[dict[str, Any]],
    price_rows: Iterable[dict[str, Any]],
    market_sessions: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    sessions = validate_sessions(market_sessions)
    book = PriceBook(price_rows, sessions)
    out: list[dict[str, Any]] = []
    for row in checkpoint_rows:
        start = str(row["checkpoint_session"])
        security_id = str(row["security_id"]).upper()
        benchmark_id = str(row["benchmark_id"]).upper()
        for horizon in HORIZONS:
            end = book.shift(start, horizon)
            if end is None:
                excess = absolute = benchmark = mfe = mae = None
                status = "PENDING_HORIZON"
            else:
                absolute = book.ret(security_id, start, end)
                benchmark = book.ret(benchmark_id, start, end)
                excess = None if absolute is None or benchmark is None else absolute - benchmark
                if excess is None:
                    mfe = mae = None
                    status = "PENDING_PRICE_GAP"
                else:
                    mfe, mae = _max_path_excursion(book, security_id, benchmark_id, start, horizon)
                    status = "RESOLVED" if mfe is not None and mae is not None else "PENDING_PRICE_GAP"
            labeled = {
                **row,
                "horizon": horizon,
                "outcome_end_session": end,
                "absolute_return": absolute,
                "benchmark_return": benchmark,
                "excess_return": excess,
                "max_favorable_excess": mfe,
                "max_adverse_excess": mae,
                "outcome_status": status,
            }
            labeled["outcome_sha256"] = digest({k: v for k, v in labeled.items() if k != "outcome_sha256"})
            out.append(labeled)
    return out


def _arm_membership(row: dict[str, Any], arm: str) -> bool:
    if arm == "ALL":
        return True
    if arm == "OFFICIAL_DIRECT":
        return bool(row.get("official_direct"))
    if arm == "OFFICIAL_DIRECT_SUBSTANCE":
        return bool(row.get("official_direct") and row.get("business_substance"))
    if arm == "CONFIRMED_COMBO":
        return bool(row.get("confirmed_combo"))
    raise ContractError(f"unknown analysis arm: {arm}")


def _sample_stats(values: Sequence[float]) -> dict[str, Any]:
    ordered = sorted(values)
    n = len(ordered)
    mean = statistics.fmean(ordered)
    median = statistics.median(ordered)
    stdev = statistics.stdev(ordered) if n >= 2 else 0.0
    sem = stdev / math.sqrt(n) if n else None
    ci_half = 1.96 * sem if sem is not None else None

    def quantile(p: float) -> float:
        if n == 1:
            return ordered[0]
        pos = (n - 1) * p
        low = int(math.floor(pos))
        high = int(math.ceil(pos))
        if low == high:
            return ordered[low]
        w = pos - low
        return ordered[low] * (1 - w) + ordered[high] * w

    return {
        "n": n,
        "mean_excess": mean,
        "median_excess": median,
        "win_rate_excess_gt0": sum(v > 0 for v in ordered) / n,
        "hit_rate_excess_gt5pct": sum(v > 0.05 for v in ordered) / n,
        "hit_rate_excess_gt10pct": sum(v > 0.10 for v in ordered) / n,
        "q25_excess": quantile(0.25),
        "q75_excess": quantile(0.75),
        "ci95_mean_low": mean - ci_half,
        "ci95_mean_high": mean + ci_half,
    }



def _cluster_stats(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Equal-weight issuer-year clusters to reduce repeated-story pseudo-power.

    This is intentionally conservative and deterministic. It does not claim to
    be a full two-way dependence model, but promotion uses this cluster-level CI
    rather than the naive event-row CI.
    """
    clusters: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        issuer = str(row.get("issuer_id") or row.get("security_id") or "UNKNOWN")
        year = str(row.get("event_session") or "")[:4]
        clusters[f"{issuer}:{year}"].append(float(row["excess_return"]))
    means = [statistics.fmean(values) for values in clusters.values() if values]
    if not means:
        return {
            "issuer_year_cluster_n": 0,
            "issuer_year_cluster_mean_excess": None,
            "issuer_year_cluster_median_excess": None,
            "issuer_year_cluster_ci95_mean_low": None,
            "issuer_year_cluster_ci95_mean_high": None,
        }
    stats = _sample_stats(means)
    return {
        "issuer_year_cluster_n": stats["n"],
        "issuer_year_cluster_mean_excess": stats["mean_excess"],
        "issuer_year_cluster_median_excess": stats["median_excess"],
        "issuer_year_cluster_ci95_mean_low": stats["ci95_mean_low"],
        "issuer_year_cluster_ci95_mean_high": stats["ci95_mean_high"],
    }

def summarize_impacts(
    outcome_rows: Iterable[dict[str, Any]],
    *,
    include_event_type_breakdown: bool = True,
    minimum_breakdown_n: int = 20,
) -> list[dict[str, Any]]:
    resolved = [
        r for r in outcome_rows
        if r.get("outcome_status") == "RESOLVED" and r.get("excess_return") is not None
    ]
    arms = ("ALL", "OFFICIAL_DIRECT", "OFFICIAL_DIRECT_SUBSTANCE", "CONFIRMED_COMBO")
    summaries: list[dict[str, Any]] = []
    for origin in sorted(SAMPLE_ORIGINS):
        origin_rows = [r for r in resolved if r.get("sample_origin") == origin]
        for checkpoint in CHECKPOINTS:
            cp_rows = [r for r in origin_rows if int(r.get("checkpoint", -1)) == checkpoint]
            for horizon in HORIZONS:
                hz_rows = [r for r in cp_rows if int(r.get("horizon", -1)) == horizon]
                for arm in arms:
                    group = [r for r in hz_rows if _arm_membership(r, arm)]
                    values = [float(r["excess_return"]) for r in group]
                    if not values:
                        continue
                    years = {str(r["event_session"])[:4] for r in group}
                    issuers = {str(r.get("issuer_id") or r["security_id"]) for r in group}
                    summaries.append({
                        "sample_origin": origin,
                        "checkpoint": checkpoint,
                        "horizon": horizon,
                        "arm": arm,
                        "event_type": "ALL",
                        "distinct_years": len(years),
                        "distinct_issuers": len(issuers),
                        **_sample_stats(values),
                        **_cluster_stats(group),
                    })
                    if include_event_type_breakdown:
                        by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
                        for r in group:
                            by_type[str(r.get("event_type") or "OTHER")].append(r)
                        for event_type, typed in by_type.items():
                            if len(typed) < minimum_breakdown_n:
                                continue
                            tvalues = [float(r["excess_return"]) for r in typed]
                            summaries.append({
                                "sample_origin": origin,
                                "checkpoint": checkpoint,
                                "horizon": horizon,
                                "arm": arm,
                                "event_type": event_type,
                                "distinct_years": len({str(r["event_session"])[:4] for r in typed}),
                                "distinct_issuers": len({str(r.get("issuer_id") or r["security_id"]) for r in typed}),
                                **_sample_stats(tvalues),
                                **_cluster_stats(typed),
                            })
    return summaries


def _summary_lookup(summaries: Iterable[dict[str, Any]], origin: str, checkpoint: int, horizon: int) -> dict[str, Any] | None:
    for row in summaries:
        if (
            row.get("sample_origin") == origin
            and int(row.get("checkpoint", -1)) == checkpoint
            and int(row.get("horizon", -1)) == horizon
            and row.get("arm") == "CONFIRMED_COMBO"
            and row.get("event_type") == "ALL"
        ):
            return row
    return None


def build_challenger_proposal(
    summaries: Iterable[dict[str, Any]],
    *,
    checkpoint: int = 5,
) -> dict[str, Any]:
    """Build a manual-review promotion proposal; never activate a selector."""
    summaries = list(summaries)
    reasons: list[str] = []
    details: dict[str, Any] = {}
    for origin in ("HISTORICAL_BACKFILL", "FORWARD_SHADOW"):
        origin_details = {}
        for horizon in PROMOTION_HORIZONS:
            row = _summary_lookup(summaries, origin, checkpoint, horizon)
            origin_details[str(horizon)] = row
            if row is None:
                reasons.append(f"{origin}:{horizon}:MISSING_COMBO_SUMMARY")
                continue
            if int(row["n"]) < POWER_MINIMUMS[horizon]:
                reasons.append(
                    f"{origin}:{horizon}:UNDERPOWERED:{row['n']}<{POWER_MINIMUMS[horizon]}"
                )
            if int(row["distinct_years"]) < 3 and origin == "HISTORICAL_BACKFILL":
                reasons.append(f"{origin}:{horizon}:LESS_THAN_3_YEARS")
            if int(row["distinct_issuers"]) < 25:
                reasons.append(f"{origin}:{horizon}:LESS_THAN_25_ISSUERS")
            if float(row["median_excess"]) <= 0:
                reasons.append(f"{origin}:{horizon}:NONPOSITIVE_MEDIAN")
        details[origin] = origin_details

    hist63 = _summary_lookup(summaries, "HISTORICAL_BACKFILL", checkpoint, 63)
    fwd63 = _summary_lookup(summaries, "FORWARD_SHADOW", checkpoint, 63)
    for label, row in (("HISTORICAL_BACKFILL", hist63), ("FORWARD_SHADOW", fwd63)):
        if row is None:
            continue
        cluster_low = row.get("issuer_year_cluster_ci95_mean_low")
        if cluster_low is None or float(cluster_low) <= 0:
            reasons.append(f"{label}:63:ISSUER_YEAR_CLUSTER_CI95_LOW_NOT_POSITIVE")

    eligible = not reasons
    return {
        "schema": "news-event-alpha-challenger-proposal-v1",
        "checkpoint": checkpoint,
        "status": "RESEARCH_CHALLENGER_REVIEW_ELIGIBLE" if eligible else "UNDERPOWERED_OR_BLOCKED",
        "manual_review_required": True,
        "selector_eligible": False,
        "production_activation_allowed": False,
        "automatic_promotion_allowed": False,
        "fullrun_required_for_this_proposal": False,
        "power_minimums": POWER_MINIMUMS,
        "reasons": reasons,
        "evidence": details,
    }


def research_priority(row: dict[str, Any]) -> float:
    """Triage score used only to limit report display; not an investment score."""
    score = 0.0
    if row.get("official_evidence"):
        score += 18
    score += {"OFFICIAL": 10, "PRIMARY": 8, "TIER1_NEWS": 5, "OTHER": 0}.get(str(row.get("source_tier")), 0)
    score += {"DIRECT": 16, "ENABLER": 9, "INDIRECT": 4, "NARRATIVE": 0}.get(str(row.get("role")), 0)
    if row.get("business_relation_new"):
        score += 10
    if row.get("economic_value_confirmed"):
        score += 12
    event_excess = row.get("event_day_excess")
    if event_excess is not None:
        score += max(-4.0, min(8.0, float(event_excess) * 100.0))
    volume_ratio = row.get("event_volume_ratio20")
    if volume_ratio is not None and float(volume_ratio) >= 1.5:
        score += min(6.0, (float(volume_ratio) - 1.0) * 3.0)
    if row.get("price_confirmed"):
        score += 8
    if row.get("breadth_confirmed"):
        score += 8
    max_risk = row.get("max_financing_risk")
    if max_risk is not None:
        score -= 15.0 * float(max_risk)
    return round(max(0.0, min(100.0, score)), 2)


def top_current_events(checkpoint_rows: Iterable[dict[str, Any]], *, top_n: int = 5, checkpoint: int = 5) -> list[dict[str, Any]]:
    latest_by_event: dict[str, dict[str, Any]] = {}
    for row in checkpoint_rows:
        if int(row.get("checkpoint", -1)) != checkpoint:
            continue
        event_id = str(row["economic_event_id"])
        ranked = dict(row)
        ranked["research_priority"] = research_priority(ranked)
        latest_by_event[event_id] = ranked
    ordered = sorted(
        latest_by_event.values(),
        key=lambda r: (float(r["research_priority"]), r["checkpoint_session"]),
        reverse=True,
    )
    return ordered[: max(0, int(top_n))]


def run_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != SCHEMA_VERSION:
        raise ContractError(f"schema must be {SCHEMA_VERSION}")
    events = payload.get("events", [])
    prices = payload.get("prices", [])
    sessions = payload.get("market_sessions", [])
    benchmark_id = str(payload.get("benchmark_id") or "SPY").upper()
    checkpoint_rows = build_checkpoint_rows(events, prices, sessions, benchmark_id=benchmark_id)
    outcomes = attach_forward_outcomes(checkpoint_rows, prices, sessions)
    summaries = summarize_impacts(outcomes)
    from .walk_forward import (
        build_walk_forward_impact_estimates,
        summarize_walk_forward_performance,
    )
    walk_forward_estimates = build_walk_forward_impact_estimates(checkpoint_rows, outcomes)
    walk_forward_performance = summarize_walk_forward_performance(walk_forward_estimates)
    proposal = build_challenger_proposal(summaries, checkpoint=int(payload.get("promotion_checkpoint", 5)))
    top_events = top_current_events(
        checkpoint_rows,
        top_n=int(payload.get("report_top_n", 5)),
        checkpoint=int(payload.get("report_checkpoint", 5)),
    )
    result = {
        "schema": RESULT_SCHEMA,
        "research_only": True,
        "selector_eligible": False,
        "target_book_changed": False,
        "orders_generated": False,
        "production_activation_allowed": False,
        "automatic_promotion_allowed": False,
        "benchmark_id": benchmark_id,
        "normalized_event_count": len(normalize_events(events)),
        "checkpoint_row_count": len(checkpoint_rows),
        "resolved_outcome_count": sum(r["outcome_status"] == "RESOLVED" for r in outcomes),
        "checkpoint_rows": checkpoint_rows,
        "outcomes": outcomes,
        "impact_summaries": summaries,
        "walk_forward_impact_estimates": walk_forward_estimates,
        "walk_forward_performance": walk_forward_performance,
        "challenger_proposal": proposal,
        "top_current_events": top_events,
    }
    result["result_sha256"] = digest(result)
    return result

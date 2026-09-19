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

SCHEMA_VERSION = "news-event-alpha-v1-p0.1"
RESULT_SCHEMA = "news-event-alpha-result-v1-p0.1"
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
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
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


# P0-1: one immutable assertion revision, not one mutable strongest article.
IDENTITY_CONTRACT = "news-event-identity-p0.1"
LABEL_CONTRACT = "checkpoint-close-observation-p0.1"
ANALOGUE_MODEL_VERSION = "historical-analogue-p0.1"


def strict_bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise ContractError(f"{label}: JSON boolean required")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label}: nonempty string required")
    return value.strip()


def _version(value: Any) -> int:
    if type(value) is not int or value < 1:
        raise ContractError("event_version: positive JSON integer required")
    return value


def _text_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ContractError(f"{label}: array of strings required")
    return sorted({_text(v, label) for v in value})


def event_security_key(row: dict[str, Any]) -> tuple[str, str]:
    # A ticker is never silently certified as a stable security identifier.
    return (_text(row.get("economic_event_id"), "economic_event_id"),
            _text(row.get("stable_security_id"), "stable_security_id"))


def event_revision_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return (*event_security_key(row), _version(row.get("event_version")))


def checkpoint_key(row: dict[str, Any]) -> tuple:
    checkpoint = row.get("checkpoint")
    if type(checkpoint) is not int or checkpoint not in CHECKPOINTS:
        raise ContractError("invalid checkpoint identity")
    return (*event_revision_key(row), checkpoint,
            _text(row.get("checkpoint_session"), "checkpoint_session"),
            utc(_text(row.get("decision_at"), "decision_at")).isoformat())


def outcome_key(row: dict[str, Any], horizon: int | None = None) -> tuple:
    h = row.get("horizon") if horizon is None else horizon
    if type(h) is not int or h not in HORIZONS:
        raise ContractError("invalid horizon identity")
    return (*checkpoint_key(row), h,
            _text(row.get("label_contract"), "label_contract"))


def prediction_key(row: dict[str, Any], horizon: int | None = None) -> tuple:
    return (*outcome_key(row, horizon),
            _text(row.get("model_version"), "model_version"))


def unique_index(rows: Iterable[dict[str, Any]], key_fn: Any, label: str) -> dict:
    index = {}
    for row in rows:
        key = key_fn(row)
        if key in index:
            raise ContractError(f"duplicate {label} identity: {key}")
        index[key] = row
    return index


def normalize_event(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ContractError("event must be an object")
    event_id = _text(raw.get("event_id"), "event_id")
    economic_id = _text(raw.get("economic_event_id"), "economic_event_id")
    security_id = _text(raw.get("security_id"), "security_id").upper()
    stable_id = _text(raw.get("stable_security_id"), "stable_security_id")
    issuer_id = _text(raw.get("issuer_id"), "issuer_id")
    version = _version(raw.get("event_version"))
    available = utc(_text(raw.get("available_at"), "available_at"))
    if version > 1 and not raw.get("first_available_at"):
        raise ContractError("revision requires original first_available_at")
    first = utc(raw.get("first_available_at", available.isoformat()))
    if first > available or (version == 1 and first != available):
        raise ContractError("invalid original event availability")
    # Producers may supply per-field clocks. None may be later than the snapshot.
    field_times = raw.get("field_available_at", {})
    if not isinstance(field_times, dict):
        raise ContractError("field_available_at must be an object")
    field_times = {_text(k, "field clock name"): utc(v).isoformat()
                   for k, v in field_times.items()}
    if any(utc(v) > available for v in field_times.values()):
        raise ContractError("future field in evidence revision")
    role = _text(raw.get("role", "INDIRECT"), "role").upper()
    tier = _text(raw.get("source_tier", "OTHER"), "source_tier").upper()
    origin = _text(raw.get("sample_origin", "FORWARD_SHADOW"), "sample_origin").upper()
    instrument = _text(raw.get("instrument"), "instrument").upper()
    exchange = _text(raw.get("exchange"), "exchange").upper()
    country = _text(raw.get("listing_country"), "listing_country").upper()
    if role not in ROLES or tier not in SOURCE_TIERS or origin not in SAMPLE_ORIGINS:
        raise ContractError("unsupported role/source/origin")
    if instrument not in ELIGIBLE_INSTRUMENTS or exchange not in ELIGIBLE_EXCHANGES or country != "US":
        raise ContractError("unverified US COMMON/ADR eligibility")
    if not strict_bool(raw.get("eligibility_verified_asof", False), "eligibility_verified_asof"):
        raise ContractError("eligibility_verified_asof=true required")
    amount = _optional_float(raw.get("economic_amount_usd"), label="economic_amount_usd", minimum=0)
    kind = _text(raw.get("economic_amount_kind", "UNKNOWN"), "economic_amount_kind").upper()
    if amount is None:
        kind = "UNKNOWN"
    ids = _text_list(raw.get("source_record_ids", [event_id]), "source_record_ids")
    if event_id not in ids:
        raise ContractError("event_id absent from source_record_ids")
    count = raw.get("source_record_count", len(ids))
    if type(count) is not int or count != len(ids):
        raise ContractError("legacy collapsed source record or count mismatch")
    peers = sorted({v.upper() for v in _text_list(raw.get("theme_peer_ids", []), "theme_peer_ids")
                    if v.upper() != security_id})
    out = {
        "identity_contract": IDENTITY_CONTRACT,
        "event_id": event_id, "economic_event_id": economic_id,
        "security_id": security_id, "stable_security_id": stable_id,
        "issuer_id": issuer_id, "event_version": version,
        "instrument": instrument, "exchange": exchange, "listing_country": country,
        "eligibility_verified_asof": True,
        "available_at": available.isoformat(), "first_available_at": first.isoformat(),
        "field_available_at": field_times,
        "event_type": _text(raw.get("event_type", "OTHER"), "event_type").upper(),
        "role": role, "source_tier": tier,
        "official_evidence": strict_bool(raw.get("official_evidence", tier == "OFFICIAL"), "official_evidence"),
        "business_relation_new": strict_bool(raw.get("business_relation_new", False), "business_relation_new"),
        "material_agreement_confirmed": strict_bool(raw.get("material_agreement_confirmed", False), "material_agreement_confirmed"),
        "economic_value_confirmed": strict_bool(raw.get("economic_value_confirmed", amount is not None), "economic_value_confirmed"),
        "economic_amount_usd": amount, "economic_amount_kind": kind,
        "theme_id": _text(raw.get("theme_id", "UNASSIGNED"), "theme_id"),
        "independent_source_groups": _text_list(raw.get("independent_source_groups", []), "independent_source_groups"),
        "source_family": str(raw.get("source_family") or ""),
        "story_id": str(raw.get("story_id") or ""),
        "event_tags": _text_list(raw.get("event_tags", []), "event_tags"),
        "source_url": str(raw.get("source_url") or raw.get("filing_url") or ""),
        "theme_peer_ids": peers, "sample_origin": origin,
        "source_record_ids": ids, "source_record_count": len(ids),
    }
    for name in ("dilution_risk", "cashflow_risk", "balance_sheet_risk"):
        out[name] = _optional_float(raw.get(name), label=name, minimum=0, maximum=1)
    out["event_sha256"] = digest(out)
    if "identity_contract" in raw:
        if raw["identity_contract"] != IDENTITY_CONTRACT or raw.get("event_sha256") != out["event_sha256"]:
            raise ContractError("canonical event hash/contract mismatch")
    return out


def normalize_events(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge only contemporaneous, semantically identical source duplicates.

    Later corroboration, correction, or a changed role/amount needs a NEW
    explicit revision. Selecting the globally strongest source is forbidden.
    """
    grouped: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    source_seen: set[tuple] = set()
    for raw in rows:
        event = normalize_event(raw)
        key = event_revision_key(event)
        for sid in event["source_record_ids"]:
            source_key = (*key, sid)
            if source_key in source_seen:
                raise ContractError("duplicate source record identity")
            source_seen.add(source_key)
        grouped[key].append(event)
    provenance = {"event_id", "event_sha256", "source_record_ids", "source_record_count",
                  "source_url", "source_family", "story_id", "independent_source_groups"}
    out = []
    for key, group in grouped.items():
        group.sort(key=lambda r: r["event_id"])
        first = group[0]
        meaning = {k: v for k, v in first.items() if k not in provenance}
        if any({k: v for k, v in g.items() if k not in provenance} != meaning for g in group[1:]):
            raise ContractError(f"ambiguous revision: create a new version for {key}")
        row = dict(first)
        row["source_record_ids"] = sorted({s for g in group for s in g["source_record_ids"]})
        row["source_record_count"] = len(row["source_record_ids"])
        row["independent_source_groups"] = sorted({s for g in group for s in g["independent_source_groups"]})
        row["event_sha256"] = digest({k: v for k, v in row.items() if k != "event_sha256"})
        out.append(row)
    return sorted(out, key=lambda r: (r["available_at"], event_revision_key(r)))


def revision_series(events: Iterable[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    unique_index(events := list(events), event_revision_key, "event revision")
    grouped: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[event_security_key(event)].append(event)
    out = []
    for key, group in sorted(grouped.items()):
        group.sort(key=lambda r: r["event_version"])
        if [r["event_version"] for r in group] != list(range(1, len(group) + 1)):
            raise ContractError(f"incomplete event revision chain: {key}")
        anchor = group[0]["available_at"]
        for i, r in enumerate(group):
            if r["first_available_at"] != anchor:
                raise ContractError("revision changed original observation clock")
            if any(r[k] != group[0][k] for k in ("security_id", "issuer_id", "sample_origin", "instrument")):
                raise ContractError("identity/origin changed inside revision chain")
            if i and utc(r["available_at"]) <= utc(group[i - 1]["available_at"]):
                raise ContractError("non-increasing revision availability")
        out.append(group)
    return out


def merge_immutable_events(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # No deletion, automatic migration, recategorization, or last-write-wins.
    index = unique_index(existing, event_revision_key, "existing ledger")
    unique_index(incoming, event_revision_key, "incoming ledger")
    for raw in existing + incoming:
        if raw.get("identity_contract") != IDENTITY_CONTRACT:
            raise ContractError("ledger migration required; legacy evidence is not certified")
        normalize_event(raw)  # also verifies the canonical semantic hash
    for row in incoming:
        key = event_revision_key(row)
        if key in index and digest(index[key]) != digest(row):
            raise ContractError(f"immutable event conflict: {key}")
        index.setdefault(key, row)
    result = sorted(index.values(), key=lambda r: (r["available_at"], event_revision_key(r)))
    revision_series(result)
    return result

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
    as_of: str | None = None,
) -> list[dict[str, Any]]:
    sessions = validate_sessions(market_sessions)
    book = PriceBook(price_rows, sessions)
    benchmark_id = benchmark_id.upper()
    if benchmark_id not in book.data:
        raise ContractError(f"benchmark price series missing: {benchmark_id}")
    cutoff = utc(as_of) if as_of is not None else book.close_at[book.sessions[-1]]
    rows = []
    for versions in revision_series(normalize_events(events)):
        original = versions[0]
        security_id = original["security_id"]
        event_session = book.decision_session(original["first_available_at"])
        if event_session is None:
            continue
        previous = book.shift(event_session, -1)
        if previous is None:
            continue
        event_return = book.ret(security_id, previous, event_session)
        event_excess = book.excess(security_id, benchmark_id, previous, event_session)
        pre20 = _pre_excess(book, security_id, benchmark_id, event_session, 20)
        pre60 = _pre_excess(book, security_id, benchmark_id, event_session, 60)
        for cp in CHECKPOINTS:
            cp_session = book.shift(event_session, cp)
            if cp_session is None or book.close_at[cp_session] > cutoff:
                continue
            decision_at = book.close_at[cp_session]
            known = [r for r in versions if utc(r["available_at"]) <= decision_at]
            if not known:
                continue
            event = known[-1]
            start = previous if cp == 0 else event_session
            post_rs = book.excess(security_id, benchmark_id, start, cp_session)
            breadth, breadth_n = _breadth(book, event["theme_peer_ids"], benchmark_id, start, cp_session)
            official_direct = event["official_evidence"] and event["role"] == "DIRECT"
            substance = any(event[k] for k in ("economic_value_confirmed", "business_relation_new", "material_agreement_confirmed"))
            confirmed = post_rs is not None and post_rs > 0
            breadth_confirmed = breadth is not None and breadth >= 0.50
            risks = [event[k] for k in ("dilution_risk", "cashflow_risk", "balance_sheet_risk") if event[k] is not None]
            row = {
                **event, "benchmark_id": benchmark_id,
                "event_session": event_session, "checkpoint": cp,
                "checkpoint_session": cp_session, "decision_at": decision_at.isoformat(),
                "label_contract": LABEL_CONTRACT,
                "model_version": ANALOGUE_MODEL_VERSION,
                "pre_rs20": pre20, "pre_rs60": pre60,
                "event_day_return": event_return, "event_day_excess": event_excess,
                "event_volume_ratio20": book.volume_ratio(security_id, event_session),
                "post_rs_checkpoint": post_rs, "theme_breadth_checkpoint": breadth,
                "theme_breadth_peer_count": breadth_n, "official_direct": official_direct,
                "business_substance": substance, "price_confirmed": confirmed,
                "breadth_confirmed": breadth_confirmed,
                "confirmed_combo": cp in {5, 10, 20} and official_direct and substance and confirmed and breadth_confirmed,
                "max_financing_risk": max(risks) if risks else None,
            }
            row["checkpoint_id"] = digest(checkpoint_key(row))
            row["row_sha256"] = digest(row)
            rows.append(row)
    unique_index(rows, checkpoint_key, "checkpoint")
    return rows

def attach_forward_outcomes(
    checkpoint_rows: Iterable[dict[str, Any]],
    price_rows: Iterable[dict[str, Any]],
    market_sessions: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    sessions = validate_sessions(market_sessions)
    book = PriceBook(price_rows, sessions)
    checkpoint_rows = list(checkpoint_rows)
    unique_index(checkpoint_rows, checkpoint_key, "checkpoint")
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
            labeled["outcome_id"] = digest(outcome_key(labeled))
            labeled["return_kind"] = "OBSERVATION_ONLY_NOT_EXECUTABLE"
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


def _economic_event_cluster_stats(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Average security outcomes within one economic story before inference."""
    clusters: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        key = str(row.get("economic_event_id") or row.get("event_id") or "UNKNOWN")
        clusters[key].append(float(row["excess_return"]))
    means = [statistics.fmean(values) for values in clusters.values() if values]
    if not means:
        return {
            "economic_event_cluster_n": 0,
            "economic_event_cluster_mean_excess": None,
            "economic_event_cluster_median_excess": None,
            "economic_event_cluster_ci95_mean_low": None,
            "economic_event_cluster_ci95_mean_high": None,
        }
    stats = _sample_stats(means)
    return {
        "economic_event_cluster_n": stats["n"],
        "economic_event_cluster_mean_excess": stats["mean_excess"],
        "economic_event_cluster_median_excess": stats["median_excess"],
        "economic_event_cluster_ci95_mean_low": stats["ci95_mean_low"],
        "economic_event_cluster_ci95_mean_high": stats["ci95_mean_high"],
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
                        **_economic_event_cluster_stats(group),
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
                                **_economic_event_cluster_stats(typed),
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
        issuer_cluster_low = row.get("issuer_year_cluster_ci95_mean_low")
        event_cluster_low = row.get("economic_event_cluster_ci95_mean_low")
        if issuer_cluster_low is None or float(issuer_cluster_low) <= 0:
            reasons.append(f"{label}:63:ISSUER_YEAR_CLUSTER_CI95_LOW_NOT_POSITIVE")
        if event_cluster_low is None or float(event_cluster_low) <= 0:
            reasons.append(f"{label}:63:ECONOMIC_EVENT_CLUSTER_CI95_LOW_NOT_POSITIVE")

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
    latest_by_event: dict[tuple, dict[str, Any]] = {}
    for row in checkpoint_rows:
        if int(row.get("checkpoint", -1)) != checkpoint:
            continue
        event_id = checkpoint_key(row)
        if event_id in latest_by_event:
            raise ContractError("duplicate top checkpoint identity")
        ranked = dict(row)
        ranked["research_priority"] = research_priority(ranked)
        latest_by_event[event_id] = ranked
    ordered = sorted(
        latest_by_event.values(),
        key=lambda r: (float(r["research_priority"]), r["checkpoint_session"], event_revision_key(r)),
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
    checkpoint_rows = build_checkpoint_rows(events, prices, sessions, benchmark_id=benchmark_id, as_of=payload.get("as_of"))
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
    from .reporting import build_top_event_impact_outlook
    top_event_impact_outlook = build_top_event_impact_outlook(
        top_events, walk_forward_estimates
    )
    result = {
        "schema": RESULT_SCHEMA,
        "research_only": True,
        "identity_contract": IDENTITY_CONTRACT,
        "selector_weight": 0.0,
        "input_acceptance_status": "NOT_CERTIFIED_P0_PARTIAL",
        "public_forecast_publication_allowed": False,
        "p0_remaining_blockers": ["verified_input_manifest", "executable_cost_labels", "active_lifecycle", "6k_seed", "repository_ci"],
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
        "top_event_impact_outlook": top_event_impact_outlook,
    }
    result["result_sha256"] = digest(result)
    return result

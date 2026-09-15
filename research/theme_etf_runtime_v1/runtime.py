"""Research-only theme/ETF leadership runtime."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any, Iterable

SCHEMA_VERSION = "theme-etf-runtime-v1"
ALLOWED_COVERAGE = {"FULL", "TOP_ONLY", "PARTIAL", "PCF", "PROXY", "NPORT"}
FULL_COVERAGE = "FULL"
ELIGIBLE_INSTRUMENTS = {"COMMON", "ADR"}
ELIGIBLE_EXCHANGES = {"XNYS", "XNAS", "XASE"}
HORIZONS = (5, 20, 60, 120, 240)


class ContractError(ValueError):
    pass


def utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ContractError(f"timezone required: {value!r}")
    return dt.astimezone(timezone.utc)


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def normalize_weight(value: Any, unit: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ContractError("weight must be a finite numeric value")
    try:
        x = float(str(value).strip().replace("%", ""))
    except (TypeError, ValueError) as exc:
        raise ContractError(f"invalid weight {value!r}") from exc
    if not math.isfinite(x):
        raise ContractError("weight must be finite")
    unit = str(unit).upper().strip()
    if unit == "PERCENT":
        x /= 100.0
    elif unit != "FRACTION":
        raise ContractError(f"unsupported weight unit {unit!r}")
    if x < -1.0 or x > 1.0:
        raise ContractError(f"normalized weight outside [-1,1]: {x}")
    return x


def _security_row(row: dict[str, Any], *, weight_unit: str) -> dict[str, Any]:
    security_id = str(row.get("security_id") or "").strip().upper()
    if not security_id:
        raise ContractError("security_id required")
    instrument = str(row.get("instrument") or "UNKNOWN").strip().upper()
    weight = normalize_weight(row.get("weight"), weight_unit)
    if instrument in {"COMMON", "ADR", "ETF"} and weight < 0:
        raise ContractError("long equity holdings cannot have negative weight")
    return {
        "security_id": security_id,
        "issuer_id": str(row.get("issuer_id") or security_id).strip(),
        "ticker": str(row.get("ticker") or security_id).strip().upper(),
        "instrument": instrument,
        "identity_verified": bool(row.get("identity_verified", False)),
        "weight": weight,
        "quantity": None if row.get("quantity") in (None, "") else float(row["quantity"]),
    }


def normalize_snapshot(raw: dict[str, Any]) -> dict[str, Any]:
    fund_id = str(raw.get("fund_id") or "").strip().upper()
    if not fund_id:
        raise ContractError("fund_id required")
    coverage_kind = str(raw.get("coverage_kind") or "").strip().upper()
    if coverage_kind not in ALLOWED_COVERAGE:
        raise ContractError(f"unsupported coverage_kind {coverage_kind!r}")
    weight_unit = str(raw.get("weight_unit") or "").strip().upper()
    rows = [_security_row(r, weight_unit=weight_unit) for r in raw.get("rows", [])]
    if not rows:
        raise ContractError("snapshot rows required")
    seen = set()
    for row in rows:
        if row["security_id"] in seen:
            raise ContractError(f"duplicate security_id in snapshot: {row['security_id']}")
        seen.add(row["security_id"])
    expected = raw.get("expected_unique_rows")
    expected_ok = expected in (None, "") or int(expected) == len(rows)
    identity_ok = all(r["identity_verified"] for r in rows if r["instrument"] in {"COMMON", "ADR", "ETF"})
    weight_sum = sum(r["weight"] for r in rows)
    tolerance = float(raw.get("weight_sum_tolerance", 0.02))
    if not (0 <= tolerance <= 0.02):
        raise ContractError("weight_sum_tolerance must be in [0,0.02]")
    weight_sum_ok = abs(weight_sum - 1.0) <= tolerance
    complete = coverage_kind == FULL_COVERAGE and expected_ok and identity_ok and weight_sum_ok
    published_at = raw.get("published_at")
    observed_at = raw.get("observed_at")
    validated_at = raw.get("validated_at") or observed_at
    if not observed_at or not validated_at:
        raise ContractError("observed_at and validated_at required")
    available_at = max(utc(observed_at), utc(validated_at), utc(published_at) if published_at else utc(observed_at))
    snapshot = {
        "schema": "etf-snapshot-v2",
        "fund_id": fund_id,
        "source_id": str(raw.get("source_id") or "").strip(),
        "portfolio_scope": str(raw.get("portfolio_scope") or "UNKNOWN").strip().upper(),
        "revision_id": str(raw.get("revision_id") or "0"),
        "revision_number": int(raw.get("revision_number", 0)),
        "coverage_kind": coverage_kind,
        "holdings_as_of": str(raw.get("holdings_as_of") or ""),
        "published_at": published_at,
        "observed_at": observed_at,
        "validated_at": validated_at,
        "available_at": available_at.isoformat(),
        "complete": complete,
        "weight_sum": weight_sum,
        "expected_unique_rows_ok": expected_ok,
        "identity_ok": identity_ok,
        "weight_sum_ok": weight_sum_ok,
        "rows": sorted(rows, key=lambda r: r["security_id"]),
    }
    snapshot["snapshot_sha256"] = digest({k: v for k, v in snapshot.items() if k != "snapshot_sha256"})
    return snapshot


def latest_asof_by_fund(snapshots: Iterable[dict[str, Any]], decision_at: str) -> dict[str, dict[str, Any]]:
    cutoff = utc(decision_at)
    latest: dict[str, dict[str, Any]] = {}
    for snap in snapshots:
        available = utc(snap["available_at"])
        if available > cutoff:
            continue
        fund = str(snap["fund_id"]).upper()
        current = latest.get(fund)
        key = (available, int(snap.get("revision_number", 0)), str(snap.get("snapshot_sha256", "")))
        current_key = None if current is None else (utc(current["available_at"]), int(current.get("revision_number", 0)), str(current.get("snapshot_sha256", "")))
        if current is None or key > current_key:
            latest[fund] = snap
    return latest


def _rows_by_security(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(r["security_id"]).upper(): r for r in snapshot.get("rows", [])}


def build_holding_events(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[dict[str, Any]]:
    cur = _rows_by_security(current)
    prev = _rows_by_security(previous) if previous else {}
    fund_id = current["fund_id"]
    events = []
    for security_id in sorted(set(cur) | set(prev)):
        c = cur.get(security_id)
        p = prev.get(security_id)
        if previous is None:
            event_type = "INITIAL"
        elif c is not None and p is None:
            event_type = "INCLUSION" if current.get("complete") and previous.get("complete") else "PRESENCE_OBSERVED"
        elif c is None and p is not None:
            event_type = "REMOVAL" if current.get("complete") and previous.get("complete") else "ABSENCE_UNCONFIRMED"
        else:
            delta = float(c["weight"]) - float(p["weight"])
            event_type = "WEIGHT_INCREASE" if delta > 0.0025 else "WEIGHT_DECREASE" if delta < -0.0025 else "UNCHANGED"
        weight = 0.0 if c is None else float(c["weight"])
        previous_weight = 0.0 if p is None else float(p["weight"])
        events.append({
            "event_id": f"etf:{fund_id}:{current['snapshot_sha256'][:12]}:{security_id}",
            "fund_id": fund_id,
            "security_id": security_id,
            "event_type": event_type,
            "weight": weight,
            "previous_weight": previous_weight,
            "weight_delta": weight - previous_weight,
            "available_at": current["available_at"],
            "trade_proven": False,
            "buy_proven": False,
            "sell_proven": False,
        })
    return events


def _series_map(rows: Iterable[dict[str, Any]], key: str) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in rows:
        ident = str(row.get(key) or "").strip().upper()
        session = str(row.get("session") or "")
        value = float(row.get("total_return_index"))
        if ident and session and math.isfinite(value) and value > 0:
            out[ident].append((session, value))
    for ident in out:
        out[ident].sort(key=lambda x: x[0])
    return out


def compute_leadership(price_rows: Iterable[dict[str, Any]], benchmark_id: str) -> list[dict[str, Any]]:
    series = _series_map(price_rows, "security_id")
    benchmark_id = benchmark_id.upper()
    benchmark = series.get(benchmark_id)
    if not benchmark:
        raise ContractError(f"benchmark series missing: {benchmark_id}")
    benchmark_values = {s: v for s, v in benchmark}
    out = []
    for security_id, points in series.items():
        if security_id == benchmark_id:
            continue
        values = {s: v for s, v in points}
        common = sorted(set(values) & set(benchmark_values))
        if len(common) < 2:
            continue
        row: dict[str, Any] = {"security_id": security_id, "benchmark_id": benchmark_id, "latest_session": common[-1]}
        for h in HORIZONS:
            if len(common) <= h:
                row[f"return_{h}"] = None
                row[f"rs_log_{h}"] = None
                continue
            start = common[-1 - h]
            end = common[-1]
            row[f"return_{h}"] = values[end] / values[start] - 1.0
            row[f"rs_log_{h}"] = math.log(values[end] / values[start]) - math.log(benchmark_values[end] / benchmark_values[start])
        out.append(row)
    return sorted(out, key=lambda r: r["security_id"])


def discover_terms(documents: Iterable[dict[str, Any]], *, max_terms: int = 30) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    sources: dict[str, set[str]] = defaultdict(set)
    seen_docs = set()
    stop = {"the", "and", "for", "with", "from", "this", "that", "will", "into", "after", "about", "market", "company"}
    for doc in documents:
        doc_id = str(doc.get("document_id") or digest([doc.get("url"), doc.get("title")]))
        if doc_id in seen_docs:
            continue
        seen_docs.add(doc_id)
        text = f"{doc.get('title','')} {doc.get('summary','')}".lower()
        tokens = [t for t in re.findall(r"[a-z0-9][a-z0-9+-]{2,}", text) if t not in stop]
        source_group = str(doc.get("source_group") or doc.get("source_id") or "unknown")
        for n in (1, 2, 3):
            for i in range(0, len(tokens) - n + 1):
                term = " ".join(tokens[i:i+n])
                counts[term] += 1
                sources[term].add(source_group)
    ranked = sorted(counts, key=lambda t: (len(sources[t]), counts[t], len(t)), reverse=True)
    return [{"term": t, "document_count": counts[t], "independent_source_groups": len(sources[t])} for t in ranked[:max_terms]]


def resolve_memberships(events: Iterable[dict[str, Any]], decision_at: str) -> dict[str, dict[str, Any]]:
    cutoff = utc(decision_at)
    ordered = sorted(events, key=lambda e: (utc(e["effective_at"]), utc(e.get("observed_at") or e["effective_at"]), str(e["event_id"])))
    state = {}
    for event in ordered:
        if utc(event["effective_at"]) > cutoff or not bool(event.get("reviewed", False)):
            continue
        security_id = str(event["security_id"]).upper()
        action = str(event["action"]).upper()
        if action == "LINK":
            state[security_id] = {
                "security_id": security_id,
                "theme_id": str(event["theme_id"]),
                "role": str(event.get("role") or "INDIRECT").upper(),
                "relevance": float(event.get("relevance", 0.0)),
                "membership_event_id": str(event["event_id"]),
            }
        elif action == "UNLINK":
            state.pop(security_id, None)
        else:
            raise ContractError(f"unsupported membership action: {action}")
    return state


def compose_universe(base_universe: Iterable[str], securities: Iterable[dict[str, Any]], memberships: dict[str, dict[str, Any]]) -> dict[str, Any]:
    base = sorted({str(x).upper() for x in base_universe if str(x).strip()})
    if not base:
        raise ContractError("base_universe cannot be empty")
    registry = {str(r["security_id"]).upper(): r for r in securities}
    additions = []
    excluded = []
    for security_id in sorted(memberships):
        if security_id in base:
            continue
        row = registry.get(security_id)
        if not row:
            excluded.append({"security_id": security_id, "reason": "SECURITY_REGISTRY_MISSING"})
            continue
        instrument = str(row.get("instrument") or "").upper()
        exchange = str(row.get("exchange") or "").upper()
        country = str(row.get("listing_country") or "").upper()
        if not bool(row.get("identity_verified", False)):
            reason = "IDENTITY_UNVERIFIED"
        elif country != "US":
            reason = "NON_US_LISTING"
        elif instrument not in ELIGIBLE_INSTRUMENTS:
            reason = "INELIGIBLE_INSTRUMENT"
        elif exchange not in ELIGIBLE_EXCHANGES:
            reason = "INELIGIBLE_EXCHANGE"
        elif not bool(row.get("research_eligible", False)):
            reason = "RESEARCH_INELIGIBLE"
        else:
            additions.append(security_id)
            continue
        excluded.append({"security_id": security_id, "reason": reason})
    proposal = sorted(set(base) | set(additions))
    return {
        "base_count": len(base),
        "addition_count": len(additions),
        "proposal_count": len(proposal),
        "base_universe_sha256": digest(base),
        "proposal_sha256": digest(proposal),
        "additions": additions,
        "excluded": excluded,
        "research_universe_proposal": proposal,
    }


def run_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != SCHEMA_VERSION:
        raise ContractError(f"schema must be {SCHEMA_VERSION}")
    decision_at = str(payload["decision_at"])
    snapshots = [normalize_snapshot(s) if s.get("schema") != "etf-snapshot-v2" else s for s in payload.get("etf_snapshots", [])]
    latest = latest_asof_by_fund(snapshots, decision_at)
    by_fund: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snap in snapshots:
        if utc(snap["available_at"]) <= utc(decision_at):
            by_fund[snap["fund_id"]].append(snap)
    events = []
    for fund_snaps in by_fund.values():
        fund_snaps.sort(key=lambda s: (utc(s["available_at"]), int(s.get("revision_number", 0))))
        previous = None
        for snap in fund_snaps:
            events.extend(build_holding_events(previous, snap))
            previous = snap
    memberships = resolve_memberships(payload.get("membership_events", []), decision_at)
    universe = compose_universe(payload["base_universe"], payload.get("securities", []), memberships)
    leadership = compute_leadership(payload.get("prices", []), str(payload["benchmark_id"])) if payload.get("prices") else []
    terms = discover_terms(payload.get("documents", []))
    summary = {
        "schema": "theme-etf-runtime-result-v1",
        "decision_at": decision_at,
        "research_only": True,
        "production_activation_allowed": False,
        "orders_generated": False,
        "target_book_changed": False,
        "latest_fund_count": len(latest),
        "holding_event_count": len(events),
        "active_membership_count": len(memberships),
        "leadership_row_count": len(leadership),
        "news_term_count": len(terms),
        "universe": universe,
    }
    result = {
        "summary": summary,
        "latest_snapshots": latest,
        "holding_events": events,
        "active_memberships": memberships,
        "leadership": leadership,
        "news_terms": terms,
    }
    result["result_sha256"] = digest(result)
    return result

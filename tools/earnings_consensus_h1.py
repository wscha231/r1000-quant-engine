"""Forward-only source semantics. No ranking, portfolio or H2 authority."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from typing import Any, Iterable

SCHEMA_VERSION = "earnings-consensus-source-v2"
IDENTITY_FIELDS = ("issuer_id", "security_id", "metric", "fiscal_period_end",
                   "period_type", "accounting_basis", "currency", "share_or_ADR_unit")


def optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def pct_change(current: Any, previous: Any) -> float | None:
    current, previous = optional_float(current), optional_float(previous)
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous)


def iso_utc(value: Any) -> str | None:
    """Exact, timezone-aware timestamps only; never infer intraday publication."""
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        return None


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def text_value(value: Any) -> str | None:
    if value is None or str(value).strip().lower() in {"", "none", "nan", "unknown", "<na>"}:
        return None
    return str(value).strip()


def period_end(row: dict) -> str | None:
    value = row.get("fiscal_period_end") or row.get("period") or row.get("fiscalDateEnding") or row.get("date")
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        return None


def estimate_rows(payload: Any) -> list[dict]:
    data = payload.get("data", payload.get("estimate", [])) if isinstance(payload, dict) else payload
    return sorted([dict(x) for x in data if isinstance(x, dict)],
                  key=lambda x: period_end(x) or "" ) if isinstance(data, list) else []


def canonical_identity(row: dict, metric: str) -> dict:
    return {"issuer_id": text_value(row.get("issuer_id")),
            "security_id": text_value(row.get("security_id")), "metric": metric,
            "fiscal_period_end": period_end(row),
            "period_type": text_value(row.get("period_type")),
            "accounting_basis": text_value(row.get("accounting_basis")),
            "currency": text_value(row.get("currency")),
            "share_or_ADR_unit": text_value(row.get("share_or_ADR_unit"))}


def identity_complete(identity: dict) -> bool:
    return all(text_value(identity.get(k)) is not None for k in IDENTITY_FIELDS)


def availability(row: dict) -> str | None:
    if row.get("publication_status") == "UNKNOWN_PUBLICATION_PRECISION":
        return None
    required = [iso_utc(row.get(k)) for k in ("observed_at", "first_seen_at", "collected_at", "strategy_available_at")]
    if not all(required):
        return None
    publication = iso_utc(row.get("provider_published_at"))
    times = required + ([publication] if publication else [])
    return max(times, key=lambda t: datetime.fromisoformat(t.replace("Z", "+00:00")))


def consensus_records(row: dict) -> list[dict]:
    if row.get("source_contract") != SCHEMA_VERSION:
        return []
    try:
        records = json.loads(row.get("consensus_observations_json") or "[]")
        if (not isinstance(records, list) or not all(isinstance(r, dict) for r in records)
                or digest(records) != row.get("source_payload_sha256")):
            return []
        return records
    except (TypeError, ValueError):
        return []


def same_period_revision(current: dict, prior: dict, prefix: str = "eps_fy1") -> float | None:
    """Compare exact economic identities and providers, independent of FY labels."""
    target = current.get(prefix + "_identity")
    if isinstance(target, str):
        target = json.loads(target)
    if not isinstance(target, dict) or not identity_complete(target):
        return None
    if current.get("identity_status") == "AMBIGUOUS" or prior.get("identity_status") == "AMBIGUOUS":
        return None
    if current.get("fetch_source") != prior.get("fetch_source"):
        return None
    now, before = availability(current), availability(prior)
    if not now or not before or datetime.fromisoformat(before) >= datetime.fromisoformat(now):
        return None
    matches = [r for r in consensus_records(prior) if r.get("identity") == target]
    current_matches = [r for r in consensus_records(current) if r.get("identity") == target]
    if (len(matches) != 1 or len(current_matches) != 1
            or optional_float(current.get("est_" + prefix)) != optional_float(current_matches[0].get("value"))):
        return None
    return pct_change(current_matches[0].get("value"), matches[0].get("value"))


def build_snapshot(ticker: str, *, eps_payload: Any, revenue_payload: Any,
                   recommendation_payload: Any, observed_at: str, collected_at: str,
                   fetch_source: str, first_seen_at: str | None = None,
                   provider_published_at: str | None = None,
                   eps_estimate_access: bool = True, revenue_estimate_access: bool = True) -> dict:
    observed, collected = iso_utc(observed_at), iso_utc(collected_at)
    first_seen = iso_utc(first_seen_at) if first_seen_at is not None else observed
    if not observed or not collected or not first_seen:
        raise ValueError("exact_timezone_aware_observation_times_required")
    row = {"source_contract": SCHEMA_VERSION, "ticker": ticker.upper().strip(),
           "fetch_source": fetch_source, "observed_at": observed, "collected_at": collected,
           "first_seen_at": first_seen, "provider_published_at": iso_utc(provider_published_at),
           "strategy_available_at": collected, "h2_eligible": False,
           "eps_estimate_access": bool(eps_estimate_access),
           "revenue_estimate_access": bool(revenue_estimate_access),
           "vendor_estimate_access": bool(eps_estimate_access and revenue_estimate_access)}
    records = []
    analyst_counts = []
    publications = []
    raw_publications = []
    if provider_published_at is not None:
        raw_publications.append(str(provider_published_at))
    for metric, payload, access in (("eps", eps_payload, eps_estimate_access),
                                    ("rev", revenue_payload, revenue_estimate_access)):
        items = estimate_rows(payload)
        for item in items:
            identity = canonical_identity(item, "EPS" if metric == "eps" else "REVENUE")
            value = optional_float(item.get("avg")) if access else None
            published_raw = item.get("provider_published_at")
            if published_raw is not None:
                raw_publications.append(str(published_raw))
            published = iso_utc(published_raw)
            if published:
                publications.append(published)
            records.append({"identity": identity, "value": value,
                            "high": optional_float(item.get("high")), "low": optional_float(item.get("low")),
                            "provider_version": text_value(item.get("provider_version")),
                            "provider_published_at": published,
                            "identity_status": "VERIFIED" if identity_complete(identity) else "UNKNOWN_IDENTITY",
                            "value_status": "UNSUPPORTED" if not access else "MISSING" if value is None else "EXPLICIT_ZERO" if value == 0 else "OBSERVED"})
        # Preserve every canonical record, but FY views require a dated annual
        # period that has not ended at observation/collection. A pending prior
        # period can still be used by the frozen-consensus helper, not as FY1.
        view_date = max(observed[:10], collected[:10])
        forward = [item for item in items if period_end(item) is not None
                   and period_end(item) >= view_date and item.get("period_type") == "ANNUAL"]
        for index in range(2):
            item = forward[index] if index < len(forward) else {}
            prefix = f"{metric}_fy{index+1}"
            identity = canonical_identity(item, "EPS" if metric == "eps" else "REVENUE")
            value = optional_float(item.get("avg")) if access else None
            row["est_" + prefix] = value
            row[prefix + "_period_end"] = identity["fiscal_period_end"]
            row[prefix + "_identity"] = json.dumps(identity, sort_keys=True)
            row[prefix + "_status"] = "UNSUPPORTED" if not access else "NO_FORWARD_VIEW" if not item and items else "NO_COVERAGE" if not item else "MISSING" if value is None else "EXPLICIT_ZERO" if value == 0 else "OBSERVED"
            count = optional_float(item.get("numberAnalysts"))
            if count is not None and count >= 0 and count.is_integer():
                analyst_counts.append(int(count))
    # A duplicate fiscal identity is ambiguous rather than provider order winning.
    keys = [json.dumps(r["identity"], sort_keys=True) for r in records]
    row["identity_status"] = "AMBIGUOUS" if len(keys) != len(set(keys)) else "VERIFIED" if records and all(identity_complete(r["identity"]) for r in records) else "UNKNOWN_IDENTITY"
    if publications:
        row["provider_published_at"] = max(publications + ([row["provider_published_at"]] if row["provider_published_at"] else []), key=datetime.fromisoformat)
    row["provider_published_at_raw"] = json.dumps(sorted(set(raw_publications)))
    row["publication_status"] = "UNKNOWN_PUBLICATION_PRECISION" if any(iso_utc(t) is None for t in raw_publications) else "EXACT" if raw_publications else "NOT_PROVIDED"
    row["strategy_available_at"] = availability(row)
    row["available_from"] = row["strategy_available_at"]
    row["as_of_date"] = collected[:10]
    row["consensus_observations_json"] = json.dumps(records, sort_keys=True, allow_nan=False)
    row["source_payload_sha256"] = digest(records)
    row["has_forward_estimate"] = int(any(row.get("est_"+prefix) is not None for prefix in ("eps_fy1", "eps_fy2", "rev_fy1", "rev_fy2")))
    row["n_analysts"] = max(analyst_counts) if analyst_counts else None
    eps_items = [item for item in estimate_rows(eps_payload) if period_end(item) is not None
                 and period_end(item) >= max(observed[:10], collected[:10]) and item.get("period_type") == "ANNUAL"]
    row["est_dispersion"] = pct_change(eps_items[0].get("high"), eps_items[0].get("low")) if eps_items and eps_estimate_access else None
    recs = recommendation_payload if isinstance(recommendation_payload, list) else []
    recs = sorted([r for r in recs if isinstance(r, dict)], key=lambda r: str(r.get("period", "")))
    rec = recs[-1] if recs else {}
    counts = [optional_float(rec.get(k)) for k in ("strongBuy", "buy", "sell", "strongSell")]
    valid = all(c is not None and c >= 0 and c.is_integer() for c in counts)
    bull, bear = (counts[0] + counts[1], counts[2] + counts[3]) if valid else (None, None)
    row.update(recommendation_period=rec.get("period"), recommendation_bull_count=bull,
               recommendation_bear_count=bear,
               analyst_recommendation_balance=(bull-bear)/(bull+bear) if valid and bull+bear else None,
               est_eps_revision_breadth=None, est_eps_revision_breadth_status="UNKNOWN_NO_ANALYST_REVISION_SOURCE",
               earnings_surprise_last=None, surprise_streak=None,
               earnings_surprise_status="UNKNOWN_NO_FROZEN_PRE_EVENT_CONSENSUS", causal_event_id=None,
               causal_event_status="UNKNOWN_NO_VERIFIED_EVENT_LINK")
    row["snapshot_version_id"] = digest(row)
    return row


def frozen_pre_event_consensus(snapshots: Iterable[dict], *, event_available_at: Any,
                                identity: dict, fetch_source: str) -> dict | None:
    cutoff = iso_utc(event_available_at)
    if not cutoff or not identity_complete(identity):
        return None
    def attributed(row):
        try:
            attempted = json.loads(row.get("attempted_estimate_providers_json") or "[]")
        except (TypeError, ValueError):
            attempted = []
        return row.get("fetch_source") == fetch_source or fetch_source in attempted
    snapshots = [r for r in snapshots if attributed(r)]
    # Discover the security's tickers only from information available pre-event.
    eligible = [r for r in snapshots if availability(r)
                and datetime.fromisoformat(availability(r)) < datetime.fromisoformat(cutoff)]
    tickers = {r.get("ticker") for r in eligible
               if any(v.get("identity") == identity for v in consensus_records(r))}
    candidates = [r for r in eligible if r.get("ticker") in tickers]
    if not candidates:
        return None
    # Unknown publication timing in a newer observation cannot revive an old value.
    for row in snapshots:
        known_times = [iso_utc(row.get(k)) for k in ("observed_at", "first_seen_at", "collected_at",
                                                    "strategy_available_at", "provider_published_at")]
        known_times = [t for t in known_times if t]
        if (row.get("ticker") in tickers and not availability(row) and known_times
                and max(map(datetime.fromisoformat, known_times)) < datetime.fromisoformat(cutoff)):
            return None
    latest_time = max(datetime.fromisoformat(availability(r)) for r in candidates)
    latest = [r for r in candidates if datetime.fromisoformat(availability(r)) == latest_time]
    if len({r.get("source_payload_sha256") for r in latest}) != 1:
        return None
    row = sorted(latest, key=lambda r: r["snapshot_version_id"])[0]
    matches = [r for r in consensus_records(row) if r.get("identity") == identity]
    if row.get("fetch_source") != fetch_source or row.get("identity_status") == "AMBIGUOUS" or len(matches) != 1 or optional_float(matches[0].get("value")) is None:
        return None
    return {"identity": identity, "value": matches[0]["value"],
            "strategy_available_at": availability(row), "snapshot_version_id": row["snapshot_version_id"],
            "source_payload_sha256": row["source_payload_sha256"], "fetch_source": fetch_source}


def earnings_surprise(actual: Any, frozen: dict | None, *, identity: dict,
                      announcement_at: Any) -> float | None:
    cutoff = iso_utc(announcement_at)
    if (not frozen or not cutoff or frozen.get("identity") != identity
            or not identity_complete(identity) or not frozen.get("snapshot_version_id")
            or not frozen.get("source_payload_sha256")
            or not iso_utc(frozen.get("strategy_available_at"))
            or datetime.fromisoformat(frozen["strategy_available_at"]) >= datetime.fromisoformat(cutoff)):
        return None
    return pct_change(actual, frozen.get("value"))


def causal_event_id(issuer_id: str, fiscal_period_end: str, announcement_at: Any) -> str | None:
    timestamp = iso_utc(announcement_at)
    issuer, period = text_value(issuer_id), period_end({"period": fiscal_period_end})
    if not issuer or not timestamp or not period:
        return None
    return digest({"issuer_id": issuer, "period": period, "announcement_at": timestamp})


def dedupe_causal_events(evidence: Iterable[dict]) -> list[dict]:
    """Group reactions under their verified common event; unknown links cannot count."""
    groups: dict[str, dict] = {}
    for row in evidence:
        key = row.get("causal_event_id")
        if not key or row.get("causal_link_verified") is not True:
            continue
        group = groups.setdefault(key, {"causal_event_id": key, "independent_event_count": 1, "reactions": []})
        if row not in group["reactions"]:
            group["reactions"].append(dict(row))
    for group in groups.values():
        group["reactions"].sort(key=lambda row: json.dumps(row, sort_keys=True))
    return [groups[key] for key in sorted(groups)]

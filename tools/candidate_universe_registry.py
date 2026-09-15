"""Research-only candidate universe membership/reason registry.

This module separates *why a security is monitored* from whether it should be
bought. Base R1000/ADR membership, positive discovery events and negative/risk
watch events are distinct reasons. Data errors never become exits.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

SCHEMA_VERSION = "candidate-universe-reasons-v1"
_ALLOWED_POLARITY = {"BASE", "CANDIDATE", "RISK_WATCH", "MIXED_REVIEW", "MONITOR"}
_ALLOWED_STATUS = {"ACTIVE", "EXPIRED", "BLOCKED", "UNKNOWN"}
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class UniverseIntegrityError(ValueError):
    pass


def _ts(value: Any, *, field: str) -> pd.Timestamp:
    ts = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(ts):
        raise UniverseIntegrityError(f"invalid_timestamp:{field}")
    return ts


def _ticker(value: Any) -> str:
    t = str(value or "").strip().upper().replace("/", ".")
    if not _TICKER_RE.fullmatch(t):
        raise UniverseIntegrityError(f"invalid_ticker:{t or 'EMPTY'}")
    return t


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class MembershipReason:
    ticker: str
    reason_type: str
    source_kind: str
    polarity: str
    status: str
    first_seen_at: str
    last_observed_at: str
    valid_until: str
    source_event_id: str
    source_hash: str
    source_quality: str
    security_type: str = "EQUITY"
    notes: str = ""

    def row(self) -> dict[str, Any]:
        return asdict(self)


def base_reasons(r1000: Iterable[str], adr: Iterable[str], *, as_of: str, source_hash: str = "") -> list[MembershipReason]:
    cutoff = _ts(as_of, field="as_of")
    stamp = cutoff.isoformat()
    rows: list[MembershipReason] = []
    rset = {_ticker(t) for t in r1000}
    aset = {_ticker(t) for t in adr}
    for t in sorted(rset):
        rows.append(MembershipReason(t, "R1000_BASE", "R1000", "BASE", "ACTIVE", stamp, stamp, "", f"R1000:{t}", source_hash, "BASE_SOURCE"))
    for t in sorted(aset):
        rows.append(MembershipReason(t, "ADR_BASE", "ADR", "BASE", "ACTIVE", stamp, stamp, "", f"ADR:{t}", source_hash, "BASE_SOURCE"))
    return rows


def validate_13f_source(summary: Mapping[str, Any]) -> None:
    if summary.get("research_only") is not True:
        raise UniverseIntegrityError("13f_summary_not_research_only")
    if summary.get("security_identity_preserved") is not True:
        raise UniverseIntegrityError("13f_security_identity_not_verified")
    if summary.get("stock_signal_scope") != "CASH_EQUITY_ONLY_OPTIONS_AND_PRN_EXCLUDED_FROM_STOCK_SCORE":
        raise UniverseIntegrityError("13f_stock_signal_scope_unverified")
    if summary.get("score_total_changed") not in (False, None):
        raise UniverseIntegrityError("13f_summary_claims_production_score_change")


def reasons_from_13f(signals: pd.DataFrame, summary: Mapping[str, Any], *, as_of: str, source_hash: str = "", ttl_days: int = 210) -> list[MembershipReason]:
    """Convert H1-validated stock-level 13F changes into research reasons.

    H2 manager skill is not assumed. These rows expand research discovery only.
    A negative-only event becomes RISK_WATCH, never a positive candidate reason.
    """
    validate_13f_source(summary)
    cutoff = _ts(as_of, field="as_of")
    required = {
        "ticker", "latest_available_from", "sec_13f_buying_manager_count",
        "sec_13f_selling_manager_count", "sec_13f_new_position_manager_count",
        "sec_13f_value_delta_usd",
    }
    missing = required - set(signals.columns)
    if missing:
        raise UniverseIntegrityError("13f_required_columns_missing:" + ",".join(sorted(missing)))
    out: list[MembershipReason] = []
    seen_ids: set[str] = set()
    for _, row in signals.iterrows():
        t = _ticker(row["ticker"])
        observed = _ts(row["latest_available_from"], field="latest_available_from")
        if observed > cutoff:
            raise UniverseIntegrityError("13f_future_event")
        buyers = int(pd.to_numeric(row["sec_13f_buying_manager_count"], errors="raise"))
        sellers = int(pd.to_numeric(row["sec_13f_selling_manager_count"], errors="raise"))
        new_count = int(pd.to_numeric(row["sec_13f_new_position_manager_count"], errors="raise"))
        delta = float(pd.to_numeric(row["sec_13f_value_delta_usd"], errors="raise"))
        if any(x < 0 for x in (buyers, sellers, new_count)) or not math.isfinite(delta):
            raise UniverseIntegrityError("13f_invalid_event_numeric")
        if buyers == 0 and sellers == 0 and new_count == 0 and delta == 0:
            continue
        if (buyers > 0 or new_count > 0) and sellers == 0:
            polarity = "CANDIDATE"
        elif sellers > 0 and buyers == 0 and new_count == 0:
            polarity = "RISK_WATCH"
        else:
            polarity = "MIXED_REVIEW"
        valid_until = observed + pd.Timedelta(days=int(ttl_days))
        status = "ACTIVE" if valid_until >= cutoff else "EXPIRED"
        event_id = f"13F:{t}:{observed.isoformat()}:{buyers}:{sellers}:{new_count}:{delta:.8g}"
        event_hash = hashlib.sha256(event_id.encode()).hexdigest()
        if event_hash in seen_ids:
            raise UniverseIntegrityError("duplicate_13f_event_identity")
        seen_ids.add(event_hash)
        out.append(MembershipReason(
            t, "SEC_13F_EVENT_RESEARCH", "SEC_13F", polarity, status,
            observed.isoformat(), observed.isoformat(), valid_until.isoformat(),
            event_hash, source_hash, "H1_VERIFIED_H2_MANAGER_SKILL_PENDING", "EQUITY",
            f"buyers={buyers};sellers={sellers};new={new_count};value_delta={delta:.8g}",
        ))
    return out


def reasons_from_form4(signals: pd.DataFrame, validation: Mapping[str, Any], *, as_of: str, source_hash: str = "", ttl_days: int = 90) -> list[MembershipReason]:
    """Accept Form4 universe expansion only after a dedicated H1 validation receipt.

    Current legacy Form4 outputs must not be promoted merely because a CSV exists.
    """
    if validation.get("eligible_for_candidate_universe") is not True or validation.get("status") != "VERIFIED_H1":
        raise UniverseIntegrityError("form4_source_not_h1_verified")
    cutoff = _ts(as_of, field="as_of")
    required = {"ticker", "latest_available_from", "insider_buy_value", "insider_sale_value", "sec_form4_sale_pressure_score"}
    missing = required - set(signals.columns)
    if missing:
        raise UniverseIntegrityError("form4_required_columns_missing:" + ",".join(sorted(missing)))
    out: list[MembershipReason] = []
    for _, row in signals.iterrows():
        t = _ticker(row["ticker"])
        observed = _ts(row["latest_available_from"], field="latest_available_from")
        if observed > cutoff:
            raise UniverseIntegrityError("form4_future_event")
        buy = float(pd.to_numeric(row["insider_buy_value"], errors="raise"))
        sale = float(pd.to_numeric(row["insider_sale_value"], errors="raise"))
        pressure = float(pd.to_numeric(row["sec_form4_sale_pressure_score"], errors="raise"))
        if min(buy, sale, pressure) < 0 or not all(math.isfinite(v) for v in (buy, sale, pressure)):
            raise UniverseIntegrityError("form4_invalid_event_numeric")
        if buy <= 0 and sale <= 0:
            continue
        polarity = "CANDIDATE" if buy > 0 and sale == 0 else "RISK_WATCH" if sale > 0 and buy == 0 else "MIXED_REVIEW"
        valid_until = observed + pd.Timedelta(days=int(ttl_days))
        status = "ACTIVE" if valid_until >= cutoff else "EXPIRED"
        eid = hashlib.sha256(f"FORM4:{t}:{observed.isoformat()}:{buy:.8g}:{sale:.8g}:{pressure:.8g}".encode()).hexdigest()
        out.append(MembershipReason(t, "FORM4_EVENT", "FORM4", polarity, status,
                                    observed.isoformat(), observed.isoformat(), valid_until.isoformat(),
                                    eid, source_hash, "VERIFIED_H1", "EQUITY",
                                    f"buy_value={buy:.8g};sale_value={sale:.8g};sale_pressure={pressure:.6g}"))
    return out


def aggregate_reasons(reasons: Iterable[MembershipReason], *, as_of: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    cutoff = _ts(as_of, field="as_of")
    rows = [r.row() for r in reasons]
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise UniverseIntegrityError("empty_membership_reasons")
    if frame.duplicated(["ticker", "reason_type", "source_event_id"], keep=False).any():
        raise UniverseIntegrityError("duplicate_membership_reason")
    for col in ("polarity", "status"):
        allowed = _ALLOWED_POLARITY if col == "polarity" else _ALLOWED_STATUS
        if not set(frame[col].astype(str)).issubset(allowed):
            raise UniverseIntegrityError(f"invalid_{col}")
    active = frame[frame["status"].eq("ACTIVE")].copy()
    agg_rows: list[dict[str, Any]] = []
    for ticker, grp in active.groupby("ticker", sort=True):
        reason_types = sorted(set(grp["reason_type"].astype(str)))
        polarities = sorted(set(grp["polarity"].astype(str)))
        has_base = bool(grp["polarity"].eq("BASE").any())
        has_candidate = bool(grp["polarity"].isin(["CANDIDATE", "MIXED_REVIEW"]).any())
        has_risk = bool(grp["polarity"].isin(["RISK_WATCH", "MIXED_REVIEW"]).any())
        agg_rows.append({
            "ticker": ticker,
            "membership_reasons": "|".join(reason_types),
            "polarities": "|".join(polarities),
            "base_member": has_base,
            "event_discovered": bool((~grp["polarity"].eq("BASE")).any()),
            "risk_watch": has_risk,
            "monitor_eligible": True,
            "candidate_scan_eligible": bool(has_base or has_candidate),
            "event_only_risk_watch": bool((not has_base) and has_risk and not has_candidate),
            "as_of": cutoff.isoformat(),
        })
    universe_columns = ["ticker","membership_reasons","polarities","base_member","event_discovered","risk_watch","monitor_eligible","candidate_scan_eligible","event_only_risk_watch","as_of"]
    universe = pd.DataFrame(agg_rows, columns=universe_columns)
    if not universe.empty:
        universe = universe.sort_values("ticker").reset_index(drop=True)
    return frame.sort_values(["ticker", "reason_type", "source_event_id"]).reset_index(drop=True), universe


def build_manifest(reasons: pd.DataFrame, universe: pd.DataFrame, *, as_of: str, source_status: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "schema": SCHEMA_VERSION,
        "as_of": _ts(as_of, field="as_of").isoformat(),
        "research_only": True,
        "automatic_trade_allowed": False,
        "portfolio_target_changed": False,
        "active_manager_roster_changed": False,
        "reason_rows": int(len(reasons)),
        "monitor_tickers": int(universe["monitor_eligible"].sum()),
        "candidate_scan_tickers": int(universe["candidate_scan_eligible"].sum()),
        "event_only_risk_watch_tickers": int(universe["event_only_risk_watch"].sum()),
        "source_status": dict(source_status),
    }
    payload["content_identity"] = hashlib.sha256(
        (reasons.to_csv(index=False) + "\n" + universe.to_csv(index=False)).encode("utf-8")
    ).hexdigest()
    return payload

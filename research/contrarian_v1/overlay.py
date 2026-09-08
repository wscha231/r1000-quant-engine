"""Evidence-gated contrarian exposure proposals. RESEARCH ONLY; no operating hook.

Uses the upstream, contrarian-free baseline and risk ceiling, never a prior
proposal as a fill. All numbers are fractions of NAV. No orders or writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "contrarian-research-v1"
CONFIG = {
    "fear_enter": 20.0, "fear_exit": 35.0,
    "greed_enter": 80.0, "greed_exit": 65.0,
    "confirm_sessions": 2, "fear_tilt": 0.10, "greed_tilt": -0.10,
    "max_step": 0.05, "no_trade_buffer": 0.01,
    "daily_max_age_hours": 96, "positioning_max_age_hours": 240,
}
SENTIMENT = ("positioning_greed_pct", "options_greed_pct", "internals_greed_pct")
FLAGS = (
    "systemic_crisis", "credit_deteriorating", "liquidity_deteriorating",
    "fundamentals_intact", "valuation_attractive", "valuation_stretched",
    "earnings_deteriorating", "breadth_improving", "breadth_deteriorating",
    "volatility_easing", "price_stabilizing",
)
PACKET_KEYS = {
    "schema", "market", "session", "previous_session", "decision_at",
    "baseline_equity", "current_equity", "risk_cap", "eligible_equity_cap",
    "new_buys_allowed", "kill_switch", "baseline_excludes_contrarian",
    "upstream_manifest_sha256", "evidence",
}
EVIDENCE_KEYS = {"value", "observed_at", "available_at", "source", "sha256", "market"}
STATE_KEYS = {
    "market", "session", "zone", "streak", "tilt", "input_hash", "config_hash", "state_hash",
}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def config_hash() -> str:
    return digest({"version": VERSION, "parameters": CONFIG})


def _number(value: Any, name: str, lo: float, hi: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"invalid_number:{name}")
    return float(value)


def _boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"invalid_boolean:{name}")
    return value


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("invalid_timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timezone_required")
    return result.astimezone(timezone.utc)


def _session(value: Any) -> date:
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("invalid_session")
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError("invalid_session")
    return result


def _sha(value: Any) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("invalid_sha256")


def _strict_object(keys: set[str], value: Any, name: str) -> None:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"invalid_schema:{name}")


def historical_percentile(current: float, history: list[float], *,
                          higher_is_greed: bool, min_observations: int = 252) -> float:
    """Midrank against PRIOR observations only; caller must establish PIT/calendar.

    Daily family: normally 756 prior sessions, minimum 252. Weekly positioning:
    normally 156 prior releases, minimum 52. Never forward-fill weeks to invent n.
    This arithmetic helper does not certify upstream observation timestamps.
    """
    _boolean(higher_is_greed, "higher_is_greed")
    if type(min_observations) is not int or min_observations < 2 or len(history) < min_observations:
        raise ValueError("insufficient_history")
    x = _number(current, "current", -1e100, 1e100)
    values = [_number(v, "history", -1e100, 1e100) for v in history]
    rank = 100 * (sum(v < x for v in values) + 0.5 * sum(v == x for v in values)) / len(values)
    return rank if higher_is_greed else 100 - rank


def evaluate(packet: Mapping[str, Any], prior: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a research proposal, NOT target-book authority or a broker command.

    Invalid top-level authority raises. Missing/stale/future evidence abstains.
    Verified canonical risk ceilings/kill-switches always supersede this module.
    The caller must verify source bytes, baseline provenance and exchange sessions;
    syntactically valid hashes alone do NOT establish genuine or PIT-safe evidence.
    """
    _strict_object(PACKET_KEYS, packet, "packet")
    if packet["schema"] != "contrarian-input-v1" or packet["market"] not in ("US", "KR"):
        raise ValueError("unsupported_schema_or_market")
    now = _timestamp(packet["decision_at"])
    session, preceding = _session(packet["session"]), _session(packet["previous_session"])
    if preceding >= session or session > now.date() or (now.date() - session).days > 1:
        raise ValueError("invalid_session_chronology")
    base, current, cap, capacity = [
        _number(packet[k], k, 0, 1)
        for k in ("baseline_equity", "current_equity", "risk_cap", "eligible_equity_cap")
    ]
    buys = _boolean(packet["new_buys_allowed"], "new_buys_allowed")
    kill = _boolean(packet["kill_switch"], "kill_switch")
    clean_base = _boolean(packet["baseline_excludes_contrarian"], "baseline_excludes_contrarian")
    _sha(packet["upstream_manifest_sha256"])
    if not isinstance(packet["evidence"], Mapping) or set(packet["evidence"]) - set(SENTIMENT + FLAGS):
        raise ValueError("unknown_evidence_field")
    # Reject NaN/Infinity anywhere, including prior records.
    input_hash = digest(packet)
    contiguous = False
    tilt, previous_zone, previous_streak = 0.0, "NEUTRAL", 0
    if prior is not None:
        _strict_object(STATE_KEYS, prior, "prior")
        payload = {k: v for k, v in prior.items() if k != "state_hash"}
        if prior["state_hash"] != digest(payload) or prior["config_hash"] != config_hash():
            raise ValueError("prior_identity_mismatch")
        if prior["market"] != packet["market"] or prior["zone"] not in ("NEUTRAL", "FEAR", "GREED"):
            raise ValueError("prior_scope_mismatch")
        prior_date = _session(prior["session"])
        if prior_date > session or type(prior["streak"]) is not int or prior["streak"] < 1:
            raise ValueError("invalid_prior_chronology")
        _sha(prior["input_hash"])
        tilt = _number(prior["tilt"], "prior_tilt", CONFIG["greed_tilt"], CONFIG["fear_tilt"])
        previous_zone, previous_streak = prior["zone"], prior["streak"]
        contiguous = prior_date == preceding
    result = {
        "version": VERSION, "research_only": True, "production_activation_allowed": False,
        "orders_allowed": False, "historical_pit_verified": False,
        "source_authenticity_verified": False, "market": packet["market"],
        "decision_at": packet["decision_at"], "session": packet["session"],
        "source_commit": None,  # supplied by an external, verified execution receipt
        "config_hash": config_hash(), "input_hash": input_hash,
        "upstream_manifest_sha256": packet["upstream_manifest_sha256"],
        "sentiment_score": None, "desired_equity": None, "proposed_equity": None,
        "proposed_cash": None, "reason": [], "state": prior,
        "execution_rule": "RESEARCH_ONLY; after decision, existing next-session execution contract",
    }
    if kill:
        return dict(result, status="DELEGATE_KILL_SWITCH", reason=["upstream_kill_switch"])
    if not clean_base:
        return dict(result, status="BLOCKED_BASELINE", reason=["legacy_or_duplicate_contrarian_tilt"])
    if prior is not None and prior["session"] == packet["session"]:
        if prior["input_hash"] != input_hash:
            raise ValueError("conflicting_same_session_packet")
        return dict(result, status="DUPLICATE_SESSION", reason=["no_second_instruction"])
    values, errors, source_ids = {}, [], []
    for name in SENTIMENT + FLAGS:
        try:
            obs = packet["evidence"][name]
            _strict_object(EVIDENCE_KEYS, obs, name)
            observed, available = _timestamp(obs["observed_at"]), _timestamp(obs["available_at"])
            if observed > available or available > now:
                raise ValueError("future_or_invalid_availability")
            ttl = CONFIG["positioning_max_age_hours"] if name == SENTIMENT[0] else CONFIG["daily_max_age_hours"]
            if now - observed > timedelta(hours=ttl):
                raise ValueError("stale_observation")
            if obs["market"] != packet["market"]:
                raise ValueError("cross_market_evidence")
            if not isinstance(obs["source"], str) or not obs["source"].strip():
                raise ValueError("missing_source")
            _sha(obs["sha256"])
            values[name] = (_number(obs["value"], name, 0, 100) if name in SENTIMENT
                            else _boolean(obs["value"], name))
            if name in SENTIMENT:
                source_ids.append(obs["source"])
        except (ValueError, TypeError, KeyError):
            errors.append(name)
    if len(set(source_ids)) != len(source_ids):
        errors.append("duplicate_sentiment_family_source")
    if errors:
        return dict(result, status="BLOCKED_EVIDENCE", reason=sorted(errors))
    if values["valuation_attractive"] and values["valuation_stretched"]:
        return dict(result, status="BLOCKED_EVIDENCE", reason=["contradictory_valuation"])
    if values["breadth_improving"] and values["breadth_deteriorating"]:
        return dict(result, status="BLOCKED_EVIDENCE", reason=["contradictory_breadth"])
    score = sum(values[k] for k in SENTIMENT) / len(SENTIMENT)
    zone = "FEAR" if score <= CONFIG["fear_enter"] else "GREED" if score >= CONFIG["greed_enter"] else "NEUTRAL"
    if contiguous and previous_zone == "FEAR" and score < CONFIG["fear_exit"]:
        zone = "FEAR"
    elif contiguous and previous_zone == "GREED" and score > CONFIG["greed_exit"]:
        zone = "GREED"
    streak = previous_streak + 1 if contiguous and zone == previous_zone else 1
    reason = []
    risk_bad = any(values[k] for k in ("systemic_crisis", "credit_deteriorating", "liquidity_deteriorating"))
    business_ok = values["fundamentals_intact"] and not values["earnings_deteriorating"]
    stabilizing = sum(values[k] for k in ("breadth_improving", "volatility_easing", "price_stabilizing")) >= 2
    # Do not sell a panic addition merely because fear normalizes. Upstream thesis
    # changes and ceilings still control it. Do not perpetuate a greed cash drag.
    if tilt > 0 and (risk_bad or not business_ok):
        tilt = 0.0
        reason.append("fear_increment_not_reapproved")
    if tilt < 0 and zone != "GREED" and not risk_bad and business_ok and not values["valuation_stretched"]:
        tilt = 0.0
        reason.append("release_greed_reserve")
    if streak >= CONFIG["confirm_sessions"]:
        if zone == "FEAR" and not risk_bad and business_ok and values["valuation_attractive"] and stabilizing:
            if buys:
                tilt = CONFIG["fear_tilt"]
                reason.append("qualified_fear_add")
            else:
                reason.append("upstream_no_buy_veto")
        elif zone == "GREED" and values["valuation_stretched"] and (
                values["breadth_deteriorating"] or values["earnings_deteriorating"]):
            tilt = CONFIG["greed_tilt"]
            reason.append("qualified_greed_trim")
        else:
            reason.append("no_qualified_contrarian_change")
    else:
        reason.append("confirmation_pending")
    if not contiguous and prior is not None:
        reason.append("session_gap_resets_confirmation")
    desired = min(cap, capacity, max(0.0, base + tilt))
    # Retaining filled fear exposure is HOLD authority, not an evergreen buy.
    # Unfilled increments require current qualification and session confirmation.
    # The independent upstream baseline may still rise; never sell a held panic
    # addition solely because sentiment normalized or confirmation was interrupted.
    if tilt > 0 and "qualified_fear_add" not in reason:
        desired = min(desired, max(current, base))
        reason.append("retained_fear_tilt_hold_only")
    if not buys or risk_bad or not business_ok:
        desired = min(desired, current)
        reason.append("no_exposure_increase")
    # Risk/capacity reductions are upstream authority and bypass the soft ladder.
    proposed = min(cap, capacity, max(current - CONFIG["max_step"], min(current + CONFIG["max_step"], desired)))
    if abs(proposed - current) < CONFIG["no_trade_buffer"] and current <= min(cap, capacity):
        proposed = current
        reason.append("no_trade_buffer")
    state = dict(market=packet["market"], session=packet["session"], zone=zone,
                 streak=streak, tilt=tilt, input_hash=input_hash, config_hash=config_hash())
    state["state_hash"] = digest(state)
    return dict(result, status="RESEARCH_PROPOSAL", sentiment_score=round(score, 8),
                desired_equity=round(desired, 8), proposed_equity=round(proposed, 8),
                proposed_cash=round(1 - proposed, 8), reason=reason, state=state)


def _load(path: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result
    def bad_constant(value: str) -> None:
        raise ValueError("nonfinite_json")
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=bad_constant)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json")
    parser.add_argument("--prior-state")
    args = parser.parse_args()
    try:
        result = evaluate(_load(args.input_json), _load(args.prior_state) if args.prior_state else None)
    except (ValueError, TypeError, OSError, KeyError):
        print(json.dumps({"status": "INVALID_INPUT", "research_only": True, "orders_allowed": False}))
        return 2
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
    return 0 if result["status"] in ("RESEARCH_PROPOSAL", "DUPLICATE_SESSION") else 2


if __name__ == "__main__":
    raise SystemExit(main())

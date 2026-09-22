"""Research-only A2 -> A3 -> ER -> A5 lifecycle glue.

No scoring, target, ledger, order, production or scheduler authority.
"""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib, json, math, re
from typing import Any

EVENT_SCHEMA = "a2-event-handoff-v1"
EVENT_REGISTRY_SCHEMA = "a2-event-registry-v1"
CANDIDATE_REGISTRY_SCHEMA = "candidate-registry-v1"
A5_VIEW_SCHEMA = "a5-candidate-input-v1"
A3_RESULT_SCHEMA = "a3-candidate-packet-v1-result"
ER_STATUS = "WALK_FORWARD_VALIDATED"
MAX_BYTES = 64 * 1024 * 1024
TIERS = ("V0", "V1", "V2")
MATERIALITIES = ("NO", "WATCH", "MATERIAL", "CRITICAL")
FRESHNESS = {"CURRENT", "DELTA_REFRESH_DUE", "FULL_REFRESH_DUE", "STALE", "BLOCKED"}
THESIS = {"POSITIVE", "INTACT", "WATCH", "NEGATIVE", "INVALID"}
SECURITY_TYPES = {"COMMON_STOCK", "ADR", "ETF", "CRYPTO_VEHICLE", "COMMODITY_VEHICLE", "OTHER_SECURITY"}
PILLARS = {
    "industry_structure_bottleneck", "moat_durability", "growth_runway_customer_product",
    "profitability_reinvestment_capital_efficiency", "valuation_margin_of_safety",
    "earnings_revision_operating_acceleration", "market_leadership_price_volume_rs",
    "management_governance_capital_allocation", "catalyst_ownership_information_edge",
    "downside_balance_sheet_cycle_regime",
}
MOAT = {
    "qualification_switching_cost", "market_structure_position", "ip_patent_durability",
    "pricing_power", "replacement_difficulty", "next_generation_relevance",
}
FP_KEYS = {
    "source_graph_hash", "fundamental_hash", "methodology_hash", "market_price_hash",
    "earnings_consensus_hash", "regime_hash",
}
ER_HORIZONS = ("1m", "3m", "6m", "12m")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,199}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
ArtifactResolver = Callable[[str, str], bytes]


class CandidateLifecycleError(ValueError):
    pass


def req(ok: bool, code: str) -> None:
    if not ok:
        raise CandidateLifecycleError(code)


def txt(v: Any, code: str, n: int = 2400) -> str:
    req(isinstance(v, str), code); v = v.strip(); req(bool(v) and len(v) <= n, code); return v


def ident(v: Any, code: str) -> str:
    v = txt(v, code, 200); req(bool(_ID.fullmatch(v)), code); return v


def hx(v: Any, code: str) -> str:
    v = txt(v, code, 64).lower(); req(bool(_HEX64.fullmatch(v)), code); return v


def stamp(v: Any, code: str) -> datetime:
    v = txt(v, code, 80); v = v[:-1] + "+00:00" if v.endswith("Z") else v
    try: out = datetime.fromisoformat(v)
    except ValueError as exc: raise CandidateLifecycleError(code) from exc
    req(out.tzinfo is not None and out.utcoffset() is not None, code); return out


def num(v: Any, code: str, lo: float | None = None, hi: float | None = None) -> float:
    req(not isinstance(v, bool) and isinstance(v, (int, float)), code); out = float(v)
    req(math.isfinite(out) and (lo is None or out >= lo) and (hi is None or out <= hi), code); return out


def canonical_sha256(v: Any) -> str:
    raw = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def ref(v: Any, code: str) -> dict[str, str]:
    req(isinstance(v, dict), code)
    return {"artifact_id": ident(v.get("artifact_id"), code+":id"), "sha256": hx(v.get("sha256"), code+":sha"), "available_at": txt(v.get("available_at"), code+":at", 80)}


def resolve(r: dict[str, str], resolver: ArtifactResolver, code: str) -> dict[str, Any]:
    req(callable(resolver), "artifact_resolver_required")
    try: raw = resolver(r["artifact_id"], r["sha256"])
    except Exception as exc: raise CandidateLifecycleError(code+":unavailable") from exc
    req(isinstance(raw, bytes) and 0 < len(raw) <= MAX_BYTES, code+":bytes")
    req(hashlib.sha256(raw).hexdigest() == r["sha256"], code+":hash_mismatch")
    try: out = json.loads(raw)
    except Exception as exc: raise CandidateLifecycleError(code+":json") from exc
    req(isinstance(out, dict), code+":object"); return out


def union(a: list[str], b: list[str]) -> list[str]:
    return list(dict.fromkeys([*a, *b]))


def validate_event(event: Any, cutoff: str) -> dict[str, Any]:
    req(isinstance(event, dict) and event.get("schema") == EVENT_SCHEMA, "event_schema")
    first, verified, cut = stamp(event.get("first_seen_at"), "event_first"), stamp(event.get("verified_at"), "event_verified"), stamp(cutoff, "cutoff")
    req(first <= verified <= cut, "event_time_order")
    tier, materiality = event.get("verification_tier"), event.get("materiality")
    req(tier in TIERS and materiality in MATERIALITIES, "event_tier_or_materiality")
    req(event.get("assessment_score_effect") == 0, "event_score_effect_must_be_zero")
    assets = [ident(x, "event_asset") for x in event.get("asset_ids", [])]
    req(len(assets) == len(set(assets)), "event_duplicate_asset")
    theme = event.get("theme_id"); theme = None if theme is None else ident(theme, "event_theme")
    req(bool(assets) or theme is not None, "event_subject_required")
    pillars, moat = event.get("affected_methodology", []), event.get("affected_moat", [])
    req(isinstance(pillars, list) and len(pillars) == len(set(pillars)) and set(pillars) <= PILLARS, "event_methodology_axes")
    req(isinstance(moat, list) and len(moat) == len(set(moat)) and set(moat) <= MOAT, "event_moat_axes")
    src = event.get("source_graph_ref")
    if tier == "V0":
        req(src is None, "event_v0_no_assessment_source_graph"); status, refresh, src = "DISCOVERY_ONLY", False, None
    else:
        src = ref(src, "event_source_graph"); req(stamp(src["available_at"], "event_source_graph_at") <= verified, "event_source_graph_future")
        refresh = materiality in {"MATERIAL", "CRITICAL"}; status = "A3_REFRESH_CANDIDATE" if refresh else "TRACK"
    out = {
        "schema": EVENT_SCHEMA, "event_id": ident(event.get("event_id"), "event_id"),
        "event_family": ident(event.get("event_family"), "event_family"),
        "first_seen_at": event["first_seen_at"], "verified_at": event["verified_at"],
        "verification_tier": tier, "materiality": materiality, "asset_ids": assets, "theme_id": theme,
        "affected_methodology": list(pillars), "affected_moat": list(moat), "assessment_score_effect": 0,
        "source_graph_ref": src, "status": status, "a3_refresh_required": refresh,
        "research_only": True, "target_book_write_allowed": False, "orders_allowed": False,
    }
    out["event_sha256"] = canonical_sha256(event); return out


def empty_event_registry(as_of: str) -> dict[str, Any]:
    stamp(as_of, "event_registry_as_of")
    return {"schema": EVENT_REGISTRY_SCHEMA, "as_of": as_of, "research_only": True, "cohorts": [], "authority": {"assessment_score_effect": 0, "target_book_write_allowed": False, "orders_allowed": False}}


def subject_key(e: dict[str, Any]) -> str:
    return "ASSET:" + ",".join(sorted(e["asset_ids"])) if e["asset_ids"] else "THEME:" + str(e["theme_id"])


def admit_event(registry: Any, event: Any, cutoff: str, *, dedup_hours: int = 24) -> tuple[dict[str, Any], dict[str, Any]]:
    req(isinstance(registry, dict) and registry.get("schema") == EVENT_REGISTRY_SCHEMA and isinstance(registry.get("cohorts"), list), "event_registry_schema")
    e, out, key = validate_event(event, cutoff), deepcopy(registry), None
    key = subject_key(e); seen = stamp(e["first_seen_at"], "event_first")
    tr, mr = {x:i for i,x in enumerate(TIERS)}, {x:i for i,x in enumerate(MATERIALITIES)}
    for c in out["cohorts"]:
        if c.get("subject_key") == key and c.get("event_family") == e["event_family"] and abs((seen-stamp(c["last_seen_at"], "cohort_last")).total_seconds()) <= dedup_hours*3600:
            c["last_seen_at"], c["latest_event_id"] = e["first_seen_at"], e["event_id"]
            c["event_ids"] = union(c.get("event_ids", []), [e["event_id"]])
            if tr[e["verification_tier"]] > tr[c["verification_tier"]]: c["verification_tier"] = e["verification_tier"]
            if mr[e["materiality"]] > mr[c["materiality"]]: c["materiality"] = e["materiality"]
            c["affected_methodology"], c["affected_moat"] = union(c.get("affected_methodology", []), e["affected_methodology"]), union(c.get("affected_moat", []), e["affected_moat"])
            if e["source_graph_ref"] is not None: c["latest_source_graph_ref"] = e["source_graph_ref"]
            c["a3_refresh_required"] = c["verification_tier"] in {"V1","V2"} and c["materiality"] in {"MATERIAL","CRITICAL"}
            c["status"] = "A3_REFRESH_CANDIDATE" if c["a3_refresh_required"] else ("TRACK" if c["verification_tier"] != "V0" else "DISCOVERY_ONLY")
            if e["verification_tier"] in {"V1", "V2"} and e["materiality"] in {"MATERIAL", "CRITICAL"}:
                c["active_watch_until"] = (seen + timedelta(days=90)).isoformat()
            c["cohort_sha256"] = canonical_sha256({k:v for k,v in c.items() if k != "cohort_sha256"}); out["as_of"] = cutoff
            return out, {"action":"DEDUP_UPDATED", "cohort_id":c["cohort_id"], "a3_refresh_required":c["a3_refresh_required"]}
    cid = "COHORT:" + e["event_id"]
    c = {"cohort_id":cid, "subject_key":key, "asset_ids":e["asset_ids"], "theme_id":e["theme_id"], "event_family":e["event_family"], "first_seen_at":e["first_seen_at"], "last_seen_at":e["first_seen_at"], "first_event_id":e["event_id"], "latest_event_id":e["event_id"], "event_ids":[e["event_id"]], "verification_tier":e["verification_tier"], "materiality":e["materiality"], "affected_methodology":e["affected_methodology"], "affected_moat":e["affected_moat"], "latest_source_graph_ref":e["source_graph_ref"], "status":e["status"], "a3_refresh_required":e["a3_refresh_required"], "active_watch_until":(seen+timedelta(days=90)).isoformat(), "outcome_track_until":(seen+timedelta(days=365)).isoformat(), "assessment_score_effect":0}
    c["cohort_sha256"] = canonical_sha256(c); out["cohorts"].append(c); out["as_of"] = cutoff
    return out, {"action":"ADDED", "cohort_id":cid, "a3_refresh_required":e["a3_refresh_required"]}


def validate_fingerprints(v: Any) -> dict[str, str]:
    req(isinstance(v, dict) and set(v) == FP_KEYS, "fingerprints_keys"); return {k:hx(v[k], "fingerprint:"+k) for k in sorted(FP_KEYS)}


def plan_delta_refresh(previous: Any, current: Any, *, event: dict[str, Any] | None = None, integrity_break: bool = False) -> dict[str, Any]:
    p, c = validate_fingerprints(previous), validate_fingerprints(current); changed = sorted(k for k in FP_KEYS if p[k] != c[k])
    if integrity_break: return {"action":"FULL_A3_REFRESH", "changed":changed, "refresh":["FULL_A3_REVIEW","VALUATION","ER"], "freshness_state":"FULL_REFRESH_DUE"}
    event_action = None
    if event is not None:
        req(event.get("schema") == EVENT_SCHEMA, "planner_event_schema")
        if event.get("verification_tier") in {"V1","V2"} and event.get("materiality") in {"MATERIAL","CRITICAL"}:
            return {"action":"AFFECTED_A3_REFRESH", "changed":changed, "refresh":["AFFECTED_METHODOLOGY_PILLARS","AFFECTED_MOAT_DIMENSIONS","VALUATION","ER"], "affected_methodology":list(event.get("affected_methodology",[])), "affected_moat":list(event.get("affected_moat",[])), "freshness_state":"DELTA_REFRESH_DUE"}
        event_action = "TRACK_ONLY" if event.get("verification_tier") in {"V1","V2"} else "DISCOVERY_ONLY"
    if not changed:
        return {"action":event_action or "SKIP_UNCHANGED", "changed":[], "refresh":[], "freshness_state":"CURRENT"}
    s=set(changed)
    if s == {"market_price_hash"}: refresh=["MARKET_VALUATION","ER"]
    elif s <= {"earnings_consensus_hash","market_price_hash"} and "earnings_consensus_hash" in s: refresh=["EARNINGS_GUIDANCE_CONSENSUS","MARKET_VALUATION","ER"]
    elif s == {"regime_hash"}: refresh=["DOWNSIDE_REGIME","PORTFOLIO_OVERLAY"]
    elif s & {"source_graph_hash","fundamental_hash","methodology_hash"}: refresh=["AFFECTED_A3_REVIEW","MARKET_VALUATION","ER"]
    else: refresh=["DELTA_REVIEW","MARKET_VALUATION","ER"]
    out={"action":"DELTA_REFRESH", "changed":changed, "refresh":refresh, "freshness_state":"DELTA_REFRESH_DUE"}
    if event_action is not None: out["event_action"] = event_action
    return out


def empty_candidate_registry(as_of: str) -> dict[str, Any]:
    stamp(as_of, "candidate_registry_as_of")
    return {"schema":CANDIDATE_REGISTRY_SCHEMA, "as_of":as_of, "research_only":True, "candidates":{}, "authority":{"buy_sell_rank_fields_allowed":False,"target_book_write_allowed":False,"orders_allowed":False}}


def upsert_candidate(registry: Any, record: Any, cutoff: str) -> dict[str, Any]:
    req(isinstance(registry,dict) and registry.get("schema")==CANDIDATE_REGISTRY_SCHEMA and isinstance(registry.get("candidates"),dict), "candidate_registry_schema")
    req(isinstance(record,dict), "candidate_record"); cut=stamp(cutoff,"cutoff")
    aid, iid = ident(record.get("asset_id"),"candidate_asset"), ident(record.get("issuer_id"),"candidate_issuer")
    market, currency = ident(record.get("market"),"candidate_market"), ident(record.get("currency"),"candidate_currency")
    st, fresh, thesis = record.get("security_type"), record.get("freshness_state"), record.get("thesis_status")
    req(st in SECURITY_TYPES and fresh in FRESHNESS and thesis in THESIS, "candidate_enum")
    a3, mkt = ref(record.get("current_a3_result_ref"),"candidate_a3"), ref(record.get("latest_market_snapshot_ref"),"candidate_market_ref")
    er0=record.get("latest_validated_er_ref"); er=None if er0 is None else ref(er0,"candidate_er")
    for name, artifact in (("a3", a3), ("market", mkt), ("er", er)):
        if artifact is not None: req(stamp(artifact["available_at"], "candidate_"+name+"_available_at") <= cut, "candidate_future_artifact:"+name)
    fps=validate_fingerprints(record.get("fingerprints")); full=stamp(record.get("last_full_review_at"),"candidate_full_review")
    delta0=record.get("last_delta_refresh_at"); delta=None if delta0 is None else stamp(delta0,"candidate_delta")
    req(full<=cut and (delta is None or full<=delta<=cut), "candidate_time_order")
    cohorts=[ident(x,"candidate_cohort") for x in record.get("event_cohort_ids",[])]; req(len(cohorts)==len(set(cohorts)),"candidate_duplicate_cohort")
    inv=record.get("invalidation_conditions"); req(isinstance(inv,list) and bool(inv),"candidate_invalidations"); inv=[txt(x,"candidate_invalidation",1200) for x in inv]
    dg, pg=record.get("data_gate_status"),record.get("pit_gate_status"); req(dg in {"PASS","BLOCKED"} and pg in {"PASS","BLOCKED"},"candidate_gates")
    a5=fresh=="CURRENT" and er is not None and dg==pg=="PASS" and thesis!="INVALID"
    row={"asset_id":aid,"issuer_id":iid,"market":market,"currency":currency,"security_type":st,"current_a3_result_ref":a3,"latest_market_snapshot_ref":mkt,"latest_validated_er_ref":er,"event_cohort_ids":cohorts,"thesis_status":thesis,"invalidation_conditions":inv,"freshness_state":fresh,"fingerprints":fps,"last_full_review_at":record["last_full_review_at"],"last_delta_refresh_at":delta0,"data_gate_status":dg,"pit_gate_status":pg,"a5_eligible_input":a5,"research_only":True,"target_book_write_allowed":False,"orders_allowed":False}
    row["record_sha256"]=canonical_sha256(row); out=deepcopy(registry); out["candidates"][aid]=row; out["as_of"]=cutoff; return out


def validate_a3(v: dict[str,Any], c: dict[str,Any]) -> None:
    req(v.get("schema")==A3_RESULT_SCHEMA and v.get("asset_id")==c["asset_id"] and v.get("issuer_id")==c["issuer_id"],"a5_a3_identity")
    req(v.get("selector_eligible") is False and v.get("portfolio_weight_effect")==0.0 and v.get("target_book_write_allowed") is False and v.get("orders_allowed") is False,"a5_a3_authority")


def validate_er(v: dict[str,Any], c: dict[str,Any], benchmark: str) -> dict[str,Any]:
    req(v.get("asset_id")==c["asset_id"] and v.get("validation_status")==ER_STATUS and v.get("benchmark_id")==benchmark and v.get("net_of_costs") is True and v.get("unit")=="RETURN_FRACTION","a5_er_contract")
    out={"signal_confidence":num(v.get("signal_confidence"),"a5_signal_conf",0,1),"thesis_confidence":num(v.get("thesis_confidence"),"a5_thesis_conf",0,1),"expected_drawdown":num(v.get("expected_drawdown"),"a5_drawdown",0,1),"downside_probability":num(v.get("downside_probability"),"a5_downside_prob",0,1),"horizons":{}}
    for h in ER_HORIZONS:
        er=num(v.get(f"expected_return_{h}"),"a5_er:"+h,-1); b=num(v.get(f"benchmark_expected_return_{h}"),"a5_ber:"+h,-1)
        out["horizons"][h]={"expected_return":er,"benchmark_expected_return":b,"expected_alpha":er-b}
    return out


def build_a5_candidate_view(registry: Any, asset_id: str, resolver: ArtifactResolver) -> dict[str,Any]:
    req(isinstance(registry,dict) and registry.get("schema")==CANDIDATE_REGISTRY_SCHEMA and isinstance(registry.get("candidates"),dict),"a5_registry")
    aid=ident(asset_id,"a5_asset"); req(aid in registry["candidates"],"a5_candidate_missing"); c=registry["candidates"][aid]
    blockers=[]
    if c.get("freshness_state")!="CURRENT": blockers.append("STALE_OR_REFRESH_DUE")
    if c.get("data_gate_status")!="PASS": blockers.append("DATA_GATE")
    if c.get("pit_gate_status")!="PASS": blockers.append("PIT_GATE")
    if c.get("latest_validated_er_ref") is None: blockers.append("MISSING_VALIDATED_ER")
    if c.get("thesis_status")=="INVALID": blockers.append("THESIS_INVALID")
    a3=resolve(c["current_a3_result_ref"],resolver,"a5_a3"); validate_a3(a3,c)
    if a3.get("status")!="VALIDATED_ER_LINKED": blockers.append("A3_ER_NOT_LINKED")
    ers=None; erref=c.get("latest_validated_er_ref")
    if erref is not None:
        ers=validate_er(resolve(erref,resolver,"a5_er"),c,ident(a3.get("benchmark_id"),"a5_benchmark"))
        req(a3.get("validated_er_sha256")==erref["sha256"],"a5_er_hash_not_bound_to_a3")
    if blockers:
        return {"schema":A5_VIEW_SCHEMA,"status":"BLOCKED_RESEARCH_ONLY","asset_id":aid,"blockers":sorted(set(blockers)),"research_only":True,"portfolio_proposal_allowed":False,"target_book_write_allowed":False,"orders_allowed":False}
    req(c.get("a5_eligible_input") is True and ers is not None,"a5_candidate_flag_mismatch")
    return {"schema":A5_VIEW_SCHEMA,"status":"READY_RESEARCH_ONLY","asset_id":aid,"issuer_id":c["issuer_id"],"market":c["market"],"currency":c["currency"],"security_type":c["security_type"],"benchmark_id":a3["benchmark_id"],"validated_er":ers["horizons"],"signal_confidence":ers["signal_confidence"],"thesis_confidence":ers["thesis_confidence"],"expected_drawdown":ers["expected_drawdown"],"downside_probability":ers["downside_probability"],"thesis_status":c["thesis_status"],"event_cohort_ids":list(c["event_cohort_ids"]),"a3_result_sha256":c["current_a3_result_ref"]["sha256"],"validated_er_sha256":erref["sha256"],"research_only":True,"portfolio_proposal_allowed":True,"target_book_write_allowed":False,"orders_allowed":False}


__all__=["A3_RESULT_SCHEMA","A5_VIEW_SCHEMA","CANDIDATE_REGISTRY_SCHEMA","CandidateLifecycleError","EVENT_REGISTRY_SCHEMA","EVENT_SCHEMA","admit_event","build_a5_candidate_view","canonical_sha256","empty_candidate_registry","empty_event_registry","plan_delta_refresh","upsert_candidate","validate_event","validate_fingerprints"]

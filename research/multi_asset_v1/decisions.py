"""Evidence-bound thesis, event memory and risk-review proposals.

This module cannot write accepted targets or orders. Proposal limits are supplied
by a reviewed risk packet; they are not fixed asset-class allocations.
"""
from __future__ import annotations

from collections import defaultdict
import math
import numpy as np

from research.theme_etf_runtime_v1.strict import normalize_snapshot
from .contracts import (ContractError, ER_HORIZONS, EVENTS, day, digest, identifier,
                        metadata, number, pinned, require, stamp)

COMPONENTS = {"price":.25, "supply_demand":.25, "inventory":.10,
              "forward_supply":.10, "technology":.10, "valuation":.10, "catalyst":.10}


def event_memory(events, assets, cutoff, policy):
    clusters, seen = {}, set()
    for row in events:
        ident = identifier(row.get("event_id"))
        require(ident not in seen, "duplicate_event_id")
        seen.add(ident)
        metadata(row,cutoff,policy,"event",fresh=False)
        require(row.get("event_type") in EVENTS, "event_taxonomy")
        require(stamp(row["published_at"]) <= stamp(row["available_at"]), "event_publication_time")
        number(row.get("confidence"),0,1)
        number(row.get("materiality"),0,1)
        require(type(row.get("confirmed")) is bool, "event_confirmation_type")
        require(row.get("thesis_effect") in {"REVIEW_POSITIVE","REVIEW_NEGATIVE","REVIEW_UNKNOWN"}, "event_is_review_only")
        require(isinstance(row.get("estimated_duration"),str) and row["estimated_duration"], "event_duration")
        for field in ("asset_ids","commodity_ids","theme_ids"):
            require(isinstance(row.get(field),list), "event_links")
            for x in row[field]: identifier(x)
        require(set(row["asset_ids"]) <= set(assets), "unknown_event_asset")
        cluster = identifier(row.get("duplicate_cluster"))
        target = clusters.setdefault(cluster,{"event_id":cluster, "first_seen":row["available_at"],
                      "last_seen":row["available_at"], "source_ids":set(), "member_ids":[],
                      "published_at":row["published_at"],"available_at":row["available_at"],
                      "commodity_ids":set(),"theme_ids":set(),"evidence":[],
                      "affected_asset_ids":set(), "event_types":set(), "thesis_effects":set(),
                      "confidence":0.0, "materiality":0.0, "confirmed":False,
                      "score_change":None, "requires_thesis_review":True})
        target["first_seen"] = min(target["first_seen"],row["available_at"],key=stamp)
        target["last_seen"] = max(target["last_seen"],row["available_at"],key=stamp)
        target["published_at"] = min(target["published_at"],row["published_at"],key=stamp)
        # Merged attributes include every contributing report, not only the first.
        target["available_at"] = target["last_seen"]
        target["commodity_ids"].update(row["commodity_ids"])
        target["theme_ids"].update(row["theme_ids"])
        target["evidence"].append({k:row[k] for k in ("event_id","published_at","available_at","source","raw_sha256","estimated_duration")})
        target["source_ids"].add(row["source"])
        target["member_ids"].append(ident)
        target["event_types"].add(row["event_type"])
        target["thesis_effects"].add(row["thesis_effect"])
        target["confidence"] = max(target["confidence"],row["confidence"])
        target["materiality"] = max(target["materiality"],row["materiality"])
        target["confirmed"] |= row["confirmed"]
        for aid,a in assets.items():
            if aid in row["asset_ids"] or a["underlying"] in row["commodity_ids"] or set(a["theme_ids"]) & set(row["theme_ids"]):
                target["affected_asset_ids"].add(aid)
    out=[]
    for cluster in sorted(clusters):
        row=clusters[cluster]
        row["source_count"]=len(row["source_ids"])
        for k,v in row.items():
            if isinstance(v,set): row[k]=sorted(v)
        out.append(row)
    return out


def evaluation(row, asset, cutoff, policy, feature_hash):
    pinned(row,policy,"evaluation",cutoff)
    require(row.get("asset_id") == asset["asset_id"], "evaluation_identity")
    require(row.get("feature_sha256") == feature_hash, "evaluation_feature_mismatch")
    require(row.get("unit") == "RETURN_FRACTION" and row.get("currency") == "USD", "evaluation_unit")
    require(row.get("validation_status") == "WALK_FORWARD_VALIDATED", "unvalidated_model")
    require(row.get("model_id") in policy["validated_models"], "model_not_admitted")
    model=policy["validated_models"][row["model_id"]]
    require(asset["asset_class"] in model["asset_classes"], "unsupported_model_asset_class")
    require(row.get("validation_sha256") == model["validation_sha256"], "validation_identity")
    require(stamp(row["training_labels_available_before"]) < stamp(row["observed_at"]), "label_leakage")
    require(row.get("thesis_status") in {"POSITIVE","INTACT","INVALID","NEGATIVE"}, "thesis_status")
    identifier(row.get("thesis_id"))
    require(type(row.get("valuation_acceptable")) is bool, "valuation_boolean")
    require(row.get("net_of_costs") is True, "net_costs_required")
    for cost in ("spread_bps","commission_bps","slippage_bps","tax_bps","expense_bps","roll_bps"):
        number(row["cost_assumptions"].get(cost),0)
    require(row.get("cost_basis") == "INCREMENTAL_NOT_ALREADY_IN_TOTAL_RETURN", "cost_double_count_guard")
    number(row.get("signal_confidence"),0,1)
    number(row.get("thesis_confidence"),0,1)
    number(row.get("downside_probability"),0,1)
    require(number(row.get("expected_drawdown"),0,1)>0,"positive_downside_risk")
    for h in ER_HORIZONS:
        er=number(row.get("expected_return_"+h),-1)
        number(row.get("benchmark_expected_return_"+h),-1)
        scenarios=row["scenarios"][h]
        returns=[number(scenarios[k]["return"],-1) for k in ("bear","base","bull")]
        probabilities=[number(scenarios[k]["probability"],0,1) for k in ("bear","base","bull")]
        require(returns==sorted(returns) and math.isclose(sum(probabilities),1,abs_tol=1e-9),"scenario_distribution")
        require(math.isclose(sum(r*p for r,p in zip(returns,probabilities)),er,abs_tol=1e-9),"scenario_expected_return")
    if asset["asset_class"] in {"COMMODITY_EQUITY","CRYPTO_EQUITY"}:
        require(row.get("company_evidence_sha256") in policy["reviewed_pins"]["company_evidence"],"company_quality_required")
    if asset["underlying"] is not None:
        require(row.get("underlying_evidence_sha256") in policy["reviewed_pins"]["underlying_evidence"],"underlying_thesis_required")
    components=row.get("component_scores",{})
    fundamental=None
    if all(k in components for k in COMPONENTS):
        fundamental=sum(number(components[k],0,1)*w for k,w in COMPONENTS.items())
    return {**row,"fundamental_score":fundamental,
            "expected_alpha_12m":row["expected_return_12m"]-row["benchmark_expected_return_12m"]}


def classify(features, evaluation_row, held=False):
    if not features:
        return "UNKNOWN","BLOCKED"
    short=features["RS20"]<0
    long_ok=features["RS120"]>0 and features["RS240"]>0
    improving=features["RS20_change_5d"]>0 and features["RS60_change_5d"]>0
    intact=evaluation_row is not None and evaluation_row["thesis_status"] in {"POSITIVE","INTACT"}
    if evaluation_row and evaluation_row.get("cycle_state")=="OVERSUPPLY":
        state="OVERSUPPLY"
    elif short and long_ok and intact:
        state="REVERSAL_PANIC"
    elif improving and short:
        state="EARLY_RECOVERY"
    elif improving and features["RS20"]>0:
        state="EMERGING"
    elif all(features[f"RS{h}"]>0 for h in (60,120,240)):
        state="ESTABLISHED"
    else:
        state="FADING"
    if evaluation_row is None:
        return state,"RESEARCH"
    if evaluation_row["thesis_status"]=="INVALID":
        return state,"EXIT_REVIEW" if held else "BLOCKED"
    if held:
        # A single short RS loss can never produce a reduction/removal.
        if evaluation_row["thesis_status"]=="NEGATIVE" and not long_ok:
            return state,"REDUCE_REVIEW"
        return state,"HOLD"
    return state,"CANDIDATE" if intact and evaluation_row["valuation_acceptable"] else "WATCH"


def lookthrough(weights, assets, holdings, cutoff, policy):
    """Expand reviewed, complete snapshots; count direct+indirect only once."""
    leaves=defaultdict(float)
    def expand(aid, weight, chain):
        require(aid not in chain,"etf_cycle")
        a=assets[aid]
        if a["vehicle_type"]=="EQUITY_ETF":
            raw=holdings.get(aid)
            require(raw is not None,"missing_etf_holdings:"+aid)
            pinned(raw,policy,"holdings",cutoff)
            require(raw.get("fund_id")==aid and raw.get("portfolio_scope")=="FULL_PORTFOLIO","holdings_scope")
            require((stamp(cutoff).date()-day(raw["holdings_as_of"])).days <= 7,"stale_holdings")
            for r in raw["rows"]:
                require(r.get("identity_verified") is True,"holding_identity")
                require(r.get("instrument") in {"COMMON","ADR","ETF"},"unsupported_holding_instrument")
                number(r.get("weight"),0)
                require(r.get("security_id") in assets,"unknown_holding")
            snap=normalize_snapshot(raw)
            require(stamp(snap["available_at"]) <= stamp(cutoff),"future_normalized_holdings")
            require(snap["complete"] and abs(snap["weight_sum"]-1)<1e-8,"incomplete_holdings")
            for r in snap["rows"]:
                expand(r["security_id"],weight*r["weight"],chain+[aid])
        else:
            # A physical/futures trust is one vehicle, not shares of a mining company.
            leaves[aid]+=weight
    for aid,weight in weights.items():
        number(weight,0,1)
        require(aid in assets,"unknown_position")
        if weight: expand(aid,weight,[])
    groups=defaultdict(float)
    for aid,weight in leaves.items():
        for group in assets[aid]["risk_group_ids"]:
            groups[group]+=weight
    return {"security_exposure":dict(leaves),"risk_group_exposure":dict(groups)}


def propose(rows, assets, risk, holdings, cutoff, policy, input_hash, current_weights=None):
    pinned(risk,policy,"risk",cutoff)
    require(risk.get("feature_sha256")==input_hash,"risk_feature_mismatch")
    require(risk.get("regime") in {"RISK_ON","CAUTION","RISK_OFF","RECOVERY"},"market_regime")
    gross=number(risk.get("max_gross"),0,1)
    cap=number(risk.get("max_security_weight"),0,1)
    max_corr=number(risk.get("max_pair_correlation"),0,1)
    current_weights=dict(current_weights or {})
    for aid,weight in current_weights.items():
        require(aid in assets,"unknown_current_position")
        number(weight,0,1)
    require(sum(current_weights.values())<=1+1e-9,"current_position_weight_sum")
    require(all(r["asset_id"] in current_weights for r in rows if r["portfolio_status"]=="HOLD"),"held_weights_required")
    eligible=[]
    threshold=number(risk.get("minimum_expected_alpha"),0)
    for r in rows:
        aid=r["asset_id"]
        if r["portfolio_status"] not in {"CANDIDATE","HOLD"}: continue
        a=assets[aid]
        if a["tradable"] is not True or a.get("identity_verified") is not True: continue
        if r.get("thesis_status") not in {"POSITIVE","INTACT"} or r.get("valuation_acceptable") is not True: continue
        if r["expected_alpha_12m"]<=threshold or r["liquidity_pass"] is not True: continue
        # Entry requires both short improvement and acceptable longer strength.
        if not (r["RS20_change_5d"]>0 and r["RS60_change_5d"]>0 and r["RS120"]>=0 and r["RS240"]>=0): continue
        multiplier=number(risk["risk_multipliers"].get(a["asset_class"]),1)
        raw=r["expected_alpha_12m"]*r["signal_confidence"]*r["thesis_confidence"]/(r["expected_drawdown"]*multiplier)
        if raw>0: eligible.append((r,raw))
    eligible.sort(key=lambda x:(-x[1],x[0]["asset_id"]))
    selected=[]
    require({aid for aid,w in current_weights.items() if w>0}<={r["asset_id"] for r in rows},"held_comparison_missing")
    existing_rows=[r for r in rows if current_weights.get(r["asset_id"],0)>0]
    for i,r in enumerate(existing_rows):
        require(len(r.get("daily_log_returns",[]))==60,"held_correlation_history_required")
        require(np.std(r["daily_log_returns"])>1e-12,"undefined_held_correlation")
        for other in existing_rows[:i]:
            correlation=float(np.corrcoef(r["daily_log_returns"],other["daily_log_returns"])[0,1])
            require(math.isfinite(correlation) and abs(correlation)<=max_corr,"carried_pair_correlation_limit")
    for r,raw in eligible:
        vector=np.asarray(r["daily_log_returns"])
        require(np.std(vector)>1e-12,"undefined_correlation")
        comparators=[p for p,_ in selected]+[p for p in existing_rows if p["asset_id"]!=r["asset_id"]]
        if any(np.std(p["daily_log_returns"])<=1e-12 or abs(float(np.corrcoef(vector,p["daily_log_returns"])[0,1]))>max_corr for p in comparators):
            continue
        selected.append((r,raw))
    total=sum(raw for _,raw in selected)
    free=max(0,gross-sum(current_weights.values()))
    # A missing entry signal does not liquidate an existing holding. Only the
    # separately pinned risk ceilings below may reduce the carried book.
    weights={aid:w for aid,w in current_weights.items() if w>0}
    if total:
        for r,raw in selected:
            aid=r["asset_id"]
            old=weights.get(aid,0)
            weights[aid]=old+min(max(0,cap-old),free*raw/total)
    exposure=lookthrough(weights,assets,holdings,cutoff,policy)
    scale=min(1.0,gross/sum(weights.values())) if sum(weights.values()) else 1.0
    for group,value in exposure["risk_group_exposure"].items():
        limit=number(risk["risk_group_limits"].get(group),0,1)
        if value>limit: scale=min(scale,limit/value)
    for value in [*weights.values(),*exposure["security_exposure"].values()]:
        if value>cap: scale=min(scale,cap/value)
    weights={k:v*scale for k,v in weights.items()}
    # No redistribution to force a commodity/crypto minimum; unused budget stays cash.
    for r,_ in selected:
        if weights[r["asset_id"]]>current_weights.get(r["asset_id"],0)+1e-12:
            r["portfolio_status"]="ADD_CONSIDERATION" if r["portfolio_status"]=="HOLD" else "BUY_CONSIDERATION"
    return {"status":"RESEARCH_PROPOSAL", "regime":risk["regime"],"proposed_weights":weights,
            "carried_position_weights":current_weights,"risk_ceiling_scale":scale,
            "reduction_basis":"REVIEWED_RISK_CEILINGS_ONLY" if scale<1 else None,
            "cash":1-sum(weights.values()),"exposure":lookthrough(weights,assets,holdings,cutoff,policy),
            "accepted_target":False,"orders_generated":False}

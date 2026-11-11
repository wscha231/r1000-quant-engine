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
                        metadata, number, pinned, require, stamp, unique)

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


def evaluation(row, asset, cutoff, policy, feature_hash, feature_available_at):
    pinned(row,policy,"evaluation",cutoff)
    require(row.get("asset_id") == asset["asset_id"], "evaluation_identity")
    require(row.get("feature_sha256") == feature_hash, "evaluation_feature_mismatch")
    require(feature_available_at is not None and stamp(row["observed_at"]) >= stamp(feature_available_at),
            "evaluation_predates_feature_inputs")
    require(row.get("unit") == "RETURN_FRACTION" and row.get("currency") == "USD", "evaluation_unit")
    require(row.get("validation_status") == "WALK_FORWARD_VALIDATED", "unvalidated_model")
    require(row.get("model_id") in policy["validated_models"], "model_not_admitted")
    model=policy["validated_models"][row["model_id"]]
    require(row.get("benchmark_id") == model.get("benchmark_id") == policy["benchmark_id"] == asset["benchmark"],
            "evaluation_benchmark_mismatch")
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


def propose(rows, assets, risk, holdings, cutoff, policy, input_hash, current_weights=None, *, decision_events=None,
            artifact_resolver=None,model_review=None):
    pinned(risk,policy,"risk",cutoff)
    require(risk.get("feature_sha256")==input_hash,"risk_feature_mismatch")
    require(risk.get("regime") in {"RISK_ON","CAUTION","RISK_OFF","RECOVERY"},"market_regime")
    if policy.get("stock_cash_research",{}).get("enabled") is True:
        return stock_cash_proposal(rows,assets,risk,holdings,cutoff,policy,input_hash,current_weights,
                                   decision_events=decision_events,artifact_resolver=artifact_resolver,
                                   model_review=model_review)
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


STOCK_CLASSES = frozenset({"US_EQUITY","COMMODITY_EQUITY","CRYPTO_EQUITY"})
EXCEPTION_SYMBOLS = frozenset({"GLDM","SHY","IEF","TLT"})


def stock_research_profile(policy):
    """An opt-in policy, authenticated by the existing current A3 policy hash."""
    p=policy.get("stock_cash_research")
    require(type(p) is dict and p.get("schema")=="stock-cash-research-v1","stock_research_profile")
    require(p.get("enabled") is True,"stock_research_disabled")
    require(p.get("allocator") in {"CONTROL","COST_AWARE_LONG_ONLY"},"stock_allocator")
    require(p.get("cadence") in {"MONTHLY","WEEKLY","MONTHLY_CONFIRMED_EVENT"},"stock_cadence")
    require(p.get("horizon")=="12_CALENDAR_MONTHS" and p.get("deep_review_count")==40,
            "stock_horizon_or_queue_changed")
    require(p.get("exception_weight_cap")==.20 and p.get("cash_mode")=="DGS3MO_CARRY",
            "stock_exception_or_cash_policy")
    require(type(p.get("cost_bps_per_side")) is int and p["cost_bps_per_side"] in {25,50,100},"stock_cost_scenario")
    require(number(p.get("risk_aversion"),0)==1.0,"stock_fixed_research_risk_aversion")
    return p


def stock_decision_scope(rows,assets,current_weights,events,cutoff,policy,decision_asset_ids=None):
    """Keep the full denominator; this queue is not a global ER certification."""
    p=stock_research_profile(policy)
    stocks=[r for r in rows if assets.get(r["asset_id"],{}).get("asset_class") in STOCK_CLASSES]
    # Discovery can nominate missing-ER names for work, never provide their ER.
    ordered=sorted(stocks,key=lambda r:(r.get("risk_adjusted_expected_alpha") is None,
        -(r.get("risk_adjusted_expected_alpha") or 0),r.get("discovery_rank") or 10**9,r["asset_id"]))
    top={r["asset_id"] for r in ordered[:p["deep_review_count"]]}
    held={a for a,w in current_weights.items() if number(w,0,1)>0}
    important={a for e in events if e["confirmed"] and e["materiality"]>=.5
               for a in e["affected_asset_ids"]}
    declared=decision_asset_ids if type(decision_asset_ids) is list else []
    ids=top|held|important|set(declared)
    by_id={r["asset_id"]:r for r in rows}
    records=[]
    for aid in sorted(ids):
        r=by_id.get(aid,{})
        ready=(r.get("data_quality")=="PRICE_OBSERVED_RESEARCH_ONLY" and
               r.get("evaluation_sha256") is not None and r.get("expected_return_12m") is not None)
        records.append(dict(asset_id=aid,status="INPUTS_OBSERVED" if ready else "UNKNOWN",
            reasons=sorted(((["TOP40"] if aid in top else [])+(["HELD"] if aid in held else [])+
                            (["IMPORTANT_EVENT"] if aid in important else [])+
                            (["EXPLICIT_A5_COHORT"] if aid in declared else []))),
            blockers=list(r.get("blockers",[])) if r else ["UNMAPPED_SCOPE_ID"]))
    valid_declared=(bool(declared) and len(declared)==len(set(declared)) and held<=set(declared) and
        set(declared)<=set(by_id) and all(next(r for r in records if r["asset_id"]==a)["status"]=="INPUTS_OBSERVED"
                                        for a in declared))
    return dict(status="RESEARCH_QUEUE_PRESERVED",records=records,asset_ids=sorted(ids),
                decision_asset_ids=declared,numeric_scope_status="SCOPED_INPUTS_OBSERVED" if valid_declared else "BLOCKED",
                queue_unknown_count=sum(r["status"]=="UNKNOWN" for r in records),
                full_roster_count=len(rows),unknown_roster_count=sum(r.get("evaluation_sha256") is None for r in rows),
                global_ranking_certified=False,cutoff=cutoff)


def stock_decision_clock(cutoff,profile,review,events):
    """Calendar-only intent; no next-session prices enter a decision."""
    from datetime import timedelta
    import pandas as pd
    import pandas_market_calendars as mcal
    from .prices import grid
    sessions=grid(cutoff)
    session=list(sessions)[-1]
    close=sessions[session]
    horizon_end=(pd.Timestamp(session)+pd.DateOffset(months=12)).date()
    schedule=mcal.get_calendar("NYSE").schedule(start_date=day(session)+timedelta(days=1),end_date=horizon_end)
    require(not schedule.empty,"stock_next_close_calendar")
    previous=review.get("previous_decision_at")
    previous_at=stamp(previous) if previous is not None else None
    require(previous_at is None or previous_at<=stamp(cutoff),"stock_future_previous_decision")
    previous_session=list(grid(previous))[-1] if previous is not None else None
    previous_day=day(previous_session) if previous_session is not None else None
    changed=[e["event_id"] for e in events if e["confirmed"] and e["materiality"]>=.5 and
             (previous_at is None or stamp(e["first_seen"])>previous_at)]
    month_due=previous_day is None or (previous_day.year,previous_day.month)!=(day(session).year,day(session).month)
    week_due=previous_day is None or previous_day.isocalendar()[:2]!=day(session).isocalendar()[:2]
    due={"MONTHLY":month_due,"WEEKLY":week_due,
         "MONTHLY_CONFIRMED_EVENT":month_due or bool(changed)}[profile["cadence"]]
    return dict(decision_session=session,previous_decision_session=previous_session,
        same_session=previous_session==session,decision_at=cutoff,scheduled_due=due,
        cadence=profile["cadence"],confirmed_new_event_ids=sorted(changed),
        earliest_fill_at=schedule["market_close"].iloc[0].isoformat(),fill_mode="NEXT_NYSE_CLOSE",
        horizon="12_CALENDAR_MONTHS",horizon_end=horizon_end.isoformat(),
        covariance_scale_sessions=len(schedule),carry_calendar_days=(horizon_end-day(session)).days,
        realized_fills=False)


def _stock_cost(row,side_bps):
    basis=row.get("portfolio_cost_basis")
    require(type(basis) is dict and basis.get("schema")=="reviewed-portfolio-cost-basis-v1",
            "stock_net_er_cost_basis_missing:"+row["asset_id"])
    require(basis.get("horizon")=="12_CALENDAR_MONTHS" and
            basis.get("kind")=="NET_REFERENCE_ROUND_TRIP","stock_er_cost_horizon")
    require(basis.get("cost_assumptions_sha256")==digest(row["cost_assumptions"]),"stock_er_cost_measurement_changed")
    require(type(basis.get("evidence_sha256")) is str and len(basis["evidence_sha256"])==64 and
            all(c in "0123456789abcdef" for c in basis["evidence_sha256"]),"stock_er_cost_original_required")
    reference=number(basis.get("reference_cost_bps_per_side"),25)
    embedded=number(basis.get("embedded_cost_fraction"),0)
    transaction=number(basis.get("embedded_transaction_cost_fraction"),0)
    ongoing=number(basis.get("embedded_ongoing_cost_fraction"),0)
    gross=number(basis.get("gross_expected_return"),-1)
    require(math.isclose(gross-embedded,number(row["expected_return_12m"],-1),abs_tol=1e-9),
            "stock_net_gross_cost_reconciliation")
    assumptions=row["cost_assumptions"]
    measured_side=sum(number(assumptions[k],0) for k in ("spread_bps","commission_bps","slippage_bps","tax_bps"))
    measured_ongoing=sum(number(assumptions[k],0) for k in ("expense_bps","roll_bps"))/10000
    require(math.isclose(reference,measured_side,abs_tol=1e-9) and reference<=side_bps and
            math.isclose(transaction,2*reference/10000,abs_tol=1e-9) and
            math.isclose(ongoing,measured_ongoing,abs_tol=1e-9) and
            math.isclose(embedded,transaction+ongoing,abs_tol=1e-9),"stock_embedded_cost_component_reconciliation")
    # Only the reference transaction is restored. Annual expense/roll remains
    # in the ER. The named 25/50/100bps scenarios are ALL-IN per actual side.
    return number(row["expected_return_12m"],-1)+transaction,side_bps/10000


def _stock_cash_return(quote,clock,cutoff,policy,artifact_resolver):
    import csv
    import hashlib
    import io
    import tempfile
    from pathlib import Path
    import pandas as pd
    from research.a2_research_intake_v1 import MemoryArtifacts
    from tools.run_broker_ledger_replay import CashCarryConfig,load_cash_rate_series,lookup_cash_rate
    require(type(quote) is dict and quote.get("metric")=="dgs3mo" and quote.get("unit")=="FRACTION",
            "stock_dgs3mo_quote_required")
    metadata(quote,cutoff,policy,"metric")
    require(quote.get("source")=="FRED_ARCHIVE","stock_current_vintage_cash_forbidden")
    ref=quote.get("original_ref")
    require(type(artifact_resolver) is MemoryArtifacts and type(ref) is dict,"stock_dgs3mo_original_resolver_required")
    require(type(ref.get("bytes")) is int and 0<ref["bytes"]<=1048576 and
            ref.get("sha256")==quote["raw_sha256"],"stock_dgs3mo_original_binding")
    raw=artifact_resolver.read(ref["artifact_id"],ref["sha256"])
    require(len(raw)==ref["bytes"] and hashlib.sha256(raw).hexdigest()==ref["sha256"],"stock_dgs3mo_original_bytes")
    original=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    require(original.fieldnames is not None and "DGS3MO" in original.fieldnames and
            ("DATE" in original.fieldnames or "observation_date" in original.fieldnames),"stock_dgs3mo_original_columns")
    date_col="DATE" if "DATE" in original.fieldnames else "observation_date"
    seen=set()
    for row in original:
        date=day(row[date_col]);value=row["DGS3MO"]
        require(date<=day(clock["decision_session"]) and date not in seen,"stock_dgs3mo_future_or_duplicate_original")
        seen.add(date)
        if value not in {".",""}:number(float(value),0,100)
    with tempfile.TemporaryDirectory(prefix="a5-cash-source-") as folder:
        path=Path(folder)/"dgs3mo.csv"
        with path.open("xb") as stream:stream.write(raw)
        config=CashCarryConfig(mode="risk_free_rate",rate_source="DGS3MO",rate_lag_days=1,
                               haircut_bps=0,day_count=365,rate_path=path)
        table=load_cash_rate_series(config,Path(folder))
        selected=lookup_cash_rate(table,pd.Timestamp(clock["decision_session"]))
    require(selected is not None and selected["rate_date"]==quote.get("observation_date") and
            math.isclose(selected["rate_pct"]/100,number(quote.get("value"),0,1),abs_tol=1e-12),
            "stock_dgs3mo_original_value_or_date_mismatch")
    # Constant-current-yield forecast for comparison; actual daily ledger accrual
    # still requires its complete admitted rate calendar. This grants no PIT.
    return selected["rate_pct"]/100*clock["carry_calendar_days"]/365


def _stock_exit(review,row,old,by_id,cutoff,current,artifact_resolver,risk):
    """Original risk review plus current same-security thesis; never missing=exit."""
    from tools.run287_hold_exit_policy import classify_execution_sell, SELL_TAXONOMY
    require(review.get("taxonomy") in set(SELL_TAXONOMY)-{"EXECUTION_RECONCILIATION"},"stock_exit_taxonomy")
    require(review.get("evaluation_sha256")==row.get("evaluation_sha256") and
            review.get("thesis_id")==row.get("thesis_id"),"stock_exit_original_thesis")
    require(type(review.get("reason")) is str and bool(review["reason"]),"stock_exit_reason")
    require(stamp(review["available_at"])<=stamp(cutoff)<stamp(review["expires_at"]),"stock_exit_clock")
    target=number(review.get("max_weight"),0,old)
    kind=review["taxonomy"]
    if kind=="THESIS_EXIT":
        require(row.get("thesis_status") in {"INVALID","NEGATIVE"},"stock_healthy_thesis_exit")
    elif kind=="RISK_EXIT":
        require(review.get("risk_feature_sha256")==digest({k:row.get(k) for k in
            ("expected_drawdown","downside_probability","RS120","RS240")}),"stock_exit_risk_features")
        scale=min(1.0,number(risk["max_gross"],0,1)/sum(current.values()),
                  number(risk["max_security_weight"],0,1)/max(current.values()))
        require(scale<1 and math.isclose(target,old*scale,abs_tol=1e-9),"stock_risk_exit_not_recomputed_ceiling")
    elif kind=="REPLACEMENT_EXIT":
        other=by_id.get(review.get("replacement_asset_id"))
        require(other is not None and other.get("portfolio_status")=="CANDIDATE" and
                other.get("evaluation_sha256")==review.get("replacement_evaluation_sha256"),
                "stock_replacement_original_candidate")
        from tools.run287_hold_exit_policy import (LeadershipPersistencePolicy,incumbent_protection,
                                                   challenger_eligible,concentration_not_worse)
        from .prices import grid
        evidence={}
        for aid,r in by_id.items():
            item=r.get("hold_exit_evidence")
            require(type(item) is dict and item.get("security_id")==aid and
                    item.get("as_of")==list(grid(cutoff))[-1] and
                    stamp(item["available_at"])<=stamp(cutoff),"stock_replacement_current_evidence")
            record=item.get("record")
            require(type(record) is dict and record.get("ticker")==r["symbol"] and not any(
                token in k.lower() for k in record for token in ("forward_return","future_return","outcome","label_")),
                "stock_replacement_record_identity_or_labels")
            evidence[aid]=record
        require(review.get("scored_cohort_sha256")==digest(evidence),"stock_replacement_cohort_changed")
        scores=[number(r.get("alphaops_vnext_score")) for r in evidence.values()]
        native=LeadershipPersistencePolicy()
        own=evidence[row["asset_id"]];challenger=evidence[other["asset_id"]]
        percentile=(sum(x<number(own["rs_benchmark_3m"]) for x in
            [number(r["rs_benchmark_3m"]) for r in evidence.values()])+1)/len(evidence)
        protected,reason,native_taxonomy=incumbent_protection(own,portfolio="main",score_median=float(np.median(scores)),
            score_sigma=float(np.std(scores)),rs_percentile=percentile,lifecycle_terminal=False,policy=native)
        require(native_taxonomy!="EXECUTION_RECONCILIATION" and not reason.startswith("missing_required_evidence"),
                "stock_replacement_incomplete_incumbent")
        allowed,_=challenger_eligible(challenger,lifecycle_terminal=False,policy=native)
        require(allowed and number(challenger["alphaops_vnext_score"])-number(own["alphaops_vnext_score"])>=
                native.required_gap(float(np.std(scores))),"stock_canonical_replacement_margin_not_met")
        before=[dict(evidence[a],weight=w) for a,w in current.items() if w>0]
        after={a:w for a,w in current.items() if w>0}
        after[row["asset_id"]]=target
        after[other["asset_id"]]=after.get(other["asset_id"],0)+old-target
        concentration_ok,_,_,_=concentration_not_worse(before,
            [dict(evidence[a],weight=w) for a,w in after.items() if w>0],portfolio="main")
        require(concentration_ok,"stock_replacement_concentration_worse")
        # The fixed margin applies even when a winner is protected; no short-RS
        # warning alone is sufficient to displace it.
        review_basis=dict(replacement_asset_id=other["asset_id"],winner_protected=protected,
                          incumbent_policy_reason=reason,required_gap=native.required_gap(float(np.std(scores))))
    else:
        import hashlib
        import tempfile
        from pathlib import Path
        import pandas as pd
        from research.a2_research_intake_v1 import MemoryArtifacts
        from tools.security_lifecycle import resolve_security_lifecycle
        from .prices import grid
        ref=review.get("lifecycle_ref")
        require(type(artifact_resolver) is MemoryArtifacts and type(ref) is dict,"stock_original_lifecycle_resolver_unbound")
        require(type(ref.get("bytes")) is int and 0<ref["bytes"]<=262144 and
                stamp(ref["available_at"])<=stamp(cutoff),"stock_lifecycle_ref_bounds_clock")
        raw=artifact_resolver.read(ref["artifact_id"],ref["sha256"])
        require(len(raw)==ref["bytes"] and hashlib.sha256(raw).hexdigest()==ref["sha256"],"stock_lifecycle_original_bytes")
        # The native parser accepts a file. Decode only the pinned small metadata
        # operand in a private temporary directory, never a book or target path.
        with tempfile.TemporaryDirectory(prefix="a5-lifecycle-") as folder:
            path=Path(folder)/"original.csv"
            with path.open("xb") as stream:stream.write(raw)
            resolved=resolve_security_lifecycle(path,session_date=pd.Timestamp(list(grid(cutoff))[-1]),
                decision_time_utc=pd.Timestamp(cutoff),active_tickers=[row["symbol"]])
            require(row["symbol"] in resolved.terminal_tickers and target==0 and
                    row["asset_id"] in set(resolved.terminal_events["stable_security_id"]),
                    "stock_lifecycle_not_terminal_same_security")
        review_basis=dict(lifecycle_original_sha256=ref["sha256"])
    taxonomy,_=classify_execution_sell(ticker=row["asset_id"],target_weight=target,
        target_gross_reduced=False,explicit_taxonomy=kind)
    return target,dict(asset_id=row["asset_id"],taxonomy=taxonomy,reason=review["reason"],
        review_sha256=digest(review),prior_weight=old,max_weight=target,
        **(review_basis if kind in {"REPLACEMENT_EXIT","LIFECYCLE_EXIT"} else {}))


def stock_cash_proposal(rows,assets,risk,holdings,cutoff,policy,input_hash,current_weights=None, *, decision_events=None,
                        artifact_resolver=None,model_review=None):
    """One frozen moment/cost input shared by Control and long-only SLSQP.

    Only research comparison weights are returned. Physical fills, integer shares,
    realized DGS3MO accrual and NAV remain the existing admitted ledger's job.
    """
    from scipy.optimize import minimize
    from sklearn.covariance import LedoitWolf
    from .prices import grid
    p=stock_research_profile(policy)
    pinned(risk,policy,"risk",cutoff)
    require(risk.get("feature_sha256")==input_hash,"risk_feature_mismatch")
    review=risk.get("stock_cash_allocation")
    require(type(review) is dict and review.get("horizon")==p["horizon"],"stock_reviewed_allocation_required")
    declared=review.get("decision_asset_ids")
    require(type(declared) is list and bool(declared) and len(declared)==len(set(declared)),"stock_explicit_a5_cohort_required")
    require(set(declared)=={r["asset_id"] for r in rows},"stock_explicit_a5_cohort_mismatch")
    require(review.get("evaluation_sha256_by_asset")=={r["asset_id"]:r.get("evaluation_sha256") for r in rows},
            "stock_declared_cohort_original_er")
    require("decision_events" not in review,"stock_decision_events_must_come_from_runtime")
    events=event_memory(decision_events or [],assets,cutoff,policy)
    require(review.get("events_sha256")==digest(decision_events or []),"stock_decision_event_binding")
    clock=stock_decision_clock(cutoff,p,review,events)
    current=dict(current_weights or {})
    require(sum(number(w,0,1) for w in current.values())<=1+1e-9,"current_position_weight_sum")
    by_id={r["asset_id"]:r for r in rows}
    require(len(by_id)==len(rows) and set(current)<=set(by_id),"stock_held_rows_missing")
    cap=number(risk.get("max_security_weight"),0,1)
    gross_cap=number(risk.get("max_gross"),0,1)
    max_corr=number(risk.get("max_pair_correlation"),0,1)
    alternatives=unique(review.get("exception_reviews",[]),"asset_id")
    exits=unique(review.get("exit_reviews",[]),"asset_id")
    require(set(exits)<={a for a,w in current.items() if w>0},"stock_exit_not_held")
    accepted,lower,upper,exit_audit=[],[],[],[]
    for row in rows:
        aid=row["asset_id"];asset=assets[aid];old=current.get(aid,0)
        stock=asset["asset_class"] in STOCK_CLASSES
        exception=asset["symbol"] in EXCEPTION_SYMBOLS
        if not (stock or exception or old>0): continue
        if row.get("evaluation_sha256") is None or row.get("data_quality")!="PRICE_OBSERVED_RESEARCH_ONLY":
            require(old==0,"stock_held_input_unknown:"+aid)
            continue
        require(row.get("net_of_costs") is True,"stock_net_er_required")
        entry=(row.get("portfolio_status") in {"CANDIDATE","HOLD"} and
            row.get("thesis_status") in {"POSITIVE","INTACT"} and row.get("valuation_acceptable") is True and
            row.get("liquidity_pass") is True and row["expected_alpha_12m"]>risk["minimum_expected_alpha"] and
            row["RS20_change_5d"]>0 and row["RS60_change_5d"]>0 and row["RS120"]>=0 and row["RS240"]>=0)
        tradable=asset["tradable"] is True and asset["identity_verified"] is True
        lo=old;hi=cap if entry and tradable and (stock or exception) else old
        if not stock and old>0:
            require(exception or asset["vehicle_type"]=="EQUITY_ETF","stock_carried_nonstock_review_required:"+aid)
        if exception:
            proof=alternatives.get(aid)
            if proof is None:
                require(old==0,"stock_exception_release_proof_missing:"+aid)
                continue
            require(proof.get("evaluation_sha256")==row["evaluation_sha256"] and
                    proof.get("thesis_id")==row["thesis_id"],"stock_exception_original_er")
            require(proof.get("basis") in {"OPPORTUNITY","SPECIAL_RISK"} and
                    all(type(proof.get(k)) is str and proof[k] for k in ("reason","release_condition")),
                    "stock_exception_review_basis")
            require(stamp(proof["available_at"])<=stamp(cutoff)<stamp(proof["expires_at"]),"stock_exception_expired")
            hi=min(hi,number(proof.get("max_weight"),0,.20))
        if aid in exits:
            hi,audit=_stock_exit(exits[aid],row,old,by_id,cutoff,current,artifact_resolver,risk);lo=hi;exit_audit.append(audit)
        if not old and (not entry or not tradable): continue
        require(lo<=hi+1e-10,"stock_winner_hard_limit_conflict:"+aid)
        accepted.append(row);lower.append(lo);upper.append(hi)
    def known_model_cash_decision():
        profile=policy.get("current_a3_review_profile")
        require(type(model_review) is dict and type(profile) is dict and
                model_review.get("status")=="CURRENT_REFERENCE_REVIEW_VERIFIED" and
                model_review.get("context_sha256")==profile.get("context_sha256") and
                model_review.get("graph_sha256")==profile.get("graph_sha256") and
                profile.get("feature_sha256")==input_hash and profile.get("risk_sha256")==digest(risk),
                "stock_cash_unknown_model_or_genesis")
        kind=model_review.get("model_state_kind")
        known=(kind=="GENESIS" and not any(current.values())) or (
            kind=="INCUMBENTS" and model_review.get("model_incumbents",{}).get("status")=="CURRENT_MODEL_ALLOCATION_VERIFIED") or (
            kind=="PARENT_LINEAGE_ONLY" and model_review.get("model_parent_lineage",{}).get("status")=="PARENT_LINEAGE_ONLY_VERIFIED")
        require(known,"stock_cash_unknown_model_or_genesis")
        return kind
    if not accepted:
        kind=known_model_cash_decision()
        # A genuine no-entry decision has fully observed inputs. Missing price,
        # ER, identity or costs cannot silently become a cash allocation.
        require(all(r.get("data_quality")=="PRICE_OBSERVED_RESEARCH_ONLY" and
                    r.get("evaluation_sha256") is not None and r.get("net_of_costs") is True and
                    assets[r["asset_id"]]["identity_verified"] is True and
                    assets[r["asset_id"]]["tradable"] is True for r in rows),"stock_cash_incomplete_decision_inputs")
        costs={r["asset_id"]:_stock_cost(r,p["cost_bps_per_side"]) for r in rows}
        quote=review.get("cash_carry")
        carry=_stock_cash_return(quote,clock,cutoff,policy,artifact_resolver)
        frozen=dict(feature_sha256=input_hash,risk_sha256=digest(risk),asset_ids=declared,
            no_entry_cost_inputs=costs,cash_quote_sha256=digest(quote),cash_return=carry,
            covariance_status="NOT_REQUIRED_ZERO_EQUITY",horizon=p["horizon"])
        return dict(status="RESEARCH_PROPOSAL",proposed_weights={},cash=1.0,
            regime=risk["regime"],intent="NO_ENTRY_HOLD_CASH",model_state_kind=kind,
            carried_position_weights=current,decision_clock=clock,exception_exposure=0,
            exit_reviews=[],exception_reviews=[],comparison_inputs=frozen,
            comparison_inputs_sha256=digest(frozen),
            comparisons={name:dict(weights={},incremental_cost_fraction=0,objective=-carry)
                         for name in ("CONTROL","COST_AWARE_LONG_ONLY")},
            accepted_target=False,orders_generated=False,execution_ready=False,
            realized_integer_fills=False,performance_claimed=False,
            turnover_cost_scope="PLANNED_TARGET_CHANGE_NOT_REALIZED_TURNOVER_OR_NAV")
    ids=[r["asset_id"] for r in accepted];n=len(ids)
    returns=np.asarray([[number(x) for x in r.get("daily_log_returns",[])] for r in accepted],dtype=float)
    require(returns.shape==(n,60) and np.isfinite(returns).all(),"stock_common_covariance_history")
    require(all(r.get("return_history_sessions")==list(grid(cutoff))[-60:] for r in accepted),
            "stock_covariance_session_alignment")
    require(np.all(np.std(returns,axis=1)>1e-12),"stock_undefined_covariance")
    covariance=LedoitWolf().fit(returns.T).covariance_*clock["covariance_scale_sessions"]
    costs=[_stock_cost(r,p["cost_bps_per_side"]) for r in accepted]
    mu=np.asarray([v[0] for v in costs]);side=np.asarray([v[1] for v in costs])
    old=np.asarray([current.get(a,0) for a in ids]);lo=np.asarray(lower);hi=np.asarray(upper)
    for audit in exit_audit:
        if "replacement_asset_id" in audit:
            require(audit["replacement_asset_id"] in ids,"stock_replacement_not_entry_eligible")
            j=ids.index(audit["replacement_asset_id"])
            lo[j]=max(lo[j],old[j]+audit["prior_weight"]-audit["max_weight"])
    quote=review.get("cash_carry")
    cash_return=_stock_cash_return(quote,clock,cutoff,policy,artifact_resolver)
    exposures=[lookthrough({a:1.0},assets,holdings,cutoff,policy) for a in ids]
    leaf_ids=sorted({a for e in exposures for a in e["security_exposure"]})
    groups=sorted({g for e in exposures for g in e["risk_group_exposure"]})
    matrix=[np.ones(n)]
    limits=[gross_cap]
    for a in leaf_ids:
        matrix.append(np.asarray([e["security_exposure"].get(a,0) for e in exposures]));limits.append(cap)
    for g in groups:
        matrix.append(np.asarray([e["risk_group_exposure"].get(g,0) for e in exposures]))
        limits.append(number(risk["risk_group_limits"].get(g),0,1))
    # A named exception vehicle counts in full even if it expands to bond
    # constituents. Indirect named holdings are added once for other vehicles.
    alt=np.asarray([1.0 if assets[aid]["symbol"] in EXCEPTION_SYMBOLS else
        sum(w for a,w in e["security_exposure"].items() if assets[a]["symbol"] in EXCEPTION_SYMBOLS)
        for aid,e in zip(ids,exposures)])
    matrix.append(alt);limits.append(.20)
    # Existing maximum pair correlation remains a hard entry constraint.
    corr=np.corrcoef(returns) if n>1 else np.ones((1,1))
    for i in range(n):
        for j in range(i):
            if abs(corr[i,j])>max_corr:
                require(not (lo[i]>0 and lo[j]>0),"stock_carried_correlation_review_required")
                loser=j if lo[i]>0 or (lo[j]==0 and mu[i]>mu[j]) else i
                hi[loser]=lo[loser]
    matrix=np.asarray(matrix);limits=np.asarray(limits)
    require(np.all(matrix@lo<=limits+1e-9) and np.all(lo<=hi+1e-9),"stock_winner_hard_limits_require_review")
    def objective(w):
        return float(-(mu@w+cash_return*(1-sum(w))-side@np.abs(w-old))+
                     p["risk_aversion"]*(w@covariance@w)/2)
    constraint={"type":"ineq","fun":lambda w:limits-matrix@w}
    def checked_solution(result,minimum,maximum,reason):
        require(result.success,reason)
        values=np.asarray(result.x,dtype=float)
        require(values.shape==(n,) and np.isfinite(values).all() and
                np.all(values>=minimum-1e-8) and np.all(values<=maximum+1e-8) and
                np.all(matrix@values<=limits+1e-8),reason)
        return values
    # Same frozen moments, costs, cash and incumbent floors for both arms.
    control=lo.copy()
    # Reuse existing propose's alpha/confidence/drawdown score, inside this
    # explicit stock scope and the same reviewed constraints as the challenger.
    # This is the multi_asset Control, NOT native Main/Con or ALPHA15/5.
    raw=np.asarray([max(0,r["expected_alpha_12m"]*r["signal_confidence"]*r["thesis_confidence"]/
        (r["expected_drawdown"]*number(risk["risk_multipliers"].get(assets[r["asset_id"]]["asset_class"]),1)))
        for r in accepted])
    budget=max(0,gross_cap-sum(lo))
    total=float(sum(raw))
    for i in sorted(range(n),key=lambda i:(-raw[i],ids[i])):
        if total<=0 or mu[i]-cash_return-side[i]<=0: continue
        room=min(hi[i]-control[i],budget*raw[i]/total)
        for line,limit in zip(matrix,limits):
            if line[i]>0:room=min(room,max(0,(limit-line@control)/line[i]))
        control[i]+=max(0,room)
    solved=minimize(objective,control,method="SLSQP",bounds=list(zip(lo,hi)),constraints=[constraint],
                    options={"ftol":1e-10,"maxiter":300})
    optimized=checked_solution(solved,lo,hi,"stock_optimizer_constraint_violation")
    chosen=control if p["allocator"]=="CONTROL" else optimized
    exception_audit=[]
    if any(chosen[i]>old[i]+1e-9 and alt[i]>0 for i in range(n)):
        no_alt_lo=lo.copy();no_alt_hi=hi.copy()
        no_alt_lo[alt>0]=0;no_alt_hi[alt>0]=0
        baseline=minimize(objective,no_alt_lo,method="SLSQP",bounds=list(zip(no_alt_lo,no_alt_hi)),
            constraints=[constraint],options={"ftol":1e-10,"maxiter":300})
        checked_solution(baseline,no_alt_lo,no_alt_hi,"stock_exception_counterfactual_failed")
        for i,aid in enumerate(ids):
            if not (chosen[i]>old[i]+1e-9 and alt[i]>0):continue
            proof=alternatives.get(aid)
            require(proof is not None,"stock_indirect_exception_original_required")
            if proof["basis"]=="OPPORTUNITY":
                require(objective(chosen)<objective(baseline.x)-1e-9,"stock_exception_no_net_objective_improvement")
                evidence=dict(objective_improvement=objective(baseline.x)-objective(chosen))
            else:
                joint=proof.get("joint_downside_recovery")
                require(type(joint) is dict,"stock_special_risk_joint_evidence_missing")
                pinned(joint,policy,"risk",cutoff)
                require(joint.get("feature_sha256")==input_hash and joint.get("asset_ids")==ids and
                        joint.get("horizon")==p["horizon"],"stock_special_risk_joint_input_mismatch")
                scenarios=np.asarray(joint.get("asset_returns"),dtype=float)
                carry=np.asarray(joint.get("cash_returns"),dtype=float)
                recovery=np.asarray(joint.get("recovery_returns"),dtype=float)
                require(scenarios.ndim==2 and scenarios.shape[1]==n and scenarios.shape[0]>=2 and
                        carry.shape==(scenarios.shape[0],) and recovery.shape==(n,) and
                        np.isfinite(scenarios).all() and np.isfinite(carry).all() and np.isfinite(recovery).all(),
                        "stock_special_risk_joint_scenarios")
                def outcomes(w):return scenarios@w+carry*(1-sum(w))-side@np.abs(w-old)
                recovery_cash=number(joint.get("recovery_cash_return"),-1)
                def recovered(w):return recovery@w+recovery_cash*(1-sum(w))-side@np.abs(w-old)
                improvement=float(min(outcomes(chosen))-min(outcomes(baseline.x)))
                require(improvement>1e-9 and recovered(chosen)>=recovered(baseline.x)-1e-9,
                        "stock_special_risk_not_better_than_cash")
                evidence=dict(worst_case_net_improvement=improvement,recovery_noninferior=True,
                              joint_original_sha256=digest(joint))
            exception_audit.append(dict(asset_id=aid,original_review_sha256=digest(proof),
                release_condition=proof["release_condition"],basis=proof["basis"],**evidence))
    intent="REVIEW_REBALANCE"
    if not clock["scheduled_due"] and not exit_audit:
        chosen=old
        intent="HOLD_UNTIL_SCHEDULED_REVIEW"
    weights={a:float(w) for a,w in zip(ids,chosen) if w>1e-10}
    if not weights:
        known_model_cash_decision()
    frozen=dict(asset_ids=ids,expected_return_horizon="12_CALENDAR_MONTHS",gross_er=mu.tolist(),
        embedded_costs=[r["portfolio_cost_basis"]["embedded_cost_fraction"] for r in accepted],
        covariance=covariance.tolist(),cash_return=cash_return,side_cost=side.tolist(),
        lower=lo.tolist(),upper=hi.tolist(),current_weights=old.tolist(),risk_aversion=p["risk_aversion"],
        feature_sha256=input_hash,risk_sha256=digest(risk),cash_quote_sha256=digest(quote))
    return dict(status="RESEARCH_PROPOSAL",regime=risk["regime"],proposed_weights=weights,
        cash=1-sum(weights.values()),carried_position_weights=current,
        accepted_target=False,orders_generated=False,execution_ready=False,
        decision_clock=clock,exception_exposure=float(alt@chosen),exception_reviews=exception_audit,exit_reviews=exit_audit,
        comparison_inputs_sha256=digest(frozen),comparison_inputs=frozen,
        comparisons={name:dict(weights={a:float(w) for a,w in zip(ids,values) if w>1e-10},
            objective=objective(values),incremental_cost_fraction=float(side@np.abs(values-old)))
            for name,values in (("CONTROL",control),("COST_AWARE_LONG_ONLY",optimized))},
        allocator=p["allocator"],intent=intent,
        control_identity="EXISTING_MULTI_ASSET_SCORE_WITH_STOCK_SCOPE_AND_SHARED_HARD_LIMITS",
        reduction_basis="PINNED_TYPED_EXIT_ONLY",
        realized_integer_fills=False,performance_claimed=False,
        turnover_cost_scope="PLANNED_TARGET_CHANGE_NOT_REALIZED_TURNOVER_OR_NAV")

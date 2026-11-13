"""Discovery -> reviewed thesis/ER -> separate risk proposal, never orders."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import math

from .contracts import (ContractError, ER_HORIZONS, HORIZONS, day, digest, identifier,
                        load_json, metadata, number, pinned, registry_rows, require, stamp, unique)
from .prices import BASE_RS_WEIGHTS, admit_prices, cross_section, grid, one_asset
from .decisions import (COMPONENTS, classify, evaluation, event_memory, lookthrough, propose,
                        stock_decision_scope, stock_research_profile, stock_er_suffix)
from .fundamentals import receipt_blockers


def feature_identity(payload, registry):
    # Evaluator and risk pins bind exactly the same input snapshot without a cycle.
    value={"registry":registry,"as_of":payload["as_of"],
           **{k:payload.get(k,[]) for k in ("prices","metrics","events","base_equity_ids","collection_receipts")}}
    if "requested_security_ids" in payload:
        value["requested_security_ids"]=payload["requested_security_ids"]
    return digest(value)


def a3_evaluation_inputs(payload, assets, policy, cutoff, session, feature_hash,
                         feature_time, artifact_resolver):
    """Replay original A3 references, then validate original ER without repair."""
    from research.a2_research_intake_v1 import MemoryArtifacts
    from research.candidate_registry_v1 import build_reference_index, ReferenceIndexError
    requested=payload.get("requested_security_ids")
    entries=payload.get("a3_reference_entries",[])
    require(type(requested) is list and 0<len(requested)<=1500,"a3_requested_universe")
    for aid in requested: identifier(aid)
    require(len(requested)==len(set(requested)),"a3_duplicate_requested_security")
    require(type(entries) is list and len(entries)<=1000,"a3_reference_entries")
    require(all(type(e) is dict and e.get("asset_id") in requested for e in entries),
            "a3_unrequested_reference")
    require(not entries or type(artifact_resolver) is MemoryArtifacts,"a3_memory_resolver_required")
    memory=artifact_resolver if entries else MemoryArtifacts({})
    try:
        index=build_reference_index(entries,cutoff=cutoff,artifact_resolver=memory.read)
    except ReferenceIndexError:
        raise ContractError("a3_reference_set_refused") from None
    by_asset={r["asset_id"]:r for r in index["records"]}
    existing=unique(payload.get("evaluations",[]),"asset_id")
    require(not set(existing).intersection(requested),"a3_duplicate_evaluation_input")
    originals,coverage,markets=[],[],{}
    for aid in requested:
        record=dict(asset_id=aid,status="BLOCKED",blocker=None,original_er_ref=None,
                    runtime_evaluation_admitted=False)
        coverage.append(record)
        reference=by_asset.get(aid)
        if reference is not None:
            record.update(consumption_blockers=list(reference["consumption_blockers"]),
                review_authentication_status=reference["review_authentication_status"],
                domain_admission_status=reference["domain_admission_status"])
        if aid not in assets:
            record["blocker"]="REGISTRY_ASSET_UNMAPPED"
            continue
        if reference is None:
            record["blocker"]="MISSING_A3_REFERENCE"
            continue
        if reference["reference_status"]!="A3_REFERENCE_REPLAY_VERIFIED":
            record.update(blocker="A3_REPLAY_BLOCKED",reference_blockers=reference["blockers"])
            continue
        ref=reference["validated_er_ref"]
        record["original_er_ref"]=ref
        if ref is None:
            record["blocker"]="VALIDATED_ER_NOT_LINKED"
            continue
        try:
            require(reference["declared_expiry_state"]=="UNEXPIRED","a3_reference_expired_or_unknown")
            info=reference["metadata"]
            require(info["market_session_date"]==session,"a3_market_session_mismatch")
            original=load_json(memory.read(ref["artifact_id"],ref["sha256"]))
            require(original.get("issuer_id")==reference["issuer_id"],"a3_er_issuer_identity")
            require(original.get("thesis_status")==info["thesis_status"],"a3_er_thesis_mismatch")
            require(info["currency"]==assets[aid]["currency"],"a3_market_currency_mismatch")
            mref=reference["upstream_artifact_refs"]["market_valuation"]
            market=load_json(memory.read(mref["artifact_id"],mref["sha256"]))
            evaluation(original,assets[aid],cutoff,policy,feature_hash,feature_time)
        except (ContractError,KeyError,ValueError) as exc:
            record.update(blocker="ORIGINAL_ER_EVALUATION_CONTRACT_BLOCKED",contract_blocker=str(exc))
            continue
        # Preserve the complete original model/scenario/cost/clock object. Its
        # independent policy digest is checked again by normal runtime admission.
        originals.append(original)
        markets[aid]=market
        record["market_valuation_ref"]=mref
        record["status"]="ORIGINAL_ER_CONTRACT_VERIFIED_RESEARCH_ONLY"
        record["blocker"]="CURRENT_A3_REVIEW_ADMISSION_REQUIRED"
    return originals,dict(requested_security_ids=list(requested),records=coverage,
        requested_count=len(requested),original_er_verified_count=len(originals),
        held_count=len(requested),reference_index_sha256=index["index_sha256"],
        canonical_write_performed=False,source_admission_granted=False,
        historical_pit_certified=False,portfolio_write_allowed=False),markets


def feature_availability(payload):
    """Latest availability among the actual observations bound into feature_identity."""
    rows=[r for kind in ("prices","metrics","events") for r in payload.get(kind,[])]
    require(bool(rows),"missing_feature_inputs")
    return max(stamp(r.get("available_at")) for r in rows).isoformat()


def metric_rows(rows, cutoff, policy):
    result=[]
    seen=set()
    for row in rows:
        key=(row.get("subject_id"),row.get("metric"),row.get("observed_at"),row.get("available_at"))
        require(key not in seen,"duplicate_metric")
        seen.add(key)
        try:
            metadata(row,cutoff,policy,"metric")
            identifier(row.get("subject_id"))
            spec=policy["metric_units"].get(row.get("metric"))
            require(spec is not None and row.get("unit") in spec,"metric_unit")
            if row.get("unit")=="TOKEN":
                require(row.get("subject_id") in {"BTC","ETH"}
                        and row.get("currency")==row["subject_id"],"metric_token_currency")
            number(row.get("value"))
            result.append({**row,"admission":"OBSERVED"})
        except ContractError as exc:
            result.append({**row,"value":None,"admission":"BLOCKED","reason":str(exc)})
    return result


def historical_readiness(payload):
    prices=payload.get("prices",[])
    blockers=[]
    if not prices: blockers.append("missing_price_history")
    if any(r.get("evidence_kind")!="PIT_ARCHIVE" for r in prices):
        blockers.append("forward_capture_not_historical_pit")
    if not payload.get("historical_universe_receipt"): blockers.append("missing_pit_universe")
    # Receipt strings alone do not authenticate kernel/cost/corporate-action evidence.
    blockers.append("canonical_replay_preflight_not_bound")
    return {"status":"BLOCKED", "blockers":blockers,
            "comparisons":["A_EQUITY_ONLY","B_EQUITY_COMMODITY","C_EQUITY_COMMODITY_EQUITY","D_EQUITY_COMMODITY_CRYPTO","E_FULL"],
            "ablations":["RS","FUNDAMENTAL","NEWS","RS_FUNDAMENTAL","RS_FUNDAMENTAL_NEWS","FULL"],
            "net_cagr":None,"mdd":None,"fullrun_executed":False}


def run(payload, registry, policy, *, artifact_resolver=None, review_root=None, code_sha=None):
    require(payload.get("schema")=="multi-asset-input-v1","input_schema")
    require(policy.get("schema")=="multi-asset-policy-v1","policy_schema")
    require(policy.get("baseline_rs_weights")==BASE_RS_WEIGHTS,"unsupported_rs_baseline")
    require(policy.get("baseline_commodity_weights")==COMPONENTS,"unsupported_commodity_baseline")
    stock_mode=policy.get("stock_cash_research",{}).get("enabled") is True
    er_suffix=stock_er_suffix(policy) if stock_mode else "12m"
    cutoff=payload["as_of"]
    stamp(cutoff)
    underlyings,assets=registry_rows(registry)
    sessions=grid(cutoff)
    as_of=list(sessions)[-1]
    identity=feature_identity(payload,registry)
    try:
        feature_time=feature_availability(payload)
    except (ContractError,ValueError):
        feature_time=None
    base_ids=payload.get("base_equity_ids",[])
    require(isinstance(base_ids,list) and len(base_ids)==len(set(base_ids)),"base_universe_identity")
    a3_scope="requested_security_ids" in payload or "a3_reference_entries" in payload
    if a3_scope:
        requested=payload.get("requested_security_ids")
        require(type(requested) is list and 0<len(requested)<=1500,"a3_requested_universe")
        for aid in requested: identifier(aid)
        require(len(requested)==len(set(requested)),"a3_duplicate_requested_security")
    unresolved_base=[]
    for aid in base_ids:
        if (a3_scope or stock_mode) and aid not in assets:
            identifier(aid)
            unresolved_base.append(aid)
        elif stock_mode:
            require(aid in assets,"missing_base_equity")
        else:
            require(aid in assets and assets[aid]["asset_class"] in {"US_EQUITY","COMMODITY_EQUITY","CRYPTO_EQUITY"},"missing_base_equity")
    base_pin=payload.get("base_universe_receipt")
    complete_base=False
    scoped_base_membership=False
    base_blockers=[]
    try:
        require(bool(base_ids) and base_pin is not None,"missing_base_universe")
        require(not unresolved_base,"unmapped_base_equity")
        if a3_scope:
            require(set(payload.get("requested_security_ids",[]))==set(base_ids),"a3_requested_base_universe_mismatch")
        pinned(base_pin,policy,"base_universe",cutoff)
        require(base_pin.get("asset_ids")==sorted(base_ids) and base_pin.get("as_of")==as_of,"base_universe_receipt_mismatch")
        complete_base=True
    except (ContractError,KeyError,ValueError) as exc:
        base_blockers.append(str(exc))
    if stock_mode:
        try:
            require(bool(base_ids) and base_pin is not None,"missing_base_universe")
            pinned(base_pin,policy,"base_universe",cutoff)
            require(base_pin.get("asset_ids")==sorted(base_ids) and base_pin.get("as_of")==as_of,
                    "base_universe_receipt_mismatch")
            scoped_base_membership=True
        except (ContractError,KeyError,ValueError) as exc:
            base_blockers.append("stock_membership:"+str(exc))
    groups=defaultdict(list)
    for r in payload.get("prices",[]):
        require(r.get("asset_id") in assets,"unregistered_price_asset")
        groups[(r["asset_id"],r.get("clock"))].append(r)
    a3_originals,a3_coverage,a3_markets=[],None,{}
    if a3_scope:
        a3_originals,a3_coverage,a3_markets=a3_evaluation_inputs(payload,assets,policy,cutoff,as_of,
            identity,feature_time,artifact_resolver)
    by_eval=unique(payload.get("evaluations",[]),"asset_id")
    a3_candidates={r["asset_id"]:r for r in a3_originals}
    a3_records={r["asset_id"]:r for r in a3_coverage["records"]} if a3_coverage else {}
    current_review=None
    if a3_scope and payload.get("current_a3_review") is not None:
        try:
            from tools.run_agent_board import current_a3_reference_admission
            binding=payload["current_a3_review"]
            current_review=current_a3_reference_admission(binding,policy,review_root,stamp(cutoff),
                code_sha,payload["requested_security_ids"],payload.get("a3_reference_entries",[]),
                identity,payload.get("risk"))
            a3_coverage["current_review"]=current_review
        except (ContractError,OSError,KeyError,ValueError,TypeError) as exc:
            a3_coverage["current_review"]={"status":"BLOCKED","reason":str(exc)
                if isinstance(exc,ContractError) else type(exc).__name__}
    require(set(by_eval)<=set(assets),"unknown_evaluation_asset")
    position_rows=payload.get("positions",[])
    model_positions=payload.get("position_book_kind")=="MODEL"
    incumbents=(current_review.get("model_incumbents") or current_review.get("model_parent_lineage")) if current_review else None
    require(incumbents is None or model_positions,"model_incumbents_kind_required")
    model_input_blocker=None
    def verified_model_rows():
        require(a3_scope and current_review is not None and
                current_review.get("status")=="CURRENT_REFERENCE_REVIEW_VERIFIED" and
                incumbents is not None,"current_model_incumbents_required")
        require(digest(payload.get("model_identity"))==digest(incumbents["model_identity"]),
                "model_incumbents_identity_mismatch")
        require("position_receipt" not in payload,"model_position_receipt_is_not_acceptance")
        if "cash_weight" in payload:
            number(payload["cash_weight"],0,1)
            require(digest(payload["cash_weight"])==digest(incumbents["cash_weight"]),
                    "model_incumbents_cash_mismatch")
        verified_rows=[dict(asset_id=aid,weight=weight) for aid,weight in
                       sorted(incumbents["current_weights"].items())]
        if "positions" in payload:
            require(type(position_rows) is list and all(type(r) is dict and
                    set(r)=={"asset_id","weight"} for r in position_rows),"model_position_shape")
            require(digest(sorted(position_rows,key=lambda r:r["asset_id"]))==digest(verified_rows),
                    "model_incumbents_weights_mismatch")
        return verified_rows
    if model_positions:
        try:
            position_rows=verified_model_rows()
        except (ContractError,KeyError,ValueError,TypeError) as exc:
            if not stock_mode:raise
            model_input_blocker=str(exc)
            position_rows=[]
            incumbents=None
    require(not position_rows or payload.get("position_book_kind") in
            {"ACTUAL_BROKER","APPROVED_TARGET","PAPER","MODEL"},"position_book_kind")
    if position_rows and not model_positions:
        receipt=payload.get("position_receipt")
        require(receipt is not None,"unreviewed_position_book")
        pinned(receipt,policy,"positions",cutoff)
        require(receipt.get("positions_sha256")==digest(position_rows) and receipt.get("as_of")==as_of
                and receipt.get("book_kind")==payload["position_book_kind"],"position_receipt_mismatch")
        require(stamp(receipt["available_at"])<=stamp(cutoff),"future_position_book")
    positions=unique(position_rows,"asset_id")
    if not stock_mode:require(set(positions)<=set(assets),"unknown_position")
    for r in positions.values(): number(r.get("weight"),0,1)
    require(sum(r["weight"] for r in positions.values())<=1+1e-9,"position_weight_sum")
    stock_membership_blocker=None
    if stock_mode and a3_scope:
        held={aid for aid,w in (incumbents or {}).get("current_weights",{}).items() if w>0}
        exceptions={aid for aid,a in assets.items() if a["symbol"] in {"GLDM","SHY","IEF","TLT"}
                    and a["identity_verified"] is True}
        requested_scope=set(payload["requested_security_ids"])
        declared_scope=set(payload.get("risk",{}).get("stock_cash_allocation",{}).get("decision_asset_ids",[]))
        if not (requested_scope==declared_scope and requested_scope<=set(base_ids)|exceptions|held
                and held<=requested_scope):
            stock_membership_blocker="stock_a0_a3_scope_or_verified_model_holdings_mismatch"
    admitted,errors={},{}
    for aid,a in assets.items():
        try:
            admitted[aid]=admit_prices(groups[(aid,"NYSE_CLOSE")],a,cutoff,policy,sessions)
        except (ContractError,ValueError) as exc:
            errors[aid]=str(exc)
    benchmark=policy["benchmark_id"]
    require(benchmark in assets,"benchmark_registry")
    events=event_memory(payload.get("events",[]),assets,cutoff,policy)
    metrics=metric_rows(payload.get("metrics",[]),cutoff,policy)
    fundamental_collection_blockers=receipt_blockers(metrics,payload.get("collection_receipts",[]))
    fundamental_collection_blocked=bool(fundamental_collection_blockers)
    for metric in metrics:
        require(metric["subject_id"] in assets or metric["subject_id"] in underlyings,"unknown_metric_subject")
    rows=[]
    for aid,a in assets.items():
        if aid==benchmark: continue
        row={"asset_id":aid,"symbol":a["symbol"],"asset_class":a["asset_class"],"underlying":a["underlying"],
             "as_of":as_of,"price":None,"RS_composite":None,"fundamental_score":None,"news_score":None,
             "downside_risk":None,"rank":None,"discovery_rank":None,"thesis_id":None,
             "rank_change_5d":None,"rank_change_20d":None,"score_change_5d":None,"score_change_20d":None,
             "portfolio_status":"BLOCKED","data_quality":"BLOCKED","leadership_state":"UNKNOWN",
             "liquidity_pass":None,"blockers":[],**{f"expected_return_{h}":None for h in ER_HORIZONS},
             **{f"{prefix}{h}":None for prefix in ("ret","RS") for h in HORIZONS}}
        features=None
        if aid in admitted and benchmark in admitted:
            try:
                features=one_asset(admitted[aid],admitted[benchmark],cutoff,benchmark,sessions)
            except (ContractError,ValueError) as exc:
                row["blockers"].append(str(exc))
        if features is not None:
            row.update(features)
            row["data_quality"]="PRICE_OBSERVED_RESEARCH_ONLY" if features["return_basis"]==features["benchmark_return_basis"]=="TOTAL_RETURN" else "PRICE_PROXY_RESEARCH_ONLY"
            hist=[admitted[aid][s] for s in list(sessions)[-20:]]
            if all(r.get("volume") is not None for r in hist):
                row["dollar_volume_20d"]=sum(r["price"]*r["volume"] for r in hist)/20
                row["liquidity_pass"]=row["dollar_volume_20d"]>=policy["min_dollar_volume_20d"]
        elif not row["blockers"]:
            row["blockers"].append(errors.get(aid,"benchmark_unavailable"))
        ev=None
        if aid in by_eval or aid in a3_candidates:
            try:
                require(row["data_quality"]=="PRICE_OBSERVED_RESEARCH_ONLY","price_proxy_or_missing_cannot_admit_er")
                require(not fundamental_collection_blocked,"fundamental_collection_incomplete")
                require(all(metric["admission"]=="OBSERVED" for metric in metrics),"feature_metric_not_admitted")
                if aid in a3_markets:
                    market=a3_markets[aid]
                    require(market["return_basis"]==features["return_basis"],"a3_market_return_basis_mismatch")
                    require(math.isclose(number(market["price"]),row["price"],rel_tol=1e-9,abs_tol=1e-9),
                            "a3_market_price_mismatch")
                    for h in HORIZONS:
                        require(math.isclose(number(market[f"return_{h}d"]),features[f"ret{h}"],rel_tol=1e-9,abs_tol=1e-9)
                                and math.isclose(number(market[f"rs_{h}d"]),features[f"RS{h}"],rel_tol=1e-9,abs_tol=1e-9),
                                "a3_market_feature_mismatch")
                checked=evaluation(a3_candidates[aid] if aid in a3_candidates else by_eval[aid],
                                   a,cutoff,policy,identity,feature_time)
                if aid in a3_candidates:
                    a3_records[aid]["original_runtime_contract_verified"]=True
                    require(current_review is not None,"a3_current_reference_admission_required")
                    a3_records[aid].update(runtime_evaluation_admitted=True,
                        current_reference_review_status=current_review["status"],
                        status="CURRENT_REVIEWED_ORIGINAL_ER_ADMITTED",blocker=None)
                ev=checked
                fields={"fundamental_score","expected_alpha_12m","expected_drawdown","downside_probability","signal_confidence","thesis_confidence","thesis_id","thesis_status","valuation_acceptable","scenarios","model_id","validation_sha256"}
                fields.update("expected_return_"+h for h in ER_HORIZONS)
                if er_suffix=="63s":
                    fields.update({"expected_return_63s","expected_alpha_63s","benchmark_expected_return_63s",
                        "schema","horizon","horizon_unit","horizon_count","forecast_clock","cost_horizon","downside_horizon"})
                row.update({k:v for k,v in ev.items() if k in fields})
                if policy.get("stock_cash_research",{}).get("enabled") is True:
                    original_evaluation=a3_candidates[aid] if aid in a3_candidates else by_eval[aid]
                    row.update(evaluation_sha256=digest(original_evaluation),net_of_costs=ev["net_of_costs"],
                        cost_assumptions=ev["cost_assumptions"],
                        portfolio_cost_basis=ev.get("portfolio_cost_basis"),
                        hold_exit_evidence=ev.get("hold_exit_evidence"),
                        return_history_sessions=list(sessions)[-60:])
                row["downside_risk"]=ev["expected_drawdown"]
            except (ContractError,KeyError,ValueError) as exc:
                row["blockers"].append("evaluation:"+str(exc))
        else:
            row["blockers"].append("missing_reviewed_evaluation")
        row["leadership_state"],row["portfolio_status"]=classify(features,ev,aid in positions and positions[aid]["weight"]>0)
        if row["liquidity_pass"] is False:
            row["portfolio_status"]="BLOCKED"
            row["blockers"].append("liquidity_failed")
        if ev and features:
            row["risk_adjusted_expected_alpha"]=ev["expected_alpha_"+er_suffix]/ev["expected_drawdown"]
        rows.append(row)
    if stock_mode:
        # Keep unmapped names as UNKNOWN; they are not registered/tradable merely
        # because a canonical tracked roster or request mentioned their IDs.
        for aid in sorted((set(unresolved_base)|set(payload.get("requested_security_ids",[]))|set(positions))-set(assets)):
            rows.append(dict(asset_id=aid,symbol=None,asset_class="UNKNOWN",price=None,rank=None,
                discovery_rank=None,RS_composite=None,rank_change_5d=None,rank_change_20d=None,
                score_change_5d=None,score_change_20d=None,
                data_quality="BLOCKED",portfolio_status="BLOCKED",leadership_state="UNKNOWN",
                evaluation_sha256=None,blockers=["UNMAPPED_SECURITY_IDENTITY"],as_of=as_of,
                **{f"expected_return_{h}":None for h in ER_HORIZONS},
                **{f"{prefix}{h}":None for prefix in ("ret","RS") for h in HORIZONS}))
    normalization=cross_section(rows)
    # Expected-return rank and discovery rank are separate columns.
    ranking=sorted([r for r in rows if "risk_adjusted_expected_alpha" in r and r["portfolio_status"] in {"CANDIDATE","HOLD","WATCH"}],
                   key=lambda r:(-r["risk_adjusted_expected_alpha"],r["asset_id"]))
    if a3_coverage is not None:
        a3_coverage["held_count"]=sum(not r["runtime_evaluation_admitted"] for r in a3_records.values())
    a3_complete=a3_coverage is None or a3_coverage["held_count"]==0
    global_ranking_ready=complete_base and a3_complete and bool(ranking) and all(
        r["data_quality"]=="PRICE_OBSERVED_RESEARCH_ONLY" and "risk_adjusted_expected_alpha" in r for r in rows)
    if global_ranking_ready:
        for i,r in enumerate(ranking,1): r["rank"]=i
    stock_scope=None
    if stock_mode:
        try:
            stock_scope=stock_decision_scope(rows,assets,{aid:r["weight"] for aid,r in positions.items()},
                events,cutoff,policy,payload.get("risk",{}).get("stock_cash_allocation",{}).get("decision_asset_ids"))
        except (ContractError,KeyError,ValueError,TypeError) as exc:
            stock_scope=dict(status="BLOCKED",reason=str(exc),asset_ids=[],records=[],
                             full_roster_count=len(rows),global_ranking_certified=False)
    proposal={"status":"BLOCKED","reasons":["missing_reviewed_risk_packet"],"proposed_weights":None,"orders_generated":False}
    if payload.get("risk") is not None:
        try:
            if stock_mode:
                require(model_input_blocker is None,model_input_blocker or "stock_model_comparison_unknown")
                require(scoped_base_membership,"stock_base_membership_unverified")
                require(stock_membership_blocker is None,stock_membership_blocker or "stock_scope_unverified")
                require(stock_scope["numeric_scope_status"]=="SCOPED_INPUTS_OBSERVED","stock_decision_scope_incomplete")
                if a3_scope: require(current_review is not None,"a3_current_reference_admission_required")
                allocation=payload["risk"].get("stock_cash_allocation",{})
                require(type(allocation) is dict,"stock_reviewed_allocation_required")
                optional={r["asset_id"] for r in allocation.get("exception_reviews",[])}
                selected_scope=set(stock_scope["decision_asset_ids"])
                require(optional<=selected_scope and optional<=set(assets),"stock_exception_security_unregistered_or_unreviewed")
                proposal_rows=[r for r in rows if r["asset_id"] in selected_scope]
            else:
                require(complete_base,"incomplete_base_universe")
                require(a3_complete,"incomplete_a3_reference_coverage")
                require(all(r["data_quality"]=="PRICE_OBSERVED_RESEARCH_ONLY" and "risk_adjusted_expected_alpha" in r for r in rows if r["asset_id"] in base_ids),"incomplete_equity_comparison")
                require(global_ranking_ready,"incomplete_cross_asset_comparison")
                proposal_rows=rows
            require(feature_time is not None and stamp(payload["risk"].get("observed_at"))>=stamp(feature_time),"risk_predates_feature_inputs")
            proposal=propose(proposal_rows,assets,payload["risk"],payload.get("holdings",{}),cutoff,policy,identity,
                             {aid:r["weight"] for aid,r in positions.items()},
                             **({"decision_events":payload.get("events",[]),"artifact_resolver":artifact_resolver,
                                 "model_review":current_review}
                                if stock_mode else {}))
            if stock_mode:
                proposal.update(scope="EXPLICIT_STOCK_REVIEW_SCOPE",global_ranking_ready=global_ranking_ready,
                    decision_scope_asset_ids=stock_scope["decision_asset_ids"])
        except (ContractError,KeyError,ValueError,TypeError) as exc:
            proposal={"status":"BLOCKED","reasons":[str(exc)],"proposed_weights":None,"orders_generated":False}
    observed_exposure={"status":"NOT_SUPPLIED","book_kind":None}
    if positions or model_positions:
        try:
            observed_exposure={"status":"RESEARCH_MEASUREMENT","book_kind":payload["position_book_kind"],
                              **lookthrough({a:r["weight"] for a,r in positions.items()},assets,payload.get("holdings",{}),cutoff,policy)}
        except (ContractError,KeyError,ValueError) as exc:
            observed_exposure={"status":"BLOCKED","reason":str(exc),"book_kind":payload["position_book_kind"]}
        if model_positions and incumbents is not None:
            observed_exposure.update(cash_weight=incumbents["cash_weight"],comparison_allocation_only=True)
    crypto=[]
    for aid,a in assets.items():
        if a["asset_class"]!="CRYPTO":continue
        item={"asset_id":aid,"utc_calendar":None,"nyse_snapshot":next((r for r in rows if r["asset_id"]==aid),None),"status":"BLOCKED",
              "metrics":[r for r in metrics if r["subject_id"]==a["underlying"]],
              "network_score":None,"network_score_status":"NO_VALIDATED_NETWORK_MODEL"}
        try:
            series=admit_prices(groups[(aid,"UTC_DAY")],a,cutoff,policy,sessions,"UTC_DAY")
            keys=sorted(series)
            end=(stamp(cutoff)-timedelta(days=1)).date().isoformat()
            require(keys[-1]==end,"crypto_stale")
            item["utc_calendar"]={"as_of":end,"clock":"UTC_DAY","price":series[end]["price"],
                "return_basis":series[end]["return_basis"],
                **{f"ret{h}_calendar_days":series[end]["total_return_index"]/series[keys[-1-h]]["total_return_index"]-1 for h in HORIZONS}}
            item["utc_calendar"]["RS_BTC"] = None
            item["utc_calendar"]["BTC_return_basis"] = None
            if aid=="CRYPTO:BTC-USD":
                item["utc_calendar"]["BTC_return_basis"]=series[end]["return_basis"]
                item["utc_calendar"]["RS_BTC"]={str(h):0.0 for h in HORIZONS}
            else:
                btc_id="CRYPTO:BTC-USD"
                if btc_id in assets:
                    try:
                        btc=admit_prices(groups[(btc_id,"UTC_DAY")],assets[btc_id],cutoff,policy,sessions,"UTC_DAY")
                        item["utc_calendar"]["BTC_return_basis"]=btc[end]["return_basis"]
                        require(series[end]["return_basis"]==btc[end]["return_basis"],"crypto_benchmark_return_basis_mismatch")
                        item["utc_calendar"]["RS_BTC"]={str(h):math.log(series[end]["total_return_index"]/series[keys[-1-h]]["total_return_index"])-math.log(btc[end]["total_return_index"]/btc[keys[-1-h]]["total_return_index"]) for h in HORIZONS}
                    except (ContractError,ValueError) as exc:item["utc_calendar"]["RS_BTC_blocker"]=str(exc)
            item["status"]="UTC_ONLY" if aid not in admitted else "BOTH_CLOCKS"
        except (ContractError,ValueError) as exc:item["reason"]=str(exc)
        crypto.append(item)
    commodity=[]
    for uid in underlyings:
        if uid in {"BTC","ETH"}: continue
        candidates=[r for r in ranking if r["underlying"]==uid]
        commodity.append({"commodity":uid,"metrics":[r for r in metrics if r["subject_id"]==uid],
                          "best_vehicle":candidates[0]["asset_id"] if candidates and global_ranking_ready else None,
                          "best_equity":next((r["asset_id"] for r in candidates if r["asset_class"]=="COMMODITY_EQUITY"),None) if global_ranking_ready else None,
                          "status":"RESEARCH_ONLY"})
    history=payload.get("history",[])
    history_sessions=[day(previous.get("as_of")) for previous in history]
    require(len(history_sessions)==len(set(history_sessions)),"duplicate_history_session")
    for previous in history:
        require(digest(previous) in policy["reviewed_pins"].get("history",[]),"unreviewed_history")
        require(previous.get("registry_sha256")==digest(registry),"history_universe_changed")
        require(stamp(previous["computed_at"])<stamp(cutoff),"future_history")
        receipt=previous.get("availability_receipt")
        require(receipt is not None,"missing_history_availability")
        pinned(receipt,policy,"history_availability",cutoff)
        require(receipt.get("evidence_kind")=="PIT_ARCHIVE","history_requires_pit_archive")
        require(receipt.get("snapshot_sha256")==digest({k:v for k,v in previous.items() if k!="availability_receipt"}),"history_receipt_mismatch")
        require(previous["as_of"] in sessions,"history_non_session")
        historical_close=sessions[previous["as_of"]]
        require(stamp(receipt["observed_at"])==historical_close,"history_observation_mismatch")
        require(historical_close<=stamp(previous["computed_at"])<=stamp(receipt["available_at"])<=historical_close+timedelta(hours=24),"retrospective_history_not_admitted")
        old=unique(previous["multi_asset_leadership_latest"],"asset_id")
        require(set(old)=={r["asset_id"] for r in rows},"history_cohort_changed")
        historical_ranks=[r["rank"] for r in old.values() if r.get("rank") is not None]
        require(all(type(rank) is int and rank>0 for rank in historical_ranks)
                and sorted(historical_ranks)==list(range(1,len(historical_ranks)+1)),"invalid_history_ranks")
        for historical_row in old.values():
            require(historical_row.get("as_of")==previous["as_of"],"history_row_session_mismatch")
            has_signal=historical_row.get("rank") is not None or historical_row.get("RS_composite") is not None
            require((not has_signal and historical_row.get("latest_session") is None) or historical_row.get("latest_session")==previous["as_of"],"history_row_latest_session_mismatch")
        for lag in (5,20):
            if previous["as_of"]!=list(sessions)[-1-lag]:continue
            for r in rows:
                p=old[r["asset_id"]]
                if r["rank"] is not None and p.get("rank") is not None:
                    r[f"rank_change_{lag}d"]=number(p["rank"],1)-r["rank"]
                if r["RS_composite"] is not None and p.get("RS_composite") is not None:
                    r[f"score_change_{lag}d"]=r["RS_composite"]-number(p["RS_composite"])
    alerts=[{"kind":"NEW_TOP10_DISCOVERY","asset_id":r["asset_id"],"order_signal":False} for r in rows if r.get("discovery_rank") is not None and r["discovery_rank"]<=10]
    # Without an admitted previous snapshot these are observations, not NEW transitions.
    for a in alerts:a["kind"]="TOP10_DISCOVERY_OBSERVATION"
    result={"schema":"multi-asset-leadership-v1","as_of":as_of,"computed_at":cutoff,"mode":"RESEARCH_ONLY",
            "feature_sha256":identity,"registry_sha256":digest(registry),"policy_sha256":digest(policy),
            "feature_available_at":feature_time,
            "fundamental_collection_blocked":fundamental_collection_blocked,
            "fundamental_collection_blockers":fundamental_collection_blockers,
            "ranking_scope":"SUBMITTED_COHORT" if global_ranking_ready else "INCOMPLETE_EVALUATION_COVERAGE" if complete_base else "INCOMPLETE_BASE_UNIVERSE",
            "global_ranking_ready":global_ranking_ready,
            "base_universe_blockers":base_blockers,
            "collection_receipts":[{k:v for k,v in r.items() if k in {"asset_id","subject_id","series","clock","source","status","rows","reason","raw_sha256","missing_dates","missing_completed_session"}} for r in payload.get("collection_receipts",[])],
            "normalization":normalization,"multi_asset_leadership_latest":rows,
            "commodity_market_latest":commodity,"crypto_market_latest":crypto,"asset_event_latest":events,
            "metrics":metrics,"proposal":proposal,"portfolio_exposure":observed_exposure,"alerts":alerts,
            "incremental_recompute_asset_ids":sorted({a for e in events for a in e["affected_asset_ids"]}),
            "historical_replay":historical_readiness(payload),"orders_generated":False,
            "accepted_target_written":False,"production_activation_allowed":False}
    if a3_coverage is not None:
        result["proposal_context"]=dict(mode="MODEL" if model_positions or not positions else "ACCOUNT_RESEARCH_COMPARISON",
            book_kind=payload.get("position_book_kind") if positions or model_positions else None,
            accepted_book_written=False,live_authority=False)
        if model_positions and incumbents is not None:
            result["proposal_context"].update(actual_holdings_claimed=False,
                execution_or_performance_claimed=False,comparison_weights="ADMITTED_MODEL_ALLOCATION_ONLY",
                allocation_as_of=incumbents["as_of"],allocation_decision_time=incumbents["decision_time"],
                allocation_relation=incumbents["allocation_relation"],cash_weight=incumbents["cash_weight"])
            result["proposal_context"]["turnover_cost_scope"]="PLANNED_TARGET_CHANGE_NOT_REALIZED_TURNOVER_OR_NAV"
        elif model_positions:
            result["proposal_context"].update(model_comparison_status="BLOCKED",model_comparison_blocker=model_input_blocker,
                actual_holdings_claimed=False,execution_or_performance_claimed=False,cash_weight=None)
        actual={r["asset_id"]:r for r in rows}
        for record in a3_coverage["records"]:
            row=actual.get(record["asset_id"],{})
            record["runtime_evaluation_admitted"]="risk_adjusted_expected_alpha" in row
            record["runtime_blockers"]=row.get("blockers",["REGISTRY_ASSET_UNMAPPED"])
        result["a3_reference_coverage"]=a3_coverage
        result["a3_model_input_candidates"]=a3_originals
        if not a3_complete:
            result["ranking_scope"]="INCOMPLETE_A3_REFERENCE_COVERAGE"
    result["status"]="PARTIAL_RESEARCH" if any(r["price"] is not None for r in rows) else "BLOCKED"
    if stock_mode:
        result["stock_research"]=dict(decision_scope=stock_scope,
            scoped_base_membership_verified=scoped_base_membership,
            full_roster_asset_ids=[r["asset_id"] for r in rows],
            unmapped_requested_ids=sorted(set(payload.get("requested_security_ids",[]))-set(assets)),
            comparison_plan=stock_comparison_plan(policy) if "reason" not in stock_scope else
                dict(status="BLOCKED",reason=stock_scope["reason"]),
            exception_preparation=[dict(symbol=s,status="METADATA_ONLY_NOT_TRADE_ADMISSION"
                if any(a["symbol"]==s for a in assets.values()) else "UNREGISTERED",
                required=["ORIGINAL_IDENTITY_AND_CA","SAME_CUTOFF_A3_ER_AND_A4_RISK",
                          "PINNED_EXCEPTION_AND_RELEASE_CONDITION","COST_AND_PRICE_INPUTS"])
                for s in ("GLDM","SHY","IEF","TLT")],
            actual_fit_executed=False,actual_backtest_executed=False)
    if stock_mode and er_suffix=="63s":
        result["allocation_horizon"]="63_NYSE_SESSIONS"
    result["result_sha256"]=digest(result)
    return result


def stock_comparison_plan(policy):
    """Prepare registered comparisons without invoking any fit/fullrunner.

    Actual retraining remains run_run287_expected_return_challenger.run behind
    its canonical U0 acceptance, mature-label purge and embargo. This plan cannot
    certify a current 12-calendar-month ER from that runner's 63-session label.
    """
    p=stock_research_profile(policy)
    shared=dict(start="2021-10-01",end="2026-11-06",starting_capital_usd=100000,
        integer_shares=True,fill="NEXT_NYSE_CLOSE",cash="DGS3MO_CARRY",horizon=p["horizon"],
        policy_sha256=digest(policy),fullrun_authorized=False)
    return dict(status="PREPARED_NOT_EXECUTABLE",shared=shared,comparison_family="STOCK_A5_MATCHED_INPUTS",
        arms=[dict(allocator=a,cadence=c,cost_bps_per_side=b) for a in ("CONTROL","COST_AWARE_LONG_ONLY")
              for c in ("MONTHLY","WEEKLY","MONTHLY_CONFIRMED_EVENT") for b in (25,50,100)],
        training_adapter="tools/run_run287_expected_return_challenger.py:run",
        training_contract="docs/run287_expected_return_challenger_contract.json",
        mature_label_functions=["prepare_frame","walk_forward_predictions"],
        training_horizons_nyse_sessions=[21,63,126],allocation_horizon=p["horizon"],
        training_output_is_not_12m_er=True,
        evaluation_adapters=["tools/a5_model_portfolio.py:prepare_model_replay_targets",
                             "tools/run_broker_ledger_replay.py:replay",
                             "tools/a5_model_portfolio.py:compare_model_replay_reports"],
        measurement_context_required=True,
        comparison_scope="FIXED_TARGET_ALLOCATION_NOT_CLOSED_LOOP_POLICY",
        independent_policy_paths_or_retraining_executed=False,
        blockers=["NAMED_EXPERIMENT_REGISTRATION_AND_DO_NOT_REPEAT_REPLAY_REQUIRED",
                  "CANONICAL_U0_AND_ORIGINAL_PIT_UNIVERSE_FINANCIAL_CA_ADMISSION_REQUIRED",
                  "SAME_SOURCE_CLOCK_COST_CASH_LEDGER_INPUTS_REQUIRED",
                  ("ORIGINAL_VALIDATED_NET_63_SESSION_ER_REQUIRED" if p["horizon"]=="63_NYSE_SESSIONS" else
                   "ORIGINAL_VALIDATED_12_CALENDAR_MONTH_ER_REQUIRED")],
        model_fit=False,targets_written=False,orders_generated=False,promotion_allowed=False)


def render(result):
    rows=result["multi_asset_leadership_latest"]
    er_label="63 NYSE intervals" if result.get("allocation_horizon")=="63_NYSE_SESSIONS" else "12m"
    lines=["# MULTI-ASSET LEADERSHIP", "", f"As of: {result['as_of']} | {result['status']}",
           "", "Research discovery and proposed reviews only. Missing expected returns are not neutral scores.",
           f"Ranking scope: {result['ranking_scope']}; global ranking ready: {result['global_ranking_ready']}",
           "", f"| Asset | Price status | Discovery rank | ER {er_label} | Portfolio status |", "|---|---|---:|---:|---|"]
    for r in rows:
        key="expected_return_63s" if result.get("allocation_horizon")=="63_NYSE_SESSIONS" else "expected_return_12m"
        lines.append(f"| {r['symbol']} | {r['data_quality']} | {r['discovery_rank']} | {r.get(key)} | {r['portfolio_status']} |")
    lines.extend(["", "## Commodity and network observations", "",
                  "Current observations only; source history is not certified PIT. Network activity is not an adoption or expected-return score.",
                  "", "| Subject | Metric | Value | Unit | Observation | Admission |", "|---|---|---:|---|---|---|"])
    for r in result["metrics"]:
        # Invalid observations still belong in the diagnostic report. Escape
        # external labels and never turn a missing report field into a number.
        cells=[str(r.get(k,"MISSING")).replace("|","\\|").replace("\n"," ").replace("\r"," ")
               for k in ("subject_id","metric","value","unit","observed_at","admission")]
        lines.append("| "+" | ".join(cells)+" |")
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- {r['symbol']}: {', '.join(r['blockers'])}" for r in rows if r["blockers"])
    lines.extend(["", "## Portfolio exposure changes", "", f"Proposal: {result['proposal']['status']}. Accepted targets and orders: unchanged.",
                  "", "## Historical replay", "", ", ".join(result["historical_replay"]["blockers"]), ""])
    return "\n".join(lines)

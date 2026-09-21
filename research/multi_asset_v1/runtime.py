"""Discovery -> reviewed thesis/ER -> separate risk proposal, never orders."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import math

from .contracts import (ContractError, ER_HORIZONS, HORIZONS, day, digest, identifier,
                        metadata, number, pinned, registry_rows, require, stamp, unique)
from .prices import BASE_RS_WEIGHTS, admit_prices, cross_section, grid, one_asset
from .decisions import COMPONENTS, classify, evaluation, event_memory, lookthrough, propose
from .fundamentals import receipt_blockers


def feature_identity(payload, registry):
    # Evaluator and risk pins bind exactly the same input snapshot without a cycle.
    return digest({"registry":registry,"as_of":payload["as_of"],
                   **{k:payload.get(k,[]) for k in ("prices","metrics","events","base_equity_ids","collection_receipts")}})


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


def run(payload, registry, policy):
    require(payload.get("schema")=="multi-asset-input-v1","input_schema")
    require(policy.get("schema")=="multi-asset-policy-v1","policy_schema")
    require(policy.get("baseline_rs_weights")==BASE_RS_WEIGHTS,"unsupported_rs_baseline")
    require(policy.get("baseline_commodity_weights")==COMPONENTS,"unsupported_commodity_baseline")
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
    for aid in base_ids:
        require(aid in assets and assets[aid]["asset_class"] in {"US_EQUITY","COMMODITY_EQUITY","CRYPTO_EQUITY"},"missing_base_equity")
    base_pin=payload.get("base_universe_receipt")
    complete_base=False
    base_blockers=[]
    try:
        require(bool(base_ids) and base_pin is not None,"missing_base_universe")
        pinned(base_pin,policy,"base_universe",cutoff)
        require(base_pin.get("asset_ids")==sorted(base_ids) and base_pin.get("as_of")==as_of,"base_universe_receipt_mismatch")
        complete_base=True
    except (ContractError,KeyError,ValueError) as exc:
        base_blockers.append(str(exc))
    groups=defaultdict(list)
    for r in payload.get("prices",[]):
        require(r.get("asset_id") in assets,"unregistered_price_asset")
        groups[(r["asset_id"],r.get("clock"))].append(r)
    by_eval=unique(payload.get("evaluations",[]),"asset_id")
    require(set(by_eval)<=set(assets),"unknown_evaluation_asset")
    position_rows=payload.get("positions",[])
    require(not position_rows or payload.get("position_book_kind") in {"ACTUAL_BROKER","APPROVED_TARGET","PAPER"},"position_book_kind")
    if position_rows:
        receipt=payload.get("position_receipt")
        require(receipt is not None,"unreviewed_position_book")
        pinned(receipt,policy,"positions",cutoff)
        require(receipt.get("positions_sha256")==digest(position_rows) and receipt.get("as_of")==as_of
                and receipt.get("book_kind")==payload["position_book_kind"],"position_receipt_mismatch")
        require(stamp(receipt["available_at"])<=stamp(cutoff),"future_position_book")
    positions=unique(position_rows,"asset_id")
    require(set(positions)<=set(assets),"unknown_position")
    for r in positions.values(): number(r.get("weight"),0,1)
    require(sum(r["weight"] for r in positions.values())<=1+1e-9,"position_weight_sum")
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
        if aid in by_eval:
            try:
                require(row["data_quality"]=="PRICE_OBSERVED_RESEARCH_ONLY","price_proxy_or_missing_cannot_admit_er")
                require(not fundamental_collection_blocked,"fundamental_collection_incomplete")
                require(all(metric["admission"]=="OBSERVED" for metric in metrics),"feature_metric_not_admitted")
                ev=evaluation(by_eval[aid],a,cutoff,policy,identity,feature_time)
                fields={"fundamental_score","expected_alpha_12m","expected_drawdown","downside_probability","signal_confidence","thesis_confidence","thesis_id","thesis_status","valuation_acceptable","scenarios","model_id","validation_sha256"}
                fields.update("expected_return_"+h for h in ER_HORIZONS)
                row.update({k:v for k,v in ev.items() if k in fields})
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
            row["risk_adjusted_expected_alpha"]=ev["expected_alpha_12m"]/ev["expected_drawdown"]
        rows.append(row)
    normalization=cross_section(rows)
    # Expected-return rank and discovery rank are separate columns.
    ranking=sorted([r for r in rows if "risk_adjusted_expected_alpha" in r and r["portfolio_status"] in {"CANDIDATE","HOLD","WATCH"}],
                   key=lambda r:(-r["risk_adjusted_expected_alpha"],r["asset_id"]))
    global_ranking_ready=complete_base and bool(ranking) and all(
        r["data_quality"]=="PRICE_OBSERVED_RESEARCH_ONLY" and "risk_adjusted_expected_alpha" in r for r in rows)
    if global_ranking_ready:
        for i,r in enumerate(ranking,1): r["rank"]=i
    proposal={"status":"BLOCKED","reasons":["missing_reviewed_risk_packet"],"proposed_weights":None,"orders_generated":False}
    if payload.get("risk") is not None:
        try:
            require(complete_base,"incomplete_base_universe")
            require(all(r["data_quality"]=="PRICE_OBSERVED_RESEARCH_ONLY" and "risk_adjusted_expected_alpha" in r for r in rows if r["asset_id"] in base_ids),"incomplete_equity_comparison")
            require(global_ranking_ready,"incomplete_cross_asset_comparison")
            require(feature_time is not None and stamp(payload["risk"].get("observed_at"))>=stamp(feature_time),"risk_predates_feature_inputs")
            proposal=propose(rows,assets,payload["risk"],payload.get("holdings",{}),cutoff,policy,identity,
                             {aid:r["weight"] for aid,r in positions.items()})
        except (ContractError,KeyError,ValueError) as exc:
            proposal={"status":"BLOCKED","reasons":[str(exc)],"proposed_weights":None,"orders_generated":False}
    observed_exposure={"status":"NOT_SUPPLIED","book_kind":None}
    if positions:
        try:
            observed_exposure={"status":"RESEARCH_MEASUREMENT","book_kind":payload["position_book_kind"],
                              **lookthrough({a:r["weight"] for a,r in positions.items()},assets,payload.get("holdings",{}),cutoff,policy)}
        except (ContractError,KeyError,ValueError) as exc:
            observed_exposure={"status":"BLOCKED","reason":str(exc),"book_kind":payload["position_book_kind"]}
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
    result["status"]="PARTIAL_RESEARCH" if any(r["price"] is not None for r in rows) else "BLOCKED"
    result["result_sha256"]=digest(result)
    return result


def render(result):
    rows=result["multi_asset_leadership_latest"]
    lines=["# MULTI-ASSET LEADERSHIP", "", f"As of: {result['as_of']} | {result['status']}",
           "", "Research discovery and proposed reviews only. Missing expected returns are not neutral scores.",
           f"Ranking scope: {result['ranking_scope']}; global ranking ready: {result['global_ranking_ready']}",
           "", "| Asset | Price status | Discovery rank | ER 12m | Portfolio status |", "|---|---|---:|---:|---|"]
    for r in rows:
        lines.append(f"| {r['symbol']} | {r['data_quality']} | {r['discovery_rank']} | {r['expected_return_12m']} | {r['portfolio_status']} |")
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

"""Independent A5 research proposal with original A3/ER, A4 and A6 binding.

Uses the incumbent allocation algorithm. A4 never specifies security weights.
Missing inputs produce a blocked diagnostic, not an invented cash allocation.
"""
from __future__ import annotations

import math
import re

from research.multi_asset_v1 import runtime
from research.multi_asset_v1.contracts import digest, require, number, stamp, registry_rows
from tools import chameleon_market_context_v2 as context

SCHEMA="a5-model-portfolio-proposal-v1"
SAFETY=dict(mode="MODEL_PORTFOLIO",accepted_target_written=False,orders_generated=False,
            actual_holdings_claimed=False,ledger_mutation_allowed=False,production_activation_allowed=False)


def seal(value):
    value["proposal_sha256"]=digest(value)
    return value


def blocked(cutoff, reasons):
    return seal(dict(schema=SCHEMA,status="BLOCKED",as_of=cutoff,proposed_weights=None,cash=None,
        changes=[],reasons=reasons,owner_routes=[dict(owner="A1",need="CURRENT_PRICE_IDENTITY_AND_ORIGINALS"),
            dict(owner="A3",need="CURRENT_REVIEWED_ORIGINAL_NET_ER"),dict(owner="A4",need="CURRENT_V2_RISK_AND_LIQUIDITY_CONTEXT"),
            dict(owner="A6",need="INDEPENDENT_CURRENT_REVIEW_AND_RISK_BINDING")],**SAFETY))


def validate_report(report, payload, policy):
    require(type(report) is dict and report.get("schema")=="market-analysis-report-v2","A5_A4_V2_REQUIRED")
    require(report.get("content_sha256")==context.digest({k:v for k,v in report.items() if k!="content_sha256"}),"A5_A4_REPORT_HASH")
    require(report.get("status")=="READY_RESEARCH_ONLY" and
            report.get("market_assessment",{}).get("ready_axis_count",0)>=8 and
            report.get("market_assessment",{}).get("required_axes_ready") is True,"A5_A4_NATIVE_NOT_READY")
    require(set(report.get("enhanced_readiness",{}))=={"funding","liquidity","bank_credit","macro"} and
            all(type(v) is bool and v for v in report["enhanced_readiness"].values()),"A5_A4_ENHANCED_NOT_READY")
    require(stamp(report["cutoff"])==stamp(payload["as_of"]),"A5_A4_CUTOFF_MISMATCH")
    require(all(report.get(k) is False for k in ("target_book_write_allowed","order_generation_allowed","ledger_mutation_allowed")),
            "A5_A4_AUTHORITY_CONFLICT")
    risk=payload.get("risk",{})
    require(risk.get("a4_report_content_sha256")==report["content_sha256"] and
            risk.get("a4_request_sha256")==report["request_sha256"],"A5_REVIEWED_RISK_A4_BINDING")
    require(digest(risk) in policy.get("reviewed_pins",{}).get("risk",[]),"A5_RISK_NOT_REVIEWED")


def _explain_result(result, risk, report, *, previous=None, policy=None):
    """Pure presentation of an already computed native result; no new sizing."""
    stock=(policy or {}).get("stock_cash_research",{}).get("enabled") is True
    from tools.run_multi_asset_leadership import fully_admitted
    require(result["proposal"]["status"]=="RESEARCH_PROPOSAL" and
            (fully_admitted(result) if stock else result.get("global_ranking_ready") is True),
            "A5_NATIVE_PROPOSAL_NOT_READY")
    proposal=result["proposal"];weights=proposal["proposed_weights"];cash=number(proposal["cash"],0,1)
    require(type(weights) is dict and all(type(k) is str for k in weights),"A5_WEIGHT_SCHEMA")
    for value in weights.values():number(value,0,1)
    require(math.isclose(sum(weights.values())+cash,1,abs_tol=1e-9),"A5_WEIGHT_SUM")
    require(sum(weights.values())<=number(risk["max_gross"],0,1)+1e-9 and
            all(w<=number(risk["max_security_weight"],0,1)+1e-9 for w in weights.values()),"A5_RISK_CEILING")
    old={};old_cash=1.0;comparison="GENESIS"
    if stock:
        require(previous is None,"A5_STOCK_COMPARISON_REQUIRES_VERIFIED_MODEL_NOT_PREVIOUS_PROPOSAL")
        review=result.get("a3_reference_coverage",{}).get("current_review",{})
        native_context=result.get("proposal_context",{})
        require(review.get("status")=="CURRENT_REFERENCE_REVIEW_VERIFIED","A5_CURRENT_A3_A6_NOT_VERIFIED")
        if native_context.get("book_kind")=="MODEL":
            verified=review.get("model_incumbents") or review.get("model_parent_lineage")
            require(type(verified) is dict and verified.get("status") in
                {"CURRENT_MODEL_ALLOCATION_VERIFIED","PARENT_LINEAGE_ONLY_VERIFIED"} and
                native_context.get("comparison_weights")=="ADMITTED_MODEL_ALLOCATION_ONLY" and
                native_context.get("actual_holdings_claimed") is False and
                native_context.get("execution_or_performance_claimed") is False,"A5_MODEL_COMPARISON_NOT_VERIFIED")
            old=proposal.get("carried_position_weights")
            old_cash=number(native_context.get("cash_weight"),0,1)
            require(type(old) is dict and old==verified["current_weights"] and
                    old_cash==verified["cash_weight"] and
                    math.isclose(sum(number(w,0,1) for w in old.values())+old_cash,1,abs_tol=1e-9),
                    "A5_MODEL_COMPARISON_WEIGHTS_OR_CASH")
            comparison=verified["allocation_relation"]
        else:
            require(native_context.get("book_kind") is None and review.get("model_state_kind")=="GENESIS",
                    "A5_EXPLICIT_GENESIS_OR_VERIFIED_MODEL_REQUIRED")
    elif previous is not None:
        require(previous.get("schema")==SCHEMA and previous.get("status")=="RESEARCH_PROPOSAL" and
                previous.get("proposal_sha256")==digest({k:v for k,v in previous.items() if k!="proposal_sha256"}),
                "A5_PREVIOUS_PROPOSAL_HASH")
        require(digest(previous) in (policy or {}).get("reviewed_pins",{}).get("model_proposal_history",[])
                and stamp(previous["as_of"])<stamp(result["computed_at"]),"A5_PREVIOUS_NOT_REVIEWED_OR_PAST")
        require(previous.get("actual_holdings_claimed") is False,"A5_PREVIOUS_BOOK_KIND")
        require(all(previous.get(k) is False for k in SAFETY if k!="mode"),"A5_PREVIOUS_AUTHORITY")
        old=previous["proposed_weights"]
        require(type(old) is dict and all(type(k) is str for k in old),"A5_PREVIOUS_WEIGHT_SCHEMA")
        for value in old.values():number(value,0,1)
        require(math.isclose(sum(old.values())+number(previous["cash"],0,1),1,abs_tol=1e-9),"A5_PREVIOUS_WEIGHT_SUM")
        comparison="PREVIOUS_MODEL_PROPOSAL"
        old_cash=previous["cash"]
    rows={r["asset_id"]:r for r in result["multi_asset_leadership_latest"]}
    require(set(weights)<=set(rows),"A5_UNEXPLAINED_WEIGHT")
    originals={r["asset_id"]:r for r in result.get("a3_model_input_candidates",[])}
    changes=[]
    for aid in sorted(set(rows)|set(old)):
        row=rows.get(aid,{});weight=weights.get(aid,0);delta=weight-old.get(aid,0)
        if weight>0:
            reasons=["CURRENT_REVIEWED_A3_NET_ER","NATIVE_RISK_ADJUSTED_CANDIDATE_COMPETITION","INDEPENDENT_REVIEWED_A5_RISK_CEILINGS"]
        else:
            reasons=list(row.get("blockers",[])) or ["NATIVE_A5_NOT_SELECTED"]
        original=originals.get(aid,{})
        changes.append(dict(asset_id=aid,weight=weight,previous_model_weight=old.get(aid,0),change=delta,
            reasons=reasons,portfolio_status=row.get("portfolio_status","NO_LONGER_IN_REQUESTED_COHORT"),
            expected_return_12m=row.get("expected_return_12m"),expected_alpha_12m=row.get("expected_alpha_12m"),
            cost_assumptions=original.get("cost_assumptions"),net_of_costs=original.get("net_of_costs"),
            model_id=original.get("model_id"),validation_sha256=original.get("validation_sha256")))
    explained=dict(schema=SCHEMA,status="RESEARCH_PROPOSAL",as_of=result["computed_at"],
        session=result["as_of"],proposed_weights=weights,cash=cash,changes=changes,comparison_basis=comparison,
        cash_change=cash-old_cash if stock or previous is not None else None,
        cash_reasons=["ONE_MINUS_NATIVE_SECURITY_WEIGHTS","REVIEWED_GROSS_AND_SECURITY_LIMITS","UNALLOCATED_NATIVE_COMPETITION_BUDGET"],
        reviewed_max_gross=risk["max_gross"],reviewed_max_security_weight=risk["max_security_weight"],
        a4_report_content_sha256=report["content_sha256"],a4_request_sha256=report["request_sha256"],
        macro_reason_evidence=dict(funding=report["funding"],liquidity=report["liquidity"],
            bank_credit=report["bank_credit"],horizon_outlook=report["horizon_outlook"]),
        native_result_sha256=result["result_sha256"],feature_sha256=result["feature_sha256"],
        policy_sha256=result["policy_sha256"],a3_reference_coverage=result.get("a3_reference_coverage"),**SAFETY)
    if stock:
        explained.update(global_ranking_ready=result["global_ranking_ready"],ranking_scope=result["ranking_scope"],
            stock_decision_scope=result["stock_research"]["decision_scope"],
            full_roster_asset_ids=result["stock_research"]["full_roster_asset_ids"],
            model_comparison_context=result.get("proposal_context"),comparison_allocation_only=True,
            turnover_cost_scope="PLANNED_TARGET_CHANGE_NOT_REALIZED_TURNOVER_OR_NAV",
            decision_clock=proposal.get("decision_clock"),intent=proposal.get("intent"),
            exit_reviews=proposal.get("exit_reviews",[]),exception_reviews=proposal.get("exception_reviews",[]),
            comparison_inputs_sha256=proposal.get("comparison_inputs_sha256"),comparisons=proposal.get("comparisons"))
        explained["replay_requirements"]=dict(fill_mode="next_close",integer_shares=True,
            model_cost_bps_per_side=policy["stock_cash_research"]["cost_bps_per_side"],
            cash_carry_mode="risk_free_rate",cash_rate_source="DGS3MO",cash_rate_lag_days=1,
            cash_carry_haircut_bps=0,cash_carry_day_count=365)
        explained["optimizer_certificate"]=proposal.get("optimizer_certificate")
    return seal(explained)


REPLAY_ARMS=("CONTROL","COST_AWARE_LONG_ONLY")
_HASH=re.compile(r"[a-f0-9]{64}\Z")


def prepare_model_replay_targets(proposals, registry, *, expected_proposal_hashes,
                                 expected_registry_sha256):
    """Serialize frozen original comparisons; never rerun A5 or authenticate Source.

    The two arms share each original decision's incumbent state. This is a
    fixed-target allocation comparison, not two closed-loop policy backtests.
    External pins are mandatory byte/semantic bindings, not review authority.
    Nothing is written and no target, ledger, fit or replay is executed here.
    """
    import pandas_market_calendars as mcal
    from datetime import timedelta
    require(type(proposals) is list and 0<len(proposals)<=10000,"A5_REPLAY_PROPOSAL_COUNT")
    require(type(expected_proposal_hashes) is list and len(expected_proposal_hashes)==len(proposals),
            "A5_REPLAY_EXTERNAL_ORIGINAL_PINS")
    require(type(expected_registry_sha256) is str and _HASH.fullmatch(expected_registry_sha256)
            and digest(registry)==expected_registry_sha256,"A5_REPLAY_REGISTRY_PIN")
    _,assets=registry_rows(registry)
    targets={arm:[] for arm in REPLAY_ARMS};decisions=[];seen=set();last=None;requirements=None
    calendar=mcal.get_calendar("NYSE")
    for proposal,pin in zip(proposals,expected_proposal_hashes):
        require(type(pin) is str and _HASH.fullmatch(pin) and digest(proposal)==pin,
                "A5_REPLAY_ORIGINAL_PIN")
        require(proposal.get("schema")==SCHEMA and proposal.get("status")=="RESEARCH_PROPOSAL"
                and proposal.get("proposal_sha256")==digest({k:v for k,v in proposal.items()
                                                            if k!="proposal_sha256"}),"A5_REPLAY_ORIGINAL_SCHEMA")
        require(proposal.get("mode")=="MODEL_PORTFOLIO" and all(proposal.get(k) is False
                for k in SAFETY if k!="mode"),"A5_REPLAY_ORIGINAL_AUTHORITY")
        at=stamp(proposal["as_of"]);session=proposal["session"];clock=proposal.get("decision_clock",{})
        require(type(session) is str and session not in seen and (last is None or at>last)
                and clock.get("decision_session")==session and stamp(clock["decision_at"])==at,
                "A5_REPLAY_DECISION_SEQUENCE")
        schedule=calendar.schedule(start_date=session,end_date=stamp(session+"T00:00:00Z").date()+timedelta(days=10))
        require(not schedule.empty and schedule.index[0].date().isoformat()==session
                and schedule["market_close"].iloc[0].to_pydatetime()<=at
                and len(schedule)>1 and at<schedule["market_close"].iloc[1].to_pydatetime(),
                "A5_REPLAY_COMPLETED_DECISION_SESSION")
        require(clock.get("fill_mode")=="NEXT_NYSE_CLOSE" and
                stamp(clock["earliest_fill_at"])==schedule["market_close"].iloc[1].to_pydatetime(),
                "A5_REPLAY_NEXT_CLOSE")
        for key in ("native_result_sha256","feature_sha256","policy_sha256",
                    "comparison_inputs_sha256","a4_report_content_sha256","a4_request_sha256"):
            require(type(proposal.get(key)) is str and _HASH.fullmatch(proposal[key]),
                    "A5_REPLAY_ORIGINAL_REFERENCE")
        req=proposal.get("replay_requirements")
        require(type(req) is dict and set(req)=={"fill_mode","integer_shares","model_cost_bps_per_side",
                "cash_carry_mode","cash_rate_source","cash_rate_lag_days","cash_carry_haircut_bps",
                "cash_carry_day_count"} and req["fill_mode"]=="next_close" and req["integer_shares"] is True
                and type(req["model_cost_bps_per_side"]) is int and req["model_cost_bps_per_side"] in (25,50,100)
                and req["cash_carry_mode"]=="risk_free_rate" and req["cash_rate_source"]=="DGS3MO"
                and req["cash_rate_lag_days"]==1 and req["cash_carry_haircut_bps"]==0
                and req["cash_carry_day_count"]==365,"A5_REPLAY_EXPLICIT_COST_CASH_POLICY")
        require(requirements is None or req==requirements,"A5_REPLAY_CHANGED_COST_CASH_POLICY")
        requirements=dict(req)
        comparisons=proposal.get("comparisons")
        require(type(comparisons) is dict and set(comparisons)==set(REPLAY_ARMS),"A5_REPLAY_TWO_ARMS")
        intent=proposal.get("intent")
        require(intent in {"REVIEW_REBALANCE","NO_ENTRY_HOLD_CASH","HOLD_UNTIL_SCHEDULED_REVIEW"},
                "A5_REPLAY_INTENT")
        require(decisions or intent!="HOLD_UNTIL_SCHEDULED_REVIEW","A5_REPLAY_INITIAL_HOLD_NEEDS_ALLOCATION")
        roster=proposal.get("full_roster_asset_ids")
        require(type(roster) is list and len(roster)==len(set(roster)),"A5_REPLAY_FULL_ROSTER")
        symbols={}
        for arm in REPLAY_ARMS:
            comparison=comparisons[arm];weights=comparison.get("weights")
            require(type(weights) is dict and set(weights)<=set(roster),"A5_REPLAY_UNCOVERED_WEIGHT")
            number(comparison.get("objective"));number(comparison.get("incremental_cost_fraction"),0)
            clean={aid:number(w,0,1) for aid,w in weights.items()}
            require(sum(clean.values())<=1+1e-9 and sum(clean.values())<=number(proposal["reviewed_max_gross"],0,1)+1e-9
                    and all(w<=number(proposal["reviewed_max_security_weight"],0,1)+1e-9 for w in clean.values()),
                    "A5_REPLAY_WEIGHT_LIMITS")
            for aid,w in clean.items():
                if not w:continue
                asset=assets.get(aid,{})
                require(asset.get("identity_verified") is True and asset.get("tradable") is True
                        and asset.get("corporate_action_quarantine") is False,"A5_REPLAY_SECURITY_IDENTITY")
                symbol=asset["symbol"]
                require(re.fullmatch(r"[A-Z][A-Z0-9.-]{0,19}",symbol) and symbol!="CASH"
                        and (symbol not in symbols or symbols[symbol]==aid),"A5_REPLAY_TICKER_COLLISION")
                symbols[symbol]=aid
            require(intent!="NO_ENTRY_HOLD_CASH" or not any(clean.values()),"A5_REPLAY_CASH_INTENT_CONFLICT")
            if intent!="HOLD_UNTIL_SCHEDULED_REVIEW":
                targets[arm].extend(dict(rebalance_date=session,ticker=assets[aid]["symbol"],weight=w)
                                    for aid,w in sorted(clean.items()) if w>0)
                # An empty security dictionary is a real cash decision, not an absent date.
                targets[arm].append(dict(rebalance_date=session,ticker="CASH",weight=max(0.0,1-sum(clean.values()))))
        decisions.append(dict(session=session,as_of=proposal["as_of"],intent=intent,original_sha256=pin,
            proposal_sha256=proposal["proposal_sha256"],native_result_sha256=proposal["native_result_sha256"],
            feature_sha256=proposal["feature_sha256"],policy_sha256=proposal["policy_sha256"],
            comparison_inputs_sha256=proposal["comparison_inputs_sha256"],
            a3_reference_coverage_sha256=digest(proposal.get("a3_reference_coverage")),
            full_roster_asset_ids=list(roster),ticker_to_asset_id=symbols,decision_clock=dict(clock),
            rebalance_exported=intent!="HOLD_UNTIL_SCHEDULED_REVIEW"))
        seen.add(session);last=at
    result=dict(schema="a5-fixed-target-replay-export-v1",status="PREPARED_NOT_EXECUTED",
        comparison_scope="FIXED_TARGET_ALLOCATION_NOT_CLOSED_LOOP_POLICY",arms=targets,decisions=decisions,
        target_rows_sha256_by_arm={a:digest(rows) for a,rows in targets.items()},
        registry_sha256=expected_registry_sha256,replay_requirements=requirements,
        source_authentication="NOT_CERTIFIED_BY_SERIALIZATION_OR_HASH_PINS",Source_admitted=False,
        historical_PIT=False,replay_executed=False,model_fit=False,performance_claimed=False,**SAFETY)
    result["content_sha256"]=digest(result)
    return result


def compare_model_replay_reports(export, reports, bindings, *, expected_export_sha256,
                                 expected_report_sha256_by_arm,expected_binding_sha256_by_arm,
                                 cost_bps_per_side):
    """Join original E2 results; never recompute prices, NAV, fees or choose a winner.

    Both real replay calls must use run_broker_ledger_replay.replay with an
    independently supplied measurement_context. Per-arm NAV/context hashes may
    differ. Missing/refused E2 evidence withholds the entire paired measurement.
    Source, PIT and closed-loop policy validation remain separate.
    """
    from tools import nav_metrics_v2 as nav
    from tools.execution_cost_model import EXECUTION_COST_MODE_FIXED
    empty=dict(schema="a5-paired-replay-measurement-v1",status="BLOCKED",metrics=None,deltas=None,
        paired_measurement_ready=False,economically_validated=False,model_fit=False,
        closed_loop_policy_tested=False,Source_admitted=False,historical_PIT=False,**SAFETY)
    try:
        require(digest(export)==expected_export_sha256 and export.get("schema")=="a5-fixed-target-replay-export-v1"
                and export.get("content_sha256")==digest({k:v for k,v in export.items() if k!="content_sha256"}),
                "A5_PAIR_EXPORT_PIN")
        for value in (reports,bindings,expected_report_sha256_by_arm,expected_binding_sha256_by_arm):
            require(type(value) is dict and set(value)==set(REPLAY_ARMS),"A5_PAIR_BOTH_ARMS_REQUIRED")
        require(type(cost_bps_per_side) is int and cost_bps_per_side in (25,50,100)
                and cost_bps_per_side>=export["replay_requirements"]["model_cost_bps_per_side"],"A5_PAIR_COST_SCENARIO")
        common=None;shared=None;summary={}
        for arm in REPLAY_ARMS:
            report=reports[arm];binding=bindings[arm]
            require(digest(report)==expected_report_sha256_by_arm[arm] and
                    digest(binding)==expected_binding_sha256_by_arm[arm],"A5_PAIR_ORIGINAL_PIN")
            require(report.get("status")==nav.COMPLETE and report.get("metric_mode")==nav.MODE
                    and report.get("metric_admission_complete") is True
                    and report.get("execution_status")=="completed"
                    and report.get("cost_basis")=="SUPPLIED_NET_NAV_NO_SECOND_FEE"
                    and all(report.get(k) is False for k in nav.AUTHORITY if k!="research_only")
                    and report.get("research_only") is True,"A5_PAIR_E2_NOT_ADMITTED")
            keys={"schema","arm","export_sha256","target_rows_sha256","metrics_sha256",
                  "price_input_sha256","identity_sha256","source_pit_binding_sha256","cash_policy_sha256",
                  "execution_policy_sha256","session_grid_sha256","measurement_context_sha256",
                  "valuation_binding_sha256"}
            require(type(binding) is dict and set(binding)==keys and binding["schema"]=="a5-fixed-target-replay-binding-v1"
                    and binding["arm"]==arm,"A5_PAIR_BINDING_SCHEMA")
            require(all(type(binding[k]) is str and _HASH.fullmatch(binding[k]) for k in keys-{"schema","arm"}),
                    "A5_PAIR_BINDING_HASHES")
            require(binding["export_sha256"]==expected_export_sha256 and binding["metrics_sha256"]==digest(report)
                    and binding["target_rows_sha256"]==export["target_rows_sha256_by_arm"][arm]
                    and binding["measurement_context_sha256"]==report.get("measurement_context_sha256")
                    and binding["valuation_binding_sha256"]==report.get("valuation_binding_provenance",{}).get("sha256"),
                    "A5_PAIR_INPUT_BINDING")
            current_shared={k:binding[k] for k in ("price_input_sha256","identity_sha256","source_pit_binding_sha256",
                "cash_policy_sha256","execution_policy_sha256","session_grid_sha256")}
            require(shared is None or current_shared==shared,"A5_PAIR_SHARED_INPUTS_CHANGED");shared=current_shared
            req=export["replay_requirements"]
            for key in ("fill_mode","integer_shares","cash_carry_mode","cash_rate_source","cash_rate_lag_days",
                        "cash_carry_haircut_bps","cash_carry_day_count"):
                require(report.get(key)==req[key],"A5_PAIR_EXECUTION_POLICY_CHANGED")
            require(report.get("cost_bps_per_side")==cost_bps_per_side,"A5_PAIR_COST_CHANGED")
            cost_config=report.get("execution_cost_config")
            require(report.get("execution_cost_mode",EXECUTION_COST_MODE_FIXED)==EXECUTION_COST_MODE_FIXED
                    and (cost_config is None or (type(cost_config) is dict
                         and cost_config.get("mode")==EXECUTION_COST_MODE_FIXED
                         and cost_config.get("enabled") is False)),"A5_PAIR_VARIABLE_COST_NOT_FIXED_ALL_IN")
            current_common={k:report[k] for k in ("start_date","end_date","frequency","annualization","anchor_timestamp",
                "ending_timestamp","starting_capital_usd","years","input_row_count")}
            require(common is None or current_common==common,"A5_PAIR_WINDOW_OR_CAPITAL_CHANGED");common=current_common
            for key in ("total_return","cagr","max_dd","ending_capital_usd","years"):
                number(report.get(key))
            require(type(report.get("trade_count")) is int and report["trade_count"]>=0,"A5_PAIR_TRADE_COUNT")
            summary[arm]={k:report[k] for k in ("total_return","cagr","max_dd","ending_capital_usd","trade_count")}
            summary[arm]["total_fees_usd"]=(number(report["total_fees_usd"],0)
                if report.get("total_fees_usd") is not None else None)
        return dict(empty,status="PAIRED_RESEARCH_MEASUREMENT_COMPLETE",metrics=summary,
            deltas={k:summary[REPLAY_ARMS[1]][k]-summary[REPLAY_ARMS[0]][k]
                    for k in ("total_return","cagr","max_dd","ending_capital_usd","trade_count")},
            paired_measurement_ready=True,comparison_scope=export["comparison_scope"],shared_inputs=shared,
            measurement_window=common,cost_bps_per_side=cost_bps_per_side,
            cost_relation=("ORIGINAL_MODEL_COST" if cost_bps_per_side==req["model_cost_bps_per_side"]
                           else "FIXED_TARGET_COST_STRESS_NO_REOPTIMIZATION"),
            fee_application="EXISTING_LEDGER_ONCE; SUPPLIED_NET_NAV_NOT_CHARGED_AGAIN",
            input_authentication="EXTERNAL_HASH_BINDINGS_NOT_PRODUCER_OR_PIT_CERTIFICATION")
    except (ValueError,KeyError,TypeError,OverflowError):
        return dict(empty,reason="A5_PAIR_ORIGINAL_E2_OR_MATCHED_INPUTS_NOT_VERIFIED")


def build_model_proposal(payload, registry, policy, report, *, artifact_resolver=None,
                         review_root=None,code_sha=None,previous=None):
    cutoff=payload.get("as_of")
    try:
        stock=policy.get("stock_cash_research",{}).get("enabled") is True
        if stock:
            require(payload.get("position_book_kind") in {None,"MODEL"} and
                    (payload.get("position_book_kind")=="MODEL" or not payload.get("positions")),
                    "A5_MODEL_ONLY_NO_ACCOUNT_BOOK")
        else:
            require(not payload.get("positions") and not payload.get("position_book_kind"),"A5_MODEL_ONLY_NO_ACCOUNT_BOOK")
        require(payload.get("requested_security_ids") and payload.get("a3_reference_entries") is not None
                and payload.get("current_a3_review") is not None,"A5_CURRENT_A3_GRAPH_REQUIRED")
        require(not payload.get("evaluations"),"A5_UNCOVERED_LEGACY_EVALUATIONS")
        _,assets=registry_rows(registry)
        if not stock:
            require(set(assets)-{policy["benchmark_id"]}==set(payload["requested_security_ids"]),
                    "A5_FULL_ALLOCATOR_COHORT_NEEDS_ORIGINAL_REFERENCES")
        validate_report(report,payload,policy)
        source_hashes=None
        if stock:
            from tools.run_multi_asset_leadership import verified_source_hashes
            source_hashes=verified_source_hashes(code_sha)
        result=runtime.run(payload,registry,policy,artifact_resolver=artifact_resolver,
                           review_root=review_root,code_sha=code_sha)
        if stock:
            require(source_hashes==verified_source_hashes(code_sha),"A5_SOURCE_CHANGED_DURING_MODEL_REVIEW")
            result.update(code_identity_verified=True,code_file_sha256=source_hashes)
            result.pop("result_sha256",None);result["result_sha256"]=digest(result)
        coverage=result.get("a3_reference_coverage",{})
        require(coverage.get("held_count")==0 and coverage.get("current_review",{}).get("status")=="CURRENT_REFERENCE_REVIEW_VERIFIED",
                "A5_CURRENT_A3_A6_NOT_VERIFIED")
        require(set(payload["requested_security_ids"])=={r["asset_id"] for r in coverage["records"]}
                and all(r.get("runtime_evaluation_admitted") is True for r in coverage["records"]),"A5_A3_ROSTER_INCOMPLETE")
        require(set(result["proposal"].get("proposed_weights",{}))<=set(payload["requested_security_ids"]),
                "A5_ALLOCATED_SECURITY_WITHOUT_ORIGINAL_COVERAGE")
        # The displayed report must be the exact original A4 report consumed by
        # the verified graph, not another self-hashed view or an auxiliary fit.
        from tools.run_a4_research_cycle import json_ref
        binding=payload["current_a3_review"]
        graph=json_ref(review_root,binding["review_graph"],4*1024**2)
        request=next(r for r in graph["state"]["requests"] if r["agent"]=="A5")
        original_report=json_ref(review_root,request["inputs"]["regime"],8*1024**2)
        require(digest(original_report)==digest(report),"A5_A4_NOT_ORIGINAL_REVIEWED_REPORT")
        return _explain_result(result,payload["risk"],report,previous=previous,policy=policy)
    except (ValueError,KeyError,TypeError,OSError,OverflowError,RecursionError):
        return blocked(cutoff,["CURRENT_A3_A4_A6_RISK_OR_NATIVE_PROPOSAL_NOT_VERIFIED"])


def pinned_inputs(root, request, expected_policy_sha256):
    from tools.run_a4_research_cycle import json_ref
    require(type(expected_policy_sha256) is str and re.fullmatch(r"[a-f0-9]{64}",expected_policy_sha256),
            "A5_EXTERNAL_POLICY_PIN")
    require(request.get("schema")=="a5-model-proposal-request-v1" and
            request["policy"]["sha256"]==expected_policy_sha256,"A5_EXTERNAL_POLICY_PIN")
    payload=json_ref(root,request["inputs"]);registry=json_ref(root,request["registry"],4*1024**2)
    policy=json_ref(root,request["policy"],1024**2)
    return payload,registry,policy


def decision_cutoff(root, request, *, expected_policy_sha256,execution_at):
    """Choose the fixed replay time; full original-graph admission still follows."""
    payload,_,policy=pinned_inputs(root,request,expected_policy_sha256)
    profile=policy["current_a3_review_profile"]
    require(stamp(profile["available_at"])<=stamp(payload["as_of"])<=stamp(execution_at)<stamp(profile["expires_at"]),
            "A5_EXECUTION_OUTSIDE_REVIEWED_VALIDITY")
    return payload["as_of"]


def load_and_build(root, request, report, *, expected_policy_sha256,code_sha,execution_at):
    """A scoped request reuses the incumbent A2 bounded original file loader."""
    from tools.run_a4_research_cycle import json_ref
    from tools.run_multi_asset_leadership import a3_artifacts
    decision_cutoff(root,request,expected_policy_sha256=expected_policy_sha256,execution_at=execution_at)
    payload,registry,policy=pinned_inputs(root,request,expected_policy_sha256)
    previous=json_ref(root,request["previous_proposal"],8*1024**2) if request.get("previous_proposal") else None
    return build_model_proposal(payload,registry,policy,report,artifact_resolver=a3_artifacts(payload,root),
        review_root=root,code_sha=code_sha,previous=previous)


def render(proposal):
    lines=["# A5 model portfolio", "", "Status: "+proposal["status"],"", "Research proposal; manual live decisions only."]
    if proposal["status"]=="BLOCKED":
        return "\n".join(lines+["", "Weights and cash: unavailable until original inputs and independent review pass.","",*proposal["reasons"],""])
    lines += ["", "| Security | Weight | Change vs previous model | Reasons |", "| --- | ---: | ---: | --- |"]
    for r in proposal["changes"]:
        lines.append(f"| {r['asset_id']} | {r['weight']:.2%} | {r['change']:+.2%} | {', '.join(r['reasons'])} |")
    lines += [f"| CASH | {proposal['cash']:.2%} | | {', '.join(proposal['cash_reasons'])} |",""]
    return "\n".join(lines)

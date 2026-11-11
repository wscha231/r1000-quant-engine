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
    return seal(explained)


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

#!/usr/bin/env python3
"""Cloud-capable daily diagnosis, weekly scores and monthly challenger trials.

Uses restored, hash-bound originals only. No provider calls, model promotion,
accepted portfolio state or credentials are created by this process. Durable
Drive persistence/readback belongs to the existing hosted workflow.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import market_analysis_engine as market
from tools import a4_macro_learning as learning
from tools.macro_history_sources import digest,encoded,exclusive

MAX_STATE_FILES=5000
MAX_CHECKPOINT_BYTES=8*1024**2
SCOPES=("A4_ONLY", "A4_A5")


def store_checkpoint(path, value):
    raw=encoded(value)
    market.need(len(raw)<=MAX_CHECKPOINT_BYTES,"A4_CHECKPOINT_SIZE")
    exclusive(path,raw)


def json_ref(root, reference, limit=64*1024**2):
    market.need(type(reference) is dict,"A4_REFERENCE")
    relative=market.safe_path(reference.get("path"))
    path=Path(root).joinpath(*relative.parts)
    market.need(path.resolve().is_relative_to(Path(root).resolve()) and
                not any(p.is_symlink() for p in (path,*path.parents)),"A4_REFERENCE_OUTSIDE_ROOT")
    raw=market.bounded(path,limit)
    market.need(digest(raw)==reference.get("sha256"),"A4_REFERENCE_HASH")
    return market.clock.decode(raw)


def restored_trials(state_root, cutoff):
    path=Path(state_root)/"trials"
    if not path.exists():return []
    market.need(not path.is_symlink(),"A4_STATE_SYMLINK")
    files=list(path.iterdir())
    market.need(len(files)<=MAX_STATE_FILES,"A4_STATE_FILE_BUDGET")
    results=[]
    for file in sorted(files):
        market.need(re.fullmatch(r"[a-f0-9]{64}\.json",file.name),"A4_STATE_FILE_IDENTITY")
        trial=market.clock.decode(market.bounded(file,learning.MAX_TRIAL_BYTES))
        learning.verify_trial(trial)
        market.need(file.stem==trial["trial_sha256"] and
                    market.clock.stamp(trial["cutoff"])<=market.clock.stamp(cutoff),"A4_STATE_CLOCK_OR_IDENTITY")
        results.append(trial)
    return results


def load_learning(root, expected_policy_sha256, *, request_name='learning_request.json'):
    market.need(request_name in {'learning_request.json','forward_request.json'},'A4_LEARNING_REQUEST_NAME')
    market.need(type(expected_policy_sha256) is str and re.fullmatch(r"[a-f0-9]{64}",expected_policy_sha256),
                "A4_LEARNING_EXTERNAL_POLICY_REQUIRED")
    raw=market.bounded(Path(root)/request_name,256*1024)
    request=market.clock.decode(raw)
    market.need(request.get("schema")=="a4-learning-request-v1" and
                request["policy"]["sha256"]==expected_policy_sha256,"A4_LEARNING_REQUEST_POLICY")
    policy=json_ref(root,request["policy"],1024**2)
    # This externally supplied pin is the raw file hash. The mathematical API
    # additionally binds its canonical decoded identity.
    payload=json_ref(root,request["inputs"])
    inventory=request.get("originals",{})
    market.need(type(inventory) is dict and len(inventory)<=128,"A4_ORIGINAL_INVENTORY")
    def resolve(sha):
        reference=inventory.get(sha)
        market.need(type(reference) is dict and reference.get("sha256")==sha,"A4_ORIGINAL_REFERENCE")
        relative=market.safe_path(reference.get("path"));path=Path(root).joinpath(*relative.parts)
        market.need(path.resolve().is_relative_to(Path(root).resolve()) and
                    not any(p.is_symlink() for p in (path,*path.parents)),"A4_REFERENCE_OUTSIDE_ROOT")
        raw=market.bounded(path,32*1024**2)
        market.need(digest(raw)==sha,"A4_ORIGINAL_HASH")
        return raw
    return payload,policy,resolve


def load_forward_context(root,release_policy):
    """An existing external release pin binds this separate macro-only request."""
    raw=market.bounded(Path(root)/'forward_request.json',256*1024)
    market.need(digest(raw)==release_policy.get('forward_request_sha256'),'A4_FORWARD_REQUEST_NOT_REVIEWED')
    request=market.clock.decode(raw)
    payload,policy,resolve=load_learning(root,request.get('policy',{}).get('sha256'),request_name='forward_request.json')
    return dict(forward_inputs=payload,forward_policy=policy,
        forward_policy_sha256=digest(encoded(policy)),artifact_resolver=resolve)


def run_cycle(*, input_root, state_root, output_dir, cutoff,
              learning_policy_sha256=None,a5_policy_sha256=None,code_sha=None,learning_input_root=None,
              scope="A4_A5",a5_input_root=None):
    market.need(scope in SCOPES,"A4_RESEARCH_SCOPE")
    root,state,out=Path(input_root),Path(state_root),Path(output_dir)
    learn_root=Path(learning_input_root) if learning_input_root is not None else root
    model_root=Path(a5_input_root) if scope=="A4_A5" and a5_input_root is not None else root
    market.need(not any(p.is_symlink() for path in (root,state,out,learn_root,model_root) for p in (path,*path.parents)),"A4_ROOT_SYMLINK")
    resolved=[p.resolve() for p in (root,state,out)]
    market.need(all(not a.is_relative_to(b) and not b.is_relative_to(a)
                    for i,a in enumerate(resolved) for b in resolved[:i]),"A4_INPUT_STATE_OUTPUT_OVERLAP")
    for packet_root,reason in ((learn_root,"A4_LEARNING_STATE_OUTPUT_OVERLAP"),
                               (model_root,"A5_INPUT_STATE_OUTPUT_OVERLAP")):
        packet_path=packet_root.resolve()
        market.need(all(not packet_path.is_relative_to(p) and not p.is_relative_to(packet_path)
                        for p in resolved[1:]),reason)
    market.need(not out.exists(),"A4_ATTEMPT_ALREADY_EXISTS")
    out.mkdir(parents=True)
    try:
        raw_pin=market.bounded(root/"request.sha256",128).decode("ascii").strip()
    except (OSError,ValueError,UnicodeError):raw_pin=None
    a5=None
    a5_request=None;replay_cutoff=cutoff
    if scope=="A4_A5":
        from tools import a5_model_portfolio as a5
        try:
            a5_request=market.clock.decode(market.bounded(model_root/"a5_request.json",256*1024))
            replay_cutoff=a5.decision_cutoff(model_root,a5_request,expected_policy_sha256=a5_policy_sha256,execution_at=cutoff)
        except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
            a5_request=None
    try:
        # Replay at the fixed decision while checking freshness and expiry at
        # actual execution time. Never refresh a past graph's timestamp/hash.
        raw_request=market.bounded(root/"request.json",256*1024)
        market.verify_request(raw_request,raw_pin,cutoff,market.current_session(cutoff))
        report=market.load_report(root/"request.json",root,raw_pin,cutoff=replay_cutoff)
    except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
        report=market.blocked("MARKET_INPUT_UNAVAILABLE_INVALID_OR_EXPIRED",cutoff=cutoff,session=market.current_session(cutoff))
    events=[];status="BLOCKED";blockers=[];scores=[];predictions=[]
    learning_context=None;daily_direction=None
    try:
        payload,policy,resolve=load_learning(learn_root,learning_policy_sha256)
        market.need(market.clock.stamp(policy['available_at'])<=market.clock.stamp(cutoff)<market.clock.stamp(policy['expires_at']),
                    'A4_LEARNING_POLICY_NOT_CURRENT_AT_EXECUTION')
        market.need(market.clock.stamp(payload["cutoff"])<=market.clock.stamp(cutoff) and
                    payload["sessions"][-1]["session"]==market.current_session(cutoff),"A4_LEARNING_NOT_CURRENT_SESSION")
        if policy.get('daily_direction_protocol_sha256') is not None:
            market.need(scope=="A4_ONLY","A4_DAILY_DIRECTION_SCOPE")
            from tools import a4_daily_direction as direction
            plan=learning.cadence(cutoff)
            prepared=direction.prepare(payload,policy,digest(encoded(policy)),resolve)
            daily_direction=direction.daily_journal(prepared,state)
            events.append(dict(kind="DAILY_BENCHMARK_JOURNAL_RECORDED",
                               checkpoint_sha256=daily_direction["checkpoint_sha256"]))
        else:
            trials=restored_trials(state,cutoff)
            previous=max((t["month"] for t in trials),default=None)
            plan=learning.cadence(cutoff,previous_training_month=previous)
            # Weekly checks score fixed past predictions, not a newly fitted model.
            weekly_path=state/"weekly"
            weeks=[]
            if weekly_path.exists():
                files=list(weekly_path.iterdir())
                market.need(len(files)<=MAX_STATE_FILES,"A4_STATE_FILE_BUDGET")
                for file in files:
                    value=market.clock.decode(market.bounded(file,MAX_CHECKPOINT_BYTES))
                    market.need(file.name==digest(encoded(value))+".json","A4_WEEKLY_STATE_HASH")
                    market.need(market.clock.stamp(value["cutoff"])<=market.clock.stamp(cutoff),"A4_FUTURE_WEEKLY_STATE")
                    weeks.append(value["week"])
            plan["weekly_score_due"]=plan["week"] not in weeks
            learning.validate_inputs(payload,policy,digest(encoded(policy)),resolve)
            if plan["monthly_trial_due"]:
                trial=learning.fit_trial(payload,policy,digest(encoded(policy)),resolve)
                receipt=learning.store_trial(trial,state)
                trials.append(trial);events.append(dict(kind="MONTHLY_CHALLENGER_STORED",**receipt))
            active=policy.get("active_trial_sha256")
            if active:
                matching=[t for t in trials if t["trial_sha256"]==active]
                market.need(len(matching)==1,"A4_FIXED_RELEASE_NOT_RESTORED")
                market.need(report.get("schema")=="market-analysis-report-v2","A4_V2_REPORT_REQUIRED")
                # Keep the native request-replay report immutable for the existing
                # A3/A6 graph. An independently pinned auxiliary view is separate
                # until its release is explicitly included in an A4 request.
                learning_context=copy.deepcopy(report)
                forward=load_forward_context(learn_root,policy) if matching[0].get('dated_vintage_sources') else {}
                predictions=learning.forecast_release(learning_context,matching[0],policy,digest(encoded(policy)),created_at=cutoff,**forward)
                if handoff := learning_context.get("review_handoff"):
                    from tools.a4_macro_diagnosis import review_handoff
                    learning_context["review_handoff"] = review_handoff(
                        learning_context, expires_at=handoff["expires_at"], entry_close_at=handoff["entry_close_at"],
                        release_expires_at=policy["expires_at"])
                    learning_context.pop("content_sha256", None)
                    learning_context["content_sha256"] = market.context.digest(learning_context)
            forecast_root=state/"predictions"
            if plan["weekly_score_due"]:
                old=[]
                if forecast_root.exists():
                    files=list(forecast_root.iterdir())
                    market.need(len(files)<=MAX_STATE_FILES,"A4_STATE_FILE_BUDGET")
                    for file in files:
                        item=market.clock.decode(market.bounded(file,MAX_CHECKPOINT_BYTES))
                        market.need(file.name==digest(encoded(item))+".json","A4_PREDICTION_HASH")
                        old.extend(item["predictions"])
                market.need(len(old)<=100000,"A4_PREDICTION_BUDGET")
                scores=learning.score_predictions(old,payload["prices"],payload["sessions"],cutoff)
                weekly=dict(schema="a4-weekly-score-v1",week=plan["week"],cutoff=cutoff,scores=scores)
                store_checkpoint(weekly_path/(digest(encoded(weekly))+".json"),weekly)
                events.append(dict(kind="WEEKLY_FIXED_PREDICTIONS_SCORED",count=len(scores)))
            if predictions:
                snapshot=dict(schema="a4-forward-predictions-v1",cutoff=cutoff,predictions=predictions)
                store_checkpoint(forecast_root/(digest(encoded(snapshot))+".json"),snapshot)
        status="RESEARCH_CYCLE_COMPLETE"
    except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
        blockers.append("LEARNING_INPUT_POLICY_STATE_OR_ORIGINALS_NOT_VERIFIED")
        plan=learning.cadence(cutoff)
    portfolio=None
    a5_executed=False
    if a5 is not None:
        portfolio=a5.blocked(cutoff,["CURRENT_A5_MODEL_REQUEST_AND_REVIEWED_INPUTS_REQUIRED"])
        try:
            market.need(a5_request is not None,"A5_FIXED_DECISION_NOT_VERIFIED")
            a5_executed=True
            portfolio=a5.load_and_build(model_root,a5_request,report,expected_policy_sha256=a5_policy_sha256,code_sha=code_sha,
                                        execution_at=cutoff)
        except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
            pass
        exclusive(out/"model_portfolio.json",encoded(portfolio))
        exclusive(out/"model_portfolio.md",a5.render(portfolio).encode("utf-8"))
        if portfolio["status"]=="RESEARCH_PROPOSAL":
            exclusive(state/"model_proposals"/(portfolio["proposal_sha256"]+".json"),encoded(portfolio))
    exclusive(out/"market_analysis.json",encoded(report))
    exclusive(out/"market_analysis.md",market.render_report(report).encode("utf-8"))
    if learning_context is not None:
        exclusive(out/"learning_context.json",encoded(learning_context))
        exclusive(out/"learning_context.md",market.render_report(learning_context).encode("utf-8"))
    cycle=dict(schema="a4-cloud-research-cycle-v1",cutoff=cutoff,decision_cutoff=report["cutoff"],market_session=report["session"],
        market_status=report["status"],learning_status=status,learning_blockers=blockers,
        scope=scope,completion_scope="A4_CYCLE" if scope=="A4_ONLY" else "A4_A5_CYCLE",
        a5_status=portfolio["status"] if portfolio is not None else "NOT_REQUESTED",
        a5_blockers=portfolio.get("reasons",[]) if portfolio is not None else [],
        a5_executed=a5_executed,fixed_forecast_count=len(predictions),
        quantitative_outlook_status=("BLOCKED" if blockers else
                                     "REVIEWED_FIXED_RELEASE" if predictions else "INSUFFICIENT_EVIDENCE"),
        cadence=plan,events=events,source_collection_requests=0,
        process_host_dependency="GITHUB_HOSTED_RUNNER_ONLY",durable_remote_verified=False,
        accepted_model_changed=False,accepted_portfolio_changed=False,orders_generated=False)
    if daily_direction is not None:
        cycle["daily_direction_journal"]=daily_direction
        cycle["quantitative_outlook_status"]=(
            "FROZEN_DAILY_RESEARCH" if daily_direction["current_forecasts"] else "INSUFFICIENT_EVIDENCE")
    a4_cycle_complete=(report.get("schema")=="market-analysis-report-v2" and report["status"]=="READY_RESEARCH_ONLY"
                 and bool(report.get("enhanced_readiness"))
                 and all(report["enhanced_readiness"].values()) and not blockers)
    cycle["a4_cycle_status"]="COMPLETE_RESEARCH_ONLY" if a4_cycle_complete else "PARTIAL_RESEARCH"
    complete=a4_cycle_complete and (scope=="A4_ONLY" or portfolio["status"]=="RESEARCH_PROPOSAL")
    cycle["status"]="COMPLETE_RESEARCH_ONLY" if complete else "PARTIAL_RESEARCH"
    exclusive(out/"cycle.json",encoded(cycle))
    return cycle


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root",required=True)
    parser.add_argument("--learning-input-root",default=None)
    parser.add_argument("--a5-input-root",help="Restored A5 packet directory for combined scope; defaults to --input-root")
    parser.add_argument("--state-root",required=True)
    parser.add_argument("--output-dir",required=True)
    parser.add_argument("--cutoff",default=None)
    parser.add_argument("--scope",choices=SCOPES,default="A4_A5")
    args=parser.parse_args()
    cutoff=args.cutoff or datetime.now(timezone.utc).isoformat()
    try:
        result=run_cycle(input_root=args.input_root,state_root=args.state_root,output_dir=args.output_dir,
                         cutoff=cutoff,learning_policy_sha256=os.environ.get("A4_LEARNING_POLICY_SHA256"),
                         a5_policy_sha256=os.environ.get("A5_MODEL_POLICY_SHA256") if args.scope=="A4_A5" else None,
                         code_sha=os.environ.get("GITHUB_SHA"),learning_input_root=args.learning_input_root,
                         a5_input_root=args.a5_input_root,scope=args.scope)
        print(json.dumps({k:result[k] for k in ("status","scope","a4_cycle_status","market_status",
                                              "learning_status","learning_blockers","quantitative_outlook_status")}))
        return 0 if result["status"]=="COMPLETE_RESEARCH_ONLY" else 2
    except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
        print('{"status":"BLOCKED","blocker":"A4_RESEARCH_ATTEMPT_INVALID"}')
        return 2


if __name__=="__main__":raise SystemExit(main())

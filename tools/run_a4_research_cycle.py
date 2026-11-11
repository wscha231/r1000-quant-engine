#!/usr/bin/env python3
"""Cloud-capable daily diagnosis, weekly scores and monthly challenger trials.

Uses restored, hash-bound originals only. No provider calls, model promotion,
accepted portfolio state or credentials are created by this process. Durable
Drive persistence/readback belongs to the existing hosted workflow.
"""
from __future__ import annotations

import argparse
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


def load_learning(root, expected_policy_sha256):
    market.need(type(expected_policy_sha256) is str and re.fullmatch(r"[a-f0-9]{64}",expected_policy_sha256),
                "A4_LEARNING_EXTERNAL_POLICY_REQUIRED")
    raw=market.bounded(Path(root)/"learning_request.json",256*1024)
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


def run_cycle(*, input_root, state_root, output_dir, cutoff,
              learning_policy_sha256=None):
    root,state,out=Path(input_root),Path(state_root),Path(output_dir)
    market.need(not any(p.is_symlink() for path in (root,state,out) for p in (path,*path.parents)),"A4_ROOT_SYMLINK")
    resolved=[p.resolve() for p in (root,state,out)]
    market.need(all(not a.is_relative_to(b) and not b.is_relative_to(a)
                    for i,a in enumerate(resolved) for b in resolved[:i]),"A4_INPUT_STATE_OUTPUT_OVERLAP")
    market.need(not out.exists(),"A4_ATTEMPT_ALREADY_EXISTS")
    out.mkdir(parents=True)
    try:
        raw_pin=market.bounded(root/"request.sha256",128).decode("ascii").strip()
    except (OSError,ValueError,UnicodeError):raw_pin=None
    report=market.load_report(root/"request.json",root,raw_pin,cutoff=cutoff)
    events=[];status="BLOCKED";blockers=[];scores=[];predictions=[]
    try:
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
        payload,policy,resolve=load_learning(root,learning_policy_sha256)
        market.need(market.clock.stamp(payload["cutoff"])<=market.clock.stamp(cutoff) and
                    payload["sessions"][-1]["session"]==market.current_session(cutoff),"A4_LEARNING_NOT_CURRENT_SESSION")
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
            predictions=learning.forecast_release(report,matching[0],policy,digest(encoded(policy)),created_at=cutoff)
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
    exclusive(out/"market_analysis.json",encoded(report))
    exclusive(out/"market_analysis.md",market.render_report(report).encode("utf-8"))
    cycle=dict(schema="a4-cloud-research-cycle-v1",cutoff=cutoff,market_session=report["session"],
        market_status=report["status"],learning_status=status,learning_blockers=blockers,
        cadence=plan,events=events,source_collection_requests=0,
        process_host_dependency="GITHUB_HOSTED_RUNNER_ONLY",durable_remote_verified=False,
        accepted_model_changed=False,accepted_portfolio_changed=False,orders_generated=False)
    complete=(report.get("schema")=="market-analysis-report-v2" and report["status"]=="READY_RESEARCH_ONLY"
              and all(report.get("enhanced_readiness",{}).values()) and not blockers)
    cycle["status"]="COMPLETE_RESEARCH_ONLY" if complete else "PARTIAL_RESEARCH"
    exclusive(out/"cycle.json",encoded(cycle))
    return cycle


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root",required=True)
    parser.add_argument("--state-root",required=True)
    parser.add_argument("--output-dir",required=True)
    parser.add_argument("--cutoff",default=None)
    args=parser.parse_args()
    cutoff=args.cutoff or datetime.now(timezone.utc).isoformat()
    try:
        result=run_cycle(input_root=args.input_root,state_root=args.state_root,output_dir=args.output_dir,
                         cutoff=cutoff,learning_policy_sha256=os.environ.get("A4_LEARNING_POLICY_SHA256"))
        print(json.dumps({k:result[k] for k in ("status","market_status","learning_status","learning_blockers")}))
        return 0 if result["status"]=="COMPLETE_RESEARCH_ONLY" else 2
    except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
        print('{"status":"BLOCKED","blocker":"A4_RESEARCH_ATTEMPT_INVALID"}')
        return 2


if __name__=="__main__":raise SystemExit(main())

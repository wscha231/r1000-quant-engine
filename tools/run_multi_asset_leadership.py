#!/usr/bin/env python3
"""Publish immutable research attempts; failure never advances last-success.

Input mode requires an externally supplied byte pin. Capture mode uses a bounded
public provider and is CURRENT_ONLY: downloaded adjusted history is not PIT.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from research.multi_asset_v1.contracts import ContractError, digest, encoded, load_json, number, require, stamp
from research.multi_asset_v1.runtime import render, run
from research.multi_asset_v1.prices import grid
from research.multi_asset_v1.sources import capture_crypto,capture_spot_metrics
from research.multi_asset_v1.fundamentals import capture_fundamentals
from tools.macro_history_sources import request_bytes, exclusive


def a3_artifacts(payload, artifact_root):
    """Load existing caller-held evidence through the bounded A2 file loader."""
    from tools.run_a2_research_intake import Files
    from research.a2_research_intake_v1 import MemoryArtifacts, IntakeError, MAX_ARTIFACTS
    entries=payload.get("artifact_files",[])
    require(type(entries) is list and len(entries)<=MAX_ARTIFACTS,"a3_artifact_files")
    require(artifact_root is not None or not entries,"a3_artifact_root_required")
    files=Files(artifact_root) if artifact_root is not None else None
    values={}
    try:
        for row in entries:
            require(type(row) is dict and set(row)=={"artifact_id","path","sha256"},"a3_artifact_file_fields")
            aid=row["artifact_id"]
            require(type(aid) is str and aid not in values,"a3_duplicate_artifact_id")
            values[aid]=files.read({"path":row["path"],"sha256":row["sha256"]},"artifact",aid)
        return MemoryArtifacts(values)
    except IntakeError as exc:
        raise ContractError("a3_artifact_input:"+str(exc)) from None


def atomic(path, raw):
    require(not any(p.is_symlink() for p in (path,*path.parents)),"symlink_output")
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix=".attempt-")
    try:
        with os.fdopen(fd,"wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)


def parse_chart(raw, asset, collected, sessions):
    data=load_json(raw)
    require(not data["chart"].get("error"),"provider_error")
    result=data["chart"]["result"]
    require(isinstance(result,list) and len(result)==1,"provider_result")
    chart=result[0]
    meta=chart["meta"]
    require(meta.get("symbol")==asset["symbol"] and meta.get("currency")=="USD","provider_identity_currency")
    require(meta.get("instrumentType") in {"EQUITY","ETF"},"provider_instrument")
    require(meta.get("exchangeTimezoneName")=="America/New_York","provider_exchange_timezone")
    times=chart.get("timestamp",[])
    quote=chart["indicators"]["quote"][0]
    adjusted=chart["indicators"]["adjclose"][0]["adjclose"]
    require(len(times)==len(adjusted)==len(quote["close"])==len(quote["volume"]),"provider_arrays")
    from zoneinfo import ZoneInfo
    rows=[]
    seen=set()
    for i,t in enumerate(times):
        number(t,0)
        session=datetime.fromtimestamp(t,ZoneInfo("America/New_York")).date().isoformat()
        require(session not in seen,"provider_duplicate_session")
        seen.add(session)
        if session not in sessions: continue
        if adjusted[i] is None or quote["close"][i] is None: continue
        # Preserve actual close separately from vendor dividend/split adjusted series.
        rows.append({"asset_id":asset["asset_id"],"session":session,"clock":"NYSE_CLOSE",
            "price":number(quote["close"][i],0),"total_return_index":number(adjusted[i],0),
            "volume":None if quote["volume"][i] is None else number(quote["volume"][i],0),
            "return_basis":"PROVIDER_ADJUSTED_CLOSE_PROXY","return_method":"PROVIDER_ADJUSTED_CLOSE_PROXY",
            "unit":asset["price_unit"],"currency":"USD","corporate_action_quarantine":asset.get("corporate_action_quarantine",True),
            "observed_at":sessions[session].isoformat(),"available_at":collected,"collected_at":collected,
            "source":"YAHOO_CHART","data_quality":"OBSERVED","evidence_kind":"FORWARD_CAPTURE",
            "raw_sha256":hashlib.sha256(raw).hexdigest()})
    return rows


def capture(registry, attempt, fetcher=request_bytes):
    started=datetime.now(timezone.utc).isoformat()
    sessions=grid(started)
    rows=[]
    receipts=[]
    for asset in registry["assets"]:
        if asset["asset_class"]=="CRYPTO":
            crypto_rows,crypto_receipts=capture_crypto(asset,sessions,attempt,fetcher)
            rows.extend(crypto_rows);receipts.extend(crypto_receipts)
            continue
        try:
            url="https://query1.finance.yahoo.com/v8/finance/chart/"+asset["symbol"]+"?"+urlencode({"range":"2y","interval":"1d","events":"div,splits"})
            raw=fetcher(url)
            collected=datetime.now(timezone.utc).isoformat()
            parsed=parse_chart(raw,asset,collected,sessions)
            raw_hash=hashlib.sha256(raw).hexdigest()
            exclusive(attempt/"raw"/raw_hash,raw)
            rows.extend(parsed)
            receipts.append({"asset_id":asset["asset_id"],"status":"CAPTURED_CURRENT_ONLY", "rows":len(parsed),"raw_sha256":raw_hash})
        except Exception as exc:
            # Provider exceptions can contain URLs/credentials. Persist only controlled labels.
            receipts.append({"asset_id":asset["asset_id"],"status":"BLOCKED","reason":str(exc) if isinstance(exc,ContractError) else "provider_unavailable_or_schema"})
    metrics,metric_receipts=capture_spot_metrics(attempt,fetcher)
    fundamental_rows,fundamental_receipts=capture_fundamentals(attempt,fetcher)
    metrics.extend(fundamental_rows)
    metric_receipts.extend(fundamental_receipts)
    payload={"schema":"multi-asset-input-v1","as_of":datetime.now(timezone.utc).isoformat(),
             "prices":rows,"metrics":metrics,"events":[],"evaluations":[],"base_equity_ids":[],"collection_receipts":receipts+metric_receipts}
    exclusive(attempt/"input.json",encoded(payload))
    return payload


def fully_admitted(result):
    proposal=result.get("proposal",{})
    scoped=result.get("stock_research",{}).get("decision_scope",{})
    explicit_scope=(proposal.get("scope")=="EXPLICIT_STOCK_REVIEW_SCOPE" and
        scoped.get("numeric_scope_status")=="SCOPED_INPUTS_OBSERVED" and
        bool(scoped.get("decision_asset_ids")) and
        proposal.get("decision_scope_asset_ids")==scoped["decision_asset_ids"])
    return ((result.get("global_ranking_ready") is True or explicit_scope) and
            proposal.get("status")=="RESEARCH_PROPOSAL" and result.get("code_identity_verified") is True)


def configuration_bytes(path, expected_sha256, repository_path):
    raw=path.read_bytes()
    if expected_sha256 is not None:
        require(hashlib.sha256(raw).hexdigest()==expected_sha256,"configuration_hash_mismatch")
    else:
        require(path.resolve()==(ROOT/repository_path).resolve(),"custom_configuration_requires_external_hash")
        reviewed=subprocess.check_output(["git","show","HEAD:"+repository_path],cwd=ROOT)
        require(raw==reviewed,"configuration_differs_from_repository_head")
    return raw


def verified_source_hashes(code_sha):
    require(isinstance(code_sha,str) and re.fullmatch(r"[a-f0-9]{40}",code_sha),"commit_identity_required")
    paths={*sorted((ROOT/"research/multi_asset_v1").glob("*.py")),ROOT/"tools/run_multi_asset_leadership.py",
           ROOT/"tools/macro_history_sources.py",ROOT/"research/theme_etf_runtime_v1/strict.py",
           ROOT/"research/theme_etf_runtime_v1/runtime.py",ROOT/"r1000_legacy_input_guard.py",
           ROOT/"tools/run_a2_research_intake.py",ROOT/"research/a2_research_intake_v1.py",
           ROOT/"research/a3_candidate_packet_v1.py",ROOT/"research/candidate_registry_v1.py",
           ROOT/"research/er_horizon_v1.py"}
    paths.update(ROOT/name for name in ("tools/run_agent_board.py", "mission_contract.py",
        "r1000_config.py", "research/control_plane/agent_contracts_v2.yaml",
        "research/control_plane/task_packet_schema.json", "research/control_plane/system_state_schema.json",
        "tools/market_analysis_engine.py", "tools/free_market_context.py",
        "tools/a4_liquidity_analysis.py", "tools/a4_macro_bridge.py",
        "tools/a5_model_portfolio.py",
        "tools/a4_macro_learning.py", "tools/macro_technical_study.py",
        "tools/run_a4_research_cycle.py",
        "docs/market_analysis_contract_v2.json",
        "tools/chameleon_market_context_v2.py", "tools/build_run287_chameleon_macro_risk.py",
        "tools/daily_crisis_report_clock.py", "docs/market_analysis_contract_v1.json",
        "tools/build_run287_chameleon_macro_inputs.py", "tools/candidate_reassessment_bridge.py",
        "r1000_helpers.py", "docs/run287_chameleon_macro_risk_contract.json",
        "tools/run_broker_ledger_replay.py", "tools/run287_hold_exit_policy.py",
        "tools/security_lifecycle.py"))
    paths.update(p for p in (ROOT/"research/__init__.py",ROOT/"tools/__init__.py",ROOT/"research/theme_etf_runtime_v1/__init__.py") if p.exists())
    hashes={}
    for path in sorted(paths):
        relative=path.relative_to(ROOT).as_posix();raw=path.read_bytes()
        try:
            expected=subprocess.check_output(["git","show",code_sha+":"+relative],cwd=ROOT,stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            raise ContractError("source_not_in_claimed_commit:"+relative) from None
        require(raw==expected,"source_differs_from_claimed_commit:"+relative)
        hashes[relative]=hashlib.sha256(raw).hexdigest()
    return hashes


def _model_originals(root, cutoff, now):
    """Bounded existing artifact checks; a descriptor is not acceptance."""
    from tools import run_agent_board as board
    require(root is not None,"model_artifact_root_required")
    cache,used={},{}
    def read(ref, *, json_value=True):
        board.schema_validate(ref,"task_packet_schema.json","artifact")
        key=digest(ref)
        path=board.artifact_path(root,ref["path"])
        if ref["path"] in used:
            require(digest(used[ref["path"]])==key,"model_artifact_conflict")
        if key not in cache:
            require(path.stat().st_size<=4*1024*1024,"model_artifact_budget")
            require(sum(len(raw) for raw in cache.values())+path.stat().st_size<=32*1024*1024,
                    "model_artifact_budget")
            board.verify_artifact(root,ref,cutoff,now)
            with path.open("rb") as stream: raw=stream.read(4*1024*1024+1)
            require(len(raw)<=4*1024*1024 and hashlib.sha256(raw).hexdigest()==ref["sha256"],
                    "model_original_changed")
            cache[key]=raw;used[ref["path"]]=ref
        return load_json(cache[key]) if json_value else cache[key]
    return read,used


def _model_context(result, context_ref, read):
    review=result.get("a3_reference_coverage",{}).get("current_review",{})
    require(review.get("context_sha256")==context_ref["sha256"],"model_context_not_current_review")
    context=read(context_ref)
    require(stamp(context["decision_time"])==stamp(result["computed_at"]),"model_context_cutoff")
    return context


def _model_origin(selection, read, cutoff):
    """Replay original A5 completion through the existing completion verifier."""
    from tools import run_agent_board as board
    packet=read(selection["a5_packet"]);receipt=read(selection["a5_receipt"])
    board.schema_validate(packet,"task_packet_schema.json")
    spec=board.contracts()["agents"]["A5"]
    require(packet["agent"]==receipt["agent"]=="A5" and receipt["status"]=="SUCCEEDED"
            and packet["task_key"]==receipt["task_key"]
            and packet["task_key"]==board.digest({"agent":"A5",**packet["identity"]})
            and board.portfolio_mode({"parameters":packet["identity"]["parameters"]})=="MODEL_PORTFOLIO"
            and packet["status"] in {"READY","SKIP_UNCHANGED"} and not packet["reasons"]
            and packet["authority"]==board.AUTHORITY and packet["mode"]==spec["mode"]
            and packet["outputs"]==spec["outputs"] and set(receipt["outputs"])==set(spec["outputs"])
            and set(packet["inputs"])==set(spec["inputs"])
            and packet["dependencies"]==spec["dependencies"]
            and set(packet["dependency_outputs"])==set(spec["dependencies"]),"model_original_a5_task")
    causal=list(packet["inputs"].values())
    for agent,dep in packet["dependency_outputs"].items():
        require(dep.get("agent")==agent,"model_original_dependency")
        for role,ref in dep["outputs"].items():
            require(packet["inputs"].get(role)==ref,"model_original_dependency")
        causal.extend(dep["outputs"].values())
    for ref in causal+list(receipt["outputs"].values()): read(ref,json_value=False)
    ready=max(stamp(ref["collected_at"]) for ref in causal)
    board.verify_completion(receipt,packet["identity"],dict(agent="A5",inputs=packet["inputs"]),
                            packet["dependency_outputs"],ready,cutoff)
    require(stamp(receipt["available_at"])<=stamp(selection["a5_receipt"]["observed_at"]),
            "model_original_receipt_clock")
    context=read(packet["inputs"]["portfolio_context"])
    board.schema_validate(context,"system_state_schema.json","a5_portfolio_context")
    return packet,receipt,context


def _model_bytes(path, limit, reason):
    with path.open("rb") as stream: raw=stream.read(limit+1)
    require(len(raw)<=limit,reason)
    return raw


def _model_source_pair(receipt_raw, result_raw, packet, context_ref):
    """The physical published pair must name this exact original A5 task."""
    receipt,result=load_json(receipt_raw),load_json(result_raw)
    review=result.get("a3_reference_coverage",{}).get("current_review",{})
    require(_published_readiness(receipt,result)
            and receipt.get("result_sha256")==hashlib.sha256(result_raw).hexdigest(),
            "model_original_publication_pair")
    require(review.get("task_keys",{}).get("A5")==packet["task_key"]
            and packet["inputs"]["portfolio_context"]==context_ref
            and review.get("context_sha256")==context_ref["sha256"]
            and result.get("code_sha")==packet["identity"]["code_sha"],
            "model_published_a5_origin_mismatch")
    return result


def _model_candidate_source(candidate, selection, read, original_packet, original_receipt, *, candidate_observed_at):
    """Recheck physical original bytes, never the candidate's SHA strings alone."""
    require(all(k in candidate for k in ("proposal_receipt","proposal_result","portfolio_context")),
            "model_source_refs_required")
    source_refs=[candidate["proposal_receipt"],candidate["proposal_result"],candidate["portfolio_context"]]
    receipt_raw=read(source_refs[0],json_value=False)
    result_raw=read(source_refs[1],json_value=False)
    result=_model_source_pair(receipt_raw,result_raw,original_packet,source_refs[2])
    _model_context(result,source_refs[2],read)
    require(hashlib.sha256(receipt_raw).hexdigest()==candidate["proposal_receipt_sha256"]
            ==selection["proposal_receipt_sha256"]
            and hashlib.sha256(result_raw).hexdigest()==candidate["proposal_result_sha256"]
            and max(stamp(result["computed_at"]),stamp(original_receipt["available_at"]))
                <=stamp(selection["selected_at"])
            and candidate.get("publication_clock_scope")=="PREPARE_READ_OBSERVATION_NOT_ORIGINAL_COLLECTION_OR_PUBLICATION",
            "model_original_publication_pair")
    for ref in source_refs[:2]:
        require(all(ref[k]==candidate["publication_read_at"] for k in ("observed_at","available_at","collected_at"))
                and stamp(result["computed_at"])<=stamp(candidate["publication_read_at"])
                    <=stamp(candidate_observed_at)
                and stamp(ref["expires_at"])<=stamp(candidate["state"]["expires_at"]),
                "model_source_observation_clock")
    return source_refs


def prepare_model_parent_read_observation(policy,review_root,*,now):
    """Read exact last-parent bytes for a PARENT_LINEAGE_ONLY context.

    This is not model acceptance or renewed QA. The dedicated board verifier
    must still replay all original proofs at their original accepted clock.
    """
    from tools import run_agent_board as board
    parent=policy.get("model_lineage_parent")
    require(type(parent) is dict and parent.get("purpose")=="PARENT_LINEAGE_ONLY" and
            stamp(parent["available_at"])<=stamp(now)<stamp(parent["expires_at"]),
            "model_explicit_parent_policy_required")
    ref=parent["acceptance"]
    board.schema_validate(ref,"task_packet_schema.json","artifact")
    raw=_model_bytes(board.artifact_path(review_root,ref["path"]),4*1024*1024,"model_parent_byte_budget")
    require(hashlib.sha256(raw).hexdigest()==ref["sha256"],"model_parent_original_changed")
    value=load_json(raw)
    board.schema_validate(value,"system_state_schema.json","model_incumbents_acceptance")
    require(digest(value) in policy["reviewed_pins"].get("positions",[]) and
            value["proofs"]["state"]["sha256"]==parent["state_sha256"] and
            digest(value["model_identity"])==parent["model_identity_sha256"],"model_parent_external_pin_required")
    observed=dict(path=ref["path"],sha256=ref["sha256"],observed_at=now,available_at=now,
        collected_at=now,expires_at=parent["expires_at"],status="VERIFIED")
    return dict(purpose="PARENT_LINEAGE_ONLY",artifact=observed,original_descriptor=ref,
                byte_hash_verified=True,acceptance_or_fresh_er_granted=False)


def prepare_model_snapshot(proposal_out, out, attempt_id=None, *, proposal_receipt_sha256,
                           owner_decision, portfolio_context, review_root, policy, now):
    """Seal an unaccepted MODEL candidate. This never issues its acceptance pin.

    The existing proposal must already be admitted and immutable. An OWNER
    selection is only pending review here; a later independent post-A5 QA and
    external whole-acceptance pin are still required for consumption.
    """
    from tools import run_agent_board as board
    cutoff=stamp(now)
    source_path=proposal_out/"latest_attempt.json"
    source_raw=_model_bytes(source_path,256*1024,"model_proposal_receipt_budget")
    require(hashlib.sha256(source_raw).hexdigest()==proposal_receipt_sha256,
            "model_proposal_receipt_external_hash")
    source=load_json(source_raw)
    require(type(source.get("attempt_id")) is str and source["attempt_id"]
            and all(c.isalnum() or c in "-_" for c in source["attempt_id"]),"attempt_id")
    original_receipt_path=proposal_out/"attempts"/source["attempt_id"]/"receipt.json"
    original_result_path=proposal_out/"attempts"/source["attempt_id"]/"result.json"
    require(_model_bytes(original_receipt_path,256*1024,"model_proposal_receipt_budget")==source_raw,
            "model_proposal_receipt_not_immutable")
    source_result_raw=_model_bytes(original_result_path,4*1024*1024,"model_proposal_result_budget")
    require(hashlib.sha256(source_result_raw).hexdigest()==source["result_sha256"],
            "model_original_publication_pair")
    def source_unchanged():
        require(_model_bytes(source_path,256*1024,"model_proposal_receipt_budget")==source_raw
                and _model_bytes(original_receipt_path,256*1024,"model_proposal_receipt_budget")==source_raw
                and _model_bytes(original_result_path,4*1024*1024,"model_proposal_result_budget")==source_result_raw,
                "model_original_publication_changed")
    result=read_latest(proposal_out,consumed_at=now)
    require(encoded(result)==source_result_raw,"model_original_publication_changed")
    source_unchanged()
    require(digest(policy)==result["policy_sha256"],"model_proposal_policy_mismatch")
    read,used=_model_originals(review_root,cutoff,cutoff)
    selection=read(owner_decision)
    board.schema_validate(selection,"system_state_schema.json","model_allocation_selection")
    require(selection["proposal_receipt_sha256"]==proposal_receipt_sha256,
            "model_selection_proposal_mismatch")
    context=_model_context(result,portfolio_context,read)
    packet,receipt,original_context=_model_origin(selection,read,cutoff)
    _model_source_pair(source_raw,source_result_raw,packet,portfolio_context)
    require(max(stamp(receipt["available_at"]),stamp(result["computed_at"]))<=stamp(selection["selected_at"])
            <=stamp(owner_decision["observed_at"])<=cutoff<stamp(selection["expires_at"]),
            "model_selection_clock")
    state=dict(schema_version="model-allocation-state-v1",state_role="MODEL_ALLOCATION_STATE",
        model_identity=selection["model_identity"],as_of=original_context["market_session_date"],
        decision_time=original_context["decision_time"],positions=selection["positions"],
        cash_weight=selection["cash_weight"],origin_a5_task_key=packet["task_key"],
        actual_holdings_claimed=False,execution_or_performance_claimed=False)
    board.schema_validate(state,"system_state_schema.json","model_allocation_state")
    weights={r["asset_id"]:number(r["weight"],0,1) for r in state["positions"]}
    require(len(weights)==len(state["positions"]) and set(weights)<=set(original_context["requested_security_ids"])
            and abs(sum(weights.values())+number(state["cash_weight"],0,1)-1)<=1e-9,
            "model_selection_weights")
    previous=None
    if context["model_state"]["kind"]=="INCUMBENTS":
        previous=board.verify_current_model_incumbents(context,review_root,stamp(result["computed_at"]),
            cutoff,policy=policy,code_sha=result["code_sha"])
    elif context["model_state"]["kind"]=="PARENT_LINEAGE_ONLY":
        previous=board.verify_model_parent_lineage(context,review_root,stamp(result["computed_at"]),
            cutoff,policy=policy,code_sha=result["code_sha"])
    same_allocation=previous is not None and digest(weights)==digest(previous["current_weights"]) and (
        digest(state["cash_weight"])==digest(previous["cash_weight"])) and (
        digest(state["model_identity"])==digest(previous["model_identity"]))
    fresh_decision=previous is not None and packet["task_key"]!=previous["origin_a5_task_key"] and (
        stamp(state["decision_time"])>stamp(previous["decision_time"])) and (
        digest(packet["inputs"])!=previous["original_a5_inputs_sha256"])
    # Repeating the SAME original selection uses the immutable attempt below.
    # A new source A5 consumes a parent; it cannot be its parent's producer.
    require(selection["change_kind"]!="NO_CHANGE","model_no_change_use_original_attempt")
    if selection["change_kind"]=="REAFFIRM_HOLD":
        require(same_allocation and fresh_decision,"model_hold_requires_new_current_assessment")
    else:
        require(not same_allocation and (previous is None or fresh_decision),"model_allocation_requires_new_assessment")
    parent_bodies={}
    state.update(assessment_kind="INITIAL_ALLOCATION" if previous is None else
                 "HOLD_REAFFIRMATION" if same_allocation else "ALLOCATION_CHANGE",
                 assessment_source_sha256=proposal_receipt_sha256,
                 assessment_inputs_sha256=digest(packet["inputs"]))
    if previous is not None:
        # Exact historical bytes are lineage, not renewed parent authority.
        for role in ("parent_acceptance","parent_state"):
            ref=previous[role]
            body=_model_bytes(board.artifact_path(review_root,ref["path"]),4*1024*1024,"model_parent_byte_budget")
            require(hashlib.sha256(body).hexdigest()==ref["sha256"],"model_parent_original_changed")
            parent_bodies[role]=body
        state.update(parent_state_sha256=hashlib.sha256(parent_bodies["parent_state"]).hexdigest(),
                     parent_acceptance_sha256=hashlib.sha256(parent_bodies["parent_acceptance"]).hexdigest())
    board.schema_validate(state,"system_state_schema.json","model_allocation_state")
    identity=digest(dict(a5_task_key=packet["task_key"],state_sha256=digest(state),
        owner_decision_sha256=owner_decision["sha256"],proposal_receipt_sha256=proposal_receipt_sha256))
    expected_attempt="model-"+identity[:32]
    require(attempt_id is None or attempt_id==expected_attempt,"model_candidate_attempt_identity")
    attempt_id=expected_attempt
    require(out.resolve().is_relative_to(review_root.resolve()),"model_output_outside_artifact_root")
    target=out/"attempts"/attempt_id
    require(not any(p.is_symlink() for p in (target,*target.parents)),"symlink_output")
    raw=encoded(state)
    expiry=min([stamp(selection["expires_at"])]+[stamp(ref["expires_at"]) for ref in used.values()])
    require(cutoff<expiry,"model_candidate_expired")
    state_ref=dict(path=(target/"model_state.json").relative_to(review_root).as_posix(),
        sha256=hashlib.sha256(raw).hexdigest(),observed_at=now,available_at=now,collected_at=now,
        expires_at=expiry.isoformat(),status="VERIFIED")
    def observed_copy(name, body):
        return dict(path=(target/name).relative_to(review_root).as_posix(),
            sha256=hashlib.sha256(body).hexdigest(),observed_at=now,available_at=now,collected_at=now,
            expires_at=expiry.isoformat(),status="VERIFIED")
    candidate=dict(schema="model-snapshot-candidate-receipt-v1",attempt_id=attempt_id,
        status="PENDING_MODEL_REVIEW",identity=identity,
        proposal_receipt_sha256=proposal_receipt_sha256,proposal_result_sha256=source["result_sha256"],
        proposal_receipt=observed_copy("source_receipt.json",source_raw),
        proposal_result=observed_copy("source_result.json",source_result_raw),
        portfolio_context=portfolio_context,publication_read_at=now,
        publication_clock_scope="PREPARE_READ_OBSERVATION_NOT_ORIGINAL_COLLECTION_OR_PUBLICATION",
        owner_decision=owner_decision,a5_packet=selection["a5_packet"],a5_receipt=selection["a5_receipt"],
        state=state_ref,model_acceptance_issued=False,consumable=False,
        accepted_book_written=False,orders_generated=False)
    if parent_bodies:
        candidate.update(parent_clock_scope="PARENT_LINEAGE_ONLY_READ_OBSERVATION_NOT_RENEWAL")
        for role,body in parent_bodies.items():candidate[role]=observed_copy(role+".json",body)
    if target.exists():
        receipt_path=target/"receipt.json"
        require(receipt_path.is_file() and receipt_path.stat().st_size<=256*1024,
                "model_candidate_attempt_exists")
        previous_candidate=load_json(receipt_path.read_bytes())
        for role,body in [("state",raw),("proposal_receipt",source_raw),("proposal_result",source_result_raw),*parent_bodies.items()]:
            previous_ref=previous_candidate.get(role,{})
            expected_ref=candidate[role]
            require(previous_ref.get("path")==expected_ref["path"]
                    and previous_ref.get("sha256")==expected_ref["sha256"]
                    and previous_ref.get("expires_at")==expected_ref["expires_at"],"model_candidate_attempt_conflict")
            candidate[role]=previous_ref
            require(read(previous_ref,json_value=False)==body,"model_candidate_attempt_conflict")
        candidate["publication_read_at"]=previous_candidate.get("publication_read_at")
        require(candidate==previous_candidate,"model_candidate_attempt_conflict")
        source_unchanged()
        return previous_candidate  # Original clocks and receipt bytes remain untouched.
    source_unchanged()
    target.mkdir(parents=True,exist_ok=False)
    exclusive(target/"model_state.json",raw)
    exclusive(target/"source_receipt.json",source_raw)
    exclusive(target/"source_result.json",source_result_raw)
    for role,body in parent_bodies.items():exclusive(target/(role+".json"),body)
    exclusive(target/"receipt.json",encoded(candidate))
    require(load_json((target/"receipt.json").read_bytes())==candidate,"model_candidate_readback")
    require(hashlib.sha256(board.artifact_path(review_root,state_ref["path"]).read_bytes()).hexdigest()
            ==state_ref["sha256"],"model_snapshot_readback")
    for role,body in (("proposal_receipt",source_raw),("proposal_result",source_result_raw)):
        require(read(candidate[role],json_value=False)==body,"model_source_readback")
    for role,body in parent_bodies.items():
        require(read(candidate[role],json_value=False)==body,"model_parent_readback")
    return candidate


def _model_publication(payload,result,policy,review_root,code_sha,request):
    """Replay current admission and the externally accepted exact candidate."""
    from tools import run_agent_board as board
    require(type(request) is dict and set(request)=={"candidate_receipt","owner_decision"},
            "model_publication_fields")
    require(fully_admitted(result) and payload.get("position_book_kind")=="MODEL",
            "model_publication_current_research_blocked")
    cutoff=stamp(payload["as_of"])
    read,_=_model_originals(review_root,cutoff,cutoff)
    context_ref=payload["current_a3_review"]["portfolio_context"]
    context=_model_context(result,context_ref,read)
    for ref in request.values():
        require(ref in context["artifact_inventory"].values(),"model_publication_not_current_inventory")
    verified=board.verify_current_model_incumbents(context,review_root,cutoff,cutoff,
                                                  policy=policy,code_sha=code_sha)
    acceptance_ref=context["model_state"]["artifact"]
    acceptance=read(acceptance_ref)
    candidate=read(request["candidate_receipt"]);selection=read(request["owner_decision"])
    board.schema_validate(selection,"system_state_schema.json","model_allocation_selection")
    require(candidate.get("schema")=="model-snapshot-candidate-receipt-v1"
            and candidate.get("status")=="PENDING_MODEL_REVIEW" and candidate.get("consumable") is False
            and candidate["owner_decision"]==request["owner_decision"]
            and candidate["state"]==acceptance["proofs"]["state"]
            and candidate["a5_packet"]==selection["a5_packet"]==acceptance["proofs"]["a5_packet"]
            and candidate["a5_receipt"]==selection["a5_receipt"]==acceptance["proofs"]["a5_receipt"]
            and candidate["proposal_receipt_sha256"]==selection["proposal_receipt_sha256"],
            "model_candidate_acceptance_mismatch")
    state=read(candidate["state"])
    require(state.get("assessment_source_sha256")==candidate["proposal_receipt_sha256"] and
            state.get("assessment_inputs_sha256")==digest(read(candidate["a5_packet"])["inputs"]),
            "model_assessment_source_or_inputs_mismatch")
    require(all(k in candidate for k in ("proposal_receipt","proposal_result","portfolio_context")),
            "model_source_refs_required")
    source_refs=[candidate["proposal_receipt"],candidate["proposal_result"],candidate["portfolio_context"]]
    for ref in source_refs:
        require(ref in context["artifact_inventory"].values(),"model_source_not_current_inventory")
    original_packet=read(acceptance["proofs"]["a5_packet"])
    original_receipt=read(acceptance["proofs"]["a5_receipt"])
    _model_candidate_source(candidate,selection,read,original_packet,original_receipt,
                            candidate_observed_at=request["candidate_receipt"]["observed_at"])
    require(selection["change_kind"] in {"SELECT_ALLOCATION","REAFFIRM_HOLD"}
            and all(digest(selection[k])==digest(state[k]) for k in ("model_identity","positions","cash_weight"))
            and stamp(selection["selected_at"])<=stamp(request["owner_decision"]["observed_at"])
            and stamp(acceptance["expires_at"])<=stamp(selection["expires_at"]),"model_owner_selection_mismatch")
    post=read(acceptance["proofs"]["a6_receipt"])
    report=read(post["outputs"]["qa_report"])
    parent_refs=[candidate[role] for role in ("parent_acceptance","parent_state") if role in candidate]
    require(all(role in candidate and candidate[role]==acceptance["proofs"].get(role)
                for role in ("parent_acceptance","parent_state") if role in acceptance["proofs"]),
            "model_parent_acceptance_pair_mismatch")
    require(all(ref in report["reviewed_artifacts"].values() for ref in [*request.values(),*source_refs]),
            "model_owner_decision_not_post_reviewed")
    require(all(ref in report["reviewed_artifacts"].values() and ref in context["artifact_inventory"].values()
                for ref in parent_refs),"model_parent_not_post_reviewed")
    return dict(status="EXTERNALLY_ACCEPTED_MODEL_REFERENCE",artifact=acceptance_ref,
        candidate_receipt=request["candidate_receipt"],owner_decision=request["owner_decision"],
        model_identity=verified["model_identity"],expires_at=verified["expires_at"],
        comparison_allocation_only=True,accepted_model_state_written=False,
        actual_holdings_claimed=False,execution_or_performance_claimed=False)


def publish(payload, registry, policy, out, attempt_id, code_sha, *, input_sha256=None,
            configuration_sha256=None, artifact_resolver=None, review_root=None, model_publication=None):
    require(attempt_id and all(c.isalnum() or c in "-_" for c in attempt_id),"attempt_id")
    # Revoke consumption before validation, preserving last-success and its bytes.
    atomic(out/"latest_attempt.json",encoded({"status":"STARTED","attempt_id":attempt_id,"last_success_retained":True}))
    target=out/"attempts"/attempt_id
    target.mkdir(parents=True,exist_ok=False)
    try:
        source_hashes=verified_source_hashes(code_sha)
        result=run(payload,registry,policy,artifact_resolver=artifact_resolver,
                   review_root=review_root,code_sha=code_sha)
        result["code_sha"]=code_sha
        result["configuration_input_sha256"]=configuration_sha256
        require(verified_source_hashes(code_sha)==source_hashes,"source_changed_during_run")
        result["code_file_sha256"]=source_hashes
        result["code_identity_verified"]=True
        if model_publication is not None:
            result["model_allocation_publication"]=_model_publication(
                payload,result,policy,review_root,code_sha,model_publication)
        result.pop("result_sha256",None)
        result["result_sha256"]=digest(result)
        raw=encoded(result)
        exclusive(target/"result.json",raw)
        exclusive(target/"daily_monitoring_report.md",render(result).encode())
        for name in ("multi_asset_leadership_latest","commodity_market_latest","crypto_market_latest","asset_event_latest"):
            exclusive(target/(name+".json"),encoded({"as_of":result["as_of"],"computed_at":result["computed_at"],
                      "code_sha":code_sha,"config_sha256":result["policy_sha256"],"data_sha256":result["feature_sha256"],"rows":result[name]}))
        receipt={"status":result["status"],"attempt_id":attempt_id,"as_of":result["as_of"],
                 "result_sha256":hashlib.sha256(raw).hexdigest(),"input_sha256":input_sha256 or digest(payload),
                 "canonical_payload_sha256":digest(payload),
                 "global_ranking_ready":result["global_ranking_ready"],"consumable":fully_admitted(result)}
        if model_publication is not None:
            receipt["model_allocation_ref"]=result["model_allocation_publication"]
            require(_model_publication(payload,result,policy,review_root,code_sha,model_publication)
                    ==receipt["model_allocation_ref"],"model_publication_changed_before_receipt")
            require(verified_source_hashes(code_sha)==source_hashes,"source_changed_during_model_publication")
        exclusive(target/"receipt.json",encoded(receipt))
        if model_publication is not None:
            require((target/"result.json").read_bytes()==raw
                    and (target/"receipt.json").read_bytes()==encoded(receipt),"model_publication_readback")
        # Only fully admitted global research output can advance last-success.
        if fully_admitted(result):
            atomic(out/"last_success.json",encoded(receipt))
        atomic(out/"latest_attempt.json",encoded(receipt))
        return result
    except Exception:
        atomic(out/"latest_attempt.json",encoded({"status":"BLOCKED","attempt_id":attempt_id,"reason":"runtime_validation_failed","last_success_retained":True}))
        raise


def _published_readiness(receipt,result):
    # Scoped readiness never changes the full-roster completeness flag. Both
    # original bodies must agree; an outer consumable flag grants no authority.
    return (receipt.get("consumable") is True and fully_admitted(result)
            and type(receipt.get("global_ranking_ready")) is bool
            and receipt["global_ranking_ready"]==result.get("global_ranking_ready")
            and receipt.get("as_of")==result.get("as_of")
            and receipt.get("status")==result.get("status"))


def read_latest(out, *, consumed_at=None):
    receipt=load_json((out/"latest_attempt.json").read_bytes())
    require(receipt.get("consumable") is True,"latest_attempt_not_ready")
    aid=receipt["attempt_id"]
    require(aid and all(c.isalnum() or c in "-_" for c in aid),"attempt_id")
    raw=(out/"attempts"/aid/"result.json").read_bytes()
    require(hashlib.sha256(raw).hexdigest()==receipt["result_sha256"],"output_tampered")
    result=load_json(raw)
    require(_published_readiness(receipt,result),"latest_proposal_not_ready")
    # Read-time freshness is separate from admission at the original decision.
    # Historical attempts remain inspectable by path, not as current latest.
    consumed_at=consumed_at or datetime.now(timezone.utc).isoformat()
    require(stamp(result["computed_at"])<=stamp(consumed_at),"latest_decision_in_future")
    require(result["as_of"]==list(grid(consumed_at))[-1],"latest_session_stale")
    require(verified_source_hashes(result["code_sha"])==result["code_file_sha256"],"output_source_identity_mismatch")
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--input",type=Path)
    mode.add_argument("--capture",action="store_true")
    p.add_argument("--expected-input-sha256")
    p.add_argument("--artifact-root",type=Path,
                   help="Existing private A3 evidence tree for hash-pinned --input artifact_files; no collection")
    p.add_argument("--registry",type=Path,default=ROOT/"docs/multi_asset_registry_v1.json")
    p.add_argument("--policy",type=Path,default=ROOT/"docs/multi_asset_policy_v1.json")
    p.add_argument("--expected-registry-sha256")
    p.add_argument("--expected-policy-sha256")
    p.add_argument("--model-publication",type=Path,
                   help="Opt-in existing candidate/OWNER descriptor pair; never an acceptance issuer")
    p.add_argument("--expected-model-publication-sha256")
    p.add_argument("--output-dir",type=Path,required=True)
    p.add_argument("--attempt-id",required=True)
    args=p.parse_args()
    # CLI revocation starts before reading inputs or collecting providers.
    atomic(args.output_dir/"latest_attempt.json",encoded({"status":"STARTED","attempt_id":args.attempt_id,"last_success_retained":True}))
    try:
        sha=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
        verified_source_hashes(sha)
        registry_raw=configuration_bytes(args.registry,args.expected_registry_sha256,"docs/multi_asset_registry_v1.json")
        policy_raw=configuration_bytes(args.policy,args.expected_policy_sha256,"docs/multi_asset_policy_v1.json")
        registry=load_json(registry_raw)
        policy=load_json(policy_raw)
        model_publication=None
        if args.model_publication is not None:
            require(args.input is not None and args.artifact_root is not None,
                    "model_publication_requires_frozen_input")
            require(args.model_publication.stat().st_size<=256*1024,"model_publication_budget")
            model_raw=args.model_publication.read_bytes()
            require(hashlib.sha256(model_raw).hexdigest()==args.expected_model_publication_sha256,
                    "model_publication_external_hash")
            model_publication=load_json(model_raw)
        else:
            require(args.expected_model_publication_sha256 is None,"model_publication_hash_without_input")
        require(args.artifact_root is None or args.input is not None,"a3_artifacts_require_frozen_input")
        if args.input:
            raw=args.input.read_bytes()
            input_sha256=hashlib.sha256(raw).hexdigest()
            require(args.expected_input_sha256==input_sha256,"input_hash_required_or_mismatch")
            payload=load_json(raw)
        else:
            require(args.attempt_id and all(c.isalnum() or c in "-_" for c in args.attempt_id),"attempt_id")
            capture_dir=args.output_dir/"captures"/args.attempt_id
            capture_dir.mkdir(parents=True,exist_ok=False)
            payload=capture(registry,capture_dir)
            input_sha256=hashlib.sha256((capture_dir/"input.json").read_bytes()).hexdigest()
        resolver=None
        if "requested_security_ids" in payload or "a3_reference_entries" in payload:
            resolver=a3_artifacts(payload,args.artifact_root)
        else:
            require(args.artifact_root is None and "artifact_files" not in payload,"a3_artifacts_without_reference_scope")
        result=publish(payload,registry,policy,args.output_dir,args.attempt_id,sha,input_sha256=input_sha256,
                       configuration_sha256={"registry":hashlib.sha256(registry_raw).hexdigest(),"policy":hashlib.sha256(policy_raw).hexdigest()},
                        artifact_resolver=resolver,review_root=args.artifact_root,model_publication=model_publication)
        print(json.dumps({"status":result["status"],"assets":len(result["multi_asset_leadership_latest"]),"global_ranking_ready":result["global_ranking_ready"]}))
        return 0 if fully_admitted(result) else 2
    except Exception as exc:
        atomic(args.output_dir/"latest_attempt.json",encoded({"status":"BLOCKED","attempt_id":args.attempt_id,"reason":"input_or_runtime_failure","last_success_retained":True}))
        print(json.dumps({"status":"BLOCKED","reason":str(exc) if isinstance(exc,ContractError) else type(exc).__name__}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())

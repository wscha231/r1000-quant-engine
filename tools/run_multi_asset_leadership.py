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
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from research.multi_asset_v1.contracts import ContractError, digest, encoded, load_json, number, require
from research.multi_asset_v1.runtime import render, run
from research.multi_asset_v1.prices import grid
from research.multi_asset_v1.sources import capture_crypto,capture_spot_metrics
from tools.macro_history_sources import request_bytes, exclusive


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
    payload={"schema":"multi-asset-input-v1","as_of":datetime.now(timezone.utc).isoformat(),
             "prices":rows,"metrics":metrics,"events":[],"evaluations":[],"base_equity_ids":[],"collection_receipts":receipts+metric_receipts}
    exclusive(attempt/"input.json",encoded(payload))
    return payload


def fully_admitted(result):
    return result.get("global_ranking_ready") is True and result.get("proposal",{}).get("status")=="RESEARCH_PROPOSAL"


def publish(payload, registry, policy, out, attempt_id, code_sha, *, input_sha256=None):
    require(attempt_id and all(c.isalnum() or c in "-_" for c in attempt_id),"attempt_id")
    # Revoke consumption before validation, preserving last-success and its bytes.
    atomic(out/"latest_attempt.json",encoded({"status":"STARTED","attempt_id":attempt_id,"last_success_retained":True}))
    target=out/"attempts"/attempt_id
    target.mkdir(parents=True,exist_ok=False)
    try:
        result=run(payload,registry,policy)
        result["code_sha"]=code_sha
        paths=[*sorted((ROOT/"research/multi_asset_v1").glob("*.py")),ROOT/"tools/run_multi_asset_leadership.py",ROOT/"research/theme_etf_runtime_v1/strict.py",ROOT/"research/theme_etf_runtime_v1/runtime.py",ROOT/"r1000_legacy_input_guard.py"]
        result["code_file_sha256"]={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
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
        exclusive(target/"receipt.json",encoded(receipt))
        # Only fully admitted global research output can advance last-success.
        if fully_admitted(result):
            atomic(out/"last_success.json",encoded(receipt))
        atomic(out/"latest_attempt.json",encoded(receipt))
        return result
    except Exception:
        atomic(out/"latest_attempt.json",encoded({"status":"BLOCKED","attempt_id":attempt_id,"reason":"runtime_validation_failed","last_success_retained":True}))
        raise


def read_latest(out):
    receipt=load_json((out/"latest_attempt.json").read_bytes())
    require(receipt.get("global_ranking_ready") is True and receipt.get("consumable") is True,"latest_attempt_not_ready")
    aid=receipt["attempt_id"]
    require(aid and all(c.isalnum() or c in "-_" for c in aid),"attempt_id")
    raw=(out/"attempts"/aid/"result.json").read_bytes()
    require(hashlib.sha256(raw).hexdigest()==receipt["result_sha256"],"output_tampered")
    result=load_json(raw)
    require(fully_admitted(result),"latest_proposal_not_ready")
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--input",type=Path)
    mode.add_argument("--capture",action="store_true")
    p.add_argument("--expected-input-sha256")
    p.add_argument("--registry",type=Path,default=ROOT/"docs/multi_asset_registry_v1.json")
    p.add_argument("--policy",type=Path,default=ROOT/"docs/multi_asset_policy_v1.json")
    p.add_argument("--output-dir",type=Path,required=True)
    p.add_argument("--attempt-id",required=True)
    args=p.parse_args()
    # CLI revocation starts before reading inputs or collecting providers.
    atomic(args.output_dir/"latest_attempt.json",encoded({"status":"STARTED","attempt_id":args.attempt_id,"last_success_retained":True}))
    try:
        registry=load_json(args.registry.read_bytes())
        policy=load_json(args.policy.read_bytes())
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
        sha=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
        result=publish(payload,registry,policy,args.output_dir,args.attempt_id,sha,input_sha256=input_sha256)
        print(json.dumps({"status":result["status"],"assets":len(result["multi_asset_leadership_latest"]),"global_ranking_ready":result["global_ranking_ready"]}))
        return 0 if fully_admitted(result) else 2
    except Exception as exc:
        atomic(args.output_dir/"latest_attempt.json",encoded({"status":"BLOCKED","attempt_id":args.attempt_id,"reason":"input_or_runtime_failure","last_success_retained":True}))
        print(json.dumps({"status":"BLOCKED","reason":str(exc) if isinstance(exc,ContractError) else type(exc).__name__}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())

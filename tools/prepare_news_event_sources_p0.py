#!/usr/bin/env python3
"""Manual SEC capture/index or reviewed producer-export assembly. No training.

`index` and `assemble` are offline. `capture` makes bounded SEC-only GET requests
ONLY with --allow-sec-network, an explicit plan, and SEC_USER_AGENT set. No
market data keys, premium APIs, Drive writes, Git writes or model promotion.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from research.news_event_alpha_v1.admission import json_load, read_bounded
from research.news_event_alpha_v1.runtime import ContractError, canonical_bytes
from research.news_event_alpha_v1.execution import require
from research.news_event_alpha_v1.source_bridge import assemble_export, load_export, index_export
from research.news_event_alpha_v1.source_capture import capture, _outside_git


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="command",required=True)
    ix=sub.add_parser("index",help="Read captured SEC metadata; print review/readiness counts")
    ix.add_argument("--export",type=Path,required=True)
    ass=sub.add_parser("assemble",help="Build a new local P0-2 input bundle from explicit reviewed exports")
    ass.add_argument("--export",type=Path,required=True)
    ass.add_argument("--output-dir",type=Path,required=True)
    cap=sub.add_parser("capture",help="Bounded opt-in SEC-only metadata and primary documents")
    cap.add_argument("--plan",type=Path,required=True)
    cap.add_argument("--output-dir",type=Path,required=True)
    cap.add_argument("--lock-file",type=Path,required=True)
    cap.add_argument("--resume",action="store_true")
    cap.add_argument("--allow-sec-network",action="store_true")
    args=p.parse_args(argv)
    now=datetime.now(timezone.utc).isoformat()
    if args.command=="index":
        m,files,_=load_export(args.export,now=now,index_only=True)
        result=index_export(m,files)
        result={"status":"INDEXED_REVIEW_REQUIRED","candidates":len(result["candidates"]),
                "excluded_records":len(result["excluded_records"]),
                "unresolved_history_urls":result["unresolved_history_urls"],
                "selector_weight":0.0,"historical_training_run":False}
    elif args.command=="assemble":
        result=assemble_export(args.export,args.output_dir,now=now)
    else:
        require(args.allow_sec_network,"SEC_NETWORK_NOT_AUTHORIZED")
        ua=os.environ.get("SEC_USER_AGENT","")
        require(bool(ua) and "@" in ua,"SEC_USER_AGENT_REQUIRED_DO_NOT_POST_IT_IN_CHAT")
        result=capture(json_load(read_bounded(args.plan)),args.output_dir,user_agent=ua,
                       lock_path=args.lock_file,resume=args.resume)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 2 if result.get("status")=="PARTIAL_BLOCKED" else 0

if __name__=="__main__":
    try: raise SystemExit(main())
    except (ContractError,OSError,ValueError,KeyError,TypeError) as exc:
        # Exceptions here have controlled error codes; never dump response bodies/auth.
        print("BLOCKED: "+str(exc),file=sys.stderr)
        raise SystemExit(2)

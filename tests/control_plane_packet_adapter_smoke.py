#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from research_only.control_plane.packet_adapter import build_packet, digest, ContractError

def env(payload, available="2026-09-17T20:00:00Z", status="VERIFIED"):
    return {
        "status": status,
        "available_at": available,
        "observed_at": available,
        "collected_at": "2026-09-17T20:01:00Z",
        "payload": payload,
        "data_hash": digest(payload),
    }

def base(market="US"):
    cur = "USD" if market=="US" else "KRW"
    exch = "XNAS" if market=="US" else "XKRX"
    return {
        "schema_version":"candidate-packet-source-bundle-v1",
        "decision_cutoff":"2026-09-17T20:05:00Z",
        "source_commit":"a"*40,
        "config_hash":"b"*64,
        "identity":{
            "security_id":f"SYNTH:{exch}:ABC","issuer_id":"SYNTH:ISSUER:ABC",
            "ticker":"ABC" if market=="US" else "000660",
            "market":market,"currency":cur,"security_type":"COMMON_STOCK"
        },
        "sources":{}
    }

def check(cond,msg):
    if not cond: raise AssertionError(msg)

def main():
    b=base()
    b["sources"]={
        "universe":env({"membership_reasons":["R1000_BASE"],"candidate_status":"CANDIDATE","event_membership_score_bonus":0.0}),
        "fundamentals":env({"revenue_growth_yoy":0.2}),
        "thesis":env({"good_company":"PASS","good_stock":"REVIEW","good_price":"FAIL","portfolio_fit":"REVIEW"}),
        "valuation":env({"current_price":100.0,"base_fair_value":80.0}),
        "expected_return":env({"h12m":-0.2,"status":"BASE_CASE_NEGATIVE"}),
    }
    p=build_packet(b)
    check(p["valuation"]["base_fair_value"]==80.0,"valuation lost")
    check(p["expected_return"]["h12m"]==-0.2,"leadership/discovery must not force positive return")
    check(p["authority"]=={"research_only":True,"target_authority":False,"order_authority":False},"authority drift")
    check(p["provenance"]["pit_status"]=="VERIFIED_INPUT_SET","verified core set should admit")
    check(p["universe"]["event_membership_score_bonus"]==0.0,"event bonus drift")

    future=base()
    future["sources"]={"universe":env({"membership_reasons":["R1000_BASE"],"candidate_status":"CANDIDATE"}, available="2026-09-17T21:00:00Z")}
    q=build_packet(future)
    check(q["provenance"]["source_status"]["universe"]=="SOURCE_FUTURE","future source admitted")
    check(q["universe"]["candidate_status"]=="BLOCKED_SOURCE_EVIDENCE","future universe changed candidate")

    missing=base()
    missing["sources"]={"fundamentals":env({"revenue_growth_yoy":0.0},status="MISSING")}
    r=build_packet(missing)
    check(r["fundamentals"]=={},"missing data became numeric")
    check(any("fundamentals:SOURCE_MISSING" in x for x in r["provenance"]["missing_reasons"]),"missing reason lost")

    forbidden=base()
    forbidden["sources"]={"valuation":env({"base_fair_value":100.0,"target_weight":0.1})}
    s=build_packet(forbidden)
    check("FORBIDDEN_AUTHORITY_FIELD" in s["provenance"]["source_status"]["valuation"],"authority field admitted")

    kr=base("KR")
    kr["sources"]={"universe":env({"membership_reasons":["KR_BASE"],"candidate_status":"WATCH"})}
    k=build_packet(kr)
    check(k["identity"]["currency"]=="KRW" and k["identity"]["market"]=="KR","KR identity drift")
    check(k["authority"]["order_authority"] is False,"KR adapter gained order authority")

    check(build_packet(b)==p,"adapter is not deterministic")
    print(json.dumps({"status":"PASS","test":"control_plane_packet_adapter_smoke","cases":6},sort_keys=True))
    return 0
if __name__=="__main__": raise SystemExit(main())

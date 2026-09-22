#!/usr/bin/env python3
"""Bounded Gold Set E2E verifier for RC1 research integration."""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"research"))
from a3_candidate_packet_v1 import evaluate_packet as evaluate_a3

SCHEMA="gold-set-e2e-v1"
HEX64=set("0123456789abcdef")

def sha256_bytes(raw: bytes)->str: return hashlib.sha256(raw).hexdigest()
def read_json(path: Path)->dict[str,Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict): raise ValueError("json_object_required")
    return value
def hash_ok(value: Any)->bool:
    return isinstance(value,str) and len(value)==64 and set(value)<=HEX64

class Resolver:
    def __init__(self,root: Path,index: dict[str,dict[str,Any]]):
        self.root=root.resolve(); self.index=index
    def __call__(self,artifact_id: str,expected_sha256: str)->bytes:
        ref=self.index.get(artifact_id)
        if not isinstance(ref,dict): raise ValueError("artifact_id_missing")
        if ref.get("sha256")!=expected_sha256 or not hash_ok(expected_sha256):
            raise ValueError("artifact_index_hash_mismatch")
        rel=Path(str(ref.get("path") or ""))
        if rel.is_absolute() or ".." in rel.parts: raise ValueError("artifact_path_unsafe")
        path=(self.root/rel).resolve()
        if not path.is_relative_to(self.root) or not path.is_file() or path.is_symlink():
            raise ValueError("artifact_path_invalid")
        raw=path.read_bytes()
        if sha256_bytes(raw)!=expected_sha256: raise ValueError("artifact_bytes_hash_mismatch")
        return raw

def validate_gold_registry(value: dict[str,Any])->dict[str,dict[str,Any]]:
    if value.get("schema")!="cross-market-gold-set-v1": raise ValueError("gold_set_schema")
    if value.get("authority")!="RESEARCH_VALIDATION_ONLY": raise ValueError("gold_set_authority")
    rows=value.get("candidates")
    if not isinstance(rows,list) or not rows: raise ValueError("gold_set_candidates")
    by_id={}
    for row in rows:
        if not isinstance(row,dict): raise ValueError("gold_set_candidate_row")
        cid=row.get("id")
        if not isinstance(cid,str) or not cid or cid in by_id: raise ValueError("gold_set_candidate_identity")
        by_id[cid]=row
    return by_id

def validate_phase2a(value: dict[str,Any],candidate: dict[str,Any])->list[str]:
    blockers=[]
    if value.get("artifact_kind")!="GROSS_RESEARCH_ER_EVIDENCE": blockers.append("phase2a_artifact_kind")
    if value.get("net_of_costs") is not False: blockers.append("phase2a_net_cost_boundary")
    if value.get("a3_validated_er_eligible") is not False: blockers.append("phase2a_a3_boundary")
    if value.get("er_promotion_gate_status")!="BLOCKED_GROSS_RESEARCH_ONLY": blockers.append("phase2a_promotion_boundary")
    rows=value.get("rows") or []
    matches=[r for r in rows if isinstance(r,dict) and r.get("ticker")==candidate["ticker"]]
    if len(matches)!=1: blockers.append("phase2a_candidate_row_missing_or_duplicate")
    return blockers

def validate_er_gate(value: dict[str,Any])->list[str]:
    blockers=[]
    if value.get("schema_version")!="er-promotion-gate-v1": blockers.append("er_gate_schema")
    if value.get("status")=="ER_ELIGIBLE": blockers.append("unexpected_er_eligible_during_gross_research_stage")
    if value.get("scenario_probabilities_used") is not False: blockers.append("scenario_probability_boundary")
    authority=value.get("authority") or {}
    if any(authority.get(k) is not False for k in ("target","portfolio","broker","orders","promotion")):
        blockers.append("er_gate_authority")
    return blockers

def run(*,gold_set: Path,manifest_path: Path,bundle_root: Path,cutoff: str)->dict[str,Any]:
    manifest=read_json(manifest_path)
    gold=validate_gold_registry(read_json(gold_set))
    if manifest.get("schema_version")!=SCHEMA: raise ValueError("manifest_schema")
    if manifest.get("research_only") is not True: raise ValueError("manifest_authority")
    authority=manifest.get("authority") or {}
    if any(authority.get(k) is not False for k in ("ranking","portfolio","target","orders","production")):
        raise ValueError("manifest_economic_authority")
    index=manifest.get("artifact_index"); candidates=manifest.get("candidates")
    if not isinstance(index,dict) or not isinstance(candidates,list) or not candidates:
        raise ValueError("manifest_content")
    resolver=Resolver(bundle_root,index); output_rows=[]
    for row in candidates:
        if not isinstance(row,dict): raise ValueError("manifest_candidate_row")
        cid=row.get("candidate_id"); candidate=gold.get(cid)
        if candidate is None: raise ValueError("candidate_not_in_gold_set")
        if row.get("ticker")!=candidate.get("ticker") or row.get("asset_class")!=candidate.get("asset_class"):
            raise ValueError("candidate_metadata_mismatch")
        packet_ref=row.get("a3_packet")
        if not isinstance(packet_ref,dict): raise ValueError("a3_packet_ref")
        packet=json.loads(resolver(packet_ref["artifact_id"],packet_ref["sha256"]))
        result=evaluate_a3(packet,cutoff,resolver); blockers=[]
        if result.get("selector_eligible") is not False or result.get("portfolio_weight_effect")!=0.0:
            blockers.append("a3_authority")
        if result.get("target_book_write_allowed") is not False or result.get("orders_allowed") is not False:
            blockers.append("a3_order_authority")
        if result.get("status")!="SCENARIO_RESEARCH_COMPLETE": blockers.append("a3_unexpected_status")
        if result.get("validated_expected_return_available") is not False: blockers.append("a3_unexpected_validated_er")
        phase2a_ref=row.get("phase2a_gross_research_er")
        if phase2a_ref is not None:
            blockers.extend(validate_phase2a(json.loads(resolver(phase2a_ref["artifact_id"],phase2a_ref["sha256"])),candidate))
        gate_ref=row.get("er_promotion_gate")
        if gate_ref is not None:
            blockers.extend(validate_er_gate(json.loads(resolver(gate_ref["artifact_id"],gate_ref["sha256"]))))
        output_rows.append({"candidate_id":cid,"ticker":candidate["ticker"],"market":candidate["market"],
            "country":candidate["country"],"asset_class":candidate["asset_class"],"a3_status":result.get("status"),
            "validated_er_available":False,"portfolio_candidate":False,"blockers":sorted(set(blockers))})
    blocked=sum(bool(r["blockers"]) for r in output_rows)
    return {"schema_version":"gold-set-e2e-result-v1",
        "status":"PASS_RESEARCH_CONNECTIVITY" if blocked==0 else "BLOCKED",
        "candidate_count":len(output_rows),"blocked_candidate_count":blocked,"research_only":True,
        "global_ranking_ready":False,"a5_execution_allowed":False,"target_authority":False,
        "order_authority":False,"rows":output_rows}

def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gold-set",default="research/cross_market_gold_set_v1.json")
    p.add_argument("--manifest",required=True); p.add_argument("--bundle-root",required=True)
    p.add_argument("--cutoff",required=True); p.add_argument("--output",required=True)
    a=p.parse_args()
    try: result=run(gold_set=Path(a.gold_set),manifest_path=Path(a.manifest),bundle_root=Path(a.bundle_root),cutoff=a.cutoff)
    except Exception as exc:
        print(json.dumps({"status":"BLOCKED","reason":str(exc)},sort_keys=True)); return 2
    Path(a.output).write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("status","candidate_count","blocked_candidate_count")},sort_keys=True))
    return 0 if result["status"]=="PASS_RESEARCH_CONNECTIVITY" else 2
if __name__=="__main__": raise SystemExit(main())

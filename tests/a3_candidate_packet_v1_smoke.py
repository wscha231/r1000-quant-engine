from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'research'))

from a3_candidate_packet_v1 import A3CandidatePacketError, evaluate_packet

RAW = {}

def add(artifact_id, obj):
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    sha = hashlib.sha256(raw).hexdigest()
    RAW[(artifact_id, sha)] = raw
    return {"artifact_id": artifact_id, "sha256": sha, "available_at":"2026-09-18T20:30:00Z", "review_status":"REVIEWED"}

def resolver(aid, sha):
    return RAW[(aid,sha)]

def methodology():
    return {
      "schema":"investment-methodology-v1-result","status":"COMPLETE_RESEARCH_REVIEW",
      "asset_id":"US:EXAMPLE","issuer_id":"CIK:1","selector_eligible":False,
      "portfolio_weight_effect":0.0,"oos_validated":False
    }

def moat():
    return {
      "schema":"moat-quality-v2-result","status":"COMPLETE_RESEARCH_REVIEW",
      "asset_id":"US:EXAMPLE","issuer_id":"CIK:1","selector_eligible":False,
      "portfolio_weight_effect":0.0,"oos_validated":False
    }

def market():
    d={"schema":"a3-market-valuation-snapshot-v1","asset_id":"US:EXAMPLE",
       "data_quality":"REVIEWED_OBSERVED","research_only":True,
       "completed_session":True,"session_date":"2026-09-18",
       "available_at":"2026-09-18T20:00:00Z","price":100.0,"currency":"USD","benchmark_id":"US:SPY",
       "return_basis":"TOTAL_RETURN","rs_method":"LOG_RELATIVE_RETURN"}
    for h in (20,60,120,240):
        d[f"return_{h}d"]=0.1
        d[f"benchmark_return_{h}d"]=0.05
        d[f"rs_{h}d"]=__import__("math").log1p(0.1)-__import__("math").log1p(0.05)
    return d

def graph():
    ir_raw=add("RAW:IR",{"document":"issuer primary"})
    news_raw=add("RAW:NEWS",{"document":"independent verification"})
    return {
      "schema":"a3-source-graph-v1","asset_id":"US:EXAMPLE","issuer_id":"CIK:1",
      "review_status":"REVIEWED","research_only":True,"as_of":"2026-09-18T20:30:00Z",
      "sources":[
        {"source_id":"IR:1","claim_id":"CLAIM:1","source_type":"COMPANY_IR","source_affiliation":"ISSUER",
         "verification_tier":"V2","independence_group":"ISSUER:EXAMPLE",
         "published_at":"2026-09-18T18:00:00Z","available_at":"2026-09-18T18:00:00Z",
         "raw_artifact_id":ir_raw["artifact_id"],"raw_sha256":ir_raw["sha256"],
         "claim":"Issuer-reported operating evidence","supports_pillars":["earnings_revision_operating_acceleration"],
         "used_for_assessment":True,"investment_score_contribution_allowed":True},
        {"source_id":"NEWS:1","claim_id":"CLAIM:2","source_type":"REUTERS","source_affiliation":"INDEPENDENT_MEDIA",
         "verification_tier":"V1","independence_group":"REUTERS",
         "published_at":"2026-09-18T19:00:00Z","available_at":"2026-09-18T19:00:00Z",
         "raw_artifact_id":news_raw["artifact_id"],"raw_sha256":news_raw["sha256"],
         "claim":"Independent corroboration","supports_pillars":["earnings_revision_operating_acceleration"],
         "used_for_assessment":True,"investment_score_contribution_allowed":True},
      ]}

def valid_er():
    d={"asset_id":"US:EXAMPLE","validation_status":"WALK_FORWARD_VALIDATED",
       "benchmark_id":"US:SPY","net_of_costs":True,"unit":"RETURN_FRACTION",
       "expected_drawdown":0.2,"downside_probability":0.3}
    for h in ("1m","3m","6m","12m"):
        d[f"expected_return_{h}"]=0.12
        d[f"benchmark_expected_return_{h}"]=0.05
    return d

def packet(include_er=False):
    arts={
      "methodology":{"kind":"METHODOLOGY_RESULT",**add("METH",methodology())},
      "moat":{"kind":"MOAT_RESULT",**add("MOAT",moat())},
      "market_valuation":{"kind":"MARKET_VALUATION_SNAPSHOT",**add("MKT",market())},
      "source_graph":{"kind":"SOURCE_GRAPH",**add("SRC",graph())},
    }
    if include_er:
        arts["validated_er"]={"kind":"VALIDATED_ER_EVALUATION",**add("ER",valid_er())}
    bridge={}
    for horizon in ("12m","24m"):
        bridge[horizon]={
          "bear":{"return":-0.2,"assumptions":["bear"]},
          "base":{"return":0.1,"assumptions":["base"]},
          "bull":{"return":0.4,"assumptions":["bull"]},
        }
    return {
      "schema":"a3-candidate-packet-v1","asset_id":"US:EXAMPLE","issuer_id":"CIK:1",
      "country":"US","asset_class":"EQUITY","as_of":"2026-09-18T21:00:00Z",
      "reviewed_at":"2026-09-19T01:00:00Z","review_status":"RESEARCH_REVIEWED",
      "moat_applicability":"REQUIRED","artifacts":arts,
      "thesis":{"status":"WATCH","counter_thesis":"counter","catalysts":["c1"],"invalidation_conditions":["i1"]},
      "scenario_research":bridge
    }

class Tests(unittest.TestCase):
  def setUp(self): RAW.clear()
  def test_scenario_not_er(self):
    out=evaluate_packet(packet(), "2026-09-19T02:00:00Z", resolver)
    self.assertEqual(out["status"],"SCENARIO_RESEARCH_COMPLETE")
    self.assertFalse(out["validated_expected_return_available"])
    self.assertFalse(out["scenario_research_is_expected_return"])
    self.assertFalse(out["selector_eligible"])
  def test_validated_er(self):
    out=evaluate_packet(packet(True), "2026-09-19T02:00:00Z", resolver)
    self.assertEqual(out["status"],"VALIDATED_ER_LINKED")
    self.assertAlmostEqual(out["validated_er"]["12m"]["expected_alpha"],.07)
  def test_no_probabilities(self):
    v=packet(); v["scenario_research"]["12m"]["base"]["probability"]=.5
    with self.assertRaisesRegex(A3CandidatePacketError,"unvalidated_scenario_probability"):
      evaluate_packet(v,"2026-09-19T02:00:00Z",resolver)
  def test_hash_mismatch(self):
    v=packet(); ref=v["artifacts"]["methodology"]; RAW[(ref["artifact_id"],ref["sha256"])]=b"bad"
    with self.assertRaisesRegex(A3CandidatePacketError,"artifact_hash_mismatch"):
      evaluate_packet(v,"2026-09-19T02:00:00Z",resolver)
  def test_moat_required(self):
    v=packet(); v["artifacts"].pop("moat")
    with self.assertRaisesRegex(A3CandidatePacketError,"moat_artifact_required"):
      evaluate_packet(v,"2026-09-19T02:00:00Z",resolver)
  def test_underlying_can_omit_moat(self):
    v=packet(); v["moat_applicability"]="NOT_APPLICABLE_UNDERLYING"; v["artifacts"].pop("moat")
    out=evaluate_packet(v,"2026-09-19T02:00:00Z",resolver)
    self.assertIsNone(out["moat_sha256"])
  def test_market_rs_must_match_log_relative_formula(self):
    v=packet()
    obj=market(); obj["rs_20d"]=0.05
    new=add("MKT2",obj); v["artifacts"]["market_valuation"]={"kind":"MARKET_VALUATION_SNAPSHOT",**new}
    with self.assertRaisesRegex(A3CandidatePacketError,"market_rs_formula"):
      evaluate_packet(v,"2026-09-19T02:00:00Z",resolver)
  def test_source_graph_requires_independent_groups(self):
    v=packet()
    obj=graph(); obj["sources"]=obj["sources"][:1]
    new=add("SRC2",obj); v["artifacts"]["source_graph"]={"kind":"SOURCE_GRAPH",**new}
    with self.assertRaisesRegex(A3CandidatePacketError,"source_graph_insufficient_independent_groups"):
      evaluate_packet(v,"2026-09-19T02:00:00Z",resolver)
  def test_telegram_v0_is_zero_credit(self):
    v=packet()
    obj=graph()
    raw=add("RAW:TG",{"telegram":"secondary claim"})
    obj["sources"].append({
      "source_id":"TG:1","claim_id":"CLAIM:TG","source_type":"TELEGRAM_SECONDARY",
      "source_affiliation":"COMMUNITY_SECONDARY","verification_tier":"V0","independence_group":"TELEGRAM",
      "published_at":"2026-09-18T19:10:00Z","available_at":"2026-09-18T19:10:00Z",
      "raw_artifact_id":raw["artifact_id"],"raw_sha256":raw["sha256"],"claim":"Secondary discovery claim",
      "supports_pillars":["catalyst_ownership_information_edge"],
      "used_for_assessment":True,"investment_score_contribution_allowed":True})
    new=add("SRC3",obj); v["artifacts"]["source_graph"]={"kind":"SOURCE_GRAPH",**new}
    with self.assertRaisesRegex(A3CandidatePacketError,"source_graph_v0_not_assessment"):
      evaluate_packet(v,"2026-09-19T02:00:00Z",resolver)
  def test_source_graph_raw_hash_is_verified(self):
    v=packet()
    ref=v["artifacts"]["source_graph"]
    obj=json.loads(RAW[(ref["artifact_id"],ref["sha256"])])
    row=obj["sources"][0]
    RAW[(row["raw_artifact_id"],row["raw_sha256"])]=b"tampered"
    with self.assertRaisesRegex(A3CandidatePacketError,"source_graph_raw_hash_mismatch"):
      evaluate_packet(v,"2026-09-19T02:00:00Z",resolver)
  def test_contract_preserves_scenario_er_boundary(self):
    contract=json.loads((ROOT/"docs"/"a3_candidate_packet_v1_contract.json").read_text())
    self.assertFalse(contract["scenario_research"]["probabilities_allowed"])
    self.assertEqual(contract["validated_er"]["validation_status"],"WALK_FORWARD_VALIDATED")
    self.assertFalse(contract["authority"]["selector_eligible"])
    self.assertEqual(contract["authority"]["portfolio_weight_effect"],0.0)
  def test_methodology_authority_rejected(self):
    v=packet()
    ref=v["artifacts"]["methodology"]
    obj=methodology(); obj["selector_eligible"]=True
    new=add("METH2",obj); v["artifacts"]["methodology"]={"kind":"METHODOLOGY_RESULT",**new}
    with self.assertRaisesRegex(A3CandidatePacketError,"methodology_selector_authority"):
      evaluate_packet(v,"2026-09-19T02:00:00Z",resolver)

if __name__=="__main__": unittest.main()

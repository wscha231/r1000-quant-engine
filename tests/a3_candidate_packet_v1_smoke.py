from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'research'))

import a3_candidate_packet_v1 as a3
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
    raw=add("RAW:MKT",{"provider":"fixture market bytes","asset_id":"US:EXAMPLE"})
    d={"schema":"a3-market-valuation-snapshot-v1","asset_id":"US:EXAMPLE",
       "data_quality":"REVIEWED_OBSERVED","research_only":True,
       "completed_session":True,"session_date":"2026-09-18",
       "observed_at":"2026-09-18T20:00:00Z",
       "available_at":"2026-09-18T20:05:00Z",
       "collected_at":"2026-09-18T20:10:00Z",
       "price":100.0,"currency":"USD","benchmark_id":"US:SPY",
       "source_identity":"FIXTURE_MARKET_DATA",
       "raw_artifact_id":raw["artifact_id"],"raw_sha256":raw["sha256"],
       "basis_review_status":"REVIEWED","corporate_action_quarantine":False,
       "historical_pit_certified":False,"validated_er_eligible":True,
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
  def test_market_raw_source_bytes_are_hash_bound(self):
    v=packet()
    ref=v["artifacts"]["market_valuation"]
    obj=json.loads(RAW[(ref["artifact_id"],ref["sha256"])])
    RAW[(obj["raw_artifact_id"],obj["raw_sha256"])]=b"tampered"
    with self.assertRaisesRegex(A3CandidatePacketError,"market_raw_hash_mismatch"):
      evaluate_packet(v,"2026-09-19T02:00:00Z",resolver)
  def test_market_source_time_and_corporate_action_guards(self):
    for field,value,code in (
      ("collected_at","2026-09-18T19:00:00Z","market_time_order"),
      ("basis_review_status","UNREVIEWED","market_basis_review_status"),
      ("corporate_action_quarantine",True,"market_corporate_action_quarantine"),
    ):
      with self.subTest(field=field):
        v=packet(); obj=market(); obj[field]=value
        new=add("MKT-GUARD-"+field,obj)
        v["artifacts"]["market_valuation"]={"kind":"MARKET_VALUATION_SNAPSHOT",**new}
        with self.assertRaisesRegex(A3CandidatePacketError,code):
          evaluate_packet(v,"2026-09-19T02:00:00Z",resolver)
  def test_adjusted_close_proxy_cannot_self_declare_validated_er_eligibility(self):
    v=packet(); obj=market()
    obj["return_basis"]="PROVIDER_ADJUSTED_CLOSE_PROXY"
    obj["validated_er_eligible"]=True
    new=add("MKT-PROXY",obj)
    v["artifacts"]["market_valuation"]={"kind":"MARKET_VALUATION_SNAPSHOT",**new}
    with self.assertRaisesRegex(A3CandidatePacketError,"market_proxy_not_validated_er"):
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

  def test_optional_cache_preserves_default_result_and_raw_gates(self):
    v=packet(True)
    expected=evaluate_packet(v,"2026-09-19T02:00:00Z",resolver)
    calls=[]
    def read(aid,sha):
      calls.append((aid,sha)); return resolver(aid,sha)
    cache=a3._VerifiedArtifactCache(read)
    with patch.object(a3,"_strict_json_object",wraps=a3._strict_json_object) as decoder:
      for _ in range(3):
        self.assertEqual(evaluate_packet(v,"2026-09-19T02:00:00Z",read,_artifact_cache=cache),expected)
    self.assertEqual(len(calls),len(set(calls)))
    self.assertEqual(decoder.call_count,len(v["artifacts"]))
    self.assertFalse(expected["selector_eligible"])

  def test_cached_methodology_mutation_cannot_change_verified_byte_semantics(self):
    import a3_candidate_packet_v1 as a3
    v=packet()
    bad=methodology(); bad["selector_eligible"]=True
    v["artifacts"]["methodology"]={"kind":"METHODOLOGY_RESULT",**add("BAD_METHOD",bad)}
    ref=v["artifacts"]["methodology"]
    cache=a3._VerifiedArtifactCache(resolver)
    value=cache.object(ref["artifact_id"],ref["sha256"])
    for mutation in (lambda: value.__setitem__("selector_eligible",False),
                     lambda: dict.__setitem__(value,"selector_eligible",False),
                     lambda: value._values.__setitem__("selector_eligible",False),
                     lambda: setattr(value,"_values",{"selector_eligible":False}),
                     lambda: object.__setattr__(value,"_values",{"selector_eligible":False}),
                     lambda: value.__init__({"selector_eligible":False})):
      try: mutation()
      except (TypeError,AttributeError): pass
      # Some immutable builtins accept a no-op __init__; retained semantics
      # must survive it just as they survive rejected base-method writes.
      self.assertIs(value["selector_eligible"],True)
    with self.assertRaisesRegex(A3CandidatePacketError,"methodology_selector_authority"):
      evaluate_packet(v,"2026-09-19T02:00:00Z",resolver,_artifact_cache=cache)
    with self.assertRaisesRegex(A3CandidatePacketError,"methodology_selector_authority"):
      evaluate_packet(v,"2026-09-19T02:00:00Z",resolver)

  def test_cached_nested_containers_are_sealed_once_and_copies_are_independent(self):
    import a3_candidate_packet_v1 as a3
    from unittest.mock import patch
    raw=b'{"nested":{"flag":true},"items":[{"flag":true}]}'
    sha=hashlib.sha256(raw).hexdigest()
    reads=[]
    def read(aid,digest): reads.append((aid,digest)); return raw
    cache=a3._VerifiedArtifactCache(read)
    with patch.object(a3.json,"loads",wraps=a3.json.loads) as decode:
      value=cache.object("SEALED",sha)
      for _ in range(8):
        self.assertIs(cache.object("SEALED",sha),value)
        copied=a3._copy_json(value)
        copied["nested"]["flag"]=False
        copied["items"][0]["flag"]=False
        self.assertIs(value["nested"]["flag"],True)
        self.assertIs(value["items"][0]["flag"],True)
      self.assertEqual(decode.call_count,1)
    for mutation in (lambda: value["nested"].__setitem__("flag",False),
                     lambda: value["items"].__setitem__(0,{}),
                     lambda: list.__setitem__(value["items"],0,{}),
                     lambda: value["items"][0].__setitem__("flag",False)):
      with self.assertRaises((TypeError,AttributeError)): mutation()
    self.assertEqual(reads,[("SEALED",sha)])
    self.assertEqual(a3.canonical_sha256(value),a3.canonical_sha256(json.loads(raw)))

  def test_optional_cache_does_not_accept_ordinary_tuple_packet_fields(self):
    import a3_candidate_packet_v1 as a3
    v=packet(); v["thesis"]["catalysts"]=("unsupported tuple",)
    for cache in (None,a3._VerifiedArtifactCache(resolver)):
      with self.assertRaisesRegex(A3CandidatePacketError,"catalysts"):
        evaluate_packet(v,"2026-09-19T02:00:00Z",resolver,_artifact_cache=cache)

  def test_optional_cache_rejects_unverified_dict_and_wrong_resolver(self):
    v=packet()
    for cache in ({},a3._VerifiedArtifactCache(lambda aid,sha:b"{}")):
      with self.assertRaisesRegex(A3CandidatePacketError,"verified_artifact_cache_required"):
        evaluate_packet(v,"2026-09-19T02:00:00Z",resolver,_artifact_cache=cache)

  def test_optional_cache_strict_decode_matrix_and_raw_hash(self):
    for raw,reason in ((b'{"x":1,"x":2}',"duplicate_json_key"),
                       (b'{"x":NaN}',"nonfinite_json"),
                       (b'{"x":1e999}',"nonfinite_json"),
                       (b'{"x":'+b'['*65+b'0'+b']'*65+b'}',"json_depth_limit"),
                       (b'{',"invalid_json")):
      with self.subTest(reason=reason):
        sha=hashlib.sha256(raw).hexdigest()
        calls=[]
        def read(aid,digest): calls.append(aid); return raw
        cache=a3._VerifiedArtifactCache(read)
        with patch.object(a3,"_strict_json_object",wraps=a3._strict_json_object) as decoder:
          for _ in range(2):
            with self.assertRaisesRegex(A3CandidatePacketError,reason): cache.object("REF",sha)
        self.assertEqual(calls,["REF"])
        self.assertEqual(decoder.call_count,1)
    cache=a3._VerifiedArtifactCache(lambda aid,sha:b"tampered")
    with self.assertRaisesRegex(A3CandidatePacketError,"artifact_hash_mismatch"):
      cache.object("REF","0"*64)
    cache=a3._VerifiedArtifactCache(lambda aid,sha:{"pretend":"decoded"})
    with self.assertRaisesRegex(A3CandidatePacketError,"artifact_bytes"):
      cache.object("REF","0"*64)

  def test_optional_cache_failed_bytes_resource_and_identity_matrix(self):
    with patch.object(a3,"MAX_ARTIFACT_BYTES",16),patch.object(a3,"MAX_CACHED_TOTAL_BYTES",30):
      calls=[]
      def read(aid,sha): calls.append(aid); return b"x"*17
      cache=a3._VerifiedArtifactCache(read)
      for _ in range(2):
        with self.assertRaisesRegex(A3CandidatePacketError,"artifact_bytes"):
          cache.read("A","0"*64)
      with self.assertRaisesRegex(A3CandidatePacketError,"total_byte_budget"):
        cache.read("B","1"*64)
      self.assertEqual(calls,["A","B"])
    cache=a3._VerifiedArtifactCache(lambda aid,sha:b"{}")
    cache.read("A",hashlib.sha256(b"{}").hexdigest())
    with self.assertRaisesRegex(A3CandidatePacketError,"artifact_id_conflict"):
      cache.read("A","0"*64)

  def test_optional_cache_node_limit_and_per_row_contract_checks(self):
    raw=b'{"values":[0,1,2,3]}'
    cache=a3._VerifiedArtifactCache(lambda aid,sha:raw)
    with patch.object(a3,"MAX_JSON_NODES",3):
      with self.assertRaisesRegex(A3CandidatePacketError,"json_node_limit"):
        cache.object("REF",hashlib.sha256(raw).hexdigest())
    for field,bad,reason in (("kind","OTHER","artifact_kind"),
                             ("review_status","PENDING","artifact_review_status"),
                             ("available_at","2026-09-20T00:00:00Z","future_artifact")):
      v=packet()
      v["artifacts"]["methodology"][field]=bad
      with self.assertRaisesRegex(A3CandidatePacketError,reason):
        evaluate_packet(v,"2026-09-19T02:00:00Z",resolver,
                        _artifact_cache=a3._VerifiedArtifactCache(resolver))

def load_tests(loader, suite, pattern):
    # #516 reference adapter stays on the existing registered A3 smoke route.
    from candidate_registry_v1_smoke import RegistryTests
    suite.addTests(loader.loadTestsFromTestCase(RegistryTests))
    return suite


if __name__=="__main__": unittest.main()

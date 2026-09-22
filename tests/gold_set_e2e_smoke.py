#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tests")); sys.path.insert(0,str(ROOT/"tools"))
import a3_candidate_packet_v1_smoke as a3_fixture
import run_gold_set_e2e as gold

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8")

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name)
        a3_fixture.RAW.clear(); packet=a3_fixture.packet(False)
        raw=json.dumps(packet,sort_keys=True,separators=(",",":")).encode(); sha=hashlib.sha256(raw).hexdigest()
        (self.root/"packet.json").write_bytes(raw); index={"PACKET":{"path":"packet.json","sha256":sha}}
        for (aid,digest),payload in a3_fixture.RAW.items():
            name=f"raw/{len(index):03d}.json"; path=self.root/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(payload)
            index[aid]={"path":name,"sha256":digest}
        self.gold=self.root/"gold.json"
        write_json(self.gold,{"schema":"cross-market-gold-set-v1","authority":"RESEARCH_VALIDATION_ONLY",
            "candidates":[{"id":"US:EXAMPLE","ticker":"EXAMPLE","market":"NYSE","country":"US","asset_class":"EQUITY"}]})
        self.manifest=self.root/"manifest.json"
        write_json(self.manifest,{"schema_version":"gold-set-e2e-v1","research_only":True,"artifact_index":index,
            "candidates":[{"candidate_id":"US:EXAMPLE","ticker":"EXAMPLE","asset_class":"EQUITY",
                "a3_packet":{"artifact_id":"PACKET","sha256":sha},"phase2a_gross_research_er":None,"er_promotion_gate":None}],
            "authority":{"ranking":False,"portfolio":False,"target":False,"orders":False,"production":False}})
    def run_it(self):
        return gold.run(gold_set=self.gold,manifest_path=self.manifest,bundle_root=self.root,cutoff="2026-09-19T02:00:00Z")
    def test_valid_connectivity(self):
        out=self.run_it(); self.assertEqual(out["status"],"PASS_RESEARCH_CONNECTIVITY"); self.assertFalse(out["a5_execution_allowed"])
    def test_non_gold_rejected(self):
        v=json.loads(self.manifest.read_text()); v["candidates"][0]["candidate_id"]="US:NO"; write_json(self.manifest,v)
        with self.assertRaisesRegex(ValueError,"candidate_not_in_gold_set"): self.run_it()
    def test_packet_hash_bound(self):
        (self.root/"packet.json").write_text("{}")
        with self.assertRaisesRegex(ValueError,"artifact_bytes_hash_mismatch"): self.run_it()
    def test_manifest_authority_rejected(self):
        v=json.loads(self.manifest.read_text()); v["authority"]["portfolio"]=True; write_json(self.manifest,v)
        with self.assertRaisesRegex(ValueError,"manifest_economic_authority"): self.run_it()
    def test_phase2a_cannot_self_promote(self):
        v=json.loads(self.manifest.read_text())
        phase={"artifact_kind":"GROSS_RESEARCH_ER_EVIDENCE","net_of_costs":False,"a3_validated_er_eligible":False,
            "er_promotion_gate_status":"BLOCKED_GROSS_RESEARCH_ONLY","rows":[{"ticker":"EXAMPLE"}]}
        raw=json.dumps(phase,sort_keys=True,separators=(",",":")).encode(); sha=hashlib.sha256(raw).hexdigest()
        (self.root/"phase.json").write_bytes(raw); v["artifact_index"]["PHASE"]={"path":"phase.json","sha256":sha}
        v["candidates"][0]["phase2a_gross_research_er"]={"artifact_id":"PHASE","sha256":sha}; write_json(self.manifest,v)
        self.assertEqual(self.run_it()["status"],"PASS_RESEARCH_CONNECTIVITY")
        phase["a3_validated_er_eligible"]=True
        raw=json.dumps(phase,sort_keys=True,separators=(",",":")).encode(); sha=hashlib.sha256(raw).hexdigest()
        (self.root/"phase.json").write_bytes(raw); v["artifact_index"]["PHASE"]["sha256"]=sha
        v["candidates"][0]["phase2a_gross_research_er"]["sha256"]=sha; write_json(self.manifest,v)
        out=self.run_it(); self.assertEqual(out["status"],"BLOCKED"); self.assertIn("phase2a_a3_boundary",out["rows"][0]["blockers"])
if __name__=="__main__": unittest.main()

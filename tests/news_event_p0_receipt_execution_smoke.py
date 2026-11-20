"""Offline synthetic P0-2 fixtures. unittest assertions remain active under -O."""
from __future__ import annotations
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from research.news_event_alpha_v1 import runtime as R
from research.news_event_alpha_v1 import admission as A
from research.news_event_alpha_v1 import execution as E

NOW = "2026-09-19T12:00:00+00:00"


def fixture(n=300):
    # Deliberately artificial weekday schedule. No historical NYSE certification.
    d = datetime(2024, 1, 2, 21, tzinfo=timezone.utc)
    cal=[]
    while len(cal)<n:
        if d.weekday()<5:
            cal.append({"session":d.date().isoformat(),"market_close_utc":d.isoformat()})
        d+=timedelta(days=1)
    prices=[]
    for i,s in enumerate(cal):
        for sid,g in (("A",.003),("B",-.002),("SPY",.001)):
            prices.append({"stable_security_id":"TEST:"+sid,"session":s["session"],
                           "total_return_index":100*(1+g)**i,"available_at":(R.utc(s["market_close_utc"])+timedelta(minutes=1)).isoformat(),
                           "status":"ACTIVE","tradable":True,"currency":"USD","feed":"SYNTHETIC",
                           "return_convention":"USD_TOTAL_RETURN_INDEX"})
    snapshots=[]
    for sid in ("A","B"):
        snapshots.append({"event_id":"doc1","economic_event_id":"shared-economic-event",
            "stable_security_id":"TEST:"+sid,"security_id":sid,"issuer_id":"ISSUER:"+sid,
            "event_version":1,"available_at":cal[5]["market_close_utc"],
            "instrument":"COMMON","exchange":"XNYS","listing_country":"US","eligibility_verified_asof":True,
            "official_evidence":True,"event_type":"CONTRACT","role":"DIRECT","source_tier":"OFFICIAL",
            "business_relation_new":True,"economic_value_confirmed":False,"sample_origin":"HISTORICAL_BACKFILL",
            "checkpoint":0,"checkpoint_session":cal[5]["session"],
            "decision_at":(R.utc(cal[5]["market_close_utc"])+timedelta(minutes=2)).isoformat(),
            "price_features_available_at":(R.utc(cal[5]["market_close_utc"])+timedelta(minutes=1)).isoformat(),
            "source_document_ids":["doc1"],"feature_available_at":{},
            "theme_peer_ids":[],"independent_source_groups":["SYNTHETIC"]})
    source=R.canonical_bytes({"replay":{"fill_mode":"next_close","primary_cost_bps_per_side":25,"cost_sensitivity_bps_per_side":[25,50,100]}})
    policy={"schema":E.POLICY_SCHEMA,"entry":"NEXT_EXACT_SESSION_CLOSE",
        "missing_entry":"NO_FILL_NO_FORWARD_SUBSTITUTION","cost_basis":"PROPORTIONAL_NOTIONAL_EACH_SIDE",
        "currency":"USD","cost_bps_per_side":[25,50,100],"benchmark_security_id":"TEST:SPY","benchmark_symbol":"SPY",
        "return_convention":"USD_TOTAL_RETURN_INDEX","portfolio_authority":False,"orders_authority":False,
        "automatic_promotion_allowed":False,"source_contract_path":"upstream_policy.json",
        "source_contract_sha256":A.sha256(source)}
    cutoff=(R.utc(cal[-1]["market_close_utc"])+timedelta(minutes=3)).isoformat()
    return cal,prices,snapshots,policy,source,cutoff


def write_bundle(root, *, origin="SYNTHETIC_TEST"):
    cal, prices, snap, policy, source, cutoff=fixture()
    if origin=="FORWARD_OBSERVED":
        for s in snap:s["sample_origin"]="FORWARD_SHADOW"
    raw=b"SYNTHETIC DOCUMENT. NO MARKET CLAIMS.\n"
    doc={"document_id":"doc1","raw_path":"raw/doc1.txt","raw_sha256":A.sha256(raw),"source_id":"test",
        "source_public_at":"2023-12-01T00:00:00+00:00","ingested_at":"2023-12-01T00:01:00+00:00",
        "revision_policy":"IMMUTABLE_PUBLIC_VERSION","source_url":"https://example.invalid/synthetic"}
    securities=[{"stable_security_id":"TEST:"+s,"issuer_id":"ISSUER:"+s,"ticker":s,"instrument":"ETF" if s=="SPY" else "COMMON",
        "exchange":"XNYS","listing_country":"US","valid_from":cal[0]["session"],"valid_to":cal[-1]["session"],
        "known_at":"2023-12-01T00:00:00+00:00","evidence_document_id":"doc1"} for s in ("A","B","SPY")]
    rights={"schema":"news-event-source-rights-p0.2","sources":[{"source_id":"test","evidence_path":"rights.txt",
        "read":True,"store":True,"derive":True,"train":False,"redistribute":False,
        "reviewed_at":"2024-01-01T00:00:00+00:00","valid_until":"2027-01-01T00:00:00+00:00"}]}
    coverage={"schema":"news-event-coverage-p0.2","scope":"DECLARED_INPUT_ONLY_NOT_ENTIRE_US_MARKET",
        "calendar_start":cal[0]["session"],"calendar_end":cal[-1]["session"],"calendar_evidence_path":"schedule_evidence.jsonl",
        "historical_universe_complete":False,"selection_rule":"SYNTHETIC_FIXTURE_ONLY",
        "included_event_security_revisions":2,"candidate_count":3,"rejected_events":[{"event_id":"rejected","reason":"SYNTHETIC_NO_SOURCE"}],
        "price_row_count":len(prices),"document_count":1}
    values={"snapshots":snap,"prices":prices,"sessions":cal,"securities":securities,"documents":[doc],
            "rights":rights,"coverage":coverage,"policy":policy,
            "config":{"schema":"news-event-audit-config-p0.2","scope":"BOUNDED_LABEL_AUDIT",
                      "selector_enabled":False,"portfolio_enabled":False,"orders_enabled":False,"historical_training_enabled":False}}
    entries=[]
    for role,v in values.items():
        path=role+(".jsonl" if isinstance(v,list) else ".json")
        data=b"".join(R.canonical_bytes(x) for x in v) if isinstance(v,list) else R.canonical_bytes(v)
        (root/path).write_bytes(data)
        entries.append({"role":role,"path":path,"bytes":len(data),"sha256":A.sha256(data),"source_id":"test"})
    for path,role,data in (("raw/doc1.txt","raw_object",raw),("rights.txt","rights_evidence",b"Synthetic fixture rights declaration, not a license."),
                           ("upstream_policy.json","policy_source",source),
                           ("schedule_evidence.jsonl","calendar_evidence",(root/"sessions.jsonl").read_bytes())):
        (root/path).parent.mkdir(exist_ok=True,parents=True);(root/path).write_bytes(data)
        entries.append({"role":role,"path":path,"bytes":len(data),"sha256":A.sha256(data),"source_id":"test"})
    m={"schema":"news-event-input-bundle-p0.2","consumer":A.CONSUMER,"origin":origin,"source_commit":"a"*40,
       "data_cutoff":cutoff,"generated_at":"2026-09-18T10:00:00+00:00","generation":1,"parent_receipt_sha256":None,"files":entries}
    (root/"manifest.json").write_bytes(R.canonical_bytes(m))
    return m


def mutate_file(root, name, fn, *, jsonl=False):
    p=root/name
    data=A.rows(p.read_bytes()) if jsonl else A.json_load(p.read_bytes())
    fn(data)
    raw=b"".join(R.canonical_bytes(x) for x in data) if jsonl else R.canonical_bytes(data)
    p.write_bytes(raw)
    m=A.json_load((root/"manifest.json").read_bytes())
    for e in m["files"]:
        if e["path"]==name:e.update(bytes=len(raw),sha256=A.sha256(raw))
    (root/"manifest.json").write_bytes(R.canonical_bytes(m))


def make_receipt(b):
    r={"schema":"news-input-review-receipt-p0.2","consumer":A.CONSUMER,
       "manifest_sha256":b.manifest_sha256,"source_commit":b.manifest["source_commit"],
       "policy_sha256":A.sha256(b.files[b.roles["policy"]]),"config_sha256":A.sha256(b.files[b.roles["config"]]),
       "generation":b.manifest["generation"],"parent_receipt_sha256":b.manifest["parent_receipt_sha256"],
       "reviewed_at":"2026-09-18T11:00:00+00:00","valid_until":"2027-01-01T00:00:00+00:00",
       "approved_purpose":"BOUNDED_LABEL_AUDIT","reviews":{k:"VERIFIED_FOR_DECLARED_SCOPE" for k in ("rights","pit","security_identity","calendar","coverage")}}
    raw=R.canonical_bytes(r)
    reg={"schema":"news-input-approval-registry-p0.2","approvals":[{"receipt_sha256":A.sha256(raw),"manifest_sha256":b.manifest_sha256,
         "expected_parent":b.manifest["parent_receipt_sha256"],"revoked":False,"review_evidence":"synthetic test harness, NOT actual approval"}]}
    return r,raw,reg


class ExecutionTests(unittest.TestCase):
    def setUp(self): self.cal,self.prices,self.snap,self.policy,self.source,self.cutoff=fixture()
    def run_labels(self,**kwargs):
        return E.attach_executable_outcomes(kwargs.pop("snapshots",self.snap),kwargs.pop("prices",self.prices),
                kwargs.pop("sessions",self.cal),as_of=kwargs.pop("as_of",self.cutoff),policy=kwargs.pop("policy",self.policy),**kwargs)
    def a5(self,**kw): return self.run_labels(horizons=(5,),**kw)[0]
    def test_next_close_not_same_close(self):
        r=self.a5();self.assertEqual(r["entry_session"],self.cal[6]["session"]);self.assertEqual(r["outcome_end_session"],self.cal[11]["session"])
    def test_no_announcement_jump_is_captured(self):
        for p in self.prices:
            if p["stable_security_id"]=="TEST:A" and p["session"]>=self.cal[6]["session"]:p["total_return_index"]*=1.5
        self.assertAlmostEqual(self.a5()["absolute_gross_return"],1.003**5-1)
    def test_cost_formula_buy_and_sell(self):
        r=self.a5();self.assertAlmostEqual(r["cost_scenarios"][0]["absolute_net_return"],(1+r["absolute_gross_return"])*.9975/1.0025-1)
    def test_costs_monotonic(self):
        x=[s["absolute_net_return"] for s in self.a5()["cost_scenarios"]];self.assertGreater(x[0],x[1]);self.assertGreater(x[1],x[2])
    def test_matched_cost_benchmark_separate(self):
        s=self.a5()["cost_scenarios"][0];self.assertNotEqual(s["net_excess_vs_gross_benchmark"],s["net_excess_vs_matched_cost_benchmark"])
    def test_shared_event_two_stable_ids(self):
        r=self.run_labels(horizons=(5,));self.assertEqual(len(r),2);self.assertNotEqual(r[0]["outcome_id"],r[1]["outcome_id"]);self.assertGreater(r[0]["absolute_gross_return"],r[1]["absolute_gross_return"])
    def test_no_fill_when_entry_absent(self):
        p=[p for p in self.prices if not(p["stable_security_id"]=="TEST:A" and p["session"]==self.cal[6]["session"])];self.assertEqual(self.a5(prices=p)["outcome_status"],"NO_FILL_ENTRY_PRICE_MISSING")
    def test_no_fill_halted_entry(self):
        for p in self.prices:
            if p["stable_security_id"]=="TEST:A" and p["session"]==self.cal[6]["session"]:p.update(status="HALTED",tradable=False,total_return_index=None)
        self.assertEqual(self.a5()["outcome_status"],"NO_FILL_ENTRY_HALTED")
    def test_delisted_unknown_is_not_erased(self):
        for p in self.prices:
            if p["stable_security_id"]=="TEST:A" and p["session"]==self.cal[11]["session"]:p.update(status="DELISTED_UNKNOWN",tradable=False,total_return_index=None)
        self.assertEqual(self.a5()["outcome_status"],"PENDING_EXIT_DELISTED_UNKNOWN")
    def test_exit_missing_stays_pending(self):
        p=[p for p in self.prices if not(p["stable_security_id"]=="TEST:A" and p["session"]==self.cal[11]["session"])];self.assertEqual(self.a5(prices=p)["outcome_status"],"PENDING_EXIT_PRICE")
    def test_missing_path_keeps_endpoint_but_blocks_risk(self):
        p=[p for p in self.prices if not(p["stable_security_id"]=="TEST:A" and p["session"]==self.cal[8]["session"])];r=self.a5(prices=p);self.assertEqual(r["outcome_status"],"RESOLVED");self.assertEqual(r["path_status"],"INCOMPLETE");self.assertIsNone(r["path_max_drawdown"])
    def test_terminal_loss_is_minus_one(self):
        p=[p for p in self.prices if not(p["stable_security_id"]=="TEST:A" and p["session"]>=self.cal[9]["session"])]; t=copy.deepcopy(self.prices[9*3]);t.update(total_return_index=0,status="TERMINAL_LOSS",tradable=False,terminal_evidence_id="doc1");p.append(t)
        r=self.a5(prices=p);self.assertEqual(r["absolute_gross_return"],-1.0);self.assertEqual(r["cost_scenarios"][0]["absolute_net_return"],-1.0);self.assertEqual(r["path_max_drawdown"],-1.0)
    def test_zero_without_terminal_rejected(self):
        self.prices[0]["total_return_index"]=0
        with self.assertRaisesRegex(R.ContractError,"NONTERMINAL_ZERO"):self.a5()
    def test_tradable_string_rejected(self):
        self.prices[0]["tradable"]="false"
        with self.assertRaises(R.ContractError):self.a5()
    def test_mixed_feeds_rejected(self):
        self.prices[0]["feed"]="OTHER"
        with self.assertRaisesRegex(R.ContractError,"MIXED_PRICE_FEED"):self.a5()
    def test_missing_benchmark_not_substituted(self):
        p=[p for p in self.prices if not(p["stable_security_id"]=="TEST:SPY" and p["session"]==self.cal[11]["session"])];self.assertEqual(self.a5(prices=p)["outcome_status"],"PENDING_BENCHMARK_EXIT")
    def test_future_bar_rejected(self):
        self.prices[-1]["available_at"]="2027-01-01T00:00:00Z"
        with self.assertRaisesRegex(R.ContractError,"PRICE_AFTER_ASOF"):self.a5()
    def test_bar_before_close_rejected(self):
        self.prices[0]["available_at"]="2023-01-01T00:00:00Z"
        with self.assertRaisesRegex(R.ContractError,"PRICE_BEFORE_CLOSE"):self.a5()
    def test_future_horizon_pending(self):
        cutoff=(R.utc(self.cal[8]["market_close_utc"])+timedelta(minutes=3)).isoformat();p=[p for p in self.prices if R.utc(p["available_at"])<=R.utc(cutoff)]
        r=self.a5(prices=p,as_of=cutoff);self.assertEqual(r["outcome_status"],"PENDING_HORIZON");self.assertIsNone(r["absolute_gross_return"])
    def test_late_decision_never_backfills_entry(self):
        self.snap[0]["decision_at"]=self.cal[6]["market_close_utc"];self.assertEqual(self.a5()["outcome_status"],"NO_FILL_MISSED_ENTRY_WINDOW")
    def test_duplicate_checkpoints_rejected(self):
        with self.assertRaisesRegex(R.ContractError,"duplicate"):self.a5(snapshots=[self.snap[0],self.snap[0]])
    def test_different_versions_do_not_mix(self):
        s=copy.deepcopy(self.snap[0]);s["event_version"]=2;r=self.run_labels(snapshots=[self.snap[0],s],horizons=(5,));self.assertNotEqual(r[0]["outcome_id"],r[1]["outcome_id"])
    def test_horizon_max_273_after_event(self):
        self.snap[0].update(checkpoint=20,checkpoint_session=self.cal[25]["session"],decision_at=(R.utc(self.cal[25]["market_close_utc"])+timedelta(minutes=2)).isoformat());r=self.run_labels(snapshots=[self.snap[0]],horizons=(252,))[0];self.assertEqual(r["outcome_end_session"],self.cal[278]["session"])
    def test_training_waits_for_availability(self):
        r=self.a5(); self.assertEqual(E.mature_training_rows([r],r["label_available_at"]),[]);later=(R.utc(r["label_available_at"])+timedelta(seconds=1)).isoformat();self.assertEqual(len(E.mature_training_rows([r],later)),1)
    def test_dst_and_skipped_session_obey_supplied_calendar(self):
        # Exercise irregular supplied sessions, not a claimed exchange calendar.
        cal=[{"session":d,"market_close_utc":d+"T"+t+":00+00:00"} for d,t in [("2024-03-08","21:00"),("2024-03-11","20:00"),("2024-03-12","20:00"),("2024-03-14","20:00"),("2024-03-15","20:00"),("2024-03-18","20:00"),("2024-03-19","20:00")]]
        p=[]
        for s in cal:
            for sid in ("TEST:A","TEST:SPY"):
                t=copy.deepcopy(self.prices[0]);t.update(stable_security_id=sid,session=s["session"],available_at=s["market_close_utc"]);p.append(t)
        s=copy.deepcopy(self.snap[0]);s.update(checkpoint_session=cal[0]["session"],decision_at=cal[0]["market_close_utc"],available_at=cal[0]["market_close_utc"])
        r=self.run_labels(snapshots=[s],prices=p,sessions=cal,as_of=cal[-1]["market_close_utc"],horizons=(5,))[0];self.assertEqual(r["entry_session"],"2024-03-11");self.assertEqual(r["outcome_end_session"],"2024-03-19")


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);write_bundle(self.root)
    def tearDown(self): self.t.cleanup()
    def verify(self):return A.verify_bundle(self.root,now=NOW)
    def test_valid_bytes_do_not_grant_authority(self):
        b=self.verify();self.assertEqual(b.report["status"],"BYTE_AND_GRAPH_CHECKED_NOT_AUTHORIZED");self.assertFalse(b.report["pit_truth_independently_verified"])
    def test_tampered_price_hash(self):
        with (self.root/"prices.jsonl").open("ab") as f:f.write(b" ")
        with self.assertRaisesRegex(R.ContractError,"HASH_MISMATCH"):self.verify()
    def test_extra_secret_file_rejected(self):
        (self.root/".env").write_text("NOT_A_REAL_SECRET")
        with self.assertRaisesRegex(R.ContractError,"UNDECLARED"):self.verify()
    def test_input_snapshot_not_reread_after_verification(self):
        b=self.verify();before=b.rows("prices");(self.root/"prices.jsonl").write_text("BAD");self.assertEqual(b.rows("prices"),before)
    def test_duplicate_json_keys_rejected(self):
        with self.assertRaisesRegex(R.ContractError,"DUPLICATE"):A.json_load(b'{"a":1,"a":2}')
    def test_nan_json_rejected(self):
        with self.assertRaisesRegex(R.ContractError,"NONFINITE"):A.json_load(b'{"a":NaN}')
    def test_symlink_rejected(self):
        p=self.root/"link"
        try:p.symlink_to(self.root/"rights.txt")
        except OSError:self.skipTest("symlink unavailable")
        with self.assertRaisesRegex(R.ContractError,"SYMLINK"):self.verify()
    def test_duplicate_file_case_rejected(self):
        def change(m):m["files"].append(dict(m["files"][0],path=m["files"][0]["path"].upper()))
        self.manifest(change)
        with self.assertRaisesRegex(R.ContractError,"DUPLICATE_FILE"):self.verify()
    def manifest(self,fn):
        p=self.root/"manifest.json";m=A.json_load(p.read_bytes());fn(m);p.write_bytes(R.canonical_bytes(m))
    def test_structural_historical_not_forward(self):
        self.manifest(lambda m:m.update(origin="FORWARD_OBSERVED"))
        with self.assertRaisesRegex(R.ContractError,"ORIGIN_LAUNDERING"):self.verify()
    def test_real_approval_requires_external_registry(self):
        self.manifest(lambda m:m.update(origin="HISTORICAL_RECONSTRUCTION"));b=self.verify();r,raw,reg=make_receipt(b)
        with self.assertRaisesRegex(R.ContractError,"NOT_IN_REVIEWED"):A.require_reviewed_receipt(b,raw,reviewed_registry={"schema":reg["schema"],"approvals":[]},expected_parent=None,now=NOW)
    def test_reviewed_path_is_not_training_permission(self):
        self.manifest(lambda m:m.update(origin="HISTORICAL_RECONSTRUCTION"));b=self.verify();r,raw,reg=make_receipt(b)
        a=A.require_reviewed_receipt(b,raw,reviewed_registry=reg,expected_parent=None,now=NOW);self.assertFalse(a["historical_training_allowed"])
    def test_synthetic_cannot_be_registered_as_real(self):
        b=self.verify();r,raw,reg=make_receipt(b)
        with self.assertRaisesRegex(R.ContractError,"SYNTHETIC_CANNOT"):A.require_reviewed_receipt(b,raw,reviewed_registry=reg,expected_parent=None,now=NOW)
    def test_wrong_parent_blocks(self):
        self.manifest(lambda m:m.update(origin="HISTORICAL_RECONSTRUCTION"));b=self.verify();r,raw,reg=make_receipt(b)
        with self.assertRaisesRegex(R.ContractError,"PARENT_BINDING"):A.require_reviewed_receipt(b,raw,reviewed_registry=reg,expected_parent="f"*64,now=NOW)
    def test_revoked_review_blocks(self):
        self.manifest(lambda m:m.update(origin="HISTORICAL_RECONSTRUCTION"));b=self.verify();r,raw,reg=make_receipt(b);reg["approvals"][0]["revoked"]=True
        with self.assertRaisesRegex(R.ContractError,"REVOKED"):A.require_reviewed_receipt(b,raw,reviewed_registry=reg,expected_parent=None,now=NOW)
    def test_cli_synthetic_end_to_end(self):
        out=self.root.parent/(self.root.name+"-output")
        try:
            proc=subprocess.run([sys.executable,"-B",str(ROOT/"tools/audit_news_event_inputs_p0.py"),"--bundle",str(self.root),"--synthetic-only","--output-dir",str(out)],capture_output=True,text=True,timeout=20)
            self.assertEqual(proc.returncode,0,proc.stderr);r=json.loads(proc.stdout);self.assertEqual(r["status"],"SYNTHETIC_LABEL_AUDIT_PASS");self.assertEqual(r["total_outcome_rows"],12)
            data=A.rows((out/"next_close_outcomes.jsonl").read_bytes());self.assertTrue(all(d["synthetic_only"] for d in data))
            proc=subprocess.run([sys.executable,"-B",str(ROOT/"tools/audit_news_event_inputs_p0.py"),"--bundle",str(self.root),"--synthetic-only","--output-dir",str(out)],capture_output=True,text=True,timeout=20);self.assertNotEqual(proc.returncode,0)
        finally:
            import shutil
            if out.exists():shutil.rmtree(out)
    def test_cli_inspect_does_not_write(self):
        before={p.relative_to(self.root).as_posix():A.sha256(p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
        proc=subprocess.run([sys.executable,"-B",str(ROOT/"tools/audit_news_event_inputs_p0.py"),"--bundle",str(self.root)],capture_output=True,text=True,timeout=20)
        self.assertEqual(proc.returncode,0,proc.stderr);after={p.relative_to(self.root).as_posix():A.sha256(p.read_bytes()) for p in self.root.rglob('*') if p.is_file()};self.assertEqual(before,after)


# Each named mutation rewrites its manifest hash too: these exercise semantics,
# not simply the same hash-mismatch assertion repeatedly.
MUTATIONS = [
 ("rights_false","rights.json",False,lambda d:d["sources"][0].update(store=False),"RIGHTS_NOT_GRANTED"),
 ("rights_string","rights.json",False,lambda d:d["sources"][0].update(read="true"),"boolean"),
 ("rights_expired","rights.json",False,lambda d:d["sources"][0].update(valid_until="2025-01-01T00:00:00Z"),"RIGHTS_EXPIRED"),
 ("rights_evidence_missing","rights.json",False,lambda d:d["sources"][0].update(evidence_path="missing"),"RIGHTS_EVIDENCE"),
 ("wrong_costs","policy.json",False,lambda d:d.update(cost_bps_per_side=[0,25,50]),"COST_SCENARIOS"),
 ("same_close_policy","policy.json",False,lambda d:d.update(entry="SAME_CLOSE"),"POLICY_ENTRY"),
 ("wrong_policy_source_hash","policy.json",False,lambda d:d.update(source_contract_sha256="0"*64),"POLICY_SOURCE_HASH"),
 ("orders_enabled","config.json",False,lambda d:d.update(orders_enabled=True),"CONFIG_AUTHORITY"),
 ("training_enabled","config.json",False,lambda d:d.update(historical_training_enabled=True),"CONFIG_AUTHORITY"),
 ("candidate_denominator","coverage.json",False,lambda d:d.update(candidate_count=999),"COVERAGE_DENOMINATOR"),
 ("document_count","coverage.json",False,lambda d:d.update(document_count=99),"DOCUMENT_COUNT"),
 ("price_count","coverage.json",False,lambda d:d.update(price_row_count=99),"PRICE_COUNT"),
 ("full_market_claim","coverage.json",False,lambda d:d.update(historical_universe_complete=True),"FULL_UNIVERSE"),
 ("rejection_removed","coverage.json",False,lambda d:d.update(rejected_events=[]),"DENOMINATOR"),
 ("raw_source_hash","documents.jsonl",True,lambda d:d[0].update(raw_sha256="0"*64),"DOCUMENT_RAW_HASH"),
 ("credential_url","documents.jsonl",True,lambda d:d[0].update(source_url="https://host.invalid/data?token=x"),"SOURCE_URL"),
 ("wrong_issuer","snapshots.jsonl",True,lambda d:d[0].update(issuer_id="OTHER"),"SECURITY_MISMATCH"),
 ("future_feature","snapshots.jsonl",True,lambda d:d[0].update(feature_available_at={"x":"2025-01-01T00:00:00Z"}),"FUTURE_FEATURE"),
 ("duplicate_snapshot","snapshots.jsonl",True,lambda d:d.append(copy.deepcopy(d[0])),"DUPLICATE_SNAPSHOT"),
 ("future_source","documents.jsonl",True,lambda d:d[0].update(source_public_at="2026-01-01T00:00:00Z",ingested_at="2026-01-01T00:00:00Z"),"SECURITY_BACKDATED"),
 ("unverified_us","snapshots.jsonl",True,lambda d:d[0].update(eligibility_verified_asof="false"),"boolean"),
 ("outside_us","securities.jsonl",True,lambda d:d[0].update(listing_country="KR"),"NON_US_SECURITY"),
 ("duplicate_security","securities.jsonl",True,lambda d:d.append(copy.deepcopy(d[0])),"INTERVAL_OVERLAP"),
 ("future_security","securities.jsonl",True,lambda d:d[0].update(known_at="2025-01-01T00:00:00Z"),"NOT_KNOWN"),
 ("price_feed","prices.jsonl",True,lambda d:d[0].update(feed="IEX"),"MIXED_PRICE_FEED"),
 ("price_currency","prices.jsonl",True,lambda d:d[0].update(currency="KRW"),"PRICE_CURRENCY"),
 ("duplicate_prices","prices.jsonl",True,lambda d:d.append(copy.deepcopy(d[0])),"DUPLICATE_PRICE"),
 ("raw_price","prices.jsonl",True,lambda d:d[0].update(return_convention="RAW_CLOSE"),"PRICE_ADJUSTMENT"),
 ("snapshot_offset","snapshots.jsonl",True,lambda d:d[0].update(checkpoint=5),"CHECKPOINT_OFFSET"),
 ("price_snapshot_backdating","snapshots.jsonl",True,lambda d:d[0].update(price_features_available_at=d[0]["available_at"]),"PRICE_BACKDATED"),
 ("spy_identity","securities.jsonl",True,lambda d:d[2].update(ticker="QQQ"),"BENCHMARK_MAPPING"),
]

def add_mutation(name, file, is_lines, fn, code):
    def test(self):
        mutate_file(self.root,file,fn,jsonl=is_lines)
        with self.assertRaisesRegex((R.ContractError,ValueError),code):self.verify()
    test.__name__="test_mutation_"+name
    setattr(BundleTests,test.__name__,test)
for args in MUTATIONS:add_mutation(*args)

class PathTests(unittest.TestCase):pass
for i,path in enumerate(("../x","/tmp/x","C:/x","a\\b","a//b","a/./b","a/../b","a:b","NUL.txt","x. ","x/COM1")):
    def test(self,p=path):
        with self.assertRaises(R.ContractError):A.safe_rel(p)
    setattr(PathTests,f"test_unsafe_path_{i:02}",test)

class ReceiptBindingTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name)
        write_bundle(self.root,origin="HISTORICAL_RECONSTRUCTION")
        self.b=A.verify_bundle(self.root,now=NOW)
    def tearDown(self):self.t.cleanup()

RECEIPT_MUTATIONS=[
 ("manifest",lambda r:r.update(manifest_sha256="0"*64),"MANIFEST_BINDING"),
 ("source",lambda r:r.update(source_commit="0"*40),"CODE_BINDING"),
 ("policy",lambda r:r.update(policy_sha256="0"*64),"POLICY_BINDING"),
 ("config",lambda r:r.update(config_sha256="0"*64),"CONFIG_BINDING"),
 ("generation",lambda r:r.update(generation=2),"GENERATION"),
 ("parent",lambda r:r.update(parent_receipt_sha256="0"*64),"PARENT_BINDING"),
 ("review_time",lambda r:r.update(reviewed_at="2020-01-01T00:00:00Z"),"PRECEDES_DATA"),
 ("expiry",lambda r:r.update(valid_until="2020-01-01T00:00:00Z"),"CLOCK"),
 ("purpose",lambda r:r.update(approved_purpose="TRAIN_AND_TRADE"),"PURPOSE"),
 ("pit",lambda r:r["reviews"].update(pit="NOT_REVIEWED"),"RECEIPT_REVIEW"),
 ("consumer",lambda r:r.update(consumer="other-tool"),"CONSUMER"),
]
for name,fn,code in RECEIPT_MUTATIONS:
    def test(self,f=fn,c=code):
        r,raw,reg=make_receipt(self.b);f(r);raw=R.canonical_bytes(r)
        # Re-pin the test-only approval to exercise receipt/bundle binding itself.
        reg["approvals"][0]["receipt_sha256"]=A.sha256(raw)
        with self.assertRaisesRegex(R.ContractError,c):
            A.require_reviewed_receipt(self.b,raw,reviewed_registry=reg,expected_parent=None,now=NOW)
    setattr(ReceiptBindingTests,"test_receipt_binding_"+name,test)

if __name__=="__main__": unittest.main(verbosity=2)

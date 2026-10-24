"""Synthetic lifecycle cases using actual XML parser and filesystem readback."""
from __future__ import annotations
import copy
import argparse
import io
import re
import runpy
import shlex
import shutil
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd
from tools import run_sec_research_consumption as c
from tools.run_sec_form4_parser import parse_form4_xml
from tools.run_form4_transaction_event_builder import build_ownership_research_events
from tools.run_13f_position_event_builder import build_disclosure_research_events

NOW = "2026-10-22T10:00:00Z"
CHECK = "2026-10-22T09:00:00Z"
ACCEPTED = "2026-10-21T20:00:00Z"
SUBJECTS = c.encoded(dict(scope="SUPPLIED_US_IDENTITY_ASSERTIONS", rows=[
    dict(security_id="US:TEST:COMMON", issuer_id="CIK:0000000001", tickers=["TEST"], country="US", currency="USD")]))


def source(status="CHECKED_NEW_OR_EXISTING"):
    events, _ = filing()
    return dict(schema="sec-research-consumption-source-v1", source_scope="SYNTHETIC_CONTRACT_FIXTURE",
        status=status, generation_id="fixture", generated_at=CHECK,
        last_successful_source_check=CHECK, latest_accepted_at=ACCEPTED,
        source_coverage=dict(complete=True, requested=1, checked=1), current_eligible=True,
        event_scope=scope(events))


def scope(events):
    return {e["event_id"]: {k:e[k] for k in ("document_sha256", "issuer_cik10", "accession", "form_type", "ticker", "accepted_at", "available_at")} for e in events}


def filing(accession="0000000001-26-000001", form="4", original="", price=""):
    xml = (f'<ownershipDocument><documentType>{form}</documentType>'
        f'<dateOfOriginalSubmission>{original}</dateOfOriginalSubmission>'
        '<issuer><issuerCik>1</issuerCik><issuerTradingSymbol>TEST</issuerTradingSymbol></issuer>'
        '<reportingOwner><reportingOwnerId><rptOwnerCik>2</rptOwnerCik><rptOwnerName>Fixture</rptOwnerName></reportingOwnerId></reportingOwner>'
        '<nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Common Stock</value></securityTitle>'
        '<transactionDate><value>2026-10-20</value></transactionDate><transactionCoding><transactionCode>P</transactionCode></transactionCoding>'
        f'<transactionAmounts><transactionShares><value>10</value></transactionShares><transactionPricePerShare><value>{price}</value></transactionPricePerShare>'
        '</transactionAmounts></nonDerivativeTransaction></nonDerivativeTable><footnotes><footnote id="F1">Private placement, venue unverified</footnote></footnotes></ownershipDocument>').encode()
    metadata = dict(cik10="0000000001", ticker="TEST", accession_number=accession,
        form_type=form, accepted_at=ACCEPTED, available_from=ACCEPTED, filing_date="2026-10-21")
    events = build_ownership_research_events(pd.DataFrame(parse_form4_xml(xml.decode(), accession, metadata)))
    return events, {c.digest(xml): xml}


def checked_generation(root, index, raw_by_accession, checks=None):
    """Synthetic offline Source->parser->merge pipeline using real implementations."""
    from tools import run_sec_submissions_collector as source
    from tools import run_sec_form4_parser as parser
    from tools import run_sec_form4_merge_shards as merge
    pit, shard = root/"pit", root/"pit/shards/daily"
    checks = checks or [dict(ticker="TEST",cik10="0000000001",status="CHECKED_NEW_FILINGS",
                             checked_at=CHECK,payload_sha256="a"*64)]
    source.write_outputs(index,shard,collection_metadata={"source_checks":checks})
    with patch.object(parser,"cache_form4_document",side_effect=lambda row,*args,**kw:
                      (None,raw_by_accession[row["accession_number"]].decode())):
        parsed = parser.parse_form4_index(index,raw_dir=root/"raw",sleep_s=0)
    parser.write_outputs(parsed,shard)
    args=argparse.Namespace(pit_root=str(pit),output_dir=str(root/"signals"),as_of_dates_csv="",
        as_of_date_column="date",window_days=90,signal_mode="current",decision_at=NOW,
        source_check_summary=str(shard/"sec_filings_index_summary.json"))
    with patch.object(merge,"datetime") as clock:
        clock.now.return_value=pd.Timestamp(NOW).to_pydatetime()
        result=merge.run(args)
    return pit,shard,result


def fixture_index(accession="0000000001-26-000001", form="4", **kw):
    return dict(cik10="0000000001",ticker="TEST",accession_number=accession,form_type=form,
        accepted_at=ACCEPTED,available_from=ACCEPTED,filing_date="2026-10-21",primary_document="fixture.xml",**kw)


class ConsumptionTests(unittest.TestCase):
    def consume(self, root, events=None, raws=None, receipt=None, **kw):
        if events is None:
            events, raws = filing()
        supplied = receipt or source()
        if receipt is None:
            supplied["event_scope"] = scope(events)
        return c.consume(events, receipt=supplied, raw_by_hash=raws,
            identities=SUBJECTS, output_root=root, decision_at=kw.pop("decision_at", NOW), **kw)

    def test_new_actual_files_replay_and_generation_change(self):
        with tempfile.TemporaryDirectory() as td:
            first = self.consume(td)
            self.assertEqual(len(first["created_requests"]), 1)
            state = c.readback(td)
            request = next(iter(state["requests"].values()))
            record = json.loads(c.read_ref(Path(td), request["registry_ref"]))
            self.assertEqual(record["request_kind"], "CANDIDATE_RESEARCH_INTAKE")
            ref = json.loads(c.read_ref(Path(td), record["a3_filing_review_refs"][0]))
            self.assertEqual(ref["status"], "FILING_CONTENT_REVIEW_PENDING")
            self.assertIsNone(ref["source_row"]["transaction_price"])
            self.assertFalse(ref["used_for_assessment"])
            before = (Path(td)/"control_plane/candidate_registry/filing_requests.json").read_bytes()
            another = source(); another["generation_id"] = "later-generation"
            replay = self.consume(td, receipt=another)
            self.assertEqual(replay["created_requests"], [])
            self.assertEqual(replay["notification_intents_created"], 0)
            self.assertEqual(before, (Path(td)/"control_plane/candidate_registry/filing_requests.json").read_bytes())

    def test_mixed_legacy_numeric_promotion_preserves_raw_semantics_and_replay(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);_,raws=filing();raw=next(iter(raws.values()));acc="0000000001-26-000001"
            pit,_,_=checked_generation(root,pd.DataFrame([fixture_index()]),{acc:raw})
            receipt,frame=c.verify_ownership_generation(pit,decision_at=NOW)
            events=build_ownership_research_events(frame)
            first=c.consume(events,receipt=receipt,raw_by_hash=raws,identities=SUBJECTS,output_root=root/"research",decision_at=NOW)
            manifest=root/"research/control_plane/candidate_registry/filing_requests.json";before=manifest.read_bytes()
            legacy=frame.drop(columns=["reporting_owner_count","transaction_id"]).copy()
            legacy["accession_number"]="0000000001-26-000099";legacy["parser_schema_version"]="legacy"
            cache=pit/"shards/legacy";cache.mkdir();legacy.to_parquet(cache/"form4_transactions.parquet",index=False)
            pit,_,_=checked_generation(root,pd.DataFrame([fixture_index()]),{acc:raw})
            receipt,frame=c.verify_ownership_generation(pit,decision_at=NOW)
            promoted=build_ownership_research_events(frame)
            self.assertIs(type(promoted[0]["source_row"]["reporting_owner_count"]),float)
            self.assertEqual(promoted[0]["source_row"]["reporting_owner_count"],1.0)
            replay=c.consume(promoted,receipt=receipt,raw_by_hash=raws,identities=SUBJECTS,output_root=root/"research",decision_at=NOW)
            self.assertEqual(replay["created_requests"],[]);self.assertEqual(replay["notification_intents_created"],0)
            self.assertEqual(before,manifest.read_bytes())
            created=c.consume(promoted,receipt=receipt,raw_by_hash=raws,identities=SUBJECTS,output_root=root/"fresh",decision_at=NOW)
            self.assertEqual(len(created["created_requests"]),1);c.readback(root/"fresh")
            for value in (True,None,"1",1.25,1.000000000001,float("inf")):
                broken=copy.deepcopy(promoted[0]);broken["source_row"]["reporting_owner_count"]=value
                with self.subTest(value=value),self.assertRaisesRegex(ValueError,"RAW_EVENT_SEMANTICS"):
                    c.verify_ownership_event(broken,raw)
            broken=copy.deepcopy(promoted[0]);broken["source_row"]["transaction_price"]=0
            with self.assertRaisesRegex(ValueError,"RAW_EVENT_SEMANTICS"):c.verify_ownership_event(broken,raw)
            broken=copy.deepcopy(promoted);broken[0]["source_row"]["reporting_owner_count"]=True
            with self.assertRaisesRegex(ValueError,"CONFLICTING_ACCESSION_SECURITY_EVENTS"):
                c.consume(broken,receipt=receipt,raw_by_hash=raws,identities=SUBJECTS,output_root=root/"research",decision_at=NOW)
            self.assertEqual(before,manifest.read_bytes())

    def test_cli_explicit_amendment_parent_persists_and_replays(self):
        for form in ("3","4","5"):
            with self.subTest(form=form),tempfile.TemporaryDirectory() as td:
                root=Path(td);rawdir=root/"raw";rawdir.mkdir();identities=root/"identities.json";identities.write_bytes(SUBJECTS)
                original="0000000001-26-000001";amendment="0000000001-26-000002"
                _,raws=filing(form=form);raw=next(iter(raws.values()))
                (rawdir/(original.replace("-","")+"_fixture.xml")).write_bytes(raw)
                pit,_,_=checked_generation(root,pd.DataFrame([fixture_index(form=form)]),{original:raw})
                args=["sec-consumer","--pit-root",str(pit),"--raw-dir",str(rawdir),"--identities",str(identities),
                      "--accession",original,"--output-dir",str(root/"research"),"--decision-at",NOW]
                with patch.object(sys,"argv",args),patch.object(sys,"stdout",io.StringIO()):self.assertEqual(c.main(),0)
                _,raws=filing(amendment,form+"/A","2026-10-21","5");raw=next(iter(raws.values()))
                (rawdir/(amendment.replace("-","")+"_fixture.xml")).write_bytes(raw)
                checked_generation(root,pd.DataFrame([fixture_index(amendment,form+"/A")]),{amendment:raw})
                args[args.index("--accession")+1]=amendment
                linked=args+["--amendment-parent-accession",original]
                for _ in range(2):
                    with patch.object(sys,"argv",linked),patch.object(sys,"stdout",io.StringIO()):self.assertEqual(c.main(),0)
                state=c.readback(root/"research");self.assertEqual(len(state["requests"]),2)
                records=[json.loads(c.read_ref(root/"research",r["registry_ref"])) for r in state["requests"].values()]
                self.assertEqual(sum(r["request_kind"]=="FILING_CORRECTION_REASSESSMENT" for r in records),1)
                current=root/"research/control_plane/candidate_registry/filing_requests.json";before=current.read_bytes()
                if form=="4":
                    for parent in ("","malformed",amendment):
                        invalid=args+(["--amendment-parent-accession",parent] if parent else [])
                        with patch.object(sys,"argv",invalid),patch.object(sys,"stdout",io.StringIO()):self.assertEqual(c.main(),2)
                        self.assertEqual(before,current.read_bytes())
                    wrong=args+["--amendment-parent-accession","0000000001-26-000099"]
                    with patch.object(sys,"argv",wrong),self.assertRaisesRegex(ValueError,"AMENDMENT_REPLAY_LINEAGE_CONFLICT"):c.main()
                    self.assertEqual(before,current.read_bytes())
                    checked_generation(root,pd.DataFrame([fixture_index()]),{original:next(iter(filing()[1].values()))})
                    plain=linked.copy();plain[plain.index("--accession")+1]=original
                    with patch.object(sys,"argv",plain),patch.object(sys,"stdout",io.StringIO()):self.assertEqual(c.main(),2)
                    self.assertEqual(before,current.read_bytes())

    def test_amendment_keeps_original_and_replays_once(self):
        with tempfile.TemporaryDirectory() as td:
            self.consume(td)
            events, raws = filing("0000000001-26-000002", "4/A", "2026-10-21", "5")
            parents = {events[0]["accession"]: "0000000001-26-000001"}
            result = self.consume(td, events, raws, amendment_parents=parents)
            self.assertEqual(len(result["created_requests"]), 1)
            records = [json.loads(c.read_ref(Path(td), v["registry_ref"])) for v in c.readback(td)["requests"].values()]
            self.assertEqual(len(records), 2)
            self.assertEqual(sum(r["supersedes_request_id"] is not None for r in records), 1)
            self.assertEqual(sorted(r["request_kind"] for r in records),
                             ["CANDIDATE_RESEARCH_INTAKE", "FILING_CORRECTION_REASSESSMENT"])
            original = next(r for r in records if r["supersedes_request_id"] is None)
            correction = next(r for r in records if r["supersedes_request_id"] is not None)
            self.assertEqual(correction["supersedes_request_id"], original["request_id"])
            self.assertIsNone(correction["existing_thesis_ref"])
            for record, expected in ((original, "DISCOVERED"), (correction, "WATCH")):
                a2 = json.loads(c.read_ref(Path(td), record["a2_intake_ref"]))
                self.assertEqual({r["state"] for r in a2["input"]["events"]}, {expected})
                self.assertFalse(record["canonical_write_allowed"])
                self.assertFalse(record["orders_allowed"])
            before = (Path(td)/"control_plane/candidate_registry/filing_requests.json").read_bytes()
            replay = self.consume(td, events, raws, amendment_parents=parents)
            self.assertEqual(replay["created_requests"], [])
            self.assertEqual(replay["notification_intents_created"], 0)
            self.assertEqual(replay["notifications_sent"], 0)
            self.assertEqual(before, (Path(td)/"control_plane/candidate_registry/filing_requests.json").read_bytes())

    def test_plain_filing_cannot_claim_correction_parent(self):
        with tempfile.TemporaryDirectory() as td:
            first = self.consume(td)
            for accession in ("0000000001-26-000001", "0000000001-26-000003"):
                events, raws = filing(accession)
                with self.assertRaisesRegex(ValueError, "PARENT_FOR_NON_AMENDMENT"):
                    self.consume(td, events, raws, amendment_parents={accession: "0000000001-26-000001"})
            self.assertEqual(list(c.readback(td)["requests"]), first["created_requests"])

    def test_unlinked_or_wrong_original_amendment_refused(self):
        with tempfile.TemporaryDirectory() as td:
            self.consume(td)
            events, raws = filing("0000000001-26-000002", "4/A", "2026-10-19")
            for parents in ({}, {events[0]["accession"]: "0000000001-26-000001"}):
                with self.assertRaises(ValueError):
                    self.consume(td, events, raws, amendment_parents=parents)
            self.assertEqual(len(c.readback(td)["requests"]), 1)
            self.assertEqual(json.loads((Path(td)/"control_plane/candidate_registry/consumption_attempt.json").read_bytes())["status"], "FAILED_VALIDATION_OR_STORAGE")

    def test_receipt_membership_and_existing_subject_are_required(self):
        with tempfile.TemporaryDirectory() as td:
            events, raws = filing("0000000001-26-000009")
            with self.assertRaises(ValueError):
                self.consume(td, events, raws, receipt=source())
            wrong = c.put(Path(td), dict(schema="a3-candidate-packet-v1", asset_id="US:WRONG", issuer_id="CIK:0000000001"))
            with self.assertRaises(ValueError):
                self.consume(td, existing_theses={"US:TEST:COMMON":wrong})
            self.assertEqual(len(c.readback(td)["requests"]), 0)

    def test_embedded_source_manifest_hash_clock_and_scope_are_bound(self):
        receipt=source()
        member=next(iter(receipt["event_scope"].values()))
        original=dict(schema_version="sec-form4-merge-shards-v2",status="completed",generation_id=receipt["generation_id"],
            generated_at_utc=CHECK,last_successful_source_check=CHECK,latest_accepted_at=ACCEPTED,
            source_coverage=receipt["source_coverage"],current_eligible=True,current_source_transaction_rows=1,
            current_source_keys=[":".join(member[k] for k in ("issuer_cik10","accession","form_type"))],
            source_checks=[dict(cik10=member["issuer_cik10"],ticker="TEST",status="CHECKED_NEW_FILINGS",checked_at=CHECK)],
            source_filings=[dict(issuer_cik10=member["issuer_cik10"],ticker="TEST",accession=member["accession"],
                form_type=member["form_type"],accepted_at=ACCEPTED,available_at=ACCEPTED)])
        raw=c.encoded(original)
        receipt.update(original_manifest_utf8=raw.decode(),original_manifest_sha256=c.digest(raw))
        self.assertEqual(c.source_state(receipt,NOW),"CHECKED_NEW_OR_EXISTING")
        for key,value in (("original_manifest_sha256","0"*64),("generation_id","changed"),("latest_accepted_at",CHECK)):
            broken={**receipt,key:value}
            with self.assertRaises(ValueError):c.source_state(broken,NOW)

    def test_checked_typed_filings_do_not_require_legacy_signal(self):
        for form,kind in (("3","HOLDING"),("5","TRANSACTION"),("4","HOLDING"),("4","DERIVATIVE")):
            with self.subTest(form=form,kind=kind),tempfile.TemporaryDirectory() as td:
                root=Path(td)
                _,raws=filing(form=form);raw=next(iter(raws.values()))
                if kind=="HOLDING":
                    raw=raw.replace(b"nonDerivativeTransaction",b"nonDerivativeHolding")
                elif kind=="DERIVATIVE":
                    raw=raw.replace(b"nonDerivative",b"derivative")
                pit,_,manifest=checked_generation(root,pd.DataFrame([fixture_index(form=form)]),
                    {"0000000001-26-000001":raw})
                self.assertEqual(manifest["status"],"completed")
                self.assertEqual(manifest["signal_rows"],0)
                self.assertEqual(manifest["legacy_signal_status"],"NO_LEGACY_SIGNALS")
                receipt,frame=c.verify_ownership_generation(pit,decision_at=NOW)
                events=build_ownership_research_events(frame)
                result=c.consume(events,receipt=receipt,raw_by_hash={c.digest(raw):raw},identities=SUBJECTS,
                    output_root=root/"research",decision_at=NOW)
                self.assertEqual(len(result["created_requests"]),1)
                self.assertEqual(len(c.readback(root/"research")["requests"]),1)

    def test_successful_empty_check_has_successful_cli_result(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            checks=[dict(ticker="TEST",cik10="0000000001",status="CHECKED_NO_NEW_FILINGS",checked_at=CHECK,payload_sha256="a"*64)]
            pit,_,manifest=checked_generation(root,pd.DataFrame([fixture_index()]).iloc[:0],{},checks)
            self.assertEqual(manifest["status"],"completed")
            receipt,frame=c.verify_ownership_generation(pit,decision_at=NOW)
            self.assertTrue(frame.empty)
            self.assertEqual(receipt["status"],"CHECKED_NO_NEW")
            with patch.object(sys,"argv",["consumer","--pit-root",str(pit),"--raw-dir",str(root/"unused"),
                    "--identities",str(root/"unused.json"),"--accession","none","--decision-at",NOW,
                    "--output-dir",str(root/"research")]):
                self.assertEqual(c.main(),0)
            attempt=json.loads((root/"research/control_plane/candidate_registry/consumption_attempt.json").read_bytes())
            self.assertEqual(attempt["status"],"CHECKED_NO_NEW")
            self.assertTrue(attempt["current_eligible"])
            self.assertEqual(attempt["notification_intents_created"],0)
            self.assertEqual(c.readback(root/"research")["requests"],{})

    def test_stale_empty_cli_refuses_without_changing_committed_requests(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);store=root/"research"
            self.consume(store)
            manifest=store/"control_plane/candidate_registry/filing_requests.json"
            before=manifest.read_bytes()
            checks=[dict(ticker="TEST",cik10="0000000001",status="CHECKED_NO_NEW_FILINGS",
                         checked_at=CHECK,payload_sha256="a"*64)]
            pit,_,_=checked_generation(root,pd.DataFrame([fixture_index()]).iloc[:0],{},checks)
            stale_at=(c.bridge.stamp(CHECK)+timedelta(days=4)).isoformat()
            for decision,code,status,eligible in ((NOW,0,"CHECKED_NO_NEW",True),(stale_at,2,"STALE",False)):
                with self.subTest(status=status),patch.object(sys,"argv",["consumer","--pit-root",str(pit),
                        "--raw-dir",str(root/"unused"),"--identities",str(root/"unused.json"),
                        "--accession","none","--decision-at",decision,"--output-dir",str(store)]),\
                        patch.object(c,"actual_utc_now",return_value=decision),patch.object(sys,"stdout",io.StringIO()):
                    self.assertEqual(c.main(),code)
                attempt=json.loads((store/"control_plane/candidate_registry/consumption_attempt.json").read_bytes())
                self.assertEqual(attempt["status"],status)
                self.assertEqual(attempt["current_eligible"],eligible)
                self.assertEqual(attempt["created_requests"],[])
                self.assertEqual(attempt["notification_intents_created"],0)
                self.assertEqual(manifest.read_bytes(),before)

    def test_amendment_parent_requires_same_underlying_form(self):
        for original_form in ("3","4","5"):
            for amendment_form in ("3","4","5"):
                with self.subTest(original=original_form,amendment=amendment_form),tempfile.TemporaryDirectory() as td:
                    store=Path(td)
                    events,raws=filing(form=original_form)
                    first=self.consume(store,events,raws)
                    manifest=store/"control_plane/candidate_registry/filing_requests.json"
                    before=manifest.read_bytes()
                    accession="0000000001-26-000002"
                    events,raws=filing(accession,amendment_form+"/A","2026-10-21",price="5")
                    parents={accession:"0000000001-26-000001"}
                    if original_form!=amendment_form:
                        with self.assertRaisesRegex(ValueError,"AMENDMENT_ORIGINAL_FORM_CONFLICT"):
                            self.consume(store,events,raws,amendment_parents=parents)
                        self.assertEqual(manifest.read_bytes(),before)
                        attempt=json.loads((store/"control_plane/candidate_registry/consumption_attempt.json").read_bytes())
                        self.assertFalse(attempt["current_eligible"])
                        self.assertEqual(attempt["status"],"FAILED_VALIDATION_OR_STORAGE")
                        self.assertEqual(len(c.readback(store)["requests"]),1)
                    else:
                        second=self.consume(store,events,raws,amendment_parents=parents)
                        state=c.readback(store)
                        record=json.loads(c.read_ref(store,state["requests"][second["created_requests"][0]]["registry_ref"]))
                        self.assertEqual(record["supersedes_request_id"],first["created_requests"][0])
                        self.assertEqual(record["request_kind"],"FILING_CORRECTION_REASSESSMENT")
                        committed=manifest.read_bytes()
                        replay=self.consume(store,events,raws)
                        self.assertEqual(replay["created_requests"],[])
                        self.assertEqual(replay["replayed_requests"],second["created_requests"])
                        self.assertEqual(manifest.read_bytes(),committed)

    def test_quarterly_source_summary_survives_both_persistence_channels(self):
        from tools import run_sec_13f_parser as parser
        fixture=runpy.run_path(str(ROOT/"tests/sec_13f_position_event_builder_smoke.py"))["standalone_fixture"]
        workflow=(ROOT/".github/workflows/sec_13f_quarterly_refresh.yml").read_text(encoding="utf-8")
        durable=workflow.split("- name: Persist collected 13F source independently of weighted analysis",1)[1].split("\n      - name:",1)[0]
        artifact=workflow.split("- name: Upload SEC 13F artifact",1)[1].split("\n      - name:",1)[0]
        patterns={"durable_raw_diagnostic":shlex.split(re.search(r"for f in (.+); do",durable).group(1)),
                  "actions_artifact":[line.strip() for line in artifact.split("path: |",1)[1].splitlines() if line.strip()]}
        summary=Path("data_pit/sec/13f_latest/sec_filings_index_summary.json")
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);options=fixture(root/"source");runner=root/"runner"
            for src,dest in ((options["filings_index"].parent,runner/"data_pit/sec/13f_latest"),
                             (options["holdings"].parent,runner/"data_pit/sec"),
                             (options["raw_dir"],runner/"data_raw/sec")):
                shutil.copytree(src,dest,dirs_exist_ok=True)
            shutil.copy2(options["cusip_map"],runner/"data_pit/sec/cusip_ticker_map.csv")
            for channel,globs in patterns.items():
                with self.subTest(channel=channel):
                    restored=root/channel
                    # Original XML/submissions/checkpoints are a separate existing raw-cache restore.
                    shutil.copytree(runner/"data_raw/sec",restored/"data_raw/sec")
                    for pattern in globs:
                        for path in runner.glob(pattern):
                            for item in path.rglob("*") if path.is_dir() else [path]:
                                if item.is_file():
                                    target=restored/item.relative_to(runner)
                                    target.parent.mkdir(parents=True,exist_ok=True)
                                    shutil.copy2(item,target)
                    self.assertTrue((restored/summary).is_file())
                    self.assertEqual((restored/summary).read_bytes(),(runner/summary).read_bytes())
                    def load():
                        return parser.load_disclosure_source_inputs(
                            holdings=restored/"data_pit/sec/institutional_13f_holdings.parquet",
                            filings_index=restored/"data_pit/sec/13f_latest/sec_filings_index.parquet",
                            raw_dir=restored/"data_raw/sec",cusip_map=restored/"data_pit/sec/cusip_ticker_map.csv",
                            manager_ciks=options["manager_ciks"])
                    verified=parser.verify_disclosure_source_inputs(load(),manager_ciks=options["manager_ciks"],
                        decision_at=options["decision_at"])
                    self.assertTrue(verified)
                    (restored/summary).unlink()
                    with self.assertRaises(FileNotFoundError):load()

    def test_merged_reparse_replaces_whole_accession_including_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            _,raws=filing();one=next(iter(raws.values()))
            start=one.index(b"<nonDerivativeTransaction>");end=one.index(b"</nonDerivativeTransaction>")+len(b"</nonDerivativeTransaction>")
            two=one.replace(b"</nonDerivativeTable>",one[start:end]+b"</nonDerivativeTable>")
            acc="0000000001-26-000001";other="0000000001-26-000009"
            checked_generation(root,pd.DataFrame([fixture_index(),fixture_index(other)]),{acc:two,other:one})
            pit,_,manifest=checked_generation(root,pd.DataFrame([fixture_index()]),{acc:one})
            self.assertEqual(manifest["current_source_transaction_rows"],1)
            receipt,current=c.verify_ownership_generation(pit,decision_at=NOW)
            self.assertEqual(len(current),1)
            self.assertEqual(len(pd.read_parquet(pit/"form4_transactions.parquet")),2)
            empty=one[:start]+one[end:]
            pit,_,manifest=checked_generation(root,pd.DataFrame([fixture_index()]),{acc:empty})
            self.assertEqual(manifest["current_source_transaction_rows"],0)
            self.assertEqual(manifest["replaced_accession_keys"],["0000000001:"+acc+":4"])
            receipt,current=c.verify_ownership_generation(pit,decision_at=NOW)
            self.assertEqual(receipt["status"],"CHECKED_NO_NEW")
            self.assertTrue(current.empty)
            retained=pd.read_parquet(pit/"form4_transactions.parquet")
            self.assertEqual(retained["accession_number"].tolist(),[other])

    def test_inactive_shards_cannot_resurrect_shorter_or_empty_replacements(self):
        for empty_result in (False,True):
            with self.subTest(empty=empty_result),tempfile.TemporaryDirectory() as td:
                root=Path(td);_,raws=filing();one=next(iter(raws.values()))
                start=one.index(b"<nonDerivativeTransaction>");end=one.index(b"</nonDerivativeTransaction>")+len(b"</nonDerivativeTransaction>")
                two=one.replace(b"</nonDerivativeTable>",one[start:end]+b"</nonDerivativeTable>")
                acc="0000000001-26-000001";other="0000000001-26-000009"
                pit,shard,_=checked_generation(root,pd.DataFrame([fixture_index()]),{acc:two})
                shutil.copytree(shard,pit/"shards/old-cache")
                replacement=one[:start]+one[end:] if empty_result else one
                checked_generation(root,pd.DataFrame([fixture_index()]),{acc:replacement})
                for _ in range(2):
                    # Existing collector CLI invalidates these pointers first.
                    checking=c.encoded(dict(status="CHECKING",current_eligible=False))
                    (pit/"sec_form4_merge_manifest.json").write_bytes(checking)
                    (root/"signals/ownership_signal_summary.json").write_bytes(checking)
                    pit,_,manifest=checked_generation(root,pd.DataFrame([fixture_index(other)]),{other:one})
                    rows=pd.read_parquet(pit/"form4_transactions.parquet")
                    self.assertEqual(int(rows["accession_number"].eq(acc).sum()),0 if empty_result else 1)
                    self.assertIn("0000000001:"+acc+":4",manifest["replacement_scope"]["protected_accession_keys"])
                    receipt,current=c.verify_ownership_generation(pit,decision_at=NOW)
                    self.assertEqual(len(current),1)
                # An explicitly selected proved new parse may replace the marker.
                pit,_,_=checked_generation(root,pd.DataFrame([fixture_index()]),{acc:two})
                self.assertEqual(int(pd.read_parquet(pit/"form4_transactions.parquet")["accession_number"].eq(acc).sum()),2)

    def test_corrected_index_clocks_survive_inactive_shards_and_later_batch(self):
        for empty_result in (False,True):
            with self.subTest(empty=empty_result),tempfile.TemporaryDirectory() as td:
                root=Path(td);_,raws=filing();raw=next(iter(raws.values()))
                acc="0000000001-26-000001";other="0000000001-26-000009"
                pit,shard,_=checked_generation(root,pd.DataFrame([fixture_index()]),{acc:raw})
                shutil.copytree(shard,pit/"shards/old-cache")
                corrected=fixture_index();corrected.update(accepted_at="2026-10-21T21:00:00Z",available_from="2026-10-21T22:00:00Z")
                start=raw.index(b"<nonDerivativeTransaction>");end=raw.index(b"</nonDerivativeTransaction>")+len(b"</nonDerivativeTransaction>")
                replacement=raw[:start]+raw[end:] if empty_result else raw
                pit,_,manifest=checked_generation(root,pd.DataFrame([corrected]),{acc:replacement})
                for stage in range(3):
                    index=pd.read_parquet(pit/"sec_filings_index.parquet")
                    original=index[index["accession_number"].eq(acc)].iloc[0]
                    self.assertEqual((original["accepted_at"],original["available_from"]),
                                     (corrected["accepted_at"],corrected["available_from"]))
                    rows=pd.read_parquet(pit/"form4_transactions.parquet")
                    for _,row in rows[rows["accession_number"].eq(acc)].iterrows():
                        self.assertEqual((row["accepted_at"],row["available_from"]),
                                         (corrected["accepted_at"],corrected["available_from"]))
                    c.verify_ownership_generation(pit,decision_at=NOW)
                    checking=c.encoded(dict(status="CHECKING",current_eligible=False))
                    (pit/"sec_form4_merge_manifest.json").write_bytes(checking)
                    (root/"signals/ownership_signal_summary.json").write_bytes(checking)
                    if stage<2:pit,_,manifest=checked_generation(root,pd.DataFrame([fixture_index(other)]),{other:raw})

    def test_missing_or_corrupt_prior_replacement_proof_revokes_current_success(self):
        from tools import run_sec_form4_merge_shards as merge
        for change in ("missing","hash","root","table_missing","checking_missing","checking_root"):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as td:
                root=Path(td);_,raws=filing();raw=next(iter(raws.values()))
                pit,shard,_=checked_generation(root,pd.DataFrame([fixture_index()]),{"0000000001-26-000001":raw})
                path=pit/"sec_form4_merge_manifest.json";manifest=json.loads(path.read_bytes())
                if change=="missing":manifest.pop("replacement_scope");manifest.pop("replacement_scope_sha256")
                elif change=="hash":manifest["replacement_scope"]["protected_accession_keys"]=["wrong"]
                elif change in {"root","checking_root"}:
                    rows=pd.read_parquet(pit/"form4_transactions.parquet");rows["transaction_shares"]=999
                    rows.to_parquet(pit/"form4_transactions.parquet",index=False)
                else:
                    summary_path=pit/"form4_transactions_summary.json";summary=json.loads(summary_path.read_bytes())
                    summary.pop("replacement_scope");summary.pop("replacement_scope_sha256")
                    summary_path.write_bytes(c.encoded(summary))
                if change.startswith("checking"):
                    manifest=dict(status="CHECKING",current_eligible=False)
                path.write_bytes(c.encoded(manifest))
                before=(pit/"form4_transactions.parquet").read_bytes()
                args=argparse.Namespace(pit_root=str(pit),output_dir=str(root/"signals"),as_of_dates_csv="",
                    as_of_date_column="date",window_days=90,signal_mode="current",decision_at=NOW,
                    source_check_summary=str(shard/"sec_filings_index_summary.json"))
                with self.assertRaisesRegex(ValueError,"PREVIOUS_.*(PROOF|CONFLICT)"):merge.run(args)
                self.assertEqual(before,(pit/"form4_transactions.parquet").read_bytes())
                self.assertFalse(json.loads(path.read_bytes())["current_eligible"])
                self.assertFalse(json.loads((root/"signals/ownership_signal_summary.json").read_bytes())["current_eligible"])

    def test_unproved_reparse_does_not_delete_prior_lake_rows(self):
        from tools import run_sec_form4_merge_shards as merge
        for change,reason in (("count","REPARSE_REPLACEMENT_ROW_COUNT"),("key","REPARSE_REPLACEMENT_OUTSIDE_INDEX")):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as td:
                root=Path(td);_,raws=filing();raw=next(iter(raws.values()))
                pit,shard,_=checked_generation(root,pd.DataFrame([fixture_index()]),{"0000000001-26-000001":raw})
                before=(pit/"form4_transactions.parquet").read_bytes()
                path=shard/"form4_transactions_summary.json";receipt=json.loads(path.read_bytes())
                key=next(iter(receipt["completed"]))
                if change=="count":receipt["completed"][key]["row_count"]=2
                else:
                    wrong="0000000009:0000000009-26-000009:4"
                    receipt["completed"][wrong]=dict(status="PARSED_EMPTY",row_count=0)
                    receipt["attempted_keys"].append(wrong)
                path.write_bytes(c.encoded(receipt))
                args=argparse.Namespace(pit_root=str(pit),output_dir=str(root/"signals"),as_of_dates_csv="",
                    as_of_date_column="date",window_days=90,signal_mode="current",decision_at=NOW,
                    source_check_summary=str(shard/"sec_filings_index_summary.json"))
                with self.assertRaisesRegex(ValueError,reason):merge.run(args)
                self.assertEqual(before,(pit/"form4_transactions.parquet").read_bytes())
                self.assertFalse(json.loads((pit/"sec_form4_merge_manifest.json").read_bytes())["current_eligible"])
                self.assertFalse(json.loads((root/"signals/ownership_signal_summary.json").read_bytes())["current_eligible"])

    def test_per_issuer_acceptance_can_exceed_conservative_batch_minimum(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            _,raws=filing();raw=next(iter(raws.values()))
            index=pd.DataFrame([fixture_index(),fixture_index("0000000002-26-000002")])
            index.loc[0,["accepted_at","available_from"]]="2026-10-22T08:59:00Z"
            index.loc[1,["accepted_at","available_from"]]="2026-10-22T09:01:00Z"
            index.loc[1,["cik10","ticker"]]=["0000000002","OTHER"]
            checks=[dict(cik10="0000000001",ticker="TEST",checked_at=CHECK,status="CHECKED_NEW_FILINGS",payload_sha256="a"*64),
                    dict(cik10="0000000002",ticker="OTHER",checked_at="2026-10-22T09:02:00Z",status="CHECKED_NEW_FILINGS",payload_sha256="b"*64)]
            pit,_,manifest=checked_generation(root,index,{"0000000001-26-000001":raw,
                "0000000002-26-000002":raw.replace(b"<issuerCik>1",b"<issuerCik>2").replace(b">TEST<",b">OTHER<")},checks)
            self.assertEqual(manifest["status"],"completed")
            receipt,current=c.verify_ownership_generation(pit,decision_at=NOW)
            self.assertGreater(pd.Timestamp(receipt["latest_accepted_at"]),pd.Timestamp(receipt["last_successful_source_check"]))
            self.assertEqual(len(current),2)
            self.assertEqual(c.source_state(receipt,NOW),"CHECKED_NEW_OR_EXISTING")
            for broken,reason in (("missing","SOURCE_ISSUER_PROOF_REQUIRED"),("wrong","SOURCE_CORRESPONDING_ISSUER_CHECK_REQUIRED"),
                                  ("early","SOURCE_ISSUER_ACCEPTANCE_ORDER"),("event","SOURCE_EVENT_CLOCK_BINDING")):
                changed=copy.deepcopy(manifest);bad=copy.deepcopy(receipt)
                if broken=="missing":changed.pop("source_checks");changed.pop("source_filings")
                elif broken=="wrong":changed["source_checks"][1]["cik10"]="0000000003"
                elif broken=="early":changed["source_checks"][1]["checked_at"]=CHECK
                else:next(v for v in bad["event_scope"].values() if v["ticker"]=="OTHER")["accepted_at"]=CHECK
                blob=c.encoded(changed);bad.update(original_manifest_utf8=blob.decode(),original_manifest_sha256=c.digest(blob))
                with self.subTest(case=broken),self.assertRaisesRegex(ValueError,reason):c.source_state(bad,NOW)
            stale_decision="2026-10-23T21:00:00Z"
            self.assertEqual(c.source_state(receipt,stale_decision),"STALE")

    def test_unavailable_delayed_filing_does_not_block_other_checked_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);_,raws=filing();raw=next(iter(raws.values()))
            rows=[fixture_index(),fixture_index("0000000001-26-000009")]
            rows[1]["available_from"]="2026-10-24T09:00:00Z"
            pit,_,manifest=checked_generation(root,pd.DataFrame(rows),
                {"0000000001-26-000001":raw,"0000000001-26-000009":raw})
            self.assertTrue(manifest["current_eligible"])
            receipt,frame=c.verify_ownership_generation(pit,decision_at=NOW)
            self.assertEqual(len(frame),1)
            self.assertEqual(receipt["status"],"CHECKED_NEW_OR_EXISTING")

    def test_old_manifest_retains_history_but_cannot_authorize_new_intake(self):
        receipt=source();member=next(iter(receipt["event_scope"].values()))
        old=dict(schema_version="sec-form4-merge-shards-v2",status="completed",generation_id=receipt["generation_id"],
            generated_at_utc=CHECK,last_successful_source_check=CHECK,latest_accepted_at=ACCEPTED,
            source_coverage=receipt["source_coverage"],current_eligible=True,current_source_transaction_rows=1,
            current_source_keys=[":".join(member[k] for k in ("issuer_cik10","accession","form_type"))])
        raw=c.encoded(old);receipt.update(original_manifest_utf8=raw.decode(),original_manifest_sha256=c.digest(raw))
        with self.assertRaisesRegex(ValueError,"SOURCE_ISSUER_PROOF_REQUIRED"):c.source_state(receipt,NOW)
        self.assertEqual(c.source_state(receipt,NOW,historical_readback=True),"CHECKED_NEW_OR_EXISTING")
        self.assertEqual(c.encoded(old),raw)

    def test_existing_registry_research_gets_reassessment(self):
        with tempfile.TemporaryDirectory() as td:
            first = self.consume(td)
            state = c.readback(td)
            prior = state["requests"][first["created_requests"][0]]["registry_ref"]
            events, raws = filing("0000000001-26-000003",price="2")
            second = self.consume(td, events, raws, existing_theses={"US:TEST:COMMON":prior})
            record = json.loads(c.read_ref(Path(td), c.readback(td)["requests"][second["created_requests"][0]]["registry_ref"]))
            self.assertEqual(record["request_kind"], "THESIS_REASSESSMENT")

    def test_standalone_null_report_and_clock_bound_resume(self):
        from tools import run_sec_ownership_signals as signals
        from tools import run_sec_form4_parser as parser
        report = signals.render_report({}, pd.DataFrame([dict(ticker="TEST",insider_buy_value=None)]))
        self.assertIn("UNKNOWN", report)
        events, raws = filing()
        index = pd.DataFrame([dict(cik10="0000000001",ticker="TEST",accession_number=events[0]["accession"],
            form_type="4",accepted_at=ACCEPTED,available_from=ACCEPTED,primary_document="fixture.xml")])
        with tempfile.TemporaryDirectory() as td, patch.object(parser,"cache_form4_document",return_value=(None,next(iter(raws.values())).decode())):
            first=parser.parse_form4_index(index,raw_dir=Path(td),sleep_s=0)
            done=first.attrs["parse_receipt"]["completed"]
            replay=parser.parse_form4_index(index,raw_dir=Path(td),sleep_s=0,completed=done)
            self.assertEqual(len(replay),0)
            changed=index.copy();changed["accepted_at"]="2026-10-21T21:00:00Z";changed["available_from"]="2026-10-21T21:00:00Z"
            refreshed=parser.parse_form4_index(changed,raw_dir=Path(td),sleep_s=0,completed=done)
            self.assertEqual(refreshed.iloc[0]["accepted_at"],"2026-10-21T21:00:00Z")

    def test_shorter_empty_reparse_removes_all_old_accession_rows(self):
        from tools.run_sec_form4_parser import replace_reparsed_rows
        events,_=filing();row=events[0]["source_row"]
        second={**row,"transaction_id":"nonDerivativeTransaction:1"}
        other={**row,"accession_number":"0000000001-26-000099"}
        prior=pd.DataFrame([row,second,other])
        receipt=dict(attempted_keys=["0000000001:"+row["accession_number"]+":4"])
        shorter=replace_reparsed_rows(prior,pd.DataFrame([row]),receipt)
        self.assertEqual(len(shorter),2)
        self.assertNotIn("nonDerivativeTransaction:1",shorter["transaction_id"].tolist())
        empty=replace_reparsed_rows(prior,pd.DataFrame(columns=prior.columns),receipt)
        self.assertEqual(empty["accession_number"].tolist(),[other["accession_number"]])

    def test_cached_xml_bytes_survive_native_newline_rules(self):
        from tools import run_sec_form4_parser as parser
        with tempfile.TemporaryDirectory() as td, patch.object(parser,"sec_get_text",return_value="<?xml version='1.0'?>\r\n<ownershipDocument/>\r\n"):
            path,text=parser.cache_form4_document(dict(cik10="1",accession_number="0000000001-26-000001",primary_document="x.xml"),Path(td))
            self.assertEqual(path.read_bytes(),text.encode())
            self.assertIn(b"\r\n",path.read_bytes())

    def test_stale_unavailable_and_checked_no_new_are_distinct(self):
        with tempfile.TemporaryDirectory() as td:
            self.consume(td)
            old = (Path(td)/"control_plane/candidate_registry/filing_requests.json").read_bytes()
            with patch.object(c,"actual_utc_now",return_value="2026-10-24T10:00:01Z"):
                stale = self.consume(td, decision_at="2026-10-24T10:00:00Z")
            self.assertEqual(stale["status"], "STALE")
            unavailable = self.consume(td, receipt=source("SOURCE_UNAVAILABLE"))
            self.assertEqual(unavailable["status"], "SOURCE_UNAVAILABLE")
            self.assertFalse(unavailable["current_eligible"])
            empty = self.consume(td, [], {}, receipt=source("CHECKED_NO_NEW"))
            self.assertEqual(empty["created_requests"], [])
            self.assertEqual(old, (Path(td)/"control_plane/candidate_registry/filing_requests.json").read_bytes())

    def test_generation_clock_is_actual_and_future_decision_refuses(self):
        with tempfile.TemporaryDirectory() as td, patch.object(c,"actual_utc_now",return_value="2026-10-22T10:00:01Z"):
            result=self.consume(td)
            self.assertEqual(result["generated_at"],"2026-10-22T10:00:01Z")
            self.assertEqual(result["decision_at"],NOW)
            with self.assertRaises(ValueError):self.consume(td,decision_at="2026-10-22T10:00:02Z")

    def test_cli_prerequisite_failure_revokes_previous_success(self):
        with tempfile.TemporaryDirectory() as td:
            self.consume(td)
            events,_=filing();frame=pd.DataFrame([events[0]["source_row"]])
            args=["sec-consumer","--pit-root",td,"--raw-dir",td,"--identities",str(Path(td)/"missing.json"),
                  "--accession",events[0]["accession"],"--output-dir",td,"--decision-at",NOW]
            for accession in (events[0]["accession"],"nonexistent-accession"):
                args[args.index("--accession")+1]=accession
                with patch.object(sys,"argv",args),patch.object(c,"verify_ownership_generation",return_value=(source(),frame)):
                    self.assertEqual(c.main(),2)
                attempt=json.loads((Path(td)/"control_plane/candidate_registry/consumption_attempt.json").read_bytes())
                self.assertFalse(attempt["current_eligible"])
                self.assertEqual(attempt["status"],"PREREQUISITE_FAILED")
                self.assertEqual(len(c.readback(td)["requests"]),1)

    def test_tamper_and_failed_commit_cannot_report_success(self):
        with tempfile.TemporaryDirectory() as td:
            self.consume(td)
            state = c.readback(td); request = next(iter(state["requests"].values()))
            artifact = Path(td)/request["raw_refs"][0]["path"]
            artifact.write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                self.consume(td)
            current = json.loads((Path(td)/"control_plane/candidate_registry/consumption_attempt.json").read_bytes())
            self.assertFalse(current["current_eligible"])

    def test_stable_document_scoped_ids_nulls_and_original_semantics(self):
        events, _ = filing()
        self.assertFalse(events[0]["is_open_market_buy"])
        self.assertIsNone(events[0]["source_row"]["transaction_value"])
        frame = pd.DataFrame([events[0]["source_row"]]); frame.index = [1000]
        frame["_source_file"] = "different-local-cache"
        self.assertEqual(build_ownership_research_events(frame), events)
        for form, meaning in (("3", "INITIAL_OWNERSHIP"), ("5", "DELAYED_OR_SUPPLEMENTAL_REPORT")):
            other, _ = filing(form=form)
            self.assertEqual(other[0]["event_type"], meaning)


class DisclosureTests(unittest.TestCase):
    def row(self, accession="a", period="2026-03-31", title="COM", shares=10, value=100, **kw):
        return dict(manager_cik="0000000002", source_accession=accession, report_period=period,
            cusip="123456789", title_of_class=title, share_type="SH", put_call="",
            investment_discretion="SOLE", other_manager="", shares=shares, market_value_usd=value,
            accepted_at={"a":"2026-05-01T00:00:00Z","b":"2026-08-01T00:00:00Z","c":"2026-08-02T00:00:00Z"}[accession],
            available_from="2026-08-03T00:00:00Z", ticker_mapped="TEST", **kw)

    def receipt(self, **kw):
        return dict(parsing_status="PARSED", document_sha256="a"*64, complete=True, mapping_complete=True, **kw)

    def test_classes_weight_only_and_reported_removal(self):
        rows=[self.row(),self.row(title="CLASS B", value=100),self.row("b","2026-06-30",value=300)]
        events=build_disclosure_research_events(pd.DataFrame(rows), {"a":self.receipt(),"b":self.receipt()})
        self.assertEqual(sum(e["event_type"]=="INITIAL_OBSERVATION" for e in events),2)
        self.assertIn("WEIGHT_CHANGE_ONLY",[e["event_type"] for e in events])
        self.assertIn("REPORTED_POSITION_REMOVAL",[e["event_type"] for e in events])
        self.assertTrue(all(not e["trade_inferred"] and not e["liquidation_confirmed"] for e in events))

    def test_additive_wrong_parent_never_complete_or_exit(self):
        rows=[self.row(),self.row("b","2026-03-31",title="CLASS B",form_type="13F-HR/A",amendment_type="NEW HOLDINGS")]
        receipts={"a":self.receipt(),"b":self.receipt(original_accession="wrong")}
        events=build_disclosure_research_events(pd.DataFrame(rows),receipts)
        self.assertTrue(all(not e["denominator_complete"] for e in events if e["accession"]=="b"))
        self.assertNotIn("REPORTED_POSITION_REMOVAL",[e["event_type"] for e in events])

    def test_unknown_amendment_cannot_remove_or_replace_complete_boundary(self):
        for amendment in (None, "", "UNKNOWN", "NEW HOLDING"):
            with self.subTest(amendment=amendment):
                rows=[self.row(),self.row(title="CLASS B"),
                      self.row("b",shares=999,form_type="13F-HR/A",amendment_type=amendment),
                      self.row("c",shares=11,form_type="13F-HR/A",amendment_type="RESTATEMENT")]
                receipts={"a":self.receipt(),"b":self.receipt(original_accession="a"),
                          "c":self.receipt(original_accession="a")}
                events=build_disclosure_research_events(pd.DataFrame(rows),receipts)
                unknown=[e for e in events if e["accession"]=="b"]
                self.assertTrue(unknown)
                self.assertTrue(all(e["event_type"]=="DISCLOSURE_REVIEW_INCOMPLETE" and not e["denominator_complete"] for e in unknown))
                later=[e for e in events if e["accession"]=="c"]
                self.assertEqual({e["prior_accession"] for e in later},{"a"})
                increased=next(e for e in later if e["event_type"]=="REPORTED_SHARES_INCREASE")
                self.assertEqual(increased["previous_shares"],10)
                self.assertEqual(increased["shares_delta"],1)

    def test_known_additive_and_restatement_have_distinct_snapshot_semantics(self):
        for amendment, expected in (("NEW HOLDINGS",False),("RESTATEMENT",True)):
            with self.subTest(amendment=amendment):
                rows=[self.row(),self.row("b",title="CLASS B",form_type="13F-HR/A",amendment_type=amendment)]
                events=build_disclosure_research_events(pd.DataFrame(rows),
                    {"a":self.receipt(),"b":self.receipt(original_accession="a")})
                changed=[e for e in events if e["accession"]=="b"]
                self.assertTrue(all(e["denominator_complete"] for e in changed))
                self.assertEqual(any(e["event_type"]=="REPORTED_POSITION_REMOVAL" for e in changed),expected)

    def test_successive_amendments_keep_root_and_latest_complete_comparison(self):
        for first,second in (("RESTATEMENT","RESTATEMENT"),("NEW HOLDINGS","NEW HOLDINGS"),("NEW HOLDINGS","RESTATEMENT")):
            with self.subTest(first=first,second=second):
                b=self.row("b",period="2026-03-31",title="CLASS B" if first=="NEW HOLDINGS" else "COM",shares=20,
                           form_type="13F-HR/A",amendment_type=first)
                title="CLASS C" if second=="NEW HOLDINGS" else "COM"
                c_row=self.row("c",period="2026-03-31",title=title,shares=30,form_type="13F-HR/A",amendment_type=second)
                following=self.row("c",period="2026-06-30",title=title,shares=25,form_type="13F-HR")
                following.update(source_accession="d",accepted_at="2026-08-04T00:00:00Z",available_from="2026-08-04T00:00:00Z")
                rows=[self.row(form_type="13F-HR"),b,c_row,following]
                receipts={"a":self.receipt(),"b":self.receipt(original_accession="a"),
                          "c":self.receipt(original_accession="a"),"d":self.receipt()}
                events=build_disclosure_research_events(pd.DataFrame(rows),receipts)
                corrected=[e for e in events if e["accession"]=="c"]
                self.assertTrue(corrected);self.assertTrue(all(e["denominator_complete"] for e in corrected))
                self.assertEqual({e["prior_accession"] for e in corrected},{"b"})
                self.assertEqual({e["original_accession"] for e in corrected},{"a"})
                later=next(e for e in events if e["accession"]=="d" and e["source_row"]["title_of_class"]==title)
                self.assertEqual((later["event_type"],later["previous_shares"],later["shares_delta"],later["prior_accession"]),
                                 ("REPORTED_SHARES_DECREASE",30,-5,"c"))
                receipts["c"]=self.receipt(original_accession="wrong")
                refused=build_disclosure_research_events(pd.DataFrame(rows),receipts)
                self.assertTrue(all(not e["denominator_complete"] for e in refused if e["accession"]=="c"))
                self.assertEqual({e["prior_accession"] for e in refused if e["accession"]=="d"},{"b"})

    def test_missing_mapping_and_ambiguous_rows_fail_closed(self):
        row=self.row()
        with self.assertRaises(ValueError):
            build_disclosure_research_events(pd.DataFrame([row,row]),{"a":self.receipt()})
        receipt=self.receipt();receipt["mapping_complete"]=False
        events=build_disclosure_research_events(pd.DataFrame([row]),{"a":receipt})
        self.assertEqual(events[0]["event_type"],"DISCLOSURE_REVIEW_INCOMPLETE")


if __name__ == "__main__":
    unittest.main()

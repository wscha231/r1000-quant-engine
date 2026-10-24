#!/usr/bin/env python3
"""Smoke checks for D1 13F position event builder."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pandas as pd

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_13f_position_event_builder import build_position_events, run  # noqa: E402


def holdings_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "manager_cik": "1067983",
                "manager_name": "Example Manager",
                "report_period": "2025-12-31",
                "filing_date": "2026-02-14",
                "accepted_at": "2026-02-14T18:00:00Z",
                "available_from": "2026-02-14T18:00:00Z",
                "cusip": "037833100",
                "issuer_name": "Apple Inc",
                "ticker_mapped": "AAPL",
                "shares": 100_000,
                "market_value_usd": 10_000_000,
            },
            {
                "manager_cik": "1067983",
                "manager_name": "Example Manager",
                "report_period": "2025-12-31",
                "filing_date": "2026-02-14",
                "accepted_at": "2026-02-14T18:00:00Z",
                "available_from": "2026-02-14T18:00:00Z",
                "cusip": "594918104",
                "issuer_name": "Microsoft Corp",
                "ticker_mapped": "MSFT",
                "shares": 50_000,
                "market_value_usd": 8_000_000,
            },
            {
                "manager_cik": "1067983",
                "manager_name": "Example Manager",
                "report_period": "2026-03-31",
                "filing_date": "2026-05-15",
                "accepted_at": "2026-05-15T18:00:00Z",
                "available_from": "2026-05-15T18:00:00Z",
                "cusip": "037833100",
                "issuer_name": "Apple Inc",
                "ticker_mapped": "AAPL",
                "shares": 125_000,
                "market_value_usd": 15_000_000,
            },
            {
                "manager_cik": "1067983",
                "manager_name": "Example Manager",
                "report_period": "2026-03-31",
                "filing_date": "2026-05-15",
                "accepted_at": "2026-05-15T18:00:00Z",
                "available_from": "2026-05-15T18:00:00Z",
                "cusip": "18452B209",
                "issuer_name": "CleanSpark Inc",
                "ticker_mapped": "CLSK",
                "shares": 200_000,
                "market_value_usd": 4_000_000,
            },
        ]
    )


def metadata_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ticker": "AAPL", "market_cap_for_audit": 3_000_000_000_000, "shares_float": 15_000_000_000, "dollar_volume_20d": 5_000_000_000, "sector": "Technology"},
            {"ticker": "MSFT", "market_cap_for_audit": 2_800_000_000_000, "shares_float": 7_400_000_000, "dollar_volume_20d": 4_000_000_000, "sector": "Technology"},
            {"ticker": "CLSK", "market_cap_for_audit": 1_500_000_000, "shares_float": 250_000_000, "dollar_volume_20d": 60_000_000, "sector": "Crypto"},
        ]
    )


def test_event_builder_detects_add_new_and_exit() -> None:
    events = build_position_events(holdings_fixture(), metadata_fixture())
    second = events[events["report_period"].eq("2026-03-31")].set_index("ticker")
    assert second.loc["AAPL", "event_type"] == "add"
    assert second.loc["CLSK", "event_type"] == "new"
    assert second.loc["MSFT", "event_type"] == "exit"
    assert int(second.loc["CLSK", "position_rank"]) == 2
    assert float(second.loc["CLSK", "manager_stake_to_float"]) > 0.0
    assert second.loc["CLSK", "market_cap_bucket"] == "small"
    assert bool(second.loc["CLSK", "research_only"]) is True
    assert bool(second.loc["CLSK", "production_activation_allowed"]) is False


def test_initial_period_is_not_false_new_signal() -> None:
    events = build_position_events(holdings_fixture(), metadata_fixture())
    first = events[events["report_period"].eq("2025-12-31")]
    assert set(first["event_type"]) == {"initial"}
    assert first["history_boundary"].astype(bool).all()


def test_manager_universe_metadata_is_attached() -> None:
    manager_universe = pd.DataFrame(
        [
            {
                "label": "ATREIDES",
                "manager_name": "Atreides Management LP",
                "cik10": "0001067983",
                "user_priority": 6,
                "external_performance_2y": 1.744,
                "allocation_tier": "growth_hedge",
            }
        ]
    )
    events = build_position_events(holdings_fixture(), metadata_fixture(), manager_universe)
    latest = events[events["report_period"].eq("2026-03-31")]
    assert float(latest["manager_rank"].max()) == 6.0
    assert float(latest["external_performance_2y"].max()) == 1.744
    assert set(latest["allocation_tier"]) == {"growth_hedge"}
    assert set(latest["manager_name"]) == {"Atreides Management LP"}


def test_restatement_replaces_base_snapshot_in_position_events() -> None:
    holdings = holdings_fixture().iloc[:2].copy()
    holdings["source_accession"] = "base"
    holdings["form_type"] = "13F-HR"
    holdings["amendment_type"] = ""
    restatement = holdings.iloc[[0]].copy()
    restatement["source_accession"] = "restatement"
    restatement["form_type"] = "13F-HR/A"
    restatement["amendment_type"] = "RESTATEMENT"
    restatement["accepted_at"] = "2026-02-17T18:00:00Z"
    restatement["available_from"] = "2026-02-17T18:00:00Z"
    events = build_position_events(pd.concat([holdings, restatement], ignore_index=True), metadata_fixture())
    base_events = events[events["available_from"].eq("2026-02-14T18:00:00Z")]
    assert set(base_events["ticker"]) == {"AAPL", "MSFT"}
    restatement_events = events[events["available_from"].eq("2026-02-17T18:00:00Z")]
    assert set(restatement_events["ticker"]) == {"MSFT"}
    assert restatement_events.iloc[0]["event_type"] == "exit"
    assert float(restatement_events.iloc[0]["previous_shares"]) == 50_000.0
    assert float(restatement_events.iloc[0]["shares"]) == 0.0


def test_late_restatement_keeps_earlier_disclosure_events() -> None:
    holdings = holdings_fixture().copy()
    holdings["source_accession"] = holdings["report_period"].map(
        {"2025-12-31": "prior-base", "2026-03-31": "current-base"}
    )
    holdings["form_type"] = "13F-HR"
    holdings["amendment_type"] = ""
    restatement = holdings[holdings["report_period"].eq("2025-12-31") & holdings["ticker_mapped"].eq("AAPL")].copy()
    restatement["source_accession"] = "late-prior-restatement"
    restatement["form_type"] = "13F-HR/A"
    restatement["amendment_type"] = "RESTATEMENT"
    restatement["accepted_at"] = "2026-06-01T18:00:00Z"
    restatement["available_from"] = "2026-06-01T18:00:00Z"
    added_then_exited = restatement.copy()
    added_then_exited["ticker_mapped"] = "NVDA"
    added_then_exited["cusip"] = "67066G104"
    added_then_exited["issuer_name"] = "NVIDIA Corp"
    restatement = pd.concat([restatement, added_then_exited], ignore_index=True)
    events = build_position_events(pd.concat([holdings, restatement], ignore_index=True), metadata_fixture())
    assert set(events[events["available_from"].eq("2026-02-14T18:00:00Z")]["ticker"]) == {"AAPL", "MSFT"}
    assert set(events[events["available_from"].eq("2026-05-15T18:00:00Z")]["ticker"]) == {"AAPL", "CLSK", "MSFT"}
    late = events[events["available_from"].eq("2026-06-01T18:00:00Z")]
    assert set(late["ticker"]) == {"NVDA"}
    assert late.iloc[0]["event_type"] == "exit"
    assert late.iloc[0]["report_period"] == "2026-03-31"
    assert float(late.iloc[0]["previous_shares"]) > 0.0
    assert float(late.iloc[0]["shares"]) == 0.0


def test_late_new_holdings_only_reconciles_to_newer_complete_snapshot() -> None:
    newer = holdings_fixture()[
        holdings_fixture()["report_period"].eq("2026-03-31")
        & holdings_fixture()["ticker_mapped"].eq("AAPL")
    ].copy()
    newer["source_accession"] = "newer-complete"
    newer["form_type"] = "13F-HR"
    newer["amendment_type"] = ""
    incremental = newer.copy()
    incremental["report_period"] = "2025-12-31"
    incremental["ticker_mapped"] = "NVDA"
    incremental["cusip"] = "67066G104"
    incremental["issuer_name"] = "NVIDIA Corp"
    incremental["source_accession"] = "late-new-holdings"
    incremental["form_type"] = "13F-HR/A"
    incremental["amendment_type"] = "NEW HOLDINGS"
    incremental["accepted_at"] = "2026-06-01T18:00:00Z"
    incremental["available_from"] = "2026-06-01T18:00:00Z"
    events = build_position_events(pd.concat([newer, incremental], ignore_index=True), metadata_fixture())
    late = events[events["available_from"].eq("2026-06-01T18:00:00Z")]
    assert set(late["ticker"]) == {"NVDA"}
    assert late.iloc[0]["event_type"] == "exit"
    assert late.iloc[0]["report_period"] == "2026-03-31"
    assert float(late.iloc[0]["previous_shares"]) > 0.0
    assert float(late.iloc[0]["shares"]) == 0.0


def test_cli_writes_pit_and_latest_outputs() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="13f_events_"))
    try:
        holdings = tmp / "holdings.parquet"
        metadata = tmp / "metadata.csv"
        pit = tmp / "data_pit" / "sec" / "13f_position_events.parquet"
        out = tmp / "outputs" / "13f_position_events"
        holdings_fixture().to_parquet(holdings, index=False)
        metadata_fixture().to_csv(metadata, index=False)
        payload = run(
            type(
                "Args",
                (),
                {
                    "holdings": str(holdings),
                    "metadata": str(metadata),
                    "pit_output": str(pit),
                    "output_dir": str(out),
                },
            )()
        )
        assert payload["status"] == "completed"
        assert payload["schema_version"] == "13f-position-events-v2"
        assert payload["available_from_before_accepted_at"] == 0
        assert pit.exists()
        assert (out / "latest.csv").exists()
        latest = pd.read_csv(out / "latest.csv")
        assert set(latest["event_type"]) == {"add", "new", "exit"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# Standalone Source/store fixtures are synthetic; no SEC or account calls.
import io
import json
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from tools import run_sec_13f_parser as source_parser
from tools import run_sec_submissions_collector as source_collector
from tools import run_13f_position_event_builder as disclosure_builder


def standalone_filings():
    return [
        dict(accession="0000000001-25-000001", period="2025-09-30",
             accepted="2025-11-14T15:00:00Z", form="13F-HR",
             positions=[("000000001", 100, 1000), ("000000002", 50, 500)]),
        dict(accession="0000000001-26-000001", period="2025-12-31",
             accepted="2026-02-13T15:00:00Z", form="13F-HR",
             positions=[("000000001", 150, 2000), ("000000003", 25, 500)]),
    ]


def standalone_fixture(root, filings=None, *, missing_map=False, crlf=False):
    """Existing real parser/checkpoints/serializers on offline synthetic XML."""
    filings = standalone_filings() if filings is None else filings
    root = Path(root)
    raw = root / "raw"
    index_dir, pit = root / "index", root / "pit"
    for path in (raw / "submissions", raw / "filings/13f", raw / "filings/13f_cover", index_dir, pit):
        path.mkdir(parents=True, exist_ok=True)
    mapping_path = root / "cusip_map.csv"
    pd.DataFrame([dict(cusip=c, ticker=t) for c, t in
        [("000000001", "AAA"), ("000000002", "BBB"), ("000000003", "CCC")]
        if not (missing_map and c == "000000003")]).to_csv(mapping_path, index=False)
    mapping = source_parser.read_cusip_map(mapping_path)
    recent = dict(form=[f["form"] for f in filings],
        accessionNumber=[f["accession"] for f in filings],
        acceptanceDateTime=[f["accepted"] for f in filings],
        filingDate=[f["accepted"][:10] for f in filings],
        reportDate=[f["period"] for f in filings], primaryDocument=["info.xml"] * len(filings))
    payload = dict(cik=1, name="SYNTHETIC MANAGER", filings=dict(recent=recent))
    source_collector.atomic_json(raw / "submissions/CIK0000000001.json", payload)
    index = source_collector.filings_from_submissions("FIXTURE", "0000000001", payload,
                                                      forms={"13F-HR", "13F-HR/A"})
    check = dict(ticker="FIXTURE", cik10="0000000001", status="CHECKED_NEW_FILINGS",
                 checked_at=datetime.now(timezone.utc).isoformat(),
                 payload_sha256=source_collector.content_hash(payload), new_accession_count=len(filings))
    source_collector.write_outputs(index, index_dir, collection_metadata=dict(source_checks=[check]))
    for filing in filings:
        parts = ["<informationTable>"]
        for cusip, shares, value in filing["positions"]:
            parts.append("<infoTable><nameOfIssuer>SYNTHETIC</nameOfIssuer><titleOfClass>COM</titleOfClass>"
                f"<cusip>{cusip}</cusip><value>{value}</value><shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt>"
                "<sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><investmentDiscretion>SOLE</investmentDiscretion>"
                "<votingAuthority><Sole>0</Sole><Shared>0</Shared><None>0</None></votingAuthority></infoTable>")
        parts.append("</informationTable>")
        text = "\n".join(parts)
        if crlf:
            text = text.replace("\n", "\r\n")
        name = source_parser.cache_name(filing["accession"], "info.xml")
        (raw / "filings/13f" / name).write_bytes(text.encode())
        if filing["form"] == "13F-HR/A":
            (raw / "filings/13f_cover" / name).write_text(
                "<edgarSubmission><headerData><submissionType>13F-HR/A</submissionType>"
                "<filerInfo><filer><credentials><cik>0000000001</cik></credentials></filer></filerInfo>"
                "<periodOfReport>" + filing["period"] + "</periodOfReport></headerData>"
                "<formData><isAmendment>true</isAmendment><amendmentType>" + filing["amendment"] +
                "</amendmentType></formData></edgarSubmission>", encoding="utf-8")
    with patch.object(source_parser, "sec_get_text", side_effect=AssertionError("network forbidden")),          patch.object(source_parser, "sec_get_json", side_effect=AssertionError("network forbidden")):
        frame = source_parser.parse_13f_index(index, raw_dir=raw, cusip_map=mapping, exact_cusip_only=True)
    source_parser.write_outputs(frame, pit)
    return dict(holdings=pit / "institutional_13f_holdings.parquet",
                filings_index=index_dir / "sec_filings_index.parquet", raw_dir=raw,
                cusip_map=mapping_path, manager_ciks=["0000000001"],
                decision_at=datetime.now(timezone.utc).isoformat())


class StandaloneDisclosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.options = standalone_fixture(self.root / "source")
        self.store = self.root / "store"

    def execute(self, **changes):
        return disclosure_builder.run_disclosure_generation(
            **{**self.options, "output_root": self.store, **changes})

    def read(self, historical=False):
        return disclosure_builder.read_disclosure_generation(self.store, historical=historical)

    def source_state(self, status, age_hours=0):
        path = self.options["filings_index"].parent / "sec_filings_index_summary.json"
        data = json.loads(path.read_text())
        check = data["source_checks"][0]
        check["status"] = status
        check["new_accession_count"] = 0 if status == "CHECKED_NO_NEW_FILINGS" else (1 if status == "CHECKED_NEW_FILINGS" else None)
        check["checked_at"] = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
        if not status.startswith("CHECKED_"):
            check["checked_at"] = None
        data["collection"]["source_checks"] = data["source_checks"]
        data["generated_at"] = datetime.now(timezone.utc).isoformat()
        good = status.startswith("CHECKED_")
        data["source_coverage"] = dict(requested=1, checked=int(good), checked_ciks=int(good), complete=good)
        data["status"] = "CHECKED" if good else "SOURCE_CHECK_INCOMPLETE"
        data["last_successful_source_check"] = check["checked_at"] if good else None
        path.write_text(json.dumps(data), encoding="utf-8")
        self.options["decision_at"] = datetime.now(timezone.utc).isoformat()

    def test_actual_serializers_store_and_same_input_replay(self):
        first = self.execute()
        self.assertEqual(first["status"], "COMPLETED_DISCLOSURE_STORAGE", first)
        manifest = self.read()
        self.assertEqual(manifest["event_count"], 5)
        self.assertEqual(first["new_events"], 5)
        pointer = (self.store / "current_generation.json").read_bytes()
        inventory = {p.name: p.read_bytes() for p in (self.store / "artifacts").iterdir()}
        second = self.execute()
        self.assertEqual(second["new_events"], 0)
        self.assertTrue(second["replayed"])
        self.assertEqual(second["new_notification_intents"], 0)
        self.assertEqual(second["notifications_sent"], 0)
        self.assertEqual((self.store / "current_generation.json").read_bytes(), pointer)
        self.assertEqual({p.name: p.read_bytes() for p in (self.store / "artifacts").iterdir()}, inventory)
        self.assertFalse(manifest["aggregate_analysis_admitted"])
        self.assertFalse(manifest["orders_allowed"])

    def test_incremental_full_prefix_matches_one_pass(self):
        self.options = standalone_fixture(self.root / "source", standalone_filings()[:1])
        self.assertEqual(self.execute()["new_events"], 2)
        self.options = standalone_fixture(self.root / "source")
        result = self.execute()
        self.assertEqual(result["status"], "COMPLETED_DISCLOSURE_STORAGE", result)
        self.assertEqual(result["new_events"], 3)
        incremental = self.read()
        other = self.root / "onepass"
        self.assertEqual(self.execute(output_root=other)["status"], "COMPLETED_DISCLOSURE_STORAGE")
        whole = disclosure_builder.read_disclosure_generation(other)
        self.assertEqual(incremental["events"], whole["events"])

    def test_missing_history_cannot_reset_comparison(self):
        self.assertEqual(self.execute()["status"], "COMPLETED_DISCLOSURE_STORAGE")
        self.options = standalone_fixture(self.root / "source", standalone_filings()[1:])
        result = self.execute()
        self.assertEqual(result["reason"], "13F_HISTORY_PREFIX_CONFLICT", result)
        self.assertEqual(result["new_events"], 0)
        with self.assertRaisesRegex(ValueError, "CURRENT_ATTEMPT"):
            self.read()
        self.assertEqual(self.read(True)["event_count"], 5)

    def test_changed_same_accession_raw_cannot_replace_history(self):
        self.execute()
        filings = standalone_filings()
        filings[0]["positions"] = [("000000001", 99, 990)]
        self.options = standalone_fixture(self.root / "source", filings)
        self.assertEqual(self.execute()["reason"], "13F_HISTORY_PREFIX_CONFLICT")

    def test_mapping_revision_is_not_SEC_amendment(self):
        self.execute()
        self.options = standalone_fixture(self.root / "source", missing_map=True)
        self.assertEqual(self.execute()["reason"], "13F_DERIVATION_CONTEXT_CONFLICT")

    def test_partial_mapping_is_review_only_without_false_removal(self):
        self.options = standalone_fixture(self.root / "source", missing_map=True)
        result = self.execute()
        self.assertEqual(result["status"], "COMPLETED_DISCLOSURE_STORAGE", result)
        manifest = self.read()
        events = [json.loads(disclosure_builder._disclosure_ref(self.store, e["ref"])) for e in manifest["events"]]
        self.assertFalse(manifest["filing_receipts"]["0000000001-26-000001"]["mapping_complete"])
        self.assertNotIn("REPORTED_POSITION_REMOVAL", {e["event_type"] for e in events})
        self.assertIn("DISCLOSURE_REVIEW_INCOMPLETE", {e["event_type"] for e in events})

    def test_restatement_empty_keeps_both_source_documents(self):
        filings = standalone_filings()
        filings.append(dict(accession="0000000001-26-000002", period="2025-12-31",
            accepted="2026-02-16T15:00:00Z", form="13F-HR/A", amendment="RESTATEMENT", positions=[]))
        self.options = standalone_fixture(self.root / "source", filings)
        result = self.execute()
        self.assertEqual(result["status"], "COMPLETED_DISCLOSURE_STORAGE", result)
        m = self.read()
        changed = [json.loads(disclosure_builder._disclosure_ref(self.store, e["ref"])) for e in m["events"]]
        removed = [e for e in changed if e["accession"] == filings[-1]["accession"]]
        self.assertEqual(len(removed), 2)
        self.assertTrue(all(e["event_type"] == "REPORTED_POSITION_REMOVAL" for e in removed))
        for event in removed:
            self.assertEqual(event["source_row_accession"], filings[1]["accession"])
            self.assertTrue({"CURRENT_REPORT", "PRIOR_CONSTITUENT"}.issubset(
                {r["role"] for r in event["evidence_refs"]}))
            self.assertFalse(event["liquidation_confirmed"])

    def test_new_holdings_then_restatement_retains_root_and_context(self):
        filings = standalone_filings()
        filings.append(dict(accession="0000000001-26-000002", period="2025-12-31",
            accepted="2026-02-16T15:00:00Z", form="13F-HR/A", amendment="NEW HOLDINGS",
            positions=[("000000002", 10, 300)]))
        filings.append(dict(accession="0000000001-26-000003", period="2025-12-31",
            accepted="2026-02-17T15:00:00Z", form="13F-HR/A", amendment="RESTATEMENT",
            positions=[("000000001", 155, 2200)]))
        self.options = standalone_fixture(self.root / "source", filings)
        result = self.execute()
        self.assertEqual(result["status"], "COMPLETED_DISCLOSURE_STORAGE", result)
        manifest = self.read()
        events = [json.loads(disclosure_builder._disclosure_ref(self.store, e["ref"])) for e in manifest["events"]]
        last = [e for e in events if e["accession"] == filings[-1]["accession"]]
        self.assertTrue(last)
        self.assertTrue(all(e["original_accession"] == filings[1]["accession"] for e in last))
        self.assertTrue(all(e["prior_accession"] == filings[2]["accession"] for e in last))

    def test_empty_original_is_a_successful_zero_event_generation(self):
        filings = standalone_filings()[:1]
        filings[0]["positions"] = []
        self.options = standalone_fixture(self.root / "source", filings)
        result = self.execute()
        self.assertEqual(result["status"], "COMPLETED_DISCLOSURE_STORAGE", result)
        self.assertEqual(self.read()["event_count"], 0)

    def test_stale_invalidates_previous_current_success(self):
        self.execute()
        self.source_state("CHECKED_NO_NEW_FILINGS", age_hours=37)
        result = self.execute()
        self.assertEqual(result["reason"], "STALE", result)
        self.assertEqual(result["new_events"], 0)
        with self.assertRaisesRegex(ValueError, "CURRENT_ATTEMPT"):
            self.read()
        self.assertEqual(self.read(True)["event_count"], 5)

    def test_unavailable_and_cached_are_distinct_from_no_new(self):
        for status, reason in [("SOURCE_UNAVAILABLE", "SOURCE_UNAVAILABLE"),
                               ("CACHED_NOT_CHECKED", "13F_CACHED_OR_UNCHECKED")]:
            with self.subTest(status=status):
                self.source_state(status)
                self.assertEqual(self.execute()["reason"], reason)
        self.options = standalone_fixture(self.root / "source")
        self.source_state("CHECKED_NO_NEW_FILINGS")
        self.options["decision_at"] = datetime.now(timezone.utc).isoformat()
        result = self.execute()
        self.assertEqual(result["status"], "COMPLETED_DISCLOSURE_STORAGE", result)

    def test_crlf_physical_original_is_not_parser_text_hash(self):
        self.options = standalone_fixture(self.root / "source", crlf=True)
        result = self.execute()
        self.assertEqual(result["status"], "COMPLETED_DISCLOSURE_STORAGE", result)
        receipt = self.read()["filing_receipts"]["0000000001-25-000001"]
        self.assertNotEqual(receipt["document_sha256"], receipt["parser_text_sha256"])

    def test_resealed_rows_do_not_substitute_for_original_XML(self):
        pit = self.options["holdings"].parent
        frame = pd.read_parquet(pit / "institutional_13f_holdings.parquet")
        frame.loc[0, "shares"] = 9999
        frame.to_parquet(pit / "institutional_13f_holdings.parquet", index=False)
        frame.to_csv(pit / "institutional_13f_holdings.csv", index=False)
        path = pit / "institutional_13f_holdings_summary.json"
        summary = json.loads(path.read_text())
        summary["output_sha256"] = {k: source_collector.file_hash(pit / ("institutional_13f_holdings." + k))
                                     for k in ("csv", "parquet")}
        path.write_text(json.dumps(summary))
        self.assertEqual(self.execute()["reason"], "13F_RAW_PARSE_SEMANTICS")

    def test_current_raw_corruption_refuses_even_with_old_good_checkpoint(self):
        self.execute()
        raw = self.options["raw_dir"] / "filings/13f/000000000126000001_info.xml"
        raw.write_text(raw.read_text().replace("<sshPrnamt>150", "<sshPrnamt>149"))
        self.assertEqual(self.execute()["reason"], "13F_RAW_PARSE_SEMANTICS")

    def test_current_manifest_metadata_is_recomputed_on_readback(self):
        self.execute()
        pointer_path = self.store / "current_generation.json"
        pointer = json.loads(pointer_path.read_text())
        manifest = self.read()
        manifest["filing_receipts"]["0000000001-26-000001"]["mapping_complete"] = False
        pointer["manifest_ref"] = disclosure_builder._disclosure_put(
            self.store, disclosure_builder._disclosure_codec(manifest))
        pointer_path.write_text(json.dumps(pointer))
        with self.assertRaisesRegex(ValueError, "STORED_SOURCE_METADATA"):
            self.read()

    def test_artifact_tamper_and_writer_lock_preserve_current_bytes(self):
        self.execute()
        before = (self.store / "attempt.json").read_bytes()
        lock = self.store / ".writer.lock"
        lock.write_text("other writer")
        with self.assertRaises(FileExistsError):
            self.execute()
        self.assertEqual((self.store / "attempt.json").read_bytes(), before)
        lock.unlink()
        event = self.read()["events"][0]
        (self.store / event["ref"]["path"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "STORE_HASH"):
            self.read()

    def test_interrupted_generation_never_becomes_current(self):
        with patch.object(disclosure_builder, "_verify_disclosure_pending", side_effect=RuntimeError("controlled crash")):
            with self.assertRaisesRegex(RuntimeError, "controlled crash"):
                self.execute()
        self.assertFalse((self.store / "current_generation.json").exists())
        self.assertEqual(json.loads((self.store / "attempt.json").read_text())["status"], "BUILDING")
        self.assertEqual(self.execute()["status"], "COMPLETED_DISCLOSURE_STORAGE")
        self.read()

    def test_source_output_overlap_is_refused_without_writes(self):
        before = {p: p.read_bytes() for p in self.options["holdings"].parent.iterdir()}
        with self.assertRaisesRegex(ValueError, "SOURCE_OUTPUT_OVERLAP"):
            self.execute(output_root=self.options["holdings"].parent / "store")
        self.assertEqual({p: p.read_bytes() for p in self.options["holdings"].parent.iterdir()}, before)

    def test_native_CLI_routes_to_typed_store_and_reports_refusal(self):
        import subprocess
        command = [sys.executable, "-B"] + (["-O"] if sys.flags.optimize else []) + [
            str(ROOT / "tools/run_13f_position_event_builder.py"), "--disclosure-research",
            "--holdings", str(self.options["holdings"]), "--filings-index", str(self.options["filings_index"]),
            "--raw-dir", str(self.options["raw_dir"]), "--cusip-map", str(self.options["cusip_map"]),
            "--manager-ciks", "0000000001", "--decision-at", self.options["decision_at"],
            "--disclosure-output-dir", str(self.store)]
        child = subprocess.run(command, capture_output=True, text=True, timeout=90)
        self.assertEqual(child.returncode, 0, child.stderr + child.stdout)
        self.assertEqual(json.loads(child.stdout)["status"], "COMPLETED_DISCLOSURE_STORAGE")
        self.source_state("SOURCE_UNAVAILABLE")
        command[command.index("--decision-at") + 1] = self.options["decision_at"]
        child = subprocess.run(command, capture_output=True, text=True, timeout=90)
        self.assertEqual(child.returncode, 2, child.stderr + child.stdout)
        self.assertEqual(json.loads(child.stdout)["reason"], "SOURCE_UNAVAILABLE")
        self.assertNotIn("Traceback", child.stderr)

    def test_amendment_cover_identity_is_not_a_type_only_hint(self):
        filings = standalone_filings()
        filings.append(dict(accession="0000000001-26-000002", period="2025-12-31",
            accepted="2026-02-16T15:00:00Z", form="13F-HR/A", amendment="RESTATEMENT", positions=[]))
        self.options = standalone_fixture(self.root / "source", filings)
        cover = self.options["raw_dir"] / "filings/13f_cover/000000000126000002_info.xml"
        original = cover.read_text()
        for old, new in [("<cik>0000000001", "<cik>0000000002"),
                         ("<periodOfReport>2025-12-31", "<periodOfReport>2025-09-30"),
                         ("<submissionType>13F-HR/A", "<submissionType>13F-HR"),
                         ("<isAmendment>true", "<isAmendment>false")]:
            with self.subTest(field=old):
                cover.write_text(original.replace(old, new))
                result = self.execute()
                self.assertEqual(result["reason"], "13F_AMENDMENT_COVER_IDENTITY", result)
                self.assertEqual(result["new_events"], 0)
        cover.write_text(original)
        self.assertEqual(self.execute()["status"], "COMPLETED_DISCLOSURE_STORAGE")
        receipt = self.read()["filing_receipts"][filings[-1]["accession"]]
        self.assertEqual(receipt["cover_document_sha256"], source_collector.file_hash(cover))

    def test_missing_CLI_argument_invalidates_owned_success_only(self):
        import subprocess
        self.execute()
        command = [sys.executable, "-B"] + (["-O"] if sys.flags.optimize else []) + [
            str(ROOT / "tools/run_13f_position_event_builder.py"), "--disclosure-research",
            "--disclosure-output-dir", str(self.store)]
        before = (self.store / "attempt.json").read_bytes()
        lock = self.store / ".writer.lock"
        lock.write_text("other writer")
        child = subprocess.run(command, capture_output=True, text=True, timeout=90)
        self.assertEqual(child.returncode, 2)
        self.assertEqual((self.store / "attempt.json").read_bytes(), before)
        lock.unlink()
        child = subprocess.run(command, capture_output=True, text=True, timeout=90)
        self.assertEqual(child.returncode, 2)
        self.assertEqual(json.loads((self.store / "attempt.json").read_text())["reason"], "13F_RESEARCH_ARGUMENTS_REQUIRED")
        with self.assertRaisesRegex(ValueError, "CURRENT_ATTEMPT"):
            self.read()
        self.assertEqual(self.read(True)["event_count"], 5)
        unowned = self.root / "unowned"
        unowned.mkdir()
        (unowned / "user.txt").write_text("preserve")
        command[-1] = str(unowned)
        self.assertEqual(subprocess.run(command, capture_output=True, text=True, timeout=90).returncode, 2)
        self.assertEqual([p.name for p in unowned.iterdir()], ["user.txt"])

    def test_weight_change_is_not_a_share_trade(self):
        filings = standalone_filings()
        filings[1]["positions"] = [("000000001", 100, 2000), ("000000002", 50, 500)]
        self.options = standalone_fixture(self.root / "source", filings)
        self.assertEqual(self.execute()["status"], "COMPLETED_DISCLOSURE_STORAGE")
        events = [json.loads(disclosure_builder._disclosure_ref(self.store, e["ref"])) for e in self.read()["events"]]
        changes = [e for e in events if e["accession"] == filings[1]["accession"]]
        self.assertEqual({e["event_type"] for e in changes}, {"WEIGHT_CHANGE_ONLY"})
        self.assertTrue(all(e["shares_delta"] == 0 and not e["trade_inferred"] for e in changes))

    def test_missing_measure_and_duplicate_constituents_refuse(self):
        for positions, reason in [([("000000001", None, 1000)], "13F_MISSING_POSITION_MEASURE"),
            ([("000000001", 10, 1000), ("000000001", 20, 2000)], "13F_AMBIGUOUS_CONSTITUENT_ROWS")]:
            with self.subTest(reason=reason):
                filings = standalone_filings()[:1]
                filings[0]["positions"] = positions
                self.options = standalone_fixture(self.root / "source", filings)
                result = self.execute()
                self.assertEqual(result["reason"], reason, result)
                self.assertEqual(result["new_events"], 0)

    def test_latest_observed_filing_cannot_be_omitted_from_index(self):
        index_path = self.options["filings_index"]
        index = pd.read_parquet(index_path).iloc[:1]
        summary = json.loads((index_path.parent / "sec_filings_index_summary.json").read_text())
        source_collector.write_outputs(index, index_path.parent, collection_metadata=summary["collection"])
        self.options["decision_at"] = datetime.now(timezone.utc).isoformat()
        self.assertEqual(self.execute()["reason"], "13F_LATEST_FILING_NOT_INDEXED")

    def test_conflicting_source_summary_cannot_claim_current_success(self):
        path = self.options["filings_index"].parent / "sec_filings_index_summary.json"
        summary = json.loads(path.read_text())
        summary["status"] = "SOURCE_CHECK_INCOMPLETE"
        path.write_text(json.dumps(summary))
        self.assertEqual(self.execute()["reason"], "13F_SOURCE_CURRENT_STATE_BINDING")

    def barrier_filings(self, additive=False, recovery=False):
        base, next_quarter = standalone_filings()
        base["positions"] = [("000000001", 10, 1000)]
        next_quarter["positions"] = [("000000001", 15, 1500)]
        amendment = dict(accession="0000000001-25-000002", period=base["period"],
            accepted="2025-11-17T15:00:00Z", form="13F-HR/A",
            amendment="NEW HOLDINGS" if additive else "RESTATEMENT",
            positions=[("000000004", 1, 100)] if additive else [("000000001", 20, 2000), ("000000004", 1, 100)])
        filings = [base, amendment]
        if additive:
            filings.append(dict(accession="0000000001-25-000003", period=base["period"],
                accepted="2025-11-18T15:00:00Z", form="13F-HR/A", amendment="NEW HOLDINGS",
                positions=[("000000002", 2, 200)]))
        if recovery:
            filings.append(dict(accession="0000000001-25-000004", period=base["period"],
                accepted="2025-11-19T15:00:00Z", form="13F-HR/A", amendment="RESTATEMENT",
                positions=[("000000001", 20, 2000)]))
        return filings + [next_quarter]

    def test_incomplete_restatement_blocks_next_quarter_comparison(self):
        filings = self.barrier_filings()
        self.options = standalone_fixture(self.root / "source", filings)
        self.assertEqual(self.execute()["status"], "COMPLETED_DISCLOSURE_STORAGE")
        manifest = self.read()
        events = [json.loads(disclosure_builder._disclosure_ref(self.store, e["ref"])) for e in manifest["events"]]
        later = [e for e in events if e["accession"] == filings[-1]["accession"]]
        self.assertEqual([e["event_type"] for e in later], ["INITIAL_OBSERVATION"])
        self.assertIsNone(later[0]["shares_delta"])
        self.assertEqual(later[0]["comparison_blocker_accessions"], [filings[1]["accession"]])
        self.assertIn("INCOMPLETE_COMPARISON_BOUNDARY", {r["role"] for r in later[0]["evidence_refs"]})
        self.assertEqual(self.execute()["new_events"], 0)

    def test_additive_cannot_skip_an_incomplete_revision(self):
        filings = self.barrier_filings(additive=True)
        self.options = standalone_fixture(self.root / "source", filings)
        self.assertEqual(self.execute()["status"], "COMPLETED_DISCLOSURE_STORAGE")
        events = [json.loads(disclosure_builder._disclosure_ref(self.store, e["ref"])) for e in self.read()["events"]]
        additive = [e for e in events if e["accession"] == filings[2]["accession"]]
        self.assertTrue(additive)
        self.assertTrue(all(e["event_type"] == "DISCLOSURE_REVIEW_INCOMPLETE" and not e["denominator_complete"] for e in additive))
        later = [e for e in events if e["accession"] == filings[-1]["accession"]]
        self.assertEqual([e["event_type"] for e in later], ["INITIAL_OBSERVATION"])
        self.assertEqual(later[0]["comparison_blocker_accessions"], [f["accession"] for f in filings[1:3]])

    def test_complete_restatement_restores_a_new_comparison_boundary(self):
        filings = self.barrier_filings(additive=True, recovery=True)
        self.options = standalone_fixture(self.root / "source", filings)
        self.assertEqual(self.execute()["status"], "COMPLETED_DISCLOSURE_STORAGE")
        events = [json.loads(disclosure_builder._disclosure_ref(self.store, e["ref"])) for e in self.read()["events"]]
        later = [e for e in events if e["accession"] == filings[-1]["accession"]]
        self.assertEqual([e["event_type"] for e in later], ["REPORTED_SHARES_DECREASE"])
        self.assertEqual(later[0]["shares_delta"], -5)
        self.assertEqual(later[0]["prior_accession"], filings[-2]["accession"])
        self.assertEqual(later[0]["comparison_blocker_accessions"], [])

    def omit_paired_filing(self, accession):
        """Use genuine serializers while retaining the full submissions witness."""
        index_path = self.options["filings_index"]
        index = pd.read_parquet(index_path)
        index = index[index["accession_number"].ne(accession)].copy()
        summary = json.loads((index_path.parent / "sec_filings_index_summary.json").read_text())
        source_collector.write_outputs(index, index_path.parent, collection_metadata=summary["collection"])
        mapping = source_parser.read_cusip_map(self.options["cusip_map"])
        with patch.object(source_parser, "sec_get_text", side_effect=AssertionError("network forbidden")), \
                patch.object(source_parser, "sec_get_json", side_effect=AssertionError("network forbidden")):
            frame = source_parser.parse_13f_index(index, raw_dir=self.options["raw_dir"],
                                                cusip_map=mapping, exact_cusip_only=True)
        source_parser.write_outputs(frame, self.options["holdings"].parent)
        self.options["decision_at"] = datetime.now(timezone.utc).isoformat()

    def test_observed_middle_revision_cannot_be_omitted_from_paired_tables(self):
        filings = self.barrier_filings()
        for seeded in (False, True):
            with self.subTest(previous_store=seeded):
                self.options = standalone_fixture(self.root / ("seeded" if seeded else "first"), filings)
                if seeded:
                    self.assertEqual(self.execute()["status"], "COMPLETED_DISCLOSURE_STORAGE")
                    old = self.read()
                self.omit_paired_filing(filings[1]["accession"])
                result = self.execute()
                self.assertEqual(result["reason"], "13F_OBSERVED_COMPARISON_TIMELINE_GAP", result)
                self.assertEqual(result["new_events"], 0)
                self.assertEqual(result["new_notification_intents"], 0)
                if seeded:
                    with self.assertRaisesRegex(ValueError, "CURRENT_ATTEMPT"):
                        self.read()
                    self.assertEqual(self.read(True)["events"], old["events"])
                else:
                    self.assertFalse((self.store / "current_generation.json").exists())

    def test_full_restatement_recovers_an_incomplete_original(self):
        filings = self.barrier_filings()
        filings[0]["positions"].append(("000000004", 1, 100))
        filings[1]["positions"] = [("000000001", 20, 2000)]
        self.options = standalone_fixture(self.root / "source", filings)
        self.assertEqual(self.execute()["status"], "COMPLETED_DISCLOSURE_STORAGE")
        manifest = self.read()
        events = [json.loads(disclosure_builder._disclosure_ref(self.store, e["ref"])) for e in manifest["events"]]
        revised = [e for e in events if e["accession"] == filings[1]["accession"]]
        self.assertEqual([e["event_type"] for e in revised], ["INITIAL_OBSERVATION"])
        self.assertEqual(revised[0]["original_accession"], filings[0]["accession"])
        self.assertTrue(revised[0]["denominator_complete"])
        self.assertIn(dict(role="VERIFIED_ORIGINAL", accession=filings[0]["accession"],
            document_sha256=manifest["filing_receipts"][filings[0]["accession"]]["document_sha256"],
            cover_document_sha256=None), revised[0]["evidence_refs"])
        later = [e for e in events if e["accession"] == filings[-1]["accession"]]
        self.assertEqual([e["event_type"] for e in later], ["REPORTED_SHARES_DECREASE"])
        self.assertEqual(later[0]["shares_delta"], -5)
        self.assertEqual(later[0]["prior_accession"], filings[1]["accession"])
        self.assertEqual(later[0]["comparison_blocker_accessions"], [])
        self.assertEqual(self.execute()["new_events"], 0)
        self.assertEqual(self.read()["events"], manifest["events"])

    def test_additive_or_unknown_revision_cannot_recover_incomplete_original(self):
        for amendment in ("NEW HOLDINGS", "UNKNOWN"):
            with self.subTest(amendment=amendment):
                filings = self.barrier_filings()
                filings[0]["positions"].append(("000000004", 1, 100))
                filings[1].update(amendment="RESTATEMENT" if amendment == "UNKNOWN" else amendment,
                                  positions=[("000000002", 2, 200)])
                self.options = standalone_fixture(self.root / amendment.replace(" ", "_"), filings)
                if amendment == "UNKNOWN":
                    cover = self.options["raw_dir"] / "filings/13f_cover/000000000125000002_info.xml"
                    cover.write_text(cover.read_text().replace("RESTATEMENT", "UNKNOWN"))
                store = self.root / (amendment + "_store")
                result = self.execute(output_root=store)
                if amendment == "UNKNOWN":
                    self.assertEqual(result["reason"], "13F_UNKNOWN_AMENDMENT_TYPE", result)
                    self.assertEqual(result["new_events"], 0)
                    self.assertFalse((store / "current_generation.json").exists())
                    continue
                self.assertEqual(result["status"], "COMPLETED_DISCLOSURE_STORAGE", result)
                manifest = disclosure_builder.read_disclosure_generation(store)
                events = [json.loads(disclosure_builder._disclosure_ref(store, e["ref"])) for e in manifest["events"]]
                revised = [e for e in events if e["accession"] == filings[1]["accession"]]
                self.assertTrue(all(e["event_type"] == "DISCLOSURE_REVIEW_INCOMPLETE" and
                                    not e["denominator_complete"] for e in revised))
                self.assertTrue(revised)
                later = [e for e in events if e["accession"] == filings[-1]["accession"]]
                self.assertEqual([e["event_type"] for e in later], ["INITIAL_OBSERVATION"])
                self.assertIsNone(later[0]["shares_delta"])
                self.assertEqual(later[0]["comparison_blocker_accessions"],
                                 [f["accession"] for f in filings[:2]])


def main() -> int:
    test_event_builder_detects_add_new_and_exit()
    test_initial_period_is_not_false_new_signal()
    test_manager_universe_metadata_is_attached()
    test_restatement_replaces_base_snapshot_in_position_events()
    test_late_restatement_keeps_earlier_disclosure_events()
    test_late_new_holdings_only_reconciles_to_newer_complete_snapshot()
    test_cli_writes_pit_and_latest_outputs()
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(StandaloneDisclosureTests))
    if not result.wasSuccessful():
        return 1
    print("sec_13f_position_event_builder_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

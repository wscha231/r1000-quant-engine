from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.candidate_universe_registry import file_sha256  # noqa: E402
from tools.run_candidate_universe_refresh import (  # noqa: E402
    _load_verified_13f_events,
    build_from_inputs,
    write_artifact,
)
from tools.run_candidate_universe_scan import (  # noqa: E402
    eligible_tickers,
    load_candidate_artifact,
    run_scan,
)

ASOF = "2026-09-16T00:00:00Z"
SUMMARY = {
    "research_only": True,
    "security_identity_preserved": True,
    "stock_signal_scope": "CASH_EQUITY_ONLY_OPTIONS_AND_PRN_EXCLUDED_FROM_STOCK_SCORE",
    "score_total_changed": False,
}


def signal(
    ticker: str = "ZZZZ",
    buyers: int = 1,
    sellers: int = 0,
    new: int = 1,
    delta: float = 1_000_000.0,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "latest_available_from": "2026-08-14T20:00:00Z",
        "sec_13f_buying_manager_count": buyers,
        "sec_13f_selling_manager_count": sellers,
        "sec_13f_new_position_manager_count": new,
        "sec_13f_value_delta_usd": delta,
    }


def verified_holding(ticker: str = "ZZZZ") -> dict[str, object]:
    return {
        "manager_cik": "0000000001",
        "manager_name": "Fixture Manager",
        "ticker_mapped": ticker,
        "report_period": "2026-06-30",
        "filing_date": "2026-08-14",
        "accepted_at": "2026-08-14T20:00:00Z",
        "available_from": "2026-08-14T20:00:00Z",
        "cusip": "123456789",
        "issuer_name": "Fixture Issuer",
        "title_of_class": "COM",
        "shares": 100.0,
        "share_type": "SH",
        "market_value_usd": 1_000.0,
        "put_call": "",
        "investment_discretion": "SOLE",
        "other_manager": "",
        "source_accession": "0000000001-26-000001",
        "form_type": "13F-HR",
        "amendment_type": "",
    }


def write_verified_source(root: Path, *, receipt_mutator=None) -> tuple[Path, Path]:
    holdings = root / "holdings.csv"
    pd.DataFrame([verified_holding()]).to_csv(holdings, index=False)
    receipt = {
        "schema_version": "sec-13f-publication-verification-v2",
        "status": "ready",
        "kind": "sec",
        "expected_identity": {
            "workflow_run_id": "123456",
            "head_sha": "a" * 40,
            "head_branch": "master",
        },
        "observed_identity": {
            "workflow_run_id": "123456",
            "head_sha": "a" * 40,
            "head_branch": "master",
        },
        "filings_index_sha256": "b" * 64,
        "holdings_sha256": file_sha256(holdings),
        "evidence_sha256": {},
        "failures": [],
        "research_only": True,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    if receipt_mutator:
        receipt_mutator(receipt)
    verification = root / "verification.json"
    verification.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    return holdings, verification


class FakeCandidate:
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.final_score = 77.0
        self.tech_score = 70.0


class CandidateUniversePipelineTests(unittest.TestCase):
    def test_event_ticker_reaches_candidate_scan_argument(self) -> None:
        reasons, universe, queue, manifest = build_from_inputs(
            r1000_tickers=["AAPL"],
            adr_tickers=["ASML"],
            as_of=ASOF,
            r1000_source_status="iwb_live",
            institutional_signals=pd.DataFrame([signal()]),
            institutional_summary=SUMMARY,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_artifact(root, reasons, universe, queue, manifest)
            fake = types.ModuleType("aggressive.scanner")
            seen: dict[str, object] = {}

            def scan(**kwargs):
                seen.update(kwargs)
                return [FakeCandidate("ZZZZ")]

            fake.scan = scan  # type: ignore[attr-defined]
            aggressive = types.ModuleType("aggressive")
            aggressive.__path__ = []  # type: ignore[attr-defined]
            with mock.patch.dict(
                sys.modules,
                {"aggressive": aggressive, "aggressive.scanner": fake},
            ):
                rows, _ = run_scan(root, verbose=False)
            self.assertIn("ZZZZ", seen["tickers"])
            self.assertEqual(seen["universe_source"], "custom")
            self.assertEqual(rows[0]["event_membership_score_bonus"], 0.0)

    def test_risk_only_event_not_sent_to_buy_scanner(self) -> None:
        reasons, universe, queue, manifest = build_from_inputs(
            r1000_tickers=["AAPL"],
            adr_tickers=[],
            as_of=ASOF,
            r1000_source_status="iwb_live",
            institutional_signals=pd.DataFrame(
                [signal(buyers=0, sellers=2, new=0, delta=-1_000_000)]
            ),
            institutional_summary=SUMMARY,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_artifact(root, reasons, universe, queue, manifest)
            frame, _ = load_candidate_artifact(root)
            self.assertNotIn("ZZZZ", eligible_tickers(frame))
            self.assertIn("AAPL", eligible_tickers(frame))

    def test_data_queue_keeps_risk_monitor(self) -> None:
        _, _, queue, _ = build_from_inputs(
            r1000_tickers=["AAPL"],
            adr_tickers=[],
            as_of=ASOF,
            r1000_source_status="iwb_live",
            institutional_signals=pd.DataFrame(
                [signal(buyers=0, sellers=1, new=0, delta=-1_000_000)]
            ),
            institutional_summary=SUMMARY,
        )
        row = queue.set_index("ticker").loc["ZZZZ"]
        self.assertEqual(row["queue_class"], "RISK_REVIEW_MONITOR_ONLY")
        self.assertTrue(bool(row["monitor_eligible"]))

    def test_themes_fallback_base_is_blocked(self) -> None:
        with self.assertRaises(Exception):
            build_from_inputs(
                r1000_tickers=["AAPL"],
                adr_tickers=[],
                as_of=ASOF,
                r1000_source_status="themes_fallback",
            )

    def test_manifest_hash_tamper_blocks_scan(self) -> None:
        reasons, universe, queue, manifest = build_from_inputs(
            r1000_tickers=["AAPL"],
            adr_tickers=[],
            as_of=ASOF,
            r1000_source_status="iwb_live",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_artifact(root, reasons, universe, queue, manifest)
            (root / "candidate_universe.csv").write_text("ticker\nBAD\n", encoding="utf-8")
            with self.assertRaises(Exception):
                load_candidate_artifact(root)

    def test_form4_absence_is_explicitly_blocked_not_fake_empty(self) -> None:
        _, _, _, manifest = build_from_inputs(
            r1000_tickers=["AAPL"],
            adr_tickers=[],
            as_of=ASOF,
            r1000_source_status="iwb_live",
        )
        self.assertEqual(manifest["source_status"]["form4"], "BLOCKED_UNVERIFIED")

    def test_13f_absence_is_explicit_missing(self) -> None:
        _, _, _, manifest = build_from_inputs(
            r1000_tickers=["AAPL"],
            adr_tickers=[],
            as_of=ASOF,
            r1000_source_status="iwb_live",
        )
        self.assertEqual(manifest["source_status"]["sec_13f"], "MISSING")

    def test_output_dir_overwrite_blocked(self) -> None:
        reasons, universe, queue, manifest = build_from_inputs(
            r1000_tickers=["AAPL"],
            adr_tickers=[],
            as_of=ASOF,
            r1000_source_status="iwb_live",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_artifact(root, reasons, universe, queue, manifest)
            with self.assertRaises(Exception):
                write_artifact(root, reasons, universe, queue, manifest)

    def test_base_and_event_reason_union_no_duplicate_ticker(self) -> None:
        reasons, universe, _, _ = build_from_inputs(
            r1000_tickers=["AAPL"],
            adr_tickers=["AAPL"],
            as_of=ASOF,
            r1000_source_status="iwb_live",
            institutional_signals=pd.DataFrame([signal(ticker="AAPL")]),
            institutional_summary=SUMMARY,
        )
        self.assertEqual(list(universe["ticker"]), ["AAPL"])
        self.assertEqual(len(reasons[reasons["ticker"].eq("AAPL")]), 3)

    def test_verified_13f_receipt_recomputes_event_from_exact_holdings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            holdings, verification = write_verified_source(Path(tmp))
            expected_holdings_sha = file_sha256(holdings)
            signals, summary, source_hash, identity = _load_verified_13f_events(
                holdings_path=holdings,
                verification_path=verification,
                as_of=ASOF,
            )
        self.assertIn("ZZZZ", set(signals["ticker"]))
        self.assertTrue(summary["security_identity_preserved"])
        self.assertEqual(identity["holdings_sha256"], expected_holdings_sha)
        self.assertEqual(len(identity["signal_content_sha256"]), 64)
        self.assertEqual(len(source_hash), 64)

    def test_verified_13f_rejects_wrong_holdings_hash(self) -> None:
        def mutate(receipt):
            receipt["holdings_sha256"] = "0" * 64

        with tempfile.TemporaryDirectory() as tmp:
            holdings, verification = write_verified_source(Path(tmp), receipt_mutator=mutate)
            with self.assertRaisesRegex(Exception, "holdings_sha256_mismatch"):
                _load_verified_13f_events(
                    holdings_path=holdings,
                    verification_path=verification,
                    as_of=ASOF,
                )

    def test_verified_13f_rejects_blocked_receipt(self) -> None:
        def mutate(receipt):
            receipt["status"] = "blocked"
            receipt["failures"] = ["freshness_not_ready"]

        with tempfile.TemporaryDirectory() as tmp:
            holdings, verification = write_verified_source(Path(tmp), receipt_mutator=mutate)
            with self.assertRaisesRegex(Exception, "not_ready"):
                _load_verified_13f_events(
                    holdings_path=holdings,
                    verification_path=verification,
                    as_of=ASOF,
                )

    def test_verified_13f_rejects_identity_mismatch(self) -> None:
        def mutate(receipt):
            receipt["observed_identity"]["head_sha"] = "b" * 40

        with tempfile.TemporaryDirectory() as tmp:
            holdings, verification = write_verified_source(Path(tmp), receipt_mutator=mutate)
            with self.assertRaisesRegex(Exception, "identity_mismatch:head_sha"):
                _load_verified_13f_events(
                    holdings_path=holdings,
                    verification_path=verification,
                    as_of=ASOF,
                )

    def test_verified_13f_rejects_receipt_with_failures_even_if_status_ready(self) -> None:
        def mutate(receipt):
            receipt["failures"] = ["holdings_sha256_mismatch"]

        with tempfile.TemporaryDirectory() as tmp:
            holdings, verification = write_verified_source(Path(tmp), receipt_mutator=mutate)
            with self.assertRaisesRegex(Exception, "has_failures"):
                _load_verified_13f_events(
                    holdings_path=holdings,
                    verification_path=verification,
                    as_of=ASOF,
                )


if __name__ == "__main__":
    unittest.main()

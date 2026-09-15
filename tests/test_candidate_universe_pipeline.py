from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_candidate_universe_refresh import build_from_inputs, write_artifact  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()

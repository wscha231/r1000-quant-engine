from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.candidate_universe_registry import (  # noqa: E402
    UniverseIntegrityError,
    aggregate_reasons,
    base_reasons,
    build_manifest,
    reasons_from_13f,
    reasons_from_form4,
)

ASOF = "2026-09-16T00:00:00Z"
SUMMARY = {
    "research_only": True,
    "security_identity_preserved": True,
    "stock_signal_scope": "CASH_EQUITY_ONLY_OPTIONS_AND_PRN_EXCLUDED_FROM_STOCK_SCORE",
    "score_total_changed": False,
}


def signal(**kwargs):
    row = {
        "ticker": "ZZZZ",
        "latest_available_from": "2026-08-14T20:00:00Z",
        "sec_13f_buying_manager_count": 1,
        "sec_13f_selling_manager_count": 0,
        "sec_13f_new_position_manager_count": 1,
        "sec_13f_value_delta_usd": 1_000_000.0,
    }
    row.update(kwargs)
    return row


class CandidateUniverseRegistryTests(unittest.TestCase):
    def test_base_r1000_and_adr_reasons_independent(self) -> None:
        reasons = base_reasons(["AAPL", "TSM"], ["TSM", "ASML"], as_of=ASOF)
        reason_frame, universe = aggregate_reasons(reasons, as_of=ASOF)
        self.assertEqual(set(universe["ticker"]), {"AAPL", "TSM", "ASML"})
        self.assertEqual(
            set(reason_frame[reason_frame["ticker"].eq("TSM")]["reason_type"]),
            {"R1000_BASE", "ADR_BASE"},
        )

    def test_positive_13f_adds_event_only_candidate(self) -> None:
        reasons = base_reasons(["AAPL"], [], as_of=ASOF) + reasons_from_13f(
            pd.DataFrame([signal()]), SUMMARY, as_of=ASOF
        )
        _, universe = aggregate_reasons(reasons, as_of=ASOF)
        row = universe.set_index("ticker").loc["ZZZZ"]
        self.assertTrue(bool(row["candidate_scan_eligible"]))
        self.assertTrue(bool(row["event_discovered"]))
        self.assertFalse(bool(row["base_member"]))

    def test_negative_only_event_is_monitor_not_buy_candidate(self) -> None:
        reasons = reasons_from_13f(
            pd.DataFrame(
                [
                    signal(
                        sec_13f_buying_manager_count=0,
                        sec_13f_new_position_manager_count=0,
                        sec_13f_selling_manager_count=2,
                        sec_13f_value_delta_usd=-5_000_000,
                    )
                ]
            ),
            SUMMARY,
            as_of=ASOF,
        )
        _, universe = aggregate_reasons(reasons, as_of=ASOF)
        row = universe.iloc[0]
        self.assertTrue(bool(row["monitor_eligible"]))
        self.assertFalse(bool(row["candidate_scan_eligible"]))
        self.assertTrue(bool(row["event_only_risk_watch"]))

    def test_base_member_remains_candidate_when_risk_event_arrives(self) -> None:
        events = reasons_from_13f(
            pd.DataFrame(
                [
                    signal(
                        ticker="AAPL",
                        sec_13f_buying_manager_count=0,
                        sec_13f_new_position_manager_count=0,
                        sec_13f_selling_manager_count=2,
                        sec_13f_value_delta_usd=-5_000_000,
                    )
                ]
            ),
            SUMMARY,
            as_of=ASOF,
        )
        _, universe = aggregate_reasons(
            base_reasons(["AAPL"], [], as_of=ASOF) + events,
            as_of=ASOF,
        )
        row = universe.iloc[0]
        self.assertTrue(bool(row["base_member"]))
        self.assertTrue(bool(row["candidate_scan_eligible"]))
        self.assertTrue(bool(row["risk_watch"]))

    def test_mixed_event_is_review_candidate_not_clean_buy(self) -> None:
        reasons = reasons_from_13f(
            pd.DataFrame([signal(sec_13f_selling_manager_count=1)]),
            SUMMARY,
            as_of=ASOF,
        )
        self.assertEqual(reasons[0].polarity, "MIXED_REVIEW")

    def test_expired_event_not_active(self) -> None:
        reasons = reasons_from_13f(
            pd.DataFrame([signal(latest_available_from="2025-01-01T00:00:00Z")]),
            SUMMARY,
            as_of=ASOF,
            ttl_days=30,
        )
        self.assertEqual(reasons[0].status, "EXPIRED")
        _, universe = aggregate_reasons(reasons, as_of=ASOF)
        self.assertTrue(universe.empty)

    def test_13f_h1_receipt_required(self) -> None:
        bad = dict(SUMMARY)
        bad["security_identity_preserved"] = False
        with self.assertRaises(UniverseIntegrityError):
            reasons_from_13f(pd.DataFrame([signal()]), bad, as_of=ASOF)

    def test_h2_skill_not_claimed(self) -> None:
        reason = reasons_from_13f(pd.DataFrame([signal()]), SUMMARY, as_of=ASOF)[0]
        self.assertEqual(reason.source_quality, "H1_VERIFIED_H2_MANAGER_SKILL_PENDING")
        self.assertNotIn("SKILLED", reason.reason_type)

    def test_future_13f_event_blocked(self) -> None:
        with self.assertRaises(UniverseIntegrityError):
            reasons_from_13f(
                pd.DataFrame([signal(latest_available_from="2026-10-01T00:00:00Z")]),
                SUMMARY,
                as_of=ASOF,
            )

    def test_zero_change_not_added(self) -> None:
        reasons = reasons_from_13f(
            pd.DataFrame(
                [
                    signal(
                        sec_13f_buying_manager_count=0,
                        sec_13f_new_position_manager_count=0,
                        sec_13f_value_delta_usd=0,
                    )
                ]
            ),
            SUMMARY,
            as_of=ASOF,
        )
        self.assertEqual(reasons, [])

    def test_form4_is_blocked_without_dedicated_h1_receipt(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "ticker": "ZZZZ",
                    "latest_available_from": "2026-09-15T00:00:00Z",
                    "insider_buy_value": 1000,
                    "insider_sale_value": 0,
                    "sec_form4_sale_pressure_score": 0,
                }
            ]
        )
        with self.assertRaisesRegex(UniverseIntegrityError, "form4_source_not_h1_verified"):
            reasons_from_form4(frame, {"status": "UNVERIFIED"}, as_of=ASOF)

    def test_verified_form4_positive_can_add_candidate(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "ticker": "ZZZZ",
                    "latest_available_from": "2026-09-15T00:00:00Z",
                    "insider_buy_value": 1000,
                    "insider_sale_value": 0,
                    "sec_form4_sale_pressure_score": 0,
                }
            ]
        )
        reasons = reasons_from_form4(
            frame,
            {"status": "VERIFIED_H1", "eligible_for_candidate_universe": True},
            as_of=ASOF,
        )
        self.assertEqual(reasons[0].polarity, "CANDIDATE")

    def test_form4_sale_only_risk_watch(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "ticker": "ZZZZ",
                    "latest_available_from": "2026-09-15T00:00:00Z",
                    "insider_buy_value": 0,
                    "insider_sale_value": 1000,
                    "sec_form4_sale_pressure_score": 1,
                }
            ]
        )
        reasons = reasons_from_form4(
            frame,
            {"status": "VERIFIED_H1", "eligible_for_candidate_universe": True},
            as_of=ASOF,
        )
        _, universe = aggregate_reasons(reasons, as_of=ASOF)
        self.assertTrue(bool(universe.iloc[0]["event_only_risk_watch"]))
        self.assertFalse(bool(universe.iloc[0]["candidate_scan_eligible"]))

    def test_duplicate_reason_blocked(self) -> None:
        reason = base_reasons(["AAPL"], [], as_of=ASOF)[0]
        with self.assertRaises(UniverseIntegrityError):
            aggregate_reasons([reason, reason], as_of=ASOF)

    def test_bad_ticker_blocked(self) -> None:
        with self.assertRaises(UniverseIntegrityError):
            base_reasons(["BAD TICKER"], [], as_of=ASOF)

    def test_manifest_is_research_only(self) -> None:
        reasons, universe = aggregate_reasons(
            base_reasons(["AAPL"], [], as_of=ASOF),
            as_of=ASOF,
        )
        manifest = build_manifest(
            reasons,
            universe,
            as_of=ASOF,
            source_status={"r1000": "ok"},
        )
        self.assertTrue(manifest["research_only"])
        self.assertFalse(manifest["automatic_trade_allowed"])
        self.assertFalse(manifest["portfolio_target_changed"])


if __name__ == "__main__":
    unittest.main()

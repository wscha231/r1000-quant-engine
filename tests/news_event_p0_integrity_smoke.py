"""Offline synthetic P0 regressions. No market data or alpha evidence.

Run directly; unittest assertions still execute under python -O.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.news_event_alpha_v1 import runtime as R
from research.news_event_alpha_v1 import reporting as REPORT
from research.news_event_alpha_v1 import walk_forward as WF
from tools import run_news_event_alpha_v1 as CLI


def fixture():
    # These are artificial sessions, NOT a reconstructed NYSE calendar.
    now = datetime(2024, 1, 2, 21, tzinfo=timezone.utc)
    sessions = []
    while len(sessions) < 350:
        if now.weekday() < 5:
            sessions.append({"session": now.date().isoformat(), "market_close_utc": now.isoformat()})
        now += timedelta(days=1)
    prices = []
    for i, sess in enumerate(sessions):
        for sid, growth in (("SPY", .0002), ("AAA", .002), ("BBB", -.0005),
                            ("P1", .001), ("P2", .001), ("P3", .001)):
            prices.append({"security_id": sid, "session": sess["session"],
                           "total_return_index": 100 * (1 + growth) ** i,
                           "volume": 1000 if i != 70 else 3000,
                           "available_at": sess["market_close_utc"]})
    events = []
    for sid in ("AAA", "BBB"):
        events.append({"event_id": "filing-1", "economic_event_id": "shared-contract",
                       "stable_security_id": "TESTSEC:" + sid, "security_id": sid,
                       "issuer_id": "TESTISSUER:" + sid, "event_version": 1,
                       "available_at": sessions[70]["market_close_utc"],
                       "instrument": "COMMON", "exchange": "XNYS", "listing_country": "US",
                       "eligibility_verified_asof": True, "official_evidence": True,
                       "event_type": "CONTRACT", "role": "DIRECT", "source_tier": "OFFICIAL",
                       "business_relation_new": True, "economic_value_confirmed": True,
                       "economic_amount_usd": 10000, "economic_amount_kind": "GUARANTEED",
                       "theme_peer_ids": ["P1", "P2", "P3"],
                       "independent_source_groups": ["TEST_IR"], "sample_origin": "HISTORICAL_BACKFILL"})
    return sessions, prices, events


CAL, PRICES, EVENTS = fixture()


def payload(events=None, **kwargs):
    return {"schema": R.SCHEMA_VERSION, "events": deepcopy(EVENTS if events is None else events),
            "prices": PRICES, "market_sessions": CAL, **kwargs}


def checkpoints(events=None, **kwargs):
    return R.build_checkpoint_rows(deepcopy(EVENTS if events is None else events), PRICES, CAL, **kwargs)


def revise(event, version=2, index=74, **kwargs):
    r = deepcopy(event)
    r.update(event_id=f"filing-{version}", event_version=version,
             first_available_at=event["available_at"], available_at=CAL[index]["market_close_utc"])
    r.update(kwargs)
    return r


def outcome_rows():
    return R.attach_forward_outcomes(checkpoints(), PRICES, CAL)


class IdentityTests(unittest.TestCase):
    def test_shared_document_is_allowed_for_two_securities(self):
        self.assertEqual(len(R.normalize_events(EVENTS)), 2)

    def test_event_keys_separate_securities(self):
        a, b = R.normalize_events(EVENTS)
        self.assertNotEqual(R.event_revision_key(a), R.event_revision_key(b))

    def test_stable_id_never_inferred_from_ticker(self):
        e = deepcopy(EVENTS[0]); del e["stable_security_id"]
        with self.assertRaisesRegex(R.ContractError, "stable_security_id"):
            R.normalize_event(e)

    def test_version_required(self):
        e = deepcopy(EVENTS[0]); del e["event_version"]
        with self.assertRaises(R.ContractError): R.normalize_event(e)

    def test_boolean_version_rejected(self):
        e = dict(EVENTS[0], event_version=True)
        with self.assertRaises(R.ContractError): R.normalize_event(e)

    def test_string_version_rejected_in_json(self):
        with self.assertRaises(R.ContractError): R.normalize_event(dict(EVENTS[0], event_version="1"))

    def test_zero_version_rejected(self):
        with self.assertRaises(R.ContractError): R.normalize_event(dict(EVENTS[0], event_version=0))

    def test_non_us_rejected(self):
        with self.assertRaises(R.ContractError): R.normalize_event(dict(EVENTS[0], listing_country="KR"))

    def test_adr_preserved(self):
        self.assertEqual(R.normalize_event(dict(EVENTS[0], instrument="ADR"))["instrument"], "ADR")

    def test_missing_issuer_rejected(self):
        e = deepcopy(EVENTS[0]); del e["issuer_id"]
        with self.assertRaises(R.ContractError): R.normalize_event(e)

    def test_duplicate_source_rejected(self):
        with self.assertRaises(R.ContractError): R.normalize_events([EVENTS[0], EVENTS[0]])

    def test_string_source_groups_rejected(self):
        with self.assertRaises(R.ContractError):
            R.normalize_event(dict(EVENTS[0], independent_source_groups="Reuters"))

    def test_normalization_is_idempotent(self):
        a = R.normalize_events(EVENTS)
        self.assertEqual(R.normalize_events(a), a)

    def test_nonfinite_json_never_hashes(self):
        with self.assertRaises(ValueError): R.canonical_bytes({"x": float("nan")})


class RevisionTests(unittest.TestCase):
    def test_contemporaneous_identical_reprints_dedup(self):
        b = dict(EVENTS[0], event_id="filing-copy", independent_source_groups=["TEST_NEWS"])
        row = R.normalize_events([EVENTS[0], b])[0]
        self.assertEqual(row["source_record_count"], 2)
        self.assertEqual(row["independent_source_groups"], ["TEST_IR", "TEST_NEWS"])
        self.assertEqual(R.normalize_events([row]), [row])

    def test_reprint_input_order_is_deterministic(self):
        b = dict(EVENTS[0], event_id="copy")
        self.assertEqual(R.normalize_events([EVENTS[0], b]), R.normalize_events([b, EVENTS[0]]))

    def test_different_availability_requires_new_version(self):
        b = dict(EVENTS[0], event_id="later-copy", available_at=CAL[71]["market_close_utc"])
        with self.assertRaisesRegex(R.ContractError, "ambiguous revision"):
            R.normalize_events([EVENTS[0], b])

    def test_different_role_requires_new_version(self):
        b = dict(EVENTS[0], event_id="copy", role="ENABLER")
        with self.assertRaises(R.ContractError): R.normalize_events([EVENTS[0], b])

    def test_different_value_requires_new_version(self):
        b = dict(EVENTS[0], event_id="copy", economic_amount_usd=20000)
        with self.assertRaises(R.ContractError): R.normalize_events([EVENTS[0], b])

    def test_revision_without_anchor_rejected(self):
        e = dict(EVENTS[0], event_version=2)
        with self.assertRaisesRegex(R.ContractError, "first_available_at"):
            R.normalize_event(e)

    def test_revision_gap_rejected(self):
        with self.assertRaisesRegex(R.ContractError, "incomplete"):
            checkpoints([EVENTS[0], revise(EVENTS[0], version=3)])

    def test_revision_cannot_change_anchor(self):
        e = revise(EVENTS[0], first_available_at=CAL[71]["market_close_utc"])
        with self.assertRaisesRegex(R.ContractError, "observation clock"): checkpoints([EVENTS[0], e])

    def test_revision_cannot_switch_origin(self):
        with self.assertRaisesRegex(R.ContractError, "origin"):
            checkpoints([EVENTS[0], revise(EVENTS[0], sample_origin="FORWARD_SHADOW")])

    def test_revision_time_must_increase(self):
        with self.assertRaisesRegex(R.ContractError, "non-increasing"):
            checkpoints([EVENTS[0], revise(EVENTS[0], index=70)])

    def test_future_field_clock_rejected(self):
        e = dict(EVENTS[0], field_available_at={"economic_amount_usd": CAL[71]["market_close_utc"]})
        with self.assertRaisesRegex(R.ContractError, "future field"): R.normalize_event(e)

    def test_canonical_hash_tampering_rejected(self):
        e = R.normalize_event(EVENTS[0]); e["economic_amount_usd"] = 55
        with self.assertRaisesRegex(R.ContractError, "hash"): R.normalize_event(e)

    def test_legacy_collapsed_record_requires_reconstruction(self):
        e = dict(EVENTS[0], source_record_count=5)
        with self.assertRaisesRegex(R.ContractError, "collapsed"): R.normalize_event(e)

    def test_late_evidence_cannot_alter_first_checkpoint(self):
        e = dict(EVENTS[0], official_evidence=False, source_tier="TIER1_NEWS")
        before = checkpoints([e])[0]
        after = checkpoints([e, revise(e, official_evidence=True, source_tier="OFFICIAL")])[0]
        self.assertEqual(before, after)

    def test_known_revision_used_only_after_available(self):
        e = dict(EVENTS[0], official_evidence=False)
        rows = checkpoints([e, revise(e, official_evidence=True)])
        self.assertFalse(rows[0]["official_evidence"])
        self.assertTrue(rows[1]["official_evidence"])
        self.assertEqual([r["event_version"] for r in rows], [1, 2, 2, 2])
        self.assertEqual({r["event_session"] for r in rows}, {CAL[70]["session"]})

    def test_correction_revokes_prior_positive_evidence(self):
        correction = revise(EVENTS[0], official_evidence=False, business_relation_new=False,
                            material_agreement_confirmed=False, economic_value_confirmed=False,
                            economic_amount_usd=None)
        rows = checkpoints([EVENTS[0], correction])
        self.assertTrue(rows[0]["business_substance"])
        self.assertFalse(rows[1]["business_substance"])

    def test_asof_blocks_future_checkpoints(self):
        rows = checkpoints(as_of=CAL[73]["market_close_utc"])
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["checkpoint"] for r in rows}, {0})


class LedgerTests(unittest.TestCase):
    def test_two_securities_persist_without_conflict(self):
        rows = R.normalize_events(EVENTS)
        self.assertEqual(len(CLI.merge_immutable_ledger([], rows)), 2)

    def test_rerun_is_idempotent(self):
        rows = R.normalize_events(EVENTS)
        self.assertEqual(CLI.merge_immutable_ledger(rows, rows), rows)

    def test_existing_duplicate_fails_even_if_identical(self):
        rows = R.normalize_events(EVENTS)
        with self.assertRaisesRegex(R.ContractError, "duplicate existing"):
            CLI.merge_immutable_ledger([rows[0], rows[0]], [])

    def test_incoming_duplicate_fails(self):
        rows = R.normalize_events(EVENTS)
        with self.assertRaisesRegex(R.ContractError, "duplicate incoming"):
            CLI.merge_immutable_ledger([], [rows[0], rows[0]])

    def test_new_revision_appends(self):
        first = R.normalize_events([EVENTS[0]])
        second = R.normalize_events([revise(EVENTS[0])])
        both = CLI.merge_immutable_ledger(first, second)
        self.assertEqual(len(both), 2)
        self.assertEqual(both[0], first[0])

    def test_old_revision_cannot_be_overwritten(self):
        first = R.normalize_events([EVENTS[0]])
        changed = R.normalize_events([dict(EVENTS[0], economic_amount_usd=777)])
        with self.assertRaisesRegex(R.ContractError, "immutable event conflict"):
            CLI.merge_immutable_ledger(first, changed)

    def test_missing_revision_parent_blocks_append(self):
        with self.assertRaisesRegex(R.ContractError, "incomplete"):
            CLI.merge_immutable_ledger([], R.normalize_events([revise(EVENTS[0])]))

    def test_legacy_ledger_not_silently_certified(self):
        e = deepcopy(EVENTS[0])
        with self.assertRaisesRegex(R.ContractError, "migration"):
            CLI.merge_immutable_ledger([e], [])


class EndToEndTests(unittest.TestCase):
    def test_two_securities_have_distinct_actuals_in_walk_forward(self):
        cp = checkpoints(); outcomes = R.attach_forward_outcomes(cp, PRICES, CAL)
        estimates = WF.build_walk_forward_impact_estimates(cp, outcomes)
        a = next(r for r in estimates if r["security_id"] == "AAA" and r["checkpoint"] == 5 and r["horizon"] == 21)
        b = next(r for r in estimates if r["security_id"] == "BBB" and r["checkpoint"] == 5 and r["horizon"] == 21)
        self.assertGreater(a["actual_excess_return"], 0)
        self.assertLess(b["actual_excess_return"], 0)
        self.assertNotEqual(a["prediction_id"], b["prediction_id"])

    def test_top_does_not_overwrite_same_economic_event(self):
        self.assertEqual(len(R.top_current_events(checkpoints(), top_n=5)), 2)

    def test_top_is_bounded(self):
        self.assertEqual(len(R.top_current_events(checkpoints(), top_n=1)), 1)

    def test_report_uses_security_specific_prediction(self):
        tops = R.top_current_events(checkpoints(), top_n=5)
        estimates = []
        for t in tops:
            estimates.append(dict(t, horizon=21, analogue_status="AVAILABLE",
                                  analogue_median_excess=.1 if t["security_id"] == "AAA" else -.1))
        report = REPORT.build_top_event_impact_outlook(tops, estimates)
        vals = {r["security_id"]: r["impact_outlook"]["21"]["analogue_median_excess"] for r in report}
        self.assertEqual(vals, {"AAA": .1, "BBB": -.1})

    def test_report_does_not_mix_model_versions(self):
        t = R.top_current_events(checkpoints(), top_n=1)[0]
        other = dict(t, horizon=21, model_version="other", analogue_status="AVAILABLE", analogue_median_excess=.9)
        result = REPORT.build_top_event_impact_outlook([t], [other])
        self.assertEqual(result[0]["impact_outlook"]["21"]["status"], "MISSING")

    def test_report_rejects_duplicate_predictions(self):
        t = R.top_current_events(checkpoints(), top_n=1)[0]
        row = dict(t, horizon=21)
        with self.assertRaisesRegex(R.ContractError, "duplicate report estimate"):
            REPORT.build_top_event_impact_outlook([t], [row, row])

    def test_walk_forward_rejects_duplicate_outcomes(self):
        rows = outcome_rows()
        with self.assertRaisesRegex(R.ContractError, "duplicate input outcome"):
            WF.build_walk_forward_impact_estimates(checkpoints(), rows + [rows[0]])

    def test_version_is_part_of_prediction_identity(self):
        row = checkpoints()[0]
        self.assertNotEqual(R.prediction_key(row, 21), R.prediction_key(dict(row, event_version=2), 21))

    def test_decision_time_is_part_of_identity(self):
        row = checkpoints()[0]
        changed = dict(row, decision_at=CAL[71]["market_close_utc"])
        self.assertNotEqual(R.prediction_key(row, 21), R.prediction_key(changed, 21))

    def test_horizon_end_starts_after_checkpoint(self):
        row = next(r for r in outcome_rows() if r["checkpoint"] == 5 and r["horizon"] == 21)
        self.assertEqual(row["outcome_end_session"], CAL[96]["session"])
        self.assertEqual(row["return_kind"], "OBSERVATION_ONLY_NOT_EXECUTABLE")

    def test_pipeline_safety_and_result_count(self):
        result = R.run_payload(payload())
        self.assertEqual(len(result["checkpoint_rows"]), 8)
        self.assertEqual(len(result["outcomes"]), 48)
        self.assertEqual(len({r["outcome_id"] for r in result["outcomes"]}), 48)
        self.assertEqual(result["selector_weight"], 0)
        self.assertFalse(result["selector_eligible"])
        self.assertFalse(result["orders_generated"])
        self.assertFalse(result["automatic_promotion_allowed"])

    def test_csv_explicit_integer_and_boolean_decoding(self):
        self.assertEqual(CLI.parse_csv_field("event_version", "1"), 1)
        self.assertIs(CLI.parse_csv_field("official_evidence", "false"), False)
        self.assertEqual(CLI.parse_csv_field("security_id", "1234"), "1234")
        self.assertEqual(CLI.parse_csv_field("event_version", "1.0"), "1.0")

    def test_json_rejects_duplicate_keys(self):
        with self.assertRaises(R.ContractError): CLI.checked_json('{"x":1,"x":2}')

    def test_json_rejects_nan(self):
        with self.assertRaises(R.ContractError): CLI.checked_json('{"x":NaN}')

    def test_mode_cannot_relabel_history_as_live(self):
        with self.assertRaises(R.ContractError): CLI.force_origin(EVENTS, "FORWARD_SHADOW")

    def test_fake_64hex_receipt_cannot_start_historical_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmd = [sys.executable, str(ROOT / "tools/run_news_event_alpha_v1.py"),
                   "--events", "missing.json", "--prices", "missing.csv",
                   "--market-sessions", "missing.csv", "--mode", "HISTORICAL_BACKFILL",
                   "--source-commit", "a" * 40, "--data-receipt-sha256", "b" * 64,
                   "--output-dir", str(Path(tmp) / "out")]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("BLOCKED_PENDING_VERIFIED_INPUT_MANIFEST", result.stderr)
            self.assertFalse((Path(tmp) / "out").exists())

    def test_cli_unattested_forward_run_never_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cmd = [sys.executable, str(ROOT / "tools/run_news_event_alpha_v1.py"),
                   "--events", "missing.json", "--prices", "missing.json",
                   "--market-sessions", "missing.json", "--mode", "FORWARD_SHADOW",
                   "--output-dir", str(root / "out")]
            for _ in range(2):
                result = subprocess.run(cmd, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("FORWARD_OBSERVATION_BLOCKED", result.stderr)
                self.assertFalse((root / "out").exists())


class WalkForwardTimingTests(unittest.TestCase):
    def make_prior(self, count=15, origin="HISTORICAL_BACKFILL", late=False):
        current = checkpoints()[1]  # AAA, T+5
        prior = []
        for i in range(count):
            row = dict(current, economic_event_id=f"prior-{i}", event_id=f"prior-doc-{i}",
                       stable_security_id=f"TESTSEC:PRIOR{i}", issuer_id=f"issuer-{i}",
                       sample_origin=origin, horizon=21, outcome_status="RESOLVED",
                       outcome_end_session=CAL[76 if late else 74]["session"],
                       excess_return=.03, event_session=CAL[30]["session"],
                       label_available_at=CAL[76 if late else 74]["market_close_utc"])
            prior.append(row)
        return current, prior

    def test_only_fully_finished_labels_enter_training(self):
        current, prior = self.make_prior()
        _, future = self.make_prior(late=True)
        future = [dict(r, economic_event_id="future-" + r["economic_event_id"], excess_return=5) for r in future]
        estimates = WF.build_walk_forward_impact_estimates([current], prior + future)
        row = next(r for r in estimates if r["horizon"] == 21)
        self.assertEqual(row["training_n"], 15)
        self.assertAlmostEqual(row["analogue_median_excess"], .03)

    def test_historical_cannot_train_on_later_forward_lane(self):
        current, prior = self.make_prior(origin="FORWARD_SHADOW")
        with self.assertRaisesRegex(R.ContractError, "FORWARD_OBSERVATION_BLOCKED"):
            WF.build_walk_forward_impact_estimates([current], prior)

    def test_unattested_forward_cannot_use_mature_historical_prior(self):
        current, prior = self.make_prior()
        current = dict(current, sample_origin="FORWARD_SHADOW")
        with self.assertRaisesRegex(R.ContractError, "FORWARD_OBSERVATION_BLOCKED"):
            WF.build_walk_forward_impact_estimates([current], prior)

    def test_same_economic_event_excluded_across_other_securities(self):
        current, prior = self.make_prior()
        prior = [dict(r, economic_event_id=current["economic_event_id"]) for r in prior]
        row = next(r for r in WF.build_walk_forward_impact_estimates([current], prior) if r["horizon"] == 21)
        self.assertEqual(row["analogue_status"], "UNDERPOWERED")

    def test_other_label_contract_not_mixed_into_training(self):
        current, prior = self.make_prior()
        prior = [dict(r, label_contract="different-price-rule") for r in prior]
        row = next(r for r in WF.build_walk_forward_impact_estimates([current], prior) if r["horizon"] == 21)
        self.assertEqual(row["analogue_status"], "UNDERPOWERED")

    def test_performance_does_not_pool_forward_and_history(self):
        current = checkpoints()[1]
        a = dict(current, horizon=21, analogue_status="AVAILABLE", actual_excess_return=.05,
                 analogue_median_excess=.03, prediction_error=.02, direction_correct=True)
        b = dict(a, sample_origin="FORWARD_SHADOW", actual_excess_return=-.2,
                 prediction_error=-.23, direction_correct=False)
        with self.assertRaisesRegex(R.ContractError, "FORWARD_OBSERVATION_BLOCKED"):
            WF.summarize_walk_forward_performance([a,b])
        self.assertEqual(WF.summarize_walk_forward_performance([a])[0]["n_predictions"], 1)

    def test_same_day_maturity_not_in_training(self):
        current, prior = self.make_prior()
        prior = [dict(r, outcome_end_session=current["checkpoint_session"]) for r in prior]
        row = next(r for r in WF.build_walk_forward_impact_estimates([current], prior) if r["horizon"] == 21)
        self.assertEqual(row["analogue_status"], "UNDERPOWERED")


# Each field is an independent named test, not a count of subtests/re-runs.
def make_boolean_test(field):
    def test(self):
        for bad in ("false", "true", "0", "no", 0, 1, None):
            with self.subTest(value=bad):
                with self.assertRaises(R.ContractError):
                    R.normalize_event(dict(EVENTS[0], **{field: bad}))
    return test


for _field in ("eligibility_verified_asof", "official_evidence", "business_relation_new",
               "material_agreement_confirmed", "economic_value_confirmed"):
    setattr(IdentityTests, "test_strict_boolean_" + _field, make_boolean_test(_field))


if __name__ == "__main__":
    unittest.main(verbosity=2)

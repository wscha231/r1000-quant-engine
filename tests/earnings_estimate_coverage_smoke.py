"""Coverage and fairness regressions; unittest checks remain active under -O."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.audit_earnings_estimate_coverage import H1, audit_rows, audit_files, sha256
from tools.build_forward_estimate_incremental_universe import select_bounded, selection_sort_key

ASOF = "2026-10-03T08:00:00Z"


class CoverageFairnessTests(unittest.TestCase):
    def test_hints_cannot_starve_unserviced_tail(self):
        rows = [{"ticker": t, "last_selected_at_utc": ""} for t in ["AAA", "BBB", "CCC", "DDD"]]
        services = []
        for day in range(8):
            selected = {}
            select_bounded(rows, limit=1, priority={"AAA"}, reason="retry", selected=selected)
            chosen = next(iter(selected))
            services.append(chosen)
            next(r for r in rows if r["ticker"] == chosen)["last_selected_at_utc"] = f"2026-10-{day+1:02}T00:00:00Z"
        self.assertEqual(services, ["AAA", "BBB", "CCC", "DDD"] * 2)

    def test_partial_stop_prefers_unacknowledged_before_hint(self):
        rows = [{"ticker": "AAA", "last_selected_at_utc": "2026-10-02T12:00:00Z"},
                {"ticker": "BBB", "last_selected_at_utc": ""}]
        self.assertEqual([r["ticker"] for r in sorted(rows, key=lambda r: selection_sort_key(r, {"AAA"}))], ["BBB", "AAA"])
        selected = {}
        select_bounded(rows, limit=1, priority={"AAA"}, reason="retry", selected=selected)
        self.assertEqual(list(selected), ["BBB"])

    def test_ever_positive_is_not_latest_null_or_stale(self):
        rows = [{"ticker": "AAA", "available_from": "2026-10-01", "has_forward_estimate": 1, "est_eps_fy1": 3},
                {"ticker": "AAA", "available_from": "2026-10-02", "has_forward_estimate": 0, "est_eps_fy1": 0},
                {"ticker": "BBB", "available_from": "2026-09-01", "has_forward_estimate": 1, "est_eps_fy1": 4}]
        out, summary = audit_rows(["AAA", "BBB", "CASH"], rows, as_of=ASOF)
        self.assertEqual(summary["counts"]["ever_estimate_positive"]["count"], 2)
        self.assertEqual(summary["counts"]["legacy_fresh_positive"]["count"], 0)
        self.assertEqual(summary["counts"]["source_v2_eligible"]["count"], 0)
        self.assertEqual(len(out), 3)

    def test_legacy_zero_is_unproven_and_negative_is_observed(self):
        rows = [{"ticker": t, "available_from": "2026-10-02", "has_forward_estimate": 1, "est_eps_fy1": v}
                for t, v in [("AAA", 0), ("BBB", -2), ("CCC", None)]]
        out, _ = audit_rows(["AAA", "BBB", "CCC"], rows, as_of=ASOF)
        self.assertEqual([r["legacy_fresh_eps_nonzero_evidence"] for r in out], [False, True, False])
        self.assertFalse(any(r["fresh_eps_fy1"] for r in out))

    def test_future_and_unknown_clocks_do_not_certify(self):
        rows = [{"ticker": "AAA", "available_from": "2026-10-04", "has_forward_estimate": 1},
                {"ticker": "BBB", "available_from": None, "has_forward_estimate": 1}]
        out, _ = audit_rows(["AAA", "BBB"], rows, as_of=ASOF)
        self.assertEqual([r["source_state"] for r in out], ["QUARANTINED_FUTURE", "UNKNOWN_TIME"])
        self.assertFalse(any(r["ever_estimate_positive"] for r in out))

    def test_conflicting_latest_cannot_fall_back(self):
        rows = [{"ticker": "AAA", "available_from": "2026-10-02", "has_forward_estimate": 1, "est_eps_fy1": v} for v in [2, 3]]
        out, _ = audit_rows(["AAA"], rows, as_of=ASOF)
        self.assertEqual(out[0]["source_state"], "QUARANTINED_CONFLICT")
        self.assertFalse(out[0]["legacy_fresh_positive"])

    def test_v2_without_upstream_validator_stays_unknown(self):
        row = {"ticker": "AAA", "source_contract": "earnings-consensus-source-v2", "collected_at": ASOF}
        out, summary = audit_rows(["AAA"], [row], as_of=ASOF, h1=None)
        self.assertIsNone(out[0]["source_v2_eligible"])
        self.assertEqual(summary["counts"]["source_v2_eligible"]["unknown"], 1)
        self.assertFalse(out[0]["research_consumer_eligible"])

    def test_frozen_universe_hash_and_source_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            snapshots = p / "snapshots"
            snapshots.mkdir()
            u = p / "universe.csv"
            u.write_text("ticker\nAAA\nCASH\n", encoding="utf-8")
            pd.DataFrame([{"ticker": "AAA", "available_from": "2026-10-02", "has_forward_estimate": 1},
                          {"ticker": "OUTSIDE", "available_from": "2026-10-02", "has_forward_estimate": 1}]).to_parquet(snapshots / "estimates_20261002.parquet")
            before = {f.name: sha256(f) for f in snapshots.iterdir()}
            args = dict(universe_path=u, snapshot_dir=snapshots, output_dir=p / "audit", as_of=ASOF,
                        universe_sha256=sha256(u), expected_equities=1)
            summary = audit_files(**args)
            self.assertEqual(summary["eligible_equities"], 1)
            self.assertEqual(summary["counts"]["ever_estimate_positive"]["count"], 1)
            self.assertEqual(before, {f.name: sha256(f) for f in snapshots.iterdir()})
            with self.assertRaisesRegex(ValueError, "hash_mismatch"):
                audit_files(**{**args, "universe_sha256": "0" * 64})
            with self.assertRaisesRegex(ValueError, "isolated"):
                audit_files(**{**args, "output_dir": snapshots})

    def test_absent_input_is_unknown_not_measured_zero(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            u = p / "universe.csv"
            u.write_text("ticker\nAAA\n", encoding="utf-8")
            summary = audit_files(universe_path=u, snapshot_dir=p / "absent", output_dir=p / "audit",
                                  as_of=ASOF, universe_sha256=sha256(u), expected_equities=1)
            self.assertEqual(summary["status"], "BLOCKED_NO_SNAPSHOT_INPUT")
            self.assertIsNone(summary["counts"]["source_v2_eligible"]["count"])

    def test_output_filename_collision_preserves_frozen_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            u = p / "coverage_by_security.csv"
            u.write_text("ticker\nAAA\n", encoding="utf-8")
            before = u.read_bytes()
            with self.assertRaisesRegex(ValueError, "overwrite_frozen_universe"):
                audit_files(universe_path=u, snapshot_dir=p / "snapshots", output_dir=p,
                            as_of=ASOF, universe_sha256=sha256(u), expected_equities=1)
            self.assertEqual(u.read_bytes(), before)


@unittest.skipIf(H1 is None, "accepted or pinned H1 validator is unavailable")
class SourceV2CoverageTests(unittest.TestCase):
    def snapshot(self, at=ASOF, value=0, provider="fmp", fiscal="2026-12-31", currency="USD", unit="share"):
        record = {"issuer_id": "issuer-A", "security_id": "security-A", "period": fiscal,
                  "period_type": "ANNUAL", "accounting_basis": "GAAP", "currency": currency,
                  "share_or_ADR_unit": unit, "avg": value}
        return H1.build_snapshot("AAA", eps_payload={"data": [record]}, revenue_payload={},
                                 recommendation_payload=[], observed_at=at, collected_at=at, fetch_source=provider)

    def test_verified_explicit_zero_and_negative_eps(self):
        for value in [0, -2]:
            out, _ = audit_rows(["AAA"], [self.snapshot(value=value)], as_of=ASOF)
            self.assertTrue(out[0]["fresh_eps_fy1"])
            self.assertFalse(out[0]["fresh_revenue_fy1"])
            self.assertFalse(out[0]["revision_30d_eligible"])
            self.assertFalse(out[0]["research_consumer_eligible"])

    def test_null_bool_missing_identity_and_expired_period(self):
        for args in [{"value": None}, {"value": True}, {"currency": None}, {"fiscal": "2025-12-31"}]:
            out, _ = audit_rows(["AAA"], [self.snapshot(**args)], as_of=ASOF)
            self.assertFalse(out[0]["fresh_eps_fy1"])

    def test_latest_missing_and_damaged_history_block_fallback(self):
        prior = self.snapshot(at="2026-10-01T08:00:00Z", value=2)
        out, _ = audit_rows(["AAA"], [prior, self.snapshot(value=None)], as_of=ASOF)
        self.assertFalse(out[0]["fresh_eps_fy1"])
        prior["est_eps_fy1"] = 500
        out, _ = audit_rows(["AAA"], [prior, self.snapshot(value=2)], as_of=ASOF)
        self.assertEqual(out[0]["source_state"], "QUARANTINED_INTEGRITY")

    def test_damaged_timestamp_cannot_hide_bad_content(self):
        damaged = self.snapshot(at="2026-10-01T08:00:00Z", value=2)
        damaged["collected_at"] = "2099-01-01T00:00:00Z"
        out, _ = audit_rows(["AAA"], [damaged, self.snapshot(value=3)], as_of=ASOF)
        self.assertEqual(out[0]["source_state"], "QUARANTINED_INTEGRITY")
        self.assertFalse(out[0]["fresh_eps_fy1"])

    def test_annual_and_quarterly_views_are_separate(self):
        record = dict(issuer_id="issuer-A", security_id="security-A", period="2026-12-31",
                      period_type="QUARTERLY", accounting_basis="GAAP", currency="USD",
                      share_or_ADR_unit="share", avg=2)
        row = H1.build_snapshot("AAA", eps_payload={"data": [record]}, revenue_payload={},
                                recommendation_payload=[], observed_at=ASOF, collected_at=ASOF, fetch_source="fmp")
        out, _ = audit_rows(["AAA"], [row], as_of=ASOF)
        self.assertTrue(out[0]["fresh_eps_next_quarter"])
        self.assertFalse(out[0]["fresh_eps_fy1"])

    def test_after_close_knowledge_is_not_available_at_close(self):
        row = self.snapshot(at="2026-10-02T21:00:00Z", value=3)
        out, _ = audit_rows(["AAA"], [row], as_of="2026-10-02T20:00:00Z")
        self.assertFalse(out[0]["fresh_eps_fy1"])

    def test_different_security_or_fiscal_period_cannot_form_both(self):
        eps = dict(issuer_id="issuer-A", security_id="security-A", period="2026-12-31",
                   period_type="ANNUAL", accounting_basis="GAAP", currency="USD", share_or_ADR_unit="share", avg=2)
        for change, state in [({"issuer_id": "issuer-B", "security_id": "security-B"}, "BLOCKED_IDENTITY_CONFLICT"),
                              ({"currency": "KRW"}, "BLOCKED_IDENTITY_CONFLICT"),
                              ({"share_or_ADR_unit": "ADR2"}, "BLOCKED_IDENTITY_CONFLICT"),
                              ({"period": "2027-03-31"}, "BLOCKED_PERIOD_CONFLICT")]:
            row = H1.build_snapshot("AAA", eps_payload={"data": [eps]}, revenue_payload={"data": [{**eps, **change}]},
                                    recommendation_payload=[], observed_at=ASOF, collected_at=ASOF, fetch_source="fmp")
            out, _ = audit_rows(["AAA"], [row], as_of=ASOF)
            self.assertEqual(out[0]["source_state"], state)
            self.assertFalse(out[0]["fresh_both_fy1"])
            self.assertFalse(out[0]["source_v2_eligible"])

    def test_revision_requires_mature_same_period_source_and_unit(self):
        prior = self.snapshot(at="2026-09-01T08:00:00Z", value=2)
        current = self.snapshot(value=3)
        out, _ = audit_rows(["AAA"], [prior, current], as_of=ASOF)
        self.assertTrue(out[0]["revision_30d_eligible"])
        self.assertFalse(out[0]["revision_90d_eligible"])
        for args in [{"provider": "other"}, {"unit": "ADR2"}, {"fiscal": "2027-12-31"}]:
            out, _ = audit_rows(["AAA"], [prior, self.snapshot(value=3, **args)], as_of=ASOF)
            self.assertFalse(out[0]["revision_30d_eligible"])

    def test_proprietary_blend_is_not_pure_analyst_consensus(self):
        out, _ = audit_rows(["AAA"], [self.snapshot(provider="finnhub")], as_of=ASOF)
        self.assertEqual(out[0]["source_state"], "BLOCKED_CONSENSUS_BASIS")
        self.assertFalse(out[0]["source_v2_eligible"])

    def test_eps_basis_block_does_not_block_finnhub_revenue(self):
        record = dict(issuer_id="issuer-A", security_id="security-A", period="2026-12-31",
                      period_type="ANNUAL", accounting_basis="GAAP", currency="USD",
                      share_or_ADR_unit="share", avg=20)
        def snap(at):
            return H1.build_snapshot("AAA", eps_payload={"data": [{**record, "avg": 2}]},
                                     revenue_payload={"data": [record]}, recommendation_payload=[],
                                     observed_at=at, collected_at=at, fetch_source="finnhub")
        out, _ = audit_rows(["AAA"], [snap("2026-09-01T08:00:00Z"), snap(ASOF)], as_of=ASOF)
        self.assertTrue(out[0]["fresh_revenue_fy1"])
        self.assertFalse(out[0]["fresh_eps_fy1"])
        self.assertFalse(out[0]["eps_revision_30d_eligible"])
        self.assertTrue(out[0]["revenue_revision_30d_eligible"])
        self.assertFalse(out[0]["research_consumer_eligible"])


if __name__ == "__main__":
    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(c)
                               for c in [CoverageFairnessTests, SourceV2CoverageTests]])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)

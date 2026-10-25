from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.trend_risk_beta_diagnostic_v1 import (
    ALL_NAMES, RISK_NAMES, TREND_NAMES, TwoAxisDiagnosticError,
    compare_snapshots, evaluate, normalize_raw_research_inputs,
)
CUTOFF = "2026-10-13T12:00:00Z"


class Fixture:
    def __init__(self):
        self.raw = {}
    def resolver(self, aid, sha):
        return self.raw[(aid, sha)]
    def packet(self, trend=0.6, risk=0.2):
        obs = {}
        for n in ALL_NAMES:
            aid = f"RAW_{n}"
            data = f"Synthetic, NOT genuine market data: {n}".encode()
            digest = hashlib.sha256(data).hexdigest()
            self.raw[(aid, digest)] = data
            row = {
                "metric_name": n,
                "normalized_value": trend if n in TREND_NAMES else risk,
                "normalized_basis": "FIXED_DEMO_V1",
                "market_id": "US", "benchmark_id": "US:SPY",
                "observation_date": "2026-10-12",
                "observed_at": "2026-10-12T20:00:00Z",
                "available_at": "2026-10-12T20:03:00Z",
                "collected_at": "2026-10-12T20:04:00Z",
                "valid_through": "2026-10-15T00:00:00Z",
                "quality": "REVIEWED_OBSERVED", "source_family": "MARKET_RAW",
                "artifact_id": aid, "sha256": digest,
            }
            if n == "breadth_trend":
                row.update(eligible_universe_count=100, valid_member_count=100,
                           cohort_coverage="COMPLETE_REVIEWED")
            obs[n] = row
        return {
            "schema": "trend-risk-two-axis-diagnostic-v1",
            "market_id": "US", "benchmark_id": "US:SPY",
            "as_of": "2026-10-12T21:00:00Z", "session_date": "2026-10-12",
            "normalization_method": "FIXED_PREREGISTERED_INPUT_SCORES",
            "normalization_version": "FIXED_DEMO_V1",
            "normalization_config_sha256": "b" * 64,
            "review_status": "RESEARCH_CONTEXT_REVIEWED",
            "observations": obs,
        }


class TrendRiskSmoke(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.packet = self.fx.packet()

    def compute(self, packet=None, cutoff=CUTOFF):
        return evaluate(self.packet if packet is None else packet, cutoff, self.fx.resolver)

    def fails(self, mutation, msg):
        p = copy.deepcopy(self.packet)
        mutation(p)
        with self.assertRaisesRegex(TwoAxisDiagnosticError, msg):
            self.compute(p)

    def test_four_quadrants_only_descriptive(self):
        for trend,risk,expected in [
            (.6,.2,"UPTREND_LOW_STRESS"), (.6,.8,"UPTREND_HIGH_STRESS"),
            (-.6,.2,"DOWNTREND_LOW_STRESS"), (-.6,.8,"DOWNTREND_HIGH_STRESS")]:
            with self.subTest(expected=expected):
                v = self.compute(self.fx.packet(trend, risk))
                self.assertEqual(v["quadrant_diagnostic"], expected)
                self.assertAlmostEqual(v["trend_score"], trend)
                self.assertAlmostEqual(v["risk_stress_score"], risk)

    def test_exposure_and_trading_authority_always_none(self):
        v = self.compute()
        for k in ("cash_weight_proposal","gross_exposure_cap","policy_action",
                  "calibrated_drawdown_probability"):
            self.assertIsNone(v[k])
        for k in ("regime_authorized", "source_authenticated", "historical_pit_certified",
                  "target_book_write_allowed", "orders_allowed", "production_authority",
                  "normalization_calibrated_oos"):
            self.assertIs(v[k], False)
        self.assertEqual(v["portfolio_weight_effect"], 0)

    def test_overlap_collapsed_within_family(self):
        p = copy.deepcopy(self.packet)
        p["observations"]["vix_stress"]["normalized_value"] = .8
        p["observations"]["realized_vol_stress"]["normalized_value"] = .6
        p["observations"]["fx_shock_stress"]["normalized_value"] = .9
        p["observations"]["rate_shock_stress"]["normalized_value"] = .1
        p["observations"]["down_volume_stress"]["normalized_value"] = .2
        p["observations"]["credit_stress"]["normalized_value"] = .3
        x = self.compute(p)
        self.assertEqual(x["risk_families"],
            {"volatility":.8, "distribution":.2, "macro_shock":.9, "credit":.3})
        self.assertAlmostEqual(x["risk_stress_score"], .55)

    def test_missing_trend_does_not_fabricate_score(self):
        p = copy.deepcopy(self.packet)
        del p["observations"]["ma_21_trend"]
        x = self.compute(p)
        self.assertIsNone(x["trend_score"])
        self.assertEqual(x["quadrant_diagnostic"],"INSUFFICIENT_INPUT")
        self.assertIn("ma_21_trend",x["missing_observations"])

    def test_missing_credit_blocks_risk_score(self):
        p = copy.deepcopy(self.packet)
        p["observations"].pop("credit_stress")
        self.assertIsNone(self.compute(p)["risk_stress_score"])

    def test_one_of_two_volatility_factors_is_sufficient(self):
        p = copy.deepcopy(self.packet)
        p["observations"].pop("realized_vol_stress")
        self.assertAlmostEqual(self.compute(p)["risk_stress_score"], .2)

    def test_zero_and_half_scores_are_not_silently_classified(self):
        for trend,risk in [(0.0,.2),(.2,.5)]:
            x=self.compute(self.fx.packet(trend,risk))
            self.assertEqual(x["quadrant_diagnostic"], "BOUNDARY_REVIEW")

    def test_bool_infinite_out_of_range_are_rejected(self):
        for x in (True, float("nan"), float("inf"), 1.2, -1.2, "0.5"):
            with self.subTest(value=str(x)):
                self.fails(lambda p: p["observations"]["ma_21_trend"].update(normalized_value=x),
                           "normalized_score")

    def test_negative_risk_rejected(self):
        self.fails(lambda p: p["observations"]["credit_stress"].update(normalized_value=-.1),
                   "normalized_score_range")

    def test_future_producer_clock(self):
        self.fails(lambda p: p["observations"]["vix_stress"].update(available_at="2026-11-01T00:00:00Z"),
                   "observation_clock_or_expiry")

    def test_expired_observation(self):
        self.fails(lambda p: p["observations"]["vix_stress"].update(valid_through="2026-10-11T23:00:00Z"),
                   "observation_clock_or_expiry")

    def test_unreviewed_or_partial_breadth_refused(self):
        self.fails(lambda p: p["observations"]["breadth_trend"].update(cohort_coverage="PARTIAL"),
                   "breadth_scope_incomplete")
        self.fails(lambda p: p["observations"]["breadth_trend"].update(valid_member_count=101),
                   "breadth_denominator")
        self.fails(lambda p: p["observations"]["breadth_trend"].update(quality="INFERRED"),
                   "unreviewed_observation")

    def test_normalization_mismatch(self):
        self.fails(lambda p: p["observations"]["ma_21_trend"].update(normalized_basis="UNVERIFIED"),
                   "normalization_version_mismatch")

    def test_benchmark_mismatch(self):
        self.fails(lambda p: p["observations"]["ma_21_trend"].update(benchmark_id="US:QQQ"),
                   "benchmark_identity_mismatch")

    def test_hash_mismatch(self):
        key = self.packet["observations"]["vix_stress"]
        self.fx.raw[(key["artifact_id"],key["sha256"])] = b"CORRUPTION"
        with self.assertRaisesRegex(TwoAxisDiagnosticError,"observation_raw_hash"):
            self.compute()

    def test_provider_exception_redacted(self):
        self.fx.raw.clear()
        with self.assertRaisesRegex(TwoAxisDiagnosticError, "observation_raw_unavailable"):
            self.compute()

    def test_future_asof_and_session(self):
        with self.assertRaisesRegex(TwoAxisDiagnosticError, "future_packet"):
            self.compute(cutoff="2026-10-12T20:00:00Z")
        self.fails(lambda p: p.update(session_date="2026-10-13"),"future_session")

    def test_deterministic_no_input_mutation(self):
        old = copy.deepcopy(self.packet)
        self.assertEqual(self.compute(), self.compute())
        self.assertEqual(self.packet, old)

    def test_compare_change_requires_same_normalizer_market_and_time(self):
        first = self.compute()
        p = self.fx.packet(trend=-.4,risk=.8)
        p["as_of"] = "2026-10-13T21:00:00Z"
        p["session_date"] = "2026-10-13"
        for row in p["observations"].values():
            row["observation_date"] = "2026-10-13"
            row["observed_at"] = "2026-10-13T20:00:00Z"
            row["available_at"] = "2026-10-13T20:03:00Z"
            row["collected_at"] = "2026-10-13T20:04:00Z"
        last = self.compute(p, "2026-10-14T12:00:00Z")
        delta=compare_snapshots(first,last)
        self.assertAlmostEqual(delta["risk_change"], .6)
        self.assertAlmostEqual(delta["trend_change"], -1.0)
        self.assertIsNone(delta["risk_acceleration"])
        with self.assertRaisesRegex(TwoAxisDiagnosticError,"comparison_time_order"):
            compare_snapshots(last,first)
        last["normalization_version"] = "REVISED"
        with self.assertRaisesRegex(TwoAxisDiagnosticError,"comparison_context_drift"):
            compare_snapshots(first,last)

    def test_pure_raw_normalizer_fixed_not_fitted(self):
        raw = {
            "price_to_ma21_ratio": 1.05, "price_to_ma63_ratio": .95,
            "price_to_ma126_ratio": 1.2, "drawdown_252_fraction": -.1,
            "global_relative_log_return_63": .03,
            "breadth_fraction_above_ma200": .7,
            "down_volume_fraction": .6,
            "vix_stress_percentile": .6, "credit_stress_percentile": .8,
        }
        scales = {"ma_ratio_saturation": .1, "drawdown_depth_fraction": .2,
                  "global_rs_log_saturation": .1}
        old = copy.deepcopy(raw)
        normalized = normalize_raw_research_inputs(raw, scales)
        self.assertAlmostEqual(normalized["ma_21_trend"], .5)
        self.assertAlmostEqual(normalized["ma_63_trend"], -.5)
        self.assertEqual(normalized["ma_126_trend"], 1.0)
        self.assertAlmostEqual(normalized["drawdown_252_trend"], 0)
        self.assertAlmostEqual(normalized["global_relative_trend"], .3)
        self.assertAlmostEqual(normalized["breadth_trend"], .4)
        self.assertAlmostEqual(normalized["down_volume_stress"], .2)
        self.assertEqual(normalized["credit_stress"], .8)
        self.assertEqual(raw, old)
        self.assertNotIn("fx_shock_stress", normalized)

    def test_pure_normalizer_rejects_bad_scales_and_inputs(self):
        scales = {"ma_ratio_saturation": .1, "drawdown_depth_fraction": .2,
                  "global_rs_log_saturation": .1}
        for s in (0, -1, float("nan"), "0.1"):
            with self.subTest(scale=str(s)), self.assertRaises(TwoAxisDiagnosticError):
                normalize_raw_research_inputs({"price_to_ma21_ratio": 1.01},
                    {**scales, "ma_ratio_saturation": s})
        for bad in (True, float("nan"), 1.1):
            with self.subTest(bad=str(bad)), self.assertRaises(TwoAxisDiagnosticError):
                normalize_raw_research_inputs({"breadth_fraction_above_ma200": bad}, scales)

    def test_comparison_refuses_missing_score(self):
        first=self.compute()
        bad=copy.deepcopy(first)
        bad["risk_stress_score"] = None
        with self.assertRaisesRegex(TwoAxisDiagnosticError,"comparison_incomplete"):
            compare_snapshots(first,bad)


if __name__ == "__main__":
    unittest.main()

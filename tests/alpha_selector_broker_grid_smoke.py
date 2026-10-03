#!/usr/bin/env python3
"""Smoke checks for alpha selector broker grid."""
from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_alpha_selector_broker_grid import run  # noqa: E402
from tools import run_alpha_selector_broker_grid as grid  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402
from tools.run_broker_ledger_replay import REPLAY_GENERATED_ARTIFACTS  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    ).to_parquet(cache_dir / px_cache_name(ticker))


def test_alpha_selector_grid_runs_broker_replay_without_forward_selection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "alpha_grid"
        cache.mkdir()
        _write_px(cache, "AAA", [100, 101, 102, 103, 104, 105])
        _write_px(cache, "BBB", [50, 51, 52, 53, 54, 55])
        _write_px(cache, "LEAK", [10, 9, 8, 7, 6, 5])
        candidate = root / "candidate_replay_book.csv"
        rows = []
        for dt in ["2026-01-02", "2026-01-05"]:
            rows.extend(
                [
                    {
                        "rebalance_date": dt,
                        "ticker": "AAA",
                        "Name": "Leader A",
                        "sector": "Tech",
                        "score": 9.0,
                        "portfolio_sleeve_label": "future_winner",
                        "portfolio_candidate_gate_label": "future_relaxed",
                        "portfolio_future_winner_engine_score": 0.95,
                        "portfolio_early_scout_engine_score": 0.85,
                        "portfolio_monster_early_score": 0.80,
                        "h6_dynamic_leader_score": 0.75,
                        "rs_acceleration_score": 0.60,
                        "industry_group_strength_score": 0.50,
                        "selection_market_confirmation_score": 0.80,
                        "entry_quality_score": 0.70,
                        "early_evidence_score": 0.90,
                        "evidence_confidence_score": 0.80,
                        "institutional_evidence_score": 0.70,
                        "institutional_evidence_confidence_score": 0.80,
                        "etf_holdings_score": 0.60,
                        "etf_evidence_confidence": 0.70,
                        "sec_combined_evidence_score": 0.75,
                        "smart_money_shadow_score": 0.85,
                        "smart_money_evidence_source_count": 3,
                        "evidence_fusion_score": 0.82,
                        "leader_onset_sec_v2_score": 0.95,
                        "leader_onset_sec_v3_score": 0.95,
                        "portfolio_risk_entry_block_score": 0.0,
                        "portfolio_stale_mega_leader_score": 0.0,
                        "px": 100.0,
                        "dollar_vol_20d": 50_000_000,
                        "mktcap": 5_000_000_000,
                        "period_forward_return": 0.10,
                    },
                    {
                        "rebalance_date": dt,
                        "ticker": "BBB",
                        "Name": "Leader B",
                        "sector": "Tech",
                        "score": 8.0,
                        "portfolio_sleeve_label": "early_scout",
                        "portfolio_candidate_gate_label": "early_relaxed",
                        "portfolio_future_winner_engine_score": 0.15,
                        "portfolio_early_scout_engine_score": 0.10,
                        "portfolio_monster_early_score": 0.10,
                        "h6_dynamic_leader_score": 0.10,
                        "rs_acceleration_score": 0.05,
                        "industry_group_strength_score": 0.05,
                        "selection_market_confirmation_score": 0.20,
                        "entry_quality_score": 0.20,
                        "early_evidence_score": 0.00,
                        "evidence_confidence_score": 0.00,
                        "institutional_evidence_score": 0.00,
                        "institutional_evidence_confidence_score": 0.00,
                        "etf_holdings_score": 0.00,
                        "etf_evidence_confidence": 0.00,
                        "sec_combined_evidence_score": 0.00,
                        "smart_money_shadow_score": 0.00,
                        "smart_money_evidence_source_count": 0,
                        "evidence_fusion_score": 0.00,
                        "leader_onset_sec_v2_score": 0.10,
                        "leader_onset_sec_v3_score": 0.10,
                        "portfolio_risk_entry_block_score": 0.0,
                        "portfolio_stale_mega_leader_score": 0.0,
                        "px": 50.0,
                        "dollar_vol_20d": 40_000_000,
                        "mktcap": 4_000_000_000,
                        "period_forward_return": 0.08,
                    },
                    {
                        "rebalance_date": dt,
                        "ticker": "LEAK",
                        "Name": "Forward Label Only",
                        "sector": "Tech",
                        "score": 0.1,
                        "portfolio_sleeve_label": "unassigned",
                        "portfolio_candidate_gate_label": "rejected",
                        "portfolio_future_winner_engine_score": 0.0,
                        "portfolio_early_scout_engine_score": 0.0,
                        "portfolio_monster_early_score": 0.0,
                        "h6_dynamic_leader_score": 0.0,
                        "rs_acceleration_score": 0.0,
                        "industry_group_strength_score": 0.0,
                        "selection_market_confirmation_score": 0.0,
                        "entry_quality_score": 0.0,
                        "early_evidence_score": 0.0,
                        "evidence_confidence_score": 0.0,
                        "institutional_evidence_score": 0.0,
                        "institutional_evidence_confidence_score": 0.0,
                        "etf_holdings_score": 0.0,
                        "etf_evidence_confidence": 0.0,
                        "sec_combined_evidence_score": 0.0,
                        "smart_money_shadow_score": 0.0,
                        "smart_money_evidence_source_count": 0,
                        "evidence_fusion_score": 0.0,
                        "leader_onset_sec_v2_score": 0.0,
                        "leader_onset_sec_v3_score": 0.0,
                        "portfolio_risk_entry_block_score": 0.0,
                        "portfolio_stale_mega_leader_score": 0.0,
                        "px": 10.0,
                        "dollar_vol_20d": 100_000_000,
                        "mktcap": 10_000_000_000,
                        "period_forward_return": 9.99,
                    },
                    {
                        "rebalance_date": dt,
                        "ticker": "MISS",
                        "Name": "Missing Price Cache",
                        "sector": "Tech",
                        "score": 10.0,
                        "portfolio_sleeve_label": "future_winner",
                        "portfolio_candidate_gate_label": "future_relaxed",
                        "portfolio_future_winner_engine_score": 1.0,
                        "portfolio_early_scout_engine_score": 1.0,
                        "portfolio_monster_early_score": 1.0,
                        "h6_dynamic_leader_score": 1.0,
                        "rs_acceleration_score": 1.0,
                        "industry_group_strength_score": 1.0,
                        "selection_market_confirmation_score": 1.0,
                        "entry_quality_score": 1.0,
                        "early_evidence_score": 1.0,
                        "evidence_confidence_score": 1.0,
                        "institutional_evidence_score": 1.0,
                        "institutional_evidence_confidence_score": 1.0,
                        "etf_holdings_score": 1.0,
                        "etf_evidence_confidence": 1.0,
                        "sec_combined_evidence_score": 1.0,
                        "smart_money_shadow_score": 1.0,
                        "smart_money_evidence_source_count": 3,
                        "evidence_fusion_score": 1.0,
                        "leader_onset_sec_v2_score": 1.0,
                        "leader_onset_sec_v3_score": 1.0,
                        "portfolio_risk_entry_block_score": 0.0,
                        "portfolio_stale_mega_leader_score": 0.0,
                        "px": 20.0,
                        "dollar_vol_20d": 100_000_000,
                        "mktcap": 20_000_000_000,
                        "period_forward_return": 99.99,
                    },
                ]
            )
        pd.DataFrame(rows).to_csv(candidate, index=False)
        payload = run(
            argparse.Namespace(
                candidate_book=str(candidate),
                price_cache=str(cache),
                output_dir=str(out),
                portfolio_kind="main",
                starting_capital=10_000.0,
                fill_mode="next_close",
                cost_bps=0.0,
                no_integer_shares=False,
                max_fill_lag_days=7,
                styles="future_heavy,future_winner_smart_money,leader_onset_shadow,sec_evidence_shadow,smart_money_shadow",
                target_ns="1",
                single_name_caps="1.00",
                max_variants=5,
                min_market_cap_usd=1_000_000_000.0,
                min_dollar_volume_usd=1_000_000.0,
                min_price=5.0,
            )
        )
        assert payload["status"] == "completed"
        assert payload["valid_for_production"] is True
        summary = pd.read_csv(out / "summary.csv")
        assert len(summary) == 5
        targets = pd.read_csv(next(out.glob("future_heavy_N1_cap*/target_book.csv")))
        assert set(targets["ticker"]) == {"AAA"}
        assert float(targets["weight"].max()) > 0.99
        assert "BBB" not in set(targets["ticker"])
        assert "LEAK" not in set(targets["ticker"])
        assert "MISS" not in set(targets["ticker"])
        confirm_targets = pd.read_csv(next(out.glob("future_winner_smart_money_N1_cap*/target_book.csv")))
        assert set(confirm_targets["ticker"]) == {"AAA"}
        assert "smart_money_shadow_score" in confirm_targets.columns
        assert "evidence_fusion_score" in confirm_targets.columns
        onset_targets = pd.read_csv(next(out.glob("leader_onset_shadow_N1_cap*/target_book.csv")))
        assert set(onset_targets["ticker"]) == {"AAA"}
        assert "leader_onset_score" in onset_targets.columns
        sec_targets = pd.read_csv(next(out.glob("sec_evidence_shadow_N1_cap*/target_book.csv")))
        assert set(sec_targets["ticker"]) == {"AAA"}
        assert "leader_onset_sec_v2_score" in sec_targets.columns
        assert "early_evidence_score" in sec_targets.columns
        smart_targets = pd.read_csv(next(out.glob("smart_money_shadow_N1_cap*/target_book.csv")))
        assert set(smart_targets["ticker"]) == {"AAA"}
        assert "smart_money_shadow_score" in smart_targets.columns
        assert "evidence_fusion_score" in smart_targets.columns
        assert payload.get("require_price_cache") is True


class BlockedGridResultChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / "out"
        self.args = argparse.Namespace(candidate_book=str(self.root / "candidates.csv"), price_cache=str(self.root),
            output_dir=str(self.out), portfolio_kind="main", starting_capital=10000., fill_mode="next_open",
            cost_bps=25., no_integer_shares=False, max_fill_lag_days=7, target_ns="1", single_name_caps="1",
            styles="future_heavy", max_variants=1, min_market_cap_usd=0., min_dollar_volume_usd=0.,
            min_price=0., allow_unfillable_targets=True)
        self.target = pd.DataFrame([{"ticker": "AAA", "rebalance_date": "2024-01-02", "weight": 1.}])

    def invoke(self, metrics, *, empty=False):
        with patch.object(grid, "read_csv", return_value=self.target), \
             patch.object(grid, "prepare_candidates", return_value=pd.DataFrame() if empty else self.target), \
             patch.object(grid, "build_target_book", return_value=self.target), \
             patch.object(grid, "broker_replay", return_value=dict(metrics)):
            return grid.run(self.args)

    def test_blocked_rows_preserve_do_not_use_and_never_show_zero_performance(self):
        result = self.invoke({"status": "blocked", "reason": "next_open_precommitted_order_intent_unavailable",
            "metric_mode": "DO_NOT_USE", "valid_for_production": False, "cagr": .99, "max_dd": -.4, "sharpe": 9.})
        self.assertEqual(result["status"], "blocked")
        variant = next(self.out.glob("*/metrics.json"))
        metrics = json.loads(variant.read_text(encoding="utf-8"))
        self.assertEqual(metrics["metric_mode"], "DO_NOT_USE")
        for field in ("cagr", "max_dd", "sharpe"):
            self.assertIsNone(metrics.get(field))
        rows = pd.read_csv(self.out / "summary.csv")
        self.assertTrue(rows[["cagr", "max_dd", "sharpe"]].isna().all().all())
        report = (self.out / "report.md").read_text(encoding="utf-8")
        self.assertIn("blocked", report)
        self.assertIn("N/A", report)
        self.assertNotIn("0.00%", report)

    def test_unknown_nonfinite_or_redacted_completed_variants_cannot_be_selected(self):
        completed = {"status": "completed", "valid_for_production": True, "cagr": .1, "max_dd": -.1, "sharpe": 1.}
        cases = [{**completed, "status": status} for status in (None, "unknown", "blocked")]
        cases += [{**completed, field: value} for field in ("cagr", "max_dd", "sharpe")
                  for value in (None, True, float("nan"), float("inf"))]
        cases += [{**completed, "metric_mode": "DO_NOT_USE"}, {**completed, "performance_fields_redacted": True}]
        for metrics in cases:
            with self.subTest(metrics=metrics):
                result = self.invoke(metrics)
                self.assertEqual(result["status"], "blocked")
                self.assertFalse(result["valid_for_production"])

    def test_reused_root_summaries_clear_before_late_or_early_block_preserving_caller_files(self):
        completed = {"status": "completed", "valid_for_production": True, "cagr": .1, "max_dd": -.1, "sharpe": 1.}
        self.assertEqual(self.invoke(completed)["status"], "completed")
        caller, nested = self.out / "caller.json", self.out / "archive" / "best_target_distance_metrics.json"
        nested.parent.mkdir()
        caller.write_bytes(b"caller")
        nested.write_bytes(b"archive")
        for empty in (False, True):
            with self.subTest(empty=empty):
                result = self.invoke({"status": "blocked", "metric_mode": "DO_NOT_USE"}, empty=empty)
                self.assertEqual(result["status"], "blocked")
                self.assertFalse((self.out / "best_target_distance_metrics.json").exists())
                self.assertEqual(json.loads((self.out / "best_metrics.json").read_text(encoding="utf-8"))["status"], "blocked")
                if empty: self.assertFalse((self.out / "summary.csv").exists())
                self.assertEqual(caller.read_bytes(), b"caller")
                self.assertEqual(nested.read_bytes(), b"archive")

    def test_cli_status_fails_closed_and_preserves_completed_exit(self):
        for status, expected in (("blocked", 2), (None, 2), ("unknown", 2), ("completed", 0)):
            with self.subTest(status=status), patch.object(grid, "parse_args", return_value=self.args), \
                 patch.object(grid, "run", return_value={"status": status}), redirect_stdout(io.StringIO()):
                self.assertEqual(grid.main(), expected)


class GridInputPreservationChecks(unittest.TestCase):
    root_exports = ("summary.csv", "best_metrics.json", "best_target_distance_metrics.json", "report.md")
    variant_exports = ("target_book.csv", *REPLAY_GENERATED_ARTIFACTS)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.cache = self.root / "cache"; self.cache.mkdir()
        _write_px(self.cache, "AAA", [100., 102., 101., 105.])
        self.frame = pd.DataFrame([{"rebalance_date": date, "ticker": "AAA", "score_total": 1.,
            "portfolio_future_winner_engine_score": 1., "market_cap_live": 1e10,
            "dollar_vol_20d": 1e8, "px": 100.} for date in ("2026-01-02", "2026-01-05")])
        self.out = self.root / "out"
        self.args = argparse.Namespace(candidate_book=str(self.root / "candidates.csv"), price_cache=str(self.cache),
            output_dir=str(self.out), portfolio_kind="main", starting_capital=10000., fill_mode="next_close",
            cost_bps=25., no_integer_shares=False, max_fill_lag_days=7, target_ns="1", single_name_caps="1",
            styles="future_heavy", max_variants=1, min_market_cap_usd=0., min_dollar_volume_usd=0.,
            min_price=0., allow_unfillable_targets=True)

    def check_collision(self, source, owned):
        source.parent.mkdir(parents=True, exist_ok=True); self.frame.to_csv(source, index=False)
        before = source.read_bytes(); self.args.candidate_book = str(source)
        caller = self.out / "caller.txt"; caller.parent.mkdir(parents=True, exist_ok=True); caller.write_bytes(b"caller")
        for path in owned:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.resolve() != source.resolve(): path.write_bytes(b"old successful export")
        result = grid.run(self.args)
        self.assertEqual(result["status"], "blocked"); self.assertEqual(result.get("metric_mode"), "DO_NOT_USE")
        self.assertEqual(result["reason"], "caller_input_collides_with_replay_output")
        self.assertEqual(source.read_bytes(), before); self.assertEqual(caller.read_bytes(), b"caller")
        for path in owned:
            if path.resolve() != source.resolve() and path.name not in ("best_metrics.json", "report.md"):
                self.assertFalse(path.exists(), str(path))
        with patch.object(grid, "parse_args", return_value=self.args), redirect_stdout(io.StringIO()):
            self.assertEqual(grid.main(), 2)
        self.assertEqual(source.read_bytes(), before)

    def test_all_root_and_requested_variant_exports_preserve_valid_csv_in_all_modes(self):
        for mode in ("next_close", "same_close", "next_open"):
            self.args.fill_mode = mode
            for folder, names in ((self.out, self.root_exports),
                    (self.out / "future_heavy_N1_cap1.0", self.variant_exports)):
                owned = [self.out / name for name in self.root_exports] + [folder / name for name in names]
                for name in names:
                    with self.subTest(mode=mode, folder=folder.name, name=name):
                        self.check_collision(folder / name, owned)

    def test_collision_precedes_candidate_and_broker_reads(self):
        source = self.out / "future_heavy_N1_cap1.0" / "equity_curve.csv"
        source.parent.mkdir(parents=True); self.frame.to_csv(source, index=False); self.args.candidate_book = str(source)
        with patch.object(grid, "read_csv", side_effect=AssertionError("must not read collided input")), \
             patch.object(grid, "broker_replay", side_effect=AssertionError("must not replay")):
            self.assertEqual(grid.run(self.args)["status"], "blocked")

    def test_nonrequested_variant_nested_and_same_basename_inputs_remain_completed(self):
        for source in (self.out / "archive" / "best_metrics.json", self.out / "future_heavy_N2_cap1.0" / "target_book.csv",
                       self.root / "sibling" / "report.md", self.out / "caller.csv"):
            with self.subTest(source=source):
                source.parent.mkdir(parents=True, exist_ok=True); self.frame.to_csv(source, index=False)
                before = source.read_bytes(); self.args.candidate_book = str(source)
                self.assertEqual(grid.run(self.args)["status"], "completed")
                self.assertEqual(source.read_bytes(), before)


def main() -> int:
    test_alpha_selector_grid_runs_broker_replay_without_forward_selection()
    if not unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(
            unittest.defaultTestLoader.loadTestsFromTestCase(cls)
            for cls in (BlockedGridResultChecks, GridInputPreservationChecks))).wasSuccessful():
        return 1
    print("alpha_selector_broker_grid_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

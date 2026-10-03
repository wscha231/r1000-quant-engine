#!/usr/bin/env python3
"""Smoke checks for SEC evidence learning pipeline orchestration."""
from __future__ import annotations

import argparse
import io
import json
import socket
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_sec_evidence_learning_pipeline import run  # noqa: E402
from tools import run_sec_evidence_learning_pipeline as learning  # noqa: E402
from tools import run_post_disclosure_overlay_challenger as overlay  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402
from tools.run_broker_ledger_replay import REPLAY_GENERATED_ARTIFACTS  # noqa: E402


def candidate_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    dates = ["2026-05-12", "2026-05-13", "2026-05-15"]
    for dt in dates:
        for i in range(30):
            ticker = "AAPL" if i == 0 else f"T{i:02d}"
            base = 1.0 - i / 40.0
            rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "Name": "Apple Inc." if ticker == "AAPL" else f"Ticker {i}",
                    "score_total": base,
                    "portfolio_future_winner_engine_score": base,
                    "selection_market_confirmation_score": base * 0.8,
                    "industry_group_strength_score": base * 0.7,
                    "rs_acceleration_score": base * 0.6,
                    "entry_quality_score": base * 0.5,
                    "market_cap_live": 3_000_000_000_000.0 if ticker == "AAPL" else 10_000_000_000.0,
                    "period_forward_return": 0.18 if ticker == "AAPL" else (0.06 - i * 0.002),
                }
            )
    return rows


def form4_rows() -> list[dict[str, object]]:
    return [
        {
            "issuer_ticker": "AAPL",
            "issuer_cik10": "0000320193",
            "reporting_owner_cik": "0001111111",
            "reporting_owner_name": "Example CEO",
            "officer_title": "Chief Executive Officer",
            "is_director": True,
            "is_officer": True,
            "is_ten_percent_owner": False,
            "transaction_date": "2026-05-10",
            "filing_date": "2026-05-12",
            "accepted_at": "2026-05-13T00:00:00+00:00",
            "available_from": "2026-05-13T00:00:00+00:00",
            "transaction_code": "P",
            "transaction_shares": 1000.0,
            "transaction_price": 100.0,
            "transaction_value": 100000.0,
            "ownership_nature": "",
            "direct_or_indirect": "D",
            "shares_owned_after": 5000.0,
            "is_derivative": False,
            "security_title": "Common Stock",
            "accession_number": "0000320193-26-000001",
            "filing_url": "https://www.sec.gov/example.xml",
        }
    ]


def thirteen_f_rows() -> list[dict[str, object]]:
    return [
        {
            "manager_cik": "0001067983",
            "manager_name": "Example Manager",
            "report_period": "2025-12-31",
            "filing_date": "2026-02-14",
            "accepted_at": "2026-02-14T18:00:00+00:00",
            "available_from": "2026-02-14T18:00:00+00:00",
            "cusip": "037833100",
            "issuer_name": "APPLE INC",
            "title_of_class": "COM",
            "ticker_mapped": "AAPL",
            "shares": 100000.0,
            "share_type": "SH",
            "market_value_usd": 10_000_000.0,
            "put_call": "",
            "investment_discretion": "SOLE",
            "other_manager": "",
            "voting_authority_sole": 100000.0,
            "voting_authority_shared": 0.0,
            "voting_authority_none": 0.0,
            "source_accession": "0001067983-26-000001",
            "filing_url": "https://www.sec.gov/example-13f.xml",
        },
        {
            "manager_cik": "0001067983",
            "manager_name": "Example Manager",
            "report_period": "2026-03-31",
            "filing_date": "2026-05-15",
            "accepted_at": "2026-05-15T18:00:00+00:00",
            "available_from": "2026-05-15T18:00:00+00:00",
            "cusip": "037833100",
            "issuer_name": "APPLE INC",
            "title_of_class": "COM",
            "ticker_mapped": "AAPL",
            "shares": 180000.0,
            "share_type": "SH",
            "market_value_usd": 18_000_000.0,
            "put_call": "",
            "investment_discretion": "SOLE",
            "other_manager": "",
            "voting_authority_sole": 180000.0,
            "voting_authority_shared": 0.0,
            "voting_authority_none": 0.0,
            "source_accession": "0001067983-26-000002",
            "filing_url": "https://www.sec.gov/example-13f-2.xml",
        },
    ]


def etf_rows() -> list[dict[str, object]]:
    return [
        {
            "etf_ticker": "AIQ",
            "etf_label": "AI ETF",
            "theme": "ai_infra",
            "holding_ticker": "AAPL",
            "holding_name": "Apple Inc.",
            "holding_weight": 0.08,
            "source": "fixture",
            "as_of_date": "2026-05-13T00:00:00+00:00",
            "available_from": "2026-05-13T00:00:00+00:00",
        }
    ]


def test_sec_evidence_learning_pipeline_outputs_research_artifacts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate = root / "candidate.csv"
        form4 = root / "form4.parquet"
        holdings_13f = root / "13f.parquet"
        etf_holdings = root / "etf.parquet"
        out = root / "learning"
        pd.DataFrame(candidate_rows()).to_csv(candidate, index=False)
        pd.DataFrame(form4_rows()).to_parquet(form4, index=False)
        pd.DataFrame(thirteen_f_rows()).to_parquet(holdings_13f, index=False)
        pd.DataFrame(etf_rows()).to_parquet(etf_holdings, index=False)

        payload = run(
            argparse.Namespace(
                candidate_book=str(candidate),
                form4=str(form4),
                institutional_13f=str(holdings_13f),
                etf_holdings=str(etf_holdings),
                price_cache=str(root / "cache_prices"),
                output_dir=str(out),
                form4_lookback_days=90,
                institutional_lookback_days=210,
                top_n=5,
                run_broker_grid=False,
                starting_capital=100000.0,
                fill_mode="next_close",
                cost_bps=25.0,
                max_fill_lag_days=7,
                styles="sec_evidence_shadow",
                target_ns="1",
                single_name_caps="1.0",
                max_variants=1,
                min_market_cap_usd=0.0,
                min_dollar_volume_usd=0.0,
                min_price=0.0,
                allow_unfillable_targets=True,
            )
        )

        assert payload["status"] == "completed"
        assert payload["research_only"] is True
        assert payload["production_activation_allowed"] is False
        assert payload["enriched_rows"] == 90
        assert payload["rows_with_form4_evidence"] > 0
        assert payload["rows_with_13f_evidence"] > 0
        assert payload["rows_with_etf_evidence"] > 0
        assert payload["rows_with_smart_money_evidence"] > 0
        assert payload["score_learning"]["status"] == "completed"
        enriched = pd.read_csv(out / "candidate_replay_book_sec_enriched.csv")
        assert "leader_onset_sec_v3_score" in enriched.columns
        assert "smart_money_shadow_score" in enriched.columns
        assert "score_total" in enriched.columns
        assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["promotion_allowed"] is False
        assert (out / "score_weight_grid.csv").exists()
        assert (out / "selection_quality" / "selection_quality_summary.json").exists()


class NestedGridStatusAndInputChecks(unittest.TestCase):
    """Actual enrichment/grid/replay; only score fitting stages are synthetic receipts."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.cache = self.root / "cache"; self.cache.mkdir()
        self.candidate = self.root / "candidates.csv"
        rows = [{"ticker": "AAA", "rebalance_date": date, "score_total": 1.,
            "portfolio_future_winner_engine_score": 1., "market_cap_live": 1e10,
            "dollar_vol_20d": 1e8, "px": 100.} for date in ("2026-01-02", "2026-01-05")]
        self.rows = pd.DataFrame(rows); self.rows.to_csv(self.candidate, index=False)
        dates = pd.bdate_range("2026-01-02", periods=4)
        pd.DataFrame({"Open": [100., 102., 101., 105.], "Close": [100., 102., 101., 105.],
            "Adj Close": [100., 102., 101., 105.]}, index=dates).to_parquet(self.cache / px_cache_name("AAA"))
        self.events = self.root / "events.csv"; self.events.write_text("ticker\n", encoding="utf-8")
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(socket.socket, "connect", side_effect=AssertionError("no network")))
        synthetic = {"status": "completed", "research_only": True, "production_activation_allowed": False,
            "fixture_scope": "synthetic prerequisite receipt; no score fit performed"}
        self.stack.enter_context(patch.object(learning, "run_selection_quality", return_value=dict(synthetic)))
        self.stack.enter_context(patch.object(learning, "learn_score_weights", return_value=dict(synthetic)))

    def args(self, module, **changes):
        values = dict(candidate_book=str(self.candidate), price_cache=str(self.cache), output_dir=str(self.root / module.__name__.split(".")[-1]),
            form4=str(self.events), institutional_13f=str(self.events), etf_holdings=str(self.events),
            events_13f=str(self.events), events_form4=str(self.events), events_etf=str(self.events),
            form4_lookback_days=90, institutional_lookback_days=210, lookback_days=120, top_n=1,
            run_broker_grid=True, portfolio_kinds="main,concentrated", starting_capital=10000., fill_mode="next_close",
            cost_bps=25., max_fill_lag_days=7, styles="future_heavy", target_ns="1", single_name_caps="1",
            main_target_ns="1", concentrated_target_ns="1", main_single_name_caps="1", concentrated_single_name_caps="1",
            max_variants=1, min_market_cap_usd=0., min_dollar_volume_usd=0., min_price=0., allow_unfillable_targets=True)
        values.update(changes); return argparse.Namespace(**values)

    def invoke(self, module, args):
        with redirect_stdout(io.StringIO()): return module.run(args)

    def check_blocked(self, module, args):
        payload = self.invoke(module, args)
        self.assertEqual(payload["status"], "blocked"); self.assertFalse(payload["production_activation_allowed"])
        broker = payload.get("broker_grid", {})
        if broker.get("portfolios"):
            self.assertEqual(broker["status"], "blocked")
            for item in broker["portfolios"].values():
                if module is learning:
                    metrics = item["metrics"]; gate = item["gate"]
                    if metrics["status"] != "completed":
                        self.assertIsNone(gate["candidate_cagr"]); self.assertIsNone(gate["candidate_max_dd"])
                        self.assertFalse(gate["beats_cagr"]); self.assertFalse(gate["beats_or_matches_mdd"])
        with patch.object(module, "parse_args", return_value=args), redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(), 2)
        return payload

    def test_actual_opening_all_and_mixed_portfolios_block_at_helper_outer_and_cli(self):
        for module in (learning, overlay):
            original = module.run_alpha_selector_grid
            for blocked_portfolio in ("all", "main", "concentrated"):
                with self.subTest(module=module.__name__, blocked=blocked_portfolio):
                    def selected(args):
                        args.fill_mode = "next_open" if blocked_portfolio in ("all", args.portfolio_kind) else "next_close"
                        return original(args)
                    with patch.object(module, "run_alpha_selector_grid", side_effect=selected):
                        self.check_blocked(module, self.args(module))

    def test_malformed_unknown_nonfinite_and_native_failures_are_bounded(self):
        for module in (learning, overlay):
            original = module.run_alpha_selector_grid
            mutations = [None, [], *[{"status": status} for status in (None, "unknown", "blocked", "skipped")],
                {"metric_mode": "DO_NOT_USE"}, {"performance_fields_redacted": True},
                *[{field: value} for field in ("cagr", "max_dd") for value in (None, True, float("nan"), float("inf"), -float("inf"))]]
            for mutation in mutations:
                with self.subTest(module=module.__name__, mutation=mutation):
                    def changed(args):
                        result = original(args)
                        if isinstance(mutation, dict): return {**result, **mutation}
                        return mutation
                    with patch.object(module, "run_alpha_selector_grid", side_effect=changed):
                        self.check_blocked(module, self.args(module))
            for error in (OSError, ValueError, RuntimeError):
                with self.subTest(module=module.__name__, error=error.__name__):
                    def failed(args):
                        original(args); raise error("PRIVATE synthetic callback detail")
                    with patch.object(module, "run_alpha_selector_grid", side_effect=failed):
                        payload = self.check_blocked(module, self.args(module))
                        self.assertNotIn("PRIVATE", json.dumps(payload))

    def test_completed_disabled_and_unavailable_optional_sharpe_positive(self):
        for module in (learning, overlay):
            for disabled in (False, True):
                with self.subTest(module=module.__name__, disabled=disabled):
                    args = self.args(module, run_broker_grid=not disabled)
                    self.assertEqual(self.invoke(module, args)["status"], "completed")
                    with patch.object(module, "parse_args", return_value=args), redirect_stdout(io.StringIO()):
                        self.assertEqual(module.main(), 0)
            original = module.run_alpha_selector_grid
            def no_sharpe(args): return {**original(args), "sharpe": None}
            with patch.object(module, "run_alpha_selector_grid", side_effect=no_sharpe):
                self.assertEqual(self.invoke(module, self.args(module))["status"], "completed")

    def test_empty_input_and_explicit_blocked_prerequisite_cannot_complete(self):
        for module in (learning, overlay):
            with self.subTest(module=module.__name__):
                self.rows.iloc[:0].to_csv(self.candidate, index=False)
                self.check_blocked(module, self.args(module)); self.rows.to_csv(self.candidate, index=False)
        for stage in ("run_selection_quality", "learn_score_weights"):
            for status in ("blocked", None, "unknown"):
                with self.subTest(stage=stage, status=status), patch.object(learning, stage, return_value={"status": status}):
                    self.check_blocked(learning, self.args(learning))

    def test_all_declared_original_inputs_against_owned_root_and_nested_writes(self):
        for module, source_fields, names in (
            (learning, ("candidate_book", "form4", "institutional_13f", "etf_holdings"),
                ("summary.json", "report.md", "candidate_replay_book_sec_enriched.csv", "enriched_latest/reports/candidate_replay_book.csv",
                 "score_weight_grid.csv", "best_score_weights.json", "selection_quality/selection_quality_summary.json")),
            (overlay, ("candidate_book", "events_13f", "events_form4", "events_etf"),
                ("summary.json", "report.md", "candidate_replay_book_post_disclosure_enriched.csv"))):
            for field in source_fields:
                for name in names:
                    with self.subTest(module=module.__name__, field=field, name=name):
                        args = self.args(module); out = Path(args.output_dir); source = out / name
                        source.parent.mkdir(parents=True, exist_ok=True)
                        if field == "candidate_book": self.rows.to_csv(source, index=False)
                        else: source.write_bytes(b"ticker\n")
                        before = source.read_bytes(); setattr(args, field, str(source))
                        with patch.object(module, "read_table", side_effect=AssertionError("guard before read")):
                            payload = self.invoke(module, args)
                        self.assertEqual(payload["status"], "blocked")
                        self.assertEqual(payload["reason"], "caller_input_collides_with_replay_output")
                        self.assertEqual(source.read_bytes(), before)
                        with patch.object(module, "parse_args", return_value=args), redirect_stdout(io.StringIO()):
                            self.assertEqual(module.main(), 2)
                        self.assertEqual(source.read_bytes(), before)

    def test_disjoint_nested_inputs_and_reused_blocked_reports_preserve_caller_files(self):
        for module in (learning, overlay):
            args = self.args(module); out = Path(args.output_dir); source = out / "archive" / "summary.json"
            source.parent.mkdir(parents=True); self.rows.to_csv(source, index=False); before = source.read_bytes()
            args.candidate_book = str(source)
            self.assertEqual(self.invoke(module, args)["status"], "completed")
            caller = out / "caller.txt"; caller.write_bytes(b"caller")
            args.fill_mode = "next_open"; self.check_blocked(module, args)
            self.assertEqual(json.loads((out / "summary.json").read_text())["status"], "blocked")
            self.assertEqual(source.read_bytes(), before); self.assertEqual(caller.read_bytes(), b"caller")

    def test_original_inputs_are_protected_from_known_dependent_stage_outputs(self):
        for module, fields in ((learning, ("candidate_book", "form4", "institutional_13f", "etf_holdings")),
                               (overlay, ("candidate_book", "events_13f", "events_form4", "events_etf"))):
            names = [f"alpha_selector_broker_grid/{portfolio}/{name}" for portfolio in ("main", "concentrated")
                     for name in ("summary.csv", "best_metrics.json", "best_target_distance_metrics.json", "report.md",
                        *("future_heavy_N1_cap1.0/" + leaf for leaf in ("target_book.csv", *REPLAY_GENERATED_ARTIFACTS)))]
            if module is learning:
                names += ["selection_quality/" + name for name in ("selection_quality_summary.json", "selection_quality_report.md",
                    "factor_ic_by_horizon.csv", "topk_forward_hit_rate.csv", "score_decile_spread.csv",
                    "sleeve_alpha_attribution.csv", "missed_winner_onset.csv")]
            for field in fields:
                for name in names:
                    with self.subTest(module=module.__name__, field=field, name=name):
                        args = self.args(module); source = Path(args.output_dir) / name
                        source.parent.mkdir(parents=True, exist_ok=True)
                        if field == "candidate_book": self.rows.to_csv(source, index=False)
                        else: source.write_bytes(b"ticker\n")
                        before = source.read_bytes(); setattr(args, field, str(source))
                        with patch.object(module, "read_table", side_effect=AssertionError("guard before read")):
                            payload = self.invoke(module, args)
                        self.assertEqual(payload["status"], "blocked")
                        self.assertEqual(payload["reason"], "caller_input_collides_with_replay_output")
                        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    test_sec_evidence_learning_pipeline_outputs_research_artifacts()
    if not unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(NestedGridStatusAndInputChecks)).wasSuccessful():
        raise SystemExit(1)
    print("sec_evidence_learning_pipeline_smoke: PASS")

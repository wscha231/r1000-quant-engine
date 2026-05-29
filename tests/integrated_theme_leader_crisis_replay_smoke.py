#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_weekly_evaluation import px_cache_name  # noqa: E402
from tools.run_integrated_theme_leader_crisis_replay import (  # noqa: E402
    build_multi_lane_book,
    case_failure_reasons,
    enrich_ab_matrix,
)


def write_price(cache: Path, ticker: str, start: float, daily_ret: float) -> None:
    dates = pd.bdate_range("2025-01-02", "2025-08-29", freq="B")
    values = [start * ((1.0 + daily_ret) ** i) for i in range(len(dates))]
    pd.DataFrame({"date": dates, "Adj Close": values, "Close": values, "Open": values}, index=dates).to_parquet(cache / px_cache_name(ticker))


def candidate_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for dt in ("2025-03-31", "2025-04-30", "2025-05-30", "2025-06-30"):
        for ticker, rs, lane_hint in [
            ("DUAL", 0.25, "leader"),
            ("RKLB", 0.35, "emerging"),
            ("QUAL", 0.05, "quality"),
            ("CYCL", 0.12, "cyclical"),
        ]:
            rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "Name": ticker,
                    "sector": "Technology" if ticker != "QUAL" else "Health Care",
                    "industry_group": "Technology",
                    "subindustry": "Technology",
                    "score": 1.0,
                    "rs_benchmark_3m": rs,
                    "rs_benchmark_6m": rs,
                    "relative_strength_composite": rs,
                    "industry_group_strength_score": rs,
                    "industry_within_leader_rank": rs,
                    "oneil_leadership_score": rs,
                    "sub_industry_rs_score": rs,
                    "industry_leader_gap": rs,
                    "portfolio_future_winner_engine_score": 1.0,
                    "portfolio_early_scout_engine_score": 1.0 if lane_hint == "emerging" else 0.0,
                    "portfolio_monster_early_score": 1.0 if lane_hint == "emerging" else 0.0,
                    "theme_phase_primary": "emerging" if lane_hint == "emerging" else "confirmed",
                    "theme_phase_multiplier_primary": 1.5 if lane_hint == "emerging" else 1.0,
                    "dollar_vol_20d": 100_000_000,
                    "market_cap_live": 5_000_000_000,
                    "data_confidence": 0.9,
                    "cash_runway_quarters": 6,
                    "dilution_4q": 0.05,
                    "fcf_margin": -0.25 if ticker == "RKLB" else 0.15,
                    "price_above_ma50": 1,
                    "price_above_ma200": 1,
                }
            )
    return rows


def concentrated_candidate_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    tickers = ["MELI", "NOW", "PAYC", "QCOM", "SHOP", "UI", "RKLB"]
    for dt in ("2025-03-31", "2025-04-30", "2025-05-30"):
        for idx, ticker in enumerate(tickers):
            emerging = ticker == "RKLB"
            rows.append(
                {
                    "rebalance_date": pd.Timestamp(dt),
                    "ticker": ticker,
                    "sector": "Technology",
                    "industry_group": "Technology",
                    "subindustry": "Technology",
                    "score": 1.0,
                    "rs_benchmark_3m": 0.35 - idx * 0.01,
                    "rs_benchmark_6m": 0.30 - idx * 0.01,
                    "relative_strength_composite": 0.30 - idx * 0.01,
                    "industry_group_strength_score": 0.30,
                    "industry_within_leader_rank": 0.30,
                    "oneil_leadership_score": 0.30,
                    "sub_industry_rs_score": 0.30,
                    "industry_leader_gap": 0.30,
                    "portfolio_future_winner_engine_score": 1.0,
                    "portfolio_early_scout_engine_score": 1.0 if emerging else 0.0,
                    "portfolio_monster_early_score": 1.0 if emerging else 0.0,
                    "theme_phase_primary": "emerging" if emerging else "confirmed",
                    "theme_phase_multiplier_primary": 1.5 if emerging else 1.0,
                    "dollar_vol_20d": 100_000_000,
                    "market_cap_live": 5_000_000_000,
                    "data_confidence": 0.9,
                    "cash_runway_quarters": 6,
                    "dilution_4q": 0.05,
                    "fcf_margin": -0.25 if emerging else 0.15,
                    "price_above_ma50": 1,
                    "price_above_ma200": 1,
                }
            )
    return rows


def test_concentrated_multi_lane_does_not_exceed_n5_after_hold_persistence() -> None:
    book, _lane_history, _rejected, _exposure = build_multi_lane_book(pd.DataFrame(concentrated_candidate_rows()), "concentrated", True)
    non_cash = book[~book["ticker"].astype(str).str.upper().isin({"CASH", "__CASH__"})].copy()
    counts = non_cash.groupby("rebalance_date")["ticker"].nunique()
    assert not counts.empty
    assert int(counts.max()) <= 5


def test_cash_trap_days_numeric_and_production_default_static_not_failure() -> None:
    ab = pd.DataFrame(
        [
            {
                "case_id": "A",
                "portfolio_kind": "concentrated",
                "selection_layer": "production",
                "status": "completed",
                "metric_mode": "broker_ledger_next_close",
                "metric_mode_review": "",
                "target_book_filter_source": "default_static",
                "crisis_overlay_enabled": False,
            },
            {
                "case_id": "H",
                "portfolio_kind": "main",
                "selection_layer": "multi_lane",
                "status": "completed",
                "metric_mode": "broker_ledger_next_close",
                "metric_mode_review": "",
                "target_book_filter_source": "not_applicable",
                "crisis_overlay_enabled": True,
            },
        ]
    )
    cash = pd.DataFrame(
        [
            {"case_id": "H", "portfolio_kind": "main", "crisis_state": "GREEN", "cash_weight": 0.11},
            {"case_id": "H", "portfolio_kind": "main", "crisis_state": "GREEN", "cash_weight": 0.03},
        ]
    )
    enriched = enrich_ab_matrix(ab, pd.DataFrame(), cash)
    h_cash = enriched.loc[enriched["case_id"].eq("H"), "cash_trap_days"].iloc[0]
    assert int(h_cash) == 1
    failures = case_failure_reasons(enriched)
    assert failures.empty


def test_integrated_replay_generates_default_8_case_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        reports = latest / "reports"
        cache = root / "cache_prices"
        macro = root / "cache_macro"
        reports.mkdir(parents=True)
        cache.mkdir()
        macro.mkdir()
        for ticker, ret in {"SPY": 0.0005, "QQQ": 0.0007, "DUAL": 0.0015, "RKLB": 0.0018, "QUAL": 0.0008, "CYCL": 0.001}.items():
            write_price(cache, ticker, 100, ret)
        pd.DataFrame(candidate_rows()).to_csv(reports / "candidate_replay_book.csv", index=False)
        (latest / "broker_replay" / "main").mkdir(parents=True)
        (latest / "broker_replay" / "main" / "metrics.json").write_text('{"status":"baseline"}\n', encoding="utf-8")
        (latest / "account_evaluation").mkdir()
        (latest / "account_evaluation" / "official_metrics.json").write_text('{"status":"baseline"}\n', encoding="utf-8")
        pd.DataFrame(
            [
                {"rebalance_date": "2025-03-31", "ticker": "DUAL", "weight": 0.50},
                {"rebalance_date": "2025-03-31", "ticker": "QUAL", "weight": 0.45},
                {"rebalance_date": "2025-04-30", "ticker": "DUAL", "weight": 0.50},
                {"rebalance_date": "2025-04-30", "ticker": "QUAL", "weight": 0.45},
                {"rebalance_date": "2025-05-30", "ticker": "DUAL", "weight": 0.50},
                {"rebalance_date": "2025-05-30", "ticker": "QUAL", "weight": 0.45},
            ]
        ).to_csv(reports / "operating_main_target_book.csv", index=False)
        cmd = [
            sys.executable,
            str(ROOT / "tools" / "run_integrated_theme_leader_crisis_replay.py"),
            "--latest-run",
            str(latest),
            "--price-cache",
            str(cache),
            "--output-dir",
            str(root / "out"),
            "--portfolio-kind",
            "main",
            "--allow-missing-baseline-lock",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        out = root / "out"
        ab = pd.read_csv(out / "ab_matrix.csv")
        assert set(ab["case_id"]) == set("ABCDEFGH")
        assert {
            "lane_allocator_enabled",
            "market_leader_enabled",
            "target_book_filter_source",
            "actual_median_position_count",
            "covid_mdd",
            "rate_2022_mdd",
            "green_avg_cash",
            "cash_trap_days",
            "review_flags",
            "review_status",
        }.issubset(ab.columns)
        assert "REVIEW_REQUIRED" in set(ab["review_status"])
        assert ab["review_flags"].astype(str).str.contains("missing_covid_mdd").any()
        delta = pd.read_csv(out / "ab_delta_decomposition.csv")
        assert {"B-A", "C-A", "D-C", "E-C", "F-D", "G-E", "H-G", "H-A"}.issubset(set(delta["delta_id"]))
        crisis_summary = pd.read_csv(out / "crisis_effect_summary.csv")
        assert {"B-A", "D-C", "F-E", "H-G"}.issubset(set(crisis_summary["delta_id"]))
        assert (out / "crisis_adjusted_target_books" / "main_B_production_crisis_only_target_book.csv").exists()
        assert (out / "crisis_adjusted_target_books" / "main_H_multi_lane_crisis_hold_replace_target_book.csv").exists()
        assert (out / "lane_feature_mapping.json").exists()
        assert (out / "lane_budget_by_regime.json").exists()
        assert (out / "lane_rules.yaml").exists()
        assert (out / "crisis_hysteresis_config.json").exists()
        assert (out / "hold_replace_policy.json").exists()
        assert (out / "crisis_actions.csv").exists()
        assert (out / "cash_by_crisis_state.csv").exists()
        assert (out / "case_failure_reasons.csv").exists()
        assert (out / "acceptance_gate_report.csv").exists()
        assert (out / "promotion_gate_status.json").exists()
        assert (out / "replay_gate_status.json").exists()
        assert (out / "case_level_summary.md").exists()
        assert (out / "top3_stability.csv").exists()
        assert (out / "production_mutation_check.json").exists()
        assert (out / "replay_integrity" / "production_mutation_check.json").exists()
        mutation = pd.read_json(out / "production_mutation_check.json", typ="series")
        assert mutation["status"] == "passed"
        assert mutation["before_file_count"] >= 2
        promotion = pd.read_json(out / "promotion_gate_status.json", typ="series")
        assert promotion["production_activation_allowed"] == False  # noqa: E712
        assert promotion["status"] in {"passed", "rejected"}
        risk_caps = pd.read_csv(out / "emerging_risk_caps.csv")
        assert "risk_cap_multiplier" in risk_caps.columns
        assert (out / "strategy_logic_ledger.csv").exists() is False
        lane_book = pd.read_csv(out / "lane_target_book.csv")
        assert "case_id" in lane_book.columns
        preflight_path = out / "cases" / "H" / "main" / "replay_integrity" / "preflight_replay_gate.json"
        assert preflight_path.exists()
        preflight = pd.read_json(preflight_path, typ="series")
        assert preflight["execution_tier"] == "TIER2_FULL_CACHE"
        assert preflight["spy_price_coverage"] == 1.0
        assert preflight["qqq_price_coverage"] == 1.0
        assert preflight["macro_feature_coverage"] == 1.0
        assert "NO_BASELINE_LOCK" in preflight["blockers"]


def main() -> int:
    test_integrated_replay_generates_default_8_case_contract()
    test_concentrated_multi_lane_does_not_exceed_n5_after_hold_persistence()
    test_cash_trap_days_numeric_and_production_default_static_not_failure()
    print("integrated_theme_leader_crisis_replay_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

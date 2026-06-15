#!/usr/bin/env python3
"""Smoke test for review-only era-aware scoring challenger."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_era_aware_scoring_challenger import evaluate_goal_contract, run  # noqa: E402


def base_row(date: str, ticker: str) -> dict[str, object]:
    return {
        "rebalance_date": date,
        "ticker": ticker,
        "Name": ticker,
        "sector": "Technology",
        "industry_group": "Software",
        "alphaops_vnext_score": 0.2,
        "score": 0.2,
        "mom_12m": 0.2,
        "mom_6m": 0.2,
        "rs_benchmark_3m": 0.2,
        "rs_semis_3m": 0.2,
        "breakout_setup_quality_score": 0.2,
        "quality_compounder_lane_score": 0.2,
        "selection_confirmation_score": 0.2,
        "oneil_leadership_score": 0.2,
        "theme_leadership_score": 0.2,
        "etf_theme_leadership_score": 0.2,
        "evidence_fusion_score": 0.2,
        "market_leader_lane_score": 0.2,
        "h6_dynamic_leader_score": 0.2,
        "price_above_ma200": 0.0,
        "risk_penalty": 0.8,
        "atr14_pct": 0.8,
        "live_event_risk_score": 0.8,
    }


def candidate_rows() -> list[dict[str, object]]:
    specs = [
        ("2021-06-30", "MOM", {"alphaops_vnext_score": 2.0, "mom_12m": 2.0, "breakout_setup_quality_score": 2.0}),
        ("2021-06-30", "LOW", {}),
        ("2022-06-30", "DEF", {"quality_compounder_lane_score": 2.0, "price_above_ma200": 1.0, "risk_penalty": 0.0, "atr14_pct": 0.0, "live_event_risk_score": 0.0}),
        ("2022-06-30", "RISK", {"alphaops_vnext_score": 1.0, "risk_penalty": 2.0, "atr14_pct": 2.0}),
        ("2024-06-30", "AI", {"alphaops_vnext_score": 2.0, "theme_leadership_score": 2.0, "etf_theme_leadership_score": 2.0, "rs_semis_3m": 2.0}),
        ("2024-06-30", "OLD", {}),
        ("2025-06-30", "CONT", {"alphaops_vnext_score": 2.0, "h6_dynamic_leader_score": 2.0, "market_leader_lane_score": 2.0, "mom_6m": 2.0}),
        ("2025-06-30", "FLAT", {}),
    ]
    rows: list[dict[str, object]] = []
    for date, ticker, overrides in specs:
        row = base_row(date, ticker)
        row.update(overrides)
        rows.append(row)
    return rows


def test_era_aware_challenger_builds_review_only_books() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest" / "reports"
        latest.mkdir(parents=True)
        candidate = latest / "candidate_replay_book.csv"
        pd.DataFrame(candidate_rows()).to_csv(candidate, index=False)
        out = root / "out"
        summary = run(
            Namespace(
                latest_run=str(root / "latest"),
                candidate_book="",
                price_cache=str(root / "cache_prices"),
                output_dir=str(out),
                main_target_n=1,
                concentrated_target_n=1,
                main_single_cap=0.97,
                concentrated_single_cap=0.95,
                score_power=2.0,
                min_dollar_volume=0.0,
                run_broker_replay=False,
                cost_bps=25.0,
                max_fill_lag_days=7,
            )
        )
        assert summary["status"] == "completed"
        assert summary["production_activation_allowed"] is False
        assert summary["production_mutation_allowed"] is False
        assert summary["sidecar_only"] is True

        main_book = pd.read_csv(out / "era_aware_main_target_book.csv")
        stocks = main_book[main_book["ticker"].ne("CASH")]
        selected = dict(zip(stocks["rebalance_date"], stocks["ticker"]))
        assert selected == {
            "2021-06-30": "MOM",
            "2022-06-30": "DEF",
            "2024-06-30": "AI",
            "2025-06-30": "CONT",
        }
        assert main_book["production_activation_allowed"].eq(False).all()
        assert main_book["sidecar_only"].eq(True).all()
        assert set(main_book["weighting_mode"]) == {"era_aware_score_power"}
        assert (out / "main_target_book.csv").exists()
        assert (out / "concentrated_target_book.csv").exists()

        factor_weights = pd.read_csv(out / "era_factor_weights.csv")
        assert {"era_bucket", "feature", "weight", "direction"}.issubset(factor_weights.columns)
        audit = pd.read_csv(out / "selection_audit.csv")
        assert audit["selected"].astype(str).str.lower().eq("true").any()
        saved = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert saved["broker_replay"]["status"] == "skipped"


def test_goal_contract_verdict_scores_replay_metrics() -> None:
    verdicts = evaluate_goal_contract(
        {
            "requested": True,
            "status": "completed",
            "portfolios": {
                "main": {
                    "status": "completed",
                    "metric_mode": "broker_ledger_next_close",
                    "start_date": "2019-06-03",
                    "end_date": "2026-06-12",
                    "years": 7.025,
                    "days": 1768,
                    "cagr": 0.35,
                    "max_dd": -0.24,
                    "sharpe": 1.5,
                    "avg_cash_weight": 0.25,
                    "windows": {
                        "is": {"cagr": 0.27, "max_dd": -0.24},
                        "oos": {"cagr": 0.50, "max_dd": -0.20},
                        "oos2": {"cagr": 0.40, "max_dd": -0.22},
                    },
                },
                "concentrated": {
                    "status": "completed",
                    "metric_mode": "broker_ledger_next_close",
                    "start_date": "2019-06-03",
                    "end_date": "2026-06-12",
                    "years": 7.025,
                    "days": 1749,
                    "cagr": 0.4443,
                    "max_dd": -0.2592,
                    "sharpe": 1.4,
                    "avg_cash_weight": 0.42,
                    "windows": {
                        "is": {"cagr": 0.2241, "max_dd": -0.2592},
                        "oos": {"cagr": 1.2326, "max_dd": -0.2303},
                        "oos2": {"cagr": 0.80, "max_dd": -0.2303},
                    },
                },
            },
        }
    )
    assert verdicts["production_activation_allowed"] is False
    assert verdicts["promotion_requires_separate_ab"] is True
    assert verdicts["portfolios"]["main"]["status"] == "evaluated"
    assert verdicts["portfolios"]["main"]["target_pass"] is True
    assert verdicts["portfolios"]["main"]["strengthened_pass"] is True
    conc = verdicts["portfolios"]["concentrated"]
    assert conc["target_pass"] is False
    assert conc["strengthened_pass"] is False
    assert "is_cagr_min" in conc["tier2_gates"]["failing"]
    assert "oos_is_cagr_ratio_max" in conc["tier2_gates"]["failing"]


if __name__ == "__main__":
    test_era_aware_challenger_builds_review_only_books()
    test_goal_contract_verdict_scores_replay_metrics()
    print("era_aware_scoring_challenger_smoke: PASS")

#!/usr/bin/env python3
"""Smoke tests for post-disclosure alpha candidate generation."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_post_disclosure_alpha_candidates import run  # noqa: E402


def test_post_disclosure_candidates_rank_converged_ticker() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        events_13f = root / "data_pit" / "sec" / "13f_position_events.parquet"
        events_form4 = root / "data_pit" / "sec" / "form4_transaction_events.parquet"
        events_etf = root / "data_pit" / "etf_holdings" / "etf_holding_events.parquet"
        manager_scores = root / "data_pit" / "sec" / "manager_disclosure_alpha_scores.parquet"
        out_dir = root / "outputs" / "post_disclosure_alpha_candidates"
        for path in [events_13f, events_form4, events_etf, manager_scores]:
            path.parent.mkdir(parents=True, exist_ok=True)

        pd.DataFrame(
            [
                {
                    "event_id": "13f:m1:aaa",
                    "ticker": "AAA",
                    "source_type": "13f",
                    "manager_cik": "0000000001",
                    "manager_name": "Manager One",
                    "event_type": "new",
                    "post_disclosure_event_seed_score": 0.70,
                    "available_from": "2024-05-01T21:00:00Z",
                },
                {
                    "event_id": "13f:m2:bbb",
                    "ticker": "BBB",
                    "source_type": "13f",
                    "manager_cik": "0000000002",
                    "manager_name": "Manager Two",
                    "event_type": "trim",
                    "post_disclosure_event_seed_score": -0.50,
                    "available_from": "2024-05-01T21:00:00Z",
                },
            ]
        ).to_parquet(events_13f, index=False)
        pd.DataFrame(
            [
                {
                    "event_id": "form4:aaa",
                    "ticker": "AAA",
                    "reporting_owner_cik": "0000000999",
                    "reporting_owner_name": "CEO Buyer",
                    "event_type": "open_market_buy",
                    "post_disclosure_event_seed_score": 0.80,
                    "available_from": "2024-05-03T21:00:00Z",
                }
            ]
        ).to_parquet(events_form4, index=False)
        pd.DataFrame(
            [
                {
                    "event_id": "etf:aaa",
                    "holding_ticker": "AAA",
                    "etf_ticker": "THEME",
                    "event_type": "inclusion",
                    "etf_event_seed_score": 0.50,
                    "available_from": "2024-05-04T00:00:00Z",
                }
            ]
        ).to_parquet(events_etf, index=False)
        pd.DataFrame(
            [
                {
                    "manager_cik": "0000000001",
                    "manager_name": "Manager One",
                    "as_of_date": "2024-04-15",
                    "manager_disclosure_alpha_score": 0.90,
                    "manager_confidence": 0.80,
                },
                {
                    "manager_cik": "0000000001",
                    "manager_name": "Manager One",
                    "as_of_date": "2024-06-01",
                    "manager_disclosure_alpha_score": 0.10,
                    "manager_confidence": 1.00,
                },
            ]
        ).to_parquet(manager_scores, index=False)

        payload = run(
            Namespace(
                events_13f=str(events_13f),
                events_form4=str(events_form4),
                events_etf=str(events_etf),
                manager_scores=str(manager_scores),
                output_dir=str(out_dir),
                as_of_date="2024-05-10",
                lookback_days=60,
                top_n=10,
            )
        )

        assert payload["status"] == "completed", payload
        ranked = pd.read_csv(out_dir / "latest.csv")
        assert ranked.loc[0, "ticker"] == "AAA"
        assert int(ranked.loc[0, "source_count"]) == 3
        assert float(ranked.loc[0, "manager_alpha_component"]) > 0.70
        assert bool(ranked.loc[0, "research_only"]) is True
        assert bool(ranked.loc[0, "production_activation_allowed"]) is False
        assert "Manager One" in ranked.loc[0, "candidate_explanation"]
        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["score_total_changed"] is False


def test_post_disclosure_candidates_block_without_events() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        out_dir = root / "outputs"
        payload = run(
            Namespace(
                events_13f=str(root / "missing_13f.parquet"),
                events_form4=str(root / "missing_form4.parquet"),
                events_etf=str(root / "missing_etf.parquet"),
                manager_scores=str(root / "missing_manager.parquet"),
                output_dir=str(out_dir),
                as_of_date="2024-05-10",
                lookback_days=60,
                top_n=10,
            )
        )
        assert payload["status"] == "blocked"
        assert pd.read_csv(out_dir / "latest.csv").empty


def test_post_disclosure_candidates_filter_to_tradable_metadata() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        events_13f = root / "data_pit" / "sec" / "13f_position_events.parquet"
        events_form4 = root / "data_pit" / "sec" / "form4_transaction_events.parquet"
        events_etf = root / "data_pit" / "etf_holdings" / "etf_holding_events.parquet"
        manager_scores = root / "data_pit" / "sec" / "manager_disclosure_alpha_scores.parquet"
        metadata = root / "scored_latest.csv"
        out_dir = root / "outputs" / "post_disclosure_alpha_candidates"
        for path in [events_13f, events_form4, events_etf, manager_scores]:
            path.parent.mkdir(parents=True, exist_ok=True)

        pd.DataFrame(
            [
                {
                    "event_id": "13f:aaa",
                    "ticker": "AAA",
                    "source_type": "13f",
                    "manager_cik": "0000000001",
                    "manager_name": "Manager One",
                    "event_type": "new",
                    "post_disclosure_event_seed_score": 0.70,
                    "available_from": "2024-05-01T21:00:00Z",
                },
                {
                    "event_id": "13f:micro",
                    "ticker": "MICR",
                    "source_type": "13f",
                    "manager_cik": "0000000001",
                    "manager_name": "Manager One",
                    "event_type": "new",
                    "post_disclosure_event_seed_score": 0.95,
                    "available_from": "2024-05-01T21:00:00Z",
                },
            ]
        ).to_parquet(events_13f, index=False)
        pd.DataFrame(columns=["ticker", "available_from"]).to_parquet(events_form4, index=False)
        pd.DataFrame(columns=["ticker", "available_from"]).to_parquet(events_etf, index=False)
        pd.DataFrame(
            [
                {
                    "manager_cik": "0000000001",
                    "manager_name": "Manager One",
                    "as_of_date": "2024-04-15",
                    "manager_disclosure_alpha_score": 0.70,
                    "manager_confidence": 0.80,
                }
            ]
        ).to_parquet(manager_scores, index=False)
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "market_cap_live": 1_000_000_000.0,
                    "dollar_vol_20d": 15_000_000.0,
                    "current_price_live": 20.0,
                    "universe_source": "smoke",
                    "ranking_eligible": True,
                    "portfolio_future_winner_engine_score": 0.50,
                    "selection_market_confirmation_score": 0.50,
                },
                {
                    "ticker": "MICR",
                    "market_cap_live": 50_000_000.0,
                    "dollar_vol_20d": 100_000.0,
                    "current_price_live": 1.0,
                    "universe_source": "smoke",
                    "ranking_eligible": True,
                },
            ]
        ).to_csv(metadata, index=False)

        payload = run(
            Namespace(
                events_13f=str(events_13f),
                events_form4=str(events_form4),
                events_etf=str(events_etf),
                manager_scores=str(manager_scores),
                metadata=str(metadata),
                output_dir=str(out_dir),
                as_of_date="2024-05-10",
                lookback_days=60,
                top_n=10,
                tradable_only=True,
                min_market_cap_usd=300_000_000.0,
                min_dollar_volume_usd=5_000_000.0,
                min_price=2.0,
            )
        )

        assert payload["status"] == "completed", payload
        assert payload["raw_candidate_rows"] == 2
        assert payload["tradable_candidate_rows"] == 1
        latest = pd.read_csv(out_dir / "latest.csv")
        assert latest["ticker"].tolist() == ["AAA"]
        assert bool(latest.loc[0, "tradable_candidate"]) is True


def test_post_disclosure_candidates_split_discovery_from_mega_confirmation() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        events_13f = root / "data_pit" / "sec" / "13f_position_events.parquet"
        events_form4 = root / "data_pit" / "sec" / "form4_transaction_events.parquet"
        events_etf = root / "data_pit" / "etf_holdings" / "etf_holding_events.parquet"
        manager_scores = root / "data_pit" / "sec" / "manager_disclosure_alpha_scores.parquet"
        metadata = root / "scored_latest.csv"
        out_dir = root / "outputs" / "post_disclosure_alpha_candidates"
        for path in [events_13f, events_form4, events_etf, manager_scores]:
            path.parent.mkdir(parents=True, exist_ok=True)

        pd.DataFrame(
            [
                {
                    "event_id": "13f:small",
                    "ticker": "SMID",
                    "source_type": "13f",
                    "manager_cik": "0000000001",
                    "manager_name": "High Alpha Manager",
                    "event_type": "new",
                    "post_disclosure_event_seed_score": 0.75,
                    "available_from": "2024-05-01T21:00:00Z",
                },
                {
                    "event_id": "13f:mega",
                    "ticker": "MEGA",
                    "source_type": "13f",
                    "manager_cik": "0000000001",
                    "manager_name": "High Alpha Manager",
                    "event_type": "new",
                    "post_disclosure_event_seed_score": 0.75,
                    "available_from": "2024-05-01T21:00:00Z",
                },
            ]
        ).to_parquet(events_13f, index=False)
        pd.DataFrame(columns=["ticker", "available_from"]).to_parquet(events_form4, index=False)
        pd.DataFrame(columns=["ticker", "available_from"]).to_parquet(events_etf, index=False)
        pd.DataFrame(
            [
                {
                    "manager_cik": "0000000001",
                    "manager_name": "High Alpha Manager",
                    "as_of_date": "2024-04-15",
                    "manager_disclosure_alpha_score": 0.80,
                    "manager_confidence": 0.80,
                }
            ]
        ).to_parquet(manager_scores, index=False)
        pd.DataFrame(
            [
                {
                    "ticker": "SMID",
                    "market_cap_live": 1_500_000_000.0,
                    "dollar_vol_20d": 25_000_000.0,
                    "current_price_live": 12.0,
                    "universe_source": "smoke",
                    "ranking_eligible": True,
                    "portfolio_future_winner_engine_score": 0.45,
                    "selection_market_confirmation_score": 0.45,
                },
                {
                    "ticker": "MEGA",
                    "market_cap_live": 900_000_000_000.0,
                    "dollar_vol_20d": 1_000_000_000.0,
                    "current_price_live": 300.0,
                    "universe_source": "smoke",
                    "ranking_eligible": True,
                    "portfolio_future_winner_engine_score": 0.75,
                    "selection_market_confirmation_score": 0.75,
                },
            ]
        ).to_csv(metadata, index=False)

        payload = run(
            Namespace(
                events_13f=str(events_13f),
                events_form4=str(events_form4),
                events_etf=str(events_etf),
                manager_scores=str(manager_scores),
                metadata=str(metadata),
                output_dir=str(out_dir),
                as_of_date="2024-05-10",
                lookback_days=60,
                top_n=10,
                tradable_only=True,
                min_market_cap_usd=300_000_000.0,
                min_dollar_volume_usd=5_000_000.0,
                min_price=2.0,
            )
        )

        assert payload["status"] == "completed", payload
        discovery = pd.read_csv(out_dir / "latest_discovery.csv")
        mega = pd.read_csv(out_dir / "latest_mega_cap_confirmation.csv")
        assert discovery.loc[0, "ticker"] == "SMID"
        assert discovery.loc[0, "candidate_bucket"] == "small_mid_discovery"
        assert float(discovery.loc[0, "size_discovery_score"]) > float(
            mega.loc[0, "size_discovery_score"]
        )
        assert mega.loc[0, "ticker"] == "MEGA"
        assert mega.loc[0, "candidate_bucket"] == "mega_cap_confirmation"
        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["small_mid_discovery_rows"] >= 1
        assert summary["mega_cap_confirmation_rows"] >= 1


if __name__ == "__main__":
    test_post_disclosure_candidates_rank_converged_ticker()
    test_post_disclosure_candidates_block_without_events()
    test_post_disclosure_candidates_filter_to_tradable_metadata()
    test_post_disclosure_candidates_split_discovery_from_mega_confirmation()
    print("post_disclosure_alpha_candidates_smoke: PASS")

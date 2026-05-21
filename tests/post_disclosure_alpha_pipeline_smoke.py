#!/usr/bin/env python3
"""Smoke tests for the end-to-end post-disclosure alpha pipeline."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_post_disclosure_alpha_pipeline import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_price_cache(cache: Path, ticker: str, start: str = "2024-01-02", periods: int = 170, base: float = 100.0) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range(start, periods=periods)
    closes = [base + float(i) for i in range(len(dates))]
    pd.DataFrame(
        {"Open": closes, "Close": closes, "Adj Close": closes, "Volume": [1_000_000] * len(dates)},
        index=dates,
    ).to_parquet(cache / px_cache_name(ticker))


def full_namespace(root: Path, *, skip_event_builders: bool = True) -> Namespace:
    return Namespace(
        output_dir=str(root / "outputs" / "post_disclosure_alpha_pipeline"),
        skip_event_builders=skip_event_builders,
        holdings_13f=str(root / "missing_13f_holdings.parquet"),
        form4_transactions=str(root / "missing_form4.parquet"),
        etf_holdings=str(root / "missing_etf_holdings.parquet"),
        metadata=str(root / "metadata.csv"),
        events_13f=str(root / "data_pit" / "sec" / "13f_position_events.parquet"),
        events_form4=str(root / "data_pit" / "sec" / "form4_transaction_events.parquet"),
        events_etf=str(root / "data_pit" / "etf_holdings" / "etf_holding_events.parquet"),
        combined_events=str(root / "data_pit" / "sec" / "post_disclosure_events_all.parquet"),
        labels=str(root / "data_pit" / "sec" / "post_disclosure_alpha_labels.parquet"),
        manager_scores=str(root / "data_pit" / "sec" / "manager_disclosure_alpha_scores.parquet"),
        price_cache=str(root / "cache_prices"),
        benchmark_ticker="SPY",
        horizons="1,5,21,63",
        learning_horizons="21,63",
        as_of_date="2024-05-10",
        lookback_days=90,
        top_n=10,
        tradable_only=True,
        etf_change_threshold=0.0025,
        run_overlay_challenger=False,
        run_broker_grid=False,
        candidate_book=str(root / "candidate_replay_book.csv"),
        portfolio_kinds="main,concentrated",
        starting_capital=100000.0,
        fill_mode="next_close",
        cost_bps=25.0,
        max_fill_lag_days=7,
        styles="post_disclosure_light,post_disclosure_balanced",
        target_ns="3,5",
        single_name_caps="0.33,0.50",
        max_variants=8,
        min_market_cap_usd=300_000_000.0,
        min_dollar_volume_usd=5_000_000.0,
        min_price=2.0,
        allow_unfillable_targets=False,
    )


def test_post_disclosure_pipeline_runs_from_prebuilt_events() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = full_namespace(root)
        for path in [Path(args.events_13f), Path(args.events_form4), Path(args.events_etf), Path(args.manager_scores)]:
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
                }
            ]
        ).to_parquet(args.events_13f, index=False)
        pd.DataFrame(
            [
                {
                    "event_id": "form4:aaa",
                    "ticker": "AAA",
                    "reporting_owner_name": "CEO Buyer",
                    "event_type": "open_market_buy",
                    "post_disclosure_event_seed_score": 0.80,
                    "available_from": "2024-05-02T21:00:00Z",
                }
            ]
        ).to_parquet(args.events_form4, index=False)
        pd.DataFrame(
            [
                {
                    "event_id": "etf:aaa",
                    "ticker": "AAA",
                    "etf_ticker": "THEME",
                    "event_type": "inclusion",
                    "etf_event_seed_score": 0.50,
                    "available_from": "2024-05-03T00:00:00Z",
                }
            ]
        ).to_parquet(args.events_etf, index=False)
        pd.DataFrame(
            [
                {
                    "manager_cik": "0000000001",
                    "manager_name": "Manager One",
                    "as_of_date": "2024-04-15",
                    "manager_disclosure_alpha_score": 0.80,
                    "manager_confidence": 0.75,
                }
            ]
        ).to_parquet(args.manager_scores, index=False)
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "market_cap_live": 1_000_000_000.0,
                    "dollar_vol_20d": 25_000_000.0,
                    "current_price_live": 25.0,
                    "universe_source": "smoke",
                    "ranking_eligible": True,
                    "portfolio_future_winner_engine_score": 0.75,
                    "selection_market_confirmation_score": 0.65,
                }
            ]
        ).to_csv(args.metadata, index=False)
        write_price_cache(Path(args.price_cache), "AAA", base=100.0)
        write_price_cache(Path(args.price_cache), "SPY", base=200.0)

        payload = run(args)

        assert payload["status"] == "completed", payload
        assert payload["combined_event_rows"] == 3
        assert payload["label_rows"] == 3
        assert payload["candidate_rows"] == 1
        assert payload["score_total_changed"] is False
        assert Path(args.combined_events).exists()
        assert Path(args.labels).exists()
        summary = json.loads((Path(args.output_dir) / "summary.json").read_text(encoding="utf-8"))
        assert summary["production_activation_allowed"] is False
        latest = pd.read_csv(Path(args.output_dir) / "post_disclosure_alpha_candidates" / "latest.csv")
        assert latest.loc[0, "ticker"] == "AAA"


def test_post_disclosure_pipeline_blocks_without_events() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = full_namespace(root)
        payload = run(args)
        assert payload["status"] == "blocked"
        assert payload["combined_event_rows"] == 0
        assert (Path(args.output_dir) / "summary.json").exists()


if __name__ == "__main__":
    test_post_disclosure_pipeline_runs_from_prebuilt_events()
    test_post_disclosure_pipeline_blocks_without_events()
    print("post_disclosure_alpha_pipeline_smoke: PASS")

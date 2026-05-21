#!/usr/bin/env python3
"""Smoke tests for post-disclosure overlay challenger wiring."""
from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_post_disclosure_overlay_challenger import add_post_disclosure_overlay, run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_price_cache(cache: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    cache.mkdir(parents=True, exist_ok=True)
    idx = pd.bdate_range(start=start, periods=len(closes))
    pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    ).to_parquet(cache / px_cache_name(ticker))


def candidate_rows() -> pd.DataFrame:
    rows = []
    for dt in ["2026-01-02", "2026-01-05"]:
        rows.extend(
            [
                {
                    "rebalance_date": dt,
                    "ticker": "AAA",
                    "Name": "Post Disclosure Leader",
                    "sector": "Tech",
                    "portfolio_sleeve_label": "future_winner",
                    "portfolio_candidate_gate_label": "future_relaxed",
                    "portfolio_future_winner_engine_score": 0.60,
                    "selection_market_confirmation_score": 0.70,
                    "rs_acceleration_score": 0.55,
                    "industry_group_strength_score": 0.50,
                    "entry_quality_score": 0.60,
                    "portfolio_risk_entry_block_score": 0.0,
                    "portfolio_stale_mega_leader_score": 0.0,
                    "px": 100.0,
                    "dollar_vol_20d": 50_000_000.0,
                    "mktcap": 2_000_000_000.0,
                    "period_forward_return": 0.10,
                },
                {
                    "rebalance_date": dt,
                    "ticker": "BBB",
                    "Name": "No Evidence Candidate",
                    "sector": "Tech",
                    "portfolio_sleeve_label": "future_winner",
                    "portfolio_candidate_gate_label": "future_relaxed",
                    "portfolio_future_winner_engine_score": 0.55,
                    "selection_market_confirmation_score": 0.50,
                    "rs_acceleration_score": 0.45,
                    "industry_group_strength_score": 0.45,
                    "entry_quality_score": 0.45,
                    "portfolio_risk_entry_block_score": 0.0,
                    "portfolio_stale_mega_leader_score": 0.0,
                    "px": 50.0,
                    "dollar_vol_20d": 30_000_000.0,
                    "mktcap": 1_500_000_000.0,
                    "period_forward_return": 0.02,
                },
            ]
        )
    return pd.DataFrame(rows)


def event_rows(score_col: str, score: float, source_type: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": f"{source_type}:AAA",
                "source_type": source_type,
                "ticker": "AAA",
                "available_from": "2026-01-01T20:00:00Z",
                "event_type": "new",
                score_col: score,
            }
        ]
    )


def test_post_disclosure_overlay_joins_events_by_available_from() -> None:
    enriched = add_post_disclosure_overlay(
        candidate_rows(),
        event_rows("post_disclosure_event_seed_score", 0.8, "13f"),
        event_rows("post_disclosure_event_seed_score", 0.7, "form4"),
        event_rows("etf_event_seed_score", 0.6, "etf_holding"),
        lookback_days=120,
    )
    aaa = enriched[enriched["ticker"].eq("AAA")].iloc[0]
    bbb = enriched[enriched["ticker"].eq("BBB")].iloc[0]
    assert float(aaa["post_disclosure_alpha_score"]) > 0.50
    assert int(aaa["post_disclosure_evidence_source_count"]) == 3
    assert float(bbb["post_disclosure_alpha_score"]) == 0.0
    assert "period_forward_return" in enriched.columns


def test_post_disclosure_overlay_runs_broker_grid_challenger() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate = root / "candidate.csv"
        events_13f = root / "13f_events.parquet"
        events_form4 = root / "form4_events.parquet"
        events_etf = root / "etf_events.parquet"
        cache = root / "cache_prices"
        out = root / "outputs"
        candidate_rows().to_csv(candidate, index=False)
        event_rows("post_disclosure_event_seed_score", 0.9, "13f").to_parquet(events_13f, index=False)
        event_rows("post_disclosure_event_seed_score", 0.8, "form4").to_parquet(events_form4, index=False)
        event_rows("etf_event_seed_score", 0.7, "etf_holding").to_parquet(events_etf, index=False)
        write_price_cache(cache, "AAA", [100, 101, 102, 103, 104, 105, 106])
        write_price_cache(cache, "BBB", [50, 50, 50, 50, 50, 50, 50])
        payload = run(
            Namespace(
                candidate_book=str(candidate),
                events_13f=str(events_13f),
                events_form4=str(events_form4),
                events_etf=str(events_etf),
                output_dir=str(out),
                lookback_days=120,
                run_broker_grid=True,
                price_cache=str(cache),
                portfolio_kinds="main",
                starting_capital=10_000.0,
                fill_mode="next_close",
                cost_bps=0.0,
                max_fill_lag_days=7,
                styles="post_disclosure_balanced",
                target_ns="1",
                single_name_caps="1.0",
                max_variants=1,
                min_market_cap_usd=300_000_000.0,
                min_dollar_volume_usd=1_000_000.0,
                min_price=2.0,
                allow_unfillable_targets=False,
            )
        )
        assert payload["status"] == "completed", payload
        assert payload["rows_with_post_disclosure_score"] >= 2
        assert payload["broker_grid"]["portfolios"]["main"]["status"] == "completed"
        targets = pd.read_csv(next((out / "alpha_selector_broker_grid" / "main").glob("post_disclosure_balanced_N1_cap*/target_book.csv")))
        assert set(targets["ticker"]) == {"AAA"}
        assert "post_disclosure_alpha_score" in targets.columns


if __name__ == "__main__":
    test_post_disclosure_overlay_joins_events_by_available_from()
    test_post_disclosure_overlay_runs_broker_grid_challenger()
    print("post_disclosure_overlay_challenger_smoke: PASS")

#!/usr/bin/env python3
"""Smoke tests for post-disclosure alpha label generation."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_post_disclosure_alpha_labeler import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_price_cache(cache: Path, ticker: str, start: str = "2024-01-02", periods: int = 150, base: float = 100.0) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range(start, periods=periods)
    closes = [base + float(i) for i in range(len(dates))]
    frame = pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(dates),
        },
        index=dates,
    )
    frame.to_parquet(cache / px_cache_name(ticker))


def test_labeler_uses_next_close_after_available_from() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        events = root / "data_pit" / "sec" / "13f_position_events.parquet"
        cache = root / "cache_prices"
        out_dir = root / "outputs" / "post_disclosure_alpha"
        pit = root / "data_pit" / "sec" / "post_disclosure_alpha_labels.parquet"
        events.parent.mkdir(parents=True, exist_ok=True)

        pd.DataFrame(
            [
                {
                    "event_id": "13f:test:AAA",
                    "source_type": "13f",
                    "manager_cik": "0000000001",
                    "manager_name": "Test Manager",
                    "ticker": "AAA",
                    "event_type": "new",
                    "post_disclosure_event_seed_score": 0.75,
                    "available_from": "2024-01-02T20:00:00Z",
                }
            ]
        ).to_parquet(events, index=False)
        write_price_cache(cache, "AAA", base=100.0)
        write_price_cache(cache, "SPY", base=200.0)

        payload = run(
            Namespace(
                events=str(events),
                price_cache=str(cache),
                pit_output=str(pit),
                output_dir=str(out_dir),
                benchmark_ticker="SPY",
                horizons="1,5,21,63",
            )
        )
        assert payload["status"] == "completed", payload
        labels = pd.read_parquet(pit)
        row = labels.iloc[0]
        assert row["entry_date"] == "2024-01-03"
        assert abs(float(row["entry_price"]) - 101.0) < 1e-9
        assert abs(float(row["ret_1d"]) - ((102.0 / 101.0) - 1.0)) < 1e-9
        assert abs(float(row["event_seed_score"]) - 0.75) < 1e-9
        assert "2024-01-02" not in str(row["entry_date"])
        assert bool(row["research_only"]) is True
        assert bool(row["production_activation_allowed"]) is False
        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["score_total_changed"] is False


def test_labeler_blocks_cleanly_without_restored_events() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        out_dir = root / "outputs"
        pit = root / "labels.parquet"
        payload = run(
            Namespace(
                events=str(root / "missing.parquet"),
                price_cache=str(root / "cache_prices"),
                pit_output=str(pit),
                output_dir=str(out_dir),
                benchmark_ticker="SPY",
                horizons="1,5",
            )
        )
        assert payload["status"] == "blocked"
        labels = pd.read_parquet(pit)
        assert labels.empty


if __name__ == "__main__":
    test_labeler_uses_next_close_after_available_from()
    test_labeler_blocks_cleanly_without_restored_events()
    print("post_disclosure_alpha_labeler_smoke: PASS")

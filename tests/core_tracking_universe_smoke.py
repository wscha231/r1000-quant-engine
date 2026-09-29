#!/usr/bin/env python3
"""Focused contract checks for the tiered core-tracking universe."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


TIER_1 = {"FTI", "CACI", "FLEX", "NVT", "CLS", "ONTO", "RBRK", "MLI", "EME", "LDOS", "CVLT", "CEG", "MEDP"}
TIER_2 = {"CAMT", "GNRC", "KTOS", "MKSI", "VST", "MCK"}
TIER_3 = {"AMAT", "GLW", "BWXT"}
EXPECTED_TICKERS = TIER_1 | TIER_2 | TIER_3


def test_tiered_loaders_are_exact_and_deduplicated() -> None:
    from aggressive.universe import load_core_tracking_universe
    from r1000_config import EngineConfig
    from r1000_pipeline import load_core_tracking_universe_frame

    tickers, metadata = load_core_tracking_universe()
    assert set(tickers) == EXPECTED_TICKERS
    assert len(tickers) == 22
    assert len(metadata) == 22

    frame = load_core_tracking_universe_frame(EngineConfig())
    assert set(frame["ticker"]) == EXPECTED_TICKERS
    assert len(frame) == 22
    assert set(frame.loc[frame["tracking_tier"].eq(1), "ticker"]) == TIER_1
    assert set(frame.loc[frame["tracking_tier"].eq(2), "ticker"]) == TIER_2
    assert set(frame.loc[frame["tracking_tier"].eq(3), "ticker"]) == TIER_3
    assert set(frame["universe_source"]) == {"core_tracking_overlay"}


def test_global_alpha_union_adds_only_missing_tracking_names() -> None:
    import aggressive.universe as universe

    original_fetch = universe.fetch_iwb_holdings
    try:
        universe.fetch_iwb_holdings = lambda force_refresh=False: pd.DataFrame(
            {
                "ticker": ["EME", "LDOS", "BASE"],
                "Name": ["EMCOR", "Leidos", "Base"],
                "Sector": ["Industrials", "Industrials", "Industrials"],
            }
        )
        tickers, metadata = universe.load_universe("global_alpha_universe")
    finally:
        universe.fetch_iwb_holdings = original_fetch

    assert EXPECTED_TICKERS.issubset(set(tickers))
    assert metadata["core_tracking_count"] == 22
    assert "CVLT" in metadata["core_tracking_added"]
    assert "EME" not in metadata["core_tracking_added"]


def test_overlay_only_rows_are_latest_only() -> None:
    from r1000_config import EngineConfig
    from r1000_helpers import get_paths
    from r1000_pipeline import apply_leader_rescue_backtest_mode_filter

    monthly = pd.DataFrame(
        {
            "rebalance_date": pd.to_datetime(["2026-07-31", "2026-08-31", "2026-07-31"]),
            "ticker": ["CVLT", "CVLT", "EME"],
            "universe_source": [
                "core_tracking_overlay",
                "core_tracking_overlay",
                "current_constituents_proxy+core_tracking_overlay",
            ],
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        cfg = EngineConfig(base_dir=tmp)
        cfg.leader_rescue_backtest_mode = "latest_only"
        latest_only = apply_leader_rescue_backtest_mode_filter(cfg, get_paths(cfg), monthly)
        assert list(latest_only["ticker"]) == ["CVLT", "EME"]
        assert pd.Timestamp(latest_only.iloc[0]["rebalance_date"]) == pd.Timestamp("2026-08-31")

        cfg.leader_rescue_backtest_mode = "off"
        disabled = apply_leader_rescue_backtest_mode_filter(cfg, get_paths(cfg), monthly)
        assert list(disabled["ticker"]) == ["EME"]


def test_main_pipeline_wiring_is_present() -> None:
    source = (ROOT / "r1000_pipeline.py").read_text(encoding="utf-8")
    for token in (
        "include_core_tracking",
        "load_core_tracking_universe_frame",
        "core_tracking_added_to_frames",
        "core_tracking_overlay",
    ):
        assert token in source, token


def main() -> int:
    test_tiered_loaders_are_exact_and_deduplicated()
    test_global_alpha_union_adds_only_missing_tracking_names()
    test_overlay_only_rows_are_latest_only()
    test_main_pipeline_wiring_is_present()
    print("core_tracking_universe_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


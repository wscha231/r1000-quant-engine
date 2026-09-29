#!/usr/bin/env python3
"""Focused contract checks for the healthcare/biotech universe overlay."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


EXPECTED_TICKERS = {
    "HALO", "CAI", "VCYT", "TMDX", "NBIX", "ACAD", "TGTX", "REGN",
    "ADMA", "EXEL", "ILMN", "TEM", "WGS", "CDNA", "CSTL", "NTRA",
    "GH", "TWST", "TXG", "GRAL",
}


def test_overlay_loaders_are_exact_and_deduplicated() -> None:
    from aggressive.universe import load_healthcare_biotech_universe
    from r1000_config import EngineConfig
    from r1000_pipeline import load_healthcare_biotech_universe_frame

    tickers, metadata = load_healthcare_biotech_universe()
    assert set(tickers) == EXPECTED_TICKERS
    assert len(tickers) == len(EXPECTED_TICKERS)
    assert len(metadata) == len(EXPECTED_TICKERS)

    frame = load_healthcare_biotech_universe_frame(EngineConfig())
    assert set(frame["ticker"]) == EXPECTED_TICKERS
    assert len(frame) == len(EXPECTED_TICKERS)
    assert set(frame["universe_source"]) == {"healthcare_biotech_overlay"}
    assert set(frame["sector"]) == {"Health Care"}


def test_global_alpha_union_adds_missing_names_without_network() -> None:
    import aggressive.universe as universe

    original_fetch = universe.fetch_iwb_holdings
    try:
        universe.fetch_iwb_holdings = lambda force_refresh=False: pd.DataFrame(
            {
                "ticker": ["HALO", "REGN", "BASE"],
                "Name": ["Halozyme", "Regeneron", "Base"],
                "Sector": ["Health Care", "Health Care", "Industrials"],
            }
        )
        tickers, metadata = universe.load_universe("global_alpha_universe")
    finally:
        universe.fetch_iwb_holdings = original_fetch

    assert EXPECTED_TICKERS.issubset(set(tickers))
    assert metadata["healthcare_biotech_count"] == len(EXPECTED_TICKERS)
    assert "VCYT" in metadata["healthcare_biotech_added"]
    assert "HALO" not in metadata["healthcare_biotech_added"]


def test_current_only_overlay_is_not_backfilled_into_history() -> None:
    from r1000_config import EngineConfig
    from r1000_helpers import get_paths
    from r1000_pipeline import apply_leader_rescue_backtest_mode_filter

    monthly = pd.DataFrame(
        {
            "rebalance_date": pd.to_datetime(["2026-07-31", "2026-08-31", "2026-07-31"]),
            "ticker": ["VCYT", "VCYT", "BASE"],
            "universe_source": [
                "healthcare_biotech_overlay",
                "healthcare_biotech_overlay",
                "current_constituents_proxy",
            ],
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        cfg = EngineConfig(base_dir=tmp)
        cfg.leader_rescue_backtest_mode = "latest_only"
        latest_only = apply_leader_rescue_backtest_mode_filter(cfg, get_paths(cfg), monthly)
        assert list(latest_only["ticker"]) == ["VCYT", "BASE"]
        assert pd.Timestamp(latest_only.iloc[0]["rebalance_date"]) == pd.Timestamp("2026-08-31")

        cfg.leader_rescue_backtest_mode = "full_proxy"
        full_proxy = apply_leader_rescue_backtest_mode_filter(cfg, get_paths(cfg), monthly)
        assert len(full_proxy) == len(monthly)

        cfg.leader_rescue_backtest_mode = "off"
        disabled = apply_leader_rescue_backtest_mode_filter(cfg, get_paths(cfg), monthly)
        assert list(disabled["ticker"]) == ["BASE"]


def test_main_pipeline_wiring_is_present() -> None:
    source = (ROOT / "r1000_pipeline.py").read_text(encoding="utf-8")
    for token in (
        "include_healthcare_biotech",
        "load_healthcare_biotech_universe_frame",
        "healthcare_biotech_added_to_frames",
        "healthcare_biotech_overlay",
    ):
        assert token in source, token


def main() -> int:
    test_overlay_loaders_are_exact_and_deduplicated()
    test_global_alpha_union_adds_missing_names_without_network()
    test_current_only_overlay_is_not_backfilled_into_history()
    test_main_pipeline_wiring_is_present()
    print("healthcare_biotech_universe_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


#!/usr/bin/env python3
"""Smoke checks for candidate-universe fallback after live source failures."""
from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import r1000_pipeline as pipeline  # noqa: E402
from r1000_config import EngineConfig  # noqa: E402
from r1000_helpers import get_paths  # noqa: E402


def _source_frame(tickers: list[str], source: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": tickers,
            "Name": tickers,
            "sector": ["Tech"] * len(tickers),
            "cik10": [pd.NA] * len(tickers),
            "universe_source": [source] * len(tickers),
        }
    )


def _patch(name: str, value, originals: dict[str, object]) -> None:
    originals[name] = getattr(pipeline, name)
    setattr(pipeline, name, value)


def test_previous_broad_base_cache_is_reused_when_iwb_fails() -> None:
    with TemporaryDirectory() as tmp:
        cfg = EngineConfig(base_dir=tmp)
        cfg.universe_mode = "global_alpha_universe"
        cfg.use_wikipedia_lists = False
        cfg.leader_rescue_universe_enabled = False
        paths = get_paths(cfg)
        paths["feature_store"].mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [
                {"ticker": "AAPL", "Name": "Apple", "sector": "Tech", "cik10": "0000320193", "universe_source": "current_constituents_proxy"},
                {"ticker": "MSFT", "Name": "Microsoft", "sector": "Tech", "cik10": "0000789019", "universe_source": "current_constituents_proxy"},
                {"ticker": "OLDADR", "Name": "Old ADR", "sector": "ADR", "cik10": pd.NA, "universe_source": "adr_whitelist"},
            ]
        ).to_parquet(paths["feature_store"] / "candidate_universe_latest.parquet", index=False)

        originals: dict[str, object] = {}
        try:
            _patch("load_historical_universe_membership", lambda cfg, paths: pd.DataFrame(), originals)
            _patch("read_ishares_holdings", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("IWB unavailable")), originals)
            _patch("load_sec_company_tickers", lambda cfg, paths: pd.DataFrame({"ticker": ["TSM"], "title": ["TSMC"], "cik10": [1046179]}), originals)
            _patch("load_adr_universe_frame", lambda min_mcap_usd_b=8.0: _source_frame(["TSM"], "adr_whitelist"), originals)
            _patch("load_cycle_play_universe_frame", lambda **kwargs: _source_frame(["RKLB"], "cycle_play_whitelist"), originals)
            _patch("load_strategic_global_hardware_universe_frame", lambda cfg: _source_frame(["ASML"], "strategic_global_hardware"), originals)
            _patch("load_etf_thematic_overlay_frame", lambda cfg: _source_frame(["IONQ"], "etf_thematic_overlay"), originals)

            out = pipeline.build_candidate_universe(cfg, paths)
        finally:
            for name, original in originals.items():
                setattr(pipeline, name, original)

        tickers = set(out["ticker"].astype(str))
        assert {"AAPL", "MSFT"}.issubset(tickers)
        assert {"TSM", "RKLB", "ASML", "IONQ"}.issubset(tickers)
        assert "OLDADR" not in tickers, "overlay-only rows from the previous cache must not masquerade as base universe"
        assert pipeline._broad_base_universe_mask(out).any()


def test_committed_latest_scored_snapshot_seeds_first_cloud_run() -> None:
    with TemporaryDirectory() as tmp:
        cfg = EngineConfig(base_dir=tmp)
        cfg.universe_mode = "global_alpha_universe"
        cfg.use_wikipedia_lists = False
        cfg.leader_rescue_universe_enabled = False
        paths = get_paths(cfg)

        latest_dir = Path(tmp) / "cloud_results" / "full_rebuild" / "latest_global_alpha_universe"
        latest_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [
                {"ticker": "AAPL", "Name": "Apple", "sector": "Tech", "cik10": "0000320193", "universe_source": "current_constituents_proxy"},
                {"ticker": "MSFT", "Name": "Microsoft", "sector": "Tech", "cik10": "0000789019", "universe_source": "current_constituents_proxy"},
                {"ticker": "OLDADR", "Name": "Old ADR", "sector": "ADR", "cik10": pd.NA, "universe_source": "adr_whitelist"},
            ]
        ).to_csv(latest_dir / "scored_latest.csv", index=False)

        originals: dict[str, object] = {}
        try:
            _patch("load_historical_universe_membership", lambda cfg, paths: pd.DataFrame(), originals)
            _patch("read_ishares_holdings", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("IWB unavailable")), originals)
            _patch("load_sec_company_tickers", lambda cfg, paths: pd.DataFrame({"ticker": ["TSM"], "title": ["TSMC"], "cik10": [1046179]}), originals)
            _patch("load_adr_universe_frame", lambda min_mcap_usd_b=8.0: _source_frame(["TSM"], "adr_whitelist"), originals)
            _patch("load_cycle_play_universe_frame", lambda **kwargs: _source_frame(["RKLB"], "cycle_play_whitelist"), originals)
            _patch("load_strategic_global_hardware_universe_frame", lambda cfg: _source_frame(["ASML"], "strategic_global_hardware"), originals)
            _patch("load_etf_thematic_overlay_frame", lambda cfg: _source_frame(["IONQ"], "etf_thematic_overlay"), originals)

            out = pipeline.build_candidate_universe(cfg, paths)
        finally:
            for name, original in originals.items():
                setattr(pipeline, name, original)

        tickers = set(out["ticker"].astype(str))
        assert {"AAPL", "MSFT", "TSM", "RKLB", "ASML", "IONQ"}.issubset(tickers)
        assert "OLDADR" not in tickers, "committed scored fallback must only seed broad-base rows"
        assert pipeline._broad_base_universe_mask(out).any()


def test_overlay_only_first_run_fails_with_clear_error() -> None:
    with TemporaryDirectory() as tmp:
        cfg = EngineConfig(base_dir=tmp)
        cfg.universe_mode = "global_alpha_universe"
        cfg.use_wikipedia_lists = False
        cfg.leader_rescue_universe_enabled = False
        paths = get_paths(cfg)

        originals: dict[str, object] = {}
        try:
            _patch("load_historical_universe_membership", lambda cfg, paths: pd.DataFrame(), originals)
            _patch("read_ishares_holdings", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("IWB unavailable")), originals)
            _patch("load_sec_company_tickers", lambda cfg, paths: pd.DataFrame({"ticker": [], "title": [], "cik10": []}), originals)
            _patch("load_adr_universe_frame", lambda min_mcap_usd_b=8.0: _source_frame(["TSM"], "adr_whitelist"), originals)
            _patch("load_cycle_play_universe_frame", lambda **kwargs: _source_frame(["RKLB"], "cycle_play_whitelist"), originals)
            _patch("load_strategic_global_hardware_universe_frame", lambda cfg: _source_frame(["ASML"], "strategic_global_hardware"), originals)
            _patch("load_etf_thematic_overlay_frame", lambda cfg: _source_frame(["IONQ"], "etf_thematic_overlay"), originals)

            try:
                pipeline.build_candidate_universe(cfg, paths)
            except RuntimeError as exc:
                assert "Broad base universe unavailable" in str(exc)
            else:
                raise AssertionError("overlay-only global-alpha run should fail instead of continuing")
        finally:
            for name, original in originals.items():
                setattr(pipeline, name, original)


if __name__ == "__main__":
    test_previous_broad_base_cache_is_reused_when_iwb_fails()
    test_committed_latest_scored_snapshot_seeds_first_cloud_run()
    test_overlay_only_first_run_fails_with_clear_error()
    print("candidate_universe_fallback_smoke: PASS")

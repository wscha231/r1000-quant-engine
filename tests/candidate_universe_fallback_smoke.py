#!/usr/bin/env python3
"""Smoke tests for cold-run broad-base universe recovery.

GitHub hosted runners can fail live IWB/Wikipedia broad source fetches while
ADR/cycle/hardware overlays are still available. That overlay-only state should
recover from committed latest broad-base artifacts, or fail early with a clear
error instead of reaching walk-forward training with zero OOS rows.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_config import EngineConfig
from r1000_pipeline import (
    _combine_candidate_universe_sources,
    _committed_latest_broad_base_universe,
    _ensure_broad_base_universe,
    _has_broad_base_universe,
)


def _write_committed_latest(base: Path) -> Path:
    p = base / "cloud_results" / "full_rebuild" / "latest_global_alpha_universe" / "scored_latest.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "Name": "APPLE INC",
                "sector": "Information Technology",
                "cik10": 320193,
                "universe_source": "current_constituents_proxy",
            },
            {
                "ticker": "LRCX",
                "Name": "LAM RESEARCH CORP",
                "sector": "Information Technology",
                "cik10": "707549",
                "universe_source": "current_constituents_proxy+strategic_global_hardware",
            },
            {
                "ticker": "BABA",
                "Name": "ALIBABA GROUP HOLDING LTD",
                "sector": "Consumer Discretionary",
                "cik10": "1577552",
                "universe_source": "adr_whitelist",
            },
            {
                "ticker": "OKLO",
                "Name": "OKLO INC",
                "sector": "Utilities",
                "cik10": "",
                "universe_source": "cycle_play_whitelist",
            },
        ]
    ).to_csv(p, index=False)
    return p


def test_committed_latest_recovery_keeps_only_broad_base_rows() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        _write_committed_latest(base)

        recovered = _committed_latest_broad_base_universe({"base": base}, "global_alpha_universe")

        assert set(recovered["ticker"]) == {"AAPL", "LRCX"}, recovered
        assert "BABA" not in set(recovered["ticker"])
        assert "OKLO" not in set(recovered["ticker"])
        assert recovered.loc[recovered["ticker"].eq("AAPL"), "cik10"].iloc[0] == "0000320193"
        assert recovered["universe_source"].str.contains("committed_latest_recovery", regex=False).all()
        assert _has_broad_base_universe(recovered)


def test_overlay_only_global_alpha_recovers_before_walkforward() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        _write_committed_latest(base)
        overlay_only = pd.DataFrame(
            [
                {
                    "ticker": "BABA",
                    "Name": "ALIBABA GROUP HOLDING LTD",
                    "sector": "Consumer Discretionary",
                    "cik10": "0001577552",
                    "universe_source": "adr_whitelist",
                }
            ]
        )

        frames = _ensure_broad_base_universe(
            [overlay_only],
            prev=pd.DataFrame(),
            cfg=EngineConfig(base_dir=str(base), universe_mode="global_alpha_universe"),
            paths={"base": base},
            universe_mode="global_alpha_universe",
        )
        combined = _combine_candidate_universe_sources(pd.concat(frames, ignore_index=True))

        assert "BABA" in set(combined["ticker"])
        assert {"AAPL", "LRCX"}.issubset(set(combined["ticker"]))
        assert _has_broad_base_universe(combined)


def test_overlay_only_first_run_fails_clearly_without_recovery() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        overlay_only = pd.DataFrame(
            [
                {
                    "ticker": "BABA",
                    "Name": "ALIBABA GROUP HOLDING LTD",
                    "sector": "Consumer Discretionary",
                    "cik10": "0001577552",
                    "universe_source": "adr_whitelist",
                }
            ]
        )

        try:
            _ensure_broad_base_universe(
                [overlay_only],
                prev=pd.DataFrame(),
                cfg=EngineConfig(base_dir=str(base), universe_mode="global_alpha_universe"),
                paths={"base": base},
                universe_mode="global_alpha_universe",
            )
        except RuntimeError as exc:
            msg = str(exc)
            assert "Broad-base universe sources unavailable" in msg
            assert "overlay-only universe" in msg
        else:
            raise AssertionError("overlay-only global alpha universe should fail clearly without recovery")


if __name__ == "__main__":
    test_committed_latest_recovery_keeps_only_broad_base_rows()
    test_overlay_only_global_alpha_recovers_before_walkforward()
    test_overlay_only_first_run_fails_clearly_without_recovery()
    print("candidate_universe_fallback_smoke: PASS")

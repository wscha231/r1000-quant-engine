#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_regime_nowcast_dial import run  # noqa: E402


def test_regime_nowcast_dial_scores_warning_panel_without_policy_hook() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        panel = root / "signals.csv"
        pd.DataFrame(
            [
                {"date": "2026-07-03", "signal_name": "spy_below_200dma", "warning_triggered": True, "covered": True},
                {"date": "2026-07-03", "signal_name": "qqq_below_200dma", "warning_triggered": True, "covered": True},
                {"date": "2026-07-03", "signal_name": "qqq_spy_rs_negative_1m_3m", "warning_triggered": True, "covered": True},
                {"date": "2026-07-03", "signal_name": "soxx_smh_rs_negative_vs_qqq", "warning_triggered": True, "covered": True},
                {"date": "2026-07-03", "signal_name": "universe_above_200dma_below_40pct", "warning_triggered": True, "covered": True},
                {"date": "2026-07-03", "signal_name": "vix_spike_or_above_25", "warning_triggered": False, "covered": True},
            ]
        ).to_csv(panel, index=False)
        payload = run(
            argparse.Namespace(
                signal_panel=str(panel),
                price_cache=str(root / "cache"),
                as_of_date="2026-07-03",
                output_dir=str(root / "out"),
            )
        )
        assert payload["status"] == "completed", payload
        assert payload["current_state"] == "CORRECTION", payload
        assert payload["bear_warning_score"] == 5, payload
        assert payload["covered_signal_count"] == 6, payload
        assert len(payload["missing_signals"]) == 6, payload
        assert "shock_review" in payload["required_review_action"], payload
        assert payload["policy_hook_allowed"] is False
        assert payload["market_timing_claim_allowed"] is False
        assert (root / "out" / "signal_panel.csv").exists()
        assert (root / "out" / "state_history.csv").exists()


def test_regime_nowcast_dial_requires_six_covered_signals() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        panel = root / "signals.csv"
        pd.DataFrame(
            [
                {"date": "2026-07-03", "signal_name": "spy_below_200dma", "warning_triggered": True, "covered": True},
                {"date": "2026-07-03", "signal_name": "qqq_below_200dma", "warning_triggered": True, "covered": True},
                {"date": "2026-07-03", "signal_name": "qqq_spy_rs_negative_1m_3m", "warning_triggered": True, "covered": True},
                {"date": "2026-07-03", "signal_name": "soxx_smh_rs_negative_vs_qqq", "warning_triggered": True, "covered": True},
                {"date": "2026-07-03", "signal_name": "universe_above_200dma_below_40pct", "warning_triggered": True, "covered": True},
            ]
        ).to_csv(panel, index=False)
        payload = run(
            argparse.Namespace(
                signal_panel=str(panel),
                price_cache=str(root / "cache"),
                as_of_date="2026-07-03",
                output_dir=str(root / "out"),
            )
        )
        assert payload["status"] == "data_insufficient", payload
        assert payload["current_state"] == "DATA_INSUFFICIENT", payload
        assert payload["bear_warning_score"] == 5, payload
        assert payload["policy_hook_allowed"] is False


def test_regime_nowcast_dial_does_not_accept_state_override_by_default() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        panel = root / "signals.csv"
        pd.DataFrame(
            [
                {
                    "date": "2026-07-03",
                    "signal_name": "spy_below_200dma",
                    "warning_triggered": False,
                    "covered": True,
                    "state_override": "BEAR",
                },
                {"date": "2026-07-03", "signal_name": "qqq_below_200dma", "warning_triggered": False, "covered": True},
                {"date": "2026-07-03", "signal_name": "qqq_spy_rs_negative_1m_3m", "warning_triggered": False, "covered": True},
                {"date": "2026-07-03", "signal_name": "soxx_smh_rs_negative_vs_qqq", "warning_triggered": False, "covered": True},
                {"date": "2026-07-03", "signal_name": "universe_above_200dma_below_40pct", "warning_triggered": False, "covered": True},
                {"date": "2026-07-03", "signal_name": "vix_spike_or_above_25", "warning_triggered": False, "covered": True},
            ]
        ).to_csv(panel, index=False)
        payload = run(
            argparse.Namespace(
                signal_panel=str(panel),
                price_cache=str(root / "cache"),
                as_of_date="2026-07-03",
                output_dir=str(root / "out"),
                allow_state_override=False,
            )
        )
        assert payload["status"] == "completed", payload
        assert payload["current_state"] == "BULL", payload
        assert payload["state_override_allowed"] is False
        state_history = pd.read_csv(root / "out" / "state_history.csv")
        assert state_history["state_override_applied"].astype(bool).sum() == 0


def main() -> int:
    test_regime_nowcast_dial_scores_warning_panel_without_policy_hook()
    test_regime_nowcast_dial_requires_six_covered_signals()
    test_regime_nowcast_dial_does_not_accept_state_override_by_default()
    print("regime_nowcast_dial_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

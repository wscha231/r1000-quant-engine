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


def test_service_mode_requires_critical_groups() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        panel = root / "signals.csv"
        pd.DataFrame(
            [
                {"date": "2026-07-03", "signal_name": "spy_below_200dma", "warning_triggered": False, "covered": True},
                {"date": "2026-07-03", "signal_name": "qqq_below_200dma", "warning_triggered": False, "covered": True},
                {"date": "2026-07-03", "signal_name": "qqq_spy_rs_negative_1m_3m", "warning_triggered": False, "covered": True},
                {"date": "2026-07-03", "signal_name": "hy_oas_widening_threshold", "warning_triggered": False, "covered": True},
                {
                    "date": "2026-07-03",
                    "signal_name": "yield_curve_inversion_or_steepening_warning",
                    "warning_triggered": False,
                    "covered": True,
                },
                {"date": "2026-07-03", "signal_name": "sahm_unemployment_momentum_warning", "warning_triggered": False, "covered": True},
                {"date": "2026-07-03", "signal_name": "eps_revision_breadth_negative", "warning_triggered": False, "covered": True},
                {"date": "2026-07-03", "signal_name": "ai_capex_bucket_rs_breakdown", "warning_triggered": False, "covered": True},
            ]
        ).to_csv(panel, index=False)
        payload = run(
            argparse.Namespace(
                signal_panel=str(panel),
                price_cache=str(root / "cache"),
                as_of_date="2026-07-03",
                output_dir=str(root / "out"),
                coverage_mode="service",
                allow_state_override=False,
            )
        )
        assert payload["status"] == "data_insufficient", payload
        assert payload["current_state"] == "DATA_INSUFFICIENT", payload
        assert "volatility_stress" in payload["missing_critical_groups"], payload
        assert "breadth" in payload["missing_critical_groups"], payload
        assert payload["policy_hook_allowed"] is False
        assert payload["public_display_allowed"] is False


def main() -> int:
    test_service_mode_requires_critical_groups()
    print("regime_nowcast_data_insufficient_critical_group_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

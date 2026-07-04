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


def test_service_mode_ignores_state_override_without_flag() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        panel = root / "signals.csv"
        rows = []
        for signal_name in [
            "spy_below_200dma",
            "qqq_below_200dma",
            "qqq_spy_rs_negative_1m_3m",
            "soxx_smh_rs_negative_vs_qqq",
            "universe_above_200dma_below_40pct",
            "vix_spike_or_above_25",
            "hy_oas_widening_threshold",
            "ai_capex_bucket_rs_breakdown",
        ]:
            rows.append(
                {
                    "date": "2026-07-03",
                    "signal_name": signal_name,
                    "warning_triggered": False,
                    "covered": True,
                    "state_override": "BEAR",
                }
            )
        pd.DataFrame(rows).to_csv(panel, index=False)
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
        assert payload["current_state"] == "BULL", payload
        assert payload["state_computed_from_data"] is True, payload
        assert payload["state_override_used"] is False, payload
        assert payload["allow_state_override"] is False, payload


def main() -> int:
    test_service_mode_ignores_state_override_without_flag()
    print("state_override_service_forbidden_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

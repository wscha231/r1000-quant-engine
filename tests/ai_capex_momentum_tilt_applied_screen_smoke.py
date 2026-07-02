#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_ai_capex_momentum_tilt_applied_screen import run_screen  # noqa: E402


def test_applied_screen_reports_main_changes_and_concentrated_noop() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "target.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-31", "ticker": "CASH", "weight": 0.10, "target_weight": 0.10},
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "MEM",
                    "sector": "Information Technology",
                    "industry_group": "Semiconductor Memory",
                    "theme": "HBM memory tight supply",
                    "rs_benchmark_3m": 0.20,
                    "weight": 0.10,
                    "target_weight": 0.10,
                    "effective_single_weight_cap": 0.12,
                },
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "OTHER",
                    "sector": "Industrials",
                    "industry_group": "Machinery",
                    "rs_benchmark_3m": -0.02,
                    "weight": 0.20,
                    "target_weight": 0.20,
                    "effective_single_weight_cap": 0.50,
                },
            ]
        ).to_csv(target, index=False)

        main = run_screen(target, root / "main", portfolio_kind="main")
        concentrated = run_screen(target, root / "conc", portfolio_kind="concentrated")

        assert main["status"] == "screen_pass_applied"
        assert main["applied_event_count"] > 0
        assert main["cash_unchanged_all_dates"] is True
        assert main["ticker_set_preserved_all_dates"] is True
        assert concentrated["status"] == "blocked_no_applied_events"
        assert concentrated["total_abs_weight_delta"] == 0.0


if __name__ == "__main__":
    test_applied_screen_reports_main_changes_and_concentrated_noop()
    print("ai_capex_momentum_tilt_applied_screen_smoke: PASS")

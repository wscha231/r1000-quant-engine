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


def test_earnings_signals_add_guidance_coverage_and_filter_future() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        panel = root / "signals.csv"
        earnings = root / "earnings_revision_signals.parquet"
        rows = []
        for idx in range(10):
            ticker = f"T{idx:02d}"
            rows.append(
                {
                    "ticker": ticker,
                    "available_from": "2026-05-01",
                    "eps_estimate": 1.0,
                    "eps_revision_13w": 0.0,
                    "positive_guidance_flag": 0,
                    "negative_guidance_flag": 0,
                    "sector_eps_revision_breadth": 0.80,
                    "source_type": "vendor_estimate_revision",
                }
            )
            rows.append(
                {
                    "ticker": ticker,
                    "available_from": "2026-06-15",
                    "eps_estimate": 1.1 + idx * 0.01,
                    "eps_revision_13w": 0.04 + idx * 0.001,
                    "positive_guidance_flag": 1 if idx < 6 else 0,
                    "negative_guidance_flag": 0,
                    "sector_eps_revision_breadth": 0.80,
                    "source_type": "vendor_estimate_revision",
                }
            )
        rows.append({"ticker": "FUTURE", "available_from": "2026-12-01", "eps_revision_13w": -1.00, "positive_guidance_flag": 0, "negative_guidance_flag": 1, "sector_eps_revision_breadth": 0.0, "source_type": "vendor_estimate_revision"})
        pd.DataFrame(rows).to_parquet(earnings, index=False)
        pd.DataFrame(
            [
                {"date": "2026-07-01", "signal_name": "spy_below_200dma", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "qqq_below_200dma", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "qqq_spy_rs_negative_1m_3m", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "vix_spike_or_above_25", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "universe_above_200dma_below_40pct", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "ai_capex_bucket_rs_breakdown", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "hy_oas_widening_threshold", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "yield_curve_inversion_or_steepening_warning", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "sahm_unemployment_momentum_warning", "warning_triggered": False, "covered": True},
            ]
        ).to_csv(panel, index=False)

        payload = run(
            argparse.Namespace(
                signal_panel=str(panel),
                price_cache=str(root / "cache_prices"),
                macro_cache=str(root / "cache_macro"),
                earnings_signals=str(earnings),
                as_of_date="2026-07-01",
                output_dir=str(root / "out"),
                coverage_mode="service",
                allow_state_override=False,
            )
        )

        assert payload["status"] == "completed", payload
        assert payload["covered_signal_count"] == 11, payload
        assert payload["critical_group_coverage"]["earnings_guidance"] is True, payload
        assert payload["missing_critical_groups"] == [], payload
        assert payload["triggered_signals"] == [], payload
        assert payload["policy_hook_allowed"] is False
        assert payload["public_display_allowed"] is False
        signal_panel = pd.read_csv(root / "out" / "signal_panel.csv")
        earned = signal_panel[signal_panel["source"].eq("earnings_revision_signals")]
        assert int(earned["earnings_signal_row_count"].max()) == 10
        assert int(earned["earnings_revision_observed_count"].max()) >= 10


def test_zero_only_earnings_signals_do_not_count_as_coverage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        panel = root / "signals.csv"
        earnings = root / "earnings_revision_signals.parquet"
        rows = [
            {
                "ticker": f"T{idx}",
                "available_from": "2026-06-01",
                "eps_revision_13w": 0.0,
                "positive_guidance_flag": 0,
                "negative_guidance_flag": 0,
                "sector_eps_revision_breadth": 0.0,
                "source_type": "vendor_estimate_revision",
            }
            for idx in range(8)
        ]
        pd.DataFrame(rows).to_parquet(earnings, index=False)
        pd.DataFrame(
            [
                {"date": "2026-07-01", "signal_name": "spy_below_200dma", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "qqq_below_200dma", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "qqq_spy_rs_negative_1m_3m", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "vix_spike_or_above_25", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "universe_above_200dma_below_40pct", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "ai_capex_bucket_rs_breakdown", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "hy_oas_widening_threshold", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "yield_curve_inversion_or_steepening_warning", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "sahm_unemployment_momentum_warning", "warning_triggered": False, "covered": True},
            ]
        ).to_csv(panel, index=False)

        payload = run(
            argparse.Namespace(
                signal_panel=str(panel),
                price_cache=str(root / "cache_prices"),
                macro_cache=str(root / "cache_macro"),
                earnings_signals=str(earnings),
                as_of_date="2026-07-01",
                output_dir=str(root / "out_zero"),
                coverage_mode="service",
                allow_state_override=False,
            )
        )

        assert payload["critical_group_coverage"]["earnings_guidance"] is False, payload
        assert "earnings_guidance" in payload["missing_critical_groups"], payload
        signal_panel = pd.read_csv(root / "out_zero" / "signal_panel.csv")
        assert not signal_panel["source"].eq("earnings_revision_signals").any()


def test_sec_actual_snapshot_earnings_do_not_count_as_guidance_coverage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        panel = root / "signals.csv"
        earnings = root / "earnings_revision_signals.parquet"
        rows = [
            {
                "ticker": f"A{idx}",
                "available_from": "2026-06-01",
                "eps_revision_13w": 0.10,
                "positive_guidance_flag": 1,
                "negative_guidance_flag": 0,
                "sector_eps_revision_breadth": 0.80,
                "source_type": "sec_actual_snapshot",
            }
            for idx in range(8)
        ]
        pd.DataFrame(rows).to_parquet(earnings, index=False)
        pd.DataFrame(
            [
                {"date": "2026-07-01", "signal_name": "spy_below_200dma", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "qqq_below_200dma", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "qqq_spy_rs_negative_1m_3m", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "vix_spike_or_above_25", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "universe_above_200dma_below_40pct", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "ai_capex_bucket_rs_breakdown", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "hy_oas_widening_threshold", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "yield_curve_inversion_or_steepening_warning", "warning_triggered": False, "covered": True},
                {"date": "2026-07-01", "signal_name": "sahm_unemployment_momentum_warning", "warning_triggered": False, "covered": True},
            ]
        ).to_csv(panel, index=False)

        payload = run(
            argparse.Namespace(
                signal_panel=str(panel),
                price_cache=str(root / "cache_prices"),
                macro_cache=str(root / "cache_macro"),
                earnings_signals=str(earnings),
                as_of_date="2026-07-01",
                output_dir=str(root / "out_actuals"),
                coverage_mode="service",
                allow_state_override=False,
            )
        )

        assert payload["critical_group_coverage"]["earnings_guidance"] is False, payload
        assert "earnings_guidance" in payload["missing_critical_groups"], payload
        signal_panel = pd.read_csv(root / "out_actuals" / "signal_panel.csv")
        assert not signal_panel["source"].eq("earnings_revision_signals").any()


def main() -> int:
    test_earnings_signals_add_guidance_coverage_and_filter_future()
    test_zero_only_earnings_signals_do_not_count_as_coverage()
    test_sec_actual_snapshot_earnings_do_not_count_as_guidance_coverage()
    print("regime_nowcast_earnings_guidance_coverage_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

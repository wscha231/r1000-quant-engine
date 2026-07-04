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


def _write_macro(cache: Path, key: str, series_id: str, values: list[float], dates: pd.DatetimeIndex) -> None:
    frame = pd.DataFrame({"date": dates.date.astype(str), "value": values})
    frame.to_parquet(cache / f"fred_{key}_{series_id}.parquet", index=False)


def test_macro_cache_adds_credit_liquidity_coverage_without_policy_hook() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        macro = root / "cache_macro"
        macro.mkdir()
        dates = pd.bdate_range("2026-01-01", periods=40)
        panel = root / "signals.csv"
        pd.DataFrame(
            [
                {"date": "2026-02-25", "signal_name": "spy_below_200dma", "warning_triggered": False, "covered": True},
                {"date": "2026-02-25", "signal_name": "qqq_below_200dma", "warning_triggered": False, "covered": True},
                {"date": "2026-02-25", "signal_name": "qqq_spy_rs_negative_1m_3m", "warning_triggered": False, "covered": True},
                {"date": "2026-02-25", "signal_name": "vix_spike_or_above_25", "warning_triggered": False, "covered": True},
                {"date": "2026-02-25", "signal_name": "universe_above_200dma_below_40pct", "warning_triggered": False, "covered": True},
                {"date": "2026-02-25", "signal_name": "ai_capex_bucket_rs_breakdown", "warning_triggered": False, "covered": True},
            ]
        ).to_csv(panel, index=False)
        _write_macro(macro, "hy_oas", "BAMLH0A0HYM2", [3.0] * 40, dates)
        _write_macro(macro, "dgs10", "DGS10", [4.0] * 40, dates)
        _write_macro(macro, "dgs3mo", "DGS3MO", [3.8] * 40, dates)
        _write_macro(macro, "sahm", "SAHMREALTIME", [0.1] * 40, dates)

        payload = run(
            argparse.Namespace(
                signal_panel=str(panel),
                price_cache=str(root / "cache_prices"),
                macro_cache=str(macro),
                as_of_date="2026-02-25",
                output_dir=str(root / "out"),
                coverage_mode="service",
                allow_state_override=False,
            )
        )

        assert payload["status"] == "completed", payload
        assert payload["current_state"] == "BULL", payload
        assert payload["covered_signal_count"] == 9, payload
        assert payload["critical_group_coverage"]["credit_liquidity"] is True, payload
        assert payload["critical_group_coverage"]["earnings_guidance"] is False, payload
        assert payload["missing_critical_groups"] == ["earnings_guidance"], payload
        assert payload["policy_hook_allowed"] is False
        assert payload["public_display_allowed"] is False
        assert payload["live_trading_allowed"] is False


def main() -> int:
    test_macro_cache_adds_credit_liquidity_coverage_without_policy_hook()
    print("regime_nowcast_macro_cache_coverage_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

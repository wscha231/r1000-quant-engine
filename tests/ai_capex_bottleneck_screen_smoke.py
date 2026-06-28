#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_ai_capex_bottleneck_screen import main, prepare  # noqa: E402


def _rows() -> pd.DataFrame:
    rows = []
    for idx, date in enumerate(["2022-01-31", "2023-01-31", "2024-07-31", "2025-01-31"]):
        rows.append(
            {
                "rebalance_date": date,
                "ticker": f"MEM{idx}",
                "industry": "Semiconductor Memory",
                "theme": "HBM memory tight supply price increase backlog",
                "eps_revision_13w": 0.10,
                "revenue_revision_13w": 0.05,
                "rs_benchmark_3m": 0.08,
                "forward_126d_excess": 0.12,
                "forward_63d_excess": 0.06,
            }
        )
    rows.append(
        {
            "rebalance_date": "2024-07-31",
            "ticker": "VALUE",
            "industry": "Retail",
            "eps_revision_13w": -0.02,
            "rs_benchmark_3m": -0.04,
            "forward_126d_excess": 0.99,
        }
    )
    return pd.DataFrame(rows)


def _earnings_signals() -> pd.DataFrame:
    rows = []
    for idx, date in enumerate(["2021-12-15", "2022-12-15", "2024-07-01", "2024-12-15"]):
        rows.append(
            {
                "ticker": f"MEM{idx}",
                "available_from": date,
                "eps_revision_13w": 0.20,
                "revenue_revision_13w": 0.10,
                "positive_guidance_flag": 1,
                "negative_guidance_flag": 0,
            }
        )
        rows.append(
            {
                "ticker": f"MEM{idx}",
                "available_from": "2030-01-01",
                "eps_revision_13w": -0.99,
                "revenue_revision_13w": -0.99,
                "positive_guidance_flag": 0,
                "negative_guidance_flag": 1,
            }
        )
    return pd.DataFrame(rows)


def test_prepare_marks_forward_returns_audit_only_inputs() -> None:
    prepared, signal_meta = prepare(_rows(), _earnings_signals())
    target = prepared[prepared["ticker"].eq("MEM0")].iloc[0]
    assert target["ai_capex_value_chain_bucket"] == "AI_MEMORY"
    assert bool(target["ai_bottleneck_high"])
    assert bool(target["eps_revision_positive"])
    assert target["earnings_confirmation_source"] == "vendor_eps_or_revenue_revision"
    assert signal_meta["earnings_signal_joined_rows"] == 4
    assert signal_meta["earnings_signal_future_rows_filtered"] == 4
    assert "forward_126d_excess_audit_only" in prepared.columns


def test_cli_screen_passes_only_to_default_off_hook_stage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        inp = root / "candidates.csv"
        signals = root / "earnings_signals.csv"
        out = root / "out"
        _rows().to_csv(inp, index=False)
        _earnings_signals().to_csv(signals, index=False)
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "run_ai_capex_bottleneck_screen.py",
                "--input",
                str(inp),
                "--output-dir",
                str(out),
                "--earnings-signals",
                str(signals),
                "--min-count",
                "3",
                "--min-oos-count",
                "1",
            ]
            assert main() == 0
        finally:
            sys.argv = old_argv
        payload = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert payload["screen_pass"] is True
        assert payload["used_forward_return_in_ranking"] is False
        assert payload["production_activation_allowed"] is False
        assert payload["earnings_signal_joined_rows"] == 4
        assert payload["earnings_confirmation_source_counts"]["vendor_eps_or_revenue_revision"] == 4


if __name__ == "__main__":
    test_prepare_marks_forward_returns_audit_only_inputs()
    test_cli_screen_passes_only_to_default_off_hook_stage()
    print("ai_capex_bottleneck_screen_smoke: PASS")

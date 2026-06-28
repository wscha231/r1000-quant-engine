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


def test_prepare_marks_forward_returns_audit_only_inputs() -> None:
    prepared = prepare(_rows())
    target = prepared[prepared["ticker"].eq("MEM0")].iloc[0]
    assert target["ai_capex_value_chain_bucket"] == "AI_MEMORY"
    assert bool(target["ai_bottleneck_high"])
    assert bool(target["eps_revision_positive"])
    assert "forward_126d_excess_audit_only" in prepared.columns


def test_cli_screen_passes_only_to_default_off_hook_stage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        inp = root / "candidates.csv"
        out = root / "out"
        _rows().to_csv(inp, index=False)
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "run_ai_capex_bottleneck_screen.py",
                "--input",
                str(inp),
                "--output-dir",
                str(out),
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


if __name__ == "__main__":
    test_prepare_marks_forward_returns_audit_only_inputs()
    test_cli_screen_passes_only_to_default_off_hook_stage()
    print("ai_capex_bottleneck_screen_smoke: PASS")

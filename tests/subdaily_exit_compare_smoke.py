#!/usr/bin/env python3
"""Smoke for tools/run_subdaily_exit_compare.py.

Builds synthetic broker_replay + position_risk_weekly_validation metrics,
runs the tool, and asserts the comparison JSON shape, delta math, and
the favourable/expensive interpretation labels.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "run_subdaily_exit_compare.py"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _build_inputs(latest: Path, baseline_cagr: float, overlay_cagr: float, baseline_mdd: float, overlay_mdd: float) -> None:
    for portfolio in ("main", "concentrated"):
        _write_json(
            latest / "broker_replay" / portfolio / "metrics.json",
            {
                "status": "completed",
                "label": "full",
                "cagr": baseline_cagr,
                "sharpe": 1.25,
                "max_dd": baseline_mdd,
                "avg_cash_weight": 0.10,
                "trade_count": 800,
                "total_fees_usd": 20000,
                "start_date": "2019-06-03",
                "end_date": "2026-06-12",
                "years": 7.0,
                "metric_mode": "broker_ledger_next_close",
            },
        )
        _write_json(
            latest / "position_risk_weekly_validation" / portfolio / "metrics.json",
            {
                "status": "completed",
                "cagr": overlay_cagr,
                "sharpe": 0.95,
                "max_dd": overlay_mdd,
                "avg_cash_weight": 0.05,
                "exit_count": 200,
                "trim_count": 60,
                "hard_stop": -0.08,
                "trailing_stop": -0.15,
                "trailing_activation": 0.15,
                "relative_exit_threshold": -0.12,
                "relative_trim_threshold": -0.06,
                "months": 84,
                "metric_mode": "position_risk_weekly_validation",
                "research_only": True,
                "valid_for_production": False,
            },
        )
        trade_log = pd.DataFrame(
            [
                {"ticker": "AAA", "side": "SELL", "reason": "hard_stop"},
                {"ticker": "BBB", "side": "SELL", "reason": "trailing_stop"},
                {"ticker": "CCC", "side": "SELL", "reason": "relative_exit"},
                {"ticker": "DDD", "side": "BUY",  "reason": "monthly_entry_open"},
            ]
        )
        (latest / "position_risk_weekly_validation" / portfolio).mkdir(parents=True, exist_ok=True)
        trade_log.to_csv(latest / "position_risk_weekly_validation" / portfolio / "trade_log.csv", index=False)


def _run(latest: Path, out_dir: Path) -> int:
    return subprocess.run(
        [sys.executable, str(TOOL), "--latest-run", str(latest), "--output-dir", str(out_dir)],
        check=False,
    ).returncode


def test_favourable_trade_off_interpretation() -> None:
    """MDD improves a lot, CAGR drops a little → 'favourable'."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        latest = tmp / "latest"
        out_dir = tmp / "out"
        _build_inputs(latest, baseline_cagr=0.21, overlay_cagr=0.20, baseline_mdd=-0.36, overlay_mdd=-0.28)
        assert _run(latest, out_dir) == 0
        s = json.loads((out_dir / "comparison.json").read_text(encoding="utf-8"))
        for p in ("main", "concentrated"):
            block = s[p]
            assert block["delta"]["status"] == "ok"
            assert abs(block["delta"]["delta_cagr_pp"] - (-1.0)) < 0.01
            assert abs(block["delta"]["delta_max_dd_pp"] - 8.0) < 0.01
            assert "favourable" in block["delta"]["interpretation"]
            # Exit-reason breakdown only counts SELLs.
            reasons = block["overlay_exit_reason_counts"]
            assert "hard_stop" in reasons and reasons["hard_stop"] == 1
            assert "monthly_entry_open" not in reasons


def test_expensive_trade_off_interpretation() -> None:
    """MDD improves, but CAGR cost is too big → 'expensive'."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        latest = tmp / "latest"
        out_dir = tmp / "out"
        _build_inputs(latest, baseline_cagr=0.21, overlay_cagr=0.13, baseline_mdd=-0.36, overlay_mdd=-0.29)
        assert _run(latest, out_dir) == 0
        s = json.loads((out_dir / "comparison.json").read_text(encoding="utf-8"))
        for p in ("main", "concentrated"):
            block = s[p]
            interp = block["delta"]["interpretation"]
            assert "expensive" in interp or "trade-off" in interp


def test_missing_inputs_marks_incomplete_without_crashing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        latest = tmp / "empty"
        latest.mkdir()
        out_dir = tmp / "out"
        assert _run(latest, out_dir) == 0
        s = json.loads((out_dir / "comparison.json").read_text(encoding="utf-8"))
        for p in ("main", "concentrated"):
            # baseline missing OR overlay missing => delta.status incomplete
            assert s[p]["delta"]["status"] in {"incomplete"}


if __name__ == "__main__":
    print("PASS test_favourable_trade_off_interpretation")
    test_favourable_trade_off_interpretation()
    print("PASS test_expensive_trade_off_interpretation")
    test_expensive_trade_off_interpretation()
    print("PASS test_missing_inputs_marks_incomplete_without_crashing")
    test_missing_inputs_marks_incomplete_without_crashing()
    print("\n3/3 passed")

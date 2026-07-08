#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_earnings_revision_signals import build_signals, main  # noqa: E402


def _raw() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "sector": "Information Technology",
                "fiscal_period": "2026Q2",
                "estimate_date": "2026-01-01",
                "available_from": "2026-01-02",
                "eps_estimate": 1.00,
                "revenue_estimate": 100.0,
                "margin_estimate": 0.20,
                "actual_eps_ttm": 0.80,
                "actual_revenue_ttm": 90.0,
                "actual_margin_ttm": 0.18,
                "guidance_direction": "neutral",
                "source_type": "historical_revision",
            },
            {
                "ticker": "AAA",
                "sector": "Information Technology",
                "fiscal_period": "2026Q2",
                "estimate_date": "2026-04-01",
                "available_from": "2026-04-02",
                "eps_estimate": 1.15,
                "revenue_estimate": 112.0,
                "margin_estimate": 0.22,
                "actual_eps_ttm": 0.82,
                "actual_revenue_ttm": 92.0,
                "actual_margin_ttm": 0.19,
                "guidance_direction": "neutral",
                "source_type": "historical_revision",
            },
            {
                "ticker": "AAA",
                "sector": "Information Technology",
                "fiscal_period": "2026Q2",
                "estimate_date": "2026-04-15",
                "available_from": "2026-04-16",
                "eps_estimate": 1.25,
                "revenue_estimate": 120.0,
                "margin_estimate": 0.23,
                "actual_eps_ttm": 0.82,
                "actual_revenue_ttm": 92.0,
                "actual_margin_ttm": 0.19,
                "guidance_direction": "positive",
                "source_type": "historical_revision",
            },
            {
                "ticker": "LATE",
                "sector": "Information Technology",
                "available_from": "2026-12-31",
                "eps_estimate": 9.99,
                "guidance_direction": "positive",
            },
        ]
    )


def test_revision_signals_require_available_from_and_filter_future() -> None:
    out, summary = build_signals(_raw(), as_of=pd.Timestamp("2026-06-30"))
    assert summary["future_available_from_rows_filtered"] == 1
    latest = out[out["ticker"].eq("AAA")].sort_values("available_from").iloc[-1]
    assert latest["eps_revision_5d"] > 0
    assert latest["revenue_revision_5d"] > 0
    assert latest["eps_revision_13w"] > 0
    assert latest["eps_estimate_vs_actual_ttm"] > 0
    assert latest["revenue_estimate_vs_actual_ttm"] > 0
    assert latest["margin_estimate_vs_actual_ttm"] > 0
    assert "eps_revision_accel_5d_vs_20d" in latest.index
    assert latest["positive_guidance_flag"] == 1
    assert latest["sector_eps_revision_breadth"] >= 0
    assert summary["input_history_depth_ticker_count"] == 1
    assert summary["coverage_eligible_history_depth_ticker_count"] == 1
    assert summary["nonzero_revision_ticker_count"] == 1
    assert summary["coverage_eligible_nonzero_revision_ticker_count"] == 1
    assert summary["directional_guidance_ticker_count"] == 1
    assert summary["coverage_eligible_directional_guidance_ticker_count"] == 1
    assert summary["short_horizon_revision_ticker_count"] == 1
    assert summary["estimate_vs_actual_gap_ticker_count"] == 1
    assert summary["regime_nowcast_coverage_ready"] is False


def test_actual_snapshot_builds_but_does_not_mark_regime_ready() -> None:
    rows = []
    for idx in range(5):
        ticker = f"A{idx}"
        rows.append(
            {
                "ticker": ticker,
                "available_from": "2026-01-02",
                "estimate_date": "2026-01-01",
                "eps_estimate": 1.0,
                "guidance_direction": "positive",
                "source_type": "sec_actual_snapshot",
            }
        )
        rows.append(
            {
                "ticker": ticker,
                "available_from": "2026-04-02",
                "estimate_date": "2026-04-01",
                "eps_estimate": 1.2,
                "guidance_direction": "positive",
                "source_type": "sec_actual_snapshot",
            }
        )
    out, summary = build_signals(pd.DataFrame(rows), as_of=pd.Timestamp("2026-06-30"))
    assert not out.empty
    assert summary["input_history_depth_ticker_count"] == 5, summary
    assert summary["coverage_eligible_history_depth_ticker_count"] == 0, summary
    assert summary["nonzero_revision_ticker_count"] == 5, summary
    assert summary["coverage_eligible_nonzero_revision_ticker_count"] == 0, summary
    assert summary["directional_guidance_ticker_count"] == 5, summary
    assert summary["coverage_eligible_directional_guidance_ticker_count"] == 0, summary
    assert summary["regime_nowcast_coverage_ready"] is False, summary
    assert out["source_type_coverage_eligible"].astype(bool).sum() == 0


def test_cli_writes_parquet() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        raw = root / "earnings_revisions.csv"
        out = root / "signals.parquet"
        summary = root / "summary.json"
        _raw().to_csv(raw, index=False)
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "build_earnings_revision_signals.py",
                "--input",
                str(raw),
                "--output",
                str(out),
                "--summary",
                str(summary),
                "--as-of",
                "2026-06-30",
            ]
            assert main() == 0
        finally:
            sys.argv = old_argv
        assert out.exists()
        assert summary.exists()


def test_cli_blocks_header_only_feed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        raw = root / "earnings_revisions.csv"
        out = root / "signals.parquet"
        summary = root / "summary.json"
        pd.DataFrame(
            columns=[
                "ticker",
                "fiscal_period",
                "estimate_date",
                "available_from",
                "eps_estimate",
                "revenue_estimate",
                "guidance_direction",
                "source",
                "source_type",
            ]
        ).to_csv(raw, index=False)
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "build_earnings_revision_signals.py",
                "--input",
                str(raw),
                "--output",
                str(out),
                "--summary",
                str(summary),
                "--as-of",
                "2026-06-30",
            ]
            assert main() == 2
        finally:
            sys.argv = old_argv
        payload = json.loads(summary.read_text(encoding="utf-8"))
        assert payload["status"] == "blocked", payload
        assert payload["reason"] == "no_output_rows", payload
        assert not out.exists()


if __name__ == "__main__":
    test_revision_signals_require_available_from_and_filter_future()
    test_actual_snapshot_builds_but_does_not_mark_regime_ready()
    test_cli_writes_parquet()
    test_cli_blocks_header_only_feed()
    print("earnings_revision_signals_smoke: PASS")

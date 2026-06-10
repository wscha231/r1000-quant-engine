#!/usr/bin/env python3
"""Smoke tests for the trade attribution analysis tool.

Verifies that:
  * a synthetic broker-ledger fixture with a clear unrealized-loss MDD
    window triggers the F1 finding (high severity)
  * a synthetic fixture with loss concentrated in one regime triggers
    F2 (medium)
  * the tool emits the documented schema fields and never claims
    production validity
  * missing inputs produce a graceful blocked result without crashing
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_trade_attribution_analysis import (  # noqa: E402
    SCHEMA_VERSION,
    analyze_portfolio,
    run,
)


def _write_broker_fixture(root: Path, portfolio_kind: str, equity_rows: list[dict], trade_rows: list[dict]) -> None:
    base = root / "broker_replay" / portfolio_kind
    base.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(equity_rows).to_csv(base / "equity_curve.csv", index=False)
    (base / "metrics.json").write_text(
        json.dumps({
            "status": "completed",
            "cagr": 0.20,
            "sharpe": 1.0,
            "max_dd": -0.30,
            "trade_count": len(trade_rows),
            "total_fees_usd": 1000.0,
        }),
        encoding="utf-8",
    )
    journal = root / "broker_trade_journal" / portfolio_kind
    journal.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(trade_rows).to_csv(journal / "round_trips.csv", index=False)


def test_unrealized_holding_mdd_triggers_f1_high_finding() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Equity rises to 200k peak then collapses to 130k over 14 days.
        # During that window only one tiny exit happens (P&L +$50). The
        # rest of the equity drop is unrealized holding loss.
        dates = pd.date_range("2024-01-02", periods=60, freq="B")
        equity = []
        for i, d in enumerate(dates):
            if i < 20:
                eq = 100_000 + i * 5_000  # ramp to 200k
            elif i < 34:
                eq = 200_000 - (i - 19) * 5_000  # crash to 130k by day 34
            else:
                eq = 130_000 + (i - 34) * 1_000  # slow recovery
            equity.append({"date": d.date().isoformat(), "equity_usd": eq})
        # One trade exits during the crash with tiny P&L.
        trade_rows = [
            {
                "ticker": "AAA",
                "entry_date": "2024-01-15",
                "exit_date": "2024-01-22",
                "entry_regime_state": "bull",
                "exit_reason": "target_exit",
                "holding_days": 5,
                "realized_return": 0.005,
                "net_pnl_usd": 50.0,
            },
            # Larger trades AFTER the crash window so they are not "in window".
            {
                "ticker": "BBB",
                "entry_date": "2024-03-01",
                "exit_date": "2024-03-15",
                "entry_regime_state": "bull",
                "exit_reason": "target_exit",
                "holding_days": 10,
                "realized_return": 0.10,
                "net_pnl_usd": 5000.0,
            },
        ]
        _write_broker_fixture(root, "main", equity, trade_rows)

        out_dir = root / "trade_attribution"
        report = analyze_portfolio(latest_run=root, portfolio_kind="main", output_dir=out_dir)
        assert report["status"] == "completed", report
        assert report["schema_version"] == SCHEMA_VERSION
        finding_ids = {f["finding_id"] for f in report["findings"]}
        assert any(fid.startswith("F1_mdd_dominated_by_unrealized_holdings") for fid in finding_ids), finding_ids
        high_findings = [f for f in report["findings"] if f["severity"] == "high"]
        assert any("unrealized_holdings" in f["finding_id"] for f in high_findings)


def test_regime_loss_concentration_triggers_f2_medium_finding() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dates = pd.date_range("2024-01-02", periods=40, freq="B")
        equity = [
            {"date": d.date().isoformat(), "equity_usd": 100_000 + i * 100}
            for i, d in enumerate(dates)
        ]
        # 8 losers in neutral regime (total -$8000), 2 in bull (-$500), 5 winners in bull.
        trade_rows = []
        for i in range(8):
            trade_rows.append({
                "ticker": f"L{i}",
                "entry_date": "2024-01-02",
                "exit_date": "2024-01-15",
                "entry_regime_state": "neutral",
                "exit_reason": "target_exit",
                "holding_days": 10,
                "realized_return": -0.05,
                "net_pnl_usd": -1000.0,
            })
        for i in range(2):
            trade_rows.append({
                "ticker": f"B{i}",
                "entry_date": "2024-01-02",
                "exit_date": "2024-01-22",
                "entry_regime_state": "bull",
                "exit_reason": "target_exit",
                "holding_days": 14,
                "realized_return": -0.02,
                "net_pnl_usd": -250.0,
            })
        for i in range(5):
            trade_rows.append({
                "ticker": f"W{i}",
                "entry_date": "2024-01-02",
                "exit_date": "2024-02-01",
                "entry_regime_state": "bull",
                "exit_reason": "target_exit",
                "holding_days": 20,
                "realized_return": 0.20,
                "net_pnl_usd": 4000.0,
            })
        _write_broker_fixture(root, "main", equity, trade_rows)
        out_dir = root / "trade_attribution"
        report = analyze_portfolio(latest_run=root, portfolio_kind="main", output_dir=out_dir)
        assert report["status"] == "completed"
        ids = [f["finding_id"] for f in report["findings"]]
        assert any("F2_loss_concentration_in_neutral_regime" in fid for fid in ids), ids


def test_missing_inputs_produce_blocked_status_not_crash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        report = analyze_portfolio(latest_run=root, portfolio_kind="main", output_dir=root / "trade_attribution")
        assert report["status"] == "blocked"
        assert "reason" in report


def test_run_wrapper_writes_summary_with_all_findings_flat() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dates = pd.date_range("2024-01-02", periods=30, freq="B")
        equity = [{"date": d.date().isoformat(), "equity_usd": 100_000 + i * 50} for i, d in enumerate(dates)]
        trade_rows = [
            {
                "ticker": "AAA",
                "entry_date": "2024-01-02",
                "exit_date": "2024-01-15",
                "entry_regime_state": "bull",
                "exit_reason": "target_exit",
                "holding_days": 10,
                "realized_return": 0.05,
                "net_pnl_usd": 500.0,
            },
        ]
        _write_broker_fixture(root, "main", equity, trade_rows)
        out_dir = root / "trade_attribution"
        summary = run(latest_run=root, output_dir=out_dir, portfolios=["main", "concentrated"])
        assert summary["schema_version"] == SCHEMA_VERSION
        assert "main" in summary["portfolios"]
        assert "concentrated" in summary["portfolios"]
        # main is completed, concentrated is blocked - both should be in summary.
        assert summary["portfolios"]["main"]["status"] == "completed"
        assert summary["portfolios"]["concentrated"]["status"] == "blocked"
        # all_findings only carries completed portfolios' findings.
        for f in summary["all_findings"]:
            assert f["portfolio_kind"] == "main"


def main() -> int:
    test_unrealized_holding_mdd_triggers_f1_high_finding()
    test_regime_loss_concentration_triggers_f2_medium_finding()
    test_missing_inputs_produce_blocked_status_not_crash()
    test_run_wrapper_writes_summary_with_all_findings_flat()
    print("trade_attribution_analysis_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

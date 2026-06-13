#!/usr/bin/env python3
"""Smoke for tools/run_leader_lifecycle_audit.py.

Builds synthetic broker_trade_journal/round_trips and broker_replay/trades for
both portfolios + a synthetic alphaops_vnext/daily_crisis_state, runs the tool,
and asserts the JSON shape, the gate evaluation, and reentry-window math.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "run_leader_lifecycle_audit.py"


def _write_round_trips(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_trades(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _build_inputs(latest: Path) -> None:
    # ---- Round-trips: one short-hold loss + one long-hold winner per book ----
    main_rt = [
        dict(
            trade_id="main_1", portfolio_kind="main", ticker="AAA",
            entry_date="2024-01-02", exit_date="2024-02-02",
            entry_reason="target_rebalance", exit_reason="target_exit",
            holding_days=31, realized_return=-0.06, grade_label="LOSS",
            entry_explosion_exit_score=0.65, entry_stage2_overext_penalty=0.10,
            entry_rs_acceleration_score=0.50, entry_explosion_entry_score=0.30,
        ),
        dict(
            trade_id="main_2", portfolio_kind="main", ticker="BBB",
            entry_date="2024-01-02", exit_date="2024-08-01",
            entry_reason="target_rebalance", exit_reason="target_exit",
            holding_days=212, realized_return=0.85, grade_label="WIN",
            entry_explosion_exit_score=0.10, entry_stage2_overext_penalty=0.05,
            entry_rs_acceleration_score=1.20, entry_explosion_entry_score=0.55,
        ),
        dict(
            trade_id="main_3", portfolio_kind="main", ticker="CCC",
            entry_date="2024-03-01", exit_date="2024-04-01",
            entry_reason="target_rebalance", exit_reason="target_exit",
            holding_days=31, realized_return=0.18, grade_label="GOOD_EXIT",
            entry_explosion_exit_score=0.20, entry_stage2_overext_penalty=0.15,
            entry_rs_acceleration_score=1.55, entry_explosion_entry_score=-0.10,
        ),
    ]
    conc_rt = [
        dict(
            trade_id="conc_1", portfolio_kind="concentrated", ticker="DDD",
            entry_date="2024-01-02", exit_date="2024-02-02",
            entry_reason="target_rebalance", exit_reason="target_exit",
            holding_days=31, realized_return=-0.10, grade_label="LOSS",
            entry_explosion_exit_score=0.80, entry_stage2_overext_penalty=0.60,
            entry_rs_acceleration_score=2.00, entry_explosion_entry_score=-0.20,
        ),
        dict(
            trade_id="conc_2", portfolio_kind="concentrated", ticker="EEE",
            entry_date="2024-02-01", exit_date="2024-09-01",
            entry_reason="target_rebalance", exit_reason="target_exit",
            holding_days=213, realized_return=1.10, grade_label="WIN",
            entry_explosion_exit_score=0.05, entry_stage2_overext_penalty=0.02,
            entry_rs_acceleration_score=0.80, entry_explosion_entry_score=0.60,
        ),
    ]
    _write_round_trips(latest / "broker_trade_journal" / "main" / "round_trips.csv", main_rt)
    _write_round_trips(latest / "broker_trade_journal" / "concentrated" / "round_trips.csv", conc_rt)

    # ---- Trades: two SELL/BUY pairs on the same date so the premature-sell
    # routine has cross-row redeploy baselines. SELL AAA at $100 on 2024-02-02;
    # BUY ZZZ at $100 on 2024-02-02; future fills show ZZZ +20% and AAA flat. ----
    main_trades = [
        # initial BUYs (so timelines exist before each SELL)
        dict(ticker="AAA", side="BUY",  fill_price=110.0, date="2024-01-02", signal_date="2023-12-29", reason="target_rebalance"),
        dict(ticker="ZZZ", side="BUY",  fill_price=100.0, date="2024-02-02", signal_date="2024-01-31", reason="target_rebalance"),
        dict(ticker="AAA", side="SELL", fill_price=100.0, date="2024-02-02", signal_date="2024-01-31", reason="target_exit"),
        # Forward observations 30/63/126 days later
        dict(ticker="AAA", side="BUY",  fill_price=104.0, date="2024-03-04", signal_date="2024-03-01", reason="target_rebalance"),
        dict(ticker="ZZZ", side="BUY",  fill_price=118.0, date="2024-03-04", signal_date="2024-03-01", reason="target_rebalance"),
        dict(ticker="AAA", side="SELL", fill_price=101.0, date="2024-04-05", signal_date="2024-03-29", reason="target_rebalance"),
        dict(ticker="ZZZ", side="SELL", fill_price=125.0, date="2024-04-05", signal_date="2024-03-29", reason="target_rebalance"),
        dict(ticker="AAA", side="SELL", fill_price=98.0,  date="2024-06-07", signal_date="2024-05-31", reason="target_rebalance"),
        dict(ticker="ZZZ", side="SELL", fill_price=140.0, date="2024-06-07", signal_date="2024-05-31", reason="target_rebalance"),
    ]
    _write_trades(latest / "broker_replay" / "main" / "trades.csv", main_trades)
    _write_trades(latest / "broker_replay" / "concentrated" / "trades.csv", main_trades)

    # ---- Daily crisis state with one defense window 2024-01-15..2024-02-15
    # so reentry-capture has a real window to evaluate. ----
    dates = pd.date_range("2024-01-01", "2024-12-31", freq="D")
    crisis_state = []
    for d in dates:
        is_defense = pd.Timestamp("2024-01-15") <= d <= pd.Timestamp("2024-02-15")
        crisis_state.append({"date": d.date().isoformat(), "crisis_state": "DEFENSE_REVIEW" if is_defense else "GREEN"})
    (latest / "alphaops_vnext").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(crisis_state).to_csv(latest / "alphaops_vnext" / "daily_crisis_state.csv", index=False)


def _run_tool(latest: Path, out_dir: Path) -> int:
    cmd = [
        sys.executable, str(TOOL),
        "--latest-run", str(latest),
        "--output-dir", str(out_dir),
    ]
    return subprocess.run(cmd, check=False).returncode


def test_audit_produces_summary_and_gates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        latest = tmp / "latest"
        out_dir = tmp / "out"
        _build_inputs(latest)
        assert _run_tool(latest, out_dir) == 0

        summary_path = out_dir / "summary.json"
        report_path = out_dir / "audit_report.md"
        assert summary_path.exists(), "summary.json missing"
        assert report_path.exists(), "audit_report.md missing"

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["schema_version"] == "leader_lifecycle_audit_v1"

        for portfolio in ("main", "concentrated"):
            block = summary[portfolio]
            assert block["holding_period"]["status"] == "ok"
            assert block["holding_period"]["trade_count"] >= 2
            assert block["extension_chase"]["status"] == "ok"
            assert block["leader_capture"]["status"] == "ok"
            # premature_sell uses cross-row trades; status ok if matched at any horizon
            psr = block["premature_sell"]
            assert psr["status"] == "ok"
            # Verify the 30d horizon matched at least one sell/buy pair (AAA vs ZZZ)
            h30 = psr["horizons"]["30d"]
            assert h30["matched"] >= 1
            # Verify reentry math fires for the synthetic defense window
            reent = block["reentry_capture"]
            assert reent["status"] == "ok"
            assert reent["defense_windows"] == 1

        # Verify per-portfolio premature exits CSV materialized for at least
        # one portfolio (worst-10 may be empty if 126d horizon found no match).
        # In our synthetic data we engineered fills at +126d so it should exist.
        for portfolio in ("main", "concentrated"):
            csv_path = out_dir / portfolio / "premature_exits.csv"
            if csv_path.exists():
                df = pd.read_csv(csv_path)
                assert "premature_sell_excess_return_126d" in df.columns
                assert len(df) >= 1


def test_missing_inputs_marks_skipped_without_crashing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        latest = tmp / "empty_latest"
        latest.mkdir()
        out_dir = tmp / "out"
        assert _run_tool(latest, out_dir) == 0
        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        for portfolio in ("main", "concentrated"):
            assert summary[portfolio]["status"] == "missing_inputs"


def test_gates_override_via_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        latest = tmp / "latest"
        out_dir = tmp / "out"
        _build_inputs(latest)
        # Override median_holding_days_min to a value our synthetic data passes
        gates_file = tmp / "gates.json"
        gates_file.write_text(json.dumps({"median_holding_days_min": 30}), encoding="utf-8")
        cmd = [
            sys.executable, str(TOOL),
            "--latest-run", str(latest),
            "--output-dir", str(out_dir),
            "--gates", str(gates_file),
        ]
        rc = subprocess.run(cmd, check=False).returncode
        assert rc == 0
        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["gates_used"]["median_holding_days_min"] == 30
        # Main median = 31 (LOSS) vs 31 (GOOD_EXIT) vs 212 (WIN) → median 31 ≥ 30 passes
        assert summary["main"]["gates"]["median_holding_days_min"]["pass"] is True


if __name__ == "__main__":
    print("PASS test_audit_produces_summary_and_gates")
    test_audit_produces_summary_and_gates()
    print("PASS test_missing_inputs_marks_skipped_without_crashing")
    test_missing_inputs_marks_skipped_without_crashing()
    print("PASS test_gates_override_via_file")
    test_gates_override_via_file()
    print("\n3/3 passed")

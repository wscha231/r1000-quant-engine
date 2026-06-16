#!/usr/bin/env python3
"""Smoke tests for Alpha Plane entry/exit timing audit."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from tools.run_entry_exit_timing_audit import run  # noqa: E402


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _build_inputs(latest: Path) -> None:
    for portfolio in ("main", "concentrated"):
        _write_csv(
            latest / "broker_trade_journal" / portfolio / "round_trips.csv",
            [
                {
                    "portfolio_kind": portfolio,
                    "ticker": "AAA",
                    "entry_date": "2026-01-02",
                    "exit_date": "2026-03-02",
                    "entry_reason": "target_rebalance",
                    "exit_reason": "target_exit",
                    "holding_days": 59,
                    "realized_return": 0.10,
                    "exit_price": 100.0,
                    "leader_state_at_exit": "HOLD",
                    "portfolio_sleeve_label": "market_leader",
                },
                {
                    "portfolio_kind": portfolio,
                    "ticker": "BBB",
                    "entry_date": "2026-01-02",
                    "exit_date": "2026-10-01",
                    "entry_reason": "target_rebalance",
                    "exit_reason": "target_exit",
                    "holding_days": 272,
                    "realized_return": 0.80,
                    "exit_price": 200.0,
                    "leader_state_at_exit": "HOLD",
                    "portfolio_sleeve_label": "market_leader",
                },
            ],
        )
        _write_csv(
            latest / "broker_replay" / portfolio / "trades.csv",
            [
                {"date": "2026-01-02", "ticker": "AAA", "side": "BUY", "fill_price": 90.0},
                {"date": "2026-03-02", "ticker": "AAA", "side": "SELL", "fill_price": 100.0},
                {"date": "2026-03-02", "ticker": "ZZZ", "side": "BUY", "fill_price": 100.0},
                {"date": "2026-05-04", "ticker": "AAA", "side": "BUY", "fill_price": 125.0},
                {"date": "2026-05-04", "ticker": "ZZZ", "side": "SELL", "fill_price": 103.0},
                {"date": "2026-07-06", "ticker": "AAA", "side": "SELL", "fill_price": 150.0},
                {"date": "2026-07-06", "ticker": "ZZZ", "side": "SELL", "fill_price": 105.0},
            ],
        )


def main() -> int:
    with TemporaryDirectory() as td:
        root = Path(td)
        latest = root / "latest"
        _build_inputs(latest)
        out_dir = root / "out"
        summary = run(latest, out_dir)
        assert summary["status"] == "completed", summary
        assert summary["production_mutation_allowed"] is False, summary
        assert summary["metric_mode"] == "broker_ledger_next_close", summary

        entry = pd.read_csv(out_dir / "entry_timing_audit.csv")
        exits = pd.read_csv(out_dir / "exit_timing_audit.csv")
        premature = pd.read_csv(out_dir / "premature_sell_counterfactual.csv")
        hold = pd.read_csv(out_dir / "hold_duration_by_lane.csv")
        repl = pd.read_csv(out_dir / "replacement_reason_summary.csv")
        assert "entry_state" in entry.columns
        assert "exit_state" in exits.columns
        assert not premature.empty
        assert bool(premature["premature_sell_candidate"].astype(bool).any()), premature
        assert "pct_held_180d_plus" in hold.columns
        assert "premature_sell_candidate" in set(repl["replacement_reason"])

        payload = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        assert payload["premature_sell_candidates"] >= 1
    print("entry exit timing audit smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

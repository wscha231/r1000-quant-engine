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


def _write_price_cache(price_cache: Path) -> None:
    price_cache.mkdir(parents=True, exist_ok=True)
    dates = pd.date_range("2026-01-02", "2026-12-31", freq="B")
    aaa = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "Adj Close": [90.0 + i * 0.60 for i in range(len(dates))],
        }
    )
    zzz = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "Adj Close": [100.0 + i * 0.05 for i in range(len(dates))],
        }
    )
    aaa.to_csv(price_cache / "AAA.csv", index=False)
    zzz.to_csv(price_cache / "ZZZ.csv", index=False)


def _build_inputs(latest: Path, price_cache: Path) -> None:
    _write_price_cache(price_cache)
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
        price_cache = root / "cache_prices"
        _build_inputs(latest, price_cache)
        out_dir = root / "out"
        summary = run(
            latest,
            out_dir,
            price_cache=price_cache,
            source_run_id="run-123",
            source_commit_sha="abc123",
            source_branch="codex/alpha-plane-measurement-audits-20260615",
            source_artifact_name="entry-exit-test-artifact",
        )
        assert summary["status"] == "completed", summary
        assert summary["production_mutation_allowed"] is False, summary
        assert summary["metric_mode"] == "broker_ledger_next_close", summary
        assert summary["source_run_id"] == "run-123", summary
        assert summary["source_of_truth_level"] == "GITHUB_ARTIFACT", summary

        entry = pd.read_csv(out_dir / "entry_timing_audit.csv")
        exits = pd.read_csv(out_dir / "exit_timing_audit.csv")
        premature = pd.read_csv(out_dir / "premature_sell_counterfactual.csv")
        hold = pd.read_csv(out_dir / "hold_duration_by_lane.csv")
        repl = pd.read_csv(out_dir / "replacement_reason_summary.csv")
        assert "entry_state" in entry.columns
        assert "exit_state" in exits.columns
        assert not premature.empty
        assert "counterfactual_price_source" in premature.columns
        assert "counterfactual_price_available" in premature.columns
        assert "counterfactual_missing_reason" in premature.columns
        assert bool(premature["counterfactual_price_available"].astype(bool).any()), premature
        assert bool(premature["premature_sell_candidate"].astype(bool).any()), premature
        assert "pct_held_180d_plus" in hold.columns
        assert "premature_sell_candidate" in set(repl["replacement_reason"])

        payload = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        assert payload["premature_sell_candidates"] >= 1

        missing_out = root / "missing_price_out"
        missing_summary = run(latest, missing_out, price_cache=root / "missing_cache")
        assert missing_summary["status"] == "completed", missing_summary
        missing = pd.read_csv(missing_out / "premature_sell_counterfactual.csv")
        assert not bool(missing["counterfactual_price_available"].astype(bool).any()), missing
        assert missing["counterfactual_missing_reason"].astype(str).str.contains("missing_price_cache_dir").any(), missing
    print("entry exit timing audit smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

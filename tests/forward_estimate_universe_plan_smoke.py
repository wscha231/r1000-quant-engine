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

from tools.build_forward_estimate_universe_plan import build_plan  # noqa: E402


def test_universe_plan_dedupes_and_shards_forward_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_a = root / "target_book.csv"
        source_b = root / "candidate_universe.csv"
        out_dir = root / "plan"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-07-02", "ticker": "AAA"},
                {"rebalance_date": "2026-07-02", "ticker": "cash"},
                {"rebalance_date": "2026-07-02", "ticker": "BBB"},
                {"rebalance_date": "2026-07-02", "ticker": "AAA"},
                {"rebalance_date": "2026-07-02", "ticker": "bad/name"},
            ]
        ).to_csv(source_a, index=False)
        pd.DataFrame(
            [
                {"symbol": "CCC"},
                {"symbol": "BRK.B"},
                {"symbol": "ddd"},
                {"symbol": "USD"},
            ]
        ).to_csv(source_b, index=False)

        summary = build_plan(
            sources=[str(source_a), str(source_b)],
            output_dir=str(out_dir),
            shard_size=2,
            max_tickers=0,
            vendor_order="fmp,finnhub",
            repo="wscha231/r1000-quant-engine",
            ref="master",
            workflow="earnings_estimates_daily.yml",
            ticker_columns=["ticker", "symbol"],
            extra_excludes=[],
        )

        assert summary["status"] == "ready_for_forward_archive_dispatch"
        assert summary["forward_only"] is True
        assert summary["backtest_acceptance_allowed"] is False
        assert summary["production_activation_allowed"] is False
        assert summary["live_trading_enabled"] is False
        assert summary["fullrun_dispatched"] is False
        assert summary["missing_vendor_coverage_policy"] == "neutral"
        assert summary["ticker_count"] == 5
        assert summary["shard_count"] == 3
        assert summary["vendor_order"] == "fmp,finnhub"

        universe = pd.read_csv(out_dir / "ticker_universe.csv")
        assert universe["ticker"].tolist() == ["AAA", "BBB", "BRK.B", "CCC", "DDD"]
        assert "CASH" not in set(universe["ticker"])
        assert "USD" not in set(universe["ticker"])

        shard0 = (out_dir / "shards" / "shard_000.txt").read_text(encoding="utf-8").strip()
        assert shard0 == "AAA,BBB"
        commands = (out_dir / "dispatch_commands.ps1").read_text(encoding="utf-8")
        assert "earnings_estimates_daily.yml" in commands
        assert "-f vendor_order='fmp,finnhub'" in commands
        assert "-f ticker_limit=0" in commands
        report = (out_dir / "report.md").read_text(encoding="utf-8")
        assert "backtest_acceptance_allowed: `false`" in report
        assert "Current/free estimate snapshots are forward paper-ledger evidence only." in report

        persisted = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        assert persisted["ticker_universe_csv"].endswith("ticker_universe.csv")


if __name__ == "__main__":
    test_universe_plan_dedupes_and_shards_forward_only()
    print("forward_estimate_universe_plan_smoke: PASS")

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

from tools.build_forward_estimate_incremental_universe import build_incremental_universe  # noqa: E402


def test_incremental_universe_keeps_covered_names_and_new_entrants_without_full_retry() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shard_dir = root / "outputs" / "forward_estimate_universe_plan_20260709" / "shards"
        snapshot_dir = root / "data_pit" / "events" / "earnings_estimates"
        shard_dir.mkdir(parents=True)
        snapshot_dir.mkdir(parents=True)
        pd.DataFrame({"ticker": ["AAA", "BBB", "CCC"]}).to_csv(shard_dir / "shard_000.csv", index=False)
        pd.DataFrame({"ticker": ["DDD", "EEE"]}).to_csv(shard_dir / "shard_001.csv", index=False)
        pd.DataFrame({"ticker": ["AAA", "DDD"]}).to_csv(root / "today_retry.csv", index=False)
        pd.DataFrame(
            [
                {"ticker": "AAA", "available_from": "2026-07-09", "has_forward_estimate": 1},
                {"ticker": "BBB", "available_from": "2026-07-09", "has_forward_estimate": 0},
                {"ticker": "OLD", "available_from": "2026-07-09", "has_forward_estimate": 1},
            ]
        ).to_parquet(snapshot_dir / "estimates_20260709.parquet", index=False)
        output = root / "outputs" / "earnings_estimates_daily" / "incremental_universe.csv"
        summary = root / "outputs" / "earnings_estimates_daily" / "incremental_universe_summary.json"

        payload = build_incremental_universe(
            shard_dir=str(shard_dir),
            snapshot_dir=str(snapshot_dir),
            output=str(output),
            summary=str(summary),
            include_tickers="CORE",
            include_file=str(root / "today_retry.csv"),
            max_new_tickers=2,
            max_covered_tickers=10,
        )

        tickers = pd.read_csv(output)["ticker"].tolist()
        assert tickers == ["CORE", "AAA", "DDD", "OLD", "CCC"]
        assert "BBB" not in tickers, "existing uncovered names should wait for rotating retry, not daily full retry"
        assert payload["known_covered_ticker_count"] == 2
        assert payload["new_universe_ticker_count"] == 2
        assert payload["history_ticker_count"] == 3
        assert payload["backtest_acceptance_allowed"] is False
        assert payload["production_activation_allowed"] is False
        assert payload["historical_backfill_allowed"] is False
        persisted = json.loads(summary.read_text(encoding="utf-8"))
        assert persisted["collection_mode"] == "incremental_covered_new_plus_retry"


if __name__ == "__main__":
    test_incremental_universe_keeps_covered_names_and_new_entrants_without_full_retry()
    print("earnings_estimate_incremental_universe_smoke: PASS")

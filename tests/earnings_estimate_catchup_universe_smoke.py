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

from tools.build_forward_estimate_catchup_universe import build_catchup_universe  # noqa: E402


def test_catchup_universe_combines_all_shards_with_neutral_forward_only_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shard_dir = root / "outputs" / "forward_estimate_universe_plan_20260709" / "shards"
        shard_dir.mkdir(parents=True)
        pd.DataFrame({"ticker": ["AAA", "BBB", "CASH"]}).to_csv(shard_dir / "shard_000.csv", index=False)
        pd.DataFrame({"ticker": ["BBB", "CCC", "DDD"]}).to_csv(shard_dir / "shard_001.csv", index=False)
        output = root / "outputs" / "earnings_estimates_daily" / "catchup_all_shards_universe.csv"
        summary = root / "outputs" / "earnings_estimates_daily" / "catchup_universe_summary.json"

        payload = build_catchup_universe(
            shard_dir=str(shard_dir),
            output=str(output),
            summary=str(summary),
            include_tickers="CORE,AAA,SMH",
        )

        assert payload["status"] == "ready_for_forward_archive_catchup"
        assert payload["collection_mode"] == "manual_all_shards_catchup"
        assert payload["ticker_count"] == 6
        assert payload["source_shard_count"] == 2
        assert payload["backtest_acceptance_allowed"] is False
        assert payload["production_activation_allowed"] is False
        assert payload["live_trading_enabled"] is False
        assert payload["missing_vendor_coverage_policy"] == "neutral"

        tickers = pd.read_csv(output)["ticker"].tolist()
        assert tickers == ["CORE", "AAA", "SMH", "BBB", "CCC", "DDD"]
        persisted = json.loads(summary.read_text(encoding="utf-8"))
        assert persisted["output_csv"].endswith("catchup_all_shards_universe.csv")


if __name__ == "__main__":
    test_catchup_universe_combines_all_shards_with_neutral_forward_only_contract()
    print("earnings_estimate_catchup_universe_smoke: PASS")

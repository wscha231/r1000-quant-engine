#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_execution_policy_replay import replay
from tools.run_weekly_evaluation import px_cache_name


def _write_price(cache: Path, ticker: str, prices: list[float]) -> None:
    dates = pd.bdate_range("2026-01-01", periods=len(prices))
    frame = pd.DataFrame({"Close": prices, "Adj Close": prices, "Open": prices}, index=dates)
    frame.to_parquet(cache / px_cache_name(ticker))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        _write_price(cache, "AAA", [100, 101, 102, 103, 104, 106, 108, 110, 111, 112, 113, 114, 115, 116, 117])
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-01", "ticker": "AAA", "weight": 1.00},
                {"rebalance_date": "2026-01-08", "ticker": "AAA", "weight": 0.99},
            ]
        ).to_csv(target, index=False)
        out = root / "out"
        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            cost_bps=0.0,
            buy_band=0.05,
            sell_band=0.05,
            min_holding_days=63,
            new_entry_scale=1.0,
        )
        assert metrics["status"] == "completed"
        assert metrics["broker_ledger_valid"] is True
        assert metrics["valid_for_production"] is False
        assert metrics["research_only"] is True
        assert metrics["metric_mode"] == "broker_ledger_execution_policy_next_close"
        trades = pd.read_csv(out / "trades.csv")
        assert len(trades) == 1, trades
        assert trades.iloc[0]["side"] == "BUY"
        policy = pd.read_csv(out / "policy_decisions.csv")
        assert "skip_sell_inside_band" in set(policy["reason"]) or "skip_buy_inside_band" in set(policy["reason"])
        loaded = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
        assert loaded["trade_count"] == 1
    print("broker_execution_policy_replay_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

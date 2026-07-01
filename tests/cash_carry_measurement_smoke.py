#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_cash_carry_measurement import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


class Args:
    pass


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    ).to_parquet(cache_dir / px_cache_name(ticker))


def test_cash_carry_measurement_blocks_without_rate_cache_and_passes_with_rates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        cache = root / "cache_prices"
        reports.mkdir(parents=True)
        cache.mkdir()
        _write_px(cache, "SPY", [100.0, 100.0, 100.0, 100.0, 100.0])
        for name in ["operating_main_target_book.csv", "operating_concentrated_target_book.csv"]:
            pd.DataFrame([{"rebalance_date": "2026-01-02", "ticker": "CASH", "weight": 1.0}]).to_csv(
                reports / name, index=False
            )
        args = Args()
        args.latest_run = str(latest)
        args.price_cache = str(cache)
        args.output_dir = str(root / "measurement_blocked")
        args.rate_source = "TESTMISSING"
        args.rate_path = ""
        args.rate_lag_days = 1
        args.haircut_bps = 50.0
        args.day_count = 365
        args.cost_bps = 25.0
        args.max_fill_lag_days = 7
        blocked = run(args)
        assert blocked["status"] == "blocked"
        assert blocked["reason"] == "cash_rate_series_unavailable"

        rate_path = root / "rates.csv"
        pd.DataFrame([{"date": "2026-01-02", "value": 4.0}]).to_csv(rate_path, index=False)
        args.output_dir = str(root / "measurement")
        args.rate_source = "DGS3MO"
        args.rate_path = str(rate_path)
        payload = run(args)
        assert payload["status"] == "completed", payload
        assert payload["cash_carry_measurement_pass"] is True
        assert payload["deltas"]["main"]["metric_mode"] == "broker_ledger_next_close_cash_carry"
        assert payload["deltas"]["main"]["cash_interest_accrued_usd"] > 0
        assert payload["deltas"]["concentrated"]["cash_interest_accrued_usd"] > 0
        assert (Path(args.output_dir) / "arm_metrics.csv").exists()


def main() -> int:
    test_cash_carry_measurement_blocks_without_rate_cache_and_passes_with_rates()
    print("cash_carry_measurement_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

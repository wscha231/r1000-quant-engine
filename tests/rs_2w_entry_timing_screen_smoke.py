#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_rs_2w_entry_timing_screen import evaluate, prepare_rows  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_price(cache: Path, ticker: str, closes: list[float]) -> None:
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    frame = pd.DataFrame({"Close": closes, "Open": closes}, index=idx)
    cache.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(cache / px_cache_name(ticker))


def test_2w_screen_passes_only_as_audit_sidecar() -> None:
    with tempfile.TemporaryDirectory() as tmp_raw:
        tmp = Path(tmp_raw)
        cache = tmp / "cache"
        n = 620
        _write_price(cache, "SPY", [100.0 + i * 0.01 for i in range(n)])
        _write_price(cache, "QQQ", [100.0 + i * 0.01 for i in range(n)])
        _write_price(cache, "AAA", [50.0 + i * 0.20 for i in range(n)])
        _write_price(cache, "BBB", [120.0 - i * 0.05 for i in range(n)])

        dates = list(pd.date_range("2024-02-29", periods=12, freq="ME"))
        rows = []
        for idx, dt in enumerate(dates):
            ticker = "AAA" if idx < 8 else "BBB"
            rows.append(
                {
                    "rebalance_date": dt.date().isoformat(),
                    "ticker": ticker,
                    "portfolio_kind": "concentrated",
                    "weight": 0.058,
                    "concentrated_cashfunded_early_entry_applied": True,
                }
            )
        book = tmp / "target_book.csv"
        pd.DataFrame(rows).to_csv(book, index=False)

        audited = prepare_rows(book, cache, portfolio="concentrated", benchmarks=("SPY", "QQQ"))
        summary, table = evaluate(audited, oos_start="2024-01-01")

    assert not audited.empty
    assert "rs_benchmark_2w" in audited.columns
    assert summary["audit_only"] is True
    assert summary["policy_mutation_allowed"] is False
    assert summary["score_mutation_allowed"] is False
    assert summary["verdict"] == "screen_pass_design_default_off_2w_rs_gate"
    two = table.loc[table["label"].eq("2w_rs_positive")].iloc[0]
    assert int(two["rows"]) >= 8


def test_empty_population_is_blocked_without_mutation() -> None:
    summary, table = evaluate(pd.DataFrame(), oos_start="2024-01-01")
    assert table.empty
    assert summary["status"] == "blocked_no_rows"
    assert summary["verdict"] == "keep_telemetry_only"


if __name__ == "__main__":
    test_2w_screen_passes_only_as_audit_sidecar()
    test_empty_population_is_blocked_without_mutation()
    print("rs_2w_entry_timing_screen_smoke: PASS")

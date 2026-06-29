#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_incumbent_challenger_opportunity_audit import run  # noqa: E402


def px_cache_name(ticker: str) -> str:
    return f"{hashlib.sha1(str(ticker).upper().encode('utf-8')).hexdigest()[:16]}.parquet"


def write_px(cache: Path, ticker: str, start_price: float, step: float) -> None:
    dates = pd.bdate_range("2020-01-01", periods=180)
    values = [start_price + i * step for i in range(len(dates))]
    frame = pd.DataFrame({"Close": values, "Open": values}, index=dates)
    frame.to_parquet(cache / px_cache_name(ticker))


def test_incumbent_challenger_audit_writes_outputs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        alpha = latest / "alphaops_vnext"
        alpha.mkdir(parents=True)
        cache = root / "cache_prices"
        cache.mkdir()
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2020-01-31",
                    "ticker": "AAA",
                    "weight": 0.60,
                    "alphaops_vnext_score": 5.0,
                    "rs_benchmark_3m": 0.10,
                    "rs_benchmark_6m": 0.12,
                    "actual_results_score": 1.0,
                    "leader_tier": "DUAL_LEADER",
                },
                {
                    "rebalance_date": "2020-01-31",
                    "ticker": "BBB",
                    "weight": 0.40,
                    "alphaops_vnext_score": 4.0,
                },
                {
                    "rebalance_date": "2020-02-28",
                    "ticker": "AAA",
                    "weight": 0.30,
                    "alphaops_vnext_score": 4.8,
                    "rs_benchmark_3m": 0.08,
                    "rs_benchmark_6m": 0.10,
                    "actual_results_score": 1.0,
                    "leader_tier": "DUAL_LEADER",
                },
                {
                    "rebalance_date": "2020-02-28",
                    "ticker": "CCC",
                    "weight": 0.70,
                    "alphaops_vnext_score": 5.0,
                    "rs_benchmark_3m": 0.03,
                    "rs_benchmark_6m": 0.04,
                    "actual_results_score": 0.0,
                    "leader_tier": "SECTOR_LEADER",
                },
            ]
        ).to_csv(alpha / "official_concentrated_target_book.csv", index=False)
        cand_dir = latest / "sec_enriched_candidate_replay"
        cand_dir.mkdir()
        pd.DataFrame(
            [
                {"rebalance_date": "2020-02-28", "ticker": "AAA", "rs_benchmark_3m": 0.08, "actual_results_score": 1.0},
                {"rebalance_date": "2020-02-28", "ticker": "CCC", "rs_benchmark_3m": 0.03, "actual_results_score": 0.0},
            ]
        ).to_csv(cand_dir / "candidate_replay_book_sec_enriched.csv", index=False)
        write_px(cache, "AAA", 100.0, 1.0)
        write_px(cache, "CCC", 100.0, 0.2)
        write_px(cache, "SPY", 100.0, 0.1)
        write_px(cache, "QQQ", 100.0, 0.1)
        out = root / "out"
        args = type(
            "Args",
            (),
            {
                "latest_run": str(latest),
                "target_book": "",
                "candidate_book": "",
                "price_cache": str(cache),
                "portfolio": "concentrated",
                "output_dir": str(out),
                "min_reduction": 0.02,
                "short_rs_days": 10,
                "forward_days": 40,
                "oos_start": "2020-02-01",
                "min_events": 1,
                "min_oos_events": 1,
            },
        )()
        payload = run(args)
        assert payload["event_count"] == 2
        assert (out / "events.csv").exists()
        assert (out / "predicate_summary.csv").exists()
        assert (out / "summary.json").exists()
        events = pd.read_csv(out / "events.csv")
        aaa = events[events["incumbent_ticker"].eq("AAA")].iloc[0]
        assert bool(aaa["incumbent_rs2w_stronger"]) is True
        assert bool(aaa["incumbent_outperformed_challenger"]) is True


if __name__ == "__main__":
    test_incumbent_challenger_audit_writes_outputs()
    print("incumbent_challenger_opportunity_audit_smoke: PASS")

#!/usr/bin/env python3
"""Smoke tests for the bounded benchmark/live-event sidecar."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_config import MACRO_FRED_SERIES  # noqa: E402
from r1000_helpers import px_cache_name  # noqa: E402
from tools.build_run287_benchmark_event_sidecar import build, source_sufficient  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_price(path: Path, multiplier: float) -> None:
    dates = pd.bdate_range("2023-01-03", "2026-07-10")
    close = (
        np.linspace(90.0, 170.0, len(dates))
        + 3.0 * np.sin(np.arange(len(dates)) / 15.0)
    ) * multiplier
    pd.DataFrame(
        {
            "Open": close * 0.998,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Adj Close": close,
            "Volume": 1_000_000,
        },
        index=dates,
    ).to_parquet(path)


def write_fred(path: Path, name: str, end: str = "2026-07-09") -> None:
    dates = pd.bdate_range("2023-01-03", end)
    values = np.linspace(20.0, 40.0, len(dates))
    pd.DataFrame({"date": dates, "value": values}).to_parquet(path, index=False)


def fixture(root: Path, *, missing_benchmark: bool = False) -> argparse.Namespace:
    macro_dir = root / "macro"
    isolated = macro_dir / "inputs" / "isolated_engine"
    price_cache = isolated / "cache_prices"
    macro_cache = isolated / "cache_macro"
    price_cache.mkdir(parents=True)
    macro_cache.mkdir(parents=True)
    for index, ticker in enumerate(["QQQ", "USO", "GLD"]):
        write_price(price_cache / px_cache_name(ticker), 1.0 + index / 10.0)
    for name in ["vix", "dgs10", "hy_oas"]:
        series_id = MACRO_FRED_SERIES[name]
        write_fred(macro_cache / f"fred_{name}_{series_id}.parquet", name)
    write_fred(
        macro_cache / f"fred_dxy_{MACRO_FRED_SERIES['dxy']}.parquet",
        "dxy",
        end="2026-07-02",
    )
    macro_current = macro_dir / "macro_current.csv"
    pd.DataFrame({"valuation_close_date": ["2026-07-10"]}).to_csv(
        macro_current, index=False
    )
    write_json(
        macro_dir / "manifest.json",
        {
            "status": "READY_CONSERVATIVE_MACRO_SIDECAR",
            "blockers": [],
            "valuation_close_date": "2026-07-10",
            "macro_available_from": "2026-07-10T23:59:59Z",
            "source_inputs_mutated": False,
            "fullrun_executed": False,
            "selector_executed": False,
            "backtest_executed": False,
            "outputs": {
                "macro_current": {
                    "path": str(macro_current),
                    "sha256": sha(macro_current),
                }
            },
        },
    )
    benchmark = root / "benchmark.parquet"
    if not missing_benchmark:
        write_fred(benchmark, "benchmark")
    return argparse.Namespace(
        macro_manifest=str(macro_dir / "manifest.json"),
        benchmark_source=str(benchmark),
        decision_time_utc="2026-07-11T06:00:00Z",
        http_timeout_seconds=5,
        max_network_requests=0,
        offline=True,
        output_dir=str(root / "output"),
    )


def test_offline_exact_sources_build_benchmark_and_live_event() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = fixture(root)
        source_hash = sha(Path(args.benchmark_source))
        payload = build(args, observed_at_utc="2026-07-11T06:00:00Z")
        assert payload["status"] == "READY_CONSERVATIVE_BENCHMARK_EVENT_SIDECAR"
        assert payload["benchmark_event_merge_allowed"] is True
        assert payload["network_requests_executed"] == 0
        assert payload["coverage"]["benchmark_finite_count"] == 6
        assert payload["coverage"]["live_event_finite_count"] == 5
        assert payload["coverage"]["future_available_row_count"] == 0
        assert payload["fred_vintage_clean"] is False
        assert payload["historical_backtest_acceptance_allowed"] is False
        assert payload["decision_ranking_allowed"] is False
        assert payload["source_inputs_mutated"] is False
        assert sha(Path(args.benchmark_source)) == source_hash


def test_missing_offline_benchmark_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload = build(
            fixture(root, missing_benchmark=True),
            observed_at_utc="2026-07-11T06:00:00Z",
        )
        assert payload["status"] == "BLOCKED_BENCHMARK_COMPONENT_COVERAGE"
        assert payload["blockers"] == ["fred_sp500_missing_or_stale"]
        assert payload["benchmark_event_merge_allowed"] is False


def test_benchmark_requires_latest_session_available_by_decision() -> None:
    stale = pd.DataFrame(
        {"date": pd.to_datetime(["2026-07-09"]), "value": [100.0]}
    )
    current = pd.DataFrame(
        {"date": pd.to_datetime(["2026-07-10"]), "value": [101.0]}
    )
    decision = pd.Timestamp("2026-07-14T05:00:00Z")
    assert source_sufficient(stale, "2026-07-13", decision) is False
    assert source_sufficient(current, "2026-07-13", decision) is True


def main() -> int:
    test_offline_exact_sources_build_benchmark_and_live_event()
    test_missing_offline_benchmark_fails_closed()
    test_benchmark_requires_latest_session_available_by_decision()
    print("run287_benchmark_event_sidecar_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

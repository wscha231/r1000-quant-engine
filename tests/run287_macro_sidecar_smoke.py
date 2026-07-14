#!/usr/bin/env python3
"""Smoke tests for the bounded current-macro sidecar contract."""
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

from r1000_config import MACRO_FRED_SERIES, MACRO_PRICE_TICKERS  # noqa: E402
from r1000_helpers import px_cache_name  # noqa: E402
from tools.build_run287_macro_sidecar import (  # noqa: E402
    REQUIRED_FRED_NAMES,
    build,
    fred_available_from,
    fred_source_sufficient,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_price(path: Path, multiplier: float) -> None:
    dates = pd.bdate_range("2023-01-03", "2026-07-10")
    close = (
        np.linspace(80.0, 150.0, len(dates))
        + 4.0 * np.sin(np.arange(len(dates)) / 19.0)
    ) * multiplier
    pd.DataFrame(
        {
            "Open": close * 0.997,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Adj Close": close,
            "Volume": 1_000_000 + np.arange(len(dates)) * 50,
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        },
        index=dates,
    ).to_parquet(path)


def write_fred(path: Path, name: str, multiplier: float) -> None:
    if name in {"vix", "dgs10", "dxy", "reverse_repo", "hy_oas"}:
        end = "2026-07-02" if name == "dxy" else "2026-07-09"
        dates = pd.bdate_range("2018-01-02", end)
    elif name in {"fed_assets", "tga"}:
        dates = pd.date_range("2018-01-03", "2026-07-08", freq="W-WED")
    else:
        dates = pd.date_range("2014-01-01", "2026-06-01", freq="MS")
    values = (
        np.linspace(100.0, 180.0, len(dates))
        + np.sin(np.arange(len(dates)) / 7.0)
    ) * multiplier
    pd.DataFrame({"date": dates, "value": values}).to_parquet(path, index=False)


def fixture(root: Path, *, missing_market: bool = False) -> argparse.Namespace:
    price_cache = root / "source_prices"
    macro_cache = root / "source_macro"
    price_cache.mkdir()
    macro_cache.mkdir()
    for index, ticker in enumerate(MACRO_PRICE_TICKERS.values()):
        if missing_market and ticker == "UNG":
            continue
        write_price(price_cache / px_cache_name(ticker), 1.0 + index / 20.0)
    for index, name in enumerate(REQUIRED_FRED_NAMES):
        series_id = MACRO_FRED_SERIES[name]
        write_fred(
            macro_cache / f"fred_{name}_{series_id}.parquet",
            name,
            1.0 + index / 30.0,
        )

    snapshot = root / "snapshot.json"
    snapshot.write_text(json.dumps({"valuation_close_date": "2026-07-10"}), encoding="utf-8")
    ticker_audit = root / "ticker_audit.csv"
    pd.DataFrame({"ticker": ["AAA", "BBB"]}).to_csv(ticker_audit, index=False)
    pilot = root / "pilot.json"
    pilot.write_text(
        json.dumps(
            {
                "status": "TECHNICAL_PARITY_READY_MACRO_FUNDAMENTAL_BLOCKED",
                "outputs": {
                    "ticker_audit": {"path": str(ticker_audit), "sha256": sha(ticker_audit)}
                },
            }
        ),
        encoding="utf-8",
    )
    return argparse.Namespace(
        snapshot_manifest=str(snapshot),
        technical_pilot_manifest=str(pilot),
        valuation_close_date="",
        decision_time_utc="2026-07-11T06:00:00Z",
        source_price_cache=str(price_cache),
        source_macro_dirs=[str(macro_cache)],
        price_start="2023-01-01",
        min_market_rows=400,
        min_macro_finite_ratio=0.90,
        http_timeout_seconds=5,
        max_network_requests=0,
        offline=True,
        output_dir=str(root / "output"),
    )


def test_offline_exact_sources_build_current_only_macro_sidecar() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = fixture(root)
        before = {
            path.name: sha(path)
            for path in Path(args.source_price_cache).glob("*.parquet")
        }
        payload = build(args, observed_at_utc="2026-07-11T06:00:00Z")
        assert payload["status"] == "READY_CONSERVATIVE_MACRO_SIDECAR"
        assert payload["macro_merge_allowed"] is True
        assert payload["decision_ranking_allowed"] is False
        assert payload["fred_vintage_clean"] is False
        assert payload["historical_backtest_acceptance_allowed"] is False
        assert payload["network_requests_executed"] == 0
        assert payload["source_inputs_mutated"] is False
        assert payload["coverage"]["market_component_ready_count"] == 9
        assert payload["coverage"]["fred_component_ready_count"] == 13
        assert payload["coverage"]["critical_missing_columns"] == []
        assert payload["coverage"]["future_fred_available_from_rows"] == 0
        assert payload["technical_pilot"]["ticker_count"] == 2
        macro = pd.read_csv(root / "output" / "macro_current.csv")
        assert str(macro.iloc[0]["valuation_close_date"]) == "2026-07-10"
        assert str(macro.iloc[0]["feature_price_cutoff_date"]) == "2026-07-10"
        tickers = pd.read_csv(root / "output" / "ticker_macro_features.csv")
        assert len(tickers) == 2
        assert tickers["macro_refresh_ready"].all()
        assert not tickers["decision_ranking_allowed"].any()
        after = {
            path.name: sha(path)
            for path in Path(args.source_price_cache).glob("*.parquet")
        }
        assert before == after


def test_h10_batch_availability_and_freshness_contract() -> None:
    observation = pd.Series(pd.to_datetime(["2026-07-02"]))
    available = fred_available_from("dxy", observation)
    assert available.iloc[0] == pd.Timestamp("2026-07-06T20:15:00Z")
    usable = pd.DataFrame({"date": observation, "value": [120.0]})
    assert fred_source_sufficient("dxy", usable, "2026-07-10") is True
    assert fred_source_sufficient("dxy", usable, "2026-07-13") is False
    daily_available = fred_available_from(
        "vix", pd.Series(pd.to_datetime(["2026-07-09"]))
    )
    assert daily_available.iloc[0] == pd.Timestamp("2026-07-10T23:59:59Z")


def test_scored_latest_ticker_contract_requires_pass_and_exact_close() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        audit = root / "ticker_refresh_audit.csv"
        pd.DataFrame(
            {
                "ticker": ["AAA", "BBB", "CCC"],
                "status": ["PASS", "FAIL", "PASS"],
                "exact_session_close": [True, True, False],
            }
        ).to_csv(audit, index=False)
        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "status": "READY_RESEARCH_SCORED_LATEST",
                    "outputs": {
                        "ticker_refresh_audit.csv": {
                            "path": str(audit),
                            "sha256": sha(audit),
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        from tools.build_run287_macro_sidecar import technical_pilot_tickers

        tickers, _ = technical_pilot_tickers(manifest)
        assert tickers == ["AAA"]


def test_missing_offline_market_component_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload = build(
            fixture(root, missing_market=True),
            observed_at_utc="2026-07-11T06:00:00Z",
        )
        assert payload["status"] == "BLOCKED_MACRO_COMPONENT_COVERAGE"
        assert "market_component_not_ready:UNG" in payload["blockers"]
        assert payload["macro_merge_allowed"] is False
        assert payload["historical_backtest_acceptance_allowed"] is False


def main() -> int:
    test_h10_batch_availability_and_freshness_contract()
    test_scored_latest_ticker_contract_requires_pass_and_exact_close()
    test_offline_exact_sources_build_current_only_macro_sidecar()
    test_missing_offline_market_component_fails_closed()
    print("run287_macro_sidecar_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

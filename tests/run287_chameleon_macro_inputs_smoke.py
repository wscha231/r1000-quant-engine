#!/usr/bin/env python3
"""Smoke tests for the Chameleon provenance-complete input normalizer."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import build_run287_chameleon_macro_inputs as inputs  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_dates(as_of: str, periods: int = 320) -> pd.DatetimeIndex:
    end = pd.Timestamp(as_of)
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=(end - pd.DateOffset(years=3)).date().isoformat(),
        end_date=end.date().isoformat(),
    )
    return pd.DatetimeIndex(schedule.index[-periods:]).tz_localize(None).normalize()


def write_source_bundle(root: Path, as_of: str) -> tuple[Path, list[Path]]:
    bundle = root / "source_bundle"
    (bundle / "cboe").mkdir(parents=True)
    (bundle / "fred").mkdir(parents=True)
    (bundle / "prices").mkdir(parents=True)
    dates = fixture_dates(as_of)
    source_files: list[Path] = []

    for offset, symbol in enumerate(("VIX", "VIX3M", "VVIX")):
        path = bundle / "cboe" / f"{symbol}.csv"
        payload = {
            "DATE": [date.strftime("%m/%d/%Y") for date in dates],
            "CLOSE": np.linspace(18.0 + offset, 24.0 + offset, len(dates)),
        }
        if symbol == "VVIX":
            payload["VVIX"] = payload.pop("CLOSE")
        else:
            payload.update(
                {
                    "OPEN": 20.0 + offset,
                    "HIGH": 21.0 + offset,
                    "LOW": 19.0 + offset,
                }
            )
        pd.DataFrame(payload).to_csv(path, index=False)
        source_files.append(path)

    contract = json.loads(inputs.DEFAULT_CONTRACT.read_text(encoding="utf-8"))
    for offset, spec in enumerate(contract["fred"].values()):
        path = bundle / "fred" / f"{spec['series_id']}.csv"
        pd.DataFrame(
            {
                "observation_date": [date.date().isoformat() for date in dates],
                spec["series_id"]: np.linspace(1.0 + offset, 2.0 + offset, len(dates)),
            }
        ).to_csv(path, index=False)
        source_files.append(path)

    for offset, ticker in enumerate(contract["prices"]):
        path = bundle / "prices" / f"{ticker}.parquet"
        close = 100.0 + offset + np.linspace(0.0, 30.0, len(dates))
        pd.DataFrame(
            {
                "Date": dates,
                "Close": close,
                "Volume": np.full(len(dates), 1_000_000 + offset * 10_000),
            }
        ).to_parquet(path, index=False)
        source_files.append(path)
    return bundle, source_files


def build_args(root: Path, bundle: Path, output_name: str, as_of: str) -> argparse.Namespace:
    return argparse.Namespace(
        as_of=as_of,
        output_dir=str(root / output_name),
        contract=str(inputs.DEFAULT_CONTRACT),
        source_bundle=str(bundle),
        price_cache="",
        universe_file="",
        allow_network=False,
        http_timeout_seconds=1,
        run_engine=True,
    )


def test_normalizer_is_free_proxy_report_only_and_fail_closed() -> None:
    as_of = "2025-12-31"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bundle, source_files = write_source_bundle(root, as_of)
        before = {str(path): sha(path) for path in source_files}
        result = inputs.build(build_args(root, bundle, "ready", as_of))

        assert result["status"] == inputs.READY_STATUS, result
        assert result["truth_class"] == "FREE_PROXY"
        assert result["historical_ab_allowed"] is False
        assert result["report_only"] is True
        assert result["selector_executed"] is False
        assert result["target_books_mutated"] is False
        assert result["trade_intents_written"] is False
        assert result["orders_generated"] is False
        assert result["ledger_mutated"] is False
        assert result["backtest_executed"] is False
        assert result["fullrun_executed"] is False
        assert result["production_activation_allowed"] is False
        assert result["live_trading_enabled"] is False
        assert result["automatic_promotion_allowed"] is False
        assert result["builder_sha256"] == sha(Path(inputs.__file__).resolve())
        assert result["engine_status"] == (
            "READY_CHAMELEON_MACRO_RISK_REPORT_ONLY_DATA_INSUFFICIENT"
        ), result
        assert before == {str(path): sha(path) for path in source_files}

        output = root / "ready"
        metrics = pd.read_csv(output / "input_metrics.csv")
        context = pd.read_csv(output / "input_context.csv")
        audit = pd.read_csv(output / "source_audit.csv")
        engine_manifest = json.loads(
            (output / "shadow_engine" / "manifest.json").read_text(encoding="utf-8")
        )
        assert set(metrics["truth_class"]) == {"FREE_PROXY"}
        assert metrics["source_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
        assert context["source_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
        assert not {
            "equity_put_call",
            "index_put_call",
            "put_call_change",
        }.intersection(metrics["component"])
        decision = pd.to_datetime(metrics["decision_time_utc"], utc=True)
        available = pd.to_datetime(metrics["available_from"], utc=True)
        assert available.le(decision).all()
        assert engine_manifest["backtest_executed"] is False
        assert engine_manifest["target_books_mutated"] is False
        assert engine_manifest["truth_class"] == "FREE_PROXY"
        assert audit["provider"].str.contains("FRED|Cboe|daily-bar", regex=True).any()
        assert not (output / "orders.csv").exists()
        assert not (output / "trade_intents.csv").exists()

        empty_bundle = root / "empty_bundle"
        empty_bundle.mkdir()
        blocked = inputs.build(build_args(root, empty_bundle, "blocked", as_of))
        assert blocked["status"] == inputs.BLOCKED_STATUS
        assert blocked["blockers"] == [
            "InputContractError:no_normalized_metric_rows"
        ]
        assert (root / "blocked" / "manifest.json").is_file()

        alternate_contract = root / "alternate_contract.json"
        alternate_contract.write_text(
            inputs.DEFAULT_CONTRACT.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        noncanonical_args = build_args(root, bundle, "noncanonical", as_of)
        noncanonical_args.contract = str(alternate_contract)
        noncanonical = inputs.build(noncanonical_args)
        assert noncanonical["status"] == inputs.BLOCKED_STATUS
        assert noncanonical["blockers"][0].startswith(
            "InputContractError:noncanonical_contract_path:"
        )


def test_source_identity_date_and_cross_section_guards() -> None:
    fred = b"observation_date,WRONG\n2025-01-02,1.5\n"
    try:
        inputs.normalize_fred(fred, "EXPECTED")
    except inputs.InputContractError as exc:
        assert str(exc) == "fred_expected_series_column_missing:EXPECTED"
    else:
        raise AssertionError("mislabeled FRED series was accepted")

    prices = inputs.normalize_price_frame(
        pd.DataFrame(
            {
                "Date": ["2025-01-02", "2025-01-03"],
                "Close": [100.0, 101.0],
                "Adj Close": [90.0, 91.0],
                "Volume": [1_000, 1_100],
            }
        )
    )
    assert prices["close"].tolist() == [90.0, 91.0]

    for bad_dates, expected in (
        (["2025-01-02T00:00:00-05:00"], "timezone_aware_daily_price_date"),
        (["2025-01-02 16:00:00"], "non_midnight_daily_price_timestamp"),
        (["2025-01-02", "2025-01-02"], "duplicate_daily_price_date"),
    ):
        try:
            inputs.normalize_price_frame(
                pd.DataFrame({"Date": bad_dates, "Close": [100.0] * len(bad_dates)})
            )
        except inputs.InputContractError as exc:
            assert str(exc) == expected
        else:
            raise AssertionError(f"invalid daily dates accepted: {bad_dates}")

    dates = pd.date_range("2024-01-01", periods=200, freq="B")
    columns = [f"S{number:03d}" for number in range(500)]
    close = pd.DataFrame(100.0, index=dates, columns=columns)
    close.iloc[0, -1] = np.nan
    volume = pd.DataFrame(1_000_000.0, index=dates, columns=columns)
    components, counts = inputs.compute_universe_components(close, volume, 500)
    assert int(close.iloc[-1].notna().sum()) == 500
    assert int(counts["pct_above_ma200"].iloc[-1]) == 499
    assert pd.isna(components["pct_above_ma200"].iloc[-1])


def test_empty_context_header_engine_propagation_and_input_limits() -> None:
    as_of = "2025-12-31"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bundle, _ = write_source_bundle(root, as_of)

        timestamp_args = build_args(
            root, bundle, "timestamp_as_of", "2025-12-31T12:00:00-05:00"
        )
        timestamp_result = inputs.build(timestamp_args)
        assert timestamp_result["status"] == inputs.BLOCKED_STATUS
        assert timestamp_result["blockers"] == [
            "InputContractError:invalid_as_of_date:2025-12-31T12:00:00-05:00"
        ]

        maximum = json.loads(
            inputs.DEFAULT_CONTRACT.read_text(encoding="utf-8")
        )["history"]["maximum_universe_symbols"]
        universe_path = root / "oversized_universe.csv"
        pd.DataFrame(
            {"ticker": [f"S{number:04d}" for number in range(maximum + 1)]}
        ).to_csv(universe_path, index=False)
        oversized_args = build_args(root, bundle, "oversized", as_of)
        oversized_args.universe_file = str(universe_path)
        oversized_args.run_engine = False
        oversized = inputs.build(oversized_args)
        assert oversized["status"] == inputs.BLOCKED_STATUS
        assert "universe_symbol_count_exceeds_maximum" in oversized["blockers"][0]

        minimal = root / "minimal"
        (minimal / "cboe").mkdir(parents=True)
        dates = fixture_dates(as_of)
        pd.DataFrame(
            {
                "DATE": [date.strftime("%m/%d/%Y") for date in dates],
                "CLOSE": np.linspace(18.0, 24.0, len(dates)),
            }
        ).to_csv(minimal / "cboe" / "VIX.csv", index=False)
        header_only = inputs.build(build_args(root, minimal, "header_only", as_of))
        assert header_only["status"] == inputs.READY_STATUS, header_only
        context = pd.read_csv(root / "header_only" / "input_context.csv")
        assert context.empty
        assert set(inputs.risk_engine.CONTEXT_REQUIRED_COLUMNS).issubset(context.columns)

        original_build = inputs.risk_engine.build
        try:
            inputs.risk_engine.build = lambda _: {
                "status": inputs.risk_engine.BLOCKED_STATUS
            }
            propagated = inputs.build(
                build_args(root, minimal, "engine_blocked", as_of)
            )
        finally:
            inputs.risk_engine.build = original_build
        assert propagated["status"] == inputs.BLOCKED_STATUS
        assert propagated["blockers"] == [
            "InputContractError:shadow_engine_not_ready:"
            + inputs.risk_engine.BLOCKED_STATUS
        ]


def main() -> int:
    test_normalizer_is_free_proxy_report_only_and_fail_closed()
    test_source_identity_date_and_cross_section_guards()
    test_empty_context_header_engine_propagation_and_input_limits()
    print("run287_chameleon_macro_inputs_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

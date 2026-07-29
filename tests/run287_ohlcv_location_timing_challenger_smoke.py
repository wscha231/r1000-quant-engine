#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_run287_holding_risk_watch import sha256_file, write_json  # noqa: E402
from tools import build_run287_ohlcv_location_timing_challenger as challenger  # noqa: E402
from tools.build_run287_ohlcv_location_timing_challenger import (  # noqa: E402
    READY_STATUS,
    adjusted_ohlcv,
    build,
    classify_shadow_action,
    fixed_window_features,
    merge_frozen_and_provider,
    vix_context,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


ASOF = pd.Timestamp("2026-07-29")
ACCEPTED_AT_UTC = "2026-07-29T21:05:00Z"


def record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "exists": True,
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def price_frame(
    close: np.ndarray,
    *,
    end: pd.Timestamp = ASOF,
    last_volume: float = 3_000_000,
) -> pd.DataFrame:
    dates = pd.bdate_range(end=end, periods=len(close))
    volume = np.full(len(close), 1_000_000.0)
    volume[-1] = last_volume
    open_ = close * 0.997
    high = np.maximum(open_, close) * 1.006
    low = np.minimum(open_, close) * 0.994
    return pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Adj Close": close,
            "Volume": volume,
        },
        index=dates,
    )


def write_manifest(
    path: Path,
    *,
    status: str,
    outputs: dict[str, Path],
    extra: dict[str, object] | None = None,
) -> None:
    write_json(
        path,
        {
            "status": status,
            "outputs": {key: record(value) for key, value in outputs.items()},
            **(extra or {}),
        },
    )


def build_fixture(root: Path) -> argparse.Namespace:
    artifacts = root / "artifacts"
    portable = root / "portable"
    macro_cache = portable / "macro_benchmark_price_cache"
    artifacts.mkdir(parents=True)
    portable.mkdir(parents=True)
    macro_cache.mkdir(parents=True)

    sessions = 340
    phase = np.arange(sessions)
    aaa = 125.0 * np.cumprod(1.0 + 0.0006 + 0.003 * np.sin(phase / 8))
    aaa[-35:] = np.linspace(aaa[-36] * 0.99, aaa[-36] * 0.70, 35)
    aaa[-1] = aaa[-2] * 0.96
    bbb = 60.0 * np.cumprod(1.0 + 0.0008 + 0.002 * np.sin(phase / 9))
    bbb[-1] = bbb[-2] * 1.025
    spy = 400.0 * np.cumprod(1.0 + 0.0005 + 0.002 * np.sin(phase / 10))
    qqq = 350.0 * np.cumprod(1.0 + 0.0006 + 0.002 * np.sin(phase / 11))
    spy[-35:] = np.linspace(spy[-36] * 0.995, spy[-36] * 0.88, 35)
    qqq[-35:] = np.linspace(qqq[-36] * 0.995, qqq[-36] * 0.86, 35)

    price_map_rows: list[dict[str, str]] = []
    provider_rows: list[pd.DataFrame] = []
    for ticker, close in (("AAA", aaa), ("BBB", bbb)):
        full = price_frame(close)
        base = full.iloc[:-1].copy()
        source = artifacts / f"{ticker.lower()}.parquet"
        base.to_parquet(source)
        price_map_rows.append(
            {
                "ticker": ticker,
                "path": str(source),
                "sha256": sha256_file(source),
            }
        )
        provider = full.iloc[-130:].reset_index(names="Date")
        future = provider.tail(1).copy()
        future["Date"] = ASOF + pd.offsets.BDay(1)
        provider_rows.append(
            pd.concat(
                [
                    provider.assign(ticker=ticker),
                    future.assign(ticker=ticker),
                ],
                ignore_index=True,
            )
        )

    price_map_csv = portable / "selector_price_map.csv"
    pd.DataFrame(price_map_rows).to_csv(price_map_csv, index=False)
    price_map_manifest = portable / "price_map_manifest.json"
    write_manifest(
        price_map_manifest,
        status="READY_CURRENT_SELECTOR_PRICE_MAP_NONSELECTING",
        outputs={"selector_price_map": price_map_csv},
    )
    provider_path = portable / "provider_price_overlap.parquet"
    pd.concat(provider_rows, ignore_index=True).to_parquet(provider_path)
    price_manifest = portable / "price_manifest.json"
    write_manifest(
        price_manifest,
        status="READY_RESEARCH_SCORED_LATEST",
        outputs={"provider_price_overlap.parquet": provider_path},
    )

    comparison = artifacts / "marked_official_advisory_comparison.csv"
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "portfolio_kind": "main",
                "scenario": "main_strict",
                "marked_weight": 0.10,
                "advisory_weight": 0.08,
            },
            {
                "ticker": "BBB",
                "portfolio_kind": "concentrated",
                "scenario": "concentrated",
                "marked_weight": 0.0,
                "advisory_weight": 0.20,
            },
        ]
    ).to_csv(comparison, index=False)
    selector_manifest = artifacts / "selector_manifest.json"
    write_manifest(
        selector_manifest,
        status="READY_CURRENT_SELECTOR_NO_WRITE_REVIEW_REQUIRED",
        outputs={"marked_official_advisory_comparison": comparison},
        extra={"selector_decision_time_utc": "2026-07-29T21:00:00Z"},
    )

    for ticker, close in (("SPY", spy), ("QQQ", qqq)):
        price_frame(close).to_parquet(macro_cache / px_cache_name(ticker))
    vix_source = artifacts / "fred_vix_VIXCLS.parquet"
    pd.DataFrame(
        {
            "date": pd.bdate_range(end=ASOF, periods=340),
            "value": np.r_[np.linspace(15.0, 19.0, 339), 35.0],
        }
    ).to_parquet(vix_source, index=False)
    fred_audit = artifacts / "fred_component_audit.csv"
    pd.DataFrame(
        [
            {
                "name": "vix",
                "status": "ready",
                "isolated_path": str(vix_source),
                "isolated_sha256": sha256_file(vix_source),
                "latest_usable_observation_date": ASOF.date().isoformat(),
                "latest_usable_available_from": "2026-07-29T20:45:00Z",
            }
        ]
    ).to_csv(fred_audit, index=False)
    macro_manifest = portable / "macro_manifest.json"
    write_manifest(
        macro_manifest,
        status="READY_CONSERVATIVE_MACRO_SIDECAR",
        outputs={"fred_component_audit": fred_audit},
    )

    benchmark_audit = {
        "isolated_cache": str(macro_cache),
        "tickers": {},
        "passed": True,
    }
    for ticker in ("SPY", "QQQ"):
        path = macro_cache / px_cache_name(ticker)
        benchmark_audit["tickers"][ticker] = {
            "isolated": {
                **record(path),
                "expected_sha256": sha256_file(path),
                "hash_matches": True,
            }
        }
    benchmark_audit_path = portable / "macro_benchmark_cache_audit.json"
    write_json(benchmark_audit_path, benchmark_audit)

    holding = artifacts / "holding_risk_watch.csv"
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "portfolio_kind": "main",
                "risk_state": "ALERT",
                "available_from": "2026-07-29T20:30:00Z",
            }
        ]
    ).to_csv(holding, index=False)

    producer = artifacts / "producer_status.json"
    write_json(
        producer,
        {
            "status": "READY_EXACT_SELECTOR_RISK_PACKET_REVIEW_ONLY",
            "valuation_price_cutoff_date": ASOF.date().isoformat(),
            "selector_manifest": record(selector_manifest),
            "outputs": {
                "macro_benchmark_cache_audit": record(benchmark_audit_path)
            },
            "source_inputs": {
                "holding_watch_csv": record(holding),
                "portable:price_map_manifest": record(price_map_manifest),
                "portable:price_manifest": record(price_manifest),
                "portable:macro_manifest": record(macro_manifest),
            },
        },
    )
    return argparse.Namespace(
        producer_status=str(producer),
        holding_watch=str(holding),
        contract=str(
            ROOT
            / "docs"
            / "run287_ohlcv_location_timing_challenger_contract.json"
        ),
        valuation_date=ASOF.date().isoformat(),
        observation_accepted_at_utc=ACCEPTED_AT_UTC,
        output_dir=str(root / "output"),
    )


def main() -> None:
    contract = json.loads(
        (
            ROOT
            / "docs"
            / "run287_ohlcv_location_timing_challenger_contract.json"
        ).read_text(encoding="utf-8")
    )
    # Future rows are excluded and historical adjusted closes are rebased
    # without accepting a raw-close identity break.
    base_close = np.linspace(80.0, 120.0, 340)
    full = price_frame(base_close)
    base = full.iloc[:-1].copy()
    provider = full.iloc[-130:].copy()
    provider["Adj Close"] *= 0.98
    future = provider.tail(1).copy()
    future.index = [ASOF + pd.offsets.BDay(1)]
    merged, audit = merge_frozen_and_provider(
        base,
        pd.concat([provider, future]),
        ASOF,
        minimum_overlap=20,
        maximum_relative_error=1e-5,
    )
    assert audit.get("failure") is None, audit
    assert audit["provider_future_rows_excluded"] == 1
    assert abs(audit["historical_adjustment_rebase_factor"] - 0.98) < 1e-12
    assert merged.index.max() == ASOF
    adjusted = adjusted_ohlcv(full, ASOF)
    assert (adjusted["high"] >= adjusted[["open", "close"]].max(axis=1)).all()
    assert (adjusted["low"] <= adjusted[["open", "close"]].min(axis=1)).all()
    malformed = full.tail(3).copy()
    malformed.iloc[0, malformed.columns.get_loc("Low")] = 0.0
    malformed.iloc[1, malformed.columns.get_loc("Low")] = -1.0
    malformed.iloc[2, malformed.columns.get_loc("Volume")] = np.nan
    assert adjusted_ohlcv(malformed, ASOF).empty

    feature, levels = fixed_window_features("TEST", adjusted, ASOF, contract)
    assert feature["price_exact_asof"] is True
    assert len(levels) == 4 * 7
    assert set(row["fibonacci_ratio"] for row in levels) == {
        0.0,
        0.236,
        0.382,
        0.5,
        0.618,
        0.786,
        1.0,
    }
    assert all(row["selected_after_outcome"] is False for row in levels)

    # A single daily outside bar cannot reveal whether the high or low came
    # first, so directional Fibonacci confirmation remains unavailable.
    ambiguous = adjusted.tail(252).copy()
    ambiguous.iloc[-1, ambiguous.columns.get_loc("high")] = (
        ambiguous["high"].iloc[:-1].max() * 1.10
    )
    ambiguous.iloc[-1, ambiguous.columns.get_loc("low")] = (
        ambiguous["low"].iloc[:-1].min() * 0.90
    )
    ambiguous_feature, ambiguous_levels = fixed_window_features(
        "AMBIGUOUS", ambiguous, ASOF, contract
    )
    assert ambiguous_feature["near_fibonacci_consensus_count"] == 0
    assert {
        row["swing_direction"] for row in ambiguous_levels
    } == {"AMBIGUOUS"}
    assert all(row["fibonacci_price"] is None for row in ambiguous_levels)

    invalid_vix = pd.DataFrame(
        {
            "date": pd.bdate_range(end=ASOF, periods=63),
            "value": [20.0] * 62 + [float("inf")],
        }
    )
    invalid_vix_context = vix_context(invalid_vix, ASOF)
    assert invalid_vix_context["vix_data_ready"] is False
    assert (
        invalid_vix_context["vix_data_reason"]
        == "latest_vix_observation_nonfinite_or_nonpositive"
    )

    # VIX stress alone cannot create a held exit or candidate entry.
    held = {
        "is_held": True,
        "data_reason": "",
        "holding_risk_states": "NORMAL",
        "above_ma20": True,
        "above_ma50": True,
        "return_21d": 0.05,
        "near_high_consensus_count": 4,
        "near_low_consensus_count": 0,
        "near_fibonacci_consensus_count": 0,
        "distribution_day": False,
        "accumulation_day": False,
    }
    action, _ = classify_shadow_action(
        held,
        {"vix_stress": True, "market_risk_off_confirmed": False},
    )
    assert action == "HOLD_REVIEW"
    candidate = {
        **held,
        "is_held": False,
        "is_proposed_entry": True,
        "near_high_consensus_count": 0,
        "near_low_consensus_count": 4,
    }
    action, _ = classify_shadow_action(
        candidate,
        {"vix_stress": False, "market_risk_off_confirmed": False},
    )
    assert action == "DATA_INSUFFICIENT_REVIEW"
    action, _ = classify_shadow_action(
        candidate,
        {
            "vix_stress": False,
            "market_risk_off_confirmed": False,
            "benchmark_context_complete": True,
        },
    )
    assert action == "MONITOR_ENTRY_REVIEW"

    with tempfile.TemporaryDirectory() as tmp:
        args = build_fixture(Path(tmp))
        summary = build(args)
        assert summary["status"] == READY_STATUS, summary
        assert summary["security_count"] == 2
        assert summary["available_from"] == "2026-07-29T21:00:00+00:00"
        assert (
            summary["forward_observation_window"][
                "observation_accepted_at_utc"
            ]
            == "2026-07-29T21:05:00+00:00"
        )
        assert summary["market_context"]["market_risk_off_confirmed"] is True
        assert summary["market_context"]["vix_only_signal_allowed"] is False
        assert summary["orders_generated"] is False
        assert summary["target_books_mutated"] is False
        assert summary["selector_weights_changed"] is False
        assert summary["cash_policy_changed"] is False
        assert summary["champion_changed"] is False
        assert summary["backtest_executed"] is False
        assert summary["fullrun_executed"] is False
        rows = pd.read_csv(
            Path(args.output_dir) / "ohlcv_location_timing.csv",
            low_memory=False,
        ).set_index("ticker")
        assert rows.loc["AAA", "shadow_action"] == "EXIT_REVIEW", rows.loc[
            "AAA"
        ].to_dict()
        assert rows.loc["BBB", "shadow_action"] != "ENTRY_CONFIRM_REVIEW"
        assert truth(rows.loc["AAA", "vix_is_standalone_stock_action_evidence"]) is False
        observations = (
            Path(args.output_dir) / "forward_observations.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        assert len(observations) == 2
        assert {
            json.loads(line)["forward_outcome_status"] for line in observations
        } == {"UNRESOLVED"}

    # A provenance change discovered after staged writes publishes only the
    # BLOCKED summary; no conflicted observation file remains archivable.
    with tempfile.TemporaryDirectory() as tmp:
        args = build_fixture(Path(tmp))
        original = challenger.changed_input_failures
        calls = {"count": 0}

        def fail_after_staging(*_args: object, **_kwargs: object) -> list[str]:
            calls["count"] += 1
            return (
                ["source_changed_during_staged_write"]
                if calls["count"] == 2
                else []
            )

        challenger.changed_input_failures = fail_after_staging
        try:
            summary = challenger.build(args)
        finally:
            challenger.changed_input_failures = original
        assert summary["status"] == challenger.BLOCKED_STATUS
        for name in challenger.DATA_OUTPUT_NAMES:
            assert not (Path(args.output_dir) / name).exists(), name
        assert (Path(args.output_dir) / "summary.json").is_file()

    # A delayed invocation cannot backfill an old session as an unresolved
    # forward event after its outcomes may already be observable.
    with tempfile.TemporaryDirectory() as tmp:
        args = build_fixture(Path(tmp))
        args.observation_accepted_at_utc = "2026-07-31T21:05:00Z"
        summary = build(args)
        assert summary["status"] == challenger.BLOCKED_STATUS
        assert "observation_acceptance_delayed" in summary["contract_failures"]
        assert not (
            Path(args.output_dir) / "forward_observations.jsonl"
        ).exists()

    # READY is committed only after report.md succeeds. A report I/O failure
    # removes every data artifact and leaves only a BLOCKED summary.
    with tempfile.TemporaryDirectory() as tmp:
        args = build_fixture(Path(tmp))
        original_write_text = Path.write_text

        def fail_report(
            self: Path, *_args: object, **_kwargs: object
        ) -> int:
            if "report.md" in self.name:
                raise OSError("simulated report write failure")
            return original_write_text(self, *_args, **_kwargs)

        Path.write_text = fail_report
        try:
            summary = build(args)
        finally:
            Path.write_text = original_write_text
        assert summary["status"] == challenger.BLOCKED_STATUS
        assert any(
            str(value).startswith("ready_finalize:OSError:")
            for value in summary["contract_failures"]
        )
        for name in challenger.DATA_OUTPUT_NAMES:
            assert not (Path(args.output_dir) / name).exists(), name
        assert (Path(args.output_dir) / "summary.json").is_file()

    print("run287 ohlcv location timing challenger smoke: PASS")


def truth(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


if __name__ == "__main__":
    main()

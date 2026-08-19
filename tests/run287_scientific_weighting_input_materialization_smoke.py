#!/usr/bin/env python3
"""Smoke tests for scientific weighting input materialization."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import build_run287_scientific_weighting_inputs as builder  # noqa: E402


NYSE = mcal.get_calendar("NYSE")
MATERIALIZATION_CONTRACT = (
    ROOT / "docs" / "run287_scientific_weighting_input_materialization_contract.json"
)
READINESS_CONTRACT = (
    ROOT / "docs" / "run287_scientific_selection_allocation_contract.json"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def make_args(
    *,
    output_dir: Path,
    component_path: Path | None = None,
    scored_path: Path | None = None,
    price_path: Path,
    prior_path: Path,
    attestation_path: Path,
    as_of: pd.Timestamp,
) -> SimpleNamespace:
    return SimpleNamespace(
        contract=str(MATERIALIZATION_CONTRACT),
        readiness_contract=str(READINESS_CONTRACT),
        component_observations=[str(component_path)] if component_path else None,
        scored_snapshot=[str(scored_path)] if scored_path else None,
        price_observations=str(price_path),
        price_map=None,
        price_manifest="",
        price_search_root="",
        static_archive="",
        archive_restore_root="",
        prior_weights_source=str(prior_path),
        prior_weight_column="weight",
        prior_attestation=str(attestation_path),
        portfolio_id="synthetic_main",
        weight_basis="total_portfolio_including_cash",
        benchmark_ticker="SPY",
        as_of_time=as_of.isoformat(),
        output_dir=str(output_dir),
    )


def accepted_attestation(prior_path: Path) -> dict[str, object]:
    return {
        "schema_version": "run287-scientific-prior-weights-attestation-v1",
        "status": "ACCEPTED_RESEARCH_PRIOR_WEIGHTS",
        "source_sha256": sha256_file(prior_path),
        "weight_column": "weight",
        "portfolio_id": "synthetic_main",
        "weight_basis": "total_portfolio_including_cash",
        "available_from": "2018-01-02T21:00:00Z",
        "research_only": True,
    }


def test_complete_canonical_inputs_pass_readiness(tmp: Path) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    schedule = NYSE.schedule(start_date="2017-01-03", end_date="2024-12-31")
    sessions = pd.to_datetime(schedule.index).tz_localize(None).normalize()
    close_by_date = {
        pd.Timestamp(date).normalize(): pd.Timestamp(close).tz_convert("UTC")
        for date, close in schedule["market_close"].items()
    }
    decision_dates = list(sessions[300:1501:20])[:60]
    assert len(decision_dates) == 60
    price_sessions = sessions[250:1650]
    tickers = [f"T{i:03d}" for i in range(100)]

    component_rows: list[dict[str, object]] = []
    for date_index, decision_date in enumerate(decision_dates):
        decision_time = close_by_date[decision_date]
        for ticker_index, ticker in enumerate(tickers):
            row: dict[str, object] = {
                "feature_date": decision_date,
                "rebalance_date": decision_date,
                "decision_time_utc": decision_time,
                "ticker": ticker,
                "sector": f"S{ticker_index % 10}",
                "stable_security_id": f"SEC:{ticker_index:03d}",
                "pit_universe_label_clean": True,
            }
            for pillar_index, spec in enumerate(builder.PILLARS.values()):
                row[spec["raw"]] = (
                    ticker_index * (pillar_index + 1) + date_index * 0.01
                )
                row[spec["available"]] = decision_time
                row[spec["observed"]] = True
            component_rows.append(row)
    component_path = tmp / "component_observations.parquet"
    pd.DataFrame(component_rows).to_parquet(component_path, index=False)

    price_rows: list[dict[str, object]] = []
    all_price_tickers = tickers + ["SPY"]
    for ticker_index, ticker in enumerate(all_price_tickers):
        stable_id = (
            f"SEC:{ticker_index:03d}" if ticker != "SPY" else "BENCHMARK:SPY"
        )
        base = 50.0 + ticker_index
        for session_index, date in enumerate(price_sessions):
            price_rows.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "stable_security_id": stable_id,
                    "adjusted_close": base
                    * np.exp(0.00025 * session_index + 0.00001 * ticker_index * session_index),
                    "available_from": close_by_date[date],
                    "pit_lifecycle_state": "ACTIVE",
                    "pit_universe_label_clean": True,
                }
            )
    price_path = tmp / "price_observations.parquet"
    pd.DataFrame(price_rows).to_parquet(price_path, index=False)

    prior_path = tmp / "prior.csv"
    pd.DataFrame(
        {
            "rebalance_date": [decision_dates[-1]] * 10,
            "ticker": tickers[:10],
            "weight": [0.1] * 10,
        }
    ).to_csv(prior_path, index=False)
    attestation_path = tmp / "prior_attestation.json"
    write_json(attestation_path, accepted_attestation(prior_path))
    as_of = close_by_date[price_sessions[-1]] + pd.Timedelta(hours=1)

    output_dir = tmp / "output"
    summary = builder.build(
        make_args(
            output_dir=output_dir,
            component_path=component_path,
            price_path=price_path,
            prior_path=prior_path,
            attestation_path=attestation_path,
            as_of=as_of,
        )
    )
    assert summary["status"] == "MATERIALIZED_READY_FOR_PREREGISTRATION"
    assert summary["materialization_blockers"] == []
    assert summary["readiness_status"] == "READY_FOR_PREREGISTRATION"
    assert summary["readiness_data_ready"] is True
    assert summary["row_counts"]["component_frame"] == 6000
    assert summary["row_counts"]["daily_returns"] > 100_000
    frame = pd.read_parquet(output_dir / "component_frame.parquet")
    assert frame["realized_benchmark_excess_63d"].notna().all()
    assert frame["realized_benchmark_excess_126d"].notna().all()
    assert frame["pillar_quality_moat"].between(-0.5, 0.5).all()
    prior = pd.read_csv(output_dir / "prior_weights.csv")
    assert prior["source_sha256"].eq(sha256_file(prior_path)).all()
    assert prior["source_accepted"].astype(bool).all()


def test_scored_snapshot_adapter_stays_fail_closed(tmp: Path) -> None:
    schedule = NYSE.schedule(start_date="2024-01-02", end_date="2025-08-29")
    sessions = pd.to_datetime(schedule.index).tz_localize(None).normalize()
    close_by_date = {
        pd.Timestamp(date).normalize(): pd.Timestamp(close).tz_convert("UTC")
        for date, close in schedule["market_close"].items()
    }
    decision_date = sessions[260]
    score_time = close_by_date[decision_date] + pd.Timedelta(minutes=30)
    scored = pd.DataFrame(
        {
            "feature_date": [decision_date, decision_date],
            "rebalance_date": [decision_date, decision_date],
            "ticker": ["AAA", "BBB"],
            "sector": ["Tech", "Health"],
            "identity_cik10": [1, 2],
            "score_available_from": [score_time, score_time],
            "feature_available_from": [close_by_date[decision_date]] * 2,
            "decision_feature_complete": [False, False],
            "latest_only_inputs_neutralized": [True, True],
            "current_technical_context_row_count": [2, 2],
            "actual_report_available": [True, False],
            "institutional_actual_available": [False, False],
            "moat_quality_blueprint_score": [0.2, 0.8],
            "valuation_blueprint_score": [0.4, 0.6],
            "growth_blueprint_score": [0.3, 0.7],
            "revision_blueprint_score": [0.1, 0.9],
            "technical_blueprint_score": [0.2, 0.8],
            "actual_results_score": [0.5, 0.0],
            "sec_13f_score": [0.0, 0.0],
            "pit_universe_label_clean": [False, False],
        }
    )
    scored_path = tmp / "scored.csv"
    scored.to_csv(scored_path, index=False)

    price_rows: list[dict[str, object]] = []
    for ticker, stable_id, drift in (
        ("AAA", "UNVERIFIED_SEC_CIK:0000000001:TICKER:AAA", 0.0004),
        ("BBB", "UNVERIFIED_SEC_CIK:0000000002:TICKER:BBB", 0.0002),
        ("SPY", "BENCHMARK:SPY", 0.0003),
    ):
        for index, date in enumerate(sessions):
            price_rows.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "stable_security_id": stable_id,
                    "adjusted_close": 100.0 * np.exp(drift * index),
                    "available_from": close_by_date[date],
                    "pit_lifecycle_state": "UNVERIFIED_CURRENT_VINTAGE",
                    "pit_universe_label_clean": False,
                }
            )
    price_path = tmp / "prices.parquet"
    pd.DataFrame(price_rows).to_parquet(price_path, index=False)
    prior_path = tmp / "prior.csv"
    pd.DataFrame(
        {
            "rebalance_date": [decision_date] * 10,
            "ticker": [f"P{i}" for i in range(10)],
            "weight": [0.1] * 10,
        }
    ).to_csv(prior_path, index=False)
    attestation_path = tmp / "prior_attestation.json"
    write_json(attestation_path, accepted_attestation(prior_path))
    as_of = close_by_date[sessions[-1]] + pd.Timedelta(hours=1)
    output_dir = tmp / "output"

    summary = builder.build(
        make_args(
            output_dir=output_dir,
            scored_path=scored_path,
            price_path=price_path,
            prior_path=prior_path,
            attestation_path=attestation_path,
            as_of=as_of,
        )
    )
    assert summary["status"] == "MATERIALIZED_RESEARCH_INPUTS_WITH_BLOCKERS"
    assert summary["readiness_status"] == "BLOCKED_DATA_READINESS"
    assert "component_frame_missing" not in summary["readiness_data_blockers"]
    assert "daily_returns_missing" not in summary["readiness_data_blockers"]
    assert "prior_weights_missing" not in summary["readiness_data_blockers"]
    assert "component_frame_pit_universe_not_clean" in summary["readiness_data_blockers"]
    assert "daily_returns_pit_universe_not_clean" in summary["readiness_data_blockers"]
    frame = pd.read_parquet(output_dir / "component_frame.parquet")
    assert frame["pillar_quality_moat"].isna().all()
    assert frame["pillar_growth_revisions"].isna().all()
    assert frame["pillar_13f_manager_flow"].isna().all()
    assert frame["pillar_leadership_momentum"].notna().all()
    assert frame["stable_security_id"].str.startswith("UNVERIFIED_SEC_CIK:").all()
    assert not frame["pit_universe_label_clean"].any()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="run287-scientific-inputs-") as raw:
        tmp = Path(raw)
        test_complete_canonical_inputs_pass_readiness(tmp / "complete")
    with tempfile.TemporaryDirectory(prefix="run287-scientific-inputs-blocked-") as raw:
        tmp = Path(raw)
        tmp.mkdir(parents=True, exist_ok=True)
        test_scored_snapshot_adapter_stays_fail_closed(tmp)
    print("run287_scientific_weighting_input_materialization_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

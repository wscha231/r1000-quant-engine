#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import audit_run287_scientific_weighting_readiness as audit  # noqa: E402


CONTRACT = ROOT / "docs" / "run287_scientific_selection_allocation_contract.json"
AS_OF = "2026-08-19T12:00:00Z"


def component_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    schedule = audit.NYSE.schedule(start_date="2019-01-01", end_date="2024-01-31")
    session_frame = pd.DataFrame({"date": pd.DatetimeIndex(schedule.index).tz_localize(None)})
    session_frame["month"] = session_frame["date"].dt.to_period("M")
    dates = session_frame.groupby("month", sort=True)["date"].first().iloc[:60].tolist()
    close_map = {
        pd.Timestamp(session).normalize(): pd.Timestamp(close).tz_convert("UTC")
        for session, close in schedule["market_close"].items()
    }
    component_specs = list(
        audit.read_json(CONTRACT)["component_model"]["inputs"].values()
    )
    for date_index, date in enumerate(dates):
        decision = close_map[pd.Timestamp(date).normalize()] + pd.Timedelta(minutes=1)
        for ticker_index in range(100):
            ticker = f"T{ticker_index:03d}"
            base = (ticker_index + 1) / 101.0
            row: dict[str, object] = {
                "feature_date": date.date().isoformat(),
                "rebalance_date": date.date().isoformat(),
                "decision_time_utc": decision.isoformat(),
                "ticker": ticker,
                "sector": f"S{ticker_index % 10}",
                "stable_security_id": f"SEC-{ticker}",
                "pit_universe_label_clean": True,
                "realized_benchmark_excess_63d": base * 0.02 - 0.01,
                "realized_benchmark_excess_126d": base * 0.03 - 0.015,
                "label_available_at_63d": (decision + pd.Timedelta(days=100)).isoformat(),
                "label_available_at_126d": (decision + pd.Timedelta(days=200)).isoformat(),
            }
            for component_index, spec in enumerate(component_specs):
                row[spec["column"]] = base + component_index * 0.001 + date_index * 0.00001
                row[spec["available_from_column"]] = (
                    decision - pd.Timedelta(minutes=1)
                ).isoformat()
                row[spec["observed_column"]] = True
            rows.append(row)
    return pd.DataFrame(rows)


def daily_returns() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    schedule = audit.NYSE.schedule(start_date="2024-01-02", end_date="2025-06-30").iloc[:300]
    dates = pd.DatetimeIndex(schedule.index).tz_localize(None)
    close_map = {
        pd.Timestamp(session).normalize(): pd.Timestamp(close).tz_convert("UTC")
        for session, close in schedule["market_close"].items()
    }
    for date_index, date in enumerate(dates):
        available = close_map[pd.Timestamp(date).normalize()] + pd.Timedelta(minutes=1)
        for ticker_index in range(100):
            ticker = f"T{ticker_index:03d}"
            rows.append(
                {
                    "date": date.date().isoformat(),
                    "ticker": ticker,
                    "stable_security_id": f"SEC-{ticker}",
                    "return": 0.0001 * np.sin(date_index + ticker_index),
                    "available_from": available.isoformat(),
                    "pit_lifecycle_state": "ACTIVE",
                    "pit_universe_label_clean": True,
                }
            )
    return pd.DataFrame(rows)


def prior_weights() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "rebalance_date": "2025-12-01",
                "ticker": f"T{index:03d}",
                "weight": 0.1,
                "source_sha256": "a" * 64,
            }
            for index in range(10)
        ]
    )


def write_fixture(root: Path) -> tuple[Path, Path, Path]:
    component_path = root / "component_frame.csv"
    returns_path = root / "daily_returns.csv"
    prior_path = root / "prior_weights.csv"
    component_frame().to_csv(component_path, index=False)
    daily_returns().to_csv(returns_path, index=False)
    prior_weights().to_csv(prior_path, index=False)
    return component_path, returns_path, prior_path


def run_fixture(
    root: Path,
    *,
    contract: Path = CONTRACT,
    component: Path | None,
    returns: Path | None,
    prior: Path | None,
) -> dict[str, object]:
    return audit.audit(
        contract_path=contract,
        component_frame_path=component,
        daily_returns_path=returns,
        prior_weights_path=prior,
        output_dir=root / "out",
        as_of_time=AS_OF,
    )


def test_contract_is_valid() -> None:
    contract = audit.read_json(CONTRACT)
    assert audit.validate_contract(contract) == []


def test_missing_data_blocks_without_running_research() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload = run_fixture(root, component=None, returns=None, prior=None)
        assert payload["status"] == audit.BLOCKED_STATUS
        assert payload["data_ready"] is False
        assert payload["safety"]["research_fit_executed"] is False
        assert payload["safety"]["portfolio_weights_produced"] is False
        assert set(payload["data_blockers"]) == {
            "component_frame_missing",
            "daily_returns_missing",
            "prior_weights_missing",
        }


def test_complete_pit_fixture_is_ready_only_for_preregistration() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        component, returns, prior = write_fixture(root)
        payload = run_fixture(
            root,
            component=component,
            returns=returns,
            prior=prior,
        )
        assert payload["status"] == audit.READY_STATUS, payload["data_blockers"]
        assert payload["contract_valid"] is True
        assert payload["data_ready"] is True
        assert payload["method_boundary"]["real_fit_authorized"] is False
        assert payload["method_boundary"]["portfolio_replay_authorized"] is False
        assert (root / "out" / "contract_audit.json").is_file()
        assert (root / "out" / "data_readiness.json").is_file()
        assert (root / "out" / "report.md").is_file()


def test_future_component_availability_blocks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        component, returns, prior = write_fixture(root)
        frame = pd.read_csv(component)
        frame.loc[0, "pillar_quality_moat_available_from"] = "2026-08-20T00:00:00Z"
        frame.to_csv(component, index=False)
        payload = run_fixture(
            root,
            component=component,
            returns=returns,
            prior=prior,
        )
        assert payload["status"] == audit.BLOCKED_STATUS
        assert "component_available_after_decision:quality_moat" in payload["data_blockers"]


def test_macro_alpha_or_13f_overweight_invalidates_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        contract = audit.read_json(CONTRACT)
        contract["decision_layers"]["macro_risk_router"]["direct_stock_alpha_points_allowed"] = True
        contract["component_model"]["inputs"]["manager_13f_flow"]["maximum_learned_weight"] = 0.25
        invalid_path = root / "invalid_contract.json"
        invalid_path.write_text(json.dumps(contract), encoding="utf-8")
        payload = run_fixture(
            root,
            contract=invalid_path,
            component=None,
            returns=None,
            prior=None,
        )
        assert payload["status"] == audit.INVALID_STATUS
        assert "macro_direct_stock_alpha_points_allowed" in payload["contract_failures"]
        assert "13f_weight_boundary_invalid" in payload["contract_failures"]
        assert payload["safety"]["champion_changed"] is False


if __name__ == "__main__":
    test_contract_is_valid()
    test_missing_data_blocks_without_running_research()
    test_complete_pit_fixture_is_ready_only_for_preregistration()
    test_future_component_availability_blocks()
    test_macro_alpha_or_13f_overweight_invalidates_contract()
    print("run287_scientific_weighting_readiness_smoke: PASS")

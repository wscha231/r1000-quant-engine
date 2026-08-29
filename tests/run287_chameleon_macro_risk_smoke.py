#!/usr/bin/env python3
"""Contract and leakage smoke tests for Chameleon macro-risk report-only v1."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import build_run287_chameleon_macro_risk as risk  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract() -> dict:
    return risk.load_contract()


def calendar_fixture(
    dates: pd.DatetimeIndex,
    *,
    ordinal_start: int = 0,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "decision_date": [date.date().isoformat() for date in dates],
            "decision_time_utc": [
                (pd.Timestamp(date).tz_localize("UTC") + pd.Timedelta(hours=22)).isoformat()
                for date in dates
            ],
            "nyse_session_ordinal": [ordinal_start + position for position in range(len(dates))],
        }
    )


def metric_fixture(
    dates: pd.DatetimeIndex,
    *,
    future_available: bool = False,
    ordinal_start: int = 0,
    calendar_hash: str = "c" * 64,
) -> pd.DataFrame:
    cfg = contract()
    rows: list[dict] = []
    for date_position, date in enumerate(dates):
        decision_time = pd.Timestamp(date).tz_localize("UTC") + pd.Timedelta(hours=22)
        for axis, spec in cfg["axes"].items():
            for component, direction in spec["components"].items():
                value = 1.0
                available = decision_time
                if future_available and date_position == len(dates) - 1 and component == "vix_level":
                    available += pd.Timedelta(seconds=1)
                rows.append(
                    {
                        "decision_date": date.date().isoformat(),
                        "decision_time_utc": decision_time.isoformat(),
                        "nyse_session_ordinal": ordinal_start + date_position,
                        "calendar_source_sha256": calendar_hash,
                        "axis": axis,
                        "component": component,
                        "raw_value": value,
                        "risk_direction": direction,
                        "source_observation_date": date.date().isoformat(),
                        "available_from": available.isoformat(),
                        "source_kind": "SYNTHETIC_PIT_FIXTURE",
                        "source_sha256": "a" * 64,
                        "truth_class": "PIT_VERIFIED",
                    }
                )
    return pd.DataFrame(rows)


def context_fixture(
    dates: pd.DatetimeIndex,
    *,
    ordinal_start: int = 0,
    calendar_hash: str = "c" * 64,
) -> pd.DataFrame:
    rows = []
    for position, date in enumerate(dates):
        decision_time = pd.Timestamp(date).tz_localize("UTC") + pd.Timedelta(hours=22)
        rows.append(
            {
                "decision_date": date.date().isoformat(),
                "decision_time_utc": decision_time.isoformat(),
                "nyse_session_ordinal": ordinal_start + position,
                "calendar_source_sha256": calendar_hash,
                "source_observation_date": date.date().isoformat(),
                "available_from": decision_time.isoformat(),
                "source_kind": "SYNTHETIC_PIT_FIXTURE",
                "source_sha256": "b" * 64,
                "truth_class": "PIT_VERIFIED",
                "spy_close": 100.0,
                "spy_prior_2d_high": 101.0,
                "spy_ma20": 100.0,
                "portfolio_fundamental_weak_ratio": 0.10,
                "breadth_improving": False,
                "hy_spread_widening": False,
                "leadership_breadth_confirmed": False,
                "market_new_low": False,
                "index_new_high_breadth_narrowing": False,
            }
        )
    return pd.DataFrame(rows)


def axis_fixture(dates: pd.DatetimeIndex, scores: dict[str, float], ready: set[str] | None = None) -> pd.DataFrame:
    cfg = contract()
    ready = set(cfg["axes"]) if ready is None else ready
    rows = []
    for position, date in enumerate(dates):
        for axis, spec in cfg["axes"].items():
            is_ready = axis in ready
            score = float(scores.get(axis, 50.0))
            rows.append(
                {
                    "decision_date": date,
                    "decision_time_utc": pd.Timestamp(date).tz_localize("UTC") + pd.Timedelta(hours=22),
                    "nyse_session_ordinal": position,
                    "calendar_source_sha256": "c" * 64,
                    "axis": axis,
                    "weight": float(spec["weight"]),
                    "red_domain": spec["red_domain"],
                    "registered_component_count": len(spec["components"]),
                    "observed_component_count": len(spec["components"]) if is_ready else 0,
                    "ready_component_count": int(spec["minimum_ready_components"]) if is_ready else 0,
                    "minimum_ready_components": int(spec["minimum_ready_components"]),
                    "ready_component_names": "fixture" if is_ready else "",
                    "axis_score": score if is_ready else np.nan,
                    "axis_ready": is_ready,
                    "red_axis": bool(is_ready and score >= 80.0),
                    "source_hash_bundle_sha256": "d" * 64 if is_ready else None,
                    "truth_class": "PIT_VERIFIED" if is_ready else None,
                }
            )
    return pd.DataFrame(rows)


def empty_context() -> pd.DataFrame:
    return pd.DataFrame(columns=list(risk.CONTEXT_REQUIRED_COLUMNS))


def test_contract_freezes_exact_axes_weights_and_nonexecution() -> None:
    cfg = contract()
    assert len(cfg["axes"]) == 10
    assert abs(sum(float(spec["weight"]) for spec in cfg["axes"].values()) - 1.0) < 1e-12
    assert cfg["readiness"]["minimum_ready_axes"] == 8
    assert set(cfg["readiness"]["required_axes"]) == {"market_breadth", "volatility", "credit"}
    assert cfg["percentile"]["red_percentile"] == 80.0
    assert cfg["calendar_artifact"]["metric_dates_must_equal_contiguous_calendar_slice"] is True
    assert cfg["calendar_artifact"]["caller_supplied_hash_without_artifact_is_valid"] is False
    assert cfg["context_columns"]["required_provenance"] == [
        "source_observation_date",
        "available_from",
        "source_kind",
        "source_sha256",
        "truth_class",
    ]
    assert cfg["safety"]["report_only"] is True
    for field, value in cfg["safety"].items():
        if field != "report_only":
            assert value is False, field
    with tempfile.TemporaryDirectory() as tmp:
        alternate = Path(tmp) / "modified_contract.json"
        modified = json.loads(json.dumps(cfg))
        modified["percentile"]["red_percentile"] = 99.0
        alternate.write_text(json.dumps(modified), encoding="utf-8")
        try:
            risk.load_contract(alternate)
            raise AssertionError("alternate contract path was accepted")
        except risk.ContractError as exc:
            assert str(exc).startswith("noncanonical_contract_path:")


def test_percentiles_are_trailing_only_under_future_outlier() -> None:
    cfg = contract()
    dates = pd.bdate_range("2024-01-02", periods=260)
    base_raw = metric_fixture(dates)
    mask = base_raw["component"].eq("vix_level")
    base_raw.loc[mask, "raw_value"] = np.linspace(10.0, 20.0, mask.sum())
    base_calendar = risk.validate_calendar(calendar_fixture(dates), "c" * 64)
    base = risk.validate_metrics(base_raw, cfg, dates[-1], base_calendar)
    base_scores = risk.compute_component_percentiles(base, cfg)

    future_date = dates[-1] + pd.offsets.BDay(1)
    future = metric_fixture(pd.DatetimeIndex([future_date]), ordinal_start=len(dates))
    future.loc[future["component"].eq("vix_level"), "raw_value"] = 10_000.0
    combined_raw = pd.concat([base_raw, future], ignore_index=True)
    combined_calendar = risk.validate_calendar(
        calendar_fixture(dates.append(pd.DatetimeIndex([future_date]))),
        "c" * 64,
    )
    combined = risk.validate_metrics(combined_raw, cfg, future_date, combined_calendar)
    combined_scores = risk.compute_component_percentiles(combined, cfg)

    selector = (base_scores["decision_date"] == dates[-1]) & base_scores["component"].eq("vix_level")
    selector_future = (combined_scores["decision_date"] == dates[-1]) & combined_scores["component"].eq("vix_level")
    assert float(base_scores.loc[selector, "raw_percentile"].iloc[0]) == float(
        combined_scores.loc[selector_future, "raw_percentile"].iloc[0]
    )


def test_calendar_gaps_and_current_vintage_pit_claims_fail_closed() -> None:
    cfg = contract()
    dates = pd.bdate_range("2025-01-02", periods=5)
    calendar = risk.validate_calendar(calendar_fixture(dates), "c" * 64)
    calendar_gap = metric_fixture(dates)
    calendar_gap.loc[calendar_gap["decision_date"].eq(dates[-1].date().isoformat()), "nyse_session_ordinal"] += 1
    try:
        risk.validate_metrics(calendar_gap, cfg, dates[-1], calendar)
        raise AssertionError("calendar gap was accepted")
    except risk.ContractError as exc:
        assert str(exc).startswith("metric_calendar_session_mismatch:")

    omitted = metric_fixture(dates.delete(2))
    omitted.loc[omitted["decision_date"].gt(dates[2].date().isoformat()), "nyse_session_ordinal"] += 1
    try:
        risk.validate_metrics(omitted, cfg, dates[-1], calendar)
        raise AssertionError("omitted NYSE session was accepted")
    except risk.ContractError as exc:
        assert str(exc) == "metric_calendar_session_coverage_mismatch"

    wrong_timestamp = metric_fixture(dates)
    target = wrong_timestamp["decision_date"].eq(dates[-1].date().isoformat())
    wrong_timestamp.loc[target, "decision_time_utc"] = (
        pd.Timestamp(dates[-1]).tz_localize("UTC") + pd.Timedelta(days=1, hours=22)
    ).isoformat()
    wrong_timestamp.loc[target, "available_from"] = wrong_timestamp.loc[target, "decision_time_utc"]
    try:
        risk.validate_metrics(wrong_timestamp, cfg, dates[-1], calendar)
        raise AssertionError("decision timestamp from another session was accepted")
    except risk.ContractError as exc:
        assert str(exc).startswith("metric_calendar_session_mismatch:")

    current_vintage = metric_fixture(dates)
    current_vintage.loc[current_vintage["component"].eq("vix_level"), "source_kind"] = "FRED_CURRENT_VINTAGE"
    try:
        risk.validate_metrics(current_vintage, cfg, dates[-1], calendar)
        raise AssertionError("current-vintage PIT claim was accepted")
    except risk.ContractError as exc:
        assert str(exc) == "current_vintage_source_cannot_be_pit_verified"

    blank_source = metric_fixture(dates)
    blank_source.loc[blank_source.index[0], "source_kind"] = np.nan
    try:
        risk.validate_metrics(blank_source, cfg, dates[-1], calendar)
        raise AssertionError("blank metric source kind was accepted")
    except risk.ContractError as exc:
        assert str(exc) == "missing_metric_source_kind"

    valid_metrics = risk.validate_metrics(metric_fixture(dates), cfg, dates[-1], calendar)
    decision_times = {
        date: group["decision_time_utc"].iloc[0]
        for date, group in valid_metrics.groupby("decision_date")
    }
    sessions = {
        date: (
            int(group["nyse_session_ordinal"].iloc[0]),
            str(group["calendar_source_sha256"].iloc[0]),
        )
        for date, group in valid_metrics.groupby("decision_date")
    }
    current_context = context_fixture(dates)
    current_context["source_kind"] = "LATEST_SNAPSHOT"
    try:
        risk.validate_context(
            current_context,
            cfg,
            dates[-1],
            decision_times,
            sessions,
            calendar,
        )
        raise AssertionError("current-vintage context PIT claim was accepted")
    except risk.ContractError as exc:
        assert str(exc) == "current_vintage_context_cannot_be_pit_verified"

    blank_context = context_fixture(dates)
    blank_context.loc[blank_context.index[0], "source_kind"] = np.nan
    try:
        risk.validate_context(
            blank_context,
            cfg,
            dates[-1],
            decision_times,
            sessions,
            calendar,
        )
        raise AssertionError("blank context source kind was accepted")
    except risk.ContractError as exc:
        assert str(exc) == "missing_context_source_kind"


def test_core_readiness_and_single_vix_cannot_create_defense() -> None:
    cfg = contract()
    dates = pd.bdate_range("2026-01-05", periods=3)
    scores = {axis: 50.0 for axis in cfg["axes"]}
    scores["volatility"] = 100.0
    state = risk.build_daily_risk(axis_fixture(dates, scores), empty_context(), cfg)
    assert state["state_change_allowed"].all()
    assert state.iloc[-1]["effective_state"] == "NORMAL"
    assert int(state.iloc[-1]["red_axis_count"]) == 1

    eight_ready = set(cfg["axes"]) - {"cross_asset", "economic_stress"}
    ready_state = risk.build_daily_risk(axis_fixture(dates, scores, eight_ready), empty_context(), cfg)
    assert ready_state["state_change_allowed"].all()
    missing_credit = (eight_ready - {"credit"}) | {"cross_asset"}
    blocked_state = risk.build_daily_risk(axis_fixture(dates, scores, missing_credit), empty_context(), cfg)
    assert not blocked_state["state_change_allowed"].any()
    assert blocked_state["new_buys_frozen"].all()
    assert blocked_state["risk_score"].isna().all()

    retained_input = pd.concat(
        [
            axis_fixture(dates[:2], scores),
            axis_fixture(pd.DatetimeIndex([dates[2]]), scores, missing_credit).assign(
                nyse_session_ordinal=2
            ),
        ],
        ignore_index=True,
    )
    retained = risk.build_daily_risk(retained_input, empty_context(), cfg)
    assert retained.iloc[1]["effective_state"] == "NORMAL"
    assert retained.iloc[2]["effective_state"] == "NORMAL"
    assert pd.isna(retained.iloc[2]["risk_score"])
    assert bool(retained.iloc[2]["new_buys_frozen"])


def test_market_state_requires_two_entry_and_five_release_sessions() -> None:
    cfg = contract()
    dates = pd.bdate_range("2026-02-02", periods=11)
    observed = ["NORMAL", "NORMAL", "RISK_DEFENSE", "RISK_DEFENSE"] + ["NORMAL"] * 7
    daily = pd.DataFrame(
        {
            "decision_date": dates,
            "risk_score": [50.0, 50.0, 80.0, 80.0] + [50.0] * 7,
            "ready_axis_count": 10,
            "required_axes_ready": True,
            "ready_axis_weight": 1.0,
            "red_axis_count": [0, 0, 6, 6] + [0] * 7,
            "red_domain_count": [0, 0, 4, 4] + [0] * 7,
            "red_axes": "",
            "observed_state": observed,
            "state_change_allowed": True,
            "new_buys_frozen": False,
            "portfolio_fundamental_weak_ratio": 0.0,
            "portfolio_fragility": False,
        }
    )
    result = risk.apply_state_hysteresis(daily, cfg)
    assert result.iloc[0]["effective_state"] == "DATA_INSUFFICIENT"
    assert result.iloc[1]["effective_state"] == "NORMAL"
    assert result.iloc[2]["effective_state"] == "NORMAL"
    assert result.iloc[3]["effective_state"] == "RISK_DEFENSE"
    assert result.iloc[7]["effective_state"] == "RISK_DEFENSE"
    assert result.iloc[8]["effective_state"] == "NORMAL"

    alternating = daily.iloc[:4].copy()
    alternating["observed_state"] = [
        "NORMAL",
        "NORMAL",
        "RISK_ALERT",
        "RISK_DEFENSE",
    ]
    alternating_result = risk.apply_state_hysteresis(alternating, cfg)
    assert alternating_result.iloc[-1]["effective_state"] == "RISK_ALERT"


def test_extreme_greed_and_fear_recovery_use_frozen_confirmation() -> None:
    cfg = contract()
    dates = list(pd.bdate_range("2026-03-02", periods=10))
    market = pd.DataFrame(
        {
            "decision_date": dates,
            "risk_score": [50.0] * 10,
            "effective_state": ["NORMAL"] * 10,
        }
    )
    rows = []
    for position, date in enumerate(dates):
        tail_value = 5.0 if position < 5 else 50.0
        for component, percentile in {
            "vix_level": tail_value,
            "hy_oas_level": tail_value,
            "ig_oas_level": tail_value,
            "spy_ma200_distance": 95.0 if position < 5 else 50.0,
            "equity_put_call": tail_value,
        }.items():
            rows.append(
                {
                    "decision_date": date,
                    "component": component,
                    "raw_percentile": percentile,
                    "component_ready": True,
                }
            )
    component_scores = pd.DataFrame(rows)
    context = pd.DataFrame(
        {
            "decision_date": dates,
            "index_new_high_breadth_narrowing": [True] * 5 + [False] * 5,
        }
    )
    greed = risk.build_sentiment_history(market, component_scores, context, cfg)
    assert not bool(greed.iloc[3]["extreme_greed_active"])
    assert bool(greed.iloc[4]["extreme_greed_active"])
    assert greed.iloc[4]["sentiment_overlay"] == "EXTREME_GREED"
    assert not bool(greed.iloc[9]["extreme_greed_active"])

    alternating_dates = list(pd.bdate_range("2026-05-01", periods=15))
    alternating_market = pd.DataFrame(
        {
            "decision_date": alternating_dates,
            "risk_score": [50.0] * 15,
            "effective_state": ["NORMAL"] * 15,
        }
    )
    alternating_rows = []
    for position, date in enumerate(alternating_dates):
        entry = position < 5
        two_conditions = position >= 5 and position % 2 == 1
        spread_low = entry or (position >= 5 and not two_conditions)
        for component, percentile in {
            "vix_level": 5.0,
            "hy_oas_level": 5.0 if spread_low else 50.0,
            "ig_oas_level": 5.0 if spread_low else 50.0,
            "spy_ma200_distance": 95.0 if entry else 50.0,
            "equity_put_call": 5.0 if entry else 50.0,
        }.items():
            alternating_rows.append(
                {
                    "decision_date": date,
                    "component": component,
                    "raw_percentile": percentile,
                    "component_ready": True,
                }
            )
    alternating_context = pd.DataFrame(
        {
            "decision_date": alternating_dates,
            "index_new_high_breadth_narrowing": [True] * 15,
        }
    )
    alternating_greed = risk.build_sentiment_history(
        alternating_market,
        pd.DataFrame(alternating_rows),
        alternating_context,
        cfg,
    )
    assert bool(alternating_greed.iloc[-1]["extreme_greed_active"])

    fear_dates = list(pd.bdate_range("2026-04-01", periods=8))
    fear_market = pd.DataFrame(
        {
            "decision_date": fear_dates,
            "risk_score": [95.0, 94.0, 88.0, 87.0, 86.0, 84.0, 82.0, 80.0],
            "effective_state": ["EXTREME_FEAR", "EXTREME_FEAR"] + ["RISK_DEFENSE"] * 6,
        }
    )
    fear_context = pd.DataFrame(
        {
            "decision_date": fear_dates,
            "spy_close": [90, 91, 101, 102, 103, 104, 105, 106],
            "spy_prior_2d_high": [100] * 8,
            "spy_ma20": [110, 110, 110, 110, 110, 103, 103, 103],
            "breadth_improving": [False, False, True, True, True, True, True, True],
            "hy_spread_widening": [False] * 8,
            "leadership_breadth_confirmed": [False] * 8,
            "market_new_low": [False] * 8,
            "index_new_high_breadth_narrowing": [False] * 8,
        }
    )
    fear = risk.build_sentiment_history(
        fear_market,
        pd.DataFrame(columns=["decision_date", "component", "raw_percentile", "component_ready"]),
        fear_context,
        cfg,
    )
    assert int(fear.iloc[2]["fear_recovery_stage"]) == 1
    assert int(fear.iloc[4]["fear_recovery_stage"]) == 1
    assert int(fear.iloc[5]["fear_recovery_stage"]) == 2
    assert int(fear.iloc[6]["fear_recovery_stage"]) == 2
    assert int(fear.iloc[7]["fear_recovery_stage"]) == 3
    assert int(fear["fear_recovery_stage_changed"].sum()) == 3

    reset_dates = list(pd.bdate_range("2026-06-01", periods=4))
    reset_market = pd.DataFrame(
        {
            "decision_date": reset_dates,
            "risk_score": [95.0, 88.0, 50.0, 86.0],
            "effective_state": ["EXTREME_FEAR", "RISK_DEFENSE", "NORMAL", "RISK_ALERT"],
        }
    )
    reset_context = pd.DataFrame(
        {
            "decision_date": reset_dates,
            "spy_close": [90.0, 101.0, 102.0, 103.0],
            "spy_prior_2d_high": [100.0] * 4,
            "spy_ma20": [110.0] * 4,
            "breadth_improving": [False] * 4,
            "hy_spread_widening": [False] * 4,
            "leadership_breadth_confirmed": [False] * 4,
            "market_new_low": [False] * 4,
            "index_new_high_breadth_narrowing": [False] * 4,
        }
    )
    reset = risk.build_sentiment_history(
        reset_market,
        pd.DataFrame(columns=["decision_date", "component", "raw_percentile", "component_ready"]),
        reset_context,
        cfg,
    )
    assert int(reset.iloc[1]["fear_recovery_stage"]) == 1
    assert not bool(reset.iloc[2]["fear_episode_active"])
    assert int(reset.iloc[2]["fear_recovery_stage"]) == 0
    assert reset.iloc[3]["sentiment_overlay"] == "NONE"


def build_args(
    root: Path,
    calendar: Path,
    metrics: Path,
    context: Path,
    output_name: str,
    *,
    as_of: str = "",
) -> argparse.Namespace:
    return argparse.Namespace(
        calendar=str(calendar),
        input_metrics=str(metrics),
        input_context=str(context),
        as_of=as_of,
        contract=str(risk.DEFAULT_CONTRACT),
        output_dir=str(root / output_name),
    )


def test_build_is_deterministic_report_only_and_future_data_hard_fails() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dates = pd.bdate_range("2024-01-02", periods=260)
        calendar_path = root / "xnys_calendar.csv"
        calendar_fixture(dates).to_csv(calendar_path, index=False)
        calendar_hash = sha(calendar_path)
        metrics_path = root / "metrics.csv"
        context_path = root / "context.csv"
        metric_fixture(dates, calendar_hash=calendar_hash).to_csv(metrics_path, index=False)
        context_fixture(dates, calendar_hash=calendar_hash).to_csv(context_path, index=False)
        before = {
            "calendar": sha(calendar_path),
            "metrics": sha(metrics_path),
            "context": sha(context_path),
        }
        first = risk.build(build_args(root, calendar_path, metrics_path, context_path, "first"))
        second = risk.build(build_args(root, calendar_path, metrics_path, context_path, "second"))
        assert first["status"] == "READY_CHAMELEON_MACRO_RISK_REPORT_ONLY"
        assert first["latest"]["effective_state"] == "NORMAL"
        assert first["latest"]["state_change_allowed"] is True
        assert first["report_only"] is True
        assert first["selector_executed"] is False
        assert first["target_books_mutated"] is False
        assert first["trade_intents_written"] is False
        assert first["orders_generated"] is False
        assert first["ledger_mutated"] is False
        assert first["fullrun_executed"] is False
        assert first["live_trading_enabled"] is False
        assert before == {
            "calendar": sha(calendar_path),
            "metrics": sha(metrics_path),
            "context": sha(context_path),
        }
        for filename in (
            "component_percentiles.csv",
            "macro_risk_axes.csv",
            "market_state_history.csv",
            "sentiment_overlay_history.csv",
            "macro_risk_snapshot.json",
            "market_state.json",
            "sentiment_overlay.json",
        ):
            assert sha(root / "first" / filename) == sha(root / "second" / filename), filename
        assert json.loads((root / "first" / "market_state.json").read_text(encoding="utf-8"))["target_weights"] is None
        sentiment_json = json.loads((root / "first" / "sentiment_overlay.json").read_text(encoding="utf-8"))
        assert sentiment_json["decision_date"] == dates[-1].date().isoformat()

        future_path = root / "future.csv"
        metric_fixture(
            dates,
            future_available=True,
            calendar_hash=calendar_hash,
        ).to_csv(future_path, index=False)
        blocked = risk.build(
            build_args(root, calendar_path, future_path, context_path, "blocked")
        )
        assert blocked["status"] == risk.BLOCKED_STATUS
        assert blocked["blockers"] == ["future_available_from_metric_row"]
        assert blocked["target_books_mutated"] is False
        assert not (root / "blocked" / "market_state.json").exists()

        invalid_as_of = risk.build(
            build_args(
                root,
                calendar_path,
                metrics_path,
                context_path,
                "invalid-as-of",
                as_of="2026-99-99",
            )
        )
        assert invalid_as_of["status"] == risk.BLOCKED_STATUS
        assert invalid_as_of["blockers"] == ["invalid_explicit_as_of:2026-99-99"]

        missing_date_path = root / "missing_decision_date.csv"
        metric_fixture(dates, calendar_hash=calendar_hash).drop(columns=["decision_date"]).to_csv(
            missing_date_path,
            index=False,
        )
        missing_date = risk.build(
            build_args(
                root,
                calendar_path,
                missing_date_path,
                context_path,
                "missing-decision-date",
            )
        )
        assert missing_date["status"] == risk.BLOCKED_STATUS
        assert missing_date["blockers"] == ["missing_columns:decision_date"]
        assert (root / "missing-decision-date" / "manifest.json").is_file()

        race_metrics_path = root / "race_metrics.csv"
        metric_fixture(dates, calendar_hash=calendar_hash).to_csv(race_metrics_path, index=False)
        verified_race_hash = sha(race_metrics_path)
        original_fingerprint = risk.fingerprint
        race_metric_fingerprint_calls = 0

        def racing_fingerprint(path: Path) -> dict:
            nonlocal race_metric_fingerprint_calls
            result = original_fingerprint(path)
            if Path(path) == race_metrics_path:
                race_metric_fingerprint_calls += 1
                if race_metric_fingerprint_calls == 2:
                    race_metrics_path.write_text(
                        race_metrics_path.read_text(encoding="utf-8") + "\n",
                        encoding="utf-8",
                    )
            return result

        risk.fingerprint = racing_fingerprint
        try:
            race_payload = risk.build(
                build_args(
                    root,
                    calendar_path,
                    race_metrics_path,
                    context_path,
                    "fingerprint-race",
                )
            )
        finally:
            risk.fingerprint = original_fingerprint
        assert race_payload["status"] == "READY_CHAMELEON_MACRO_RISK_REPORT_ONLY"
        assert race_payload["inputs"]["metrics"]["sha256"] == verified_race_hash
        assert sha(race_metrics_path) != verified_race_hash
        race_truth = json.loads(
            (root / "fingerprint-race" / "backtest_truth_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert race_truth["metric_input"]["sha256"] == verified_race_hash

        code_race_metrics_path = root / "code_race_metrics.csv"
        metric_fixture(dates, calendar_hash=calendar_hash).to_csv(
            code_race_metrics_path,
            index=False,
        )
        builder_path = Path(risk.__file__).resolve()
        builder_fingerprint_calls = 0

        def changing_code_fingerprint(path: Path) -> dict:
            nonlocal builder_fingerprint_calls
            result = original_fingerprint(path)
            if Path(path).resolve() == builder_path:
                builder_fingerprint_calls += 1
                if builder_fingerprint_calls == 2:
                    result = {**result, "sha256": "f" * 64}
            return result

        risk.fingerprint = changing_code_fingerprint
        try:
            code_race = risk.build(
                build_args(
                    root,
                    calendar_path,
                    code_race_metrics_path,
                    context_path,
                    "code-identity-race",
                )
            )
        finally:
            risk.fingerprint = original_fingerprint
        assert code_race["status"] == risk.BLOCKED_STATUS
        assert code_race["blockers"] == ["code_identity_mutated_during_build"]
        assert not (root / "code-identity-race" / "backtest_truth_manifest.json").exists()

        short_dates = dates[:20]
        short_calendar_path = root / "short_xnys_calendar.csv"
        calendar_fixture(short_dates).to_csv(short_calendar_path, index=False)
        short_hash = sha(short_calendar_path)
        short_metrics_path = root / "short_metrics.csv"
        short_context_path = root / "short_context.csv"
        metric_fixture(short_dates, calendar_hash=short_hash).to_csv(short_metrics_path, index=False)
        context_fixture(short_dates, calendar_hash=short_hash).to_csv(short_context_path, index=False)
        insufficient = risk.build(
            build_args(
                root,
                short_calendar_path,
                short_metrics_path,
                short_context_path,
                "insufficient",
            )
        )
        assert insufficient["status"] == "READY_CHAMELEON_MACRO_RISK_REPORT_ONLY_DATA_INSUFFICIENT"
        for path in (root / "insufficient").glob("*.json"):
            json.loads(
                path.read_text(encoding="utf-8"),
                parse_constant=lambda value: (_ for _ in ()).throw(
                    AssertionError(f"non-standard JSON constant: {value}")
                ),
            )


def main() -> int:
    test_contract_freezes_exact_axes_weights_and_nonexecution()
    test_percentiles_are_trailing_only_under_future_outlier()
    test_calendar_gaps_and_current_vintage_pit_claims_fail_closed()
    test_core_readiness_and_single_vix_cannot_create_defense()
    test_market_state_requires_two_entry_and_five_release_sessions()
    test_extreme_greed_and_fear_recovery_use_frozen_confirmation()
    test_build_is_deterministic_report_only_and_future_data_hard_fails()
    print("run287_chameleon_macro_risk_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

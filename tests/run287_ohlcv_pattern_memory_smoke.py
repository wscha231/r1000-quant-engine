#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import archive_run287_ohlcv_pattern_memory as memory  # noqa: E402
from tools.build_run287_holding_risk_watch import sha256_file, write_json  # noqa: E402


def fingerprint(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_timing(
    root: Path,
    *,
    as_of_date: str,
    stock_close: float,
    stock_prior_return: float,
    stock_return: float,
    spy_close: float,
    spy_prior_return: float,
    spy_return: float,
    outcome_origin_date: str | None = None,
    outcome_basis_prices: dict[str, tuple[float, float]] | None = None,
    stock_data_reason: str = "",
    stock_transition_sessions_consecutive: bool = True,
) -> Path:
    source = root / f"timing_{as_of_date}"
    source.mkdir(parents=True)
    security = {
        "ticker": "AAA",
        "as_of_date": as_of_date,
        "close": stock_close,
        "prior_return_1d": stock_prior_return,
        "return_1d": stock_return,
        "return_2d": (1.0 + stock_prior_return) * (1.0 + stock_return) - 1.0,
        "return_transition_signature": memory_signature(
            stock_prior_return,
            stock_return,
        ),
        "return_transition_sessions_consecutive": (
            stock_transition_sessions_consecutive
        ),
        "return_transition_data_reason": (
            ""
            if stock_transition_sessions_consecutive
            else "nonconsecutive_nyse_sessions"
        ),
        "prior_down_current_up": stock_prior_return < 0.0 < stock_return,
        "range_21d_position": 0.21,
        "range_63d_position": 0.36,
        "range_126d_position": 0.52,
        "range_252d_position": 0.68,
        "data_reason": stock_data_reason,
        "is_held": True,
        "portfolios": "main",
        "shadow_action": "HOLD_REVIEW",
        "forward_outcome_status": "UNRESOLVED",
    }
    observations = source / "forward_observations.jsonl"
    observations.write_text(
        json.dumps(security, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    benchmark = source / "benchmark_location.csv"
    pd.DataFrame(
        [
            {
                "ticker": "SPY",
                "close": spy_close,
                "prior_return_1d": spy_prior_return,
                "return_1d": spy_return,
                "return_2d": (1.0 + spy_prior_return) * (1.0 + spy_return)
                - 1.0,
                "return_transition_signature": memory_signature(
                    spy_prior_return,
                    spy_return,
                ),
                "data_reason": "",
            },
            {
                "ticker": "QQQ",
                "close": spy_close * 0.9,
                "prior_return_1d": -0.02,
                "return_1d": -0.01,
                "return_2d": (1.0 - 0.02) * (1.0 - 0.01) - 1.0,
                "return_transition_signature": "CONTINUED_DOWN",
                "data_reason": "",
            },
        ]
    ).to_csv(benchmark, index=False)
    endpoint_path = source / "forward_outcome_endpoints.jsonl"
    endpoint_rows: list[dict[str, object]] = []
    if outcome_origin_date and outcome_basis_prices:
        contract_sha256 = sha256_file(
            ROOT / "docs" / "run287_ohlcv_pattern_memory_contract.json"
        )
        for source_kind, ticker in (
            ("SECURITY", "AAA"),
            ("BENCHMARK", "SPY"),
            ("BENCHMARK", "QQQ"),
        ):
            origin_close, target_close = outcome_basis_prices[ticker]
            observation_event_id = memory.canonical_hash(
                {
                    "schema_version": memory.OBSERVATION_SCHEMA_VERSION,
                    "source_kind": source_kind,
                    "ticker": ticker,
                    "as_of_date": outcome_origin_date,
                    "memory_contract_sha256": contract_sha256,
                }
            )
            endpoint = {
                "schema_version": (
                    "run287-ohlcv-forward-outcome-endpoint-v1"
                ),
                "observation_event_id": observation_event_id,
                "source_kind": source_kind,
                "ticker": ticker,
                "origin_session_date": outcome_origin_date,
                "target_session_date": as_of_date,
                "horizon_nyse_sessions": 1,
                "pattern_signature": (
                    "DOWN_TO_UP_REVERSAL"
                    if ticker != "QQQ"
                    else "CONTINUED_DOWN"
                ),
                "origin_close_on_target_adjustment_basis": origin_close,
                "target_close_on_target_adjustment_basis": target_close,
                "adjustment_basis_as_of": as_of_date,
                "adjustment_basis_policy": (
                    "both_endpoints_from_target_session_hash_verified_"
                    "adjusted_history"
                ),
                "data_reason": "",
                "exact_target_session": True,
                "research_only": True,
                "portfolio_transition_allowed": False,
                "orders_generated": False,
                "target_books_mutated": False,
            }
            endpoint["endpoint_id"] = memory.canonical_hash(
                {
                    "schema_version": endpoint["schema_version"],
                    "observation_event_id": observation_event_id,
                    "horizon_nyse_sessions": 1,
                    "target_session_date": as_of_date,
                }
            )
            endpoint_rows.append(endpoint)
    endpoint_path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in endpoint_rows
        ),
        encoding="utf-8",
    )
    summary = source / "summary.json"
    write_json(
        summary,
        {
            "schema_version": "run287-ohlcv-location-timing-challenger-v1",
            "status": "READY_OHLCV_LOCATION_TIMING_FORWARD_REVIEW_ONLY",
            "as_of_date": as_of_date,
            "available_from": f"{as_of_date}T20:00:00Z",
            "forward_observation_window": {
                "observation_accepted_at_utc": f"{as_of_date}T21:00:00Z"
            },
            "portfolio_transition_allowed": False,
            "orders_generated": False,
            "target_books_mutated": False,
            "selector_weights_changed": False,
            "cash_policy_changed": False,
            "champion_changed": False,
            "backtest_executed": False,
            "fullrun_executed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
            "outputs": {
                "forward_observations": fingerprint(observations),
                "benchmark_location": fingerprint(benchmark),
                "forward_outcome_endpoints": fingerprint(endpoint_path),
            },
        },
    )
    return summary


def memory_signature(prior: float, current: float) -> str:
    if prior < 0.0 < current:
        return "DOWN_TO_UP_REVERSAL"
    if prior > 0.0 > current:
        return "UP_TO_DOWN_REVERSAL"
    if prior < 0.0 and current < 0.0:
        return "CONTINUED_DOWN"
    if prior > 0.0 and current > 0.0:
        return "CONTINUED_UP"
    return "FLAT_OR_INSUFFICIENT"


def args_for(summary: Path, archive: Path, date: str) -> argparse.Namespace:
    return argparse.Namespace(
        timing_summary=str(summary),
        contract=str(
            ROOT / "docs" / "run287_ohlcv_pattern_memory_contract.json"
        ),
        valuation_date=date,
        output_dir=str(archive),
    )


def persist_timing_evidence(
    summary: Path,
    archive: Path,
    date: str,
) -> tuple[Path, Path]:
    payload = memory.read_json(summary)
    observations, observations_audit = memory.resolve_output(
        summary,
        payload,
        "forward_observations",
    )
    benchmark, benchmark_audit = memory.resolve_output(
        summary,
        payload,
        "benchmark_location",
    )
    endpoints, endpoints_audit = memory.resolve_output(
        summary,
        payload,
        "forward_outcome_endpoints",
    )
    return memory.persist_recovery_evidence(
        memory_dir=archive,
        valuation_date=date,
        contract_sha256=memory.sha256_file(
            ROOT / "docs" / "run287_ohlcv_pattern_memory_contract.json"
        ),
        source_paths={
            "timing_summary": summary,
            "timing_observations": observations,
            "timing_benchmark": benchmark,
            "timing_outcome_endpoints": endpoints,
        },
        sources={
            "timing_summary": memory.fingerprint(summary),
            "timing_observations": observations_audit,
            "timing_benchmark": benchmark_audit,
            "timing_outcome_endpoints": endpoints_audit,
        },
    )


def main() -> None:
    assert memory.sha256_file(
        ROOT / "docs" / "run287_ohlcv_pattern_memory_contract.json"
    ) == memory.PINNED_CONTRACT_SHA256
    with tempfile.TemporaryDirectory() as tmp:
        prefix_path = Path(tmp) / "prefixes.bin"
        prefix_path.write_bytes(b"abcdef")
        prefix_hashes = memory.sha256_prefixes(
            prefix_path,
            [6, 0, 3, 3],
        )
        assert prefix_hashes == {
            0: memory.hashlib.sha256(b"").hexdigest(),
            3: memory.hashlib.sha256(b"abc").hexdigest(),
            6: memory.hashlib.sha256(b"abcdef").hexdigest(),
        }
    try:
        memory.expected_forward_sessions("2026-07-29", "2026-07-28")
    except ValueError as exc:
        assert "precedes forward launch" in str(exc)
    else:
        raise AssertionError("pre-launch pattern session was accepted")

    sessions = [
        pd.Timestamp(value).date().isoformat()
        for value in memory.mcal.get_calendar("NYSE")
        .schedule(start_date="2026-01-02", end_date="2026-03-31")
        .index[:30]
    ]
    synthetic_observations = [
        {
            "event_id": f"observation-{index}",
            "source_kind": "SECURITY",
            "ticker": f"T{index:02d}",
            "as_of_date": session,
            "observed_close": 100.0,
            "return_transition_signature": "DOWN_TO_UP_REVERSAL",
        }
        for index, session in enumerate(sessions)
    ]
    synthetic_outcomes = [
        {
            "observation_event_id": f"observation-{index}",
            "source_kind": "SECURITY",
            "pattern_signature": "DOWN_TO_UP_REVERSAL",
            "horizon_nyse_sessions": 1,
            "forward_return": 0.01,
            "excess_return_vs_spy": 0.0,
        }
        for index in range(29)
    ]
    censored = memory.aggregate_outcomes(
        synthetic_observations,
        synthetic_outcomes,
        30,
        1.0,
        "2026-04-01",
        [1],
    )[0]
    assert censored["matured_observation_count"] == 30
    assert censored["resolved_observation_count"] == 29
    assert censored["missing_exact_outcome_count"] == 1
    assert censored["directional_statistics_published"] is False
    synthetic_outcomes.append(
        {
            "observation_event_id": "observation-29",
            "source_kind": "SECURITY",
            "pattern_signature": "DOWN_TO_UP_REVERSAL",
            "horizon_nyse_sessions": 1,
            "forward_return": 0.01,
            "excess_return_vs_spy": 0.0,
        }
    )
    complete = memory.aggregate_outcomes(
        synthetic_observations,
        synthetic_outcomes,
        30,
        1.0,
        "2026-04-01",
        [1],
    )[0]
    assert complete["resolution_coverage"] == 1.0
    assert complete["directional_statistics_published"] is True
    gap_suppressed = memory.aggregate_outcomes(
        synthetic_observations,
        synthetic_outcomes,
        30,
        1.0,
        "2026-04-01",
        [1],
        session_coverage_complete=False,
    )[0]
    assert gap_suppressed["resolution_coverage"] == 1.0
    assert gap_suppressed["session_coverage_complete"] is False
    assert gap_suppressed["directional_statistics_published"] is False
    close_missing_observation = {
        "event_id": "observation-close-missing",
        "source_kind": "SECURITY",
        "ticker": "MISSING",
        "as_of_date": "2026-04-01",
        "observed_close": None,
        "data_ready": False,
        "return_transition_signature": "DOWN_TO_UP_REVERSAL",
    }
    close_missing = memory.aggregate_outcomes(
        [*synthetic_observations, close_missing_observation],
        synthetic_outcomes,
        30,
        1.0,
        "2026-04-02",
        [1],
        observation_data_coverage_complete=False,
    )[0]
    assert close_missing["matured_observation_count"] == 31
    assert close_missing["resolved_observation_count"] == 30
    assert close_missing["missing_exact_outcome_count"] == 1
    assert close_missing["observation_data_coverage_complete"] is False
    assert close_missing["directional_statistics_published"] is False
    assert memory.has_powered_security_evidence(
        [
            {
                "source_kind": "BENCHMARK",
                "directional_statistics_published": True,
            }
        ]
    ) is False
    assert memory.has_powered_security_evidence(
        [
            {
                "source_kind": "SECURITY",
                "directional_statistics_published": True,
            }
        ]
    ) is True

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        archive = root / "archive" / "ohlcv_pattern_memory"
        prelaunch_summary = write_timing(
            root,
            as_of_date="2026-07-28",
            stock_close=95.0,
            stock_prior_return=-0.01,
            stock_return=0.01,
            spy_close=498.0,
            spy_prior_return=-0.01,
            spy_return=0.01,
        )
        prelaunch = memory.build(
            args_for(prelaunch_summary, archive, "2026-07-28")
        )
        assert prelaunch["status"] == memory.BLOCKED_STATUS
        assert "precedes forward launch" in " ".join(
            prelaunch["contract_failures"]
        )
        assert not (archive / "observations.jsonl").exists()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        archive = root / "archive" / "ohlcv_pattern_memory"
        nonconsecutive_summary = write_timing(
            root,
            as_of_date="2026-07-29",
            stock_close=96.0,
            stock_prior_return=-0.04,
            stock_return=0.06,
            spy_close=500.0,
            spy_prior_return=-0.02,
            spy_return=0.03,
            stock_transition_sessions_consecutive=False,
        )
        nonconsecutive = memory.build(
            args_for(nonconsecutive_summary, archive, "2026-07-29")
        )
        assert nonconsecutive["status"] == memory.READY_STATUS, nonconsecutive
        security_observation = next(
            row
            for row in memory.read_jsonl(archive / "observations.jsonl")
            if row["source_kind"] == "SECURITY"
        )
        assert security_observation["data_ready"] is False
        assert (
            security_observation[
                "return_transition_sessions_consecutive"
            ]
            is False
        )
        assert nonconsecutive["observation_data_coverage_complete"] is False
        assert nonconsecutive["proposal_eligible"] is False

    # A hard stop can leave a fully written descendant manifest while the
    # atomic accepted pointer still names its parent. The pointer remains the
    # sole commit marker: the descendant events are an exact-session suffix
    # until a retry publishes that already validated manifest.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        archive = root / "archive" / "ohlcv_pattern_memory"
        first_summary = write_timing(
            root,
            as_of_date="2026-07-29",
            stock_close=96.0,
            stock_prior_return=-0.04,
            stock_return=0.06,
            spy_close=500.0,
            spy_prior_return=-0.02,
            spy_return=0.03,
        )
        first = memory.build(
            args_for(first_summary, archive, "2026-07-29")
        )
        assert first["status"] == memory.READY_STATUS, first
        committed_head_id = first["accepted_head_id"]
        second_summary = write_timing(
            root,
            as_of_date="2026-07-30",
            stock_close=100.0,
            stock_prior_return=0.06,
            stock_return=-0.02,
            spy_close=505.0,
            spy_prior_return=0.03,
            spy_return=0.01,
        )
        original_atomic_write_json = memory.atomic_write_json

        def hard_stop_before_pointer(
            path: Path,
            payload: dict[str, object],
        ) -> None:
            if path == archive / "accepted_head.json":
                raise KeyboardInterrupt(
                    "simulated process stop before accepted pointer commit"
                )
            original_atomic_write_json(path, payload)

        memory.atomic_write_json = hard_stop_before_pointer
        try:
            try:
                memory.build(
                    args_for(second_summary, archive, "2026-07-30")
                )
            except KeyboardInterrupt:
                pass
            else:
                raise AssertionError("hard-stop simulation did not interrupt")
        finally:
            memory.atomic_write_json = original_atomic_write_json

        assert memory.read_json(archive / "accepted_head.json")[
            "head_id"
        ] == committed_head_id
        assert len(
            list((archive / "accepted_heads").glob("*/manifest.json"))
        ) == 2
        observations = memory.read_jsonl(archive / "observations.jsonl")
        outcomes = memory.read_jsonl(archive / "outcomes.jsonl")
        durable = memory.validate_accepted_head_state(
            memory_dir=archive,
            observations=observations,
            outcomes=outcomes,
            contract_sha256=memory.PINNED_CONTRACT_SHA256,
            allow_unaccepted_events=True,
        )
        assert durable["head_id"] == committed_head_id
        assert durable["pointer_repair_required"] is True
        assert durable["uncommitted_descendant_manifest_count"] == 1
        assert memory.required_unaccepted_retry_session(
            observations=observations,
            outcomes=outcomes,
            durable_head=durable,
        ) == "2026-07-30"
        resumed = memory.build(
            args_for(second_summary, archive, "2026-07-30")
        )
        assert resumed["status"] == memory.READY_STATUS, resumed
        assert resumed["accepted_head_id"] != committed_head_id
        assert memory.read_json(archive / "accepted_head.json")[
            "head_id"
        ] == resumed["accepted_head_id"]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        archive = root / "archive" / "ohlcv_pattern_memory"
        first_summary = write_timing(
            root,
            as_of_date="2026-07-29",
            stock_close=96.0,
            stock_prior_return=-0.04,
            stock_return=0.06,
            spy_close=500.0,
            spy_prior_return=-0.02,
            spy_return=0.03,
        )
        first = memory.build(args_for(first_summary, archive, "2026-07-29"))
        assert first["status"] == memory.READY_STATUS, first
        assert first["appended_observation_count"] == 3
        assert first["resolved_outcome_event_count"] == 0
        assert first["proposal_eligible"] is False
        assert first["session_coverage_complete"] is True
        assert first["missing_session_dates"] == []
        assert first["observation_data_coverage_complete"] is True
        assert first["missing_origin_observation_count"] == 0
        assert first["accepted_head_id"]
        assert (archive / "accepted_head.json").is_file()
        assert len(list((archive / "accepted_heads").glob("*/manifest.json"))) == 1
        published_first = memory.read_json(archive / "summary.json")
        for key in ("accepted_head", "accepted_head_manifest"):
            record = published_first["outputs"][key]
            actual = memory.fingerprint(Path(record["path"]))
            assert actual["sha256"] == record["sha256"]
            assert actual["bytes"] == record["bytes"]
        report_record = published_first["outputs"]["report"]
        actual_report = memory.fingerprint(archive / "report.md")
        assert actual_report["sha256"] == report_record["sha256"]
        assert actual_report["bytes"] == report_record["bytes"]
        first_security_observation = next(
            row
            for row in memory.read_jsonl(archive / "observations.jsonl")
            if row["source_kind"] == "SECURITY"
        )
        assert first_security_observation["range_21d_position"] == 0.21
        assert first_security_observation["range_63d_position"] == 0.36
        assert first_security_observation["range_126d_position"] == 0.52
        assert first_security_observation["range_252d_position"] == 0.68

        torn_archive = root / "torn_archive" / "ohlcv_pattern_memory"
        shutil.copytree(archive, torn_archive)
        torn_observations = torn_archive / "observations.jsonl"
        accepted_observation_bytes = torn_observations.read_bytes()
        with torn_observations.open("ab") as handle:
            handle.write(b'{"schema_version":"torn')
        repaired_tail = memory.build(
            args_for(first_summary, torn_archive, "2026-07-29")
        )
        assert repaired_tail["status"] == memory.READY_STATUS, repaired_tail
        assert torn_observations.read_bytes() == accepted_observation_bytes
        repair_audit = repaired_tail["source_inputs"][
            "unaccepted_jsonl_tail_repair"
        ]
        assert repair_audit["status"] == (
            "REPAIRED_MALFORMED_UNACCEPTED_TAIL"
        )
        assert repair_audit["repairs"][0][
            "discarded_unaccepted_tail_bytes"
        ] > 0

        report_loss_archive = (
            root / "report_loss_archive" / "ohlcv_pattern_memory"
        )
        shutil.copytree(archive, report_loss_archive)
        (report_loss_archive / "report.md").unlink()
        report_loss = memory.record_failed_session(
            argparse.Namespace(
                output_dir=str(report_loss_archive),
                contract=str(
                    ROOT
                    / "docs"
                    / "run287_ohlcv_pattern_memory_contract.json"
                ),
                valuation_date="2026-07-30",
                record_failed_session_reason="current_session_pending",
            )
        )
        assert report_loss["record_mode_must_stop"] is True
        assert report_loss["stale_public_marker_replaced"] is True
        assert report_loss["required_publication_retry_session"] == (
            "2026-07-29"
        )
        assert memory.process_exit_code(
            report_loss,
            record_mode=True,
        ) == 2
        report_loss_public = memory.read_json(
            report_loss_archive / "summary.json"
        )
        assert report_loss_public["status"] == memory.BLOCKED_STATUS
        assert report_loss_public["failed_session_date"] == "2026-07-29"

        repeated = memory.build(args_for(first_summary, archive, "2026-07-29"))
        assert repeated["status"] == memory.READY_STATUS, repeated
        assert repeated["appended_observation_count"] == 0
        assert repeated["appended_outcome_count"] == 0
        assert repeated["accepted_head_id"] == first["accepted_head_id"]

        first_payload = json.loads(
            first_summary.read_text(encoding="utf-8")
        )
        first_observation_path = Path(
            first_payload["outputs"]["forward_observations"]["path"]
        )
        regenerated_rows = memory.read_jsonl(first_observation_path)
        for row in regenerated_rows:
            row["available_from"] = "2026-07-29T20:05:00Z"
            row["observation_accepted_at_utc"] = "2026-07-29T21:10:00Z"
        first_observation_path.write_text(
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in regenerated_rows
            ),
            encoding="utf-8",
        )
        first_payload["available_from"] = "2026-07-29T20:05:00Z"
        first_payload["forward_observation_window"][
            "observation_accepted_at_utc"
        ] = "2026-07-29T21:10:00Z"
        first_payload["outputs"]["forward_observations"] = fingerprint(
            first_observation_path
        )
        write_json(first_summary, first_payload)
        regenerated = memory.build(
            args_for(first_summary, archive, "2026-07-29")
        )
        assert regenerated["status"] == memory.READY_STATUS, regenerated
        assert regenerated["appended_observation_count"] == 0
        assert regenerated["accepted_head_id"] == first["accepted_head_id"]

        accepted_source_bytes = first_observation_path.read_bytes()
        accepted_source_payload = json.loads(
            first_summary.read_text(encoding="utf-8")
        )
        extra_security = {
            **regenerated_rows[0],
            "ticker": "CCC",
            "close": 77.0,
        }
        first_observation_path.write_text(
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in [*regenerated_rows, extra_security]
            ),
            encoding="utf-8",
        )
        changed_cohort_payload = {
            **accepted_source_payload,
            "outputs": {
                **accepted_source_payload["outputs"],
                "forward_observations": fingerprint(
                    first_observation_path
                ),
            },
        }
        write_json(first_summary, changed_cohort_payload)
        changed_cohort = memory.build(
            args_for(first_summary, archive, "2026-07-29")
        )
        assert changed_cohort["status"] == memory.BLOCKED_STATUS
        assert "accepted observation session cohort changed" in " ".join(
            changed_cohort["contract_failures"]
        )
        first_observation_path.write_bytes(accepted_source_bytes)
        accepted_source_payload["outputs"][
            "forward_observations"
        ] = fingerprint(first_observation_path)
        write_json(first_summary, accepted_source_payload)
        refinalized = memory.build(
            args_for(first_summary, archive, "2026-07-29")
        )
        assert refinalized["status"] == memory.READY_STATUS, refinalized
        assert refinalized["appended_observation_count"] == 0

        second_summary = write_timing(
            root,
            as_of_date="2026-07-30",
            stock_close=100.0,
            stock_prior_return=0.06,
            stock_return=-0.02,
            spy_close=505.0,
            spy_prior_return=0.03,
            spy_return=0.01,
            outcome_origin_date="2026-07-29",
            outcome_basis_prices={
                "AAA": (96.0, 100.0),
                "SPY": (500.0, 505.0),
                "QQQ": (450.0, 454.5),
            },
        )
        second = memory.build(args_for(second_summary, archive, "2026-07-30"))
        assert second["status"] == memory.READY_STATUS, second
        assert second["appended_observation_count"] == 3
        assert second["appended_outcome_count"] == 3
        assert second["resolved_outcome_event_count"] == 3
        assert len(list((archive / "accepted_heads").glob("*/manifest.json"))) == 2
        security_aggregate = next(
            row
            for row in second["aggregates"]
            if row["source_kind"] == "SECURITY"
            and row["pattern_signature"] == "DOWN_TO_UP_REVERSAL"
            and row["horizon_nyse_sessions"] == 1
        )
        assert security_aggregate["resolved_observation_count"] == 1
        assert security_aggregate["matured_observation_count"] == 1
        assert security_aggregate["missing_exact_outcome_count"] == 0
        assert security_aggregate["resolution_coverage"] == 1.0
        assert security_aggregate["underpowered"] is True
        assert security_aggregate["directional_statistics_published"] is False
        assert "directional_statistics" not in security_aggregate

        observations = memory.read_jsonl(archive / "observations.jsonl")
        outcomes = memory.read_jsonl(archive / "outcomes.jsonl")
        assert len(observations) == 6
        assert len(outcomes) == 3
        stock_outcome = next(
            row for row in outcomes if row["source_kind"] == "SECURITY"
        )
        assert abs(stock_outcome["forward_return"] - (100.0 / 96.0 - 1.0)) < 1e-12
        assert stock_outcome["target_session_date"] == "2026-07-30"
        assert stock_outcome["resolution_policy"] == (
            "EXACT_ARCHIVED_NYSE_TARGET_SESSION_ONLY"
        )
        assert stock_outcome["adjustment_basis_as_of"] == "2026-07-30"
        assert stock_outcome["source_summary_sha256"] == (
            memory.sha256_file(second_summary)
        )

        accepted_second_payload = json.loads(
            second_summary.read_text(encoding="utf-8")
        )
        accepted_endpoint_path = Path(
            accepted_second_payload["outputs"][
                "forward_outcome_endpoints"
            ]["path"]
        )
        accepted_endpoint_bytes = accepted_endpoint_path.read_bytes()
        changed_endpoint_rows = memory.read_jsonl(accepted_endpoint_path)
        for row in changed_endpoint_rows:
            if row["source_kind"] == "SECURITY":
                row["target_close_on_target_adjustment_basis"] = 101.0
        accepted_endpoint_path.write_text(
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in changed_endpoint_rows
            ),
            encoding="utf-8",
        )
        changed_endpoint_payload = {
            **accepted_second_payload,
            "outputs": {
                **accepted_second_payload["outputs"],
                "forward_outcome_endpoints": fingerprint(
                    accepted_endpoint_path
                ),
            },
        }
        write_json(second_summary, changed_endpoint_payload)
        changed_outcome_retry = memory.build(
            args_for(second_summary, archive, "2026-07-30")
        )
        assert changed_outcome_retry["status"] == memory.BLOCKED_STATUS
        assert "same identity payload changed" in " ".join(
            changed_outcome_retry["contract_failures"]
        )
        accepted_endpoint_path.write_bytes(accepted_endpoint_bytes)
        accepted_second_payload["outputs"][
            "forward_outcome_endpoints"
        ] = fingerprint(accepted_endpoint_path)
        write_json(second_summary, accepted_second_payload)

        frozen_observation_bytes = (
            archive / "observations.jsonl"
        ).read_bytes()
        (archive / "observations.jsonl").write_text(
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in observations[:3]
            ),
            encoding="utf-8",
        )
        rolled_back = memory.build(
            args_for(second_summary, archive, "2026-07-30")
        )
        assert rolled_back["status"] == memory.BLOCKED_STATUS
        assert "accepted JSONL prefix truncated" in " ".join(
            rolled_back["contract_failures"]
        ), rolled_back["contract_failures"]
        (archive / "observations.jsonl").write_bytes(
            frozen_observation_bytes
        )
        refinalized_second = memory.build(
            args_for(second_summary, archive, "2026-07-30")
        )
        assert (
            refinalized_second["status"] == memory.READY_STATUS
        ), refinalized_second
        assert refinalized_second["appended_observation_count"] == 0

        out_of_order = memory.build(
            args_for(first_summary, archive, "2026-07-29")
        )
        assert out_of_order["status"] == memory.BLOCKED_STATUS
        assert "out-of-order observation" in " ".join(
            out_of_order["contract_failures"]
        )
        assert len(memory.read_jsonl(archive / "observations.jsonl")) == 6

        second_payload = json.loads(
            second_summary.read_text(encoding="utf-8")
        )
        source_observations = Path(
            second_payload["outputs"]["forward_observations"]["path"]
        )
        source_observations.write_text(
            source_observations.read_text(encoding="utf-8").replace(
                '"close":100.0',
                '"close":101.0',
            ),
            encoding="utf-8",
        )
        changed = memory.build(
            args_for(second_summary, archive, "2026-07-30")
        )
        assert changed["status"] == memory.BLOCKED_STATUS
        assert "fingerprint mismatch" in " ".join(changed["contract_failures"])
        assert len(memory.read_jsonl(archive / "observations.jsonl")) == 6

    # A report failure may occur after the append-only observation commit.
    # The next invocation resumes by event identity without duplicating rows.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        archive = root / "archive" / "ohlcv_pattern_memory"
        summary = write_timing(
            root,
            as_of_date="2026-07-29",
            stock_close=96.0,
            stock_prior_return=-0.04,
            stock_return=0.06,
            spy_close=500.0,
            spy_prior_return=-0.02,
            spy_return=0.03,
        )
        original_atomic_write_text = memory.atomic_write_text

        def fail_report(path: Path, text: str) -> None:
            if path.name == "report.md":
                raise OSError("simulated report failure")
            original_atomic_write_text(path, text)

        memory.atomic_write_text = fail_report
        try:
            interrupted = memory.build(
                args_for(summary, archive, "2026-07-29")
            )
        finally:
            memory.atomic_write_text = original_atomic_write_text
        assert interrupted["status"] == memory.BLOCKED_STATUS
        interrupted_marker = memory.read_json(archive / "summary.json")
        assert interrupted_marker["status"] == memory.BLOCKED_STATUS
        assert interrupted_marker["proposal_eligible"] is False
        assert not (archive / "report.md").exists()
        assert not (archive / "accepted_head.json").exists()
        assert not (archive / "accepted_heads").exists()
        assert len(memory.read_jsonl(archive / "observations.jsonl")) == 3
        recovery_summaries = list(
            (
                archive / "recovery_evidence" / "20260729"
            ).glob("*/summary.json")
        )
        assert len(recovery_summaries) == 1
        next_summary = write_timing(
            root,
            as_of_date="2026-07-30",
            stock_close=100.0,
            stock_prior_return=0.06,
            stock_return=-0.02,
            spy_close=505.0,
            spy_prior_return=0.03,
            spy_return=0.01,
            outcome_origin_date="2026-07-29",
            outcome_basis_prices={
                "AAA": (96.0, 100.0),
                "SPY": (500.0, 505.0),
                "QQQ": (450.0, 454.5),
            },
        )
        advanced = memory.build(
            args_for(next_summary, archive, "2026-07-30")
        )
        assert advanced["status"] == memory.BLOCKED_STATUS
        assert "requires exact retry:2026-07-29!=2026-07-30" in " ".join(
            advanced["contract_failures"]
        )
        assert len(memory.read_jsonl(archive / "observations.jsonl")) == 3
        assert not (archive / "accepted_head.json").exists()
        decoy_summary = write_timing(
            root / "decoy",
            as_of_date="2026-07-29",
            stock_close=95.0,
            stock_prior_return=-0.03,
            stock_return=0.04,
            spy_close=499.0,
            spy_prior_return=-0.01,
            spy_return=0.02,
        )
        contract_sha256 = memory.sha256_file(
            ROOT / "docs" / "run287_ohlcv_pattern_memory_contract.json"
        )
        persist_timing_evidence(
            decoy_summary,
            archive,
            "2026-07-29",
        )
        all_recovery_summaries = list(
            (
                archive / "recovery_evidence" / "20260729"
            ).glob("*/summary.json")
        )
        assert len(all_recovery_summaries) == 2
        suffix_rows = memory.read_jsonl(archive / "observations.jsonl")
        expected_summary_hashes = {
            str(row.get("source_summary_sha256") or "")
            for row in suffix_rows
            if row.get("as_of_date") == "2026-07-29"
        }
        assert len(expected_summary_hashes) == 1
        selected_recovery_summary = (
            memory.select_recovery_evidence_summary(
                memory_dir=archive,
                session_date="2026-07-29",
                expected_summary_sha256=next(
                    iter(expected_summary_hashes)
                ),
                contract_sha256=contract_sha256,
            )
        )
        assert selected_recovery_summary == recovery_summaries[0]
        required_observation_payload_hashes = {
            memory.canonical_hash(
                memory.event_comparison_payload(row)
            )
            for row in suffix_rows
            if row.get("as_of_date") == "2026-07-29"
        }
        selected_by_complete_observation_suffix = (
            memory.select_recovery_evidence_summary(
                memory_dir=archive,
                session_date="2026-07-29",
                accepted_summary_sha256s={
                    memory.sha256_file(recovery_summaries[0]),
                    memory.sha256_file(decoy_summary),
                },
                required_observation_payload_sha256s=(
                    required_observation_payload_hashes
                ),
                contract_sha256=contract_sha256,
            )
        )
        assert (
            selected_by_complete_observation_suffix
            == recovery_summaries[0]
        )

        # The immediately preceding schema did not put source-summary
        # provenance on outcome rows. An outcome-only suffix must recover from
        # its exact endpoint payload hashes, not remain permanently blocked.
        legacy_summary, _ = persist_timing_evidence(
            next_summary,
            archive,
            "2026-07-30",
        )
        legacy_decoy = write_timing(
            root / "legacy_decoy",
            as_of_date="2026-07-30",
            stock_close=101.0,
            stock_prior_return=0.06,
            stock_return=-0.01,
            spy_close=506.0,
            spy_prior_return=0.03,
            spy_return=0.012,
            outcome_origin_date="2026-07-29",
            outcome_basis_prices={
                "AAA": (96.0, 101.0),
                "SPY": (500.0, 506.0),
                "QQQ": (450.0, 455.4),
            },
        )
        persist_timing_evidence(
            legacy_decoy,
            archive,
            "2026-07-30",
        )
        legacy_equivalent = write_timing(
            root / "legacy_equivalent",
            as_of_date="2026-07-30",
            stock_close=100.0,
            stock_prior_return=0.06,
            stock_return=-0.02,
            spy_close=505.0,
            spy_prior_return=0.03,
            spy_return=0.01,
            outcome_origin_date="2026-07-29",
            outcome_basis_prices={
                "AAA": (96.0, 100.0),
                "SPY": (500.0, 505.0),
                "QQQ": (450.0, 454.5),
            },
        )
        legacy_equivalent_summary, _ = persist_timing_evidence(
            legacy_equivalent,
            archive,
            "2026-07-30",
        )
        next_payload = memory.read_json(next_summary)
        next_endpoint_path, _ = memory.resolve_output(
            next_summary,
            next_payload,
            "forward_outcome_endpoints",
        )
        required_legacy_endpoint_hashes = {
            memory.canonical_hash(row)
            for row in memory.read_jsonl(next_endpoint_path)
        }
        selected_legacy_summary = (
            memory.select_recovery_evidence_summary(
                memory_dir=archive,
                session_date="2026-07-30",
                expected_summary_sha256="",
                required_endpoint_payload_sha256s=(
                    required_legacy_endpoint_hashes
                ),
                contract_sha256=contract_sha256,
            )
        )
        assert selected_legacy_summary == sorted(
            [legacy_summary, legacy_equivalent_summary]
        )[0]
        # A delayed runner may no longer have the original timing directory.
        # Recovery must therefore reuse the exact preserved summary bytes and
        # hash-validated sibling outputs without generating a new timestamp.
        for source_file in summary.parent.iterdir():
            source_file.unlink()
        summary.parent.rmdir()
        blocked_summary_bytes = (archive / "summary.json").read_bytes()
        blocked_report_bytes = (archive / "report.md").read_bytes()
        blocked_last_attempt_bytes = (
            archive / "last_attempt.json"
        ).read_bytes()
        deferred_args = args_for(
            selected_recovery_summary,
            archive,
            "2026-07-29",
        )
        deferred_args.preserve_blocked_publication = True
        deferred_args.pending_session_date = "2026-07-30"
        for staged_report in (
            archive / "deferred_reports" / "20260729"
        ).glob("*.md"):
            staged_report.unlink()
        original_atomic_write_text = memory.atomic_write_text

        def fail_deferred_report(path: Path, text: str) -> None:
            if "deferred_reports" in path.parts:
                raise OSError("simulated deferred report failure")
            original_atomic_write_text(path, text)

        memory.atomic_write_text = fail_deferred_report
        try:
            deferred_failure = memory.build(deferred_args)
        finally:
            memory.atomic_write_text = original_atomic_write_text
        assert (
            deferred_failure["status"] == memory.BLOCKED_STATUS
        ), deferred_failure
        assert deferred_failure["public_blocked_marker_preserved"] is True
        assert (archive / "summary.json").read_bytes() == blocked_summary_bytes
        assert (archive / "report.md").read_bytes() == blocked_report_bytes
        assert (
            archive / "last_attempt.json"
        ).read_bytes() == blocked_last_attempt_bytes
        assert not (archive / "accepted_head.json").exists()

        deferred = memory.build(deferred_args)
        assert deferred["status"] == memory.READY_STATUS, deferred
        assert deferred["publication_deferred"] is True
        assert deferred["appended_observation_count"] == 0
        assert (archive / "summary.json").read_bytes() == blocked_summary_bytes
        still_blocked = memory.read_json(archive / "summary.json")
        assert still_blocked["status"] == memory.BLOCKED_STATUS
        assert still_blocked["failed_session_date"] == "2026-07-30"
        assert still_blocked["proposal_eligible"] is False
        assert not (archive / "accepted_head.json").exists()

        # The post-ledger D recovery may commit its durable head while D+1's
        # public BLOCKED marker remains byte-identical. It must then reject a
        # jump to D+2 instead of making D+1 impossible to backfill.
        commit_archive = root / "commit_preserving_public_block"
        shutil.copytree(archive, commit_archive)
        commit_summary = commit_archive / selected_recovery_summary.relative_to(
            archive
        )
        commit_args = args_for(
            commit_summary,
            commit_archive,
            "2026-07-29",
        )
        commit_args.commit_head_preserve_blocked_publication = True
        commit_args.pending_session_date = "2026-07-30"
        committed = memory.build(commit_args)
        assert committed["status"] == memory.READY_STATUS, committed
        assert committed["accepted_head_committed"] is True
        assert committed["public_blocked_marker_preserved"] is True
        assert (commit_archive / "accepted_head.json").is_file()
        assert (
            commit_archive / "summary.json"
        ).read_bytes() == blocked_summary_bytes
        assert (
            commit_archive / "report.md"
        ).read_bytes() == blocked_report_bytes
        assert (
            commit_archive / "last_attempt.json"
        ).read_bytes() == blocked_last_attempt_bytes
        committed_head_id = memory.read_json(
            commit_archive / "accepted_head.json"
        )["head_id"]
        leap_summary = write_timing(
            root / "leap",
            as_of_date="2026-07-31",
            stock_close=101.0,
            stock_prior_return=-0.01,
            stock_return=0.02,
            spy_close=506.0,
            spy_prior_return=-0.01,
            spy_return=0.01,
        )
        leap = memory.build(
            args_for(leap_summary, commit_archive, "2026-07-31")
        )
        assert leap["status"] == memory.BLOCKED_STATUS
        assert (
            "requires chronological session:2026-07-30!=2026-07-31"
            in " ".join(leap["contract_failures"])
        )
        assert memory.read_json(commit_archive / "accepted_head.json")[
            "head_id"
        ] == committed_head_id

        # A hard stop while publishing the final READY summary occurs only
        # after the accepted pointer and report are durable. The earlier
        # publication-pending marker must therefore remain BLOCKED.
        original_atomic_write_json = memory.atomic_write_json
        interrupted_ready_summary_once = False

        def interrupt_ready_summary_once(
            path: Path,
            payload: dict[str, object],
        ) -> None:
            nonlocal interrupted_ready_summary_once
            if (
                path.name == "summary.json"
                and payload.get("status") == memory.READY_STATUS
                and not interrupted_ready_summary_once
            ):
                interrupted_ready_summary_once = True
                raise KeyboardInterrupt("simulated hard stop before READY")
            original_atomic_write_json(path, payload)

        memory.atomic_write_json = interrupt_ready_summary_once
        try:
            try:
                memory.build(
                    args_for(
                        selected_recovery_summary,
                        archive,
                        "2026-07-29",
                    )
                )
            except KeyboardInterrupt:
                pass
            else:
                raise AssertionError("simulated hard stop did not fire")
        finally:
            memory.atomic_write_json = original_atomic_write_json
        interrupted_public = memory.read_json(archive / "summary.json")
        assert interrupted_public["status"] == memory.BLOCKED_STATUS
        assert interrupted_public["proposal_eligible"] is False
        assert interrupted_public["failed_session_date"] == "2026-07-29"
        assert (archive / "accepted_head.json").is_file()
        assert (archive / "accepted_heads").is_dir()
        pending_next_session = memory.record_failed_session(
            argparse.Namespace(
                output_dir=str(archive),
                contract=str(
                    ROOT
                    / "docs"
                    / "run287_ohlcv_pattern_memory_contract.json"
                ),
                valuation_date="2026-07-30",
                record_failed_session_reason="current_session_pending",
            )
        )
        assert pending_next_session["status"] == memory.BLOCKED_STATUS
        assert (
            pending_next_session["required_publication_retry_session"]
            == "2026-07-29"
        )
        assert pending_next_session["record_mode_must_stop"] is True
        assert memory.process_exit_code(
            pending_next_session,
            record_mode=True,
        ) == 2
        assert memory.read_json(archive / "summary.json") == (
            interrupted_public
        )
        premature_advance = memory.build(
            args_for(next_summary, archive, "2026-07-30")
        )
        assert premature_advance["status"] == memory.BLOCKED_STATUS
        assert premature_advance["public_blocked_marker_preserved"] is True
        assert premature_advance["required_publication_retry_session"] == (
            "2026-07-29"
        )
        assert (
            "accepted pattern head requires public finalization:"
            "2026-07-29!=2026-07-30"
            in " ".join(premature_advance["contract_failures"])
        )
        assert memory.read_json(archive / "summary.json") == (
            interrupted_public
        )

        # The exact-session retry finalizes the already committed head and is
        # the first point at which the public summary exposes READY.
        resumed = memory.build(
            args_for(selected_recovery_summary, archive, "2026-07-29")
        )
        assert resumed["status"] == memory.READY_STATUS, resumed
        assert resumed["appended_observation_count"] == 0
        assert len(memory.read_jsonl(archive / "observations.jsonl")) == 3
        accepted_manifest = memory.read_json(
            archive
            / "accepted_heads"
            / resumed["accepted_head_id"]
            / "manifest.json"
        )
        assert resumed["durable_parent_head_id"] == (
            accepted_manifest["parent_head_id"]
        )
        assert resumed["durable_parent_head_id"] != resumed["accepted_head_id"]

        rows = memory.read_jsonl(archive / "observations.jsonl")
        rows[0]["event_hash"] = "0" * 64
        (archive / "observations.jsonl").write_text(
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )
        tampered = memory.build(
            args_for(selected_recovery_summary, archive, "2026-07-29")
        )
        assert tampered["status"] == memory.BLOCKED_STATUS
        assert "accepted JSONL prefix hash mismatch" in " ".join(
            tampered["contract_failures"]
        )

    # When retry B supplies an endpoint missing from suffix attempt A, the new
    # outcome retains B's source identity. A second interruption then selects
    # B because it is the only bundle satisfying every summary and endpoint
    # provenance record in the suffix.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        archive = root / "archive" / "ohlcv_pattern_memory"
        first_summary = write_timing(
            root,
            as_of_date="2026-07-29",
            stock_close=96.0,
            stock_prior_return=-0.04,
            stock_return=0.06,
            spy_close=500.0,
            spy_prior_return=-0.02,
            spy_return=0.03,
        )
        first = memory.build(
            args_for(first_summary, archive, "2026-07-29")
        )
        assert first["status"] == memory.READY_STATUS, first

        partial_summary = write_timing(
            root,
            as_of_date="2026-07-30",
            stock_close=100.0,
            stock_prior_return=0.06,
            stock_return=-0.02,
            spy_close=505.0,
            spy_prior_return=0.03,
            spy_return=0.01,
            outcome_origin_date="2026-07-29",
            outcome_basis_prices={
                "AAA": (96.0, 100.0),
                "SPY": (500.0, 505.0),
                "QQQ": (450.0, 454.5),
            },
        )
        partial_payload = memory.read_json(partial_summary)
        partial_endpoint_path = Path(
            partial_payload["outputs"]["forward_outcome_endpoints"]["path"]
        )
        partial_endpoint_rows = [
            row
            for row in memory.read_jsonl(partial_endpoint_path)
            if row.get("ticker") != "AAA"
        ]
        partial_endpoint_path.write_text(
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":"))
                + "\n"
                for row in partial_endpoint_rows
            ),
            encoding="utf-8",
        )
        partial_payload["outputs"]["forward_outcome_endpoints"] = (
            fingerprint(partial_endpoint_path)
        )
        write_json(partial_summary, partial_payload)
        first_attempt_summary_sha256 = memory.sha256_file(partial_summary)
        original_atomic_write_text = memory.atomic_write_text

        def fail_partial_report(path: Path, text: str) -> None:
            if path.name == "report.md":
                raise OSError("simulated partial outcome report failure")
            original_atomic_write_text(path, text)

        memory.atomic_write_text = fail_partial_report
        try:
            partial = memory.build(
                args_for(partial_summary, archive, "2026-07-30")
            )
        finally:
            memory.atomic_write_text = original_atomic_write_text
        assert partial["status"] == memory.BLOCKED_STATUS
        assert len(memory.read_jsonl(archive / "outcomes.jsonl")) == 2

        retry_summary = write_timing(
            root / "retry",
            as_of_date="2026-07-30",
            stock_close=100.0,
            stock_prior_return=0.06,
            stock_return=-0.02,
            spy_close=505.0,
            spy_prior_return=0.03,
            spy_return=0.01,
            outcome_origin_date="2026-07-29",
            outcome_basis_prices={
                "AAA": (96.0, 100.0),
                "SPY": (500.0, 505.0),
                "QQQ": (450.0, 454.5),
            },
        )
        assert memory.sha256_file(retry_summary) != (
            first_attempt_summary_sha256
        )
        memory.atomic_write_text = fail_partial_report
        try:
            retry_interrupted = memory.build(
                args_for(retry_summary, archive, "2026-07-30")
            )
        finally:
            memory.atomic_write_text = original_atomic_write_text
        assert retry_interrupted["status"] == memory.BLOCKED_STATUS
        durable_head = memory.validate_accepted_head_state(
            memory_dir=archive,
            observations=memory.read_jsonl(archive / "observations.jsonl"),
            outcomes=memory.read_jsonl(archive / "outcomes.jsonl"),
            contract_sha256=memory.PINNED_CONTRACT_SHA256,
            allow_unaccepted_events=True,
        )
        observation_count = int(durable_head["observation_event_count"])
        outcome_count = int(durable_head["resolved_outcome_event_count"])
        all_observations = memory.read_jsonl(archive / "observations.jsonl")
        all_outcomes = memory.read_jsonl(archive / "outcomes.jsonl")
        retry_summary_hashes = {
            str(row.get("source_summary_sha256") or "")
            for row in all_observations[observation_count:]
        }
        retry_summary_hashes.update(
            str(row.get("source_summary_sha256") or "")
            for row in all_outcomes[outcome_count:]
        )
        retry_summary_hashes.discard("")
        retry_endpoint_hashes = {
            str(row.get(key) or "")
            for row in all_outcomes[outcome_count:]
            for key in (
                "source_endpoint_payload_sha256",
                "spy_endpoint_payload_sha256",
            )
        }
        retry_endpoint_hashes.discard("")
        selected_retry_summary = (
            memory.select_recovery_evidence_summary(
                memory_dir=archive,
                session_date="2026-07-30",
                accepted_summary_sha256s=retry_summary_hashes,
                required_endpoint_payload_sha256s=retry_endpoint_hashes,
                contract_sha256=memory.PINNED_CONTRACT_SHA256,
            )
        )
        assert memory.sha256_file(selected_retry_summary) == (
            memory.sha256_file(retry_summary)
        )
        recovered = memory.build(
            args_for(selected_retry_summary, archive, "2026-07-30")
        )
        assert recovered["status"] == memory.READY_STATUS, recovered
        recovered_outcomes = [
            row
            for row in memory.read_jsonl(archive / "outcomes.jsonl")
            if row.get("recorded_during_session") == "2026-07-30"
        ]
        assert len(recovered_outcomes) == 3
        retry_summary_sha256 = memory.sha256_file(retry_summary)
        assert {
            row.get("source_summary_sha256")
            for row in recovered_outcomes
        } == {first_attempt_summary_sha256, retry_summary_sha256}
        recovered_security = next(
            row
            for row in recovered_outcomes
            if row.get("ticker") == "AAA"
        )
        assert recovered_security["source_summary_sha256"] == (
            retry_summary_sha256
        )

    # A failed or absent launch session cannot be skipped. Accepting a later
    # session would make the gap impossible to backfill under append ordering.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        archive = root / "archive" / "ohlcv_pattern_memory"
        gap_summary = write_timing(
            root,
            as_of_date="2026-07-30",
            stock_close=100.0,
            stock_prior_return=-0.04,
            stock_return=0.06,
            spy_close=505.0,
            spy_prior_return=-0.02,
            spy_return=0.03,
        )
        gap = memory.build(
            args_for(gap_summary, archive, "2026-07-30")
        )
        assert gap["status"] == memory.BLOCKED_STATUS, gap
        assert (
            "requires chronological session:2026-07-29!=2026-07-30"
            in " ".join(gap["contract_failures"])
        )
        assert not (archive / "observations.jsonl").exists()
        assert not (archive / "accepted_head.json").exists()

    # A timing-side failure must invalidate a prior public READY marker
    # immediately, even though immutable chains and portfolio state remain.
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp) / "ohlcv_pattern_memory"
        output_dir.mkdir(parents=True)
        write_json(
            output_dir / "summary.json",
            {
                "schema_version": memory.SCHEMA_VERSION,
                "status": memory.READY_STATUS,
                "proposal_eligible": True,
            },
        )
        (output_dir / "report.md").write_text(
            "stale eligible report\n",
            encoding="utf-8",
        )
        failed_marker = memory.record_failed_session(
            argparse.Namespace(
                output_dir=str(output_dir),
                valuation_date="2026-07-30",
                record_failed_session_reason="timing_builder_blocked",
            )
        )
        assert failed_marker["status"] == memory.BLOCKED_STATUS
        assert failed_marker["proposal_eligible"] is False
        assert failed_marker["directional_statistics_published"] is False
        published_marker = memory.read_json(output_dir / "summary.json")
        assert published_marker["status"] == memory.BLOCKED_STATUS
        assert published_marker["failed_session_date"] == "2026-07-30"
        assert "stale eligible report" not in (
            output_dir / "report.md"
        ).read_text(encoding="utf-8")
        assert memory.process_exit_code(
            failed_marker,
            record_mode=True,
        ) == 0

        write_json(
            output_dir / "summary.json",
            {
                "schema_version": memory.SCHEMA_VERSION,
                "status": memory.READY_STATUS,
                "proposal_eligible": True,
            },
        )
        (output_dir / "report.md").write_text(
            "stale eligible report after provenance failure\n",
            encoding="utf-8",
        )
        write_json(output_dir / "accepted_head.json", {"invalid": True})
        corrupt_pointer = memory.record_failed_session(
            argparse.Namespace(
                output_dir=str(output_dir),
                contract=str(
                    ROOT
                    / "docs"
                    / "run287_ohlcv_pattern_memory_contract.json"
                ),
                valuation_date="2026-07-31",
                record_failed_session_reason="current_session_pending",
            )
        )
        assert corrupt_pointer["record_mode_must_stop"] is True
        assert corrupt_pointer["stale_public_marker_replaced"] is True
        assert memory.process_exit_code(
            corrupt_pointer,
            record_mode=True,
        ) == 2
        replaced_stale = memory.read_json(output_dir / "summary.json")
        assert replaced_stale["status"] == memory.BLOCKED_STATUS
        assert replaced_stale["proposal_eligible"] is False
        assert replaced_stale["failed_session_date"] == "2026-07-31"

    # A valid close does not make an underpowered/data-not-ready observation
    # resolvable; it remains in the matured missing denominator permanently.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        archive = root / "archive" / "ohlcv_pattern_memory"
        first_summary = write_timing(
            root,
            as_of_date="2026-07-29",
            stock_close=96.0,
            stock_prior_return=-0.04,
            stock_return=0.06,
            spy_close=500.0,
            spy_prior_return=-0.02,
            spy_return=0.03,
            stock_data_reason="history_underpowered:20<253",
        )
        first = memory.build(
            args_for(first_summary, archive, "2026-07-29")
        )
        assert first["status"] == memory.READY_STATUS, first
        assert first["observation_data_coverage_complete"] is False
        second_summary = write_timing(
            root,
            as_of_date="2026-07-30",
            stock_close=100.0,
            stock_prior_return=0.06,
            stock_return=-0.02,
            spy_close=505.0,
            spy_prior_return=0.03,
            spy_return=0.01,
            outcome_origin_date="2026-07-29",
            outcome_basis_prices={
                "AAA": (96.0, 100.0),
                "SPY": (500.0, 505.0),
                "QQQ": (450.0, 454.5),
            },
        )
        second = memory.build(
            args_for(second_summary, archive, "2026-07-30")
        )
        assert second["status"] == memory.READY_STATUS, second
        outcomes = memory.read_jsonl(archive / "outcomes.jsonl")
        assert not any(
            row["source_kind"] == "SECURITY" for row in outcomes
        )
        security_group = next(
            row
            for row in second["aggregates"]
            if row["source_kind"] == "SECURITY"
            and row["horizon_nyse_sessions"] == 1
        )
        assert security_group["matured_observation_count"] == 1
        assert security_group["resolved_observation_count"] == 0
        assert security_group["directional_statistics_published"] is False

    # A security outcome is unresolved when either exact SPY endpoint is
    # absent, even if the security's own target-basis endpoint is complete.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        archive = root / "archive" / "ohlcv_pattern_memory"
        first_summary = write_timing(
            root,
            as_of_date="2026-07-29",
            stock_close=96.0,
            stock_prior_return=-0.04,
            stock_return=0.06,
            spy_close=500.0,
            spy_prior_return=-0.02,
            spy_return=0.03,
        )
        assert memory.build(
            args_for(first_summary, archive, "2026-07-29")
        )["status"] == memory.READY_STATUS
        second_summary = write_timing(
            root,
            as_of_date="2026-07-30",
            stock_close=100.0,
            stock_prior_return=0.06,
            stock_return=-0.02,
            spy_close=505.0,
            spy_prior_return=0.03,
            spy_return=0.01,
            outcome_origin_date="2026-07-29",
            outcome_basis_prices={
                "AAA": (96.0, 100.0),
                "SPY": (500.0, 505.0),
                "QQQ": (450.0, 454.5),
            },
        )
        second_payload = json.loads(
            second_summary.read_text(encoding="utf-8")
        )
        endpoint_path = Path(
            second_payload["outputs"]["forward_outcome_endpoints"]["path"]
        )
        endpoint_rows = [
            row
            for row in memory.read_jsonl(endpoint_path)
            if row["ticker"] != "SPY"
        ]
        endpoint_path.write_text(
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in endpoint_rows
            ),
            encoding="utf-8",
        )
        second_payload["outputs"]["forward_outcome_endpoints"] = fingerprint(
            endpoint_path
        )
        write_json(second_summary, second_payload)
        incomplete_spy = memory.build(
            args_for(second_summary, archive, "2026-07-30")
        )
        assert incomplete_spy["status"] == memory.READY_STATUS, incomplete_spy
        resolved = memory.read_jsonl(archive / "outcomes.jsonl")
        assert not any(
            row["source_kind"] == "SECURITY" for row in resolved
        )
        security_group = next(
            row
            for row in incomplete_spy["aggregates"]
            if row["source_kind"] == "SECURITY"
            and row["horizon_nyse_sessions"] == 1
        )
        assert security_group["matured_observation_count"] == 1
        assert security_group["resolved_observation_count"] == 0
        assert security_group["missing_exact_outcome_count"] == 1
        assert security_group["directional_statistics_published"] is False

    print("run287_ohlcv_pattern_memory_smoke: PASS")


if __name__ == "__main__":
    main()

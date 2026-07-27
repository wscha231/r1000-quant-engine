#!/usr/bin/env python3
"""Smoke checks for the fail-closed Run287 multiple-testing gate."""
from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "run_run287_multiple_testing_gate.py"
SPEC = importlib.util.spec_from_file_location(
    "run_run287_multiple_testing_gate", MODULE_PATH
)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)
sys.path.insert(0, str(ROOT / "tools"))
from run287_promotion_gate import (  # noqa: E402
    DEFAULT_EVIDENCE,
    DEFAULT_STATE,
    overlay_multiple_testing_evidence,
    read_json,
)
CONTRACT = ROOT / "docs" / "run287_multiple_testing_gate_contract.json"
EXPECTED_OUTPUTS = {
    "source_manifest.json",
    "multiple_testing_gate.json",
    "cscv_splits.csv",
    "white_reality_check.json",
    "report.md",
}


def default_prior_registry_entry() -> dict[str, Any]:
    return {
        "id": "prior-performance-family",
        "signal": "prior_signal",
        "mechanism": "prior_mechanism",
        "book": "prior_book",
        "window": "prior_window",
        "status": "REJECTED",
        "blocked_reuse": True,
        "multiplicity": {
            "performance_evaluated": True,
            "candidate_id": "run287-prior-performance-family",
            "causal_family_id": "prior_performance_family",
            "completed_trial_count": 1,
            "evidence_sha256": "1" * 64,
        },
    }


def strong_matrix(
    observation_count: int = 504,
    trial_count: int = 5,
) -> np.ndarray:
    index = np.arange(observation_count, dtype=float)
    columns = []
    for trial in range(trial_count):
        noise = (
            0.0015 * np.sin(index * (0.071 + trial * 0.004) + trial * 0.2)
            + 0.0008
            * np.cos(index * (0.031 + trial * 0.003) + trial * 0.4)
        )
        mean = 0.0025 if trial == 0 else 0.0007 - trial * 0.00012
        columns.append(mean + noise)
    return np.column_stack(columns)


def weak_matrix(
    observation_count: int = 504,
    trial_count: int = 5,
) -> np.ndarray:
    rng = np.random.default_rng(9917)
    shared = rng.normal(0.0, 0.01, size=(observation_count, 1))
    idiosyncratic = rng.normal(
        0.0, 0.004, size=(observation_count, trial_count)
    )
    return shared + idiosyncratic


def ledger_for(matrix: np.ndarray) -> dict[str, Any]:
    promotion_state = read_json(DEFAULT_STATE)
    canonical_champion = promotion_state["canonical_champion"]
    trial_ids = [f"trial_{index:02d}" for index in range(matrix.shape[1])]
    sharpes = MOD.sharpe_vector(matrix)
    selected_id, selected_index = MOD.selected_trial(trial_ids, sharpes)
    prior_index = (
        len(trial_ids) - 1
        if selected_index != len(trial_ids) - 1
        else 0
    )
    trials = []
    for index, trial_id in enumerate(trial_ids):
        prior_trial = index == prior_index
        parameter_set = {
            "rank_power": round(1.0 + index * 0.1, 2),
            "no_trade_band_bps": index * 5,
        }
        trials.append(
            {
                "trial_id": trial_id,
                "candidate_id": (
                    "run287-prior-performance-family"
                    if prior_trial
                    else "run287-pit-leadership-acceleration-v1"
                ),
                "causal_family_id": (
                    "prior_performance_family"
                    if prior_trial
                    else "pit_leadership_acceleration_v1"
                ),
                "preregistered": True,
                "performance_evaluated": True,
                "status": "COMPLETED",
                "return_column": f"excess_{trial_id}",
                "parameter_set": parameter_set,
                "parameter_set_sha256": MOD.canonical_parameter_hash(
                    parameter_set
                ),
            }
        )
    return {
        "schema_version": MOD.LEDGER_SCHEMA,
        "candidate_id": "run287-pit-leadership-acceleration-v1",
        "champion_id": canonical_champion["policy_id"],
        "canonical_champion": canonical_champion,
        "causal_family_id": "pit_leadership_acceleration_v1",
        "causal_challenger_count": 1,
        "complete_attempt_history": True,
        "multiplicity_population_complete": True,
        "prior_performance_evaluated_trial_count": 1,
        "performance_evaluated_family_count": 2,
        "preregistered": True,
        "selection_metric": "daily_sharpe",
        "return_semantics": MOD.CANONICAL_INPUT_CONTRACT["return_semantics"],
        "costs_included": True,
        "selected_trial_id": selected_id,
        "attempted_parameter_set_count": len(trials),
        "trials": trials,
    }


def write_fixture(
    root: Path,
    matrix: np.ndarray,
    *,
    ledger: dict[str, Any] | None = None,
    registry_entries: list[dict[str, Any]] | None = None,
    preregistration_registry_path: str = (
        "docs/run287_do_not_repeat_registry.json"
    ),
) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    payload = ledger or ledger_for(matrix)
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date="2022-01-03",
        end_date="2026-12-31",
    )
    dates = schedule.index[: matrix.shape[0]]
    payload["evaluation_window"] = {
        "calendar": "NYSE",
        "date_column": "date",
        "first_session": dates[0].date().isoformat(),
        "last_session": dates[-1].date().isoformat(),
        "session_count": len(dates),
    }
    repository = root / "registration_repository"
    repository.mkdir()

    def git(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=repository,
            capture_output=True,
            text=True,
            check=True,
        )

    git("init", "-q")
    git("config", "user.name", "Run287 Test")
    git("config", "user.email", "run287-test@example.invalid")
    git("config", "core.autocrlf", "false")
    docs = repository / "docs"
    docs.mkdir()
    effective_registry_entries = (
        [default_prior_registry_entry()]
        if registry_entries is None
        else registry_entries
    )
    registry_path = docs / "run287_do_not_repeat_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "run287-do-not-repeat-registry-v1",
                "match_fields": ["signal", "mechanism", "book", "window"],
                "entries": effective_registry_entries,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    registry_sha256 = MOD.sha256_file(registry_path)
    preregistration_path = docs / "challenger_preregistration.json"
    preregistration_path.write_text(
        json.dumps(
            {
                "schema_version": MOD.PREREGISTRATION_SCHEMA,
                "candidate_id": payload["candidate_id"],
                "champion_id": payload["champion_id"],
                "canonical_champion": payload["canonical_champion"],
                "causal_family_id": payload["causal_family_id"],
                "causal_challenger_count": 1,
                "hypothesis": "one PIT leadership acceleration mechanism",
                "mechanism": "confirmation_veto_only",
                "selection_metric": "daily_sharpe",
                "registered_before_evaluation": True,
                "preregistered_trial_count": len(payload["trials"]),
                "trial_specifications": MOD.trial_specification_map(
                    payload["trials"]
                ),
                "evaluation_window": payload["evaluation_window"],
                "multiplicity_population_complete": True,
                "prior_performance_evaluated_trial_count": payload[
                    "prior_performance_evaluated_trial_count"
                ],
                "performance_evaluated_family_count": payload[
                    "performance_evaluated_family_count"
                ],
                "do_not_repeat_registry_path": (
                    preregistration_registry_path
                ),
                "do_not_repeat_registry_sha256": registry_sha256,
                "do_not_repeat_conflict_absent": True,
                "do_not_repeat_descriptor": {
                    "signal": "pit_leadership_acceleration",
                    "mechanism": "confirmation_veto_only",
                    "book": "run287_generated_books",
                    "window": "preregistered_u4_window",
                },
                "safety": MOD.CANONICAL_PREREGISTRATION_SAFETY,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    git("add", "docs")
    git("commit", "-q", "-m", "preregister challenger")
    registration_commit = git("rev-parse", "HEAD").stdout.strip()
    preregistration_blob = MOD.git_blob(
        repository,
        registration_commit,
        "docs/challenger_preregistration.json",
    )
    promotion_state_sha256 = MOD.sha256_file(DEFAULT_STATE)
    evaluation_snapshot_path = docs / "challenger_evaluation_snapshot.json"
    evaluation_snapshot_path.write_text(
        json.dumps(
            {
                "schema_version": MOD.EVALUATION_SNAPSHOT_SCHEMA,
                "candidate_id": payload["candidate_id"],
                "champion_id": payload["champion_id"],
                "canonical_champion": payload["canonical_champion"],
                "causal_family_id": payload["causal_family_id"],
                "selection_metric": "daily_sharpe",
                "evaluation_trial_count": len(payload["trials"]),
                "trial_specifications": MOD.trial_specification_map(
                    payload["trials"]
                ),
                "evaluation_window": payload["evaluation_window"],
                "multiplicity_population_complete": True,
                "prior_performance_evaluated_trial_count": payload[
                    "prior_performance_evaluated_trial_count"
                ],
                "performance_evaluated_family_count": payload[
                    "performance_evaluated_family_count"
                ],
                "preregistration": {
                    "commit_sha": registration_commit,
                    "path": "docs/challenger_preregistration.json",
                    "sha256": MOD.sha256_bytes(preregistration_blob),
                },
                "promotion_state_sha256": promotion_state_sha256,
                "canonical_do_not_repeat_registry_sha256": registry_sha256,
                "safety": MOD.CANONICAL_EVALUATION_SNAPSHOT_SAFETY,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    git("add", "docs/challenger_evaluation_snapshot.json")
    git("commit", "-q", "-m", "anchor evaluation start")
    evaluation_commit = git("rev-parse", "HEAD").stdout.strip()
    evaluation_snapshot_blob = MOD.git_blob(
        repository,
        evaluation_commit,
        "docs/challenger_evaluation_snapshot.json",
    )
    git("commit", "--allow-empty", "-q", "-m", "evaluation head")
    payload["registration_commit_sha"] = registration_commit
    payload["preregistration_path"] = (
        "docs/challenger_preregistration.json"
    )
    payload["preregistration_sha256"] = MOD.sha256_bytes(
        preregistration_blob
    )
    payload["evaluation_commit_sha"] = evaluation_commit
    payload["evaluation_snapshot_path"] = (
        "docs/challenger_evaluation_snapshot.json"
    )
    payload["evaluation_snapshot_sha256"] = MOD.sha256_bytes(
        evaluation_snapshot_blob
    )
    ledger_path = root / "experiment_ledger.json"
    frame = pd.DataFrame(
        {
            trial["return_column"]: matrix[:, index]
            for index, trial in enumerate(payload["trials"])
        }
    )
    frame.insert(0, "date", dates.strftime("%Y-%m-%d"))
    return_path = root / "daily_excess_returns.csv"
    frame.to_csv(return_path, index=False, lineterminator="\n")
    payload["return_matrix_sha256"] = MOD.sha256_file(return_path)
    ledger_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "ledger": ledger_path,
        "returns": return_path,
        "output": root / "output",
        "repository": repository,
        "promotion_state": DEFAULT_STATE,
    }


def run(paths: dict[str, Path]) -> dict[str, Any]:
    return MOD.evaluate(
        contract_path=CONTRACT,
        experiment_ledger_path=paths["ledger"],
        return_matrix_path=paths["returns"],
        output_dir=paths["output"],
        repository_root=paths["repository"],
        promotion_state_path=paths["promotion_state"],
    )


def test_strong_complete_family_passes_and_is_deterministic() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        paths = write_fixture(root, strong_matrix())
        gate = run(paths)
        assert gate["status"] == "PASS"
        assert gate["passed"] is True
        assert set(path.name for path in paths["output"].iterdir()) == EXPECTED_OUTPUTS
        assert gate["deflated_sharpe"]["probability"] >= 0.95
        assert gate["probability_of_backtest_overfitting"]["probability"] <= 0.20
        assert gate["probability_of_backtest_overfitting"]["split_count"] == 70
        white = json.loads(
            (paths["output"] / "white_reality_check.json").read_text(
                encoding="utf-8"
            )
        )
        assert white["passed"] is True
        assert [row["block_length"] for row in white["results"]] == [5, 21, 63]
        assert all(row["p_value"] <= 0.10 for row in white["results"])
        assert gate["safety"] == MOD.CANONICAL_SAFETY
        assert gate["champion_changed"] is False
        assert gate["fullrun_executed"] is False
        source = paths["output"] / "source_manifest.json"
        assert gate["source_manifest_sha256"] == MOD.sha256_file(source)
        for name, digest in gate["artifact_hashes"].items():
            assert digest == MOD.sha256_file(paths["output"] / name)
        assert run(paths) == gate

        second = {**paths, "output": root / "output_second"}
        second_gate = run(second)
        assert second_gate == gate
        for name in EXPECTED_OUTPUTS:
            assert (paths["output"] / name).read_bytes() == (
                second["output"] / name
            ).read_bytes()


def test_incomplete_or_forged_trial_history_fails_without_statistics() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        matrix = strong_matrix()
        ledger = ledger_for(matrix)
        ledger["complete_attempt_history"] = False
        ledger["trials"][0]["parameter_set_sha256"] = "0" * 64
        paths = write_fixture(root, matrix, ledger=ledger)
        gate = run(paths)
        assert gate["passed"] is False
        assert "complete_attempt_history_not_proven" in gate["blockers"]
        assert any(
            blocker.endswith("parameter_set_sha256_mismatch")
            for blocker in gate["blockers"]
        )
        assert gate["deflated_sharpe"]["status"] == "NOT_EVALUATED"
        assert (
            gate["probability_of_backtest_overfitting"]["status"]
            == "NOT_EVALUATED"
        )


def test_matrix_must_match_every_recorded_trial_and_date() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        paths = write_fixture(root, strong_matrix())
        frame = pd.read_csv(paths["returns"])
        frame = frame.drop(columns=[frame.columns[-1]])
        frame.loc[1, "date"] = frame.loc[0, "date"]
        frame.to_csv(paths["returns"], index=False, lineterminator="\n")
        gate = run(paths)
        assert gate["passed"] is False
        assert "return_matrix_column_set_mismatch" in gate["blockers"]
        assert gate["sample"]["observation_count"] == 0


def test_return_columns_and_evaluation_window_are_preregistered() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        paths = write_fixture(root, strong_matrix())
        ledger = json.loads(paths["ledger"].read_text(encoding="utf-8"))
        first = ledger["trials"][0]["return_column"]
        second = ledger["trials"][1]["return_column"]
        ledger["trials"][0]["return_column"] = second
        ledger["trials"][1]["return_column"] = first
        paths["ledger"].write_text(
            json.dumps(ledger, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        gate = run(paths)
        assert gate["passed"] is False
        assert "preregistered_trial_set_mismatch" in gate["blockers"]
        assert "evaluation_snapshot_trial_set_mismatch" in gate["blockers"]

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        paths = write_fixture(root, strong_matrix())
        frame = pd.read_csv(paths["returns"])
        shifted = mcal.get_calendar("NYSE").schedule(
            start_date="2023-01-03",
            end_date="2026-12-31",
        ).index[: len(frame)]
        frame["date"] = shifted.strftime("%Y-%m-%d")
        frame.to_csv(
            paths["returns"],
            index=False,
            lineterminator="\n",
        )
        ledger = json.loads(paths["ledger"].read_text(encoding="utf-8"))
        ledger["return_matrix_sha256"] = MOD.sha256_file(paths["returns"])
        paths["ledger"].write_text(
            json.dumps(ledger, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        gate = run(paths)
        assert gate["passed"] is False
        assert "return_matrix_evaluation_window_mismatch" in gate["blockers"]


def test_selected_trial_is_reproduced_not_trusted() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        matrix = strong_matrix()
        ledger = ledger_for(matrix)
        assert ledger["selected_trial_id"] == "trial_00"
        ledger["selected_trial_id"] = "trial_01"
        paths = write_fixture(root, matrix, ledger=ledger)
        gate = run(paths)
        assert gate["passed"] is False
        assert (
            "selected_trial_not_reproducible:trial_01!=trial_00"
            in gate["blockers"]
        )
        assert gate["deflated_sharpe"]["status"] == "NOT_EVALUATED"

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        matrix = strong_matrix()
        ledger = ledger_for(matrix)
        prior_trial = next(
            trial
            for trial in ledger["trials"]
            if trial["candidate_id"] != ledger["candidate_id"]
        )
        ledger["selected_trial_id"] = prior_trial["trial_id"]
        paths = write_fixture(root, matrix, ledger=ledger)
        gate = run(paths)
        assert gate["passed"] is False
        assert (
            "selected_trial_not_in_active_causal_challenger"
            in gate["blockers"]
        )


def test_canonical_champion_is_not_caller_selected() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        matrix = strong_matrix()
        ledger = ledger_for(matrix)
        forged = dict(ledger["canonical_champion"])
        forged["policy_id"] = "caller-selected-champion"
        ledger["canonical_champion"] = forged
        ledger["champion_id"] = forged["policy_id"]
        paths = write_fixture(root, matrix, ledger=ledger)
        gate = run(paths)
        assert gate["passed"] is False
        assert "ledger_canonical_champion_mismatch" in gate["blockers"]
        assert gate["checks"]["canonical_champion_binding"] is False


def test_preregistration_must_precede_evaluation_head() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        paths = write_fixture(root, strong_matrix())
        ledger = json.loads(paths["ledger"].read_text(encoding="utf-8"))
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=paths["repository"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        ledger["registration_commit_sha"] = head
        preregistration_blob = MOD.git_blob(
            paths["repository"],
            head,
            ledger["preregistration_path"],
        )
        ledger["preregistration_sha256"] = MOD.sha256_bytes(
            preregistration_blob
        )
        paths["ledger"].write_text(
            json.dumps(ledger), encoding="utf-8"
        )
        gate = run(paths)
        assert gate["passed"] is False
        assert (
            "registration_commit_does_not_strictly_precede_evaluation"
            in gate["blockers"]
        )
        assert gate["checks"]["git_anchored_preregistration"] is False


def test_registry_must_be_canonical_and_append_only() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        paths = write_fixture(
            root,
            strong_matrix(),
            preregistration_registry_path="docs/arbitrary_empty_registry.json",
        )
        gate = run(paths)
        assert gate["passed"] is False
        assert (
            "preregistration_do_not_repeat_registry_anchor_invalid"
            in gate["blockers"]
        )

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        protected_entry = {
            "id": "prior-rejected-family",
            "signal": "prior_signal",
            "mechanism": "prior_mechanism",
            "book": "prior_book",
            "window": "prior_window",
            "blocked_reuse": True,
            "multiplicity": {
                "performance_evaluated": False,
            },
        }
        paths = write_fixture(
            root,
            strong_matrix(),
            registry_entries=[protected_entry],
        )
        registry = (
            paths["repository"]
            / "docs"
            / "run287_do_not_repeat_registry.json"
        )
        registry.write_text(
            json.dumps(
                {
                    "schema_version": "run287-do-not-repeat-registry-v1",
                    "match_fields": [
                        "signal",
                        "mechanism",
                        "book",
                        "window",
                    ],
                    "entries": [],
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        gate = run(paths)
        assert gate["passed"] is False
        assert any(
            blocker.startswith(
                "canonical_registry_history_not_preserved:"
                "evaluation_to_current:"
            )
            for blocker in gate["blockers"]
        )
        assert gate["checks"]["canonical_registry_history"] is False

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        paths = write_fixture(root, strong_matrix())
        registry = (
            paths["repository"]
            / "docs"
            / "run287_do_not_repeat_registry.json"
        )
        payload = json.loads(registry.read_text(encoding="utf-8"))
        payload["match_fields"] = [
            "signal",
            "mechanism",
            "book",
            "window",
            "caller_selected_field",
        ]
        registry.write_text(
            json.dumps(payload, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        gate = run(paths)
        assert gate["passed"] is False
        assert "current_registry_match_fields_not_canonical" in gate[
            "blockers"
        ]


def test_prior_performance_families_are_in_multiplicity_population() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        matrix = strong_matrix()
        ledger = ledger_for(matrix)
        for trial in ledger["trials"]:
            trial["candidate_id"] = ledger["candidate_id"]
            trial["causal_family_id"] = ledger["causal_family_id"]
        ledger["prior_performance_evaluated_trial_count"] = 0
        ledger["performance_evaluated_family_count"] = 1
        paths = write_fixture(root, matrix, ledger=ledger)
        gate = run(paths)
        assert gate["passed"] is False
        assert (
            "prior_performance_trial_population_missing:0<1"
            in gate["blockers"]
        )
        assert (
            gate["checks"][
                "complete_cross_family_multiplicity_population"
            ]
            is False
        )

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        unclassified = default_prior_registry_entry()
        unclassified.pop("multiplicity")
        paths = write_fixture(
            root,
            strong_matrix(),
            registry_entries=[unclassified],
        )
        gate = run(paths)
        assert gate["passed"] is False
        assert (
            "evaluation_registry_multiplicity_classification_missing:"
            "prior-performance-family"
            in gate["blockers"]
        )


def test_minimum_trials_and_observations_are_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        matrix = strong_matrix(observation_count=503, trial_count=4)
        paths = write_fixture(root, matrix)
        gate = run(paths)
        assert gate["passed"] is False
        assert "minimum_trials_not_met:4<5" in gate["blockers"]
        assert (
            "minimum_synchronous_observations_not_met:503<504"
            in gate["blockers"]
        )
        assert gate["checks"]["minimum_trials"] is False
        assert gate["checks"]["minimum_synchronous_observations"] is False


def test_noise_does_not_become_a_promotable_winner() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        paths = write_fixture(root, weak_matrix())
        gate = run(paths)
        assert gate["passed"] is False
        assert any(
            blocker
            in {
                "deflated_sharpe_threshold_not_met",
                "pbo_threshold_not_met",
                "white_reality_check_threshold_not_met",
            }
            for blocker in gate["blockers"]
        )
        assert all(
            math.isfinite(float(value))
            for value in gate["deflated_sharpe"][
                "trial_daily_sharpes"
            ].values()
        )
        assert gate["champion_changed"] is False


def test_contract_thresholds_cannot_be_weakened() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        paths = write_fixture(root, strong_matrix())
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["thresholds"][
            "deflated_sharpe_probability_minimum"
        ] = 0.50
        tampered = root / "tampered_contract.json"
        tampered.write_text(json.dumps(contract), encoding="utf-8")
        gate = MOD.evaluate(
            contract_path=tampered,
            experiment_ledger_path=paths["ledger"],
            return_matrix_path=paths["returns"],
            output_dir=paths["output"],
            repository_root=paths["repository"],
            promotion_state_path=paths["promotion_state"],
        )
        assert gate["passed"] is False
        assert "contract_thresholds_not_canonical" in gate["blockers"]
        assert gate["deflated_sharpe"]["status"] == "NOT_EVALUATED"


def test_promotion_overlay_requires_exact_untampered_bundle() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        paths = write_fixture(root, strong_matrix())
        gate = run(paths)
        gate_path = paths["output"] / "multiple_testing_gate.json"
        base = read_json(DEFAULT_EVIDENCE)
        base["candidate_id"] = gate["candidate_id"]
        base["historical"]["multiple_testing_pass"] = True
        overlaid = overlay_multiple_testing_evidence(
            base,
            gate_path,
            expected_gate_sha256=MOD.sha256_file(gate_path),
            contract_path=CONTRACT,
            experiment_ledger_path=paths["ledger"],
            return_matrix_path=paths["returns"],
            promotion_state_snapshot_path=paths["promotion_state"],
            repository_root=paths["repository"],
            current_promotion_state=read_json(DEFAULT_STATE),
        )
        assert overlaid["historical"]["multiple_testing_pass"] is True
        observation = overlaid["multiple_testing_gate_observation"]
        assert observation["candidate_id"] == gate["candidate_id"]
        assert observation["champion_changed"] is False

        def expect_overlay_error(expected_error: str) -> None:
            try:
                overlay_multiple_testing_evidence(
                    base,
                    gate_path,
                    expected_gate_sha256=MOD.sha256_file(gate_path),
                    contract_path=CONTRACT,
                    experiment_ledger_path=paths["ledger"],
                    return_matrix_path=paths["returns"],
                    promotion_state_snapshot_path=paths["promotion_state"],
                    repository_root=paths["repository"],
                    current_promotion_state=read_json(DEFAULT_STATE),
                )
            except ValueError as exc:
                assert expected_error in str(exc), str(exc)
            else:
                raise AssertionError(
                    f"tampered multiple-testing input accepted: {expected_error}"
                )

        white_path = paths["output"] / "white_reality_check.json"
        original_white = white_path.read_bytes()
        white_path.write_text("{}\n", encoding="utf-8")
        expect_overlay_error("artifact_sha256_mismatch")
        white_path.write_bytes(original_white)

        report_path = paths["output"] / "report.md"
        original_report = report_path.read_bytes()
        report_path.write_text("forged report\n", encoding="utf-8")
        expect_overlay_error("artifact_sha256_mismatch:report.md")
        report_path.write_bytes(original_report)

        original_ledger = paths["ledger"].read_bytes()
        paths["ledger"].write_text("{}\n", encoding="utf-8")
        expect_overlay_error(
            "multiple_testing_recompute_input_sha256_mismatch:"
            "experiment_ledger"
        )
        paths["ledger"].write_bytes(original_ledger)

        forged_state = read_json(DEFAULT_STATE)
        forged_state["canonical_champion"] = dict(
            forged_state["canonical_champion"]
        )
        forged_state["canonical_champion"]["policy_id"] = "forged"
        try:
            overlay_multiple_testing_evidence(
                base,
                gate_path,
                expected_gate_sha256=MOD.sha256_file(gate_path),
                contract_path=CONTRACT,
                experiment_ledger_path=paths["ledger"],
                return_matrix_path=paths["returns"],
                promotion_state_snapshot_path=paths["promotion_state"],
                repository_root=paths["repository"],
                current_promotion_state=forged_state,
            )
        except ValueError as exc:
            assert "canonical_champion_mismatch" in str(exc)
        else:
            raise AssertionError("caller-selected champion was accepted")

        advanced_state = read_json(DEFAULT_STATE)
        advanced_state["promotion_state"] = "SHADOW_OPERATION_READY"
        advanced_state["official_challenger"] = {
            "candidate_id": "different-candidate",
            "causal_family_id": gate["causal_family_id"],
            "selected_trial_id": gate["selected_trial_id"],
            "multiple_testing_gate_sha256": MOD.sha256_file(gate_path),
        }
        try:
            overlay_multiple_testing_evidence(
                base,
                gate_path,
                expected_gate_sha256=MOD.sha256_file(gate_path),
                contract_path=CONTRACT,
                experiment_ledger_path=paths["ledger"],
                return_matrix_path=paths["returns"],
                promotion_state_snapshot_path=paths["promotion_state"],
                repository_root=paths["repository"],
                current_promotion_state=advanced_state,
            )
        except ValueError as exc:
            assert "official_challenger_mismatch" in str(exc)
        else:
            raise AssertionError("mismatched official challenger was accepted")


def test_official_promotion_wrapper_ignores_unattested_true_bit() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        evidence = read_json(DEFAULT_EVIDENCE)
        evidence["historical"]["multiple_testing_pass"] = True
        evidence_path = root / "forged_evidence.json"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        output = root / "promotion"
        process = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "run_run287_promotion_gate.py"),
                "--evidence",
                str(evidence_path),
                "--output-dir",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert process.returncode == 0, process.stdout + process.stderr
        gate = json.loads(
            (output / "promotion_gate.json").read_text(encoding="utf-8")
        )
        assert gate["historical_gate"]["checks"]["multiple_testing_pass"] is False
        assert "multiple_testing_pass" in gate["historical_gate"]["blockers"]


def test_advanced_state_requires_daily_approved_bundle() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        state = read_json(DEFAULT_STATE)
        state["promotion_state"] = "FORWARD_PAPER_VALIDATING"
        state_path = root / "advanced_state.json"
        state_path.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        process = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "run_run287_promotion_gate.py"),
                "--state",
                str(state_path),
                "--output-dir",
                str(root / "promotion"),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert process.returncode != 0
        assert (
            "advanced_state_multiple_testing_bundle_required"
            in process.stderr
        )


def main() -> int:
    test_strong_complete_family_passes_and_is_deterministic()
    test_incomplete_or_forged_trial_history_fails_without_statistics()
    test_matrix_must_match_every_recorded_trial_and_date()
    test_return_columns_and_evaluation_window_are_preregistered()
    test_selected_trial_is_reproduced_not_trusted()
    test_canonical_champion_is_not_caller_selected()
    test_preregistration_must_precede_evaluation_head()
    test_registry_must_be_canonical_and_append_only()
    test_prior_performance_families_are_in_multiplicity_population()
    test_minimum_trials_and_observations_are_fail_closed()
    test_noise_does_not_become_a_promotable_winner()
    test_contract_thresholds_cannot_be_weakened()
    test_promotion_overlay_requires_exact_untampered_bundle()
    test_official_promotion_wrapper_ignores_unattested_true_bit()
    test_advanced_state_requires_daily_approved_bundle()
    print("run287_multiple_testing_gate_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

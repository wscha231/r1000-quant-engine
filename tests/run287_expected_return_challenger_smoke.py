#!/usr/bin/env python3
"""Smoke tests for the PIT-purged Run287 expected-return challenger."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import warnings
import zipfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import run_run287_expected_return_challenger as MOD  # noqa: E402


CONTRACT_PATH = ROOT / "docs" / "run287_expected_return_challenger_contract.json"


def contract() -> dict:
    return MOD.validate_contract(MOD.read_json(CONTRACT_PATH))


def valid_u0() -> dict:
    audit_sha = MOD.git_head()
    source = valid_source_u0(audit_sha)
    gate = contract()["historical_gate"]
    trial_floor = 5
    return {
        "schema_version": "run287-u0-v3-recovery-census-v1",
        "repository": MOD.REPOSITORY,
        "audit_default_branch": "master",
        "audit_default_branch_sha": audit_sha,
        "source_observed_at_utc": source["generated_at_utc"],
        "repository_namespace_sha256": MOD.canonical_sha256(
            MOD.source_repository_namespace(source)
        ),
        "source_census_sha256": MOD.canonical_sha256(source),
        "source_inventory_sha256": MOD.git_json_blob_canonical_sha256(
            audit_sha, "docs/run287_u0_experiment_inventory.json"
        ),
        "recovery_contract_sha256": gate[
            "accepted_u0_recovery_contract_sha256"
        ],
        "safety": {
            "metadata_only": True,
            "fullrun_allowed": False,
            "target_order_ledger_mutation_allowed": False,
            "production_or_live_trading_allowed": False,
            "automatic_promotion_allowed": False,
            "acceptance_gate_migration_allowed_by_this_contract": False,
        },
        "summary": {
            "historical_experiment_census_complete": True,
            "historical_challenger_preregistration_ready": True,
            "historical_challenger_allowed": False,
            "conservative_historical_trial_count_lower_bound": trial_floor,
        },
        "census_completion_blockers": [],
        "acceptance_migration_blockers": gate[
            "required_recovery_migration_blockers"
        ],
        "recovered_candidates": [],
    }


def valid_source_u0(audit_sha: str | None = None) -> dict:
    audit_sha = audit_sha or MOD.git_head()
    branches = [
        {
            "name": "master",
            "head_sha": audit_sha,
            "ancestry": "IDENTICAL_TO_AUDIT_HEAD",
        }
    ]
    pull_requests = [
        {
            "number": 1,
            "head_branch": "legacy-1",
            "head_sha": "c" * 40,
            "base_sha": audit_sha,
            "updated_at": "2026-08-10T00:00:00Z",
        }
    ]
    source_contract = {
        "branch_payload_sha256": "a" * 64,
        "pull_request_payload_sha256": "b" * 64,
        "metadata_only": True,
        "fullrun_executed": False,
        "production_or_live_mutated": False,
        "champion_changed": False,
    }
    source_contract["normalized_branch_rows_sha256"] = MOD.canonical_sha256(
        branches
    )
    source_contract["normalized_pull_request_rows_sha256"] = (
        MOD.canonical_sha256(pull_requests)
    )
    return {
        "schema_version": "run287-u0-v2-github-census-v1",
        "repository": MOD.REPOSITORY,
        "audit_default_branch": "master",
        "audit_default_branch_sha": audit_sha,
        "generated_at_utc": "2026-08-11T00:00:00+00:00",
        "source_contract": source_contract,
        "branches": branches,
        "pull_requests": pull_requests,
        "summary": {
            "historical_experiment_census_complete": True,
            "historical_challenger_allowed": True,
        },
        "promotion_blockers": [],
    }


def accepted_u0_evidence(census: dict) -> dict:
    gate = contract()["historical_gate"]
    source = valid_source_u0(census["audit_default_branch_sha"])
    trial_floor = census["summary"][
        "conservative_historical_trial_count_lower_bound"
    ]
    return {
        "schema_version": "run287-u0-v3-accepted-evidence-v1",
        "repository": MOD.REPOSITORY,
        "workflow_identity": "run287-u0-v3-acceptance",
        "audit_default_branch": "master",
        "audit_default_branch_sha": census["audit_default_branch_sha"],
        "source_observed_at_utc": source["generated_at_utc"],
        "repository_namespace_sha256": MOD.canonical_sha256(
            MOD.source_repository_namespace(source)
        ),
        "source_census_sha256": MOD.canonical_sha256(source),
        "recovery_census_sha256": MOD.canonical_sha256(census),
        "source_inventory_sha256": census["source_inventory_sha256"],
        "recovery_contract_sha256": gate[
            "accepted_u0_recovery_contract_sha256"
        ],
        "acceptance_contract_sha256": gate[
            "accepted_u0_acceptance_contract_sha256"
        ],
        "conservative_historical_trial_count_lower_bound": trial_floor,
        "historical_experiment_census_complete": True,
        "historical_challenger_preregistration_ready": True,
        "historical_challenger_research_fit_allowed": True,
        "historical_broker_backtest_allowed": False,
        "legacy_result_promotion_allowed": False,
        "promotion_blockers": [],
        "target_order_ledger_mutation_allowed": False,
        "production_or_live_trading_allowed": False,
        "automatic_promotion_allowed": False,
        "fullrun_allowed": False,
    }


def canonical_u0_artifact(census: dict, evidence: dict) -> dict:
    source = valid_source_u0(census["audit_default_branch_sha"])
    namespace_sha256 = MOD.canonical_sha256(
        MOD.source_repository_namespace(source)
    )
    return {
        "verified": True,
        "artifact_id": 287,
        "workflow_run_id": 2870805,
        "workflow_path": ".github/workflows/run287_u0_acceptance.yml",
        "head_sha": census["audit_default_branch_sha"],
        "artifact_digest": "sha256:" + "a" * 64,
        "source_observed_at_utc": source["generated_at_utc"],
        "repository_namespace_sha256": namespace_sha256,
        "live_repository_namespace_sha256": namespace_sha256,
        "source_census": source,
        "census": json.loads(json.dumps(census)),
        "accepted_evidence": json.loads(json.dumps(evidence)),
    }


def run_with_accepted_test_u0(args: Namespace) -> dict:
    census = MOD.read_json(Path(args.u0_census))
    audit_sha = str(census["audit_default_branch_sha"])
    evidence_path = Path(args.u0_census).with_name("accepted_evidence.json")
    evidence_path.write_text(
        json.dumps(accepted_u0_evidence(census)), encoding="utf-8"
    )
    args.u0_accepted_evidence = str(evidence_path)
    evidence = accepted_u0_evidence(census)
    original_default = MOD.git_default_branch_sha
    original_ancestor = MOD.git_is_ancestor
    original_loader = MOD.load_canonical_u0_artifact
    MOD.git_default_branch_sha = lambda: audit_sha
    MOD.git_is_ancestor = lambda ancestor, descendant: (
        ancestor == audit_sha and descendant == MOD.git_head()
    )
    MOD.load_canonical_u0_artifact = lambda artifact_id, _contract: (
        canonical_u0_artifact(census, evidence)
        if artifact_id == 287
        else (_ for _ in ()).throw(ValueError("unexpected artifact id"))
    )
    args.u0_accepted_artifact_id = 287
    try:
        return MOD.run(args)
    finally:
        MOD.git_default_branch_sha = original_default
        MOD.git_is_ancestor = original_ancestor
        MOD.load_canonical_u0_artifact = original_loader


def u0_gate_with_accepted_test_default(census: dict) -> list[str]:
    accepted_sha = str(valid_u0()["audit_default_branch_sha"])
    original_default = MOD.git_default_branch_sha
    original_ancestor = MOD.git_is_ancestor
    MOD.git_default_branch_sha = lambda: accepted_sha
    MOD.git_is_ancestor = lambda ancestor, descendant: (
        ancestor == accepted_sha and descendant == MOD.git_head()
    )
    try:
        evidence = accepted_u0_evidence(census)
        return MOD.u0_gate(
            census,
            evidence,
            canonical_u0_artifact(census, evidence),
            contract(),
        )
    finally:
        MOD.git_default_branch_sha = original_default
        MOD.git_is_ancestor = original_ancestor


def blocked_u0() -> dict:
    return {
        "schema_version": "run287-u0-v3-recovery-census-v1",
        "summary": {
            "historical_experiment_census_complete": False,
            "historical_challenger_preregistration_ready": False,
            "historical_challenger_allowed": False,
        },
        "census_completion_blockers": ["unmapped_trials"],
    }


def synthetic_frame(months: int = 96, tickers: int = 25) -> pd.DataFrame:
    cfg = contract()
    dates = pd.date_range("2018-01-31", periods=months, freq="ME")
    start = dates.min() - pd.Timedelta(days=10)
    end = dates.max() + pd.Timedelta(days=260)
    sessions = MOD.NYSE.valid_days(start_date=start, end_date=end).tz_localize(None).normalize()
    all_features = sorted(
        {
            feature
            for horizon in MOD.HORIZONS
            for feature in cfg["features"][str(horizon)]
        }
    )
    rows: list[dict[str, object]] = []
    for month_index, date in enumerate(dates):
        future = sessions[sessions > pd.Timestamp(date)]
        assert len(future) > 126
        for ticker_index in range(tickers):
            latent = (ticker_index - (tickers - 1) / 2.0) / tickers
            row: dict[str, object] = {
                "feature_date": date,
                "rebalance_date": date,
                "ticker": f"T{ticker_index:03d}",
                "sector": f"S{ticker_index % 5}",
                "benchmark_identity": "SPY",
                "benchmark_source": "YF:SPY",
            }
            for feature_index, feature in enumerate(all_features):
                row[feature] = (
                    latent
                    + 0.03
                    * np.sin(
                        month_index * 0.31
                        + ticker_index * 0.17
                        + feature_index * 0.11
                    )
                )
            for horizon, label in ((21, "1m"), (63, "3m"), (126, "6m")):
                benchmark = 0.004 * (horizon / 21.0)
                noise = 0.004 * np.sin(month_index * 0.7 + ticker_index * 0.9)
                stock = benchmark + latent * 0.18 * (horizon / 63.0) + noise
                row[f"r_{label}"] = stock
                row[f"bench_r_{label}"] = benchmark
                row[f"r_{label}_label_end_date"] = future[horizon]
                row[f"bench_r_{label}_label_end_date"] = future[horizon]
            rows.append(row)
    return pd.DataFrame(rows)


def test_contract_is_fixed_and_leakage_features_are_rejected() -> None:
    cfg = contract()
    features = [
        feature
        for horizon in MOD.HORIZONS
        for feature in cfg["features"][str(horizon)]
    ]
    assert cfg["horizons"]["21"]["score_weight"] == 0.0
    assert cfg["horizons"]["63"]["score_weight"] == 0.65
    assert cfg["horizons"]["126"]["score_weight"] == 0.35
    assert not any(MOD.FORBIDDEN_FEATURE_RE.search(feature) for feature in features)
    tampered = json.loads(json.dumps(cfg))
    tampered["features"]["63"].append("future_return_leak")
    try:
        MOD.validate_contract(tampered)
    except ValueError as exc:
        assert "future/label columns" in str(exc)
    else:
        raise AssertionError("a future-return feature entered the whitelist")

    wrong_cadence = json.loads(json.dumps(cfg))
    wrong_cadence["horizons"]["63"]["score_weight"] = 0.60
    wrong_cadence["horizons"]["126"]["score_weight"] = 0.40
    try:
        MOD.validate_contract(wrong_cadence)
    except ValueError as exc:
        assert "fixed horizon score weight mismatch" in str(exc)
    else:
        raise AssertionError("an unapproved 63D/126D cadence was accepted")

    weak_embargo = json.loads(json.dumps(cfg))
    weak_embargo["purge_and_windows"]["embargo_nyse_sessions"] = 1
    try:
        MOD.validate_contract(weak_embargo)
    except ValueError as exc:
        assert "embargo must equal 126" in str(exc)
    else:
        raise AssertionError("a weakened embargo was accepted")

    wrong_alpha_mix = json.loads(json.dumps(cfg))
    wrong_alpha_mix["target_contract"]["benchmark_sector_mix"] = {
        "benchmark_excess": 0.0,
        "sector_neutral": 1.0,
    }
    try:
        MOD.validate_contract(wrong_alpha_mix)
    except ValueError as exc:
        assert "fixed alpha target mix mismatch" in str(exc)
    else:
        raise AssertionError("an unapproved alpha target mix was accepted")

    unregistered_hyperparameter = json.loads(json.dumps(cfg))
    unregistered_hyperparameter["model"]["ridge_alpha"] = 9.0
    try:
        MOD.validate_contract(unregistered_hyperparameter)
    except ValueError as exc:
        assert "contract hash mismatch" in str(exc)
    else:
        raise AssertionError("an unregistered contract mutation was accepted")


def test_u0_gate_blocks_model_fit_and_all_mutations() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        feature_store = root / "features.parquet"
        synthetic_frame(months=18).to_parquet(feature_store)
        census_payload = blocked_u0()
        census = root / "census.json"
        census.write_text(json.dumps(census_payload), encoding="utf-8")
        evidence = root / "accepted_evidence.json"
        evidence.write_text(
            json.dumps(
                {
                    "schema_version": "run287-u0-v3-accepted-evidence-v1",
                    "repository": MOD.REPOSITORY,
                    "workflow_identity": "run287-u0-v3-acceptance",
                    "audit_default_branch_sha": "",
                    "recovery_census_sha256": MOD.canonical_sha256(
                        census_payload
                    ),
                    "historical_experiment_census_complete": False,
                    "historical_challenger_research_fit_allowed": False,
                    "promotion_blockers": ["unmapped_trials"],
                }
            ),
            encoding="utf-8",
        )
        output = root / "out"
        original = MOD.walk_forward_predictions

        def forbidden_fit(*_args, **_kwargs):
            raise AssertionError("historical fit ran through a blocked U0 gate")

        MOD.walk_forward_predictions = forbidden_fit
        try:
            summary = MOD.run(
                Namespace(
                    contract=str(CONTRACT_PATH),
                    u0_census=str(census),
                    u0_accepted_evidence=str(evidence),
                    feature_store=str(feature_store),
                    output_dir=str(output),
                )
            )
        finally:
            MOD.walk_forward_predictions = original
        assert summary["status"] == MOD.BLOCKED_STATUS
        assert (
            "u0_historical_challenger_preregistration_not_ready"
            in summary["blockers"]
        )
        assert summary["historical_model_fit_executed"] is False
        assert summary["historical_backtest_executed"] is False
        assert summary["target_books_written"] is False
        assert summary["orders_generated"] is False
        assert summary["portfolio_or_ledger_mutated"] is False

    assert "u0_accepted_evidence_not_an_object" in MOD.u0_gate(
        valid_u0(), None, None, contract()
    )
    accepted = valid_u0()
    accepted_evidence = accepted_u0_evidence(accepted)
    canonical = canonical_u0_artifact(accepted, accepted_evidence)
    truncated = json.loads(json.dumps(accepted))
    truncated["summary"][
        "conservative_historical_trial_count_lower_bound"
    ] = 6
    forged_evidence = accepted_u0_evidence(truncated)
    forged_blockers = MOD.u0_gate(
        truncated, forged_evidence, canonical, contract()
    )
    assert "u0_census_not_exact_canonical_artifact" in forged_blockers
    assert "u0_evidence_not_exact_canonical_artifact" in forged_blockers

    broadened_evidence = json.loads(json.dumps(accepted_evidence))
    broadened_evidence["historical_broker_backtest_allowed"] = True
    broadened_canonical = canonical_u0_artifact(
        accepted, broadened_evidence
    )
    assert "u0_accepted_evidence_not_approved" in MOD.u0_gate(
        accepted,
        broadened_evidence,
        broadened_canonical,
        contract(),
    )

    original_blob_hash = MOD.git_json_blob_canonical_sha256
    MOD.git_json_blob_canonical_sha256 = lambda _sha, _path: "0" * 64
    try:
        inventory_blockers = MOD.u0_gate(
            accepted,
            accepted_evidence,
            canonical,
            contract(),
        )
    finally:
        MOD.git_json_blob_canonical_sha256 = original_blob_hash
    assert "u0_source_inventory_not_current_runner_git_blob" in inventory_blockers

    wrong_source = json.loads(json.dumps(accepted))
    wrong_source["source_census_sha256"] = "0" * 64
    wrong_source_evidence = accepted_u0_evidence(wrong_source)
    wrong_source_canonical = canonical_u0_artifact(
        wrong_source, wrong_source_evidence
    )
    assert "u0_recovery_source_census_hash_mismatch" in MOD.u0_gate(
        wrong_source,
        wrong_source_evidence,
        wrong_source_canonical,
        contract(),
    )

    forged = valid_u0()
    forged_sha = "d" * 40
    forged["audit_default_branch_sha"] = forged_sha
    assert "u0_census_audit_sha_not_current_default_branch" in (
        u0_gate_with_accepted_test_default(forged)
    )


def test_u0_canonical_artifact_is_verified_from_github() -> None:
    census = valid_u0()
    evidence = accepted_u0_evidence(census)
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr(
            "github_census.json",
            json.dumps(valid_source_u0(census["audit_default_branch_sha"])),
        )
        archive.writestr("github_recovery_census.json", json.dumps(census))
        archive.writestr("u0_accepted_evidence.json", json.dumps(evidence))
    artifact_id = 287
    run_id = 2870805
    audit_sha = census["audit_default_branch_sha"]
    artifact = {
        "id": artifact_id,
        "name": "run287-u0-accepted-evidence",
        "expired": False,
        "digest": "sha256:" + "a" * 64,
        "workflow_run": {
            "id": run_id,
            "head_sha": audit_sha,
            "head_branch": "master",
        },
    }
    run = {
        "id": run_id,
        "path": ".github/workflows/run287_u0_acceptance.yml",
        "event": "workflow_dispatch",
        "head_branch": "master",
        "head_sha": audit_sha,
        "status": "completed",
        "conclusion": "success",
    }
    live_branches = [
        {"name": "master", "commit": {"sha": audit_sha}}
    ]
    live_pull_requests = [
        {
            "number": 1,
            "head": {"ref": "legacy-1", "sha": "c" * 40},
            "base": {"sha": audit_sha},
            "updated_at": "2026-08-10T00:00:00Z",
        }
    ]
    namespace_stale = False
    original = MOD.subprocess.check_output

    def fake_check_output(command, **_kwargs):
        endpoint = command[-1]
        if endpoint.endswith(f"/artifacts/{artifact_id}"):
            return json.dumps(artifact).encode("utf-8")
        if endpoint.endswith(f"/runs/{run_id}"):
            return json.dumps(run).encode("utf-8")
        if endpoint.endswith(f"/artifacts/{artifact_id}/zip"):
            return archive_buffer.getvalue()
        if endpoint.endswith("/branches?per_page=100"):
            rows = list(live_branches)
            if namespace_stale:
                rows.append(
                    {"name": "new-experiment", "commit": {"sha": "d" * 40}}
                )
            return json.dumps([rows]).encode("utf-8")
        if endpoint.endswith("/pulls?state=all&per_page=100"):
            return json.dumps([live_pull_requests]).encode("utf-8")
        raise AssertionError(f"unexpected GitHub API endpoint:{endpoint}")

    MOD.subprocess.check_output = fake_check_output
    try:
        canonical = MOD.load_canonical_u0_artifact(artifact_id, contract())
    finally:
        MOD.subprocess.check_output = original
    assert canonical["verified"] is True
    assert canonical["workflow_run_id"] == run_id
    assert MOD.canonical_sha256(canonical["census"]) == MOD.canonical_sha256(
        census
    )
    assert MOD.canonical_sha256(
        canonical["source_census"]
    ) == MOD.canonical_sha256(valid_source_u0(audit_sha))
    assert MOD.canonical_sha256(
        canonical["accepted_evidence"]
    ) == MOD.canonical_sha256(evidence)
    assert canonical["source_observed_at_utc"] == (
        valid_source_u0(audit_sha)["generated_at_utc"]
    )
    assert canonical["live_repository_namespace_sha256"] == canonical[
        "repository_namespace_sha256"
    ]

    namespace_stale = True
    MOD.subprocess.check_output = fake_check_output
    try:
        MOD.load_canonical_u0_artifact(artifact_id, contract())
    except ValueError as exc:
        assert "stale for the live repository namespace" in str(exc)
    else:
        raise AssertionError("stale U0 repository namespace was accepted")
    finally:
        MOD.subprocess.check_output = original
    namespace_stale = False

    duplicate_archive = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(duplicate_archive, "w") as archive:
            archive.writestr(
                "github_census.json",
                json.dumps(
                    valid_source_u0(census["audit_default_branch_sha"])
                ),
            )
            archive.writestr("github_census.json", json.dumps({}))
            archive.writestr("github_recovery_census.json", json.dumps(census))
            archive.writestr("u0_accepted_evidence.json", json.dumps(evidence))
    archive_buffer = duplicate_archive
    MOD.subprocess.check_output = fake_check_output
    try:
        MOD.load_canonical_u0_artifact(artifact_id, contract())
    except ValueError as exc:
        assert "missing or duplicated" in str(exc)
    else:
        raise AssertionError("non-canonical U0 artifact layout was accepted")
    finally:
        MOD.subprocess.check_output = original


def test_missing_exact_label_provenance_blocks_even_with_u0_allowed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        frame = synthetic_frame(months=18)
        frame = frame.drop(columns=["r_6m_label_end_date"])
        frame["bench_r_3m"] = np.nan
        feature_store = root / "features.parquet"
        frame.to_parquet(feature_store)
        census = root / "census.json"
        census.write_text(json.dumps(valid_u0()), encoding="utf-8")
        summary = run_with_accepted_test_u0(
            Namespace(
                contract=str(CONTRACT_PATH),
                u0_census=str(census),
                feature_store=str(feature_store),
                output_dir=str(root / "out"),
            )
        )
        joined = "|".join(summary["blockers"])
        assert "feature_store_missing_required_columns:r_6m_label_end_date" in joined
        assert summary["historical_model_fit_executed"] is False


def test_zero_weight_21d_labels_are_optional_for_monthly_selection() -> None:
    cfg = contract()
    optional_columns = [
        cfg["horizons"]["21"][key]
        for key in (
            "stock_return",
            "benchmark_return",
            "stock_label_end",
            "benchmark_label_end",
        )
    ]
    missing = synthetic_frame(months=48).drop(columns=optional_columns)
    assert not MOD.input_readiness(missing, cfg)
    prepared = MOD.prepare_frame(missing, cfg)
    predictions, audit, _ = MOD.walk_forward_predictions(prepared, cfg)
    assert not predictions.empty
    assert predictions["expected_alpha_21d"].isna().all()
    assert predictions["expected_alpha_63d"].notna().all()
    assert (
        audit.loc[audit["horizon"].eq(21), "status"]
        .eq("UNAVAILABLE_TIMING_ONLY_INSUFFICIENT_TRAINING")
        .any()
    )

    all_null = synthetic_frame(months=18)
    for column in optional_columns:
        all_null[column] = pd.NaT if column.endswith("_date") else np.nan
    assert not MOD.input_readiness(all_null, cfg)

    missing_timing_feature = synthetic_frame(months=48).drop(columns=["atr14_pct"])
    assert not MOD.input_readiness(missing_timing_feature, cfg)
    prepared_timing = MOD.prepare_frame(missing_timing_feature, cfg)
    timing_predictions, timing_audit, _ = MOD.walk_forward_predictions(
        prepared_timing, cfg
    )
    assert not timing_predictions.empty
    assert timing_predictions["entry_timing_score"].isna().all()
    assert timing_audit["status"].eq("UNAVAILABLE_TIMING_ONLY_MISSING_FEATURES").any()


def test_required_selection_features_must_be_usable() -> None:
    cfg = contract()
    unusable = synthetic_frame(months=18)
    unusable["rs_benchmark_3m"] = "not-numeric"
    blockers = MOD.input_readiness(unusable, cfg)
    assert "selection_feature_unusable:63:rs_benchmark_3m" in blockers

    latest_unusable = synthetic_frame(months=18)
    latest = latest_unusable["feature_date"].max()
    latest_unusable.loc[
        latest_unusable["feature_date"].eq(latest), "rs_benchmark_3m"
    ] = np.nan
    latest_blockers = MOD.input_readiness(latest_unusable, cfg)
    assert (
        "selection_feature_unusable_on_decision_date:63:rs_benchmark_3m"
        in latest_blockers
    )

    historical_gap = synthetic_frame(months=18)
    middle = sorted(historical_gap["feature_date"].unique())[5]
    historical_gap.loc[
        historical_gap["feature_date"].eq(middle), "rs_benchmark_3m"
    ] = np.nan
    assert (
        "selection_feature_unusable_on_decision_date:63:rs_benchmark_3m"
        in MOD.input_readiness(historical_gap, cfg)
    )


def test_walk_forward_is_exactly_purged_and_learns_expected_return() -> None:
    cfg = contract()
    raw = synthetic_frame()
    raw["future_return_leak"] = np.arange(len(raw), dtype=float)
    prepared = MOD.prepare_frame(raw, cfg)
    predictions, audit, latest_models = MOD.walk_forward_predictions(prepared, cfg)
    assert not predictions.empty
    fitted = audit[audit["status"].eq("FIT_PIT_PURGED")]
    assert not fitted.empty
    assert fitted["label_strictly_before_decision"].astype(bool).all()
    assert fitted["training_feature_on_or_before_embargo"].astype(bool).all()
    assert (
        pd.to_datetime(fitted["max_label_available_at"])
        < pd.to_datetime(fitted["decision_date"])
    ).all()
    assert (
        pd.to_datetime(fitted["max_training_feature_date"])
        <= pd.to_datetime(fitted["embargo_cutoff"])
    ).all()
    used_features = {
        feature
        for horizon in latest_models["horizons"].values()
        for feature in horizon["features"]
    }
    assert "future_return_leak" not in used_features
    assert used_features.issubset(
        {
            feature
            for horizon in MOD.HORIZONS
            for feature in cfg["features"][str(horizon)]
        }
    )

    metrics = MOD.evaluate_predictions(predictions, cfg)
    full_63 = metrics["windows"]["full"]["horizons"]["63"][
        "benchmark_excess"
    ]
    oos_63 = metrics["windows"]["oos"]["horizons"]["63"][
        "benchmark_excess"
    ]
    assert full_63["rows"] > 500
    assert full_63["mean_monthly_spearman_ic"] > 0.7
    assert full_63["top_bottom_realized_spread"] > 0.05
    assert oos_63["rows"] > 100
    assert oos_63["mean_monthly_spearman_ic"] > 0.7

    proposal = MOD.public_latest_proposal(predictions)
    assert not proposal.empty
    assert not any(column.startswith("realized_") for column in proposal.columns)
    assert not any(column.startswith("label_available_at_") for column in proposal.columns)
    assert proposal["research_only"].eq(True).all()
    assert "entry_timing_score" in proposal.columns


def test_benchmark_identity_and_forward_dates_are_fail_closed() -> None:
    cfg = contract()
    inconsistent = synthetic_frame(months=18)
    same_date = inconsistent["feature_date"].eq(inconsistent["feature_date"].iloc[0])
    first_index = inconsistent.index[same_date][0]
    inconsistent.loc[first_index, "bench_r_3m"] = 0.99
    try:
        MOD.prepare_frame(inconsistent, cfg)
    except ValueError as exc:
        assert "benchmark return is not unique" in str(exc)
    else:
        raise AssertionError("inconsistent benchmark return was accepted")

    nonforward = synthetic_frame(months=18)
    first_decision = nonforward["feature_date"].eq(nonforward.loc[0, "feature_date"])
    nonforward.loc[first_decision, "r_1m_label_end_date"] = nonforward.loc[
        first_decision, "feature_date"
    ]
    nonforward.loc[first_decision, "bench_r_1m_label_end_date"] = nonforward.loc[
        first_decision, "feature_date"
    ]
    try:
        MOD.prepare_frame(nonforward, cfg)
    except ValueError as exc:
        assert "label end is not exact NYSE horizon:21" in str(exc)
    else:
        raise AssertionError("same-day forward label was accepted")

    wrong_benchmark = synthetic_frame(months=18)
    wrong_benchmark["benchmark_identity"] = "^GSPC"
    try:
        MOD.prepare_frame(wrong_benchmark, cfg)
    except ValueError as exc:
        assert "benchmark identity provenance mismatch" in str(exc)
    else:
        raise AssertionError("a non-SPY benchmark was accepted")

    mismatched_end = synthetic_frame(months=18)
    mismatched_end.loc[0, "r_3m_label_end_date"] = (
        pd.Timestamp(mismatched_end.loc[0, "r_3m_label_end_date"])
        + pd.Timedelta(days=1)
    )
    try:
        MOD.prepare_frame(mismatched_end, cfg)
    except ValueError as exc:
        assert "stock/benchmark label end mismatch" in str(exc)
    else:
        raise AssertionError("mismatched stock/benchmark label ends were accepted")

    mixed_end = synthetic_frame(months=18)
    shifted = pd.Timestamp(mixed_end.loc[0, "r_6m_label_end_date"]) + pd.Timedelta(days=1)
    mixed_end.loc[0, "r_6m_label_end_date"] = shifted
    mixed_end.loc[0, "bench_r_6m_label_end_date"] = shifted
    try:
        MOD.prepare_frame(mixed_end, cfg)
    except ValueError as exc:
        assert (
            "mixed cross-sectional label end dates" in str(exc)
            or "benchmark label end is not unique" in str(exc)
        )
    else:
        raise AssertionError("mixed cross-sectional label ends were accepted")

    wrong_horizon = synthetic_frame(months=18)
    first_date = pd.Timestamp(wrong_horizon.loc[0, "feature_date"])
    next_session = MOD.NYSE.valid_days(
        start_date=first_date + pd.Timedelta(days=1),
        end_date=first_date + pd.Timedelta(days=10),
    ).tz_localize(None).normalize()[0]
    first_rows = wrong_horizon["feature_date"].eq(first_date)
    wrong_horizon.loc[first_rows, "r_3m_label_end_date"] = next_session
    wrong_horizon.loc[first_rows, "bench_r_3m_label_end_date"] = next_session
    try:
        MOD.prepare_frame(wrong_horizon, cfg)
    except ValueError as exc:
        assert "label end is not exact NYSE horizon:63" in str(exc)
    else:
        raise AssertionError("a non-63-session label horizon was accepted")

    partial_required = synthetic_frame(months=18)
    partial_required.loc[0, "r_3m_label_end_date"] = ""
    try:
        MOD.prepare_frame(partial_required, cfg)
    except ValueError as exc:
        assert "partial required label provenance:63" in str(exc)
    else:
        raise AssertionError("a partial required label row was accepted")

    unparseable_required = synthetic_frame(months=18)
    unparseable_required["r_6m"] = unparseable_required["r_6m"].astype(object)
    unparseable_required.loc[0, "r_6m"] = "not-a-return"
    try:
        MOD.prepare_frame(unparseable_required, cfg)
    except ValueError as exc:
        assert "unparseable required label provenance:126" in str(exc)
    else:
        raise AssertionError("an unparseable required label row was accepted")

    null_ticker = synthetic_frame(months=18)
    null_ticker.loc[0, "ticker"] = None
    try:
        MOD.prepare_frame(null_ticker, cfg)
    except ValueError as exc:
        assert "null ticker" in str(exc)
    else:
        raise AssertionError("a null ticker identity was accepted")

    blank_sector = synthetic_frame(months=18)
    blank_sector.loc[0, "sector"] = "  "
    try:
        MOD.prepare_frame(blank_sector, cfg)
    except ValueError as exc:
        assert "empty sector" in str(exc)
    else:
        raise AssertionError("a blank sector identity was accepted")


def test_21d_timing_unavailability_does_not_block_monthly_selection() -> None:
    cfg = contract()
    raw = synthetic_frame()
    raw["r_1m"] = 0.05
    prepared = MOD.prepare_frame(raw, cfg)
    predictions, audit, latest_models = MOD.walk_forward_predictions(prepared, cfg)
    assert not predictions.empty
    unavailable = audit[
        audit["status"].eq("UNAVAILABLE_TIMING_ONLY_INSUFFICIENT_TRAINING")
        & audit["horizon"].eq(21)
    ]
    assert not unavailable.empty
    assert predictions["expected_alpha_21d"].isna().all()
    assert predictions["entry_timing_score"].isna().all()
    assert predictions["expected_alpha_63d"].notna().all()
    assert predictions["expected_alpha_126d"].notna().all()
    assert latest_models["horizons"]["21"]["status"].startswith("UNAVAILABLE_TIMING_ONLY")


def test_semantic_failure_and_stale_latest_are_auditable_blocks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        census = root / "census.json"
        census.write_text(json.dumps(valid_u0()), encoding="utf-8")

        duplicate = pd.concat(
            [synthetic_frame(months=18), synthetic_frame(months=18).iloc[[0]]],
            ignore_index=True,
        )
        duplicate_store = root / "duplicate.parquet"
        duplicate.to_parquet(duplicate_store)
        duplicate_output = root / "duplicate_out"
        duplicate_summary = run_with_accepted_test_u0(
            Namespace(
                contract=str(CONTRACT_PATH),
                u0_census=str(census),
                feature_store=str(duplicate_store),
                output_dir=str(duplicate_output),
            )
        )
        assert duplicate_summary["status"] == MOD.BLOCKED_STATUS
        assert "feature_store_semantic_validation_failed" in "|".join(
            duplicate_summary["blockers"]
        )
        assert (duplicate_output / "summary.json").is_file()
        assert (duplicate_output / "source_manifest.json").is_file()

        valid_store = root / "valid.parquet"
        synthetic_frame(months=48).to_parquet(valid_store)
        stale_output = root / "stale_out"
        original = MOD.walk_forward_predictions

        def stale_predictions(prepared, cfg):
            predictions, audit, models = original(prepared, cfg)
            latest = predictions["feature_date"].max()
            return predictions[predictions["feature_date"].lt(latest)], audit, models

        MOD.walk_forward_predictions = stale_predictions
        try:
            stale_summary = run_with_accepted_test_u0(
                Namespace(
                    contract=str(CONTRACT_PATH),
                    u0_census=str(census),
                    feature_store=str(valid_store),
                    output_dir=str(stale_output),
                )
            )
        finally:
            MOD.walk_forward_predictions = original
        assert stale_summary["status"] == MOD.BLOCKED_STATUS
        assert "latest_input_decision_not_scored" in "|".join(stale_summary["blockers"])
        assert pd.read_csv(stale_output / "latest_expected_return_proposal.csv").empty


def test_undersized_latest_sectors_are_not_scored() -> None:
    cfg = contract()
    raw = synthetic_frame()
    latest = raw["feature_date"].max()
    latest_index = raw.index[raw["feature_date"].eq(latest)]
    raw.loc[latest_index[:4], "sector"] = "TINY"
    prepared = MOD.prepare_frame(raw, cfg)
    predictions, audit, _ = MOD.walk_forward_predictions(prepared, cfg)
    latest_predictions = predictions[predictions["feature_date"].eq(latest)]
    assert not latest_predictions.empty
    assert "TINY" not in set(latest_predictions["sector"])
    source_latest = raw[raw["feature_date"].eq(latest)]
    sector_sizes = source_latest.groupby("sector")["ticker"].size()
    assert latest_predictions["sector"].map(sector_sizes).ge(5).all()
    latest_audit = audit[
        audit["decision_date"].eq(latest)
        & audit["horizon"].isin([63, 126])
    ]
    assert latest_audit["scoring_sector_ineligible_rows"].gt(0).all()


def test_unreadable_u0_census_writes_blocked_packet() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        feature_store = root / "features.parquet"
        synthetic_frame(months=18).to_parquet(feature_store)
        census = root / "census.json"
        census.write_text('{"duplicate": 1, "duplicate": 2}', encoding="utf-8")
        output = root / "out"
        summary = MOD.run(
            Namespace(
                contract=str(CONTRACT_PATH),
                u0_census=str(census),
                feature_store=str(feature_store),
                output_dir=str(output),
            )
        )
        assert summary["status"] == MOD.BLOCKED_STATUS
        assert "u0_census_unreadable:ValueError" in summary["blockers"]
        assert (output / "summary.json").is_file()
        assert (output / "source_manifest.json").is_file()


def test_allowed_synthetic_run_writes_only_research_outputs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        feature_store = root / "features.parquet"
        synthetic_frame(months=48).to_parquet(feature_store)
        census = root / "census.json"
        census.write_text(json.dumps(valid_u0()), encoding="utf-8")
        output = root / "out"
        summary = run_with_accepted_test_u0(
            Namespace(
                contract=str(CONTRACT_PATH),
                u0_census=str(census),
                feature_store=str(feature_store),
                output_dir=str(output),
            )
        )
        assert summary["status"] == MOD.READY_STATUS
        assert summary["historical_model_fit_executed"] is True
        assert summary[
            "conservative_historical_trial_count_lower_bound"
        ] == 5
        assert summary["historical_backtest_executed"] is False
        assert summary["target_books_written"] is False
        assert summary["orders_generated"] is False
        assert not (output / "main_target.csv").exists()
        assert not (output / "concentrated_target.csv").exists()
        manifest = json.loads(
            (output / "source_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["historical_fit_executed"] is True
        assert manifest[
            "conservative_historical_trial_count_lower_bound"
        ] == 5
        assert manifest["historical_backtest_executed"] is False
        metrics = json.loads(
            (output / "expected_return_metrics.json").read_text(
                encoding="utf-8"
            )
        )
        assert metrics["multiple_testing_context"][
            "conservative_historical_trial_count_lower_bound"
        ] == 5
        proposal = pd.read_csv(output / "latest_expected_return_proposal.csv")
        assert not any(column.startswith("realized_") for column in proposal.columns)
        assert "target_weight" not in proposal.columns


def test_source_contains_no_broker_or_promotion_execution() -> None:
    source = (ROOT / "tools" / "run_run287_expected_return_challenger.py").read_text(
        encoding="utf-8"
    )
    assert "run_broker_ledger_replay" not in source
    assert "target_books_written\": True" not in source
    assert "automatic_promotion_allowed\": True" not in source


def test_feature_store_builder_materializes_spy_provenance() -> None:
    from r1000_config import EngineConfig
    import r1000_pipeline as pipeline

    cfg = EngineConfig()
    cfg.benchmark_history_source = "yfinance"
    cfg.benchmark_ticker = "SPY"
    decision = pd.Timestamp("2022-01-31")
    sessions = MOD.NYSE.valid_days(
        start_date=decision - pd.Timedelta(days=10),
        end_date=decision + pd.Timedelta(days=1200),
    ).tz_localize(None).normalize()
    close = pd.Series(
        np.linspace(100.0, 200.0, len(sessions)), index=sessions
    )
    original = pipeline.load_benchmark_price_series
    pipeline.load_benchmark_price_series = lambda _cfg, _paths: close
    try:
        frame = pipeline.attach_benchmark_forward_returns(
            cfg, {}, pd.DataFrame({"rebalance_date": [decision]})
        )
    finally:
        pipeline.load_benchmark_price_series = original
    assert frame.loc[0, "benchmark_identity"] == "SPY"
    assert frame.loc[0, "benchmark_source"] == "YF:SPY"
    assert pd.Timestamp(frame.loc[0, "bench_r_3m_label_end_date"]) == (
        sessions[sessions > decision][cfg.target_3m_days]
    )


def test_canonical_u0_workflow_is_research_only() -> None:
    path = ROOT / ".github" / "workflows" / "run287_u0_acceptance.yml"
    source = path.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    assert "refs/heads/master" in source
    assert "run287-u0-accepted-evidence" in source
    assert "build_run287_u0_v3_acceptance.py" in source
    assert "github_recovery_census.json" in source
    assert "+refs/pull/*/head:refs/run287-u0-pull-heads/*" in source
    assert "run287-u0-v2-acceptance" not in source
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in source
    diagnostic = "name: run287-u0-census-diagnostic"
    accepted = "name: run287-u0-accepted-evidence"
    gate = "- name: Require complete U0 and create acceptance envelope"
    assert diagnostic in source
    assert "github_census_summary.json" in source
    assert "experiment_candidates.csv" in source
    assert source.index(diagnostic) < source.index(gate) < source.index(accepted)
    assert source.count(accepted) == 1
    forbidden = (
        "run_broker_ledger_replay",
        "main_target.csv",
        "concentrated_target.csv",
        "git push",
        "production_or_live_trading_enabled: true",
    )
    assert not any(token in source for token in forbidden)




def _er_v2_h1_fixture():
    cfg = MOD.read_json(ROOT / "docs" / "run287_expected_return_v2_contract.json")
    decision = "2026-10-19T15:00:00Z"
    entry_day = pd.Timestamp("2025-09-15")
    end = MOD.expected_nyse_label_ends(pd.Series([entry_day]), 252).iloc[0]
    close = MOD.NYSE.schedule(start_date=end, end_date=end)["market_close"].iloc[0]
    row = {
        "asset_id": "US:EXAMPLE-SECURITY", "issuer_id": "CIK:0000000001",
        "feature_date": entry_day, "benchmark_identity": "SPY",
        "benchmark_source": "YF:SPY", "security_lifecycle_status": "ACTIVE",
        "stock_return_basis": "TOTAL_RETURN", "benchmark_return_basis": "TOTAL_RETURN",
        "r_12m": 0.12, "bench_r_12m": 0.06,
        "r_12m_label_end_date": end, "bench_r_12m_label_end_date": end,
        "label_12m_available_at": (close + pd.Timedelta(seconds=1)).isoformat(),
    }
    return cfg, row, decision


@patch.object(MOD, "_v2_h1_observed_at", return_value=pd.Timestamp("2026-12-01T00:00:00Z"))
def test_er_v2_h1_252_contract_and_labels(_clock) -> None:
    """V2 H1 is label-only: no model, ER, A5, or historical PIT authority."""
    def check(value, name):
        # Still executable under python -O; no assert-based safety guards.
        if not value:
            raise AssertionError(name)
    cfg = MOD.read_json(ROOT / "docs" / "run287_expected_return_v2_contract.json")
    check(MOD.validate_v2_h1_252_contract(cfg) is cfg, "V2 contract acceptance")
    check(MOD.HORIZONS == (21, 63, 126), "V1 horizon preservation")
    check(cfg["purge_and_windows"]["embargo_nyse_sessions"] == 252, "252 embargo")
    check(cfg["safety"]["model_fit_allowed"] is False, "V2 model fit disabled")
    check(cfg["safety"]["validated_er_allowed"] is False, "V2 validated ER disabled")

    for key, value in (("version", "IMPROPER"),
                       ("purge_and_windows", {"embargo_nyse_sessions": 126})):
        changed = json.loads(json.dumps(cfg))
        changed[key] = value
        try:
            MOD.validate_v2_h1_252_contract(changed)
        except ValueError:
            pass
        else:
            raise AssertionError("a modified V2 H1 contract passed")

    _, row, decision = _er_v2_h1_fixture()
    entry_day = row["feature_date"]
    end = row["r_12m_label_end_date"]
    close = MOD.NYSE.schedule(start_date=end, end_date=end)["market_close"].iloc[0]
    ok = MOD.audit_v2_h1_252_labels(pd.DataFrame([row]), cfg, decision_at=decision)
    check(ok["cohort_denominator"] == 1, "positive denominator")
    check(ok["precheck_consistent_rows"] == 1, "positive precheck")
    check(ok["records"][0]["observed_excess_return"] == 0.06, "excess arithmetic")
    check(ok["records"][0]["net_expected_return_12m"] is None, "net ER null")
    check(ok["model_fit_allowed"] is False and ok["A5_eligible_input"] is False, "no economic authority")

    cases = (
        ({"bench_r_12m_label_end_date": end + pd.Timedelta(days=1)}, "BENCHMARK_LABEL_END_NOT_EXACT_252"),
        ({"r_12m_label_end_date": None}, "STOCK_LABEL_END_MISSING"),
        ({"r_12m": None}, "STOCK_RETURN_INVALID_OR_MISSING"),
        ({"bench_r_12m": float("nan")}, "BENCHMARK_RETURN_INVALID_OR_MISSING"),
        ({"r_12m": True}, "STOCK_RETURN_INVALID_OR_MISSING"),
        ({"r_12m": -1.1}, "STOCK_RETURN_INVALID_OR_MISSING"),
        ({"r_12m": "0.14"}, "STOCK_RETURN_INVALID_OR_MISSING"),
        ({"benchmark_identity": "QQQ"}, "BENCHMARK_IDENTITY_MISMATCH"),
        ({"benchmark_source": "INDEX:SP500"}, "BENCHMARK_SOURCE_MISMATCH"),
        ({"benchmark_return_basis": "PROVIDER_ADJUSTED_CLOSE_PROXY"}, "RETURN_BASIS_MISMATCH_OR_UNKNOWN"),
        ({"security_lifecycle_status": "DELISTED"}, "TERMINAL_PROCEEDS_A1_ADMISSION_REQUIRED"),
        ({"security_lifecycle_status": []}, "LIFECYCLE_UNKNOWN"),
        ({"security_lifecycle_status": {"ACTIVE": True}}, "LIFECYCLE_UNKNOWN"),
        ({"label_12m_available_at": "2026-10-19"}, "LABEL_AVAILABILITY_MISSING_OR_UNVERIFIED_CLOCK"),
        ({"label_12m_available_at": decision}, "LABEL_NOT_MATURE_STRICTLY_BEFORE_DECISION"),
        ({"label_12m_available_at": (close - pd.Timedelta(seconds=1)).isoformat()},
         "LABEL_AVAILABLE_BEFORE_ACTUAL_NYSE_CLOSE"),
        ({"feature_date": pd.Timestamp("2026-04-01")}, "FEATURE_WITHIN_252_SESSION_EMBARGO"),
    )
    for mutation, expected_blocker in cases:
        candidate = row.copy(); candidate.update(mutation)
        result = MOD.audit_v2_h1_252_labels(pd.DataFrame([candidate]), cfg, decision_at=decision)
        check(result["cohort_denominator"] == 1, "negative case denominator")
        check(result["precheck_consistent_rows"] == 0, "negative case refused")
        check(expected_blocker in result["records"][0]["blockers"], repr((mutation, result)))
        check(result["records"][0]["net_expected_return_12m"] is None, "blocked net ER null")

    both = pd.DataFrame([row,row.copy()])
    try:
        MOD.audit_v2_h1_252_labels(both,cfg,decision_at=decision)
    except ValueError as exc:
        check("duplicate_asset_decision" in str(exc), "duplicate refusal")
    else:
        raise AssertionError("duplicate security/decision accepted")

    # Exact NYSE calendar includes U.S. holidays, early closures and leap years.
    for date in ("2025-04-17", "2025-11-28", "2025-10-20"):
        expected = MOD.expected_nyse_label_ends(pd.Series([pd.Timestamp(date)]),252).iloc[0]
        sessions = MOD.NYSE.valid_days(
            start_date=date, end_date=pd.Timestamp(date)+pd.Timedelta(days=770)
        ).tz_localize(None).normalize()
        future = sessions[sessions > pd.Timestamp(date)]
        check(expected == future[252], "exact NYSE 252 price interval")
    check(MOD.nyse_embargo_cutoffs([pd.Timestamp("2026-10-19")],252)[pd.Timestamp("2026-10-19")] < pd.Timestamp("2026-10-19"), "embargo cutoff")

    # UTC midnight must never advance a U.S. NYSE embargo clock.
    for when, session in (
        ("2026-10-19T23:30:00Z", "2026-10-19"),
        ("2026-10-20T00:30:00Z", "2026-10-19"),
        ("2026-10-20T13:00:00Z", "2026-10-19"),
        ("2026-10-20T21:00:00Z", "2026-10-20"),
        ("2026-10-18T17:00:00Z", "2026-10-16"),
        ("2026-11-29T17:00:00Z", "2026-11-27"),
    ):
        boundary = MOD.audit_v2_h1_252_labels(pd.DataFrame([row]), cfg, decision_at=when)
        check(boundary["decision_completed_nyse_session"] == session,
              "NY-clock session mismatch: " + when)
    for before, after in (
        ("2026-10-19T23:30:00Z", "2026-10-20T00:30:00Z"),
        ("2026-10-20T13:00:00Z", "2026-10-20T21:00:00Z"),
    ):
        first = MOD.audit_v2_h1_252_labels(pd.DataFrame([row]), cfg, decision_at=before)
        second = MOD.audit_v2_h1_252_labels(pd.DataFrame([row]), cfg, decision_at=after)
        if first["decision_completed_nyse_session"] == second["decision_completed_nyse_session"]:
            check(first["embargo_cutoff_nyse_session"] == second["embargo_cutoff_nyse_session"],
                  "same U.S. session changed 252 embargo")


def _er_v2_h1_check(value, reason):
    if not value:
        raise AssertionError(reason)


def test_er_v2_h1_benchmark_cohort_conflicts() -> None:
    cfg, row, decision = _er_v2_h1_fixture()
    second = dict(row, asset_id="US:OTHER-SECURITY", issuer_id="CIK:0000000002")
    with patch.object(MOD, "_v2_h1_observed_at", return_value=pd.Timestamp("2026-10-20T18:00:00Z")):
        equal = MOD.audit_v2_h1_252_labels(pd.DataFrame([row, second]), cfg, decision_at=decision)
        _er_v2_h1_check(equal["precheck_consistent_rows"] == 2, "consistent cohort accepted")
        conflicting = dict(second, bench_r_12m=0.07)
        for supplied in ([row, conflicting], [conflicting, row],
                         [row, dict(conflicting, security_lifecycle_status="DELISTED")]):
            result = MOD.audit_v2_h1_252_labels(pd.DataFrame(supplied), cfg, decision_at=decision)
            _er_v2_h1_check(result["cohort_denominator"] == 2, "conflicting cohort rows retained")
            _er_v2_h1_check(result["precheck_consistent_rows"] == 0, "conflicting cohort rejected")
            for record in result["records"]:
                _er_v2_h1_check("BENCHMARK_RETURN_CONFLICT_FOR_FEATURE_DATE" in record["blockers"], "SPY conflict recorded on every affected row")
                _er_v2_h1_check(record["observed_spy_return"] is None, "conflicted SPY value remains null")
                _er_v2_h1_check(record["observed_excess_return"] is None, "conflicted excess return remains null")
        other_date = dict(second, feature_date=pd.Timestamp("2025-09-12"), bench_r_12m=0.07)
        other_end = MOD.expected_nyse_label_ends(pd.Series([other_date["feature_date"]]), 252).iloc[0]
        other_date.update(r_12m_label_end_date=other_end, bench_r_12m_label_end_date=other_end,
                         label_12m_available_at=row["label_12m_available_at"])
        independent = MOD.audit_v2_h1_252_labels(pd.DataFrame([row, other_date]), cfg, decision_at=decision)
        _er_v2_h1_check(independent["precheck_consistent_rows"] == 2, "different feature dates remain independent")


def test_er_v2_h1_noncanonical_identities() -> None:
    cfg, row, decision = _er_v2_h1_fixture()
    for field in ("asset_id", "issuer_id"):
        for value in (row[field] + " ", " " + row[field], row[field] + "\n",
                      row[field] + "\t", "US:bad identity", "US:\u200bID", "/ID", "a" * 201,
                      "", None, [], {}):
            try:
                MOD.audit_v2_h1_252_labels(pd.DataFrame([row, dict(row, **{field: value})]),
                                           cfg, decision_at=decision)
            except ValueError as exc:
                _er_v2_h1_check("noncanonical_security_identity" in str(exc), "identity rejected before deduplication")
            else:
                raise AssertionError("noncanonical " + field + " accepted: " + repr(value))


def test_er_v2_h1_decision_bounded_by_observed_clock() -> None:
    cfg, row, _ = _er_v2_h1_fixture()
    observed = pd.Timestamp("2026-10-20T18:00:00Z")
    with patch.object(MOD, "_v2_h1_observed_at", return_value=observed) as clock:
        result = MOD.audit_v2_h1_252_labels(pd.DataFrame([row]), cfg,
                                           decision_at="2026-10-21T03:00:00+09:00")
        _er_v2_h1_check(result["precheck_consistent_rows"] == 1, "decision equal to observation accepted")
        _er_v2_h1_check(result["observed_at"] == observed.isoformat(), "receipt uses runtime UTC snapshot")
        _er_v2_h1_check(clock.call_count == 1, "runtime clock sampled once")
    for future in ("2026-10-20T18:00:00.000001Z", "2030-10-20T18:00:00Z"):
        with patch.object(MOD, "_v2_h1_observed_at", return_value=observed):
            try:
                # A claimed availability before a fake future decision is still future evidence.
                MOD.audit_v2_h1_252_labels(pd.DataFrame([dict(row,
                    label_12m_available_at="2026-10-20T18:00:00.000001Z")]),
                    cfg, decision_at=future)
            except ValueError as exc:
                _er_v2_h1_check(str(exc) == "v2_h1_future_decision", "future decision rejected before labels")
            else:
                raise AssertionError("caller-supplied future decision accepted")


def main() -> int:
    test_contract_is_fixed_and_leakage_features_are_rejected()
    test_u0_gate_blocks_model_fit_and_all_mutations()
    test_u0_canonical_artifact_is_verified_from_github()
    test_missing_exact_label_provenance_blocks_even_with_u0_allowed()
    test_zero_weight_21d_labels_are_optional_for_monthly_selection()
    test_required_selection_features_must_be_usable()
    test_walk_forward_is_exactly_purged_and_learns_expected_return()
    test_benchmark_identity_and_forward_dates_are_fail_closed()
    test_21d_timing_unavailability_does_not_block_monthly_selection()
    test_semantic_failure_and_stale_latest_are_auditable_blocks()
    test_undersized_latest_sectors_are_not_scored()
    test_unreadable_u0_census_writes_blocked_packet()
    test_allowed_synthetic_run_writes_only_research_outputs()
    test_source_contains_no_broker_or_promotion_execution()
    test_feature_store_builder_materializes_spy_provenance()
    test_canonical_u0_workflow_is_research_only()
    test_er_v2_h1_252_contract_and_labels()
    test_er_v2_h1_benchmark_cohort_conflicts()
    test_er_v2_h1_noncanonical_identities()
    test_er_v2_h1_decision_bounded_by_observed_clock()
    print("run287_expected_return_challenger_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

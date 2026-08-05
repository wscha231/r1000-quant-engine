#!/usr/bin/env python3
"""Smoke tests for the PIT-purged Run287 expected-return challenger."""
from __future__ import annotations

import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

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
    branches = [
        {
            "name": "master",
            "head_sha": audit_sha,
            "ancestry": "IDENTICAL_TO_AUDIT_HEAD",
        }
    ]
    pull_requests = [{"number": 1, "head_sha": "c" * 40}]
    return {
        "schema_version": "run287-u0-v2-github-census-v1",
        "repository": MOD.REPOSITORY,
        "audit_default_branch": "master",
        "audit_default_branch_sha": audit_sha,
        "source_contract": {
            "branch_payload_sha256": "a" * 64,
            "pull_request_payload_sha256": "b" * 64,
            "metadata_only": True,
            "fullrun_executed": False,
            "production_or_live_mutated": False,
            "champion_changed": False,
        },
        "branches": branches,
        "pull_requests": pull_requests,
        "summary": {
            "historical_experiment_census_complete": True,
            "historical_challenger_allowed": True,
        },
        "promotion_blockers": [],
    }


def accepted_u0_evidence(census: dict) -> dict:
    return {
        "schema_version": "run287-u0-accepted-evidence-v1",
        "repository": MOD.REPOSITORY,
        "workflow_identity": "run287-u0-v2-acceptance",
        "audit_default_branch_sha": census["audit_default_branch_sha"],
        "census_sha256": MOD.canonical_sha256(census),
        "source_contract_sha256": MOD.canonical_sha256(
            census["source_contract"]
        ),
        "historical_experiment_census_complete": True,
        "historical_challenger_allowed": True,
        "promotion_blockers": [],
    }


def run_with_accepted_test_u0(args: Namespace) -> dict:
    census = MOD.read_json(Path(args.u0_census))
    audit_sha = str(census["audit_default_branch_sha"])
    evidence_path = Path(args.u0_census).with_name("accepted_evidence.json")
    evidence_path.write_text(
        json.dumps(accepted_u0_evidence(census)), encoding="utf-8"
    )
    args.u0_accepted_evidence = str(evidence_path)
    original_default = MOD.git_default_branch_sha
    original_ancestor = MOD.git_is_ancestor
    MOD.git_default_branch_sha = lambda: audit_sha
    MOD.git_is_ancestor = lambda ancestor, descendant: (
        ancestor == audit_sha and descendant == MOD.git_head()
    )
    try:
        return MOD.run(args)
    finally:
        MOD.git_default_branch_sha = original_default
        MOD.git_is_ancestor = original_ancestor


def u0_gate_with_accepted_test_default(census: dict) -> list[str]:
    accepted_sha = str(valid_u0()["audit_default_branch_sha"])
    original_default = MOD.git_default_branch_sha
    original_ancestor = MOD.git_is_ancestor
    MOD.git_default_branch_sha = lambda: accepted_sha
    MOD.git_is_ancestor = lambda ancestor, descendant: (
        ancestor == accepted_sha and descendant == MOD.git_head()
    )
    try:
        return MOD.u0_gate(census, accepted_u0_evidence(census), contract())
    finally:
        MOD.git_default_branch_sha = original_default
        MOD.git_is_ancestor = original_ancestor

def blocked_u0() -> dict:
    return {
        "schema_version": "run287-u0-v2-github-census-v1",
        "summary": {
            "historical_experiment_census_complete": False,
            "historical_challenger_allowed": False,
        },
        "promotion_blockers": ["unmapped_trials"],
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
                    "schema_version": "run287-u0-accepted-evidence-v1",
                    "repository": MOD.REPOSITORY,
                    "workflow_identity": "run287-u0-v2-acceptance",
                    "audit_default_branch_sha": "",
                    "census_sha256": MOD.canonical_sha256(census_payload),
                    "source_contract_sha256": MOD.canonical_sha256(None),
                    "historical_experiment_census_complete": False,
                    "historical_challenger_allowed": False,
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
        assert "u0_historical_challenger_not_allowed" in summary["blockers"]
        assert summary["historical_model_fit_executed"] is False
        assert summary["historical_backtest_executed"] is False
        assert summary["target_books_written"] is False
        assert summary["orders_generated"] is False
        assert summary["portfolio_or_ledger_mutated"] is False

    assert "u0_accepted_evidence_not_an_object" in MOD.u0_gate(
        valid_u0(), None, contract()
    )
    accepted = valid_u0()
    accepted_evidence = accepted_u0_evidence(accepted)
    truncated = json.loads(json.dumps(accepted))
    truncated["pull_requests"] = []
    assert "u0_census_not_exact_accepted_artifact" in MOD.u0_gate(
        truncated, accepted_evidence, contract()
    )
    forged = valid_u0()
    forged_sha = "d" * 40
    forged["audit_default_branch_sha"] = forged_sha
    forged["branches"][0]["head_sha"] = forged_sha
    assert "u0_census_audit_sha_not_current_default_branch" in (
        u0_gate_with_accepted_test_default(forged)
    )


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
        assert summary["historical_backtest_executed"] is False
        assert summary["target_books_written"] is False
        assert summary["orders_generated"] is False
        assert not (output / "main_target.csv").exists()
        assert not (output / "concentrated_target.csv").exists()
        manifest = json.loads(
            (output / "source_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["historical_fit_executed"] is True
        assert manifest["historical_backtest_executed"] is False
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


def main() -> int:
    test_contract_is_fixed_and_leakage_features_are_rejected()
    test_u0_gate_blocks_model_fit_and_all_mutations()
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
    print("run287_expected_return_challenger_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

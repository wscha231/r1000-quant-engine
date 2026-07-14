#!/usr/bin/env python3
"""Verify the complete Run287 current cross-section without scoring it.

The verifier consumes only hash-pinned append-only artifacts.  It checks the
decision-eligible ticker set, terminal/non-equity exclusions, 238-column frozen
model order, raw-missing to scaled-zero neutrality, finite scaled input,
accepted-time/date bounds, technical/current-row readiness, and the explicit
corporate-action quarantine.  Passing this gate does not score, rank, select,
backtest, run fullrun, change target books, or authorize production/live use.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import build_run287_feature_frame_pilot as feature_builder  # noqa: E402
from tools import stage_run287_price_batch as checkpoint  # noqa: E402
from r1000_config import CORE_FUNDAMENTAL_MINIMUM_FIELDS  # noqa: E402


SCHEMA_VERSION = "run287-complete-current-cross-section-verifier-v1"


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return ""


def split_tickers(value: str) -> set[str]:
    return {
        item.upper().strip()
        for item in str(value or "").replace(";", ",").split(",")
        if item.strip()
    }


def split_values(value: str) -> set[str]:
    return {
        item.strip()
        for item in str(value or "").replace(";", ",").split(",")
        if item.strip()
    }


def expected_input(path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    audit = checkpoint.fingerprint(path)
    expected = str(expected_sha256 or "").lower().strip()
    audit.update(
        {
            "label": label,
            "expected_sha256": expected or None,
            "hash_matches": bool(
                expected and str(audit.get("sha256") or "").lower() == expected
            ),
        }
    )
    return audit


def manifest_record(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    section: str,
    name: str,
) -> tuple[Path, dict[str, Any]]:
    record = (manifest.get(section) or {}).get(name) or {}
    return checkpoint.verify_record(record, manifest_path, label=name)


def boolish(value: Any) -> bool:
    return checkpoint.boolish(value)


def explicitly_false(series: pd.Series) -> pd.Series:
    """Distinguish a declared false value from a legacy missing field."""

    normalized = series.astype(str).str.strip().str.lower()
    return normalized.isin({"0", "false", "no", "n"})


def normalize_tickers(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    if "ticker" in output.columns:
        output["ticker"] = output["ticker"].astype(str).str.upper().str.strip()
    return output


def source_files_unchanged(input_audits: Mapping[str, Mapping[str, Any]]) -> bool:
    return all(
        checkpoint.fingerprint(Path(str(audit.get("path") or ""))).get("sha256")
        == audit.get("sha256")
        for audit in input_audits.values()
        if audit.get("path") and audit.get("exists")
    )


def blocked_payload(
    output_dir: Path,
    *,
    failures: list[str],
    input_audits: Mapping[str, Any],
    started: float,
    valuation_date: str,
) -> dict[str, Any]:
    unchanged = source_files_unchanged(input_audits)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED_COMPLETE_CURRENT_CROSS_SECTION_VERIFICATION",
        "contract_failures": failures,
        "blockers": failures,
        "valuation_price_cutoff_date": valuation_date,
        "research_only": True,
        "complete_cross_section_verification_passed": False,
        "current_decision_data_complete": False,
        "research_model_scoring_prerequisite_passed": False,
        "decision_ranking_allowed": False,
        "model_scoring_executed": False,
        "selector_executed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_requests_executed": 0,
        "source_inputs_mutated": not unchanged,
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "source_inputs": dict(input_audits),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {
            "git_head": git_head(),
            "builder": checkpoint.fingerprint(Path(__file__)),
        },
    }
    checkpoint.write_json(output_dir / "manifest.json", payload)
    return payload


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = checkpoint.repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"append-only output already exists: {output_dir}")
    output_dir.mkdir(parents=True)

    valuation_date = checkpoint.clean_date(args.valuation_date)
    expected_terminals = split_tickers(args.expected_terminal_tickers)
    expected_non_equities = split_tickers(args.expected_non_equity_tickers)
    expected_actions = split_tickers(args.expected_corporate_action_tickers)
    expected_all_missing = split_values(args.expected_all_missing_features)
    feature_path = checkpoint.repo_path(args.feature_manifest)
    technical_path = checkpoint.repo_path(args.technical_manifest)
    input_audits = {
        "feature_manifest": expected_input(
            feature_path, args.expected_feature_sha256, "feature_manifest"
        ),
        "technical_manifest": expected_input(
            technical_path, args.expected_technical_sha256, "technical_manifest"
        ),
    }
    failures = [
        f"input_hash_mismatch:{name}"
        for name, audit in input_audits.items()
        if audit.get("hash_matches") is not True
    ]
    if not valuation_date:
        failures.append("valuation_date_invalid")
    if not expected_actions:
        failures.append("corporate_action_ticker_set_empty")
    if expected_actions & (expected_terminals | expected_non_equities):
        failures.append("corporate_action_exclusion_set_overlap")
    if failures:
        return blocked_payload(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=valuation_date,
        )

    feature = checkpoint.read_json(feature_path)
    technical = checkpoint.read_json(technical_path)
    relation = (feature.get("source_inputs") or {}).get("technical_manifest") or {}
    if str(relation.get("sha256") or "") != input_audits["technical_manifest"].get(
        "sha256"
    ):
        failures.append("feature_technical_manifest_relation_mismatch")

    record_specs = [
        ("feature_frame", feature_path, feature, "outputs", "pilot_feature_frame"),
        (
            "selection_context",
            feature_path,
            feature,
            "outputs",
            "pilot_selection_context",
        ),
        ("scaled_input", feature_path, feature, "outputs", "pilot_scaled_model_input"),
        ("feature_provenance", feature_path, feature, "outputs", "model_feature_provenance"),
        ("feature_coverage", feature_path, feature, "outputs", "ticker_feature_coverage"),
        ("technical_latest", technical_path, technical, "outputs", "latest_technical_features"),
        ("technical_audit", technical_path, technical, "outputs", "ticker_audit"),
        (
            "corporate_action_audit",
            technical_path,
            technical,
            "outputs",
            "corporate_action_recovery_audit",
        ),
        (
            "official_sec_document",
            technical_path,
            technical,
            "outputs",
            "official_sec_document",
        ),
        ("preflight_manifest", feature_path, feature, "source_inputs", "preflight_manifest"),
        ("model_meta", feature_path, feature, "source_inputs", "model_meta"),
    ]
    verified_paths: dict[str, Path] = {}
    for label, owner_path, owner, section, name in record_specs:
        path, audit = manifest_record(owner_path, owner, section, name)
        verified_paths[label] = path
        input_audits[label] = audit
        if audit.get("hash_matches") is not True:
            failures.append(f"input_hash_mismatch:{label}")

    if failures:
        return blocked_payload(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=valuation_date,
        )

    preflight_path = verified_paths["preflight_manifest"]
    preflight = checkpoint.read_json(preflight_path)
    for label, section, name in (
        ("universe_snapshot", "source_inputs", "universe_snapshot"),
        ("refresh_batches", "outputs", "refresh_batches"),
    ):
        path, audit = manifest_record(preflight_path, preflight, section, name)
        verified_paths[label] = path
        input_audits[label] = audit
        if audit.get("hash_matches") is not True:
            failures.append(f"input_hash_mismatch:{label}")

    feature_checks = {
        "assembled_status": feature.get("status")
        == "CURRENT_CROSS_SECTION_ASSEMBLED_VERIFICATION_REQUIRED",
        "assembled_flag": feature.get("full_current_cross_section_assembled") is True,
        "not_preverified": feature.get("complete_cross_section_verification_passed")
        is False,
        "no_ranking": feature.get("decision_ranking_allowed") is False,
        "no_model_scoring": feature.get("model_scoring_executed") is False,
        "no_selector": feature.get("selector_executed") is False,
        "no_backtest": feature.get("backtest_executed") is False,
        "no_fullrun": feature.get("fullrun_executed") is False,
        "zero_network": int(feature.get("network_requests_executed") or 0) == 0,
        "no_mutation": feature.get("source_inputs_mutated") is False,
        "source_immutable": (feature.get("source_immutability") or {}).get(
            "all_verified_files_unchanged"
        )
        is True,
    }
    technical_checks = {
        "ready_status": technical.get("status")
        == "TECHNICAL_PARITY_READY_MACRO_FUNDAMENTAL_BLOCKED",
        "complete_context": technical.get("current_cross_section_complete") is True,
        "recovery_ready": technical.get("corporate_action_recovery_ready") is True,
        "quarantine": technical.get("corporate_action_quarantine") is True,
        "frozen_parity_not_reclassified": technical.get(
            "frozen_parity_reclassified_as_pass"
        )
        is False,
        "network_contract": feature_builder.technical_network_contract(technical),
        "no_ranking": technical.get("decision_ranking_allowed") is False,
        "no_selector": technical.get("selector_executed") is False,
        "no_backtest": technical.get("backtest_executed") is False,
        "no_fullrun": technical.get("fullrun_executed") is False,
        "no_mutation": technical.get("source_inputs_mutated") is False,
    }
    preflight_checks = {
        "blocked_bounded_status": preflight.get("status")
        == "BLOCKED_BOUNDED_DECISION_REFRESH",
        "no_quick_rescore": preflight.get("quick_rescore_dispatched") is False,
        "no_target_book_mutation": preflight.get("target_books_mutated") is False,
        "zero_network": int(preflight.get("network_requests_executed") or 0) == 0,
        "no_production": preflight.get("production_activation_allowed") is False,
        "no_live_trading": preflight.get("live_trading_enabled") is False,
        "no_fullrun": preflight.get("fullrun_executed") is False,
        "no_mutation": preflight.get("source_inputs_mutated") is False,
    }
    failures.extend(
        f"feature_contract:{name}" for name, passed in feature_checks.items() if not passed
    )
    failures.extend(
        f"technical_contract:{name}"
        for name, passed in technical_checks.items()
        if not passed
    )
    failures.extend(
        f"preflight_contract:{name}"
        for name, passed in preflight_checks.items()
        if not passed
    )

    manifest_dates = {
        checkpoint.clean_date(feature.get("valuation_price_cutoff_date")),
        checkpoint.clean_date(technical.get("valuation_price_cutoff_date")),
        checkpoint.clean_date(preflight.get("decision_date")),
        valuation_date,
    }
    if manifest_dates != {valuation_date}:
        failures.append("valuation_date_mismatch:" + ",".join(sorted(manifest_dates)))
    decision_time = pd.to_datetime(
        feature.get("decision_time_utc"), errors="coerce", utc=True
    )
    available_from = pd.to_datetime(
        feature.get("feature_available_from"), errors="coerce", utc=True
    )
    if (
        pd.isna(decision_time)
        or pd.isna(available_from)
        or available_from > decision_time
    ):
        failures.append("feature_availability_after_decision")

    if failures:
        return blocked_payload(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=valuation_date,
        )

    feature_frame = normalize_tickers(pd.read_parquet(verified_paths["feature_frame"]))
    selection_context = normalize_tickers(
        pd.read_parquet(verified_paths["selection_context"])
    )
    scaled = normalize_tickers(pd.read_parquet(verified_paths["scaled_input"]))
    provenance = pd.read_csv(verified_paths["feature_provenance"], low_memory=False)
    coverage = normalize_tickers(
        pd.read_csv(verified_paths["feature_coverage"], low_memory=False)
    )
    technical_latest = normalize_tickers(
        pd.read_csv(verified_paths["technical_latest"], low_memory=False)
    )
    technical_audit = normalize_tickers(
        pd.read_csv(verified_paths["technical_audit"], low_memory=False)
    )
    action_audit = normalize_tickers(
        pd.read_csv(verified_paths["corporate_action_audit"], low_memory=False)
    )
    universe = normalize_tickers(
        pd.read_csv(verified_paths["universe_snapshot"], low_memory=False)
    )
    refresh_batches = normalize_tickers(
        pd.read_csv(verified_paths["refresh_batches"], low_memory=False)
    )
    model_meta = checkpoint.read_json(verified_paths["model_meta"])
    model_features = [str(value) for value in model_meta.get("model_features") or []]

    frames = {
        "feature_frame": feature_frame,
        "selection_context": selection_context,
        "scaled_input": scaled,
        "feature_coverage": coverage,
        "technical_latest": technical_latest,
        "technical_audit": technical_audit,
        "corporate_action_audit": action_audit,
        "universe_snapshot": universe,
        "refresh_batches": refresh_batches,
    }
    for name, frame in frames.items():
        if frame.empty:
            failures.append(f"empty_frame:{name}")
        if "ticker" not in frame.columns:
            failures.append(f"ticker_column_missing:{name}")
        elif frame["ticker"].duplicated().any():
            failures.append(f"duplicate_ticker:{name}")

    if "is_equity_issuer" not in universe.columns:
        failures.append("universe_equity_flag_missing")
        equity_tickers: set[str] = set()
        non_equity_tickers: set[str] = set()
    else:
        equity_mask = universe["is_equity_issuer"].map(boolish)
        equity_tickers = set(universe.loc[equity_mask, "ticker"])
        non_equity_tickers = set(universe.loc[~equity_mask, "ticker"])
    if non_equity_tickers != expected_non_equities:
        failures.append("non_equity_ticker_set_mismatch")
    manifest_terminals = {
        str(value).upper().strip()
        for value in (technical.get("terminal_nontradable_tickers") or [])
    }
    if manifest_terminals != expected_terminals:
        failures.append("terminal_ticker_set_mismatch")
    decision_tickers = equity_tickers - expected_terminals
    observed_sets = {
        "feature_frame": set(feature_frame.get("ticker", [])),
        "selection_context": set(selection_context.get("ticker", [])),
        "scaled_input": set(scaled.get("ticker", [])),
        "feature_coverage": set(coverage.get("ticker", [])),
        "technical_latest": set(technical_latest.get("ticker", [])),
        "technical_audit": set(technical_audit.get("ticker", [])),
    }
    for name, observed in observed_sets.items():
        if observed != decision_tickers:
            failures.append(
                f"decision_ticker_set_mismatch:{name}:missing="
                + ",".join(sorted(decision_tickers - observed))
                + ";extra="
                + ",".join(sorted(observed - decision_tickers))
            )
    if len(equity_tickers) != int(args.expected_universe_count):
        failures.append(
            f"equity_universe_count:{len(equity_tickers)}!={int(args.expected_universe_count)}"
        )
    if len(decision_tickers) != int(args.expected_context_count):
        failures.append(
            f"decision_context_count:{len(decision_tickers)}!={int(args.expected_context_count)}"
        )
    if len(refresh_batches) != int(args.expected_universe_count):
        failures.append("refresh_batch_count_mismatch")

    coverage_manifest = feature.get("coverage") or {}
    manifest_count_checks = {
        "pilot_current_ticker_count": int(
            coverage_manifest.get("pilot_current_ticker_count") or 0
        )
        == int(args.expected_context_count),
        "decision_eligible_equity_count": int(
            coverage_manifest.get("decision_eligible_equity_count") or 0
        )
        == int(args.expected_context_count),
        "full_equity_queue_count": int(
            coverage_manifest.get("full_equity_queue_count") or 0
        )
        == int(args.expected_universe_count),
        "terminal_nontradable_excluded_count": int(
            coverage_manifest.get("terminal_nontradable_excluded_count") or 0
        )
        == len(expected_terminals),
        "price_refresh_resolved_ticker_count": int(
            coverage_manifest.get("price_refresh_resolved_ticker_count") or 0
        )
        == int(args.expected_price_refresh_count),
        "remaining_price_refresh_ticker_count": int(
            coverage_manifest.get("remaining_price_refresh_ticker_count") or 0
        )
        == 0,
        "model_feature_count": int(coverage_manifest.get("model_feature_count") or 0)
        == int(args.expected_model_feature_count),
        "selection_context_column_count": int(
            coverage_manifest.get("selection_context_column_count") or 0
        )
        == len(selection_context.columns),
        "scaled_finite_ratio": float(
            coverage_manifest.get("scaled_model_feature_finite_ratio") or 0.0
        )
        == 1.0,
        "future_statement_rows": int(
            coverage_manifest.get("future_statement_date_row_count") or 0
        )
        == 0,
    }
    failures.extend(
        f"manifest_coverage:{name}"
        for name, passed in manifest_count_checks.items()
        if not passed
    )

    if len(model_features) != int(args.expected_model_feature_count):
        failures.append("model_feature_count_mismatch")
    expected_scaled_columns = ["ticker", *model_features]
    if list(scaled.columns) != expected_scaled_columns:
        failures.append("scaled_model_schema_order_mismatch")
    missing_feature_columns = [
        column for column in model_features if column not in feature_frame.columns
    ]
    if missing_feature_columns:
        failures.append(
            "raw_model_feature_columns_missing:" + ",".join(missing_feature_columns)
        )

    raw_model = feature_frame.reindex(columns=model_features).apply(
        pd.to_numeric, errors="coerce"
    )
    scaled_model = scaled.reindex(columns=model_features).apply(
        pd.to_numeric, errors="coerce"
    )
    raw_values = raw_model.to_numpy(dtype=float)
    scaled_values = scaled_model.to_numpy(dtype=float)
    raw_infinite_count = int(np.isinf(raw_values).sum())
    scaled_nonfinite_count = int((~np.isfinite(scaled_values)).sum())
    missing_mask = raw_model.isna()
    missing_scaled_values = scaled_model.where(missing_mask).stack()
    missing_neutral_violation_count = int(
        (missing_scaled_values.abs() > float(args.missing_neutral_tolerance)).sum()
    )
    if raw_infinite_count:
        failures.append(f"raw_infinite_value_count:{raw_infinite_count}")
    if scaled_nonfinite_count:
        failures.append(f"scaled_nonfinite_value_count:{scaled_nonfinite_count}")
    if missing_neutral_violation_count:
        failures.append(
            f"scaled_missing_neutral_violation_count:{missing_neutral_violation_count}"
        )
    all_missing_features = set(raw_model.columns[raw_model.isna().all()])
    if all_missing_features != expected_all_missing:
        failures.append("all_missing_feature_set_mismatch")
    raw_finite_ratio = float(np.isfinite(raw_values).mean())
    manifest_raw_finite_ratio = float(
        coverage_manifest.get("raw_model_feature_finite_ratio") or 0.0
    )
    if not np.isclose(raw_finite_ratio, manifest_raw_finite_ratio, rtol=0, atol=1e-15):
        failures.append("raw_finite_ratio_manifest_mismatch")
    if int(missing_mask.sum().sum()) != int(
        coverage_manifest.get("raw_model_missing_cell_count") or 0
    ):
        failures.append("raw_missing_cell_count_manifest_mismatch")

    provenance_orders = pd.to_numeric(
        provenance.get("model_feature_order"), errors="coerce"
    ).tolist()
    if provenance_orders != list(range(len(model_features))):
        failures.append("feature_provenance_order_mismatch")
    if list(provenance.get("column", [])) != model_features:
        failures.append("feature_provenance_column_order_mismatch")
    if not pd.to_numeric(
        provenance.get("scaled_finite_count"), errors="coerce"
    ).eq(len(decision_tickers)).all():
        failures.append("feature_provenance_scaled_finite_count_mismatch")
    if not pd.to_numeric(
        provenance.get("scaler_missing_neutral_value"), errors="coerce"
    ).fillna(np.nan).eq(0.0).all():
        failures.append("feature_provenance_missing_neutral_value_mismatch")

    if not coverage.get("decision_ranking_allowed", False).map(boolish).eq(False).all():
        failures.append("ticker_coverage_ranking_enabled")
    if not pd.to_numeric(
        coverage.get("scaled_model_feature_finite_count"), errors="coerce"
    ).eq(len(model_features)).all():
        failures.append("ticker_coverage_scaled_finite_count_mismatch")
    raw_nonmissing = pd.to_numeric(
        coverage.get("raw_model_feature_nonmissing_count"), errors="coerce"
    )
    raw_missing = pd.to_numeric(
        coverage.get("raw_model_feature_missing_neutral_count"), errors="coerce"
    )
    if not (raw_nonmissing + raw_missing).eq(len(model_features)).all():
        failures.append("ticker_coverage_raw_count_sum_mismatch")

    if not feature_frame.get("decision_ranking_allowed", False).map(boolish).eq(False).all():
        failures.append("feature_frame_ranking_enabled")
    missing_selection_fields = [
        column
        for column in CORE_FUNDAMENTAL_MINIMUM_FIELDS
        if column not in selection_context.columns
    ]
    if missing_selection_fields:
        failures.append(
            "selection_context_core_fields_missing:"
            + ",".join(missing_selection_fields)
        )
    if not selection_context.get("decision_ranking_allowed", False).map(boolish).eq(
        False
    ).all():
        failures.append("selection_context_ranking_enabled")
    feature_dates = pd.to_datetime(
        feature_frame.get("valuation_price_cutoff_date"), errors="coerce"
    )
    if feature_dates.isna().any() or not feature_dates.dt.date.astype(str).eq(
        valuation_date
    ).all():
        failures.append("feature_frame_valuation_date_mismatch")
    frame_available = pd.to_datetime(
        feature_frame.get("feature_available_from"), errors="coerce", utc=True
    )
    if frame_available.isna().any() or (frame_available > decision_time).any():
        failures.append("feature_frame_available_after_decision")
    selection_available = pd.to_datetime(
        selection_context.get("feature_available_from"), errors="coerce", utc=True
    )
    if selection_available.isna().any() or (selection_available > decision_time).any():
        failures.append("selection_context_available_after_decision")
    future_statement_count = 0
    for column in (
        "accepted",
        "fund_accepted",
        "fund_effective_accepted",
        "fund_latest_accepted_overall",
        "fund_ttm_fallback_accepted",
    ):
        if column in feature_frame.columns:
            future_statement_count += int(
                (
                    pd.to_datetime(feature_frame[column], errors="coerce")
                    > pd.Timestamp(valuation_date)
                ).sum()
            )
    if future_statement_count:
        failures.append(f"future_statement_date_row_count:{future_statement_count}")

    technical_pass_set = set(
        technical_audit.loc[
            technical_audit.get("ticker_parity_pass", False).map(boolish), "ticker"
        ]
    )
    if technical_pass_set != decision_tickers:
        failures.append("technical_current_ready_ticker_set_mismatch")
    declared_no_reference = {
        str(value).upper().strip()
        for value in (
            (technical.get("delta_eligibility") or {}).get(
                "no_frozen_reference_tickers"
            )
            or []
        )
    }
    audited_no_reference = set(
        technical_audit.loc[
            explicitly_false(technical_audit["frozen_reference_available"])
            & explicitly_false(technical_audit["parity_applicable"]),
            "ticker",
        ]
    )
    if declared_no_reference != audited_no_reference:
        failures.append("no_frozen_reference_ticker_set_mismatch")

    observed_action_tickers = set(action_audit.get("ticker", []))
    if observed_action_tickers != expected_actions:
        failures.append("corporate_action_audit_ticker_set_mismatch")
    if not action_audit.empty:
        failed_parity_ratios = pd.to_numeric(
            action_audit.get("failed_frozen_parity_ratio"), errors="coerce"
        )
        parity_threshold = float(
            (technical.get("parity") or {}).get("ticker_threshold") or 0.90
        )
        action_contract = (
            action_audit.get("frozen_parity_failure_preserved", False).map(boolish)
            & action_audit.get("corporate_action_quarantine", False).map(boolish)
            & action_audit.get("current_technical_recompute_all_match", False).map(
                boolish
            )
            & action_audit.get("current_context_append_allowed", False).map(boolish)
            & ~action_audit.get("decision_ranking_allowed", True).map(boolish)
            & failed_parity_ratios.notna()
            & failed_parity_ratios.lt(parity_threshold)
        )
        if not action_contract.all():
            failures.append("corporate_action_recovery_contract_failed")
    action_technical = technical_audit.loc[
        technical_audit["ticker"].isin(expected_actions)
    ]
    if set(action_technical.get("ticker", [])) != expected_actions:
        failures.append("corporate_action_technical_row_missing")
    elif not (
        action_technical.get("status", "").eq(
            "current_only_ready_exact_corporate_action"
        )
        & ~action_technical.get("parity_applicable", True).map(boolish)
        & action_technical.get("frozen_reference_available", False).map(boolish)
        & action_technical.get("technical_current_row_ready", False).map(boolish)
        & action_technical.get("ticker_parity_pass", False).map(boolish)
        & ~action_technical.get("decision_ranking_allowed", True).map(boolish)
    ).all():
        failures.append("corporate_action_technical_quarantine_contract_failed")
    if expected_actions & declared_no_reference:
        failures.append("corporate_action_misclassified_no_frozen_reference")

    unchanged = source_files_unchanged(input_audits)
    if not unchanged:
        failures.append("verified_source_file_mutated")
    if failures:
        return blocked_payload(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=valuation_date,
        )

    ticker_rows: list[dict[str, Any]] = []
    feature_index = feature_frame.set_index("ticker")
    coverage_index = coverage.set_index("ticker")
    technical_index = technical_audit.set_index("ticker")
    for ticker in sorted(set(universe["ticker"])):
        is_equity = ticker in equity_tickers
        is_terminal = ticker in expected_terminals
        is_non_equity = ticker in expected_non_equities
        decision_eligible = is_equity and not is_terminal
        ticker_rows.append(
            {
                "ticker": ticker,
                "is_equity_issuer": is_equity,
                "terminal_nontradable": is_terminal,
                "non_equity_placeholder": is_non_equity,
                "decision_eligible": decision_eligible,
                "feature_row_present": ticker in feature_index.index,
                "technical_row_present": ticker in technical_index.index,
                "scaled_row_present": ticker in set(scaled["ticker"]),
                "raw_model_feature_nonmissing_count": (
                    coverage_index.loc[ticker, "raw_model_feature_nonmissing_count"]
                    if ticker in coverage_index.index
                    else np.nan
                ),
                "scaled_model_feature_finite_count": (
                    coverage_index.loc[ticker, "scaled_model_feature_finite_count"]
                    if ticker in coverage_index.index
                    else np.nan
                ),
                "corporate_action_quarantine": ticker in expected_actions,
                "decision_ranking_allowed": False,
            }
        )
    feature_rows: list[dict[str, Any]] = []
    for order, column in enumerate(model_features):
        raw_column = raw_model[column]
        scaled_column = scaled_model[column]
        missing = raw_column.isna()
        feature_rows.append(
            {
                "model_feature_order": order,
                "column": column,
                "raw_nonmissing_count": int(raw_column.notna().sum()),
                "raw_missing_neutral_count": int(missing.sum()),
                "scaled_finite_count": int(np.isfinite(scaled_column).sum()),
                "scaled_missing_neutral_violation_count": int(
                    (
                        scaled_column.where(missing).dropna().abs()
                        > float(args.missing_neutral_tolerance)
                    ).sum()
                ),
                "all_missing_neutral_feature": column in expected_all_missing,
            }
        )
    output_frames = {
        "cross_section_ticker_audit": pd.DataFrame(ticker_rows),
        "model_feature_schema_audit": pd.DataFrame(feature_rows),
    }
    outputs: dict[str, Any] = {}
    for name, frame in output_frames.items():
        path = output_dir / f"{name}.csv"
        frame.to_csv(path, index=False)
        outputs[name] = {
            **checkpoint.fingerprint(path),
            "row_count": int(len(frame)),
        }

    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_COMPLETE_CURRENT_CROSS_SECTION_NONRANKING",
        "contract_failures": [],
        "blockers": [
            "research_model_scoring_not_run",
            "selector_and_target_book_not_run",
            "historical_cagr_mdd_evidence_unchanged",
            "pit_universe_membership_not_clean",
            "corporate_action_quarantine:" + ",".join(sorted(expected_actions)),
        ],
        "valuation_price_cutoff_date": valuation_date,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "complete_cross_section_verification_passed": True,
        "current_decision_data_complete": True,
        "research_model_scoring_prerequisite_passed": True,
        "decision_ranking_allowed": False,
        "model_scoring_allowed": False,
        "model_scoring_executed": False,
        "selector_executed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_requests_executed": 0,
        "source_inputs_mutated": False,
        "target_books_mutated": False,
        "pit_universe_label_clean": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "coverage": {
            "equity_universe_count": len(equity_tickers),
            "terminal_nontradable_count": len(expected_terminals),
            "terminal_nontradable_tickers": sorted(expected_terminals),
            "non_equity_placeholder_count": len(expected_non_equities),
            "non_equity_placeholder_tickers": sorted(expected_non_equities),
            "decision_eligible_ticker_count": len(decision_tickers),
            "verified_current_feature_ticker_count": len(feature_frame),
            "verified_selection_context_ticker_count": len(selection_context),
            "selection_context_column_count": len(selection_context.columns),
            "verified_current_technical_ticker_count": len(technical_latest),
            "price_refresh_resolved_ticker_count": int(
                coverage_manifest.get("price_refresh_resolved_ticker_count") or 0
            ),
            "remaining_price_refresh_ticker_count": 0,
            "model_feature_count": len(model_features),
            "raw_model_feature_finite_ratio": raw_finite_ratio,
            "raw_model_missing_cell_count": int(missing_mask.sum().sum()),
            "all_missing_neutral_feature_count": len(all_missing_features),
            "all_missing_neutral_features": sorted(all_missing_features),
            "scaled_model_feature_finite_ratio": 1.0,
            "scaled_missing_neutral_violation_count": 0,
            "future_statement_date_row_count": 0,
        },
        "corporate_action": {
            "quarantine_tickers": sorted(expected_actions),
            "frozen_parity_reclassified_as_pass": False,
            "current_recompute_all_match": True,
            "official_sec_document_hash_verified": True,
        },
        "recommended_next_step": (
            "run a non-mutating research scoring/schema dry-run only, compare current "
            "Main/Concentrated policy decisions with the prior target books, and keep "
            "selection/target-book writes disabled"
        ),
        "source_inputs": input_audits,
        "source_immutability": {"all_verified_files_unchanged": True},
        "outputs": outputs,
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {
            "git_head": git_head(),
            "builder": checkpoint.fingerprint(Path(__file__)),
        },
    }
    checkpoint.write_json(output_dir / "manifest.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-manifest", required=True)
    parser.add_argument("--expected-feature-sha256", required=True)
    parser.add_argument("--technical-manifest", required=True)
    parser.add_argument("--expected-technical-sha256", required=True)
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument("--expected-universe-count", type=int, required=True)
    parser.add_argument("--expected-context-count", type=int, required=True)
    parser.add_argument("--expected-price-refresh-count", type=int, required=True)
    parser.add_argument("--expected-model-feature-count", type=int, required=True)
    parser.add_argument("--expected-terminal-tickers", required=True)
    parser.add_argument("--expected-non-equity-tickers", required=True)
    parser.add_argument("--expected-corporate-action-tickers", required=True)
    parser.add_argument("--expected-all-missing-features", required=True)
    parser.add_argument("--missing-neutral-tolerance", type=float, default=1e-12)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") in {
        "READY_COMPLETE_CURRENT_CROSS_SECTION_NONRANKING",
        "BLOCKED_COMPLETE_CURRENT_CROSS_SECTION_VERIFICATION",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())

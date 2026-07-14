#!/usr/bin/env python3
"""Assemble a non-ranking 238-column current feature-frame pilot for Run287.

The builder verifies the pinned technical, macro, 8-K, benchmark/live-event,
and refresh-plan artifacts; updates the exact-price pilot rows; applies the
engine's registered feature transforms in the frozen context plus explicit
identity-only rows for names outside that context; and checks the exact frozen
Phase 4 model schema and scaler behavior.

Latest-only analyst/ownership and rejected 13F/Form 4 inputs are neutralized
before recomputation. Missing raw values remain NaN and become zero only after
the frozen model scaler, matching the engine's missing-neutral contract.

An optional exact-accepted fundamental manifest may promote SEC-blocked rows
after their technical, event, and statement gates resolve. This is still a
code/schema gate, not a complete current cross-section. It never
predicts, ranks, selects, backtests, runs fullrun, or changes a target book.
"""
from __future__ import annotations

import argparse
import hashlib
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

from r1000_config import (  # noqa: E402
    BENCHMARK_RELATIVE_COLUMNS,
    DYNAMIC_LEADER_COLUMNS,
    EngineConfig,
    LATEST_ONLY_SIGNAL_COLUMNS,
    LIVE_EVENT_ALERT_COLUMNS,
    MACRO_INTERACTION_COLUMNS,
    MACRO_REGIME_COLUMNS,
    MARKET_ADAPTATION_COLUMNS,
    REGIME_ROTATION_COLUMNS,
    SEC_13F_COLUMNS,
    SEC_FORM345_COLUMNS,
)
from r1000_features import (  # noqa: E402
    compute_actual_priority_columns,
    compute_crisis_sector_fit,
    compute_dynamic_leadership_features,
    compute_event_regime_features,
    compute_latest_flow_factor_columns,
    compute_live_factor_columns,
    compute_macro_interaction_features,
    compute_market_adaptation_features,
    compute_moat_proxy_features,
    compute_multidimensional_pillar_scores,
    compute_strategy_blueprint_columns,
    compute_three_level_relative_strength,
)
from r1000_pipeline import (  # noqa: E402
    apply_scaler,
    compute_valuation_columns,
    model_feature_columns,
)


SCHEMA_VERSION = "run287-current-feature-frame-pilot-v2"
DEFAULT_TECHNICAL = (
    "outputs/run287_latest_feature_pilot_20260711_commit_bfbc1276/manifest.json"
)
DEFAULT_MACRO = "outputs/run287_macro_sidecar_20260711_commit_0d97c720/manifest.json"
DEFAULT_EVENT = (
    "outputs/run287_8k_event_actual_sidecar_20260711_commit_62154c17/manifest.json"
)
DEFAULT_BENCHMARK = (
    "outputs/run287_benchmark_event_sidecar_20260711_commit_127ee12d/manifest.json"
)
DEFAULT_PREFLIGHT = (
    "outputs/run287_decision_refresh_preflight_20260711_commit_62154c17/manifest.json"
)
DEFAULT_FUNDAMENTAL = ""
DEFAULT_MODEL_META = "G:/내 드라이브/r1000_top30_institutional/models/phase4_latest_scoring_meta.json"
DEFAULT_OUTPUT = "outputs/run287_feature_frame_pilot_20260711"

FLOW_MODEL_COLUMNS = {
    "institutional_flow_actual_score",
    "insider_flow_actual_score",
    "institutional_flow_signal_score",
    "insider_flow_signal_score",
    "ownership_flow_pillar_score",
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def manifest_path_list(value: Any) -> list[Path]:
    """Normalize one or repeated manifest arguments without splitting paths."""

    values = value if isinstance(value, (list, tuple)) else [value]
    return [repo_path(str(item).strip()) for item in values if str(item or "").strip()]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "bytes": 0, "sha256": None}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "bytes": int(stat.st_size),
        "sha256": sha256_file(path),
        "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return loaded


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return str(value)


def clean_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else parsed.date().isoformat()


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def technical_network_contract(technical: Mapping[str, Any]) -> bool:
    """Allow zero network, or one fully pinned official SEC recovery fetch."""

    request_count = int(technical.get("network_requests_executed") or 0)
    if request_count == 0:
        return True
    sec_contract = technical.get("sec_contract") or {}
    outputs = technical.get("outputs") or {}
    official_document = outputs.get("official_sec_document") or {}
    return bool(
        request_count == 1
        and technical.get("corporate_action_recovery_ready") is True
        and technical.get("corporate_action_quarantine") is True
        and technical.get("frozen_parity_reclassified_as_pass") is False
        and technical.get("current_cross_section_verification_passed") is False
        and sec_contract.get("exact_acceptance") is True
        and int(sec_contract.get("future_row_count") or 0) == 0
        and str(sec_contract.get("accession_number") or "")
        and str(official_document.get("sha256") or "")
    )


def utc_timestamp(value: Any) -> pd.Timestamp:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        raise ValueError(f"invalid UTC timestamp: {value}")
    return pd.Timestamp(parsed)


def manifest_record_path(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    section: str,
    key: str,
) -> Path:
    record = (manifest.get(section) or {}).get(key) or {}
    raw = str(record.get("path") or "")
    if not raw:
        raise ValueError(f"manifest missing {section}.{key}.path")
    path = Path(raw)
    return path if path.is_absolute() else manifest_path.parent / path


def verify_manifest_file(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    section: str,
    key: str,
) -> tuple[Path, dict[str, Any]]:
    path = manifest_record_path(manifest_path, manifest, section, key)
    actual = fingerprint(path)
    expected = (manifest.get(section) or {}).get(key) or {}
    actual["expected_sha256"] = expected.get("sha256")
    actual["hash_matches"] = bool(
        actual.get("exists")
        and expected.get("sha256")
        and actual.get("sha256") == expected.get("sha256")
    )
    return path, actual


def git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def robust_cross_sectional_z(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    median = float(np.nanmedian(values))
    mad = float(np.nanmedian(np.abs(values - median)))
    denominator = 1.4826 * max(mad, max(abs(median) * 0.01, 1e-6))
    return pd.Series(
        np.clip((values - median) / denominator, -6.0, 6.0),
        index=series.index,
        dtype=float,
    )


def recompute_long_momentum_columns(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    mom12 = pd.to_numeric(output.get("mom_12m"), errors="coerce")
    mom24 = pd.to_numeric(output.get("mom_24m"), errors="coerce")
    mom36 = pd.to_numeric(output.get("mom_36m"), errors="coerce")
    output["multi_year_winner_score"] = (
        0.50 * robust_cross_sectional_z(mom12.fillna(0.0))
        + 0.80 * robust_cross_sectional_z(mom24.fillna(0.0))
        + 0.60 * robust_cross_sectional_z(mom36.fillna(0.0))
    ).where(mom24.notna(), 0.0).clip(lower=-6.0, upper=6.0)
    output["persistence_trend_24m"] = (
        (mom12 > 0.15) & (mom24 > 0.30) & (mom36 > 0.50)
    ).astype(float)
    return output


def transform_feature_context(frame: pd.DataFrame, cfg: EngineConfig) -> pd.DataFrame:
    output = compute_live_factor_columns(frame, cfg)
    output = compute_latest_flow_factor_columns(output)
    output = compute_actual_priority_columns(output, cfg)
    output = compute_valuation_columns(output, cfg)
    output = compute_macro_interaction_features(output)
    output = compute_market_adaptation_features(output)
    output = compute_event_regime_features(output)
    output = compute_moat_proxy_features(output)
    output = compute_dynamic_leadership_features(output)
    output = compute_three_level_relative_strength(output)
    output = compute_crisis_sector_fit(output)
    output = compute_strategy_blueprint_columns(output, cfg)
    output = compute_multidimensional_pillar_scores(output)
    return output


def feature_lane(column: str, technical_columns: set[str]) -> tuple[str, str]:
    if column in technical_columns or column in {
        "multi_year_winner_score",
        "persistence_trend_24m",
    }:
        return "technical", "current_exact_pilot_partial_context"
    if column in set(MACRO_REGIME_COLUMNS):
        return "macro", "current_global_sidecar"
    if column in set(MACRO_INTERACTION_COLUMNS):
        return "macro_derived", "current_global_partial_context"
    if column in set(BENCHMARK_RELATIVE_COLUMNS) or column.startswith("rs_benchmark_"):
        return "benchmark", "current_global_sidecar"
    if column in set(LIVE_EVENT_ALERT_COLUMNS):
        return "live_event", "current_global_sidecar"
    if column in FLOW_MODEL_COLUMNS or "institutional_flow" in column or "insider_flow" in column:
        return "ownership_flow", "neutralized_unrefreshed_source"
    partial_sets = (
        set(DYNAMIC_LEADER_COLUMNS)
        | set(MARKET_ADAPTATION_COLUMNS)
        | set(REGIME_ROTATION_COLUMNS)
    )
    if column in partial_sets:
        return "cross_sectional_derived", "current_partial_context"
    if column in set(LATEST_ONLY_SIGNAL_COLUMNS):
        return "latest_only_vendor", "neutralized_then_registered_fallback"
    return "fundamental_or_derived", "statement_asof_carry_or_partial_context"


def blocked_payload(
    output_dir: Path,
    *,
    status: str,
    failures: list[str],
    decision_time: pd.Timestamp,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "contract_failures": failures,
        "blockers": failures,
        "decision_time_utc": decision_time.isoformat(),
        "research_only": True,
        "schema_assembly_ready": False,
        "bounded_price_refresh_allowed": False,
        "decision_feature_complete": False,
        "decision_ranking_allowed": False,
        "historical_backtest_acceptance_allowed": False,
        "fullrun_executed": False,
        "selector_executed": False,
        "model_scoring_executed": False,
        "backtest_executed": False,
        "network_requests_executed": 0,
        "source_inputs_mutated": False,
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def build(args: argparse.Namespace, *, observed_at_utc: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    technical_path = repo_path(args.technical_manifest)
    macro_path = repo_path(args.macro_manifest)
    event_path = repo_path(args.event_manifest)
    benchmark_path = repo_path(args.benchmark_manifest)
    preflight_path = repo_path(args.preflight_manifest)
    model_meta_path = repo_path(args.model_meta)
    fundamental_paths = manifest_path_list(
        getattr(args, "fundamental_manifest", "")
    )
    fundamental_enabled = bool(fundamental_paths)
    sec_promotion_paths = manifest_path_list(
        getattr(args, "sec_promotion_manifest", "")
    )
    sec_promotion_enabled = bool(sec_promotion_paths)
    promotion_enabled = fundamental_enabled or sec_promotion_enabled
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    decision_time = utc_timestamp(
        observed_at_utc
        or getattr(args, "decision_time_utc", "")
        or datetime.now(timezone.utc).isoformat()
    )
    manifest_paths = [
        technical_path,
        macro_path,
        event_path,
        benchmark_path,
        preflight_path,
        model_meta_path,
    ]
    manifest_paths.extend(fundamental_paths)
    manifest_paths.extend(sec_promotion_paths)
    missing = [str(path) for path in manifest_paths if not path.is_file()]
    if missing:
        return blocked_payload(
            output_dir,
            status="BLOCKED_FEATURE_FRAME_INPUT_MISSING",
            failures=[f"required_input_missing:{path}" for path in missing],
            decision_time=decision_time,
        )

    technical = read_json(technical_path)
    macro = read_json(macro_path)
    event = read_json(event_path)
    benchmark = read_json(benchmark_path)
    preflight = read_json(preflight_path)
    model_meta = read_json(model_meta_path)
    fundamentals = [read_json(path) for path in fundamental_paths]
    sec_promotions = [read_json(path) for path in sec_promotion_paths]
    valuation_date = clean_date(technical.get("valuation_price_cutoff_date"))
    technical_latest_path, technical_latest_input = verify_manifest_file(
        technical_path, technical, "outputs", "latest_technical_features"
    )
    ticker_audit_path, ticker_audit_input = verify_manifest_file(
        technical_path, technical, "outputs", "ticker_audit"
    )
    corporate_action_document_input: dict[str, Any] | None = None
    if technical.get("corporate_action_recovery_ready") is True:
        _, corporate_action_document_input = verify_manifest_file(
            technical_path, technical, "outputs", "official_sec_document"
        )
    ranked_path, ranked_input = verify_manifest_file(
        technical_path, technical, "source_inputs", "ranked_universe"
    )
    macro_current_path, macro_input = verify_manifest_file(
        macro_path, macro, "outputs", "macro_current"
    )
    event_audit_path, event_input = verify_manifest_file(
        event_path, event, "outputs", "event_actual_audit"
    )
    benchmark_current_path, benchmark_input = verify_manifest_file(
        benchmark_path, benchmark, "outputs", "benchmark_current"
    )
    live_event_path, live_event_input = verify_manifest_file(
        benchmark_path, benchmark, "outputs", "live_event_current"
    )
    refresh_batches_path, refresh_batches_input = verify_manifest_file(
        preflight_path, preflight, "outputs", "refresh_batches"
    )
    universe_snapshot_path, universe_snapshot_input = verify_manifest_file(
        preflight_path, preflight, "source_inputs", "universe_snapshot"
    )
    fundamental_overrides_paths: list[Path] = []
    promotion_audit_paths: list[Path] = []
    sec_promotion_audit_paths: list[Path] = []
    delta_latest_path: Path | None = None
    delta_audit_path: Path | None = None
    input_audits = {
        "technical_latest": technical_latest_input,
        "ticker_audit": ticker_audit_input,
        "ranked_universe": ranked_input,
        "macro_current": macro_input,
        "event_actual_audit": event_input,
        "benchmark_current": benchmark_input,
        "live_event_current": live_event_input,
        "refresh_batches": refresh_batches_input,
        "universe_snapshot": universe_snapshot_input,
    }
    if corporate_action_document_input is not None:
        input_audits["corporate_action_official_sec_document"] = (
            corporate_action_document_input
        )
    if fundamental_enabled:
        for index, (fundamental_path, fundamental) in enumerate(
            zip(fundamental_paths, fundamentals)
        ):
            fundamental_overrides_path, fundamental_overrides_input = (
                verify_manifest_file(
                    fundamental_path,
                    fundamental,
                    "outputs",
                    "latest_fundamental_overrides",
                )
            )
            promotion_audit_path, promotion_audit_input = verify_manifest_file(
                fundamental_path, fundamental, "outputs", "promotion_audit"
            )
            fundamental_overrides_paths.append(fundamental_overrides_path)
            promotion_audit_paths.append(promotion_audit_path)
            input_audits.update(
                {
                    f"fundamental_{index}_overrides": fundamental_overrides_input,
                    f"fundamental_{index}_promotion_audit": promotion_audit_input,
                }
            )
    if sec_promotion_enabled:
        for index, (promotion_path, promotion) in enumerate(
            zip(sec_promotion_paths, sec_promotions)
        ):
            promotion_audit_path, promotion_audit_input = verify_manifest_file(
                promotion_path, promotion, "outputs", "promotion_audit"
            )
            sec_promotion_audit_paths.append(promotion_audit_path)
            input_audits[
                f"sec_promotion_{index}_audit"
            ] = promotion_audit_input
    if promotion_enabled:
        delta_latest_path, promoted_delta_latest_input = verify_manifest_file(
            technical_path,
            technical,
            "outputs",
            "delta_latest_technical_features",
        )
        delta_audit_path, promoted_delta_audit_input = verify_manifest_file(
            technical_path, technical, "outputs", "delta_ticker_audit"
        )
        input_audits.update(
            {
                "promoted_delta_latest": promoted_delta_latest_input,
                "promoted_delta_audit": promoted_delta_audit_input,
            }
        )
    contract_failures: list[str] = []
    for name, audit in input_audits.items():
        if audit.get("hash_matches") is not True:
            contract_failures.append(f"input_hash_mismatch:{name}")

    expected_status = {
        "technical": technical.get("status")
        == "TECHNICAL_PARITY_READY_MACRO_FUNDAMENTAL_BLOCKED",
        "macro": macro.get("status") == "READY_CONSERVATIVE_MACRO_SIDECAR",
        "event": event.get("status") == "READY_8K_FROZEN_SCHEMA_NOOP_SIDECAR",
        "benchmark": benchmark.get("status")
        == "READY_CONSERVATIVE_BENCHMARK_EVENT_SIDECAR",
        "preflight": preflight.get("status") == "BLOCKED_BOUNDED_DECISION_REFRESH",
    }
    if fundamental_enabled:
        for index, fundamental in enumerate(fundamentals):
            expected_status[f"fundamental_{index}"] = (
                fundamental.get("status")
                == "READY_B002_EXACT_FUNDAMENTAL_PROMOTION_GATE"
            )
    if sec_promotion_enabled:
        for index, promotion in enumerate(sec_promotions):
            expected_status[f"sec_promotion_{index}"] = (
                promotion.get("status")
                == "READY_8K_FROZEN_SCHEMA_NOOP_SIDECAR"
            )
    contract_failures.extend(
        f"upstream_status_not_ready:{name}"
        for name, ready in expected_status.items()
        if not ready
    )
    dates = {
        valuation_date,
        clean_date(macro.get("valuation_close_date")),
        clean_date(event.get("valuation_price_cutoff_date")),
        clean_date(benchmark.get("valuation_close_date")),
        clean_date(preflight.get("decision_date")),
    }
    if fundamental_enabled:
        dates.update(
            clean_date(fundamental.get("valuation_price_cutoff_date"))
            for fundamental in fundamentals
        )
    if sec_promotion_enabled:
        dates.update(
            clean_date(promotion.get("valuation_price_cutoff_date"))
            for promotion in sec_promotions
        )
    if len(dates) != 1 or "" in dates:
        contract_failures.append(f"valuation_date_mismatch:{sorted(dates)}")
    safety_checks = {
        "technical_no_ranking": technical.get("decision_ranking_allowed") is False,
        "technical_no_mutation": technical.get("source_inputs_mutated") is False,
        "technical_network_contract": technical_network_contract(technical),
        "technical_corporate_action_contract": (
            technical.get("corporate_action_recovery_ready") is not True
            or (
                technical.get("current_cross_section_complete") is True
                and technical.get("corporate_action_quarantine") is True
                and technical.get("frozen_parity_reclassified_as_pass") is False
                and technical.get("decision_ranking_allowed") is False
            )
        ),
        "technical_no_fullrun": technical.get("fullrun_executed") is False,
        "macro_merge": macro.get("macro_merge_allowed") is True,
        "event_noop": event.get("event_actual_refresh_gate_resolved") is True
        and event.get("actual_feature_value_change_count") == 0,
        "benchmark_merge": benchmark.get("benchmark_event_merge_allowed") is True,
        "macro_no_mutation": macro.get("source_inputs_mutated") is False,
        "macro_zero_network": macro.get("network_requests_executed") == 0,
        "macro_no_fullrun": macro.get("fullrun_executed") is False,
        "event_no_mutation": event.get("source_inputs_mutated") is False,
        "event_zero_network": event.get("network_requests_executed") == 0,
        "event_no_fullrun": event.get("fullrun_executed") is False,
        "benchmark_no_mutation": benchmark.get("source_inputs_mutated") is False,
        "benchmark_zero_network": benchmark.get("network_requests_executed") == 0,
        "benchmark_no_fullrun": benchmark.get("fullrun_executed") is False,
        "preflight_no_mutation": preflight.get("source_inputs_mutated") is False,
        "preflight_zero_network": preflight.get("network_requests_executed") == 0,
        "preflight_no_fullrun": preflight.get("fullrun_executed") is False,
    }
    if fundamental_enabled:
        for index, fundamental in enumerate(fundamentals):
            safety_checks.update(
                {
                    f"fundamental_{index}_gate_resolved": fundamental.get(
                        "fundamental_refresh_gate_resolved"
                    )
                    is True,
                    f"fundamental_{index}_promotion_allowed": fundamental.get(
                        "technical_context_promotion_allowed"
                    )
                    is True,
                    f"fundamental_{index}_no_ranking": fundamental.get(
                        "decision_ranking_allowed"
                    )
                    is False,
                    f"fundamental_{index}_no_mutation": fundamental.get(
                        "source_inputs_mutated"
                    )
                    is False,
                    f"fundamental_{index}_zero_network": fundamental.get(
                        "network_requests_executed"
                    )
                    == 0,
                    f"fundamental_{index}_no_fullrun": fundamental.get(
                        "fullrun_executed"
                    )
                    is False,
                }
            )
    if sec_promotion_enabled:
        for index, promotion in enumerate(sec_promotions):
            safety_checks.update(
                {
                    f"sec_promotion_{index}_event_gate_resolved": promotion.get(
                        "event_actual_refresh_gate_resolved"
                    )
                    is True,
                    f"sec_promotion_{index}_promotion_allowed": promotion.get(
                        "technical_context_promotion_allowed"
                    )
                    is True,
                    f"sec_promotion_{index}_no_ranking": promotion.get(
                        "decision_ranking_allowed"
                    )
                    is False,
                    f"sec_promotion_{index}_no_mutation": promotion.get(
                        "source_inputs_mutated"
                    )
                    is False,
                    f"sec_promotion_{index}_zero_network": promotion.get(
                        "network_requests_executed"
                    )
                    == 0,
                    f"sec_promotion_{index}_no_fullrun": promotion.get(
                        "fullrun_executed"
                    )
                    is False,
                }
            )
    contract_failures.extend(
        f"upstream_safety_check:{name}" for name, ready in safety_checks.items() if not ready
    )
    available_times = [
        pd.to_datetime(technical.get("observed_at_utc"), errors="coerce", utc=True),
        pd.to_datetime(macro.get("macro_available_from"), errors="coerce", utc=True),
        pd.to_datetime(
            benchmark.get("benchmark_event_available_from"), errors="coerce", utc=True
        ),
        pd.to_datetime(event.get("observed_at_utc"), errors="coerce", utc=True),
    ]
    if fundamental_enabled:
        available_times.extend(
            pd.to_datetime(
                fundamental.get("decision_time_utc"), errors="coerce", utc=True
            )
            for fundamental in fundamentals
        )
    if sec_promotion_enabled:
        available_times.extend(
            pd.to_datetime(
                promotion.get("observed_at_utc"), errors="coerce", utc=True
            )
            for promotion in sec_promotions
        )
    if any(pd.isna(value) for value in available_times):
        contract_failures.append("upstream_available_from_missing")
        feature_available_from = pd.NaT
    else:
        feature_available_from = max(pd.Timestamp(value) for value in available_times)
        if feature_available_from > decision_time:
            contract_failures.append("feature_available_after_decision_time")

    model_features = [str(value) for value in model_meta.get("model_features") or []]
    scaler = model_meta.get("scaler") or {}
    expected_model_count = int(args.expected_model_feature_count)
    if len(model_features) != expected_model_count:
        contract_failures.append(
            f"model_feature_count:{len(model_features)}!={expected_model_count}"
        )
    if set(model_features) != set(scaler):
        contract_failures.append("model_scaler_schema_mismatch")
    current_code_features = model_feature_columns(EngineConfig())
    missing_from_current_code = [
        column for column in model_features if column not in current_code_features
    ]
    if missing_from_current_code:
        contract_failures.append(
            "frozen_features_missing_from_current_code:"
            + ",".join(missing_from_current_code)
        )
    code_only_features = [
        column for column in current_code_features if column not in model_features
    ]

    if contract_failures:
        return blocked_payload(
            output_dir,
            status="BLOCKED_FEATURE_FRAME_INPUT_CONTRACT",
            failures=contract_failures,
            decision_time=decision_time,
        )

    ranked = pd.read_csv(ranked_path, low_memory=False)
    technical_latest = pd.read_csv(technical_latest_path, low_memory=False)
    ticker_audit = pd.read_csv(ticker_audit_path, low_memory=False)
    macro_current = pd.read_csv(macro_current_path, low_memory=False)
    benchmark_current = pd.read_csv(benchmark_current_path, low_memory=False)
    live_event_current = pd.read_csv(live_event_path, low_memory=False)
    refresh_batches = pd.read_csv(refresh_batches_path, low_memory=False)
    universe_snapshot = pd.read_csv(universe_snapshot_path, low_memory=False)
    # Read the event audit even though the registered merge action is a no-op;
    # this verifies the pinned output remains parseable at assembly time.
    event_audit = pd.read_csv(event_audit_path, low_memory=False)
    fundamental_overrides = pd.DataFrame()
    promotion_audit = pd.DataFrame()
    promoted_tickers: set[str] = set()
    fundamental_override_columns: list[str] = []
    fundamental_changed_model_feature_count = 0
    fundamental_override_tickers: set[str] = set()
    newly_appended_promoted_tickers: set[str] = set()
    if promotion_enabled:
        if (
            len(fundamental_overrides_paths) != len(fundamentals)
            or len(promotion_audit_paths) != len(fundamentals)
            or len(sec_promotion_audit_paths) != len(sec_promotions)
            or delta_latest_path is None
            or delta_audit_path is None
        ):
            contract_failures.append("promotion_input_path_missing")
        else:
            override_frames: list[pd.DataFrame] = []
            promotion_frames: list[pd.DataFrame] = []
            promotion_occurrences: list[str] = []
            override_column_order: list[str] | None = None
            for index, (
                fundamental,
                fundamental_overrides_path,
                promotion_audit_path,
            ) in enumerate(
                zip(
                    fundamentals,
                    fundamental_overrides_paths,
                    promotion_audit_paths,
                )
            ):
                override_frame = pd.read_csv(
                    fundamental_overrides_path, low_memory=False
                )
                promotion_frame = pd.read_csv(
                    promotion_audit_path, low_memory=False
                )
                for frame in (override_frame, promotion_frame):
                    frame["ticker"] = (
                        frame["ticker"].astype(str).str.upper().str.strip()
                    )
                if override_column_order is None:
                    override_column_order = list(override_frame.columns)
                elif set(override_frame.columns) != set(override_column_order):
                    contract_failures.append(
                        f"fundamental_{index}_override_schema_mismatch"
                    )
                else:
                    override_frame = override_frame.reindex(
                        columns=override_column_order
                    )
                if promotion_frame["ticker"].duplicated().any():
                    contract_failures.append(
                        f"fundamental_{index}_duplicate_promotion_tickers"
                    )
                manifest_promoted = set(
                    promotion_frame.loc[
                        promotion_frame[
                            "technical_context_promotion_allowed"
                        ].map(boolish),
                        "ticker",
                    ]
                )
                expected_promoted = set(
                    str(ticker or "").upper().strip()
                    for ticker in (
                        (fundamental.get("promotion") or {}).get(
                            "newly_promoted_tickers"
                        )
                        or []
                    )
                )
                if manifest_promoted != expected_promoted:
                    contract_failures.append(
                        f"fundamental_{index}_promotion_ticker_set_mismatch"
                    )
                if set(override_frame["ticker"]) - manifest_promoted:
                    contract_failures.append(
                        f"fundamental_{index}_override_ticker_outside_promotion_set"
                    )
                promotion_occurrences.extend(sorted(manifest_promoted))
                override_frames.append(override_frame)
                promotion_frames.append(promotion_frame)
                fundamental_changed_model_feature_count += int(
                    (fundamental.get("coverage") or {}).get(
                        "changed_model_feature_count"
                    )
                    or 0
                )
            for index, (promotion, promotion_audit_path) in enumerate(
                zip(sec_promotions, sec_promotion_audit_paths)
            ):
                promotion_frame = pd.read_csv(
                    promotion_audit_path, low_memory=False
                )
                promotion_frame["ticker"] = (
                    promotion_frame["ticker"].astype(str).str.upper().str.strip()
                )
                if promotion_frame["ticker"].duplicated().any():
                    contract_failures.append(
                        f"sec_promotion_{index}_duplicate_promotion_tickers"
                    )
                manifest_promoted = set(
                    promotion_frame.loc[
                        promotion_frame[
                            "technical_context_promotion_allowed"
                        ].map(boolish),
                        "ticker",
                    ]
                )
                expected_promoted = set(
                    str(ticker or "").upper().strip()
                    for ticker in (
                        (promotion.get("promotion") or {}).get(
                            "newly_promoted_tickers"
                        )
                        or []
                    )
                )
                if manifest_promoted != expected_promoted:
                    contract_failures.append(
                        f"sec_promotion_{index}_ticker_set_mismatch"
                    )
                promotion_occurrences.extend(sorted(manifest_promoted))
                promotion_frames.append(promotion_frame)
            duplicate_promotions = sorted(
                {
                    ticker
                    for ticker in promotion_occurrences
                    if promotion_occurrences.count(ticker) > 1
                }
            )
            if duplicate_promotions:
                contract_failures.append(
                    "duplicate_promotion_tickers:"
                    + ",".join(duplicate_promotions)
                )
            fundamental_overrides = (
                pd.concat(override_frames, ignore_index=True, sort=False)
                if override_frames
                else pd.DataFrame()
            )
            promotion_audit = pd.concat(
                promotion_frames, ignore_index=True, sort=False
            )
            duplicate_overrides = (
                sorted(
                    fundamental_overrides.loc[
                        fundamental_overrides["ticker"].duplicated(keep=False),
                        "ticker",
                    ].unique()
                )
                if not fundamental_overrides.empty
                else []
            )
            if duplicate_overrides:
                contract_failures.append(
                    "duplicate_fundamental_override_tickers:"
                    + ",".join(duplicate_overrides)
                )
            promoted_delta_latest = pd.read_csv(delta_latest_path, low_memory=False)
            promoted_delta_audit = pd.read_csv(delta_audit_path, low_memory=False)
            for frame in (
                promoted_delta_latest,
                promoted_delta_audit,
            ):
                frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
            promoted_tickers = set(
                promotion_audit.loc[
                    promotion_audit["technical_context_promotion_allowed"].map(boolish),
                    "ticker",
                ]
            )
            fundamental_override_tickers = (
                set(fundamental_overrides["ticker"])
                if not fundamental_overrides.empty
                else set()
            )
            technical_present = set(
                technical_latest["ticker"].astype(str).str.upper().str.strip()
            )
            already_present_promoted = promoted_tickers & technical_present
            newly_appended_promoted_tickers = promoted_tickers - technical_present
            promoted_latest_rows = promoted_delta_latest[
                promoted_delta_latest["ticker"].isin(
                    newly_appended_promoted_tickers
                )
            ].copy()
            promoted_audit_rows = promoted_delta_audit[
                promoted_delta_audit["ticker"].isin(
                    newly_appended_promoted_tickers
                )
            ].copy()
            if set(promoted_latest_rows["ticker"]) != newly_appended_promoted_tickers:
                contract_failures.append("promoted_technical_rows_missing")
            if set(promoted_audit_rows["ticker"]) != newly_appended_promoted_tickers:
                contract_failures.append("promoted_audit_rows_missing")
            if not promoted_audit_rows["ticker_parity_pass"].map(boolish).all():
                contract_failures.append("promoted_ticker_parity_not_resolved")
            existing_audit = ticker_audit.copy()
            existing_audit["ticker"] = (
                existing_audit["ticker"].astype(str).str.upper().str.strip()
            )
            existing_promoted_audit = existing_audit[
                existing_audit["ticker"].isin(already_present_promoted)
            ]
            if set(existing_promoted_audit["ticker"]) != already_present_promoted:
                contract_failures.append("carried_promoted_audit_rows_missing")
            elif not existing_promoted_audit["ticker_parity_pass"].map(boolish).all():
                contract_failures.append("carried_promoted_ticker_parity_not_resolved")
            technical_latest = pd.concat(
                [technical_latest, promoted_latest_rows], ignore_index=True, sort=False
            )
            ticker_audit = pd.concat(
                [ticker_audit, promoted_audit_rows], ignore_index=True, sort=False
            )
            if not fundamental_overrides.empty:
                override_available = pd.to_datetime(
                    fundamental_overrides.get("available_from"),
                    errors="coerce",
                    utc=True,
                )
                if override_available.isna().any():
                    contract_failures.append(
                        "fundamental_override_available_from_missing"
                    )
                elif not override_available.empty:
                    feature_available_from = max(
                        feature_available_from, pd.Timestamp(override_available.max())
                    )
                    if feature_available_from > decision_time:
                        contract_failures.append(
                            "fundamental_override_available_after_decision_time"
                        )
    if any(
        frame.empty
        for frame in [
            ranked,
            technical_latest,
            ticker_audit,
            macro_current,
            benchmark_current,
            live_event_current,
            refresh_batches,
            universe_snapshot,
            event_audit,
        ]
    ):
        return blocked_payload(
            output_dir,
            status="BLOCKED_FEATURE_FRAME_EMPTY_INPUT",
            failures=["one_or_more_verified_inputs_empty"],
            decision_time=decision_time,
        )

    ranked["ticker"] = ranked["ticker"].astype(str).str.upper().str.strip()
    technical_latest["ticker"] = (
        technical_latest["ticker"].astype(str).str.upper().str.strip()
    )
    ticker_audit["ticker"] = ticker_audit["ticker"].astype(str).str.upper().str.strip()
    universe_snapshot["ticker"] = (
        universe_snapshot["ticker"].astype(str).str.upper().str.strip()
    )
    pilot_tickers = set(technical_latest["ticker"])
    parity_tickers = set(
        ticker_audit.loc[ticker_audit["ticker_parity_pass"].map(boolish), "ticker"]
    )
    if pilot_tickers != parity_tickers:
        contract_failures.append("technical_pilot_ticker_parity_set_mismatch")
    missing_context_tickers = sorted(pilot_tickers - set(ranked["ticker"]))
    context = ranked.copy()
    context["context_seed_source"] = "frozen_ranked_context"
    context["frozen_reference_available"] = True
    identity_seeded_context_tickers: set[str] = set()
    if missing_context_tickers:
        declared_no_frozen = {
            str(ticker).upper().strip()
            for ticker in (
                (technical.get("delta_eligibility") or {}).get(
                    "no_frozen_reference_tickers"
                )
                or []
            )
        }
        audited_no_frozen = (
            set(
                ticker_audit.loc[
                    ticker_audit["ticker"].isin(set(missing_context_tickers))
                    & ~ticker_audit["parity_applicable"].map(boolish),
                    "ticker",
                ]
            )
            if "parity_applicable" in ticker_audit.columns
            else set()
        )
        expected_missing = set(missing_context_tickers)
        if declared_no_frozen != expected_missing:
            contract_failures.append(
                "no_frozen_reference_manifest_ticker_set_mismatch"
            )
        if audited_no_frozen != expected_missing:
            contract_failures.append(
                "no_frozen_reference_audit_ticker_set_mismatch"
            )
        if universe_snapshot["ticker"].duplicated().any():
            contract_failures.append("universe_snapshot_duplicate_tickers")
        identity_rows = universe_snapshot.loc[
            universe_snapshot["ticker"].isin(expected_missing)
        ].copy()
        if set(identity_rows["ticker"]) != expected_missing:
            contract_failures.append(
                "no_frozen_reference_universe_identity_missing"
            )
        if (
            "is_equity_issuer" in identity_rows.columns
            and not identity_rows["is_equity_issuer"].map(boolish).all()
        ):
            contract_failures.append(
                "no_frozen_reference_non_equity_identity"
            )
        terminal_tickers = {
            str(ticker).upper().strip()
            for ticker in (technical.get("terminal_nontradable_tickers") or [])
        }
        if expected_missing & terminal_tickers:
            contract_failures.append(
                "no_frozen_reference_terminal_identity_overlap"
            )
        if (
            set(identity_rows["ticker"]) == expected_missing
            and not (
                "is_equity_issuer" in identity_rows.columns
                and not identity_rows["is_equity_issuer"].map(boolish).all()
            )
        ):
            new_context = pd.DataFrame(
                np.nan,
                index=range(len(identity_rows)),
                columns=context.columns,
            )
            identity_columns = [
                column
                for column in (
                    "ticker",
                    "cik",
                    "cik10",
                    "name",
                    "company_name",
                    "exchange",
                    "sector",
                    "industry",
                    "sub_industry",
                    "universe_source",
                    "cik_mapping_status",
                    "is_equity_issuer",
                )
                if column in identity_rows.columns
            ]
            identity_index = identity_rows.set_index("ticker")
            for column in identity_columns:
                if column == "ticker":
                    new_context[column] = identity_rows["ticker"].values
                else:
                    new_context[column] = new_context["ticker"].map(
                        identity_index[column]
                    )
            new_context["context_seed_source"] = (
                "universe_snapshot_identity_only"
            )
            new_context["frozen_reference_available"] = False
            context = pd.concat(
                [context, new_context], ignore_index=True, sort=False
            )
            identity_seeded_context_tickers = expected_missing

    context["source_feature_date"] = context.get("feature_date")
    context["source_rebalance_date"] = context.get("rebalance_date")
    old_px = pd.to_numeric(context.get("px"), errors="coerce").copy()

    neutralized_columns = sorted(
        {
            *LATEST_ONLY_SIGNAL_COLUMNS,
            *SEC_13F_COLUMNS,
            *SEC_FORM345_COLUMNS,
        }
        & set(context.columns)
    )
    for column in neutralized_columns:
        context[column] = np.nan

    technical_index = technical_latest.set_index("ticker")
    technical_columns: set[str] = set()
    for column in technical_latest.columns:
        if not column.startswith("technical_"):
            continue
        base_column = column[len("technical_") :]
        if f"delta_{base_column}" not in technical_latest.columns:
            continue
        technical_columns.add(base_column)
        mask = context["ticker"].isin(technical_index.index)
        context.loc[mask, base_column] = context.loc[mask, "ticker"].map(
            technical_index[column]
        )

    new_px = pd.to_numeric(context.get("px"), errors="coerce")
    price_ratio = (new_px / old_px.replace(0, np.nan)).replace(
        [np.inf, -np.inf], np.nan
    )
    pilot_mask = context["ticker"].isin(pilot_tickers)
    for column in ("mktcap", "market_cap_live"):
        if column in context.columns:
            context.loc[pilot_mask, column] = (
                pd.to_numeric(context.loc[pilot_mask, column], errors="coerce")
                * price_ratio.loc[pilot_mask]
            )
    if "current_price_live" in context.columns:
        context.loc[pilot_mask, "current_price_live"] = new_px.loc[pilot_mask]

    if fundamental_enabled and not fundamental_overrides.empty:
        override_index = fundamental_overrides.set_index("ticker")
        excluded_override_columns = {
            "ticker",
            "cik",
            "cik10",
            "accession_number",
            "form",
            "fiscal_period",
            "period",
            "period_of_report",
            "source",
            "source_hashes",
            "pit_caveats",
            "pit_universe_label_clean",
            "exact_acceptance",
            "component_coverage",
            "missing_evidence_policy",
            "filed_fallback_used",
            "used_forward_return",
            "valuation_price_cutoff_date",
            "valuation_px",
        }
        fundamental_override_columns = sorted(
            column
            for column in fundamental_overrides.columns
            if column not in excluded_override_columns
            and (column in context.columns or column in model_features)
        )
        override_mask = context["ticker"].isin(override_index.index)
        for column in fundamental_override_columns:
            context.loc[override_mask, column] = context.loc[
                override_mask, "ticker"
            ].map(override_index[column])

    macro_row = macro_current.iloc[0]
    benchmark_row = benchmark_current.iloc[0]
    live_event_row = live_event_current.iloc[0]
    for column, value in macro_row.items():
        if column in context.columns or column in model_features:
            context[column] = value
    for column, value in benchmark_row.items():
        if column.startswith("bench_"):
            context[column] = value
    for column, value in live_event_row.items():
        if column.startswith("live_event_"):
            context[column] = value

    context["rebalance_date"] = pd.Timestamp(valuation_date)
    context["feature_date"] = pd.Timestamp(valuation_date)
    for horizon in (1, 3, 6, 12):
        context[f"rs_benchmark_{horizon}m"] = pd.to_numeric(
            context.get(f"mom_{horizon}m"), errors="coerce"
        ) - pd.to_numeric(context.get(f"bench_ret_{horizon}m"), errors="coerce")
    context["dd_gap_benchmark"] = pd.to_numeric(
        context.get("bench_dd_1y"), errors="coerce"
    ) - pd.to_numeric(context.get("dd_1y"), errors="coerce")
    context = recompute_long_momentum_columns(context)

    cfg = EngineConfig()
    context = transform_feature_context(context, cfg)
    for column in model_features:
        if column not in context.columns:
            context[column] = np.nan
    pilot = context[context["ticker"].isin(pilot_tickers)].copy()
    pilot = pilot.sort_values("ticker").reset_index(drop=True)
    raw_model = pilot[model_features].apply(pd.to_numeric, errors="coerce")
    scaled_matrix = apply_scaler(pilot, scaler, model_features)
    scaled = pd.DataFrame(scaled_matrix, columns=model_features)
    scaled.insert(0, "ticker", pilot["ticker"].values)
    raw_values = raw_model.to_numpy(dtype=float)
    scaled_values = scaled_matrix.astype(float)
    raw_finite_ratio = float(np.isfinite(raw_values).mean())
    scaled_finite_ratio = float(np.isfinite(scaled_values).mean())

    date_columns = [
        column
        for column in (
            "accepted",
            "fund_accepted",
            "fund_effective_accepted",
            "fund_latest_accepted_overall",
            "fund_ttm_fallback_accepted",
        )
        if column in pilot.columns
    ]
    future_date_rows = 0
    for column in date_columns:
        future_date_rows += int(
            (
                pd.to_datetime(pilot[column], errors="coerce")
                > pd.Timestamp(valuation_date)
            ).sum()
        )

    expected_pilot_count = int(
        (technical.get("parity") or {}).get("pilot_ticker_count") or 0
    ) + int(
        len(newly_appended_promoted_tickers) if promotion_enabled else 0
    )
    if len(pilot) != expected_pilot_count:
        contract_failures.append("assembled_pilot_ticker_count_mismatch")
    if len(model_features) != len(raw_model.columns):
        contract_failures.append("assembled_raw_schema_count_mismatch")
    if list(raw_model.columns) != model_features:
        contract_failures.append("assembled_raw_schema_order_mismatch")
    if scaled_finite_ratio != 1.0:
        contract_failures.append(f"scaled_matrix_nonfinite_ratio:{scaled_finite_ratio}")
    if future_date_rows:
        contract_failures.append(f"future_statement_date_rows:{future_date_rows}")

    source_hashes_after = {
        name: sha256_file(Path(str(audit["path"])))
        for name, audit in input_audits.items()
        if audit.get("exists") and Path(str(audit.get("path"))).is_file()
    }
    source_files_unchanged = all(
        source_hashes_after.get(name) == audit.get("sha256")
        for name, audit in input_audits.items()
        if audit.get("exists")
    )
    if not source_files_unchanged:
        contract_failures.append("verified_source_file_mutated")

    metadata = pd.DataFrame(
        {
            "ticker": pilot["ticker"],
            "source_feature_date": pilot["source_feature_date"],
            "source_rebalance_date": pilot["source_rebalance_date"],
            "context_seed_source": pilot["context_seed_source"],
            "frozen_reference_available": pilot[
                "frozen_reference_available"
            ].map(boolish),
            "identity_cik10": pilot.get(
                "cik10", pd.Series(index=pilot.index, dtype=object)
            ),
            "valuation_price_cutoff_date": valuation_date,
            "feature_available_from": (
                feature_available_from.isoformat()
                if pd.notna(feature_available_from)
                else ""
            ),
            "partial_context_row_count": len(context),
            "current_technical_context_row_count": len(pilot),
            "latest_only_inputs_neutralized": True,
            "event_actual_value_change_count": 0,
            "fundamental_value_change_count": np.where(
                pilot["ticker"].isin(fundamental_override_tickers),
                fundamental_changed_model_feature_count,
                0,
            ),
            "fundamental_override_applied": pilot["ticker"].isin(
                fundamental_override_tickers
            ),
            "fundamental_promotion_applied": pilot["ticker"].isin(
                promoted_tickers
            ),
            "decision_feature_complete": False,
            "decision_ranking_allowed": False,
        }
    )
    feature_frame = pd.concat(
        [metadata.reset_index(drop=True), raw_model.reset_index(drop=True)], axis=1
    )
    feature_frame_path = output_dir / "pilot_feature_frame.parquet"
    scaled_path = output_dir / "pilot_scaled_model_input.parquet"
    feature_frame.to_parquet(feature_frame_path, index=False)
    scaled.to_parquet(scaled_path, index=False)

    provenance_rows: list[dict[str, Any]] = []
    for index, column in enumerate(model_features):
        lane, freshness = feature_lane(column, technical_columns)
        series = raw_model[column]
        provenance_rows.append(
            {
                "model_feature_order": index,
                "column": column,
                "lane": lane,
                "freshness": freshness,
                "raw_nonmissing_count": int(series.notna().sum()),
                "raw_missing_neutral_count": int(series.isna().sum()),
                "raw_finite_ratio": float(np.isfinite(series.to_numpy(dtype=float)).mean()),
                "scaled_finite_count": int(np.isfinite(scaled_matrix[:, index]).sum()),
                "scaler_missing_neutral_value": 0.0,
            }
        )
    provenance = pd.DataFrame(provenance_rows)
    provenance_path = output_dir / "model_feature_provenance.csv"
    provenance.to_csv(provenance_path, index=False)

    ticker_coverage = metadata.copy()
    ticker_coverage["raw_model_feature_nonmissing_count"] = raw_model.notna().sum(axis=1).values
    ticker_coverage["raw_model_feature_missing_neutral_count"] = raw_model.isna().sum(axis=1).values
    ticker_coverage["scaled_model_feature_finite_count"] = np.isfinite(
        scaled_matrix
    ).sum(axis=1)
    ticker_coverage_path = output_dir / "ticker_feature_coverage.csv"
    ticker_coverage.to_csv(ticker_coverage_path, index=False)

    performance = preflight.get("performance_plan") or {}
    total_equities = int(performance.get("total_queue_rows") or len(refresh_batches))
    terminal_nontradable_count = int(
        technical.get("terminal_nontradable_ticker_count") or 0
    )
    decision_eligible_equities = max(
        total_equities - terminal_nontradable_count, 0
    )
    price_refresh_count = int(performance.get("price_refresh_tickers") or 0)
    resolved_price_refresh_count = int(
        technical.get("price_refresh_resolved_ticker_count") or 0
    )
    remaining_price_refresh_count = max(
        price_refresh_count - resolved_price_refresh_count, 0
    )
    context_current_ratio = (
        float(len(pilot) / decision_eligible_equities)
        if decision_eligible_equities
        else 0.0
    )
    full_current_cross_section_assembled = bool(
        decision_eligible_equities > 0
        and len(pilot) == decision_eligible_equities
        and remaining_price_refresh_count == 0
    )
    remaining_blockers = (
        [
            "complete_current_cross_section_verification_required",
            *(
                ["corporate_action_quarantine_review_required"]
                if technical.get("corporate_action_quarantine") is True
                else []
            ),
        ]
        if full_current_cross_section_assembled
        else [
            f"full_universe_current_context:{len(pilot)}/{decision_eligible_equities}",
            f"bounded_price_refresh_required:{remaining_price_refresh_count}",
            "current_cross_section_not_assembled",
        ]
    )
    status = (
        (
            "CURRENT_CROSS_SECTION_ASSEMBLED_VERIFICATION_REQUIRED"
            if full_current_cross_section_assembled
            else "PILOT_SCHEMA_READY_FULL_UNIVERSE_BLOCKED"
        )
        if not contract_failures
        else "BLOCKED_FEATURE_FRAME_PILOT_CONTRACT"
    )
    elapsed = time.perf_counter() - started
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "contract_failures": contract_failures,
        "blockers": remaining_blockers if not contract_failures else contract_failures,
        "valuation_price_cutoff_date": valuation_date,
        "decision_time_utc": decision_time.isoformat(),
        "feature_available_from": (
            feature_available_from.isoformat()
            if pd.notna(feature_available_from)
            else ""
        ),
        "research_only": True,
        "current_decision_only": True,
        "pilot_only": True,
        "full_current_cross_section_assembled": full_current_cross_section_assembled,
        "complete_cross_section_verification_passed": False,
        "schema_assembly_ready": not contract_failures,
        "bounded_price_refresh_allowed": not contract_failures,
        "price_refresh_output_policy": "isolated_append_only_checkpointed_batches",
        "decision_feature_complete": False,
        "decision_ranking_allowed": False,
        "model_scoring_allowed": False,
        "target_book_generation_allowed": False,
        "historical_backtest_acceptance_allowed": False,
        "fullrun_executed": False,
        "selector_executed": False,
        "model_scoring_executed": False,
        "backtest_executed": False,
        "network_requests_executed": 0,
        "source_inputs_mutated": not source_files_unchanged,
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "missing_evidence_policy": "raw_nan_then_frozen_scaler_zero",
        "no_frozen_reference_policy": (
            "universe_identity_plus_current_technical_raw_nan_elsewhere"
        ),
        "latest_only_source_policy": "neutralized_before_registered_fallbacks",
        "fundamental_promotion_applied": fundamental_enabled,
        "fundamental_manifest_count": len(fundamentals),
        "sec_promotion_applied": sec_promotion_enabled,
        "sec_promotion_manifest_count": len(sec_promotions),
        "promotion_manifest_count": len(fundamentals) + len(sec_promotions),
        "promoted_tickers": sorted(promoted_tickers),
        "coverage": {
            "frozen_context_row_count": int(len(ranked)),
            "identity_seeded_context_row_count": int(
                len(identity_seeded_context_tickers)
            ),
            "identity_seeded_context_tickers": sorted(
                identity_seeded_context_tickers
            ),
            "assembly_context_row_count": int(len(context)),
            "pilot_current_ticker_count": int(len(pilot)),
            "full_equity_queue_count": total_equities,
            "decision_eligible_equity_count": decision_eligible_equities,
            "terminal_nontradable_excluded_count": terminal_nontradable_count,
            "terminal_nontradable_excluded_tickers": sorted(
                str(ticker).upper().strip()
                for ticker in (technical.get("terminal_nontradable_tickers") or [])
            ),
            "current_context_ratio": context_current_ratio,
            "price_refresh_ticker_count": price_refresh_count,
            "price_refresh_resolved_ticker_count": resolved_price_refresh_count,
            "remaining_price_refresh_ticker_count": remaining_price_refresh_count,
            "model_feature_count": int(len(model_features)),
            "raw_model_feature_finite_ratio": raw_finite_ratio,
            "raw_model_missing_cell_count": int(raw_model.isna().sum().sum()),
            "raw_all_missing_feature_count": int(raw_model.isna().all().sum()),
            "scaled_model_feature_finite_ratio": scaled_finite_ratio,
            "future_statement_date_row_count": future_date_rows,
            "neutralized_source_column_count": int(len(neutralized_columns)),
            "fundamental_override_column_count": int(
                len(fundamental_override_columns)
            ),
            "fundamental_changed_model_feature_count": (
                fundamental_changed_model_feature_count
            ),
        },
        "schema_drift": {
            "frozen_model_feature_count": int(len(model_features)),
            "current_code_feature_count": int(len(current_code_features)),
            "frozen_features_missing_from_current_code": missing_from_current_code,
            "current_code_features_excluded_from_frozen_model": code_only_features,
            "frozen_model_order_preserved": list(raw_model.columns) == model_features,
        },
        "performance": {
            "elapsed_seconds": elapsed,
            "context_rows_per_second": float(len(context) / elapsed) if elapsed else None,
            "technical_compute_992_estimate_seconds": (
                (technical.get("performance") or {}).get(
                    "estimated_seconds_for_992_tickers"
                )
            ),
        },
        "recommended_next_step": (
            "run the hash-pinned complete-current-cross-section verifier; preserve "
            "all missing-neutral and corporate-action quarantine evidence; do not "
            "score or rank"
            if full_current_cross_section_assembled
            else (
                f"record the {len(pilot)}-name exact-SEC promoted checkpoint and ledger; "
                "keep it non-ranking; dispatch the next isolated append-only price batch "
                "only after this gate is documented"
                if promotion_enabled and newly_appended_promoted_tickers
                else str(
                    technical.get("post_assembly_recommended_next_step")
                    or (
                        "run isolated append-only price batch B001 only; checkpoint "
                        "hashes; do not score or build target books"
                    )
                )
            )
        ),
        "source_inputs": {
            "technical_manifest": fingerprint(technical_path),
            "macro_manifest": fingerprint(macro_path),
            "event_manifest": fingerprint(event_path),
            "benchmark_manifest": fingerprint(benchmark_path),
            "preflight_manifest": fingerprint(preflight_path),
            "model_meta": fingerprint(model_meta_path),
            **(
                {
                    "fundamental_manifests": [
                        fingerprint(path) for path in fundamental_paths
                    ]
                }
                if fundamental_paths
                else {}
            ),
            **(
                {
                    "sec_promotion_manifests": [
                        fingerprint(path) for path in sec_promotion_paths
                    ]
                }
                if sec_promotion_paths
                else {}
            ),
            **input_audits,
        },
        "source_immutability": {
            "all_verified_files_unchanged": source_files_unchanged,
        },
        "outputs": {
            "pilot_feature_frame": {
                **fingerprint(feature_frame_path),
                "row_count": int(len(feature_frame)),
                "model_feature_count": int(len(model_features)),
            },
            "pilot_scaled_model_input": {
                **fingerprint(scaled_path),
                "row_count": int(len(scaled)),
                "model_feature_count": int(len(model_features)),
            },
            "model_feature_provenance": {
                **fingerprint(provenance_path),
                "row_count": int(len(provenance)),
            },
            "ticker_feature_coverage": {
                **fingerprint(ticker_coverage_path),
                "row_count": int(len(ticker_coverage)),
            },
        },
        "code": {
            "git_head": git_head(),
            "builder": fingerprint(Path(__file__).resolve()),
        },
    }
    write_json(output_dir / "manifest.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def render_report(payload: Mapping[str, Any]) -> str:
    coverage = payload.get("coverage") or {}
    drift = payload.get("schema_drift") or {}
    lines = [
        "# Run287 current feature-frame pilot",
        "",
        f"- status: `{payload.get('status')}`",
        f"- current pilot / decision-eligible queue: "
        f"`{coverage.get('pilot_current_ticker_count')}` / "
        f"`{coverage.get('decision_eligible_equity_count')}`",
        f"- terminal non-tradable exclusions / original queue: "
        f"`{coverage.get('terminal_nontradable_excluded_count')}` / "
        f"`{coverage.get('full_equity_queue_count')}`",
        f"- frozen model columns: `{coverage.get('model_feature_count')}`",
        f"- raw finite ratio: `{float(coverage.get('raw_model_feature_finite_ratio') or 0.0):.2%}`",
        f"- scaled finite ratio: `{float(coverage.get('scaled_model_feature_finite_ratio') or 0.0):.2%}`",
        f"- current-code columns excluded from frozen model: "
        f"`{len(drift.get('current_code_features_excluded_from_frozen_model') or [])}`",
        f"- bounded price refresh allowed: `{payload.get('bounded_price_refresh_allowed')}`",
        f"- decision ranking allowed: `{payload.get('decision_ranking_allowed')}`",
        "",
        "## Remaining blockers",
        "",
    ]
    lines.extend([f"- `{item}`" for item in payload.get("blockers") or []] or ["- none"])
    lines.extend(
        [
            "",
            "## Decision",
            "",
            (
                "The full current cross-section is assembled but still requires its "
                "separate hash-pinned verification gate."
                if payload.get("full_current_cross_section_assembled")
                else (
                    f"The frozen 238-column code/scaler path is ready, but "
                    f"{coverage.get('pilot_current_ticker_count')} pilot rows are not a "
                    "complete current cross-section."
                )
            ),
            "Do not predict, rank, select, backtest, or mutate portfolio targets yet.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--technical-manifest", default=DEFAULT_TECHNICAL)
    parser.add_argument("--macro-manifest", default=DEFAULT_MACRO)
    parser.add_argument("--event-manifest", default=DEFAULT_EVENT)
    parser.add_argument("--benchmark-manifest", default=DEFAULT_BENCHMARK)
    parser.add_argument("--preflight-manifest", default=DEFAULT_PREFLIGHT)
    parser.add_argument(
        "--fundamental-manifest",
        action="append",
        default=None,
        help="Repeat to apply disjoint exact-fundamental promotion manifests.",
    )
    parser.add_argument(
        "--sec-promotion-manifest",
        action="append",
        default=None,
        help="Repeat to apply disjoint exact event-only promotion manifests.",
    )
    parser.add_argument("--model-meta", default=DEFAULT_MODEL_META)
    parser.add_argument("--decision-time-utc", default="")
    parser.add_argument("--expected-model-feature-count", type=int, default=238)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=json_default))
    return 0 if payload.get("status") in {
        "PILOT_SCHEMA_READY_FULL_UNIVERSE_BLOCKED",
        "CURRENT_CROSS_SECTION_ASSEMBLED_VERIFICATION_REQUIRED",
        "BLOCKED_FEATURE_FRAME_PILOT_CONTRACT",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())

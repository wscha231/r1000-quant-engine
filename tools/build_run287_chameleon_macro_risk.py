#!/usr/bin/env python3
"""Build the Run287 Chameleon ten-axis market-risk report-only sidecar.

The input is a decision-date-normalized, point-in-time metric ledger.  Every
metric row carries the value visible at that decision timestamp, its original
observation date, availability timestamp, source hash, and truth class.  This
tool computes trailing-only five-year empirical percentiles, aggregates the
registered ten axes, applies the fixed market-state hysteresis, and reports the
extreme-fear/recovery/greed overlay.

It deliberately has no network collector and no portfolio write surface.  It
does not select securities, size positions, create TradeIntent rows, write
targets or orders, mutate a ledger, run a backtest/fullrun, or promote a policy.
Those actions require later, separately approved causal changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "docs" / "run287_chameleon_macro_risk_contract.json"
SCHEMA_VERSION = "run287-chameleon-macro-risk-report-v1"
CANONICAL_CONTRACT_SEMANTIC_SHA256 = "5cbd1915a12bba77e8114cab00e281cb4956a2e46af1c21612d4bd637c26ebef"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EXPLICIT_OFFSET_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d{1,9})?)?"
    r"(?:[Zz]|(?P<offset_sign>[+-])(?P<offset_hour>\d{2}):(?P<offset_minute>\d{2}))$"
)
CALENDAR_REQUIRED_COLUMNS = (
    "decision_date",
    "decision_time_utc",
    "nyse_session_ordinal",
)
METRIC_REQUIRED_COLUMNS = (
    "decision_date",
    "decision_time_utc",
    "nyse_session_ordinal",
    "calendar_source_sha256",
    "axis",
    "component",
    "raw_value",
    "risk_direction",
    "source_observation_date",
    "available_from",
    "source_kind",
    "source_sha256",
    "truth_class",
)
CONTEXT_REQUIRED_COLUMNS = (
    "decision_date",
    "decision_time_utc",
    "nyse_session_ordinal",
    "calendar_source_sha256",
    "source_observation_date",
    "available_from",
    "source_kind",
    "source_sha256",
    "truth_class",
)
BLOCKED_STATUS = "BLOCKED_CHAMELEON_MACRO_RISK_INPUT_CONTRACT"


class ContractError(ValueError):
    """Raised when an input could fabricate or leak a decision-time state."""


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(payload: Any) -> str:
    raw = json.dumps(
        json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": int(path.stat().st_size),
    }


def capture_input_fingerprint(path: Path, label: str) -> dict[str, Any]:
    try:
        return fingerprint(path)
    except OSError as exc:
        raise ContractError(
            f"input_fingerprint_unreadable:{label}:{path}:{type(exc).__name__}"
        ) from exc


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "UNAVAILABLE"


def capture_code_identity() -> dict[str, Any]:
    head = git_head().strip().lower()
    if not GIT_COMMIT_RE.fullmatch(head):
        raise ContractError("git_head_unavailable_or_invalid")
    builder_path = Path(__file__).resolve()
    try:
        builder = fingerprint(builder_path)
    except OSError as exc:
        raise ContractError(
            f"builder_source_unreadable:{builder_path}:{type(exc).__name__}"
        ) from exc
    return {"git_head": head, "builder": builder}


def json_safe(value: Any) -> Any:
    """Recursively normalize pandas/NumPy missing values to strict JSON."""

    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp,)):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, int)):
        return value
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(json_safe(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            return pd.read_csv(path, low_memory=False)
        if suffix in {".parquet", ".pq"}:
            return pd.read_parquet(path)
        if suffix in {".jsonl", ".ndjson"}:
            return pd.read_json(path, lines=True)
    except Exception as exc:
        raise ContractError(
            f"input_table_unreadable:{path}:{type(exc).__name__}"
        ) from exc
    raise ContractError(f"unsupported_input_format:{path.suffix}")


def parse_date_only(values: pd.Series, label: str) -> pd.Series:
    try:
        text_values = values[values.notna()].astype(str).str.strip()
        if not text_values.map(lambda value: bool(DATE_ONLY_RE.fullmatch(value))).all():
            raise ContractError(f"invalid_{label}")
        parsed = pd.to_datetime(values, errors="coerce")
        timezone = parsed.dt.tz
        if timezone is not None:
            raise ContractError(f"invalid_{label}")
        return parsed.dt.normalize()
    except ContractError:
        raise
    except (AttributeError, TypeError, ValueError) as exc:
        raise ContractError(f"invalid_{label}") from exc


def parse_explicit_offset_timestamp(values: pd.Series, label: str) -> pd.Series:
    parsed_values: list[pd.Timestamp] = []
    for value in values:
        if value is None or value is pd.NA or value is pd.NaT:
            parsed_values.append(pd.NaT)
            continue
        try:
            if isinstance(value, str):
                text = value.strip()
                match = EXPLICIT_OFFSET_TIMESTAMP_RE.fullmatch(text)
                if match is None:
                    raise ContractError(f"invalid_{label}")
                if match.group("offset_hour") is not None:
                    offset_hour = int(match.group("offset_hour"))
                    offset_minute = int(match.group("offset_minute"))
                    if (
                        offset_hour > 23
                        or offset_minute > 59
                        or (
                            match.group("offset_sign") == "-"
                            and offset_hour == 0
                            and offset_minute == 0
                        )
                    ):
                        raise ContractError(f"invalid_{label}")
                parsed = pd.Timestamp(text)
            else:
                parsed = pd.Timestamp(value)
            if pd.isna(parsed):
                parsed_values.append(pd.NaT)
                continue
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ContractError(f"invalid_{label}")
            parsed_values.append(parsed.tz_convert("UTC"))
        except ContractError:
            raise
        except (TypeError, ValueError, OverflowError) as exc:
            raise ContractError(f"invalid_{label}") from exc
    return pd.Series(parsed_values, index=values.index, dtype="datetime64[ns, UTC]")


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    if path.resolve() != DEFAULT_CONTRACT.resolve():
        raise ContractError(f"noncanonical_contract_path:{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"contract_unreadable:{path}:{exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError("contract_root_not_object")
    semantic_hash = sha256_json(payload)
    if semantic_hash != CANONICAL_CONTRACT_SEMANTIC_SHA256:
        raise ContractError(
            "canonical_contract_semantic_hash_mismatch:"
            f"{semantic_hash}!={CANONICAL_CONTRACT_SEMANTIC_SHA256}"
        )
    validate_contract(payload)
    return payload


def component_registry(contract: Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    registry: dict[str, tuple[str, str]] = {}
    for axis, spec in contract["axes"].items():
        for component, direction in spec["components"].items():
            if component in registry:
                raise ContractError(f"duplicate_contract_component:{component}")
            registry[component] = (axis, direction)
    return registry


def validate_contract(contract: Mapping[str, Any]) -> None:
    axes = contract.get("axes")
    if not isinstance(axes, dict) or len(axes) != 10:
        raise ContractError("contract_must_define_exactly_10_axes")
    weights = [float(spec.get("weight", math.nan)) for spec in axes.values()]
    if not all(math.isfinite(value) and value > 0 for value in weights):
        raise ContractError("contract_axis_weight_invalid")
    if not math.isclose(sum(weights), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ContractError(f"contract_axis_weights_not_one:{sum(weights)}")
    for axis, spec in axes.items():
        components = spec.get("components")
        minimum = int(spec.get("minimum_ready_components", 0))
        if not isinstance(components, dict) or not components:
            raise ContractError(f"contract_axis_components_missing:{axis}")
        if minimum < 1 or minimum > len(components):
            raise ContractError(f"contract_axis_minimum_invalid:{axis}")
        bad = [name for name, direction in components.items() if direction not in {"HIGH", "LOW"}]
        if bad:
            raise ContractError(f"contract_risk_direction_invalid:{axis}:{','.join(bad)}")
        if not str(spec.get("red_domain") or ""):
            raise ContractError(f"contract_red_domain_missing:{axis}")
    component_registry(contract)
    readiness = contract.get("readiness") or {}
    required_axes = set(readiness.get("required_axes") or [])
    if not required_axes.issubset(axes):
        raise ContractError("contract_required_axis_unknown")
    if int(readiness.get("minimum_ready_axes", 0)) != 8:
        raise ContractError("contract_minimum_ready_axes_must_be_8")
    if readiness.get("composite_method") != "AVAILABLE_AXIS_WEIGHT_NORMALIZED_ONLY_AFTER_READINESS_GATE":
        raise ContractError("contract_composite_method_invalid")
    safety = contract.get("safety") or {}
    required_false = (
        "stock_alpha_allowed",
        "selector_execution_allowed",
        "target_book_write_allowed",
        "trade_intent_write_allowed",
        "order_generation_allowed",
        "ledger_mutation_allowed",
        "fullrun_allowed",
        "production_activation_allowed",
        "live_trading_allowed",
        "automatic_promotion_allowed",
    )
    if safety.get("report_only") is not True or any(safety.get(key) is not False for key in required_false):
        raise ContractError("contract_report_only_safety_envelope_invalid")


def _parse_bool(value: Any, *, label: str) -> bool | None:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if not np.isscalar(value):
        raise ContractError(f"invalid_boolean:{label}:non_scalar")
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError) as exc:
        raise ContractError(f"invalid_boolean:{label}:non_scalar") from exc
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise ContractError(f"invalid_boolean:{label}:{value}")


def _parse_optional_numeric(value: Any, *, label: str) -> float:
    if value is None or value is pd.NA or value is pd.NaT:
        return math.nan
    if isinstance(value, (bool, np.bool_)):
        raise ContractError(f"invalid_context_numeric:{label}:boolean")
    if not np.isscalar(value):
        raise ContractError(f"invalid_context_numeric:{label}:non_scalar")
    try:
        if bool(pd.isna(value)):
            return math.nan
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"invalid_context_numeric:{label}") from exc
    if not math.isfinite(numeric):
        raise ContractError(f"invalid_context_numeric:{label}")
    return numeric


def validate_calendar(frame: pd.DataFrame, source_sha256: str) -> pd.DataFrame:
    missing = [column for column in CALENDAR_REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ContractError(f"calendar_missing_columns:{','.join(missing)}")
    source_hash = str(source_sha256 or "").strip().lower()
    if not SHA256_RE.fullmatch(source_hash):
        raise ContractError("invalid_calendar_artifact_sha256")
    output = frame[list(CALENDAR_REQUIRED_COLUMNS)].copy()
    if output.empty:
        raise ContractError("calendar_empty")
    output["decision_date"] = parse_date_only(output["decision_date"], "calendar_decision_date")
    output["decision_time_utc"] = parse_explicit_offset_timestamp(
        output["decision_time_utc"],
        "calendar_decision_time_timestamp",
    )
    output["nyse_session_ordinal"] = pd.to_numeric(output["nyse_session_ordinal"], errors="coerce")
    if output[["decision_date", "decision_time_utc", "nyse_session_ordinal"]].isna().any().any():
        raise ContractError("invalid_calendar_row")
    ordinal_values = output["nyse_session_ordinal"].to_numpy(dtype=float)
    if not np.equal(ordinal_values, np.floor(ordinal_values)).all():
        raise ContractError("invalid_calendar_session_ordinal")
    output["nyse_session_ordinal"] = output["nyse_session_ordinal"].astype(int)
    if output.duplicated(["decision_date"]).any() or output.duplicated(["nyse_session_ordinal"]).any():
        raise ContractError("duplicate_calendar_session")
    output = output.sort_values("decision_date").reset_index(drop=True)
    if len(output) > 1 and not (output["nyse_session_ordinal"].diff().dropna() == 1).all():
        raise ContractError("noncontiguous_calendar_session_ordinal")
    local_session_dates = (
        output["decision_time_utc"]
        .dt.tz_convert("America/New_York")
        .dt.tz_localize(None)
        .dt.normalize()
    )
    if not local_session_dates.equals(output["decision_date"]):
        raise ContractError("calendar_decision_timestamp_date_mismatch")
    try:
        import pandas_market_calendars as mcal

        schedule = mcal.get_calendar("NYSE").schedule(
            start_date=output["decision_date"].iloc[0].date().isoformat(),
            end_date=output["decision_date"].iloc[-1].date().isoformat(),
        )
    except ImportError as exc:
        raise ContractError("xnys_calendar_validator_unavailable") from exc
    except Exception as exc:
        raise ContractError("xnys_calendar_validation_failed") from exc
    expected_dates = pd.DatetimeIndex(schedule.index).tz_localize(None).normalize()
    observed_dates = pd.DatetimeIndex(output["decision_date"])
    if not observed_dates.equals(expected_dates):
        raise ContractError("calendar_xnys_session_coverage_mismatch")
    output.attrs["source_sha256"] = source_hash
    return output


def validate_session_binding(
    frame: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    label: str,
    require_contiguous_slice: bool,
) -> None:
    if calendar.empty:
        raise ContractError("calendar_empty")
    expected_hash = str(calendar.attrs.get("source_sha256") or "")
    if not expected_hash or not frame["calendar_source_sha256"].eq(expected_hash).all():
        raise ContractError(f"{label}_calendar_artifact_hash_mismatch")
    expected = calendar.set_index("decision_date")
    observed_sessions = frame[
        ["decision_date", "decision_time_utc", "nyse_session_ordinal"]
    ].drop_duplicates()
    if observed_sessions.duplicated(["decision_date"]).any():
        raise ContractError(f"multiple_{label}_session_bindings")
    for row in observed_sessions.itertuples(index=False):
        if row.decision_date not in expected.index:
            raise ContractError(f"{label}_decision_date_not_in_calendar:{row.decision_date.date()}")
        calendar_row = expected.loc[row.decision_date]
        if (
            pd.Timestamp(row.decision_time_utc) != pd.Timestamp(calendar_row["decision_time_utc"])
            or int(row.nyse_session_ordinal) != int(calendar_row["nyse_session_ordinal"])
        ):
            raise ContractError(f"{label}_calendar_session_mismatch:{row.decision_date.date()}")
    if require_contiguous_slice and not observed_sessions.empty:
        observed_dates = list(observed_sessions.sort_values("decision_date")["decision_date"])
        expected_dates = list(
            calendar.loc[
                calendar["decision_date"].between(observed_dates[0], observed_dates[-1]),
                "decision_date",
            ]
        )
        if observed_dates != expected_dates:
            raise ContractError(f"{label}_calendar_session_coverage_mismatch")


def _normalize_dates(frame: pd.DataFrame, *, context: bool = False) -> pd.DataFrame:
    output = frame.copy()
    required = CONTEXT_REQUIRED_COLUMNS if context else METRIC_REQUIRED_COLUMNS
    missing = [column for column in required if column not in output.columns]
    if missing:
        raise ContractError(f"missing_columns:{','.join(missing)}")
    output["decision_date"] = parse_date_only(output["decision_date"], "decision_date")
    output["decision_time_utc"] = parse_explicit_offset_timestamp(
        output["decision_time_utc"],
        "decision_time_timestamp",
    )
    output["available_from"] = parse_explicit_offset_timestamp(
        output["available_from"],
        "available_from_timestamp",
    )
    if output[["decision_date", "decision_time_utc", "available_from"]].isna().any().any():
        raise ContractError("invalid_decision_or_availability_timestamp")
    output["source_observation_date"] = parse_date_only(
        output["source_observation_date"],
        "source_observation_date",
    )
    if output["source_observation_date"].isna().any():
        raise ContractError("invalid_source_observation_date")
    return output


def validate_metrics(
    frame: pd.DataFrame,
    contract: Mapping[str, Any],
    as_of: pd.Timestamp,
    calendar: pd.DataFrame,
) -> pd.DataFrame:
    output = _normalize_dates(frame)
    output = output[output["decision_date"] <= as_of].copy()
    if output.empty:
        raise ContractError("no_metric_rows_on_or_before_as_of")
    if not (output["decision_date"] == as_of).any():
        raise ContractError(f"as_of_decision_rows_missing:{as_of.date().isoformat()}")
    output["axis"] = output["axis"].astype(str).str.strip()
    output["component"] = output["component"].astype(str).str.strip()
    output["risk_direction"] = output["risk_direction"].astype(str).str.strip().str.upper()
    output["source_kind"] = output["source_kind"].astype(str).str.strip()
    if output["source_kind"].str.lower().isin({"", "nan", "none", "null", "nat", "<na>"}).any():
        raise ContractError("missing_metric_source_kind")
    output["source_sha256"] = output["source_sha256"].astype(str).str.strip().str.lower()
    output["calendar_source_sha256"] = output["calendar_source_sha256"].astype(str).str.strip().str.lower()
    output["truth_class"] = output["truth_class"].astype(str).str.strip().str.upper()
    output["raw_value"] = pd.to_numeric(output["raw_value"], errors="coerce")
    output["nyse_session_ordinal"] = pd.to_numeric(output["nyse_session_ordinal"], errors="coerce")
    if not np.isfinite(output["raw_value"].to_numpy(dtype=float)).all():
        raise ContractError("nonfinite_metric_raw_value")
    session_values = output["nyse_session_ordinal"].to_numpy(dtype=float)
    if not np.isfinite(session_values).all() or not np.equal(session_values, np.floor(session_values)).all():
        raise ContractError("invalid_nyse_session_ordinal")
    output["nyse_session_ordinal"] = output["nyse_session_ordinal"].astype(int)
    registry = component_registry(contract)
    for row in output[["axis", "component", "risk_direction"]].drop_duplicates().itertuples(index=False):
        expected = registry.get(row.component)
        if expected is None:
            raise ContractError(f"unregistered_metric_component:{row.component}")
        if expected != (row.axis, row.risk_direction):
            raise ContractError(
                f"metric_contract_mismatch:{row.component}:{row.axis}/{row.risk_direction}!={expected[0]}/{expected[1]}"
            )
    if output.duplicated(["decision_date", "component"]).any():
        raise ContractError("duplicate_metric_decision_component")
    if (output["available_from"] > output["decision_time_utc"]).any():
        raise ContractError("future_available_from_metric_row")
    if (output["source_observation_date"] > output["decision_date"]).any():
        raise ContractError("future_source_observation_date_metric_row")
    bad_hashes = sorted(set(output.loc[~output["source_sha256"].map(lambda value: bool(SHA256_RE.fullmatch(value))), "source_sha256"]))
    if bad_hashes:
        raise ContractError("invalid_metric_source_sha256")
    if not output["calendar_source_sha256"].map(lambda value: bool(SHA256_RE.fullmatch(value))).all():
        raise ContractError("invalid_calendar_source_sha256")
    if output["calendar_source_sha256"].nunique() != 1:
        raise ContractError("multiple_calendar_source_hashes")
    truth_classes = set(contract["truth_classes_in_quality_order"])
    if not set(output["truth_class"]).issubset(truth_classes):
        raise ContractError("invalid_metric_truth_class")
    forbidden_tokens = contract.get("source_truth_rules", {}).get(
        "pit_verified_forbidden_source_kind_tokens", []
    )
    forbidden_pit = output["truth_class"].eq("PIT_VERIFIED") & output["source_kind"].str.upper().map(
        lambda value: any(str(token).upper() in value for token in forbidden_tokens)
    )
    if forbidden_pit.any():
        raise ContractError("current_vintage_source_cannot_be_pit_verified")
    time_counts = output.groupby("decision_date")["decision_time_utc"].nunique()
    if (time_counts != 1).any():
        raise ContractError("multiple_decision_times_for_metric_date")
    validate_session_binding(
        output,
        calendar,
        label="metric",
        require_contiguous_slice=True,
    )
    return output.sort_values(["decision_date", "axis", "component"]).reset_index(drop=True)


def validate_context(
    frame: pd.DataFrame | None,
    contract: Mapping[str, Any],
    as_of: pd.Timestamp,
    metric_decision_times: Mapping[pd.Timestamp, pd.Timestamp],
    metric_sessions: Mapping[pd.Timestamp, tuple[int, str]],
    calendar: pd.DataFrame,
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=list(CONTEXT_REQUIRED_COLUMNS))
    output = _normalize_dates(frame, context=True)
    output = output[output["decision_date"] <= as_of].copy()
    if output.duplicated(["decision_date"]).any():
        raise ContractError("duplicate_context_decision_date")
    if (output["available_from"] > output["decision_time_utc"]).any():
        raise ContractError("future_available_from_context_row")
    if (output["source_observation_date"] > output["decision_date"]).any():
        raise ContractError("future_source_observation_date_context_row")
    output["source_kind"] = output["source_kind"].astype(str).str.strip()
    if output["source_kind"].str.lower().isin({"", "nan", "none", "null", "nat", "<na>"}).any():
        raise ContractError("missing_context_source_kind")
    output["source_sha256"] = output["source_sha256"].astype(str).str.strip().str.lower()
    output["calendar_source_sha256"] = output["calendar_source_sha256"].astype(str).str.strip().str.lower()
    output["truth_class"] = output["truth_class"].astype(str).str.strip().str.upper()
    output["nyse_session_ordinal"] = pd.to_numeric(output["nyse_session_ordinal"], errors="coerce")
    session_values = output["nyse_session_ordinal"].to_numpy(dtype=float)
    if not np.isfinite(session_values).all() or not np.equal(session_values, np.floor(session_values)).all():
        raise ContractError("invalid_context_nyse_session_ordinal")
    output["nyse_session_ordinal"] = output["nyse_session_ordinal"].astype(int)
    if not output["source_sha256"].map(lambda value: bool(SHA256_RE.fullmatch(value))).all():
        raise ContractError("invalid_context_source_sha256")
    if not output["calendar_source_sha256"].map(lambda value: bool(SHA256_RE.fullmatch(value))).all():
        raise ContractError("invalid_context_calendar_source_sha256")
    if not set(output["truth_class"]).issubset(set(contract["truth_classes_in_quality_order"])):
        raise ContractError("invalid_context_truth_class")
    forbidden_tokens = contract.get("source_truth_rules", {}).get(
        "pit_verified_forbidden_source_kind_tokens", []
    )
    forbidden_pit = output["truth_class"].eq("PIT_VERIFIED") & output["source_kind"].str.upper().map(
        lambda value: any(str(token).upper() in value for token in forbidden_tokens)
    )
    if forbidden_pit.any():
        raise ContractError("current_vintage_context_cannot_be_pit_verified")
    validate_session_binding(
        output,
        calendar,
        label="context",
        require_contiguous_slice=False,
    )
    for row in output[["decision_date", "decision_time_utc"]].itertuples(index=False):
        expected = metric_decision_times.get(row.decision_date)
        if expected is not None and pd.Timestamp(expected) != pd.Timestamp(row.decision_time_utc):
            raise ContractError(f"context_metric_decision_time_mismatch:{row.decision_date.date()}")
    for row in output[["decision_date", "nyse_session_ordinal", "calendar_source_sha256"]].itertuples(index=False):
        expected = metric_sessions.get(row.decision_date)
        if expected is not None and expected != (int(row.nyse_session_ordinal), str(row.calendar_source_sha256)):
            raise ContractError(f"context_calendar_mismatch:{row.decision_date.date()}")
    columns = contract.get("context_columns") or {}
    for column in columns.get("optional_numeric") or []:
        if column in output.columns:
            output[column] = [
                _parse_optional_numeric(value, label=column)
                for value in output[column]
            ]
    for column in ("spy_close", "spy_prior_2d_high", "spy_ma20"):
        if column in output.columns:
            present = output[column].notna()
            if (output.loc[present, column] <= 0.0).any():
                raise ContractError(f"invalid_context_numeric_range:{column}")
    ratio_column = "portfolio_fundamental_weak_ratio"
    if ratio_column in output.columns:
        present = output[ratio_column].notna()
        ratio = output.loc[present, ratio_column]
        if ((ratio < 0.0) | (ratio > 1.0)).any():
            raise ContractError(f"invalid_context_numeric_range:{ratio_column}")
    for column in columns.get("optional_boolean") or []:
        if column in output.columns:
            output[column] = [_parse_bool(value, label=column) for value in output[column]]
    return output.sort_values("decision_date").reset_index(drop=True)


def empirical_midrank(values: np.ndarray, current: float) -> float:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return math.nan
    less = int(np.sum(finite < current))
    equal = int(np.sum(finite == current))
    return 100.0 * (less + 0.5 * equal) / float(finite.size)


def compute_component_percentiles(metrics: pd.DataFrame, contract: Mapping[str, Any]) -> pd.DataFrame:
    percentile = contract["percentile"]
    window_years = int(percentile["window_years"])
    maximum_sessions = int(percentile["maximum_sessions"])
    minimum_observations = int(percentile["minimum_observations"])
    rows: list[dict[str, Any]] = []
    for component, group in metrics.groupby("component", sort=True):
        group = group.sort_values("decision_date").reset_index(drop=True)
        dates = group["decision_date"]
        values = group["raw_value"].to_numpy(dtype=float)
        direction = str(group.iloc[0]["risk_direction"])
        for index, source in group.iterrows():
            lower = source["decision_date"] - pd.DateOffset(years=window_years)
            eligible = np.flatnonzero((dates >= lower).to_numpy() & (dates <= source["decision_date"]).to_numpy())
            eligible = eligible[-maximum_sessions:]
            history = values[eligible]
            raw_percentile = empirical_midrank(history, float(source["raw_value"]))
            risk_percentile = raw_percentile if direction == "HIGH" else 100.0 - raw_percentile
            rows.append(
                {
                    "decision_date": source["decision_date"],
                    "decision_time_utc": source["decision_time_utc"],
                    "nyse_session_ordinal": int(source["nyse_session_ordinal"]),
                    "calendar_source_sha256": source["calendar_source_sha256"],
                    "axis": source["axis"],
                    "component": component,
                    "raw_value": float(source["raw_value"]),
                    "risk_direction": direction,
                    "raw_percentile": float(raw_percentile),
                    "risk_percentile": float(risk_percentile),
                    "history_observation_count": int(len(history)),
                    "component_ready": bool(len(history) >= minimum_observations),
                    "source_observation_date": source["source_observation_date"],
                    "available_from": source["available_from"],
                    "source_kind": source["source_kind"],
                    "source_sha256": source["source_sha256"],
                    "truth_class": source["truth_class"],
                }
            )
    return pd.DataFrame(rows).sort_values(["decision_date", "axis", "component"]).reset_index(drop=True)


def _worst_truth(values: Sequence[str], contract: Mapping[str, Any]) -> str | None:
    if not values:
        return None
    order = {name: index for index, name in enumerate(contract["truth_classes_in_quality_order"])}
    return min(values, key=lambda value: order[value])


def aggregate_axes(component_scores: pd.DataFrame, contract: Mapping[str, Any]) -> pd.DataFrame:
    red_threshold = float(contract["percentile"]["red_percentile"])
    rows: list[dict[str, Any]] = []
    dates = sorted(component_scores["decision_date"].drop_duplicates())
    for date in dates:
        date_rows = component_scores[component_scores["decision_date"] == date]
        decision_time = date_rows["decision_time_utc"].iloc[0]
        session_ordinal = int(date_rows["nyse_session_ordinal"].iloc[0])
        calendar_hash = str(date_rows["calendar_source_sha256"].iloc[0])
        for axis, spec in contract["axes"].items():
            observed = date_rows[date_rows["axis"] == axis]
            ready = observed[observed["component_ready"]]
            minimum = int(spec["minimum_ready_components"])
            axis_ready = len(ready) >= minimum
            score = float(ready["risk_percentile"].mean()) if axis_ready else math.nan
            source_bundle = [
                {
                    "component": row.component,
                    "source_sha256": row.source_sha256,
                    "available_from": row.available_from,
                }
                for row in ready.sort_values("component").itertuples(index=False)
            ]
            rows.append(
                {
                    "decision_date": date,
                    "decision_time_utc": decision_time,
                    "nyse_session_ordinal": session_ordinal,
                    "calendar_source_sha256": calendar_hash,
                    "axis": axis,
                    "weight": float(spec["weight"]),
                    "red_domain": spec["red_domain"],
                    "registered_component_count": int(len(spec["components"])),
                    "observed_component_count": int(len(observed)),
                    "ready_component_count": int(len(ready)),
                    "minimum_ready_components": minimum,
                    "ready_component_names": ";".join(sorted(ready["component"].astype(str))),
                    "axis_score": score,
                    "axis_ready": bool(axis_ready),
                    "red_axis": bool(axis_ready and score >= red_threshold),
                    "axis_available_from": ready["available_from"].max() if len(ready) else pd.NaT,
                    "source_hash_bundle_sha256": sha256_json(source_bundle) if source_bundle else None,
                    "truth_class": _worst_truth(list(ready["truth_class"].astype(str)), contract),
                }
            )
    return pd.DataFrame(rows).sort_values(["decision_date", "axis"]).reset_index(drop=True)


def classify_market_state(score: float, red_axes: int, red_domains: int, contract: Mapping[str, Any]) -> str:
    states = contract["state_machine"]
    fear = states["extreme_fear"]
    if (
        score >= float(fear["minimum_score"])
        and red_axes >= int(fear["minimum_red_axes"])
        and red_domains >= int(fear["minimum_red_domains"])
    ):
        return "EXTREME_FEAR"
    defense = states["risk_defense"]
    if score >= float(defense["minimum_score"]) and red_axes >= int(defense["minimum_red_axes"]):
        return "RISK_DEFENSE"
    alert = states["risk_alert"]
    if score >= float(alert["minimum_score"]) or red_axes >= int(alert["minimum_red_axes"]):
        return "RISK_ALERT"
    return "NORMAL"


def build_daily_risk(axis_scores: pd.DataFrame, context: pd.DataFrame, contract: Mapping[str, Any]) -> pd.DataFrame:
    required_axes = set(contract["readiness"]["required_axes"])
    minimum_axes = int(contract["readiness"]["minimum_ready_axes"])
    context_by_date = {row.decision_date: row for row in context.itertuples(index=False)}
    rows: list[dict[str, Any]] = []
    for date, group in axis_scores.groupby("decision_date", sort=True):
        ready = group[group["axis_ready"]]
        ready_names = set(ready["axis"].astype(str))
        state_change_allowed = len(ready) >= minimum_axes and required_axes.issubset(ready_names)
        ready_weight = float(ready["weight"].sum())
        score = (
            float((ready["axis_score"] * ready["weight"]).sum() / ready_weight)
            if state_change_allowed and ready_weight > 0
            else math.nan
        )
        red = ready[ready["red_axis"]]
        red_domains = int(red["red_domain"].nunique())
        state_source_bundle = [
            {
                "axis": row.axis,
                "axis_score": row.axis_score,
                "source_hash_bundle_sha256": row.source_hash_bundle_sha256,
            }
            for row in ready.sort_values("axis").itertuples(index=False)
        ]
        observed = (
            classify_market_state(score, int(len(red)), red_domains, contract)
            if state_change_allowed
            else "DATA_INSUFFICIENT"
        )
        context_row = context_by_date.get(date)
        weak_ratio = None
        if context_row is not None and hasattr(context_row, "portfolio_fundamental_weak_ratio"):
            value = getattr(context_row, "portfolio_fundamental_weak_ratio")
            if value is not None and not pd.isna(value):
                weak_ratio = float(value)
        fragility = bool(weak_ratio is not None and weak_ratio > float(contract["state_machine"]["portfolio_fragility_threshold"]))
        rows.append(
            {
                "decision_date": date,
                "decision_time_utc": group["decision_time_utc"].iloc[0],
                "nyse_session_ordinal": int(group["nyse_session_ordinal"].iloc[0]),
                "calendar_source_sha256": str(group["calendar_source_sha256"].iloc[0]),
                "state_source_hash_bundle_sha256": sha256_json(state_source_bundle),
                "risk_score": score,
                "ready_axis_count": int(len(ready)),
                "required_axes_ready": bool(required_axes.issubset(ready_names)),
                "ready_axis_weight": ready_weight,
                "red_axis_count": int(len(red)),
                "red_domain_count": red_domains,
                "red_axes": ";".join(sorted(red["axis"].astype(str))),
                "observed_state": observed,
                "state_change_allowed": bool(state_change_allowed),
                "new_buys_frozen": bool(not state_change_allowed),
                "portfolio_fundamental_weak_ratio": weak_ratio,
                "portfolio_fragility": fragility,
            }
        )
    return apply_state_hysteresis(pd.DataFrame(rows), contract)


def apply_state_hysteresis(daily: pd.DataFrame, contract: Mapping[str, Any]) -> pd.DataFrame:
    order = list(contract["state_machine"]["states_in_severity_order"])
    severity = {state: index for index, state in enumerate(order)}
    entry_required = int(contract["state_machine"]["entry_confirmation_sessions"])
    release_required = int(contract["state_machine"]["release_confirmation_sessions"])
    current = "DATA_INSUFFICIENT"
    entry_window: list[int] = []
    release_window: list[int] = []
    effective: list[str] = []
    entry_counts: list[int] = []
    release_counts: list[int] = []
    changed: list[bool] = []
    confidence_states: list[str] = []
    for row in daily.sort_values("decision_date").itertuples(index=False):
        previous = current
        observed = str(row.observed_state)
        if not bool(row.state_change_allowed) or observed == "DATA_INSUFFICIENT":
            entry_window = []
            release_window = []
        else:
            current_severity = severity.get(current, -1)
            observed_severity = severity[observed]
            if observed_severity > current_severity:
                release_window = []
                entry_window.append(observed_severity)
                entry_window = entry_window[-entry_required:]
                if len(entry_window) >= entry_required:
                    # Enter the lowest boundary sustained by every session in
                    # the confirmation window. Alert/defense alternation must
                    # therefore confirm at least alert instead of resetting.
                    current = order[min(entry_window)]
                    entry_window = []
            elif observed_severity < current_severity:
                entry_window = []
                release_window.append(observed_severity)
                release_window = release_window[-release_required:]
                if len(release_window) >= release_required:
                    # Release only to the highest severity that remained
                    # breached throughout the full confirmation window.
                    current = order[max(release_window)]
                    release_window = []
            else:
                entry_window = []
                release_window = []
        effective.append(current)
        entry_counts.append(len(entry_window))
        release_counts.append(len(release_window))
        changed.append(current != previous)
        if bool(row.portfolio_fragility) and current in severity:
            confidence_states.append(order[min(severity[current] + 1, len(order) - 1)])
        else:
            confidence_states.append(current)
    result = daily.sort_values("decision_date").reset_index(drop=True).copy()
    result["effective_state"] = effective
    result["entry_confirmation_count"] = entry_counts
    result["release_confirmation_count"] = release_counts
    result["state_changed"] = changed
    result["defense_confidence_state"] = confidence_states
    return result


def _component_percentile_lookup(component_scores: pd.DataFrame) -> dict[tuple[pd.Timestamp, str], float]:
    ready = component_scores[component_scores["component_ready"]]
    return {
        (row.decision_date, row.component): float(row.raw_percentile)
        for row in ready.itertuples(index=False)
    }


def _context_value(context_by_date: Mapping[pd.Timestamp, Any], date: pd.Timestamp, name: str) -> Any:
    row = context_by_date.get(date)
    if row is None or not hasattr(row, name):
        return None
    value = getattr(row, name)
    return None if value is None or pd.isna(value) else value


def _trailing_context_true(
    dates: list[pd.Timestamp],
    position: int,
    count: int,
    predicate,
    *,
    after_position: int | None = None,
) -> bool:
    if position + 1 < count:
        return False
    if after_position is not None and position - after_position < count:
        return False
    window = dates[position - count + 1 : position + 1]
    return all(bool(predicate(date)) for date in window)


def build_sentiment_history(
    market_states: pd.DataFrame,
    component_scores: pd.DataFrame,
    context: pd.DataFrame,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    greed_contract = contract["sentiment_overlay"]["extreme_greed"]
    tail = float(contract["percentile"]["greed_tail_percentile"])
    lookup = _component_percentile_lookup(component_scores)
    context_by_date = {row.decision_date: row for row in context.itertuples(index=False)}
    dates = list(market_states.sort_values("decision_date")["decision_date"])
    greed_active = False
    greed_entry = 0
    greed_release = 0
    fear_episode = False
    fear_peak = math.nan
    recovery_stage = 0
    recovery_stage_started_position: int | None = None
    rows: list[dict[str, Any]] = []
    for position, state_row in enumerate(market_states.sort_values("decision_date").itertuples(index=False)):
        date = state_row.decision_date
        vix_pct = lookup.get((date, "vix_level"))
        hy_pct = lookup.get((date, "hy_oas_level"))
        ig_pct = lookup.get((date, "ig_oas_level"))
        distance_pct = lookup.get((date, "spy_ma200_distance"))
        put_call_pct = lookup.get((date, "equity_put_call"))
        narrowing = _context_value(context_by_date, date, "index_new_high_breadth_narrowing")
        greed_values: dict[str, bool | None] = {
            "vix_lower_10pct": None if vix_pct is None else vix_pct <= tail,
            "hy_and_ig_spreads_lower_10pct": None if hy_pct is None or ig_pct is None else hy_pct <= tail and ig_pct <= tail,
            "spy_ma200_distance_upper_10pct": None if distance_pct is None else distance_pct >= 100.0 - tail,
            "equity_put_call_lower_10pct": None if put_call_pct is None else put_call_pct <= tail,
            "index_high_breadth_narrowing": None if narrowing is None else bool(narrowing),
        }
        greed_ready = all(value is not None for value in greed_values.values())
        greed_count = sum(value is True for value in greed_values.values())
        if greed_ready:
            if not greed_active:
                greed_entry = greed_entry + 1 if greed_count >= int(greed_contract["minimum_true_conditions"]) else 0
                if greed_entry >= int(greed_contract["entry_confirmation_sessions"]):
                    greed_active = True
                    greed_entry = 0
                    greed_release = 0
            else:
                if greed_count < int(greed_contract["release_below_condition_count"]):
                    greed_release += 1
                else:
                    greed_release = 0
                if greed_release >= int(greed_contract["release_confirmation_sessions"]):
                    greed_active = False
                    greed_release = 0
                    greed_entry = 0
        else:
            greed_entry = 0
            greed_release = 0

        effective = str(state_row.effective_state)
        risk_score = float(state_row.risk_score) if not pd.isna(state_row.risk_score) else math.nan
        if effective == "EXTREME_FEAR":
            if not fear_episode:
                fear_episode = True
                fear_peak = risk_score
                recovery_stage = 0
                recovery_stage_started_position = None
            else:
                if math.isfinite(risk_score):
                    fear_peak = max(fear_peak, risk_score) if math.isfinite(fear_peak) else risk_score
                if recovery_stage > 0:
                    recovery_stage = 0
                    recovery_stage_started_position = None
        elif effective == "NORMAL" and fear_episode:
            fear_episode = False
            fear_peak = math.nan
            recovery_stage = 0
            recovery_stage_started_position = None
        hy_pause_guard = _context_value(context_by_date, date, "hy_spread_widening")
        low_pause_guard = _context_value(context_by_date, date, "market_new_low")
        pause_guards_ready = hy_pause_guard is not None and low_pause_guard is not None
        paused = bool(hy_pause_guard is True or low_pause_guard is True)
        recovery_blocked = paused or not pause_guards_ready
        if fear_episode and recovery_blocked and recovery_stage in {1, 2}:
            recovery_stage_started_position = position
        stage_changed = False
        if (
            effective != "EXTREME_FEAR"
            and fear_episode
            and not recovery_blocked
            and math.isfinite(fear_peak)
            and math.isfinite(risk_score)
        ):
            if recovery_stage == 0:
                spy = _context_value(context_by_date, date, "spy_close")
                prior_high = _context_value(context_by_date, date, "spy_prior_2d_high")
                if spy is not None and prior_high is not None and fear_peak - risk_score >= 5.0 and float(spy) >= float(prior_high):
                    recovery_stage = 1
                    recovery_stage_started_position = position
                    stage_changed = True
            elif recovery_stage == 1:
                breadth_three = _trailing_context_true(
                    dates,
                    position,
                    3,
                    lambda item: _context_value(context_by_date, item, "breadth_improving") is True,
                    after_position=recovery_stage_started_position,
                )
                hy_widening = _context_value(context_by_date, date, "hy_spread_widening")
                if breadth_three and hy_widening is False:
                    recovery_stage = 2
                    recovery_stage_started_position = position
                    stage_changed = True
            elif recovery_stage == 2:
                recovered_two = _trailing_context_true(
                    dates,
                    position,
                    2,
                    lambda item: (
                        _context_value(context_by_date, item, "leadership_breadth_confirmed") is True
                        or (
                            _context_value(context_by_date, item, "spy_close") is not None
                            and _context_value(context_by_date, item, "spy_ma20") is not None
                            and float(_context_value(context_by_date, item, "spy_close"))
                            >= float(_context_value(context_by_date, item, "spy_ma20"))
                        )
                    ),
                    after_position=recovery_stage_started_position,
                )
                if recovered_two:
                    recovery_stage = 3
                    recovery_stage_started_position = position
                    stage_changed = True

        if effective == "EXTREME_FEAR":
            overlay = "EXTREME_FEAR"
        elif fear_episode and recovery_stage > 0 and effective != "NORMAL":
            overlay = "FEAR_RECOVERY"
        elif greed_active:
            overlay = "EXTREME_GREED"
        else:
            overlay = "NONE"
        rows.append(
            {
                "decision_date": date,
                "sentiment_overlay": overlay,
                "greed_condition_count": int(greed_count),
                "greed_conditions_ready": bool(greed_ready),
                "greed_entry_confirmation_count": int(greed_entry),
                "greed_release_confirmation_count": int(greed_release),
                "extreme_greed_active": bool(greed_active),
                "fear_episode_active": bool(fear_episode),
                "fear_peak_risk_score": fear_peak,
                "fear_recovery_stage": int(recovery_stage),
                "fear_recovery_stage_changed": bool(stage_changed),
                "fear_recovery_paused": bool(paused),
                "fear_recovery_pause_guards_ready": bool(pause_guards_ready),
                **greed_values,
            }
        )
    return pd.DataFrame(rows)


def _serialize_frame(frame: pd.DataFrame, path: Path) -> dict[str, Any]:
    output = frame.copy()
    for column in output.columns:
        if pd.api.types.is_datetime64_any_dtype(output[column]):
            output[column] = output[column].map(lambda value: value.isoformat() if not pd.isna(value) else "")
    output.to_csv(path, index=False, lineterminator="\n")
    return {**fingerprint(path), "row_count": int(len(output))}


def _safety_payload(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "research_only": True,
        "report_only": True,
        "stock_alpha_allowed": False,
        "selector_executed": False,
        "target_books_mutated": False,
        "trade_intents_written": False,
        "orders_generated": False,
        "ledger_mutated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "automatic_promotion_allowed": False,
        "contract_safety": contract["safety"],
    }


def blocked_payload(
    output_dir: Path,
    contract_path: Path,
    calendar_path: Path,
    input_path: Path,
    context_path: Path | None,
    error: str,
) -> dict[str, Any]:
    contract: dict[str, Any] = {}
    try:
        loaded_contract = json.loads(contract_path.read_text(encoding="utf-8"))
        if isinstance(loaded_contract, dict):
            contract = loaded_contract
    except Exception:
        pass
    safety = _safety_payload(contract) if contract.get("safety") else {
        "research_only": True,
        "report_only": True,
        "selector_executed": False,
        "target_books_mutated": False,
        "trade_intents_written": False,
        "orders_generated": False,
        "ledger_mutated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "automatic_promotion_allowed": False,
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "blockers": [error],
        "calendar_path": str(calendar_path),
        "input_metric_path": str(input_path),
        "input_context_path": str(context_path) if context_path else None,
        **safety,
    }
    write_json(output_dir / "manifest.json", payload)
    (output_dir / "report.md").write_text(
        "# Run287 Chameleon macro-risk report\n\n"
        f"- status: `{BLOCKED_STATUS}`\n"
        f"- blocker: `{error}`\n\n"
        "No state, target, order, or ledger output was accepted.\n",
        encoding="utf-8",
    )
    return payload


def cleanup_blocked_outputs(output_dir: Path) -> None:
    """Remove run-local evidence if a late contract check fails."""
    for path in output_dir.iterdir():
        if path.is_file():
            path.unlink()


def build(args: argparse.Namespace) -> dict[str, Any]:
    contract_path = repo_path(args.contract)
    calendar_path = repo_path(args.calendar)
    input_path = repo_path(args.input_metrics)
    context_path = repo_path(args.input_context) if str(args.input_context or "").strip() else None
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    try:
        code_identity_before = capture_code_identity()
        if not contract_path.is_file():
            raise ContractError(f"contract_input_missing:{contract_path}")
        if not calendar_path.is_file():
            raise ContractError(f"calendar_input_missing:{calendar_path}")
        if not input_path.is_file():
            raise ContractError(f"metric_input_missing:{input_path}")
        if context_path is not None and not context_path.is_file():
            raise ContractError(f"context_input_missing:{context_path}")
        input_fingerprints_before = {
            "contract": capture_input_fingerprint(contract_path, "contract"),
            "calendar": capture_input_fingerprint(calendar_path, "calendar"),
            "metrics": capture_input_fingerprint(input_path, "metrics"),
        }
        if context_path is not None:
            input_fingerprints_before["context"] = capture_input_fingerprint(
                context_path,
                "context",
            )
        contract = load_contract(contract_path)
        raw_metrics = read_table(input_path)
        missing_metric_columns = [
            column for column in METRIC_REQUIRED_COLUMNS if column not in raw_metrics.columns
        ]
        if missing_metric_columns:
            raise ContractError(f"missing_columns:{','.join(missing_metric_columns)}")
        calendar = validate_calendar(
            read_table(calendar_path),
            input_fingerprints_before["calendar"]["sha256"],
        )
        as_of_text = str(args.as_of or "").strip()
        requested_as_of = pd.to_datetime(as_of_text, errors="coerce") if as_of_text else None
        if as_of_text and pd.isna(requested_as_of):
            raise ContractError(f"invalid_explicit_as_of:{as_of_text}")
        if requested_as_of is None:
            parsed_dates = pd.to_datetime(raw_metrics["decision_date"], errors="coerce")
            if parsed_dates.isna().all():
                raise ContractError("metric_decision_dates_invalid")
            as_of = parsed_dates.max().normalize()
        else:
            requested_timestamp = pd.Timestamp(requested_as_of)
            if requested_timestamp.tzinfo is not None:
                requested_timestamp = requested_timestamp.tz_convert("UTC").tz_localize(None)
            as_of = requested_timestamp.normalize()
        metrics = validate_metrics(raw_metrics, contract, as_of, calendar)
        decision_times = {
            date: group["decision_time_utc"].iloc[0]
            for date, group in metrics.groupby("decision_date")
        }
        metric_sessions = {
            date: (
                int(group["nyse_session_ordinal"].iloc[0]),
                str(group["calendar_source_sha256"].iloc[0]),
            )
            for date, group in metrics.groupby("decision_date")
        }
        raw_context = read_table(context_path) if context_path is not None else None
        context = validate_context(
            raw_context,
            contract,
            as_of,
            decision_times,
            metric_sessions,
            calendar,
        )
        component_scores = compute_component_percentiles(metrics, contract)
        axis_scores = aggregate_axes(component_scores, contract)
        market_states = build_daily_risk(axis_scores, context, contract)
        sentiment = build_sentiment_history(market_states, component_scores, context, contract)
        latest_date = market_states["decision_date"].max()
        latest_state = market_states[market_states["decision_date"] == latest_date].iloc[-1].to_dict()
        latest_sentiment = sentiment[sentiment["decision_date"] == latest_date].iloc[-1].to_dict()
        latest_axes = axis_scores[axis_scores["decision_date"] == latest_date].to_dict(orient="records")
        truth_values = list(metrics["truth_class"].astype(str)) + list(context.get("truth_class", pd.Series(dtype=str)).astype(str))
        truth_class = _worst_truth(truth_values, contract) or "FREE_PROXY"
        outputs: dict[str, Any] = {}
        outputs["component_percentiles"] = _serialize_frame(component_scores, output_dir / "component_percentiles.csv")
        outputs["macro_risk_axes"] = _serialize_frame(axis_scores, output_dir / "macro_risk_axes.csv")
        outputs["market_state_history"] = _serialize_frame(market_states, output_dir / "market_state_history.csv")
        outputs["sentiment_overlay_history"] = _serialize_frame(sentiment, output_dir / "sentiment_overlay_history.csv")
        snapshot_payload = {
            "schema_version": "MacroRiskSnapshot-v1",
            "decision_date": latest_date.date().isoformat(),
            "risk_score": latest_state["risk_score"],
            "ready_axis_count": latest_state["ready_axis_count"],
            "required_axes_ready": latest_state["required_axes_ready"],
            "red_axis_count": latest_state["red_axis_count"],
            "red_domain_count": latest_state["red_domain_count"],
            "state_change_allowed": latest_state["state_change_allowed"],
            "new_buys_frozen": latest_state["new_buys_frozen"],
            "axes": latest_axes,
            "truth_class": truth_class,
            "report_only": True,
        }
        write_json(output_dir / "macro_risk_snapshot.json", snapshot_payload)
        outputs["macro_risk_snapshot"] = fingerprint(output_dir / "macro_risk_snapshot.json")
        market_payload = {
            "schema_version": "MarketState-v1",
            "decision_date": latest_date.date().isoformat(),
            "observed_state": latest_state["observed_state"],
            "effective_state": latest_state["effective_state"],
            "defense_confidence_state": latest_state["defense_confidence_state"],
            "portfolio_fragility": latest_state["portfolio_fragility"],
            "confirmation": {
                "entry_sessions": latest_state["entry_confirmation_count"],
                "release_sessions": latest_state["release_confirmation_count"],
            },
            "state_change_allowed": latest_state["state_change_allowed"],
            "new_buys_frozen": latest_state["new_buys_frozen"],
            "target_weights": None,
            "policy_handoff_implemented": False,
            "report_only": True,
        }
        write_json(output_dir / "market_state.json", market_payload)
        outputs["market_state"] = fingerprint(output_dir / "market_state.json")
        sentiment_payload = {
            "schema_version": "SentimentOverlay-v1",
            **{
                key: value
                for key, value in latest_sentiment.items()
                if key != "decision_date"
            },
            "decision_date": latest_date.date().isoformat(),
            "advisory_only": True,
            "trade_intent_generated": False,
        }
        write_json(output_dir / "sentiment_overlay.json", sentiment_payload)
        outputs["sentiment_overlay"] = fingerprint(output_dir / "sentiment_overlay.json")
        input_fingerprints_after = {
            "contract": capture_input_fingerprint(contract_path, "contract"),
            "calendar": capture_input_fingerprint(calendar_path, "calendar"),
            "metrics": capture_input_fingerprint(input_path, "metrics"),
        }
        if context_path is not None:
            input_fingerprints_after["context"] = capture_input_fingerprint(
                context_path,
                "context",
            )
        if input_fingerprints_before != input_fingerprints_after:
            raise ContractError("source_input_mutated_during_build")
        code_identity_after = capture_code_identity()
        if code_identity_before != code_identity_after:
            raise ContractError("code_identity_mutated_during_build")
        verified_inputs = input_fingerprints_after
        verified_code = code_identity_after
        truth_payload = {
            "schema_version": "BacktestTruthManifest-v1",
            "decision_date": latest_date.date().isoformat(),
            "truth_class": truth_class,
            "calendar_input": verified_inputs["calendar"],
            "metric_input": verified_inputs["metrics"],
            "context_input": verified_inputs.get("context"),
            "contract": verified_inputs["contract"],
            "code": verified_code,
            "cost_model": "NOT_APPLICABLE_REPORT_ONLY",
            "execution_model": "NOT_APPLICABLE_REPORT_ONLY",
            "integer_share_rule": "NOT_APPLICABLE_REPORT_ONLY",
            "delisting_rule": "INPUT_PRODUCER_RESPONSIBILITY_NO_RETURN_LABELS_CONSUMED",
            "historical_backtest_acceptance_allowed": False,
            "truth_class_supports_future_historical_ab": truth_class == "PIT_VERIFIED",
            "portfolio_backtest_executed": False,
        }
        write_json(output_dir / "backtest_truth_manifest.json", truth_payload)
        outputs["backtest_truth_manifest"] = fingerprint(output_dir / "backtest_truth_manifest.json")
        status = (
            "READY_CHAMELEON_MACRO_RISK_REPORT_ONLY"
            if bool(latest_state["state_change_allowed"])
            else "READY_CHAMELEON_MACRO_RISK_REPORT_ONLY_DATA_INSUFFICIENT"
        )
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "blockers": [],
            "decision_date": latest_date.date().isoformat(),
            "truth_class": truth_class,
            "source_inputs_unchanged": True,
            "network_requests_executed": 0,
            "latest": {
                "risk_score": latest_state["risk_score"],
                "observed_state": latest_state["observed_state"],
                "effective_state": latest_state["effective_state"],
                "sentiment_overlay": latest_sentiment["sentiment_overlay"],
                "fear_recovery_stage": latest_sentiment["fear_recovery_stage"],
                "state_change_allowed": latest_state["state_change_allowed"],
                "new_buys_frozen": latest_state["new_buys_frozen"],
            },
            "coverage": {
                "registered_axis_count": 10,
                "ready_axis_count": latest_state["ready_axis_count"],
                "required_axes_ready": latest_state["required_axes_ready"],
                "red_axis_count": latest_state["red_axis_count"],
                "red_domain_count": latest_state["red_domain_count"],
            },
            "inputs": {
                "metrics": verified_inputs["metrics"],
                "context": verified_inputs.get("context"),
                "calendar": verified_inputs["calendar"],
                "contract": verified_inputs["contract"],
            },
            "outputs": outputs,
            "code": verified_code,
            **_safety_payload(contract),
        }
        write_json(output_dir / "manifest.json", payload)
        (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
        return payload
    except ContractError as exc:
        cleanup_blocked_outputs(output_dir)
        return blocked_payload(
            output_dir,
            contract_path,
            calendar_path,
            input_path,
            context_path,
            str(exc),
        )


def render_report(payload: Mapping[str, Any]) -> str:
    latest = payload.get("latest") or {}
    coverage = payload.get("coverage") or {}
    lines = [
        "# Run287 Chameleon ten-axis macro-risk report",
        "",
        f"- status: `{payload.get('status')}`",
        f"- decision date: `{payload.get('decision_date')}`",
        f"- truth class: `{payload.get('truth_class')}`",
        f"- risk score: `{latest.get('risk_score')}`",
        f"- observed/effective state: `{latest.get('observed_state')}` / `{latest.get('effective_state')}`",
        f"- sentiment overlay: `{latest.get('sentiment_overlay')}`",
        f"- ready axes: `{coverage.get('ready_axis_count')}` / `10`",
        f"- required axes ready: `{coverage.get('required_axes_ready')}`",
        f"- new buys frozen by data readiness: `{latest.get('new_buys_frozen')}`",
        "",
        "This artifact is observation-only. It does not select stocks, write",
        "target weights or TradeIntent rows, generate orders, mutate a ledger,",
        "run a backtest/fullrun, or enable production/live trading.",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calendar", required=True)
    parser.add_argument("--input-metrics", required=True)
    parser.add_argument("--input-context", default="")
    parser.add_argument("--as-of", default="")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(json_safe(payload), indent=2, sort_keys=True, allow_nan=False))
    return 0 if str(payload.get("status", "")).startswith("READY_") else 2


if __name__ == "__main__":
    raise SystemExit(main())

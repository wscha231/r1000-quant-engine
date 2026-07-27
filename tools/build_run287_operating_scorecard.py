#!/usr/bin/env python3
"""Build the private Run287 operating scorecard from validated artifacts.

The scorecard stores metric values plus provenance; it does not copy source
artifacts. Historical, current-paper, and true-forward evidence keep separate
statuses, and forward observations can never replace historical acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from tools.run287_promotion_gate import gate_for_consumer
except ModuleNotFoundError:  # direct `python tools/...` execution
    from run287_promotion_gate import gate_for_consumer


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "run287-operating-scorecard-v1"
SECTIONS = (
    "selection_quality",
    "holding_quality",
    "exit_quality",
    "risk_defense",
    "reentry",
    "reserve",
    "execution",
    "integrity",
    "forward_evidence",
)
RESERVE_REASONS = (
    "crisis_reserve",
    "capacity_unallocated",
    "reentry_pending",
    "data_block_reserve",
    "transaction_buffer",
    "residual_cash",
)
PAPER_INTEGRITY_FIELDS = (
    "account_reset_count",
    "duplicate_client_order_id_count",
    "same_day_fill_count",
    "stale_close_count",
    "future_close_count",
    "missing_exact_close_count",
    "hash_chain_break_count",
    "lifecycle_unresolved_count",
    "degraded_data_day_count",
)
EVIDENCE_LANES = ("historical", "current_paper_execution", "true_forward")
CANONICAL_SOURCE_PREFIX = "data_static/run287_operating_scorecard_sources_v1/"
CANONICAL_SOURCE_ROOT = (
    REPO_ROOT / CANONICAL_SOURCE_PREFIX.rstrip("/")
).resolve()


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def clean_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, str)):
        return value
    if finite(value):
        return float(value)
    return None


def strict_session_date(value: Any, *, label: str) -> str:
    text = str(value or "")
    parsed = pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
    if pd.isna(parsed) or pd.Timestamp(parsed).strftime("%Y-%m-%d") != text:
        raise ValueError(f"{label}:invalid_session_date")
    return text


def accepted_close_curve_metrics(
    path: Path,
    *,
    expected_session_date: str,
) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"accepted_close_curve_missing:{path}")
    frame = pd.read_csv(path, low_memory=False)
    required = {"date", "equity_usd", "record_type"}
    if frame.empty or not required.issubset(frame.columns):
        raise ValueError(f"accepted_close_curve_schema_invalid:{path}")
    dates = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="coerce")
    equity = pd.to_numeric(frame["equity_usd"], errors="coerce")
    record_types = frame["record_type"].fillna("").astype(str)
    valid_record_types = record_types.eq("FORWARD_MARK").all() or (
        len(record_types) > 1
        and record_types.iloc[0] == "SEED_ACCOUNT"
        and record_types.iloc[1:].eq("FORWARD_MARK").all()
    )
    if (
        dates.isna().any()
        or equity.isna().any()
        or not (equity > 0).all()
        or dates.duplicated().any()
        or not dates.is_monotonic_increasing
        or not valid_record_types
    ):
        raise ValueError(f"accepted_close_curve_rows_invalid:{path}")
    start_date = pd.Timestamp(dates.iloc[0]).date().isoformat()
    end_date = pd.Timestamp(dates.iloc[-1]).date().isoformat()
    if end_date != expected_session_date:
        raise ValueError(
            "accepted_close_curve_stale:"
            f"{path}:{end_date}!={expected_session_date}"
        )
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    elapsed_days = int((dates.iloc[-1] - dates.iloc[0]).days)
    powered = len(frame) >= 252 and elapsed_days >= 300
    cagr = None
    if powered:
        cagr = float(
            (float(equity.iloc[-1]) / float(equity.iloc[0]))
            ** (365.25 / elapsed_days)
            - 1.0
        )
    return {
        "status": "MEASURED" if powered else "UNDERPOWERED",
        "metric_mode": (
            "accepted_exact_close_paper_marks_including_durable_catchup"
        ),
        "start_date": start_date,
        "end_date": end_date,
        "observations": int(len(frame)),
        "elapsed_days": elapsed_days,
        "starting_equity_usd": float(equity.iloc[0]),
        "ending_equity_usd": float(equity.iloc[-1]),
        "total_return": float(
            float(equity.iloc[-1]) / float(equity.iloc[0]) - 1.0
        ),
        "max_drawdown": float(drawdown.min()),
        "cagr": cagr,
        "cagr_status": "MEASURED" if powered else "UNDERPOWERED",
        "durable_catchup_marks_included": True,
        "historical_metric_replacement_allowed": False,
    }


def chain_link_latest_close(
    *,
    historical: dict[str, Any],
    operating: dict[str, Any],
    expected_session_date: str,
) -> dict[str, Any]:
    start_date = strict_session_date(
        historical.get("start_date"),
        label="historical_start_date",
    )
    historical_end_date = strict_session_date(
        historical.get("end_date"),
        label="historical_end_date",
    )
    operating_start_date = strict_session_date(
        operating.get("start_date"),
        label="operating_start_date",
    )
    if historical_end_date >= operating_start_date:
        raise ValueError(
            "historical_and_operating_windows_overlap:"
            f"{historical_end_date}>={operating_start_date}"
        )
    start_equity = float(historical.get("starting_capital_usd"))
    historical_end_equity = float(historical.get("ending_capital_usd"))
    paper_start_equity = float(operating.get("starting_equity_usd"))
    paper_end_equity = float(operating.get("ending_equity_usd"))
    historical_mdd = float(historical.get("max_dd"))
    for label, value in (
        ("historical_starting_capital", start_equity),
        ("historical_ending_capital", historical_end_equity),
        ("paper_starting_equity", paper_start_equity),
        ("paper_ending_equity", paper_end_equity),
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{label}:positive_finite_required")
    if not math.isfinite(historical_mdd) or not -1.0 < historical_mdd <= 0:
        raise ValueError("historical_max_drawdown_invalid")
    chain_end_equity = historical_end_equity * (
        paper_end_equity / paper_start_equity
    )
    elapsed_days = int(
        (
            pd.Timestamp(expected_session_date)
            - pd.Timestamp(start_date)
        ).days
    )
    if elapsed_days <= 0:
        raise ValueError("chain_link_elapsed_days_invalid")
    cagr = float(
        (chain_end_equity / start_equity)
        ** (365.25 / elapsed_days)
        - 1.0
    )
    operating_mdd = float(operating.get("max_drawdown"))
    return {
        "status": "LATEST_CLOSE_DIAGNOSTIC",
        "metric_mode": (
            "locked_historical_endpoint_chain_linked_to_accepted_paper_marks"
        ),
        "start_date": start_date,
        "historical_end_date": historical_end_date,
        "operating_start_date": operating_start_date,
        "end_date": expected_session_date,
        "elapsed_days": elapsed_days,
        "cagr": cagr,
        "max_drawdown": min(historical_mdd, operating_mdd),
        "historical_max_drawdown": historical_mdd,
        "operating_since_seed_max_drawdown": operating_mdd,
        "max_drawdown_exact": False,
        "max_drawdown_bound_direction": (
            "optimistic_lower_bound_on_loss_magnitude;"
            "exact_chain_mdd_can_be_more_negative"
        ),
        "max_drawdown_method": (
            "minimum_of_locked_historical_mdd_and_paper_operating_mdd"
        ),
        "max_drawdown_limitation": (
            "This is an optimistic lower bound on drawdown loss magnitude. "
            "The exact chain MDD can be more negative when the historical "
            "endpoint was already below its prior peak. Exact cross-boundary "
            "MDD requires the complete historical equity curve; the locked "
            "historical MDD and accepted paper path are preserved separately."
        ),
        "cagr_endpoint_chain_exact": True,
        "historical_metric_replacement_allowed": False,
        "promotion_evidence_allowed": False,
    }


def build_latest_close_performance(
    *,
    verified_paper: dict[str, Any] | None,
    paper_root: Path | None,
    paper_snapshot_hash: str | None,
    p5: dict[str, Any] | None,
    p5_source_sha256: str | None,
    expected_session_date: str | None,
) -> tuple[dict[str, Any], list[str]]:
    base = {
        "schema_version": "run287-latest-close-performance-v1",
        "status": "UNAVAILABLE",
        "as_of_date": None,
        "expected_session_date": expected_session_date,
        "paper_snapshot_hash": paper_snapshot_hash,
        "historical_source_sha256": p5_source_sha256,
        "portfolios": {},
        "review_only": True,
        "live_trading_enabled": False,
        "production_activation_allowed": False,
        "historical_cagr_mdd_replacement_allowed": False,
        "promotion_evidence_allowed": False,
        "fullrun_executed": False,
    }
    if not isinstance(verified_paper, dict) or paper_root is None:
        return base, ["latest_close_paper_snapshot_unavailable"]
    if not isinstance(p5, dict):
        return base, ["latest_close_historical_baseline_unavailable"]
    errors: list[str] = []
    paper_as_of = str(verified_paper.get("as_of_date") or "")
    try:
        paper_as_of = strict_session_date(
            paper_as_of,
            label="paper_summary_as_of_date",
        )
    except ValueError as exc:
        errors.append(str(exc))
    expected = str(expected_session_date or paper_as_of)
    try:
        expected = strict_session_date(
            expected,
            label="expected_session_date",
        )
    except ValueError as exc:
        errors.append(str(exc))
    base["as_of_date"] = paper_as_of or None
    base["expected_session_date"] = expected or None
    if paper_as_of and expected and paper_as_of != expected:
        errors.append(
            f"latest_close_paper_summary_stale:{paper_as_of}!={expected}"
        )
    if (
        verified_paper.get("status") != "completed"
        or verified_paper.get("review_only") is not True
        or verified_paper.get("live_trading_enabled") is not False
        or verified_paper.get("production_mutation_allowed") is not False
        or verified_paper.get(
            "historical_cagr_mdd_replacement_allowed"
        ) is not False
    ):
        errors.append("latest_close_paper_safety_contract_invalid")
    if p5.get("control_parity_passed") is not True:
        errors.append("latest_close_historical_control_parity_failed")
    p5_portfolios = (
        p5.get("portfolios")
        if isinstance(p5.get("portfolios"), dict)
        else {}
    )
    paper_portfolios = (
        verified_paper.get("portfolios")
        if isinstance(verified_paper.get("portfolios"), dict)
        else {}
    )
    for portfolio in ("main", "concentrated"):
        try:
            paper_manifest = paper_portfolios.get(portfolio)
            if (
                not isinstance(paper_manifest, dict)
                or paper_manifest.get("as_of_date") != expected
                or paper_manifest.get("review_only") is not True
                or paper_manifest.get("live_trading_enabled") is not False
                or paper_manifest.get("production_mutation_allowed") is not False
                or paper_manifest.get(
                    "historical_cagr_mdd_replacement_allowed"
                ) is not False
            ):
                raise ValueError(
                    f"latest_close_paper_manifest_invalid:{portfolio}"
                )
            historical = (
                p5_portfolios.get(portfolio, {})
                .get("windows", {})
                .get("full", {})
                .get("control", {})
            )
            if (
                not isinstance(historical, dict)
                or historical.get("status") != "completed"
            ):
                raise ValueError(
                    f"latest_close_historical_full_window_missing:{portfolio}"
                )
            operating = accepted_close_curve_metrics(
                paper_root / portfolio / "equity_curve.csv",
                expected_session_date=expected,
            )
            declared_forward = paper_manifest.get("forward_metrics")
            if not isinstance(declared_forward, dict):
                raise ValueError(
                    f"latest_close_forward_metrics_missing:{portfolio}"
                )
            forward_observations = int(
                declared_forward.get("observations") or 0
            )
            if (
                forward_observations < 0
                or forward_observations > operating["observations"]
            ):
                raise ValueError(
                    f"latest_close_forward_observation_count_invalid:{portfolio}"
                )
            base["portfolios"][portfolio] = {
                "historical_locked": {
                    "status": "LOCKED_HISTORICAL_BASELINE",
                    "start_date": historical.get("start_date"),
                    "end_date": historical.get("end_date"),
                    "cagr": clean_scalar(historical.get("cagr")),
                    "max_drawdown": clean_scalar(
                        historical.get("max_dd")
                    ),
                    "historical_metric_replacement_allowed": False,
                },
                "operating_since_seed": {
                    **operating,
                    "forward_only_observations": forward_observations,
                    "non_forward_or_durable_catchup_observations": (
                        operating["observations"] - forward_observations
                    ),
                },
                "latest_close_chain_linked": chain_link_latest_close(
                    historical=historical,
                    operating=operating,
                    expected_session_date=expected,
                ),
            }
        except (TypeError, ValueError) as exc:
            errors.append(str(exc))
    if errors:
        return {
            **base,
            "status": "INTEGRITY_ERROR",
            "errors": sorted(set(errors)),
        }, sorted(set(errors))
    return {
        **base,
        "status": "READY_LATEST_CLOSE_REVIEW_ONLY",
        "errors": [],
        "latest_close_exact": True,
        "accepted_close_marks_include_durable_catchup": True,
    }, []


def load_registry(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "run287-operating-scorecard-source-registry-v1":
        raise ValueError("source registry schema mismatch")
    ids = [str(row.get("id") or "") for row in payload.get("sources", [])]
    if not ids or len(ids) != len(set(ids)) or any(not value for value in ids):
        raise ValueError("source ids must be present and unique")
    return payload


def verify_canonical_source_bundle(
    registry: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Verify the committed immutable source bundle against the source registry."""
    managed = {
        str(row["id"]): row
        for row in registry.get("sources", [])
        if row.get("required") is True
        and str(row.get("disposition") or "") == "ABSORBED_SOURCE"
    }
    spec = registry.get("canonical_source_bundle_manifest")
    record: dict[str, Any] = {
        "status": "NOT_REQUIRED" if not managed else "UNVERIFIED",
        "path": None,
        "sha256": None,
        "expected_sha256": None,
        "source_count": 0,
        "verified_source_count": 0,
    }
    errors: list[str] = []
    if not managed:
        return record, errors
    if not isinstance(spec, dict) or not str(spec.get("path") or "").strip():
        return record, ["canonical_source_bundle_manifest_missing"]
    path = repo_path(str(spec["path"]))
    record.update(
        {
            "path": str(path),
            "expected_sha256": str(spec.get("expected_sha256") or "").lower(),
        }
    )
    if not record["expected_sha256"]:
        return record, [
            "canonical_source_bundle_manifest_expected_sha256_missing"
        ]
    if not path_is_within(path, CANONICAL_SOURCE_ROOT):
        return record, [
            "canonical_source_bundle_manifest_outside_canonical_root"
        ]
    if not path.is_file():
        return record, ["canonical_source_bundle_manifest_unavailable"]
    actual_hash = sha256_file(path)
    record["sha256"] = actual_hash
    manifest_hash_mismatch = bool(
        record["expected_sha256"]
        and actual_hash != record["expected_sha256"]
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        parse_errors = [
            f"canonical_source_bundle_manifest_parse_error:{type(exc).__name__}"
        ]
        if manifest_hash_mismatch:
            parse_errors.append("canonical_source_bundle_manifest_hash_mismatch")
        return record, sorted(parse_errors)
    if payload.get("schema_version") != "run287-operating-scorecard-source-bundle-v1":
        errors.append("canonical_source_bundle_manifest_schema_mismatch")
    if payload.get("immutable") is not True:
        errors.append("canonical_source_bundle_not_immutable")
    items = payload.get("sources")
    if not isinstance(items, list):
        items = []
        errors.append("canonical_source_bundle_sources_invalid")
    item_ids = [
        str(item.get("id") or "")
        for item in items
        if isinstance(item, dict) and str(item.get("id") or "")
    ]
    if len(item_ids) != len(items):
        errors.append("canonical_source_bundle_source_entry_invalid")
    by_id = {
        str(item.get("id") or ""): item
        for item in items
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    record["source_count"] = len(by_id)
    for source_id in sorted({value for value in item_ids if item_ids.count(value) > 1}):
        errors.append(f"canonical_source_bundle_source_id_duplicate:{source_id}")
    for source_id in sorted(set(managed) - set(by_id)):
        errors.append(
            f"canonical_source_bundle_manifest_source_missing:{source_id}"
        )
    for source_id in sorted(set(by_id) - set(managed)):
        errors.append(
            f"canonical_source_bundle_manifest_source_unregistered:{source_id}"
        )
    for source_id, source in managed.items():
        item = by_id.get(source_id)
        if not isinstance(item, dict):
            continue
        source_path = repo_path(str(source.get("path") or ""))
        item_path = repo_path(str(item.get("path") or ""))
        source_inside_root = path_is_within(source_path, CANONICAL_SOURCE_ROOT)
        item_inside_root = path_is_within(item_path, CANONICAL_SOURCE_ROOT)
        if not source_inside_root:
            errors.append(
                f"canonical_source_bundle_source_outside_root:{source_id}"
            )
        if not item_inside_root:
            errors.append(
                f"canonical_source_bundle_manifest_path_outside_root:{source_id}"
            )
        if item_path.resolve() != source_path.resolve():
            errors.append(f"canonical_source_bundle_path_mismatch:{source_id}")
        manifest_hash = str(item.get("sha256") or "").lower()
        registry_hash = str(source.get("expected_sha256") or "").lower()
        if not manifest_hash or manifest_hash != registry_hash:
            errors.append(f"canonical_source_bundle_hash_mismatch:{source_id}")
        if not source_inside_root:
            continue
        if not source_path.is_file():
            errors.append(f"canonical_source_bundle_source_missing:{source_id}")
        elif not manifest_hash or sha256_file(source_path) != manifest_hash:
            errors.append(
                f"canonical_source_bundle_source_hash_mismatch:{source_id}"
            )
        else:
            record["verified_source_count"] += 1
    if manifest_hash_mismatch:
        scoped_source_ids = sorted({
            token
            for value in errors
            for token in value.split(":")[1:]
            if token in managed
        })
        global_errors = [
            value for value in errors
            if not any(token in managed for token in value.split(":")[1:])
        ]
        if scoped_source_ids and not global_errors:
            errors.extend(
                f"canonical_source_bundle_manifest_hash_mismatch:{source_id}"
                for source_id in scoped_source_ids
            )
        else:
            errors.append("canonical_source_bundle_manifest_hash_mismatch")
    record["status"] = "VERIFIED" if not errors else "INTEGRITY_ERROR"
    return record, sorted(set(errors))


def validate_metric_migration(previous: dict[str, Any], registry: dict[str, Any]) -> None:
    if previous.get("metric_definition_version") != registry.get("metric_definition_version") \
            and not str(registry.get("migration_note") or "").strip():
        raise ValueError("metric definition changed without migration note")


def load_sources(registry: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    loaded: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for spec in registry["sources"]:
        source_id = str(spec["id"])
        path = repo_path(spec["path"])
        record = {
            "source_id": source_id,
            "evidence_class": spec["evidence_class"],
            "section": spec["section"],
            "path": str(path),
            "as_of_date": spec.get("as_of_date"),
            "metric_mode": spec["metric_mode"],
            "required": bool(spec.get("required")),
            "disposition": spec.get("disposition", "SOURCE"),
            "status": "UNAVAILABLE",
            "sha256": None,
            "expected_sha256": spec.get("expected_sha256"),
        }
        if not path.is_file():
            if record["required"]:
                errors.append(f"required_source_missing:{source_id}")
            records.append(record)
            continue
        actual_hash = sha256_file(path)
        record["sha256"] = actual_hash
        expected = str(spec.get("expected_sha256") or "").lower()
        if expected and actual_hash.lower() != expected:
            record["status"] = "INTEGRITY_ERROR"
            errors.append(f"source_hash_mismatch:{source_id}")
            records.append(record)
            continue
        try:
            if spec["format"] == "json":
                loaded[source_id] = json.loads(path.read_text(encoding="utf-8"))
            elif spec["format"] == "csv":
                loaded[source_id] = pd.read_csv(path, low_memory=False)
            else:
                raise ValueError(f"unsupported format:{spec['format']}")
        except Exception as exc:
            record["status"] = "INTEGRITY_ERROR"
            errors.append(f"source_parse_error:{source_id}:{type(exc).__name__}")
            records.append(record)
            continue
        record["status"] = "VERIFIED"
        records.append(record)
    return loaded, records, errors


def build_scorecard(
    registry: dict[str, Any], *, source_registry_path: Path,
    promotion_state_path: Path | None = None,
    expected_session_date: str | None = None,
) -> dict[str, Any]:
    loaded, source_records, source_integrity_errors = load_sources(registry)
    records_by_id = {row["source_id"]: row for row in source_records}
    source_specs_by_id = {
        str(row["id"]): row for row in registry.get("sources", [])
    }
    lane_integrity_errors: dict[str, list[str]] = {
        lane: [] for lane in EVIDENCE_LANES
    }
    managed_source_ids = {
        source_id
        for source_id, spec in source_specs_by_id.items()
        if spec.get("required") is True
        and str(spec.get("disposition") or "") == "ABSORBED_SOURCE"
    }

    def record_integrity_error(lane: str, value: str) -> None:
        resolved_lane = lane if lane in lane_integrity_errors else "historical"
        lane_integrity_errors[resolved_lane].append(value)

    for value in source_integrity_errors:
        parts = value.split(":")
        source_id = parts[1] if len(parts) > 1 else ""
        lane = str(
            source_specs_by_id.get(source_id, {}).get("evidence_class") or "historical"
        )
        record_integrity_error(lane, value)
    source_bundle, source_bundle_errors = verify_canonical_source_bundle(registry)
    for value in source_bundle_errors:
        affected_source_ids = [
            token for token in value.split(":")[1:]
            if token in managed_source_ids
        ]
        if affected_source_ids:
            for source_id in affected_source_ids:
                lane = str(
                    source_specs_by_id[source_id].get("evidence_class")
                    or "historical"
                )
                record_integrity_error(lane, value)
        else:
            managed_lanes = {
                str(row.get("evidence_class") or "historical")
                for row in source_specs_by_id.values()
                if row.get("required") is True
                and str(row.get("disposition") or "") == "ABSORBED_SOURCE"
            }
            for lane in managed_lanes or {"historical"}:
                record_integrity_error(lane, value)
    if source_bundle.get("status") not in {"VERIFIED", "NOT_REQUIRED"}:
        scoped_failed_source_ids = {
            token
            for value in source_bundle_errors
            for token in value.split(":")[1:]
            if token in managed_source_ids
        }
        has_global_bundle_error = any(
            not any(
                token in managed_source_ids
                for token in value.split(":")[1:]
            )
            for value in source_bundle_errors
        )
        rejected_source_ids = (
            managed_source_ids
            if has_global_bundle_error
            else scoped_failed_source_ids
        )
        for source_id in rejected_source_ids:
            loaded.pop(source_id, None)
            if source_id in records_by_id:
                records_by_id[source_id]["status"] = "BUNDLE_INTEGRITY_ERROR"
        source_bundle["rejected_source_ids"] = sorted(rejected_source_ids)
    metrics: list[dict[str, Any]] = []

    def add(
        section: str,
        metric_id: str,
        value: Any,
        source_id: str,
        *,
        evidence_class: str,
        status: str | None = None,
        portfolio: str | None = None,
        unit: str = "value",
        note: str = "",
        provenance_override: dict[str, Any] | None = None,
    ) -> None:
        source = records_by_id.get(source_id, {})
        resolved_status = status or ("AVAILABLE" if value is not None else "UNAVAILABLE")
        provenance = {
            "source_id": source_id,
            "source_path": source.get("path"),
            "source_sha256": source.get("sha256"),
            "as_of_date": source.get("as_of_date"),
            "metric_mode": source.get("metric_mode"),
        }
        if provenance_override:
            provenance.update(provenance_override)
        metrics.append({
            "section": section,
            "metric_id": metric_id,
            "portfolio": portfolio,
            "evidence_class": evidence_class,
            "status": resolved_status,
            "value": clean_scalar(value),
            "unit": unit,
            "note": note,
            "provenance": provenance,
        })

    p6 = loaded.get("p6_selection_summary")
    p6_metrics = loaded.get("p6_selection_metrics")
    if records_by_id.get("p6_selection_summary", {}).get("status") != "VERIFIED":
        p6 = None
        p6_metrics = None
    elif isinstance(p6, dict) and (
        str(p6.get("status") or "").upper().startswith("BLOCKED_")
        or p6.get("valid_for_scorecard_absorption") is False
        or p6.get("downstream_outcome_evaluation_executed") is False
    ):
        record_integrity_error(
            "historical", "p6_source_invalid_for_scorecard_absorption"
        )
        p6 = None
        p6_metrics = None
    if isinstance(p6, dict):
        stability = p6.get("rank_stability", {})
        for metric_id, key in (
            ("score_spearman_adjacent_decisions", "mean_score_spearman"),
            ("top10_overlap_adjacent_decisions", "mean_top_10_overlap"),
            ("top30_overlap_adjacent_decisions", "mean_top_30_overlap"),
        ):
            add("selection_quality", metric_id, stability.get(key), "p6_selection_summary",
                evidence_class="historical", unit="ratio")
        add("selection_quality", "sector_etf_excess", None, "p6_selection_summary",
            evidence_class="historical", status=str(p6.get("sector_etf_excess_status") or "UNAVAILABLE"),
            note="Sector-neutral excess is available; pinned sector-ETF history is not.")
    else:
        add("selection_quality", "selection_summary", None, "p6_selection_summary",
            evidence_class="historical")
    if isinstance(p6_metrics, pd.DataFrame):
        for row in p6_metrics.to_dict("records"):
            portfolio = str(row.get("portfolio"))
            cohort = str(row.get("cohort"))
            window = str(row.get("window"))
            horizon = int(row.get("horizon_sessions"))
            prefix = f"{window}_{cohort}_{horizon}d"
            for column, unit in (
                ("mean_return", "return"),
                ("mean_spy_excess", "return"),
                ("mean_qqq_excess", "return"),
                ("mean_sector_neutral_excess", "return"),
            ):
                add("selection_quality", f"{prefix}_{column}", row.get(column),
                    "p6_selection_metrics", evidence_class="historical",
                    portfolio=portfolio, unit=unit)

    p5 = loaded.get("p5_hold_exit")
    headlines: dict[str, Any] = {}
    if isinstance(p5, dict):
        if not bool(p5.get("control_parity_passed")):
            record_integrity_error("historical", "p5_control_parity_failed")
        for portfolio in ("main", "concentrated"):
            pdata = p5.get("portfolios", {}).get(portfolio, {})
            expected = pdata.get("control_parity", {}).get("expected", {})
            headlines[portfolio] = {
                "cagr": clean_scalar(expected.get("cagr")),
                "max_drawdown": clean_scalar(expected.get("max_dd")),
                "sharpe": clean_scalar(expected.get("sharpe")),
                "trade_count": clean_scalar(expected.get("trade_count")),
                "fees_usd": clean_scalar(expected.get("total_fees_usd")),
                "source_id": "p5_hold_exit",
            }
            holding = pdata.get("holding_statistics", {})
            for metric_id, key, unit in (
                ("completed_lot_count", "completed_lot_count", "count"),
                ("median_holding_days", "median_holding_days", "days"),
                ("pct_held_365d_plus", "pct_held_365d_plus", "ratio"),
                ("exit_reentry_churn_63d", "exit_reentry_churn_63_sessions", "count"),
            ):
                add("holding_quality", metric_id, holding.get(key), "p5_hold_exit",
                    evidence_class="historical", portfolio=portfolio, unit=unit)
            add("holding_quality", "mean_holding_days", None, "p5_hold_exit",
                evidence_class="historical", portfolio=portfolio, unit="days")
            add("holding_quality", "durable_winner_contribution", None, "p5_hold_exit",
                evidence_class="historical", portfolio=portfolio, unit="return")
            add("holding_quality", "thesis_state_changes", None, "p5_hold_exit",
                evidence_class="historical", portfolio=portfolio, unit="count")
            for taxonomy, count in sorted(pdata.get("sell_taxonomy_counts", {}).items()):
                add("exit_quality", f"exit_count_{taxonomy.lower()}", count, "p5_hold_exit",
                    evidence_class="historical", portfolio=portfolio, unit="count")
            counter = pdata.get("counterfactual_summary", {})
            counter_status = "UNDERPOWERED" if counter.get("status") == "NO_EVENTS" else "AVAILABLE"
            for metric_id in ("sold_vs_replacement_forward_return", "premature_sell_regret", "avoided_drawdown"):
                add("exit_quality", metric_id, None, "p5_hold_exit",
                    evidence_class="historical", portfolio=portfolio,
                    status=counter_status, unit="return")
            for bps, values in sorted(pdata.get("cost_sensitivity", {}).items()):
                add("execution", f"fees_{bps}", values.get("control_fees"), "p5_hold_exit",
                    evidence_class="historical", portfolio=portfolio, unit="usd")
                add("execution", f"cagr_{bps}", values.get("control_cagr"), "p5_hold_exit",
                    evidence_class="historical", portfolio=portfolio, unit="return")
            add("execution", "trade_count_25bps", expected.get("trade_count"), "p5_hold_exit",
                evidence_class="historical", portfolio=portfolio, unit="count")
            for metric_id, unit in (
                ("target_tracking_error", "weight"), ("pending_fill_lag", "days"),
                ("rejected_order_count", "count"), ("unfilled_order_count", "count"),
                ("slippage", "return"),
            ):
                add("execution", metric_id, None, "current_paper_summary",
                    evidence_class="current_paper_execution", portfolio=portfolio, unit=unit)
    else:
        for portfolio in ("main", "concentrated"):
            headlines[portfolio] = {"cagr": None, "max_drawdown": None, "sharpe": None,
                                    "trade_count": None, "fees_usd": None, "source_id": "p5_hold_exit"}

    for portfolio, source_id in (("main", "p3_main_crisis"), ("concentrated", "p3_concentrated_crisis")):
        crisis = loaded.get(source_id)
        if not isinstance(crisis, dict):
            for metric_id in ("defense_episode_count", "false_defense_episode_count", "detection_lead_lag_days",
                              "reserve_target_reach_days", "avoided_drawdown", "missed_rebound"):
                add("risk_defense", metric_id, None, source_id, evidence_class="historical", portfolio=portfolio)
            continue
        state = crisis.get("state_evaluation", {})
        full = crisis.get("full_period", {})
        for metric_id, key, unit in (
            ("defense_episode_count", "defense_episode_count", "count"),
            ("false_defense_episode_count", "false_defense_episode_count", "count"),
            ("avoided_drawdown", "mdd_delta", "return"),
            ("missed_rebound_proxy_cagr_delta", "cagr_delta", "return"),
        ):
            container = state if key in state else full
            add("risk_defense", metric_id, container.get(key), source_id,
                evidence_class="historical", portfolio=portfolio, unit=unit,
                note="Rejected shadow policy; not operating champion.")
        add("risk_defense", "detection_lead_lag_days", None, source_id,
            evidence_class="historical", portfolio=portfolio, unit="days")
        add("risk_defense", "reserve_target_reach_days", None, source_id,
            evidence_class="historical", portfolio=portfolio, unit="days")
        add("reentry", "cash_trap_days", state.get("cash_trap_snapshot_count"), source_id,
            evidence_class="historical", portfolio=portfolio, unit="snapshots")
        add("reentry", "false_reentry_redefense_count", state.get("false_reentry_redefense_count"), source_id,
            evidence_class="historical", portfolio=portfolio, unit="count")
        for level in ("25", "50", "75", "95"):
            values = state.get("reentry_recovery_business_days", {}).get(level, {})
            add("reentry", f"median_days_to_{level}pct_gross", values.get("median"), source_id,
                evidence_class="historical", portfolio=portfolio, unit="business_days")
        add("reentry", "recovery_leader_participation", None, source_id,
            evidence_class="historical", portfolio=portfolio, unit="ratio")

    p4 = loaded.get("p4_reserve_summary")
    if isinstance(p4, dict):
        if not bool(p4.get("double_count_check_passed")):
            record_integrity_error("historical", "reserve_double_count_check_failed")
        if not bool(p4.get("reason_reconciliation_passed")):
            record_integrity_error("historical", "reserve_reason_reconciliation_failed")
    reserve_metrics = loaded.get("p4_reserve_metrics")
    if isinstance(reserve_metrics, pd.DataFrame):
        rows = reserve_metrics[reserve_metrics["mode"].astype(str).eq("DGS3MO_CARRY")]
        for row in rows.to_dict("records"):
            portfolio = str(row["portfolio"])
            for metric_id, key, unit in (
                ("average_reserve_weight", "average_reserve_weight", "weight"),
                ("latest_reserve_weight", "latest_reserve_weight", "weight"),
                ("reserve_return_contribution_usd", "reserve_return_contribution_usd_vs_broker_cash", "usd"),
                ("cash_interest_accrued_usd", "cash_interest_accrued_usd", "usd"),
                ("reserve_turnover_usd", "reserve_turnover_usd", "usd"),
                ("reserve_fees_usd", "reserve_fees_usd", "usd"),
            ):
                add("reserve", metric_id, row.get(key), "p4_reserve_metrics",
                    evidence_class="historical", portfolio=portfolio, unit=unit)
    for portfolio, source_id in (("main", "p4_main_reserve_reasons"),
                                 ("concentrated", "p4_concentrated_reserve_reasons")):
        reason_rows = loaded.get(source_id)
        if isinstance(reason_rows, list) and reason_rows:
            for reason in RESERVE_REASONS:
                values = [row.get("reason_weights", {}).get(reason) for row in reason_rows]
                values = [float(value) for value in values if finite(value)]
                add("reserve", f"mean_{reason}", sum(values) / len(values) if values else None,
                    source_id, evidence_class="historical", portfolio=portfolio, unit="weight")

    paper = loaded.get("current_paper_summary")
    paper_runtime_manifest: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "manifest_path": records_by_id.get("current_paper_integrity", {}).get("path"),
        "manifest_sha256": records_by_id.get("current_paper_integrity", {}).get("sha256"),
        "snapshot_hash": None,
        "file_count": 0,
        "trusted_boolean_fields_ignored": True,
    }
    verified_paper_payload: dict[str, Any] | None = None
    verified_paper_file_hashes: dict[str, str] = {}
    paper_ledger_root: Path | None = None
    manifest_path = repo_path(records_by_id["current_paper_integrity"]["path"])
    summary_path = repo_path(records_by_id["current_paper_summary"]["path"])
    if manifest_path.is_file():
        paper_summary_binding_error = ""
        try:
            try:
                from tools.run287_paper_ledger_integrity import verify_integrity_manifest
            except ModuleNotFoundError:
                from run287_paper_ledger_integrity import verify_integrity_manifest
            ledger_root = manifest_path.parent.resolve()
            paper_ledger_root = ledger_root
            if manifest_path.resolve() != (
                ledger_root / "snapshot_integrity.json"
            ).resolve():
                paper_summary_binding_error = (
                    "paper integrity source is not the canonical snapshot manifest"
                )
                raise ValueError(paper_summary_binding_error)
            if summary_path.parent.resolve() != ledger_root:
                paper_summary_binding_error = (
                    "paper summary and integrity manifest directories differ"
                )
                raise ValueError(paper_summary_binding_error)
            verified_manifest = verify_integrity_manifest(ledger_root, require=True)
            summary_relative = summary_path.resolve().relative_to(
                ledger_root
            ).as_posix()
            manifest_bytes = manifest_path.read_bytes()
            rebound_manifest = json.loads(manifest_bytes)
            verified_manifest_payload = {
                key: value
                for key, value in verified_manifest.items()
                if key != "status"
            }
            if rebound_manifest != verified_manifest_payload:
                paper_summary_binding_error = (
                    "paper integrity manifest changed after verification"
                )
                raise ValueError(paper_summary_binding_error)
            bound_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
            verified_files = rebound_manifest.get("files") or {}
            if not isinstance(verified_files, dict):
                paper_summary_binding_error = (
                    "paper integrity manifest files are invalid"
                )
                raise ValueError(paper_summary_binding_error)
            summary_bytes = summary_path.read_bytes()
            bound_summary_sha256 = hashlib.sha256(summary_bytes).hexdigest()
            if (
                summary_relative not in verified_files
                or verified_files.get(summary_relative) != bound_summary_sha256
            ):
                paper_summary_binding_error = (
                    "paper summary is not hash-bound by the verified snapshot manifest"
                )
                raise ValueError(paper_summary_binding_error)
            rebound_paper = json.loads(summary_bytes)
            if not isinstance(rebound_paper, dict):
                paper_summary_binding_error = "paper summary is not a JSON object"
                raise ValueError(paper_summary_binding_error)
            for portfolio in ("main", "concentrated"):
                curve_relative = f"{portfolio}/equity_curve.csv"
                expected_curve_sha256 = str(
                    verified_files.get(curve_relative) or ""
                ).lower()
                curve_path = ledger_root / curve_relative
                if (
                    len(expected_curve_sha256) != 64
                    or not curve_path.is_file()
                    or sha256_file(curve_path)
                    != expected_curve_sha256
                ):
                    paper_summary_binding_error = (
                        "paper equity curve is not hash-bound by the "
                        f"verified snapshot manifest:{portfolio}"
                    )
                    raise ValueError(paper_summary_binding_error)
                verified_paper_file_hashes[curve_relative] = (
                    expected_curve_sha256
                )
            verified_paper_payload = rebound_paper
            records_by_id["current_paper_summary"]["sha256"] = (
                bound_summary_sha256
            )
            records_by_id["current_paper_summary"]["status"] = "VERIFIED"
            records_by_id["current_paper_integrity"]["sha256"] = (
                bound_manifest_sha256
            )
            records_by_id["current_paper_integrity"]["status"] = "VERIFIED"
            paper_runtime_manifest.update(
                {
                    "status": "VERIFIED",
                    "manifest_sha256": bound_manifest_sha256,
                    "snapshot_hash": rebound_manifest.get("snapshot_hash"),
                    "file_count": int(rebound_manifest.get("file_count") or 0),
                    "summary_path": str(summary_path),
                    "summary_relative_path": summary_relative,
                    "summary_sha256": bound_summary_sha256,
                }
            )
        except Exception as exc:
            paper_runtime_manifest["status"] = "INTEGRITY_ERROR"
            paper_runtime_manifest["error"] = f"{type(exc).__name__}:{exc}"
            record_integrity_error(
                "current_paper_execution", "paper_snapshot_hash_chain_unverified"
            )
            if paper_summary_binding_error:
                record_integrity_error(
                    "current_paper_execution",
                    "paper_summary_not_bound_to_snapshot_manifest",
                )
    elif isinstance(paper, dict) or summary_path.is_file():
        record_integrity_error(
            "current_paper_execution", "paper_snapshot_integrity_missing"
        )

    verified_paper = (
        verified_paper_payload
        if isinstance(verified_paper_payload, dict)
        and paper_runtime_manifest.get("status") == "VERIFIED"
        else None
    )
    latest_close_performance, latest_close_errors = (
        build_latest_close_performance(
            verified_paper=verified_paper,
            paper_root=paper_ledger_root,
            paper_snapshot_hash=paper_runtime_manifest.get("snapshot_hash"),
            p5=p5 if isinstance(p5, dict) else None,
            p5_source_sha256=records_by_id.get(
                "p5_hold_exit", {}
            ).get("sha256"),
            expected_session_date=expected_session_date,
        )
    )
    if isinstance(verified_paper, dict):
        for error in latest_close_errors:
            record_integrity_error(
                "current_paper_execution",
                f"latest_close_performance:{error}",
            )
    for portfolio in ("main", "concentrated"):
        current_payload = latest_close_performance.get(
            "portfolios", {}
        ).get(portfolio, {})
        operating = (
            current_payload.get("operating_since_seed", {})
            if isinstance(current_payload, dict)
            else {}
        )
        chain_linked = (
            current_payload.get("latest_close_chain_linked", {})
            if isinstance(current_payload, dict)
            else {}
        )
        metric_status = (
            "AVAILABLE"
            if latest_close_performance.get("status")
            == "READY_LATEST_CLOSE_REVIEW_ONLY"
            else "INTEGRITY_ERROR"
            if latest_close_performance.get("status") == "INTEGRITY_ERROR"
            else "UNAVAILABLE"
        )
        curve_path = (
            paper_ledger_root / portfolio / "equity_curve.csv"
            if paper_ledger_root is not None
            else None
        )
        curve_provenance = {
            "source_id": f"current_paper_{portfolio}_equity_curve",
            "source_path": str(curve_path) if curve_path else None,
            "source_sha256": verified_paper_file_hashes.get(
                f"{portfolio}/equity_curve.csv"
            ),
            "as_of_date": latest_close_performance.get("as_of_date"),
            "metric_mode": operating.get("metric_mode"),
            "snapshot_manifest_path": str(manifest_path),
            "snapshot_manifest_sha256": records_by_id.get(
                "current_paper_integrity", {}
            ).get("sha256"),
            "snapshot_tree_sha256": paper_runtime_manifest.get(
                "snapshot_hash"
            ),
        }
        for metric_id, value, unit in (
            (
                "latest_close_operating_return",
                operating.get("total_return"),
                "return",
            ),
            (
                "latest_close_operating_max_drawdown",
                operating.get("max_drawdown"),
                "return",
            ),
            (
                "latest_close_chain_linked_cagr",
                chain_linked.get("cagr"),
                "return",
            ),
            (
                "latest_close_chain_linked_max_drawdown",
                chain_linked.get("max_drawdown"),
                "return",
            ),
            (
                "latest_close_accepted_mark_count",
                operating.get("observations"),
                "count",
            ),
        ):
            add(
                "forward_evidence",
                metric_id,
                value,
                "current_paper_summary",
                evidence_class="current_paper_execution",
                portfolio=portfolio,
                status=metric_status,
                unit=unit,
                note=(
                    "Latest accepted exact-close operating evidence; durable "
                    "catch-up marks are included. This cannot replace the "
                    "locked historical acceptance result."
                ),
                provenance_override={
                    **curve_provenance,
                    **(
                        {
                            "historical_source_sha256": (
                                latest_close_performance.get(
                                    "historical_source_sha256"
                                )
                            )
                        }
                        if metric_id.startswith(
                            "latest_close_chain_linked_"
                        )
                        else {}
                    ),
                },
            )
    if isinstance(verified_paper, dict):
        for field in PAPER_INTEGRITY_FIELDS:
            value = verified_paper.get("integrity", {}).get(
                field, verified_paper.get(field)
            )
            status = "AVAILABLE" if value is not None else "UNAVAILABLE"
            add("integrity", field, value, "current_paper_summary",
                evidence_class="current_paper_execution", status=status, unit="count")
            if finite(value) and float(value) > 0 and field != "degraded_data_day_count":
                record_integrity_error(
                    "current_paper_execution",
                    f"current_paper_integrity:{field}:{int(float(value))}",
                )
        for metric_id, key, unit in (
            ("turnover", "turnover", "weight"), ("fill_count", "fill_count", "count"),
            ("fees_usd", "fees_usd", "usd"), ("slippage", "slippage", "return"),
            ("target_tracking_error", "target_tracking_error", "weight"),
            ("pending_fill_lag", "pending_fill_lag", "days"),
            ("rejected_order_count", "rejected_order_count", "count"),
            ("unfilled_order_count", "unfilled_order_count", "count"),
        ):
            add("execution", metric_id, verified_paper.get(key), "current_paper_summary",
                evidence_class="current_paper_execution", unit=unit)
    else:
        for field in PAPER_INTEGRITY_FIELDS:
            add("integrity", field, None, "current_paper_summary",
                evidence_class="current_paper_execution", status="UNAVAILABLE", unit="count")
        add("execution", "current_paper_execution", None, "current_paper_summary",
            evidence_class="current_paper_execution", status="UNAVAILABLE")

    forward = loaded.get("true_forward_summary")
    if isinstance(forward, dict):
        readiness = forward.get("review_readiness", {})
        forward_status = str(readiness.get("status") or "UNDERPOWERED")
        for metric_id, value, unit in (
            ("elapsed_market_sessions", forward.get("coverage", {}).get("decision_date_count"), "sessions"),
            ("decision_weeks_21d", readiness.get("sample_checks", {}).get("decision_week_blocks_21d", {}).get("actual"), "count"),
            ("decision_weeks_63d", readiness.get("sample_checks", {}).get("decision_week_blocks_63d", {}).get("actual"), "count"),
            ("distinct_securities", readiness.get("distinct_true_forward_ticker_count"), "count"),
            ("resolved_21d_outcomes", readiness.get("cohort_metrics", {}).get("true_forward_arm", {}).get("21d", {}).get("completed_count"), "count"),
            ("resolved_63d_outcomes", readiness.get("cohort_metrics", {}).get("true_forward_arm", {}).get("63d", {}).get("completed_count"), "count"),
            ("resolved_126d_outcomes", readiness.get("cohort_metrics", {}).get("true_forward_arm", {}).get("126d", {}).get("completed_count"), "count"),
        ):
            add("forward_evidence", metric_id, value, "true_forward_summary",
                evidence_class="true_forward", status=forward_status, unit=unit)
        add("forward_evidence", "resolved_252d_outcomes", None, "true_forward_summary",
            evidence_class="true_forward", status="UNAVAILABLE", unit="count",
            note="The current true-forward ledger contract resolves 21/63/126D only.")
        add("forward_evidence", "review_ready", bool(readiness.get("review_ready")),
            "true_forward_summary", evidence_class="true_forward", status=forward_status, unit="boolean")
    else:
        for metric_id in ("elapsed_market_sessions", "decision_weeks_21d", "decision_weeks_63d",
                          "distinct_securities", "resolved_21d_outcomes", "resolved_63d_outcomes",
                          "resolved_126d_outcomes", "resolved_252d_outcomes", "review_ready"):
            add("forward_evidence", metric_id, None, "true_forward_summary",
                evidence_class="true_forward", status="UNAVAILABLE")

    # Known historical integrity checks are real zeroes only when their source ran.
    if isinstance(p5, dict):
        add("integrity", "historical_control_parity_error_count",
            0 if bool(p5.get("control_parity_passed")) else 1, "p5_hold_exit",
            evidence_class="historical", unit="count")
    if isinstance(p4, dict):
        add("integrity", "reserve_reconciliation_error_count",
            0 if bool(p4.get("reason_reconciliation_passed")) else 1,
            "p4_reserve_summary", evidence_class="historical", unit="count")

    lane_integrity_errors = {
        lane: sorted(set(values)) for lane, values in lane_integrity_errors.items()
    }
    integrity_errors = sorted(
        {value for values in lane_integrity_errors.values() for value in values}
    )
    historical_integrity_errors = lane_integrity_errors["historical"]
    headline_trust = "NOT_TRUSTED" if historical_integrity_errors else "TRUSTED"
    for payload in headlines.values():
        payload["trust"] = headline_trust
        source = records_by_id.get(str(payload.get("source_id")), {})
        payload["provenance"] = {
            "source_path": source.get("path"), "source_sha256": source.get("sha256"),
            "as_of_date": source.get("as_of_date"), "metric_mode": source.get("metric_mode"),
        }

    evidence_status = {
        "historical": "NOT_TRUSTED" if historical_integrity_errors else "AVAILABLE_PARTIAL",
        "current_paper_execution": (
            "NOT_TRUSTED" if lane_integrity_errors["current_paper_execution"] else
            "AVAILABLE" if isinstance(verified_paper, dict) and paper_runtime_manifest["status"] == "VERIFIED"
            else "UNAVAILABLE"
        ),
        "true_forward": (
            "NOT_TRUSTED" if lane_integrity_errors["true_forward"] else
            str(forward.get("review_readiness", {}).get("status") or "UNDERPOWERED")
            if isinstance(forward, dict) else "UNAVAILABLE"
        ),
    }
    trust_lanes = {
        lane: {
            "status": evidence_status[lane],
            "trusted": (
                False if lane_integrity_errors[lane]
                else None if evidence_status[lane] == "UNAVAILABLE"
                else True
            ),
            "integrity_errors": lane_integrity_errors[lane],
        }
        for lane in EVIDENCE_LANES
    }
    scorecard_trust_blockers = list(integrity_errors)
    if not isinstance(verified_paper, dict):
        scorecard_trust_blockers.append("current_paper_summary_unavailable")
    if paper_runtime_manifest["status"] != "VERIFIED":
        scorecard_trust_blockers.append("current_paper_runtime_manifest_unverified")
    scorecard_trust_blockers = sorted(set(scorecard_trust_blockers))
    scorecard_trusted = not scorecard_trust_blockers
    section_status: dict[str, str] = {}
    for section in SECTIONS:
        section_rows = [row for row in metrics if row["section"] == section]
        statuses = {row["status"] for row in section_rows}
        if "INTEGRITY_ERROR" in statuses:
            section_status[section] = "INTEGRITY_ERROR"
        elif any(value == "AVAILABLE" for value in statuses):
            section_status[section] = "AVAILABLE_PARTIAL" if any(
                value in {"UNAVAILABLE", "UNDERPOWERED"} or value.startswith("BLOCKED_")
                for value in statuses
            ) else "AVAILABLE"
        elif "UNDERPOWERED" in statuses:
            section_status[section] = "UNDERPOWERED"
        else:
            section_status[section] = "UNAVAILABLE"

    selection_deltas = [row for row in p6.get("selection_quality_delta", [])] if isinstance(p6, dict) else []
    all_selection_positive = bool(selection_deltas) and all(
        finite(row.get("selected_minus_control")) and float(row["selected_minus_control"]) > 0
        for row in selection_deltas
    )
    attribution = {}
    for portfolio in ("main", "concentrated"):
        crisis = loaded.get(f"p3_{portfolio}_crisis", {})
        hold = p5.get("portfolios", {}).get(portfolio, {}) if isinstance(p5, dict) else {}
        reserve_row = None
        if isinstance(reserve_metrics, pd.DataFrame):
            matched = reserve_metrics[
                reserve_metrics["portfolio"].astype(str).eq(portfolio)
                & reserve_metrics["mode"].astype(str).eq("DGS3MO_CARRY")
            ]
            if not matched.empty:
                reserve_row = matched.iloc[0].to_dict()
        attribution[portfolio] = {
            "selection": "POSITIVE_MATCHED_CONTROL_EVIDENCE" if all_selection_positive else "UNAVAILABLE_OR_MIXED",
            "holding": "BOTTLENECK_SHORT_HOLDS" if finite(hold.get("holding_statistics", {}).get("median_holding_days"))
            and float(hold["holding_statistics"]["median_holding_days"]) < 63 else "UNAVAILABLE_OR_NOT_FLAGGED",
            "exit": "UNDERPOWERED_NO_COUNTERFACTUAL_EVENTS" if hold.get("counterfactual_summary", {}).get("status") == "NO_EVENTS" else "AVAILABLE",
            "risk_defense": "REJECTED_CAGR_SACRIFICE" if crisis.get("status") == "REJECTED_POLICY_PROMOTION" else "UNAVAILABLE",
            "reserve": "POSITIVE_CARRY_NOT_SELECTION_ALPHA" if reserve_row and float(reserve_row.get("delta_cagr_pp_vs_broker_cash", 0)) > 0 else "UNAVAILABLE_OR_NONPOSITIVE",
            "cost": "MATERIAL_CAGR_DRAG" if len(hold.get("cost_sensitivity", {})) >= 3 else "UNAVAILABLE",
            "forward": evidence_status["true_forward"],
        }

    promotion = gate_for_consumer(explicit=promotion_state_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "metric_definition_version": registry["metric_definition_version"],
        "migration_note": registry.get("migration_note"),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scorecard_as_of_date": registry.get("scorecard_as_of_date"),
        "latest_close_as_of_date": latest_close_performance.get("as_of_date"),
        "latest_close_performance": latest_close_performance,
        "source_registry": str(source_registry_path),
        "source_registry_sha256": sha256_file(source_registry_path),
        "private_review_only": True,
        "public_deployment_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "promotion_governance": promotion,
        "historical_acceptance_overwritten_by_forward": False,
        "scorecard_trusted": scorecard_trusted,
        "scorecard_trust_basis": "runtime-source-sha256-and-paper-directory-manifest-v1",
        "scorecard_trust_blockers": scorecard_trust_blockers,
        "runtime_trust_manifest": {
            "source_bundle": source_bundle,
            "paper_snapshot": paper_runtime_manifest,
            "trusted_boolean_fields_ignored": True,
        },
        "headline_performance_trust": headline_trust,
        "headline_performance": headlines,
        "integrity_errors": integrity_errors,
        "integrity_errors_by_lane": lane_integrity_errors,
        "trust_lanes": trust_lanes,
        "evidence_status": evidence_status,
        "section_status": section_status,
        "performance_attribution": attribution,
        "sources": source_records,
        "metrics": metrics,
        "absorbed_source_count": sum(row.get("disposition") == "ABSORBED_SOURCE" for row in source_records),
        "source_artifacts_copied": False,
        "fullrun_executed": False,
    }


def render_report(scorecard: dict[str, Any]) -> str:
    def pct(value: Any) -> str:
        return (
            "UNAVAILABLE"
            if value is None
            else f"{100 * float(value):.4f}%"
        )

    lines = [
        "# Run287 canonical operating scorecard",
        "",
        f"As of: {scorecard.get('scorecard_as_of_date')}",
        f"Headline trust: **{scorecard['headline_performance_trust']}**",
        f"Runtime scorecard trusted: **{str(scorecard['scorecard_trusted']).lower()}**",
        "",
        "Historical, current-paper, and true-forward evidence are deliberately separate. "
        "Forward evidence never changes the historical acceptance label.",
        "",
        "## Headline historical performance",
        "",
        "| Portfolio | CAGR | MDD | Sharpe | Trust |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for portfolio, payload in scorecard["headline_performance"].items():
        sharpe = "UNAVAILABLE" if payload.get("sharpe") is None else f"{float(payload['sharpe']):.4f}"
        lines.append(f"| {portfolio.title()} | {pct(payload.get('cagr'))} | {pct(payload.get('max_drawdown'))} | {sharpe} | {payload['trust']} |")
    latest = scorecard.get("latest_close_performance") or {}
    lines.extend(
        [
            "",
            "## Latest accepted close performance",
            "",
            f"- status: `{latest.get('status') or 'UNAVAILABLE'}`",
            f"- as_of_date: `{latest.get('as_of_date') or 'UNAVAILABLE'}`",
            "- Durable chronological catch-up marks are included in the operating path.",
            "- Chain-linked CAGR is exact at the endpoints; its MDD value is an optimistic lower bound on loss magnitude and the exact MDD can be more negative.",
            "- Neither latest-close diagnostic replaces the locked historical acceptance result.",
            "",
            "| Portfolio | Historical CAGR/MDD | Operating return/MDD since seed | Latest-close chain CAGR/optimistic MDD bound |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for portfolio in ("main", "concentrated"):
        payload = latest.get("portfolios", {}).get(portfolio, {})
        historical = payload.get("historical_locked", {})
        operating = payload.get("operating_since_seed", {})
        chain = payload.get("latest_close_chain_linked", {})
        lines.append(
            f"| {portfolio.title()} | "
            f"{pct(historical.get('cagr'))} / "
            f"{pct(historical.get('max_drawdown'))} | "
            f"{pct(operating.get('total_return'))} / "
            f"{pct(operating.get('max_drawdown'))} | "
            f"{pct(chain.get('cagr'))} / "
            f"{pct(chain.get('max_drawdown'))} |"
        )
    lines.extend(["", "## Evidence lanes", "", "| Lane | Status |", "| --- | --- |"])
    for lane, status in scorecard["evidence_status"].items():
        lines.append(f"| {lane} | `{status}` |")
    promotion = scorecard["promotion_governance"]
    lines.extend([
        "",
        "## Promotion governance",
        "",
        f"- promotion_state: `{promotion['promotion_state']}`",
        f"- rollback_triggered: `{str(promotion['rollback_triggered']).lower()}`",
        "- production_activation_allowed: `false`",
        "- live_trading_enabled: `false`",
    ])
    lines.extend(["", "## Operating sections", "", "| Section | Status | Available / total |", "| --- | --- | ---: |"])
    for section in SECTIONS:
        rows = [row for row in scorecard["metrics"] if row["section"] == section]
        available = sum(row["status"] == "AVAILABLE" for row in rows)
        lines.append(f"| {section} | `{scorecard['section_status'][section]}` | {available}/{len(rows)} |")
    lines.extend(["", "## Performance attribution", ""])
    for portfolio, values in scorecard["performance_attribution"].items():
        lines.append(f"### {portfolio.title()}")
        lines.append("")
        for key, value in values.items():
            lines.append(f"- {key}: `{value}`")
        lines.append("")
    if scorecard["integrity_errors"]:
        lines.extend(["## Integrity errors", ""])
        lines.extend(f"- `{value}`" for value in scorecard["integrity_errors"])
        lines.append("")
    lines.extend([
        "## Provenance contract",
        "",
        "Every metric in `operating_scorecard.json` carries source path, SHA-256, as-of date, "
        "and metric mode. Missing evidence is `UNAVAILABLE` or `UNDERPOWERED`, never synthetic zero.",
        "Source artifacts are referenced, not copied. This report is private/review-only and cannot activate production or live trading.",
        "",
    ])
    return "\n".join(lines)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-registry", default="docs/run287_operating_scorecard_sources.json")
    parser.add_argument("--output-dir", default="outputs/run287_operating_scorecard")
    parser.add_argument("--previous-scorecard")
    parser.add_argument("--promotion-state")
    parser.add_argument("--expected-session-date")
    args = parser.parse_args()
    registry_path = repo_path(args.source_registry)
    registry = load_registry(registry_path)
    if args.previous_scorecard:
        previous = json.loads(repo_path(args.previous_scorecard).read_text(encoding="utf-8"))
        validate_metric_migration(previous, registry)
    promotion_path = repo_path(args.promotion_state) if args.promotion_state else None
    scorecard = build_scorecard(
        registry,
        source_registry_path=registry_path,
        promotion_state_path=promotion_path,
        expected_session_date=args.expected_session_date,
    )
    output_dir = repo_path(args.output_dir)
    write_json(output_dir / "operating_scorecard.json", scorecard)
    (output_dir / "operating_scorecard.md").write_text(render_report(scorecard), encoding="utf-8")
    print(json.dumps({
        "status": "READY_PRIVATE_REVIEW_SCORECARD",
        "headline_trust": scorecard["headline_performance_trust"],
        "evidence_status": scorecard["evidence_status"],
        "metric_count": len(scorecard["metrics"]),
        "output_dir": str(output_dir),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

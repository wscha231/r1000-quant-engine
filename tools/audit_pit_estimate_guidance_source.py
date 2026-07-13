#!/usr/bin/env python3
"""Fail-closed audit for a provider-neutral PIT estimate/guidance sample.

This tool decides only whether an export is fit to enter the Run287
single-source screen.  It never computes alpha, changes a target book, starts a
fullrun, or authorizes a purchase.  Missing securities remain missing/neutral.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "run287-pit-estimate-guidance-source-gate-v1"
DEFAULT_REQUIREMENTS = "docs/run287_pit_estimate_guidance_source_requirements.json"

EVENT_REQUIRED_COLUMNS = {
    "provider",
    "observation_id",
    "security_id",
    "ticker",
    "record_type",
    "metric",
    "fiscal_period_end",
    "fiscal_period_type",
    "value_role",
    "value",
    "currency",
    "unit",
    "analyst_count",
    "observed_at",
    "available_from",
    "source_hash",
}
UNIVERSE_REQUIRED_COLUMNS = {"security_id", "ticker", "is_delisted"}
METADATA_REQUIRED_FIELDS = {
    "provider",
    "export_id",
    "point_in_time_history_claimed",
    "symbol_history_included",
    "delisted_history_included",
    "research_reproduction_allowed",
    "lock_in_required",
    "sample_quote_amount",
    "approved_cost_ceiling_amount",
    "quote_currency",
    "ceiling_currency",
}

ALLOWED_RECORD_TYPES = {"consensus_estimate", "company_guidance"}
ALLOWED_METRICS = {"eps", "revenue"}
ALLOWED_PERIOD_TYPES = {"FY", "FQ"}
ALLOWED_VALUE_ROLES = {"consensus_mean", "guidance_midpoint"}
EXACT_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$"
)
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix in {".csv", ".txt"}:
        return pd.read_csv(path)
    raise ValueError(f"unsupported input format: {path.suffix}; use CSV or Parquet")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ratio(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


def clean_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def finite_float(value: Any) -> float | None:
    try:
        output = float(value)
    except (TypeError, ValueError):
        return None
    return output if math.isfinite(output) else None


def exact_timestamp_mask(series: pd.Series) -> pd.Series:
    return series.astype(str).str.match(EXACT_TIMESTAMP_RE, na=False)


def add_check(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    observed: Any,
    required: Any,
    category: str,
    detail: str,
) -> None:
    checks.append(
        {
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "category": category,
            "observed": observed,
            "required": required,
            "detail": detail,
        }
    )


def empty_coverage() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "security_id",
            "ticker",
            "is_delisted",
            "has_any_event",
            "history_start",
            "history_end",
            "full_window_covered",
            "oos2_covered",
            "oos_covered",
            "eps_revision_ready",
            "revenue_revision_ready",
            "revision_ready",
            "guidance_pair_ready",
        ]
    )


def _revision_ready(group: pd.DataFrame, metric: str) -> bool:
    subset = group[
        group["record_type"].eq("consensus_estimate")
        & group["value_role"].eq("consensus_mean")
        & group["metric"].eq(metric)
    ]
    if subset.empty:
        return False
    counts = subset.groupby(["fiscal_period_end", "fiscal_period_type"])["observation_id"].nunique()
    return bool((counts >= 2).any())


def _guidance_pair_ready(group: pd.DataFrame) -> bool:
    estimates = group[
        group["record_type"].eq("consensus_estimate") & group["value_role"].eq("consensus_mean")
    ]
    guidance = group[
        group["record_type"].eq("company_guidance") & group["value_role"].eq("guidance_midpoint")
    ]
    if estimates.empty or guidance.empty:
        return False
    keys = ["metric", "fiscal_period_end", "fiscal_period_type"]
    for key, g_rows in guidance.groupby(keys, dropna=False):
        e_rows = estimates
        for column, value in zip(keys, key):
            e_rows = e_rows[e_rows[column].eq(value)]
        if not e_rows.empty and bool(
            (e_rows["available_from_ts"].min() < g_rows["available_from_ts"].max())
        ):
            return True
    return False


def build_coverage(
    events: pd.DataFrame,
    universe: pd.DataFrame,
    requirements: dict[str, Any],
) -> pd.DataFrame:
    start = pd.Timestamp(requirements["window_start"], tz="UTC")
    end = pd.Timestamp(requirements["window_end"], tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    oos2 = pd.Timestamp(requirements["oos2_start"], tz="UTC")
    oos = pd.Timestamp(requirements["oos_start"], tz="UTC")
    start_limit = start + pd.Timedelta(days=int(requirements["history_start_grace_days"]))
    end_limit = end - pd.Timedelta(days=int(requirements["history_end_grace_days"]))

    groups = {key: group for key, group in events.groupby("security_id", sort=False)}
    rows: list[dict[str, Any]] = []
    for record in universe.to_dict("records"):
        security_id = str(record["security_id"])
        group = groups.get(security_id, events.iloc[0:0])
        has_any = not group.empty
        history_start = group["available_from_ts"].min() if has_any else pd.NaT
        history_end = group["available_from_ts"].max() if has_any else pd.NaT
        eps_ready = _revision_ready(group, "eps") if has_any else False
        revenue_ready = _revision_ready(group, "revenue") if has_any else False
        rows.append(
            {
                "security_id": security_id,
                "ticker": str(record["ticker"]),
                "is_delisted": bool(record["is_delisted_bool"]),
                "has_any_event": has_any,
                "history_start": history_start.isoformat() if pd.notna(history_start) else "",
                "history_end": history_end.isoformat() if pd.notna(history_end) else "",
                "full_window_covered": bool(
                    has_any and history_start <= start_limit and history_end >= end_limit
                ),
                "oos2_covered": bool(has_any and (group["available_from_ts"] >= oos2).any()),
                "oos_covered": bool(has_any and (group["available_from_ts"] >= oos).any()),
                "eps_revision_ready": eps_ready,
                "revenue_revision_ready": revenue_ready,
                "revision_ready": eps_ready and revenue_ready,
                "guidance_pair_ready": _guidance_pair_ready(group) if has_any else False,
            }
        )
    return pd.DataFrame(rows) if rows else empty_coverage()


def audit_source(
    *,
    events: pd.DataFrame,
    universe: pd.DataFrame,
    metadata: dict[str, Any],
    requirements: dict[str, Any],
    input_hash: str = "",
    universe_hash: str = "",
    metadata_hash: str = "",
    requirements_hash: str = "",
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    checks: list[dict[str, Any]] = []
    missing_event = sorted(EVENT_REQUIRED_COLUMNS - set(events.columns))
    missing_universe = sorted(UNIVERSE_REQUIRED_COLUMNS - set(universe.columns))
    missing_metadata = sorted(METADATA_REQUIRED_FIELDS - set(metadata))
    add_check(checks, "event_schema", not missing_event, missing_event, [], "schema", "required long-event columns")
    add_check(checks, "universe_schema", not missing_universe, missing_universe, [], "schema", "stable ID and delisted flag")
    add_check(checks, "metadata_schema", not missing_metadata, missing_metadata, [], "schema", "provider and procurement fields")

    coverage = empty_coverage()
    if missing_event or missing_universe or missing_metadata:
        status = "BLOCKED_SCHEMA"
        summary = _summary(status, events, universe, metadata, requirements, checks, coverage, input_hash, universe_hash, metadata_hash, requirements_hash)
        return summary, pd.DataFrame(checks), coverage

    events = events.copy()
    universe = universe.copy()
    for column in ["provider", "observation_id", "security_id", "ticker", "record_type", "metric", "fiscal_period_type", "value_role", "currency", "unit", "observed_at", "available_from", "source_hash"]:
        events[column] = events[column].astype(str).str.strip()
    universe["security_id"] = universe["security_id"].astype(str).str.strip()
    universe["ticker"] = universe["ticker"].astype(str).str.strip().str.upper()
    universe["is_delisted_bool"] = universe["is_delisted"].map(clean_bool)

    exact_observed = exact_timestamp_mask(events["observed_at"])
    exact_available = exact_timestamp_mask(events["available_from"])
    exact_ratio = ratio(int((exact_observed & exact_available).sum()), len(events))
    observed_ts = pd.to_datetime(events["observed_at"], errors="coerce", utc=True)
    available_ts = pd.to_datetime(events["available_from"], errors="coerce", utc=True)
    events["available_from_ts"] = available_ts
    fiscal_period_end = pd.to_datetime(events["fiscal_period_end"], errors="coerce")
    events["fiscal_period_end"] = fiscal_period_end.dt.date.astype(str)
    numeric_value = pd.to_numeric(events["value"], errors="coerce")
    analyst_count = pd.to_numeric(events["analyst_count"], errors="coerce")

    enum_ok = bool(
        events["record_type"].isin(ALLOWED_RECORD_TYPES).all()
        and events["metric"].isin(ALLOWED_METRICS).all()
        and events["fiscal_period_type"].isin(ALLOWED_PERIOD_TYPES).all()
        and events["value_role"].isin(ALLOWED_VALUE_ROLES).all()
    )
    role_ok = bool(
        (
            events["record_type"].eq("consensus_estimate")
            & events["value_role"].eq("consensus_mean")
            | events["record_type"].eq("company_guidance")
            & events["value_role"].eq("guidance_midpoint")
        ).all()
    )
    timestamps_parse = bool(observed_ts.notna().all() and available_ts.notna().all())
    chronology_ok = bool(timestamps_parse and (available_ts >= observed_ts).all())
    window_end = pd.Timestamp(requirements["window_end"], tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    no_future_rows = bool(timestamps_parse and (available_ts <= window_end).all())
    source_hash_ratio = ratio(int(events["source_hash"].str.match(SHA256_RE, na=False).sum()), len(events))
    observation_unique = bool(events["observation_id"].ne("").all() and not events["observation_id"].duplicated().any())
    event_key_unique = not events.duplicated(
        ["security_id", "record_type", "metric", "fiscal_period_end", "fiscal_period_type", "value_role", "available_from"]
    ).any()
    requested_ids = set(universe["security_id"])
    foreign_ids = sorted(set(events["security_id"]) - requested_ids)
    universe_id_unique = bool(universe["security_id"].ne("").all() and not universe["security_id"].duplicated().any())
    required_text_columns = ["provider", "observation_id", "security_id", "ticker", "currency", "unit"]
    empty_required_text = int(sum(events[column].eq("").sum() for column in required_text_columns))
    metadata_text_ok = all(str(metadata.get(field, "")).strip() for field in ["provider", "export_id", "quote_currency", "ceiling_currency"])

    exact_required = float(requirements["min_exact_timestamp_ratio"])
    hash_required = float(requirements["min_source_hash_ratio"])
    add_check(checks, "exact_timestamp_ratio", exact_ratio >= exact_required, exact_ratio, exact_required, "pit", "both timestamps require time and timezone")
    add_check(checks, "timestamp_parse", timestamps_parse, int((observed_ts.isna() | available_ts.isna()).sum()), 0, "pit", "timestamps parse as UTC")
    add_check(checks, "availability_chronology", chronology_ok, int((available_ts < observed_ts).sum()) if timestamps_parse else len(events), 0, "pit", "available_from must not precede observed_at")
    add_check(checks, "no_future_rows", no_future_rows, int((available_ts > window_end).sum()) if timestamps_parse else len(events), 0, "pit", "rows after the frozen window end are excluded")
    add_check(checks, "source_hash_ratio", source_hash_ratio >= hash_required, source_hash_ratio, hash_required, "pit", "SHA-256 provenance required")
    add_check(checks, "observation_id_unique", observation_unique, int(events["observation_id"].duplicated().sum()), 0, "pit", "append-only observation IDs")
    add_check(checks, "event_key_unique", event_key_unique, int(events.duplicated(["security_id", "record_type", "metric", "fiscal_period_end", "fiscal_period_type", "value_role", "available_from"]).sum()), 0, "pit", "no duplicate event keys")
    add_check(checks, "universe_id_unique", universe_id_unique, int(universe["security_id"].duplicated().sum()), 0, "schema", "one requested row per stable security ID")
    add_check(checks, "events_within_requested_universe", not foreign_ids, len(foreign_ids), 0, "schema", "no unrequested security IDs")
    add_check(checks, "required_text_nonempty", empty_required_text == 0, empty_required_text, 0, "schema", "identity, currency, and unit values")
    add_check(checks, "metadata_text_nonempty", metadata_text_ok, bool(metadata_text_ok), True, "schema", "provider, export, and currency values")
    add_check(checks, "valid_delisted_flags", universe["is_delisted_bool"].notna().all(), int(universe["is_delisted_bool"].isna().sum()), 0, "schema", "boolean delisted flags")
    add_check(checks, "fiscal_period_end_parse", fiscal_period_end.notna().all(), int(fiscal_period_end.isna().sum()), 0, "schema", "valid fiscal period end dates")
    add_check(checks, "allowed_enums", enum_ok, sorted(set(events["record_type"]) | set(events["metric"]) | set(events["fiscal_period_type"]) | set(events["value_role"])), "registered enums", "schema", "record, metric, period, and value roles")
    add_check(checks, "record_value_role_consistency", role_ok, bool(role_ok), True, "schema", "consensus and guidance roles cannot be mixed")
    finite_values = bool(numeric_value.notna().all() and numeric_value.map(math.isfinite).all())
    valid_analyst = bool(analyst_count.notna().all() and (analyst_count >= 0).all())
    add_check(checks, "finite_values", finite_values, int(numeric_value.isna().sum()), 0, "schema", "finite estimate/guidance values")
    add_check(checks, "valid_analyst_count", valid_analyst, int(analyst_count.isna().sum()), 0, "schema", "nonnegative analyst count; use zero for guidance")

    metadata_provider_match = bool(events["provider"].eq(str(metadata["provider"])).all())
    quote_amount = finite_float(metadata["sample_quote_amount"])
    ceiling_amount = finite_float(metadata["approved_cost_ceiling_amount"])
    valid_cost_values = bool(
        quote_amount is not None
        and ceiling_amount is not None
        and quote_amount >= 0
        and ceiling_amount >= 0
    )
    quote_currency_match = str(metadata["quote_currency"]).upper() == str(metadata["ceiling_currency"]).upper()
    capability_ok = all(
        metadata.get(field) is True
        for field in [
            "point_in_time_history_claimed",
            "symbol_history_included",
            "delisted_history_included",
            "research_reproduction_allowed",
        ]
    )
    add_check(checks, "provider_match", metadata_provider_match, str(metadata["provider"]), "all rows", "procurement", "one provider per single-source screen")
    add_check(checks, "provider_capabilities", capability_ok, capability_ok, True, "procurement", "PIT, symbol, delisted, and reproducibility claims")
    add_check(checks, "no_provider_lock_in", metadata.get("lock_in_required") is False, metadata.get("lock_in_required"), False, "procurement", "sample must not require long-term lock-in")
    add_check(checks, "valid_cost_values", valid_cost_values, f"quote={quote_amount}; ceiling={ceiling_amount}", "finite nonnegative values", "procurement", "invalid cost values cannot authorize procurement")
    add_check(checks, "sample_cost_within_approved_ceiling", bool(valid_cost_values and quote_currency_match and quote_amount <= ceiling_amount), f"{quote_amount} {metadata['quote_currency']}", f"<= {ceiling_amount} {metadata['ceiling_currency']}", "procurement", "this file records approval; the tool never grants it")

    hard_precoverage_failed = any(c["status"] == "FAIL" and c["category"] in {"schema", "pit"} for c in checks)
    if not hard_precoverage_failed:
        coverage = build_coverage(events, universe, requirements)
        requested_count = len(coverage)
        covered = int(coverage["has_any_event"].sum())
        full_covered = int(coverage["full_window_covered"].sum())
        oos2_covered = int(coverage["oos2_covered"].sum())
        oos_covered = int(coverage["oos_covered"].sum())
        revisions = int(coverage["revision_ready"].sum())
        guidance = int(coverage["guidance_pair_ready"].sum())
        delisted = coverage[coverage["is_delisted"]]
        delisted_covered = int(delisted["has_any_event"].sum())
        coverage_checks = [
            ("requested_security_count", requested_count, int(requirements["min_requested_security_count"]), "count"),
            ("security_coverage_ratio", ratio(covered, requested_count), float(requirements["min_security_coverage_ratio"]), "ratio"),
            ("full_window_security_ratio", ratio(full_covered, requested_count), float(requirements["min_full_window_security_ratio"]), "ratio"),
            ("oos2_security_ratio", ratio(oos2_covered, requested_count), float(requirements["min_oos2_security_ratio"]), "ratio"),
            ("oos_security_ratio", ratio(oos_covered, requested_count), float(requirements["min_oos_security_ratio"]), "ratio"),
            ("revision_ready_security_ratio", ratio(revisions, requested_count), float(requirements["min_revision_ready_security_ratio"]), "ratio"),
            ("guidance_pair_security_ratio", ratio(guidance, requested_count), float(requirements["min_guidance_pair_security_ratio"]), "ratio"),
            ("requested_delisted_count", len(delisted), int(requirements["min_requested_delisted_count"]), "count"),
            ("delisted_coverage_ratio", ratio(delisted_covered, len(delisted)), float(requirements["min_delisted_coverage_ratio"]), "ratio"),
        ]
        for check_id, observed, required, unit in coverage_checks:
            add_check(checks, check_id, observed >= required, observed, required, "coverage", f"{unit}; missing remains neutral")

    schema_failed = any(c["status"] == "FAIL" and c["category"] == "schema" for c in checks)
    pit_failed = any(c["status"] == "FAIL" and c["category"] == "pit" for c in checks)
    procurement_failed = any(c["status"] == "FAIL" and c["category"] == "procurement" for c in checks)
    coverage_failed = any(c["status"] == "FAIL" and c["category"] == "coverage" for c in checks)
    if schema_failed:
        status = "BLOCKED_SCHEMA"
    elif pit_failed:
        status = "BLOCKED_PIT"
    elif procurement_failed:
        status = "BLOCKED_PROCUREMENT"
    elif coverage_failed:
        status = "UNDER_COVERED"
    else:
        status = "READY_FOR_SOURCE_SCREEN"

    summary = _summary(status, events, universe, metadata, requirements, checks, coverage, input_hash, universe_hash, metadata_hash, requirements_hash)
    return summary, pd.DataFrame(checks), coverage


def _summary(
    status: str,
    events: pd.DataFrame,
    universe: pd.DataFrame,
    metadata: dict[str, Any],
    requirements: dict[str, Any],
    checks: list[dict[str, Any]],
    coverage: pd.DataFrame,
    input_hash: str,
    universe_hash: str,
    metadata_hash: str,
    requirements_hash: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": status,
        "research_only": True,
        "single_source_only": True,
        "missing_policy": "neutral",
        "backtest_acceptance_allowed": False,
        "portfolio_arm_allowed": False,
        "purchase_authorized": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_dispatched": False,
        "provider": metadata.get("provider", ""),
        "export_id": metadata.get("export_id", ""),
        "event_rows": int(len(events)),
        "requested_security_count": int(len(universe)),
        "covered_security_count": int(coverage["has_any_event"].sum()) if "has_any_event" in coverage else 0,
        "failed_check_count": sum(1 for check in checks if check["status"] == "FAIL"),
        "failed_checks": [check["check_id"] for check in checks if check["status"] == "FAIL"],
        "requirements": requirements,
        "input_hashes": {
            "events_sha256": input_hash,
            "universe_sha256": universe_hash,
            "metadata_sha256": metadata_hash,
            "requirements_sha256": requirements_hash,
        },
        "next_action": (
            "run_preregistered_single_source_screen"
            if status == "READY_FOR_SOURCE_SCREEN"
            else "do_not_purchase_or_backtest; repair_or_replace_sample"
        ),
    }


def write_outputs(output_dir: Path, summary: dict[str, Any], checks: pd.DataFrame, coverage: pd.DataFrame) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checks.to_csv(output_dir / "checks.csv", index=False)
    coverage.to_csv(output_dir / "coverage_by_security.csv", index=False)
    failed = checks[checks["status"].eq("FAIL")] if not checks.empty else checks
    lines = [
        "# Run287 PIT estimate/guidance source gate",
        "",
        f"- Status: `{summary['status']}`",
        f"- Provider: `{summary['provider'] or 'unknown'}`",
        f"- Event rows: `{summary['event_rows']}`",
        f"- Requested / covered securities: `{summary['requested_security_count']}` / `{summary['covered_security_count']}`",
        f"- Failed checks: `{summary['failed_check_count']}`",
        "- Missing policy: `neutral`",
        "- Backtest, portfolio arm, purchase, production, and fullrun: `not authorized`",
        "",
        "## Failed checks",
        "",
    ]
    if failed.empty:
        lines.append("None. The export may enter the preregistered source screen; it has not passed an alpha gate.")
    else:
        for row in failed.to_dict("records"):
            lines.append(f"- `{row['check_id']}`: observed `{row['observed']}`, required `{row['required']}`. {row['detail']}")
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Provider long-event CSV or Parquet")
    parser.add_argument("--universe", required=True, help="Requested sample universe CSV or Parquet")
    parser.add_argument("--metadata", required=True, help="Provider/export/procurement metadata JSON")
    parser.add_argument("--requirements", default=DEFAULT_REQUIREMENTS, help="Frozen gate requirements JSON")
    parser.add_argument("--output-dir", default="outputs/run287_pit_estimate_guidance_source_gate")
    parser.add_argument("--report-only", action="store_true", help="Write a blocked report but exit zero")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = repo_path(args.input)
    universe_path = repo_path(args.universe)
    metadata_path = repo_path(args.metadata)
    requirements_path = repo_path(args.requirements)
    paths = [input_path, universe_path, metadata_path, requirements_path]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        print(json.dumps({"status": "BLOCKED_SCHEMA", "missing_files": missing}, indent=2))
        return 0 if args.report_only else 2
    summary, checks, coverage = audit_source(
        events=read_table(input_path),
        universe=read_table(universe_path),
        metadata=read_json(metadata_path),
        requirements=read_json(requirements_path),
        input_hash=sha256_file(input_path),
        universe_hash=sha256_file(universe_path),
        metadata_hash=sha256_file(metadata_path),
        requirements_hash=sha256_file(requirements_path),
    )
    write_outputs(repo_path(args.output_dir), summary, checks, coverage)
    print(json.dumps({"status": summary["status"], "failed_checks": summary["failed_checks"], "output_dir": str(repo_path(args.output_dir))}, indent=2))
    return 0 if summary["status"] == "READY_FOR_SOURCE_SCREEN" or args.report_only else 2


if __name__ == "__main__":
    sys.exit(main())

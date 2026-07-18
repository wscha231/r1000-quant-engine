#!/usr/bin/env python3
"""Audit the forward estimate archive and paper ledger without promotion.

The free estimate archive is a contemporaneous, forward-only observation lane.
This tool keeps that lane separate from historical PIT evidence while measuring
whether the paper sample has reached its preregistered review thresholds.  It
does not fetch data, run a backtest, or mutate portfolio state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "run287-forward-estimate-evidence-gate-v1"
CONTRACT_SCHEMA_VERSION = "run287-forward-estimate-evidence-gate-contract-v1"
STATUS_BLOCKED = "BLOCKED_FORWARD_EVIDENCE_CONTRACT"
STATUS_UNDERPOWERED = "UNDERPOWERED_FORWARD_PAPER"
STATUS_READY = "READY_FORWARD_PAPER_REVIEW_ONLY"

REQUIRED_SNAPSHOT_COLUMNS = {
    "ticker",
    "as_of_date",
    "available_from",
    "fetch_source",
    "eps_estimate_access",
    "revenue_estimate_access",
    "vendor_estimate_access",
    "has_forward_estimate",
}
STABLE_EVENT_ID_COLUMNS = {"event_id", "estimate_id", "vendor_event_id", "source_event_id"}
DELISTED_COLUMNS = {"is_delisted", "delisted_at", "listing_status"}
ADR_IDENTITY_COLUMNS = {"adr_flag", "depositary_receipt_flag", "primary_listing_ticker", "issuer_id"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def integer(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_exact_timezone_timestamp(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    if isinstance(value, pd.Timestamp):
        return value.tzinfo is not None and value.hour + value.minute + value.second + value.microsecond >= 0
    text = str(value).strip()
    if not ("T" in text or " " in text):
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def load_json_object(path: Path, label: str, failures: list[str]) -> dict[str, Any]:
    if not path.is_file():
        failures.append(f"missing_{label}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        failures.append(f"invalid_{label}")
        return {}
    if not isinstance(payload, dict):
        failures.append(f"invalid_{label}_root")
        return {}
    return payload


def load_archive_index(path: Path, failures: list[str]) -> list[dict[str, Any]]:
    if not path.is_file():
        failures.append("missing_archive_index")
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                failures.append(f"archive_index_row_{line_number}_not_object")
                continue
            rows.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError):
        failures.append("invalid_archive_index")
    return rows


def snapshot_date_from_name(path: Path) -> str:
    match = re.fullmatch(r"estimates_(\d{8})\.parquet", path.name)
    if not match:
        return ""
    raw = match.group(1)
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"


def audit_snapshots(
    snapshot_dir: Path,
    index_rows: list[dict[str, Any]],
    failures: list[str],
) -> tuple[dict[str, Any], pd.DataFrame]:
    files = sorted(snapshot_dir.glob("estimates_*.parquet")) if snapshot_dir.is_dir() else []
    if not files:
        failures.append("missing_snapshot_files")
        return {}, pd.DataFrame()

    latest_index_by_date: dict[str, dict[str, Any]] = {}
    for row in index_rows:
        fetch_date = str(row.get("fetch_date") or "")
        if fetch_date:
            latest_index_by_date[fetch_date] = row

    frames: list[pd.DataFrame] = []
    daily_rows: list[dict[str, Any]] = []
    hash_mismatches: list[str] = []
    for file in files:
        file_date = snapshot_date_from_name(file)
        if not file_date:
            failures.append(f"invalid_snapshot_filename:{file.name}")
            continue
        try:
            frame = pd.read_parquet(file)
        except Exception as exc:  # pragma: no cover - defensive provider artifact boundary
            failures.append(f"unreadable_snapshot:{file.name}:{type(exc).__name__}")
            continue
        missing = sorted(REQUIRED_SNAPSHOT_COLUMNS - set(frame.columns))
        if missing:
            failures.append(f"missing_snapshot_columns:{file.name}:{','.join(missing)}")
            continue
        frame = frame.copy()
        frame["_snapshot_file"] = file.name
        frames.append(frame)
        true_mask = pd.to_numeric(frame["has_forward_estimate"], errors="coerce").fillna(0).gt(0)
        digest = sha256_file(file)
        indexed_digest = str((latest_index_by_date.get(file_date) or {}).get("snapshot_sha256") or "")
        if not indexed_digest:
            hash_mismatches.append(f"{file.name}:missing_index_hash")
        elif digest != indexed_digest:
            hash_mismatches.append(f"{file.name}:sha256_mismatch")
        daily_rows.append(
            {
                "snapshot_date": file_date,
                "snapshot_file": file.name,
                "snapshot_sha256": digest,
                "row_count": len(frame),
                "distinct_ticker_count": int(frame["ticker"].astype(str).nunique()),
                "true_estimate_row_count": int(true_mask.sum()),
                "true_estimate_ticker_count": int(frame.loc[true_mask, "ticker"].astype(str).nunique()),
                "indexed_hash_match": bool(indexed_digest and digest == indexed_digest),
            }
        )

    if not frames:
        failures.append("no_valid_snapshot_frames")
        return {}, pd.DataFrame(daily_rows)
    if hash_mismatches:
        failures.extend(f"snapshot_index_integrity:{item}" for item in hash_mismatches)

    combined = pd.concat(frames, ignore_index=True)
    as_of = pd.to_datetime(combined["as_of_date"], errors="coerce", utc=True)
    available = pd.to_datetime(combined["available_from"], errors="coerce", utc=True)
    invalid_as_of = int(as_of.isna().sum())
    invalid_available = int(available.isna().sum())
    as_of_exact = combined["as_of_date"].map(is_exact_timezone_timestamp)
    future_exact = as_of_exact & available.gt(as_of)
    future_date_only = (~as_of_exact) & available.dt.normalize().gt(as_of.dt.normalize())
    future_rows = int((future_exact | future_date_only).fillna(False).sum())
    duplicates = int(combined.duplicated(["ticker", "as_of_date"]).sum())
    if invalid_as_of:
        failures.append(f"invalid_as_of_date_rows:{invalid_as_of}")
    if invalid_available:
        failures.append(f"invalid_available_from_rows:{invalid_available}")
    if future_rows:
        failures.append(f"future_availability_rows:{future_rows}")
    if duplicates:
        failures.append(f"duplicate_ticker_date_rows:{duplicates}")

    true_mask = pd.to_numeric(combined["has_forward_estimate"], errors="coerce").fillna(0).gt(0)
    true_rows = combined.loc[true_mask]
    access_ok = (
        true_rows["vendor_estimate_access"].fillna(False).astype(bool)
        & (
            true_rows["eps_estimate_access"].fillna(False).astype(bool)
            | true_rows["revenue_estimate_access"].fillna(False).astype(bool)
        )
    )
    bad_true_access = int((~access_ok).sum())
    if bad_true_access:
        failures.append(f"true_estimate_without_access:{bad_true_access}")

    exact_count = int(combined["available_from"].map(is_exact_timezone_timestamp).sum())
    latest_date = max((row["snapshot_date"] for row in daily_rows), default="")
    latest = combined.loc[combined["as_of_date"].astype(str).str[:10].eq(latest_date)]
    latest_true = pd.to_numeric(latest["has_forward_estimate"], errors="coerce").fillna(0).gt(0)
    false_rows = combined.loc[~true_mask]
    numeric_fields = [field for field in ("est_eps_fy1", "est_eps_fy2", "est_rev_fy1") if field in combined]
    placeholder_numeric_rows = (
        int(false_rows[numeric_fields].notna().any(axis=1).sum()) if numeric_fields else 0
    )
    columns = set(combined.columns)
    audit = {
        "snapshot_file_count": len(daily_rows),
        "snapshot_row_count": len(combined),
        "snapshot_date_count": len({row["snapshot_date"] for row in daily_rows}),
        "first_snapshot_date": min((row["snapshot_date"] for row in daily_rows), default=""),
        "latest_snapshot_date": latest_date,
        "attempted_distinct_ticker_count": int(combined["ticker"].astype(str).nunique()),
        "true_estimate_row_count": int(true_mask.sum()),
        "true_estimate_distinct_ticker_count": int(true_rows["ticker"].astype(str).nunique()),
        "latest_snapshot_row_count": len(latest),
        "latest_true_estimate_row_count": int(latest_true.sum()),
        "fetch_source_counts": {
            str(key): int(value) for key, value in combined["fetch_source"].astype(str).value_counts().items()
        },
        "true_estimate_fetch_source_counts": {
            str(key): int(value) for key, value in true_rows["fetch_source"].astype(str).value_counts().items()
        },
        "duplicate_ticker_date_row_count": duplicates,
        "future_availability_row_count": future_rows,
        "exact_timezone_available_from_count": exact_count,
        "exact_timezone_available_from_ratio": exact_count / max(1, len(combined)),
        "date_only_or_timezone_missing_available_from_count": len(combined) - exact_count,
        "false_estimate_rows_with_numeric_placeholders": placeholder_numeric_rows,
        "stable_event_id_columns_present": sorted(columns & STABLE_EVENT_ID_COLUMNS),
        "delisted_metadata_columns_present": sorted(columns & DELISTED_COLUMNS),
        "adr_identity_columns_present": sorted(columns & ADR_IDENTITY_COLUMNS),
        "snapshot_index_hash_mismatches": hash_mismatches,
    }
    return audit, pd.DataFrame(daily_rows)


def paper_gate(ledger: Mapping[str, Any], failures: list[str]) -> dict[str, Any]:
    expected_false = (
        "historical_backtest_acceptance_allowed",
        "live_trading_enabled",
        "production_promotion_allowed",
        "target_books_mutated",
        "valid_for_backtest",
        "valid_for_production",
        "fullrun_dispatched",
    )
    for field in expected_false:
        if ledger.get(field) is not False:
            failures.append(f"paper_ledger_{field}_not_false")
    readiness = ledger.get("review_readiness") or {}
    if not isinstance(readiness, Mapping):
        failures.append("paper_ledger_review_readiness_not_object")
        readiness = {}
    if readiness.get("paper_only") is not True:
        failures.append("paper_ledger_review_readiness_paper_only_not_true")
    if readiness.get("valid_for_historical_backtest_acceptance") is not False:
        failures.append("paper_ledger_historical_acceptance_not_false")
    sample_checks = readiness.get("sample_checks") or {}

    def actual(name: str) -> int:
        value = sample_checks.get(name) or {}
        return integer(value.get("actual")) if isinstance(value, Mapping) else 0

    observed = {
        "ledger_as_of_date": str(ledger.get("as_of_date") or ""),
        "ledger_status": str(ledger.get("status") or ""),
        "review_readiness_status": str(readiness.get("status") or ""),
        "review_ready": readiness.get("review_ready") is True,
        "decision_date_count": integer((ledger.get("coverage") or {}).get("decision_date_count")),
        "observation_count": integer((ledger.get("coverage") or {}).get("observation_count")),
        "unique_ticker_count": integer((ledger.get("coverage") or {}).get("unique_ticker_count")),
        "distinct_true_forward_ticker_count": integer(readiness.get("distinct_true_forward_ticker_count")),
        "resolved_outcome_count": integer(readiness.get("resolved_outcome_count")),
        "decision_week_blocks_21d": actual("decision_week_blocks_21d"),
        "decision_week_blocks_63d": actual("decision_week_blocks_63d"),
        "source_observed_at_utc": str((ledger.get("capture_audit") or {}).get("source_observed_at_utc") or ""),
        "source_receipt_lag_days": integer((ledger.get("capture_audit") or {}).get("source_receipt_lag_days"), -1),
    }
    if observed["source_observed_at_utc"] and not is_exact_timezone_timestamp(observed["source_observed_at_utc"]):
        failures.append("paper_ledger_source_observed_at_not_exact_timezone")
    return observed


def write_report(output_dir: Path, summary: Mapping[str, Any]) -> None:
    archive = summary.get("archive") or {}
    paper = summary.get("paper_gate") or {}
    repeat = summary.get("coverage_repeat_gate") or {}
    lines = [
        "# Run287 forward estimate evidence gate",
        "",
        f"- Status: `{summary['status']}`",
        f"- Archive window: `{archive.get('first_snapshot_date', '')}` to `{archive.get('latest_snapshot_date', '')}`",
        f"- True estimate tickers: `{archive.get('true_estimate_distinct_ticker_count', 0)}` / `{summary['universe_size']}`",
        f"- Ledger-observed true-forward tickers: `{paper.get('distinct_true_forward_ticker_count', 0)}` / `{summary['thresholds']['distinct_true_forward_tickers']}`",
        f"- Resolved 63D outcomes: `{paper.get('resolved_outcome_count', 0)}` / `{summary['thresholds']['resolved_outcomes_63d']}`",
        f"- 21D week blocks: `{paper.get('decision_week_blocks_21d', 0)}` / `{summary['thresholds']['decision_week_blocks_21d']}`",
        f"- 63D week blocks: `{paper.get('decision_week_blocks_63d', 0)}` / `{summary['thresholds']['decision_week_blocks_63d']}`",
        f"- Coverage increase versus frozen baseline: `{repeat.get('coverage_increase_percentage_points', 0.0):.4f}`pp / `{repeat.get('required_increase_percentage_points', 0.0):.2f}`pp",
        "",
        "## Historical PIT boundary",
        "",
        f"- Historical source screen allowed: `{str(summary['historical_source_screen_allowed']).lower()}`",
        f"- Exact timezone-bearing `available_from`: `{archive.get('exact_timezone_available_from_count', 0)}` / `{archive.get('snapshot_row_count', 0)}`",
        f"- PIT universe label clean: `{str(summary['identity']['pit_universe_label_clean']).lower()}`",
        f"- Blockers: `{json.dumps(summary['historical_source_blockers'], sort_keys=True)}`",
        "- Numeric placeholders on missing estimate rows are never counted as estimate coverage.",
        "",
        "## Forward paper gate",
        "",
        f"- Review ready: `{str(paper.get('review_ready', False)).lower()}`",
        f"- Archive-to-ledger true-ticker utilization: `{summary['archive_to_ledger_true_ticker_utilization']:.2%}`",
        f"- Next action: `{summary['next_action']}`",
        "- A paper review can never promote this forward-only archive into historical CAGR/MDD evidence.",
        "",
        "## Safety",
        "",
        "- No provider request, historical backtest, fullrun, order, target-book mutation, weight change, cash-policy change, production activation, or live trading was performed.",
    ]
    if summary.get("contract_failures"):
        lines.extend(["", "## Contract failures", "", *[f"- `{item}`" for item in summary["contract_failures"]]])
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(
    *,
    snapshot_dir: str,
    archive_index: str,
    collection_checkpoint: str,
    paper_ledger_summary: str,
    output_dir: str,
    universe_size: int = 993,
    baseline_true_ticker_count: int = 13,
    repeat_coverage_increase_pp: float = 5.0,
    required_distinct_true_tickers: int = 50,
    required_resolved_outcomes: int = 200,
    required_week_blocks_21d: int = 12,
    required_week_blocks_63d: int = 8,
) -> dict[str, Any]:
    failures: list[str] = []
    snapshots = resolve_path(snapshot_dir)
    index_path = resolve_path(archive_index)
    checkpoint_path = resolve_path(collection_checkpoint)
    ledger_path = resolve_path(paper_ledger_summary)
    destination = resolve_path(output_dir)

    index_rows = load_archive_index(index_path, failures)
    archive, daily = audit_snapshots(snapshots, index_rows, failures)
    checkpoint = load_json_object(checkpoint_path, "collection_checkpoint", failures)
    ledger = load_json_object(ledger_path, "paper_ledger_summary", failures)
    paper = paper_gate(ledger, failures) if ledger else {}

    true_count = integer(archive.get("true_estimate_distinct_ticker_count"))
    observed_count = integer(paper.get("distinct_true_forward_ticker_count"))
    coverage_increase_pp = (true_count - baseline_true_ticker_count) / max(1, universe_size) * 100.0
    repeat_threshold_met = coverage_increase_pp >= repeat_coverage_increase_pp
    pit_clean = bool(((checkpoint.get("universe") or {}).get("source") or {}).get("pit_universe_label_clean") is True)
    forward_only = checkpoint.get("forward_only") is True
    historical_blockers: list[str] = []
    if forward_only:
        historical_blockers.append("archive_is_forward_only")
    if number(archive.get("exact_timezone_available_from_ratio")) < 1.0:
        historical_blockers.append("available_from_not_exact_timezone_100pct")
    if not archive.get("stable_event_id_columns_present"):
        historical_blockers.append("stable_vendor_event_id_missing")
    if not archive.get("delisted_metadata_columns_present"):
        historical_blockers.append("delisted_metadata_missing")
    if not archive.get("adr_identity_columns_present"):
        historical_blockers.append("adr_global_identity_metadata_missing")
    if not pit_clean:
        historical_blockers.append("pit_universe_label_not_clean")
    if not repeat_threshold_met:
        historical_blockers.append("coverage_increase_below_5pp_repeat_threshold")

    thresholds = {
        "distinct_true_forward_tickers": required_distinct_true_tickers,
        "resolved_outcomes_63d": required_resolved_outcomes,
        "decision_week_blocks_21d": required_week_blocks_21d,
        "decision_week_blocks_63d": required_week_blocks_63d,
    }
    computed_paper_ready = bool(
        observed_count >= required_distinct_true_tickers
        and integer(paper.get("resolved_outcome_count")) >= required_resolved_outcomes
        and integer(paper.get("decision_week_blocks_21d")) >= required_week_blocks_21d
        and integer(paper.get("decision_week_blocks_63d")) >= required_week_blocks_63d
        and paper.get("review_ready") is True
    )
    status = STATUS_BLOCKED if failures else (STATUS_READY if computed_paper_ready else STATUS_UNDERPOWERED)
    if observed_count < required_distinct_true_tickers:
        next_action = "continue_bounded_incremental_collection_until_50_distinct_true_forward_tickers"
    elif integer(paper.get("resolved_outcome_count")) < required_resolved_outcomes:
        next_action = "wait_for_exact_21d_63d_outcomes_without_retuning"
    elif not computed_paper_ready:
        next_action = "wait_for_preregistered_week_block_and_performance_checks"
    else:
        next_action = "prepare_paper_only_review_package_no_historical_promotion"

    latest_index = index_rows[-1] if index_rows else {}
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract_schema_version": CONTRACT_SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": status,
        "universe_size": universe_size,
        "archive": archive,
        "archive_index": {
            "row_count": len(index_rows),
            "latest_fetch_date": str(latest_index.get("fetch_date") or ""),
            "latest_collector_status": str(latest_index.get("collector_status") or ""),
            "latest_tripped_vendors": list(latest_index.get("entitlement_circuit_tripped_vendors") or []),
            "latest_estimated_http_requests_avoided": integer(latest_index.get("estimated_estimate_http_requests_avoided")),
        },
        "identity": {
            "pit_universe_label_clean": pit_clean,
            "current_universe_proxy": not pit_clean,
            "checkpoint_ticker_count": integer((checkpoint.get("universe") or {}).get("ticker_count")),
            "checkpoint_eligible_ticker_count": integer((checkpoint.get("universe") or {}).get("eligible_ticker_count")),
        },
        "paper_gate": paper,
        "thresholds": thresholds,
        "archive_to_ledger_true_ticker_utilization": observed_count / max(1, true_count),
        "coverage_repeat_gate": {
            "frozen_baseline_true_ticker_count": baseline_true_ticker_count,
            "current_true_ticker_count": true_count,
            "coverage_increase_ticker_count": true_count - baseline_true_ticker_count,
            "coverage_increase_percentage_points": coverage_increase_pp,
            "required_increase_percentage_points": repeat_coverage_increase_pp,
            "threshold_met": repeat_threshold_met,
        },
        "historical_source_blockers": historical_blockers,
        "historical_source_screen_allowed": False,
        "historical_generated_book_experiment_allowed": False,
        "same_arm_historical_retest_allowed": False,
        "forward_paper_review_ready": computed_paper_ready,
        "next_action": next_action,
        "contract_failures": failures,
        "research_only": True,
        "paper_only": True,
        "historical_cagr_mdd_evidence_changed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "selector_weights_changed": False,
        "cash_policy_changed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    destination.mkdir(parents=True, exist_ok=True)
    write_json(destination / "summary.json", summary)
    daily.to_csv(destination / "snapshot_daily.csv", index=False)
    write_report(destination, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", default="data_pit/events/earnings_estimates")
    parser.add_argument("--archive-index", default="data_pit/events/earnings_estimates/archive_index.jsonl")
    parser.add_argument("--collection-checkpoint", default="data_pit/events/earnings_estimates/collection_checkpoint.json")
    parser.add_argument("--paper-ledger-summary", default="outputs/free_data_forward_paper_ledger/summary.json")
    parser.add_argument("--output-dir", default="outputs/run287_forward_estimate_evidence_gate")
    parser.add_argument("--universe-size", type=int, default=993)
    parser.add_argument("--baseline-true-ticker-count", type=int, default=13)
    parser.add_argument("--repeat-coverage-increase-pp", type=float, default=5.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = run(
        snapshot_dir=args.snapshot_dir,
        archive_index=args.archive_index,
        collection_checkpoint=args.collection_checkpoint,
        paper_ledger_summary=args.paper_ledger_summary,
        output_dir=args.output_dir,
        universe_size=args.universe_size,
        baseline_true_ticker_count=args.baseline_true_ticker_count,
        repeat_coverage_increase_pp=args.repeat_coverage_increase_pp,
    )
    print(json.dumps({"status": payload["status"], "output_dir": str(resolve_path(args.output_dir))}, sort_keys=True))


if __name__ == "__main__":
    main()

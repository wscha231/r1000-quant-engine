#!/usr/bin/env python3
"""Resolve forward outcomes for frozen Run287 held/candidate risk signals.

The source decision archive is immutable.  This tool appends separate signal
and outcome events, builds a bounded unresolved price universe, and reports
diagnostics only.  It never tunes the risk thresholds or changes a book, cash,
orders, historical backtests, production, or live trading.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(REPO_ROOT))

from tools.run_free_data_forward_paper_ledger import (  # noqa: E402
    _max_drawdown,
    load_cached_prices,
    load_nyse_sessions,
)
from tools.archive_run287_decision_observation import (  # noqa: E402
    canonical_tracked_contract_sha256,
)
from tools.build_run287_risk_outcome_parent_anchor import (  # noqa: E402
    ANCHOR_SCHEMA_VERSION,
    ANCHOR_STATUSES,
    EMPTY_SHA256,
    FALSE_SAFETY_FLAGS as PARENT_ANCHOR_FALSE_SAFETY_FLAGS,
    OUTCOME_CHAIN_SCHEMA_VERSION,
    PARENT_ACCEPTANCE_STATUSES,
    event_log_metadata,
    sha256_bytes,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


SCHEMA_VERSION = "run287-risk-outcome-archive-v1"
EVENT_LOG_NAME = "risk_outcome_events.jsonl"
READY_STATUS = "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY"
SKIPPED_STATUS = "SKIPPED_NO_DECISION_OBSERVATIONS"
BLOCKED_STATUS = "BLOCKED_RISK_OUTCOME_ARCHIVE"
NEEDS_PRICE_CACHE_STATUS = "NEEDS_PRICE_CACHE_BOOTSTRAP_REVIEW_ONLY"
CONTRACT_EXPECTED_SHA256 = (
    "cc15a0a79968723ad0bdeef34a56b2c47e547dc8e9d469dfe9d3cfbc53986103"
)
ALLOWED_STATES = {"ALERT", "WATCH", "NORMAL", "DATA_INSUFFICIENT"}
FALSE_SOURCE_FLAGS = (
    "portfolio_transition_allowed",
    "orders_generated",
    "target_books_mutated",
    "selector_weight_changed_by_archive",
    "production_activation_allowed",
    "live_trading_enabled",
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def normalize_ticker(value: Any) -> str:
    ticker = clean_text(value).upper().replace(".", "-")
    return "" if ticker in {"", "CASH", "__CASH__"} else ticker


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def truthy(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return clean_text(value).lower() in {"1", "true", "yes", "y"}


def json_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat() if pd.notna(value) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_hash(payload: Any) -> str:
    return sha256_text(canonical_json(payload))


def strict_json_object(
    payload: str | bytes,
    *,
    label: str,
) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label}:duplicate_json_key:{key}")
            result[key] = value
        return result

    try:
        decoded = json.loads(payload, object_pairs_hook=object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}:invalid_json") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{label}:json_object_required")
    return decoded


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return strict_json_object(
        path.read_text(encoding="utf-8"),
        label=str(path),
    )


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        row = strict_json_object(
            raw,
            label=f"{path}:{line_number}",
        )
        event_id = clean_text(row.get("event_id"))
        if path.name == EVENT_LOG_NAME:
            if not event_id:
                raise ValueError(f"missing event_id at {path}:{line_number}")
            if event_id in seen:
                raise ValueError(f"duplicate event_id at {path}:{line_number}:{event_id}")
            seen.add(event_id)
        rows.append(row)
    return rows


def append_events(path: Path, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = path.exists() and path.stat().st_size > 0 and not path.read_bytes().endswith(b"\n")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        if needs_newline:
            handle.write("\n")
        for event in events:
            handle.write(canonical_json(event) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _strict_nonnegative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label}_invalid")
    return value


def _event_log_snapshot(path: Path) -> tuple[bytes, str, int, int]:
    payload = path.read_bytes() if path.is_file() else b""
    digest, size, count = event_log_metadata(
        payload,
        label="risk_outcome_event_log",
    )
    return payload, digest, size, count


def _empty_chain_context(
    *,
    status: str,
    event_log: Path,
) -> dict[str, Any]:
    try:
        initial, digest, size, count = _event_log_snapshot(event_log)
    except ValueError:
        initial, digest, size, count = b"", EMPTY_SHA256, 0, 0
    return {
        "status": status,
        "anchor": {},
        "anchor_sha256": "",
        "initial_event_log_bytes_payload": initial,
        "initial_event_log_sha256": digest,
        "initial_event_log_bytes": size,
        "initial_event_count": count,
        "exact_parent_prefix_verified": False,
    }


def _anchor_parent_fields(anchor: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "parent_summary_sha256": clean_text(
            anchor.get("parent_summary_sha256")
        ),
        "parent_summary_bytes": _strict_nonnegative_integer(
            anchor.get("parent_summary_bytes"),
            "parent_anchor_parent_summary_bytes",
        ),
        "parent_event_log_sha256": clean_text(
            anchor.get("parent_event_log_sha256")
        ),
        "parent_event_log_bytes": _strict_nonnegative_integer(
            anchor.get("parent_event_log_bytes"),
            "parent_anchor_parent_event_log_bytes",
        ),
        "parent_event_count": _strict_nonnegative_integer(
            anchor.get("parent_event_count"),
            "parent_anchor_parent_event_count",
        ),
        "parent_as_of_date": clean_text(anchor.get("parent_as_of_date")),
        "carried_quarantined_prefix_event_count": (
            _strict_nonnegative_integer(
                anchor.get("carried_quarantined_prefix_event_count"),
                "parent_anchor_carried_quarantined_prefix_event_count",
            )
        ),
        "parent_acceptance_status": clean_text(
            anchor.get("parent_acceptance_status")
        ),
        "parent_accepted_manifest_sha256": clean_text(
            anchor.get("parent_accepted_manifest_sha256")
        ),
        "parent_accepted_manifest_bytes": _strict_nonnegative_integer(
            anchor.get("parent_accepted_manifest_bytes"),
            "parent_anchor_parent_accepted_manifest_bytes",
        ),
        "parent_accepted_manifest_as_of_date": clean_text(
            anchor.get("parent_accepted_manifest_as_of_date")
        ),
    }


def _verify_prior_invocation_summary(
    *,
    summary: Mapping[str, Any],
    anchor: Mapping[str, Any],
    anchor_sha256: str,
    current_event_log_sha256: str,
    current_event_log_bytes: int,
    current_event_count: int,
) -> None:
    chain = summary.get("outcome_chain")
    if not isinstance(chain, dict):
        raise ValueError("prior_invocation_outcome_chain_missing")
    if chain.get("schema_version") != OUTCOME_CHAIN_SCHEMA_VERSION:
        raise ValueError("prior_invocation_outcome_chain_schema_invalid")
    if chain.get("status") != "VERIFIED_APPEND_ONLY":
        raise ValueError("prior_invocation_outcome_chain_not_verified")
    if (
        chain.get("exact_parent_prefix_verified") is not True
        or chain.get("append_only_verified") is not True
    ):
        raise ValueError("prior_invocation_outcome_chain_proof_missing")
    expected = {
        "parent_anchor_sha256": anchor_sha256,
        "parent_anchor_status": anchor.get("status"),
        **_anchor_parent_fields(anchor),
        "current_event_log_sha256": current_event_log_sha256,
        "current_event_log_bytes": current_event_log_bytes,
        "current_event_count": current_event_count,
    }
    for field, value in expected.items():
        if chain.get(field) != value:
            raise ValueError(
                f"prior_invocation_outcome_chain_{field}_mismatch"
            )
    carried = int(chain["carried_quarantined_prefix_event_count"])
    if chain.get("trusted_event_count") != current_event_count - carried:
        raise ValueError(
            "prior_invocation_outcome_chain_trusted_event_count_mismatch"
        )
    declared_hash = clean_text(
        (summary.get("outputs") or {}).get("event_log_sha256")
    )
    if declared_hash and declared_hash != current_event_log_sha256:
        raise ValueError("prior_invocation_summary_event_log_sha256_mismatch")


def prepare_outcome_chain(
    *,
    parent_anchor: str | Path | None,
    expected_prior_invocation_summary_sha256: str,
    output: Path,
    event_log: Path,
) -> tuple[dict[str, Any], list[str]]:
    if not clean_text(parent_anchor):
        return (
            _empty_chain_context(status="UNANCHORED", event_log=event_log),
            ["risk_outcome_parent_anchor_missing"],
        )
    anchor_path = repo_path(str(parent_anchor))
    if not anchor_path.is_file():
        return (
            _empty_chain_context(status="UNANCHORED", event_log=event_log),
            ["risk_outcome_parent_anchor_missing"],
        )
    try:
        expected_prior_summary_sha256 = clean_text(
            expected_prior_invocation_summary_sha256
        ).lower()
        if expected_prior_summary_sha256 and (
            len(expected_prior_summary_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in expected_prior_summary_sha256
            )
        ):
            raise ValueError(
                "expected_prior_invocation_summary_sha256_invalid"
            )
        anchor_bytes = anchor_path.read_bytes()
        anchor = strict_json_object(
            anchor_bytes,
            label="risk_outcome_parent_anchor",
        )
        if anchor.get("schema_version") != ANCHOR_SCHEMA_VERSION:
            raise ValueError("parent_anchor_schema_invalid")
        if anchor.get("status") not in ANCHOR_STATUSES:
            raise ValueError("parent_anchor_status_invalid")
        if anchor.get("review_only") is not True:
            raise ValueError("parent_anchor_not_review_only")
        for field in PARENT_ANCHOR_FALSE_SAFETY_FLAGS:
            if anchor.get(field) is not False:
                raise ValueError(f"parent_anchor_{field}_not_false")
        parent = _anchor_parent_fields(anchor)
        if (
            parent["carried_quarantined_prefix_event_count"]
            > parent["parent_event_count"]
        ):
            raise ValueError("parent_anchor_quarantine_exceeds_event_count")
        acceptance_status = parent["parent_acceptance_status"]
        if acceptance_status not in PARENT_ACCEPTANCE_STATUSES:
            raise ValueError("parent_anchor_acceptance_status_invalid")
        accepted_sha256 = parent["parent_accepted_manifest_sha256"]
        accepted_head_valid = bool(
            len(accepted_sha256) == 64
            and all(
                character in "0123456789abcdef"
                for character in accepted_sha256.lower()
            )
            and parent["parent_accepted_manifest_bytes"] > 0
            and parent["parent_accepted_manifest_as_of_date"]
            == parent["parent_as_of_date"]
        )
        accepted_head_empty = bool(
            not accepted_sha256
            and parent["parent_accepted_manifest_bytes"] == 0
            and not parent["parent_accepted_manifest_as_of_date"]
        )
        if anchor["status"] == "GENESIS_EMPTY":
            if any(
                (
                    parent["parent_summary_sha256"],
                    parent["parent_summary_bytes"],
                    parent["parent_event_log_bytes"],
                    parent["parent_event_count"],
                    parent["parent_as_of_date"],
                )
            ) or (
                parent["parent_event_log_sha256"] != EMPTY_SHA256
                or acceptance_status != "NO_PRIOR_STATE"
                or not accepted_head_empty
            ):
                raise ValueError("parent_anchor_genesis_fields_invalid")
        elif anchor["status"] == "VERIFIED_EMPTY_PARENT":
            if (
                not parent["parent_summary_sha256"]
                or parent["parent_summary_bytes"] <= 0
                or parent["parent_event_log_sha256"] != EMPTY_SHA256
                or parent["parent_event_log_bytes"] != 0
                or parent["parent_event_count"] != 0
                or not parent["parent_as_of_date"]
            ):
                raise ValueError("parent_anchor_empty_parent_fields_invalid")
        elif (
            not parent["parent_summary_sha256"]
            or parent["parent_summary_bytes"] <= 0
            or len(parent["parent_event_log_sha256"]) != 64
            or parent["parent_event_log_bytes"] <= 0
            or parent["parent_event_count"] <= 0
            or not parent["parent_as_of_date"]
        ):
            raise ValueError("parent_anchor_verified_parent_fields_invalid")
        if anchor["status"] != "GENESIS_EMPTY":
            if acceptance_status == "VERIFIED_ACCEPTED_HEAD":
                if not accepted_head_valid:
                    raise ValueError(
                        "parent_anchor_accepted_head_fields_invalid"
                    )
            elif acceptance_status == "QUARANTINED_LEGACY":
                if (
                    not accepted_head_empty
                    or parent[
                        "carried_quarantined_prefix_event_count"
                    ]
                    != parent["parent_event_count"]
                ):
                    raise ValueError(
                        "parent_anchor_legacy_quarantine_fields_invalid"
                    )
            else:
                raise ValueError(
                    "parent_anchor_existing_state_not_accepted"
                )

        current, current_sha, current_size, current_count = (
            _event_log_snapshot(event_log)
        )
        parent_size = parent["parent_event_log_bytes"]
        if current_size < parent_size:
            raise ValueError("parent_event_log_prefix_truncated")
        prefix = current[:parent_size]
        if prefix and not prefix.endswith(b"\n"):
            raise ValueError("parent_event_log_prefix_boundary_invalid")
        prefix_sha, _, prefix_count = event_log_metadata(
            prefix,
            label="risk_outcome_parent_event_log_prefix",
        )
        if prefix_sha != parent["parent_event_log_sha256"]:
            raise ValueError("parent_event_log_prefix_sha256_mismatch")
        if prefix_count != parent["parent_event_count"]:
            raise ValueError("parent_event_log_prefix_count_mismatch")

        summary_path = output / "summary.json"
        if summary_path.is_file():
            summary_bytes = summary_path.read_bytes()
            summary_sha = sha256_bytes(summary_bytes)
            summary = strict_json_object(
                summary_bytes,
                label="current_risk_outcome_summary",
            )
            if summary_sha == parent["parent_summary_sha256"]:
                if (
                    expected_prior_summary_sha256
                    and expected_prior_summary_sha256 != summary_sha
                ):
                    raise ValueError(
                        "expected_prior_invocation_summary_sha256_mismatch"
                    )
                if len(summary_bytes) != parent["parent_summary_bytes"]:
                    raise ValueError("parent_summary_bytes_mismatch")
                if (
                    current_size != parent_size
                    or current_count != parent["parent_event_count"]
                    or current_sha != parent["parent_event_log_sha256"]
                ):
                    raise ValueError(
                        "unsealed_event_log_extension_before_resolver"
                    )
            else:
                if not expected_prior_summary_sha256:
                    raise ValueError(
                        "expected_prior_invocation_summary_sha256_missing"
                    )
                if expected_prior_summary_sha256 != summary_sha:
                    raise ValueError(
                        "expected_prior_invocation_summary_sha256_mismatch"
                    )
                _verify_prior_invocation_summary(
                    summary=summary,
                    anchor=anchor,
                    anchor_sha256=sha256_bytes(anchor_bytes),
                    current_event_log_sha256=current_sha,
                    current_event_log_bytes=current_size,
                    current_event_count=current_count,
                )
        elif anchor["status"] != "GENESIS_EMPTY":
            raise ValueError("parent_summary_missing")
        elif current_size or current_count:
            raise ValueError("genesis_event_log_not_empty")
        elif expected_prior_summary_sha256:
            raise ValueError(
                "expected_prior_invocation_summary_sha256_without_summary"
            )

        return (
            {
                "status": "VERIFIED_APPEND_ONLY",
                "anchor": anchor,
                "anchor_sha256": sha256_bytes(anchor_bytes),
                "initial_event_log_bytes_payload": current,
                "initial_event_log_sha256": current_sha,
                "initial_event_log_bytes": current_size,
                "initial_event_count": current_count,
                "exact_parent_prefix_verified": True,
            },
            [],
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        return (
            _empty_chain_context(
                status="BLOCKED_PARENT_ANCHOR",
                event_log=event_log,
            ),
            [f"risk_outcome_parent_anchor_invalid:{exc}"],
        )


def verify_event_log_append(
    context: Mapping[str, Any],
    event_log: Path,
    *,
    expected_appended_event_count: int,
) -> None:
    if context.get("status") != "VERIFIED_APPEND_ONLY":
        raise ValueError("risk outcome event log mutation requires a verified parent anchor")
    current, _, _, current_count = _event_log_snapshot(event_log)
    initial = context["initial_event_log_bytes_payload"]
    if not current.startswith(initial):
        raise ValueError("risk outcome event log rewrote the invocation prefix")
    if (
        current_count
        != int(context["initial_event_count"])
        + int(expected_appended_event_count)
    ):
        raise ValueError("risk outcome event log append count mismatch")
    anchor = context["anchor"]
    parent_size = int(anchor["parent_event_log_bytes"])
    parent_prefix = current[:parent_size]
    if parent_prefix and not parent_prefix.endswith(b"\n"):
        raise ValueError("risk outcome parent prefix boundary changed")
    parent_sha, _, parent_count = event_log_metadata(
        parent_prefix,
        label="risk_outcome_parent_event_log_prefix_after_append",
    )
    if (
        parent_sha != anchor["parent_event_log_sha256"]
        or parent_count != anchor["parent_event_count"]
    ):
        raise ValueError("risk outcome parent prefix changed after append")


def finalize_outcome_chain(
    context: Mapping[str, Any],
    event_log: Path,
    *,
    as_of_date: str,
) -> dict[str, Any]:
    _, current_sha, current_size, current_count = _event_log_snapshot(
        event_log
    )
    anchor = context.get("anchor") or {}
    carried = int(
        anchor.get(
            "carried_quarantined_prefix_event_count",
            current_count,
        )
    )
    verified = context.get("status") == "VERIFIED_APPEND_ONLY"
    return {
        "schema_version": OUTCOME_CHAIN_SCHEMA_VERSION,
        "status": context.get("status") or "BLOCKED_PARENT_ANCHOR",
        "parent_anchor_sha256": context.get("anchor_sha256") or "",
        "parent_anchor_status": anchor.get("status") or "",
        "parent_summary_sha256": anchor.get("parent_summary_sha256") or "",
        "parent_summary_bytes": int(anchor.get("parent_summary_bytes") or 0),
        "parent_event_log_sha256": (
            anchor.get("parent_event_log_sha256") or EMPTY_SHA256
        ),
        "parent_event_log_bytes": int(
            anchor.get("parent_event_log_bytes") or 0
        ),
        "parent_event_count": int(anchor.get("parent_event_count") or 0),
        "parent_as_of_date": anchor.get("parent_as_of_date") or "",
        "carried_quarantined_prefix_event_count": carried,
        "parent_acceptance_status": (
            anchor.get("parent_acceptance_status") or ""
        ),
        "parent_accepted_manifest_sha256": (
            anchor.get("parent_accepted_manifest_sha256") or ""
        ),
        "parent_accepted_manifest_bytes": int(
            anchor.get("parent_accepted_manifest_bytes") or 0
        ),
        "parent_accepted_manifest_as_of_date": (
            anchor.get("parent_accepted_manifest_as_of_date") or ""
        ),
        "current_event_log_sha256": current_sha,
        "current_event_log_bytes": current_size,
        "current_event_count": current_count,
        "current_as_of_date": as_of_date,
        "exact_parent_prefix_verified": bool(
            verified and context.get("exact_parent_prefix_verified")
        ),
        "append_only_verified": verified,
        "trusted_event_count": current_count - carried if verified else 0,
    }


@contextmanager
def exclusive_lock(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / ".run287_risk_outcome.lock"
    try:
        descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"risk outcome archive is already locked: {path}") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()} utc={utc_now()}\n".encode("utf-8"))
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def source_safety_failures(rows: Iterable[Mapping[str, Any]], label: str) -> list[str]:
    failures: list[str] = []
    for index, row in enumerate(rows):
        for flag in FALSE_SOURCE_FLAGS:
            if truthy(row.get(flag)):
                failures.append(f"{label}:{index}:{flag}_true")
        if truthy(row.get("historical_cagr_mdd_evidence_changed")):
            failures.append(f"{label}:{index}:historical_cagr_mdd_evidence_changed_true")
    return failures


def observation_id(family: str, decision_date: str, ticker: str, portfolio: str = "") -> str:
    return sha256_text(f"{SCHEMA_VERSION}|{family}|{decision_date}|{portfolio}|{ticker}")[:24]


def build_observations(
    candidate_rows: list[dict[str, Any]], position_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    failures = source_safety_failures(candidate_rows, "candidate") + source_safety_failures(position_rows, "position")
    proposals: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in position_rows:
        ticker = normalize_ticker(row.get("ticker"))
        decision = clean_text(row.get("as_of_date"))
        if not ticker or not decision or not truthy(row.get("proposed_new_entry")):
            continue
        weight = finite(row.get("advisory_weight"))
        if weight is None or weight <= 0:
            continue
        proposals.setdefault((decision, ticker), []).append(
            {
                "portfolio_kind": clean_text(row.get("portfolio_kind")).lower(),
                "scenario": clean_text(row.get("scenario")),
                "advisory_weight": weight,
            }
        )
    for values in proposals.values():
        values.sort(key=lambda row: (row["portfolio_kind"], row["scenario"], row["advisory_weight"]))

    observations: list[dict[str, Any]] = []
    candidate_keys: set[tuple[str, str]] = set()
    for row in candidate_rows:
        ticker = normalize_ticker(row.get("ticker"))
        decision = clean_text(row.get("as_of_date"))
        state = clean_text(row.get("risk_state")).upper()
        key = (decision, ticker)
        if not decision or not ticker:
            failures.append("candidate_blank_decision_or_ticker")
            continue
        if key in candidate_keys:
            failures.append(f"candidate_duplicate:{decision}:{ticker}")
            continue
        candidate_keys.add(key)
        if state not in ALLOWED_STATES:
            failures.append(f"candidate_invalid_state:{decision}:{ticker}:{state}")
            continue
        if truthy(row.get("risk_state_may_authorize_buy")):
            failures.append(f"candidate_authorizes_buy:{decision}:{ticker}")
        snapshot = {
            "family": "candidate",
            "decision_date": decision,
            "ticker": ticker,
            "risk_state": state,
            "advisory_action": clean_text(row.get("advisory_action")),
            "reason_codes": clean_text(row.get("reason_codes")),
            "history_observations": finite(row.get("history_observations")),
            "signal_return_1d": finite(row.get("return_1d")),
            "signal_spy_excess_return_1d": finite(row.get("spy_excess_return_1d")),
            "signal_return_21d": finite(row.get("return_21d")),
            "signal_spy_excess_return_21d": finite(row.get("spy_excess_return_21d")),
            "signal_drawdown_63d": finite(row.get("drawdown_63d")),
            "proposed_entries": proposals.get(key, []),
        }
        observations.append(
            {
                **snapshot,
                "observation_id": observation_id("candidate", decision, ticker),
                "signal_snapshot_sha256": canonical_hash(snapshot),
                "source_record_event_ids": [clean_text(row.get("event_id"))],
            }
        )

    held_source: list[dict[str, Any]] = []
    for row in position_rows:
        ticker = normalize_ticker(row.get("ticker"))
        marked = finite(row.get("marked_weight"))
        if ticker and marked is not None and marked > 1e-12:
            held_source.append(row)
    held_frame = pd.DataFrame(held_source)
    if not held_frame.empty:
        held_frame["_decision"] = held_frame["as_of_date"].map(clean_text)
        held_frame["_portfolio"] = held_frame["portfolio_kind"].map(lambda value: clean_text(value).lower())
        held_frame["_ticker"] = held_frame["ticker"].map(normalize_ticker)
        for (decision, portfolio, ticker), group in held_frame.groupby(
            ["_decision", "_portfolio", "_ticker"], sort=True
        ):
            states = sorted({clean_text(value).upper() for value in group["held_risk_state"] if clean_text(value)})
            weights = [finite(value) for value in group["marked_weight"]]
            weights = [value for value in weights if value is not None]
            official = [finite(value) for value in group["official_prior_weight"]]
            official = [value for value in official if value is not None]
            if not decision or not portfolio or not ticker:
                failures.append("held_blank_identity")
                continue
            if len(states) != 1 or states[0] not in ALLOWED_STATES:
                failures.append(f"held_state_conflict:{decision}:{portfolio}:{ticker}:{','.join(states)}")
                continue
            if not weights or max(weights) - min(weights) > 1e-9:
                failures.append(f"held_marked_weight_conflict:{decision}:{portfolio}:{ticker}")
                continue
            actions = sorted({clean_text(value) for value in group["held_risk_advisory_action"] if clean_text(value)})
            reasons = sorted({clean_text(value) for value in group["held_risk_reason_codes"] if clean_text(value)})
            if len(actions) > 1 or len(reasons) > 1:
                failures.append(f"held_risk_payload_conflict:{decision}:{portfolio}:{ticker}")
                continue
            snapshot = {
                "family": "held",
                "decision_date": decision,
                "portfolio_kind": portfolio,
                "ticker": ticker,
                "risk_state": states[0],
                "advisory_action": actions[0] if actions else "",
                "reason_codes": reasons[0] if reasons else "",
                "marked_weight": weights[0],
                "official_prior_weight": official[0] if official else None,
                "scenario_keys": sorted({clean_text(value) for value in group["scenario"]}),
            }
            observations.append(
                {
                    **snapshot,
                    "observation_id": observation_id("held", decision, ticker, portfolio),
                    "signal_snapshot_sha256": canonical_hash(snapshot),
                    "source_record_event_ids": sorted(clean_text(value) for value in group["event_id"]),
                }
            )
    observations.sort(key=lambda row: (row["decision_date"], row["family"], row.get("portfolio_kind", ""), row["ticker"]))
    return observations, sorted(set(failures))


def capture_signal_events(
    observations: list[dict[str, Any]], existing: list[dict[str, Any]], recorded_at: str
) -> tuple[list[dict[str, Any]], list[str]]:
    prior = {
        clean_text(event.get("observation_id")): event
        for event in existing
        if event.get("event_type") == "risk_signal_observed"
    }
    new: list[dict[str, Any]] = []
    failures: list[str] = []
    for observation in observations:
        oid = observation["observation_id"]
        if oid in prior:
            if clean_text(prior[oid].get("signal_snapshot_sha256")) != observation["signal_snapshot_sha256"]:
                failures.append(f"immutable_signal_conflict:{oid}")
            continue
        iso = pd.Timestamp(observation["decision_date"]).isocalendar()
        new.append(
            {
                "schema_version": SCHEMA_VERSION,
                "event_id": sha256_text(f"{SCHEMA_VERSION}|risk_signal_observed|{oid}"),
                "event_type": "risk_signal_observed",
                "recorded_at_utc": recorded_at,
                "iso_decision_week": f"{int(iso.year):04d}-W{int(iso.week):02d}",
                "benchmark_ticker": "SPY",
                **observation,
                "review_only": True,
                "threshold_tuning_allowed": False,
                "portfolio_transition_allowed": False,
                "orders_generated": False,
                "target_books_mutated": False,
                "historical_cagr_mdd_evidence_changed": False,
                "production_activation_allowed": False,
                "live_trading_enabled": False,
            }
        )
    return new, failures


def exact_close(frame: pd.DataFrame, when: pd.Timestamp) -> float | None:
    if frame.empty or when not in frame.index:
        return None
    value = frame.loc[when, "close"]
    if isinstance(value, pd.Series):
        value = value.iloc[-1]
    return finite(value)


def max_gain(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    return float((numeric / float(numeric.iloc[0]) - 1.0).max())


def recovery_from_trough(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    trough = float(numeric.min())
    return float(numeric.iloc[-1] / trough - 1.0) if trough > 0 else 0.0


def exact_price_path_sha256(values: pd.Series) -> str:
    payload = [
        {
            "date": pd.Timestamp(index).date().isoformat(),
            "close": float(value),
        }
        for index, value in values.items()
    ]
    return sha256_text(canonical_json(payload))


def outcome_event(
    signal: Mapping[str, Any],
    horizon: int,
    ticker_frame: pd.DataFrame,
    benchmark_frame: pd.DataFrame,
    sessions: pd.DatetimeIndex | None,
    *,
    as_of_date: pd.Timestamp,
    recorded_at: str,
    ticker_hash: str,
    benchmark_hash: str,
) -> tuple[dict[str, Any] | None, str]:
    if sessions is None:
        return None, "pending_exchange_calendar_unavailable"
    decision = pd.Timestamp(signal["decision_date"]).normalize()
    if decision not in sessions:
        return None, "pending_signal_date_not_nyse_session"
    future_sessions = sessions[(sessions > decision) & (sessions <= as_of_date)]
    if len(future_sessions) < horizon:
        return None, "pending_not_elapsed"
    target_sessions = pd.DatetimeIndex(future_sessions[:horizon])
    path = pd.DatetimeIndex([decision, *target_sessions])
    ticker_window = ticker_frame.reindex(path)["close"] if not ticker_frame.empty else pd.Series(dtype=float)
    benchmark_window = benchmark_frame.reindex(path)["close"] if not benchmark_frame.empty else pd.Series(dtype=float)
    if len(ticker_window) != horizon + 1 or ticker_window.isna().any() or (~np.isfinite(ticker_window)).any():
        return None, "pending_ticker_price_path_unavailable"
    if benchmark_window.isna().any() or (~np.isfinite(benchmark_window)).any():
        return None, "pending_benchmark_price_path_unavailable"
    ticker_return = float(ticker_window.iloc[-1] / ticker_window.iloc[0] - 1.0)
    benchmark_return = float(benchmark_window.iloc[-1] / benchmark_window.iloc[0] - 1.0)
    actionable_ticker: float | None = None
    actionable_benchmark: float | None = None
    actionable_dd: float | None = None
    actionable_gain: float | None = None
    actionable_recovery: float | None = None
    if horizon > 1:
        actionable_ticker_window = ticker_window.iloc[1:]
        actionable_benchmark_window = benchmark_window.iloc[1:]
        actionable_ticker = float(actionable_ticker_window.iloc[-1] / actionable_ticker_window.iloc[0] - 1.0)
        actionable_benchmark = float(actionable_benchmark_window.iloc[-1] / actionable_benchmark_window.iloc[0] - 1.0)
        actionable_dd = _max_drawdown(actionable_ticker_window)
        actionable_gain = max_gain(actionable_ticker_window)
        actionable_recovery = recovery_from_trough(actionable_ticker_window)
    oid = clean_text(signal.get("observation_id"))
    return (
        {
            "schema_version": SCHEMA_VERSION,
            "event_id": sha256_text(f"{SCHEMA_VERSION}|forward_outcome_observed|{oid}|{horizon}"),
            "event_type": "forward_outcome_observed",
            "recorded_at_utc": recorded_at,
            "evaluated_as_of_date": as_of_date.date().isoformat(),
            "observation_id": oid,
            "family": signal["family"],
            "portfolio_kind": signal.get("portfolio_kind", ""),
            "decision_date": signal["decision_date"],
            "ticker": signal["ticker"],
            "risk_state": signal["risk_state"],
            "benchmark_ticker": signal["benchmark_ticker"],
            "horizon_trading_days": int(horizon),
            "outcome_date": pd.Timestamp(target_sessions[-1]).date().isoformat(),
            "signal_close_price": float(ticker_window.iloc[0]),
            "next_close_price": float(ticker_window.iloc[1]),
            "outcome_close_price": float(ticker_window.iloc[-1]),
            "ticker_total_return": ticker_return,
            "benchmark_total_return": benchmark_return,
            "spy_excess_total_return": ticker_return - benchmark_return,
            "ticker_max_drawdown": _max_drawdown(ticker_window),
            "benchmark_max_drawdown": _max_drawdown(benchmark_window),
            "ticker_max_gain": max_gain(ticker_window),
            "ticker_recovery_from_trough": recovery_from_trough(ticker_window),
            "actionable_ticker_total_return": actionable_ticker,
            "actionable_benchmark_total_return": actionable_benchmark,
            "actionable_spy_excess_total_return": None
            if actionable_ticker is None or actionable_benchmark is None
            else actionable_ticker - actionable_benchmark,
            "actionable_ticker_max_drawdown": actionable_dd,
            "actionable_ticker_max_gain": actionable_gain,
            "actionable_ticker_recovery_from_trough": actionable_recovery,
            "actionable_start_date": pd.Timestamp(target_sessions[0]).date().isoformat(),
            "actionable_metrics_status": "not_applicable_at_1d" if horizon == 1 else "completed",
            "price_basis": "adjusted_close",
            "price_evidence_hash_basis": "exact_nyse_close_path_v1",
            "ticker_price_path_sha256": exact_price_path_sha256(
                ticker_window
            ),
            "benchmark_price_path_sha256": exact_price_path_sha256(
                benchmark_window
            ),
            "ticker_price_cache_sha256": ticker_hash,
            "benchmark_price_cache_sha256": benchmark_hash,
            "outcome_status": "completed",
            "review_only": True,
            "portfolio_transition_allowed": False,
            "orders_generated": False,
            "target_books_mutated": False,
            "historical_cagr_mdd_evidence_changed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
        },
        "completed",
    )


def evaluate(
    events: list[dict[str, Any]], price_cache: Path, contract: Mapping[str, Any], as_of: pd.Timestamp, recorded_at: str
) -> tuple[list[dict[str, Any]], dict[str, dict[int, str]]]:
    signals = [event for event in events if event.get("event_type") == "risk_signal_observed"]
    outcomes = {
        (clean_text(event.get("observation_id")), int(event.get("horizon_trading_days", 0))): event
        for event in events
        if event.get("event_type") == "forward_outcome_observed"
    }
    horizons = tuple(int(value) for value in contract["outcome_contract"]["horizons_trading_days"])
    decision_dates = pd.to_datetime([signal.get("decision_date") for signal in signals], errors="coerce")
    valid = decision_dates[decision_dates.notna()]
    sessions = load_nyse_sessions(pd.Timestamp(valid.min()), as_of) if len(valid) else pd.DatetimeIndex([])
    frame_cache: dict[str, tuple[pd.DataFrame, str, str]] = {}

    def prices(ticker: str) -> tuple[pd.DataFrame, str, str]:
        if ticker not in frame_cache:
            cache_path = price_cache / px_cache_name(ticker)
            if not cache_path.is_file():
                frame_cache[ticker] = (pd.DataFrame(), "unavailable", "")
                return frame_cache[ticker]
            frame, basis = load_cached_prices(price_cache, ticker)
            frame = frame[frame.index <= as_of].copy() if not frame.empty else frame
            frame_cache[ticker] = (frame, basis, sha256_file(cache_path))
        return frame_cache[ticker]

    appended: list[dict[str, Any]] = []
    evaluations: dict[str, dict[int, str]] = {}
    existing_ids = {clean_text(event.get("event_id")) for event in events}
    for signal in signals:
        oid = clean_text(signal.get("observation_id"))
        ticker_frame, ticker_basis, ticker_hash = prices(clean_text(signal.get("ticker")))
        benchmark_frame, benchmark_basis, benchmark_hash = prices(clean_text(signal.get("benchmark_ticker")))
        evaluations[oid] = {}
        for horizon in horizons:
            if (oid, horizon) in outcomes:
                evaluations[oid][horizon] = "completed"
                continue
            if ticker_basis != "adjusted_close":
                evaluations[oid][horizon] = "pending_ticker_adjusted_price_unavailable"
                continue
            if benchmark_basis != "adjusted_close":
                evaluations[oid][horizon] = "pending_benchmark_adjusted_price_unavailable"
                continue
            event, status = outcome_event(
                signal,
                horizon,
                ticker_frame,
                benchmark_frame,
                sessions,
                as_of_date=as_of,
                recorded_at=recorded_at,
                ticker_hash=ticker_hash,
                benchmark_hash=benchmark_hash,
            )
            evaluations[oid][horizon] = status
            if event is not None and event["event_id"] not in existing_ids:
                appended.append(event)
                existing_ids.add(event["event_id"])
    return appended, evaluations


def build_current_status(
    events: list[dict[str, Any]], evaluations: Mapping[str, Mapping[int, str]], horizons: tuple[int, ...]
) -> pd.DataFrame:
    signals = [event for event in events if event.get("event_type") == "risk_signal_observed"]
    outcomes = {
        (clean_text(event.get("observation_id")), int(event.get("horizon_trading_days", 0))): event
        for event in events
        if event.get("event_type") == "forward_outcome_observed"
    }
    rows: list[dict[str, Any]] = []
    for signal in signals:
        oid = clean_text(signal.get("observation_id"))
        row = {
            key: signal.get(key)
            for key in (
                "observation_id",
                "decision_date",
                "iso_decision_week",
                "family",
                "portfolio_kind",
                "ticker",
                "risk_state",
                "advisory_action",
                "reason_codes",
                "marked_weight",
                "official_prior_weight",
                "signal_snapshot_sha256",
            )
        }
        row["proposed_entries"] = canonical_json(signal.get("proposed_entries", []))
        for horizon in horizons:
            outcome = outcomes.get((oid, horizon)) or {}
            prefix = f"outcome_{horizon}d"
            row[f"{prefix}_status"] = "completed" if outcome else evaluations.get(oid, {}).get(horizon, "pending")
            for name in (
                "outcome_date",
                "ticker_total_return",
                "benchmark_total_return",
                "spy_excess_total_return",
                "ticker_max_drawdown",
                "ticker_max_gain",
                "ticker_recovery_from_trough",
                "actionable_ticker_total_return",
                "actionable_spy_excess_total_return",
                "actionable_ticker_max_drawdown",
                "actionable_ticker_max_gain",
                "actionable_ticker_recovery_from_trough",
            ):
                row[f"{prefix}_{name}"] = outcome.get(name)
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["decision_date", "family", "portfolio_kind", "ticker"], kind="stable"
    ).reset_index(drop=True) if rows else pd.DataFrame()


def group_metrics(status: pd.DataFrame, horizon: int) -> dict[str, Any]:
    if status.empty:
        return {}
    prefix = f"outcome_{horizon}d"
    completed = status[status[f"{prefix}_status"].eq("completed")].copy()
    completed = completed.sort_values(["decision_date", "ticker", "family", "portfolio_kind"]).drop_duplicates(
        ["decision_date", "ticker"], keep="first"
    )
    completed = completed[completed["risk_state"].isin(["ALERT", "WATCH", "NORMAL"])].copy()
    completed["risk_bucket"] = np.where(completed["risk_state"].isin(["ALERT", "WATCH"]), "warning", "normal")
    result: dict[str, Any] = {}
    for bucket, group in completed.groupby("risk_bucket", sort=True):
        excess = pd.to_numeric(group[f"{prefix}_spy_excess_total_return"], errors="coerce").dropna()
        drawdown = pd.to_numeric(group[f"{prefix}_ticker_max_drawdown"], errors="coerce").dropna()
        actionable = pd.to_numeric(group[f"{prefix}_actionable_spy_excess_total_return"], errors="coerce").dropna()
        result[bucket] = {
            "count": int(len(group)),
            "distinct_tickers": int(group["ticker"].nunique()),
            "decision_week_blocks": int(group["iso_decision_week"].nunique()),
            "mean_spy_excess_total_return": float(excess.mean()) if len(excess) else None,
            "median_spy_excess_total_return": float(excess.median()) if len(excess) else None,
            "mean_ticker_max_drawdown": float(drawdown.mean()) if len(drawdown) else None,
            "mean_actionable_spy_excess_total_return": float(actionable.mean()) if len(actionable) else None,
        }
    if "warning" in result and "normal" in result:
        result["warning_minus_normal"] = {
            key: result["warning"][key] - result["normal"][key]
            for key in (
                "mean_spy_excess_total_return",
                "median_spy_excess_total_return",
                "mean_ticker_max_drawdown",
                "mean_actionable_spy_excess_total_return",
            )
            if result["warning"][key] is not None and result["normal"][key] is not None
        }
    return result


def write_price_universe(
    status: pd.DataFrame, output: Path, horizons: tuple[int, ...], benchmark: str
) -> pd.DataFrame:
    pending_rows = status.copy()
    if not status.empty:
        complete = pd.Series(True, index=status.index)
        for horizon in horizons:
            complete &= status[f"outcome_{horizon}d_status"].eq("completed")
        pending_rows = status[~complete].copy()
    rows: list[dict[str, Any]] = []
    if not status.empty:
        for ticker, group in status.groupby("ticker", sort=True):
            ticker_pending = pending_rows[
                pending_rows["ticker"].astype(str).eq(str(ticker))
            ]
            rows.append(
                {
                    "ticker": ticker,
                    "source": (
                        "unresolved_risk_observation"
                        if not ticker_pending.empty
                        else "completed_risk_observation_replay"
                    ),
                    "families": "|".join(sorted(set(group["family"].astype(str)))),
                    "rebalance_date": min(group["decision_date"].astype(str)),
                    "unresolved_observation_count": int(len(ticker_pending)),
                }
            )
    rows.append(
        {
            "ticker": benchmark,
            "source": "benchmark",
            "families": "benchmark",
            "rebalance_date": min(pending_rows["decision_date"].astype(str)) if not pending_rows.empty else "2026-07-13",
            "unresolved_observation_count": int(len(pending_rows)),
        }
    )
    frame = pd.DataFrame(rows).drop_duplicates("ticker", keep="last").sort_values("ticker").reset_index(drop=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    return frame


def render_report(summary: Mapping[str, Any]) -> str:
    one_day = (summary.get("group_metrics") or {}).get("1d") or {}
    one_day_warning = (one_day.get("warning") or {}).get("count", 0)
    one_day_normal = (one_day.get("normal") or {}).get("count", 0)
    lines = [
        "# Run287 risk outcome archive",
        "",
        f"- Status: `{summary['status']}`",
        f"- As-of close: `{summary['as_of_date']}`",
        f"- Signal observations: `{summary['signal_observation_count']}`",
        f"- Distinct weeks: `{summary['distinct_decision_week_count']}`",
        f"- Price-universe tickers: `{summary['price_universe_unique_ticker_count']}`",
        f"- 1D resolved warning/normal (diagnostic only): `{one_day_warning}` / `{one_day_normal}`",
        f"- 63D resolved warning/normal: `{summary['mechanism_review_gate']['warning_63d_count']}` / `{summary['mechanism_review_gate']['normal_63d_count']}`",
        f"- Mechanism review ready: `{str(summary['mechanism_review_ready']).lower()}`",
        "- 1D actionable metrics are not applicable and cannot open the mechanism review gate.",
        "- This archive does not create a stop, exit, resize, cash, order, target-book, fullrun, production, or live-trading rule.",
    ]
    blockers = summary.get("blockers") or []
    if blockers:
        lines.extend(["", "## Blockers", ""] + [f"- `{item}`" for item in blockers])
    return "\n".join(lines) + "\n"


def run_unlocked(args: argparse.Namespace, *, now_utc: str | None = None) -> dict[str, Any]:
    recorded_at = now_utc or utc_now()
    as_of = pd.Timestamp(args.as_of_date).normalize()
    archive = repo_path(args.decision_archive)
    price_cache = repo_path(args.price_cache)
    price_cache_manifest_path = (
        price_cache / "replay_price_cache_manifest.json"
    )
    output = repo_path(args.output_dir)
    contract_path = repo_path(args.contract)
    contract = read_json(contract_path)
    contract_sha256 = canonical_tracked_contract_sha256(
        contract_path,
        contract,
        CONTRACT_EXPECTED_SHA256,
    )
    output.mkdir(parents=True, exist_ok=True)
    event_log = output / EVENT_LOG_NAME
    chain_context, chain_failures = prepare_outcome_chain(
        parent_anchor=getattr(args, "parent_anchor", ""),
        expected_prior_invocation_summary_sha256=getattr(
            args,
            "expected_prior_invocation_summary_sha256",
            "",
        ),
        output=output,
        event_log=event_log,
    )
    manifest_path = archive / "manifest.json"
    candidate_path = archive / "candidate_risk_history.jsonl"
    position_path = archive / "position_history.jsonl"
    source_manifest = read_json(manifest_path)
    blockers: list[str] = list(chain_failures)
    if contract_sha256 != CONTRACT_EXPECTED_SHA256:
        blockers.append("risk_outcome_contract_not_canonical")
    source_status = clean_text(source_manifest.get("status"))
    source_absent = bool(
        not candidate_path.is_file()
        and not position_path.is_file()
        and source_status in {"", "SKIPPED_NO_EXACT_SELECTOR_RISK_PACKET"}
    )
    if not source_absent and source_status != "READY_DECISION_OBSERVATION_ARCHIVE_REVIEW_ONLY":
        blockers.append("source_decision_archive_not_ready")
    if not source_absent and candidate_path.is_file() != position_path.is_file():
        blockers.append("source_decision_archive_histories_incomplete")
    if not contract:
        blockers.append("risk_outcome_contract_missing_or_invalid")
    candidate_rows = read_jsonl(candidate_path)
    position_rows = read_jsonl(position_path)
    observations, observation_failures = build_observations(candidate_rows, position_rows)
    blockers.extend(observation_failures)
    future = [row["observation_id"] for row in observations if pd.Timestamp(row["decision_date"]).normalize() > as_of]
    if future:
        blockers.append(f"future_decision_observations:{len(future)}")
    existing = read_jsonl(event_log)
    signal_events, signal_failures = capture_signal_events(observations, existing, recorded_at)
    blockers.extend(signal_failures)
    if blockers:
        summary = {
            "schema_version": SCHEMA_VERSION,
            "status": BLOCKED_STATUS,
            "as_of_date": as_of.date().isoformat(),
            "blockers": sorted(set(blockers)),
            "signal_observation_count": len([event for event in existing if event.get("event_type") == "risk_signal_observed"]),
            "forward_outcome_event_count": len(
                [
                    event
                    for event in existing
                    if event.get("event_type")
                    == "forward_outcome_observed"
                ]
            ),
            "distinct_decision_week_count": 0,
            "price_universe_unique_ticker_count": 0,
            "mechanism_review_gate": {"warning_63d_count": 0, "normal_63d_count": 0},
            "mechanism_review_ready": False,
            "mechanism_promotion_allowed": False,
            "review_only": True,
            "threshold_tuning_allowed": False,
            "stop_or_exit_rule_created": False,
            "selector_weights_changed": False,
            "cash_policy_changed": False,
            "portfolio_transition_allowed": False,
            "orders_generated": False,
            "target_books_mutated": False,
            "historical_cagr_mdd_evidence_changed": False,
            "backtest_executed": False,
            "fullrun_executed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
            "outputs": {
                "event_log_sha256": (
                    sha256_file(event_log)
                    if event_log.is_file()
                    else EMPTY_SHA256
                ),
            },
            "outcome_chain": finalize_outcome_chain(
                chain_context,
                event_log,
                as_of_date=as_of.date().isoformat(),
            ),
        }
        write_json(output / "summary.json", summary)
        (output / "report.md").write_text(render_report(summary), encoding="utf-8")
        return summary
    if not observations and not existing:
        summary = {
            "schema_version": SCHEMA_VERSION,
            "status": SKIPPED_STATUS,
            "as_of_date": as_of.date().isoformat(),
            "blockers": [],
            "signal_observation_count": 0,
            "forward_outcome_event_count": 0,
            "distinct_decision_week_count": 0,
            "price_universe_unique_ticker_count": 1,
            "mechanism_review_gate": {"warning_63d_count": 0, "normal_63d_count": 0},
            "mechanism_review_ready": False,
            "mechanism_promotion_allowed": False,
            "review_only": True,
            "threshold_tuning_allowed": False,
            "stop_or_exit_rule_created": False,
            "selector_weights_changed": False,
            "cash_policy_changed": False,
            "portfolio_transition_allowed": False,
            "orders_generated": False,
            "target_books_mutated": False,
            "historical_cagr_mdd_evidence_changed": False,
            "backtest_executed": False,
            "fullrun_executed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
            "outputs": {"event_log_sha256": EMPTY_SHA256},
            "outcome_chain": finalize_outcome_chain(
                chain_context,
                event_log,
                as_of_date=as_of.date().isoformat(),
            ),
        }
        write_json(output / "summary.json", summary)
        (output / "report.md").write_text(render_report(summary), encoding="utf-8")
        return summary
    append_events(event_log, signal_events)
    verify_event_log_append(
        chain_context,
        event_log,
        expected_appended_event_count=len(signal_events),
    )
    events_after_signals = existing + signal_events
    required_price_tickers = sorted(
        {
            ticker
            for event in events_after_signals
            if event.get("event_type") == "risk_signal_observed"
            for ticker in (
                clean_text(event.get("ticker")),
                clean_text(event.get("benchmark_ticker")),
            )
            if ticker
        }
    )
    missing_price_cache_tickers = [
        ticker
        for ticker in required_price_tickers
        if not (price_cache / px_cache_name(ticker)).is_file()
    ]
    outcome_events, evaluations = evaluate(events_after_signals, price_cache, contract, as_of, recorded_at)
    append_events(event_log, outcome_events)
    verify_event_log_append(
        chain_context,
        event_log,
        expected_appended_event_count=(
            len(signal_events) + len(outcome_events)
        ),
    )
    all_events = events_after_signals + outcome_events
    horizons = tuple(int(value) for value in contract["outcome_contract"]["horizons_trading_days"])
    status = build_current_status(all_events, evaluations, horizons)
    status.to_csv(output / "current_status.csv", index=False)
    universe = write_price_universe(status, output / "price_universe.csv", horizons, clean_text(contract.get("benchmark")) or "SPY")
    max_tickers = int(contract["bounded_price_refresh"]["maximum_unique_tickers_including_benchmark"])
    if len(universe) > max_tickers:
        blockers.append(f"price_universe_cap_exceeded:{len(universe)}>{max_tickers}")
    primary = int(contract["mechanism_review_gate"]["primary_horizon_trading_days"])
    metric_frame = status.sort_values(["decision_date", "ticker", "family", "portfolio_kind"]).drop_duplicates(
        ["decision_date", "ticker"], keep="first"
    )
    completed = metric_frame[metric_frame[f"outcome_{primary}d_status"].eq("completed")].copy()
    warning = completed[completed["risk_state"].isin(contract["mechanism_review_gate"]["warning_states"])]
    normal = completed[completed["risk_state"].eq(contract["mechanism_review_gate"]["control_state"])]
    paired_weeks = len(set(warning["iso_decision_week"]) & set(normal["iso_decision_week"]))
    gate = {
        "warning_63d_count": int(len(warning)),
        "normal_63d_count": int(len(normal)),
        "distinct_63d_tickers": int(completed["ticker"].nunique()),
        "paired_63d_decision_week_blocks": int(paired_weeks),
        "minimum_distinct_decision_weeks": int(contract["mechanism_review_gate"]["minimum_distinct_decision_weeks"]),
        "minimum_warning_observations": int(contract["mechanism_review_gate"]["minimum_warning_observations"]),
        "minimum_normal_observations": int(contract["mechanism_review_gate"]["minimum_normal_observations"]),
        "minimum_distinct_tickers": int(contract["mechanism_review_gate"]["minimum_distinct_tickers"]),
        "minimum_paired_decision_week_blocks": int(contract["mechanism_review_gate"]["minimum_paired_decision_week_blocks"]),
    }
    weeks = int(status["iso_decision_week"].nunique()) if not status.empty else 0
    mechanism_ready = bool(
        weeks >= gate["minimum_distinct_decision_weeks"]
        and gate["warning_63d_count"] >= gate["minimum_warning_observations"]
        and gate["normal_63d_count"] >= gate["minimum_normal_observations"]
        and gate["distinct_63d_tickers"] >= gate["minimum_distinct_tickers"]
        and gate["paired_63d_decision_week_blocks"] >= gate["minimum_paired_decision_week_blocks"]
    )
    event_counts = Counter(clean_text(event.get("event_type")) for event in all_events)
    appended_counts = Counter(clean_text(event.get("event_type")) for event in signal_events + outcome_events)
    diagnostic_horizons = tuple(
        int(value)
        for value in contract["outcome_contract"].get(
            "diagnostic_group_metrics_horizons_trading_days", [21, 63]
        )
    )
    price_cache_manifest_sha256 = (
        sha256_file(price_cache_manifest_path)
        if price_cache_manifest_path.is_file()
        else ""
    )
    price_cache_bootstrap_required = bool(
        missing_price_cache_tickers
        or any(
            status_value
            in {
                "pending_ticker_adjusted_price_unavailable",
                "pending_benchmark_adjusted_price_unavailable",
            }
            for horizon_statuses in evaluations.values()
            for status_value in horizon_statuses.values()
        )
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            BLOCKED_STATUS
            if blockers
            else (
                READY_STATUS
                if price_cache_manifest_sha256
                and not price_cache_bootstrap_required
                else NEEDS_PRICE_CACHE_STATUS
            )
        ),
        "as_of_date": as_of.date().isoformat(),
        "generated_at_utc": recorded_at,
        "blockers": blockers,
        "signal_observation_count": int(event_counts.get("risk_signal_observed", 0)),
        "held_signal_observation_count": int(sum(event.get("event_type") == "risk_signal_observed" and event.get("family") == "held" for event in all_events)),
        "candidate_signal_observation_count": int(sum(event.get("event_type") == "risk_signal_observed" and event.get("family") == "candidate" for event in all_events)),
        "forward_outcome_event_count": int(event_counts.get("forward_outcome_observed", 0)),
        "appended_event_counts": dict(appended_counts),
        "distinct_decision_week_count": weeks,
        "price_universe_unique_ticker_count": int(len(universe)),
        "price_universe_cap": max_tickers,
        "price_cache_bootstrap_required": price_cache_bootstrap_required,
        "missing_price_cache_tickers": missing_price_cache_tickers,
        "horizon_status_counts": {
            f"{horizon}d": {str(key): int(value) for key, value in status[f"outcome_{horizon}d_status"].value_counts().to_dict().items()}
            for horizon in horizons
        },
        "group_metrics": {
            f"{horizon}d": group_metrics(status, horizon) for horizon in diagnostic_horizons
        },
        "mechanism_review_gate": gate,
        "mechanism_review_ready": mechanism_ready,
        "mechanism_promotion_allowed": False,
        "source_inputs": {
            "decision_archive_manifest_sha256": sha256_file(manifest_path),
            "candidate_risk_history_sha256": sha256_file(candidate_path),
            "position_history_sha256": sha256_file(position_path),
            "contract_sha256": contract_sha256,
            "price_cache_manifest_sha256": price_cache_manifest_sha256,
        },
        "outputs": {
            "event_log_sha256": sha256_file(event_log),
            "current_status_sha256": sha256_file(output / "current_status.csv"),
            "price_universe_sha256": sha256_file(output / "price_universe.csv"),
        },
        "review_only": True,
        "threshold_tuning_allowed": False,
        "stop_or_exit_rule_created": False,
        "selector_weights_changed": False,
        "cash_policy_changed": False,
        "portfolio_transition_allowed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "historical_cagr_mdd_evidence_changed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "outcome_chain": finalize_outcome_chain(
            chain_context,
            event_log,
            as_of_date=as_of.date().isoformat(),
        ),
        "recommended_next_step": "continue exact-close observations; do not review an execution mechanism before the frozen 12-week and resolved 63D sample gate",
    }
    write_json(output / "summary.json", summary)
    (output / "report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def run(args: argparse.Namespace, *, now_utc: str | None = None) -> dict[str, Any]:
    output = repo_path(args.output_dir)
    with exclusive_lock(output):
        return run_unlocked(args, now_utc=now_utc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-archive", default="outputs/run287_decision_observation_archive")
    parser.add_argument("--price-cache", default="outputs/run287_risk_outcome_price_cache")
    parser.add_argument("--output-dir", default="outputs/run287_risk_outcome_archive")
    parser.add_argument("--contract", default="docs/run287_risk_outcome_archive_contract.json")
    parser.add_argument(
        "--parent-anchor",
        default="",
        help=(
            "pre-mutation anchor.json from "
            "build_run287_risk_outcome_parent_anchor.py; omission is "
            "fail-closed and produces an UNANCHORED chain"
        ),
    )
    parser.add_argument(
        "--expected-prior-invocation-summary-sha256",
        default="",
        help=(
            "externally captured summary SHA-256 from the immediately prior "
            "resolver call when reusing one parent anchor in the same run"
        ),
    )
    parser.add_argument("--as-of-date", required=True)
    return parser.parse_args()


def main() -> int:
    summary = run(parse_args())
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 2 if summary["status"] == BLOCKED_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())

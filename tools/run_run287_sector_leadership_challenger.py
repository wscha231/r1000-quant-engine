#!/usr/bin/env python3
"""Build an accepted-current-snapshot-bound sector leadership challenger.

The challenger is deliberately unable to write target books, orders, accounts,
or operating ledgers.  It consumes already accepted, hash-bound current-close
evidence and publishes only the ten artifacts declared in
``docs/run287_sector_leadership_challenger_contract.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal


REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = REPO_ROOT / "docs" / "run287_sector_leadership_challenger_contract.json"

SCHEMA_VERSION = "run287-sector-leadership-challenger-v1"
SUMMARY_SCHEMA_VERSION = "run287-sector-leadership-summary-v1"
READY_STATUS = "READY_SECTOR_LEADERSHIP_RESEARCH_ONLY"
BLOCKED_STATUS = "BLOCKED_SECTOR_LEADERSHIP_CHALLENGER"
SKIPPED_NO_ACCEPTED_STATUS = "SKIPPED_NO_ACCEPTED_NORMAL_EVIDENCE"
SKIPPED_CATCHUP_STATUS = "SKIPPED_CATCH_UP_WITHOUT_PIT_EVIDENCE"
SKIPPED_CATCHUP_NO_PIT_STATUS = (
    "SKIPPED_CATCHUP_NO_PIT_SCORE_SNAPSHOT"
)

ACCEPTED_SCHEMA = "run287-accepted-publication-manifest-v1"
ACCEPTED_READY = "READY_ACCEPTED_PUBLICATION_REVIEW_ONLY"
SCORED_SCHEMA = "run287-scored-latest-refresh-v4"
SCORED_READY = "READY_RESEARCH_SCORED_LATEST"
BENCHMARK_SCHEMA = "run287-replay-price-cache-manifest-v2"
BENCHMARK_READY = {"completed", "already_cached"}

EXPECTED_OUTPUTS = (
    "source_manifest.json",
    "feature_manifest.json",
    "experiment_ledger.json",
    "sector_leadership.csv",
    "subsector_leadership.csv",
    "leadership_transitions.csv",
    "candidate_ranking.csv",
    "operation_health.json",
    "summary.json",
    "report.md",
)

SAFETY_FLAGS: dict[str, Any] = {
    "research_only": True,
    "review_only": True,
    "production_activation_allowed": False,
    "target_books_mutated": False,
    "orders_generated": False,
    "automatic_promotion_allowed": False,
    "automatic_champion_replacement_allowed": False,
    "production_mutation_allowed": False,
    "portfolio_weights_written": False,
    "weights_mutated": False,
    "cash_allocator_written": False,
    "accounts_written": False,
    "account_state_mutated": False,
    "operating_ledgers_written": False,
    "operating_ledger_mutated": False,
    "backtest_executed": False,
    "fullrun_executed": False,
    "live_trading_enabled": False,
    "taxonomy_snapshot_scope": "accepted_current_decision_snapshot_bound",
    "taxonomy_bitemporal_vintage_complete": False,
    "historical_taxonomy_backfill_allowed": False,
    "leadership_scope": "eligible_candidate_leadership",
    "breadth_scope": "eligible_candidate_breadth",
    "full_universe_market_breadth_claimed": False,
    "full_universe_canonical_taxonomy_complete": False,
}

CANONICAL_SECTORS = (
    "Communication Services",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Financials",
    "Health Care",
    "Industrials",
    "Information Technology",
    "Materials",
    "Real Estate",
    "Utilities",
)

SECTOR_ALIASES = {
    "communication services": "Communication Services",
    "communication": "Communication Services",
    "communications": "Communication Services",
    "internet": "Communication Services",
    "consumer cyclical": "Consumer Discretionary",
    "consumer discretionary": "Consumer Discretionary",
    "auto": "Consumer Discretionary",
    "consumer defensive": "Consumer Staples",
    "consumer staples": "Consumer Staples",
    "energy": "Energy",
    "financial services": "Financials",
    "financial": "Financials",
    "financials": "Financials",
    "health care": "Health Care",
    "healthcare": "Health Care",
    "pharma": "Health Care",
    "industrials": "Industrials",
    "technology": "Information Technology",
    "information technology": "Information Technology",
    "semiconductors": "Information Technology",
    "software": "Information Technology",
    "basic materials": "Materials",
    "materials": "Materials",
    "real estate": "Real Estate",
    "utilities": "Utilities",
}

BENCHMARKS = ("SPY", "QQQ", "SMH")
HORIZONS: tuple[tuple[str, int], ...] = (
    ("1d", 1),
    ("5d", 5),
    ("1m", 21),
    ("3m", 63),
    ("6m", 126),
    ("12m", 252),
)
SHORT_HORIZONS = {"1d", "5d"}
LONG_MOMENTUM_COLUMNS = {
    "1m": ("mom_1m", "momentum_1m", "ret_1m", "return_1m"),
    "3m": ("mom_3m", "momentum_3m", "ret_3m", "return_3m"),
    "6m": ("mom_6m", "momentum_6m", "ret_6m", "return_6m"),
    "12m": ("mom_12m", "momentum_12m", "ret_12m", "return_12m"),
}
BASE_SCORE_COLUMNS = (
    "score",
    "score_total",
    "alphaops_vnext_score",
    "model_score",
)

STATE_VALUES = {
    "EMERGING_WATCH",
    "EMERGING_CONFIRMED",
    "LEADING",
    "WEAKENING",
    "BREAKDOWN",
    "REENTRY",
}
RAW_SIGNAL_VALUES = {"BREAKDOWN", "WEAKENING", "LEADING", "EMERGING"}
PENDING_CONFIRMATION_VALUES = {"", "EMERGING", "REENTRY"}
ENTITY_TYPES = ("sector", "industry_group", "subindustry", "stock")

THRESHOLDS = {
    "breakdown_alpha_max": -0.75,
    "breakdown_breadth_5d_max": 0.20,
    "weakening_alpha_max": -0.20,
    "weakening_breadth_5d_max": 0.40,
    "leading_alpha_min": 0.65,
    "leading_breadth_5d_min": 0.60,
    "leading_breadth_composite_min": 0.55,
    "emerging_alpha_min": 0.00,
    "emerging_breadth_5d_min": 0.50,
    "emerging_breadth_composite_min": 0.50,
    "confirmation_distinct_sessions": 2,
}

CANDIDATE_COLUMNS = (
    "rank",
    "ticker",
    "sector",
    "industry_group",
    "subindustry",
    "taxonomy_resolution",
    "close",
    "return_1d",
    "return_5d",
    "return_1m",
    "return_3m",
    "return_6m",
    "return_12m",
    *(f"rs_{benchmark.lower()}_{horizon}" for benchmark in BENCHMARKS for horizon, _ in HORIZONS),
    "rs_composite_score",
    "rs_acceleration_score",
    "volume_ratio",
    "volume_signal_score",
    "base_score",
    "alpha_score",
    "confidence_score",
    "raw_signal",
    "leadership_state",
    "pending_confirmation",
    "pending_streak",
    "idiosyncratic_decline",
    "exact_close",
    "feature_complete",
)

GROUP_COLUMNS = (
    "rank",
    "entity_key",
    "sector",
    "member_count",
    "alpha_score",
    "confidence_score",
    "breadth_1d",
    "breadth_5d",
    "breadth_1m",
    "breadth_composite",
    "rs_acceleration_score",
    "volume_confirmation",
    "top_member",
    "top_member_alpha_score",
    "raw_signal",
    "leadership_state",
    "pending_confirmation",
    "pending_streak",
)

SUBSECTOR_COLUMNS = (
    "hierarchy_level",
    "rank",
    "entity_key",
    "sector",
    "industry_group",
    "subindustry",
    "member_count",
    "alpha_score",
    "confidence_score",
    "breadth_1d",
    "breadth_5d",
    "breadth_1m",
    "breadth_composite",
    "rs_acceleration_score",
    "volume_confirmation",
    "top_member",
    "top_member_alpha_score",
    "raw_signal",
    "leadership_state",
    "pending_confirmation",
    "pending_streak",
)

TRANSITION_COLUMNS = (
    "session_date",
    "entity_type",
    "entity_key",
    "previous_state",
    "raw_signal",
    "current_state",
    "state_changed",
    "pending_confirmation",
    "pending_streak",
    "confirmation_distinct_sessions_required",
    "immediate_negative_transition",
    "same_date_idempotent",
)

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class ChallengerError(ValueError):
    """A fail-closed contract or evidence error."""


@dataclass(frozen=True)
class SourceIdentity:
    run_id: str
    run_attempt: str
    commit_sha: str
    session_date: str
    workflow: str

    def as_dict(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "commit_sha": self.commit_sha,
            "session_date": self.session_date,
            "workflow": self.workflow,
        }


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def declared_output_path(value: str | Path) -> Path:
    """Return an absolute output path without dereferencing its final symlink."""

    path = Path(value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return Path(os.path.abspath(str(path)))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_sha256(value: Any) -> bool:
    return bool(SHA256_PATTERN.fullmatch(str(value or "")))


def valid_commit(value: Any) -> bool:
    return bool(COMMIT_PATTERN.fullmatch(str(value or "").lower()))


def strict_json_object(path: Path) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ChallengerError(f"duplicate_json_key:{path.name}:{key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=no_duplicates,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChallengerError(f"invalid_json:{path}") from exc
    if not isinstance(value, dict):
        raise ChallengerError(f"json_object_required:{path}")
    return value


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            default=str,
        )
        + "\n"
    ).encode("utf-8")


def canonical_csv_bytes(frame: pd.DataFrame, columns: Sequence[str]) -> bytes:
    output = frame.copy()
    for column in columns:
        if column not in output.columns:
            output[column] = pd.Series(dtype="object")
    output = output.loc[:, list(columns)]
    text = output.to_csv(
        index=False,
        lineterminator="\n",
        float_format="%.10g",
    )
    return text.encode("utf-8")


def publish_bundle_atomic(
    output_dir: Path,
    blobs: Mapping[str, bytes],
) -> None:
    """Publish a whole new bundle through one sibling-directory rename.

    A non-identical existing bundle is never updated in place.  This prevents
    readers from observing a mixture of old and new files.  Identical existing
    bundles are accepted as idempotent reruns.  Retry cleanup is restricted to
    validated, non-symlink sibling stage directories created by this producer.
    """

    bundle_id = sha256_bytes(
        canonical_json_bytes(
            {
                name: sha256_bytes(payload)
                for name, payload in sorted(blobs.items())
            }
        )
    )[:16]
    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    if parent.is_symlink():
        raise ChallengerError("output_parent_symlink_forbidden")
    stage_prefix = f".{output_dir.name}.run287-sector-stage-"
    stage_name_pattern = re.compile(
        re.escape(stage_prefix) + r"[0-9a-f]{16}$"
    )

    def validate_bundle_directory(
        path: Path,
        *,
        allow_partial: bool,
    ) -> set[str]:
        if path.is_symlink() or not path.is_dir():
            raise ChallengerError(f"bundle_directory_invalid:{path.name}")
        entries = list(path.iterdir())
        names: set[str] = set()
        for entry in entries:
            if entry.is_symlink() or not entry.is_file():
                raise ChallengerError(
                    f"bundle_entry_not_regular_file:{path.name}:{entry.name}"
                )
            if entry.name not in EXPECTED_OUTPUTS:
                raise ChallengerError(
                    f"bundle_undeclared_entry:{path.name}:{entry.name}"
                )
            if entry.name in names:
                raise ChallengerError(
                    f"bundle_duplicate_entry:{path.name}:{entry.name}"
                )
            names.add(entry.name)
        if not allow_partial and names != set(EXPECTED_OUTPUTS):
            raise ChallengerError(f"bundle_file_contract_invalid:{path.name}")
        return names

    def remove_valid_orphan_stage(path: Path) -> None:
        validate_bundle_directory(path, allow_partial=True)
        resolved = path.resolve()
        if resolved.parent != parent.resolve():
            raise ChallengerError("orphan_stage_outside_output_parent")
        for entry in list(path.iterdir()):
            entry.unlink()
        path.rmdir()

    # Only producer-shaped sibling directories are candidates for cleanup.
    for candidate in sorted(parent.iterdir(), key=lambda path: path.name):
        if candidate.name.startswith(stage_prefix):
            if stage_name_pattern.fullmatch(candidate.name) is None:
                raise ChallengerError(
                    f"malformed_orphan_stage_name:{candidate.name}"
                )
            remove_valid_orphan_stage(candidate)

    if output_dir.exists():
        if output_dir.is_symlink() or not output_dir.is_dir():
            raise ChallengerError("output_bundle_path_invalid")
        validate_bundle_directory(output_dir, allow_partial=False)
        identical = all(
            sha256_file(output_dir / name) == sha256_bytes(blobs[name])
            for name in EXPECTED_OUTPUTS
        )
        if identical:
            return
        raise ChallengerError("output_bundle_exists_with_different_content")

    stage_dir = parent / f"{stage_prefix}{bundle_id}"
    if stage_dir.exists():
        remove_valid_orphan_stage(stage_dir)
    stage_dir.mkdir()
    try:
        for name in EXPECTED_OUTPUTS:
            payload = blobs[name]
            stage_file = stage_dir / name
            with stage_file.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if sha256_file(stage_file) != sha256_bytes(payload):
                raise ChallengerError(f"staged_output_hash_mismatch:{name}")
        validate_bundle_directory(stage_dir, allow_partial=False)
        for name in EXPECTED_OUTPUTS:
            if sha256_file(stage_dir / name) != sha256_bytes(blobs[name]):
                raise ChallengerError(f"staged_bundle_hash_mismatch:{name}")
        # output_dir is absent, so this one directory rename is the publication.
        os.replace(stage_dir, output_dir)
    except BaseException:
        if stage_dir.exists():
            remove_valid_orphan_stage(stage_dir)
        raise


def parse_iso_date(value: Any, label: str) -> str:
    text = str(value or "")
    try:
        parsed = pd.Timestamp(text)
    except Exception as exc:
        raise ChallengerError(f"invalid_date:{label}") from exc
    if (
        len(text) != 10
        or parsed.tzinfo is not None
        or parsed.date().isoformat() != text
    ):
        raise ChallengerError(f"invalid_date:{label}")
    return text


def previous_nyse_session(session_date: str) -> str:
    session = pd.Timestamp(session_date).normalize()
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=session - pd.Timedelta(days=14),
        end_date=session,
    )
    sessions = pd.DatetimeIndex(schedule.index).tz_localize(None).normalize()
    previous = sessions[sessions < session]
    if previous.empty:
        raise ChallengerError("previous_nyse_session_unavailable")
    return pd.Timestamp(previous[-1]).date().isoformat()


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, np.integer)) and value in (0, 1):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "pass"}


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return " ".join(str(value).strip().split())


def normalize_ticker(value: Any) -> str:
    return clean_text(value).upper().replace(".", "-")


def canonical_sector(value: Any) -> str:
    text = clean_text(value)
    return SECTOR_ALIASES.get(text.casefold(), "")


def finite_number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def safe_float(value: Any, default: float = 0.0) -> float:
    result = finite_number(value)
    return default if result is None else result


def input_fingerprint(
    path: Path,
    *,
    expected_sha256: str,
    label: str,
) -> dict[str, Any]:
    expected = str(expected_sha256 or "").lower()
    if not valid_sha256(expected):
        raise ChallengerError(f"invalid_expected_sha256:{label}")
    exists = path.is_file()
    actual = sha256_file(path) if exists else ""
    record = {
        "label": label,
        "path": str(path),
        "exists": exists,
        "bytes": int(path.stat().st_size) if exists else 0,
        "sha256": actual,
        "expected_sha256": expected,
        "hash_matches": exists and actual == expected,
    }
    if not record["hash_matches"]:
        raise ChallengerError(f"input_hash_mismatch:{label}")
    return record


def resolve_manifest_output(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    *,
    key: str,
    explicit_path: Path,
    expected_sha256: str,
) -> dict[str, Any]:
    outputs = manifest.get("outputs")
    record = outputs.get(key) if isinstance(outputs, dict) else None
    if not isinstance(record, dict):
        raise ChallengerError(f"manifest_output_missing:{key}")
    raw_path = str(record.get("path") or "")
    if not raw_path:
        raise ChallengerError(f"manifest_output_path_missing:{key}")
    declared_path = Path(raw_path)
    if not declared_path.is_absolute():
        declared_path = (manifest_path.parent / declared_path).resolve()
    else:
        declared_path = declared_path.resolve()
    explicit_resolved = explicit_path.resolve()

    def outputs_suffix(path: Path) -> tuple[str, ...] | None:
        parts = path.parts
        anchors = [
            index
            for index, part in enumerate(parts)
            if str(part).casefold() == "outputs"
        ]
        if not anchors:
            return None
        suffix = tuple(str(part).casefold() for part in parts[anchors[-1] :])
        return suffix if len(suffix) >= 2 else None

    declared_suffix = outputs_suffix(declared_path)
    explicit_suffix = outputs_suffix(explicit_resolved)
    portable_relocation = bool(
        declared_suffix is not None
        and explicit_suffix is not None
        and declared_suffix == explicit_suffix
    )
    if declared_path != explicit_resolved and not portable_relocation:
        raise ChallengerError(f"manifest_output_path_mismatch:{key}")
    declared_hash = str(record.get("sha256") or "").lower()
    if declared_hash != str(expected_sha256).lower():
        raise ChallengerError(f"manifest_output_sha256_mismatch:{key}")
    if record.get("bytes") is not None:
        declared_bytes = record.get("bytes")
        if (
            isinstance(declared_bytes, bool)
            or not isinstance(declared_bytes, int)
            or declared_bytes != explicit_path.stat().st_size
        ):
            raise ChallengerError(f"manifest_output_bytes_mismatch:{key}")
    return {
        "manifest_key": key,
        "manifest_path": str(manifest_path),
        "path": str(explicit_path),
        "declared_path": str(declared_path),
        "portable_outputs_relocation_verified": portable_relocation,
        "bytes": explicit_path.stat().st_size,
        "sha256": declared_hash,
        "hash_matches": True,
    }


def ensure_safety(
    payload: Mapping[str, Any],
    *,
    label: str,
    required_true: Iterable[str] = (),
    required_false: Iterable[str] = (),
) -> None:
    for field in required_true:
        if payload.get(field) is not True:
            raise ChallengerError(f"unsafe_or_missing_flag:{label}:{field}")
    for field in required_false:
        if payload.get(field) is not False:
            raise ChallengerError(f"unsafe_or_missing_flag:{label}:{field}")


def input_set_sha256(
    audits: Mapping[str, Mapping[str, Any]],
    identity: SourceIdentity,
) -> str:
    primary = {
        label: {
            "bytes": int(record.get("bytes") or 0),
            "sha256": str(record.get("sha256") or ""),
        }
        for label, record in sorted(audits.items())
        if label != "prior_challenger_artifact"
    }
    return sha256_bytes(
        canonical_json_bytes(
            {
                "source_identity": identity.as_dict(),
                "primary_inputs": primary,
            }
        )
    )


def reverify_inputs(audits: Mapping[str, Mapping[str, Any]]) -> None:
    for label, record in audits.items():
        path = Path(str(record.get("path") or ""))
        if (
            not path.is_file()
            or path.stat().st_size != int(record.get("bytes") or -1)
            or sha256_file(path) != record.get("sha256")
        ):
            raise ChallengerError(f"input_changed_before_publish:{label}")


def safe_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {**payload, **SAFETY_FLAGS}


def empty_frames() -> dict[str, pd.DataFrame]:
    return {
        "sector_leadership.csv": pd.DataFrame(columns=GROUP_COLUMNS),
        "subsector_leadership.csv": pd.DataFrame(columns=SUBSECTOR_COLUMNS),
        "leadership_transitions.csv": pd.DataFrame(columns=TRANSITION_COLUMNS),
        "candidate_ranking.csv": pd.DataFrame(columns=CANDIDATE_COLUMNS),
    }


def report_text(
    *,
    status: str,
    session_date: str,
    blockers: Sequence[str],
    summary: Mapping[str, Any],
) -> str:
    lines = [
        "# Run287 Sector Leadership Challenger",
        "",
        f"- status: `{status}`",
        f"- source_session_date: `{session_date}`",
        "- research_only: `true`",
        "- production_activation_allowed: `false`",
        "- target_books_mutated: `false`",
        "- orders_generated: `false`",
        "- automatic_promotion_allowed: `false`",
        "",
        "This artifact is a research challenger. It cannot change portfolio "
        "weights, cash, orders, accounts, or the operating ledger.",
    ]
    if blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{reason}`" for reason in sorted(set(blockers)))
    else:
        lines.extend(
            [
                "",
                "## Result",
                "",
                f"- stock rows: `{summary.get('stock_count', 0)}`",
                f"- canonical sectors: `{summary.get('sector_count', 0)}`",
                f"- transitions: `{summary.get('transition_count', 0)}`",
                f"- top sector: `{summary.get('top_sector', '')}`",
                "",
                "Emerging and re-entry states require evidence on two distinct "
                "sessions. Weakening and breakdown states are immediate.",
            ]
        )
    return "\n".join(lines) + "\n"


def emit_artifacts(
    output_dir: Path,
    *,
    status: str,
    identity: SourceIdentity,
    audits: Mapping[str, Mapping[str, Any]],
    blockers: Sequence[str],
    frames: Mapping[str, pd.DataFrame] | None = None,
    coverage: Mapping[str, Any] | None = None,
    state_memory: Sequence[Mapping[str, Any]] = (),
    input_set_hash: str = "",
    prior: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    tables = dict(frames or empty_frames())
    csv_columns = {
        "sector_leadership.csv": GROUP_COLUMNS,
        "subsector_leadership.csv": SUBSECTOR_COLUMNS,
        "leadership_transitions.csv": TRANSITION_COLUMNS,
        "candidate_ranking.csv": CANDIDATE_COLUMNS,
    }
    blobs: dict[str, bytes] = {
        name: canonical_csv_bytes(tables.get(name, pd.DataFrame()), columns)
        for name, columns in csv_columns.items()
    }
    candidate = tables.get("candidate_ranking.csv", pd.DataFrame())
    sectors = tables.get("sector_leadership.csv", pd.DataFrame())
    transitions = tables.get("leadership_transitions.csv", pd.DataFrame())
    summary_core = {
        "stock_count": int(len(candidate)),
        "sector_count": int(len(sectors)),
        "transition_count": int(len(transitions)),
        "top_sector": (
            str(sectors.iloc[0].get("sector") or "") if not sectors.empty else ""
        ),
    }
    report = report_text(
        status=status,
        session_date=identity.session_date,
        blockers=blockers,
        summary=summary_core,
    ).encode("utf-8")
    blobs["report.md"] = report

    builder_path = Path(__file__).resolve()
    contract_record = {
        "path": str(CONTRACT_PATH),
        "exists": CONTRACT_PATH.is_file(),
        "bytes": CONTRACT_PATH.stat().st_size if CONTRACT_PATH.is_file() else 0,
        "sha256": sha256_file(CONTRACT_PATH) if CONTRACT_PATH.is_file() else "",
    }
    source_manifest = safe_payload(
        {
            "schema_version": f"{SCHEMA_VERSION}-source-manifest",
            "status": status,
            "source_identity": identity.as_dict(),
            "input_set_sha256": input_set_hash,
            "source_inputs": {
                key: dict(value) for key, value in sorted(audits.items())
            },
            "prior_artifact": dict(prior or {}),
            "contract": contract_record,
            "code": {
                "path": str(builder_path),
                "sha256": sha256_file(builder_path),
                "bytes": builder_path.stat().st_size,
            },
            "contract_failures": sorted(set(blockers)),
            "output_scope": str(output_dir),
            "fullrun_executed": False,
            "backtest_executed": False,
            "account_state_mutated": False,
            "operating_ledger_mutated": False,
        }
    )
    blobs["source_manifest.json"] = canonical_json_bytes(source_manifest)

    csv_hashes = {
        name: {"bytes": len(blobs[name]), "sha256": sha256_bytes(blobs[name])}
        for name in csv_columns
    }
    feature_manifest = safe_payload(
        {
            "schema_version": f"{SCHEMA_VERSION}-feature-manifest",
            "status": status,
            "source_session_date": identity.session_date,
            "input_set_sha256": input_set_hash,
            "hierarchy": [
                "sector",
                "industry_group",
                "subindustry",
                "stock",
            ],
            "canonical_sectors": list(CANONICAL_SECTORS),
            "benchmarks": list(BENCHMARKS),
            "horizons": [name for name, _ in HORIZONS],
            "feature_contract": {
                "short_horizon_stock_source": "hash_bound_provider_price_overlap",
                "long_horizon_stock_source": "hash_bound_scored_latest_momentum",
                "benchmark_source": "hash_bound_exact_close_cache",
                "relative_strength": "stock_return_minus_benchmark_return",
                "confidence_is_separate_from_alpha": True,
                "semiconductor_special_weighting": False,
                "taxonomy_snapshot_scope": (
                    "accepted_current_decision_snapshot_bound"
                ),
                "taxonomy_bitemporal_vintage_complete": False,
                "historical_taxonomy_backfill_allowed": False,
            },
            "thresholds": dict(THRESHOLDS),
            "coverage": dict(coverage or {}),
            "table_outputs": csv_hashes,
            "contract_failures": sorted(set(blockers)),
            "fullrun_executed": False,
            "backtest_executed": False,
        }
    )
    blobs["feature_manifest.json"] = canonical_json_bytes(feature_manifest)

    experiment_ledger = safe_payload(
        {
            "schema_version": f"{SCHEMA_VERSION}-experiment-ledger",
            "status": status,
            "experiment_id": "run287_sector_leadership_challenger_v1",
            "causal_challenger_count": 1,
            "hypothesis": (
                "equal-treatment sector and industry breadth plus benchmark-relative "
                "strength can identify leadership rotation earlier without mutating "
                "the champion"
            ),
            "parameter_set": dict(THRESHOLDS),
            "parameter_set_sha256": sha256_bytes(
                canonical_json_bytes(THRESHOLDS)
            ),
            "do_not_repeat_key": (
                "sector_subsector_rs_breadth_volume_acceleration_v1"
            ),
            "source_session_date": identity.session_date,
            "input_set_sha256": input_set_hash,
            "result_artifact_hashes": csv_hashes,
            "contract_failures": sorted(set(blockers)),
            "ledger_scope": "research_experiment_record_only",
            "operating_ledger_mutated": False,
            "champion_changed": False,
            "backtest_executed": False,
            "fullrun_executed": False,
        }
    )
    blobs["experiment_ledger.json"] = canonical_json_bytes(experiment_ledger)

    def audit_labels_bound(labels: Sequence[str]) -> bool:
        return all(
            label in audits
            and audits[label].get("hash_matches") is True
            and bool(audits[label].get("sha256"))
            for label in labels
        )

    source_identity_valid = bool(
        identity.run_id
        and identity.run_attempt
        and identity.workflow
        and valid_commit(identity.commit_sha)
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", identity.session_date)
    )
    scored_audit_labels = (
        "scored_latest_manifest",
        "scored_latest_csv",
        "provider_price_overlap",
        "ticker_refresh_audit",
        "scored_manifest_output_csv",
        "scored_manifest_output_provider",
        "scored_manifest_output_ticker_audit",
    )
    benchmark_audit_labels = (
        "benchmark_cache_manifest",
        "benchmark_spy",
        "benchmark_qqq",
        "benchmark_smh",
    )
    exact_final = (
        safe_float((coverage or {}).get("exact_stock_close_ratio"))
        == 1.0
    )
    exact_full = (
        safe_float(
            (coverage or {}).get("full_source_exact_close_ratio")
        )
        == 1.0
    )
    exact_eligible = (
        safe_float((coverage or {}).get("eligible_exact_close_ratio"))
        == 1.0
    )
    exact_benchmarks = (
        (coverage or {}).get("exact_benchmarks") == list(BENCHMARKS)
    )
    gates = {
        "accepted_publication_bound": (
            status == READY_STATUS
            and audit_labels_bound(("accepted_publication_manifest",))
        ),
        "source_identity_bound": (
            status == READY_STATUS and source_identity_valid
        ),
        "scored_outputs_hash_bound": (
            status == READY_STATUS
            and audit_labels_bound(scored_audit_labels)
        ),
        "benchmark_cache_hash_bound": (
            status == READY_STATUS
            and audit_labels_bound(benchmark_audit_labels)
        ),
        "exact_stock_close_coverage_100pct": (
            status == READY_STATUS and exact_final
        ),
        "full_source_exact_close_coverage_100pct": (
            status == READY_STATUS and exact_full
        ),
        "eligible_exact_close_coverage_100pct": (
            status == READY_STATUS and exact_eligible
        ),
        "taxonomy_coverage_at_least_98pct": (
            status == READY_STATUS
            and safe_float((coverage or {}).get("taxonomy_coverage_ratio")) >= 0.98
        ),
        "all_11_canonical_sectors_represented": (
            status == READY_STATUS
            and int((coverage or {}).get("canonical_sector_count") or 0) == 11
        ),
        "exact_spy_qqq_smh": (
            status == READY_STATUS and exact_benchmarks
        ),
        "no_future_rows": (
            status == READY_STATUS
            and exact_final
            and exact_full
            and exact_eligible
            and exact_benchmarks
            and (coverage or {}).get(
                "ticker_audit_session_date_exact"
            )
            is True
        ),
    }
    gates["safe_to_review"] = bool(
        status == READY_STATUS
        and not blockers
        and all(gates.values())
    )
    health_status = (
        "READY"
        if status == READY_STATUS
        else ("SKIPPED" if status.startswith("SKIPPED_") else "BLOCKED")
    )
    operation_health = safe_payload(
        {
            "schema_version": f"{SCHEMA_VERSION}-operation-health",
            "status": health_status,
            "challenger_status": status,
            "source_session_date": identity.session_date,
            "input_set_sha256": input_set_hash,
            "gates": gates,
            "coverage": dict(coverage or {}),
            "contract_failures": sorted(set(blockers)),
            "mutation_surface": {
                "output_dir_only": True,
                "target_books": False,
                "weights": False,
                "orders": False,
                "accounts": False,
                "operating_ledgers": False,
            },
            "fullrun_executed": False,
            "backtest_executed": False,
        }
    )
    blobs["operation_health.json"] = canonical_json_bytes(operation_health)

    artifact_hashes_before_summary = {
        name: {"bytes": len(value), "sha256": sha256_bytes(value)}
        for name, value in sorted(blobs.items())
    }
    summary = safe_payload(
        {
            "schema_version": SUMMARY_SCHEMA_VERSION,
            "status": status,
            "source_identity": identity.as_dict(),
            "input_set_sha256": input_set_hash,
            **summary_core,
            "coverage": dict(coverage or {}),
            "state_memory": [dict(row) for row in state_memory],
            "artifact_hashes": artifact_hashes_before_summary,
            "contract_failures": sorted(set(blockers)),
            "review_required": True,
            "champion_changed": False,
            "portfolio_transition_allowed": False,
            "backtest_executed": False,
            "fullrun_executed": False,
        }
    )
    blobs["summary.json"] = canonical_json_bytes(summary)

    for name in EXPECTED_OUTPUTS:
        if blobs.get(name) is None:
            raise ChallengerError(f"internal_missing_output:{name}")
    publish_bundle_atomic(output_dir, blobs)
    actual = sorted(path.name for path in output_dir.iterdir())
    if actual != sorted(EXPECTED_OUTPUTS):
        raise ChallengerError("output_contract_mismatch_after_publish")
    return summary


def normalize_price_frame(
    frame: pd.DataFrame,
    *,
    session_date: str,
    label: str,
) -> pd.DataFrame:
    output = frame.copy()
    if output.empty:
        raise ChallengerError(f"empty_price_frame:{label}")
    if not isinstance(output.index, pd.DatetimeIndex):
        date_column = next(
            (
                column
                for column in ("Date", "date", "Datetime", "datetime")
                if column in output.columns
            ),
            None,
        )
        if date_column is None:
            raise ChallengerError(f"price_date_missing:{label}")
        output = output.set_index(date_column)
    index = pd.to_datetime(output.index, errors="coerce", utc=True)
    if index.isna().any():
        raise ChallengerError(f"invalid_price_date:{label}")
    output.index = index.tz_convert(None).normalize()
    if output.index.duplicated().any():
        raise ChallengerError(f"duplicate_price_date:{label}")
    output = output.sort_index()
    session = pd.Timestamp(session_date)
    if bool((output.index > session).any()):
        raise ChallengerError(f"future_price_row:{label}")
    close_column = next(
        (
            column
            for column in ("Adj Close", "Close", "adj_close", "close")
            if column in output.columns
        ),
        None,
    )
    if close_column is None:
        raise ChallengerError(f"price_close_missing:{label}")
    close = pd.to_numeric(output[close_column], errors="coerce")
    if close.isna().any() or bool((close <= 0).any()):
        raise ChallengerError(f"invalid_price_close:{label}")
    normalized = pd.DataFrame({"close": close.astype(float)}, index=output.index)
    volume_column = next(
        (column for column in ("Volume", "volume") if column in output.columns),
        None,
    )
    if volume_column is not None:
        normalized["volume"] = pd.to_numeric(
            output[volume_column], errors="coerce"
        )
    if session not in normalized.index:
        raise ChallengerError(f"missing_exact_session_close:{label}")
    return normalized


def provider_price_map(
    path: Path,
    *,
    session_date: str,
    required_tickers: set[str],
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        raise ChallengerError("provider_price_overlap_unreadable") from exc
    if "ticker" not in frame.columns:
        raise ChallengerError("provider_ticker_column_missing")
    frame = frame.copy()
    frame["ticker"] = frame["ticker"].map(normalize_ticker)
    if bool(frame["ticker"].eq("").any()):
        raise ChallengerError("provider_empty_ticker")
    observed_tickers = set(frame["ticker"])
    missing = sorted(required_tickers - observed_tickers)
    extras = sorted(observed_tickers - required_tickers)
    if missing or extras:
        raise ChallengerError(
            "provider_full_scored_universe_mismatch:"
            f"missing={','.join(missing)}:extra={','.join(extras)}"
        )
    result: dict[str, pd.DataFrame] = {}
    for ticker, group in frame.groupby("ticker", sort=True):
        result[str(ticker)] = normalize_price_frame(
            group.drop(columns=["ticker"]),
            session_date=session_date,
            label=f"provider:{ticker}",
        )
    return result, {
        "provider_full_scored_observed_count": int(
            len(observed_tickers)
        ),
        "provider_full_scored_exact_close_count": int(len(result)),
        "provider_full_scored_exact_close_ratio": (
            float(len(result) / len(required_tickers))
            if required_tickers
            else 0.0
        ),
        "provider_full_scored_ticker_set_sha256": ticker_set_sha256(
            observed_tickers
        ),
    }


def price_return(frame: pd.DataFrame, trading_days: int) -> float | None:
    if len(frame) < trading_days + 1:
        return None
    end = float(frame["close"].iloc[-1])
    start = float(frame["close"].iloc[-(trading_days + 1)])
    if start <= 0:
        return None
    result = end / start - 1.0
    return result if math.isfinite(result) else None


def volume_ratio(frame: pd.DataFrame) -> float | None:
    if "volume" not in frame or len(frame) < 2:
        return None
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    latest = finite_number(volume.iloc[-1])
    prior = volume.iloc[max(0, len(volume) - 21) : -1].dropna()
    if latest is None or latest < 0 or prior.empty:
        return None
    baseline = float(prior.mean())
    if not math.isfinite(baseline) or baseline <= 0:
        return None
    return latest / baseline


def first_column(frame: pd.DataFrame, candidates: Sequence[str]) -> str | None:
    return next((column for column in candidates if column in frame.columns), None)


def robust_zscore(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    median = float(values.median()) if values.notna().any() else 0.0
    deviation = (values - median).abs()
    mad = float(deviation.median()) if deviation.notna().any() else 0.0
    if math.isfinite(mad) and mad > 1e-12:
        scale = 1.4826 * mad
    else:
        scale = float(values.std(ddof=0)) if values.notna().any() else 0.0
    if not math.isfinite(scale) or scale <= 1e-12:
        return pd.Series(0.0, index=series.index, dtype=float)
    return ((values - median) / scale).clip(-4.0, 4.0).fillna(0.0)


def scored_taxonomy(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    output = frame.copy()
    if "ticker" not in output.columns:
        raise ChallengerError("scored_ticker_column_missing")
    output["ticker"] = output["ticker"].map(normalize_ticker)
    output = output.loc[
        ~output["ticker"].isin({"", "CASH", "__CASH__"})
    ].copy()
    if output.empty or output["ticker"].duplicated().any():
        raise ChallengerError("scored_ticker_empty_or_duplicate")
    sector_column = first_column(
        output, ("sector", "gics_sector", "Sector", "sector_name")
    )
    industry_group_column = first_column(
        output,
        (
            "industry_group",
            "industryGroup",
            "gics_industry_group",
            "industry",
            "Industry",
        ),
    )
    subindustry_column = first_column(
        output,
        (
            "subindustry",
            "sub_industry",
            "gics_subindustry",
            "industry_detail",
            "industry",
            "Industry",
        ),
    )
    if sector_column is None or industry_group_column is None:
        raise ChallengerError("taxonomy_columns_missing")
    output["sector"] = output[sector_column].map(canonical_sector)
    output["industry_group"] = output[industry_group_column].map(clean_text)
    if subindustry_column is None:
        output["subindustry"] = output["industry_group"]
        output["taxonomy_resolution"] = "industry_group_proxy_for_subindustry"
    else:
        output["subindustry"] = output[subindustry_column].map(clean_text)
        exact_depth = subindustry_column not in {"industry", "Industry"}
        output["taxonomy_resolution"] = (
            "exact_sector_industry_group_subindustry"
            if exact_depth
            else "industry_proxy_for_group_and_subindustry"
        )
    missing_sub = output["subindustry"].eq("")
    output.loc[missing_sub, "subindustry"] = output.loc[
        missing_sub, "industry_group"
    ]
    output.loc[
        missing_sub, "taxonomy_resolution"
    ] = "industry_group_proxy_for_subindustry"
    taxonomy_ok = (
        output["sector"].isin(CANONICAL_SECTORS)
        & output["industry_group"].ne("")
        & output["subindustry"].ne("")
    )
    ratio = float(taxonomy_ok.mean())
    represented = sorted(output.loc[taxonomy_ok, "sector"].unique())
    excluded_tickers = sorted(output.loc[~taxonomy_ok, "ticker"].astype(str))
    diagnostics = {
        "taxonomy_covered_count": int(taxonomy_ok.sum()),
        "taxonomy_total_count": int(len(output)),
        "taxonomy_coverage_ratio": ratio,
        "taxonomy_excluded_count": int((~taxonomy_ok).sum()),
        "taxonomy_excluded_tickers": excluded_tickers,
        "taxonomy_excluded_ticker_set_sha256": ticker_set_sha256(
            excluded_tickers
        ),
        "taxonomy_exclusion_policy": (
            "excluded_from_leadership_calculation_after_exact_price_audit"
        ),
        "canonical_sectors": represented,
        "canonical_sector_count": len(represented),
        "missing_canonical_sectors": sorted(
            set(CANONICAL_SECTORS) - set(represented)
        ),
    }
    if ratio < 0.98:
        raise ChallengerError(f"taxonomy_coverage_below_98pct:{ratio:.6f}")
    if represented != sorted(CANONICAL_SECTORS):
        raise ChallengerError(
            "canonical_sector_representation_incomplete:"
            + ",".join(diagnostics["missing_canonical_sectors"])
        )
    # Unresolved rows never form blank-sector groups and never receive a
    # leadership alpha or confidence.  They remain represented in the eligible
    # exact-price coverage recorded before this filter.
    return output.loc[taxonomy_ok].copy(), diagnostics


def verify_scored_dates(frame: pd.DataFrame, session_date: str) -> None:
    date_column = first_column(
        frame,
        (
            "valuation_price_cutoff_date",
            "feature_date",
            "rebalance_date",
        ),
    )
    if date_column is None:
        raise ChallengerError("scored_row_date_column_missing")
    dates = pd.to_datetime(frame[date_column], errors="coerce", utc=True)
    if dates.isna().any():
        raise ChallengerError("scored_row_date_invalid")
    normalized = dates.dt.tz_convert(None).dt.date.astype(str)
    if not bool(normalized.eq(session_date).all()):
        raise ChallengerError("scored_row_date_not_exact_session")


def ticker_set_sha256(values: Iterable[Any]) -> str:
    tickers = sorted(
        {
            normalize_ticker(value)
            for value in values
            if normalize_ticker(value)
        }
    )
    return sha256_bytes(("\n".join(tickers) + "\n").encode("utf-8"))


def strict_eligibility_value(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        if int(value) in (0, 1):
            return bool(int(value))
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
    raise ChallengerError("research_eligibility_value_invalid")


def normalize_full_scored_universe(frame: pd.DataFrame) -> pd.DataFrame:
    if "ticker" not in frame.columns:
        raise ChallengerError("scored_ticker_column_missing")
    output = frame.copy()
    output["ticker"] = output["ticker"].map(normalize_ticker)
    output = output.loc[
        ~output["ticker"].isin({"", "CASH", "__CASH__"})
    ].copy()
    if output.empty:
        raise ChallengerError("full_scored_universe_empty")
    if output["ticker"].duplicated().any():
        raise ChallengerError("full_scored_ticker_duplicate")
    return output


def apply_research_eligibility(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    field = "research_eligible_after_quarantine"
    if field not in frame.columns:
        raise ChallengerError("research_eligibility_field_missing")
    output = normalize_full_scored_universe(frame)
    try:
        eligible_mask = output[field].map(strict_eligibility_value)
    except ChallengerError:
        raise
    eligible = output.loc[eligible_mask].copy()
    ineligible = output.loc[~eligible_mask].copy()
    if eligible.empty:
        raise ChallengerError("research_eligible_universe_empty")
    diagnostics = {
        "research_eligibility_field": field,
        "research_eligibility_contract": (
            "strict_true_false_or_zero_one_no_missing"
        ),
        "pre_quarantine_row_count": int(len(output)),
        "eligible_after_quarantine_count": int(len(eligible)),
        "ineligible_after_quarantine_count": int(len(ineligible)),
        "pre_eligibility_ticker_count": int(len(output)),
        "post_eligibility_ticker_count": int(len(eligible)),
        "eligible_ticker_set_sha256": ticker_set_sha256(
            eligible["ticker"]
        ),
        "ineligible_ticker_set_sha256": ticker_set_sha256(
            ineligible["ticker"]
        ),
        "ineligible_rows_in_leadership_calculation": 0,
    }
    return eligible, diagnostics


def verify_ticker_audit(
    audit_path: Path,
    tickers: set[str],
    *,
    session_date: str,
) -> dict[str, Any]:
    try:
        audit = pd.read_csv(audit_path)
    except Exception as exc:
        raise ChallengerError("ticker_refresh_audit_unreadable") from exc
    if "ticker" not in audit.columns:
        raise ChallengerError("ticker_refresh_audit_ticker_missing")
    audit = audit.copy()
    audit["ticker"] = audit["ticker"].map(normalize_ticker)
    if audit["ticker"].duplicated().any():
        raise ChallengerError("ticker_refresh_audit_duplicate_ticker")
    if "session_date" not in audit.columns:
        raise ChallengerError("ticker_refresh_audit_session_date_missing")
    audit_sessions = audit["session_date"].astype(str).str.strip()
    if not bool(audit_sessions.eq(session_date).all()):
        raise ChallengerError(
            "ticker_refresh_audit_session_date_mismatch"
        )
    indexed = audit.set_index("ticker", drop=False)
    observed = set(indexed.index)
    missing = sorted(tickers - observed)
    extras = sorted(observed - tickers)
    if missing or extras:
        raise ChallengerError(
            "ticker_refresh_audit_full_scored_universe_mismatch:"
            f"missing={','.join(missing)}:extra={','.join(extras)}"
        )
    if "status" not in audit.columns:
        raise ChallengerError("ticker_refresh_audit_status_missing")
    if not bool(
        audit["status"]
        .astype(str)
        .str.strip()
        .str.upper()
        .eq("PASS")
        .all()
    ):
        raise ChallengerError("ticker_refresh_audit_nonpass")
    if "exact_session_close" not in audit.columns:
        raise ChallengerError("ticker_refresh_audit_exact_close_missing")
    if not bool(
        audit["exact_session_close"].map(boolish).all()
    ):
        raise ChallengerError("ticker_refresh_audit_nonexact_close")
    return {
        "ticker_audit_full_scored_observed_count": int(len(observed)),
        "ticker_audit_full_scored_exact_count": int(len(audit)),
        "ticker_audit_full_scored_exact_ratio": (
            float(len(audit) / len(tickers)) if tickers else 0.0
        ),
        "ticker_audit_full_scored_ticker_set_sha256": (
            ticker_set_sha256(observed)
        ),
        "ticker_audit_session_date": session_date,
        "ticker_audit_session_date_exact": True,
    }


def verify_benchmark_cache(
    *,
    cache_dir: Path,
    manifest_path: Path,
    manifest: Mapping[str, Any],
    session_date: str,
    audits: dict[str, dict[str, Any]],
) -> dict[str, pd.DataFrame]:
    if (
        manifest.get("schema_version") != BENCHMARK_SCHEMA
        or manifest.get("status") not in BENCHMARK_READY
        or str(manifest.get("refresh_through_date") or "") != session_date
        or str(manifest.get("common_coverage_end") or "") != session_date
        or manifest.get("refresh_through_exact_coverage") is not True
        or manifest.get("refresh_through_missing_tickers") != []
    ):
        raise ChallengerError("benchmark_cache_manifest_contract_invalid")
    files = manifest.get("cache_files")
    if not isinstance(files, dict):
        raise ChallengerError("benchmark_cache_files_missing")
    result: dict[str, pd.DataFrame] = {}
    cache_root = cache_dir.resolve()
    for ticker in BENCHMARKS:
        record = files.get(ticker)
        if not isinstance(record, dict):
            raise ChallengerError(f"benchmark_cache_entry_missing:{ticker}")
        relative = str(record.get("file") or "")
        expected_filename = (
            hashlib.sha1(ticker.upper().encode("utf-8")).hexdigest()[:16]
            + ".parquet"
        )
        if (
            not relative
            or Path(relative).is_absolute()
            or relative != expected_filename
        ):
            raise ChallengerError(f"benchmark_cache_file_invalid:{ticker}")
        path = (cache_root / relative).resolve()
        try:
            path.relative_to(cache_root)
        except ValueError as exc:
            raise ChallengerError(
                f"benchmark_cache_path_escape:{ticker}"
            ) from exc
        expected = str(record.get("sha256") or "").lower()
        audits[f"benchmark_{ticker.lower()}"] = input_fingerprint(
            path,
            expected_sha256=expected,
            label=f"benchmark_{ticker.lower()}",
        )
        if record.get("bytes") is not None and (
            isinstance(record.get("bytes"), bool)
            or not isinstance(record.get("bytes"), int)
            or record.get("bytes") != path.stat().st_size
        ):
            raise ChallengerError(f"benchmark_cache_bytes_mismatch:{ticker}")
        try:
            raw = pd.read_parquet(path)
        except Exception as exc:
            raise ChallengerError(
                f"benchmark_cache_unreadable:{ticker}"
            ) from exc
        frame = normalize_price_frame(
            raw,
            session_date=session_date,
            label=f"benchmark:{ticker}",
        )
        if len(frame) < 253:
            raise ChallengerError(f"benchmark_history_too_short:{ticker}")
        result[ticker] = frame
    return result


def benchmark_returns(
    price_map: Mapping[str, pd.DataFrame],
) -> dict[tuple[str, str], float]:
    result: dict[tuple[str, str], float] = {}
    for benchmark in BENCHMARKS:
        frame = price_map[benchmark]
        for horizon, days in HORIZONS:
            value = price_return(frame, days)
            if value is None:
                raise ChallengerError(
                    f"benchmark_return_unavailable:{benchmark}:{horizon}"
                )
            result[(benchmark, horizon)] = value
    return result


def build_candidates(
    scored: pd.DataFrame,
    provider: Mapping[str, pd.DataFrame],
    benchmark_return_map: Mapping[tuple[str, str], float],
    *,
    session_date: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    tickers = set(scored["ticker"])
    if set(provider) != tickers:
        missing = sorted(tickers - set(provider))
        extra = sorted(set(provider) - tickers)
        raise ChallengerError(
            "provider_scored_universe_mismatch:"
            f"missing={','.join(missing)}:extra={','.join(extra)}"
        )
    long_columns: dict[str, str] = {}
    for horizon, candidates in LONG_MOMENTUM_COLUMNS.items():
        column = first_column(scored, candidates)
        if column is None:
            raise ChallengerError(f"scored_momentum_column_missing:{horizon}")
        long_columns[horizon] = column
    base_column = first_column(scored, BASE_SCORE_COLUMNS)
    rows: list[dict[str, Any]] = []
    session = pd.Timestamp(session_date)
    for _, scored_row in scored.sort_values("ticker").iterrows():
        ticker = str(scored_row["ticker"])
        frame = provider[ticker]
        if frame.index[-1] != session:
            raise ChallengerError(f"provider_latest_date_not_session:{ticker}")
        return_1d = price_return(frame, 1)
        return_5d = price_return(frame, 5)
        if return_1d is None or return_5d is None:
            raise ChallengerError(f"provider_short_history_incomplete:{ticker}")
        returns: dict[str, float | None] = {
            "1d": return_1d,
            "5d": return_5d,
        }
        for horizon in ("1m", "3m", "6m", "12m"):
            value = finite_number(scored_row.get(long_columns[horizon]))
            if value is None:
                days = dict(HORIZONS)[horizon]
                value = price_return(frame, days)
            returns[horizon] = value
        feature_complete = all(
            value is not None for value in returns.values()
        )
        row: dict[str, Any] = {
            "ticker": ticker,
            "sector": scored_row["sector"],
            "industry_group": scored_row["industry_group"],
            "subindustry": scored_row["subindustry"],
            "taxonomy_resolution": scored_row["taxonomy_resolution"],
            "close": float(frame.loc[session, "close"]),
            "volume_ratio": volume_ratio(frame),
            "base_score": (
                finite_number(scored_row.get(base_column))
                if base_column is not None
                else None
            ),
            "exact_close": True,
            "feature_complete": bool(feature_complete),
        }
        for horizon, _ in HORIZONS:
            row[f"return_{horizon}"] = returns[horizon]
            for benchmark in BENCHMARKS:
                stock_return = returns[horizon]
                row[f"rs_{benchmark.lower()}_{horizon}"] = (
                    None
                    if stock_return is None
                    else stock_return
                    - benchmark_return_map[(benchmark, horizon)]
                )
        rows.append(row)
    candidates = pd.DataFrame(rows)
    complete_ratio = float(candidates["feature_complete"].mean())
    if complete_ratio < 0.98:
        raise ChallengerError(
            f"stock_feature_coverage_below_98pct:{complete_ratio:.6f}"
        )

    rs_columns = [
        f"rs_{benchmark.lower()}_{horizon}"
        for benchmark in BENCHMARKS
        for horizon, _ in HORIZONS
    ]
    z_columns: dict[str, pd.Series] = {
        column: robust_zscore(candidates[column]) for column in rs_columns
    }
    rs_z = pd.DataFrame(z_columns, index=candidates.index)
    candidates["rs_composite_score"] = rs_z.mean(axis=1)
    short_columns = [
        f"rs_{benchmark.lower()}_{horizon}"
        for benchmark in BENCHMARKS
        for horizon in ("1d", "5d", "1m")
    ]
    long_columns_rs = [
        f"rs_{benchmark.lower()}_{horizon}"
        for benchmark in BENCHMARKS
        for horizon in ("3m", "6m", "12m")
    ]
    candidates["rs_acceleration_score"] = (
        rs_z[short_columns].mean(axis=1)
        - rs_z[long_columns_rs].mean(axis=1)
    )
    volume_log = pd.to_numeric(
        candidates["volume_ratio"], errors="coerce"
    ).map(lambda value: math.log(value) if pd.notna(value) and value > 0 else np.nan)
    candidates["volume_signal_score"] = robust_zscore(volume_log)
    candidates["base_score_z"] = robust_zscore(candidates["base_score"])
    candidates["alpha_score"] = (
        0.65 * candidates["rs_composite_score"]
        + 0.20 * candidates["rs_acceleration_score"]
        + 0.10 * candidates["volume_signal_score"]
        + 0.05 * candidates["base_score_z"]
    )
    taxonomy_confidence = candidates["taxonomy_resolution"].map(
        {
            "exact_sector_industry_group_subindustry": 1.0,
            "industry_group_proxy_for_subindustry": 0.75,
            "industry_proxy_for_group_and_subindustry": 0.60,
        }
    ).fillna(0.5)
    candidates["confidence_score"] = (
        0.35
        + 0.35 * candidates["feature_complete"].astype(float)
        + 0.15 * candidates["volume_ratio"].notna().astype(float)
        + 0.15 * taxonomy_confidence
    ).clip(0.0, 1.0)
    candidates = candidates.sort_values(
        ["alpha_score", "ticker"], ascending=[False, True], kind="mergesort"
    ).reset_index(drop=True)
    candidates.insert(0, "rank", np.arange(1, len(candidates) + 1))
    coverage = {
        "stock_count": int(len(candidates)),
        "exact_stock_close_count": int(candidates["exact_close"].sum()),
        "exact_stock_close_ratio": float(candidates["exact_close"].mean()),
        "feature_complete_count": int(candidates["feature_complete"].sum()),
        "feature_complete_ratio": complete_ratio,
        "volume_covered_count": int(candidates["volume_ratio"].notna().sum()),
        "volume_coverage_ratio": float(candidates["volume_ratio"].notna().mean()),
    }
    return candidates, coverage


def group_metrics(
    candidates: pd.DataFrame,
    *,
    hierarchy_level: str,
) -> pd.DataFrame:
    if hierarchy_level == "sector":
        keys = ["sector"]
    elif hierarchy_level == "industry_group":
        keys = ["sector", "industry_group"]
    elif hierarchy_level == "subindustry":
        keys = ["sector", "industry_group", "subindustry"]
    else:
        raise ChallengerError(f"invalid_hierarchy_level:{hierarchy_level}")
    rows: list[dict[str, Any]] = []
    rs_by_horizon = {
        horizon: [
            f"rs_{benchmark.lower()}_{horizon}" for benchmark in BENCHMARKS
        ]
        for horizon, _ in HORIZONS
    }
    for values, group in candidates.groupby(keys, sort=True, dropna=False):
        if not isinstance(values, tuple):
            values = (values,)
        labels = dict(zip(keys, values))
        member_alpha = pd.to_numeric(group["alpha_score"], errors="coerce")
        ordered = group.sort_values(
            ["alpha_score", "ticker"],
            ascending=[False, True],
            kind="mergesort",
        )
        top_count = max(1, math.ceil(len(group) * 0.25))
        top_alpha = float(ordered.head(top_count)["alpha_score"].mean())
        median_alpha = float(member_alpha.median())
        breadth: dict[str, float] = {}
        for horizon in ("1d", "5d", "1m"):
            per_stock = group[rs_by_horizon[horizon]].mean(axis=1)
            breadth[horizon] = float(per_stock.gt(0.0).mean())
        breadth_composite = float(
            np.mean([breadth["1d"], breadth["5d"], breadth["1m"]])
        )
        volume_confirmation = float(
            pd.to_numeric(
                group["volume_signal_score"], errors="coerce"
            ).median()
        )
        acceleration = float(
            pd.to_numeric(
                group["rs_acceleration_score"], errors="coerce"
            ).median()
        )
        alpha_score = (
            0.50 * median_alpha
            + 0.20 * top_alpha
            + 0.20 * (2.0 * breadth_composite - 1.0)
            + 0.10 * volume_confirmation
        )
        sample_confidence = min(1.0, math.sqrt(len(group) / 5.0))
        confidence = float(group["confidence_score"].mean()) * (
            0.70 + 0.30 * sample_confidence
        )
        entity_parts = [hierarchy_level]
        entity_parts.extend(str(labels[key]) for key in keys)
        row = {
            "hierarchy_level": hierarchy_level,
            "entity_key": "|".join(entity_parts),
            "sector": labels.get("sector", ""),
            "industry_group": labels.get("industry_group", ""),
            "subindustry": labels.get("subindustry", ""),
            "member_count": int(len(group)),
            "alpha_score": float(alpha_score),
            "confidence_score": float(np.clip(confidence, 0.0, 1.0)),
            "breadth_1d": breadth["1d"],
            "breadth_5d": breadth["5d"],
            "breadth_1m": breadth["1m"],
            "breadth_composite": breadth_composite,
            "rs_acceleration_score": acceleration,
            "volume_confirmation": volume_confirmation,
            "top_member": str(ordered.iloc[0]["ticker"]),
            "top_member_alpha_score": float(ordered.iloc[0]["alpha_score"]),
        }
        rows.append(row)
    output = pd.DataFrame(rows)
    output = output.sort_values(
        ["alpha_score", "entity_key"],
        ascending=[False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    output.insert(0, "rank", np.arange(1, len(output) + 1))
    return output


def classify_signal(row: Mapping[str, Any]) -> str:
    alpha = safe_float(row.get("alpha_score"))
    breadth_5d = safe_float(row.get("breadth_5d"))
    breadth_composite = safe_float(row.get("breadth_composite"))
    acceleration = safe_float(row.get("rs_acceleration_score"))
    if (
        alpha <= THRESHOLDS["breakdown_alpha_max"]
        or (
            breadth_5d <= THRESHOLDS["breakdown_breadth_5d_max"]
            and acceleration < 0.0
        )
    ):
        return "BREAKDOWN"
    if (
        alpha <= THRESHOLDS["weakening_alpha_max"]
        or (
            breadth_5d <= THRESHOLDS["weakening_breadth_5d_max"]
            and acceleration <= 0.0
        )
    ):
        return "WEAKENING"
    if (
        alpha >= THRESHOLDS["leading_alpha_min"]
        and breadth_5d >= THRESHOLDS["leading_breadth_5d_min"]
        and breadth_composite
        >= THRESHOLDS["leading_breadth_composite_min"]
    ):
        return "LEADING"
    if (
        alpha >= THRESHOLDS["emerging_alpha_min"]
        and breadth_5d >= THRESHOLDS["emerging_breadth_5d_min"]
        and breadth_composite
        >= THRESHOLDS["emerging_breadth_composite_min"]
    ):
        return "EMERGING"
    return "WEAKENING"


def stock_state_metrics(row: Mapping[str, Any]) -> dict[str, Any]:
    rs_1d = np.mean(
        [safe_float(row.get(f"rs_{benchmark.lower()}_1d")) for benchmark in BENCHMARKS]
    )
    rs_5d = np.mean(
        [safe_float(row.get(f"rs_{benchmark.lower()}_5d")) for benchmark in BENCHMARKS]
    )
    rs_1m = np.mean(
        [safe_float(row.get(f"rs_{benchmark.lower()}_1m")) for benchmark in BENCHMARKS]
    )
    return {
        "alpha_score": safe_float(row.get("alpha_score")),
        "breadth_1d": float(rs_1d > 0.0),
        "breadth_5d": float(rs_5d > 0.0),
        "breadth_1m": float(rs_1m > 0.0),
        "breadth_composite": float(
            np.mean([rs_1d > 0.0, rs_5d > 0.0, rs_1m > 0.0])
        ),
        "rs_acceleration_score": safe_float(
            row.get("rs_acceleration_score")
        ),
    }


def prior_state_map(
    payload: Mapping[str, Any] | None,
    *,
    expected_prior_session: str,
) -> dict[tuple[str, str], dict[str, Any]]:
    if not payload:
        return {}
    expected_session = parse_iso_date(
        expected_prior_session, "expected_prior_session"
    )
    rows = payload.get("state_memory")
    if not isinstance(rows, list):
        raise ChallengerError("prior_state_memory_missing")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for value in rows:
        if not isinstance(value, dict):
            raise ChallengerError("prior_state_memory_record_invalid")
        required_fields = {
            "entity_type",
            "entity_key",
            "state",
            "signal",
            "pending_confirmation",
            "pending_streak",
            "last_evidence_session",
            "last_session",
        }
        if not required_fields.issubset(value):
            raise ChallengerError(
                "prior_state_memory_required_field_missing"
            )
        entity_type = str(value.get("entity_type") or "")
        entity_key = str(value.get("entity_key") or "")
        state = str(value.get("state") or "")
        signal = str(value.get("signal") or "")
        pending = str(value.get("pending_confirmation") or "")
        pending_streak = value.get("pending_streak")
        last_evidence = str(value.get("last_evidence_session") or "")
        last_session = parse_iso_date(
            value.get("last_session"),
            "prior_state_memory_last_session",
        )
        if (
            entity_type not in ENTITY_TYPES
            or not entity_key
            or not entity_key.startswith(f"{entity_type}|")
            or state not in STATE_VALUES
            or signal not in RAW_SIGNAL_VALUES
            or pending not in PENDING_CONFIRMATION_VALUES
            or isinstance(pending_streak, bool)
            or not isinstance(pending_streak, int)
            or pending_streak < 0
            or last_session != expected_session
            or (entity_type, entity_key) in result
        ):
            raise ChallengerError("prior_state_memory_record_invalid")
        if last_evidence:
            evidence_session = parse_iso_date(
                last_evidence,
                "prior_state_memory_last_evidence_session",
            )
            if evidence_session != expected_session:
                raise ChallengerError(
                    "prior_state_memory_evidence_session_mismatch"
                )
        if state == "EMERGING_WATCH":
            if (
                signal not in {"EMERGING", "LEADING"}
                or pending not in {"EMERGING", "REENTRY"}
                or pending_streak != 1
                or last_evidence != expected_session
            ):
                raise ChallengerError(
                    "prior_state_memory_pending_watch_incoherent"
                )
        else:
            if pending or pending_streak != 0 or last_evidence:
                raise ChallengerError(
                    "prior_state_memory_nonwatch_pending_incoherent"
                )
            allowed_signal_by_state = {
                "BREAKDOWN": {"BREAKDOWN"},
                "WEAKENING": {"WEAKENING"},
                "EMERGING_CONFIRMED": {"EMERGING"},
                "LEADING": {"LEADING"},
                "REENTRY": {"EMERGING", "LEADING"},
            }
            if signal not in allowed_signal_by_state.get(state, set()):
                raise ChallengerError(
                    "prior_state_memory_state_signal_incoherent"
                )
        result[(entity_type, entity_key)] = dict(value)
    return result


def advance_state(
    *,
    entity_type: str,
    entity_key: str,
    signal: str,
    session_date: str,
    prior: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    previous_state = str((prior or {}).get("state") or "")
    previous_session = str((prior or {}).get("last_session") or "")
    if previous_session == session_date:
        if str((prior or {}).get("signal") or "") != signal:
            raise ChallengerError(
                f"same_date_signal_drift:{entity_type}:{entity_key}"
            )
        memory = dict(prior or {})
        transition = {
            "session_date": session_date,
            "entity_type": entity_type,
            "entity_key": entity_key,
            "previous_state": previous_state,
            "raw_signal": signal,
            "current_state": previous_state,
            "state_changed": False,
            "pending_confirmation": str(
                memory.get("pending_confirmation") or ""
            ),
            "pending_streak": int(memory.get("pending_streak") or 0),
            "confirmation_distinct_sessions_required": 2,
            "immediate_negative_transition": False,
            "same_date_idempotent": True,
        }
        return memory, transition

    if signal in {"BREAKDOWN", "WEAKENING"}:
        state = signal
        pending = ""
        streak = 0
        last_evidence_session = ""
        immediate_negative = True
    else:
        immediate_negative = False
        if previous_state == "LEADING" and signal == "LEADING":
            state = "LEADING"
            pending = ""
            streak = 0
            last_evidence_session = ""
        elif previous_state == "EMERGING_CONFIRMED":
            state = "LEADING" if signal == "LEADING" else "EMERGING_CONFIRMED"
            pending = ""
            streak = 0
            last_evidence_session = ""
        elif previous_state == "REENTRY":
            state = "LEADING" if signal == "LEADING" else "REENTRY"
            pending = ""
            streak = 0
            last_evidence_session = ""
        else:
            recovery = (
                previous_state in {"BREAKDOWN", "WEAKENING"}
                or str((prior or {}).get("pending_confirmation") or "")
                == "REENTRY"
            )
            target = "REENTRY" if recovery else "EMERGING"
            prior_pending = str(
                (prior or {}).get("pending_confirmation") or ""
            )
            prior_evidence_session = str(
                (prior or {}).get("last_evidence_session") or ""
            )
            prior_streak = int((prior or {}).get("pending_streak") or 0)
            streak = (
                prior_streak + 1
                if prior_pending == target
                and prior_evidence_session
                and prior_evidence_session != session_date
                else 1
            )
            last_evidence_session = session_date
            if streak >= int(THRESHOLDS["confirmation_distinct_sessions"]):
                if target == "REENTRY":
                    state = "REENTRY"
                else:
                    state = (
                        "LEADING"
                        if signal == "LEADING"
                        else "EMERGING_CONFIRMED"
                    )
                pending = ""
                streak = 0
                last_evidence_session = ""
            else:
                state = "EMERGING_WATCH"
                pending = target
    memory = {
        "entity_type": entity_type,
        "entity_key": entity_key,
        "state": state,
        "signal": signal,
        "pending_confirmation": pending,
        "pending_streak": int(streak),
        "last_evidence_session": last_evidence_session,
        "last_session": session_date,
    }
    transition = {
        "session_date": session_date,
        "entity_type": entity_type,
        "entity_key": entity_key,
        "previous_state": previous_state,
        "raw_signal": signal,
        "current_state": state,
        "state_changed": state != previous_state,
        "pending_confirmation": pending,
        "pending_streak": int(streak),
        "confirmation_distinct_sessions_required": 2,
        "immediate_negative_transition": immediate_negative,
        "same_date_idempotent": False,
    }
    return memory, transition


def apply_states(
    *,
    candidates: pd.DataFrame,
    sector_frame: pd.DataFrame,
    industry_frame: pd.DataFrame,
    subindustry_frame: pd.DataFrame,
    session_date: str,
    prior_states: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    list[dict[str, Any]],
]:
    state_memory: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []

    def decorate(
        frame: pd.DataFrame,
        entity_type: str,
        key_column: str,
        metric_fn: Any | None = None,
    ) -> pd.DataFrame:
        output = frame.copy()
        signals: list[str] = []
        states: list[str] = []
        pending: list[str] = []
        streaks: list[int] = []
        for _, row in output.iterrows():
            entity_key = str(row[key_column])
            metrics = metric_fn(row) if metric_fn else row
            signal = classify_signal(metrics)
            memory, transition = advance_state(
                entity_type=entity_type,
                entity_key=entity_key,
                signal=signal,
                session_date=session_date,
                prior=prior_states.get((entity_type, entity_key)),
            )
            state_memory.append(memory)
            transitions.append(transition)
            signals.append(signal)
            states.append(memory["state"])
            pending.append(memory["pending_confirmation"])
            streaks.append(int(memory["pending_streak"]))
        output["raw_signal"] = signals
        output["leadership_state"] = states
        output["pending_confirmation"] = pending
        output["pending_streak"] = streaks
        return output

    sector = decorate(sector_frame, "sector", "entity_key")
    industry = decorate(industry_frame, "industry_group", "entity_key")
    subindustry = decorate(subindustry_frame, "subindustry", "entity_key")
    stock = candidates.copy()
    stock["entity_key"] = "stock|" + stock["ticker"].astype(str)
    stock = decorate(stock, "stock", "entity_key", stock_state_metrics)
    stock = stock.drop(columns=["entity_key"])
    transitions_frame = pd.DataFrame(transitions)
    transitions_frame = transitions_frame.sort_values(
        ["entity_type", "entity_key"], kind="mergesort"
    ).reset_index(drop=True)
    state_memory = sorted(
        state_memory,
        key=lambda row: (str(row["entity_type"]), str(row["entity_key"])),
    )
    return stock, sector, industry, subindustry, transitions_frame, state_memory


def validate_accepted_manifest(
    payload: Mapping[str, Any],
    requested: SourceIdentity,
) -> tuple[str, SourceIdentity]:
    status = str(payload.get("status") or "")
    as_of_date = str(payload.get("as_of_date") or "")
    if status != ACCEPTED_READY:
        return SKIPPED_NO_ACCEPTED_STATUS, requested
    if as_of_date != requested.session_date:
        return SKIPPED_CATCHUP_STATUS, requested
    if payload.get("schema_version") != ACCEPTED_SCHEMA:
        raise ChallengerError("accepted_publication_schema_invalid")
    ensure_safety(
        payload,
        label="accepted_publication",
        required_true=("review_only",),
        required_false=(
            "automatic_champion_replacement_allowed",
            "production_activation_allowed",
            "live_trading_enabled",
            "fullrun_executed",
        ),
    )
    identity = payload.get("source_identity")
    if not isinstance(identity, dict):
        raise ChallengerError("accepted_source_identity_missing")
    accepted = SourceIdentity(
        run_id=str(identity.get("run_id") or ""),
        run_attempt=str(identity.get("run_attempt") or ""),
        commit_sha=str(identity.get("commit_sha") or "").lower(),
        session_date=as_of_date,
        workflow=str(identity.get("workflow") or ""),
    )
    if (
        accepted.run_id != requested.run_id
        or accepted.run_attempt != requested.run_attempt
        or accepted.commit_sha != requested.commit_sha
        or not accepted.workflow
        or (
            requested.workflow
            and requested.workflow != accepted.workflow
        )
    ):
        raise ChallengerError("accepted_source_identity_mismatch")
    return READY_STATUS, accepted


def load_prior(
    args: argparse.Namespace,
    *,
    session_date: str,
    current_input_set_sha256: str,
    audits: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    raw_path = str(args.prior_challenger_artifact or "").strip()
    raw_hash = str(args.expected_prior_challenger_sha256 or "").strip()
    if bool(raw_path) != bool(raw_hash):
        raise ChallengerError("prior_artifact_and_hash_must_be_paired")
    if not raw_path:
        return None, {}
    path = repo_path(raw_path)
    audits["prior_challenger_artifact"] = input_fingerprint(
        path,
        expected_sha256=raw_hash,
        label="prior_challenger_artifact",
    )
    payload = strict_json_object(path)
    if (
        payload.get("schema_version") != SUMMARY_SCHEMA_VERSION
        or payload.get("status") != READY_STATUS
    ):
        raise ChallengerError("prior_challenger_contract_invalid")
    ensure_safety(
        payload,
        label="prior_challenger",
        required_true=("research_only",),
        required_false=(
            "production_activation_allowed",
            "target_books_mutated",
            "orders_generated",
            "automatic_promotion_allowed",
        ),
    )
    identity = payload.get("source_identity")
    if not isinstance(identity, dict):
        raise ChallengerError("prior_source_identity_missing")
    prior_session = parse_iso_date(
        identity.get("session_date"), "prior_session_date"
    )
    if prior_session > session_date:
        raise ChallengerError("prior_session_is_future")
    # Validate every state record even when an old prior will be ignored for
    # hysteresis.  A hash-bound summary may not carry internally contradictory
    # or future-dated memory.
    prior_state_map(
        payload,
        expected_prior_session=prior_session,
    )
    if (
        prior_session < session_date
        and prior_session != previous_nyse_session(session_date)
    ):
        return None, {
            "path": str(path),
            "sha256": audits["prior_challenger_artifact"]["sha256"],
            "session_date": prior_session,
            "same_date": False,
            "ignored": True,
            "ignored_reason": "not_immediately_preceding_nyse_session",
            "state_restart": "fresh_first_observation",
        }
    if (
        prior_session == session_date
        and payload.get("input_set_sha256") != current_input_set_sha256
    ):
        raise ChallengerError("same_date_input_drift")
    return payload, {
        "path": str(path),
        "sha256": audits["prior_challenger_artifact"]["sha256"],
        "session_date": prior_session,
        "same_date": prior_session == session_date,
    }


def requested_identity(args: argparse.Namespace) -> SourceIdentity:
    commit = str(args.source_commit_sha or "").lower()
    if not valid_commit(commit):
        raise ChallengerError("source_commit_sha_invalid")
    run_id = str(args.source_run_id or "").strip()
    run_attempt = str(args.source_run_attempt or "").strip()
    if not run_id or not run_attempt:
        raise ChallengerError("source_run_identity_invalid")
    return SourceIdentity(
        run_id=run_id,
        run_attempt=run_attempt,
        commit_sha=commit,
        session_date=parse_iso_date(
            args.source_session_date, "source_session_date"
        ),
        workflow=str(args.source_workflow or "").strip(),
    )


def build(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = declared_output_path(args.output_dir)
    requested = requested_identity(args)
    audits: dict[str, dict[str, Any]] = {}

    if bool(getattr(args, "emit_catchup_skip", False)):
        if not requested.workflow:
            raise ChallengerError(
                "source_workflow_required_for_catchup_skip"
            )
        skip_hash = input_set_sha256(audits, requested)
        return emit_artifacts(
            output_dir,
            status=SKIPPED_CATCHUP_NO_PIT_STATUS,
            identity=requested,
            audits=audits,
            blockers=["catchup_has_no_pit_score_snapshot"],
            input_set_hash=skip_hash,
        )

    normal_required = {
        "accepted_publication_manifest": args.accepted_publication_manifest,
        "expected_accepted_publication_sha256": (
            args.expected_accepted_publication_sha256
        ),
        "scored_latest_manifest": args.scored_latest_manifest,
        "expected_scored_latest_manifest_sha256": (
            args.expected_scored_latest_manifest_sha256
        ),
        "scored_latest_csv": args.scored_latest_csv,
        "expected_scored_latest_csv_sha256": (
            args.expected_scored_latest_csv_sha256
        ),
        "provider_price_overlap": args.provider_price_overlap,
        "expected_provider_price_overlap_sha256": (
            args.expected_provider_price_overlap_sha256
        ),
        "ticker_refresh_audit": args.ticker_refresh_audit,
        "expected_ticker_refresh_audit_sha256": (
            args.expected_ticker_refresh_audit_sha256
        ),
        "benchmark_cache_dir": args.benchmark_cache_dir,
        "benchmark_cache_manifest": args.benchmark_cache_manifest,
        "expected_benchmark_cache_manifest_sha256": (
            args.expected_benchmark_cache_manifest_sha256
        ),
    }
    missing_normal = sorted(
        key
        for key, value in normal_required.items()
        if not str(value or "").strip()
    )
    if missing_normal:
        raise ChallengerError(
            "normal_mode_required_argument_missing:"
            + ",".join(missing_normal)
        )

    accepted_path = repo_path(args.accepted_publication_manifest)
    audits["accepted_publication_manifest"] = input_fingerprint(
        accepted_path,
        expected_sha256=args.expected_accepted_publication_sha256,
        label="accepted_publication_manifest",
    )
    accepted_payload = strict_json_object(accepted_path)
    accepted_status, identity = validate_accepted_manifest(
        accepted_payload, requested
    )
    if accepted_status != READY_STATUS:
        blockers = [
            (
                "accepted_publication_not_ready"
                if accepted_status == SKIPPED_NO_ACCEPTED_STATUS
                else "accepted_publication_not_for_requested_session"
            )
        ]
        reverify_inputs(audits)
        return emit_artifacts(
            output_dir,
            status=accepted_status,
            identity=requested,
            audits=audits,
            blockers=blockers,
            input_set_hash=input_set_sha256(audits, requested),
        )

    scored_manifest_path = repo_path(args.scored_latest_manifest)
    scored_path = repo_path(args.scored_latest_csv)
    provider_path = repo_path(args.provider_price_overlap)
    audit_path = repo_path(args.ticker_refresh_audit)
    benchmark_manifest_path = repo_path(args.benchmark_cache_manifest)
    benchmark_cache_dir = repo_path(args.benchmark_cache_dir)

    declared_inputs = (
        (
            "scored_latest_manifest",
            scored_manifest_path,
            args.expected_scored_latest_manifest_sha256,
        ),
        (
            "scored_latest_csv",
            scored_path,
            args.expected_scored_latest_csv_sha256,
        ),
        (
            "provider_price_overlap",
            provider_path,
            args.expected_provider_price_overlap_sha256,
        ),
        (
            "ticker_refresh_audit",
            audit_path,
            args.expected_ticker_refresh_audit_sha256,
        ),
        (
            "benchmark_cache_manifest",
            benchmark_manifest_path,
            args.expected_benchmark_cache_manifest_sha256,
        ),
    )
    for label, path, expected in declared_inputs:
        audits[label] = input_fingerprint(
            path, expected_sha256=expected, label=label
        )

    scored_manifest = strict_json_object(scored_manifest_path)
    if (
        scored_manifest.get("schema_version") != SCORED_SCHEMA
        or scored_manifest.get("status") != SCORED_READY
        or str(scored_manifest.get("session_date") or "")
        != identity.session_date
    ):
        raise ChallengerError("scored_latest_manifest_contract_invalid")
    ensure_safety(
        scored_manifest,
        label="scored_latest_manifest",
        required_true=("research_only",),
        required_false=(
            "fullrun_executed",
            "target_books_mutated",
            "production_activation_allowed",
        ),
    )
    audits["scored_manifest_output_csv"] = resolve_manifest_output(
        scored_manifest_path,
        scored_manifest,
        key="scored_latest.csv",
        explicit_path=scored_path,
        expected_sha256=args.expected_scored_latest_csv_sha256,
    )
    audits["scored_manifest_output_provider"] = resolve_manifest_output(
        scored_manifest_path,
        scored_manifest,
        key="provider_price_overlap.parquet",
        explicit_path=provider_path,
        expected_sha256=args.expected_provider_price_overlap_sha256,
    )
    audits["scored_manifest_output_ticker_audit"] = resolve_manifest_output(
        scored_manifest_path,
        scored_manifest,
        key="ticker_refresh_audit.csv",
        explicit_path=audit_path,
        expected_sha256=args.expected_ticker_refresh_audit_sha256,
    )

    benchmark_manifest = strict_json_object(benchmark_manifest_path)
    benchmark_map = verify_benchmark_cache(
        cache_dir=benchmark_cache_dir,
        manifest_path=benchmark_manifest_path,
        manifest=benchmark_manifest,
        session_date=identity.session_date,
        audits=audits,
    )
    benchmark_return_map = benchmark_returns(benchmark_map)

    try:
        scored_raw = pd.read_csv(scored_path)
    except Exception as exc:
        raise ChallengerError("scored_latest_csv_unreadable") from exc
    verify_scored_dates(scored_raw, identity.session_date)
    full_scored = normalize_full_scored_universe(scored_raw)
    full_scored_tickers = set(full_scored["ticker"])
    provider, provider_coverage = provider_price_map(
        provider_path,
        session_date=identity.session_date,
        required_tickers=full_scored_tickers,
    )
    ticker_audit_coverage = verify_ticker_audit(
        audit_path,
        full_scored_tickers,
        session_date=identity.session_date,
    )
    eligible_scored, eligibility_coverage = apply_research_eligibility(
        full_scored
    )
    eligible_tickers = set(eligible_scored["ticker"])
    scored, taxonomy_coverage = scored_taxonomy(eligible_scored)
    leadership_tickers = set(scored["ticker"])
    leadership_provider = {
        ticker: provider[ticker] for ticker in sorted(leadership_tickers)
    }

    candidates, stock_coverage = build_candidates(
        scored,
        leadership_provider,
        benchmark_return_map,
        session_date=identity.session_date,
    )
    coverage = {
        **eligibility_coverage,
        **provider_coverage,
        **ticker_audit_coverage,
        **taxonomy_coverage,
        **stock_coverage,
        "eligible_exact_price_audited_count": int(
            len(eligible_tickers)
        ),
        "eligible_exact_price_audited_ticker_set_sha256": (
            ticker_set_sha256(eligible_tickers)
        ),
        "leadership_calculation_ticker_count": int(
            len(leadership_tickers)
        ),
        "leadership_calculation_ticker_set_sha256": (
            ticker_set_sha256(leadership_tickers)
        ),
        "full_scored_ticker_count": int(len(full_scored_tickers)),
        "full_scored_ticker_set_sha256": ticker_set_sha256(
            full_scored_tickers
        ),
        "full_source_ticker_count": int(len(full_scored_tickers)),
        "full_source_ticker_set_sha256": ticker_set_sha256(
            full_scored_tickers
        ),
        "eligible_ticker_count": int(len(eligible_tickers)),
        "eligible_ticker_set_sha256": ticker_set_sha256(
            eligible_tickers
        ),
        "analyzed_ticker_count": int(len(leadership_tickers)),
        "analyzed_ticker_set_sha256": ticker_set_sha256(
            leadership_tickers
        ),
        "full_source_exact_close_count": int(
            len(full_scored_tickers)
        ),
        "full_source_exact_close_ratio": 1.0,
        "eligible_exact_close_count": int(len(eligible_tickers)),
        "eligible_exact_close_ratio": 1.0,
        "analyzed_exact_close_count": int(len(leadership_tickers)),
        "analyzed_exact_close_ratio": 1.0,
        "breadth_scope": "eligible_candidate_breadth",
        "leadership_scope": "eligible_candidate_leadership",
        "full_universe_market_breadth_claimed": False,
        "full_universe_canonical_taxonomy_complete": False,
        "full_universe_canonical_taxonomy_enrichment_required": True,
        "exact_benchmarks": list(BENCHMARKS),
        "benchmark_count": len(BENCHMARKS),
    }
    current_input_hash = input_set_sha256(audits, identity)
    prior_payload, prior_record = load_prior(
        args,
        session_date=identity.session_date,
        current_input_set_sha256=current_input_hash,
        audits=audits,
    )
    # Prior is lineage, not current evidence.  Its hash is intentionally
    # excluded from this primary input identity.
    current_input_hash = input_set_sha256(audits, identity)
    prior_states = prior_state_map(
        prior_payload,
        expected_prior_session=(
            str(prior_record.get("session_date") or "")
            if prior_payload is not None
            else identity.session_date
        ),
    )

    sectors = group_metrics(candidates, hierarchy_level="sector")
    industries = group_metrics(candidates, hierarchy_level="industry_group")
    subindustries = group_metrics(candidates, hierarchy_level="subindustry")
    (
        candidates,
        sectors,
        industries,
        subindustries,
        transitions,
        state_memory,
    ) = apply_states(
        candidates=candidates,
        sector_frame=sectors,
        industry_frame=industries,
        subindustry_frame=subindustries,
        session_date=identity.session_date,
        prior_states=prior_states,
    )
    sector_state = sectors.set_index("sector")["leadership_state"].to_dict()
    subindustry_state = subindustries.set_index(
        ["sector", "industry_group", "subindustry"]
    )["leadership_state"].to_dict()
    candidates["idiosyncratic_decline"] = [
        bool(
            str(row.raw_signal) == "BREAKDOWN"
            and sector_state.get(str(row.sector)) != "BREAKDOWN"
            and subindustry_state.get(
                (
                    str(row.sector),
                    str(row.industry_group),
                    str(row.subindustry),
                )
            )
            != "BREAKDOWN"
        )
        for row in candidates.itertuples(index=False)
    ]
    subsectors = pd.concat([industries, subindustries], ignore_index=True)
    subsectors = subsectors.sort_values(
        ["hierarchy_level", "alpha_score", "entity_key"],
        ascending=[True, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    subsectors["rank"] = (
        subsectors.groupby("hierarchy_level", sort=True).cumcount() + 1
    )
    sectors = sectors.sort_values(
        ["rank", "entity_key"], kind="mergesort"
    ).reset_index(drop=True)
    candidates = candidates.sort_values(
        ["rank", "ticker"], kind="mergesort"
    ).reset_index(drop=True)

    frames = {
        "sector_leadership.csv": sectors,
        "subsector_leadership.csv": subsectors,
        "leadership_transitions.csv": transitions,
        "candidate_ranking.csv": candidates,
    }
    reverify_inputs(audits)
    return emit_artifacts(
        output_dir,
        status=READY_STATUS,
        identity=identity,
        audits=audits,
        blockers=[],
        frames=frames,
        coverage=coverage,
        state_memory=state_memory,
        input_set_hash=current_input_hash,
        prior=prior_record,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-catchup-skip", action="store_true")
    parser.add_argument("--accepted-publication-manifest", default="")
    parser.add_argument(
        "--expected-accepted-publication-sha256", default=""
    )
    parser.add_argument("--scored-latest-manifest", default="")
    parser.add_argument(
        "--expected-scored-latest-manifest-sha256", default=""
    )
    parser.add_argument("--scored-latest-csv", default="")
    parser.add_argument("--expected-scored-latest-csv-sha256", default="")
    parser.add_argument("--provider-price-overlap", default="")
    parser.add_argument(
        "--expected-provider-price-overlap-sha256", default=""
    )
    parser.add_argument("--ticker-refresh-audit", default="")
    parser.add_argument(
        "--expected-ticker-refresh-audit-sha256", default=""
    )
    parser.add_argument("--benchmark-cache-dir", default="")
    parser.add_argument("--benchmark-cache-manifest", default="")
    parser.add_argument(
        "--expected-benchmark-cache-manifest-sha256", default=""
    )
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-run-attempt", required=True)
    parser.add_argument("--source-commit-sha", required=True)
    parser.add_argument("--source-session-date", required=True)
    parser.add_argument("--source-workflow", default="")
    parser.add_argument("--prior-challenger-artifact", default="")
    parser.add_argument("--expected-prior-challenger-sha256", default="")
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = build(args)
    except Exception as exc:
        try:
            identity = requested_identity(args)
        except Exception:
            identity = SourceIdentity(
                run_id=str(getattr(args, "source_run_id", "") or ""),
                run_attempt=str(getattr(args, "source_run_attempt", "") or ""),
                commit_sha=str(getattr(args, "source_commit_sha", "") or ""),
                session_date=str(
                    getattr(args, "source_session_date", "") or ""
                ),
                workflow=str(getattr(args, "source_workflow", "") or ""),
            )
        reason = f"{type(exc).__name__}:{exc}"
        try:
            payload = emit_artifacts(
                declared_output_path(args.output_dir),
                status=BLOCKED_STATUS,
                identity=identity,
                audits={},
                blockers=[reason],
            )
        except Exception as publish_exc:
            print(
                json.dumps(
                    {
                        "status": BLOCKED_STATUS,
                        "contract_failures": [
                            reason,
                            f"blocked_artifact_publish_failed:{type(publish_exc).__name__}:{publish_exc}",
                        ],
                        **SAFETY_FLAGS,
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
    status = str(payload.get("status") or "")
    print(
        json.dumps(
            {
                "status": status,
                "source_session_date": (
                    (payload.get("source_identity") or {}).get("session_date")
                ),
                "stock_count": payload.get("stock_count", 0),
                "sector_count": payload.get("sector_count", 0),
                **SAFETY_FLAGS,
            },
            sort_keys=True,
        )
    )
    return 0 if status in {
        READY_STATUS,
        SKIPPED_NO_ACCEPTED_STATUS,
        SKIPPED_CATCHUP_STATUS,
        SKIPPED_CATCHUP_NO_PIT_STATUS,
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())

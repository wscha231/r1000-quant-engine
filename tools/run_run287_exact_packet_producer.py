#!/usr/bin/env python3
"""Produce one exact-close Run287 selector/risk packet without execution.

The producer intentionally starts after the expensive decision-frame and
score-stack refresh.  It consumes one hash-pinned, same-close input registry,
runs the frozen selector in no-write mode, evaluates only proposed new entries
with the frozen risk contract, and leaves a packet for the append-only decision
archive.  Missing, stale, ambiguous, or changed inputs fail closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_run287_candidate_risk_watch import (  # noqa: E402
    build as build_candidate_risk,
    candidate_metadata,
)
from tools.build_run287_holding_risk_watch import sha256_file  # noqa: E402
from tools.run_run287_current_selector_no_write import (  # noqa: E402
    build as build_selector,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402
from tools.run287_code_identity import (  # noqa: E402
    code_identity_failures,
    current_code_identity,
)


SCHEMA_VERSION = "run287-exact-packet-producer-v1"
READY_STATUS = "READY_EXACT_SELECTOR_RISK_PACKET_REVIEW_ONLY"
REUSED_STATUS = "READY_EXISTING_EXACT_SELECTOR_RISK_PACKET_REVIEW_ONLY"
SKIPPED_STATUS = "SKIPPED_NO_EXACT_PACKET_INPUT_REGISTRY"
BLOCKED_STATUS = "BLOCKED_EXACT_PACKET_PRODUCER"
SELECTOR_MACRO_BENCHMARKS = ("SPY", "QQQ", "SMH")
SELECTOR_OUTPUT_FILES = {
    "advisory_policy_projection": "advisory_policy_projection.csv",
    "advisory_transition_audit": "advisory_transition_audit.csv",
    "advisory_rejection_audit": "advisory_rejection_audit.csv",
    "advisory_scenario_summary": "advisory_scenario_summary.csv",
    "advisory_policy_stage_audit": "advisory_policy_stage_audit.csv",
    "marked_official_advisory_comparison": (
        "marked_official_advisory_comparison.csv"
    ),
    "turnover_cost_summary": "turnover_cost_summary.csv",
    "benchmark_price_audit": "benchmark_price_audit.csv",
    "pit_evidence_audit": "pit_evidence_audit.csv",
    "pinned_selector_runtime_module_audit": (
        "pinned_selector_runtime_module_audit.csv"
    ),
}
RISK_OUTPUT_FILES = {
    "candidate_risk_watch": "candidate_risk_watch.csv",
    "price_source_audit": "price_source_audit.csv",
    "risk_history": "risk_history.jsonl",
}
SELECTOR_SCHEMA_VERSION = "run287-current-selector-no-write-v1"
SELECTOR_READY_STATUS = "READY_CURRENT_SELECTOR_NO_WRITE_REVIEW_REQUIRED"
RISK_SCHEMA_VERSION = "run287-candidate-risk-watch-v1"
RISK_READY_STATUSES = {
    "READY_CANDIDATE_RISK_REVIEW_ONLY",
    "READY_CANDIDATE_RISK_REVIEW_ONLY_WITH_DATA_INSUFFICIENT",
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"JSON object required: {path}")
    return loaded


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "bytes": 0, "sha256": ""}
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, timeout=10
        ).strip()
    except Exception:
        return ""


def canonical_tracked_copy(
    source: Path, destination: Path, expected_sha256: str
) -> Path:
    """Use the committed LF bytes when Windows checkout conversion changes a hash."""
    if source.is_file() and sha256_file(source) == expected_sha256:
        return source
    try:
        relative = source.resolve().relative_to(REPO_ROOT).as_posix()
        content = subprocess.check_output(
            ["git", "show", f"HEAD:{relative}"], cwd=REPO_ROOT, timeout=10
        )
    except Exception as exc:
        raise ValueError(f"cannot recover canonical tracked input: {source}") from exc
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError(f"canonical tracked input hash mismatch: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return destination


def normalized_parts(raw: str) -> list[str]:
    return [part for part in re.split(r"[\\/]+", raw.strip()) if part and not part.endswith(":")]


def resolve_portable_path(raw: str, *, owner: Path | None = None) -> Path:
    """Resolve restored Windows/Linux manifest paths without guessing by basename."""
    direct = Path(raw)
    if raw and direct.exists():
        return direct.resolve()
    if raw and not direct.is_absolute():
        relative = (owner.parent / direct) if owner is not None else (REPO_ROOT / direct)
        if relative.exists():
            return relative.resolve()
    parts = normalized_parts(raw)
    anchors = (
        "outputs",
        "cache_prices",
        "data_pit",
        "data_raw",
        "data_static",
        "models",
        "feature_store",
    )
    # A verified archive may preserve the repository-relative tree beneath a
    # dedicated restore root (for example ``run287_research_static/outputs``).
    # Prefer that owner's same-anchor tree before the live repository tree;
    # this is an exact relative-path mapping, not basename or latest discovery.
    if owner is not None:
        for anchor in anchors:
            if anchor not in parts:
                continue
            owner_anchor = next(
                (ancestor for ancestor in (owner.parent, *owner.parents) if ancestor.name == anchor),
                None,
            )
            if owner_anchor is not None:
                candidate = owner_anchor.parent.joinpath(*parts[parts.index(anchor) :])
                if candidate.exists():
                    return candidate.resolve()
    for anchor in anchors:
        if anchor in parts:
            candidate = REPO_ROOT.joinpath(*parts[parts.index(anchor) :])
            if candidate.exists():
                return candidate.resolve()
    if owner is not None and owner.parent.name in parts:
        index = parts.index(owner.parent.name)
        candidate = owner.parent.joinpath(*parts[index + 1 :])
        if candidate.exists():
            return candidate.resolve()
    return direct


def registry_record(
    registry_path: Path, record: Mapping[str, Any], label: str
) -> tuple[Path, dict[str, Any]]:
    raw = str(record.get("path") or "")
    expected = str(record.get("sha256") or "").lower()
    path = resolve_portable_path(raw, owner=registry_path)
    audit = fingerprint(path)
    audit.update(
        label=label,
        expected_sha256=expected,
        hash_matches=bool(expected and audit.get("sha256") == expected),
    )
    return path, audit


def manifest_output(
    manifest_path: Path, manifest: Mapping[str, Any], key: str
) -> tuple[Path, dict[str, Any]]:
    record = (manifest.get("outputs") or {}).get(key) or {}
    path = resolve_portable_path(str(record.get("path") or ""), owner=manifest_path)
    expected = str(record.get("sha256") or "").lower()
    audit = fingerprint(path)
    audit.update(
        label=key,
        expected_sha256=expected,
        hash_matches=bool(expected and audit.get("sha256") == expected),
    )
    return path, audit


def generated_manifest_audit(
    manifest_path: Path,
    payload: Mapping[str, Any],
    *,
    label: str,
    schema_version: str,
    ready_statuses: set[str],
    date_field: str,
    valuation_date: str,
    passed_field: str,
    expected_outputs: Mapping[str, str],
) -> tuple[dict[str, Any], list[str]]:
    """Validate one generated manifest and every byte-addressed output.

    Generated packet outputs are not portable inputs.  They must remain under
    the exact packet directory and use the canonical filenames emitted by the
    frozen builders; an absolute alias, traversal, symlink, missing/extra key,
    or changed byte stream is a contract failure.
    """

    failures: list[str] = []
    audit: dict[str, Any] = {
        "manifest": fingerprint(manifest_path),
        "expected_output_keys": sorted(expected_outputs),
        "outputs": {},
    }
    if manifest_path.is_symlink():
        failures.append(f"{label}:manifest_symlink")
    if payload.get("schema_version") != schema_version:
        failures.append(f"{label}:schema_version")
    if str(payload.get("status") or "") not in ready_statuses:
        failures.append(f"{label}:status")
    if str(payload.get(date_field) or "") != valuation_date:
        failures.append(f"{label}:date")
    if payload.get(passed_field) is not True:
        failures.append(f"{label}:passed")
    if payload.get("contract_failures") != []:
        failures.append(f"{label}:contract_failures")

    outputs = payload.get("outputs")
    if not isinstance(outputs, Mapping):
        failures.append(f"{label}:outputs_schema")
        outputs = {}
    actual_keys = {str(key) for key in outputs}
    expected_keys = set(expected_outputs)
    missing = sorted(expected_keys.difference(actual_keys))
    extra = sorted(actual_keys.difference(expected_keys))
    if missing:
        failures.append(f"{label}:outputs_missing:{','.join(missing)}")
    if extra:
        failures.append(f"{label}:outputs_extra:{','.join(extra)}")

    expected_parent = manifest_path.parent.absolute()
    for key, filename in expected_outputs.items():
        record = outputs.get(key)
        if not isinstance(record, Mapping):
            failures.append(f"{label}:output_record:{key}")
            continue
        raw_path = str(record.get("path") or "").strip()
        expected_path = expected_parent / filename
        declared = Path(os.path.abspath(raw_path)) if raw_path else Path()
        path_matches = bool(
            raw_path
            and Path(raw_path).is_absolute()
            and os.path.normcase(os.path.abspath(raw_path))
            == os.path.normcase(os.path.abspath(expected_path))
        )
        symlink = bool(raw_path and declared.is_symlink())
        current = fingerprint(declared) if raw_path else {
            "path": "",
            "exists": False,
            "bytes": 0,
            "sha256": "",
        }
        recorded_sha = str(record.get("sha256") or "").strip().lower()
        recorded_bytes = record.get("bytes")
        entry = dict(current)
        entry.update(
            expected_path=str(expected_path),
            declared_path=raw_path,
            canonical_path_matches=path_matches,
            symlink=symlink,
            recorded_exists=record.get("exists"),
            recorded_bytes=recorded_bytes,
            recorded_sha256=recorded_sha,
            hash_matches=bool(
                re.fullmatch(r"[0-9a-f]{64}", recorded_sha)
                and current.get("sha256") == recorded_sha
            ),
        )
        audit["outputs"][key] = entry
        if not path_matches:
            failures.append(f"{label}:output_path:{key}")
        if symlink:
            failures.append(f"{label}:output_symlink:{key}")
        if current.get("exists") is not True:
            failures.append(f"{label}:output_missing:{key}")
        if record.get("exists") is not True:
            failures.append(f"{label}:output_recorded_exists:{key}")
        if (
            not isinstance(recorded_bytes, int)
            or isinstance(recorded_bytes, bool)
            or recorded_bytes != current.get("bytes")
        ):
            failures.append(f"{label}:output_bytes:{key}")
        if entry["hash_matches"] is not True:
            failures.append(f"{label}:output_sha256:{key}")
    return audit, failures


def load_generated_manifest(
    manifest_path: Path,
    **audit_arguments: Any,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    try:
        payload = read_json(manifest_path)
    except Exception as exc:
        return (
            {},
            {"manifest": fingerprint(manifest_path), "outputs": {}},
            [
                f"{audit_arguments.get('label', 'generated_manifest')}"
                f":read:{type(exc).__name__}:{exc}"
            ],
        )
    audit, failures = generated_manifest_audit(
        manifest_path,
        payload,
        **audit_arguments,
    )
    return payload, audit, failures


def portable_manifest(
    source_path: Path,
    destination: Path,
    *,
    required_outputs: tuple[str, ...],
) -> tuple[Path, dict[str, Any]]:
    payload = read_json(source_path)
    for key in required_outputs:
        path, audit = manifest_output(source_path, payload, key)
        if audit.get("hash_matches") is not True:
            raise ValueError(f"manifest output hash mismatch: {source_path}:{key}")
        payload.setdefault("outputs", {}).setdefault(key, {})["path"] = str(path)
        if key == "scored_latest.csv":
            coverage = payload.get("core_candidate_coverage")
            if isinstance(coverage, dict):
                coverage["path"] = str(path)
    write_json(destination, payload)
    return destination, fingerprint(destination)


def portable_price_map_manifest(
    source_path: Path, destination_dir: Path
) -> tuple[Path, dict[str, Any]]:
    payload = read_json(source_path)
    source_csv, audit = manifest_output(source_path, payload, "selector_price_map")
    if audit.get("hash_matches") is not True:
        raise ValueError("selector price-map output hash mismatch")
    frame = pd.read_csv(source_csv, low_memory=False)
    failures: list[str] = []
    resolved: list[str] = []
    for index, row in frame.iterrows():
        path = resolve_portable_path(str(row.get("path") or ""), owner=source_csv)
        expected = str(row.get("sha256") or "").lower()
        actual = sha256_file(path) if path.is_file() else ""
        if not expected or actual != expected:
            failures.append(f"{row.get('ticker')}:{index}")
        resolved.append(str(path))
    if failures:
        raise ValueError(f"price-map source mismatch: {','.join(failures[:10])}")
    frame["path"] = resolved
    destination_dir.mkdir(parents=True, exist_ok=True)
    csv_path = destination_dir / "selector_price_map.csv"
    frame.to_csv(csv_path, index=False)
    payload.setdefault("outputs", {}).setdefault("selector_price_map", {}).update(
        fingerprint(csv_path)
    )
    manifest_path = destination_dir / "manifest.json"
    write_json(manifest_path, payload)
    return manifest_path, fingerprint(manifest_path)


def materialize_registered_inputs(
    *,
    resolved: Mapping[str, Path],
    portable_root: Path,
    required_outputs: Mapping[str, tuple[str, ...]],
    macro_market_audit_override: Path,
    sources: dict[str, Any],
) -> dict[str, Path]:
    """Revalidate every transitive registry output and publish portable owners."""
    portable: dict[str, Path] = {}
    for label, keys in required_outputs.items():
        destination = portable_root / f"{label}.json"
        portable[label], sources[f"portable:{label}"] = portable_manifest(
            resolved[label], destination, required_outputs=keys
        )
        if label == "macro_manifest":
            payload = read_json(portable[label])
            payload.setdefault("outputs", {})["market_component_audit"] = fingerprint(
                macro_market_audit_override
            )
            write_json(portable[label], payload)
            sources[f"portable:{label}"] = fingerprint(portable[label])
    portable["price_map_manifest"], sources["portable:price_map_manifest"] = (
        portable_price_map_manifest(
            resolved["price_map_manifest"], portable_root / "price_map"
        )
    )
    return portable


def build_portable_macro_market_audit(
    benchmark_audit: Mapping[str, Any],
    destination: Path,
) -> dict[str, Any]:
    """Rewrite benchmark audit paths to the isolated cache actually consumed."""
    market = benchmark_audit.get("market_component_audit") or {}
    source = Path(str(market.get("path") or ""))
    if (
        not source.is_file()
        or sha256_file(source) != str(market.get("expected_sha256") or "")
    ):
        raise ValueError("market component audit changed before portable rewrite")
    frame = pd.read_csv(source, low_memory=False)
    if "ticker" not in frame.columns:
        raise ValueError("market component audit has no ticker column")
    normalized = frame["ticker"].astype(str).str.strip().str.upper()
    for ticker in SELECTOR_MACRO_BENCHMARKS:
        rows = frame.index[normalized.eq(ticker)]
        if len(rows) != 1:
            raise ValueError(f"{ticker} portable audit row count: {len(rows)}")
        isolated = (
            (benchmark_audit.get("tickers") or {}).get(ticker) or {}
        ).get("isolated") or {}
        path = Path(str(isolated.get("path") or ""))
        expected = str(isolated.get("expected_sha256") or "")
        if (
            isolated.get("hash_matches") is not True
            or not path.is_file()
            or sha256_file(path) != expected
        ):
            raise ValueError(f"{ticker} isolated benchmark is not hash-pinned")
        frame.loc[rows[0], "isolated_path"] = str(path.resolve())
        frame.loc[rows[0], "isolated_sha256"] = expected
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(destination)
    return fingerprint(destination)


def changed_source_failures(
    value: Any,
    *,
    prefix: str = "source_inputs",
) -> list[str]:
    """Recursively rehash every fingerprint record immediately before READY."""
    failures: list[str] = []
    if not isinstance(value, Mapping):
        return failures
    raw_path = value.get("path")
    if isinstance(raw_path, str) and raw_path and "sha256" in value:
        current = fingerprint(Path(raw_path))
        if any(
            current.get(field) != value.get(field)
            for field in ("exists", "bytes", "sha256")
        ):
            failures.append(f"input_changed_before_producer_publish:{prefix}")
    for key, nested in value.items():
        if isinstance(nested, Mapping):
            failures.extend(
                changed_source_failures(
                    nested,
                    prefix=f"{prefix}.{key}",
                )
            )
    return failures


def packet_input_identity(
    sources: Mapping[str, Any],
    *,
    valuation_date: str,
    code_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Canonical identity for every non-generated input that can change a packet."""
    labels = (
        "producer_contract",
        "input_registry",
        "holding_watch_summary",
        "holding_watch_csv",
        "holding_risk_contract",
        "candidate_risk_contract_canonical",
        "selector_builder",
        "candidate_risk_builder",
    )
    hashes: dict[str, str] = {}
    for label in labels:
        record = sources.get(label) or {}
        if label == "candidate_risk_contract_canonical" and not record:
            record = sources.get("candidate_risk_contract") or {}
        hashes[label] = str(record.get("sha256") or "").lower()
    payload = {
        "schema_version": "run287-exact-packet-input-identity-v1",
        "valuation_price_cutoff_date": valuation_date,
        "git_head": str(code_identity.get("source_commit_sha") or ""),
        "code_identity_sha256": str(
            code_identity.get("identity_sha256") or ""
        ),
        "sha256_by_input": hashes,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    payload["identity_sha256"] = hashlib.sha256(serialized).hexdigest()
    return payload


def changed_code_identity_failures(
    frozen_identity: Mapping[str, Any],
) -> list[str]:
    try:
        current_identity = current_code_identity()
    except Exception as exc:
        return [f"code_identity_current:{type(exc).__name__}"]
    return code_identity_failures(
        frozen_identity,
        current=current_identity,
        prefix="code_identity",
    )


def exact_close_evidence(path: Path, valuation_date: str) -> dict[str, Any]:
    """Describe the exact final close that the selector will consume."""
    frame = pd.read_parquet(path)
    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.copy()
        frame.columns = frame.columns.get_level_values(0)
    columns = {str(column).strip().lower(): column for column in frame.columns}
    date_column = columns.get("date")
    raw_dates = frame[date_column] if date_column is not None else frame.index
    dates = pd.DatetimeIndex(pd.to_datetime(raw_dates, errors="coerce"))
    if dates.tz is not None:
        dates = dates.tz_convert(None)
    dates = dates.normalize()
    usable_dates = dates[dates.notna()]
    close_column = columns.get("adj close") or columns.get("close")
    valuation = pd.Timestamp(valuation_date).normalize()
    exact_mask = dates == valuation
    exact_values = (
        pd.to_numeric(frame.loc[exact_mask, close_column], errors="coerce").dropna()
        if close_column is not None
        else pd.Series(dtype=float)
    )
    close_value = float(exact_values.iloc[-1]) if len(exact_values) == 1 else None
    return {
        "row_count": int(len(frame)),
        "date_min": (
            pd.Timestamp(usable_dates.min()).date().isoformat()
            if len(usable_dates)
            else ""
        ),
        "date_max": (
            pd.Timestamp(usable_dates.max()).date().isoformat()
            if len(usable_dates)
            else ""
        ),
        "valuation_date": valuation.date().isoformat(),
        "valuation_row_count": int(exact_mask.sum()),
        "close_column": str(close_column or ""),
        "valuation_close": close_value,
        "passed": bool(
            len(usable_dates)
            and pd.Timestamp(usable_dates.max()) == valuation
            and int(exact_mask.sum()) == 1
            and close_column is not None
            and close_value is not None
            and math.isfinite(close_value)
            and close_value > 0.0
        ),
    }


def copy_hash_pinned(source: Path, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and sha256_file(destination) == expected_sha256:
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        if sha256_file(temporary) != expected_sha256:
            raise ValueError(f"benchmark changed while copying: {source}")
        if sha256_file(source) != expected_sha256:
            raise ValueError(f"benchmark changed after copying: {source}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def macro_price_cache(
    macro_manifest_path: Path,
    macro: Mapping[str, Any],
    *,
    destination: Path,
    valuation_date: str,
) -> tuple[Path, dict[str, Any]]:
    """Build a selector cache containing only hash-pinned SPY/QQQ/SMH files."""
    failures: list[str] = []
    payload: dict[str, Any] = {
        "schema_version": "run287-selector-macro-benchmark-cache-audit-v1",
        "valuation_price_cutoff_date": valuation_date,
        "required_tickers": list(SELECTOR_MACRO_BENCHMARKS),
        "isolated_cache": str(destination.resolve()),
        "market_component_audit": {},
        "tickers": {},
        "contract_failures": failures,
        "passed": False,
    }
    try:
        audit_path, audit = manifest_output(
            macro_manifest_path, macro, "market_component_audit"
        )
        payload["market_component_audit"] = audit
        if audit.get("hash_matches") is not True:
            failures.append("market_component_audit_hash")
            return destination, payload
        frame = pd.read_csv(audit_path, low_memory=False)
    except Exception as exc:
        failures.append(f"market_component_audit:{type(exc).__name__}:{exc}")
        return destination, payload

    if "ticker" not in frame.columns:
        failures.append("market_component_audit_missing_ticker")
        return destination, payload
    ticker_series = frame["ticker"].astype(str).str.strip().str.upper()
    planned: list[tuple[str, Path, str]] = []
    seen_sources: set[Path] = set()
    for ticker in SELECTOR_MACRO_BENCHMARKS:
        rows = frame.loc[ticker_series.eq(ticker)]
        entry: dict[str, Any] = {"audit_row_count": int(len(rows))}
        payload["tickers"][ticker] = entry
        if len(rows) != 1:
            failures.append(f"{ticker}:audit_row_count:{len(rows)}")
            continue
        row = rows.iloc[0]
        expected = str(row.get("isolated_sha256") or "").strip().lower()
        raw_path = str(row.get("isolated_path") or "").strip()
        source = resolve_portable_path(raw_path, owner=audit_path)
        source_audit = fingerprint(source)
        source_audit.update(
            expected_sha256=expected,
            hash_matches=bool(
                re.fullmatch(r"[0-9a-f]{64}", expected)
                and source_audit.get("sha256") == expected
            ),
        )
        entry.update(
            audit_record={
                "status": str(row.get("status") or ""),
                "path": raw_path,
                "expected_sha256": expected,
                "row_count": int(row.get("row_count") or 0),
                "date_min": str(row.get("date_min") or ""),
                "date_max": str(row.get("date_max") or ""),
            },
            source=source_audit,
        )
        if str(row.get("status") or "") != "ready":
            failures.append(f"{ticker}:status")
        if str(row.get("date_max") or "") != valuation_date:
            failures.append(f"{ticker}:audit_date_max")
        if source_audit.get("hash_matches") is not True:
            failures.append(f"{ticker}:source_hash")
            continue
        if source in seen_sources:
            failures.append(f"{ticker}:duplicate_source_path")
            continue
        seen_sources.add(source)
        try:
            close_evidence = exact_close_evidence(source, valuation_date)
        except Exception as exc:
            entry["exact_close"] = {
                "passed": False,
                "error": f"{type(exc).__name__}:{exc}",
            }
            failures.append(f"{ticker}:exact_close_read")
            continue
        entry["exact_close"] = close_evidence
        if close_evidence.get("passed") is not True:
            failures.append(f"{ticker}:exact_close")
        if int(row.get("row_count") or 0) != int(close_evidence["row_count"]):
            failures.append(f"{ticker}:row_count")
        if str(row.get("date_min") or "") != str(close_evidence["date_min"]):
            failures.append(f"{ticker}:audit_date_min")
        planned.append((ticker, source, expected))

    if failures:
        return destination, payload

    expected_names = {px_cache_name(ticker) for ticker in SELECTOR_MACRO_BENCHMARKS}
    destination.mkdir(parents=True, exist_ok=True)
    unexpected = sorted(
        path.name for path in destination.iterdir() if path.name not in expected_names
    )
    if unexpected:
        failures.append(f"isolated_cache_unexpected_entries:{','.join(unexpected)}")
        return destination, payload
    try:
        for ticker, source, expected in planned:
            isolated = destination / px_cache_name(ticker)
            copy_hash_pinned(source, isolated, expected)
            isolated_audit = fingerprint(isolated)
            isolated_audit.update(
                expected_sha256=expected,
                hash_matches=isolated_audit.get("sha256") == expected,
            )
            payload["tickers"][ticker]["isolated"] = isolated_audit
            if isolated_audit.get("hash_matches") is not True:
                failures.append(f"{ticker}:isolated_hash")
    except Exception as exc:
        failures.append(f"isolated_copy:{type(exc).__name__}:{exc}")

    actual_names = (
        sorted(path.name for path in destination.iterdir()) if destination.is_dir() else []
    )
    payload["isolated_entries"] = actual_names
    if set(actual_names) != expected_names:
        failures.append("isolated_cache_entry_set")
    payload["passed"] = not failures
    return destination, payload


def macro_price_cache_rehash(audit: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    market = audit.get("market_component_audit") or {}
    market_path = Path(str(market.get("path") or ""))
    if (
        not market_path.is_file()
        or sha256_file(market_path) != str(market.get("expected_sha256") or "")
    ):
        failures.append("market_component_audit_changed")
    expected_names = {px_cache_name(ticker) for ticker in SELECTOR_MACRO_BENCHMARKS}
    isolated_cache = Path(str(audit.get("isolated_cache") or ""))
    actual_names = (
        {path.name for path in isolated_cache.iterdir()}
        if isolated_cache.is_dir()
        else set()
    )
    if actual_names != expected_names:
        failures.append("isolated_cache_entry_set_changed")
    ticker_checks: dict[str, Any] = {}
    for ticker in SELECTOR_MACRO_BENCHMARKS:
        entry = (audit.get("tickers") or {}).get(ticker) or {}
        expected = str(((entry.get("source") or {}).get("expected_sha256")) or "")
        source = Path(str(((entry.get("source") or {}).get("path")) or ""))
        isolated = Path(str(((entry.get("isolated") or {}).get("path")) or ""))
        source_matches = bool(source.is_file() and sha256_file(source) == expected)
        isolated_matches = bool(isolated.is_file() and sha256_file(isolated) == expected)
        ticker_checks[ticker] = {
            "expected_sha256": expected,
            "source": str(source),
            "source_hash_matches": source_matches,
            "isolated": str(isolated),
            "isolated_hash_matches": isolated_matches,
        }
        if not source_matches:
            failures.append(f"{ticker}:source_changed")
        if not isolated_matches:
            failures.append(f"{ticker}:isolated_changed")
    return {
        "passed": not failures,
        "contract_failures": failures,
        "tickers": ticker_checks,
        "isolated_entries": sorted(actual_names),
    }


def base_payload(status: str, valuation_date: str, started: float) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "valuation_price_cutoff_date": valuation_date,
        "research_only": True,
        "advisory_only": True,
        "exact_packet_ready": status in {READY_STATUS, REUSED_STATUS},
        "selector_weights_changed_by_producer": False,
        "target_book_file_written": False,
        "orders_generated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_requests_executed": 0,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "historical_cagr_mdd_evidence_changed": False,
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }


def finish(
    output_dir: Path,
    payload: dict[str, Any],
    *,
    failures: list[str] | None = None,
    sources: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload["contract_failures"] = list(failures or [])
    payload["source_inputs"] = dict(sources or {})
    write_json(output_dir / "status.json", payload)
    return payload


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "status.json"
    previous_status_arg = str(getattr(args, "previous_status", "") or "").strip()
    previous_status_path = (
        repo_path(previous_status_arg) if previous_status_arg else status_path
    )
    try:
        previous_status = (
            read_json(previous_status_path)
            if previous_status_path.is_file()
            else {}
        )
    except Exception:
        previous_status = {}
    status_path.unlink(missing_ok=True)
    valuation_date = pd.Timestamp(args.valuation_date).date().isoformat()
    contract_path = repo_path(args.contract)
    registry_path = repo_path(args.input_registry)
    sources: dict[str, Any] = {
        "producer_contract": fingerprint(contract_path),
        "selector_builder": fingerprint(Path(build_selector.__code__.co_filename)),
        "candidate_risk_builder": fingerprint(
            Path(build_candidate_risk.__code__.co_filename)
        ),
    }
    if not registry_path.is_file():
        payload = base_payload(SKIPPED_STATUS, valuation_date, started)
        payload["skip_reason"] = "input_registry_missing"
        if args.allow_missing:
            return finish(output_dir, payload, sources=sources)
        payload["status"] = BLOCKED_STATUS
        payload["exact_packet_ready"] = False
        return finish(output_dir, payload, failures=["input_registry_missing"], sources=sources)

    contract = read_json(contract_path)
    registry = read_json(registry_path)
    sources["input_registry"] = fingerprint(registry_path)
    failures: list[str] = []
    registry_code_identity = registry.get("code_identity")
    try:
        current_identity = current_code_identity()
    except Exception as exc:
        current_identity = {}
        failures.append(f"code_identity_current:{type(exc).__name__}")
    failures.extend(
        code_identity_failures(
            registry_code_identity,
            current=current_identity,
            prefix="input_registry_code_identity",
        )
    )
    if contract.get("schema_version") != "run287-exact-packet-producer-contract-v1":
        failures.append("producer_contract_schema")
    registered_contract_sha = str(
        registry.get("producer_contract_sha256") or ""
    ).strip().lower()
    current_contract_sha = str(
        sources["producer_contract"].get("sha256") or ""
    ).strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", registered_contract_sha) is None:
        failures.append("producer_contract_sha256_missing_or_invalid")
    elif registered_contract_sha != current_contract_sha:
        failures.append("producer_contract_sha256_mismatch")
    if registry.get("schema_version") != contract.get("input_registry_schema_version"):
        failures.append("input_registry_schema")
    if registry.get("status") != "READY_EXACT_PACKET_INPUTS_REVIEW_ONLY":
        failures.append("input_registry_status")
    if str(registry.get("valuation_price_cutoff_date") or "") != valuation_date:
        failures.append("input_registry_date")

    resolved: dict[str, Path] = {}
    dynamic_payloads: dict[str, dict[str, Any]] = {}
    records = registry.get("inputs") or {}
    for label, requirement in (contract.get("required_dynamic_inputs") or {}).items():
        path, audit = registry_record(registry_path, records.get(label) or {}, label)
        resolved[label] = path
        sources[label] = audit
        if audit.get("hash_matches") is not True:
            failures.append(f"input_hash:{label}")
            continue
        payload = read_json(path)
        dynamic_payloads[label] = payload
        if payload.get("status") != requirement.get("status"):
            failures.append(f"input_status:{label}")
        if str(payload.get(requirement.get("date_field")) or "") != valuation_date:
            failures.append(f"input_date:{label}")

    for label, expected in (contract.get("required_fixed_inputs") or {}).items():
        path, audit = registry_record(registry_path, records.get(label) or {}, label)
        resolved[label] = path
        sources[label] = audit
        if audit.get("hash_matches") is not True or audit.get("sha256") != expected:
            failures.append(f"fixed_input:{label}")

    holding_summary = repo_path(args.holding_watch_summary)
    holding_csv = repo_path(args.holding_watch_csv)
    sources["holding_watch_summary"] = fingerprint(holding_summary)
    sources["holding_watch_csv"] = fingerprint(holding_csv)
    if not holding_summary.is_file() or not holding_csv.is_file():
        failures.append("holding_watch_missing")
    else:
        holding = read_json(holding_summary)
        if holding.get("status") != "READY_REVIEW_ONLY":
            failures.append("holding_watch_status")
        if str(holding.get("as_of_date") or "") != valuation_date:
            failures.append("holding_watch_date")
        expected_csv = str((holding.get("output_hashes") or {}).get("holding_risk_watch_sha256") or "")
        if sha256_file(holding_csv) != expected_csv:
            failures.append("holding_watch_csv_hash")

    tracked = contract.get("tracked_contracts") or {}
    base_contract = repo_path(args.base_contract)
    candidate_contract = repo_path(args.candidate_contract)
    sources["holding_risk_contract"] = fingerprint(base_contract)
    sources["candidate_risk_contract"] = fingerprint(candidate_contract)
    if sources["holding_risk_contract"].get("sha256") != tracked.get("holding_risk_contract"):
        failures.append("holding_risk_contract_hash")
    canonical_candidate_contract = candidate_contract
    if sources["candidate_risk_contract"].get("sha256") != tracked.get("candidate_risk_contract"):
        try:
            canonical_candidate_contract = canonical_tracked_copy(
                candidate_contract,
                output_dir / "portable_inputs" / "candidate_risk_contract.json",
                str(tracked.get("candidate_risk_contract") or ""),
            )
            sources["candidate_risk_contract_canonical"] = fingerprint(
                canonical_candidate_contract
            )
        except Exception:
            failures.append("candidate_risk_contract_hash")
    if failures:
        return finish(
            output_dir,
            base_payload(BLOCKED_STATUS, valuation_date, started),
            failures=failures,
            sources=sources,
        )

    current_packet_input_identity = packet_input_identity(
        sources,
        valuation_date=valuation_date,
        code_identity=registry_code_identity,
    )
    date_token = valuation_date.replace("-", "")
    portable_root = output_dir / "portable_inputs" / date_token
    portable_root.mkdir(parents=True, exist_ok=True)
    macro_cache_audit_path = portable_root / "macro_benchmark_cache_audit.json"
    macro_market_audit_path = (
        portable_root / "macro_benchmark_market_component_audit.csv"
    )
    try:
        macro_cache, macro_cache_audit = macro_price_cache(
            resolved["macro_manifest"],
            dynamic_payloads["macro_manifest"],
            destination=portable_root / "macro_benchmark_price_cache",
            valuation_date=valuation_date,
        )
        sources["macro_benchmark_price_cache"] = macro_cache_audit
        if macro_cache_audit.get("passed") is True:
            portable_market_audit = build_portable_macro_market_audit(
                macro_cache_audit,
                macro_market_audit_path,
            )
            macro_cache_audit["portable_market_component_audit"] = (
                portable_market_audit
            )
            sources["portable:macro_market_component_audit"] = (
                portable_market_audit
            )
        write_json(macro_cache_audit_path, macro_cache_audit)
        sources["portable:macro_benchmark_cache_audit"] = fingerprint(
            macro_cache_audit_path
        )
    except Exception as exc:
        return finish(
            output_dir,
            base_payload(BLOCKED_STATUS, valuation_date, started),
            failures=[f"macro_benchmark_cache:{type(exc).__name__}:{exc}"],
            sources=sources,
        )
    if macro_cache_audit.get("passed") is not True:
        payload = base_payload(BLOCKED_STATUS, valuation_date, started)
        payload["outputs"] = {
            "macro_benchmark_cache_audit": fingerprint(macro_cache_audit_path)
        }
        return finish(
            output_dir,
            payload,
            failures=[
                f"macro_benchmark_cache:{failure}"
                for failure in macro_cache_audit.get("contract_failures") or []
            ],
            sources=sources,
        )

    required_outputs = {
        "decision_manifest": ("selection_context",),
        "score_stack_manifest": ("ticker_order_score_stack",),
        "crisis_manifest": ("current_crisis_state",),
        "price_manifest": ("provider_price_overlap.parquet", "scored_latest.csv"),
        "macro_manifest": ("market_component_audit",),
        "soxx_manifest": ("price_file",),
    }
    try:
        portable = materialize_registered_inputs(
            resolved=resolved,
            portable_root=portable_root,
            required_outputs=required_outputs,
            macro_market_audit_override=macro_market_audit_path,
            sources=sources,
        )
    except Exception as exc:
        return finish(
            output_dir,
            base_payload(BLOCKED_STATUS, valuation_date, started),
            failures=[f"portable_input:{type(exc).__name__}:{exc}"],
            sources=sources,
        )

    packet_root = repo_path(args.packet_root)
    packet_root.mkdir(parents=True, exist_ok=True)
    selector_dir = packet_root / f"run287_current_selector_no_write_exact_close_{date_token}"
    risk_dir = packet_root / f"run287_candidate_risk_watch_exact_close_{date_token}"
    selector_manifest = selector_dir / "manifest.json"
    risk_summary = risk_dir / "summary.json"
    selector_audit_arguments = {
        "label": "selector_manifest",
        "schema_version": SELECTOR_SCHEMA_VERSION,
        "ready_statuses": {SELECTOR_READY_STATUS},
        "date_field": "valuation_price_cutoff_date",
        "valuation_date": valuation_date,
        "passed_field": "selector_no_write_passed",
        "expected_outputs": SELECTOR_OUTPUT_FILES,
    }
    risk_audit_arguments = {
        "label": "candidate_risk_summary",
        "schema_version": RISK_SCHEMA_VERSION,
        "ready_statuses": RISK_READY_STATUSES,
        "date_field": "as_of_date",
        "valuation_date": valuation_date,
        "passed_field": "candidate_risk_watch_passed",
        "expected_outputs": RISK_OUTPUT_FILES,
    }
    if selector_dir.exists() or risk_dir.exists():
        if not selector_manifest.is_file() or not risk_summary.is_file():
            return finish(
                output_dir,
                base_payload(BLOCKED_STATUS, valuation_date, started),
                failures=["partial_existing_packet"],
                sources=sources,
            )
        (
            selector_existing,
            selector_output_audit,
            selector_output_failures,
        ) = load_generated_manifest(
            selector_manifest,
            **selector_audit_arguments,
        )
        (
            risk_existing,
            risk_output_audit,
            risk_output_failures,
        ) = load_generated_manifest(
            risk_summary,
            **risk_audit_arguments,
        )
        generated_output_audit = {
            "selector": selector_output_audit,
            "candidate_risk": risk_output_audit,
        }
        sources["generated_selector_packet"] = selector_output_audit
        sources["generated_candidate_risk_packet"] = risk_output_audit
        generated_output_failures = [
            *selector_output_failures,
            *risk_output_failures,
        ]
        if generated_output_failures:
            return finish(
                output_dir,
                base_payload(BLOCKED_STATUS, valuation_date, started),
                failures=[
                    f"existing_generated_packet:{failure}"
                    for failure in generated_output_failures
                ],
                sources=sources,
            )
        previous = previous_status
        previous_sources = previous.get("source_inputs") or {}
        previous_registry_sha = str(
            (previous_sources.get("input_registry") or {}).get("sha256") or ""
        )
        current_registry_sha = str(sources["input_registry"].get("sha256") or "")
        previous_selector_sha = str(
            (previous.get("selector_manifest") or {}).get("sha256") or ""
        )
        previous_risk_sha = str(
            (previous.get("candidate_risk_summary") or {}).get("sha256") or ""
        )
        selector_sources = selector_existing.get("source_inputs") or {}
        selector_holding_summary_sha = str(
            (selector_sources.get("holding_watch_summary") or {}).get("sha256")
            or ""
        )
        selector_holding_csv_sha = str(
            (selector_sources.get("holding_watch_csv") or {}).get("sha256")
            or ""
        )
        current_holding_summary_sha = str(
            sources["holding_watch_summary"].get("sha256") or ""
        )
        current_holding_csv_sha = str(
            sources["holding_watch_csv"].get("sha256") or ""
        )
        valid_existing = bool(
            selector_existing.get("status") == SELECTOR_READY_STATUS
            and selector_existing.get("valuation_price_cutoff_date") == valuation_date
            and str(risk_existing.get("status") or "") in RISK_READY_STATUSES
            and risk_existing.get("as_of_date") == valuation_date
            and previous.get("status") in {READY_STATUS, REUSED_STATUS}
            and previous_registry_sha == current_registry_sha
            and previous_selector_sha == sha256_file(selector_manifest)
            and previous_risk_sha == sha256_file(risk_summary)
            and previous.get("packet_input_identity")
            == current_packet_input_identity
            and selector_holding_summary_sha == current_holding_summary_sha
            and selector_holding_csv_sha == current_holding_csv_sha
            and previous.get("generated_output_audit")
            == generated_output_audit
        )
        if not valid_existing:
            existing_failures = ["existing_packet_contract"]
            if (
                previous.get("packet_input_identity")
                != current_packet_input_identity
            ):
                existing_failures.append("existing_packet_input_identity")
            if (
                selector_holding_summary_sha != current_holding_summary_sha
                or selector_holding_csv_sha != current_holding_csv_sha
            ):
                existing_failures.append("existing_selector_holding_watch_identity")
            if (
                previous.get("generated_output_audit")
                != generated_output_audit
            ):
                existing_failures.append("existing_generated_output_audit")
            return finish(
                output_dir,
                base_payload(BLOCKED_STATUS, valuation_date, started),
                failures=existing_failures,
                sources=sources,
            )
        try:
            portable = materialize_registered_inputs(
                resolved=resolved,
                portable_root=portable_root,
                required_outputs=required_outputs,
                macro_market_audit_override=macro_market_audit_path,
                sources=sources,
            )
        except Exception as exc:
            return finish(
                output_dir,
                base_payload(BLOCKED_STATUS, valuation_date, started),
                failures=[
                    f"registered_input_revalidation:{type(exc).__name__}:{exc}"
                ],
                sources=sources,
            )
        macro_cache_audit["pre_publish_rehash"] = macro_price_cache_rehash(
            macro_cache_audit
        )
        write_json(macro_cache_audit_path, macro_cache_audit)
        sources["portable:macro_benchmark_cache_audit"] = fingerprint(
            macro_cache_audit_path
        )
        if macro_cache_audit["pre_publish_rehash"].get("passed") is not True:
            payload = base_payload(BLOCKED_STATUS, valuation_date, started)
            payload["outputs"] = {
                "macro_benchmark_cache_audit": fingerprint(macro_cache_audit_path)
            }
            return finish(
                output_dir,
                payload,
                failures=[
                    f"macro_benchmark_cache_rehash:{failure}"
                    for failure in macro_cache_audit["pre_publish_rehash"].get(
                        "contract_failures"
                    )
                    or []
                ],
                sources=sources,
            )
        source_changes = changed_source_failures(sources)
        source_changes.extend(
            changed_code_identity_failures(registry_code_identity)
        )
        if source_changes:
            return finish(
                output_dir,
                base_payload(BLOCKED_STATUS, valuation_date, started),
                failures=sorted(set(source_changes)),
                sources=sources,
            )
        payload = base_payload(REUSED_STATUS, valuation_date, started)
        payload["code_identity"] = registry_code_identity
        payload["packet_input_identity"] = current_packet_input_identity
        payload["generated_output_audit"] = generated_output_audit
        payload["selector_manifest"] = selector_output_audit["manifest"]
        payload["candidate_risk_summary"] = risk_output_audit["manifest"]
        payload["outputs"] = {
            "macro_benchmark_cache_audit": fingerprint(macro_cache_audit_path)
        }
        final_source_changes = changed_source_failures(sources)
        final_source_changes.extend(
            changed_code_identity_failures(registry_code_identity)
        )
        if final_source_changes:
            return finish(
                output_dir,
                base_payload(BLOCKED_STATUS, valuation_date, started),
                failures=sorted(set(final_source_changes)),
                sources=sources,
            )
        return finish(output_dir, payload, sources=sources)

    context_count = int(
        (dynamic_payloads["decision_manifest"].get("coverage") or {}).get(
            "decision_ticker_count", -1
        )
    )
    eligible_count = int(
        (dynamic_payloads["score_stack_manifest"].get("coverage") or {}).get(
            "registered_eligible_ticker_count", -1
        )
    )
    try:
        selector_args = argparse.Namespace(
            decision_manifest=str(portable["decision_manifest"]),
            expected_decision_sha256=sha256_file(portable["decision_manifest"]),
            score_stack_manifest=str(portable["score_stack_manifest"]),
            expected_score_stack_sha256=sha256_file(portable["score_stack_manifest"]),
            crisis_manifest=str(portable["crisis_manifest"]),
            expected_crisis_sha256=sha256_file(portable["crisis_manifest"]),
            price_manifest=str(portable["price_manifest"]),
            expected_price_sha256=sha256_file(portable["price_manifest"]),
            macro_manifest=str(portable["macro_manifest"]),
            expected_macro_sha256=sha256_file(portable["macro_manifest"]),
            soxx_manifest=str(portable["soxx_manifest"]),
            expected_soxx_sha256=sha256_file(portable["soxx_manifest"]),
            selector_contract_manifest=str(resolved["selector_contract_manifest"]),
            expected_selector_contract_sha256=sha256_file(resolved["selector_contract_manifest"]),
            pinned_import_manifest=str(resolved["pinned_import_manifest"]),
            expected_pinned_import_sha256=sha256_file(resolved["pinned_import_manifest"]),
            target_generation_manifest=str(resolved["target_generation_manifest"]),
            expected_target_generation_sha256=sha256_file(resolved["target_generation_manifest"]),
            main_prior_book=str(resolved["main_prior_book"]),
            expected_main_prior_book_sha256=sha256_file(resolved["main_prior_book"]),
            concentrated_prior_book=str(resolved["concentrated_prior_book"]),
            expected_concentrated_prior_book_sha256=sha256_file(resolved["concentrated_prior_book"]),
            holding_watch_summary=str(holding_summary),
            expected_holding_watch_summary_sha256=sha256_file(holding_summary),
            holding_watch_csv=str(holding_csv),
            expected_holding_watch_csv_sha256=sha256_file(holding_csv),
            macro_price_cache=str(macro_cache),
            expected_policy_commit=str(contract["pinned_policy_commit"]),
            valuation_date=valuation_date,
            expected_context_count=context_count,
            expected_eligible_count=eligible_count,
            output_dir=str(selector_dir),
        )
        build_selector(selector_args)
        (
            selector_payload,
            selector_output_audit,
            selector_output_failures,
        ) = load_generated_manifest(
            selector_manifest,
            **selector_audit_arguments,
        )
        sources["generated_selector_packet"] = selector_output_audit
        if selector_output_failures:
            raise ValueError(
                "selector_generated_contract:"
                + ",".join(selector_output_failures)
            )
        comparison_path = Path(
            str(
                selector_output_audit["outputs"][
                    "marked_official_advisory_comparison"
                ]["path"]
            )
        )
        comparison = pd.read_csv(comparison_path, low_memory=False)
        candidates = candidate_metadata(comparison)
        tickers = sorted(set(candidates.get("ticker", pd.Series(dtype=str))))
        risk_args = argparse.Namespace(
            selector_manifest=str(selector_manifest),
            expected_selector_sha256=sha256_file(selector_manifest),
            price_map_manifest=str(portable["price_map_manifest"]),
            expected_price_map_sha256=sha256_file(portable["price_map_manifest"]),
            price_manifest=str(portable["price_manifest"]),
            expected_price_sha256=sha256_file(portable["price_manifest"]),
            macro_manifest=str(portable["macro_manifest"]),
            expected_macro_sha256=sha256_file(portable["macro_manifest"]),
            holding_watch_summary=str(holding_summary),
            expected_holding_watch_summary_sha256=sha256_file(holding_summary),
            macro_price_cache=str(macro_cache),
            base_contract=args.base_contract,
            expected_base_contract_sha256=sha256_file(base_contract),
            candidate_contract=str(canonical_candidate_contract),
            expected_candidate_contract_sha256=sha256_file(canonical_candidate_contract),
            valuation_date=valuation_date,
            expected_candidate_count=len(tickers),
            expected_tickers=",".join(tickers),
            output_dir=str(risk_dir),
        )
        build_candidate_risk(risk_args)
        (
            risk_payload,
            risk_output_audit,
            risk_output_failures,
        ) = load_generated_manifest(
            risk_summary,
            **risk_audit_arguments,
        )
        sources["generated_candidate_risk_packet"] = risk_output_audit
        if risk_output_failures:
            raise ValueError(
                "candidate_risk_generated_contract:"
                + ",".join(risk_output_failures)
            )
        generated_changes_after_risk = changed_source_failures(
            {
                "selector": selector_output_audit,
                "candidate_risk": risk_output_audit,
            },
            prefix="generated_packet_after_risk",
        )
        if generated_changes_after_risk:
            raise ValueError(
                "generated_packet_changed_after_risk:"
                + ",".join(generated_changes_after_risk)
            )
    except Exception as exc:
        return finish(
            output_dir,
            base_payload(BLOCKED_STATUS, valuation_date, started),
            failures=[f"packet_build:{type(exc).__name__}:{exc}"],
            sources=sources,
        )

    try:
        portable = materialize_registered_inputs(
            resolved=resolved,
            portable_root=portable_root,
            required_outputs=required_outputs,
            macro_market_audit_override=macro_market_audit_path,
            sources=sources,
        )
    except Exception as exc:
        return finish(
            output_dir,
            base_payload(BLOCKED_STATUS, valuation_date, started),
            failures=[
                f"registered_input_revalidation:{type(exc).__name__}:{exc}"
            ],
            sources=sources,
        )
    macro_cache_audit["pre_publish_rehash"] = macro_price_cache_rehash(
        macro_cache_audit
    )
    write_json(macro_cache_audit_path, macro_cache_audit)
    sources["portable:macro_benchmark_cache_audit"] = fingerprint(
        macro_cache_audit_path
    )
    if macro_cache_audit["pre_publish_rehash"].get("passed") is not True:
        payload = base_payload(BLOCKED_STATUS, valuation_date, started)
        payload["outputs"] = {
            "macro_benchmark_cache_audit": fingerprint(macro_cache_audit_path)
        }
        return finish(
            output_dir,
            payload,
            failures=[
                f"macro_benchmark_cache_rehash:{failure}"
                for failure in macro_cache_audit["pre_publish_rehash"].get(
                    "contract_failures"
                )
                or []
            ],
            sources=sources,
        )
    source_changes = changed_source_failures(sources)
    source_changes.extend(changed_code_identity_failures(registry_code_identity))
    if source_changes:
        return finish(
            output_dir,
            base_payload(BLOCKED_STATUS, valuation_date, started),
            failures=sorted(set(source_changes)),
            sources=sources,
        )

    payload = base_payload(READY_STATUS, valuation_date, started)
    generated_output_audit = {
        "selector": selector_output_audit,
        "candidate_risk": risk_output_audit,
    }
    payload.update(
        code_identity=registry_code_identity,
        packet_input_identity=current_packet_input_identity,
        generated_output_audit=generated_output_audit,
        selector_manifest=selector_output_audit["manifest"],
        candidate_risk_summary=risk_output_audit["manifest"],
        candidate_count=int(risk_payload.get("candidate_count") or 0),
        candidate_tickers=risk_payload.get("candidate_tickers") or [],
        selector_scenario_count=len(selector_payload.get("scenario_summary") or {}),
        outputs={
            "macro_benchmark_cache_audit": fingerprint(macro_cache_audit_path)
        },
    )
    final_source_changes = changed_source_failures(sources)
    final_source_changes.extend(changed_code_identity_failures(registry_code_identity))
    if final_source_changes:
        return finish(
            output_dir,
            base_payload(BLOCKED_STATUS, valuation_date, started),
            failures=sorted(set(final_source_changes)),
            sources=sources,
        )
    return finish(output_dir, payload, sources=sources)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-registry", required=True)
    parser.add_argument(
        "--previous-status",
        default="",
        help=(
            "Optional quarantined prior status used only for exact immutable "
            "same-date reuse; the current status marker is always cleared first."
        ),
    )
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument("--holding-watch-summary", required=True)
    parser.add_argument("--holding-watch-csv", required=True)
    parser.add_argument(
        "--contract", default="docs/run287_exact_packet_producer_contract.json"
    )
    parser.add_argument(
        "--base-contract", default="docs/run287_holding_risk_watch_contract.json"
    )
    parser.add_argument(
        "--candidate-contract", default="docs/run287_candidate_risk_watch_contract.json"
    )
    parser.add_argument(
        "--output-dir", default="outputs/run287_exact_packet_producer"
    )
    parser.add_argument("--packet-root", default="outputs")
    parser.add_argument("--allow-missing", action="store_true")
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") in {READY_STATUS, REUSED_STATUS, SKIPPED_STATUS} else 2


if __name__ == "__main__":
    raise SystemExit(main())

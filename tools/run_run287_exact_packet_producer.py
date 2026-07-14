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
import re
import subprocess
import sys
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


SCHEMA_VERSION = "run287-exact-packet-producer-v1"
READY_STATUS = "READY_EXACT_SELECTOR_RISK_PACKET_REVIEW_ONLY"
REUSED_STATUS = "READY_EXISTING_EXACT_SELECTOR_RISK_PACKET_REVIEW_ONLY"
SKIPPED_STATUS = "SKIPPED_NO_EXACT_PACKET_INPUT_REGISTRY"
BLOCKED_STATUS = "BLOCKED_EXACT_PACKET_PRODUCER"


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
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


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
    anchors = ("outputs", "cache_prices", "data_pit", "data_raw", "models", "feature_store")
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


def macro_price_cache(macro_manifest_path: Path, macro: Mapping[str, Any]) -> Path:
    audit_path, audit = manifest_output(
        macro_manifest_path, macro, "market_component_audit"
    )
    if audit.get("hash_matches") is not True:
        raise ValueError("macro market component audit mismatch")
    frame = pd.read_csv(audit_path, low_memory=False)
    spy = frame.loc[frame["ticker"].astype(str).str.upper().eq("SPY")]
    if len(spy) != 1:
        raise ValueError(f"macro SPY audit count: {len(spy)}")
    path = resolve_portable_path(str(spy.iloc[0].get("isolated_path") or ""), owner=audit_path)
    if not path.is_file() or sha256_file(path) != str(spy.iloc[0].get("isolated_sha256") or ""):
        raise ValueError("macro SPY source mismatch")
    return path.parent


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
    valuation_date = pd.Timestamp(args.valuation_date).date().isoformat()
    contract_path = repo_path(args.contract)
    registry_path = repo_path(args.input_registry)
    sources: dict[str, Any] = {"producer_contract": fingerprint(contract_path)}
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
    if contract.get("schema_version") != "run287-exact-packet-producer-contract-v1":
        failures.append("producer_contract_schema")
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

    date_token = valuation_date.replace("-", "")
    packet_root = repo_path(args.packet_root)
    packet_root.mkdir(parents=True, exist_ok=True)
    selector_dir = packet_root / f"run287_current_selector_no_write_exact_close_{date_token}"
    risk_dir = packet_root / f"run287_candidate_risk_watch_exact_close_{date_token}"
    selector_manifest = selector_dir / "manifest.json"
    risk_summary = risk_dir / "summary.json"
    if selector_dir.exists() or risk_dir.exists():
        if not selector_manifest.is_file() or not risk_summary.is_file():
            return finish(
                output_dir,
                base_payload(BLOCKED_STATUS, valuation_date, started),
                failures=["partial_existing_packet"],
                sources=sources,
            )
        selector_existing = read_json(selector_manifest)
        risk_existing = read_json(risk_summary)
        previous_path = output_dir / "status.json"
        previous = read_json(previous_path) if previous_path.is_file() else {}
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
        valid_existing = bool(
            selector_existing.get("status") == "READY_CURRENT_SELECTOR_NO_WRITE_REVIEW_REQUIRED"
            and selector_existing.get("valuation_price_cutoff_date") == valuation_date
            and str(risk_existing.get("status") or "").startswith("READY_CANDIDATE_RISK_REVIEW_ONLY")
            and risk_existing.get("as_of_date") == valuation_date
            and previous.get("status") in {READY_STATUS, REUSED_STATUS}
            and previous_registry_sha == current_registry_sha
            and previous_selector_sha == sha256_file(selector_manifest)
            and previous_risk_sha == sha256_file(risk_summary)
        )
        if not valid_existing:
            return finish(
                output_dir,
                base_payload(BLOCKED_STATUS, valuation_date, started),
                failures=["existing_packet_contract"],
                sources=sources,
            )
        payload = base_payload(REUSED_STATUS, valuation_date, started)
        payload["selector_manifest"] = fingerprint(selector_manifest)
        payload["candidate_risk_summary"] = fingerprint(risk_summary)
        return finish(output_dir, payload, sources=sources)

    portable_root = output_dir / "portable_inputs" / date_token
    portable_root.mkdir(parents=True, exist_ok=True)
    required_outputs = {
        "decision_manifest": ("selection_context",),
        "score_stack_manifest": ("ticker_order_score_stack",),
        "crisis_manifest": ("current_crisis_state",),
        "price_manifest": ("provider_price_overlap.parquet",),
        "macro_manifest": ("market_component_audit",),
        "soxx_manifest": ("price_file",),
    }
    portable: dict[str, Path] = {}
    try:
        for label, keys in required_outputs.items():
            destination = portable_root / f"{label}.json"
            portable[label], sources[f"portable:{label}"] = portable_manifest(
                resolved[label], destination, required_outputs=keys
            )
        portable["price_map_manifest"], sources["portable:price_map_manifest"] = (
            portable_price_map_manifest(
                resolved["price_map_manifest"], portable_root / "price_map"
            )
        )
        macro_cache = macro_price_cache(
            portable["macro_manifest"], read_json(portable["macro_manifest"])
        )
    except Exception as exc:
        return finish(
            output_dir,
            base_payload(BLOCKED_STATUS, valuation_date, started),
            failures=[f"portable_input:{type(exc).__name__}:{exc}"],
            sources=sources,
        )

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
        selector_payload = build_selector(selector_args)
        if not selector_payload.get("selector_no_write_passed"):
            raise ValueError(f"selector blocked: {selector_payload.get('contract_failures')}")
        comparison_record = (selector_payload.get("outputs") or {}).get(
            "marked_official_advisory_comparison"
        ) or {}
        comparison_path = resolve_portable_path(
            str(comparison_record.get("path") or ""), owner=selector_manifest
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
        risk_payload = build_candidate_risk(risk_args)
        if not risk_payload.get("candidate_risk_watch_passed"):
            raise ValueError(f"candidate risk blocked: {risk_payload.get('contract_failures')}")
    except Exception as exc:
        return finish(
            output_dir,
            base_payload(BLOCKED_STATUS, valuation_date, started),
            failures=[f"packet_build:{type(exc).__name__}:{exc}"],
            sources=sources,
        )

    payload = base_payload(READY_STATUS, valuation_date, started)
    payload.update(
        selector_manifest=fingerprint(selector_manifest),
        candidate_risk_summary=fingerprint(risk_summary),
        candidate_count=int(risk_payload.get("candidate_count") or 0),
        candidate_tickers=risk_payload.get("candidate_tickers") or [],
        selector_scenario_count=len(selector_payload.get("scenario_summary") or {}),
    )
    return finish(output_dir, payload, sources=sources)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-registry", required=True)
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

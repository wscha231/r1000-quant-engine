#!/usr/bin/env python3
"""Build research-only PIT 13F manager clone event evidence artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.sec_13f_manager_clone_event_evidence import (
    CloneEvidenceConfig, CloneEvidenceError, build_event_clone_evidence,
)

MAX_INPUT_BYTES = 64 * 1024 * 1024


def _json_read(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise CloneEvidenceError("input_size_limit")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise CloneEvidenceError("invalid_json_input") from exc
    if not isinstance(value, dict):
        raise CloneEvidenceError("json_object_required")
    return value


def _table_read(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise CloneEvidenceError(f"input_missing:{path}")
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def manager_map_from_registry(registry: Mapping[str, Any]) -> dict[str, str]:
    candidates = registry.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise CloneEvidenceError("registry_candidates_missing")
    out: dict[str, str] = {}
    for row in candidates:
        if not isinstance(row, dict):
            raise CloneEvidenceError("registry_candidate_invalid")
        manager = str(row.get("economic_manager_id") or "").strip()
        cik = str(row.get("reporting_cik") or "").strip()
        if not manager or not cik:
            raise CloneEvidenceError("registry_identity_missing")
        keys = {cik, cik.lstrip("0") or "0", (cik.lstrip("0") or "0").zfill(10)}
        for key in keys:
            if key in out and out[key] != manager:
                raise CloneEvidenceError("registry_cik_conflict")
            out[key] = manager
    return out


def config_from_json(value: Mapping[str, Any]) -> CloneEvidenceConfig:
    allowed = {"horizons", "entry_delays", "per_side_cost_bps", "benchmark_ticker"}
    unknown = set(value) - allowed - {"research_only", "status", "usage"}
    if unknown:
        raise CloneEvidenceError("unknown_config_key:" + ",".join(sorted(unknown)))
    return CloneEvidenceConfig(
        horizons=tuple(int(x) for x in value.get("horizons", (63, 126, 252, 504))),
        entry_delays=tuple(int(x) for x in value.get("entry_delays", (0, 2, 5))),
        per_side_cost_bps=float(value.get("per_side_cost_bps", 10.0)),
        benchmark_ticker=str(value.get("benchmark_ticker", "SPY")),
    )


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


def publish_immutable(output_dir: Path, result: dict[str, Any], metadata: Mapping[str, Any]) -> dict[str, Any]:
    output_dir = Path(output_dir)
    if output_dir.is_symlink() or any(p.is_symlink() for p in output_dir.parents):
        raise CloneEvidenceError("symlink_output_forbidden")
    files = {
        "event_evidence.csv": _csv_bytes(result["event_rows"]),
        "summary.json": _json_bytes({k: v for k, v in result.items() if k != "event_rows"}),
    }
    manifest = {
        **dict(metadata),
        "artifact_kind": "RESEARCH_DIAGNOSTIC_NOT_ACCEPTED_STATE",
        "research_only": True,
        "manager_skill_rank_built": False,
        "continuous_clone_nav_built": False,
        "portfolio_target_changed": False,
        "automatic_trade_allowed": False,
        "production_promotion_allowed": False,
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())},
    }
    files["manifest.json"] = _json_bytes(manifest)
    if output_dir.exists():
        if not output_dir.is_dir() or {p.name for p in output_dir.iterdir()} != set(files):
            raise CloneEvidenceError("existing_output_incomplete_or_different")
        for name, raw in files.items():
            p = output_dir / name
            if p.is_symlink() or not p.is_file() or p.read_bytes() != raw:
                raise CloneEvidenceError("existing_output_hash_or_content_mismatch")
        return {**manifest, "publication": "IDENTICAL_RERUN_VERIFIED"}
    output_dir.mkdir(parents=True, exist_ok=False)
    for name in ("event_evidence.csv", "summary.json", "manifest.json"):
        with (output_dir / name).open("xb") as stream:
            stream.write(files[name]); stream.flush(); os.fsync(stream.fileno())
    return {**manifest, "publication": "NEW_LOCAL_DIAGNOSTIC"}


def evaluate(*, events: pd.DataFrame, registry: Mapping[str, Any], provenance: Mapping[str, Any],
             config_value: Mapping[str, Any], decision_cutoff: str,
             price_loader: Callable[[str], pd.DataFrame]) -> dict[str, Any]:
    config = config_from_json(config_value)
    return build_event_clone_evidence(
        events.to_dict(orient="records"), price_loader=price_loader,
        manager_map=manager_map_from_registry(registry), decision_cutoff=decision_cutoff,
        provenance=provenance, config=config,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", default="data_pit/sec/13f_position_events.parquet")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--manager-registry", default="configs/research/sec_13f_priority_registry_20260916.json")
    parser.add_argument("--provenance", required=True)
    parser.add_argument("--config", default="configs/research/sec_13f_manager_clone_event_evidence_v1.json")
    parser.add_argument("--decision-cutoff", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        events_path = Path(args.events); events_path = events_path if events_path.is_absolute() else REPO_ROOT / events_path
        cache = Path(args.price_cache); cache = cache if cache.is_absolute() else REPO_ROOT / cache
        registry_path = Path(args.manager_registry); registry_path = registry_path if registry_path.is_absolute() else REPO_ROOT / registry_path
        provenance_path = Path(args.provenance); provenance_path = provenance_path if provenance_path.is_absolute() else REPO_ROOT / provenance_path
        config_path = Path(args.config); config_path = config_path if config_path.is_absolute() else REPO_ROOT / config_path
        output = Path(args.output_dir); output = output if output.is_absolute() else REPO_ROOT / output

        from tools.run_weekly_evaluation import load_price_series
        result = evaluate(
            events=_table_read(events_path), registry=_json_read(registry_path),
            provenance=_json_read(provenance_path), config_value=_json_read(config_path),
            decision_cutoff=args.decision_cutoff,
            price_loader=lambda ticker: load_price_series(cache, ticker),
        )
        manifest = publish_immutable(output, result, {
            "decision_cutoff": result["decision_cutoff"],
            "evidence_id": result["evidence_id"],
            "events_sha256": hashlib.sha256(events_path.read_bytes()).hexdigest(),
            "registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
            "provenance_sha256": hashlib.sha256(provenance_path.read_bytes()).hexdigest(),
            "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        })
        print(json.dumps({"status": result["status"], "publication": manifest["publication"],
                          "matured_rows": result["matured_rows"], "research_only": True}))
        return 0 if result["matured_rows"] > 0 else 2
    except (CloneEvidenceError, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "BLOCKED_INTEGRITY", "reason": str(exc),
                          "accepted_publication": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

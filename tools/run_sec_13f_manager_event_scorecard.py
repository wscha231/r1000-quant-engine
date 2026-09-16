#!/usr/bin/env python3
"""Build immutable research-only 13F manager event-study scorecards."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.sec_13f_manager_event_scorecard import (
    ScorecardConfig, ScorecardError, build_manager_event_scorecards,
)

MAX_BYTES = 64 * 1024 * 1024


def read_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ScorecardError("input_size_limit")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ScorecardError("invalid_json") from exc
    if not isinstance(value, dict):
        raise ScorecardError("json_object_required")
    return value


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ScorecardError(f"input_missing:{path}")
    return pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path, low_memory=False)


def config_from_json(value: Mapping[str, Any]) -> ScorecardConfig:
    allowed = {"horizons", "base_delay", "robustness_delays", "minimum_events_per_horizon", "recent_window_months", "minimum_unique_tickers", "research_only", "status", "usage"}
    unknown = set(value) - allowed
    if unknown:
        raise ScorecardError("unknown_config_key:" + ",".join(sorted(unknown)))
    return ScorecardConfig(
        horizons=tuple(int(x) for x in value.get("horizons", (63,126,252,504))),
        base_delay=int(value.get("base_delay", 0)),
        robustness_delays=tuple(int(x) for x in value.get("robustness_delays", (2,5))),
        minimum_events_per_horizon=int(value.get("minimum_events_per_horizon", 5)),
        recent_window_months=int(value.get("recent_window_months", 36)),
        minimum_unique_tickers=int(value.get("minimum_unique_tickers", 3)),
    )


def validate_source_manifest(manifest: Mapping[str, Any]) -> str:
    if manifest.get("artifact_kind") != "RESEARCH_DIAGNOSTIC_NOT_ACCEPTED_STATE":
        raise ScorecardError("source_artifact_kind_invalid")
    if manifest.get("research_only") is not True or manifest.get("manager_skill_rank_built") is not False:
        raise ScorecardError("source_manifest_boundary_invalid")
    evidence_id = str(manifest.get("evidence_id") or "").strip()
    if not evidence_id:
        raise ScorecardError("source_evidence_id_missing")
    return evidence_id


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def publish_immutable(output_dir: Path, result: Mapping[str, Any], metadata: Mapping[str, Any]) -> dict[str, Any]:
    output_dir = Path(output_dir)
    if output_dir.is_symlink() or any(p.is_symlink() for p in output_dir.parents):
        raise ScorecardError("symlink_output_forbidden")
    files = {"manager_event_scorecards.json": json_bytes(dict(result))}
    manifest = {
        **dict(metadata),
        "artifact_kind": "RESEARCH_DIAGNOSTIC_NOT_ACCEPTED_STATE",
        "research_only": True,
        "event_study_not_account_nav": True,
        "continuous_clone_nav_built": False,
        "manager_skill_rank_built": False,
        "outcome_overlap_adjusted": False,
        "portfolio_target_changed": False,
        "automatic_trade_allowed": False,
        "production_promotion_allowed": False,
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())},
    }
    files["manifest.json"] = json_bytes(manifest)
    if output_dir.exists():
        if not output_dir.is_dir() or {p.name for p in output_dir.iterdir()} != set(files):
            raise ScorecardError("existing_output_incomplete_or_different")
        for name, raw in files.items():
            path = output_dir / name
            if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
                raise ScorecardError("existing_output_hash_or_content_mismatch")
        return {**manifest, "publication": "IDENTICAL_RERUN_VERIFIED"}
    output_dir.mkdir(parents=True, exist_ok=False)
    for name in ("manager_event_scorecards.json", "manifest.json"):
        with (output_dir / name).open("xb") as stream:
            stream.write(files[name]); stream.flush(); os.fsync(stream.fileno())
    return {**manifest, "publication": "NEW_LOCAL_DIAGNOSTIC"}


def evaluate(event_evidence: pd.DataFrame, source_manifest: Mapping[str, Any], config_value: Mapping[str, Any], decision_cutoff: str) -> dict[str, Any]:
    source_id = validate_source_manifest(source_manifest)
    config = config_from_json(config_value)
    return build_manager_event_scorecards(event_evidence.to_dict(orient="records"), decision_cutoff=decision_cutoff, source_evidence_id=source_id, config=config)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--event-evidence", required=True)
    p.add_argument("--source-manifest", required=True)
    p.add_argument("--config", default="configs/research/sec_13f_manager_event_scorecard_v1.json")
    p.add_argument("--decision-cutoff", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args(argv)
    try:
        event_path = Path(args.event_evidence); event_path = event_path if event_path.is_absolute() else REPO_ROOT / event_path
        manifest_path = Path(args.source_manifest); manifest_path = manifest_path if manifest_path.is_absolute() else REPO_ROOT / manifest_path
        config_path = Path(args.config); config_path = config_path if config_path.is_absolute() else REPO_ROOT / config_path
        output = Path(args.output_dir); output = output if output.is_absolute() else REPO_ROOT / output
        result = evaluate(read_table(event_path), read_json(manifest_path), read_json(config_path), args.decision_cutoff)
        manifest = publish_immutable(output, result, {
            "decision_cutoff": result["decision_cutoff"],
            "scorecard_evidence_id": result.get("scorecard_evidence_id", ""),
            "event_evidence_sha256": hashlib.sha256(event_path.read_bytes()).hexdigest(),
            "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        })
        print(json.dumps({"status": result["status"], "publication": manifest["publication"], "scorecards": len(result["scorecards"]), "research_only": True}))
        return 0 if result["scorecards"] else 2
    except (ScorecardError, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status":"BLOCKED_INTEGRITY","reason":str(exc),"accepted_publication":False}), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())

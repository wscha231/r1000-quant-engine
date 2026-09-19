"""Use the existing M0-A evaluator through the exact offline compute runtime.

This is a compute/transport integration, NOT a new strategy/backtest. Input
plans and local cache are trusted private workspace material. No API, broker,
Drive, scheduler or accepted 'latest' is touched. CLI has no arbitrary callbacks.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from . import mission_metrics as metrics
from .compute_runtime import (MAX_PLAN_BYTES, ComputeError, Operator, Task, canonical, need,
                              run, safe_file, sha, shard_ids, join_shards)

PLAN_SCHEMA = "mission-v3-compute-plan-v1"


def precheck(inputs: dict[str, bytes], params: dict[str, Any]) -> bytes:
    need(set(inputs) == {"bundle"} and not params, "PRECHECK_INPUTS")
    # Actual reuse of #460. No alternate CAGR/MDD implementation.
    result = metrics.assess_pair(metrics.strict_json(inputs["bundle"].decode("utf-8")))
    return canonical(result)


def collect(inputs: dict[str, bytes], params: dict[str, Any]) -> bytes:
    need(set(params) == {"title"} and type(params["title"]) is str, "REPORT_PARAMETERS")
    reports = {}
    for identity, blob in sorted(inputs.items()):
        row = json.loads(blob)
        need(row.get("mission_status") == "NOT_PROVEN" and
             row.get("orders_allowed") is False and
             row.get("production_promotion_allowed") is False, "UPSTREAM_AUTHORITY")
        reports[identity] = {"output_sha256": sha(blob), "numeric_status": row["numeric_status"]}
    return canonical({"schema_version": "mission-v3-compute-report-v1",
                      "title": params["title"], "reports": reports,
                      "authority": "RESEARCH_ONLY", "mission_status": "NOT_PROVEN",
                      "orders_allowed": False, "production_promotion_allowed": False})


def operators() -> dict[str, Operator]:
    # -m uses __main__; spawn must import canonical callables, not __mp_main__.
    from importlib import import_module
    module = import_module("research_only.mission_v3.compute_m0")
    return {
        "m0_precheck": Operator("m0_precheck", module.precheck,
                               (("mission_metrics", str(Path(metrics.__file__))),)),
        "collect_prechecks": Operator("collect_prechecks", module.collect),
    }


def build_tasks(plan: dict[str, Any], blobs: dict[str, bytes]) -> list[Task]:
    need(type(plan) is dict and set(plan) == {
        "schema_version", "universe_ids", "decision_cutoff", "entries", "report_title"}, "PLAN_KEYS")
    need(plan["schema_version"] == PLAN_SCHEMA, "PLAN_SCHEMA")
    need(type(plan["entries"]) is list and 1 <= len(plan["entries"]) <= 128, "PLAN_ENTRIES")
    # The full ID list is kept in the plan; worker count never changes membership.
    universe = join_shards(plan["universe_ids"], shard_ids(plan["universe_ids"], 8))
    context = {"decision_cutoff": plan["decision_cutoff"], "universe_sha256": sha(canonical(universe))}
    ids = []
    tasks = []
    for row in plan["entries"]:
        need(type(row) is dict and set(row) == {"id", "path", "sha256"}, "ENTRY_KEYS")
        identity = row["id"]
        need(type(identity) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,70}", identity)
             is not None and identity not in ids, "ENTRY_ID")
        need(identity in blobs and type(blobs[identity]) is bytes and
             sha(blobs[identity]) == row["sha256"], "BUNDLE_HASH_MISMATCH")
        ids.append(identity)
        tasks.append(Task("m0:" + identity, "m0_precheck", {"bundle": blobs[identity]}, {}, {}, context))
    need(set(blobs) == set(ids), "BUNDLE_SET_MISMATCH")
    tasks.append(Task("report", "collect_prechecks", {}, {"title": plan["report_title"]},
                      {identity: "m0:" + identity for identity in sorted(ids)}, context))
    return tasks


def load_plan(path: Path, expected_sha256: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    raw = safe_file(path)
    need(type(expected_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
         is not None and sha(raw) == expected_sha256, "PLAN_PIN_MISMATCH")
    # strict parser rejects duplicate keys/NaN/huge structures; build_tasks checks types.
    plan = metrics.strict_json(raw.decode("utf-8"))
    need(type(plan) is dict and type(plan.get("entries")) is list
         and len(plan["entries"]) <= 128, "PLAN_ENTRIES")
    blobs = {}
    total = 0
    for row in plan["entries"]:
        need(type(row) is dict and type(row.get("path")) is str and type(row.get("id")) is str, "ENTRY_KEYS")
        name = row["path"]
        need(re.fullmatch(r"[a-z0-9_./-]{1,180}", name) is not None, "UNSAFE_INPUT_PATH")
        rel = PurePosixPath(name)
        need(not rel.is_absolute() and ".." not in name.split("/")
             and all(part not in {"", "."} for part in name.split("/")), "UNSAFE_INPUT_PATH")
        need(row["id"] not in blobs, "ENTRY_ID")
        need(total < MAX_PLAN_BYTES, "PLAN_INPUT_SIZE")
        blobs[row["id"]] = safe_file(path.parent / Path(*rel.parts), min(metrics.MAX_INPUT_BYTES, MAX_PLAN_BYTES - total))
        total += len(blobs[row["id"]])
    build_tasks(plan, blobs)
    return plan, blobs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("plan", type=Path)
    p.add_argument("--plan-sha256", required=True)
    p.add_argument("--cache-dir", type=Path, required=True)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--workers", type=int, default=1, choices=[1, 2, 4])
    args = p.parse_args(argv)
    # New directory only; never overwrite a previous run or accepted output.
    try:
        need(not args.run_dir.exists() and not args.run_dir.is_symlink(), "RUN_DIR_EXISTS")
        need(not any(p.is_symlink() for p in args.run_dir.absolute().parents), "SYMLINK_RUN_PARENT")
        plan, blobs = load_plan(args.plan, args.plan_sha256)
        result = run(build_tasks(plan, blobs), operators(), args.cache_dir, workers=args.workers)
        args.run_dir.mkdir(parents=True, exist_ok=False)
        outputs = result.pop("outputs")
        (args.run_dir / "execution_receipt.json").write_bytes(canonical(result))
        if result["status"] == "COMPLETE":
            (args.run_dir / "report.json").write_bytes(outputs["report"])
        manifest = {f.name: {"size": f.stat().st_size, "sha256": sha(f.read_bytes())}
                    for f in sorted(args.run_dir.iterdir()) if f.is_file()}
        (args.run_dir / "manifest.json").write_bytes(canonical(manifest))
        print(json.dumps({"status": result["status"], "stats": result["stats"],
                          "semantic_output_hash": result["semantic_output_hash"],
                          "mission_status": "NOT_PROVEN", "orders_allowed": False}, sort_keys=True))
        return 0 if result["status"] == "COMPLETE" else 2
    except (ComputeError, metrics.InputError, UnicodeError, OSError) as exc:
        print(json.dumps({"status": "INVALID_INPUT", "error_type": type(exc).__name__,
                          "mission_status": "NOT_PROVEN", "orders_allowed": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

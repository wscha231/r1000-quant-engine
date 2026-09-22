#!/usr/bin/env python3
"""A0-facing CLI for Candidate Lifecycle V1.

No network access, no scheduler, no target/ledger/order writes. The CLI only
reads explicit JSON inputs and writes research-only JSON outputs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research"))

from candidate_lifecycle_v1 import (  # noqa: E402
    admit_event,
    build_a5_candidate_view,
    empty_candidate_registry,
    empty_event_registry,
    plan_delta_refresh,
    upsert_candidate,
)


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def artifact_resolver(manifest_path: str | Path):
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("artifacts"), dict):
        raise SystemExit("artifact manifest must contain an artifacts object")
    base = Path(manifest_path).resolve().parent
    mapping = manifest["artifacts"]

    def resolve(artifact_id: str, sha256: str) -> bytes:
        row = mapping.get(artifact_id)
        if not isinstance(row, dict):
            raise KeyError(artifact_id)
        if row.get("sha256") != sha256:
            raise ValueError("manifest sha mismatch")
        raw_path = Path(row.get("path", ""))
        path = raw_path if raw_path.is_absolute() else base / raw_path
        return path.read_bytes()

    return resolve


def cmd_admit_event(args: argparse.Namespace) -> int:
    registry = load_json(args.registry) if args.registry else empty_event_registry(args.cutoff)
    event = load_json(args.event)
    out, receipt = admit_event(registry, event, args.cutoff)
    write_json(args.output, out)
    if args.receipt:
        write_json(args.receipt, receipt)
    return 0


def cmd_plan_refresh(args: argparse.Namespace) -> int:
    previous = load_json(args.previous)
    current = load_json(args.current)
    event = load_json(args.event) if args.event else None
    out = plan_delta_refresh(
        previous,
        current,
        event=event,
        integrity_break=args.integrity_break,
    )
    write_json(args.output, out)
    return 0


def cmd_upsert_candidate(args: argparse.Namespace) -> int:
    registry = load_json(args.registry) if args.registry else empty_candidate_registry(args.cutoff)
    record = load_json(args.record)
    out = upsert_candidate(registry, record, args.cutoff)
    write_json(args.output, out)
    return 0


def cmd_a5_view(args: argparse.Namespace) -> int:
    registry = load_json(args.registry)
    resolver = artifact_resolver(args.artifact_manifest)
    out = build_a5_candidate_view(registry, args.asset_id, resolver)
    write_json(args.output, out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("admit-event", help="admit/deduplicate one A2 handoff")
    p.add_argument("--event", required=True)
    p.add_argument("--registry")
    p.add_argument("--cutoff", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--receipt")
    p.set_defaults(func=cmd_admit_event)

    p = sub.add_parser("plan-refresh", help="compute minimum A3 refresh scope")
    p.add_argument("--previous", required=True)
    p.add_argument("--current", required=True)
    p.add_argument("--event")
    p.add_argument("--integrity-break", action="store_true")
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_plan_refresh)

    p = sub.add_parser("upsert-candidate", help="replace the one current candidate record")
    p.add_argument("--record", required=True)
    p.add_argument("--registry")
    p.add_argument("--cutoff", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_upsert_candidate)

    p = sub.add_parser("build-a5-view", help="create hash-bound research-only A5 input")
    p.add_argument("--registry", required=True)
    p.add_argument("--asset-id", required=True)
    p.add_argument("--artifact-manifest", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_a5_view)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

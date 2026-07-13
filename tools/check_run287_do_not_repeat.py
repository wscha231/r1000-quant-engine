#!/usr/bin/env python3
"""Fail-closed preflight for duplicate Run287 research candidates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = REPO_ROOT / "docs" / "run287_do_not_repeat_registry.json"


def normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("entries"), list):
        raise ValueError("registry entries must be a list")
    return payload


def evaluate_candidate(
    registry: dict[str, Any],
    *,
    signal: str,
    mechanism: str,
    book: str,
    window: str,
    component_coverage_increase_pp: float = 0.0,
    semantics_changed: bool = False,
    change_note: str = "",
) -> dict[str, Any]:
    candidate = {
        "signal": normalize(signal),
        "mechanism": normalize(mechanism),
        "book": normalize(book),
        "window": normalize(window),
    }
    match_fields = list(registry.get("match_fields") or candidate.keys())
    matches: list[dict[str, Any]] = []
    for entry in registry.get("entries") or []:
        if not entry.get("blocked_reuse", False):
            continue
        if all(normalize(entry.get(field)) == candidate.get(field, "") for field in match_fields):
            matches.append(entry)

    policy = registry.get("reuse_policy") or {}
    coverage_floor = float(policy.get("minimum_component_coverage_increase_pp", 5.0))
    coverage_delta = float(component_coverage_increase_pp)
    semantic_override = bool(semantics_changed and str(change_note).strip())
    if not matches:
        status = "ALLOWED_NEW_COMBINATION"
        allowed = True
        reason = "no exact signal+mechanism+book+window match"
    elif coverage_delta >= coverage_floor:
        status = "ALLOWED_COVERAGE_CHANGE"
        allowed = True
        reason = f"component coverage increased by at least {coverage_floor:.1f}pp"
    elif semantic_override:
        status = "ALLOWED_SEMANTIC_CHANGE"
        allowed = True
        reason = "explicit semantic or application-mechanism change supplied"
    else:
        status = "BLOCKED_DO_NOT_REPEAT"
        allowed = False
        reason = "exact rejected combination without sufficient coverage or semantic change"
    return {
        "schema_version": "run287-do-not-repeat-preflight-v1",
        "status": status,
        "allowed": allowed,
        "reason": reason,
        "candidate": candidate,
        "coverage_increase_pp": coverage_delta,
        "coverage_override_floor_pp": coverage_floor,
        "semantics_changed": bool(semantics_changed),
        "change_note": str(change_note).strip(),
        "matched_entry_ids": [str(entry.get("id") or "") for entry in matches],
        "matched_entries": matches,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--signal", required=True)
    parser.add_argument("--mechanism", required=True)
    parser.add_argument("--book", required=True)
    parser.add_argument("--window", required=True)
    parser.add_argument("--component-coverage-increase-pp", type=float, default=0.0)
    parser.add_argument("--semantics-changed", action="store_true")
    parser.add_argument("--change-note", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = evaluate_candidate(
        load_registry(Path(args.registry)),
        signal=args.signal,
        mechanism=args.mechanism,
        book=args.book,
        window=args.window,
        component_coverage_increase_pp=args.component_coverage_increase_pp,
        semantics_changed=bool(args.semantics_changed),
        change_note=args.change_note,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

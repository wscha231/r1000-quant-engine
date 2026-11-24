#!/usr/bin/env python3
"""Detect the next missing NYSE paper session before expensive daily work.

Consume only a previously verified immutable-head selection receipt.  This
preflight never repairs paper state, chooses securities, approves a target,
executes orders, fetches prices, or grants catch-up authority.  A missing or
unverifiable remote head fails closed rather than accepting a cache date.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "run287-paper-gap-preflight-v1"
SELECTION_SCHEMA = "run287-paper-immutable-head-selection-v1"
SELECTION_STATUS = "VERIFIED_LINEAR_IMMUTABLE_PAPER_HEAD_SELECTED"
SELECTION_KEYS = frozenset({
    "schema_version", "status", "heads_root", "immutable_head_count",
    "root_snapshot_hash", "terminal_snapshot_hash", "selected_snapshot_hash",
    "selected_head_dir", "selected_as_of_date", "chain_snapshot_hashes",
})
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def canonical_date(raw: object) -> date:
    if not isinstance(raw, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise ValueError("date_not_canonical")
    result = date.fromisoformat(raw)
    if result.isoformat() != raw:
        raise ValueError("date_not_canonical")
    return result


def verified_frontier(selection: object, remote_head: str) -> tuple[date, str, int]:
    """Validate the receipt structure; byte/lineage verification is upstream."""
    if not isinstance(selection, dict) or set(selection) != SELECTION_KEYS:
        raise ValueError("selection_schema_fields")
    if (selection["schema_version"] != SELECTION_SCHEMA
            or selection["status"] != SELECTION_STATUS):
        raise ValueError("selection_not_verified")
    count = selection["immutable_head_count"]
    chain = selection["chain_snapshot_hashes"]
    if (type(count) is not int or count <= 0 or not isinstance(chain, list)
            or len(chain) != count or any(not isinstance(h, str) or not SHA256.fullmatch(h) for h in chain)
            or len(set(chain)) != count):
        raise ValueError("head_chain_invalid")
    if (selection["root_snapshot_hash"] != chain[0]
            or selection["terminal_snapshot_hash"] != chain[-1]
            or selection["selected_snapshot_hash"] != chain[-1]
            or not isinstance(remote_head, str)
            or not SHA256.fullmatch(remote_head)
            or remote_head != chain[-1]):
        raise ValueError("remote_head_mismatch")
    if (not isinstance(selection["heads_root"], str)
            or not selection["heads_root"].startswith("/")
            or not isinstance(selection["selected_head_dir"], str)
            or selection["selected_head_dir"] != str(Path(selection["heads_root"]) / chain[-1])):
        raise ValueError("head_receipt_paths_invalid")
    return canonical_date(selection["selected_as_of_date"]), chain[-1], count


def assess(
    *,
    selection: object,
    remote_head: str,
    requested_session: str,
    completed_sessions: Iterable[str],
    durable_ready: bool,
) -> dict[str, Any]:
    if durable_ready is not True:
        raise ValueError("remote_readback_not_verified")
    prior, head, count = verified_frontier(selection, remote_head)
    requested = canonical_date(requested_session)
    sessions = [canonical_date(value) for value in completed_sessions]
    if sessions != sorted(set(sessions)):
        raise ValueError("NYSE_calendar_not_strictly_ordered")
    if requested < prior:
        status, missing, next_session = "BLOCKED_REQUEST_BEFORE_PAPER", [], None
    elif requested == prior:
        status, missing, next_session = "ALREADY_AT_REQUESTED_SESSION", [], None
    else:
        if not sessions or sessions[-1] != requested:
            raise ValueError("requested_session_not_completed_NYSE")
        if sessions[0] <= prior or any(s <= prior or s > requested for s in sessions):
            raise ValueError("NYSE_grid_outside_gap")
        missing = [s.isoformat() for s in sessions]
        next_session = missing[0]
        status = "READY_EXACT_SUCCESSOR" if len(missing) == 1 else "BLOCKED_SESSION_GAP"
    return {
        "schema_version": SCHEMA,
        "status": status,
        "paper_as_of": prior.isoformat(),
        "requested_session": requested.isoformat(),
        "next_missing_session": next_session,
        "missing_nyse_session_count": len(missing),
        "immutable_head_count": count,
        "verified_remote_terminal_sha256": head,
        "read_only": True,
        "paper_ledger_mutated": False,
        "actual_broker_consulted": False,
        "target_mutated": False,
        "trade_authorization_granted": False,
        "catchup_evidence_admitted": False,
        "owner_scope_attestation_verified": False,
    }


def nyse_sessions(prior_date: date, requested: date) -> list[str]:
    """Use the existing exchange calendar; weekends-only arithmetic is unsafe."""
    if requested <= prior_date:
        return []
    import pandas_market_calendars as mcal
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=(prior_date + timedelta(days=1)).isoformat(),
        end_date=requested.isoformat(),
    )
    return [day.strftime("%Y-%m-%d") for day in schedule.index]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".paper_gap_", delete=False,
    ) as temp:
        name = temp.name
        json.dump(payload, temp, indent=2, sort_keys=True)
        temp.write("\n")
    os.replace(name, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--requested-session", required=True)
    parser.add_argument("--remote-terminal-sha256", default="")
    parser.add_argument("--durable-ready", choices=("yes", "no"), default="no")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        selection = json.loads(args.selection.read_text(encoding="utf-8"))
        prior, _, _ = verified_frontier(selection, args.remote_terminal_sha256)
        requested = canonical_date(args.requested_session)
        result = assess(
            selection=selection,
            remote_head=args.remote_terminal_sha256,
            requested_session=args.requested_session,
            completed_sessions=nyse_sessions(prior, requested),
            durable_ready=args.durable_ready == "yes",
        )
    except (ValueError, TypeError, OSError, json.JSONDecodeError, ImportError):
        result = {
            "schema_version": SCHEMA,
            "status": "BLOCKED_UNVERIFIED_PAPER_FRONTIER_OR_CALENDAR",
            "paper_as_of": None,
            "requested_session": args.requested_session,
            "next_missing_session": None,
            "missing_nyse_session_count": None,
            "read_only": True,
            "paper_ledger_mutated": False,
            "target_mutated": False,
            "trade_authorization_granted": False,
        }
    write_json(args.output, result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {
        "READY_EXACT_SUCCESSOR", "ALREADY_AT_REQUESTED_SESSION"
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())

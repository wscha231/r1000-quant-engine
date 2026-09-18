#!/usr/bin/env python3
"""CLI for the research-only News Event Alpha V1 runtime.

The CLI accepts a normalized historical/forward event stream plus explicit NYSE
session rows and total-return price rows. It writes an append-only event ledger
and research artifacts only. It does not touch selector weights, target books,
orders, paper/actual broker ledgers, or model promotion state.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.news_event_alpha_v1.runtime import (  # noqa: E402
    ContractError,
    SAMPLE_ORIGINS,
    canonical_bytes,
    digest,
    normalize_events,
    run_payload,
)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_scalar(value: str) -> Any:
    raw = value.strip()
    if raw == "":
        return None
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    if raw.startswith("[") or raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def load_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        rows = []
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ContractError(f"invalid JSONL {path}:{lineno}") from exc
            if not isinstance(item, dict):
                raise ContractError(f"JSONL row must be object: {path}:{lineno}")
            rows.append(item)
        return rows
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            return payload["rows"]
        raise ContractError(f"JSON must be a list or {{rows:[...]}}: {path}")
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [
                {k: _parse_scalar(v) for k, v in row.items()}
                for row in csv.DictReader(handle)
            ]
    raise ContractError(f"unsupported input format: {path}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return value


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                columns.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in columns})


def merge_immutable_ledger(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append new economic events while refusing historical mutation."""
    by_id: dict[str, dict[str, Any]] = {}
    for row in existing:
        key = str(row.get("economic_event_id") or "")
        if not key:
            raise ContractError("existing ledger row missing economic_event_id")
        by_id[key] = row
    for row in incoming:
        key = str(row["economic_event_id"])
        previous = by_id.get(key)
        if previous is None:
            by_id[key] = row
            continue
        if digest(previous) != digest(row):
            raise ContractError(f"immutable event conflict: {key}")
    return sorted(by_id.values(), key=lambda r: (str(r["available_at"]), str(r["economic_event_id"])))


def force_origin(rows: list[dict[str, Any]], origin: str) -> list[dict[str, Any]]:
    if origin not in SAMPLE_ORIGINS:
        raise ContractError(f"unsupported mode/origin: {origin}")
    out = []
    for row in rows:
        item = dict(row)
        item["sample_origin"] = origin
        out.append(item)
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--events", required=True, help="Normalized event .jsonl/.json/.csv")
    p.add_argument("--prices", required=True, help="Total-return price rows .jsonl/.json/.csv")
    p.add_argument("--market-sessions", required=True, help="Explicit NYSE session/market_close_utc rows")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--mode", choices=sorted(SAMPLE_ORIGINS), required=True)
    p.add_argument("--existing-ledger", default="", help="Optional prior event_ledger.jsonl")
    p.add_argument("--benchmark", default="SPY")
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--report-checkpoint", type=int, default=5, choices=[0, 5, 10, 20])
    p.add_argument("--promotion-checkpoint", type=int, default=5, choices=[5, 10, 20])
    p.add_argument("--source-commit", default="", help="Exact repository SHA used to build inputs")
    p.add_argument("--data-receipt-sha256", default="", help="Verified data receipt/catalog hash when available")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    event_path = Path(args.events)
    price_path = Path(args.prices)
    session_path = Path(args.market_sessions)
    output_dir = Path(args.output_dir)

    if args.mode == "HISTORICAL_BACKFILL":
        if not args.source_commit or len(args.source_commit.strip()) < 7:
            raise ContractError("HISTORICAL_BACKFILL requires --source-commit")
        receipt = args.data_receipt_sha256.strip().lower()
        if len(receipt) != 64 or any(c not in "0123456789abcdef" for c in receipt):
            raise ContractError("HISTORICAL_BACKFILL requires a verified 64-hex --data-receipt-sha256")

    incoming_raw = force_origin(load_rows(event_path), args.mode)
    incoming = normalize_events(incoming_raw)
    existing: list[dict[str, Any]] = []
    existing_path = Path(args.existing_ledger) if args.existing_ledger else None
    if existing_path is not None and existing_path.exists():
        existing = load_rows(existing_path)
    ledger = merge_immutable_ledger(existing, incoming)

    prices = load_rows(price_path)
    sessions = load_rows(session_path)
    payload = {
        "schema": "news-event-alpha-v1",
        "events": ledger,
        "prices": prices,
        "market_sessions": sessions,
        "benchmark_id": args.benchmark,
        "report_top_n": args.top_n,
        "report_checkpoint": args.report_checkpoint,
        "promotion_checkpoint": args.promotion_checkpoint,
    }
    result = run_payload(payload)

    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = output_dir / "event_ledger.jsonl"
    features_path = output_dir / "checkpoint_features.csv"
    outcomes_path = output_dir / "forward_outcomes.csv"
    summary_path = output_dir / "impact_summary.csv"
    proposal_path = output_dir / "challenger_proposal.json"
    top_path = output_dir / "top_current_events.json"

    write_jsonl(ledger_path, ledger)
    write_csv(features_path, result["checkpoint_rows"])
    write_csv(outcomes_path, result["outcomes"])
    write_csv(summary_path, result["impact_summaries"])
    write_json(proposal_path, result["challenger_proposal"])
    write_json(top_path, result["top_current_events"])

    artifacts = [ledger_path, features_path, outcomes_path, summary_path, proposal_path, top_path]
    manifest = {
        "schema": "news-event-alpha-manifest-v1",
        "mode": args.mode,
        "research_only": True,
        "selector_eligible": False,
        "production_activation_allowed": False,
        "automatic_promotion_allowed": False,
        "source_commit": args.source_commit or None,
        "data_receipt_sha256": args.data_receipt_sha256 or None,
        "benchmark": args.benchmark.upper(),
        "input_hashes": {
            "events": file_sha256(event_path),
            "prices": file_sha256(price_path),
            "market_sessions": file_sha256(session_path),
            "existing_ledger": file_sha256(existing_path) if existing_path is not None and existing_path.exists() else None,
        },
        "counts": {
            "incoming_normalized_events": len(incoming),
            "ledger_events": len(ledger),
            "checkpoint_rows": len(result["checkpoint_rows"]),
            "resolved_outcomes": result["resolved_outcome_count"],
            "impact_summaries": len(result["impact_summaries"]),
            "top_reported_events": len(result["top_current_events"]),
        },
        "outputs": {p.name: {"sha256": file_sha256(p), "bytes": p.stat().st_size} for p in artifacts},
        "challenger_status": result["challenger_proposal"]["status"],
        "result_sha256": result["result_sha256"],
    }
    write_json(output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

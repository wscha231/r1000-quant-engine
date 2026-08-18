#!/usr/bin/env python3
"""Verify an immutable SEC/Smart Money artifact against its triggering workflow identity."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def verify(
    *,
    kind: str,
    manifest: dict[str, Any],
    filings_index: Path,
    holdings: Path,
    form4: Path | None = None,
    etf: Path | None = None,
    expected_run_id: str,
    expected_head_sha: str,
    expected_head_branch: str,
) -> dict[str, Any]:
    if kind == "sec":
        identity = manifest.get("source_identity") or {}
        freshness = manifest
    elif kind == "smart":
        identity = manifest.get("publication_identity") or {}
        freshness = manifest.get("13f_freshness") or {}
    else:
        raise ValueError(f"unsupported publication kind: {kind}")

    failures: list[str] = []
    expected_identity = {
        "workflow_run_id": str(expected_run_id),
        "head_sha": str(expected_head_sha).lower(),
        "head_branch": str(expected_head_branch),
    }
    observed_identity = {
        "workflow_run_id": str(identity.get("workflow_run_id") or ""),
        "head_sha": str(identity.get("head_sha") or "").lower(),
        "head_branch": str(identity.get("head_branch") or ""),
    }
    for key, expected in expected_identity.items():
        if not expected or observed_identity.get(key) != expected:
            failures.append(f"identity_mismatch:{key}")
    if not bool(freshness.get("freshness_ready")):
        failures.append("freshness_not_ready")
    if not bool(freshness.get("parsed_holdings_required")):
        failures.append("parsed_holdings_not_required")
    if not filings_index.exists():
        failures.append("filings_index_missing")
        filings_sha = ""
    else:
        filings_sha = sha256_file(filings_index)
        if filings_sha != str(freshness.get("filings_index_sha256") or "").lower():
            failures.append("filings_index_sha256_mismatch")
    if not holdings.exists():
        failures.append("holdings_missing")
        holdings_sha = ""
    else:
        holdings_sha = sha256_file(holdings)
        if holdings_sha != str(freshness.get("holdings_sha256") or "").lower():
            failures.append("holdings_sha256_mismatch")
    evidence_hashes: dict[str, str] = {}
    if kind == "smart":
        expected_evidence = manifest.get("evidence_sha256") or {}
        for label, path in [("form4", form4), ("etf", etf)]:
            if path is None or not path.exists():
                evidence_hashes[label] = ""
                failures.append(f"{label}_evidence_missing")
                continue
            observed_hash = sha256_file(path)
            evidence_hashes[label] = observed_hash
            if observed_hash != str(expected_evidence.get(label) or "").lower():
                failures.append(f"{label}_evidence_sha256_mismatch")
    return {
        "schema_version": "sec-13f-publication-verification-v2",
        "status": "ready" if not failures else "blocked",
        "kind": kind,
        "expected_identity": expected_identity,
        "observed_identity": observed_identity,
        "filings_index_sha256": filings_sha,
        "holdings_sha256": holdings_sha,
        "evidence_sha256": evidence_hashes,
        "failures": failures,
        "research_only": True,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["sec", "smart"], required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--filings-index", required=True)
    parser.add_argument("--holdings", required=True)
    parser.add_argument("--form4", default="")
    parser.add_argument("--etf", default="")
    parser.add_argument("--expected-run-id", required=True)
    parser.add_argument("--expected-head-sha", required=True)
    parser.add_argument("--expected-head-branch", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    payload = verify(
        kind=args.kind,
        manifest=load_object(Path(args.manifest)),
        filings_index=Path(args.filings_index),
        holdings=Path(args.holdings),
        form4=Path(args.form4) if args.form4 else None,
        etf=Path(args.etf) if args.etf else None,
        expected_run_id=str(args.expected_run_id),
        expected_head_sha=str(args.expected_head_sha),
        expected_head_branch=str(args.expected_head_branch),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 2 if args.strict and payload["status"] != "ready" else 0


if __name__ == "__main__":
    raise SystemExit(main())

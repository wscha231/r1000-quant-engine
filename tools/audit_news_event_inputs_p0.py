#!/usr/bin/env python3
"""Read-only integrity audit, or explicitly synthetic/reviewed label computation.

No network, Drive writes, training, target, broker, scheduler or promotion.
Default checks ONLY the input bytes/graph. Reviewed computation needs a separate
approval in the pinned repository registry, which ships empty intentionally.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from research.news_event_alpha_v1.admission import (verify_bundle, require_reviewed_receipt, json_load, sha256, read_bounded)
from research.news_event_alpha_v1.execution import attach_executable_outcomes
from research.news_event_alpha_v1.runtime import canonical_bytes, ContractError

# This is a code-reviewed authority map, never supplied by the market-data bundle.
# Empty means no real inputs were certified by this patch.
REVIEWED_REGISTRY = {"schema": "news-input-approval-registry-p0.2", "approvals": []}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle", required=True, type=Path)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--synthetic-only", action="store_true")
    mode.add_argument("--compute-reviewed", action="store_true")
    p.add_argument("--review-receipt", type=Path)
    p.add_argument("--expected-parent", default=None)
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args(argv)
    now = datetime.now(timezone.utc).isoformat()
    b = verify_bundle(args.bundle, now=now)
    report = dict(b.report)
    consumer_paths = ["research/news_event_alpha_v1/runtime.py", "research/news_event_alpha_v1/admission.py",
                      "research/news_event_alpha_v1/execution.py", "tools/audit_news_event_inputs_p0.py"]
    report["consumer_source_hashes"] = {rel: sha256((ROOT/rel).read_bytes()) for rel in consumer_paths}
    report.update(checked_at=now, historical_training_run=False, selector_changed=False,
                  portfolio_changed=False, orders_generated=False, drive_publication=False)
    if args.synthetic_only or args.compute_reviewed:
        if args.output_dir is None:
            raise ContractError("OUTPUT_DIR_REQUIRED")
        out = args.output_dir.resolve()
        if out == args.bundle.resolve() or out.is_relative_to(args.bundle.resolve()):
            raise ContractError("OUTPUT_MUST_NOT_MUTATE_INPUT_BUNDLE")
        if any((a / ".git").exists() for a in (out, *out.parents)):
            raise ContractError("OUTPUT_MUST_BE_OUTSIDE_GIT_WORKTREE")
        if args.synthetic_only:
            if b.manifest["origin"] != "SYNTHETIC_TEST":
                raise ContractError("SYNTHETIC_MODE_REJECTS_REAL_ORIGIN")
            report["authorization"] = "SYNTHETIC_TEST_ONLY"
        else:
            if args.review_receipt is None:
                raise ContractError("REVIEW_RECEIPT_REQUIRED")
            authorization = require_reviewed_receipt(
                b, read_bounded(args.review_receipt), reviewed_registry=REVIEWED_REGISTRY,
                expected_parent=args.expected_parent, now=now)
            report["authorization"] = authorization
        outcomes = attach_executable_outcomes(
            b.rows("snapshots"), b.rows("prices"), b.rows("sessions"),
            as_of=b.manifest["data_cutoff"], policy=b.json("policy"))
        counts = {}
        for r in outcomes:
            r["input_manifest_sha256"] = b.manifest_sha256
            r["input_origin"] = b.manifest["origin"]
            r["synthetic_only"] = args.synthetic_only
            # Add origin binding without retaining an obsolete content hash.
            r.pop("outcome_sha256", None)
            r["outcome_sha256"] = sha256(canonical_bytes(r))
            counts[r["outcome_status"]] = counts.get(r["outcome_status"],0) + 1
        data = b"".join(canonical_bytes(r) for r in outcomes)
        report.update(outcome_status_counts=counts, total_outcome_rows=len(outcomes),
                      output_sha256=sha256(data),
                      status="SYNTHETIC_LABEL_AUDIT_PASS" if args.synthetic_only else "REVIEWED_BOUNDED_LABEL_AUDIT_PASS")
        # Exclusive directory: never overwrite an earlier research output.
        out.mkdir(parents=True, exist_ok=False)
        with (out/"next_close_outcomes.jsonl").open("xb") as f: f.write(data)
        with (out/"LOCAL_AUDIT_REPORT.json").open("xb") as f: f.write(canonical_bytes(report))
        if sha256((out/"next_close_outcomes.jsonl").read_bytes()) != report["output_sha256"]:
            raise ContractError("LOCAL_OUTPUT_READBACK_FAILED")
    elif args.output_dir is not None or args.review_receipt is not None:
        raise ContractError("INSPECT_MODE_DOES_NOT_WRITE_OR_AUTHORIZE")
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ContractError, OSError, ValueError, KeyError, TypeError) as exc:
        # No raw market records, URL query strings or credentials printed here.
        print("BLOCKED: " + str(exc), file=sys.stderr)
        raise SystemExit(2)

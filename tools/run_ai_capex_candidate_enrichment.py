#!/usr/bin/env python3
"""Research-only AI capex candidate enrichment sidecar."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.ai_capex_taxonomy import enrich_frame, taxonomy_table  # noqa: E402

SCHEMA_VERSION = "ai-capex-candidate-enrichment-v1"
DEFAULT_OUTPUT_DIR = "outputs/ai_capex_candidate_enrichment"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def default_candidate_book(latest_run: Path) -> Path:
    candidates = [
        latest_run / "alphaops_vnext" / "candidate_replay_book.csv",
        latest_run / "candidate_replay_book.csv",
        latest_run / "r1000_candidate_lanes.csv",
        REPO_ROOT / "outputs" / "alphaops_vnext" / "candidate_replay_book.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def summarize(enriched: pd.DataFrame) -> dict[str, Any]:
    total = int(len(enriched))
    bucket_counts = (
        enriched.get("ai_capex_value_chain_bucket", pd.Series(dtype=str)).fillna("AI_OTHER").value_counts().to_dict()
        if total
        else {}
    )
    classified = total - int(bucket_counts.get("AI_OTHER", 0))
    high_bottleneck = int((pd.to_numeric(enriched.get("ai_capex_bottleneck_score"), errors="coerce").fillna(0.0) >= 0.5).sum()) if total else 0
    return {
        "row_count": total,
        "classified_count": classified,
        "classified_coverage": (classified / total) if total else 0.0,
        "high_bottleneck_count": high_bottleneck,
        "bucket_counts": bucket_counts,
        "source_confidence_counts": enriched.get("ai_capex_source_confidence", pd.Series(dtype=str)).fillna("missing").value_counts().to_dict()
        if total
        else {},
    }


def render_report(summary: dict[str, Any], output_csv: Path) -> str:
    lines = [
        "# AI Capex Candidate Enrichment",
        "",
        f"- Schema: `{SCHEMA_VERSION}`",
        f"- Status: `{summary.get('status')}`",
        f"- Research only: `{summary.get('research_only')}`",
        f"- Output: `{output_csv}`",
        f"- Rows: {summary.get('row_count', 0)}",
        f"- Classified coverage: {summary.get('classified_coverage', 0.0):.2%}",
        f"- High bottleneck rows: {summary.get('high_bottleneck_count', 0)}",
        "",
        "Bucket counts:",
        "",
    ]
    for bucket, count in sorted((summary.get("bucket_counts") or {}).items()):
        lines.append(f"- `{bucket}`: {count}")
    lines.extend(
        [
            "",
            "This sidecar does not modify `score_total`, weights, target books, production gates, or live trading.",
            "Known tickers in the taxonomy are seed examples only, not buy lists.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    candidate_book = repo_path(args.candidate_book) if args.candidate_book else default_candidate_book(latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source = read_csv(candidate_book)
    if source.empty:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked",
            "reason": "missing_or_empty_candidate_book",
            "candidate_book": str(candidate_book),
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "summary.json", payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    enriched = enrich_frame(source)
    out_csv = output_dir / "candidate_replay_book_ai_capex_enriched.csv"
    enriched.to_csv(out_csv, index=False)
    taxonomy_table().to_csv(output_dir / "taxonomy_table.csv", index=False)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "candidate_book": str(candidate_book),
        "output_csv": str(out_csv),
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_mutated": False,
        **summarize(enriched),
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload, out_csv), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build a research-only R1000 + ADR + validated-event membership registry.

This is a discovery/monitoring artifact, not a portfolio target. Form4 expansion
fails closed until a dedicated H1 validation receipt explicitly authorizes it.
13F expansion is labelled H2-manager-skill-pending.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from tools.candidate_universe_registry import (
    UniverseIntegrityError,
    aggregate_reasons,
    base_reasons,
    build_manifest,
    file_sha256,
    reasons_from_13f,
    reasons_from_form4,
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise UniverseIntegrityError("json_object_required")
    return value


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def build_from_inputs(
    *,
    r1000_tickers: list[str],
    adr_tickers: list[str],
    as_of: str,
    r1000_source_status: str,
    institutional_signals: pd.DataFrame | None = None,
    institutional_summary: dict[str, Any] | None = None,
    institutional_source_hash: str = "",
    form4_signals: pd.DataFrame | None = None,
    form4_validation: dict[str, Any] | None = None,
    form4_source_hash: str = "",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if r1000_source_status == "themes_fallback":
        raise UniverseIntegrityError("r1000_themes_fallback_not_acceptable_for_candidate_registry")
    reasons = base_reasons(r1000_tickers, adr_tickers, as_of=as_of)
    source_status: dict[str, Any] = {
        "r1000": r1000_source_status,
        "adr": "CURATED_BASE",
        "sec_13f": "MISSING",
        "form4": "BLOCKED_UNVERIFIED",
    }
    if institutional_signals is not None or institutional_summary is not None:
        if institutional_signals is None or institutional_summary is None:
            raise UniverseIntegrityError("13f_signal_and_summary_must_arrive_together")
        reasons.extend(
            reasons_from_13f(
                institutional_signals,
                institutional_summary,
                as_of=as_of,
                source_hash=institutional_source_hash,
            )
        )
        source_status["sec_13f"] = "H1_VERIFIED_H2_MANAGER_SKILL_PENDING"
    if form4_signals is not None or form4_validation is not None:
        if form4_signals is None or form4_validation is None:
            raise UniverseIntegrityError("form4_signal_and_validation_must_arrive_together")
        try:
            reasons.extend(
                reasons_from_form4(
                    form4_signals,
                    form4_validation,
                    as_of=as_of,
                    source_hash=form4_source_hash,
                )
            )
            source_status["form4"] = "VERIFIED_H1"
        except UniverseIntegrityError as exc:
            if str(exc) != "form4_source_not_h1_verified":
                raise
            source_status["form4"] = "BLOCKED_UNVERIFIED"
    reason_frame, universe = aggregate_reasons(reasons, as_of=as_of)
    queue = universe[
        [
            "ticker",
            "membership_reasons",
            "polarities",
            "base_member",
            "event_discovered",
            "risk_watch",
            "monitor_eligible",
            "candidate_scan_eligible",
            "event_only_risk_watch",
            "as_of",
        ]
    ].copy()
    queue["queue_class"] = "BASE_COVERAGE"
    queue.loc[queue["event_discovered"], "queue_class"] = "EVENT_REVIEW"
    queue.loc[queue["event_only_risk_watch"], "queue_class"] = "RISK_REVIEW_MONITOR_ONLY"
    queue["data_status"] = "REQUIRED_OR_REUSE_VERIFIED_CACHE"
    manifest = build_manifest(reason_frame, universe, as_of=as_of, source_status=source_status)
    return reason_frame, universe, queue, manifest


def write_artifact(
    output_dir: Path,
    reasons: pd.DataFrame,
    universe: pd.DataFrame,
    queue: pd.DataFrame,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise UniverseIntegrityError("output_dir_must_be_new_or_empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "membership_reasons.csv": reasons,
        "candidate_universe.csv": universe,
        "data_queue.csv": queue,
    }
    for name, frame in files.items():
        frame.to_csv(output_dir / name, index=False)
    manifest = dict(manifest)
    manifest["files"] = {name: file_sha256(output_dir / name) for name in files}
    manifest["status"] = "READY_RESEARCH_ONLY"
    manifest["selector_weight_changed"] = False
    manifest["portfolio_changed"] = False
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def resolve_live_inputs() -> tuple[list[str], list[str], str]:
    from aggressive.universe import load_adr_universe, load_universe

    r1000, meta = load_universe("r1000")
    if not r1000:
        raise UniverseIntegrityError("empty_r1000_base")
    adr, _ = load_adr_universe()
    return r1000, adr, str(meta.get("source_used") or "UNKNOWN")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--as-of", required=True)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument(
        "--institutional-signals",
        type=Path,
        default=Path("outputs/sec_institutional_signals/13f_latest.csv"),
    )
    p.add_argument(
        "--institutional-summary",
        type=Path,
        default=Path("outputs/sec_institutional_signals/institutional_signal_summary.json"),
    )
    p.add_argument(
        "--form4-signals",
        type=Path,
        default=Path("outputs/sec_ownership_signals/form4_latest.csv"),
    )
    p.add_argument(
        "--form4-validation",
        type=Path,
        default=Path("outputs/sec_ownership_signals/universe_source_validation.json"),
    )
    p.add_argument("--require-13f", action="store_true")
    args = p.parse_args(argv)
    try:
        r1000, adr, rstatus = resolve_live_inputs()
        inst = None
        inst_summary = None
        inst_hash = ""
        if args.institutional_signals.exists() and args.institutional_summary.exists():
            inst = _read_table(args.institutional_signals)
            inst_summary = _read_json(args.institutional_summary)
            inst_hash = hashlib.sha256(
                (file_sha256(args.institutional_signals) + file_sha256(args.institutional_summary)).encode()
            ).hexdigest()
        elif args.require_13f:
            raise UniverseIntegrityError("required_13f_inputs_missing")

        form4 = None
        form4_validation = None
        form4_hash = ""
        if args.form4_signals.exists() and args.form4_validation.exists():
            form4 = _read_table(args.form4_signals)
            form4_validation = _read_json(args.form4_validation)
            form4_hash = hashlib.sha256(
                (file_sha256(args.form4_signals) + file_sha256(args.form4_validation)).encode()
            ).hexdigest()

        reasons, universe, queue, manifest = build_from_inputs(
            r1000_tickers=r1000,
            adr_tickers=adr,
            as_of=args.as_of,
            r1000_source_status=rstatus,
            institutional_signals=inst,
            institutional_summary=inst_summary,
            institutional_source_hash=inst_hash,
            form4_signals=form4,
            form4_validation=form4_validation,
            form4_source_hash=form4_hash,
        )
        manifest = write_artifact(args.output_dir, reasons, universe, queue, manifest)
        print(
            json.dumps(
                {
                    "status": manifest["status"],
                    "monitor_tickers": manifest["monitor_tickers"],
                    "candidate_scan_tickers": manifest["candidate_scan_tickers"],
                    "source_status": manifest["source_status"],
                },
                sort_keys=True,
            )
        )
        return 0
    except (UniverseIntegrityError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"status": "BLOCKED_INTEGRITY", "reason": str(exc), "published": False},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Feed a verified candidate-universe artifact into the existing scanner.

This is research-only. Event membership changes candidate discovery/monitoring,
not selector weights, portfolio targets, or orders.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from tools.candidate_universe_registry import UniverseIntegrityError, file_sha256


def load_candidate_artifact(root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "READY_RESEARCH_ONLY" or manifest.get("research_only") is not True:
        raise UniverseIntegrityError("candidate_manifest_not_ready_research_only")
    if manifest.get("automatic_trade_allowed") is not False or manifest.get("portfolio_changed") is not False:
        raise UniverseIntegrityError("candidate_manifest_crossed_trade_boundary")
    expected = (manifest.get("files") or {}).get("candidate_universe.csv")
    if not expected or file_sha256(root / "candidate_universe.csv") != expected:
        raise UniverseIntegrityError("candidate_universe_hash_mismatch")
    frame = pd.read_csv(root / "candidate_universe.csv", low_memory=False)
    required = {
        "ticker",
        "candidate_scan_eligible",
        "risk_watch",
        "membership_reasons",
        "event_only_risk_watch",
    }
    if not required.issubset(frame.columns):
        raise UniverseIntegrityError("candidate_universe_columns_missing")
    return frame, manifest


def eligible_tickers(frame: pd.DataFrame) -> list[str]:
    if str(frame["candidate_scan_eligible"].dtype) == "bool":
        flag = frame["candidate_scan_eligible"]
    else:
        flag = frame["candidate_scan_eligible"].astype(str).str.lower().eq("true")
    return sorted(set(frame.loc[flag, "ticker"].astype(str).str.upper()))


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def run_scan(
    root: Path,
    *,
    min_score: float = 50.0,
    top_n: int = 50,
    verbose: bool = True,
):
    frame, manifest = load_candidate_artifact(root)
    tickers = eligible_tickers(frame)
    if not tickers:
        raise UniverseIntegrityError("no_candidate_scan_tickers")
    from aggressive.scanner import scan

    candidates = scan(
        tickers=tickers,
        universe_source="custom",
        min_tech_score=min_score,
        top_n=top_n,
        verbose=verbose,
    )
    meta = frame.set_index("ticker")
    rows = []
    for candidate in candidates:
        ticker = str(candidate.ticker).upper()
        rows.append(
            {
                "ticker": ticker,
                "final_score": float(candidate.final_score),
                "tech_score": float(candidate.tech_score),
                "membership_reasons": str(meta.loc[ticker, "membership_reasons"])
                if ticker in meta.index
                else "",
                "risk_watch": _as_bool(meta.loc[ticker, "risk_watch"])
                if ticker in meta.index
                else False,
                "research_only": True,
                "event_membership_score_bonus": 0.0,
            }
        )
    summary = {
        "requested_candidate_tickers": len(tickers),
        "returned_ranked_candidates": len(rows),
        "membership_content_identity": manifest.get("content_identity"),
        "event_membership_score_bonus": 0.0,
        "research_only": True,
        "portfolio_target_changed": False,
    }
    return rows, summary


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifact-dir", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--min-score", type=float, default=50.0)
    p.add_argument("--top", type=int, default=50)
    args = p.parse_args(argv)
    try:
        rows, summary = run_scan(
            args.artifact_dir,
            min_score=args.min_score,
            top_n=args.top,
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(args.output_dir / "candidate_scan_ranked.csv", index=False)
        (args.output_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"status": "OK_RESEARCH_ONLY", **summary}, sort_keys=True))
        return 0
    except (UniverseIntegrityError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"status": "BLOCKED_INTEGRITY", "reason": str(exc), "published": False},
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

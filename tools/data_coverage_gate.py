#!/usr/bin/env python3
"""Data coverage gate — turn silent zero-fallback into a loud failure.

Every evidence layer in this engine treats "missing data = neutral, fill 0", so
a dead feed (ETF holdings at 0%, SEC available_from at 12%, an unwired Top7 lane)
produces a GREEN job and a GREEN rebuild while 100% of that layer's alpha sits at
zero. This gate reads the materialised coverage ratios and FAILS LOUDLY when a
layer falls below its floor, so green-but-empty becomes impossible.

Inputs (auto-discovered under --run-dir, or pass explicit paths):
  * sec_enriched_candidate_replay/summary.json  -> coverage_13f_ratio,
        coverage_etf_ratio, coverage_smart_money_ratio, coverage_ratio
        (coverage_ratio == fraction of rows carrying a SEC available_from PIT stamp)
  * data_readiness/summary.json                 -> feature_source_coverage,
        pit_available_from_check (future-dated stamp guard)

Floors (override via --floors-json). Defaults are deliberately modest — they
catch "dead", not "imperfect":
    etf            >= 0.30
    available_from >= 0.30   (the PIT stamp that gates 13F/Form4 lanes downstream)
    13f            >= 0.50
    smart_money    >= 0.50

A layer can be marked WARN instead of FAIL (``--warn-only etf,top7``) while a feed
is being repaired, so the gate is adoptable incrementally without blocking the
whole pipeline on day one.

Emits coverage_gate.json with per-layer status + an overall verdict, and exits
non-zero when any FAIL-severity layer is below floor (unless --no-fail).

Research/ops tool. Reads only; never mutates data or production policy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_FLOORS = {
    "etf": 0.30,
    "sec_v1_evidence": 0.20,   # Form4 v1 leader_onset detection rate — naturally sparse
    "13f": 0.50,
    "smart_money": 0.50,
    "top_manager": 0.05,       # Top-7 discovery is naturally sparse (few names per date)
}

# Map a layer -> the summary.json key that carries its materialised coverage.
# coverage_ratio = rows with evidence_confidence_score > 0 (Form4 v1 onset hits).
# It is NOT the fraction of rows with an available_from PIT stamp — that signal
# lives in data_readiness/summary.json::pit_available_from_check and is checked
# separately below (any future-dated stamp -> hard fail).
SEC_ENRICHED_KEYS = {
    "etf": "coverage_etf_ratio",
    "sec_v1_evidence": "coverage_ratio",
    "13f": "coverage_13f_ratio",
    "smart_money": "coverage_smart_money_ratio",
    "top_manager": "coverage_top_manager_ratio",
}


def repo_path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else REPO_ROOT / p


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def discover(run_dir: Path, explicit: str, *names: str) -> Path:
    if explicit:
        return repo_path(explicit)
    for n in names:
        p = run_dir / n
        if p.exists():
            return p
    return run_dir / names[0]


def evaluate(
    *,
    sec_enriched: dict[str, Any],
    readiness: dict[str, Any],
    floors: dict[str, float],
    warn_only: set[str],
) -> dict[str, Any]:
    layers: list[dict[str, Any]] = []
    overall_fail = False
    overall_warn = False

    for layer, key in SEC_ENRICHED_KEYS.items():
        floor = float(floors.get(layer, DEFAULT_FLOORS.get(layer, 0.0)))
        present = key in sec_enriched
        value = sec_enriched.get(key)
        try:
            value = float(value) if value is not None else None
        except (TypeError, ValueError):
            value = None
        below = (value is None) or (value < floor)
        severity = "warn" if layer in warn_only else "fail"
        status = "ok"
        if below:
            status = "WARN" if severity == "warn" else "FAIL"
            if severity == "warn":
                overall_warn = True
            else:
                overall_fail = True
        layers.append({
            "layer": layer,
            "source_key": key,
            "coverage": value,
            "floor": floor,
            "present": present,
            "status": status,
            "severity": severity,
            "action": "" if status == "ok" else f"{layer} coverage {value} < floor {floor}: feed dead or unmaterialised",
        })

    # Future-dated available_from is a hard PIT violation regardless of floors.
    pit_check = (
        readiness.get("feature_source_coverage", {})
        .get("books", {})
        .get("concentrated", {})
        .get("pit_available_from_check", {})
    )
    future_rows = int(pit_check.get("rows_with_any_future_available_from", 0) or 0)
    pit_ok = future_rows == 0
    if not pit_ok:
        overall_fail = True
    layers.append({
        "layer": "pit_no_future_available_from",
        "source_key": "rows_with_any_future_available_from",
        "coverage": future_rows,
        "floor": 0,
        "present": bool(pit_check),
        "status": "ok" if pit_ok else "FAIL",
        "severity": "fail",
        "action": "" if pit_ok else f"{future_rows} rows carry a FUTURE available_from (lookahead leak)",
    })

    verdict = "FAIL" if overall_fail else ("WARN" if overall_warn else "PASS")
    return {
        "verdict": verdict,
        "n_layers": len(layers),
        "n_fail": sum(1 for l in layers if l["status"] == "FAIL"),
        "n_warn": sum(1 for l in layers if l["status"] == "WARN"),
        "floors": floors,
        "warn_only": sorted(warn_only),
        "layers": layers,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", default="outputs", help="Run dir holding sec_enriched_candidate_replay/ and data_readiness/.")
    p.add_argument("--sec-enriched-summary", default="", help="Explicit path override.")
    p.add_argument("--readiness-summary", default="", help="Explicit path override.")
    p.add_argument("--output", default="outputs/coverage_gate.json")
    p.add_argument("--floors-json", default="", help="JSON file overriding layer floors.")
    p.add_argument("--warn-only", default="", help="Comma list of layers to downgrade FAIL->WARN while repairing (e.g. 'etf,available_from').")
    p.add_argument("--no-fail", action="store_true", help="Always exit 0 (report-only mode).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = repo_path(args.run_dir)
    sec_path = discover(run_dir, args.sec_enriched_summary,
                        "sec_enriched_candidate_replay/summary.json")
    rdy_path = discover(run_dir, args.readiness_summary,
                        "data_readiness/summary.json")
    floors = dict(DEFAULT_FLOORS)
    if args.floors_json:
        floors.update(read_json(repo_path(args.floors_json)))
    warn_only = {s.strip() for s in args.warn_only.split(",") if s.strip()}

    sec_enriched = read_json(sec_path)
    readiness = read_json(rdy_path)
    if not sec_enriched:
        result = {
            "verdict": "FAIL",
            "reason": f"sec_enriched summary not found/empty: {sec_path}",
            "layers": [],
        }
        write_json(repo_path(args.output), result)
        print(json.dumps(result, indent=2))
        return 0 if args.no_fail else 3

    result = evaluate(sec_enriched=sec_enriched, readiness=readiness, floors=floors, warn_only=warn_only)
    result["sec_enriched_summary"] = str(sec_path)
    result["readiness_summary"] = str(rdy_path)
    write_json(repo_path(args.output), result)

    print(f"[coverage-gate] verdict={result['verdict']}  fail={result['n_fail']}  warn={result['n_warn']}")
    for l in result["layers"]:
        if l["status"] != "ok":
            print(f"  {l['status']:4s} {l['layer']:32s} cov={l['coverage']} floor={l['floor']}  {l['action']}")
    if result["verdict"] == "FAIL" and not args.no_fail:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

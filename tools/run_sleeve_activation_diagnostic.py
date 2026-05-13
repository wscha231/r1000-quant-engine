#!/usr/bin/env python3
"""Sleeve activation diagnostic — why are dormant sleeves dormant?

Walks the 84-month candidate_replay_book.csv and evaluates each
sleeve's published gates against every (rebalance_date, ticker) row.
Output identifies the single most-binding gate per sleeve so a single
focused, conservative relaxation can activate the sleeve in subsequent
iterations.

READ-ONLY. No engine change. Walk-forward safe — uses only the
candidate_replay_book PIT data; no forward-return information is
consulted for gate evaluation.

Currently covers `alpha_sprint` (the cleanest case — `status:
inactive_no_bull_months_or_candidates` in every measured month).
`early_scout` and `future_winner` gate evaluation is approximated from
the published config thresholds; a more faithful evaluator would
import the exact gate code from r1000_pipeline.py and is left for the
next iteration.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_alpha_sprint import (  # noqa: E402
    ALPHA_SPRINT_POLICY,
    candidate_passes,
    catalyst_flags,
    overextension_flags,
    technical_gate_flags,
    universe_filter_flags,
)


SCHEMA_VERSION = "sleeve-activation-diagnostic-v1"
DEFAULT_CANDIDATE_BOOK = (
    "cloud_results/full_rebuild/latest_global_alpha_universe/reports/candidate_replay_book.csv"
)
DEFAULT_OUTPUT_DIR = "outputs/sleeve_activation_diagnostic"


def repo_path(p: str | Path) -> Path:
    path = Path(p)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_int(x: Any) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def analyze_alpha_sprint(candidate_book: pd.DataFrame) -> dict[str, Any]:
    """Per-month gate-failure breakdown for alpha_sprint.

    Reports, per rebalance_date, how many candidates passed each of
    the four gates and how many passed all four. Aggregates surface
    the single most-binding gate (the gate with the lowest historical
    pass rate).
    """
    per_month: list[dict[str, Any]] = []
    if candidate_book.empty or "rebalance_date" not in candidate_book.columns:
        return {"per_month": [], "summary": {"reason": "empty candidate book"}}

    rejection_examples: list[dict[str, Any]] = []
    near_pass_examples: list[dict[str, Any]] = []  # rows that pass 3/4 gates

    for date, period in candidate_book.groupby("rebalance_date"):
        gate_pass = {"universe": 0, "catalyst": 0, "technical": 0, "overextension": 0}
        all_pass = 0
        score_when_pass: list[float] = []
        first_failed_gate_counts = {"universe": 0, "catalyst": 0, "technical": 0, "overextension": 0}
        for _, row in period.iterrows():
            r = row.to_dict()
            ticker = str(r.get("ticker") or "").strip().upper()
            if not ticker or ticker == "CASH":
                continue
            try:
                uni_flags = universe_filter_flags(r, ALPHA_SPRINT_POLICY)
                cat_flags = catalyst_flags(r)
                tech_flags = technical_gate_flags(r)
                over_flags = overextension_flags(r)
            except Exception:
                continue
            uni_ok = all(uni_flags.values())
            cat_ok = any(cat_flags.values())
            tech_ok = all(tech_flags.values())
            over_ok = all(over_flags.values())
            gate_pass["universe"] += int(uni_ok)
            gate_pass["catalyst"] += int(cat_ok)
            gate_pass["technical"] += int(tech_ok)
            gate_pass["overextension"] += int(over_ok)
            n_pass = sum([uni_ok, cat_ok, tech_ok, over_ok])
            if uni_ok and cat_ok and tech_ok and over_ok:
                all_pass += 1
            else:
                # Identify first failed gate (in evaluation order).
                for gname, ok in (("universe", uni_ok), ("catalyst", cat_ok), ("technical", tech_ok), ("overextension", over_ok)):
                    if not ok:
                        first_failed_gate_counts[gname] += 1
                        break
                if n_pass == 3 and len(near_pass_examples) < 30:
                    near_pass_examples.append({
                        "rebalance_date": str(date),
                        "ticker": ticker,
                        "universe": dict(uni_flags),
                        "catalyst": dict(cat_flags),
                        "technical": dict(tech_flags),
                        "overextension": dict(over_flags),
                    })
        per_month.append({
            "rebalance_date": str(date),
            "candidates_evaluated": int(len(period)),
            "passed_universe": gate_pass["universe"],
            "passed_catalyst": gate_pass["catalyst"],
            "passed_technical": gate_pass["technical"],
            "passed_overextension": gate_pass["overextension"],
            "passed_all_4": all_pass,
            "first_failed_gate_counts": first_failed_gate_counts,
        })

    df = pd.DataFrame(per_month)
    total_evaluated = int(df["candidates_evaluated"].sum()) if not df.empty else 0
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sleeve": "alpha_sprint",
        "months_analyzed": int(len(df)),
        "total_candidates_evaluated": total_evaluated,
        "months_with_zero_passes": int((df["passed_all_4"] == 0).sum()) if not df.empty else 0,
        "months_with_some_passes": int((df["passed_all_4"] > 0).sum()) if not df.empty else 0,
        "gate_pass_rate": {
            g: float(df[f"passed_{g}"].sum() / max(total_evaluated, 1)) if not df.empty else 0.0
            for g in ("universe", "catalyst", "technical", "overextension")
        },
        "all_pass_rate": float(df["passed_all_4"].sum() / max(total_evaluated, 1)) if not df.empty else 0.0,
        "first_failure_totals": {
            g: int(df.apply(lambda r: r["first_failed_gate_counts"].get(g, 0), axis=1).sum()) if not df.empty else 0
            for g in ("universe", "catalyst", "technical", "overextension")
        },
    }
    # Most binding = gate with lowest pass rate.
    if summary["gate_pass_rate"]:
        summary["most_binding_gate"] = min(summary["gate_pass_rate"], key=summary["gate_pass_rate"].get)
    return {
        "summary": summary,
        "per_month": per_month,
        "near_pass_examples_3of4": near_pass_examples[:15],
    }


def analyze_early_scout_approx(candidate_book: pd.DataFrame) -> dict[str, Any]:
    """Approximate early_scout gate evaluation from published config thresholds.

    Faithful evaluation lives in r1000_pipeline.py; this approximation
    only covers the four published numeric thresholds:
        early_scout_growth_floor_min_signal     0.25  (post-phase-x0)
        early_scout_breakout_min_score          0.15
        early_scout_confirmation_min            0.34
        early_scout_fundamental_presence_min    0.18

    Real selection has additional sleeve weight / promotion logic.
    Treat this as a directional signal, not ground truth.
    """
    per_month: list[dict[str, Any]] = []
    if candidate_book.empty:
        return {"per_month": [], "summary": {"reason": "empty"}}
    thresholds = {
        "growth_floor": 0.25,
        "breakout": 0.15,
        "confirmation": 0.34,
        "fundamental_presence": 0.18,
    }
    columns = {
        "growth_floor": ["future_winner_scout_score", "portfolio_early_scout_engine_score"],
        "breakout": ["breakout_setup_quality_score"],
        "confirmation": ["selection_confirmation_score"],
        "fundamental_presence": ["fundamental_presence_score", "fundamental_reliability_score"],
    }
    for date, period in candidate_book.groupby("rebalance_date"):
        gate_pass: dict[str, int] = {g: 0 for g in thresholds}
        all_pass = 0
        for _, row in period.iterrows():
            ok_flags: dict[str, bool] = {}
            for gname, cols in columns.items():
                values = [pd.to_numeric(row.get(c), errors="coerce") for c in cols]
                best = max((float(v) for v in values if pd.notna(v)), default=0.0)
                ok_flags[gname] = best >= thresholds[gname]
            for g, ok in ok_flags.items():
                gate_pass[g] += int(ok)
            if all(ok_flags.values()):
                all_pass += 1
        per_month.append({
            "rebalance_date": str(date),
            "candidates_evaluated": int(len(period)),
            **{f"passed_{g}": gate_pass[g] for g in thresholds},
            "passed_all_4_approx": all_pass,
        })
    df = pd.DataFrame(per_month)
    total = int(df["candidates_evaluated"].sum()) if not df.empty else 0
    summary = {
        "schema_version": SCHEMA_VERSION,
        "sleeve": "early_scout_approx",
        "thresholds_used": thresholds,
        "approximation_note": (
            "Approximates early_scout gates using published config thresholds against the "
            "candidate_replay_book columns. Faithful evaluation requires r1000_pipeline.py "
            "sleeve assignment logic; this is a directional indicator only."
        ),
        "months_analyzed": int(len(df)),
        "total_candidates_evaluated": total,
        "months_with_zero_passes": int((df["passed_all_4_approx"] == 0).sum()) if not df.empty else 0,
        "gate_pass_rate": {
            g: float(df[f"passed_{g}"].sum() / max(total, 1)) if not df.empty else 0.0
            for g in thresholds
        },
        "all_pass_rate_approx": float(df["passed_all_4_approx"].sum() / max(total, 1)) if not df.empty else 0.0,
    }
    if summary["gate_pass_rate"]:
        summary["most_binding_gate_approx"] = min(summary["gate_pass_rate"], key=summary["gate_pass_rate"].get)
    return {"summary": summary, "per_month": per_month}


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Sleeve Activation Diagnostic",
        "",
        f"- Generated: {payload.get('generated_at_utc')}",
        f"- Candidate book: `{payload.get('candidate_book')}`",
        f"- Schema: `{SCHEMA_VERSION}`",
        "",
        "Read-only analysis. No engine change. Walk-forward safe (no forward-return data consulted).",
        "",
        "## alpha_sprint (faithful gate evaluator)",
        "",
    ]
    asp = payload.get("alpha_sprint") or {}
    asum = asp.get("summary") or {}
    lines.append(f"- Months analyzed: {asum.get('months_analyzed', 0)}")
    lines.append(f"- Candidates evaluated: {asum.get('total_candidates_evaluated', 0):,}")
    lines.append(f"- Months with zero passes: **{asum.get('months_with_zero_passes', 0)}** / {asum.get('months_analyzed', 0)}")
    lines.append(f"- Overall all-pass rate: {asum.get('all_pass_rate', 0):.4%}")
    lines.append("")
    lines.append("### Per-gate pass rate (lower = more binding)")
    lines.append("")
    lines.append("| Gate | Pass rate | First-failure share |")
    lines.append("| --- | ---: | ---: |")
    rate = asum.get("gate_pass_rate", {})
    first_fail = asum.get("first_failure_totals", {})
    total_first_fail = sum(first_fail.values()) or 1
    for g in ("universe", "catalyst", "technical", "overextension"):
        r = rate.get(g, 0)
        ff_pct = first_fail.get(g, 0) / total_first_fail
        lines.append(f"| {g} | {r:.2%} | {ff_pct:.1%} |")
    lines.append("")
    if asum.get("most_binding_gate"):
        lines.append(f"**Most binding gate (lowest pass rate)**: `{asum['most_binding_gate']}`")
    lines.append("")
    lines.append("## early_scout (approximate from config thresholds)")
    lines.append("")
    es = payload.get("early_scout") or {}
    es_sum = es.get("summary") or {}
    lines.append(f"- Approximation note: {es_sum.get('approximation_note', '')}")
    lines.append(f"- All-pass rate (approx): {es_sum.get('all_pass_rate_approx', 0):.4%}")
    lines.append("")
    lines.append("| Gate | Pass rate |")
    lines.append("| --- | ---: |")
    for g, r in (es_sum.get("gate_pass_rate") or {}).items():
        lines.append(f"| {g} | {r:.2%} |")
    if es_sum.get("most_binding_gate_approx"):
        lines.append("")
        lines.append(f"**Most binding gate (approx)**: `{es_sum['most_binding_gate_approx']}`")
    lines.extend([
        "",
        "## How to use this report",
        "",
        "1. Find the single most-binding gate per sleeve.",
        "2. Propose ONE conservative relaxation (e.g., lower threshold by 10-15%).",
        "3. Re-run the candidate evaluation locally to confirm activation count rises.",
        "4. Push the config change and trigger a Full Rebuild (Tier-3) to measure broker-ledger CAGR/MDD/Sharpe.",
        "5. Walk-forward validate: split 84 months 36/12 rolling. Reject the change if OOS regression.",
        "",
    ])
    return "\n".join(lines)


def run(candidate_book_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not candidate_book_path.exists():
        payload = {"status": "blocked", "reason": f"candidate book not found: {candidate_book_path}"}
        (output_dir / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
    cb = pd.read_csv(candidate_book_path, low_memory=False)
    alpha_result = analyze_alpha_sprint(cb)
    early_result = analyze_early_scout_approx(cb)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_book": str(candidate_book_path),
        "alpha_sprint": alpha_result,
        "early_scout": early_result,
        "research_only": True,
        "production_activation_allowed": False,
    }
    (output_dir / "summary.json").write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(
        candidate_book_path=repo_path(args.candidate_book),
        output_dir=repo_path(args.output_dir),
    )
    if payload.get("status") != "completed":
        print(json.dumps(payload, indent=2))
        return 2
    print(json.dumps({
        "schema": payload["schema_version"],
        "alpha_sprint_summary": payload["alpha_sprint"]["summary"],
        "early_scout_summary": payload["early_scout"]["summary"],
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

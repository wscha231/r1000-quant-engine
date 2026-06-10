#!/usr/bin/env python3
"""Report-only winner lifecycle diagnostics.

This tool prepares the daily AutoLearning inputs the engine needs before any
production rule can be changed:

- missed winners: strong non-held leaders the current portfolio failed to own
- stale winners: held names whose recent relative strength no longer justifies
  their weight
- leadership rotations: same-sector challengers that may deserve a swap test

It is intentionally artifact-only and proposal-only. It does not alter model
features, portfolio construction, weights, or production config.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUTPUT_DIR = "outputs/winner_lifecycle"
CASH_TICKERS = {"CASH", "BIL", "SGOV"}


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return [dict(row) for row in csv.DictReader(f)]
    except Exception:
        return []


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if math.isnan(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def clip(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, float(value)))


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("Ticker") or "").strip().upper()


def name(row: dict[str, Any]) -> str:
    return str(row.get("Name") or row.get("name") or row.get("company") or "")


def sector(row: dict[str, Any]) -> str:
    return str(row.get("sector") or row.get("Sector") or "Unknown")


def pct(value: float) -> str:
    return f"{value:.2%}"


def first_metric(row: dict[str, Any], *names: str, default: float = 0.0) -> float:
    for key in names:
        if key in row and row.get(key) not in (None, ""):
            return safe_float(row.get(key), default)
    return default


def selected_tickers(*frames: list[dict[str, str]]) -> set[str]:
    out: set[str] = set()
    for rows in frames:
        for row in rows:
            t = ticker(row)
            if t and t not in CASH_TICKERS:
                out.add(t)
    return out


def selected_weight_map(*frames: list[dict[str, str]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for rows in frames:
        for row in rows:
            t = ticker(row)
            if t and t not in CASH_TICKERS:
                out[t] = max(out.get(t, 0.0), first_metric(row, "weight", "target_weight"))
    return out


def row_by_ticker(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {ticker(row): row for row in rows if ticker(row)}


def add_score_ranks(rows: list[dict[str, str]]) -> None:
    ranked = sorted(rows, key=lambda row: safe_float(row.get("score"), -999.0), reverse=True)
    for idx, row in enumerate(ranked, start=1):
        row["_score_rank"] = str(idx)


def momentum_norm(row: dict[str, Any]) -> float:
    mom_1m = first_metric(row, "mom_1m")
    mom_3m = first_metric(row, "mom_3m")
    mom_6m = first_metric(row, "mom_6m")
    mom_12m = first_metric(row, "mom_12m")
    return (
        0.15 * clip(mom_1m / 0.20, -1.0, 3.0)
        + 0.35 * clip(mom_3m / 0.50, -1.0, 3.0)
        + 0.30 * clip(mom_6m / 1.00, -1.0, 3.0)
        + 0.20 * clip(mom_12m / 1.50, -1.0, 3.0)
    )


def engine_interest(row: dict[str, Any]) -> float:
    return max(
        first_metric(row, "portfolio_future_winner_engine_score"),
        first_metric(row, "portfolio_early_scout_engine_score"),
        first_metric(row, "portfolio_core_compounder_engine_score"),
        first_metric(row, "score") / 6.0,
    )


def reason_join(reasons: list[str]) -> str:
    return ",".join(dict.fromkeys([r for r in reasons if r]))


def build_missed_winners(
    scored_rows: list[dict[str, str]],
    held_tickers: set[str],
    top_n: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in scored_rows:
        t = ticker(row)
        if not t or t in CASH_TICKERS or t in held_tickers:
            continue
        mom_3m = first_metric(row, "mom_3m")
        mom_6m = first_metric(row, "mom_6m")
        mom_12m = first_metric(row, "mom_12m")
        rs = first_metric(row, "relative_strength_composite", "rs_score")
        entry = first_metric(row, "entry_quality_score", default=0.5)
        future = first_metric(row, "portfolio_future_winner_engine_score")
        early = first_metric(row, "portfolio_early_scout_engine_score")
        score_rank = int(safe_float(row.get("_score_rank"), 999999))
        reasons = []
        if mom_3m >= 0.30:
            reasons.append("strong_3m_momentum")
        if mom_6m >= 0.50:
            reasons.append("strong_6m_momentum")
        if mom_12m >= 0.75:
            reasons.append("strong_12m_momentum")
        if rs >= 1.5:
            reasons.append("high_relative_strength")
        if entry <= 0.15 and (mom_3m >= 0.50 or mom_6m >= 1.00):
            reasons.append("entry_quality_chase_penalty")
        if max(future, early) >= 0.70:
            reasons.append("engine_likes_nonheld_name")
        if score_rank > 75 and (mom_3m >= 0.50 or rs >= 2.0):
            reasons.append("ranking_mismatch")

        missed_score = (
            2.00 * momentum_norm(row)
            + 0.55 * clip(rs / 4.0, -1.0, 2.0)
            + 0.45 * clip(engine_interest(row), -1.0, 2.0)
            + 0.25 * first_metric(row, "selection_confirmation_score")
            - 0.35 * max(0.0, 0.25 - entry)
        )
        if missed_score <= 0.75 and not reasons:
            continue
        policy_probe = "watchlist_only"
        if "entry_quality_chase_penalty" in reasons:
            policy_probe = "fundamental_acceleration_override_replay"
        elif "engine_likes_nonheld_name" in reasons:
            policy_probe = "concentrated_or_alpha_sprint_replay"
        elif "high_relative_strength" in reasons:
            policy_probe = "leadership_rotation_replay"
        rows.append(
            {
                "ticker": t,
                "name": name(row),
                "sector": sector(row),
                "score_rank": score_rank,
                "score": first_metric(row, "score"),
                "missed_winner_score": round(missed_score, 6),
                "mom_1m": first_metric(row, "mom_1m"),
                "mom_3m": mom_3m,
                "mom_6m": mom_6m,
                "mom_12m": mom_12m,
                "relative_strength_composite": rs,
                "entry_quality_score": entry,
                "future_winner_score": future,
                "early_scout_score": early,
                "portfolio_sleeve_label": row.get("portfolio_sleeve_label", ""),
                "diagnosis": reason_join(reasons),
                "policy_probe": policy_probe,
                "production_activation_allowed": False,
            }
        )
    return sorted(rows, key=lambda row: row["missed_winner_score"], reverse=True)[:top_n]


def build_stale_winners(
    portfolio_rows: list[dict[str, str]],
    scored_by_ticker: dict[str, dict[str, str]],
    top_n: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for holding in portfolio_rows:
        t = ticker(holding)
        if not t or t in CASH_TICKERS:
            continue
        score_row = scored_by_ticker.get(t, {})
        merged = dict(score_row)
        merged.update(holding)
        weight = first_metric(holding, "weight", "target_weight")
        mom_3m = first_metric(merged, "mom_3m")
        mom_6m = first_metric(merged, "mom_6m")
        mom_12m = first_metric(merged, "mom_12m")
        rs3 = first_metric(merged, "rs_benchmark_3m", default=mom_3m)
        rs6 = first_metric(merged, "rs_benchmark_6m", default=mom_6m)
        rs = first_metric(merged, "relative_strength_composite")
        reasons = []
        if mom_3m < 0.05:
            reasons.append("weak_3m_absolute_momentum")
        if mom_6m < 0.00:
            reasons.append("negative_6m_absolute_momentum")
        if rs3 < 0.00:
            reasons.append("under_benchmark_3m")
        if rs6 < 0.00:
            reasons.append("under_benchmark_6m")
        if rs < 0.50 and weight >= 0.05:
            reasons.append("high_weight_low_relative_strength")
        if first_metric(merged, "broken_momentum_penalty") >= 0.50:
            reasons.append("broken_momentum_penalty")
        stale_score = (
            1.50 * weight
            + 0.80 * max(0.0, 0.08 - mom_3m)
            + 1.10 * max(0.0, -mom_6m)
            + 0.45 * max(0.0, -rs3)
            + 0.45 * max(0.0, -rs6)
            + 0.25 * max(0.0, 0.35 - rs)
        )
        if not reasons:
            continue
        rows.append(
            {
                "ticker": t,
                "name": name(merged),
                "sector": sector(merged),
                "weight": weight,
                "score": first_metric(merged, "score"),
                "stale_winner_score": round(stale_score, 6),
                "mom_3m": mom_3m,
                "mom_6m": mom_6m,
                "mom_12m": mom_12m,
                "rs_benchmark_3m": rs3,
                "rs_benchmark_6m": rs6,
                "relative_strength_composite": rs,
                "portfolio_sleeve_label": merged.get("portfolio_sleeve_label", ""),
                "diagnosis": reason_join(reasons),
                "policy_probe": "trim_or_replace_replay" if reasons else "monitor",
                "production_activation_allowed": False,
            }
        )
    return sorted(rows, key=lambda row: row["stale_winner_score"], reverse=True)[:top_n]


def build_leadership_rotations(
    portfolio_rows: list[dict[str, str]],
    scored_rows: list[dict[str, str]],
    held_tickers: set[str],
    top_n: int,
) -> list[dict[str, Any]]:
    by_sector: dict[str, list[dict[str, str]]] = {}
    for row in scored_rows:
        t = ticker(row)
        if not t or t in CASH_TICKERS or t in held_tickers:
            continue
        by_sector.setdefault(sector(row), []).append(row)

    rows: list[dict[str, Any]] = []
    scored_lookup = row_by_ticker(scored_rows)
    for holding in portfolio_rows:
        held = ticker(holding)
        if not held or held in CASH_TICKERS:
            continue
        held_row = dict(scored_lookup.get(held, {}))
        held_row.update(holding)
        candidates = by_sector.get(sector(held_row), [])
        if not candidates:
            continue
        best: dict[str, Any] | None = None
        for challenger in candidates:
            score_delta = first_metric(challenger, "score") - first_metric(held_row, "score")
            mom3_delta = first_metric(challenger, "mom_3m") - first_metric(held_row, "mom_3m")
            mom6_delta = first_metric(challenger, "mom_6m") - first_metric(held_row, "mom_6m")
            rs_delta = first_metric(challenger, "relative_strength_composite") - first_metric(
                held_row, "relative_strength_composite"
            )
            entry_delta = first_metric(challenger, "entry_quality_score") - first_metric(held_row, "entry_quality_score")
            rotation_score = (
                1.20 * max(0.0, mom3_delta)
                + 0.80 * max(0.0, mom6_delta)
                + 0.45 * max(0.0, rs_delta)
                + 0.12 * max(0.0, score_delta)
                + 0.15 * max(0.0, entry_delta)
            )
            if rotation_score <= 0.30:
                continue
            candidate_row = {
                "held_ticker": held,
                "held_name": name(held_row),
                "held_weight": first_metric(holding, "weight", "target_weight"),
                "challenger_ticker": ticker(challenger),
                "challenger_name": name(challenger),
                "sector": sector(held_row),
                "rotation_score": round(rotation_score, 6),
                "held_score": first_metric(held_row, "score"),
                "challenger_score": first_metric(challenger, "score"),
                "score_delta": score_delta,
                "held_mom_3m": first_metric(held_row, "mom_3m"),
                "challenger_mom_3m": first_metric(challenger, "mom_3m"),
                "mom_3m_delta": mom3_delta,
                "held_mom_6m": first_metric(held_row, "mom_6m"),
                "challenger_mom_6m": first_metric(challenger, "mom_6m"),
                "mom_6m_delta": mom6_delta,
                "held_relative_strength": first_metric(held_row, "relative_strength_composite"),
                "challenger_relative_strength": first_metric(challenger, "relative_strength_composite"),
                "relative_strength_delta": rs_delta,
                "diagnosis": "same_sector_challenger_outperforming",
                "policy_probe": "leadership_rotation_shadow_replay",
                "production_activation_allowed": False,
            }
            if best is None or candidate_row["rotation_score"] > best["rotation_score"]:
                best = candidate_row
        if best is not None:
            rows.append(best)
    return sorted(rows, key=lambda row: row["rotation_score"], reverse=True)[:top_n]


def render_markdown(summary: dict[str, Any], top_n: int = 10) -> str:
    def table(rows: list[dict[str, Any]], cols: list[str]) -> list[str]:
        if not rows:
            return ["_none_"]
        out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
        for row in rows[:top_n]:
            values = []
            for col in cols:
                value = row.get(col, "")
                if isinstance(value, float):
                    value = round(value, 4)
                values.append(str(value))
            out.append("| " + " | ".join(values) + " |")
        return out

    lines = [
        "# Winner Lifecycle Daily Diagnostics",
        "",
        "Research-only. No production rules, weights, features, or execution behavior are changed.",
        "",
        f"- generated_at_utc: `{summary['generated_at_utc']}`",
        f"- latest_run: `{summary['latest_run']}`",
        f"- scored_rows: `{summary['counts']['scored_rows']}`",
        f"- held_tickers: `{summary['counts']['held_tickers']}`",
        f"- missed_winner_count: `{summary['counts']['missed_winners']}`",
        f"- stale_winner_count: `{summary['counts']['stale_winners']}`",
        f"- leadership_rotation_count: `{summary['counts']['leadership_rotations']}`",
        "",
        "## Missed Winners",
        "",
    ]
    lines.extend(
        table(
            summary["missed_winners"],
            ["ticker", "sector", "missed_winner_score", "mom_3m", "mom_6m", "entry_quality_score", "diagnosis", "policy_probe"],
        )
    )
    lines.extend(["", "## Stale Winners", ""])
    lines.extend(
        table(
            summary["stale_winners"],
            ["ticker", "weight", "stale_winner_score", "mom_3m", "mom_6m", "relative_strength_composite", "diagnosis", "policy_probe"],
        )
    )
    lines.extend(["", "## Leadership Rotation Candidates", ""])
    lines.extend(
        table(
            summary["leadership_rotations"],
            [
                "held_ticker",
                "challenger_ticker",
                "sector",
                "rotation_score",
                "held_weight",
                "mom_3m_delta",
                "mom_6m_delta",
                "policy_probe",
            ],
        )
    )
    lines.extend(
        [
            "",
            "## Suggested Next Experiments",
            "",
            "1. Replay `fundamental_acceleration_override` for missed winners with high momentum and low entry quality.",
            "2. Replay `trim_or_replace` for stale high-weight holdings with negative 3-6 month relative strength.",
            "3. Replay `leadership_rotation` by replacing stale same-sector holdings with stronger challengers.",
            "4. Keep all three proposal-only until historical replay, shadow, and canary gates pass.",
            "",
        ]
    )
    return "\n".join(lines)


def render_policy_yaml(summary: dict[str, Any]) -> str:
    missed = summary["missed_winners"][:8]
    stale = summary["stale_winners"][:8]
    rotations = summary["leadership_rotations"][:8]
    lines = [
        "# AUTO-GENERATED by tools/run_winner_lifecycle_reports.py",
        "# Research-only candidate rules. Do not wire to production without",
        "# historical replay, shadow validation, canary sizing, and human approval.",
        "mode: proposal_only",
        "production_activation_allowed: false",
        "requires_historical_replay: true",
        "requires_shadow_validation: true",
        "requires_human_approval: true",
        "generated_at_utc: " + str(summary["generated_at_utc"]),
        "rules:",
        "  - id: fundamental_acceleration_override_candidate",
        "    rationale: Treat explosive leaders as repricing candidates, not automatic chase rejects.",
        "    source_report: missed_winners",
        "    candidate_tickers: [" + ", ".join(row["ticker"] for row in missed) + "]",
        "    action: replay_alpha_sprint_or_concentrated_pilot_entry",
        "  - id: stale_winner_trim_candidate",
        "    rationale: Reduce opportunity cost from high-weight holdings lagging the market.",
        "    source_report: stale_winners",
        "    candidate_tickers: [" + ", ".join(row["ticker"] for row in stale) + "]",
        "    action: replay_trim_or_replace",
        "  - id: leadership_rotation_candidate",
        "    rationale: Test same-sector challenger swaps when new leaders overtake current holdings.",
        "    source_report: leadership_rotations",
        "    candidate_pairs:",
    ]
    if rotations:
        for row in rotations:
            lines.append(f"      - [{row['held_ticker']}, {row['challenger_ticker']}]")
    else:
        lines.append("      []")
    return "\n".join(lines) + "\n"


def run(latest_run: Path, output_dir: Path, top_n: int) -> dict[str, Any]:
    scored = read_csv_rows(latest_run / "scored_latest.csv")
    portfolio = read_csv_rows(latest_run / "portfolio_latest.csv")
    concentrated = read_csv_rows(latest_run / "concentrated_portfolio_latest.csv")
    add_score_ranks(scored)
    held = selected_tickers(portfolio, concentrated)
    score_lookup = row_by_ticker(scored)

    missed = build_missed_winners(scored, held, top_n)
    stale = build_stale_winners(portfolio, score_lookup, top_n)
    rotations = build_leadership_rotations(portfolio, scored, held, top_n)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_run": str(latest_run),
        "counts": {
            "scored_rows": len(scored),
            "portfolio_rows": len(portfolio),
            "concentrated_rows": len(concentrated),
            "held_tickers": len(held),
            "missed_winners": len(missed),
            "stale_winners": len(stale),
            "leadership_rotations": len(rotations),
        },
        "missed_winners": missed,
        "stale_winners": stale,
        "leadership_rotations": rotations,
        "production_activation_allowed": False,
    }

    missed_cols = [
        "ticker",
        "name",
        "sector",
        "score_rank",
        "score",
        "missed_winner_score",
        "mom_1m",
        "mom_3m",
        "mom_6m",
        "mom_12m",
        "relative_strength_composite",
        "entry_quality_score",
        "future_winner_score",
        "early_scout_score",
        "portfolio_sleeve_label",
        "diagnosis",
        "policy_probe",
        "production_activation_allowed",
    ]
    stale_cols = [
        "ticker",
        "name",
        "sector",
        "weight",
        "score",
        "stale_winner_score",
        "mom_3m",
        "mom_6m",
        "mom_12m",
        "rs_benchmark_3m",
        "rs_benchmark_6m",
        "relative_strength_composite",
        "portfolio_sleeve_label",
        "diagnosis",
        "policy_probe",
        "production_activation_allowed",
    ]
    rotation_cols = [
        "held_ticker",
        "held_name",
        "held_weight",
        "challenger_ticker",
        "challenger_name",
        "sector",
        "rotation_score",
        "held_score",
        "challenger_score",
        "score_delta",
        "held_mom_3m",
        "challenger_mom_3m",
        "mom_3m_delta",
        "held_mom_6m",
        "challenger_mom_6m",
        "mom_6m_delta",
        "held_relative_strength",
        "challenger_relative_strength",
        "relative_strength_delta",
        "diagnosis",
        "policy_probe",
        "production_activation_allowed",
    ]
    write_csv(output_dir / "missed_winner_report.csv", missed, missed_cols)
    write_csv(output_dir / "stale_winner_report.csv", stale, stale_cols)
    write_csv(output_dir / "leadership_rotation_report.csv", rotations, rotation_cols)
    write_json(output_dir / "winner_lifecycle_summary.json", summary)
    write_text(output_dir / "winner_lifecycle_report.md", render_markdown(summary))
    write_text(output_dir / "system_policy_candidates.yaml", render_policy_yaml(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-n", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    summary = run(latest_run, output_dir, max(1, int(args.top_n)))
    print(
        "winner lifecycle reports written: "
        f"missed={summary['counts']['missed_winners']} "
        f"stale={summary['counts']['stale_winners']} "
        f"rotations={summary['counts']['leadership_rotations']} "
        f"out={output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

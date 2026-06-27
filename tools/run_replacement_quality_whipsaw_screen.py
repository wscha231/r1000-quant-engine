#!/usr/bin/env python3
"""Screen replacement-quality whipsaw candidates before any policy hook.

This tool is measurement-only.  It compares dropped prior holdings against
newly-added challengers using PIT fields available on the rebalance row.  Future
return columns, when present, are copied only as audit labels and never used for
candidate selection or ranking.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_alphaops_vnext_policy_replay import score_month  # noqa: E402

SCHEMA_VERSION = "replacement-quality-whipsaw-screen-v1"
CASH_TICKERS = {"CASH", "__CASH__"}
DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/replacement_quality_whipsaw_screen"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def clean_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def default_candidate_book(latest_run: Path) -> Path:
    candidates = [
        latest_run / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv",
        latest_run / "candidate_replay" / "candidate_replay_book.csv",
        latest_run / "market_leader_challenger" / "candidate_replay_book.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def default_target_book(latest_run: Path, portfolio: str) -> Path:
    candidates = [
        latest_run / "alphaops_vnext" / f"official_{portfolio}_target_book.csv",
        latest_run / "reports" / f"operating_{portfolio}_target_book.csv",
        latest_run / "market_leader_challenger" / f"{portfolio}_target_book.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "rebalance_date" not in frame.columns or "ticker" not in frame.columns:
        return pd.DataFrame()
    d = frame.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].map(clean_ticker)
    d = d[d["rebalance_date"].notna()]
    d = d[d["ticker"].ne("")]
    return d


def non_cash_tickers(frame: pd.DataFrame) -> set[str]:
    if frame.empty:
        return set()
    return set(frame["ticker"].dropna().map(clean_ticker)) - CASH_TICKERS


def target_sets_by_date(target: pd.DataFrame) -> dict[pd.Timestamp, set[str]]:
    out: dict[pd.Timestamp, set[str]] = {}
    if target.empty:
        return out
    for raw_dt, group in target.groupby("rebalance_date"):
        out[pd.Timestamp(raw_dt).normalize()] = non_cash_tickers(group)
    return out


def prior_sets_by_date(target: pd.DataFrame) -> dict[pd.Timestamp, set[str]]:
    out: dict[pd.Timestamp, set[str]] = {}
    previous: set[str] = set()
    for raw_dt in sorted(pd.to_datetime(target["rebalance_date"], errors="coerce").dropna().unique()):
        dt = pd.Timestamp(raw_dt).normalize()
        out[dt] = set(previous)
        previous = non_cash_tickers(target[target["rebalance_date"].eq(dt)])
    return out


def effective_leader_tier(row: dict[str, Any]) -> str:
    native = str(row.get("leader_tier") or "").upper()
    if native in {"DUAL_LEADER", "SECTOR_LEADER", "EMERGING_LEADER"}:
        return native
    medium_rs = medium_relative_strength(row)
    long_rs = long_relative_strength(row)
    sector_score = safe_float(row.get("sector_leadership_score"), safe_float(row.get("industry_group_strength_score"), 0.0))
    if medium_rs > 0.0 and long_rs > 0.0 and sector_score > 0.0:
        return "SECTOR_LEADER_FALLBACK"
    if medium_rs > 0.0 and long_rs > 0.0:
        return "DUAL_LEADER_FALLBACK"
    if medium_rs > 0.0:
        return "EMERGING_LEADER_FALLBACK"
    return native or "UNKNOWN"


def leader_tier_score(value: Any) -> float:
    text = str(value or "").upper()
    if text == "DUAL_LEADER":
        return 1.00
    if text == "DUAL_LEADER_FALLBACK":
        return 0.85
    if text == "SECTOR_LEADER":
        return 0.80
    if text == "SECTOR_LEADER_FALLBACK":
        return 0.70
    if text == "EMERGING_LEADER":
        return 0.45
    if text == "EMERGING_LEADER_FALLBACK":
        return 0.35
    if text == "LAGGING":
        return -0.25
    return 0.0


def revision_score(row: dict[str, Any]) -> float:
    for col in ("eps_revision_score", "revision_score", "earnings_revision_score", "eps_revision_proxy"):
        if col in row and str(row.get(col)).strip().lower() not in {"", "nan", "none"}:
            return safe_float(row.get(col), 0.0)
    return 0.0


def medium_relative_strength(row: dict[str, Any]) -> float:
    return safe_float(
        row.get("rs_benchmark_3m"),
        safe_float(row.get("rs_qqq_3m"), safe_float(row.get("rs_spy_3m"), 0.0)),
    )


def long_relative_strength(row: dict[str, Any]) -> float:
    return safe_float(
        row.get("rs_benchmark_6m"),
        safe_float(row.get("rs_qqq_6m"), safe_float(row.get("rs_spy_6m"), 0.0)),
    )


def thesis_quality_score(row: dict[str, Any]) -> float:
    rs_component = clamp((medium_relative_strength(row) * 0.7 + long_relative_strength(row) * 0.3) / 0.50, -1.0, 1.0)
    actual_component = clamp(safe_float(row.get("actual_results_score"), 0.0) / 2.0, -0.5, 1.0)
    sector_component = clamp(safe_float(row.get("sector_leadership_score"), safe_float(row.get("industry_group_strength_score"), 0.0)), -1.0, 1.0)
    revision_component = clamp(revision_score(row), -1.0, 1.0)
    trend_component = 0.5 * clamp(safe_float(row.get("price_above_ma200"), 0.0), 0.0, 1.0) + 0.5 * clamp(safe_float(row.get("price_above_ma50"), 0.0), 0.0, 1.0)
    overextension_penalty = clamp(safe_float(row.get("stage2_overext_penalty"), 0.0) + safe_float(row.get("overheat_penalty"), 0.0), 0.0, 1.0)
    return (
        0.25 * leader_tier_score(effective_leader_tier(row))
        + 0.20 * actual_component
        + 0.20 * rs_component
        + 0.15 * sector_component
        + 0.10 * revision_component
        + 0.10 * trend_component
        - 0.10 * overextension_penalty
    )


def thesis_intact(row: dict[str, Any]) -> tuple[bool, str]:
    tier = effective_leader_tier(row)
    if tier not in {"DUAL_LEADER", "SECTOR_LEADER", "DUAL_LEADER_FALLBACK", "SECTOR_LEADER_FALLBACK"}:
        return False, f"leader_tier_not_intact:{tier or 'unknown'}"
    if medium_relative_strength(row) <= 0.0:
        return False, "medium_relative_strength_nonpositive"
    if safe_float(row.get("price_above_ma200"), 1.0) < 0.5:
        return False, "below_ma200"
    if revision_score(row) < -0.25:
        return False, "revision_negative"
    return True, "thesis_intact"


def alphaops_score(row: dict[str, Any]) -> float:
    return safe_float(row.get("alphaops_vnext_score"), safe_float(row.get("alphaops_vnext_weight_score"), safe_float(row.get("concentrated_score"), safe_float(row.get("score"), 0.0))))


def score_candidate_months(candidate: pd.DataFrame, target_dates: set[pd.Timestamp]) -> dict[pd.Timestamp, dict[str, dict[str, Any]]]:
    out: dict[pd.Timestamp, dict[str, dict[str, Any]]] = {}
    if candidate.empty:
        return out
    candidate = candidate[candidate["rebalance_date"].isin(target_dates)].copy()
    for raw_dt, month_raw in candidate.groupby("rebalance_date"):
        dt = pd.Timestamp(raw_dt).normalize()
        try:
            scored = score_month(month_raw.copy())
        except Exception:
            scored = month_raw.copy()
        scored["ticker"] = scored["ticker"].map(clean_ticker)
        out[dt] = {str(row["ticker"]): row.to_dict() for _, row in scored.iterrows()}
    return out


def build_screen(
    *,
    candidate: pd.DataFrame,
    target: pd.DataFrame,
    quality_margin: float,
    min_events: int,
    min_positive_rate: float,
    min_mean_forward_edge: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    target_sets = target_sets_by_date(target)
    prior_sets = prior_sets_by_date(target)
    scored_by_date = score_candidate_months(candidate, set(target_sets))
    rows: list[dict[str, Any]] = []
    replacement_events = 0
    for dt in sorted(target_sets):
        prior = prior_sets.get(dt, set())
        current = target_sets.get(dt, set())
        dropped = sorted(prior - current)
        added = sorted(current - prior)
        if not dropped or not added:
            continue
        month = scored_by_date.get(dt, {})
        added_rows = [month[ticker] for ticker in added if ticker in month]
        if not added_rows:
            continue
        replacement_events += len(dropped)
        added_rows = sorted(added_rows, key=alphaops_score, reverse=True)
        challenger = added_rows[0]
        challenger_score = alphaops_score(challenger)
        challenger_quality = thesis_quality_score(challenger)
        challenger_forward = safe_float(challenger.get("period_forward_return"), math.nan)
        for incumbent_ticker in dropped:
            incumbent = month.get(incumbent_ticker)
            if not incumbent:
                continue
            incumbent_score = alphaops_score(incumbent)
            incumbent_quality = thesis_quality_score(incumbent)
            intact, intact_reason = thesis_intact(incumbent)
            quality_edge = incumbent_quality - challenger_quality
            incumbent_forward = safe_float(incumbent.get("period_forward_return"), math.nan)
            if math.isfinite(incumbent_forward) and math.isfinite(challenger_forward):
                audit_forward_edge = incumbent_forward - challenger_forward
            else:
                audit_forward_edge = math.nan
            screen_candidate = bool(intact and quality_edge >= quality_margin)
            rows.append(
                {
                    "rebalance_date": dt.date().isoformat(),
                    "incumbent_ticker": incumbent_ticker,
                    "challenger_ticker": clean_ticker(challenger.get("ticker")),
                    "screen_candidate": screen_candidate,
                    "incumbent_thesis_intact": intact,
                    "incumbent_thesis_reason": intact_reason,
                    "incumbent_alphaops_score": incumbent_score,
                    "challenger_alphaops_score": challenger_score,
                    "raw_score_gap_challenger_minus_incumbent": challenger_score - incumbent_score,
                    "incumbent_quality_score": incumbent_quality,
                    "challenger_quality_score": challenger_quality,
                    "quality_edge_incumbent_minus_challenger": quality_edge,
                    "incumbent_leader_tier": incumbent.get("leader_tier", ""),
                    "challenger_leader_tier": challenger.get("leader_tier", ""),
                    "incumbent_effective_leader_tier": effective_leader_tier(incumbent),
                    "challenger_effective_leader_tier": effective_leader_tier(challenger),
                    "incumbent_medium_rs": medium_relative_strength(incumbent),
                    "challenger_medium_rs": medium_relative_strength(challenger),
                    "incumbent_actual_results_score": safe_float(incumbent.get("actual_results_score"), 0.0),
                    "challenger_actual_results_score": safe_float(challenger.get("actual_results_score"), 0.0),
                    "incumbent_revision_score": revision_score(incumbent),
                    "challenger_revision_score": revision_score(challenger),
                    "incumbent_forward_return_audit_only": incumbent_forward,
                    "challenger_forward_return_audit_only": challenger_forward,
                    "audit_forward_edge_incumbent_minus_challenger": audit_forward_edge,
                }
            )
    events = pd.DataFrame(rows)
    candidates = events[events["screen_candidate"].eq(True)].copy() if not events.empty else pd.DataFrame()
    candidate_count = int(len(candidates))
    valid_forward = candidates[pd.to_numeric(candidates.get("audit_forward_edge_incumbent_minus_challenger", pd.Series(dtype=float)), errors="coerce").notna()].copy() if not candidates.empty else pd.DataFrame()
    if not valid_forward.empty:
        edges = pd.to_numeric(valid_forward["audit_forward_edge_incumbent_minus_challenger"], errors="coerce")
        positive_rate = float((edges > 0).mean())
        mean_edge = float(edges.mean())
        median_edge = float(edges.median())
    else:
        positive_rate = 0.0
        mean_edge = 0.0
        median_edge = 0.0
    screen_pass = bool(candidate_count >= min_events and positive_rate >= min_positive_rate and mean_edge >= min_mean_forward_edge)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "research_only": True,
        "production_activation_allowed": False,
        "forward_columns_used_for_selection": False,
        "replacement_events": int(replacement_events),
        "evaluated_pairs": int(len(events)),
        "screen_candidate_count": candidate_count,
        "quality_margin": float(quality_margin),
        "screen_candidate_forward_observation_count": int(len(valid_forward)),
        "screen_candidate_positive_rate": positive_rate,
        "screen_candidate_mean_forward_edge": mean_edge,
        "screen_candidate_median_forward_edge": median_edge,
        "min_events": int(min_events),
        "min_positive_rate": float(min_positive_rate),
        "min_mean_forward_edge": float(min_mean_forward_edge),
        "screen_pass": screen_pass,
        "verdict": "screen_pass_design_default_off_hook" if screen_pass else "reject_or_inconclusive",
        "next_action": "design_default_off_replacement_quality_hook" if screen_pass else "discard_or_tighten_without_fullrun",
    }
    return events, summary


def render_report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Replacement Quality Whipsaw Screen",
            "",
            f"- Status: `{summary.get('status')}`",
            f"- Verdict: `{summary.get('verdict')}`",
            f"- Replacement events: {summary.get('replacement_events')}",
            f"- Evaluated pairs: {summary.get('evaluated_pairs')}",
            f"- Screen candidates: {summary.get('screen_candidate_count')}",
            f"- Candidate positive rate: {safe_float(summary.get('screen_candidate_positive_rate')):.2%}",
            f"- Candidate mean forward edge: {safe_float(summary.get('screen_candidate_mean_forward_edge')):.2%}",
            "",
            "Forward returns are audit labels only. They are not used for screen candidate selection.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--target-book", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--portfolio-kind", choices=["concentrated"], default="concentrated")
    parser.add_argument("--quality-margin", type=float, default=0.20)
    parser.add_argument("--min-events", type=int, default=8)
    parser.add_argument("--min-positive-rate", type=float, default=0.55)
    parser.add_argument("--min-mean-forward-edge", type=float, default=0.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    candidate_path = repo_path(args.candidate_book) if args.candidate_book else default_candidate_book(latest_run)
    target_path = repo_path(args.target_book) if args.target_book else default_target_book(latest_run, args.portfolio_kind)
    output_dir = repo_path(args.output_dir)
    candidate = prepare_frame(load_csv(candidate_path))
    target = prepare_frame(load_csv(target_path))
    if candidate.empty or target.empty:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked",
            "reason": "missing_candidate_or_target_book",
            "candidate_book": str(candidate_path),
            "target_book": str(target_path),
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "summary.json", payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    events, summary = build_screen(
        candidate=candidate,
        target=target,
        quality_margin=args.quality_margin,
        min_events=args.min_events,
        min_positive_rate=args.min_positive_rate,
        min_mean_forward_edge=args.min_mean_forward_edge,
    )
    summary.update(
        {
            "candidate_book": str(candidate_path),
            "target_book": str(target_path),
            "output_dir": str(output_dir),
        }
    )
    write_csv(output_dir / "replacement_quality_events.csv", events)
    if not events.empty:
        write_csv(output_dir / "replacement_quality_candidates.csv", events[events["screen_candidate"].eq(True)].copy())
    else:
        write_csv(output_dir / "replacement_quality_candidates.csv", pd.DataFrame())
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

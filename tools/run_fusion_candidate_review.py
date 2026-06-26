#!/usr/bin/env python3
"""Build a review-only fusion queue from independent diagnostic artifacts.

This sidecar does not create a trading rule. It only intersects already
generated diagnostics so a future policy candidate starts from multiple
PIT-visible signals instead of a failed broad layer.

Forward returns are carried only as audit labels. They are not used in the
fusion score, ranking, target construction, cash policy, or live signals.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

SCHEMA_VERSION = "fusion-candidate-review-v2"
DEFAULT_OUTPUT_DIR = "outputs/fusion_candidate_review"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def norm_ticker(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def norm_portfolio(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"main", "concentrated"}:
        return text
    return "unknown"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(out) or math.isinf(out):
        return default
    return out


def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def first_text(row: pd.Series, names: tuple[str, ...]) -> str:
    for name in names:
        if name in row.index and str(row.get(name, "")).strip():
            return str(row.get(name, "")).strip()
    return ""


def first_float(row: pd.Series, names: tuple[str, ...], default: float = 0.0) -> float:
    for name in names:
        if name in row.index:
            val = safe_float(row.get(name), math.nan)
            if not math.isnan(val):
                return val
    return default


def key_for(portfolio: str, ticker: str) -> tuple[str, str]:
    return (portfolio or "unknown", ticker)


def base_candidate(portfolio: str, ticker: str) -> dict[str, Any]:
    return {
        "portfolio": portfolio,
        "ticker": ticker,
        "evidence_sources": set(),
        "pit_signal_sources": set(),
        "outcome_selected_sources": set(),
        "source_dates": [],
        "sector": "",
        "theme": "",
        "subindustry": "",
        "entry_signal_stack_count_max": 0.0,
        "candidate_rank_percentile_max": 0.0,
        "rs_3m_max": 0.0,
        "rs_6m_max": 0.0,
        "audit_forward_63d_excess_spy_max": "",
        "audit_forward_126d_excess_spy_max": "",
        "audit_forward_126d_excess_max": "",
        "name_contribution_return_on_start": "",
        "name_contribution_status": "",
        "used_forward_return_in_ranking": False,
        "policy_mutation_allowed": False,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
    }


def ensure_candidate(candidates: dict[tuple[str, str], dict[str, Any]], portfolio: str, ticker: str) -> dict[str, Any]:
    key = key_for(portfolio, ticker)
    if key not in candidates:
        candidates[key] = base_candidate(portfolio, ticker)
    return candidates[key]


def update_context(candidate: dict[str, Any], row: pd.Series) -> None:
    for out_col, names in {
        "sector": ("sector", "gics_sector", "theme_sector"),
        "theme": ("theme", "theme_label", "dominant_theme"),
        "subindustry": ("subindustry", "gics_subindustry", "industry", "group_value"),
    }.items():
        if not candidate.get(out_col):
            candidate[out_col] = first_text(row, names)
    candidate["entry_signal_stack_count_max"] = max(
        safe_float(candidate.get("entry_signal_stack_count_max")),
        first_float(row, ("entry_signal_stack_count", "drop_entry_signal_stack_count", "signal_stack_count")),
    )
    candidate["candidate_rank_percentile_max"] = max(
        safe_float(candidate.get("candidate_rank_percentile_max")),
        first_float(row, ("candidate_rank_percentile", "drop_candidate_rank_percentile", "leader_rank_percentile")),
    )
    candidate["rs_3m_max"] = max(
        safe_float(candidate.get("rs_3m_max")),
        first_float(row, ("rs_benchmark_3m", "rs_spy_3m", "spy_relative_3m", "rs_3m")),
    )
    candidate["rs_6m_max"] = max(
        safe_float(candidate.get("rs_6m_max")),
        first_float(row, ("rs_benchmark_6m", "rs_spy_6m", "spy_relative_6m", "rs_6m")),
    )


def add_source(
    candidates: dict[tuple[str, str], dict[str, Any]],
    portfolio: str,
    ticker: str,
    source: str,
    row: pd.Series,
    *,
    pit_signal: bool,
    outcome_selected: bool = False,
    date_names: tuple[str, ...] = (),
) -> None:
    if not ticker:
        return
    candidate = ensure_candidate(candidates, portfolio, ticker)
    candidate["evidence_sources"].add(source)
    if pit_signal:
        candidate["pit_signal_sources"].add(source)
    if outcome_selected:
        candidate["outcome_selected_sources"].add(source)
    for name in date_names:
        if name in row.index and str(row.get(name, "")).strip():
            candidate["source_dates"].append(f"{source}:{row.get(name)}")
            break
    update_context(candidate, row)


def load_entry_signals(base: Path, candidates: dict[tuple[str, str], dict[str, Any]]) -> int:
    rows = read_csv(base / "right_tail_entry_signal_audit" / "winner_entry_signals.csv")
    count = 0
    for _, row in rows.iterrows():
        ticker = norm_ticker(row.get("ticker"))
        portfolio = norm_portfolio(row.get("portfolio"))
        skill = safe_bool(row.get("skill_evidence_flag")) or safe_float(row.get("entry_signal_stack_count")) >= 5
        if not skill:
            continue
        add_source(
            candidates,
            portfolio,
            ticker,
            "right_tail_entry_skill",
            row,
            pit_signal=True,
            date_names=("entry_signal_date", "entry_date", "signal_date"),
        )
        count += 1
    return count


def load_drop_signal_reviews(base: Path, candidates: dict[tuple[str, str], dict[str, Any]]) -> int:
    rows = read_csv(base / "right_tail_entry_signal_audit" / "drop_signal_reviews.csv")
    count = 0
    for _, row in rows.iterrows():
        ticker = norm_ticker(row.get("ticker"))
        portfolio = norm_portfolio(row.get("portfolio"))
        still_signal = safe_bool(row.get("drop_skill_evidence_flag")) or safe_float(row.get("drop_candidate_rank_percentile")) >= 0.80
        if not still_signal:
            continue
        add_source(
            candidates,
            portfolio,
            ticker,
            "drop_still_pit_signal",
            row,
            pit_signal=True,
            date_names=("drop_date",),
        )
        count += 1
    return count


def load_drop_counterfactuals(base: Path, candidates: dict[tuple[str, str], dict[str, Any]]) -> int:
    rows = read_csv(base / "right_tail_drop_counterfactual_audit" / "drop_counterfactuals.csv")
    count = 0
    for _, row in rows.iterrows():
        ticker = norm_ticker(row.get("ticker"))
        portfolio = norm_portfolio(row.get("portfolio"))
        high_signal = (
            safe_bool(row.get("drop_skill_evidence_flag"))
            and safe_float(row.get("drop_candidate_rank_percentile")) >= 0.80
            and safe_float(row.get("drop_entry_signal_stack_count", row.get("entry_signal_stack_count"))) >= 7
        )
        if not high_signal:
            continue
        add_source(
            candidates,
            portfolio,
            ticker,
            "drop_counterfactual_high_signal",
            row,
            pit_signal=True,
            date_names=("drop_date",),
        )
        candidate = ensure_candidate(candidates, portfolio, ticker)
        for out_col, names in {
            "audit_forward_63d_excess_spy_max": ("fwd_63d_excess_spy",),
            "audit_forward_126d_excess_spy_max": ("fwd_126d_excess_spy",),
        }.items():
            value = first_float(row, names, math.nan)
            if not math.isnan(value):
                old = safe_float(candidate.get(out_col), -999.0)
                candidate[out_col] = max(old, value)
        count += 1
    return count


def load_cap_replacement(base: Path, candidates: dict[tuple[str, str], dict[str, Any]]) -> int:
    rows = read_csv(base / "concentrated_cap_replacement_audit" / "top_missed_cap_replacement.csv")
    count = 0
    for _, row in rows.iterrows():
        ticker = norm_ticker(row.get("ticker"))
        portfolio = norm_portfolio(row.get("portfolio") or "concentrated")
        high_rs = (
            first_float(row, ("rs_benchmark_3m", "rs_spy_3m", "spy_relative_3m", "rs_3m")) >= 0.20
            or first_float(row, ("leader_rank_percentile", "candidate_rank_percentile")) >= 0.80
        )
        if not high_rs:
            continue
        add_source(
            candidates,
            portfolio,
            ticker,
            "cap_replacement_high_rs_miss",
            row,
            pit_signal=True,
            date_names=("rebalance_date", "date"),
        )
        candidate = ensure_candidate(candidates, portfolio, ticker)
        value = first_float(row, ("forward_126d_excess", "fwd_126d_excess_spy"), math.nan)
        if not math.isnan(value):
            old = safe_float(candidate.get("audit_forward_126d_excess_max"), -999.0)
            candidate["audit_forward_126d_excess_max"] = max(old, value)
        count += 1
    return count


def load_name_contribution(base: Path, candidates: dict[tuple[str, str], dict[str, Any]]) -> int:
    count = 0
    for portfolio in ("main", "concentrated"):
        rows = read_csv(base / "alpha_beta_attribution" / portfolio / "name_contribution.csv")
        if rows.empty:
            continue
        for _, row in rows.iterrows():
            ticker = norm_ticker(row.get("ticker"))
            contribution = first_float(row, ("contribution_return_on_start", "pnl_usd", "realized_pnl_usd"), 0.0)
            if contribution <= 0:
                continue
            add_source(
                candidates,
                portfolio,
                ticker,
                "positive_name_contribution",
                row,
                pit_signal=False,
                outcome_selected=True,
                date_names=("date", "as_of_date"),
            )
            candidate = ensure_candidate(candidates, portfolio, ticker)
            candidate["name_contribution_return_on_start"] = max(
                safe_float(candidate.get("name_contribution_return_on_start"), -999.0),
                contribution,
            )
            count += 1
    return count


def normalize_candidate_rows(candidates: dict[tuple[str, str], dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for candidate in candidates.values():
        sources = sorted(candidate.pop("evidence_sources"))
        pit_sources = sorted(candidate.pop("pit_signal_sources"))
        outcome_sources = sorted(candidate.pop("outcome_selected_sources"))
        dates = sorted(set(candidate.pop("source_dates")))
        independent_source_count = len(sources)
        pit_signal_source_count = len(pit_sources)
        outcome_selected_source_count = len(outcome_sources)
        fusion_review_candidate = independent_source_count >= 2 and pit_signal_source_count >= 1
        # This score intentionally excludes forward-return labels.
        fusion_review_score = independent_source_count + 0.25 * pit_signal_source_count
        row = {
            **candidate,
            "evidence_sources": ";".join(sources),
            "pit_signal_sources": ";".join(pit_sources),
            "outcome_selected_sources": ";".join(outcome_sources),
            "source_dates": ";".join(dates),
            "independent_source_count": independent_source_count,
            "pit_signal_source_count": pit_signal_source_count,
            "outcome_selected_source_count": outcome_selected_source_count,
            "has_outcome_selected_source": outcome_selected_source_count > 0,
            "fusion_review_score": round(float(fusion_review_score), 4),
            "fusion_review_candidate": bool(fusion_review_candidate),
            "policy_eligible": False,
            "review_status": "ready_for_manual_fusion_review" if fusion_review_candidate else "insufficient_independent_sources",
        }
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=[
            "portfolio",
            "ticker",
            "evidence_sources",
            "independent_source_count",
            "pit_signal_source_count",
            "outcome_selected_source_count",
            "fusion_review_candidate",
            "used_forward_return_in_ranking",
        ])
    return frame.sort_values(
        ["fusion_review_candidate", "independent_source_count", "pit_signal_source_count", "fusion_review_score", "ticker"],
        ascending=[False, False, False, False, True],
    )


def load_segment_summary(base: Path) -> pd.DataFrame:
    rows = read_csv(base / "right_tail_drop_counterfactual_audit" / "segment_summary.csv")
    if rows.empty:
        return pd.DataFrame(columns=[
            "portfolio",
            "group_field",
            "group_value",
            "subset",
            "observations",
            "avg_126d_excess_spy",
            "positive_rate_126d_excess_spy",
            "segment_review_candidate",
            "used_forward_return_in_ranking",
            "policy_eligible",
        ])
    out = rows.copy()
    for col in ("observations", "avg_126d_excess_spy", "positive_rate_126d_excess_spy"):
        out[col] = pd.to_numeric(out.get(col), errors="coerce").fillna(0.0)
    out["segment_review_candidate"] = (
        out.get("subset", "").astype(str).eq("high_signal")
        & out["observations"].ge(3)
        & out["avg_126d_excess_spy"].gt(0.0)
        & out["positive_rate_126d_excess_spy"].ge(0.60)
    )
    out["used_forward_return_in_ranking"] = False
    out["policy_eligible"] = False
    return out.sort_values(
        ["segment_review_candidate", "observations", "avg_126d_excess_spy"],
        ascending=[False, False, False],
    )


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Fusion Candidate Review",
        "",
        "Research-only intersection of independent diagnostics.",
        "",
        "Forward returns are audit labels only. They are not used in ranking,",
        "target construction, cash policy, production decisions, or live signals.",
        "",
        f"- status: `{payload.get('status')}`",
        f"- fusion_review_candidate_count: {payload.get('fusion_review_candidate_count', 0)}",
        f"- segment_review_candidate_count: {payload.get('segment_review_candidate_count', 0)}",
        f"- used_forward_return_in_ranking: `{payload.get('used_forward_return_in_ranking')}`",
        f"- outcome_selected_candidate_count: {payload.get('outcome_selected_candidate_count', 0)}",
        f"- forward_blind_policy_design_required: `{payload.get('forward_blind_policy_design_required')}`",
        f"- full_population_walkforward_required: `{payload.get('full_population_walkforward_required')}`",
        "",
        "## Inputs",
        "",
    ]
    for name, block in payload.get("inputs", {}).items():
        lines.append(f"- {name}: rows={block.get('rows', 0)} path=`{block.get('path')}`")
    lines.extend([
        "",
        "## Interpretation",
        "",
        "- `fusion_review_candidate=true` means at least two independent diagnostics",
        "  point to the same ticker and at least one source is PIT signal evidence.",
        "- `policy_eligible=false` is intentional. A future policy still needs a",
        "  default-OFF implementation and broker-ledger A/B acceptance.",
        "- Outcome-selected sources such as positive realized contribution are",
        "  confirmatory diagnostics only. They may bias the review queue toward",
        "  past winners, so any derived predicate must be designed forward-blind",
        "  from PIT columns and validated on the full candidate population.",
    ])
    return "\n".join(lines) + "\n"


def run(base_dir: Path, output_dir: Path) -> dict[str, Any]:
    base_dir = repo_path(base_dir)
    output_dir = repo_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    input_counts = {
        "right_tail_entry_signal_audit/winner_entry_signals.csv": load_entry_signals(base_dir, candidates),
        "right_tail_entry_signal_audit/drop_signal_reviews.csv": load_drop_signal_reviews(base_dir, candidates),
        "right_tail_drop_counterfactual_audit/drop_counterfactuals.csv": load_drop_counterfactuals(base_dir, candidates),
        "concentrated_cap_replacement_audit/top_missed_cap_replacement.csv": load_cap_replacement(base_dir, candidates),
        "alpha_beta_attribution/*/name_contribution.csv": load_name_contribution(base_dir, candidates),
    }
    candidate_frame = normalize_candidate_rows(candidates)
    segment_frame = load_segment_summary(base_dir)
    candidate_frame.to_csv(output_dir / "candidate_signals.csv", index=False)
    segment_frame.to_csv(output_dir / "segment_fusion_summary.csv", index=False)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_dir": str(base_dir),
        "research_only": True,
        "policy_eligible": False,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "used_forward_return_in_ranking": False,
        "forward_blind_policy_design_required": True,
        "full_population_walkforward_required": True,
        "fusion_review_candidate_count": int(candidate_frame.get("fusion_review_candidate", pd.Series(dtype=bool)).astype(bool).sum()) if not candidate_frame.empty else 0,
        "segment_review_candidate_count": int(segment_frame.get("segment_review_candidate", pd.Series(dtype=bool)).astype(bool).sum()) if not segment_frame.empty else 0,
        "outcome_selected_candidate_count": (
            int(
                candidate_frame[
                    candidate_frame.get("fusion_review_candidate", pd.Series(dtype=bool)).astype(bool)
                    & candidate_frame.get("has_outcome_selected_source", pd.Series(dtype=bool)).astype(bool)
                ].shape[0]
            )
            if not candidate_frame.empty
            else 0
        ),
        "queue_bias_warning": "candidate queue may be outcome-selected when positive_name_contribution is present; derived policies require forward-blind PIT design and full-population walk-forward validation",
        "candidate_signals_path": str(output_dir / "candidate_signals.csv"),
        "segment_fusion_summary_path": str(output_dir / "segment_fusion_summary.csv"),
        "inputs": {
            key: {"rows": int(value), "path": str(base_dir / key.replace("*", "<portfolio>"))}
            for key, value in input_counts.items()
        },
    }
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", default="outputs")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    payload = run(repo_path(args.base_dir), repo_path(args.output_dir))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

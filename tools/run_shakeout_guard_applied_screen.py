#!/usr/bin/env python3
"""Fast applied-count screen for SHAKEOUT_GUARD.

This is a target-book/candidate-row diagnostic, not a broker replay. It answers
one question before any expensive A/B:

    Would PHASE_SHAKEOUT_GUARD_PROD_ENABLED actually suppress any prior-holding
    TRIM/WARNING decisions on the clean 7Y candidate/target substrate?

If the answer is zero, do not run broker A/B.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_alphaops_vnext_policy_replay import (  # noqa: E402
    DEFAULT_CONCENTRATED_TARGET_N,
    DEFAULT_MAIN_TARGET_N,
    holding_state,
    score_month,
    shakeout_guard_prod_decision,
)
from tools.run_market_leader_challenger import normalize_candidate_frame, read_table, resolve_candidate_book  # noqa: E402

SCHEMA_VERSION = "shakeout-guard-applied-screen-v1"
CASH_TICKERS = {"CASH", "__CASH__"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if pd.isna(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


@contextmanager
def patched_env(updates: dict[str, str | None]) -> Iterator[None]:
    old = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def target_book_path(latest_run: Path, portfolio: str, explicit: str | None = None) -> Path:
    if explicit:
        return repo_path(explicit)
    candidates = [
        latest_run / "reports" / f"operating_{portfolio}_target_book.csv",
        latest_run / "alphaops_vnext" / f"official_{portfolio}_target_book.csv",
        latest_run / "market_leader_challenger" / f"{portfolio}_target_book.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def load_target_book(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    d = pd.read_csv(path)
    if d.empty or "rebalance_date" not in d.columns or "ticker" not in d.columns:
        return pd.DataFrame()
    d = d.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d = d[d["rebalance_date"].notna()]
    d = d[~d["ticker"].isin(CASH_TICKERS)]
    return d


def prior_holdings_by_date(book: pd.DataFrame) -> dict[pd.Timestamp, set[str]]:
    out: dict[pd.Timestamp, set[str]] = {}
    if book.empty:
        return out
    dates = sorted(pd.to_datetime(book["rebalance_date"], errors="coerce").dropna().unique())
    previous: set[str] = set()
    for raw_dt in dates:
        dt = pd.Timestamp(raw_dt).normalize()
        out[dt] = set(previous)
        current = set(book.loc[book["rebalance_date"].eq(dt), "ticker"].dropna().astype(str).str.upper())
        previous = current
    return out


def screen_portfolio(
    candidate: pd.DataFrame,
    target_book: pd.DataFrame,
    *,
    portfolio: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if candidate.empty or target_book.empty:
        return rows, {
            "portfolio": portfolio,
            "status": "blocked",
            "reason": "missing_candidate_or_target_book",
            "prior_holding_evaluated_rows": 0,
            "suppressed_rows": 0,
        }
    candidate = candidate.copy()
    target_book = target_book.copy()
    candidate["rebalance_date"] = pd.to_datetime(candidate["rebalance_date"], errors="coerce").dt.normalize()
    target_book["rebalance_date"] = pd.to_datetime(target_book["rebalance_date"], errors="coerce").dt.normalize()
    candidate = candidate[candidate["rebalance_date"].notna()]
    target_book = target_book[target_book["rebalance_date"].notna()]
    prior_by_date = prior_holdings_by_date(target_book)
    evaluated = 0
    protected = 0
    suppressed = 0
    month_count = 0
    baseline_states: Counter[str] = Counter()
    on_states: Counter[str] = Counter()
    guard_block_reasons: Counter[str] = Counter()
    guard_classifier_states: Counter[str] = Counter()
    leader_tiers: Counter[str] = Counter()
    benchmark_tier_candidate_states: Counter[str] = Counter()
    loose_abs_1m_candidate_states: Counter[str] = Counter()
    benchmark_tier_candidate_rows = 0
    loose_abs_1m_candidate_rows = 0
    for raw_dt in sorted(pd.to_datetime(candidate["rebalance_date"], errors="coerce").dropna().unique()):
        dt = pd.Timestamp(raw_dt).normalize()
        prior = prior_by_date.get(dt, set())
        if not prior:
            continue
        month_raw = candidate[candidate["rebalance_date"].eq(dt)].copy()
        if month_raw.empty:
            continue
        month_count += 1
        month = score_month(month_raw)
        score_sigma = float(pd.to_numeric(month["alphaops_vnext_score"], errors="coerce").std(ddof=0) or 0.0)
        score_median = float(pd.to_numeric(month["alphaops_vnext_score"], errors="coerce").median() or 0.0)
        month["ticker"] = month["ticker"].astype(str).str.upper().str.strip()
        for _, row in month[month["ticker"].isin(prior)].iterrows():
            rec = row.to_dict()
            ticker = str(rec.get("ticker") or "").upper()
            if not ticker or ticker in CASH_TICKERS:
                continue
            rec["shakeout_guard_prior_holding"] = True
            evaluated += 1
            with patched_env({"PHASE_SHAKEOUT_GUARD_PROD_ENABLED": "0"}):
                base_state, base_reason = holding_state(rec, score_median, score_sigma)
            with patched_env(
                {
                    "PHASE_SHAKEOUT_GUARD_PROD_ENABLED": "1",
                    "PHASE_SHAKEOUT_GUARD_WARNING_SUPPRESS_ENABLED": "0",
                }
            ):
                on_state, on_reason = holding_state(rec, score_median, score_sigma)
                decision = shakeout_guard_prod_decision(rec, applied=str(on_reason).startswith("shakeout_guard_prod_suppressed_"))
            baseline_states[str(base_state)] += 1
            on_states[str(on_state)] += 1
            guard_block_reasons[str(decision.block_reason or "protected_not_applied" if decision.protected else decision.block_reason or "unknown")] += 1
            guard_classifier_states[str(decision.classifier_state or "not_evaluated")] += 1
            leader_tiers[str(rec.get("leader_tier") or "unknown")] += 1
            if decision.protected:
                protected += 1
            benchmark_tier_candidate = (
                safe_float(rec.get("rs_benchmark_3m")) > 0.0
                and safe_float(rec.get("rs_benchmark_6m")) > 0.0
                and safe_float(rec.get("sector_leadership_score")) > 0.0
                and safe_float(rec.get("smart_money_evidence_confidence")) >= 0.25
                and safe_float(rec.get("price_above_ma200"), 1.0) >= 0.5
            )
            if benchmark_tier_candidate:
                benchmark_tier_candidate_rows += 1
                benchmark_tier_candidate_states[str(base_state)] += 1
                if safe_float(rec.get("r_1m")) < 0.0:
                    loose_abs_1m_candidate_rows += 1
                    loose_abs_1m_candidate_states[str(base_state)] += 1
            if str(on_reason).startswith("shakeout_guard_prod_suppressed_"):
                suppressed += 1
                rows.append(
                    {
                        "portfolio": portfolio,
                        "rebalance_date": dt.date().isoformat(),
                        "ticker": ticker,
                        "baseline_state": base_state,
                        "baseline_reason": base_reason,
                        "shakeout_state": on_state,
                        "shakeout_reason": on_reason,
                        "leader_tier": rec.get("leader_tier"),
                        "sector_leadership_score": safe_float(rec.get("sector_leadership_score")),
                        "smart_money_evidence_confidence": safe_float(rec.get("smart_money_evidence_confidence")),
                        "rs_benchmark_1m": safe_float(rec.get("rs_benchmark_1m")),
                        "rs_benchmark_3m": safe_float(rec.get("rs_benchmark_3m")),
                        "rs_benchmark_6m": safe_float(rec.get("rs_benchmark_6m")),
                        "rs_qqq_1m": safe_float(rec.get("rs_qqq_1m")),
                        "rs_qqq_3m": safe_float(rec.get("rs_qqq_3m")),
                        "rs_qqq_6m": safe_float(rec.get("rs_qqq_6m")),
                        "classifier_reason": decision.classifier_reason,
                        "fallback_source": decision.fallback_source,
                    }
                )
    return rows, {
        "portfolio": portfolio,
        "status": "screen_passed" if suppressed else "no_applied_rows",
        "month_count_with_prior_holdings": int(month_count),
        "prior_holding_evaluated_rows": int(evaluated),
        "protected_rows": int(protected),
        "suppressed_rows": int(suppressed),
        "baseline_state_counts": dict(sorted(baseline_states.items())),
        "shakeout_state_counts": dict(sorted(on_states.items())),
        "guard_block_reason_counts": dict(sorted(guard_block_reasons.items())),
        "guard_classifier_state_counts": dict(sorted(guard_classifier_states.items())),
        "leader_tier_counts": dict(sorted(leader_tiers.items())),
        "benchmark_tier_candidate_rows": int(benchmark_tier_candidate_rows),
        "benchmark_tier_candidate_baseline_state_counts": dict(sorted(benchmark_tier_candidate_states.items())),
        "loose_abs_1m_candidate_rows": int(loose_abs_1m_candidate_rows),
        "loose_abs_1m_candidate_baseline_state_counts": dict(sorted(loose_abs_1m_candidate_states.items())),
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# SHAKEOUT_GUARD Applied Screen",
        "",
        f"- status: `{payload.get('status')}`",
        f"- candidate source: `{payload.get('candidate_source_mode')}`",
        f"- candidate book: `{payload.get('candidate_book')}`",
        "",
        "## Portfolio Summary",
        "",
    ]
    for item in payload.get("portfolios", {}).values():
        lines.extend(
            [
                f"### {item.get('portfolio')}",
                "",
                f"- status: `{item.get('status')}`",
                f"- prior rows evaluated: `{item.get('prior_holding_evaluated_rows')}`",
                f"- protected rows: `{item.get('protected_rows')}`",
                f"- suppressed rows: `{item.get('suppressed_rows')}`",
                f"- baseline states: `{item.get('baseline_state_counts', {})}`",
                f"- guard block reasons: `{item.get('guard_block_reason_counts', {})}`",
                f"- benchmark-tier fallback candidates: `{item.get('benchmark_tier_candidate_rows')}` / states `{item.get('benchmark_tier_candidate_baseline_state_counts', {})}`",
                f"- loose absolute-1m candidates: `{item.get('loose_abs_1m_candidate_rows')}` / states `{item.get('loose_abs_1m_candidate_baseline_state_counts', {})}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation",
            "",
            "- If suppressed rows are `0`, do not run SHAKEOUT broker A/B.",
            "- If suppressed rows are positive, run broker-ledger A/B before claiming any CAGR/MDD effect.",
            "- This screen does not mutate target books or production state.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--candidate-book", default="")
    parser.add_argument("--main-target-book", default="")
    parser.add_argument("--concentrated-target-book", default="")
    parser.add_argument("--output-dir", default="outputs/shakeout_guard_applied_screen")
    args = parser.parse_args()

    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    candidate_path, source_mode = resolve_candidate_book(latest_run, args.candidate_book or None)
    candidate = normalize_candidate_frame(read_table(candidate_path))
    main_book_path = target_book_path(latest_run, "main", args.main_target_book or None)
    concentrated_book_path = target_book_path(latest_run, "concentrated", args.concentrated_target_book or None)
    main_book = load_target_book(main_book_path)
    concentrated_book = load_target_book(concentrated_book_path)

    all_rows: list[dict[str, Any]] = []
    portfolios: dict[str, Any] = {}
    for portfolio, book in [("main", main_book), ("concentrated", concentrated_book)]:
        rows, summary = screen_portfolio(candidate, book, portfolio=portfolio)
        all_rows.extend(rows)
        portfolios[portfolio] = summary

    total_suppressed = sum(int(item.get("suppressed_rows", 0)) for item in portfolios.values())
    total_evaluated = sum(int(item.get("prior_holding_evaluated_rows", 0)) for item in portfolios.values())
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "applied_rows_found" if total_suppressed else "no_applied_rows",
        "latest_run": str(latest_run),
        "candidate_book": str(candidate_path),
        "candidate_source_mode": source_mode,
        "candidate_rows": int(len(candidate)),
        "main_target_book": str(main_book_path),
        "concentrated_target_book": str(concentrated_book_path),
        "total_prior_holding_evaluated_rows": int(total_evaluated),
        "total_suppressed_rows": int(total_suppressed),
        "portfolios": portfolios,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "next_action": "run_broker_ab" if total_suppressed else "do_not_run_broker_ab",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", payload)
    write_csv(output_dir / "suppressed_rows.csv", pd.DataFrame(all_rows))
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

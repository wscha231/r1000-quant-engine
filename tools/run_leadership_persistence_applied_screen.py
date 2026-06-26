#!/usr/bin/env python3
"""Fast applied-count screen for leadership-persistence hold.

This is a target-book/candidate-row diagnostic, not a broker replay. It answers
whether the existing PHASE_LEADERSHIP_PERSISTENCE_HOLD gate can actually change
replacement decisions on the clean 7Y substrate before any expensive A/B.

The screen uses only PIT candidate rows and official target-book prior holdings.
It does not mutate policy targets, cash policy, broker replay, workflows, or
live trading.
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
    allowed_candidate,
    apply_concentrated_leader_gate_annotations,
    apply_crisis_lane_policy,
    crisis_state_for_date,
    holding_state,
    leadership_persistence_hold_protected,
    replacement_gap_for_weakest,
    score_month,
)
from tools.run_market_leader_challenger import normalize_candidate_frame, read_table, resolve_candidate_book  # noqa: E402

SCHEMA_VERSION = "leadership-persistence-applied-screen-v1"
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


def clean_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except TypeError:
        pass
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n", "", "nan", "none", "null"}:
        return False
    return default


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def sanitize_policy_record(rec: dict[str, Any]) -> dict[str, Any]:
    """Normalize CSV-loaded policy fields to their in-replay semantics."""

    out = dict(rec)
    out["ticker"] = clean_ticker(out.get("ticker"))
    out["top7_standalone_blocked"] = safe_bool(out.get("top7_standalone_blocked"), False)
    out["emerging_tenbagger_hard_reject_reason"] = clean_text(out.get("emerging_tenbagger_hard_reject_reason"))
    return out


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
    d = pd.read_csv(path, low_memory=False)
    if d.empty or "rebalance_date" not in d.columns or "ticker" not in d.columns:
        return pd.DataFrame()
    d = d.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].map(clean_ticker)
    d = d[d["rebalance_date"].notna()]
    d = d[~d["ticker"].isin(CASH_TICKERS)]
    return d


def load_crisis_states(latest_run: Path) -> pd.DataFrame:
    for rel in [
        "alphaops_vnext/crisis_state_audit.csv",
        "alphaops_vnext/daily_crisis_state.csv",
        "crisis_monitor/daily_crisis_state.csv",
    ]:
        path = latest_run / rel
        if path.exists():
            d = pd.read_csv(path)
            if "date" in d.columns:
                d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
                return d[d["date"].notna()].copy()
    return pd.DataFrame()


def candidate_input_diagnostics(candidate: pd.DataFrame, latest_run: Path) -> dict[str, Any]:
    required_cols = [
        "rs_spy_3m",
        "rs_qqq_3m",
        "rs_spy_6m",
        "rs_qqq_6m",
        "leader_tier",
        "sector_leadership_score",
        "smart_money_evidence_confidence",
    ]
    present = {col: bool(col in candidate.columns) for col in required_cols}
    missing = [col for col, ok in present.items() if not ok]
    rejected_path = latest_run / "alphaops_vnext" / "rejected_by_reason.csv"
    return {
        "required_columns_present": present,
        "missing_required_columns": missing,
        "has_alphaops_rejected_by_reason": rejected_path.exists(),
        "alphaops_rejected_by_reason_path": str(rejected_path),
        "screen_input_quality": "usable" if not missing and rejected_path.exists() else "limited",
    }


def official_sets_by_date(book: pd.DataFrame) -> dict[pd.Timestamp, set[str]]:
    out: dict[pd.Timestamp, set[str]] = {}
    if book.empty:
        return out
    for raw_dt, group in book.groupby("rebalance_date"):
        dt = pd.Timestamp(raw_dt).normalize()
        out[dt] = set(group["ticker"].dropna().map(clean_ticker)) - CASH_TICKERS
    return out


def prior_weights_by_date(book: pd.DataFrame) -> dict[pd.Timestamp, dict[str, float]]:
    out: dict[pd.Timestamp, dict[str, float]] = {}
    if book.empty:
        return out
    dates = sorted(pd.to_datetime(book["rebalance_date"], errors="coerce").dropna().unique())
    previous: dict[str, float] = {}
    weight_col = "weight" if "weight" in book.columns else "target_weight"
    for raw_dt in dates:
        dt = pd.Timestamp(raw_dt).normalize()
        out[dt] = dict(previous)
        current: dict[str, float] = {}
        for _, row in book[book["rebalance_date"].eq(dt)].iterrows():
            ticker = clean_ticker(row.get("ticker"))
            if ticker and ticker not in CASH_TICKERS:
                current[ticker] = safe_float(row.get(weight_col), 0.0)
        previous = current
    return out


def score_key(rec: dict[str, Any]) -> float:
    return safe_float(rec.get("alphaops_vnext_weight_score"), safe_float(rec.get("alphaops_vnext_score")))


def replacement_delta_payload(
    *,
    portfolio: str,
    rebalance_date: pd.Timestamp,
    candidate: dict[str, Any],
    weakest: dict[str, Any],
    threshold_normal: float,
    required_gap: float,
    gap_reason: str,
) -> dict[str, Any]:
    candidate_score = safe_float(candidate.get("alphaops_vnext_score"))
    weakest_score = safe_float(weakest.get("alphaops_vnext_score"))
    would_pass_standard = candidate_score >= weakest_score + threshold_normal
    passes_current = candidate_score >= weakest_score + required_gap
    return {
        "portfolio": portfolio,
        "rebalance_date": rebalance_date.date().isoformat(),
        "candidate_ticker": clean_ticker(candidate.get("ticker")),
        "candidate_score": candidate_score,
        "weakest_ticker": clean_ticker(weakest.get("ticker")),
        "weakest_score": weakest_score,
        "weakest_leader_tier": weakest.get("leader_tier"),
        "weakest_prior_weight": safe_float(weakest.get("prior_weight")),
        "threshold_normal": float(threshold_normal),
        "required_gap": float(required_gap),
        "gap_reason": gap_reason,
        "would_pass_standard": bool(would_pass_standard),
        "passes_persistence_gap": bool(passes_current),
        "behavior_delta": bool(would_pass_standard and not passes_current),
        "weakest_rs_benchmark_3m": safe_float(weakest.get("rs_benchmark_3m")),
        "weakest_rs_benchmark_6m": safe_float(weakest.get("rs_benchmark_6m")),
    }


def summarize_match(selected_by_date: dict[pd.Timestamp, set[str]], official_by_date: dict[pd.Timestamp, set[str]]) -> dict[str, Any]:
    overlaps: list[float] = []
    exact = 0
    compared = 0
    for dt, official in official_by_date.items():
        selected = selected_by_date.get(dt, set())
        if not official and not selected:
            continue
        compared += 1
        if selected == official:
            exact += 1
        denom = len(selected | official)
        overlaps.append((len(selected & official) / denom) if denom else 1.0)
    return {
        "dates_compared": int(compared),
        "exact_date_matches": int(exact),
        "exact_date_match_rate": float(exact / compared) if compared else None,
        "avg_jaccard_match": float(sum(overlaps) / len(overlaps)) if overlaps else None,
    }


def simulate_portfolio(
    candidate: pd.DataFrame,
    target_book: pd.DataFrame,
    crisis_states: pd.DataFrame,
    *,
    portfolio: str,
    target_n: int,
    enable_persistence: bool,
) -> tuple[dict[pd.Timestamp, set[str]], list[dict[str, Any]], dict[str, Any]]:
    selected_by_date: dict[pd.Timestamp, set[str]] = {}
    rows: list[dict[str, Any]] = []
    if candidate.empty or target_book.empty:
        return selected_by_date, rows, {
            "status": "blocked",
            "reason": "missing_candidate_or_target_book",
        }

    candidate = candidate.copy()
    candidate["rebalance_date"] = pd.to_datetime(candidate["rebalance_date"], errors="coerce").dt.normalize()
    candidate["ticker"] = candidate["ticker"].map(clean_ticker)
    candidate = candidate[candidate["rebalance_date"].notna()]
    prior_by_date = prior_weights_by_date(target_book)

    env_value = "1" if enable_persistence else "0"
    protected_prior_rows = 0
    applied_tests = 0
    marginal_blocked = 0
    allowed_despite_applied = 0
    replacement_tests = 0
    month_count = 0
    protection_reasons: Counter[str] = Counter()
    selected_counts: Counter[str] = Counter()

    with patched_env({"PHASE_LEADERSHIP_PERSISTENCE_HOLD_ENABLED": env_value}):
        for raw_dt in sorted(pd.to_datetime(candidate["rebalance_date"], errors="coerce").dropna().unique()):
            dt = pd.Timestamp(raw_dt).normalize()
            prior_weights = prior_by_date.get(dt, {})
            if not prior_weights:
                continue
            month_raw = candidate[candidate["rebalance_date"].eq(dt)].copy()
            if month_raw.empty:
                continue
            month_count += 1
            month = score_month(month_raw)
            crisis_row = crisis_state_for_date(crisis_states, dt)
            month = apply_crisis_lane_policy(month, crisis_row, portfolio)
            month = apply_concentrated_leader_gate_annotations(month, portfolio, target_n)
            score_sigma = float(pd.to_numeric(month["alphaops_vnext_score"], errors="coerce").std(ddof=0) or 0.0)
            score_median = float(pd.to_numeric(month["alphaops_vnext_score"], errors="coerce").median() or 0.0)
            month_records = [sanitize_policy_record(rec) for rec in month.to_dict("records")]
            by_ticker = {clean_ticker(rec.get("ticker")): rec for rec in month_records}
            selected: list[dict[str, Any]] = []
            selected_tickers: set[str] = set()
            emerging_count = 0
            for ticker, prior_weight in sorted(prior_weights.items(), key=lambda item: -item[1]):
                rec = by_ticker.get(ticker)
                if not rec:
                    continue
                state, state_reason = holding_state(rec, score_median, score_sigma)
                if state == "EXIT":
                    continue
                ok, _reason = allowed_candidate(rec, portfolio, emerging_count, is_new_buy=False)
                if not ok:
                    continue
                out = dict(rec)
                out["holding_state"] = state
                out["holding_state_reason"] = state_reason
                out["hold_replace_decision"] = "keep_prior_holding"
                out["prior_weight"] = float(prior_weight)
                protected, protection_reason = leadership_persistence_hold_protected(out, portfolio_kind=portfolio)
                protection_reasons[str(protection_reason)] += 1
                if protected:
                    protected_prior_rows += 1
                selected.append(out)
                selected_tickers.add(ticker)
                if str(rec.get("primary_lane")) in {"EMERGING_TENBAGGER", "TOP7_MANAGER_DISCOVERY"}:
                    emerging_count += 1
                if len(selected) >= target_n:
                    break

            ranked = sorted(month_records, key=score_key, reverse=True)
            threshold_normal = max(0.15, 0.75 * max(score_sigma, 0.20))
            threshold_broken = max(0.08, 0.35 * max(score_sigma, 0.20))
            for rec in ranked:
                ticker = clean_ticker(rec.get("ticker"))
                if not ticker or ticker in selected_tickers or ticker in CASH_TICKERS:
                    continue
                ok, _reason = allowed_candidate(rec, portfolio, emerging_count, is_new_buy=True)
                if not ok:
                    continue
                out = dict(rec)
                out["holding_state"] = "NEW"
                out["holding_state_reason"] = "new_candidate_cleared_vnext_gates"
                out["hold_replace_decision"] = "new_entry"
                if len(selected) < target_n:
                    selected.append(out)
                    selected_tickers.add(ticker)
                    if str(rec.get("primary_lane")) in {"EMERGING_TENBAGGER", "TOP7_MANAGER_DISCOVERY"}:
                        emerging_count += 1
                    continue

                weakest_idx = min(range(len(selected)), key=lambda i: safe_float(selected[i].get("alphaops_vnext_score")))
                weakest = selected[weakest_idx]
                required_gap, gap_reason, persistence_applied = replacement_gap_for_weakest(
                    weakest,
                    portfolio_kind=portfolio,
                    threshold_normal=threshold_normal,
                    threshold_broken=threshold_broken,
                    score_sigma=score_sigma,
                )
                replacement_tests += 1
                candidate_score = safe_float(rec.get("alphaops_vnext_score"))
                weakest_score = safe_float(weakest.get("alphaops_vnext_score"))
                would_pass_standard = candidate_score >= weakest_score + threshold_normal
                passes_current = candidate_score >= weakest_score + required_gap
                if persistence_applied:
                    applied_tests += 1
                    delta_row = replacement_delta_payload(
                        portfolio=portfolio,
                        rebalance_date=dt,
                        candidate=rec,
                        weakest=weakest,
                        threshold_normal=threshold_normal,
                        required_gap=required_gap,
                        gap_reason=gap_reason,
                    )
                    rows.append(delta_row)
                    if would_pass_standard and not passes_current:
                        marginal_blocked += 1
                    elif passes_current:
                        allowed_despite_applied += 1
                if passes_current:
                    selected_tickers.discard(clean_ticker(weakest.get("ticker")))
                    selected[weakest_idx] = out
                    selected_tickers.add(ticker)

            selected_set = {clean_ticker(row.get("ticker")) for row in selected if clean_ticker(row.get("ticker"))}
            selected_by_date[dt] = selected_set - CASH_TICKERS
            selected_counts.update(selected_by_date[dt])

    return selected_by_date, rows, {
        "status": "screen_passed" if marginal_blocked else ("applied_without_behavior_delta" if applied_tests else "no_applied_rows"),
        "month_count_with_prior_holdings": int(month_count),
        "protected_prior_rows": int(protected_prior_rows),
        "replacement_tests": int(replacement_tests),
        "applied_to_replacement_tests": int(applied_tests),
        "marginal_blocked_replacements": int(marginal_blocked),
        "allowed_replacements_despite_persistence": int(allowed_despite_applied),
        "protection_reason_counts": dict(sorted(protection_reasons.items())),
        "selected_ticker_top10": dict(selected_counts.most_common(10)),
    }


def screen_portfolio(
    candidate: pd.DataFrame,
    target_book: pd.DataFrame,
    crisis_states: pd.DataFrame,
    *,
    portfolio: str,
    target_n: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    official_by_date = official_sets_by_date(target_book)
    off_selected, _off_rows, off_summary = simulate_portfolio(
        candidate,
        target_book,
        crisis_states,
        portfolio=portfolio,
        target_n=target_n,
        enable_persistence=False,
    )
    on_selected, rows, on_summary = simulate_portfolio(
        candidate,
        target_book,
        crisis_states,
        portfolio=portfolio,
        target_n=target_n,
        enable_persistence=True,
    )
    match = summarize_match(off_selected, official_by_date)
    changed_dates = sum(1 for dt, names in on_selected.items() if names != off_selected.get(dt, set()))
    avg_jaccard = match.get("avg_jaccard_match")
    screen_fidelity_ok = avg_jaccard is not None and float(avg_jaccard) >= 0.90
    next_action = "do_not_run_broker_ab"
    if not screen_fidelity_ok:
        next_action = "fix_screen_fidelity_before_ab"
    elif int(on_summary.get("marginal_blocked_replacements", 0)) > 0:
        next_action = "eligible_for_target_book_ab"
    summary = {
        "portfolio": portfolio,
        "status": on_summary.get("status"),
        "screen_fidelity_ok": bool(screen_fidelity_ok),
        "next_action": next_action,
        "off_replay_match_to_official": match,
        "on_vs_off_changed_dates": int(changed_dates),
        "off_summary": off_summary,
        "on_summary": on_summary,
    }
    return rows, summary


def build_report(payload: dict[str, Any]) -> str:
    input_diag = payload.get("candidate_input_diagnostics", {})
    lines = [
        "# Leadership Persistence Applied Screen",
        "",
        "Research-only diagnostic. This is not a broker replay and does not mutate production policy.",
        "",
        f"- generated_at_utc: {payload['generated_at_utc']}",
        f"- source_candidate_book: {payload.get('candidate_book_source')}",
        f"- candidate_input_quality: {input_diag.get('screen_input_quality')}",
        f"- missing_required_columns: {', '.join(input_diag.get('missing_required_columns') or []) or 'none'}",
        f"- alphaops_rejected_by_reason_present: {input_diag.get('has_alphaops_rejected_by_reason')}",
        f"- next_action: {payload.get('next_action')}",
        "",
        "## Portfolio Summary",
        "",
        "| portfolio | status | fidelity_ok | protected_prior | applied_tests | marginal_blocked | changed_dates | next_action |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in payload.get("portfolios", []):
        on = item.get("on_summary", {})
        lines.append(
            "| {portfolio} | {status} | {fidelity} | {protected} | {applied} | {blocked} | {changed} | {next_action} |".format(
                portfolio=item.get("portfolio"),
                status=item.get("status"),
                fidelity=item.get("screen_fidelity_ok"),
                protected=on.get("protected_prior_rows", 0),
                applied=on.get("applied_to_replacement_tests", 0),
                blocked=on.get("marginal_blocked_replacements", 0),
                changed=item.get("on_vs_off_changed_dates", 0),
                next_action=item.get("next_action"),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- If `marginal_blocked_replacements` is zero, do not run a broker A/B for this lever.",
            "- If `screen_fidelity_ok` is false, improve the screen before using it for decisions.",
            "- If candidate input quality is limited, rerun target-book-only replay after RS/leader-tier carry-through or use `rejected_by_reason.csv` telemetry.",
            "- A positive screen only permits target-book A/B; broker acceptance still requires broker_ledger_next_close.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs", help="Full rebuild output directory to inspect.")
    parser.add_argument("--output-dir", default="outputs/leadership_persistence_applied_screen")
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--main-target-book", default=None)
    parser.add_argument("--concentrated-target-book", default=None)
    args = parser.parse_args()

    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    candidate_path, source_mode = resolve_candidate_book(latest_run, args.candidate_book or None)
    candidate = normalize_candidate_frame(read_table(candidate_path))
    input_diag = candidate_input_diagnostics(candidate, latest_run)
    crisis_states = load_crisis_states(latest_run)
    portfolio_specs = [
        ("main", DEFAULT_MAIN_TARGET_N, target_book_path(latest_run, "main", args.main_target_book)),
        (
            "concentrated",
            DEFAULT_CONCENTRATED_TARGET_N,
            target_book_path(latest_run, "concentrated", args.concentrated_target_book),
        ),
    ]

    all_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for portfolio, target_n, book_path in portfolio_specs:
        target_book = load_target_book(book_path)
        rows, summary = screen_portfolio(
            candidate,
            target_book,
            crisis_states,
            portfolio=portfolio,
            target_n=target_n,
        )
        summary["target_book_source"] = str(book_path)
        summaries.append(summary)
        all_rows.extend(rows)

    next_action = "do_not_run_broker_ab"
    if any(item.get("next_action") == "fix_screen_fidelity_before_ab" for item in summaries):
        next_action = "fix_screen_fidelity_before_ab"
    elif any(item.get("next_action") == "eligible_for_target_book_ab" for item in summaries):
        next_action = "eligible_for_target_book_ab"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "research_only": True,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "broker_replay_executed": False,
        "candidate_book_source": str(candidate_path),
        "candidate_source_mode": source_mode,
        "candidate_input_diagnostics": input_diag,
        "next_action": next_action,
        "portfolios": summaries,
    }
    rows_frame = pd.DataFrame(all_rows)
    write_json(output_dir / "summary.json", payload)
    write_csv(output_dir / "applied_replacement_tests.csv", rows_frame)
    (output_dir / "report.md").write_text(build_report(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

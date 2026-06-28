#!/usr/bin/env python3
"""Target-book drop leak screen for hold-duration research.

This diagnostic reads official target books and the entry/exit timing audit to
identify names that were dropped from the target book and later outperformed the
same-day replacement basket. Forward returns are audit labels only; they are not
used to rank live candidates or mutate policy.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_VERSION = "hold-duration-leak-screen-v1"
CASH_TICKERS = {"CASH", "__CASH__"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


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


def load_premature_audit(latest_run: Path) -> pd.DataFrame:
    path = latest_run / "entry_exit_timing_audit" / "premature_sell_counterfactual.csv"
    if not path.exists():
        return pd.DataFrame()
    d = pd.read_csv(path)
    required = {"portfolio", "ticker", "sell_date"}
    if d.empty or not required.issubset(d.columns):
        return pd.DataFrame()
    d = d.copy()
    d["portfolio"] = d["portfolio"].astype(str).str.lower().str.strip()
    d["ticker"] = d["ticker"].map(clean_ticker)
    d["sell_date"] = pd.to_datetime(d["sell_date"], errors="coerce").dt.normalize()
    return d[d["sell_date"].notna()]


def audit_lookup(audit: pd.DataFrame, portfolio: str, ticker: str, drop_date: pd.Timestamp) -> dict[str, Any]:
    if audit.empty:
        return {}
    subset = audit[(audit["portfolio"].eq(portfolio)) & (audit["ticker"].eq(ticker))].copy()
    if subset.empty:
        return {}
    subset["lag_days"] = (subset["sell_date"] - drop_date).dt.days
    subset = subset[(subset["lag_days"] >= 0) & (subset["lag_days"] <= 10)]
    if subset.empty:
        return {}
    row = subset.sort_values("lag_days").iloc[0].to_dict()
    return row


def target_rows_by_date(book: pd.DataFrame) -> dict[pd.Timestamp, pd.DataFrame]:
    return {pd.Timestamp(dt).normalize(): group.copy() for dt, group in book.groupby("rebalance_date")}


def drop_rows_for_portfolio(book: pd.DataFrame, audit: pd.DataFrame, portfolio: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if book.empty:
        return rows
    by_date = target_rows_by_date(book)
    dates = sorted(by_date)
    for prev_dt, curr_dt in zip(dates, dates[1:]):
        prev = by_date[prev_dt]
        curr = by_date[curr_dt]
        prev_by_ticker = {clean_ticker(row.get("ticker")): row.to_dict() for _, row in prev.iterrows()}
        curr_names = set(curr["ticker"].map(clean_ticker))
        for ticker, prev_row in sorted(prev_by_ticker.items()):
            if not ticker or ticker in CASH_TICKERS or ticker in curr_names:
                continue
            matched = audit_lookup(audit, portfolio, ticker, curr_dt)
            excess_126d = safe_float(matched.get("premature_sell_excess_126d"), 0.0) if matched else None
            payload = {
                "portfolio": portfolio,
                "ticker": ticker,
                "prior_rebalance_date": prev_dt.date().isoformat(),
                "drop_rebalance_date": curr_dt.date().isoformat(),
                "prior_weight": safe_float(prev_row.get("weight"), safe_float(prev_row.get("target_weight"))),
                "prior_alphaops_vnext_score": safe_float(prev_row.get("alphaops_vnext_score")),
                "prior_holding_state": clean_text(prev_row.get("holding_state")),
                "prior_hold_replace_decision": clean_text(prev_row.get("hold_replace_decision")),
                "prior_leader_tier": clean_text(prev_row.get("leader_tier")),
                "prior_primary_lane": clean_text(prev_row.get("primary_lane")),
                "prior_rs_benchmark_3m": safe_float(prev_row.get("rs_benchmark_3m")),
                "prior_rs_benchmark_6m": safe_float(prev_row.get("rs_benchmark_6m")),
                "prior_rs_spy_3m": safe_float(prev_row.get("rs_spy_3m")),
                "prior_rs_qqq_3m": safe_float(prev_row.get("rs_qqq_3m")),
                "prior_price_above_ma200": safe_float(prev_row.get("price_above_ma200"), 0.0),
                "prior_price_above_ma50": safe_float(prev_row.get("price_above_ma50"), 0.0),
                "prior_actual_results_score": safe_float(prev_row.get("actual_results_score")),
                "prior_eps_revision_score": safe_float(prev_row.get("eps_revision_score")),
                "prior_revision_score": safe_float(prev_row.get("revision_score")),
                "prior_event_reaction_score": safe_float(prev_row.get("event_reaction_score")),
                "prior_regime_state": clean_text(prev_row.get("regime_state")),
                "audit_matched": bool(matched),
                "audit_sell_date": matched.get("sell_date") if matched else "",
                "audit_leader_state_at_exit": matched.get("leader_state_at_exit") if matched else "",
                "sold_forward_return_126d": matched.get("sold_forward_return_126d") if matched else None,
                "same_day_replacement_return_126d": matched.get("same_day_replacement_return_126d") if matched else None,
                "premature_sell_excess_126d": excess_126d,
                "premature_sell_candidate": bool(matched.get("premature_sell_candidate")) if matched else False,
            }
            payload["pit_leader_hold_candidate"] = bool(
                payload["prior_weight"] >= 0.02
                and payload["prior_holding_state"].upper() == "HOLD"
                and payload["prior_leader_tier"] in {"DUAL_LEADER", "SECTOR_LEADER"}
                and payload["prior_rs_benchmark_3m"] > 0.0
                and payload["prior_rs_benchmark_6m"] > 0.0
                and payload["prior_price_above_ma200"] >= 0.5
            )
            payload["positive_excess_126d"] = bool(excess_126d is not None and excess_126d > 0.0)
            rows.append(payload)
    return rows


def summarize_drops(rows: list[dict[str, Any]], portfolio: str) -> dict[str, Any]:
    d = pd.DataFrame(rows)
    if d.empty:
        return {
            "portfolio": portfolio,
            "dropped_rows": 0,
            "matched_audit_rows": 0,
            "pit_leader_hold_candidate_rows": 0,
        }
    matched = d[d["audit_matched"].astype(bool)]
    candidates = d[d["pit_leader_hold_candidate"].astype(bool)]
    candidate_matched = candidates[candidates["audit_matched"].astype(bool)]
    candidate_positive = candidate_matched[candidate_matched["positive_excess_126d"].astype(bool)]
    by_tier = Counter(d["prior_leader_tier"].astype(str))
    by_state = Counter(d["prior_holding_state"].astype(str))
    candidate_rate = float(len(candidate_positive) / len(candidate_matched)) if len(candidate_matched) else None
    candidate_mean = (
        float(pd.to_numeric(candidate_matched["premature_sell_excess_126d"], errors="coerce").mean())
        if len(candidate_matched)
        else None
    )
    if len(candidate_matched) == 0:
        candidate_verdict = "no_matched_pit_candidate_rows"
    elif candidate_mean is not None and candidate_mean > 0.0 and candidate_rate is not None and candidate_rate >= 0.55:
        candidate_verdict = "candidate_positive"
    else:
        candidate_verdict = "candidate_mixed_or_negative"
    return {
        "portfolio": portfolio,
        "dropped_rows": int(len(d)),
        "matched_audit_rows": int(len(matched)),
        "positive_excess_126d_rows": int(d["positive_excess_126d"].astype(bool).sum()),
        "mean_excess_126d_matched": float(pd.to_numeric(matched["premature_sell_excess_126d"], errors="coerce").mean()) if not matched.empty else None,
        "pit_leader_hold_candidate_rows": int(len(candidates)),
        "pit_leader_hold_candidate_matched_rows": int(len(candidate_matched)),
        "pit_leader_hold_candidate_positive_rows": int(len(candidate_positive)),
        "pit_leader_hold_candidate_positive_rate": candidate_rate,
        "pit_leader_hold_candidate_mean_excess_126d": candidate_mean,
        "pit_leader_hold_candidate_verdict": candidate_verdict,
        "prior_leader_tier_counts": dict(by_tier.most_common()),
        "prior_holding_state_counts": dict(by_state.most_common()),
    }


def build_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Hold Duration Leak Screen",
        "",
        "Research-only target-book drop audit. Forward returns are audit labels only.",
        "",
        f"- generated_at_utc: {payload['generated_at_utc']}",
        f"- next_action: {payload.get('next_action')}",
        "",
        "| portfolio | dropped | matched | PIT hold candidates | positive rate | mean 126d excess | verdict |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in payload.get("portfolios", []):
        lines.append(
            "| {portfolio} | {dropped} | {matched} | {candidates} | {rate} | {mean} | {verdict} |".format(
                portfolio=item.get("portfolio"),
                dropped=item.get("dropped_rows", 0),
                matched=item.get("matched_audit_rows", 0),
                candidates=item.get("pit_leader_hold_candidate_rows", 0),
                rate="" if item.get("pit_leader_hold_candidate_positive_rate") is None else f"{item['pit_leader_hold_candidate_positive_rate']:.2%}",
                mean="" if item.get("pit_leader_hold_candidate_mean_excess_126d") is None else f"{item['pit_leader_hold_candidate_mean_excess_126d']:.2%}",
                verdict=item.get("pit_leader_hold_candidate_verdict", ""),
            )
        )
    lines.extend(
        [
            "",
            "Interpretation:",
            "- Positive audit results are not live signals.",
            "- A PIT hold predicate must be validated with target-book and broker A/B before use.",
            "- If candidate rows are mixed or negative, discard broad hold-duration rescue and search for a narrower PIT predicate.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/hold_duration_leak_screen")
    parser.add_argument("--main-target-book", default=None)
    parser.add_argument("--concentrated-target-book", default=None)
    args = parser.parse_args()

    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    audit = load_premature_audit(latest_run)
    specs = [
        ("main", target_book_path(latest_run, "main", args.main_target_book)),
        ("concentrated", target_book_path(latest_run, "concentrated", args.concentrated_target_book)),
    ]
    all_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for portfolio, book_path in specs:
        book = load_target_book(book_path)
        rows = drop_rows_for_portfolio(book, audit, portfolio)
        all_rows.extend(rows)
        summary = summarize_drops(rows, portfolio)
        summary["target_book_source"] = str(book_path)
        summaries.append(summary)

    any_positive_candidate = any(item.get("pit_leader_hold_candidate_verdict") == "candidate_positive" for item in summaries)
    next_action = "design_target_book_hold_duration_ab" if any_positive_candidate else "discard_broad_hold_duration_rescue"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "research_only": True,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "broker_replay_executed": False,
        "entry_exit_audit_source": str(latest_run / "entry_exit_timing_audit" / "premature_sell_counterfactual.csv"),
        "next_action": next_action,
        "portfolios": summaries,
    }
    rows_frame = pd.DataFrame(all_rows)
    write_json(output_dir / "summary.json", payload)
    write_csv(output_dir / "drop_leak_rows.csv", rows_frame)
    (output_dir / "report.md").write_text(build_report(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Screen whipsaw events by sell-time PIT features.

This research-only screen joins same-ticker sell-then-rebuy whipsaw events to
the latest target-book row known at or before the sell signal date.  It reports
which generic, PIT-visible predicates concentrate whipsaw cost.  It does not
change target books or implement a policy hook.
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

from tools.run_whipsaw_cost_audit import (  # noqa: E402
    CASH_TICKERS,
    clean_ticker,
    read_csv,
    repo_path,
    safe_float,
    whipsaw_events,
    write_json,
    write_text,
)

DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/whipsaw_pit_feature_screen"
SCHEMA_VERSION = "whipsaw-pit-feature-screen-v1"
DEFAULT_OOS_START = "2024-06-03"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    d = read_csv(path)
    if d.empty or "rebalance_date" not in d.columns or "ticker" not in d.columns:
        return pd.DataFrame()
    d = d.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].map(clean_ticker)
    d = d[d["rebalance_date"].notna()]
    d = d[(d["ticker"] != "") & (~d["ticker"].isin(CASH_TICKERS))]
    return d.sort_values(["ticker", "rebalance_date"]).reset_index(drop=True)


def latest_target_row_lookup(book: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if book.empty:
        return {}
    return {ticker: group.sort_values("rebalance_date").reset_index(drop=True) for ticker, group in book.groupby("ticker")}


def row_at_or_before(groups: dict[str, pd.DataFrame], ticker: str, as_of: pd.Timestamp) -> dict[str, Any]:
    group = groups.get(clean_ticker(ticker))
    if group is None or group.empty or pd.isna(as_of):
        return {}
    eligible = group[group["rebalance_date"].le(as_of)]
    if eligible.empty:
        return {}
    return eligible.iloc[-1].to_dict()


def add_pit_features(events: pd.DataFrame, book: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    groups = latest_target_row_lookup(book)
    rows: list[dict[str, Any]] = []
    for event in events.to_dict("records"):
        sell_signal_date = pd.to_datetime(event.get("sell_signal_date") or event.get("sell_date"), errors="coerce")
        target_row = row_at_or_before(groups, clean_ticker(event.get("ticker")), pd.Timestamp(sell_signal_date).normalize())
        payload = dict(event)
        payload["pit_row_found"] = bool(target_row)
        payload["pit_rebalance_date"] = (
            pd.Timestamp(target_row.get("rebalance_date")).date().isoformat()
            if target_row and pd.notna(target_row.get("rebalance_date"))
            else ""
        )
        for source, dest in [
            ("weight", "pit_weight"),
            ("target_weight", "pit_target_weight"),
            ("holding_state", "pit_holding_state"),
            ("hold_replace_decision", "pit_hold_replace_decision"),
            ("leader_tier", "pit_leader_tier"),
            ("primary_lane", "pit_primary_lane"),
            ("rs_benchmark_1m", "pit_rs_benchmark_1m"),
            ("rs_benchmark_3m", "pit_rs_benchmark_3m"),
            ("rs_benchmark_6m", "pit_rs_benchmark_6m"),
            ("price_above_ma200", "pit_price_above_ma200"),
            ("price_above_ma50", "pit_price_above_ma50"),
            ("actual_results_score", "pit_actual_results_score"),
            ("eps_revision_score", "pit_eps_revision_score"),
            ("revision_score", "pit_revision_score"),
            ("event_reaction_score", "pit_event_reaction_score"),
            ("sector_leadership_score", "pit_sector_leadership_score"),
            ("smart_money_evidence_confidence", "pit_smart_money_evidence_confidence"),
            ("emerging_tenbagger_hard_reject_reason", "pit_hard_reject_reason"),
        ]:
            payload[dest] = target_row.get(source, "") if target_row else ""

        leader_tier = clean_text(payload.get("pit_leader_tier")).upper()
        holding_state = clean_text(payload.get("pit_holding_state")).upper()
        hard_reject = clean_text(payload.get("pit_hard_reject_reason"))
        rs3 = safe_float(payload.get("pit_rs_benchmark_3m"))
        rs6 = safe_float(payload.get("pit_rs_benchmark_6m"))
        ma200 = safe_float(payload.get("pit_price_above_ma200"))
        actual = safe_float(payload.get("pit_actual_results_score"))
        eps_rev = safe_float(payload.get("pit_eps_revision_score"))
        revision = safe_float(payload.get("pit_revision_score"))
        event_reaction = safe_float(payload.get("pit_event_reaction_score"))
        sector_leadership = safe_float(payload.get("pit_sector_leadership_score"))
        shares_after = safe_float(payload.get("sell_shares_after"))

        payload["full_exit"] = bool(shares_after <= 0.0)
        payload["pit_leader"] = bool(leader_tier in {"DUAL_LEADER", "SECTOR_LEADER"})
        payload["pit_healthy_hold"] = bool(holding_state == "HOLD")
        payload["pit_rs_intact"] = bool(rs3 > 0.0 and rs6 > 0.0)
        payload["pit_price_intact"] = bool(ma200 >= 0.5)
        payload["pit_actual_results_positive"] = bool(actual > 0.0)
        payload["pit_revision_positive"] = bool(max(eps_rev, revision, event_reaction) > 0.0)
        payload["pit_sector_leadership_positive"] = bool(sector_leadership > 0.0)
        payload["pit_no_hard_reject"] = bool(not hard_reject)
        payload["thesis_intact_actual_results"] = bool(
            payload["pit_leader"]
            and payload["pit_healthy_hold"]
            and payload["pit_rs_intact"]
            and payload["pit_price_intact"]
            and payload["pit_actual_results_positive"]
            and payload["pit_no_hard_reject"]
        )
        payload["thesis_intact_actual_or_revision"] = bool(
            payload["pit_leader"]
            and payload["pit_healthy_hold"]
            and payload["pit_rs_intact"]
            and payload["pit_price_intact"]
            and (payload["pit_actual_results_positive"] or payload["pit_revision_positive"])
            and payload["pit_no_hard_reject"]
        )
        payload["full_exit_thesis_intact_actual"] = bool(payload["full_exit"] and payload["thesis_intact_actual_results"])
        payload["partial_sell_thesis_intact_actual"] = bool((not payload["full_exit"]) and payload["thesis_intact_actual_results"])
        rows.append(payload)
    return pd.DataFrame(rows)


def summarize_group(frame: pd.DataFrame, label: str, mask: pd.Series, *, oos_start: pd.Timestamp) -> dict[str, Any]:
    part = frame[mask.fillna(False)].copy() if not frame.empty else pd.DataFrame()
    if part.empty:
        return {
            "predicate": label,
            "event_count": 0,
            "positive_whipsaw_rate": 0.0,
            "net_whipsaw_cost_usd": 0.0,
            "mean_price_return_while_out": None,
            "oos_event_count": 0,
            "oos_positive_whipsaw_rate": 0.0,
        }
    sell_dates = pd.to_datetime(part["sell_date"], errors="coerce")
    oos = part[sell_dates.ge(oos_start)]
    missed = pd.to_numeric(part.get("missed_reentry_cost_usd"), errors="coerce").fillna(0.0)
    avoided = pd.to_numeric(part.get("avoided_loss_usd"), errors="coerce").fillna(0.0)
    oos_missed = pd.to_numeric(oos.get("missed_reentry_cost_usd"), errors="coerce").fillna(0.0) if not oos.empty else pd.Series(dtype=float)
    oos_avoided = pd.to_numeric(oos.get("avoided_loss_usd"), errors="coerce").fillna(0.0) if not oos.empty else pd.Series(dtype=float)
    positive = part.get("whipsaw_positive", pd.Series(False, index=part.index)).astype(bool)
    oos_positive = oos.get("whipsaw_positive", pd.Series(False, index=oos.index)).astype(bool) if not oos.empty else pd.Series(dtype=bool)
    top = []
    if "ticker" in part.columns:
        grouped = part.groupby("ticker", as_index=False).agg(
            event_count=("ticker", "size"),
            missed_reentry_cost_usd=("missed_reentry_cost_usd", "sum"),
            avoided_loss_usd=("avoided_loss_usd", "sum"),
        )
        grouped["net_whipsaw_cost_usd"] = grouped["missed_reentry_cost_usd"] - grouped["avoided_loss_usd"]
        top = grouped.sort_values("net_whipsaw_cost_usd", ascending=False).head(10).to_dict("records")
    return {
        "predicate": label,
        "event_count": int(len(part)),
        "positive_whipsaw_count": int(positive.sum()),
        "positive_whipsaw_rate": float(positive.mean()) if len(part) else 0.0,
        "total_missed_reentry_cost_usd": float(missed.sum()),
        "total_avoided_loss_usd": float(avoided.sum()),
        "net_whipsaw_cost_usd": float(missed.sum() - avoided.sum()),
        "mean_price_return_while_out": float(pd.to_numeric(part.get("price_return_while_out"), errors="coerce").mean()),
        "median_price_return_while_out": float(pd.to_numeric(part.get("price_return_while_out"), errors="coerce").median()),
        "oos_event_count": int(len(oos)),
        "oos_positive_whipsaw_count": int(oos_positive.sum()) if len(oos) else 0,
        "oos_positive_whipsaw_rate": float(oos_positive.mean()) if len(oos) else 0.0,
        "oos_net_whipsaw_cost_usd": float(oos_missed.sum() - oos_avoided.sum()) if len(oos) else 0.0,
        "top_tickers": top,
    }


def screen_summary(enriched: pd.DataFrame, *, oos_start: pd.Timestamp) -> list[dict[str, Any]]:
    if enriched.empty:
        return []
    predicates: list[tuple[str, pd.Series]] = [
        ("all_events", pd.Series(True, index=enriched.index)),
        ("full_exit", enriched["full_exit"].astype(bool)),
        ("partial_sell", ~enriched["full_exit"].astype(bool)),
        ("pit_leader_rs_price_intact", enriched["pit_leader"].astype(bool) & enriched["pit_rs_intact"].astype(bool) & enriched["pit_price_intact"].astype(bool)),
        ("thesis_intact_actual_results", enriched["thesis_intact_actual_results"].astype(bool)),
        ("thesis_intact_actual_or_revision", enriched["thesis_intact_actual_or_revision"].astype(bool)),
        ("full_exit_thesis_intact_actual", enriched["full_exit_thesis_intact_actual"].astype(bool)),
        ("partial_sell_thesis_intact_actual", enriched["partial_sell_thesis_intact_actual"].astype(bool)),
        ("actual_results_positive", enriched["pit_actual_results_positive"].astype(bool)),
        ("revision_positive", enriched["pit_revision_positive"].astype(bool)),
        ("sector_leadership_positive", enriched["pit_sector_leadership_positive"].astype(bool)),
    ]
    return [summarize_group(enriched, label, mask, oos_start=oos_start) for label, mask in predicates]


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Whipsaw PIT Feature Screen",
        "",
        "Research-only screen of sell-time PIT predicates for same-ticker sell->rebuy whipsaw events.",
        "",
        f"- portfolio: `{payload.get('portfolio')}`",
        f"- event_count: `{payload.get('event_count')}`",
        f"- oos_start: `{payload.get('oos_start')}`",
        f"- verdict: `{payload.get('verdict')}`",
        f"- next_action: `{payload.get('next_action')}`",
        "",
        "## Predicate Summary",
        "",
        "| predicate | events | positive rate | net cost | OOS events | OOS net cost |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in payload.get("predicate_summary", []):
        lines.append(
            f"| `{row.get('predicate')}` | {row.get('event_count', 0)} | "
            f"{row.get('positive_whipsaw_rate', 0.0):.1%} | "
            f"${row.get('net_whipsaw_cost_usd', 0.0):,.0f} | "
            f"{row.get('oos_event_count', 0)} | "
            f"${row.get('oos_net_whipsaw_cost_usd', 0.0):,.0f} |"
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This is not a policy hook.",
            "- Whipsaw outcomes are audit labels only.",
            "- Any next hook must be default-OFF and broker-ledger A/B tested.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    portfolio = str(args.portfolio).lower().strip()
    trades_path = repo_path(args.trades) if args.trades else latest_run / "broker_replay" / portfolio / "trades.csv"
    target_path = target_book_path(latest_run, portfolio, args.target_book or None)
    trades = read_csv(trades_path)
    book = load_target_book(target_path)
    events = whipsaw_events(trades, max_rebuy_days=int(args.max_rebuy_days))
    enriched = add_pit_features(events, book)
    oos_start = pd.Timestamp(args.oos_start).normalize()
    predicates = screen_summary(enriched, oos_start=oos_start)
    primary = next((row for row in predicates if row.get("predicate") == "thesis_intact_actual_results"), {})
    primary_events = int(primary.get("event_count", 0) or 0)
    primary_oos = int(primary.get("oos_event_count", 0) or 0)
    primary_net = safe_float(primary.get("net_whipsaw_cost_usd"))
    primary_oos_net = safe_float(primary.get("oos_net_whipsaw_cost_usd"))
    screen_pass = bool(primary_events >= int(args.min_events) and primary_oos >= int(args.min_oos_events) and primary_net > 0 and primary_oos_net >= 0)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "portfolio": portfolio,
        "research_only": True,
        "production_activation_allowed": False,
        "inputs": {
            "trades": str(trades_path),
            "target_book": str(target_path),
        },
        "max_rebuy_days": int(args.max_rebuy_days),
        "oos_start": args.oos_start,
        "event_count": int(len(enriched)),
        "pit_joined_event_count": int(enriched.get("pit_row_found", pd.Series(dtype=bool)).astype(bool).sum()) if not enriched.empty else 0,
        "predicate_summary": predicates,
        "primary_predicate": "thesis_intact_actual_results",
        "screen_pass": bool(screen_pass),
        "verdict": "screen_pass_design_default_off_whipsaw_hook" if screen_pass else "screen_reject_or_inconclusive",
        "next_action": "design_default_off_whipsaw_guard_candidate" if screen_pass else "report_only",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(output_dir / "whipsaw_pit_events.csv", index=False)
    pd.DataFrame(predicates).to_csv(output_dir / "predicate_summary.csv", index=False)
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--trades", default="")
    parser.add_argument("--target-book", default="")
    parser.add_argument("--portfolio", choices=["main", "concentrated"], default="concentrated")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-rebuy-days", type=int, default=252)
    parser.add_argument("--oos-start", default=DEFAULT_OOS_START)
    parser.add_argument("--min-events", type=int, default=10)
    parser.add_argument("--min-oos-events", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()

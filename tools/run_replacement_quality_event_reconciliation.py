#!/usr/bin/env python3
"""Reconcile fixed-book replacement-quality swaps against policy-path hook events.

This is a research-only gate. It does not run a broker replay, mutate target
books, or approve production activation. The goal is to prove that a
default-OFF replacement-quality hook is firing on the same event set as the
fixed-book counterfactual before any broker A/B or fullrun discussion.
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


DEFAULT_REJECTION_REASONS = {
    "hold_replace_threshold_not_met",
    "leadership_persistence_hold_threshold_not_met",
    "concentrated_emerging_or_top7_seat_cap",
}


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def norm_text(value: Any) -> str:
    raw = "" if value is None else str(value)
    if raw.lower() in {"nan", "none", "nat"}:
        return ""
    return raw.strip()


def norm_ticker(value: Any) -> str:
    return norm_text(value).upper()


def norm_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return pd.Timestamp(parsed).date().isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def bool_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y", "t"})


def event_key(date: Any, added: Any, removed: Any) -> str:
    return f"{norm_date(date)}|{norm_ticker(added)}|{norm_ticker(removed)}"


def candidate_key(date: Any, added: Any) -> str:
    return f"{norm_date(date)}|{norm_ticker(added)}"


def available_from_columns(frame: pd.DataFrame) -> list[str]:
    return [col for col in frame.columns if "available_from" in str(col).lower()]


def future_available_from_count(frame: pd.DataFrame) -> int:
    if frame.empty or "rebalance_date" not in frame.columns:
        return 0
    dates = pd.to_datetime(frame["rebalance_date"], errors="coerce")
    count = 0
    for col in available_from_columns(frame):
        available = pd.to_datetime(frame[col], errors="coerce")
        count += int(((available.notna()) & (dates.notna()) & (available > dates)).sum())
    return count


def load_fixed_events(path: Path) -> pd.DataFrame:
    frame = read_csv(path)
    if frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out["rebalance_date"] = out.get("rebalance_date", "").map(norm_date)
    out["added_ticker"] = out.get("added_ticker", "").map(norm_ticker)
    out["removed_ticker"] = out.get("removed_ticker", "").map(norm_ticker)
    out["event_key"] = [
        event_key(row.rebalance_date, row.added_ticker, row.removed_ticker)
        for row in out[["rebalance_date", "added_ticker", "removed_ticker"]].itertuples(index=False)
    ]
    out["candidate_key"] = [candidate_key(row.rebalance_date, row.added_ticker) for row in out.itertuples(index=False)]
    out["event_source"] = "fixed_book_counterfactual"
    out["rejection_class"] = "cap_or_replacement_missed_leader"
    out["forward_return_is_audit_label_only"] = (
        out.get("forward_return_is_audit_label_only", pd.Series(True, index=out.index)).astype(str).str.lower().ne("false")
    )
    out["forward_labels_used_for_ranking"] = bool_series(
        out.get("forward_labels_used_for_ranking", pd.Series(False, index=out.index))
    )
    return out


def load_policy_events(path: Path, reasons: set[str]) -> pd.DataFrame:
    frame = read_csv(path)
    if frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out["rebalance_date"] = out.get("rebalance_date", "").map(norm_date)
    out["added_ticker"] = out.get("ticker", "").map(norm_ticker)
    out["removed_ticker"] = out.get("replacement_test_weakest_ticker", "").map(norm_ticker)
    out["rejection_reason"] = out.get("rejection_reason", "").map(norm_text)
    if "portfolio_kind" in out.columns:
        out = out[out["portfolio_kind"].astype(str).str.lower().eq("concentrated")].copy()
    out = out[out["rejection_reason"].isin(reasons)].copy()
    out["event_key"] = [
        event_key(row.rebalance_date, row.added_ticker, row.removed_ticker)
        for row in out[["rebalance_date", "added_ticker", "removed_ticker"]].itertuples(index=False)
    ]
    out["candidate_key"] = [candidate_key(row.rebalance_date, row.added_ticker) for row in out.itertuples(index=False)]
    out["event_source"] = "policy_path_month_rejections"
    return out


def load_hook_swaps(path: Path) -> pd.DataFrame:
    frame = read_csv(path)
    if frame.empty or "concentrated_replacement_quality_applied" not in frame.columns:
        return pd.DataFrame()
    applied = bool_series(frame["concentrated_replacement_quality_applied"])
    out = frame[applied].copy()
    out["rebalance_date"] = out.get("rebalance_date", "").map(norm_date)
    out["added_ticker"] = out.get("concentrated_replacement_quality_added_ticker", out.get("ticker", "")).map(norm_ticker)
    out["removed_ticker"] = out.get("concentrated_replacement_quality_removed_ticker", "").map(norm_ticker)
    out["rejection_reason"] = out.get("concentrated_replacement_quality_source_rejection_reason", "").map(norm_text)
    out["leader_rank_ex_ante"] = out.get("concentrated_replacement_quality_leader_rank_ex_ante", out.get("leader_rank_ex_ante", ""))
    out["revenue_growth"] = out.get("concentrated_replacement_quality_revenue_growth", out.get("revenue_growth", ""))
    out["rs_spy_3m"] = out.get("concentrated_replacement_quality_rs_spy_3m", out.get("rs_spy_3m", ""))
    out["event_key"] = [
        event_key(row.rebalance_date, row.added_ticker, row.removed_ticker)
        for row in out[["rebalance_date", "added_ticker", "removed_ticker"]].itertuples(index=False)
    ]
    out["candidate_key"] = [candidate_key(row.rebalance_date, row.added_ticker) for row in out.itertuples(index=False)]
    out["event_source"] = "policy_path_hook_swaps"
    return out


def unique_by_key(frame: pd.DataFrame, key: str) -> pd.DataFrame:
    if frame.empty or key not in frame.columns:
        return pd.DataFrame()
    return frame.drop_duplicates(subset=[key]).copy()


def reconcile(fixed: pd.DataFrame, policy: pd.DataFrame, hook: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    fixed_keys = set(fixed.get("event_key", pd.Series(dtype=str)).astype(str))
    hook_keys = set(hook.get("event_key", pd.Series(dtype=str)).astype(str))
    policy_keys = set(policy.get("event_key", pd.Series(dtype=str)).astype(str))
    fixed_candidate_keys = set(fixed.get("candidate_key", pd.Series(dtype=str)).astype(str))
    policy_candidate_keys = set(policy.get("candidate_key", pd.Series(dtype=str)).astype(str))

    fixed_lookup = unique_by_key(fixed, "event_key").set_index("event_key", drop=False) if not fixed.empty else pd.DataFrame()
    hook_lookup = unique_by_key(hook, "event_key").set_index("event_key", drop=False) if not hook.empty else pd.DataFrame()
    policy_lookup = unique_by_key(policy, "event_key").set_index("event_key", drop=False) if not policy.empty else pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for key in sorted(fixed_keys | hook_keys | policy_keys):
        fixed_row = fixed_lookup.loc[key].to_dict() if not fixed_lookup.empty and key in fixed_lookup.index else {}
        hook_row = hook_lookup.loc[key].to_dict() if not hook_lookup.empty and key in hook_lookup.index else {}
        policy_row = policy_lookup.loc[key].to_dict() if not policy_lookup.empty and key in policy_lookup.index else {}
        source = hook_row or fixed_row or policy_row
        ckey = norm_text(source.get("candidate_key"))
        in_fixed = key in fixed_keys
        in_hook = key in hook_keys
        in_policy = key in policy_keys
        if in_hook and in_fixed:
            status = "exact_match"
        elif in_hook and ckey in fixed_candidate_keys:
            status = "same_ticker_same_month_different_source"
        elif in_hook:
            status = "policy_only"
        elif in_fixed:
            status = "fixed_book_only"
        else:
            status = "policy_event_no_hook_or_fixed"
        rows.append(
            {
                "event_key": key,
                "candidate_key": ckey,
                "rebalance_date": source.get("rebalance_date", ""),
                "added_ticker": source.get("added_ticker", ""),
                "removed_ticker": source.get("removed_ticker", ""),
                "event_match_status": status,
                "in_fixed_book": in_fixed,
                "in_hook": in_hook,
                "in_policy_rejections": in_policy,
                "policy_same_candidate_month": ckey in policy_candidate_keys,
                "leader_rank_ex_ante": source.get("leader_rank_ex_ante", ""),
                "revenue_growth": source.get("revenue_growth", ""),
                "rs_spy_3m": source.get("rs_spy_3m", ""),
                "rejection_reason_fixed": fixed_row.get("rejection_reason", fixed_row.get("rejection_class", "")),
                "rejection_reason_policy": policy_row.get("rejection_reason", ""),
                "rejection_reason_hook": hook_row.get("rejection_reason", ""),
                "replacement_weight": source.get("replacement_weight", source.get("concentrated_replacement_quality_replacement_weight", "")),
            }
        )
    diff = pd.DataFrame(rows)
    hook_only = int((diff["event_match_status"] == "policy_only").sum()) if not diff.empty else 0
    exact = int((diff["event_match_status"] == "exact_match").sum()) if not diff.empty else 0
    same_month = int((diff["event_match_status"] == "same_ticker_same_month_different_source").sum()) if not diff.empty else 0
    fixed_only = int((diff["event_match_status"] == "fixed_book_only").sum()) if not diff.empty else 0
    fixed_count = int(len(fixed))
    hook_count = int(len(hook))
    count_delta_pct = float(abs(hook_count - fixed_count) / fixed_count) if fixed_count else (0.0 if hook_count == 0 else 1.0)
    stats = {
        "fixed_event_count": fixed_count,
        "hook_event_count": hook_count,
        "policy_event_count": int(len(policy)),
        "exact_match_count": exact,
        "same_ticker_same_month_different_source_count": same_month,
        "policy_only_hook_count": hook_only,
        "fixed_book_only_count": fixed_only,
        "hook_is_subset_of_fixed": bool(hook_only == 0 and same_month == 0),
        "hook_count_delta_pct_abs": count_delta_pct,
    }
    return diff, stats


def pit_audit(fixed: pd.DataFrame, hook: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[pd.DataFrame] = []
    if not fixed.empty:
        f = fixed.copy()
        f["pit_audit_source"] = "fixed"
        rows.append(f)
    if not hook.empty:
        h = hook.copy()
        h["pit_audit_source"] = "hook"
        rows.append(h)
    combined = pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame()
    future_count = future_available_from_count(combined)
    forward_used = 0
    if "forward_labels_used_for_ranking" in combined.columns:
        forward_used = int(bool_series(combined["forward_labels_used_for_ranking"]).sum())
    forward_cols = [col for col in combined.columns if str(col).lower().startswith("forward_")]
    combined["no_forward_return_used"] = forward_used == 0
    combined["no_future_label_used"] = forward_used == 0
    summary = {
        "row_count": int(len(combined)),
        "available_from_columns": available_from_columns(combined),
        "future_available_from_count": future_count,
        "forward_label_columns_present": forward_cols,
        "forward_labels_used_for_ranking_count": forward_used,
        "pit_blockers": [
            *("future_available_from" for _ in range(1) if future_count > 0),
            *("forward_labels_used_for_ranking" for _ in range(1) if forward_used > 0),
        ],
        "pit_warnings": ["no_available_from_columns_observed"] if not available_from_columns(combined) else [],
    }
    return combined, summary


def render_report(payload: dict[str, Any]) -> str:
    stats = payload["event_reconciliation"]
    pit = payload["pit_audit"]
    lines = [
        "# Replacement-Quality Event Reconciliation",
        "",
        f"- status: `{payload['status']}`",
        f"- verdict: `{payload['verdict']}`",
        f"- fixed swaps: `{payload['fixed_swaps']}`",
        f"- policy rejections: `{payload['policy_rejections']}`",
        f"- hook target book: `{payload['hook_target_book']}`",
        "",
        "## Event Counts",
        "",
        f"- fixed events: `{stats['fixed_event_count']}`",
        f"- hook events: `{stats['hook_event_count']}`",
        f"- policy events: `{stats['policy_event_count']}`",
        f"- exact matches: `{stats['exact_match_count']}`",
        f"- same ticker/month different source: `{stats['same_ticker_same_month_different_source_count']}`",
        f"- policy-only hook events: `{stats['policy_only_hook_count']}`",
        f"- fixed-book-only events: `{stats['fixed_book_only_count']}`",
        f"- hook subset of fixed: `{stats['hook_is_subset_of_fixed']}`",
        f"- hook count delta abs: `{stats['hook_count_delta_pct_abs']:.2%}`",
        "",
        "## PIT Audit",
        "",
        f"- future available_from count: `{pit['future_available_from_count']}`",
        f"- forward labels used for ranking count: `{pit['forward_labels_used_for_ranking_count']}`",
        f"- available_from columns: `{pit['available_from_columns']}`",
        f"- warnings: `{pit['pit_warnings']}`",
        "",
        "## Blockers",
        "",
    ]
    blockers = payload.get("blockers") or []
    if blockers:
        lines.extend([f"- `{item}`" for item in blockers])
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rejection_reasons = {item.strip() for item in str(args.rejection_reasons or "").split(",") if item.strip()}
    if not rejection_reasons:
        rejection_reasons = set(DEFAULT_REJECTION_REASONS)

    fixed_path = repo_path(args.fixed_swaps)
    policy_path = repo_path(args.policy_rejections)
    hook_path = repo_path(args.hook_target_book)
    fixed = load_fixed_events(fixed_path)
    policy = load_policy_events(policy_path, rejection_reasons)
    hook = load_hook_swaps(hook_path)
    diff, stats = reconcile(fixed, policy, hook)
    pit_rows, pit_summary = pit_audit(fixed, hook)

    fixed.to_csv(output_dir / "fixed_book_events.csv", index=False)
    policy.to_csv(output_dir / "policy_path_events.csv", index=False)
    hook.to_csv(output_dir / "hook_swaps.csv", index=False)
    diff.to_csv(output_dir / "event_diff.csv", index=False)
    pit_rows.to_csv(output_dir / "applied_rows.csv", index=False)

    count_within_tolerance = bool(stats["hook_count_delta_pct_abs"] <= float(args.swap_count_tolerance_pct))
    hook_dates = hook.groupby("rebalance_date").size() if not hook.empty else pd.Series(dtype=int)
    max_swaps_violation = bool((hook_dates > int(args.max_swaps_per_date)).any()) if not hook_dates.empty else False
    blockers: list[str] = []
    if not stats["hook_is_subset_of_fixed"]:
        blockers.append("hook_swaps_not_subset_of_fixed_book_counterfactual")
    if not count_within_tolerance:
        blockers.append("hook_swap_count_outside_tolerance")
    if stats["hook_event_count"] <= 0:
        blockers.append("hook_no_applied_swaps")
    if max_swaps_violation:
        blockers.append("hook_max_swaps_per_date_violation")
    blockers.extend(pit_summary["pit_blockers"])
    status = "blocked" if blockers else "ready_for_event_matched_broker_ab"
    verdict = (
        "Do not run fullrun. Reconcile or narrow the hook event source first."
        if blockers
        else "Hook event source matches fixed-book swaps closely enough for event-matched broker A/B."
    )
    payload = {
        "schema_version": "replacement-quality-event-reconciliation-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "verdict": verdict,
        "fixed_swaps": str(fixed_path),
        "policy_rejections": str(policy_path),
        "hook_target_book": str(hook_path),
        "output_dir": str(output_dir),
        "event_reconciliation": {
            **stats,
            "swap_count_tolerance_pct": float(args.swap_count_tolerance_pct),
            "hook_count_within_tolerance": count_within_tolerance,
            "max_swaps_per_date": int(args.max_swaps_per_date),
            "hook_max_swaps_per_date_violation": max_swaps_violation,
            "rejection_reasons": sorted(rejection_reasons),
        },
        "pit_audit": pit_summary,
        "blockers": blockers,
        "production_activation_allowed": False,
        "fullrun_allowed": False,
        "live_trading_enabled": False,
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixed-swaps", required=True)
    parser.add_argument("--policy-rejections", required=True)
    parser.add_argument("--hook-target-book", required=True)
    parser.add_argument("--output-dir", default="outputs/concentrated_replacement_quality_event_reconciliation")
    parser.add_argument("--swap-count-tolerance-pct", type=float, default=0.10)
    parser.add_argument("--max-swaps-per-date", type=int, default=1)
    parser.add_argument("--rejection-reasons", default=",".join(sorted(DEFAULT_REJECTION_REASONS)))
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

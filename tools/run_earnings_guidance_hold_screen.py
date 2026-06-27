"""PIT earnings/guidance hold screen for Concentrated CAGR repair.

This diagnostic searches target-book drop rows for a narrow, PIT-observable
predicate that may justify a later default-OFF hold-extension hook. It does not
mutate policy, rank live candidates, or run broker replay.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_VERSION = "earnings-guidance-hold-screen-v1"
DEFAULT_OUTPUT_DIR = "outputs/earnings_guidance_hold_screen"
IS_END_EXCLUSIVE = pd.Timestamp("2024-06-03")
OOS_START = pd.Timestamp("2024-06-03")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


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


def target_book_path(latest_run: Path, portfolio: str, explicit: str | None = None) -> Path:
    if explicit:
        return repo_path(explicit)
    candidates = [
        latest_run / "alphaops_vnext" / f"official_{portfolio}_target_book.csv",
        latest_run / "reports" / f"operating_{portfolio}_target_book.csv",
        latest_run / "market_leader_challenger" / f"{portfolio}_target_book.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def hold_screen_rows(latest_run: Path, explicit: str | None = None) -> Path:
    if explicit:
        return repo_path(explicit)
    candidates = [
        latest_run.parent / "hold_duration_leak_screen" / "drop_leak_rows.csv",
        latest_run / "hold_duration_leak_screen" / "drop_leak_rows.csv",
        REPO_ROOT / "outputs" / "hold_duration_leak_screen" / "drop_leak_rows.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([0.0] * len(frame), index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def load_joined(latest_run: Path, *, portfolio: str, target_book: Path, drop_rows: Path) -> pd.DataFrame:
    if not target_book.exists():
        raise FileNotFoundError(f"target book not found: {target_book}")
    if not drop_rows.exists():
        raise FileNotFoundError(f"hold-duration drop rows not found: {drop_rows}")
    drops = pd.read_csv(drop_rows, low_memory=False)
    book = pd.read_csv(target_book, low_memory=False)
    if drops.empty or book.empty:
        return pd.DataFrame()
    drops = drops.copy()
    book = book.copy()
    drops["portfolio"] = drops.get("portfolio", "").astype(str).str.lower().str.strip()
    drops = drops[drops["portfolio"].eq(portfolio.lower())]
    drops["prior_rebalance_date"] = pd.to_datetime(drops["prior_rebalance_date"], errors="coerce").dt.normalize()
    book["rebalance_date"] = pd.to_datetime(book["rebalance_date"], errors="coerce").dt.normalize()
    drops["ticker"] = drops["ticker"].map(clean_ticker)
    book["ticker"] = book["ticker"].map(clean_ticker)

    columns = [
        "rebalance_date",
        "ticker",
        "eps_revision_score",
        "revision_score",
        "eps_revision_proxy",
        "actual_results_score",
        "event_reaction_score",
        "profitability_inflection_score",
        "profit_turn_positive_4q",
        "any_profit_sign_flip_pos",
        "sales_growth_yoy",
        "eps_growth_yoy",
        "revenue_growth_final",
        "rev_growth_accel_4q",
        "selection_confirmation_score",
        "alphaops_vnext_score",
        "leader_tier",
        "holding_state",
        "primary_lane",
        "regime_state",
        "sector",
        "industry_group",
        "latest_available_from",
    ]
    columns = [column for column in columns if column in book.columns]
    right = book[columns].rename(columns={"rebalance_date": "prior_rebalance_date"})
    joined = drops.merge(right, on=["prior_rebalance_date", "ticker"], how="left", suffixes=("", "_book"))
    joined["audit_matched_bool"] = joined.get("audit_matched", False).astype(str).str.lower().isin({"true", "1", "yes"})
    joined["pit_leader_hold_candidate_bool"] = joined.get("pit_leader_hold_candidate", False).astype(str).str.lower().isin({"true", "1", "yes"})
    joined["positive_excess_126d_bool"] = joined.get("positive_excess_126d", False).astype(str).str.lower().isin({"true", "1", "yes"})
    joined["premature_sell_excess_126d_num"] = pd.to_numeric(joined.get("premature_sell_excess_126d"), errors="coerce")
    joined["actual_results_positive"] = numeric(joined, "actual_results_score").gt(0.0)
    joined["event_reaction_positive"] = numeric(joined, "event_reaction_score").gt(0.0)
    joined["eps_revision_positive"] = (
        numeric(joined, "eps_revision_score").gt(0.0)
        | numeric(joined, "revision_score").gt(0.0)
        | numeric(joined, "eps_revision_proxy").gt(0.0)
    )
    joined["profit_turn_positive"] = (
        numeric(joined, "profit_turn_positive_4q").gt(0.0)
        | numeric(joined, "any_profit_sign_flip_pos").gt(0.0)
        | numeric(joined, "profitability_inflection_score").gt(0.0)
    )
    joined["growth_positive"] = (
        numeric(joined, "sales_growth_yoy").gt(0.0)
        | numeric(joined, "eps_growth_yoy").gt(0.0)
        | numeric(joined, "revenue_growth_final").gt(0.0)
        | numeric(joined, "rev_growth_accel_4q").gt(0.0)
    )
    joined["pit_confirmation_count"] = joined[
        ["actual_results_positive", "event_reaction_positive", "eps_revision_positive", "profit_turn_positive", "growth_positive"]
    ].sum(axis=1)
    return joined


def predicate_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "actual_results_positive_pit_hold": frame["pit_leader_hold_candidate_bool"] & frame["actual_results_positive"],
        "actual_and_event_positive_pit_hold": (
            frame["pit_leader_hold_candidate_bool"] & frame["actual_results_positive"] & frame["event_reaction_positive"]
        ),
        "two_plus_confirmations_pit_hold": frame["pit_leader_hold_candidate_bool"] & frame["pit_confirmation_count"].ge(2),
        "eps_revision_positive_pit_hold": frame["pit_leader_hold_candidate_bool"] & frame["eps_revision_positive"],
    }


def summarize_subset(frame: pd.DataFrame, mask: pd.Series, label: str, split: str) -> dict[str, Any]:
    subset = frame[mask & frame["audit_matched_bool"]].copy()
    excess = pd.to_numeric(subset.get("premature_sell_excess_126d_num"), errors="coerce").dropna()
    return {
        "label": label,
        "split": split,
        "rows": int(len(subset)),
        "positive_rows": int((excess > 0.0).sum()),
        "positive_rate": float((excess > 0.0).mean()) if len(excess) else None,
        "mean_excess_126d": float(excess.mean()) if len(excess) else None,
        "median_excess_126d": float(excess.median()) if len(excess) else None,
        "min_excess_126d": float(excess.min()) if len(excess) else None,
        "max_excess_126d": float(excess.max()) if len(excess) else None,
    }


def evaluate_candidate(rows_by_split: dict[str, dict[str, Any]]) -> dict[str, Any]:
    full = rows_by_split.get("full", {})
    is_row = rows_by_split.get("is", {})
    oos = rows_by_split.get("oos", {})
    gates = {
        "full_rows_ge_30": int(full.get("rows", 0)) >= 30,
        "is_rows_ge_30": int(is_row.get("rows", 0)) >= 30,
        "oos_rows_ge_8": int(oos.get("rows", 0)) >= 8,
        "full_mean_positive": safe_float(full.get("mean_excess_126d"), -1.0) > 0.0,
        "is_mean_positive": safe_float(is_row.get("mean_excess_126d"), -1.0) > 0.0,
        "oos_mean_positive": safe_float(oos.get("mean_excess_126d"), -1.0) > 0.0,
        "oos_positive_rate_ge_50": safe_float(oos.get("positive_rate"), 0.0) >= 0.50,
    }
    return {
        "gates": gates,
        "screen_pass": all(gates.values()),
        "next_action": "design_default_off_hook_candidate" if all(gates.values()) else "do_not_design_hook",
    }


def build_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Earnings / Guidance Hold Screen",
        "",
        f"- schema_version: `{payload['schema_version']}`",
        f"- generated_at: `{payload['generated_at_utc']}`",
        f"- target: Concentrated CAGR >= 50%, MDD >= -25%",
        f"- primary_candidate: `{payload['primary_candidate']['label']}`",
        f"- screen_pass: `{payload['primary_candidate']['evaluation']['screen_pass']}`",
        f"- next_action: `{payload['primary_candidate']['evaluation']['next_action']}`",
        "",
        "## Predicate summaries",
        "",
        "| predicate | split | rows | positive rate | mean 126d excess | median |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in payload.get("predicate_summaries", []):
        rate = row.get("positive_rate")
        mean = row.get("mean_excess_126d")
        median = row.get("median_excess_126d")
        lines.append(
            f"| {row.get('label')} | {row.get('split')} | {row.get('rows')} | "
            f"{'' if rate is None else f'{rate:.2%}'} | "
            f"{'' if mean is None else f'{mean:.2%}'} | "
            f"{'' if median is None else f'{median:.2%}'} |"
        )
    lines.extend(
        [
            "",
            "## Governance",
            "",
            "- Forward 126d returns are audit labels only.",
            "- This screen does not mutate ranking, target books, broker replay, or live trading.",
            "- A pass only permits a later default-OFF hook design and cheap target-book/broker A/B.",
            "- It is not production evidence while `pit_universe_label_clean=false`.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    portfolio = str(args.portfolio).lower().strip()
    target_path = target_book_path(latest_run, portfolio, args.target_book)
    drop_path = hold_screen_rows(latest_run, args.drop_rows)
    joined = load_joined(latest_run, portfolio=portfolio, target_book=target_path, drop_rows=drop_path)

    masks = predicate_masks(joined) if not joined.empty else {}
    split_masks = {
        "full": pd.Series([True] * len(joined), index=joined.index),
        "is": joined["prior_rebalance_date"].lt(IS_END_EXCLUSIVE) if not joined.empty else pd.Series(dtype=bool),
        "oos": joined["prior_rebalance_date"].ge(OOS_START) if not joined.empty else pd.Series(dtype=bool),
    }
    summaries: list[dict[str, Any]] = []
    by_label: dict[str, dict[str, dict[str, Any]]] = {}
    for label, mask in masks.items():
        by_label[label] = {}
        for split, split_mask in split_masks.items():
            summary = summarize_subset(joined, mask & split_mask, label, split)
            summaries.append(summary)
            by_label[label][split] = summary

    primary_label = "actual_results_positive_pit_hold"
    primary = {
        "label": primary_label,
        "summaries": by_label.get(primary_label, {}),
        "evaluation": evaluate_candidate(by_label.get(primary_label, {})),
    }
    if not joined.empty:
        out_rows = joined[
            masks.get(primary_label, pd.Series([False] * len(joined), index=joined.index))
            & joined["audit_matched_bool"]
        ].copy()
    else:
        out_rows = pd.DataFrame()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not out_rows.empty:
        out_rows.sort_values("premature_sell_excess_126d_num", ascending=False).to_csv(
            output_dir / "primary_candidate_rows.csv", index=False
        )
    else:
        pd.DataFrame().to_csv(output_dir / "primary_candidate_rows.csv", index=False)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "portfolio": portfolio,
        "target": {"cagr": 0.50, "max_dd": -0.25},
        "latest_run": str(latest_run),
        "target_book": str(target_path),
        "drop_rows": str(drop_path),
        "joined_rows": int(len(joined)),
        "is_oos_split": {
            "is_end_exclusive": IS_END_EXCLUSIVE.date().isoformat(),
            "oos_start": OOS_START.date().isoformat(),
        },
        "predicate_summaries": summaries,
        "primary_candidate": primary,
        "research_only": True,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(build_report(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--portfolio", default="concentrated")
    parser.add_argument("--target-book", default="")
    parser.add_argument("--drop-rows", default="")
    args = parser.parse_args()
    payload = run(args)
    print(
        json.dumps(
            {
                "status": "completed",
                "screen_pass": payload["primary_candidate"]["evaluation"]["screen_pass"],
                "next_action": payload["primary_candidate"]["evaluation"]["next_action"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

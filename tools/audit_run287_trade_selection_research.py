#!/usr/bin/env python3
"""Fail-closed audit for Run287 trade-learning selection hypotheses.

This research-only sidecar closes two tempting but potentially overfit paths:

* issuer re-entry memory derived from completed historical trades; and
* conditional retention after a target-book drop when the old selector still
  reports a strong right-tail signal.

The first path is diagnostic because historical trades have unequal holding
periods.  The second path uses fixed 63/126-session SPY-excess labels produced
by ``run_right_tail_drop_counterfactual_audit.py`` and is evaluated on frozen,
overlapping full/OOS2/OOS windows.  No target book, weight, cash balance, score,
rank, or order is changed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = "run287-trade-selection-research-audit-v1"
WINDOWS = {
    "full": pd.Timestamp("1900-01-01"),
    "oos2": pd.Timestamp("2023-01-01"),
    "oos": pd.Timestamp("2024-07-01"),
}
PRIMARY_HORIZON = 63
HORIZONS = (63, 126)
MIN_EVENTS_PER_STATE = 50
MIN_DECISION_WEEK_BLOCKS = 12
BOOTSTRAP_SAMPLES = 2_000
BOOTSTRAP_ALPHA = 0.05


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def bool_series(values: pd.Series) -> pd.Series:
    return values.astype(str).str.strip().str.lower().isin({"1", "true", "yes"})


def finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def prior_trade_memory_rows(trades: pd.DataFrame) -> pd.DataFrame:
    required = {"ticker", "entry_date", "exit_date", "entry_answer", "alpha_vs_benchmark"}
    if trades.empty or not required.issubset(trades.columns):
        return pd.DataFrame()
    out = trades.copy()
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out["entry_date"] = pd.to_datetime(out["entry_date"], errors="coerce")
    out["exit_date"] = pd.to_datetime(out["exit_date"], errors="coerce")
    out["alpha_vs_benchmark"] = pd.to_numeric(out["alpha_vs_benchmark"], errors="coerce")
    out = out.dropna(subset=["ticker", "entry_date"]).sort_values(
        ["ticker", "entry_date", "exit_date"], na_position="last"
    )
    states: list[str] = []
    for _, row in out.iterrows():
        prior = out[
            out["ticker"].eq(row["ticker"])
            & out["exit_date"].notna()
            & out["exit_date"].lt(row["entry_date"])
        ]
        if prior.empty:
            state = "no_prior"
        else:
            answer = str(prior.sort_values("exit_date").iloc[-1]["entry_answer"])
            if answer == "GOOD_ENTRY_POSITIVE_ALPHA":
                state = "positive"
            elif answer == "WRONG_ENTRY_LOSS_AND_LAG":
                state = "negative"
            else:
                state = "neutral"
        states.append(state)
    out["prior_ticker_memory"] = states
    return out.reset_index(drop=True)


def memory_summary(rows: pd.DataFrame) -> pd.DataFrame:
    result: list[dict[str, Any]] = []
    if rows.empty:
        return pd.DataFrame()
    for window, start in WINDOWS.items():
        subset = rows[rows["entry_date"].ge(start)].copy()
        positive = subset[subset["prior_ticker_memory"].eq("positive")]["alpha_vs_benchmark"].dropna()
        negative = subset[subset["prior_ticker_memory"].eq("negative")]["alpha_vs_benchmark"].dropna()
        pos_mean = float(positive.mean()) if not positive.empty else math.nan
        neg_mean = float(negative.mean()) if not negative.empty else math.nan
        result.append(
            {
                "window": window,
                "positive_count": int(len(positive)),
                "negative_count": int(len(negative)),
                "positive_mean_alpha": pos_mean,
                "negative_mean_alpha": neg_mean,
                "positive_minus_negative_mean_alpha": pos_mean - neg_mean,
                "label_caveat": "variable_realized_holding_period_diagnostic_only",
                "eligible_for_portfolio_ab": False,
            }
        )
    return pd.DataFrame(result)


def high_signal_mask(frame: pd.DataFrame) -> pd.Series:
    skill = bool_series(frame.get("drop_skill_evidence_flag", pd.Series(False, index=frame.index)))
    rank = pd.to_numeric(frame.get("candidate_rank_percentile"), errors="coerce").fillna(0.0)
    stack = pd.to_numeric(frame.get("drop_signal_stack_count"), errors="coerce").fillna(0.0)
    return skill & rank.ge(0.80) & stack.ge(7.0)


def stable_seed(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (2**32)


def cluster_bootstrap_lower(
    frame: pd.DataFrame,
    value_column: str,
    state_column: str,
    block_column: str,
    seed: int,
) -> float:
    data = frame[[value_column, state_column, block_column]].copy()
    data[value_column] = pd.to_numeric(data[value_column], errors="coerce")
    data = data.dropna(subset=[value_column, block_column])
    if data.empty:
        return math.nan
    blocks = sorted(data[block_column].astype(str).unique())
    if not blocks:
        return math.nan
    block_stats: list[tuple[float, int, float, int]] = []
    for block in blocks:
        group = data[data[block_column].astype(str).eq(block)]
        positive = group[group[state_column].astype(bool)][value_column]
        negative = group[~group[state_column].astype(bool)][value_column]
        block_stats.append(
            (
                float(positive.sum()),
                int(len(positive)),
                float(negative.sum()),
                int(len(negative)),
            )
        )
    stats = np.asarray(block_stats, dtype=float)
    rng = np.random.default_rng(seed)
    spreads: list[float] = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sampled = stats[rng.integers(0, len(stats), size=len(stats))].sum(axis=0)
        if sampled[1] <= 0 or sampled[3] <= 0:
            continue
        spreads.append(float(sampled[0] / sampled[1] - sampled[2] / sampled[3]))
    if not spreads:
        return math.nan
    return float(np.quantile(np.asarray(spreads), BOOTSTRAP_ALPHA))


def right_tail_screen(rows: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    if rows.empty:
        return pd.DataFrame(), {"status": "BLOCKED_MISSING_DROP_COUNTERFACTUALS"}
    required = {
        "portfolio",
        "drop_date",
        "drop_skill_evidence_flag",
        "candidate_rank_percentile",
        "drop_signal_stack_count",
        "used_forward_return_in_ranking",
        "fwd_63d_excess_spy",
        "fwd_126d_excess_spy",
    }
    missing = sorted(required - set(rows.columns))
    if missing:
        return pd.DataFrame(), {
            "status": "BLOCKED_SCHEMA",
            "missing_columns": missing,
        }
    out = rows.copy()
    out["drop_date"] = pd.to_datetime(out["drop_date"], errors="coerce")
    out = out.dropna(subset=["drop_date"])
    out["high_signal"] = high_signal_mask(out)
    out["decision_week"] = out["drop_date"].dt.to_period("W-FRI").astype(str)
    leakage_count = int(bool_series(out["used_forward_return_in_ranking"]).sum())
    metrics: list[dict[str, Any]] = []
    portfolio_verdicts: dict[str, Any] = {}
    for portfolio in sorted(out["portfolio"].dropna().astype(str).unique()):
        portfolio_failures: list[str] = []
        portfolio_rows = out[out["portfolio"].astype(str).eq(portfolio)]
        for window, start in WINDOWS.items():
            window_rows = portfolio_rows[portfolio_rows["drop_date"].ge(start)].copy()
            for horizon in HORIZONS:
                value_column = f"fwd_{horizon}d_excess_spy"
                completed = window_rows.dropna(subset=[value_column]).copy()
                completed[value_column] = pd.to_numeric(completed[value_column], errors="coerce")
                completed = completed.dropna(subset=[value_column])
                positive = completed[completed["high_signal"]][value_column]
                negative = completed[~completed["high_signal"]][value_column]
                pos_mean = float(positive.mean()) if not positive.empty else math.nan
                neg_mean = float(negative.mean()) if not negative.empty else math.nan
                spread = pos_mean - neg_mean
                lower = cluster_bootstrap_lower(
                    completed,
                    value_column,
                    "high_signal",
                    "decision_week",
                    stable_seed(portfolio, window, str(horizon)),
                )
                block_count = int(completed["decision_week"].nunique())
                metrics.append(
                    {
                        "portfolio": portfolio,
                        "window": window,
                        "horizon": horizon,
                        "high_signal_count": int(len(positive)),
                        "comparator_count": int(len(negative)),
                        "decision_week_block_count": block_count,
                        "high_signal_mean": pos_mean,
                        "comparator_mean": neg_mean,
                        "high_minus_comparator_mean": spread,
                        "high_signal_median": float(positive.median()) if not positive.empty else math.nan,
                        "comparator_median": float(negative.median()) if not negative.empty else math.nan,
                        "week_cluster_bootstrap_95_lower": lower,
                        "used_forward_return_in_ranking": False,
                    }
                )
                if horizon != PRIMARY_HORIZON:
                    continue
                if not math.isfinite(spread) or spread <= 0.0:
                    portfolio_failures.append(f"{window}_direction_not_positive")
                if window in {"oos2", "oos"}:
                    if len(positive) < MIN_EVENTS_PER_STATE or len(negative) < MIN_EVENTS_PER_STATE:
                        portfolio_failures.append(f"{window}_underpowered_event_count")
                    if block_count < MIN_DECISION_WEEK_BLOCKS:
                        portfolio_failures.append(f"{window}_underpowered_week_blocks")
                    if not math.isfinite(lower) or lower < 0.0:
                        portfolio_failures.append(f"{window}_bootstrap_lower_negative")
        unique_failures = sorted(set(portfolio_failures))
        portfolio_verdicts[portfolio] = {
            "status": "PASS_SOURCE_SCREEN" if not unique_failures and leakage_count == 0 else "REJECT_SOURCE_SCREEN",
            "failures": unique_failures,
        }
    if leakage_count:
        status = "BLOCKED_FORWARD_LABEL_LEAKAGE"
    elif portfolio_verdicts and all(
        item["status"] == "PASS_SOURCE_SCREEN" for item in portfolio_verdicts.values()
    ):
        status = "PASS_SOURCE_SCREEN"
    else:
        status = "REJECT_SOURCE_SCREEN"
    return pd.DataFrame(metrics), {
        "status": status,
        "forward_label_leakage_count": leakage_count,
        "portfolios": portfolio_verdicts,
    }


def render_report(summary: dict[str, Any], memory: pd.DataFrame, screen: pd.DataFrame) -> str:
    lines = [
        "# Run287 Trade Selection Research Audit",
        "",
        f"Overall status: `{summary.get('status')}`",
        "",
        "This is a research-only, fail-closed audit. It does not change target books,",
        "scores, ranks, weights, cash, orders, production, or live trading.",
        "",
        "## Issuer re-entry memory",
        "",
        "The label uses each historical trade's realized, unequal holding period, so this",
        "lane is diagnostic only and can never open a portfolio A/B from this artifact.",
        "",
    ]
    for row in memory.to_dict(orient="records"):
        lines.append(
            "- "
            f"{row['window']}: positive n={row['positive_count']}, negative n={row['negative_count']}, "
            f"spread={finite_float(row['positive_minus_negative_mean_alpha']) or 0.0:.4%}"
        )
    lines.extend(["", "## Conditional right-tail retention", ""])
    if screen.empty:
        lines.append("No valid fixed-horizon rows were available.")
    else:
        primary = screen[screen["horizon"].eq(PRIMARY_HORIZON)]
        for row in primary.to_dict(orient="records"):
            lines.append(
                "- "
                f"{row['portfolio']} {row['window']} 63D: "
                f"high n={row['high_signal_count']}, comparator n={row['comparator_count']}, "
                f"spread={finite_float(row['high_minus_comparator_mean']) or 0.0:.4%}, "
                f"bootstrap lower={finite_float(row['week_cluster_bootstrap_95_lower']) or 0.0:.4%}"
            )
    lines.extend(
        [
            "",
            "A failed direction, power, clustered-confidence, or leakage gate blocks fixed-book",
            "and generated-book replay. Recent-window point estimates alone cannot reopen it.",
            "",
        ]
    )
    return "\n".join(lines)


def run(trade_notebook: Path, drop_counterfactuals: Path, output_dir: Path) -> dict[str, Any]:
    trade_notebook = repo_path(trade_notebook)
    drop_counterfactuals = repo_path(drop_counterfactuals)
    output_dir = repo_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    trades = read_csv(trade_notebook)
    drop_rows = read_csv(drop_counterfactuals)
    memory_rows = prior_trade_memory_rows(trades)
    memory_metrics = memory_summary(memory_rows)
    right_tail_metrics, right_tail = right_tail_screen(drop_rows)

    memory_metrics.to_csv(output_dir / "issuer_reentry_memory_screen.csv", index=False)
    right_tail_metrics.to_csv(output_dir / "right_tail_drop_source_screen.csv", index=False)
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": right_tail.get("status", "BLOCKED"),
        "research_only": True,
        "posthoc_closure_not_preregistered_pass": True,
        "fullrun_dispatched": False,
        "target_books_mutated": False,
        "score_rank_selector_changed": False,
        "cash_policy_changed": False,
        "orders_generated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "used_forward_return_in_ranking": False,
        "fixed_windows": {key: value.date().isoformat() for key, value in WINDOWS.items()},
        "gates": {
            "primary_horizon_sessions": PRIMARY_HORIZON,
            "min_events_per_state": MIN_EVENTS_PER_STATE,
            "min_decision_week_blocks": MIN_DECISION_WEEK_BLOCKS,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "bootstrap_alpha": BOOTSTRAP_ALPHA,
            "positive_direction_required_full_oos2_oos": True,
            "nonnegative_bootstrap_lower_required_oos2_oos": True,
        },
        "issuer_reentry_memory": {
            "status": "REJECT_DIAGNOSTIC_VARIABLE_HOLDING_LABEL",
            "trade_count": int(len(trades)),
            "repeat_entry_count": int(memory_rows["prior_ticker_memory"].ne("no_prior").sum())
            if not memory_rows.empty
            else 0,
            "portfolio_ab_eligible": False,
        },
        "right_tail_drop": right_tail,
        "inputs": {
            "trade_notebook": {
                "path": str(trade_notebook),
                "sha256": sha256_file(trade_notebook) if trade_notebook.exists() else None,
            },
            "drop_counterfactuals": {
                "path": str(drop_counterfactuals),
                "sha256": sha256_file(drop_counterfactuals) if drop_counterfactuals.exists() else None,
            },
        },
    }
    write_json(output_dir / "summary.json", summary)
    write_text(output_dir / "report.md", render_report(summary, memory_metrics, right_tail_metrics))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--trade-notebook",
        default="outputs/run287_historical_trade_answer_notebook_20260717/trade_answer_notebook.csv",
    )
    parser.add_argument(
        "--drop-counterfactuals",
        default="outputs/run287_right_tail_drop_counterfactual_audit_20260718/drop_counterfactuals.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/run287_trade_selection_research_audit_20260718",
    )
    args = parser.parse_args(argv)
    summary = run(
        repo_path(args.trade_notebook),
        repo_path(args.drop_counterfactuals),
        repo_path(args.output_dir),
    )
    print(summary["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

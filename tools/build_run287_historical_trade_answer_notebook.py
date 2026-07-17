#!/usr/bin/env python3
"""Grade historical Run287 entries and exits at fixed forward horizons.

Entry quality uses the trade journal's realized return and same-period alpha.
Exit quality is a descriptive opportunity-cost check: from the first close
after the recorded exit decision, did the exited ticker beat SPY over
21/63/126 sessions?  The primary horizon is fixed at 63 sessions.  A positive
post-exit spread is a possible premature-exit review, not proof that holding
was optimal because the replacement portfolio is not represented here.

This tool is report-only and cannot modify a model, selector, portfolio, cash
policy, or order.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_weekly_evaluation import load_price_series  # noqa: E402


SCHEMA_VERSION = "run287-historical-trade-answer-notebook-v1"
HORIZONS = (21, 63, 126)
PRIMARY_HORIZON = 63


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "bytes": 0, "sha256": None}
    return {
        "path": str(path),
        "exists": True,
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def read_trades(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        trades = pd.read_parquet(path)
    else:
        trades = pd.read_csv(path, low_memory=False)
    required = {"trade_id", "ticker", "entry_date", "exit_date", "realized_return"}
    missing = required - set(trades.columns)
    if missing:
        raise ValueError(f"trade journal missing columns: {sorted(missing)}")
    output = trades.copy()
    output["ticker"] = output["ticker"].astype(str).str.upper().str.strip()
    output["entry_date"] = pd.to_datetime(output["entry_date"], errors="coerce").dt.normalize()
    output["exit_date"] = pd.to_datetime(output["exit_date"], errors="coerce").dt.normalize()
    output["realized_return"] = pd.to_numeric(output["realized_return"], errors="coerce")
    if "alpha_vs_benchmark" not in output:
        output["alpha_vs_benchmark"] = np.nan
    output["alpha_vs_benchmark"] = pd.to_numeric(output["alpha_vs_benchmark"], errors="coerce")
    output = output.dropna(subset=["entry_date", "exit_date", "realized_return"])
    output = output.loc[output["ticker"].ne("") & output["ticker"].ne("NAN")].copy()
    if output["trade_id"].astype(str).duplicated().any():
        raise ValueError("trade_id must be unique")
    return output.reset_index(drop=True)


def post_exit_path(
    stock: pd.DataFrame,
    benchmark: pd.DataFrame,
    exit_date: pd.Timestamp,
) -> dict[str, Any]:
    output: dict[str, Any] = {"post_exit_entry_date": ""}
    for horizon in HORIZONS:
        output[f"post_exit_{horizon}d_status"] = "pending_price_or_horizon"
        output[f"post_exit_{horizon}d_ticker_return"] = np.nan
        output[f"post_exit_{horizon}d_spy_return"] = np.nan
        output[f"post_exit_{horizon}d_spy_excess"] = np.nan
        output[f"post_exit_{horizon}d_mae"] = np.nan
    if stock.empty or benchmark.empty:
        return output
    joined = stock[["close"]].rename(columns={"close": "ticker"}).join(
        benchmark[["close"]].rename(columns={"close": "spy"}), how="inner"
    ).dropna()
    joined = joined.loc[(joined["ticker"] > 0.0) & (joined["spy"] > 0.0)].sort_index()
    if joined.empty:
        return output
    dates = joined.index.to_numpy(dtype="datetime64[ns]")
    start = int(np.searchsorted(dates, np.datetime64(exit_date), side="right"))
    if start >= len(joined):
        return output
    output["post_exit_entry_date"] = pd.Timestamp(joined.index[start]).date().isoformat()
    ticker_start = float(joined.iloc[start]["ticker"])
    spy_start = float(joined.iloc[start]["spy"])
    for horizon in HORIZONS:
        end = start + horizon
        if end >= len(joined):
            continue
        ticker_return = float(joined.iloc[end]["ticker"] / ticker_start - 1.0)
        spy_return = float(joined.iloc[end]["spy"] / spy_start - 1.0)
        path_return = joined.iloc[start : end + 1]["ticker"].div(ticker_start).sub(1.0)
        output[f"post_exit_{horizon}d_status"] = "completed"
        output[f"post_exit_{horizon}d_ticker_return"] = ticker_return
        output[f"post_exit_{horizon}d_spy_return"] = spy_return
        output[f"post_exit_{horizon}d_spy_excess"] = ticker_return - spy_return
        output[f"post_exit_{horizon}d_mae"] = float(path_return.min())
    return output


def entry_answer(realized_return: Any, alpha: Any) -> str:
    ret = pd.to_numeric(pd.Series([realized_return]), errors="coerce").iloc[0]
    excess = pd.to_numeric(pd.Series([alpha]), errors="coerce").iloc[0]
    if pd.isna(ret):
        return "ENTRY_UNGRADED"
    if pd.isna(excess):
        return "ENTRY_POSITIVE_RETURN" if float(ret) > 0.0 else "ENTRY_NEGATIVE_RETURN"
    if float(ret) > 0.0 and float(excess) > 0.0:
        return "GOOD_ENTRY_POSITIVE_ALPHA"
    if float(ret) <= 0.0 and float(excess) <= 0.0:
        return "WRONG_ENTRY_LOSS_AND_LAG"
    if float(ret) <= 0.0 and float(excess) > 0.0:
        return "DEFENSIVE_ENTRY_LOSS_BUT_OUTPERFORMED"
    return "POSITIVE_ENTRY_BUT_LAGGED"


def grade_trades(trades: pd.DataFrame, price_cache: Path) -> pd.DataFrame:
    benchmark = load_price_series(price_cache, "SPY")
    price_map = {
        ticker: load_price_series(price_cache, ticker)
        for ticker in sorted(trades["ticker"].unique())
    }
    rows: list[dict[str, Any]] = []
    for trade in trades.to_dict("records"):
        row = dict(trade)
        row.update(post_exit_path(price_map.get(str(trade["ticker"]), pd.DataFrame()), benchmark, pd.Timestamp(trade["exit_date"])))
        row["entry_answer"] = entry_answer(row.get("realized_return"), row.get("alpha_vs_benchmark"))
        periods = pd.to_numeric(pd.Series([row.get("n_periods")]), errors="coerce").iloc[0]
        if pd.isna(periods):
            row["holding_period_bucket"] = "UNKNOWN"
        elif float(periods) <= 1:
            row["holding_period_bucket"] = "1_PERIOD"
        elif float(periods) <= 3:
            row["holding_period_bucket"] = "2_TO_3_PERIODS"
        elif float(periods) <= 6:
            row["holding_period_bucket"] = "4_TO_6_PERIODS"
        else:
            row["holding_period_bucket"] = "7_PLUS_PERIODS"
        status = row.get(f"post_exit_{PRIMARY_HORIZON}d_status")
        horizon = PRIMARY_HORIZON
        if status != "completed":
            horizon = 21
            status = row.get("post_exit_21d_status")
        row["exit_grade_horizon"] = horizon if status == "completed" else 0
        excess = row.get(f"post_exit_{horizon}d_spy_excess") if status == "completed" else np.nan
        row["exit_grade_spy_excess"] = excess
        if status != "completed" or pd.isna(excess):
            row["exit_answer"] = "EXIT_PENDING_FIXED_HORIZON"
        elif float(excess) > 0.0:
            row["exit_answer"] = "POSSIBLE_PREMATURE_EXIT_REVIEW"
        else:
            row["exit_answer"] = "GOOD_EXIT_AVOIDED_UNDERPERFORMANCE"
        row["replacement_relative_answer_unknown"] = True
        row["checklist_change_proposed"] = False
        row["automatic_checklist_change_allowed"] = False
        rows.append(row)
    return pd.DataFrame(rows)


def evidence_summary(graded: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for dimension in (
        "entry_answer", "holding_period_bucket", "exit_reason", "entry_sleeve",
        "entry_regime_state", "source_journal",
    ):
        if dimension not in graded:
            continue
        for value, group in graded.groupby(dimension, dropna=False, sort=True):
            exit_ready = group["exit_grade_horizon"].gt(0)
            premature = group["exit_answer"].eq("POSSIBLE_PREMATURE_EXIT_REVIEW")
            entry_wrong = group["entry_answer"].eq("WRONG_ENTRY_LOSS_AND_LAG")
            alpha = pd.to_numeric(group.get("alpha_vs_benchmark"), errors="coerce")
            post = pd.to_numeric(group.get("exit_grade_spy_excess"), errors="coerce")
            ready_count = int(exit_ready.sum())
            rows.append(
                {
                    "dimension": dimension,
                    "value": str(value),
                    "trade_count": int(len(group)),
                    "exit_grade_ready_count": ready_count,
                    "possible_premature_exit_rate": float(premature[exit_ready].mean()) if ready_count else np.nan,
                    "wrong_entry_rate": float(entry_wrong.mean()) if len(group) else np.nan,
                    "mean_holding_alpha": float(alpha.mean()) if alpha.notna().any() else np.nan,
                    "mean_post_exit_spy_excess": float(post.mean()) if post.notna().any() else np.nan,
                    "review_proposal": (
                        "REVIEW_HOLD_EXTENSION_MECHANISM"
                        if ready_count >= 12 and float(premature[exit_ready].mean()) >= 0.60
                        else (
                            "REVIEW_ENTRY_GATE_MECHANISM"
                            if dimension != "entry_answer"
                            and len(group) >= 12
                            and float(entry_wrong.mean()) >= 0.60
                            else "NO_FIXED_CHANGE_PROPOSAL"
                        )
                    ),
                    "automatic_change_allowed": False,
                }
            )
    return pd.DataFrame(rows)


def write_report(output_dir: Path, summary: dict[str, Any], graded: pd.DataFrame, evidence: pd.DataFrame) -> None:
    premature = graded[graded["exit_answer"].eq("POSSIBLE_PREMATURE_EXIT_REVIEW")].sort_values(
        "exit_grade_spy_excess", ascending=False
    )
    wrong = graded[graded["entry_answer"].eq("WRONG_ENTRY_LOSS_AND_LAG")].sort_values(
        "alpha_vs_benchmark", ascending=True
    )
    lines = [
        "# Run287 Historical Trade Answer Notebook",
        "",
        f"Status: `{summary['status']}`",
        "",
        "The exit grade compares the exited ticker with SPY after the exit. It does not know the replacement portfolio, so a positive result is a review item rather than proof that the sale was wrong.",
        "",
        "## Summary",
        "",
        f"- trades: {summary['trade_count']}",
        f"- fixed-horizon exits resolved: {summary['exit_grade_ready_count']}",
        f"- possible premature-exit reviews: {summary['possible_premature_exit_count']}",
        f"- good exits versus SPY: {summary['good_exit_count']}",
        f"- wrong entry loss and lag: {summary['wrong_entry_count']}",
        "",
        "## Largest Post-Exit Continuations",
        "",
        "| ticker | entry | exit | holding return | holding alpha | post-exit horizon | post-exit SPY excess |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in premature.head(20).itertuples(index=False):
        lines.append(
            f"| {row.ticker} | {pd.Timestamp(row.entry_date).date()} | {pd.Timestamp(row.exit_date).date()} | "
            f"{float(row.realized_return):.2%} | {float(row.alpha_vs_benchmark):.2%} | "
            f"{int(row.exit_grade_horizon)}D | {float(row.exit_grade_spy_excess):.2%} |"
        )
    lines.extend(
        [
            "",
            "## Worst Entries",
            "",
            "| ticker | entry | exit | holding return | holding alpha | sleeve | regime |",
            "| --- | --- | --- | ---: | ---: | --- | --- |",
        ]
    )
    for row in wrong.head(20).itertuples(index=False):
        lines.append(
            f"| {row.ticker} | {pd.Timestamp(row.entry_date).date()} | {pd.Timestamp(row.exit_date).date()} | "
            f"{float(row.realized_return):.2%} | {float(row.alpha_vs_benchmark):.2%} | "
            f"{getattr(row, 'entry_sleeve', '')} | {getattr(row, 'entry_regime_state', '')} |"
        )
    proposals = evidence[evidence["review_proposal"].ne("NO_FIXED_CHANGE_PROPOSAL")]
    lines.extend(["", "## Evidence-Based Review Proposals", ""])
    if proposals.empty:
        lines.append("No group reached the fixed count/rate proposal threshold.")
    else:
        lines.extend(
            [
                "| dimension | value | n | proposal | premature rate | wrong-entry rate |",
                "| --- | --- | ---: | --- | ---: | ---: |",
            ]
        )
        for row in proposals.itertuples(index=False):
            lines.append(
                f"| {row.dimension} | {row.value} | {int(row.trade_count)} | {row.review_proposal} | "
                f"{float(row.possible_premature_exit_rate):.2%} | {float(row.wrong_entry_rate):.2%} |"
            )
    lines.extend(
        [
            "",
            "No rule was changed. A review proposal must be preregistered and pass fixed-book OOS/OOS2, costs, concentration, and drawdown gates before any portfolio A/B.",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(args: argparse.Namespace) -> dict[str, Any]:
    trade_path = repo_path(args.trade_journal)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trades = read_trades(trade_path)
    graded = grade_trades(trades, price_cache)
    evidence = evidence_summary(graded)
    graded.to_csv(output_dir / "trade_answer_notebook.csv", index=False, lineterminator="\n")
    evidence.to_csv(output_dir / "checklist_evidence_summary.csv", index=False, lineterminator="\n")
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_RUN287_HISTORICAL_TRADE_ANSWER_NOTEBOOK_REVIEW_ONLY",
        "trade_count": int(len(graded)),
        "unique_ticker_count": int(graded["ticker"].nunique()),
        "entry_date_min": pd.Timestamp(graded["entry_date"].min()).date().isoformat(),
        "exit_date_max": pd.Timestamp(graded["exit_date"].max()).date().isoformat(),
        "primary_exit_horizon_sessions": PRIMARY_HORIZON,
        "exit_grade_ready_count": int(graded["exit_grade_horizon"].gt(0).sum()),
        "possible_premature_exit_count": int(
            graded["exit_answer"].eq("POSSIBLE_PREMATURE_EXIT_REVIEW").sum()
        ),
        "good_exit_count": int(
            graded["exit_answer"].eq("GOOD_EXIT_AVOIDED_UNDERPERFORMANCE").sum()
        ),
        "wrong_entry_count": int(graded["entry_answer"].eq("WRONG_ENTRY_LOSS_AND_LAG").sum()),
        "review_proposal_count": int(evidence["review_proposal"].ne("NO_FIXED_CHANGE_PROPOSAL").sum()),
        "source_inputs": {
            "trade_journal": fingerprint(trade_path),
            "price_cache": {"path": str(price_cache), "exists": price_cache.is_dir()},
        },
        "outputs": {
            "trade_answer_notebook": fingerprint(output_dir / "trade_answer_notebook.csv"),
            "checklist_evidence_summary": fingerprint(output_dir / "checklist_evidence_summary.csv"),
        },
        "replacement_relative_answer_known": False,
        "model_mutated": False,
        "score_mutated": False,
        "rank_mutated": False,
        "selector_mutated": False,
        "target_books_mutated": False,
        "cash_policy_mutated": False,
        "orders_generated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "automatic_checklist_change_allowed": False,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_report(output_dir, summary, graded, evidence)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trade-journal", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--output-dir", default="outputs/run287_historical_trade_answer_notebook")
    return parser.parse_args()


if __name__ == "__main__":
    result = build(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))

#!/usr/bin/env python3
"""Build historical holding and trade journey reports.

This is a report-only sidecar. It reconstructs what the engine owned over
time, how long each ticker stayed in each book, which names were repeatedly
churned, and how current holdings relate to past winners. It does not alter
portfolio construction, weights, features, or promotion gates.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from historical_replay_lib import read_table, repo_path, safe_float, write_json, write_rows, write_text  # noqa: E402


DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUTPUT_DIR = "outputs/historical_trade_journey"
CASH_TICKERS = {"", "CASH", "BIL", "SGOV"}

BOOK_SOURCES: tuple[tuple[str, str], ...] = (
    ("production_main", "reports/main_monthly_weights.csv"),
    ("concentrated_grid_presence", "reports/concentrated_strategy_holdings.csv"),
    ("production_tactical", "reports/tactical_monthly_weights.csv"),
    ("production_alpha_sprint", "reports/alpha_sprint_monthly_weights.csv"),
    ("main_v2_research", "main_v2_backtest/monthly_holdings.csv"),
    ("lifecycle_review_overlay_main", "lifecycle_review_overlay_main/holdings.csv"),
    ("monster_lifecycle_main", "monster_lifecycle_review_main/holdings.csv"),
    ("monster_lifecycle_concentrated", "monster_lifecycle_review_concentrated/holdings.csv"),
)


def _read_first_existing(paths: list[Path]) -> pd.DataFrame:
    for path in paths:
        if path.exists():
            return read_table(path)
    return pd.DataFrame()


def _clean_ticker(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out = out[~out["ticker"].isin(CASH_TICKERS)]
    return out


def _normalize_book(frame: pd.DataFrame, book: str, source_path: Path) -> pd.DataFrame:
    frame = _clean_ticker(frame)
    if frame.empty:
        return pd.DataFrame()
    if "rebalance_date" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")
    out = out.dropna(subset=["rebalance_date", "ticker"])
    if out.empty:
        return out
    for col in ("weight", "period_forward_return", "weighted_forward_return", "raw_score"):
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    if "weighted_forward_return" not in frame.columns:
        out["weighted_forward_return"] = out["weight"] * out["period_forward_return"]
    for col in ("Name", "sector", "portfolio_sleeve_label", "regime_state"):
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].fillna("").astype(str)
    out["book"] = book
    out["source_path"] = str(source_path)
    out["duplicate_config_count"] = 1
    out = _dedupe_book_rows(out)
    return out.sort_values(["book", "ticker", "rebalance_date"])


def _dedupe_book_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Collapse same date/ticker duplicates from grid artifacts.

    Some research reports, especially concentrated_strategy_holdings.csv,
    contain one row per tested grid configuration. Those rows are useful for
    presence diagnostics but are not distinct monthly holds. Collapsing them
    prevents impossible 300+ month runs inside an 8-year backtest.
    """
    if frame.empty:
        return frame
    keys = ["book", "ticker", "rebalance_date"]
    if not all(key in frame.columns for key in keys):
        return frame
    if not frame.duplicated(keys).any():
        return frame
    rows: list[dict[str, Any]] = []
    for _, group in frame.groupby(keys, sort=False):
        first = group.iloc[0].to_dict()
        for col in ("weight", "period_forward_return", "weighted_forward_return", "raw_score"):
            if col in group.columns:
                numeric = pd.to_numeric(group[col], errors="coerce")
                if col in {"weight", "weighted_forward_return", "raw_score"}:
                    first[col] = float(numeric.max()) if numeric.notna().any() else 0.0
                else:
                    first[col] = float(numeric.mean()) if numeric.notna().any() else 0.0
        for col in ("Name", "sector", "portfolio_sleeve_label", "regime_state", "source_path"):
            if col in group.columns:
                first[col] = _last_nonempty(group[col])
        first["duplicate_config_count"] = int(len(group))
        rows.append(first)
    return pd.DataFrame(rows)


def load_holding_books(latest_run: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for book, rel_path in BOOK_SOURCES:
        path = latest_run / rel_path
        frame = _normalize_book(read_table(path), book, path)
        if not frame.empty:
            frames.append(frame)
    if frames:
        return pd.concat(frames, ignore_index=True)

    fallback = _read_first_existing(
        [
            latest_run / "trade_journal" / "holdings_history.csv",
            latest_run / "trade_journal" / "holdings_history.parquet",
        ]
    )
    fallback = _normalize_book(fallback, "trade_journal_main", latest_run / "trade_journal")
    return fallback


def load_trades(latest_run: Path) -> pd.DataFrame:
    trades = _read_first_existing(
        [
            latest_run / "trade_journal" / "trades.csv",
            latest_run / "trade_journal" / "trades.parquet",
        ]
    )
    if trades.empty or "ticker" not in trades.columns:
        return pd.DataFrame()
    out = _clean_ticker(trades)
    for col in ("entry_date", "exit_date"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")
    for col in ("realized_return", "alpha_vs_benchmark", "holding_days", "n_periods"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def load_current_holdings(latest_run: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for book, rel_path in (
        ("current_main", "portfolio_latest.csv"),
        ("current_concentrated", "concentrated_portfolio_latest.csv"),
    ):
        path = latest_run / rel_path
        frame = _clean_ticker(read_table(path))
        if frame.empty:
            continue
        if "weight" not in frame.columns:
            frame["weight"] = 0.0
        frame["weight"] = pd.to_numeric(frame["weight"], errors="coerce").fillna(0.0)
        frame["book"] = book
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _compound(values: pd.Series) -> float:
    rets = pd.to_numeric(values, errors="coerce").fillna(0.0)
    equity = 1.0
    for ret in rets:
        if math.isfinite(float(ret)):
            equity *= 1.0 + float(ret)
    return equity - 1.0


def _first_nonempty(values: pd.Series) -> str:
    for value in values:
        text = str(value).strip()
        if text and text.lower() != "nan":
            return text
    return ""


def _last_nonempty(values: pd.Series) -> str:
    for value in reversed(list(values)):
        text = str(value).strip()
        if text and text.lower() != "nan":
            return text
    return ""


def build_holding_runs(books: pd.DataFrame) -> pd.DataFrame:
    if books.empty:
        return pd.DataFrame()
    latest_by_book = books.groupby("book")["rebalance_date"].max().to_dict()
    rows: list[dict[str, Any]] = []
    for (book, ticker), group in books.groupby(["book", "ticker"], sort=True):
        group = group.sort_values("rebalance_date").reset_index(drop=True)
        if group.empty:
            continue
        start_idx = 0
        for idx in range(1, len(group) + 1):
            split = idx == len(group)
            if not split:
                gap_days = (group.loc[idx, "rebalance_date"] - group.loc[idx - 1, "rebalance_date"]).days
                split = gap_days > 45
            if not split:
                continue
            block = group.iloc[start_idx:idx].copy()
            start_idx = idx
            start_date = block["rebalance_date"].iloc[0]
            end_date = block["rebalance_date"].iloc[-1]
            latest_date = latest_by_book.get(book)
            months_held = int(len(block))
            total_return = _compound(block["period_forward_return"])
            weighted_contribution = float(pd.to_numeric(block["weighted_forward_return"], errors="coerce").fillna(0.0).sum())
            avg_weight = float(pd.to_numeric(block["weight"], errors="coerce").fillna(0.0).mean())
            max_weight = float(pd.to_numeric(block["weight"], errors="coerce").fillna(0.0).max())
            recent_3m_return = _compound(block["period_forward_return"].tail(3))
            status = "open" if latest_date is not None and end_date == latest_date else "closed"
            rows.append(
                {
                    "book": book,
                    "ticker": ticker,
                    "name": _last_nonempty(block["Name"]) if "Name" in block.columns else "",
                    "sector": _last_nonempty(block["sector"]) if "sector" in block.columns else "",
                    "first_sleeve": _first_nonempty(block["portfolio_sleeve_label"]) if "portfolio_sleeve_label" in block.columns else "",
                    "last_sleeve": _last_nonempty(block["portfolio_sleeve_label"]) if "portfolio_sleeve_label" in block.columns else "",
                    "entry_date": start_date.strftime("%Y-%m-%d"),
                    "exit_date": end_date.strftime("%Y-%m-%d"),
                    "status": status,
                    "months_held": months_held,
                    "total_return": total_return,
                    "recent_3m_return": recent_3m_return,
                    "weighted_contribution": weighted_contribution,
                    "avg_weight": avg_weight,
                    "max_weight": max_weight,
                    "entry_score": safe_float(block["raw_score"].iloc[0]) if "raw_score" in block.columns else 0.0,
                    "exit_score": safe_float(block["raw_score"].iloc[-1]) if "raw_score" in block.columns else 0.0,
                    "entry_regime": _first_nonempty(block["regime_state"]) if "regime_state" in block.columns else "",
                    "exit_regime": _last_nonempty(block["regime_state"]) if "regime_state" in block.columns else "",
                    "journey_tag": _journey_tag(months_held, total_return, recent_3m_return, status),
                }
            )
    return pd.DataFrame(rows).sort_values(["book", "entry_date", "ticker"])


def _journey_tag(months_held: int, total_return: float, recent_3m_return: float, status: str) -> str:
    if status == "open" and months_held >= 6 and recent_3m_return <= -0.05:
        return "open_stale_watch"
    if status == "open" and months_held >= 6 and total_return >= 0.50:
        return "open_winner_hold"
    if months_held <= 3 and total_return >= 0.20:
        return "short_big_win_review"
    if months_held <= 2 and total_return <= -0.10:
        return "quick_loss"
    if months_held >= 6 and total_return >= 0.50:
        return "long_winner"
    return "normal"


def trade_summary_by_ticker(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for ticker, group in trades.groupby("ticker", sort=True):
        realized = pd.to_numeric(group.get("realized_return"), errors="coerce").fillna(0.0)
        alpha = pd.to_numeric(group.get("alpha_vs_benchmark"), errors="coerce")
        holding_days = pd.to_numeric(group.get("holding_days"), errors="coerce")
        win_rate = float((realized > 0).mean()) if len(realized) else 0.0
        rows.append(
            {
                "ticker": ticker,
                "trade_count": int(len(group)),
                "win_rate": win_rate,
                "compound_realized_return": _compound(realized),
                "avg_realized_return": float(realized.mean()) if len(realized) else 0.0,
                "best_trade_return": float(realized.max()) if len(realized) else 0.0,
                "worst_trade_return": float(realized.min()) if len(realized) else 0.0,
                "avg_alpha_vs_benchmark": float(alpha.mean()) if alpha.notna().any() else None,
                "avg_holding_days": float(holding_days.mean()) if holding_days.notna().any() else None,
                "max_holding_days": float(holding_days.max()) if holding_days.notna().any() else None,
                "dominant_exit_reason": _mode_text(group.get("exit_reason")),
                "churn_tag": _churn_tag(len(group), holding_days.mean() if holding_days.notna().any() else None, realized.mean() if len(realized) else 0.0),
            }
        )
    return pd.DataFrame(rows).sort_values(["compound_realized_return", "trade_count"], ascending=[False, False])


def _mode_text(series: pd.Series | None) -> str:
    if series is None:
        return ""
    counts = series.fillna("").astype(str).value_counts()
    return str(counts.index[0]) if not counts.empty else ""


def _churn_tag(trade_count: int, avg_holding_days: float | None, avg_return: float) -> str:
    if trade_count >= 4 and avg_holding_days is not None and avg_holding_days <= 75:
        if avg_return > 0.0:
            return "profitable_reentry_churn"
        return "unproductive_reentry_churn"
    if avg_holding_days is not None and avg_holding_days >= 180 and avg_return > 0.10:
        return "patient_winner"
    return "normal"


def leader_rotation_timeline(books: pd.DataFrame, top_n: int = 8) -> pd.DataFrame:
    if books.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for (book, date), group in books.groupby(["book", "rebalance_date"], sort=True):
        ranked = group.sort_values("weight", ascending=False).head(top_n)
        rows.append(
            {
                "book": book,
                "rebalance_date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                "top_tickers": ",".join(ranked["ticker"].astype(str).tolist()),
                "top_weights": ",".join(f"{float(x):.4f}" for x in ranked["weight"].tolist()),
                "n_positions": int(len(group)),
                "cash_estimate": max(0.0, 1.0 - float(pd.to_numeric(group["weight"], errors="coerce").fillna(0.0).sum())),
            }
        )
    timeline = pd.DataFrame(rows)
    if timeline.empty:
        return timeline
    out_rows: list[dict[str, Any]] = []
    for book, group in timeline.groupby("book", sort=True):
        prev: set[str] = set()
        for row in group.sort_values("rebalance_date").to_dict("records"):
            cur = set(str(row["top_tickers"]).split(",")) if row.get("top_tickers") else set()
            out_rows.append(
                {
                    **row,
                    "entered_top": ",".join(sorted(cur - prev)),
                    "left_top": ",".join(sorted(prev - cur)),
                }
            )
            prev = cur
    return pd.DataFrame(out_rows)


def current_vs_history(current: pd.DataFrame, runs: pd.DataFrame) -> pd.DataFrame:
    if current.empty or runs.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for row in current.to_dict("records"):
        ticker = str(row.get("ticker") or "").upper()
        hist = runs[runs["ticker"] == ticker].copy()
        if hist.empty:
            rows.append(
                {
                    "current_book": row.get("book", ""),
                    "ticker": ticker,
                    "current_weight": safe_float(row.get("weight")),
                    "history_status": "new_unseen",
                }
            )
            continue
        open_runs = hist[hist["status"] == "open"].sort_values("exit_date")
        current_run = open_runs.iloc[-1].to_dict() if not open_runs.empty else hist.sort_values("exit_date").iloc[-1].to_dict()
        total_months = int(pd.to_numeric(hist["months_held"], errors="coerce").fillna(0).sum())
        total_contribution = float(pd.to_numeric(hist["weighted_contribution"], errors="coerce").fillna(0.0).sum())
        rows.append(
            {
                "current_book": row.get("book", ""),
                "ticker": ticker,
                "name": row.get("Name") or row.get("name") or current_run.get("name", ""),
                "sector": row.get("sector") or current_run.get("sector", ""),
                "current_weight": safe_float(row.get("weight")),
                "history_status": "open_history" if current_run.get("status") == "open" else "returning_after_gap",
                "first_seen": hist["entry_date"].min(),
                "last_seen": hist["exit_date"].max(),
                "total_months_held": total_months,
                "run_count": int(len(hist)),
                "current_run_months": current_run.get("months_held"),
                "current_run_return": current_run.get("total_return"),
                "current_run_recent_3m_return": current_run.get("recent_3m_return"),
                "current_run_tag": current_run.get("journey_tag"),
                "historical_weighted_contribution": total_contribution,
            }
        )
    return pd.DataFrame(rows).sort_values(["current_book", "current_weight"], ascending=[True, False])


def _top_records(frame: pd.DataFrame, sort_col: str, n: int = 10, ascending: bool = False) -> list[dict[str, Any]]:
    if frame.empty or sort_col not in frame.columns:
        return []
    return frame.sort_values(sort_col, ascending=ascending).head(n).to_dict("records")


def build_report(
    summary: dict[str, Any],
    runs: pd.DataFrame,
    trades_by_ticker: pd.DataFrame,
    current_history: pd.DataFrame,
) -> str:
    def table(rows: list[dict[str, Any]], cols: list[str]) -> str:
        if not rows:
            return "_None._\n"
        lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
        for row in rows:
            vals = []
            for col in cols:
                value = row.get(col, "")
                if isinstance(value, float):
                    if not math.isfinite(value):
                        vals.append("")
                        continue
                    if "return" in col or "weight" in col or "contribution" in col:
                        vals.append(f"{value:.2%}")
                    else:
                        vals.append(f"{value:.4f}")
                else:
                    vals.append(str(value))
            lines.append("| " + " | ".join(vals) + " |")
        return "\n".join(lines) + "\n"

    longest = _top_records(runs, "months_held", 10)
    contributors = _top_records(runs, "weighted_contribution", 10)
    short_wins = runs[runs.get("journey_tag", "") == "short_big_win_review"] if not runs.empty else pd.DataFrame()
    stale_open = runs[runs.get("journey_tag", "") == "open_stale_watch"] if not runs.empty else pd.DataFrame()
    churn = trades_by_ticker[trades_by_ticker.get("churn_tag", "") != "normal"] if not trades_by_ticker.empty else pd.DataFrame()

    return (
        "# Historical Trade Journey\n\n"
        f"Status: `{summary.get('status', 'unknown')}`\n\n"
        "This report is sidecar-only. It reconstructs historical holdings and round-trip trades so current decisions can be compared against past ownership behavior.\n\n"
        "## Summary\n\n"
        f"- Holding books: {summary.get('holding_books', [])}\n"
        f"- Holding runs: {summary.get('holding_run_count', 0)}\n"
        f"- Unique held tickers: {summary.get('unique_held_tickers', 0)}\n"
        f"- Average run length: {summary.get('avg_run_months', 0):.2f} months\n"
        f"- Median run length: {summary.get('median_run_months', 0):.2f} months\n"
        f"- Runs >= 6m / 12m: {summary.get('runs_ge_6m', 0)} / {summary.get('runs_ge_12m', 0)}\n"
        f"- Trade journal rows: {summary.get('trade_count', 0)}\n"
        "\n## Longest Holding Runs\n\n"
        + table(longest, ["book", "ticker", "entry_date", "exit_date", "status", "months_held", "total_return", "max_weight", "journey_tag"])
        + "\n## Largest Weighted Contributors\n\n"
        + table(contributors, ["book", "ticker", "entry_date", "exit_date", "months_held", "total_return", "weighted_contribution", "journey_tag"])
        + "\n## Short Big Wins To Review\n\n"
        + table(_top_records(short_wins, "total_return", 12), ["book", "ticker", "entry_date", "exit_date", "months_held", "total_return", "journey_tag"])
        + "\n## Open Stale Watch\n\n"
        + table(_top_records(stale_open, "recent_3m_return", 12, ascending=True), ["book", "ticker", "entry_date", "exit_date", "months_held", "total_return", "recent_3m_return", "journey_tag"])
        + "\n## Current Holdings Versus History\n\n"
        + table(current_history.to_dict("records") if not current_history.empty else [], ["current_book", "ticker", "current_weight", "history_status", "total_months_held", "run_count", "current_run_months", "current_run_return", "current_run_tag"])
        + "\n## Reentry Churn Watch\n\n"
        + table(_top_records(churn, "trade_count", 15), ["ticker", "trade_count", "win_rate", "avg_realized_return", "avg_holding_days", "compound_realized_return", "churn_tag"])
    )


def analyze(latest_run: Path, output_dir: Path) -> dict[str, Any]:
    latest_run = repo_path(latest_run)
    output_dir = repo_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    books = load_holding_books(latest_run)
    trades = load_trades(latest_run)
    current = load_current_holdings(latest_run)

    if books.empty and trades.empty:
        summary = {
            "status": "blocked",
            "reason": "No historical holding books or trade journal files found.",
            "latest_run": str(latest_run),
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "summary.json", summary)
        write_text(output_dir / "report.md", "# Historical Trade Journey\n\nStatus: `blocked`\n\nNo historical holding books or trade journal files found.\n")
        return summary

    runs = build_holding_runs(books)
    trades_by_ticker = trade_summary_by_ticker(trades)
    timeline = leader_rotation_timeline(books)
    current_history = current_vs_history(current, runs)

    if not runs.empty:
        run_months = pd.to_numeric(runs["months_held"], errors="coerce").fillna(0)
        summary: dict[str, Any] = {
            "status": "completed",
            "latest_run": str(latest_run),
            "holding_books": sorted(books["book"].unique().tolist()) if not books.empty else [],
            "holding_rows": int(len(books)),
            "holding_run_count": int(len(runs)),
            "unique_held_tickers": int(runs["ticker"].nunique()),
            "avg_run_months": float(run_months.mean()) if len(run_months) else 0.0,
            "median_run_months": float(run_months.median()) if len(run_months) else 0.0,
            "p90_run_months": float(run_months.quantile(0.90)) if len(run_months) else 0.0,
            "max_run_months": int(run_months.max()) if len(run_months) else 0,
            "runs_ge_6m": int((run_months >= 6).sum()),
            "runs_ge_12m": int((run_months >= 12).sum()),
            "short_big_win_review_count": int((runs["journey_tag"] == "short_big_win_review").sum()),
            "open_stale_watch_count": int((runs["journey_tag"] == "open_stale_watch").sum()),
            "trade_count": int(len(trades)),
            "trade_summary_ticker_count": int(len(trades_by_ticker)),
            "research_only": True,
            "production_activation_allowed": False,
        }
    else:
        summary = {
            "status": "completed_no_holding_runs",
            "latest_run": str(latest_run),
            "holding_books": [],
            "holding_rows": int(len(books)),
            "holding_run_count": 0,
            "trade_count": int(len(trades)),
            "trade_summary_ticker_count": int(len(trades_by_ticker)),
            "research_only": True,
            "production_activation_allowed": False,
        }

    if not trades.empty and "exit_reason" in trades.columns:
        summary["exit_reason_counts"] = trades["exit_reason"].fillna("").astype(str).value_counts().head(20).to_dict()

    write_json(output_dir / "summary.json", summary)
    if not runs.empty:
        write_rows(output_dir / "holding_runs.csv", runs.to_dict("records"))
    if not trades_by_ticker.empty:
        write_rows(output_dir / "trade_summary_by_ticker.csv", trades_by_ticker.to_dict("records"))
    if not timeline.empty:
        write_rows(output_dir / "leader_rotation_timeline.csv", timeline.to_dict("records"))
    if not current_history.empty:
        write_rows(output_dir / "current_vs_history.csv", current_history.to_dict("records"))
    if not books.empty:
        thin_cols = [
            col
            for col in [
                "book",
                "rebalance_date",
                "ticker",
                "Name",
                "sector",
                "weight",
                "raw_score",
                "portfolio_sleeve_label",
                "period_forward_return",
                "weighted_forward_return",
                "regime_state",
            ]
            if col in books.columns
        ]
        journey = books[thin_cols].copy()
        journey["rebalance_date"] = journey["rebalance_date"].dt.strftime("%Y-%m-%d")
        write_rows(output_dir / "ticker_journey.csv", journey.to_dict("records"))
    write_text(output_dir / "report.md", build_report(summary, runs, trades_by_ticker, current_history))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = analyze(repo_path(args.latest_run), repo_path(args.output_dir))
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

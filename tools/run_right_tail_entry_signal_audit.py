#!/usr/bin/env python3
"""Audit whether right-tail winners had ex-ante entry signals.

Research-only diagnostic. This tool uses realized/open-position PnL only to
choose names for review, then evaluates each name using candidate/target-book
features available at the entry signal date. It does not mutate ranking,
selection, target books, cash policy, workflows, or trading.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


SCHEMA_VERSION = "right-tail-entry-signal-audit-v1"
PORTFOLIOS = ("main", "concentrated")
CASH_TICKERS = {"", "CASH", "__CASH__", "BIL", "SGOV"}


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent.parent / path


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def clean_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def date_col(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(pd.NaT, index=df.index)
    return pd.to_datetime(df[column], errors="coerce").dt.tz_localize(None)


def _candidate_book(latest_run: Path) -> pd.DataFrame:
    candidates = read_csv(latest_run / "reports" / "candidate_replay_book.csv")
    if candidates.empty:
        return candidates
    out = candidates.copy()
    out["ticker"] = out.get("ticker", "").map(clean_ticker)
    out["rebalance_date"] = date_col(out, "rebalance_date")
    out["score_numeric"] = pd.to_numeric(out.get("score"), errors="coerce")
    out = out.dropna(subset=["rebalance_date"])
    return out


def _target_book(latest_run: Path, portfolio: str) -> pd.DataFrame:
    paths = [
        latest_run / "alphaops_vnext" / f"official_{portfolio}_target_book.csv",
        latest_run / "reports" / f"operating_{portfolio}_target_book.csv",
    ]
    for path in paths:
        raw = read_csv(path)
        if not raw.empty:
            out = raw.copy()
            out["ticker"] = out.get("ticker", "").map(clean_ticker)
            out["rebalance_date"] = date_col(out, "rebalance_date")
            return out.dropna(subset=["rebalance_date"])
    return pd.DataFrame()


def _winner_rows(latest_run: Path, portfolio: str, top_n: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    positions_path = latest_run / "broker_replay" / portfolio / "positions_latest.csv"
    positions = read_csv(positions_path)
    if positions.empty or "ticker" not in positions.columns:
        return pd.DataFrame(), {"status": "missing_positions_latest", "source": str(positions_path)}
    out = positions.copy()
    out["ticker"] = out["ticker"].map(clean_ticker)
    out = out[~out["ticker"].isin(CASH_TICKERS)].copy()
    out["realized_pnl_usd"] = pd.to_numeric(out.get("realized_pnl_usd"), errors="coerce").fillna(0.0)
    out["unrealized_pnl_usd"] = pd.to_numeric(out.get("unrealized_pnl_usd"), errors="coerce").fillna(0.0)
    out["pnl_usd"] = out["realized_pnl_usd"] + out["unrealized_pnl_usd"]
    out = out.sort_values("pnl_usd", ascending=False).head(top_n).reset_index(drop=True)
    total_positive = float(out["pnl_usd"].clip(lower=0.0).sum())
    out["positive_contribution_share"] = out["pnl_usd"].clip(lower=0.0) / max(total_positive, 1e-9)
    return out, {
        "status": "completed_positions_latest_partial",
        "source": str(positions_path),
        "coverage_note": "positions_latest includes current open positions plus realized pnl tracked on those tickers; fully closed historical winners may be absent.",
    }


def _first_entry(trades: pd.DataFrame, ticker: str) -> dict[str, Any]:
    if trades.empty:
        return {"entry_status": "missing_trades"}
    t = trades.copy()
    t["ticker"] = t.get("ticker", "").map(clean_ticker)
    t["side"] = t.get("side", "").astype(str).str.upper()
    t["date"] = date_col(t, "date")
    t["signal_date"] = date_col(t, "signal_date")
    buys = t[(t["ticker"] == ticker) & (t["side"] == "BUY")].dropna(subset=["date"]).sort_values("date")
    if buys.empty:
        return {"entry_status": "missing_buy"}
    row = buys.iloc[0]
    signal = row.get("signal_date")
    if pd.isna(signal):
        signal = row.get("date")
    return {
        "entry_status": "completed",
        "entry_date": pd.Timestamp(row["date"]),
        "entry_signal_date": pd.Timestamp(signal),
        "entry_price": safe_float(row.get("fill_price"), math.nan),
        "entry_reason": str(row.get("reason") or ""),
    }


def _nearest_entry_row(frame: pd.DataFrame, ticker: str, signal_date: pd.Timestamp) -> tuple[pd.Series | None, int | None]:
    if frame.empty or pd.isna(signal_date):
        return None, None
    exact = frame[(frame["ticker"] == ticker) & (frame["rebalance_date"] == signal_date)]
    if not exact.empty:
        return exact.iloc[0], 0
    before = frame[(frame["ticker"] == ticker) & (frame["rebalance_date"] <= signal_date)].copy()
    if before.empty:
        return None, None
    before["lag_days"] = (signal_date - before["rebalance_date"]).dt.days
    before = before[before["lag_days"].between(0, 7)].sort_values("lag_days")
    if before.empty:
        return None, None
    return before.iloc[0], int(before.iloc[0]["lag_days"])


def _rank_context(candidates: pd.DataFrame, ticker: str, signal_date: pd.Timestamp) -> dict[str, Any]:
    if candidates.empty or pd.isna(signal_date):
        return {"candidate_rank_status": "missing_candidate_book"}
    same = candidates[candidates["rebalance_date"] == signal_date].copy()
    if same.empty:
        return {"candidate_rank_status": "missing_candidate_date"}
    same = same.sort_values("score_numeric", ascending=False, na_position="last").reset_index(drop=True)
    same["candidate_rank"] = same.index + 1
    row = same[same["ticker"] == ticker]
    if row.empty:
        return {"candidate_rank_status": "ticker_not_in_candidate_date", "candidate_count": int(len(same))}
    rank = int(row.iloc[0]["candidate_rank"])
    count = int(len(same))
    pct = 1.0 - ((rank - 1) / max(count - 1, 1))
    return {"candidate_rank_status": "completed", "candidate_rank": rank, "candidate_count": count, "candidate_rank_percentile": float(pct)}


def _metric(row: pd.Series | None, names: tuple[str, ...]) -> float:
    if row is None:
        return 0.0
    for name in names:
        if name in row.index:
            return safe_float(row.get(name), 0.0)
    return 0.0


def _text(row: pd.Series | None, names: tuple[str, ...]) -> str:
    if row is None:
        return ""
    for name in names:
        if name in row.index and str(row.get(name) or "").strip():
            return str(row.get(name) or "").strip()
    return ""


def _signal_summary(candidate_row: pd.Series | None, target_row: pd.Series | None, rank: dict[str, Any]) -> dict[str, Any]:
    source = candidate_row if candidate_row is not None else target_row
    rs_3m = _metric(source, ("rs_benchmark_3m", "rs_spy_3m", "spy_relative_3m"))
    rs_6m = _metric(source, ("rs_benchmark_6m", "rs_spy_6m", "spy_relative_6m"))
    oneil = _metric(source, ("oneil_leadership_score",))
    scout = _metric(source, ("future_winner_scout_score", "portfolio_future_winner_engine_score"))
    industry = _metric(source, ("industry_group_strength_score",))
    dynamic = _metric(source, ("h6_dynamic_leader_score",))
    eps_revision = _metric(source, ("eps_revision_score", "revision_score"))
    actual_results = _metric(source, ("actual_results_score",))
    entry_quality = _metric(source, ("entry_quality_score", "breakout_setup_quality_score"))
    overheat = _metric(source, ("overheat_penalty", "stage2_overext_penalty"))
    price_ma200 = _metric(source, ("price_above_ma200",))
    rank_pct = safe_float(rank.get("candidate_rank_percentile"), 0.0)
    flags = {
        "top_decile_score": rank_pct >= 0.90,
        "positive_3m_rs": rs_3m > 0.0,
        "strong_3m_rs": rs_3m >= 0.10,
        "positive_6m_rs": rs_6m > 0.0,
        "above_ma200": price_ma200 >= 0.5,
        "oneil_leadership": oneil >= 0.50,
        "future_winner_scout": scout >= 0.70,
        "industry_strength": industry >= 0.30,
        "dynamic_leader": dynamic >= 0.50,
        "positive_revision": eps_revision >= 0.50,
        "actual_results": actual_results >= 0.75,
        "entry_quality": entry_quality >= 0.50,
        "not_overheated": overheat <= 0.20,
    }
    stack_count = int(sum(1 for value in flags.values() if bool(value)))
    return {
        "signal_source": "candidate" if candidate_row is not None else "target" if target_row is not None else "missing",
        "sector": _text(source, ("sector", "Sector")),
        "industry_group": _text(source, ("industry_group", "industry")),
        "primary_lane": _text(source, ("primary_lane", "portfolio_sleeve_label", "lane")),
        "leader_tier": _text(target_row, ("leader_tier",)) or _text(source, ("leader_tier",)),
        "score": _metric(source, ("score", "concentrated_score", "score_total")),
        "rs_benchmark_3m": rs_3m,
        "rs_benchmark_6m": rs_6m,
        "oneil_leadership_score": oneil,
        "future_winner_scout_score": scout,
        "industry_group_strength_score": industry,
        "h6_dynamic_leader_score": dynamic,
        "eps_revision_score": eps_revision,
        "actual_results_score": actual_results,
        "entry_quality_score": entry_quality,
        "overheat_penalty": overheat,
        "price_above_ma200": price_ma200,
        "entry_signal_stack_count": stack_count,
        "ex_ante_signal_flags": ";".join(sorted(k for k, v in flags.items() if v)),
        "skill_evidence_flag": stack_count >= 5,
    }


def analyze_portfolio(latest_run: Path, portfolio: str, top_n: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    winners, winner_summary = _winner_rows(latest_run, portfolio, top_n)
    trades = read_csv(latest_run / "broker_replay" / portfolio / "trades.csv")
    candidates = _candidate_book(latest_run)
    target = _target_book(latest_run, portfolio)
    rows: list[dict[str, Any]] = []
    for _, winner in winners.iterrows():
        ticker = clean_ticker(winner.get("ticker"))
        entry = _first_entry(trades, ticker)
        signal_date = entry.get("entry_signal_date")
        if not isinstance(signal_date, pd.Timestamp):
            signal_date = pd.NaT
        candidate_row, candidate_lag = _nearest_entry_row(candidates, ticker, signal_date)
        target_row, target_lag = _nearest_entry_row(target, ticker, signal_date)
        rank = _rank_context(candidates, ticker, signal_date)
        signal = _signal_summary(candidate_row, target_row, rank)
        rows.append(
            {
                "portfolio": portfolio,
                "ticker": ticker,
                "pnl_usd": safe_float(winner.get("pnl_usd"), 0.0),
                "positive_contribution_share": safe_float(winner.get("positive_contribution_share"), 0.0),
                "realized_pnl_usd": safe_float(winner.get("realized_pnl_usd"), 0.0),
                "unrealized_pnl_usd": safe_float(winner.get("unrealized_pnl_usd"), 0.0),
                "entry_status": entry.get("entry_status"),
                "entry_date": entry.get("entry_date").date().isoformat() if isinstance(entry.get("entry_date"), pd.Timestamp) else "",
                "entry_signal_date": signal_date.date().isoformat() if isinstance(signal_date, pd.Timestamp) and not pd.isna(signal_date) else "",
                "entry_price": safe_float(entry.get("entry_price"), math.nan),
                "entry_reason": entry.get("entry_reason", ""),
                "candidate_match_lag_days": candidate_lag,
                "target_match_lag_days": target_lag,
                "selected_in_target_at_entry": target_row is not None,
                "used_forward_return_in_ranking": False,
                "production_mutation_allowed": False,
                **rank,
                **signal,
            }
        )
    out = pd.DataFrame(rows)
    contribution_status = winner_summary.pop("status", "unknown")
    if out.empty:
        summary = {"status": "empty", "name_contribution_status": contribution_status, **winner_summary}
    else:
        summary = {
            **winner_summary,
            "status": "completed",
            "name_contribution_status": contribution_status,
            "winner_count": int(len(out)),
            "selected_at_entry_count": int(out["selected_in_target_at_entry"].astype(bool).sum()),
            "skill_evidence_count": int(out["skill_evidence_flag"].astype(bool).sum()),
            "avg_entry_signal_stack_count": float(pd.to_numeric(out["entry_signal_stack_count"], errors="coerce").mean()),
            "used_forward_return_in_ranking": False,
        }
    return out, summary


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Right-Tail Entry Signal Audit",
        "",
        "Research-only diagnostic. Realized PnL is used only to choose winners for audit.",
        "Entry quality is evaluated from candidate/target-book fields at the entry signal date.",
        "No forward return is used for ranking, selection, target books, cash policy, or live trading.",
        "",
    ]
    for portfolio, block in sorted((payload.get("portfolios") or {}).items()):
        lines.extend(
            [
                f"## {portfolio}",
                "",
                f"- status: `{block.get('status')}`",
                f"- winner_count: {block.get('winner_count', 0)}",
                f"- selected_at_entry_count: {block.get('selected_at_entry_count', 0)}",
                f"- skill_evidence_count: {block.get('skill_evidence_count', 0)}",
                f"- avg_entry_signal_stack_count: {safe_float(block.get('avg_entry_signal_stack_count'), 0.0):.2f}",
                f"- source: `{block.get('source', '')}`",
                "",
            ]
        )
    return "\n".join(lines)


def run(latest_run: Path, output_dir: Path, portfolios: tuple[str, ...] = PORTFOLIOS, top_n: int = 5) -> dict[str, Any]:
    latest_run = repo_path(latest_run)
    output_dir = repo_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "latest_run": str(latest_run),
        "research_only": True,
        "metric_context": "broker_ledger_next_close",
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "used_forward_return_in_ranking": False,
        "portfolios": {},
    }
    all_rows: list[pd.DataFrame] = []
    for portfolio in portfolios:
        rows, summary = analyze_portfolio(latest_run, portfolio, top_n)
        payload["portfolios"][portfolio] = summary
        portfolio_dir = output_dir / portfolio
        portfolio_dir.mkdir(parents=True, exist_ok=True)
        rows.to_csv(portfolio_dir / "winner_entry_signals.csv", index=False)
        write_json(portfolio_dir / "summary.json", summary)
        if not rows.empty:
            all_rows.append(rows)
    if all_rows:
        pd.concat(all_rows, ignore_index=True).to_csv(output_dir / "winner_entry_signals.csv", index=False)
    else:
        pd.DataFrame().to_csv(output_dir / "winner_entry_signals.csv", index=False)
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/right_tail_entry_signal_audit")
    parser.add_argument("--portfolios", nargs="+", default=list(PORTFOLIOS))
    parser.add_argument("--top-n", type=int, default=5)
    args = parser.parse_args(argv)
    payload = run(repo_path(args.latest_run), repo_path(args.output_dir), tuple(args.portfolios), args.top_n)
    for portfolio, block in payload.get("portfolios", {}).items():
        print(
            f"{portfolio}: status={block.get('status')} winners={block.get('winner_count', 0)} "
            f"skill_evidence={block.get('skill_evidence_count', 0)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

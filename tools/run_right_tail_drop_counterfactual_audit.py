#!/usr/bin/env python3
"""Audit post-drop returns for right-tail candidates.

Research-only diagnostic. Target-book drop events are identified from monthly
target books. Forward returns are computed only after the drop event and are
written as audit labels; they are never used for ranking, target construction,
cash policy, or live trading.
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
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import load_price_series, price_on_or_after  # noqa: E402


SCHEMA_VERSION = "right-tail-drop-counterfactual-audit-v1"
PORTFOLIOS = ("main", "concentrated")
CASH_TICKERS = {"", "CASH", "__CASH__", "BIL", "SGOV"}
HORIZONS = (21, 63, 126)
BENCHMARKS = ("SPY", "QQQ", "SMH", "SOXX")


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def clean_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


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


def date_col(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(pd.NaT, index=df.index)
    return pd.to_datetime(df[column], errors="coerce").dt.tz_localize(None)


def target_book_path(latest_run: Path, portfolio: str) -> Path:
    for path in (
        latest_run / "alphaops_vnext" / f"official_{portfolio}_target_book.csv",
        latest_run / "reports" / f"operating_{portfolio}_target_book.csv",
    ):
        if path.exists():
            return path
    return latest_run / "alphaops_vnext" / f"official_{portfolio}_target_book.csv"


def normalize_target_book(path: Path) -> pd.DataFrame:
    raw = read_csv(path)
    if raw.empty:
        return pd.DataFrame(columns=["rebalance_date", "ticker", "weight"])
    out = raw.copy()
    out["rebalance_date"] = date_col(out, "rebalance_date")
    out["ticker"] = out.get("ticker", "").map(clean_ticker)
    out["weight"] = pd.to_numeric(out.get("weight", out.get("target_weight", 0.0)), errors="coerce").fillna(0.0)
    out = out.dropna(subset=["rebalance_date"])
    out = out[~out["ticker"].isin(CASH_TICKERS)].copy()
    out = out[out["weight"] > 0].copy()
    return out.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)


def candidate_book(latest_run: Path) -> pd.DataFrame:
    raw = read_csv(latest_run / "reports" / "candidate_replay_book.csv")
    if raw.empty:
        return pd.DataFrame()
    out = raw.copy()
    out["rebalance_date"] = date_col(out, "rebalance_date")
    out["ticker"] = out.get("ticker", "").map(clean_ticker)
    out["score_numeric"] = pd.to_numeric(out.get("score"), errors="coerce")
    return out.dropna(subset=["rebalance_date"]).reset_index(drop=True)


def drop_events(target: pd.DataFrame, portfolio: str) -> list[dict[str, Any]]:
    if target.empty:
        return []
    dates = sorted(pd.Timestamp(x).normalize() for x in target["rebalance_date"].dropna().unique())
    by_date: dict[pd.Timestamp, set[str]] = {}
    for dt in dates:
        rows = target[target["rebalance_date"].eq(dt)]
        by_date[dt] = {clean_ticker(x) for x in rows["ticker"] if clean_ticker(x) not in CASH_TICKERS}
    events: list[dict[str, Any]] = []
    previous: set[str] = set()
    previous_date: pd.Timestamp | None = None
    for dt in dates:
        current = by_date.get(dt, set())
        if previous_date is not None:
            for ticker in sorted(previous - current):
                events.append(
                    {
                        "portfolio": portfolio,
                        "ticker": ticker,
                        "drop_date": dt.date().isoformat(),
                        "previous_rebalance_date": previous_date.date().isoformat(),
                    }
                )
        previous = current
        previous_date = dt
    return events


def rank_context(candidates: pd.DataFrame, ticker: str, drop_date: pd.Timestamp) -> tuple[pd.Series | None, dict[str, Any]]:
    if candidates.empty:
        return None, {"candidate_rank_status": "missing_candidate_book"}
    same = candidates[candidates["rebalance_date"].eq(drop_date)].copy()
    if same.empty:
        return None, {"candidate_rank_status": "missing_candidate_date"}
    same = same.sort_values("score_numeric", ascending=False, na_position="last").reset_index(drop=True)
    same["candidate_rank"] = same.index + 1
    row = same[same["ticker"].eq(ticker)]
    if row.empty:
        return None, {"candidate_rank_status": "ticker_not_in_candidate_date", "candidate_count": int(len(same))}
    rank = int(row.iloc[0]["candidate_rank"])
    count = int(len(same))
    pct = 1.0 - ((rank - 1) / max(count - 1, 1))
    return row.iloc[0], {
        "candidate_rank_status": "completed",
        "candidate_rank": rank,
        "candidate_count": count,
        "candidate_rank_percentile": float(pct),
    }


def metric(row: pd.Series | None, names: tuple[str, ...]) -> float:
    if row is None:
        return 0.0
    for name in names:
        if name in row.index:
            return safe_float(row.get(name), 0.0)
    return 0.0


def signal_summary(candidate_row: pd.Series | None, rank: dict[str, Any]) -> dict[str, Any]:
    rs_3m = metric(candidate_row, ("rs_benchmark_3m", "rs_spy_3m", "spy_relative_3m"))
    rs_6m = metric(candidate_row, ("rs_benchmark_6m", "rs_spy_6m", "spy_relative_6m"))
    overheat = metric(candidate_row, ("overheat_penalty", "stage2_overext_penalty"))
    rank_pct = safe_float(rank.get("candidate_rank_percentile"), 0.0)
    flags = {
        "top_decile_score": rank_pct >= 0.90,
        "rank80": rank_pct >= 0.80,
        "positive_3m_rs": rs_3m > 0.0,
        "strong_3m_rs": rs_3m >= 0.10,
        "positive_6m_rs": rs_6m > 0.0,
        "above_ma200": metric(candidate_row, ("price_above_ma200",)) >= 0.5,
        "oneil_leadership": metric(candidate_row, ("oneil_leadership_score",)) >= 0.50,
        "future_winner_scout": metric(candidate_row, ("future_winner_scout_score", "portfolio_future_winner_engine_score")) >= 0.70,
        "industry_strength": metric(candidate_row, ("industry_group_strength_score",)) >= 0.30,
        "dynamic_leader": metric(candidate_row, ("h6_dynamic_leader_score",)) >= 0.50,
        "positive_revision": metric(candidate_row, ("eps_revision_score", "revision_score")) >= 0.50,
        "actual_results": metric(candidate_row, ("actual_results_score",)) >= 0.75,
        "entry_quality": metric(candidate_row, ("entry_quality_score", "breakout_setup_quality_score")) >= 0.50,
        "not_overheated": overheat <= 0.20,
    }
    active = sorted(k for k, v in flags.items() if bool(v))
    stack = int(len(active))
    return {
        "drop_signal_stack_count": stack,
        "drop_skill_evidence_flag": bool(stack >= 5),
        "drop_ex_ante_signal_flags": ";".join(active),
        "rs_benchmark_3m": rs_3m,
        "rs_benchmark_6m": rs_6m,
        "overheat_penalty": overheat,
    }


def forward_return_from_price(px: pd.DataFrame, start_date: pd.Timestamp, horizon: int) -> dict[str, Any]:
    if px.empty:
        return {f"fwd_{horizon}d_status": "missing_price"}
    fill_dt, fill_px = price_on_or_after(px, start_date + pd.Timedelta(days=1), "close")
    if fill_dt is None or fill_px is None:
        return {f"fwd_{horizon}d_status": "missing_start_price"}
    idx = pd.DatetimeIndex(px.index)
    start_pos = int(idx.searchsorted(pd.Timestamp(fill_dt), side="left"))
    end_pos = start_pos + int(horizon)
    if end_pos >= len(idx):
        return {
            f"fwd_{horizon}d_status": "insufficient_future_price",
            "counterfactual_start_date": pd.Timestamp(fill_dt).date().isoformat(),
        }
    end_dt = pd.Timestamp(idx[end_pos])
    end_px = safe_float(px["close"].iloc[end_pos], math.nan)
    if not math.isfinite(end_px) or end_px <= 0:
        return {
            f"fwd_{horizon}d_status": "invalid_end_price",
            "counterfactual_start_date": pd.Timestamp(fill_dt).date().isoformat(),
        }
    return {
        f"fwd_{horizon}d_status": "completed",
        "counterfactual_start_date": pd.Timestamp(fill_dt).date().isoformat(),
        f"fwd_{horizon}d_end_date": end_dt.date().isoformat(),
        f"fwd_{horizon}d_return": float(end_px / float(fill_px) - 1.0),
    }


def price_return_block(price_cache: Path, ticker: str, drop_date: pd.Timestamp, benchmark_returns: dict[str, dict[int, float]]) -> dict[str, Any]:
    px = load_price_series(price_cache, ticker)
    out: dict[str, Any] = {}
    for horizon in HORIZONS:
        result = forward_return_from_price(px, drop_date, horizon)
        out.update(result)
        ticker_ret = result.get(f"fwd_{horizon}d_return")
        if isinstance(ticker_ret, float) and math.isfinite(ticker_ret):
            for bench in BENCHMARKS:
                bench_ret = benchmark_returns.get(bench, {}).get(horizon)
                if bench_ret is not None and math.isfinite(float(bench_ret)):
                    out[f"fwd_{horizon}d_excess_{bench.lower()}"] = float(ticker_ret) - float(bench_ret)
    return out


def benchmark_return_cache(price_cache: Path, drop_dates: list[pd.Timestamp]) -> dict[str, dict[str, dict[int, float]]]:
    out: dict[str, dict[str, dict[int, float]]] = {}
    for bench in BENCHMARKS:
        px = load_price_series(price_cache, bench)
        per_date: dict[str, dict[int, float]] = {}
        for dt in sorted(set(pd.Timestamp(x).normalize() for x in drop_dates)):
            per_horizon: dict[int, float] = {}
            for horizon in HORIZONS:
                result = forward_return_from_price(px, dt, horizon)
                value = result.get(f"fwd_{horizon}d_return")
                if isinstance(value, float) and math.isfinite(value):
                    per_horizon[horizon] = float(value)
            per_date[dt.date().isoformat()] = per_horizon
        out[bench] = per_date
    return out


def analyze_portfolio(latest_run: Path, price_cache: Path, candidates: pd.DataFrame, portfolio: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    target = normalize_target_book(target_book_path(latest_run, portfolio))
    events = drop_events(target, portfolio)
    drop_dates = [pd.Timestamp(event["drop_date"]) for event in events]
    bench_cache = benchmark_return_cache(price_cache, drop_dates)
    rows: list[dict[str, Any]] = []
    for event in events:
        ticker = clean_ticker(event["ticker"])
        drop_dt = pd.Timestamp(event["drop_date"]).normalize()
        candidate_row, rank = rank_context(candidates, ticker, drop_dt)
        signal = signal_summary(candidate_row, rank)
        benchmark_returns = {bench: bench_cache.get(bench, {}).get(drop_dt.date().isoformat(), {}) for bench in BENCHMARKS}
        returns = price_return_block(price_cache, ticker, drop_dt, benchmark_returns)
        row = {
            **event,
            **rank,
            **signal,
            **returns,
            "used_forward_return_in_ranking": False,
            "production_mutation_allowed": False,
        }
        row["missed_rebound_63d_spy_flag"] = bool(
            row.get("drop_skill_evidence_flag")
            and safe_float(row.get("fwd_63d_excess_spy"), 0.0) > 0.0
        )
        row["missed_rebound_126d_spy_flag"] = bool(
            row.get("drop_skill_evidence_flag")
            and safe_float(row.get("fwd_126d_excess_spy"), 0.0) > 0.0
        )
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, {"status": "empty", "drop_event_count": 0, "target_book": str(target_book_path(latest_run, portfolio))}
    skill = frame[frame["drop_skill_evidence_flag"].astype(bool)].copy()
    rank_pct = pd.to_numeric(frame.get("candidate_rank_percentile"), errors="coerce").fillna(0.0)
    stack = pd.to_numeric(frame.get("drop_signal_stack_count"), errors="coerce").fillna(0.0)
    high_signal_mask = frame["drop_skill_evidence_flag"].astype(bool) & rank_pct.ge(0.80) & stack.ge(7)
    high_signal = frame[high_signal_mask].copy()
    summary = {
        "status": "completed",
        "target_book": str(target_book_path(latest_run, portfolio)),
        "drop_event_count": int(len(frame)),
        "skill_signal_drop_count": int(len(skill)),
        "rank80_drop_count": int(rank_pct.ge(0.80).sum()),
        "high_signal_drop_count": int(len(high_signal)),
        "missed_rebound_63d_spy_count": int(frame["missed_rebound_63d_spy_flag"].astype(bool).sum()),
        "missed_rebound_126d_spy_count": int(frame["missed_rebound_126d_spy_flag"].astype(bool).sum()),
        "high_signal_missed_rebound_63d_spy_count": int((high_signal.get("missed_rebound_63d_spy_flag", pd.Series(dtype=bool)).astype(bool)).sum()) if not high_signal.empty else 0,
        "high_signal_missed_rebound_126d_spy_count": int((high_signal.get("missed_rebound_126d_spy_flag", pd.Series(dtype=bool)).astype(bool)).sum()) if not high_signal.empty else 0,
        "used_forward_return_in_ranking": False,
    }
    for horizon in HORIZONS:
        col = f"fwd_{horizon}d_excess_spy"
        if col in skill.columns:
            summary[f"avg_skill_drop_{col}"] = float(pd.to_numeric(skill[col], errors="coerce").mean())
        if col in high_signal.columns:
            summary[f"avg_high_signal_drop_{col}"] = float(pd.to_numeric(high_signal[col], errors="coerce").mean())
    return frame, summary


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Right-Tail Drop Counterfactual Audit",
        "",
        "Research-only diagnostic. Drop events come from target books; forward returns are audit labels only.",
        "No forward return is used for ranking, target construction, cash policy, production mutation, or live trading.",
        "",
    ]
    for portfolio, block in sorted((payload.get("portfolios") or {}).items()):
        lines.extend(
            [
                f"## {portfolio}",
                "",
                f"- status: `{block.get('status')}`",
                f"- drop_event_count: {block.get('drop_event_count', 0)}",
                f"- skill_signal_drop_count: {block.get('skill_signal_drop_count', 0)}",
                f"- rank80_drop_count: {block.get('rank80_drop_count', 0)}",
                f"- high_signal_drop_count: {block.get('high_signal_drop_count', 0)}",
                f"- missed_rebound_63d_spy_count: {block.get('missed_rebound_63d_spy_count', 0)}",
                f"- missed_rebound_126d_spy_count: {block.get('missed_rebound_126d_spy_count', 0)}",
                f"- high_signal_missed_rebound_63d_spy_count: {block.get('high_signal_missed_rebound_63d_spy_count', 0)}",
                f"- high_signal_missed_rebound_126d_spy_count: {block.get('high_signal_missed_rebound_126d_spy_count', 0)}",
                f"- avg_skill_drop_fwd_63d_excess_spy: {safe_float(block.get('avg_skill_drop_fwd_63d_excess_spy'), 0.0):.4f}",
                f"- avg_skill_drop_fwd_126d_excess_spy: {safe_float(block.get('avg_skill_drop_fwd_126d_excess_spy'), 0.0):.4f}",
                f"- avg_high_signal_drop_fwd_63d_excess_spy: {safe_float(block.get('avg_high_signal_drop_fwd_63d_excess_spy'), 0.0):.4f}",
                f"- avg_high_signal_drop_fwd_126d_excess_spy: {safe_float(block.get('avg_high_signal_drop_fwd_126d_excess_spy'), 0.0):.4f}",
                "",
            ]
        )
    return "\n".join(lines)


def run(latest_run: Path, price_cache: Path, output_dir: Path, portfolios: tuple[str, ...] = PORTFOLIOS) -> dict[str, Any]:
    latest_run = repo_path(latest_run)
    price_cache = repo_path(price_cache)
    output_dir = repo_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = candidate_book(latest_run)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "latest_run": str(latest_run),
        "price_cache": str(price_cache),
        "research_only": True,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "used_forward_return_in_ranking": False,
        "portfolios": {},
    }
    all_rows: list[pd.DataFrame] = []
    for portfolio in portfolios:
        rows, summary = analyze_portfolio(latest_run, price_cache, candidates, portfolio)
        payload["portfolios"][portfolio] = summary
        portfolio_dir = output_dir / portfolio
        portfolio_dir.mkdir(parents=True, exist_ok=True)
        rows.to_csv(portfolio_dir / "drop_counterfactuals.csv", index=False)
        write_json(portfolio_dir / "summary.json", summary)
        if not rows.empty:
            all_rows.append(rows)
    if all_rows:
        pd.concat(all_rows, ignore_index=True).to_csv(output_dir / "drop_counterfactuals.csv", index=False)
    else:
        pd.DataFrame().to_csv(output_dir / "drop_counterfactuals.csv", index=False)
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/right_tail_drop_counterfactual_audit")
    parser.add_argument("--portfolios", nargs="+", default=list(PORTFOLIOS))
    args = parser.parse_args(argv)
    payload = run(repo_path(args.latest_run), repo_path(args.price_cache), repo_path(args.output_dir), tuple(args.portfolios))
    for portfolio, block in payload.get("portfolios", {}).items():
        print(
            f"{portfolio}: status={block.get('status')} drops={block.get('drop_event_count', 0)} "
            f"skill_drops={block.get('skill_signal_drop_count', 0)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

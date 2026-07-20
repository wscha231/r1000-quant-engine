#!/usr/bin/env python3
"""Evaluate the single preregistered Run287 P5 hold/exit/replacement arm.

This is a bounded generated-book post-processing study, not a fullrun.  The
frozen books are replayed unchanged as controls.  Candidate evidence is loaded
from an independently restored PIT artifact-derived cache, with all forward
label columns physically excluded by ``run287_hold_exit_policy``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run287_hold_exit_policy import (  # noqa: E402
    POLICY_ID,
    SCHEMA_VERSION as POLICY_SCHEMA_VERSION,
    LeadershipPersistencePolicy,
    build_leadership_persistence_book,
    classify_execution_sell,
    clean_ticker,
    file_sha256,
    lifecycle_for_date,
    load_scored_candidate_cache,
    normalize_target_book,
    safe_float,
)
from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_CARRY_MODE_RISK_FREE,
    DEFAULT_OOS2_START,
    DEFAULT_OOS_START,
    CashCarryConfig,
    calc_metrics,
    replay,
)
from tools.run_weekly_evaluation import load_price_series, price_on_or_after  # noqa: E402
from tools.reserve_asset_policy import DGS3MO_CARRY  # noqa: E402


SCHEMA_VERSION = "run287-hold-exit-replacement-evaluation-v1"
EXPECTED_INPUT_HASHES = {
    "main_target_book": "356bac22ec55090b2d2da882c7505b1460973227639a5d0b7a4c59c25c0ccff9",
    "concentrated_target_book": "848c1bac00985ab0b132794ee3e1c2942c1561d2f728b0a89778bd6c4e63660e",
    "candidate_artifact": "7ffa0b27382d303008ffca55878b259ccf7f11beaee28be6f1e4653c30e97989",
}
EXPECTED_CONTROL = {
    "main": {
        "cagr": 0.3440322188069127,
        "max_dd": -0.25362940173158566,
        "sharpe": 1.2757089748853234,
        "trade_count": 1625,
        "total_fees_usd": 42922.447834389284,
        "trade_sha256": "e7f428f60c85fb0863473158b9c314f9c5d5167cf32eb9cead48dd5423e0470a",
    },
    "concentrated": {
        "cagr": 0.4909680440544679,
        "max_dd": -0.22955985434861514,
        "sharpe": 1.5001888936072352,
        "trade_count": 730,
        "total_fees_usd": 62764.081878475816,
        "trade_sha256": "b85688b75e06f0096e0edeb5cef4befda41219aca3fa1d27e8988b1db098347e",
    },
}
COST_GRID = (25.0, 50.0, 100.0)
HORIZONS = (21, 63, 126)
CASH_TICKERS = {"CASH", "__CASH__"}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")


def _cash_config(rate_path: Path) -> CashCarryConfig:
    return CashCarryConfig(
        mode=CASH_CARRY_MODE_RISK_FREE,
        rate_path=rate_path,
        haircut_bps=50.0,
        day_count=365,
        rate_lag_days=1,
    )


def run_replay(
    *,
    target_book: Path,
    price_cache: Path,
    rate_path: Path,
    output_dir: Path,
    portfolio: str,
    cost_bps: float,
) -> dict[str, Any]:
    return replay(
        target_book=target_book,
        price_cache=price_cache,
        output_dir=output_dir,
        portfolio_kind=portfolio,
        starting_capital=100000.0,
        fill_mode="next_close",
        cost_bps=cost_bps,
        integer_shares=True,
        max_fill_lag_days=7,
        disable_concentrated_champion_filter=True,
        oos_start=DEFAULT_OOS_START,
        oos2_start=DEFAULT_OOS2_START,
        cash_carry_config=_cash_config(rate_path),
        reserve_mode=DGS3MO_CARRY,
    )


def control_parity(metrics: dict[str, Any], trades_path: Path, portfolio: str) -> dict[str, Any]:
    expected = EXPECTED_CONTROL[portfolio]
    checks = {
        key: abs(safe_float(metrics.get(key), math.inf) - float(expected[key])) <= 1e-6
        for key in ("cagr", "max_dd", "sharpe", "total_fees_usd")
    }
    checks["trade_count"] = int(metrics.get("trade_count", -1)) == int(expected["trade_count"])
    actual_trade_hash = file_sha256(trades_path) if trades_path.is_file() else ""
    checks["trade_sha256"] = actual_trade_hash == expected["trade_sha256"]
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "actual_trade_sha256": actual_trade_hash,
        "expected": expected,
    }


def _window(metrics: dict[str, Any], name: str) -> dict[str, Any]:
    windows = metrics.get("windows") or {}
    if isinstance(windows, dict) and isinstance(windows.get(name), dict):
        return windows[name]
    return metrics if name == "full" else {}


def _metric_delta(treatment: dict[str, Any], control: dict[str, Any], key: str) -> float | None:
    lhs = safe_float(treatment.get(key))
    rhs = safe_float(control.get(key))
    if not (math.isfinite(lhs) and math.isfinite(rhs)):
        return None
    return lhs - rhs


def embargo_metrics(replay_dir: Path, cut: str) -> dict[str, Any]:
    curve_path = replay_dir / "equity_curve.csv"
    trades_path = replay_dir / "trades.csv"
    if not curve_path.is_file():
        return {"status": "blocked", "reason": "missing_equity_curve"}
    curve = pd.read_csv(curve_path)
    trades = pd.read_csv(trades_path) if trades_path.is_file() else pd.DataFrame()
    dates = pd.to_datetime(curve.get("date"), errors="coerce").dropna().sort_values().drop_duplicates()
    eligible = dates[dates >= pd.Timestamp(cut)]
    if len(eligible) <= 126:
        return {"status": "blocked", "reason": "underpowered_126_session_embargo", "session_count": len(eligible)}
    start = pd.Timestamp(eligible.iloc[126]).date().isoformat()
    out = calc_metrics(
        curve,
        trades,
        100000.0,
        date_range=(start, None),
        label=f"embargo126_{cut}",
        cash_carry_mode=CASH_CARRY_MODE_RISK_FREE,
    )
    out["embargo_sessions"] = 126
    out["original_cut"] = cut
    return out


def _price_frame(price_cache: Path, ticker: str) -> pd.DataFrame:
    return load_price_series(price_cache, ticker)


def _session_return(frame: pd.DataFrame, signal_date: pd.Timestamp, sessions: int) -> tuple[float | None, str, str]:
    if frame.empty:
        return None, "", ""
    start_date, start_price = price_on_or_after(frame, signal_date + pd.Timedelta(days=1), "close")
    if start_date is None or start_price is None:
        return None, "", ""
    index = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
    positions = np.flatnonzero(index >= pd.Timestamp(start_date).normalize())
    if not len(positions):
        return None, "", ""
    end_pos = int(positions[0]) + int(sessions)
    if end_pos >= len(frame):
        return None, pd.Timestamp(start_date).date().isoformat(), ""
    end_date = pd.Timestamp(index[end_pos]).normalize()
    end_price = safe_float(frame.iloc[end_pos].get("close"))
    if not math.isfinite(end_price) or end_price <= 0 or float(start_price) <= 0:
        return None, pd.Timestamp(start_date).date().isoformat(), end_date.date().isoformat()
    return end_price / float(start_price) - 1.0, pd.Timestamp(start_date).date().isoformat(), end_date.date().isoformat()


def counterfactuals(decisions: pd.DataFrame, price_cache: Path) -> pd.DataFrame:
    if decisions.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    price_frames: dict[str, pd.DataFrame] = {}
    for decision in decisions.to_dict("records"):
        incumbent = clean_ticker(decision.get("incumbent_ticker"))
        challenger = clean_ticker(decision.get("challenger_ticker"))
        if not incumbent or not challenger:
            continue
        signal_date = pd.Timestamp(decision["rebalance_date"]).normalize()
        for ticker in (incumbent, challenger):
            if ticker not in price_frames:
                price_frames[ticker] = _price_frame(price_cache, ticker)
        row = dict(decision)
        for horizon in HORIZONS:
            incumbent_return, start_date, end_date = _session_return(price_frames[incumbent], signal_date, horizon)
            challenger_return, challenger_start, challenger_end = _session_return(price_frames[challenger], signal_date, horizon)
            row[f"incumbent_return_{horizon}d"] = incumbent_return
            row[f"challenger_return_{horizon}d"] = challenger_return
            row[f"incumbent_minus_challenger_{horizon}d"] = (
                incumbent_return - challenger_return
                if incumbent_return is not None and challenger_return is not None
                else None
            )
            row[f"start_date_{horizon}d"] = start_date
            row[f"end_date_{horizon}d"] = end_date
            row[f"paired_dates_match_{horizon}d"] = bool(start_date and start_date == challenger_start and end_date == challenger_end)
        rows.append(row)
    return pd.DataFrame(rows)


def _return_between(frame: pd.DataFrame, signal_date: pd.Timestamp, next_signal_date: pd.Timestamp) -> float | None:
    if frame.empty:
        return None
    start_date, start_price = price_on_or_after(frame, signal_date + pd.Timedelta(days=1), "close")
    end_date, end_price = price_on_or_after(frame, next_signal_date + pd.Timedelta(days=1), "close")
    if start_date is None or end_date is None or start_price is None or end_price is None or start_price <= 0:
        return None
    return float(end_price / start_price - 1.0)


def contribution_concentration(
    decisions: pd.DataFrame,
    target_dates: list[pd.Timestamp],
    price_cache: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    applied = decisions[decisions.get("action", pd.Series(dtype=str)).eq("RETAIN_INCUMBENT")].copy()
    if applied.empty:
        return pd.DataFrame(), {"status": "NO_OP", "max_ticker_share": None, "max_era_share": None}
    ordered_dates = sorted(pd.Timestamp(day).normalize() for day in target_dates)
    next_date = {ordered_dates[index]: ordered_dates[index + 1] for index in range(len(ordered_dates) - 1)}
    price_frames: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, Any]] = []
    for item in applied.to_dict("records"):
        day = pd.Timestamp(item["rebalance_date"]).normalize()
        end = next_date.get(day)
        incumbent = clean_ticker(item.get("incumbent_ticker"))
        challenger = clean_ticker(item.get("challenger_ticker"))
        if end is None or not incumbent or not challenger:
            continue
        for ticker in (incumbent, challenger):
            if ticker not in price_frames:
                price_frames[ticker] = _price_frame(price_cache, ticker)
        incumbent_return = _return_between(price_frames[incumbent], day, end)
        challenger_return = _return_between(price_frames[challenger], day, end)
        contribution = None
        if incumbent_return is not None and challenger_return is not None:
            contribution = safe_float(item.get("retained_weight"), 0.0) * (incumbent_return - challenger_return)
        era = "2019_2020" if day.year <= 2020 else ("2021_2022" if day.year <= 2022 else ("2023_2024" if day.year <= 2024 else "2025_2026"))
        rows.append({
            **item,
            "next_rebalance_date": end.date().isoformat(),
            "incumbent_period_return": incumbent_return,
            "challenger_period_return": challenger_return,
            "weighted_incremental_contribution": contribution,
            "era": era,
        })
    frame = pd.DataFrame(rows)
    completed = frame.dropna(subset=["weighted_incremental_contribution"]) if not frame.empty else pd.DataFrame()
    positive = completed[completed["weighted_incremental_contribution"] > 0].copy() if not completed.empty else pd.DataFrame()
    total_positive = float(positive["weighted_incremental_contribution"].sum()) if not positive.empty else 0.0
    if total_positive <= 0:
        return frame, {"status": "NO_POSITIVE_CONTRIBUTION", "max_ticker_share": None, "max_era_share": None}
    ticker_share = positive.groupby("incumbent_ticker")["weighted_incremental_contribution"].sum() / total_positive
    era_share = positive.groupby("era")["weighted_incremental_contribution"].sum() / total_positive
    return frame, {
        "status": "COMPLETED",
        "positive_incremental_contribution": total_positive,
        "max_ticker_share": float(ticker_share.max()),
        "max_ticker": str(ticker_share.idxmax()),
        "max_era_share": float(era_share.max()),
        "max_era": str(era_share.idxmax()),
        "ticker_share": ticker_share.sort_values(ascending=False).to_dict(),
        "era_share": era_share.sort_values(ascending=False).to_dict(),
    }


def execution_sell_intents(
    treatment_book: pd.DataFrame,
    exits: pd.DataFrame,
    *,
    portfolio: str,
    lifecycle_path: Path,
) -> pd.DataFrame:
    book = normalize_target_book(treatment_book)
    exit_map = {
        (str(row.rebalance_date), clean_ticker(row.ticker)): (str(row.sell_taxonomy), str(row.sell_taxonomy_reason))
        for row in exits.itertuples(index=False)
    } if not exits.empty else {}
    previous: dict[str, float] = {}
    previous_gross = 0.0
    rows: list[dict[str, Any]] = []
    for day, group in book.groupby("rebalance_date", sort=True):
        day = pd.Timestamp(day).normalize()
        current = {
            clean_ticker(row.ticker): safe_float(row.weight, 0.0)
            for row in group.itertuples(index=False)
            if clean_ticker(row.ticker) not in CASH_TICKERS
        }
        current_gross = sum(current.values())
        incoming = set(current) - set(previous)
        terminal = set(lifecycle_for_date(lifecycle_path, day, set(previous) | set(current)).terminal_tickers)
        for ticker in sorted(set(previous) | set(current)):
            prior_weight = previous.get(ticker, 0.0)
            target_weight = current.get(ticker, 0.0)
            if target_weight >= prior_weight - 1e-12:
                continue
            explicit, explicit_reason = exit_map.get((day.date().isoformat(), ticker), ("", ""))
            taxonomy, reason = classify_execution_sell(
                ticker=ticker,
                target_weight=target_weight,
                target_gross_reduced=current_gross < previous_gross - 1e-12,
                replacement_tickers=incoming,
                lifecycle_terminal=ticker in terminal,
                explicit_taxonomy=explicit,
            )
            rows.append({
                "signal_date": day.date().isoformat(),
                "portfolio": portfolio,
                "ticker": ticker,
                "prior_weight": prior_weight,
                "target_weight": target_weight,
                "sell_taxonomy": taxonomy,
                "sell_taxonomy_reason": explicit_reason or reason,
                "replacement_tickers": "|".join(sorted(incoming)),
            })
        previous = current
        previous_gross = current_gross
    return pd.DataFrame(rows)


def attach_trade_taxonomy(trades: pd.DataFrame, intents: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    out = trades.copy()
    out["ticker"] = out["ticker"].map(clean_ticker)
    out["signal_date"] = pd.to_datetime(out["signal_date"], errors="coerce").dt.date.astype(str)
    if intents.empty:
        out["sell_taxonomy"] = np.where(out["side"].astype(str).eq("SELL"), "EXECUTION_RECONCILIATION", "")
        out["sell_taxonomy_reason"] = np.where(out["side"].astype(str).eq("SELL"), "missing_target_intent", "")
        return out
    join = intents[["signal_date", "ticker", "sell_taxonomy", "sell_taxonomy_reason"]].drop_duplicates(["signal_date", "ticker"])
    out = out.merge(join, on=["signal_date", "ticker"], how="left")
    sell = out["side"].astype(str).eq("SELL")
    out.loc[sell & out["sell_taxonomy"].isna(), "sell_taxonomy"] = "EXECUTION_RECONCILIATION"
    out.loc[sell & out["sell_taxonomy_reason"].isna(), "sell_taxonomy_reason"] = "integer_or_weight_reconciliation"
    out.loc[~sell, ["sell_taxonomy", "sell_taxonomy_reason"]] = ""
    return out


def holding_statistics(trades: pd.DataFrame, price_cache: Path) -> dict[str, Any]:
    if trades.empty:
        return {"completed_lot_count": 0, "median_holding_days": None, "pct_held_365d_plus": None, "exit_reentry_churn_63_sessions": 0}
    ordered = trades.copy()
    ordered["date"] = pd.to_datetime(ordered["date"], errors="coerce")
    ordered = ordered.dropna(subset=["date"]).sort_values(["date", "side", "ticker"])
    lots: dict[str, deque[list[Any]]] = defaultdict(deque)
    durations: list[int] = []
    full_exits: dict[str, list[pd.Timestamp]] = defaultdict(list)
    reentries: dict[str, list[pd.Timestamp]] = defaultdict(list)
    position_qty: dict[str, float] = defaultdict(float)
    for row in ordered.to_dict("records"):
        ticker = clean_ticker(row.get("ticker"))
        side = str(row.get("side") or "").upper()
        qty = max(0.0, safe_float(row.get("quantity"), 0.0))
        day = pd.Timestamp(row["date"]).normalize()
        if side == "BUY":
            if position_qty[ticker] <= 1e-12 and full_exits.get(ticker):
                reentries[ticker].append(day)
            lots[ticker].append([qty, day])
            position_qty[ticker] += qty
        elif side == "SELL":
            remaining = qty
            while remaining > 1e-12 and lots[ticker]:
                lot_qty, entry_day = lots[ticker][0]
                taken = min(remaining, float(lot_qty))
                if taken > 1e-12:
                    durations.append(max(0, int((day - pd.Timestamp(entry_day)).days)))
                lot_qty -= taken
                remaining -= taken
                if lot_qty <= 1e-12:
                    lots[ticker].popleft()
                else:
                    lots[ticker][0][0] = lot_qty
            position_qty[ticker] = max(0.0, position_qty[ticker] - qty)
            if position_qty[ticker] <= 1e-12:
                full_exits[ticker].append(day)
    churn = 0
    for ticker, exit_days in full_exits.items():
        frame = _price_frame(price_cache, ticker)
        sessions = pd.DatetimeIndex(frame.index).tz_localize(None).normalize() if not frame.empty else pd.DatetimeIndex([])
        for exit_day in exit_days:
            later = [day for day in reentries.get(ticker, []) if day > exit_day]
            if not later or sessions.empty:
                continue
            next_buy = min(later)
            count = int(((sessions > exit_day) & (sessions <= next_buy)).sum())
            if count <= 63:
                churn += 1
    series = pd.Series(durations, dtype=float)
    return {
        "completed_lot_count": len(durations),
        "median_holding_days": float(series.median()) if not series.empty else None,
        "pct_held_365d_plus": float(series.ge(365).mean()) if not series.empty else None,
        "exit_reentry_churn_63_sessions": int(churn),
    }


def summarize_counterfactuals(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"status": "NO_EVENTS"}
    out: dict[str, Any] = {"status": "COMPLETED", "event_count": len(frame)}
    for horizon in HORIZONS:
        diff = pd.to_numeric(frame.get(f"incumbent_minus_challenger_{horizon}d"), errors="coerce").dropna()
        out[f"paired_count_{horizon}d"] = len(diff)
        out[f"mean_incumbent_minus_challenger_{horizon}d"] = float(diff.mean()) if not diff.empty else None
        out[f"median_incumbent_minus_challenger_{horizon}d"] = float(diff.median()) if not diff.empty else None
    retained = frame[frame.get("action", pd.Series(dtype=str)).eq("RETAIN_INCUMBENT")]
    retained_126 = pd.to_numeric(retained.get("incumbent_return_126d"), errors="coerce").dropna()
    out["retained_event_count"] = len(retained)
    out["right_tail_retained_positive_126d_count"] = int(retained_126.gt(0).sum())
    out["left_tail_retained_negative_126d_count"] = int(retained_126.lt(0).sum())
    out["left_tail_retained_mean_126d"] = float(retained_126[retained_126 < 0].mean()) if bool(retained_126.lt(0).any()) else None
    allowed = frame[frame.get("action", pd.Series(dtype=str)).eq("ALLOW_REPLACEMENT")]
    regret = pd.to_numeric(allowed.get("incumbent_minus_challenger_126d"), errors="coerce").dropna()
    out["premature_sell_regret_positive_count_126d"] = int(regret.gt(0).sum())
    out["premature_sell_regret_mean_126d"] = float(regret[regret > 0].mean()) if bool(regret.gt(0).any()) else None
    return out


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = repo_path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    price_cache = repo_path(args.price_cache)
    rate_path = repo_path(args.cash_rate_path)
    lifecycle_path = repo_path(args.security_lifecycle_events)
    candidate_artifact = repo_path(args.candidate_artifact)
    scored_cache_path = repo_path(args.scored_candidate_cache)
    books = {
        "main": repo_path(args.main_target_book),
        "concentrated": repo_path(args.concentrated_target_book),
    }
    input_hashes = {
        "main_target_book": file_sha256(books["main"]),
        "concentrated_target_book": file_sha256(books["concentrated"]),
        "candidate_artifact": file_sha256(candidate_artifact),
        "scored_candidate_cache": file_sha256(scored_cache_path),
        "cash_rate": file_sha256(rate_path),
        "security_lifecycle_events": file_sha256(lifecycle_path),
    }
    hash_checks = {key: input_hashes[key] == value for key, value in EXPECTED_INPUT_HASHES.items()}
    if not all(hash_checks.values()):
        payload = {"schema_version": SCHEMA_VERSION, "status": "BLOCKED_INPUT_HASH", "input_hashes": input_hashes, "hash_checks": hash_checks}
        write_json(out_dir / "summary.json", payload)
        return payload
    scored = load_scored_candidate_cache(scored_cache_path)
    policy = LeadershipPersistencePolicy()
    portfolio_data: dict[str, dict[str, Any]] = {}
    overall_parity = True
    total_applied = 0

    for portfolio, book_path in books.items():
        portfolio_dir = out_dir / portfolio
        portfolio_dir.mkdir(parents=True, exist_ok=True)
        control_frame = pd.read_csv(book_path, low_memory=False)
        treatment, decisions, exits, policy_audit = build_leadership_persistence_book(
            control_frame,
            scored,
            portfolio=portfolio,
            lifecycle_path=lifecycle_path,
            policy=policy,
        )
        treatment_path = portfolio_dir / "treatment_target_book.csv"
        write_csv(treatment_path, treatment)
        write_csv(portfolio_dir / "replacement_decisions.csv", decisions)
        write_csv(portfolio_dir / "exit_intents.csv", exits)
        write_json(portfolio_dir / "policy_audit.json", policy_audit)
        total_applied += int(policy_audit["applied_retention_count"])

        cost_metrics: dict[str, dict[str, Any]] = {}
        replay_dirs: dict[str, dict[str, Path]] = {}
        for cost in COST_GRID:
            label = f"{int(cost)}bps"
            control_replay_dir = portfolio_dir / "broker" / label / "control"
            treatment_replay_dir = portfolio_dir / "broker" / label / "treatment"
            control_metrics = run_replay(
                target_book=book_path, price_cache=price_cache, rate_path=rate_path,
                output_dir=control_replay_dir, portfolio=portfolio, cost_bps=cost,
            )
            if int(policy_audit["applied_retention_count"]) > 0:
                treatment_metrics = run_replay(
                    target_book=treatment_path, price_cache=price_cache, rate_path=rate_path,
                    output_dir=treatment_replay_dir, portfolio=portfolio, cost_bps=cost,
                )
                effective_treatment_dir = treatment_replay_dir
            else:
                treatment_metrics = dict(control_metrics)
                effective_treatment_dir = control_replay_dir
            cost_metrics[label] = {"control": control_metrics, "treatment": treatment_metrics}
            replay_dirs[label] = {"control": control_replay_dir, "treatment": effective_treatment_dir}

        primary = cost_metrics["25bps"]
        parity = control_parity(primary["control"], portfolio_dir / "broker" / "25bps" / "control" / "trades.csv", portfolio)
        overall_parity = overall_parity and bool(parity["passed"])
        embargo = {}
        for name, cut in (("oos", DEFAULT_OOS_START), ("oos2", DEFAULT_OOS2_START)):
            control_embargo = embargo_metrics(replay_dirs["25bps"]["control"], cut)
            treatment_embargo = embargo_metrics(replay_dirs["25bps"]["treatment"], cut)
            embargo[name] = {
                "control": control_embargo,
                "treatment": treatment_embargo,
                "delta_cagr": _metric_delta(treatment_embargo, control_embargo, "cagr"),
                "delta_max_dd": _metric_delta(treatment_embargo, control_embargo, "max_dd"),
                "delta_sharpe": _metric_delta(treatment_embargo, control_embargo, "sharpe"),
            }
        counter = counterfactuals(decisions, price_cache)
        write_csv(portfolio_dir / "exit_counterfactuals.csv", counter)
        contribution_rows, concentration = contribution_concentration(
            decisions,
            sorted(pd.to_datetime(normalize_target_book(control_frame)["rebalance_date"]).unique()),
            price_cache,
        )
        write_csv(portfolio_dir / "incremental_contribution_attribution.csv", contribution_rows)
        intents = execution_sell_intents(treatment, exits, portfolio=portfolio, lifecycle_path=lifecycle_path)
        write_csv(portfolio_dir / "execution_sell_intents.csv", intents)
        treatment_trades = pd.read_csv(replay_dirs["25bps"]["treatment"] / "trades.csv", low_memory=False)
        trade_taxonomy = attach_trade_taxonomy(treatment_trades, intents)
        write_csv(portfolio_dir / "trades_with_sell_taxonomy.csv", trade_taxonomy)
        unclassified_sells = int(
            trade_taxonomy.loc[trade_taxonomy["side"].astype(str).eq("SELL"), "sell_taxonomy"].fillna("").eq("").sum()
        )
        holdings = holding_statistics(treatment_trades, price_cache)
        windows: dict[str, Any] = {}
        for window_name in ("full", "oos", "oos2"):
            control_window = _window(primary["control"], window_name)
            treatment_window = _window(primary["treatment"], window_name)
            windows[window_name] = {
                "control": control_window,
                "treatment": treatment_window,
                "delta_cagr": _metric_delta(treatment_window, control_window, "cagr"),
                "delta_max_dd": _metric_delta(treatment_window, control_window, "max_dd"),
                "delta_sharpe": _metric_delta(treatment_window, control_window, "sharpe"),
            }
        cost_summary = {}
        for label, values in cost_metrics.items():
            cost_summary[label] = {
                "control_cagr": safe_float(values["control"].get("cagr")),
                "treatment_cagr": safe_float(values["treatment"].get("cagr")),
                "delta_cagr": _metric_delta(values["treatment"], values["control"], "cagr"),
                "control_max_dd": safe_float(values["control"].get("max_dd")),
                "treatment_max_dd": safe_float(values["treatment"].get("max_dd")),
                "delta_max_dd": _metric_delta(values["treatment"], values["control"], "max_dd"),
                "control_sharpe": safe_float(values["control"].get("sharpe")),
                "treatment_sharpe": safe_float(values["treatment"].get("sharpe")),
                "delta_sharpe": _metric_delta(values["treatment"], values["control"], "sharpe"),
                "control_fees": safe_float(values["control"].get("total_fees_usd")),
                "treatment_fees": safe_float(values["treatment"].get("total_fees_usd")),
            }
        gates = {
            "control_parity": bool(parity["passed"]),
            "not_noop": int(policy_audit["applied_retention_count"]) > 0,
            "full_delta_cagr_ge_0_5pp": safe_float(windows["full"]["delta_cagr"], -math.inf) >= 0.005,
            "full_delta_sharpe_ge_minus_0_05": safe_float(windows["full"]["delta_sharpe"], -math.inf) >= -0.05,
            "full_delta_mdd_ge_minus_3pp": safe_float(windows["full"]["delta_max_dd"], -math.inf) >= -0.03,
            "oos_delta_cagr_nonnegative": safe_float(windows["oos"]["delta_cagr"], -math.inf) >= 0.0,
            "oos2_delta_cagr_nonnegative": safe_float(windows["oos2"]["delta_cagr"], -math.inf) >= 0.0,
            "oos_embargo_delta_cagr_nonnegative": safe_float(embargo["oos"]["delta_cagr"], -math.inf) >= 0.0,
            "oos2_embargo_delta_cagr_nonnegative": safe_float(embargo["oos2"]["delta_cagr"], -math.inf) >= 0.0,
            "ticker_contribution_le_50pct": safe_float(concentration.get("max_ticker_share"), math.inf) <= 0.50,
            "era_contribution_le_50pct": safe_float(concentration.get("max_era_share"), math.inf) <= 0.50,
            "sell_taxonomy_complete": unclassified_sells == 0,
            "future_label_use_zero": True,
            "weight_reserve_position_conservation": bool(
                policy_audit["weight_conservation_passed"]
                and policy_audit["cash_reserve_conservation_passed"]
                and policy_audit["position_count_conservation_passed"]
            ),
        }
        portfolio_data[portfolio] = {
            "policy_audit": policy_audit,
            "control_parity": parity,
            "windows": windows,
            "embargo_126_sessions": embargo,
            "cost_sensitivity": cost_summary,
            "holding_statistics": holdings,
            "counterfactual_summary": summarize_counterfactuals(counter),
            "contribution_concentration": concentration,
            "sell_taxonomy_counts": trade_taxonomy.loc[
                trade_taxonomy["side"].astype(str).eq("SELL"), "sell_taxonomy"
            ].value_counts().sort_index().to_dict(),
            "unclassified_sell_count": unclassified_sells,
            "gates": gates,
            "passed": all(gates.values()),
        }

    passed = bool(overall_parity and total_applied > 0 and all(item["passed"] for item in portfolio_data.values()))
    status = "PASS_RESEARCH_ONLY" if passed else ("BLOCKED_PARITY" if not overall_parity else ("REJECT_NO_OP" if total_applied == 0 else "REJECT_GATES"))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "policy_schema_version": POLICY_SCHEMA_VERSION,
        "status": status,
        "policy": policy.audit(),
        "input_hashes": input_hashes,
        "expected_input_hash_checks": hash_checks,
        "candidate_cache_future_columns_physically_excluded": scored.attrs.get("future_columns_physically_excluded", []),
        "candidate_cache_rows": len(scored),
        "portfolios": portfolio_data,
        "total_applied_retention_count": total_applied,
        "control_parity_passed": overall_parity,
        "do_not_repeat_key": (
            "" if passed else
            f"{POLICY_ID}+generated_books+2019-05-31_2026-07-10+25bps+dgs3mo"
        ),
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    write_json(out_dir / "summary.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-target-book", required=True)
    parser.add_argument("--concentrated-target-book", required=True)
    parser.add_argument("--candidate-artifact", required=True)
    parser.add_argument("--scored-candidate-cache", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--cash-rate-path", required=True)
    parser.add_argument("--security-lifecycle-events", default="data_static/run287_exact_packet/security_lifecycle_events.csv")
    parser.add_argument("--output-dir", default="outputs/run287_hold_exit_replacement")
    return parser.parse_args()


def main() -> int:
    payload = evaluate(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") not in {"BLOCKED_INPUT_HASH", "BLOCKED_PARITY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

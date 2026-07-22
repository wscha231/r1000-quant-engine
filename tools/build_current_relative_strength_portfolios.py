#!/usr/bin/env python3
"""Build review-only current portfolio proposals from relative-strength research.

The builder turns a dated, ranked research cross-section into three explicit
proposals: a diversified main book, a concentrated N=3 alternative, and the
recommended concentrated N=5 book.  It also marks the current paper accounts
with the same-close price source and writes integer-share transition previews.

It never mutates canonical target books, paper ledgers, or broker state, and it
does not place orders or run a backtest/fullrun.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.reserve_asset_policy import (  # noqa: E402
    BROKER_CASH_OR_MMF,
    reserve_reason_source_hash,
    resolve_reserve_asset_policy,
)

SCHEMA_VERSION = "run287-current-relative-strength-portfolios-v1"
CASH_TICKER = "CASH"
DATA_BLOCK_RESERVE = 0.08
TRANSACTION_BUFFER = 0.02
PULLBACK_DEPLOYMENT_MULTIPLIER = 0.75
RISK_WATCH_DEPLOYMENT_MULTIPLIER = 0.0
TARGET_COLUMNS = [
    "rebalance_date",
    "portfolio_kind",
    "proposal",
    "ticker",
    "Name",
    "sector",
    "industry_group",
    "target_weight",
    "weight",
    "target_stock_names",
    "selection_order",
    "optimization_rank",
    "optimization_score",
    "research_status",
    "current_price_live",
    "rs_spy_1m",
    "rs_spy_3m",
    "rs_spy_6m",
    "rs_spy_12m",
    "data_block_reserve",
    "transaction_buffer",
    "reentry_pending",
    "capacity_unallocated",
    "crisis_reserve",
    "residual_cash",
    "reserve_reason_source_hash",
    "review_only",
    "production_activation_allowed",
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def normalize_ticker(value: Any) -> str:
    ticker = str(value or "").upper().strip()
    return "" if ticker in {"", "NAN", "NONE"} else ticker


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def validate_source_freshness(
    ranked: pd.DataFrame,
    *,
    as_of_date: str,
    max_signal_age_days: int,
) -> str:
    if "valuation_close_date" not in ranked.columns:
        raise ValueError("ranked source missing valuation_close_date")
    dates = pd.to_datetime(ranked["valuation_close_date"], errors="coerce").dt.normalize()
    if dates.isna().any() or dates.nunique() != 1:
        raise ValueError("ranked source must contain exactly one valuation close date")
    valuation = pd.Timestamp(dates.iloc[0]).normalize()
    cutoff = pd.Timestamp(as_of_date).normalize()
    age = int((cutoff - valuation).days)
    if age < 0:
        raise ValueError(f"valuation close is after as-of date: {valuation.date()} > {cutoff.date()}")
    if age > int(max_signal_age_days):
        raise ValueError(
            f"stale relative-strength source: age={age} days, max={max_signal_age_days}"
        )
    return valuation.date().isoformat()


def prepare_ranked(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "ticker",
        "optimization_rank",
        "optimization_score",
        "sector_normalized",
        "industry_group",
        "research_status",
        "valuation_close_date",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("ranked source missing columns: " + ",".join(missing))
    out = frame.copy()
    out["ticker"] = out["ticker"].map(normalize_ticker)
    out["optimization_rank"] = pd.to_numeric(out["optimization_rank"], errors="coerce")
    out["optimization_score"] = pd.to_numeric(out["optimization_score"], errors="coerce")
    out = out.loc[
        out["ticker"].ne("")
        & out["optimization_rank"].notna()
        & out["optimization_score"].notna()
    ].copy()
    if out["ticker"].duplicated().any():
        duplicate = sorted(out.loc[out["ticker"].duplicated(False), "ticker"].unique())
        raise ValueError("duplicate ranked tickers: " + ",".join(duplicate))
    return out.sort_values(
        ["optimization_rank", "optimization_score", "ticker"],
        ascending=[True, False, True],
    ).reset_index(drop=True)


def constrained_select(
    ranked: pd.DataFrame,
    *,
    count: int,
    sector_cap: int,
    industry_cap: int,
) -> pd.DataFrame:
    selected: list[int] = []
    sectors: dict[str, int] = {}
    industries: dict[str, int] = {}
    for index, row in ranked.iterrows():
        sector = str(row.get("sector_normalized") or "Unknown")
        industry = str(row.get("industry_group") or "Unknown")
        if sectors.get(sector, 0) >= sector_cap:
            continue
        if industries.get(industry, 0) >= industry_cap:
            continue
        selected.append(index)
        sectors[sector] = sectors.get(sector, 0) + 1
        industries[industry] = industries.get(industry, 0) + 1
        if len(selected) == count:
            break
    if len(selected) != count:
        raise ValueError(f"constrained selection shortfall: {len(selected)} != {count}")
    result = ranked.loc[selected].copy().reset_index(drop=True)
    result["selection_order"] = np.arange(1, len(result) + 1)
    return result


def capped_weights(scores: pd.Series, *, gross: float, single_cap: float) -> pd.Series:
    values = pd.to_numeric(scores, errors="coerce").clip(lower=0.0).fillna(0.0) ** 2
    if float(values.sum()) <= 0:
        values = pd.Series(1.0, index=scores.index)
    weights = pd.Series(0.0, index=scores.index, dtype=float)
    active = list(scores.index)
    remaining = float(gross)
    while active and remaining > 1e-12:
        active_scores = values.loc[active]
        proposed = remaining * active_scores / float(active_scores.sum())
        breached = proposed[proposed > single_cap + 1e-12]
        if breached.empty:
            weights.loc[active] = proposed
            remaining = 0.0
            break
        for index in breached.index:
            weights.loc[index] = single_cap
            remaining -= single_cap
            active.remove(index)
    if remaining > 1e-9:
        raise ValueError("single-name cap prevents requested gross allocation")
    return weights


def deployment_multiplier(status: Any) -> float:
    value = str(status or "").upper().strip()
    if value.startswith("A_ENTRY_READY"):
        return 1.0
    if value.startswith("C_RISK"):
        return RISK_WATCH_DEPLOYMENT_MULTIPLIER
    return PULLBACK_DEPLOYMENT_MULTIPLIER


def build_target(
    selected: pd.DataFrame,
    *,
    portfolio_kind: str,
    proposal: str,
    valuation_date: str,
    single_cap: float,
    data_blocked: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    data_reserve = DATA_BLOCK_RESERVE if data_blocked else 0.0
    transaction_buffer = TRANSACTION_BUFFER
    fixed_reserve = data_reserve + transaction_buffer
    theoretical = capped_weights(
        selected["optimization_score"],
        gross=1.0 - fixed_reserve,
        single_cap=single_cap,
    )
    multipliers = selected["research_status"].map(deployment_multiplier)
    deployed = theoretical * multipliers
    reentry_pending = float((theoretical - deployed).sum())
    cash_weight = fixed_reserve + reentry_pending
    rows = selected.copy()
    rows["rebalance_date"] = valuation_date
    rows["portfolio_kind"] = portfolio_kind
    rows["proposal"] = proposal
    rows["target_weight"] = deployed
    rows["weight"] = deployed
    rows["target_stock_names"] = int(len(selected))
    rows["sector"] = rows.get("sector_normalized", "Unknown")
    rows["data_block_reserve"] = 0.0
    rows["transaction_buffer"] = 0.0
    rows["reentry_pending"] = 0.0
    rows["capacity_unallocated"] = 0.0
    rows["crisis_reserve"] = 0.0
    rows["residual_cash"] = 0.0
    reason_weights = {
        "crisis_reserve": 0.0,
        "data_block_reserve": round(data_reserve, 12),
        "transaction_buffer": round(transaction_buffer, 12),
        "reentry_pending": round(reentry_pending, 12),
        "capacity_unallocated": 0.0,
        "residual_cash": 0.0,
    }
    reason_hash = reserve_reason_source_hash(
        policy=resolve_reserve_asset_policy(BROKER_CASH_OR_MMF),
        reserve_weight=cash_weight,
        reasons=reason_weights,
    )
    rows["reserve_reason_source_hash"] = reason_hash
    rows["review_only"] = True
    rows["production_activation_allowed"] = False
    cash = {column: np.nan for column in rows.columns}
    cash.update(
        {
            "rebalance_date": valuation_date,
            "portfolio_kind": portfolio_kind,
            "proposal": proposal,
            "ticker": CASH_TICKER,
            "Name": "Broker cash or money-market reserve",
            "sector": "Reserve",
            "sector_normalized": "Reserve",
            "industry_group": "Reserve",
            "target_weight": cash_weight,
            "weight": cash_weight,
            "target_stock_names": int(len(selected)),
            "selection_order": int(len(selected)) + 1,
            "optimization_rank": np.nan,
            "optimization_score": np.nan,
            "research_status": "RESERVE",
            "current_price_live": 1.0,
            "data_block_reserve": data_reserve,
            "transaction_buffer": transaction_buffer,
            "reentry_pending": reentry_pending,
            "capacity_unallocated": 0.0,
            "crisis_reserve": 0.0,
            "residual_cash": 0.0,
            "reserve_reason_source_hash": reason_hash,
            "review_only": True,
            "production_activation_allowed": False,
        }
    )
    result = pd.concat([rows, pd.DataFrame([cash])], ignore_index=True)
    for column in TARGET_COLUMNS:
        if column not in result.columns:
            result[column] = np.nan
    result = result[TARGET_COLUMNS]
    total = float(result["target_weight"].sum())
    if not math.isclose(total, 1.0, abs_tol=1e-9):
        raise ValueError(f"target weights do not conserve to one: {proposal}={total}")
    stock = result.loc[result["ticker"].ne(CASH_TICKER)]
    if float(stock["target_weight"].max()) > single_cap + 1e-9:
        raise ValueError(f"single-name cap exceeded: {proposal}")
    summary = {
        "portfolio_kind": portfolio_kind,
        "proposal": proposal,
        "stock_count": int(len(stock)),
        "stock_weight": float(stock["target_weight"].sum()),
        "cash_weight": cash_weight,
        "data_block_reserve": data_reserve,
        "transaction_buffer": transaction_buffer,
        "reentry_pending": reentry_pending,
        "single_name_cap": single_cap,
        "tickers": stock["ticker"].tolist(),
        "reserve_reason_source_hash": reason_hash,
    }
    return result, summary


def load_account(path: Path, portfolio_kind: str) -> dict[str, Any]:
    payload = read_json(path)
    positions = payload.get("positions")
    if not isinstance(positions, list):
        raise ValueError(f"account positions missing: {path}")
    payload["portfolio_kind"] = portfolio_kind
    return payload


def price_map(frame: pd.DataFrame) -> dict[str, float]:
    if "ticker" not in frame.columns or "current_price_live" not in frame.columns:
        raise ValueError("price source requires ticker and current_price_live")
    result: dict[str, float] = {}
    for row in frame.to_dict("records"):
        ticker = normalize_ticker(row.get("ticker"))
        price = safe_float(row.get("current_price_live"))
        if ticker and price > 0:
            result[ticker] = price
    return result


def marked_account(
    account: dict[str, Any],
    *,
    prices: dict[str, float],
    valuation_date: str,
) -> tuple[pd.DataFrame, float, float]:
    rows: list[dict[str, Any]] = []
    stock_value = 0.0
    for position in account.get("positions") or []:
        ticker = normalize_ticker(position.get("ticker"))
        shares = safe_float(position.get("shares"))
        fallback = safe_float(position.get("price"))
        price = prices.get(ticker, fallback)
        if not ticker or shares <= 0 or price <= 0:
            raise ValueError(f"cannot mark current position: {ticker or '<blank>'}")
        value = shares * price
        stock_value += value
        rows.append(
            {
                "valuation_date": valuation_date,
                "portfolio_kind": str(account.get("portfolio_kind") or ""),
                "ticker": ticker,
                "shares": shares,
                "mark_price": price,
                "market_value_usd": value,
                "price_source": "same_close_price_source" if ticker in prices else "account_fallback",
            }
        )
    cash = safe_float(account.get("cash_usd"))
    equity = stock_value + cash
    if equity <= 0:
        raise ValueError("marked account equity must be positive")
    for row in rows:
        row["current_weight"] = row["market_value_usd"] / equity
    rows.append(
        {
            "valuation_date": valuation_date,
            "portfolio_kind": str(account.get("portfolio_kind") or ""),
            "ticker": CASH_TICKER,
            "shares": cash,
            "mark_price": 1.0,
            "market_value_usd": cash,
            "current_weight": cash / equity,
            "price_source": "account_cash",
        }
    )
    return pd.DataFrame(rows), equity, cash


def transition_preview(
    current: pd.DataFrame,
    target: pd.DataFrame,
    *,
    proposal: str,
    equity: float,
    current_cash: float,
    cost_bps: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    current_by = current.set_index("ticker").to_dict("index")
    target_by = target.set_index("ticker").to_dict("index")
    tickers = sorted((set(current_by) | set(target_by)) - {CASH_TICKER})
    rows: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    sell_proceeds = 0.0
    buy_cost = 0.0
    fee_rate = float(cost_bps) / 10_000.0
    for ticker in tickers:
        current_row = current_by.get(ticker, {})
        target_row = target_by.get(ticker, {})
        shares = safe_float(current_row.get("shares"))
        price = safe_float(target_row.get("current_price_live"), safe_float(current_row.get("mark_price")))
        if price <= 0:
            raise ValueError(f"transition price missing: {ticker}")
        target_weight = safe_float(target_row.get("target_weight"))
        target_value = equity * target_weight
        target_shares = math.floor(target_value / price + 1e-12)
        delta = int(target_shares - shares)
        current_weight = safe_float(current_row.get("current_weight"))
        if shares > 0 and target_shares == 0:
            decision = "EXIT"
        elif shares <= 0 and target_shares > 0:
            decision = "NEW"
        elif delta == 0:
            decision = "KEEP"
        elif delta > 0:
            decision = "ADD"
        else:
            decision = "TRIM"
        side = "BUY" if delta > 0 else "SELL" if delta < 0 else "HOLD"
        notional = abs(delta) * price
        fee = notional * fee_rate if delta else 0.0
        if delta > 0:
            buy_cost += notional + fee
        elif delta < 0:
            sell_proceeds += notional - fee
        row = {
            "proposal": proposal,
            "portfolio_kind": str(target_row.get("portfolio_kind") or current_row.get("portfolio_kind") or ""),
            "ticker": ticker,
            "decision": decision,
            "side": side,
            "current_shares": shares,
            "current_weight": current_weight,
            "target_weight": target_weight,
            "mark_price": price,
            "target_shares": target_shares,
            "share_delta": delta,
            "estimated_notional_usd": notional,
            "estimated_fee_usd": fee,
            "review_only": True,
            "live_order": False,
        }
        rows.append(row)
        if delta:
            orders.append(
                {
                    "proposal": proposal,
                    "portfolio_kind": row["portfolio_kind"],
                    "sequence": 1 if side == "SELL" else 2,
                    "ticker": ticker,
                    "side": side,
                    "quantity": abs(delta),
                    "estimated_price": price,
                    "estimated_notional_usd": notional,
                    "estimated_fee_usd": fee,
                    "review_only": True,
                    "live_order": False,
                }
            )
    frame = pd.DataFrame(rows).sort_values(
        ["decision", "estimated_notional_usd"], ascending=[True, False]
    )
    order_frame = pd.DataFrame(orders)
    if not order_frame.empty:
        order_frame = order_frame.sort_values(
            ["sequence", "estimated_notional_usd"], ascending=[True, False]
        ).reset_index(drop=True)
    projected_cash = current_cash + sell_proceeds - buy_cost
    target_cash = safe_float(target_by.get(CASH_TICKER, {}).get("target_weight"))
    equity_turnover_ex_cash = (
        float(frame["target_weight"].sub(frame["current_weight"]).abs().sum()) / 2.0
    )
    current_cash_weight = safe_float(
        current_by.get(CASH_TICKER, {}).get("current_weight")
    )
    turnover_including_cash = equity_turnover_ex_cash + (
        abs(target_cash - current_cash_weight) / 2.0
    )
    summary = {
        "proposal": proposal,
        "equity_usd": equity,
        "target_cash_weight": target_cash,
        "projected_cash_usd_after_integer_preview": projected_cash,
        "projected_cash_weight_after_integer_preview": projected_cash / equity,
        "estimated_weight_turnover_including_cash": turnover_including_cash,
        "estimated_equity_weight_turnover_ex_cash": equity_turnover_ex_cash,
        "preview_order_count": int(len(order_frame)),
        "exit_tickers": frame.loc[frame["decision"].eq("EXIT"), "ticker"].tolist(),
        "new_tickers": frame.loc[frame["decision"].eq("NEW"), "ticker"].tolist(),
        "kept_or_resized_tickers": frame.loc[
            frame["decision"].isin({"KEEP", "ADD", "TRIM"}), "ticker"
        ].tolist(),
    }
    return frame.reset_index(drop=True), order_frame, summary


def build(args: argparse.Namespace) -> dict[str, Any]:
    ranked_path = repo_path(args.ranked_candidates)
    summary_path = repo_path(args.selection_summary)
    price_path = repo_path(args.price_source)
    main_account_path = repo_path(args.main_account)
    concentrated_account_path = repo_path(args.concentrated_account)
    output_dir = repo_path(args.output_dir)
    ranked = prepare_ranked(pd.read_csv(ranked_path, low_memory=False))
    valuation_date = validate_source_freshness(
        ranked,
        as_of_date=args.as_of_date,
        max_signal_age_days=args.max_signal_age_days,
    )
    research_summary = read_json(summary_path)
    data_blocked = not bool(research_summary.get("upstream_full_bundle_ready"))
    prices = price_map(pd.read_csv(price_path, low_memory=False))

    selectable = ranked.loc[
        ~ranked["research_status"].astype(str).str.upper().str.startswith("C_RISK")
    ].reset_index(drop=True)
    main_selected = constrained_select(
        selectable,
        count=args.main_count,
        sector_cap=args.main_sector_cap,
        industry_cap=args.main_industry_cap,
    )
    n3_selected = constrained_select(
        selectable,
        count=3,
        sector_cap=2,
        industry_cap=1,
    )
    n5_selected = constrained_select(
        selectable,
        count=5,
        sector_cap=2,
        industry_cap=1,
    )
    targets: dict[str, pd.DataFrame] = {}
    target_summaries: dict[str, dict[str, Any]] = {}
    for name, selected, kind, cap in [
        ("main_n15", main_selected, "main", args.main_single_cap),
        ("concentrated_n3", n3_selected, "concentrated", args.concentrated_n3_single_cap),
        ("concentrated_n5", n5_selected, "concentrated", args.concentrated_n5_single_cap),
    ]:
        targets[name], target_summaries[name] = build_target(
            selected,
            portfolio_kind=kind,
            proposal=name,
            valuation_date=valuation_date,
            single_cap=cap,
            data_blocked=data_blocked,
        )

    main_account = load_account(main_account_path, "main")
    concentrated_account = load_account(concentrated_account_path, "concentrated")
    main_current, main_equity, main_cash = marked_account(
        main_account, prices=prices, valuation_date=valuation_date
    )
    concentrated_current, concentrated_equity, concentrated_cash = marked_account(
        concentrated_account, prices=prices, valuation_date=valuation_date
    )
    current = pd.concat([main_current, concentrated_current], ignore_index=True)

    transitions: dict[str, pd.DataFrame] = {}
    orders: dict[str, pd.DataFrame] = {}
    transition_summaries: dict[str, dict[str, Any]] = {}
    for name, target in targets.items():
        if name == "main_n15":
            account_frame, equity, cash = main_current, main_equity, main_cash
        else:
            account_frame, equity, cash = (
                concentrated_current,
                concentrated_equity,
                concentrated_cash,
            )
        transitions[name], orders[name], transition_summaries[name] = transition_preview(
            account_frame,
            target,
            proposal=name,
            equity=equity,
            current_cash=cash,
            cost_bps=args.cost_bps,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    targets["main_n15"].to_csv(output_dir / "main_target_proposal.csv", index=False)
    targets["concentrated_n3"].to_csv(
        output_dir / "concentrated_target_n3_alternative.csv", index=False
    )
    targets["concentrated_n5"].to_csv(
        output_dir / "concentrated_target_n5_recommended.csv", index=False
    )
    current.to_csv(output_dir / "current_portfolios_same_close.csv", index=False)
    for name in targets:
        transitions[name].to_csv(output_dir / f"{name}_transition.csv", index=False)
        orders[name].to_csv(output_dir / f"{name}_order_preview.csv", index=False)

    current_summaries = {}
    for kind, frame, equity in [
        ("main", main_current, main_equity),
        ("concentrated", concentrated_current, concentrated_equity),
    ]:
        current_summaries[kind] = {
            "equity_usd": equity,
            "cash_weight": safe_float(
                frame.loc[frame["ticker"].eq(CASH_TICKER), "current_weight"].iloc[0]
            ),
            "positions": [
                {
                    "ticker": str(row["ticker"]),
                    "shares": safe_float(row["shares"]),
                    "weight": safe_float(row["current_weight"]),
                    "mark_price": safe_float(row["mark_price"]),
                }
                for row in frame.loc[frame["ticker"].ne(CASH_TICKER)].to_dict("records")
            ],
        }

    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_REVIEW_ONLY_CURRENT_PORTFOLIO_PROPOSALS",
        "valuation_close_date": valuation_date,
        "as_of_date": args.as_of_date,
        "signal_age_calendar_days": int(
            (pd.Timestamp(args.as_of_date) - pd.Timestamp(valuation_date)).days
        ),
        "recommended_concentrated_proposal": "concentrated_n5",
        "selection_policy": {
            "main_count": args.main_count,
            "main_sector_cap": args.main_sector_cap,
            "main_industry_cap": args.main_industry_cap,
            "concentrated_n3_sector_cap": 2,
            "concentrated_n5_sector_cap": 2,
            "concentrated_industry_cap": 1,
            "score_weighting": "optimization_score_squared",
            "entry_ready_deployment_multiplier": 1.0,
            "pullback_watch_deployment_multiplier": PULLBACK_DEPLOYMENT_MULTIPLIER,
            "risk_watch_deployment_multiplier": RISK_WATCH_DEPLOYMENT_MULTIPLIER,
            "data_block_reserve": DATA_BLOCK_RESERVE if data_blocked else 0.0,
            "transaction_buffer": TRANSACTION_BUFFER,
        },
        "current_portfolios": current_summaries,
        "target_proposals": target_summaries,
        "transition_previews": transition_summaries,
        "source_inputs": {
            "ranked_candidates": {"path": str(ranked_path), "sha256": sha256(ranked_path)},
            "selection_summary": {"path": str(summary_path), "sha256": sha256(summary_path)},
            "price_source": {"path": str(price_path), "sha256": sha256(price_path)},
            "main_account": {"path": str(main_account_path), "sha256": sha256(main_account_path)},
            "concentrated_account": {
                "path": str(concentrated_account_path),
                "sha256": sha256(concentrated_account_path),
            },
        },
        "review_only": True,
        "target_books_mutated": False,
        "paper_accounts_mutated": False,
        "order_preview_generated": True,
        "orders_generated": False,
        "live_orders_placed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
    }
    write_json(output_dir / "summary.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ranked-candidates", required=True)
    parser.add_argument("--selection-summary", required=True)
    parser.add_argument("--price-source", required=True)
    parser.add_argument("--main-account", required=True)
    parser.add_argument("--concentrated-account", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    parser.add_argument("--max-signal-age-days", type=int, default=3)
    parser.add_argument("--main-count", type=int, default=15)
    parser.add_argument("--main-sector-cap", type=int, default=3)
    parser.add_argument("--main-industry-cap", type=int, default=2)
    parser.add_argument("--main-single-cap", type=float, default=0.18)
    parser.add_argument("--concentrated-n3-single-cap", type=float, default=0.40)
    parser.add_argument("--concentrated-n5-single-cap", type=float, default=0.30)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(
        json.dumps(
            {
                "status": payload["status"],
                "valuation_close_date": payload["valuation_close_date"],
                "recommended_concentrated_proposal": payload[
                    "recommended_concentrated_proposal"
                ],
                "target_books_mutated": payload["target_books_mutated"],
                "orders_generated": payload["orders_generated"],
                "fullrun_executed": payload["fullrun_executed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

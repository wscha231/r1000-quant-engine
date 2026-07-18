#!/usr/bin/env python3
"""Create a fail-closed, review-only seed for the Run287 forward paper ledger.

The daily workflow must not depend on a historical fullrun artifact being
present before it can begin collecting true-forward fills.  When neither a
restored paper account nor a frozen bootstrap account exists, this tool marks
the latest target allocation at one exact completed-session adjusted close.

The seed is an explicit starting assumption, not a historical fill claim.  It
never calls a broker, backfills trades, changes a target book, or authorizes
production use.  Subsequent changes continue through the existing next-close,
25 bps, integer-share forward ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_account_order_preview import normalize_target  # noqa: E402
from tools.run_broker_ledger_replay import CASH_TICKERS  # noqa: E402
from tools.run_weekly_evaluation import load_price_series, px_cache_name  # noqa: E402


PORTFOLIOS = ("main", "concentrated")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def file_hash(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def clean_ticker(value: Any) -> str:
    ticker = str(value or "").upper().strip()
    return "" if ticker in {"", "NAN", "NONE"} else ticker


def load_exact_close(price_cache: Path, ticker: str, as_of_date: pd.Timestamp) -> float:
    frame = load_price_series(price_cache, ticker)
    if frame.empty or "close" not in frame.columns:
        raise ValueError(f"missing price series for bootstrap ticker {ticker}")
    exact = frame[frame.index.normalize() == as_of_date]
    if exact.empty:
        raise ValueError(f"missing exact completed-session close for {ticker} on {as_of_date.date().isoformat()}")
    values = pd.to_numeric(exact["close"], errors="coerce").dropna()
    if len(values) != 1:
        raise ValueError(f"ambiguous exact completed-session close for {ticker} on {as_of_date.date().isoformat()}")
    price = float(values.iloc[0])
    if not math.isfinite(price) or price <= 0:
        raise ValueError(f"invalid exact completed-session close for {ticker} on {as_of_date.date().isoformat()}")
    return price


def target_for_date(target_path: Path, portfolio: str, as_of_date: pd.Timestamp) -> pd.DataFrame:
    if not target_path.is_file():
        raise FileNotFoundError(f"missing target book for {portfolio}: {target_path}")
    raw = pd.read_csv(target_path, low_memory=False)
    target = normalize_target(raw, portfolio, as_of_date.date().isoformat())
    if target.empty:
        raise ValueError(f"empty target allocation for {portfolio}")
    target = target[["ticker", "target_weight"]].copy()
    target["ticker"] = target["ticker"].map(clean_ticker)
    target["target_weight"] = pd.to_numeric(target["target_weight"], errors="coerce")
    target = target[(target["ticker"] != "") & target["target_weight"].notna()].copy()
    if target.empty or (target["target_weight"] < -1e-12).any():
        raise ValueError(f"invalid target allocation for {portfolio}")
    target = target.groupby("ticker", as_index=False)["target_weight"].sum().sort_values("ticker").reset_index(drop=True)
    total = float(target["target_weight"].sum())
    if total <= 0 or total > 1.0 + 1e-9:
        raise ValueError(f"target weight sum outside (0,1] for {portfolio}: {total}")
    return target


def validate_existing_bootstrap(payload: dict[str, Any], portfolio: str, cost_bps: float) -> None:
    if not payload:
        raise ValueError(f"empty existing bootstrap for {portfolio}")
    if str(payload.get("portfolio_kind") or "").lower() != portfolio:
        raise ValueError(f"existing bootstrap portfolio mismatch for {portfolio}")
    if payload.get("review_only") is not True or payload.get("live_trading_enabled") is not False:
        raise ValueError(f"existing bootstrap safety flags invalid for {portfolio}")
    if payload.get("production_mutation_allowed") is not False:
        raise ValueError(f"existing bootstrap production flag invalid for {portfolio}")
    if payload.get("integer_shares") is not True or str(payload.get("fill_mode") or "") != "next_close":
        raise ValueError(f"existing bootstrap execution contract invalid for {portfolio}")
    if abs(float(payload.get("cost_bps_per_side", cost_bps)) - float(cost_bps)) > 1e-9:
        raise ValueError(f"existing bootstrap cost mismatch for {portfolio}")


def validate_seed_date(payload: dict[str, Any], portfolio: str, expected_seed_date: pd.Timestamp | None) -> None:
    if expected_seed_date is None:
        return
    raw = payload.get("seed_as_of_date") or payload.get("as_of_date")
    actual = pd.to_datetime(raw, errors="coerce")
    if pd.isna(actual) or pd.Timestamp(actual).normalize() != expected_seed_date:
        actual_text = "missing" if pd.isna(actual) else pd.Timestamp(actual).date().isoformat()
        raise ValueError(
            f"paper seed date mismatch for {portfolio}: expected "
            f"{expected_seed_date.date().isoformat()}, got {actual_text}"
        )


def has_prior_ledger_state(portfolio_dir: Path) -> bool:
    if (portfolio_dir / "manifest.json").exists() or (portfolio_dir / "state_meta.json").exists():
        return True
    for name in ("fills.csv", "rejections.csv", "pending_orders.csv", "equity_curve.csv"):
        path = portfolio_dir / name
        if path.is_file() and path.stat().st_size > 0:
            return True
    return False


def build_account(
    *,
    portfolio: str,
    target_path: Path,
    price_cache: Path,
    as_of_date: pd.Timestamp,
    starting_capital: float,
    cost_bps: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    target = target_for_date(target_path, portfolio, as_of_date)
    stock_target = target[~target["ticker"].isin(CASH_TICKERS)].copy()
    if stock_target.empty:
        raise ValueError(f"bootstrap target has no securities for {portfolio}")

    positions: list[dict[str, Any]] = []
    price_hashes: dict[str, str] = {}
    stock_value = 0.0
    for row in stock_target.itertuples(index=False):
        ticker = str(row.ticker)
        target_weight = float(row.target_weight)
        price = load_exact_close(price_cache, ticker, as_of_date)
        shares = int(math.floor((starting_capital * target_weight) / price + 1e-12))
        if shares <= 0:
            continue
        market_value = float(shares * price)
        stock_value += market_value
        positions.append(
            {
                "as_of_date": as_of_date.date().isoformat(),
                "ticker": ticker,
                "shares": shares,
                "price": price,
                "market_value_usd": market_value,
                "weight": market_value / starting_capital,
                "cost_basis": price,
                "seed_position_assumption": "target_assumed_applied_at_exact_close",
            }
        )
        price_hashes[ticker] = file_hash(price_cache / px_cache_name(ticker))
    if not positions:
        raise ValueError(f"integer-share bootstrap produced no positions for {portfolio}")

    cash = float(starting_capital - stock_value)
    if cash < -1e-6:
        raise ValueError(f"bootstrap produced negative cash for {portfolio}")
    target_rows = [
        {"ticker": str(row.ticker), "target_weight": round(float(row.target_weight), 12)}
        for row in target.itertuples(index=False)
    ]
    target_digest = canonical_hash({"schema": "run287-forward-target-v1", "rows": target_rows})
    account = {
        "schema_version": "run287-daily-paper-bootstrap-account-v1",
        "portfolio_kind": portfolio,
        "as_of_date": as_of_date.date().isoformat(),
        "seed_as_of_date": as_of_date.date().isoformat(),
        "starting_capital_usd": float(starting_capital),
        "seed_equity_usd": float(starting_capital),
        "equity_usd": float(starting_capital),
        "cash_usd": cash,
        "cash_weight": cash / starting_capital,
        "stock_value_usd": stock_value,
        "position_count": len(positions),
        "fill_mode": "next_close",
        "cost_bps_per_side": float(cost_bps),
        "integer_shares": True,
        "cash_carry_mode": "none",
        "positions": positions,
        "realized_pnl_by_ticker": {},
        "target_sha256": file_hash(target_path),
        "assumed_applied_target_hash": target_digest,
        "bootstrap_method": "exact_close_target_snapshot_without_historical_trade_backfill",
        "historical_trade_backfill_claimed": False,
        "portfolio_weights_changed": False,
        "review_only": True,
        "simulated_broker_ledger": True,
        "live_trading_enabled": False,
        "production_mutation_allowed": False,
        "human_approval_required_for_live_orders": True,
        "created_at_utc": utc_now(),
    }
    evidence = {
        "portfolio_kind": portfolio,
        "target_sha256": file_hash(target_path),
        "target_hash": target_digest,
        "target_weight_sum": float(target["target_weight"].sum()),
        "target_stock_weight_sum": float(stock_target["target_weight"].sum()),
        "actual_stock_weight": stock_value / starting_capital,
        "actual_cash_weight": cash / starting_capital,
        "position_count": len(positions),
        "price_file_sha256": price_hashes,
    }
    return account, evidence


def run(args: argparse.Namespace) -> dict[str, Any]:
    state_root = repo_path(args.state_dir)
    price_cache = repo_path(args.price_cache)
    as_of_date = pd.Timestamp(args.as_of_date).normalize()
    if pd.isna(as_of_date):
        raise ValueError("--as-of-date must be a completed market date")
    starting_capital = float(args.starting_capital)
    cost_bps = float(args.cost_bps)
    expected_seed_raw = str(getattr(args, "expected_seed_date", "") or "").strip()
    expected_seed_date = pd.Timestamp(expected_seed_raw).normalize() if expected_seed_raw else None
    if expected_seed_date is not None and pd.isna(expected_seed_date):
        raise ValueError("--expected-seed-date must be a valid market date")
    if not math.isfinite(starting_capital) or starting_capital <= 0:
        raise ValueError("--starting-capital must be positive")
    if not math.isfinite(cost_bps) or cost_bps < 0:
        raise ValueError("--cost-bps must be non-negative")

    bootstrap_dir = state_root / "bootstrap"
    results: dict[str, Any] = {}
    created = 0
    for portfolio in PORTFOLIOS:
        portfolio_dir = state_root / portfolio
        state_path = portfolio_dir / "account_state_latest.json"
        bootstrap_path = bootstrap_dir / f"{portfolio}_account.json"
        state = read_json(state_path)
        existing = read_json(bootstrap_path)
        if state:
            if state.get("review_only") is not True or state.get("live_trading_enabled") is not False:
                raise ValueError(f"restored paper account safety flags invalid for {portfolio}")
            validate_seed_date(state, portfolio, expected_seed_date)
            if expected_seed_date is not None:
                if not existing:
                    raise ValueError(f"missing frozen bootstrap anchor for restored {portfolio} paper state")
                validate_existing_bootstrap(existing, portfolio, cost_bps)
                validate_seed_date(existing, portfolio, expected_seed_date)
            results[portfolio] = {
                "status": "RESTORED_STATE_PRESENT",
                "account_path": str(state_path),
                "account_sha256": file_hash(state_path),
            }
            continue
        if existing:
            if has_prior_ledger_state(portfolio_dir):
                raise ValueError(f"paper ledger state is incomplete for {portfolio}; refusing bootstrap reset")
            validate_existing_bootstrap(existing, portfolio, cost_bps)
            validate_seed_date(existing, portfolio, expected_seed_date)
            results[portfolio] = {
                "status": "REUSED_FROZEN_BOOTSTRAP",
                "account_path": str(bootstrap_path),
                "account_sha256": file_hash(bootstrap_path),
            }
            continue

        if expected_seed_date is not None and as_of_date != expected_seed_date:
            raise ValueError(
                f"missing canonical paper state for {portfolio} after seed date "
                f"{expected_seed_date.date().isoformat()}; refusing late bootstrap on "
                f"{as_of_date.date().isoformat()}"
            )

        target_path = repo_path(getattr(args, f"{portfolio}_target"))
        account, evidence = build_account(
            portfolio=portfolio,
            target_path=target_path,
            price_cache=price_cache,
            as_of_date=as_of_date,
            starting_capital=starting_capital,
            cost_bps=cost_bps,
        )
        write_json(bootstrap_path, account)
        created += 1
        results[portfolio] = {
            "status": "CREATED_EXACT_CLOSE_BOOTSTRAP",
            "account_path": str(bootstrap_path),
            "account_sha256": file_hash(bootstrap_path),
            **evidence,
        }

    payload = {
        "schema_version": "run287-daily-paper-bootstrap-v1",
        "status": "READY_REVIEW_ONLY_PAPER_BOOTSTRAP",
        "as_of_date": as_of_date.date().isoformat(),
        "expected_seed_date": expected_seed_date.date().isoformat() if expected_seed_date is not None else None,
        "starting_capital_usd": starting_capital,
        "cost_bps_per_side": cost_bps,
        "created_account_count": created,
        "results": results,
        "historical_trade_backfill_claimed": False,
        "fullrun_executed": False,
        "target_books_changed": False,
        "portfolio_weights_changed": False,
        "orders_placed": False,
        "review_only": True,
        "live_trading_enabled": False,
        "production_mutation_allowed": False,
        "generated_at_utc": utc_now(),
    }
    write_json(bootstrap_dir / "summary.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default="outputs/daily_simulated_fill_ledger")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--main-target", default="outputs/reports/operating_main_target_book.csv")
    parser.add_argument("--concentrated-target", default="outputs/reports/operating_concentrated_target_book.csv")
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument(
        "--expected-seed-date",
        default="",
        help="Canonical first paper session; blocks creation of a replacement seed on later dates.",
    )
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    return parser.parse_args()


def main() -> int:
    try:
        payload = run(parse_args())
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

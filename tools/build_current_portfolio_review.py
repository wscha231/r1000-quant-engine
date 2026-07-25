#!/usr/bin/env python3
"""Mark accepted portfolios to an exact close and apply promotion guardrails.

This is intentionally report-only.  It never writes target books, account
state, ledgers, or orders.  A research challenger that misses either the CAGR
or drawdown objective cannot silently become the displayed "current" book.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_theme_leadership_tape import load_price_cache  # noqa: E402


OBJECTIVES = {
    "main": {"minimum_cagr": 0.35, "minimum_max_drawdown": -0.25},
    "concentrated": {"minimum_cagr": 0.50, "minimum_max_drawdown": -0.25},
}


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def exact_close(price_cache: Path, ticker: str, close_date: pd.Timestamp) -> float:
    frame = load_price_cache(price_cache, ticker)
    if frame.empty or close_date not in frame.index:
        return math.nan
    value = pd.to_numeric(frame.loc[close_date, "raw_close"], errors="coerce")
    if isinstance(value, pd.Series):
        value = value.iloc[-1]
    return float(value)


def mark_portfolio(
    name: str,
    portfolio: dict[str, Any],
    price_cache: Path,
    close_date: pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    previous_total = float(portfolio["equity_usd"])
    cash_usd = float(portfolio["cash_weight"]) * previous_total
    rows: list[dict[str, Any]] = []
    missing: list[str] = []

    for position in portfolio.get("positions", []):
        ticker = str(position["ticker"]).strip().upper()
        price = exact_close(price_cache, ticker, close_date)
        if not math.isfinite(price):
            missing.append(ticker)
            continue
        shares = float(position["shares"])
        rows.append(
            {
                "portfolio": name,
                "ticker": ticker,
                "asset_type": "equity",
                "shares": shares,
                "close_date": close_date.strftime("%Y-%m-%d"),
                "close_price": price,
                "market_value_usd": shares * price,
            }
        )

    if missing:
        raise RuntimeError(
            f"{name} missing exact close for {close_date.date()}: {', '.join(missing)}"
        )

    rows.append(
        {
            "portfolio": name,
            "ticker": "CASH",
            "asset_type": "cash",
            "shares": math.nan,
            "close_date": close_date.strftime("%Y-%m-%d"),
            "close_price": 1.0,
            "market_value_usd": cash_usd,
        }
    )
    marked = pd.DataFrame(rows)
    current_total = float(marked["market_value_usd"].sum())
    marked["current_weight"] = marked["market_value_usd"] / current_total
    marked["proposed_weight"] = marked["current_weight"]
    marked["reconstruction_action"] = "RETAIN"
    marked = marked.sort_values(
        ["asset_type", "current_weight"], ascending=[True, False]
    ).reset_index(drop=True)

    summary = {
        "portfolio": name,
        "close_date": close_date.strftime("%Y-%m-%d"),
        "exact_close_position_count": len(rows) - 1,
        "exact_close_coverage": 1.0,
        "cash_usd": cash_usd,
        "cash_weight": cash_usd / current_total,
        "previous_total_equity_usd": previous_total,
        "current_total_equity_usd": current_total,
        "mark_to_market_change_usd": current_total - previous_total,
        "mark_to_market_change": current_total / previous_total - 1.0,
    }
    return marked, summary


def challenger_evaluation(
    cost_sensitivity: pd.DataFrame,
    portfolio: str,
) -> dict[str, Any]:
    objective = OBJECTIVES[portfolio]
    rows = cost_sensitivity.loc[
        cost_sensitivity["portfolio_kind"].astype(str).eq(portfolio)
    ].copy()
    row_25 = rows.loc[pd.to_numeric(rows["cost_bps"]).eq(25.0)]
    if len(row_25) != 1:
        raise RuntimeError(f"{portfolio}: expected one 25bps challenger result")
    metric = row_25.iloc[0]
    cagr = float(metric["cagr"])
    max_dd = float(metric["max_dd"])
    cagr_pass = cagr >= objective["minimum_cagr"]
    drawdown_pass = max_dd >= objective["minimum_max_drawdown"]
    cost_rows = []
    for _, row in rows.sort_values("cost_bps").iterrows():
        cost_rows.append(
            {
                "cost_bps": float(row["cost_bps"]),
                "cagr": float(row["cagr"]),
                "max_drawdown": float(row["max_dd"]),
                "sharpe": float(row["sharpe"]),
            }
        )
    return {
        "portfolio": portfolio,
        "variant_id": str(metric["variant_id"]),
        "objective": objective,
        "metrics_25bps": {
            "cagr": cagr,
            "max_drawdown": max_dd,
            "sharpe": float(metric["sharpe"]),
        },
        "cost_sensitivity": cost_rows,
        "cagr_pass": cagr_pass,
        "drawdown_pass": drawdown_pass,
        "promotion_gate_pass": cagr_pass and drawdown_pass,
        "decision": (
            "PROMOTION_ELIGIBLE"
            if cagr_pass and drawdown_pass
            else "RETAIN_ACCEPTED_CHAMPION"
        ),
    }


def run(
    current_summary_path: Path,
    price_cache: Path,
    tape_summary_path: Path,
    cost_sensitivity_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    current_summary = read_json(current_summary_path)
    tape_summary = read_json(tape_summary_path)
    close_date = pd.Timestamp(tape_summary["common_close_date"]).tz_localize(None)
    cost_sensitivity = pd.read_csv(cost_sensitivity_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    price_cache_manifest = price_cache / "replay_price_cache_manifest.json"
    if not price_cache_manifest.is_file():
        raise RuntimeError(
            f"price cache manifest is required for reproducible marks: {price_cache_manifest}"
        )

    marked_frames: list[pd.DataFrame] = []
    portfolio_summaries: dict[str, Any] = {}
    challenger: dict[str, Any] = {}
    for name in ("main", "concentrated"):
        marked, marked_summary = mark_portfolio(
            name,
            current_summary["current_portfolios"][name],
            price_cache,
            close_date,
        )
        evaluation = challenger_evaluation(cost_sensitivity, name)
        if evaluation["promotion_gate_pass"]:
            marked["reconstruction_action"] = "REVIEW_PROMOTION_ELIGIBLE"
        marked_frames.append(marked)
        portfolio_summaries[name] = marked_summary
        challenger[name] = evaluation

    holdings = pd.concat(marked_frames, ignore_index=True)
    holdings_path = output_dir / "current_holdings_exact_close.csv"
    holdings.to_csv(holdings_path, index=False, float_format="%.10f")

    promotion_allowed = all(
        item["promotion_gate_pass"] for item in challenger.values()
    )
    payload = {
        "schema_version": "run287-current-portfolio-review-v1",
        "status": "READY_REVIEW_ONLY",
        "close_date": close_date.strftime("%Y-%m-%d"),
        "source_account_state_as_of": current_summary.get("as_of_date"),
        "source_account_valuation_close": current_summary.get("valuation_close_date"),
        "decision": (
            "REVIEW_CHALLENGER_PROMOTION"
            if promotion_allowed
            else "RETAIN_ACCEPTED_CHAMPION"
        ),
        "decision_reason": (
            "All portfolio objectives passed at 25bps."
            if promotion_allowed
            else "Hierarchical challenger missed one or more CAGR/drawdown objectives."
        ),
        "portfolio_summaries": portfolio_summaries,
        "challenger_evaluation": challenger,
        "current_holdings_path": str(holdings_path.resolve()),
        "research_only": True,
        "production_activation_allowed": False,
        "target_books_mutated": False,
        "account_state_mutated": False,
        "orders_generated": False,
        "fullrun_executed": False,
        "inputs": {
            "current_summary": {
                "path": str(current_summary_path.resolve()),
                "sha256": sha256_file(current_summary_path),
            },
            "tape_summary": {
                "path": str(tape_summary_path.resolve()),
                "sha256": sha256_file(tape_summary_path),
            },
            "cost_sensitivity": {
                "path": str(cost_sensitivity_path.resolve()),
                "sha256": sha256_file(cost_sensitivity_path),
            },
            "price_cache": str(price_cache.resolve()),
            "price_cache_manifest": {
                "path": str(price_cache_manifest.resolve()),
                "sha256": sha256_file(price_cache_manifest),
            },
        },
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-summary", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--tape-summary", required=True)
    parser.add_argument("--cost-sensitivity", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(
        repo_path(args.current_summary),
        repo_path(args.price_cache),
        repo_path(args.tape_summary),
        repo_path(args.cost_sensitivity),
        repo_path(args.output_dir),
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

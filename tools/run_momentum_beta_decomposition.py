#!/usr/bin/env python3
"""Research-only M1 momentum beta decomposition.

This audit decomposes monthly target-book returns against a market proxy and an
internal cross-sectional momentum factor. It never changes selection or weights.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.research_audit_utils import first_existing, linear_regression, read_csv, repo_path, safe_float, write_json  # noqa: E402
from tools.run_weekly_evaluation import load_price_series  # noqa: E402

DEFAULT_OUTPUT_DIR = "outputs/momentum_beta_decomposition"
RETURN_COLUMNS = ["period_forward_return", "forward_period_return", "forward_21d_excess", "forward_63d_excess"]


def portfolio_from_path(path: Path) -> str:
    text = path.name.lower()
    if "concentrated" in text:
        return "concentrated"
    if "main" in text:
        return "main"
    return "unknown"


def load_book_returns(paths: list[Path]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for path in paths:
        frame = read_csv(path)
        ret_col = first_existing(frame, RETURN_COLUMNS)
        if frame.empty or "rebalance_date" not in frame.columns or "ticker" not in frame.columns or "weight" not in frame.columns or not ret_col:
            continue
        d = frame.copy()
        d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
        d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
        d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0)
        d["row_return"] = pd.to_numeric(d[ret_col], errors="coerce")
        d["portfolio_kind"] = d["portfolio_kind"] if "portfolio_kind" in d.columns else portfolio_from_path(path)
        d = d[d["rebalance_date"].notna() & d["ticker"].ne("")]
        d["weighted_return"] = d["weight"] * d["row_return"].fillna(0.0)
        grouped = (
            d.groupby(["portfolio_kind", "rebalance_date"], dropna=False)
            .agg(portfolio_return=("weighted_return", "sum"), row_count=("ticker", "count"), source=("ticker", lambda _: str(path)))
            .reset_index()
        )
        rows.append(grouped)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def market_returns(price_cache: Path, dates: list[pd.Timestamp], ticker: str = "SPY") -> pd.DataFrame:
    px = load_price_series(price_cache, ticker)
    if px.empty or "close" not in px.columns:
        return pd.DataFrame({"rebalance_date": dates, "market_return": [None] * len(dates)})
    out = []
    for dt in dates:
        dt = pd.Timestamp(dt)
        prior = px[px.index <= dt - pd.Timedelta(days=21)]
        now = px[px.index <= dt]
        if prior.empty or now.empty:
            value = None
        else:
            value = safe_float(now["close"].iloc[-1] / prior["close"].iloc[-1] - 1.0, default=0.0)
        out.append({"rebalance_date": dt, "market_return": value})
    return pd.DataFrame(out)


def internal_momentum_factor(book_paths: list[Path], dates: list[pd.Timestamp]) -> pd.DataFrame:
    frames = [read_csv(path) for path in book_paths]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame({"rebalance_date": dates, "internal_momentum_return": [None] * len(dates)})
    d = pd.concat(frames, ignore_index=True)
    ret_col = first_existing(d, RETURN_COLUMNS)
    score_col = first_existing(d, ["mom_12m", "relative_strength_composite", "rs_spy_12m", "rs_spy_6m", "rs_spy_3m"])
    if not ret_col or not score_col or "rebalance_date" not in d.columns:
        return pd.DataFrame({"rebalance_date": dates, "internal_momentum_return": [None] * len(dates)})
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["_ret"] = pd.to_numeric(d[ret_col], errors="coerce")
    d["_score"] = pd.to_numeric(d[score_col], errors="coerce")
    out = []
    for dt in dates:
        day = d[d["rebalance_date"].eq(pd.Timestamp(dt))].dropna(subset=["_ret", "_score"])
        if len(day) < 6:
            factor = None
        else:
            top = day[day["_score"] >= day["_score"].quantile(0.8)]["_ret"].mean()
            bottom = day[day["_score"] <= day["_score"].quantile(0.2)]["_ret"].mean()
            factor = safe_float(top - bottom)
        out.append({"rebalance_date": pd.Timestamp(dt), "internal_momentum_return": factor})
    return pd.DataFrame(out)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    book_paths = [repo_path(path) for path in args.target_books]
    portfolio = load_book_returns(book_paths)
    if portfolio.empty:
        payload = {
            "schema_version": "momentum-beta-decomposition-v1",
            "status": "blocked",
            "reason": "missing_target_book_returns",
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "summary.json", payload)
        (output_dir / "report.md").write_text("# Momentum Beta Decomposition\n\nBlocked: missing target-book return columns.\n", encoding="utf-8")
        pd.DataFrame().to_csv(output_dir / "factor_returns.csv", index=False)
        pd.DataFrame().to_csv(output_dir / "regression_table.csv", index=False)
        return payload
    dates = sorted(pd.to_datetime(portfolio["rebalance_date"], errors="coerce").dropna().unique())
    factor = pd.DataFrame({"rebalance_date": dates})
    factor = factor.merge(market_returns(repo_path(args.price_cache), dates, args.market_ticker), on="rebalance_date", how="left")
    factor = factor.merge(internal_momentum_factor(book_paths, dates), on="rebalance_date", how="left")
    portfolio = portfolio.merge(factor, on="rebalance_date", how="left")
    rows: list[dict[str, Any]] = []
    for portfolio_kind, group in portfolio.groupby("portfolio_kind", dropna=False):
        reg = linear_regression(
            group["portfolio_return"],
            group[["market_return", "internal_momentum_return"]],
        )
        rows.append({"portfolio_kind": portfolio_kind, **reg})
    reg_table = pd.DataFrame(rows)
    factor.to_csv(output_dir / "factor_returns.csv", index=False)
    reg_table.to_csv(output_dir / "regression_table.csv", index=False)
    payload = {
        "schema_version": "momentum-beta-decomposition-v1",
        "status": "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_books": [str(path) for path in book_paths],
        "price_cache": str(repo_path(args.price_cache)),
        "portfolio_month_count": int(len(portfolio)),
        "factor_month_count": int(len(factor)),
        "research_only": True,
        "production_activation_allowed": False,
        "selection_or_weight_change_allowed": False,
        "canonical_input_rule": "fixed_official_books_preferred_until_w1_control_reproduction_passes",
        "regenerated_target_book_acceptance_allowed": False,
        "outputs": {
            "factor_returns_csv": str(output_dir / "factor_returns.csv"),
            "regression_table_csv": str(output_dir / "regression_table.csv"),
            "report_md": str(output_dir / "report.md"),
        },
    }
    write_json(output_dir / "summary.json", payload)
    lines = [
        "# Momentum Beta Decomposition",
        "",
        f"- status: `{payload['status']}`",
        f"- portfolio months: `{payload['portfolio_month_count']}`",
        "- research only: `true`",
        "- selection or weight change allowed: `false`",
        "",
        "| portfolio | status | n | market beta | momentum beta | residual alpha mean | r2 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('portfolio_kind')} | {row.get('status')} | {row.get('sample_count')} | "
            f"{row.get('market_return_beta', '')} | {row.get('internal_momentum_return_beta', '')} | "
            f"{row.get('residual_alpha_mean', '')} | {row.get('r_squared', '')} |"
        )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-books", nargs="+", required=True)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--market-ticker", default="SPY")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

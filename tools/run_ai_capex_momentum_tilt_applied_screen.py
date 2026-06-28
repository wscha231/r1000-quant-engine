#!/usr/bin/env python3
"""Fast applied-count screen for the Main AI Capex momentum tilt hook."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_alphaops_vnext_policy_replay import apply_main_ai_capex_momentum_tilt, safe_float  # noqa: E402

SCHEMA_VERSION = "ai-capex-momentum-tilt-applied-screen-v1"
CASH_TICKERS = {"CASH", "__CASH__"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def clean_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def is_cash_row(row: pd.Series) -> bool:
    return clean_ticker(row.get("ticker")) in CASH_TICKERS


def weight_value(row: pd.Series | dict[str, Any]) -> float:
    return safe_float(row.get("target_weight"), safe_float(row.get("weight")))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, sort_keys=True) + "\n", encoding="utf-8")


def run_screen(target_book: Path, output_dir: Path, *, portfolio_kind: str = "main") -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    book = pd.read_csv(target_book, low_memory=False)
    if "rebalance_date" not in book.columns or "ticker" not in book.columns:
        raise ValueError("target book must include rebalance_date and ticker")
    book["rebalance_date"] = pd.to_datetime(book["rebalance_date"], errors="coerce").dt.date.astype(str)
    old_env = os.environ.get("PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED")
    os.environ["PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED"] = "1"
    date_rows: list[dict[str, Any]] = []
    stock_rows: list[dict[str, Any]] = []
    out_groups: list[pd.DataFrame] = []
    try:
        for date_text, group in book.groupby("rebalance_date", sort=True):
            cash_mask = group.apply(is_cash_row, axis=1)
            stocks = group.loc[~cash_mask].copy()
            cash = group.loc[cash_mask].copy()
            before = {clean_ticker(row.get("ticker")): weight_value(row) for _, row in stocks.iterrows()}
            after_records = apply_main_ai_capex_momentum_tilt(stocks.to_dict(orient="records"), portfolio_kind)
            after = {clean_ticker(row.get("ticker")): weight_value(row) for row in after_records}
            applied = [row for row in after_records if bool(row.get("main_ai_capex_momentum_tilt_applied"))]
            total_abs_delta = float(sum(abs(after.get(ticker, 0.0) - weight) for ticker, weight in before.items()))
            cash_before = float(sum(weight_value(row) for _, row in cash.iterrows()))
            cash_after = cash_before
            date_rows.append(
                {
                    "rebalance_date": date_text,
                    "stock_count": int(len(stocks)),
                    "applied_count": int(len(applied)),
                    "stock_ticker_set_preserved": set(before) == set(after),
                    "cash_weight_before": cash_before,
                    "cash_weight_after": cash_after,
                    "cash_unchanged": abs(cash_before - cash_after) <= 1e-12,
                    "stock_gross_before": float(sum(before.values())),
                    "stock_gross_after": float(sum(after.values())),
                    "total_abs_weight_delta": total_abs_delta,
                }
            )
            for row in after_records:
                ticker = clean_ticker(row.get("ticker"))
                stock_rows.append(
                    {
                        "rebalance_date": date_text,
                        "ticker": ticker,
                        "pre_weight": before.get(ticker, 0.0),
                        "post_weight": after.get(ticker, 0.0),
                        "delta": after.get(ticker, 0.0) - before.get(ticker, 0.0),
                        "applied": bool(row.get("main_ai_capex_momentum_tilt_applied")),
                        "bucket": row.get("ai_capex_value_chain_bucket", ""),
                        "bottleneck_score": row.get("ai_capex_bottleneck_score", ""),
                    }
                )
            out_groups.append(pd.concat([pd.DataFrame(after_records), cash], ignore_index=True))
    finally:
        if old_env is None:
            os.environ.pop("PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED", None)
        else:
            os.environ["PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED"] = old_env

    date_df = pd.DataFrame(date_rows)
    stock_df = pd.DataFrame(stock_rows)
    date_df.to_csv(output_dir / "date_telemetry.csv", index=False)
    stock_df.to_csv(output_dir / "stock_telemetry.csv", index=False)
    if out_groups:
        pd.concat(out_groups, ignore_index=True).to_csv(output_dir / "tilted_target_book.csv", index=False)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "target_book": str(target_book),
        "portfolio_kind": portfolio_kind,
        "research_only": True,
        "production_activation_allowed": False,
        "full_policy_replay_required_before_fullrun": True,
        "date_count": int(len(date_df)),
        "applied_event_count": int(pd.to_numeric(date_df.get("applied_count", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not date_df.empty else 0,
        "changed_date_count": int((pd.to_numeric(date_df.get("total_abs_weight_delta", pd.Series(dtype=float)), errors="coerce").fillna(0.0) > 1e-12).sum()) if not date_df.empty else 0,
        "total_abs_weight_delta": float(pd.to_numeric(date_df.get("total_abs_weight_delta", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if not date_df.empty else 0.0,
        "cash_unchanged_all_dates": bool(date_df.get("cash_unchanged", pd.Series(dtype=bool)).all()) if not date_df.empty else True,
        "ticker_set_preserved_all_dates": bool(date_df.get("stock_ticker_set_preserved", pd.Series(dtype=bool)).all()) if not date_df.empty else True,
        "status": "screen_pass_applied" if (not date_df.empty and int(date_df["applied_count"].sum()) > 0) else "blocked_no_applied_events",
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--output-dir", default="outputs/ai_capex_momentum_tilt_applied_screen")
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated"], default="main")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_screen(repo_path(args.target_book), repo_path(args.output_dir), portfolio_kind=args.portfolio_kind)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

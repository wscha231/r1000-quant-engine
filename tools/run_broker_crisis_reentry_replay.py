#!/usr/bin/env python3
"""Convert crisis-reentry target books into broker-ledger evidence.

`run_crisis_reentry_replay.py` is a monthly research sidecar. This runner takes
one of its exported policy target books and replays it through the stricter
broker-style ledger:

- next-close fills after the signal date;
- integer shares;
- cash accounting;
- transaction costs;
- daily equity and drawdown.

It does not change production defaults. It only makes the crisis cash ladder /
bargain re-entry idea comparable against the official broker-ledger metrics.
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

from tools.run_broker_ledger_replay import replay as broker_replay  # noqa: E402


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUT_DIR = "outputs/broker_crisis_reentry_replay/main"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def render_report(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Broker Crisis-Reentry Replay",
            "",
            "Broker-ledger conversion of the crisis cash ladder / bargain re-entry target book.",
            "",
            f"- Status: `{metrics.get('status')}`",
            f"- Policy: `{metrics.get('policy_id')}`",
            f"- Metric mode: `{metrics.get('metric_mode')}`",
            f"- CAGR: {safe_float(metrics.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
            f"- Avg cash: {safe_float(metrics.get('avg_cash_weight')):.2%}",
            f"- Trade count: {int(safe_float(metrics.get('trade_count')))}",
            f"- Valid for production evidence: `{str(metrics.get('valid_for_production')).lower()}`",
            "",
            "This is a broker-compatible challenger, not an automatic production promotion.",
            "",
        ]
    )


def build_target_book(latest_run: Path, output_dir: Path, policy_id: str) -> tuple[Path, dict[str, Any]]:
    holdings_path = latest_run / "crisis_reentry_replay" / "holdings.csv"
    if not holdings_path.exists():
        raise FileNotFoundError(f"missing crisis reentry holdings: {holdings_path}")
    raw = pd.read_csv(holdings_path)
    if raw.empty or "policy_id" not in raw.columns:
        raise ValueError("crisis reentry holdings must contain policy_id rows")
    d = raw[raw["policy_id"].astype(str).eq(str(policy_id))].copy()
    if d.empty:
        raise ValueError(f"policy_id={policy_id!r} not found in {holdings_path}")
    if "rebalance_date" not in d.columns or "ticker" not in d.columns or "weight" not in d.columns:
        raise ValueError("crisis reentry holdings must contain rebalance_date, ticker, weight")
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
    d = d.dropna(subset=["rebalance_date"])
    d = d[(d["ticker"] != "") & (d["weight"] > 1e-12)]
    keep = [
        col
        for col in [
            "rebalance_date",
            "ticker",
            "weight",
            "Name",
            "sector",
            "portfolio_sleeve_label",
            "portfolio_sleeve_role",
            "policy_id",
            "macro_risk_state",
            "policy_action",
        ]
        if col in d.columns
    ]
    target = d[keep].sort_values(["rebalance_date", "weight"], ascending=[True, False]).reset_index(drop=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    target_path = output_dir / "target_book.csv"
    target.to_csv(target_path, index=False)
    diagnostics = {
        "policy_id": policy_id,
        "source_holdings": str(holdings_path),
        "target_book": str(target_path),
        "rows": int(len(target)),
        "months": int(target["rebalance_date"].nunique()),
        "avg_cash_weight": float(
            target.loc[target["ticker"].eq("CASH"), "weight"].mean()
            if target["ticker"].eq("CASH").any()
            else 0.0
        ),
    }
    write_json(output_dir / "target_book_diagnostics.json", diagnostics)
    return target_path, diagnostics


def run(
    *,
    latest_run: Path,
    price_cache: Path,
    output_dir: Path,
    policy_id: str,
    starting_capital: float = 100000.0,
    fill_mode: str = "next_close",
    cost_bps: float = 25.0,
    integer_shares: bool = True,
    max_fill_lag_days: int = 7,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        target_book, diagnostics = build_target_book(latest_run, output_dir, policy_id)
    except Exception as exc:
        payload = {
            "status": "blocked",
            "reason": str(exc),
            "policy_id": policy_id,
            "latest_run": str(latest_run),
            "valid_for_production": False,
        }
        write_json(output_dir / "metrics.json", payload)
        (output_dir / "replay_report.md").write_text(render_report(payload), encoding="utf-8")
        return payload

    metrics = broker_replay(
        target_book=target_book,
        price_cache=price_cache,
        output_dir=output_dir,
        portfolio_kind="main",
        starting_capital=starting_capital,
        fill_mode=fill_mode,
        cost_bps=cost_bps,
        integer_shares=integer_shares,
        max_reasonable_weight_sum=1.05,
        max_fill_lag_days=max_fill_lag_days,
    )
    metrics.update(
        {
            "candidate_id": f"main_broker_crisis_reentry_{policy_id}",
            "data_mode": "broker_ledger_crisis_reentry_target_book",
            "policy_id": policy_id,
            "source_research_sidecar": "crisis_reentry_replay",
            "target_book": str(target_book),
            "target_book_rows": diagnostics.get("rows"),
            "target_book_months": diagnostics.get("months"),
            "target_book_avg_cash_weight": diagnostics.get("avg_cash_weight"),
            "promotion_note": "Broker-compatible challenger for crisis cash ladder / bargain re-entry. Promotion requires target gates, stress review, and human approval.",
        }
    )
    write_json(output_dir / "metrics.json", metrics)
    (output_dir / "replay_report.md").write_text(render_report(metrics), encoding="utf-8")
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--policy-id", default="fast_reentry")
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--fill-mode", choices=["next_close", "next_open", "same_close"], default="next_close")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--no-integer-shares", action="store_true")
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(
        latest_run=repo_path(args.latest_run),
        price_cache=repo_path(args.price_cache),
        output_dir=repo_path(args.output_dir),
        policy_id=args.policy_id,
        starting_capital=args.starting_capital,
        fill_mode=args.fill_mode,
        cost_bps=args.cost_bps,
        integer_shares=not args.no_integer_shares,
        max_fill_lag_days=args.max_fill_lag_days,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

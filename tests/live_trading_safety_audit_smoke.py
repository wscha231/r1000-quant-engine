#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_live_trading_safety_audit import run
from r1000_pipeline import drop_actionable_leakage_columns


class Args:
    pass


def _args(root: Path, strict: bool = False) -> Args:
    args = Args()
    args.latest_run = str(root)
    args.output_dir = str(root / "live_trading_safety")
    args.max_stale_days = 5
    args.main_max_weight_sum = 1.05
    args.main_max_single_weight = 0.33
    args.main_max_order_notional_pct = 0.35
    args.concentrated_max_weight_sum = 1.05
    args.concentrated_max_single_weight = 0.50
    args.concentrated_max_order_notional_pct = 0.60
    args.strict = strict
    return args


def _write_preview(root: Path, portfolio: str) -> None:
    out = root / "account_ledger_preview" / portfolio
    out.mkdir(parents=True)
    (out / "preview_metrics.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "as_of_date": "2026-01-10",
                "account_state_as_of_date": "2026-01-10",
                "equity_usd": 100000,
                "cash_usd": 10000,
                "integer_shares": True,
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {"ticker": "AAA", "shares": 100, "price": 100, "price_date": "2026-01-10", "market_value_usd": 10000, "current_weight": 0.10},
            {"ticker": "BBB", "shares": 0, "price": 50, "price_date": "2026-01-10", "market_value_usd": 0, "current_weight": 0.0},
        ]
    ).to_csv(out / "positions_current.csv", index=False)
    pd.DataFrame([{"ticker": "AAA", "target_weight": 0.10}, {"ticker": "BBB", "target_weight": 0.20}]).to_csv(
        out / "target_weights.csv", index=False
    )
    pd.DataFrame(
        [
            {"ticker": "AAA", "side": "SELL", "quantity": 10, "gross_value_usd": 1000, "estimated_fee_usd": 2.5, "estimated_cash_after_usd": 10997.5, "status": "ready"},
            {"ticker": "BBB", "side": "BUY", "quantity": 10, "gross_value_usd": 500, "estimated_fee_usd": 1.25, "estimated_cash_after_usd": 10496.25, "status": "ready"},
        ]
    ).to_csv(out / "orders_preview.csv", index=False)


def test_live_trading_safety_passes_clean_preview() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pd.DataFrame([{"ticker": "AAA", "weight": 0.10}, {"ticker": "BBB", "weight": 0.20}]).to_csv(root / "portfolio_latest.csv", index=False)
        pd.DataFrame([{"ticker": "AAA", "weight": 0.50}, {"ticker": "BBB", "weight": 0.50}]).to_csv(root / "concentrated_portfolio_latest.csv", index=False)
        _write_preview(root, "main")
        _write_preview(root, "concentrated")
        payload = run(_args(root))
        assert payload["status"] == "pass", payload
        assert (root / "live_trading_safety" / "safety_audit_summary.json").exists()


def test_live_trading_safety_blocks_forward_columns() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pd.DataFrame([{"ticker": "AAA", "weight": 0.10, "period_forward_return": 0.50, "forward_return_coverage_score": 1.0, "r_1m": 0.20, "bench_r_6m": 0.10}]).to_csv(root / "portfolio_latest.csv", index=False)
        pd.DataFrame([{"ticker": "AAA", "weight": 0.50}]).to_csv(root / "concentrated_portfolio_latest.csv", index=False)
        _write_preview(root, "main")
        _write_preview(root, "concentrated")
        payload = run(_args(root))
        assert payload["status"] == "blocked"
        assert any(row["check_id"] == "main_target_leakage_columns" for row in payload["issues"])


def test_actionable_export_hygiene_strips_forward_columns() -> None:
    frame = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "weight": 0.25,
                "r_1m": 0.20,
                "bench_r_12m": 0.15,
                "period_forward_return": 0.33,
                "forward_return_coverage_score": 1.0,
                "future_winner_scout_score": 0.70,
            }
        ]
    )
    out = drop_actionable_leakage_columns(frame)
    assert "r_1m" not in out.columns
    assert "bench_r_12m" not in out.columns
    assert "period_forward_return" not in out.columns
    assert "forward_return_coverage_score" not in out.columns
    assert "future_winner_scout_score" in out.columns


def main() -> int:
    test_live_trading_safety_passes_clean_preview()
    test_live_trading_safety_blocks_forward_columns()
    test_actionable_export_hygiene_strips_forward_columns()
    print("live_trading_safety_audit_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

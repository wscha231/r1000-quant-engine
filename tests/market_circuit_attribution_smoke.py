#!/usr/bin/env python3
"""Smoke test for alpha-selector market-circuit attribution."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_market_circuit_attribution import run  # noqa: E402


def test_market_circuit_attribution_emits_drawdowns_and_substitutions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        variant = latest / "alpha_selector_market_circuit_grid" / "main" / "monster_heavy_N3_cap0.5" / "ma50_caution_0p70_crisis_0p40"
        variant.mkdir(parents=True)
        base = latest / "alpha_selector_market_circuit_grid" / "main"
        pd.DataFrame(
            [
                {"date": "2026-01-02", "equity_usd": 100_000, "cash_usd": 1_000, "cash_weight": 0.01},
                {"date": "2026-01-05", "equity_usd": 92_000, "cash_usd": 2_000, "cash_weight": 0.02},
                {"date": "2026-01-06", "equity_usd": 88_000, "cash_usd": 2_000, "cash_weight": 0.02},
                {"date": "2026-01-07", "equity_usd": 101_000, "cash_usd": 1_000, "cash_weight": 0.01},
            ]
        ).to_csv(variant / "equity_curve.csv", index=False)
        pd.DataFrame(
            [
                {"date": "2026-01-02", "state": "normal", "multiplier": 1.0},
                {"date": "2026-01-05", "state": "caution", "multiplier": 0.7},
                {"date": "2026-01-06", "state": "caution", "multiplier": 0.7},
                {"date": "2026-01-07", "state": "normal", "multiplier": 1.0},
            ]
        ).to_csv(variant / "market_circuit_states.csv", index=False)
        pd.DataFrame([{"date": "2026-01-05", "event": "normal_to_caution"}]).to_csv(variant / "market_circuit_events.csv", index=False)
        pd.DataFrame([{"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 1.0}]).to_csv(
            variant / "market_circuit_target_book.csv",
            index=False,
        )
        pd.DataFrame(
            [
                {"date": "2026-01-05", "ticker": "AAA", "side": "SELL", "quantity": 10, "fill_price": 100, "gross_value": 1_000, "fee_usd": 0},
                {"date": "2026-01-06", "ticker": "BBB", "side": "BUY", "quantity": 10, "fill_price": 50, "gross_value": 500, "fee_usd": 0},
            ]
        ).to_csv(variant / "trades.csv", index=False)
        holdings = []
        for dt, aaa, bbb in [
            ("2026-01-05", 100, 50),
            ("2026-01-12", 112, 48),
            ("2026-01-26", 130, 49),
        ]:
            holdings.append({"date": dt, "ticker": "AAA", "shares": 0, "price": aaa, "market_value_usd": 0})
            holdings.append({"date": dt, "ticker": "BBB", "shares": 10, "price": bbb, "market_value_usd": bbb * 10})
        pd.DataFrame(holdings).to_csv(variant / "holdings_daily.csv", index=False)
        (variant / "metrics.json").write_text(
            '{"status":"completed","cagr":0.25,"max_dd":-0.12,"sharpe":1.2,"valid_for_production":true}\n',
            encoding="utf-8",
        )
        (base / "best_metrics.json").write_text(
            '{"target_book":"' + str(variant / "market_circuit_target_book.csv").replace("\\", "\\\\") + '","cagr":0.25,"max_dd":-0.12,"sharpe":1.2,"valid_for_production":true}\n',
            encoding="utf-8",
        )
        payload = run(latest, "main", root / "out", min_drawdown=-0.05, substitution_horizon_days=20)
        assert payload["status"] == "completed", payload
        assert payload["drawdown_period_count"] >= 1, payload
        assert payload["wrong_substitution_count"] >= 1, payload
        assert (root / "out" / "main_drawdown_periods.csv").exists()
        assert (root / "out" / "wrong_substitutions.csv").exists()


def main() -> int:
    test_market_circuit_attribution_emits_drawdowns_and_substitutions()
    print("market_circuit_attribution_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run287_forensics import run  # noqa: E402
from tools.run_broker_ledger_replay import calc_metrics  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def write_replay(root: Path, portfolio: str, end_equity: float) -> None:
    replay = root / "broker_replay" / portfolio
    equity_rows = [
        {
            "date": "2026-06-26",
            "equity_usd": 100000.0,
            "cash_usd": 20000.0,
            "cash_weight": 0.20,
            "stock_value_usd": 80000.0,
            "position_count": 2,
            "fill_mode": "next_close",
        },
        {
            "date": "2026-06-29",
            "equity_usd": 120000.0,
            "cash_usd": 24000.0,
            "cash_weight": 0.20,
            "stock_value_usd": 96000.0,
            "position_count": 2,
            "fill_mode": "next_close",
        },
        {
            "date": "2026-07-02",
            "equity_usd": end_equity,
            "cash_usd": 18000.0,
            "cash_weight": 0.20,
            "stock_value_usd": end_equity - 18000.0,
            "position_count": 2,
            "fill_mode": "next_close",
        },
    ]
    trade_rows = [
        {
            "ticker": "AAA",
            "side": "BUY",
            "quantity": 10,
            "fill_price": 100.0,
            "gross_value": 1000.0,
            "fee_usd": 1.0,
            "date": "2026-06-26",
        }
    ]
    write_csv(replay / "equity_curve.csv", equity_rows)
    write_csv(replay / "trades.csv", trade_rows)
    metrics = calc_metrics(pd.DataFrame(equity_rows), pd.DataFrame(trade_rows), 100000.0)
    metrics["starting_capital_usd"] = 100000.0
    write_json(replay / "metrics.json", metrics)


def write_books(frozen: Path, run_root: Path, portfolio: str) -> None:
    frozen_rows = [
        {"rebalance_date": "2026-06-29", "ticker": "AAA", "target_weight": 0.60, "period_forward_return": 0.10},
        {"rebalance_date": "2026-06-29", "ticker": "BBB", "target_weight": 0.40, "period_forward_return": -0.10},
    ]
    generated_rows = [
        {
            "rebalance_date": "2026-06-29",
            "ticker": "AAA",
            "target_weight": 0.20,
            "period_forward_return": 0.10,
            "main_post_selection_topn_filter_applied": True,
            "main_post_selection_topn_target_n": 14,
            "main_ai_capex_momentum_tilt_applied": True,
            "main_ai_capex_momentum_tilt_strength": 0.20,
            "concentrated_replacement_quality_applied": True,
            "concentrated_cashfunded_early_entry_applied": False,
            "concentrated_cashfunded_early_entry_add_weight": 0.058,
        },
        {
            "rebalance_date": "2026-06-29",
            "ticker": "CCC",
            "target_weight": 0.80,
            "period_forward_return": -0.20,
            "main_post_selection_topn_filter_applied": False,
            "main_post_selection_topn_target_n": 14,
            "main_ai_capex_momentum_tilt_applied": False,
            "main_ai_capex_momentum_tilt_strength": 0.20,
            "concentrated_replacement_quality_applied": False,
            "concentrated_cashfunded_early_entry_applied": True,
            "concentrated_cashfunded_early_entry_add_weight": 0.058,
        },
    ]
    write_csv(frozen / f"official_{portfolio}_target_book.csv", frozen_rows)
    write_csv(run_root / "alphaops_vnext" / f"official_{portfolio}_target_book.csv", generated_rows)


def write_sidecar_metrics(root: Path, portfolio: str) -> None:
    write_json(
        root / "generated_book_zero_yield" / portfolio / "metrics.json",
        {
            "status": "completed",
            "metric_mode": "broker_ledger_next_close",
            "start_date": "2026-06-26",
            "end_date": "2026-07-02",
            "cagr": 0.30,
            "max_dd": -0.20,
            "sharpe": 1.0,
            "avg_cash_weight": 0.2,
            "ending_capital_usd": 90000.0,
        },
    )
    write_json(
        root / "generated_book_cash_carry" / portfolio / "metrics.json",
        {
            "status": "completed",
            "metric_mode": "broker_ledger_next_close_cash_carry",
            "start_date": "2026-06-26",
            "end_date": "2026-07-02",
            "cagr": 0.34 if portfolio == "main" else 0.48,
            "max_dd": -0.24,
            "sharpe": 1.1,
            "avg_cash_weight": 0.2,
            "ending_capital_usd": 95000.0,
            "cash_interest_accrued_usd": 123.0,
        },
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_root = root / "run"
        frozen_root = root / "frozen"
        out = root / "out"
        sidecar = root / "metric_sidecar"
        macro_cache = root / "cache_macro"
        macro_cache.mkdir(parents=True)
        (macro_cache / "fred_dgs3mo_DGS3MO.parquet").write_text("fake rate cache", encoding="utf-8")
        write_json(
            run_root / "account_evaluation" / "official_metrics.json",
            {
                "official_metric_mode": "broker_ledger_next_close",
                "production_promotion_allowed": False,
                "pit_universe_label_clean": False,
            },
        )
        for portfolio, end_equity in [("main", 90000.0), ("concentrated", 95000.0)]:
            write_replay(run_root, portfolio, end_equity)
            write_books(frozen_root, run_root, portfolio)
            write_sidecar_metrics(sidecar, portfolio)
            write_json(
                frozen_root
                / ("broker_main_cash_carry" if portfolio == "main" else "broker_concentrated_cash_carry")
                / "metrics.json",
                {"metric_mode": "broker_ledger_next_close_cash_carry", "cagr": 0.50, "max_dd": -0.20, "sharpe": 1.5},
            )

        payload = run(
            run_root=run_root,
            frozen_root=frozen_root,
            output_dir=out,
            official_window_end="2026-06-29",
            actual_window_end="2026-07-02",
            price_cache=root / "missing_cache_prices",
            macro_cache=macro_cache,
            metric_sidecar_root=sidecar,
        )

        assert payload["new_fullrun_dispatched"] is False
        assert payload["production_promotion_allowed"] is False
        assert payload["cash_carry_exact_replay"]["status"] == "blocked_missing_price_cache"
        assert payload["window_attribution"]["main"]["official_metrics_reproduced"] is True
        assert payload["window_attribution"]["main"]["delta_actual_minus_clamp"]["cagr_pp"] < 0.0
        assert payload["target_book_drift"]["main"]["common_date_count"] == 1
        assert payload["target_book_drift"]["main"]["average_ticker_overlap"] < 1.0
        assert payload["hook_telemetry"]["status"] == "telemetry_only_pending_counterfactual"
        assert payload["metric_sidecar"]["status"] == "completed"
        assert payload["metric_sidecar"]["latest_generated_book_cash_carry_pass"] is False
        assert payload["decision_label"] == "alpha_candidate_rejected_on_generated_book"
        assert (out / "summary.json").exists()
        assert (out / "report.md").exists()
        assert (out / "metric_sidecar_arm_metrics.csv").exists()
        assert (sidecar / "arm_metrics.csv").exists()
        assert (sidecar / "summary.json").exists()
        assert (sidecar / "report.md").exists()
        assert (out / "window_attribution.csv").exists()
        assert (out / "date_level_drift.csv").exists()
        assert (out / "ticker_level_drift.csv").exists()
        assert (out / "hook_telemetry.csv").exists()

    print("run287_forensics_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

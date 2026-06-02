#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from argparse import Namespace
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_alphaops_vnext_policy_replay import apply_crisis_lane_policy, build, crisis_new_buy_allowed
from tools.run_weekly_evaluation import px_cache_name


def candidate_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    tickers = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    for dt in ["2026-01-31", "2026-02-28"]:
        for rank, ticker in enumerate(tickers):
            rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "Name": ticker,
                    "sector": "Technology" if rank < 4 else "Industrials",
                    "industry_group": "Semiconductors" if rank < 4 else "Machinery",
                    "rs_spy_3m": 0.05 - rank * 0.002,
                    "rs_qqq_3m": 0.04 - rank * 0.002,
                    "rs_spy_6m": 0.08 - rank * 0.003,
                    "rs_qqq_6m": 0.07 - rank * 0.003,
                    "rs_benchmark_1w": 0.02 - rank * 0.001,
                    "rs_benchmark_3m": 0.05 - rank * 0.002,
                    "rs_benchmark_6m": 0.07 - rank * 0.003,
                    "rs_semis_3m": 0.03 - rank * 0.001,
                    "relative_strength_composite": 90 - rank,
                    "industry_group_strength_score": 1.0 - rank * 0.05,
                    "portfolio_future_winner_engine_score": 1.0 - rank * 0.05,
                    "theme_phase_multiplier_primary": 1.0,
                    "dollar_vol_20d": 50_000_000,
                    "market_cap_live": 10_000_000_000,
                    "data_confidence": 1.0,
                    "price_above_ma200": 1.0,
                    "price_above_ma50": 1.0,
                    "fcf_ttm": 1_000_000_000,
                    "fcf_margin": 0.15,
                    "forward_pe": 22 + rank,
                    "peg_ratio": 1.1 + rank * 0.1,
                    "fcf_yield": 0.04,
                    "available_from": dt,
                }
            )
    rows.append(
        {
            "rebalance_date": "2026-02-28",
            "ticker": "FUT",
            "sector": "Technology",
            "industry_group": "Software",
            "top7_discovery_score": 999.0,
            "sec_13f_smart_money_score": 999.0,
            "available_from": "2026-03-15",
            "dollar_vol_20d": 100_000_000,
            "market_cap_live": 20_000_000_000,
            "data_confidence": 1.0,
            "price_above_ma200": 1.0,
            "price_above_ma50": 1.0,
        }
    )
    rows.append(
        {
            "rebalance_date": "2026-02-28",
            "ticker": "NEG",
            "sector": "Technology",
            "industry_group": "Emerging Software",
            "rs_benchmark_1w": 0.08,
            "rs_benchmark_3m": 0.15,
            "rs_benchmark_6m": 0.20,
            "theme_phase_multiplier_primary": 2.0,
            "portfolio_early_scout_engine_score": 2.0,
            "portfolio_monster_early_score": 2.0,
            "dollar_vol_20d": 80_000_000,
            "market_cap_live": 3_000_000_000,
            "data_confidence": 1.0,
            "price_above_ma200": 1.0,
            "price_above_ma50": 1.0,
            "fcf_ttm": -10_000_000,
            "fcf_margin": -0.05,
            "cash_runway_quarters": 8,
            "available_from": "2026-02-28",
        }
    )
    return rows


def write_price_cache(cache_dir: Path, tickers: set[str], latest_date: str = "2026-03-05") -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    index = pd.to_datetime(["2026-01-31", "2026-02-28", latest_date])
    for ticker in sorted(tickers):
        pd.DataFrame(
            {
                "Open": [10.0, 11.0, 12.0],
                "Close": [10.0, 11.0, 12.0],
                "Adj Close": [10.0, 11.0, 12.0],
            },
            index=index,
        ).to_parquet(cache_dir / px_cache_name(ticker))


def test_alphaops_vnext_replaces_operating_books_and_blocks_future_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        reports.mkdir(parents=True)
        candidates = candidate_rows()
        pd.DataFrame(candidates).to_csv(reports / "candidate_replay_book.csv", index=False)
        write_price_cache(
            root / "cache_prices",
            {str(row["ticker"]) for row in candidates if str(row["ticker"]) != "FUT"},
        )
        pd.DataFrame([{"rebalance_date": "2026-01-31", "ticker": "OLD", "weight": 1.0}]).to_csv(
            reports / "operating_main_target_book.csv",
            index=False,
        )
        pd.DataFrame([{"rebalance_date": "2026-01-31", "ticker": "OLD", "weight": 1.0}]).to_csv(
            reports / "operating_concentrated_target_book.csv",
            index=False,
        )

        payload = build(
            Namespace(
                latest_run=str(latest),
                candidate_book=None,
                price_cache=str(root / "cache_prices"),
                output_dir=str(latest / "alphaops_vnext"),
                portfolio_kind="both",
                main_target_n=15,
                concentrated_target_n=5,
                production_output_mode="replace_operating",
                skip_broker_replay=True,
                run_current_report=False,
                cost_bps=25.0,
                max_fill_lag_days=7,
                long_crisis_features=str(root / "missing_long_crisis.parquet"),
                long_crisis_thresholds=str(root / "missing_thresholds.json"),
            )
        )
        assert payload["status"] == "completed"
        assert payload["production_applied"] is True
        activation = json.loads((latest / "alphaops_vnext" / "production_activation.json").read_text(encoding="utf-8"))
        assert activation["current_holdings_source"] == "alphaops_vnext_policy_target_book"

        main = pd.read_csv(reports / "operating_main_target_book.csv")
        concentrated = pd.read_csv(reports / "operating_concentrated_target_book.csv")
        assert "OLD" not in set(main["ticker"].astype(str))
        assert "OLD" not in set(concentrated["ticker"].astype(str))
        assert main["rebalance_date"].min() == "2026-01-31"
        assert main["rebalance_date"].max() == "2026-03-05"
        assert concentrated["rebalance_date"].max() == "2026-03-05"
        latest_main = main[pd.to_datetime(main["rebalance_date"]).dt.date.astype(str).eq("2026-03-05")]
        assert bool(latest_main["operating_appended"].all())
        operating_summary = json.loads((reports / "operating_target_books_summary.json").read_text(encoding="utf-8"))
        assert all(row["operating_book_current"] for row in operating_summary["books"])
        assert "alphaops_vnext_policy_replay" in set(main["operating_target_source"].astype(str))
        assert "FUT" not in set(main["ticker"].astype(str))

        pit = pd.read_csv(latest / "alphaops_vnext" / "pit_evidence_audit.csv")
        assert "FUT" in set(pit["ticker"].astype(str))
        lane = pd.read_csv(latest / "alphaops_vnext" / "lane_scores_history.csv")
        neg = lane[lane["ticker"].astype(str).eq("NEG")]
        assert not neg.empty
        assert float(neg["emerging_tenbagger_risk_cap"].iloc[0]) < 1.0


def test_alphaops_vnext_applies_crisis_lane_new_buy_blocks() -> None:
    frame = pd.DataFrame(
        [
            {
                "ticker": "CYC",
                "primary_lane": "CYCLICAL_RECOVERY",
                "alphaops_vnext_score": 10.0,
                "leader_chase_risk_score": 0.0,
                "liquidity_capacity_weight_cap": 1.0,
                "atr14_pct": 0.02,
            },
            {
                "ticker": "QLT",
                "primary_lane": "QUALITY_COMPOUNDER",
                "alphaops_vnext_score": 5.0,
                "leader_chase_risk_score": 0.0,
                "liquidity_capacity_weight_cap": 1.0,
                "atr14_pct": 0.02,
            },
        ]
    )
    out = apply_crisis_lane_policy(frame, {"crisis_state": "CRISIS_DEFENSE"}, "main")
    cyc = out[out["ticker"].eq("CYC")].iloc[0]
    qlt = out[out["ticker"].eq("QLT")].iloc[0]
    assert bool(cyc["crisis_new_buy_allowed"]) is False
    assert "CRISIS_DEFENSE:CYCLICAL_RECOVERY" in str(cyc["crisis_new_buy_block_reason"])
    assert bool(qlt["crisis_new_buy_allowed"]) is True
    assert float(cyc["alphaops_vnext_weight_score"]) < float(cyc["alphaops_vnext_score"])
    assert float(qlt["alphaops_vnext_weight_score"]) > float(cyc["alphaops_vnext_weight_score"])
    ok, reason = crisis_new_buy_allowed(cyc.to_dict(), "CRISIS_DEFENSE")
    assert ok is False
    assert reason.startswith("crisis_new_buy_blocked_for_lane")


if __name__ == "__main__":
    test_alphaops_vnext_replaces_operating_books_and_blocks_future_evidence()
    print("alphaops_vnext_policy_replay_smoke: PASS")

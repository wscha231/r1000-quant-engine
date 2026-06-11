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

from tools.run_alphaops_vnext_policy_replay import (
    DEFAULT_CONCENTRATED_TARGET_N,
    apply_concentrated_defense_neutral_quality_new_entry_cap,
    apply_concentrated_green_benchmark_risk_cyclical_new_entry_block,
    apply_concentrated_hold_decay_trim,
    apply_concentrated_risk_state_new_entry_cap,
    apply_concentrated_green_bull_qqq_down_new_entry_cap,
    apply_concentrated_green_consumer_overheat_new_entry_cap,
    apply_concentrated_green_confirmed_market_leader_weak_rs_new_entry_cap,
    apply_concentrated_green_neutral_cyclical_high_vol_new_entry_cap,
    apply_concentrated_high_vol_weak_timing_new_entry_cap,
    apply_concentrated_unconfirmed_high_vol_new_entry_cap,
    apply_concentrated_unconfirmed_quality_bull_new_entry_cap,
    apply_concentrated_watch_damaged_weak_market_leader_cap,
    apply_concentrated_watch_unconfirmed_high_vol_new_entry_cap,
    apply_concentrated_watch_unconfirmed_market_leader_new_entry_cap,
    apply_crisis_lane_policy,
    apply_main_balanced_bull_qqq_damage_low_confirm_leader_cap,
    apply_main_balanced_neutral_soft_qqq_damage_weak_leader_cap,
    apply_main_defense_review_balanced_new_entry_block,
    apply_main_green_bull_low_confirm_high_vol_new_entry_cap,
    apply_main_green_neutral_cyclical_high_vol_new_entry_cap,
    apply_main_defense_review_turnaround_new_entry_block,
    apply_main_high_volatility_new_entry_cap,
    apply_main_cash_count_structure,
    apply_main_neutral_regime_churn_filter,
    apply_main_quality_bull_low_confirm_new_entry_cap,
    apply_main_quality_hold_weak_timing_trim,
    apply_main_watch_unconfirmed_market_leader_new_entry_cap,
    apply_neutral_metals_new_entry_block,
    build,
    crisis_new_buy_allowed,
    enforce_pit_available,
    evidence_support_score,
)
from tools.run_market_leader_challenger import resolve_candidate_book
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
                    "regime_state": "bear" if dt == "2026-02-28" else "neutral",
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
            "regime_state": "bear",
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
            "regime_state": "bear",
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
        enriched = pd.DataFrame(candidates)
        enriched["sec_13f_smart_money_score"] = 0.0
        enriched["smart_money_shadow_score"] = 0.0
        enriched["evidence_fusion_score"] = 0.0
        enriched.loc[enriched["ticker"].astype(str).eq("AAA"), "sec_13f_smart_money_score"] = 10.0
        enriched.loc[enriched["ticker"].astype(str).eq("AAA"), "smart_money_shadow_score"] = 8.0
        enriched.loc[enriched["ticker"].astype(str).eq("AAA"), "evidence_fusion_score"] = 6.0
        enriched["latest_13f_available_from"] = enriched["rebalance_date"]
        enriched_dir = latest / "sec_enriched_candidate_replay"
        enriched_dir.mkdir(parents=True)
        enriched.to_csv(enriched_dir / "candidate_replay_book_sec_enriched.csv", index=False)
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
        assert payload["candidate_source_mode"] == "sec_enriched_candidate_book"
        selected_candidate, source_mode = resolve_candidate_book(latest, None)
        assert source_mode == "sec_enriched_candidate_book"
        assert selected_candidate.name == "candidate_replay_book_sec_enriched.csv"
        activation = json.loads((latest / "alphaops_vnext" / "production_activation.json").read_text(encoding="utf-8"))
        assert activation["current_holdings_source"] == "alphaops_vnext_policy_target_book"
        assert activation["candidate_source_mode"] == "sec_enriched_candidate_book"
        assert activation["candidate_book"].endswith("candidate_replay_book_sec_enriched.csv")

        main = pd.read_csv(reports / "operating_main_target_book.csv")
        concentrated = pd.read_csv(reports / "operating_concentrated_target_book.csv")
        for book in (main, concentrated):
            assert "sec_13f_smart_money_score" in book.columns
            assert "smart_money_shadow_score" in book.columns
            assert "evidence_fusion_score" in book.columns
            assert "evidence_support_score" in book.columns
        assert pd.to_numeric(
            main.loc[main["ticker"].astype(str).eq("AAA"), "sec_13f_smart_money_score"],
            errors="coerce",
        ).max() == 10.0
        assert "OLD" not in set(main["ticker"].astype(str))
        assert "OLD" not in set(concentrated["ticker"].astype(str))
        assert main["rebalance_date"].min() == "2026-01-31"
        assert main["rebalance_date"].max() == "2026-03-05"
        assert concentrated["rebalance_date"].max() == "2026-03-05"
        assert float(main[~main["ticker"].astype(str).eq("CASH")]["effective_single_weight_cap"].dropna().max()) <= 0.120001
        assert float(concentrated[~concentrated["ticker"].astype(str).eq("CASH")]["effective_single_weight_cap"].dropna().max()) <= 0.300001
        latest_main = main[pd.to_datetime(main["rebalance_date"]).dt.date.astype(str).eq("2026-03-05")]
        assert bool(latest_main["operating_appended"].all())
        latest_concentrated = concentrated[pd.to_datetime(concentrated["rebalance_date"]).dt.date.astype(str).eq("2026-03-05")]
        latest_concentrated_stock = latest_concentrated[~latest_concentrated["ticker"].astype(str).eq("CASH")]
        assert not latest_concentrated_stock.empty
        assert set(latest_concentrated_stock["regime_capacity_regime"].astype(str)) == {"bear"}
        assert set(round(float(x), 2) for x in latest_concentrated_stock["regime_capacity_multiplier"]) == {0.5}
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


def test_sec_available_from_columns_are_pit_checked_and_positive_only() -> None:
    frame = pd.DataFrame(
        [
            {
                "rebalance_date": "2026-02-28",
                "ticker": "FUT",
                "sec_13f_smart_money_score": 10.0,
                "latest_13f_available_from": "2026-03-15T18:00:00Z",
            },
            {
                "rebalance_date": "2026-02-28",
                "ticker": "OK",
                "sec_13f_smart_money_score": 4.0,
                "latest_13f_available_from": "2026-02-15T18:00:00+00:00",
            },
            {
                "rebalance_date": "2026-02-28",
                "ticker": "MISS",
            },
        ]
    )
    checked, audit = enforce_pit_available(frame)
    by_ticker = {row["ticker"]: row for row in checked.to_dict("records")}
    assert by_ticker["FUT"]["pit_evidence_blocked"] is True
    assert by_ticker["FUT"]["sec_13f_smart_money_score"] == 0.0
    assert by_ticker["OK"]["pit_evidence_blocked"] is False
    assert by_ticker["OK"]["sec_13f_smart_money_score"] == 4.0
    assert len(audit) == 1

    support = evidence_support_score(checked)
    assert float(support.loc[checked["ticker"].eq("OK")].iloc[0]) > 0.0
    assert float(support.loc[checked["ticker"].eq("FUT")].iloc[0]) == 0.0
    assert float(support.loc[checked["ticker"].eq("MISS")].iloc[0]) == 0.0


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


def test_alphaops_vnext_concentrated_production_default_is_n5() -> None:
    assert DEFAULT_CONCENTRATED_TARGET_N == 5


def test_concentrated_risk_state_caps_new_entries_only() -> None:
    selected = [
        {
            "ticker": "RISK",
            "weight": 0.30,
            "target_weight": 0.30,
            "crisis_state": "WATCH",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "KEEP",
            "weight": 0.30,
            "target_weight": 0.30,
            "crisis_state": "WATCH",
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
    ]
    capped = apply_concentrated_risk_state_new_entry_cap(selected, "concentrated")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["RISK"]["weight"] == 0.20
    assert by_ticker["RISK"]["target_weight"] == 0.20
    assert by_ticker["RISK"]["risk_state_new_entry_cap_status"] == "applied"
    assert by_ticker["KEEP"]["weight"] == 0.30
    main = apply_concentrated_risk_state_new_entry_cap(selected, "main")
    assert main[0]["weight"] == 0.30


def test_main_neutral_churn_filter_blocks_reentries_and_rebuilds_cash() -> None:
    rows = [
        ("2024-01-31", "CHURNY", 0.30, "neutral"),
        ("2024-01-31", "STABLE", 0.30, "neutral"),
        ("2024-01-31", "CASH", 0.40, "neutral"),
        ("2024-02-29", "STABLE", 0.30, "neutral"),
        ("2024-02-29", "CASH", 0.70, "neutral"),
        ("2024-03-31", "CHURNY", 0.30, "neutral"),
        ("2024-03-31", "STABLE", 0.30, "neutral"),
        ("2024-03-31", "CASH", 0.40, "neutral"),
        ("2024-04-30", "STABLE", 0.30, "neutral"),
        ("2024-04-30", "CASH", 0.70, "neutral"),
        ("2024-05-31", "CHURNY", 0.30, "neutral"),
        ("2024-05-31", "STABLE", 0.30, "neutral"),
        ("2024-05-31", "CASH", 0.40, "neutral"),
        ("2024-06-28", "STABLE", 0.30, "neutral"),
        ("2024-06-28", "CASH", 0.70, "neutral"),
        ("2024-07-31", "CHURNY", 0.30, "neutral"),
        ("2024-07-31", "STABLE", 0.50, "neutral"),
        ("2024-07-31", "CASH", 0.20, "neutral"),
    ]
    book = pd.DataFrame(
        [
            {
                "rebalance_date": date,
                "ticker": ticker,
                "weight": weight,
                "target_weight": weight,
                "regime_state": regime,
                "primary_lane": "MARKET_LEADER" if ticker != "CASH" else "CASH",
                "selection_reason": "test",
            }
            for date, ticker, weight, regime in rows
        ]
    )
    filtered, payload = apply_main_neutral_regime_churn_filter(book, "main")
    last = filtered[filtered["rebalance_date"].astype(str).eq("2024-07-31")]
    assert "CHURNY" not in set(last["ticker"].astype(str))
    assert "STABLE" in set(last["ticker"].astype(str))
    assert float(last.loc[last["ticker"].astype(str).eq("CASH"), "weight"].iloc[0]) == 0.50
    assert payload["status"] == "completed"
    assert payload["stock_rows_removed"] == 2
    assert payload["neutral_entries_blocked"] == 2
    assert payload["cash_rebuilt_explicitly"] is True
    concentrated, concentrated_payload = apply_main_neutral_regime_churn_filter(book, "concentrated")
    assert len(concentrated) == len(book)
    assert concentrated_payload["status"] == "skipped"


def test_neutral_metals_new_entry_block_removes_new_entries_and_rebuilds_cash() -> None:
    book = pd.DataFrame(
        [
            {
                "rebalance_date": "2025-06-30",
                "ticker": "BLOCK",
                "weight": 0.30,
                "target_weight": 0.30,
                "sector": "Materials",
                "industry_group": "Metals & Mining",
                "primary_lane": "MARKET_LEADER",
                "market_style_regime_label": "quality_compounder",
                "regime_state": "neutral",
                "holding_state": "NEW",
                "hold_replace_decision": "new_entry",
                "prior_weight": 0.0,
                "selection_reason": "MARKET_LEADER",
            },
            {
                "rebalance_date": "2025-06-30",
                "ticker": "KEEPHOLD",
                "weight": 0.20,
                "target_weight": 0.20,
                "sector": "Materials",
                "industry_group": "Metals & Mining",
                "primary_lane": "MARKET_LEADER",
                "market_style_regime_label": "quality_compounder",
                "regime_state": "neutral",
                "holding_state": "HOLD",
                "hold_replace_decision": "keep_prior_holding",
                "prior_weight": 0.20,
                "selection_reason": "MARKET_LEADER",
            },
            {
                "rebalance_date": "2025-06-30",
                "ticker": "KEEPTECH",
                "weight": 0.25,
                "target_weight": 0.25,
                "sector": "Information Technology",
                "industry_group": "Semiconductors",
                "primary_lane": "MARKET_LEADER",
                "market_style_regime_label": "quality_compounder",
                "regime_state": "neutral",
                "holding_state": "NEW",
                "hold_replace_decision": "new_entry",
                "prior_weight": 0.0,
                "selection_reason": "MARKET_LEADER",
            },
            {
                "rebalance_date": "2025-06-30",
                "ticker": "CASH",
                "weight": 0.25,
                "target_weight": 0.25,
                "sector": "Cash",
                "industry_group": "",
                "primary_lane": "CASH",
                "market_style_regime_label": "quality_compounder",
                "regime_state": "neutral",
                "holding_state": "CASH",
                "hold_replace_decision": "",
                "prior_weight": 0.25,
                "selection_reason": "cash",
            },
        ]
    )
    filtered, payload = apply_neutral_metals_new_entry_block(book, "main")
    tickers = set(filtered["ticker"].astype(str))
    assert "BLOCK" not in tickers
    assert "KEEPHOLD" in tickers
    assert "KEEPTECH" in tickers
    cash_weight = float(filtered.loc[filtered["ticker"].astype(str).eq("CASH"), "weight"].iloc[0])
    assert abs(cash_weight - 0.55) < 1e-12
    assert payload["status"] == "completed"
    assert payload["blocked_new_entries"] == 1
    assert payload["stock_rows_removed"] == 1
    assert payload["weight_dropped_total"] == 0.30
    assert payload["cash_rebuilt_explicitly"] is True

    concentrated, concentrated_payload = apply_neutral_metals_new_entry_block(book, "concentrated")
    assert "BLOCK" not in set(concentrated["ticker"].astype(str))
    assert concentrated_payload["portfolio"] == "concentrated"
    assert concentrated_payload["blocked_new_entries"] == 1


def test_concentrated_green_benchmark_risk_cyclical_block_is_narrow() -> None:
    book = pd.DataFrame(
        [
            {
                "rebalance_date": "2022-03-31",
                "ticker": "BLOCK",
                "weight": 0.08,
                "target_weight": 0.08,
                "sector": "Materials",
                "industry_group": "Chemicals",
                "primary_lane": "MARKET_LEADER",
                "market_style_regime_label": "quality_compounder",
                "regime_state": "neutral",
                "crisis_state": "GREEN",
                "benchmark_risk_score": 2.0,
                "atr14_pct": 0.12,
                "breakout_setup_quality_score": 0.30,
                "holding_state": "NEW",
                "hold_replace_decision": "new_entry",
                "prior_weight": 0.0,
                "selection_reason": "MARKET_LEADER",
            },
            {
                "rebalance_date": "2022-03-31",
                "ticker": "KEEPHOLD",
                "weight": 0.12,
                "target_weight": 0.12,
                "sector": "Materials",
                "industry_group": "Chemicals",
                "primary_lane": "MARKET_LEADER",
                "market_style_regime_label": "quality_compounder",
                "regime_state": "neutral",
                "crisis_state": "GREEN",
                "benchmark_risk_score": 2.0,
                "atr14_pct": 0.12,
                "breakout_setup_quality_score": 0.30,
                "holding_state": "HOLD",
                "hold_replace_decision": "keep_prior_holding",
                "prior_weight": 0.12,
                "selection_reason": "MARKET_LEADER",
            },
            {
                "rebalance_date": "2022-03-31",
                "ticker": "KEEPLOWRISK",
                "weight": 0.08,
                "target_weight": 0.08,
                "sector": "Materials",
                "industry_group": "Chemicals",
                "primary_lane": "MARKET_LEADER",
                "market_style_regime_label": "quality_compounder",
                "regime_state": "neutral",
                "crisis_state": "GREEN",
                "benchmark_risk_score": 0.30,
                "atr14_pct": 0.12,
                "breakout_setup_quality_score": 0.30,
                "holding_state": "NEW",
                "hold_replace_decision": "new_entry",
                "prior_weight": 0.0,
                "selection_reason": "MARKET_LEADER",
            },
            {
                "rebalance_date": "2022-03-31",
                "ticker": "CASH",
                "weight": 0.72,
                "target_weight": 0.72,
                "sector": "Cash",
                "industry_group": "",
                "primary_lane": "CASH",
                "market_style_regime_label": "quality_compounder",
                "regime_state": "neutral",
                "crisis_state": "GREEN",
                "benchmark_risk_score": 0.0,
                "atr14_pct": 0.0,
                "breakout_setup_quality_score": 1.0,
                "holding_state": "CASH",
                "hold_replace_decision": "",
                "prior_weight": 0.72,
                "selection_reason": "cash",
            },
        ]
    )
    filtered, payload = apply_concentrated_green_benchmark_risk_cyclical_new_entry_block(book, "concentrated")
    tickers = set(filtered["ticker"].astype(str))
    assert "BLOCK" not in tickers
    assert "KEEPHOLD" in tickers
    assert "KEEPLOWRISK" in tickers
    cash_weight = float(filtered.loc[filtered["ticker"].astype(str).eq("CASH"), "weight"].iloc[0])
    assert abs(cash_weight - 0.80) < 1e-12
    assert payload["status"] == "completed"
    assert payload["blocked_new_entries"] == 1
    assert payload["weight_dropped_total"] == 0.08

    main, main_payload = apply_concentrated_green_benchmark_risk_cyclical_new_entry_block(book, "main")
    assert len(main) == len(book)
    assert main_payload["status"] == "skipped"


def test_main_defense_review_turnaround_new_entry_block_preserves_holds() -> None:
    book = pd.DataFrame(
        [
            {
                "rebalance_date": "2022-11-30",
                "ticker": "BLOCK",
                "weight": 0.05,
                "target_weight": 0.05,
                "sector": "Communication",
                "industry_group": "Internet Content & Information",
                "primary_lane": "QUALITY_COMPOUNDER",
                "market_style_regime_label": "turnaround_accumulation",
                "regime_state": "neutral",
                "crisis_state": "DEFENSE_REVIEW",
                "holding_state": "NEW",
                "hold_replace_decision": "new_entry",
                "prior_weight": 0.0,
                "selection_reason": "QUALITY_COMPOUNDER",
            },
            {
                "rebalance_date": "2022-11-30",
                "ticker": "KEEPHOLD",
                "weight": 0.10,
                "target_weight": 0.10,
                "sector": "Information Technology",
                "industry_group": "Semiconductors",
                "primary_lane": "QUALITY_COMPOUNDER",
                "market_style_regime_label": "turnaround_accumulation",
                "regime_state": "neutral",
                "crisis_state": "DEFENSE_REVIEW",
                "holding_state": "HOLD",
                "hold_replace_decision": "keep_prior_holding",
                "prior_weight": 0.03,
                "selection_reason": "QUALITY_COMPOUNDER",
            },
            {
                "rebalance_date": "2022-11-30",
                "ticker": "KEEPGREEN",
                "weight": 0.05,
                "target_weight": 0.05,
                "sector": "Information Technology",
                "industry_group": "Software",
                "primary_lane": "QUALITY_COMPOUNDER",
                "market_style_regime_label": "turnaround_accumulation",
                "regime_state": "neutral",
                "crisis_state": "GREEN",
                "holding_state": "NEW",
                "hold_replace_decision": "new_entry",
                "prior_weight": 0.0,
                "selection_reason": "QUALITY_COMPOUNDER",
            },
            {
                "rebalance_date": "2022-11-30",
                "ticker": "CASH",
                "weight": 0.80,
                "target_weight": 0.80,
                "sector": "Cash",
                "industry_group": "",
                "primary_lane": "CASH",
                "market_style_regime_label": "turnaround_accumulation",
                "regime_state": "neutral",
                "crisis_state": "DEFENSE_REVIEW",
                "holding_state": "CASH",
                "hold_replace_decision": "",
                "prior_weight": 0.80,
                "selection_reason": "cash",
            },
        ]
    )
    filtered, payload = apply_main_defense_review_turnaround_new_entry_block(book, "main")
    tickers = set(filtered["ticker"].astype(str))
    assert "BLOCK" not in tickers
    assert "KEEPHOLD" in tickers
    assert "KEEPGREEN" in tickers
    cash_weight = float(filtered.loc[filtered["ticker"].astype(str).eq("CASH"), "weight"].iloc[0])
    assert abs(cash_weight - 0.85) < 1e-12
    assert payload["status"] == "completed"
    assert payload["blocked_new_entries"] == 1
    assert payload["weight_dropped_total"] == 0.05

    concentrated, concentrated_payload = apply_main_defense_review_turnaround_new_entry_block(book, "concentrated")
    assert len(concentrated) == len(book)
    assert concentrated_payload["status"] == "skipped"


def test_main_defense_review_balanced_new_entry_block_preserves_existing_positions() -> None:
    book = pd.DataFrame(
        [
            {
                "rebalance_date": "2023-04-28",
                "ticker": "BLOCK",
                "weight": 0.05,
                "target_weight": 0.05,
                "sector": "Consumer Discretionary",
                "industry_group": "Hotels Restaurants & Leisure",
                "primary_lane": "QUALITY_COMPOUNDER",
                "market_style_regime_label": "balanced",
                "regime_state": "neutral",
                "crisis_state": "DEFENSE_REVIEW",
                "breakout_setup_quality_score": 0.20,
                "holding_state": "NEW",
                "hold_replace_decision": "new_entry",
                "prior_weight": 0.0,
                "selection_reason": "QUALITY_COMPOUNDER",
            },
            {
                "rebalance_date": "2023-04-28",
                "ticker": "KEEPWARNING",
                "weight": 0.05,
                "target_weight": 0.05,
                "sector": "Financials",
                "industry_group": "Consumer Finance",
                "primary_lane": "QUALITY_COMPOUNDER",
                "market_style_regime_label": "balanced",
                "regime_state": "neutral",
                "crisis_state": "DEFENSE_REVIEW",
                "breakout_setup_quality_score": 0.20,
                "holding_state": "WARNING",
                "hold_replace_decision": "keep_prior_holding",
                "prior_weight": 0.02,
                "selection_reason": "QUALITY_COMPOUNDER",
            },
            {
                "rebalance_date": "2023-04-28",
                "ticker": "KEEPGOOD",
                "weight": 0.05,
                "target_weight": 0.05,
                "sector": "Information Technology",
                "industry_group": "Software",
                "primary_lane": "QUALITY_COMPOUNDER",
                "market_style_regime_label": "balanced",
                "regime_state": "neutral",
                "crisis_state": "DEFENSE_REVIEW",
                "breakout_setup_quality_score": 0.70,
                "holding_state": "NEW",
                "hold_replace_decision": "new_entry",
                "prior_weight": 0.0,
                "selection_reason": "QUALITY_COMPOUNDER",
            },
            {
                "rebalance_date": "2023-04-28",
                "ticker": "KEEPGREEN",
                "weight": 0.05,
                "target_weight": 0.05,
                "sector": "Information Technology",
                "industry_group": "Software",
                "primary_lane": "QUALITY_COMPOUNDER",
                "market_style_regime_label": "balanced",
                "regime_state": "neutral",
                "crisis_state": "GREEN",
                "breakout_setup_quality_score": 0.20,
                "holding_state": "NEW",
                "hold_replace_decision": "new_entry",
                "prior_weight": 0.0,
                "selection_reason": "QUALITY_COMPOUNDER",
            },
            {
                "rebalance_date": "2023-04-28",
                "ticker": "CASH",
                "weight": 0.80,
                "target_weight": 0.80,
                "sector": "Cash",
                "industry_group": "",
                "primary_lane": "CASH",
                "market_style_regime_label": "balanced",
                "regime_state": "neutral",
                "crisis_state": "DEFENSE_REVIEW",
                "breakout_setup_quality_score": 1.0,
                "holding_state": "CASH",
                "hold_replace_decision": "",
                "prior_weight": 0.80,
                "selection_reason": "cash",
            },
        ]
    )
    filtered, payload = apply_main_defense_review_balanced_new_entry_block(book, "main")
    tickers = set(filtered["ticker"].astype(str))
    assert "BLOCK" not in tickers
    assert "KEEPWARNING" in tickers
    assert "KEEPGOOD" in tickers
    assert "KEEPGREEN" in tickers
    cash_weight = float(filtered.loc[filtered["ticker"].astype(str).eq("CASH"), "weight"].iloc[0])
    assert abs(cash_weight - 0.85) < 1e-12
    assert payload["status"] == "completed"
    assert payload["blocked_new_entries"] == 1
    assert payload["weight_dropped_total"] == 0.05

    concentrated, concentrated_payload = apply_main_defense_review_balanced_new_entry_block(book, "concentrated")
    assert len(concentrated) == len(book)
    assert concentrated_payload["status"] == "skipped"


def test_main_high_volatility_cap_applies_to_new_market_leaders_only() -> None:
    selected = [
        {
            "ticker": "RISK",
            "weight": 0.12,
            "target_weight": 0.12,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "atr14_pct": 0.08,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "KEEP",
            "weight": 0.12,
            "target_weight": 0.12,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "atr14_pct": 0.08,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "QUALITY",
            "weight": 0.12,
            "target_weight": 0.12,
            "primary_lane": "QUALITY_COMPOUNDER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "atr14_pct": 0.08,
            "selection_reason": "QUALITY_COMPOUNDER",
        },
        {
            "ticker": "LOWVOL",
            "weight": 0.12,
            "target_weight": 0.12,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "atr14_pct": 0.04,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "EXEMPT",
            "weight": 0.12,
            "target_weight": 0.12,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "atr14_pct": 0.07,
            "crisis_state": "GREEN",
            "market_style_regime_label": "quality_compounder",
            "selection_confirmation_score": 1.0,
            "alphaops_vnext_score": 4.90,
            "sec_combined_evidence_score": 0.25,
            "rs_benchmark_1m": 0.50,
            "selection_reason": "MARKET_LEADER",
        },
    ]
    capped = apply_main_high_volatility_new_entry_cap(selected, "main")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["RISK"]["weight"] == 0.08
    assert by_ticker["RISK"]["target_weight"] == 0.08
    assert by_ticker["RISK"]["main_high_vol_new_entry_cap_status"] == "applied"
    assert by_ticker["KEEP"]["weight"] == 0.12
    assert by_ticker["QUALITY"]["weight"] == 0.12
    assert by_ticker["LOWVOL"]["weight"] == 0.12
    assert by_ticker["EXEMPT"]["weight"] == 0.12
    assert by_ticker["EXEMPT"]["main_high_vol_new_entry_cap_status"] == "exempt_high_conviction_stable_leader"
    concentrated = apply_main_high_volatility_new_entry_cap(selected, "concentrated")
    assert concentrated[0]["weight"] == 0.12


def test_main_watch_unconfirmed_market_leader_cap_applies_to_neutral_watch_new_entries_only() -> None:
    selected = [
        {
            "ticker": "CAP",
            "weight": 0.12,
            "target_weight": 0.12,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "WATCH",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.24,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "CONFIRMED",
            "weight": 0.12,
            "target_weight": 0.12,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "WATCH",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "neutral",
            "selection_confirmation_score": 1.0,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "BULL",
            "weight": 0.12,
            "target_weight": 0.12,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "WATCH",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "bull",
            "selection_confirmation_score": 0.24,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "QUALITY",
            "weight": 0.12,
            "target_weight": 0.12,
            "primary_lane": "QUALITY_COMPOUNDER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "WATCH",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.24,
            "selection_reason": "QUALITY_COMPOUNDER",
        },
    ]
    capped = apply_main_watch_unconfirmed_market_leader_new_entry_cap(selected, "main")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["CAP"]["weight"] == 0.04
    assert by_ticker["CAP"]["target_weight"] == 0.04
    assert by_ticker["CAP"]["main_watch_unconfirmed_ml_new_entry_cap_status"] == "applied"
    assert by_ticker["CONFIRMED"]["weight"] == 0.12
    assert by_ticker["BULL"]["weight"] == 0.12
    assert by_ticker["QUALITY"]["weight"] == 0.12
    concentrated = apply_main_watch_unconfirmed_market_leader_new_entry_cap(selected, "concentrated")
    assert concentrated[0]["weight"] == 0.12


def test_main_green_neutral_cyclical_high_vol_cap_applies_to_new_energy_materials_only() -> None:
    selected = [
        {
            "ticker": "CAP",
            "weight": 0.08,
            "target_weight": 0.08,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "regime_state": "neutral",
            "sector": "Energy",
            "atr14_pct": 0.15,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "LOW_VOL",
            "weight": 0.08,
            "target_weight": 0.08,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "regime_state": "neutral",
            "sector": "Materials",
            "atr14_pct": 0.04,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "TECH",
            "weight": 0.08,
            "target_weight": 0.08,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "regime_state": "neutral",
            "sector": "Information Technology",
            "atr14_pct": 0.15,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "WATCH",
            "weight": 0.08,
            "target_weight": 0.08,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "WATCH",
            "regime_state": "neutral",
            "sector": "Energy",
            "atr14_pct": 0.15,
            "selection_reason": "MARKET_LEADER",
        },
    ]
    capped = apply_main_green_neutral_cyclical_high_vol_new_entry_cap(selected, "main")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["CAP"]["weight"] == 0.01
    assert by_ticker["CAP"]["target_weight"] == 0.01
    assert by_ticker["CAP"]["main_green_neutral_cyclical_high_vol_new_entry_cap_status"] == "applied"
    assert by_ticker["LOW_VOL"]["weight"] == 0.08
    assert by_ticker["TECH"]["weight"] == 0.08
    assert by_ticker["WATCH"]["weight"] == 0.08
    concentrated = apply_main_green_neutral_cyclical_high_vol_new_entry_cap(selected, "concentrated")
    assert concentrated[0]["weight"] == 0.08


def test_main_green_bull_low_confirm_high_vol_cap_applies_to_new_market_leaders_only() -> None:
    selected = [
        {
            "ticker": "CAP",
            "weight": 0.08,
            "target_weight": 0.08,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "regime_state": "bull",
            "atr14_pct": 0.08,
            "selection_confirmation_score": 0.25,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "CONFIRMED",
            "weight": 0.08,
            "target_weight": 0.08,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "regime_state": "bull",
            "atr14_pct": 0.08,
            "selection_confirmation_score": 1.0,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "LOWVOL",
            "weight": 0.08,
            "target_weight": 0.08,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "regime_state": "bull",
            "atr14_pct": 0.04,
            "selection_confirmation_score": 0.25,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "NEUTRAL",
            "weight": 0.08,
            "target_weight": 0.08,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "regime_state": "neutral",
            "atr14_pct": 0.08,
            "selection_confirmation_score": 0.25,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "HOLD",
            "weight": 0.08,
            "target_weight": 0.08,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "crisis_state": "GREEN",
            "regime_state": "bull",
            "atr14_pct": 0.08,
            "selection_confirmation_score": 0.25,
            "selection_reason": "MARKET_LEADER",
        },
    ]
    capped = apply_main_green_bull_low_confirm_high_vol_new_entry_cap(selected, "main")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["CAP"]["weight"] == 0.05
    assert by_ticker["CAP"]["target_weight"] == 0.05
    assert by_ticker["CAP"]["main_green_bull_low_confirm_high_vol_new_entry_cap_status"] == "applied"
    assert by_ticker["CONFIRMED"]["weight"] == 0.08
    assert by_ticker["LOWVOL"]["weight"] == 0.08
    assert by_ticker["NEUTRAL"]["weight"] == 0.08
    assert by_ticker["HOLD"]["weight"] == 0.08
    concentrated = apply_main_green_bull_low_confirm_high_vol_new_entry_cap(selected, "concentrated")
    assert concentrated[0]["weight"] == 0.08


def test_main_balanced_bull_qqq_damage_low_confirm_leader_cap_applies_narrowly() -> None:
    selected = [
        {
            "ticker": "NEWCAP",
            "weight": 0.08,
            "target_weight": 0.08,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "balanced",
            "regime_state": "bull",
            "sector": "Information Technology",
            "selection_confirmation_score": 0.24,
            "volatility_contraction_score": -0.20,
            "spy_1m_return": 0.03,
            "qqq_1m_return": 0.01,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "HOLDCAP",
            "weight": 0.09,
            "target_weight": 0.09,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "crisis_state": "GREEN",
            "market_style_regime_label": "balanced",
            "regime_capacity_regime": "bull",
            "sector": "Industrials",
            "selection_confirmation_score": 0.24,
            "volatility_contraction_score": -0.02,
            "spy_1m_return": 0.03,
            "qqq_1m_return": 0.01,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "QQQLEADS",
            "weight": 0.08,
            "target_weight": 0.08,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "balanced",
            "regime_state": "bull",
            "sector": "Information Technology",
            "selection_confirmation_score": 0.24,
            "volatility_contraction_score": -0.20,
            "spy_1m_return": 0.01,
            "qqq_1m_return": 0.03,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "CONFIRMED",
            "weight": 0.08,
            "target_weight": 0.08,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "balanced",
            "regime_state": "bull",
            "sector": "Information Technology",
            "selection_confirmation_score": 1.0,
            "volatility_contraction_score": -0.20,
            "spy_1m_return": 0.03,
            "qqq_1m_return": 0.01,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "SMALL",
            "weight": 0.04,
            "target_weight": 0.04,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "balanced",
            "regime_state": "bull",
            "sector": "Industrials",
            "selection_confirmation_score": 0.24,
            "volatility_contraction_score": -0.20,
            "spy_1m_return": 0.03,
            "qqq_1m_return": 0.01,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "SECTOR",
            "weight": 0.08,
            "target_weight": 0.08,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "balanced",
            "regime_state": "bull",
            "sector": "Health Care",
            "selection_confirmation_score": 0.24,
            "volatility_contraction_score": -0.20,
            "spy_1m_return": 0.03,
            "qqq_1m_return": 0.01,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "NOBENCH",
            "weight": 0.08,
            "target_weight": 0.08,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "balanced",
            "regime_state": "bull",
            "sector": "Information Technology",
            "selection_confirmation_score": 0.24,
            "volatility_contraction_score": -0.20,
            "selection_reason": "MARKET_LEADER",
        },
    ]
    capped = apply_main_balanced_bull_qqq_damage_low_confirm_leader_cap(selected, "main")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["NEWCAP"]["weight"] == 0.0
    assert by_ticker["NEWCAP"]["target_weight"] == 0.0
    assert by_ticker["NEWCAP"]["main_balanced_bull_qqq_damage_low_confirm_leader_cap_status"] == "applied"
    assert by_ticker["HOLDCAP"]["weight"] == 0.0
    assert by_ticker["HOLDCAP"]["main_balanced_bull_qqq_damage_low_confirm_leader_cap_status"] == "applied"
    assert by_ticker["QQQLEADS"]["weight"] == 0.08
    assert by_ticker["CONFIRMED"]["weight"] == 0.08
    assert by_ticker["SMALL"]["weight"] == 0.04
    assert by_ticker["SECTOR"]["weight"] == 0.08
    assert by_ticker["NOBENCH"]["weight"] == 0.08
    concentrated = apply_main_balanced_bull_qqq_damage_low_confirm_leader_cap(selected, "concentrated")
    assert concentrated[0]["weight"] == 0.08


def test_main_balanced_neutral_soft_qqq_damage_weak_leader_cap_applies_narrowly() -> None:
    selected = [
        {
            "ticker": "LOWCONF",
            "weight": 0.10,
            "target_weight": 0.10,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "balanced",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.40,
            "breakout_setup_quality_score": 0.80,
            "spy_1m_return": 0.02,
            "qqq_1m_return": 0.01,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "WEAKBREAKOUT",
            "weight": 0.11,
            "target_weight": 0.11,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "crisis_state": "GREEN",
            "market_style_regime_label": "balanced",
            "regime_capacity_regime": "neutral",
            "selection_confirmation_score": 0.90,
            "breakout_setup_quality_score": 0.50,
            "spy_1m_return": 0.02,
            "qqq_1m_return": 0.01,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "STRONGSPY",
            "weight": 0.10,
            "target_weight": 0.10,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "balanced",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.40,
            "breakout_setup_quality_score": 0.50,
            "spy_1m_return": 0.04,
            "qqq_1m_return": 0.01,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "QQQDOWN",
            "weight": 0.10,
            "target_weight": 0.10,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "balanced",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.40,
            "breakout_setup_quality_score": 0.50,
            "spy_1m_return": 0.02,
            "qqq_1m_return": -0.01,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "QQQLEADS",
            "weight": 0.10,
            "target_weight": 0.10,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "balanced",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.40,
            "breakout_setup_quality_score": 0.50,
            "spy_1m_return": 0.02,
            "qqq_1m_return": 0.025,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "CONFIRMED",
            "weight": 0.10,
            "target_weight": 0.10,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "balanced",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.80,
            "breakout_setup_quality_score": 0.80,
            "spy_1m_return": 0.02,
            "qqq_1m_return": 0.01,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "BULL",
            "weight": 0.10,
            "target_weight": 0.10,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "balanced",
            "regime_state": "bull",
            "selection_confirmation_score": 0.40,
            "breakout_setup_quality_score": 0.50,
            "spy_1m_return": 0.02,
            "qqq_1m_return": 0.01,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "SMALL",
            "weight": 0.08,
            "target_weight": 0.08,
            "primary_lane": "MARKET_LEADER",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "balanced",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.40,
            "breakout_setup_quality_score": 0.50,
            "spy_1m_return": 0.02,
            "qqq_1m_return": 0.01,
            "selection_reason": "MARKET_LEADER",
        },
    ]
    capped = apply_main_balanced_neutral_soft_qqq_damage_weak_leader_cap(selected, "main")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["LOWCONF"]["weight"] == 0.04
    assert by_ticker["LOWCONF"]["target_weight"] == 0.04
    assert by_ticker["LOWCONF"]["main_balanced_neutral_soft_qqq_damage_weak_leader_cap_status"] == "applied"
    assert by_ticker["WEAKBREAKOUT"]["weight"] == 0.04
    assert by_ticker["WEAKBREAKOUT"]["main_balanced_neutral_soft_qqq_damage_weak_leader_cap_status"] == "applied"
    assert by_ticker["STRONGSPY"]["weight"] == 0.10
    assert by_ticker["QQQDOWN"]["weight"] == 0.10
    assert by_ticker["QQQLEADS"]["weight"] == 0.10
    assert by_ticker["CONFIRMED"]["weight"] == 0.10
    assert by_ticker["BULL"]["weight"] == 0.10
    assert by_ticker["SMALL"]["weight"] == 0.08
    concentrated = apply_main_balanced_neutral_soft_qqq_damage_weak_leader_cap(selected, "concentrated")
    assert concentrated[0]["weight"] == 0.10


def test_main_quality_bull_low_confirm_new_entry_cap_applies_narrowly() -> None:
    selected = [
        {
            "ticker": "LOWCONF",
            "weight": 0.12,
            "target_weight": 0.12,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "bull",
            "selection_confirmation_score": 0.62,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "CAPACITYBULL",
            "weight": 0.08,
            "target_weight": 0.08,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "quality_compounder",
            "regime_capacity_regime": "bull",
            "selection_confirmation_score": 0.24,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "CONFIRMED",
            "weight": 0.08,
            "target_weight": 0.08,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "bull",
            "selection_confirmation_score": 0.90,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "WATCH",
            "weight": 0.08,
            "target_weight": 0.08,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "WATCH",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "bull",
            "selection_confirmation_score": 0.24,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "HOLD",
            "weight": 0.08,
            "target_weight": 0.08,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "crisis_state": "GREEN",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "bull",
            "selection_confirmation_score": 0.24,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "NEUTRAL",
            "weight": 0.08,
            "target_weight": 0.08,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.24,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "BREAKOUT",
            "weight": 0.08,
            "target_weight": 0.08,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "breakout_growth",
            "regime_state": "bull",
            "selection_confirmation_score": 0.24,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
    ]
    capped = apply_main_quality_bull_low_confirm_new_entry_cap(selected, "main")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["LOWCONF"]["weight"] == 0.01
    assert by_ticker["LOWCONF"]["target_weight"] == 0.01
    assert by_ticker["LOWCONF"]["main_quality_bull_low_confirm_new_entry_cap_status"] == "applied"
    assert by_ticker["CAPACITYBULL"]["weight"] == 0.01
    assert by_ticker["CAPACITYBULL"]["main_quality_bull_low_confirm_new_entry_cap_status"] == "applied"
    assert by_ticker["CONFIRMED"]["weight"] == 0.08
    assert by_ticker["WATCH"]["weight"] == 0.08
    assert by_ticker["HOLD"]["weight"] == 0.08
    assert by_ticker["NEUTRAL"]["weight"] == 0.08
    assert by_ticker["BREAKOUT"]["weight"] == 0.08
    concentrated = apply_main_quality_bull_low_confirm_new_entry_cap(selected, "concentrated")
    assert concentrated[0]["weight"] == 0.12


def test_main_quality_hold_weak_timing_trim_applies_to_tired_holds_only() -> None:
    selected = [
        {
            "ticker": "LOWCONF",
            "weight": 0.12,
            "target_weight": 0.12,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "bull",
            "selection_confirmation_score": 0.24,
            "rs_benchmark_1m": 0.12,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "WEAKRS",
            "weight": 0.11,
            "target_weight": 0.11,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "market_style_regime_label": "quality_compounder",
            "regime_capacity_regime": "bull",
            "selection_confirmation_score": 1.0,
            "rs_benchmark_1m": 0.02,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "MIDCONF",
            "weight": 0.11,
            "target_weight": 0.11,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "market_style_regime_label": "quality_compounder",
            "regime_capacity_regime": "bull",
            "selection_confirmation_score": 0.62,
            "rs_benchmark_1m": 0.12,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "MIDRS",
            "weight": 0.11,
            "target_weight": 0.11,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "market_style_regime_label": "quality_compounder",
            "regime_capacity_regime": "bull",
            "selection_confirmation_score": 1.0,
            "rs_benchmark_1m": 0.08,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "OKHOLD",
            "weight": 0.12,
            "target_weight": 0.12,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "market_style_regime_label": "quality_compounder",
            "regime_capacity_regime": "bull",
            "selection_confirmation_score": 1.0,
            "rs_benchmark_1m": 0.12,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "NEW",
            "weight": 0.12,
            "target_weight": 0.12,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "market_style_regime_label": "quality_compounder",
            "regime_capacity_regime": "bull",
            "selection_confirmation_score": 0.24,
            "rs_benchmark_1m": 0.12,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "BEAR",
            "weight": 0.12,
            "target_weight": 0.12,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "market_style_regime_label": "quality_compounder",
            "regime_capacity_regime": "bear",
            "selection_confirmation_score": 0.24,
            "rs_benchmark_1m": 0.12,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "BREAKOUT",
            "weight": 0.12,
            "target_weight": 0.12,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "market_style_regime_label": "breakout_growth",
            "regime_capacity_regime": "bull",
            "selection_confirmation_score": 0.24,
            "rs_benchmark_1m": 0.12,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
    ]
    trimmed = apply_main_quality_hold_weak_timing_trim(selected, "main")
    by_ticker = {row["ticker"]: row for row in trimmed}
    assert by_ticker["LOWCONF"]["weight"] == 0.01
    assert by_ticker["LOWCONF"]["target_weight"] == 0.01
    assert by_ticker["LOWCONF"]["main_quality_hold_weak_timing_trim_status"] == "applied"
    assert by_ticker["WEAKRS"]["weight"] == 0.01
    assert by_ticker["WEAKRS"]["main_quality_hold_weak_timing_trim_status"] == "applied"
    assert by_ticker["MIDCONF"]["weight"] == 0.01
    assert by_ticker["MIDCONF"]["main_quality_hold_weak_timing_trim_status"] == "applied"
    assert by_ticker["MIDRS"]["weight"] == 0.01
    assert by_ticker["MIDRS"]["main_quality_hold_weak_timing_trim_status"] == "applied"
    assert by_ticker["OKHOLD"]["weight"] == 0.12
    assert by_ticker["NEW"]["weight"] == 0.12
    assert by_ticker["BEAR"]["weight"] == 0.12
    assert by_ticker["BREAKOUT"]["weight"] == 0.12
    concentrated = apply_main_quality_hold_weak_timing_trim(selected, "concentrated")
    assert concentrated[0]["weight"] == 0.12


def test_concentrated_hold_decay_trim_applies_to_decaying_holds_only() -> None:
    selected = [
        {
            "ticker": "DECAY",
            "weight": 0.30,
            "target_weight": 0.30,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "ticker_ret_1m": -0.02,
            "rs_benchmark_1m": 0.03,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "RELDECAY",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "ticker_ret_1m": 0.04,
            "rs_benchmark_1m": -0.01,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "NEW",
            "weight": 0.30,
            "target_weight": 0.30,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "ticker_ret_1m": -0.02,
            "rs_benchmark_1m": -0.01,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "OKHOLD",
            "weight": 0.30,
            "target_weight": 0.30,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "ticker_ret_1m": 0.02,
            "rs_benchmark_1m": 0.01,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
    ]
    trimmed = apply_concentrated_hold_decay_trim(selected, "concentrated")
    by_ticker = {row["ticker"]: row for row in trimmed}
    assert by_ticker["DECAY"]["weight"] == 0.04
    assert by_ticker["DECAY"]["target_weight"] == 0.04
    assert by_ticker["DECAY"]["concentrated_hold_decay_trim_status"] == "applied"
    assert by_ticker["RELDECAY"]["weight"] == 0.04
    assert by_ticker["RELDECAY"]["concentrated_hold_decay_trim_status"] == "applied"
    assert by_ticker["NEW"]["weight"] == 0.30
    assert by_ticker["OKHOLD"]["weight"] == 0.30
    main = apply_concentrated_hold_decay_trim(selected, "main")
    assert main[0]["weight"] == 0.30


def test_concentrated_high_vol_weak_timing_new_entry_cap_applies_narrowly() -> None:
    selected = [
        {
            "ticker": "LOWCONF",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "primary_lane": "MARKET_LEADER",
            "atr14_pct": 0.05,
            "selection_confirmation_score": 0.24,
            "rs_benchmark_1m": 0.20,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "WEAKRS",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "primary_lane": "MARKET_LEADER",
            "atr14_pct": 0.07,
            "selection_confirmation_score": 1.0,
            "rs_benchmark_1m": 0.02,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "CONFIRMED",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "primary_lane": "MARKET_LEADER",
            "atr14_pct": 0.07,
            "selection_confirmation_score": 1.0,
            "rs_benchmark_1m": 0.20,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "LOWVOL",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "primary_lane": "MARKET_LEADER",
            "atr14_pct": 0.04,
            "selection_confirmation_score": 0.24,
            "rs_benchmark_1m": 0.20,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "HOLD",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "primary_lane": "MARKET_LEADER",
            "atr14_pct": 0.07,
            "selection_confirmation_score": 0.24,
            "rs_benchmark_1m": 0.20,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "OTHERLANE",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "primary_lane": "QUALITY_COMPOUNDER",
            "atr14_pct": 0.07,
            "selection_confirmation_score": 0.24,
            "rs_benchmark_1m": 0.20,
            "selection_reason": "QUALITY_COMPOUNDER",
        },
    ]
    capped = apply_concentrated_high_vol_weak_timing_new_entry_cap(selected, "concentrated")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["LOWCONF"]["weight"] == 0.08
    assert by_ticker["LOWCONF"]["target_weight"] == 0.08
    assert by_ticker["LOWCONF"]["concentrated_high_vol_weak_timing_new_entry_cap_status"] == "applied"
    assert by_ticker["WEAKRS"]["weight"] == 0.08
    assert by_ticker["WEAKRS"]["concentrated_high_vol_weak_timing_new_entry_cap_status"] == "applied"
    assert by_ticker["CONFIRMED"]["weight"] == 0.20
    assert by_ticker["LOWVOL"]["weight"] == 0.20
    assert by_ticker["HOLD"]["weight"] == 0.20
    assert by_ticker["OTHERLANE"]["weight"] == 0.20
    main = apply_concentrated_high_vol_weak_timing_new_entry_cap(selected, "main")
    assert main[0]["weight"] == 0.20


def test_concentrated_unconfirmed_quality_bull_cap_applies_to_new_entries_only() -> None:
    selected = [
        {
            "ticker": "CAP",
            "weight": 0.30,
            "target_weight": 0.30,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "bull",
            "selection_confirmation_score": 0.24,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "CONFIRMED",
            "weight": 0.30,
            "target_weight": 0.30,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "bull",
            "selection_confirmation_score": 1.0,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "NEUTRAL",
            "weight": 0.30,
            "target_weight": 0.30,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.24,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "BALANCED",
            "weight": 0.30,
            "target_weight": 0.30,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "market_style_regime_label": "balanced",
            "regime_state": "bull",
            "selection_confirmation_score": 0.24,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "HOLD",
            "weight": 0.30,
            "target_weight": 0.30,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "bull",
            "selection_confirmation_score": 0.24,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "EXEMPT",
            "weight": 0.30,
            "target_weight": 0.30,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "bull",
            "selection_confirmation_score": 0.24,
            "primary_lane": "MARKET_LEADER",
            "alphaops_vnext_score": 4.95,
            "sec_combined_evidence_score": 0.21,
            "atr14_pct": 0.025,
            "rs_benchmark_1m": 0.21,
            "selection_reason": "MARKET_LEADER",
        },
    ]
    capped = apply_concentrated_unconfirmed_quality_bull_new_entry_cap(selected, "concentrated")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["CAP"]["weight"] == 0.03
    assert by_ticker["CAP"]["target_weight"] == 0.03
    assert by_ticker["CAP"]["concentrated_unconfirmed_quality_bull_new_entry_cap_status"] == "applied"
    assert by_ticker["CONFIRMED"]["weight"] == 0.30
    assert by_ticker["NEUTRAL"]["weight"] == 0.30
    assert by_ticker["BALANCED"]["weight"] == 0.30
    assert by_ticker["HOLD"]["weight"] == 0.30
    assert by_ticker["EXEMPT"]["weight"] == 0.30
    assert by_ticker["EXEMPT"]["concentrated_unconfirmed_quality_bull_new_entry_cap_status"] == (
        "exempt_high_conviction_stable_leader"
    )
    main = apply_concentrated_unconfirmed_quality_bull_new_entry_cap(selected, "main")
    assert main[0]["weight"] == 0.30


def test_concentrated_watch_unconfirmed_high_vol_cap_applies_to_watch_new_entries_only() -> None:
    selected = [
        {
            "ticker": "CAP",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "WATCH",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.24,
            "atr14_pct": 0.07,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "CONFIRMED",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "WATCH",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "neutral",
            "selection_confirmation_score": 1.0,
            "atr14_pct": 0.07,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "GREEN",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.24,
            "atr14_pct": 0.07,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "LOWVOL",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "WATCH",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.24,
            "atr14_pct": 0.04,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "HOLD",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "crisis_state": "WATCH",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.24,
            "atr14_pct": 0.07,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
    ]
    capped = apply_concentrated_watch_unconfirmed_high_vol_new_entry_cap(selected, "concentrated")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["CAP"]["weight"] == 0.12
    assert by_ticker["CAP"]["target_weight"] == 0.12
    assert by_ticker["CAP"]["concentrated_watch_unconfirmed_high_vol_new_entry_cap_status"] == "applied"
    assert by_ticker["CONFIRMED"]["weight"] == 0.20
    assert by_ticker["GREEN"]["weight"] == 0.20
    assert by_ticker["LOWVOL"]["weight"] == 0.20
    assert by_ticker["HOLD"]["weight"] == 0.20
    main = apply_concentrated_watch_unconfirmed_high_vol_new_entry_cap(selected, "main")
    assert main[0]["weight"] == 0.20


def test_concentrated_watch_unconfirmed_market_leader_cap_applies_without_atr_filter() -> None:
    selected = [
        {
            "ticker": "CAP",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "WATCH",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.24,
            "atr14_pct": 0.04,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "CONFIRMED",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "WATCH",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "neutral",
            "selection_confirmation_score": 1.0,
            "atr14_pct": 0.04,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "GREEN",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.24,
            "atr14_pct": 0.04,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "QUALITY",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "WATCH",
            "market_style_regime_label": "quality_compounder",
            "regime_state": "neutral",
            "selection_confirmation_score": 0.24,
            "atr14_pct": 0.04,
            "primary_lane": "QUALITY_COMPOUNDER",
            "selection_reason": "QUALITY_COMPOUNDER",
        },
    ]
    capped = apply_concentrated_watch_unconfirmed_market_leader_new_entry_cap(selected, "concentrated")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["CAP"]["weight"] == 0.08
    assert by_ticker["CAP"]["target_weight"] == 0.08
    assert by_ticker["CAP"]["concentrated_watch_unconfirmed_ml_new_entry_cap_status"] == "applied"
    assert by_ticker["CONFIRMED"]["weight"] == 0.20
    assert by_ticker["GREEN"]["weight"] == 0.20
    assert by_ticker["QUALITY"]["weight"] == 0.20
    main = apply_concentrated_watch_unconfirmed_market_leader_new_entry_cap(selected, "main")
    assert main[0]["weight"] == 0.20


def test_concentrated_green_bull_qqq_down_cap_applies_to_new_market_leaders_only() -> None:
    selected = [
        {
            "ticker": "CAP",
            "weight": 0.24,
            "target_weight": 0.24,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "regime_state": "bull",
            "qqq_1m_return": -0.02,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "QQQ_UP",
            "weight": 0.24,
            "target_weight": 0.24,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "regime_state": "bull",
            "qqq_1m_return": 0.01,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "NEUTRAL",
            "weight": 0.24,
            "target_weight": 0.24,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "regime_state": "neutral",
            "qqq_1m_return": -0.02,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "HOLD",
            "weight": 0.24,
            "target_weight": 0.24,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "crisis_state": "GREEN",
            "regime_state": "bull",
            "qqq_1m_return": -0.02,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "QUALITY",
            "weight": 0.24,
            "target_weight": 0.24,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "regime_state": "bull",
            "qqq_1m_return": -0.02,
            "primary_lane": "QUALITY_COMPOUNDER",
            "selection_reason": "QUALITY_COMPOUNDER",
        },
    ]
    capped = apply_concentrated_green_bull_qqq_down_new_entry_cap(selected, "concentrated")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["CAP"]["weight"] == 0.08
    assert by_ticker["CAP"]["target_weight"] == 0.08
    assert by_ticker["CAP"]["concentrated_green_bull_qqq_down_new_entry_cap_status"] == "applied"
    assert by_ticker["QQQ_UP"]["weight"] == 0.24
    assert by_ticker["NEUTRAL"]["weight"] == 0.24
    assert by_ticker["HOLD"]["weight"] == 0.24
    assert by_ticker["QUALITY"]["weight"] == 0.24
    main = apply_concentrated_green_bull_qqq_down_new_entry_cap(selected, "main")
    assert main[0]["weight"] == 0.24


def test_concentrated_green_consumer_overheat_cap_applies_to_new_entries_only() -> None:
    selected = [
        {
            "ticker": "CAP",
            "weight": 0.30,
            "target_weight": 0.30,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "sector": "Consumer Discretionary",
            "rs_benchmark_1m": 0.32,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "LOW_RS",
            "weight": 0.30,
            "target_weight": 0.30,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "sector": "Consumer Discretionary",
            "rs_benchmark_1m": 0.18,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "HOLD",
            "weight": 0.30,
            "target_weight": 0.30,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "crisis_state": "GREEN",
            "sector": "Consumer Discretionary",
            "rs_benchmark_1m": 0.32,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "WATCH",
            "weight": 0.30,
            "target_weight": 0.30,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "WATCH",
            "sector": "Consumer Discretionary",
            "rs_benchmark_1m": 0.32,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "TECH",
            "weight": 0.30,
            "target_weight": 0.30,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "sector": "Information Technology",
            "rs_benchmark_1m": 0.32,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
    ]
    capped = apply_concentrated_green_consumer_overheat_new_entry_cap(selected, "concentrated")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["CAP"]["weight"] == 0.08
    assert by_ticker["CAP"]["target_weight"] == 0.08
    assert by_ticker["CAP"]["concentrated_green_consumer_overheat_new_entry_cap_status"] == "applied"
    assert by_ticker["LOW_RS"]["weight"] == 0.30
    assert by_ticker["HOLD"]["weight"] == 0.30
    assert by_ticker["WATCH"]["weight"] == 0.30
    assert by_ticker["TECH"]["weight"] == 0.30
    main = apply_concentrated_green_consumer_overheat_new_entry_cap(selected, "main")
    assert main[0]["weight"] == 0.30


def test_concentrated_green_confirmed_market_leader_weak_rs_cap_applies_to_new_entries_only() -> None:
    selected = [
        {
            "ticker": "CAP",
            "weight": 0.24,
            "target_weight": 0.24,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "selection_confirmation_score": 1.0,
            "rs_benchmark_1m": 0.08,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "STRONG_RS",
            "weight": 0.24,
            "target_weight": 0.24,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "selection_confirmation_score": 1.0,
            "rs_benchmark_1m": 0.20,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "UNCONFIRMED",
            "weight": 0.24,
            "target_weight": 0.24,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "selection_confirmation_score": 0.25,
            "rs_benchmark_1m": 0.08,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "HOLD",
            "weight": 0.24,
            "target_weight": 0.24,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "crisis_state": "GREEN",
            "selection_confirmation_score": 1.0,
            "rs_benchmark_1m": 0.08,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "HIGH_CONVICTION_STABLE",
            "weight": 0.30,
            "target_weight": 0.30,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "selection_confirmation_score": 1.0,
            "rs_benchmark_1m": 0.06,
            "score": 5.8,
            "sec_combined_evidence_score": 0.31,
            "atr14_pct": 0.03,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
    ]
    capped = apply_concentrated_green_confirmed_market_leader_weak_rs_new_entry_cap(
        selected,
        "concentrated",
    )
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["CAP"]["weight"] == 0.12
    assert by_ticker["CAP"]["target_weight"] == 0.12
    assert by_ticker["CAP"]["concentrated_green_confirmed_ml_weak_rs_new_entry_cap_status"] == "applied"
    assert by_ticker["STRONG_RS"]["weight"] == 0.24
    assert by_ticker["UNCONFIRMED"]["weight"] == 0.24
    assert by_ticker["HOLD"]["weight"] == 0.24
    assert by_ticker["HIGH_CONVICTION_STABLE"]["weight"] == 0.30
    assert (
        by_ticker["HIGH_CONVICTION_STABLE"]["concentrated_green_confirmed_ml_weak_rs_new_entry_cap_status"]
        == "exempt_high_conviction_stable_leader"
    )
    main = apply_concentrated_green_confirmed_market_leader_weak_rs_new_entry_cap(selected, "main")
    assert main[0]["weight"] == 0.24


def test_concentrated_green_neutral_cyclical_high_vol_cap_applies_to_new_energy_materials_only() -> None:
    selected = [
        {
            "ticker": "CAP",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "regime_state": "neutral",
            "sector": "Materials",
            "atr14_pct": 0.14,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "LOW_VOL",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "regime_state": "neutral",
            "sector": "Energy",
            "atr14_pct": 0.05,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "MID_VOL",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "regime_state": "neutral",
            "sector": "Materials",
            "atr14_pct": 0.065,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "TECH",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "regime_state": "neutral",
            "sector": "Information Technology",
            "atr14_pct": 0.14,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "BEAR",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "DEFENSE_REVIEW",
            "regime_state": "neutral",
            "sector": "Materials",
            "atr14_pct": 0.14,
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
    ]
    capped = apply_concentrated_green_neutral_cyclical_high_vol_new_entry_cap(
        selected,
        "concentrated",
    )
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["CAP"]["weight"] == 0.06
    assert by_ticker["CAP"]["target_weight"] == 0.06
    assert by_ticker["CAP"]["concentrated_green_neutral_cyclical_high_vol_new_entry_cap_status"] == "applied"
    assert by_ticker["MID_VOL"]["weight"] == 0.06
    assert by_ticker["MID_VOL"]["target_weight"] == 0.06
    assert by_ticker["MID_VOL"]["concentrated_green_neutral_cyclical_high_vol_new_entry_cap_status"] == "applied"
    assert by_ticker["LOW_VOL"]["weight"] == 0.20
    assert by_ticker["TECH"]["weight"] == 0.20
    assert by_ticker["BEAR"]["weight"] == 0.20
    main = apply_concentrated_green_neutral_cyclical_high_vol_new_entry_cap(selected, "main")
    assert main[0]["weight"] == 0.20


def test_concentrated_defense_neutral_quality_cap_applies_to_new_quality_entries_only() -> None:
    selected = [
        {
            "ticker": "CAP",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "DEFENSE_REVIEW",
            "regime_state": "neutral",
            "primary_lane": "QUALITY_COMPOUNDER",
            "selection_reason": "QUALITY_COMPOUNDER",
        },
        {
            "ticker": "GREEN",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "GREEN",
            "regime_state": "neutral",
            "primary_lane": "QUALITY_COMPOUNDER",
            "selection_reason": "QUALITY_COMPOUNDER",
        },
        {
            "ticker": "BULL",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "DEFENSE_REVIEW",
            "regime_state": "bull",
            "primary_lane": "QUALITY_COMPOUNDER",
            "selection_reason": "QUALITY_COMPOUNDER",
        },
        {
            "ticker": "LEADER",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "crisis_state": "DEFENSE_REVIEW",
            "regime_state": "neutral",
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "HOLD",
            "weight": 0.20,
            "target_weight": 0.20,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "crisis_state": "DEFENSE_REVIEW",
            "regime_state": "neutral",
            "primary_lane": "QUALITY_COMPOUNDER",
            "selection_reason": "QUALITY_COMPOUNDER",
        },
    ]
    capped = apply_concentrated_defense_neutral_quality_new_entry_cap(selected, "concentrated")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["CAP"]["weight"] == 0.12
    assert by_ticker["CAP"]["target_weight"] == 0.12
    assert by_ticker["CAP"]["concentrated_defense_neutral_quality_new_entry_cap_status"] == "applied"
    assert by_ticker["GREEN"]["weight"] == 0.20
    assert by_ticker["BULL"]["weight"] == 0.20
    assert by_ticker["LEADER"]["weight"] == 0.20
    assert by_ticker["HOLD"]["weight"] == 0.20
    main = apply_concentrated_defense_neutral_quality_new_entry_cap(selected, "main")
    assert main[0]["weight"] == 0.20


def test_concentrated_unconfirmed_high_vol_cap_applies_to_green_new_entries_only() -> None:
    selected = [
        {
            "ticker": "CAP",
            "weight": 0.30,
            "target_weight": 0.30,
            "primary_lane": "MARKET_LEADER",
            "crisis_state": "GREEN",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "atr14_pct": 0.08,
            "selection_confirmation_score": 0.0,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "CONFIRMED",
            "weight": 0.30,
            "target_weight": 0.30,
            "primary_lane": "MARKET_LEADER",
            "crisis_state": "GREEN",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "atr14_pct": 0.08,
            "selection_confirmation_score": 1.0,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "WATCH",
            "weight": 0.30,
            "target_weight": 0.30,
            "primary_lane": "MARKET_LEADER",
            "crisis_state": "WATCH",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "atr14_pct": 0.08,
            "selection_confirmation_score": 0.0,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "HOLD",
            "weight": 0.30,
            "target_weight": 0.30,
            "primary_lane": "MARKET_LEADER",
            "crisis_state": "GREEN",
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "atr14_pct": 0.08,
            "selection_confirmation_score": 0.0,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "LOWVOL",
            "weight": 0.30,
            "target_weight": 0.30,
            "primary_lane": "MARKET_LEADER",
            "crisis_state": "GREEN",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "atr14_pct": 0.04,
            "selection_confirmation_score": 0.0,
            "selection_reason": "MARKET_LEADER",
        },
    ]
    capped = apply_concentrated_unconfirmed_high_vol_new_entry_cap(selected, "concentrated")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["CAP"]["weight"] == 0.12
    assert by_ticker["CAP"]["target_weight"] == 0.12
    assert by_ticker["CAP"]["concentrated_unconfirmed_high_vol_new_entry_cap_status"] == "applied"
    assert by_ticker["CONFIRMED"]["weight"] == 0.30
    assert by_ticker["WATCH"]["weight"] == 0.30
    assert by_ticker["HOLD"]["weight"] == 0.30
    assert by_ticker["LOWVOL"]["weight"] == 0.30
    main = apply_concentrated_unconfirmed_high_vol_new_entry_cap(selected, "main")
    assert main[0]["weight"] == 0.30


def test_concentrated_watch_damaged_weak_market_leader_cap_applies_to_new_and_hold_rows() -> None:
    selected = [
        {
            "ticker": "CAPNEW",
            "weight": 0.18,
            "target_weight": 0.18,
            "primary_lane": "MARKET_LEADER",
            "crisis_state": "WATCH",
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "selection_confirmation_score": 0.40,
            "breakout_setup_quality_score": 0.80,
            "qqq_1m_return": 0.01,
            "spy_1m_return": 0.03,
            "ticker_ret_1m": 0.10,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "CAPHOLD",
            "weight": 0.16,
            "target_weight": 0.16,
            "primary_lane": "MARKET_LEADER",
            "crisis_state": "DEFENSE_REVIEW",
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "selection_confirmation_score": 1.0,
            "breakout_setup_quality_score": 0.40,
            "qqq_1m_return": 0.04,
            "spy_1m_return": 0.02,
            "ticker_ret_1m": 0.03,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "STRONG",
            "weight": 0.18,
            "target_weight": 0.18,
            "primary_lane": "MARKET_LEADER",
            "crisis_state": "WATCH",
            "holding_state": "NEW",
            "selection_confirmation_score": 1.0,
            "breakout_setup_quality_score": 0.80,
            "qqq_1m_return": 0.01,
            "spy_1m_return": 0.03,
            "ticker_ret_1m": 0.10,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "NODAMAGE",
            "weight": 0.18,
            "target_weight": 0.18,
            "primary_lane": "MARKET_LEADER",
            "crisis_state": "WATCH",
            "holding_state": "NEW",
            "selection_confirmation_score": 0.40,
            "breakout_setup_quality_score": 0.80,
            "qqq_1m_return": 0.04,
            "spy_1m_return": 0.02,
            "ticker_ret_1m": 0.10,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "GREEN",
            "weight": 0.18,
            "target_weight": 0.18,
            "primary_lane": "MARKET_LEADER",
            "crisis_state": "GREEN",
            "holding_state": "NEW",
            "selection_confirmation_score": 0.40,
            "breakout_setup_quality_score": 0.80,
            "qqq_1m_return": 0.01,
            "spy_1m_return": 0.03,
            "ticker_ret_1m": 0.10,
            "selection_reason": "MARKET_LEADER",
        },
        {
            "ticker": "QUALITY",
            "weight": 0.18,
            "target_weight": 0.18,
            "primary_lane": "QUALITY_COMPOUNDER",
            "crisis_state": "WATCH",
            "holding_state": "NEW",
            "selection_confirmation_score": 0.40,
            "breakout_setup_quality_score": 0.80,
            "qqq_1m_return": 0.01,
            "spy_1m_return": 0.03,
            "ticker_ret_1m": 0.10,
            "selection_reason": "QUALITY_COMPOUNDER",
        },
    ]
    capped = apply_concentrated_watch_damaged_weak_market_leader_cap(selected, "concentrated")
    by_ticker = {row["ticker"]: row for row in capped}
    assert by_ticker["CAPNEW"]["weight"] == 0.08
    assert by_ticker["CAPNEW"]["target_weight"] == 0.08
    assert by_ticker["CAPNEW"]["concentrated_watch_damaged_weak_ml_cap_status"] == "applied"
    assert by_ticker["CAPHOLD"]["weight"] == 0.08
    assert by_ticker["CAPHOLD"]["target_weight"] == 0.08
    assert by_ticker["CAPHOLD"]["concentrated_watch_damaged_weak_ml_cap_status"] == "applied"
    assert by_ticker["STRONG"]["weight"] == 0.18
    assert by_ticker["NODAMAGE"]["weight"] == 0.18
    assert by_ticker["GREEN"]["weight"] == 0.18
    assert by_ticker["QUALITY"]["weight"] == 0.18
    main = apply_concentrated_watch_damaged_weak_market_leader_cap(selected, "main")
    assert main[0]["weight"] == 0.18


def test_main_cash_count_structure_narrows_high_cash_main_books() -> None:
    selected = []
    for idx in range(15):
        selected.append(
            {
                "ticker": f"T{idx:02d}",
                "weight": 0.04,
                "target_weight": 0.04,
                "alphaops_vnext_weight_score": 100 - idx,
                "alphaops_vnext_score": 100 - idx,
                "primary_lane": "MARKET_LEADER",
                "selection_reason": "smoke",
            }
        )
    reshaped = apply_main_cash_count_structure(
        selected,
        portfolio_kind="main",
        target_n=15,
        crisis_state="GREEN",
    )
    cash = 1.0 - sum(float(row["weight"]) for row in reshaped)
    assert len(reshaped) == 8
    assert round(cash, 8) == 0.40
    assert all(row["main_cash_count_structure_status"] == "applied" for row in reshaped)
    assert all(row["main_cash_count_structure_max_names"] == 8 for row in reshaped)


if __name__ == "__main__":
    test_alphaops_vnext_replaces_operating_books_and_blocks_future_evidence()
    test_sec_available_from_columns_are_pit_checked_and_positive_only()
    test_alphaops_vnext_applies_crisis_lane_new_buy_blocks()
    test_alphaops_vnext_concentrated_production_default_is_n5()
    test_concentrated_risk_state_caps_new_entries_only()
    test_main_neutral_churn_filter_blocks_reentries_and_rebuilds_cash()
    test_neutral_metals_new_entry_block_removes_new_entries_and_rebuilds_cash()
    test_concentrated_green_benchmark_risk_cyclical_block_is_narrow()
    test_main_defense_review_turnaround_new_entry_block_preserves_holds()
    test_main_defense_review_balanced_new_entry_block_preserves_existing_positions()
    test_main_high_volatility_cap_applies_to_new_market_leaders_only()
    test_main_watch_unconfirmed_market_leader_cap_applies_to_neutral_watch_new_entries_only()
    test_main_green_neutral_cyclical_high_vol_cap_applies_to_new_energy_materials_only()
    test_main_green_bull_low_confirm_high_vol_cap_applies_to_new_market_leaders_only()
    test_main_balanced_bull_qqq_damage_low_confirm_leader_cap_applies_narrowly()
    test_main_balanced_neutral_soft_qqq_damage_weak_leader_cap_applies_narrowly()
    test_main_quality_bull_low_confirm_new_entry_cap_applies_narrowly()
    test_main_quality_hold_weak_timing_trim_applies_to_tired_holds_only()
    test_concentrated_hold_decay_trim_applies_to_decaying_holds_only()
    test_concentrated_high_vol_weak_timing_new_entry_cap_applies_narrowly()
    test_concentrated_unconfirmed_quality_bull_cap_applies_to_new_entries_only()
    test_concentrated_watch_unconfirmed_high_vol_cap_applies_to_watch_new_entries_only()
    test_concentrated_watch_unconfirmed_market_leader_cap_applies_without_atr_filter()
    test_concentrated_green_bull_qqq_down_cap_applies_to_new_market_leaders_only()
    test_concentrated_green_consumer_overheat_cap_applies_to_new_entries_only()
    test_concentrated_green_confirmed_market_leader_weak_rs_cap_applies_to_new_entries_only()
    test_concentrated_green_neutral_cyclical_high_vol_cap_applies_to_new_energy_materials_only()
    test_concentrated_defense_neutral_quality_cap_applies_to_new_quality_entries_only()
    test_concentrated_unconfirmed_high_vol_cap_applies_to_green_new_entries_only()
    test_concentrated_watch_damaged_weak_market_leader_cap_applies_to_new_and_hold_rows()
    test_main_cash_count_structure_narrows_high_cash_main_books()
    print("alphaops_vnext_policy_replay_smoke: PASS")

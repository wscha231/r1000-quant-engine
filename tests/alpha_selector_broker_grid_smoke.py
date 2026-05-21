#!/usr/bin/env python3
"""Smoke checks for alpha selector broker grid."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_alpha_selector_broker_grid import run, select_satellite_targets  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    ).to_parquet(cache_dir / px_cache_name(ticker))


def test_alpha_selector_grid_runs_broker_replay_without_forward_selection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "alpha_grid"
        cache.mkdir()
        _write_px(cache, "AAA", [100, 101, 102, 103, 104, 105])
        _write_px(cache, "BBB", [50, 51, 52, 53, 54, 55])
        _write_px(cache, "LEAK", [10, 9, 8, 7, 6, 5])
        candidate = root / "candidate_replay_book.csv"
        rows = []
        for dt in ["2026-01-02", "2026-01-05"]:
            rows.extend(
                [
                    {
                        "rebalance_date": dt,
                        "ticker": "AAA",
                        "Name": "Leader A",
                        "sector": "Tech",
                        "score": 9.0,
                        "portfolio_sleeve_label": "future_winner",
                        "portfolio_candidate_gate_label": "future_relaxed",
                        "portfolio_future_winner_engine_score": 0.95,
                        "portfolio_early_scout_engine_score": 0.85,
                        "portfolio_monster_early_score": 0.80,
                        "h6_dynamic_leader_score": 0.75,
                        "rs_acceleration_score": 0.60,
                        "industry_group_strength_score": 0.50,
                        "selection_market_confirmation_score": 0.80,
                        "entry_quality_score": 0.70,
                        "early_evidence_score": 0.90,
                        "evidence_confidence_score": 0.80,
                        "institutional_evidence_score": 0.70,
                        "institutional_evidence_confidence_score": 0.80,
                        "etf_holdings_score": 0.60,
                        "etf_evidence_confidence": 0.70,
                        "sec_combined_evidence_score": 0.75,
                        "smart_money_shadow_score": 0.85,
                        "smart_money_evidence_source_count": 3,
                        "evidence_fusion_score": 0.82,
                        "post_disclosure_discovery_score": 0.88,
                        "post_disclosure_mega_confirmation_score": 0.74,
                        "post_disclosure_price_confirmed_score": 0.80,
                        "post_disclosure_price_confirmation_score": 0.75,
                        "pda_size_discovery_score": 0.85,
                        "pda_13f_new_or_add_score": 0.90,
                        "pda_13f_new_or_add_count": 2,
                        "pda_13f_first_buy_surprise_score": 0.85,
                        "pda_13f_first_buy_surprise_count": 1,
                        "pda_form4_open_market_buy_score": 0.80,
                        "pda_form4_open_market_buy_count": 1,
                        "pda_etf_new_or_increase_score": 0.70,
                        "pda_etf_new_or_increase_count": 1,
                        "leader_onset_sec_v2_score": 0.95,
                        "leader_onset_sec_v3_score": 0.95,
                        "portfolio_risk_entry_block_score": 0.0,
                        "portfolio_stale_mega_leader_score": 0.0,
                        "px": 100.0,
                        "dollar_vol_20d": 50_000_000,
                        "mktcap": 5_000_000_000,
                        "period_forward_return": 0.10,
                    },
                    {
                        "rebalance_date": dt,
                        "ticker": "BBB",
                        "Name": "Leader B",
                        "sector": "Tech",
                        "score": 8.0,
                        "portfolio_sleeve_label": "early_scout",
                        "portfolio_candidate_gate_label": "early_relaxed",
                        "portfolio_future_winner_engine_score": 0.15,
                        "portfolio_early_scout_engine_score": 0.10,
                        "portfolio_monster_early_score": 0.10,
                        "h6_dynamic_leader_score": 0.10,
                        "rs_acceleration_score": 0.05,
                        "industry_group_strength_score": 0.05,
                        "selection_market_confirmation_score": 0.20,
                        "entry_quality_score": 0.20,
                        "early_evidence_score": 0.00,
                        "evidence_confidence_score": 0.00,
                        "institutional_evidence_score": 0.00,
                        "institutional_evidence_confidence_score": 0.00,
                        "etf_holdings_score": 0.00,
                        "etf_evidence_confidence": 0.00,
                        "sec_combined_evidence_score": 0.00,
                        "smart_money_shadow_score": 0.00,
                        "smart_money_evidence_source_count": 0,
                        "evidence_fusion_score": 0.00,
                        "post_disclosure_discovery_score": 0.0,
                        "post_disclosure_mega_confirmation_score": 0.0,
                        "post_disclosure_price_confirmed_score": 0.0,
                        "post_disclosure_price_confirmation_score": 0.0,
                        "pda_size_discovery_score": 0.85,
                        "pda_13f_new_or_add_score": 0.0,
                        "pda_13f_new_or_add_count": 0,
                        "pda_13f_first_buy_surprise_score": 0.0,
                        "pda_13f_first_buy_surprise_count": 0,
                        "pda_form4_open_market_buy_score": 0.0,
                        "pda_form4_open_market_buy_count": 0,
                        "pda_etf_new_or_increase_score": 0.0,
                        "pda_etf_new_or_increase_count": 0,
                        "leader_onset_sec_v2_score": 0.10,
                        "leader_onset_sec_v3_score": 0.10,
                        "portfolio_risk_entry_block_score": 0.0,
                        "portfolio_stale_mega_leader_score": 0.0,
                        "px": 50.0,
                        "dollar_vol_20d": 40_000_000,
                        "mktcap": 4_000_000_000,
                        "period_forward_return": 0.08,
                    },
                    {
                        "rebalance_date": dt,
                        "ticker": "LEAK",
                        "Name": "Forward Label Only",
                        "sector": "Tech",
                        "score": 0.1,
                        "portfolio_sleeve_label": "unassigned",
                        "portfolio_candidate_gate_label": "rejected",
                        "portfolio_future_winner_engine_score": 0.0,
                        "portfolio_early_scout_engine_score": 0.0,
                        "portfolio_monster_early_score": 0.0,
                        "h6_dynamic_leader_score": 0.0,
                        "rs_acceleration_score": 0.0,
                        "industry_group_strength_score": 0.0,
                        "selection_market_confirmation_score": 0.0,
                        "entry_quality_score": 0.0,
                        "early_evidence_score": 0.0,
                        "evidence_confidence_score": 0.0,
                        "institutional_evidence_score": 0.0,
                        "institutional_evidence_confidence_score": 0.0,
                        "etf_holdings_score": 0.0,
                        "etf_evidence_confidence": 0.0,
                        "sec_combined_evidence_score": 0.0,
                        "smart_money_shadow_score": 0.0,
                        "smart_money_evidence_source_count": 0,
                        "evidence_fusion_score": 0.0,
                        "post_disclosure_discovery_score": 0.0,
                        "post_disclosure_mega_confirmation_score": 0.0,
                        "post_disclosure_price_confirmed_score": 0.0,
                        "post_disclosure_price_confirmation_score": 0.0,
                        "pda_size_discovery_score": 0.0,
                        "pda_13f_new_or_add_score": 0.0,
                        "pda_13f_new_or_add_count": 0,
                        "pda_13f_first_buy_surprise_score": 0.0,
                        "pda_13f_first_buy_surprise_count": 0,
                        "pda_form4_open_market_buy_score": 0.0,
                        "pda_form4_open_market_buy_count": 0,
                        "pda_etf_new_or_increase_score": 0.0,
                        "pda_etf_new_or_increase_count": 0,
                        "leader_onset_sec_v2_score": 0.0,
                        "leader_onset_sec_v3_score": 0.0,
                        "portfolio_risk_entry_block_score": 0.0,
                        "portfolio_stale_mega_leader_score": 0.0,
                        "px": 10.0,
                        "dollar_vol_20d": 100_000_000,
                        "mktcap": 10_000_000_000,
                        "period_forward_return": 9.99,
                    },
                    {
                        "rebalance_date": dt,
                        "ticker": "MISS",
                        "Name": "Missing Price Cache",
                        "sector": "Tech",
                        "score": 10.0,
                        "portfolio_sleeve_label": "future_winner",
                        "portfolio_candidate_gate_label": "future_relaxed",
                        "portfolio_future_winner_engine_score": 1.0,
                        "portfolio_early_scout_engine_score": 1.0,
                        "portfolio_monster_early_score": 1.0,
                        "h6_dynamic_leader_score": 1.0,
                        "rs_acceleration_score": 1.0,
                        "industry_group_strength_score": 1.0,
                        "selection_market_confirmation_score": 1.0,
                        "entry_quality_score": 1.0,
                        "early_evidence_score": 1.0,
                        "evidence_confidence_score": 1.0,
                        "institutional_evidence_score": 1.0,
                        "institutional_evidence_confidence_score": 1.0,
                        "etf_holdings_score": 1.0,
                        "etf_evidence_confidence": 1.0,
                        "sec_combined_evidence_score": 1.0,
                        "smart_money_shadow_score": 1.0,
                        "smart_money_evidence_source_count": 3,
                        "evidence_fusion_score": 1.0,
                        "post_disclosure_discovery_score": 1.0,
                        "post_disclosure_mega_confirmation_score": 1.0,
                        "post_disclosure_price_confirmed_score": 1.0,
                        "post_disclosure_price_confirmation_score": 1.0,
                        "pda_size_discovery_score": 0.0,
                        "pda_13f_new_or_add_score": 1.0,
                        "pda_13f_new_or_add_count": 3,
                        "pda_13f_first_buy_surprise_score": 1.0,
                        "pda_13f_first_buy_surprise_count": 2,
                        "pda_form4_open_market_buy_score": 1.0,
                        "pda_form4_open_market_buy_count": 2,
                        "pda_etf_new_or_increase_score": 1.0,
                        "pda_etf_new_or_increase_count": 2,
                        "leader_onset_sec_v2_score": 1.0,
                        "leader_onset_sec_v3_score": 1.0,
                        "portfolio_risk_entry_block_score": 0.0,
                        "portfolio_stale_mega_leader_score": 0.0,
                        "px": 20.0,
                        "dollar_vol_20d": 100_000_000,
                        "mktcap": 20_000_000_000,
                        "period_forward_return": 99.99,
                    },
                ]
            )
        pd.DataFrame(rows).to_csv(candidate, index=False)
        payload = run(
            argparse.Namespace(
                candidate_book=str(candidate),
                price_cache=str(cache),
                output_dir=str(out),
                portfolio_kind="main",
                starting_capital=10_000.0,
                fill_mode="next_close",
                cost_bps=0.0,
                no_integer_shares=False,
                max_fill_lag_days=7,
                styles="future_heavy,future_heavy_post_disclosure_micro,future_heavy_post_disclosure_confirmed,future_heavy_post_disclosure_optional_satellite,future_heavy_post_disclosure_satellite,future_winner_smart_money,leader_onset_shadow,sec_evidence_shadow,smart_money_shadow,post_disclosure_discovery,post_disclosure_price_confirmed,post_disclosure_mega_confirmation",
                target_ns="1",
                single_name_caps="1.00",
                max_variants=12,
                min_market_cap_usd=1_000_000_000.0,
                min_dollar_volume_usd=1_000_000.0,
                min_price=5.0,
            )
        )
        assert payload["status"] == "completed"
        assert payload["valid_for_production"] is True
        summary = pd.read_csv(out / "summary.csv")
        assert len(summary) == 12
        targets = pd.read_csv(next(out.glob("future_heavy_N1_cap*/target_book.csv")))
        assert set(targets["ticker"]) == {"AAA"}
        assert float(targets["weight"].max()) > 0.99
        assert "BBB" not in set(targets["ticker"])
        assert "LEAK" not in set(targets["ticker"])
        assert "MISS" not in set(targets["ticker"])
        confirm_targets = pd.read_csv(next(out.glob("future_winner_smart_money_N1_cap*/target_book.csv")))
        assert set(confirm_targets["ticker"]) == {"AAA"}
        assert "smart_money_shadow_score" in confirm_targets.columns
        assert "evidence_fusion_score" in confirm_targets.columns
        onset_targets = pd.read_csv(next(out.glob("leader_onset_shadow_N1_cap*/target_book.csv")))
        assert set(onset_targets["ticker"]) == {"AAA"}
        assert "leader_onset_score" in onset_targets.columns
        sec_targets = pd.read_csv(next(out.glob("sec_evidence_shadow_N1_cap*/target_book.csv")))
        assert set(sec_targets["ticker"]) == {"AAA"}
        assert "leader_onset_sec_v2_score" in sec_targets.columns
        assert "early_evidence_score" in sec_targets.columns
        smart_targets = pd.read_csv(next(out.glob("smart_money_shadow_N1_cap*/target_book.csv")))
        assert set(smart_targets["ticker"]) == {"AAA"}
        assert "smart_money_shadow_score" in smart_targets.columns
        assert "evidence_fusion_score" in smart_targets.columns
        micro_targets = pd.read_csv(next(out.glob("future_heavy_post_disclosure_micro_N1_cap*/target_book.csv")))
        assert set(micro_targets["ticker"]) == {"AAA"}
        assert "post_disclosure_discovery_score" in micro_targets.columns
        assert "pda_13f_first_buy_surprise_score" in micro_targets.columns
        assert "pda_form4_open_market_buy_score" in micro_targets.columns
        confirmed_micro_targets = pd.read_csv(next(out.glob("future_heavy_post_disclosure_confirmed_N1_cap*/target_book.csv")))
        assert set(confirmed_micro_targets["ticker"]) == {"AAA"}
        assert "post_disclosure_price_confirmed_score" in confirmed_micro_targets.columns
        satellite_targets = pd.read_csv(next(out.glob("future_heavy_post_disclosure_satellite_N1_cap*/target_book.csv")))
        assert set(satellite_targets["ticker"]) == {"AAA"}
        assert "post_disclosure_satellite_slot" in satellite_targets.columns
        optional_satellite_targets = pd.read_csv(next(out.glob("future_heavy_post_disclosure_optional_satellite_N1_cap*/target_book.csv")))
        assert set(optional_satellite_targets["ticker"]) == {"AAA"}
        assert "post_disclosure_satellite_slot" in optional_satellite_targets.columns
        discovery_targets = pd.read_csv(next(out.glob("post_disclosure_discovery_N1_cap*/target_book.csv")))
        assert set(discovery_targets["ticker"]) == {"AAA"}
        assert "post_disclosure_discovery_score" in discovery_targets.columns
        assert "pda_13f_new_or_add_score" in discovery_targets.columns
        assert "pda_etf_new_or_increase_score" in discovery_targets.columns
        price_confirmed_targets = pd.read_csv(next(out.glob("post_disclosure_price_confirmed_N1_cap*/target_book.csv")))
        assert set(price_confirmed_targets["ticker"]) == {"AAA"}
        assert "post_disclosure_price_confirmed_score" in price_confirmed_targets.columns
        mega_targets = pd.read_csv(next(out.glob("post_disclosure_mega_confirmation_N1_cap*/target_book.csv")))
        assert set(mega_targets["ticker"]) == {"AAA"}
        assert "post_disclosure_mega_confirmation_score" in mega_targets.columns
        assert payload.get("require_price_cache") is True


def test_satellite_selector_preserves_exposure_under_tight_cap() -> None:
    group = pd.DataFrame(
        [
            {
                "ticker": "CORE1",
                "portfolio_future_winner_engine_score_rank": 1.00,
                "portfolio_early_scout_engine_score_rank": 1.00,
                "portfolio_monster_early_score_rank": 1.00,
                "h6_dynamic_leader_score_rank": 1.00,
                "selection_market_confirmation_score_rank": 0.90,
                "rs_acceleration_score_rank": 0.90,
                "industry_group_strength_score_rank": 0.90,
                "entry_quality_score_rank": 0.90,
                "portfolio_risk_entry_block_score_safe_rank": 1.00,
                "portfolio_stale_mega_leader_score_safe_rank": 1.00,
            },
            {
                "ticker": "CORE2",
                "portfolio_future_winner_engine_score_rank": 0.95,
                "portfolio_early_scout_engine_score_rank": 0.95,
                "portfolio_monster_early_score_rank": 0.95,
                "h6_dynamic_leader_score_rank": 0.95,
                "selection_market_confirmation_score_rank": 0.85,
                "rs_acceleration_score_rank": 0.85,
                "industry_group_strength_score_rank": 0.85,
                "entry_quality_score_rank": 0.85,
                "portfolio_risk_entry_block_score_safe_rank": 1.00,
                "portfolio_stale_mega_leader_score_safe_rank": 1.00,
            },
            {
                "ticker": "SAT",
                "portfolio_future_winner_engine_score_rank": 0.10,
                "portfolio_early_scout_engine_score_rank": 0.10,
                "portfolio_monster_early_score_rank": 0.10,
                "h6_dynamic_leader_score_rank": 0.10,
                "selection_market_confirmation_score_rank": 1.00,
                "rs_acceleration_score_rank": 1.00,
                "industry_group_strength_score_rank": 1.00,
                "entry_quality_score_rank": 1.00,
                "post_disclosure_price_confirmed_score_rank": 1.00,
                "post_disclosure_discovery_score_rank": 1.00,
                "pda_13f_first_buy_surprise_score_rank": 1.00,
                "pda_form4_open_market_buy_score_rank": 1.00,
                "pda_etf_new_or_increase_score_rank": 1.00,
                "post_disclosure_price_confirmed_score": 1.00,
                "pda_13f_first_buy_surprise_score": 1.00,
                "pda_form4_open_market_buy_score": 0.00,
                "pda_etf_new_or_increase_score": 0.00,
                "portfolio_risk_entry_block_score_safe_rank": 1.00,
                "portfolio_stale_mega_leader_score_safe_rank": 1.00,
            },
        ]
    ).fillna(0.5)
    selected, weights = select_satellite_targets(group, target_n=3, single_name_cap=0.33)
    assert set(selected["ticker"]) == {"CORE1", "CORE2", "SAT"}
    assert weights.sum() > 0.98
    satellite_weight = float(weights[selected["ticker"].tolist().index("SAT")])
    assert 0.32 <= satellite_weight <= 0.33


def test_optional_satellite_requires_strong_supported_signal() -> None:
    group = pd.DataFrame(
        [
            {
                "ticker": "CORE1",
                "portfolio_future_winner_engine_score_rank": 1.00,
                "portfolio_early_scout_engine_score_rank": 1.00,
                "portfolio_monster_early_score_rank": 1.00,
                "h6_dynamic_leader_score_rank": 1.00,
                "selection_market_confirmation_score_rank": 0.90,
                "rs_acceleration_score_rank": 0.90,
                "industry_group_strength_score_rank": 0.90,
                "entry_quality_score_rank": 0.90,
                "portfolio_risk_entry_block_score_safe_rank": 1.00,
                "portfolio_stale_mega_leader_score_safe_rank": 1.00,
            },
            {
                "ticker": "CORE2",
                "portfolio_future_winner_engine_score_rank": 0.95,
                "portfolio_early_scout_engine_score_rank": 0.95,
                "portfolio_monster_early_score_rank": 0.95,
                "h6_dynamic_leader_score_rank": 0.95,
                "selection_market_confirmation_score_rank": 0.85,
                "rs_acceleration_score_rank": 0.85,
                "industry_group_strength_score_rank": 0.85,
                "entry_quality_score_rank": 0.85,
                "portfolio_risk_entry_block_score_safe_rank": 1.00,
                "portfolio_stale_mega_leader_score_safe_rank": 1.00,
            },
            {
                "ticker": "WEAK",
                "portfolio_future_winner_engine_score_rank": 0.70,
                "portfolio_early_scout_engine_score_rank": 0.70,
                "portfolio_monster_early_score_rank": 0.70,
                "h6_dynamic_leader_score_rank": 0.70,
                "selection_market_confirmation_score_rank": 0.55,
                "rs_acceleration_score_rank": 0.55,
                "industry_group_strength_score_rank": 0.55,
                "entry_quality_score_rank": 0.55,
                "post_disclosure_price_confirmed_score_rank": 1.00,
                "post_disclosure_discovery_score_rank": 1.00,
                "pda_13f_first_buy_surprise_score_rank": 1.00,
                "post_disclosure_price_confirmed_score": 0.25,
                "post_disclosure_price_confirmation_score": 0.20,
                "pda_13f_first_buy_surprise_score": 0.80,
                "portfolio_risk_entry_block_score_safe_rank": 1.00,
                "portfolio_stale_mega_leader_score_safe_rank": 1.00,
            },
            {
                "ticker": "STRONG",
                "portfolio_future_winner_engine_score_rank": 0.80,
                "portfolio_early_scout_engine_score_rank": 0.80,
                "portfolio_monster_early_score_rank": 0.80,
                "h6_dynamic_leader_score_rank": 0.80,
                "selection_market_confirmation_score_rank": 0.80,
                "rs_acceleration_score_rank": 0.80,
                "industry_group_strength_score_rank": 0.80,
                "entry_quality_score_rank": 0.80,
                "post_disclosure_price_confirmed_score_rank": 1.00,
                "post_disclosure_discovery_score_rank": 1.00,
                "pda_13f_first_buy_surprise_score_rank": 1.00,
                "post_disclosure_price_confirmed_score": 0.70,
                "post_disclosure_price_confirmation_score": 0.65,
                "pda_13f_first_buy_surprise_score": 0.80,
                "portfolio_risk_entry_block_score_safe_rank": 1.00,
                "portfolio_stale_mega_leader_score_safe_rank": 1.00,
            },
        ]
    ).fillna(0.5)

    selected, weights = select_satellite_targets(group, target_n=3, single_name_cap=0.33, optional=True)
    assert set(selected["ticker"]) == {"CORE1", "CORE2", "STRONG"}
    assert "WEAK" not in set(selected["ticker"])
    assert weights.sum() > 0.98
    satellite_weight = float(weights[selected["ticker"].tolist().index("STRONG")])
    assert 0.32 <= satellite_weight <= 0.33


def main() -> int:
    test_alpha_selector_grid_runs_broker_replay_without_forward_selection()
    test_satellite_selector_preserves_exposure_under_tight_cap()
    test_optional_satellite_requires_strong_supported_signal()
    print("alpha_selector_broker_grid_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

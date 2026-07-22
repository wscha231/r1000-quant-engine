#!/usr/bin/env python3
"""Smoke checks for review-only current relative-strength portfolio proposals."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.build_current_relative_strength_portfolios import (  # noqa: E402
    build,
    build_target,
    constrained_select,
    prepare_ranked,
    validate_source_freshness,
)
from tools.build_current_relative_strength_ranking import build_ranking  # noqa: E402
from tools.reserve_asset_policy import (  # noqa: E402
    BROKER_CASH_OR_MMF,
    reserve_reason_reconciliation,
    resolve_reserve_asset_policy,
)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_frame(count: int = 24) -> pd.DataFrame:
    sectors = ["Technology", "Health Care", "Financials", "Industrials", "Energy", "Real Estate"]
    rows = []
    for index in range(1, count + 1):
        rows.append(
            {
                "ticker": f"T{index:02d}",
                "Name": f"Company {index:02d}",
                "sector": sectors[(index - 1) % len(sectors)],
                "sector_normalized": sectors[(index - 1) % len(sectors)],
                "industry_group": f"Industry {(index - 1) % 12:02d}",
                "optimization_rank": index,
                "optimization_score": 101.0 - index,
                "research_status": (
                    "A_ENTRY_READY_RESEARCH" if index % 4 == 0 else "B_PULLBACK_WATCH"
                ),
                "valuation_close_date": "2026-07-21",
                "current_price_live": 100.0 + index,
                "rs_spy_1m": 0.01 * index,
                "rs_spy_3m": 0.02 * index,
                "rs_spy_6m": 0.03 * index,
                "rs_spy_12m": 0.04 * index,
            }
        )
    return pd.DataFrame(rows)


def scored_frame(count: int = 40) -> pd.DataFrame:
    rows = []
    for index in range(1, count + 1):
        strength = float(count - index + 1) / count
        rows.append(
            {
                "ticker": f"R{index:02d}",
                "Name": f"Rank Company {index:02d}",
                "sector": f"Sector {(index - 1) % 10:02d}",
                "industry_group": f"Industry {(index - 1) % 20:02d}",
                "registered_ranking_eligible": True,
                "research_eligible_after_quarantine": True,
                "corporate_action_quarantine": False,
                "score_total": strength,
                "research_score_rank": index,
                "ret_1d": strength / 100.0,
                "mom_1m": strength / 10.0,
                "mom_3m": strength / 5.0,
                "mom_6m": strength / 4.0,
                "mom_12m": strength / 3.0,
                "price_above_ma50": 1,
                "price_above_ma200": 1,
                "broken_momentum_penalty": 0,
                "overheat_signal_score": 0,
                "current_price_live": 100.0 + index,
                "valuation_price_cutoff_date": "2026-07-21",
            }
        )
    return pd.DataFrame(rows)


def benchmark_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "benchmark": ticker,
                "date": "2026-07-21",
                "ret_1d": 0.001,
                "ret_1m": 0.01,
                "ret_3m": 0.02,
                "ret_6m": 0.03,
                "ret_12m": 0.04,
            }
            for ticker in ("SPY", "QQQ", "SMH")
        ]
    )


def test_ranking_recomputes_relative_strength_and_diversified_shortlists() -> None:
    ranked, top30, focus15 = build_ranking(
        scored_frame(), benchmark_frame(), valuation_date="2026-07-21"
    )
    assert len(ranked) == 40
    assert len(top30) == 30
    assert len(focus15) == 15
    assert ranked.iloc[0]["ticker"] == "R01"
    assert abs(float(ranked.iloc[0]["rs_spy_1m"]) - 0.09) < 1e-12
    assert int(top30["sector_normalized"].value_counts().max()) <= 4
    assert int(top30["industry_group"].value_counts().max()) <= 2
    assert int(focus15["sector_normalized"].value_counts().max()) <= 3
    assert int(focus15["industry_group"].value_counts().max()) <= 2


def test_source_freshness_rejects_stale_input() -> None:
    ranked = candidate_frame()
    assert (
        validate_source_freshness(
            ranked, as_of_date="2026-07-23", max_signal_age_days=3
        )
        == "2026-07-21"
    )
    try:
        validate_source_freshness(
            ranked, as_of_date="2026-07-25", max_signal_age_days=3
        )
    except ValueError as exc:
        assert "stale relative-strength source" in str(exc)
    else:
        raise AssertionError("stale source was accepted")


def test_constrained_selection_and_explicit_reserve_contract() -> None:
    ranked = prepare_ranked(candidate_frame())
    selected = constrained_select(ranked, count=5, sector_cap=2, industry_cap=1)
    assert len(selected) == 5
    assert int(selected["sector_normalized"].value_counts().max()) <= 2
    assert int(selected["industry_group"].value_counts().max()) <= 1
    target, summary = build_target(
        selected,
        portfolio_kind="concentrated",
        proposal="concentrated_n5",
        valuation_date="2026-07-21",
        single_cap=0.30,
        data_blocked=True,
    )
    assert abs(float(target["target_weight"].sum()) - 1.0) < 1e-9
    assert set(target.loc[target["ticker"].eq("CASH"), "research_status"]) == {"RESERVE"}
    assert summary["cash_weight"] >= 0.10
    assert summary["data_block_reserve"] == 0.08
    assert summary["transaction_buffer"] == 0.02
    assert float(target.loc[target["ticker"].ne("CASH"), "target_weight"].max()) <= 0.30
    hashes = target["reserve_reason_source_hash"].dropna().unique()
    assert len(hashes) == 1 and len(str(hashes[0])) == 64
    reconciliation = reserve_reason_reconciliation(
        target,
        policy=resolve_reserve_asset_policy(BROKER_CASH_OR_MMF),
        weight_col="target_weight",
    )
    assert reconciliation["reserve_reason_source_hash"] == str(hashes[0])


def test_build_writes_review_only_targets_and_integer_transition_previews() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ranked_path = root / "ranked.csv"
        price_path = root / "prices.csv"
        selection_summary_path = root / "selection_summary.json"
        main_account_path = root / "main_account.json"
        concentrated_account_path = root / "concentrated_account.json"
        output_dir = root / "proposals"
        ranked = candidate_frame()
        ranked.loc[ranked["ticker"].eq("T01"), "research_status"] = (
            "C_RISK_OR_EXTENSION_WATCH"
        )
        ranked.to_csv(ranked_path, index=False)
        prices = pd.concat(
            [
                ranked[["ticker", "current_price_live"]],
                pd.DataFrame(
                    [
                        {"ticker": "OLD1", "current_price_live": 80.0},
                        {"ticker": "OLD2", "current_price_live": 60.0},
                    ]
                ),
            ],
            ignore_index=True,
        )
        prices.to_csv(price_path, index=False)
        selection_summary_path.write_text(
            json.dumps({"upstream_full_bundle_ready": False}), encoding="utf-8"
        )
        main_account = {
            "as_of_date": "2026-07-17",
            "cash_usd": 1_000.0,
            "positions": [
                {"ticker": "T01", "shares": 10, "price": 100.0},
                {"ticker": "OLD1", "shares": 10, "price": 75.0},
            ],
        }
        concentrated_account = {
            "as_of_date": "2026-07-17",
            "cash_usd": 500.0,
            "positions": [
                {"ticker": "OLD1", "shares": 10, "price": 75.0},
                {"ticker": "OLD2", "shares": 10, "price": 55.0},
            ],
        }
        main_account_path.write_text(json.dumps(main_account), encoding="utf-8")
        concentrated_account_path.write_text(
            json.dumps(concentrated_account), encoding="utf-8"
        )
        before = {
            main_account_path: file_hash(main_account_path),
            concentrated_account_path: file_hash(concentrated_account_path),
        }
        args = argparse.Namespace(
            ranked_candidates=str(ranked_path),
            selection_summary=str(selection_summary_path),
            price_source=str(price_path),
            main_account=str(main_account_path),
            concentrated_account=str(concentrated_account_path),
            output_dir=str(output_dir),
            as_of_date="2026-07-23",
            max_signal_age_days=3,
            main_count=15,
            main_sector_cap=3,
            main_industry_cap=2,
            main_single_cap=0.18,
            concentrated_n3_single_cap=0.40,
            concentrated_n5_single_cap=0.30,
            cost_bps=25.0,
        )
        payload = build(args)
        assert payload["status"] == "READY_REVIEW_ONLY_CURRENT_PORTFOLIO_PROPOSALS"
        assert payload["recommended_concentrated_proposal"] == "concentrated_n5"
        assert payload["target_books_mutated"] is False
        assert payload["paper_accounts_mutated"] is False
        assert payload["orders_generated"] is False
        assert payload["order_preview_generated"] is True
        assert payload["backtest_executed"] is False
        assert payload["fullrun_executed"] is False
        assert (
            payload["transition_previews"]["concentrated_n5"][
                "estimated_weight_turnover_including_cash"
            ]
            > payload["transition_previews"]["concentrated_n5"][
                "estimated_equity_weight_turnover_ex_cash"
            ]
        )
        assert file_hash(main_account_path) == before[main_account_path]
        assert file_hash(concentrated_account_path) == before[concentrated_account_path]
        target = pd.read_csv(output_dir / "concentrated_target_n5_recommended.csv")
        assert len(target.loc[target["ticker"].ne("CASH")]) == 5
        assert "T01" not in set(target["ticker"])
        assert abs(float(target["target_weight"].sum()) - 1.0) < 1e-9
        transition = pd.read_csv(output_dir / "concentrated_n5_transition.csv")
        assert set(transition.loc[transition["decision"].eq("EXIT"), "ticker"]) == {
            "OLD1",
            "OLD2",
        }
        preview = pd.read_csv(output_dir / "concentrated_n5_order_preview.csv")
        assert set(preview["side"]) == {"BUY", "SELL"}
        assert (preview["quantity"] % 1 == 0).all()
        assert not preview["live_order"].astype(bool).any()


def main() -> None:
    test_ranking_recomputes_relative_strength_and_diversified_shortlists()
    test_source_freshness_rejects_stale_input()
    test_constrained_selection_and_explicit_reserve_contract()
    test_build_writes_review_only_targets_and_integer_transition_previews()
    print("current_relative_strength_portfolios_smoke: PASS")


if __name__ == "__main__":
    main()

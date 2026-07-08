#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.run_run287_multisource_fusion_broker_ab as mod  # noqa: E402


class Args:
    pass


def candidate_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in range(40):
        good = idx % 2 == 0
        oos = idx >= 20
        ticker = "AAA" if good else "BBB"
        rows.append(
            {
                "rebalance_date": "2025-01-31" if oos else "2023-01-31",
                "ticker": ticker,
                "Name": f"{ticker} Corp",
                "sector": "Technology",
                "industry_group": "Semiconductors",
                "period_forward_return": 0.12 if good else -0.08,
                "actual_results_score": 0.9 if good else 0.1,
                "profitability_inflection_score": 0.8 if good else 0.2,
                "capital_efficiency_score": 0.8 if good else 0.2,
                "gross_margins": 0.7 if good else 0.3,
                "relative_strength_composite": 0.9 if good else 0.1,
                "rs_acceleration_score": 0.8 if good else 0.2,
                "mom_6m": 0.4 if good else -0.2,
                "mom_12m": 0.5 if good else -0.3,
                "trend_template_full": 1.0 if good else 0.0,
                "entry_quality_score": 0.8 if good else 0.2,
                "style_row_breakout_fit": 0.8 if good else 0.2,
                "style_row_compounder_fit": 0.8 if good else 0.2,
                "style_liquidity_tailwind_score": 0.7 if good else 0.3,
                "regime_state_score": 0.7 if good else 0.3,
                "style_rate_pressure_score": 0.1 if good else 0.8,
                "style_inflation_pressure_score": 0.1 if good else 0.8,
                "style_overheat_risk_score": 0.1 if good else 0.8,
                "risk_penalty": 0.1 if good else 0.9,
                "overheat_penalty": 0.1 if good else 0.8,
                "atr14_pct": 0.2 if good else 0.9,
            }
        )
    return rows


def target_rows(portfolio_kind: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for date in ["2023-01-31", "2025-01-31", "2025-02-03"]:
        rows.append(
            {
                "rebalance_date": date,
                "ticker": "CASH",
                "weight": 0.20,
                "target_weight": 0.20,
                "portfolio_kind": portfolio_kind,
            }
        )
        rows.extend(
            [
                {
                    "rebalance_date": date,
                    "ticker": "AAA",
                    "weight": 0.40,
                    "target_weight": 0.40,
                    "effective_single_weight_cap": 0.60,
                    "portfolio_kind": portfolio_kind,
                },
                {
                    "rebalance_date": date,
                    "ticker": "BBB",
                    "weight": 0.40,
                    "target_weight": 0.40,
                    "effective_single_weight_cap": 0.60,
                    "portfolio_kind": portfolio_kind,
                },
            ]
        )
    return rows


def form4_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for ticker, code, available in [
        ("AAA", "P", "2022-12-16T21:00:00Z"),
        ("BBB", "S", "2022-12-16T21:00:00Z"),
        ("AAA", "P", "2024-12-16T21:00:00Z"),
        ("BBB", "S", "2024-12-16T21:00:00Z"),
    ]:
        rows.append(
            {
                "issuer_ticker": ticker,
                "issuer_cik10": "0000000001" if ticker == "AAA" else "0000000002",
                "reporting_owner_cik": "0000000101",
                "reporting_owner_name": f"{ticker} Owner",
                "officer_title": "Chief Executive Officer",
                "is_director": True,
                "is_officer": True,
                "is_ten_percent_owner": False,
                "transaction_date": available[:10],
                "filing_date": available[:10],
                "accepted_at": available,
                "available_from": available,
                "transaction_code": code,
                "transaction_shares": 10_000,
                "transaction_price": 25.0,
                "transaction_value": 250_000.0,
                "shares_owned_after": 50_000,
                "accession_number": f"{ticker}-{available[:4]}",
            }
        )
    return rows


def holdings_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for period, available, aaa_shares, bbb_shares in [
        ("2022-09-30", "2022-11-14T21:00:00Z", 100_000, 100_000),
        ("2022-12-31", "2023-01-15T21:00:00Z", 200_000, 25_000),
        ("2024-09-30", "2024-11-14T21:00:00Z", 200_000, 100_000),
        ("2024-12-31", "2025-01-15T21:00:00Z", 350_000, 25_000),
    ]:
        for ticker, shares in [("AAA", aaa_shares), ("BBB", bbb_shares)]:
            rows.append(
                {
                    "manager_cik": "0000100000",
                    "manager_name": "Example Manager",
                    "report_period": period,
                    "filing_date": available[:10],
                    "accepted_at": available,
                    "available_from": available,
                    "ticker_mapped": ticker,
                    "shares": shares,
                    "market_value_usd": shares * 10.0,
                }
            )
    return rows


def fake_replay(**kwargs):
    arm = kwargs["target_book"].parent.name
    portfolio = kwargs["portfolio_kind"]
    base_cagr = 0.34 if portfolio == "main" else 0.48
    max_dd = -0.255 if portfolio == "main" else -0.23
    if arm == "growth_confirmation_top_quintile_tilt05":
        base_cagr += 0.006
    elif arm == "growth_confirmation_top_quintile_tilt10":
        base_cagr += 0.012
        max_dd = -0.245 if portfolio == "main" else -0.225
    return {
        "status": "completed",
        "metric_mode": "broker_ledger_next_close_cash_carry",
        "cagr": base_cagr,
        "max_dd": max_dd,
        "sharpe": 1.3,
        "years": 7.1,
        "start_date": "2019-06-03",
        "end_date": "2026-07-06",
        "avg_cash_weight": 0.20,
        "trade_count": 12,
        "total_fees_usd": 100.0,
        "gross_traded_usd": 10000.0,
        "cash_interest_accrued_usd": 1000.0,
        "windows": {
            "is": {"cagr": base_cagr * 0.8, "max_dd": -0.18},
            "oos": {"cagr": base_cagr * 1.2, "max_dd": max_dd},
        },
    }


def test_multisource_fusion_broker_ab_research_only_contract_blocked() -> None:
    original_replay = mod.broker_ab.run_broker_replay
    mod.broker_ab.run_broker_replay = fake_replay
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            latest = root / "latest" / "alphaops_vnext"
            latest.mkdir(parents=True)
            pd.DataFrame(target_rows("main")).to_csv(latest / "official_main_target_book.csv", index=False)
            pd.DataFrame(target_rows("concentrated")).to_csv(latest / "official_concentrated_target_book.csv", index=False)
            candidate = root / "candidate.csv"
            form4 = root / "form4.parquet"
            sec13f = root / "13f.parquet"
            parity = root / "parity.json"
            survivorship = root / "survivorship.json"
            pd.DataFrame(candidate_rows()).to_csv(candidate, index=False)
            pd.DataFrame(form4_rows()).to_parquet(form4, index=False)
            pd.DataFrame(holdings_rows()).to_parquet(sec13f, index=False)
            parity.write_text('{"runner_parity_status":"parity_documented_gap","runner_parity_reason":"fixture gap"}\n')
            survivorship.write_text(
                '{"label":"proxy","unmeasured_component":"delisted_exclusion",'
                '"survivorship_inflation_estimate_cagr_pp":0.0,'
                '"survivorship_inflation_estimate":{"cagr_pp_lower_bound":0.0,"label":"proxy",'
                '"method":"fixture","unmeasured_component":"delisted_exclusion"}}\n'
            )

            args = Args()
            args.latest_run = str(root / "latest")
            args.candidate_book = str(candidate)
            args.form4_path = str(form4)
            args.sec13f_path = str(sec13f)
            args.manager_universe = str(root / "missing_managers.csv")
            args.portfolio_kind = ["main", "concentrated"]
            args.signals = ["growth_confirmation_score", "w4_consensus_score"]
            args.price_cache = str(root / "cache_prices")
            args.output_dir = str(root / "out")
            args.oos_start = "2024-07-01"
            args.cost_bps = 25.0
            args.max_fill_lag_days = 7
            args.starting_capital = 100000.0
            args.single_cap = 0.60
            args.cash_carry_mode = "risk_free_rate"
            args.cash_rate_source = "DGS3MO"
            args.cash_rate_path = ""
            args.cash_rate_lag_days = 1
            args.cash_carry_haircut_bps = 50.0
            args.cash_carry_day_count = 365
            args.replay_end_date = "2026-07-06"
            args.official_baseline_end_date = "2026-07-06"
            args.parity_summary = str(parity)
            args.survivorship_summary = str(survivorship)
            args.max_missing_score_rate = 0.001

            payload = mod.run(args)
            assert payload["status"] == "completed"
            assert payload["research_only"] is True
            assert payload["candidate_allowed"] is False
            assert payload["fullrun_dispatched"] is False
            assert payload["new_alpha_hook_added"] is False
            assert payload["threshold_tuning_performed"] is False
            assert payload["used_forward_return_in_ranking"] is False
            assert payload["production_promotion_allowed"] is False
            assert payload["live_trading_enabled"] is False
            assert payload["runner_parity_status"] == "parity_documented_gap"
            assert "runner_parity_not_exact" in payload["measurement_contract_acceptance_blockers"]
            assert payload["measurement_contract_acceptance_allowed"] is False
            assert payload["decision_label"] == "broker_ab_positive_but_measurement_contract_blocks_acceptance"
            assert set(payload["portfolios"]) == {"main", "concentrated"}
            assert payload["signals"] == ["growth_confirmation_score", "w4_consensus_score"]
            assert any(row["target_contract_pass"] for row in payload["arm_rows"])
            assert payload["enriched_target_books"]["main"]["asof_prior_score_rows"] == 2
            assert payload["enriched_target_books"]["main"]["missing_fusion_score_non_cash_rows"] == 0
            assert (root / "out" / "enriched_target_books" / "main_target_book.csv").exists()
            assert (root / "out" / "enriched_target_books" / "concentrated_target_book.csv").exists()
            enriched = pd.read_csv(root / "out" / "enriched_target_books" / "concentrated_target_book.csv")
            assert "w4_consensus_score" in enriched.columns
            assert (root / "out" / "summary.json").exists()
            assert (root / "out" / "arm_metrics.csv").exists()
            assert (root / "out" / "report.md").exists()
    finally:
        mod.broker_ab.run_broker_replay = original_replay


def main() -> int:
    test_multisource_fusion_broker_ab_research_only_contract_blocked()
    print("run287_multisource_fusion_broker_ab_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_run287_multisource_fusion_screen import run  # noqa: E402


class Args:
    pass


def candidate_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in range(100):
        good = idx % 2 == 0
        oos = idx >= 50
        rows.append(
            {
                "rebalance_date": "2025-01-31" if oos else "2023-01-31",
                "ticker": "AAA" if good else "BBB",
                "Name": "AAA Corp" if good else "BBB Corp",
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


def form4_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for ticker, code, value in [("AAA", "P", 250_000.0), ("BBB", "S", 250_000.0)]:
        for suffix, available in [("is", "2022-12-16T21:00:00Z"), ("oos", "2024-12-16T21:00:00Z")]:
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
                    "transaction_value": value,
                    "shares_owned_after": 50_000,
                    "accession_number": f"{ticker}-{suffix}",
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
        rows.append(
            {
                "manager_cik": "0000100000",
                "manager_name": "Example Manager",
                "report_period": period,
                "filing_date": available[:10],
                "accepted_at": available,
                "available_from": available,
                "ticker_mapped": "AAA",
                "shares": aaa_shares,
                "market_value_usd": aaa_shares * 10.0,
            }
        )
        rows.append(
            {
                "manager_cik": "0000100000",
                "manager_name": "Example Manager",
                "report_period": period,
                "filing_date": available[:10],
                "accepted_at": available,
                "available_from": available,
                "ticker_mapped": "BBB",
                "shares": bbb_shares,
                "market_value_usd": bbb_shares * 10.0,
            }
        )
    return rows


def test_multisource_fusion_research_only_positive_screen() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate = root / "candidate.csv"
        form4 = root / "form4.parquet"
        sec13f = root / "13f.parquet"
        out = root / "out"
        pd.DataFrame(candidate_rows()).to_csv(candidate, index=False)
        pd.DataFrame(form4_rows()).to_parquet(form4, index=False)
        pd.DataFrame(holdings_rows()).to_parquet(sec13f, index=False)

        args = Args()
        args.input = str(candidate)
        args.form4_path = str(form4)
        args.sec13f_path = str(sec13f)
        args.manager_universe = str(root / "missing_managers.csv")
        args.output_dir = str(out)
        args.oos_start = "2024-07-01"
        args.min_rows = 5
        args.min_oos_high_count = 5
        args.sample_rows = 50
        payload = run(args)

        assert payload["status"] == "completed"
        assert payload["research_only"] is True
        assert payload["candidate_allowed"] is False
        assert payload["fullrun_dispatched"] is False
        assert payload["new_alpha_hook_added"] is False
        assert payload["threshold_tuning_performed"] is False
        assert payload["production_promotion_allowed"] is False
        assert payload["live_trading_enabled"] is False
        assert payload["used_forward_return_in_ranking"] is False
        assert payload["forward_returns_audit_only"] is True
        assert "drawdown_aware_fusion_score" in payload["positive_signals"]
        assert payload["decision_label"] == "multisource_fusion_positive_requires_broker_ab_review"

        sample = pd.read_csv(out / "enriched_candidate_sample.csv")
        assert "financial_statement_proxy_score" in sample.columns
        assert "technical_momentum_score" in sample.columns
        assert "macro_regime_score" in sample.columns
        assert "w4_sec_score" in sample.columns
        assert "risk_control_score" in sample.columns
        assert (out / "summary.json").exists()
        assert (out / "signal_stats.csv").exists()
        assert (out / "report.md").exists()


def main() -> int:
    test_multisource_fusion_research_only_positive_screen()
    print("run287_multisource_fusion_screen_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

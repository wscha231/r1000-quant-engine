#!/usr/bin/env python3
"""Smoke tests for the standalone smart-money ranking report."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_smart_money_top30 import build_smart_money_rank  # noqa: E402


def test_smart_money_convergence_ranks_first() -> None:
    institutional = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "latest_available_from": "2026-05-15T20:00:00+00:00",
                "sec_13f_manager_count": 8,
                "sec_13f_buying_manager_count": 6,
                "sec_13f_selling_manager_count": 1,
                "sec_13f_new_position_manager_count": 1,
                "sec_13f_total_value_usd": 500_000_000,
                "sec_13f_value_delta_usd": 100_000_000,
                "sec_13f_smart_money_score": 0.70,
                "sec_13f_crowding_score": 0.20,
                "sec_13f_stale_penalty": 0.0,
                "institutional_evidence_score": 0.70,
                "institutional_evidence_confidence_score": 0.80,
            },
            {
                "ticker": "CCC",
                "latest_available_from": "2026-05-15T20:00:00+00:00",
                "sec_13f_manager_count": 5,
                "sec_13f_buying_manager_count": 4,
                "sec_13f_selling_manager_count": 0,
                "sec_13f_new_position_manager_count": 1,
                "sec_13f_total_value_usd": 200_000_000,
                "sec_13f_value_delta_usd": 50_000_000,
                "sec_13f_smart_money_score": 0.60,
                "sec_13f_crowding_score": 0.10,
                "sec_13f_stale_penalty": 0.0,
                "institutional_evidence_score": 0.60,
                "institutional_evidence_confidence_score": 0.70,
            },
        ]
    )
    form4 = pd.DataFrame(
        [
            {
                "ticker": "BBB",
                "latest_available_from": "2026-05-19T20:00:00+00:00",
                "insider_buy_count": 3,
                "insider_buy_value": 2_000_000,
                "insider_sale_value": 0,
                "sec_form4_open_market_buy_score": 0.90,
                "sec_form4_cluster_buy_score": 0.90,
                "sec_form4_ceo_cfo_buy_score": 0.90,
                "sec_form4_sale_pressure_score": 0.0,
                "early_evidence_score": 0.90,
                "evidence_confidence_score": 0.90,
            },
            {
                "ticker": "CCC",
                "latest_available_from": "2026-05-19T20:00:00+00:00",
                "insider_buy_count": 2,
                "insider_buy_value": 1_500_000,
                "insider_sale_value": 0,
                "sec_form4_open_market_buy_score": 0.60,
                "sec_form4_cluster_buy_score": 0.60,
                "sec_form4_ceo_cfo_buy_score": 0.60,
                "sec_form4_sale_pressure_score": 0.0,
                "early_evidence_score": 0.60,
                "evidence_confidence_score": 0.70,
            },
        ]
    )
    etf = pd.DataFrame(
        [
            {
                "ticker": "CCC",
                "latest_available_from": "2026-05-20T00:00:00+00:00",
                "etf_consensus_count": 4,
                "etf_weight_sum": 0.0,
                "etf_theme_leadership_score": 0.50,
                "etf_crowding_score": 0.20,
                "etf_holdings_score": 0.60,
                "etf_evidence_confidence": 0.80,
                "etf_themes": "ai_infrastructure,semiconductors",
                "etf_sources": "CHAT,SMH",
            }
        ]
    )
    ranked = build_smart_money_rank(institutional, form4, etf)
    assert ranked.loc[0, "ticker"] == "CCC"
    assert bool(ranked.loc[0, "smart_money_convergence_flag"]) is True
    assert int(ranked.loc[0, "evidence_source_count"]) == 3
    assert "13F:" in ranked.loc[0, "smart_money_explanation"]
    assert "Form4:" in ranked.loc[0, "smart_money_explanation"]
    assert "ETF:" in ranked.loc[0, "smart_money_explanation"]


def test_smart_money_cli_writes_research_only_outputs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        institutional = root / "13f.csv"
        form4 = root / "form4.csv"
        etf = root / "etf.csv"
        out = root / "smart_money"
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "latest_available_from": "2026-05-15T20:00:00+00:00",
                    "sec_13f_manager_count": 3,
                    "institutional_evidence_score": 0.8,
                    "institutional_evidence_confidence_score": 0.8,
                }
            ]
        ).to_csv(institutional, index=False)
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "latest_available_from": "2026-05-16T20:00:00+00:00",
                    "insider_buy_count": 1,
                    "insider_buy_value": 500_000,
                    "early_evidence_score": 0.5,
                    "evidence_confidence_score": 0.5,
                }
            ]
        ).to_csv(form4, index=False)
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "latest_available_from": "2026-05-17T20:00:00+00:00",
                    "etf_consensus_count": 2,
                    "etf_holdings_score": 0.4,
                    "etf_evidence_confidence": 0.5,
                }
            ]
        ).to_csv(etf, index=False)
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "run_smart_money_top30.py"),
                "--institutional",
                str(institutional),
                "--form4",
                str(form4),
                "--etf",
                str(etf),
                "--output-dir",
                str(out),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        summary = json.loads((out / "smart_money_summary.json").read_text(encoding="utf-8"))
        assert summary["research_only"] is True
        assert summary["production_activation_allowed"] is False
        assert summary["score_total_changed"] is False
        assert summary["ranked_tickers"] == 1
        assert (out / "top30_latest.csv").exists()
        assert (out / "report.md").exists()


def test_smart_money_workflow_braces_gdrive_base() -> None:
    workflow = (ROOT / ".github" / "workflows" / "smart_money_top30_refresh.yml").read_text(encoding="utf-8")
    assert "$BASEoutputs" not in workflow
    assert "${BASE}outputs/smart_money/" in workflow


def main() -> int:
    test_smart_money_convergence_ranks_first()
    test_smart_money_cli_writes_research_only_outputs()
    test_smart_money_workflow_braces_gdrive_base()
    print("smart_money_top30_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

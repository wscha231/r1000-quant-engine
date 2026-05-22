#!/usr/bin/env python3
"""Smoke tests for research-only evidence discovery universe expansion."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_evidence_discovery_universe import build_discovery_universe  # noqa: E402


def test_discovery_universe_combines_all_sources() -> None:
    institutional = pd.DataFrame(
        [
            {
                "ticker": "ALFA",
                "sec_13f_manager_count": 3,
                "sec_13f_buying_manager_count": 2,
                "sec_13f_new_position_manager_count": 1,
                "institutional_evidence_score": 0.8,
                "institutional_evidence_confidence_score": 0.9,
                "latest_available_from": "2026-05-15T20:00:00Z",
            },
            {
                "ticker": "BRAV",
                "sec_13f_manager_count": 1,
                "sec_13f_buying_manager_count": 1,
                "sec_13f_new_position_manager_count": 1,
                "institutional_evidence_score": 0.6,
                "institutional_evidence_confidence_score": 0.8,
            },
        ]
    )
    form4 = pd.DataFrame(
        [
            {
                "ticker": "ALFA",
                "insider_buy_count": 2,
                "insider_buy_value": 1_500_000,
                "early_evidence_score": 0.7,
                "evidence_confidence_score": 0.8,
                "latest_available_from": "2026-05-16T20:00:00Z",
            },
            {
                "ticker": "CHAR",
                "insider_buy_count": 1,
                "insider_buy_value": 200_000,
                "early_evidence_score": 0.5,
                "evidence_confidence_score": 0.7,
            },
        ]
    )
    etf = pd.DataFrame(
        [
            {
                "ticker": "ALFA",
                "etf_consensus_count": 2,
                "etf_holdings_score": 0.6,
                "etf_evidence_confidence": 0.9,
                "etf_themes": "ai_infra",
            },
            {
                "ticker": "DELT",
                "etf_consensus_count": 1,
                "etf_holdings_score": 0.45,
                "etf_evidence_confidence": 0.8,
                "etf_themes": "robotics",
            },
        ]
    )

    out = build_discovery_universe(institutional, form4, etf)
    assert not out.empty
    assert set(["ALFA", "BRAV", "CHAR", "DELT"]).issubset(set(out["ticker"]))
    alfa = out[out["ticker"] == "ALFA"].iloc[0]
    assert bool(alfa["has_13f"]) is True
    assert bool(alfa["has_form4"]) is True
    assert bool(alfa["has_etf"]) is True
    assert int(alfa["evidence_source_count"]) == 3
    assert alfa["candidate_bucket"] == "triple_source"
    assert out.iloc[0]["ticker"] == "ALFA"


def test_discovery_universe_cli_outputs_research_only_files() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        inst = root / "13f.csv"
        form4 = root / "form4.csv"
        etf = root / "etf.csv"
        out_dir = root / "out"
        pd.DataFrame(
            [
                {
                    "ticker": "ALFA",
                    "sec_13f_manager_count": 1,
                    "institutional_evidence_score": 1.0,
                    "institutional_evidence_confidence_score": 1.0,
                }
            ]
        ).to_csv(inst, index=False)
        pd.DataFrame(
            [
                {
                    "ticker": "BRAV",
                    "insider_buy_count": 1,
                    "early_evidence_score": 0.8,
                    "evidence_confidence_score": 1.0,
                }
            ]
        ).to_csv(form4, index=False)
        pd.DataFrame(
            [
                {
                    "ticker": "CHAR",
                    "etf_consensus_count": 1,
                    "etf_holdings_score": 0.7,
                    "etf_evidence_confidence": 1.0,
                }
            ]
        ).to_csv(etf, index=False)
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "build_evidence_discovery_universe.py"),
                "--institutional",
                str(inst),
                "--form4",
                str(form4),
                "--etf",
                str(etf),
                "--output-dir",
                str(out_dir),
                "--top-n",
                "10",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assert (out_dir / "latest.csv").exists()
        assert (out_dir / "evidence_discovery_universe.csv").exists()
        assert (out_dir / "summary.json").exists()
        latest = pd.read_csv(out_dir / "latest.csv")
        assert len(latest) == 3
        assert latest["evidence_discovery_score"].max() > 0.0


def test_discovery_universe_workflow_artifacts_are_synced() -> None:
    smart_money = (ROOT / ".github" / "workflows" / "smart_money_top30_refresh.yml").read_text(encoding="utf-8")
    post_disclosure = (ROOT / ".github" / "workflows" / "post_disclosure_alpha_pipeline.yml").read_text(encoding="utf-8")
    for workflow in (smart_money, post_disclosure):
        assert "tools/build_evidence_discovery_universe.py" in workflow
        assert "outputs/evidence_discovery_universe/" in workflow
        assert "outputs/full_rebuild_logs/evidence_discovery_universe.log" in workflow


if __name__ == "__main__":
    test_discovery_universe_combines_all_sources()
    test_discovery_universe_cli_outputs_research_only_files()
    test_discovery_universe_workflow_artifacts_are_synced()
    print("evidence_discovery_universe_smoke: PASS")

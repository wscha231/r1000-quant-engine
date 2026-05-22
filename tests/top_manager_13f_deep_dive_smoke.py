#!/usr/bin/env python3
"""Smoke tests for top-manager 13F detail discovery reports."""
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

from tools.run_top_manager_13f_deep_dive import add_period_rank, build_top_manager_deep_dive, select_top_managers  # noqa: E402


def _managers() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "label": "SITUATIONAL",
                "manager_name": "Situational Awareness LP",
                "cik10": "0002045724",
                "active": True,
                "verified_cik": True,
                "user_priority": 1,
                "external_performance_2y": "",
                "performance_26q1": 0.36,
                "allocation_tier": "high_conviction",
            },
            {
                "label": "WHALEROCK",
                "manager_name": "Whale Rock Capital Management LLC",
                "cik10": "0001545215",
                "active": True,
                "verified_cik": True,
                "user_priority": 4,
                "external_performance_2y": 1.98,
                "performance_26q1": "",
                "allocation_tier": "growth_hedge_high_conviction",
            },
            {
                "label": "INACTIVE",
                "manager_name": "Inactive Manager",
                "cik10": "0000000001",
                "active": False,
                "verified_cik": True,
                "user_priority": 2,
            },
        ]
    )


def _holdings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "manager_cik": "0002045724",
                "manager_name": "Situational Awareness LP",
                "report_period": "2025-12-31",
                "ticker_mapped": "CLSK",
                "cusip": "18452B209",
                "issuer_name": "CLEANSPARK INC",
                "shares": 100,
                "market_value_usd": 1_000,
                "put_call": "",
            },
            {
                "manager_cik": "0002045724",
                "manager_name": "Situational Awareness LP",
                "report_period": "2026-03-31",
                "accepted_at": "2026-05-15T18:33:35+00:00",
                "available_from": "2026-05-15T18:33:35+00:00",
                "ticker_mapped": "CLSK",
                "cusip": "18452B209",
                "issuer_name": "CLEANSPARK INC",
                "shares": 1_000,
                "market_value_usd": 20_000,
                "put_call": "",
            },
            {
                "manager_cik": "0002045724",
                "manager_name": "Situational Awareness LP",
                "report_period": "2026-03-31",
                "accepted_at": "2026-05-15T18:33:35+00:00",
                "available_from": "2026-05-15T18:33:35+00:00",
                "ticker_mapped": "TE",
                "cusip": "35834F104",
                "issuer_name": "T1 ENERGY INC",
                "shares": 5_000,
                "market_value_usd": 50_000,
                "put_call": "",
            },
            {
                "manager_cik": "0001545215",
                "manager_name": "Whale Rock Capital Management LLC",
                "report_period": "2025-12-31",
                "ticker_mapped": "NVDA",
                "cusip": "67066G104",
                "issuer_name": "NVIDIA CORPORATION",
                "shares": 100,
                "market_value_usd": 10_000,
                "put_call": "",
            },
            {
                "manager_cik": "0001545215",
                "manager_name": "Whale Rock Capital Management LLC",
                "report_period": "2026-03-31",
                "ticker_mapped": "NVDA",
                "cusip": "67066G104",
                "issuer_name": "NVIDIA CORPORATION",
                "shares": 50,
                "market_value_usd": 5_000,
                "put_call": "",
            },
            {
                "manager_cik": "0001545215",
                "manager_name": "Whale Rock Capital Management LLC",
                "report_period": "2026-03-31",
                "ticker_mapped": "APLD",
                "cusip": "038169207",
                "issuer_name": "APPLIED DIGITAL CORP",
                "shares": 3_000,
                "market_value_usd": 30_000,
                "put_call": "",
            },
        ]
    )


def test_select_top_managers_excludes_inactive() -> None:
    selected = select_top_managers(_managers(), top_manager_count=10)
    assert list(selected["label"]) == ["SITUATIONAL", "WHALEROCK"]
    assert "INACTIVE" not in set(selected["label"])


def test_deep_dive_surfaces_new_and_added_ai_infra() -> None:
    out = build_top_manager_deep_dive(_holdings(), _managers(), top_manager_count=10)
    assert not out.empty
    assert {"TE", "CLSK", "APLD"}.issubset(set(out["ticker"]))
    te = out[out["ticker"] == "TE"].iloc[0]
    assert te["event_type"] == "new_position"
    assert bool(te["ai_infra_theme_flag"]) is True
    assert "power_infrastructure" in te["theme_bucket"]
    clsk = out[out["ticker"] == "CLSK"].iloc[0]
    assert clsk["event_type"] == "added_position"
    assert bool(clsk["underfollowed_top_manager_pick"]) is True
    assert "crypto_compute" in clsk["theme_bucket"]


def test_deep_dive_can_emit_historical_events() -> None:
    history = build_top_manager_deep_dive(_holdings(), _managers(), top_manager_count=10, latest_only=False)
    assert not history.empty
    assert {"2025-12-31", "2026-03-31"}.issubset(set(history["report_period"]))
    initial = history[(history["ticker"] == "CLSK") & (history["report_period"] == "2025-12-31")].iloc[0]
    assert initial["event_type"] == "initial_position"
    latest = history[(history["ticker"] == "CLSK") & (history["report_period"] == "2026-03-31")].iloc[0]
    assert latest["event_type"] == "added_position"
    ranked = add_period_rank(history)
    assert "period_rank" in ranked.columns
    assert ranked["period_rank"].min() == 1


def test_top_manager_cli_and_workflow_outputs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        holdings = root / "holdings.csv"
        managers = root / "managers.csv"
        out = root / "deep_dive"
        _holdings().to_csv(holdings, index=False)
        _managers().to_csv(managers, index=False)
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "run_top_manager_13f_deep_dive.py"),
                "--holdings",
                str(holdings),
                "--managers",
                str(managers),
                "--output-dir",
                str(out),
                "--top-manager-count",
                "10",
                "--top-n",
                "20",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["research_only"] is True
        assert summary["production_activation_allowed"] is False
        assert summary["score_total_changed"] is False
        assert summary["new_or_added_rows"] >= 3
        assert summary["historical_event_rows"] >= summary["detailed_rows"]
        assert summary["historical_periods"] >= 2
        assert (out / "latest.csv").exists()
        assert (out / "selected_managers.csv").exists()
        assert (out / "historical_events.csv").exists()
        assert (out / "historical_coverage.csv").exists()

    workflow = (ROOT / ".github" / "workflows" / "smart_money_top30_refresh.yml").read_text(encoding="utf-8")
    assert "tools/run_top_manager_13f_deep_dive.py" in workflow
    assert "outputs/top_manager_13f_deep_dive/" in workflow
    assert "${BASE}outputs/top_manager_13f_deep_dive/" in workflow


def main() -> int:
    test_select_top_managers_excludes_inactive()
    test_deep_dive_surfaces_new_and_added_ai_infra()
    test_deep_dive_can_emit_historical_events()
    test_top_manager_cli_and_workflow_outputs()
    print("top_manager_13f_deep_dive_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Smoke tests for ETF holding event construction."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_etf_holding_event_builder import build_etf_holding_events, run  # noqa: E402


def sample_holdings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "etf_ticker": "SMH",
                "etf_label": "VanEck Semiconductor ETF",
                "theme": "semiconductors",
                "holding_ticker": "AAA",
                "holding_name": "AAA Inc",
                "holding_weight": 0.10,
                "source": "fixture",
                "as_of_date": "2026-04-30T00:00:00Z",
                "available_from": "2026-04-30T00:00:00Z",
            },
            {
                "etf_ticker": "SMH",
                "etf_label": "VanEck Semiconductor ETF",
                "theme": "semiconductors",
                "holding_ticker": "CCC",
                "holding_name": "CCC Inc",
                "holding_weight": 0.04,
                "source": "fixture",
                "as_of_date": "2026-04-30T00:00:00Z",
                "available_from": "2026-04-30T00:00:00Z",
            },
            {
                "etf_ticker": "SMH",
                "etf_label": "VanEck Semiconductor ETF",
                "theme": "semiconductors",
                "holding_ticker": "AAA",
                "holding_name": "AAA Inc",
                "holding_weight": 0.15,
                "source": "fixture",
                "as_of_date": "2026-05-31T00:00:00Z",
                "available_from": "2026-05-31T00:00:00Z",
            },
            {
                "etf_ticker": "SMH",
                "etf_label": "VanEck Semiconductor ETF",
                "theme": "semiconductors",
                "holding_ticker": "BBB",
                "holding_name": "BBB Inc",
                "holding_weight": 0.06,
                "source": "fixture",
                "as_of_date": "2026-05-31T00:00:00Z",
                "available_from": "2026-05-31T00:00:00Z",
            },
            {
                "etf_ticker": "BOTZ",
                "etf_label": "Global X Robotics ETF",
                "theme": "robotics_ai",
                "holding_ticker": "AAA",
                "holding_name": "AAA Inc",
                "holding_weight": 0.08,
                "source": "fixture",
                "as_of_date": "2026-05-31T00:00:00Z",
                "available_from": "2026-05-31T00:00:00Z",
            },
        ]
    )


def test_etf_holding_event_builder_detects_inclusion_weight_change_and_removal() -> None:
    events = build_etf_holding_events(sample_holdings(), change_threshold=0.0025)
    assert len(events) == 6
    counts = events["event_type"].value_counts().to_dict()
    assert counts["initial"] == 3
    assert counts["weight_increase"] == 1
    assert counts["inclusion"] == 1
    assert counts["removal"] == 1
    increase = events[(events["etf_ticker"].eq("SMH")) & (events["ticker"].eq("AAA")) & (events["event_type"].eq("weight_increase"))].iloc[0]
    assert abs(float(increase["holding_weight_delta"]) - 0.05) < 1e-9
    assert int(increase["etf_consensus_count"]) == 2
    assert float(increase["etf_event_seed_score"]) > 0
    removal = events[events["event_type"].eq("removal")].iloc[0]
    assert float(removal["etf_event_seed_score"]) < 0
    assert bool(events["research_only"].all()) is True
    assert bool((~events["production_activation_allowed"]).all()) is True


def test_etf_holding_event_builder_cli_outputs_summary() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        holdings = root / "data_pit" / "etf_holdings" / "etf_holdings.parquet"
        pit = root / "data_pit" / "etf_holdings" / "etf_holding_events.parquet"
        out = root / "outputs" / "etf_holding_events"
        holdings.parent.mkdir(parents=True, exist_ok=True)
        sample_holdings().to_parquet(holdings, index=False)
        payload = run(Namespace(holdings=str(holdings), pit_output=str(pit), output_dir=str(out), change_threshold=0.0025))
        assert payload["status"] == "completed", payload
        assert payload["event_rows"] == 6
        assert payload["ticker_count"] == 3
        saved = pd.read_parquet(pit)
        assert len(saved) == 6
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["score_total_changed"] is False


if __name__ == "__main__":
    test_etf_holding_event_builder_detects_inclusion_weight_change_and_removal()
    test_etf_holding_event_builder_cli_outputs_summary()
    print("etf_holding_event_builder_smoke: PASS")

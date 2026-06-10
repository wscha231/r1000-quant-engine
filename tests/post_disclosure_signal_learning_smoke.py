#!/usr/bin/env python3
"""Smoke tests for post-disclosure signal learning outputs."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_post_disclosure_signal_learning import run  # noqa: E402


def test_signal_learning_outputs_and_manager_pit_guard() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        labels = root / "data_pit" / "sec" / "post_disclosure_alpha_labels.parquet"
        out_dir = root / "outputs" / "post_disclosure_signal_learning"
        manager_output = root / "data_pit" / "sec" / "manager_disclosure_alpha_scores.parquet"
        labels.parent.mkdir(parents=True, exist_ok=True)

        pd.DataFrame(
            [
                {
                    "event_id": "13f:m1:aaa:20240102",
                    "source_type": "13f",
                    "manager_cik": "0000000001",
                    "manager_name": "Manager One",
                    "ticker": "AAA",
                    "event_type": "new",
                    "event_seed_score": 0.80,
                    "available_from": "2024-01-02T21:00:00Z",
                    "ret_21d": 0.08,
                    "ret_63d": 0.22,
                    "excess_spy_21d": 0.05,
                    "excess_spy_63d": 0.18,
                    "target_date_21d": "2024-02-01",
                    "target_date_63d": "2024-03-01",
                },
                {
                    "event_id": "13f:m1:bbb:20240315",
                    "source_type": "13f",
                    "manager_cik": "0000000001",
                    "manager_name": "Manager One",
                    "ticker": "BBB",
                    "event_type": "add",
                    "event_seed_score": 0.60,
                    "available_from": "2024-03-15T21:00:00Z",
                    "ret_21d": 0.03,
                    "ret_63d": 0.10,
                    "excess_spy_21d": 0.02,
                    "excess_spy_63d": 0.08,
                    "target_date_21d": "2024-04-10",
                    "target_date_63d": "2024-04-20",
                },
                {
                    "event_id": "form4:m1:ccc:20240501",
                    "source_type": "form4",
                    "manager_cik": "0000000001",
                    "manager_name": "Manager One",
                    "ticker": "CCC",
                    "event_type": "open_market_buy",
                    "event_seed_score": 0.40,
                    "available_from": "2024-05-01T21:00:00Z",
                    "ret_21d": 0.04,
                    "ret_63d": 0.06,
                    "excess_spy_21d": 0.02,
                    "excess_spy_63d": 0.04,
                    "target_date_21d": "2024-05-30",
                    "target_date_63d": "2024-07-01",
                },
                {
                    "event_id": "13f:m2:ddd:20240201",
                    "source_type": "13f",
                    "manager_cik": "0000000002",
                    "manager_name": "Manager Two",
                    "ticker": "DDD",
                    "event_type": "trim",
                    "event_seed_score": -0.70,
                    "available_from": "2024-02-01T21:00:00Z",
                    "ret_21d": -0.04,
                    "ret_63d": -0.12,
                    "excess_spy_21d": -0.06,
                    "excess_spy_63d": -0.15,
                    "target_date_21d": "2024-03-01",
                    "target_date_63d": "2024-04-01",
                },
                {
                    "event_id": "etf:eee:20240415",
                    "source_type": "etf",
                    "manager_cik": "",
                    "manager_name": "",
                    "ticker": "EEE",
                    "event_type": "inclusion",
                    "event_seed_score": 0.30,
                    "available_from": "2024-04-15T21:00:00Z",
                    "ret_21d": 0.05,
                    "ret_63d": 0.09,
                    "excess_spy_21d": 0.04,
                    "excess_spy_63d": 0.07,
                    "target_date_21d": "2024-05-15",
                    "target_date_63d": "2024-06-17",
                },
            ]
        ).to_parquet(labels, index=False)

        payload = run(
            Namespace(
                labels=str(labels),
                output_dir=str(out_dir),
                manager_output=str(manager_output),
                horizons="21,63",
            )
        )

        assert payload["status"] == "completed", payload
        assert payload["label_rows"] == 5
        assert payload["score_total_changed"] is False
        assert (out_dir / "signal_ic_by_horizon.csv").exists()
        assert (out_dir / "source_alpha.csv").exists()
        assert (out_dir / "follow_vs_fade_report.csv").exists()
        assert (out_dir / "manager_alpha_ranking.csv").exists()
        assert manager_output.exists()

        manager_scores = pd.read_parquet(manager_output)
        latest_m1 = manager_scores[manager_scores["manager_cik"].eq("0000000001")].sort_values("as_of_date").iloc[-1]
        assert int(latest_m1["sample_count"]) == 2
        assert float(latest_m1["avg_excess_return"]) > 0.0
        assert bool(latest_m1["research_only"]) is True
        assert bool(latest_m1["production_activation_allowed"]) is False

        source_alpha = pd.read_csv(out_dir / "source_alpha.csv")
        assert set(source_alpha["source_type"]) >= {"13f", "form4", "etf"}
        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["production_activation_allowed"] is False


def test_signal_learning_blocks_cleanly_without_labels() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        out_dir = root / "outputs"
        manager_output = root / "manager_scores.parquet"
        payload = run(
            Namespace(
                labels=str(root / "missing.parquet"),
                output_dir=str(out_dir),
                manager_output=str(manager_output),
                horizons="21,63",
            )
        )
        assert payload["status"] == "blocked"
        assert pd.read_parquet(manager_output).empty
        assert (out_dir / "summary.json").exists()


if __name__ == "__main__":
    test_signal_learning_outputs_and_manager_pit_guard()
    test_signal_learning_blocks_cleanly_without_labels()
    print("post_disclosure_signal_learning_smoke: PASS")

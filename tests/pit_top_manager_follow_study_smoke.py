#!/usr/bin/env python3
"""Smoke tests for PIT top-manager 13F follow study."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_pit_top_manager_follow_study import run  # noqa: E402


def _event(
    event_id: str,
    manager_cik: str,
    manager_name: str,
    ticker: str,
    event_type: str,
    available_from: str,
    bucket: str,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "source_type": "13f",
        "manager_cik": manager_cik,
        "manager_name": manager_name,
        "ticker": ticker,
        "event_type": event_type,
        "available_from": available_from,
        "market_cap_bucket": bucket,
        "post_disclosure_event_seed_score": 0.70 if event_type == "new" else 0.45,
        "research_only": True,
        "production_activation_allowed": False,
    }


def _label(event: dict[str, object], ret63: float, target_date_63d: str, ret21: float | None = None) -> dict[str, object]:
    ret21 = ret63 / 2.0 if ret21 is None else ret21
    return {
        "event_id": event["event_id"],
        "source_type": event["source_type"],
        "manager_cik": event["manager_cik"],
        "manager_name": event["manager_name"],
        "ticker": event["ticker"],
        "event_type": event["event_type"],
        "event_seed_score": event["post_disclosure_event_seed_score"],
        "available_from": event["available_from"],
        "entry_date": str(pd.Timestamp(str(event["available_from"])).date()),
        "entry_price": 10.0,
        "label_status": "completed",
        "ret_21d": ret21,
        "ret_63d": ret63,
        "ret_126d": ret63 * 1.4,
        "ret_252d": ret63 * 1.8,
        "excess_spy_21d": ret21,
        "excess_spy_63d": ret63,
        "excess_spy_126d": ret63 * 1.4,
        "excess_spy_252d": ret63 * 1.8,
        "target_date_21d": str(pd.Timestamp(target_date_63d) - pd.Timedelta(days=42)),
        "target_date_63d": target_date_63d,
        "target_date_126d": str(pd.Timestamp(target_date_63d) + pd.Timedelta(days=90)),
        "target_date_252d": str(pd.Timestamp(target_date_63d) + pd.Timedelta(days=270)),
        "max_dd_63d": min(0.0, ret63),
        "research_only": True,
        "production_activation_allowed": False,
    }


def test_pit_top_manager_follow_study_uses_only_completed_prior_labels() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        events_path = root / "data_pit" / "sec" / "13f_position_events.parquet"
        labels_path = root / "data_pit" / "sec" / "post_disclosure_alpha_labels.parquet"
        out_dir = root / "outputs" / "pit_top_manager_follow_study"
        cohort_pit = root / "data_pit" / "sec" / "pit_top_manager_cohorts.parquet"
        follow_pit = root / "data_pit" / "sec" / "top_manager_13f_follow_events.parquet"
        events_path.parent.mkdir(parents=True, exist_ok=True)

        events = [
            _event("m1-old-1", "1", "PIT Winner", "AAA", "new", "2020-01-15T21:00:00Z", "small"),
            _event("m1-old-2", "1", "PIT Winner", "AAB", "add", "2020-07-15T21:00:00Z", "mid"),
            _event("m2-old-1", "2", "PIT Loser", "BBB", "new", "2020-01-15T21:00:00Z", "small"),
            _event("m2-old-2", "2", "PIT Loser", "BBC", "add", "2020-07-15T21:00:00Z", "mid"),
            # Strong M2 future label is available before the cohort date but
            # incomplete at cohort date, so it must not rank M2 as a top fund.
            _event("m2-future-incomplete", "2", "PIT Loser", "BBF", "new", "2021-06-15T21:00:00Z", "small"),
            _event("m1-follow", "1", "PIT Winner", "WIN", "new", "2021-07-15T21:00:00Z", "small"),
            _event("m2-follow", "2", "PIT Loser", "LOSS", "new", "2021-07-15T21:00:00Z", "small"),
        ]
        labels = [
            _label(events[0], 0.20, "2020-04-30"),
            _label(events[1], 0.16, "2020-10-30"),
            _label(events[2], -0.12, "2020-04-30"),
            _label(events[3], -0.08, "2020-10-30"),
            _label(events[4], 0.80, "2021-09-30"),
            _label(events[5], 0.25, "2021-10-30"),
            _label(events[6], -0.05, "2021-10-30"),
        ]
        pd.DataFrame(events).to_parquet(events_path, index=False)
        pd.DataFrame(labels).to_parquet(labels_path, index=False)

        payload = run(
            Namespace(
                events=str(events_path),
                labels=str(labels_path),
                output_dir=str(out_dir),
                cohort_pit=str(cohort_pit),
                follow_events_pit=str(follow_pit),
                horizons="21,63,126,252",
                ranking_horizon=63,
                ranking_lookback_days=1095,
                cohort_refresh_months=6,
                top_n=1,
                min_manager_events=2,
                history_years=8,
            )
        )

        assert payload["status"] == "completed", payload
        assert payload["score_total_changed"] is False
        assert payload["production_activation_allowed"] is False
        assert cohort_pit.exists()
        assert follow_pit.exists()

        cohorts = pd.read_parquet(cohort_pit)
        follow = pd.read_parquet(follow_pit)
        assert cohorts["cohort_date"].max() == "2021-07-01"
        july = cohorts[cohorts["cohort_date"].eq("2021-07-01")]
        assert not july.empty
        assert str(july.iloc[0]["manager_cik"]) == "0000000001"
        assert int(july.iloc[0]["manager_sample_count"]) == 2
        assert set(follow["ticker"]) == {"WIN"}
        assert "LOSS" not in set(follow["ticker"])

        stats = pd.read_csv(out_dir / "bucket_performance.csv")
        assert set(stats["horizon"]) >= {21, 63, 126, 252}
        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["selected_follow_events"] == 1
        assert summary["latest_cohort_date"] == "2021-07-01"
        report = (out_dir / "report.md").read_text(encoding="utf-8")
        assert "Research-only study" in report


def test_pit_top_manager_follow_study_blocks_without_completed_samples() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        out_dir = root / "outputs"
        payload = run(
            Namespace(
                events=str(root / "missing_events.parquet"),
                labels=str(root / "missing_labels.parquet"),
                output_dir=str(out_dir),
                cohort_pit=str(root / "cohorts.parquet"),
                follow_events_pit=str(root / "follow.parquet"),
                horizons="21,63",
                ranking_horizon=63,
                ranking_lookback_days=1095,
                cohort_refresh_months=6,
                top_n=10,
                min_manager_events=2,
                history_years=8,
            )
        )
        assert payload["status"] == "blocked"
        assert (out_dir / "summary.json").exists()


if __name__ == "__main__":
    test_pit_top_manager_follow_study_uses_only_completed_prior_labels()
    test_pit_top_manager_follow_study_blocks_without_completed_samples()
    print("pit_top_manager_follow_study_smoke: PASS")

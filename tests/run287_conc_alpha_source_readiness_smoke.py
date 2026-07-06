#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run287_conc_alpha_source_readiness import run  # noqa: E402


class Args:
    pass


def write_book(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"rebalance_date": "2026-07-02", "ticker": "A0", "target_weight": 0.2, "alphaops_score": 10},
            {"rebalance_date": "2026-07-02", "ticker": "A1", "target_weight": 0.2, "alphaops_score": 9},
            {"rebalance_date": "2026-07-02", "ticker": "A2", "target_weight": 0.2, "alphaops_score": 8},
        ]
    ).to_csv(path, index=False)


def make_args(root: Path, feed: Path) -> Args:
    args = Args()
    args.candidate_book = str(root / "candidate_replay_book.csv")
    args.target_book = str(root / "official_concentrated_target_book.csv")
    args.earnings_signals = str(feed)
    args.raw_earnings_feed = str(root / "missing_raw.csv")
    args.as_of = "2026-07-02"
    args.output_dir = str(root / "out")
    return args


def test_missing_feed_blocks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_book(root / "candidate_replay_book.csv")
        write_book(root / "official_concentrated_target_book.csv")
        payload = run(make_args(root, root / "missing.parquet"))
        assert payload["decision_label"] == "blocked_missing_w4_decision_time_source", payload
        assert payload["candidate_source_ready"] is False, payload
        assert payload["candidate_allowed"] is False, payload
        assert payload["new_alpha_hook_added"] is False, payload
        assert payload["rank_rs_revenue_variants_allowed"] is False, payload
        assert (root / "out" / "summary.json").exists()
        assert (root / "out" / "source_readiness.csv").exists()


def test_true_revision_feed_opens_oos_screen_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_book(root / "candidate_replay_book.csv")
        write_book(root / "official_concentrated_target_book.csv")
        feed = root / "earnings_revision_signals.csv"
        rows = []
        for idx in range(10):
            rows.append(
                {
                    "ticker": f"A{idx}",
                    "available_from": "2026-05-15",
                    "eps_estimate": 1.0,
                    "eps_revision_13w": 0.0,
                    "source_type": "vendor_estimate_revision",
                }
            )
            rows.append(
                {
                    "ticker": f"A{idx}",
                    "available_from": "2026-06-25",
                    "eps_estimate": 1.2,
                    "eps_revision_13w": 0.08,
                    "source_type": "vendor_estimate_revision",
                }
            )
        pd.DataFrame(rows).to_csv(feed, index=False)
        payload = run(make_args(root, feed))
        assert payload["decision_label"] == "ready_for_oos_source_screen", payload
        assert payload["candidate_source_ready"] is True, payload
        assert payload["candidate_allowed"] is False, payload
        assert payload["hook_allowed"] is False, payload
        assert payload["next_action_requires_oos_source_screen"] is True, payload
        assert payload["earnings_guidance"]["research_ready"] is True, payload


def main() -> int:
    test_missing_feed_blocks()
    test_true_revision_feed_opens_oos_screen_only()
    print("run287_conc_alpha_source_readiness_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

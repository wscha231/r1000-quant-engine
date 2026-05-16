#!/usr/bin/env python3
"""Smoke test for selection quality diagnostics."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_selection_quality_report import run  # noqa: E402


def test_selection_quality_report_emits_ic_and_topk_outputs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        rows = []
        for month in ["2026-01-31", "2026-02-28", "2026-03-31"]:
            for i in range(30):
                score = i / 29.0
                rows.append(
                    {
                        "rebalance_date": month,
                        "ticker": f"T{i:02d}",
                        "Name": f"Ticker {i}",
                        "sector": "Tech" if i % 2 else "Industrial",
                        "score_total": score,
                        "portfolio_monster_early_score": score * 0.8,
                        "portfolio_sleeve_label": "future_winner" if i >= 20 else "core_compounder",
                        "period_forward_return": score * 0.20 - 0.05,
                    }
                )
        out_dir = latest / "reports"
        out_dir.mkdir(parents=True)
        pd.DataFrame(rows).to_csv(out_dir / "candidate_replay_book.csv", index=False)
        payload = run(latest, root / "out", top_n=5)
        assert payload["status"] == "completed", payload
        assert payload["rows"] == 90, payload
        assert payload["best_factor_by_monthly_ic"] in {"score_total", "portfolio_monster_early_score", "leader_onset_score"}, payload
        ic = pd.read_csv(root / "out" / "factor_ic_by_horizon.csv")
        assert not ic.empty
        assert "leader_onset_score" in set(ic["factor"])
        assert float(ic.iloc[0]["avg_monthly_spearman_ic"]) > 0.9
        topk = pd.read_csv(root / "out" / "topk_forward_hit_rate.csv")
        assert not topk.empty
        assert float(topk.iloc[0]["avg_excess_return"]) > 0
        assert (root / "out" / "missed_winner_onset.csv").exists()


def main() -> int:
    test_selection_quality_report_emits_ic_and_topk_outputs()
    print("selection_quality_report_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

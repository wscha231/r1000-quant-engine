#!/usr/bin/env python3
"""Smoke tests for the Run287 trade-selection research audit."""
from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.audit_run287_trade_selection_research import run  # noqa: E402


def trade_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "entry_date": "2022-01-03",
                "exit_date": "2022-03-31",
                "entry_answer": "GOOD_ENTRY_POSITIVE_ALPHA",
                "alpha_vs_benchmark": 0.10,
            },
            {
                "ticker": "AAA",
                "entry_date": "2023-01-03",
                "exit_date": "2023-03-31",
                "entry_answer": "WRONG_ENTRY_LOSS_AND_LAG",
                "alpha_vs_benchmark": -0.05,
            },
            {
                "ticker": "AAA",
                "entry_date": "2024-07-01",
                "exit_date": "2024-09-30",
                "entry_answer": "GOOD_ENTRY_POSITIVE_ALPHA",
                "alpha_vs_benchmark": 0.02,
            },
        ]
    )


def drop_rows(leakage: bool = False) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.bdate_range("2024-07-01", periods=15, freq="5B")
    for portfolio in ("main", "concentrated"):
        for idx in range(60):
            dt = dates[idx % len(dates)]
            for high in (True, False):
                rows.append(
                    {
                        "portfolio": portfolio,
                        "ticker": f"{portfolio[:1].upper()}{idx:03d}{'H' if high else 'L'}",
                        "drop_date": dt.date().isoformat(),
                        "drop_skill_evidence_flag": high,
                        "candidate_rank_percentile": 0.90 if high else 0.20,
                        "drop_signal_stack_count": 8 if high else 2,
                        "used_forward_return_in_ranking": leakage and idx == 0 and high,
                        "fwd_63d_excess_spy": 0.10 if high else -0.10,
                        "fwd_126d_excess_spy": 0.15 if high else -0.05,
                    }
                )
    return pd.DataFrame(rows)


def main() -> int:
    with TemporaryDirectory() as td:
        root = Path(td)
        trade_path = root / "trades.csv"
        drop_path = root / "drops.csv"
        trade_rows().to_csv(trade_path, index=False)
        drop_rows().to_csv(drop_path, index=False)
        out = root / "out"
        summary = run(trade_path, drop_path, out)
        assert summary["schema_version"] == "run287-trade-selection-research-audit-v1"
        assert summary["status"] == "PASS_SOURCE_SCREEN", summary
        assert summary["research_only"] is True
        assert summary["posthoc_closure_not_preregistered_pass"] is True
        assert summary["issuer_reentry_memory"]["portfolio_ab_eligible"] is False
        assert summary["issuer_reentry_memory"]["repeat_entry_count"] == 2
        assert (out / "issuer_reentry_memory_screen.csv").exists()
        assert (out / "right_tail_drop_source_screen.csv").exists()
        assert (out / "summary.json").exists()
        assert (out / "report.md").exists()
        screen = pd.read_csv(out / "right_tail_drop_source_screen.csv")
        primary = screen[screen["horizon"].eq(63)]
        assert len(primary) == 6
        assert (primary["high_minus_comparator_mean"] > 0).all()
        assert (
            primary[primary["window"].isin(["oos2", "oos"])][
                "week_cluster_bootstrap_95_lower"
            ]
            >= 0
        ).all()

        leaked = root / "drops_leaked.csv"
        drop_rows(leakage=True).to_csv(leaked, index=False)
        leaked_summary = run(trade_path, leaked, root / "leaked_out")
        assert leaked_summary["status"] == "BLOCKED_FORWARD_LABEL_LEAKAGE"
        assert leaked_summary["right_tail_drop"]["forward_label_leakage_count"] == 2

    print("run287 trade-selection research audit smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Smoke tests for the research-only candidate evaluation funnel."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.audit_run287_candidate_evaluation_funnel import build  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def price_file(root: Path, ticker: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    dates = pd.to_datetime(["2019-05-09", "2026-07-13"])
    pd.DataFrame({"Close": [10.0, 20.0]}, index=dates).to_parquet(
        root / px_cache_name(ticker)
    )


def args(root: Path, out: Path) -> argparse.Namespace:
    return argparse.Namespace(
        intake=str(root / "intake.csv"),
        universe=str(root / "universe.csv"),
        scored=str(root / "scored.csv"),
        overlay_ranked=str(root / "overlay_ranked.csv"),
        overlay_selected=str(root / "overlay_selected.csv"),
        main_target=str(root / "main.csv"),
        concentrated_target=str(root / "concentrated.csv"),
        historical_rejections=str(root / "rejections.csv"),
        current_advisory_rejections=str(root / "current_advisory_rejections.csv"),
        current_advisory_projection=str(root / "current_advisory_projection.csv"),
        company_tickers=str(root / "company_tickers.json"),
        price_search_root=[str(root / "prices")],
        authoritative_price_root=[],
        sec_index=[str(root / "sec.parquet")],
        as_of="2026-07-13",
        output_dir=str(out),
    )


def main() -> int:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_csv(
            root / "intake.csv",
            [
                {"ticker": x, "intake_promotes_universe": False, "intake_promotes_portfolio": False}
                for x in ("AAA", "BBB", "CCC", "DDD", "EEE")
            ],
        )
        write_csv(
            root / "universe.csv",
            [{"ticker": x, "cik10": i} for i, x in enumerate(("AAA", "BBB", "CCC", "EEE"), 1)],
        )
        write_csv(
            root / "scored.csv",
            [
                {"ticker": "AAA", "rebalance_date": "2026-07-13", "research_score_rank": 1, "ranking_eligible": True, "portfolio_candidate_gate_label": "core_strict"},
                {"ticker": "BBB", "rebalance_date": "2026-07-13", "research_score_rank": 2, "ranking_eligible": True, "portfolio_candidate_gate_label": "future_relaxed"},
                {"ticker": "CCC", "rebalance_date": "2026-07-13", "research_score_rank": 3, "ranking_eligible": False, "portfolio_candidate_gate_label": "rejected"},
                {"ticker": "EEE", "rebalance_date": "2026-07-13", "research_score_rank": 4, "ranking_eligible": True, "portfolio_candidate_gate_label": "core_strict"},
            ],
        )
        write_csv(root / "overlay_ranked.csv", [{"ticker": x, "free_data_selection_rank": i} for i, x in enumerate(("AAA", "BBB", "CCC", "EEE"), 1)])
        write_csv(root / "overlay_selected.csv", [{"ticker": "AAA"}, {"ticker": "BBB"}, {"ticker": "EEE"}])
        write_csv(root / "main.csv", [{"ticker": "AAA", "rebalance_date": "2026-07-13", "weight": 1.0}])
        write_csv(root / "concentrated.csv", [{"ticker": "AAA", "rebalance_date": "2026-07-13", "weight": 1.0}])
        write_csv(
            root / "rejections.csv",
            [{"ticker": "BBB", "rebalance_date": "2026-05-29", "portfolio_kind": "main", "variant_id": "N15", "rejection_reason": "hold_replace_threshold_not_met"}],
        )
        write_csv(
            root / "current_advisory_rejections.csv",
            [{"ticker": "BBB", "date": "2026-07-13", "portfolio_kind": "main", "scenario": "strict", "rejection_reason": "hold_replace_threshold_not_met"}],
        )
        write_csv(
            root / "current_advisory_projection.csv",
            [
                {"ticker": "AAA", "date": "2026-07-13", "portfolio_kind": "main", "scenario": "strict", "advisory_weight": 0.5},
                {"ticker": "EEE", "date": "2026-07-13", "portfolio_kind": "main", "scenario": "strict", "advisory_weight": 0.2},
            ],
        )
        (root / "company_tickers.json").write_text(
            json.dumps({"0": {"ticker": "DDD", "cik_str": 44, "title": "Outside Candidate"}}),
            encoding="utf-8",
        )
        price_file(root / "prices", "AAA")
        price_file(root / "prices", "BBB")
        price_file(root / "prices", "EEE")
        pd.DataFrame(
            [
                {"ticker": "AAA", "accession_number": "a", "form_type": "10-K", "accepted_at": "2026-01-01T12:00:00Z"},
                {"ticker": "DDD", "accession_number": "d", "form_type": "20-F", "accepted_at": "2026-01-02T12:00:00Z"},
            ]
        ).to_parquet(root / "sec.parquet", index=False)

        out = root / "out"
        summary = build(args(root, out))
        assert summary["status"] == "READY_RESEARCH_ONLY_CANDIDATE_EVALUATION", summary
        assert summary["candidate_count"] == 5, summary
        audit = pd.read_csv(out / "candidate_evaluation_funnel.csv")
        outcomes = dict(zip(audit["ticker"], audit["evaluation_stage_outcome"]))
        assert outcomes["AAA"] == "SELECTED_CURRENT_TARGET", outcomes
        assert outcomes["BBB"] == "CURRENT_ADVISORY_REJECTED", outcomes
        assert outcomes["CCC"] == "CANDIDATE_GATE_REJECTED", outcomes
        assert outcomes["DDD"] == "RESEARCH_CONTEXT_ONBOARDING_REQUIRED", outcomes
        assert outcomes["EEE"] == "CURRENT_ADVISORY_SELECTED_OPERATING_DIVERGENCE", outcomes
        bbb = audit.loc[audit["ticker"].eq("BBB")].iloc[0]
        assert not bool(bbb["historical_rejection_is_current_causal"]), bbb
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["network_requests_executed"] == 0, manifest
        assert manifest["fullrun_executed"] is False, manifest
        assert manifest["orders_generated"] is False, manifest
        assert manifest["universe_mutated"] is False, manifest
        assert manifest["portfolio_weights_mutated"] is False, manifest
        assert manifest["research_context_queue_count"] == 1, manifest
        assert manifest["selector_reconciliation_queue_count"] == 1, manifest
        context_queue = pd.read_csv(out / "research_context_queue.csv")
        assert list(context_queue["ticker"]) == ["DDD"], context_queue
        assert not bool(context_queue.iloc[0]["operating_universe_append_allowed"]), context_queue
        reconciliation = pd.read_csv(out / "selector_reconciliation_queue.csv")
        assert list(reconciliation["ticker"]) == ["EEE"], reconciliation
        assert not bool(reconciliation.iloc[0]["trade_authorization"]), reconciliation

        short_root = root / "authoritative"
        short_root.mkdir()
        pd.DataFrame(
            {"Close": [10.0, 20.0]},
            index=pd.to_datetime(["2025-01-02", "2026-07-13"]),
        ).to_parquet(short_root / px_cache_name("DDD"))
        short_args = args(root, root / "short_out")
        short_args.price_search_root = [str(short_root)]
        short_args.authoritative_price_root = [str(short_root)]
        build(short_args)
        short_audit = pd.read_csv(short_args.output_dir + "/candidate_evaluation_funnel.csv")
        ddd = short_audit.loc[short_audit["ticker"].eq("DDD")].iloc[0]
        assert ddd["price_history_status"] == "FULL_AVAILABLE_HISTORY_SHORT_LISTING", ddd
        assert not bool(ddd["price_backfill_required"]), ddd
        assert not bool(ddd["canonical_7y_price_eligible"]), ddd

        try:
            build(args(root, out))
            raise AssertionError("append-only output reuse should fail")
        except FileExistsError:
            pass

    print("run287 candidate evaluation funnel smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

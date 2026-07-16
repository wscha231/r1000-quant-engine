#!/usr/bin/env python3
"""Synthetic smoke test for the append-only Run287 causal ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import build_run287_decision_outcome_ledger as ledger  # noqa: E402


HEADS = list(ledger.HEAD_COLUMNS)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="run287-ledger-") as tmp_raw:
        tmp = Path(tmp_raw)
        contract = {
            "expected_universe_count": 4,
            "expected_model_feature_count": 3,
            "prediction_heads": HEADS,
            "outcome_horizons_sessions": [1, 5, 21, 63, 126, 252],
            "benchmark_tickers": ["SPY", "QQQ"],
            "sector_etf_map": {"Technology": "XLK"},
            "decision_gates": {"cash_reconciliation_tolerance_usd": 0.01},
        }
        contract_path = tmp / "contract.json"
        write_json(contract_path, contract)
        safe_manifest = {
            "valuation_price_cutoff_date": "2026-07-13",
            "decision_time_utc": "2026-07-14T05:00:00Z",
            "coverage": {"future_feature_row_count": 0},
            "target_books_mutated": False,
            "orders_generated": False,
            "backtest_executed": False,
            "fullrun_executed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
        }
        manifest_paths = {}
        for name in ("decision", "stack", "scored", "selector"):
            path = tmp / f"{name}_manifest.json"
            write_json(path, safe_manifest)
            manifest_paths[name] = path

        tickers = ["AAA", "BBB", "CCC", "DDD"]
        context = pd.DataFrame(
            {
                "ticker": tickers,
                "f1": [1.0, 2.0, 3.0, 4.0],
                "f2": [0.1, 0.2, 0.3, 0.4],
                "f3": [10.0, 20.0, 30.0, 40.0],
                "sector": ["Technology", "Technology", "Industrials", "Industrials"],
                "industry": ["A", "B", "C", "D"],
                "mktcap": [100, 90, 80, 70],
                "vol_252d": [0.2, 0.3, 0.25, 0.4],
            }
        )
        scaled = context[["ticker", "f1", "f2", "f3"]].copy()
        context_path, scaled_path = tmp / "context.parquet", tmp / "scaled.parquet"
        context.to_parquet(context_path, index=False)
        scaled.to_parquet(scaled_path, index=False)
        stack = pd.DataFrame(
            {
                "ticker": tickers,
                "score": [4.0, 3.0, 2.0, 1.0],
                "score_core": [4.0, 3.0, 2.0, 1.0],
                "registered_ranking_eligible": [True, True, True, False],
                "portfolio_candidate_gate_label": ["eligible", "eligible", "eligible", "low_coverage"],
                **{head: [0.4, 0.3, 0.2, 0.1] for head in HEADS},
            }
        )
        scored = stack[["ticker", *HEADS]].copy()
        scored["score"] = [4.0, 3.0, 2.0, 1.0]
        scored["score_total"] = scored["score"]
        scored["score_rank"] = [1, 2, 3, 4]
        scored["ranking_eligible"] = [True, True, True, False]
        stack_path, scored_path = tmp / "stack.csv", tmp / "scored.csv"
        stack.to_csv(stack_path, index=False)
        scored.to_csv(scored_path, index=False)
        adaptive_path = tmp / "adaptive.csv"
        pd.DataFrame(
            [{"linear_weight": 0.3, "catboost_weight": 0.4, "ranker_weight": 0.3, "history_months": 12}]
        ).to_csv(adaptive_path, index=False)

        projection_path = tmp / "projection.csv"
        pd.DataFrame(
            [
                {"portfolio_kind": "main", "scenario": "strict", "ticker": "AAA", "advisory_weight": 0.6, "prior_weight": 0.0, "selection_reason": "top_rank", "alphaops_vnext_score": 4.0},
                {"portfolio_kind": "concentrated", "scenario": "strict", "ticker": "BBB", "advisory_weight": 0.9, "prior_weight": 0.0, "selection_reason": "top_rank", "alphaops_vnext_score": 3.0},
            ]
        ).to_csv(projection_path, index=False)
        rejection_rows = []
        for portfolio, selected in (("main", "AAA"), ("concentrated", "BBB")):
            for ticker in ("AAA", "BBB", "CCC"):
                if ticker != selected:
                    rejection_rows.append(
                        {"portfolio_kind": portfolio, "scenario": "strict", "ticker": ticker, "rejection_reason": "not_selected", "candidate_score": 1.0}
                    )
        rejection_path = tmp / "rejections.csv"
        pd.DataFrame(rejection_rows).to_csv(rejection_path, index=False)
        stages_path = tmp / "stages.csv"
        pd.DataFrame(columns=["portfolio_kind", "scenario", "ticker", "stage_sequence", "transition", "stage_name"]).to_csv(stages_path, index=False)
        scenarios_path = tmp / "scenarios.csv"
        pd.DataFrame(
            [
                {"portfolio_kind": "main", "scenario": "strict", "cash_weight": 0.4},
                {"portfolio_kind": "concentrated", "scenario": "strict", "cash_weight": 0.1},
            ]
        ).to_csv(scenarios_path, index=False)

        operating_main, operating_conc = tmp / "operating_main.csv", tmp / "operating_conc.csv"
        pd.DataFrame([{"rebalance_date": "2026-07-13", "ticker": "AAA", "weight": 0.6}]).to_csv(operating_main, index=False)
        pd.DataFrame([{"rebalance_date": "2026-07-13", "ticker": "BBB", "weight": 0.9}]).to_csv(operating_conc, index=False)
        paper_root = tmp / "paper"
        for portfolio, ticker, shares, price, weight, cash in (
            ("main", "AAA", 6, 100.0, 0.6, 400.0),
            ("concentrated", "BBB", 9, 100.0, 0.9, 100.0),
        ):
            root = paper_root / portfolio
            root.mkdir(parents=True)
            pd.DataFrame(
                [{"as_of_date": "2026-07-13", "ticker": ticker, "shares": shares, "price": price, "market_value_usd": shares * price, "weight": weight}]
            ).to_csv(root / "positions_latest.csv", index=False)
            write_json(
                root / "account_state_latest.json",
                {
                    "as_of_date": "2026-07-13", "equity_usd": 1000.0, "cash_usd": cash,
                    "cash_weight": cash / 1000.0, "simulated_broker_ledger": True,
                    "live_trading_enabled": False, "integer_shares": True, "cost_bps_per_side": 25,
                },
            )

        output = tmp / "ledger"
        args = argparse.Namespace(
            contract=str(contract_path), decision_frame_manifest=str(manifest_paths["decision"]),
            decision_context=str(context_path), scaled_model_input=str(scaled_path),
            score_stack_manifest=str(manifest_paths["stack"]), score_stack=str(stack_path),
            adaptive_ensemble=str(adaptive_path), scored_latest_manifest=str(manifest_paths["scored"]),
            scored_latest=str(scored_path), selector_manifest=str(manifest_paths["selector"]),
            selector_projection=str(projection_path), selector_rejections=str(rejection_path),
            selector_stages=str(stages_path), selector_scenarios=str(scenarios_path),
            operating_main=str(operating_main), operating_concentrated=str(operating_conc),
            paper_root=str(paper_root), output_dir=str(output), price_cache=None,
            decision_date="2026-07-13", as_of_date="2026-07-13",
            recorded_at_utc="2026-07-14T06:00:00Z", path_reconciliation_status="SYNTHETIC_EXACT",
        )
        first = ledger.run(args)
        assert first["status"] == ledger.READY_STATUS, first
        assert first["current_status_row_count"] == 8
        assert first["capture_audit"]["missing_selector_reason_count"] == 0
        assert first["capture_audit"]["future_row_count"] == 0
        assert first["capture_audit"]["prediction_head_count"] == 6
        assert first["capture_audit"]["operating_share_mismatch_count"] == 0
        assert (output / "outcome_events.jsonl").is_file()
        event_hash = sha(output / "decision_events.jsonl")
        second = ledger.run(args)
        assert second["appended_event_counts"]["decision_observed"] == 0
        assert second["duplicate_event_counts"]["decision_observed"] == 8
        assert sha(output / "decision_events.jsonl") == event_hash
        current = pd.read_parquet(output / "current_status.parquet")
        assert not current[["model_mutated", "selector_mutated", "target_books_mutated", "orders_generated"]].any().any()
        assert current["paper_cash_reconciliation_error_usd"].max() <= 0.01
        assert set(current.groupby(["portfolio_kind", "scenario"])["advisory_cash_weight"].first()) == {0.1, 0.4}
    print("run287_decision_outcome_ledger_smoke: PASS")


if __name__ == "__main__":
    main()

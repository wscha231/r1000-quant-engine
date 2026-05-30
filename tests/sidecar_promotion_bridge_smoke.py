#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_sidecar_promotion import (  # noqa: E402
    file_sha256,
    run_approved_integrated,
    run_check_promotion,
    run_market_leader_shadow,
    run_shadow,
    rollback_targets,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_price(cache: Path, ticker: str, start: float = 100.0) -> None:
    dates = pd.bdate_range("2025-01-02", "2025-04-30")
    values = [start * (1.001**i) for i in range(len(dates))]
    pd.DataFrame({"date": dates, "Adj Close": values, "Close": values, "Open": values}, index=dates).to_parquet(cache / px_cache_name(ticker))


def build_fixture(root: Path) -> tuple[Path, Path, Path]:
    latest = root / "outputs"
    cache = root / "cache_prices"
    integrated = latest / "integrated_theme_leader_crisis_replay"
    reports = latest / "reports"
    reports.mkdir(parents=True)
    cache.mkdir()
    for ticker in ("AAA", "BBB", "CCC", "ON", "WDC", "MU", "PR", "ETR", "PEG"):
        write_price(cache, ticker)
    pd.DataFrame(
        [
            {"rebalance_date": "2025-01-31", "ticker": "AAA", "weight": 0.45},
            {"rebalance_date": "2025-01-31", "ticker": "BBB", "weight": 0.45},
        ]
    ).to_csv(reports / "operating_main_target_book.csv", index=False)
    pd.DataFrame(
        [
            {"rebalance_date": "2025-01-31", "ticker": "PR", "weight": 0.42},
            {"rebalance_date": "2025-01-31", "ticker": "ETR", "weight": 0.38},
            {"rebalance_date": "2025-01-31", "ticker": "PEG", "weight": 0.19},
        ]
    ).to_csv(reports / "operating_concentrated_target_book.csv", index=False)
    for portfolio, rows in {
        "main": [
            {"ticker": "AAA", "shares": 10, "market_value_usd": 50000, "weight": 0.50},
            {"ticker": "BBB", "shares": 10, "market_value_usd": 45000, "weight": 0.45},
        ],
        "concentrated": [
            {"ticker": "PR", "shares": 10, "market_value_usd": 42150, "weight": 0.4215},
            {"ticker": "ETR", "shares": 10, "market_value_usd": 38300, "weight": 0.3830},
            {"ticker": "PEG", "shares": 10, "market_value_usd": 19550, "weight": 0.1955},
        ],
    }.items():
        out = latest / "broker_replay" / portfolio
        out.mkdir(parents=True)
        pd.DataFrame(rows).to_csv(out / "positions_latest.csv", index=False)
    h_dir = integrated / "crisis_adjusted_target_books"
    h_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {"rebalance_date": "2025-01-31", "ticker": "ON", "weight": 0.35, "portfolio_kind": "main", "case_id": "H"},
            {"rebalance_date": "2025-01-31", "ticker": "WDC", "weight": 0.30, "portfolio_kind": "main", "case_id": "H"},
            {"rebalance_date": "2025-01-31", "ticker": "MU", "weight": 0.25, "portfolio_kind": "main", "case_id": "H"},
        ]
    ).to_csv(h_dir / "main_H_multi_lane_crisis_hold_replace_target_book.csv", index=False)
    pd.DataFrame(
        [
            {"rebalance_date": "2025-01-31", "ticker": "ON", "weight": 0.35, "portfolio_kind": "concentrated", "case_id": "H"},
            {"rebalance_date": "2025-01-31", "ticker": "WDC", "weight": 0.30, "portfolio_kind": "concentrated", "case_id": "H"},
            {"rebalance_date": "2025-01-31", "ticker": "MU", "weight": 0.25, "portfolio_kind": "concentrated", "case_id": "H"},
        ]
    ).to_csv(h_dir / "concentrated_H_multi_lane_crisis_hold_replace_target_book.csv", index=False)
    ml_dir = latest / "market_leader_challenger"
    ml_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {"rebalance_date": "2025-01-31", "ticker": "ON", "weight": 0.3531, "portfolio_kind": "main"},
            {"rebalance_date": "2025-01-31", "ticker": "WDC", "weight": 0.2648, "portfolio_kind": "main"},
            {"rebalance_date": "2025-01-31", "ticker": "MU", "weight": 0.2572, "portfolio_kind": "main"},
        ]
    ).to_csv(ml_dir / "main_target_book.csv", index=False)
    pd.DataFrame(
        [
            {"rebalance_date": "2025-01-31", "ticker": "ON", "weight": 0.3531, "portfolio_kind": "concentrated"},
            {"rebalance_date": "2025-01-31", "ticker": "WDC", "weight": 0.2648, "portfolio_kind": "concentrated"},
            {"rebalance_date": "2025-01-31", "ticker": "MU", "weight": 0.2572, "portfolio_kind": "concentrated"},
        ]
    ).to_csv(ml_dir / "concentrated_target_book.csv", index=False)
    pd.DataFrame(
        [
            {"case_id": "H", "portfolio_kind": "main", "acceptance_status": "passed", "acceptance_blockers": ""},
            {"case_id": "H", "portfolio_kind": "concentrated", "acceptance_status": "rejected", "acceptance_blockers": "concentrated_max_dd_worse_than_minus_30pct"},
        ]
    ).to_csv(integrated / "acceptance_gate_report.csv", index=False)
    pd.DataFrame(
        [
            {
                "case_id": "H",
                "portfolio_kind": "main",
                "status": "completed",
                "metric_mode": "broker_ledger_next_close",
                "target_book_filter_source": "disabled_explicit",
                "actual_median_position_count": 3,
            },
            {
                "case_id": "H",
                "portfolio_kind": "concentrated",
                "status": "completed",
                "metric_mode": "broker_ledger_next_close",
                "target_book_filter_source": "disabled_explicit",
                "actual_median_position_count": 3,
            },
        ]
    ).to_csv(integrated / "ab_matrix.csv", index=False)
    return latest, cache, integrated


def test_shadow_mode_does_not_mutate_and_shows_current_to_target_deltas() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest, cache, integrated = build_fixture(root)
        before_main = file_sha256(latest / "reports" / "operating_main_target_book.csv")
        payload = run_shadow(latest_run=latest, integrated_dir=integrated, price_cache=cache, output_root=latest)
        assert payload["production_mutated"] is False
        assert file_sha256(latest / "reports" / "operating_main_target_book.csv") == before_main
        projected = pd.read_csv(latest / "operator_review" / "projected_holdings_after_integrated_target.csv")
        concentrated = projected[projected["portfolio"].eq("concentrated")]
        assert {"PR", "ETR", "PEG"}.issubset(set(concentrated[concentrated["action"].eq("FULL_EXIT")]["ticker"]))
        assert {"ON", "WDC", "MU"}.issubset(set(concentrated[concentrated["action"].eq("ADD")]["ticker"]))
        assert (latest / "shadow_operating" / "integrated_concentrated_current_holdings.csv").exists()


def test_portfolio_level_promotion_allows_main_while_concentrated_blocks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest, _cache, integrated = build_fixture(root)
        check = run_check_promotion(latest_run=latest, integrated_dir=integrated, output_root=latest)
        assert check["main_promotion_gate"]["status"] == "passed"
        assert check["concentrated_promotion_gate"]["status"] == "rejected"
        source = integrated / "crisis_adjusted_target_books" / "main_H_multi_lane_crisis_hold_replace_target_book.csv"
        policy = {
            "approved_portfolios": ["main"],
            "source_run_id": "prior_run",
            "source_case_id_main": "H",
            "source_case_id_concentrated": "H",
            "source_target_book_path_main": str(source),
            "source_target_book_path_concentrated": "",
            "source_target_book_sha256_main": file_sha256(source),
            "source_target_book_sha256_concentrated": "",
            "main": {"approved": True, "source_case_id": "H"},
            "concentrated": {"approved": False, "source_case_id": "H"},
            "human_approved": True,
            "production_mutation_allowed": True,
            "allow_replace_operating_target_books": True,
        }
        policy_path = latest / "promotion_review" / "approved_target_policy.json"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        before_conc = file_sha256(latest / "reports" / "operating_concentrated_target_book.csv")
        old_env = os.environ.get("ALLOW_PRODUCTION_MUTATION")
        os.environ["ALLOW_PRODUCTION_MUTATION"] = "1"
        try:
            audit = run_approved_integrated(latest_run=latest, output_root=latest, policy_path=policy_path, integrated_dir=integrated)
        finally:
            if old_env is None:
                os.environ.pop("ALLOW_PRODUCTION_MUTATION", None)
            else:
                os.environ["ALLOW_PRODUCTION_MUTATION"] = old_env
        assert audit["status"] == "applied"
        assert [row["portfolio"] for row in audit["actual_changes"]] == ["main"]
        assert file_sha256(latest / "reports" / "operating_main_target_book.csv") == file_sha256(source)
        assert file_sha256(latest / "reports" / "operating_concentrated_target_book.csv") == before_conc
        rollback = rollback_targets(latest_run=latest, output_root=latest, rerun=False)
        assert rollback["status"] == "completed"


def test_market_leader_shadow_shows_pr_etr_exit_and_mu_wdc_add() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest, cache, integrated = build_fixture(root)
        before_conc = file_sha256(latest / "reports" / "operating_concentrated_target_book.csv")
        payload = run_market_leader_shadow(latest_run=latest, integrated_dir=integrated, price_cache=cache, output_root=latest)
        assert payload["production_mutated"] is False
        assert payload["mode"] == "market_leader_shadow"
        assert file_sha256(latest / "reports" / "operating_concentrated_target_book.csv") == before_conc
        projected = pd.read_csv(latest / "operator_review" / "projected_holdings_after_market_leader_target.csv")
        concentrated = projected[projected["portfolio"].eq("concentrated")]
        assert {"PR", "ETR", "PEG"}.issubset(set(concentrated[concentrated["action"].eq("FULL_EXIT")]["ticker"]))
        assert {"ON", "WDC", "MU"}.issubset(set(concentrated[concentrated["action"].eq("ADD")]["ticker"]))
        assert (latest / "shadow_operating" / "market_leader_concentrated_current_holdings.csv").exists()


def test_approved_market_leader_concentrated_override_copies_target() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest, _cache, integrated = build_fixture(root)
        run_check_promotion(latest_run=latest, integrated_dir=integrated, output_root=latest)
        source = latest / "market_leader_challenger" / "concentrated_target_book.csv"
        policy = {
            "approved_portfolios": ["concentrated"],
            "source_run_id": "prior_market_leader_run",
            "source_policy_concentrated": "market_leader",
            "source_case_id_concentrated": "market_leader",
            "source_target_book_path_concentrated": str(source),
            "source_target_book_sha256_concentrated": file_sha256(source),
            "main": {"approved": False, "source_policy": "integrated_h", "source_case_id": "H"},
            "concentrated": {
                "approved": True,
                "source_policy": "market_leader",
                "source_case_id": "market_leader",
                "source_target_book_path": str(source),
                "source_target_book_sha256": file_sha256(source),
                "manual_gate_override": True,
                "allow_stale_holding_exit_override": True,
                "manual_gate_override_reason": "Approved replacement for stale PR/ETR/PEG concentrated holdings.",
            },
            "human_approved": True,
            "production_mutation_allowed": True,
            "allow_replace_operating_target_books": True,
        }
        policy_path = latest / "promotion_review" / "approved_target_policy.json"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        before_main = file_sha256(latest / "reports" / "operating_main_target_book.csv")
        old_env = os.environ.get("ALLOW_PRODUCTION_MUTATION")
        os.environ["ALLOW_PRODUCTION_MUTATION"] = "1"
        try:
            audit = run_approved_integrated(latest_run=latest, output_root=latest, policy_path=policy_path, integrated_dir=integrated)
        finally:
            if old_env is None:
                os.environ.pop("ALLOW_PRODUCTION_MUTATION", None)
            else:
                os.environ["ALLOW_PRODUCTION_MUTATION"] = old_env
        assert audit["status"] == "applied"
        assert [row["portfolio"] for row in audit["actual_changes"]] == ["concentrated"]
        assert audit["actual_changes"][0]["source_policy"] == "market_leader"
        assert audit["actual_changes"][0]["gate_override_used"] is True
        assert file_sha256(latest / "reports" / "operating_concentrated_target_book.csv") == file_sha256(source)
        assert file_sha256(latest / "reports" / "operating_main_target_book.csv") == before_main


def test_approved_mode_blocks_without_env_or_source_sha() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest, _cache, integrated = build_fixture(root)
        run_check_promotion(latest_run=latest, integrated_dir=integrated, output_root=latest)
        source = integrated / "crisis_adjusted_target_books" / "main_H_multi_lane_crisis_hold_replace_target_book.csv"
        policy = {
            "approved_portfolios": ["main"],
            "source_target_book_path_main": str(source),
            "source_target_book_sha256_main": "badsha",
            "main": {"approved": True},
            "human_approved": True,
            "production_mutation_allowed": True,
            "allow_replace_operating_target_books": True,
        }
        policy_path = latest / "promotion_review" / "approved_target_policy.json"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        os.environ.pop("ALLOW_PRODUCTION_MUTATION", None)
        audit = run_approved_integrated(latest_run=latest, output_root=latest, policy_path=policy_path, integrated_dir=integrated)
        assert audit["status"] == "blocked"
        assert "ALLOW_PRODUCTION_MUTATION_env_not_set" in audit["blockers"]


def main() -> int:
    test_shadow_mode_does_not_mutate_and_shows_current_to_target_deltas()
    test_portfolio_level_promotion_allows_main_while_concentrated_blocks()
    test_market_leader_shadow_shows_pr_etr_exit_and_mu_wdc_add()
    test_approved_market_leader_concentrated_override_copies_target()
    test_approved_mode_blocks_without_env_or_source_sha()
    print("sidecar_promotion_bridge_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

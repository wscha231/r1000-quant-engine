#!/usr/bin/env python3
"""Smoke test for broker-ledger account evaluation."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_account_evaluation import run  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_equity_curve(path: Path, start: str = "2019-06-03", end: str = "2026-06-12") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cur = date.fromisoformat(start)
    last = date.fromisoformat(end)
    rows = ["date,equity\n"]
    value = 100000.0
    while cur <= last:
        if cur.weekday() < 5:
            rows.append(f"{cur.isoformat()},{value:.2f}\n")
            value += 10.0
        cur += timedelta(days=1)
    path.write_text("".join(rows), encoding="utf-8")


def seed_portfolio(root: Path, portfolio: str, *, cagr: float, max_dd: float, sharpe: float) -> None:
    write_json(
        root / "broker_replay" / portfolio / "metrics.json",
        {
            "status": "completed",
            "metric_mode": "broker_ledger_next_close",
            "valid_for_production": True,
            "start_date": "2019-06-03",
            "end_date": "2026-06-12",
            "years": 7.03,
            "starting_capital_usd": 100000,
            "ending_capital_usd": 400000,
            "cagr": cagr,
            "max_dd": max_dd,
            "sharpe": sharpe,
            "avg_cash_weight": 0.03,
            "trade_count": 10,
            "total_fees_usd": 123.45,
            "gross_traded_usd": 49380,
        },
    )
    write_equity_curve(root / "broker_replay" / portfolio / "equity_curve.csv")
    write_json(
        root / "broker_replay" / portfolio / "account_state_latest.json",
        {
            "portfolio_kind": portfolio,
            "as_of_date": "2026-06-12",
            "equity_usd": 400000,
            "cash_usd": 8000,
            "cash_weight": 0.02,
            "position_count": 7,
        },
    )
    write_json(
        root / "account_ledger_preview" / portfolio / "preview_metrics.json",
        {
            "status": "completed",
            "order_count": 4,
            "buy_count": 2,
            "sell_count": 2,
            "blocked_order_count": 0,
        },
    )
    write_json(
        root / "broker_trade_journal" / portfolio / "summary.json",
        {
            "status": "completed",
            "trade_count": 9,
            "win_rate": 0.66,
            "avg_realized_return": 0.08,
            "avg_holding_days": 55,
            "profit_factor": 2.1,
        },
    )


def test_account_evaluation_uses_broker_ledger_as_official_source() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "latest"
        out = Path(tmp) / "account_eval"
        seed_portfolio(root, "main", cagr=0.31, max_dd=-0.14, sharpe=1.2)
        seed_portfolio(root, "concentrated", cagr=0.49, max_dd=-0.16, sharpe=1.4)
        write_json(root / "backtest_metrics.json", {"strategy_cagr": 0.99, "max_dd": -0.01, "sharpe": 9.0})
        write_json(root / "concentrated_backtest_metrics.json", {"strategy_cagr": 0.99, "max_dd": -0.01, "sharpe": 9.0})
        write_json(root / "portfolio_goal_search" / "goal_search_summary.json", {"research_target_pass": True})
        write_json(
            root / "data_readiness" / "summary.json",
            {
                "status": "ready",
                "ready_for_fullrun": True,
                "ready_for_policy_replay": True,
                "free_data_coverage": {"known_gaps": []},
            },
        )

        result = run(Namespace(latest_run=str(root), output_dir=str(out)))
        assert result["official_metric_mode"] == "broker_ledger_next_close"
        assert result["target_type"] == "canonical_mission"
        assert result["target_contract_status"] == "approved_current_mission"
        assert result["target_contract"]["canonical_mission"]["main"]["cagr"] == 0.35
        assert result["mission_target_pass"] is False
        assert result["production_target_pass"] is False
        assert result["research_target_pass"] is True

        main = result["portfolios"][0]
        concentrated = result["portfolios"][1]
        assert main["portfolio"] == "main"
        assert main["target_type"] == "canonical_mission"
        assert main["canonical_cagr_target"] == 0.35
        assert main["canonical_max_dd_target"] == -0.25
        assert main["target_pass"] is False
        assert main["broker_ledger_actual_trading_days"] >= 252 * 7
        assert main["evidence_window_label"] == "research_7y"
        assert main["production_promotion_allowed"] is False
        assert main["legacy_cagr"] == 0.99
        assert concentrated["target_pass"] is False
        assert concentrated["canonical_max_dd_target"] == -0.25
        assert concentrated["cagr_gap_pp"] == 1.0
        official = json.loads((out / "official_metrics.json").read_text(encoding="utf-8"))
        assert official["target_type"] == "canonical_mission"
        assert official["mission_target_pass"] is False
        assert official["target_contract"]["canonical_mission"]["concentrated"]["max_dd"] == -0.25
        assert (out / "portfolio_account_metrics.csv").exists()
        report = (out / "account_evaluation_report.md").read_text(encoding="utf-8")
        assert "remain unresolved until explicit user approval" not in report
        assert "Canonical mission targets are approved" in report


def evaluate_mission_case(main_cagr: float, main_mdd: float, conc_cagr: float, conc_mdd: float) -> dict:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "latest"
        out = Path(tmp) / "account_eval"
        seed_portfolio(root, "main", cagr=main_cagr, max_dd=main_mdd, sharpe=1.5)
        seed_portfolio(root, "concentrated", cagr=conc_cagr, max_dd=conc_mdd, sharpe=1.6)
        write_json(
            root / "data_readiness" / "summary.json",
            {
                "status": "ready",
                "ready_for_fullrun": True,
                "ready_for_policy_replay": True,
                "free_data_coverage": {"known_gaps": []},
            },
        )
        return run(Namespace(latest_run=str(root), output_dir=str(out)))


def test_account_evaluation_canonical_mission_boundaries() -> None:
    main_cagr_fail = evaluate_mission_case(0.32, -0.20, 0.50, -0.25)
    assert main_cagr_fail["portfolios"][0]["target_pass"] is False

    main_mdd_fail = evaluate_mission_case(0.36, -0.26, 0.50, -0.25)
    assert main_mdd_fail["portfolios"][0]["target_pass"] is False

    conc_mdd_fail = evaluate_mission_case(0.35, -0.25, 0.52, -0.27)
    assert conc_mdd_fail["portfolios"][1]["target_pass"] is False

    exact_boundary = evaluate_mission_case(0.35, -0.25, 0.50, -0.25)
    assert [row["target_pass"] for row in exact_boundary["portfolios"]] == [True, True]
    assert exact_boundary["mission_target_pass"] is True
    assert exact_boundary["production_target_pass"] is True
    assert exact_boundary["production_promotion_allowed"] is False


def test_account_evaluation_separates_mission_from_production_and_rejects_failed_replay() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "latest"
        out = Path(tmp) / "account_eval"
        seed_portfolio(root, "main", cagr=0.35, max_dd=-0.25, sharpe=1.5)
        seed_portfolio(root, "concentrated", cagr=0.50, max_dd=-0.25, sharpe=1.6)
        write_json(
            root / "data_readiness" / "summary.json",
            {
                "status": "ready",
                "ready_for_fullrun": True,
                "ready_for_policy_replay": True,
                "free_data_coverage": {"known_gaps": []},
            },
        )

        main_path = root / "broker_replay" / "main" / "metrics.json"
        main = json.loads(main_path.read_text(encoding="utf-8"))
        main["valid_for_production"] = False
        write_json(main_path, main)
        result = run(Namespace(latest_run=str(root), output_dir=str(out)))
        assert result["portfolios"][0]["target_pass"] is True
        assert result["portfolios"][0]["valid_for_production"] is False
        assert result["mission_target_pass"] is True
        assert result["production_target_pass"] is False

        main["status"] = "failed"
        main["valid_for_production"] = True
        write_json(main_path, main)
        failed = run(Namespace(latest_run=str(root), output_dir=str(out)))
        assert failed["portfolios"][0]["target_pass"] is False
        assert failed["mission_target_pass"] is False
        assert failed["production_target_pass"] is False


def test_account_evaluation_missing_numeric_metric_fails_mission() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "latest"
        out = Path(tmp) / "account_eval"
        seed_portfolio(root, "main", cagr=0.35, max_dd=-0.25, sharpe=1.5)
        seed_portfolio(root, "concentrated", cagr=0.50, max_dd=-0.25, sharpe=1.6)
        metrics_path = root / "broker_replay" / "concentrated" / "metrics.json"
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        metrics.pop("max_dd")
        write_json(metrics_path, metrics)
        write_json(
            root / "data_readiness" / "summary.json",
            {
                "status": "ready",
                "ready_for_fullrun": True,
                "ready_for_policy_replay": True,
                "free_data_coverage": {"known_gaps": []},
            },
        )
        result = run(Namespace(latest_run=str(root), output_dir=str(out)))
        concentrated = result["portfolios"][1]
        assert concentrated["max_dd"] is None
        assert concentrated["target_pass"] is False
        assert result["mission_target_pass"] is False


def test_mission_surfaces_recompute_same_numeric_boundaries() -> None:
    from tools.run_account_evaluation import summarize_portfolio
    from tools.run_ab_result_verifier import collect_evidence
    from tools.run_metric_hygiene_report import official_portfolio
    from tools.run_system_acceptance_audit import account_evidence

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Stale published successes must not override any current numeric verdict.
        write_json(root / "account_evaluation" / "official_metrics.json", {
            "production_target_pass": True,
            "portfolios": {name: {"target_pass": True, "cagr": .99, "max_dd": -.01}
                           for name in ("main", "concentrated")},
        })
        cases = [("main", .32, -.20, False), ("main", .36, -.26, False),
                 ("concentrated", .52, -.27, False),
                 ("main", .35, -.25, True), ("concentrated", .50, -.25, True)]
        for invalid in (None, True, False, float("nan"), float("inf"), -float("inf")):
            cases.extend([("main", invalid, -.24, False), ("main", .36, invalid, False)])
        for name, cagr, mdd, expected in cases:
            seed_portfolio(root, name, cagr=cagr, max_dd=mdd, sharpe=1.5)
            rows = [summarize_portfolio(root, name), collect_evidence(root, name),
                    official_portfolio(root, name), account_evidence(root)[1][name]]
            for row in rows:
                assert row["target_type"] == "canonical_mission"
                assert row["target_pass"] is expected, (name, cagr, mdd, row)

        seed_portfolio(root, "main", cagr=.36, max_dd=-.24, sharpe=1.5)
        failed_path = root / "broker_replay" / "main" / "metrics.json"
        failed_metrics = json.loads(failed_path.read_text(encoding="utf-8"))
        failed_metrics["status"] = "failed"
        write_json(failed_path, failed_metrics)
        rows = [summarize_portfolio(root, "main"), collect_evidence(root, "main"),
                official_portfolio(root, "main"), account_evidence(root)[1]["main"]]
        assert [row["target_pass"] for row in rows] == [False, False, False, False]


if __name__ == "__main__":
    test_mission_surfaces_recompute_same_numeric_boundaries()
    test_account_evaluation_uses_broker_ledger_as_official_source()
    test_account_evaluation_canonical_mission_boundaries()
    test_account_evaluation_separates_mission_from_production_and_rejects_failed_replay()
    test_account_evaluation_missing_numeric_metric_fails_mission()
    print("account_evaluation_smoke: PASS")

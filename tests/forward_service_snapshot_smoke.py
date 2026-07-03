#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_forward_service_snapshot import run  # noqa: E402


class Args:
    pass


def _write_portfolio(root: Path, portfolio: str, cagr: float, max_dd: float, cash_weight: float) -> None:
    replay = root / "broker_replay" / portfolio
    replay.mkdir(parents=True, exist_ok=True)
    (replay / "account_state_latest.json").write_text(
        json.dumps(
            {
                "portfolio_kind": portfolio,
                "as_of_date": "2026-06-29",
                "equity_usd": 1000.0,
                "cash_usd": 1000.0 * cash_weight,
                "cash_weight": cash_weight,
                "position_count": 1,
                "metrics": {
                    "metric_mode": "broker_ledger_next_close",
                    "cagr": cagr,
                    "max_dd": max_dd,
                    "sharpe": 1.2,
                    "years": 7.0,
                    "start_date": "2019-06-03",
                    "end_date": "2026-06-29",
                },
            }
        ),
        encoding="utf-8",
    )
    with (replay / "positions_latest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["as_of_date", "ticker", "shares", "price", "market_value_usd", "weight"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "as_of_date": "2026-06-29",
                "ticker": "AAA",
                "shares": 5,
                "price": 100.0,
                "market_value_usd": 500.0,
                "weight": 0.5,
            }
        )


def test_forward_service_snapshot_is_review_only_and_hashes_holdings() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        outputs = root / "official" / "outputs"
        (outputs / "account_evaluation").mkdir(parents=True)
        _write_portfolio(outputs, "main", 0.35, -0.24, 0.10)
        _write_portfolio(outputs, "concentrated", 0.49, -0.25, 0.06)
        (outputs / "account_evaluation" / "official_metrics.json").write_text(
            json.dumps(
                {
                    "official_metric_mode": "broker_ledger_next_close",
                    "portfolios": {
                        "main": {
                            "cagr": 0.35,
                            "max_dd": -0.24,
                            "sharpe": 1.2,
                            "pit_universe_label_clean": False,
                            "production_promotion_allowed": False,
                        },
                        "concentrated": {
                            "cagr": 0.49,
                            "max_dd": -0.25,
                            "sharpe": 1.4,
                            "pit_universe_label_clean": False,
                            "production_promotion_allowed": False,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        args = Args()
        args.latest_run = str(root)
        args.output_dir = str(root / "out")
        args.freeze_date = ""
        payload = run(args)

        assert payload["status"] == "completed"
        assert payload["public_display_allowed"] is False
        assert payload["production_activation_allowed"] is False
        snapshot = json.loads((root / "out" / "current_public_snapshot.json").read_text(encoding="utf-8"))
        readiness = json.loads((root / "out" / "service_readiness.json").read_text(encoding="utf-8"))
        with (root / "out" / "public_holdings.csv").open("r", encoding="utf-8", newline="") as fh:
            holdings = list(csv.DictReader(fh))
        with (root / "out" / "forward_ledger_seed.csv").open("r", encoding="utf-8", newline="") as fh:
            seed = list(csv.DictReader(fh))

        assert snapshot["research_only"] is True
        assert snapshot["snapshot_hash"] == payload["snapshot_hash"]
        assert snapshot["snapshot_hash"] == snapshot["public_snapshot_hash"]
        assert snapshot["snapshot_hash_semantics"] == "alias_of_public_snapshot_hash"
        assert snapshot["broker_state_hash"] == payload["broker_state_hash"]
        assert snapshot["target_snapshot_hash"] == payload["target_snapshot_hash"]
        assert snapshot["hash_inputs"]["broker_state"]["file_count"] == 5
        assert snapshot["backtest_metrics_are_simulated"] is True
        assert snapshot["forward_expectation_basis"] == "is_cagr_band_not_headline"
        assert snapshot["portfolios"][0]["metrics"]["backtest_metrics_are_simulated"] is True
        assert snapshot["portfolios"][0]["metrics"]["forward_expectation_basis"] == "is_cagr_band_not_headline"
        assert "pit_universe_label_clean_false_blocks_production_promotion" in readiness["blockers"]
        assert readiness["public_snapshot_hash"] == snapshot["public_snapshot_hash"]
        assert readiness["broker_state_hash"] == snapshot["broker_state_hash"]
        assert readiness["target_snapshot_hash"] == snapshot["target_snapshot_hash"]
        assert {row["ticker"] for row in holdings} == {"AAA", "CASH"}
        assert {row["backtest_metrics_are_simulated"] for row in holdings} == {"True"}
        assert {row["forward_expectation_basis"] for row in holdings} == {"is_cagr_band_not_headline"}
        assert {row["public_snapshot_hash"] for row in holdings} == {snapshot["public_snapshot_hash"]}
        assert {row["target_snapshot_hash"] for row in holdings} == {snapshot["target_snapshot_hash"]}
        assert {row["broker_state_hash"] for row in holdings} == {snapshot["broker_state_hash"]}
        assert {row["portfolio_kind"] for row in seed} == {"main", "concentrated"}
        assert {row["public_snapshot_hash"] for row in seed} == {snapshot["public_snapshot_hash"]}
        assert {row["target_snapshot_hash"] for row in seed} == {snapshot["target_snapshot_hash"]}
        assert {row["broker_state_hash"] for row in seed} == {snapshot["broker_state_hash"]}


def test_forward_service_snapshot_hashes_are_idempotent_and_state_sensitive() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        outputs = root / "official" / "outputs"
        (outputs / "account_evaluation").mkdir(parents=True)
        _write_portfolio(outputs, "main", 0.35, -0.24, 0.10)
        _write_portfolio(outputs, "concentrated", 0.49, -0.25, 0.06)
        (outputs / "account_evaluation" / "official_metrics.json").write_text(
            json.dumps(
                {
                    "official_metric_mode": "broker_ledger_next_close",
                    "portfolios": {
                        "main": {"cagr": 0.35, "max_dd": -0.24, "sharpe": 1.2},
                        "concentrated": {"cagr": 0.49, "max_dd": -0.25, "sharpe": 1.4},
                    },
                }
            ),
            encoding="utf-8",
        )

        args1 = Args()
        args1.latest_run = str(root)
        args1.output_dir = str(root / "out1")
        args1.freeze_date = "2026-06-29"
        first = run(args1)
        args2 = Args()
        args2.latest_run = str(root)
        args2.output_dir = str(root / "out2")
        args2.freeze_date = "2026-06-29"
        second = run(args2)

        assert first["public_snapshot_hash"] == second["public_snapshot_hash"]
        assert first["broker_state_hash"] == second["broker_state_hash"]
        assert first["target_snapshot_hash"] == second["target_snapshot_hash"]

        positions_path = outputs / "broker_replay" / "main" / "positions_latest.csv"
        with positions_path.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["as_of_date", "ticker", "shares", "price", "market_value_usd", "weight"],
            )
            writer.writerow(
                {
                    "as_of_date": "2026-06-29",
                    "ticker": "BBB",
                    "shares": 1,
                    "price": 100.0,
                    "market_value_usd": 100.0,
                    "weight": 0.1,
                }
            )
        args3 = Args()
        args3.latest_run = str(root)
        args3.output_dir = str(root / "out3")
        args3.freeze_date = "2026-06-29"
        changed = run(args3)
        assert changed["broker_state_hash"] != first["broker_state_hash"]
        assert changed["public_snapshot_hash"] != first["public_snapshot_hash"]
        assert changed["target_snapshot_hash"] == first["target_snapshot_hash"]


def main() -> int:
    test_forward_service_snapshot_is_review_only_and_hashes_holdings()
    test_forward_service_snapshot_hashes_are_idempotent_and_state_sensitive()
    print("forward_service_snapshot_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

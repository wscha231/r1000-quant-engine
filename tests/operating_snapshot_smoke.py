#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_operating_snapshot import build_snapshot


class Args:
    pass


def _args(root: Path) -> Args:
    args = Args()
    args.latest_run = str(root)
    args.output_dir = str(root / "operating_snapshot")
    args.as_of_date = ""
    return args


def _write_preview(root: Path, portfolio: str, account_path: str, equity: float, cash: float) -> None:
    out = root / "account_ledger_preview" / portfolio
    out.mkdir(parents=True)
    (out / "preview_metrics.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "as_of_date": "2026-01-09",
                "account_state": account_path,
                "equity_usd": equity,
                "cash_usd": cash,
                "order_batch_id": f"batch-{portfolio}",
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {"ticker": "AAA", "shares": 100, "price": 100, "market_value_usd": 10000, "cost_basis": 90},
            {"ticker": "CCC", "shares": 50, "price": 200, "market_value_usd": 10000, "cost_basis": 180},
            {"ticker": "BBB", "shares": 0, "price": 50, "market_value_usd": 0, "cost_basis": 0},
        ]
    ).to_csv(out / "positions_current.csv", index=False)
    pd.DataFrame([{"ticker": "AAA", "target_weight": 0.3}, {"ticker": "BBB", "target_weight": 0.2}]).to_csv(
        out / "target_weights.csv",
        index=False,
    )
    pd.DataFrame(
        [
            {"ticker": "BBB", "side": "BUY", "quantity": 20, "gross_value_usd": 1000, "status": "ready"},
            {"ticker": "CCC", "side": "SELL", "quantity": 5, "gross_value_usd": 1000, "status": "ready"},
        ]
    ).to_csv(out / "orders_preview.csv", index=False)


def _write_broker_snapshot(root: Path, portfolio: str, equity: float, cash: float) -> None:
    out = root / "broker_replay" / portfolio
    out.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "as_of_date": "2026-01-09",
                "ticker": "AAA",
                "shares": 100,
                "price": 100,
                "market_value_usd": 10000,
                "weight": 10000 / equity,
                "cost_basis": 90,
                "unrealized_pnl_usd": 1000,
                "realized_pnl_usd": 25,
            },
            {
                "as_of_date": "2026-01-09",
                "ticker": "CCC",
                "shares": 50,
                "price": 200,
                "market_value_usd": 10000,
                "weight": 10000 / equity,
                "cost_basis": 180,
                "unrealized_pnl_usd": 1000,
                "realized_pnl_usd": 0,
            },
        ]
    ).to_csv(out / "positions_latest.csv", index=False)
    pd.DataFrame(
        [
            {
                "date": "2026-01-09",
                "equity_usd": equity,
                "cash_usd": cash,
                "cash_weight": cash / equity,
                "stock_value_usd": equity - cash,
                "position_count": 2,
                "fill_mode": "next_close",
            }
        ]
    ).to_csv(out / "equity_curve.csv", index=False)

    journal = root / "broker_trade_journal" / portfolio
    journal.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "portfolio_kind": portfolio,
                "ticker": "AAA",
                "entry_date": "2025-12-31",
                "entry_signal_date": "2025-12-30",
                "entry_reason": "target_rebalance",
                "quantity_open": 100,
                "entry_price": 90,
                "entry_target_weight": 0.30,
                "entry_sleeve": "future_winner",
                "entry_monster_early_score": 0.72,
                "entry_stale_mega_leader_score": 0.0,
                "entry_risk_entry_block_score": 0.1,
            }
        ]
    ).to_csv(journal / "open_positions.csv", index=False)


def test_operating_snapshot_accepts_simulation_mode_and_prefers_preview_target() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        orch = root / "orchestrator"
        orch.mkdir()
        pd.DataFrame(
            [
                {"ticker": "AAA", "target_weight": 0.40, "row_type": "equity"},
                {"ticker": "BBB", "target_weight": 0.20, "row_type": "equity"},
                {"ticker": "CASH", "target_weight": 0.40, "row_type": "cash"},
            ]
        ).to_csv(orch / "unified_target_latest.csv", index=False)
        (orch / "unified_target_latest.json").write_text(
            json.dumps({"cash_target": 0.40, "regime_state": "red"}),
            encoding="utf-8",
        )
        _write_preview(root, "main", "outputs/broker_replay/main/account_state_latest.json", 100000, 20000)
        _write_preview(root, "concentrated", "outputs/broker_replay/concentrated/account_state_latest.json", 50000, 10000)
        _write_broker_snapshot(root, "main", 100000, 20000)
        _write_broker_snapshot(root, "concentrated", 50000, 10000)
        risk_dir = root / "live_trading_risk_controls"
        risk_dir.mkdir()
        (risk_dir / "risk_controls_summary.json").write_text(
            json.dumps(
                {
                    "status": "pass",
                    "account_mode": "simulated",
                    "issues": [
                        {
                            "severity": "info",
                            "check_id": "simulated_broker_account",
                            "message": "simulated broker account",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        macro_dir = root / "macro_policy_engine"
        macro_dir.mkdir()
        (macro_dir / "summary.json").write_text(
            json.dumps(
                {
                    "latest": {
                        "macro_risk_state": "recovery",
                        "recommended_cash_floor": 0.05,
                        "cash_raise_gate": "reentry_holdback_only",
                        "cash_raise_confirmation_count": 0,
                        "confirmed_cash_raise": False,
                    }
                }
            ),
            encoding="utf-8",
        )
        safety_dir = root / "live_trading_safety"
        safety_dir.mkdir()
        (safety_dir / "safety_audit_summary.json").write_text(json.dumps({"status": "pass", "issues": []}), encoding="utf-8")

        payload = build_snapshot(_args(root))
        assert payload["status"] == "simulation"
        assert payload["approval_status"] == "simulation_ready_preview_only"
        assert payload["account_source"] == "simulated_broker_replay"
        assert payload["target_cash_weight"] == 0.0
        assert payload["target_precedence"] == "account_ledger_preview_target_weights"
        frame = pd.read_csv(root / "operating_snapshot" / "operating_snapshot_latest.csv")
        cash = frame[frame["ticker"] == "CASH"].iloc[0]
        assert cash["row_type"] == "cash"
        assert cash["target_weight"] == 0.0
        aaa = frame[frame["ticker"] == "AAA"].iloc[0]
        assert aaa["target_weight"] == 0.30
        assert "portfolio_latest" not in str(aaa["source_target"])
        assert "account_ledger_preview" in str(aaa["source_target"])
        current = pd.read_csv(root / "operating_snapshot" / "current_portfolio_snapshot_latest.csv")
        main_aaa = current[(current["portfolio_kind"] == "main") & (current["ticker"] == "AAA")].iloc[0]
        assert main_aaa["snapshot_semantics"] == "current_broker_ledger_mark_to_market"
        assert main_aaa["first_entry_date"] == "2025-12-31"
        assert main_aaa["target_portfolio_weight"] == 0.30
        assert main_aaa["review_action"] == "HOLD"
        cash_rows = current[current["row_type"] == "cash"]
        assert set(cash_rows["portfolio_kind"]) == {"main", "concentrated"}
        assert set(cash_rows["review_action"]) == {"DEPLOY_CASH_REVIEW"}
        assert cash_rows["combined_current_cash_weight"].astype(float).iloc[0] == 0.20
        assert cash_rows["combined_target_cash_weight"].astype(float).iloc[0] == 0.0
        assert cash_rows["cash_policy_flag"].iloc[0] == "cash_above_target"
        summary = json.loads((root / "operating_snapshot" / "current_portfolio_snapshot_summary.json").read_text())
        assert summary["status"] == "completed"
        assert summary["schema_version"] == "current-portfolio-snapshot-v2"
        assert summary["primary_user_view"] == "current_operating_holdings_latest.csv"
        assert summary["portfolio_position_counts"]["main"] == 2
        assert summary["cash_policy_review_action"] == "DEPLOY_CASH_REVIEW"
        current_only = pd.read_csv(root / "operating_snapshot" / "current_operating_holdings_latest.csv")
        assert "target_portfolio_weight" not in set(current_only.columns)
        assert "daily_review_action" in set(current_only.columns)
        assert set(current_only["portfolio_kind"]) == {"main", "concentrated"}
        assert (root / "operating_snapshot" / "current_operating_holdings_main_latest.csv").exists()
        assert (root / "operating_snapshot" / "current_operating_holdings_concentrated_latest.csv").exists()
        deltas = pd.read_csv(root / "operating_snapshot" / "proposed_target_deltas_latest.csv")
        assert "target_portfolio_weight" in set(deltas.columns)


def main() -> int:
    test_operating_snapshot_accepts_simulation_mode_and_prefers_preview_target()
    print("operating_snapshot_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

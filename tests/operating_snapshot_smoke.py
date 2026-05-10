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


def test_operating_snapshot_accepts_simulation_mode_and_uses_unified_target() -> None:
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
        safety_dir = root / "live_trading_safety"
        safety_dir.mkdir()
        (safety_dir / "safety_audit_summary.json").write_text(json.dumps({"status": "pass", "issues": []}), encoding="utf-8")

        payload = build_snapshot(_args(root))
        assert payload["status"] == "simulation"
        assert payload["approval_status"] == "simulation_ready_preview_only"
        assert payload["account_source"] == "simulated_broker_replay"
        assert payload["target_cash_weight"] == 0.40
        frame = pd.read_csv(root / "operating_snapshot" / "operating_snapshot_latest.csv")
        cash = frame[frame["ticker"] == "CASH"].iloc[0]
        assert cash["row_type"] == "cash"
        assert cash["target_weight"] == 0.40
        aaa = frame[frame["ticker"] == "AAA"].iloc[0]
        assert aaa["target_weight"] == 0.40
        assert "portfolio_latest" not in str(aaa["source_target"])


def main() -> int:
    test_operating_snapshot_accepts_simulation_mode_and_uses_unified_target()
    print("operating_snapshot_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

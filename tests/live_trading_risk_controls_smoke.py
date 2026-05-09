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

from tools.run_live_trading_risk_controls import run


class Args:
    pass


def _args(root: Path, previous_manifest: str = "", strict_live: bool = False) -> Args:
    args = Args()
    args.latest_run = str(root)
    args.output_dir = str(root / "live_trading_risk_controls")
    args.price_cache = str(root / "cache_prices")
    args.broker_snapshot_dir = ""
    args.previous_manifest = previous_manifest
    args.strict_live = strict_live
    args.max_stale_days = 1000
    args.share_tolerance = 1e-8
    args.cash_tolerance_usd = 5.0
    args.equity_tolerance_pct = 0.005
    args.corporate_action_jump_pct = 0.50
    args.strict = False
    return args


def _write_preview(root: Path, portfolio: str, client_order_id: str) -> None:
    out = root / "account_ledger_preview" / portfolio
    out.mkdir(parents=True)
    (out / "preview_metrics.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "as_of_date": "2026-01-09",
                "account_state_as_of_date": "2026-01-09",
                "equity_usd": 100000,
                "cash_usd": 20000,
                "order_batch_id": f"batch-{portfolio}",
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {"ticker": "AAA", "shares": 100, "price": 100, "price_date": "2026-01-09", "market_value_usd": 10000, "cost_basis": 90},
            {"ticker": "BBB", "shares": 0, "price": 50, "price_date": "2026-01-09", "market_value_usd": 0, "cost_basis": 50},
        ]
    ).to_csv(out / "positions_current.csv", index=False)
    pd.DataFrame([{"ticker": "AAA", "target_weight": 0.10}, {"ticker": "BBB", "target_weight": 0.20}]).to_csv(
        out / "target_weights.csv",
        index=False,
    )
    pd.DataFrame(
        [
            {
                "ticker": "BBB",
                "side": "BUY",
                "quantity": 10,
                "reference_price": 50,
                "limit_price": 50.125,
                "gross_value_usd": 500,
                "estimated_fee_usd": 1.25,
                "cash_impact_usd": -501.25,
                "estimated_cash_after_usd": 19498.75,
                "status": "ready",
                "client_order_id": client_order_id,
                "idempotency_key": f"key-{client_order_id}",
            }
        ]
    ).to_csv(out / "orders_preview.csv", index=False)


def test_live_trading_risk_controls_writes_manifest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_preview(root, "main", "r1k-M-20260109-B-BBB-aaa")
        _write_preview(root, "concentrated", "r1k-C-20260109-B-BBB-bbb")
        payload = run(_args(root))
        assert payload["status"] == "pass", payload
        manifest = pd.read_csv(root / "live_trading_risk_controls" / "order_manifest.csv")
        fills = pd.read_csv(root / "live_trading_risk_controls" / "fill_reconciliation_template.csv")
        assert len(manifest) == 2
        assert len(fills) == 2
        assert manifest["client_order_id"].is_unique


def test_live_trading_risk_controls_blocks_duplicate_prior_manifest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_preview(root, "main", "r1k-M-20260109-B-BBB-aaa")
        _write_preview(root, "concentrated", "r1k-C-20260109-B-BBB-bbb")
        previous = root / "previous_order_manifest.csv"
        pd.DataFrame(
            [
                {
                    "portfolio": "main",
                    "client_order_id": "r1k-M-20260109-B-BBB-aaa",
                    "lifecycle_status": "planned",
                }
            ]
        ).to_csv(previous, index=False)
        payload = run(_args(root, previous_manifest=str(previous)))
        assert payload["status"] == "blocked"
        assert any(row["check_id"] == "main_duplicate_prior_manifest" for row in payload["issues"])


def test_strict_live_requires_broker_snapshot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_preview(root, "main", "r1k-M-20260109-B-BBB-aaa")
        _write_preview(root, "concentrated", "r1k-C-20260109-B-BBB-bbb")
        payload = run(_args(root, strict_live=True))
        assert payload["status"] == "blocked"
        assert any(row["check_id"] == "broker_snapshot_required" for row in payload["issues"])


def main() -> int:
    test_live_trading_risk_controls_writes_manifest()
    test_live_trading_risk_controls_blocks_duplicate_prior_manifest()
    test_strict_live_requires_broker_snapshot()
    print("live_trading_risk_controls_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

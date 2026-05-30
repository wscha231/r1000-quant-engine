#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from argparse import Namespace
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_user_current_report import build_report


def test_user_current_explains_research_sidecars_do_not_alter_holdings() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        (latest / "operating_snapshot").mkdir(parents=True)
        (latest / "account_evaluation").mkdir()
        (latest / "broker_replay" / "main").mkdir(parents=True)
        (latest / "broker_replay" / "concentrated").mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "as_of_date": "2026-01-31",
                    "portfolio_kind": "main",
                    "row_type": "stock",
                    "ticker": "AAA",
                    "current_weight": 0.5,
                }
            ]
        ).to_csv(latest / "operating_snapshot" / "current_operating_holdings_latest.csv", index=False)
        (latest / "account_evaluation" / "official_metrics.json").write_text(
            json.dumps({"official_metric_mode": "broker_ledger_next_close", "valid_for_production": True}),
            encoding="utf-8",
        )
        for portfolio in ("main", "concentrated"):
            pd.DataFrame(
                [
                    {"date": "2026-01-02", "equity_usd": 100000, "cash_weight": 0.05},
                    {"date": "2026-01-31", "equity_usd": 101000, "cash_weight": 0.05},
                ]
            ).to_csv(latest / "broker_replay" / portfolio / "equity_curve.csv", index=False)
        (latest / "integrated_theme_leader_crisis_replay").mkdir()
        (latest / "integrated_theme_leader_crisis_replay" / "replay_gate_status.json").write_text('{"status":"passed"}\n', encoding="utf-8")
        (latest / "integrated_theme_leader_crisis_replay" / "promotion_gate_status.json").write_text('{"status":"rejected","production_activation_allowed":false}\n', encoding="utf-8")

        payload = build_report(Namespace(latest_run=str(latest), price_cache=str(root / "cache_prices"), output_dir=str(root / "user_current"), strict=False))
        out = root / "user_current"
        context = json.loads((out / "07_research_sidecar_context.json").read_text(encoding="utf-8"))
        summary = (out / "05_action_summary.md").read_text(encoding="utf-8")
        assert payload["production_applied"] is False
        assert payload["sidecar_only"] is True
        assert payload["production_policy"] == "production_baseline"
        assert payload["sidecar_applied_to_production"] is False
        assert context["current_holdings_source"] == "production_operating_target_book"
        assert "sidecar_applied_to_production" in summary
        assert "Market Leader / Multi-Lane / Crisis outputs alter current holdings only after approved_integrated promotion" in summary
        assert "promotion_gate_status" in summary


if __name__ == "__main__":
    test_user_current_explains_research_sidecars_do_not_alter_holdings()
    print("user_current_research_notice_smoke: PASS")

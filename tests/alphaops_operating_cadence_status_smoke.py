#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_alphaops_operating_cadence_status import status_from_artifacts


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_stale_price_requires_daily_update() -> None:
    with tempfile.TemporaryDirectory() as tmp_raw:
        root = Path(tmp_raw)
        _write(root / "latest_price_date_audit.json", {"status": "STALE_PRICE_REVIEW", "stale_trading_days": 3})
        payload = status_from_artifacts(root, material_change=True)
    assert payload["recommendation"]["next_action"] == "run_free_data_daily_update"
    assert payload["price_audit"]["data_refresh_required"] is True


def test_material_change_with_fresh_prices_requests_fullrun() -> None:
    with tempfile.TemporaryDirectory() as tmp_raw:
        root = Path(tmp_raw)
        _write(
            root / "latest_price_date_audit.json",
            {"status": "ok", "benchmark_anchor_date": "2026-06-26", "audit_date": "2026-06-29"},
        )
        payload = status_from_artifacts(root, material_change=True, today=pd.Timestamp("2026-06-29"))
    assert payload["recommendation"]["next_action"] == "run_full_rebuild_manual_with_integration_env"
    assert payload["recommendation"]["fullrun_ready"] is True


def test_passing_goal_without_material_change_holds_fullrun() -> None:
    with tempfile.TemporaryDirectory() as tmp_raw:
        root = Path(tmp_raw)
        _write(
            root / "latest_price_date_audit.json",
            {"status": "ok", "benchmark_anchor_date": "2026-06-26", "audit_date": "2026-06-29"},
        )
        _write(
            root / "goal_verifier" / "summary.json",
            {
                "status": "pass",
                "portfolios": {
                    "main": {"pass": True},
                    "concentrated": {"pass": True},
                },
            },
        )
        _write(root / "account_evaluation" / "official_metrics.json", {"pit_universe_label_clean": False})
        payload = status_from_artifacts(root, material_change=False, today=pd.Timestamp("2026-06-29"))
    assert payload["recommendation"]["next_action"] == "hold_fullrun_run_weekly_sidecars_only"
    assert payload["production"]["production_blocked_by_pit"] is True


def test_account_evaluation_gate_fallback_supplies_readiness_and_pit() -> None:
    with tempfile.TemporaryDirectory() as tmp_raw:
        root = Path(tmp_raw)
        _write(root / "latest_price_date_audit.json", {"status": "ok", "audit_date": "2026-06-29"})
        _write(
            root / "account_evaluation" / "official_metrics.json",
            {
                "portfolios": {
                    "main": {
                        "broker_ledger_window_gate": {
                            "pit_universe_label_clean": False,
                            "production_promotion_allowed": False,
                            "data_readiness": {
                                "status": "warn",
                                "ready_for_policy_replay": True,
                                "ready_for_fullrun": True,
                            },
                        }
                    }
                }
            },
        )
        payload = status_from_artifacts(root, material_change=True, today=pd.Timestamp("2026-06-29"))
    assert payload["data_readiness"]["ready_for_policy_replay_or_fullrun"] is True
    assert payload["production"]["production_blocked_by_pit"] is True


def test_old_price_audit_forces_daily_update_even_if_status_ok() -> None:
    with tempfile.TemporaryDirectory() as tmp_raw:
        root = Path(tmp_raw)
        _write(root / "latest_price_date_audit.json", {"status": "ok", "audit_date": "2026-06-24"})
        payload = status_from_artifacts(root, material_change=True, today=pd.Timestamp("2026-06-29"))
    assert payload["price_audit"]["audit_record_stale"] is True
    assert payload["recommendation"]["next_action"] == "run_free_data_daily_update"


if __name__ == "__main__":
    test_stale_price_requires_daily_update()
    test_material_change_with_fresh_prices_requests_fullrun()
    test_passing_goal_without_material_change_holds_fullrun()
    test_account_evaluation_gate_fallback_supplies_readiness_and_pit()
    test_old_price_audit_forces_daily_update_even_if_status_ok()
    print("alphaops_operating_cadence_status_smoke: PASS")

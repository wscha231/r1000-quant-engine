#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

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
        _write(root / "latest_price_date_audit.json", {"status": "ok", "benchmark_anchor_date": "2026-06-26"})
        payload = status_from_artifacts(root, material_change=True)
    assert payload["recommendation"]["next_action"] == "run_full_rebuild_manual_with_integration_env"
    assert payload["recommendation"]["fullrun_ready"] is True


def test_passing_goal_without_material_change_holds_fullrun() -> None:
    with tempfile.TemporaryDirectory() as tmp_raw:
        root = Path(tmp_raw)
        _write(root / "latest_price_date_audit.json", {"status": "ok", "benchmark_anchor_date": "2026-06-26"})
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
        payload = status_from_artifacts(root, material_change=False)
    assert payload["recommendation"]["next_action"] == "hold_fullrun_run_weekly_sidecars_only"
    assert payload["production"]["production_blocked_by_pit"] is True


if __name__ == "__main__":
    test_stale_price_requires_daily_update()
    test_material_change_with_fresh_prices_requests_fullrun()
    test_passing_goal_without_material_change_holds_fullrun()
    print("alphaops_operating_cadence_status_smoke: PASS")

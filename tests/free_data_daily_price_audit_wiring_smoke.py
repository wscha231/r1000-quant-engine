#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_free_data_daily_update_emits_latest_price_audit() -> None:
    workflow = (ROOT / ".github" / "workflows" / "free_data_daily_update.yml").read_text(encoding="utf-8")
    command = "python tools/run_latest_price_date_audit.py --latest-run \"$LATEST\" --price-cache cache_prices --output outputs/latest_price_date_audit.json"
    assert command in workflow
    assert "outputs/full_rebuild_logs/latest_price_date_audit.log" in workflow
    assert "outputs/latest_price_date_audit.json" in workflow
    assert "latest_price_date_audit.json" in workflow


if __name__ == "__main__":
    test_free_data_daily_update_emits_latest_price_audit()
    print("free_data_daily_price_audit_wiring_smoke: PASS")

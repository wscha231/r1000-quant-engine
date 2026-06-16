#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_data_freshness_contract import source_watermark  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_macro_latest_json_manifest_clears_stale_macro_blocker() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        today = datetime.now(timezone.utc).date().isoformat()
        macro_dir = root / "data_pit" / "macro"
        write_json(
            macro_dir / "latest.json",
            {
                "asof_date": today,
                "asof": f"{today} 00:00 UTC",
                "regime_state": "neutral",
            },
        )

        macro = source_watermark(
            {
                "name": "macro",
                "layer": "macro",
                "provider": "FRED_yfinance_market_snapshot",
                "path": str(macro_dir),
                "cadence_days": 3,
                "owner_workflow": "daily_operating_selection_refresh.yml",
                "hard_required_for_selection": True,
            },
            today=datetime.now(timezone.utc).date(),
        )
        assert macro["status"] == "ok"
        assert macro["freshness_basis"] == "manifest:asof_date"
        assert macro["latest_asof"] == today


def main() -> int:
    test_macro_latest_json_manifest_clears_stale_macro_blocker()
    print("data_freshness_macro_snapshot_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

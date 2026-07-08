#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import r1000_config as cfg  # noqa: E402


def test_phase18_estimate_feed_is_not_in_backtest_feature_store() -> None:
    columns = set(cfg.PHASE18_ESTIMATE_REVISION_COLUMNS)
    default_features = set(getattr(cfg, "DEFAULT_FEATURES", []))
    assert columns
    assert not (columns & default_features), columns & default_features
    pipeline_text = (ROOT / "r1000_pipeline.py").read_text(encoding="utf-8")
    assert "PHASE18_ESTIMATE_REVISION_COLUMNS" not in pipeline_text
    assert "PHASE_ESTIMATE_REVISION_CONFIRM_ENABLED" not in pipeline_text
    assert cfg.PHASE_ESTIMATE_REVISION_CONFIRM_ENABLED is False


if __name__ == "__main__":
    test_phase18_estimate_feed_is_not_in_backtest_feature_store()
    print("estimate_feed_backtest_neutrality_smoke: PASS")

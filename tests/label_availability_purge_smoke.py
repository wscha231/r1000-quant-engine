#!/usr/bin/env python3
"""Exact label maturity must govern walk-forward and latest-model training."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import r1000_pipeline as pipeline  # noqa: E402
from r1000_config import ENGINE_REUSE_VERSION, EngineConfig  # noqa: E402


def test_stock_forward_end_dates() -> None:
    idx = pd.bdate_range("2020-01-02", periods=900)
    hist = pd.DataFrame({"Open": np.arange(1.0, 901.0)}, index=idx)
    base = pd.Series([pd.Timestamp("2020-01-02")])
    entry, returns, ends = pipeline.compute_forward_returns_for_dates(hist, base, [21, 63, 126])
    raw_pos = idx.searchsorted(pd.Timestamp("2020-01-03"), side="left")
    assert entry.iloc[0] == idx[raw_pos]
    for horizon in (21, 63, 126):
        assert ends[horizon].iloc[0] == idx[raw_pos + horizon]
        expected = hist["Open"].iloc[raw_pos + horizon] / hist["Open"].iloc[raw_pos] - 1.0
        assert abs(float(returns[horizon].iloc[0]) - float(expected)) < 1e-12


def _complete_label_frame() -> pd.DataFrame:
    row: dict[str, object] = {}
    dates = {
        "1m": "2020-02-03",
        "3m": "2020-04-01",
        "6m": "2020-07-01",
        "12m": "2021-01-04",
        "24m": "2022-01-03",
        "36m": "2023-01-03",
    }
    for label, date in dates.items():
        row[f"r_{label}"] = 0.10
        row[f"bench_r_{label}"] = 0.05
        row[f"r_{label}_label_end_date"] = date
        row[f"bench_r_{label}_label_end_date"] = date
    return pd.DataFrame([row])


def test_exact_blended_target_maturity() -> None:
    cfg = EngineConfig()
    frame = _complete_label_frame()
    frame["feature_date"] = pd.Timestamp("2020-01-31")
    out = pipeline.derive_label_availability(frame, cfg)
    assert bool(out.loc[0, "short_label_complete"])
    assert bool(out.loc[0, "future_label_complete"])
    assert out.loc[0, "short_label_available_at"] == pd.Timestamp("2020-07-01")
    assert out.loc[0, "future_label_available_at"] == pd.Timestamp("2023-01-03")
    assert not bool(pipeline.label_ready_before(out, "short", "2020-07-01").iloc[0])
    assert bool(pipeline.label_ready_before(out, "short", "2020-07-02").iloc[0])
    assert not bool(pipeline.label_ready_before(out, "future", "2023-01-03").iloc[0])
    assert bool(pipeline.label_ready_before(out, "future", "2023-01-04").iloc[0])

    missing_benchmark = _complete_label_frame()
    missing_benchmark["feature_date"] = pd.Timestamp("2020-01-31")
    missing_benchmark.loc[0, "bench_r_36m"] = np.nan
    blocked = pipeline.derive_label_availability(missing_benchmark, cfg)
    assert not bool(blocked.loc[0, "future_label_complete"])
    assert pd.isna(blocked.loc[0, "future_label_available_at"])

    staggered = pd.concat([frame, frame], ignore_index=True)
    staggered.loc[1, "r_6m_label_end_date"] = "2020-07-02"
    staggered.loc[1, "bench_r_6m_label_end_date"] = "2020-07-02"
    grouped = pipeline.derive_label_availability(staggered, cfg)
    assert (grouped["short_label_available_at"] == pd.Timestamp("2020-07-02")).all()


def test_benchmark_columns_are_canonical() -> None:
    cfg = EngineConfig()
    close = pd.Series(
        np.arange(100.0, 1000.0),
        index=pd.bdate_range("2020-01-02", periods=900),
    )
    monthly = pd.DataFrame({"rebalance_date": [pd.Timestamp("2020-01-02")]})
    with patch.object(pipeline, "load_benchmark_price_series", return_value=close):
        out = pipeline.attach_benchmark_forward_returns(cfg, {}, monthly)
    assert "bench_r_1m" in out.columns
    assert "bench_r_1m_label_end_date" in out.columns
    assert not any(str(c).endswith(("_x", "_y")) for c in out.columns)
    assert pd.notna(out.loc[0, "bench_r_6m"])
    assert pd.notna(out.loc[0, "bench_r_6m_label_end_date"])


def test_training_source_is_fail_closed() -> None:
    source = (REPO_ROOT / "r1000_pipeline.py").read_text(encoding="utf-8")
    assert "pd.Timedelta(days=cfg.embargo_days)" not in source
    assert (
        'hist[(hist["feature_date"] >= train_start) & (hist["rebalance_date"] < latest_dt)]'
        not in source
    )
    assert 'label_ready_before(d, "short", anchor_dt)' in source
    assert 'label_ready_before(fit_df, "future", anchor_dt)' in source
    assert 'label_ready_before(hist, "short", latest_dt)' in source
    assert 'label_ready_before(train_df, "future", latest_dt)' in source
    assert ENGINE_REUSE_VERSION == "2026-07-27-exact-label-availability-v1"


def test_label_provenance_is_not_orderable_output() -> None:
    frame = pd.DataFrame(
        {
            "ticker": ["ABC"],
            "score": [1.0],
            "r_6m_label_end_date": [pd.Timestamp("2020-07-01")],
            "short_label_available_at": [pd.Timestamp("2020-07-01")],
            "short_label_complete": [True],
        }
    )
    clean = pipeline.drop_actionable_leakage_columns(frame)
    assert list(clean.columns) == ["ticker", "score"]


def main() -> None:
    test_stock_forward_end_dates()
    test_exact_blended_target_maturity()
    test_benchmark_columns_are_canonical()
    test_training_source_is_fail_closed()
    test_label_provenance_is_not_orderable_output()
    print("label_availability_purge_smoke: ok")


if __name__ == "__main__":
    main()

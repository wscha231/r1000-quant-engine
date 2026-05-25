#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_shakeout_disclosure_reversal_study import run  # noqa: E402


def px_cache_name(ticker: str) -> str:
    return f"{hashlib.sha1(str(ticker).upper().encode('utf-8')).hexdigest()[:16]}.parquet"


def main() -> int:
    tmp = ROOT / "tmp_test_shakeout_disclosure"
    if tmp.exists():
        import shutil

        shutil.rmtree(tmp)
    price_cache = tmp / "cache_prices"
    price_cache.mkdir(parents=True)
    dates = pd.bdate_range("2026-01-01", periods=120)
    close = []
    volume = []
    for i, _ in enumerate(dates):
        if i < 70:
            price = 100 + i * 1.0
            vol = 1_000_000
        elif i < 76:
            price = 170 - (i - 69) * 8.0
            vol = 2_500_000
        elif i < 86:
            price = 122 + (i - 75) * 5.0
            vol = 2_000_000
        else:
            price = 177 + (i - 85) * 0.5
            vol = 1_300_000
        close.append(price)
        volume.append(vol)
    px = pd.DataFrame(
        {
            "Open": close,
            "High": [x * 1.02 for x in close],
            "Low": [x * 0.98 for x in close],
            "Close": close,
            "Adj Close": close,
            "Volume": volume,
        },
        index=dates,
    )
    px.to_parquet(price_cache / px_cache_name("AAA"))
    event_date = dates[74]
    events = pd.DataFrame(
        [
            {
                "event_id": "13f:top:AAA",
                "source_type": "13f",
                "manager_cik": "000TOP",
                "manager_name": "Top Fund",
                "ticker": "AAA",
                "event_type": "new_position",
                "available_from": event_date.isoformat(),
                "event_seed_score": 0.85,
                "manager_rank": 1,
            }
        ]
    )
    event_path = tmp / "events.csv"
    events.to_csv(event_path, index=False)
    output_dir = tmp / "out"
    args = type(
        "Args",
        (),
        {
            "events": [str(event_path)],
            "price_cache": str(price_cache),
            "output_dir": str(output_dir),
            "peak_window": 63,
            "reset_window": 63,
            "event_window": 5,
        },
    )()
    summary = run(args)
    out = pd.read_csv(output_dir / "events.csv")
    row = out.iloc[0]
    assert summary["event_count"] == 1
    assert row["pattern_bucket"] == "shakeout_reversal_confirmed"
    assert float(row["shakeout_disclosure_reversal_score"]) >= 0.60
    assert float(row["drawdown_from_prior_peak"]) <= -0.12
    assert int(row["reclaim_prior_peak_21d"]) == 1
    payload = json.loads((output_dir / "pattern_summary.json").read_text(encoding="utf-8"))
    assert payload["production_activation_allowed"] is False

    dates2 = pd.bdate_range("2025-12-01", periods=150)
    close2 = []
    volume2 = []
    for i, _ in enumerate(dates2):
        if i <= 2:
            price = 180 + i * 5.0
            vol = 1_000_000
        elif i <= 84:
            price = 190 - (i - 2) * 1.25
            vol = 1_100_000
        elif i <= 100:
            price = 87 + (i - 84) * 3.0
            vol = 1_200_000
        elif i <= 124:
            price = 135 + (i - 100) * 1.5
            vol = 1_300_000
        elif i <= 130:
            price = 171 - (i - 124) * 2.0
            vol = 2_400_000
        else:
            price = 160 + (i - 130) * 4.0
            vol = 2_000_000
        close2.append(price)
        volume2.append(vol)
    px2 = pd.DataFrame(
        {
            "Open": close2,
            "High": [x * 1.02 for x in close2],
            "Low": [x * 0.98 for x in close2],
            "Close": close2,
            "Adj Close": close2,
            "Volume": volume2,
        },
        index=dates2,
    )
    px2.to_parquet(price_cache / px_cache_name("BBB"))
    event2 = pd.DataFrame(
        [
            {
                "event_id": "13f:atreides:BBB",
                "source_type": "13f",
                "manager_cik": "0001777813",
                "manager_name": "Atreides Management LP",
                "ticker": "BBB",
                "event_type": "new",
                "available_from": dates2[128].isoformat(),
                "event_seed_score": 0.85,
                "manager_rank": 6,
                "external_performance_2y": 1.744,
            }
        ]
    )
    event2_path = tmp / "events2.csv"
    event2.to_csv(event2_path, index=False)
    output2_dir = tmp / "out2"
    args2 = type(
        "Args",
        (),
        {
            "events": [str(event2_path)],
            "price_cache": str(price_cache),
            "output_dir": str(output2_dir),
            "peak_window": 126,
            "reset_window": 126,
            "event_window": 10,
        },
    )()
    run(args2)
    out2 = pd.read_csv(output2_dir / "events.csv")
    row2 = out2.iloc[0]
    assert row2["pattern_bucket"] == "long_base_shakeout_reversal_confirmed"
    assert int(row2["days_peak_to_low"]) > 21
    assert int(row2["reclaim_prior_peak_63d"]) == 1
    print("shakeout_disclosure_reversal_study_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.materialize_cash_rate_series import run  # noqa: E402


class Args:
    pass


def test_materialize_cash_rate_from_fallback_csv() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fallback = root / "dgs3mo.csv"
        pd.DataFrame(
            [
                {"DATE": "2026-01-02", "DGS3MO": 4.25},
                {"DATE": "2026-01-05", "DGS3MO": "."},
                {"DATE": "2026-01-06", "DGS3MO": 4.30},
            ]
        ).to_csv(fallback, index=False)
        args = Args()
        args.rate_source = "dgs3mo"
        args.output_cache = str(root / "cache_macro")
        args.summary = str(root / "outputs" / "cash_rate_materialization" / "summary.json")
        args.fallback_csv = str(fallback)
        args.force = True
        payload = run(args)
        assert payload["status"] == "completed", payload
        assert payload["series_id"] == "DGS3MO"
        assert payload["row_count"] == 2
        assert Path(payload["output_path"]).exists()
        assert payload["latest_rate_pct"] == 4.30


def main() -> int:
    test_materialize_cash_rate_from_fallback_csv()
    print("cash_rate_materialization_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

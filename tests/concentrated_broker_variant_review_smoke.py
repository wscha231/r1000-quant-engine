#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_concentrated_broker_variant_review import build_review, parse_variants, write_outputs
from tools.run_weekly_evaluation import px_cache_name


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_px(cache_dir: Path, ticker: str, closes: list[float]) -> None:
    idx = pd.bdate_range("2026-01-02", periods=len(closes))
    pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    ).to_parquet(cache_dir / px_cache_name(ticker))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        reports = root / "reports"
        output = root / "operator_review"
        cache.mkdir()
        reports.mkdir()
        for ticker, start in [("AAA", 100), ("BBB", 90), ("CCC", 80), ("DDD", 70), ("EEE", 60)]:
            _write_px(cache, ticker, [start, start + 2, start + 4, start + 6, start + 8, start + 10])

        rows: list[dict] = []
        for rebalance_date in ["2026-01-02", "2026-01-07"]:
            for ticker, weight in [("AAA", 0.40), ("BBB", 0.30), ("CCC", 0.30)]:
                rows.append(
                    {
                        "rebalance_date": rebalance_date,
                        "ticker": ticker,
                        "weight": weight,
                        "target_stock_names": 3,
                        "weighting_mode": "score_power",
                        "active_rebalance_interval_months": 1,
                    }
                )
            for ticker, weight in [("AAA", 0.25), ("BBB", 0.20), ("CCC", 0.20), ("DDD", 0.20), ("EEE", 0.15)]:
                rows.append(
                    {
                        "rebalance_date": rebalance_date,
                        "ticker": ticker,
                        "weight": weight,
                        "target_stock_names": 5,
                        "weighting_mode": "score_power",
                        "active_rebalance_interval_months": 1,
                    }
                )
        pd.DataFrame(rows).to_csv(reports / "concentrated_strategy_holdings.csv", index=False)
        _write_json(
            root / "account_evaluation" / "official_metrics.json",
            {
                "official_metric_mode": "broker_ledger_next_close",
                "portfolios": {
                    "concentrated": {
                        "status": "completed",
                        "official_metric_mode": "broker_ledger_next_close",
                        "cagr": 0.31,
                        "max_dd": -0.39,
                        "sharpe": 1.0,
                        "end_date": "2026-02-28",
                    }
                },
            },
        )

        payload = build_review(
            latest_run=root,
            price_cache=cache,
            output_dir=output,
            variants=parse_variants("3:score_power:1,5:score_power:1"),
            cost_bps=25.0,
            max_fill_lag_days=7,
        )
        assert payload["research_only"] is True
        assert payload["production_activation_allowed"] is False
        rows_by_id = {row["variant_id"]: row for row in payload["rows"]}
        assert {"N3_score_power_I1", "N5_score_power_I1"}.issubset(rows_by_id)
        assert rows_by_id["N3_score_power_I1"]["metric_mode"] == "broker_ledger_next_close"
        assert rows_by_id["N5_score_power_I1"]["status"] == "completed"
        assert rows_by_id["N5_score_power_I1"]["coverage_reaches_official_end"] is False
        assert rows_by_id["N5_score_power_I1"]["review_valid_for_promotion"] is False
        write_outputs(payload, output)
        assert (output / "concentrated_broker_variant_review.json").exists()
        report = (output / "concentrated_broker_variant_review.md").read_text(encoding="utf-8")
        assert "Production activation allowed: `false`" in report
        assert "N5_score_power_I1" in report
    print("concentrated_broker_variant_review_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

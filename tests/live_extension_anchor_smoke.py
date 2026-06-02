#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.r1000_live_extension import infer_anchor_date, latest_date_from_json_payload


def test_infers_anchor_date_from_broker_metrics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        portfolio_path = root / "portfolio_latest.csv"
        portfolio = pd.DataFrame([{"ticker": "AAA", "weight": 0.2}])
        portfolio.to_csv(portfolio_path, index=False)
        metrics_dir = root / "broker_replay" / "main"
        metrics_dir.mkdir(parents=True)
        (metrics_dir / "metrics.json").write_text(
            json.dumps({"status": "completed", "end_date": "2026-05-29"}),
            encoding="utf-8",
        )

        assert infer_anchor_date(portfolio_path, portfolio, None) == "2026-05-29"


def test_infers_anchor_date_from_official_current_metrics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        portfolio_path = root / "portfolio_latest.csv"
        portfolio = pd.DataFrame([{"ticker": "AAA", "weight": 0.2}])
        portfolio.to_csv(portfolio_path, index=False)
        current_dir = root / "user_current"
        current_dir.mkdir(parents=True)
        (current_dir / "04_official_metrics.json").write_text(
            json.dumps(
                {
                    "official_metric_mode": "broker_ledger_next_close",
                    "portfolios": {
                        "main": {"end_date": "2026-05-29"},
                        "concentrated": {"end_date": "2026-05-28"},
                    },
                }
            ),
            encoding="utf-8",
        )

        assert infer_anchor_date(portfolio_path, portfolio, None) == "2026-05-29"


def test_portfolio_date_takes_precedence_over_json_metrics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        portfolio_path = root / "portfolio_latest.csv"
        portfolio = pd.DataFrame([{"ticker": "AAA", "weight": 0.2, "asof": "2026-06-01"}])
        portfolio.to_csv(portfolio_path, index=False)
        metrics_dir = root / "broker_replay" / "main"
        metrics_dir.mkdir(parents=True)
        (metrics_dir / "metrics.json").write_text(
            json.dumps({"status": "completed", "end_date": "2026-05-29"}),
            encoding="utf-8",
        )

        assert infer_anchor_date(portfolio_path, portfolio, None) == "2026-06-01"


def test_generated_at_is_not_an_anchor_date_candidate() -> None:
    payload = {
        "generated_at_utc": "2026-05-30T09:40:15+00:00",
        "portfolios": {"main": {"end_date": "2026-05-29"}},
    }
    assert latest_date_from_json_payload(payload, ["end_date", "as_of_date", "asof", "date", "anchor_date"]) == "2026-05-29"


def main() -> int:
    test_infers_anchor_date_from_broker_metrics()
    test_infers_anchor_date_from_official_current_metrics()
    test_portfolio_date_takes_precedence_over_json_metrics()
    test_generated_at_is_not_an_anchor_date_candidate()
    print("live_extension_anchor_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

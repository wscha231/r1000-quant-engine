#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_public_portfolio_dashboard import (  # noqa: E402
    build_dashboard,
    validate_public_payload,
)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def build_replay_fixture(root: Path) -> Path:
    source = root / "replay"
    for portfolio, ticker, cash, cagr, max_dd in [
        ("main", "AAA", 0.20, 0.35, -0.24),
        ("concentrated", "BBB", 0.35, 0.51, -0.22),
    ]:
        target = source / "replays" / portfolio
        write_csv(
            target / "positions_latest.csv",
            [
                {
                    "as_of_date": "2026-07-10",
                    "ticker": ticker,
                    "shares": "100",
                    "price": "125.5",
                    "market_value_usd": "12550",
                    "weight": str(1.0 - cash),
                    "cost_basis": "90",
                    "unrealized_pnl_usd": "3550",
                }
            ],
        )
        write_csv(
            target / "equity_curve.csv",
            [
                {"date": "2019-06-03", "equity_usd": "100000", "cash_weight": str(cash)},
                {"date": "2026-07-10", "equity_usd": "800000", "cash_weight": str(cash)},
            ],
        )
        write_csv(
            target / "trades.csv",
            [
                {
                    "ticker": ticker,
                    "side": "BUY",
                    "quantity": "100",
                    "fill_price": "100",
                    "gross_value": "10000",
                    "fee_usd": "25",
                    "cash_after": "90000",
                    "shares_after": "100",
                    "date": "2026-07-06",
                    "signal_date": "2026-07-02",
                    "reason": "target_rebalance",
                    "target_weight": str(1.0 - cash),
                    "fill_mode": "next_close",
                }
            ],
        )
        write_json(
            target / "metrics.json",
            {
                "portfolio_kind": portfolio,
                "cagr": cagr,
                "max_dd": max_dd,
                "sharpe": 1.4,
                "avg_cash_weight": cash,
                "trade_count": 42,
                "start_date": "2019-06-03",
                "end_date": "2026-07-10",
                "metric_mode": "broker_ledger_next_close_cash_carry",
                "fill_mode": "next_close",
                "cost_bps_per_side": 25,
                "valid_for_production": False,
                "target_book": r"H:\private\target.csv",
                "starting_capital_usd": 100000,
                "ending_capital_usd": 800000,
            },
        )
    return source


def test_replay_export_is_privacy_safe() -> None:
    with TemporaryDirectory() as tmp:
        source = build_replay_fixture(Path(tmp))
        payload = build_dashboard(source)
        validate_public_payload(payload)

        assert payload["as_of_close"] == "2026-07-10"
        assert payload["status"]["review_only"] is True
        assert payload["status"]["live_trading_enabled"] is False
        assert payload["portfolios"]["main"]["cash_weight"] == 0.20
        assert payload["portfolios"]["main"]["holdings"][0]["ticker"] == "AAA"
        assert payload["portfolios"]["main"]["trades"][0]["side"] == "BUY"

        encoded = json.dumps(payload).lower()
        for forbidden in [
            '"market_value_usd":',
            '"shares_after":',
            '"quantity":',
            '"cost_basis":',
            '"unrealized_pnl_usd":',
            '"ending_capital_usd":',
            r"h:\private",
        ]:
            assert forbidden not in encoded, forbidden


def test_daily_artifact_refreshes_holdings_but_not_fake_trades() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        base = build_dashboard(build_replay_fixture(root))
        base_path = root / "dashboard.json"
        write_json(base_path, base)

        current = root / "daily" / "user_current"
        write_json(
            current / "summary.json",
            {
                "review_only": True,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
                "source_run_id": "123",
                "source_commit_sha": "abc",
            },
        )
        write_csv(
            current / "01_current_holdings.csv",
            [
                {
                    "portfolio_kind": "main",
                    "row_type": "equity",
                    "ticker": "NEW",
                    "current_weight": "0.70",
                    "current_shares": "77",
                    "current_price": "200",
                    "as_of_date": "2026-07-11",
                },
                {
                    "portfolio_kind": "main",
                    "row_type": "cash",
                    "ticker": "CASH",
                    "current_weight": "0.30",
                    "current_shares": "0",
                    "current_price": "1",
                    "as_of_date": "2026-07-11",
                },
                {
                    "portfolio_kind": "concentrated",
                    "row_type": "equity",
                    "ticker": "BBB",
                    "current_weight": "0.65",
                    "current_shares": "99",
                    "current_price": "130",
                    "as_of_date": "2026-07-11",
                },
            ],
        )
        write_csv(
            current / "02_target_weights.csv",
            [
                {"portfolio_kind": "main", "ticker": "NEW", "target_weight": "0.75"},
                {"portfolio_kind": "main", "ticker": "CASH", "target_weight": "0.25"},
            ],
        )
        write_csv(
            current / "03_order_preview.csv",
            [
                {
                    "portfolio_kind": "main",
                    "ticker": "NEW",
                    "action": "REVIEW_REQUIRED",
                    "current_weight": "0.70",
                    "target_weight": "0.75",
                    "delta_weight": "0.05",
                    "reference_price": "200",
                    "quantity": "15",
                }
            ],
        )
        write_json(
            current / "08_rebalance_decision.json",
            {"decision": "REVIEW_REQUIRED", "live_trading_enabled": False},
        )

        payload = build_dashboard(root / "daily", base_json=base_path)
        validate_public_payload(payload)
        assert payload["as_of_close"] == "2026-07-11"
        assert payload["source"]["mode"] == "daily_operating_review_artifact"
        assert payload["source"]["trade_history_status"] == "retained_from_last_validated_replay"
        assert payload["portfolios"]["main"]["holdings"][0]["ticker"] == "NEW"
        assert payload["portfolios"]["main"]["target_cash_weight"] == 0.25
        assert payload["portfolios"]["main"]["trades"][0]["ticker"] == "AAA"
        assert payload["order_previews"][0]["executed"] is False
        assert '"quantity":' not in json.dumps(payload).lower()


def test_static_site_references_only_public_assets() -> None:
    html = (ROOT / "docs" / "public" / "index.html").read_text(encoding="utf-8")
    assert "./styles.css" in html
    assert "./app.js" in html
    assert "CODEX_" not in html
    assert "AGENT_SHARED" not in html
    assert "noindex, nofollow" in html


def main() -> int:
    test_replay_export_is_privacy_safe()
    test_daily_artifact_refreshes_holdings_but_not_fake_trades()
    test_static_site_references_only_public_assets()
    print("public_portfolio_dashboard_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

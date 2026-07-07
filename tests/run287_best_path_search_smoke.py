#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_run287_best_path_search import run  # noqa: E402


class Args:
    pass


def write_json(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


def write_arm(root: Path, arm: str, *, shares_aaa: float, shares_bbb: float, cagr: float, mdd: float) -> None:
    arm_root = root / "main" / arm
    broker = arm_root / "broker"
    broker.mkdir(parents=True)
    write_json(
        broker / "metrics.json",
        (
            '{"cagr": %.6f, "max_dd": %.6f, "max_dd_peak_date": "2022-01-01", '
            '"max_dd_trough_date": "2022-01-03"}'
        )
        % (cagr, mdd),
    )
    pd.DataFrame(
        [
            {"date": "2022-01-01", "equity_usd": 200.0},
            {"date": "2022-01-02", "equity_usd": 180.0},
            {"date": "2022-01-03", "equity_usd": 160.0},
        ]
    ).to_csv(broker / "equity_curve.csv", index=False)
    rows = []
    for date, px_aaa, px_bbb in [
        ("2022-01-01", 10.0, 10.0),
        ("2022-01-02", 8.0, 11.0),
        ("2022-01-03", 7.0, 10.0),
    ]:
        rows.append(
            {
                "date": date,
                "ticker": "AAA",
                "shares": shares_aaa,
                "price": px_aaa,
                "market_value_usd": shares_aaa * px_aaa,
                "weight": shares_aaa * px_aaa / 200.0,
            }
        )
        rows.append(
            {
                "date": date,
                "ticker": "BBB",
                "shares": shares_bbb,
                "price": px_bbb,
                "market_value_usd": shares_bbb * px_bbb,
                "weight": shares_bbb * px_bbb / 200.0,
            }
        )
    pd.DataFrame(rows).to_csv(broker / "holdings_daily.csv", index=False)
    pd.DataFrame(
        [
            {
                "arm": arm,
                "rebalance_date": "2022-01-01",
                "ticker": "AAA",
                "score": 0.9,
                "eligible": True,
                "pre_weight": 0.5,
                "post_weight": shares_aaa * 10.0 / 200.0,
                "delta_weight": shares_aaa * 10.0 / 200.0 - 0.5,
            },
            {
                "arm": arm,
                "rebalance_date": "2022-01-01",
                "ticker": "BBB",
                "score": -0.2,
                "eligible": False,
                "pre_weight": 0.5,
                "post_weight": shares_bbb * 10.0 / 200.0,
                "delta_weight": shares_bbb * 10.0 / 200.0 - 0.5,
            },
        ]
    ).to_csv(arm_root / "stock_telemetry.csv", index=False)


def test_best_path_search_contract_blocked_source_candidate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        replay_root = root / "replay"
        write_arm(replay_root, "baseline", shares_aaa=10, shares_bbb=10, cagr=0.338, mdd=-0.253)
        write_arm(
            replay_root,
            "growth_confirmation_top_quintile_tilt10",
            shares_aaa=15,
            shares_bbb=5,
            cagr=0.358,
            mdd=-0.259,
        )
        fusion_summary = root / "fusion_summary.json"
        source_summary = root / "source_summary.json"
        parity = root / "parity.json"
        survivorship = root / "survivorship.json"
        write_json(fusion_summary, '{"decision_label":"reject_no_broker_ab_candidate"}')
        write_json(
            source_summary,
            """
{
  "arm_rows": [
    {"portfolio_kind":"concentrated","signal":"w4_sec_score","arm":"baseline","ab_verdict":"baseline","cagr":0.484,"max_dd":-0.23,"delta_cagr_pp":0.0,"delta_max_dd_pp":0.0},
    {"portfolio_kind":"concentrated","signal":"w4_sec_score","arm":"w4_sec_top_quintile_tilt10","ab_verdict":"broker_ab_positive_requires_review","cagr":0.512,"max_dd":-0.241,"delta_cagr_pp":2.8,"delta_max_dd_pp":-1.1},
    {"portfolio_kind":"concentrated","signal":"risk_control_score","arm":"risk_control_top_quintile_tilt10","ab_verdict":"reject_no_cagr_edge","cagr":0.470,"max_dd":-0.220,"delta_cagr_pp":-1.4,"delta_max_dd_pp":1.0}
  ]
}
""".strip(),
        )
        write_json(parity, '{"runner_parity_status":"parity_documented_gap","runner_parity_reason":"fixture"}')
        write_json(
            survivorship,
            '{"label":"proxy","unmeasured_component":"delisted_exclusion",'
            '"survivorship_inflation_estimate_cagr_pp":0.0,'
            '"survivorship_inflation_estimate":{"cagr_pp_lower_bound":0.0,"label":"proxy",'
            '"method":"fixture","unmeasured_component":"delisted_exclusion"}}',
        )
        args = Args()
        args.fusion_broker_summary = str(fusion_summary)
        args.fusion_replay_root = str(replay_root)
        args.source_broker_summary = str(source_summary)
        args.output_dir = str(root / "out")
        args.parity_summary = str(parity)
        args.survivorship_summary = str(survivorship)
        payload = run(args)
        assert payload["status"] == "completed"
        assert payload["research_only"] is True
        assert payload["candidate_allowed"] is False
        assert payload["fullrun_dispatched"] is False
        assert payload["new_alpha_hook_added"] is False
        assert payload["threshold_tuning_performed"] is False
        assert payload["production_promotion_allowed"] is False
        assert payload["live_trading_enabled"] is False
        assert payload["measurement_contract_acceptance_allowed"] is False
        assert "runner_parity_not_exact" in payload["measurement_contract_acceptance_blockers"]
        assert payload["decision_label"] == "best_path_concentrated_source_candidate_review_only_measurement_blocked"
        assert payload["main_mdd_attribution"]["decision"] == "main_growth_signal_exists_but_mdd_blocked"
        assert payload["main_mdd_attribution"]["top_mdd_worseners"][0]["ticker"] == "AAA"
        assert (root / "out" / "main_mdd_ticker_attribution.csv").exists()
        assert (root / "out" / "concentrated_source_ranking.csv").exists()
        assert (root / "out" / "summary.json").exists()
        assert (root / "out" / "report.md").exists()


def main() -> int:
    test_best_path_search_contract_blocked_source_candidate()
    print("run287_best_path_search_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

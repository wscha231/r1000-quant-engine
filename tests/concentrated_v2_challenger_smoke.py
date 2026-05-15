#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_concentrated_v2_challenger import replay


def make_row(date: str, ticker: str, score: float, ret: float, *, risk: float = 0.0, stale: float = 0.0, sector: str = "Tech") -> dict:
    return {
        "rebalance_date": date,
        "ticker": ticker,
        "Name": ticker,
        "sector": sector,
        "industry_group": sector,
        "period_forward_return": ret,
        "score": score,
        "score_total": score,
        "portfolio_future_winner_engine_score": score,
        "portfolio_monster_early_score": score,
        "h6_dynamic_leader_score": score,
        "oneil_leadership_score": score,
        "industry_group_strength_score": score,
        "future_winner_scout_score": score,
        "rs_acceleration_score": score,
        "entry_quality_score": score,
        "selection_confirmation_score": score,
        "concentrated_score": score,
        "portfolio_risk_entry_block_score": risk,
        "portfolio_stale_mega_leader_score": stale,
        "risk_penalty": risk,
        "stage2_overext_penalty": 0.0,
        "overheat_penalty": 0.0,
        "rs_benchmark_3m": score - 0.5,
        "portfolio_candidate_gate_label": "pass",
        "dollar_vol_20d": 20_000_000,
        "market_cap_live": 5_000_000_000,
        "mktcap": 5_000_000_000,
        "regime_state": "bull",
    }


def test_concentrated_v2_challenger_outputs_replay_book() -> None:
    tmp = REPO_ROOT / "_tmp_concentrated_v2_smoke"
    if tmp.exists():
        shutil.rmtree(tmp)
    latest = tmp / "latest" / "reports"
    latest.mkdir(parents=True, exist_ok=True)
    rows = [
        make_row("2024-01-31", "AAA", 0.92, 0.10),
        make_row("2024-01-31", "BBB", 0.82, 0.02),
        make_row("2024-01-31", "CCC", 0.68, -0.01),
        make_row("2024-02-29", "AAA", 0.90, 0.08),
        make_row("2024-02-29", "DDD", 0.88, 0.15),
        make_row("2024-02-29", "BBB", 0.20, -0.12, risk=0.85),
        make_row("2024-03-31", "DDD", 0.91, 0.06),
        make_row("2024-03-31", "EEE", 0.84, 0.04, sector="Energy"),
        make_row("2024-03-31", "AAA", 0.40, -0.02, stale=0.70),
    ]
    candidate_book = latest / "candidate_replay_book.csv"
    pd.DataFrame(rows).to_csv(candidate_book, index=False)
    out_dir = tmp / "out"
    metrics = replay(
        candidate_book,
        out_dir,
        cost_bps=25,
        target_n=3,
        single_cap=0.50,
        min_market_cap_usd=1_000_000_000,
        min_dollar_volume_usd=5_000_000,
    )
    assert metrics["status"] == "completed"
    assert metrics["research_only"] is True
    assert metrics["production_activation_allowed"] is False
    assert metrics["broker_ledger_required_for_official_verdict"] is True
    assert metrics["used_forward_return_for_selection"] is False
    holdings = pd.read_csv(out_dir / "monthly_holdings.csv")
    assert not holdings.empty
    assert holdings.groupby("rebalance_date")["ticker"].nunique().max() <= 3
    assert holdings.groupby("rebalance_date")["weight"].sum().max() <= 1.000001
    assert holdings["weight"].max() <= 0.500001
    decisions = pd.read_csv(out_dir / "decisions.csv")
    assert "drop" in set(decisions["decision"].astype(str))
    assert (out_dir / "target_book.csv").exists()
    assert json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))["status"] == "completed"
    shutil.rmtree(tmp)


def main() -> int:
    test_concentrated_v2_challenger_outputs_replay_book()
    print("concentrated_v2_challenger_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

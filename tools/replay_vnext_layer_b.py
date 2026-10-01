#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

REGIME_EXPOSURE = {"strong_bull": 1.0, "bull": 1.0, "neutral": 0.90, "bear": 0.65, "deep_bear": 0.40}
COST_PER_NOTIONAL = 0.0025


def metrics(returns: pd.Series) -> dict[str, float | int | None]:
    returns = pd.to_numeric(returns, errors="coerce").fillna(0)
    nav = (1 + returns).cumprod()
    count = len(returns)
    years = count / 12.0
    cagr = float(nav.iloc[-1] ** (1 / years) - 1) if count and nav.iloc[-1] > 0 else None
    drawdown = nav / nav.cummax() - 1
    std = returns.std(ddof=1)
    sharpe = float(returns.mean() / std * math.sqrt(12)) if std and std > 0 else None
    return {
        "months": count,
        "ending_nav": float(nav.iloc[-1]),
        "cagr": cagr,
        "checkpoint_mdd": float(drawdown.min()),
        "sharpe_monthly_annualized": sharpe,
    }


def run(frame: pd.DataFrame, target_n: int, hold_buffer: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = sorted(frame.rebalance_date.dropna().unique())
    previous: dict[str, float] = {}
    equity_rows = []
    selection_rows = []
    for decision_date in dates:
        group = frame[frame.rebalance_date == decision_date].copy()
        pool = group[group.candidate_discovery_pass_b1 & group.expected_return_confidence_adj_b1.notna()].copy()
        pool = pool.sort_values(["expected_return_confidence_adj_b1", "leadership_score_b1"], ascending=False)
        ranks = {ticker: index + 1 for index, ticker in enumerate(pool.ticker.tolist())}
        keep_limit = max(target_n, int(math.ceil(target_n * (1 + hold_buffer))))
        chosen = [ticker for ticker in previous if ticker in ranks and ranks[ticker] <= keep_limit]
        for ticker in pool.ticker:
            if ticker not in chosen:
                chosen.append(ticker)
            if len(chosen) >= target_n:
                break
        chosen = chosen[:target_n]
        mode = group.regime_state.dropna().mode() if "regime_state" in group else pd.Series(dtype=str)
        regime = mode.iat[0] if not mode.empty else "neutral"
        exposure = REGIME_EXPOSURE.get(str(regime), 0.90)
        current = {ticker: exposure / len(chosen) for ticker in chosen} if chosen else {}
        turnover = sum(abs(current.get(ticker, 0) - previous.get(ticker, 0)) for ticker in set(current) | set(previous))
        cost = turnover * COST_PER_NOTIONAL
        selected = group[group.ticker.isin(chosen)]
        period_return = sum(current.get(row.ticker, 0) * float(row.r_1m) for row in selected.itertuples()) - cost
        equity_rows.append({
            "rebalance_date": decision_date,
            "portfolio_return": period_return,
            "regime": regime,
            "exposure": exposure,
            "turnover_stock_notional": turnover,
            "cost": cost,
            "holdings": len(chosen),
        })
        for ticker in chosen:
            row = pool[pool.ticker == ticker].iloc[0]
            selection_rows.append({
                "rebalance_date": decision_date,
                "ticker": ticker,
                "weight": current[ticker],
                "rank": ranks[ticker],
                "leadership_score_b1": row.leadership_score_b1,
                "expected_return_proxy_b1": row.expected_return_proxy_b1,
                "layer_b_coverage_b1": row.layer_b_coverage_b1,
                "r_1m": row.r_1m,
            })
        previous = current
    return pd.DataFrame(equity_rows), pd.DataFrame(selection_rows)


def period_metrics(equity: pd.DataFrame) -> dict[str, dict[str, float | int | None]]:
    work = equity.copy()
    work["year"] = pd.to_datetime(work.rebalance_date).dt.year
    spans = {"2019_2021": (2019, 2021), "2022_2023": (2022, 2023), "2024_2026": (2024, 2026)}
    output = {}
    for name, (first, last) in spans.items():
        returns = work[(work.year >= first) & (work.year <= last)].portfolio_return
        if len(returns):
            output[name] = metrics(returns.reset_index(drop=True))
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer-b", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    frame = pd.read_csv(args.layer_b, compression="gzip", low_memory=False)
    frame["rebalance_date"] = pd.to_datetime(frame.rebalance_date)
    output_dir = Path(args.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "vnext-layer-b-replay-v1",
        "authority": "RESEARCH_ONLY",
        "cost_per_side": COST_PER_NOTIONAL,
        "regime_exposure": REGIME_EXPOSURE,
        "performance_mdd_kind": "MONTHLY_CHECKPOINT_NOT_DAILY_CERTIFIED",
        "models": {},
    }
    for name, target_n in [("main", 15), ("concentrated", 8)]:
        equity, selections = run(frame, target_n, 0.20)
        equity.to_csv(output_dir / f"{name}_equity.csv", index=False)
        selections.to_csv(output_dir / f"{name}_selections.csv", index=False)
        summary["models"][name] = {
            "full": metrics(equity.portfolio_return),
            "subperiods": period_metrics(equity),
            "avg_exposure": float(equity.exposure.mean()),
            "avg_stock_turnover": float(equity.turnover_stock_notional.mean()),
        }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

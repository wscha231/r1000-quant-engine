#!/usr/bin/env python3
"""IS-only attribution for a broker_replay run.

Surface where the IS-period CAGR is leaking by breaking the equity curve down
by year, attributing returns to invested-vs-cash, and tagging the leak driver
(under-investment in bull regime vs over-defense in bear regime vs flat alpha).

Run 27498401423 surfaced the headline blind spot: full-period CAGR 34.33%
Main / 44.57% Conc looked respectable, but the IS-only (2019-06 -> 2024-06)
window was 21.45% / 21.29%. This tool tells you year-by-year where the
14pp+ leak is.

Outputs (per portfolio):
  outputs/is_attribution/<portfolio>_yearly.csv
  outputs/is_attribution/<portfolio>_summary.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def repo_path(p: str | Path) -> Path:
    pp = Path(p)
    return pp if pp.is_absolute() else (REPO / pp)


def _load_equity(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["year"] = df["date"].dt.year
    df["cash_weight"] = pd.to_numeric(df.get("cash_weight"), errors="coerce").fillna(0.0)
    df["position_count"] = pd.to_numeric(df.get("position_count"), errors="coerce").fillna(0).astype(int)
    return df


def _load_target_book(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path, low_memory=False)
    df["rebalance_date"] = pd.to_datetime(df.get("rebalance_date"), errors="coerce")
    df = df.dropna(subset=["rebalance_date"])
    df["year"] = df["rebalance_date"].dt.year
    df["is_cash"] = df["ticker"].astype(str).str.upper().isin({"CASH", "__CASH__"})
    df["weight"] = pd.to_numeric(df.get("weight"), errors="coerce").fillna(0.0)
    return df


def _yearly_equity(eq: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for yr, g in eq.groupby("year"):
        g = g.sort_values("date")
        start_eq = float(g["equity_usd"].iloc[0])
        end_eq = float(g["equity_usd"].iloc[-1])
        days = (g["date"].iloc[-1] - g["date"].iloc[0]).days + 1
        year_frac = max(days / 365.25, 1e-6)
        ret = (end_eq / start_eq) - 1.0 if start_eq > 0 else 0.0
        cagr = (1.0 + ret) ** (1.0 / year_frac) - 1.0 if (1.0 + ret) > 0 else float("nan")
        # in-year max drawdown
        cummax = g["equity_usd"].cummax()
        dd = ((g["equity_usd"] / cummax) - 1.0).min()
        rows.append({
            "year": int(yr),
            "start_eq": start_eq,
            "end_eq": end_eq,
            "year_return": ret,
            "year_cagr": cagr,
            "max_dd_in_year": float(dd),
            "avg_cash_weight": float(g["cash_weight"].mean()),
            "avg_positions": float(g["position_count"].mean()),
            "year_frac": year_frac,
            "days": days,
        })
    return pd.DataFrame(rows)


def _yearly_target_book(book: pd.DataFrame | None) -> pd.DataFrame:
    if book is None or book.empty:
        return pd.DataFrame(columns=["year", "avg_stock_weight_sum", "avg_stock_names", "regime_dist"])
    rows = []
    for yr, g in book.groupby("year"):
        stock = g[~g["is_cash"]]
        per_month_wt = stock.groupby("rebalance_date")["weight"].sum()
        per_month_n = stock.groupby("rebalance_date").size()
        regime_top = ""
        if "regime_state" in g.columns:
            rd = stock["regime_state"].value_counts(normalize=True).head(3)
            regime_top = "; ".join(f"{k}={v*100:.0f}%" for k, v in rd.items())
        rows.append({
            "year": int(yr),
            "avg_stock_weight_sum": float(per_month_wt.mean()) if len(per_month_wt) else 0.0,
            "avg_stock_names": float(per_month_n.mean()) if len(per_month_n) else 0.0,
            "regime_dist": regime_top,
        })
    return pd.DataFrame(rows)


def _classify_leak(row: dict) -> str:
    """Tag the year as one of:
      - structural_underinvestment_bull: bull/strong_bull regime + low stock_weight_sum + flat or negative return
      - over_defense_bear: bear regime + high cash + small negative return (defense worked)
      - flat_alpha_invested: high stock_weight_sum but low return — selection problem
      - healthy: strong return with reasonable stock_weight
      - mixed_neutral: neutral with mediocre return
    """
    ret = row.get("year_return", 0.0)
    cash = row.get("avg_cash_weight", 0.0)
    stock_wt = row.get("avg_stock_weight_sum", 1.0 - cash)
    if pd.isna(stock_wt):
        stock_wt = 1.0 - cash
    regime_raw = row.get("regime_dist")
    regime = str(regime_raw).lower() if regime_raw and not (isinstance(regime_raw, float) and pd.isna(regime_raw)) else ""
    bull_share = 0.0
    bear_share = 0.0
    for part in regime.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        try:
            pct = float(v.strip().rstrip("%")) / 100.0
        except ValueError:
            continue
        if "bull" in k:
            bull_share += pct
        elif "bear" in k:
            bear_share += pct
    if bear_share > 0.5 and ret > -0.20 and cash > 0.50:
        return "over_defense_bear_ok"
    if bull_share > 0.40 and stock_wt < 0.70 and ret < 0.25:
        return "structural_underinvestment_bull"
    if stock_wt > 0.75 and ret < 0.10:
        return "flat_alpha_invested"
    if ret > 0.30:
        return "healthy"
    return "mixed"


def _render_md(portfolio: str, merged: pd.DataFrame, summary: dict) -> str:
    lines = []
    lines.append(f"# {portfolio.title()} IS Attribution")
    lines.append("")
    lines.append(f"- Run period: {summary.get('start_date')} -> {summary.get('end_date')}")
    lines.append(f"- Full period CAGR: `{summary.get('full_cagr', float('nan'))*100:.2f}%`")
    lines.append(f"- IS-only CAGR (2019-06 -> 2024-06): `{summary.get('is_cagr', float('nan'))*100:.2f}%`")
    lines.append(f"- OOS-only CAGR (2024-07+): `{summary.get('oos_cagr', float('nan'))*100:.2f}%`")
    lines.append(f"- OOS / IS ratio: `{summary.get('oos_is_ratio', float('nan')):.2f}x`")
    lines.append("")
    lines.append("## Yearly breakdown")
    lines.append("")
    lines.append("| Year | Return | CAGR | Max DD | Avg Cash | Stock Wt | Names | Regime (top) | Leak Tag |")
    lines.append("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |")
    for _, r in merged.iterrows():
        lines.append(
            f"| {int(r['year'])} | {r['year_return']*100:+.2f}% | {r['year_cagr']*100:+.2f}% | {r['max_dd_in_year']*100:+.2f}% | "
            f"{r['avg_cash_weight']*100:.1f}% | {r.get('avg_stock_weight_sum', float('nan'))*100:.1f}% | "
            f"{r.get('avg_stock_names', float('nan')):.1f} | {r.get('regime_dist','')} | `{r['leak_tag']}` |"
        )
    lines.append("")
    lines.append("## Leak counts")
    lines.append("")
    counts = merged["leak_tag"].value_counts()
    for tag, n in counts.items():
        lines.append(f"- `{tag}`: {n} year(s)")
    lines.append("")
    return "\n".join(lines)


def run_for_portfolio(latest_run: Path, output_dir: Path, portfolio: str) -> dict:
    eq_path = latest_run / "broker_replay" / portfolio / "equity_curve.csv"
    book_path = latest_run / "reports" / f"operating_{portfolio}_target_book.csv"
    if not eq_path.exists():
        return {"portfolio": portfolio, "status": "missing_equity_curve"}
    eq = _load_equity(eq_path)
    book = _load_target_book(book_path)
    yearly = _yearly_equity(eq)
    yearly_book = _yearly_target_book(book)
    merged = yearly.merge(yearly_book, on="year", how="left")
    merged["leak_tag"] = merged.apply(lambda r: _classify_leak(r.to_dict()), axis=1)

    # is/oos splits — 2019-06 to 2024-06 IS, 2024-07+ OOS (standard split)
    eq_is = eq[eq["date"] < "2024-07-01"]
    eq_oos = eq[eq["date"] >= "2024-07-01"]
    def _cagr(seg: pd.DataFrame) -> float:
        if seg.empty:
            return float("nan")
        s, e = float(seg["equity_usd"].iloc[0]), float(seg["equity_usd"].iloc[-1])
        days = (seg["date"].iloc[-1] - seg["date"].iloc[0]).days
        yrs = max(days / 365.25, 1e-6)
        return (e / s) ** (1.0 / yrs) - 1.0 if s > 0 and e > 0 else float("nan")
    is_cagr = _cagr(eq_is)
    oos_cagr = _cagr(eq_oos)
    full_cagr = _cagr(eq)
    summary = {
        "portfolio": portfolio,
        "start_date": str(eq["date"].iloc[0].date()),
        "end_date": str(eq["date"].iloc[-1].date()),
        "full_cagr": full_cagr,
        "is_cagr": is_cagr,
        "oos_cagr": oos_cagr,
        "oos_is_ratio": (oos_cagr / is_cagr) if (is_cagr and is_cagr > 0.01) else float("nan"),
        "leak_year_tags": merged.set_index("year")["leak_tag"].to_dict(),
        "structural_underinvestment_bull_years": sorted(int(y) for y, t in merged.set_index("year")["leak_tag"].items() if t == "structural_underinvestment_bull"),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output_dir / f"{portfolio}_yearly.csv", index=False)
    (output_dir / f"{portfolio}_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (output_dir / f"{portfolio}_summary.md").write_text(_render_md(portfolio, merged, summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--latest-run", default="outputs")
    p.add_argument("--output-dir", default="outputs/is_attribution")
    p.add_argument("--portfolios", nargs="+", default=["main", "concentrated"])
    args = p.parse_args(argv)
    latest = repo_path(args.latest_run)
    out = repo_path(args.output_dir)
    rolled = {}
    for k in args.portfolios:
        rolled[k] = run_for_portfolio(latest, out, k)
    (out / "summary.json").write_text(json.dumps(rolled, indent=2, default=str), encoding="utf-8")
    for k, s in rolled.items():
        if s.get("status") == "missing_equity_curve":
            print(f"  {k}: missing equity_curve; skipped")
            continue
        print(f"  {k}: full {s['full_cagr']*100:.2f}% | IS {s['is_cagr']*100:.2f}% | OOS {s['oos_cagr']*100:.2f}% | underinvestment_bull years: {s['structural_underinvestment_bull_years']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

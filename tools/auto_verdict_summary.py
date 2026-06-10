#!/usr/bin/env python3
"""Generate Telegram-ready full-rebuild summary text.

Official performance evidence is account-like broker-ledger replay:

- next-close fills after the signal date
- integer shares
- cash accounting
- transaction costs
- daily account equity and drawdown

Monthly/weight-level backtest metrics are retained only as research context.
They must not trigger baseline rotation or production SHIP decisions.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def safe_load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def safe_load_csv(path: Path):
    if not path.exists():
        return None
    try:
        import pandas as pd

        return pd.read_csv(path)
    except Exception:
        return None


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if out != out:
            return default
        return out
    except (TypeError, ValueError):
        return default


def pct(value: Any) -> str:
    return f"{fnum(value) * 100:.2f}%"


def fmt_money(value: Any) -> str:
    return f"${fnum(value):,.0f}"


def official_rows(official: dict[str, Any]) -> dict[str, dict[str, Any]]:
    portfolios = official.get("portfolios")
    if isinstance(portfolios, dict):
        return {str(k): dict(v or {}) for k, v in portfolios.items()}
    if isinstance(portfolios, list):
        return {str(row.get("portfolio")): dict(row) for row in portfolios if isinstance(row, dict)}
    return {}


def legacy_metric(metrics: dict[str, Any], *names: str) -> float | None:
    for name in names:
        if name in metrics:
            return fnum(metrics.get(name))
    return None


def render_portfolio_snapshot(lines: list[str], portfolio) -> None:
    if portfolio is None or getattr(portfolio, "empty", True):
        return
    lines.append("")
    lines.append(f"Latest target snapshot: {len(portfolio)} rows")
    if "portfolio_sleeve_label" in portfolio.columns:
        sleeves = portfolio["portfolio_sleeve_label"].value_counts()
        sleeve_str = " / ".join(f"{k}:{v}" for k, v in sleeves.items())
        lines.append(f"  Sleeves: {sleeve_str}")
    if "ticker" in portfolio.columns and "weight" in portfolio.columns:
        top5 = portfolio.nlargest(min(5, len(portfolio)), "weight")[["ticker", "weight"]]
        top_str = ", ".join(f"{r['ticker']} {float(r['weight']) * 100:.1f}%" for _, r in top5.iterrows())
        lines.append(f"  Top 5: {top_str}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="outputs", help="output directory")
    parser.add_argument("--mode", default="global_alpha_universe", help="universe_mode label")
    args = parser.parse_args()

    out = Path(args.base)
    official = safe_load_json(out / "account_evaluation" / "official_metrics.json")
    account_summary = safe_load_json(out / "account_evaluation" / "account_evaluation_summary.json")
    main_legacy = safe_load_json(out / "backtest_metrics.json")
    concentrated_legacy = safe_load_json(out / "concentrated_backtest_metrics.json")
    portfolio = safe_load_csv(out / "portfolio_latest.csv")
    concentrated_portfolio = safe_load_csv(out / "concentrated_portfolio_latest.csv")

    rows = official_rows(official)
    production_pass = bool(official.get("production_target_pass"))

    lines: list[str] = []
    lines.append(f"r1000 [{args.mode}]")
    lines.append("OFFICIAL metric mode: broker-ledger next-close account replay")
    lines.append("Monthly/weight-level SHIP verdicts are deprecated research context.")
    lines.append("")

    if rows:
        lines.append("Official account performance:")
        for name in ("main", "concentrated"):
            row = rows.get(name, {})
            if not row:
                lines.append(f"  {name}: missing broker-ledger metrics")
                continue
            lines.append(
                "  {name}: CAGR {cagr} / Sharpe {sharpe:.3f} / MaxDD {maxdd} / "
                "cash {cash} / trades {trades} / equity {equity}".format(
                    name=name,
                    cagr=pct(row.get("cagr")),
                    sharpe=fnum(row.get("sharpe")),
                    maxdd=pct(row.get("max_dd")),
                    cash=pct(row.get("avg_cash_weight")),
                    trades=int(fnum(row.get("broker_trade_count"))),
                    equity=fmt_money(row.get("ending_capital_usd")),
                )
            )
        lines.append("")
        if production_pass:
            lines.append("OFFICIAL RESULT: production target pass. Review before baseline rotation.")
        else:
            lines.append("OFFICIAL RESULT: NO PRODUCTION SHIP. Improve broker-ledger CAGR/MaxDD first.")
    else:
        lines.append("Official account performance missing. Do not ship from legacy metrics.")

    lines.append("")
    lines.append("Research-only legacy metrics:")
    if main_legacy:
        lines.append(
            "  main weight-level: CAGR {cagr} / Sharpe {sharpe:.3f} / MaxDD {maxdd}".format(
                cagr=pct(legacy_metric(main_legacy, "cagr", "strategy_cagr")),
                sharpe=fnum(legacy_metric(main_legacy, "sharpe")),
                maxdd=pct(legacy_metric(main_legacy, "max_dd", "max_drawdown")),
            )
        )
    if concentrated_legacy:
        lines.append(
            "  concentrated weight-level: CAGR {cagr} / Sharpe {sharpe:.3f} / MaxDD {maxdd}".format(
                cagr=pct(legacy_metric(concentrated_legacy, "strategy_cagr", "cagr")),
                sharpe=fnum(legacy_metric(concentrated_legacy, "sharpe")),
                maxdd=pct(legacy_metric(concentrated_legacy, "max_dd", "max_drawdown")),
            )
        )
        if concentrated_legacy.get("production_valid") is False:
            lines.append("  concentrated weight-level production_valid=false")

    render_portfolio_snapshot(lines, portfolio)
    if concentrated_portfolio is not None and not concentrated_portfolio.empty:
        if "ticker" in concentrated_portfolio.columns and "weight" in concentrated_portfolio.columns:
            cstr = ", ".join(
                f"{r['ticker']} {float(r['weight']) * 100:.0f}%"
                for _, r in concentrated_portfolio.head(5).iterrows()
            )
            lines.append(f"  Concentrated latest: {cstr}")

    if account_summary:
        lines.append("")
        lines.append(
            "Governance: production_target_pass={p} research_target_pass={r}".format(
                p=str(account_summary.get("production_target_pass")).lower(),
                r=str(account_summary.get("research_target_pass")).lower(),
            )
        )

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Research-only R1 composite bear/correction nowcast dial.

This is a measurement artifact, not a market-timing or trading rule. Missing
signals are neutral and are reported through coverage fields.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.research_audit_utils import read_csv, repo_path, safe_float, write_json  # noqa: E402
from tools.run_weekly_evaluation import load_price_series  # noqa: E402

DEFAULT_OUTPUT_DIR = "outputs/regime_nowcast_dial"

WARNING_SIGNALS = [
    "spy_below_200dma",
    "qqq_below_200dma",
    "qqq_spy_rs_negative_1m_3m",
    "soxx_smh_rs_negative_vs_qqq",
    "universe_above_200dma_below_40pct",
    "vix_spike_or_above_25",
    "hy_oas_widening_threshold",
    "yield_curve_inversion_or_steepening_warning",
    "sahm_unemployment_momentum_warning",
    "eps_revision_breadth_negative",
    "positive_guidance_ratio_deteriorating",
    "ai_capex_bucket_rs_breakdown",
]

CONTEXT_SIGNALS = [
    "yield_curve_10y_3m",
    "hy_oas_widening",
    "breadth_ma200",
    "vix_percentile",
    "defensive_sector_rs",
    "unemployment_trend",
    "spy_200dma_slope",
    "distribution_days",
    "new_high_new_low_breadth",
    "earnings_revision_breadth",
    "rate_volatility_stress",
    "dxy_liquidity_financial_conditions_stress",
]

SUPPORTED_STATES = ["BULL", "LATE_CYCLE", "CORRECTION", "BEAR", "RECOVERY", "DATA_INSUFFICIENT"]

REQUIRED_REVIEW_ACTION = {
    "BULL": "normal_momentum_process_review",
    "LATE_CYCLE": "concentration_warning_and_eps_confirmation_review",
    "CORRECTION": "shock_review_no_new_discretionary_entries_cash_tbill_reserve_review",
    "BEAR": "capital_preservation_and_strategy_allocation_review",
    "RECOVERY": "staged_reentry_only_after_trend_and_breadth_confirmation",
    "DATA_INSUFFICIENT": "no_current_regime_claim_refresh_or_expand_signal_coverage",
}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "t", "triggered"}


def _series_until(price_cache: Path, ticker: str, as_of_date: str) -> pd.DataFrame:
    series = load_price_series(price_cache, ticker)
    if series.empty or "close" not in series.columns:
        return pd.DataFrame()
    series = series.sort_index()
    if as_of_date:
        series = series[series.index <= pd.Timestamp(as_of_date)]
    return series


def _return_over(series: pd.DataFrame, days: int) -> float | None:
    if len(series) <= days:
        return None
    start = safe_float(series["close"].iloc[-days - 1])
    end = safe_float(series["close"].iloc[-1])
    if start <= 0:
        return None
    return end / start - 1.0


def _ma200_warning(price_cache: Path, ticker: str, signal_name: str, as_of_date: str) -> dict[str, Any] | None:
    series = _series_until(price_cache, ticker, as_of_date)
    if len(series) < 200:
        return None
    close = safe_float(series["close"].iloc[-1])
    ma200 = safe_float(series["close"].tail(200).mean())
    if ma200 <= 0:
        return None
    return {
        "date": pd.Timestamp(series.index[-1]).date().isoformat(),
        "signal_name": signal_name,
        "value": close / ma200 - 1.0,
        "covered": True,
        "warning_triggered": close < ma200,
        "risk_score": 1.0 if close < ma200 else 0.0,
        "source": f"{ticker}_price_cache",
    }


def price_cache_warning_rows(price_cache: Path, as_of_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ticker, signal_name in [("SPY", "spy_below_200dma"), ("QQQ", "qqq_below_200dma")]:
        row = _ma200_warning(price_cache, ticker, signal_name, as_of_date)
        if row is not None:
            rows.append(row)

    spy = _series_until(price_cache, "SPY", as_of_date)
    qqq = _series_until(price_cache, "QQQ", as_of_date)
    if not spy.empty and not qqq.empty and len(spy) >= 64 and len(qqq) >= 64:
        qqq_1m = _return_over(qqq, 21)
        spy_1m = _return_over(spy, 21)
        qqq_3m = _return_over(qqq, 63)
        spy_3m = _return_over(spy, 63)
        if None not in {qqq_1m, spy_1m, qqq_3m, spy_3m}:
            rs_1m = float(qqq_1m) - float(spy_1m)
            rs_3m = float(qqq_3m) - float(spy_3m)
            rows.append(
                {
                    "date": pd.Timestamp(qqq.index[-1]).date().isoformat(),
                    "signal_name": "qqq_spy_rs_negative_1m_3m",
                    "value": min(rs_1m, rs_3m),
                    "covered": True,
                    "warning_triggered": rs_1m < 0.0 and rs_3m < 0.0,
                    "risk_score": 1.0 if rs_1m < 0.0 and rs_3m < 0.0 else 0.0,
                    "source": "price_cache",
                }
            )

    semi = _series_until(price_cache, "SOXX", as_of_date)
    if semi.empty:
        semi = _series_until(price_cache, "SMH", as_of_date)
    if not semi.empty and not qqq.empty and len(semi) >= 64 and len(qqq) >= 64:
        semi_3m = _return_over(semi, 63)
        qqq_3m = _return_over(qqq, 63)
        if semi_3m is not None and qqq_3m is not None:
            rs_3m = float(semi_3m) - float(qqq_3m)
            rows.append(
                {
                    "date": pd.Timestamp(semi.index[-1]).date().isoformat(),
                    "signal_name": "soxx_smh_rs_negative_vs_qqq",
                    "value": rs_3m,
                    "covered": True,
                    "warning_triggered": rs_3m < 0.0,
                    "risk_score": 1.0 if rs_3m < 0.0 else 0.0,
                    "source": "price_cache",
                }
            )
    return rows


def normalize_signal_panel(panel: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    if panel.empty:
        panel = pd.DataFrame(columns=["date", "signal_name", "risk_score", "covered", "warning_triggered", "value"])
    panel = panel.copy()
    if "date" not in panel.columns:
        panel["date"] = as_of_date
    if "signal_name" not in panel.columns:
        panel["signal_name"] = panel.get("warning_signal_name", "unknown")
    if "risk_score" not in panel.columns:
        score_col = "bearish_score" if "bearish_score" in panel.columns else "value"
        panel["risk_score"] = pd.to_numeric(panel.get(score_col), errors="coerce").clip(0.0, 1.0)
    if "covered" not in panel.columns:
        panel["covered"] = True
    trigger_col = next(
        (col for col in ["warning_triggered", "bear_warning_triggered", "triggered"] if col in panel.columns),
        "",
    )
    if trigger_col:
        panel["warning_triggered"] = panel[trigger_col].map(_truthy)
    else:
        panel["warning_triggered"] = pd.to_numeric(panel["risk_score"], errors="coerce").fillna(0.0) >= 0.75
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce").dt.date.astype(str)
    panel["signal_name"] = panel["signal_name"].astype(str).str.strip()
    panel["risk_score"] = pd.to_numeric(panel["risk_score"], errors="coerce").fillna(0.5).clip(0.0, 1.0)
    panel["covered"] = panel["covered"].map(_truthy)
    return panel


def complete_warning_signals(panel: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    panel = normalize_signal_panel(panel, as_of_date)
    dates = sorted([date for date in panel["date"].dropna().astype(str).unique() if date and date != "NaT"]) or [as_of_date]
    additions: list[dict[str, Any]] = []
    for dt in dates:
        names = set(panel.loc[panel["date"].astype(str).eq(dt), "signal_name"].astype(str))
        for signal_name in WARNING_SIGNALS:
            if signal_name not in names:
                additions.append(
                    {
                        "date": dt,
                        "signal_name": signal_name,
                        "risk_score": 0.5,
                        "covered": False,
                        "warning_triggered": False,
                        "value": "",
                        "source": "missing_neutral",
                    }
                )
    if additions:
        panel = pd.concat([panel, pd.DataFrame(additions)], ignore_index=True, sort=False)
    return normalize_signal_panel(panel, as_of_date)


def load_signal_panel(signal_panel: Path, price_cache: Path, as_of_date: str) -> pd.DataFrame:
    panel = read_csv(signal_panel) if signal_panel else pd.DataFrame()
    if panel.empty:
        panel = pd.DataFrame(price_cache_warning_rows(price_cache, as_of_date))
    return complete_warning_signals(panel, as_of_date)


def warning_interpretation(score: int) -> str:
    if score <= 2:
        return "risk_on"
    if score <= 4:
        return "watch"
    if score <= 6:
        return "correction_defensive"
    if score <= 8:
        return "bear_warning"
    return "capital_preservation"


def state_from_warning_score(score: int, covered_signal_count: int) -> str:
    if covered_signal_count < 6:
        return "DATA_INSUFFICIENT"
    if score <= 2:
        return "BULL"
    if score <= 4:
        return "LATE_CYCLE"
    if score <= 6:
        return "CORRECTION"
    return "BEAR"


def state_override(group: pd.DataFrame) -> str:
    for col in ["state_override", "regime_state", "current_state"]:
        if col not in group.columns:
            continue
        values = [str(value).strip().upper() for value in group[col].dropna().tolist()]
        for value in values:
            if value in SUPPORTED_STATES and value != "DATA_INSUFFICIENT":
                return value
    return ""


def build_state_history(panel: pd.DataFrame, allow_state_override: bool = False) -> pd.DataFrame:
    state_rows: list[dict[str, Any]] = []
    for dt, group in panel.groupby("date", dropna=False):
        warning_group = group[group["signal_name"].isin(WARNING_SIGNALS)]
        covered = warning_group[warning_group["covered"]]
        covered_names = sorted(set(covered["signal_name"].astype(str)))
        triggered = covered[covered["warning_triggered"]]
        triggered_names = sorted(set(triggered["signal_name"].astype(str)))
        missing_names = sorted(set(WARNING_SIGNALS) - set(covered_names))
        score = min(12, len(triggered_names))
        confidence = len(covered_names) / len(WARNING_SIGNALS)
        state = state_from_warning_score(score, len(covered_names))
        override = state_override(group) if allow_state_override else ""
        if state != "DATA_INSUFFICIENT" and override:
            state = override
        state_rows.append(
            {
                "date": dt,
                "state": state,
                "bear_warning_score": int(score),
                "bear_warning_label": warning_interpretation(score),
                "risk_score": score / 12.0,
                "signal_coverage": confidence,
                "confidence": confidence,
                "covered_signal_count": int(len(covered_names)),
                "expected_signal_count": int(len(WARNING_SIGNALS)),
                "triggered_signals": ";".join(triggered_names),
                "missing_signals": ";".join(missing_names),
                "required_review_action": REQUIRED_REVIEW_ACTION[state],
                "state_override_allowed": bool(allow_state_override),
                "state_override_applied": bool(override),
                "production_activation_allowed": False,
                "policy_hook_allowed": False,
            }
        )
    return pd.DataFrame(state_rows).sort_values("date")


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    as_of = args.as_of_date or pd.Timestamp.utcnow().date().isoformat()
    panel = load_signal_panel(repo_path(args.signal_panel) if args.signal_panel else Path(), repo_path(args.price_cache), as_of)
    state = build_state_history(panel, allow_state_override=bool(getattr(args, "allow_state_override", False)))
    panel.to_csv(output_dir / "signal_panel.csv", index=False)
    state.to_csv(output_dir / "state_history.csv", index=False)
    latest = state.iloc[-1].to_dict() if not state.empty else {}
    current_state = str(latest.get("state", "DATA_INSUFFICIENT"))
    payload = {
        "schema_version": "regime-nowcast-dial-v2",
        "status": "data_insufficient" if current_state == "DATA_INSUFFICIENT" else "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "as_of_date": latest.get("date", as_of),
        "current_state": current_state,
        "bear_warning_score": latest.get("bear_warning_score"),
        "bear_warning_label": latest.get("bear_warning_label"),
        "risk_score": latest.get("risk_score"),
        "signal_coverage": latest.get("signal_coverage"),
        "covered_signal_count": latest.get("covered_signal_count"),
        "expected_signal_count": latest.get("expected_signal_count"),
        "triggered_signals": str(latest.get("triggered_signals", "")).split(";") if latest.get("triggered_signals") else [],
        "missing_signals": str(latest.get("missing_signals", "")).split(";") if latest.get("missing_signals") else [],
        "confidence": latest.get("confidence"),
        "required_review_action": latest.get("required_review_action", REQUIRED_REVIEW_ACTION["DATA_INSUFFICIENT"]),
        "missing_signals_are_neutral": True,
        "state_override_allowed": bool(getattr(args, "allow_state_override", False)),
        "market_timing_claim_allowed": False,
        "research_only": True,
        "production_activation_allowed": False,
        "policy_hook_allowed": False,
        "live_trading_allowed": False,
        "states_supported": SUPPORTED_STATES,
    }
    write_json(output_dir / "summary.json", payload)
    lines = [
        "# Regime Nowcast Dial",
        "",
        f"- status: `{payload['status']}`",
        f"- current state: `{payload['current_state']}`",
        f"- bear warning score: `{payload['bear_warning_score']}`",
        f"- signal coverage: `{payload['signal_coverage']}`",
        f"- confidence: `{payload['confidence']}`",
        f"- required review action: `{payload['required_review_action']}`",
        "- market-timing claim allowed: `false`",
        "- policy hook allowed: `false`",
        "- live trading allowed: `false`",
        "",
    ]
    if payload["triggered_signals"]:
        lines.extend(["Triggered signals:", ""])
        lines.extend([f"- `{signal}`" for signal in payload["triggered_signals"]])
        lines.append("")
    if payload["missing_signals"]:
        lines.extend(["Missing neutral signals:", ""])
        lines.extend([f"- `{signal}`" for signal in payload["missing_signals"]])
        lines.append("")
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signal-panel", default="")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--allow-state-override",
        action="store_true",
        help="Allow explicit state_override/regime_state/current_state columns to override computed score state. Off by default.",
    )
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

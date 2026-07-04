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

import numpy as np
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

CRITICAL_GROUPS: dict[str, list[str]] = {
    "trend": ["spy_below_200dma", "qqq_below_200dma", "qqq_spy_rs_negative_1m_3m"],
    "volatility_stress": ["vix_spike_or_above_25", "rate_volatility_stress"],
    "credit_liquidity": [
        "hy_oas_widening_threshold",
        "yield_curve_inversion_or_steepening_warning",
        "dxy_liquidity_financial_conditions_stress",
    ],
    "breadth": ["universe_above_200dma_below_40pct", "new_high_new_low_breadth"],
    "earnings_guidance": ["eps_revision_breadth_negative", "positive_guidance_ratio_deteriorating"],
    "ai_bucket_rs": ["ai_capex_bucket_rs_breakdown"],
}

SERVICE_REQUIRED_GROUPS = ["trend", "volatility_stress", "breadth"]

AI_CAPEX_RS_TICKERS = [
    "AMD",
    "AMAT",
    "AVGO",
    "BE",
    "CIEN",
    "GEV",
    "GLW",
    "KLAC",
    "LITE",
    "LRCX",
    "MU",
    "NVDA",
    "PWR",
    "SNDK",
    "TLN",
    "UMC",
    "VRT",
    "WDC",
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


def _read_cached_price_file(path: Path, as_of_date: str) -> pd.DataFrame:
    try:
        px = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()
    if px.empty:
        return pd.DataFrame()
    px = px.copy()
    px.index = pd.to_datetime(px.index, errors="coerce").tz_localize(None)
    px = px[px.index.notna()].sort_index()
    if as_of_date:
        px = px[px.index <= pd.Timestamp(as_of_date)]
    if isinstance(px.columns, pd.MultiIndex):
        px.columns = px.columns.get_level_values(0)
    close_col = "Adj Close" if "Adj Close" in px.columns else "Close"
    if close_col not in px.columns:
        return pd.DataFrame()
    out = pd.DataFrame(index=px.index)
    out["close"] = pd.to_numeric(px[close_col], errors="coerce")
    return out.dropna(subset=["close"])


def _read_macro_series(macro_cache: Path, name: str, series_id: str) -> pd.Series:
    if not macro_cache or not macro_cache.exists():
        return pd.Series(dtype=float)
    key = str(name).strip().lower()
    sid = str(series_id).strip().upper()
    candidates = [
        macro_cache / f"fred_{key}_{sid}.parquet",
        macro_cache / f"fred_{key}_{sid}.csv",
        macro_cache / f"fred_{sid.lower()}_{sid}.parquet",
        macro_cache / f"fred_{sid.lower()}_{sid}.csv",
    ]
    frame = pd.DataFrame()
    for path in candidates:
        if not path.exists():
            continue
        try:
            frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
        except Exception:
            frame = pd.DataFrame()
        if not frame.empty:
            break
    if frame.empty:
        return pd.Series(dtype=float)
    frame = frame.copy()
    if "date" in frame.columns:
        idx = pd.to_datetime(frame["date"], errors="coerce")
        value_col = "value" if "value" in frame.columns else next((col for col in frame.columns if col != "date"), "")
    else:
        idx = pd.to_datetime(frame.index, errors="coerce")
        value_col = "value" if "value" in frame.columns else (frame.columns[0] if len(frame.columns) else "")
    if not value_col:
        return pd.Series(dtype=float)
    values = pd.to_numeric(frame[value_col].replace(".", pd.NA), errors="coerce")
    series = pd.Series(values.to_numpy(), index=idx).dropna()
    series = series[series.index.notna()].sort_index()
    return series[~series.index.duplicated(keep="last")]


def _macro_until(series: pd.Series, as_of_date: str) -> pd.Series:
    if series.empty:
        return series
    out = series.sort_index()
    if as_of_date:
        out = out[out.index <= pd.Timestamp(as_of_date)]
    return out.dropna()


def _read_table(path: Path) -> pd.DataFrame:
    if not path or not path.exists():
        return pd.DataFrame()
    try:
        if path.suffix.lower() == ".parquet":
            return pd.read_parquet(path)
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


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


def _spy_realized_vol_warning(price_cache: Path, as_of_date: str) -> dict[str, Any] | None:
    spy = _series_until(price_cache, "SPY", as_of_date)
    if len(spy) < 64:
        return None
    returns = spy["close"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < 63:
        return None
    vol20 = float(returns.tail(20).std(ddof=0) * np.sqrt(252.0))
    vol63 = float(returns.tail(63).std(ddof=0) * np.sqrt(252.0))
    vol_ratio = vol20 / vol63 if vol63 > 1e-12 else 0.0
    triggered = vol20 >= 0.25 or vol_ratio >= 1.5
    return {
        "date": pd.Timestamp(spy.index[-1]).date().isoformat(),
        "signal_name": "vix_spike_or_above_25",
        "value": vol20,
        "covered": True,
        "warning_triggered": triggered,
        "risk_score": 1.0 if triggered else 0.0,
        "source": "spy_realized_vol_proxy",
        "realized_vol_20d": vol20,
        "realized_vol_63d": vol63,
        "realized_vol_20d_to_63d": vol_ratio,
    }


def _cached_universe_breadth_warning(price_cache: Path, as_of_date: str) -> dict[str, Any] | None:
    if not price_cache.exists():
        return None
    as_of_ts = pd.Timestamp(as_of_date)
    total = 0
    above_200 = 0
    latest_dates: list[pd.Timestamp] = []
    for path in price_cache.glob("*.parquet"):
        px = _read_cached_price_file(path, as_of_date)
        if len(px) < 200:
            continue
        latest = pd.Timestamp(px.index[-1])
        if latest < as_of_ts - pd.Timedelta(days=7):
            continue
        close = safe_float(px["close"].iloc[-1])
        ma200 = safe_float(px["close"].tail(200).mean())
        if close <= 0 or ma200 <= 0:
            continue
        total += 1
        above_200 += int(close >= ma200)
        latest_dates.append(latest)
    if total < 30:
        return None
    pct_above = above_200 / total
    return {
        "date": as_of_date,
        "signal_name": "universe_above_200dma_below_40pct",
        "value": pct_above,
        "covered": True,
        "warning_triggered": pct_above < 0.40,
        "risk_score": 1.0 if pct_above < 0.40 else 0.0,
        "source": "price_cache_all_cached_tickers",
        "source_scope": "price_cache_files_without_ticker_mapping",
        "breadth_ticker_count": total,
        "breadth_above_200dma_count": above_200,
        "breadth_latest_date_min": min(latest_dates).date().isoformat() if latest_dates else "",
        "breadth_latest_date_max": max(latest_dates).date().isoformat() if latest_dates else "",
    }


def _ai_capex_bucket_rs_warning(price_cache: Path, as_of_date: str) -> dict[str, Any] | None:
    qqq = _series_until(price_cache, "QQQ", as_of_date)
    if len(qqq) < 64:
        return None
    qqq_1m = _return_over(qqq, 21)
    qqq_3m = _return_over(qqq, 63)
    if qqq_1m is None or qqq_3m is None:
        return None
    basket_1m: list[float] = []
    basket_3m: list[float] = []
    available: list[str] = []
    for ticker in AI_CAPEX_RS_TICKERS:
        series = _series_until(price_cache, ticker, as_of_date)
        if len(series) < 64:
            continue
        ret_1m = _return_over(series, 21)
        ret_3m = _return_over(series, 63)
        if ret_1m is None or ret_3m is None:
            continue
        basket_1m.append(float(ret_1m))
        basket_3m.append(float(ret_3m))
        available.append(ticker)
    if len(available) < 3:
        return None
    rs_1m = float(np.mean(basket_1m)) - float(qqq_1m)
    rs_3m = float(np.mean(basket_3m)) - float(qqq_3m)
    triggered = rs_1m < 0.0 and rs_3m < 0.0
    return {
        "date": pd.Timestamp(qqq.index[-1]).date().isoformat(),
        "signal_name": "ai_capex_bucket_rs_breakdown",
        "value": min(rs_1m, rs_3m),
        "covered": True,
        "warning_triggered": triggered,
        "risk_score": 1.0 if triggered else 0.0,
        "source": "price_cache_ai_capex_basket_vs_qqq",
        "ai_capex_available_ticker_count": len(available),
        "ai_capex_available_tickers": ",".join(available),
        "ai_capex_rs_1m": rs_1m,
        "ai_capex_rs_3m": rs_3m,
    }


def macro_cache_warning_rows(macro_cache: Path, as_of_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    hy_oas = _macro_until(_read_macro_series(macro_cache, "hy_oas", "BAMLH0A0HYM2"), as_of_date)
    if len(hy_oas) >= 22:
        latest = safe_float(hy_oas.iloc[-1])
        change_21d = latest - safe_float(hy_oas.iloc[-22])
        triggered = latest >= 5.0 or change_21d >= 0.75
        rows.append(
            {
                "date": as_of_date,
                "signal_name": "hy_oas_widening_threshold",
                "value": latest,
                "covered": True,
                "warning_triggered": triggered,
                "risk_score": 1.0 if triggered else 0.0,
                "source": "macro_cache_fred_hy_oas",
                "source_observation_date": pd.Timestamp(hy_oas.index[-1]).date().isoformat(),
                "hy_oas_level": latest,
                "hy_oas_change_21d": change_21d,
            }
        )

    dgs10 = _macro_until(_read_macro_series(macro_cache, "dgs10", "DGS10"), as_of_date)
    dgs3mo = _macro_until(_read_macro_series(macro_cache, "dgs3mo", "DGS3MO"), as_of_date)
    if not dgs10.empty and not dgs3mo.empty:
        aligned = pd.concat([dgs10.rename("dgs10"), dgs3mo.rename("dgs3mo")], axis=1).sort_index().ffill().dropna()
        if len(aligned) >= 22:
            spread = safe_float(aligned["dgs10"].iloc[-1]) - safe_float(aligned["dgs3mo"].iloc[-1])
            spread_21d_ago = safe_float(aligned["dgs10"].iloc[-22]) - safe_float(aligned["dgs3mo"].iloc[-22])
            steepening_from_inversion = spread_21d_ago < 0.0 and spread - spread_21d_ago >= 0.50
            triggered = spread < 0.0 or steepening_from_inversion
            rows.append(
                {
                    "date": as_of_date,
                    "signal_name": "yield_curve_inversion_or_steepening_warning",
                    "value": spread,
                    "covered": True,
                    "warning_triggered": triggered,
                    "risk_score": 1.0 if triggered else 0.0,
                    "source": "macro_cache_fred_dgs10_dgs3mo",
                    "source_observation_date": pd.Timestamp(aligned.index[-1]).date().isoformat(),
                    "yield_curve_10y_3m_spread": spread,
                    "yield_curve_10y_3m_spread_change_21d": spread - spread_21d_ago,
                }
            )

    sahm = _macro_until(_read_macro_series(macro_cache, "sahm", "SAHMREALTIME"), as_of_date)
    if not sahm.empty:
        latest = safe_float(sahm.iloc[-1])
        rows.append(
            {
                "date": as_of_date,
                "signal_name": "sahm_unemployment_momentum_warning",
                "value": latest,
                "covered": True,
                "warning_triggered": latest >= 0.50,
                "risk_score": 1.0 if latest >= 0.50 else 0.0,
                "source": "macro_cache_fred_sahm",
                "source_observation_date": pd.Timestamp(sahm.index[-1]).date().isoformat(),
                "sahm_realtime": latest,
            }
        )
    else:
        unrate = _macro_until(_read_macro_series(macro_cache, "unrate", "UNRATE"), as_of_date)
        if len(unrate) >= 4:
            latest = safe_float(unrate.iloc[-1])
            change_3m = latest - safe_float(unrate.iloc[-4])
            triggered = change_3m >= 0.30
            rows.append(
                {
                    "date": as_of_date,
                    "signal_name": "sahm_unemployment_momentum_warning",
                    "value": change_3m,
                    "covered": True,
                    "warning_triggered": triggered,
                    "risk_score": 1.0 if triggered else 0.0,
                    "source": "macro_cache_fred_unrate_proxy",
                    "source_observation_date": pd.Timestamp(unrate.index[-1]).date().isoformat(),
                    "unrate_level": latest,
                    "unrate_change_3m": change_3m,
                }
            )
    return rows


def earnings_guidance_warning_rows(earnings_signals: Path, as_of_date: str) -> list[dict[str, Any]]:
    d = _read_table(earnings_signals)
    if d.empty or "available_from" not in d.columns:
        return []
    d = d.copy()
    d["available_from"] = pd.to_datetime(d["available_from"], errors="coerce").dt.normalize()
    as_of_ts = pd.Timestamp(as_of_date).normalize()
    d = d[d["available_from"].notna() & (d["available_from"] <= as_of_ts)].copy()
    if d.empty:
        return []
    if "ticker" in d.columns:
        d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
        d = d[d["ticker"].ne("")]
        d = d.sort_values(["ticker", "available_from"]).drop_duplicates("ticker", keep="last")
    else:
        d = d.sort_values("available_from")
    row_count = int(len(d))
    if row_count < 5:
        return []
    eps_cols = [col for col in ["eps_revision_13w", "revenue_revision_13w"] if col in d.columns]
    if not eps_cols and "sector_eps_revision_breadth" not in d.columns and "sector_positive_guidance_ratio" not in d.columns:
        return []
    eps_positive_mask = pd.Series(False, index=d.index)
    for col in eps_cols:
        eps_positive_mask = eps_positive_mask | (pd.to_numeric(d[col], errors="coerce").fillna(0.0) > 0.0)
    if "sector_eps_revision_breadth" in d.columns:
        sector_breadth = float(pd.to_numeric(d["sector_eps_revision_breadth"], errors="coerce").dropna().mean())
        eps_breadth = max(float(eps_positive_mask.mean()), sector_breadth)
    else:
        eps_breadth = float(eps_positive_mask.mean())
    positive_guidance_ratio = (
        float((pd.to_numeric(d["positive_guidance_flag"], errors="coerce").fillna(0.0) > 0.0).mean())
        if "positive_guidance_flag" in d.columns
        else 0.0
    )
    negative_guidance_ratio = (
        float((pd.to_numeric(d["negative_guidance_flag"], errors="coerce").fillna(0.0) > 0.0).mean())
        if "negative_guidance_flag" in d.columns
        else 0.0
    )
    if "sector_positive_guidance_ratio" in d.columns:
        sector_guidance = float(pd.to_numeric(d["sector_positive_guidance_ratio"], errors="coerce").dropna().mean())
        positive_guidance_ratio = max(positive_guidance_ratio, sector_guidance)
    latest_obs = d["available_from"].max().date().isoformat()
    return [
        {
            "date": as_of_date,
            "signal_name": "eps_revision_breadth_negative",
            "value": eps_breadth,
            "covered": True,
            "warning_triggered": eps_breadth < 0.40,
            "risk_score": 1.0 if eps_breadth < 0.40 else 0.0,
            "source": "earnings_revision_signals",
            "source_observation_date": latest_obs,
            "earnings_signal_row_count": row_count,
            "eps_revision_positive_ratio": eps_breadth,
        },
        {
            "date": as_of_date,
            "signal_name": "positive_guidance_ratio_deteriorating",
            "value": positive_guidance_ratio - negative_guidance_ratio,
            "covered": True,
            "warning_triggered": positive_guidance_ratio < negative_guidance_ratio,
            "risk_score": 1.0 if positive_guidance_ratio < negative_guidance_ratio else 0.0,
            "source": "earnings_revision_signals",
            "source_observation_date": latest_obs,
            "earnings_signal_row_count": row_count,
            "positive_guidance_ratio": positive_guidance_ratio,
            "negative_guidance_ratio": negative_guidance_ratio,
        },
    ]


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

    vol_row = _spy_realized_vol_warning(price_cache, as_of_date)
    if vol_row is not None:
        rows.append(vol_row)

    breadth_row = _cached_universe_breadth_warning(price_cache, as_of_date)
    if breadth_row is not None:
        rows.append(breadth_row)

    ai_rs_row = _ai_capex_bucket_rs_warning(price_cache, as_of_date)
    if ai_rs_row is not None:
        rows.append(ai_rs_row)
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


def load_signal_panel(
    signal_panel: Path,
    price_cache: Path,
    macro_cache: Path,
    earnings_signals: Path,
    as_of_date: str,
) -> pd.DataFrame:
    panel = read_csv(signal_panel) if signal_panel else pd.DataFrame()
    if panel.empty:
        rows = price_cache_warning_rows(price_cache, as_of_date)
        rows.extend(macro_cache_warning_rows(macro_cache, as_of_date))
        rows.extend(earnings_guidance_warning_rows(earnings_signals, as_of_date))
        panel = pd.DataFrame(rows)
    else:
        extra_rows: list[dict[str, Any]] = []
        if macro_cache:
            extra_rows.extend(macro_cache_warning_rows(macro_cache, as_of_date))
        if earnings_signals:
            extra_rows.extend(earnings_guidance_warning_rows(earnings_signals, as_of_date))
        if extra_rows:
            panel = pd.concat([panel, pd.DataFrame(extra_rows)], ignore_index=True, sort=False)
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


def critical_group_coverage(covered_names: set[str]) -> tuple[dict[str, bool], list[str]]:
    coverage = {
        group: any(signal in covered_names for signal in signals)
        for group, signals in CRITICAL_GROUPS.items()
    }
    missing = sorted([group for group, covered in coverage.items() if not covered])
    return coverage, missing


def data_insufficient_reason(covered_names: set[str], coverage_mode: str) -> str:
    group_coverage, missing_groups = critical_group_coverage(covered_names)
    covered_count = len(covered_names)
    covered_group_count = sum(1 for covered in group_coverage.values() if covered)
    mode = str(coverage_mode or "internal").strip().lower()
    if covered_count < 6:
        return "covered_signals_lt_6"
    if mode in {"service", "public"}:
        if covered_count < 8:
            return "covered_signals_lt_8_for_service"
        if covered_group_count < 4:
            return "critical_group_coverage_lt_4"
        missing_required = [group for group in SERVICE_REQUIRED_GROUPS if group in missing_groups]
        if missing_required:
            return "missing_required_critical_group:" + ",".join(missing_required)
    return ""


def state_override(group: pd.DataFrame) -> str:
    for col in ["state_override", "regime_state", "current_state"]:
        if col not in group.columns:
            continue
        values = [str(value).strip().upper() for value in group[col].dropna().tolist()]
        for value in values:
            if value in SUPPORTED_STATES and value != "DATA_INSUFFICIENT":
                return value
    return ""


def build_state_history(
    panel: pd.DataFrame,
    allow_state_override: bool = False,
    coverage_mode: str = "internal",
) -> pd.DataFrame:
    state_rows: list[dict[str, Any]] = []
    for dt, group in panel.groupby("date", dropna=False):
        warning_group = group[group["signal_name"].isin(WARNING_SIGNALS)]
        covered = warning_group[warning_group["covered"]]
        covered_names = sorted(set(covered["signal_name"].astype(str)))
        covered_name_set = set(covered_names)
        all_covered_names = set(group[group["covered"]]["signal_name"].astype(str))
        triggered = covered[covered["warning_triggered"]]
        triggered_names = sorted(set(triggered["signal_name"].astype(str)))
        missing_names = sorted(set(WARNING_SIGNALS) - set(covered_names))
        score = min(12, len(triggered_names))
        confidence = len(covered_names) / len(WARNING_SIGNALS)
        group_coverage, missing_critical_groups = critical_group_coverage(all_covered_names)
        insufficient_reason = data_insufficient_reason(covered_name_set, coverage_mode)
        if not insufficient_reason and str(coverage_mode or "internal").strip().lower() in {"service", "public"}:
            covered_group_count = sum(1 for covered_group in group_coverage.values() if covered_group)
            missing_required = [group_name for group_name in SERVICE_REQUIRED_GROUPS if group_name in missing_critical_groups]
            if covered_group_count < 4:
                insufficient_reason = "critical_group_coverage_lt_4"
            elif missing_required:
                insufficient_reason = "missing_required_critical_group:" + ",".join(missing_required)
        state = "DATA_INSUFFICIENT" if insufficient_reason else state_from_warning_score(score, len(covered_names))
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
                "coverage_mode": str(coverage_mode or "internal").strip().lower(),
                "critical_group_coverage_count": int(sum(1 for covered in group_coverage.values() if covered)),
                "critical_group_expected_count": int(len(CRITICAL_GROUPS)),
                "critical_group_coverage": json.dumps(group_coverage, sort_keys=True),
                "missing_critical_groups": ";".join(missing_critical_groups),
                "data_insufficient_reason": insufficient_reason,
                "triggered_signals": ";".join(triggered_names),
                "missing_signals": ";".join(missing_names),
                "required_review_action": REQUIRED_REVIEW_ACTION[state],
                "state_override_allowed": bool(allow_state_override),
                "state_override_applied": bool(override),
                "state_computed_from_data": True,
                "production_activation_allowed": False,
                "policy_hook_allowed": False,
            }
        )
    return pd.DataFrame(state_rows).sort_values("date")


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    as_of = args.as_of_date or pd.Timestamp.utcnow().date().isoformat()
    macro_cache_arg = str(getattr(args, "macro_cache", "") or "").strip()
    earnings_signals_arg = str(getattr(args, "earnings_signals", "") or "").strip()
    panel = load_signal_panel(
        repo_path(args.signal_panel) if args.signal_panel else Path(),
        repo_path(args.price_cache),
        repo_path(macro_cache_arg) if macro_cache_arg else Path(),
        repo_path(earnings_signals_arg) if earnings_signals_arg else Path(),
        as_of,
    )
    state = build_state_history(
        panel,
        allow_state_override=bool(getattr(args, "allow_state_override", False)),
        coverage_mode=str(getattr(args, "coverage_mode", "internal") or "internal"),
    )
    panel.to_csv(output_dir / "signal_panel.csv", index=False)
    panel.to_csv(output_dir / "indicator_rows.csv", index=False)
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
        "coverage_mode": latest.get("coverage_mode", getattr(args, "coverage_mode", "internal")),
        "critical_group_coverage_count": latest.get("critical_group_coverage_count"),
        "critical_group_expected_count": latest.get("critical_group_expected_count"),
        "critical_group_coverage": json.loads(latest.get("critical_group_coverage", "{}"))
        if latest.get("critical_group_coverage")
        else {},
        "missing_critical_groups": str(latest.get("missing_critical_groups", "")).split(";")
        if latest.get("missing_critical_groups")
        else [],
        "data_insufficient_reason": latest.get("data_insufficient_reason", ""),
        "covered_signal_count": latest.get("covered_signal_count"),
        "expected_signal_count": latest.get("expected_signal_count"),
        "triggered_signals": str(latest.get("triggered_signals", "")).split(";") if latest.get("triggered_signals") else [],
        "missing_signals": str(latest.get("missing_signals", "")).split(";") if latest.get("missing_signals") else [],
        "confidence": latest.get("confidence"),
        "required_review_action": latest.get("required_review_action", REQUIRED_REVIEW_ACTION["DATA_INSUFFICIENT"]),
        "missing_signals_are_neutral": True,
        "state_computed_from_data": True,
        "state_override_allowed": bool(getattr(args, "allow_state_override", False)),
        "state_override_used": bool(latest.get("state_override_applied", False)),
        "allow_state_override": bool(getattr(args, "allow_state_override", False)),
        "market_timing_claim_allowed": False,
        "public_display_allowed": False,
        "review_only": True,
        "backtest_metrics_are_simulated": True,
        "current_holdings_are_not_forward_promise": True,
        "historical_metrics_forward_promise_allowed": False,
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
        f"- critical group coverage: `{payload['critical_group_coverage_count']}/{payload['critical_group_expected_count']}`",
        f"- confidence: `{payload['confidence']}`",
        f"- data insufficient reason: `{payload['data_insufficient_reason']}`",
        f"- required review action: `{payload['required_review_action']}`",
        "- market-timing claim allowed: `false`",
        "- public display allowed: `false`",
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
    parser.add_argument("--macro-cache", default="cache_macro")
    parser.add_argument("--earnings-signals", default="data_pit/events/earnings_revision_signals.parquet")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--coverage-mode", choices=["internal", "service", "public"], default="internal")
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

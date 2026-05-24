"""Research-only long crisis and liquidity learning helpers.

This module is intentionally side-effect free. It builds PIT-safe feature
panels, labels future drawdowns for research, scores liquidity confirmation,
and evaluates simple threshold grids for the Phase G crisis governor.

Nothing here changes production scores or live target books.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd


SPLIT_BOUNDARIES = {
    "train": ("1990-01-01", "2002-12-31"),
    "validation": ("2003-01-01", "2009-12-31"),
    "test": ("2010-01-01", "2019-12-31"),
    "holdout": ("2020-01-01", "2099-12-31"),
}


@dataclass(frozen=True)
class CashGateDecision:
    allowed: bool
    effective_crisis_score: float
    reason: str
    liquidity_confirmation_score: float
    market_trend_damage_score: float
    credit_stress_score: float
    shakeout_guard_score: float


def _as_series(value: Any) -> pd.Series:
    if isinstance(value, pd.Series):
        out = value.copy()
    elif isinstance(value, pd.DataFrame):
        if value.empty:
            return pd.Series(dtype=float)
        out = value.iloc[:, 0].copy()
    else:
        return pd.Series(dtype=float)
    out.index = pd.to_datetime(out.index, errors="coerce")
    out = out[~out.index.isna()]
    out.index = pd.DatetimeIndex(out.index).tz_localize(None).normalize()
    out = pd.to_numeric(out, errors="coerce").dropna().sort_index()
    return out[~out.index.duplicated(keep="last")]


def clip01(value: pd.Series | float) -> pd.Series | float:
    if isinstance(value, pd.Series):
        return value.clip(lower=0.0, upper=1.0)
    return float(max(0.0, min(1.0, float(value))))


def rolling_zscore(series: pd.Series, window: int = 252) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    mean = s.rolling(window, min_periods=max(20, window // 5)).mean()
    std = s.rolling(window, min_periods=max(20, window // 5)).std(ddof=0)
    return (s - mean) / std.replace(0, np.nan)


def positive_z(series: pd.Series, window: int = 252, scale: float = 2.0) -> pd.Series:
    return clip01(rolling_zscore(series, window=window).fillna(0.0) / float(scale))


def negative_z(series: pd.Series, window: int = 252, scale: float = 2.0) -> pd.Series:
    return clip01(-rolling_zscore(series, window=window).fillna(0.0) / float(scale))


def macro_series_to_billions(name: str, series: pd.Series) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce").astype(float)
    if out.empty:
        return out
    # WALCL and WDTGAL are stored by FRED in millions; RRPTSYD is billions.
    if name in {"fed_assets", "tga"}:
        out = out / 1000.0
    return out


def monthly_release_lag(series: pd.Series, months: int = 1) -> pd.Series:
    """Apply a conservative monthly release lag.

    The observation dated month M is not exposed to daily features until at
    least the next monthly row. This prevents same-month M2 leakage.
    """
    s = _as_series(series)
    if s.empty:
        return s
    monthly = s.resample("MS").last().sort_index()
    return monthly.shift(int(months))


def _asof_to_index(series: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    s = _as_series(series)
    if s.empty:
        return pd.Series(np.nan, index=idx, dtype=float)
    return s.reindex(s.index.union(idx)).sort_index().ffill().reindex(idx)


def forward_drawdown(close: pd.Series, horizon: int) -> pd.Series:
    """Worst forward drawdown from today's close over the next horizon days."""
    c = pd.to_numeric(close, errors="coerce").astype(float)
    future_min = c.iloc[::-1].rolling(horizon + 1, min_periods=1).min().iloc[::-1]
    return (future_min / c.replace(0, np.nan)) - 1.0


def forward_return(close: pd.Series, horizon: int) -> pd.Series:
    c = pd.to_numeric(close, errors="coerce").astype(float)
    return c.shift(-horizon) / c.replace(0, np.nan) - 1.0


def split_name_for_date(date: pd.Timestamp) -> str:
    dt = pd.Timestamp(date)
    for name, (lo, hi) in SPLIT_BOUNDARIES.items():
        if pd.Timestamp(lo) <= dt <= pd.Timestamp(hi):
            return name
    return "unknown"


def compute_liquidity_confirmation_score(features: pd.DataFrame) -> pd.Series:
    idx = features.index
    parts: list[pd.Series] = []

    if "m2_6m_change_lag1m" in features:
        parts.append(clip01((-features["m2_6m_change_lag1m"].fillna(0.0)) / 0.04))
    if "fed_assets_13w_change_pct" in features:
        parts.append(clip01((-features["fed_assets_13w_change_pct"].fillna(0.0)) / 0.06))
    if "net_liquidity_13w_change_pct" in features:
        parts.append(clip01((-features["net_liquidity_13w_change_pct"].fillna(0.0)) / 0.08))
    if "reverse_repo_13w_change_pct" in features:
        # RRP rebuild drains liquidity; RRP drain is not a risk signal.
        parts.append(clip01(features["reverse_repo_13w_change_pct"].fillna(0.0) / 0.50))
    if "tga_13w_change_pct" in features:
        # TGA rebuild drains reserves from the private system.
        parts.append(clip01(features["tga_13w_change_pct"].fillna(0.0) / 0.50))
    if "dxy_ret_20d" in features:
        parts.append(positive_z(features["dxy_ret_20d"], window=252, scale=2.0))
    if "hy_oas_zscore_252d" in features:
        parts.append(clip01(features["hy_oas_zscore_252d"].fillna(0.0) / 2.5))

    if not parts:
        return pd.Series(0.0, index=idx)
    return pd.concat(parts, axis=1).mean(axis=1).fillna(0.0).clip(0.0, 1.0)


def build_long_crisis_features(
    market_close: pd.Series,
    macro_series: Mapping[str, pd.Series],
    *,
    qqq_close: pd.Series | None = None,
    start: str = "1990-01-01",
    end: str | None = None,
    m2_lag_months: int = 1,
) -> pd.DataFrame:
    """Build daily long-crisis features plus research labels.

    `market_close` should be a broad US equity proxy: SP500, ^GSPC, or SPY.
    Labels are included in this research table, but downstream live tools must
    select only feature columns and must not consume any `future_*` fields.
    """
    market = _as_series(market_close)
    if market.empty:
        return pd.DataFrame()
    qqq = _as_series(qqq_close) if qqq_close is not None else pd.Series(dtype=float)

    min_date = max(pd.Timestamp(start), market.index.min())
    max_date = pd.Timestamp(end) if end else market.index.max()
    idx = pd.bdate_range(min_date, max_date)
    out = pd.DataFrame(index=idx)

    close = _asof_to_index(market, idx)
    out["market_close"] = close
    out["market_ma50"] = close.rolling(50).mean()
    out["market_ma200"] = close.rolling(200).mean()
    out["market_below_ma200"] = (close < out["market_ma200"]).astype(float)
    out["market_5d_dd"] = close / close.rolling(5).max() - 1.0
    out["market_20d_dd"] = close / close.rolling(20).max() - 1.0
    out["market_63d_dd"] = close / close.rolling(63).max() - 1.0
    out["market_ret_21d"] = close.pct_change(21)
    out["market_trend_damage_score"] = (
        0.35 * out["market_below_ma200"].fillna(0.0)
        + 0.40 * clip01((-out["market_63d_dd"].clip(upper=0).fillna(0.0)) / 0.20)
        + 0.25 * clip01((-out["market_20d_dd"].clip(upper=0).fillna(0.0)) / 0.12)
    ).clip(0.0, 1.0)

    if not qqq.empty:
        q = _asof_to_index(qqq, idx)
        out["qqq_close"] = q
        out["qqq_ma200"] = q.rolling(200).mean()
        out["qqq_below_ma200"] = (q < out["qqq_ma200"]).astype(float)
        out["qqq_rel_market_21d"] = q.pct_change(21) - close.pct_change(21)

    vix = _asof_to_index(macro_series.get("vix", pd.Series(dtype=float)), idx)
    if vix.notna().any():
        out["vix_level"] = vix
        out["vix_zscore_252d"] = rolling_zscore(vix, 252)
        out["vix_spike_5d"] = vix.diff(5)
        out["volatility_stress_score"] = (
            0.70 * clip01(out["vix_zscore_252d"].fillna(0.0) / 2.5)
            + 0.30 * positive_z(out["vix_spike_5d"], window=252, scale=2.0)
        ).clip(0.0, 1.0)
    else:
        out["volatility_stress_score"] = 0.0

    hy = _asof_to_index(macro_series.get("hy_oas", pd.Series(dtype=float)), idx)
    if hy.notna().any():
        out["hy_oas"] = hy
        out["hy_oas_zscore_252d"] = rolling_zscore(hy, 252)
        out["hy_oas_20d_change"] = hy.diff(20)
        out["credit_stress_score"] = (
            0.70 * clip01(out["hy_oas_zscore_252d"].fillna(0.0) / 2.5)
            + 0.30 * positive_z(out["hy_oas_20d_change"], window=252, scale=2.0)
        ).clip(0.0, 1.0)
    else:
        out["credit_stress_score"] = 0.0

    dgs10 = _asof_to_index(macro_series.get("dgs10", pd.Series(dtype=float)), idx)
    if dgs10.notna().any():
        out["ten_year_yield"] = dgs10
        out["ten_year_20d_change_bps"] = dgs10.diff(20) * 100.0
        out["rate_shock_score"] = clip01(out["ten_year_20d_change_bps"].abs().fillna(0.0) / 75.0)
    else:
        out["rate_shock_score"] = 0.0

    dxy = _asof_to_index(macro_series.get("dxy", pd.Series(dtype=float)), idx)
    if dxy.notna().any():
        out["dxy_level"] = dxy
        out["dxy_ret_20d"] = dxy.pct_change(20)

    m2 = monthly_release_lag(macro_series.get("m2", pd.Series(dtype=float)), months=m2_lag_months)
    if not m2.empty:
        m2_daily = _asof_to_index(m2, idx)
        out["m2_level_lag1m"] = m2_daily
        out["m2_yoy_lag1m"] = m2_daily.pct_change(252)
        out["m2_6m_change_lag1m"] = m2_daily.pct_change(126)

    fed_assets = macro_series_to_billions("fed_assets", _as_series(macro_series.get("fed_assets", pd.Series(dtype=float))))
    reverse_repo = macro_series_to_billions("reverse_repo", _as_series(macro_series.get("reverse_repo", pd.Series(dtype=float))))
    tga = macro_series_to_billions("tga", _as_series(macro_series.get("tga", pd.Series(dtype=float))))
    fed_daily = _asof_to_index(fed_assets, idx)
    rrp_daily = _asof_to_index(reverse_repo, idx)
    tga_daily = _asof_to_index(tga, idx)
    if fed_daily.notna().any():
        out["fed_assets_bil"] = fed_daily
        out["fed_assets_13w_change_pct"] = fed_daily.pct_change(65)
    if rrp_daily.notna().any():
        out["reverse_repo_bil"] = rrp_daily
        out["reverse_repo_13w_change_pct"] = rrp_daily.pct_change(65)
    if tga_daily.notna().any():
        out["tga_bil"] = tga_daily
        out["tga_13w_change_pct"] = tga_daily.pct_change(65)
    if fed_daily.notna().any():
        net = fed_daily - rrp_daily.fillna(0.0) - tga_daily.fillna(0.0)
        out["net_liquidity_bil"] = net
        out["net_liquidity_13w_change_pct"] = net.pct_change(65)

    out["liquidity_confirmation_score"] = compute_liquidity_confirmation_score(out)
    out["crisis_score"] = (
        0.30 * out["market_trend_damage_score"].fillna(0.0)
        + 0.20 * out["volatility_stress_score"].fillna(0.0)
        + 0.20 * out["credit_stress_score"].fillna(0.0)
        + 0.20 * out["liquidity_confirmation_score"].fillna(0.0)
        + 0.10 * out["rate_shock_score"].fillna(0.0)
    ).clip(0.0, 1.0)
    out["cash_raise_confirmation_score"] = (
        0.40 * out["liquidity_confirmation_score"].fillna(0.0)
        + 0.30 * out["market_trend_damage_score"].fillna(0.0)
        + 0.20 * out["credit_stress_score"].fillna(0.0)
        + 0.10 * out["volatility_stress_score"].fillna(0.0)
    ).clip(0.0, 1.0)

    out["future_21d_return"] = forward_return(close, 21)
    out["future_63d_return"] = forward_return(close, 63)
    out["future_126d_return"] = forward_return(close, 126)
    out["future_21d_drawdown"] = forward_drawdown(close, 21)
    out["future_63d_drawdown"] = forward_drawdown(close, 63)
    out["future_126d_drawdown"] = forward_drawdown(close, 126)
    out["future_63d_drawdown_le_15pct"] = (out["future_63d_drawdown"] <= -0.15).astype(int)
    out["future_126d_drawdown_le_20pct"] = (out["future_126d_drawdown"] <= -0.20).astype(int)
    out["false_alarm_no_drawdown_63d"] = (out["future_63d_drawdown"] > -0.05).astype(int)
    out["split"] = [split_name_for_date(x) for x in out.index]
    return out


def cash_raise_decision(
    feature_row: Mapping[str, Any] | pd.Series,
    crisis_score: float,
    *,
    mid_threshold: float = 0.50,
    liquidity_gate: float = 0.35,
    trend_gate: float = 0.35,
    credit_gate: float = 0.55,
    shakeout_gate: float = 0.60,
) -> CashGateDecision:
    """Gate cash raises so VIX-only or single-name shakeouts do not cut CAGR."""
    row = dict(feature_row)
    liq = float(row.get("liquidity_confirmation_score", 0.0) or 0.0)
    trend = float(row.get("market_trend_damage_score", 0.0) or 0.0)
    credit = float(row.get("credit_stress_score", 0.0) or 0.0)
    shakeout = float(row.get("shakeout_guard_score", 0.0) or 0.0)
    score = float(crisis_score or 0.0)
    if score < mid_threshold:
        return CashGateDecision(True, score, "below_cash_raise_zone", liq, trend, credit, shakeout)
    confirmed = (liq >= liquidity_gate and trend >= trend_gate) or credit >= credit_gate or trend >= 0.70
    if shakeout >= shakeout_gate and not confirmed:
        effective = min(score, max(0.0, mid_threshold - 0.01))
        return CashGateDecision(False, effective, "shakeout_guard_blocks_cash_raise", liq, trend, credit, shakeout)
    if confirmed:
        return CashGateDecision(True, score, "systemic_confirmation_pass", liq, trend, credit, shakeout)
    effective = min(score, max(0.0, mid_threshold - 0.01))
    return CashGateDecision(False, effective, "blocked_no_liquidity_or_trend_confirmation", liq, trend, credit, shakeout)


def rank_auc(score: pd.Series, label: pd.Series) -> float:
    d = pd.DataFrame({"score": score, "label": label}).dropna()
    if d.empty or d["label"].nunique() < 2:
        return float("nan")
    ranks = d["score"].rank(method="average")
    pos = d["label"].astype(int).eq(1)
    n_pos = int(pos.sum())
    n_neg = int((~pos).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    rank_sum_pos = float(ranks[pos].sum())
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def evaluate_thresholds(
    features: pd.DataFrame,
    *,
    crisis_gate: float,
    liquidity_gate: float,
    trend_gate: float,
    split: str,
    drawdown_col: str = "future_63d_drawdown_le_15pct",
) -> dict[str, Any]:
    d = features.copy()
    if split:
        d = d[d.get("split", "").astype(str).eq(split)]
    if d.empty or drawdown_col not in d.columns:
        return {"status": "blocked", "split": split, "rows": 0}
    signal = (
        pd.to_numeric(d.get("crisis_score"), errors="coerce").fillna(0.0).ge(crisis_gate)
        & pd.to_numeric(d.get("liquidity_confirmation_score"), errors="coerce").fillna(0.0).ge(liquidity_gate)
        & pd.to_numeric(d.get("market_trend_damage_score"), errors="coerce").fillna(0.0).ge(trend_gate)
    )
    label = pd.to_numeric(d[drawdown_col], errors="coerce").fillna(0).astype(int).eq(1)
    false_alarm = pd.to_numeric(d.get("false_alarm_no_drawdown_63d"), errors="coerce").fillna(0).astype(int).eq(1)
    tp = int((signal & label).sum())
    fp = int((signal & ~label).sum())
    fn = int((~signal & label).sum())
    tn = int((~signal & ~label).sum())
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    signal_rate = float(signal.mean()) if len(signal) else 0.0
    false_positive_rate = fp / max(fp + tn, 1)
    whipsaw_rate = float((signal & false_alarm).sum() / max(signal.sum(), 1))
    score = recall + 0.35 * precision - 0.65 * false_positive_rate - 0.35 * signal_rate - 0.35 * whipsaw_rate
    return {
        "status": "ok",
        "split": split,
        "rows": int(len(d)),
        "crisis_gate": float(crisis_gate),
        "liquidity_gate": float(liquidity_gate),
        "trend_gate": float(trend_gate),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": float(precision),
        "recall": float(recall),
        "signal_rate": float(signal_rate),
        "false_positive_rate": float(false_positive_rate),
        "whipsaw_rate": float(whipsaw_rate),
        "score": float(score),
    }


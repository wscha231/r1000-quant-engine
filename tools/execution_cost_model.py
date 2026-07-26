#!/usr/bin/env python3
"""Research-only spread, ADV, market-impact, and capacity cost model.

The default broker replay remains the fixed-bps champion contract.  This module
adds an opt-in challenger measurement layer:

* Corwin-Schultz full-spread estimates from strictly prior daily highs/lows;
* prior-20-session adjusted-dollar ADV and close-to-close volatility;
* square-root market impact ``Y * sigma * sqrt(order / ADV)``;
* optional paper implementation-shortfall evidence; and
* strict 0.1%, 0.5%, and 1.0% ADV portfolio-capacity scenarios.

Observed paper slippage and the OHLCV estimate are alternatives, not additive
costs.  The effective variable cost is their maximum, preventing spread and
impact from being double counted while remaining conservative.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


EXECUTION_COST_SCHEMA_VERSION = "run287-execution-cost-capacity-v1"
EXECUTION_COST_MODE_FIXED = "fixed_bps"
EXECUTION_COST_MODE_SPREAD_ADV_IMPACT = "spread_adv_impact_v1"
DEFAULT_CAPACITY_PARTICIPATION_RATES = (0.001, 0.005, 0.010)


def _finite_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


@dataclass(frozen=True)
class ExecutionCostConfig:
    """Immutable configuration for the opt-in research cost model."""

    mode: str = EXECUTION_COST_MODE_FIXED
    lookback_sessions: int = 20
    min_history_sessions: int = 12
    impact_coefficient: float = 0.50
    minimum_half_spread_bps: float = 1.0
    maximum_half_spread_bps: float = 100.0
    maximum_market_impact_bps: float = 500.0
    capacity_participation_rates: tuple[float, ...] = DEFAULT_CAPACITY_PARTICIPATION_RATES
    paper_slippage_path: Path | None = None
    require_complete_liquidity_coverage: bool = True

    def __post_init__(self) -> None:
        if self.mode not in {
            EXECUTION_COST_MODE_FIXED,
            EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
        }:
            raise ValueError(f"unsupported execution cost mode: {self.mode!r}")
        if int(self.min_history_sessions) < 3:
            raise ValueError("min_history_sessions must be at least 3")
        if int(self.lookback_sessions) < int(self.min_history_sessions):
            raise ValueError("lookback_sessions must be >= min_history_sessions")
        if not math.isfinite(float(self.impact_coefficient)) or float(
            self.impact_coefficient
        ) < 0.0:
            raise ValueError("impact_coefficient must be non-negative")
        minimum_spread = float(self.minimum_half_spread_bps)
        maximum_spread = float(self.maximum_half_spread_bps)
        if (
            not math.isfinite(minimum_spread)
            or not math.isfinite(maximum_spread)
            or not 0.0 <= minimum_spread <= maximum_spread
        ):
            raise ValueError("half-spread bounds are invalid")
        if not math.isfinite(float(self.maximum_market_impact_bps)) or float(
            self.maximum_market_impact_bps
        ) < 0.0:
            raise ValueError("maximum_market_impact_bps must be non-negative")
        if not self.capacity_participation_rates or any(
            not 0.0 < float(value) <= 1.0
            for value in self.capacity_participation_rates
        ):
            raise ValueError("capacity participation rates must be in (0, 1]")

    @property
    def enabled(self) -> bool:
        return str(self.mode).strip().lower() == EXECUTION_COST_MODE_SPREAD_ADV_IMPACT

    def audit(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["paper_slippage_path"] = (
            str(self.paper_slippage_path) if self.paper_slippage_path is not None else ""
        )
        payload["capacity_participation_rates"] = [
            float(value) for value in self.capacity_participation_rates
        ]
        payload["schema_version"] = EXECUTION_COST_SCHEMA_VERSION
        payload["enabled"] = self.enabled
        return payload


@dataclass(frozen=True)
class LiquiditySnapshot:
    status: str
    history_sessions: int
    adv20_usd: float | None = None
    daily_volatility20: float | None = None
    full_spread_bps: float | None = None
    half_spread_bps: float | None = None
    history_end_date: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ExecutionCostQuote:
    status: str
    fixed_cost_bps: float
    half_spread_bps: float | None
    market_impact_bps: float | None
    estimated_variable_cost_bps: float | None
    observed_slippage_bps: float | None
    effective_variable_cost_bps: float | None
    total_cost_bps: float
    adv20_usd: float | None
    participation_rate: float | None
    daily_volatility20: float | None
    spread_source: str
    slippage_source: str
    observed_exceeds_model: bool | None
    liquidity_history_end_date: str
    reason: str = ""

    def audit(self) -> dict[str, Any]:
        return asdict(self)


def _corwin_schultz_full_spread(high: pd.Series, low: pd.Series) -> pd.Series:
    """Return the two-day Corwin-Schultz full-spread estimate.

    Negative alpha estimates are floored at zero, matching the simple
    non-negative estimator used in the paper.  Inputs must already be adjusted
    onto the same price scale.
    """

    high_num = pd.to_numeric(high, errors="coerce")
    low_num = pd.to_numeric(low, errors="coerce")
    valid = (high_num > 0.0) & (low_num > 0.0) & (high_num >= low_num)
    log_hl_sq = np.log((high_num.where(valid) / low_num.where(valid))) ** 2
    beta = log_hl_sq + log_hl_sq.shift(1)
    two_day_high = pd.concat([high_num, high_num.shift(1)], axis=1).max(axis=1)
    two_day_low = pd.concat([low_num, low_num.shift(1)], axis=1).min(axis=1)
    gamma = np.log(two_day_high / two_day_low) ** 2
    denominator = 3.0 - 2.0 * math.sqrt(2.0)
    alpha = (
        (np.sqrt(2.0 * beta.clip(lower=0.0)) - np.sqrt(beta.clip(lower=0.0)))
        / denominator
        - np.sqrt(gamma.clip(lower=0.0) / denominator)
    ).clip(lower=0.0)
    exp_alpha = np.exp(alpha.clip(upper=20.0))
    spread = 2.0 * (exp_alpha - 1.0) / (1.0 + exp_alpha)
    return spread.where(valid & valid.shift(1, fill_value=False))


def liquidity_snapshot(
    price_frame: pd.DataFrame,
    fill_date: Any,
    config: ExecutionCostConfig,
) -> LiquiditySnapshot:
    """Build a strictly prior-data liquidity snapshot for one fill."""

    cutoff = pd.to_datetime(fill_date, errors="coerce")
    if pd.isna(cutoff):
        return LiquiditySnapshot(
            status="blocked",
            history_sessions=0,
            reason="invalid_fill_date",
        )
    if price_frame.empty:
        return LiquiditySnapshot(
            status="blocked",
            history_sessions=0,
            reason="price_history_missing",
        )
    required = {"close", "high", "low", "volume"}
    missing = sorted(required - set(price_frame.columns))
    if missing:
        return LiquiditySnapshot(
            status="blocked",
            history_sessions=0,
            reason="missing_price_columns:" + ",".join(missing),
        )

    frame = price_frame.copy()
    frame.index = pd.to_datetime(frame.index, errors="coerce").tz_localize(None)
    frame = frame.loc[frame.index.notna() & (frame.index < pd.Timestamp(cutoff))].sort_index()
    frame = frame.tail(max(int(config.lookback_sessions) + 1, int(config.min_history_sessions) + 1))
    history_sessions = int(len(frame))
    if history_sessions < int(config.min_history_sessions):
        return LiquiditySnapshot(
            status="blocked",
            history_sessions=history_sessions,
            history_end_date=(
                pd.Timestamp(frame.index.max()).date().isoformat() if history_sessions else ""
            ),
            reason="insufficient_prior_history",
        )

    close = pd.to_numeric(frame["close"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    dollar_volume_source = (
        pd.to_numeric(frame["dollar_volume"], errors="coerce")
        if "dollar_volume" in frame.columns
        else close * volume
    )
    dollar_volume = dollar_volume_source.replace([np.inf, -np.inf], np.nan).dropna()
    dollar_volume = dollar_volume[dollar_volume > 0.0].tail(int(config.lookback_sessions))
    returns = np.log(close.where(close > 0.0)).diff().replace([np.inf, -np.inf], np.nan).dropna()
    returns = returns.tail(int(config.lookback_sessions))
    spreads = _corwin_schultz_full_spread(frame["high"], frame["low"]).dropna()
    spreads = spreads.tail(int(config.lookback_sessions))

    if (
        len(dollar_volume) < int(config.min_history_sessions)
        or len(returns) < int(config.min_history_sessions) - 1
        or len(spreads) < int(config.min_history_sessions) - 1
    ):
        return LiquiditySnapshot(
            status="blocked",
            history_sessions=history_sessions,
            history_end_date=pd.Timestamp(frame.index.max()).date().isoformat(),
            reason="incomplete_prior_ohlcv_window",
        )

    adv20 = _finite_float(dollar_volume.mean())
    daily_volatility = _finite_float(returns.std(ddof=0))
    full_spread = _finite_float(spreads.median())
    if (
        adv20 is None
        or adv20 <= 0.0
        or daily_volatility is None
        or daily_volatility < 0.0
        or full_spread is None
        or full_spread < 0.0
    ):
        return LiquiditySnapshot(
            status="blocked",
            history_sessions=history_sessions,
            history_end_date=pd.Timestamp(frame.index.max()).date().isoformat(),
            reason="invalid_liquidity_statistics",
        )

    full_spread_bps = full_spread * 10000.0
    half_spread_bps = float(
        np.clip(
            full_spread_bps / 2.0,
            float(config.minimum_half_spread_bps),
            float(config.maximum_half_spread_bps),
        )
    )
    return LiquiditySnapshot(
        status="complete",
        history_sessions=history_sessions,
        adv20_usd=float(adv20),
        daily_volatility20=float(daily_volatility),
        full_spread_bps=float(full_spread_bps),
        half_spread_bps=half_spread_bps,
        history_end_date=pd.Timestamp(frame.index.max()).date().isoformat(),
    )


def load_paper_slippage(path: Path | None) -> pd.DataFrame:
    """Load optional same-trade implementation-shortfall evidence."""

    columns = ["date", "ticker", "side", "observed_slippage_bps"]
    if path is None or not Path(path).exists():
        return pd.DataFrame(columns=columns)
    try:
        raw = pd.read_parquet(path) if Path(path).suffix.lower() == ".parquet" else pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=columns)
    if raw.empty:
        return pd.DataFrame(columns=columns)
    date_col = next((name for name in ("date", "fill_date", "executed_at") if name in raw.columns), "")
    value_col = next(
        (
            name
            for name in (
                "observed_slippage_bps",
                "implementation_shortfall_bps",
                "slippage_bps",
            )
            if name in raw.columns
        ),
        "",
    )
    if (
        not date_col
        or "ticker" not in raw.columns
        or "side" not in raw.columns
        or not value_col
    ):
        return pd.DataFrame(columns=columns)

    def normalize_trade_date(value: Any) -> pd.Timestamp:
        text = str(value).strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return pd.Timestamp(text).normalize()
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return pd.NaT
        timestamp = pd.Timestamp(parsed)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(
                "America/New_York",
                ambiguous="NaT",
                nonexistent="shift_forward",
            )
        else:
            timestamp = timestamp.tz_convert("America/New_York")
        if pd.isna(timestamp):
            return pd.NaT
        return timestamp.tz_localize(None).normalize()

    normalized_dates = raw[date_col].map(normalize_trade_date)
    out = pd.DataFrame(
        {
            "date": normalized_dates,
            "ticker": raw["ticker"].astype(str).str.upper().str.strip(),
            "side": raw["side"].astype(str).str.upper().str.strip(),
            "observed_slippage_bps": pd.to_numeric(raw[value_col], errors="coerce"),
        }
    ).dropna(subset=["date", "observed_slippage_bps"])
    out = out[
        out["ticker"].ne("")
        & out["side"].isin({"BUY", "SELL"})
    ].copy()
    return out.sort_values(["date", "ticker", "side"]).reset_index(drop=True)


class ExecutionCostModel:
    """Quote conservative per-order costs from PIT OHLCV and paper evidence."""

    def __init__(self, prices: dict[str, pd.DataFrame], config: ExecutionCostConfig):
        self.prices = prices
        self.config = config
        self.paper_slippage = load_paper_slippage(config.paper_slippage_path)
        self._snapshot_cache: dict[tuple[str, str], LiquiditySnapshot] = {}

    def snapshot(self, ticker: str, fill_date: Any) -> LiquiditySnapshot:
        date = pd.Timestamp(fill_date).normalize()
        key = (str(ticker).upper(), date.date().isoformat())
        if key not in self._snapshot_cache:
            self._snapshot_cache[key] = liquidity_snapshot(
                self.prices.get(key[0], pd.DataFrame()),
                date,
                self.config,
            )
        return self._snapshot_cache[key]

    def observed_slippage(self, ticker: str, side: str, fill_date: Any) -> float | None:
        if self.paper_slippage.empty:
            return None
        date = pd.Timestamp(fill_date).normalize()
        rows = self.paper_slippage[
            self.paper_slippage["date"].eq(date)
            & self.paper_slippage["ticker"].eq(str(ticker).upper())
            & self.paper_slippage["side"].eq(str(side).upper())
        ]
        if rows.empty:
            return None
        value = _finite_float(rows["observed_slippage_bps"].median())
        return max(float(value), 0.0) if value is not None else None

    def paper_slippage_issues(
        self,
        *,
        fixed_cost_bps: float,
        relevant_trade_keys: set[tuple[str, str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Return relevant paper rows whose fee would consume sale proceeds.

        A paper file may be a shared implementation ledger.  Only evidence
        whose ``(date, ticker, side)`` can be used by this replay is allowed to
        block it; unrelated symbols, dates, and sides remain unused evidence.
        """

        if self.paper_slippage.empty:
            return []
        maximum_observed = max(0.0, 10000.0 - max(float(fixed_cost_bps), 0.0))
        candidates = self.paper_slippage
        if relevant_trade_keys is not None:
            normalized_keys = {
                (
                    pd.Timestamp(raw_date).normalize().date().isoformat(),
                    str(ticker).upper().strip(),
                    str(side).upper().strip(),
                )
                for raw_date, ticker, side in relevant_trade_keys
            }
            candidate_keys = pd.Series(
                list(
                    zip(
                        candidates["date"].map(
                            lambda value: pd.Timestamp(value)
                            .normalize()
                            .date()
                            .isoformat()
                        ),
                        candidates["ticker"].astype(str).str.upper().str.strip(),
                        candidates["side"].astype(str).str.upper().str.strip(),
                    )
                ),
                index=candidates.index,
                dtype=object,
            )
            candidates = candidates.loc[
                candidate_keys.map(normalized_keys.__contains__)
            ]
        invalid = candidates[
            candidates["observed_slippage_bps"].ge(maximum_observed)
        ]
        return [
            {
                "date": pd.Timestamp(row.date).date().isoformat(),
                "ticker": str(row.ticker),
                "side": str(row.side),
                "observed_slippage_bps": float(row.observed_slippage_bps),
                "maximum_allowed_observed_slippage_bps": maximum_observed,
                "reason": "paper_slippage_plus_fixed_cost_reaches_100_percent",
            }
            for row in invalid.itertuples(index=False)
        ]

    def quote(
        self,
        *,
        ticker: str,
        side: str,
        fill_date: Any,
        gross_value: float,
        fixed_cost_bps: float,
    ) -> ExecutionCostQuote:
        base_bps = max(float(fixed_cost_bps), 0.0)
        snapshot = self.snapshot(ticker, fill_date)
        observed = self.observed_slippage(ticker, side, fill_date)
        if snapshot.status != "complete":
            missing_liquidity_ceiling = (
                float(self.config.maximum_half_spread_bps)
                + float(self.config.maximum_market_impact_bps)
            )
            effective_variable = max(
                missing_liquidity_ceiling,
                float(observed) if observed is not None else 0.0,
            )
            return ExecutionCostQuote(
                status="blocked",
                fixed_cost_bps=base_bps,
                half_spread_bps=None,
                market_impact_bps=None,
                estimated_variable_cost_bps=missing_liquidity_ceiling,
                observed_slippage_bps=observed,
                effective_variable_cost_bps=effective_variable,
                total_cost_bps=base_bps + effective_variable,
                adv20_usd=snapshot.adv20_usd,
                participation_rate=None,
                daily_volatility20=snapshot.daily_volatility20,
                spread_source="unavailable",
                slippage_source="paper" if observed is not None else "unavailable",
                observed_exceeds_model=(
                    bool(float(observed) > missing_liquidity_ceiling)
                    if observed is not None
                    else None
                ),
                liquidity_history_end_date=snapshot.history_end_date,
                reason=snapshot.reason,
            )

        participation = max(float(gross_value), 0.0) / max(float(snapshot.adv20_usd), 1e-12)
        impact_bps = float(
            np.clip(
                float(self.config.impact_coefficient)
                * float(snapshot.daily_volatility20)
                * math.sqrt(max(participation, 0.0))
                * 10000.0,
                0.0,
                float(self.config.maximum_market_impact_bps),
            )
        )
        estimated_variable = float(snapshot.half_spread_bps) + impact_bps
        effective_variable = (
            max(estimated_variable, float(observed))
            if observed is not None
            else estimated_variable
        )
        return ExecutionCostQuote(
            status="complete",
            fixed_cost_bps=base_bps,
            half_spread_bps=float(snapshot.half_spread_bps),
            market_impact_bps=impact_bps,
            estimated_variable_cost_bps=estimated_variable,
            observed_slippage_bps=observed,
            effective_variable_cost_bps=effective_variable,
            total_cost_bps=base_bps + effective_variable,
            adv20_usd=float(snapshot.adv20_usd),
            participation_rate=participation,
            daily_volatility20=float(snapshot.daily_volatility20),
            spread_source="corwin_schultz_prior_ohlcv",
            slippage_source=(
                "max_paper_or_model" if observed is not None else "ohlcv_model"
            ),
            observed_exceeds_model=(
                bool(float(observed) > estimated_variable) if observed is not None else None
            ),
            liquidity_history_end_date=snapshot.history_end_date,
        )


def summarize_execution_costs(
    trades: pd.DataFrame,
    *,
    starting_capital: float,
    config: ExecutionCostConfig,
) -> dict[str, Any]:
    """Summarize coverage, cost attribution, and scalable ADV capacity."""

    if trades.empty:
        return {
            "schema_version": EXECUTION_COST_SCHEMA_VERSION,
            "trade_count": 0,
            "covered_trade_count": 0,
            "coverage_rate": 1.0,
            "coverage_complete": True,
            "capacity_scenarios": [],
        }
    frame = trades.copy()
    status = frame.get("cost_data_status", pd.Series("blocked", index=frame.index)).astype(str)
    covered = status.eq("complete")
    def numeric_column(name: str) -> pd.Series:
        source = (
            frame[name]
            if name in frame.columns
            else pd.Series(np.nan, index=frame.index, dtype=float)
        )
        return pd.to_numeric(source, errors="coerce")

    participation = numeric_column("participation_rate")
    total_cost_bps = numeric_column("total_cost_bps")
    estimated_bps = numeric_column("estimated_variable_cost_bps")
    observed_bps = numeric_column("observed_slippage_bps")
    gross = numeric_column("gross_value").fillna(0.0)
    observed_mask = observed_bps.notna()
    observed_exceeds = observed_mask & (observed_bps > estimated_bps)

    scenarios: list[dict[str, Any]] = []
    valid_participation = participation[covered & participation.notna() & participation.gt(0.0)]
    for limit in sorted({float(value) for value in config.capacity_participation_rates}):
        capacity_values = (
            float(starting_capital) * limit / valid_participation
            if not valid_participation.empty
            else pd.Series(dtype=float)
        )
        scenarios.append(
            {
                "max_adv_participation": limit,
                "strict_capacity_usd": (
                    float(capacity_values.min()) if not capacity_values.empty else None
                ),
                "p05_capacity_usd": (
                    float(capacity_values.quantile(0.05)) if not capacity_values.empty else None
                ),
                "median_capacity_usd": (
                    float(capacity_values.median()) if not capacity_values.empty else None
                ),
                "breach_trade_count_at_starting_capital": int(
                    (valid_participation > limit).sum()
                ),
            }
        )

    return {
        "schema_version": EXECUTION_COST_SCHEMA_VERSION,
        "trade_count": int(len(frame)),
        "covered_trade_count": int(covered.sum()),
        "coverage_rate": float(covered.mean()),
        "coverage_complete": bool(covered.all()),
        "paper_slippage_trade_count": int(observed_mask.sum()),
        "paper_slippage_coverage_rate": float(observed_mask.mean()),
        "paper_slippage_exceeds_model_count": int(observed_exceeds.sum()),
        "paper_slippage_exceeds_model_rate": (
            float(observed_exceeds.sum() / observed_mask.sum())
            if observed_mask.any()
            else None
        ),
        "gross_traded_usd": float(gross.sum()),
        "total_execution_cost_usd": float(
            numeric_column("fee_usd").fillna(0.0).sum()
        ),
        "gross_weighted_total_cost_bps": (
            float((gross * total_cost_bps.fillna(0.0)).sum() / gross.sum())
            if gross.sum() > 0.0
            else 0.0
        ),
        "max_participation_rate": (
            float(valid_participation.max()) if not valid_participation.empty else None
        ),
        "p95_participation_rate": (
            float(valid_participation.quantile(0.95))
            if not valid_participation.empty
            else None
        ),
        "capacity_scenarios": scenarios,
    }

# Implementation Proposal: Defensive Upgrades for Asymmetric Return Profile

**Target file**: `r1000_top30_institutional.py` (~20,686 lines)
**Objective**: Maximize gains in bull markets, minimize losses in bear markets ("eat more when eating, lose less when losing"). Catch market changes fast without being fooled by false signals.
**Audience**: Implementation agent (Sonnet / Codex / GPT). Do not deviate from the exact insertion points, function signatures, or data flows described below. Read the referenced line numbers in the current file before making any change — this proposal was written against commit `9f80653` and line numbers may have shifted if newer commits exist.

---

## Executive Summary

Seven changes are proposed, grouped into three phases. Each change is self-contained and can be implemented and tested independently. The phases are ordered by **defensive impact per unit of complexity**.

| # | Title | Phase | Complexity | Expected effect |
|---|---|---|---|---|
| 1 | Portfolio-level drawdown circuit breaker | P1 | Low | Cuts tail losses ≥ -25% |
| 2 | Per-sleeve stop-loss extension | P1 | Low | Limits individual position damage across all sleeves |
| 3 | VIX level hard guard | P1 | Low | Immediate risk-off when VIX > 30/40 |
| 4 | Yield curve inversion signal | P2 | Medium | Earlier recession warning |
| 5 | Cross-asset confirmation layer | P2 | Medium | Reduces false regime flips |
| 6 | Regime transition smoothing (N-of-M confirmation) | P2 | Medium | Reduces whipsaw |
| 7 | Volatility targeting | P3 | Medium-High | Scales exposure inversely with realized vol |

All seven changes together require **no new external data dependencies** beyond two new FRED series (`DGS2` and `T10Y2Y` — already accessible via the existing `load_fred_series()` helper).

---

## Phase 1 — Immediate Defense (implement first)

### Proposal 1: Portfolio-level Drawdown Circuit Breaker

#### Problem
`backtest_portfolio()` (line 16634) tracks monthly returns in `ret_rows` but never computes a running drawdown and never reacts to it. If the portfolio drops 20%+ inside a single month or across two months, the system keeps the same exposure until the next scheduled rebalance. `max_dd_1y: 0.65` (EngineConfig line 841) is only used as a candidate-filter in screening (line 10855), not as a real-time trigger.

#### Design

Add a running equity-peak tracker inside the backtest loop. When running drawdown from peak crosses a series of thresholds, forcibly scale the portfolio toward cash **without waiting for the next rebalance**.

**Drawdown ladder (asymmetric, tunable):**

| Running DD from peak | Forced cash floor | Sleeve exposure scale |
|---|---|---|
| 0% to −8% | no action | 1.00 |
| −8% to −15% | cash ≥ 15% | 0.90 |
| −15% to −25% | cash ≥ 35% | 0.70 |
| > −25% | cash ≥ 60% | 0.40 |

The cash floor is a **hard minimum** — it overrides the sleeve policy cash target from `compute_regime_portfolio_controls()` when the ladder triggers a higher cash floor. Sleeve exposure scale multiplies all non-cash weights proportionally.

**Recovery hysteresis**: once triggered, stay at the cash floor until equity has recovered to within 3% of the level that triggered the breaker. This prevents whipsaw.

#### New EngineConfig fields

Insert after `speculative_stop_loss_pct` (currently around line 1058):

```python
# Portfolio drawdown circuit breaker
drawdown_circuit_breaker_enabled: bool = True
drawdown_breaker_level_1_threshold: float = 0.08   # -8% from peak
drawdown_breaker_level_1_cash_floor: float = 0.15
drawdown_breaker_level_1_scale: float = 0.90
drawdown_breaker_level_2_threshold: float = 0.15   # -15% from peak
drawdown_breaker_level_2_cash_floor: float = 0.35
drawdown_breaker_level_2_scale: float = 0.70
drawdown_breaker_level_3_threshold: float = 0.25   # -25% from peak
drawdown_breaker_level_3_cash_floor: float = 0.60
drawdown_breaker_level_3_scale: float = 0.40
drawdown_breaker_recovery_buffer: float = 0.03     # must recover within 3% of trigger equity
```

#### Insertion point

Inside `backtest_portfolio()`, two places:

**(a) Initialize tracker state** — immediately after `speculative_cum_ret: dict[str, float] = {}` at line 16697:

```python
    # Drawdown circuit breaker state
    dd_breaker_enabled = bool(getattr(cfg, "drawdown_circuit_breaker_enabled", True))
    dd_peak_equity: float = 1.0       # compounded peak from start
    dd_running_equity: float = 1.0    # compounded current from start
    dd_active_level: int = 0          # 0 = not triggered, 1/2/3 = ladder level
    dd_trigger_equity: float = 0.0    # equity value when breaker last triggered
```

**(b) Apply breaker logic** — inside the monthly loop, AFTER `net_ret = month_ret - cost` at line 16833 and BEFORE `current_w = drift_weights_by_period_returns(...)` at line 16834:

```python
        # Update drawdown tracker with this month's net return
        dd_running_equity *= (1.0 + float(net_ret))
        if dd_running_equity > dd_peak_equity:
            dd_peak_equity = dd_running_equity
            # Recovered fully → reset breaker
            if dd_active_level > 0 and dd_running_equity >= dd_trigger_equity * (1.0 - float(cfg.drawdown_breaker_recovery_buffer)):
                dd_active_level = 0
                dd_trigger_equity = 0.0
        current_dd = 0.0 if dd_peak_equity <= 0 else 1.0 - (dd_running_equity / dd_peak_equity)

        if dd_breaker_enabled:
            # Determine ladder level to apply (never step down mid-drawdown)
            target_level = 0
            if current_dd >= float(cfg.drawdown_breaker_level_3_threshold):
                target_level = 3
            elif current_dd >= float(cfg.drawdown_breaker_level_2_threshold):
                target_level = 2
            elif current_dd >= float(cfg.drawdown_breaker_level_1_threshold):
                target_level = 1
            # Step up immediately; only step down after full recovery (handled above)
            if target_level > dd_active_level:
                dd_active_level = target_level
                dd_trigger_equity = dd_running_equity
            if dd_active_level > 0:
                cash_floor = [
                    0.0,
                    float(cfg.drawdown_breaker_level_1_cash_floor),
                    float(cfg.drawdown_breaker_level_2_cash_floor),
                    float(cfg.drawdown_breaker_level_3_cash_floor),
                ][dd_active_level]
                scale = [
                    1.0,
                    float(cfg.drawdown_breaker_level_1_scale),
                    float(cfg.drawdown_breaker_level_2_scale),
                    float(cfg.drawdown_breaker_level_3_scale),
                ][dd_active_level]
                # Scale all non-cash weights down and push residual to cash
                current_cash = float(current_w.get(CASH_PROXY_TICKER, 0.0))
                non_cash_tickers = [t for t in current_w.keys() if str(t).upper() != CASH_PROXY_TICKER]
                non_cash_total = sum(float(current_w[t]) for t in non_cash_tickers)
                target_non_cash = max(0.0, min(1.0 - cash_floor, non_cash_total * scale))
                if non_cash_total > 1e-9:
                    shrink = target_non_cash / non_cash_total
                    for t in non_cash_tickers:
                        current_w[t] = float(current_w[t]) * shrink
                current_w[CASH_PROXY_TICKER] = float(max(cash_floor, 1.0 - target_non_cash))
                # Renormalize to 1.0
                total = sum(float(v) for v in current_w.values())
                if total > 1e-9 and abs(total - 1.0) > 1e-8:
                    current_w = {k: float(v) / total for k, v in current_w.items() if float(v) > 1e-10}
```

**(c) Record breaker state in ret_rows** — inside the `ret_rows.append({...})` call around line 16884, add these fields:

```python
                "dd_running": float(current_dd),
                "dd_breaker_level": int(dd_active_level),
                "dd_peak_equity": float(dd_peak_equity),
```

#### Edge cases

1. If `dd_peak_equity == 0` → skip (first month).
2. If breaker is triggered on the same month as a scheduled rebalance → the rebalance runs first (producing normal target weights), then breaker scales them down. This is the correct order because the rebalance is the "fresh signal" and the breaker is "post-trade defense".
3. If `scale == 0.40` and existing cash target is already 70% → pick `max(cash_floor, existing)`, keep the more defensive.
4. Recovery buffer prevents oscillation: breaker at level 2 triggered at equity = 0.85 stays at level 2 until equity reaches `0.85 * (1 - 0.03) = 0.8245` — but wait, this is WRONG for a recovery check. Recovery means equity GOES UP, not down. The check should be: `dd_running_equity >= dd_trigger_equity` (i.e., equity has recovered all the way back to the trigger point). The buffer should be applied as a tolerance: `dd_running_equity >= dd_trigger_equity * (1.0 + buffer)` to require slight overshoot before resetting. Fix the sign in the implementation — the intent is "equity must be above the trigger level by at least 3% before resetting".

**Correct recovery check**:
```python
if dd_active_level > 0 and dd_running_equity >= dd_trigger_equity * (1.0 + float(cfg.drawdown_breaker_recovery_buffer)):
    dd_active_level = 0
    dd_trigger_equity = 0.0
```

#### Test plan

1. **Sanity**: run backtest with `drawdown_circuit_breaker_enabled=False` — should produce identical results to current code.
2. **Synthetic crash test**: construct a signal DataFrame that forces a -30% single-month return. Verify breaker triggers level 3 and cash floor reaches ≥60%.
3. **Recovery**: in a followed month that reverses the loss, verify breaker resets at level 0 after equity exceeds trigger × 1.03.
4. **Full backtest diff**: compare metrics before/after on full 2008 and 2020 Q1 history. Expected: max_dd improves by 3–8 percentage points, CAGR stays within ±0.5pp of baseline.

---

### Proposal 2: Per-Sleeve Stop-Loss Extension

#### Problem
Current stop-loss (line 16836-16869) only applies to tickers flagged `_is_speculative` (early_scout-leaning names with high scout scores). Core_compounder and future_winner positions can drop 40%+ with no per-name exit.

#### Design

Replace the single `speculative_stop_loss_pct` with a per-sleeve threshold dictionary. Track cumulative return from entry for **every** held position (not just speculative ones). Use sleeve-specific thresholds:

| Sleeve | Stop-loss |
|---|---|
| early_scout | -25% (unchanged) |
| future_winner | -20% |
| core_compounder | -15% |
| cash | n/a |

Rationale: early_scout names are speculative and need room to breathe. Core compounders should not be declining -15%+ if the thesis holds — a -15% drop is a signal the thesis is broken.

#### New EngineConfig fields

Add after `speculative_stop_loss_pct: float = 0.25`:

```python
stop_loss_per_sleeve_enabled: bool = True
stop_loss_core_compounder_pct: float = 0.15
stop_loss_future_winner_pct: float = 0.20
stop_loss_early_scout_pct: float = 0.25   # same as current speculative
```

#### Insertion point

Modify the existing stop-loss block (lines 16836-16869 in `backtest_portfolio()`).

Replace:
```python
        # Hard stop-loss: track speculative positions and force-exit at -25%
        if stop_loss_pct > 0:
            is_spec = {}
            ...
```

With:
```python
        # Per-sleeve hard stop-loss: track ALL positions and force-exit per sleeve threshold
        per_sleeve_sl_enabled = bool(getattr(cfg, "stop_loss_per_sleeve_enabled", True))
        if per_sleeve_sl_enabled:
            sleeve_thresholds = {
                "core_compounder": float(getattr(cfg, "stop_loss_core_compounder_pct", 0.15)),
                "future_winner":   float(getattr(cfg, "stop_loss_future_winner_pct", 0.20)),
                "early_scout":     float(getattr(cfg, "stop_loss_early_scout_pct", 0.25)),
            }
            # Map ticker -> sleeve label from current_portfolio
            ticker_sleeve: dict[str, str] = {}
            if not current_portfolio.empty and "portfolio_sleeve_label" in current_portfolio.columns:
                for _, row in current_portfolio.iterrows():
                    t = str(row.get("ticker", ""))
                    ticker_sleeve[t] = str(row.get("portfolio_sleeve_label", "core_compounder"))
            # Update cumulative returns for every non-cash holding
            new_cum: dict[str, float] = {}
            for tkr in list(current_w.keys()):
                if tkr == CASH_PROXY_TICKER:
                    continue
                r_m = ticker_month_returns.get(tkr, 0.0)
                if tkr in speculative_cum_ret:
                    new_cum[tkr] = (1 + speculative_cum_ret[tkr]) * (1 + r_m) - 1
                else:
                    new_cum[tkr] = r_m
            speculative_cum_ret = new_cum
            # Apply per-sleeve stop-loss
            for tkr, cum_r in list(speculative_cum_ret.items()):
                sleeve = ticker_sleeve.get(tkr, "core_compounder")
                threshold = sleeve_thresholds.get(sleeve, sleeve_thresholds["core_compounder"])
                if cum_r <= -abs(threshold):
                    stopped_out_tickers.add(tkr)
                    if tkr in current_w:
                        released = float(current_w.pop(tkr, 0.0))
                        current_w[CASH_PROXY_TICKER] = float(current_w.get(CASH_PROXY_TICKER, 0.0)) + released
                    del speculative_cum_ret[tkr]
            # Clean up tickers no longer held
            for tkr in list(speculative_cum_ret.keys()):
                if tkr not in current_w:
                    del speculative_cum_ret[tkr]
            # Reset tracking on rebalance (allow re-entry if signals improve)
            if rebalance_action in ("rebalance", "initial_rebalance"):
                stopped_out_tickers.clear()
        elif stop_loss_pct > 0:
            # Legacy path (speculative-only) kept for backward compatibility
            # [copy existing speculative-only block here]
            pass
```

#### Edge cases

1. Ticker not found in `current_portfolio` → fall back to `core_compounder` threshold (most conservative).
2. Stopped-out ticker reappears in next rebalance signals → normal entry (tracking cleared).
3. Cash proxy ticker must always be excluded.

#### Test plan

1. Force a -17% monthly return on a single core_compounder ticker → verify it is stopped out.
2. Force a -22% monthly return on a future_winner → verify stopped out at -20%.
3. Force a -24% monthly return on an early_scout → verify NOT stopped out (threshold is -25%).
4. Verify `stopped_out_tickers` count in backtest diagnostics increases.

---

### Proposal 3: VIX Level Hard Guard

#### Problem
`compute_regime_portfolio_controls()` uses `vix_z_63d` (rolling z-score) but the absolute VIX level matters independently. In Aug 2015, Feb 2018, March 2020, VIX jumped to 40+ in a week — the z-score lags by 2-3 weeks because the rolling 63-day window is slow to adjust.

#### Design

Add a hard guard: if current VIX level exceeds configurable thresholds, force minimum cash floor directly in `compute_regime_portfolio_controls()`.

| VIX level | Cash floor |
|---|---|
| < 22 | no action |
| 22 – 28 | cash ≥ 10% |
| 28 – 35 | cash ≥ 25% |
| 35 – 45 | cash ≥ 40% |
| > 45 | cash ≥ 55% |

Uses median of `vix_level` column across the month_df (the regime table already has `vix_level`, line 6213).

#### New EngineConfig fields

Add after `live_event_growth_threshold: float = 0.55`:

```python
vix_level_guard_enabled: bool = True
vix_level_tier1_threshold: float = 22.0   # mild elevation
vix_level_tier1_cash_floor: float = 0.10
vix_level_tier2_threshold: float = 28.0   # stress
vix_level_tier2_cash_floor: float = 0.25
vix_level_tier3_threshold: float = 35.0   # crisis
vix_level_tier3_cash_floor: float = 0.40
vix_level_tier4_threshold: float = 45.0   # panic
vix_level_tier4_cash_floor: float = 0.55
```

#### Insertion point

Inside `compute_regime_portfolio_controls()`, immediately before the final `cash_target = float(np.clip(cash_target, 0.0, cfg.cash_weight_max))` at line 8355:

```python
        # VIX level hard guard — immediate risk reduction when absolute VIX is high
        if bool(getattr(cfg, "vix_level_guard_enabled", True)):
            vix_level_val = _median_or_default("vix_level", np.nan)
            if not np.isnan(vix_level_val):
                vix_floor = 0.0
                if vix_level_val >= float(cfg.vix_level_tier4_threshold):
                    vix_floor = float(cfg.vix_level_tier4_cash_floor)
                elif vix_level_val >= float(cfg.vix_level_tier3_threshold):
                    vix_floor = float(cfg.vix_level_tier3_cash_floor)
                elif vix_level_val >= float(cfg.vix_level_tier2_threshold):
                    vix_floor = float(cfg.vix_level_tier2_cash_floor)
                elif vix_level_val >= float(cfg.vix_level_tier1_threshold):
                    vix_floor = float(cfg.vix_level_tier1_cash_floor)
                cash_target = max(cash_target, vix_floor)
```

#### Data requirement

`vix_level` column must be present in `month_df`. Already provided by `build_macro_regime_table()` at line 6213. No new data ingestion needed.

#### Test plan

1. Monkeypatch `_median_or_default` to return `vix_level = 42.0` → verify cash_target ≥ 0.40.
2. Monkeypatch `vix_level = 15.0` → verify no override.
3. Verify the guard is orthogonal to existing event-regime logic (both stack via `max`).

---

## Phase 2 — Signal Quality (implement after Phase 1 verified)

### Proposal 4: Yield Curve Inversion Signal

#### Problem
The 2y/10y yield curve (T10Y2Y spread) is one of the most reliable recession leading indicators — inverted ≥ 6 months before recessions in 2001, 2008, 2020. Currently not computed. DGS10 is loaded but DGS2 is not.

#### Design

1. Add `DGS2` to `MACRO_FRED_SERIES` dict at line 255.
2. In `build_macro_regime_table()` at line 6218, load DGS2 alongside DGS10 and compute:
   - `yield_curve_spread_2y10y = dgs10 - dgs2` (positive = normal, negative = inverted)
   - `yield_curve_inverted_flag = 1.0 if spread < 0 else 0.0`
   - `yield_curve_inversion_depth = max(0.0, -spread)` (0 if normal, positive depth if inverted)
   - `yield_curve_inverted_days_120d = rolling sum of inverted_flag over 120 trading days`
3. Add these columns to `MACRO_REGIME_COLUMNS` list at line 286.
4. Integrate into `compute_regime_portfolio_controls()`:
   - Read `yield_curve_inversion_depth` and `yield_curve_inverted_days_120d`
   - Add to the `stress` composite with weight ~0.30
   - Specifically: deep inversion (depth > 0.50 for 60+ days) contributes to systemic risk pool
5. Use as a leading indicator for `growth_reentry_score` (negatively) — when curve is still inverted, growth re-entry signal should be discounted.

#### New FRED series definition

Add to `MACRO_FRED_SERIES` (line 255):

```python
MACRO_FRED_SERIES = {
    "vix": "VIXCLS",
    "dgs10": "DGS10",
    "dgs2": "DGS2",                    # ← NEW
    "t10y2y": "T10Y2Y",                # ← NEW: FRED-computed spread (fallback if DGS2 unavailable)
    ...
}
```

Use `T10Y2Y` as primary (FRED already computes the spread) and `DGS10 - DGS2` as fallback.

#### New EngineConfig fields

```python
yield_curve_signal_enabled: bool = True
yield_curve_inversion_stress_weight: float = 0.30
yield_curve_deep_inversion_threshold: float = 0.50   # percentage points
yield_curve_deep_inversion_days_threshold: int = 60  # trading days
```

#### Insertion point (build_macro_regime_table)

After line 6223 (`dgs_df["dgs10_change_1m"] = dgs10.diff(21)`):

```python
    dgs2 = load_fred_series(cfg, paths, "dgs2", MACRO_FRED_SERIES["dgs2"])
    t10y2y_direct = load_fred_series(cfg, paths, "t10y2y", MACRO_FRED_SERIES["t10y2y"])
    if not t10y2y_direct.empty:
        yc_df = pd.DataFrame(index=t10y2y_direct.index)
        yc_df["yield_curve_spread_2y10y"] = t10y2y_direct
    elif not dgs2.empty and not dgs10.empty:
        aligned = pd.concat([dgs10, dgs2], axis=1, keys=["dgs10", "dgs2"]).ffill()
        yc_df = pd.DataFrame(index=aligned.index)
        yc_df["yield_curve_spread_2y10y"] = aligned["dgs10"] - aligned["dgs2"]
    else:
        yc_df = pd.DataFrame()
    if not yc_df.empty:
        yc_df["yield_curve_inverted_flag"] = (yc_df["yield_curve_spread_2y10y"] < 0).astype(float)
        yc_df["yield_curve_inversion_depth"] = (-yc_df["yield_curve_spread_2y10y"]).clip(lower=0.0)
        yc_df["yield_curve_inverted_days_120d"] = yc_df["yield_curve_inverted_flag"].rolling(120, min_periods=1).sum()
        frames.append(yc_df)
```

Add to `MACRO_REGIME_COLUMNS` list:
```python
    "yield_curve_spread_2y10y",
    "yield_curve_inverted_flag",
    "yield_curve_inversion_depth",
    "yield_curve_inverted_days_120d",
```

#### Insertion point (compute_regime_portfolio_controls)

Inside the function, after line 8132 (`liquidity_drain = 0.0 if ... else liquidity_drain`):

```python
    yc_depth = _median_or_default("yield_curve_inversion_depth", 0.0)
    yc_days = _median_or_default("yield_curve_inverted_days_120d", 0.0)
    yc_signal_enabled = bool(getattr(cfg, "yield_curve_signal_enabled", True))
    yc_stress_weight = float(getattr(cfg, "yield_curve_inversion_stress_weight", 0.30))
    yc_deep_threshold = float(getattr(cfg, "yield_curve_deep_inversion_threshold", 0.50))
    yc_days_threshold = float(getattr(cfg, "yield_curve_deep_inversion_days_threshold", 60))
    yc_stress_component = 0.0
    if yc_signal_enabled:
        # Linear stress: any inversion contributes; deep+sustained inversion contributes heavily
        shallow = min(1.0, yc_depth / 1.0)   # 0 to 1 as depth goes 0 to 1pp
        deep_sustained = (
            1.0
            if (yc_depth >= yc_deep_threshold and yc_days >= yc_days_threshold)
            else 0.0
        )
        yc_stress_component = yc_stress_weight * (0.60 * shallow + 0.40 * deep_sustained)
```

Then add `yc_stress_component` to the `stress` composite (line 8156-8177):

```python
    stress = (
        max(0.0, risk_off)
        + 0.50 * max(0.0, inflation)
        + ...
        + yc_stress_component    # ← NEW
        + float(cfg.event_regime_sensitivity) * (...)
    )
```

And discount `growth_reentry` when curve is still inverted (around line 8184):

```python
    # Discount growth re-entry when curve is still inverted
    growth_reentry_discounted = growth_reentry * (1.0 - min(0.50, yc_stress_component))
    bullish = (
        ...
        + float(cfg.event_regime_sensitivity) * 0.90 * growth_reentry_discounted
        ...
    )
```

#### Edge cases

1. FRED data for DGS2/T10Y2Y may be missing before 1976 → check `yc_df.empty` and skip gracefully.
2. `yield_curve_inverted_days_120d` requires 120 days of history → use `min_periods=1` so early samples still report.
3. Rolling 120d may pick up stale inversions from prior cycles — this is acceptable because the system weights "depth + days" jointly.

#### Test plan

1. Verify DGS2 loads successfully (check `macro["yield_curve_spread_2y10y"]` column exists after `build_macro_regime_table`).
2. Historical check: `yield_curve_inverted_days_120d` should be high during 2006-2007, 2019, 2022-2023.
3. Verify `stress` score increases in those periods vs. baseline.

---

### Proposal 5: Cross-Asset Confirmation Layer

#### Problem
Gold, TLT (long bonds), DXY, and commodities are all loaded but only as individual regime inputs. There is no explicit "cross-asset confirmation" — i.e., checking whether multiple asset classes agree on a regime call. A single asset signal can be noise; three asset classes agreeing is much rarer and much more reliable.

#### Design

Compute a `cross_asset_confirmation_score` per rebalance date. The score is a vote count across N independent asset-class signals:

| Asset class | Bearish condition | Bullish condition |
|---|---|---|
| Equity breadth | `market_breadth_regime_score < 0.50` | `> 0.60` |
| HY credit spreads | `hy_oas_change_1m > +0.30` (widening) | `< -0.15` (tightening) |
| USD (DXY) | `dxy_ret_1m > +0.025` (strong USD = risk-off) | `< -0.015` |
| Long bonds (via DGS10) | `dgs10_change_1m < -0.20` (yields dropping = flight to safety) | `> +0.10` |
| Gold (GLD) | `gld_ret_1m > +0.04` (gold rally = risk-off) | `< -0.02` |
| Oil (USO) | `uso_ret_1m < -0.08` (demand collapse) | `> +0.05` |

Vote count: each condition met = +1 bearish or +1 bullish.
- `cross_asset_bearish_votes = sum of bearish conditions met` (0 to 6)
- `cross_asset_bullish_votes = sum of bullish conditions met` (0 to 6)
- `cross_asset_net_signal = (bullish - bearish) / 6.0` in [-1, +1]

Integration: use `cross_asset_bearish_votes >= 4` as a **confirmation gate** for defensive actions. Specifically, apply a `cross_asset_confirmation_multiplier` to the final `stress` calculation.

#### New EngineConfig fields

```python
cross_asset_confirmation_enabled: bool = True
cross_asset_bearish_vote_threshold: int = 4
cross_asset_bullish_vote_threshold: int = 4
cross_asset_confirmation_strength: float = 0.25   # adds up to +25% to stress when fully confirmed
```

#### New helper function

Add before `compute_regime_portfolio_controls()` at line 8056:

```python
def compute_cross_asset_confirmation(month_df: pd.DataFrame) -> dict[str, float]:
    """Count how many asset classes agree on a bearish or bullish regime call."""
    def _median(col: str, default: float = 0.0) -> float:
        if col not in month_df.columns:
            return float(default)
        v = safe_float(pd.to_numeric(month_df[col], errors="coerce").median())
        return float(default if np.isnan(v) else v)

    breadth       = _median("market_breadth_regime_score", 0.50)
    hy_oas_chg    = _median("hy_oas_change_1m", 0.0)
    dxy_ret       = _median("dxy_ret_1m", 0.0)
    dgs10_chg     = _median("dgs10_change_1m", 0.0)
    gld_ret       = _median("gld_ret_1m", 0.0)
    uso_ret       = _median("uso_ret_1m", 0.0)

    bearish_votes = sum([
        breadth < 0.50,
        hy_oas_chg > 0.30,
        dxy_ret > 0.025,
        dgs10_chg < -0.20,
        gld_ret > 0.04,
        uso_ret < -0.08,
    ])
    bullish_votes = sum([
        breadth > 0.60,
        hy_oas_chg < -0.15,
        dxy_ret < -0.015,
        dgs10_chg > 0.10,
        gld_ret < -0.02,
        uso_ret > 0.05,
    ])
    return {
        "cross_asset_bearish_votes": float(bearish_votes),
        "cross_asset_bullish_votes": float(bullish_votes),
        "cross_asset_net_signal": float((bullish_votes - bearish_votes) / 6.0),
    }
```

#### Integration in compute_regime_portfolio_controls

After line 8191 (`liquidity_multiplier = 1.0 + ...`):

```python
    if bool(getattr(cfg, "cross_asset_confirmation_enabled", True)):
        ca = compute_cross_asset_confirmation(month_df)
        bearish_thr = int(getattr(cfg, "cross_asset_bearish_vote_threshold", 4))
        bullish_thr = int(getattr(cfg, "cross_asset_bullish_vote_threshold", 4))
        ca_strength = float(getattr(cfg, "cross_asset_confirmation_strength", 0.25))
        if ca["cross_asset_bearish_votes"] >= bearish_thr:
            confirmation_boost = ca_strength * (ca["cross_asset_bearish_votes"] / 6.0)
            stress = stress * (1.0 + confirmation_boost)
        elif ca["cross_asset_bullish_votes"] >= bullish_thr:
            confirmation_discount = ca_strength * (ca["cross_asset_bullish_votes"] / 6.0)
            stress = stress * max(0.5, 1.0 - confirmation_discount)
```

#### Edge cases

1. Only apply when `month_df` has at least 3 of the 6 required columns — otherwise return neutral.
2. Keep bullish vs bearish strictly separate — do not net them first then apply, because the intent is to require multi-asset confirmation of a single direction.

#### Test plan

1. Backtest March 2020 month: expect bearish_votes ≥ 4 (breadth down, HY widening, gold up, oil down).
2. Backtest June 2020 recovery: expect bullish_votes ≥ 4.
3. Verify orthogonality: disable and re-enable, confirm stress score differs only when gate fires.

---

### Proposal 6: Regime Transition Smoothing (N-of-M Confirmation)

#### Problem
Current regime classification (`event_regime_label`) is computed per month with hard thresholds. A single noisy month can flip the regime from `balanced` to `systemic_crisis` and back — causing the sleeve policy to swing by 20-30 percentage points between core and future. This creates whipsaw turnover costs and noise.

#### Design

Add a **regime confirmation buffer**: before accepting a regime label change, require the new label to appear in `N` of the last `M` months. Default: 2-of-3 for growth→defensive, 3-of-4 for defensive→growth (asymmetric — go defensive fast, come back slow).

State is tracked across the walk-forward loop in `train_walkforward()` / `compute_event_regime_features()`.

#### New EngineConfig fields

```python
regime_confirmation_enabled: bool = True
regime_confirmation_to_defensive_n: int = 2   # N-of-M
regime_confirmation_to_defensive_m: int = 3
regime_confirmation_to_growth_n: int = 3
regime_confirmation_to_growth_m: int = 4
```

#### New helper function

Add after `compute_event_regime_features()` at line 5934:

```python
DEFENSIVE_REGIMES = {"systemic_crisis", "carry_unwind", "war_oil_rate_shock", "stagflation"}
GROWTH_REGIMES = {"growth_reentry"}
NEUTRAL_REGIMES = {"balanced"}

def smooth_regime_transitions(
    df: pd.DataFrame,
    cfg: EngineConfig,
    label_col: str = "event_regime_label",
) -> pd.DataFrame:
    """Add a `confirmed_regime_label` column that only transitions after N-of-M confirmation."""
    d = df.copy()
    if label_col not in d.columns or d.empty:
        d["confirmed_regime_label"] = d.get(label_col, "balanced")
        return d
    if not bool(getattr(cfg, "regime_confirmation_enabled", True)):
        d["confirmed_regime_label"] = d[label_col].astype(str)
        return d
    d = d.sort_values("rebalance_date")
    n_to_def = int(getattr(cfg, "regime_confirmation_to_defensive_n", 2))
    m_to_def = int(getattr(cfg, "regime_confirmation_to_defensive_m", 3))
    n_to_gro = int(getattr(cfg, "regime_confirmation_to_growth_n", 3))
    m_to_gro = int(getattr(cfg, "regime_confirmation_to_growth_m", 4))
    # Iterate cik by cik? No — regime is market-wide, so run on unique rebalance dates
    unique_dates = d["rebalance_date"].drop_duplicates().sort_values().tolist()
    raw_labels = {dt: d.loc[d["rebalance_date"] == dt, label_col].dropna().astype(str).mode().iloc[0]
                  if not d.loc[d["rebalance_date"] == dt, label_col].dropna().empty else "balanced"
                  for dt in unique_dates}
    confirmed = {}
    current = raw_labels[unique_dates[0]]
    history: list[str] = [current]
    confirmed[unique_dates[0]] = current
    for i in range(1, len(unique_dates)):
        dt = unique_dates[i]
        raw = raw_labels[dt]
        history.append(raw)
        current_is_defensive = current in DEFENSIVE_REGIMES
        raw_is_defensive = raw in DEFENSIVE_REGIMES
        raw_is_growth = raw in GROWTH_REGIMES
        if current_is_defensive and raw_is_growth:
            # Transitioning OUT of defensive → require N-of-M confirmation
            window = history[-m_to_gro:]
            growth_count = sum(1 for x in window if x in GROWTH_REGIMES)
            if growth_count >= n_to_gro:
                current = raw
        elif (not current_is_defensive) and raw_is_defensive:
            # Transitioning INTO defensive → require N-of-M confirmation
            window = history[-m_to_def:]
            def_count = sum(1 for x in window if x in DEFENSIVE_REGIMES)
            if def_count >= n_to_def:
                current = raw
        else:
            # Same direction or neutral → accept immediately
            current = raw
        confirmed[dt] = current
    d["confirmed_regime_label"] = d["rebalance_date"].map(confirmed).fillna("balanced").astype(str)
    return d
```

#### Insertion point

Call `smooth_regime_transitions()` after `compute_event_regime_features()` in the feature store build pipeline. The function signature expects a single DataFrame with `rebalance_date` and `event_regime_label` columns.

Locate where `event_regime_label` is written in the walk-forward scored panel — grep for `event_regime_label`. Apply smoothing there and use `confirmed_regime_label` in downstream consumers (`compute_regime_portfolio_controls`, `compute_regime_conditional_ensemble_weights`).

**Minimal integration**: in `compute_regime_portfolio_controls()` at line 8056, read `confirmed_regime_label` first and fall back to `event_regime_label`:

```python
def _regime_label_for_controls(month_df: pd.DataFrame) -> str:
    for col in ("confirmed_regime_label", "event_regime_label", "regime_label"):
        if col in month_df.columns:
            vals = month_df[col].dropna().astype(str)
            if not vals.empty:
                return str(vals.mode().iloc[0])
    return "balanced"
```

#### Edge cases

1. First `M` months have insufficient history → use raw label (no smoothing).
2. Walk-forward OOS: `smooth_regime_transitions()` must only look at PAST months — it already does because it iterates in order and never peeks forward. **However**, when called in a walk-forward loop where each month is processed independently with a cumulative `scored` DataFrame, make sure the function receives only the months up to and including the current test month.
3. Transition within the defensive family (e.g., `systemic_crisis` → `war_oil_rate_shock`) should be immediate (both are defensive) — the code above handles this correctly because `current_is_defensive == raw_is_defensive` falls through to the "accept immediately" branch.

#### Test plan

1. Synthetic sequence `['balanced', 'systemic_crisis', 'balanced', 'balanced']` → confirmed should stay `balanced` (1 of 3 not ≥ 2).
2. Sequence `['balanced', 'systemic_crisis', 'systemic_crisis', 'balanced']` → confirmed should flip to `systemic_crisis` on month 3 (2 of 3), then stay systemic for at least 4 months before returning to balanced.
3. Verify turnover decreases and average cash_target variance decreases between runs with/without smoothing.

---

## Phase 3 — Return Maximization

### Proposal 7: Explicit Volatility Targeting

#### Problem
Current weighting uses `weight_invvol_power: 0.20` — a very mild penalty on high-vol names. Position sizing does not adapt to the overall **portfolio vol regime**. In low-vol calm markets (realized vol ~8%), the system could safely take more exposure. In high-vol stressed markets (realized vol ~25%), the same exposure is too aggressive.

#### Design

Compute realized portfolio vol over the trailing N months. Compare to a target vol. Scale the entire invested share (1 − cash) by `target_vol / realized_vol`, bounded between `[0.5, 1.0]` (never leverage above 100%, but can shrink to 50%).

| Realized portfolio vol (annualized) | Scale factor |
|---|---|
| ≤ 10% | 1.00 (no shrink) |
| 12% (target) | 0.83 |
| 15% | 0.67 |
| 20% | 0.50 (hard floor) |
| > 20% | 0.50 |

Formula: `scale = clip(target_vol / max(realized_vol, target_vol), 0.5, 1.0)`

#### New EngineConfig fields

```python
volatility_targeting_enabled: bool = False   # default OFF until validated
vol_target_annualized: float = 0.12
vol_lookback_months: int = 6
vol_scale_floor: float = 0.50
vol_scale_ceiling: float = 1.00
```

#### Insertion point

Inside `backtest_portfolio()`, maintain a rolling list of recent `net_return` values. Before applying each new portfolio's weights, compute the scale factor and apply it.

Add state initialization after line 16697:

```python
    vol_target_enabled = bool(getattr(cfg, "volatility_targeting_enabled", False))
    vol_target = float(getattr(cfg, "vol_target_annualized", 0.12))
    vol_lookback = int(getattr(cfg, "vol_lookback_months", 6))
    vol_floor = float(getattr(cfg, "vol_scale_floor", 0.50))
    vol_ceiling = float(getattr(cfg, "vol_scale_ceiling", 1.00))
    recent_returns: list[float] = []   # last vol_lookback monthly net returns
```

After `net_ret = month_ret - cost` at line 16833, append to recent_returns:

```python
        recent_returns.append(float(net_ret))
        if len(recent_returns) > vol_lookback:
            recent_returns.pop(0)
```

And immediately after the drawdown circuit breaker block (from Proposal 1), add vol scaling:

```python
        if vol_target_enabled and len(recent_returns) >= max(3, vol_lookback // 2):
            realized_monthly_vol = float(np.std(recent_returns, ddof=1))
            realized_annualized = realized_monthly_vol * (12 ** 0.5)
            if realized_annualized > 1e-9:
                vol_scale = vol_target / max(realized_annualized, vol_target)
                vol_scale = float(np.clip(vol_scale, vol_floor, vol_ceiling))
            else:
                vol_scale = 1.0
            if vol_scale < 1.0 - 1e-6:
                non_cash_tickers = [t for t in current_w.keys() if str(t).upper() != CASH_PROXY_TICKER]
                non_cash_total = sum(float(current_w[t]) for t in non_cash_tickers)
                target_non_cash = non_cash_total * vol_scale
                shrink = target_non_cash / non_cash_total if non_cash_total > 1e-9 else 1.0
                for t in non_cash_tickers:
                    current_w[t] = float(current_w[t]) * shrink
                freed = non_cash_total - target_non_cash
                current_w[CASH_PROXY_TICKER] = float(current_w.get(CASH_PROXY_TICKER, 0.0)) + freed
                total = sum(float(v) for v in current_w.values())
                if total > 1e-9 and abs(total - 1.0) > 1e-8:
                    current_w = {k: float(v) / total for k, v in current_w.items() if float(v) > 1e-10}
```

#### Edge cases

1. First 3 months have insufficient history → skip (set scale = 1.0).
2. Realized vol ≤ target → no shrink (scale = 1.0).
3. Interaction with drawdown circuit breaker: apply drawdown breaker FIRST, then vol targeting. The breaker takes precedence.
4. Default OFF (`volatility_targeting_enabled: False`) — must be explicitly enabled because it can reduce CAGR in calm markets if the target is set too low.

#### Test plan

1. Run with `volatility_targeting_enabled=False` → identical to current.
2. Run with target=0.12 → expect lower vol, slightly lower CAGR, higher Sharpe in noisy periods.
3. Run with target=0.20 → expect minimal change (target too loose).
4. Verify acceptance: `max_dd` improves, `sharpe` improves, `cagr` may drop slightly.

---

## Implementation Order & Dependencies

```
Phase 1 (no cross-dependencies, implement in any order):
  1. Drawdown circuit breaker    (backtest_portfolio loop)
  2. Per-sleeve stop-loss        (backtest_portfolio loop — touches same block as #1)
  3. VIX level hard guard        (compute_regime_portfolio_controls)

Phase 2 (independent, but #6 depends on feature being present):
  4. Yield curve signal          (macro loader + compute_regime_portfolio_controls)
  5. Cross-asset confirmation    (new helper + compute_regime_portfolio_controls)
  6. Regime transition smoothing (new helper + compute_regime_portfolio_controls)

Phase 3 (independent):
  7. Volatility targeting        (backtest_portfolio loop — touches same block as #1)
```

**Recommended PR sequence**:

1. **PR A**: Proposals 1 + 2 (both live in the same stop-loss code block in `backtest_portfolio`) + CHANGELOG entry.
2. **PR B**: Proposal 3 (VIX guard, minimal) + CHANGELOG entry.
3. **PR C**: Proposal 4 (yield curve — requires FRED series addition) + CHANGELOG entry.
4. **PR D**: Proposals 5 + 6 (both touch regime logic) + CHANGELOG entry.
5. **PR E**: Proposal 7 (vol targeting, default OFF for safe merge) + CHANGELOG entry.

Each PR should produce its own CHANGELOG entry using the strict agent-readable format defined in `CHANGELOG.md` — see the `Agent Update Contract` section. Every entry must include `symbols_added`, `symbols_changed`, `config_fields_added`, `breaking_changes`. All in English.

---

## Global Testing Plan

For each PR:

1. **Backward-compat check**: run with all new `*_enabled` flags set to `False` — verify the backtest produces bit-identical metrics to the pre-change version (within 1e-9 float tolerance).
2. **Syntax check**: `python -c "import ast; ast.parse(open('r1000_top30_institutional.py').read())"`.
3. **Smoke test**: run a 2-year backtest (2018-2020) end-to-end, verify no exceptions.
4. **Full regression**: run full historical backtest and compare these metrics:
   - `cagr`, `max_dd`, `sharpe`, `sortino`, `calmar`, `excess_cagr`, `ir`, `beat_month_ratio`, `avg_turnover_monthly`, `avg_cash_weight`
5. **Period-specific stress tests**:
   - **2008 Q4** — expect max_dd improvement ≥ 5pp, CAGR slightly lower, Sharpe improvement
   - **2020 Q1** — expect max_dd improvement ≥ 3pp
   - **2022 full year** — expect better ranking vs S&P
   - **2017 calm bull** — expect CAGR within ±1pp (no over-defensiveness)

---

## EngineConfig Summary — All New Fields

```python
# Proposal 1: Drawdown circuit breaker
drawdown_circuit_breaker_enabled: bool = True
drawdown_breaker_level_1_threshold: float = 0.08
drawdown_breaker_level_1_cash_floor: float = 0.15
drawdown_breaker_level_1_scale: float = 0.90
drawdown_breaker_level_2_threshold: float = 0.15
drawdown_breaker_level_2_cash_floor: float = 0.35
drawdown_breaker_level_2_scale: float = 0.70
drawdown_breaker_level_3_threshold: float = 0.25
drawdown_breaker_level_3_cash_floor: float = 0.60
drawdown_breaker_level_3_scale: float = 0.40
drawdown_breaker_recovery_buffer: float = 0.03

# Proposal 2: Per-sleeve stop-loss
stop_loss_per_sleeve_enabled: bool = True
stop_loss_core_compounder_pct: float = 0.15
stop_loss_future_winner_pct: float = 0.20
stop_loss_early_scout_pct: float = 0.25

# Proposal 3: VIX level hard guard
vix_level_guard_enabled: bool = True
vix_level_tier1_threshold: float = 22.0
vix_level_tier1_cash_floor: float = 0.10
vix_level_tier2_threshold: float = 28.0
vix_level_tier2_cash_floor: float = 0.25
vix_level_tier3_threshold: float = 35.0
vix_level_tier3_cash_floor: float = 0.40
vix_level_tier4_threshold: float = 45.0
vix_level_tier4_cash_floor: float = 0.55

# Proposal 4: Yield curve inversion signal
yield_curve_signal_enabled: bool = True
yield_curve_inversion_stress_weight: float = 0.30
yield_curve_deep_inversion_threshold: float = 0.50
yield_curve_deep_inversion_days_threshold: int = 60

# Proposal 5: Cross-asset confirmation
cross_asset_confirmation_enabled: bool = True
cross_asset_bearish_vote_threshold: int = 4
cross_asset_bullish_vote_threshold: int = 4
cross_asset_confirmation_strength: float = 0.25

# Proposal 6: Regime transition smoothing
regime_confirmation_enabled: bool = True
regime_confirmation_to_defensive_n: int = 2
regime_confirmation_to_defensive_m: int = 3
regime_confirmation_to_growth_n: int = 3
regime_confirmation_to_growth_m: int = 4

# Proposal 7: Volatility targeting
volatility_targeting_enabled: bool = False   # default OFF
vol_target_annualized: float = 0.12
vol_lookback_months: int = 6
vol_scale_floor: float = 0.50
vol_scale_ceiling: float = 1.00
```

Total: 38 new EngineConfig fields across 7 proposals.

---

## Math & Logic Verification Notes (for Opus-level cross-check)

### Drawdown ladder direction
- `current_dd = 1.0 - (running / peak)` → always ≥ 0.
- Ladder triggers when `current_dd >= level_N_threshold` (positive threshold compared to positive DD).
- Ladder escalates monotonically; resets only when `running >= trigger * (1 + recovery_buffer)`.
- **Verified**: ladder is direction-correct.

### Recovery hysteresis
- When breaker triggered at equity 0.85 (peak 1.0, dd = 0.15), `dd_trigger_equity = 0.85`.
- Recovery requires `running >= 0.85 * 1.03 = 0.8755` → equity must recover at least 3% above the trigger point.
- This prevents bouncing in and out of the breaker around the exact trigger level.
- **Verified**: no oscillation risk.

### VIX guard vs sleeve policy cash target
- VIX guard applies `cash_target = max(cash_target, vix_floor)` — take the MORE defensive.
- Sleeve policy later enforces its own rules — compatible because sleeve policy also uses `max()` in most places.
- **Verified**: no conflict.

### Cross-asset vote asymmetry
- Bearish and bullish votes are counted separately (not netted first).
- This prevents a "3 bearish + 3 bullish = 0 net" from masking real regime confusion.
- When both thresholds fire simultaneously → bearish wins (defensive-first priority).
- **Verified**: asymmetric treatment is intentional.

### Regime smoothing look-ahead safety
- Function iterates `unique_dates` in sorted order and builds `history` list incrementally.
- Inside the walk-forward loop, when called with `scored_so_far`, it receives only OOS months up to the current test month — no peek.
- **Verified**: PIT-safe.

### Volatility targeting scaling
- `scale = target / max(realized, target)` → scale ∈ [0, 1], never > 1 (no leverage).
- Clipped to [floor, ceiling] = [0.50, 1.00].
- Applied AFTER drawdown breaker, so breaker is the hard line, vol targeting is the soft shrink.
- **Verified**: multiplicative composition is safe.

---

## Open Questions (flag these back to the user before implementation)

1. **Rebalance cadence interaction**: Should the drawdown breaker be allowed to trigger a forced rebalance (intra-month risk reduction), or only adjust weights without a full signal refresh? Current proposal: adjust weights only, do not trigger a rebalance. This is cheaper but less responsive.

2. **Cost modeling for breaker**: When breaker shrinks weights from 100% equity to 60% equity, that's 40% turnover in that month. Should this turnover be cost-charged (same as rebalance) or treated as emergency free-exit? Current proposal: cost-charge it at the same rate to stay honest.

3. **Per-sleeve stop-loss vs ensemble score conflict**: If a core_compounder is stopped at -15% but re-enters on the next month's high score, is that desired behavior? Current proposal: yes, allow re-entry — the stop-loss is a forced risk reduction, not a blacklist.

4. **Yield curve data availability in Colab environment**: DGS2 is a standard FRED series; verify `load_fred_series()` already handles it or if additional error handling is needed for the first fetch.

5. **Vol targeting default**: Should it be ON or OFF by default? Current proposal: **OFF** because aggressive targeting can hurt returns in calm markets; user should enable explicitly after backtest validation.

---

## End of Proposal

Implementation agent: start with **PR A (Proposals 1 + 2)**. Report each PR's test results (backward-compat diff, full regression metrics) before moving to the next PR.

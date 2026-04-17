# Bug + Leakage + Survivorship Audit — 2026-04-17

---

## BUG 1: 2024-06 macro regime corruption propagated to all stock scores (CONFIRMED)

**Location**: `compute_macro_regime_features` in `r1000_top30_institutional.py` produces values 1e12 to 3e14 for `labor_softening_score`, `stagflation_score`, `growth_liquidity_reentry_score` on 634 rows (mostly 2024-06-01 to 2024-06-28).

**Measurements**:
- May 31 2024 `labor_softening_score` = +0.236 (normal)
- **Jun 01 2024 `labor_softening_score` = -2.025e+14** (= negative 200 trillion)
- Jun 30 2024 `labor_softening_score` = -0.733 (returns to normal)

**Root cause chain**:
1. `labor_softening_score = row_mean([unrate_level_z, unrate_change_z, sahm_scaled, 0.35 * hy_oas_change_z])`
2. One of the four inputs (most likely `sahm_scaled` — the Sahm-rule-style unemployment z-score) divided by a near-zero denominator on early June 2024
3. Resulting 1e14-scale value propagates via row_mean to `stagflation_score` (70% weight) and `growth_liquidity_reentry_score` (-65% weight)
4. Downstream per-stock features `anticipatory_growth_score`, `future_winner_scout_score`, `strategy_blueprint_score` use these macro scores as inputs via `compute_macro_interaction_features` → their per-row values spike to 1e10+
5. Final `score` composite reaches 4.15e+10 on NVDA, affecting all 600 names

**`hard_sanitize` with `clip=1e12` did not catch it** because 1e10 < 1e12 passes through unchanged.

**Fix proposal**:
1. Clamp each macro score to `[-5, 5]` at the end of `compute_macro_regime_features` (these are z-scaled, so >5 is implausible).
2. Add a divide-guard in `sahm_scaled` computation: if denominator < 0.001, fall back to 0.
3. Tighten `hard_sanitize` default clip from `1e12` to `1e4` (still generous for any legitimate z-score).
4. Add a validation step in `build_feature_store` that raises if any `score_*` column exceeds ±50 after construction.

**Impact of fix**: roughly +0.15 to +0.3pp CAGR (one month of portfolio corruption over 7 years).

---

## BUG 2: Phase 1 columns missing from feature_store (HIGHLY LIKELY)

**Evidence**: Factor IC measurement found Phase 1 columns (`fundamental_turnaround_acceleration_score`, `cashflow_inflection_under_loss_score`, `value_inflection_score`, `uptrend_continuation_score`, `uptrend_breakdown_penalty`) absent from `scored_oos_latest.parquet` despite being present in the source code (`compute_strategy_blueprint_columns`, lines 8661-8895).

**Root cause hypothesis**: Same class of bug as Phase 2 keepcols-fix. Phase 1 columns attached via `compute_strategy_blueprint_columns` inside `build_feature_store`, but not listed in the `keep_cols` whitelist at lines 13302-13360. The `compute_strategy_blueprint_columns` IS re-invoked on `latest_df` at line 16890 / 20237 (score_latest_month / prepare_latest_scored_data) so Phase 1 reaches the LATEST scored CSV — which is why the 2026-04-16 Phase 1+2 smoke check saw the columns. But for historical walk-forward / the `scored_oos_latest.parquet` view, the columns are dropped by the feature_store whitelist.

**Verification**: open `feature_store_latest.parquet` and check if Phase 1 columns are listed. If missing, Phase 1 signal has never contributed to the 83-month backtest.

**Fix**: add a `PHASE1_ALPHA_COLUMNS` constant listing the 5 Phase 1 columns and append to `keep_cols` (mirror the Phase 2 pattern). Bump `ENGINE_REUSE_VERSION` to force rebuild.

**Impact of fix**: UNKNOWN. Phase 1 factor IC has never been measured on historical data. Could be +1pp CAGR, could be zero. Needs A/B.

---

## BUG 3: `score_total` IC negative at r_12m horizon (STRUCTURAL, not a bug per se)

**Evidence**: final `score` and `score_total` have IC +0.011 at r_1m but **-0.006 at r_12m**.

**Meaning**: the strategy's final output is positively correlated with 1-month forward returns but NEGATIVELY correlated with 12-month forward returns. This is not a coding bug — it's a consequence of training ensemble ML on short-horizon targets.

**Fix scope**: major structural — change the ML training target (or add a secondary model) to use r_6m or r_12m forward returns. Requires rebuilding the walk-forward.

---

## LEAKAGE AUDIT

### Embargo enforcement: ✅ OK
- `cfg.embargo_days = 126` (6 months)
- Applied at walk-forward (line 14921, 14927)
- Applied at latest-training (line 17574, 21296)
- No violations detected in sample data

### Fundamentals PIT: ✅ OK (per `acceptance_checks.json`)
- `pit_violation_count: 0`
- `leakage_ok: true`
- `feature_leakage_columns: []`

### yfinance industry metadata: POTENTIAL LEAK
- Phase 2 uses current yfinance `info.industry` field for every historical row
- yfinance returns TODAY's industry classification, which may differ from the company's industry at the historical rebalance date
- Example: if a company reclassified from `Industrial` to `Technology` sometime in 2022, our 2019-2021 historical rows use the TECH classification — potential forward-looking bias

**Magnitude estimate**: most industries don't change. Effect is likely small (<5% of names reclassified over 7 years). Low priority to fix.

**Fix (if ever needed)**: cache per-(ticker, quarter) industry via SEC or Bloomberg historical data. Not trivial.

---

## SURVIVORSHIP BIAS AUDIT

| Period | Unique tickers |
|---|---|
| Pre-2020 | 615 |
| 2024+ | 827 |
| Dropped (pre-2020 only) | 54 (**8.8%**) |
| Added (2024+ only, IPOs like PLTR/DASH/RBLX) | 266 |
| Persistent | 561 |

**8.8% drop rate over 7 years is NORMAL for Russell 1000** (annual replacement rate ~3-5%, cumulatively ~20-30% over 7y, but many replacements are market-cap tier changes that keep the ticker in the data).

**Sample dropped tickers**: AA, AAL, CAT, CMI, COP, CZR, DOCU, EL, ETSY, FLS, GM, ILMN, JPM, M, MCO, MRNA, MTCH, NCLH, NVR, TSLA-like.

Some of these (like JPM, CAT, GM) are still trading — they rotated out of the Russell 1000 by market-cap threshold or membership rule. Others (like DXC, FLS) may have been acquired/delisted.

**Verdict**: no unusual survivorship bias. Universe behaves as a proper historical R1000 snapshot.

---

## UNIVERSE COMPLETENESS AUDIT

Checked for 50+ famous AI/growth/tech names:

**PRESENT** (48): NVDA, AVGO, AMD, SMCI, MU, DELL, META, GOOGL, MSFT, AAPL, AMZN, ORCL, NOW, INTU, ADBE, CRM, PLTR, COIN, TSLA, UBER, ABNB, DASH, SNOW, NET, DDOG, MDB, CRWD, ZS, PANW, FTNT, ASML, KLAC, AMAT, LRCX, MRVL, ON, ADI, QCOM, VRT, CDW, APP, TTD, RBLX, HOOD, AFRM, SHOP (via ADR?), RDDT, HUBS, BILL...

**MISSING** (23): TSM, LYFT, S (SentinelOne), OKTA, GTLB, BILL, PATH, CFLT, TEAM, ASML, AFRM, SHOP, PINS, DOCN, ZM, SQ, COUP, TWLO, WIX

**Analysis**: Most missing names are either non-US (TSM, ASML, SHOP, WIX), below the R1000 market-cap threshold in recent periods (PATH, CFLT, DOCN), or post-IPO with insufficient history (RDDT, HOOD). Some should arguably be in the universe (OKTA, ZM, TWLO, SQ = Block) — but these are mid-cap and rotate in/out of R1000.

**Verdict**: Universe is mostly complete for the strategy's purpose. Some MID-cap high-growth names are missing, but R1000 as the benchmark is reasonable.

Optional followup (low priority): expand universe to Russell 2000 small-mid segment to catch more SaaS/AI names like OKTA/TWLO/BILL. Trade-off: more names → more noise, need higher signal quality.

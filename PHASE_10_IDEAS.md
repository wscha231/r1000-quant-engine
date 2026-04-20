# Phase 10 Ideas — Post-Refactor Alpha Brainstorm

> **Status**: BRAINSTORMING ONLY. Not a commitment. Decisions deferred until Refactor Phase A ships (Stages 3d + 4 + 5 done, byte-exact baseline confirmed).
> **Audience**: future Claude/Codex session, or human user revisiting after refactor.
> **Last updated**: 2026-04-20 12:00 KST.
> **Current production baseline (unchanged by refactor)**: main diversified CAGR 22.91% / Sharpe 1.172 / MaxDD -26.26%; concentrated champion N=5/1m/score_power CAGR 34.75% / Sharpe 1.254.

---

## 0. Why write this now

Refactor Phase A is mid-flight. Stages 3d/4/5 will finish it. Once the 5-module structure is live, alpha work becomes MUCH cheaper (one signal = one function in one module). This memo captures the top post-refactor ideas so the next session has a ranked starting point instead of re-doing the survey.

**Rule**: nothing here ships without an A/B against the current baseline, and no idea goes into master without clearing the standard ship gate:
- ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ -0.05 AND ΔMaxDD ≥ -3pp
- Plus sleeve sanity: early_scout count ≥ 4

---

## 1. Shortlist (ranked by expected alpha per wall-clock hour)

| Rank | Idea | Est. Δ CAGR | Est. work | Risk | Refactor benefit |
|---|---|---|---|---|---|
| **1** | **Phase 8e — r_12m ML training target** | +1.0-2.0pp | 11-13h | Medium | HIGH — walk-forward refactor needed |
| **2** | **Quarterly rebalance option** (vs monthly) | +0.2-0.8pp, -5-15pp turnover | 1 day | Low | HIGH — rebalance lives in signals.py |
| **3** | **R2000 universe expansion** | +0.5-1.5pp | 3-7 days | High | MEDIUM — universe lives in pipeline.py |
| **4** | **Top-10 concentration sleeve** (diversified between 5 and 30) | +1-3pp CAGR, +3-5pp MaxDD | 1-2 days | Medium | LOW — already modular via concentrated grid |
| **5** | **Analyst revision signal** (EPS estimate momentum) | +0.3-0.8pp | 2-3 days (data sourcing) | Medium | LOW — just a new feature |
| **6** | **Options IV risk overlay** (VIX variant per-name) | +0pp CAGR, -1-3pp MaxDD | 2-3 days | Medium | LOW — risk-overlay sleeve |
| **7** | **Insider flow + Form 4 acceleration** | +0.2-0.5pp | 3-5 days | High (data) | LOW |
| **8** | **Alternative data — sentiment/news** | Unknown | 1+ week | High | LOW |
| **9** | **LightGBM ensemble member** (alongside CatBoost) | +0.1-0.4pp | 2-3 days | Low | LOW |

Ranking rationale: **Phase 8e** has the highest expected alpha AND benefits most from refactor (walk-forward becomes single-owner in `r1000_pipeline.py`, so adding a second training target is mechanical). **Quarterly rebalance** is nearly free after refactor (one flag in `r1000_signals.py`) and historical fits suggest it reduces turnover without losing much alpha. **R2000 expansion** is the biggest potential win but also the biggest data engineering lift.

---

## 2. Detailed writeups (top 3)

### 2.1 Phase 8e — r_12m ML training target

**Hypothesis**: current walk-forward trains on `r_1m` (1-month forward return) only. This is myopic — industry/value/quality signals take 6-18 months to mean-revert. A second ensemble trained on `r_12m` would:
- Capture longer-horizon alpha that the 1m target washes out
- Reduce noise in the training labels (12m returns are less volatile than 1m)
- Provide a second opinion that can be blended with `r_1m` in `score_latest_month`

**Implementation sketch** (post-refactor, all in `r1000_pipeline.py` + `r1000_signals.py`):
```python
# In walk-forward training loop
targets = {"r_1m": r_1m, "r_12m": r_12m.shift(-11)}  # 12m cumulative forward
models = {k: train_ensemble(X, y, cfg) for k, y in targets.items()}

# In score_latest_month
score_1m = models["r_1m"].predict(X_latest)
score_12m = models["r_12m"].predict(X_latest)
blended = cfg.phase8e_weight_1m * score_1m + cfg.phase8e_weight_12m * score_12m
```

**Tuning grid**:
- `phase8e_weight_12m`: [0.0, 0.25, 0.5, 0.75]
- `phase8e_embargo_months`: [6, 9, 12] (must exceed label horizon)
- `phase8e_enabled`: bool

**Risks**:
- **Label leakage**: 12m forward return requires 12m embargo. Currently embargo=126d. Needs bump to 378d+.
- **Training data loss**: 12m labels mean last 12 months of training data are unusable (no label yet). 83-month backtest becomes effectively 71-month at the end.
- **FULL rebuild required**: `ENGINE_REUSE_VERSION` bump → 3-4h Colab rebuild to measure.

**Ship test plan**:
1. Baseline: Phase 9 C3 + CE v2 (current).
2. A/B: Phase 8e weight_12m=0.5 vs weight_12m=0.0.
3. Sensitivity: weight_12m ∈ {0.25, 0.5, 0.75}.

---

### 2.2 Quarterly rebalance option

**Hypothesis**: monthly rebalance incurs 43% annual turnover (current baseline). Quarterly (every 3 months) would cut turnover ~60% with minimal alpha loss — top-30 portfolio constituents don't flip every month.

**Implementation sketch** (post-refactor, in `r1000_signals.py`):
```python
# In backtest loop
rebalance_freq = cfg.rebalance_frequency  # "monthly" | "quarterly" | "annually"
if rebalance_freq == "quarterly" and month_i % 3 != 0:
    # Hold previous portfolio; no rescoring
    continue
# else re-run select_top30 / select_concentrated_portfolio_topk
```

**Tuning grid**:
- `rebalance_frequency`: monthly / quarterly (3m) / semiannually (6m) / annually (12m)
- Overlay: `drift_threshold_pct` (rebalance triggered if any position drifts >X% from target, e.g. 20%). Hybrid of calendar + drift.

**Risks**:
- **Missing fast-moving signals**: Phase 9 C3 EPS turn-positive flags might fire in month 1 but portfolio waits until month 3 to pick up the name.
- **Turnover reduction may tank early_scout sleeve**: early names by definition move fast. Quarterly rebalance may miss entry windows.

**Ship test plan**:
1. A/B: rebalance_frequency="monthly" (current) vs "quarterly" vs "semiannually".
2. Concentrated too: already has `concentrated_rebalance_intervals=[1,2,3]` grid. Add `[1,3,6,12]` for wider sweep.
3. Compare: turnover, CAGR, Sharpe, MaxDD, tax efficiency (not modeled but noted).

---

### 2.3 R2000 universe expansion (Russell 1000 → Russell 3000)

**Hypothesis**: Top-30 within R1000 is already concentrated in mega-cap. R2000 adds 2000 mid/small-cap names where anomalies (value, momentum, quality) are historically stronger. Expected +0.5-1.5pp CAGR from wider opportunity set.

**Implementation sketch**:
1. Expand `r1000_data_collector.py` ticker universe to R3000 constituents (CRSP or iShares IWV).
2. Rate limit: Alpha Vantage 25/day → need paid tier OR SEC-only fallback (no intraday fundamentals).
3. Liquidity filter: require ADV > $10M to avoid small-cap illiquidity inflating backtest returns.
4. Point-in-time universe: R3000 rebalances annually; use historical constituent lists (CRSP has them).

**Risks**:
- **Data engineering effort**: scraping 2000+ additional tickers' SEC/price data ~3 days.
- **Survivorship bias amplified**: small-caps have higher delisting rates. Need PIT constituent lists, not current membership.
- **Signal drift**: some factors (e.g. mega-cap override in Phase 8c.1) may not apply to small-caps; may need sleeve-specific signal weights.

**Ship test plan**:
1. Build R3000 historical universe separately (don't merge collector yet).
2. Backtest Top-30 select on R3000 universe with current signals.
3. A/B: R1000 baseline vs R3000 universe, same Top-30 count.
4. Sensitivity: Top-30 vs Top-60 (wider pool argues for wider select).

---

## 3. Medium-priority ideas (2-3 sentence blurbs)

### 3.1 Top-10 concentrated sleeve (between main diversified 18 and CE champion 5)

Current baseline has two extremes: main diversified 18 positions, CE champion 5 positions. Missing a middle ground — Top-10 would sit between them with ~30% CAGR expected but 25-30% MaxDD (softer than CE's -26.74%). Already mechanical with the CE v2 grid — just widen `concentrated_top_n_candidates` to include 10.

### 3.2 Analyst EPS revision momentum

IBES or FactSet analyst consensus EPS revisions (last 3m slope) have a well-documented ~2% annual premium. Likely complementary to Phase 9 C3 EPS-turn-positive because revisions are forward-looking where C3 is backward-looking (trailing 4Q EPS sign flip).

### 3.3 Options-implied risk overlay

Use per-name 30-day IV (from options chains) to scale position sizes inversely with expected vol. Similar to vol-targeting (Phase 6c, currently OFF) but per-name rather than portfolio-wide. Expected: no CAGR boost, but 1-3pp MaxDD improvement in 2022-like vol regimes.

### 3.4 Insider Form 4 / Rule 10b5-1 flow

13F data (Phase 8 SEC_13F_COLUMNS) is quarterly + lagged 45 days. Insider Form 4 is within 2 days of transaction. Combine: insider buys + low 13F institutional ownership = early-stage institutional onboarding signal. Expected +0.2-0.5pp, but data plumbing is non-trivial (SEC XBRL parsing for Form 4s).

### 3.5 LightGBM ensemble member

Current ensemble: Ridge + LogReg + CatBoost. Add LightGBM (different tree construction, different feature importance). Cheap: use existing X/y pipeline. Expected: small gain from disagreement reducing overfit. ~2-3 days engineering.

### 3.6 Sentiment / alternative data (exploratory)

News sentiment (GDELT), earnings call transcripts (Seeking Alpha, FactSet), Reddit WSB mentions. High noise, high data cost. Only worth attempting if (a) free data source identified, (b) ML pipeline already robust. Defer to Phase 11.

---

## 4. Prioritization rubric

When Stage 5 refactor ships and it's time to pick the next feature, apply:

```
for idea in shortlist:
    score = (expected_cagr_gain_pp / work_days) * refactor_leverage_multiplier
    # refactor_leverage_multiplier: 2.0 if touches walk-forward (refactor helps most there)
    #                               1.0 if pure signal (refactor neutral)
    if idea.data_dependency == "new_free_source": score *= 0.5  # defer until after easier wins
    if idea.risk == "HIGH" and baseline.cagr > 0.25: score *= 0.7  # don't gamble when winning
sort desc; take top 1 for first A/B.
```

Initial ranking under this rubric (assuming CAGR gain estimates midpoint):
1. Quarterly rebalance: 0.5 / 1 * 1.0 = **0.50**
2. Phase 8e: 1.5 / 12 * 2.0 = **0.25**
3. Top-10 concentrated: 2.0 / 1.5 * 1.0 = **1.33** (actually highest by rubric!)
4. LightGBM: 0.25 / 2.5 * 1.0 = **0.10**
5. R2000: 1.0 / 5 * 1.0 * 0.5 (new data) = **0.10**
6. Analyst revision: 0.55 / 2.5 * 1.0 * 0.5 = **0.11**

→ **Suggested order post-refactor: Top-10 concentrated (quick win) → Quarterly rebalance → Phase 8e → R2000 → the rest.**

But this is just rubric output; judgment overrides. E.g. if the user's *real goal* is "CAGR 40%+", only R2000 or Phase 8e realistically move the needle that far. If the goal is "CAGR 30% with half the turnover", quarterly rebalance is the answer.

---

## 5. What NOT to do (explicit rejections)

- **Crypto correlation signals** — regime already captured in macro_regime_table; marginal.
- **Insider buying volume ratio** — tested in ARCHITECTURE_REVIEW.md, IC ~0.
- **Social media (WSB) position leaderboard** — 2021 memes are over; no persistent alpha.
- **Daily rebalance** — transaction costs eat everything; not implementable in retail accounts.
- **More signals for their own sake** — REFACTOR_PLAN.md Stage 6 (Subtractive) goes the OTHER way: drop 153 zero-IC factors. Adding more noise hurts.
- **Options strategies (covered calls, cash-secured puts)** — fundamentally different product; not the stock-picking problem.

---

## 6. Decision log

Entries go here when an idea is picked up, A/B'd, and shipped (or rejected).

| Date | Idea | Verdict | Metrics vs baseline |
|---|---|---|---|
| — | — | — | — |

---

## 7. How to use this memo in a fresh session

1. Read `SESSION_HANDOFF.md` first — current state of refactor.
2. If refactor (Stages 3d + 4 + 5 + 6) is done → read this file + `ARCHITECTURE_REVIEW.md` §6b sleeve taxonomy notes.
3. Pick the highest-ranked idea that matches the user's stated goal.
4. Scaffold A/B against current baseline. Ship gate is ΔCAGR ≥ +0.5pp AND Sharpe ≥ -0.05 AND MaxDD ≥ -3pp (same as Phase 9).
5. Update §6 decision log when verdict is in.

---

**NOT A ROADMAP**. Ideas here may be reordered, dropped, or replaced by better ones. The refactor is the guarantee of cheap iteration; this memo is the inbox of what to try first.

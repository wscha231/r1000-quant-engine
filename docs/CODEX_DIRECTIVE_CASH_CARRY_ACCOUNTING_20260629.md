# Codex Directive — Cash Carry Accounting Realism (broker ledger)

> Author: Claude Code (web), 2026-06-29. Decision-maker synthesis merged + technically corrected.
> Companions: `docs/CODEX_MEASUREMENT_PROTOCOL.md`, `docs/CODEX_WORK_ORDER_CONC_CAGR_BULL_FLOOR_20260629.md`.

## 0. Why (verified in code)

`run_broker_ledger_replay.py` marks equities at **adjusted close** (`load_price_series`,
`run_weekly_evaluation.py:80` prefers `Adj Close`), so **stock/ETF dividends ARE in returns** via the
total-return price path. But `LedgerState.cash` only changes on buys/sells — **idle cash earns 0%**. With
Concentrated avg cash ≈ 40.5%, the 0%-cash assumption is an unrealistic pessimism, not just strategy drag
(a real account holds MMF / T-bills at the short rate). This is a **cash accounting realism correction**, NOT
a new alpha — measure it first, then bull-floor reduces the cash itself.

## Corrections vs the initial draft (read first)

1. **Day-count default must be 365 (ACT/365), not 252.** Cash interest accrues on **calendar days incl.
   weekends/holidays**. The equity curve is marked on trading days (~1777 marks / 7.06y); accrue at each mark
   on the **calendar days elapsed since the previous mark / 365**. A 252 trading-day basis drops weekend
   accrual (~30% under-credit) and mismatches the DGS3MO investment-basis (BEY) quote.
2. **Rate is in percent** (DGS3MO 3.83 = 3.83%) → divide by 100 before use.
3. **Reuse existing FRED infra — do not invent a new file path.** Add `"dgs3mo": "DGS3MO"` to
   `MACRO_FRED_SERIES` (`r1000_config.py:432`); `load_fred_series` (`r1000_pipeline.py:4243`) already
   fetches+caches FRED series this way (DGS10 already is). No `data_pit/macro/rates/dgs3mo.parquet` invention.
4. **Negative-cash guard:** credit `max(state.cash, 0) * daily_rate` only (long-only cash-funded book).
5. **Benchmark unchanged:** SPY is fully invested → no carry applied; `excess_cagr` rises honestly.

## Non-negotiables

Default OFF. No production promotion. No live trading. No fullrun required for first measurement. No future
rates (PIT). Baseline and treatment measured under the SAME cash-carry mode. Keep the zero-yield number
side-by-side. New `metric_mode` clearly labeled.

## Task 0 — PIT short-rate source (prerequisite)

- Add `"dgs3mo": "DGS3MO"` (optionally `"dgs1mo": "DGS1MO"`) to `MACRO_FRED_SERIES`.
- Pull via the existing `load_fred_series` path; cache as the other `fred_*` series.
- PIT rule: a rate row is usable at mark date `D` only if `available_from <= D`; DGS3MO publishes next
  business day → `available_from = rate_date + 1 business day` (or `--cash-rate-lag-days`, default 1).
  Forward-fill from past only; never backfill a future rate.

## Task 1 — Cash carry in the broker ledger

File: `tools/run_broker_ledger_replay.py`. CLI/env (default OFF):
- `--cash-carry-mode {none,risk_free_rate,cash_proxy_etf}` / `R1000_BROKER_CASH_CARRY_ENABLED=1`
- `--cash-rate-source DGS3MO` / `R1000_BROKER_CASH_RATE_SOURCE`
- `--cash-rate-lag-days 1`
- `--cash-carry-haircut-bps 50` (MMF/sweep friction; 0 = optimistic bound)
- `--cash-carry-day-count 365` **(default 365; ACT/365. Do NOT default 252.)**

`LedgerState` += `cash_interest_accrued`, `last_cash_accrual_date`. Deterministic per mark date:
1. accrue: `days = (mark_date - last_cash_accrual_date).days` (calendar);
   `daily = (max(rate_pct,0)/100 - haircut_bps/1e4) / day_count`;
   `credit = max(state.cash, 0) * daily * days`; `state.cash += credit`; `cash_interest_accrued += credit`;
   set `last_cash_accrual_date = mark_date`.
2. process fills/orders for the date. 3. mark equity. (Accrue BEFORE fills; document the order.)

## Task 2 — Metrics + equity-curve fields

`metrics.json`: `cash_carry_mode`, `cash_rate_source`, `cash_carry_haircut_bps`, `cash_carry_day_count`,
`cash_interest_accrued_usd`, `cash_interest_accrued_pct_starting_capital`, `cash_carry_cagr_contribution_pp`,
and `metric_mode = broker_ledger_next_close_cash_carry` when enabled (else unchanged).
`equity_curve.csv`: `cash_interest_daily`, `cash_interest_accrued_to_date`, `cash_rate_used`,
`cash_rate_available_from`.

## Task 3 — Measure on artifact 28360773460 (no fullrun)

Re-run policy replay + broker ledger only. Arms:
A. `cash_carry_mode=none` (current zero-yield).
B. `cash_carry_mode=risk_free_rate, source=DGS3MO, haircut=50bps, day_count=365`.

Report for BOTH sleeves: CAGR / MaxDD / Sharpe before→after, `cash_interest_accrued`, avg_cash,
`cash_carry_cagr_contribution_pp`, and the effect on Concentrated's +3.34pp gap. **Also report tier-2
`is_cagr_min` and `oos_is_cagr_ratio` before→after** — carry should lift IS CAGR and modestly lower OOS/IS.

This is an **accounting baseline correction, not an alpha delta.** After adoption, every future A/B uses the
cash-carry baseline on BOTH arms.

## Task 4 — Cash proxy ETF A/B (optional, second)

`tools/run_cash_proxy_broker_ab.py`. Replace CASH rows with BIL/SGOV/SHV when history covers the 7Y window
(SGOV is short-listed; BIL has longer history). Preserve stock weights; ETF marked at Adj Close (distributions
included). Arms: `cash_zero | cash_carry_dgs3mo | cash_proxy_BIL | cash_proxy_SGOV(if_history)`. Acceptance:
MaxDD must not worsen materially; CAGR ≈ cash carry; mark `blocked_short_history` if ETF history is incomplete.

## Task 5 — Gate-first CAGR surplus bonus (config selection only, NOT live)

Hard gates FIRST: MaxDD ≥ −0.25 AND CAGR ≥ target AND Main non-regress AND OOS/IS not worse AND no
single-name/single-era dependence. Only then score a **capped** surplus bonus. A high CAGR NEVER offsets an
MaxDD failure. Reference shape: `if max_dd < -0.25: -inf; elif cagr < target: -100 + 100*(cagr-target);
else: 100 + capped_cagr_bonus + capped_mdd_cushion_bonus - overfit_penalty - concentration_penalty`.

## Task 6 — Reserve vs satellite taxonomy (do NOT mix)

- **Reserve (cash-equivalent):** CASH + DGS3MO carry, BIL/SGOV/SHV. ← cash substitute lives ONLY here.
- **Defensive satellite (own drawdown/correlation):** GLD, LQD/VCIT, low-vol/dividend equity. NOT a cash
  substitute — Concentrated MaxDD has only 0.88pp headroom to −25%; corporate bonds/gold/blue-chips add
  correlated drawdown (2022-style) and can break the gate. Treat as a separate, strictly-measured risk sleeve.
- **Growth:** AI Capex / momentum leaders / semis.

## Task 7 — Bull-floor AFTER cash-carry baseline

Compare **cash-carry baseline vs cash-carry bull-floor** (never zero-yield vs cash-carry bull-floor). Reject
if Conc MaxDD < −25%, Main regresses, gain is 2025/one-ticker only, or OOS/IS worsens.

## Task 8 — Tests

`tests/broker_cash_carry_smoke.py`: default-off preserves EXACT old metrics; positive cash accrues over
calendar days (weekend gap credited); rate units (%/100) correct; no future rate used (PIT); forward-fill from
past only; `metric_mode` flips when enabled; dividends still via Adj Close (not via cash interest); negative
cash not credited. `tests/cagr_surplus_bonus_scoring_smoke.py`: bonus never crowns an MaxDD violator.
Validate: `python -m py_compile tools/run_broker_ledger_replay.py && python tests/broker_cash_carry_smoke.py`.

## End state

Cash zero-yield pessimism removed and made explicit/measurable; future bull-floor & selection A/Bs use an
apples-to-apples cash-carry baseline; production stays blocked until `pit_universe_label_clean`.

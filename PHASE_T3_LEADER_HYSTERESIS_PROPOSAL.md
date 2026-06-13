# Stage T3 Proposal — Production Leader Hysteresis

## Why this exists

Stage T1 (leader_lifecycle_audit) measured the 20260613 broker-ledger run:
both Main and Concentrated pass `leader_capture` (46.6% / 42.0%) and
`premature_sell_excess_return_126d` (-2% gate met by both), but BOTH portfolios
fail the holding-period gates:

| portfolio | median_holding | pct_held_180d+ | pct_held_365d+ |
|---|---:|---:|---:|
| Main | 58 d (gate 60) | 2.46% (gate 15%) | **0%** (gate 5%) |
| Concentrated | **33 d** (gate 60) | 0.76% (gate 15%) | **0%** (gate 5%) |

The system finds real leaders and exits without leaving money on the table
in the 126-day window — but it does not let any leader compound for a year.

Stage T2 (subdaily_exit_compare) attributed part of the CAGR drag to
hard_stop firing too tightly (`-8%` triggers 95% of overlay exits). T2b is
sweeping the stop grid in parallel. But the dominant root cause of short
holding periods is not the sub-monthly stops — it is the production monthly
rebalance itself overwriting the book every month.

## Diagnosis: who actually writes `main_monthly_weights.csv` in backtest

- `tools/run_market_leader_challenger.py` and
  `tools/run_integrated_theme_leader_crisis_replay.py` already use
  `r1000_market_leader_engine.select_market_leader_targets(scored, variant,
  prev_holdings=prev_weights)` — this selector implements a
  `prev_candidates` vs `new_candidates` split that prefers previously-held
  names whose `leader_state ∈ PREVIOUS_HOLD_ALLOWED_STATES = {HOLD,
  SHAKEOUT_GUARD, WARNING}`.
- The production backtest path is different: `r1000_pipeline.py` writes
  `main_monthly_weights.csv` from `bt.holdings.to_csv(...)` at line ~17210.
  `bt` is the backtester whose monthly portfolio assembly happens inside the
  same module's `Backtester`/scoring path — and **that path does not call
  `select_market_leader_targets`**. Every rebalance month, the production
  backtester rebuilds the book from current-month scores with no carry-over
  signal from the prior month.
- `build_latest_portfolio` (line 15785) is the live-trading function that
  reads `previous_live_policy` and applies `scheduled_hold_active` gating —
  but that lives in the live-decision lane, not in the historical backtest.

So the audit gap is: the challenger/replay tools have hysteresis,
the production backtest does not, and the production backtest is the source
of every metric we ship.

## Proposal (research-only by default)

Add a single, env-gated hysteresis hook to the production backtest's monthly
portfolio assembly. Concretely:

1. Track `prior_month_holdings: dict[ticker, weight]` across rebalance dates
   in the backtester loop.
2. Before applying current-month score ranking, partition candidates:
   - `prev_keep` — tickers in `prior_month_holdings` AND
     `leader_state ∈ {HOLD, SHAKEOUT_GUARD, WARNING}` AND
     `score_percentile_drop_vs_prior <= retention_band_pct`
     (default `retention_band_pct = 0.30`).
   - `new_entries` — everyone else, ranked normally.
3. Fill the target_n slots from `prev_keep` first (preserving their prior
   weight up to the single-cap), then top up with `new_entries` by score.
4. Wire `PHASE_T3_LEADER_HYSTERESIS_ENABLED` env toggle (default `auto =
   False` until measured). When disabled, behavior is unchanged.

This mirrors the challenger-side selector but lives in the production
backtest loop so `main_monthly_weights.csv` reflects the carry-over.

## Why this is the right shape

- Minimal surface area: one new helper + one env-gated branch in the
  backtest monthly loop. No model changes, no signal changes.
- Already proven harmless in challenger lane: same logic shape, just lifted
  into production.
- Directly addresses the failing gates: `median_holding`,
  `pct_held_180d_plus`, `pct_held_365d_plus`, and `reentry_capture` (because
  holding longer means fewer forced re-entries).
- Composable with T2/T2b: the sub-monthly stop sweep tunes when forced
  exits fire INTRA-month; T3 tunes whether the monthly rebalance flushes a
  still-good leader. Different layers, independent.

## Risks + a/b plan

- Risk: in a strong-momentum bull tape, holding stale leaders past their
  prime caps the score-rotation alpha. The retention band of 30% is a guess;
  it has to be measured.
- Risk: if a leader's `leader_state` flips to WARNING the gate keeps it
  anyway. In late-stage crisis tape this could deepen MaxDD.
- A/B plan:
  1. Implement the hook with the toggle DEFAULT-OFF.
  2. Add a smoke test that synthesizes a 12-month book where ticker A's
     score percentile drops 20% between months 1 and 2; with the toggle on
     A is retained, with it off A is replaced.
  3. Run a single FULL rebuild with `PHASE_T3_LEADER_HYSTERESIS_ENABLED=1`,
     compare T1 gates and broker CAGR/MDD vs the toggle-off baseline (the
     just-completed `27457206698`).
  4. Promote to default only if T1 holding-period gates improve AND broker
     CAGR delta is `>= -1.0pp` AND MaxDD delta `>= -3pp`.

## Open questions to resolve during implementation

1. Where exactly is the backtest's monthly portfolio assembly? `bt.holdings`
   is the output, but we need the function that builds each month's
   `selected_for_portfolio` set so the hook plugs in there.
2. Does the retention band compare against percentile of the current-month
   score column, or against the score sleeve label? The simpler form is
   percentile within the current-month ranked universe.
3. How does this interact with `scheduled_hold_active` in
   `build_latest_portfolio`? They should not double-apply for the live row.

## Sequencing vs T2/T2b/regression-tracking

- T2b grid sweep is dispatched against `source_run_id=27457206698`. Its
  workflow needs master-branch merge before GitHub's Actions index lists
  it — the feature-branch dispatch returned 404. The composite ranker is
  fully unit-tested already (7/7) so the answer it produces will be
  trustworthy as soon as the workflow runs.
- A new FULL rebuild is dispatched on `ea1bb874` (T1/T2/T2b sidecar wiring
  included) — its T1 + T2 artefacts will land in `outputs/` automatically.
- Regression tracking found that `20260610 -> 20260613` cash-policy
  evolution was the INTENDED big mover (avg_cash 0%/6% -> 27%/42%, CAGR
  +13.7pp Main, +13.4pp Conc, MDD +6.6pp/+12.4pp better). It is not a
  regression to revert. The remaining gap vs CLAUDE.md baseline
  (`27086825471` 35.22%/-23.24% Main, 50.75%/-22.99% Conc) is small enough
  that T2b's stop tune + T3 hysteresis are the right levers, not a code
  revert.

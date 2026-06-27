# AlphaOps vNext System Direction Update - 2026-06-27

## Current Goal

Do not add more broad levers until they prove an applied, broker-ledger edge.
The current system direction is:

1. Keep the clean `research_7y` broker-ledger baseline as the only mechanical
   performance reference.
2. Keep `pit_universe_label_clean=false` as a production blocker.
3. Use cheap target-book or broker-ledger A/B screens before any fullrun.
4. Discard broad levers that fail, but retain narrowly useful diagnostics.
5. Move only one scoped candidate at a time into broker-ledger proof.

The active research target is now fixed as:

- Concentrated CAGR >= 50%
- Concentrated MDD >= -25%

This is a research target until PIT membership is clean. It is not production
promotion authority.

## Latest Closed Work

### Score-Sizing

Verdict: **parked research infrastructure, no policy candidate**.

The cap-safe score-sizing broker A/B rejected both policy-safe arms:

- `blend75_rank_power1_5_cap30`: CAGR -0.76pp, MDD -0.12pp, cap breach 0.
- `blend50_rank_power1_5_cap30`: CAGR -0.25pp, MDD +0.48pp, cap breach 0.

The uncapped arm had a small positive signal but breached the single-name cap 30
times, so it is alpha evidence only and not policy.

### Baseline Reproducibility

The official clean-7Y Concentrated result and local score-sizing A/B baseline
showed a small drift. The new reproducibility audit explains it as an end-date
mismatch:

- official end date: `2026-06-23`
- A/B baseline end date: `2026-06-25`
- metric mode mismatch: false
- window mismatch > 0.03y: false
- target-book source unexplained: false
- score-sizing decision changed: false

This drift should be tracked, but it does not change the score-sizing reject.

## Green/Bull Gross-Floor Sweep

Tool:

```bash
python tools/run_lever_sweep.py \
  --latest-run artifacts/28074476465/outputs \
  --candidate-book artifacts/28074476465/outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv \
  --price-cache artifacts/28074476465/cache_prices \
  --output-dir artifacts/28074476465/green_bull_gross_floor_sweep_20260627 \
  --skip-daily-stop \
  --conc-gross-floors 0.0,0.7,0.8,0.9 \
  --cost-bps 25 \
  --max-fill-lag-days 7
```

Result: **reject broad gross floor**.

| Floor | CAGR | MDD | Sharpe | Avg Cash | Applied months |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0.0 | 47.90% | -26.46% | 1.451 | 42.67% | 0 |
| 0.7 | 46.23% | -34.90% | 1.397 | 39.89% | 19 |
| 0.8 | 45.40% | -37.07% | 1.363 | 38.45% | 29 |
| 0.9 | 44.36% | -39.69% | 1.320 | 36.56% | 33 |

Interpretation:

- The lever fired, so this is not a wiring no-op.
- It reduced cash, but it worsened both CAGR and MDD.
- The damage is concentrated in the IS/stress period; OOS strength does not
  rescue the full-window gate.
- Broad green/bull gross exposure is not the next viable route.

## Updated Direction

### Discard

- Broad Concentrated gross floor.
- Cap-safe score sizing as implemented.
- SHAKEOUT until `applied_count > 0` appears on current artifacts.
- Dropped-leader rescue unless segment candidate evidence reappears.

### Keep as Infrastructure

- Score-sizing hook and broker A/B harness, default OFF.
- Baseline reproducibility audit.
- PIT membership audit/producer.
- Fusion candidate review, but only as a queue generator, not as a policy.

### Next Candidate Class

The next high-value direction is **narrow, PIT-confirmed winner hold /
earnings-event confirmation**, not broad exposure:

1. Event/earnings guidance evidence layer:
   - PIT `available_from <= rebalance_date`.
   - accepted timestamps, not report periods.
   - attach event strength to candidate/holding rows.
   - cheap screen before any hook.
2. Winner hold-duration screen:
   - identify where winners were sold too early,
   - require ex-ante PIT confirmation,
   - avoid hardcoded tickers/dates/sectors,
   - broker A/B only if `applied_count > 0`.
3. Concentrated sizing only if cap-safe and event/hold predicates create a
   better candidate subset than raw score rank.

## Fullrun Policy

No fullrun should be dispatched from either latest tested lever:

- score-sizing: cap-safe policy candidates empty.
- broad gross floor: all non-control arms fail broker-ledger gates.

Next fullrun requires a cheap broker-ledger screen with:

- `broker_ledger_next_close`,
- valid 7Y window,
- `applied_count > 0`,
- target-specific improvement,
- no MDD break,
- OOS non-collapse,
- no production promotion claim while `pit_universe_label_clean=false`.

## Immediate Next Step

Build or reuse a PIT-safe event/earnings evidence screen. The output must answer
one question before any hook is written:

> Did earnings/guidance-confirmed leaders that were held or retained outperform
> similar unconfirmed leaders on broker-ledger-relevant windows without worsening
> drawdown?

If the cheap screen does not show this, stop and do not add another policy hook.

## Earnings / Guidance Hold Screen Result

Tool:

```bash
python tools/run_earnings_guidance_hold_screen.py \
  --latest-run artifacts/28074476465/outputs \
  --output-dir artifacts/28074476465/earnings_guidance_hold_screen_20260627
```

Result: **screen pass for a narrow hook candidate**.

Primary predicate:

```text
portfolio = concentrated
pit_leader_hold_candidate = true
actual_results_score > 0
```

This is PIT-observable at the prior rebalance row and does not use forward
returns for live ranking. Forward 126d returns remain audit labels only.

| Split | Rows | Positive Rate | Mean 126d Excess | Median |
| --- | ---: | ---: | ---: | ---: |
| Full | 52 | 53.85% | +10.39% | +3.45% |
| IS before 2024-06-03 | 41 | 53.66% | +9.83% | +5.26% |
| OOS from 2024-06-03 | 11 | 54.55% | +12.50% | +0.29% |

Interpretation:

- Broad hold-duration rescue was negative and remains rejected.
- A narrow actual-results-confirmed hold predicate is the first surviving
  candidate after score-sizing and gross-floor rejects.
- This does not prove CAGR/MDD improvement yet. It only permits the next step:
  a default-OFF target-book hook candidate and cheap broker A/B.

Next required hook design:

- default OFF,
- Concentrated only,
- prior holding only,
- require `actual_results_score > 0`,
- require existing PIT leader hold predicate,
- no ticker/date/sector hardcoding,
- prove `applied_count > 0` before broker delta,
- accept only if broker-ledger moves toward CAGR >= 50% and MDD >= -25%.

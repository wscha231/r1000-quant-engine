# Fable 5 Review Packet - AlphaOps vNext - 2026-07-02

## Purpose

This is the single packet to send to an expensive external reviewer. The goal is
not to brainstorm broadly. The goal is to get a gate-first verdict on what to do
after cash-carry passed and broad gross/hold/sizing variants failed.

## Non-Negotiables

- No production promotion.
- No live trading.
- No proxy 8Y/10Y.
- No fullrun unless a cheap replay-stage candidate first reaches the mission gate.
- `pit_universe_label_clean=false` remains a hard production blocker.
- Cash-carry is research/accounting until the user explicitly approves a formal accounting contract.
- Forward returns are audit labels only, never live ranking inputs.

## Current Branch / Commit

```text
branch: codex/integration-fullrun-clean-20260630
latest pushed commit before this packet: d3c37169 feat: add fixed-book phase2 concentrated replays
```

Important code/doc paths:

```text
tools/run_broker_ledger_replay.py
tools/run_fixed_book_hold_exit_timing_ab.py
tools/run_fixed_book_concentrated_sizing_ab.py
tools/run_ai_capex_bucket_revision_audit.py
docs/CODEX_BULL_FLOOR_CLOSEOUT_20260702.md
docs/CODEX_PHASE2_CONCENTRATED_GAP_REPORT_20260702.md
outputs/phase2_concentrated_gap/summary.json
```

## Latest Confirmed Facts

### Phase 1

Cash-carry is a research accounting win:

| Sleeve | Baseline | Cash-carry | Delta |
|---|---:|---:|---:|
| Main | 34.27% / -24.11% | 35.11% / -23.99% | +0.84pp CAGR, MDD better |
| Concentrated | 47.46% / -24.08% | 48.83% / -23.79% | +1.37pp CAGR, MDD better |

Broad bull-floor is rejected:

| Arm | CAGR | MaxDD | Verdict |
|---|---:|---:|---|
| cash-carry control | 48.83% | -23.79% | control |
| floor 0.85 | 45.83% | -32.03% | reject |
| floor 0.90 | 45.22% | -33.53% | reject |
| floor 0.95 | 44.71% | -34.90% | reject |

Interpretation:

```text
Concentrated cash is load-bearing MDD defense.
Do not broadly redeploy cash into the same small stock set.
```

### Replay-End Clamp / Skip Guard

The replay now explicitly records skipped signal dates when next-close fill would
occur after the official replay end.

Implemented fields:

```text
replay_end_filtered_target_row_count
replay_end_filtered_target_date_count
replay_end_skipped_rebalance_count
replay_end_skipped_signal_dates
actual_equity_curve_end_date
end_date_matches_official
```

Smoke test:

```text
signal date: 2026-01-06
next close fill: 2026-01-07
replay_end_date: 2026-01-06
expected: no 2026-01-07 trade, skipped signal date recorded
```

### Phase 2 Fixed Official-Book A/B

Baseline:

```text
Concentrated cash-carry: 48.83% CAGR / -23.79% MaxDD / 1.445 Sharpe
Remaining gap: +1.17pp CAGR
```

Hold/exit timing A/B:

| Arm | Applied | CAGR | MaxDD | Verdict |
|---|---:|---:|---:|---|
| baseline_cash_carry | 0 | 48.83% | -23.79% | control |
| delay_target_exit_one_cycle | 223 | 43.16% | -31.59% | reject |
| delay_target_exit_only_if_leader | 216 | 43.05% | -31.60% | reject |
| partial_replace_50 | 223 | 46.97% | -27.40% | reject |
| accelerate_exit_if_deteriorating | 0 | 48.83% | -23.79% | no-op |
| keep_winner_if_rs_positive | 216 | 43.05% | -31.60% | reject |

Cap-safe sizing A/B:

| Arm | Applied | Cap breaches | CAGR | MaxDD | Verdict |
|---|---:|---:|---:|---:|---|
| baseline_cash_carry | 0 | 0 | 48.83% | -23.79% | control |
| vol_adjusted_weight | 453 | 0 | 38.00% | -20.21% | reject |
| max_drawdown_contribution_capped | 453 | 0 | 40.55% | -21.26% | reject |
| rs_plus_low_vol_blend | 453 | 0 | 41.38% | -24.13% | reject |
| winner_pyramiding_only_if_positive_rs | 453 | 0 | 41.75% | -24.40% | reject |
| equal_weight_with_cash_preserved | 453 | 0 | 40.66% | -21.31% | reject |

Interpretation:

```text
The missing +1.17pp is not broad gross, broad hold-delay, or cap-safe reshuffling.
Current Concentrated right-tail returns are load-bearing; flattening them hurts CAGR.
```

### AI Capex / EPS Diagnostics

Cheap screen, not broker evidence:

| Group | Split | Count | Mean 126d excess | Positive rate |
|---|---|---:|---:|---:|
| AI bottleneck + revision positive + momentum | full | 98 | +9.10% | 63.27% |
| AI bottleneck + revision positive + momentum | OOS | 37 | +14.23% | 72.97% |
| AI bottleneck + revision nonpositive + momentum | full | 56 | +10.61% | 62.50% |
| AI bottleneck + revision nonpositive + momentum | OOS | 34 | +17.10% | 73.53% |

Dedicated bucket audit:

| Bucket | Rows | Unique tickers | Avg fwd return audit | Weighted fwd audit |
|---|---:|---:|---:|---:|
| AI_OTHER | 305 | 132 | +2.51% | 1.366 |
| AI_STORAGE | 38 | 10 | +16.28% | 1.056 |
| AI_CONNECT | 21 | 2 | +19.80% | 0.714 |
| AI_COMPUTE | 67 | 17 | +3.70% | 0.349 |
| AI_GRID | 5 | 2 | +14.94% | 0.116 |
| AI_POWER | 20 | 7 | -0.43% | 0.029 |

Caveat:

```text
Taxonomy is diagnostic. It is not yet a production-grade feed.
AI_STORAGE and AI_CONNECT look relevant, but AI_OTHER remains materially important.
True PIT EPS/guidance feed is still missing.
```

### Target-Generation Control Reproduction

Known issue:

```text
Regenerated vNext target book still does not exactly reproduce the official artifact.
Date mismatch was fixed by append clamp, but ticker mismatch remains on 25 dates and max weight delta is about 0.285.
```

Implication:

```text
Selection-side regenerated target-book A/B is diagnostic only until control reproduction is exact or near-exact.
Fixed official-book transformation A/B is acceptable replay evidence.
```

## Questions For Fable 5

Please answer gate-first, with no broad brainstorming.

1. Is it reasonable to adopt `broker_ledger_next_close_cash_carry` as the official research baseline, while keeping production blocked until `pit_universe_label_clean=true`?
2. Given broad bull-floor, broad hold-delay, and cap-safe sizing all failed, is the correct next alpha path selection/replacement quality rather than more timing/sizing variants?
3. Does the AI Capex diagnostic justify building one default-OFF replacement-quality hook, or is the taxonomy too noisy without a true PIT EPS/guidance feed?
4. If one hook is justified, what should it be exactly?
   - Candidate: narrow replacement-quality rule for AI_STORAGE / AI_CONNECT / high-RS AI bottleneck names, requiring PIT momentum plus EPS/guidance or actual-results confirmation.
   - Constraint: no hardcoded tickers, no forward labels, no production activation.
5. Should we stop all regenerated selection-side A/B until target-generation control reproduction is fixed?
6. Is there any reason to run a fullrun now?
   - Current Codex answer: no. Fullrun only if a replay-stage candidate reaches Concentrated >=50% CAGR and MaxDD >= -25%, with Main non-regression and OOS/era stability.
7. What is the single highest-value next engineering task?
   - Option A: target-generation control reproduction root cause.
   - Option B: PIT EPS/guidance feed and AI bucket cleanup.
   - Option C: one default-OFF replacement-quality hook using fixed official-book evidence first.

## Expected Output Format

```text
Verdict:
- cash-carry baseline: accept / reject / conditionally accept
- Phase 2 fixed-book timing/sizing: closed / continue
- AI Capex replacement hook: proceed / wait for data feed / reject
- fullrun now: yes / no

Top 3 next actions:
1.
2.
3.

Risks / blockers:
-

Any correction to Codex's interpretation:
-
```

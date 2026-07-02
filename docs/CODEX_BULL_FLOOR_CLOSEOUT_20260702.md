# Bull-Floor Closeout - 2026-07-02

## Verdict

Broad Concentrated bull-floor / gross-floor is rejected for the `28436307420`
official-book path.

This is negative research evidence, not a production result.

## Reference

- Reference fullrun: `28436307420`
- Local artifact root: `artifacts/fullrun_28436307420/official/outputs`
- Official concentrated target book: `artifacts/fullrun_28436307420/official/outputs/alphaops_vnext/official_concentrated_target_book.csv`
- Fresh replay cache: `outputs/phase1_replay_goal_test/cache_prices`
- Bull-floor A/B output: `outputs/phase1_replay_goal_test/official_book_bull_floor_broker_ab`
- Replay end: `2026-06-29`
- Metric mode: `broker_ledger_next_close_cash_carry`
- Production status: blocked by `pit_universe_label_clean=false`

## Results

| Floor | Lifted dates | CAGR | MaxDD | Sharpe | Avg cash | Verdict |
|---:|---:|---:|---:|---:|---:|---|
| 0.00 | 0 | 48.83% | -23.79% | 1.445 | 40.23% | control |
| 0.85 | 11 | 45.83% | -32.03% | 1.355 | 37.25% | reject |
| 0.90 | 13 | 45.22% | -33.53% | 1.334 | 36.53% | reject |
| 0.95 | 16 | 44.71% | -34.90% | 1.315 | 35.73% | reject |

## Interpretation

The harness was checked for the failure-sensitive conditions:

- It lifts only in bull regimes.
- It respects the same capped water-fill logic and per-name caps used by the production overlay implementation.
- The fixed official-book control reproduced the cash-carry baseline.

The result shows that Concentrated cash is not simple idle cash. In this
strategy, a substantial portion of cash is load-bearing drawdown defense.
Broadly forcing stock exposure into the existing small leader set raises
idiosyncratic and theme concentration risk enough to reduce CAGR and materially
worsen MaxDD.

## Closed Hypothesis

Rejected:

```text
In bull regimes, raise Concentrated stock gross exposure to 85-95% to close the CAGR gap.
```

Reason:

```text
The floor reduces cash, but both CAGR and MaxDD get worse.
```

## Do Not Repeat

Do not run more broad gross-floor variants such as:

- 0.80 / 0.82 / 0.88 floors
- only-strong-bull broad floors
- broad green cash redeploy floors
- cash-to-equity conversion without a narrower stock-selection or timing predicate

Any future cash redeployment hypothesis must be narrow and must explain why it
will avoid the observed drawdown explosion.

## Next Direction

The remaining gap after cash-carry is approximately:

```text
Concentrated: 48.83% -> 50.00% = +1.17pp CAGR
```

The next work should target decision quality:

- fixed official-book hold / exit timing
- replacement timing
- cap-safe sizing within the selected set
- AI-capex bucket and earnings/revision confirmation

No fullrun is justified by bull-floor.

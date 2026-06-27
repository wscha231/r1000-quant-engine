# Re-Entry Timing Whipsaw Screen Report - 2026-06-28

## Verdict

The re-entry timing screen passes as the next measurement candidate.

This is not production evidence and not a fullrun trigger. It means a
default-OFF review-only re-entry candidate hook is worth designing next.

## Why This Is Not Cheating

The screen uses every Concentrated broker SELL event, not only names that later
worked.

Trigger rules use only the PIT price path after each sell:

- reclaim sell price +5%
- reclaim sell price +10%
- rebound 8% from post-sell trough
- close above prior 20-day high

Future returns and actual later rebuys are audit labels only. They are not used
to fire triggers.

## Inputs

Artifact:

- `artifacts/28074476465/outputs`

Trades:

- `artifacts/28074476465/outputs/broker_replay/concentrated/trades.csv`

Price cache:

- `artifacts/28074476465/cache_prices`

Command:

```bash
python tools/run_reentry_timing_whipsaw_screen.py \
  --latest-run artifacts/28074476465/outputs \
  --price-cache artifacts/28074476465/cache_prices \
  --output-dir artifacts/28074476465/reentry_timing_whipsaw_screen_20260628
```

## Results

Total SELL events:

- 330

Trigger summary:

| Trigger | Hits | Saved premium positive rate | Median saved premium | 20d loss rate | Verdict |
|---|---:|---:|---:|---:|---|
| reclaim_5pct | 258 | 95.89% | 26.44% | 39.92% | pass |
| reclaim_10pct | 221 | 90.91% | 19.44% | 43.44% | pass |
| trough_rebound_8pct | 323 | 93.90% | 28.30% | 42.41% | pass |
| close_above_20d_high | 320 | 96.34% | 31.08% | 42.81% | pass |

Screen-level verdict:

- `screen_pass_design_default_off_reentry_hook`

## Interpretation

The earlier hold-extension attempts failed because they protected too many bad
incumbents.

This screen targets a different failure:

- the system sells a leader,
- price later reclaims strength,
- the official monthly policy often waits until a much higher rebuy price.

The signal is not yet a strategy. It is a candidate for a review-only re-entry
hook.

## Next Implementation

Design a default-OFF hook that emits re-entry candidates only:

- no automatic live trade
- Concentrated first
- review-only output
- no target mutation until broker A/B
- no fullrun until cheap broker replay shows improvement

Hook acceptance gate:

- `applied_count > 0`
- broker-ledger Concentrated CAGR improves by >= +0.50pp
- MaxDD does not worsen
- OOS does not collapse
- no hardcoded tickers, dates, sectors, or future labels

## Production Boundary

`pit_universe_label_clean=false` still blocks production promotion. Any pass is
research evidence only until PIT membership is clean.

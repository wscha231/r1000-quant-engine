# AlphaOps Pre-Fullrun Review - 2026-05-04

This review records the changes made before the next full rebuild. No full
rebuild was run as part of this update.

## Current Problem

Latest cloud results still do not meet the product-level target:

- Main: CAGR 19.17%, Sharpe 1.084, MaxDD -24.91%, avg cash 6.04%.
- Latest main portfolio cash: 14.00%, despite `cash_target=0.0`.
- Concentrated: CAGR 34.94%, Sharpe 1.376, MaxDD -25.74%.

The main cash drag is not mainly a cash-target problem. It comes from residual
cash after name/sleeve/speculative caps bind. The latest main book held 18
stocks plus 14% cash; several high-growth names were constrained by low
speculative/partial-scout caps.

## Implemented Before Full Rebuild

### 1. Lower Main Cash Drag Candidates

- Reduced manual balanced/growth cash sleeves from 8% to 5%.
- Replaced AI four-sleeve candidates that used 8-14% standing cash with
  3-5% cash growth candidates.
- Removed the hard 8% minimum cash allowance in the AI four-sleeve adaptive
  comparison; it now honors `sleeve_regime_comparison_cash_max`.
- Raised neutral live main single-name fallback cap from 12% to 16%.
- Raised partial-scout/speculative caps:
  - partial scout single-name cap: 4% -> 6%
  - partial scout total cap: 10% -> 18%
  - speculative single-name cap: 4% -> 8%
  - speculative total cap: 15% -> 24%

Intent: deploy residual cash into selected growth leaders instead of leaving
idle cash when regime is not severe risk-off.

### 2. Shake-out vs Distribution

The event study now separates:

- `SHAKEOUT`: fast drawdown, high-volume panic signature, recovery, positive
  forward return.
- `DISTRIBUTION`: partial recovery fails, then lower low; or slow stair-step
  decline with weak relative strength.
- `TRUE_BREAKDOWN`: direct continuation lower or poor forward return.

New diagnostics include half-recovery, lower-low-after-half-recovery,
fast-drop flag, high-volume-panic flag, V-recovery days, and distribution risk
score.

Limitations still not solved: no institutional/foreign flow, no news/disclosure
classification, and no sector co-drawdown filter yet.

### 3. AutoLearning Policy/Value Readiness

`run_autolearning_winner_challenger.py` now:

- reads main avg cash and latest monthly cash;
- flags cash drag and main CAGR gap;
- writes `policy_value_replay.status`;
- generates proposal-only replay grids for:
  - main cash caps: 0%, 3%, 5%, 8%
  - main single-name caps: 18%, 22%, 25%, 33%
  - concentrated single-name caps: 25%, 33%, 40%, 50%
  - shakeout/distribution actions.

This is still proposal-only. It does not auto-promote rules.

## What Is Still Not Proven

- No full rebuild has tested whether lower cash and wider growth caps improve
  CAGR without worsening MaxDD/turnover.
- Shakeout/distribution logic is event-level, not yet a portfolio-level
  value function.
- AutoLearning still proposes challenger policies; it does not yet perform a
  full portfolio policy/value replay by itself.

## Next Fullrun Readout

After the next full rebuild, check:

1. Main latest cash below 8%, unless severe risk-off.
2. Main CAGR versus 19.17% and Phase 15-D/Phase 14 baselines.
3. Main MaxDD does not worsen materially beyond -25%.
4. Concentrated CAGR remains near or above 35%.
5. AutoLearning output reports `policy_value_replay.status`.
6. Shakeout report includes `DISTRIBUTION` counts and action rows.

If CAGR improves but MDD worsens, the next fix should be position-aware exits,
not a return to standing cash.

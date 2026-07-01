# AlphaOps vNext Phase 2 Directive - Concentrated +1.17pp Gap

## Summary

Phase 1 produced the first clean replay-stage answer after run `28436307420`:

- Cash-carry is a real research accounting improvement.
- Main reaches the headline research target under cash-carry.
- Concentrated improves but remains short of the 50% CAGR target.
- Broad bull-floor / gross-floor is rejected.
- No fullrun is justified yet.
- Production remains blocked by `pit_universe_label_clean=false`.

Current research baseline for Phase 2:

| Portfolio | Baseline | + Cash-carry | Interpretation |
|---|---:|---:|---|
| Main | 34.27% / -24.11% | 35.11% / -23.99% | headline research pass |
| Concentrated | 47.46% / -24.08% | 48.83% / -23.79% | still +1.17pp CAGR short |

Bull-floor closeout:

| Floor | Lifted dates | CAGR | MaxDD | Verdict |
|---:|---:|---:|---:|---|
| 0.00 | 0 | 48.83% | -23.79% | control |
| 0.85 | 11 | 45.83% | -32.03% | reject |
| 0.90 | 13 | 45.22% | -33.53% | reject |
| 0.95 | 16 | 44.71% | -34.90% | reject |

Interpretation:

> Concentrated cash is not pure idle drag. Broadly forcing bull-regime gross exposure into the same small stock set destroys drawdown and lowers CAGR. The remaining +1.17pp problem is not solved by reducing cash. It is a decision-quality problem: which leaders to hold, when to rotate, how to size, and whether the engine is missing stronger AI-capex / earnings-confirmed leaders.

## Non-Negotiables

- No production promotion.
- No live trading.
- No proxy 8Y/10Y.
- No fullrun until a replay-stage candidate passes the gates below.
- No partial-year annualized proof.
- No broad bull-floor / gross-floor revival without a new, narrow hypothesis.
- Cash-carry remains research-only unless a separate production accounting contract is explicitly approved.
- `pit_universe_label_clean=false` remains a production blocker.
- Every A/B must reproduce the official control before any treatment arm is interpreted.

## Phase 2 Priorities

### P0 - Cash-Carry Governance Draft

Cash-carry is the highest-confidence improvement from Phase 1. It should remain research-only for now, but we should draft the accounting contract so the user can decide whether to adopt it officially later.

Create or update a governance note with:

- rate source: `DGS3MO`
- PIT lag: `1 business day`
- haircut: `50bps`
- day count: `ACT/365`
- negative cash earns no interest
- metric mode: `broker_ledger_next_close_cash_carry`
- zero-yield baseline and cash-carry baseline both preserved
- all future A/B arms must use identical cash treatment
- no production promotion until PIT membership is clean

Do not silently change production metrics.

### P1 - Bull-Floor Closeout

Create:

- `docs/CODEX_BULL_FLOOR_CLOSEOUT_20260701.md`

Include:

- cash-carry control result: `48.83% / -23.79%`
- floor `0.85 / 0.90 / 0.95` results
- lifted date count
- avg cash reduction
- why it failed:
  - gross deployment was too blunt
  - reduced cash but increased drawdown
  - failed both CAGR and MDD
- conclusion:
  - broad bull-floor rejected
  - no fullrun
  - remaining gap is Concentrated +1.17pp CAGR

### P2 - Control Reproducibility Audit

The Phase 1 work found that `run_lever_sweep.py` regenerated a vNext target book that did not match the official artifact target book, even before applying treatment. This makes generated-target A/B results non-interpretable unless control reproduction is proven.

Create:

- `tools/run_target_book_control_repro_audit.py`

Compare:

- official artifact target book
- regenerated vNext target book under the same env/config

Report:

- date set differences
- ticker set differences by rebalance date
- weight deltas by ticker/date
- book hash delta
- env flags
- candidate book path/hash
- price cache end date
- code commit

Acceptance:

- exact or near-exact control reproduction is required before using regenerated vNext books for selection-side A/B.
- until then, prefer fixed official-book harnesses for replay-stage levers.

### P3 - Concentrated Hysteresis / Replacement Timing A/B

Goal:

Determine whether current operating-book stickiness is useful winner-hold hysteresis or stale lock-in that caps CAGR.

Create:

- `tools/run_concentrated_hysteresis_replacement_ab.py`

Baseline:

- official concentrated target book from run `28436307420`
- cash-carry ON
- replay end date `2026-06-29`
- metric mode `broker_ledger_next_close_cash_carry`
- control must reproduce `48.83% / -23.79%`

Arms:

1. `operating_baseline`
   - exact official target book
   - must reproduce control

2. `raw_score_rotation`
   - diagnostic upper bound only
   - high turnover expected
   - not a policy candidate unless turnover and MDD are acceptable

3. `relaxed_hysteresis`
   - reduce current-holding protection
   - replace only when new candidate exceeds holding by score gap

4. `score_gap_confirmed_rotation`
   - rotate only when:
     - score gap exceeds threshold
     - 3m/6m RS is positive or superior
     - no crisis/defense regime
     - current holding does not have strong winner/leader protection

5. `turnover_capped_rotation`
   - partially follow raw target with turnover caps
   - test caps: 25%, 50%, 75%

Grid:

- score gap: 5%, 10%, 15%
- RS confirmation: true/false
- one-cycle delay: true/false

Metrics:

- CAGR, MaxDD, Sharpe
- avg cash
- turnover, trade count, fees
- IS/OOS/OOS2 CAGR
- OOS/IS ratio
- contribution by ticker
- contribution by AI-capex bucket
- average holding period
- late loser contribution
- premature exit contribution

Acceptance:

- Concentrated CAGR >= 50%
- MaxDD >= -25%
- Sharpe deterioration <= 0.05
- OOS/IS not worse
- not only 2025
- not only one ticker
- turnover and fees acceptable
- official control reproduced before treatment interpretation

### P4 - Narrow Hold-Duration / Exit Timing A/B

Broad hold-longer already failed in prior work. Do not revive broad hold-duration rescue.

Create:

- `tools/run_concentrated_hold_exit_timing_ab.py`

Hypothesis:

Narrow, leader-confirmed hold extension or deteriorating-holder exit acceleration may recover part of the +1.17pp without reducing cash.

Arms:

1. `baseline_cash_carry`
2. `hold_extend_confirmed_leader_one_cycle`
3. `exit_accelerate_deteriorating_holder`
4. `replacement_delay_one_cycle`
5. `replacement_partial_50`

Hold extension only when:

- above MA200
- 3m benchmark RS >= 0
- 6m RS positive
- no crisis/defense regime
- no hard reject
- no severe MA50 + MA200 failure
- earnings/revision/guidance evidence is positive or neutral when available

Exit acceleration only when:

- 3m RS < 0
- MA50 and MA200 fail
- earnings/revision/guidance evidence negative if available
- replacement candidate has superior RS/score

Acceptance:

- applied count > 0
- Concentrated CAGR improves meaningfully
- MaxDD remains >= -25%
- OOS non-regress
- no single ticker / single era dependence

### P5 - Cap-Safe Concentrated Sizing A/B

Previous broad score-sizing failed as a policy candidate. Do not rerun the same broad score-sizing.

Create or extend:

- `tools/run_concentrated_risk_adjusted_sizing_ab.py`

Hypothesis:

Within already-selected official names, risk-adjusted sizing may improve CAGR/MDD without broad gross-floor exposure.

Arms:

1. `baseline_cash_carry`
2. `cap_safe_score_blend_low`
3. `vol_adjusted_score`
4. `rs_plus_low_vol_score`
5. `drawdown_contribution_capped`
6. `winner_pyramiding_only_after_positive_RS`

Rules:

- preserve selected names unless the arm explicitly tests replacement
- preserve total stock gross unless explicitly testing cash shift
- no single-name cap breach
- no uncapped arm as policy candidate
- cash-carry ON
- replay end date `2026-06-29`

Acceptance:

- Concentrated CAGR moves toward or above 50%
- MaxDD >= -25%
- no cap breach
- turnover and fees acceptable
- OOS/IS non-regress

### P6 - AI-Capex Bucket / EPS Revision Confirmation Audit

The next durable selection layer should not be "AI stock" broadly. It should classify bottleneck buckets and verify earnings/revision support.

Create:

- `tools/run_ai_capex_bucket_revision_audit.py`

Buckets:

- `COMPUTE`: AMD, NVDA, ASIC/accelerator names
- `MEMORY`: MU, HBM/DRAM
- `STORAGE`: SNDK, WDC
- `CONNECT`: CIEN, LITE, CRDO, GLW, COHR
- `POWER_GRID`: VRT, GEV, TLN, BE, PWR
- `EQUIPMENT_FOUNDRY`: AMAT, LRCX, KLAC, TSM, UMC

Inputs:

- candidate book
- raw scored target
- operating target
- broker contribution
- EPS revision/guidance fields if present
- RS metrics

Outputs:

- `bucket_exposure_by_rebalance.csv`
- `bucket_contribution.csv`
- `missed_bucket_candidates.csv`
- `report.md`

Questions:

- Is STORAGE/CONNECT concentration justified by PIT score and contribution?
- Are COMPUTE/POWER/EQUIPMENT candidates rejected by hysteresis or cash?
- Do EPS revision/guidance signals support rotation candidates?
- Would bucket diversification improve OOS/IS ratio?

Important:

- Uploaded research PDFs are taxonomy inputs only.
- Use PIT data and broker contribution for decisions.

### P7 - Main Run-to-Run Attribution

Main reached the headline target under cash-carry, but prior runs showed roughly 1pp drift before cash-carry. Do not call Main stable until this is explained.

Create or run:

- `tools/run_main_run_delta_attribution.py`

Compare:

- run `28360773460`
- run `28436307420`

Report:

- target book hash delta
- price cache end-date delta
- env flag delta
- SH hedge contribution
- cash-funded early entry contribution
- holdings contribution by ticker
- cash trajectory
- universe/count delta

Interpretation:

- Main MDD repair track stays frozen.
- Main headline pass under cash-carry is useful.
- Main stability requires attribution.

## Fullrun Gate

Do not run a fullrun until one Phase 2 replay-stage candidate satisfies:

- Concentrated CAGR >= 50%
- MaxDD >= -25%
- Main non-regress
- OOS/IS not worse
- effect not one ticker / one era
- official control reproduced
- metric mode is broker-ledger or explicitly research cash-carry
- no future `available_from` leakage
- `pit_universe_label_clean=false` remains labeled as production blocker

If no Phase 2 replay-stage candidate passes:

- mark `partial_gap_remaining`
- do not continue broad lever hunting
- move to selection-layer work only after vNext control reproducibility is addressed.

## Near-Term Execution Order

1. P1 bull-floor closeout doc.
2. P0 cash-carry governance draft.
3. P2 control reproducibility audit.
4. P3 hysteresis/replacement timing A/B.
5. P4 hold/exit timing A/B.
6. P5 risk-adjusted sizing A/B.
7. P6 AI-capex bucket audit.
8. P7 Main run-to-run attribution.

The first implementation target should be P1/P0/P2, not another fullrun.


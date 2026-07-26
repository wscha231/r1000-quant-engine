# Run287 Ultimate System review — 2026-07-27

## Verdict

Run287 remains `RESEARCH_ONLY`. There is no accepted CAGR/MDD challenger and
no result in this review authorizes a fullrun, production mutation, or live
trading.

The checksum-locked fixture currently records:

| Portfolio | CAGR | MDD | Research target | Remaining fixture gap |
|---|---:|---:|---:|---:|
| Main | 34.4032% | -25.3629% | CAGR >= 35%, MDD >= -25% | +0.5968%p CAGR and +0.3629%p MDD |
| Concentrated | 49.0968% | -22.9560% | CAGR >= 50%, MDD >= -25% | +0.9032%p CAGR; MDD already inside the target |

These are fixture baselines, not a corrected new fullrun and not a claim that
the targets have been achieved.

## Review from the beginning

### Safety and operating correctness

- H2 and H3 are merged.
- PR #341 adds spread, paper slippage, ADV participation, volatility impact,
  and capacity evidence. It also fails closed on missing fill/liquidity
  coverage and impossible execution costs.
- Daily paper continuity, exact-close checks, scorecard trust, and promotion
  governance exist, but the canonical state correctly remains research-only.
- Catch-up and current-session work must continue in completed NYSE-session
  order. A future or incomplete session must not be manufactured.

### Data and feature layer

- PIT availability controls exist for several SEC, price, macro, and operating
  artifacts.
- Historical point-in-time universe membership, delisted coverage, taxonomy
  vintages, and free historical estimate snapshots are not yet complete enough
  to support a new official alpha claim.
- The sector/subsector leadership tape is useful for forward detection and
  review. It is not historical CAGR/MDD evidence by itself.

### Portfolio and execution layer

- Main and Concentrated are separate books and must remain separately
  attributable.
- Normal rebalancing and exceptional lifecycle/crisis actions must remain
  distinct.
- Execution cost/capacity evidence now prevents a nominal target from being
  scored as if an unfillable trade occurred.
- Cash policy must continue to use one attributed allocator. Independent cash
  floors must not be added together.

### Historical research layer

The do-not-repeat registry already blocks the principal failed lanes:

- broad cash/gross floors;
- stop or exit-delay grids;
- static fundamental/profitability tilts;
- direct 13F/Form 4 tilts;
- weak-source fusion;
- direct growth transfer;
- account-aware execution variants;
- prior sector-leadership reconstruction and canonical sector-RS variants.

Renaming one of these ideas or moving a threshold is not a new causal
hypothesis.

### Multiple-testing and promotion layer

This change adds the missing U4 statistical barrier:

- the candidate, causal family, selection rule, full parameter set, and
  do-not-repeat registry snapshot must be in a Git-anchored preregistration
  committed before evaluation;
- every preregistered performance trial must appear in the complete experiment
  ledger and synchronized after-cost excess-return matrix;
- the matrix must contain at least 504 exact contiguous NYSE sessions;
- Deflated Sharpe probability must be at least 95%;
- CSCV PBO over all 70 four-of-eight block splits must be at most 20%;
- centered circular-block White Reality Check p-values for 5, 21, and 63
  sessions must each be at most 10%;
- an exact hash-pinned bundle is required before
  `multiple_testing_pass=true` can enter the promotion gate.

Tracked evidence cannot set this bit. The official wrapper resets it to false
unless the exact runtime bundle is independently supplied and verified.

## CAGR/MDD improvement sequence

Infrastructure changes do not improve CAGR or MDD by themselves. The next
causal challenger must follow this order:

1. Commit one preregistration with a materially new mechanism and the complete
   trial set.
2. Prove PIT source, universe, taxonomy, and after-cost return coverage.
3. Run source-screen and fixed-book checks without changing the champion.
4. Obtain separate approval for one corrected fullrun only after every
   preflight passes.
5. Apply Full/OOS/OOS2, embargo, stress, concentration, cost, DSR, PBO, and
   Reality Check gates.
6. If no arm passes both portfolio targets without structural OOS degradation,
   retain the champion.
7. If one arm passes, begin separate forward paper validation; do not
   auto-promote it.

The next candidate should be surgical rather than a portfolio reconstruction:
a PIT-valid sector/subsector leadership-transition confirmation or stale-leader
veto may be preregistered only if its data semantics and mechanism are
materially different from the rejected leadership reconstruction. It must not
be backtested until the preregistration is merged and the PIT taxonomy/history
coverage gate passes.

## Remaining system work

- U0: normalize all historical branch/PR experiments into one permanent
  append-only experiment registry.
- U1: finish bitemporal universe, taxonomy, macro vintage, delisted, and
  estimate/guidance coverage.
- U2/U3: keep sector leadership research-only until independent OOS evidence;
  finish the single cash allocator and no-trade-band optimizer.
- U4: add purged walk-forward, regime leave-one-out, parameter perturbation,
  top-winner removal, and block/event robustness as explicit promotion checks.
- U5/U6: finish checkpoint/replay SLO evidence, dependency lock/review, SBOM,
  and signed artifact attestation.
- U7: allow automated challenger proposals only; every champion transition
  remains an independently reviewed user decision.

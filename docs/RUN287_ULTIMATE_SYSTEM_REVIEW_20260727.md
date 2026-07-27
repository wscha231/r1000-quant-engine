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

### U0 experiment audit

The U0 inventory now classifies all 21 canonical do-not-repeat entries, but it
explicitly does not claim that those entries are the complete historical
experiment census. PRs 229, 230, and 237 already expose additional
out-of-registry rolling-window, tilt, and source-selection attempts. All 21
canonical entries remain promotion-blocking. The audit found 21 references to
PR evidence whose head commit is no longer in current master ancestry, five
referenced local result files that are absent, and four concept-overlap groups
that could otherwise double-count the same trial lineage.

This is an intentionally fail-closed result:

- summary CAGR/MDD is not a substitute for synchronized daily after-cost
  returns;
- source screens and no-signal attempts must contribute to a separate
  selection-multiplicity penalty;
- no-op trials still count as attempted causal families;
- invalid or unverified legacy claims cannot be silently classified as
  non-performance;
- exact trial manifests and return columns must be recovered before a new
  challenger can use the historical multiplicity population.

The machine-readable contract and inventory are
`docs/run287_u0_experiment_audit_contract.json` and
`docs/run287_u0_experiment_inventory.json`.

### Multiple-testing and promotion layer

This change adds the missing U4 statistical barrier:

- the candidate, canonical champion identity and target hashes, causal family,
  selection rule, full parameter set, and canonical do-not-repeat registry
  must be in a Git-anchored preregistration that strictly predates an exact
  evaluation-start snapshot;
- rejected registry entries must remain append-only from registration through
  evaluation and the current canonical registry, including the fixed
  signal/mechanism/book/window matching semantics and canonical
  trim/lowercase normalization;
- every current and prior performance trial across causal families must appear
  in the complete experiment ledger and synchronized after-cost excess-return
  matrix, while only one active causal challenger is allowed;
- each canonical do-not-repeat entry must first be classified as
  performance-evaluated or non-performance; the gate remains blocked until U0
  completes that reviewed classification and each prior family's exact
  trial-identity manifest matches the ledger;
- each trial's candidate, causal family, parameter hash, and return column are
  preregistered together;
- the matrix must exactly match the preregistered first session, last session,
  and count, and contain at least 504 contiguous NYSE sessions;
- Deflated Sharpe probability must be at least 95%;
- CSCV PBO over all 70 four-of-eight block splits must be at most 20%;
- centered circular-block White Reality Check p-values for 5, 21, and 63
  sessions must each be at most 10%;
- the promotion gate reopens the ledger, returns, contract, promotion-state
  snapshot, preregistration, and registry history, recomputes the full gate,
  and requires a byte-identical five-file bundle;
- the statistical input hash stops at the evaluation-time registry snapshot;
  later append-only registry history is revalidated separately so a legitimate
  new research entry cannot invalidate an already approved daily bundle;
- every non-research daily evaluation must carry the reviewed immutable bundle
  through the canonical approved-pointer file and match its candidate to the
  canonical state's official challenger before
  `multiple_testing_pass=true` can enter the promotion gate.

Tracked evidence cannot set this bit. The official wrapper resets it to false
unless the exact runtime bundle is independently supplied, recomputed, and
verified. `report.md` is included in the artifact hashes.

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

- U0: the 21 canonical entries have a fail-closed baseline; finish the full
  branch/PR experiment census, absorb the known PR 229/230/237 backlog, recover
  orphaned exact trial manifests and daily return columns, deduplicate the four
  overlap groups, and implement source-selection multiplicity before
  preregistering a challenger.
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

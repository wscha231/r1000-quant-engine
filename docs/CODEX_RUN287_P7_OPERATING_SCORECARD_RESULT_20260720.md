# Run287 P7 canonical operating scorecard result - 2026-07-20

## Decision

The private/review-only canonical operating scorecard is ready. One command
now produces a machine-readable JSON scorecard and a human-readable Markdown
report without copying any source artifact:

```text
python tools/build_run287_operating_scorecard.py --output-dir outputs/run287_operating_scorecard
```

Historical evidence, current paper execution, and true-forward outcomes have
independent statuses. Missing evidence is `UNAVAILABLE` or `UNDERPOWERED`,
never zero. Any verified integrity error changes every headline performance
label to `NOT_TRUSTED`.

## Actual bounded result

- Headline historical trust: `TRUSTED`.
- Historical evidence: `AVAILABLE_PARTIAL`.
- Current durable paper execution: `UNAVAILABLE` because neither
  `outputs/daily_simulated_fill_ledger/summary.json` nor its
  `snapshot_integrity.json` exists in the current local workspace. The P0
  transaction implementation is validated, but a test result is not presented
  as a current account.
- True-forward evidence: `UNDERPOWERED`. The available archive is as of
  2026-07-10, has 10 distinct true-forward tickers and zero resolved
  21/63/126-day outcomes. Its current schema has no 252-day outcome, which is
  explicitly `UNAVAILABLE`.
- Scorecard output contains 316 provenance-bearing metrics. Ten prior P3-P6
  summaries/audits are marked `ABSORBED_SOURCE`; none is duplicated into a new
  archive.

The scorecard's generation date is 2026-07-20, but the historical market
evidence remains through 2026-07-10. It must not be described as a July 17
close performance refresh.

## Trusted historical headline

| Portfolio | CAGR | MDD | Sharpe | Trades | Fees |
| --- | ---: | ---: | ---: | ---: | ---: |
| Main | 34.4032% | -25.3629% | 1.2757 | 1,625 | $42,922.45 |
| Concentrated | 49.0968% | -22.9560% | 1.5002 | 730 | $62,764.08 |

Every headline value traces to the P5 exact-parity summary SHA-256
`60d075f6502533e9ab0df50be8a067e695872ac9978b436ab50c4724dae8fa23`,
as of 2026-07-10, using broker-ledger next-close, integer shares, DGS3MO carry,
and 25 bps per side.

## What currently explains performance

The scorecard does not claim that correlation is causation. It separates
measured support, measured failure, and missing evidence:

- Selection: positive matched-control evidence. Existing selected names beat
  nearest-score-rank controls in both books, Full/OOS/OOS2, and every
  21/63/126/252-day horizon tested in P6.
- Holding: bottleneck. Median completed holds are only 33 days Main and 32
  days Concentrated, with zero completed lots held at least 365 days. The P5
  strict persistence arm was a no-op, so this is not proof that blindly holding
  longer raises CAGR.
- Exit: underpowered. The one P5 arm produced no eligible incumbent/challenger
  counterfactual event, so premature-sell regret, replacement advantage, and
  avoided drawdown remain `UNDERPOWERED`.
- Risk defense: the fixed P3 shadow policy is rejected. It improved Main MDD
  but sacrificed 10.80pp CAGR; Concentrated sacrificed 16.23pp CAGR and did
  not improve MDD.
- Re-entry: the same rejected shadow exposed slow recovery and cash traps;
  those diagnostics cannot be promoted as operating alpha.
- Reserve: DGS3MO carry is positive but not selection alpha. Historical mean
  Reserve was 29.31% Main and 40.80% Concentrated, classified almost entirely
  as `capacity_unallocated`, not `crisis_reserve`.
- Cost: material. Increasing the replay assumption from 25 to 100 bps reduces
  Main CAGR from 34.40% to 25.41% and Concentrated from 49.10% to 38.38%.
- Rank stability: adjacent-decision top-10 overlap is only 33.57% and top-30
  overlap 42.62%, so selection changes and transaction costs must be reviewed
  together.

## Integrity and provenance contract

Each metric carries:

- source ID and absolute path;
- verified SHA-256;
- source as-of date;
- metric mode;
- evidence class and availability status.

The source registry itself is versioned and hashed. A metric-definition version
change requires a migration note when compared with a previous scorecard.
Known historical parity and Reserve reconciliation checks are genuine measured
zero-error counts. Missing current account resets, duplicate orders, exact-close
errors, hash-chain breaks, lifecycle failures, and degraded-data days are
`UNAVAILABLE`, not fabricated zeroes.

Actual local outputs:

- `_tmp_tests/p7_operating_scorecard_actual_v3_20260720/operating_scorecard.json`
  SHA-256 `ecc8c04471391785c0845700bc5ff04a08cf847f4157258b2e6f5342268bf842`.
- `_tmp_tests/p7_operating_scorecard_actual_v3_20260720/operating_scorecard.md`
  SHA-256 `3cfe6ab64d90336fa12b68393516f49dcf2e0f33e389fac975d328fcc3bada9d`.

## Safety and next gate

- The scorecard is not a public dashboard and does not write target books,
  orders, fills, or account state.
- Historical acceptance is never overwritten by forward results.
- Repository pytest passed `129/129`; full Tier-1 PR validation passed
  `188/188` in `479.59s`.
- Fullrun executed: false. Production enabled: false. Live trading enabled:
  false.
- P8 may now replace hidden dated-path dependencies with small canonical
  pointers/fixtures and external checksum-verified restore contracts. It must
  preserve all existing local evidence and may not rewrite Git history.

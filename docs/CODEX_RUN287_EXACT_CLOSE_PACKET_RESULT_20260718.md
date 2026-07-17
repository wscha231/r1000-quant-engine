# Run287 exact-close selector packet result — 2026-07-18

## Outcome

The bounded 2026-07-16 close chain is now complete through the immutable input
registry and the no-write selector/candidate-risk packet.

- upstream: `READY_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY`;
- immutable registry: `READY_EXACT_PACKET_INPUTS_REVIEW_ONLY`;
- selector/risk producer: `READY_EXACT_SELECTOR_RISK_PACKET_REVIEW_ONLY`;
- resume network requests: `0`;
- backtest, fullrun, orders, target-book writes, production, and live trading:
  all `false` or `0`.

This is current advisory evidence. It did not change historical CAGR/MDD and
did not authorize a portfolio transition.

## Exact data gates

| Gate | Result |
|---|---:|
| Frozen universe contract | 989 |
| Active decision tickers | 988 |
| Verified terminal exclusions | 1 (`GTLS`) |
| Model features | 238 |
| Scaled finite ratio | 100% |
| Missing-neutral violations | 0 |
| Future feature rows | 0 |
| SEC exact-acceptance rows | 87 / 87 |
| Fundamental refreshes | 6 / 6 |
| Selector price-map sources | 363 / 363 |

GTLS was not given a fabricated 2026-07-16 close. SEC accession
`0001193125-26-305482`, accepted `2026-07-16T13:02:00Z`, records the completed
$210 cash acquisition and delisting, so the ticker is a verified terminal
exclusion from the active cross-section.

NKE accession `0000320187-26-000088` and GE accession
`0000040545-26-000049` each lacked only the canonical `op_income_ttm` field.
The exact-accession contract leaves that field missing and lets the frozen
scaler neutralize it. No old value was carried and no value was synthesized.

## Resume and price-source hardening

- A resumed attempt now follows hash-verified stage manifest pointers even
  when those stages came from an older append-only attempt.
- Downstream macro caches now follow the reused macro manifest's real parent
  instead of an empty new-attempt directory.
- The 2026-07-16 SOXX series was recovered from a date-specific hash-pinned
  local file with 2,145 rows from 2018-01-02 through 2026-07-16. The exact
  2026-07-16 close is `530.50`.
- The candidate-risk overlap failure for MRVL, MU, and UMC was caused by
  dividend-driven historical `Adj Close` restatement. Raw closes matched
  exactly. The repair keeps the `1e-5` raw-close identity gate, replaces the
  provider overlap with the current adjusted history, and rebases only the
  older frozen history. The tolerance was not relaxed.

## Current no-write selector snapshot

| Scenario | Stocks | Advisory cash | Marked cash | One-way turnover vs marked | 25 bp estimated drag |
|---|---:|---:|---:|---:|---:|
| Main strict | 14 | 7.87% | 1.38% | 93.41% | 0.451% |
| Main prior-hold bridge | 14 | 9.12% | 1.38% | 93.59% | 0.449% |
| Concentrated strict | 5 | 61.95% | 0.84% | 99.16% | 0.343% |

The 15 proposed-entry candidates are `ALAB`, `AMD`, `ARM`, `DELL`, `DINO`,
`DVA`, `FLEX`, `FTNT`, `HPE`, `MRVL`, `MU`, `PANW`, `SNDK`, `STX`, and `UMC`.
Candidate risk states are 4 ALERT, 3 WATCH, 8 NORMAL, and 0
DATA_INSUFFICIENT. FLEX, MRVL, STX, and UMC are ALERT; ARM, MU, and SNDK are
WATCH.

The large Concentrated cash recommendation is therefore diagnostic, not an
execution target. It is produced by the frozen neutral-regime capacity logic,
has extreme turnover, includes an ALERT candidate (`UMC`), and has not passed
the risk-watch promotion gate.

## Performance boundary and next gate

The exact packet repairs the stale-current-selector bottleneck and creates a
truthful forward observation for a volatile semiconductor episode. It does
not establish that the proposed high-cash rotation improves seven-year CAGR
or MDD. Historical generated-book evidence remains unchanged.

Next, append this immutable decision packet to the forward causal archive and
resolve fixed 1/5/21/63/126-session outcomes. Do not use the current episode to
retune cash, turnover, risk thresholds, or semiconductor exits. A portfolio
challenger remains closed until its preregistered forward/source gates pass.

## Evidence

- upstream status:
  `outputs/run287_exact_packet_upstream/attempts/local-20260717-close-20260716-neutral-v12/status.json`;
- source bundle SHA-256:
  `c420f655de23fe6e1c71901bb0ae6c7ce2ee32508f0bae8be7bdc1634c0b6fa9`;
- registry SHA-256:
  `bb88a4d9d0e6ec0b08c2d812381ec6cec82495d4249046f1b4e09f9812b15508`;
- producer status:
  `outputs/run287_exact_packet_producer_20260718_close_20260716_v2/status.json`;
- selector manifest SHA-256:
  `9592be19c72555bc1a2a96291e2fedac66b82d2a80862a50d5349a6061cdf1b4`;
- candidate-risk summary SHA-256:
  `9aba447dba43aafba272a871ce4e94af555e75bf56887e25f05c63d54c5fd04a`.

# Run287 SEC balance-sheet resilience source-screen result (2026-07-18)

## Decision

`REJECT_SOURCE_SCREEN`. Do not create a Main or Concentrated portfolio arm,
and do not retune the comparison period, debt scope, horizon, or event rule.

The result is research-only. It did not change holdings, target weights, cash,
orders, fullrun, production, or live trading. The generated-book baselines
remain Main `34.4032% / -25.3619%` and Concentrated `49.0971% / -22.9552%`.

## Frozen signal

- Availability is Companyfacts `accn` joined to exact SEC submissions
  `accepted_at`; Companyfacts `filed` is never used.
- The current state uses assets, cash, and a complete debt scope from one
  filing period. Missing and incomparable scope are neutral.
- The comparator is the latest earlier fiscal-period state accepted before the
  current filing, 45 through 460 calendar days earlier, with the same complete
  debt scope.
- Positive requires both debt/assets and net-debt/assets to be no higher, with
  at least one strictly lower. Negative is the symmetric rule. There is no
  magnitude threshold, percentile, grid, decay, or sector adjustment.
- Entry is the first NYSE close strictly after exact acceptance. The primary
  label is 63-session SPY excess return; 21 and 126 sessions are secondary.

## Data result

| Item | Result |
|---|---:|
| Exact SEC filing rows eligible | 115,185 |
| Balance-sheet states | 27,168 |
| Issuers represented | 915 |
| Exact event history | 2018-01-04 to 2026-07-02 |
| Current complete / comparable complete | 15,775 / 14,715 |
| Positive / negative / neutral | 6,646 / 4,696 / 15,826 |
| Resolved entry rows | 23,608 |
| Future rows / filed fallbacks | 0 / 0 |

All 27,168 issuer-accessions are unique. Every fired row has both comparable
ratios, an earlier exact acceptance, the same debt scope, and a period gap
inside the frozen range. Every resolved entry close is strictly after the SEC
acceptance timestamp.

## Primary 63-session result

All values are mean SPY excess returns. Spread is positive minus negative.

| Segment | Positive n | Negative n | Positive mean | Negative mean | Spread | Filing-week bootstrap 95% CI |
|---|---:|---:|---:|---:|---:|---:|
| Full | 5,819 | 3,958 | -0.118% | -0.211% | **+0.093%p** | [-0.753%, +0.898%] |
| OOS2 (2023-01-01+) | 3,033 | 2,096 | -1.661% | -2.036% | **+0.375%p** | [-0.669%, +1.555%] |
| OOS (2024-07-01+) | 1,657 | 1,115 | -1.051% | -2.416% | **+1.365%p** | [-0.129%, +3.020%] |

The event-count and week-block power gates pass, and all three point estimates
are positive. The preregistered OOS and OOS2 bootstrap lower bounds are still
below zero, so the source screen fails. This is a near-directional result, not
permission to weaken the confidence gate.

The secondary horizons do not rescue the lane: 21-session spreads are small
with negative lower bounds, while the full-history 126-session spread is
`-1.155%p` even though the recent OOS estimate is positive.

## Closure and next gate

The exact do-not-repeat key is:

`sec_balance_sheet_resilience_event+exact_accepted_time_within_issuer_change_source_screen+single_source_sec_events+2018-01-02_2026-07-09`

No portfolio A/B is authorized. Reopening requires at least five percentage
points of genuine component coverage or a prospectively justified semantic
change before outcomes are inspected. Changing the debt magnitude, prior gap,
63-day endpoint, confidence gate, or attaching this source to the rejected
growth arm does not qualify.

The next admissible CAGR lane is not another Companyfacts threshold search. It
is the already contracted PIT estimate/guidance sample gate, or continued
true-forward archive accumulation. Any paid acquisition needs separate user
approval and remains research-only.

## Evidence hashes

- `balance_facts_accession_cache.parquet`: `de4febc4bc7315968f7e5e8cc931efadc29537ccbcbce0a845870619fe763e1d`
- `sec_balance_sheet_resilience_events.parquet`: `e8a6cd5c48b0db3aec0224e8b462b77bcdb9ab1b68a397198d8ed1c3e7a3b7fc`
- `source_screen_event_returns.csv`: `4d3f233b00a4d90c2b893af6258001e2b28641e74d7db324ce06f3b316cf82c2`
- `source_screen_summary.json`: `cef28ecee0bcf9e8d51ddaee7aef51691b1a8bfd2b90960096cf36e311837ccb`

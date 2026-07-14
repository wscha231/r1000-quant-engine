# Run287 Partial-Resize Confirmation Result - 2026-07-13

## Verdict

`partial_resize_two_signal_confirmation` is rejected and must not be tuned or
promoted. It reduced trades and fees, but it delayed useful monthly
target-weight information. Full-window, OOS, and OOS2 CAGR fell for both
portfolios under cash-carry and zero-yield accounting.

No fullrun or production/live action was performed.

## Fixed mechanism

- New entries execute immediately.
- Full exits execute immediately.
- Partial sells execute immediately whenever total target gross falls.
- Every other held-name partial resize is deferred once and executes only if
  the same buy/sell direction repeats at the immediately following decision.
- There is no threshold or parameter grid.

The implementation is an explicit research-only option in
`tools/run_broker_ledger_replay.py`. The default mechanical replay remains
unchanged and the research arm always reports
`production_activation_allowed=false`.

## Control parity

The current code reproduced the frozen cash-carry control exactly:

| Portfolio | CAGR | MDD | Sharpe | Trades | Trade-ledger parity |
| --- | ---: | ---: | ---: | ---: | --- |
| Main | 34.4032% | -25.3619% | 1.2757 | 1,625 | exact SHA-256 match |
| Concentrated | 49.0971% | -22.9552% | 1.5003 | 730 | exact SHA-256 match |

Main trade SHA-256:
`8df08ee86e0d3c755198756e9e92b0244241fe7a7d41899f6cbfb21a99a9f65f`.

Concentrated trade SHA-256:
`c26af4f11aadf9f6b47979d5c4e52f9fcc2930a65f915453aeb0bdcee923ff3d`.

## Cash-carry result

| Portfolio | Arm CAGR | dCAGR | Arm MDD | dMDD | dSharpe | OOS dCAGR | OOS2 dCAGR | Fee change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Main | 31.5886% | -2.8146pp | -27.0363% | -1.6744pp | -0.0618 | -14.4485pp | -6.9461pp | -$5,259.96 |
| Concentrated | 38.2025% | -10.8946pp | -23.5305% | -0.5753pp | -0.2226 | -31.9098pp | -15.6199pp | -$21,147.52 |

The arm fired materially:

- Main: 303 deferrals, 77 second-signal confirmations, 188 immediate target-
  gross risk cuts, 540 immediate entries, and 526 immediate exits.
- Concentrated: 91 deferrals, 17 confirmations, 77 immediate risk cuts, 275
  immediate entries, and 270 immediate exits.

This is not a no-op. The mechanism itself is wrong for these books.

## Zero-yield sensitivity

| Portfolio | Control CAGR | Arm CAGR | dCAGR | OOS dCAGR | OOS2 dCAGR |
| --- | ---: | ---: | ---: | ---: | ---: |
| Main | 33.5352% | 30.6551% | -2.8801pp | -14.4936pp | -7.0376pp |
| Concentrated | 47.6898% | 36.7727% | -10.9170pp | -31.8876pp | -15.6659pp |

The failure does not depend on cash interest.

## Interpretation and stop rule

The cost upper bound showed that execution costs are large enough in theory to
cover the remaining headline CAGR gaps. This A/B shows that suppressing monthly
partial resizes is not a free way to capture that upper bound: the avoided
trades carry more alpha than their fees cost. Small-trade filtering is also too
small to close the gap.

Close execution-delay and generic churn-suppression research for this exact
signal, mechanism, book, and window. Do not try a threshold, a longer/shorter
confirmation count, or a renamed deadband variant.

The next admissible historical alpha path is a genuinely new PIT
estimate/guidance source. Free current snapshots remain forward paper evidence
only.

## Frozen evidence

- Base code SHA: `572dbce22d6fa92b1ad740561c4f51fe4bb0572a`
- Main target-book SHA-256:
  `356bac22ec55090b2d2da882c7505b1460973227639a5d0b7a4c59c25c0ccff9`
- Concentrated target-book SHA-256:
  `848c1bac00985ab0b132794ee3e1c2942c1561d2f728b0a89778bd6c4e63660e`
- Temporal-extension manifest SHA-256:
  `d3612852c5e189295d9eb89c2599dc40213d42ac893f77b367290d15af89704c`
- Cash-rate SHA-256:
  `565c27385682d9ba562b7d80d591594b53564e4a756bedc62207342f35b47532`
- Machine-readable result:
  `outputs/run287_partial_resize_two_signal_20260713/summary.json`

Do-not-repeat key:
`target_weight_direction+partial_resize_two_signal_confirmation+generated_baseline_books+2019-06-03_2026-07-10`.

The machine-readable registry is
`docs/run287_do_not_repeat_registry.json`. New research registrations should
run `tools/check_run287_do_not_repeat.py`; the exact combination is blocked
unless component coverage rises by at least 5pp or an explicit semantic or
application-mechanism change is supplied.

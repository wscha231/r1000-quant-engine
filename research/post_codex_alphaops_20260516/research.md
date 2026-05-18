# Post-Codex AlphaOps Research - 2026-05-16

## Scope

This note formalizes the post-Codex AlphaOps direction after the first
production-compatible improvement from the alpha-selector plus market-circuit
stack. It is intentionally research-only. No production defaults are changed by
this plan.

## Official Baselines

Official evidence remains the broker-ledger/account-like evaluator:

- next-close fills
- integer shares
- explicit cash ledger
- fees included
- daily equity curve and daily drawdown

The prior official broker-ledger full-run baseline was:

| Portfolio | CAGR | MaxDD | Sharpe |
|---|---:|---:|---:|
| main | 18.44% | -31.93% | 0.848 |
| concentrated | 35.10% | -22.68% | 1.300 |

The strongest current main challenger from the fast replay path is
`main_alpha_selector_market_circuit_grid_best`:

| Portfolio | Candidate | CAGR | MaxDD | Sharpe |
|---|---|---:|---:|---:|
| main | `main_alpha_selector_market_circuit_grid_best` | 28.95% | -21.40% | 1.149 |

This is a large official improvement, but it is still not a production default:
the main target remains 30% CAGR with MaxDD near -15%, and the current challenger
still has too much drawdown.

## Proxy vs Broker-Ledger Separation

Proxy/monthly target-pass results are idea sources only. They cannot be promoted
until they survive the broker-ledger evaluator. The key remaining concentrated
problem is the conversion gap:

- concentrated proxy/research candidates can exceed 50% CAGR.
- official concentrated broker-ledger remains near 35% CAGR with MaxDD around
  -23%.

That means the next concentrated task is not blind single-cap, stop, or target-N
tuning. It is a trade-path reconciliation between the high-proxy candidate and
the official broker-ledger replay.

## Main MDD Problem

The alpha-selector plus market-circuit stack mostly addresses main CAGR, but the
remaining drawdown is still too high. The most useful next diagnostic is not
another stop-loss layer. Prior experiments showed that naive longer holding,
simple rebalance slowdown, and extra stop overlays can hurt CAGR.

The next main diagnostic should identify:

- drawdown periods by market-circuit state
- months where the circuit stayed too exposed
- wrong substitutions where a sold winner outperformed the replacement
- 2024 leader-rotation mistakes
- whether new buys, rather than existing winners, caused the worst drawdown

## Leader Discovery Failure Hypothesis

The leader recovery watchlist is diagnostic only. It must never force a buy.
The watchlist exists to answer where strong names dropped out:

`SNDK, MU, AMD, ARM, ASML, INTC, WDC, STX, LITE, CIEN`

For each ticker, the required path is:

```text
universe -> scored -> sleeve -> target book -> broker buy -> exit
```

The audit should capture:

- first scored date
- first onset signal date
- first target date
- first broker buy date
- first broker exit date
- missed return after onset
- drop reason

This is a missed-leader audit, not a hardcoded-ticker strategy.

## Leader-Onset Shadow Score

The new `leader_onset_score` is a shadow selector score. It should be used in
alpha-selector target-book challengers and selection-quality reports first, not
as a default production model feature.

Allowed contemporaneous inputs include:

- monster early score
- future-winner score
- early-scout score
- relative-strength acceleration
- dynamic leader score
- industry-group strength
- relative-strength composite
- O'Neil leadership score
- governance/catalyst score when available
- dollar-volume and price ranks as small liquidity/attention proxies

Forward-return labels are validation-only and must not influence target-book
selection.

## Concentrated Conversion Gap

The new reconciliation output should explain why proxy concentrated variants
lose performance in broker-ledger form:

- proxy CAGR, MaxDD, Sharpe
- official broker CAGR, MaxDD, Sharpe
- trade count and fees
- high-cash rows
- per-ticker buy/sell path
- available risk-action to sell-lag comparison

Promotion remains blocked until concentrated improvement is official
broker-ledger evidence.

## Workflow Ownership

- `full_rebuild_manual.yml` remains Tier 3 official artifact generation.
- `alphaops_replay_sidecars_manual.yml` remains Tier 2 fast replay and
  challenger comparison.
- branch/run-scoped Google Drive paths remain:
  `research_runs/<branch>/<run_id>/...`
- no automatic promotion is added.

## Promotion Gates

Main challenger:

- CAGR >= 28.5%
- MaxDD >= -20% first gate, then >= -18%
- Sharpe >= 1.10
- official broker-ledger only
- no stale or blocked actionable orders

Concentrated challenger:

- CAGR >= 40% first gate, then >= 45%
- MaxDD >= -22% first gate, then >= -18%
- official broker-ledger only
- proxy target-pass alone is not evidence

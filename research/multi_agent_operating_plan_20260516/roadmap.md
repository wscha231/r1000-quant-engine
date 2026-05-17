# Multi-Agent Roadmap 20260516

## Operating Model

Use parallel agents only when their write scopes do not overlap. Strategy-changing work is gated by official broker-ledger evidence and human approval.

Default flow:

```text
PR validation
-> focused sidecar replay
-> official minimal broker replay
-> research full run
-> human promotion review
```

## Phase Order

1. A0 Orchestrator
   - Maintain baseline registry, agent contracts, promotion gates, and merge order.
   - Code changes are not allowed.

2. A8 QA/Governance
   - Add tests that block leakage, CIK schema regressions, official/proxy label confusion, and production activation without approval.

3. A1 Data/PIT
   - Stabilize CIK schema, candidate universe parquet exports, price/cache coverage, and PIT labels.

4. A2 SEC Evidence
   - Start with Form 4 only.
   - Add 13D/G, 8-K, 13F, and Form 144 only after Form 4 passes PIT and shadow validation.

5. A7 Diagnostics
   - Build run-to-run diff, hold-vs-replace audit, wrong substitution analysis, missed leader paths, and cash policy reconciliation.

6. A3 Selection
   - Add shadow `early_evidence_score`, `market_confirmation_score`, `leader_onset_score`, and `evidence_confidence_score`.
   - Do not change `score_total`.

7. A4 Main PM
   - Build Main challenger from the Main champion baseline.
   - Evaluate only with broker-ledger next-close replay.

8. A5 Concentrated PM
   - Restore and improve from the `20260514` concentrated champion.
   - N7 is not allowed as a concentrated champion until it beats the baseline officially.

9. A6 Broker/Risk
   - Validate costs, stress windows, daily drawdown, replacement swaps, and order feasibility.

10. A9 DevOps
   - Slim workflows only after the research/evaluation path is stable.

## Parallel Rules

Allowed in parallel:

```text
A2 Form 4 evidence
A7 Diagnostics
A9 workflow timing/reporting
```

Sequential first:

```text
A0 baseline registry
A8 QA gate
A1 CIK/PIT schema
```

Never allow multiple agents to edit `r1000_pipeline.py`, `r1000_signals.py`, or `r1000_config.py` at the same time.

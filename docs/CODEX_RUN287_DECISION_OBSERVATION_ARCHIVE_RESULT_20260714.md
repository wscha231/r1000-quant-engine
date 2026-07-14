# Run287 decision observation archive result - 2026-07-14

## Decision

The exact-close no-write selector and proposed-candidate risk packets now feed
a single append-only forward observation archive. The first observation is the
completed 2026-07-13 session and ISO decision week `2026-W29`.

The archive is `READY_DECISION_OBSERVATION_ARCHIVE_REVIEW_ONLY`. It cannot
approve a portfolio transition, alter a selector weight, mutate a target book
or cash policy, generate an order, run a backtest/fullrun, or activate
production/live trading.

## First observation

| Record family | First-run rows | Same-date rerun rows | History rows |
| --- | ---: | ---: | ---: |
| Decision close | 1 | 0 | 1 |
| Selector scenarios | 3 | 0 | 3 |
| Selector positions including cash | 50 | 0 | 50 |
| Proposed-candidate risk | 7 | 0 | 7 |

The normalized decision retains Main strict, Main prior-hold bridge, and
Concentrated strict. Candidate states remain STX ALERT, AMAT/COHU WATCH, and
ARM/DELL/FTNT/PANW NORMAL. NORMAL remains explicitly non-authorizing.

Current gate counts:

- completed decision dates: 1;
- distinct ISO decision weeks: 1;
- early four-week stability review: not ready;
- minimum twelve-week review gate: not met;
- resolved forward-outcome gate: not met;
- archive promotion permission: false.

## Frozen ingestion contract

An observation is accepted only when all of the following hold:

1. selector status is `READY_CURRENT_SELECTOR_NO_WRITE_REVIEW_REQUIRED`;
2. candidate-risk status is an allowed review-only READY state;
3. both packets refer to the same requested completed close;
4. the policy commit, selector contract, held-risk contract, candidate-risk
   contract, and three scenario keys match the frozen identity exactly;
5. selector advisory weights sum to one in each scenario;
6. the mechanically derived proposed-entry union exactly matches the risk
   packet ticker union;
7. every candidate row has an exact close and a valid frozen risk state;
8. all packet and row-level execution, mutation, and production flags remain
   false.

The archive rejects an observation older than its latest close. A same-date
rerun must reproduce normalized decision, scenario, position, and risk payloads
exactly. The normalized event excludes environment-specific file paths and
generation timestamps, so a semantically identical rerun is idempotent while
a changed decision fails closed.

## Daily workflow integration

`daily_operating_selection_refresh.yml` now:

- restores the archive from the GitHub cache and, when configured, Google
  Drive;
- runs archive ingestion after the exact-close holding-risk watch and before
  user-facing reports;
- discovers only a Run287 selector/risk pair for the completed session;
- records `SKIPPED_NO_EXACT_SELECTOR_RISK_PACKET` when that pair is absent,
  without overwriting the last valid archive manifest or history;
- uploads the archive in the GitHub artifact and persists it under
  `paper_archive/run287_decision_observation_archive`.

This is conditional ingestion and persistence, not automatic generation of
the upstream Run287 decision frame, score stack, selector, and candidate-risk
packet. The daily operating selector is deliberately not substituted. Until a
separate exact Run287 packet-generation workflow is validated, days without
that packet safely skip the archive.

## Determinism and fail-closed tests

Synthetic tests verify:

- first append and exact same-date no-op;
- a later decision week append;
- rejection of an older observation;
- rejection of changed same-date weights;
- exact candidate-set and scenario-set matching;
- safe missing-packet behavior that preserves a prior READY archive;
- workflow ordering, cache, artifact, and Drive persistence references.

Local standard PR validation passed `167/167` in `212.23` seconds, including
the direct-fullrun guard, daily completed-close gate, portfolio/cash contracts,
PIT checks, workflow artifact contract, and public dashboard checks.

Canonical first-observation history hashes:

- `decision_history.jsonl`:
  `c5c444da8969e6cf5388d5cace19cce18612a1e46f96d341b711ba5d0ca53e15`
- `scenario_history.jsonl`:
  `9911152d62678f5bd5fa6ed8b23e75f365ffd2eb5100c7fa9b10d8b558ea9ede`
- `position_history.jsonl`:
  `60fbeb9396d6a6aebe3a4f5e4205106101944ad49ec13529594c6f498de26cf0`
- `candidate_risk_history.jsonl`:
  `f9d8cee12bb2ec5dfa002f205a00818ab128267ac32adc934dcccae746f96a5e`

## Next gate

After this archive change passes review, the next independent engineering
step is an exact Run287 current-packet producer workflow. It must reproduce the
already validated decision-frame, score-stack, no-write selector, and candidate
risk contracts without fullrun, target-book writes, or fallback to the daily
operating selector. That producer requires its own cost and artifact audit.

No stability or transition conclusion should be drawn before four distinct
weeks. No promotion review should open before twelve weeks and resolved forward
outcomes. Historical CAGR/MDD remains Main 34.4032% / -25.3619% and
Concentrated 49.0971% / -22.9552%.

The next zero-network half was implemented on 2026-07-14 in
`docs/CODEX_RUN287_EXACT_PACKET_PRODUCER_RESULT_20260714.md`. It produces the
no-write selector and candidate-risk pair only after a hash-pinned same-close
input registry is ready. Automatic decision-frame and score-stack registry
production remains the next independent gate.

## Evidence

- `docs/run287_decision_observation_archive_contract.json`
- `tools/archive_run287_decision_observation.py`
- `tests/run287_decision_observation_archive_smoke.py`
- `.github/workflows/daily_operating_selection_refresh.yml`
- `outputs/run287_decision_observation_archive/`

# R1000 Quant Engine Current Status

Status snapshot: `2026-08-23 10:05 KST` (`2026-08-23 01:05 UTC`)

Tracking issue: [#382](https://github.com/wscha231/r1000-quant-engine/issues/382)

## Executive status

| Boundary | Current status |
|---|---|
| Market scope | `US_ONLY` — Russell 1000 / US-listed security selection, backtest, and target research |
| Governance state | `RESEARCH_ONLY` |
| Intended account | Internal simulated-fill / virtual paper ledger |
| Live broker execution | `DISABLED` |
| Automatic champion promotion | `DISABLED` |
| Fullrun | Not authorized by this status snapshot |
| Daily source-data jobs | Partially healthy; freshness differs by source |
| Daily operating selection / virtual ledger | `BLOCKED_FAIL_CLOSED` |

This repository is the US engine. Korean-market code may be inspected as
reference, but is not part of this repository's canonical strategy, target, or
paper state.

The repository contains older Alpaca paper-execution utilities and a workflow
named `Live Extension Daily`. Their presence and names do not authorize broker
orders. `Live Extension Daily` is a forward-walk reporting job; it is not proof
of live trading or accepted virtual-ledger publication. No Alpaca paper or live
order path is canonical for the current Run287 operating flow.

## Canonical identities

These identities answer different questions and must not be substituted for
one another.

| Concern | Exact identity | Meaning |
|---|---|---|
| Source snapshot base | [`86ff31f3528ce62b6ebcf327d260e76ee6a872bb`](https://github.com/wscha231/r1000-quant-engine/commit/86ff31f3528ce62b6ebcf327d260e76ee6a872bb) | Protected `master` observed when issue #382 and this status branch were created. The P0-2 merge necessarily advances `master`; GitHub's default-branch head remains the source-publication authority. |
| Registered champion policy | [`819cbaa905bab6a455ed3e7c2a2a90ae2824833a`](https://github.com/wscha231/r1000-quant-engine/commit/819cbaa905bab6a455ed3e7c2a2a90ae2824833a) | `run287-generated-book-champion-20260710`, as declared by [`data_static/run287_promotion_state.json`](data_static/run287_promotion_state.json). This is a policy identity, not the current repository head. |
| Accepted metric evidence | [`dc735d9953ca195fde69930d16ff893b5786194f`](https://github.com/wscha231/r1000-quant-engine/commit/dc735d9953ca195fde69930d16ff893b5786194f) | Last commit touching [`data_static/run287_promotion_evidence_current.json`](data_static/run287_promotion_evidence_current.json); evidence `as_of_date` is `2026-07-10`. |
| Latest broadly scheduled data/operating code | [`8790af4dc520fa7962e7375390d7f42219896c40`](https://github.com/wscha231/r1000-quant-engine/commit/8790af4dc520fa7962e7375390d7f42219896c40) | Head used by most scheduled runs on 2026-08-19 through 2026-08-22. It is neither the champion policy identity nor proof of a completed paper session. |
| AutoLearning dependency fix | [`faf01e1cc2d30e7c5e125352cbc9ba9712151b85`](https://github.com/wscha231/r1000-quant-engine/commit/faf01e1cc2d30e7c5e125352cbc9ba9712151b85) | Restored the daily AutoLearning calendar dependency; the manual verification run succeeded. |
| Local recovery publication | [`86ff31f3528ce62b6ebcf327d260e76ee6a872bb`](https://github.com/wscha231/r1000-quant-engine/commit/86ff31f3528ce62b6ebcf327d260e76ee6a872bb) | P0-1 recovery manifest merge. It preserves lineage evidence and does not promote recovered code. |

`master` protection was observed with strict required checks `validate`,
`portfolio_guard`, and `review_complete`, enforced for administrators, with
required conversation resolution. Protection evidence is a GitHub setting and
is not encoded by a Git commit.

## Strategy and performance state

The tracked promotion state is `RESEARCH_ONLY`, has no official challenger,
allows neither production activation nor automatic transition, and explicitly
sets `live_trading_enabled=false`.

The current accepted fixture records:

| Sleeve | CAGR | Max drawdown | Mission constraint status |
|---|---:|---:|---|
| Main | `34.4032%` | `-25.3629%` | Fails the `MDD <= 25%` hard constraint by `0.3629%p`; CAGR is `0.5968%p` below `35%`. |
| Concentrated | `49.0968%` | `-22.9560%` | MDD passes; CAGR is `0.9032%p` below `50%`. |

These figures are fixture/promotion evidence, not a corrected current
fullrun. The tracked evidence also marks PIT no-lookahead, OOS, OOS2, cost,
stress, concentration, multiple-testing, and scorecard trust gates as not
passed. The [foundation review](docs/CODEX_RUN287_SYSTEM_FOUNDATION_REVIEW_20260727.md)
requires a separately approved corrected rebaseline before these numbers are
used as a new optimization authority. Issue
[#358](https://github.com/wscha231/r1000-quant-engine/issues/358) remains an
isolated parity-replay experiment and does not authorize promotion.

## Repository-visible operating evidence

GitHub Actions timestamps below are UTC. A green workflow run proves only that
the workflow completed; data-level freshness and durable paper publication need
their own evidence.

| Capability | Latest inspected evidence | Verdict |
|---|---|---|
| Free daily data | [Run `32538279577`](https://github.com/wscha231/r1000-quant-engine/actions/runs/32538279577), scheduled `2026-08-21 23:50`, success | `PARTIAL`: the run reported `status=completed` but `common_coverage_end=2026-07-02`. A green job does not prove full-universe prices through the prior close. |
| Earnings / estimates | [Run `32545141558`](https://github.com/wscha231/r1000-quant-engine/actions/runs/32545141558), scheduled `2026-08-22 02:02`, success | Prices/data reported through `2026-08-21`, but estimate coverage was `1/6` (`16.67%`) and the collector verdict was `blocked_partial_coverage`. Missing coverage remains neutral and cannot support promotion. |
| SEC Form 4 | [Run `32537831782`](https://github.com/wscha231/r1000-quant-engine/actions/runs/32537831782), scheduled `2026-08-21 23:42`, success | Index rebuild completed with `611,218` filing rows from `38` source files. Semantic PIT completeness was not independently re-audited in P0-2. |
| SEC 13F | [Run `32606451394`](https://github.com/wscha231/r1000-quant-engine/actions/runs/32606451394), scheduled `2026-08-22 23:54`, success | Artifact `9484657726`, digest `5d2bfd9d7bccc8d277de99e0b5cc90690ce16e0e81d85f23f8a4bf9a35f8eb35`; the workflow's Drive copy step completed. Signal acceptance is a separate gate. |
| Smart-money derivation | [Run `32607976292`](https://github.com/wscha231/r1000-quant-engine/actions/runs/32607976292), workflow-run trigger `2026-08-23 00:29`, success | Derived refresh completed after the 13F run; it does not alter the champion by itself. |
| Crisis monitor | [Run `32534478487`](https://github.com/wscha231/r1000-quant-engine/actions/runs/32534478487), scheduled `2026-08-21 22:48`, success | Monitoring artifact was produced. Durable synchronization and application to the latest paper transaction are not proven by this run alone. |
| After-close macro / regime | [Run `32557987910`](https://github.com/wscha231/r1000-quant-engine/actions/runs/32557987910), scheduled `2026-08-22 06:50`, success | `data_as_of=2026-08-21`; macro snapshot reported `neutral`, and the regime snapshot reported `normal`. This is monitoring evidence, not a completed target/ledger transition. |
| Daily AutoLearning | [Run `32554049412`](https://github.com/wscha231/r1000-quant-engine/actions/runs/32554049412), manual `2026-08-22 05:19`, success at `faf01e1...` | Dependency repair is verified once. The next scheduled run on the fixed head was not yet observed at snapshot time. Proposals remain challenger-only. |
| Daily operating selection / simulated ledger | [Run `32545955145`](https://github.com/wscha231/r1000-quant-engine/actions/runs/32545955145), scheduled `2026-08-22 02:19`, failure | `BLOCKED_FAIL_CLOSED`: the run stopped at `Restore verified risk-outcome accepted head` because a legacy outcome parent requires explicit one-time `workflow_dispatch` authorization. Price refresh, market snapshot, target books, macro freshness, and the paper transaction were skipped. |
| Last green daily operating run | [Run `30975268034`](https://github.com/wscha231/r1000-quant-engine/actions/runs/30975268034), manual `2026-08-05 04:29`, success | The selected catch-up session was `2026-07-24` while the latest completed NYSE session was `2026-08-04`. Green status is not evidence that every later session was durably processed. |
| Monthly research | [Run `31913424489`](https://github.com/wscha231/r1000-quant-engine/actions/runs/31913424489), scheduled `2026-08-15 22:56`, success | Research automation completed; it cannot promote the champion. |
| Quarterly Auto-Learning | [Run `28505491747`](https://github.com/wscha231/r1000-quant-engine/actions/runs/28505491747), scheduled `2026-07-01 08:51`, success | Historical learning review only; no automatic policy activation. |

At the snapshot time the repository has `40` workflow YAML files. This file
does not assign writer authority to all of them; P0-3 must complete that census.

## Virtual paper account truth

The repository contract names the durable Google Drive account and ledger as
the canonical accepted paper state. P0-2 did not directly read or mutate that
Drive state. Therefore the exact accepted holdings, cash, ledger tip, and last
durably completed market session are `NOT VERIFIED` in this snapshot.

The latest failed operating run observed an immutable remote terminal hash
`65fa6f5b4b12729811b72a90661fc744320826dfe868ec6da2632768b1ec02a7`,
but then failed before selecting/migrating the legacy outcome parent. That hash
is discovery evidence only; it is not a claim that the `2026-08-21` paper
session completed.

Do not rerun the transactional daily workflow blindly. Resume only through its
explicit chronological catch-up / one-time migration contract after verifying
the accepted Drive head, intended session, artifact digest, idempotency, and
required authorization.

## Active blockers and next actions

1. **P0-5 operating blocker:** issue
   [#357](https://github.com/wscha231/r1000-quant-engine/issues/357) remains
   open, and its failure boundary still reproduces on run `32545955145`.
   Diagnose and authorize the narrow legacy-parent migration without changing
   alpha, risk thresholds, target policy, or ledger semantics.
2. **Price freshness ambiguity:** the green free-data run's common coverage
   ended on `2026-07-02`, while a later earnings workflow obtained coverage
   through `2026-08-21`. P0-3/P0-4 must identify which dataset is the official
   selector input and hash its exact coverage before P0-5 publication recovery.
3. **Paper state not reconciled:** inspect the canonical Drive head read-only
   before any catch-up dispatch; preserve chronological NYSE sessions and
   fail-closed behavior.
4. **Workflow authority unresolved:** classify all 40 workflows by inputs,
   outputs, durable writes, target writes, paper-ledger writes, broker-facing
   behavior, and promotion authority in P0-3. In particular, classify the
   contents-writing `Live Extension Daily` path and every Alpaca paper utility
   as noncanonical unless separately approved.
5. **Research baseline incomplete:** no corrected canonical rebaseline or
   accepted challenger exists. Do not dispatch a fullrun or parity replay until
   its named preflight and explicit approval are present.
6. **P0 sequence:** complete P0-3 branch/PR/workflow census, then P0-4 dataset,
   model, and artifact hash inventory. Repair the daily operating path in an
   isolated P0-5 PR; do not mix it with alpha or learning changes.

## Change safety for this snapshot

- Fullrun executed: `false`.
- Target, order, paper-ledger, or broker-book mutation: `false`.
- Production or live trading enabled: `false`.
- Champion or challenger promoted: `false`.
- Existing recovery branches or user worktrees modified: `false`.

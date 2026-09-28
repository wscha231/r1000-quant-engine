# Run287 U0 branch/result census refresh — 2026-08-21

## Conclusion

The exact-head GitHub census was rebuilt against protected `master` commit
`8790af4dc520fa7962e7375390d7f42219896c40` by research-only Actions run
[`32469837458`](https://github.com/wscha231/r1000-quant-engine/actions/runs/32469837458).
It did not run a backtest, build a target, generate an order, mutate a paper
ledger, or promote a model.

The repository now has 290 remote branches, not 287.  The census found 365
experiment candidates representing 364 distinct exact code heads.  After the
53-attempt lower bound already preserved by the canonical do-not-repeat
registry, the conservative historical trial-count floor is 417.

| Measure | 2026-08-05 diagnostic | 2026-08-21 refresh | Change |
|---|---:|---:|---:|
| Remote branches | not recorded in the v3 design summary | 290 | — |
| Experiment candidates | 351 | 365 | +14 |
| Distinct exact code-head trials | 350 | 364 | +14 |
| Conservative historical trial floor | 403 | 417 | +14 |
| Unverified assertions | 345 | 359 | +14 |
| Changed-path-incomplete canonical groups | 13 | 13 | 0 |

The diagnostic artifact hashes are:

- source U0-v2 census: `058b661ace821dbe945440ad4c6ad093bd4d8f2ddbec59bf6a356cc9eb10a021`
- conservative U0-v3 recovery census: `812bdd2b0d7e72981e965db937b93324b15b2d211f975659f9e453ca1ac7bba4`

## Branch and PR topology

- branches: 290
  - ancestor of current master: 65
  - identical to current master: 1
  - orphaned from current master: 224
- pull requests: 365
  - merged: 237
  - open: 105
  - closed without merge: 23
- experiment candidates: 365
  - PR-linked: 360
  - branch-only: 5
- Run287-named branches: 114
- Run287-named PRs: 116

An ancestor branch is not automatically an accepted experiment, and an
orphaned branch is not automatically useless.  These counts describe Git
topology only.  They do not authorize merge, cherry-pick, performance claims,
or branch deletion.

## Branch-only candidates

The five candidates with no exact PR link remain blocked until their changed
paths and trial identities are recovered:

| Branch | Ancestry | Preliminary capability family |
|---|---|---|
| `codex/alphaops-integrated-replay` | ancestor | expected return/scoring |
| `codex/broker-ledger-replay-foundation` | orphaned | execution/ledger |
| `codex/goal-risk-replay-fullrun` | ancestor | risk/cash/crisis |
| `codex/run287-sec-capital-actions-20260717` | orphaned | SEC/PIT data |
| `codex/score-sizing-closeout-repro-audit-20260627` | orphaned | expected return/scoring |

## Recoverable evidence is still not performance evidence

Only six candidates have a stronger classification than an unverified legacy
assertion:

- orphaned summary recoverable: PRs
  [#170](https://github.com/wscha231/r1000-quant-engine/pull/170),
  [#171](https://github.com/wscha231/r1000-quant-engine/pull/171),
  [#178](https://github.com/wscha231/r1000-quant-engine/pull/178), and
  [#209](https://github.com/wscha231/r1000-quant-engine/pull/209)
- source-screen only: PRs
  [#278](https://github.com/wscha231/r1000-quant-engine/pull/278) and
  [#303](https://github.com/wscha231/r1000-quant-engine/pull/303)

The other 359 candidate records remain `UNVERIFIED_ASSERTION`.  Even the six
rows above lack synchronized daily after-cost return series and therefore may
not replace or support the champion.

## Incomplete changed-path evidence

The current completion gate is blocked by truncated changed-path metadata.
The directly identified PRs are
[#5](https://github.com/wscha231/r1000-quant-engine/pull/5),
[#6](https://github.com/wscha231/r1000-quant-engine/pull/6),
[#11](https://github.com/wscha231/r1000-quant-engine/pull/11),
[#16](https://github.com/wscha231/r1000-quant-engine/pull/16),
[#49](https://github.com/wscha231/r1000-quant-engine/pull/49),
[#62](https://github.com/wscha231/r1000-quant-engine/pull/62),
[#147](https://github.com/wscha231/r1000-quant-engine/pull/147), and
[#212](https://github.com/wscha231/r1000-quant-engine/pull/212).
Across their shared code-head groups this affects 13 canonical candidate
groups.  The next census repair must retrieve complete path and commit lists;
it must not infer missing paths from titles or branch names.

## Historical performance cutoff

The accepted historical performance evidence remains through the completed
2026-07-10 NYSE close:

| Portfolio | CAGR | MDD |
|---|---:|---:|
| Main | 34.4032% | -25.3629% |
| Concentrated | 49.0968% | -22.9560% |

PR #212's older 2019-06-03 through 2026-06-25 report of Main
`36.82% / -24.76%` and Concentrated `50.07% / -24.96%` remains historical
evidence only.  It used a different baseline, data window, target book, and
execution contract.  It must be parity-replayed on current master rather than
merged.

Work after July 10 includes current-decision, forward-paper, crisis, macro,
data-readiness, and shadow evidence.  None of it is a replacement historical
CAGR/MDD backtest.

## Conservative disposition

The census cannot yet assign final A–F dispositions safely.  Until evidence is
recovered:

- the 359 unverified assertions remain quarantine/F by default;
- the four recoverable summaries are recovery candidates, not merge
  candidates;
- the two source screens are signal evidence only, not portfolio evidence;
- a C bug-fix or D alpha designation requires a minimal diff review against
  current master and an exact trial manifest;
- no branch may be bulk-merged, bulk-cherry-picked, deleted, or used for
  champion replacement from this census alone.

## Next gate

1. Repair complete changed paths and commit OIDs for the eight directly
   identified PRs and regenerate U0 at the then-current exact master SHA.
2. Recover the five branch-only changed-path sets and link aliases to exact PR
   heads where possible.
3. Recover exact parameter/data hashes, target/cash/cost contracts, and daily
   after-cost returns for one candidate family at a time.
4. Keep issue [#358](https://github.com/wscha231/r1000-quant-engine/issues/358)
   as the parity-replay queue for the old goal-crossing hooks.
5. Request explicit approval before one named full broker-ledger replay.  No
   broad fullrun is authorized by this census.

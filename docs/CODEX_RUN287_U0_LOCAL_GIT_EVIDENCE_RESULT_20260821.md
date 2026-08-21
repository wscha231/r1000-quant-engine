# Run287 U0 local Git evidence repair — 2026-08-21

## Conclusion

The U0 exact-head census can now recover changed paths and commit OIDs from the
exact GitHub-captured PR base/head objects when legacy GitHub metadata is
missing, contradictory, or capped.  Complete GitHub path sets remain
authoritative; the local fallback is used only for incomplete evidence.

The workflow fetches all branch heads and immutable PR head refs before the
census.  The fallback uses:

- one exact `merge-base` for the captured base/head pair;
- the three-dot, rename-aware Git diff for changed paths;
- the exact `base..head` commit list;
- explicit source labels and SHA-bound hashes in the census output.

If either object is absent, the merge base is ambiguous, a path record is
malformed, or the exact head is absent from the commit list, the record remains
blocked.

## Root cause

For eight old PRs the GitHub REST detail endpoint currently reports
`changed_files=0` even though its pinned files endpoint returns paths.  PR #11
also exceeds GitHub's 3,000-file PR-files cap.  Exact local Git evidence gave:

| PR | Local changed paths | Exact base..head commits |
|---|---:|---:|
| #5 | 2,347 | 136 |
| #6 | 1,502 | 10 |
| #11 | 13,414 | 131 |
| #16 | 1,482 | 46 |
| #49 | 1,076 | 4 |
| #62 | 1,480 | 228 |
| #147 | 2,646 | 38 |
| #212 | 2,280 | 20 |

For #5, #16, and #49 the GitHub files endpoint, GraphQL changed-file count,
and exact local Git path count agree.  For the other records the local diff is
the only complete exact-head source available; titles or branch names are not
used to invent paths.

## Preflight result

The repaired collector and conservative recovery classifier were executed
locally against audit master
`8790af4dc520fa7962e7375390d7f42219896c40`.  The live namespace had advanced
to 291 branches and 366 PRs/candidates because the new census documentation PR
had been opened during this work.

- canonical exact code-head trials: 365
- conservative historical trial floor: 418
- `historical_experiment_census_complete`: `true`
- `historical_challenger_preregistration_ready`: `true`
- census completion blockers: none
- unverified ancestry canonical trials: 0
- U0-v3 acceptance envelope: created successfully

Preflight hashes:

- source U0-v2 census:
  `c2b4b15c3e42bd76eed8b04c40a9c18df64546479dca19db69811e48666aeb1a`
- recovery U0-v3 census:
  `c0bf64b670d49503dfd99d9a7ff3f84d16e00397c39b11ad0937ba469b28392b`
- repository namespace:
  `0e4073bfff9f4354a66ea6cf7cde8458088a36bde8c7a736af484ad95bdb9675`

## Safety boundary

The accepted evidence authorizes only the narrower preregistered research-fit
stage.  It explicitly keeps all of the following false:

- historical broker backtest allowed
- fullrun allowed
- target/order/ledger mutation allowed
- legacy result promotion allowed
- automatic promotion allowed
- production or live trading allowed

All 365 legacy trials still lack exact parameter/data hashes, verified PIT
contracts, target/cash/cost contracts, and synchronized daily after-cost return
series.  Completing the census does not validate their reported CAGR or MDD.

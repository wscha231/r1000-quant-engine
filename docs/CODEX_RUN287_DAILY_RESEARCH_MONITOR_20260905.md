# Daily research monitoring connection

The requested workflow reuses GitHub data, fills gaps from primary sources,
adds industry/moat research, and investigates disagreements with the engine.
This change adds the observable handoff and daily health checks. It does not
claim that today's investment ranking or the trading system has been repaired.

## Observed blocker

- Inspected master: `34bab52743c238c3419db0d03d17a366645459da`.
- Daily operating run `33947924742`, job `101257262458`, failed at
  `Restore verified risk-outcome accepted head` before current decision inputs.
- Its receipt reported
  `BLOCKED_ONE_TIME_LEGACY_QUARANTINE_AUTHORIZATION_REQUIRED` and
  `obtain_separate_user_approval_before_workflow_dispatch` for the
  2026-09-04 session. No recovery dispatch is part of this change.
- After-close run `33932795788` reported target day 2026-09-04, price day
  2026-08-24 and scored rebalance date 2026-07-13. A successful workflow is
  therefore insufficient evidence of current investment inputs.

## Implemented connection

`run287_daily_research_monitor.yml` reads the latest master run for four
explicit workflows: daily operating, after-close tactical, earnings estimates,
and Smart Money. It never substitutes an older successful run for a newer
failed or running run. It checks run/commit identity and the archive SHA-256,
then reads only exact JSON/CSV member paths without extracting or executing
artifact contents. Downloads and individual members have size ceilings.
All configured members are required except the explicitly optional operating
recovery receipt. Missing members generate source-level and file-level alerts;
available failure diagnostics remain readable. Smart Money also accepts its
canonical `workflow_run` event from the quarterly SEC producer.

The report records recovery status, model and price dates, collection dates,
requested estimate coverage separately from archive coverage, quarterly 13F
period separately from collection date, and independently refreshed price
archive coverage. A 33-name US/KR research queue joins available, exact-date US
prices and timestamped disclosed ownership scores. Missing fields remain null;
Korean symbols retain leading zeros and are not scored using US data.

Outputs are `report.json`, `report.md`, and `research_queue.csv` under a new
run/attempt directory, retained in an Actions artifact for 45 days. The job's
success means the monitoring report was produced, not that its inputs are
current or an investment ranking is approved. Current ranking remains withheld
until a separate validated ranking handoff exists.

The new schedule runs at 08:25 UTC / 17:25 Korea time. A same-repository PR run
exercises the integration with a token limited to reading contents and Actions.
It uses no provider, Drive, broker or messaging secrets. Scheduled runs become
active only after publication to the default branch; no deployment is claimed
by creating the branch or PR.

## Research and remaining work

The user-facing daily task is configured around 19:00 Asia/Seoul. It reads the
GitHub report or its original source runs, supplements missing facts from primary
web sources, and reports changed candidates and disagreements. The existing
Saturday research task now also reads GitHub first.

The monitor itself does not obtain long price histories, Korean fundamentals,
patent claims, valuation models or earnings forecasts. These remain explicit
research gaps. It must not turn an operational failure into low company quality.
No new composite weights or return forecasts are invented. Testing a new moat
factor requires PIT availability, an economic hypothesis, purged walk-forward
validation, costs, multiple-testing correction and an untouched holdout. Such
research execution remains subject to the existing separate approval boundary.

The existing bounded upstream producer can refresh frozen model inputs without
fullrun, but today's transactional pipeline reaches its approval gate before
that producer. Restoring that pipeline remains the separate exact-session
recovery task; this monitor neither bypasses nor executes that recovery.

## Validation and publication

The focused suite checks stale/future/invalid dates, partial estimates despite
full archive coverage, missing values, leading-zero Korean identifiers,
disclosure timing, duplicate prices and ZIP members, archive digest mismatch,
failed/running run selection, market holidays, early closes and source
immutability. The already registered `workflow_artifact_smoke.py` invokes this
suite, so Tier-1 CI exercises it without changing protected validator pins.

Local artifact downloads through temporary connector storage URLs returned
HTTP 403 / error 1010. This is recorded as a local transport limitation, not a
successful real-artifact verification. The read-only PR workflow provides the
GitHub-runner integration check; inspect its actual output before claiming it
works with current artifacts.

No fullrun/backtest, selector/model/risk-limit change, order, target/ledger
mutation, migration/quarantine, catch-up, PR #394 merge or recovery dispatch
was performed. The pre-existing user-owned holdings CSV is excluded from the
commit and must retain its original SHA-256.

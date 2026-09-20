# [PROJECT_HANDOFF] Theme/ETF source admission and monitor connection

Scope: issue #433, T01 consumer implementation; global coordination remains
#448. Audited source: `f20410549464e3f2557ae6d90ba8b20ee8bcc42e`.

## Implemented connection

The existing daily research monitor routes an optional, exact-path bundle from
its authenticated operating artifact into
`research.theme_etf_runtime_v1.strict.run_payload`. It writes an internal
`theme_etf_bridge.json` and adds admission/coverage observations to its report.
There is no new collector, cron, universe engine, company evaluator, candidate
packet or backtester. No target, ledger, champion or selector policy is changed.

The adapter verifies GitHub-provided producer identity and actual ZIP bytes,
then exact component, receipt and raw-object bytes. Six components are required:
base universe, securities, prices, ETF snapshots, documents and membership
events. Even empty lists must have explicit receipts. Failed, missing or
running upstream work cannot be replaced by an older successful artifact.

Every proposed ID receives an evaluation reconciliation row, including
`BLOCKED_COMPANY_EVALUATOR_RECEIPT_MISSING` and null 1/3/6/12-month returns. No
model score, neutral missing value, investment rank or evaluation success is
fabricated. This complements the separate input-integrity PR #463, whose
unmerged code is not imported here.

## Source contract and trust boundary

The extension is in the existing monitor contract under `theme_etf_bridge`.
The optional manifest path is
`outputs/theme_etf_bridge/attempts/{run_id}-{run_attempt}/source_bundle.json`.

The manifest uses schema `theme-etf-source-bundle-v1`, with `decision_at`,
`producer` and `components`. Producer fields are repository, workflow, head_sha,
run_id and run_attempt. Each of the six components has `data` and `receipt`
references, each containing an exact member `path` and actual-byte `sha256`.

Each `theme-etf-component-receipt-v1` binds the same producer, role, data hash,
validation timestamp and nonempty raw-object references. Usable receipt states
are COLLECTED/UNCHANGED, with no failures and a research-only boundary. Paths
are confined to the fixed research prefix. Duplicate keys/members, oversized
objects, traversal, nonfinite JSON and nested execution authority are rejected.

The public monitor obtains metadata from GitHub, not from the ZIP. The pure
reader assumes its caller supplies this authenticated metadata and reviewed
repository policy. Calling it directly with fabricated metadata is not an
authentication mechanism. Hashes/receipt labels do not certify economic truth,
provider rights or normalization methodology. A reviewed upstream producer and
normalizer are still required before real data can be published here.

In particular, source `reviewed=true` cannot authorize a business LINK.
`approved_membership_reviews` is a separately reviewed repository mapping from
canonical event hashes to reviewer identity, review timestamp, decision and
exact document hashes. **The shipped mapping is empty.** No real relationship
is approved by this PR. A future reviewer service must preserve that independent
trust boundary; it must not build the mapping from the untrusted bundle.

The base requires at least 1,000 distinct IDs with registry coverage. This
rejects small/theme fallback cohorts but does not certify Russell membership;
the producer must establish the actual cohort identity. Prices require USD/SPY,
a declared distributions-reinvested total-return methodology, the current
settled NYSE session, after-close availability and contiguous benchmark
sessions. Adjusted close is never inferred to be total return. Methodology
claims still need the reviewed normalizer described above.

## Whole-system interfaces

| Existing owner | Bridge output/use | Remaining boundary |
|---|---|---|
| #435/#436 | Existing strict runtime; raw ETF units/coverage | Live issuer adapter |
| #445, head `9f0f63e4…` | Existing MembershipReason field shape | Preview only; unmerged composer |
| #451, head `2125c0c7…` | Existing candidate-data-queue-v1 shape | Preview only; no canonical writer/packet |
| #459, head `803a4442…` | Documents treated as data | Unmerged news producer; not invoked |
| Existing company evaluator | Every ID reconciled with missing receipt | No evaluator execution or return claim |
| Monitor / Pages | Internal admission status; public allowlist retained | No raw bridge/source publication to Pages |
| #458/#460/#461, regime/account | Separate downstream authority | No fullrun, OOS, account or metric change |

The membership score bonus is zero and selector authority is false. Queue
preview rows remain DATA_PENDING until genuine per-channel receipts exist.
100% accounting of requested IDs is not 100% completed company analysis.
Expected-return evaluation and portfolio risk remain separate from leadership.
Consumers must recheck current versions before canonical integration.

## Additional V1 limitations found

1. Membership resolution is keyed by security, not `(theme, security)`. A
   second theme's UNLINK can erase another relationship. Multi-theme histories
   are blocked here until a separate lifecycle fix is reviewed.
2. ETF snapshots are primarily ordered by availability. A late historical
   report can look like the newest composition. Decreasing holdings-as-of
   sequences are blocked until the historical adapter is reviewed.

Neither block deletes the base or permits a sale. Partial ETF absence remains
ABSENCE_UNCONFIRMED; an independently approved business relationship can remain.

## Actual evidence inspected

#435 merged as `74765812b8f198818289ae1e082ee0ac70b18c2a`; #436 merged as
`580deea81a2ef47fae0bdbfe5d50663e07d45449`.

Latest inspected [monitor run 35443247344, attempt 1](https://github.com/wscha231/r1000-quant-engine/actions/runs/35443247344)
used audited master. Artifact 10584611169 matches locally available ZIP bytes:
`b0249034cdd2ec7d81e3bd8f7fd781d756409a8ea596d8703e97cba55007e665`.
Its report's expected session is 2026-09-18. The report states:

- operating run 35424976962 / attempt 1 / `90b55fe92f25236c663a71cad7ab9138da497919` failed;
- recovery is BLOCKED_ONE_TIME_LEGACY_QUARANTINE_AUTHORIZATION_REQUIRED;
- operating upstream, market and price members are missing;
- estimates coverage is 1/6, with blocked_partial_coverage;
- verified current engine-score count is zero.

Replaying that authenticated report's operating-source status at the new
observation boundary returns BLOCKED / upstream_not_verified. This verifies
monitor ZIP bytes and its reported state, not a new upstream source-byte audit,
Drive accepted-state audit or live evaluator cycle. No transactional job was
rerun. The separate operating ZIP download could not be materialized locally;
it is not included in the byte-verification claim.

## Validation and next boundary

30 new unittest methods pass, including an authenticated artifact-to-strict
runtime synthetic cycle with 1,118 base IDs plus one ADR candidate. Tests cover
complete ID reconciliation, hash/receipt/document/event binding, producer and
attempt mismatches, units/partial holdings, calendar/freshness, authority
injection, replay and the lifecycle blocks. They also pass under Python -O;
repeated executions are not additional test counts.

19 existing monitor tests, 11 existing strict-runtime checks, one benchmark
anchor check and eight public-output tests also pass. New tests run through the
existing monitor CI entry point. The protected Tier-1 registry and review gates
are unchanged. Monitor/Pages sparse checkouts include the strict runtime.
Compilation, YAML parsing and explicit diff checks pass. No cron or permission
is changed; only PR path matching is extended for the new code/tests.

Exact-head remote CI and independent review are separate publication gates.
The synthetic cycle is not live-data completion. A real producer bundle does
not yet exist, business-review pins are empty, company evaluation is unconnected
and #445/#451/#459 canonical consumers remain pending. Next causal work must
supply genuine producer/normalizer/reviewer receipts, fix the isolated lifecycle
defects, then verify a bounded real cycle, following-session replay and restore.
Durable account recovery remains a separate authorized workflow.

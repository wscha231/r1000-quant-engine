# A4 cloud research and recovery

Primary-source capture is an additive opt-in producer in this same workflow;
see [its bounded collection/storage contract](A4_PRIMARY_DATA_OPERATIONS.md).
Its separate enable flag does not imply reviewed learning inputs or A5 readiness.
With primary capture enabled, market inputs use the capture attempt directory;
`--learning-input-root` keeps the original restored learning bundle independently
available and validated. Without that option, the library/CLI retains its single
input-root behavior. Neither mode creates or approves a learning policy.

The existing Daily Crisis Monitor runs on GitHub-hosted Ubuntu. Its schedule
and manual dispatch are independent of the developer's PC. Google Drive under
the existing configured base stores `outputs/a4_research/state` and immutable
`outputs/a4_research/attempts/<run-id>-<attempt>`. No additional paid server,
desktop scheduler, trading process or second accepted-state authority is used.

## Activation prerequisites

The feature defaults OFF. Merge only after exact-head independent review,
required CI, review_complete and expected-head protection. Then supply the
existing source owner with the required current-session A4 v2 request and its
original SHA file under `outputs/market_analysis_inputs`. Source collection is
still performed by the existing approved producer; this consumer makes zero
provider requests. Adding TGCR/H8 scope does not extend an old provider profile.

`A4_RESEARCH_ENABLED=true` enables the new consumer in the existing workflow.
`A4_RESEARCH_ALLOW_STATE_GENESIS=true` is allowed only for the initial empty
namespace. A successful parent inventory must prove `a4_research` absent;
quota/auth errors or an existing namespace refuse genesis. Disable the variable
after the first verified publication. Existing state must always restore and
pass `rclone check` before computation. A per-workflow single writer prevents
overlapping checkpoint publications.

Authentication must be verified for the actual hosted secret, separately from
the desktop profile. The desktop's shared rclone client listed the commit folder
once, then returned403 project requests-per-minute quota on bounded metadata
reads; no current catalog/execution or original packs were verified. Rclone's
[official Drive instructions](https://rclone.org/drive/#making-your-own-client-id)
recommend an owner client_id and document retirement of the shared client in2026.
Use the existing approved OAuth configuration in `RCLONE_CONFIG_GDRIVE`, or the
existing approved service-account route, with the same durable namespace; verify
actual read and research checkpoint readback before activation. Listing success
alone does not prove stable access, source readiness or persistence.

Set `A4_LEARNING_POLICY_SHA256` to the SHA256 of the original reviewed private
policy file. Leave it empty while source rights or input qualification is
unresolved: diagnosis still emits, learning is visibly blocked, and the overall
cycle is partial. The latest Source contract currently disables FRED learning;
neither a new CSV nor this code grants rights to train on retained FRED bytes.
Do not log signed URLs, credential-bearing provider URLs or secret values.

## Learning request and evidence

`learning_request.json` has schema `a4-learning-request-v1`, hash-bound `inputs`
and `policy` references (`path`, `sha256`), and an `originals` mapping from SHA256
to the same bounded references. Paths stay under the restored input root.
The policy's original file hash is supplied independently through the workflow
variable; its canonical decoded hash is also bound by the mathematics API.

Inputs use schema `a4-macro-learning-inputs-v1`: a cutoff, the complete actual
NYSE `sessions` (`session`, `close_utc`), original-bound `observations` using the
A4 source register, and target-keyed `prices`. Price rows contain session,
value, actual available_at, original_sha256 and one consistent return_basis.
The producer must build this packet using the existing verified Lake/Reader
and retain original source/normalization receipts. A raw-hash replay alone
does not authenticate Reader identity, historical PIT or supplier rights.

The external policy schema is `a4-learning-input-policy-v1`, purpose
`MACRO_RELATIONSHIP_RESEARCH`, with available_at/expires_at, exact input_pins,
reviewed_rights_pins, reviewed_source_receipt_pins, and source_bindings by original
hash. Each binding includes size_bytes, source_ids, purpose, historical_use
(`FORWARD_CAPTURE_ONLY` or `DATE_ARCHIVE_RESEARCH_ONLY`), rights_evidence_sha256
and source_receipt_sha256. It also supplies the four-field do-not-repeat
trial_identity. Target prices require the exact `price:<ETF>` member in that
original's reviewed source_ids; a macro-only or other-ETF binding is insufficient.
Source membership, units, clocks, file sizes and original bytes
are rechecked. The policy is externally reviewed evidence, not a declaration
that this consumer independently qualified every source.

## Cadence and immutable state

Every run diagnoses the latest completed NYSE session. Weekly scoring uses only
previously recorded, fixed predictions and complete matured next-close paths.
Monthly trials reuse the incumbent expanding regression, HAC intervals and BY
correction across every declared test, including missing/negative tests.
Actual price-label availability is additionally checked at each historical
training anchor. Source frequency is preserved; weekly releases do not become
five independent daily samples. One-session realized volatility is unknown.

Trial files are content-addressed under `state/trials`; identical writes reuse
bytes and conflicts refuse. All 14 targets, seven horizons and three outcomes
remain in the declared family. Writer and restore share a32MiB per-trial budget;
oversized trials are refused before entering state. Weekly scoring caches each
target/horizon path once per call without changing missing or immature results.
Weekly-score and forward-prediction checkpoints share an8MiB write/restore
budget. Oversized populations are blocked before checkpoint publication; the
attempt remains visible and does not certify a completed weekly checkpoint.
Insufficient evidence remains in the family. New trials are
challenger proposals. To explain a later A4 report with a fixed release, an
external policy must explicitly bind active_trial_sha256 and reviewed_trial_pins.
Code/math/feature-recipe changes refuse the old release until independently
reviewed. There is no best-trial auto-selection or champion replacement.

For the fixed release to be part of the report reviewed by A3/A6, include one
`learning_release` input in the native A4 v2 request. Its original JSON contains
exactly `trial` and `policy`; `sha256` binds those file bytes and `policy_sha256`
binds the canonical encoded reviewed policy. The source owner must independently
review this pin. The separate `learning_context.json` cloud diagnostic does not
replace the native request-replay report or enter A5 as an alternate A4 report.
New auxiliary forecasts retain the actual execution creation clock, even during
fixed-report replay. They cannot be recorded after their next-close entry.
The existing forward monitor admits the larger v2 relationship payload within
its scoped16MiB member/32MiB archive limits; global transport limits and exact
artifact, member, session and clock checks remain in force.

Persist and `rclone check` the state and attempt before recording a separate
transport readback witness. A computation result itself keeps
durable_remote_verified=false. Upload failures fail the job; failed attempts
remain diagnostics and never advance an accepted model or portfolio pointer.
Recovery starts from the verified Drive state, not files on this PC. Do not
blindly rerun transactional legacy steps; follow their existing contracts.

## Independent A5 model proposals

The optional `a5_request.json` uses schema `a5-model-proposal-request-v1` with
hash-bound `inputs`, `registry`, `policy` and optional `previous_proposal` paths.
`A5_MODEL_POLICY_SHA256` independently pins the original policy file. Inputs
reuse the existing MODEL_PORTFOLIO request, bounded A3 original artifact loader
and current A6 review graph. The graph must replay the exact native A4 v2 report.
The reviewed risk packet additionally binds `a4_report_content_sha256` and
`a4_request_sha256`; current A3 net returns and reviewed allocation limits pass
through the incumbent independent allocator.
Every security in the submitted allocator registry (except its benchmark) must
have a current original A3 reference. Legacy evaluation rows are refused.
The cloud cycle replays A4 at the fixed A5 decision time from the independently
pinned policy/input packet. It separately checks current NYSE session and A4
request expiry at execution time, and refuses execution after the reviewed
profile expires. Replaying the decision never refreshes its timestamp or hash.

The output includes security and cash weights, selection/exclusion reasons,
original cost assumptions, macro evidence and changes against an externally
reviewed previous model proposal. `reviewed_pins.model_proposal_history` binds
that previous decoded proposal's canonical digest. This comparison is research
history and never an account position book. Successful proposals are immutable
under `state/model_proposals`; no accepted portfolio pointer is advanced.
Missing A3/A4/A6 or policy evidence writes a BLOCKED diagnostic with null weights
and cash plus owner routes. It is not the first completed portfolio.

## Deployment status

Code and synthetic validation are separate from activation, actual source
readiness, a scheduled run, Drive readback and the first qualified A5 proposal.
Those are individually evidenced milestones. Missing current A3/ER, A4 or A6
inputs remain blockers; no artificial all-cash proposal is published.

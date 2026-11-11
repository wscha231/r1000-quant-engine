# A4 cloud research and recovery

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
trial_identity. Source membership, units, clocks, file sizes and original bytes
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
remain in the declared family, including insufficient evidence. New trials are
challenger proposals. To explain a later A4 report with a fixed release, an
external policy must explicitly bind active_trial_sha256 and reviewed_trial_pins.
Code/math/feature-recipe changes refuse the old release until independently
reviewed. There is no best-trial auto-selection or champion replacement.

Persist and `rclone check` the state and attempt before recording a separate
transport readback witness. A computation result itself keeps
durable_remote_verified=false. Upload failures fail the job; failed attempts
remain diagnostics and never advance an accepted model or portfolio pointer.
Recovery starts from the verified Drive state, not files on this PC. Do not
blindly rerun transactional legacy steps; follow their existing contracts.

## Deployment status

Code and synthetic validation are separate from activation, actual source
readiness, a scheduled run, Drive readback and the first qualified A5 proposal.
Those are individually evidenced milestones. Missing current A3/ER, A4 or A6
inputs remain blockers; no artificial all-cash proposal is published.

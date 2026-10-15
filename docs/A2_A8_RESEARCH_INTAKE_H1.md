# A2/A8 research intake H1

Task: `R1000-A2-A8-RESEARCH-INTAKE-CONTRACT-H1-20261015`.
Base: current master `8a30f94f4d8b30b8f93791d85b9abe15ae83e8f5`.
Classification: supplied-byte research proposals only; no deployment approval.

## Existing boundaries and inputs

`research/a2_research_intake_v1.py` reuses the existing A3 source-graph and ER
validators and `candidate_registry_v1.build_reference_index`. It creates no
second persistent registry, source adapter, risk engine, scheduler or writer.

Callers supply exact JSON bytes, an explicit timezone-aware cutoff, a
`MemoryArtifacts` inventory of already-held bytes, and identity-assertion JSON.
Arbitrary resolver callbacks are refused. The inventory is bounded and sealed;
this is an in-process pure API, not a sandbox against malicious Python code.
The module performs no network, filesystem, subprocess, persistence or wallclock
access. Schema files must be supplied as `SCHEMA:<filename>` inventory entries
with their exact code-pinned SHA256. Schema resolution cannot fetch remote refs.

Identity assertions have exactly `scope=SUPPLIED_US_IDENTITY_ASSERTIONS` and
`rows`, each containing `security_id`, `issuer_id`, `tickers`, `country=US` and
`currency=USD`. These caller assertions do not authenticate identity, historical
listing, corporate actions, rights, PIT, source review or a canonical current
pointer. Missing mappings are refused; ticker-only inference is absent.

## API and semantics

All public validation functions return proposals or raise bounded `IntakeError`.
All inputs use strict duplicate-key decoding. Byte, lexical depth and token
limits are checked before allocating the JSON tree. Unknown fields, nonfinite
numbers, number/boolean confusion and naive clocks are rejected. No guard uses
Python `assert`. Default bounds: 4MiB/object, depth32, 50,000 lexical tokens,
10,000 in-memory artifacts and 32MiB total artifact bytes; lexical array
entries1000 (identity-assertion decoding explicitly allows10000). The byte/token
bounds still apply to identity assertions. Native test corpora may restore
CRLF schema checkout bytes to LF only when the result matches the exact static
schema hash; the runtime API never normalizes evidence.

- `validate_events(raw, cutoff=..., artifact_resolver=..., identities=...)`:
  validates the event schema, publication <= availability <= collection <=
  supplied as_of <= cutoff, observation <= collection and expiry >= collection.
  The canonical direct-score field is `score_contribution=0`. Old aliases are
  unknown fields. V0 requires null graph references and null verified_fact,
  assessment=false and a discovery/watch/refusal state. Telegram/community
  stays discovery-only even when its tier is relabeled. V1/V2 requires exact
  graph/raw bytes, matching subjects and the existing A3 source rules. Identical
  raw bytes and repeated publisher families cannot manufacture independent
  groups. Semantic independence and authentic reviewer identity remain separate
  upstream gates. Even graph-consistent input emits assessment=false and
  canonical_verified=false; this H1 does not execute admission transitions.
- Clusters sort by aware available_at then immutable event_id. The key is the
  sorted issuer/security set plus event_family. The first event anchors an
  inclusive24h interval; headlines cannot extend the interval by chaining.
  Ticker aliases do not multiply security identities. Active research watches
  are capped at30 securities and10 themes. Expiry <= cutoff and rejected/stale/
  blocked events do not consume active capacity; every original event remains
  in the denominator. These caps do not limit the investment universe.
- `validate_queue(...)`: validates the existing queue preview meaning in a
  closed typed envelope. Required channels and statuses must match. Missing
  consumer receipts remain DATA_PENDING. Unknown expiry from the Theme preview
  is permitted only in DATA_PENDING, not certified as fresh. Supplied item
  identities are unique by security. Different securities of one issuer remain
  distinct. An upstream Theme preview needs an explicit caller envelope and
  actual supplied identity mapping; this module does not invent either.
- `reference_preview(raw, ...)`: the only field is `entries`, passed to the
  existing Registry adapter. Null means RECONCILE_PENDING. The existing replay
  result preserves SUPPLIED_REFERENCE_SET_ONLY, NOT_VERIFIED review/current/
  domain selection and closed reuse/economic authority. It never means CURRENT.
- `plan_delta(previous_raw, current_raw, cutoff=...)`: pure comparison of
  explicit subject/fingerprint/expiry/exception assertions. Null prior means
  RECONCILE_PENDING. Price changes refresh market/valuation/ER; earnings refresh
  earnings/valuation/ER; industry changes refresh affected pillars; regime
  refreshes downside/overlay. Source, identity or accounting breaks require full
  A3 review. Expiry/catalyst/correction/retraction/source failure/outcome maturity
  prevent blind skip despite unchanged fingerprints. SKIP_UNCHANGED is a plan
  over supplied research_reuse_ready assertions, never a freshness certificate,
  authenticated gate, A0 completion, current write or execution authorization.
- `er_preview(ref_raw, ...)`: absent ER stays null. Internally consistent
  original net WALK_FORWARD_VALIDATED bytes may expose `declared_er`, preserving
  a genuine numeric zero. `validated_er` stays null and BLOCKED_RESEARCH_ONLY
  because independent review/model/config/data/PIT admission is not implemented.
  Wrong identity/benchmark, gross/scenario/stale inputs are refused. A shortened
  A3 result cannot substitute for the original risk/ER artifact.
- `validate_cohort(...)`: rows link event/cohort/decision/subject/benchmark/model/
  config/data/calendar/code identities. `calendar_ref` resolves a closed
  `h1-supplied-target-calendar-v1` object with targets keyed
  `<decision_id>:<horizon>`, each exactly `{session, close_at}`. `outcome_ref`
  resolves `h1-supplied-outcomes-v1` rows containing exactly the row's identity,
  session and return fields, excluding status/authority/denominator/source hash.
  Every MATURED row must match those bytes, exact target session, actual supplied
  availability after the supplied close, and asset minus benchmark return.
  No NYSE calendar or performance computation is introduced; supplied calendars
  and outcomes still require independent upstream admission. Complete exact
  seven-horizon coverage creates only `maturity_candidate=true`, while
  outcome_admission=NOT_VERIFIED and learning_eligible=false. Partial/missing/
  delisted/exited outcomes remain null and in the denominator. WATCH, REJECT,
  BLOCKED and NOT_SELECTED are retained. Late-session substitution is refused.

All root and investment-object authority flags are mandatory exact false,
including selector/ER/target/portfolio/paper/broker/orders/promotion/execute/
production/dispatch/admission/ledger/canonical_write/learning. No automatic A3,
A0, A5, champion, paper or broker operation is connected.

## Validation and real-data boundary

The new synthetic suite is registered through the existing A3 `load_tests`
without removing RegistryTests or AuditTests or changing protected runners.
Run the intake, full registered A3 route and Control Plane smoke normal and -O.
The external successor evidence maps the original40 planned families to actual
methods and modes, including full registered regressions, output parity and
proof inventory omission/stale/delete/rename attacks. Counts are test methods,
not proof of40 completed investment-data families.

The original preparation packet remains immutable:
SHA256 `20e1c906b7f90c64b70bde91ab5c6476d4a865b4de111effd0cac8a9d6eb9e21`.
Actual37-name/23-earnings-pair research is not synthesized into valid input:
missing raw/time/identity/review/market evidence stays BLOCKED_PROOF and is
reported separately from fixtures. Source #618 and Main #620/#621 are separate
unmerged scopes; this branch is not their integrated master or deployment.

H1 remains NO_CODEX and Draft-only. Native and independent A6 evidence do not
authorize Ready, maintainer attestation, merge, fullrun, collection, learning,
Source/PIT promotion, portfolio/book/order changes or notifications.

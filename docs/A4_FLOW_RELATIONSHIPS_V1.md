# A4 test-period flow and benchmark relationship research

This opt-in component reuses Daily Crisis Monitor, its single-writer lease,
the existing primary archive/Readers and build_replay_price_cache.download_yfinance.
It adds no scheduler, accepted-state authority, model fit or A3/A5 connection.

## Actual research population

Twenty-four distinct native series are requested: four H.4.1 balances (Fed
assets, weekly-average reserves/TGA/other-account RRP), sixteen H.8 bank
series (deposits, loans, C&I loans and cash in all/domestic/large/small scopes),
and four funding rates (SOFR/TGCR/IORB/EFFR). Four funding spreads are derived.
Overlapping bank aggregates and algebraically related spreads share dependence
groups; 24 series are not 24 independent economic votes.

Weekly balances use exact seven-calendar-day changes in USD. A missing week
stays missing. Funding rates use native preceding-observation changes in bp
with at most seven calendar days between operands; spreads require matching
observation dates. Rates are prices of funding, not identified cash transfers.
H.4.1 other-account weekly RRP is not silently relabelled daily ON RRP.
Deposit changes are not identified equity/MMF-to-bank transfers.

The fixed population is 28 features x 2 ETF proxies (SPY/QQQ) x 8 horizons
(1/5/10/21/63/126/252/504 observed sessions): 448 pairs and 896 Pearson/Spearman
coefficients, including unavailable/constant/negative cases. This is a separate
descriptive question; no p-values, significance, combination selection or
predictive loss superiority are claimed. Pairwise populations, dates and
counts remain visible; cross-feature ranking is not validated. At least 30
paired observations are required for a coefficient. Nonoverlap outcome-window
counts remain separate, with fewer than 20 labelled insufficient evidence.

Current revised histories are aligned by their measurement dates to the next
observed price session. Original actual collection/availability remains in
provenance. Measurement dates are NOT historical publication dates, and these
coefficients are NOT historically tradable/PIT evidence, causal effects,
walk-forward model validation or a forecast. Source observations before the
first price date are excluded rather than collected at its first anchor.
Weekly observations are not forward-filled into daily independent samples.
Labels reuse next-close entry and complete outcome-path checks. Current UTC
date prices are conservatively excluded without fabricating a close clock.

## Finite price test and custody

Default OFF: A4_FLOW_RESEARCH_POLICY_SHA256 must independently bind the exact
private flow-research-policy.json restored from outputs/market_analysis_inputs/
flow_research. Its schema is a4-flow-test-policy-v1, purpose
PRIVATE_CURRENT_VINTAGE_FLOW_ASSOCIATION. It fixes SPY/QQQ only, 2016-01-01
history, Close, USD as OWNER expectation, producer hashes, the existing resolved research folder ID, one batch per attempt,
one consumed attempt per completed US session, zero fits and no portfolio changes.
The actual collector's currency is not independently verified by this wrapper.
The legacy collector pin uses LF-canonical text, matching the existing data-
center collector identity; new flow source pins bind exact LF bytes.
Expiry is at most 31 days from availability; that approval duration never means
31-day stale daily prices are fresh. Latest completed session is obtained from
the existing market calendar helper and both exact closes are mandatory. Data-center admission requires the
view target session to equal the latest completed session at its cutoff.

The existing collector returns normalized DataFrames, not raw vendor HTTP
originals. Preserve exact deterministic returned-frame snapshots, normalized
Close views and explicit raw_http_originals_available=false,
provider_currency_verified=false, source/training/PIT admission=false.
This policy does not create supplier permission, Source qualification or
training rights. Provider private-use/Drive-storage rights remain explicitly
UNVERIFIED in this limited test, without a new supplier approval claim. The
transport accepts only the existing scheduled research locators, checks its
resolved folder against the external policy and refuses implicit mkdir or
unrelated object operations. No new provider endpoint, FRED/ICI/ICE/FINRA route, shared legacy
cache, target book, 80-ticker cohort or managed-price control is changed.

A content-addressed session claim is written/read back in the existing private
macro-primary/reports namespace before one collector batch. A failed attempt
keeps its claim and requires owner recovery; no provider retry is added. Failure
receipts are also attempted in the same immutable reports namespace; failed
publication leaves a local witness. Public artifacts retain only file hashes
and byte counts, including failed attempts, never financial snapshot contents.
An unchanged completed-session view may be reused only after the newest
verified data-center catalog and exact view are read back. The cached view must
bind the currently approved policy, producer and completed session; a changed
same-session policy is not relabelled. An older-session producer does not block
a new authorized session capture. A blocked newest same-session context cannot
fall back to an earlier success; an older session's failure stays recorded while
a new session may start its own single consumed claim. Completed snapshots and views
are stored under existing objects hashes, followed by a typed execution receipt.
A durable-completion marker is created only after the typed execution receipt's
write/readback and expiry recheck. The data center rejects any failure witness,
requires that marker and independently rereads the typed remote execution before
accepting durable price evidence. Actual CLI execution requires --publish;
local-only provider execution cannot bypass the shared session claim. Injected
synthetic downloaders remain test fixtures, without execution authority.
All writes use the existing immutable copy/readback transport. Backend HTTP
counts are UNKNOWN; one wrapper batch is not one backend HTTP request. Discovery,
readbacks and uploads share caps of 128 transport commands and 32MiB counted
payload bytes, with a 600-second soft deadline and a hosted 12-minute process
kill boundary (10-second termination grace). One command may return an object
up to the existing transport limit before a cumulative-byte refusal; these
caps count wrapper payloads, not provider/Drive backend HTTP traffic.

## Data center and deployment

The existing workflow prepares test prices after successful primary capture.
The data center consumes only that attempt's output, validates the external
policy and loaded producer identity, replays snapshot-to-Close normalization
and stores flow_relationships in its same private catalog. Missing, expired,
changed or unsuccessful price evidence makes this component BLOCKED; native
ten-axis risk and historical-learning gates stay unchanged. No policy means
NOT_CONFIGURED and zero additional provider calls.

Review exact source, focused normal/optimized invariants, A6 dependency closure
and full CI before enabling a new finite profile or actual collection. Verify
one bounded dispatch, original snapshot/view/execution hashes, Drive readback
and a scheduled outcome separately. Keep failed/expired claims; never replay
an earlier scope or infer current market coverage from the retained July cache.
Public GitHub artifacts remain counts/hashes only; numerical research stays
in the existing private Drive catalog. Research is RESEARCH_ONLY and cannot
supply A3 expected returns, A5 weights or a champion replacement.

## Bounded multi-provider price test (v2, opt-in)

The v1 policy/view and its single existing-yfinance batch remain supported.
An independently pinned a4-flow-test-policy-v2 may explicitly order two or
three existing adapters: alpaca_sip, yfinance and twelve_data. It allows one
attempt per provider, at most the declared two/three batches in total, under
the same single consumed session claim and existing hosted timeout. Each
descriptor binds a private-test-use scope hash and explicit owner test
authorization. Alpaca additionally requires the noncommercial terms
acknowledgment; Twelve Data requires the reviewed SPY/QQQ MIC mapping. These
declarations do not establish supplier storage, training or Source rights.
Missing credentials/entitlement, network/limit errors, empty/partial/stale
frames or inadequate history advance only to the next declared provider.
Policy expiry, session rollover or credential echoes stop the whole chain.
No retry of a provider, failed session or expired execution scope is added.

Select both exact latest-completed-session closes from one provider; never
splice one ETF or historical segment from another provider/cache. History
must start no later than 2016-01-11 and contain at least 2,000 nonmissing
closes per ETF. This lower coverage check is not exchange-calendar, identity,
corporate-action or PIT certification. All-failed is BLOCKED; retained July
2026 prices never qualify as current prices. An existing same-session view
is reusable only under the same external policy, producer and durable rules.

Alpaca reuses the SIP raw-bars request/parser and preserves its inclusive-end
delay before credentials/networking. Twelve reuses authenticated header-only,
no-redirect/no-retry HTTP; its inclusive end is the selected session and
adjust=none. Each has at most two reserved-before-call HTTP requests, each
response at most 2MiB. Yahoo keeps the existing auto_adjust=False downloader;
one logical batch has UNKNOWN backend HTTP count. No false cross-provider
HTTP total is asserted. API keys stay in existing environment/secrets, never
policy, URL, diagnostics or artifact contents. Existing hosted scheduling
and default-OFF policy activation are unchanged.

Private provider-evidence.json records whitelisted frame type/shape/columns/
index, safe failure category, times and exact-body hashes. It never repeats
arbitrary labels, exception text or provider error bodies into public logs.
Credential-checked HTTP bodies are retained only in private content-addressed
evidence. The v2 snapshot/view bind selected provider, policy descriptor and
ordered attempted prefix. The Reader rehashes retained bodies and replays
Alpaca/Twelve normalization to the snapshot closes; Yahoo explicitly has no
raw HTTP original. A v2 snapshot is at most 8MiB, its view 4MiB, and provider
evidence 8MiB, within the unchanged cumulative transport allowance. An
all-failed witness is separately stored/read back; no completion marker is
written. Public receipts list only hashes/byte counts, including that witness.

The raw original flag does not grant Source/PIT/training admission. These
current-vintage raw Close series omit total-return/cost qualification and
cannot be silently passed to learning or portfolio allocation. Deployment,
actual provider capture, private Drive readback and scheduled execution must
be evidenced separately; offline synthetic failure tests establish none of
those actual outcomes.

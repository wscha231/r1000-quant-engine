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
history, Close, USD as OWNER expectation, producer hashes, one batch per attempt,
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
training rights. No new provider endpoint, FRED/ICI/ICE/FINRA route, shared legacy
cache, target book, 80-ticker cohort or managed-price control is changed.

A content-addressed session claim is written/read back in the existing private
macro-primary/reports namespace before one collector batch. A failed attempt
keeps its claim and requires owner recovery; no provider retry is added. Failure
receipts are also attempted in the same immutable reports namespace; failed
publication leaves a local witness. Public artifacts retain only file hashes
and byte counts, including failed attempts, never financial snapshot contents.
An unchanged completed-session view may be reused only after the newest
verified data-center catalog and exact view are read back. A blocked newest
context cannot fall back to an earlier success. Completed snapshots and views
are stored under existing objects hashes, followed by a typed execution receipt.
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

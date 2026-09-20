# Multi-asset observed fundamental sources

Continuation of issue #465 and merged PR #466, based on master
`4ef3a9cf55bfdf0869c5d68f640b321e8b6237b9`. Research only.

## Scope and reuse

`research/multi_asset_v1/fundamentals.py` adds actual provider collection to the
existing capture -> metric admission -> commodity/crypto artifacts -> daily
report path. It reuses the strict JSON/number/time contract and immutable raw
writer. Network HTTP uses the existing bounded no-redirect reader. EIA alone
needs up to two HTTPS redirects to the same host and fixed document path;
signed redirect URLs and provider exception strings are never persisted.

| Source | Subject | Normalized observations | Unit |
|---|---|---|---|
| EIA Weekly Natural Gas Storage Report | NATURAL_GAS | Inventory, 5-year average, weekly change, relative difference from average | Bcf; fractional difference |
| Coin Metrics Community | BTC | HashRate, CapMVRVCur, FeeTotNtv | H/s after explicit TH/s conversion; ratio; BTC |
| Coin Metrics Community | ETH | FeeTotNtv, AdrActCnt, TxCnt, SplyCur | ETH; address count; transaction count; ETH |

Only the Lower 48 total is selected; regional and total inventory are not added.
An average comparison is not an inventory percentile. Active addresses and
transactions are observations, not estimates of unique users or adoption.
ETH supply is not net issuance, staking, burn, L2 activity or ETF flow. No ETH
mining metric is requested. Native fees are not converted using asset prices.

Source contracts checked against:
- https://ir.eia.gov/ngs/ngs.html and its linked `wngsr.json`
- https://docs.coinmetrics.io/network-data/network-data-overview/mining/hash-rate
- https://docs.coinmetrics.io/network-data/network-data-overview/fees-and-revenue/fees
- https://docs.coinmetrics.io/network-data/network-data-overview

## Time, units and missingness

EIA's JSON release date contains a midnight placeholder. It is retained as a
date, never interpreted as a known intraday publication timestamp. Observation
date remains the weekly period label; `available_at` is the actual retrieval.
Reject releases older than eight calendar days at capture, invalid periods,
duplicate totals, incorrect units and inconsistent inventory changes. The
dedicated EIA_STORAGE observation-age ceiling is fourteen days, allowing the
weekly release lag without relaxing other EIA sources.

Network daily labels are converted to UTC interval ends. Each request is for
one asset/metric over seven completed days with a 100-row ceiling. Reject
unexpected pagination, identity, duplicate/future periods, nonfinite values,
negative values and fractional counts. Null on the latest returned period stays
null even if older periods have values. Token currency must equal BTC or ETH.
The normal runtime freshness gate rejects observations older than four days.

Raw hashes, provider metric ID, source value, unit multiplier, period label,
observation end, retrieval and source identity remain attached to observations.
This is revised **current** evidence, not retrospective PIT evidence. Downloaded
historical rows are never assigned their period dates as availability times.

## Artifacts and failure behavior

The existing workflow now uploads the capture input and original responses as
well as diagnostic outputs, making a capture reproducible after runner deletion.
The 45-day GitHub retention is explicitly not durable historical storage.

Each provider request has its own receipt. Successful raw bytes survive a parse
failure. A failed/unlicensed metric request does not erase other successful
observations. Existing runtime invalid-metric gates remain in force. No change
to latest-success semantics, registry tradability, evaluator approvals, risk
limits, targets, broker calls or model promotion.

Crypto artifacts expose their admitted metric rows and a null network score
with `NO_VALIDATED_NETWORK_MODEL`. Daily reporting shows value, unit, original
observation time and admission. No price or network count is mapped to invented
fundamental confidence or expected returns.

## Validation and remaining scope

Twenty new offline regressions live in the existing registered multi-asset
smoke file: units/times, source identity, totals, revisions, stale/future data,
redirect allowlist, pagination, missing latest values, numerical boundaries,
partial failures, raw byte recovery, artifact/report integration and workflow
retention. Fixture values are synthetic test cases, never live results.

Real provider probes retrieved current EIA and all seven network metrics.
Reproduce the actual run and inspect its receipts; preliminary probes alone do
not certify an automated post-merge capture. Some combined Coin Metrics requests
returned HTTP 403; public metrics are requested separately without credentials.
The public CSV archive was stale and is not used as a current fallback.

Still required for complete V1: remaining commodity fundamentals, network/ETF
flows, validated full-equity and cross-asset ER producers, canonical news
integration, accepted holdings/look-through, historical PIT replay/OOS,
durable observation archives and sustained shadow operation. No performance
claim or production promotion is implied by this source-collection change.

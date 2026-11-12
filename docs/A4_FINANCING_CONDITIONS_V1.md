# A4 financing conditions: research context

The separate financing adapter reuses the existing primary archive, Reader,
daily workflow and immutable receipts. It does not change the bank/funding
codec, native ten-axis policy, A3 expected returns, A5 limits or winner exits.
`financing_primary` is a v2-only input; v1 requests remain supported.

## Public-source capture

- TreasuryDirect Note/Bond auction snapshots retain original term, security
  type, CUSIP and reopening identity. Bid-to-cover is the published ratio.
  Dealer/direct/indirect shares use competitive awards inside the offering;
  SOMA and grand totals do not replace that denominator. Compare the preceding
  six same-original-term auctions and separately the same issuance type. A
  current auctioned-security snapshot is not a complete historical universe.
  Indirect bidder participation is not foreign-only demand.
  Report both peer means and their direction agreement. A lower ratio than a
  mixed new/reopening cohort can coexist with a higher ratio than the same
  issuance-type cohort; that disagreement is visible, not a calibrated risk
  classification.
- SLOOS discovers the latest published quarter from the official index, then
  parses the domestic table. Question labels, response counts, net tightening
  and net stronger demand stay separate. The respondent population differs
  from H.8 aggregates. Missing special NDFI questions remain visibly missing.
- The NYFed chart CSV contains monthly ACM estimates. The separately
  published XLS is read from its exact ACM Daily sheet with the pinned xlrd
  parser, bounded rows and three matching 10-year model components. Preserve
  model/revision caveats; monthly values cannot fill daily samples or count
  as another independent signal. The fitted zero-coupon curve is distinct
  from Treasury par yields. Missing latest values never fall back silently.

`A4_FINANCING_COLLECTION_ENABLED=true` opts six captures into the existing
primary workflow after review and deployment validation. Originals use an
8 MiB limit except the 12 MiB daily XLS; the existing 64 MiB request budget and
shared transport limits remain. The setting defaults off and
does not enable learning. Failed optional sources retain verified core data
as an explicit partial attempt; the collection process still fails completion.
All captures keep actual collection availability and no historical PIT grant.
All18 files bound by the A4 implementation identity use canonical LF bytes.
The regression exercises actual source/contract bytes through an autocrlf
checkout; raw code/original hashes are not normalized or ignored at read time.
The primary collection flag is also required; financing alone fails the final
configuration gate. Its larger capture/readback budget uses a 60-minute job
limit while financing is enabled; the existing 30-minute default remains.

## Licensed and unverified evidence

ICI ETF net issuance, MMF balances, ICE CCC/HY and FINRA margin data require
their own rights/original evidence before automated ingestion. No FRED/ICE or
ICI endpoint is in the new fetch allowlist. Public display does not supply
training permission or an externally reviewed input policy.

ETF net issuance is creations less redemptions, not secondary-market net
buying. MMF asset changes are balance changes, not identified transfers from
stocks. Concurrent growth does not identify the same investors. CCC/HY
constituents differ; their spread gap is descriptive rather than a causal
crisis estimate. Correlated measures share a signal group.

An auction tail requires an independently verified auction-time when-issued
quote. The difference from a prior auction yield is not a tail. Conditional
rates/credit/breadth scenarios remain uncalibrated until independent evidence
supports them. A manually proposed CAUTION label is not a native risk state.
New financing features require independent recipe/input-policy review before
learning. Existing research-only, maturation and challenger gates remain.

Sources: [Treasury auction query](https://www.treasurydirect.gov/auctions/auction-query/),
[SLOOS](https://www.federalreserve.gov/data/sloos.htm),
[NYFed term premia](https://www.newyorkfed.org/research/data_indicators/term-premia-tabs),
[ICI permissions](https://www.ici.org/permissions),
[ICI copyright](https://www.ici.org/copyright-and-linking-policies).

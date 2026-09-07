# Research Decision V1 — independent input contract

Related issue: #396. Scope: H1 input admission; H2 valuation/allocation is a
separate dependent PR. This is not a repair or activation of the NONRANKING
monitor. PR validation installs the frozen dependencies and tests both platforms. No
operating workflow, target, accepted account, order, policy, or model changes.

The caller materializes existing provider/cache data into `research-input-v1`.
Every price/financial/thesis/risk block retains source URL, security identity,
report period, publication/availability/observation/ingestion timestamps,
cutoff, explicit units, currency, accounting basis and canonical payload hash.
Unknown publication times remain null; unknown public availability blocks admission.
Financial period ends cannot follow publication/observation, and official closes
cannot be observed before the exchange close. Current observations cannot certify
historical PIT. Payload hashes prove byte identity, not truth of a source or
correctness of a manual extraction; source reconciliation is a separate gate.

Markets export independently. US entrypoint rejects KR inputs. The KR repository
entrypoint uses this shared pure calculation package pinned by source hash.
Exports retain the original input so a consumer can replay admission rather than
trusting a readiness Boolean. No NONRANKING or legacy score is an input.

Price input is an official raw current-share close. Historical `raw_unadjusted`
and `split_adjusted` bases are distinct: split ratios apply only to unadjusted
history. Dividends are per share on the ex-date share basis. Total-return RS
uses matching benchmark sessions; 240-session RS needs 241 observations.
Missing long history is explicit and does not invent momentum. Fewer than 21
sessions blocks liquidity sizing. Corporate-action coverage must be declared
through the current completed session for both security and benchmark. US uses
SPY; KR listing board selects KOSPI200 or KOSDAQ150. Calendar dependency is pinned to
`pandas_market_calendars==5.4.0`; a changed calendar requires a reviewed update.

H1 retains valid consolidated financial observations in USD / KRW, including
reported losses. Profitability is a valuation-domain gate, not a data-quality
judgment: valuation_method_eligibility marks PE only for positive TTM net income
and EV_EBITDA only for positive EBITDA. H2 independently repeats that metric
gate before calculation. Unsupported methods remain blocked. Financial
currency values use base units, not millions; diluted shares use actual shares.
FCF = operating cash flow minus positive cash CAPEX. Required TTM age <=210 days.
The latest quarter must match TTM end, the latest annual end must be within
370 days of it, and supplied histories must be contiguous. Recent-quarter and
annual records are required; deeper requested histories are
reported by coverage and not fabricated. Unsupported accounting/valuation types
must remain blocked rather than forced into a P/E calculation.

`available / stale / missing / provider_error / no_event / not_applicable /
unverified` remain separate. Optional 403, missing ownership/news, or no-event
cannot zero-fill core fundamentals or disable other valid evidence. Optional
evidence never adds alpha in V1. `consensus_revision=null` unless a separate,
verified historical snapshot mechanism exists.

Run: `python tools/export_research_decision_market.py --input <frozen-input.json>`.
Writes only `outputs/research_decision_v1/exports/<export_hash>.json`; collision
with different bytes fails. Exit 2 is a partial/blocked export, not success.
Fixtures live under `tests/` and must carry `data_kind=SYNTHETIC`; real inputs use
`REAL` and are never relabeled when data fails.

Reuse assessment: existing `r1000_valuations.compute_live_valuations` uses
zero-debt/cash fallback, growth clipping and TTM-as-forward fallback; these do
not satisfy this contract. Existing monitor scores remain diagnostic only.
Existing calendars are reused; provider callers/caches remain unchanged.
PR #320 has RS-based allocation; #336's portfolio reconstruction is rejected in
the do-not-repeat registry. Neither allocation rule is imported. PR #394's
rclone repair and #389's macro archive are not dependencies.

Review corrections: reject every legacy score field/NONRANKING status, and reject
credential-bearing or reserved synthetic-source input before even a blocked
snapshot can be persisted. Files publish by atomic no-replace link after fsync.
Source pins cover recursive Python package files and the parent initializer;
the KR loader executes only the verified snapshot bytes. Third-party runtime
dependencies remain a separate, pinned installation contract.

Validation lineage: `tools/run_pr_validation.py` is protected by the P0-4
inventory verifier. Its sole new registration is already published in ancestor
`7d5913f1d48e213faaf979ea110276e51ab800dd`. Advance only the verifier's protected
publication constant and matching regression expectation to that ancestor. The
protected path set, frozen inventory, generator behavior and rejection checks
are unchanged; external exact-head review is still required.

Second exact-head review: reported financial periods complete at next local
midnight in the explicitly supplied IANA `reporting_timezone`; same-day
availability before that instant is blocked. Price report periods match their
bar range. REAL input cannot carry a reserved synthetic feed. Common secret
field aliases are rejected before snapshots. Input reading walks directories
without following symlinks and validates/bounds bytes from the same descriptor.

Third review corrections: price units are currency_per_share, volume units are
shares, risk units are fractions, and dividends are on the ex-date share basis.
For split-adjusted closes, historical dividends are divided by subsequent split
ratios. Raw and adjusted series agree across pre-split dividends and reverse
splits. KR benchmark bars must be a total-return index with no extra split or
dividend application; US SPY uses price plus distributions.

Tier-1 installs requirements_research_decision_v1.txt explicitly and includes it
in the pip cache key. A bounded Windows PR job exercises the same admission
tests. POSIX uses directory-relative no-follow descriptors; Windows opens and
checks non-reparse handles, holds parents and denies write/delete sharing during
the read. Windows publication uses no-replace MoveFileExW with WRITE_THROUGH.
See the primary [CreateFileW API](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
and [MoveFileExW API](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw).
Windows native execution is a CI validation requirement; Linux tests do not
certify the Windows implementation. URI scans handle scheme names and case
before any embedded value can reach a stored snapshot.

The third-review CI dependency/Windows job change is causally published in
`0629e4a50dcef8f85701f1e010466033107d1839`. The protected-publication verifier and
matching regression constant now reference that ancestor; verifier behavior and
the protected path set are unchanged.

The subsequent Linux cache-key compatibility fix was published in causal ancestor
`5755e5f1f6e0ecf4ad6098dcfd2c1bb2e0392290`; the protected-publication pin advances
there without changing inventory or verifier behavior. Research dependencies are
still installed explicitly on every validation run.

Seventh-review boundary corrections: normalize credential metadata with NFKC and
reject JWT/bearer/session-id/access-key families and recognized JWT/bearer values
before retaining blocked snapshots. A price bar's `session` remains a date.
REAL public-document provenance requires a valid DNS name after percent/IDNA
normalization; all IP literals and resolver-dependent numeric/hex forms are
rejected. This is a provenance admission rule, not a claim of DNS verification.
Financial reporting-day completion reads `tzdata==2026.3` package bytes through
ZoneInfo.from_file, independent of host TZPATH and cached system ZoneInfo objects.
The export records the pinned database version. Missing/mismatched timezone
data blocks financial admission, and does not fall back to the host database.

Eighth-review corrections: REAL provenance also excludes special-use DNS
namespaces (including home.arpa, onion and alt) and private naming conventions.
Registry reference: https://www.iana.org/assignments/special-use-domain-names
The V1 financial boundary is tied to the supported market timezone: US
America/New_York, KR Asia/Seoul. Other reporting jurisdictions need a separate
verified contract extension; an arbitrary IANA zone cannot advance admission.
All TTM/history boundaries are canonical date-only values with exact adjacent
dates. Exports include the admission module source SHA256 captured at import
(normalized LF), in addition to dependency versions and the input hash. It is
part of export_hash; KR/H2 verified loaders bind this to their source snapshot.

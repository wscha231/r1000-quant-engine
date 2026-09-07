# Research Decision V1 — independent input contract

Related issue: #396. Scope: H1 input admission; H2 valuation/allocation is a
separate dependent PR. This is not a repair or activation of the NONRANKING
monitor. No workflow, target, accepted account, order, policy, or model changes.

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

V1 supports consolidated profitable operating companies in USD / KRW. Financial
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

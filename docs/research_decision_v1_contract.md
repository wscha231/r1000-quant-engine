# Research Decision V1 — independent input contract

Related issue: #396. Scope: H1 input admission; H2 valuation/allocation is a
separate dependent PR. This is not a repair or activation of the NONRANKING
monitor. No workflow, target, accepted account, order, policy, or model changes.

The caller materializes existing provider/cache data into `research-input-v1`.
Every price/financial/thesis/risk block retains source URL, security identity,
report period, publication/availability/observation/ingestion timestamps,
cutoff, explicit units, currency, accounting basis and canonical payload hash.
Unknown publication times remain null. Current observations cannot certify
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
through the current completed session. Calendar dependency is pinned to
`pandas_market_calendars==5.4.0`; a changed calendar requires a reviewed update.

V1 supports consolidated profitable operating companies in USD / KRW. Financial
currency values use base units, not millions; diluted shares use actual shares.
FCF = operating cash flow minus positive cash CAPEX. Required TTM age <=210 days.
Recent-quarter and annual records are required; deeper requested histories are
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

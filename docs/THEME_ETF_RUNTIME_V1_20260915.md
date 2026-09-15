# Theme·ETF Runtime V1 — 2026-09-15

Status: `RESEARCH_ONLY` / no orders / no target-book mutation / no champion promotion.

This additive runtime joins new-theme discovery, ETF holding changes with explicit units and completeness, 5/20/60/120/240-session log-relative total-return leadership, and reviewed business-membership events that may expand but never replace the base research universe.

## Supported contract

The supported API and CLI route through `research/theme_etf_runtime_v1/strict.py`. The lower-level `runtime.py` is an implementation layer, not a trusted external-input boundary.

Key invariants:

- percent/fraction units are explicit; percent-marked values conflict with `FRACTION` rather than being silently reinterpreted;
- a pre-normalized snapshot must retain its content hash and internally consistent completeness gates;
- `TOP_ONLY`, `PARTIAL`, `PCF`, `PROXY`, or `NPORT` absence cannot prove a holding removal;
- ETF holding changes do not prove trades, buys, or sells;
- latest holdings are selected independently per fund at the decision time;
- reviewed business-relation `LINK` events are required for universe expansion;
- only verified, research-eligible U.S.-listed common shares or ADRs can be added;
- the base research universe is unioned with reviewed additions and is never replaced by a theme list;
- outputs cannot create orders or mutate target books.

## Validation and reusable lessons

The initial local review identified two fail-open risks before merge: a percent-marked value paired with a `FRACTION` declaration, and an externally supplied `etf-snapshot-v2` object that could claim a forged `complete` state. The strict boundary rejects both. These cases are regression-tested in normal and optimized Python modes and in the side-effect-free GitHub Actions matrix.

The execution environment could not resolve `github.com` for `git clone/push`. After the user explicitly authorized modification and merge, locally validated file bytes were published through the connected GitHub write API to a dedicated branch. This exception does not waive PR diff review, exact-head checks, unresolved-thread review, or expected-head merge gates.

Files in this change remain research-only. Historical alpha, OOS CAGR/MDD, live issuer downloads, the existing company evaluator, KR/global runtime, accepted Drive-lake publication, and changes to the legacy `tools/run_etf_holdings_refresh.py` collector are separate validation gates.

# Theme·ETF Runtime V1 — 2026-09-15

Status: `RESEARCH_ONLY` / no orders / no target-book mutation / no champion promotion.

This additive runtime joins new-theme discovery, ETF holding changes with explicit units and completeness, 5/20/60/120/240-session log-relative total-return leadership, and reviewed business-membership events that may expand but never replace the base research universe.

## Supported integration contract

The supported integration boundary is `research/theme_etf_runtime_v1/strict.py:run_payload` and `tools/run_theme_etf_runtime_v1.py`. Lower-level functions remain research primitives and must not be substituted for the strict point-in-time input boundary.

Key invariants:

- percent/fraction units are explicit; percent-marked values conflict with `FRACTION` rather than being silently reinterpreted;
- externally supplied pre-normalized snapshots may be reused only conservatively; a `complete=True` claim must be rebuilt from raw source evidence in the current run;
- `TOP_ONLY`, `PARTIAL`, `PCF`, `PROXY`, or `NPORT` absence cannot prove a holding removal;
- ETF holding changes do not prove trades, buys, or sells;
- latest holdings are selected independently per fund at the decision time;
- ETF snapshots, price rows, documents, security-registry rows, reviewed membership events, and the base-universe snapshot must be available no later than the decision cutoff;
- reviewed membership evidence must not be reviewed before it was observed;
- price rows are unique by security/session, and leadership windows use the benchmark's exact 5/20/60/120/240-session anchors rather than silently stretching a horizon around missing asset rows;
- reviewed business-relation `LINK` events are required for universe expansion;
- only verified, research-eligible U.S.-listed common shares or ADRs can be added;
- the base research universe is unioned with reviewed additions and is never replaced by a theme list;
- outputs cannot create orders or mutate target books.

## Validation and reusable lessons

Self-review before merge found several fail-open risks and converted them into regressions: percent-marked input paired with `FRACTION`; externally forged pre-normalized completeness; future/unavailable prices and documents; membership evidence observed or reviewed after the decision time; duplicated price/event/security rows; future base/security-registry state; and relative-strength horizons stretched by missing asset sessions.

The execution environment could not resolve `github.com` for normal `git clone/push`. After the user explicitly authorized modification and merge, the implementation developed in an isolated local directory was published through the connected GitHub write API to a dedicated branch. This is an exception to the normal publication path, so local/remote byte parity is not used as a merge gate. The exact remote PR head must pass PR diff review, side-effect-free CI, unresolved-thread review, and expected-head merge checks.

Files in this change remain research-only. Historical alpha, OOS CAGR/MDD, live issuer downloads, the existing company evaluator, KR/global runtime, accepted Drive-lake publication, and changes to the legacy `tools/run_etf_holdings_refresh.py` collector are separate validation gates.

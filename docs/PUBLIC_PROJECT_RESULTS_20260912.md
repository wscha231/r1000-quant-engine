# [PROJECT_HANDOFF] Public project results connection

Date: 2026-09-12. Source base: e89e87e722c67b32e56c2dd86969502c8e952676.
Branch: codex/public-project-results-20260912.

User request: connect the current investment project's results to the existing
GitHub Pages website so they update automatically.

PR417 is already merged/deployed. It independently updates holding quotes;
its public account remains July10. This change adds a distinct project results
panel using current master workflow artifacts and the existing monitor verifier.

Output: docs/public/data/project-results.json generated on the Pages runner.
It contains source execution status and verified artifact identity, current
nonranking research scores when available, original score/price dates, and
aggregate theme/macro/ETF data-quality diagnostics. Explicit allowlist only;
no raw source reports, absolute paths, private dollars/quantities or tokens.

Triggers: existing account refresh plus after-close, research-monitor, estimate,
ownership and long-history completions; daily08:45UTC reconciliation and existing
02:35UTC post-close refresh. Only the exact successful account producer can
enter portfolio ingestion. Failed source status does not reuse earlier success.

Known limitations: existing monitor's33US/KR watchlist, not whole-universe
ranking; missing KR adapter; long-history workflow status only, not catalog
acceptance; source macro/ETF observation dates unavailable; no chronological
paper recovery or fullrun. Current account/performance cannot be claimed until
that separate durable path succeeds.

## Independent research-score freshness, 2026-11-08

Research scores now retain their own source/model/clock envelope. The adapter
reuses `evaluate_score_handoff` on the original verified operating artifact;
report-ready flags or a summary score cannot replace that proof. Exported
watchlist values must match the original ticker's score and research flags.
The allowlist exposes source run/artifact digests, engine SHA, model anchor/meta
digests and feature/decision/execution clocks, never original paths or reports.
Exporter code/config identifiers remain distinct from the scoring model.

The deadline is the next actual NYSE close after the score's bound session
close, using the existing calendar helper. It is not calculated from the
page-build time: rebuilding during the next close's 90-minute settlement buffer
must not renew the previous session. Holidays, early closes and DST apply.
The browser rechecks this envelope during rendering and clears expired scores
even in an already open tab. Missing or stale legacy account quotes cannot hide
a separately verified current research score; they still gate displayed prices.

This remains the existing US24/KR9 watchlist, not an820-security ranking. Model
identity is shown as research context; predictive value and portfolio performance
remain unvalidated. No new portfolio, holding, weight, return or approval is
inferred from the diagnostic score, and legacy portfolio guards remain intact.

Validation and publication evidence are recorded in the PR. Merge requires
exact-head independent Codex review, no unresolved threads and green required
checks. No automatic approval or policy change.

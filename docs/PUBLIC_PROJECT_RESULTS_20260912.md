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

Validation and publication evidence are recorded in the PR. Merge requires
exact-head independent Codex review, no unresolved threads and green required
checks. No automatic approval or policy change.

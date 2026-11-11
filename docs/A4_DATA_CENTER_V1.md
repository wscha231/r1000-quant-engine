# Unified A4 research data center

The index is a bounded view over the existing primary archive and shared
data-access routes. It creates no provider collector, scheduler, portfolio
policy or accepted account/ledger. Original data stay in their existing
content-addressed archives; temporary request files are working caches.

`tools/a4_data_center.py` verifies explicitly pinned capture execution bytes,
generation manifests and selected original/normalized pairs using the existing
primary, economic and financing Readers. Source versions remain separate.
Selection uses the capture cutoff, not a delayed publication completion time.
A failed latest attempt blocks that feed; an older success cannot replace it.
Future completed attempts are excluded into a separate audit so they cannot
change an earlier catalog or diagnostic. Only selected vintages are replayed:
weekly data and multiple capture versions do not become independent daily
samples. Same inputs and equivalent UTC cutoff reuse the catalog identity.

The snapshot records native units, bank scopes, seasonal/measurement basis,
observation range, actual availability, missing/latest/stale values, source
hashes and the original execution. The human report preserves bank dates,
SLOOS respondent denominators and ACM model caveats. These are verified
research bytes, not automatic Source/PIT or training admission.

## Current, historical and forward use

- Current diagnosis reconstructs an A4 v2 request from selected originals and
  reuses the native ten-axis engine. Only the newest attempt's still-current
  native request may contribute risk operands. An expired/missing native
  request never falls back to an older one. Missing essential inputs leave the
  native state blocked while verified liquidity/bank/financing context remains
  inspectable. Native derived operands are archived once by exact hash when
  the reconstructed request/report is published.
- Historical evaluation uses the existing externally pinned learning request,
  original resolver, rights/source policy, NYSE calendar and return-basis checks.
  The index performs readiness validation, not a hidden fit or backtest.
  Execution remains in the existing restored-state research cycle, with
  expanding windows, purge/overlap controls, maturity and do-not-repeat gates.
  Outcomes remain return, maximum drawdown and realized volatility for
  1/5/10/21/63/126/252 sessions and the existing fourteen ETF targets.
  An observed historical range is distinct from a qualified historical-PIT
  range. Current revised government histories cannot be backdated.
- The forward view exposes conditional scenarios and horizon evidence.
  It cannot invent probabilities, expected returns or portfolio weights.
  Quantitative forecasts still require an independently reviewed fixed trial
  through `forecast_release`; learning may propose challengers only.

The optional legacy Lake probe reads bounded commit/catalog/execution
metadata only. It retains the latest chain and dataset states but never calls
this original-pack or execution validation. Actual consumption must use
`Lake.verified_execution` and the existing Readers. FRED/ALFRED rights remain
separate, even if old metadata show collected data. Price and financial
discovery stays with `research_model_inputs`; locator counts are not current
coverage or A3/A5 admission. ICI/ICE/FINRA remain explicitly rights-blocked.

## Storage and bounded replay

Under the existing `shared-research-v1/macro-primary` namespace:

- `catalogs/<sha256>.json`: immutable as-of catalog;
- `reports/<sha256>.json`: reconstructed request/report using existing publisher;
- `index-executions/<sha256>.json`: receipt published after object readbacks.

Every local attempt has catalog JSON/Markdown, request/report, audit and
execution receipt. A failed publication/readback leaves a separate
`publication_failed.json`; a local COMPLETE-looking receipt cannot certify
durability without the matching remote readback. No mutable latest pointer is
an authority. Use exact snapshot/execution pins for historical queries.

Limits: eight capture references per view, nineteen registered feeds per
capture, 150,000 selected native rows and64MiB cached original/normalized
reads. The metadata-only Lake view permits256 commits/receipts, a4MiB catalog
and8MiB cumulative metadata. Exceeding these limits is blocked, not silently
truncated or interpreted as absence. Existing per-source and transport limits
remain unchanged.

```powershell
python tools/a4_data_center.py --capture-root <existing-capture> `
  --execution-sha256 <original-execution-hash> --cutoff <UTC-as-of> `
  --output-dir <new-attempt-directory>
```

`--remote-execution-sha256` restores immutable receipt/native references with
the existing configured research transport; it does not call a provider.
Remote references can be mixed with local ones, up to the same bounded limit.
`--publish` writes/rechecks the index and research reports; without it, remote
references are read-only. `--probe-lake-metadata` adds the metadata-only view.
`--learning-input-root` plus the externally supplied original policy hash
enable readiness checks without manufacturing a policy or changing state.

The existing Daily Crisis Monitor builds/publishes the index after primary
capture, then consumes its current request. Index failure points the run at
the attempted root and fails the final gate, never at a restored old success.
The research cycle runs only after its original state restore and a successful
index when primary collection is enabled. Existing enable flags, single writer
and30/60-minute workflow bounds remain; no additional schedule is installed.

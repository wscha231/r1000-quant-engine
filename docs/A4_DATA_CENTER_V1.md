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
The original six-feed v1 receipt is recognized when its later optional feed
list is absent: only the closed original core profile is inferred. Original
receipt/manifest hashes are preserved. Failed attempts need no unpublished
generation bodies before they can be retained as blocked history.

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
  SPY/QQQ focus readiness is additionally reported as
  `learning.benchmark_research_status`; it does not require the other twelve
  targets to be present before an independently reviewed benchmark-only input
  subset can enter the existing research cycle. Full-family coverage/status
  remains separate, and the original fourteen-target test family is retained.
  Price validation uses the actual session/close records, not the validated
  date index, and a target with only missing prices is still missing evidence.
  Original policy validity is also checked at this view's actual cutoff.
  This is input verification only: maturity, independent windows, fitting and
  fixed-release review still belong to their existing gates.
  An observed historical range is distinct from a qualified historical-PIT
  range. Current revised government histories cannot be backdated.
  A separate current-vintage description reports three fixed weekly-change
  correlations: TGA/reserves, deposits/loans and deposits/cash. It uses exact
  seven-day observations, preserves gaps, reports all declared pairs and does
  not reconstruct structural adjustments. These are descriptive statistics,
  not past investment decisions, causal effects, trained features or a backtest.
- The forward view exposes conditional scenarios and horizon evidence.
  It cannot invent probabilities, expected returns or portfolio weights.
  Quantitative forecasts still require an independently reviewed fixed trial
  through `forecast_release`; learning may propose challengers only.

The optional legacy Lake probe reads bounded commit/catalog/execution
metadata only. It selects the latest commit available at the requested cutoff
and matching receipts whose declared creation clock is no later than the cutoff.
Valid future commits/receipts do not change an earlier view; unavailable
future catalogs are not read. All discovery reads still consume the existing
metadata budget, while catalog `metadata_bytes` counts only visible commits,
the selected catalog and matching visible receipts. These declared metadata
clocks do not certify historical PIT. The probe retains dataset states but
never calls this original-pack or execution validation. Actual consumption must use
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
The publisher records its exact repository code SHA separately from the
reusable catalog identity. Source/locator fingerprints are checked before and
after construction; changing them during replay refuses publication. The
twenty hash-bound risk/index/locator files use canonical LF bytes.

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
Publication requires `--code-sha` or the existing workflow's `GITHUB_SHA`.
`--learning-input-root` plus the externally supplied original policy hash
enable readiness checks without manufacturing a policy or changing state.

The existing Daily Crisis Monitor builds/publishes the index after primary
capture, then consumes its current request. Index failure points the run at
the attempted root and fails the final gate, never at a restored old success.
The research cycle runs only after its original state restore and a successful
index when primary collection is enabled. Existing enable flags and the single
writer remain in place. Primary/index work uses the existing60-minute ceiling
(30 minutes when disabled); no additional schedule is installed. This accounts for paired
readback plus bounded legacy metadata reads without raising object/request caps.
An index with a blocked core can still retain its diagnostic metadata, but its
CLI/workflow step fails and cannot start the dependent research cycle.

## Evidence needed to open each remaining gate

| Use | Existing owner route | Required evidence |
| --- | --- | --- |
| Native current risk classification | `build_run287_chameleon_macro_inputs.py` and the existing source adapter | Current source originals, availability clocks and hashed NYSE calendar; keep the native eight-ready-axis gate and required breadth/volatility/credit axes. |
| Fourteen-ETF historical evaluation | `research_model_inputs.py`, original price Readers and `run_a4_research_cycle.py` | Complete retained price arrays, session coverage, adjustment/return basis, original hashes, purpose-specific rights and an externally reviewed learning policy. A rotation summary or price hash alone is insufficient. |
| Historical macro evidence | `long_history_lake.py:Lake.verified_execution` and the existing original Readers | Matching current catalog/execution/quality, verified packs, usable rights and dated vintage/release evidence. A current revised history is not historical PIT. |
| ICI / ICE / FINRA context or training | Existing source policy and financing input routes | Provider permission for the intended collection, cloud retention and analytical purpose; public visibility or collection consent is not a rights receipt. |
| Quantified future forecast | Existing learning cycle and `forecast_release` | Mature outcomes, fixed trial/experiment census, independent recipe and release review. Conditional scenarios alone supply no calibrated probabilities. |
| A5 model allocation | Existing `MODEL_PORTFOLIO` path | Current original A3 expected returns, exact independent A6 evidence, reviewed risk/cost limits and the A4 report. Missing prerequisites continue to block numerical weights. |

Research-cycle activation additionally requires the existing durable checkpoint restore/readback and reviewed policy pins. Neither the catalog nor these operational instructions create rights, independent reviews, a new accepted model or an accepted paper account.

The offline native-request format handoff is
[native input handoff](A4_NATIVE_INPUT_HANDOFF_V1.md). It replays the
unchanged native readiness gate before emitting the request consumed by the
existing collector. The Source owner still supplies the independently pinned,
qualified original normalizer result; local preparation is not supplier-rights
review, Source/PIT admission, historical learning or a new cloud activation.

The daily wrapper also retains its existing current-session source snapshot,
coverage and clock checks. A fresh A4 capture cannot refresh or authorize a
stale legacy success row; wrapper completion and A4 context capture remain
separate results until their respective current inputs pass.

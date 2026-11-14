# Existing native Source outputs into A4

`tools/prepare_a4_native_inputs.py` supplies the missing offline format handoff
from `build_run287_chameleon_macro_inputs.py` to the existing A4 request reader.
It creates no collector, provider call, scheduler, accepted state or data-use
permission. The Source owner must independently qualify the original sources,
identity, research-use rights and actual coverage before publishing this packet.
A successful local preparation is not evidence of that upstream qualification.

Supply one exact original normalizer manifest SHA256 and its five output files:
`xnys_calendar.csv`, `input_metrics.csv`, `input_context.csv`, `source_audit.csv`
and `source_lineage.json`. Stored Linux paths are locators only: the preparer
reads these fixed names under the explicit local root, with bounded sizes,
symlink rejection and a cumulative64MiB byte limit. It verifies every original
output hash, producer implementation and frozen contract, calendar/row lineage,
original FREE_PROXY truth classification, and all report-only safety flags.

The original `market_analysis_engine.native_risk` then validates the calendar,
session grid, availability clocks and unchanged ten-axis readiness. At least
eight axes, including breadth, volatility and credit, must be ready. Missing
required axes, stale sessions, future rows, changed Source/code or conflicting
destination bytes refuse the handoff before writing a request. The original
native breadth producer still requires500 covered symbols; fourteen ETF prices
are not a substitute for the market-breadth denominator.

```powershell
python tools/prepare_a4_native_inputs.py --source-root <qualified-normalizer-root> `
  --manifest-sha256 <independently-pinned-original-manifest-hash> `
  --output-dir <new-private-handoff-root>
```

The CLI uses the actual execution time and latest completed NYSE session.
Its `request.json`/`request.sha256` and three immutable `native/<sha256>` objects
are consumed by the existing collector's `--existing-input-root` option.

If the Source owner supplies current HY/IG originals separately, pass both
`--current-credit-input-root <current-credit-root>` and
`--current-credit-request-sha256 <independent-request-hash>`. The pinned request
must be current and unexpired. Only its registered FRED HY/IG `macro`/`macro_v2`
roles are retained; native operands in that separate request cannot replace the
five-file Source manifest. Original byte hashes, normalization and clocks stay
unchanged. Invalid, missing, changed, stale or future configured credit refuses
preparation before the request commit marker. These originals do not make a
missing native axis ready or grant data rights or historical training approval.

The same hosted workflow has an additive, default-off preparation stage. After
Source qualification, its owner publishes/rechecks the normalizer's original
manifest and five files under the existing private
`outputs/market_analysis_inputs/native_source` restore tree, and independently
pins that original manifest in `A4_NATIVE_SOURCE_MANIFEST_SHA256`. This pin
identifies a reviewed input; setting it is not supplier or Source/PIT approval.
An optional `A4_CREDIT_REQUEST_SHA256` independently pins
`outputs/market_analysis_inputs/current_credit/request.json` and its originals
in that same private restore tree. It also requires the native Source manifest
and primary collection. A configured but invalid credit handoff follows the
same failed-preparation and legacy-writer guards; it cannot silently fall back.
Primary collection must also be enabled. Preparation records its attempted
root before replay; a failure cannot fall back to the restored old request and
fails the final durable gate. Only its metadata receipt is uploaded as an
artifact. A failed configured preparation also skips the legacy daily history
writer and its artifact/sync steps. With no pin, the workflow retains its existing input path and visibly
blocked native behavior. No enable flag, secret, Source publication or accepted
state is changed by deploying this code. Existing learning enablement and
checkpoint contracts are unchanged.

`native-preparation.json` binds the original manifest/output hashes and the
preparer/runtime identity. Request operands also retain the original manifest
and lineage pins. Their collection clock is explicitly the derived-packet
preparation time, while every source observation/availability clock is unchanged.
It cannot refresh an old source session or manufacture historical PIT. The
request hash commit marker is written last; same inputs/time reuse identical
bytes, and a conflicting old destination is never overwritten.

Original Source objects are not independently replayed by this format handoff.
Supplier rights remain uncertified by it. Current-vintage histories remain
FREE_PROXY and are not admitted into historical training/backtests. Learning
still requires its separate fourteen-target, original-bound price/vintage and
externally reviewed policy gates. A3/A5, orders, ledgers, model promotion and
the legacy daily report's late-session guard are unchanged.

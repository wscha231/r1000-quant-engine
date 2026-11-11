# A4 primary-original collection

The existing Daily Crisis Monitor workflow can capture the Board's H.4.1,
H.8 and policy-rate SDMX originals, plus the New York Fed's last30 SOFR,
TGCR and EFFR observations. This bounded research capture does not call FRED,
replace the Lake head, alter the shared price/financial registry or write an
accepted portfolio. Other macro sources still require their own qualified
producer and rights evidence; these six feeds do not complete ten-axis risk.

## Collection and data center

`tools/collect_a4_primary_data.py` uses a closed six-feed list: six provider
requests, each at most18MiB, no arbitrary URL, redirect, credentials or provider
retry. ZIP expansion is limited to220MiB, selected retained rows to256MiB and
150,000 rows. Native series identity, currency, frequency, SA basis and units
are checked. Twenty H.8 series cover deposits, loans, C&I loans, cash and assets
for all, domestic, large and small banks. Seven H.4.1 series keep Wednesday
levels distinct from weekly averages, including total/foreign/other RRP.
IORB starts in2021; old IOER/IORR are not silently spliced into it. Its explicit
current observation window ends at the latest common funding date.

Objects use the existing scoped research transport and shared Reader hash/byte
checks, under the configured canonical research base:

- `shared-research-v1/macro-primary/objects/<sha256>`: exact ZIP/JSON or
  deterministic normalized gzip JSONL;
- `shared-research-v1/macro-primary/generations/<sha256>.json`: one immutable
  capture manifest binding original/normalized hashes, clocks, source identity,
  native units, normalizer bytes, actual window, attribution and closed authority;
- `shared-research-v1/macro-primary/executions/<sha256>.json`: the exact attempt,
  its capture pins, readbacks, failures and training blockers.
- `shared-research-v1/macro-primary/reports/<sha256>.json`: original pinned A4
  request/report diagnostics, read back before the execution receipt; a blocked
  report remains blocked, not accepted input or model authority.

This is a new primary-source component of the same data center, not a second
accepted account or model authority. No `latest`, old-success fallback or
synthetic long-history execution is created. `read_generation(transport, pin,
cutoff=...)` requires an exact manifest pin, verifies both objects and replays
normalization from the original. A changed normalizer fails closed until a
reviewed migration; no original or manifest is overwritten. Same-byte originals
reuse their hash paths. Different actual collection times are distinct captures.
Normalized gzip headers use explicit level6, empty filename and mtime0. Readers
verify the archived compressed hash, then compare bounded canonical JSONL rows
against the original replay. They do not recompress as an equality check:
Python3.12/3.14 and zlib versions can encode identical rows differently.

Data objects precede capture manifests. Every published object is reread and
the full original/normalized pair is replayed. An execution is written last
and reread. A local transport never proves Drive publication. Failure receipts
are audit records, not accepted input. A failed feed prevents publication of
the aggregate input request. A failed execution readback leaves a separate
immutable `publication_failed.json` witness and a failing process.

## Existing cloud cadence

After exact-head review/merge and a successful bounded dispatch, set repository
variable `A4_PRIMARY_COLLECTION_ENABLED=true`. Provide the dedicated
`A4_RCLONE_CONFIG_GDRIVE` secret in the existing `[gdrive]` config format. The
existing `configure_macro_research_drive.py` makes a temporary scoped research
configuration; no global desktop config or shared credential secret is changed.
When primary capture is enabled the existing job's legacy restore/checkpoint
transport also selects that dedicated credential, so shared-client quota does
not leave the consumer on a different failing authentication path. With the
flag disabled its prior credential selection remains unchanged.
Existing shared-client quota failures do not count as absence or genesis.

The existing weekday22:30UTC GitHub-hosted run is the scheduler. It continues
when the user's computer is off. Primary capture and durable readback have
separate required outcomes. Once enabled, the attempted primary input root is
selected even on failure so a restored old report cannot replace today's failure.
Only a current, valid original request can supply native risk operands; its
hashes and total byte bound are rechecked before copying. Native risk gates,
all ten axes and A5 policy/independent review remain unchanged. The collector
may succeed while the complete report truthfully remains `DATA_BLOCKED`.

`A4_RESEARCH_ENABLED` and `A4_RESEARCH_ALLOW_STATE_GENESIS` remain separate
consumer/checkpoint settings. Collection does not enable a learning policy,
manufacture an independent review, renew an expired policy or run a fullrun.
The cycle uses `--learning-input-root outputs/market_analysis_inputs` to retain
the separately restored, externally pinned learning request/policy/payload and
originals. The new market capture directory does not replace or copy that bundle.
All existing policy/hash/clock checks still run; input roots cannot overlap state
or attempt output. A changed A4 request still requires a new current A3/A6 graph
before A5 can consume it.
Dispatch success is separate from a verified scheduled run and from actual
model/portfolio completion.

## Historical learning boundary

The Board's currently downloadable history includes revisions. Observation
dates and HTTP Last-Modified are not original release availability. Preserve
the raw history, null publication clocks and actual collection timestamp;
allow these snapshots only as forward captures. An external learning policy
cannot label `frb:` captures as `DATE_ARCHIVE_RESEARCH_ONLY`.

The existing learning code accepts the closed `frb:` semantic register with
`FORWARD_CAPTURE_ONLY`, independent reviewed rights/source pins and exact input
pins. The original14 ETF targets, seven horizons, outcome maturity, purged
expanding-window/HAC/BY math, do-not-repeat checks and challenger-only boundary
remain. No mature historical features can be created from today's revised
capture. Qualified ETF price originals/rights and dated historical macro
vintages must be independently supplied before claiming a real historical fit.
Missing policy, labels or independent samples are blocked/insufficient evidence,
never a completed model or a valid first portfolio.

Board-produced data are attributed to the Board under its
[public-domain notice](https://www.federalreserve.gov/disclaimer.htm), excluding
marked third-party material. New York Fed data retain reference-rate attribution,
non-endorsement and DTCC notices under its
[terms](https://www.newyorkfed.org/privacy/termsofuse). Those public notices do
not authorize unrelated retained FRED/ICE/price data. Existing FRED AUTO settings
and legacy Lake execution gates remain unchanged.

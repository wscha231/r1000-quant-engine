# Run287 current decision frame - 2026-07-13 close

## Outcome

The bounded current-decision substrate is ready for research scoring, but not
for ranking, portfolio mutation, production, or live trading.

- Status: `READY_COMPLETE_CURRENT_DECISION_FRAME`
- Decision tickers: `989`
- Frozen model features: `238`
- Scaled finite coverage: `100%`
- Raw finite coverage: `84.41597063496784%`
- Missing-neutral violations: `0`
- Future feature rows: `0`
- Feature availability: `2026-07-13T23:59:59Z`
- Decision time: `2026-07-14T05:00:00Z`
- PIT universe membership clean: `false`

Canonical evidence:

- `outputs/run287_current_decision_frame_20260714_close_20260713_v4/manifest.json`
- selection context SHA-256:
  `83ae5d5e6479a637e74f0a9f4bf47fcdcd30f2a511767165ebddbe9c0be78bfc`
- scaled input SHA-256:
  `71cb23e233372c140470d9a599977683938e63f10936cae1ad5b17d67cf78090`

## Bounded refresh work

The current price packet was not enough by itself: benchmark, macro, and SEC
inputs still represented earlier observation dates. The refresh used isolated,
source-immutable sidecars.

- Macro: 9/9 market components, 13/13 FRED components, 49/49 finite macro
  columns, 2 network requests.
- Benchmark: official FRED `SP500`, latest observation available by the
  decision time `2026-07-10`, 6/6 benchmark and 5/5 live-event columns, 1
  network request.
- SEC: daily master indexes for July 10 and July 13 reduced the refresh from
  989 issuers to 49 CIKs. The packet contains 56/56 exact accepted-time rows,
  no future row, 55 event-metadata rows, and one statement candidate.
- Companyfacts: only DAL required a statement refresh, so one Companyfacts
  request was made. Canonical SEC/Google Drive inputs were not mutated.

The recent SEC delta used 51 requests instead of refreshing every universe CIK.
The entire macro/benchmark/SEC/Companyfacts completion used 55 bounded
requests.

## DAL 10-Q effect

DAL filed an exact accepted 10-Q at `2026-07-10T16:17:17Z`, covering
`2026-06-30`. The existing context still carried the April 8 statement.

- Exact Companyfacts records: `331`
- Selected exact records: `271`
- Fundamental panel rows: `35`
- Refreshed shared values changed: `71`
- Frozen model features changed: `41`
- TTM revenue: `63.364B -> 68.287B`
- TTM operating income: `5.822B -> 5.516B`
- TTM net income: `5.005B -> 3.950B`
- TTM operating cash flow: `8.342B -> 8.134B`
- Sales growth YoY: `2.79% -> 10.27%`
- Operating margin: `9.19% -> 8.08%`

No filed-date fallback or forward return was used. The current ticker/CIK map
remains a present-day identity snapshot, so this is current-decision research
evidence only.

## Failed attempts retained

- `...current_decision_frame.../` stopped before writing evidence because one
  exact SEC timestamp was timezone-aware while the frozen context used
  timezone-naive UTC.
- `...current_decision_frame..._v2/` completed calculations but stopped while
  serializing a mixed string/Timestamp `fund_period` column.
- `v3` normalized timestamps to the frozen UTC representation and period fields
  to `YYYY-MM-DD`; `v4` reran the identical calculation after extracting those
  normalizers into tested functions. `v3` and `v4` have identical selection
  context and scaled-input hashes; `v4` is pinned to the final builder hash.

These failed append-only outputs are intentionally retained and must not be
deleted or reclassified as valid evidence.

## Safety and next gate

Direct `python r1000_pipeline.py` execution now fails closed unless both
`R1000_ALLOW_DIRECT_FULLRUN=1` and `--allow-direct-fullrun` are supplied. No
fullrun was executed in this work.

Local Tier-1 PR validation passed `159/159`, including the restored macro,
benchmark, exact-fundamental, complete-cross-section, direct-fullrun guard, and
new recent-SEC/current-frame contracts.

The next step is a separate score-only artifact from this verified context,
followed by the pinned advisory selector comparison and 25/50/100 bps turnover
cost review. It must remain next-close and non-executable. No fixed-book or
generated-book A/B starts until that review is complete.

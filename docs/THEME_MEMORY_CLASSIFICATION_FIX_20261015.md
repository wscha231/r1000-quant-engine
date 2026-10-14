# Memory/storage classification correction

Research-only. The existing memory theme includes memory semiconductors and
digital storage hardware. Curated issuer tickers retain membership. Generic
storage branding and inherited theme labels are insufficient business evidence.
Qualified memory/storage terms use word boundaries and direct business metadata;
physical/energy storage is excluded and supplied nonhardware industries reject
name-only hardware phrases. Missing-industry sentinels remain missing. Direct
storage/REIT or storage/real-estate metadata resolves to real_estate before generic
space/storage keywords, preserving curated issuer mappings.

Both consumers still use the same infer_theme function. Tests exercise actual
daily build_ticker_tape and monthly add_theme_and_scores, the six actual archived
business rows, and broader positive/negative controls. The two small fixtures
are extracted from the 20260510 ticker_leadership.csv and theme_leadership.csv;
they retain original leadership_theme fields as the regression's old outcome.

## Bounded historical diagnostic

Base: 40b68f0757e161888642decf10c6697950f331a3. Input directories are the existing
cloud_results/full_rebuild/{date}_global_alpha_universe/theme_leadership_tape.
No prices were fetched or refreshed. Reuse every saved ticker-level metric and
change only classification. The old classifier exactly reproduces all saved
labels; aggregate numeric reproduction passes rtol=1e-12, atol=1e-10. Individual
monthly member scores remain unchanged. All theme aggregates are recalculated
together because robust_z depends on the full theme cross-section.

| Archive | Rows | Memory members | Memory score before | After | Delta | Memory rank |
|---|---:|---|---:|---:|---:|---|
| 20260510 | 731 | 6 → 4 | 2.86668698365 | 3.76318917122 | +0.89650218757 | 1 → 1 |
| 20260512 | 730 | 6 → 4 | 2.66923139366 | 2.81968468603 | +0.15045329237 | 1 → 1 |

Exactly two rows change in each complete archived input: PSA and EXR move from
memory_semiconductors to real_estate. MU/SNDK/STX/WDC remain memory members;
the other 729/728 row classifications are unchanged. Larger memory scores after
removing weaker real-estate constituents do not imply better strategy returns.
Other theme scores/ranks change through cross-section normalization. May10 memory
state changes emerging_leader→climax_hot; May12 remains emerging_leader.

Input ticker CSV SHA256:

- 20260510: b70f658a1552ee684072846a59e68fb70868f556f12bfe9445b6097ac70eb0e8
- 20260512: 6e39d0bbf018afb2e3e2a2c5f75de87d7b8f567a0bd650824dd518d9dde0691a

Versioned [evidence manifest](theme_memory_fix_evidence_20261015/manifest.json)
identifies all before/after aggregate CSVs, all-theme score/rank deltas, membership
deltas and input hashes with exact sizes/SHA256. Files are checked in under
[the separate diagnostic directory](theme_memory_fix_evidence_20261015/). Original historical reports and
metrics are unchanged. This is a reclassification diagnostic on frozen archived
metrics, not a fullrun, historical PIT certification, alpha/OOS validation or a
measurement of October 2026 latest theme ranks. Uncurated ambiguous names without
industry/business evidence can now be conservatively excluded.

## Final-review performance correction

Static business normalization and all memory/real-estate matchers are compiled
once. Each row's business fields are normalized once and shared by both checks.
Real-Estate, Real_Estate and Real Estate therefore use the same real_estate label.
The hot-path regression refuses per-row regex construction.

On the exact existing latest candidate replay book, classification-only apply on
46,772 rows took2.027s(parent),11.359s(initial correction),2.642s(precompiled
correction) in one local run per implementation. Initial/corrected labels agree
on all rows. [Timing evidence](theme_memory_fix_evidence_20261015/performance_correction.json)
pins the input Git blob. These are illustrative elapsed times, not a universal
performance guarantee or a CI timing threshold; no replay/fullrun was executed.

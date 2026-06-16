# Ledger Reconciliation 2026-06-15

## Summary

Claude and Codex both produced `tools/run_performance_ledger.py` during the
2026-06-15 self-sustaining-loop work. The executable implementation in
`origin/codex/self-sustaining-loop-20260615` is canonical because it is based on
the current clean PR64 branch. The Claude branch remains a research/data source.

## Schema Check

The bull-floor verdict row from
`origin/claude/analyze-updated-code-OfEbu:cloud_results/performance_ledger/ledger.jsonl`
was compared against the first row in PR64's
`cloud_results/performance_ledger/ledger.jsonl`.

Result:

- top-level field set: identical
- `portfolios.main` field set: identical
- `portfolios.concentrated` field set: identical
- source run: `27516185696`
- source commit: `cd48042`

No schema translation was required. The row was ported as data and the PR64
ledger summary/verdict were regenerated from the canonical Codex ledger logic.

## Verdict Preserved

The port preserves the only measured bull-floor A/B result:

| Portfolio | IS-CAGR Before | IS-CAGR After | Full CAGR After | MDD After | Interpretation |
| --- | ---: | ---: | ---: | ---: | --- |
| Main | 21.45% | 22.90% | 35.20% | -24.49% | improved; Tier-1 headline passes |
| Concentrated | 21.29% | 22.41% | 44.43% | -25.92% | improved IS-CAGR; headline CAGR/MDD still miss canonical mission |

Both portfolios still fail strengthened gates on `is_cagr_min` and
`oos_is_cagr_ratio_max`, so this is evidence for further A/B, not production
promotion.

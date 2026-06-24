# Era-Aware Scoring Challenger

- sidecar_only: `true`
- production_activation_allowed: `false`
- status: `completed`
- candidate_book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv`
- candidate_rows: `46772`
- scored_rows: `46772`
- rebalance_dates: `84`

## Outputs

| Portfolio | Target Book | Rows |
| --- | --- | ---: |
| concentrated | `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/era_aware_scoring_challenger/era_aware_concentrated_target_book.csv` | 504 |
| main | `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/era_aware_scoring_challenger/era_aware_main_target_book.csv` | 1344 |

## Goal Verdicts

| Portfolio | CAGR | MaxDD | Tier-1 | Tier-2 | Review Status |
| --- | ---: | ---: | :---: | :---: | --- |
| concentrated | 16.12% | -51.58% | FAIL | FAIL | not_eligible |
| main | 17.42% | -37.59% | FAIL | FAIL | not_eligible |

## Promotion Policy Candidate

- review_candidate_portfolios: `none`
- human_approved: `false`
- production_mutation_allowed: `false`
- allow_replace_operating_target_books: `false`
- policy_candidate_path: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/era_aware_scoring_challenger/era_aware_approved_target_policy_candidate.json`

The generated books are review-only challengers. They are broker-replayable, but they do not replace `outputs/reports/operating_*_target_book.csv`.

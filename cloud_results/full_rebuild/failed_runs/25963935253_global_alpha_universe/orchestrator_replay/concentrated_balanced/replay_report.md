# Orchestrator Replay

- Status: `blocked_missing_concentrated_monthly`
- Data mode: `proxy_top_raw_score_within_main_holdings`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 23.65% | 25.00% | -25.75% | -20.00% | false |
| concentrated | 21.24% | 40.00% | -31.36% | -22.00% | false |
| unified_balanced | 16.77% | 28.00% | -21.01% | -22.00% | false |

## Interpretation

Historical concentrated_strategy_monthly.csv is missing, so concentrated returns are only a proxy from selected main holdings.
Run the full rebuild after this change so reports/concentrated_strategy_monthly.csv is preserved into cloud_results.
Production remains blocked until target gates and human approval pass.

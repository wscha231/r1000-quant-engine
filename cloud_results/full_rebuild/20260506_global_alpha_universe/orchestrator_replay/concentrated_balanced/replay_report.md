# Orchestrator Replay

- Status: `blocked_missing_concentrated_monthly`
- Data mode: `proxy_top_raw_score_within_main_holdings`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 33.91% | 25.00% | -14.05% | -20.00% | true |
| concentrated | 26.01% | 40.00% | -27.63% | -22.00% | false |
| unified_balanced | 23.24% | 28.00% | -12.45% | -22.00% | false |

## Interpretation

Historical concentrated_strategy_monthly.csv is missing, so concentrated returns are only a proxy from selected main holdings.
Run the full rebuild after this change so reports/concentrated_strategy_monthly.csv is preserved into cloud_results.
Production remains blocked until target gates and human approval pass.

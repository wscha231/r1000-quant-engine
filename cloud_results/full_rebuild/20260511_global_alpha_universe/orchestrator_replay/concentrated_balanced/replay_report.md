# Orchestrator Replay

- Status: `completed`
- Data mode: `historical_concentrated_monthly`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 31.29% | 25.00% | -15.69% | -20.00% | true |
| concentrated | 39.86% | 40.00% | -16.58% | -22.00% | false |
| unified_balanced | 24.39% | 28.00% | -11.72% | -22.00% | false |

## Interpretation

Replay used historical concentrated monthly returns and can be used as a challenger input.
Production remains blocked until target gates and human approval pass.

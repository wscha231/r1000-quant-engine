# Orchestrator Replay

- Status: `completed`
- Data mode: `historical_concentrated_monthly`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 33.26% | 25.00% | -15.19% | -20.00% | true |
| concentrated | 43.22% | 40.00% | -15.05% | -22.00% | true |
| unified_balanced | 26.58% | 28.00% | -11.34% | -22.00% | false |

## Interpretation

Replay used historical concentrated monthly returns and can be used as a challenger input.
Production remains blocked until target gates and human approval pass.

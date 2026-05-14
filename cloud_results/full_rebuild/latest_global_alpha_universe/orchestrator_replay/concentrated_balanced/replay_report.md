# Orchestrator Replay

- Status: `completed`
- Data mode: `historical_concentrated_monthly`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 35.17% | 25.00% | -15.20% | -20.00% | true |
| concentrated | 45.49% | 40.00% | -17.13% | -22.00% | true |
| unified_balanced | 27.72% | 28.00% | -11.90% | -22.00% | false |

## Interpretation

Replay used historical concentrated monthly returns and can be used as a challenger input.
Production remains blocked until target gates and human approval pass.

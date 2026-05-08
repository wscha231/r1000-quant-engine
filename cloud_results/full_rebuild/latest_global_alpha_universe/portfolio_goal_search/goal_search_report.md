# Portfolio Goal Search

Artifact-only ranking against explicit portfolio targets. Production defaults are unchanged.

## Targets

| Portfolio | CAGR Target | MaxDD Target |
| --- | ---: | ---: |
| main | 30.00% | -15.00% |
| concentrated | 50.00% | -18.00% |

## Best Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `experiment_E6_risk_sensing_on` | 18.47% | 11.53pp | -21.63% | 6.63pp | false | `blocked_both` |
| concentrated | `experiment_E4_concentrated_balanced` | 34.85% | 15.15pp | -22.94% | 4.94pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `experiment_E6_risk_sensing_on` | 18.47% | 11.53pp | -21.63% | 6.63pp | 1.119 | false | experiment:outputs/experiments/E6_risk_sensing_on/metrics.json |
| `experiment_E0_baseline_latest` | 21.40% | 8.60pp | -27.27% | 12.27pp | 1.183 | false | experiment:outputs/experiments/E0_baseline_latest/metrics.json |
| `experiment_E2_main_v2_balanced` | 21.40% | 8.60pp | -27.27% | 12.27pp | 1.183 | false | experiment:outputs/experiments/E2_main_v2_balanced/metrics.json |
| `experiment_E3_main_v2_aggressive` | 21.40% | 8.60pp | -27.27% | 12.27pp | 1.183 | false | experiment:outputs/experiments/E3_main_v2_aggressive/metrics.json |
| `experiment_E5_orchestrator_balanced` | 21.40% | 8.60pp | -27.27% | 12.27pp | 1.183 | false | experiment:outputs/experiments/E5_orchestrator_balanced/metrics.json |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `experiment_E4_concentrated_balanced` | 34.85% | 15.15pp | -22.94% | 4.94pp | 1.429 | false | experiment:outputs/experiments/E4_concentrated_balanced/metrics.json |
| `concentrated_policy_replay` |  |  |  |  |  | false | sidecar:outputs/concentrated_policy_replay/metrics.json |
| `concentrated_position_risk_proxy` |  |  |  |  |  | false | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `monster_lifecycle_replay` |  |  |  |  |  | false | sidecar:outputs/monster_lifecycle_replay/metrics.json |
| `monster_lifecycle_review_concentrated` |  |  |  |  |  | false | sidecar:outputs/monster_lifecycle_review_concentrated/metrics.json |

## Next Actions

- Main: run true Main v2 historical challenger; current artifacts do not meet both CAGR and MaxDD targets.
- Concentrated: run full concentrated grid replay from concentrated_strategy_monthly and reject proxy-only evidence.

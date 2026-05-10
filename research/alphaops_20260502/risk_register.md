# R1000 AlphaOps Risk Register

Date: 2026-05-02 KST

| ID | Risk | Severity | Probability | Why it matters | Mitigation | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | Overfitting from many experiments | High | High | A 6-8 year window can make random variants look strong | Keep baseline registry, log failed tests, use cost sensitivity and stress windows | Research and production gates |
| R2 | Main book concentration too aggressive | High | Medium | Target N 7-10 can lift CAGR but may break MDD target | Test N variants separately; cap single-name and sector exposure | Target-N A/B gate |
| R3 | Drawdown hidden by partial data window | High | Medium | Latest 8/10 year comparison is partial at 82 months | Always report actual months and 5/8/10 status | Window validity gate |
| R4 | Survivorship or universe drift | High | Medium | Current Russell proxy/global alpha universe may not match historical membership | Keep universe snapshots and coverage reports; avoid claiming 10-year proof if data incomplete | Data coverage gate |
| R5 | ADR/global company financial unit mismatch | High | Low/Medium | Foreign issuer values can distort score and market cap if not normalized | Preserve ADR USD market-cap normalization; audit currency/unit fields | ADR data gate |
| R6 | Auto feature gates mutate production silently | High | Medium | Bad gates can disable useful signals or amplify false edges | Proposal-only; challenger A/B; no direct active YAML creation | Auto-learning promotion gate |
| R7 | Tactical sleeve turnover overwhelms alpha | High | Medium | Weekly trading plus 25 bps per side can erase edge | Standalone tactical cost test; turnover cap; bull-only capacity | Tactical gate |
| R8 | Explosion model inactive but assumed active | Medium | High | `explosion_*` currently falls back to zero | Require model health report before relying on explosion score | Feature health gate |
| R9 | Regime classifier stuck neutral | High | Medium | Regime-conditioned allocation is useless or dangerous if classifier lacks variation | Regime distribution health test; no allocation impact until passed | Regime health gate |
| R10 | Risk rules sell winners too early | High | Medium | The engine's edge depends on holding winners | Separate hard stops for broken names from continuation-winner override | Risk A/B gate |
| R11 | Concentrated sleeve single-name exposure | High | Medium | Concentrated CAGR can be high while hidden name risk is unacceptable | Define max ticker cap and max sleeve capacity before production use | Concentrated gate |
| R12 | Leverage amplifies unproven alpha | Critical | Medium | Leverage can turn moderate drawdown into forced liquidation | Defer leverage; require unlevered gates first; start at 1.15x only | Leverage gate |
| R13 | Execution cost/slippage under-modeled | High | Medium | 25 bps per side may be too low for thin names and tactical trades | Add order ticket cost model and sensitivity 10/25/50/100 bps | Execution gate |
| R14 | Broker/API automation failure | Critical | Medium | Bad orders, stale positions, or API disconnects can cause real loss | Signal-only first, paper broker, reconciliation, kill switch | Live trading gate |
| R15 | GDrive/GitHub artifact drift | Medium | Medium | Local and cloud artifacts can disagree | Baseline registry with run id, commit, artifact path, GDrive timestamp | Artifact gate |
| R16 | Workflow sprawl and duplicate automations | Medium | High | Too many workflows make state hard to reason about | Compress into daily signal, monthly full rebuild, quarterly learning, smoke test | Automation audit |
| R17 | Branch divergence | High | Medium | Stale feature branches can overwrite master improvements | Fresh fetch before implementation, compare against upstream, no force push | Git hygiene gate |
| R18 | Config drift across local, Colab, GHA | Medium | High | Same engine run can mean different settings | Config audit report before full rebuild | Config audit gate |
| R19 | Dynamic theme false positives | Medium | Medium | New theme clusters can chase noise | Sidecar first; require retrospective early-winner recall | Theme gate |
| R20 | User goal pressure causes unsafe optimization | High | High | 40-50% CAGR targets invite overfitting and leverage abuse | Separate research stretch targets from production gates | Ship gate discipline |

## Risk Priority For Next Work

Top risks to reduce first:

1. R1 overfitting.
2. R6 auto gate mutation.
3. R9 regime classifier health.
4. R13 execution realism.
5. R18 config drift.

The immediate implementation batch should reduce these risks before pursuing
CAGR-heavy experiments.


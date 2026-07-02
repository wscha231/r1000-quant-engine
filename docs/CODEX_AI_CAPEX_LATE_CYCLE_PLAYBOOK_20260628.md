# AI Capex Late-Cycle Playbook — 2026-06-28

## Purpose

This playbook converts the uploaded AI capex / late-cycle research packets into reusable AlphaOps research signals.

It does not create a buy list, production policy, fullrun trigger, or live-trading instruction.

## Thesis

The useful interpretation is not "buy AI beneficiaries." The useful interpretation is:

> In a late-cycle AI capex regime, prefer companies that own bottleneck assets in the AI buildout value chain, where hyperscalers cannot easily stop spending and supply cannot quickly expand. Confirm the thesis with PIT earnings revisions, guidance, margins, and relative strength, then validate only through broker-ledger A/B.

## Source Treatment

The uploaded packets are research inputs with different confidence levels:

- Macro / strategy research: useful for regime and style framing.
- AI value-chain idea packet: useful for taxonomy design, but stock-level claims are `idea_only` until verified by primary sources.
- FactSet-style earnings insight: useful for earnings revision, guidance breadth, sector leadership, and valuation-stretch schema design.

Non-negotiable:

- Stock-specific PDF examples are not buy rules.
- No hardcoded ticker/date/sector policy.
- Every earnings, guidance, transcript, and event input must have `available_from <= decision_date`.
- Forward returns are audit labels only.
- Broker-ledger A/B is required before any fullrun.

## Value-Chain Buckets

The taxonomy lives in `tools/ai_capex_taxonomy.py`.

Buckets:

- `AI_COMPUTE`: GPU, accelerator, ASIC, CPU/DPU compute
- `AI_MEMORY`: HBM, DRAM, advanced memory
- `AI_STORAGE`: NAND, enterprise SSD, HDD replacement, AI data lake storage
- `AI_CONNECT`: Ethernet, AEC, optical, retimer, SerDes, CPO
- `AI_POWER`: nuclear, gas, power generation, PPA, baseload
- `AI_GRID`: transformers, switchgear, transmission, grid equipment
- `AI_COOLING`: liquid cooling, thermal, HVAC
- `AI_EQUIPMENT`: semiconductor equipment, test, packaging
- `AI_FOUNDRY`: advanced nodes, foundry, CoWoS, advanced packaging
- `AI_OTHER`: unclassified

Known tickers in the taxonomy are seed examples only. They provide diagnostics and coverage, not portfolio selection.

## Signals

### AI Capex Bottleneck

Produced by:

- `tools/run_ai_capex_candidate_enrichment.py`

Columns:

- `ai_capex_value_chain_bucket`
- `ai_capex_bottleneck_score`
- `ai_capex_supplier_type`
- `ai_capex_pricing_power_score`
- `ai_capex_substitution_risk`
- `ai_capex_customer_concentration_risk`
- `ai_capex_peakout_risk`
- `ai_capex_source_confidence`

### Earnings Revision / Guidance

Produced by:

- `tools/build_earnings_revision_signals.py`

Core columns:

- `eps_revision_4w`
- `eps_revision_13w`
- `eps_revision_26w`
- `revenue_revision_13w`
- `positive_guidance_flag`
- `negative_guidance_flag`
- `guidance_vs_consensus_score`
- `margin_revision_score`
- `sector_eps_revision_breadth`
- `sector_positive_guidance_ratio`
- `forward_pe_vs_5y_avg`
- `forward_pe_vs_10y_avg`

### Earnings Call Keyword Shock

Produced by:

- `tools/build_earnings_call_keyword_signals.py`

Families:

- `AI_CAPEX`
- `MEMORY`
- `POWER`
- `NETWORKING`
- `COST_PRESSURE`
- `PRICING_POWER`
- `CUSTOMER_PUSHBACK`

Scores:

- `ai_capex_demand_keyword_score`
- `bottleneck_pricing_power_keyword_score`
- `downstream_cost_pressure_keyword_score`
- `customer_pushback_keyword_score`
- `guidance_risk_keyword_score`

## Cheap Screen

Produced by:

- `tools/run_ai_capex_bottleneck_screen.py`

Hypothesis:

Late-cycle winners should be high-RS, positive-revision, AI capex bottleneck suppliers, not merely cheap value stocks.

Screen group:

- AI capex bucket present
- bottleneck score high
- EPS or revenue revision positive
- 3M RS / momentum positive

Acceptance to justify a default-off policy hook:

- sufficient candidate count
- sufficient OOS count
- positive full 126d excess
- nonnegative OOS 126d excess
- positive-rate at least 50%
- not one ticker only

This screen does not authorize a fullrun. It can only justify a later default-off hook proposal.

## Late-Cycle Regime Telemetry

Produced by:

- `tools/run_late_cycle_ai_regime_audit.py`

Flags:

- `late_cycle_ai_capex_regime`
- `bubble_precondition_score`
- `breadth_compression_score`
- `momentum_dominance_score`
- `valuation_stretch_score`
- `rate_shock_risk_score`

This is telemetry only. It must not force trades.

## Selection Philosophy

Candidate preference in this regime:

1. AI capex value-chain bucket is clear.
2. Bottleneck score is high.
3. EPS/revenue revisions are positive.
4. Guidance is positive or not deteriorating.
5. Relative strength is positive versus benchmark/sector.
6. Margin or pricing-power evidence confirms the thesis.
7. Valuation heat is allowed only if EPS revisions keep pace.
8. Customer concentration, substitution, peakout, and margin risks are visible.

Exit or trim pressure should rise when:

- EPS revision rolls over
- guidance cuts appear
- margin revision turns negative
- ASP/pricing commentary turns negative
- customer pushback or order delays rise
- price falls below MA200
- 3M RS breaks

## Operating Rules

Daily:

- update prices, RS, and momentum
- refresh AI capex candidate enrichment when candidate books refresh
- update available earnings/guidance/transcript event files

Weekly:

- run the AI capex bottleneck screen
- inspect sector revision breadth and positive guidance ratio
- review late-cycle AI regime telemetry

Earnings season:

- update guidance direction
- update transcript keyword shocks
- distinguish supplier pricing power from downstream cost pressure

Fullrun remains forbidden until:

1. cheap screen passes,
2. OOS direction holds,
3. default-off hook is implemented,
4. cheap broker-ledger A/B improves CAGR/MDD or a target-specific gate,
5. concentration and MDD gates hold,
6. data freshness and PIT checks are green.

Production remains blocked when `pit_universe_label_clean=false`.

# Investment Methodology V1 — style-neutral cross-method research layer

[PROJECT_HANDOFF]

- Date: 2026-09-21 KST
- Base: `wscha231/r1000-quant-engine` master after Moat/Quality V2 merge
- Mode: `RESEARCH_ONLY`
- Purpose: compare companies across sectors/countries using the same canonical research axes while preserving sector-appropriate evidence
- Non-scope: selector weights, target books, broker/ledger/orders, production, champion state, portfolio sizing
- Moat/Quality V2 remains the canonical evidence source for qualitative competitive-advantage claims

## 1. Why this layer exists

The repository already contains many useful methods and signals: quality/compounder,
GARP, Minervini/Superperformance, O'Neil-style leadership, market/industry RS,
earnings revisions, valuation, 13F/Form4/event evidence, macro/regime and crisis
risk. A naive implementation that adds a Buffett score, Graham score, O'Neil
score, Minervini score, etc. would count the same information repeatedly.

Investment Methodology V1 solves that by separating:

1. **canonical pillars** — counted once for equal comparison;
2. **method lenses** — different interpretations of the same pillars;
3. **sector profiles** — different evidence/metric interpretation, never extra weight.

Named methods are therefore explanatory views, not additive alpha factors.

## 2. Ten canonical pillars

1. `industry_structure_bottleneck`
   - Porter structure, value-chain profit pool, structural demand, capacity scarcity,
     substitutes, customer necessity and 2–5y bottleneck durability.
2. `moat_durability`
   - Moat V2 qualification/switching cost, IP/patent durability, pricing power,
     replacement difficulty and next-generation relevance.
3. `growth_runway_customer_product`
   - addressable runway, product roadmap, customer expansion, repeat demand,
     revenue/EPS/FCF growth and order/backlog quality.
4. `profitability_reinvestment_capital_efficiency`
   - ROIC/ROE, FCF economics, incremental margins, reinvestment opportunity,
     working-capital quality and dilution/SBC discipline.
5. `valuation_margin_of_safety`
   - forward PE, EV/EBITDA, FCF yield, PEG, sector/global peer valuation and
     Bull/Base/Bear valuation bridge.
6. `earnings_revision_operating_acceleration`
   - estimate revisions, guidance, earnings surprises, margin/FCF inflection,
     backlog conversion and operating acceleration.
7. `market_leadership_price_volume_rs`
   - 20/60/120/240D RS, benchmark/industry leadership, trend template,
     breakout/volume, overextension and price confirmation.
8. `management_governance_capital_allocation`
   - governance, dilution, buybacks, reinvestment, M&A discipline, shareholder
     treatment, incentives and execution credibility.
9. `catalyst_ownership_information_edge`
   - verified product/technology catalysts, 13F/Form4, ETF changes, order wins,
     regulatory events and evidence-backed news/event developments.
10. `downside_balance_sheet_cycle_regime`
    - leverage/liquidity, customer concentration, cyclicality, scenario downside,
      macro/regime sensitivity, MDD contribution and thesis invalidation risk.

All ten are required. Missing evidence is not imputed.

## 3. Equal evaluation policy

Two equal-weight diagnostic scores are reported separately:

- **absolute score**: business/investment quality versus the common `canonical-pillar-anchor-v1` scale;
- **peer-relative score**: a percentile computed from reviewed peer rank, not a manually entered relative score.

The peer percentile is computed as `(N-rank)/(N-1)`, where rank 1 is best. The reviewed peer snapshot is byte/hash verified. They are never blended automatically. This prevents a globally weak company from
looking strong only because its local peer set is weak, while still allowing
sector-specific economics to be judged fairly.

Every pillar has identical weight in these diagnostic scores. That equal weighting
is **research-only** and is not a claim that equal weighting maximizes alpha. Any
future selector weighting requires PIT/OOS validation.

Peer groups should prefer global industry peers where comparable data exists.
Any non-global peer scope requires an explicit exception reason. Lifecycle-stage
peers may be used for pre-commercial biotech or other structurally different
business stages, but the adjustment must be explicit.

Common absolute-score anchors are:
- 0.00: severe impairment / thesis-negative;
- 0.25: materially below investable/global standard;
- 0.50: neutral/mixed or ordinary economics;
- 0.75: strong, durable and evidence-backed;
- 1.00: exceptional/global best-in-class with durable multi-source evidence.

Intermediate values interpolate between these anchors.

## 4. Sector profiles — interpretation only

`SEMICONDUCTOR_HARDWARE`
- qualification time, yield/process know-how, design wins, node/roadmap relevance,
  customer concentration, dual sourcing, capacity and packaging/interconnect shifts.

`POWER_UTILITIES_INFRA`
- certification, installed base, local manufacturing, transformer/grid lead times,
  backlog quality, regulated/contract economics and replacement capacity.

`PROJECT_INDUSTRIAL_SHIPBUILDING_NUCLEAR`
- engineering qualification, yard/component slots, backlog margin quality,
  milestone/cost-overrun risk, working capital, customer concentration and
  localization.

`CONSUMER_BRAND_ODM`
- brand durability, repeat purchase, channel concentration, inventory, distributor
  economics, formulation/manufacturing know-how and ODM switching cost.

`BIOTECH_PRECOMMERCIAL`
- composition/platform/process IP, freedom to operate, partner validation,
  probability-adjusted pipeline value, royalty economics, cash runway and
  clinical/regulatory invalidation. PE/FCF is not forced when economically invalid.

`SOFTWARE_PLATFORM`
- retention, gross margin, unit economics, switching cost, ecosystem/network
  effects, SBC/dilution and FCF conversion.

`FINANCIALS`
- ROTCE/ROE, capital adequacy, funding, NIM/spread economics, credit quality,
  reserve adequacy and cycle sensitivity.

`COMMODITY_CYCLICAL`
- cost curve, reserve/resource quality, replacement CAPEX, inventory/curve,
  supply discipline, balance sheet and cycle-normalized earnings.

`GENERAL`
- standard implementation for businesses not requiring one of the above adapters.

Sector profiles do not change pillar weights.

## 5. Classic investment lenses

The following lenses are encoded over canonical pillars:

- **Graham** — margin of safety, downside and earnings/capital quality.
- **Buffett/Munger** — durable moat, reinvestment economics, management,
  growth runway and price paid.
- **Fisher** — long growth runway, product/customer quality, moat, management and
  industry opportunity.
- **Lynch/GARP** — growth relative to valuation with operating confirmation.
- **Greenblatt** — capital efficiency plus earnings/valuation yield logic.
- **O'Neil/CANSLIM** — current/annual earnings acceleration, new catalysts,
  supply-demand/institutional sponsorship, leadership and market condition.
- **Minervini/Superperformance** — accelerating fundamentals plus leadership,
  price/volume confirmation and disciplined downside control.
- **Porter** — industry structure and durable competitive position.
- **Damodaran** — scenario-driven growth, reinvestment, valuation and risk.
- **Druckenmiller** — strong themes, revisions/catalysts, leadership, liquidity/
  regime and asymmetric downside.
- **Howard Marks** — cycle positioning, price, downside and second-level risk.
- **Piotroski** — financial strength, profitability/cash quality, leverage and
  operating improvement.
- **Soros/reflexivity** — feedback between narrative/fundamentals, price/flows,
  catalysts and regime.
- **Mauboussin competitive-advantage period** — duration of excess returns,
  reinvestment and price paid.

These names are explanatory taxonomy only. Their lens scores are not added to the
canonical equal-pillar score.

## 5A. Academic empirical lenses

The diagnostic registry also maps well-established empirical research onto the
same pillars without creating new additive factors:

- **Fama-French value/profitability/investment** — valuation, profitability,
  capital allocation/investment discipline and balance-sheet risk.
- **Jegadeesh-Titman momentum** — sustained market leadership with operating/
  catalyst confirmation.
- **Novy-Marx gross profitability** — underlying profitability and reinvestment
  quality considered alongside growth and price paid.
- **Asness quality/value/momentum** — quality, valuation, trend and risk as a
  multi-style cross-check.
- **Post-earnings-announcement drift (PEAD)** — earnings surprise/revision,
  subsequent price confirmation and catalyst persistence.

These remain lenses over canonical pillars, not extra points.

## 5B. Portfolio theories belong to A5, not company scoring

Several important investment theories answer a different question — how to size
and combine already-reviewed opportunities — and therefore must not be added to
the company score:

- **Markowitz mean-variance**: expected return, covariance and constraints.
- **Fractional Kelly**: edge relative to uncertainty/downside, constrained by
  the project's hard MDD ceiling.
- **Black-Litterman**: equilibrium/prior plus explicitly reviewed views and
  confidence.
- **Risk budgeting / correlation control**: marginal risk, common-factor and
  theme/customer/country/FX concentration.
- **Factor-residual alpha**: separate market, size, value, momentum, sector and
  other common exposures from idiosyncratic alpha.

These are A5 portfolio-analysis candidates only and require their own OOS
validation before production use.

## 6. Existing project-native lenses

- `PROJECT_QUALITY_COMPOUNDER`
- `PROJECT_MARKET_LEADER`
- `PROJECT_EARLY_GROWTH_INFLECTION`
- `PROJECT_TURNAROUND_VALUE`
- `PROJECT_SMART_MONEY_EVENT`
- `PROJECT_REGIME_RESILIENCE`

They map the current engine's existing research philosophy onto the same pillars,
so legacy project methods can be compared without double counting.

## 7. Mapping to existing repository signals

Examples, not a new source of truth:

- industry/bottleneck: theme/sector leadership, GICS/sub-industry RS, verified
  business relationships, market leader engine, industry research.
- moat: Moat/Quality V2, `moat_quality_blueprint_score`,
  `pricing_power_score`, qualification/IP evidence.
- growth: sales/EPS/OCF/FCF growth, `growth_blueprint_score`, backlog/guidance.
- capital efficiency: ROIC/ROE, FCF margin, `capital_efficiency_score`,
  `quality_trend_score`.
- valuation: forward PE, EV/EBITDA, FCF yield, PEG,
  `valuation_blueprint_score`, sector/global peer comparisons.
- acceleration: `revision_blueprint_score`, `revision_score`,
  `actual_results_score`, event reaction and guidance.
- leadership: 20/60/120/240D RS, `oneil_leadership_score`,
  Minervini overlay, trend/breakout and volume.
- management/governance: governance overlays, dilution, capital allocation,
  buybacks and insider alignment.
- catalyst/ownership: 13F, Form4, ETF changes, event/news evidence, order wins.
- downside/regime: leverage, concentration, expected drawdown, crisis/regime
  overlays, volatility and scenario invalidation.

Existing scores remain their own surfaces. Investment Methodology V1 consumes
reviewed artifacts and does not silently reinterpret current live columns as PIT
history.

## 8. Evidence contract

Every pillar requires:

- absolute assessment 0..1;
- peer-relative assessment 0..1;
- separate confidence 0..1;
- absolute and peer rationale;
- counter-argument and invalidation conditions;
- reviewed peer group identity, rank and snapshot;
- one or more reviewed upstream artifacts available no later than the packet
  `as_of`.

The evaluator resolves the peer snapshot and each upstream artifact from the
trusted artifact store and recomputes SHA-256 before admission. A syntactically
valid hash string without matching bytes is rejected.

`STAGE_ADJUSTED` is allowed only with an explicit reason. It changes the
economic interpretation, not the weight.

## 9. Authority

Outputs are diagnostic research only:

- `historical_pit_certified=false`
- `oos_validated=false`
- `selector_eligible=false`
- `portfolio_weight_effect=0`
- no target/order/production authority

## 10. Promotion path

1. Use existing quantitative/leadership/ER filters to reduce the universe.
2. Create Methodology V1 + Moat V2 packets for roughly 20–30 serious candidates.
3. Compare absolute score, peer-relative score, style/lens dispersion, ER and downside.
4. Accumulate timestamped forward outcomes.
5. Preregister a purged walk-forward/OOS experiment testing whether any pillar
   weighting or method-consensus feature improves 1/3/6/12m excess return and MDD.
6. Only validated incremental information may enter selector weights.

This preserves the project rule: theory helps define the question; evidence and
OOS results decide whether it deserves investment authority.

# Cross-Market Gold Set V1 — Methodology/Moat/ER calibration set

[PROJECT_HANDOFF]

- Date: 2026-09-21 KST
- Base: `wscha231/r1000-quant-engine` master after Investment Methodology V1 merge
- Authority: `RESEARCH_VALIDATION_ONLY`
- Purpose: validate reproducibility, peer-set sensitivity and evidence discipline before scaling Methodology V1 + Moat V2 to the full U.S./Korea/multi-asset universe
- Inclusion is **not** a buy/hold/target/portfolio decision

## Design principles

The set is intentionally heterogeneous. It contains:
- established global leaders;
- emerging high-growth businesses;
- challenged-moat cases;
- project/backlog businesses;
- brand/ODM consumer models;
- CDMO and platform biotech;
- one weaker/emerging optical-control case;
- non-equity commodity underlyings.

The goal is not sector quota parity. The goal is to test whether the same ten
canonical pillars and Moat V2 evidence rules remain coherent across very
different economic models.

Maximum size is 30. V1 contains 30 candidates.

## Gold set

### U.S. / global listed equities
- AVGO — custom silicon + connectivity platform
- ANET — AI Ethernet/networking leader
- CRDO — high-growth interconnect
- LITE — optical components
- COHR — optical materials/components
- VRT — AI power/cooling
- ETN — electrification/power distribution
- GEV — generation/grid equipment
- NVT — AI liquid cooling + electrical infrastructure
- EME — electrical/mechanical contractor exposure to data-center buildout
- BWXT — nuclear components/defense
- CEG — nuclear generation / power-demand sensitivity

### Korea
- 000660 SK hynix — HBM/advanced memory
- 357780 Soulbrain — qualified semiconductor materials
- 058470 Leeno Industrial — precision test interface
- 095340 ISC — silicone-rubber test sockets
- 403870 HPSP — challenged former-monopoly advanced process equipment
- 267260 HD Hyundai Electric — transformer/grid bottleneck
- 298040 Hyosung Heavy Industries — EHV transformer installed base
- 034020 Doosan Enerbility — nuclear + turbine optionality
- 009540 HD Korea Shipbuilding & Offshore Engineering — high-end shipbuilding backlog/technology
- 042660 Hanwha Ocean — shipbuilding + defense optionality
- 192820 Cosmax — global beauty ODM
- 278470 APR — beauty brand/device/DTC growth
- 207940 Samsung Biologics — biologics CDMO scale
- 196170 Alteogen — drug-delivery platform/royalty economics
- 141080 LigaChem Biosciences — ADC platform optionality
- 046970 Wooriro — emerging optical small-cap control case

### Non-equity underlyings
- U3O8 uranium spot — nuclear-fuel supply bottleneck
- Copper / HG — electrification/grid metal

## Wave order

P0 packets are created first because they provide the widest calibration value:
AVGO, ANET, VRT, BWXT, SK hynix, Soulbrain, Leeno Industrial, HD Hyundai
Electric, HD KSOE, Cosmax, Samsung Biologics and Alteogen.

P1 then covers high-beta or alternative-business-model cases, followed by the P2
control case. Priority is a research sequencing label, not an investment rank.

## Required comparison

Each packet must preserve:
- current asset/issuer identity and as-of timestamps;
- reviewed global peer group and peer snapshot hash;
- ten Methodology V1 pillars, common absolute anchor and rank-derived peer percentiles;
- Moat V2 six dimensions where applicable;
- current valuation + historical/global-peer context;
- 20/60/120/240D RS and benchmark;
- growth/FCF/ROIC/revisions/guidance/backlog evidence as applicable;
- Bull/Base/Bear 12/24m bridge;
- 1/3/6/12m ER, benchmark excess return and downside;
- counter-thesis, invalidation conditions, catalysts and evidence graph.

No global ranking is claimed until coverage across U.S., Korea and multi-asset
candidates is sufficiently complete.

## Control / falsification cases

- HPSP: tests whether a once-strong monopoly narrative is correctly downgraded
  when competition/IP facts change.
- Wooriro: tests whether weak scale/limited evidence prevents a thematic optical
  narrative from receiving a high score.
- Uranium and copper: test whether the same research architecture can represent
  non-equity supply/demand economics without forcing equity metrics.
- Pre-commercial/platform biotech: tests whether stage-adjusted valuation can
  remain comparable without deleting the valuation/downside pillars.

## Authority

Gold-set packets are A3 research artifacts only. They do not write selector
scores, ER production surfaces, targets, portfolio weights or orders. Any
production weighting requires timestamped history and separate PIT/OOS promotion.

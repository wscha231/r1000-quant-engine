# Cross-Sector Leadership Rotation Report — 2026-06-28

## Purpose

This report documents the first generic leadership-rotation screen added after the AI Capex work. The goal is to verify that AlphaOps can detect future leadership outside AI, including biotech, energy, utilities, financials, industrials, materials, software, and other groups.

This is a research-only sidecar:

- no selection change
- no score change
- no target weight change
- no cash or live trading change
- no production promotion
- forward returns are audit labels only

## New Tool

`tools/run_cross_sector_leadership_rotation_screen.py`

Inputs:

- candidate or target book CSV
- existing PIT-visible fields such as sector, industry group, RS, momentum, leader tier, theme multiplier, earnings/revision scores

Outputs:

- `summary.json`
- `candidate_leaders.csv`
- `group_leadership_stats.csv`
- `report.md`

Safety fields:

- `used_forward_return_in_ranking=false`
- `forward_returns_audit_only=true`
- `production_activation_allowed=false`
- `policy_mutation_allowed=false`
- `live_trading_enabled=false`

## Why This Matters

The AI Capex layer is a specific thesis pack, not the whole leadership system. If the next rally comes from biotech, energy, financials, industrials, utilities, or materials, the system must first detect the rotation through generic leadership evidence:

- 1M/3M/6M relative strength
- sector and industry-group strength
- market leader lane score
- O'Neil leadership score
- entry quality
- earnings/revision confirmation when available

Only after the generic screen finds a durable pocket should a sector-specific thesis pack be built.

## Thesis Buckets Added

The screen classifies rows into coarse research buckets:

- `BIOTECH_PLATFORM`
- `BIOTECH_REVENUE_INFLECTION`
- `HEALTHCARE_NON_BIOTECH`
- `ENERGY_POWER_SUPPLY`
- `FINANCIAL_RATE_CYCLE`
- `INDUSTRIAL_RESHORING_CAPEX`
- `MATERIALS_COMMODITY`
- `SOFTWARE_PLATFORM`
- `AI_CAPEX_SUPPLY_CHAIN`
- `CONSUMER_DISCRETIONARY`
- `OTHER_CROSS_SECTOR_LEADER`

These buckets are taxonomy labels only. They are not buy lists.

## Clean7Y Artifact Check

Applied to:

- `artifacts/28074476465/outputs/alphaops_vnext/official_concentrated_target_book.csv`
- `artifacts/28074476465/outputs/alphaops_vnext/official_main_target_book.csv`

### Concentrated

- rows: 412
- leadership candidates: 125
- status: `screen_passed`
- forward label used for audit: `period_forward_return`

Top OOS groups by mean audit label:

| group | candidates | mean audit label | positive rate |
|---|---:|---:|---:|
| Tech Hardware & Storage | 8 | 0.2794 | 87.5% |
| AI Capex Supply Chain | 12 | 0.2206 | 75.0% |
| Information Technology | 26 | 0.1673 | 80.8% |
| Communication Equipment | 8 | 0.1422 | 87.5% |
| Software Infrastructure | 5 | 0.1304 | 100.0% |
| Industrials | 6 | 0.1109 | 83.3% |
| Health Care | 4 | 0.0592 | 100.0% |

Biotech detail:

- full-period Biotechnology candidate mean: -0.0168, positive rate 46.7%
- OOS Biotechnology candidate mean: 0.0592, positive rate 100.0%

Interpretation: the screen can detect biotech leadership when it appears, but the full-period evidence is not strong enough to justify a biotech policy hook without catalyst-level PIT data.

### Main

- rows: 1197
- leadership candidates: 360
- status: `screen_passed`
- forward label used for audit: `period_forward_return`

Top OOS groups by mean audit label:

| group | candidates | mean audit label | positive rate |
|---|---:|---:|---:|
| Tech Hardware & Storage | 10 | 0.2738 | 90.0% |
| Communication Equipment | 19 | 0.2027 | 94.7% |
| AI Capex Supply Chain | 23 | 0.1975 | 69.6% |
| Information Technology | 56 | 0.1704 | 76.8% |
| Semiconductors | 13 | 0.1389 | 53.8% |
| Utilities | 7 | 0.1016 | 85.7% |
| Software Infrastructure | 11 | 0.1214 | 72.7% |

Biotech detail:

- full-period Biotechnology candidate mean: -0.0010, positive rate 47.4%
- OOS Biotechnology candidate mean: 0.0356, positive rate 75.0%

Interpretation: biotech was detectable in the recent OOS sample, but the full-period edge is thin. It should be watched, not promoted.

## Biotech-Specific Next Requirements

For biotech, generic RS is not enough. A real biotech leadership pack must add PIT-visible catalyst and balance-sheet evidence:

- trial phase and primary endpoint calendar
- FDA/PDUFA/advisory committee dates, with `available_from`
- approval/commercialization status
- revenue inflection versus pre-revenue binary risk
- cash runway and dilution risk
- trial readout failure risk
- acquisition rumor exclusion unless sourced with `available_from`

Until those fields exist, biotech can be detected as a rotation pocket, but not safely promoted as a policy tilt.

## Acceptance Discipline

This screen can justify only the next research step. It cannot justify fullrun or policy activation.

Before any default-OFF policy hook:

1. candidate count must be sufficient
2. full-period direction must be positive
3. OOS direction must not collapse
4. result must not be one ticker or one era
5. sector-specific PIT thesis data must exist
6. broker-ledger A/B must pass after a cheap screen

Production remains blocked unless the usual evidence gates pass, including PIT universe membership.


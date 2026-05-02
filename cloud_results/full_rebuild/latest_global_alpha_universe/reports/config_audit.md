# AlphaOps Config Audit

- Status: block
- Generated UTC: 2026-05-02T13:48:18Z

## Findings

- [block] active_auto_feature_gates: Active auto feature gates exist; confirm challenger promotion before production.
- [info] main_target_n_broad: Main mandate target_n is broad; target-N compression should be A/B tested, not changed blindly.
- [warn] concentrated_single_name_uncapped: Concentrated max single-name weight is 100%; declare sleeve-level cap before production orchestration.

## Key Defaults

- Backtest years: 8
- Cost per side bps: 25.0
- Main mandate target N: 20
- Concentrated max single name weight: 1.0

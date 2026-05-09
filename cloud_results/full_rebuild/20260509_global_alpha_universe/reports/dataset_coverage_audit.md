# Dataset Coverage Audit

- latest run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored latest rows: 734
- latest scored date: 2026-05-08
- historical candidate rows: 46733
- historical months: 84
- historical candidate last date: 2026-03-31

## Effective Market Cap Coverage

- `latest_scored` effective cap numeric=100.0%, inputs=`market_cap_live,mktcap`
- `historical_candidate_book` effective cap numeric=100.0%, inputs=`market_cap_live,mktcap`

## Largest Coverage Gaps

- `historical_candidate_book.market_cap_live` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.gross_margins` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.operating_margins` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.revenue_growth_final` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.op_income_growth_yoy` numeric=5.2%, nonzero=5.2%
- `historical_candidate_book.ocf_growth_yoy` numeric=5.9%, nonzero=5.9%
- `historical_candidate_book.roe_proxy` numeric=44.9%, nonzero=44.9%
- `historical_candidate_book.gross_profit_ttm` numeric=45.0%, nonzero=45.0%
- `historical_candidate_book.capex_ttm` numeric=47.1%, nonzero=46.9%
- `historical_candidate_book.ocf_ttm` numeric=56.5%, nonzero=56.5%
- `historical_candidate_book.op_income_ttm` numeric=56.8%, nonzero=56.8%
- `historical_candidate_book.revenues_ttm` numeric=57.7%, nonzero=57.7%

## Missing Audit Columns

- `historical_candidate_book.r_12m`
- `historical_candidate_book.r_6m`
- `latest_scored.eps_revision_proxy`
- `latest_scored.revision_score`

## Watchlist Gaps

- `AMAT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=5.489289650419185
- `AMD`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=72; sleeve=`core_compounder`; score=4.141259894659922
- `ANET`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=53; sleeve=`core_compounder`; score=3.734547356834623
- `ARM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=5.596683254976173
- `ASML`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.307140508600201
- `AVGO`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=4.887565920105388
- `CIEN`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`future_winner`; score=4.85440795048646
- `COHR`: selection_gate_or_rank_rejected; latest=True; hist_months=21; sleeve=`unassigned`; score=4.566339636508105
- `DELL`: historical_only_not_current_latest_universe; latest=False; hist_months=8; sleeve=``; score=None
- `GEV`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=9; sleeve=`core_compounder`; score=5.875488864405028
- `GLW`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=10; sleeve=`future_winner`; score=6.45342093023648
- `GOOGL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=6.279080014512887
- `HPE`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`early_scout`; score=3.477003122894786
- `INTC`: historical_only_not_current_latest_universe; latest=False; hist_months=64; sleeve=``; score=None
- `KLAC`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=4.658566362068823
- `LITE`: selection_gate_or_rank_rejected; latest=True; hist_months=72; sleeve=`unassigned`; score=5.359286567884744
- `LRCX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=6.686915360375868
- `MRVL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=49; sleeve=`future_winner`; score=5.7524021415116575
- `MU`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=4.630066411188046
- `NVDA`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=65; sleeve=`core_compounder`; score=4.8965909460740615
- `OKLO`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `PLTR`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=27; sleeve=`core_compounder`; score=6.283509507482637
- `QCOM`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=5.063736632668476
- `SMCI`: historical_only_not_current_latest_universe; latest=False; hist_months=8; sleeve=``; score=None
- `SMR`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `SNDK`: selection_gate_or_rank_rejected; latest=True; hist_months=2; sleeve=`unassigned`; score=2.787856993014925
- `STX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=5.17295584112799
- `TSM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=5.288359937161943
- `VRT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=48; sleeve=`core_compounder`; score=5.822232702710207
- `WDC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=38; sleeve=`future_winner`; score=5.465381537552259
- `WMT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=23; sleeve=`core_compounder`; score=4.379099167807363

## Files

- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit.json`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_coverage.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_watchlist.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_distributions.csv`

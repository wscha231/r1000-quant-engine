#!/usr/bin/env bash
set -e
set -o pipefail
mkdir -p outputs/replay_integrity
if [ "$PORTFOLIO_POLICY" = "alphaops_vnext_production" ]; then
  cp outputs/alphaops_vnext/official_main_target_book.csv outputs/replay_integrity/source_vnext_official_main_target_book.csv 2>/dev/null || true
  cp outputs/alphaops_vnext/official_concentrated_target_book.csv outputs/replay_integrity/source_vnext_official_concentrated_target_book.csv 2>/dev/null || true
fi
python tools/build_operating_target_books.py --latest-run outputs --price-cache cache_prices --output-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/operating_target_books.log
if [ "$PORTFOLIO_POLICY" = "alphaops_vnext_production" ]; then
  BASE_CANDIDATE_BOOK="outputs/reports/candidate_replay_book.csv"
  ENRICHED_CANDIDATE_BOOK="outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv"
  if [ -s "$BASE_CANDIDATE_BOOK" ] || [ -s "$ENRICHED_CANDIDATE_BOOK" ]; then
    if [ -s "$ENRICHED_CANDIDATE_BOOK" ]; then
      ALPHAOPS_CANDIDATE_BOOK="$ENRICHED_CANDIDATE_BOOK"
      echo "[replay] using restored enriched candidate book for vNext: $ALPHAOPS_CANDIDATE_BOOK"
    else
      ALPHAOPS_CANDIDATE_BOOK="$BASE_CANDIDATE_BOOK"
      echo "[replay] using base candidate book for vNext: $ALPHAOPS_CANDIDATE_BOOK"
      if [ -s data_pit/sec/form4_transactions.parquet ] || [ -s data_pit/sec/institutional_13f_holdings.parquet ] || [ -s data_pit/etf_holdings/etf_holdings.parquet ]; then
        python tools/run_sec_enriched_candidate_replay.py --candidate-book "$ALPHAOPS_CANDIDATE_BOOK" --output-dir outputs/sec_enriched_candidate_replay 2>&1 | tee outputs/full_rebuild_logs/sec_enriched_candidate_replay_for_vnext.log || true
        if [ -s "$ENRICHED_CANDIDATE_BOOK" ]; then
          ALPHAOPS_CANDIDATE_BOOK="$ENRICHED_CANDIDATE_BOOK"
          echo "[replay] built enriched candidate book for vNext: $ALPHAOPS_CANDIDATE_BOOK"
        else
          echo "[replay] enriched candidate book unavailable for vNext; using base candidate book"
        fi
      else
        echo "[replay] SEC/ETF PIT stores unavailable; using base candidate book for vNext"
      fi
    fi
    python tools/run_alphaops_vnext_policy_replay.py --latest-run outputs --candidate-book "$ALPHAOPS_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/alphaops_vnext --portfolio-kind both --main-target-n 15 --concentrated-target-n 5 --production-output-mode replace_operating --skip-broker-replay --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/alphaops_vnext_policy_replay.log
  elif [ -s outputs/replay_integrity/source_vnext_official_main_target_book.csv ] && [ -s outputs/replay_integrity/source_vnext_official_concentrated_target_book.csv ]; then
    echo "[replay] candidate_replay_book missing; restoring archived vNext official operating target books" | tee outputs/full_rebuild_logs/alphaops_vnext_policy_replay.log
    cp outputs/replay_integrity/source_vnext_official_main_target_book.csv outputs/reports/operating_main_target_book.csv
    cp outputs/replay_integrity/source_vnext_official_concentrated_target_book.csv outputs/reports/operating_concentrated_target_book.csv
  else
    echo "[replay] ERROR: alphaops_vnext_production requires candidate_replay_book or archived official vNext target books" | tee outputs/full_rebuild_logs/alphaops_vnext_policy_replay.log
    exit 2
  fi
fi
python tools/archive_target_snapshots.py --latest-run outputs --price-cache cache_prices --output-dir outputs/target_snapshots 2>&1 | tee outputs/full_rebuild_logs/target_snapshot_archive.log
python tools/run_position_risk_weekly_validation.py --holdings outputs/reports/main_monthly_weights.csv --period-map outputs/reports/regime_by_month.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/position_risk_weekly_validation/main 2>&1 | tee outputs/full_rebuild_logs/position_risk_weekly_validation_main.log
if [ -s outputs/main_v2_backtest/monthly_holdings.csv ]; then
  python tools/run_position_risk_weekly_validation.py --holdings outputs/main_v2_backtest/monthly_holdings.csv --period-map outputs/reports/regime_by_month.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/position_risk_weekly_validation/main_v2 2>&1 | tee outputs/full_rebuild_logs/position_risk_weekly_validation_main_v2.log || true
fi
python tools/run_position_risk_weekly_validation.py --holdings outputs/reports/concentrated_strategy_holdings.csv --period-map outputs/reports/concentrated_strategy_monthly.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/position_risk_weekly_validation/concentrated 2>&1 | tee outputs/full_rebuild_logs/position_risk_weekly_validation_concentrated.log || true
python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_replay/main --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/broker_ledger_replay_main.log
python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_replay/concentrated --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/broker_ledger_replay_concentrated.log
if [ -s outputs/reports/main_monthly_weights.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/main_monthly_weights.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/legacy_monthly_broker_replay/main --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/legacy_monthly_broker_replay_main.log || true
fi
if [ -s outputs/reports/concentrated_strategy_holdings.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/concentrated_strategy_holdings.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/legacy_monthly_broker_replay/concentrated --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/legacy_monthly_broker_replay_concentrated.log || true
fi
python tools/build_event_target_books.py --latest-run outputs --price-cache cache_prices --output-dir outputs/event_target_books --reports-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/event_target_books.log || true
if [ -s outputs/reports/event_main_target_book.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/event_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/event_broker_replay/main --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/event_broker_replay_main.log || true
fi
if [ -s outputs/reports/event_concentrated_target_book.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/event_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/event_broker_replay/concentrated --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/event_broker_replay_concentrated.log || true
fi
python tools/build_weekly_leader_target_books.py --latest-run outputs --price-cache cache_prices --output-dir outputs/weekly_leader_snapshots --reports-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/weekly_leader_target_books.log || true
if [ -s outputs/reports/weekly_leader_main_target_book.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/weekly_leader_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/weekly_leader_broker_replay/main --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/weekly_leader_broker_replay_main.log || true
fi
if [ -s outputs/reports/weekly_leader_concentrated_target_book.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/weekly_leader_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/weekly_leader_broker_replay/concentrated --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/weekly_leader_broker_replay_concentrated.log || true
fi
if [ -s outputs/reports/operating_main_target_book.csv ]; then
  python tools/run_cost_sensitivity_sidecar.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/cost_sensitivity/main --cost-bps-list 25 50 75 100 --baseline-cost-bps 25 2>&1 | tee outputs/full_rebuild_logs/cost_sensitivity_main.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book.csv ]; then
  python tools/run_cost_sensitivity_sidecar.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/cost_sensitivity/concentrated --cost-bps-list 25 50 75 100 --baseline-cost-bps 25 2>&1 | tee outputs/full_rebuild_logs/cost_sensitivity_concentrated.log || true
fi
rm -rf outputs/execution_cost_capacity/main
if [ -s outputs/reports/operating_main_target_book.csv ]; then
  python tools/run_execution_cost_capacity_sidecar.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/execution_cost_capacity/main --base-cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" --capacity-participation-rates 0.001 0.005 0.01 2>&1 | tee outputs/full_rebuild_logs/execution_cost_capacity_main.log || true
fi
rm -rf outputs/execution_cost_capacity/concentrated
if [ -s outputs/reports/operating_concentrated_target_book.csv ]; then
  python tools/run_execution_cost_capacity_sidecar.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/execution_cost_capacity/concentrated --base-cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" --capacity-participation-rates 0.001 0.005 0.01 2>&1 | tee outputs/full_rebuild_logs/execution_cost_capacity_concentrated.log || true
fi
if [ -s outputs/reports/operating_main_target_book.csv ]; then
  python tools/run_neutral_regime_churn_filter.py --input-book outputs/reports/operating_main_target_book.csv --output-book outputs/reports/operating_main_target_book_churn_filtered.csv --diagnostics outputs/churn_filter/main/diagnostics.json --swap-threshold 2 --window-months 6 --target-regimes neutral 2>&1 | tee outputs/full_rebuild_logs/churn_filter_main.log || true
fi
if [ -s outputs/reports/operating_main_target_book_churn_filtered.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book_churn_filtered.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/churn_filtered_broker_replay/main --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/churn_filtered_broker_replay_main.log || true
fi
if [ -s outputs/reports/operating_main_target_book.csv ]; then
  python tools/run_macro_circuit_breaker_filter.py --input-book outputs/reports/operating_main_target_book.csv --output-book outputs/reports/operating_main_target_book_macro_filtered.csv --diagnostics outputs/macro_circuit_filter/main/diagnostics.json --price-cache cache_prices --ma-window 200 --confirm-days 3 --halve-factor 0.5 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_filter_main.log || true
fi
if [ -s outputs/reports/operating_main_target_book_macro_filtered.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book_macro_filtered.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/macro_circuit_broker_replay/main --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_broker_replay_main.log || true
fi
if [ -s outputs/reports/operating_main_target_book.csv ]; then
  python tools/run_macro_circuit_breaker_filter.py --input-book outputs/reports/operating_main_target_book.csv --output-book outputs/reports/operating_main_target_book_macro_factor25.csv --diagnostics outputs/macro_circuit_filter/main_factor25/diagnostics.json --price-cache cache_prices --ma-window 200 --confirm-days 3 --halve-factor 0.25 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_filter_main_factor25.log || true
  python tools/run_macro_circuit_breaker_filter.py --input-book outputs/reports/operating_main_target_book.csv --output-book outputs/reports/operating_main_target_book_macro_factor00.csv --diagnostics outputs/macro_circuit_filter/main_factor00/diagnostics.json --price-cache cache_prices --ma-window 200 --confirm-days 3 --halve-factor 0.00 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_filter_main_factor00.log || true
fi
if [ -s outputs/reports/operating_main_target_book_macro_factor25.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book_macro_factor25.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/macro_circuit_broker_replay/main_factor25 --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_broker_replay_main_factor25.log || true
fi
if [ -s outputs/reports/operating_main_target_book_macro_factor00.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book_macro_factor00.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/macro_circuit_broker_replay/main_factor00 --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_broker_replay_main_factor00.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book.csv ]; then
  python tools/run_macro_circuit_breaker_filter.py --input-book outputs/reports/operating_concentrated_target_book.csv --output-book outputs/reports/operating_concentrated_target_book_macro_filtered.csv --diagnostics outputs/macro_circuit_filter/concentrated/diagnostics.json --price-cache cache_prices --ma-window 200 --confirm-days 3 --halve-factor 0.5 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_filter_concentrated.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book_macro_filtered.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_concentrated_target_book_macro_filtered.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/macro_circuit_broker_replay/concentrated --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_broker_replay_concentrated.log || true
fi
if [ -s outputs/reports/operating_main_target_book.csv ]; then
  python tools/run_regime_capacity_filter.py --input-book outputs/reports/operating_main_target_book.csv --output-book outputs/reports/operating_main_target_book_regime_capacity_filtered.csv --diagnostics outputs/regime_capacity_filter/main/diagnostics.json --multipliers "bear=0.5,deep_bear=0.25" 2>&1 | tee outputs/full_rebuild_logs/regime_capacity_filter_main.log || true
fi
if [ -s outputs/reports/operating_main_target_book_regime_capacity_filtered.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book_regime_capacity_filtered.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/regime_capacity_broker_replay/main --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/regime_capacity_broker_replay_main.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book.csv ]; then
  python tools/run_regime_capacity_filter.py --input-book outputs/reports/operating_concentrated_target_book.csv --output-book outputs/reports/operating_concentrated_target_book_regime_capacity_filtered.csv --diagnostics outputs/regime_capacity_filter/concentrated/diagnostics.json --multipliers "bear=0.5,deep_bear=0.25,neutral=0.85" --regime-source-book outputs/reports/operating_main_target_book.csv 2>&1 | tee outputs/full_rebuild_logs/regime_capacity_filter_concentrated.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book_regime_capacity_filtered.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_concentrated_target_book_regime_capacity_filtered.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/regime_capacity_broker_replay/concentrated --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/regime_capacity_broker_replay_concentrated.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book.csv ]; then
  python tools/run_regime_capacity_filter.py --input-book outputs/reports/operating_concentrated_target_book.csv --output-book outputs/reports/operating_concentrated_target_book_regime_capacity_neutral90.csv --diagnostics outputs/regime_capacity_filter/concentrated_neutral90/diagnostics.json --multipliers "bear=0.5,deep_bear=0.25,neutral=0.90" --regime-source-book outputs/reports/operating_main_target_book.csv 2>&1 | tee outputs/full_rebuild_logs/regime_capacity_filter_concentrated_neutral90.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book_regime_capacity_neutral90.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_concentrated_target_book_regime_capacity_neutral90.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/regime_capacity_broker_replay/concentrated_neutral90 --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/regime_capacity_broker_replay_concentrated_neutral90.log || true
fi
python tools/run_trade_attribution_analysis.py --latest-run outputs --output-dir outputs/trade_attribution 2>&1 | tee outputs/full_rebuild_logs/trade_attribution_analysis.log || true
python tools/run_broker_position_risk_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_position_risk_replay/main --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/broker_position_risk_replay_main.log || true
python tools/run_broker_position_risk_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_position_risk_replay/concentrated --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/broker_position_risk_replay_concentrated.log || true
python tools/run_broker_position_risk_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_parabolic_risk_replay/main --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" --hard-stop -9 --relative-trim-threshold -9 --relative-exit-threshold -9 --disable-distribution-exit --candidate-id main_broker_parabolic_risk_replay --trailing-activation 0.50 --trailing-stop -0.20 2>&1 | tee outputs/full_rebuild_logs/broker_parabolic_risk_replay_main.log || true
python tools/run_broker_position_risk_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_parabolic_risk_replay/concentrated --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" --hard-stop -9 --relative-trim-threshold -9 --relative-exit-threshold -9 --disable-distribution-exit --candidate-id concentrated_broker_parabolic_risk_replay --trailing-activation 0.50 --trailing-stop -0.20 2>&1 | tee outputs/full_rebuild_logs/broker_parabolic_risk_replay_concentrated.log || true
python tools/run_broker_execution_policy_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_execution_policy_replay/main --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/broker_execution_policy_replay_main.log || true
python tools/run_broker_execution_policy_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_execution_policy_replay/concentrated --fill-mode next_close --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" --buy-band 0.04 --sell-band 0.06 --winner-overweight-band 0.15 --new-entry-scale 0.85 2>&1 | tee outputs/full_rebuild_logs/broker_execution_policy_replay_concentrated.log || true
python tools/run_operating_event_backtest.py --latest-run outputs --output-dir outputs/operating_event_backtest 2>&1 | tee outputs/full_rebuild_logs/operating_event_backtest.log || true
python tools/run_broker_gap_attribution.py --latest-run outputs --output-dir outputs/broker_gap_attribution 2>&1 | tee outputs/full_rebuild_logs/broker_gap_attribution.log || true
python tools/run_broker_trade_journal.py --latest-run outputs --output-dir outputs/broker_trade_journal 2>&1 | tee outputs/full_rebuild_logs/broker_trade_journal.log || true
python tools/run_account_order_preview.py --account-state outputs/broker_replay/main/account_state_latest.json --target outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/account_ledger_preview/main --cost-bps "$COST_BPS" --security-lifecycle-events data_static/run287_exact_packet/security_lifecycle_events.csv --decision-time-utc "$DECISION_TIME_UTC" 2>&1 | tee outputs/full_rebuild_logs/account_order_preview_main.log
python tools/run_account_order_preview.py --account-state outputs/broker_replay/concentrated/account_state_latest.json --target outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/account_ledger_preview/concentrated --cost-bps "$COST_BPS" --security-lifecycle-events data_static/run287_exact_packet/security_lifecycle_events.csv --decision-time-utc "$DECISION_TIME_UTC" 2>&1 | tee outputs/full_rebuild_logs/account_order_preview_concentrated.log
python tools/run_live_trading_safety_audit.py --latest-run outputs --output-dir outputs/live_trading_safety 2>&1 | tee outputs/full_rebuild_logs/live_trading_safety_audit.log || true
python tools/run_live_trading_risk_controls.py --latest-run outputs --price-cache cache_prices --output-dir outputs/live_trading_risk_controls --account-mode simulated 2>&1 | tee outputs/full_rebuild_logs/live_trading_risk_controls.log || true
python tools/run_weekly_evaluation.py --latest-run outputs --price-cache cache_prices --output-dir outputs/weekly_evaluation --stale-days-threshold 10 2>&1 | tee outputs/full_rebuild_logs/weekly_evaluation.log || true
python tools/run_theme_leadership_tape.py --scored outputs/scored_latest.csv --price-cache cache_prices --output-dir outputs/theme_leadership_tape 2>&1 | tee outputs/full_rebuild_logs/theme_leadership_tape.log || true
python tools/run_theme_concentration_challenger.py --latest-run outputs --output-dir outputs/theme_concentration_challenger --top-n "$THEME_TOP_N" --single-name-cap "$THEME_SINGLE_NAME_CAP" --cost-bps "$THEME_COST_BPS" 2>&1 | tee outputs/full_rebuild_logs/theme_concentration_challenger.log || true
if [ -s outputs/reports/candidate_replay_book.csv ]; then
  python tools/run_concentrated_policy_replay.py --latest-run outputs --output-dir outputs/concentrated_policy_replay --price-cache cache_prices --run-broker-replay --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/concentrated_policy_replay.log || true
else
  echo "[replay] skipping concentrated_policy_replay; missing outputs/reports/candidate_replay_book.csv" | tee outputs/full_rebuild_logs/concentrated_policy_replay.log
fi
python tools/run_portfolio_goal_search.py --latest-run outputs 2>&1 | tee outputs/full_rebuild_logs/portfolio_goal_search.log || true
python tools/run_account_evaluation.py --latest-run outputs --output-dir outputs/account_evaluation 2>&1 | tee outputs/full_rebuild_logs/account_evaluation.log || true
python tools/validate_target_book_cash_contract.py --latest-run outputs --output-dir outputs/cash_contract 2>&1 | tee outputs/full_rebuild_logs/cash_contract.log || true
if [ -n "${SOURCE_ARTIFACT_DIR:-}" ] && [ -d "${SOURCE_ARTIFACT_DIR:-}" ]; then
  python tools/run_fast_full_drift_audit.py --full-run "$SOURCE_ARTIFACT_DIR" --fast-run outputs --output-dir outputs/fast_full_drift_audit 2>&1 | tee outputs/full_rebuild_logs/fast_full_drift_audit.log || true
else
  echo "[fast-full-drift] source artifact dir unavailable; skipping paired audit" | tee outputs/full_rebuild_logs/fast_full_drift_audit.log
fi
python tools/run_metric_hygiene_report.py --latest-run outputs --output-dir outputs/metric_hygiene 2>&1 | tee outputs/full_rebuild_logs/metric_hygiene_report.log || true
python tools/run_monster_recommendation_bridge.py --latest-run outputs --output-dir outputs/monster_recommendations 2>&1 | tee outputs/full_rebuild_logs/monster_recommendations.log || true
python tools/run_operating_snapshot.py --latest-run outputs --output-dir outputs/operating_snapshot 2>&1 | tee outputs/full_rebuild_logs/operating_snapshot.log || true
python tools/run_user_portfolio_reports.py --latest-run outputs --price-cache cache_prices --output-dir outputs/user_portfolio_reports 2>&1 | tee outputs/full_rebuild_logs/user_portfolio_reports.log || true
python tools/run_position_cleanup_review.py --latest-run outputs --output-dir outputs/operator_review 2>&1 | tee outputs/full_rebuild_logs/position_cleanup_review.log || true
python tools/audit_data_readiness.py --latest-run outputs --price-cache cache_prices --output-dir outputs/data_readiness 2>&1 | tee outputs/full_rebuild_logs/data_readiness.log || true
python tools/run_dataset_coverage_audit.py --latest-run outputs --output-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/dataset_coverage_audit.log || true
python tools/run_portfolio_system_guard.py --latest-run outputs --output-dir outputs/portfolio_system_guard 2>&1 | tee outputs/full_rebuild_logs/portfolio_system_guard.log || true
BASELINE_RUN_ID="${SOURCE_RUN_ID}_${GITHUB_RUN_ID}"
python tools/create_healthy_baseline_lock.py --latest-run outputs --output-dir outputs/baseline_lock --run-id "$BASELINE_RUN_ID" --branch "$GITHUB_REF_NAME" --head-sha "$GITHUB_SHA" --artifact-id "$SOURCE_RUN_ID" 2>&1 | tee outputs/full_rebuild_logs/baseline_lock.log || true
SIDECAR_CANDIDATE_BOOK="outputs/reports/candidate_replay_book.csv"
if [ "$RUN_EXTENDED_RESEARCH_SIDECARS" = "true" ]; then
  python tools/run_sec_enriched_candidate_replay.py --candidate-book "$SIDECAR_CANDIDATE_BOOK" --output-dir outputs/sec_enriched_candidate_replay 2>&1 | tee outputs/full_rebuild_logs/sec_enriched_candidate_replay.log || true
  if [ -s outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv ]; then
    SIDECAR_CANDIDATE_BOOK="outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv"
    echo "[replay] using enriched candidate book: $SIDECAR_CANDIDATE_BOOK"
  else
    echo "[replay] enriched candidate book unavailable; using base candidate book"
  fi
  python tools/run_superperformance_trader_replay.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/superperformance_trader_replay --cost-bps "$COST_BPS" --max-fill-lag-days "$MAX_FILL_LAG_DAYS" 2>&1 | tee outputs/full_rebuild_logs/superperformance_trader_replay.log || true
  python tools/run_long_crisis_dataset_builder.py 2>&1 | tee outputs/full_rebuild_logs/long_crisis_dataset_builder.log || true
  python tools/run_long_crisis_signal_learning.py 2>&1 | tee outputs/full_rebuild_logs/long_crisis_signal_learning.log || true
  python tools/run_long_crisis_threshold_search.py 2>&1 | tee outputs/full_rebuild_logs/long_crisis_threshold_search.log || true
  python tools/run_integrated_theme_leader_crisis_replay.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/integrated_theme_leader_crisis_replay --baseline-lock outputs/baseline_lock/active_baseline.json --portfolio-kind both --cost-bps "$COST_BPS" --artifact-id "$SOURCE_RUN_ID" 2>&1 | tee outputs/full_rebuild_logs/integrated_theme_leader_crisis_replay.log || true
  python tools/run_strategy_logic_ledger.py --latest-run outputs --integrated-output outputs/integrated_theme_leader_crisis_replay --output-dir outputs/strategy_logic_ledger --run-id "$GITHUB_RUN_ID" --commit-sha "$GITHUB_SHA" --artifact-id "$SOURCE_RUN_ID" 2>&1 | tee outputs/full_rebuild_logs/strategy_logic_ledger.log || true
else
  echo "[replay] skipping extended research sidecars; set run_extended_research_sidecars=true to include superperformance and integrated theme/leader/crisis replay"
  rm -rf outputs/superperformance_trader_replay outputs/integrated_theme_leader_crisis_replay outputs/strategy_logic_ledger
fi
python tools/run_patch_application_manifest.py --latest-run outputs --output outputs/patch_application_manifest.json --run-id "$GITHUB_RUN_ID" --run-attempt "$GITHUB_RUN_ATTEMPT" --head-sha "$GITHUB_SHA" --branch "$GITHUB_REF_NAME" --artifact-id "$SOURCE_RUN_ID" --sidecar-profile "alphaops_replay_sidecars" --artifact-profile "replay_sidecar" --gdrive-sync-mode "research" --portfolio-policy "$PORTFOLIO_POLICY" 2>&1 | tee outputs/full_rebuild_logs/patch_application_manifest.log || true
python tools/run_user_current_report.py --latest-run outputs --price-cache cache_prices --output-dir outputs/user_current --strict 2>&1 | tee outputs/full_rebuild_logs/user_current_report.log || true
python tools/run_patch_application_manifest.py --latest-run outputs --output outputs/patch_application_manifest.json --run-id "$GITHUB_RUN_ID" --run-attempt "$GITHUB_RUN_ATTEMPT" --head-sha "$GITHUB_SHA" --branch "$GITHUB_REF_NAME" --artifact-id "$SOURCE_RUN_ID" --sidecar-profile "alphaops_replay_sidecars" --artifact-profile "replay_sidecar" --gdrive-sync-mode "research" --portfolio-policy "$PORTFOLIO_POLICY" 2>&1 | tee outputs/full_rebuild_logs/patch_application_manifest_final.log || true

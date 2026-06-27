#!/usr/bin/env python3
"""Run full rebuild sidecars outside the GitHub workflow YAML.

The GitHub Actions parser rejects very large `run: |` blocks once expression
scanning crosses its limit. Keeping the long sidecar command list here lets the
workflow expose small profile inputs while this tool owns generation behavior.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


SHELL_SCRIPT = r"""set -e
set -o pipefail
SIDECAR_PROFILE="${SIDECAR_PROFILE:-research_full}"
ARTIFACT_PROFILE="${ARTIFACT_PROFILE:-unknown}"
GDRIVE_SYNC_MODE="${GDRIVE_SYNC_MODE:-unknown}"
PORTFOLIO_POLICY="${PORTFOLIO_POLICY:-alphaops_vnext_production}"
APPROVED_TARGET_POLICY_PATH="${APPROVED_TARGET_POLICY_PATH:-outputs/promotion_review/approved_target_policy.json}"
UNIVERSE_MODE="${UNIVERSE_MODE:-global_alpha_universe}"
BACKTEST_YEARS="${BACKTEST_YEARS:-}"
echo "[sidecar] profile=${SIDECAR_PROFILE} artifact_profile=${ARTIFACT_PROFILE} gdrive_sync_mode=${GDRIVE_SYNC_MODE} portfolio_policy=${PORTFOLIO_POLICY} universe_mode=${UNIVERSE_MODE} backtest_years=${BACKTEST_YEARS}"

run_patch_manifest() {
  local run_id="${GITHUB_RUN_ID:-local}"
  python tools/run_patch_application_manifest.py --latest-run outputs --output outputs/patch_application_manifest.json --run-id "$run_id" --head-sha "${GITHUB_SHA:-}" --branch "${GITHUB_REF_NAME:-}" --artifact-id "$run_id" --sidecar-profile "$SIDECAR_PROFILE" --artifact-profile "$ARTIFACT_PROFILE" --gdrive-sync-mode "$GDRIVE_SYNC_MODE" --portfolio-policy "$PORTFOLIO_POLICY" --approved-target-policy-path "$APPROVED_TARGET_POLICY_PATH" 2>&1 | tee outputs/full_rebuild_logs/patch_application_manifest.log || true
}

run_sidecar_promotion_hook() {
  echo "[sidecar-promotion] pre_broker_replay_target_override_hook mode=${PORTFOLIO_POLICY}"
  local hook_mode="$PORTFOLIO_POLICY"
  if [ "$hook_mode" = "alphaops_vnext_production" ]; then
    echo "[sidecar-promotion] alphaops_vnext_production already replaced operating target books; skipping shadow bridge"
  elif [ "$hook_mode" = "integrated_shadow" ]; then
    python tools/run_sidecar_promotion_bridge.py --mode integrated_shadow --latest-run outputs --price-cache cache_prices --output-root outputs --approved-policy "$APPROVED_TARGET_POLICY_PATH" --source-integrated-dir outputs/integrated_theme_leader_crisis_replay 2>&1 | tee outputs/full_rebuild_logs/sidecar_promotion_bridge.log || true
  elif [ "$hook_mode" = "market_leader_shadow" ]; then
    echo "[sidecar-promotion] writing outputs/operator_review/projected_holdings_after_market_leader_target.csv"
    python tools/run_sidecar_promotion_bridge.py --mode market_leader_shadow --latest-run outputs --price-cache cache_prices --output-root outputs --approved-policy "$APPROVED_TARGET_POLICY_PATH" --source-integrated-dir outputs/integrated_theme_leader_crisis_replay 2>&1 | tee outputs/full_rebuild_logs/sidecar_promotion_bridge.log || true
  elif [ "$hook_mode" = "approved_integrated" ]; then
    python tools/run_sidecar_promotion_bridge.py --mode approved_integrated --latest-run outputs --price-cache cache_prices --output-root outputs --approved-policy "$APPROVED_TARGET_POLICY_PATH" --source-integrated-dir outputs/integrated_theme_leader_crisis_replay 2>&1 | tee outputs/full_rebuild_logs/sidecar_promotion_bridge.log
  else
    python tools/run_sidecar_promotion_bridge.py --mode production_baseline --latest-run outputs --price-cache cache_prices --output-root outputs --approved-policy "$APPROVED_TARGET_POLICY_PATH" --source-integrated-dir outputs/integrated_theme_leader_crisis_replay 2>&1 | tee outputs/full_rebuild_logs/sidecar_promotion_bridge.log || true
  fi
}

build_long_crisis_inputs() {
  echo "[long-crisis] building inputs before integrated replay"
  python tools/run_long_crisis_dataset_builder.py 2>&1 | tee outputs/full_rebuild_logs/long_crisis_dataset_builder.log || true
  python tools/run_long_crisis_signal_learning.py 2>&1 | tee outputs/full_rebuild_logs/long_crisis_signal_learning.log || true
  python tools/run_long_crisis_threshold_search.py 2>&1 | tee outputs/full_rebuild_logs/long_crisis_threshold_search.log || true
}

SIDECAR_CANDIDATE_BOOK="outputs/reports/candidate_replay_book.csv"

# Walk-forward Top-7 manager discovery signals, materialised before SEC
# enrichment so the TOP7_MANAGER_DISCOVERY lane has data to score. The follow
# study (6-month-rolling PIT cohorts) is also invoked later in the sidecar flow;
# we run it here only if its output parquet is missing so there is no double
# work, then aggregate per (rebalance_date, ticker).
ensure_top_manager_discovery_signals() {
  local candidate_book="$1"
  local follow_events="data_pit/sec/top_manager_13f_follow_events.parquet"
  local discovery="data_pit/sec/top_manager_discovery_signals.parquet"
  mkdir -p outputs/full_rebuild_logs
  if [ ! -s "$follow_events" ]; then
    echo "[top7-discovery] follow events missing; running PIT top-manager follow study first"
    python tools/run_pit_top_manager_follow_study.py --events data_pit/sec/13f_position_events.parquet --labels data_pit/sec/post_disclosure_alpha_labels.parquet --output-dir outputs/pit_top_manager_follow_study --cohort-pit data_pit/sec/pit_top_manager_cohorts.parquet --follow-events-pit "$follow_events" --horizons 21,63,126,252 --ranking-horizon 63 --ranking-lookback-days 1095 --cohort-refresh-months 6 --top-n 10 --min-manager-events 8 --history-years 8 2>&1 | tee outputs/full_rebuild_logs/pit_top_manager_follow_study.log || true
  fi
  if [ ! -s "$follow_events" ]; then
    echo "[top7-discovery] follow events still missing; lane will be zero-filled"
    return 0
  fi
  python tools/build_top_manager_discovery_signals.py --follow-events "$follow_events" --candidate-book "$candidate_book" --output "$discovery" --lookback-days 252 2>&1 | tee outputs/full_rebuild_logs/top_manager_discovery_signals.log || true
}

build_sec_enriched_candidate_book() {
  SIDECAR_CANDIDATE_BOOK="outputs/reports/candidate_replay_book.csv"
  local enriched="outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv"
  if [ -s "$enriched" ]; then
    SIDECAR_CANDIDATE_BOOK="$enriched"
    echo "[sec-enrich] using existing enriched candidate book: $SIDECAR_CANDIDATE_BOOK"
    return 0
  fi
  echo "[sec-enrich] building PIT-safe evidence-enriched candidate replay book"
  if [ ! -s "$SIDECAR_CANDIDATE_BOOK" ]; then
    echo "[sec-enrich] missing base candidate replay book; sidecars will use default resolver"
    return 0
  fi
  ensure_top_manager_discovery_signals "$SIDECAR_CANDIDATE_BOOK"
  python tools/run_sec_enriched_candidate_replay.py --candidate-book "$SIDECAR_CANDIDATE_BOOK" --output-dir outputs/sec_enriched_candidate_replay 2>&1 | tee outputs/full_rebuild_logs/sec_enriched_candidate_replay.log || true
  if [ -s "$enriched" ]; then
    SIDECAR_CANDIDATE_BOOK="$enriched"
    echo "[sec-enrich] using enriched candidate book: $SIDECAR_CANDIDATE_BOOK"
  else
    echo "[sec-enrich] enriched candidate book unavailable; using base candidate book"
  fi
}

refresh_replay_price_cache() {
  echo "[price-cache] refreshing replay price cache and observed-bar manifest"
  mkdir -p outputs/full_rebuild_logs
  local books=()
  if [ -s outputs/reports/main_monthly_weights.csv ]; then
    books+=(outputs/reports/main_monthly_weights.csv)
  fi
  if [ -s outputs/reports/concentrated_strategy_holdings.csv ]; then
    books+=(outputs/reports/concentrated_strategy_holdings.csv)
  fi
  if [ "${#books[@]}" -eq 0 ]; then
    echo "[price-cache] no monthly books available; cannot refresh replay price cache manifest" | tee outputs/full_rebuild_logs/replay_price_cache_refresh.log
    return 0
  fi
  python tools/build_replay_price_cache.py --books "${books[@]}" --scored outputs/scored_latest.csv --output-dir cache_prices --required-tickers SPY QQQ --refresh-stale-days 2 2>&1 | tee outputs/full_rebuild_logs/replay_price_cache_refresh.log
}

run_alphaops_vnext_production() {
  if [ "$PORTFOLIO_POLICY" = "alphaops_vnext_production" ]; then
    echo "[alphaops-vnext] replacing operating target books before broker replay"
    build_sec_enriched_candidate_book
    python tools/run_alphaops_vnext_policy_replay.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/alphaops_vnext --portfolio-kind both --main-target-n 15 --concentrated-target-n 5 --production-output-mode replace_operating --skip-broker-replay --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/alphaops_vnext_policy_replay.log
  fi
}

run_decision_cadence_review() {
  echo "[decision-cadence] reviewing daily/weekly/monthly decision cadence"
  python tools/run_decision_cadence_review.py --latest-run outputs --price-cache cache_prices --output-dir outputs/decision_cadence 2>&1 | tee outputs/full_rebuild_logs/decision_cadence_review.log || true
}

build_daily_market_snapshot() {
  echo "[daily-market-snapshot] building latest close/open/market-cap snapshot for freshness contract"
  mkdir -p outputs/full_rebuild_logs data_raw/free/market_snapshot data_pit/free/market_snapshot
  BOOK_ARGS=()
  [ -s outputs/portfolio_latest.csv ] && BOOK_ARGS+=(--book outputs/portfolio_latest.csv)
  [ -s outputs/concentrated_portfolio_latest.csv ] && BOOK_ARGS+=(--book outputs/concentrated_portfolio_latest.csv)
  [ -s outputs/reports/operating_main_target_book.csv ] && BOOK_ARGS+=(--book outputs/reports/operating_main_target_book.csv)
  [ -s outputs/reports/operating_concentrated_target_book.csv ] && BOOK_ARGS+=(--book outputs/reports/operating_concentrated_target_book.csv)
  timeout 10m python tools/build_daily_market_snapshot.py \
    --price-cache cache_prices \
    "${BOOK_ARGS[@]}" \
    --scored outputs/scored_latest.csv \
    --max-scored 250 \
    --required-tickers SPY QQQ SMH SOXX \
    --output-dir outputs/daily_market_snapshot \
    --data-lake-dir data_pit/free/market_snapshot \
    --info-cache data_raw/free/market_snapshot/yf_market_info_cache.csv \
    --refresh-info-days 14 \
    2>&1 | tee outputs/full_rebuild_logs/daily_market_snapshot.log || true
}

run_metric_hygiene_report() {
  echo "[metric-hygiene] separating official broker-ledger metrics from deprecated legacy/proxy metrics"
  python tools/run_metric_hygiene_report.py --latest-run outputs --output-dir outputs/metric_hygiene 2>&1 | tee outputs/full_rebuild_logs/metric_hygiene_report.log || true
}

run_data_freshness_contract() {
  echo "[data-freshness] validating restored data watermarks before operating recommendations"
  python tools/run_data_freshness_contract.py \
    --latest-run outputs \
    --price-cache cache_prices \
    --output-dir outputs/data_freshness_contract \
    --require-current-operating-books \
    --source-run-id "${GITHUB_RUN_ID:-local}" \
    --source-commit-sha "${GITHUB_SHA:-}" \
    --source-branch "${GITHUB_REF_NAME:-}" \
    --source-artifact-name "${ARTIFACT_PROFILE}_${SIDECAR_PROFILE}_${GITHUB_RUN_ID:-local}" \
    --source-context full_rebuild_sidecar \
    --freshness-contract-non-fatal \
    2>&1 | tee outputs/full_rebuild_logs/data_freshness_contract.log || true
}

run_universe_health_audit() {
  echo "[universe-health] auditing R1000/IWB source chain before official broker evidence"
  mkdir -p outputs/full_rebuild_logs
  python tools/run_universe_health_audit.py \
    --latest-run outputs \
    --price-cache cache_prices \
    --output-dir outputs/universe_health \
    --min-r1000-base 400 \
    --universe-mode "$UNIVERSE_MODE" \
    2>&1 | tee outputs/full_rebuild_logs/universe_health_audit.log || true
}

write_alpha_plane_measurement_status() {
  echo "[alpha-plane] writing measurement sidecar status"
  python - <<'PY'
import json
from pathlib import Path

checks = {
    "stock_selection_quality": (
        "outputs/stock_selection_quality/summary.json",
        "outputs/full_rebuild_logs/stock_selection_quality_audit.log",
    ),
    "entry_exit_timing": (
        "outputs/entry_exit_timing_audit/summary.json",
        "outputs/full_rebuild_logs/entry_exit_timing_audit.log",
    ),
    "cash_reentry_quality": (
        "outputs/cash_reentry_quality/summary.json",
        "outputs/full_rebuild_logs/cash_reentry_quality_audit.log",
    ),
}
payload = {
    "schema_version": "alpha_plane_measurement_status_v1",
    "production_mutation_allowed": False,
    "tools": {},
}
for name, (summary_path, log_path) in checks.items():
    summary_file = Path(summary_path)
    log_file = Path(log_path)
    tool_status = "missing_summary"
    detail = {}
    if summary_file.exists():
        try:
            detail = json.loads(summary_file.read_text(encoding="utf-8"))
            tool_status = str(detail.get("status") or "completed")
        except Exception as exc:
            tool_status = "invalid_summary_json"
            detail = {"error": str(exc)}
    payload["tools"][name] = {
        "status": tool_status,
        "summary_path": summary_path,
        "summary_exists": summary_file.exists(),
        "log_path": log_path,
        "log_exists": log_file.exists(),
        "production_mutation_allowed": False,
        "source_run_id": detail.get("source_run_id"),
        "source_commit_sha": detail.get("source_commit_sha"),
        "source_artifact_name": detail.get("source_artifact_name"),
        "source_of_truth_level": detail.get("source_of_truth_level"),
    }
Path("outputs").mkdir(parents=True, exist_ok=True)
Path("outputs/alpha_plane_measurement_status.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
}

run_cash_contract_validator() {
  echo "[cash-contract] validating target-book cash against broker realized cash"
  python tools/validate_target_book_cash_contract.py --latest-run outputs --output-dir outputs/cash_contract 2>&1 | tee outputs/full_rebuild_logs/cash_contract.log || true
}

if [ "$SIDECAR_PROFILE" = "phase_g_only" ]; then
  echo "[sidecar] phase_g_only is handled by phase_g_crisis_evidence_liquidity_replay.yml; skipping full rebuild sidecars."
  mkdir -p outputs/full_rebuild_logs
  BASELINE_RUN_ID="${GITHUB_RUN_ID:-local}"
  run_patch_manifest
  exit 0
fi
if [ "$SIDECAR_PROFILE" = "operating_minimal" ] || [ "$SIDECAR_PROFILE" = "official" ]; then
  refresh_replay_price_cache
  python tools/build_operating_target_books.py --latest-run outputs --price-cache cache_prices --output-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/operating_target_books.log
  build_daily_market_snapshot
  # Crisis defense substrate (run 27445937281 diagnosis, 2026-06-13): without
  # these, vnext daily_crisis_state has long_crisis_score=0.0 and
  # cash_gate_reason='missing_long_crisis_features' through COVID/2022, so the
  # 2-confirmation cash-raise gate never opens and MaxDD stays at the
  # unhedged path (Main -26%, Conc -26%). Building the crisis features +
  # walk-forward thresholds before run_alphaops_vnext_production lets vnext
  # use the real confirmation. Lightweight: FRED data is already restored
  # and the long-crisis feature builder is CPU-cheap. Failures are non-fatal.
  if [ ! -s outputs/crisis_signals/daily_features.parquet ]; then
    python tools/run_crisis_signal_builder.py 2>&1 | tee outputs/full_rebuild_logs/crisis_signal_builder.log || true
  fi
  build_long_crisis_inputs
  run_alphaops_vnext_production
  run_universe_health_audit
  python tools/audit_data_readiness.py --latest-run outputs --price-cache cache_prices --output-dir outputs/data_readiness 2>&1 | tee outputs/full_rebuild_logs/data_readiness_pre_broker.log || true
  run_data_freshness_contract
  run_sidecar_promotion_hook
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_ledger_replay_main.log
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_ledger_replay_concentrated.log
  if [ -s outputs/reports/main_monthly_weights.csv ]; then
    python tools/run_broker_ledger_replay.py --target-book outputs/reports/main_monthly_weights.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/legacy_monthly_broker_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/legacy_monthly_broker_replay_main.log || true
  fi
  if [ -s outputs/reports/concentrated_strategy_holdings.csv ]; then
    python tools/run_broker_ledger_replay.py --target-book outputs/reports/concentrated_strategy_holdings.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/legacy_monthly_broker_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/legacy_monthly_broker_replay_concentrated.log || true
  fi
  python tools/run_mdd_cash_overlay_research.py --latest-run outputs --output-dir outputs/mdd_cash_overlay_research --cost-bps 25 --confirm-days 2 --release-step 0.10 --change-band 0.03 2>&1 | tee outputs/full_rebuild_logs/mdd_cash_overlay_research.log || true
  # Build round-trip trade journal early so leader_lifecycle_audit (Stage T1)
  # has its inputs in operating_minimal too — previously the journal only ran
  # in the official-and-above branch, leaving the audit blind on the cheap
  # profile we use for fast iteration. Cheap (just FIFO-pairs broker trades),
  # failures stay non-fatal.
  python tools/run_broker_trade_journal.py --latest-run outputs --output-dir outputs/broker_trade_journal 2>&1 | tee outputs/full_rebuild_logs/broker_trade_journal.log || true
  python tools/run_trade_attribution_analysis.py --latest-run outputs --output-dir outputs/trade_attribution 2>&1 | tee outputs/full_rebuild_logs/trade_attribution_analysis.log || true
  python tools/run_leader_lifecycle_audit.py --latest-run outputs --output-dir outputs/leader_lifecycle_audit 2>&1 | tee outputs/full_rebuild_logs/leader_lifecycle_audit.log || true
  python tools/run_entry_exit_timing_audit.py --latest-run outputs --output-dir outputs/entry_exit_timing_audit --price-cache cache_prices --source-run-id "${GITHUB_RUN_ID:-local}" --source-commit-sha "${GITHUB_SHA:-}" --source-branch "${GITHUB_REF_NAME:-}" --source-artifact-name "${ARTIFACT_PROFILE}_${SIDECAR_PROFILE}_${GITHUB_RUN_ID:-local}" 2>&1 | tee outputs/full_rebuild_logs/entry_exit_timing_audit.log || true
  # Stage T2 — sub-monthly exit overlay measurement. PRWV walks daily closes
  # between monthly rebalances and fires hard/trailing/relative stops; the
  # compare tool surfaces the CAGR/MDD trade-off vs monthly broker baseline.
  # Promoted into operating_minimal because the comparison is the precondition
  # for tuning stop thresholds. Failures stay non-fatal.
  if [ -s outputs/reports/main_monthly_weights.csv ]; then
    python tools/run_position_risk_weekly_validation.py --holdings outputs/reports/main_monthly_weights.csv --period-map outputs/reports/regime_by_month.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/position_risk_weekly_validation/main 2>&1 | tee outputs/full_rebuild_logs/position_risk_weekly_validation_main.log || true
  fi
  if [ -s outputs/reports/concentrated_strategy_holdings.csv ]; then
    python tools/run_position_risk_weekly_validation.py --holdings outputs/reports/concentrated_strategy_holdings.csv --period-map outputs/reports/concentrated_strategy_monthly.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/position_risk_weekly_validation/concentrated 2>&1 | tee outputs/full_rebuild_logs/position_risk_weekly_validation_concentrated.log || true
  fi
  python tools/run_subdaily_exit_compare.py --latest-run outputs --output-dir outputs/subdaily_exit_compare 2>&1 | tee outputs/full_rebuild_logs/subdaily_exit_compare.log || true
  # Stage T2b — production-grade daily-stop next-close ledger. Promoted out of
  # the official-only block into operating_minimal so every fast A/B arm yields a
  # broker_position_risk_replay MaxDD directly comparable to the plain
  # broker_replay (monthly next-close) MaxDD — the precondition for deciding
  # whether a daily position stop earns promotion to the acceptance metric.
  # Stop levels are env-overridable (R1000_DAILY_STOP_*) so challenger runs can
  # sweep stop tightness through experiment_env_json without editing this file.
  # Cheap (daily walk over an already-built target book); failures stay
  # non-fatal. The parabolic variant stays official-only below.
  DAILY_STOP_HARD="${R1000_DAILY_STOP_HARD_STOP:--0.12}"
  DAILY_STOP_TRAILING="${R1000_DAILY_STOP_TRAILING_STOP:--0.20}"
  DAILY_STOP_TRAIL_ACT="${R1000_DAILY_STOP_TRAILING_ACTIVATION:-0.25}"
  echo "[sidecar] daily-stop params hard=${DAILY_STOP_HARD} trailing=${DAILY_STOP_TRAILING} activation=${DAILY_STOP_TRAIL_ACT}"
  if [ -s outputs/reports/operating_main_target_book.csv ]; then
    python tools/run_broker_position_risk_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_position_risk_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 --hard-stop "$DAILY_STOP_HARD" --trailing-stop "$DAILY_STOP_TRAILING" --trailing-activation "$DAILY_STOP_TRAIL_ACT" 2>&1 | tee outputs/full_rebuild_logs/broker_position_risk_replay_main.log || true
  fi
  if [ -s outputs/reports/operating_concentrated_target_book.csv ]; then
    python tools/run_broker_position_risk_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_position_risk_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 --hard-stop "$DAILY_STOP_HARD" --trailing-stop "$DAILY_STOP_TRAILING" --trailing-activation "$DAILY_STOP_TRAIL_ACT" 2>&1 | tee outputs/full_rebuild_logs/broker_position_risk_replay_concentrated.log || true
  fi
  if [ "$SIDECAR_PROFILE" = "official" ]; then
    python tools/run_broker_position_risk_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_parabolic_risk_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 --hard-stop -9 --relative-trim-threshold -9 --relative-exit-threshold -9 --disable-distribution-exit --candidate-id main_broker_parabolic_risk_replay --trailing-activation 0.50 --trailing-stop -0.20 2>&1 | tee outputs/full_rebuild_logs/broker_parabolic_risk_replay_main.log || true
    python tools/run_broker_position_risk_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_parabolic_risk_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 --hard-stop -9 --relative-trim-threshold -9 --relative-exit-threshold -9 --disable-distribution-exit --candidate-id concentrated_broker_parabolic_risk_replay --trailing-activation 0.50 --trailing-stop -0.20 2>&1 | tee outputs/full_rebuild_logs/broker_parabolic_risk_replay_concentrated.log || true
  fi
  # Opt-in lever sweep (R1000_LEVER_SWEEP=1). The conc-gross floor and daily-stop
  # levers act only at the target-book/replay stage, so one rebuild's scored
  # output can measure a whole grid here instead of paying a full ~3-4h rebuild
  # per lever value. Measurement only; never replaces operating books. Off by
  # default so normal A/B arms are unchanged. Failures stay non-fatal.
  # Unconditional invocation probe — committed via the outputs/lever_sweep copy so
  # the cause is visible in git even though the 31-min sidecar step's mid-log is
  # too deep to fetch. Three prior runs produced no lever_sweep output at all;
  # since the harness writes a skeleton summary.json on its first line, an empty
  # dir means the harness was never invoked — this probe pins down whether this
  # shell actually saw R1000_LEVER_SWEEP=1.
  mkdir -p outputs/lever_sweep
  printf '{"r1000_lever_sweep_seen":"%s","sidecar_profile":"%s","floors":"%s","ts":"%s"}\n' "${R1000_LEVER_SWEEP:-unset}" "${SIDECAR_PROFILE:-unset}" "${R1000_LEVER_SWEEP_FLOORS:-default}" "$(date -u +%FT%TZ)" > outputs/lever_sweep/_invocation_probe.json
  if [ "${R1000_LEVER_SWEEP:-0}" = "1" ]; then
    # tee the harness output into outputs/lever_sweep/ (copied to git) so a crash
    # traceback survives without needing the unreachable step log.
    python tools/run_lever_sweep.py --latest-run outputs --price-cache cache_prices --output-dir outputs/lever_sweep --conc-gross-floors "${R1000_LEVER_SWEEP_FLOORS:-0.0,0.7,0.8,0.9}" --daily-stop-grid "${R1000_LEVER_SWEEP_DAILY_STOP:-default,-0.12:-0.20,-0.10:-0.15,-0.08:-0.12}" 2>&1 | tee outputs/lever_sweep/_harness.log outputs/full_rebuild_logs/lever_sweep.log || true
    # Fail-loud guard: a prior run had R1000_LEVER_SWEEP=1 but produced no
    # output (harness killed before writing), yet the job still reported
    # success. Surface the outcome explicitly so a silent no-op is visible.
    if [ -f outputs/lever_sweep/summary.json ]; then
      echo "[lever-sweep][guard] summary status: $(python -c 'import json,sys;print(json.load(open("outputs/lever_sweep/summary.json")).get("status","unknown"))' 2>/dev/null || echo unparseable)"
    else
      echo "[lever-sweep][guard] WARN: R1000_LEVER_SWEEP=1 but outputs/lever_sweep/summary.json is missing — harness did not complete (OOM/timeout?)."
    fi
  fi
  python tools/run_account_order_preview.py --account-state outputs/broker_replay/main/account_state_latest.json --target outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/account_ledger_preview/main --cost-bps 25 2>&1 | tee outputs/full_rebuild_logs/account_order_preview_main.log || true
  python tools/run_account_order_preview.py --account-state outputs/broker_replay/concentrated/account_state_latest.json --target outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/account_ledger_preview/concentrated --cost-bps 25 2>&1 | tee outputs/full_rebuild_logs/account_order_preview_concentrated.log || true
  python tools/run_live_trading_safety_audit.py --latest-run outputs --output-dir outputs/live_trading_safety 2>&1 | tee outputs/full_rebuild_logs/live_trading_safety_audit.log || true
  python tools/run_live_trading_risk_controls.py --latest-run outputs --price-cache cache_prices --output-dir outputs/live_trading_risk_controls --account-mode simulated 2>&1 | tee outputs/full_rebuild_logs/live_trading_risk_controls.log || true
  python tools/run_macro_policy_engine.py --latest-run outputs --output-dir outputs/macro_policy_engine 2>&1 | tee outputs/full_rebuild_logs/macro_policy_engine.log || true
  python tools/run_cash_policy_attribution.py --latest-run outputs --output-dir outputs/cash_policy 2>&1 | tee outputs/full_rebuild_logs/cash_policy_attribution.log || true
  python tools/run_stock_selection_quality_audit.py --latest-run outputs --output-dir outputs/stock_selection_quality --source-run-id "${GITHUB_RUN_ID:-local}" --source-commit-sha "${GITHUB_SHA:-}" --source-branch "${GITHUB_REF_NAME:-}" --source-artifact-name "${ARTIFACT_PROFILE}_${SIDECAR_PROFILE}_${GITHUB_RUN_ID:-local}" 2>&1 | tee outputs/full_rebuild_logs/stock_selection_quality_audit.log || true
  python tools/run_cash_reentry_quality_audit.py --latest-run outputs --output-dir outputs/cash_reentry_quality --source-run-id "${GITHUB_RUN_ID:-local}" --source-commit-sha "${GITHUB_SHA:-}" --source-branch "${GITHUB_REF_NAME:-}" --source-artifact-name "${ARTIFACT_PROFILE}_${SIDECAR_PROFILE}_${GITHUB_RUN_ID:-local}" 2>&1 | tee outputs/full_rebuild_logs/cash_reentry_quality_audit.log || true
  write_alpha_plane_measurement_status
  python tools/run_portfolio_goal_search.py --latest-run outputs 2>&1 | tee outputs/full_rebuild_logs/portfolio_goal_search.log || true
  # Official account evaluation reads this summary as part of the 8-year
  # broker-ledger/data-coverage gate, so it must exist before the verdict.
  python tools/audit_data_readiness.py --latest-run outputs --price-cache cache_prices --output-dir outputs/data_readiness 2>&1 | tee outputs/full_rebuild_logs/data_readiness.log || true
  python tools/check_10y_backtest_readiness.py --latest-run outputs --min-years 8 --output-dir outputs/eight_year_backtest_readiness --ref "${GITHUB_REF_NAME:-master}" --repo "${GITHUB_REPOSITORY:-wscha231/r1000-quant-engine}" 2>&1 | tee outputs/full_rebuild_logs/eight_year_backtest_readiness.log || true
  python tools/run_account_evaluation.py --latest-run outputs --output-dir outputs/account_evaluation 2>&1 | tee outputs/full_rebuild_logs/account_evaluation.log || true
  python tools/run_oos_lock_audit.py --latest-run outputs --output-dir outputs/oos_lock --config research/oos_lock.yaml 2>&1 | tee outputs/full_rebuild_logs/oos_lock.log || true
  # IS-only attribution sidecar — surfaces year-by-year where the IS CAGR is
  # leaking. Run 27498401423 conc 2021/2023 were tagged
  # structural_underinvestment_bull (~14pp of the IS gap). Cheap (rolls the
  # broker_replay equity curve + target book), failures stay non-fatal.
  python tools/run_is_attribution.py --latest-run outputs --output-dir outputs/is_attribution 2>&1 | tee outputs/full_rebuild_logs/is_attribution.log || true
  # Alpha/beta attribution: separates broker-ledger returns into broad market,
  # growth/tech, semiconductor factor beta, cash drag, and name contribution.
  # Review-only measurement sidecar; no scoring, target, cash, or order mutation.
  python tools/run_alpha_beta_attribution.py --latest-run outputs --price-cache cache_prices --output-dir outputs/alpha_beta_attribution 2>&1 | tee outputs/full_rebuild_logs/alpha_beta_attribution.log || true
  # Right-tail entry signal audit: verifies whether top contribution names had
  # PIT-visible entry signals. Realized PnL only chooses audit targets; no
  # forward-return ranking, target, cash, scoring, or order mutation.
  python tools/run_right_tail_entry_signal_audit.py --latest-run outputs --output-dir outputs/right_tail_entry_signal_audit 2>&1 | tee outputs/full_rebuild_logs/right_tail_entry_signal_audit.log || true
  # Right-tail drop counterfactual audit: measures whether dropped leaders still
  # had PIT-visible signals and then rebounded. Forward returns are audit labels
  # only; this never mutates scoring, target books, cash policy, or trading.
  python tools/run_right_tail_drop_counterfactual_audit.py --latest-run outputs --price-cache cache_prices --output-dir outputs/right_tail_drop_counterfactual_audit 2>&1 | tee outputs/full_rebuild_logs/right_tail_drop_counterfactual_audit.log || true
  # Fusion candidate review: intersects independent diagnostics before any new
  # capture-continuity policy is designed. Forward returns are audit labels only;
  # no scoring, target, cash, workflow, production, or live mutation.
  python tools/run_fusion_candidate_review.py --base-dir outputs --output-dir outputs/fusion_candidate_review 2>&1 | tee outputs/full_rebuild_logs/fusion_candidate_review.log || true
  # Era leadership diagnostic: factor IC and top-name contribution by era.
  # Review-only sidecar; no production scoring or target-book mutation.
  python tools/run_era_leadership_sidecar.py --latest-run outputs --output-dir outputs/era_leadership 2>&1 | tee outputs/full_rebuild_logs/era_leadership.log || true
  # Era-aware scoring challenger: converts the era diagnosis into
  # broker-replayable review-only target books. It never replaces operating
  # books; promotion requires a separate A/B and account-evaluation gate.
  python tools/run_era_aware_scoring_challenger.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/era_aware_scoring_challenger --promotion-review-dir outputs/promotion_review --source-run-id "${GITHUB_RUN_ID:-local}" --run-broker-replay 2>&1 | tee outputs/full_rebuild_logs/era_aware_scoring_challenger.log || true
  # ADR candidate scan: review-only universe expansion artifact. It never
  # mutates adr_universe.yaml, but gives system acceptance a current manifest.
  python tools/run_adr_candidate_scanner.py --adr-universe adr_universe.yaml --price-cache cache_prices --scan-price-cache --output-dir outputs/adr_candidates 2>&1 | tee outputs/full_rebuild_logs/adr_candidate_scanner.log || true
  # Performance ledger — the self-sustaining evaluation memory. Appends ONE
  # row per run to cloud_results/performance_ledger/ledger.jsonl (a path
  # OUTSIDE the per-date full_rebuild rotation, so it accumulates across runs
  # and is committed by `git add -f cloud_results/`). Trends IS-CAGR (the
  # honest KPI), flags IMPROVING/FLAT/REGRESSING, tracks best-ever, and
  # surfaces the dominant open leak as the recommended next focus. Non-fatal.
  LEDGER_RUN_ID="${GITHUB_RUN_ID:-local}"
  LEDGER_COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  python tools/run_performance_ledger.py --latest-run outputs --ledger-dir cloud_results/performance_ledger --run-id "$LEDGER_RUN_ID" --commit "$LEDGER_COMMIT" --universe "${UNIVERSE_MODE:-global_alpha_universe}" 2>&1 | tee outputs/full_rebuild_logs/performance_ledger.log || true
  python tools/run_whipsaw_cost_audit.py --latest-run outputs --output-dir outputs/whipsaw_cost_audit 2>&1 | tee outputs/full_rebuild_logs/whipsaw_cost_audit.log || true
  python tools/run_cagr_walkforward.py --latest-run outputs --output-dir outputs/cagr_walkforward 2>&1 | tee outputs/full_rebuild_logs/cagr_walkforward.log || true
  python tools/run_self_correction_router.py --ledger-dir cloud_results/performance_ledger --latest-run outputs --output-dir outputs/self_correction_router --ref "${GITHUB_REF_NAME:-master}" --repo "${GITHUB_REPOSITORY:-wscha231/r1000-quant-engine}" 2>&1 | tee outputs/full_rebuild_logs/self_correction_router.log || true
  python tools/run_review_dispatcher.py --payloads outputs/self_correction_router/workflow_dispatch_payloads.json --output-dir outputs/review_dispatcher_self_correction --repo "${GITHUB_REPOSITORY:-wscha231/r1000-quant-engine}" 2>&1 | tee outputs/full_rebuild_logs/review_dispatcher_self_correction.log || true
  run_cash_contract_validator
  run_metric_hygiene_report
  python tools/run_operating_snapshot.py --latest-run outputs --output-dir outputs/operating_snapshot 2>&1 | tee outputs/full_rebuild_logs/operating_snapshot.log || true
  python tools/run_user_portfolio_reports.py --latest-run outputs --price-cache cache_prices --output-dir outputs/user_portfolio_reports 2>&1 | tee outputs/full_rebuild_logs/user_portfolio_reports.log || true
  python tools/run_position_cleanup_review.py --latest-run outputs --output-dir outputs/operator_review 2>&1 | tee outputs/full_rebuild_logs/position_cleanup_review.log || true
  python tools/run_user_current_report.py --latest-run outputs --price-cache cache_prices --output-dir outputs/user_current --strict 2>&1 | tee outputs/full_rebuild_logs/user_current_report.log
  python tools/run_daily_crisis_monitor.py --latest-run outputs --output-dir outputs/daily_crisis_monitor 2>&1 | tee outputs/full_rebuild_logs/daily_crisis_monitor.log || true
  python tools/run_crisis_paper_order_bridge.py --latest-run outputs --price-cache cache_prices --output-dir outputs/crisis_paper_order_bridge 2>&1 | tee outputs/full_rebuild_logs/crisis_paper_order_bridge.log || true
  run_decision_cadence_review
  python tools/run_dataset_coverage_audit.py --latest-run outputs --output-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/dataset_coverage_audit.log || true
  python tools/run_portfolio_system_guard.py --latest-run outputs --output-dir outputs/portfolio_system_guard 2>&1 | tee outputs/full_rebuild_logs/portfolio_system_guard.log || true
  python tools/run_system_acceptance_audit.py --latest-run outputs --output-dir outputs/system_acceptance_audit --ref "${GITHUB_REF_NAME:-master}" --repo "${GITHUB_REPOSITORY:-wscha231/r1000-quant-engine}" 2>&1 | tee outputs/full_rebuild_logs/system_acceptance_audit.log || true
  python tools/run_review_dispatcher.py --payloads outputs/system_acceptance_audit/workflow_dispatch_payloads.json --output-dir outputs/review_dispatcher --repo "${GITHUB_REPOSITORY:-wscha231/r1000-quant-engine}" 2>&1 | tee outputs/full_rebuild_logs/review_dispatcher.log || true
  if [ "$SIDECAR_PROFILE" = "official" ]; then
    python tools/run_broker_execution_policy_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_execution_policy_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_execution_policy_replay_main.log || true
    python tools/run_broker_execution_policy_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_execution_policy_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 --buy-band 0.04 --sell-band 0.06 --winner-overweight-band 0.15 --new-entry-scale 0.85 2>&1 | tee outputs/full_rebuild_logs/broker_execution_policy_replay_concentrated.log || true
    python tools/run_execution_lag_review.py --latest-run outputs --output-dir outputs/operator_review 2>&1 | tee outputs/full_rebuild_logs/execution_lag_review.log || true
    python tools/run_position_risk_review.py --latest-run outputs --output-dir outputs/operator_review 2>&1 | tee outputs/full_rebuild_logs/position_risk_review.log || true
    python tools/run_concentrated_broker_variant_review.py --latest-run outputs --price-cache cache_prices --output-dir outputs/operator_review 2>&1 | tee outputs/full_rebuild_logs/concentrated_broker_variant_review.log || true
    python tools/run_position_cleanup_review.py --latest-run outputs --output-dir outputs/operator_review 2>&1 | tee outputs/full_rebuild_logs/position_cleanup_review.log || true
    BASELINE_RUN_ID="${GITHUB_RUN_ID:-local}"
    python tools/create_healthy_baseline_lock.py --latest-run outputs --output-dir outputs/baseline_lock --run-id "$BASELINE_RUN_ID" 2>&1 | tee outputs/full_rebuild_logs/baseline_lock.log || true
    build_sec_enriched_candidate_book
    python tools/run_market_leader_challenger.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/market_leader_challenger --baseline-lock "outputs/baseline_lock/healthy_baseline_${BASELINE_RUN_ID}.json" --allow-missing-baseline-lock 2>&1 | tee outputs/full_rebuild_logs/market_leader_challenger.log || true
    python tools/run_superperformance_trader_replay.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/superperformance_trader_replay --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/superperformance_trader_replay.log || true
    if [ ! -s outputs/crisis_signals/daily_features.parquet ]; then
      python tools/run_crisis_signal_builder.py 2>&1 | tee outputs/full_rebuild_logs/crisis_signal_builder.log || true
    fi
    # Walk-forward governor threshold learning. Without these the integrated
    # replay falls back to the conservative defaults (low=0.30/mid=0.50/high=
    # 0.70), which run 27247439447 showed never trigger the defense zone --
    # so the COVID/2022 MDD delta is structurally pinned at zero.
    build_long_crisis_inputs
    python tools/run_integrated_leader_crisis_replay.py --leader-dir outputs/market_leader_challenger --crisis-features outputs/crisis_signals/daily_features.parquet --price-cache cache_prices --output-dir outputs/integrated_leader_crisis_replay --portfolio-kind both --cost-bps 25 --thresholds-json outputs/long_crisis_learning/best_thresholds.json 2>&1 | tee outputs/full_rebuild_logs/integrated_leader_crisis_replay.log || true
    python tools/run_integrated_theme_leader_crisis_replay.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/integrated_theme_leader_crisis_replay --baseline-lock outputs/baseline_lock/active_baseline.json --portfolio-kind both --cost-bps 25 --artifact-id "$BASELINE_RUN_ID" 2>&1 | tee outputs/full_rebuild_logs/integrated_theme_leader_crisis_replay.log || true
    if [ "$PORTFOLIO_POLICY" = "integrated_shadow" ] || [ "$PORTFOLIO_POLICY" = "market_leader_shadow" ]; then
      run_sidecar_promotion_hook
    fi
    python tools/run_strategy_logic_ledger.py --latest-run outputs --integrated-output outputs/integrated_theme_leader_crisis_replay --output-dir outputs/strategy_logic_ledger --run-id "$BASELINE_RUN_ID" --commit-sha "${GITHUB_SHA:-}" --artifact-id "$BASELINE_RUN_ID" 2>&1 | tee outputs/full_rebuild_logs/strategy_logic_ledger.log || true
    run_decision_cadence_review
    run_patch_manifest
    python tools/run_user_current_report.py --latest-run outputs --price-cache cache_prices --output-dir outputs/user_current --strict 2>&1 | tee outputs/full_rebuild_logs/user_current_report_final.log || true
  fi
  python tools/run_latest_price_date_audit.py --price-cache cache_prices --latest-run outputs --output outputs/latest_price_date_audit.json 2>&1 | tee outputs/full_rebuild_logs/latest_price_date_audit.log || true
  BASELINE_RUN_ID="${GITHUB_RUN_ID:-local}"
  run_patch_manifest
  python tools/run_user_current_report.py --latest-run outputs --price-cache cache_prices --output-dir outputs/user_current --strict 2>&1 | tee outputs/full_rebuild_logs/user_current_report_final.log || true
  echo "[sidecar] ${SIDECAR_PROFILE} completed; heavy research sidecars skipped."
  exit 0
fi
refresh_replay_price_cache
python tools/run_main_v2_backtest.py --latest-run outputs --output-dir outputs/main_v2_backtest 2>&1 | tee outputs/full_rebuild_logs/main_v2_backtest.log || true
python tools/run_concentrated_policy_replay.py --latest-run outputs --output-dir outputs/concentrated_policy_replay --price-cache cache_prices --run-broker-replay --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/concentrated_policy_replay.log || true
python tools/run_concentrated_position_risk_replay.py --latest-run outputs --output-dir outputs/concentrated_position_risk_replay 2>&1 | tee outputs/full_rebuild_logs/concentrated_position_risk_replay.log || true
python tools/run_alpha_sprint_backtest.py --latest-run outputs --output-dir outputs/alpha_sprint_backtest 2>&1 | tee outputs/full_rebuild_logs/alpha_sprint_backtest.log || true
python tools/run_position_aware_risk_replay.py --holdings outputs/main_v2_backtest/monthly_holdings.csv --output-dir outputs/position_aware_risk_replay 2>&1 | tee outputs/full_rebuild_logs/position_aware_risk_replay.log || true
python tools/build_operating_target_books.py --latest-run outputs --price-cache cache_prices --output-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/operating_target_books.log
build_daily_market_snapshot
run_alphaops_vnext_production
run_universe_health_audit
python tools/audit_data_readiness.py --latest-run outputs --price-cache cache_prices --output-dir outputs/data_readiness 2>&1 | tee outputs/full_rebuild_logs/data_readiness_pre_broker.log || true
run_data_freshness_contract
run_sidecar_promotion_hook
python tools/archive_target_snapshots.py --latest-run outputs --price-cache cache_prices --output-dir outputs/target_snapshots 2>&1 | tee outputs/full_rebuild_logs/target_snapshot_archive.log
python tools/run_position_risk_weekly_validation.py --holdings outputs/reports/main_monthly_weights.csv --period-map outputs/reports/regime_by_month.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/position_risk_weekly_validation/main 2>&1 | tee outputs/full_rebuild_logs/position_risk_weekly_validation_main.log || true
python tools/run_position_risk_weekly_validation.py --holdings outputs/main_v2_backtest/monthly_holdings.csv --period-map outputs/reports/regime_by_month.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/position_risk_weekly_validation/main_v2 2>&1 | tee outputs/full_rebuild_logs/position_risk_weekly_validation_main_v2.log || true
python tools/run_position_risk_weekly_validation.py --holdings outputs/reports/concentrated_strategy_holdings.csv --period-map outputs/reports/concentrated_strategy_monthly.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/position_risk_weekly_validation/concentrated 2>&1 | tee outputs/full_rebuild_logs/position_risk_weekly_validation_concentrated.log || true
python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_ledger_replay_main.log
python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_ledger_replay_concentrated.log
python tools/run_subdaily_exit_grid_sweep.py --latest-run outputs --price-cache cache_prices --output-dir outputs/subdaily_exit_grid_wide_trailing --portfolio-kind both --hard-stop-grid=disabled --trailing-stop-grid=-0.25,-0.30,-0.35,-0.45 --trailing-activation 0.30 --relative-trim-threshold -99 --relative-exit-threshold -99 2>&1 | tee outputs/full_rebuild_logs/subdaily_exit_grid_wide_trailing.log || true
python tools/run_broker_position_risk_grid_sweep.py --latest-run outputs --price-cache cache_prices --output-dir outputs/broker_position_risk_grid_wide_trailing --portfolio-kind both --hard-stop-grid=disabled --trailing-stop-grid=-0.25,-0.30,-0.35,-0.45 --trailing-activation 0.30 --relative-trim-threshold -99 --relative-exit-threshold -99 2>&1 | tee outputs/full_rebuild_logs/broker_position_risk_grid_wide_trailing.log || true
python tools/run_mdd_cash_overlay_research.py --latest-run outputs --output-dir outputs/mdd_cash_overlay_research --cost-bps 25 --confirm-days 2 --release-step 0.10 --change-band 0.03 2>&1 | tee outputs/full_rebuild_logs/mdd_cash_overlay_research.log || true
python tools/build_event_target_books.py --latest-run outputs --price-cache cache_prices --output-dir outputs/event_target_books --reports-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/event_target_books.log || true
if [ -s outputs/reports/event_main_target_book.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/event_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/event_broker_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/event_broker_replay_main.log || true
fi
if [ -s outputs/reports/event_concentrated_target_book.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/event_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/event_broker_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/event_broker_replay_concentrated.log || true
fi
python tools/build_weekly_leader_target_books.py --latest-run outputs --price-cache cache_prices --output-dir outputs/weekly_leader_snapshots --reports-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/weekly_leader_target_books.log || true
if [ -s outputs/reports/weekly_leader_main_target_book.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/weekly_leader_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/weekly_leader_broker_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/weekly_leader_broker_replay_main.log || true
fi
if [ -s outputs/reports/weekly_leader_concentrated_target_book.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/weekly_leader_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/weekly_leader_broker_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/weekly_leader_broker_replay_concentrated.log || true
fi
if [ -s outputs/reports/operating_main_target_book.csv ]; then
  python tools/run_cost_sensitivity_sidecar.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/cost_sensitivity/main --cost-bps-list 25 50 75 100 --baseline-cost-bps 25 2>&1 | tee outputs/full_rebuild_logs/cost_sensitivity_main.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book.csv ]; then
  python tools/run_cost_sensitivity_sidecar.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/cost_sensitivity/concentrated --cost-bps-list 25 50 75 100 --baseline-cost-bps 25 2>&1 | tee outputs/full_rebuild_logs/cost_sensitivity_concentrated.log || true
fi
if [ -s outputs/reports/operating_main_target_book.csv ]; then
  python tools/run_neutral_regime_churn_filter.py --input-book outputs/reports/operating_main_target_book.csv --output-book outputs/reports/operating_main_target_book_churn_filtered.csv --diagnostics outputs/churn_filter/main/diagnostics.json --swap-threshold 2 --window-months 6 --target-regimes neutral 2>&1 | tee outputs/full_rebuild_logs/churn_filter_main.log || true
fi
if [ -s outputs/reports/operating_main_target_book_churn_filtered.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book_churn_filtered.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/churn_filtered_broker_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/churn_filtered_broker_replay_main.log || true
fi
if [ -s outputs/reports/operating_main_target_book.csv ]; then
  python tools/run_macro_circuit_breaker_filter.py --input-book outputs/reports/operating_main_target_book.csv --output-book outputs/reports/operating_main_target_book_macro_filtered.csv --diagnostics outputs/macro_circuit_filter/main/diagnostics.json --price-cache cache_prices --ma-window 200 --confirm-days 3 --halve-factor 0.5 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_filter_main.log || true
fi
if [ -s outputs/reports/operating_main_target_book_macro_filtered.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book_macro_filtered.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/macro_circuit_broker_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_broker_replay_main.log || true
fi
if [ -s outputs/reports/operating_main_target_book.csv ]; then
  python tools/run_macro_circuit_breaker_filter.py --input-book outputs/reports/operating_main_target_book.csv --output-book outputs/reports/operating_main_target_book_macro_factor25.csv --diagnostics outputs/macro_circuit_filter/main_factor25/diagnostics.json --price-cache cache_prices --ma-window 200 --confirm-days 3 --halve-factor 0.25 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_filter_main_factor25.log || true
  python tools/run_macro_circuit_breaker_filter.py --input-book outputs/reports/operating_main_target_book.csv --output-book outputs/reports/operating_main_target_book_macro_factor00.csv --diagnostics outputs/macro_circuit_filter/main_factor00/diagnostics.json --price-cache cache_prices --ma-window 200 --confirm-days 3 --halve-factor 0.00 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_filter_main_factor00.log || true
fi
if [ -s outputs/reports/operating_main_target_book_macro_factor25.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book_macro_factor25.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/macro_circuit_broker_replay/main_factor25 --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_broker_replay_main_factor25.log || true
fi
if [ -s outputs/reports/operating_main_target_book_macro_factor00.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book_macro_factor00.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/macro_circuit_broker_replay/main_factor00 --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_broker_replay_main_factor00.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book.csv ]; then
  python tools/run_macro_circuit_breaker_filter.py --input-book outputs/reports/operating_concentrated_target_book.csv --output-book outputs/reports/operating_concentrated_target_book_macro_filtered.csv --diagnostics outputs/macro_circuit_filter/concentrated/diagnostics.json --price-cache cache_prices --ma-window 200 --confirm-days 3 --halve-factor 0.5 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_filter_concentrated.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book_macro_filtered.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_concentrated_target_book_macro_filtered.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/macro_circuit_broker_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_broker_replay_concentrated.log || true
fi
if [ -s outputs/reports/operating_main_target_book.csv ]; then
  python tools/run_regime_capacity_filter.py --input-book outputs/reports/operating_main_target_book.csv --output-book outputs/reports/operating_main_target_book_regime_capacity_filtered.csv --diagnostics outputs/regime_capacity_filter/main/diagnostics.json --multipliers "bear=0.5,deep_bear=0.25" 2>&1 | tee outputs/full_rebuild_logs/regime_capacity_filter_main.log || true
fi
if [ -s outputs/reports/operating_main_target_book_regime_capacity_filtered.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book_regime_capacity_filtered.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/regime_capacity_broker_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/regime_capacity_broker_replay_main.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book.csv ]; then
  python tools/run_regime_capacity_filter.py --input-book outputs/reports/operating_concentrated_target_book.csv --output-book outputs/reports/operating_concentrated_target_book_regime_capacity_filtered.csv --diagnostics outputs/regime_capacity_filter/concentrated/diagnostics.json --multipliers "bear=0.5,deep_bear=0.25,neutral=0.85" --regime-source-book outputs/reports/operating_main_target_book.csv 2>&1 | tee outputs/full_rebuild_logs/regime_capacity_filter_concentrated.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book_regime_capacity_filtered.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_concentrated_target_book_regime_capacity_filtered.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/regime_capacity_broker_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/regime_capacity_broker_replay_concentrated.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book.csv ]; then
  python tools/run_regime_capacity_filter.py --input-book outputs/reports/operating_concentrated_target_book.csv --output-book outputs/reports/operating_concentrated_target_book_regime_capacity_neutral90.csv --diagnostics outputs/regime_capacity_filter/concentrated_neutral90/diagnostics.json --multipliers "bear=0.5,deep_bear=0.25,neutral=0.90" --regime-source-book outputs/reports/operating_main_target_book.csv 2>&1 | tee outputs/full_rebuild_logs/regime_capacity_filter_concentrated_neutral90.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book_regime_capacity_neutral90.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_concentrated_target_book_regime_capacity_neutral90.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/regime_capacity_broker_replay/concentrated_neutral90 --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/regime_capacity_broker_replay_concentrated_neutral90.log || true
fi
python tools/run_trade_attribution_analysis.py --latest-run outputs --output-dir outputs/trade_attribution 2>&1 | tee outputs/full_rebuild_logs/trade_attribution_analysis.log || true
python tools/run_broker_position_risk_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_position_risk_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_position_risk_replay_main.log || true
python tools/run_broker_position_risk_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_position_risk_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_position_risk_replay_concentrated.log || true
python tools/run_broker_position_risk_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_parabolic_risk_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 --hard-stop -9 --relative-trim-threshold -9 --relative-exit-threshold -9 --disable-distribution-exit --candidate-id main_broker_parabolic_risk_replay --trailing-activation 0.50 --trailing-stop -0.20 2>&1 | tee outputs/full_rebuild_logs/broker_parabolic_risk_replay_main.log || true
python tools/run_broker_position_risk_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_parabolic_risk_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 --hard-stop -9 --relative-trim-threshold -9 --relative-exit-threshold -9 --disable-distribution-exit --candidate-id concentrated_broker_parabolic_risk_replay --trailing-activation 0.50 --trailing-stop -0.20 2>&1 | tee outputs/full_rebuild_logs/broker_parabolic_risk_replay_concentrated.log || true
python tools/run_broker_execution_policy_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_execution_policy_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_execution_policy_replay_main.log || true
python tools/run_broker_execution_policy_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_execution_policy_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 --buy-band 0.04 --sell-band 0.06 --winner-overweight-band 0.15 --new-entry-scale 0.85 2>&1 | tee outputs/full_rebuild_logs/broker_execution_policy_replay_concentrated.log || true
python tools/run_operating_event_backtest.py --latest-run outputs --output-dir outputs/operating_event_backtest 2>&1 | tee outputs/full_rebuild_logs/operating_event_backtest.log || true
python tools/run_broker_gap_attribution.py --latest-run outputs --output-dir outputs/broker_gap_attribution 2>&1 | tee outputs/full_rebuild_logs/broker_gap_attribution.log || true
python tools/run_broker_trade_journal.py --latest-run outputs --output-dir outputs/broker_trade_journal 2>&1 | tee outputs/full_rebuild_logs/broker_trade_journal.log || true
python tools/run_account_order_preview.py --account-state outputs/broker_replay/main/account_state_latest.json --target outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/account_ledger_preview/main --cost-bps 25 2>&1 | tee outputs/full_rebuild_logs/account_order_preview_main.log || true
python tools/run_account_order_preview.py --account-state outputs/broker_replay/concentrated/account_state_latest.json --target outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/account_ledger_preview/concentrated --cost-bps 25 2>&1 | tee outputs/full_rebuild_logs/account_order_preview_concentrated.log || true
python tools/run_live_trading_safety_audit.py --latest-run outputs --output-dir outputs/live_trading_safety 2>&1 | tee outputs/full_rebuild_logs/live_trading_safety_audit.log || true
python tools/run_live_trading_risk_controls.py --latest-run outputs --price-cache cache_prices --output-dir outputs/live_trading_risk_controls --account-mode simulated 2>&1 | tee outputs/full_rebuild_logs/live_trading_risk_controls.log || true
python tools/run_monster_lifecycle_replay.py --latest-run outputs --policy concentrated --output-dir outputs/monster_lifecycle_replay 2>&1 | tee outputs/full_rebuild_logs/monster_lifecycle_replay.log || true
python tools/run_lifecycle_review_overlay.py --latest-run outputs --policy lifecycle_review_main --output-dir outputs/lifecycle_review_overlay_main 2>&1 | tee outputs/full_rebuild_logs/lifecycle_review_overlay_main.log || true
python tools/run_monster_lifecycle_replay.py --latest-run outputs --policy lifecycle_review_main --output-dir outputs/monster_lifecycle_review_main 2>&1 | tee outputs/full_rebuild_logs/monster_lifecycle_review_main.log || true
python tools/run_monster_lifecycle_replay.py --latest-run outputs --policy lifecycle_review_concentrated --output-dir outputs/monster_lifecycle_review_concentrated 2>&1 | tee outputs/full_rebuild_logs/monster_lifecycle_review_concentrated.log || true
python tools/run_orchestrator_replay.py --latest-run outputs 2>&1 | tee outputs/full_rebuild_logs/orchestrator_replay.log || true
python tools/run_leader_drop_diagnostics_sidecar.py --latest-run outputs --output-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/leader_drop_diagnostics_sidecar.log || true
python tools/run_governance_catalyst_report.py --latest-run outputs --output-dir outputs/governance_catalyst 2>&1 | tee outputs/full_rebuild_logs/governance_catalyst_report.log || true
python tools/run_style_regime_report.py --latest-run outputs --output-dir outputs/style_regime_report 2>&1 | tee outputs/full_rebuild_logs/style_regime_report.log || true
python tools/run_macro_policy_engine.py --latest-run outputs --output-dir outputs/macro_policy_engine 2>&1 | tee outputs/full_rebuild_logs/macro_policy_engine.log || true
python tools/run_cash_policy_attribution.py --latest-run outputs --output-dir outputs/cash_policy 2>&1 | tee outputs/full_rebuild_logs/cash_policy_attribution.log || true
python tools/run_cash_reentry_quality_audit.py --latest-run outputs --output-dir outputs/cash_reentry_quality --source-run-id "${GITHUB_RUN_ID:-local}" --source-commit-sha "${GITHUB_SHA:-}" --source-branch "${GITHUB_REF_NAME:-}" --source-artifact-name "${ARTIFACT_PROFILE}_${SIDECAR_PROFILE}_${GITHUB_RUN_ID:-local}" 2>&1 | tee outputs/full_rebuild_logs/cash_reentry_quality_audit.log || true
python tools/run_main_cash_drag_replay.py --latest-run outputs --output-dir outputs/main_cash_drag_replay 2>&1 | tee outputs/full_rebuild_logs/main_cash_drag_replay.log || true
python tools/run_crisis_reentry_replay.py --latest-run outputs --output-dir outputs/crisis_reentry_replay 2>&1 | tee outputs/full_rebuild_logs/crisis_reentry_replay.log || true
python tools/run_broker_crisis_reentry_replay.py --latest-run outputs --price-cache cache_prices --output-dir outputs/broker_crisis_reentry_replay/main --policy-id fast_reentry --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_crisis_reentry_replay.log || true
python tools/run_portfolio_goal_search.py --latest-run outputs 2>&1 | tee outputs/full_rebuild_logs/portfolio_goal_search.log || true
python tools/run_account_evaluation.py --latest-run outputs --output-dir outputs/account_evaluation 2>&1 | tee outputs/full_rebuild_logs/account_evaluation.log || true
python tools/run_oos_lock_audit.py --latest-run outputs --output-dir outputs/oos_lock --config research/oos_lock.yaml 2>&1 | tee outputs/full_rebuild_logs/oos_lock.log || true
run_cash_contract_validator
run_metric_hygiene_report
python tools/run_historical_trade_journey.py --latest-run outputs --output-dir outputs/historical_trade_journey 2>&1 | tee outputs/full_rebuild_logs/historical_trade_journey.log || true
python tools/run_selection_audit.py --latest-run outputs --output-dir outputs/selection_audit 2>&1 | tee outputs/full_rebuild_logs/selection_audit.log || true
python tools/run_stock_selection_quality_audit.py --latest-run outputs --output-dir outputs/stock_selection_quality --source-run-id "${GITHUB_RUN_ID:-local}" --source-commit-sha "${GITHUB_SHA:-}" --source-branch "${GITHUB_REF_NAME:-}" --source-artifact-name "${ARTIFACT_PROFILE}_${SIDECAR_PROFILE}_${GITHUB_RUN_ID:-local}" 2>&1 | tee outputs/full_rebuild_logs/stock_selection_quality_audit.log || true
python tools/run_entry_exit_timing_audit.py --latest-run outputs --output-dir outputs/entry_exit_timing_audit --price-cache cache_prices --source-run-id "${GITHUB_RUN_ID:-local}" --source-commit-sha "${GITHUB_SHA:-}" --source-branch "${GITHUB_REF_NAME:-}" --source-artifact-name "${ARTIFACT_PROFILE}_${SIDECAR_PROFILE}_${GITHUB_RUN_ID:-local}" 2>&1 | tee outputs/full_rebuild_logs/entry_exit_timing_audit.log || true
write_alpha_plane_measurement_status
python tools/run_dataset_coverage_audit.py --latest-run outputs --output-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/dataset_coverage_audit.log || true
python tools/check_10y_backtest_readiness.py --latest-run outputs --min-years 8 --output-dir outputs/eight_year_backtest_readiness --ref "${GITHUB_REF_NAME:-master}" --repo "${GITHUB_REPOSITORY:-wscha231/r1000-quant-engine}" 2>&1 | tee outputs/full_rebuild_logs/eight_year_backtest_readiness.log || true
python tools/check_10y_backtest_readiness.py --latest-run outputs --output-dir outputs/ten_year_backtest_readiness --ref "${GITHUB_REF_NAME:-master}" --repo "${GITHUB_REPOSITORY:-wscha231/r1000-quant-engine}" 2>&1 | tee outputs/full_rebuild_logs/ten_year_backtest_readiness.log || true
python tools/audit_data_readiness.py --latest-run outputs --price-cache cache_prices --output-dir outputs/data_readiness 2>&1 | tee outputs/full_rebuild_logs/data_readiness.log || true
python tools/run_weekly_evaluation.py --latest-run outputs --price-cache cache_prices --output-dir outputs/weekly_evaluation --stale-days-threshold 10 2>&1 | tee outputs/full_rebuild_logs/weekly_evaluation.log || true
python tools/run_adr_candidate_scanner.py --adr-universe adr_universe.yaml --price-cache cache_prices --scan-price-cache --output-dir outputs/adr_candidates 2>&1 | tee outputs/full_rebuild_logs/adr_candidate_scanner.log || true
python tools/run_theme_leadership_tape.py --scored outputs/scored_latest.csv --price-cache cache_prices --output-dir outputs/theme_leadership_tape 2>&1 | tee outputs/full_rebuild_logs/theme_leadership_tape.log || true
python tools/run_theme_concentration_challenger.py --latest-run outputs --output-dir outputs/theme_concentration_challenger --top-n 3 --single-name-cap 0.50 --cost-bps 50 2>&1 | tee outputs/full_rebuild_logs/theme_concentration_challenger.log || true
BASELINE_RUN_ID="${GITHUB_RUN_ID:-local}"
python tools/create_healthy_baseline_lock.py --latest-run outputs --output-dir outputs/baseline_lock --run-id "$BASELINE_RUN_ID" 2>&1 | tee outputs/full_rebuild_logs/baseline_lock.log || true
build_sec_enriched_candidate_book
python tools/run_market_leader_challenger.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/market_leader_challenger --baseline-lock "outputs/baseline_lock/healthy_baseline_${BASELINE_RUN_ID}.json" --allow-missing-baseline-lock 2>&1 | tee outputs/full_rebuild_logs/market_leader_challenger.log || true
python tools/run_superperformance_trader_replay.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/superperformance_trader_replay --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/superperformance_trader_replay.log || true
if [ ! -s outputs/crisis_signals/daily_features.parquet ]; then
  python tools/run_crisis_signal_builder.py 2>&1 | tee outputs/full_rebuild_logs/crisis_signal_builder.log || true
fi
build_long_crisis_inputs
python tools/run_integrated_leader_crisis_replay.py --leader-dir outputs/market_leader_challenger --crisis-features outputs/crisis_signals/daily_features.parquet --price-cache cache_prices --output-dir outputs/integrated_leader_crisis_replay --portfolio-kind both --cost-bps 25 --thresholds-json outputs/long_crisis_learning/best_thresholds.json 2>&1 | tee outputs/full_rebuild_logs/integrated_leader_crisis_replay.log || true
python tools/run_integrated_theme_leader_crisis_replay.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/integrated_theme_leader_crisis_replay --baseline-lock outputs/baseline_lock/active_baseline.json --portfolio-kind both --cost-bps 25 --artifact-id "$BASELINE_RUN_ID" 2>&1 | tee outputs/full_rebuild_logs/integrated_theme_leader_crisis_replay.log || true
if [ "$PORTFOLIO_POLICY" = "integrated_shadow" ] || [ "$PORTFOLIO_POLICY" = "market_leader_shadow" ]; then
  run_sidecar_promotion_hook
fi
python tools/run_strategy_logic_ledger.py --latest-run outputs --integrated-output outputs/integrated_theme_leader_crisis_replay --output-dir outputs/strategy_logic_ledger --run-id "$BASELINE_RUN_ID" --commit-sha "${GITHUB_SHA:-}" --artifact-id "$BASELINE_RUN_ID" 2>&1 | tee outputs/full_rebuild_logs/strategy_logic_ledger.log || true
python tools/run_latest_price_date_audit.py --price-cache cache_prices --latest-run outputs --output outputs/latest_price_date_audit.json 2>&1 | tee outputs/full_rebuild_logs/latest_price_date_audit.log || true
python tools/run_auto_learning_v2.py --latest-run outputs --output-dir outputs/auto_learning_v2 --research-dir outputs/auto_learning_v2/research 2>&1 | tee outputs/full_rebuild_logs/auto_learning_v2.log || true
python tools/run_winner_lifecycle_reports.py --latest-run outputs --output-dir outputs/winner_lifecycle 2>&1 | tee outputs/full_rebuild_logs/winner_lifecycle.log || true
python tools/run_winner_onset_study.py --scored outputs/scored_latest.csv --top-tickers 80 --limit 80 --years 10 --output-dir outputs/winner_onset_study 2>&1 | tee outputs/full_rebuild_logs/winner_onset_study.log || true
python tools/run_shakeout_breakdown_study.py --scored outputs/scored_latest.csv --top-tickers 80 --limit 80 --years 10 --output-dir outputs/shakeout_breakdown_study 2>&1 | tee outputs/full_rebuild_logs/shakeout_breakdown_study.log || true
python tools/run_shakeout_disclosure_reversal_study.py --events data_pit/sec/13f_position_events.parquet --events data_pit/sec/form4_transaction_events.parquet --events data_pit/etf_holdings/etf_holding_events.parquet --price-cache cache_prices --output-dir outputs/shakeout_disclosure_reversal_study 2>&1 | tee outputs/full_rebuild_logs/shakeout_disclosure_reversal_study.log || true
if [ ! -s data_pit/sec/top_manager_13f_follow_events.parquet ]; then
python tools/run_pit_top_manager_follow_study.py --events data_pit/sec/13f_position_events.parquet --labels data_pit/sec/post_disclosure_alpha_labels.parquet --output-dir outputs/pit_top_manager_follow_study --cohort-pit data_pit/sec/pit_top_manager_cohorts.parquet --follow-events-pit data_pit/sec/top_manager_13f_follow_events.parquet --horizons 21,63,126,252 --ranking-horizon 63 --ranking-lookback-days 1095 --cohort-refresh-months 6 --top-n 10 --min-manager-events 8 --history-years 8 2>&1 | tee outputs/full_rebuild_logs/pit_top_manager_follow_study.log || true
else
echo "[pit-top-manager] follow events already built during sec-enrich prerequisite; skipping duplicate run"
fi
python tools/run_autolearning_winner_challenger.py --latest-run outputs --autolearning-dir outputs/auto_learning_v2 --lifecycle-dir outputs/winner_lifecycle --onset-dir outputs/winner_onset_study --shakeout-dir outputs/shakeout_breakdown_study --cash-drag-dir outputs/main_cash_drag_replay --main-v2-replay-dir outputs/main_v2_backtest --concentrated-replay-dir outputs/concentrated_policy_replay --alpha-sprint-replay-dir outputs/alpha_sprint_backtest --position-risk-replay-dir outputs/position_aware_risk_replay --monster-lifecycle-replay-dir outputs/monster_lifecycle_replay --output-dir outputs/autolearning_winner_challenger 2>&1 | tee outputs/full_rebuild_logs/autolearning_winner_challenger.log || true
python tools/run_alphaops_policy_fusion.py --latest-run outputs --output-dir outputs/policy_fusion 2>&1 | tee outputs/full_rebuild_logs/policy_fusion.log || true
python tools/run_monster_recommendation_bridge.py --latest-run outputs --output-dir outputs/monster_recommendations 2>&1 | tee outputs/full_rebuild_logs/monster_recommendations.log || true
python tools/run_operating_snapshot.py --latest-run outputs --output-dir outputs/operating_snapshot 2>&1 | tee outputs/full_rebuild_logs/operating_snapshot.log || true
python tools/run_user_portfolio_reports.py --latest-run outputs --price-cache cache_prices --output-dir outputs/user_portfolio_reports 2>&1 | tee outputs/full_rebuild_logs/user_portfolio_reports.log || true
python tools/run_position_cleanup_review.py --latest-run outputs --output-dir outputs/operator_review 2>&1 | tee outputs/full_rebuild_logs/position_cleanup_review.log || true
BASELINE_RUN_ID="${GITHUB_RUN_ID:-local}"
python tools/run_daily_crisis_monitor.py --latest-run outputs --output-dir outputs/daily_crisis_monitor 2>&1 | tee outputs/full_rebuild_logs/daily_crisis_monitor.log || true
run_decision_cadence_review
python tools/run_portfolio_system_guard.py --latest-run outputs --output-dir outputs/portfolio_system_guard 2>&1 | tee outputs/full_rebuild_logs/portfolio_system_guard.log || true
run_patch_manifest
python tools/run_user_current_report.py --latest-run outputs --price-cache cache_prices --output-dir outputs/user_current --strict 2>&1 | tee outputs/full_rebuild_logs/user_current_report.log || true
run_patch_manifest

"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run profile-gated full rebuild sidecars")
    parser.add_argument(
        "--profile",
        choices=["operating_minimal", "official", "research_full", "phase_g_only"],
        default="operating_minimal",
        help="Sidecar generation profile from full_rebuild_manual.yml",
    )
    parser.add_argument("--artifact-profile", default=os.environ.get("ARTIFACT_PROFILE", "unknown"))
    parser.add_argument("--gdrive-sync-mode", default=os.environ.get("GDRIVE_SYNC_MODE", "unknown"))
    parser.add_argument("--portfolio-policy", choices=["production_baseline", "integrated_shadow", "market_leader_shadow", "approved_integrated", "alphaops_vnext_production"], default=os.environ.get("PORTFOLIO_POLICY", "alphaops_vnext_production"))
    parser.add_argument("--approved-target-policy-path", default=os.environ.get("APPROVED_TARGET_POLICY_PATH", "outputs/promotion_review/approved_target_policy.json"))
    parser.add_argument("--universe-mode", default=os.environ.get("UNIVERSE_MODE", "global_alpha_universe"))
    parser.add_argument("--backtest-years", default=os.environ.get("BACKTEST_YEARS", ""))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = os.environ.copy()
    env["SIDECAR_PROFILE"] = args.profile
    env["ARTIFACT_PROFILE"] = args.artifact_profile
    env["GDRIVE_SYNC_MODE"] = args.gdrive_sync_mode
    env["PORTFOLIO_POLICY"] = args.portfolio_policy
    env["APPROVED_TARGET_POLICY_PATH"] = args.approved_target_policy_path
    env["UNIVERSE_MODE"] = args.universe_mode
    env["BACKTEST_YEARS"] = str(args.backtest_years or "")
    if os.name == "nt":
        print("run_full_rebuild_sidecars.py is intended for the GitHub Linux runner", file=sys.stderr)
        return 2
    completed = subprocess.run(["bash", "-lc", SHELL_SCRIPT], env=env, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())

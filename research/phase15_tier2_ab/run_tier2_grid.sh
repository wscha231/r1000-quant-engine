#!/usr/bin/env bash
# Phase 15 Tier 2 A/B grid runner.
#
# Runs 6 cells sequentially with --ab-quick (~5min each = ~30min total):
#   A baseline                — all gates OFF
#   B 15-R1 trailing only     — early_scout 15% trailing stop
#   C 15-R2 revision only     — 2-month consecutive negative revision exit
#   D 15-R3 RS break only     — was top 15%, dropped to bottom 30%
#   E all 3 R stacked         — R1+R2+R3
#   F R + A1 stacked          — R1+R2+R3 + drop 3 negative features
#
# After each cell, snapshots backtest_metrics.json + concentrated_backtest_metrics.json
# to research/phase15_tier2_ab/cells/<cell>_*.json. Run analyze_tier2.py after to
# get a delta table.
#
# REQUIRES: phase4_modeling cache must already be built with current fingerprint
# (i.e. one slow rebuild after commit 7b9dad1 must have completed). Otherwise
# every cell will trigger ML rebuild = 30min × 6 = 3 hours.
#
# Usage:
#   bash research/phase15_tier2_ab/run_tier2_grid.sh
set -e

cd "$(dirname "$0")/../.."  # to repo root
mkdir -p research/phase15_tier2_ab/cells

run_cell() {
    local name="$1"; shift
    local envs="$@"
    echo "=== [$name] $envs ==="
    eval "$envs PHASE_PHASE11_MULTIBAGGER_ENABLED=0 py -3 run_local.py --no-collector --ab-quick" > "/tmp/tier2_${name}.log" 2>&1
    cp "/g/내 드라이브/r1000_top30_institutional/outputs/backtest_metrics.json" \
       "research/phase15_tier2_ab/cells/${name}_backtest_metrics.json"
    cp "/g/내 드라이브/r1000_top30_institutional/outputs/concentrated_backtest_metrics.json" \
       "research/phase15_tier2_ab/cells/${name}_concentrated_backtest_metrics.json" 2>/dev/null || true
    echo "  done -> cells/${name}_*"
}

run_cell A_baseline ""
run_cell B_r1_only "PHASE_PHASE15_R1_TRAILING_ENABLED=1"
run_cell C_r2_only "PHASE_PHASE15_R2_REVISION_BREAK_ENABLED=1"
run_cell D_r3_only "PHASE_PHASE15_R3_RS_BREAK_ENABLED=1"
run_cell E_all_r   "PHASE_PHASE15_R1_TRAILING_ENABLED=1 PHASE_PHASE15_R2_REVISION_BREAK_ENABLED=1 PHASE_PHASE15_R3_RS_BREAK_ENABLED=1"
run_cell F_r_plus_a1 "PHASE_PHASE15_R1_TRAILING_ENABLED=1 PHASE_PHASE15_R2_REVISION_BREAK_ENABLED=1 PHASE_PHASE15_R3_RS_BREAK_ENABLED=1 PHASE_PHASE15_A1_DROP_NEGATIVE_FEATURES_ENABLED=1"

echo "ALL TIER 2 CELLS DONE. Run analyze_tier2.py for delta table."

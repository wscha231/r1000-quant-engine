#!/bin/bash
# Overnight full pipeline test.
# Runs in background - logs to /tmp/overnight_{timestamp}.log
set -e

cd /mnt/h/codex/tmp_r1000_quant_engine 2>/dev/null || cd H:/codex/tmp_r1000_quant_engine

TS=$(date +%Y%m%d_%H%M%S)
LOG="/tmp/overnight_${TS}.log"

echo "=== OVERNIGHT FULL TEST START $(date) ===" > "$LOG"
echo "" >> "$LOG"

echo "[STEP 1/5] Validate system (quick)..." >> "$LOG"
py -3 tests/validate_system.py --quick >> "$LOG" 2>&1 || echo "VALIDATION WARNINGS" >> "$LOG"
echo "" >> "$LOG"

echo "[STEP 2/5] Fresh R1000 scanner (top 150)..." >> "$LOG"
py -3 -u aggressive/scanner.py --universe r1000 --min-score 50 --top 150 --dry-run >> "$LOG" 2>&1 || echo "SCAN ERROR" >> "$LOG"
echo "" >> "$LOG"

echo "[STEP 3/5] Rebuild unified universe..." >> "$LOG"
py -3 -u r1000_unified_universe.py >> "$LOG" 2>&1 || echo "UNIFY ERROR" >> "$LOG"
echo "" >> "$LOG"

echo "[STEP 4/5] Run all 3 advisors..." >> "$LOG"
py -3 -u r1000_rebalance_advisor.py --scored-csv "G:/내 드라이브/r1000_top30_institutional/outputs/scored_unified.csv" >> "$LOG" 2>&1 || echo "V1 ERROR" >> "$LOG"
py -3 -u r1000_rebalance_advisor_v2.py --use-cached-scanner >> "$LOG" 2>&1 || echo "V2 ERROR" >> "$LOG"
py -3 -u r1000_rebalance_advisor_v3.py >> "$LOG" 2>&1 || echo "V3 ERROR" >> "$LOG"
echo "" >> "$LOG"

echo "[STEP 5/5] Final validate + summary..." >> "$LOG"
py -3 tests/validate_system.py >> "$LOG" 2>&1 || echo "FINAL VALIDATE WARNINGS" >> "$LOG"
echo "" >> "$LOG"
echo "=== OVERNIGHT FULL TEST DONE $(date) ===" >> "$LOG"
echo "" >> "$LOG"
echo "Summary section:" >> "$LOG"
grep -E "PASS|FAIL|TOTAL|PROPOSED|EXIT|ADD|HOLD|Consensus" "$LOG" | tail -40 >> "$LOG"

echo "Overnight test complete. Log: $LOG"

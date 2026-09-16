#!/usr/bin/env python3
from __future__ import annotations
import subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
TESTS=[ROOT/"tests"/"test_sec_13f_manager_event_scorecard.py",ROOT/"tests"/"test_run_sec_13f_manager_event_scorecard.py"]
for opt in (False,True):
    for test in TESTS:
        cmd=[sys.executable]+(["-O"] if opt else [])+[str(test)]
        if subprocess.run(cmd,cwd=ROOT).returncode: raise SystemExit(1)
print("sec_13f_manager_event_scorecard_smoke: PASS (19 unique tests; normal and -O)")

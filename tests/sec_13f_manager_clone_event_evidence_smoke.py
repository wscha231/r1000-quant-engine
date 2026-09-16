#!/usr/bin/env python3
from __future__ import annotations
import subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
TESTS = [ROOT/"tests"/"test_sec_13f_manager_clone_event_evidence.py", ROOT/"tests"/"test_run_sec_13f_manager_clone_event_evidence.py"]
for opt in (False, True):
    for test in TESTS:
        cmd = [sys.executable] + (["-O"] if opt else []) + [str(test)]
        rc = subprocess.run(cmd, cwd=ROOT).returncode
        if rc: raise SystemExit(rc)
print("sec_13f_manager_clone_event_evidence_smoke: PASS (19 unique tests; normal and -O)")

"""Standalone compatibility entry for the existing registered macro suite."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from daily_crisis_monitor_long_crisis_smoke import (  # noqa: E402
    OrchestratorRegimeInputTests,
    run_orchestrator_regime_tests,
)


if __name__ == "__main__":
    run_orchestrator_regime_tests()
    print("orchestrator_regime_input_smoke: PASS")

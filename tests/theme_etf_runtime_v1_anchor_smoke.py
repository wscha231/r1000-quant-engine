from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_ROOT = ROOT / "research" / "theme_etf_runtime_v1"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from strict import compute_leadership  # noqa: E402


def main() -> None:
    rows = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(22):
        day = (start + timedelta(days=i)).date().isoformat()
        rows.append({"security_id": "SPY", "session": day, "available_at": day + "T23:00:00Z", "total_return_index": 100 + i})
        if i != 1:  # exact 20-session benchmark start anchor is unavailable
            rows.append({"security_id": "ETF1", "session": day, "available_at": day + "T23:00:00Z", "total_return_index": 100 + 2 * i})
    row = compute_leadership(rows, "SPY", decision_at="2026-01-22T23:30:00Z")[0]
    assert row["latest_session"] == "2026-01-22"
    assert row["return_20"] is None
    assert row["rs_log_20"] is None
    print("PASS benchmark_session_anchor")


if __name__ == "__main__":
    main()

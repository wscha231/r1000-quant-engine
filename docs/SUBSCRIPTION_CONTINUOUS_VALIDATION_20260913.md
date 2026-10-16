# Continuous operations validation follow-up / 2026-09-13

Parent published commit: cf6f3d794e9c81e699c281a5850361aa977c33c8.

The 40-test suite initially returned OK but emitted an ignored ResourceWarning
from the tamper-injection fixture's SQLite connection. An explicit closing context
now closes that connection; all 40 new plus 36 original tests pass normal/-O
with no ResourceWarning on stderr. This fixes a fixture resource leak, not trade math.

Inspect stderr as well as return codes. Repeated matrix runs are 76 unique tests,
not 304 independent tests. Exact-head CI and independent review remain separate
requirements. Synthetic tests and model-cycle replay are not realized performance.

No production, selector, canonical ledger or scheduler was changed. See
SUBSCRIPTION_CONTINUOUS_OPERATIONS_20260913.md for actual legacy audit counts,
source hashes, maturity rules and remaining source/calendar/storage trust boundaries.

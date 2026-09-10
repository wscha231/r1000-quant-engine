# Upstream market-session skip receipts

Daily Operating Selection Refresh publishes its read-only session-gate JSON
before account work. Publication failure stops subsequent work normally.

Sector Leadership may accept a skip only when both normal source artifact
families are absent, exactly one gate artifact exists, and the already verified
default-branch source run completed successfully. A partial transaction is
still an error.

The verifier binds artifact name, ID, run/head, compressed size and SHA-256;
accepts exactly one small JSON member; checks timestamps against that run
attempt; and recomputes the declared skip using the NYSE calendar and the
fixed 90-minute/18-hour session policy. Forced runs and READY receipts cannot
excuse missing normal artifacts. GitHub second-resolution creation timestamps
allow only their subsecond rounding interval.

The result is a separate `run287-sector-leadership-session-skip-*` diagnostic,
with ready=false and no orders, ledger or target changes. Its name excludes it
from the existing prior READY research artifact search. Existing failed runs,
missing receipts, bad hashes and normal artifact omissions remain blocked.

This change does not resume an old transaction, approve legacy quarantine,
modify accepted account state, or authorize a backtest or production action.

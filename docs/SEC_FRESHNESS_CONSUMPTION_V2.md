# SEC current source freshness — Form345 Source scope

Current source admission is separate from historical data-anchor research.
The existing collector refreshes submissions, reuses accession XML and parser
checkpoints, and parses newest filings across issuers before the older backlog.
A successful no-new-filing check differs from source failure or an unchecked cache.

Current merge requires hash-bound source/parser receipts, completed accessions
inside the decision window, and matching checked/index/parser CIK/ticker scope.
CSV, Parquet and table summaries share a generation. Partial writes revoke old
success. Joint owners, holdings, derivatives, amendments, codes and notes survive;
ambiguous owner fields and unavailable numeric values stay unknown.

The existing 20-issuer/500-filing workflow remains a bounded batch. Its coverage
receipt is never whole-universe coverage. For incremental expansion, pass the
existing collector a deduplicated, identity-reviewed fixed-universe/candidate
cohort in bounded batches; keep prior accession checkpoints. This PR does not
automatically approve or schedule a larger universe. Unresolved identities must
be recorded and reviewed before their source batch is admitted.

The daily workflow uses the existing collector's acceptance-based history start
at execution time minus 90 days and the nonnegative safety delay. This is a
conservative superset of the later decision window, so old backlog does not
consume the 500 new-parse budget before current filings. It does not erase
retained history. A batch above the cap remains incomplete and blocked until
resumed; a larger checked list does not imply complete parsing.

Form3 initial holdings and Form5 late/supplementary reports are retained as
evidence, excluded from the legacy Form4 signal calculation. P-code score names
are compatibility research proxies and do not certify public-market execution.
No score weights/live switches, A2/A3 Registry state, portfolio or orders change.

Main typed-event/reassessment changes remain with the existing Main owner.
No current real disclosure-to-A3 claim follows from these Source-only fixtures.

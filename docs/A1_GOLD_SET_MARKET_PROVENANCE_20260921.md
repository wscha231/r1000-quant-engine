# [PROJECT_HANDOFF] A1 Gold Set market provenance — 2026-09-21

Issue: #484
Base: d4c5090fe3b1ad150488dfda184d4e065796b0a5
Scope: A3 market-snapshot input integrity only.

## Problem

A3 Candidate Packet V1 already recomputed 20/60/120/240D log-relative RS, but the
market snapshot validator did not itself bind the reviewed snapshot to the raw
market-data bytes, explicit collection timing, or corporate-action quarantine state.
That gap could allow a syntactically valid snapshot to outrun the A1 evidence needed
by Issue #484.

## Contract added

A reviewed A3 market snapshot must now carry:
- observed_at, available_at and collected_at with causal ordering;
- source_identity;
- raw_artifact_id + raw_sha256 whose bytes resolve through the packet resolver;
- basis_review_status=REVIEWED;
- corporate_action_quarantine=false;
- explicit historical_pit_certified and validated_er_eligible booleans;
- positive price, completed session and exact 20/60/120/240D log-relative RS.

For PROVIDER_ADJUSTED_CLOSE_PROXY, validated_er_eligible must be false. The proxy
remains discovery/RS research evidence and cannot self-promote into validated ER.

## Boundaries

This change does not claim that current Yahoo/Alpaca or Korean captures are reviewed.
It strengthens the admission seam. Actual U.S. Gold Set capture must still archive
raw bytes and pass basis/corporate-action review; Korean evidence remains governed by
the KR engine's own source semantics. Missing or unresolved evidence stays blocked.

No selector, model, ER production, target book, portfolio, broker, order, fullrun or
production activation changes.

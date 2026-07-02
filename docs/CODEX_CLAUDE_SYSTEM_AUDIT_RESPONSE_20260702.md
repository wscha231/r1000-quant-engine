# Claude System Audit Response - 2026-07-02

## Verdict

Claude's sequencing is mostly right:

```text
governance -> reproducibility -> PIT universe -> rotation/replacement diagnosis -> EPS/guidance feed -> fullrun engineering -> longer-IS/era robustness
```

But one factual claim needs correction before it becomes an engineering task.

## What Is Already Reflected

Already reflected in the current branch:

- Cash-carry remains research accounting, not production.
- Broad bull-floor / gross-floor is closed.
- Broad hold-delay and cap-safe sizing are closed by fixed official-book replay.
- AI Capex taxonomy is diagnostic only.
- Fixed official-book A/B is acceptable; regenerated selection-side A/B remains diagnostic until control reproduction works.
- `pit_universe_label_clean=false` remains the hard production blocker.
- No fullrun is justified now.

## Correction To Claude W1

Claude wrote that there is no `random_state` / seed anywhere in the engine.

Current code does not support that exact claim.

Evidence:

```text
r1000_config.py:1852 random_seed: int = 42
r1000_pipeline.py:9969 Ridge(... random_state=cfg.random_seed)
r1000_pipeline.py:9974 LogisticRegression(... random_state=cfg.random_seed)
r1000_pipeline.py:10014 CatBoostRegressor(... random_seed=cfg.random_seed)
r1000_pipeline.py:10036 CatBoostClassifier(... random_seed=cfg.random_seed)
r1000_pipeline.py:10059 CatBoostRanker(... random_seed=cfg.random_seed)
r1000_pipeline.py:12560+ latest scoring path also uses cfg.random_seed
```

Corrected interpretation:

```text
The reproducibility problem is real, but the root cause is not simply "no seed."
The task should be target-book control reproduction root-cause analysis, not blind seed injection.
```

Possible remaining nondeterminism sources:

- candidate/input snapshot mismatch between official artifact and regenerated run
- SEC-enriched vs non-enriched candidate source mismatch
- appended operating date / cache freshness differences
- parallel CatBoost/thread nondeterminism in some environments
- unstable tie-breaking from sort/rank/groupby paths
- missing macro/crisis inputs in the local artifact snapshot

## Adopted Priority Changes

### W0 - Governance

Keep as user decision:

- Adopt `broker_ledger_next_close_cash_carry` as official research baseline?
- Keep zero-yield side-by-side?
- Production remains blocked until PIT universe evidence is clean.

### W1 - Reproducibility

Adopt with corrected wording.

Goal:

```text
same inputs -> identical target book
```

Acceptance:

- official-only dates = 0
- generated-only dates = 0
- ticker mismatch dates = 0
- max weight delta near zero

Do not start regenerated selection-side A/B before this passes.

### W2 - PIT Universe Membership

Adopt.

This remains the production path:

```text
r1000_config.py:1803 universe_fallback_mode = "current_constituents"
```

Existing tools:

```text
tools/build_pit_membership_by_month.py
tools/run_pit_membership_audit.py
tools/run_universe_health_audit.py
```

The blocker is sourcing real historical membership, not audit plumbing.

### W3 - Rotation / Replacement Quality

Adopt as the next alpha direction, but with strict gating.

Need:

- leadership rotation latency audit by era
- replacement-quality audit against rejected/capped candidate logs
- one narrow default-OFF hook at most

No broad timing/sizing/gross-floor variants.

### W4 - PIT EPS / Guidance Feed

Adopt.

Current `actual_results_score` is not a true analyst estimate/guidance feed. It
can support diagnostics, but it should not be the final confirmation layer.

### W5 - Fullrun Completion Engineering

Adopt before the next fullrun.

Do not dispatch another 5-6h fullrun until:

- cheap replay-stage candidate passes
- fullrun timeout/sidecar split/fail-fast plan is ready
- user explicitly approves

### W6 - Overfit / Longer IS

Adopt later, after W1 and W2.

The OOS-heavy right-tail remains the real robustness wall.

### W7 - Forward Service Readiness

Adopt now as a separate service track.

The user-facing service question is different from the backtest question. The
current holdings are process outputs, not a guarantee that historical CAGR/MDD
will continue. A public site needs a freeze-date forward paper ledger,
expectation bands, alpha-decay alarms, immutable snapshot hashes, data-license
review, and regulatory/disclosure review.

Implemented seed:

```text
docs/CODEX_FORWARD_SERVICE_READINESS_20260702.md
tools/run_forward_service_snapshot.py
tests/forward_service_snapshot_smoke.py
outputs/forward_service_28436307420/
```

Real artifact result:

```text
snapshot_hash = 788dffa178daf31e97853b6f9927dec6809fb44efabcf6e6cf834d568b85337b
freeze_date = 2026-06-29
public_display_allowed = false
production_activation_allowed = false
```

This is not an alpha lever and does not justify a fullrun. Its value is starting
the forward record now so future service claims can be audited against what was
shown before the returns happened.

## Concrete Next Plan

1. Ask Fable 5 the packet in `docs/CODEX_FABLE5_REVIEW_PACKET_20260702.md`, now updated with this corrected W1 interpretation.
2. Start W1 root-cause work:
   - compare official vs regenerated input hashes;
   - isolate candidate source, cache manifest, SEC-enriched candidate, append date, and macro/crisis inputs;
   - produce a deterministic control-repro failure table.
3. In parallel, prepare W3 rotation/replacement-quality audit, but do not turn it into a hook until W1's control reproduction problem is understood.
4. Keep W2 PIT membership as the production-critical data track.
5. Start W7 forward paper ledger tracking from the hash-stamped snapshot, but
   keep website/public display blocked until readiness gates clear.

## Bottom Line

Claude's strategic order is good. The main correction is that the engine is
already seeded in major ML paths, so the reproducibility task must be framed as
a control-reproduction investigation rather than a simple seed patch.

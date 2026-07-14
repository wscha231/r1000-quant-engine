# Full rebuild schedule governance result - 2026-07-14

## Decision

The long-running full rebuild is manual-only. No cron, scheduled event, or
other automatic trigger may start it. A manual dispatch must fail before any
checkout, dependency installation, collection, replay, artifact upload, Drive
sync, or repository write unless the reviewed commit SHA, frozen input-manifest
SHA-256, expected runner minutes, and exact approval phrase are supplied.

Research approval does not authorize production or live trading.

## Incident evidence

GitHub Actions run `29249021773` started from a `schedule` event on
2026-07-13 at 12:12:59 UTC. The workflow reached the full rebuild command with
blank dispatch-only values and failed because `--fast-mode ''` was invalid.
The run had already performed runner cleanup, checkout, dependency setup, SEC
bulk refresh, cache restore, preflights, and Drive restore before that failure.

The workflow also ran diagnostic sidecars, uploaded minimal artifacts, tried a
Drive sync, and reached its repository commit step. This was an automatic
execution path inconsistent with the Run287 rule that fullrun requires a
separate user approval after hashes and expected cost are reported.

## Fix

- remove the weekly `schedule` trigger;
- retain `workflow_dispatch` as the only trigger;
- require the exact phrase `FULLRUN_APPROVED`;
- require the dispatched `GITHUB_SHA` to equal the reviewed 40-hex commit SHA;
- require a 64-hex frozen source-manifest SHA-256;
- require reviewed expected runner minutes between 1 and 350;
- reject blank or invalid core dispatch inputs before expensive steps;
- block `alphaops_vnext_production` under the current research-only scope;
- serialize manual full rebuilds without cancelling a running approved job.

## Validation boundary

Only static/smoke and PR validation may be run for this governance change. The
full rebuild itself must not be dispatched as a test. Existing untracked
outputs and downloaded artifacts must remain untouched.

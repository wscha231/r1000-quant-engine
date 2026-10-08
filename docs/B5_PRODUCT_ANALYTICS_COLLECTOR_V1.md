# B5 Product Analytics Collector V1 — PREPARE_ONLY / NO_DEPLOY

Issue: #588

Status: `PREPARED_NOT_DEPLOYED`

This is a B-side product-analytics transport preparation only. It does not alter
Leadership, RS, Fundamentals, ER/Thesis, ranking, portfolio targets, broker/paper
books, publication authority, or any A-side investment meaning. It also does not
modify `docs/public/**`, PR #585, browser instrumentation, GitHub secrets, or GCP
resources.

## Architecture

- frontend remains the existing static GitHub Pages surface;
- collector runtime target: Cloud Run in `asia-northeast3` (Seoul);
- raw store target: a **dedicated named Firestore Native-mode database** in
  `asia-northeast3` (Seoul), not `(default)`;
- collection: `product_analytics_events_v1`;
- endpoint: `POST /v1/events`;
- canonical event/schema/privacy validation reuses
  `data_static/product_analytics_event_contract_v1.json` and
  `tools/aggregate_product_analytics.py`.

Cloud Run and Firestore both currently list `asia-northeast3` as Seoul. This
must be re-verified from deployed resource metadata before production traffic.

## Runtime contract

Success:
- `202 Accepted` for a new valid event;
- idempotent `202 Accepted` for an exact duplicate `event_id`.

Fail closed:
- `400` malformed JSON, schema violation, Firestore-incompatible document ID,
  unsupported content type, or future client timestamp;
- `403` inactive consent or disallowed/missing Origin;
- `409` conflicting reuse of an existing `event_id`;
- `413` request body over the configured limit;
- `429` per-instance bounded rate limit;
- `503` invalid runtime configuration or persistence failure.

Responses never echo `event_id` or `session_id`.

## Privacy and identity

- analytics is opt-in only; inactive consent is rejected;
- no persistent anonymous ID or user ID;
- only the B5-P01a required/optional field allowlist is stored;
- no source IP, forwarded IP, user-agent, full referrer, free text, email,
  phone, account, broker, position or P&L fields are read into the event record;
- no autocapture, session replay, ad tracking or cross-site tracking;
- CORS is an exact browser-origin allowlist and is explicitly **not**
  authentication;
- application code does not emit request/access logs. Cloud Run request logs are
  platform-generated and therefore require a Cloud Logging exclusion before any
  production traffic.

Cloud Run automatically creates request logs; Google Cloud documents that these
can be controlled with Cloud Logging exclusions. The exclusion must be verified
against the actual collector service before enabling browser transmission.

## Firestore idempotency and IAM

The adapter first performs an atomic document `create` using exact `event_id`
as the document key. Firestore-reserved document IDs (`.`, `..`, or
`__...__`) are rejected before persistence. Only when the document already exists does it read that
single document to distinguish an exact duplicate from a conflicting duplicate.
It does not query, list, update or delete analytics documents.

This means the runtime identity needs the equivalent of:
- `datastore.entities.create`;
- `datastore.entities.get`.

Do not grant `roles/datastore.user` merely for convenience if a narrower custom
role can be used. Bind the runtime only to the dedicated analytics database or
otherwise prove it cannot access unrelated R1000 data. Exact provider/IAM scope
must be verified before deployment.

## Retention

Each new document receives:
- `server_received_at_utc`;
- `expires_at = server_received_at_utc + 89 days`.

The intended Firestore TTL field is `expires_at`. Google Cloud states that TTL
deletion is not instantaneous and is typically completed within 24 hours after
expiration. Using day 89 as the expiration target provides a one-day operational
margin toward the <=90-day target, but this is **not a hard deletion guarantee**.
Before production, either accept and disclose this behavior or add a verified
scheduled purge if strict deletion by day 90 is required.

Identifier-free daily aggregates remain <=13 months. D1/D7/D30 remain
`NOT_AVAILABLE`; this task creates no signup or persistent user identity.

## Required runtime configuration

All are deployment-time inputs; no credential values belong in GitHub:

- `GOOGLE_CLOUD_PROJECT`
- `R1000_ANALYTICS_ALLOWED_ORIGINS` — comma-separated HTTPS origins, no wildcard
- `R1000_ANALYTICS_FIRESTORE_DATABASE` — dedicated named database, not default
- `R1000_ANALYTICS_FIRESTORE_LOCATION=asia-northeast3`
- `R1000_ANALYTICS_CLOUD_RUN_REGION=asia-northeast3`
- optional `R1000_ANALYTICS_MAX_BODY_BYTES` (default 16384)
- optional `R1000_ANALYTICS_RATE_PER_MINUTE` (default 120 per instance)
- optional `R1000_ANALYTICS_RAW_TTL_DAYS` (maximum 89)

The region environment variables are fail-closed runtime assertions, not proof of
actual resource placement. Deployment verification must query the real Cloud Run
and Firestore resource metadata.

## Deployment blockers

Do not deploy or send browser events until all are true:

1. PR #587 is merged/current.
2. Privacy policy/consent UI changes are separately approved.
3. Cloud Run service region is verified as exactly `asia-northeast3`.
4. Firestore database location is verified as exactly `asia-northeast3`.
5. A dedicated analytics database exists and runtime IAM cannot access unrelated
   R1000 data.
6. Cloud Logging request-log exclusion is configured and verified for the actual
   service; provider handling is disclosed.
7. Firestore TTL on `expires_at` is enabled and retention wording matches its
   asynchronous behavior, or a stricter purge path is approved.
8. Cloud Run min instances remains 0, max instances is capped, request-based
   billing is selected, and a budget alert exists.
9. Raw events cannot reach public GitHub, Pages, or public Actions artifacts.
10. `collector_endpoint`/frontend transmission remains disabled until the
    separate activation gate.
11. No persistent anonymous ID, user ID, signup/payment/CRM, session replay,
    autocapture, advertising or cross-site tracking is introduced.
12. No A-side, publisher, ranking, freshness, portfolio, broker or paper authority
    changes are bundled into collector activation.

## Prepared files

- `tools/product_analytics_collector/app.py`
- `tools/product_analytics_collector/firestore_store.py`
- `tools/product_analytics_collector/Dockerfile`
- `tools/product_analytics_collector/requirements.txt`
- `tests/product_analytics_collector_v1_smoke.py`
- `tools/product_analytics_collector/deploy.env.example`
- `tools/product_analytics_collector/iam_role.yaml`
- `tools/product_analytics_collector/predeploy_check.py`
- `tools/product_analytics_collector/render_deploy_plan.py`
- `docs/B5_PRODUCT_ANALYTICS_DEPLOY_RUNBOOK.md`

No deployment command is executed by this change.

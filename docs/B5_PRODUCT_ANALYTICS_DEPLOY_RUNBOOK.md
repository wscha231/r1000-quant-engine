# B5-P01b deployment runbook — prepared, not executed

Status: `PREDEPLOY_BLOCKED_FIRST_DEPLOY_NO_TRAFFIC / NO_GCP_MUTATION`

The current task stops before any GCP resource creation, image push, Cloud Run deployment, secret change, browser transmission, or public traffic.

## CI/runtime layout
Tier-1 sparse checkout includes `tools/` but not a new top-level `services/` path. The collector therefore lives at `tools/product_analytics_collector/` so CI and the Docker build consume the same code without changing the protected validation workflow.

## Target
- Cloud Run: `asia-northeast3` (Seoul)
- Artifact Registry: `asia-northeast3`
- Firestore Standard/Native named DB: `asia-northeast3`
- dedicated runtime service account
- custom Firestore role: database get + entity create/get only
- IAM condition limited to the named analytics DB
- TTL field: `expires_at`
- min instances 0, initial max 2, request-based billing
- private invocation is required; the first-deployment no-traffic requirement is
  **blocked** by the current SDK, as explained below

## Prepare variables
```bash
cp tools/product_analytics_collector/deploy.env.example /tmp/r1000-analytics.env
nano /tmp/r1000-analytics.env
```

## Read-only predeploy probe
```bash
python tools/product_analytics_collector/predeploy_check.py --env-file /tmp/r1000-analytics.env
```

## Render future deployment commands without executing them
```bash
python tools/product_analytics_collector/render_deploy_plan.py --env-file /tmp/r1000-analytics.env > /tmp/r1000-analytics-deploy-plan.sh
cat /tmp/r1000-analytics-deploy-plan.sh
```

The renderer prints review templates only. It emits an unconditional `exit 2`
before any GCP mutation because the current first-deploy contract cannot be
implemented. Do not remove this stop or execute the templates piecemeal.

## Verified first-deployment blocker (2026-10-08)

The official rapid-channel SDK is **588.0.0**. Its
`googlecloudsdk/command_lib/run/config_changes.py`, `NoTrafficChange.Adjust`,
rejects a service without an existing generation:
`--no-traffic not supported when creating a new service.`

Source: [official SDK component manifest](https://dl.google.com/dl/cloudsdk/channels/rapid/components-2.json).
Reviewed core archive: `components/google-cloud-sdk-core-20261002073740.tar.gz`;
SHA256: `6f5ed0f5bede78214b77968556113bae907fbee418ec4750a1727a69290e2c87`.

An absent service is required by this task's no-overwrite probe, so the printed
`--no-traffic` deployment template cannot be the first deployment. A separately
approved private bootstrap contract is required; no bootstrap, traffic change,
public access, or default-URL workaround is authorized here. Code integration
does not make the deployment `READY` while this blocker remains.

## Input and verification controls

- Required user inputs: `PROJECT_ID`, `BILLING_ACCOUNT_ID`, finite positive
  `BUDGET_AMOUNT_USD`, actual HTTPS `ALLOWED_ORIGINS`, and merged exact `DEPLOY_SHA`.
- Other values use `deploy.env.example` defaults: Seoul, named DB, initial max=2,
  body limit 16384 bytes, rate=120/minute/instance, TTL=89 days.
- Every resource probe and rendered GCP command explicitly selects the project.
  Permission errors, failed queries, malformed results, unknown placement/type,
  and existing resources requiring reuse review fail closed. CLI errors/metadata
  are summarized; raw stdout/stderr and credentials are not printed.
- `PREDEPLOY_READ_ONLY_OK` means metadata reads succeeded, not deployment approval;
  `deployment_status` still records the first-deploy blocker.
- Before a future build, source must be at `DEPLOY_SHA`, at repository root, with
  no tracked/untracked changes. Artifact Registry tags are immutable. Confirm
  Cloud Build's actual builder has push permission; none is granted by this task.
- Multiple origins stay in one Cloud Run environment value through gcloud's
  alternate dictionary delimiter (`^|^`), rather than being split into env keys.
- The logging exclusion uses the singular `--add-exclusion` flag, service name,
  resource type and request-log ID only. It precedes deployment; verify other
  project/ancestor sinks cannot retain the same request logs.
- Docker selects the finite-category `PrivacySafeLogger`; it discards Gunicorn
  access/error arguments and exception traces. Verify this logger remains selected
  in the private revision before any traffic; platform exclusions alone do not
  prevent IP/URI appearing in default Gunicorn container error logs.
- The budget command has project scope and 50/80/100% alerts. USD is valid only
  for a USD billing account. A different billing currency requires a separately
  reviewed currency-specific plan. Budget alerts alone are not a hard spend cap.
- Database IAM conditions restrict the dedicated DB, not individual collections.
  Reserve that DB exclusively for analytics; verify runtime access to unrelated
  databases is denied. Do not substitute `roles/datastore.user`.

## Official CLI and provider references

- [Firestore IAM methods/permissions](https://docs.cloud.google.com/firestore/native/docs/security/iam)
- [Per-database IAM conditions](https://docs.cloud.google.com/firestore/native/docs/manage-databases#configure_per-database_access_permissions)
- [Cloud Run deploy flags](https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy)
- [Dictionary escaping](https://docs.cloud.google.com/sdk/gcloud/reference/topic/escaping)
- [Logging sink exclusions](https://docs.cloud.google.com/sdk/gcloud/reference/logging/sinks/update)
- [Billing budget flags](https://docs.cloud.google.com/sdk/gcloud/reference/billing/budgets/create)
- [Cloud Build config/substitutions](https://docs.cloud.google.com/sdk/gcloud/reference/builds/submit)
- [Firestore TTL update](https://docs.cloud.google.com/sdk/gcloud/reference/firestore/fields/ttls/update)
- [Firestore asynchronous TTL](https://docs.cloud.google.com/firestore/native/docs/ttl)

## Mandatory post-private-deploy checks before public traffic
1. Cloud Run and Firestore both report `asia-northeast3`.
2. IAM is limited to the named analytics database and has no broad Datastore role.
3. TTL on `expires_at` is active.
4. Cloud Run request-log exclusion is narrowly configured for this service in Cloud Logging.
5. min=0, max cap, request-based billing and a budget alert are verified.
6. private endpoint contract tests pass and raw events never reach GitHub/public artifacts.
7. privacy/consent UI is separately approved.
8. D1/D7/D30 remain NOT_AVAILABLE.

Only a separate activation task may allow unauthenticated invocation, route traffic, set `collector_endpoint`, and enable frontend transmission.

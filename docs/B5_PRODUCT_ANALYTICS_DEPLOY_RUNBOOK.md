# B5-P01b deployment runbook — prepared, not executed

Status: `PREDEPLOY_PREPARED / NO_GCP_MUTATION`

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
- first deployment private and no-traffic

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

The rendered plan covers API enablement, Seoul Artifact Registry, Seoul Firestore, service account, custom conditional IAM, TTL, image build/push, and a private/no-traffic Cloud Run deployment.

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

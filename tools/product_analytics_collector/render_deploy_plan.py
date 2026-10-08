#!/usr/bin/env python3
from __future__ import annotations
import argparse, re, shlex, sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from tools.product_analytics_collector.app import valid_https_origin
SEOUL="asia-northeast3"
REQUIRED=("PROJECT_ID","BILLING_ACCOUNT_ID","BUDGET_AMOUNT_USD","DEPLOY_SHA","REGION","DATABASE_ID","ARTIFACT_REPOSITORY","SERVICE_NAME","SERVICE_ACCOUNT_NAME","CUSTOM_ROLE_ID","ALLOWED_ORIGINS","MAX_INSTANCES","MAX_BODY_BYTES","RATE_PER_MINUTE","RAW_TTL_DAYS")
def read_env(path: Path) -> dict[str,str]:
    values={}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line=raw.strip()
        if not line or line.startswith("#"): continue
        if "=" not in line: raise SystemExit("invalid env line")
        k,v=(x.strip() for x in line.split("=",1))
        if k not in REQUIRED or k in values: raise SystemExit("unknown or duplicate env key")
        values[k]=v
    missing=[k for k in REQUIRED if not values.get(k)]
    if missing: raise SystemExit("missing required values: "+",".join(missing))
    if values["REGION"]!=SEOUL: raise SystemExit("REGION must be asia-northeast3")
    patterns={
        "PROJECT_ID": r"[a-z][a-z0-9-]{4,28}[a-z0-9]",
        "BILLING_ACCOUNT_ID": r"[A-Fa-f0-9]{6}(?:-[A-Fa-f0-9]{6}){2}",
        "DATABASE_ID": r"[a-z][a-z0-9-]{2,61}[a-z0-9]",
        "ARTIFACT_REPOSITORY": r"[a-z][a-z0-9-]{0,61}[a-z0-9]",
        "SERVICE_NAME": r"[a-z][a-z0-9-]{0,47}[a-z0-9]",
        "SERVICE_ACCOUNT_NAME": r"[a-z][a-z0-9-]{4,28}[a-z0-9]",
        "CUSTOM_ROLE_ID": r"[A-Za-z0-9_.]{3,64}",
    }
    for k,pattern in patterns.items():
        if not re.fullmatch(pattern,values[k]): raise SystemExit("invalid "+k)
    if re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",values["DATABASE_ID"]): raise SystemExit("UUID-like database ID is forbidden")
    origins=[x.strip() for x in values["ALLOWED_ORIGINS"].split(",")]
    if not origins or any(not valid_https_origin(x) for x in origins): raise SystemExit("exact HTTPS origins without wildcards required")
    values["ALLOWED_ORIGINS"]=",".join(origins)
    if len(values["DEPLOY_SHA"])!=40 or any(c not in "0123456789abcdef" for c in values["DEPLOY_SHA"].lower()): raise SystemExit("DEPLOY_SHA must be an exact 40-char git SHA")
    values["DEPLOY_SHA"]=values["DEPLOY_SHA"].lower()
    for k,maximum in (("MAX_INSTANCES",2),("MAX_BODY_BYTES",65536),("RATE_PER_MINUTE",10000),("RAW_TTL_DAYS",89)):
        raw=values[k]
        if not raw.isascii() or not raw.isdecimal() or len(raw)>6 or not 1<=int(raw)<=maximum: raise SystemExit("invalid "+k)
    try:
        budget=Decimal(values["BUDGET_AMOUNT_USD"])
    except InvalidOperation as exc:
        raise SystemExit("BUDGET_AMOUNT_USD must be numeric") from exc
    if not budget.is_finite() or budget<=0 or budget.as_tuple().exponent < -2 or budget.adjusted()>12: raise SystemExit("BUDGET_AMOUNT_USD must be finite, positive, and in USD cents")
    values["BUDGET_AMOUNT_USD"]=format(budget,"f")
    return values
def q(v:str)->str: return shlex.quote(v)
def render_plan(v:dict[str,str])->list[str]:
    project=v["PROJECT_ID"]; billing=v["BILLING_ACCOUNT_ID"]; region=v["REGION"]; db=v["DATABASE_ID"]; repo=v["ARTIFACT_REPOSITORY"]; service=v["SERVICE_NAME"]; sa_name=v["SERVICE_ACCOUNT_NAME"]; sa=f"{sa_name}@{project}.iam.gserviceaccount.com"; role=v["CUSTOM_ROLE_ID"]
    image=f"{region}-docker.pkg.dev/{project}/{repo}/{service}:{v['DEPLOY_SHA']}"
    envs="^|^"+"|".join((f"GOOGLE_CLOUD_PROJECT={project}",f"R1000_ANALYTICS_ALLOWED_ORIGINS={v['ALLOWED_ORIGINS']}",f"R1000_ANALYTICS_FIRESTORE_DATABASE={db}",f"R1000_ANALYTICS_FIRESTORE_LOCATION={region}",f"R1000_ANALYTICS_CLOUD_RUN_REGION={region}",f"R1000_ANALYTICS_MAX_BODY_BYTES={v['MAX_BODY_BYTES']}",f"R1000_ANALYTICS_RATE_PER_MINUTE={v['RATE_PER_MINUTE']}",f"R1000_ANALYTICS_RAW_TTL_DAYS={v['RAW_TTL_DAYS']}"))
    condition=f'resource.name=="projects/{project}/databases/{db}"'
    log_filter=f'resource.type="cloud_run_revision" AND resource.labels.service_name="{service}" AND logName="projects/{project}/logs/run.googleapis.com%2Frequests"'
    exclusion=f"name=r1000_analytics_request_logs,description=Exclude collector request logs from _Default storage,filter={log_filter}"
    commands=[
      "# MUTATING COMMANDS BELOW — REVIEW, THEN RUN MANUALLY ONLY AFTER APPROVAL.",
      "set -euo pipefail",
      "# BLOCKED_FIRST_DEPLOY_NO_TRAFFIC: SDK 588.0.0 rejects --no-traffic for a new service.",
      'echo "BLOCKED: approve a separate private bootstrap contract before any GCP mutation" >&2; exit 2',
      f'test "$(git rev-parse HEAD)" = {q(v["DEPLOY_SHA"])} || {{ echo "DEPLOY_SHA mismatch" >&2; exit 2; }}',
      'test -z "$(git rev-parse --show-prefix)" || { echo "Use repository root" >&2; exit 2; }',
      'test -z "$(git status --porcelain)" || { echo "Build requires clean tracked and untracked source" >&2; exit 2; }',
      "# USD budget requires a USD billing account; otherwise STOP for a reviewed currency-specific plan.",
      "gcloud services enable run.googleapis.com firestore.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com logging.googleapis.com iam.googleapis.com billingbudgets.googleapis.com",
      f"gcloud artifacts repositories create {q(repo)} --repository-format=docker --location={q(region)} --description=\"R1000 B5 analytics collector images\" --immutable-tags",
      f"gcloud firestore databases create --database={q(db)} --location={q(region)} --edition=standard --type=firestore-native --delete-protection",
      f"gcloud iam service-accounts create {q(sa_name)} --display-name=\"R1000 analytics collector\"",
      f"gcloud iam roles create {q(role)} --project={q(project)} --file=tools/product_analytics_collector/iam_role.yaml",
      f"gcloud projects add-iam-policy-binding {q(project)} --member={q('serviceAccount:'+sa)} --role={q('projects/'+project+'/roles/'+role)} --condition={q('expression='+condition+',title=r1000_analytics_database_only,description=Only the dedicated analytics database')}",
      f"gcloud firestore fields ttls update expires_at --collection-group=product_analytics_events_v1 --database={q(db)} --enable-ttl",
      f"gcloud billing budgets create --billing-account={q(billing)} --display-name={q('R1000 analytics '+project)} --budget-amount={q(v['BUDGET_AMOUNT_USD']+'USD')} --filter-projects={q('projects/'+project)} --threshold-rule=percent=0.5 --threshold-rule=percent=0.8 --threshold-rule=percent=1.0",
      f"gcloud logging sinks update _Default --project={q(project)} --add-exclusion={q(exclusion)}",
      "# STOP unless builder push permission and all other/ancestor log sinks have been reviewed.",
      f"gcloud builds submit . --region={q(region)} --config=tools/product_analytics_collector/cloudbuild.yaml --substitutions={q('_IMAGE='+image)}",
      "# The following deployment template is for an existing, separately reviewed service only; it cannot create the first service.",
      f"gcloud run deploy {q(service)} --image={q(image)} --region={q(region)} --service-account={q(sa)} --min=0 --max={q(v['MAX_INSTANCES'])} --cpu-throttling --set-env-vars={q(envs)} --no-allow-unauthenticated --no-traffic",
      "# STOP: verify region/IAM/TTL/log exclusion/budget/private endpoint before public activation."
    ]
    return [c if not c.startswith("gcloud ") or " --project=" in c else c+f" --project={q(project)}" for c in commands]
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--env-file",type=Path,required=True); a=p.parse_args()
    print("\n".join(render_plan(read_env(a.env_file)))); return 0
if __name__=="__main__": raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations
import argparse, shlex
from pathlib import Path
SEOUL="asia-northeast3"
REQUIRED=("PROJECT_ID","BILLING_ACCOUNT_ID","REGION","DATABASE_ID","ARTIFACT_REPOSITORY","SERVICE_NAME","SERVICE_ACCOUNT_NAME","CUSTOM_ROLE_ID","ALLOWED_ORIGINS","MAX_INSTANCES","MAX_BODY_BYTES","RATE_PER_MINUTE","RAW_TTL_DAYS")
def read_env(path: Path) -> dict[str,str]:
    values={}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line=raw.strip()
        if not line or line.startswith("#"): continue
        if "=" not in line: raise SystemExit(f"invalid env line: {raw}")
        k,v=line.split("=",1); values[k.strip()]=v.strip()
    missing=[k for k in REQUIRED if not values.get(k)]
    if missing: raise SystemExit("missing required values: "+",".join(missing))
    if values["REGION"]!=SEOUL: raise SystemExit("REGION must be asia-northeast3")
    if values["DATABASE_ID"]=="(default)": raise SystemExit("dedicated named Firestore database required")
    if any(x.strip()=="*" for x in values["ALLOWED_ORIGINS"].split(",")): raise SystemExit("wildcard origin is forbidden")
    return values
def q(v:str)->str: return shlex.quote(v)
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--env-file",type=Path,required=True); a=p.parse_args(); v=read_env(a.env_file)
    project=v["PROJECT_ID"]; region=v["REGION"]; db=v["DATABASE_ID"]; repo=v["ARTIFACT_REPOSITORY"]; service=v["SERVICE_NAME"]; sa_name=v["SERVICE_ACCOUNT_NAME"]; sa=f"{sa_name}@{project}.iam.gserviceaccount.com"; role=v["CUSTOM_ROLE_ID"]
    image=f"{region}-docker.pkg.dev/{project}/{repo}/{service}:DEPLOY_SHA"
    envs=f"GOOGLE_CLOUD_PROJECT={project},R1000_ANALYTICS_ALLOWED_ORIGINS={v['ALLOWED_ORIGINS']},R1000_ANALYTICS_FIRESTORE_DATABASE={db},R1000_ANALYTICS_FIRESTORE_LOCATION={region},R1000_ANALYTICS_CLOUD_RUN_REGION={region},R1000_ANALYTICS_MAX_BODY_BYTES={v['MAX_BODY_BYTES']},R1000_ANALYTICS_RATE_PER_MINUTE={v['RATE_PER_MINUTE']},R1000_ANALYTICS_RAW_TTL_DAYS={v['RAW_TTL_DAYS']}"
    condition=f'resource.name=="projects/{project}/databases/{db}"'
    commands=[
      "# MUTATING COMMANDS BELOW — REVIEW, THEN RUN MANUALLY ONLY AFTER APPROVAL.",
      f"gcloud config set project {q(project)}",
      "gcloud services enable run.googleapis.com firestore.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com logging.googleapis.com iam.googleapis.com",
      f"gcloud artifacts repositories create {q(repo)} --repository-format=docker --location={q(region)} --description=\"R1000 B5 analytics collector images\"",
      f"gcloud firestore databases create --database={q(db)} --location={q(region)} --edition=standard --type=firestore-native --delete-protection",
      f"gcloud iam service-accounts create {q(sa_name)} --display-name=\"R1000 analytics collector\"",
      f"gcloud iam roles create {q(role)} --project={q(project)} --file=tools/product_analytics_collector/iam_role.yaml",
      f"gcloud projects add-iam-policy-binding {q(project)} --member={q('serviceAccount:'+sa)} --role={q('projects/'+project+'/roles/'+role)} --condition={q('expression='+condition+',title=r1000_analytics_database_only,description=Only the dedicated analytics database')}",
      f"gcloud firestore fields ttls update expires_at --collection-group=product_analytics_events_v1 --database={q(db)} --enable-ttl",
      "# Configure a narrowly scoped _Default logging exclusion after the private service exists and before production traffic.",
      f"gcloud builds submit --tag {q(image)} -f tools/product_analytics_collector/Dockerfile .",
      f"gcloud run deploy {q(service)} --image={q(image)} --region={q(region)} --service-account={q(sa)} --min=0 --max={q(v['MAX_INSTANCES'])} --cpu-throttling --set-env-vars={q(envs)} --no-allow-unauthenticated --no-traffic",
      "# STOP: verify region/IAM/TTL/log exclusion/budget/private endpoint before public activation."
    ]
    print("\n".join(commands)); return 0
if __name__=="__main__": raise SystemExit(main())

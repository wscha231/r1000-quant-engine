#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, shutil, subprocess
from pathlib import Path
from tools.product_analytics_collector.render_deploy_plan import read_env
SEOUL="asia-northeast3"
def run(*args:str)->tuple[int,str]:
    p=subprocess.run(list(args),capture_output=True,text=True,encoding="utf-8",errors="replace",check=False)
    return p.returncode,(p.stdout+p.stderr).strip()
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--env-file",type=Path,required=True); a=ap.parse_args()
    if shutil.which("gcloud") is None: raise SystemExit("gcloud not found; use Google Cloud Shell or install Google Cloud CLI")
    v=read_env(a.env_file); project=v["PROJECT_ID"]; region=v["REGION"]; db=v["DATABASE_ID"]; repo=v["ARTIFACT_REPOSITORY"]; service=v["SERVICE_NAME"]; sa=f"{v['SERVICE_ACCOUNT_NAME']}@{project}.iam.gserviceaccount.com"
    specs=[
      ("active_account",["gcloud","auth","list","--filter=status:ACTIVE","--format=value(account)"]),
      ("project",["gcloud","config","get-value","project"]),
      ("database",["gcloud","firestore","databases","describe","--database",db,"--format=json"]),
      ("artifact_repo",["gcloud","artifacts","repositories","describe",repo,"--location",region,"--format=json"]),
      ("service_account",["gcloud","iam","service-accounts","describe",sa,"--format=json"]),
      ("cloud_run_service",["gcloud","run","services","describe",service,"--region",region,"--format=json"]),
    ]
    checks=[]
    for name,cmd in specs:
        code,out=run(*cmd); checks.append({"name":name,"code":code,"output":out[:4000]})
    fatal=[]
    account=next(x for x in checks if x["name"]=="active_account")
    if account["code"]!=0 or not str(account["output"]).strip(): fatal.append("no_active_gcloud_account")
    pc=next(x for x in checks if x["name"]=="project")
    if pc["code"]!=0 or str(pc["output"]).strip()!=project: fatal.append("gcloud_project_mismatch")
    dc=next(x for x in checks if x["name"]=="database")
    if dc["code"]==0:
        try: payload=json.loads(str(dc["output"]))
        except json.JSONDecodeError: fatal.append("database_describe_not_json")
        else:
            loc=str(payload.get("locationId") or payload.get("location_id") or "")
            if loc and loc!=SEOUL: fatal.append("existing_database_not_seoul")
    sc=next(x for x in checks if x["name"]=="cloud_run_service")
    if sc["code"]==0: fatal.append("cloud_run_service_already_exists_review_before_deploy")
    print(json.dumps({"status":"BLOCKED" if fatal else "PREDEPLOY_READ_ONLY_OK","mutations_performed":[],"fatal":fatal,"checks":checks},indent=2,sort_keys=True))
    return 2 if fatal else 0
if __name__=="__main__": raise SystemExit(main())

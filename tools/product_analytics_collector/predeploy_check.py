#!/usr/bin/env python3
"""Read-only GCP metadata probes; never print raw CLI stdout or stderr."""
from __future__ import annotations
import argparse, json, shutil, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from tools.product_analytics_collector.render_deploy_plan import read_env
SEOUL="asia-northeast3"

def run(*args:str)->tuple[int,str]:
    try:
        p=subprocess.run(list(args),capture_output=True,text=True,encoding="utf-8",errors="replace",check=False,timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return 124,""
    return p.returncode,p.stdout.strip()

def probe(v:dict[str,str])->dict:
    project=v["PROJECT_ID"]; region=v["REGION"]; scope=["--project",project]
    specs=[
      ("active_account",["gcloud","auth","list","--filter=status:ACTIVE","--format=value(account)"],None),
      ("project",["gcloud","config","get-value","project"],None),
      ("budgets",["gcloud","billing","budgets","list","--billing-account",v["BILLING_ACCOUNT_ID"],*scope,"--format=json"],list),
      ("database",["gcloud","firestore","databases","list",*scope,"--format=json"],list),
      ("artifact_repo",["gcloud","artifacts","repositories","list","--location",region,*scope,"--format=json"],list),
      ("service_account",["gcloud","iam","service-accounts","list",*scope,"--format=json"],list),
      ("cloud_run_service",["gcloud","run","services","list","--region",region,*scope,"--format=json"],list),
      ("default_log_sink",["gcloud","logging","sinks","describe","_Default",*scope,"--format=json"],dict),
    ]
    checks=[]; payloads={}; fatal=[]
    for name,cmd,expected_type in specs:
        code,out=run(*cmd); summary={"name":name,"code":code}
        if code!=0:
            fatal.append(name+"_query_failed")
        elif expected_type is None:
            if name=="active_account":
                summary["active_account_present"]=bool(out.strip())
                if not out.strip(): fatal.append("no_active_gcloud_account")
            elif out.strip()!=project: fatal.append("gcloud_project_mismatch")
        else:
            try: payload=json.loads(out)
            except (ValueError,RecursionError): fatal.append(name+"_invalid_json")
            else:
                if not isinstance(payload,expected_type) or (isinstance(payload,list) and any(not isinstance(row,dict) for row in payload)):
                    fatal.append(name+"_invalid_shape")
                else:
                    valid=True
                    if expected_type is list:
                        for row in payload:
                            if name=="service_account": identity=row.get("email")
                            elif name=="cloud_run_service":
                                metadata=row.get("metadata") or {}
                                identity=(metadata.get("name") if isinstance(metadata,dict) else None) or row.get("name")
                            else: identity=row.get("name")
                            if not isinstance(identity,str) or not identity: valid=False
                    elif name=="default_log_sink":
                        valid=payload.get("name")=="_Default" and isinstance(payload.get("destination"),str) and bool(payload["destination"])
                    if not valid: fatal.append(name+"_missing_resource_identity")
                    else: payloads[name]=payload; summary["metadata_read"]=True
        checks.append(summary)
    db_name=f"projects/{project}/databases/{v['DATABASE_ID']}"
    for database in payloads.get("database",[]):
        if database.get("name")==db_name:
            if database.get("locationId")!=SEOUL: fatal.append("existing_database_not_verified_seoul")
            if database.get("type")!="FIRESTORE_NATIVE": fatal.append("existing_database_not_verified_native")
            if database.get("databaseEdition","STANDARD")!="STANDARD": fatal.append("existing_database_not_standard")
            fatal.append("database_already_exists_review_before_create")
    for service in payloads.get("cloud_run_service",[]):
        metadata=service.get("metadata") or {}
        name=metadata.get("name") if isinstance(metadata,dict) else None
        if name==v["SERVICE_NAME"] or str(service.get("name","")).split("/")[-1]==v["SERVICE_NAME"]:
            fatal.append("cloud_run_service_already_exists_review_before_deploy")
    for repository in payloads.get("artifact_repo",[]):
        if str(repository.get("name","")).split("/")[-1]==v["ARTIFACT_REPOSITORY"]: fatal.append("artifact_repo_already_exists_review_before_create")
    sa=f"{v['SERVICE_ACCOUNT_NAME']}@{project}.iam.gserviceaccount.com"
    if any(account.get("email")==sa for account in payloads.get("service_account",[])): fatal.append("service_account_already_exists_review_before_create")
    return {"status":"BLOCKED" if fatal else "PREDEPLOY_READ_ONLY_OK","deployment_status":"BLOCKED_FIRST_DEPLOY_NO_TRAFFIC","mutations_performed":[],"fatal":fatal,"checks":checks}

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--env-file",type=Path,required=True); a=ap.parse_args(); v=read_env(a.env_file)
    if shutil.which("gcloud") is None:
        result={"status":"BLOCKED","mutations_performed":[],"fatal":["gcloud_not_found"],"checks":[]}
    else: result=probe(v)
    print(json.dumps(result,indent=2,sort_keys=True))
    return 2 if result["status"]=="BLOCKED" else 0
if __name__=="__main__": raise SystemExit(main())
